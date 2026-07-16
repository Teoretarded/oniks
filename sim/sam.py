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

from sim.aero import (ALPHA_TAX, AP_TAU_SAM, CL_MAX_SAM, QS_FLOOR,
                      autopilot_step_scalar, project_perpendicular_scalar,
                      q_scalar)
from sim.flight_computer import (AirframeEnvelope, FlightState,
                                 MissionSnapshot, OnlineFlightComputer)
from sim.physics import DENSITY_SCALE_HEIGHT, RHO0
from sim.guidance import pn_accel
from sim.missile import _surface_at, _swept_surface_hit
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
# Lead cap 40 s (energy re-tune 2026-07-06; was 90): against an ORBITING
# target a long lead swings the predicted point tens of km every turn and
# the round S-curves after ghost leads — free before induced drag,
# measured -9 m/s^2 (3.6x trim) on a 240 km AWACS coast. 40 s still tames
# the early-boost tiny-closing-speed blowup the cap exists for.
TGO_MAX = 40.0                 # s

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

# Midcourse steering: lateral accel = MID_GAIN * angle_error * speed,
# G-limited together with the gravity compensation.
MID_GAIN = 2.2                 # 1/s of angle error

# Midcourse correction budget (energy model 2026-07-05): the hot MID_GAIN
# saturated every small correction at 10-20 g — free when lift cost
# nothing, ruinous under induced drag (measured: the ASBM glide bled from
# Mach 3 to Mach 0.6 paying saturated corrections). Real midcourse
# autopilots hold a gentle 2-5 g and save the airframe limit for terminal
# PN; the terminal phase is untouched by this cap.
MID_MAX_A_G = 4.0              # g of midcourse lateral correction

# Energy cruise (2026-07-06): a coasting round's drag is minimized where
# parasite == induced, i.e. at qS* = sqrt(k_ind/CD0) * L — and since the
# optimum q is CONSTANT, the optimal ALTITUDE descends as the round slows
# (induced trim drag grows as 1/v^2: a fixed 33 km coast melts itself in a
# death spiral — measured: a 240 km 40N6 shot died 68 km short at a clean
# 1-g trim). The loft bias is capped at the current drag-optimal altitude
# plus a per-round allowance derived from the loft identity (the 40N6
# deliberately rides above optimum — its tall arc IS its discriminator;
# the cost is accepted and its motor re-based for it).
COAST_CD0 = 0.30               # the supersonic-plateau CD0 the optimum uses
COAST_OVER_OPT_FRAC = 0.25     # allowance = frac * (loft_bias_max - 14 km)

# Terminal PN navigation constant 5 (energy re-tune 2026-07-06; module
# default is 4): a DECELERATING interceptor carries a standing PN bias
# miss proportional to its decel (Zarchan) — free-energy rounds never
# decelerated in terminal, honest ones do (measured: clean control
# closest 18.6 m, a hair inside the 20 m fuse; stealth-noise runs
# clustered 22-31 m, just outside). N=5 is the classic counter real
# interceptors fly for exactly this bias.
# 4.5, not 5: N=5 halves the decel-bias miss but AMPLIFIES tracking-noise
# chase (Zarchan's trade) — at N=5 a lone noisy sea-skimmer started
# leaking through the SM-2 again (measured: 1/15 leak; N=4 left the clean
# control at 18.6 m against a 20 m fuse). 4.5 holds both ends (measured:
# clean ~16 m, lone skimmer serviced).
TERMINAL_PN_GAIN = 4.5

