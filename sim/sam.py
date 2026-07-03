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
from sim.missile import _surface_at
from sim.physics import (GRAVITY, cd_from_mach_scalar, drag_force_scalar,
                         mach_scalar)
from sim.radar import terrain_blocks
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
# tilt toward the predicted intercept point begins. Footage-derived
# (docs/research/s300_tipover_physics.md §3: the declination is visibly
# under way well inside the first second after ignition).
BOOST_VERTICAL_TIME = 0.3      # s

# Tip-over dynamics (normative: docs/research/s300_tipover_physics.md).
# Frame-timed S-300P war-shot footage: ~30 deg from vertical 1.0 s after
# ignition, ~60 deg at 2.0 s — average ~30 deg/s, peak 40-45 deg/s, rate
# ramp ~80-100 deg/s^2. The autopilot PROGRAM is the limiter (vane torque
# over ~6,500 kg*m^2 could pitch far faster), so the body rate is capped at
# the researched 45 deg/s, the ramp at 100 deg/s^2, and the PATH bends no
# faster than the physically available sideforce allows:
#   omega_path <= a_lat / v,  a_lat = thrust * sin(AoA_max) / mass
# (~40 m/s^2 at 18 deg AoA — the old 120 deg/s cap implied an impossible
# 21 g of lateral at 100 m/s; user feel report confirmed by the math).
TILT_ACCEL = math.radians(100.0)     # rad/s^2 (footage ramp)
TILT_RATE_MAX = math.radians(45.0)   # rad/s (footage peak body rate)
BOOST_AOA_SIN = math.sin(math.radians(18.0))   # max boost angle of attack
BRAKE_MARGIN = 0.6   # braking-curve accel budget: arrive with the rate
#                      already bled off (see sim/missile.py _slewed_rate)

# Body attitude (render feel): the airframe slews ahead of the flight path
# (TVC turns the body; the path follows), clamped to AOA_MAX off the
# velocity vector. AOA_MAX matches the researched 18 deg boost AoA — the
# visible nose-lead IS the sideforce generator.
BODY_RATE_LEAD = 1.6
BODY_RATE_MIN = math.radians(20.0)   # rad/s attitude tracking floor
AOA_MAX = math.radians(18.0)
AOA_COS = math.cos(AOA_MAX)

# Predicted-intercept time-to-go: t_go = range / max(closing_speed, FLOOR)
# (locked floor), then one fixed-point refinement on the led point. The cap
# matters early in boost, where the closing speed is tiny and an uncapped
# t_go would lead a crossing target by hundreds of kilometers.
TGO_CLOSING_FLOOR = 50.0       # m/s
TGO_MAX = 90.0                 # s

# Loft shaping (energy management): the commanded altitude sits above the
# aim point by ``loft_gain`` per meter of ground range-to-go beyond the fade
# range, capped at ``loft_bias_max``. Coasting high keeps dynamic pressure
# low enough that the envelope emerges from drag, not from a range gate
# (tuned by sweep, Task S2). The fade range sits just OUTSIDE terminal
# handover so the dive onto the real target is already established when PN
# takes over — handing over at apogee is the 'wallow' the high-loft 40N6
# would suffer if its fade range were not pushed out past its terminal gate.
#
# These three numbers are PER ROUND: they live on the SamDef (loft_gain,
# loft_bias_max, loft_fade_range) so the 48N6 and 40N6 fly genuinely
# different arcs (the 48N6 medium loft ~32 km apogee; the 40N6 a high loft
# toward its 40 km ceiling, reaching far past where the 48N6 self-destructs).
# The baseline default profile (48N6 / SM-2 / SM-6 / Pantsir) is
# loft_gain=0.55, loft_bias_max=14_000, loft_fade_range=25_000.

# Altitude capture: the commanded flight path closes the gap to the loft
# profile over this ground run, clamped to sane climb/dive angles (the steep
# climb cap matters: leaving the dense air fast is what saves the energy).
LOFT_CAPTURE_RUN = 15_000.0    # m
CLIMB_MAX_TAN = math.tan(math.radians(55.0))
DIVE_MAX_TAN = math.tan(math.radians(25.0))

