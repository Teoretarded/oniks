"""ONIKS entry point: pygame init, GL window, state machine, fixed-timestep loop.

Run: python main.py    (starts at the menu; avg FPS printed on exit)

The App loop below is THE loop — this exact structure stays for the whole
game: real time accumulates into fixed 120 Hz sim steps (scaled by
``time_scale``), capped at 64 steps/frame so an overloaded frame drops sim
time instead of spiraling; rendering runs once per frame with real dt.

App flags driven by game/controls.py: ``paused`` (P), ``frame_step`` (N:
exactly one sim step while paused), ``screenshot_requested`` (F2, saved
after the frame renders). ``time_scale`` is re-read from the state each
frame (the sandbox forces 1x while a launch is in EJECT/BOOST; the menu
returns 0 so no sim time accumulates while it is up).

State flow (Task 21): App starts at MenuState; SANDBOX starts a fresh
world, ESC in the sandbox returns to the menu (sim frozen, RESUME appears),
QUIT or window close ends ``run`` via ``app.running``.
"""

from __future__ import annotations

import os
import time

import pygame

from game.audio import AudioManager

# Mixer settings must be staged before Window's pygame.init() (plan-fixed).
AudioManager.pre_init()

from engine.renderer import Renderer            # noqa: E402
from engine.window import Window                # noqa: E402
from game.states import MenuState, StateMachine  # noqa: E402

PHYS_DT = 1.0 / 120.0
SCREENSHOT_DIR = "renders"


class App:
    def __init__(self, hidden: bool = False, width: int = 1600,
                 height: int = 900):
        self.window = Window(width, height, hidden=hidden)
        self.renderer = Renderer()
        # Hidden windows are batch tools (screenshot/perf harness): silent.
        self.audio = AudioManager(enabled=not hidden)
        self.time_scale = 1.0
        self.paused = False
        self.frame_step = False             # N: one sim step while paused
        self.screenshot_requested = False   # F2: saved after render
        self.running = True                 # cleared by QUIT / menu QUIT
        self.states = StateMachine()
        self.sandbox = None                 # live game session (RESUME target)
        self.menu = MenuState(self)
        self.states.switch(self.menu)

    @property
    def state(self):
        return self.states.current

    # ------------------------------------------------------- state switching

    def start_sandbox(self) -> None:
        """Menu SANDBOX item: start a fresh game session."""
        from game.sandbox import SandboxState   # after the GL context exists
        if self.sandbox is not None:
            self.sandbox.dispose()          # free the replaced session's GL
        self.paused = False
        self.sandbox = SandboxState(self)
        self.states.switch(self.sandbox)

    def open_menu(self) -> None:
        """ESC in the sandbox: back to the menu (sandbox kept for RESUME)."""
        self.states.switch(self.menu)

    def run(self) -> None:
        clock = pygame.time.Clock()
        acc = 0.0
        frames = 0
        t0 = time.perf_counter()
        while self.running:
            dt_real = min(clock.tick() / 1000.0, 0.1)
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    self.running = False
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
