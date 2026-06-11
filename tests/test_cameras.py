"""Task 17: CameraRig math — chase spring, mode transitions, ground clamp.

GL-free: drives the rig with a fake missile (pos/vel only) and an injected
flat-ocean terrain function so every assertion is deterministic.
"""

import numpy as np
import pytest

from engine.camera import Camera
from game.cameras import (CHASE_DIST_MAX, CHASE_DIST_MIN, MODES, MOUSE_SENS,
                          ORBIT_DIST_MAX, ORBIT_DIST_MIN, ORBIT_DRIFT_RATE,
                          ORBIT_IDLE_DELAY, TRANSITION_TIME, ZOOM_STEP,
                          CameraRig, StaticSubject, next_subject,
                          subject_cycle_order)
from world.generation import BASE_POS

DT = 1.0 / 60.0


def ocean(x, z):
    """Deep open water everywhere (terrain below sea level)."""
    return -45.0


class FakeMissile:
    """Minimal stand-in: the rig only reads pos/vel/alive/phase/targets."""

    def __init__(self, pos, vel):
        self.pos = np.asarray(pos, dtype=np.float64)
        self.vel = np.asarray(vel, dtype=np.float64)
        self.alive = True
        self.phase = 3  # PH_CRUISE
        self.locked_ship = None
        self.target_point = np.array([0.0, 0.0, 5_000.0])


def launcher_eye():
    """The launcher view eye as a settled reference rig computes it."""
    ref = CameraRig(Camera(), terrain_height_fn=ocean)
    ref.update(DT)
    return ref.camera.eye.copy()


# ---------------------------------------------------------------- plan tests

def test_chase_eye_stays_within_bounds_on_a_curve():
    """Chase eye stays within [25, 70] m of a missile flying a curve."""
    rig = CameraRig(Camera(), terrain_height_fn=ocean)
    rig.set_mode("chase")
    radius, speed, alt = 1_800.0, 250.0, 400.0   # ~3.5 g sustained turn
    om = speed / radius
    m = FakeMissile([radius, alt, 0.0], [0.0, 0.0, speed])
    t = 0.0
    dists = []
    for _ in range(int(12.0 / DT)):
        t += DT
        m.pos = np.array([radius * np.cos(om * t), alt,
                          radius * np.sin(om * t)])
        m.vel = speed * np.array([-np.sin(om * t), 0.0, np.cos(om * t)])
        rig.update(DT, missile=m)
        if t > TRANSITION_TIME + 0.5:           # blend + spring settled
            dists.append(float(np.linalg.norm(rig.camera.eye - m.pos)))
    assert len(dists) > 600
    assert min(dists) >= 25.0
    assert max(dists) <= 70.0


def test_transition_blend_monotonic_and_ends_exactly_on_new_eye():
    """Switching modes blends monotonically and lands EXACTLY on the
    new mode's eye."""
    expected = launcher_eye()

    rig = CameraRig(Camera(), terrain_height_fn=ocean)
    rig.set_mode("free")
    rig.freecam.pos = expected + np.array([260.0, 120.0, -340.0])
    rig.update(DT)                               # camera now at the free pose
    rig.set_mode("launcher")

    prev = float(np.linalg.norm(rig.camera.eye - expected))
    assert prev > 100.0                          # genuinely far away
    for _ in range(int(1.0 / DT)):               # > TRANSITION_TIME
        rig.update(DT)
        d = float(np.linalg.norm(rig.camera.eye - expected))
        assert d <= prev + 1e-9                  # monotonic approach
        prev = d
    assert np.array_equal(rig.camera.eye, expected)   # bit-exact landing


