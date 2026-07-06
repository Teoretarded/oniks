"""Camera controllers: FreeCam (Task 9) plus the cinematic CameraRig suite
(chase / orbit / target / launcher with smooth mode transitions, Task 17),
the launch-event camera shake (Task LC) and the player-controlled orbit
camera with wheel zoom + subject cycling (Task CAM).

Pure numpy state — GL-free, unit-testable headless. All eyes are float64.

Task CAM subject model: chase/orbit/target follow whatever ``update`` is
handed as the subject — a live missile, a :class:`StaticSubject` anchored
on a TEL, or a ship/aircraft entity (anything with ``pos``/``vel``). The
``subject_cycle_order``/``next_subject`` helpers define the [ / ] cycle.
"""

from __future__ import annotations

import math

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

# SPECTATE (sandbox war 2026-07-06): a NAMED mode OUTSIDE the C cycle —
# entered only through the war sandbox's spectate flow (map click / the
# bottom plate arrows), it reuses the player-orbit controller verbatim on
# whatever entity is being watched.  Pressing C from spectate re-enters
# the classic cycle at its head; MODES itself is LOCKED (test-pinned) so
# combat's C rotation is untouched.
SPECTATE_MODE = "spectate"
VALID_MODES = MODES + [SPECTATE_MODE]

TRANSITION_TIME = 0.6      # s — slerp-ish blend duration when switching modes
CHASE_BACK = 38.0          # m behind the missile along -vhat
CHASE_UP = 10.0            # m above the missile
CHASE_LOOK_AHEAD = 60.0    # chase look point: missile.pos + vhat * this
CHASE_SPRING_K = 8.0       # critically-damped spring stiffness (1/s)
_SPRING_MAX_DT = 1.0 / 120.0   # substep cap keeps explicit Euler accurate
ORBIT_RADIUS = 60.0        # m default horizontal orbit radius (sets the
ORBIT_ALT = 18.0           # default dist/elevation with this eye height)

# Task CAM: player-controlled orbit + wheel zoom. Drags rotate az/el at
# MOUSE_SENS; the wheel multiplies the spring TARGET by ZOOM_STEP per click
# (exponential steps) and the sprung distance follows critically damped.
# The old always-on auto-orbit became a gentle drift that waits for
# ORBIT_IDLE_DELAY of no player input.
ORBIT_DIST_MIN = 8.0       # m wheel-zoom floor (reads the model close up)
ORBIT_DIST_MAX = 600.0     # m wheel-zoom ceiling (whole launch column)
ORBIT_EL_MIN = math.radians(-5.0)   # just below the horizon
ORBIT_EL_MAX = math.radians(85.0)   # short of the pole (basis degenerates)
ORBIT_DRIFT_RATE = 0.05    # rad/s idle auto-drift
ORBIT_IDLE_DELAY = 5.0     # s of no orbit input before the drift starts
ORBIT_DEFAULT_DIST = math.hypot(ORBIT_RADIUS, ORBIT_ALT)
ORBIT_DEFAULT_EL = math.atan2(ORBIT_ALT, ORBIT_RADIUS)
CHASE_DIST_MIN = 25.0      # m wheel range for the chase follow distance
CHASE_DIST_MAX = 120.0
CHASE_DEFAULT_DIST = math.hypot(CHASE_BACK, CHASE_UP)
ZOOM_STEP = 1.2            # exponential wheel factor per click
TARGET_BACK = 25.0         # m behind the target (away from incoming missile)
TARGET_UP = 25.0           # m above the target
LAUNCHER_DIST = 28.0       # m horizontal eye distance from the TEL
LAUNCHER_UP = 9.0          # m eye height above the TEL base
LAUNCHER_LOOK_UP = 4.5     # aim at canister mid-height on the TEL
GROUND_CLEARANCE = 2.0     # eye.y >= terrain+2 and >= 2 above water (y=0)

# Camera shake (Task LC): small eye perturbation kicked by ignition events
# within SHAKE_RANGE of the camera (linear falloff to zero at the range).
# Amplitude decays exponentially; the offset wobbles on three
# incommensurate frequencies so it never reads as a loop.
SHAKE_RANGE = 2_000.0      # m: events farther than this do not shake
SHAKE_DECAY = 1.9          # 1/s exponential amplitude decay (~0.36 s half-life)
SHAKE_FREQS = (31.0, 24.7, 19.3)   # rad/s per axis
SHAKE_PHASES = (0.0, 1.7, 3.9)
SHAKE_FLOOR = 1e-4         # amplitude below this snaps to exactly zero

