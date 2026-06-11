"""Frame-time benchmark: the worst-case scene at forced 8x time accel.

usage: python -m tools.perf_harness [frames]    (default 600)

Hidden 1600x900 window. Worst-case scene: camera 400 m over the base
looking north; ALL 14 ships alive (the two nearest moved into view and
set burning so deck fires emit); 4 missiles airborne — 2 hi cruise at
100/200 km downrange, 1 terminal at 8 km with a full trail ribbon, and
1 mid-boost at t = +2 s launched through the real launch path.

Each rendered frame advances the sim by 16 fixed 120 Hz substeps (time
scale 8 at a 60 FPS render rate) and draws the sandbox scene in its
exact render order with time.perf_counter timers around each section:
sim_step total, particles update+build(+draw), terrain/ocean draw,
models draw, HUD/map, swap. ``Effects.update`` (the particle sim) runs
inside ``sim_step``; the harness times it separately and reports it
under *particles*, subtracting it from the *sim_step* row so the rows
sum to the frame total (the leftover rig/sky/begin time is *other*).

Swap section: frames are paced like a real double/triple-buffered
swapchain — a GL fence is inserted after each frame's submission and
the swap section waits for the fence from two frames back before
presenting, so GPU back-pressure (a GPU running slower than the CPU)
shows up in *swap* exactly as it would in ``pygame.display.flip``.
The present itself is skipped when the OS throttles presentation of
this window (Windows/DWM limits hidden or occluded windows to ~3 Hz —
measured ~320 ms per SwapBuffers on this machine — which would swamp
the measurement with compositor wait time that is not app cost; the
fallback is detected by probing flip latency after warm-up and is
reported in the output).

Report: avg + p95 ms per section over 600 frames; exits 1 if the avg
frame total exceeds the 16.0 ms (60 FPS) budget.
"""

from __future__ import annotations

import sys
import time

import numpy as np
import pygame

from engine.particles import TRAIL_MAX_POINTS, TRAIL_POINT_SPACING
from main import PHYS_DT, App
from sim.arsenal import ONIKS
from sim.missile import PH_CRUISE, PH_TERMINAL, Missile
from sim.physics import speed_of_sound
from sim.ships import ST_BURNING
from world.generation import BASE_POS

FRAMES = 600                  # rendered frames measured
SUBSTEPS = 16                 # sim steps per frame: time_scale 8 @ 120/60 Hz
BUDGET_MS = 16.0              # avg frame budget (60 FPS)
CAM_ALT = 400.0               # m above the base
CAM_PITCH = -0.15             # slight down pitch: ocean + terrain + ships in view
WARMUP_FRAMES = 1200          # cap on terrain LOD streaming warm-up
SETUP_BOOST_S = 2.0           # sim time after launch -> missile mid-boost
FENCE_DEPTH = 2               # frames in flight before the swap wait (triple buffer)
THROTTLE_PROBE_FLIPS = 16     # probed flips: must outlast DWM's ~10-present grace
THROTTLE_LIMIT_S = 0.1        # a flip blocking this long = compositor-throttled

SECTIONS = ("sim_step", "particles", "terrain_ocean", "models",
            "hud_map", "swap", "other")


def _cruise_missile(world, z_north: float) -> Missile:
    """Hand-built hi-profile missile established in cruise at ``z_north``."""
    pos = np.array([0.0, ONIKS.cruise_alt_hi, z_north])
    m = Missile(ONIKS, pos, heading=0.0, profile="hi-lo",
                target_point=np.array([0.0, 0.0, 480_000.0]))
    m.phase = PH_CRUISE
    m.t = 120.0
    speed = ONIKS.cruise_mach_hi * float(speed_of_sound(pos[1]))
    m.vel = np.array([0.0, 0.0, speed])
    world.missiles.append(m)
    return m


def _terminal_missile(world) -> Missile:
    """Sea-skimming terminal missile 8 km out, no lock (open water ahead)."""
    pos = np.array([-20_000.0, ONIKS.skim_alt, 8_000.0])
    m = Missile(ONIKS, pos, heading=0.0, profile="lo-lo",
                target_point=np.array([-20_000.0, 0.0, 80_000.0]))
    m.phase = PH_TERMINAL
    m.t = 60.0
    speed = ONIKS.cruise_mach_lo * float(speed_of_sound(pos[1]))
    m.vel = np.array([0.0, 0.0, speed])
    world.missiles.append(m)
    return m


