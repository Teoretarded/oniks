"""CombatSetupState: the two-page setup screen before a COMBAT session (Phase 7).

Visual language matches SettingsState/MenuState (game/states.py): corner-tick
panel, amber header rule, 40 px rows with label-left/value-right, selected-row
highlight with 3 px left focus bar, 80 ms press-flash on START, footer hints.

Two pages toggled with TAB:
    World  -- SEED + force-count steppers + CARRIER (fixed) display.
    Armory -- per-weapon ammo + reload steppers.

Navigation:
    UP/DN   move selection
    LEFT/RT adjust stepper value (+/- 1 for counts, +/- 5 s for reloads)
    TAB     switch page
    ENTER   START (bottom row of each page, or press on the START sentinel)
    ESC     back to main menu (no confirm -- no session data exists yet)

Seed editing:
    Typing digits 0-9 while the seed row is focused appends to a digit
    buffer; ENTER commits, BACKSPACE erases, ESC cancels.  A dedicated R key
    advances a deterministic LCG counter -- no host RNG, no wall-clock.

All input logic runs headless; GL/text is deferred to enter()/render().
"""

from __future__ import annotations

from typing import Callable

import pygame

from engine.text import BODY_SIZE, HEADER_SIZE, SMALL_SIZE
from game.states import (
    ACCENT, ACCENT_DIM, BG0, BG2, DISABLED, FOCUS_BAR_W, FOOTER_MARGIN,
    LINE_COL, MUTED, PAD, PRESS_FLASH_A, PRESS_FLASH_S, ROW_H,
    TEXT_COL, GameState, draw_header_rule, draw_panel,
    move_selection,
)
from world.combat_config import (
    CombatConfig,
    CLAMP_AMMO, CLAMP_AWACS, CLAMP_DESTROYERS, CLAMP_DRONES,
    CLAMP_ENEMY_RADARS, CLAMP_PANTSIR, CLAMP_PLAYER_RADARS, CLAMP_RELOAD_S,
    clamp_config,
)

# --- Layout -------------------------------------------------------------------

SETUP_PANEL_W = 680    # wider than menu COL_W; fits label + value + chevrons
SETUP_FOOTER = ("UP/DN SELECT   LT/RT ADJUST   TAB PAGE   "
                "ENTER START   R RANDOMIZE SEED   ESC BACK")

# Deterministic LCG for seed randomisation (Numerical Recipes constants).
# No host RNG, no wall-clock: same sequence from the same starting counter.
_LCG_A   = 1664525
_LCG_C   = 1013904223
_LCG_MOD = 2 ** 32
_SEED_MAX = 2 ** 31 - 1

# Page indices
_PAGE_WORLD  = 0
_PAGE_ARMORY = 1
_PAGE_NAMES  = ("WORLD", "ARMORY")

# Sentinel string: selecting this row fires START.
_START = "START"


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


# Row descriptors --------------------------------------------------------------
# Each dict:
#   kind:   "stepper" | "fixed" | "seed" | "action"
#   label:  display string (left side)
#   field:  CombatConfig field name (steppers / seed)
#   step:   increment per LEFT/RIGHT press
#   lo/hi:  per-row clamp bounds

_WORLD_ROWS = [
    {"kind": "seed",    "label": "SEED",          "field": "seed"},
    {"kind": "fixed",   "label": "CARRIER",       "value": "1  (FIXED)"},
    {"kind": "stepper", "label": "DESTROYERS",    "field": "n_destroyers",
     "step": 1, "lo": CLAMP_DESTROYERS[0],    "hi": CLAMP_DESTROYERS[1]},
    {"kind": "stepper", "label": "AWACS",         "field": "n_awacs",
     "step": 1, "lo": CLAMP_AWACS[0],         "hi": CLAMP_AWACS[1]},
    {"kind": "stepper", "label": "ENEMY RADARS",  "field": "n_enemy_radars",
     "step": 1, "lo": CLAMP_ENEMY_RADARS[0],  "hi": CLAMP_ENEMY_RADARS[1]},
    {"kind": "stepper", "label": "PLAYER RADARS", "field": "n_player_radars",
     "step": 1, "lo": CLAMP_PLAYER_RADARS[0], "hi": CLAMP_PLAYER_RADARS[1]},
    {"kind": "stepper", "label": "PANTSIR TELs",  "field": "n_pantsir",
     "step": 1, "lo": CLAMP_PANTSIR[0],       "hi": CLAMP_PANTSIR[1]},
    {"kind": "stepper", "label": "DRONES",        "field": "n_drones",
     "step": 1, "lo": CLAMP_DRONES[0],        "hi": CLAMP_DRONES[1]},
    {"kind": "action",  "label": _START},
]

