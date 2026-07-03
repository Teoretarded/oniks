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

from sim.guidance import (STEER_GAIN, STEER_MAX_A, altitude_hold_accel,
                          pn_accel, waypoint_reached)
from sim.physics import (GRAVITY, cd_from_mach_scalar, drag_force_scalar,
                         mach_scalar, speed_of_sound_scalar)
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
# jets start the tip-over at PITCH_START_T; the turn rate follows a
# TRAPEZOIDAL profile — it can never CHANGE faster than TURN_ACCEL (the
# pulse jets spin a 3 t airframe up and brake it back down), peaks at
# PITCH_RATE_MAX (ground-launch footage measures 90-120 deg/s; 70 reads
# heavy-but-agile from the chase cam) and bleeds off as the climb-out
# direction is captured, so the flight path is a continuous heavy arc with
# no kinks (user feedback 2026-06-11: the path used to corner 0 -> 49 deg/s
# inside one physics tick). The cap is shot off at capture — high-thrust
# mode ignites the same instant, inheriting the live turn rate.
RIDEOUT_THRUST = 46_000.0            # N, booster low-thrust mode
PITCH_START_T = 2.0                  # s after exit: pitch-initiate pulse
PITCH_RATE_MAX = np.radians(70.0)    # rad/s peak path rotation rate
TURN_ACCEL = np.radians(150.0)       # rad/s^2 angular accel limit (launch)
BRAKE_MARGIN = 0.6                   # fraction of TURN_ACCEL the braking
#                                      curve plans with (arrive-slow margin)
PITCH_DONE_COS = np.cos(np.radians(2.0))   # capture cone: cap-off trigger
PITCH_MAX_T = 4.6                    # s hard cap on the tip-over
BOOST_END_MACH = 2.0                 # high-thrust burnout -> slug ejection

# Body attitude (render feel): the airframe rotates AHEAD of the flight path
# — fins/jets turn the body, thrust then drags the velocity around — so the
# nose visibly leads into a turn. The body slews toward the commanded
# direction faster than the path (BODY_RATE_LEAD x the live turn rate, never
# slower than BODY_RATE_MIN for guided-flight tracking) and is clamped to
# AOA_MAX off the velocity vector (a sea-skimmer is not a shopping cart).
BODY_RATE_LEAD = 1.6
BODY_RATE_MIN = np.radians(30.0)     # rad/s attitude tracking floor
AOA_MAX = np.radians(10.0)           # max visible angle of attack
AOA_COS = float(np.cos(AOA_MAX))

# Boost attitude hold: keep rotating the velocity direction onto the climb
# direction at up to this rate, targeting the given elevation per profile.
# The lo elevation is shallow on purpose: the real boost leg is the FLAT
# streak of the footage, and the lo-lo profile must stay under ~900 m
# through the full Mach-2 burn.
BOOST_TILT_RATE = np.radians(40.0)   # rad/s of velocity-vector rotation
BOOST_ELEV_HI = np.radians(38.0)     # hi-lo climb-out elevation (full cruise)
BOOST_ELEV_LO = np.radians(10.5)     # lo-lo climb-out elevation (flat streak;
#                                      10.5 keeps the gravity-comp'd boost
#                                      under the 900 m lo-lo ceiling)
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

# Post-burnout guidance authority ease-in: the fins bite over this window
# instead of stepping to the full saturated command in the single tick the
# booster dies (a 6 g lateral step is an instant path kink on the trail).
GUID_RAMP_T = 0.6    # s

# Descent: track a target altitude ramped down at DESCENT_RAMP_RATE toward
# skim_alt, with stiffer kp so the dive actually follows the ramp (a plain
# PD straight at skim_alt converges far too slowly from 14 km and overflies
# the target). Vertical speed is clamped >= -DESCENT_MAX_SINK.
DESCENT_KP = 0.08          # 1/s^2
DESCENT_KD = 0.6           # 1/s (zeta ~ 1.06 with kp 0.08)
DESCENT_RAMP_RATE = 220.0  # m/s target-altitude ramp
DESCENT_MAX_SINK = 260.0   # m/s hard vertical-speed clamp

