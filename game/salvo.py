"""SALVO / ripple-fire scheduler (M6) — pure, GL-free, headless-testable.

A salvo is a thin SCHEDULER over the EXISTING per-tube launch path
(``world.launch`` for the Bastion battery, ``world.launch_sam`` for the S-300):
it empties the currently-ready tubes in a controlled ripple instead of one
SPACE per round, so the player can saturate the SM-2 ``<=4 in flight`` cap (the
documented king move).  It is a pure read/schedule layer:

  - PHYSICS NOT DICE: it introduces NO new outcome roll.  Each round flies the
    same launch path with the same per-round physics; the salvo only launches
    MORE of them.  The only stochastic element is the FAN aim spread, and that
    is a SEEDED deterministic child stream (``[seed, FAN_TAG, ordinal]``), so a
    given seed + config + target reproduces the same aim points bit-for-bit.

  - FOG / NO-CHEAT: the ready-tube count reads ONLY the player's OWN tube state
    (``_oniks_tubes`` / ``_s300_tubes`` — friendly own-force logistics, exempt
    from the radar gate exactly like the battery panel).  It NEVER reads enemy
    truth.  The salvo cannot fire at anything the player could not already
    single-fire at: the launch path itself keeps its sensor gating (an Oniks
    salvo needs a surface aim point, an S-300 salvo needs a held air track).

  - DETERMINISM / NO WALL-CLOCK: the schedule advances on the SIM ``dt`` passed
    to :meth:`SalvoQueue.tick` (from ``sim_step``), never on real time, so it is
    scale-invariant under time-warp and reproducible.

Three modes (coastal-battery salvo doctrine):
  RIPPLE — fire each ready tube spaced by a fixed interval (the launch
           cinematic clears between rounds).
  FAN    — RIPPLE with a small deterministic aim spread per round for a
           multi-axis arrival.
  TOT    — time-on-target: stagger launches so rounds ARRIVE together
           (longer-flight rounds launch first); see :func:`tot_delays`.

The scheduler keeps the SCHEDULING MATH pure here; the GL/world wiring (camera
re-anchor, launch effects) lives in game/sandbox.py, which owns one SalvoQueue
and ticks it from ``sim_step`` BEFORE ``world.step`` so queued launches enter
the same frame.  SANDBOX worlds (no tube dicts) yield a zero ready count, so a
salvo there is a graceful no-op.
"""

from __future__ import annotations

import math

import numpy as np

# --- Doctrine modes -----------------------------------------------------------

SALVO_MODES = ("ripple", "fan", "tot")


def next_salvo_mode(mode: str) -> str:
    """The next salvo mode in the RIPPLE -> FAN -> TOT cycle (wraps).  An
    unknown current mode lands on the first entry rather than crashing."""
    try:
        i = SALVO_MODES.index(mode)
    except ValueError:
        return SALVO_MODES[0]
    return SALVO_MODES[(i + 1) % len(SALVO_MODES)]


# --- Tuning constants ---------------------------------------------------------

# Ripple spacing: ~1.5 s is enough for the Oniks launch cinematic
# (IGNITION/RIDE-OUT/PITCH-OVER/BOOST) to clear the muzzle before the next tube
# fires — the salvo can't fire faster than the launch physics allows.
RIPPLE_INTERVAL_S = 1.5

# FAN aim spread: a small lateral perturbation (metres) of the surface aim point
# per round so the rounds arrive on slightly different axes.  Small relative to
# a warhead lethal radius — it widens the arrival fan, it does not re-target.
FAN_SPREAD_M = 600.0

# TOT timing margin (s): slack added on top of the longest round's flight time
# so even the longest-flight round gets a non-negative launch window.
TOT_MARGIN_S = 2.0

# Deterministic child-stream tag for the FAN aim spread: np.random.default_rng(
# [seed, FAN_TAG, ordinal]).  Uses a DEDICATED tag (17) outside the allocated sim
# range 3-16, NOT the contested tag 9: NumPy SeedSequence drops a trailing-zero
# entry, so [seed, 9, 0] == [seed, 9] byte-for-byte — FAN's ordinal-0 stream would
# alias the CBR-reserved [seed, 9] stream (ROADMAP §5 reserves 9 for CBR).  Tag 17
# is FAN's own; 9 is left free for CBR.  (battle_idx is folded into the caller's
# seed via campaign.derive_seed, never a tag dimension.)
FAN_TAG = 17


