"""COMBAT Phase 4 end-to-end (GL-free): the recon drone.

Covers the integration seams wired in world/combat.py, sim/enemy_defense.py
and the GL-free game-layer helpers:

  * CombatWorld fields one drone at the base — friendly telemetry, never in
    ``self.aircraft`` (that list feeds contact pictures).
  * ELINT kill chain: a tasked crossing leg triangulates an EMITTING
    destroyer to an actionable fix and injects a fading uncertain track
    into the player picture while the hull stays far beyond the ground
    radar horizon; silencing every emitter ages the intel out (the track
    coasts and drops like any lost track).
  * SAR kill chain: overflying a SILENT hull forms a truth track through
    the board's normal sustained-detection flow.
  * The drone hunt: a destroyer that radar-detects the drone inside its
    'stealth' range engages with SM-2s (max 2 in flight per drone), the
    RWR shows SPIKE then LOCK, the fuse kill classifies as a sam_kill and
    starts the respawn cooldown; the replacement spawns at the base with a
    cleared route.
  * Stealth low-SNR guidance noise (user law: physics, never dice):
    seeded engagement batches lock the emergent kill statistics two-sided
    — near-certain close in, degraded at the detection edge — with a
    clean-guidance control killing everywhere (the misses ARE the noise).
  * SANDBOX untouched: WorldState has no drone and the sandbox TAB cycle
    keeps exactly two platforms.

Physics at the locked 120 Hz step where rounds fly; drone transits with no
ballistics in the air use coarse steps (the phase-3 e2e pattern).
"""

import math

import numpy as np
import pytest

from game.controls import PLATFORMS_COMBAT, PLATFORMS_SANDBOX, next_platform
from game.hud import drone_panel_rows
from sim.arsenal import SM2
from sim.contacts import TRACK_DROP_S
from sim.enemy_defense import (DRONE_SM2_MAX_INFLIGHT, STEALTH_SNR_SIGMA_MAX_M,
                               StealthTargetSam)
from sim.recon import (DRONE_ALT_M, DRONE_GONE, DRONE_SHOT_DOWN,
                       ELINT_FIX_ACTIONABLE_M, RWR_LOCK, RWR_SPIKE,
                       ReconDrone)
from sim.sam import SamMissile
from world.combat import DRONE_RESPAWN_S, ELINT_AGE_MAX_S, CombatWorld
from world.combat_config import CombatConfig
from world.generation import BASE_POS
from world.world import WorldState

DT = 1.0 / 120.0
DT_COARSE = 0.25        # transit cadence: nothing ballistic in the air


# ---------------------------------------------------------------------------
# Spawn wiring
# ---------------------------------------------------------------------------

def test_drone_spawns_at_base_outside_aircraft_list():
    w = CombatWorld()
    d = w.drone
    assert d is not None and d.alive
    assert d.aircraft_id == "drone_00"
    assert float(d.pos[0]) == BASE_POS[0]
    assert float(d.pos[2]) == BASE_POS[2]
    assert float(d.pos[1]) == DRONE_ALT_M
    assert d.route == []
    assert w.aircraft == []                 # friendly telemetry, not a contact
    assert w.drone_wrecks == []
    assert w.drone_respawn_left == 0.0
    # the sensor suite is wired
    assert w.elint is not None and w.sar is not None and w.rwr is not None


def test_sandbox_untouched():
    """WorldState carries no drone; the sandbox TAB cycle stays two
    platforms; COMBAT adds exactly the drone."""
    w = WorldState()
    assert not hasattr(w, "drone")
    assert PLATFORMS_SANDBOX == ("bastion", "s300")
    assert next_platform("bastion", PLATFORMS_SANDBOX) == "s300"
    assert next_platform("s300", PLATFORMS_SANDBOX) == "bastion"
    assert PLATFORMS_COMBAT == ("bastion", "s300", "drone")
    assert next_platform("s300", PLATFORMS_COMBAT) == "drone"
    assert next_platform("drone", PLATFORMS_COMBAT) == "bastion"


# ---------------------------------------------------------------------------
# Visibility gate: radar net OR (surface AND live drone AND SAR strip)
# ---------------------------------------------------------------------------

def test_player_visible_gate_sar_surface_only():
    w = CombatWorld()
    d = w.drone
    under = np.array([d.pos[0] + 10_000.0, 0.0, d.pos[2]])
    far = np.array([d.pos[0] + 60_000.0, 0.0, d.pos[2]])
    assert w._player_visible(under, "ship")          # in the strip
    assert not w._player_visible(far, "ship")        # outside the strip
    assert not w._player_visible(under, "fighter")   # SAR never images air
    d.kill()                                          # dead platform sees nothing
    assert not w._player_visible(under, "ship")