# The descent gains above are calibrated for the ~Mach-2.5 Oniks. A faster
# weapon (the Mach-8 Zircon) covers the descent corridor proportionally faster
# at the same range-to-go, so it must bleed altitude proportionally faster or it
# overflies the target still kilometres high and wallows (measured:
# tools/probe_zircon_traj.py — a 150 km hi-lo Zircon crossing the target at
# 4.4 km, splashing ~20 km past). The descent ramp / pull-down authority / sink
# clamp therefore scale by the weapon's hi cruise Mach over this baseline; the
# Oniks ratio is exactly 1.0 (bit-identical), and only the DESCENT phase is
# affected (climb/cruise/terminal altitude-hold keep the unscaled gains). The
# descent START range (``_descent_range``) is left unscaled on purpose: the
# faster missile keeps its long high cruise and only dives crisper — preserving
# the Zircon's high profile as the SM-6 counterplay axis (GAME_ANALYSIS §7).
DESCENT_BASELINE_MACH = 2.55   # ONIKS.cruise_mach_hi (the calibration Mach)

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
# scale = min(1, (speed/stall_speed)^2). A fuel-starved missile sinks.
#
# STALL_SPEED is the Mach-2.5-Oniks-calibrated absolute floor (a fuel-starved
# Oniks bleeding below ~Mach 0.6 has lost its sustainer and sinks). But a flat
# 200 m/s mis-classifies a HEALTHY subsonic airframe: the M4-B SWARM cruises at
# its DESIGN ~85-150 m/s under full power, yet at a flat 200 m/s floor its
# gravity-compensation lift is faded to (130/200)^2 = 0.42, so the alt-hold
# sags it ~38 m UNDER every commanded altitude — at skim_alt that sinks it into
# the sea ~7.5 km short of the target (MEASURED, tools/probe_swarm_descent.py).
# The per-missile stall speed therefore scales to the weapon's OWN slow-cruise
# band: a round is "stalling" when it drops below STALL_MACH_FRAC of its lo
# cruise speed, NOT below the Oniks's absolute number. The ``min(STALL_SPEED,
# ...)`` keeps the LOCKED fast weapons EXACTLY at 200.0 (Oniks lo cruise ~680,
# Zircon ~1531 m/s -> the per-weapon term is >200, so the min returns the
# literal 200.0 float, byte-for-byte) while the subsonic SWARM gets ~51 m/s.
STALL_SPEED = 200.0        # m/s (Oniks calibration; the LOCKED absolute floor)
STALL_MACH_FRAC = 0.6      # fraction of lo cruise speed below which lift fades
STALL_REF_SOUND = 340.3    # m/s, fixed sea-level a (deterministic reference)

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


def _surface_at(world, x: float, z: float) -> float:
    """Impact/skim surface max(terrain, 0) — through the world's fast
    open-water path when it has one (Task GATE perf), with the plain
    terrain query as the fallback for minimal world stubs."""
    f = getattr(world, "surface_height_at", None)
    if f is not None:
        return f(x, z)
    return max(float(world.terrain_height_at(x, z)), 0.0)


def _steer_heading_scalar(vx: float, vz: float, desired_heading: float):
    """guidance.steer_heading_accel on plain floats: returns the (x, z)
    lateral-accel components (the y component is always 0). Identical
    float ops in identical order — no per-substep array temporaries
    (Task GATE perf)."""
    horiz_speed = math.hypot(vx, vz)
    if horiz_speed < 1e-9:
        return 0.0, 0.0
    heading = math.atan2(vx, vz)
    err = (desired_heading - heading + math.pi) % (2.0 * math.pi) - math.pi
    a_lat = STEER_GAIN * err * horiz_speed
    a_lat = min(max(a_lat, -STEER_MAX_A), STEER_MAX_A)
    s = a_lat / horiz_speed
    return vz * s, -vx * s


