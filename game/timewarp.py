"""AUTO-TIME-WARP (M6) — pure, GL-free, headless-testable pacing director.

Generalises the EXISTING launch-cinematic 1x lock (``world.launch_realtime_lock``
+ ``game/sandbox.effective_time_scale``) and the ``TIME_SCALES`` ladder into a
smart event-aware pacing system, exactly the way every modern wargame/4X auto-
slows on contact:

  * the player sets a TARGET warp on the - / = ladder (extended past 16x);
  * when something IMPORTANT happens the effective scale auto-DROPS to 1x for
    the event window, holds for a real-time DWELL (debounce), then EASES back
    toward the target over ~RAMP_S seconds.

Two halves, both pure:

  1. :class:`TimeWarpDirector` — the easing/dwell state machine.  Its
     :meth:`tick` takes ``(dt_real, requested_scale, drop_active)`` and returns
     the effective scale.  NO pygame, NO GL, NO wall-clock: the only time it
     sees is the ``dt_real`` the caller hands it, so it is fully deterministic
     and unit-testable.

  2. The three DROP PREDICATES — pure functions of a (duck-typed) world.

FOG / NO-CHEAT (LOAD-BEARING).  The inbound-threat predicate reads ONLY the
player's DETECTED picture — a strike id that is held in BOTH ``_strike_board``
AND ``contacts.tracks`` (radar-gated / launch-warning cue).  It NEVER iterates
``world.missiles`` to decide "is a hostile inbound": a sea-skimming Tomahawk
under the horizon (alive + is_hostile + in the strike board, but NOT yet in
``contacts.tracks``) must NOT drop the warp, or the auto-warp itself would leak
that an undetected threat exists.  The own-round predicates (own-terminal /
intercept-window) read ``world.missiles`` directly because those are FRIENDLY
rounds the player owns — there is no fog on your own missiles.

DETERMINISM.  The director never feeds the sim; it only governs the real->sim
time multiplier the App loop already applies (``acc += dt_real * time_scale``).
The warp therefore stays a PURE multiplier on accumulated sim time, so the
commander / back-plot is bit-identical at any warp for a given seed.  A drop to
1x changes only real-time pacing, never a sim outcome.

PRACTICAL CEILING.  The App loop caps at 64 sim steps per rendered frame
(main.py), i.e. ~0.53 s of sim per frame at 120 Hz.  At 64x and 60 FPS that is
exactly the cap, so 64x is the documented effective ceiling even though the
ladder stops there; higher targets would simply saturate the step guard and
stall sim-time growth rather than run faster.
"""

from __future__ import annotations

import math

# --- Easing / debounce tuning (real-time seconds) -----------------------------

# Nominal ramp duration for a single ladder step's worth of change.  The ease
# runs in log2 space at a fixed slew, sized so an 8x (== 3 octaves) transition
# completes in RAMP_S; smaller steps are faster, the full 1<->64x span is ~2x
# RAMP_S.  ~1.5 s avoids a jarring snap (spec UX note).
RAMP_S = 1.5

# Octaves (log2 units) of warp the ease can traverse per real second.  An 8x
# transition is log2(8) == 3 octaves, so 3 / RAMP_S octaves/s lands it in
# exactly RAMP_S.
_SLEW_OCT_PER_S = 3.0 / RAMP_S

# Minimum real-time the warp holds at 1x AFTER the last triggering event clears
# (debounce): a flickering horizon track cannot strobe the warp.  >= 1.0 s is
# the spec contract.
DWELL_S = 1.0

# Phase label a missile reports in its terminal homing leg (sim/missile.py and
# sim/sam.py both expose the duck-typed ``phase_label`` == "TERMINAL").
_TERMINAL = "TERMINAL"


def _log2(x: float) -> float:
    return math.log2(x) if x > 0.0 else 0.0


