"""ONIKS entry point: pygame init, GL window, state machine, fixed-timestep loop.

Run: python main.py    (ESC quits; avg FPS printed on exit)

The App loop below is THE loop — this exact structure stays for the whole
game: real time accumulates into fixed 120 Hz sim steps (scaled by
``time_scale``), capped at 64 steps/frame so an overloaded frame drops sim
time instead of spiraling; rendering runs once per frame with real dt.

App flags driven by game/controls.py: ``paused`` (P), ``frame_step`` (N:
exactly one sim step while paused), ``screenshot_requested`` (F2, saved
after the frame renders). ``time_scale`` is re-read from the state each
frame (the sandbox forces 1x while a launch is in EJECT/BOOST).
"""

from __future__ import annotations

import os
import time

import pygame

from engine.renderer import Renderer
from engine.window import Window
from game.states import StateMachine

PHYS_DT = 1.0 / 120.0
SCREENSHOT_DIR = "renders"


class App:
    def __init__(self, hidden: bool = False, width: int = 1600,
                 height: int = 900):
        self.window = Window(width, height, hidden=hidden)
        self.renderer = Renderer()
        self.time_scale = 1.0
        self.paused = False
        self.frame_step = False             # N: one sim step while paused
        self.screenshot_requested = False   # F2: saved after render
        self.states = StateMachine()
        from game.sandbox import SandboxState   # after the GL context exists
        self.states.switch(SandboxState(self))

    @property
    def state(self):
        return self.states.current

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
                    running = False         # ESC: menu arrives with Task 21
                elif ev.type == pygame.VIDEORESIZE:
                    self.window.handle_resize(ev.w, ev.h)
                else:
                    self.state.handle_event(ev)
            self.time_scale = self.state.effective_time_scale()
            if not self.paused:
                acc += dt_real * self.time_scale
                steps = 0
                while acc >= PHYS_DT and steps < 64:
                    self.state.sim_step(PHYS_DT)
                    acc -= PHYS_DT
                    steps += 1
                if steps == 64:
                    acc = 0.0           # overload: drop time, never spiral
            elif self.frame_step:
                self.state.sim_step(PHYS_DT)
                self.frame_step = False
                acc = 0.0
            self.state.render(dt_real)
            if self.screenshot_requested:
                self.screenshot_requested = False
                print(f"[main] saved {self._save_screenshot()}")
            self.window.swap()
            frames += 1
        elapsed = time.perf_counter() - t0
        if frames and elapsed > 0.0:
            print(f"[main] {frames} frames in {elapsed:.1f} s - "
                  f"avg {frames / elapsed:.1f} FPS")
        pygame.quit()

    def _save_screenshot(self) -> str:
        """Save the just-rendered back buffer to renders/screenshot_NNN.png."""
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        i = 0
        while True:
            path = os.path.join(SCREENSHOT_DIR, f"screenshot_{i:03d}.png")
            if not os.path.exists(path):
                break
            i += 1
        pygame.image.save(self.window.read_pixels_to_surface(), path)
        return os.path.abspath(path)


if __name__ == "__main__":
    App().run()
