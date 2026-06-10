import numpy as np, pytest
from sim.missile import Missile, PH_EJECT, PH_BOOST, PH_CRUISE, PH_TERMINAL, PH_DEAD
from sim.arsenal import ONIKS

DT = 1/120
class _World:  # minimal stub
    ships = []
    def terrain_height_at(self, x, z): return -50.0  # open ocean

def _launch(profile="hi-lo", target=(0., 0., 200_000.)):
    m = Missile(ONIKS, np.array([0., 60., 0.]), heading=0.0, profile=profile,
                target_point=np.array(target))
    return m

def test_cold_launch_goes_straight_up():
    m = _launch(); w = _World()
    for _ in range(int(0.8 / DT)): m.update(DT, w)
    assert m.phase == PH_EJECT
    assert m.pos[1] > 60.0 and abs(m.pos[0]) < 0.5 and abs(m.pos[2]) < 0.5

def test_booster_ignites_and_climbs():
    m = _launch(); w = _World()
    for _ in range(int(3.5 / DT)): m.update(DT, w)
    assert m.phase != PH_EJECT
    assert m.vel[1] > 50.0                      # climbing hard
    assert np.linalg.norm(m.vel) > 250.0

def test_hi_lo_reaches_cruise_alt_and_mach():
    m = _launch(); w = _World()
    for _ in range(int(180 / DT)):
        m.update(DT, w)
        if m.phase == PH_CRUISE and m.t > 120: break
    from sim.physics import mach
    assert m.phase == PH_CRUISE
    assert abs(m.pos[1] - ONIKS.cruise_alt_hi) < 800.0
    assert abs(mach(np.linalg.norm(m.vel), m.pos[1]) - ONIKS.cruise_mach_hi) < 0.25

def test_lo_lo_stays_low():
    m = _launch("lo-lo"); w = _World()
    max_alt = 0.0
    for _ in range(int(90 / DT)):
        m.update(DT, w); max_alt = max(max_alt, m.pos[1])
    assert max_alt < 900.0                       # never balloons
    assert m.phase == PH_CRUISE and abs(m.pos[1] - ONIKS.lo_alt) < 30.0

@pytest.mark.slow
def test_full_hi_lo_flight_sea_skims_then_splashes_at_target():
    m = _launch(target=(0., 0., 250_000.)); w = _World()
    skim_samples = []
    for _ in range(int(900 / DT)):
        m.update(DT, w)
        if m.phase == PH_TERMINAL: skim_samples.append(m.pos[1])
        if not m.alive: break
    assert not m.alive and m.impact_pos is not None
    assert np.linalg.norm(m.impact_pos[[0, 2]] - np.array([0., 250_000.])) < 600.0
    settled = np.array(skim_samples[len(skim_samples)//3:])
    assert settled.size and abs(settled.mean() - ONIKS.skim_alt) < 5.0 and settled.max() < 40.0

@pytest.mark.slow
def test_fuel_lasts_long_range():
    m = _launch(target=(0., 0., 340_000.)); w = _World()
    for _ in range(int(900 / DT)):
        m.update(DT, w)
        if not m.alive: break
    assert m.impact_pos is not None and m.fuel > 0.0   # made 340 km with fuel to spare

def test_waypoints_pop_as_the_route_is_flown():
    """Regression (found by Task 20): route waypoints are (x, z) pairs but
    waypoint_reached takes a 3-vector — flying past a waypoint used to crash."""
    m = Missile(ONIKS, np.array([0., 60., 0.]), heading=0.0, profile="hi-lo",
                target_point=np.array([0., 0., 200_000.]),
                waypoints=((100., 1_000.), (0., 100_000.)))
    w = _World()
    assert len(m.route) == 3                     # 2 waypoints + target point
    m.pos = np.array([0., 4_000., 1_000.])       # within radius of waypoint 1
    m.update(DT, w)
    assert m.route == [(0., 100_000.), (0., 200_000.)]

def test_determinism():
    a = _launch(); b = _launch(); w = _World()
    for _ in range(int(30 / DT)): a.update(DT, w)
    for _ in range(int(30 / DT)): b.update(DT, w)
    assert np.array_equal(a.pos, b.pos) and np.array_equal(a.vel, b.vel)