def _descent_range(weapon, cruise_alt):
    """Range-to-go at which the hi profile starts down, timed so the skim
    is captured at SKIM_CAPTURE_RANGE (Task RTG seeker-fix window). The
    capture margin is held constant across weapons on purpose: it is the
    speed-bleed / terminal-run-in room the homing phase needs, and shrinking
    it lets a hypersonic round arrive low but too fast and overshoot the
    target horizontally (measured). Faster weapons instead get a STEEPER dive
    inside this same corridor (self._descent_scale in the DESCENT guidance).

    A weapon with an EXPLICIT per-weapon profile (descent_range_m set on the
    arsenal def) overrides this timing wholesale — the formula above encodes
    the Oniks letdown; a hypersonic round that must dive LATE and arrive FAST
    (measured: the Zircon handed over 100 km out spent >200 s at sea level
    and died at 159 m/s, 7 km short) declares its own start range instead."""
    if weapon.descent_range_m > 0.0:
        return weapon.descent_range_m
    ramp_s = (cruise_alt - weapon.skim_alt) / DESCENT_RAMP_RATE
    return (SKIM_CAPTURE_RANGE
            + (ramp_s + DESCENT_SETTLE_T) * DESCENT_RUN_SPEED)


def _slewed_rate(turn_rate, angle_rem, rate_max, dt):
    """Trapezoidal turn-rate profile: accelerate toward the commanded peak,
    brake as the remaining angle shrinks, and never change the rate faster
    than TURN_ACCEL — the physical guarantee that the flight path has
    continuous curvature (no single-tick rate jumps). The braking curve
    budgets only BRAKE_MARGIN of the available angular acceleration so the
    rotation always reaches the target direction with the rate already bled
    off (a full-budget curve arrives carrying ~20 deg/s and stops dead in
    one tick — the snap the curve exists to prevent)."""
    cmd = min(rate_max, math.sqrt(2.0 * BRAKE_MARGIN * TURN_ACCEL
                                  * max(angle_rem, 0.0)))
    if cmd > turn_rate:
        return min(turn_rate + TURN_ACCEL * dt, cmd)
    return max(turn_rate - TURN_ACCEL * dt, cmd)


