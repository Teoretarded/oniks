"""First-person walk controller for the cinematic scenes.

GL-free on purpose (unit tests import this module): the controller is pure
kinematics against two callbacks — a ground-height sampler and an obstacle
query — so it can be stepped headless.  The state that owns it feeds real
mouse/key input and reads ``eye`` for the camera.

Design (locked by the cinematic brief): this is a HUMAN, not a free camera.
Gravity, eye height, walk/sprint speeds and a slope limit keep the player on
the ground; LiDAR lumps taller than a ledge (trees, roofs) are walls, not
ramps.  Units are meters / seconds, axes are the engine's X east, Y up,
Z north.
"""

from __future__ import annotations

import math

EYE_HEIGHT = 1.70          # m above the soles
WALK_SPEED = 1.9           # m/s brisk hike
SPRINT_SPEED = 5.2         # m/s run
GRAVITY = 9.81             # m/s^2
JUMP_SPEED = 3.4           # m/s vertical, a modest hop
MAX_SLOPE = math.radians(38.0)   # steeper ground refuses the step uphill
STEP_LEDGE = 0.55          # m of instant rise a leg can absorb in one step
PITCH_LIMIT = math.radians(89.0)
ACCEL = 24.0               # m/s^2 ground acceleration toward wish velocity
AIR_CONTROL = 0.18         # fraction of ACCEL available while airborne


class Walker:
    """Kinematic first-person humanoid on a heightfield.

    ``ground_h(x, z) -> float`` samples the walkable bare-earth surface;
    ``blocked(x, z) -> bool`` marks cells whose LiDAR surface rises more than
    a ledge above bare earth (tree trunks/canopy, buildings) — impassable.
    """

    def __init__(self, ground_h, blocked=None, pos=(0.0, 0.0),
                 yaw: float = 0.0):
        self.ground_h = ground_h
        self.blocked = blocked or (lambda x, z: False)
        self.x = float(pos[0])
        self.z = float(pos[1])
        self.y = float(ground_h(self.x, self.z))      # soles altitude
        self.vx = 0.0
        self.vy = 0.0
        self.vz = 0.0
        self.yaw = float(yaw)          # 0 = +Z north, positive turns east
        self.pitch = 0.0
        self.on_ground = True
        self.walked = 0.0              # odometer (headbob phase source)

    # ------------------------------------------------------------- input

    def look(self, dyaw: float, dpitch: float) -> None:
        """Mouse-look deltas in radians."""
        self.yaw = (self.yaw + dyaw) % (2.0 * math.pi)
        self.pitch = max(-PITCH_LIMIT, min(PITCH_LIMIT, self.pitch + dpitch))

    def jump(self) -> None:
        if self.on_ground:
            self.vy = JUMP_SPEED
            self.on_ground = False

    # ------------------------------------------------------------- update

    def step(self, dt: float, fwd: float = 0.0, strafe: float = 0.0,
             sprint: bool = False) -> None:
        """Advance ``dt`` with move intent ``fwd``/``strafe`` in [-1, 1]
        (forward along the view yaw; strafe positive to the right)."""
        dt = float(dt)
        if not math.isfinite(dt) or dt <= 0.0:
            return                              # bad clock: a strict no-op
        dt = min(dt, 0.1)                       # a hitch never tunnels
        fwd = float(fwd) if math.isfinite(float(fwd)) else 0.0
        strafe = float(strafe) if math.isfinite(float(strafe)) else 0.0
        sin_y, cos_y = math.sin(self.yaw), math.cos(self.yaw)
        # Wish velocity on the ground plane (yaw only — walking, not flying).
        mag = math.hypot(fwd, strafe)
        if mag > 1.0:
            fwd, strafe = fwd / mag, strafe / mag
        speed = SPRINT_SPEED if sprint else WALK_SPEED
        wish_x = (fwd * sin_y + strafe * cos_y) * speed
        wish_z = (fwd * cos_y - strafe * sin_y) * speed
        accel = ACCEL * (1.0 if self.on_ground else AIR_CONTROL)
        blend = min(1.0, accel * dt / max(speed, 1e-6))
        self.vx += (wish_x - self.vx) * blend
        self.vz += (wish_z - self.vz) * blend

        # Horizontal move: try the full displacement first (axis-separated
        # slope tests are order-dependent — a legal 35 deg DIAGONAL slope
        # must not be judged twice as two steeper axis moves), then fall
        # back to per-axis wall slide so walls are skated along instead of
        # stopping the player dead.
        if not self._move_axis(dt, self.vx, self.vz, zero_on_fail=False):
            self._move_axis(dt, self.vx, 0.0)
            self._move_axis(dt, 0.0, self.vz)

        # Vertical: gravity, then ground clamp.
        h = self.ground_h(self.x, self.z)
        if self.on_ground:
            # Follow the ground down slopes; a >ledge drop becomes a fall.
            if self.y - h > STEP_LEDGE:
                self.on_ground = False
                self.vy = 0.0
            else:
                self.y = h
                self.vy = 0.0
        if not self.on_ground:
            self.vy -= GRAVITY * dt
            self.y += self.vy * dt
            if self.y <= h and self.vy <= 0.0:
                self.y = h
                self.vy = 0.0
                self.on_ground = True
        if self.on_ground:
            self.walked += math.hypot(self.vx, self.vz) * dt

    def _move_axis(self, dt: float, vx: float, vz: float,
                   zero_on_fail: bool = True) -> bool:
        """Attempt one horizontal displacement; True if it was applied.
        ``zero_on_fail=False`` is the full-displacement PROBE — it must not
        kill velocity, or the per-axis wall slide has nothing to slide."""
        if vx == 0.0 and vz == 0.0:
            return True

        def fail() -> bool:
            if zero_on_fail:
                if vx: self.vx = 0.0
                if vz: self.vz = 0.0
            return False

        nx = self.x + vx * dt
        nz = self.z + vz * dt
        if self.blocked(nx, nz):
            return fail()
        h = self.ground_h(nx, nz)
        rise = h - self.y
        if self.on_ground:
            if rise > STEP_LEDGE:
                return fail()
            if rise > 0.0:
                run = math.hypot(vx, vz) * dt
                if math.atan2(rise, max(run, 1e-9)) > MAX_SLOPE:
                    return fail()
        elif rise > STEP_LEDGE:
            # Airborne: ground higher than the feet is a WALL, not a ramp —
            # without this a jump into a cliff face sails inside the
            # terrain and teleports out on landing (GPT-5.6 review).
            return fail()
        self.x = nx
        self.z = nz
        return True

    # ------------------------------------------------------------- camera

    @property
    def eye(self) -> tuple:
        """(x, y, z) of the eyes — soles + eye height."""
        return (self.x, self.y + EYE_HEIGHT, self.z)

    def forward(self) -> tuple:
        """View direction unit vector from yaw/pitch."""
        cp = math.cos(self.pitch)
        return (math.sin(self.yaw) * cp, math.sin(self.pitch),
                math.cos(self.yaw) * cp)
