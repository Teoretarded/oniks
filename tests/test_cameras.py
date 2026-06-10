"""Task 17: CameraRig math — chase spring, mode transitions, ground clamp.

GL-free: drives the rig with a fake missile (pos/vel only) and an injected
flat-ocean terrain function so every assertion is deterministic.
"""

import numpy as np
import pytest

from engine.camera import Camera
from game.cameras import MODES, TRANSITION_TIME, CameraRig
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
