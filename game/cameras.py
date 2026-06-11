"""Camera controllers: FreeCam (Task 9) plus the cinematic CameraRig suite
(chase / orbit / target / launcher with smooth mode transitions, Task 17).

Pure numpy state — GL-free, unit-testable headless. All eyes are float64.
"""

from __future__ import annotations

import numpy as np

from sim.missile import PH_DEAD
from world import generation

# Free-cam speed tiers (m/s): base / SHIFT (x40) / CTRL+SHIFT (x400).
FREE_SPEEDS = (60.0, 2_400.0, 24_000.0)
MOUSE_SENS = 0.0028                 # radians per mouse pixel
_PITCH_LIMIT = np.radians(89.0)     # stay short of the poles (basis degenerates)
_UP = np.array([0.0, 1.0, 0.0])

# ---------------------------------------------------------------- rig tuning

MODES = ["chase", "orbit", "target", "launcher", "free"]

TRANSITION_TIME = 0.6      # s — slerp-ish blend duration when switching modes
CHASE_BACK = 38.0          # m behind the missile along -vhat
CHASE_UP = 10.0            # m above the missile
CHASE_LOOK_AHEAD = 60.0    # chase look point: missile.pos + vhat * this
CHASE_SPRING_K = 8.0       # critically-damped spring stiffness (1/s)
_SPRING_MAX_DT = 1.0 / 120.0   # substep cap keeps explicit Euler accurate
ORBIT_RADIUS = 60.0        # m horizontal orbit radius around the missile
ORBIT_RATE = 0.15          # rad/s azimuth advance
ORBIT_ALT = 18.0           # m eye height above the missile
TARGET_BACK = 25.0         # m behind the target (away from incoming missile)
TARGET_UP = 25.0           # m above the target
LAUNCHER_DIST = 28.0       # m horizontal eye distance from the TEL
LAUNCHER_UP = 9.0          # m eye height above the TEL base
LAUNCHER_LOOK_UP = 4.5     # aim at canister mid-height on the TEL
GROUND_CLEARANCE = 2.0     # eye.y >= terrain+2 and >= 2 above water (y=0)

# Launcher view sits SE of the TEL looking NW: canister in 3/4 profile with
# the ocean (launch direction, +Z) behind it.
_LAUNCHER_VIEW_DIR = np.array([0.66, 0.0, -0.75])
_LAUNCHER_VIEW_DIR = _LAUNCHER_VIEW_DIR / np.linalg.norm(_LAUNCHER_VIEW_DIR)


def _unit(v):
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else np.array([0.0, 0.0, 1.0])


def _terrain_height_scalar(x, z) -> float:
    """Scalar world heightfield query (generation's fast path)."""
    return generation.terrain_height_scalar(x, z)


class FreeCam:
    """Free-flying camera: float64 position + yaw/pitch orientation.

    Yaw follows the LOCKED heading convention (0 = +Z north, increasing
    clockwise seen from above); pitch is radians above the horizon.
    """

    def __init__(self, pos, yaw: float = 0.0, pitch: float = 0.0):
        self.pos = np.asarray(pos, dtype=np.float64).copy()
        self.yaw = float(yaw)
        self.pitch = float(pitch)

    def look(self, dx_px: float, dy_px: float) -> None:
        """Apply mouse motion in pixels: drag right turns right (clockwise),
        drag down pitches down."""
        self.yaw += dx_px * MOUSE_SENS
        self.pitch = float(np.clip(self.pitch - dy_px * MOUSE_SENS,
                                   -_PITCH_LIMIT, _PITCH_LIMIT))

    @property
    def forward(self) -> np.ndarray:
        cp = np.cos(self.pitch)
        return np.array([np.sin(self.yaw) * cp,
                         np.sin(self.pitch),
                         np.cos(self.yaw) * cp])

    @property
    def right(self) -> np.ndarray:
        """Horizontal right vector (east when facing north)."""
        return np.array([np.cos(self.yaw), 0.0, -np.sin(self.yaw)])

    def move(self, dt: float, fwd: float, strafe: float, lift: float,
             speed: float) -> None:
        """Translate: ``fwd`` along the view direction, ``strafe`` along the
        horizontal right vector, ``lift`` along world up. Axis inputs are
        -1/0/+1; the combined direction is normalized so diagonals are not
        faster."""
        v = self.forward * fwd + self.right * strafe + _UP * lift
        n = float(np.linalg.norm(v))
        if n > 1e-9:
            self.pos += v * (speed * dt / n)

    def apply(self, camera) -> None:
        """Write position/orientation into an engine Camera (float64 eye)."""
        camera.eye = self.pos.copy()
        camera.set_orientation(self.forward)


