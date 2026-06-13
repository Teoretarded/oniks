"""sim/pantsir.py — Pantsir-S1 point-defense unit + controller.
(Pure pytest, GL-free)

Coverage (spec §4.2 + integration contract):
  - PANTSIR_57E6 SamDef in sim/arsenal.py has the expected key attributes.
  - Pantsir radar joins the player network (range dict correct, antenna height).
  - Detects an inbound hostile missile at 15 km; ignores one at 35 km (outside
    30 km radar range) and one beyond the radar horizon.
  - No track forms before TRACK_FORM_S of continuous visibility.
  - 57E6 launches within sustained-detection window with correct flags.
  - In-flight cap (PANTSIR_MAX_INFLIGHT) is respected.
  - Ammo and reload-timer gating prevent over-firing.
  - Gun engages inside GUN_RANGE_M only; stays silent against an untracked or
    far target.
  - A 57E6 actually intercepts a straight-flying Tomahawk-like target in a
    stepped sim: closest approach < fuse radius → target dead.
  - Dead Pantsir (alive=False) engages nothing.
  - A launched 57E6 is NOT is_hostile (cannot damage player base via the
    structure sweep filter).

Geometry note:
  The Pantsir is placed on the coastal ridge at (0, 160.6, -3000) — a high
  point in the terrain that gives unobstructed LOS to targets in the z>0
  (enemy-approach) direction.  The ridge position was measured with
  terrain_height_scalar and verified by terrain_blocks (tools/probe logic).
  Threats are placed at z > 0 approaching south-west (closing z<0) so the
  tests cross open sea / low terrain rather than the ridge behind the unit.
"""

import math

import numpy as np
import pytest

from sim.arsenal import PANTSIR_57E6
from sim.pantsir import (
    GUN_RANGE_M,
    MISSILE_RELOAD_S,
    PANTSIR_MAX_INFLIGHT,
    PANTSIR_RADAR_RANGES,
    PANTSIR_ANTENNA_M,
    SAM_MIN_RANGE_M,
    TRACK_FORM_S,
    Pantsir,
    PantsirDefenseController,
)
from sim.radar import RadarNetwork
from sim.sam import SamMissile

DT = 1.0 / 120.0

# Pantsir deployment position: on the coastal ridge at z=-3000 (terrain 160.6 m).
# Measured via terrain_height_scalar(0, -3000) = 160.6 m.
# Placing the unit HERE gives unobstructed LOS to all threats at z > 0 because
# the ridge itself is the highest terrain on the approach bearing — confirmed by
# terrain_blocks checks in probe scripts.
PANTSIR_POS = np.array([0.0, 160.6, -3_000.0], dtype=np.float64)

# Threat approach corridor: threats placed at z=12000 closing south (vel z<0).
# Distance from Pantsir: sqrt((12000-(-3000))^2) = 15 000 m — inside the 57E6
# max_range of 20 000 m and within the radar 30 000 m missile range.
THREAT_Z = 12_000.0
THREAT_ALT = 300.0      # m — well above terrain, clearly above min_intercept_alt


# ---------------------------------------------------------------------------
# Stub world
# ---------------------------------------------------------------------------

class _StubWorld:
    """Minimal world duck-type for the controller: missiles, events, sim_time.
    terrain_height_at returns -500 m everywhere (deep ocean — no LOS blocking
    for the SamMissile's own surface-impact check during the intercept test).
    The Pantsir radar uses world.generation.terrain_height_scalar (the real
    heightfield) for its LOS check, so the Pantsir position must have actual
    LOS to targets (guaranteed by PANTSIR_POS on the ridge above)."""

    def __init__(self):
        self.missiles = []
        self.events = []
        self.sim_time = 0.0

    @staticmethod
    def terrain_height_at(x, z):
        # Used by SamMissile._surface_at during the intercept step test.
        # Return deep-below-sea so the 57E6 never ground-impacts in mid-flight.
        return -500.0

    @staticmethod
    def surface_height_at(x, z):
        return -500.0


# ---------------------------------------------------------------------------
# Stub hostile missile
# ---------------------------------------------------------------------------