# Terminal autopilot bandwidth (gain scheduling, mirrors sim/missile.py
# TERMINAL_AP_TAU): the endgame runs the tightest loop the airframe allows
# (research §3.3 "agile terminal SAM ~0.15-0.3 s") — the midcourse tau in
# the terminal PN lowpassed the seeker hard enough that a LONE slow
# skimmer leaked through the SM-2 (measured 2026-07-05).
TERMINAL_AP_TAU = 0.15         # s

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
                 contact_estimate_fn=None, rng=None, illuminator_pos_fn=None,
                 illuminator_ok_fn=None):
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
        # R-P1 SARH sector gate: optional () -> bool, re-checked on the LOS
        # cadence — False means the illuminating FCR is alive but slewed
        # OFF this round's target (one engagement radar cannot paint two
        # wedges at once); the lock freezes exactly like a terrain mask.
        # None (every legacy construction) = no sector dependency.
        self.illuminator_ok_fn = illuminator_ok_fn
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
        # Energy model (sim/aero.py, plan 2026-07-05): the coast/terminal
        # guidance accel is q-limited, autopilot-lagged, and charged as
        # induced drag — a hard post-burnout turn SHEDS speed (research doc
        # worked example B: a 20 g snap costs ~160 m/s per second).
        self._cl_max = sam_def.cl_max if sam_def.cl_max > 0.0 else CL_MAX_SAM
        self._k_ind = (sam_def.k_induced if sam_def.k_induced > 0.0
                       else ALPHA_TAX / self._cl_max)
        self._ap_tau = (sam_def.autopilot_tau if sam_def.autopilot_tau > 0.0
                        else AP_TAU_SAM)
        self._ap_x = self._ap_y = self._ap_z = 0.0  # achieved-accel lag state
        # Energy-cruise state (see COAST_CD0): sqrt(k/CD0) and the per-round
        # above-optimum allowance, precomputed once.
        self._qs_opt_per_lift = math.sqrt(self._k_ind / COAST_CD0)
        self._coast_over_opt = max(
            0.0, (sam_def.loft_bias_max - 14_000.0) * COAST_OVER_OPT_FRAC)
        # Receding-horizon vertical planner.  SamDef intentionally is not a
        # WeaponDef, so construct the small numeric envelope explicitly.  The
        # planner predicts the solid boost from the remaining propellant and
        # the unpowered coast once it is gone; it never receives ``target`` or
        # any other world/entity reference.
        dry_mass = max(1.0, sam_def.launch_mass - sam_def.propellant_mass)
        ideal_delta_v = (sam_def.isp * GRAVITY
                         * math.log(sam_def.launch_mass / dry_mass))
        preferred_mach = min(max(ideal_delta_v / 300.0, 1.0), 6.0)
        low_mach = min(preferred_mach, max(
            sam_def.self_destruct_speed / 300.0, 0.5))
        is_ballistic = str(sam_def.weapon_id) == "asbm"
        is_high_loft = str(sam_def.weapon_id) == "40n6"
        preferred_alt = (sam_def.loft_bias_max if is_ballistic else
                         sam_def.max_intercept_alt
                         + 0.35 * sam_def.loft_bias_max)
        envelope = AirframeEnvelope(
            ref_area_m2=sam_def.ref_area,
            cl_max=self._cl_max,
            max_g=sam_def.max_g,
            k_induced=self._k_ind,
            dry_mass_kg=dry_mass,
            fuel_capacity_kg=sam_def.propellant_mass,
            max_thrust_n=sam_def.motor_thrust,
            isp_s=sam_def.isp,
            thrust_tau_s=0.0,
            preferred_mach=preferred_mach,
            low_mach=low_mach,
            preferred_alt_m=preferred_alt,
            preferred_alt_is_agl=False,
            deck_agl_m=50.0,
            # A receding-horizon SAM starts its letdown early; a 50-degree
            # instantaneous corridor made a ballistic coast wait too long and
            # then demand an unrecoverable dive.  The MaRV subclass retains
            # its genuinely ballistic envelope.
            max_climb_gamma_rad=math.radians(
                70.0 if is_ballistic else 55.0 if is_high_loft else 35.0),
            max_descent_gamma_rad=math.radians(
                70.0 if is_ballistic else 25.0),
            terminal_speed_min_mps=sam_def.self_destruct_speed,
            fuel_reserve_kg=0.0,
            # Interceptors shape a broad loft over tens of kilometres; the
            # cruise-missile computer's 10 km preview demanded a 35-degree
            # zoom and carried the unpowered 48N6 above 40 km.  Scale preview
            # with the selected energy altitude so the online solution keeps
            # horizontal velocity while still replanning every half-second.
            control_lookahead_m=(
                10_000.0 if is_ballistic else
                9_500.0 if is_high_loft else
                15_000.0 if str(sam_def.weapon_id) == "s300" else
                max(30_000.0, 3.0 * preferred_alt)),
            altitude_preview_m=10_000.0,
            latch_infeasible_midcourse=is_high_loft,
            # Long-range 40N6 energy-corridor search (25 tuning + 25 held-out
            # targets): engage the blend earlier and settle toward a lower,
            # drag-efficient 35% preferred-altitude fraction at extreme range.
            # Defaults remain unchanged for every other weapon family.
            energy_fallback_floor_fraction=(0.35 if is_high_loft else 0.5),
            # Keep the established visibly-high medium-range 40N6 arc; the
            # corridor begins at 120 km at its full preferred-altitude end,
            # so the identity arc is unchanged while 120-140 km shots gain
            # earlier online energy management.  This was the only expanded
            # shortlist change to improve the third fresh 49-case matrix.
            energy_fallback_min_range_m=(
                120_000.0 if is_high_loft else 100_000.0),
            energy_fallback_near_scale=(2.0 if is_high_loft else 2.5),
            energy_fallback_far_scale=(4.0 if is_high_loft else 5.0),
            # Medium shots retain the visibly high 40N6 arc.  Above 120 km,
            # blend continuously toward the searched 12 km control horizon;
            # it becomes fully active at 200 km.  This changes predictor
            # horizon, never prescribes a launch path.
            long_range_control_lookahead_m=(
                12_000.0 if is_high_loft else None),
            long_range_control_start_m=120_000.0,
            long_range_control_full_m=200_000.0,
            # SAM replans run at 2 Hz rather than the cruise families' 4 Hz.
            # One-second broad-mode dwell therefore filters a single noisy
            # candidate flip while still allowing two fresh solutions each
            # second and immediate terminal/feasibility transitions.
            corridor_min_hold_s=1.0,
        )
        self._fc = OnlineFlightComputer(envelope, replan_interval_s=0.5)
        self._fc_command = None
        # The target picture is sampled on the same cadence as the bounded
        # replan.  Holding this immutable numeric aim between replans prevents
        # a moving track from invalidating the flight-computer cache at 120 Hz.
        self._fc_aim = None
        self._fc_preferred_alt = None
        self._fc_next_sample_t = 0.0
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
        ok_fn = self.illuminator_ok_fn
        target_ref = getattr(ok_fn, "_target_ref", None)
        estimate_ref = getattr(ok_fn, "_estimate_ref", None)
        if target_ref is not None:
            target_ref[0] = new_target
        if estimate_ref is not None:
            estimate_ref[0] = contact_estimate_fn
        self._fc_aim = None
        self._fc_preferred_alt = None
        self._fc_command = None
        self._fc_next_sample_t = self.t
        self._fc.invalidate("retarget")
        return True

    # --- guidance helpers -------------------------------------------------------

    def _target_state(self):
        """(tx, ty, tz, tvx, tvy, tvz): the contact estimate before terminal
        (when supplied), the true aircraft state otherwise. The multipath
        error rides on the position either way — the noise lives in the
        tracking/illumination chain, not in any one data source."""
        # Command-guided rounds never grow an onboard truth seeker in the
        # terminal phase: their tighter PN loop still flies the permitted FCR
        # estimate.  SARH/ARH rounds change to their terminal measurement.
        if (self.contact_estimate_fn is not None
                and (self.phase < SPH_TERMINAL
                     or self.weapon.guidance == "command")):
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
        guidance = self.weapon.guidance
        if self.phase >= SPH_TERMINAL and guidance == "arh":
            # An active round measures from its own seeker after handover,
            # regardless of any launcher callback accidentally supplied.
            fc = self.pos
        else:
            ill = (self.illuminator_pos_fn()
                   if self.illuminator_pos_fn is not None else None)
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
        guidance = self.weapon.guidance
        if guidance == "arh":
            # Own seeker: launcher death, sector changes, and a mistakenly
            # wired illuminator cannot break an established active lock.
            src = self.pos
        else:
            # SARH and command guidance remain fire-control dependent.  A
            # missing callback means a legacy fixed launch-site radar, not an
            # onboard seeker; an explicit dead/off-sector callback breaks it.
            if (self.illuminator_ok_fn is not None
                    and not self.illuminator_ok_fn()):
                return True
            if self.illuminator_pos_fn is not None:
                src = self.illuminator_pos_fn()
                if src is None:
                    return True
            else:
                src = self._fc_pos
        return terrain_blocks(src, self.target.pos,
                              height_fn=world.terrain_height_at)

    def _predicted_intercept_point(self, px, py, pz, vx, vy, vz):
        """Led numeric aim built only from the permitted target estimate."""
        tx, ty, tz, tvx, tvy, tvz = self._target_state()
        rx, ry, rz = tx - px, ty - py, tz - pz
        d = math.sqrt(rx * rx + ry * ry + rz * rz)
        if d < 1.0:
            return tx, ty, tz
        closing = -((tvx - vx) * rx + (tvy - vy) * ry
                    + (tvz - vz) * rz) / d
        t_go = min(d / max(closing, TGO_CLOSING_FLOOR), TGO_MAX)
        ax, ay, az = tx + tvx * t_go, ty + tvy * t_go, tz + tvz * t_go
        # One deterministic fixed-point refinement, still entirely on the
        # supplied estimate rather than entity truth.
        d2 = math.sqrt((ax - px) ** 2 + (ay - py) ** 2 + (az - pz) ** 2)
        t_go = min(d2 / max(closing, TGO_CLOSING_FLOOR), TGO_MAX)
        return tx + tvx * t_go, ty + tvy * t_go, tz + tvz * t_go

    def _command_direction(self, px, py, pz, aim, command):
        """3-D unit path direction from planner gamma plus aim azimuth.

        AIR-INTERCEPT FLOOR (2026-07-17, pre-existing regression found by
        the audit): inside the round's loft-fade range the corridor
        planner's terrain-cruise gamma has no room to matter, and against
        a HIGH close target it aimed the whole boost tens of degrees UNDER
        the intercept line — the round entered terminal ~50 deg off the
        LOS, PN could not remove the error in the remaining kilometres and
        it zoomed ballistically past (measured: every <=22 km drone shot
        missed by 4-6 km; the phase-4 kill curve was dead).  The floor
        clamps the commanded path to AT LEAST the direct line to the led
        aim point when close — long lofted shots (rg beyond the fade
        range) and low targets (direct line below the planner's arc) are
        untouched."""
        ax, ay, az = aim
        gx, gz = ax - px, az - pz
        rg = math.hypot(gx, gz)
        direct = math.atan2(ay - py, max(rg, 1.0))
        gamma = (command.target_path_gamma_rad if command is not None else
                 direct)
        # CLIMB geometries only (direct > 0): a round ABOVE its aim keeps
        # the planner's steeper letdown — clamping a descent to the
        # shallower direct line broke the 48N6's dive onto high targets
        # (test_s300_rounds_distinct caught it).
        if (rg < self.weapon.loft_fade_range and direct > 0.0
                and direct > gamma):
            gamma = direct
        if rg < 1e-9:
            return 0.0, (1.0 if gamma >= 0.0 else -1.0), 0.0
        cg = math.cos(gamma)
        return gx / rg * cg, math.sin(gamma), gz / rg * cg

    def _flight_computer_step(self, dt, world, px, py, pz, vx, vy, vz):
        """Update the bounded online plan from numeric state/track data."""
        if (self._fc_aim is None
                or self.t + 1e-12 >= self._fc_next_sample_t):
            self._fc_aim = self._predicted_intercept_point(
                px, py, pz, vx, vy, vz)
            self._fc_next_sample_t = self.t + self._fc.replan_interval_s
            ax, ay, az = self._fc_aim
            # Live energy-altitude basket: retain the per-round loft ceiling,
            # capped at the minimum-drag dynamic-pressure altitude for the
            # current mass/speed.  Sample it on the same cadence as the track
            # so the immutable mission signature remains cached between plans.
            rg = math.hypot(ax - px, az - pz)
            bias = min(
                self.weapon.loft_gain * max(
                    rg - self.weapon.loft_fade_range, 0.0),
                self.weapon.loft_bias_max)
            speed = math.sqrt(vx * vx + vy * vy + vz * vz)
            if bias > 0.0 and speed > 1.0:
                rho_opt = (2.0 * self._qs_opt_per_lift * self.mass * GRAVITY
                           / (self.weapon.ref_area * speed * speed))
                if rho_opt < RHO0:
                    h_opt = (-DENSITY_SCALE_HEIGHT
                             * math.log(rho_opt / RHO0)
                             + self._coast_over_opt)
                    bias = min(bias, max(0.0, h_opt - ay))
            if vy < 0.0:
                bias = min(bias, max(0.0, py - ay))
            self._fc_preferred_alt = ay + bias
        ax, ay, az = self._fc_aim
        # Plan to an energy-preserving handover basket above the estimate;
        # terminal PN owns the remaining vertical closure.  Supplying that
        # basket as the numeric mission endpoint lets every corridor be judged
        # against the same achievable terminal geometry.
        handover_buffer = min(
            10_000.0,
            0.40 * self.weapon.terminal_range,
            (0.35 * self.weapon.loft_bias_max
             + 0.25 * max(self.weapon.loft_bias_max - 14_000.0, 0.0)))
        handover_y = ay + max(500.0, handover_buffer)
        preferred_alt = (ay if self._fc_preferred_alt is None else
                         self._fc_preferred_alt)
        state = FlightState(
            pos=(px, py, pz), vel=(vx, vy, vz),
            mass_kg=float(self.mass), fuel_kg=float(self.propellant),
            thrust_actual_n=(self.weapon.motor_thrust
                             if self.phase == SPH_BOOST else 0.0),
            time_s=float(self.t))
        mission = MissionSnapshot(
            path_xz=((ax, az),),
            target_y_m=handover_y,
            preferred_altitude_m=preferred_alt,
            terminal_handover_alt_m=handover_y,
            allow_high=True,
            # SamMissile retains its seeker range/cone handover.  The flight
            # computer owns the letdown decision, not terminal phase commit.
            terminal_armed=False,
            terminal_latched=False,
            terminal_commit_max_m=float(self.weapon.terminal_range))
        self._fc_command = self._fc.update(
            dt, state, mission,
            lambda x, z: _surface_at(world, x, z))
        return self._fc_command

    def _online_midcourse_guidance(self, speed, vx, vy, vz, command):
        """Inner loop following online vertical energy and horizontal lead."""
        gx = gy = gz = 0.0
        hspeed = math.hypot(vx, vz)
        if self._fc_aim is not None and hspeed > 1e-9:
            rx = self._fc_aim[0] - float(self.pos[0])
            rz = self._fc_aim[2] - float(self.pos[2])
            rr = math.hypot(rx, rz)
            if rr > 1e-9:
                dx, dz = rx / rr, rz / rr
                hx, hz = vx / hspeed, vz / hspeed
                dot = min(max(dx * hx + dz * hz, -1.0), 1.0)
                ex, ez = dx - dot * hx, dz - dot * hz
                en = math.hypot(ex, ez)
                if en > 1e-9:
                    a = min(MID_GAIN * math.atan2(en, dot) * speed,
                            MID_MAX_A_G * GRAVITY,
                            self.weapon.max_g * GRAVITY)
                    gx += ex / en * a
                    gz += ez / en * a
        if speed > 1e-9 and hspeed > 1e-9:
            gamma = math.atan2(vy, hspeed)
            path_a = command.path_normal_accel_mps2
            # A fuel-empty, prediction-infeasible long shot preserves energy
            # by following its ballistic vertical arc instead of paying
            # induced drag to hold a loft altitude.  Re-enter closed-loop
            # vertical guidance before the per-round loft-fade/terminal zone.
            energy_coast = (
                self.propellant <= 0.0
                and self.t > self.weapon.motor_time
                # The 40N6's high-loft boost intentionally creates vertical
                # energy.  Releasing all normal lift after burnout turns its
                # guided corridor into an 80+ km ballistic lob; keep that
                # round on the online energy path through coast instead.
                and str(self.weapon.weapon_id) != "40n6"
                and not command.prediction.feasible
                and command.prediction.route_range_m > max(
                    2.0 * self.weapon.terminal_range,
                    self.weapon.loft_fade_range))
            lift_n = (0.0 if energy_coast else
                      path_a + GRAVITY * math.cos(gamma))
            nx = -vx * vy / (speed * hspeed)
            ny = hspeed / speed
            nz = -vz * vy / (speed * hspeed)
            gx += nx * lift_n
            gy += ny * lift_n
            gz += nz * lift_n
        else:
            gy = GRAVITY
        return gx, gy, gz

    def _apply_energy_model(self, gx, gy, gz, speed, alt, dt):
        """Shared coast/terminal energy step (sim/aero.py, plan 2026-07-05):
        q-limit the commanded accel, lag it through the autopilot, charge
        the achieved lift as induced drag on top of the zero-lift drag.
        Returns (gx, gy, gz, drag). BOOST is thrust-vectored and EJECT is
        ballistic — neither comes through here (locked launch beats)."""
        w = self.weapon
        vx, vy, vz = self.vel.tolist()
        gx, gy, gz = project_perpendicular_scalar(
            gx, gy, gz, vx, vy, vz)
        q = q_scalar(speed, alt)
        qs = q * w.ref_area
        tau = (min(self._ap_tau, TERMINAL_AP_TAU)
               if self.phase == SPH_TERMINAL else self._ap_tau)
        gx, gy, gz = autopilot_step_scalar(
            gx, gy, gz, self._ap_x, self._ap_y, self._ap_z,
            dt=dt, tau=tau, q=q, ref_area=w.ref_area, mass=self.mass,
            cl_max=self._cl_max, structural_limit=w.max_g * GRAVITY)
        self._ap_x, self._ap_y, self._ap_z = gx, gy, gz
        lift = self.mass * math.sqrt(gx * gx + gy * gy + gz * gz)
        drag = (qs * cd_from_mach_scalar(mach_scalar(speed, alt))
                + self._k_ind * lift * lift / max(qs, QS_FLOOR))
        return gx, gy, gz, drag

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
        if not getattr(self.target, "alive", True):
            # A sister round / the gun already killed it this step: never
            # fuse over a corpse — the old path re-killed the frozen truth
            # pos and OVERWROTE its death_cause/killed_by forensics stamp.
            return False
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
        # Break off when the assigned target is already dead (shoot-shoot
        # doctrine: the FIRST round or the gun got it).  The old behaviour
        # kept PN-homing on the corpse's frozen truth pos and "killed" it a
        # second time — double kill events + corrupted forensics stamps.
        if not getattr(self.target, "alive", True):
            self.self_destructed = True
            self._die(self.pos.copy())
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
            # Range/cone acquisition is judged on the permitted midcourse
            # picture.  Only after commitment may ARH/SARH terminal homing
            # consume their own terminal measurement.
            tx, ty, tz, _, _, _ = self._target_state()
            rx = tx - px0
            ry = ty - alt
            rz = tz - pz0
            d2 = rx * rx + ry * ry + rz * rz
            in_range = d2 < w.terminal_range * w.terminal_range
            # R-P1 seeker cone (scanned model, homing rounds only): the
            # terminal seeker acquires about the VELOCITY vector — a target
            # inside the range gate but outside the gimbal cone is not
            # acquired; midcourse keeps flying and PN geometry brings the
            # nose around (command-guided rounds have no onboard seeker and
            # keep the pure range gate; the legacy functional suite keeps
            # it for every round, byte-identically).
            if (in_range and speed > 1e-9
                    and w.guidance in ("arh", "sarh")
                    and getattr(world, "radar_model",
                                "functional") == "scanned"):
                cos_off = (rx * hx + ry * hy + rz * hz) / max(
                    math.sqrt(d2), 1e-9)
                if cos_off < math.cos(
                        math.radians(w.seeker_half_angle_deg)):
                    in_range = False
            if in_range:
                # Seed the frozen guide point from the midcourse estimate
                # BEFORE the phase flips (an immediately masked lock coasts
                # on the honest handover picture), then force an LOS check
                # on the first terminal step.
                self._lock_pos = np.array([tx, ty, tz])
                self._los_next_t = self.t
                self.phase = SPH_TERMINAL
                self._fc.force_terminal()

        # --- forces ---
        gx = gy = gz = 0.0                     # guidance accel components
        thrust = 0.0
        drag = 0.0
        if self.phase == SPH_BOOST:
            if self.t >= w.eject_time + BOOST_VERTICAL_TIME and speed > 1e-9:
                command = self._flight_computer_step(
                    dt, world, px0, alt, pz0, vx, vy, vz)
                dx, dy, dz = self._command_direction(
                    px0, alt, pz0, self._fc_aim, command)
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
            command = self._flight_computer_step(
                dt, world, px0, alt, pz0, vx, vy, vz)
            gx, gy, gz = self._online_midcourse_guidance(
                speed, vx, vy, vz, command)
            gx, gy, gz, drag = self._apply_energy_model(
                gx, gy, gz, speed, alt, dt)
        elif self.phase == SPH_TERMINAL:
            # Terminal lock maintenance: LOS re-check on the cadence; a
            # blocked check freezes the last estimate (no reacquire until a
            # later check clears).
            if self.t >= self._los_next_t:
                self._los_next_t = self.t + LOS_CHECK_PERIOD_S
                self._lock_ok = not self._los_masked(world)
            if self._lock_ok:
                tx, ty, tz, tvx, tvy, tvz = self._target_state()
                tpos = np.array([tx, ty, tz])
                tvel = np.array([tvx, tvy, tvz])
                self._lock_pos = tpos          # last estimate: frozen on snap
            else:
                tpos = self._lock_pos          # coast on the frozen estimate
                tvel = np.zeros(3)
            g = pn_accel(self.pos, self.vel, tpos, tvel,
                         n_gain=TERMINAL_PN_GAIN)
            gx, gy, gz = g.tolist()
            gy += GRAVITY                      # gravity compensation
            gmax = w.max_g * GRAVITY
            n2 = gx * gx + gy * gy + gz * gz
            if n2 > gmax * gmax:
                s = gmax / math.sqrt(n2)
                gx *= s
                gy *= s
                gz *= s
            gx, gy, gz, drag = self._apply_energy_model(
                gx, gy, gz, speed, alt, dt)
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

        # A spent, unreachable round descending toward the surface late in
        # its time budget bursts safely in the air.  This is the flight
        # computer's terminal-energy fail-safe, and avoids carrying a live
        # area-defense warhead into the terrain after a rejected long shot.
        if (self.phase == SPH_MIDCOURSE
                and self.propellant <= 0.0
                and self.t > 0.75 * w.self_destruct_t
                and py <= 1_500.0 and vy < 0.0
                and self._fc_command is not None
                and not self._fc_command.prediction.feasible):
            self.self_destructed = True
            self._die(self.pos.copy())
            return

        # --- surface impact (terrain query skipped above the world ceiling;
        # SWEPT segment test so a Mach-3+ round cannot tunnel one substep
        # past a cliff face — mirrors sim/missile.py) ---
        if min(alt, py) <= TERRAIN_MAX_HEIGHT:
            hit = _swept_surface_hit(world, px0, alt, pz0, px, py, pz)
            if hit is not None:
                self.pos[0] = hit[0]
                self.pos[1] = hit[1]
                self.pos[2] = hit[2]
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
