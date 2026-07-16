"""Close-in weapon system (CIWS) — last-ditch gun with PHYSICS, not dice.

Models a Phalanx/Kashtan-class radar-guided autocannon that engages incoming
missiles at close range.  Designed as the final layer inside the S-300 /
SM-2 envelope; it is not a point-defense missile system.

Engagement model (2026-07-17 rework — the old flat Pk roll was the last
probability-roll kill in the game, replaced under the physics-not-dice law):

The gun fires in 1 s bursts separated by 0.5 s pauses (muzzle-cooling /
tracking-settle cadence) whenever a hostile missile is inside the engagement
range with positive closing rate.  A burst KILLS when the fire-control
solution actually covers the target — a geometric gate, never a roll:

  * The fire-control TRACKING ERROR is a time-correlated Ornstein-Uhlenbeck
    process (the sim/sam.py multipath pattern): an ANGLE error at the mount,
    so its magnitude in meters scales with slant range —
        sigma_m = TRACK_SIGMA_MRAD/1000 * slant.
    It is advanced with the EXACT OU discretization once per burst
    (e' = e*exp(-dt/tau) + sigma*sqrt(1-exp(-2dt/tau))*randn), so consecutive
    bursts are correlated on TRACK_TAU_S — a gun whose solution is "on"
    stays on for a beat, a bad solution takes time to walk back in.
  * The burst's round stream covers a lethal disc around the aim point:
        lethal_m = target_radius + LETHAL_DISP_MRAD/1000 * slant
    (ballistic dispersion opens the stream linearly with range).  A partial
    burst (ammo running dry) thins the stream — round density scales the
    covered radius by sqrt(rounds_actual / rounds_full).
  * KILL  <=>  |tracking error| <= lethal_m.

Consequences, all emergent: point-blank shots are near-certain (the angle
error collapses faster than the target disc), long shots mostly miss, a
leaker that survives one burst often survives the next (correlated error),
and a bigger target (``target.radius`` when exposed) is genuinely easier
to hit.  The per-range kill frequencies are CALIBRATED to the previous
tuned Pk ramps (P~0.5 at 800 m / ~0.15 at 2 km for the 20 mm; ~0.55 at
1 km / ~0.15 at 4 km for the Pantsir 30 mm) so the balance bands hold —
see tools/probe_gun_physics.py, run it before touching the constants.

Events
------
``engage()`` returns event tuples the caller consumes:

    (EVENT_BURST, position_3f64)   – burst fired, rounds in the air
    (EVENT_KILL,  position_3f64)   – burst geometrically covered the target

A kill event is always accompanied by a preceding burst event in the same
call.  The killed missile's ``alive`` flag is set False by the CIWS before
the event is appended; the world integrator must not step it again that
tick.

Determinism
-----------
All randomness routes through the injected ``numpy.random.Generator``
(three standard-normal draws per completed burst — the OU step).  Same
seed, same call sequence -> identical outcomes.

Usage
-----
    rng  = np.random.default_rng(seed=42)
    ciws = Ciws(ammo=1000, rng=rng)

    # per-physics substep (120 Hz):
    events = ciws.engage(target_missile, dt)
    for kind, pos in events:
        if kind == "ciws_kill":
            apply_kill_effects(pos)
"""

import math

import numpy as np

# --- Engagement parameters (spec §5.2 / §7 / §9) ----------------------------

ENGAGE_RANGE = 2_000.0      # m, acquisition and max-fire range

BURST_FIRE_TIME = 1.0       # s, duration of one firing burst
BURST_PAUSE_TIME = 0.5      # s, cooling/settle pause between bursts
ROUNDS_PER_SECOND = 75.0    # rd/s muzzle rate during a burst

# Fire-control tracking error (OU angle process — see module docstring).
# CALIBRATED (tools/probe_gun_physics.py) against the previous Pk ramp:
# ~0.50 kill-per-burst at 800 m, ~0.15 at the 2 km edge, vs a missile-sized
# (2.6 m effective radius) target.
TRACK_SIGMA_MRAD = 3.06     # mrad RMS per-axis tracking error
TRACK_TAU_S = 1.0           # s OU correlation (FCS solution persistence).
#   1.0 s vs the 1.5 s burst cadence -> consecutive bursts are nearly
#   independent (corr ~0.22): a closing engagement gets honest repeated
#   tries, matching the old per-burst ramp CUMULATIVELY too (the M4-B
#   "a lone swarm round never leaks given ammo" contract broke at tau 2).
LETHAL_DISP_MRAD = 1.45     # mrad: dispersion-stream lethal radius growth

