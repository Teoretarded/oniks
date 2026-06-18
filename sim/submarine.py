"""Submarine: the enemy diesel SSK (Kilo/Project-877 analogue) — M5.

The one threat the player's radar/SAR/ELINT suite physically cannot find: it
carries NO radar RCS and NO antenna above water, so it is NEVER added to
``world.combat.CombatWorld.ships`` and NEVER passed to any ``sim.radar.Radar``
detect path (mirrors how ``sim.recon.ReconDrone`` is kept out of self.aircraft).
It is detectable ONLY acoustically: it emits a continuous low broadband
``radiated_noise()`` (a function of its speed state — quiet on APPROACH, loud on
the LAUNCH run and the EVADE sprint) plus a sharp LAUNCH TRANSIENT spike when it
fires.  Those are what the player's sonobuoys (sim/recon.AcousticReceiver) hear.

State machine (the speed/quietness economy — loudest exactly when it shoots):

    DEEP_TRANSIT  deep (~-120 m), quiet, transit toward the launch box
        | reached the box AND threat LOW
        v
    APPROACH      slow, quietest (the stealthy creep into firing position)
        | settled AND threat LOW AND salvo cooldown elapsed AND rounds left
        v
    LAUNCH        brief, SHALLOW (~-15 m), NOISY (flood tubes + gas eject);
        |         fire_salvo() seam returns the aim point ONCE here
        v
    EVADE         sprint deep + away, LOUD, then quiet down
        | evade window elapsed
        v
    DEEP_TRANSIT  (cycle repeats while rounds remain)

The boat is SENSOR-DRIVEN and never reads truth: ``step(dt, threat_level)`` takes
a scalar threat (0 = unprosecuted, 1 = recently datum'd/pinged) fed by the
SubCommander from the sensor-only EnemyPicture.  A HIGH threat keeps it from
committing to the noisy launch run (it stays deep) and LENGTHENS the evade
window — exactly the symmetric ASW fairness loop (handoff 03, features 1/4/5).

Pure numpy, GL-free.  Axes: X east, Y up, Z north.  All SI float64.
Determinism: the ONLY randomness is jitter drawn from the injected child stream
([seed, 13]) at construction — same seed -> identical state/timing sequence.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# State constants
# ---------------------------------------------------------------------------
SUB_DEEP_TRANSIT = 0   # deep, quiet, transit toward the launch box
SUB_APPROACH     = 1   # slow, quietest creep into firing position
SUB_LAUNCH       = 2   # shallow, noisy: floods tubes + fires the salvo
SUB_EVADE        = 3   # sprint deep + away, loud, then quiet down

STATE_LABELS = {
    SUB_DEEP_TRANSIT: "DEEP TRANSIT",
    SUB_APPROACH:     "APPROACH",
    SUB_LAUNCH:       "LAUNCH",
    SUB_EVADE:        "EVADE",
}

# ---------------------------------------------------------------------------
# Tuning constants (research-grounded; the speed/quietness economy)
# ---------------------------------------------------------------------------
SUB_DEPTH_M        = -120.0   # m, loiter / transit depth (deep = "the Black Hole")
SUB_LAUNCH_DEPTH_M = -15.0    # m, periscope/launch depth (breaches to fire)

# Speeds (m/s).  A diesel boat creeps near-silent and sprints loud:
#   ~3 kn approach (1.5 m/s), ~14 kn transit (7 m/s), ~16 kn sprint (8 m/s).
# Transit is brisk (a quiet diesel runs ~12-15 kn submerged on the battery) so
# a boat spawned at the deep edge of the 80-140 km band can close to the launch
# box in a sane window; APPROACH is the slow stealthy creep into firing range.
SUB_APPROACH_SPEED_MPS = 1.5    # the stealthy creep (quietest)
SUB_TRANSIT_SPEED_MPS  = 7.0    # deep transit toward the box
SUB_SPRINT_SPEED_MPS   = 8.0    # the EVADE dash (loud)

# Radiated broadband noise scalars (arbitrary acoustic units; the sonobuoy
# detection floor in sim/recon is calibrated against these).  The ORDERING is
# the contract: LAUNCH/EVADE strictly louder than APPROACH/DEEP, APPROACH the
# quietest of all (the creep).  These are NOT dB — a simple monotone scale the
# AcousticReceiver's range-scaled floor consumes.
SUB_NOISE_APPROACH = 1.0    # quietest — the stealthy creep
SUB_NOISE_DEEP     = 2.0    # quiet transit
SUB_NOISE_LAUNCH   = 12.0   # LOUD: flooding tubes + gas-generator eject
SUB_NOISE_EVADE    = 8.0    # loud sprint away
# The sharp transient SPIKE emitted at the instant of fire (heard much farther
# than the steady radiated noise — guarantees a fix opportunity every salvo).
SUB_LAUNCH_TRANSIENT = 40.0

# Timing (s).  Tuned so the full find->shoot->run cycle is exercised in minutes.
SUB_APPROACH_SETTLE_S = 40.0     # time spent settling in APPROACH before launch
SUB_LAUNCH_DWELL_S    = 8.0      # brief, noisy time shallow at launch depth
SUB_EVADE_S           = 120.0    # base sprint-away window after a salvo
SUB_EVADE_THREAT_S    = 180.0    # EXTRA evade seconds when prosecuted (threat=1)
SUB_SALVO_PERIOD_S    = 90.0     # cooldown between salvos
# The launch box: how close to the base the boat creeps before it will fire.
# Inside this the Kalibr's scaled 500 km leg comfortably reaches the base.  Set
# at the OUTER edge of the sub spawn band (80-140 km) so a boat anywhere in the
# band only has to transit a modest distance before it can settle + fire.
SUB_LAUNCH_BOX_RANGE_M = 130_000.0

# Threat gate: above this the boat refuses to commit to the noisy launch run.
SUB_THREAT_COMMIT_MAX = 0.5

# Depth slew (m/s): how fast the boat changes depth between states.
SUB_DEPTH_SLEW_MPS = 4.0


class Submarine:
    """Enemy diesel SSK.  Invisible to radar by construction (no .radar mount,
    no radar_size attr); detectable only via ``radiated_noise()`` + the launch
    transient.  ``step(dt, threat_level)`` advances the state machine and, on
    the tick it fires, returns the surveyed base aim point (the fire_salvo seam
    the world consumes to spawn Kalibrs); otherwise returns None."""

    # NO radar_size / radar attrs — these absences ARE the contract (the sub
    # can never be duck-typed into a Radar.detects / RadarNetwork.visible path).

    def __init__(self, anchor_xz: Tuple[float, float],
                 rng: np.random.Generator,
                 kalibr_ammo: int = 4,
                 base_xz: Tuple[float, float] = (0.0, 0.0),
                 sub_id: str = "ssk_00"):
        self.sub_id = sub_id
        ax, az = float(anchor_xz[0]), float(anchor_xz[1])
        self.pos = np.array([ax, SUB_DEPTH_M, az], dtype=np.float64)
        self.prev_pos = self.pos.copy()
        self.vel = np.zeros(3, dtype=np.float64)
        self._base_xz = (float(base_xz[0]), float(base_xz[1]))
        self.kalibr_ammo = int(kalibr_ammo)
        self._rng = rng
        self.alive = True

        self.state = SUB_DEEP_TRANSIT
        self._state_t = 0.0          # time-in-state accumulator
        self._salvo_cd = 0.0         # salvo cooldown
        self._evade_window = SUB_EVADE_S
        self._fired_this_launch = False
        # A one-tick transient flag the world reads to inject the launch datum
        # and the sonobuoy spike; cleared after it is consumed each step.
        self.launch_transient = False

        # Deterministic per-boat jitter (drawn ONCE from the injected stream so
        # the same seed gives the same timings) — staggers multiple boats and
        # keeps the cycle from being robotically uniform.
        self._approach_jitter = float(rng.uniform(-8.0, 8.0))
        self._cd_jitter = float(rng.uniform(-10.0, 10.0))
        # Initial cooldown so a fresh boat doesn't launch on tick 1.
        self._salvo_cd = max(0.0, 20.0 + self._cd_jitter)

    # ------------------------------------------------------------------
    # duck-type helpers
    # ------------------------------------------------------------------

    @property
    def depth(self) -> float:
        """Signed depth (m, negative below the surface) == pos[1]."""
        return float(self.pos[1])

    @property
    def state_label(self) -> str:
        return STATE_LABELS.get(self.state, "---")

    def kill(self) -> None:
        """Mission kill (an ASW round acquired the boat).  No burning/listing —
        a hit on a submerged hull is a kill."""
        self.alive = False

    # ------------------------------------------------------------------
    # noise model
    # ------------------------------------------------------------------

    def radiated_noise(self) -> float:
        """Continuous broadband radiated-noise level by state (the steady
        signature the sonobuoys hear; the sharp launch transient is separate —
        see ``launch_transient``).  Strictly louder in LAUNCH/EVADE than
        APPROACH/DEEP (the speed/quietness tradeoff)."""
        if not self.alive:
            return 0.0
        if self.state == SUB_APPROACH:
            return SUB_NOISE_APPROACH
        if self.state == SUB_LAUNCH:
            return SUB_NOISE_LAUNCH
        if self.state == SUB_EVADE:
            return SUB_NOISE_EVADE
        return SUB_NOISE_DEEP

    # ------------------------------------------------------------------
    # depth
    # ------------------------------------------------------------------

    def _target_depth(self) -> float:
        return SUB_LAUNCH_DEPTH_M if self.state == SUB_LAUNCH else SUB_DEPTH_M

    def _apply_state_depth(self) -> None:
        """Snap to the state's commanded depth (used by tests + on a state
        change for an instantaneous set; the per-step slew is in step())."""
        self.pos[1] = self._target_depth()

    # ------------------------------------------------------------------
    # state machine
    # ------------------------------------------------------------------

    def _range_to_base(self) -> float:
        return math.hypot(self.pos[0] - self._base_xz[0],
                          self.pos[2] - self._base_xz[1])

    def _heading_to_base(self) -> Tuple[float, float]:
        dx = self._base_xz[0] - self.pos[0]
        dz = self._base_xz[1] - self.pos[2]
        d = math.hypot(dx, dz)
        if d < 1e-6:
            return 0.0, 0.0
        return dx / d, dz / d

    def step(self, dt: float, threat_level: float = 0.0) -> Optional[Tuple[float, float, float]]:
        """Advance one tick.  ``threat_level`` (0..1) is the sensor-only
        prosecution belief fed by the SubCommander (NOT a truth read).  Returns
        the surveyed base aim (x, z, y) on the SINGLE tick it fires a salvo,
        else None."""
        self.launch_transient = False
        if not self.alive:
            return None
        self.prev_pos = self.pos.copy()
        self._state_t += dt
        if self._salvo_cd > 0.0:
            self._salvo_cd = max(0.0, self._salvo_cd - dt)

        fire_aim = None

        if self.state == SUB_DEEP_TRANSIT:
            self._creep(dt, SUB_TRANSIT_SPEED_MPS, toward_base=True)
            # Advance to APPROACH once inside the launch box AND threat is low.
            if (self._range_to_base() <= SUB_LAUNCH_BOX_RANGE_M
                    and threat_level <= SUB_THREAT_COMMIT_MAX):
                self._enter(SUB_APPROACH)

        elif self.state == SUB_APPROACH:
            self._creep(dt, SUB_APPROACH_SPEED_MPS, toward_base=True)
            settle = SUB_APPROACH_SETTLE_S + self._approach_jitter
            # If the threat spikes mid-creep, fall back deep (do not surface).
            if threat_level > SUB_THREAT_COMMIT_MAX:
                self._enter(SUB_DEEP_TRANSIT)
            elif (self._state_t >= settle and self._salvo_cd <= 0.0
                  and self.kalibr_ammo > 0):
                self._enter(SUB_LAUNCH)

        elif self.state == SUB_LAUNCH:
            # Rise to launch depth; brief noisy dwell; fire ONCE.
            self._rise_to(dt, SUB_LAUNCH_DEPTH_M)
            if not self._fired_this_launch and self.kalibr_ammo > 0:
                self._fired_this_launch = True
                self.launch_transient = True
                bx, bz = self._base_xz
                fire_aim = (bx, bz, 0.0)
                # Lengthen the evade if prosecuted (symmetric fairness loop).
                self._evade_window = (SUB_EVADE_S
                                      + SUB_EVADE_THREAT_S * float(threat_level))
            if self._state_t >= SUB_LAUNCH_DWELL_S:
                self._salvo_cd = max(0.0, SUB_SALVO_PERIOD_S + self._cd_jitter)
                self._enter(SUB_EVADE)

        elif self.state == SUB_EVADE:
            # Sprint AWAY from the base, diving back deep.
            self._creep(dt, SUB_SPRINT_SPEED_MPS, toward_base=False)
            self._rise_to(dt, SUB_DEPTH_M)
            # A fresh threat while evading extends the window further.
            window = self._evade_window + SUB_EVADE_THREAT_S * (
                float(threat_level) if threat_level > SUB_THREAT_COMMIT_MAX
                else 0.0)
            if self._state_t >= window:
                self._enter(SUB_DEEP_TRANSIT)

        return fire_aim

    def _enter(self, new_state: int) -> None:
        self.state = new_state
        self._state_t = 0.0
        if new_state == SUB_LAUNCH:
            self._fired_this_launch = False

    def _creep(self, dt: float, speed: float, toward_base: bool) -> None:
        """Move horizontally toward (or away from) the base + slew depth toward
        the state's commanded depth."""
        hx, hz = self._heading_to_base()
        sign = 1.0 if toward_base else -1.0
        self.vel = np.array([sign * hx * speed, 0.0, sign * hz * speed],
                            dtype=np.float64)
        self.pos[0] += self.vel[0] * dt
        self.pos[2] += self.vel[2] * dt
        self._slew_depth(dt, self._target_depth())

    def _rise_to(self, dt: float, target_depth: float) -> None:
        self._slew_depth(dt, target_depth)

    def _slew_depth(self, dt: float, target_depth: float) -> None:
        cur = float(self.pos[1])
        step_m = SUB_DEPTH_SLEW_MPS * dt
        if cur < target_depth:
            self.pos[1] = min(target_depth, cur + step_m)
        elif cur > target_depth:
            self.pos[1] = max(target_depth, cur - step_m)
