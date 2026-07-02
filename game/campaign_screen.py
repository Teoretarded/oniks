"""CampaignHubState: the between-battles CAMPAIGN hub (M6 #5 UI wiring).

The pure campaign core (game/campaign.py: state, seeding, escalation, ammo
carry-forward, resupply, JSON persistence) shipped with M6; THIS screen is the
deferred player-facing wrapper.  Three modes, decided by the App's campaign
slot + save file:

    FRESH        no campaign on disk -- SEED + BATTLES steppers, START CAMPAIGN
    IN PROGRESS  a battle ladder (grades so far), the carried ammo ledger, the
                 next battle's escalated enemy preview, START BATTLE / ABANDON
    COMPLETE     final ladder + summary, NEW CAMPAIGN / BACK

Visual language matches CombatSetupState (corner-tick panel, 40 px rows,
label-left/value-right, selected-row focus bar, press-flash before firing).
All input logic is headless; GL/text binds in enter()/render().

Wiring (main.py):
    App.open_campaign()          -- menu CAMPAIGN item; loads the save lazily
    App.start_campaign_battle()  -- START BATTLE: next_config + ammo ingest
The end overlay's CONTINUE CAMPAIGN advances + saves + returns here
(game/combat.py _campaign_continue).
"""

from __future__ import annotations

import os
from typing import Optional

import pygame

from engine.text import BODY_SIZE, HEADER_SIZE, SMALL_SIZE
from game.states import (
    ACCENT, ACCENT_DIM, BG0, BG2, DANGER, DISABLED, FOCUS_BAR_W,
    FOOTER_MARGIN, MUTED, OK_COL, PAD, PRESS_FLASH_A, PRESS_FLASH_S, ROW_H,
    TEXT_COL, WARN, GameState, draw_header_rule, draw_panel, move_selection,
)
import game.campaign as campaign
from world.combat_config import CombatConfig

# --- Layout -------------------------------------------------------------------

HUB_PANEL_W = 680
HUB_FOOTER = ("UP/DN SELECT   LT/RT ADJUST   ENTER OK   "
              "R RANDOMIZE SEED   ESC BACK")

# Fresh-mode steppers
_BATTLES_LO, _BATTLES_HI = 3, 12

# Deterministic LCG for seed randomisation (same constants as the setup
# screen: no host RNG, no wall-clock).
_LCG_A   = 1664525
_LCG_C   = 1013904223
_LCG_MOD = 2 ** 32
_SEED_MAX = 2 ** 31 - 1

# Row action labels (also the test surface)
START_CAMPAIGN = "START CAMPAIGN"
START_BATTLE   = "START BATTLE"
ABANDON        = "ABANDON CAMPAIGN"
NEW_CAMPAIGN   = "NEW CAMPAIGN"
BACK           = "BACK"

_GRADE_COLS = {"S": OK_COL, "A": OK_COL, "B": WARN, "C": DANGER, "D": DANGER}


def ladder_text(camp) -> str:
    """Pure: the grade ladder line -- one letter per finished battle, '-' for
    the battles still ahead ('S A B - - -')."""
    slots = list(camp.grades) + ["-"] * max(0, camp.n_battles - len(camp.grades))
    return " ".join(slots[: camp.n_battles])


def ledger_rows(camp, base: Optional[CombatConfig] = None) -> list:
    """Pure: (label, 'cur/cap') per carried weapon for the info block.  An
    EMPTY ledger (fresh battle 0) reads the caps themselves -- battle 0 arms
    from the config, so cap/cap is the truth."""
    base = base or CombatConfig(seed=camp.seed)
    rows = []
    for weapon, (_attr, cap_field) in campaign.WEAPONS.items():
        cap = int(getattr(base, cap_field))
        cur = int(camp.ledger.get(weapon, cap))
        rows.append((weapon.upper().replace("_", " "), f"{cur}/{cap}"))
    return rows


def next_battle_preview(camp, base: Optional[CombatConfig] = None) -> list:
    """Pure: (label, value) rows describing the UPCOMING battle's escalated
    enemy counts (what the player is about to face)."""
    cfg = campaign.next_config(camp, base)
    return [
        ("DESTROYERS", str(cfg.n_destroyers)),
        ("ENEMY RADARS", str(cfg.n_enemy_radars)),
        ("AWACS", str(cfg.n_awacs)),
        ("SEED", str(cfg.seed)),
    ]


