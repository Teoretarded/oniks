"""M3-F2 enemy escort jammer (EA-18G-class Growler).

A standoff jammer orbits ~deep behind the carrier screen and radiates a
barrage-noise corridor that COLLAPSES the player radar's range via the EW
field model (sim/ew.py, M3-F1).  It is a fat always-on beacon: the player can
ELINT-localize + SEAD it, or go passive under the corridor.  Its AI (the
commander's ``_defend_jammer`` sub-doctrine) reads ONLY the sensor picture
(believed emitters, sensed missile tracks) — NEVER a real player entity's
position.  It stations on the fleet->loudest-believed-emitter bearing, lifts
the jam (anti-strobe dwell) when ELINT-localized or an ARM/SAM track is
inbound, and flees toward the carrier when a missile track closes.

CONTRACTS exercised here:
  * THE gameplay link — n_jammers=1 drops a target the radar tracks at
    n_jammers=0 (the field model bites through ``_player_visible``).
  * the jammer is a fat beacon the player ELINT hears (localizable for SEAD).
  * NO-CHEAT — the station bearing follows BELIEF, not the real player radar.
  * anti-strobe — lift on inbound ARM holds through the dwell, no per-tick
    strobe, re-jams when clear.
  * determinism — same seed + same picture => identical orders.
  * REGRESSION GATE — n_jammers=0 (default) is byte-identical: no jammer is
    built, _player_visible passes jammers=() unchanged.
"""

from __future__ import annotations

import math

import numpy as np

from world.combat import CombatWorld
from world.combat_config import CombatConfig
from sim.commander import (EmitterIntel, JAMMER_THREAT_RANGE_M,
                           JAMMER_EMCON_DWELL_S)
import sim.commander as _cmd
import sim.enemy_air as _ea
import sim.ew as _ew


DT = 1.0 / 30.0


# ---------------------------------------------------------------------------
# 0. The standoff constant must agree across the doctrine, the flight model,
#    and the EW calibration — they are split only to dodge a circular import.
# ---------------------------------------------------------------------------

def test_standoff_constant_consistent():
    assert _cmd.JAMMER_STANDOFF_M == _ea.JAMMER_STANDOFF_M
    assert _cmd.JAMMER_STANDOFF_M == _ew.EW_DEFAULT_STANDOFF_M
    # the flight jam power matches the EW default the field model is tuned to.
    assert _ea.JAMMER_POWER_W == _ew.EW_DEFAULT_JAM_POWER_W


# ---------------------------------------------------------------------------
# 1. THE gameplay link: the jammer collapses the player radar's tracked range.
# ---------------------------------------------------------------------------

def _high_air_target_at(world, ground_range_m, alt_m=11_000.0):
    """A point ``ground_range_m`` down-range (+z) of the player radar station
    at ``alt_m`` — high enough to clear the radar horizon so the ONLY thing the
    jammer changes is the range-ring collapse."""
    r = world.radar_station
    return (float(r.pos[0]), float(alt_m), float(r.pos[2]) + ground_range_m)


def test_jammer_collapses_player_radar():
    """A high-altitude air target the player radar tracks at long range WITHOUT
    the jammer is NO LONGER tracked WITH the jammer active (the EW field model
    bites through ``_player_visible``); and with n_jammers=0 it IS tracked
    (the byte-identical baseline)."""
    # Range chosen so it sits inside the 350 km ring + above the horizon, but
    # BEYOND the default jammer's collapsed burn-through (~255 km).
    RANGE_M = 300_000.0

    # --- baseline: no jammer -> the target IS tracked.
    w0 = CombatWorld(CombatConfig(seed=11, n_jammers=0))
    tgt0 = _high_air_target_at(w0, RANGE_M)
    assert w0._active_enemy_jammers() == [], "n_jammers=0 builds no jammers"
    assert w0._player_visible(tgt0, "fighter"), \
        "without a jammer the radar tracks the long-range air target"

    # --- with a jammer: the corridor collapses the ring and drops the target.
    w1 = CombatWorld(CombatConfig(seed=11, n_jammers=1))
    tgt1 = _high_air_target_at(w1, RANGE_M)
    jammers = w1._active_enemy_jammers()
    assert jammers, "n_jammers=1 builds a live, emitting jammer"
    # Same geometry, but now denied by the burn-through corridor.
    assert not w1._player_visible(tgt1, "fighter"), \
        "the active jammer must collapse the ring and drop the tracked target"

    # And a CLOSE target both worlds would see is still seen under the jam
    # (the close-in floor — jamming never denies a knife-range detection).
    close0 = _high_air_target_at(w0, 30_000.0, alt_m=6_000.0)
    close1 = _high_air_target_at(w1, 30_000.0, alt_m=6_000.0)
    assert w0._player_visible(close0, "fighter")
    assert w1._player_visible(close1, "fighter"), \
        "the jammer must not deny a close-in detection (EW close floor)"


