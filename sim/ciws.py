"""Close-in weapon system (CIWS) — probabilistic last-ditch gun.

Models a Phalanx/Kashtan-class radar-guided autocannon that engages incoming
missiles at close range.  Designed as the final layer inside the S-300 /
SM-2 envelope; it is not a point-defense missile system.

Engagement model
----------------
The gun is active every substep via ``engage()``.  When a hostile missile is
inside the engagement range and the closing rate is positive the gun fires in
1 s bursts separated by 0.5 s pauses (muzzle-cooling / tracking-settle
cadence).  Each completed burst draws rounds from the ammo pool and rolls a
single kill probability that is a linear ramp of slant range:

    Pk = lerp(P_NEAR, P_FAR, (range - R_NEAR) / (R_FAR - R_NEAR))

    P_FAR  = 0.15 at R_FAR  = 2 000 m  (just inside acquisition)
    P_NEAR = 0.50 at R_NEAR =   800 m  (last-ditch up close)

The ramp is clamped so Pk = P_NEAR for any range ≤ R_NEAR and
Pk = P_FAR for any range ≥ R_FAR.  These values are intentionally
conservative: the CIWS stops leakers, it does not replace the SAM layer.

The gun goes silent when ammo reaches 0 even mid-burst.

Events
------
``engage()`` returns a list of event tuples that the caller (effects layer /
combat world) consumes:

    ("ciws_burst", position_3f64)   – burst fired, rounds in the air
    ("ciws_kill",  position_3f64)   – burst resulted in a kill

A "ciws_kill" event is always accompanied by a preceding "ciws_burst" in the
same call.  The killed missile's ``alive`` flag is set to ``False`` by the
CIWS before the event is appended; the world integrator must not step it again
that tick.

Determinism
-----------
All randomness is routed through the ``numpy.random.Generator`` injected at
construction.  Seeding that generator reproducibly makes the CIWS fully
deterministic (required by the sim determinism contract).

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
R_FAR  = 2_000.0            # m, far boundary for Pk ramp (= ENGAGE_RANGE)
R_NEAR =   800.0            # m, near boundary; Pk saturates here
P_FAR  = 0.15               # kill probability per burst at R_FAR
P_NEAR = 0.50               # kill probability per burst at R_NEAR

BURST_FIRE_TIME = 1.0       # s, duration of one firing burst
BURST_PAUSE_TIME = 0.5      # s, cooling/settle pause between bursts
ROUNDS_PER_SECOND = 75.0    # rd/s muzzle rate during a burst


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
    """

    def __init__(self, ammo: int, rng: np.random.Generator):
        self.ammo = int(ammo)
        self._rng = rng
        # Burst state machine: True = currently firing, False = in pause.
        self._firing = False
        self._phase_t = 0.0     # time elapsed in the current firing/pause phase

    @property
    def ready(self) -> bool:
        """True when there is ammo and the gun is not destroyed/disabled."""
        return self.ammo > 0

    def _kill_prob(self, slant_range: float) -> float:
        """Linear Pk ramp clamped to [P_FAR, P_NEAR]."""
        if slant_range <= R_NEAR:
            return P_NEAR
        if slant_range >= R_FAR:
            return P_FAR
        t = (slant_range - R_NEAR) / (R_FAR - R_NEAR)
        return P_NEAR + t * (P_FAR - P_NEAR)

    def engage(self, target, dt: float) -> list:
        """Step the CIWS for one physics substep.

        Parameters
        ----------
        target:
            Any object with ``.pos`` (3,) float64, ``.velocity()`` → (3,)
            float64, and ``.alive`` bool.  If not alive the call is a no-op.
        dt:
            Substep duration in seconds (typically 1/120).

        Returns
        -------
        List of ``(kind, pos)`` event tuples where ``kind`` is one of
        ``"ciws_burst"`` or ``"ciws_kill"`` and ``pos`` is a (3,) float64
        representing the intercept point (target position at the moment of
        the event).
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

        if slant > ENGAGE_RANGE:
            # Outside acquisition — reset burst cadence so we start fresh
            # if the target later enters the envelope.
            self._firing = False
            self._phase_t = 0.0
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
            return []

        events = []
        self._phase_t += dt

        if not self._firing:
            # Pause phase.
            if self._phase_t >= BURST_PAUSE_TIME:
                self._phase_t -= BURST_PAUSE_TIME
                self._firing = True
        # Note: deliberate fall-through — if a pause just completed, we
        # start firing in the same substep (avoids a one-tick blank gap).
        if self._firing:
            if self._phase_t >= BURST_FIRE_TIME:
                # Burst completed — evaluate the kill roll.
                self._phase_t -= BURST_FIRE_TIME
                self._firing = False

                rounds_fired = int(ROUNDS_PER_SECOND * BURST_FIRE_TIME)
                actual = min(rounds_fired, self.ammo)
                self.ammo -= actual

                snap_pos = np.array([dx, dy, dz], dtype=np.float64)
                events.append(("ciws_burst", snap_pos))

                # Only roll a kill if we fired a full burst; a partial burst
                # (ammo ran out mid-fire) gets a proportionally scaled Pk.
                if actual > 0:
                    pk = self._kill_prob(slant)
                    if actual < rounds_fired:
                        pk *= actual / rounds_fired
                    if self._rng.random() < pk:
                        target.alive = False
                        events.append(("ciws_kill", snap_pos))

        return events
