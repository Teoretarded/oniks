"""ONIKS entry point: pygame init, GL window, state machine, fixed-timestep loop.

Run: python main.py    (ESC quits; avg FPS printed on exit)

The App loop below is THE loop — this exact structure stays for the whole
game: real time accumulates into fixed 120 Hz sim steps (scaled by
``time_scale``), capped at 64 steps/frame so an overloaded frame drops sim
time instead of spiraling; rendering runs once per frame with real dt.
"""

from __future__ import annotations

import time

import numpy as np
import pygame

from engine.camera import Camera
from engine.renderer import Renderer
from engine.window import Window
from game.cameras import FreeCam
from game.controls import FreeCamControls
from world.generation import BASE_POS
from world.ocean import Ocean
from world.sky import Sky
from world.terrain import Terrain

PHYS_DT = 1.0 / 120.0
START_ALT_ABOVE_BASE = 200.0


class WorldViewState:
    """Stub state: flyable sky/ocean/terrain world with a free camera.

    SandboxState (Task 18) replaces this, keeping the same interface:
    handle_event / sim_step / render.
    """

    def __init__(self, window, renderer):
        self.window = window
        self.renderer = renderer
        self.camera = Camera()
        self.sky = Sky()
        self.ocean = Ocean()
        self.terrain = Terrain()
        start = np.asarray(BASE_POS, dtype=np.float64) + (
            0.0, START_ALT_ABOVE_BASE, 0.0)
        # 200 m above the base, looking north over the ocean.
        self.freecam = FreeCam(start, yaw=0.0, pitch=0.0)
        self.controls = FreeCamControls(self.freecam)
        self.sim_time = 0.0

    def handle_event(self, ev) -> None:
        self.controls.handle_event(ev)

    def sim_step(self, dt: float) -> None:
        self.sim_time += dt

    def render(self, dt_real: float) -> None:
        self.controls.update(dt_real)        # camera flies in real time
        self.freecam.apply(self.camera)
        w, h = self.window.size()
        self.renderer.begin(self.camera, w / h)
        self.sky.draw(self.renderer)
        self.terrain.draw(self.renderer)
        self.ocean.draw(self.renderer, self.camera, self.sim_time)


class App:
    def __init__(self, hidden: bool = False, width: int = 1600,
                 height: int = 900):
        self.window = Window(width, height, hidden=hidden)
        self.renderer = Renderer()
        self.state = WorldViewState(self.window, self.renderer)
        self.time_scale = 1.0
        self.paused = False

    def run(self) -> None:
        clock = pygame.time.Clock()
        acc = 0.0
        frames = 0
        t0 = time.perf_counter()
        running = True
        while running:
            dt_real = min(clock.tick() / 1000.0, 0.1)
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT or (
                        ev.type == pygame.KEYDOWN
                        and ev.key == pygame.K_ESCAPE):
                    running = False
                elif ev.type == pygame.VIDEORESIZE:
                    self.window.handle_resize(ev.w, ev.h)
                else:
                    self.state.handle_event(ev)
            if not self.paused:
                acc += dt_real * self.time_scale
                steps = 0
                while acc >= PHYS_DT and steps < 64:
                    self.state.sim_step(PHYS_DT)
                    acc -= PHYS_DT
                    steps += 1
                if steps == 64:
                    acc = 0.0           # overload: drop time, never spiral
            self.state.render(dt_real)
            self.window.swap()
            frames += 1
        elapsed = time.perf_counter() - t0
        if frames and elapsed > 0.0:
            print(f"[main] {frames} frames in {elapsed:.1f} s - "
                  f"avg {frames / elapsed:.1f} FPS")
        pygame.quit()


if __name__ == "__main__":
    App().run()