# Midcourse steering: lateral accel = MID_GAIN * angle_error * speed,
# G-limited together with the gravity compensation.
MID_GAIN = 2.2                 # 1/s of angle error

# --- Low-altitude multipath tracking noise (Phase 3 gate: physics, not dice) --
# Against a target down in the sea-clutter/multipath region the surface-
# reflected return interferes with the direct one and the MEASURED target
# position wanders — the classic low-elevation problem that makes sea-
# skimmers the SM-2's hard case (and why Aegis pairs it with CIWS). Modeled
# as a per-axis Ornstein-Uhlenbeck error added to the position the missile
# guides on (BOTH the midcourse contact estimate and the terminal lock):
#     n += (-n / tau) * dt + sigma * sqrt(2 * dt / tau) * randn
# Time-correlated (tau ~ the lobe-flicker decorrelation scale) so PN chases
# a coherently wandering point instead of averaging white jitter out; the
# vertical axis is included because vertical miss is what defeats the 20 m
# fuse. sigma scales linearly with how deep the target sits below the
# threshold altitude and is ZERO above it. The proximity fuse always works
# on truth: misses must EMERGE from guiding on a wandering point, never
# from a kill roll (user law). No rng wired (the default) = zero noise —
# the player's S-300 vs aircraft is bit-identical to before.
MULTIPATH_ALT_M = 150.0   # m: target altitude below which the error grows
MULTIPATH_TAU_S = 0.5     # s: OU correlation time (multipath lobe flicker)
# Multipath is an ANGLE error at the fire-control sensor: the sigma below is
# calibrated AT the reference range (the "3 mrad at 20 km = 60 m" note), so
# the meters of wander SHRINK as the tracking geometry closes (measured
# 2026-07-03: the flat-60 m version made the Pantsir dump a 12-round
# magazine at two 50 m Tomahawks for ~one kill — point defense at 5 km was
# chasing 20 km worth of noise).  Scaled by sensor->target range over the
# reference, capped at 1.0 so every engagement AT or beyond the reference
# keeps the exact tuned behavior (the SM-2 duel bands).
MULTIPATH_REF_RANGE_M = 20_000.0
MULTIPATH_SIGMA_M = 60.0  # m: stationary per-axis RMS error at zero target
#                           altitude (~3 mrad of low-elevation angle error
#                           at 20 km — severe but documented multipath
#                           territory). MEASURED, not guessed: tuned via
#                           tools/probe_sm2_batch.py N=20 seeded battles —
#                           sigma 18 killed the lo-lo Oniks 20/20 (PN low-
#                           passes the tau=0.5 s wander, so the felt miss is
#                           well under the raw sigma); the sweep 30/45/50/
#                           55/60 measured 0.90/0.60/0.60/0.55/0.50
#                           kill-per-engagement. 60.0 locks lo-lo at 0.50
#                           (band 0.25-0.60) with hi-lo untouched at 1.00
#                           (intercepts happen far above MULTIPATH_ALT_M).
#                           Locked by tests/test_sm2_statistics.py.

