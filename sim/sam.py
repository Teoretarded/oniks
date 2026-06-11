"""SamMissile: S-300 interceptor phase machine + point-mass integration
(pure numpy/math, GL-free).

Flight: cold catapult eject (vertical, gravity only — a true ballistic HANG
decelerating to near-zero vertical speed 18-32 m up, ignition via the delay
unit 1.5 s after tube exit; Task LC per s300_reference.md) -> solid boost,
pure vertical for its first second then a speed-scaled tilt toward the
predicted intercept point -> post-burnout midcourse coast steering at a LOFTED
predicted-intercept aim (thin air up high is what stretches the coast to the
~150 km practical envelope) -> terminal proportional navigation inside
20 km -> proximity fuse. Self-destructs on flight time or post-burnout speed
floor; the surface kills it like any missile.

Duck-types into ``world.missiles``: pos, vel, alive, prev_pos, impact_pos,
update(dt, world). BOOST/MIDCOURSE aim at the CONTACT estimate when a
``contact_estimate_fn`` is supplied (the player launches on stale tracks);
the terminal seeker and the proximity fuse always use the true aircraft
state, which is what corrects the stale picture.

Hot-loop style per the Task 22 perf pass: per-step math is plain-float
``math`` calls (no per-step numpy scalar dispatch); numpy appears only where
the shared guidance helper (pn_accel) already uses it. Axes per the LOCKED
CONVENTIONS: X = east, Y = up, Z = north.
"""

import math

import numpy as np

from sim.guidance import pn_accel
from sim.physics import (GRAVITY, cd_from_mach_scalar, drag_force_scalar,
                         mach_scalar)
from world.generation import TERRAIN_MAX_HEIGHT

# --- Phase enum (locked: Task S2) ---------------------------------------------
SPH_EJECT, SPH_BOOST, SPH_MIDCOURSE, SPH_TERMINAL, SPH_DEAD = range(5)

# HUD labels (Task S4: the duck-typed ``phase_label`` shared with
# sim.missile.Missile — phase int VALUES collide between the two enums, so
# consumers must never compare raw ints across classes).
PHASE_LABELS = {SPH_EJECT: "EJECT", SPH_BOOST: "BOOST",
                SPH_MIDCOURSE: "MIDCOURSE", SPH_TERMINAL: "TERMINAL",
                SPH_DEAD: "DEAD"}

# --- Tuning constants ----------------------------------------------------------

# Boost: thrust runs pure vertical for this long after ignition before the
# tilt toward the predicted intercept point begins (locked).
BOOST_VERTICAL_TIME = 1.0      # s

# Predicted-intercept time-to-go: t_go = range / max(closing_speed, FLOOR)
# (locked floor), then one fixed-point refinement on the led point. The cap
# matters early in boost, where the closing speed is tiny and an uncapped
# t_go would lead a crossing target by hundreds of kilometers.
TGO_CLOSING_FLOOR = 50.0       # m/s
TGO_MAX = 90.0                 # s

# Loft shaping (energy management): the commanded altitude sits above the
# aim point by LOFT_GAIN per meter of ground range-to-go beyond the fade
# range, capped. Coasting at ~20 km keeps dynamic pressure low enough that
# a 130 km shot arrives ~30 s inside the self-destruct window at ~775 m/s,
# the practical edge sits almost exactly at the locked "max guided range vs
# air ~ 150 km" (a 150 km shot connects at t ~ 179.7 s), and a 200 km shot
# honestly times out ~44 km short — the envelope emerges from drag, not
# from a range gate (tuned by sweep, Task S2). The fade range sits just
# outside terminal handover so the dive onto the real target is already
# established when PN takes over.
LOFT_GAIN = 0.55               # m of altitude bias per m of range-to-go
LOFT_BIAS_MAX = 14_000.0       # m (peak loft 20.5 km < 25 km envelope ceiling)
LOFT_FADE_RANGE = 25_000.0     # m

# Altitude capture: the commanded flight path closes the gap to the loft
# profile over this ground run, clamped to sane climb/dive angles (the steep
# climb cap matters: leaving the dense air fast is what saves the energy).
LOFT_CAPTURE_RUN = 15_000.0    # m
CLIMB_MAX_TAN = math.tan(math.radians(55.0))
DIVE_MAX_TAN = math.tan(math.radians(25.0))

# Midcourse steering: lateral accel = MID_GAIN * angle_error * speed,
# G-limited together with the gravity compensation.
MID_GAIN = 2.2                 # 1/s of angle error


