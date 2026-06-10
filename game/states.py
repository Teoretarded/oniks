"""GameState base + state machine + MenuState (Task 21).

States receive the App (window, renderer, paused/frame_step flags) and
implement the three loop callbacks dispatched by main.App.run:
``handle_event`` / ``sim_step`` / ``render``.

The menu logic helpers (``menu_items`` / ``move_selection``) are pure and
unit-tested headless; MenuState defers its OpenGL import to ``enter`` so
this module stays importable without a GL context (LOCKED test convention).
"""

from __future__ import annotations

import pygame

from engine.text import BODY_SIZE, HEADER_SIZE

# --- Menu tuning ----------------------------------------------------------------

MENU_BG = (0.012, 0.018, 0.028)     # near-black navy clear color
TITLE_TEXT = "ONIKS"
TITLE_SCALE = 3.0                   # 28 pt header glyphs x3 via quad scale
SUBTITLE_TEXT = "P-800 coastal strike sandbox"
ITEM_RESUME, ITEM_SANDBOX, ITEM_QUIT = "RESUME", "SANDBOX", "QUIT"

TITLE_Y_FRAC = 0.24                 # title top edge, fraction of screen height
SUBTITLE_GAP = 10                   # px between title baseline and subtitle
ITEMS_Y_FRAC = 0.55                 # first item top edge
ITEM_SPACING = 52                   # px between item tops
ITEM_PAD_X = 34                     # hover/click hit-box padding around items
ITEM_PAD_Y = 8
MARKER_GAP = 22                     # px between the '>' marker and the item

TITLE_COL = (0.95, 0.85, 0.45, 1.0)         # HUD header gold
SUBTITLE_COL = (0.62, 0.74, 0.66, 1.0)
ITEM_COL = (0.80, 0.86, 0.80, 0.92)
SELECT_COL = (0.45, 1.00, 0.55, 1.0)        # status green
HINT_COL = (0.55, 0.62, 0.56, 0.85)
HINT_TEXT = "ARROWS/MOUSE select   ENTER confirm   ESC back"
HINT_MARGIN = 14                    # px from the bottom edge


def menu_items(has_sandbox: bool) -> list[str]:
    """RESUME appears (first, pre-selected) once a sandbox session exists."""
    return ([ITEM_RESUME] if has_sandbox else []) + [ITEM_SANDBOX, ITEM_QUIT]


def move_selection(idx: int, delta: int, count: int) -> int:
    """Step the selected index with wrap-around (empty list stays at 0)."""
    return (idx + delta) % count if count else 0


class GameState:
    """Base state: no-op callbacks + enter/leave hooks for the machine."""

    def __init__(self, app):
        self.app = app

    def enter(self) -> None:
        pass

    def leave(self) -> None:
        pass

    def handle_event(self, ev) -> None:
        pass

    def sim_step(self, dt: float) -> None:
        pass

    def render(self, dt_real: float) -> None:
        pass

    def effective_time_scale(self) -> float:
        """Sim seconds per real second this frame (states may clamp it)."""
        return 1.0


class StateMachine:
    """Holds the active state; ``switch`` runs the leave/enter hooks."""

    def __init__(self):
        self.current: GameState | None = None

    def switch(self, state: GameState | None) -> None:
        if self.current is not None:
            self.current.leave()
        self.current = state
        if state is not None:
            state.enter()


