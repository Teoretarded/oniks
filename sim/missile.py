"""Missile: phase machine + point-mass integration (pure numpy, GL-free).

The Oniks flight (Task LC: hybrid hot launch per docs/research/
oniks_launch_sequence.md): in-tube low-thrust ignition and tube exit at
~30 m/s, a heavy low-thrust vertical RIDE-OUT, nose-cap pulse-jet PITCH-OVER
toward the route bearing, cap jettison straight into the high-thrust BOOST
(burnout at Mach 2, the booster slug is ram-ejected), then the ramjet
climb/cruise (hi-lo or lo-lo profile), ramped descent to a sea-skim, active
seeker terminal homing, splash/impact. All state float64; integration is
semi-implicit Euler at the fixed physics step.

Axes follow the locked conventions: X = east, Y = up, Z = north; heading 0 is
+Z (north) increasing clockwise seen from above.
"""

import math

import numpy as np

from sim.guidance import (altitude_hold_accel, pn_accel, steer_heading_accel,
                          waypoint_reached)
from sim.physics import (GRAVITY, cd_from_mach_scalar, drag_force_scalar,
                         mach_scalar)
from world.generation import TERRAIN_MAX_HEIGHT

# --- Phase enum (locked convention) ------------------------------------------
PH_EJECT, PH_BOOST, PH_CLIMB, PH_CRUISE, PH_DESCENT, PH_TERMINAL, PH_DEAD = range(7)

# Task LC internal launch phases, appended AFTER the locked range so no
# existing value shifts (no consumer orders Oniks phases with </>). PH_EJECT
# now reads as the in-tube ignition + tube-exit beat ("IGNITION" on the HUD).
PH_RIDEOUT, PH_PITCHOVER = 7, 8

# Every phase of the launch cinematic: time accel locks to 1x through these
# and the launch trail/plume effects key off membership (game/sandbox.py).
LAUNCH_PHASES = (PH_EJECT, PH_RIDEOUT, PH_PITCHOVER, PH_BOOST)

# HUD labels for the phase enum (Task S4: ``phase_label`` is the duck-typed
# property shared with sim.sam.SamMissile — the HUD never reads raw phase
# ints, whose values collide between the two enums).
PHASE_LABELS = {PH_EJECT: "IGNITION", PH_RIDEOUT: "RIDE-OUT",
                PH_PITCHOVER: "PITCH-OVER", PH_BOOST: "BOOST",
                PH_CLIMB: "CLIMB", PH_CRUISE: "CRUISE",
                PH_DESCENT: "DESCENT", PH_TERMINAL: "TERMINAL",
                PH_DEAD: "DEAD"}

# --- Tuning constants (controller gains and shaping) --------------------------

# Task LC hot-launch timeline (normative: oniks_launch_sequence.md §3/§6).
# Low-thrust mode burns from t = 0 (in-tube ignition): net accel ~+4 m/s^2
# on top of the ~30 m/s exit — the "heavy ride" beat. The nose-cap pulse
# jets start the tip-over at PITCH_START_T, the turn rate ramps up over
# PITCH_RAMP_T to PITCH_RATE_MAX (ground-launch footage measures 90-120
# deg/s; 62 reads heavy-but-agile from the chase cam), and the cap is shot
# off the moment the velocity vector captures the climb-out direction
# (~3.0-3.5 s) — high-thrust mode ignites the same instant.
RIDEOUT_THRUST = 46_000.0            # N, booster low-thrust mode
PITCH_START_T = 2.0                  # s after exit: pitch-initiate pulse
PITCH_RATE_MAX = np.radians(70.0)    # rad/s peak velocity-vector rotation
PITCH_RAMP_T = 0.8                   # s of rate ramp-in (pulse-jet spin-up)
PITCH_DONE_COS = np.cos(np.radians(2.0))   # capture cone: cap-off trigger
PITCH_MAX_T = 4.6                    # s hard cap on the tip-over
BOOST_END_MACH = 2.0                 # high-thrust burnout -> slug ejection