# Launcher view sits SE of the TEL looking NW: canister in 3/4 profile with
# the ocean (launch direction, +Z) behind it.
_LAUNCHER_VIEW_DIR = np.array([0.66, 0.0, -0.75])
_LAUNCHER_VIEW_DIR = _LAUNCHER_VIEW_DIR / np.linalg.norm(_LAUNCHER_VIEW_DIR)


def _unit(v):
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else np.array([0.0, 0.0, 1.0])


def _spring_scalar(value, vel, target, dt, k=CHASE_SPRING_K):
    """Critically-damped scalar spring -> (value, vel): the chase cam's
    substepped explicit Euler, so a from-rest approach never overshoots."""
    remaining = dt
    while remaining > 1e-12:
        h = min(remaining, _SPRING_MAX_DT)
        remaining -= h
        acc = k * k * (target - value) - 2.0 * k * vel
        vel += acc * h
        value += vel * h
    return value, vel


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
        self._orbit_az = 0.0                     # player orbit state (CAM)
        self._orbit_el = ORBIT_DEFAULT_EL
        self._orbit_dist = ORBIT_DEFAULT_DIST    # sprung wheel zoom
        self._orbit_dist_target = ORBIT_DEFAULT_DIST
        self._orbit_dist_vel = 0.0
        self._orbit_idle = 0.0                   # s since last orbit input
        self._chase_off = np.zeros(3)            # sprung eye offset (world)
        self._chase_vel = np.zeros(3)
        self._chase_valid = False                # snap spring on (re)entry
        self._chase_dist = CHASE_DEFAULT_DIST    # sprung follow distance
        self._chase_dist_target = CHASE_DEFAULT_DIST
        self._chase_dist_vel = 0.0
        self._shake_amp = 0.0                    # current shake amplitude (m)
        self._shake_t = 0.0                      # wobble clock (s)
        eye, fwd = self._launcher_view()         # sane camera from birth
        self.camera.eye = eye.copy()
        self.camera.set_orientation(fwd)
        self.freecam = FreeCam(eye,
                               yaw=float(np.arctan2(fwd[0], fwd[2])),
                               pitch=float(np.arcsin(np.clip(fwd[1], -1.0, 1.0))))

    # ------------------------------------------------------------- mode API

    def set_mode(self, mode: str) -> None:
        if mode not in VALID_MODES:
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
        """Advance to the next mode in MODES (the C key).  From SPECTATE
        (outside the cycle) C re-enters the classic rotation at its head."""
        if self.mode not in MODES:
            self.set_mode(MODES[0])
            return self.mode
        self.set_mode(MODES[(MODES.index(self.mode) + 1) % len(MODES)])
        return self.mode

    def retarget(self) -> None:
        """Smooth-blend onto the (possibly new) subject's view: called when
        the player cycles the orbit/chase subject or a launch re-aims the
        rig (Task CAM QOL — subject swaps must never snap)."""
        self._start_eye = self.camera.eye.copy()
        self._start_fwd = self.camera.forward.copy()
        self._blend_t = 0.0
        self._chase_valid = False        # chase springs re-snap on arrival

    # ------------------------------------------- player orbit input (CAM)

    @property
    def orbit_az(self) -> float:
        return self._orbit_az

    @property
    def orbit_el(self) -> float:
        return self._orbit_el

    @property
    def orbit_dist(self) -> float:
        """Current sprung orbit distance (m)."""
        return self._orbit_dist

    @property
    def orbit_dist_target(self) -> float:
        return self._orbit_dist_target

    @property
    def chase_dist(self) -> float:
        """Current sprung chase follow distance (m)."""
        return self._chase_dist

    @property
    def chase_dist_target(self) -> float:
        return self._chase_dist_target

    def orbit_drag(self, dx_px: float, dy_px: float) -> None:
        """RMB/LMB drag in orbit mode: rotate around the subject. Drag
        right swings the eye east of it; drag up raises the eye (pygame's
        +y is down-screen, hence the sign). Elevation clamps to
        ORBIT_EL_MIN..MAX; any drag parks the idle drift."""
        self._orbit_az = math.remainder(
            self._orbit_az + dx_px * MOUSE_SENS, math.tau)
        self._orbit_el = float(np.clip(self._orbit_el - dy_px * MOUSE_SENS,
                                       ORBIT_EL_MIN, ORBIT_EL_MAX))
        self._orbit_idle = 0.0

    def zoom(self, steps: float) -> None:
        """Mouse wheel: positive steps zoom IN. Each click multiplies the
        spring TARGET by ZOOM_STEP (exponential steps); the sprung distance
        follows critically damped, so there is no overshoot. Orbit mode
        zooms the orbit distance (8-600 m), chase mode the follow distance
        (25-120 m); other modes ignore the wheel."""
        f = ZOOM_STEP ** (-float(steps))
        if self.mode in ("orbit", SPECTATE_MODE):
            self._orbit_dist_target = float(np.clip(
                self._orbit_dist_target * f, ORBIT_DIST_MIN, ORBIT_DIST_MAX))
            self._orbit_idle = 0.0
        elif self.mode == "chase":
            self._chase_dist_target = float(np.clip(
                self._chase_dist_target * f, CHASE_DIST_MIN, CHASE_DIST_MAX))

    # ----------------------------------------------------- shake (Task LC)

    @property
    def shake_amp(self) -> float:
        """Current shake amplitude in meters (testing/diagnostics)."""
        return self._shake_amp

    def kick_shake(self, amplitude: float, pos=None) -> None:
        """Kick the camera shake to at least ``amplitude`` (m). ``pos``:
        world position of the event — the kick falls off linearly to zero
        at SHAKE_RANGE from the camera eye; ``None`` applies it in full."""
        amp = float(amplitude)
        if pos is not None:
            p = np.asarray(pos, dtype=np.float64)
            d = float(np.linalg.norm(p - self.camera.eye))
            if d >= SHAKE_RANGE:
                return
            amp *= 1.0 - d / SHAKE_RANGE
        if amp > self._shake_amp:
            self._shake_amp = amp

    def _shake_offset(self, dt: float) -> np.ndarray | None:
        """Advance the shake clock/decay; return the eye offset or None."""
        if self._shake_amp <= 0.0:
            return None
        self._shake_t += dt
        self._shake_amp *= math.exp(-SHAKE_DECAY * dt)
        if self._shake_amp < SHAKE_FLOOR:
            self._shake_amp = 0.0
            return None
        t = self._shake_t
        return self._shake_amp * np.array(
            [math.sin(SHAKE_FREQS[0] * t + SHAKE_PHASES[0]),
             math.sin(SHAKE_FREQS[1] * t + SHAKE_PHASES[1]),
             math.sin(SHAKE_FREQS[2] * t + SHAKE_PHASES[2])])

    def set_launcher_pos(self, pos) -> None:
        """Anchor the launcher view on the active platform's TEL (Task S4:
        TAB platform switching). Starts a normal mode-blend so the camera
        sweeps to the other site instead of teleporting."""
        pos = np.asarray(pos, dtype=np.float64).copy()
        if np.array_equal(pos, self._base):
            return
        self._base = pos
        self._start_eye = self.camera.eye.copy()
        self._start_fwd = self.camera.forward.copy()
        self._blend_t = 0.0

    # --------------------------------------------------------------- update

    def update(self, dt: float, missile=None, target_pos=None) -> None:
        """Advance the rig by real (unscaled) dt and write the camera.

        missile: the followed camera subject — a Missile, a StaticSubject
        (TEL) or a ship/aircraft entity (pos/vel float64) — or None.
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
        shake = self._shake_offset(dt)           # ignition events (Task LC)
        if shake is not None:
            eye = self._clamp(eye + shake)
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
        if mode in ("orbit", SPECTATE_MODE) and m is not None:
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
        # Wheel-zoomed follow distance (Task CAM): the sprung scalar scales
        # the stock CHASE_BACK/CHASE_UP offset, so the default distance
        # reproduces the original framing bit-for-bit (scale = 1).
        if self._chase_valid:
            self._chase_dist, self._chase_dist_vel = _spring_scalar(
                self._chase_dist, self._chase_dist_vel,
                self._chase_dist_target, dt)
        else:
            self._chase_dist = self._chase_dist_target
            self._chase_dist_vel = 0.0
        desired_off = ((-vhat * CHASE_BACK + _UP * CHASE_UP)
                       * (self._chase_dist / CHASE_DEFAULT_DIST))
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
        """Player-controlled orbit (Task CAM): az/el from drags, distance
        from the sprung wheel zoom, idle drift after ORBIT_IDLE_DELAY."""
        self._orbit_idle += dt
        if self._orbit_idle >= ORBIT_IDLE_DELAY:
            self._orbit_az += ORBIT_DRIFT_RATE * dt
        self._orbit_dist, self._orbit_dist_vel = _spring_scalar(
            self._orbit_dist, self._orbit_dist_vel,
            self._orbit_dist_target, dt)
        ce = math.cos(self._orbit_el)
        off = self._orbit_dist * np.array(
            [math.sin(self._orbit_az) * ce, math.sin(self._orbit_el),
             math.cos(self._orbit_az) * ce])
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
        tgt = getattr(m, "target", None)        # SamMissile's aircraft
        if tgt is not None:
            return np.asarray(tgt.pos, dtype=np.float64)
        return getattr(m, "target_point", None)

    def _clamp(self, eye):
        """Ground clamp: >= GROUND_CLEARANCE above terrain and water."""
        eye = np.asarray(eye, dtype=np.float64).copy()
        floor = max(self._terrain(float(eye[0]), float(eye[2])), 0.0) + GROUND_CLEARANCE
        if eye[1] < floor:
            eye[1] = floor
        return eye


# ------------------------------------------- camera subjects (Task CAM)

class StaticSubject:
    """Fixed-point camera subject (a TEL): satisfies the same pos/vel
    contract as a missile, is never 'dead' to the rig, and carries no
    ``phase_label`` so the HUD keeps showing the launcher block."""

    __slots__ = ("pos", "vel", "label")

    def __init__(self, pos, label: str = ""):
        self.pos = np.asarray(pos, dtype=np.float64).copy()
        self.vel = np.zeros(3)
        self.label = label


class SpectateSubject:
    """Live proxy camera subject over ANY entity (sandbox-war spectate):
    ships expose velocity() not .vel, parked fighters report alive False,
    subs sit at depth — this adapter normalizes all of them to the rig's
    pos/vel/alive contract while TRACKING the entity (properties, not
    copies).  Carries no ``phase_label`` (HUD keeps the launcher block)."""

    __slots__ = ("entity", "label")

    def __init__(self, entity, label: str = ""):
        self.entity = entity
        self.label = label

    @property
    def pos(self):
        return np.asarray(self.entity.pos, dtype=np.float64)

    @property
    def vel(self):
        e = self.entity
        v = getattr(e, "vel", None)
        if v is not None:
            return np.asarray(v, dtype=np.float64)
        velocity = getattr(e, "velocity", None)
        if callable(velocity):
            return np.asarray(velocity(), dtype=np.float64)
        return np.zeros(3)

    @property
    def alive(self) -> bool:
        # Raw life flag first (a parked fighter's .alive is False by
        # design — hangar semantics); fall back to the alive property.
        flag = getattr(self.entity, "_alive", None)
        if flag is not None:
            return bool(flag)
        return bool(getattr(self.entity, "alive", True))


def subject_cycle_order(missiles, tel_subject=None, contact_entity=None):
    """The [ / ] orbit/chase subject cycle: newest missile first, then the
    other in-flight missiles newest -> oldest, then the active TEL, then
    the selected contact's entity (when still alive). Pure + GL-free."""
    order = [m for m in reversed(list(missiles)) if CameraRig._in_flight(m)]
    if tel_subject is not None:
        order.append(tel_subject)
    if contact_entity is not None and CameraRig._in_flight(contact_entity):
        order.append(contact_entity)
    return order


def next_subject(order, current, step: int = 1):
    """``current``'s cycle neighbor ``step`` places along (wraps both
    ways). A subject that left the cycle (died) or was never set lands on
    the first candidate; an empty cycle returns None."""
    if not order:
        return None
    try:
        i = order.index(current)
    except ValueError:
        return order[0]
    return order[(i + step) % len(order)]