class _HostileMissile:
    """Synthetic inbound threat (straight-line ballistic).

    Duck-types the integration contract:
      is_hostile = True, is_air = True, radar_size = 'missile',
      pos / vel / prev_pos / alive / impact_pos / velocity().
    """

    is_hostile = True
    is_air = True
    radar_size = "missile"

    def __init__(self, pos, vel):
        self.pos = np.asarray(pos, dtype=np.float64).copy()
        self.vel = np.asarray(vel, dtype=np.float64).copy()
        self.prev_pos = self.pos.copy()
        self.alive = True
        self.impact_pos = None
        self._id = f"fake_{id(self):x}"

    @property
    def aircraft_id(self):
        return self._id

    def velocity(self):
        return self.vel

    def update(self, dt, world=None):
        if not self.alive:
            return
        np.copyto(self.prev_pos, self.pos)
        self.pos += self.vel * dt


# ---------------------------------------------------------------------------
# Stub structure
# ---------------------------------------------------------------------------

class _StubStructure:
    """Minimal structure for time-to-impact priority."""
    def __init__(self, pos):
        self.pos = np.asarray(pos, dtype=np.float64).copy()
        self.alive = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(ctrl, world, seconds, step_missiles=False):
    """Advance controller + optionally step missiles for ``seconds``."""
    steps = int(round(seconds / DT))
    for _ in range(steps):
        world.sim_time += DT
        if step_missiles:
            for m in list(world.missiles):
                if hasattr(m, "update"):
                    m.update(DT)
        ctrl.step(world, DT)


def _sams(world):
    return [m for m in world.missiles if isinstance(m, SamMissile)]


def _make_threat(pos_offset=(0.0, 0.0, 0.0), vel=(0.0, 0.0, -680.0)):
    """Return a closing threat at PANTSIR_POS + pos_offset."""
    pos = PANTSIR_POS + np.array([
        pos_offset[0],
        THREAT_ALT - PANTSIR_POS[1] + pos_offset[1],
        THREAT_Z - PANTSIR_POS[2] + pos_offset[2],
    ], dtype=np.float64)
    return _HostileMissile(pos, np.array(vel, dtype=np.float64))


# ===========================================================================
# 1. PANTSIR_57E6 SamDef sanity
# ===========================================================================

def test_pantsir_57e6_samdef_in_sams_registry():
    from sim.arsenal import SAMS
    assert "pantsir_57e6" in SAMS
    assert SAMS["pantsir_57e6"] is PANTSIR_57E6


def test_pantsir_57e6_key_attributes():
    d = PANTSIR_57E6
    assert d.max_range == 20_000.0, "spec §4.2: 20 km"
    assert d.min_intercept_alt == 5.0, "spec §4.2: sea-skimmer capable"
    assert d.max_intercept_alt == 15_000.0, "spec §4.2: 15 km ceiling"
    assert d.max_g == 40.0, "spec §4.2: very high agility"
    assert d.fuse_radius == 8.0, "tight point-defense fuse"
    # Mach 2.7 at ~900 m/s: the burnout delta-v must plausibly reach this.
    avg_mass = (d.launch_mass + (d.launch_mass - d.propellant_mass)) / 2.0
    dv = d.motor_thrust * d.motor_time / avg_mass
    assert dv > 800.0, f"motor delta-v {dv:.0f} m/s must exceed 800 m/s for Mach 2.7"
    assert d.eject_time < 0.5, "rail-eject: short clear delay (not a ballistic hang)"


# ===========================================================================
# 2. Pantsir unit: radar joins the network
# ===========================================================================

def test_pantsir_radar_joins_network():
    net = RadarNetwork()
    p = Pantsir("p0", PANTSIR_POS, radar_network=net)
    assert p.radar in net.radars
    assert p.radar.radar_id == "p0_pantsir"
    assert p.radar.antenna_m == PANTSIR_ANTENNA_M


def test_pantsir_radar_ranges_correct():
    p = Pantsir("p1", PANTSIR_POS)
    assert p.radar.ranges["missile"] == PANTSIR_RADAR_RANGES["missile"]
    assert p.radar.ranges["fighter"] == PANTSIR_RADAR_RANGES["fighter"]
    assert p.radar.ranges["stealth"] == PANTSIR_RADAR_RANGES["stealth"]
    assert p.radar.ranges["ship"]    == PANTSIR_RADAR_RANGES["ship"]


# ===========================================================================
# 3. Detection / range / horizon gating
# ===========================================================================

def test_detects_hostile_at_15km():
    """Hostile at 15 km range, 300 m altitude — inside 30 km radar range with
    clear LOS over the ridge (the unit sits on the ridge top)."""
    p = Pantsir("p_det", PANTSIR_POS)
    # 15 km northeast of the Pantsir at 300 m altitude.
    target_pos = np.array([0.0, THREAT_ALT, PANTSIR_POS[2] + THREAT_Z],
                          dtype=np.float64)
    assert p.radar.detects(target_pos, "missile"), (
        "target at 15 km must be detected (within 30 km radar range, clear LOS)")