# Boost attitude hold: keep rotating the velocity direction onto the climb
# direction at up to this rate, targeting the given elevation per profile.
# The lo elevation is shallow on purpose: the real boost leg is the FLAT
# streak of the footage, and the lo-lo profile must stay under ~900 m
# through the full Mach-2 burn.
BOOST_TILT_RATE = np.radians(40.0)   # rad/s of velocity-vector rotation
BOOST_ELEV_HI = np.radians(38.0)     # hi-lo climb-out elevation (full cruise)
BOOST_ELEV_LO = np.radians(12.0)     # lo-lo climb-out elevation (flat streak)
# A hi-lo shot with a scaled-down cruise altitude (close target, Task 22b)
# boosts shallow too — elevation blends LO -> HI as the commanded cruise
# altitude approaches this reference (a 7 s Mach-2 burn at 38 deg would zoom
# a 1 km-cruise shot to 3.5 km).
BOOST_ELEV_REF_ALT = 8_000.0         # m of commanded cruise alt for full HI

# Climb: hand over to cruise once this fraction of cruise altitude is reached;
# the flight-path angle is clamped so the alt-hold's saturated "pull up"
# command rides a clean cruise-climb instead of zooming vertical.
CLIMB_TO_CRUISE_FRAC = 0.92
CLIMB_MAX_TAN = np.tan(np.radians(40.0))   # max climb slope (vy / horiz speed)

# Altitude-hold PD used in climb/cruise/terminal. kd ~ 2*sqrt(kp) is near
# critical damping; max accel 60 m/s^2 (~6 g) is needed so the lo-lo profile
# captures 60 m without ballooning past 900 m after the 25-degree boost.
ALT_KP = 0.35        # 1/s^2
ALT_KD = 1.1         # 1/s
ALT_MAX_A = 60.0     # m/s^2

# Descent: track a target altitude ramped down at DESCENT_RAMP_RATE toward
# skim_alt, with stiffer kp so the dive actually follows the ramp (a plain
# PD straight at skim_alt converges far too slowly from 14 km and overflies
# the target). Vertical speed is clamped >= -DESCENT_MAX_SINK.
DESCENT_KP = 0.08          # 1/s^2
DESCENT_KD = 0.6           # 1/s (zeta ~ 1.06 with kp 0.08)
DESCENT_RAMP_RATE = 220.0  # m/s target-altitude ramp
DESCENT_MAX_SINK = 260.0   # m/s hard vertical-speed clamp

# Task RTG profile accuracy (oniks_reference.md §3: brief seeker fix at
# 50-75 km, then below the radio horizon at skim height): the descent start
# is timed so the missile is AT skim altitude SKIM_CAPTURE_RANGE out —
# descent_range = capture range + the ground covered while the altitude
# ramp runs down + the PD's ramp-following lag (steady-state error
# kd/kp * ramp_rate, closed out at the slow pole) at an assumed ground
# speed, replacing the old geometry-only glide-slope rule.
SKIM_CAPTURE_RANGE = 60_000.0   # m, tunable 50-75 km (plan-fixed center)
DESCENT_RUN_SPEED = 660.0       # m/s assumed ground speed during the letdown
DESCENT_SETTLE_T = 25.0         # s of PD lag closing onto the skim hold
#                                 (tuned: full-cruise capture measures ~60 km)

# Terminal phase starts when below this multiple of skim altitude.
TERMINAL_ALT_FACTOR = 4.0

# Close-range hi-lo handling (Task 22b): a hi-lo shot whose total route ground
# distance is shorter than descent_range * CLOSE_HILO_FACTOR cannot reach full
# cruise altitude without overshooting the target and circling back. The
# commanded cruise altitude scales down quadratically with route length so
# short shots stay low (a 35 km shot commands ~1 km, a 100 km shot ~8 km).
CLOSE_HILO_FACTOR = 1.25

# Inside this range the seeker (or the unguided aim point) gets full 3D PN —
# the final dive out of the sea-skim onto the hull/aim point.
FINAL_PN_RANGE = 800.0     # m

# In-flight route edits (Task RTG) share the tactical map's planning cap.
MAX_ROUTE_WAYPOINTS = 8

# Terminal skim altitude is held above the LOCAL surface (sea or terrain),
# sampled here-and-ahead so the along-track slope feeds the PD's damping term
# (otherwise the kd term fights the climb and the missile flies a 12 m ASL
# line into a rising coast ~2.5 km short of an inland target). Over open
# water both samples are 0 and the maths is bit-identical to a plain
# sea-level hold (Task 23 spec acceptance: land targets explode at the site).
SKIM_LOOKAHEAD = 500.0     # m ahead along track for the slope sample