# ---------------------------------------------------------------------------
# ELINT kill chain + intel aging
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_elint_locates_emitting_ship_then_intel_ages_out():
    """Crossing leg south of the fleet: actionable fix within sim minutes,
    track injected at the estimate with the error mapped onto age, hull
    invisible to the radar net the whole time. Silencing every emitter
    stops the refresh and the track coasts out and drops.

    Phase 7 (updated): uses seed=5 where destroyer_02 (ships[2]) is ~135 km
    from base — good ELINT geometry for the crossing leg. The drone crosses
    30 km south of the ship so the crossing angle is sharp and the fix
    converges quickly."""
    w = CombatWorld(CombatConfig(seed=5))
    d = w.drone
    # Use the closest destroyer (ships[2] = destroyer_02 at ~135 km).
    ship = next(s for s in w.ships if s.ship_id == "destroyer_02")
    sx, sz = float(ship.pos[0]), float(ship.pos[2])
    # Crossing leg: 60 km west to 60 km east of the ship, 30 km south
    d.pos[0], d.pos[2] = sx - 60_000.0, sz - 30_000.0
    d.set_route([(sx + 60_000.0, sz - 30_000.0)])
    eid = "destroyer_02_spy1"
    fix_t = None
    for _ in range(int(600.0 / DT_COARSE)):
        w.step(DT_COARSE)
        if w.elint.is_actionable(eid):
            fix_t = w.sim_time
            break
    assert fix_t is not None, "fix never went actionable on a 120 km leg"
    for _ in range(8):                       # a couple of injection periods
        w.step(DT_COARSE)

    assert not w.radar_net.visible(ship.pos, "ship")  # only the drone explains it
    track = w.contacts.tracks.get(ship.ship_id)
    assert track is not None and not track["is_air"]
    assert np.array_equal(track["vel"], np.zeros(3))  # bearings carry no velocity
    # estimate is honest: near the true hull. fix_quality measures bearing
    # spread (< ELINT_FIX_ACTIONABLE_M = 5 km to be actionable). The
    # bearing-intersection centroid can lie a few km from truth due to
    # geometry — 10 km is a realistic ELINT accuracy bound for this crossing.
    est = w.elint.est_pos(eid)
    err = math.hypot(est[0] - ship.pos[0], est[2] - ship.pos[2])
    assert err < 10_000.0
    q = w.elint.fix_quality(eid)
    assert 0.0 < track["age"] <= ELINT_AGE_MAX_S + 5.0
    assert track["age"] >= ELINT_AGE_MAX_S * q / ELINT_FIX_ACTIONABLE_M - 5.0

    # Intel aging: every emitter silent -> injection stops, the track
    # coasts (the radar gate still fails) and drops at TRACK_DROP_S.
    for s in w.ships:
        s.radar.emitting = False
    for _ in range(int((TRACK_DROP_S + 10.0) / DT_COARSE)):
        w.step(DT_COARSE)
        if ship.ship_id not in w.contacts.tracks:
            break
    assert ship.ship_id not in w.contacts.tracks


# ---------------------------------------------------------------------------
# SAR kill chain
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_sar_overflight_tracks_silent_ship():
    """Phase 7 (updated): uses seed=5; the closest destroyer (ships[2] =
    destroyer_02 at ~135 km) is silenced and the drone overflies it directly.
    The SAR strip covers the hull and the board forms a truth track."""
    w = CombatWorld(CombatConfig(seed=5))
    d = w.drone
    # Use the closest destroyer: destroyer_02 = ships[2].
    ship = next(s for s in w.ships if s.ship_id == "destroyer_02")
    ship.radar.emitting = False              # target ship dark from t = 0
    sx, sz = float(ship.pos[0]), float(ship.pos[2])
    # Overfly the ship: start 40 km south of it, fly north through it.
    d.pos[0], d.pos[2] = sx, sz - 40_000.0
    d.set_route([(sx, sz + 40_000.0)])       # overfly its anchor
    sar_t = None
    for _ in range(int(600.0 / DT_COARSE)):
        w.step(DT_COARSE)
        if ship.ship_id in w.contacts.tracks:
            sar_t = w.sim_time
            break
    assert sar_t is not None, "SAR overflight never formed a track"
    assert d.alive                            # the silent ship cannot engage
    assert not w.radar_net.visible(ship.pos, "ship")
    track = w.contacts.tracks[ship.ship_id]
    err = math.hypot(track["pos"][0] - ship.pos[0],
                     track["pos"][2] - ship.pos[2])
    # SAR refreshes through the normal board flow: a truth fix, then the
    # usual dead-reckoned staleness — at formation it is essentially exact.
    assert err < 2_000.0
    # ELINT never heard the silent ship: SAR is the only explanation.
    assert f"{ship.ship_id}_spy1" not in w.elint.heard_emitters()


