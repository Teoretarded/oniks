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

from game.cameras import SPECTATE_MODE, SpectateSubject
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
        # SPECTATE: a fresh map click arms the contact id; closing the map
        # (M) resolves it to the live entity and swings the camera onto it.
        self._spectate_pending: str | None = None
        self._spectate_rects = None     # (left, right) arrow hit boxes

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

    # ------------------------------------------------------------- spectate

    @property
    def _spectate_active(self) -> bool:
        return (self.rig.mode == SPECTATE_MODE
                and isinstance(self.followed, SpectateSubject))

    def spectate_entity(self, entity, label: str) -> None:
        """Swing the camera onto ``entity`` in SPECTATE mode (the orbit
        controller on a live proxy subject; C leaves back into the classic
        mode cycle)."""
        self.followed = SpectateSubject(entity, label)
        if self.rig.mode != SPECTATE_MODE:
            self.rig.set_mode(SPECTATE_MODE)
        else:
            self.rig.retarget()          # subject swaps never snap
        # No hint flash: the plate IS the feedback, and the hint line draws
        # at bottom-center — exactly under the plate (ghost-text overlap,
        # caught on the first spectate render).

    def spectate_cycle(self, step: int) -> None:
        """LEFT/RIGHT (keys or the plate arrows): the next watchable thing.
        Entering from a non-spectate mode starts at the roster head."""
        roster = self.world.spectate_roster()
        if not roster:
            self.show_hint("SPECTATE: NOTHING TO WATCH")
            return
        current = (self.followed.entity if self._spectate_active else None)
        idx = next((i for i, r in enumerate(roster)
                    if r["entity"] is current), None)
        entry = (roster[(idx + step) % len(roster)] if idx is not None
                 else roster[0])
        self.spectate_entity(entry["entity"], entry["label"])
        self.app.audio.ui_click()

    def _spectate_watchdog(self) -> None:
        """A dead subject auto-advances to the next live one (or falls back
        to the launcher view when the roster ran dry)."""
        if not self._spectate_active or self.followed.alive:
            return
        if self.world.spectate_roster():
            self.spectate_cycle(+1)
        else:
            self.rig.set_mode("launcher")

    def _spectate_event(self, ev) -> bool:
        """3D-view input (map closed): arrow keys + the plate's arrow
        boxes cycle the roster."""
        if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_LEFT,
                                                    pygame.K_RIGHT):
            self.spectate_cycle(-1 if ev.key == pygame.K_LEFT else +1)
            return True
        if (ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1
                and self._spectate_rects is not None):
            for rect, step in zip(self._spectate_rects, (-1, +1)):
                x0, y0, x1, y1 = rect
                if x0 <= ev.pos[0] <= x1 and y0 <= ev.pos[1] <= y1:
                    self.spectate_cycle(step)
                    return True
        return False

    def _draw_spectate_plate(self, w: int, h: int) -> None:
        """Bottom-middle plate: '<  SPECTATE: <label>  >' with clickable
        arrow boxes (the user's asked-for chrome)."""
        from engine.text import SMALL_SIZE
        from game.states import ACCENT, PAPER_MUTED, TEXT_COL, draw_panel
        text = self.text
        label = self.followed.label
        body = f"SPECTATE: {label}"
        lh = text.line_height(SMALL_SIZE)
        bw = text.text_width(body, SMALL_SIZE)
        arrow_w = lh + 10
        pw = bw + arrow_w * 2 + 44
        ph = lh + 16
        px = (w - pw) * 0.5
        py = h - ph - 54                 # above the bottom hint line
        draw_panel(text, px, py, pw, ph)
        ay = py + 8
        text.draw_text(px + 12, ay, "<", ACCENT, SMALL_SIZE)
        text.draw_text(px + arrow_w + 22, ay, body, TEXT_COL, SMALL_SIZE)
        text.draw_text(px + pw - arrow_w + 4, ay, ">", ACCENT, SMALL_SIZE)
        text.draw_text(px + pw + 10, ay, "ARROWS CYCLE  C EXIT",
                       PAPER_MUTED, SMALL_SIZE)
        left = (px, py, px + arrow_w, py + ph)
        right = (px + pw - arrow_w, py, px + pw, py + ph)
        self._spectate_rects = (left, right)
        self.ui.add("hud.spectate_plate", px, py, pw, ph,
                    code="game/sandbox_war.py:_draw_spectate_plate")
        text.flush(w, h)

    # ---------------------------------------------------------------- events

    def handle_event(self, ev) -> None:
        if self._director_up and self._director_event(ev):
            return
        if (not self.map_open and self.forensics_open is False
                and self._end_overlay is None and self._bug_ui is None
                and self._spectate_event(ev)):
            return
        # SPECTATE map seam: a FRESH click on a contact this map session
        # arms it; the map closing (M key, M-close chip, any path) resolves
        # the id to the live entity and swings the camera.  A stale
        # selection from an earlier session never re-triggers.
        was_open = self.map_open
        sel_before = self.tactical_map.selected_contact
        super().handle_event(ev)
        if self.map_open and not self._director_up:
            sel_now = self.tactical_map.selected_contact
            if sel_now is not None and sel_now != sel_before:
                self._spectate_pending = sel_now
        if was_open and not self.map_open and self._spectate_pending:
            cid, self._spectate_pending = self._spectate_pending, None
            resolved = self.world.resolve_contact_entity(cid)
            if resolved is not None:
                self.spectate_entity(*resolved)

    def render(self, dt_real: float) -> None:
        self._spectate_watchdog()
        self._spectate_rects = None      # refreshed only while drawn
        super().render(dt_real)
        w, h = self.window.size()
        if self._director_up:
            draw_unit_markers(self, self.director, w, h)
            draw_director(self, self.director, w, h)
        if (self._spectate_active and not self.map_open
                and not self.forensics_open and self._end_overlay is None
                and self._bug_ui is None):
            self._draw_spectate_plate(w, h)
