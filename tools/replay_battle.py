"""Replay a recorded battle ledger bit-for-bit and verify it (BLACK BOX).

The bug-hunting loop this closes: the player flags a moment with F3 (or a
battle just leaves its ledger in blackbox/); this tool rebuilds the same
CombatWorld from the recorded config, re-applies every player command at
its recorded tick, and

  * VERIFIES every periodic hash record against the replayed state — a
    mismatch is a recording gap or a determinism regression, reported with
    the first bad tick (exit 1, never absorbed);
  * prints the ledger's event/hint/loss timeline next to the replay so a
    reader (human or AI) sees the battle without the renderer;
  * with --to-tick N, stops after N ticks and dumps a deep state summary
    (every missile's kind/pos/vel/phase, every ship, the fog picture) —
    the "pause at the flagged moment and look at everything" move.

Usage:
    python tools/replay_battle.py blackbox/battle_X.jsonl
    python tools/replay_battle.py bug_reports/bug_001/ledger.jsonl --to-tick 1500
    python tools/replay_battle.py <ledger> --quiet      (verify only)

Headless, GL-free, deterministic (fixed 120 Hz, seeded RNG, no wall clock).
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from game.blackbox import load_ledger, state_digest, _apply_record
from world.combat import CombatWorld
from world.combat_config import CombatConfig

DT = 1.0 / 120.0


def fmt_t(t: float) -> str:
    return f"T+{int(t // 60):02d}:{int(t % 60):02d}"


def replay(header: dict, records: list[dict], to_tick: int | None,
           quiet: bool) -> int:
    cfg_dict = dict(header.get("config") or {})
    cfg = CombatConfig(**cfg_dict) if cfg_dict else CombatConfig()
    world = CombatWorld(cfg)

    cmds: dict[int, list[dict]] = {}
    hashes: dict[int, str] = {}
    last_tick = 0
    for r in records:
        if r["rec"] in ("cmd", "toggle"):
            cmds.setdefault(int(r["tick"]), []).append(r)
            last_tick = max(last_tick, int(r["tick"]))
        elif r["rec"] == "hash":
            hashes[int(r["tick"])] = r["digest"]
            last_tick = max(last_tick, int(r["tick"]))
        elif r["rec"] in ("mark", "end"):
            last_tick = max(last_tick, int(r.get("tick", 0)))

    n_ticks = to_tick if to_tick is not None else last_tick
    if n_ticks <= 0:
        print("[replay] nothing to replay (no ticked records)")
        return 0

    print(f"[replay] seed {header.get('seed')} commit "
          f"{header.get('commit') or '---'} -> {n_ticks} ticks "
          f"({n_ticks / 120.0:.1f} s sim)")
    bad = 0
    for t in range(int(n_ticks)):
        for rec in cmds.get(t, ()):
            if not quiet:
                if rec["rec"] == "toggle":
                    print(f"  {fmt_t(rec['t'])} tick {t:>6}  TOGGLE "
                          f"{rec['name']} -> {rec['value']}")
                else:
                    state = "ok" if rec.get("ok") else "DENIED"
                    print(f"  {fmt_t(rec['t'])} tick {t:>6}  {rec['verb']} "
                          f"[{state}] {rec['args']}")
            _apply_record(world, rec)
        world.step(DT)
        world.drain_events()
        tick_now = t + 1
        want = hashes.get(tick_now)
        if want is not None:
            got = state_digest(world)
            okc = "OK" if got == want else "MISMATCH"
            if got != want:
                bad += 1
                print(f"  tick {tick_now:>6}  HASH {okc}  recorded "
                      f"{want[:12]}...  replayed {got[:12]}...")
            elif not quiet:
                print(f"  tick {tick_now:>6}  HASH {okc}")

    print(f"[replay] done at tick {n_ticks} "
          f"(sim {world.sim_time:.1f} s) - digest {state_digest(world)[:16]}")
    if not quiet:
        _dump_state(world)
        _dump_timeline(records, n_ticks)
    if bad:
        print(f"[replay] {bad} HASH MISMATCH(ES) - recording gap or "
              f"determinism regression. FAIL.")
        return 1
    print("[replay] all recorded hashes verified" if hashes
          else "[replay] no hash records to verify")
    return 0


def _dump_state(world) -> None:
    print("\n--- WORLD STATE AT STOP ------------------------------------")
    for m in world.missiles:
        v = float(np.linalg.norm(m.vel))
        host = "HOSTILE" if getattr(m, "is_hostile", False) else "own"
        wid = getattr(getattr(m, "weapon", None), "weapon_id", type(m).__name__)
        print(f"  round {wid:<10} {host:<7} phase {m.phase_label:<10} "
              f"pos ({m.pos[0]:9.0f},{m.pos[1]:7.0f},{m.pos[2]:9.0f}) "
              f"spd {v:5.0f} m/s alive {m.alive}")
    for s in world.ships:
        print(f"  ship  {s.ship_id:<14} state {s.state} "
              f"pos ({s.pos[0]:9.0f},{s.pos[2]:9.0f})")
    print("  --- fog picture (player tracks) ---")
    for cid, trk in world.contacts.tracks.items():
        print(f"  track {cid:<18} kind {trk.get('kind') or '-':<10} "
              f"air {bool(trk.get('is_air'))} age {trk.get('age', 0.0):.1f}s")


def _dump_timeline(records: list[dict], n_ticks: int) -> None:
    print("\n--- LEDGER TIMELINE (evt/hint/loss/mark/end) -----------------")
    for r in records:
        kind = r["rec"]
        if kind == "evt":
            print(f"  {fmt_t(r['t'])}  EVT   {r['kind']}")
        elif kind == "hint":
            print(f"  {fmt_t(r['t'])}  HINT  {r['text']}")
        elif kind == "loss":
            print(f"  {fmt_t(r['t'])}  LOSS  {r.get('kind')}-{r.get('seq')} "
                  f"{r.get('code')} {r.get('detail')} "
                  f"observed={r.get('observed')}")
        elif kind == "mark":
            print(f"  {fmt_t(r['t'])}  MARK  <<< {r.get('note')} >>> "
                  f"tick {r.get('tick')}")
        elif kind == "end":
            print(f"  {fmt_t(r['t'])}  END   {r.get('outcome')} "
                  f"grade {r.get('grade') or '-'}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("ledger", help="battle ledger JSONL (blackbox/ or a "
                                   "bug_reports/bug_NNN/ledger.jsonl)")
    ap.add_argument("--to-tick", type=int, default=None,
                    help="stop after N ticks and dump deep state")
    ap.add_argument("--quiet", action="store_true",
                    help="hash verification only, no timeline")
    args = ap.parse_args()
    header, records = load_ledger(args.ledger)
    if not header:
        print("[replay] no header record - not a battle ledger")
        return 2
    return replay(header, records, args.to_tick, args.quiet)


if __name__ == "__main__":
    raise SystemExit(main())
