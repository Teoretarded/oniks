"""F3-P3 cloud perf gate — built BEFORE the cloud shader (the gate exists
on day one; the baseline row is the evidence the shader's cost is judged
against).

usage: python -m tools.perf_clouds [frames]     (default 600)

Reuses tools/perf_harness.py's worst-case scene and FencePacer, with the
camera pitched AT THE HORIZON (the worst cloud-march geometry: maximum
slab traversal per ray) and a dedicated ``clouds`` timer section around
``state.clouds.draw`` (zero until world/clouds.py lands — the pre-cloud
run IS the baseline).

Budgets: V2 is quality-tiered (High 1.0/1.5 ms avg/p95); legacy retains the
older 3.0/5.0 ms gate. One sim substep gates a 6.94 ms / 144 FPS frame;
the historical eight-substep stress case retains 16 ms. Exit 1 on a miss.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
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
FRAME_144_BUDGET_MS = 1000.0 / 144.0
V2_BUDGETS_MS = {
    "low": (0.4, 0.7), "med": (0.7, 1.0),
    "high": (1.0, 1.5), "ultra": (1.5, 2.25),
}
HORIZON_PITCH = -0.02          # worst case: rays graze the whole slab

SECTIONS = ("sim_step", "scene", "clouds", "hud", "swap", "other")
GPU_QUERY_DELAY_FRAMES = 4
GPU_QUERY_POOL_SIZE = 16
MIN_CLOUD_WARMUP = 32


def _query_scalar(value) -> int:
    """Normalize PyOpenGL scalar/one-element-array return values."""
    return int(np.asarray(value).reshape(-1)[0])


class CloudGpuTimer:
    """Delayed ``GL_TIME_ELAPSED`` query pool.

    Same-frame query reads serialize the CPU and GPU and contaminate the
    whole-frame number. Results here are read only after several frames and
    only when OpenGL reports them available.
    """

    def __init__(self, pool_size: int = GPU_QUERY_POOL_SIZE):
        from OpenGL.GL import glGenQueries
        queries = np.atleast_1d(glGenQueries(int(pool_size))).reshape(-1)
        self._queries = [int(q) for q in queries]
        self._free = list(self._queries)
        self._pending = {}
        self._active = None

    def _grow(self) -> int:
        # Never stall a measured frame waiting for a query slot.
        from OpenGL.GL import glGenQueries
        q = _query_scalar(glGenQueries(1))
        self._queries.append(q)
        return q

    def begin(self, frame: int) -> None:
        from OpenGL.GL import GL_TIME_ELAPSED, glBeginQuery
        if self._active is not None:
            raise RuntimeError("cloud GPU timer query already active")
        q = self._free.pop() if self._free else self._grow()
        glBeginQuery(GL_TIME_ELAPSED, q)
        self._active = (q, int(frame))

    def end(self) -> None:
        from OpenGL.GL import GL_TIME_ELAPSED, glEndQuery
        if self._active is None:
            raise RuntimeError("cloud GPU timer query is not active")
        glEndQuery(GL_TIME_ELAPSED)
        q, frame = self._active
        self._pending[q] = frame
        self._active = None

    def collect_available(self, current_frame: int, force: bool = False):
        from OpenGL.GL import (GL_QUERY_RESULT, GL_QUERY_RESULT_AVAILABLE,
                               glGetQueryObjectuiv)
        ready = []
        for q, frame in list(self._pending.items()):
            if not force and current_frame - frame < GPU_QUERY_DELAY_FRAMES:
                continue
            available = _query_scalar(
                glGetQueryObjectuiv(q, GL_QUERY_RESULT_AVAILABLE))
            if not available and not force:
                continue
            # PyOpenGL's uint64 converter is broken on some Windows/NVIDIA
            # installs. A uint32 nanosecond result still spans 4.29 seconds,
            # orders of magnitude above this per-pass query.
            gpu_ns = _query_scalar(glGetQueryObjectuiv(q, GL_QUERY_RESULT))
            ready.append((frame, gpu_ns * 1e-9))
            del self._pending[q]
            self._free.append(q)
        return ready

    def finish(self, current_frame: int):
        """Drain after measurement; this wait is outside all timed frames."""
        from OpenGL.GL import glFinish
        glFinish()
        return self.collect_available(current_frame, force=True)

    def delete(self) -> None:
        from OpenGL.GL import GL_TIME_ELAPSED, glDeleteQueries, glEndQuery
        if self._active is not None:
            try:
                glEndQuery(GL_TIME_ELAPSED)
            except Exception:
                pass
            self._active = None
        if self._queries:
            glDeleteQueries(len(self._queries), self._queries)
        self._queries = []
        self._free = []
        self._pending = {}


def render_frame(s, timers=None, gpu_timer=None, frame_index=None):
    """Draw in ``SandboxState`` production order.

    The ``clouds`` section is delayed GPU time via GL_TIME_ELAPSED. CPU
    submission time remains in ``other`` and fence-paced GPU back-pressure
    remains in ``swap``.
    """
    mark = time.perf_counter
    w, h = s.window.size()
    t0 = mark()
    s._cloud_time = float(getattr(s, "_cloud_time", 0.0)) + (1.0 / 60.0)
    s.rig.update(1.0 / 60.0, s.followed)
    s.renderer.begin(s.camera, w / h)
    s._bind_cloud_shadows()
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
    t2 = mark()
    clouds = getattr(s, "clouds", None)
    if clouds is not None and clouds.enabled:
        if gpu_timer is not None:
            gpu_timer.begin(frame_index)
        clouds.draw(s.renderer, s.camera, s._cloud_time)
        if gpu_timer is not None:
            gpu_timer.end()
    t3 = mark()
    # Production draws particles after clouds so exhaust remains visible.
    s.particles.draw(s.renderer, s.effects)
    t4 = mark()
    if s.map_open:
        s.tactical_map.update(0.0)
        s.tactical_map.draw(w, h)
    elif s.hud_visible:
        s.hud.draw(s, w, h)
    t5 = mark()
    if timers is not None:
        # The delayed GPU result fills ``clouds`` in run().
        timers["other"] += (t1 - t0) + (t3 - t2)
        timers["scene"] += (t2 - t1) + (t4 - t3)
        timers["hud"] += t5 - t4


def run(frames: int = FRAMES, mist: bool = False,
        renderer: str = "legacy", quality: str = "high",
        substeps: int = SUBSTEPS, recipe=None) -> int:
    os.environ["ONIKS_CLOUD_RENDERER"] = renderer
    os.environ["ONIKS_CLOUD_QUALITY"] = quality
    if recipe is not None:
        os.environ["ONIKS_CLOUD_WEATHER"] = "custom"
    else:
        # Keep the baseline reproducible regardless of a player's saved
        # Graphics weather override. Severe recipes are requested explicitly.
        os.environ["ONIKS_CLOUD_WEATHER"] = "battle"
    app = App(hidden=True)
    recipe_digest = None
    recipe_spec = None
    if recipe is not None:
        from tools.probe_weather_composer import load_recipe
        from game.weather_composer import (compose_custom_weather,
                                            custom_recipe_digest)
        selection = load_recipe(Path(recipe))
        app.ui_prefs.values.update(selection)
        app.ui_prefs.values["cloud_weather_override"] = "custom"
        recipe_digest = custom_recipe_digest(selection)
        recipe_spec = compose_custom_weather(selection)
    s = setup_scene(app)
    s.rig.freecam.pitch = HORIZON_PITCH     # stare through the slab
    if mist:
        # v6 gate: the playtest FPS collapse happened INSIDE the layer —
        # every pixel marches thin cloud with no early-out. Park the camera
        # in the fair-cu band staring down its length.
        s.rig.freecam.pos = np.array([0.0, 1_400.0, 40_000.0])
        s.rig.freecam.pitch = 0.02
    elif recipe_spec is not None and recipe_spec.supercells.enabled:
        from tools.probe_cloud_flight import find_cluster_v2
        cluster = find_cluster_v2(7, recipe_spec)
        pos = np.asarray(cluster["outside"], dtype=np.float64)
        pos[1] = 7_800.0
        target = np.asarray(cluster["center"], dtype=np.float64)
        delta = target - pos
        s.rig.freecam.pos = pos
        s.rig.freecam.yaw = float(np.arctan2(delta[0], delta[2]))
        s.rig.freecam.pitch = float(np.arcsin(np.clip(
            delta[1] / max(float(np.linalg.norm(delta)), 1e-6), -1, 1)))
    s.rig.update(0.0, None)

    for warmup in range(WARMUP_FRAMES):
        render_frame(s)
        if warmup + 1 >= MIN_CLOUD_WARMUP and not s.terrain._jobs:
            break

    pacer = FencePacer(s.window)
    pacer.probe_throttle()

    from OpenGL.GL import GL_RENDERER, glGetString
    name = glGetString(GL_RENDERER)
    if name:
        print(f"[perf] GL_RENDERER: {name.decode()}")
    has_clouds = getattr(s, "clouds", None) is not None
    clouds_obj = getattr(s, "clouds", None)
    actual_backend = getattr(clouds_obj, "backend_name", "off")
    actual_v2 = bool(getattr(clouds_obj, "using_v2", False))
    print(f"[perf] clouds pass present: {has_clouds}"
          + ("" if has_clouds else "  (BASELINE run)"))
    print(f"[perf] requested/actual backend: {renderer}/{actual_backend}")
    if recipe_digest is not None:
        print(f"[perf] custom weather recipe: {recipe_digest}")
    if renderer == "v2" and quality != "off" and not actual_v2:
        s.dispose()
        pygame.quit()
        raise RuntimeError("requested V2 benchmark entered legacy fallback")

    per = {k: np.empty(frames) for k in SECTIONS}
    per["clouds"].fill(0.0)
    totals = np.empty(frames)
    gpu_timer = CloudGpuTimer()
    timed_cloud_frames = set()
    measured_cloud_frames = set()
    mark = time.perf_counter
    try:
        for f in range(frames):
            pygame.event.pump()
            timers = dict.fromkeys(SECTIONS, 0.0)
            t0 = mark()
            for _ in range(substeps):
                s.sim_step(PHYS_DT)
            timers["sim_step"] = mark() - t0
            clouds = getattr(s, "clouds", None)
            if clouds is not None and clouds.enabled:
                timed_cloud_frames.add(f)
            render_frame(s, timers, gpu_timer=gpu_timer, frame_index=f)
            t2 = mark()
            excluded = pacer.end_frame()
            timers["swap"] = mark() - t2 - excluded
            for measured_frame, gpu_s in gpu_timer.collect_available(f):
                per["clouds"][measured_frame] = gpu_s
                measured_cloud_frames.add(measured_frame)
            for k in SECTIONS:
                if k != "clouds":
                    per[k][f] = timers[k]
            totals[f] = mark() - t0 - excluded

        for measured_frame, gpu_s in gpu_timer.finish(frames):
            per["clouds"][measured_frame] = gpu_s
            measured_cloud_frames.add(measured_frame)
        missing = timed_cloud_frames.difference(measured_cloud_frames)
        if missing:
            raise RuntimeError(
                f"missing cloud GPU query results: {sorted(missing)}")
    finally:
        gpu_timer.delete()
        s.dispose()
        pygame.quit()
    if pacer.throttled:
        print("[perf] NOTE: hidden-window presents OS-throttled; swap = "
              "fence-paced GPU completion (see perf_harness)")

    ms = 1e3
    print(f"\n[perf] cloud gate scene, {frames} frames x {substeps} substeps")
    print(f"{'section':<10}{'avg ms':>9}{'p95 ms':>9}")
    for k in SECTIONS:
        print(f"{k:<10}{per[k].mean() * ms:>9.2f}"
              f"{np.percentile(per[k], 95) * ms:>9.2f}")
    avg_total = totals.mean() * ms
    print(f"{'TOTAL':<10}{avg_total:>9.2f}"
          f"{np.percentile(totals, 95) * ms:>9.2f}")

    c_avg = per["clouds"].mean() * ms
    c_p95 = np.percentile(per["clouds"], 95) * ms
    if quality == "off":
        cloud_avg_budget = cloud_p95_budget = 0.05
    elif actual_v2:
        cloud_avg_budget, cloud_p95_budget = V2_BUDGETS_MS[quality]
    else:
        cloud_avg_budget, cloud_p95_budget = (CLOUD_BUDGET_AVG_MS,
                                               CLOUD_BUDGET_P95_MS)
    frame_budget = FRAME_144_BUDGET_MS if substeps == 1 else FRAME_BUDGET_MS
    ok = (c_avg <= cloud_avg_budget and c_p95 <= cloud_p95_budget
          and avg_total <= frame_budget)
    print(f"[perf] clouds {c_avg:.2f}/{c_p95:.2f} ms vs "
          f"{cloud_avg_budget:.1f}/{cloud_p95_budget:.1f} budget; "
          f"frame {avg_total:.2f} vs {frame_budget:.2f} "
          f"-> {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Cloud rendering performance gate.")
    parser.add_argument("frames", nargs="?", type=int, default=FRAMES,
                        help=f"measured frame count (default: {FRAMES})")
    parser.add_argument("--mist", action="store_true",
                        help="benchmark from inside the cloud layer")
    parser.add_argument("--renderer", choices=("legacy", "v2"),
                        default="legacy")
    parser.add_argument("--quality", choices=("off", "low", "med", "high",
                                               "ultra"), default="high")
    parser.add_argument("--substeps", type=int, choices=range(1, SUBSTEPS + 1),
                        default=SUBSTEPS,
                        help="simulation steps per rendered frame; 1 gates 144 FPS")
    parser.add_argument("--recipe", type=Path,
                        help="Weather Composer JSON recipe")
    args = parser.parse_args(argv)
    if args.frames <= 0:
        parser.error("frames must be > 0")
    return args


if __name__ == "__main__":
    args = parse_args(sys.argv[1:])
    raise SystemExit(run(args.frames, mist=args.mist,
                         renderer=args.renderer, quality=args.quality,
                         substeps=args.substeps, recipe=args.recipe))