def test_ground_clamp_holds_when_missile_sea_skims_at_12m():
    """Eye never dips below 2 m over water while chasing a 12 m sea-skimmer,
    even through a violent pitch maneuver that would put it underwater."""
    rig = CameraRig(Camera(), terrain_height_fn=ocean)
    rig.set_mode("chase")
    speed = 250.0
    pos = np.array([0.0, 12.0, -2_000.0])
    min_eye_y = np.inf
    t = 0.0
    for _ in range(int(6.0 / DT)):
        t += DT
        if 3.0 <= t < 3.6:                       # violent pitch-up jink
            vdir = np.array([0.0, 0.85, np.sqrt(1.0 - 0.85 ** 2)])
        else:
            vdir = np.array([0.0, 0.0, 1.0])
        vel = vdir * speed
        pos = pos + np.array([vel[0], 0.0, vel[2]]) * DT   # hugs 12 m
        rig.update(DT, missile=FakeMissile(pos, vel))
        if t > TRANSITION_TIME + 0.3:
            assert rig.camera.eye[1] >= 2.0 - 1e-9
            min_eye_y = min(min_eye_y, float(rig.camera.eye[1]))
    # the clamp actually engaged (unclamped eye would have gone underwater)
    assert min_eye_y == pytest.approx(2.0)


# ------------------------------------------------------------- extra checks

def test_chase_falls_back_to_launcher_view_without_missile():
    rig = CameraRig(Camera(), terrain_height_fn=ocean)
    rig.set_mode("chase")
    for _ in range(60):
        rig.update(DT)                           # no missile in flight
    assert np.allclose(rig.camera.eye, launcher_eye(), atol=1e-9)


def test_launcher_eye_geometry():
    eye = launcher_eye()
    base = np.array(BASE_POS, dtype=np.float64)
    assert np.hypot(eye[0] - base[0], eye[2] - base[2]) == pytest.approx(28.0)
    assert eye[1] - base[1] == pytest.approx(9.0)


def test_orbit_keeps_radius_and_looks_at_missile():
    rig = CameraRig(Camera(), terrain_height_fn=ocean)
    rig.set_mode("orbit")
    m = FakeMissile([3_000.0, 300.0, 8_000.0], [0.0, 0.0, 240.0])
    t = 0.0
    checked = 0
    for _ in range(int(3.0 / DT)):
        t += DT
        m.pos = m.pos + m.vel * DT
        rig.update(DT, missile=m)
        if t > TRANSITION_TIME + 0.1:
            off = rig.camera.eye - m.pos
            assert np.hypot(off[0], off[2]) == pytest.approx(60.0)
            assert off[1] == pytest.approx(18.0)
            to_m = m.pos - rig.camera.eye
            to_m /= np.linalg.norm(to_m)
            assert float(to_m @ rig.camera.forward) > 0.999
            checked += 1
    assert checked > 100


def test_entering_free_mode_keeps_current_view():
    rig = CameraRig(Camera(), terrain_height_fn=ocean)
    rig.update(DT)
    eye0 = rig.camera.eye.copy()
    fwd0 = rig.camera.forward.copy()
    rig.set_mode("free")
    rig.update(DT)
    assert np.allclose(rig.camera.eye, eye0, atol=1e-9)
    assert np.allclose(rig.camera.forward, fwd0, atol=1e-6)


def test_modes_list_and_cycle_order():
    assert MODES == ["chase", "orbit", "target", "launcher", "free"]
    rig = CameraRig(Camera(), terrain_height_fn=ocean)
    assert rig.mode == "launcher"
    seen = [rig.cycle_mode() for _ in range(5)]
    assert seen == ["free", "chase", "orbit", "target", "launcher"]


# ------------------------------- Task CAM: player orbit + zoom + subjects

class FakeEntity:
    """Ship/aircraft stand-in: pos/vel + alive flag, no phase_label."""

    def __init__(self, pos, alive=True):
        self.pos = np.asarray(pos, dtype=np.float64)
        self.vel = np.zeros(3)
        self.alive = alive


def settled_orbit_rig(subject, seconds=TRANSITION_TIME + 0.2):
    """An orbit-mode rig blended onto ``subject`` and settled."""
    rig = CameraRig(Camera(), terrain_height_fn=ocean)
    rig.set_mode("orbit")
    for _ in range(int(seconds / DT)):
        rig.update(DT, missile=subject)
    return rig