# Speed controller: thrust = clip(KP_THRUST*(target_mach - mach)*THRUST_SCALE
# + drag_feedforward, 0, max_thrust). The drag feedforward cancels steady-state
# error, so KP_THRUST = 1.0 converges smoothly (first-order, tau ~ 2 s).
KP_THRUST = 1.0
THRUST_SCALE = 4.0e5       # N per Mach of error at KP_THRUST = 1

# Guidance authority fades below this speed (no dynamic pressure -> no lift):
# scale = min(1, (speed/STALL_SPEED)^2). A fuel-starved missile sinks.
STALL_SPEED = 200.0        # m/s

# Terminal evasive weave (Task RTG, oniks_reference.md "erratic terminal
# maneuvers"): lateral S-curve jinks across the last 12 km, full amplitude
# between WEAVE_FULL_RANGE and the ramp-in band, tapered to ZERO by 1.5 km
# so the final run is clean. The jink is applied as a kinematic cross-track
# OVERLAY on top of the homing core (stripped before each integration step,
# re-applied after): the displacement profile is exact and deterministic,
# the g-limited guidance never fights it, and the hit is untouched — the
# rudder-driven jink authority is modeled, not re-derived from the 11 g
# airframe clamp (a 200 m / 4 s weave is ~5x that limit; cinematic spec).
WEAVE_RANGE = 12_000.0       # m range-to-aim at which the jinks start
WEAVE_RAMP_IN = 1_500.0      # m of range over which the amplitude ramps in
WEAVE_FULL_RANGE = 4_500.0   # m: full amplitude until here ...
WEAVE_END_RANGE = 1_500.0    # m: ... then tapered to zero by here
WEAVE_AMP = 200.0            # m cross-track amplitude (plan: 150-250)
WEAVE_OMEGA = 2.0 * math.pi / 4.0   # rad/s (plan: ~4 s period)
WEAVE_PHASE_STEP = 2.399963229728653   # rad per salvo ordinal (golden angle)

_UP = np.array([0.0, 1.0, 0.0])


def _descent_range(weapon, cruise_alt):
    """Range-to-go at which the hi profile starts down, timed so the skim
    is captured at SKIM_CAPTURE_RANGE (Task RTG seeker-fix window)."""
    ramp_s = (cruise_alt - weapon.skim_alt) / DESCENT_RAMP_RATE
    return (SKIM_CAPTURE_RANGE
            + (ramp_s + DESCENT_SETTLE_T) * DESCENT_RUN_SPEED)


def _rotate_toward(vhat, target_dir, max_angle):
    """Rotate unit vector vhat toward unit target_dir by at most max_angle."""
    c = float(np.clip(vhat @ target_dir, -1.0, 1.0))
    angle = float(np.arccos(c))
    if angle <= max_angle or angle < 1e-12:
        return target_dir.copy()
    axis = np.cross(vhat, target_dir)
    n = float(np.linalg.norm(axis))
    if n < 1e-12:   # anti-parallel: pick any perpendicular pivot
        axis = np.array([1.0, 0.0, 0.0]) if abs(vhat[0]) < 0.9 else _UP
        axis = axis - vhat * (axis @ vhat)
        axis /= np.linalg.norm(axis)
    else:
        axis /= n
    s, co = np.sin(max_angle), np.cos(max_angle)
    return vhat * co + np.cross(axis, vhat) * s + axis * (axis @ vhat) * (1.0 - co)


