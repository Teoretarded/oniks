"""ONIKS entry point: pygame init, GL window, state machine, fixed-timestep loop.

Run: python main.py    (starts at the menu; avg FPS printed on exit)

The App loop below is THE loop — this exact structure stays for the whole
game: real time accumulates into fixed 120 Hz sim steps (scaled by
``time_scale``), capped at 64 steps/frame so an overloaded frame drops sim
time instead of spiraling; rendering runs once per frame with real dt.

App flags driven by game/controls.py: ``paused`` (P), ``frame_step`` (N:
exactly one sim step while paused), ``screenshot_requested`` (F2, saved
after the frame renders). ``time_scale`` is re-read from the state each
frame (the sandbox forces 1x through the launch cinematic; the menu
returns 0 so no sim time accumulates while it is up).

State flow (Task 21, reshaped by Task UI): App starts at MenuState
(SANDBOX / SETTINGS / QUIT); ESC in the sandbox opens PauseState over the
frozen frame (RESUME / SETTINGS / MAIN MENU — the latter discards the
session after a confirm), SETTINGS opens from either menu and returns to
whoever opened it. The rebindable action->key table (game/keybinds.py)
loads at startup and persists to %APPDATA%\\ONIKS\\settings.json.
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
from game.keybinds import Keybinds              # noqa: E402
from game.states import (MenuState, PauseState, SettingsState,  # noqa: E402
                         StateMachine)

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
        self.keybinds = Keybinds()          # persisted action->key table
        self.states = StateMachine()
        self.sandbox = None                 # live game session (RESUME target)
        self.campaign = None                # CampaignState (lazily loaded)
        self.campaign_battle = False        # True while playing a campaign battle
        self.menu = MenuState(self)
        self.pause_menu = PauseState(self)
        self.settings = SettingsState(self)
        self._ui_text = None                # TextRenderer shared by menus
        self.states.switch(self.menu)

    @property
    def state(self):
        return self.states.current

    def ui_text(self):
        """The menu screens' shared TextRenderer (GL exists by enter())."""
        if self._ui_text is None:
            from engine.text import TextRenderer
            self._ui_text = TextRenderer()
        return self._ui_text

    # ------------------------------------------------------- state switching

    def start_sandbox(self) -> None:
        """Menu SANDBOX item: start a fresh game session."""
        from game.sandbox import SandboxState   # after the GL context exists
        self._draw_loading_frame()          # world build takes ~2 s: show it
        if self.sandbox is not None:
            self.sandbox.dispose()          # free the replaced session's GL
        self.paused = False
        self.sandbox = SandboxState(self)
        self.states.switch(self.sandbox)

    def open_combat_setup(self) -> None:
        """Menu COMBAT item: the two-page setup screen (World/Armory) before
        the battle.  START there calls ``start_combat(config)``; ESC returns
        to the main menu.  A fresh CombatSetupState each time so a re-entry
        starts on the World page with the default selection."""
        from game.combat_setup import CombatSetupState  # GL deferred to enter
        setup = CombatSetupState(self, self.start_combat)
        self._combat_setup = setup        # held so it is not GC'd mid-session
        self.states.switch(setup)

    def start_combat(self, config=None) -> None:
        """Start a fresh fog-of-war combat session from a CombatConfig.

        ``config`` None keeps the screen-less path working (smoke tools and
        tests that call ``start_combat()`` bare, plus the REMATCH callback
        passing the just-played config): the CombatState falls back to the
        default config, so behaviour is unchanged for existing callers.
        Reuses the ``sandbox`` slot so pause/resume/quit flows apply."""
        from game.combat import CombatState     # after the GL context exists
        self._draw_loading_frame()
        if self.sandbox is not None:
            self.sandbox.dispose()
        self.paused = False
        self.campaign_battle = False        # a plain battle, unless the
        self.sandbox = CombatState(self, config=config)   # campaign path
        self.states.switch(self.sandbox)                  # re-flags below

    def open_campaign(self) -> None:
        """Menu CAMPAIGN item: the between-battles hub (fresh / in-progress /
        complete — game/campaign_screen.py decides from the save)."""
        from game.campaign_screen import CampaignHubState
        hub = CampaignHubState(self)
        self._campaign_hub = hub          # held so it is not GC'd mid-session
        self.states.switch(hub)

    def start_campaign_battle(self) -> None:
        """Hub START: build the campaign's CURRENT battle (escalated, derived
        seed via game/campaign.next_config) and ingest the carried ammo ledger
        (initial_state_for; None on battle 0 = the byte-identical fresh
        path)."""
        import game.campaign as campaign
        camp = self.campaign
        if camp is None or camp.complete:
            return
        cfg = campaign.next_config(camp)
        st = campaign.initial_state_for(camp)
        self.start_combat(cfg)
        if st:
            self.sandbox.world.apply_initial_state(st)
        self.campaign_battle = True

    def _draw_loading_frame(self) -> None:
        """One immediate 'BUILDING WORLD...' frame so the SANDBOX click never
        reads as a hang while terrain/models/audio construct (~2 s)."""
        from OpenGL import GL as gl
        from engine.text import HEADER_SIZE
        from game.states import ACCENT, BG0
        gl.glClearColor(BG0[0], BG0[1], BG0[2], 1.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        text = self.ui_text()
        w, h = self.window.size()
        msg = "BUILDING WORLD..."
        tw = text.text_width(msg, HEADER_SIZE)
        text.draw_text((w - tw) * 0.5, (h - 28) * 0.5, msg, ACCENT, HEADER_SIZE)
        text.flush(w, h)
        self.window.swap()

    def open_pause(self) -> None:
        """ESC in the sandbox: pause menu over the frozen frame."""
        self.states.switch(self.pause_menu)

    def resume(self) -> None:
        """Pause RESUME / ESC: back into the running session."""
        self.states.switch(self.sandbox)

    def open_settings(self, back_to) -> None:
        """SETTINGS item (main menu or pause): ESC/BACK returns to opener."""
        self.settings.back_to = back_to
        self.states.switch(self.settings)

    def quit_to_menu(self) -> None:
        """Pause MAIN MENU (confirmed): discard the session, title screen."""
        if self.sandbox is not None:
            self.sandbox.dispose()
            self.sandbox = None
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