def test_orbit_drag_maps_pixels_to_az_el():
    """Drag deltas map px -> radians at MOUSE_SENS (drag up raises the eye)
    and the rendered eye sits exactly on the az/el/dist spherical offset."""
    rig = CameraRig(Camera(), terrain_height_fn=ocean)
    rig.set_mode("orbit")
    el0 = rig.orbit_el
    rig.orbit_drag(120.0, 0.0)
    assert rig.orbit_az == pytest.approx(120.0 * MOUSE_SENS)
    rig.orbit_drag(0.0, -80.0)                   # drag UP
    assert rig.orbit_el == pytest.approx(el0 + 80.0 * MOUSE_SENS)
    m = FakeMissile([0.0, 500.0, 0.0], [0.0, 0.0, 200.0])
    for _ in range(int((TRANSITION_TIME + 0.2) / DT)):
        rig.update(DT, missile=m)
    off = rig.camera.eye - m.pos
    d = float(np.linalg.norm(off))
    assert d == pytest.approx(rig.orbit_dist)
    assert off[1] == pytest.approx(d * np.sin(rig.orbit_el))
    assert float(np.arctan2(off[0], off[2])) == pytest.approx(rig.orbit_az)


def test_orbit_elevation_clamps_minus5_to_85_deg():
    rig = CameraRig(Camera(), terrain_height_fn=ocean)
    rig.set_mode("orbit")
    rig.orbit_drag(0.0, -1e6)                    # crank all the way up
    assert rig.orbit_el == pytest.approx(np.radians(85.0))
    rig.orbit_drag(0.0, 1e6)                     # ... and all the way down
    assert rig.orbit_el == pytest.approx(np.radians(-5.0))


def test_orbit_zoom_steps_are_exponential_and_clamped():
    rig = CameraRig(Camera(), terrain_height_fn=ocean)
    rig.set_mode("orbit")
    d0 = rig.orbit_dist_target
    rig.zoom(1)                                  # one click IN
    assert rig.orbit_dist_target == pytest.approx(d0 / ZOOM_STEP)
    rig.zoom(-1)                                 # one click back OUT
    assert rig.orbit_dist_target == pytest.approx(d0)
    rig.zoom(200)
    assert rig.orbit_dist_target == ORBIT_DIST_MIN
    rig.zoom(-500)
    assert rig.orbit_dist_target == ORBIT_DIST_MAX
    assert (ORBIT_DIST_MIN, ORBIT_DIST_MAX) == (8.0, 600.0)


def test_orbit_zoom_spring_converges_without_overshoot():
    m = FakeMissile([0.0, 500.0, 0.0], [0.0, 0.0, 0.0])
    rig = settled_orbit_rig(m)
    rig.zoom(6)                                  # zoom hard IN
    target = rig.orbit_dist_target
    assert target < rig.orbit_dist - 20.0        # a real distance to cover
    prev = rig.orbit_dist
    for _ in range(int(3.0 / DT)):
        rig.update(DT, missile=m)
        d = rig.orbit_dist
        assert d <= prev + 1e-9                  # monotonic approach ...
        assert d >= target - 1e-6                # ... with NO overshoot
        prev = d
    assert prev == pytest.approx(target, abs=0.01)
    assert float(np.linalg.norm(rig.camera.eye - m.pos)) == pytest.approx(prev)