def test_ignores_hostile_beyond_radar_range():
    """A target 35 km from the Pantsir is outside the 30 km missile-class range."""
    p = Pantsir("p_far", PANTSIR_POS)
    target_pos = np.array([0.0, 1_000.0, PANTSIR_POS[2] + 35_000.0],
                          dtype=np.float64)
    assert not p.radar.detects(target_pos, "missile"), (
        "target at 35 km is outside 30 km range — must not be detected")


def test_ignores_target_below_radar_horizon():
    """A low-flying target 80 km away at 15 m AGL is below the radar horizon.

    4/3-earth horizon from PANTSIR_ANTENNA_M=5 above ridge (altitude ~165.6 m):
      d = 4120 * (sqrt(165.6) + sqrt(15)) ≈ 4120 * (12.87 + 3.87) ≈ 69 km
    80 km > 69 km horizon → below horizon → not detected.
    """
    from sim.radar import radar_horizon_m
    p = Pantsir("p_horiz", PANTSIR_POS)
    antenna_alt = p.radar.antenna_alt
    h_target = 15.0
    horizon = radar_horizon_m(antenna_alt, h_target)
    # Put the target 80 km away at 15 m altitude
    target_pos = np.array([0.0, h_target, PANTSIR_POS[2] + 80_000.0],
                          dtype=np.float64)
    rng_to_target = math.hypot(target_pos[0] - PANTSIR_POS[0],
                               target_pos[2] - PANTSIR_POS[2])
    assert rng_to_target > horizon, (
        f"80 km should exceed horizon {horizon:.0f} m — fix test geometry")
    assert not p.radar.detects(target_pos, "missile"), (
        "target beyond radar horizon must not be detected")


# ===========================================================================
# 4. Track formation and sustained-detection gating
# ===========================================================================

def test_no_launch_before_track_forms():
    """No 57E6 must be launched before TRACK_FORM_S of continuous visibility."""
    net = RadarNetwork()
    p = Pantsir("p_track", PANTSIR_POS, radar_network=net)
    ctrl = PantsirDefenseController([p])
    w = _StubWorld()
    threat = _make_threat()
    w.missiles.append(threat)
    _run(ctrl, w, TRACK_FORM_S - 0.5)
    assert _sams(w) == [], "must not launch before track forms"


def test_launch_after_track_forms():
    """57E6 launches after TRACK_FORM_S + epsilon of continuous visibility."""
    net = RadarNetwork()
    p = Pantsir("p_launch", PANTSIR_POS, radar_network=net)
    ctrl = PantsirDefenseController([p])
    w = _StubWorld()
    threat = _make_threat()
    w.missiles.append(threat)
    _run(ctrl, w, TRACK_FORM_S + 0.5)
    sams = _sams(w)
    assert len(sams) >= 1, "must launch a 57E6 after track forms"
    sam = sams[0]
    # Check integration flags
    assert sam.weapon is PANTSIR_57E6
    assert sam.launch_platform is p
    assert sam.launch_cinematic is False
    # 57E6 must NOT be is_hostile
    assert not getattr(sam, "is_hostile", False), (
        "57E6 must NOT be is_hostile — cannot damage player structures")
    assert p.missile_ammo == 11


def test_launch_emits_pantsir_launch_event():
    net = RadarNetwork()
    p = Pantsir("p_evt", PANTSIR_POS, radar_network=net)
    ctrl = PantsirDefenseController([p])
    w = _StubWorld()
    threat = _make_threat()
    w.missiles.append(threat)
    _run(ctrl, w, TRACK_FORM_S + 0.5)
    kinds = [k for k, _ in w.events]
    assert "pantsir_launch" in kinds, "launch must emit pantsir_launch event"


# ===========================================================================
# 5. In-flight cap
# ===========================================================================

