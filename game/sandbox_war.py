"""SandboxWarState: the WAR SANDBOX shell — the menu SANDBOX button.

CombatState with a SandboxWorld (docs/plans/sandbox_war_2026-07-06.md):
every combat mesh, platform, HUD pane, the forensics ledger (J), the
battery panel (O) and the black-box ledger come along by inheritance;
the world underneath swaps in the full passive toybox with the
all-seeing player picture and no defeat/victory latch (the end overlay
can therefore never open — ``_check_end_state`` reads the overridden
properties and stays inert forever).

The civilian lane traffic and patrol racetracks render through the SAME
inherited passes: ``_draw_ships`` routes by ``ship.ship_type`` through
the shared ``_ship_meshes`` dict (the base class builds the civilian
hull meshes, CombatState registers the destroyer/carrier), and
CombatState's ``_draw_aircraft`` calls the base pass first (the patrol
racetracks) before the drone / enemy-air additions.

The RED-FORCE DIRECTOR (I, map open): game/director.py owns the model +
panel; this state routes input to it ahead of the base chain, converts
the armed map click through the map view's screen_to_world, and draws
the panel + truth markers over the map.  Every director message flows
through show_hint — the combat shell's ledger denial channel — so
orders leave a black-box trail for free.

GL-touching module (subclasses game/combat.py) — never imported by unit
tests.
"""

from __future__ import annotations

import pygame

from game.combat import CombatState
from game.director import DirectorModel, draw_director, draw_unit_markers
from world.sandbox_world import SandboxWorld


class SandboxWarState(CombatState):
    """The SANDBOX session: full toybox, passive red force, no game-over."""

    def _build_world(self):
        """Always the war-sandbox world — there is no setup screen on this
        path (the toybox IS the config; world/sandbox_world.SANDBOX_CONFIG)."""
        return SandboxWorld()

    def __init__(self, app):
        # CombatState stashes _config before its __init__ builds the world;
        # None here means the ledger header + scorecard paths read the
        # world's own _config (SANDBOX_CONFIG) — the established fallback.
        super().__init__(app, config=None)
        self.director = DirectorModel(self.world)

    # ------------------------------------------------------------- director

    def toggle_director(self) -> None:
        """I (director binding): the panel lives ON the tactical map — the
        click-to-launch flow needs the map's world transform under it."""
        if not self.map_open:
            key = self.app.keybinds.name_for("map")
            self.show_hint(f"DIRECTOR: OPEN THE MAP ({key}) FIRST")
            return
        self.director.toggle()
        self.app.audio.ui_click()

    def _director_event(self, ev) -> bool:
        """Input routing while the panel is open (map underneath): keys
        drive the rows, an armed LMB launches at the clicked world point,
        every other LMB is eaten (the plan: normal click-to-target is
        suppressed under the panel).  MMB pan / RMB / wheel pass through
        so the operator can aim the map."""
        model = self.director
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_UP:
                model.move(-1)
                return True
            if ev.key == pygame.K_DOWN:
                model.move(+1)
                return True
            if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                msg = model.activate()
                if msg:
                    self.show_hint(msg)
                self.app.audio.ui_click()
                return True
            if ev.key == pygame.K_ESCAPE:
                if model.cancel():
                    self.app.audio.ui_click()
                    return True
                return False
            if self.app.keybinds.matches("director", ev.key):
                model.toggle()
                self.app.audio.ui_click()
                return True
            return False                    # other keys: base chain (M, F1…)
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            xz = self.tactical_map.view.screen_to_world(ev.pos)
            result = model.click((float(xz[0]), float(xz[1])))
            if result is not None:
                _ok, msg = result
                self.show_hint(msg)
                self.app.audio.ui_click()
            return True                     # LMB never falls through
        return False

    @property
    def _director_up(self) -> bool:
        """The panel is live: map open, no meta overlay on top of it."""
        return (self.director.open and self.map_open
                and not self.forensics_open
                and self._end_overlay is None
                and self._bug_ui is None)

    def handle_event(self, ev) -> None:
        if self._director_up and self._director_event(ev):
            return
        super().handle_event(ev)

    def render(self, dt_real: float) -> None:
        super().render(dt_real)
        if self._director_up:
            w, h = self.window.size()
            draw_unit_markers(self, self.director, w, h)
            draw_director(self, self.director, w, h)
