"""R-P1 seeker honesty contracts (spec: weather_system_design_2026-07-07.md
PART 2 §10; plan: radar_scan_seeker_honesty_plan_2026-07-07.md).

The Oniks/Zircon active-radar terminal seeker must obey the same physics
its victims' radars obey: the radar horizon and terrain masking.  Before
this pass it read truth ships anywhere inside its gimbal cone — a 50 km
acquisition from a 12 m sea-skim is geometrically impossible (horizon to a
~18 m superstructure is ~32 km).
"""

import math

import numpy as np

from sim.arsenal import ONIKS
from sim.missile import Missile, SHIP_MAST_M


class _StubWorld:
    """Minimal duck-type for _acquire_lock: ships + the terrain query.
    radar_model='scanned' arms the honest-seeker gates (the game layer
    always plays scanned; 'functional' keeps the legacy truth-in-cone
    seeker for the byte-identity suite)."""

    def __init__(self, ships, height_fn=None, radar_model="scanned"):
        self.ships = ships
        self.radar_model = radar_model
        if height_fn is not None:
            self.terrain_height_at = height_fn
        else:
            self.terrain_height_at = lambda x, z: 0.0


class _Ship:
    def __init__(self, x, z, alive=True):
        self.pos = np.array([x, 15.0, z])
        self.alive = alive
        self.vel = np.zeros(3)

    def velocity(self):
        return self.vel


def _terminal_oniks(alt):
    """Bare Missile carrying only what _acquire_lock reads."""
    m = Missile.__new__(Missile)
    m.weapon = ONIKS
    m.pos = np.array([0.0, alt, 0.0])
    m.vel = np.array([0.0, 0.0, 680.0])     # flying north
    m.locked_ship = None
    return m


def test_oniks_seeker_horizon_limited():
    m = _terminal_oniks(alt=12.0)                       # 12 m sea-skim
    far = _Ship(0.0, 45_000.0)                          # beyond the horizon
    m._acquire_lock(_StubWorld([far]), speed=680.0)
    assert m.locked_ship is None
    near = _Ship(0.0, 25_000.0)                         # inside the horizon
    m._acquire_lock(_StubWorld([near]), speed=680.0)
    assert m.locked_ship is near


def test_oniks_seeker_blocked_by_island():
    def ridge(x, z):
        # 2 km wide so the long-range 2 km LOS sample step cannot straddle
        # it (terrain_blocks samples at z = 2000*i over this 18 km line).
        return 140.0 if 7_500.0 < z < 9_500.0 else 0.0
    m = _terminal_oniks(alt=12.0)
    hidden = _Ship(0.0, 18_000.0)
    m._acquire_lock(_StubWorld([hidden], ridge), speed=680.0)
    assert m.locked_ship is None
    # Same geometry, no ridge: the lock is there (two-sided).
    m2 = _terminal_oniks(alt=12.0)
    open_ship = _Ship(0.0, 18_000.0)
    m2._acquire_lock(_StubWorld([open_ship]), speed=680.0)
    assert m2.locked_ship is open_ship


def test_high_diver_keeps_long_acquisition():
    # A Zircon-style high diver looks DOWN past any surface horizon — the
    # gates must not nerf the designed high-altitude acquisition geometry.
    m = _terminal_oniks(alt=15_000.0)
    m.vel = np.array([0.0, -300.0, 600.0])
    far = _Ship(0.0, 45_000.0)
    m._acquire_lock(_StubWorld([far]), speed=671.0)
    assert m.locked_ship is far


def test_horizon_math_matches_radar_module():
    # The seeker uses the SAME horizon helper as every radar (one physics).
    from sim.radar import radar_horizon_m
    horizon = radar_horizon_m(12.0, 15.0 + SHIP_MAST_M)
    assert 28_000.0 < horizon < 40_000.0    # sanity band for the test geoms


def test_functional_world_keeps_legacy_seeker():
    # Byte-identity flag: a functional-model world (the whole legacy test
    # suite) keeps the old truth-in-cone seeker verbatim.
    m = _terminal_oniks(alt=12.0)
    far = _Ship(0.0, 45_000.0)
    m._acquire_lock(_StubWorld([far], radar_model="functional"), speed=680.0)
    assert m.locked_ship is far