# ---------------------------------------------------------------------------
# The drone hunt: engagement, RWR, kill classification, respawn
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_drone_engaged_rwr_lock_kill_and_respawn():
    """The validated engagement geometry (smoke_combat): the silent ship
    lights up with the drone inside its 30 km stealth bubble — sustained
    detection, SM-2s (max 2 per drone in flight), SPIKE then LOCK on the
    RWR, a sam_kill air burst, the respawn cooldown and the replacement
    at the base.

    Phase 7 (updated): uses seed=5 where destroyer_02 (ships[2]) is ~135 km
    from base — within the 30 km stealth detection range at a reasonable
    transit distance. The drone is placed 25 km south of the ship and routes
    north through it so the ship is dead ahead when radar is activated."""
    w = CombatWorld(CombatConfig(seed=5))
    # 5b: the commander also vectors AIM-9X fighters at drone tracks —
    # ground the air wing so this test keeps isolating the SM-2 channel
    # it has always pinned (the IR hunt is covered by the 5b e2e).
    from sim.enemy_air import FS_GONE, Fighter
    for e in w.enemy_air:
        if isinstance(e, Fighter):
            e.state = FS_GONE
            e._alive = False
    d = w.drone
    # Use the closest destroyer: destroyer_02 = ships[2] at ~135 km.
    ship = next(s for s in w.ships if s.ship_id == "destroyer_02")
    sx, sz = float(ship.pos[0]), float(ship.pos[2])
    ship.radar.emitting = False
    # Start 25 km south of the ship, route north through it.
    d.pos[0], d.pos[2] = sx, sz - 25_000.0
    d.set_route([(sx, sz + 50_000.0)])
    for _ in range(int(60.0 / DT_COARSE)):   # close to within the stealth bubble
        w.step(DT_COARSE)
    w.drain_events()
    ship.radar.emitting = True

    saw_spike = saw_lock = False
    max_inflight = 0
    killed_t = None
    for _ in range(int(360.0 / DT)):
        w.step(DT)
        if w.drone is None:
            killed_t = w.sim_time
            break
        levels = [a[0] for a in w.rwr.alerts()]
        saw_spike = saw_spike or RWR_SPIKE in levels
        saw_lock = saw_lock or RWR_LOCK in levels
        hunters = [m for m in w.missiles if m.alive
                   and getattr(m, "target", None) is w.drone]
        assert all(isinstance(m, StealthTargetSam) for m in hunters)
        max_inflight = max(max_inflight, len(hunters))
    assert saw_spike, "RWR never spiked inside the stealth bubble"
    assert saw_lock, "RWR never showed LOCK with an SM-2 inbound"
    assert 1 <= max_inflight <= DRONE_SM2_MAX_INFLIGHT
    assert killed_t is not None, "close-in SM-2s never killed the drone"

    assert "sam_kill" in [k for k, _ in w.drain_events()]
    assert w.drone_respawn_left == DRONE_RESPAWN_S
    assert len(w.drone_wrecks) == 1
    assert w.drone_wrecks[0].state == DRONE_SHOT_DOWN

    # Cooldown runs out -> replacement at the base, route cleared.
    for _ in range(int((DRONE_RESPAWN_S + 1.0) / DT_COARSE)):
        w.step(DT_COARSE)
        if w.drone is not None:
            break
    assert w.drone is not None and w.drone.alive
    assert w.drone.aircraft_id == "drone_00"
    assert float(w.drone.pos[0]) == BASE_POS[0]
    assert float(w.drone.pos[2]) == BASE_POS[2]
    assert w.drone.route == []
    assert w.drone_respawn_left == 0.0


def test_respawn_timer_only_after_kill():
    """The cooldown starts when the drone is SHOT DOWN, not before; the
    wreck keeps spiralling in drone_wrecks while the timer runs."""
    w = CombatWorld()
    assert w.drone_respawn_left == 0.0
    w.drone.kill()
    w.step(DT)
    assert w.drone is None
    assert w.drone_respawn_left == pytest.approx(DRONE_RESPAWN_S, abs=1.0)
    assert len(w.drone_wrecks) == 1
    alt0 = float(w.drone_wrecks[0].pos[1])
    for _ in range(int(10.0 / DT)):
        w.step(DT)
    assert float(w.drone_wrecks[0].pos[1]) < alt0    # spiralling down
    assert w.drone_wrecks[0].state != DRONE_GONE


