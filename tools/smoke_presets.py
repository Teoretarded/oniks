"""Per-preset COMBAT smoke: the AI finds fire lines on every map (M3-F4).

For each map preset (0 OPEN SEA / 1 ARCHIPELAGO / 2 NARROW STRAIT /
3 FJORD COAST) this builds a CombatWorld and asserts the battle is neither
broken-on-arrival nor soft-locked:

  * every ship spawns in OPEN WATER on the active preset field (no beaching),
  * the enemy commander schedules a strike off the player radar's ESM fix
    (the enemy AI finds a fire line — it is not stuck), and
  * a player Oniks fired up the central corridor FLIES (clears terrain — the
    corridor stays navigable; it is not grounded on a preset island),
  * the battle resolves to victory when every enemy asset is killed (the win
    condition is reachable on the preset, i.e. WINNABLE).

Pure sim (GL-free): exits 0 when all presets pass, 1 otherwise.

Run: python tools/smoke_presets.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from main import PHYS_DT
from sim.ships import ST_GONE
from world.combat import CombatWorld
from world.combat_config import CombatConfig, MAP_PRESET_NAMES

DT4 = 0.25


def run_preset(p: int) -> bool:
    name = MAP_PRESET_NAMES[p]
    ok = True

    def check(label, cond):
        nonlocal ok
        print(f"[preset {p} {name}] {'PASS' if cond else 'FAIL'}  {label}")
        ok = ok and cond

    cfg = CombatConfig(seed=1337, map_preset=p, n_enemy_radars=2)
    w = CombatWorld(cfg)
    hf = w.height_field.height_scalar

    # 1. No ship beached on the active field.
    beached = [s.ship_id for s in w.ships
               if hf(float(s.pos[0]), float(s.pos[2])) > 0.0]
    check("all ships in open water (none beached)", not beached)

    # 2. Enemy AI finds a fire line: the radar emits, the ESM fix matures and
    #    the commander schedules a HARM strike (not soft-locked).
    w.radar_station.emitting = True
    scheduled = False
    for _ in range(int(120.0 / DT4)):
        w.step(DT4)
        if any(m["kind"] == "harm_package" for m in w._cmd_missions):
            scheduled = True
            break
    check("enemy commander schedules a HARM strike off the ESM fix", scheduled)

    # 3. The central corridor is navigable: a player Oniks fired straight up
    #    the middle FLIES (is not grounded by a preset island). Fire at a deep
    #    mid-ocean point on the x=0 corridor and confirm it climbs/cruises.
    w2 = CombatWorld(cfg)
    tgt = np.array([0.0, 0.0, 300_000.0])
    m = w2.launch("hi-lo", tgt)
    flew = False
    grounded = False
    if m is not None:
        # The Oniks (Mach ~2.5) climbs to cruise and tracks up the corridor.
        # "Not grounded" = it gets well downrange at cruise altitude without a
        # premature ground/terrain impact (a corridor island would clip it).
        for _ in range(int(90.0 / PHYS_DT)):
            w2.step(PHYS_DT)
            if not m.alive:
                # Died deep downrange? fine. Died short + low (a corridor
                # island clipped it)? that is a grounded soft-lock.
                grounded = m.pos[2] < 40_000.0 and m.pos[1] < 50.0
                break
            # Reached cruise altitude well clear of any terrain, downrange up
            # the corridor: definitively flying, not grounded on an island.
            if m.pos[1] > 5_000.0 and m.pos[2] > 30_000.0:
                flew = True
                break
    check("player Oniks flies the central corridor (not grounded)",
          flew and not grounded)

    # 4. WINNABLE: killing every enemy asset flips victory on this preset.
    w3 = CombatWorld(cfg)
    for s in w3.ships:
        s.state = ST_GONE
    w3.airfield.alive = False
    for st, r in w3.enemy_radars:
        st.alive = False
        r.alive = False
    check("victory reachable (all enemy assets dead -> victorious)",
          w3.victorious)

    return ok


def main() -> int:
    all_ok = True
    for p in range(len(MAP_PRESET_NAMES)):
        all_ok = run_preset(p) and all_ok
        print()
    print("ALL PRESETS PASS" if all_ok else "SOME PRESETS FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