# ---------------------------------------------------------------------------
# 2. The jammer is a fat beacon the player ELINT hears.
# ---------------------------------------------------------------------------

def test_jammer_heard_by_player_elint():
    """The jammer's emitter joins ``world._emitters()`` and the drone's
    ElintReceiver can HEAR it — it is a loud always-on beacon, so the player
    can passively localize it (the SEAD-ARM hand-off from M2)."""
    w = CombatWorld(CombatConfig(seed=11, n_jammers=1))
    jammer = w._jammers[0]
    eid = jammer.emitter.radar_id

    # The emitter is published in the ELINT/RWR emitter list.
    ems = dict(w._emitters())
    assert eid in ems, "the live jammer's emitter must appear in _emitters()"

    # Park the drone right under the jammer orbit and let the ELINT listen:
    # within range + horizon + LOS the emitter must be HEARD.
    jp = jammer.emitter.pos
    # Drone at the jammer's altitude, a short slant away (clear LOS, in range).
    w.drone.pos[:] = np.array([float(jp[0]) + 5_000.0, float(jp[1]),
                               float(jp[2])], dtype=np.float64)
    w.elint.update(w.drone.pos, w._emitters(), sim_time=w.sim_time)
    assert eid in w.elint.heard_emitters(), \
        "the always-on jammer beacon must be heard by the drone ELINT"


# ---------------------------------------------------------------------------
# 3. NO-CHEAT: the station bearing follows BELIEF, not the real player radar.
# ---------------------------------------------------------------------------

def _fleet_centroid_xz(world):
    xs = [float(s.pos[0]) for s in world.ships if s.alive]
    zs = [float(s.pos[2]) for s in world.ships if s.alive]
    return (sum(xs) / len(xs), sum(zs) / len(zs))


def test_jammer_stations_on_belief_not_truth():
    """With a located player emitter in the picture, the commander stations the
    jammer on the fleet->BELIEVED-emitter bearing.  Move the REAL player radar
    far from the believed fix and confirm the station bearing follows the
    BELIEF (the EmitterIntel), never the truth."""
    w = CombatWorld(CombatConfig(seed=11, n_jammers=1))
    cmd = w.commander
    pic = cmd.picture

    # Believed player emitter at a fabricated, located fix WELL EAST of the
    # real radar station (the truth lives at world.radar_station.pos).
    believed = np.array([300_000.0, 100.0, 50_000.0], dtype=np.float64)
    pic.emitters["radar_player_00"] = EmitterIntel(
        emitter_id="radar_player_00",
        believed_pos=believed.copy(),
        alive=True,
        fix_progress=1.0,           # located
        last_heard_t=w.sim_time,
    )
    # MOVE THE TRUTH far away from the belief (opposite side of the map).
    w.radar_station.pos[:] = np.array([-300_000.0, 100.0, 50_000.0],
                                      dtype=np.float64)

    cmd.pending_orders.clear()
    cmd._defend_jammer(w.sim_time)
    jam_orders = [o for o in cmd.pending_orders if o["type"] == "jammer_jam"]
    assert jam_orders, "a stationing jam order must be issued"
    station = np.asarray(jam_orders[0]["station_xz"], dtype=np.float64)

    # The commanded station must lie on the fleet->BELIEF bearing, not the
    # fleet->TRUTH bearing.
    fx, fz = _fleet_centroid_xz(w)
    bearing_belief = math.atan2(believed[0] - fx, believed[2] - fz)
    bearing_truth = math.atan2(w.radar_station.pos[0] - fx,
                               w.radar_station.pos[2] - fz)
    bearing_station = math.atan2(station[0] - fx, station[1] - fz)

    def _angdiff(a, b):
        return abs((a - b + math.pi) % (2.0 * math.pi) - math.pi)

    assert _angdiff(bearing_station, bearing_belief) < math.radians(5.0), \
        "station must follow the BELIEVED emitter bearing"
    assert _angdiff(bearing_station, bearing_truth) > math.radians(45.0), \
        "station must NOT follow the real (truth) radar bearing"


# ---------------------------------------------------------------------------
# 4. Anti-strobe: lift on inbound ARM, hold through the dwell, re-jam clear.
# ---------------------------------------------------------------------------

