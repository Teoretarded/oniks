import math

import numpy as np, pytest
from sim.missile import (Missile, PH_EJECT, PH_RIDEOUT, PH_PITCHOVER,
                         PH_BOOST, PH_CLIMB, PH_CRUISE, PH_TERMINAL, PH_DEAD)
from sim.arsenal import ONIKS, ZIRCON
from sim.physics import mach_scalar

DT = 1/120
class _World:  # minimal stub
    ships = []
    def terrain_height_at(self, x, z): return -50.0  # open ocean

def _launch(profile="hi-lo", target=(0., 0., 200_000.)):
    m = Missile(ONIKS, np.array([0., 60., 0.]), heading=0.0, profile=profile,
                target_point=np.array(target))
    return m

def _fly_to_boost(m, w):
    """Step until the cap-jettison handover (PITCH-OVER -> BOOST)."""
    while m.phase != PH_BOOST and m.t < 8.0:
        m.update(DT, w)
    assert m.phase == PH_BOOST
    return m.t

# --- Task LC: hybrid hot launch (in-tube ignition, ride-out, pitch-over) -----

def test_hot_launch_exit_speed_and_vertical_rideout():
    m = _launch(); w = _World()
    m.update(DT, w)
    assert m.phase == PH_EJECT and m.phase_label == "IGNITION"
    assert 25.0 <= m.vel[1] <= 40.0             # plan: exit at 25-40 m/s
    for _ in range(int(1.4 / DT)):              # into the heavy ride-out
        m.update(DT, w)
    assert m.phase == PH_RIDEOUT and m.phase_label == "RIDE-OUT"
    assert abs(m.pos[0]) < 0.5 and abs(m.pos[2]) < 0.5   # dead vertical
    assert m.vel[1] > ONIKS.eject_speed         # net accel small but POSITIVE
    assert m.vel[1] < 60.0                      # ... and visibly heavy

def test_pitchover_cap_jettison_window_and_heading():
    bearing = math.radians(30.0)                # off-axis: heading must turn
    target = (100_000.0 * math.sin(bearing), 0.0, 100_000.0 * math.cos(bearing))
    m = _launch(target=target); w = _World()
    t_cap = _fly_to_boost(m, w)
    assert 2.8 <= t_cap <= 3.6                  # plan: end of tip-over ~3.0-3.5
    assert 100.0 <= m.pos[1] - 60.0 <= 260.0    # plan: cap-jettison altitude
    hdg = math.atan2(m.vel[0], m.vel[2])
    err = (hdg - bearing + math.pi) % (2.0 * math.pi) - math.pi
    assert abs(err) <= math.radians(15.0)       # plan: within 15 deg of route

def test_pitchover_window_lo_profile():
    m = _launch("lo-lo"); w = _World()
    t_cap = _fly_to_boost(m, w)
    assert 2.8 <= t_cap <= 3.6
    assert 100.0 <= m.pos[1] - 60.0 <= 260.0
    assert m.phase_label == "BOOST"

def test_pitchover_label_while_turning():
    m = _launch(); w = _World()
    for _ in range(int(2.4 / DT)):
        m.update(DT, w)
    assert m.phase == PH_PITCHOVER and m.phase_label == "PITCH-OVER"
    assert np.linalg.norm(m.vel) < 120.0        # still slow: the violent beat waits

def test_high_thrust_reaches_mach2_in_6_to_9s():
    m = _launch(); w = _World()
    t0 = _fly_to_boost(m, w)
    while m.phase == PH_BOOST and m.t - t0 < 12.0:
        m.update(DT, w)
    assert m.phase in (PH_CLIMB, PH_CRUISE)     # burnout hands over to ramjet
    burn = m.t - t0
    assert 6.0 <= burn <= 9.0                   # plan: Mach 2 6-9 s after slam
    assert mach_scalar(float(np.linalg.norm(m.vel)), float(m.pos[1])) > 1.9

def test_high_thrust_boost_climbs_hard():
    m = _launch(); w = _World()
    for _ in range(int(6.5 / DT)): m.update(DT, w)
    assert m.phase == PH_BOOST
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

def test_hi_lo_close_range_no_overshoot():
    """Task 22b: a hi-lo shot at a target inside the descent envelope must not
    climb to full cruise altitude, overshoot, and circle back."""
    target = np.array([0., 0., 35_000.])
    m = _launch(target=target); w = _World()
    path_len = 0.0; peak_alt = 0.0
    for _ in range(int(300 / DT)):
        m.update(DT, w)
        path_len += float(np.linalg.norm(m.pos - m.prev_pos))
        peak_alt = max(peak_alt, float(m.pos[1]))
        if not m.alive: break
    assert not m.alive and m.impact_pos is not None
    assert np.linalg.norm(m.impact_pos[[0, 2]] - target[[0, 2]]) < 600.0
    direct = float(np.hypot(target[0] - 0.0, target[2] - 0.0))
    assert path_len < 1.5 * direct           # no overshoot-and-circle-back
    assert peak_alt < 3000.0                 # stays low on a short shot

def test_hi_lo_long_range_unchanged():
    """Task 22b: route length far beyond the descent envelope -> the full
    commanded hi cruise altitude is unchanged."""
    m = _launch(target=(0., 0., 250_000.)); w = _World()
    for _ in range(int(180 / DT)):
        m.update(DT, w)
        if m.phase == PH_CRUISE and m.t > 120: break
    assert m.phase == PH_CRUISE
    assert abs(m.pos[1] - ONIKS.cruise_alt_hi) < 800.0