def _rotate_toward_scalar(hx, hy, hz, dx, dy, dz, max_angle):
    """Rotate unit (hx,hy,hz) toward unit (dx,dy,dz) by at most max_angle
    (Rodrigues, plain floats — the boost tilt runs at 120 Hz)."""
    c = hx * dx + hy * dy + hz * dz
    c = min(max(c, -1.0), 1.0)
    angle = math.acos(c)
    if angle <= max_angle or angle < 1e-12:
        return dx, dy, dz
    ax = hy * dz - hz * dy
    ay = hz * dx - hx * dz
    az = hx * dy - hy * dx
    n = math.sqrt(ax * ax + ay * ay + az * az)
    if n < 1e-12:               # anti-parallel: pivot about any perpendicular
        ax, ay, az = (1.0, 0.0, 0.0) if abs(hx) < 0.9 else (0.0, 1.0, 0.0)
        d = ax * hx + ay * hy + az * hz
        ax -= hx * d
        ay -= hy * d
        az -= hz * d
        n = math.sqrt(ax * ax + ay * ay + az * az)
    ax /= n
    ay /= n
    az /= n
    s, co = math.sin(max_angle), math.cos(max_angle)
    cx = ay * hz - az * hy
    cy = az * hx - ax * hz
    cz = ax * hy - ay * hx
    k = (1.0 - co) * (ax * hx + ay * hy + az * hz)
    return (hx * co + cx * s + ax * k,
            hy * co + cy * s + ay * k,
            hz * co + cz * s + az * k)


