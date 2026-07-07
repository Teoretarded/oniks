"""F3-P3 cloud perf gate — built BEFORE the cloud shader (the gate exists
on day one; the baseline row is the evidence the shader's cost is judged
against).

usage: python -m tools.perf_clouds [frames]     (default 600)

Reuses tools/perf_harness.py's worst-case scene and FencePacer, with the
camera pitched AT THE HORIZON (the worst cloud-march geometry: maximum
slab traversal per ray) and a dedicated ``clouds`` timer section around
``state.clouds.draw`` (zero until world/clouds.py lands — the pre-cloud
run IS the baseline).

Budgets (locked, F3): clouds ≤ 3.0 ms avg / 5.0 ms p95 at 1600×900;
whole frame ≤ 16.0 ms avg.  Exit 1 on any budget miss.
"""

from __future__ import annotations

import sys
import time

import numpy as np
import pygame

from tools.perf_harness import (FencePacer, SUBSTEPS, WARMUP_FRAMES,
                                setup_scene)
from main import PHYS_DT, App

FRAMES = 600
CLOUD_BUDGET_AVG_MS = 3.0
CLOUD_BUDGET_P95_MS = 5.0
FRAME_BUDGET_MS = 16.0
HORIZON_PITCH = -0.02          # worst case: rays graze the whole slab

SECTIONS = ("sim_step", "scene", "clouds", "hud", "swap", "other")


_GPU_QUERY = None


def _cloud_gpu_query():
    """One GL_TIME_ELAPSED query, lazily created (needs a live context)."""
    global _GPU_QUERY
    if _GPU_QUERY is None:
        from OpenGL.GL import glGenQueries
        _GPU_QUERY = int(np.atleast_1d(glGenQueries(1))[0])
    return _GPU_QUERY


def render_frame(s, timers=None):
    """Sandbox render order + the clouds slot (after particles, before
    HUD — the locked 'drawn LAST into the default framebuffer' position).

    The ``clouds`` section is GPU time via GL_TIME_ELAPSED — the CPU wall
    clock around the draw call only measures command submission (~0.1 ms)
    while the actual raymarch cost lands in the fence-paced swap; the v5
    playtest FPS collapse hid behind that blind spot (2026-07-07)."""
    mark = time.perf_counter
    w, h = s.window.size()
    t0 = mark()
    s.rig.update(1.0 / 60.0, s.followed)
    s.renderer.begin(s.camera, w / h)
    s.sky.draw(s.renderer)
    t1 = mark()
    s.terrain.draw(s.renderer)
    s.ocean.draw(s.renderer, s.camera, s.world.sim_time,
                 sea_amp=getattr(s, "_sea_amp", 1.0))
    for mesh, pos in s._site_draws:
        s.renderer.draw_mesh(mesh, pos)
    s._draw_ships()
    s._draw_aircraft()
    s._draw_tel()
    s._draw_missiles()
    s.particles.draw(s.renderer, s.effects)
    t2 = mark()
    clouds = getattr(s, "clouds", None)
    gpu_ns = 0
    if clouds is not None and clouds.enabled:
        from OpenGL.GL import (GL_QUERY_RESULT, GL_TIME_ELAPSED,
                               glBeginQuery, glEndQuery,
                               glGetQueryObjectuiv)
        q = _cloud_gpu_query()
        glBeginQuery(GL_TIME_ELAPSED, q)
        clouds.draw(s.renderer, s.camera, s.world.sim_time)
        glEndQuery(GL_TIME_ELAPSED)
        gpu_ns = int(glGetQueryObjectuiv(q, GL_QUERY_RESULT))
    t3 = mark()
    if s.hud_visible:
        s.hud.draw(s, w, h)
    t4 = mark()
    if timers is not None:
        timers["other"] += t1 - t0
        timers["scene"] += t2 - t1
        timers["clouds"] += gpu_ns * 1e-9
        timers["hud"] += t4 - t3


def run(frames: int = FRAMES, mist: bool = False) -> int:
    app = App(hidden=True)
    s = setup_scene(app)
    s.rig.freecam.pitch = HORIZON_PITCH     # stare through the slab
    if mist:
        # v6 gate: the playtest FPS collapse happened INSIDE the layer —
        # every pixel marches thin cloud with no early-out. Park the camera
        # in the fair-cu band staring down its length.
        s.rig.freecam.pos = np.array([0.0, 1_400.0, 40_000.0])
        s.rig.freecam.pitch = 0.02
    s.rig.update(0.0, None)

    for _ in range(WARMUP_FRAMES):
        render_frame(s)
        if not s.terrain._jobs:
            break

    pacer = FencePacer(s.window)
    pacer.probe_throttle()

    from OpenGL.GL import GL_RENDERER, glGetString
    name = glGetString(GL_RENDERER)
    if name:
        print(f"[perf] GL_RENDERER: {name.decode()}")
    has_clouds = getattr(s, "clouds", None) is not None
    print(f"[perf] clouds pass present: {has_clouds}"
          + ("" if has_clouds else "  (BASELINE run)"))

    per = {k: np.empty(frames) for k in SECTIONS}
    totals = np.empty(frames)
    mark = time.perf_counter
    for f in range(frames):
        pygame.event.pump()
        timers = dict.fromkeys(SECTIONS, 0.0)
        t0 = mark()
        for _ in range(SUBSTEPS):
            s.sim_step(PHYS_DT)
        timers["sim_step"] = mark() - t0
        render_frame(s, timers)
        t2 = mark()
        excluded = pacer.end_frame()
        timers["swap"] = mark() - t2 - excluded
        for k in SECTIONS:
            per[k][f] = timers[k]
        totals[f] = mark() - t0 - excluded

    pygame.quit()
    if pacer.throttled:
        print("[perf] NOTE: hidden-window presents OS-throttled; swap = "
              "fence-paced GPU completion (see perf_harness)")

    ms = 1e3
    print(f"\n[perf] cloud gate scene, {frames} frames x {SUBSTEPS} substeps")
    print(f"{'section':<10}{'avg ms':>9}{'p95 ms':>9}")
    for k in SECTIONS:
        print(f"{k:<10}{per[k].mean() * ms:>9.2f}"
              f"{np.percentile(per[k], 95) * ms:>9.2f}")
    avg_total = totals.mean() * ms
    print(f"{'TOTAL':<10}{avg_total:>9.2f}"
          f"{np.percentile(totals, 95) * ms:>9.2f}")

    c_avg = per["clouds"].mean() * ms
    c_p95 = np.percentile(per["clouds"], 95) * ms
    ok = (c_avg <= CLOUD_BUDGET_AVG_MS and c_p95 <= CLOUD_BUDGET_P95_MS
          and avg_total <= FRAME_BUDGET_MS)
    print(f"[perf] clouds {c_avg:.2f}/{c_p95:.2f} ms vs "
          f"{CLOUD_BUDGET_AVG_MS:.1f}/{CLOUD_BUDGET_P95_MS:.1f} budget; "
          f"frame {avg_total:.2f} vs {FRAME_BUDGET_MS:.1f} "
          f"-> {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--mist"]
    n = int(args[0]) if args else FRAMES
    raise SystemExit(run(n, mist="--mist" in sys.argv))