def test_inflight_cap_respected():
    """At most PANTSIR_MAX_INFLIGHT 57E6s may be in flight simultaneously."""
    net = RadarNetwork()
    p = Pantsir("p_cap", PANTSIR_POS, missile_ammo=12, radar_network=net)
    ctrl = PantsirDefenseController([p])
    w = _StubWorld()
    threat = _make_threat()
    w.missiles.append(threat)
    # Zero the reload timer every step so reload is never the gating factor.
    for _ in range(int(30.0 / DT)):
        w.sim_time += DT
        p._reload_timer = 0.0
        ctrl.step(w, DT)
    # Launched SAMs are never stepped so all stay in flight.
    assert len(_sams(w)) == PANTSIR_MAX_INFLIGHT, (
        f"in-flight cap must be exactly {PANTSIR_MAX_INFLIGHT}")
    assert p.missile_ammo == 12 - PANTSIR_MAX_INFLIGHT


# ===========================================================================
# 6. Ammo and reload gating
# ===========================================================================

def test_ammo_exhaustion_stops_launches():
    """With ammo=2 exactly two rounds fire regardless of elapsed time."""
    net = RadarNetwork()
    p = Pantsir("p_ammo", PANTSIR_POS, missile_ammo=2, radar_network=net)
    ctrl = PantsirDefenseController([p])
    w = _StubWorld()
    threat = _make_threat()
    w.missiles.append(threat)
    for _ in range(int(20.0 / DT)):
        w.sim_time += DT
        p._reload_timer = 0.0
        ctrl.step(w, DT)
    assert len(_sams(w)) == 2, "exactly 2 rounds must fire (ammo cap)"
    assert p.missile_ammo == 0


def test_reload_paces_launches():
    """Default 1.5 s reload paces launches: one round in first 2 s, then
    at most one more per MISSILE_RELOAD_S interval.

    Timeline:
      ~0.8 s: TRACK_FORM_S elapsed → shot 1 fires, reload_timer = 1.5 s
      ~2.3 s: reload clears → shot 2 fires, reload_timer = 1.5 s
      ~3.8 s: reload clears → shot 3 fires (hits PANTSIR_MAX_INFLIGHT=3 cap)

    So 2 s → exactly 1 round; 4 s → 3 rounds (3 = PANTSIR_MAX_INFLIGHT cap).
    The test verifies the reload PACES launches (not instant salvo), not a
    fixed count.
    """
    net = RadarNetwork()
    p = Pantsir("p_pace", PANTSIR_POS, radar_network=net)
    ctrl = PantsirDefenseController([p])
    w = _StubWorld()
    threat = _make_threat()
    w.missiles.append(threat)
    # At 2 s exactly one round has fired (reload timer prevents the second).
    _run(ctrl, w, 2.0)
    count_2s = len(_sams(w))
    assert count_2s == 1, "exactly one shot in first 2 s (reload pacing)"
    # After another 2 s (total 4 s), at least one more shot fires;
    # exact count bounded by reload cadence and PANTSIR_MAX_INFLIGHT=3.
    _run(ctrl, w, 2.0)
    count_4s = len(_sams(w))
    assert count_4s > count_2s, "reload must allow additional shots by 4 s"
    assert count_4s <= PANTSIR_MAX_INFLIGHT, "in-flight cap must not be exceeded"


# ===========================================================================
# 7. Gun engagement
# ===========================================================================

class _AlwaysKillRng:
    """rng whose kill roll always succeeds and integers() returns 0."""
    def random(self):
        return 0.0
    def integers(self, *a, **kw):
        return 0


def test_gun_engages_inside_4km():
    """A tracked target at 2 km must draw gun fire (pantsir_gun event).
    SAM channel is disabled (missile_ammo=0) to isolate the gun."""
    net = RadarNetwork()
    rng = _AlwaysKillRng()
    p = Pantsir("p_gun", PANTSIR_POS, missile_ammo=0, rng=rng,
                radar_network=net)
    ctrl = PantsirDefenseController([p])
    w = _StubWorld()
    # 2 km north of Pantsir at 300 m altitude; radar detects it (within 30 km).
    threat_pos = np.array([
        PANTSIR_POS[0],
        PANTSIR_POS[1] + 300.0,
        PANTSIR_POS[2] + 2_000.0,
    ], dtype=np.float64)
    threat = _HostileMissile(threat_pos, np.array([0.0, 0.0, -680.0]))
    w.missiles.append(threat)
    _run(ctrl, w, TRACK_FORM_S + 2.0)
    kinds = [k for k, _ in w.events]
    assert ("pantsir_gun" in kinds or "pantsir_kill" in kinds), (
        "gun must fire against tracked target inside 4 km")