class Missile:
    """P-800-style point-mass missile with a phase machine.

    profile: "hi-lo" (high cruise then descent) or "lo-lo" (low all the way).
    target_point: np(3,) float64 sea-level aim point from the map.
    waypoints: tuple of (x, z) flown before the final target point.
    target_ship: Ship or None — the seeker refines onto a ship at terminal.
    salvo: launch ordinal (Task RTG) — seeds the terminal weave phase so a
        salvo does not jink in formation; deterministic per ordinal.
    """

    def __init__(self, weapon, pos_f64, heading, profile, target_point,
                 waypoints=(), target_ship=None, salvo=0):
        assert profile in ("hi-lo", "lo-lo")
        self.weapon = weapon
        self.pos = np.asarray(pos_f64, dtype=np.float64).copy()
        self.prev_pos = self.pos.copy()
        self.vel = np.zeros(3)
        self.heading = float(heading)
        self.profile = profile
        self.hi = profile == "hi-lo"
        self.target_point = np.asarray(target_point, dtype=np.float64).copy()
        self.target_ship = target_ship
        self.phase = PH_EJECT
        self.t = 0.0
        self.fuel = weapon.fuel_mass
        self.route = [(float(x), float(z)) for (x, z) in waypoints]
        self.route.append((float(self.target_point[0]), float(self.target_point[2])))
        self.locked_ship = None
        self.alive = True
        self.impact_pos = None
        self._plan_vertical_profile()
        self._descent_alt0 = 0.0
        self._descent_elapsed = 0.0
        self._boost_t0 = 0.0     # t at cap jettison / high-thrust ignition
        # Terminal weave overlay state (Task RTG): the currently applied
        # cross-track position/velocity offsets, the weave clock and the
        # per-salvo phase seed.
        self.weave_phi = (int(salvo) * WEAVE_PHASE_STEP) % (2.0 * math.pi)
        self._weave_t = 0.0
        self._weave_x = self._weave_z = 0.0
        self._weave_vx = self._weave_vz = 0.0

    def _plan_vertical_profile(self):
        """Commanded cruise altitude + the range-to-go at which the hi
        profile starts down, from the CURRENT position over the remaining
        route. A hi-lo leg shorter than the descent envelope scales its
        cruise altitude down (quadratically with route length) and
        recomputes the descent range to match, so close targets are hit
        directly instead of overshot from 14 km (Task 22b; reused by
        Task RTG retargeting)."""
        weapon = self.weapon
        self.cruise_alt = weapon.cruise_alt_hi
        self.descent_range = _descent_range(weapon, self.cruise_alt)
        if self.hi:
            pts = [(float(self.pos[0]), float(self.pos[2]))] + self.route
            d_route = sum(np.hypot(x1 - x0, z1 - z0)
                          for (x0, z0), (x1, z1) in zip(pts, pts[1:]))
            envelope = self.descent_range * CLOSE_HILO_FACTOR
            if d_route < envelope:
                self.cruise_alt = max(weapon.lo_alt,
                                      weapon.cruise_alt_hi
                                      * (d_route / envelope) ** 2)
                self.descent_range = _descent_range(weapon, self.cruise_alt)

    @property
    def mass(self):
        return self.weapon.launch_mass - (self.weapon.fuel_mass - self.fuel)

    @property
    def phase_label(self) -> str:
        """HUD phase text (duck-typed across Missile and SamMissile)."""
        return PHASE_LABELS.get(self.phase, "---")

    # --- mid-flight retargeting (Task RTG) -------------------------------------

    @property
    def retargetable(self) -> bool:
        """True while the route can still be redirected: the guided
        CLIMB/CRUISE/DESCENT phases, before the terminal seeker is locked.
        The launch cinematic and the terminal run are committed."""
        return (self.phase in (PH_CLIMB, PH_CRUISE, PH_DESCENT)
                and self.locked_ship is None)

    def retarget(self, new_target, new_waypoints=()):
        """Redirect to ``new_target`` (3,) via optional (x, z) waypoints:
        rebuilds the route from the CURRENT position, re-plans the vertical
        profile (close-range cruise rescale included) and — when the new leg
        is long enough to leave the descent envelope — re-enters CLIMB from
        DESCENT. Returns False (state untouched) once committed."""
        if not self.retargetable:
            return False
        self.target_point = np.asarray(new_target, dtype=np.float64).copy()
        self.target_ship = None
        self.route = [(float(x), float(z)) for (x, z) in new_waypoints]
        self.route.append((float(self.target_point[0]),
                           float(self.target_point[2])))
        self._plan_vertical_profile()
        if self.phase == PH_DESCENT:
            if self._dist_to_target() > self.descent_range:
                self.phase = PH_CLIMB           # long new leg: climb back out
            else:                               # still inside the envelope:
                self._descent_alt0 = float(self.pos[1])   # re-base the ramp
                self._descent_elapsed = 0.0
        return True

    def append_waypoint(self, xz) -> bool:
        """In-flight route edit (map RMB with this round selected): insert
        an (x, z) waypoint just before the final target point. Refused when
        committed or at the MAX_ROUTE_WAYPOINTS cap. The vertical profile is
        deliberately NOT re-planned — a waypoint click must never trigger a
        surprise re-climb."""
        if not self.retargetable or len(self.route) - 1 >= MAX_ROUTE_WAYPOINTS:
            return False
        self.route.insert(len(self.route) - 1, (float(xz[0]), float(xz[1])))
        return True

    def clear_route_waypoints(self) -> bool:
        """Drop the remaining waypoints (map X with this round selected),
        keeping the final target point."""
        if not self.retargetable or len(self.route) <= 1:
            return False
        del self.route[:-1]
        return True

    # --- helpers --------------------------------------------------------------

    def _dist_to_target(self):
        dx = self.pos[0] - self.target_point[0]
        dz = self.pos[2] - self.target_point[2]
        return math.hypot(dx, dz)

    def _route_heading(self):
        wx, wz = self.route[0]
        return math.atan2(wx - self.pos[0], wz - self.pos[2])

    def _climb_dir(self) -> np.ndarray:
        """Unit climb-out direction for pitch-over/boost: toward the first
        route point, at the profile elevation (scaled down with the commanded
        cruise altitude on close hi-lo shots)."""
        if self.hi:
            f = min(self.cruise_alt / BOOST_ELEV_REF_ALT, 1.0)
            elev = BOOST_ELEV_LO + (BOOST_ELEV_HI - BOOST_ELEV_LO) * f
        else:
            elev = BOOST_ELEV_LO
        hd = self._route_heading()
        ce = np.cos(elev)
        return np.array([np.sin(hd) * ce, np.sin(elev), np.cos(hd) * ce])

    def _sustainer_thrust(self, speed, alt, dt):
        """Mach-hold thrust (PI-like: P + drag feedforward); burns ramjet fuel."""
        if self.fuel <= 0.0:
            return 0.0
        w = self.weapon
        target_mach = (w.cruise_mach_hi
                       if self.hi and self.phase in (PH_CLIMB, PH_CRUISE)
                       else w.cruise_mach_lo)
        m_now = mach_scalar(speed, alt)
        cd = cd_from_mach_scalar(m_now)
        drag_ff = drag_force_scalar(speed, alt, cd, w.ref_area)
        thrust = KP_THRUST * (target_mach - m_now) * THRUST_SCALE + drag_ff
        thrust = min(max(thrust, 0.0), w.max_thrust)
        self.fuel = max(0.0, self.fuel - thrust / (w.isp * GRAVITY) * dt)
        return thrust

    def _acquire_lock(self, world, speed):
        """Pick the nearest alive ship inside seeker range and gimbal cone."""
        w = self.weapon
        cos_half = math.cos(math.radians(w.seeker_half_angle_deg))
        best, best_d = None, w.seeker_range
        px, py, pz = self.pos[0], self.pos[1], self.pos[2]
        vx, vy, vz = self.vel[0], self.vel[1], self.vel[2]
        for ship in world.ships:
            if not getattr(ship, "alive", True):
                continue
            sp = ship.pos
            rx = sp[0] - px
            ry = sp[1] - py
            rz = sp[2] - pz
            d = math.sqrt(rx * rx + ry * ry + rz * rz)
            if d >= best_d or d < 1e-6:
                continue
            if speed > 1e-9 and ((rx * vx + ry * vy + rz * vz)
                                 / (d * speed)) < cos_half:
                continue
            best, best_d = ship, d
        if best is not None:
            self.locked_ship = best   # once locked, stays locked

    def _skim_ref(self, alt, vs, world):
        """(altitude, vertical speed) for the terminal skim hold, measured
        against the local surface and its slope along track: returns
        ``(alt - surface, vs - surface_rise_rate)`` so the PD holds skim_alt
        AGL up a coastal slope. Exactly ``(alt, vs)`` over open water."""
        px, pz = self.pos[0], self.pos[2]
        s0 = max(float(world.terrain_height_at(px, pz)), 0.0)
        vx, vz = self.vel[0], self.vel[2]
        hspeed = math.hypot(vx, vz)
        if hspeed < 1e-9:
            return alt - s0, vs
        scale = SKIM_LOOKAHEAD / hspeed
        s1 = max(float(world.terrain_height_at(px + vx * scale,
                                               pz + vz * scale)), 0.0)
        return alt - s0, vs - (s1 - s0) / SKIM_LOOKAHEAD * hspeed

    def _guidance(self, alt, vs, speed, dt, world):
        """Commanded guidance accel (includes gravity compensation 'lift').

        The vertical commands (altitude-hold PD + the gravity-cancel lift)
        are added into component [1] of the freshly-allocated steer/PN
        vector instead of via ``* _UP`` array temporaries (Task 22 perf —
        this runs per missile per 120 Hz substep)."""
        w = self.weapon
        if self.phase == PH_CLIMB:
            g = steer_heading_accel(self.vel, self._route_heading())
            g[1] += altitude_hold_accel(alt, vs, self.cruise_alt,
                                        ALT_KP, ALT_KD, ALT_MAX_A) + GRAVITY
        elif self.phase == PH_CRUISE:
            target_alt = self.cruise_alt if self.hi else w.lo_alt
            g = steer_heading_accel(self.vel, self._route_heading())
            g[1] += altitude_hold_accel(alt, vs, target_alt,
                                        ALT_KP, ALT_KD, ALT_MAX_A) + GRAVITY
        elif self.phase == PH_DESCENT:
            self._descent_elapsed += dt
            ramp = self._descent_alt0 - DESCENT_RAMP_RATE * self._descent_elapsed
            target_alt = max(w.skim_alt, ramp)
            g = steer_heading_accel(self.vel, self._route_heading())
            g[1] += altitude_hold_accel(alt, vs, target_alt,
                                        DESCENT_KP, DESCENT_KD, ALT_MAX_A) + GRAVITY
        else:   # PH_TERMINAL
            if self.locked_ship is None:
                self._acquire_lock(world, speed)
            tgt = self.locked_ship
            if tgt is not None:
                tpos = np.asarray(tgt.pos, dtype=np.float64)
                tvel = np.asarray(getattr(tgt, "vel", np.zeros(3)), dtype=np.float64)
                dx = tpos[0] - self.pos[0]
                dy = tpos[1] - self.pos[1]
                dz = tpos[2] - self.pos[2]
                if math.sqrt(dx * dx + dy * dy + dz * dz) < FINAL_PN_RANGE:
                    g = pn_accel(self.pos, self.vel, tpos, tvel)
                    g[1] += GRAVITY
                else:
                    g = pn_accel(self.pos, self.vel, tpos, tvel)
                    ralt, rvs = self._skim_ref(alt, vs, world)
                    g[1] = (altitude_hold_accel(ralt, rvs, w.skim_alt,
                                                ALT_KP, ALT_KD, ALT_MAX_A)
                            + GRAVITY)
            elif self._dist_to_target() < FINAL_PN_RANGE:
                g = pn_accel(self.pos, self.vel, self.target_point,
                             np.zeros(3))
                g[1] += GRAVITY
            else:
                g = steer_heading_accel(self.vel, self._route_heading())
                ralt, rvs = self._skim_ref(alt, vs, world)
                g[1] += altitude_hold_accel(ralt, rvs, w.skim_alt,
                                            ALT_KP, ALT_KD, ALT_MAX_A) + GRAVITY
        # No dynamic pressure -> no control authority (fuel-starved missiles sink).
        if speed < STALL_SPEED:
            g *= (speed / STALL_SPEED) ** 2
        # G-limit the total commanded accel.
        gmax = w.max_g * GRAVITY
        n2 = g[0] * g[0] + g[1] * g[1] + g[2] * g[2]
        if n2 > gmax * gmax:
            g *= gmax / math.sqrt(n2)
        return g

    # --- main step --------------------------------------------------------------

    def update(self, dt, world):
        if not self.alive:
            return
        w = self.weapon
        if self.phase == PH_EJECT and self.t == 0.0:
            # Hot launch: low-thrust mode is already burning in the tube; the
            # missile clears the muzzle at eject_speed, dead vertical.
            self.vel = np.array([0.0, w.eject_speed, 0.0])
        np.copyto(self.prev_pos, self.pos)
        self.t += dt

        # Strip the terminal weave overlay (Task RTG): the integration below
        # always runs on the clean homing core; the overlay is re-applied at
        # the bottom of the step from the fresh range/clock.
        if self._weave_x != 0.0 or self._weave_z != 0.0:
            self.pos[0] -= self._weave_x
            self.pos[2] -= self._weave_z
            self.vel[0] -= self._weave_vx
            self.vel[2] -= self._weave_vz
            self._weave_x = self._weave_z = 0.0
            self._weave_vx = self._weave_vz = 0.0

        alt = float(self.pos[1])
        vx, vy, vz = self.vel.tolist()         # plain floats: scalar-fast math
        speed = math.sqrt(vx * vx + vy * vy + vz * vz)
        if speed > 1e-9:
            inv = 1.0 / speed
            hx, hy, hz = vx * inv, vy * inv, vz * inv
        else:
            hx, hy, hz = 0.0, 1.0, 0.0

        # Pop reached waypoints (never the final target point). Route entries
        # are (x, z) pairs; waypoint_reached expects a 3-vector.
        while len(self.route) > 1 and waypoint_reached(
                self.pos, (self.route[0][0], 0.0, self.route[0][1])):
            self.route.pop(0)

        # --- phase transitions ---
        if self.phase == PH_EJECT and self.t >= w.eject_time:
            self.phase = PH_RIDEOUT
        if self.phase == PH_RIDEOUT and self.t >= PITCH_START_T:
            self.phase = PH_PITCHOVER
        # PITCHOVER -> BOOST happens in the forces section below (the cap-off
        # trigger needs the freshly rotated velocity direction).
        if self.phase == PH_BOOST and (
                mach_scalar(speed, alt) >= BOOST_END_MACH
                or self.t - self._boost_t0 >= w.booster_time):
            self.phase = PH_CLIMB if self.hi else PH_CRUISE
        if self.phase == PH_CLIMB and alt >= CLIMB_TO_CRUISE_FRAC * self.cruise_alt:
            self.phase = PH_CRUISE
        if self.phase == PH_CRUISE:
            down_range = self.descent_range if self.hi else w.terminal_range
            if self._dist_to_target() < down_range:
                self.phase = PH_DESCENT
                self._descent_alt0 = alt
                self._descent_elapsed = 0.0
        if self.phase == PH_DESCENT and alt < TERMINAL_ALT_FACTOR * w.skim_alt:
            self.phase = PH_TERMINAL

        # --- forces ---
        gx = gy = gz = 0.0                 # guidance accel components
        thrust = 0.0
        drag = 0.0
        if self.phase in (PH_EJECT, PH_RIDEOUT):
            # Low-thrust ride-out: thrust along the (vertical) velocity, net
            # accel small but positive — the heavy, columnar climb.
            thrust = RIDEOUT_THRUST
            drag = drag_force_scalar(
                speed, alt, cd_from_mach_scalar(mach_scalar(speed, alt)),
                w.ref_area)
        elif self.phase == PH_PITCHOVER:
            # Nose-cap pulse jets: rotate the velocity direction toward the
            # climb-out direction at a ramping rate. The instant it captures
            # (or the hard cap expires) the cap is shot off and the
            # high-thrust mode lights — phase BOOST from this same step.
            tilt_dir = self._climb_dir()
            rate = PITCH_RATE_MAX * min(
                (self.t - PITCH_START_T) / PITCH_RAMP_T, 1.0)
            vhat = _rotate_toward(np.array([hx, hy, hz]), tilt_dir, rate * dt)
            hx, hy, hz = vhat.tolist()
            vx, vy, vz = hx * speed, hy * speed, hz * speed
            self.vel[0] = vx
            self.vel[1] = vy
            self.vel[2] = vz
            thrust = RIDEOUT_THRUST
            drag = drag_force_scalar(
                speed, alt, cd_from_mach_scalar(mach_scalar(speed, alt)),
                w.ref_area)
            captured = (hx * tilt_dir[0] + hy * tilt_dir[1]
                        + hz * tilt_dir[2]) >= PITCH_DONE_COS
            if captured or self.t >= PITCH_MAX_T:
                self.phase = PH_BOOST          # cap jettison + full grunt
                self._boost_t0 = self.t
        elif self.phase == PH_BOOST:
            # High-thrust mode: hold the climb-out direction and burn hard
            # until Mach 2 (the transition check at the top of update()).
            vhat = _rotate_toward(np.array([hx, hy, hz]), self._climb_dir(),
                                  BOOST_TILT_RATE * dt)
            hx, hy, hz = vhat.tolist()
            vx, vy, vz = hx * speed, hy * speed, hz * speed
            self.vel[0] = vx
            self.vel[1] = vy
            self.vel[2] = vz
            thrust = w.booster_thrust
            drag = drag_force_scalar(
                speed, alt, cd_from_mach_scalar(mach_scalar(speed, alt)),
                w.ref_area)
        elif self.phase in (PH_CLIMB, PH_CRUISE, PH_DESCENT, PH_TERMINAL):
            thrust = self._sustainer_thrust(speed, alt, dt)
            g = self._guidance(alt, vy, speed, dt, world)
            gx, gy, gz = g.tolist()
            drag = drag_force_scalar(
                speed, alt, cd_from_mach_scalar(mach_scalar(speed, alt)),
                w.ref_area)

        # --- semi-implicit Euler + phase shaping clamps (scalar: Task 22) ---
        coef = (thrust - drag) / self.mass
        vx += (hx * coef + gx) * dt
        vy += (hy * coef + gy - GRAVITY) * dt
        vz += (hz * coef + gz) * dt
        if self.phase == PH_CLIMB:
            max_vy = math.hypot(vx, vz) * CLIMB_MAX_TAN
            if vy > max_vy:
                vy = max_vy
        elif self.phase == PH_DESCENT and vy < -DESCENT_MAX_SINK:
            vy = -DESCENT_MAX_SINK
        self.vel[0] = vx
        self.vel[1] = vy
        self.vel[2] = vz
        px0, py0, pz0 = self.pos.tolist()
        px = px0 + vx * dt
        py = py0 + vy * dt
        pz = pz0 + vz * dt
        self.pos[0] = px
        self.pos[1] = py
        self.pos[2] = pz

        # --- impact (terrain, or the water surface at y = 0) ---
        # Above the world's strict terrain ceiling no surface can be hit, so
        # the heightfield query is skipped (Task 22 perf: saves the query for
        # the whole climb/cruise of a hi profile).
        if py <= TERRAIN_MAX_HEIGHT:
            surface = max(float(world.terrain_height_at(px, pz)), 0.0)
            if py <= surface:
                self.pos[1] = surface
                self.impact_pos = self.pos.copy()
                self.phase = PH_DEAD
                self.alive = False
                return

        # --- terminal weave overlay (Task RTG) ---
        if self.phase == PH_TERMINAL:
            self._apply_weave(dt, vx, vz)

    def _apply_weave(self, dt, vx, vz):
        """Re-apply the evasive S-curve as a cross-track overlay on the core
        state: amplitude ramps in below WEAVE_RANGE, holds WEAVE_AMP, tapers
        to zero by WEAVE_END_RANGE so the final run is straight. Pure scalar
        math (one sin/cos per terminal step — Task 22 hot-loop style)."""
        self._weave_t += dt
        tgt = self.locked_ship.pos if self.locked_ship is not None \
            else self.target_point
        d = math.hypot(float(tgt[0]) - self.pos[0],
                       float(tgt[2]) - self.pos[2])
        if d >= WEAVE_RANGE or d <= WEAVE_END_RANGE:
            return
        hsp = math.hypot(vx, vz)
        if hsp < 1e-9:
            return
        amp = WEAVE_AMP * min((WEAVE_RANGE - d) / WEAVE_RAMP_IN,
                              (d - WEAVE_END_RANGE)
                              / (WEAVE_FULL_RANGE - WEAVE_END_RANGE), 1.0)
        ph = WEAVE_OMEGA * self._weave_t + self.weave_phi
        y = amp * math.sin(ph)
        ydot = amp * WEAVE_OMEGA * math.cos(ph)
        pxh, pzh = vz / hsp, -vx / hsp         # horizontal right-hand perp
        self._weave_x = pxh * y
        self._weave_z = pzh * y
        self._weave_vx = pxh * ydot
        self._weave_vz = pzh * ydot
        self.pos[0] += self._weave_x
        self.pos[2] += self._weave_z
        self.vel[0] += self._weave_vx
        self.vel[2] += self._weave_vz