def test_chase_wheel_adjusts_follow_distance_with_clamps():
    rig = CameraRig(Camera(), terrain_height_fn=ocean)
    rig.set_mode("chase")
    m = FakeMissile([0.0, 400.0, 0.0], [0.0, 0.0, 250.0])

    def fly(seconds):
        for _ in range(int(seconds / DT)):
            m.pos = m.pos + m.vel * DT
            rig.update(DT, missile=m)

    fly(TRANSITION_TIME + 1.0)                   # blend + springs settled
    assert (float(np.linalg.norm(rig.camera.eye - m.pos))
            == pytest.approx(np.hypot(38.0, 10.0), abs=0.01))
    rig.zoom(-100)                               # way out: clamps at 120 m
    assert rig.chase_dist_target == CHASE_DIST_MAX
    fly(3.0)
    assert (float(np.linalg.norm(rig.camera.eye - m.pos))
            == pytest.approx(CHASE_DIST_MAX, abs=0.05))
    rig.zoom(200)                                # way in: clamps at 25 m
    assert rig.chase_dist_target == CHASE_DIST_MIN
    fly(3.0)
    assert (float(np.linalg.norm(rig.camera.eye - m.pos))
            == pytest.approx(CHASE_DIST_MIN, abs=0.05))


def test_orbit_drift_only_after_idle_timeout():
    """No auto-drift for ORBIT_IDLE_DELAY after player input; then the
    azimuth advances at ORBIT_DRIFT_RATE. Zoom input parks it again."""
    tel = StaticSubject([0.0, 50.0, 0.0], "TEL")
    rig = settled_orbit_rig(tel)
    rig.orbit_drag(10.0, 0.0)                    # player input: drift parked
    az0 = rig.orbit_az
    for _ in range(int(4.0 / DT)):               # 4.0 s idle: still parked
        rig.update(DT, missile=tel)
    assert rig.orbit_az == az0
    for _ in range(int(4.0 / DT)):               # 8.0 s idle: 3 s of drift
        rig.update(DT, missile=tel)
    assert rig.orbit_az - az0 == pytest.approx(
        ORBIT_DRIFT_RATE * (8.0 - ORBIT_IDLE_DELAY),
        abs=2.0 * ORBIT_DRIFT_RATE * DT)
    rig.zoom(1)                                  # zoom is input too
    az1 = rig.orbit_az
    for _ in range(int(4.0 / DT)):
        rig.update(DT, missile=tel)
    assert rig.orbit_az == az1


def test_zoom_ignored_outside_orbit_and_chase():
    rig = CameraRig(Camera(), terrain_height_fn=ocean)   # launcher mode
    o0, c0 = rig.orbit_dist_target, rig.chase_dist_target
    rig.zoom(5)
    assert rig.orbit_dist_target == o0
    assert rig.chase_dist_target == c0


def test_subject_cycle_order_and_wrap():
    """[ / ] order: newest missile -> other in-flight missiles -> active
    TEL -> selected contact's entity; wraps both ways; dead entries drop."""
    m1 = FakeMissile([0.0, 100.0, 0.0], [0.0, 0.0, 200.0])      # older
    dead = FakeMissile([0.0, 100.0, 0.0], [0.0, 0.0, 200.0])
    dead.alive = False
    m2 = FakeMissile([0.0, 200.0, 0.0], [0.0, 0.0, 200.0])      # newest
    tel = StaticSubject([10.0, 0.0, 20.0], "TEL")
    ship = FakeEntity([500.0, 0.0, 9_000.0])
    order = subject_cycle_order([m1, dead, m2], tel, ship)
    assert order == [m2, m1, tel, ship]
    assert next_subject(order, m2, +1) is m1
    assert next_subject(order, m1, +1) is tel
    assert next_subject(order, tel, +1) is ship
    assert next_subject(order, ship, +1) is m2               # wraps forward
    assert next_subject(order, m2, -1) is ship               # wraps back
    assert next_subject(order, None, +1) is m2               # nothing yet
    assert next_subject(order, dead, +1) is m2               # gone subject
    assert next_subject([], None, +1) is None
    sunk = FakeEntity([0.0, 0.0, 0.0], alive=False)
    assert subject_cycle_order([], tel, sunk) == [tel]