# --- Pure helpers -------------------------------------------------------------

def ready_tube_count(world, platform: str) -> int:
    """Number of READY (loaded + re-cocked) tubes for ``platform`` — the size
    of the salvo the player can fire RIGHT NOW.

    Friendly own-force telemetry: reads only the player's OWN tube dicts, never
    any enemy state.  Mirrors the launch-path readiness predicate so the count
    matches what ``launch``/``launch_sam`` will actually fire:

      bastion -> Oniks tubes with ``loaded`` and ``reload_left <= 0``
      s300    -> S-300 tubes with ``reload_left <= 0``, bounded by the pooled
                 ``sam_ammo`` (a re-cocked tube still needs a round in the pool)

    SANDBOX worlds (no tube dicts) return 0, so a salvo is a graceful no-op."""
    if platform == "s300":
        tubes = getattr(world, "_s300_tubes", None)
        if not tubes:
            return 0
        recocked = sum(1 for t in tubes if t.get("reload_left", 0.0) <= 0.0)
        return min(recocked, max(0, int(getattr(world, "sam_ammo", 0))))
    tubes = getattr(world, "_oniks_tubes", None)
    if not tubes:
        return 0
    return sum(1 for t in tubes
               if t.get("loaded") and t.get("reload_left", 0.0) <= 0.0)


def fan_offset(seed: int, ordinal: int) -> np.ndarray:
    """Deterministic FAN aim offset (a ground-plane (x, 0, z) vector, metres)
    for round ``ordinal`` of a salvo, drawn from the seeded child stream
    ``[seed, FAN_TAG, ordinal]``.  Same seed+ordinal -> identical offset (the
    determinism contract); different seed OR ordinal -> a different offset."""
    rng = np.random.default_rng([int(seed), FAN_TAG, int(ordinal)])
    ang = float(rng.uniform(0.0, 2.0 * math.pi))
    mag = float(rng.uniform(0.25, 1.0)) * FAN_SPREAD_M
    return np.array([mag * math.cos(ang), 0.0, mag * math.sin(ang)],
                    dtype=np.float64)


def tot_delays(ranges, speed: float, margin: float = TOT_MARGIN_S) -> list:
    """Per-round launch delays (s) for a TIME-ON-TARGET salvo, relative to the
    first launch: every round arrives at the common instant
    ``T = max(range)/speed`` measured from the salvo start.

    A round at ground range ``r`` flying at ``speed`` takes ``r/speed`` to
    arrive, so to land at ``T`` it must launch ``T - r/speed`` after the salvo
    starts.  The longest-flight round launches FIRST (delay 0); shorter-flight
    rounds wait.  Delays are therefore monotone DECREASING in flight time and
    the implied arrival times coincide exactly.

    ``margin`` is a documented coordination-buffer knob (a minimum salvo window
    the caller may use for the camera/HUD countdown); it shifts every round
    uniformly so it does NOT change the relative spacing or the front-runner's
    zero delay, and so is left out of the returned relative delays.

    Degenerate ``speed <= 0`` (no flight-time model) yields all-zero delays
    (a plain simultaneous bundle), never a divide-by-zero."""
    rs = [float(r) for r in ranges]
    if not rs:
        return []
    if speed <= 0.0:
        return [0.0 for _ in rs]
    flight = [r / speed for r in rs]
    arrival = max(flight)
    return [max(0.0, arrival - f) for f in flight]


# --- The scheduler ------------------------------------------------------------