class CampaignHubState(GameState):
    """The CAMPAIGN hub screen (see module docstring).

    ``save_path`` overrides the campaign JSON location (tests use a tmp dir;
    None = game/campaign.py default under %APPDATA%/ONIKS)."""

    def __init__(self, app, save_path: Optional[str] = None):
        super().__init__(app)
        self._gl = None
        self.text = None
        self.save_path = save_path

        # Fresh-mode editable fields
        self._seed: int = CombatConfig().seed
        self._battles: int = campaign.DEFAULT_N_BATTLES
        self._lcg_state: int = 0

        self._sel: int = 0
        self._pending: str | None = None
        self._pending_left: float = 0.0
        self._hit_rects: list = []

        # Load the save lazily on construction so the mode is right even in
        # headless tests (enter() only binds GL).
        if self.app.campaign is None:
            self.app.campaign = campaign.load(self.save_path)

    # ------------------------------------------------------------------ mode

    @property
    def camp(self):
        return self.app.campaign

    @property
    def mode(self) -> str:
        """'fresh' | 'in_progress' | 'complete'."""
        if self.camp is None:
            return "fresh"
        return "complete" if self.camp.complete else "in_progress"

    # ------------------------------------------------------------------ rows

    def _rows(self) -> list:
        m = self.mode
        if m == "fresh":
            return [
                {"kind": "stepper", "label": "SEED", "field": "seed"},
                {"kind": "stepper", "label": "BATTLES", "field": "battles"},
                {"kind": "action", "label": START_CAMPAIGN},
                {"kind": "action", "label": BACK},
            ]
        if m == "in_progress":
            return [
                {"kind": "action", "label": START_BATTLE},
                {"kind": "action", "label": ABANDON, "danger": True},
                {"kind": "action", "label": BACK},
            ]
        return [
            {"kind": "action", "label": NEW_CAMPAIGN},
            {"kind": "action", "label": BACK},
        ]

    @property
    def options(self) -> tuple:
        """The action labels for the current mode (test surface)."""
        return tuple(r["label"] for r in self._rows() if r["kind"] == "action")

    # ------------------------------------------------------------------ enter

    def enter(self) -> None:
        pygame.event.set_grab(False)
        pygame.mouse.set_visible(True)
        if self.text is None:
            import OpenGL.GL as gl
            self._gl = gl
            self.text = self.app.ui_text()
        self._sel = 0
        self._pending = None
        self._pending_left = 0.0
        self._hit_rects = []

    def effective_time_scale(self) -> float:
        return 0.0

    # ------------------------------------------------------------------ input

    def handle_event(self, ev) -> None:
        if self._pending is not None:
            return
        if ev.type == pygame.KEYDOWN:
            self._handle_key(ev.key)
        elif ev.type == pygame.MOUSEMOTION:
            hit = self._hit(ev.pos)
            if hit is not None and hit != self._sel:
                self._sel = hit
                self.app.audio.ui_click()
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            hit = self._hit(ev.pos)
            if hit is not None:
                self._sel = hit
                self._activate_current()

    def _handle_key(self, key: int) -> None:
        n = len(self._rows())
        if key == pygame.K_UP:
            self._sel = move_selection(self._sel, -1, n)
            self.app.audio.ui_click()
        elif key == pygame.K_DOWN:
            self._sel = move_selection(self._sel, 1, n)
            self.app.audio.ui_click()
        elif key == pygame.K_ESCAPE:
            self._back()
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._activate_current()
        elif key == pygame.K_LEFT:
            self._adjust(-1)
        elif key == pygame.K_RIGHT:
            self._adjust(1)
        elif key == pygame.K_r and self.mode == "fresh":
            self._lcg_state = (self._lcg_state * _LCG_A + _LCG_C) % _LCG_MOD
            self._seed = self._lcg_state & _SEED_MAX
            self.app.audio.ui_click()

    def _adjust(self, direction: int) -> None:
        row = self._rows()[self._sel]
        if row.get("kind") != "stepper":
            return
        if row["field"] == "seed":
            self._seed = max(0, min(_SEED_MAX, self._seed + direction))
        else:
            self._battles = max(_BATTLES_LO,
                                min(_BATTLES_HI, self._battles + direction))
        self.app.audio.ui_click()

    def _activate_current(self) -> None:
        row = self._rows()[self._sel]
        if row.get("kind") != "action":
            return
        self.app.audio.ui_click()
        self._pending = row["label"]
        self._pending_left = PRESS_FLASH_S

    def _tick_pending(self, dt: float) -> None:
        if self._pending is None:
            return
        self._pending_left -= dt
        if self._pending_left <= 0.0:
            name, self._pending = self._pending, None
            self._fire(name)

    def _fire(self, name: str) -> None:
        app = self.app
        if name == BACK:
            self._back()
        elif name == START_CAMPAIGN:
            app.campaign = campaign.new_campaign(self._seed, self._battles)
            campaign.save(app.campaign, self.save_path)
            app.start_campaign_battle()
        elif name == START_BATTLE:
            app.start_campaign_battle()
        elif name == ABANDON:
            self._delete_save()
            app.campaign = None
            self._sel = 0
        elif name == NEW_CAMPAIGN:
            self._delete_save()
            app.campaign = None
            self._sel = 0

    def _delete_save(self) -> None:
        path = self.save_path or campaign.default_save_path()
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass   # a locked file must never trap the player in the hub

    def _back(self) -> None:
        self.app.states.switch(self.app.menu)

    def _hit(self, pos):
        for i, (x0, y0, x1, y1) in self._hit_rects:
            if x0 <= pos[0] <= x1 and y0 <= pos[1] <= y1:
                return i
        return None

    # ------------------------------------------------------------------ render

    def render(self, dt_real: float) -> None:
        self._tick_pending(dt_real)
        gl = self._gl
        gl.glClearColor(BG0[0], BG0[1], BG0[2], 1.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        w, h = self.app.window.size()
        text = self.text
        x = (w - HUB_PANEL_W) // 2
        self._hit_rects = []

        head_lh  = text.line_height(HEADER_SIZE)
        small_lh = text.line_height(SMALL_SIZE)
        body_lh  = text.line_height(BODY_SIZE)

        # --- Header ----------------------------------------------------------
        m = self.mode
        if m == "fresh":
            sub = "NEW CAMPAIGN"
        elif m == "in_progress":
            sub = f"BATTLE {self.camp.battle_idx + 1} / {self.camp.n_battles}"
        else:
            sub = "CAMPAIGN COMPLETE"
        text.draw_text(x, 40, f"CAMPAIGN  /  {sub}", ACCENT, HEADER_SIZE)
        rule_y = 40 + head_lh + 8
        draw_header_rule(text, x, rule_y, HUB_PANEL_W)

        # --- Info block (in_progress / complete) ------------------------------
        iy = rule_y + 14
        if m != "fresh":
            camp = self.camp
            # Grade ladder
            text.draw_text(x, iy, "LADDER", MUTED, SMALL_SIZE)
            lx = x + 110
            for g in ladder_text(camp).split(" "):
                col = _GRADE_COLS.get(g, DISABLED)
                text.draw_text(lx, iy, g, col, SMALL_SIZE)
                lx += text.text_width(g, SMALL_SIZE) + 10
            iy += small_lh + 6
            # Carried ammo ledger (two columns)
            rows = ledger_rows(camp)
            col_w = HUB_PANEL_W // 2
            for i, (label, val) in enumerate(rows):
                cx = x + (i % 2) * col_w
                text.draw_text(cx, iy, label, MUTED, SMALL_SIZE)
                vw = text.text_width(val, SMALL_SIZE)
                text.draw_text(cx + col_w - vw - 24, iy, val,
                               TEXT_COL, SMALL_SIZE)
                if i % 2 == 1:
                    iy += small_lh + 2
            if len(rows) % 2 == 1:
                iy += small_lh + 2
            iy += 6
            # Upcoming battle preview (in_progress only)
            if m == "in_progress":
                text.draw_text(x, iy, "NEXT BATTLE", MUTED, SMALL_SIZE)
                iy += small_lh + 2
                for label, val in next_battle_preview(camp):
                    text.draw_text(x + 16, iy, label, MUTED, SMALL_SIZE)
                    vw = text.text_width(val, SMALL_SIZE)
                    text.draw_text(x + HUB_PANEL_W - vw, iy, val,
                                   TEXT_COL, SMALL_SIZE)
                    iy += small_lh + 2
            iy += 8

        # --- Rows panel --------------------------------------------------------
        rows = self._rows()
        panel_y = iy
        panel_h = len(rows) * ROW_H + 2 * PAD
        draw_panel(text, x, panel_y, HUB_PANEL_W, panel_h, strip=True)
        row_x = x + PAD
        row_w = HUB_PANEL_W - 2 * PAD
        ry = panel_y + PAD
        for i, row in enumerate(rows):
            selected = (i == self._sel)
            label = row["label"]
            if selected:
                col = DANGER if row.get("danger") else ACCENT
                text.draw_rect(row_x, ry, row_w, ROW_H, (*BG2, 1.0))
                text.draw_rect(row_x, ry, FOCUS_BAR_W, ROW_H, (*col, 1.0))
            if self._pending == label:
                text.draw_rect(row_x, ry, row_w, ROW_H,
                               (*ACCENT, PRESS_FLASH_A))
            ty = ry + (ROW_H - body_lh) // 2
            if row["kind"] == "stepper":
                lab_col = ACCENT if selected else MUTED
                text.draw_text(row_x + PAD, ty, label, lab_col)
                v = self._seed if row["field"] == "seed" else self._battles
                display = f"< {v} >" if selected else str(v)
                vw = text.text_width(display)
                text.draw_text(row_x + row_w - vw, ty, display,
                               TEXT_COL if selected else MUTED)
            else:
                col = (DANGER if row.get("danger") and selected
                       else ACCENT if selected else MUTED)
                tw = text.text_width(label)
                text.draw_text(row_x + (row_w - tw) // 2, ty, label, col)
            self._hit_rects.append((i, (row_x, ry, row_x + row_w,
                                        ry + ROW_H)))
            ry += ROW_H

        # --- Footer ------------------------------------------------------------
        fy = h - FOOTER_MARGIN - small_lh
        fw = text.text_width(HUB_FOOTER, SMALL_SIZE)
        text.draw_text((w - fw) // 2, fy, HUB_FOOTER, ACCENT_DIM, SMALL_SIZE)
        text.flush(w, h)
