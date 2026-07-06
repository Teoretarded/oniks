"""WAR SANDBOX frame budget probe: the live toybox at 8x, no staging.

usage: python -m tools.perf_sandbox_war [frames]    (default 300)

Hidden 1600x900 window, SandboxWarState fresh from the menu path, camera
400 m over the base looking north (the perf_harness vantage).  Each
frame advances 16 fixed 120 Hz substeps (8x at 60 FPS) then renders the
full scene.  The present is NOT timed (hidden windows are DWM-throttled
— see tools/perf_harness.py, which measures swap properly on the staged
worst case); this probe answers one question: does the 22-hull + subs +
enemy-air toybox hold the 16 ms CPU budget?  Exits 1 over budget.
"""

from __future__ import annotations

import sys
import time

import numpy as np

from main import PHYS_DT, App

FRAMES_DEFAULT = 300
SUBSTEPS = 16                 # 8x time accel at a 60 FPS render rate
BUDGET_MS = 16.0


def main(argv: list[str]) -> None:
    frames = int(argv[0]) if argv else FRAMES_DEFAULT
    app = App(hidden=True)
    from game.sandbox_war import SandboxWarState
    state = SandboxWarState(app)
    app.states.switch(state)
    app.sandbox = state
    from world.generation import BASE_POS
    state.rig.set_mode("free")
    state.rig.freecam.pos = np.array(
        [BASE_POS[0], BASE_POS[1] + 400.0, BASE_POS[2] - 400.0])
    state.rig.freecam.yaw = 0.0
    state.rig.freecam.pitch = -0.3
    # Terrain LOD warm-up so streaming builds don't pollute the timings.
    for _ in range(1200):
        state.render(0.0)
        if not state.terrain._jobs:
            break
    sim_ms = []
    render_ms = []
    for _ in range(frames):
        t0 = time.perf_counter()
        for _ in range(SUBSTEPS):
            state.sim_step(PHYS_DT)
        t1 = time.perf_counter()
        state.render(1.0 / 60.0)
        t2 = time.perf_counter()
        sim_ms.append((t1 - t0) * 1000.0)
        render_ms.append((t2 - t1) * 1000.0)
    sim = np.array(sim_ms)
    ren = np.array(render_ms)
    tot = sim + ren
    print(f"frames {frames}  substeps/frame {SUBSTEPS} (8x)")
    print(f"sim    avg {sim.mean():6.2f} ms  p95 {np.percentile(sim, 95):6.2f}")
    print(f"render avg {ren.mean():6.2f} ms  p95 {np.percentile(ren, 95):6.2f}")
    print(f"TOTAL  avg {tot.mean():6.2f} ms  p95 {np.percentile(tot, 95):6.2f}"
          f"  budget {BUDGET_MS} ms")
    if tot.mean() > BUDGET_MS:
        print("OVER BUDGET")
        raise SystemExit(1)
    print("PASS")


if __name__ == "__main__":
    main(sys.argv[1:])