class SalvoQueue:
    """A queued ripple of launches over the existing per-tube launch path.

    Owned by the sandbox/combat state (NOT the world — the world stays
    single-shot/deterministic).  :meth:`start` arms the queue; :meth:`tick`
    (called from ``sim_step`` with the SIM ``dt``) fires the next round when its
    scheduled offset elapses, by calling the platform's launch method ONCE per
    beat.  A beat whose launch returns None (no ready tube — RELOADING/EMPTY)
    is consumed as a graceful no-op and the queue ends when the count is spent.

    All per-round timing offsets are SIM-time (no wall-clock), so the salvo is
    scale-invariant under time-warp and bit-reproducible."""

    def __init__(self):
        self._reset()

    def _reset(self) -> None:
        self.active = False
        self.platform = "bastion"
        self.mode = "ripple"
        self.count_left = 0
        self.interval = RIPPLE_INTERVAL_S
        self.profile = "hi-lo"
        self.target_point = None       # surface aim (bastion)
        self.target_id = None          # air track id (s300)
        self.round_id = "48n6"
        self.weapon_id = "oniks"
        self._seed = 0
        self._ordinal = 0              # rounds already fired this salvo (FAN)
        self._offsets = None           # per-round launch offsets (TOT); else None
        self._next_t = 0.0             # sim-time until the next beat fires
        self.last_round = None         # the most recent launched round (camera)

    def start(self, platform: str, *, mode: str = "ripple", count: int,
              interval: float = RIPPLE_INTERVAL_S, profile: str = "hi-lo",
              target_point=None, target_id=None, round_id: str = "48n6",
              weapon_id: str = "oniks", seed: int = 0, offsets=None) -> bool:
        """Arm a salvo of ``count`` rounds on ``platform``.  Returns False (and
        does not arm) when there is nothing to fire (count <= 0).  ``offsets``,
        when given (TOT), are the per-round launch delays from :func:`tot_delays`
        (longest-flight first); otherwise rounds are spaced by ``interval``.

        Offsets are SORTED on ingest: tot_delays returns delays in the
        caller's ``ranges`` order, but tubes are fungible, so the schedule
        fires the earliest delay first — an unsorted list would clamp
        negative gaps to 0 in _beat_gap and bunch the stagger (latent until
        a multi-aim-point TOT feeds differing ranges)."""
        if count <= 0:
            self._reset()
            return False
        self._reset()
        self.active = True
        self.platform = platform
        self.mode = mode
        self.count_left = int(count)
        self.interval = float(interval)
        self.profile = profile
        self.target_point = (None if target_point is None
                             else np.asarray(target_point, dtype=np.float64))
        self.target_id = target_id
        self.round_id = round_id
        self.weapon_id = weapon_id
        self._seed = int(seed)
        self._offsets = (sorted(float(o) for o in offsets)
                         if offsets is not None else None)
        self._next_t = 0.0             # the first round fires on the next tick
        return True

    def cancel(self) -> None:
        """Stop queuing further rounds (already-launched rounds fly on)."""
        self._reset()

    def tick(self, dt: float, world):
        """Advance the salvo by sim ``dt`` and fire any rounds now due.

        Returns the LAST round launched this tick (for the camera to follow),
        or None.  Several rounds can fall due in one tick at high warp / a TOT
        front-load; each is launched in order.  An idle queue is a no-op."""
        if not self.active:
            return None
        self._next_t -= dt
        fired = None
        # Fire every beat whose offset has elapsed this tick (>=1 at high warp).
        while self.active and self._next_t <= 0.0:
            rnd = self._fire_one(world)
            if rnd is not None:
                fired = rnd
                self.last_round = rnd
            self.count_left -= 1
            if self.count_left <= 0:
                self.active = False
                break
            self._next_t += self._beat_gap()
        return fired

    def _beat_gap(self) -> float:
        """Sim-time until the NEXT round after the one just fired.  TOT uses the
        difference between consecutive launch offsets (longest-flight first, so
        offsets are non-decreasing); otherwise the fixed ripple interval."""
        if self._offsets is not None:
            i = self._ordinal
            if 0 < i < len(self._offsets):
                return max(0.0, self._offsets[i] - self._offsets[i - 1])
            return 0.0
        return self.interval

    def _fire_one(self, world):
        """Launch a single round via the platform's existing launch method.
        Returns the round (or None when no tube is ready — a graceful no-op
        beat).  Increments the FAN ordinal regardless so the per-round seeded
        offset stream stays in lock-step with the schedule."""
        ordinal = self._ordinal
        self._ordinal += 1
        if self.platform == "s300":
            if self.target_id is None:
                return None
            return world.launch_sam(self.target_id, round_id=self.round_id)
        # Bastion: optionally perturb the aim point for the FAN mode.
        if self.target_point is None:
            return None
        aim = self.target_point
        if self.mode == "fan":
            aim = self.target_point + fan_offset(self._seed, ordinal)
        return world.launch(self.profile, aim, weapon_id=self.weapon_id)
