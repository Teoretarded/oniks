"""Probe: play a scripted CombatWorld battle and print the after-action card.

Measure-don't-guess harness for M6 AFTER-ACTION SCORING (game/scoring.py).  It
runs a REAL CombatWorld (the SM-2 screen, the contact picture, the commander
back-plot are all in the loop), fires a scripted Oniks salvo at the fleet, steps
the sim, and accumulates the SAME fog-honest telemetry the COMBAT shell does in
``CombatState.sim_step``:

  * rounds_fired  — counted on each launch (the wrapper's non-None return);
  * first_fix_t   — latched when the PLAYER contact picture first holds a
                    surface (enemy ship) contact;
  * leakers       — each player OFFENSIVE round that reaches its TERMINAL leg.

At the end it builds the ScoreCard (the AAR truth read: kill tallies), computes
the per-seed PAR, grades it, and prints the card vs PAR.  This mirrors
playtest_killchain.py's scripted-battle style; it is a TOOL, not a test.

Run:  python tools/probe_scoring.py [--seed 1337] [--steps 60000] [--n-oniks 2]
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from game.scoring import (
    compute_par, compute_scorecard, grade, new_telemetry,
    picture_has_actionable_contact,
)
from world.combat import CombatWorld
from world.combat_config import CombatConfig

PHYS_DT = 1.0 / 120.0


def _is_player_offensive(m) -> bool:
    """Player OFFENSIVE round (Oniks cruise) in TERMINAL — mirrors
    CombatState._is_player_offensive (the leaker signal)."""
    if getattr(m, "is_hostile", False):
        return False
    if hasattr(m, "sam_phase") or type(m).__name__.endswith("SamMissile"):
        return False
    return True


def run(seed: int, steps: int, n_oniks: int) -> None:
    cfg = CombatConfig(seed=seed, n_oniks=max(1, n_oniks))
    world = CombatWorld(cfg)
    tel = new_telemetry()
    leaker_seen: set[int] = set()

    # Scripted salvo: aim a few rounds at the deep band (the carrier/escort
    # anchors) so the contact picture, the SM-2 screen and the commander
    # back-plot all wake up — a realistic recon->fire opening.
    targets = [np.array([0.0, 0.0, 200_000.0]),
               np.array([40_000.0, 0.0, 260_000.0]),
               np.array([-20_000.0, 0.0, 180_000.0]),
               np.array([20_000.0, 0.0, 220_000.0])]
    fire_at = {120: 0, 1200: 1, 2400: 2, 3600: 3}

    for i in range(steps):
        if i in fire_at:
            profile = "lo-lo" if (i // 1200) % 2 else "hi-lo"
            m = world.launch(profile, targets[fire_at[i]])
            if m is not None:
                tel["rounds_fired"] += 1
        world.step(PHYS_DT)

        # first-fix: PLAYER contact picture holds a surface (ship) contact.
        if tel["first_fix_t"] is None and picture_has_actionable_contact(world):
            tel["first_fix_t"] = float(world.sim_time)

        # leakers: each player offensive round entering TERMINAL, once.
        for m in world.missiles:
            mid = id(m)
            if mid in leaker_seen:
                continue
            if (getattr(m, "phase_label", None) == "TERMINAL"
                    and _is_player_offensive(m)):
                leaker_seen.add(mid)
                tel["leakers"] += 1

        if world.victorious or world.defeated:
            break

    card = compute_scorecard(world, tel)
    par = compute_par(seed, cfg)
    card.grade = grade(card, par)

    print(f"=== AFTER-ACTION CARD  seed={seed}  sim_t={world.sim_time:6.1f}s "
          f"({'VICTORY' if card.victory else 'no-win'}) ===")
    print(f"  GRADE          {card.grade}")
    print(f"  KILLS          {card.kills}/{card.enemy_total}")
    print(f"  ROUNDS         {card.rounds_fired}")
    print(f"  EFFICIENCY     {card.efficiency:5.2f}   "
          f"(PAR {par.efficiency:5.2f})")
    ff = "never" if card.first_fix_t is None else f"{card.first_fix_t:6.1f}s"
    print(f"  FIRST FIX      {ff}   (PAR {par.first_fix_t:6.1f}s)")
    print(f"  BACK-PLOTTED   {'YES' if card.was_back_plotted else 'NO'}")
    print(f"  LEAK RATE      {card.leak_rate * 100:4.0f}%   "
          f"(PAR {par.leak_rate * 100:4.0f}%)")
    print(f"  BASE INTACT    {card.base_intact_pct * 100:4.0f}%  "
          f"(PAR {par.base_intact_pct * 100:4.0f}%)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--steps", type=int, default=60000)
    ap.add_argument("--n-oniks", type=int, default=2)
    a = ap.parse_args()
    run(a.seed, a.steps, a.n_oniks)