def _feed_full_trail(state, m) -> None:
    """Pre-feed the missile's ribbon to capacity along its past track."""
    trail = state.effects.add_trail()
    state._trails[id(m)] = trail
    spacing = TRAIL_POINT_SPACING + 1.0
    for i in range(TRAIL_MAX_POINTS, 0, -1):
        trail.add_point(m.pos - np.array([0.0, 0.0, i * spacing]))


def setup_scene(app: App):
    """Build the worst-case scene on a fresh sandbox; returns the state."""
    from game.sandbox import SandboxState
    app.states.switch(SandboxState(app))
    s = app.state
    s.hud_visible = True
    s.map_open = False

    # Camera: free cam 400 m over the base looking north.
    s.rig.set_mode("free")
    s.rig.freecam.pos = np.array([BASE_POS[0], BASE_POS[1] + CAM_ALT,
                                  BASE_POS[2]], dtype=np.float64)
    s.rig.freecam.yaw = 0.0
    s.rig.freecam.pitch = CAM_PITCH
    s.rig.update(0.0, None)

    # Two burning ships in view (within deck-fire emission range).
    for ship, (x, z) in zip(s.world.ships[:2],
                            ((1_500.0, 9_000.0), (-2_500.0, 14_000.0))):
        ship.pos[0], ship.pos[2] = x, z
        ship.state = ST_BURNING

    # Missiles: 2 hi cruise (100/200 km), 1 terminal (8 km, full trail).
    _cruise_missile(s.world, 100_000.0)
    _cruise_missile(s.world, 200_000.0)
    term = _terminal_missile(s.world)
    _feed_full_trail(s, term)

    # ... and 1 launched through the real path, simmed to mid-boost t=+2 s.
    boost = s.world.launch("hi-lo", np.array([0.0, 0.0, 250_000.0]))
    s.followed = boost
    for _ in range(int(round(SETUP_BOOST_S / PHYS_DT))):
        s.sim_step(PHYS_DT)
    return s


def render_frame(s, timers=None) -> None:
    """Draw one frame in SandboxState.render's exact order, timing sections
    into ``timers`` (dict) when given. Mirrors game/sandbox.py:render minus
    controls/audio (hidden batch window: silent, no input)."""
    mark = time.perf_counter
    w, h = s.window.size()
    t0 = mark()
    s.rig.update(1.0 / 60.0, s.followed)
    s.renderer.begin(s.camera, w / h)
    s.sky.draw(s.renderer)
    t1 = mark()
    s.terrain.draw(s.renderer)
    s.ocean.draw(s.renderer, s.camera, s.world.sim_time)
    t2 = mark()
    for mesh, pos in s._site_draws:
        s.renderer.draw_mesh(mesh, pos)
    s._draw_ships()
    s._draw_tel()
    s._draw_missiles()
    t3 = mark()
    s.particles.draw(s.renderer, s.effects)
    t4 = mark()
    if s.map_open:
        s.tactical_map.update(0.0)
        s.tactical_map.draw(w, h)
    elif s.hud_visible:
        s.hud.draw(s, w, h)
    t5 = mark()
    if timers is not None:
        timers["other"] += t1 - t0
        timers["terrain_ocean"] += t2 - t1
        timers["models"] += t3 - t2
        timers["particles"] += t4 - t3
        timers["hud_map"] += t5 - t4