# --- 3M22 Zircon: hypersonic anti-ship (Phase 8) -----------------------------
# The Zircon reuses the Oniks flight machine at Mach 8. Its hi-lo descent must
# bleed altitude proportionally faster (it covers the descent corridor ~3x
# faster than the Mach-2.5 Oniks the descent gains were tuned for) or it
# overflies the target still kilometres high and wallows. Regression measured
# by tools/probe_zircon_traj.py: a 150 km hi-lo shot splashed ~20 km past the
# target after crossing it at 4.4 km overfly altitude.

@pytest.mark.slow
def test_zircon_hi_lo_medium_range_hits():
    target = np.array([0., 0., 150_000.])
    m = Missile(ZIRCON, np.array([0., 60., 0.]), heading=0.0, profile="hi-lo",
                target_point=target)
    w = _World()
    for _ in range(int(400 / DT)):
        m.update(DT, w)
        if not m.alive:
            break
    assert not m.alive and m.impact_pos is not None
    assert np.linalg.norm(m.impact_pos[[0, 2]] - target[[0, 2]]) < 600.0

@pytest.mark.slow
def test_zircon_hi_lo_long_range_hits_and_stays_high():
    """Near the top of the Zircon's hi-lo fuel envelope (~250 km; it is
    fuel-starved past ~100 km and coasts) the long shot keeps its high Mach-8
    cruise (the SM-6 counterplay axis, GAME_ANALYSIS §7) and still dives onto
    the target: the descent fix gives a steeper terminal dive WITHIN the same
    descent corridor, so it must neither throw the high profile away nor
    overfly."""
    target = np.array([0., 0., 250_000.])
    m = Missile(ZIRCON, np.array([0., 60., 0.]), heading=0.0, profile="hi-lo",
                target_point=target)
    w = _World()
    reached_high = False
    for _ in range(int(400 / DT)):
        m.update(DT, w)
        if m.phase == PH_CRUISE and m.pos[1] > 12_000.0:
            reached_high = True
        if not m.alive:
            break
    assert reached_high                       # flew the high Mach-8 cruise
    assert not m.alive and m.impact_pos is not None
    assert np.linalg.norm(m.impact_pos[[0, 2]] - target[[0, 2]]) < 600.0

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

class _CoastWorld:
    """Open ocean ramping onto a 25 m/km coastal slope at z = 499 km
    (mirrors the enemy coast in world.generation near HARBOR KILO)."""
    ships = []
    def terrain_height_at(self, x, z):
        return (z - 499_000.0) * 0.025 if z > 499_000.0 else -50.0

def test_lo_lo_land_strike_rides_the_coast_up_to_the_site():
    """Task 23 spec acceptance ('land targets explode'): a shot at a site
    3 km inland (terrain ~75 m up a 25 m/km slope) must ride its terminal
    skim up the coast and impact at the site — not hold 12 m ASL into the
    beach ~2.5 km short of it."""
    target = np.array([0., 0., 502_000.])
    m = Missile(ONIKS, np.array([0., 60., 452_000.]), heading=0.0,
                profile="lo-lo", target_point=target)
    w = _CoastWorld()
    for _ in range(int(240 / DT)):
        m.update(DT, w)
        if not m.alive:
            break
    assert not m.alive and m.impact_pos is not None
    assert np.linalg.norm(m.impact_pos[[0, 2]] - target[[0, 2]]) < 800.0
    assert m.impact_pos[1] > 30.0           # up on the slope, not the beach


# --- Turn dynamics (user feedback 2026-06-11: no instant path kinks) ----------

def _turn_rate_trace(m, w, seconds):
    """Per-step velocity-direction turn rate (deg/s) over the given window."""
    rates = []
    prev_dir = None
    for _ in range(int(seconds / DT)):
        m.update(DT, w)
        v = m.vel
        s = float(np.linalg.norm(v))
        if s < 1.0:
            continue
        d = (v / s).copy()
        if prev_dir is not None:
            c = min(1.0, max(-1.0, float(d @ prev_dir)))
            rates.append(math.degrees(math.acos(c)) / DT)
        prev_dir = d
    return rates

def test_launch_turn_rate_is_continuous():
    # The flight path may turn fast, but its turn RATE must never jump:
    # the angular-acceleration limit allows ~0.8 deg/s of change per tick
    # (TURN_ACCEL), so any step-to-step jump beyond a small margin is the
    # old single-tick kink (it measured 0 -> 49 deg/s before the fix).
    m = _launch(target=(70_710.0, 0.0, 70_710.0))   # 45-deg off-axis launch
    rates = _turn_rate_trace(m, _World(), 12.0)
    jumps = [abs(b - a) for a, b in zip(rates, rates[1:])]
    assert max(jumps) < 3.0
    assert max(rates) < 80.0          # peak stays near PITCH_RATE_MAX + gravity

def test_body_leads_path_through_pitchover():
    m = _launch(target=(100_000.0, 0.0, 0.0))       # 90-deg off-axis: big turn
    w = _World()
    led = 0
    samples = 0
    while m.phase != PH_BOOST and m.t < 8.0:
        m.update(DT, w)
        if m.phase == PH_PITCHOVER:
            assert abs(float(np.linalg.norm(m.body_dir)) - 1.0) < 1e-9
            v = m.vel / np.linalg.norm(m.vel)
            aoa = math.degrees(math.acos(min(1.0, max(-1.0, float(m.body_dir @ v)))))
            assert aoa <= 10.0 + 1e-6               # AOA_MAX clamp holds
            tilt = m._climb_dir()
            samples += 1
            if float(m.body_dir @ tilt) >= float(v @ tilt) - 1e-12:
                led += 1                            # nose at/ahead of the path
    assert samples > 30
    assert led >= samples * 0.9                     # the nose leads the turn
