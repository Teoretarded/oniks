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

from engine.text import BODY_SIZE, HEADER_SIZE, SMALL_SIZE, TITLE_SIZE
from game.states import (
    ACCENT, BG0, BG2, DANGER, FAINT, GRADE_COLS, GRADE_TINTS, GRADE_VERDICTS,
    MUTED, OK_COL, PAD, PAUSE_DIM_A, PRESS_FILL, PRESS_FLASH_S, ROW_DIVIDER,
    ROW_H, TEXT_COL, GameState, draw_hint_bar, draw_panel, move_selection,
)

# --- Layout (Wardroom Dusk, mock 09: grade plate + VALUE-vs-PAR table) ----------

END_PANEL_W   = 800
GRADE_W       = 208          # tinted grade plate width (left column)
END_FOOTER    = "UP/DN SELECT   ENTER OK   ESC MENU"

_ITEMS          = ("REMATCH", "NEW BATTLE", "MAIN MENU")
# Campaign-mode rows: the battle belongs to a chain, so REMATCH/NEW BATTLE
# (grade-scum / off-ramp) are replaced by the single continue affordance.
_CAMPAIGN_ITEMS = ("CONTINUE CAMPAIGN", "MAIN MENU")


def _fmt_mmss(t):
    """sim seconds -> 'm:ss' (or '--:--' for a never-fixed None)."""
    if t is None:
        return "--:--"
    t = max(0.0, float(t))
    m = int(t) // 60
    s = int(t) % 60
    return f"{m}:{s:02d}"


def aar_rows(card, par=None):
    """Pure: ScoreCard (+ optional Par) -> ordered stat rows for the AAR table.

    Each row is ``(label, value, passed, par_text)`` where ``passed`` is
    True/False against the SAME bar :func:`game.scoring.grade` scored (green
    pass / dusk-red fail), or None for a neutral measurement, and ``par_text``
    is the faint annotation ('- PAR >=0.45') or None when the sim publishes no
    bar for that stat.  HONESTY RULES (locked): ROUNDS EXPENDED has no PAR in
    the sim, so it carries NO annotation (the mock's '<=12' was a placeholder);
    LEAK RATE grades HIGHER-is-better (rounds that got through) and BACK-
    PLOTTED's bar is NO (staying hidden earns the point) — both annotate the
    real direction, not the mock's guess.  GL-free + unit-testable."""
    intact = card.base_intact_pct
    fixed = card.first_fix_t is not None
    rows = [
        ("KILLS", f"{card.kills}/{card.enemy_total}",
         card.kills >= card.enemy_total, f"- PAR {card.enemy_total}"),
        ("ROUNDS EXPENDED", f"{card.rounds_fired}", None, None),
    ]
    if par is not None:
        rows += [
            ("EFFICIENCY", f"{card.efficiency:.2f}",
             card.efficiency >= par.efficiency,
             f"- PAR >={par.efficiency:.2f}"),
            ("FIRST FIX", _fmt_mmss(card.first_fix_t),
             fixed and card.first_fix_t <= par.first_fix_t,
             f"- PAR <={_fmt_mmss(par.first_fix_t)}"),
            ("BACK-PLOTTED", "YES" if card.was_back_plotted else "NO",
             not card.was_back_plotted, "- PAR NO"),
            ("LEAK RATE", f"{card.leak_rate * 100:.0f}%",
             card.leak_rate >= par.leak_rate,
             f"- PAR >={par.leak_rate * 100:.0f}%"),
            ("BASE INTACT", f"{intact * 100:.0f}%",
             intact >= par.base_intact_pct,
             f"- PAR >={par.base_intact_pct * 100:.0f}%"),
        ]
    else:                       # degraded path: measurements without a bar
        rows += [
            ("EFFICIENCY", f"{card.efficiency:.2f}", None, None),
            ("FIRST FIX", _fmt_mmss(card.first_fix_t),
             None if fixed else False, None),
            ("BACK-PLOTTED", "YES" if card.was_back_plotted else "NO",
             not card.was_back_plotted, None),
            ("LEAK RATE", f"{card.leak_rate * 100:.0f}%", None, None),
            ("BASE INTACT", f"{intact * 100:.0f}%",
             True if intact >= 0.999 else (None if intact > 0.0 else False),
             None),
        ]
    return rows