class MenuState(GameState):
    """Title screen / pause menu: SANDBOX / QUIT (+ RESUME once a game runs).

    Navigable by mouse (hover selects, LMB activates) and arrows + ENTER.
    The sandbox sim is frozen while the menu is up (state switch + time
    scale 0). GL-touching only from ``enter`` on (context exists by then).
    """

    def __init__(self, app):
        super().__init__(app)
        self._gl = None
        self.text = None                    # TextRenderer, built on first enter
        self.items = menu_items(False)
        self.sel = 0
        self._rects: list = []              # per-item hit boxes, set by render

    def enter(self) -> None:
        pygame.event.set_grab(False)        # in case a mouse-look drag was live
        pygame.mouse.set_visible(True)
        if self.text is None:
            import OpenGL.GL as gl

            from engine.text import TextRenderer
            self._gl = gl
            self.text = TextRenderer()
        self.items = menu_items(self.app.sandbox is not None)
        self.sel = 0                        # RESUME (when present) pre-selected
        self._rects = []

    def effective_time_scale(self) -> float:
        return 0.0                          # menu up: no sim time accumulates

    # ----------------------------------------------------------------- input

    def handle_event(self, ev) -> None:
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_UP:
                self._move(-1)
            elif ev.key == pygame.K_DOWN:
                self._move(1)
            elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._activate(self.items[self.sel])
            elif ev.key == pygame.K_ESCAPE:
                if self.app.sandbox is not None:
                    self._activate(ITEM_RESUME)
                else:
                    self.app.running = False
        elif ev.type == pygame.MOUSEMOTION:
            hit = self._hit(ev.pos)
            if hit is not None:
                self.sel = hit
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            hit = self._hit(ev.pos)
            if hit is not None:
                self.sel = hit
                self._activate(self.items[hit])

    def _move(self, delta: int) -> None:
        self.sel = move_selection(self.sel, delta, len(self.items))
        self.app.audio.ui_click()

    def _hit(self, pos):
        for i, (x0, y0, x1, y1) in enumerate(self._rects):
            if x0 <= pos[0] <= x1 and y0 <= pos[1] <= y1:
                return i
        return None

    def _activate(self, name: str) -> None:
        self.app.audio.ui_click()
        if name == ITEM_QUIT:
            self.app.running = False
        elif name == ITEM_RESUME and self.app.sandbox is not None:
            self.app.states.switch(self.app.sandbox)
        elif name == ITEM_SANDBOX:
            self.app.start_sandbox()        # fresh world (RESUME continues)

    # ----------------------------------------------------------------- render

    def render(self, dt_real: float) -> None:
        gl = self._gl
        gl.glClearColor(MENU_BG[0], MENU_BG[1], MENU_BG[2], 1.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        w, h = self.app.window.size()
        text = self.text

        tw = text.text_width(TITLE_TEXT, HEADER_SIZE) * TITLE_SCALE
        ty = h * TITLE_Y_FRAC
        text.draw_text((w - tw) * 0.5, ty, TITLE_TEXT, TITLE_COL,
                       HEADER_SIZE, scale=TITLE_SCALE)
        sy = ty + text.line_height(HEADER_SIZE) * TITLE_SCALE + SUBTITLE_GAP
        sw = text.text_width(SUBTITLE_TEXT, BODY_SIZE)
        text.draw_text((w - sw) * 0.5, sy, SUBTITLE_TEXT, SUBTITLE_COL)

        self._rects = []
        line_h = text.line_height(HEADER_SIZE)
        for i, name in enumerate(self.items):
            iw = text.text_width(name, HEADER_SIZE)
            x = (w - iw) * 0.5
            y = h * ITEMS_Y_FRAC + i * ITEM_SPACING
            selected = i == self.sel
            col = SELECT_COL if selected else ITEM_COL
            text.draw_text(x, y, name, col, HEADER_SIZE)
            if selected:
                text.draw_text(x - text.text_width(">", HEADER_SIZE)
                               - MARKER_GAP, y, ">", col, HEADER_SIZE)
                text.draw_text(x + iw + MARKER_GAP, y, "<", col, HEADER_SIZE)
            self._rects.append((x - ITEM_PAD_X, y - ITEM_PAD_Y,
                                x + iw + ITEM_PAD_X, y + line_h + ITEM_PAD_Y))

        hw = text.text_width(HINT_TEXT, BODY_SIZE)
        text.draw_text((w - hw) * 0.5,
                       h - text.line_height(BODY_SIZE) - HINT_MARGIN,
                       HINT_TEXT, HINT_COL)
        text.flush(w, h)
