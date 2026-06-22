"""CombatEndOverlay: VICTORY / DEFEAT banner over the frozen final frame (Phase 7).

Rendered exactly like PauseState: the last combat frame is already on screen;
a BG0 dim rect covers it; a corner-tick panel shows the outcome banner and
three option rows (REMATCH / NEW BATTLE / MAIN MENU).

The class is a pure render + input unit.  The integrator attaches callbacks:
    rematch_cb()     -- restart the same config
    new_battle_cb()  -- go to the setup screen
    menu_cb()        -- go to the main menu

Navigation mirrors _ListScreen: UP/DN select, ENTER confirms (80 ms press-
flash), ESC triggers MAIN MENU (safe default -- the battle is over).

GL-touching module -- never imported by unit tests.  All input logic is
headless (deferred enter pattern, same as every other GameState).
"""

from __future__ import annotations

from typing import Callable

import pygame

from engine.text import BODY_SIZE, HEADER_SIZE, SMALL_SIZE
from game.states import (
    ACCENT, ACCENT_DIM, BG0, BG2, DANGER, DISABLED, FOCUS_BAR_W,
    FOOTER_MARGIN, MUTED, OK_COL, PAD, PAUSE_DIM_A, PRESS_FLASH_A,
    PRESS_FLASH_S, ROW_H, TEXT_COL, WARN, GameState, draw_header_rule,
    draw_panel, move_selection,
)

# --- Layout -------------------------------------------------------------------

END_PANEL_W   = 480
END_FOOTER    = "UP/DN SELECT  ENTER OK  ESC MENU"

_ITEMS        = ("REMATCH", "NEW BATTLE", "MAIN MENU")
_IDX_REMATCH  = 0
_IDX_NEW      = 1
_IDX_MENU     = 2

# Grade -> banner colour (S/A green, B amber, C/D red — same OK/WARN/DANGER
# palette the rest of the HUD uses).
_GRADE_COLS = {"S": OK_COL, "A": OK_COL, "B": WARN, "C": DANGER, "D": DANGER}


def _fmt_mmss(t):
    """sim seconds -> 'm:ss' (or '--:--' for a never-fixed None)."""
    if t is None:
        return "--:--"
    t = max(0.0, float(t))
    m = int(t) // 60
    s = int(t) % 60
    return f"{m}:{s:02d}"


def scorecard_rows(card):
    """Pure: a ScoreCard -> ordered list of (label, value, colour-key) rows for
    the end-overlay stats block.  GL-free + unit-testable; the overlay maps the
    colour key to the OK/WARN/DANGER palette.  ``colour-key`` is 'ok' | 'warn'
    | 'danger' | 'text'."""
    intact = card.base_intact_pct
    return [
        ("KILLS", f"{card.kills}/{card.enemy_total}",
         "ok" if card.kills >= card.enemy_total else "warn"),
        ("ROUNDS", f"{card.rounds_fired}", "text"),
        ("EFFICIENCY", f"{card.efficiency:.2f}", "text"),
        ("FIRST FIX", _fmt_mmss(card.first_fix_t),
         "danger" if card.first_fix_t is None else "text"),
        ("BACK-PLOTTED", "YES" if card.was_back_plotted else "NO",
         "danger" if card.was_back_plotted else "ok"),
        ("LEAK RATE", f"{card.leak_rate * 100:.0f}%", "text"),
        ("BASE INTACT", f"{intact * 100:.0f}%",
         "ok" if intact >= 0.999 else ("warn" if intact > 0.0 else "danger")),
    ]


_ROW_COL = {"ok": OK_COL, "warn": WARN, "danger": DANGER, "text": TEXT_COL}