def failed_axes(card, par):
    """Pure: the grade axes that missed PAR, as display names (the grade
    plate's shame caption).  Mirrors the five axes grade() scores; an axis
    at full merit is omitted.  Empty when par is None or everything passed."""
    if par is None:
        return []
    out = []
    if card.first_fix_t is None or card.first_fix_t > par.first_fix_t:
        out.append("FIRST FIX")
    if card.efficiency < par.efficiency:
        out.append("EFFICIENCY")
    if card.leak_rate < par.leak_rate:
        out.append("LEAK RATE")
    if card.base_intact_pct < par.base_intact_pct:
        out.append("BASE INTACT")
    if card.was_back_plotted:
        out.append("BACK-PLOT")
    return out


# DEFEAT subtitle per lose clause (world.defeat_cause).  'bastion' is the
# fallback for None/unknown so every legacy caller keeps the historic string.
_DEFEAT_SUBTITLES = {
    "bastion":   "ALL BASTION TELs DESTROYED",
    "beachhead": "BEACHHEAD ESTABLISHED",
}


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
    campaign_cb:
        Optional CONTINUE CAMPAIGN callback (M6 campaign UI wiring).  When
        given the option rows become CONTINUE CAMPAIGN / MAIN MENU — the
        battle belongs to a chain, so REMATCH / NEW BATTLE are not offered.
        ``None`` keeps the legacy three-row layout byte-for-byte.
    """

    def __init__(
        self,
        app,
        victory: bool,
        rematch_cb:   Callable[[], None],
        new_battle_cb: Callable[[], None],
        menu_cb:      Callable[[], None],
        scorecard=None,
        campaign_cb=None,
        par=None,
        end_time=None,
        debrief_cb=None,
        defeat_cause=None,
    ):
        super().__init__(app)
        self._gl   = None
        self.text  = None
        self.victory = victory
        # Which lose clause tripped ('bastion' | 'beachhead' | None) — drives
        # the DEFEAT subtitle so a beachhead loss no longer reads the bastion
        # string.  None keeps the legacy bastion wording (smoke/tool callers).
        self.defeat_cause = defeat_cause
        self.scorecard = scorecard
        self.par = par                  # game.scoring.Par (None: no bar shown)
        self.end_time = end_time        # sim clock at the decision (header)
        self._t = 0.0                   # presentation clock (D-grade blink)

        if campaign_cb is not None:
            self._items = _CAMPAIGN_ITEMS
            self._callbacks = {
                "CONTINUE CAMPAIGN": campaign_cb,
                "MAIN MENU":         menu_cb,
            }
        else:
            self._items = _ITEMS
            self._callbacks = {
                "REMATCH":    rematch_cb,
                "NEW BATTLE": new_battle_cb,
                "MAIN MENU":  menu_cb,
            }
        # FORENSICS handoff: a DEBRIEF row opens the recorded-flight-path
        # ledger OVER this overlay (ESC on the sheet leafs back here).  Only
        # offered when the owning state wired a callback — legacy/smoke
        # constructions keep the exact historical row set.
        if debrief_cb is not None:
            self._items = ("DEBRIEF",) + tuple(self._items)
            self._callbacks["DEBRIEF"] = debrief_cb

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
                self._sel = move_selection(self._sel, -1, len(self._items))
                self.app.audio.ui_click()
            elif key == pygame.K_DOWN:
                self._sel = move_selection(self._sel, 1, len(self._items))
                self.app.audio.ui_click()
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._activate(self._items[self._sel])
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
                self._activate(self._items[hit])

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
        self._t += dt_real

        # The final combat frame is still on screen (the integrator leaves it
        # there by NOT clearing before calling this state's render).  We just
        # apply the dim + overlay.
        w, h = self.app.window.size()
        text = self.text
        self._hit_rects = []

        # Dim the frozen scene
        text.draw_rect(0, 0, w, h, (*BG0, PAUSE_DIM_A))

        # --- Geometry (mock 09): hero AAR plate, then the option plate -------
        head_lh  = text.line_height(HEADER_SIZE)
        small_lh = text.line_height(SMALL_SIZE)
        body_lh  = text.line_height(BODY_SIZE)

        card = self.scorecard
        stat_rows = aar_rows(card, self.par) if card is not None else []
        head_band = PAD + head_lh + 10          # banner row + gap
        if card is not None:
            table_h = small_lh + 6 + len(stat_rows) * ROW_H
            stats_h = max(table_h, 150) + PAD
        else:
            stats_h = 0
        panel_h = head_band + stats_h + (PAD if card is None else 0)
        menu_h = len(self._items) * ROW_H + 2 * 8

        px = (w - END_PANEL_W) // 2
        py = (h - (panel_h + 12 + menu_h)) // 2 - 30
        draw_panel(text, px, py, END_PANEL_W, panel_h, strip=True)

        # --- Banner row: outcome left, clock caption right -------------------
        banner_text = "VICTORY" if self.victory else "DEFEAT"
        banner_col  = OK_COL if self.victory else DANGER
        text.draw_text(px + PAD, py + PAD, banner_text, banner_col, HEADER_SIZE)
        if self.victory:
            sub = "MISSION COMPLETE"
        else:
            sub = _DEFEAT_SUBTITLES.get(self.defeat_cause,
                                        _DEFEAT_SUBTITLES["bastion"])
        if self.end_time is not None:
            sub += f" - T+{_fmt_mmss(self.end_time)}"
        sw = text.text_width(sub, SMALL_SIZE)
        text.draw_text(px + END_PANEL_W - PAD - sw,
                       py + PAD + (head_lh - small_lh), sub, MUTED, SMALL_SIZE)

        # --- Grade plate (left) + VALUE-vs-PAR table (right) -----------------
        if card is not None:
            gy = py + head_band
            self._grade_plate(px + PAD, gy, GRADE_W, stats_h - PAD, card)
            tx = px + PAD + GRADE_W + 20
            tw_col = px + END_PANEL_W - PAD - tx          # right column width
            # Faint table header: STAT left, VALUE - PAR right.
            text.draw_text(tx, gy, "STAT", FAINT, SMALL_SIZE)
            hdr = "VALUE - PAR"
            text.draw_text(tx + tw_col - text.text_width(hdr, SMALL_SIZE), gy,
                           hdr, FAINT, SMALL_SIZE)
            ry = gy + small_lh + 6
            for label, value, passed, par_text in stat_rows:
                text.draw_lines([(tx, ry), (tx + tw_col, ry)],
                                (*ROW_DIVIDER, 1.0), 1.0)
                vy = ry + (ROW_H - body_lh) // 2
                text.draw_text(tx, vy, label, MUTED)
                # value (pass green / fail dusk-red / neutral cream) with the
                # faint PAR annotation trailing it.
                vcol = (TEXT_COL if passed is None
                        else OK_COL if passed else DANGER)
                pw = (text.text_width(par_text, SMALL_SIZE) + 8
                      if par_text else 0)
                vw = text.text_width(value)
                text.draw_text(tx + tw_col - pw - vw, vy, value, vcol)
                if par_text:
                    text.draw_text(tx + tw_col - pw + 8,
                                   ry + (ROW_H - small_lh) // 2,
                                   par_text, FAINT, SMALL_SIZE)
                ry += ROW_H

        # --- Option plate ----------------------------------------------------
        my = py + panel_h + 12
        draw_panel(text, px, my, END_PANEL_W, menu_h, ticks=False)
        ry = my + 8
        for i, name in enumerate(self._items):
            selected = (i == self._sel)
            col = MUTED
            rx = px + 1
            rw = END_PANEL_W - 2
            if selected:
                col = ACCENT
                text.draw_rect(rx, ry, rw, ROW_H, (*BG2, 1.0))
                text.draw_rect(rx, ry, 4, ROW_H, (*ACCENT, 1.0))
            if self._pending == name:
                text.draw_rect(rx, ry, rw, ROW_H, (*PRESS_FILL, 1.0))
            ty = ry + (ROW_H - body_lh) // 2
            tw = text.text_width(name)
            text.draw_text(px + (END_PANEL_W - tw) // 2, ty, name, col)
            self._hit_rects.append((i, (rx, ry, rx + rw, ry + ROW_H)))
            ry += ROW_H

        # --- Hint bar ---------------------------------------------------------
        draw_hint_bar(text, w, h, END_FOOTER)
        text.flush(w, h)

    def _grade_plate(self, x, y, w, h, card) -> None:
        """The family-tinted grade plate (mock 09 + widget sheet 08): 56pt
        letter, verdict word, and the missed-axes caption.  S wears a flat
        ring glow; D wears the shame treatment (deep red tint, inset ring,
        blinking letter).  Flat rects + text only."""
        text = self.text
        g = card.grade or "-"
        tint = GRADE_TINTS.get(g)
        gcol = GRADE_COLS.get(g, TEXT_COL)
        if tint is not None:
            bg, border = tint
            text.draw_rect(x, y, w, h, (*bg, 1.0))
            text.draw_lines([(x, y), (x + w, y), (x + w, y + h), (x, y + h),
                             (x, y)], (*border, 1.0), 1.0)
        if g in ("S", "D"):
            # Flat inset ring: S = achievement glow, D = the shame ring.
            ring = OK_COL if g == "S" else DANGER
            text.draw_lines([(x + 4, y + 4), (x + w - 4, y + 4),
                             (x + w - 4, y + h - 4), (x + 4, y + h - 4),
                             (x + 4, y + 4)], (*ring, 0.25), 2.0)
        title_lh = text.line_height(TITLE_SIZE)
        small_lh = text.line_height(SMALL_SIZE)
        # D blinks its letter at ~1.2 Hz (presentation clock only).
        visible = (g != "D") or (int(self._t * 2.4) % 2 == 0)
        gw = text.text_width(g, TITLE_SIZE)
        gy = y + max(10, (h - title_lh - 2 * small_lh - 18) // 2)
        if visible:
            text.draw_text(x + (w - gw) // 2, gy, g, gcol, TITLE_SIZE)
        verdict = GRADE_VERDICTS.get(g, "")
        if verdict:
            vw = text.text_width(verdict, SMALL_SIZE)
            text.draw_text(x + (w - vw) // 2, gy + title_lh + 6, verdict,
                           (*gcol[:3], 0.75), SMALL_SIZE)
        # Missed-axes caption, faint, up to two lines.
        axes = failed_axes(card, self.par)
        if axes:
            line1 = " - ".join(axes[:2])
            line2 = " - ".join(axes[2:4])
            cy = gy + title_lh + 6 + small_lh + 8
            for ln in (line1, line2):
                if not ln:
                    continue
                lw = text.text_width(ln, SMALL_SIZE)
                text.draw_text(x + (w - lw) // 2, cy, ln, FAINT, SMALL_SIZE)
                cy += small_lh + 2

    # ------------------------------------------------------------------ public API

    @property
    def options(self) -> tuple:
        """The option labels, in order (legacy: REMATCH / NEW BATTLE /
        MAIN MENU; campaign: CONTINUE CAMPAIGN / MAIN MENU).  Exposed for
        tests so they can verify the set without hardcoding strings."""
        return self._items