class CameraRig:
    """Owns the engine Camera, the active mode controller and the smooth
    transition between modes (smoothstep blend over TRANSITION_TIME, eye
    lerped, forward nlerped — "slerp-ish").

    Modes (see MODES): chase / orbit / target follow the missile passed to
    ``update``; with no missile in flight they fall back to the launcher
    view. ``free`` is the Task 9 FreeCam (seeded from the current camera
    pose on entry, so switching into it never jumps).

    Every eye is computed in float64 and ground-clamped:
    ``eye.y >= max(terrain_height(eye.xz), 0) + GROUND_CLEARANCE``.
    """

    MODES = MODES

    def __init__(self, camera, terrain_height_fn=None):
        self.camera = camera
        self.mode = "launcher"
        self._terrain = terrain_height_fn or _terrain_height_scalar
        self._base = np.array(generation.BASE_POS, dtype=np.float64)
        self._blend_t = TRANSITION_TIME          # no transition pending
        self._start_eye = np.zeros(3)
        self._start_fwd = np.array([0.0, 0.0, 1.0])
        self._orbit_az = 0.0
        self._chase_off = np.zeros(3)            # sprung eye offset (world)
        self._chase_vel = np.zeros(3)
        self._chase_valid = False                # snap spring on (re)entry
        eye, fwd = self._launcher_view()         # sane camera from birth
        self.camera.eye = eye.copy()
        self.camera.set_orientation(fwd)
        self.freecam = FreeCam(eye,
                               yaw=float(np.arctan2(fwd[0], fwd[2])),
                               pitch=float(np.arcsin(np.clip(fwd[1], -1.0, 1.0))))

    # ------------------------------------------------------------- mode API

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"unknown camera mode {mode!r}")
        if mode == self.mode:
            return
        self._start_eye = self.camera.eye.copy()
        self._start_fwd = self.camera.forward.copy()
        self._blend_t = 0.0
        if mode == "free":
            # Seamless handoff: the free cam adopts the current camera pose,
            # so there is nothing to blend.
            f = self.camera.forward
            self.freecam.pos = self.camera.eye.copy()
            self.freecam.yaw = float(np.arctan2(f[0], f[2]))
            self.freecam.pitch = float(np.arcsin(np.clip(f[1], -1.0, 1.0)))
            self._blend_t = TRANSITION_TIME
        if mode == "chase":
            self._chase_valid = False
        self.mode = mode

    def cycle_mode(self) -> str:
        """Advance to the next mode in MODES (the C key)."""
        self.set_mode(MODES[(MODES.index(self.mode) + 1) % len(MODES)])
        return self.mode

    # --------------------------------------------------------------- update

    def update(self, dt: float, missile=None, target_pos=None) -> None:
        """Advance the rig by real (unscaled) dt and write the camera.

        missile: the followed Missile (pos/vel float64) or None.
        target_pos: float64 (3,) the missile's victim for target mode; if
        None it is derived from missile.locked_ship / missile.target_point.
        """
        m = missile if self._in_flight(missile) else None
        eye, fwd = self._desired(dt, m, target_pos)
        if self._blend_t < TRANSITION_TIME:
            self._blend_t += dt
            u = min(max(self._blend_t / TRANSITION_TIME, 0.0), 1.0)
            w = u * u * (3.0 - 2.0 * u)          # smoothstep: monotonic
            if w < 1.0:
                eye = self._clamp(self._start_eye * (1.0 - w) + eye * w)
                fwd = _unit(self._start_fwd * (1.0 - w) + fwd * w)  # nlerp
        self.camera.eye = eye.copy()
        self.camera.set_orientation(fwd)

    # ----------------------------------------------------- mode controllers

    def _desired(self, dt, m, target_pos):
        """(eye, forward) for the active mode, ground-clamped, float64."""
        mode = self.mode
        if mode == "free":
            self.freecam.pos = self._clamp(self.freecam.pos)  # no diving
            return self.freecam.pos.copy(), self.freecam.forward
        if mode == "chase" and m is not None:
            return self._chase_view(dt, m)
        if mode == "orbit" and m is not None:
            return self._orbit_view(dt, m)
        if mode == "target" and m is not None:
            tp = target_pos if target_pos is not None else self._missile_target(m)
            if tp is not None:
                return self._target_view(m, tp)
        if m is None:
            self._chase_valid = False            # snap spring on next flight
        return self._launcher_view()

    def _chase_view(self, dt, m):
        speed = float(np.linalg.norm(m.vel))
        vhat = m.vel / speed if speed > 1e-9 else np.array([0.0, 0.0, 1.0])
        desired_off = -vhat * CHASE_BACK + _UP * CHASE_UP
        if not self._chase_valid:
            self._chase_off = desired_off.copy()
            self._chase_vel = np.zeros(3)
            self._chase_valid = True
        else:
            # Critically-damped spring in OFFSET space (eye - missile): the
            # lag responds to direction changes, not to the missile's bulk
            # motion, so the eye never trails hundreds of meters at Mach 2.
            k, remaining = CHASE_SPRING_K, dt
            while remaining > 1e-12:
                h = min(remaining, _SPRING_MAX_DT)
                remaining -= h
                acc = k * k * (desired_off - self._chase_off) - 2.0 * k * self._chase_vel
                self._chase_vel = self._chase_vel + acc * h
                self._chase_off = self._chase_off + self._chase_vel * h
        eye = self._clamp(m.pos + self._chase_off)
        look = m.pos + vhat * CHASE_LOOK_AHEAD
        return eye, _unit(look - eye)

    def _orbit_view(self, dt, m):
        self._orbit_az += ORBIT_RATE * dt
        off = np.array([np.sin(self._orbit_az) * ORBIT_RADIUS, ORBIT_ALT,
                        np.cos(self._orbit_az) * ORBIT_RADIUS])
        eye = self._clamp(np.asarray(m.pos, dtype=np.float64) + off)
        return eye, _unit(np.asarray(m.pos, dtype=np.float64) - eye)

    def _target_view(self, m, target_pos):
        tp = np.asarray(target_pos, dtype=np.float64).copy()
        back = tp - np.asarray(m.pos, dtype=np.float64)
        back[1] = 0.0                            # horizontal "behind" only
        n = float(np.linalg.norm(back))
        back = back / n if n > 1e-6 else np.array([0.0, 0.0, 1.0])
        eye = self._clamp(tp + back * TARGET_BACK + _UP * TARGET_UP)
        return eye, _unit(np.asarray(m.pos, dtype=np.float64) - eye)

    def _launcher_view(self):
        eye = self._clamp(self._base + _LAUNCHER_VIEW_DIR * LAUNCHER_DIST
                          + _UP * LAUNCHER_UP)
        look = self._base + _UP * LAUNCHER_LOOK_UP
        return eye, _unit(look - eye)

    # -------------------------------------------------------------- helpers

    @staticmethod
    def _in_flight(m) -> bool:
        return (m is not None and getattr(m, "alive", True)
                and getattr(m, "phase", None) != PH_DEAD)

    @staticmethod
    def _missile_target(m):
        ship = getattr(m, "locked_ship", None)
        if ship is not None:
            return np.asarray(ship.pos, dtype=np.float64)
        return getattr(m, "target_point", None)

    def _clamp(self, eye):
        """Ground clamp: >= GROUND_CLEARANCE above terrain and water."""
        eye = np.asarray(eye, dtype=np.float64).copy()
        floor = max(self._terrain(float(eye[0]), float(eye[2])), 0.0) + GROUND_CLEARANCE
        if eye[1] < floor:
            eye[1] = floor
        return eye