def test_orbit_static_subject_and_smooth_retarget():
    """The orbit cam works on a fixed TEL subject, and retarget() blends
    to a new subject instead of snapping."""
    tel = StaticSubject([0.0, 50.0, 0.0], "TEL")
    rig = settled_orbit_rig(tel)
    assert (float(np.linalg.norm(rig.camera.eye - tel.pos))
            == pytest.approx(rig.orbit_dist))
    eye0 = rig.camera.eye.copy()
    m = FakeMissile([4_000.0, 600.0, 2_000.0], [0.0, 0.0, 0.0])
    ce = np.cos(rig.orbit_el)                    # the new subject's orbit eye
    expected = m.pos + rig.orbit_dist * np.array(
        [np.sin(rig.orbit_az) * ce, np.sin(rig.orbit_el),
         np.cos(rig.orbit_az) * ce])
    rig.retarget()
    rig.update(DT, missile=m)                    # one frame: barely moved
    assert float(np.linalg.norm(rig.camera.eye - eye0)) < 60.0
    prev = float(np.linalg.norm(rig.camera.eye - expected))
    for _ in range(int(1.0 / DT)):               # > TRANSITION_TIME
        rig.update(DT, missile=m)
        d = float(np.linalg.norm(rig.camera.eye - expected))
        assert d <= prev + 1e-9                  # monotonic approach
        prev = d
    assert np.allclose(rig.camera.eye, expected, atol=1e-9)
    assert (float(np.linalg.norm(rig.camera.eye - m.pos))
            == pytest.approx(rig.orbit_dist))
    to_m = m.pos - rig.camera.eye
    to_m /= np.linalg.norm(to_m)
    assert float(to_m @ rig.camera.forward) > 0.999


# ------------------------------------------------- Task LC: camera shake

def test_shake_amplitude_decays_exponentially():
    import numpy as _np
    from game.cameras import SHAKE_DECAY
    rig = CameraRig(Camera(), terrain_height_fn=ocean)
    rig.update(DT)                               # settle the launcher view
    rig.kick_shake(1.0)
    assert rig.shake_amp == pytest.approx(1.0)
    rig.update(DT)
    assert rig.shake_amp == pytest.approx(_np.exp(-SHAKE_DECAY * DT))
    for _ in range(int(1.0 / DT)):
        rig.update(DT)
    assert rig.shake_amp == pytest.approx(
        _np.exp(-SHAKE_DECAY * (1.0 + DT)), rel=1e-6)


def test_shake_perturbs_eye_then_settles():
    ref = CameraRig(Camera(), terrain_height_fn=ocean)
    rig = CameraRig(Camera(), terrain_height_fn=ocean)
    for r in (ref, rig):
        r.update(DT)
    rig.kick_shake(1.0)
    moved = 0.0
    for _ in range(int(0.5 / DT)):
        ref.update(DT)
        rig.update(DT)
        d = float(np.linalg.norm(rig.camera.eye - ref.camera.eye))
        moved = max(moved, d)
        assert d <= rig.shake_amp * np.sqrt(3.0) + 1e-9   # offset bounded
    assert moved > 0.05                          # the shake actually shook
    for _ in range(int(6.0 / DT)):               # ... and dies out
        rig.update(DT)
    assert rig.shake_amp == 0.0
    rig.update(DT)
    ref.update(DT)
    assert np.allclose(rig.camera.eye, ref.camera.eye)


def test_shake_distance_gate_2km():
    from game.cameras import SHAKE_RANGE
    assert SHAKE_RANGE == 2_000.0
    rig = CameraRig(Camera(), terrain_height_fn=ocean)
    rig.update(DT)
    eye = rig.camera.eye.copy()
    far = eye + np.array([2_500.0, 0.0, 0.0])
    rig.kick_shake(1.0, pos=far)                 # beyond range: ignored
    assert rig.shake_amp == 0.0
    near = eye + np.array([1_000.0, 0.0, 0.0])
    rig.kick_shake(1.0, pos=near)                # linear falloff to range
    assert rig.shake_amp == pytest.approx(0.5, abs=0.01)
    rig.kick_shake(0.2, pos=near)                # weaker kick never reduces
    assert rig.shake_amp == pytest.approx(0.5, abs=0.01)
