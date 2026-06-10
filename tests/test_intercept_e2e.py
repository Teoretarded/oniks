"""End-to-end Oniks-vs-ship intercepts: missile + ships + damage wired together."""
import numpy as np
import pytest

from sim.arsenal import ONIKS
from sim.damage import apply_missile_hits
from sim.missile import Missile
from sim.ships import ST_ALIVE, ST_BURNING, ST_SINKING, Ship

DT = 1 / 120


class _WorldWithShips:  # minimal world stub: open ocean + a ship list
    def __init__(self, ships):
        self.ships = ships

    def terrain_height_at(self, x, z):
        return -50.0


@pytest.mark.slow
def test_e2e_oniks_sinks_moving_cargo_at_180km():
    # Ship sails a straight lane crossing x at 7.5 m/s; launch with target_point at its CONTACT
    # (dead-reckoned, 40s stale) position; seeker must correct terminal error and hit.
    lane = [(-40_000.0, 180_000.0), (40_000.0, 180_000.0)]
    ship = Ship("c1", "cargo", lane, 0.45)
    w = _WorldWithShips([ship])
    stale_pos = ship.pos + ship.velocity() * 40.0
    m = Missile(ONIKS, np.array([0., 60., 0.]), 0.0, "hi-lo",
                target_point=np.array([stale_pos[0], 0.0, stale_pos[2]]))
    for _ in range(int(700 / DT)):
        m.update(DT, w); ship.update(DT)
        apply_missile_hits([m], [ship], [])
        if not m.alive: break
    assert ship.state in (ST_BURNING, ST_SINKING)     # HIT despite 300m of contact drift


@pytest.mark.slow
def test_e2e_miss_when_contact_hopeless():
    # Hopeless contact: target_point 30 km abeam of where the ship actually is.
    # With the ONIKS seeker (50 km range, 32 deg gimbal) any lateral error above
    # ~26.5 km can never enter the acquisition basket -> clean miss into the sea.
    lane = [(-40_000.0, 180_000.0), (40_000.0, 180_000.0)]
    ship = Ship("c1", "cargo", lane, 0.45)
    w = _WorldWithShips([ship])
    bogus = ship.pos + np.array([-30_000.0, 0.0, 0.0])
    m = Missile(ONIKS, np.array([0., 60., 0.]), 0.0, "hi-lo",
                target_point=np.array([bogus[0], 0.0, bogus[2]]))
    for _ in range(int(700 / DT)):
        m.update(DT, w); ship.update(DT)
        apply_missile_hits([m], [ship], [])
        if not m.alive: break
    assert ship.state == ST_ALIVE and not m.alive
    assert m.impact_pos is not None                                # splashed at sea
    assert float(np.linalg.norm(m.impact_pos - ship.pos)) > 10_000.0  # nowhere near