class TimeWarpDirector:
    """Eases the effective time scale toward a target, dropping to 1x on an
    event and holding through a debounce dwell before ramping back.

    Pure state machine: ``tick`` is the only entry point.  All time is the
    ``dt_real`` the caller passes (the App loop's real frame dt) — there is no
    internal clock, so two identical tick sequences are bit-identical.
    """

    def __init__(self) -> None:
        # Current effective scale in log2 (octaves above 1x).  Starts parked at
        # 1x so the FIRST tick at target 1x is a no-op (byte-identical default:
        # auto-warp OFF leaves the requested scale untouched, see sandbox).
        self._eff_oct = 0.0
        self._dwell_left = 0.0          # real-time s remaining at the 1x hold
        self._cause: str | None = None  # latched drop-cause tag for the HUD

    @property
    def effective(self) -> float:
        """The current effective scale (>= 1.0)."""
        return 2.0 ** self._eff_oct

    @property
    def dropped(self) -> bool:
        """True while a drop/dwell is holding the warp at (or easing to) 1x."""
        return self._dwell_left > 0.0

    @property
    def cause(self) -> str | None:
        """The LATCHED cause tag of the active drop ('INBOUND'/'TERMINAL'/
        'INTERCEPT'/'LAUNCH').  Unlike re-evaluating ``drop_cause`` every
        frame, the latch holds through the DWELL debounce — the HUD tag
        cannot flicker off while the warp is still parked at 1x — and clears
        only once the dwell expires."""
        return self._cause

    def reset(self, scale: float = 1.0) -> None:
        """Snap the effective scale (no ease) — used when auto-warp is toggled
        on so the indicator starts from the current requested rate, not a
        stale eased value."""
        self._eff_oct = _log2(max(1.0, scale))
        self._dwell_left = 0.0
        self._cause = None

    def tick(self, dt_real: float, requested_scale: float,
             drop_active: bool, cause: str | None = None) -> float:
        """Advance one real frame and return the effective scale.

        ``drop_active`` is the OR of the launch-cinematic lock and the fog-safe
        drop predicates (passed in by the sandbox).  While it is True the warp
        eases to 1x and the dwell timer is (re)armed; once it clears the warp
        holds 1x until the dwell expires, then eases back to ``requested``.

        ``cause`` is the current drop-cause tag; it is latched while the drop
        (and its dwell) holds so the HUD label stays stable frame-to-frame.
        ``None`` during a drop keeps the previous latch (defensive: legacy
        callers that never pass a cause keep their exact old behaviour).
        """
        dt = max(0.0, float(dt_real))
        if drop_active:
            self._dwell_left = DWELL_S          # re-arm the debounce each frame
            if cause is not None:
                self._cause = cause             # latch the live cause
            target_oct = 0.0                    # ease toward 1x
        elif self._dwell_left > 0.0:
            self._dwell_left = max(0.0, self._dwell_left - dt)
            if self._dwell_left <= 0.0:
                self._cause = None              # dwell just expired
            target_oct = 0.0                    # hold 1x through the dwell
        else:
            self._cause = None                  # dwell over: clear the latch
            target_oct = _log2(max(1.0, requested_scale))
        self._ease_toward(target_oct, dt)
        return self.effective

    def _ease_toward(self, target_oct: float, dt: float) -> None:
        """Rate-limited move of the effective octave toward ``target_oct`` at
        the fixed slew (linear in log2 space -> a smooth multiplicative ramp)."""
        step = _SLEW_OCT_PER_S * dt
        delta = target_oct - self._eff_oct
        if abs(delta) <= step:
            self._eff_oct = target_oct          # snap the final sub-step
        else:
            self._eff_oct += math.copysign(step, delta)


# --- Fog-safe drop predicates -------------------------------------------------
#
# Each takes a (duck-typed) world and returns a bool.  They are deliberately
# defensive (getattr / .get) so a SANDBOX WorldState — which has no strike
# board / pantsirs — yields False everywhere and never drops the warp.