class CombatEndOverlay(GameState):
    """VICTORY or DEFEAT overlay over the frozen final combat frame.

    Parameters
    ----------
    app:
        The App instance (for window size, TextRenderer, audio, states).
    victory:
        True -> VICTORY banner (green); False -> DEFEAT banner (red).
    rematch_cb:
        Called when the player chooses REMATCH.
    new_battle_cb:
        Called when the player chooses NEW BATTLE (opens the setup screen).
    menu_cb:
        Called when the player chooses MAIN MENU.
    scorecard:
        Optional :class:`game.scoring.ScoreCard` (M6 after-action scoring).
        When given, a stats block (grade + metric rows) renders above the
        option rows.  Defaults to ``None`` — the legacy / smoke path with no
        stats, so existing callers and tools are unchanged.
    """

    def __init__(
        self,
        app,
        victory: bool,
        rematch_cb:   Callable[[], None],
        new_battle_cb: Callable[[], None],
        menu_cb:      Callable[[], None],
        scorecard=None,
    ):
        super().__init__(app)
        self._gl   = None
        self.text  = None
        self.victory = victory
        self.scorecard = scorecard

        self._callbacks = {
            "REMATCH":    rematch_cb,
            "NEW BATTLE": new_battle_cb,
            "MAIN MENU":  menu_cb,
        }

        self._sel:          int   = 0
        self._pending:      str | None = None
        self._pending_left: float = 0.0
        self._hit_rects:    list  = []

    # ------------------------------------------------------------------ enter

    def enter(self) -> None:
        pygame.event.set_grab(False)
        pygame.mouse.set_visible(True)
        if self.text is None:
            import OpenGL.GL as gl
            self._gl = gl
            self.text = self.app.ui_text()
        self._sel  = 0
        self._pending = None
        self._pending_left = 0.0
        self._hit_rects = []

    def effective_time_scale(self) -> float:
        return 0.0   # battle is over; sim time frozen

    # ------------------------------------------------------------------ input

    def handle_event(self, ev) -> None:
        if self._pending is not None:
            return
        if ev.type == pygame.KEYDOWN:
            key = ev.key
            if key == pygame.K_UP:
                self._sel = move_selection(self._sel, -1, len(_ITEMS))
                self.app.audio.ui_click()
            elif key == pygame.K_DOWN:
                self._sel = move_selection(self._sel, 1, len(_ITEMS))
                self.app.audio.ui_click()
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._activate(_ITEMS[self._sel])
            elif key == pygame.K_ESCAPE:
                self._activate("MAIN MENU")
        elif ev.type == pygame.MOUSEMOTION:
            hit = self._hit(ev.pos)
            if hit is not None and hit != self._sel:
                self._sel = hit
                self.app.audio.ui_click()
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            hit = self._hit(ev.pos)
            if hit is not None:
                self._sel = hit
                self._activate(_ITEMS[hit])

    def _activate(self, name: str) -> None:
        self.app.audio.ui_click()
        self._pending      = name
        self._pending_left = PRESS_FLASH_S

    def _tick_pending(self, dt: float) -> None:
        if self._pending is None:
            return
        self._pending_left -= dt
        if self._pending_left <= 0.0:
            name, self._pending = self._pending, None
            self._callbacks[name]()

    def _hit(self, pos) -> int | None:
        for i, (x0, y0, x1, y1) in self._hit_rects:
            if x0 <= pos[0] <= x1 and y0 <= pos[1] <= y1:
                return i
        return None

    # ------------------------------------------------------------------ render

    def render(self, dt_real: float) -> None:
        self._tick_pending(dt_real)

        # The final combat frame is still on screen (the integrator leaves it
        # there by NOT clearing before calling this state's render).  We just
        # apply the dim + overlay.
        w, h = self.app.window.size()
        text = self.text
        self._hit_rects = []

        # Dim the frozen scene
        text.draw_rect(0, 0, w, h, (*BG0, PAUSE_DIM_A))

        # --- Panel geometry --------------------------------------------------
        head_lh  = text.line_height(HEADER_SIZE)
        small_lh = text.line_height(SMALL_SIZE)
        body_lh  = text.line_height(BODY_SIZE)
        inner_w  = END_PANEL_W - 2 * PAD

        # M6 stats block (grade row + one line per metric) — height 0 when no
        # ScoreCard is attached, so the legacy/smoke panel is byte-for-byte the
        # old geometry.
        card = self.scorecard
        if card is not None:
            stat_rows = scorecard_rows(card)
            stats_h = (head_lh + 4               # grade row
                       + len(stat_rows) * small_lh + 10)   # metric lines + gap
        else:
            stat_rows = []
            stats_h = 0

        panel_h  = (PAD + head_lh + 2 + small_lh + 10 + stats_h + 10
                    + len(_ITEMS) * ROW_H + PAD)
        px = (w - END_PANEL_W) // 2
        py = (h - panel_h)     // 2 - 40
        draw_panel(text, px, py, END_PANEL_W, panel_h, strip=True)

        # --- Outcome banner --------------------------------------------------
        if self.victory:
            banner_text  = "VICTORY"
            banner_col   = OK_COL
        else:
            banner_text  = "DEFEAT"
            banner_col   = DANGER
        text.draw_text(px + PAD, py + PAD, banner_text, banner_col, HEADER_SIZE)

        # Sub-label: small, muted
        sub = "MISSION COMPLETE" if self.victory else "ALL BASTION TELs DESTROYED"
        text.draw_text(px + PAD, py + PAD + head_lh + 2, sub, MUTED, SMALL_SIZE)

        # Divider
        rule_y = py + PAD + head_lh + 2 + small_lh + 10
        draw_header_rule(text, px + PAD, rule_y, inner_w)

        # --- M6 stats block (grade + metric rows) ----------------------------
        block_y = rule_y + 10
        if card is not None:
            label_x = px + PAD
            val_x = px + END_PANEL_W - PAD            # right-aligned values
            grade_col = _GRADE_COLS.get(card.grade, TEXT_COL)
            # Big grade letter on the left, 'GRADE' label trailing it.
            text.draw_text(label_x, block_y, card.grade or "-",
                           grade_col, HEADER_SIZE)
            gw = text.text_width(card.grade or "-", HEADER_SIZE)
            text.draw_text(label_x + gw + 8,
                           block_y + (head_lh - small_lh),
                           "GRADE", MUTED, SMALL_SIZE)
            sy = block_y + head_lh + 4
            for label, value, key in stat_rows:
                text.draw_text(label_x, sy, label, MUTED, SMALL_SIZE)
                vw = text.text_width(value, SMALL_SIZE)
                text.draw_text(val_x - vw, sy, value,
                               _ROW_COL.get(key, TEXT_COL), SMALL_SIZE)
                sy += small_lh
            block_y = sy + 10

        # --- Option rows -----------------------------------------------------
        row_x = px + PAD
        ry    = block_y
        for i, name in enumerate(_ITEMS):
            selected = (i == self._sel)
            col = MUTED
            if selected:
                col = ACCENT
                text.draw_rect(row_x, ry, inner_w, ROW_H, (*BG2, 1.0))
                text.draw_rect(row_x, ry, FOCUS_BAR_W, ROW_H, (*ACCENT, 1.0))
            if self._pending == name:
                text.draw_rect(row_x, ry, inner_w, ROW_H, (*ACCENT, PRESS_FLASH_A))
            ty = ry + (ROW_H - body_lh) // 2
            text.draw_text(row_x + PAD, ty, name, col)
            self._hit_rects.append((i, (row_x, ry, row_x + inner_w, ry + ROW_H)))
            ry += ROW_H

        # --- Footer ----------------------------------------------------------
        fw = text.text_width(END_FOOTER, SMALL_SIZE)
        text.draw_text((w - fw) // 2, py + panel_h + FOOTER_MARGIN,
                       END_FOOTER, ACCENT_DIM, SMALL_SIZE)

        text.flush(w, h)

    # ------------------------------------------------------------------ public API

    @property
    def options(self) -> tuple:
        """The three option labels, in order (REMATCH / NEW BATTLE / MAIN MENU).
        Exposed for tests so they can verify the set without hardcoding strings."""
        return _ITEMS