_ARMORY_ROWS = [
    {"kind": "stepper", "label": "ONIKS  AMMO",
     "field": "oniks_ammo",
     "step": 1,  "lo": CLAMP_AMMO[0],    "hi": CLAMP_AMMO[1]},
    {"kind": "stepper", "label": "ONIKS  RELOAD (s)",
     "field": "oniks_mag_reload_s",
     "step": 5,  "lo": CLAMP_RELOAD_S[0], "hi": CLAMP_RELOAD_S[1]},
    {"kind": "stepper", "label": "S-300  48N6 AMMO",
     "field": "s300_48n6_ammo",
     "step": 1,  "lo": CLAMP_AMMO[0],    "hi": CLAMP_AMMO[1]},
    {"kind": "stepper", "label": "S-300  40N6 AMMO",
     "field": "s300_40n6_ammo",
     "step": 1,  "lo": CLAMP_AMMO[0],    "hi": CLAMP_AMMO[1]},
    {"kind": "stepper", "label": "S-300  RELOAD (s)",
     "field": "s300_mag_reload_s",
     "step": 5,  "lo": CLAMP_RELOAD_S[0], "hi": CLAMP_RELOAD_S[1]},
    {"kind": "stepper", "label": "PANTSIR  57E6 AMMO",
     "field": "pantsir_57e6_ammo",
     "step": 1,  "lo": CLAMP_AMMO[0],    "hi": CLAMP_AMMO[1]},
    {"kind": "stepper", "label": "PANTSIR  GUN AMMO",
     "field": "pantsir_gun_ammo",
     "step": 10, "lo": CLAMP_AMMO[0],    "hi": CLAMP_AMMO[1]},
    {"kind": "stepper", "label": "PANTSIR  RELOAD (s)",
     "field": "pantsir_mag_reload_s",
     "step": 5,  "lo": CLAMP_RELOAD_S[0], "hi": CLAMP_RELOAD_S[1]},
    {"kind": "action",  "label": _START},
]

_PAGES = (_WORLD_ROWS, _ARMORY_ROWS)