def inbound_detected(world) -> bool:
    """A hostile strike round the player's RADAR HOLDS is inbound.

    FOG-SAFE: a track is "detected inbound" only when its id is in BOTH the
    player strike board (so it IS a hostile strike round, not a friendly air
    track) AND ``contacts.tracks`` with ``is_air`` (so the radar / launch-
    warning cue actually holds it).  An undetected hostile (in ``_strike_board``
    but absent from ``contacts.tracks``) is INVISIBLE here — never iterate
    ``world.missiles`` for this decision.
    """
    board = getattr(world, "_strike_board", None)
    if not board:
        return False
    contacts = getattr(world, "contacts", None)
    tracks = getattr(contacts, "tracks", None)
    if not tracks:
        return False
    for cid in board:
        trk = tracks.get(cid)
        if trk is not None and trk.get("is_air"):
            return True                         # radar holds a hostile strike
    return False


def own_terminal(world) -> bool:
    """A player (NOT hostile) Missile is in its TERMINAL homing leg — the
    satisfying own-round hit.  Reads ``world.missiles`` directly: a friendly
    round the player owns has no fog."""
    for m in getattr(world, "missiles", ()):
        if (getattr(m, "alive", False)
                and not getattr(m, "is_hostile", False)
                and getattr(m, "phase_label", None) == _TERMINAL
                and not _is_sam(m)):
            return True
    return False


def intercept_window(world) -> bool:
    """An active intercept: a non-hostile SAM round (player S-300 or Pantsir
    57E6) in TERMINAL, OR any Pantsir currently engaging.  Friendly rounds /
    own units -> truth read is fog-safe."""
    for m in getattr(world, "missiles", ()):
        if (getattr(m, "alive", False)
                and not getattr(m, "is_hostile", False)
                and _is_sam(m)
                and getattr(m, "phase_label", None) == _TERMINAL):
            return True
    for unit in getattr(world, "pantsirs", ()):
        if getattr(unit, "alive", True) and _pantsir_engaging(unit):
            return True
    return False


def event_drop(world) -> bool:
    """The OR of the three fog-safe drop predicates — True when the auto-warp
    should ease to 1x for an in-progress event (the launch-cinematic lock is
    OR'd in separately by the sandbox)."""
    return (inbound_detected(world) or own_terminal(world)
            or intercept_window(world))


def drop_cause(world) -> str | None:
    """The cause tag for the active event drop (for the HUD): 'INBOUND' (a
    detected hostile strike), 'TERMINAL' (an own round homing in), or
    'INTERCEPT' (a friendly SAM / Pantsir engaging).  None when no event
    predicate is firing.  Priority INBOUND > TERMINAL > INTERCEPT — a detected
    threat is the most urgent reason to slow down.  Fog-safe (delegates to the
    same predicates)."""
    if inbound_detected(world):
        return "INBOUND"
    if own_terminal(world):
        return "TERMINAL"
    if intercept_window(world):
        return "INTERCEPT"
    return None


# --- predicate helpers (kept private so the public surface stays small) -------

def _is_sam(m) -> bool:
    """Duck-typed: a SAM round (S-300 / Pantsir 57E6) carries a ``sam_phase``
    or is an instance whose class name ends in 'SamMissile'.  Used only to
    split own-round (cruise) terminals from intercept (SAM) terminals; both are
    friendly so this never touches fog."""
    if hasattr(m, "sam_phase"):
        return True
    return type(m).__name__.endswith("SamMissile")


def _pantsir_engaging(unit) -> bool:
    """A Pantsir is 'engaging' when its point-defense fire control currently
    holds a FORMED track on a live inbound hostile (gun/SAM channels actively
    prosecuting it) or has a 57E6 in flight.  ``sim/pantsir.py`` publishes this
    own-force signal as the ``unit.engaging`` flag every step (the same gun-
    channel engagement the HUD 'ENGAGING' cue reflects), so the gun-only window
    — a threat inside GUN_RANGE_M with no SAM in the air — drops the warp too.
    Reads own-force state only (the Pantsir is a player unit) -> fog-safe.
    Defensive: returns False for any unit shape lacking the bool signal."""
    for attr in ("engaging", "is_engaging"):
        val = getattr(unit, attr, None)
        if isinstance(val, bool):
            return val
    return False