# Crossing-rate servo lag: the mount's traverse/settle trails a CROSSING
# target by SERVO_LAG_S seconds of its cross-range speed, shrinking the
# covered radius by lag_m = SERVO_LAG_S * v_perp (and closing the shot
# entirely when the lag exceeds the whole lethal radius — the physical
# dead zone every real CIWS has against fast crossers).  A radial closer
# (v_perp ~ 0) pays nothing, so the head-on calibration above is
# untouched; leakers CROSSING the mount's position survive close passes —
# the reason ships pair the gun with missiles, and the seam the phase-6
# saturation raid leaks through (its defeat-path contract broke when the
# reworked gun was point-blank-certain against crossers too).
SERVO_LAG_S = 0.02          # s effective traverse/settle lag

# Effective target radius when the target does not expose ``.radius``:
# an Oniks-class 8.9 m airframe sphere-izes to ~2.6 m (the manpads
# _target_radius convention, length * 0.3).
DEFAULT_TARGET_RADIUS_M = 2.6


class Ciws:
    """Phalanx/Kashtan-class close-in weapon system.

    Parameters
    ----------
    ammo:
        Integer round count at construction (drawn in full bursts of
        ``ROUNDS_PER_SECOND * BURST_FIRE_TIME`` rounds per burst).
    rng:
        ``numpy.random.Generator`` — injected for determinism.  Use
        ``numpy.random.default_rng(seed)`` at the call site.

    Subclasses (the Pantsir 30 mm) override only the class-level
    constants below — the engage loop itself is shared.
    """

    # Class-level engagement constants (subclass override points).
    _ENGAGE_RANGE = ENGAGE_RANGE
    _ROUNDS_PER_SECOND = ROUNDS_PER_SECOND
    _TRACK_SIGMA_MRAD = TRACK_SIGMA_MRAD
    _TRACK_TAU_S = TRACK_TAU_S
    _LETHAL_DISP_MRAD = LETHAL_DISP_MRAD
    _SERVO_LAG_S = SERVO_LAG_S
    EVENT_BURST = "ciws_burst"
    EVENT_KILL = "ciws_kill"

    def __init__(self, ammo: int, rng: np.random.Generator):
        self.ammo = int(ammo)
        self._rng = rng
        # Burst state machine: True = currently firing, False = in pause.
        self._firing = False
        self._phase_t = 0.0     # time elapsed in the current firing/pause phase
        # OU tracking-error state (mrad, per-axis — an ANGLE process, so the
        # meter error at the target scales with slant range automatically)
        # + time since its last advance (the exact discretization handles
        # any gap).  Initialized lazily at the STATIONARY distribution on
        # the first burst: a fresh fire-control solution is a typical one,
        # not a perfect one.
        self._err_mrad = np.zeros(3, dtype=np.float64)
        self._err_init = False
        self._err_age_s = 0.0

    @property
    def ready(self) -> bool:
        """True when there is ammo and the gun is not destroyed/disabled."""
        return self.ammo > 0

    # --- physics internals ----------------------------------------------------

    def _advance_track_error(self, dt: float) -> None:
        """One EXACT OU step of the fire-control ANGLE error.

        Exact discretization (unconditionally correct for any dt):
            e' = e * exp(-dt/tau) + sigma * sqrt(1 - exp(-2dt/tau)) * N(0,1)
        Three standard-normal draws per call — called once per completed
        burst, so the rng cadence stays burst-scale (determinism contract).
        The FIRST call draws straight from the stationary distribution
        (a fresh solution is a TYPICAL one, never a perfect zero-error one).
        """
        sigma = self._TRACK_SIGMA_MRAD
        z = self._rng.standard_normal(3)
        if not self._err_init:
            self._err_init = True
            self._err_mrad[:] = sigma * z
            return
        decay = math.exp(-dt / self._TRACK_TAU_S)
        kick = sigma * math.sqrt(max(1.0 - decay * decay, 0.0))
        self._err_mrad *= decay
        self._err_mrad += kick * z

    def _lethal_radius_m(self, slant_range: float, target,
                         density_frac: float) -> float:
        """Radius around the aim point the burst's stream covers lethally:
        target extent + linear dispersion growth, thinned by sqrt(round
        density) when the magazine could not feed a full burst."""
        radius = float(getattr(target, "radius", DEFAULT_TARGET_RADIUS_M))
        lethal = radius + self._LETHAL_DISP_MRAD * 1e-3 * slant_range
        return lethal * math.sqrt(max(min(density_frac, 1.0), 0.0))

    # --- main loop --------------------------------------------------------------

    def engage(self, target, dt: float) -> list:
        """Step the CIWS for one physics substep.

        Parameters
        ----------
        target:
            Any object with ``.pos`` (3,) float64, ``.velocity()`` → (3,)
            float64, and ``.alive`` bool.  If not alive the call is a no-op.
            An optional ``.radius`` (m) is honored as the target extent.
        dt:
            Substep duration in seconds (typically 1/120).

        Returns
        -------
        List of ``(kind, pos)`` event tuples where ``kind`` is
        ``EVENT_BURST`` or ``EVENT_KILL`` and ``pos`` is a (3,) float64
        (target position at the moment of the event, mount-relative when
        the caller adapts it so).
        """
        if not self.ready or not target.alive:
            return []

        tpos = target.pos
        tvel = target.velocity()

        # Slant range and closing rate (positive = approaching).
        dx = float(tpos[0])
        dy = float(tpos[1])
        dz = float(tpos[2])
        slant = math.sqrt(dx * dx + dy * dy + dz * dz)

        if slant > self._ENGAGE_RANGE:
            # Outside acquisition — reset burst cadence so we start fresh
            # if the target later enters the envelope.
            self._firing = False
            self._phase_t = 0.0
            self._err_age_s += dt      # the solution still ages while idle
            return []

        # Closing rate: -dot(r_hat, v_target).  Positive means the gap shrinks.
        # We need at least a nominal approach; a receding target or one moving
        # purely laterally is not engaged (gun cannot lead far enough at close
        # range to reliably hit a pure cross-course target — and a receding
        # target is no longer a threat).
        if slant > 1e-6:
            closing = -(dx * float(tvel[0]) + dy * float(tvel[1])
                        + dz * float(tvel[2])) / slant
        else:
            closing = 1.0   # point-blank: always engage

        if closing <= 0.0:
            # Target is moving away — pause the gun but keep the cadence state
            # so it resumes seamlessly if the target turns back.
            self._err_age_s += dt
            return []

        events = []
        self._phase_t += dt
        self._err_age_s += dt

        if not self._firing:
            # Pause phase.
            if self._phase_t >= BURST_PAUSE_TIME:
                self._phase_t -= BURST_PAUSE_TIME
                self._firing = True
        # Note: deliberate fall-through — if a pause just completed, we
        # start firing in the same substep (avoids a one-tick blank gap).
        if self._firing:
            if self._phase_t >= BURST_FIRE_TIME:
                # Burst completed — resolve it geometrically.
                self._phase_t -= BURST_FIRE_TIME
                self._firing = False

                rounds_fired = int(self._ROUNDS_PER_SECOND * BURST_FIRE_TIME)
                actual = min(rounds_fired, self.ammo)
                self.ammo -= actual

                snap_pos = np.array([dx, dy, dz], dtype=np.float64)
                events.append((self.EVENT_BURST, snap_pos))

                if actual > 0:
                    # Advance the fire-control angle error over the time
                    # since it was last sampled, then gate at the CURRENT
                    # geometry: the stream either covers the target or not.
                    self._advance_track_error(max(self._err_age_s, 1e-6))
                    self._err_age_s = 0.0
                    miss_m = (float(np.linalg.norm(self._err_mrad))
                              * 1e-3 * slant)
                    lethal = self._lethal_radius_m(
                        slant, target, actual / max(rounds_fired, 1))
                    # Crossing-rate servo lag (SERVO_LAG_S): the covered
                    # radius shrinks by the mount's traverse trail behind
                    # the target's cross-range speed.  v_perp is the
                    # component of target velocity perpendicular to the
                    # line of sight; a radial closer pays nothing.
                    vx, vy, vz = (float(tvel[0]), float(tvel[1]),
                                  float(tvel[2]))
                    if slant > 1e-6:
                        radial = (dx * vx + dy * vy + dz * vz) / slant
                        v2 = vx * vx + vy * vy + vz * vz
                        v_perp = math.sqrt(max(v2 - radial * radial, 0.0))
                        lethal -= self._SERVO_LAG_S * v_perp
                    if lethal > 0.0 and miss_m <= lethal:
                        target.alive = False
                        events.append((self.EVENT_KILL, snap_pos))

        return events