def _rotate_toward_scalar(hx, hy, hz, dx, dy, dz, max_angle):
    """_rotate_toward on plain floats (Rodrigues) — the per-substep body
    attitude update runs through here (Task 22 hot-loop style)."""
    c = hx * dx + hy * dy + hz * dz
    c = min(max(c, -1.0), 1.0)
    angle = math.acos(c)
    if angle <= max_angle or angle < 1e-12:
        return dx, dy, dz
    ax = hy * dz - hz * dy
    ay = hz * dx - hx * dz
    az = hx * dy - hy * dx
    n = math.sqrt(ax * ax + ay * ay + az * az)
    if n < 1e-12:                      # anti-parallel: arbitrary perpendicular
        ax, ay, az = (1.0, 0.0, 0.0) if abs(hx) < 0.9 else (0.0, 1.0, 0.0)
        d = ax * hx + ay * hy + az * hz
        ax, ay, az = ax - hx * d, ay - hy * d, az - hz * d
        n = math.sqrt(ax * ax + ay * ay + az * az)
    ax, ay, az = ax / n, ay / n, az / n
    s, co = math.sin(max_angle), math.cos(max_angle)
    k = (ax * hx + ay * hy + az * hz) * (1.0 - co)
    return (hx * co + (ay * hz - az * hy) * s + ax * k,
            hy * co + (az * hx - ax * hz) * s + ay * k,
            hz * co + (ax * hy - ay * hx) * s + az * k)


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
        # Speed-proportional descent authority (see DESCENT_BASELINE_MACH):
        # >= 1.0 so a slower-than-Oniks weapon never gets a GENTLER dive. Set
        # before _plan_vertical_profile so the descent-range timing reads it.
        self._descent_scale = max(
            1.0, weapon.cruise_mach_hi / DESCENT_BASELINE_MACH)
        # Per-weapon descent profile (arsenal fields; 0.0 = the Oniks-tuned
        # module defaults with their speed-ratio scaling — bit-identical
        # arithmetic for every weapon that leaves them unset).
        self._descent_ramp_rate = (
            weapon.descent_ramp_rate if weapon.descent_ramp_rate > 0.0
            else DESCENT_RAMP_RATE * self._descent_scale)
        self._descent_max_sink = (
            weapon.descent_max_sink if weapon.descent_max_sink > 0.0
            else DESCENT_MAX_SINK * self._descent_scale)
        self._final_pn_range = (
            weapon.final_pn_range_m if weapon.final_pn_range_m > 0.0
            else FINAL_PN_RANGE)
        # Per-weapon stall speed (see STALL_SPEED): the lift-fade floor scales
        # to the weapon's own slow-cruise band so a HEALTHY subsonic round keeps
        # full guidance authority and holds its skim altitude. The min() keeps
        # the LOCKED fast weapons (Oniks/Zircon) at EXACTLY 200.0 m/s, so the
        # fade arithmetic is byte-for-byte unchanged for them.
        self._stall_speed = min(
            STALL_SPEED, STALL_MACH_FRAC * weapon.cruise_mach_lo * STALL_REF_SOUND)
        self._plan_vertical_profile()
        self._descent_alt0 = 0.0
        self._descent_elapsed = 0.0
        self._boost_t0 = 0.0     # t at cap jettison / high-thrust ignition
        self._turn_rate = 0.0    # rad/s live path rotation (launch slew state)
        self._guid_t0 = None     # set at burnout: guidance ease-in clock
        # Body attitude: starts dead vertical in the canister; the renderer
        # orients the airframe by this, NOT by the velocity vector.
        self.body_dir = np.array([0.0, 1.0, 0.0])
        # Terminal weave overlay state (Task RTG): the currently applied
        # cross-track position/velocity offsets, the weave clock and the
        # per-salvo phase seed.
        self.salvo = int(salvo)
        self.weave_phi = (int(salvo) * WEAVE_PHASE_STEP) % (2.0 * math.pi)
        self._weave_t = 0.0
        self._weave_x = self._weave_z = 0.0
        self._weave_vx = self._weave_vz = 0.0
        # M4-B loitering swarm: an optional COMMANDED ground speed for the
        # cruise Mach-hold (sim/swarm.compute_swarm_speeds sets it per round so
        # a bundle reaches the aim point simultaneously).  UNSET (None) is the
        # LOCKED contract: the _sustainer_thrust Mach-hold then runs the exact
        # existing arithmetic, byte-for-byte (tests/test_swarm.py guard).
        self._commanded_speed = None

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

    def velocity(self):
        """World-space velocity (3,) float64 — the shared targetable
        duck-type (Ship/Aircraft expose the same): an interceptor's PN and
        proximity fuse (sim/sam.py) read the target through it, which is
        how an SM-2 engages an Oniks in COMBAT mode."""
        return self.vel

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

    def _sustainer_thrust(self, m_now, drag_ff, dt, alt=0.0):
        """Mach-hold thrust (PI-like: P + drag feedforward); burns ramjet
        fuel. ``m_now``/``drag_ff`` are the caller's already-computed Mach
        and drag (Task GATE perf: one atmosphere evaluation per step).

        M4-B: when ``self._commanded_speed`` is set (the loitering swarm's
        per-round time-on-target ground speed), the target Mach is that
        commanded GROUND speed expressed in the LOCAL atmosphere
        (commanded / speed_of_sound(alt)) instead of the weapon cruise Mach.
        The override is GUARDED so the UNSET (None) path is byte-for-byte the
        existing arithmetic — no reordering, the cruise_mach_* selection and
        the thrust line are untouched (the LOCKED Oniks/duel contract)."""
        if self.fuel <= 0.0:
            return 0.0
        w = self.weapon
        if self._commanded_speed is None:
            target_mach = (w.cruise_mach_hi
                           if self.hi and self.phase in (PH_CLIMB, PH_CRUISE)
                           else w.cruise_mach_lo)
        else:
            target_mach = self._commanded_speed / speed_of_sound_scalar(alt)
        thrust = KP_THRUST * (target_mach - m_now) * THRUST_SCALE + drag_ff
        thrust = min(max(thrust, 0.0), w.max_thrust)
        self.fuel = max(0.0, self.fuel - thrust / (w.isp * GRAVITY) * dt)
        return thrust

    def _acquire_lock(self, world, speed):
        """Pick the nearest alive ship inside seeker range and gimbal cone."""
        w = self.weapon
        cos_half = math.cos(math.radians(w.seeker_half_angle_deg))
        best, best_d = None, w.seeker_range
        px, py, pz = self.pos.tolist()
        vx, vy, vz = self.vel.tolist()
        for ship in world.ships:
            if not getattr(ship, "alive", True):
                continue
            sp = ship.pos
            rx = float(sp[0]) - px
            ry = float(sp[1]) - py
            rz = float(sp[2]) - pz
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
        px, pz = float(self.pos[0]), float(self.pos[2])
        s0 = _surface_at(world, px, pz)
        vx, vz = float(self.vel[0]), float(self.vel[2])
        hspeed = math.hypot(vx, vz)
        if hspeed < 1e-9:
            return alt - s0, vs
        scale = SKIM_LOOKAHEAD / hspeed
        s1 = _surface_at(world, px + vx * scale, pz + vz * scale)
        return alt - s0, vs - (s1 - s0) / SKIM_LOOKAHEAD * hspeed

    def _guidance(self, alt, vs, speed, vx, vz, dt, world):
        """Commanded guidance accel components (gx, gy, gz) as plain floats,
        gravity-compensation 'lift' included.

        Steering/altitude-hold runs entirely on scalars (Task GATE perf:
        this runs per missile per 120 Hz substep — the old per-step
        steer/PN array allocations are gone); the rarely-hot PN branches
        still call the shared ``pn_accel``."""
        w = self.weapon
        if self.phase == PH_CLIMB:
            gx, gz = _steer_heading_scalar(vx, vz, self._route_heading())
            gy = altitude_hold_accel(alt, vs, self.cruise_alt,
                                     ALT_KP, ALT_KD, ALT_MAX_A) + GRAVITY
        elif self.phase == PH_CRUISE:
            target_alt = self.cruise_alt if self.hi else w.lo_alt
            gx, gz = _steer_heading_scalar(vx, vz, self._route_heading())
            gy = altitude_hold_accel(alt, vs, target_alt,
                                     ALT_KP, ALT_KD, ALT_MAX_A) + GRAVITY
        elif self.phase == PH_DESCENT:
            self._descent_elapsed += dt
            ramp = (self._descent_alt0
                    - self._descent_ramp_rate * self._descent_elapsed)
            target_alt = max(w.skim_alt, ramp)
            gx, gz = _steer_heading_scalar(vx, vz, self._route_heading())
            gy = altitude_hold_accel(alt, vs, target_alt,
                                     DESCENT_KP, DESCENT_KD,
                                     ALT_MAX_A * self._descent_scale) + GRAVITY
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
                gx, gy, gz = pn_accel(self.pos, self.vel, tpos, tvel).tolist()
                if math.sqrt(dx * dx + dy * dy + dz * dz) < self._final_pn_range:
                    gy += GRAVITY
                else:
                    ralt, rvs = self._skim_ref(alt, vs, world)
                    gy = (altitude_hold_accel(ralt, rvs, w.skim_alt,
                                              ALT_KP, ALT_KD, ALT_MAX_A)
                          + GRAVITY)
            elif self._dist_to_target() < self._final_pn_range:
                gx, gy, gz = pn_accel(self.pos, self.vel, self.target_point,
                                      np.zeros(3)).tolist()
                gy += GRAVITY
            else:
                gx, gz = _steer_heading_scalar(vx, vz, self._route_heading())
                ralt, rvs = self._skim_ref(alt, vs, world)
                gy = altitude_hold_accel(ralt, rvs, w.skim_alt,
                                         ALT_KP, ALT_KD, ALT_MAX_A) + GRAVITY
        # Post-burnout ease-in: scale the COMMAND (not the gravity-comp lift)
        # so the path curvature ramps instead of stepping (GUID_RAMP_T).
        if self._guid_t0 is not None:
            r = (self.t - self._guid_t0) / GUID_RAMP_T
            if r >= 1.0:
                self._guid_t0 = None
            else:
                gx *= r
                gz *= r
                gy = (gy - GRAVITY) * r + GRAVITY
        # No dynamic pressure -> no control authority (fuel-starved missiles
        # sink). The stall speed is per-weapon (see STALL_SPEED / __init__): an
        # Oniks/Zircon uses the locked 200.0 m/s floor byte-for-byte; a healthy
        # subsonic SWARM at its design ~85-150 m/s is NOT treated as stalling.
        stall = self._stall_speed
        if speed < stall:
            k = (speed / stall) ** 2
            gx *= k
            gy *= k
            gz *= k
        # G-limit the total commanded accel.
        gmax = w.max_g * GRAVITY
        n2 = gx * gx + gy * gy + gz * gz
        if n2 > gmax * gmax:
            k = gmax / math.sqrt(n2)
            gx *= k
            gy *= k
            gz *= k
        return gx, gy, gz

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
            self._guid_t0 = self.t      # fins ease in over GUID_RAMP_T
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
        # Per-weapon-profile rounds hand over by RANGE as well: a fast diver
        # can reach the target while the ramp-following PD is still kilometres
        # high (the lag is ~ramp_rate*kd/kp) — the altitude gate alone then
        # never trips and the round OVERFLIES with the seeker never engaged
        # (measured: Zircon crossed the ship at 151 m, still in DESCENT).
        # Legacy weapons (descent_range_m unset) keep the alt-only gate.
        if (self.phase == PH_DESCENT and w.descent_range_m > 0.0
                and self._dist_to_target() < w.terminal_range):
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
            # Nose-cap pulse jets: the path rotation rate slews under the
            # TURN_ACCEL limit (trapezoid up, brake onto capture) — no
            # rate discontinuity anywhere in the arc. The instant it
            # captures (or the hard cap expires) the cap is shot off and
            # the high-thrust mode lights — phase BOOST this same step.
            tilt_dir = self._climb_dir()
            c = min(max(hx * tilt_dir[0] + hy * tilt_dir[1]
                        + hz * tilt_dir[2], -1.0), 1.0)
            self._turn_rate = _slewed_rate(self._turn_rate, math.acos(c),
                                           PITCH_RATE_MAX, dt)
            hx, hy, hz = _rotate_toward_scalar(
                hx, hy, hz, tilt_dir[0], tilt_dir[1], tilt_dir[2],
                self._turn_rate * dt)
            vx, vy, vz = hx * speed, hy * speed, hz * speed
            self.vel[0] = vx
            self.vel[1] = vy
            self.vel[2] = vz
            # The pulse jets hold the commanded arc against gravity: cancel
            # gravity's path-bending (perpendicular) component so the slewed
            # turn rate IS the path's turn rate; the along-track part still
            # costs climb energy honestly.
            gx = -GRAVITY * hy * hx
            gy = GRAVITY * (1.0 - hy * hy)
            gz = -GRAVITY * hy * hz
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
            # The turn rate carries over from pitch-over and keeps slewing
            # under the same accel limit — the handover leaves no kink.
            tilt_dir = self._climb_dir()
            c = min(max(hx * tilt_dir[0] + hy * tilt_dir[1]
                        + hz * tilt_dir[2], -1.0), 1.0)
            self._turn_rate = _slewed_rate(self._turn_rate, math.acos(c),
                                           BOOST_TILT_RATE, dt)
            hx, hy, hz = _rotate_toward_scalar(
                hx, hy, hz, tilt_dir[0], tilt_dir[1], tilt_dir[2],
                self._turn_rate * dt)
            vx, vy, vz = hx * speed, hy * speed, hz * speed
            self.vel[0] = vx
            self.vel[1] = vy
            self.vel[2] = vz
            # TVC holds the climb-out against gravity (see PITCHOVER note).
            gx = -GRAVITY * hy * hx
            gy = GRAVITY * (1.0 - hy * hy)
            gz = -GRAVITY * hy * hz
            thrust = w.booster_thrust
            drag = drag_force_scalar(
                speed, alt, cd_from_mach_scalar(mach_scalar(speed, alt)),
                w.ref_area)
        elif self.phase in (PH_CLIMB, PH_CRUISE, PH_DESCENT, PH_TERMINAL):
            # One atmosphere evaluation feeds both the Mach-hold thrust
            # (drag feedforward) and the drag force (Task GATE perf: the
            # old code computed the identical mach/cd/drag twice per step).
            m_now = mach_scalar(speed, alt)
            drag = drag_force_scalar(speed, alt, cd_from_mach_scalar(m_now),
                                     w.ref_area)
            thrust = self._sustainer_thrust(m_now, drag, dt, alt)
            gx, gy, gz = self._guidance(alt, vy, speed, vx, vz, dt, world)

        # --- semi-implicit Euler + phase shaping clamps (scalar: Task 22) ---
        coef = (thrust - drag) / self.mass
        vx += (hx * coef + gx) * dt
        vy += (hy * coef + gy - GRAVITY) * dt
        vz += (hz * coef + gz) * dt
        if self.phase == PH_CLIMB:
            max_vy = math.hypot(vx, vz) * CLIMB_MAX_TAN
            if vy > max_vy:
                vy = max_vy
        elif self.phase == PH_DESCENT:
            max_sink = self._descent_max_sink
            if vy < -max_sink:
                vy = -max_sink
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
            surface = _surface_at(world, px, pz)
            if py <= surface:
                self.pos[1] = surface
                self.impact_pos = self.pos.copy()
                self.phase = PH_DEAD
                self.alive = False
                return

        # --- terminal weave overlay (Task RTG) ---
        if self.phase == PH_TERMINAL:
            self._apply_weave(dt, vx, vz)

        self._update_body(dt)

    def _update_body(self, dt):
        """Rotate the body attitude toward its commanded direction: the
        airframe leads the path during the launch tip-over (the fins/jets
        turn the BODY first, thrust then drags the velocity around — the
        nose visibly rotates before the trail bends), tracks the velocity
        vector in guided flight, and never shows more than AOA_MAX off the
        actual flight path. Plain-scalar per-substep math (Task 22 style)."""
        vx, vy, vz = self.vel.tolist()
        speed = math.sqrt(vx * vx + vy * vy + vz * vz)
        if speed < 1e-9:
            return
        inv = 1.0 / speed
        hx, hy, hz = vx * inv, vy * inv, vz * inv
        if self.phase in (PH_PITCHOVER, PH_BOOST):
            tgt = self._climb_dir()
            tx, ty, tz = float(tgt[0]), float(tgt[1]), float(tgt[2])
        else:
            tx, ty, tz = hx, hy, hz
        bx, by, bz = self.body_dir.tolist()
        rate = max(self._turn_rate * BODY_RATE_LEAD, BODY_RATE_MIN)
        bx, by, bz = _rotate_toward_scalar(bx, by, bz, tx, ty, tz, rate * dt)
        if bx * hx + by * hy + bz * hz < AOA_COS:
            # AoA clamp: the body sits exactly AOA_MAX off the path, on the
            # great-circle arc toward where it wanted to point.
            bx, by, bz = _rotate_toward_scalar(hx, hy, hz, bx, by, bz, AOA_MAX)
        self.body_dir[0] = bx
        self.body_dir[1] = by
        self.body_dir[2] = bz

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