class CombatSetupState(GameState):
    """Two-page setup screen for configuring a COMBAT session.

    ``start_cb`` is called with a fully-built, clamped CombatConfig when the
    player confirms START (after the 80 ms press-flash).  The integrator
    wires this to app.start_combat(config).

    All input / state runs headless; GL is deferred to enter()/render().
    """

    def __init__(self, app, start_cb: Callable[[CombatConfig], None]):
        super().__init__(app)
        self._gl = None
        self.text = None
        self.start_cb = start_cb

        # Mutable mirror of CombatConfig fields; floats stay float.
        defaults = CombatConfig()
        self._fields: dict[str, int | float] = {
            "seed":               defaults.seed,
            "n_destroyers":       defaults.n_destroyers,
            "n_awacs":            defaults.n_awacs,
            "n_enemy_radars":     defaults.n_enemy_radars,
            "n_player_radars":    defaults.n_player_radars,
            "n_pantsir":          defaults.n_pantsir,
            "n_drones":           defaults.n_drones,
            "oniks_ammo":         defaults.oniks_ammo,
            "oniks_mag_reload_s": defaults.oniks_mag_reload_s,
            "s300_48n6_ammo":     defaults.s300_48n6_ammo,
            "s300_40n6_ammo":     defaults.s300_40n6_ammo,
            "s300_mag_reload_s":  defaults.s300_mag_reload_s,
            "pantsir_57e6_ammo":  defaults.pantsir_57e6_ammo,
            "pantsir_gun_ammo":   defaults.pantsir_gun_ammo,
            "pantsir_mag_reload_s": defaults.pantsir_mag_reload_s,
        }

        self._page: int = _PAGE_WORLD
        self._sel:  int = 0

        # Press-flash before firing START
        self._pending:      bool  = False
        self._pending_left: float = 0.0

        # Deterministic seed LCG: counter only, no host RNG / wall-clock.
        self._lcg_state: int = 0

        # Digit buffer for seed row entry
        self._seed_editing: bool = False
        self._seed_digits:  str  = ""

        # Per-render hit rectangles: [(row_index, (x0, y0, x1, y1))]
        self._hit_rects: list = []

    # ------------------------------------------------------------------ enter

    def enter(self) -> None:
        pygame.event.set_grab(False)
        pygame.mouse.set_visible(True)
        if self.text is None:
            import OpenGL.GL as gl
            self._gl = gl
            self.text = self.app.ui_text()
        self._sel = 0
        self._pending = False
        self._pending_left = 0.0
        self._hit_rects = []

    def effective_time_scale(self) -> float:
        return 0.0   # setup screen freezes the sim

    # ------------------------------------------------------------------ helpers

    def _rows(self) -> list:
        return _PAGES[self._page]

    def _row_count(self) -> int:
        return len(self._rows())

    def _current_row(self) -> dict:
        return self._rows()[self._sel]

    # ------------------------------------------------------------------ LCG

    def _advance_lcg(self) -> int:
        """One deterministic LCG step; returns a seed value in [0, 2^31-1]."""
        self._lcg_state = (self._lcg_state * _LCG_A + _LCG_C) % _LCG_MOD
        return self._lcg_state & _SEED_MAX

    # ------------------------------------------------------------------ input

    def handle_event(self, ev) -> None:
        if self._pending:
            return   # press-flash in progress; all input off
        if ev.type == pygame.KEYDOWN:
            self._handle_key(ev.key, ev.unicode)
        elif ev.type == pygame.MOUSEMOTION:
            hit = self._hit(ev.pos)
            if hit is not None and hit != self._sel:
                self._sel = hit
                self._cancel_seed_edit()
                self.app.audio.ui_click()
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            hit = self._hit(ev.pos)
            if hit is not None:
                self._sel = hit
                self._activate_current()

    def _handle_key(self, key: int, unicode: str) -> None:
        row = self._current_row()

        # --- Digit mode: seed row is accepting typed digits ---
        if self._seed_editing and row.get("kind") == "seed":
            if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._commit_seed_digits()
                return
            if key == pygame.K_ESCAPE:
                self._cancel_seed_edit()
                return
            if key == pygame.K_BACKSPACE:
                self._seed_digits = self._seed_digits[:-1]
                return
            if unicode and unicode.isdigit() and len(self._seed_digits) < 10:
                self._seed_digits += unicode
                return
            # Any other key while editing: ignore
            return

        # --- Normal navigation ---
        if key == pygame.K_UP:
            self._sel = move_selection(self._sel, -1, self._row_count())
            self._cancel_seed_edit()
            self.app.audio.ui_click()
        elif key == pygame.K_DOWN:
            self._sel = move_selection(self._sel, 1, self._row_count())
            self._cancel_seed_edit()
            self.app.audio.ui_click()
        elif key == pygame.K_TAB:
            self._page = _PAGE_ARMORY if self._page == _PAGE_WORLD else _PAGE_WORLD
            self._sel = 0
            self._cancel_seed_edit()
            self.app.audio.ui_click()
        elif key == pygame.K_ESCAPE:
            self._back()
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._activate_current()
        elif key == pygame.K_LEFT:
            self._adjust(-1)
        elif key == pygame.K_RIGHT:
            self._adjust(1)
        elif key == pygame.K_r:
            # Randomize seed (on any page -- user may trigger from armory too)
            self._fields["seed"] = self._advance_lcg()
            self._cancel_seed_edit()
            self.app.audio.ui_click()
        else:
            # Start digit capture when a digit is typed on the seed row
            if row.get("kind") == "seed" and unicode and unicode.isdigit():
                self._seed_editing = True
                self._seed_digits = unicode
                self.app.audio.ui_click()

    def _adjust(self, direction: int) -> None:
        """LEFT/RIGHT: step the focused row's value."""
        row = self._current_row()
        kind = row.get("kind")
        if kind == "stepper":
            field = row["field"]
            v = self._fields[field] + row["step"] * direction
            self._fields[field] = _clamp(v, row["lo"], row["hi"])
            self.app.audio.ui_click()
        elif kind == "seed":
            v = int(self._fields["seed"]) + direction
            self._fields["seed"] = _clamp(v, 0, _SEED_MAX)
            self.app.audio.ui_click()

    def _activate_current(self) -> None:
        row = self._current_row()
        kind = row.get("kind")
        if kind == "action" and row["label"] == _START:
            self.app.audio.ui_click()
            self._pending = True
            self._pending_left = PRESS_FLASH_S
        elif kind == "seed":
            # Toggle digit-entry mode on ENTER
            if self._seed_editing:
                self._commit_seed_digits()
            else:
                self._seed_editing = True
                self._seed_digits = ""
            self.app.audio.ui_click()

    def _commit_seed_digits(self) -> None:
        if self._seed_digits:
            v = int(self._seed_digits)
            self._fields["seed"] = _clamp(v, 0, _SEED_MAX)
        self._seed_editing = False
        self._seed_digits = ""

    def _cancel_seed_edit(self) -> None:
        self._seed_editing = False
        self._seed_digits = ""

    def _back(self) -> None:
        self._cancel_seed_edit()
        self.app.states.switch(self.app.menu)

    def _hit(self, pos) -> int | None:
        for i, (x0, y0, x1, y1) in self._hit_rects:
            if x0 <= pos[0] <= x1 and y0 <= pos[1] <= y1:
                return i
        return None

    # ------------------------------------------------------------------ tick

    def _tick_pending(self, dt: float) -> None:
        if not self._pending:
            return
        self._pending_left -= dt
        if self._pending_left <= 0.0:
            self._pending = False
            self.start_cb(self.build_config())

    # ------------------------------------------------------------------ config

    def build_config(self) -> CombatConfig:
        """Return a clamped CombatConfig from the current field state."""
        f = self._fields
        return clamp_config(
            seed               = int(f["seed"]),
            n_destroyers       = int(f["n_destroyers"]),
            n_awacs            = int(f["n_awacs"]),
            n_enemy_radars     = int(f["n_enemy_radars"]),
            n_player_radars    = int(f["n_player_radars"]),
            n_pantsir          = int(f["n_pantsir"]),
            n_drones           = int(f["n_drones"]),
            oniks_ammo         = int(f["oniks_ammo"]),
            oniks_mag_reload_s = float(f["oniks_mag_reload_s"]),
            s300_48n6_ammo     = int(f["s300_48n6_ammo"]),
            s300_40n6_ammo     = int(f["s300_40n6_ammo"]),
            s300_mag_reload_s  = float(f["s300_mag_reload_s"]),
            pantsir_57e6_ammo  = int(f["pantsir_57e6_ammo"]),
            pantsir_gun_ammo   = int(f["pantsir_gun_ammo"]),
            pantsir_mag_reload_s = float(f["pantsir_mag_reload_s"]),
        )

    # ------------------------------------------------------------------ render

    def render(self, dt_real: float) -> None:
        self._tick_pending(dt_real)
        gl = self._gl
        gl.glClearColor(BG0[0], BG0[1], BG0[2], 1.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        w, h = self.app.window.size()
        text = self.text
        x = (w - SETUP_PANEL_W) // 2
        self._hit_rects = []

        head_lh  = text.line_height(HEADER_SIZE)
        small_lh = text.line_height(SMALL_SIZE)
        body_lh  = text.line_height(BODY_SIZE)

        # --- Header ----------------------------------------------------------
        page_name   = _PAGE_NAMES[self._page]
        header_text = f"COMBAT SETUP  /  {page_name}"
        text.draw_text(x, 40, header_text, ACCENT, HEADER_SIZE)
        rule_y = 40 + head_lh + 8
        draw_header_rule(text, x, rule_y, SETUP_PANEL_W)

        # --- Page tabs -------------------------------------------------------
        tab_w = SETUP_PANEL_W // len(_PAGE_NAMES)
        for i, pname in enumerate(_PAGE_NAMES):
            col = ACCENT if i == self._page else MUTED
            tx = x + i * tab_w
            text.draw_text(tx, rule_y + 6, pname, col, SMALL_SIZE)
            if i == self._page:
                pw = text.text_width(pname, SMALL_SIZE)
                text.draw_lines(
                    [(tx, rule_y + 6 + small_lh + 2),
                     (tx + pw, rule_y + 6 + small_lh + 2)],
                    (*ACCENT, 1.0), 1.5)
        tab_h = small_lh + 12

        # --- Panel -----------------------------------------------------------
        rows = self._rows()
        panel_y = rule_y + tab_h + 4
        panel_h = len(rows) * ROW_H + 2 * PAD
        draw_panel(text, x, panel_y, SETUP_PANEL_W, panel_h, strip=True)

        # --- Rows ------------------------------------------------------------
        row_x = x + PAD
        row_w = SETUP_PANEL_W - 2 * PAD
        ry = panel_y + PAD
        for i, row in enumerate(rows):
            self._draw_row(row, i, row_x, ry, row_w, body_lh)
            ry += ROW_H

        # --- Footer ----------------------------------------------------------
        fy = h - FOOTER_MARGIN - small_lh
        fw = text.text_width(SETUP_FOOTER, SMALL_SIZE)
        text.draw_text((w - fw) // 2, fy, SETUP_FOOTER, ACCENT_DIM, SMALL_SIZE)

        text.flush(w, h)

    def _draw_row(self, row: dict, idx: int, x: int, y: int, w: int,
                  body_lh: int) -> None:
        text  = self.text
        kind  = row.get("kind")
        selected = (idx == self._sel)
        label = row["label"]

        # Row background + 3px left focus bar
        if selected:
            text.draw_rect(x, y, w, ROW_H, (*BG2, 1.0))
            text.draw_rect(x, y, FOCUS_BAR_W, ROW_H, (*ACCENT, 1.0))

        # Press-flash on the START action row
        if self._pending and kind == "action" and label == _START:
            text.draw_rect(x, y, w, ROW_H, (*ACCENT, PRESS_FLASH_A))

        label_col = ACCENT if selected else MUTED
        ty = y + (ROW_H - body_lh) // 2

        if kind == "fixed":
            text.draw_text(x + PAD, ty, label, MUTED)
            val = row.get("value", "")
            vw  = text.text_width(val)
            text.draw_text(x + w - vw, ty, val, DISABLED)

        elif kind == "seed":
            text.draw_text(x + PAD, ty, label, label_col)
            if self._seed_editing and selected:
                display  = (self._seed_digits + "_") if self._seed_digits else "_"
                val_col  = ACCENT
            else:
                display  = str(int(self._fields["seed"]))
                val_col  = TEXT_COL if selected else MUTED
            vw = text.text_width(display)
            text.draw_text(x + w - vw, ty, display, val_col)

        elif kind == "stepper":
            text.draw_text(x + PAD, ty, label, label_col)
            field = row["field"]
            v     = self._fields[field]
            # Whole-number floats (reload multiples of 5 s): show as int
            if isinstance(v, float) and v == int(v):
                val_str = str(int(v))
            elif isinstance(v, float):
                val_str = f"{v:.1f}"
            else:
                val_str = str(v)
            if selected:
                display = f"< {val_str} >"
            else:
                display = val_str
            vw      = text.text_width(display)
            val_col = TEXT_COL if selected else MUTED
            text.draw_text(x + w - vw, ty, display, val_col)

        elif kind == "action":
            # START: centred, uses accent when selected, disabled otherwise
            col = ACCENT if selected else DISABLED
            tw  = text.text_width(label)
            text.draw_text(x + (w - tw) // 2, ty, label, col)

        self._hit_rects.append((idx, (x, y, x + w, y + ROW_H)))
