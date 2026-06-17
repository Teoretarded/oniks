"""No-cheat regression (2026-06-18 zero-bias audit, HIGH finding).

Contract #2 (fog-of-war / no cheat): a fighter may steer and fire on the drone's
TRUTH position ONLY while its OWN nose radar HOLDS the drone this step.  A single
radar ping must NOT grant a permanent truth-track — continuous engagement
requires continuous own-sensor reacquisition.  On contact loss the fighter flies
the cached LAST-KNOWN fix for a short anti-strobe dwell, then drops the entity
track so the commander re-vectors.

Before the fix: once ``_intercept_target`` was set after one detection,
``Fighter.update`` steered on the drone's truth pos every tick and
``release_weapons`` fired AIM-9X on truth with no live-radar re-check.
"""
import types

import numpy as np

from sim.enemy_air import (
    AirBase,
    Carrier,
    Fighter,
    FIGHTER_ALT_M,
    FIGHTER_INTERCEPT_HOLD_S,
    FS_ON_STATION,
)

DT = 1.0 / 120.0


def _drone_at(xz, alt=FIGHTER_ALT_M, vel=(0.0, 0.0, 0.0)):
    """Minimal duck-typed ReconDrone stub: a stealth-class air target."""
    d = types.SimpleNamespace()
    d.pos = np.array([xz[0], alt, xz[1]], dtype=np.float64)
    d.alive = True
    d.radar_size = "stealth"
    d.velocity = lambda: np.array(vel, dtype=np.float64)
    return d


def _airborne_fighter(at_xz=(0.0, 0.0)):
    """A fighter on station at altitude, nose radar hot, heading north (+z)."""
    base = AirBase(Carrier("cv", anchor_xz=(0.0, 250_000.0), heading_deg=0.0))
    f = Fighter("f_nc", base, (0.0, 0.0))
    f.pos = np.array([at_xz[0], FIGHTER_ALT_M, at_xz[1]], dtype=np.float64)
    f.state = FS_ON_STATION
    f.heading = 0.0
    f._hardpoints = ["aim9x"]
    f.radar.emitting = True
    f.radar.pos = f.pos.copy()
    f.radar._heading_ref = 0.0
    return f


def test_aim9x_fires_only_with_a_live_radar_hold():
    """Same geometry (drone 4 km dead ahead, inside IR + stealth-cone range);
    the ONLY difference is whether the nose radar is holding it.  Held -> fires;
    not held (radar silent / no contact) -> must NOT fire on truth."""
    # Held: nose radar on, drone in the cone -> a legitimate shot.
    f = _airborne_fighter()
    drone = _drone_at((0.0, 4_000.0))
    f.execute_order({"type": "intercept", "target": drone})
    f.radar.pos = f.pos.copy()
    f.radar._heading_ref = 0.0
    assert f.radar.detects(drone.pos, "stealth")           # sanity: held
    assert len(f.release_weapons([], [])) == 1             # fires on a hold

    # Not held: identical geometry, but the radar is NOT holding the drone.
    f2 = _airborne_fighter()
    drone2 = _drone_at((0.0, 4_000.0))
    f2.execute_order({"type": "intercept", "target": drone2})
    f2.radar.emitting = False                              # no live sensor hold
    f2.radar.pos = f2.pos.copy()
    f2.radar._heading_ref = 0.0
    assert not f2.radar.detects(drone2.pos, "stealth")
    assert f2.release_weapons([], []) == []               # NO truth-fire (fix)


def test_steers_last_known_not_truth_after_contact_loss():
    """After a hold then a loss, the fighter flies the LAST-KNOWN fix, not the
    drone's moved-far truth position."""
    f = _airborne_fighter()
    drone = _drone_at((0.0, 8_000.0))                      # 8 km ahead -> held
    f.execute_order({"type": "intercept", "target": drone})
    f.update(DT)                                           # caches last-known
    # Drone jumps far out of any radar hold.
    drone.pos = np.array([0.0, FIGHTER_ALT_M, 60_000.0])
    f.update(DT)                                           # contact lost
    wp = f._waypoints[0]
    # The fix steers toward the ~8 km last-known, NOT the 60 km truth.
    assert wp[2] < 20_000.0


def test_drops_entity_track_after_anti_strobe_dwell():
    """A sustained contact loss (longer than the dwell) drops the entity track
    so the commander re-vectors — no permanent truth-track off one ping."""
    f = _airborne_fighter()
    drone = _drone_at((0.0, 8_000.0))
    f.execute_order({"type": "intercept", "target": drone})
    f.update(DT)                                           # held once
    drone.pos = np.array([0.0, FIGHTER_ALT_M, 200_000.0])  # gone for good
    for _ in range(int(FIGHTER_INTERCEPT_HOLD_S / DT) + 10):
        f.update(DT)
    assert f._intercept_target is None