class SamMissile:
    """48N6-style point-mass interceptor with a phase machine.

    sam_def: SamDef (sim.arsenal.S300).
    pos_f64: (3,) float64 tube-mouth launch position.
    target_aircraft: sim.aircraft.Aircraft — truth source for the terminal
        seeker and the proximity fuse (``kill()`` is called on a fuse hit).
    contact_estimate_fn: optional () -> (pos(3,), vel(3,)) giving the stale
        CONTACT picture; used for boost/midcourse aiming when present.
    """

    def __init__(self, sam_def, pos_f64, target_aircraft,
                 contact_estimate_fn=None):
        self.weapon = sam_def
        self.pos = np.asarray(pos_f64, dtype=np.float64).copy()
        self.prev_pos = self.pos.copy()
        self.vel = np.zeros(3)
        self.target = target_aircraft
        self.contact_estimate_fn = contact_estimate_fn
        self.phase = SPH_EJECT
        self.t = 0.0
        self.propellant = sam_def.propellant_mass
        self.alive = True
        self.impact_pos = None
        # Death-cause flags (Task S4): the world classifies the effects event
        # from these — a fuse kill at 6.5 km must not read as a ground hit.
        self.killed_target = False
        self.self_destructed = False
        self._mdot = sam_def.motor_thrust / (sam_def.isp * GRAVITY)
        self._fuse_r2 = sam_def.fuse_radius * sam_def.fuse_radius

    @property
    def mass(self):
        return (self.weapon.launch_mass
                - (self.weapon.propellant_mass - self.propellant))

    @property
    def phase_label(self) -> str:
        """HUD phase text (duck-typed across Missile and SamMissile)."""
        return PHASE_LABELS.get(self.phase, "---")

    # --- guidance helpers -------------------------------------------------------

    def _target_state(self):
        """(tx, ty, tz, tvx, tvy, tvz): the contact estimate before terminal
        (when supplied), the true aircraft state otherwise."""
        if self.phase < SPH_TERMINAL and self.contact_estimate_fn is not None:
            tpos, tvel = self.contact_estimate_fn()
            return (float(tpos[0]), float(tpos[1]), float(tpos[2]),
                    float(tvel[0]), float(tvel[1]), float(tvel[2]))
        tp = self.target.pos
        tv = self.target.velocity()
        return (float(tp[0]), float(tp[1]), float(tp[2]),
                float(tv[0]), float(tv[1]), float(tv[2]))

    def _aim_direction(self, px, py, pz, vx, vy, vz):
        """Unit direction toward the loft-shaped predicted intercept point:
        t_go = |r| / max(closing, 50) capped, aim = tgt + tgt_vel * t_go with
        one refinement iteration, altitude biased up by the loft profile and
        captured along a clamped climb/dive slope."""
        tx, ty, tz, tvx, tvy, tvz = self._target_state()
        rx = tx - px
        ry = ty - py
        rz = tz - pz
        d = math.sqrt(rx * rx + ry * ry + rz * rz)
        if d < 1.0:
            return 0.0, 1.0, 0.0
        closing = -((tvx - vx) * rx + (tvy - vy) * ry + (tvz - vz) * rz) / d
        t_go = min(d / max(closing, TGO_CLOSING_FLOOR), TGO_MAX)
        ax = tx + tvx * t_go
        ay = ty + tvy * t_go
        az = tz + tvz * t_go
        # one refinement iteration on the led point
        rx = ax - px
        ry = ay - py
        rz = az - pz
        d2 = math.sqrt(rx * rx + ry * ry + rz * rz)
        t_go = min(d2 / max(closing, TGO_CLOSING_FLOOR), TGO_MAX)
        ax = tx + tvx * t_go
        ay = ty + tvy * t_go
        az = tz + tvz * t_go
        # loft profile + slope capture
        gx = ax - px
        gz = az - pz
        rg = math.hypot(gx, gz)
        bias = min(LOFT_GAIN * max(rg - LOFT_FADE_RANGE, 0.0), LOFT_BIAS_MAX)
        slope = (ay + bias - py) / LOFT_CAPTURE_RUN
        slope = min(max(slope, -DIVE_MAX_TAN), CLIMB_MAX_TAN)
        if rg < 1e-6:
            return 0.0, (1.0 if slope >= 0.0 else -1.0), 0.0
        n = math.sqrt(1.0 + slope * slope) * rg
        return gx / n, slope * rg / n, gz / n

    def _steer_accel(self, hx, hy, hz, speed, dx, dy, dz):
        """Midcourse coast steering: lateral accel rotating the velocity
        toward unit (dx,dy,dz), plus gravity compensation, G-limited."""
        dot = dx * hx + dy * hy + dz * hz
        ex = dx - dot * hx
        ey = dy - dot * hy
        ez = dz - dot * hz
        en = math.sqrt(ex * ex + ey * ey + ez * ez)
        gmax = self.weapon.max_g * GRAVITY
        if en > 1e-9:
            err = math.atan2(en, dot)
            a = min(MID_GAIN * err * speed, gmax)
            s = a / en
            gx, gy, gz = ex * s, ey * s + GRAVITY, ez * s
        else:
            gx, gy, gz = 0.0, GRAVITY, 0.0
        n2 = gx * gx + gy * gy + gz * gz
        if n2 > gmax * gmax:
            s = gmax / math.sqrt(n2)
            gx *= s
            gy *= s
            gz *= s
        return gx, gy, gz

    # --- death modes -------------------------------------------------------------

    def _die(self, impact):
        self.impact_pos = impact
        self.phase = SPH_DEAD
        self.alive = False

    def _fuse_check(self):
        """Proximity fuse: if the segment prev_pos -> pos passes within the
        fuse radius of the TRUE target position, the target is killed and the
        missile dies at the closest-approach point (direct hits included)."""
        tp = self.target.pos
        ax, ay, az = self.prev_pos.tolist()
        bx, by, bz = self.pos.tolist()
        dx = bx - ax
        dy = by - ay
        dz = bz - az
        qx = float(tp[0]) - ax
        qy = float(tp[1]) - ay
        qz = float(tp[2]) - az
        denom = dx * dx + dy * dy + dz * dz
        if denom < 1e-12:
            s = 0.0
        else:
            s = min(max((qx * dx + qy * dy + qz * dz) / denom, 0.0), 1.0)
        cx = ax + s * dx
        cy = ay + s * dy
        cz = az + s * dz
        mx = float(tp[0]) - cx
        my = float(tp[1]) - cy
        mz = float(tp[2]) - cz
        if mx * mx + my * my + mz * mz <= self._fuse_r2:
            self.target.kill()
            self.killed_target = True
            self._die(np.array([cx, cy, cz]))
            return True
        return False

    # --- main step -----------------------------------------------------------------

    def update(self, dt, world):
        if not self.alive:
            return
        w = self.weapon
        if self.phase == SPH_EJECT and self.t == 0.0:
            self.vel[1] = w.eject_speed        # catapult: straight up
        np.copyto(self.prev_pos, self.pos)
        self.t += dt

        alt = float(self.pos[1])
        vx, vy, vz = self.vel.tolist()         # plain floats: scalar-fast math
        speed = math.sqrt(vx * vx + vy * vy + vz * vz)
        if speed > 1e-9:
            inv = 1.0 / speed
            hx, hy, hz = vx * inv, vy * inv, vz * inv
        else:
            hx, hy, hz = 0.0, 1.0, 0.0

        # --- phase transitions ---
        if self.phase == SPH_EJECT and self.t >= w.eject_time:
            self.phase = SPH_BOOST
        if self.phase == SPH_BOOST and self.propellant <= 0.0:
            self.phase = SPH_MIDCOURSE
        if self.phase == SPH_MIDCOURSE:
            tp = self.target.pos               # seeker truth at handover
            rx = float(tp[0]) - self.pos[0]
            ry = float(tp[1]) - self.pos[1]
            rz = float(tp[2]) - self.pos[2]
            if (rx * rx + ry * ry + rz * rz
                    < w.terminal_range * w.terminal_range):
                self.phase = SPH_TERMINAL

        # --- forces ---
        gx = gy = gz = 0.0                     # guidance accel components
        thrust = 0.0
        drag = 0.0
        if self.phase == SPH_BOOST:
            if self.t >= w.eject_time + BOOST_VERTICAL_TIME and speed > 1e-9:
                dx, dy, dz = self._aim_direction(
                    self.pos[0], alt, self.pos[2], vx, vy, vz)
                max_ang = w.max_g * GRAVITY / max(speed, 1.0) * dt
                hx, hy, hz = _rotate_toward_scalar(hx, hy, hz,
                                                   dx, dy, dz, max_ang)
                vx, vy, vz = hx * speed, hy * speed, hz * speed
                self.vel[0] = vx
                self.vel[1] = vy
                self.vel[2] = vz
            thrust = w.motor_thrust
            self.propellant = max(0.0, self.propellant - self._mdot * dt)
            drag = drag_force_scalar(
                speed, alt, cd_from_mach_scalar(mach_scalar(speed, alt)),
                w.ref_area)
        elif self.phase == SPH_MIDCOURSE:
            dx, dy, dz = self._aim_direction(
                self.pos[0], alt, self.pos[2], vx, vy, vz)
            gx, gy, gz = self._steer_accel(hx, hy, hz, speed, dx, dy, dz)
            drag = drag_force_scalar(
                speed, alt, cd_from_mach_scalar(mach_scalar(speed, alt)),
                w.ref_area)
        elif self.phase == SPH_TERMINAL:
            tpos = np.asarray(self.target.pos, dtype=np.float64)
            g = pn_accel(self.pos, self.vel, tpos, self.target.velocity())
            gx, gy, gz = g.tolist()
            gy += GRAVITY                      # gravity compensation
            gmax = w.max_g * GRAVITY
            n2 = gx * gx + gy * gy + gz * gz
            if n2 > gmax * gmax:
                s = gmax / math.sqrt(n2)
                gx *= s
                gy *= s
                gz *= s
            drag = drag_force_scalar(
                speed, alt, cd_from_mach_scalar(mach_scalar(speed, alt)),
                w.ref_area)
        # SPH_EJECT: gravity only — no thrust, no guidance, no drag (locked).

        # --- semi-implicit Euler (scalar, Task 22 style) ---
        coef = (thrust - drag) / self.mass
        vx += (hx * coef + gx) * dt
        vy += (hy * coef + gy - GRAVITY) * dt
        vz += (hz * coef + gz) * dt
        self.vel[0] = vx
        self.vel[1] = vy
        self.vel[2] = vz
        px = self.pos[0] + vx * dt
        py = self.pos[1] + vy * dt
        pz = self.pos[2] + vz * dt
        self.pos[0] = px
        self.pos[1] = py
        self.pos[2] = pz

        # --- proximity fuse (truth) ---
        if self._fuse_check():
            return

        # --- surface impact (terrain query skipped above the world ceiling) ---
        if py <= TERRAIN_MAX_HEIGHT:
            surface = max(float(world.terrain_height_at(px, pz)), 0.0)
            if py <= surface:
                self.pos[1] = surface
                self._die(self.pos.copy())
                return

        # --- self-destruct: flight time, or post-burnout speed floor ---
        speed = math.sqrt(vx * vx + vy * vy + vz * vz)
        if (self.t > w.self_destruct_t
                or (self.phase >= SPH_MIDCOURSE
                    and speed < w.self_destruct_speed)):
            self.self_destructed = True
            self._die(self.pos.copy())
