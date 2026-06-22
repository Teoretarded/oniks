"""AFTER-ACTION SCORING (M6) — pure, GL-free, headless-testable.

On battle end (``world.victorious`` / ``world.defeated`` already latched) the
COMBAT shell builds a :class:`ScoreCard` from MEASURED metrics and grades it
against a deterministic per-seed :class:`Par`.  Same seed -> same bar to beat.

Everything here is a MEASUREMENT of what already happened in the sim, never a
roll (physics-not-dice):

  * KILL TALLIES read ground-truth death flags (ships ``alive``, structure
    ``alive``, airfield ``alive``).  This is the ONE place truth may be read:
    the battle is over, the after-action report is omniscient by design (a real
    AAR is).  Nothing here feeds a fog-gated DECISION.

  * IN-BATTLE signals are fog-honest by construction:
      - ``first_fix_t`` is accumulated by the shell from the PLAYER contact
        picture (``world.contacts.tracks``), never from enemy truth.
      - ``was_back_plotted`` reads ``world.commander.picture.clusters`` — the
        ENEMY's sensor-derived belief, which never peeks at truth.

  * DETERMINISM: :func:`compute_par` draws its small per-seed jitter from a
    FRESH standalone ``np.random.default_rng([seed, PAR_TAG])`` on a DEDICATED
    free tag (tags 3-14 are taken by sim child streams; 15 is reserved here) so
    it never touches/interleaves with any sim RNG.  No wall-clock.

The shell (game/combat.py) owns a telemetry dict (see :func:`new_telemetry`)
that it updates in ``sim_step`` from the launch-wrapper return values and the
contact picture; at battle end it calls :func:`compute_scorecard` then
:func:`grade`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

# Dedicated free child-stream tag for the PAR jitter.  Tags 3-14 are consumed by
# the sim's [seed, tag] child streams; 15 is reserved for scoring so the PAR rng
# never interleaves with a sim stream (determinism contract).
PAR_TAG: int = 15


# --------------------------------------------------------------- telemetry

def new_telemetry() -> dict:
    """A fresh per-battle telemetry accumulator.

    The shell mutates this in ``sim_step``:
      * ``rounds_fired`` += 1 on each player round that actually launched
        (a non-None return from request_launch / _request_sam_launch / salvo).
      * ``leakers``      += 1 when a player round reaches terminal/hit
        (the go-low payoff: rounds that got through to their target).
      * ``first_fix_t``  latched (once) to ``world.sim_time`` the first time the
        PLAYER contact picture holds an enemy surface contact (recon->fire
        opening move).  Stays ``None`` if the enemy was never fixed.
    """
    return {"rounds_fired": 0, "leakers": 0, "first_fix_t": None}


def picture_has_actionable_contact(world) -> bool:
    """FOG-HONEST first-fix predicate: does the PLAYER contact picture hold an
    actionable enemy SURFACE contact (the recon->fire opening move)?

    Reads ONLY ``world.contacts.tracks`` (the radar-gated player picture) — an
    enemy ship is in ``tracks`` only once the player's radar/SAR/ELINT actually
    held it.  An UNDETECTED hostile (in ``world.missiles``, never in the gated
    picture) therefore NEVER trips this -> first_fix stays None until the player
    truly finds something.  A surface contact is ``is_air == False`` (inbound
    hostile ROUNDS are stamped is_air True and do not count as 'found the enemy
    to shoot').  Pure: takes a duck-typed world, no GL."""
    contacts = getattr(world, "contacts", None)
    tracks = getattr(contacts, "tracks", {}) if contacts is not None else {}
    for trk in tracks.values():
        if not trk.get("is_air", False):
            return True
    return False


# --------------------------------------------------------------- ScoreCard

@dataclass
class ScoreCard:
    """The measured after-action metrics + the assigned grade.

    All fields are plain measurements; ``grade`` is filled in by the shell after
    calling :func:`grade` (kept off :func:`compute_scorecard` so the metric read
    and the grading policy stay separable + independently testable)."""

    kills: int                  # enemy assets destroyed (ships + radars + field)
    enemy_total: int            # total enemy assets at battle start
    rounds_fired: int           # player rounds expended
    efficiency: float           # kills per round expended
    leak_rate: float            # rounds reaching terminal/hit / rounds fired
    first_fix_t: Optional[float]  # sim_time of first actionable enemy contact
    was_back_plotted: bool      # any targetable enemy-belief launch cluster
    base_intact_pct: float      # surviving player structures / total
    victory: bool               # world.victorious at end
    grade: str = ""             # S/A/B/C/D, assigned post-hoc


# --------------------------------------------------------------- PAR

@dataclass
class Par:
    """Deterministic per-seed bar the ScoreCard is graded against."""
    first_fix_t: float          # target time (s) to first actionable contact
    efficiency: float           # target kills-per-round
    leak_rate: float            # target leak fraction
    base_intact_pct: float      # target surviving-structure fraction


# Base PAR scaffold (tuning thresholds — a balance pass refines these with real
# playtest data; the spec gives a deterministic scaffold).
_PAR_BASE_FIRST_FIX_S = 300.0   # ~5 min baseline to first actionable contact
_PAR_PER_ASSET_FIRST_FIX_S = 45.0   # +45 s leniency per enemy asset to find
_PAR_BASE_EFFICIENCY = 0.45     # kills-per-round bar
_PAR_BASE_LEAK = 0.40           # leak-rate bar
_PAR_BASE_BASE_INTACT = 0.80    # surviving-structure bar


def _enemy_asset_count(config) -> int:
    """Targetable enemy assets the player must service, from the config force
    counts: destroyers + carrier(always 1) + ground radars + the airfield(1).
    A heavier fleet earns a more lenient time PAR and a stricter efficiency
    PAR (balance: a hard seed isn't graded on the same clock)."""
    n_dest = int(getattr(config, "n_destroyers", 0))
    n_flag = int(getattr(config, "n_flagship", 0))
    n_aaw = int(getattr(config, "n_aaw", 0))
    n_ga = int(getattr(config, "n_ground_attack", 0))
    n_radar = int(getattr(config, "n_enemy_radars", 0))
    ships = 1 + n_dest + n_flag + n_aaw + n_ga      # +1 carrier
    return ships + n_radar + 1                       # +1 airfield


def compute_par(seed: int, config) -> Par:
    """Deterministic per-seed PAR.

    Scales the base thresholds by the config force count, then applies a small
    seeded jitter (+-10%) from a FRESH standalone rng on the DEDICATED PAR_TAG
    so the bar is fixed per seed and reproducible, and NEVER touches a sim child
    stream or the numpy global rng (determinism contract)."""
    rng = np.random.default_rng([int(seed), PAR_TAG])
    assets = _enemy_asset_count(config)

    # +-10% deterministic jitter per axis (drawn in a FIXED order so the same
    # seed reproduces the same PAR bit-for-bit).
    j_first, j_eff, j_leak, j_base = (1.0 + 0.10 * (2.0 * rng.random() - 1.0)
                                      for _ in range(4))

    first_fix = (_PAR_BASE_FIRST_FIX_S
                 + _PAR_PER_ASSET_FIRST_FIX_S * assets) * j_first
    # heavier fleet -> a slightly STRICTER efficiency bar (more to kill per
    # round you can afford), bounded so it never goes negative.
    efficiency = max(0.1, _PAR_BASE_EFFICIENCY * (1.0 + 0.02 * assets)) * j_eff
    leak_rate = _PAR_BASE_LEAK * j_leak
    base_intact = min(1.0, _PAR_BASE_BASE_INTACT * j_base)
    return Par(first_fix_t=float(first_fix),
               efficiency=float(efficiency),
               leak_rate=float(leak_rate),
               base_intact_pct=float(base_intact))


# --------------------------------------------------------------- compute

def _ship_alive(s) -> bool:
    return bool(getattr(s, "alive", False))


def compute_scorecard(world, telemetry: dict) -> ScoreCard:
    """Read the END-STATE world + the accumulated telemetry into a ScoreCard.

    TRUTH READ (legitimate AAR): kill tallies from ship/structure ``alive``.
    FOG-HONEST: ``was_back_plotted`` from the enemy belief; ``first_fix_t`` and
    the round/leak counters from the shell's player-side telemetry."""
    ships = list(getattr(world, "ships", ()))
    enemy_radars = list(getattr(world, "enemy_radars", ()))
    airfield = getattr(world, "airfield", None)

    # ---- kills (truth, end-of-battle AAR) -------------------------------
    ships_total = len(ships)
    ships_dead = sum(1 for s in ships if not _ship_alive(s))
    radars_total = len(enemy_radars)
    radars_dead = sum(1 for struct, _r in enemy_radars
                      if not getattr(struct, "alive", False))
    field_total = 1 if airfield is not None else 0
    field_dead = 1 if (airfield is not None
                       and not getattr(airfield, "alive", False)) else 0

    kills = ships_dead + radars_dead + field_dead
    enemy_total = ships_total + radars_total + field_total

    # ---- player-structure survival (truth) ------------------------------
    structures = list(getattr(world, "structures", ()))
    if structures:
        alive = sum(1 for s in structures if getattr(s, "alive", False))
        base_intact_pct = alive / len(structures)
    else:
        base_intact_pct = 1.0

    # ---- telemetry counters (player-side, fog-honest) -------------------
    rounds_fired = int(telemetry.get("rounds_fired", 0))
    leakers = int(telemetry.get("leakers", 0))
    first_fix_t = telemetry.get("first_fix_t", None)

    efficiency = (kills / rounds_fired) if rounds_fired > 0 else 0.0
    leak_rate = (leakers / rounds_fired) if rounds_fired > 0 else 0.0

    # ---- back-plot (enemy belief, fog-honest) ---------------------------
    was_back_plotted = _read_back_plotted(world)

    return ScoreCard(
        kills=kills,
        enemy_total=enemy_total,
        rounds_fired=rounds_fired,
        efficiency=float(efficiency),
        leak_rate=float(leak_rate),
        first_fix_t=(float(first_fix_t) if first_fix_t is not None else None),
        was_back_plotted=was_back_plotted,
        base_intact_pct=float(base_intact_pct),
        victory=bool(getattr(world, "victorious", False)),
    )


def _read_back_plotted(world) -> bool:
    """True if the enemy commander confirmed ANY launch cluster (a targetable
    cluster in its sensor-derived belief).  Reads ONLY the enemy BELIEF
    (commander.picture.clusters), never truth."""
    commander = getattr(world, "commander", None)
    if commander is None:
        return False
    picture = getattr(commander, "picture", None)
    if picture is None:
        return False
    clusters = getattr(picture, "clusters", ()) or ()
    return any(getattr(c, "targetable", False) for c in clusters)


# --------------------------------------------------------------- grade

# Letter grade from a 0-5 merit score.  Five axes each contribute up to ~1
# point; the final letter is a banded sum so a single weak axis can't tank an
# otherwise-clean run and a single strong axis can't carry a disaster.
_GRADE_BANDS = ((4.5, "S"), (3.5, "A"), (2.5, "B"), (1.5, "C"))


def grade(scorecard: ScoreCard, par: Par) -> str:
    """Map (ScoreCard vs Par) -> letter S/A/B/C/D.

    Each of the five axes scores in [0, 1]; the banded sum picks the letter.
    A lost battle (no victory) is capped below S regardless (you cannot ace a
    battle you did not win)."""
    sc = scorecard
    score = 0.0

    # (1) base intact: meet/exceed PAR -> full point, scaled below.
    score += _ratio_score(sc.base_intact_pct, par.base_intact_pct)
    # (2) efficiency: kills per round vs PAR.
    score += _ratio_score(sc.efficiency, par.efficiency)
    # (3) leak rate: HIGHER is better (more rounds got through) vs PAR.
    score += _ratio_score(sc.leak_rate, par.leak_rate)
    # (4) first fix: EARLIER is better; never fixed -> 0.  Inverse ratio.
    if sc.first_fix_t is None:
        pass                                 # no points: never found the enemy
    else:
        score += _inverse_ratio_score(sc.first_fix_t, par.first_fix_t)
    # (5) was back-plotted: staying hidden is the EW payoff.
    score += 0.0 if sc.was_back_plotted else 1.0

    letter = "D"
    for threshold, name in _GRADE_BANDS:
        if score >= threshold:
            letter = name
            break

    # Cap: you cannot earn S without the win (the AAR honours the objective).
    if not sc.victory and letter == "S":
        letter = "A"
    return letter


def _ratio_score(value: float, par: float) -> float:
    """0..1 merit where HIGHER value is better: value/par clamped to [0, 1].
    A zero PAR (degenerate) yields a full point for any non-negative value."""
    if par <= 0.0:
        return 1.0
    return max(0.0, min(1.0, value / par))


def _inverse_ratio_score(value: float, par: float) -> float:
    """0..1 merit where LOWER value is better (e.g. time-to-first-fix):
    par/value clamped to [0, 1].  A non-positive value yields a full point."""
    if value <= 0.0:
        return 1.0
    return max(0.0, min(1.0, par / value))