# --- Terminal lock-break on terrain mask (Phase 3 gate) ------------------------
# While terminal-locked the seeker line of sight is re-checked on a cadence
# (sim/radar.terrain_blocks samples terrain every 2 km — the cadence, not
# per-substep checking, is the hot-path budget). SARH rounds (enemy SM-2)
# check from the LAUNCHING SHIP's illuminator via ``illuminator_pos_fn``;
# rounds without one (player S-300) check from the missile's own seeker.
# A blocked check snaps the lock: the last estimate freezes and the missile
# guides on the frozen point — no reacquire until a later check clears.
LOS_CHECK_PERIOD_S = 0.5  # s between terminal line-of-sight re-checks


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
    """SamDef-driven point-mass interceptor with a phase machine.

    sam_def: SamDef (sim.arsenal.S300, sim.arsenal.SM2, …).
    pos_f64: (3,) float64 tube-mouth / deck-ejector launch position.
    target: truth target duck-typed as any object with ``.pos`` (3,),
        ``.velocity()`` → (3,) float64, and ``.alive`` bool.  Aircraft
        targets also expose ``.kill()``; missile and drone targets do not
        (the fuse sets ``.alive = False`` directly in that case).
    contact_estimate_fn: optional () -> (pos(3,), vel(3,)) giving the stale
        CONTACT picture; used for boost/midcourse aiming when present.
    rng: optional numpy Generator feeding the low-altitude multipath noise
        (a child generator per launch — sim/enemy_defense.py — keeps battles
        deterministic). None (default) = zero noise, bit-identical guidance.
    illuminator_pos_fn: optional () -> (x, y, z) | None giving the SARH
        illuminator position for the terminal LOS check (the SM-2's
        launching ship; None return = illuminator dead, lock breaks).
        Default None = the missile's own seeker is the LOS source.
    """

    def __init__(self, sam_def, pos_f64, target,
                 contact_estimate_fn=None, rng=None, illuminator_pos_fn=None):
        self.weapon = sam_def
        self.pos = np.asarray(pos_f64, dtype=np.float64).copy()
        self.prev_pos = self.pos.copy()
        self.vel = np.zeros(3)
        # NOTE: velocity() below completes the targetable duck-type
        # (Ship/Aircraft/Missile expose it): enemy SM-2s ride the gated
        # ContactBoard feed as hostile air contacts (world/combat.py).
        self.target = target
        self.contact_estimate_fn = contact_estimate_fn
        self.rng = rng
        self.illuminator_pos_fn = illuminator_pos_fn
        # Multipath OU error state (m, world axes) — see MULTIPATH_* above.
        self._mp_x = self._mp_y = self._mp_z = 0.0
        # Fire-control position for the multipath range scaling: the launch
        # site (the tracking radar rides the launcher; SARH rounds override
        # with the live illuminator each step).
        self._fc_pos = (float(self.pos[0]), float(self.pos[1]),
                        float(self.pos[2]))
        # Terminal lock state: next LOS re-check time, lock flag, and the
        # frozen guide point while masked (set at terminal handover).
        self._los_next_t = 0.0
        self._lock_ok = True
        self._lock_pos = None
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
        self._turn_rate = 0.0    # rad/s live path rotation (tilt slew state)
        # Body attitude: dead vertical in the tube; the renderer orients the
        # airframe by this, NOT by the velocity vector.
        self.body_dir = np.array([0.0, 1.0, 0.0])
        self._body_target = None   # boost-tilt aim dir (body leads the path)

    def velocity(self):
        """World-space velocity (3,) float64 — the shared targetable
        duck-type (Ship/Aircraft/Missile expose the same): the gated
        ContactBoard dead-reckons hostile SM-2 contacts through it."""
        return self.vel

    @property
    def mass(self):
        return (self.weapon.launch_mass
                - (self.weapon.propellant_mass - self.propellant))

    @property
    def phase_label(self) -> str:
        """HUD phase text (duck-typed across Missile and SamMissile)."""
        return PHASE_LABELS.get(self.phase, "---")

    # --- mid-flight retargeting (Task RTG) ----------------------------------------

    @property
    def retargetable(self) -> bool:
        """True while the shot can swap targets: BOOST/MIDCOURSE. The eject
        hang is unguided and the terminal seeker is committed."""
        return self.phase in (SPH_BOOST, SPH_MIDCOURSE)

    def retarget(self, new_target, new_waypoints=(), contact_estimate_fn=None):
        """Swap onto ``new_target`` (any duck-typed target) with a fresh
        contact-estimate closure. ``new_waypoints`` exists for signature parity
        with Missile.retarget and is ignored — a SAM flies trackless.
        Returns False (state untouched) when committed."""
        if not self.retargetable:
            return False
        self.target = new_target
        self.contact_estimate_fn = contact_estimate_fn
        return True

    # --- guidance helpers -------------------------------------------------------

    def _target_state(self):
        """(tx, ty, tz, tvx, tvy, tvz): the contact estimate before terminal
        (when supplied), the true aircraft state otherwise. The multipath
        error rides on the position either way — the noise lives in the
        tracking/illumination chain, not in any one data source."""
        if self.phase < SPH_TERMINAL and self.contact_estimate_fn is not None:
            tpos, tvel = self.contact_estimate_fn()
            return (float(tpos[0]) + self._mp_x, float(tpos[1]) + self._mp_y,
                    float(tpos[2]) + self._mp_z,
                    float(tvel[0]), float(tvel[1]), float(tvel[2]))
        tp = self.target.pos
        tv = self.target.velocity()
        return (float(tp[0]) + self._mp_x, float(tp[1]) + self._mp_y,
                float(tp[2]) + self._mp_z,
                float(tv[0]), float(tv[1]), float(tv[2]))

    def _update_multipath(self, dt):
        """One OU step of the per-axis tracking error (only called with an
        rng wired). sigma fades linearly to zero at MULTIPATH_ALT_M and the
        accumulated error DECAYS on tau once the target climbs out of the
        multipath region — no discontinuity at the threshold."""
        f = (MULTIPATH_ALT_M - float(self.target.pos[1])) / MULTIPATH_ALT_M
        sigma = MULTIPATH_SIGMA_M * min(max(f, 0.0), 1.0)
        # Angle-error range scaling (see MULTIPATH_REF_RANGE_M): the sensor
        # is the illuminating ship when one is wired (SARH), else the launch
        # site (the fire-control radar rides the launcher).
        ill = self.illuminator_pos_fn() if self.illuminator_pos_fn else None
        fc = ill if ill is not None else self._fc_pos
        tp0 = self.target.pos
        srng = math.sqrt((float(tp0[0]) - float(fc[0])) ** 2
                         + (float(tp0[1]) - float(fc[1])) ** 2
                         + (float(tp0[2]) - float(fc[2])) ** 2)
        sigma *= min(srng / MULTIPATH_REF_RANGE_M, 1.0)
        k = dt / MULTIPATH_TAU_S
        q = sigma * math.sqrt(2.0 * dt / MULTIPATH_TAU_S)
        rng = self.rng
        self._mp_x += -self._mp_x * k + q * rng.standard_normal()
        self._mp_y += -self._mp_y * k + q * rng.standard_normal()
        self._mp_z += -self._mp_z * k + q * rng.standard_normal()

    def _los_masked(self, world):
        """True when terrain masks the terminal lock. SARH rounds check from
        the illuminator (a dead/None illuminator IS a masked lock — a
        sinking ship stops painting the target); rounds without one check
        from the missile's own seeker. Terrain comes through the world's
        heightfield so stub worlds exercise the same code path."""
        if self.illuminator_pos_fn is not None:
            src = self.illuminator_pos_fn()
            if src is None:
                return True
        else:
            src = self.pos
        return terrain_blocks(src, self.target.pos,
                              height_fn=world.terrain_height_at)

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
        w = self.weapon                # per-round loft (48N6 medium / 40N6 high)
        bias = min(w.loft_gain * max(rg - w.loft_fade_range, 0.0),
                   w.loft_bias_max)
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
        missile dies at the closest-approach point (direct hits included).

        Duck-typed for both Aircraft (has ``kill()``) and any other targetable
        object (``Missile``, future drone) — if ``kill`` is absent the fuse
        sets ``target.alive = False`` directly, which is the common alive-flag
        contract shared across all sim objects."""
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
            kill_fn = getattr(self.target, "kill", None)
            if kill_fn is not None:
                kill_fn()
            else:
                self.target.alive = False
            self.killed_target = True
            # Forensics stamps (WRITE-ONLY): the debrief flight recorder
            # reads these off the dead round; NO sim code ever does — the
            # digest contract is untouched.
            self.target.death_cause = ("sam", str(getattr(
                self.weapon, "weapon_id", "sam")))
            self.target.killed_by = self
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
        if self.rng is not None:               # multipath tracking error
            self._update_multipath(dt)

        px0, alt, pz0 = self.pos.tolist()      # plain floats: scalar-fast math
        vx, vy, vz = self.vel.tolist()
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
            rx = float(tp[0]) - px0
            ry = float(tp[1]) - alt
            rz = float(tp[2]) - pz0
            if (rx * rx + ry * ry + rz * rz
                    < w.terminal_range * w.terminal_range):
                # Seed the frozen guide point from the midcourse estimate
                # BEFORE the phase flips (an immediately masked lock coasts
                # on the honest handover picture), then force an LOS check
                # on the first terminal step.
                tx, ty, tz, _, _, _ = self._target_state()
                self._lock_pos = np.array([tx, ty, tz])
                self._los_next_t = self.t
                self.phase = SPH_TERMINAL

        # --- forces ---
        gx = gy = gz = 0.0                     # guidance accel components
        thrust = 0.0
        drag = 0.0
        if self.phase == SPH_BOOST:
            if self.t >= w.eject_time + BOOST_VERTICAL_TIME and speed > 1e-9:
                dx, dy, dz = self._aim_direction(px0, alt, pz0, vx, vy, vz)
                c = min(max(hx * dx + hy * dy + hz * dz, -1.0), 1.0)
                # Physical path-rate ceiling: sideforce from thrust at the
                # researched max boost AoA, divided by current speed.
                a_lat = w.motor_thrust * BOOST_AOA_SIN / self.mass
                omega_cap = min(a_lat / max(speed, 1.0), TILT_RATE_MAX)
                cmd = min(omega_cap,
                          math.sqrt(2.0 * BRAKE_MARGIN * TILT_ACCEL
                                    * math.acos(c)))
                if cmd > self._turn_rate:
                    self._turn_rate = min(self._turn_rate + TILT_ACCEL * dt,
                                          cmd)
                else:
                    self._turn_rate = max(self._turn_rate - TILT_ACCEL * dt,
                                          cmd)
                hx, hy, hz = _rotate_toward_scalar(hx, hy, hz, dx, dy, dz,
                                                   self._turn_rate * dt)
                self._body_target = (dx, dy, dz)
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
            dx, dy, dz = self._aim_direction(px0, alt, pz0, vx, vy, vz)
            gx, gy, gz = self._steer_accel(hx, hy, hz, speed, dx, dy, dz)
            drag = drag_force_scalar(
                speed, alt, cd_from_mach_scalar(mach_scalar(speed, alt)),
                w.ref_area)
        elif self.phase == SPH_TERMINAL:
            # Terminal lock maintenance: LOS re-check on the cadence; a
            # blocked check freezes the last estimate (no reacquire until a
            # later check clears).
            if self.t >= self._los_next_t:
                self._los_next_t = self.t + LOS_CHECK_PERIOD_S
                self._lock_ok = not self._los_masked(world)
            if self._lock_ok:
                tp = self.target.pos
                tpos = np.array([float(tp[0]) + self._mp_x,
                                 float(tp[1]) + self._mp_y,
                                 float(tp[2]) + self._mp_z])
                tvel = np.asarray(self.target.velocity(), dtype=np.float64)
                self._lock_pos = tpos          # last estimate: frozen on snap
            else:
                tpos = self._lock_pos          # coast on the frozen estimate
                tvel = np.zeros(3)
            g = pn_accel(self.pos, self.vel, tpos, tvel)
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
        px = px0 + vx * dt
        py = alt + vy * dt
        pz = pz0 + vz * dt
        self.pos[0] = px
        self.pos[1] = py
        self.pos[2] = pz

        # --- proximity fuse (truth) ---
        if self._fuse_check():
            return

        # --- surface impact (terrain query skipped above the world ceiling) ---
        if py <= TERRAIN_MAX_HEIGHT:
            surface = _surface_at(world, px, pz)
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
            return

        self._update_body(dt, vx, vy, vz, speed)

    def _update_body(self, dt, vx, vy, vz, speed):
        """Slew the body attitude: leads the path toward the aim direction
        during the boost tilt, tracks the velocity vector everywhere else,
        clamped to AOA_MAX off the path (mirrors sim/missile.py)."""
        if speed < 1e-9:
            return
        inv = 1.0 / speed
        hx, hy, hz = vx * inv, vy * inv, vz * inv
        if self.phase == SPH_BOOST and self._body_target is not None:
            tx, ty, tz = self._body_target
        else:
            tx, ty, tz = hx, hy, hz
        bx, by, bz = self.body_dir.tolist()
        rate = max(self._turn_rate * BODY_RATE_LEAD, BODY_RATE_MIN)
        bx, by, bz = _rotate_toward_scalar(bx, by, bz, tx, ty, tz, rate * dt)
        if bx * hx + by * hy + bz * hz < AOA_COS:
            bx, by, bz = _rotate_toward_scalar(hx, hy, hz, bx, by, bz, AOA_MAX)
        self.body_dir[0] = bx
        self.body_dir[1] = by
        self.body_dir[2] = bz