def test_jammer_lifts_on_inbound_arm_no_strobe():
    """A sensed inbound ARM/missile track within JAMMER_THREAT_RANGE_M lifts
    the jam (emitter.emitting False) and HOLDS through the dwell without
    strobing each tick; the jam comes back once the threat is clear and the
    dwell elapses."""
    w = CombatWorld(CombatConfig(seed=11, n_jammers=1))
    cmd = w.commander
    pic = cmd.picture
    jammer = w._jammers[0]
    jp = jammer.emitter.pos
    assert jammer.emitter.emitting, "jammer emits by default"

    # Inbound ARM track 30 km from the jammer (< JAMMER_THREAT_RANGE_M).
    arm = np.array([float(jp[0]), 6_000.0, float(jp[2]) - 30_000.0],
                   dtype=np.float64)
    assert math.hypot(arm[0] - jp[0], arm[2] - jp[2]) < JAMMER_THREAT_RANGE_M
    pic.update_missile_track("arm_probe", arm,
                             np.array([0.0, 0.0, 300.0]), sim_time=0.0,
                             kind="kh31p")

    # First tick: lift the jam, exactly ONE lift order.
    cmd.pending_orders.clear()
    cmd._defend_jammer(0.0)
    lifts = [o for o in cmd.pending_orders if o["type"] == "jammer_lift"]
    assert len(lifts) == 1, "exactly one lift order on the first threatened tick"
    for o in cmd.pending_orders:
        w._execute_commander_order(o)
    assert not jammer.emitter.emitting, "jam must be lifted while ARM inbound"

    # Threat still present a tick later: NO second lift order (anti-spam).
    cmd.pending_orders.clear()
    cmd._defend_jammer(1.0)
    assert [o for o in cmd.pending_orders if o["type"] == "jammer_lift"] == [], \
        "no per-tick lift spam while the threat persists"

    # Threat gone but WITHIN the dwell -> still lifted (no premature re-jam).
    pic.missile_tracks.clear()
    cmd.pending_orders.clear()
    cmd._defend_jammer(JAMMER_EMCON_DWELL_S * 0.5)
    rejams = [o for o in cmd.pending_orders if o["type"] == "jammer_jam"]
    assert rejams == [], "must hold the lift through the dwell (no self-strobe)"

    # After the dwell, threat clear -> re-jam.
    cmd.pending_orders.clear()
    cmd._defend_jammer(JAMMER_EMCON_DWELL_S + 2.0)
    rejams = [o for o in cmd.pending_orders if o["type"] == "jammer_jam"]
    assert len(rejams) >= 1, "re-jam once the threat is clear and dwell elapses"
    for o in cmd.pending_orders:
        w._execute_commander_order(o)
    assert jammer.emitter.emitting, "the jammer re-radiates after the dwell"


# ---------------------------------------------------------------------------
# 5. Determinism: same seed + same picture -> identical orders.
# ---------------------------------------------------------------------------

def test_jammer_determinism():
    """Two same-seed worlds fed the same believed picture produce identical
    jammer orders (the brain is a pure function of picture + time; no RNG)."""
    def run():
        w = CombatWorld(CombatConfig(seed=77, n_jammers=1))
        pic = w.commander.picture
        believed = np.array([250_000.0, 100.0, 40_000.0], dtype=np.float64)
        pic.emitters["radar_player_00"] = EmitterIntel(
            emitter_id="radar_player_00",
            believed_pos=believed.copy(), alive=True,
            fix_progress=1.0, last_heard_t=0.0)
        w.commander.pending_orders.clear()
        w.commander._defend_jammer(0.0)
        out = []
        for o in w.commander.pending_orders:
            st = o.get("station_xz")
            out.append((o["type"],
                        None if st is None
                        else (round(float(st[0]), 3), round(float(st[1]), 3))))
        return tuple(out)

    assert run() == run(), "same-seed jammer orders must be identical"


# ---------------------------------------------------------------------------
# 6. REGRESSION GATE: n_jammers=0 (default) is byte-identical.
# ---------------------------------------------------------------------------

def _emit_states(w):
    """Snapshot of every ship + ground radar emitting state plus the AWACS
    (the surfaces the defend doctrines toggle)."""
    ships = tuple(sorted(
        (s.ship_id, bool(s.radar.emitting)) for s in w.ships
        if getattr(s, "radar", None) is not None))
    ground = tuple(sorted(
        (r.radar_id, bool(r.emitting))
        for r in getattr(w, "_enemy_ground_radars", [])))
    awacs = bool(w.awacs.radar.emitting)
    return ships, ground, awacs


def test_default_no_jammer_byte_identical():
    """CombatConfig().n_jammers == 0; a default same-seed battle is bit-identical
    to before (no jammer built, _player_visible unchanged)."""
    assert CombatConfig().n_jammers == 0, "the jammer is OFF by default"

    # No jammers built, the active-jammer list is empty.
    w = CombatWorld(CombatConfig(seed=42))
    assert w._jammers == []
    assert w._active_enemy_jammers() == []

    # _player_visible with no jammer must pass jammers=() to the net — verify
    # it equals the raw radar-net visibility (the legacy gate, untouched).
    for rng in (40_000.0, 120_000.0, 360_000.0):
        tgt = (float(w.radar_station.pos[0]), 9_000.0,
               float(w.radar_station.pos[2]) + rng)
        assert (w._player_visible(tgt, "fighter")
                == (w.radar_net.visible(tgt, "fighter")
                    or (tgt is None)))

    # Two same-seed default battles step to identical emit states.
    def runb():
        wb = CombatWorld(CombatConfig(seed=42))
        for _ in range(int(20.0 / DT)):
            wb.step(DT)
        return _emit_states(wb)

    assert runb() == runb(), "default battle emit states diverged"
