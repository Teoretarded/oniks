"""Battle 1b - the 'new battle / new seed' reload path (full App + GL).

Generation (battle 1) is clean, so a real "new seed never loads" bug would live
in the LOAD path: App.start_combat disposes the old session and builds a fresh
CombatState. This drives several seed-to-seed transitions in one App and checks
each new battle actually comes up - world built, frames render, sim advances.
A hang here (caught by the run timeout) or a missing/empty world reproduces it.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playtest_harness import finding, set_battle, write_report
from main import App, PHYS_DT
from world.combat_config import CombatConfig

SEEDS = [7, 42, 123, 1000, 5, 88]


def main():
    set_battle("battle1b-new-battle-reload")
    app = App(hidden=True)
    for i, sd in enumerate(SEEDS):
        print(f"[b1b] transition {i}: start_combat seed {sd} ...", flush=True)
        app.start_combat(CombatConfig(seed=sd, n_destroyers=4, oniks_ammo=20))
        st = app.state
        w = getattr(st, "world", None)
        # A 'never loads' bug shows up as a hang in start_combat/render above,
        # or a state with no world / no renderable frame here.
        for _ in range(12):
            st.sim_step(PHYS_DT)
            st.render(PHYS_DT)
        ok = (w is not None and len(getattr(w, "ships", [])) > 0)
        t = getattr(w, "sim_time", -1.0) if w else -1.0
        print(f"[b1b]   seed {sd}: world={'ok' if ok else 'MISSING'} "
              f"ships={len(w.ships) if w else 0} t={t:.2f} "
              f"state={type(st).__name__}", flush=True)
        if not ok:
            finding("CRASHER", f"new battle failed to load (seed {sd})",
                    detail=f"transition {i}: world missing/empty after "
                           f"start_combat; state={type(st).__name__}")
    print("[b1b] all transitions completed", flush=True)
    write_report()


if __name__ == "__main__":
    main()