class FencePacer:
    """Swapchain-style frame pacing with GL fence syncs.

    ``end_frame`` waits for the fence inserted FENCE_DEPTH frames ago
    (GPU back-pressure lands here, like a buffered flip) and presents.
    Windows/DWM throttles presents of hidden or occluded windows to
    ~3 Hz (measured ~320 ms per SwapBuffers on this machine; the block
    can surface on ANY later GL call, after a ~10-present grace window)
    — that is compositor wait, not app cost. ``probe_throttle`` runs
    enough flips before measurement to outlast the grace window and
    disables presents if any blocks; as a backstop, a mid-run flip that
    blocks past THROTTLE_LIMIT_S is excluded from that frame's swap
    time and ends presenting. The fence wait still captures real GPU
    back-pressure either way. ``throttled`` reports what happened.
    """

    def __init__(self, window):
        import OpenGL.GL as gl
        self._gl = gl
        self._window = window
        self._fences = []
        self.present = True
        self.throttled = False

    def probe_throttle(self) -> None:
        """Disable presents if the compositor throttles this window."""
        worst = 0.0
        for _ in range(THROTTLE_PROBE_FLIPS):
            t0 = time.perf_counter()
            self._window.swap()
            self._gl.glFinish()          # absorb a deferred present block
            worst = max(worst, time.perf_counter() - t0)
        if worst > THROTTLE_LIMIT_S:
            self.present = False
            self.throttled = True

    def end_frame(self) -> float:
        """Fence-wait + present; returns OS-throttle time to EXCLUDE."""
        gl = self._gl
        self._fences.append(
            gl.glFenceSync(gl.GL_SYNC_GPU_COMMANDS_COMPLETE, 0))
        if len(self._fences) > FENCE_DEPTH:
            fence = self._fences.pop(0)
            gl.glClientWaitSync(fence, gl.GL_SYNC_FLUSH_COMMANDS_BIT,
                                int(1e9))
            gl.glDeleteSync(fence)
        if not self.present:
            return 0.0
        t0 = time.perf_counter()
        self._window.swap()
        dt_flip = time.perf_counter() - t0
        if dt_flip <= THROTTLE_LIMIT_S:
            return 0.0
        self.present = False                 # OS-throttled: stop presenting
        self.throttled = True
        return dt_flip


def run(frames: int = FRAMES) -> int:
    app = App(hidden=True)
    s = setup_scene(app)

    # Time Effects.update (particle sim inside sim_step) separately.
    upd_acc = [0.0]
    effects_update = s.effects.update

    def timed_effects_update(dt):
        t0 = time.perf_counter()
        effects_update(dt)
        upd_acc[0] += time.perf_counter() - t0

    s.effects.update = timed_effects_update

    # Warm up: drain the terrain LOD build queue so streaming hitches do
    # not pollute the steady-state measurement (builds are budgeted and
    # transient; the camera never moves in this scene).
    for _ in range(WARMUP_FRAMES):
        render_frame(s)
        if not s.terrain._jobs:
            break

    pacer = FencePacer(s.window)
    pacer.probe_throttle()

    from OpenGL.GL import GL_RENDERER, glGetString
    renderer_name = glGetString(GL_RENDERER)
    if renderer_name:
        print(f"[perf] GL_RENDERER: {renderer_name.decode()}")

    per_frame = {name: np.empty(frames) for name in SECTIONS}
    totals = np.empty(frames)
    mark = time.perf_counter
    for f in range(frames):
        pygame.event.pump()
        timers = dict.fromkeys(SECTIONS, 0.0)
        upd_acc[0] = 0.0
        t0 = mark()
        for _ in range(SUBSTEPS):
            s.sim_step(PHYS_DT)
        t1 = mark()
        timers["sim_step"] = (t1 - t0) - upd_acc[0]
        timers["particles"] += upd_acc[0]
        render_frame(s, timers)
        t2 = mark()
        excluded = pacer.end_frame()
        timers["swap"] = mark() - t2 - excluded
        for name in SECTIONS:
            per_frame[name][f] = timers[name]
        totals[f] = mark() - t0 - excluded

    pygame.quit()
    if pacer.throttled:
        print("[perf] NOTE: OS throttles presents of this hidden window "
              "(Windows/DWM limits occluded windows to ~3 Hz); presents "
              "were dropped - swap times are fence-paced GPU completion, "
              "which is what flip waits on in an interactive session")
    return report(per_frame, totals, frames)


def report(per_frame, totals, frames: int) -> int:
    ms = 1e3
    print(f"\n[perf] worst-case scene, {frames} frames x {SUBSTEPS} "
          f"substeps (time_scale 8 @ 60 FPS render)")
    print(f"{'section':<14}{'avg ms':>9}{'p95 ms':>9}")
    for name in SECTIONS:
        t = per_frame[name]
        print(f"{name:<14}{t.mean() * ms:>9.2f}"
              f"{np.percentile(t, 95) * ms:>9.2f}")
    avg = totals.mean() * ms
    p95 = np.percentile(totals, 95) * ms
    print(f"{'TOTAL':<14}{avg:>9.2f}{p95:>9.2f}")
    ok = avg <= BUDGET_MS
    print(f"[perf] avg total {avg:.2f} ms vs budget {BUDGET_MS:.1f} ms "
          f"-> {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else FRAMES
    raise SystemExit(run(n))
