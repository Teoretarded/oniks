"""SM-6 long-range AREA air defense (Phase 8): the fleet's SM-6 must reach out
and engage HIGH inbound cruise missiles (hi-profile Oniks/Zircon) far beyond the
SM-2 band, forcing the player low — while leaving sea-skimmers to the SM-2/CIWS/
multipath layer. Sensor-only: it engages a formed TRACK, never ground truth.

Before the Phase-8 fix the SM-6 iterated only the drone track store (a stealthy
target seen <=40 km), so its 240 km reach was unreachable and it never engaged
the high cruise missiles it was designed to counter.
"""

import numpy as np

from sim.arsenal import SM6
from sim.enemy_defense import ShipDefense, TRACK_FORM_S, VIS_CHECK_PERIOD
from sim.enemy_ships import Destroyer
from sim.sam import SamMissile
from world.combat import CombatWorld
from world.combat_config import CombatConfig

DT = 1.0 / 120.0


class _Missile:
    """Minimal player-cruise-missile duck-type for the track store."""
    def __init__(self, pos, vel):
        self.pos = np.array(pos, dtype=np.float64)
        self.vel = np.array(vel, dtype=np.float64)
        self.alive = True


def _ship_over_water():
    """A real destroyer (radar over deep water, full attributes)."""
    w = CombatWorld(CombatConfig(seed=7))
    ship = next(s for s in w.ships if isinstance(s, Destroyer))
    ship.sm6_ammo = 8
    ship.sm6_reload_timer = 0.0
    ship.sm2_ammo = 24
    ship.sm2_reload_timer = 0.0
    return ship


def _form_and_fire(defense, missile, ship):
    import types
    world = types.SimpleNamespace(missiles=[missile], sim_time=0.0, drone=None)
    t = 0.0
    while t <= TRACK_FORM_S + VIS_CHECK_PERIOD + 0.1:
        defense._update_tracks([missile], t, DT)
        t += DT
    world.sim_time = t
    defense._try_sm6_launch(world, t)
    return [r for r in world.missiles
            if isinstance(r, SamMissile) and r.weapon is SM6]


def test_sm6_engages_high_inbound_missile_beyond_sm2():
    """A HIGH inbound cruise missile (14 km cruise) ~100 km out draws an SM-6."""
    ship = _ship_over_water()
    defense = ShipDefense(ship, np.random.default_rng(1))
    sx, sz = float(ship.pos[0]), float(ship.pos[2])
    # Hi-profile Oniks 100 km south of the ship, 14 km alt, inbound (+z).
    m = _Missile(pos=(sx, 14_000.0, sz - 100_000.0), vel=(0.0, 0.0, 250.0))
    rounds = _form_and_fire(defense, m, ship)
    assert len(rounds) == 1, f"SM-6 must engage a high inbound missile; got {len(rounds)}"


def test_sm6_ignores_low_target():
    """A target below the area-defense altitude floor (here 1 km at 60 km, which
    the radar DOES hold) is the SM-2/CIWS domain — the SM-6 must not poach it."""
    ship = _ship_over_water()
    defense = ShipDefense(ship, np.random.default_rng(2))
    sx, sz = float(ship.pos[0]), float(ship.pos[2])
    m = _Missile(pos=(sx, 1_000.0, sz - 60_000.0), vel=(0.0, 0.0, 250.0))
    rounds = _form_and_fire(defense, m, ship)
    assert len(rounds) == 0, "SM-6 must leave low targets to the SM-2 layer"


def test_sm6_engages_a_track_not_truth():
    """No truth leak: silent radar -> no track -> no SM-6, though the missile
    exists in the world."""
    ship = _ship_over_water()
    ship.radar.emitting = False
    defense = ShipDefense(ship, np.random.default_rng(3))
    sx, sz = float(ship.pos[0]), float(ship.pos[2])
    m = _Missile(pos=(sx, 14_000.0, sz - 100_000.0), vel=(0.0, 0.0, 250.0))
    rounds = _form_and_fire(defense, m, ship)
    assert len(rounds) == 0, "no track (silent radar) -> no SM-6 (sensor-only)"