# ---------------------------------------------------------------------------
# Stealth low-SNR noise: the locked statistical contract (physics, not dice)
# ---------------------------------------------------------------------------

class _OpenSea:
    """Minimal world stub: deep ocean everywhere (no terrain mask)."""

    ships = []

    def terrain_height_at(self, x, z):
        return -500.0


_DECK = np.array([0.0, 10.0, 0.0])
_DETECT = 30_000.0          # SPY-1 'stealth' class range


def _illum():
    return (0.0, 20.0, 0.0)


def _drone_shot(range_m, seed):
    """One StealthTargetSam vs the real ReconDrone crossing at ground
    range ``range_m`` (tools/probe_drone_sm2.py geometry). seed None =
    plain SamMissile, zero noise (clean control)."""
    drone = ReconDrone(spawn_xz=(range_m, -20_000.0),
                       height_fn=lambda x, z: -500.0)
    drone.set_route([(range_m, 500_000.0)])
    if seed is None:
        sam = SamMissile(SM2, _DECK, drone, illuminator_pos_fn=_illum)
    else:
        sam = StealthTargetSam(SM2, _DECK, drone,
                               rng=np.random.default_rng(seed),
                               illuminator_pos_fn=_illum,
                               detection_range_m=_DETECT)
    w = _OpenSea()
    t = 0.0
    while sam.alive and t < 120.0:
        drone.update(DT)
        sam.update(DT, w)
        t += DT
    return sam.killed_target


def test_stealth_noise_sigma_scales_with_range_cubed():
    """The low-SNR fraction follows (R / R_detect)^3 (sigma_angle ~ R^2
    from SNR ~ R^-4, position error = angle x range)."""
    drone = ReconDrone(spawn_xz=(15_000.0, 0.0),
                       height_fn=lambda x, z: -500.0)
    sam = StealthTargetSam(SM2, _DECK, drone,
                           rng=np.random.default_rng(0),
                           illuminator_pos_fn=_illum,
                           detection_range_m=_DETECT)
    assert sam._snr_fraction() == pytest.approx(0.5 ** 3)
    drone.pos[0] = 30_000.0
    assert sam._snr_fraction() == pytest.approx(1.0)
    drone.pos[0] = 90_000.0                  # beyond the edge: clamped
    assert sam._snr_fraction() == pytest.approx(1.0)


@pytest.mark.slow
def test_stealth_kill_statistics_two_sided():
    """Seeded batches (measured by tools/probe_drone_sm2.py, sigma sweep
    40/60/80 — see sim/enemy_defense.py): at the locked sigma 60 the
    close batch (10 km, f^3 = 0.037) measured 14/15 and the edge batch
    (28 km, f^3 = 0.81) measured 4/15. Bands catch a 2x drift either way:
    close >= 0.75, edge within [0.05, 0.60]."""
    close = sum(_drone_shot(10_000.0, 1000 + i) for i in range(15)) / 15.0
    assert close >= 0.75, (
        f"close-in kill fraction {close:.2f} — the noise must clean up "
        f"near the radar (sigma={STEALTH_SNR_SIGMA_MAX_M})")
    edge = sum(_drone_shot(28_000.0, 1000 + i) for i in range(15)) / 15.0
    assert 0.05 <= edge <= 0.60, (
        f"edge-of-envelope kill fraction {edge:.2f} outside [0.05, 0.60] "
        f"— sigma drifted? (sigma={STEALTH_SNR_SIGMA_MAX_M})")


def test_clean_control_kills_everywhere():
    """rng None = zero noise: the same geometry kills at every range —
    the edge misses above are the NOISE, not a broken interceptor."""
    for rng_m in (10_000.0, 20_000.0, 28_000.0):
        assert _drone_shot(rng_m, None), f"clean SM-2 missed at {rng_m} m"


# ---------------------------------------------------------------------------
# HUD pure helper
# ---------------------------------------------------------------------------

def test_drone_panel_rows_airborne_and_down():
    w = CombatWorld()
    rows = drone_panel_rows(w)
    labels = [r[0] for r in rows]
    assert labels == ["STATUS", "ALT", "SPD", "SENSORS", "RWR"]
    assert rows[0][1] == "AIRBORNE"
    assert rows[-1][1] == "CLEAR"
    w.drone.kill()
    w.step(DT)                               # moves to wrecks, timer starts
    rows = drone_panel_rows(w)
    assert [r[0] for r in rows] == ["STATUS", "RESPAWN"]
    assert rows[0][1] == "DOWN"
    assert rows[1][1].endswith(" s")
