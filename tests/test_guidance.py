import numpy as np
from sim.guidance import pn_accel, altitude_hold_accel, steer_heading_accel, waypoint_reached

def _fly_pn(mis_pos, mis_vel, tgt_pos, tgt_vel, t_max=120.0, dt=1/120):
    """Integrate a PN-guided point at constant speed; return min miss distance."""
    mis_pos, mis_vel = mis_pos.copy(), mis_vel.copy()
    speed = np.linalg.norm(mis_vel); best = 1e18
    for _ in range(int(t_max / dt)):
        a = pn_accel(mis_pos, mis_vel, tgt_pos, tgt_vel)
        a = np.clip(a, -110.0, 110.0)             # ~11 g
        mis_vel = mis_vel + a * dt
        mis_vel *= speed / np.linalg.norm(mis_vel)  # constant speed
        mis_pos = mis_pos + mis_vel * dt
        tgt_pos = tgt_pos + tgt_vel * dt
        best = min(best, float(np.linalg.norm(tgt_pos - mis_pos)))
        if best < 3.0: break
    return best

def test_pn_hits_crossing_ship():
    miss = _fly_pn(np.array([0., 12., 0.]), np.array([0., 0., 680.]),
                   np.array([3_000., 8., 30_000.]), np.array([-9., 0., 0.]))
    assert miss < 8.0

def test_pn_hits_fast_crossing_target():
    miss = _fly_pn(np.array([0., 12., 0.]), np.array([0., 0., 680.]),
                   np.array([-5_000., 8., 25_000.]), np.array([14., 0., -6.]))
    assert miss < 8.0

def test_pn_head_on_stays_stable():
    miss = _fly_pn(np.array([0., 12., 0.]), np.array([0., 0., 680.]),
                   np.array([0., 8., 40_000.]), np.array([0., 0., -10.]))
    assert miss < 8.0

def test_pn_accel_perpendicular_to_velocity():
    a = pn_accel(np.zeros(3), np.array([0., 0., 600.]), np.array([5_000., 0., 20_000.]), np.array([-8., 0., 0.]))
    assert abs(a @ np.array([0., 0., 1.])) < 1e-9

def test_altitude_hold_converges():
    alt, vs = 300.0, 0.0
    for _ in range(120 * 60):
        a = altitude_hold_accel(alt, vs, 12.0)
        vs += a * (1/120); alt += vs * (1/120)
    assert abs(alt - 12.0) < 1.0 and abs(vs) < 0.5

def test_steer_heading_turns_correct_way():
    vel = np.array([0., 0., 600.])             # heading 0 (north)
    a = steer_heading_accel(vel, np.radians(20))   # want to turn east
    assert a[0] > 1.0 and abs(a[2]) < abs(a[0])    # accel points east-ish


def test_steer_heading_wraps_angle():
    # heading -170 deg (10 deg west of south); desired +170 deg (10 deg east
    # of south). Shortest turn is 20 deg through due south, swinging the
    # velocity x-component from negative to positive, so the lateral accel
    # points east-ish (a[0] > 0) -- not the 340 deg long way around.
    h = np.radians(-170.0)
    vel = np.array([np.sin(h), 0.0, np.cos(h)]) * 400.0
    a = steer_heading_accel(vel, np.radians(170.0))
    assert a[0] > 0.0


def test_steer_heading_perpendicular_to_velocity():
    h = np.radians(35.0)
    vel = np.array([np.sin(h), 0.0, np.cos(h)]) * 500.0
    a = steer_heading_accel(vel, np.radians(80.0))
    assert abs(a @ vel) < 1e-6 * np.linalg.norm(vel)
    assert abs(a[1]) < 1e-12  # purely horizontal


def test_waypoint_reached_horizontal_only():
    wp = np.array([1_000.0, 0.0, 2_000.0])
    # 1 km horizontal offset, huge altitude difference: still reached (horizontal test)
    assert waypoint_reached(np.array([1_500.0, 9_000.0, 2_000.0]), wp)
    assert not waypoint_reached(np.array([5_000.0, 0.0, 2_000.0]), wp)
    # exactly at radius edge behaves sanely just inside/outside
    assert waypoint_reached(np.array([1_000.0 + 2_499.0, 12.0, 2_000.0]), wp)
    assert not waypoint_reached(np.array([1_000.0 + 2_501.0, 12.0, 2_000.0]), wp)