def test_gun_silent_against_far_target():
    """A target outside GUN_RANGE_M (8 km) must not draw gun fire."""
    net = RadarNetwork()
    p = Pantsir("p_gun_far", PANTSIR_POS, missile_ammo=0, radar_network=net)
    ctrl = PantsirDefenseController([p])
    w = _StubWorld()
    # 8 km north — within radar range but outside 4 km gun range.
    threat_pos = np.array([
        PANTSIR_POS[0],
        PANTSIR_POS[1] + 300.0,
        PANTSIR_POS[2] + 8_000.0,
    ], dtype=np.float64)
    threat = _HostileMissile(threat_pos, np.array([0.0, 0.0, -5.0]))
    w.missiles.append(threat)
    _run(ctrl, w, TRACK_FORM_S + 2.0)
    kinds = [k for k, _ in w.events]
    assert "pantsir_gun" not in kinds, "gun must stay silent at 8 km"
    assert "pantsir_kill" not in kinds


# ===========================================================================
# 8. End-to-end intercept: 57E6 kills a straight-flying Tomahawk-like target
# ===========================================================================

def test_57e6_intercepts_straight_flying_tomahawk():
    """A 57E6 must kill a straight-flying 250 m/s cruise-missile-like target
    at 12 km range within one self_destruct_t flight window.

    The target flies at 300 m altitude at Mach 0.74 (~250 m/s) closing toward
    the Pantsir.  Both the 57E6 and the target are stepped at 120 Hz.
    The fuse check inside SamMissile.update() sets target.alive=False when the
    closest approach falls within PANTSIR_57E6.fuse_radius = 8 m.
    """
    w = _StubWorld()

    # Target: 12 km north of Pantsir at 300 m, closing south at 250 m/s.
    target_pos = np.array([0.0, THREAT_ALT, PANTSIR_POS[2] + 12_000.0],
                          dtype=np.float64)
    target_vel = np.array([0.0, 0.0, -250.0], dtype=np.float64)
    threat = _HostileMissile(target_pos, target_vel)
    w.missiles.append(threat)

    net = RadarNetwork()
    p = Pantsir("p_e2e", PANTSIR_POS, radar_network=net)
    ctrl = PantsirDefenseController([p])

    killed = False
    max_steps = int(PANTSIR_57E6.self_destruct_t / DT)

    for _ in range(max_steps):
        w.sim_time += DT
        threat.update(DT)
        ctrl.step(w, DT)
        # Step any 57E6s in flight.
        for m in list(w.missiles):
            if isinstance(m, SamMissile) and m.alive:
                m.update(DT, w)
        if not threat.alive:
            killed = True
            break

    assert killed, (
        "57E6 must intercept a straight-flying 250 m/s target at 12 km "
        f"within {PANTSIR_57E6.self_destruct_t} s")
    # Confirm launch event was emitted (the fuse kill is silent; the launch is logged).
    kinds = [k for k, _ in w.events]
    assert "pantsir_launch" in kinds


# ===========================================================================
# 9. Dead Pantsir engages nothing
# ===========================================================================

def test_dead_pantsir_engages_nothing():
    net = RadarNetwork()
    p = Pantsir("p_dead", PANTSIR_POS, radar_network=net)
    p.kill()
    ctrl = PantsirDefenseController([p])
    w = _StubWorld()
    threat = _make_threat()
    w.missiles.append(threat)
    _run(ctrl, w, 5.0)
    assert _sams(w) == [], "dead unit must launch nothing"
    assert p.radar.alive is False, "dead unit's radar must be dark"
    assert w.events == [], "dead unit must emit no events"
    assert threat.alive is True


# ===========================================================================
# 10. 57E6 is NOT hostile (structure sweep safety)
# ===========================================================================

def test_57e6_is_not_hostile():
    """A launched 57E6 must not be is_hostile; the structure sweep in
    sim/bases.py apply_missile_hits_structures checks getattr(m, 'is_hostile',
    False) before testing OBBs.  False here guarantees it never hits own base."""
    net = RadarNetwork()
    p = Pantsir("p_safe", PANTSIR_POS, radar_network=net)
    ctrl = PantsirDefenseController([p])
    w = _StubWorld()
    threat = _make_threat()
    w.missiles.append(threat)
    _run(ctrl, w, TRACK_FORM_S + 0.5)
    sams = _sams(w)
    assert sams, "prerequisite: a 57E6 must have been launched"
    for sam in sams:
        assert not getattr(sam, "is_hostile", False), (
            "57E6 round must NOT be is_hostile — cannot damage player structures")
