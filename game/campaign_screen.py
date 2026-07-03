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

import dataclasses

from engine.text import BODY_SIZE, HEADER_SIZE, SMALL_SIZE
from game.states import (
    ACCENT, BG0, BG2, DANGER, DISABLED, FAINT, GRADE_COLS, GRADE_TINTS,
    LINE_COL, MUTED, OK_COL, PAD, PRESS_FILL, PRESS_FLASH_S, ROW_DIVIDER,
    ROW_H, TEXT_COL, WARN, GameState, draw_hint_bar, draw_panel,
    draw_plate_header, gauge_bar, move_selection,
)
import game.campaign as campaign
from world.combat_config import CombatConfig

# --- Layout (Wardroom Dusk, mock 05: ladder chips + ledger bars + intel) --------

HUB_CONTENT_W = 1160
GRID_GAP = 20
LADDER_CHIP = 30             # px, grade-ladder slot box size
LEDGER_LABEL_W = 130         # px, ledger weapon-name column
LEDGER_VALUE_W = 56          # px, right-aligned cur/cap column
HUB_FOOTER = ("UP/DN SELECT   LT/RT ADJUST   ENTER OK   "
              "R RANDOMIZE SEED   ESC BACK")
# HONEST carry-over caption: game/campaign.py resupplies a grade-scaled
# fraction between battles (_RESUPPLY_BY_GRADE S 60% .. D 10%) — the mock's
# 'NO RESUPPLY' placeholder copy contradicted the sim and is corrected here.
CARRY_CAPTION = "CARRY-OVER AMMO - RESUPPLY SCALES WITH GRADE"

# Ledger display names + bar family: offense = own-strike green, the SAM
# pools = amber (mock 05's two-family ledger).
_LEDGER_NAMES = {
    "oniks": "ONIKS", "zircon": "ZIRCON", "asbm": "ASBM", "kh31p": "KH-31P",
    "s300_48n6": "S-300 48N6", "s300_40n6": "S-300 40N6",
}
_LEDGER_DEFENSIVE = frozenset({"s300_48n6", "s300_40n6"})

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

def ladder_text(camp) -> str:
    """Pure: the grade ladder line -- one letter per finished battle, '-' for
    the battles still ahead ('S A B - - -')."""
    slots = list(camp.grades) + ["-"] * max(0, camp.n_battles - len(camp.grades))
    return " ".join(slots[: camp.n_battles])


def ledger_rows(camp, base: Optional[CombatConfig] = None) -> list:
    """Pure: (label, cur, cap) per carried weapon for the ammo-ledger bars.
    An EMPTY ledger (fresh battle 0) reads the caps themselves -- battle 0
    arms from the config, so cap/cap is the truth.  Labels use the display
    names (mock 05); the ints feed the 5px bar meters directly."""
    base = base or CombatConfig(seed=camp.seed)
    rows = []
    for weapon, (_attr, cap_field) in campaign.WEAPONS.items():
        cap = int(getattr(base, cap_field))
        cur = int(camp.ledger.get(weapon, cap))
        rows.append((_LEDGER_NAMES.get(weapon, weapon.upper()), cur, cap))
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


# The escalation axes the caption can name, in display order.
_ESCALATION_AXES = (
    ("DDG", "n_destroyers"), ("AAW", "n_aaw"), ("FLAGSHIP", "n_flagship"),
    ("GA", "n_ground_attack"), ("TRANSPORT", "n_transports"),
    ("SUB", "n_subs"), ("JAMMER", "n_jammers"), ("RADAR", "n_enemy_radars"),
    ("AWACS", "n_awacs"),
)


def escalation_caption(camp, base: Optional[CombatConfig] = None) -> str:
    """Pure: 'ESCALATION: +2 DDG  +1 RADAR VS BATTLE n' — the REAL delta
    between this battle's escalated counts and the previous battle's (both
    from campaign.next_config, so the caption can never drift from the sim).
    Empty for battle 0 or when nothing escalated."""
    if camp.battle_idx <= 0:
        return ""
    cur = campaign.next_config(camp, base)
    prev = campaign.next_config(
        dataclasses.replace(camp, battle_idx=camp.battle_idx - 1), base)
    parts = []
    for label, fieldname in _ESCALATION_AXES:
        d = int(getattr(cur, fieldname)) - int(getattr(prev, fieldname))
        if d > 0:
            parts.append(f"+{d} {label}")
    if not parts:
        return ""
    return "ESCALATION: " + "  ".join(parts) + f" VS BATTLE {camp.battle_idx}"


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
        x = (w - HUB_CONTENT_W) // 2
        self._hit_rects = []

        head_lh  = text.line_height(HEADER_SIZE)
        small_lh = text.line_height(SMALL_SIZE)
        body_lh  = text.line_height(BODY_SIZE)

        # --- Header (mock 05): cream 'CAMPAIGN' + dim slash + brass state ----
        m = self.mode
        if m == "fresh":
            sub = "NEW CAMPAIGN"
        elif m == "in_progress":
            sub = f"BATTLE {self.camp.battle_idx + 1} OF {self.camp.n_battles}"
        else:
            sub = "CAMPAIGN COMPLETE"
        hx = x
        text.draw_text(hx, 40, "CAMPAIGN", TEXT_COL, HEADER_SIZE)
        hx += text.text_width("CAMPAIGN", HEADER_SIZE) + 12
        text.draw_text(hx, 40, "/", DISABLED, HEADER_SIZE)
        hx += text.text_width("/", HEADER_SIZE) + 12
        text.draw_text(hx, 40, sub, ACCENT, HEADER_SIZE)

        iy = 40 + head_lh + 16
        if m != "fresh":
            iy = self._ladder_strip(x, iy, small_lh)
            col_w = (HUB_CONTENT_W - GRID_GAP) // 2
            b1 = self._ammo_plate(x, iy, col_w, small_lh)
            if m == "in_progress":
                b2 = self._intel_plate(x + col_w + GRID_GAP, iy, col_w,
                                       small_lh, body_lh)
            else:
                b2 = iy
            iy = max(b1, b2) + GRID_GAP

        # --- Rows plate: fresh-mode steppers + the action rows ----------------
        rows = self._rows()
        panel_y = iy
        panel_h = len(rows) * ROW_H + 2 * 8
        draw_panel(text, x, panel_y, HUB_CONTENT_W, panel_h, ticks=False)
        ry = panel_y + 8
        rx = x + 1
        rw = HUB_CONTENT_W - 2
        for i, row in enumerate(rows):
            selected = (i == self._sel)
            label = row["label"]
            if selected:
                col = DANGER if row.get("danger") else ACCENT
                text.draw_rect(rx, ry, rw, ROW_H, (*BG2, 1.0))
                text.draw_rect(rx, ry, 4, ROW_H, (*col, 1.0))
            if self._pending == label:
                text.draw_rect(rx, ry, rw, ROW_H, (*PRESS_FILL, 1.0))
            ty = ry + (ROW_H - body_lh) // 2
            if row["kind"] == "stepper":
                lab_col = ACCENT if selected else MUTED
                text.draw_text(rx + PAD, ty, label, lab_col)
                v = self._seed if row["field"] == "seed" else self._battles
                display = f"< {v} >" if selected else str(v)
                vw = text.text_width(display)
                text.draw_text(rx + rw - PAD - vw, ty, display,
                               ACCENT if selected else TEXT_COL)
            else:
                col = (DANGER if row.get("danger") and selected
                       else ACCENT if selected else MUTED)
                tw = text.text_width(label)
                text.draw_text(rx + (rw - tw) // 2, ty, label, col)
            self._hit_rects.append((i, (rx, ry, rx + rw, ry + ROW_H)))
            ry += ROW_H

        # --- Hint bar ----------------------------------------------------------
        draw_hint_bar(text, w, h, HUB_FOOTER)
        text.flush(w, h)

    # ------------------------------------------------------------ hub plates

    def _ladder_strip(self, x, y, small_lh) -> float:
        """The grade-ladder strip (mock 05): LADDER label, one boxed slot per
        battle (finished = family-tinted grade letter, current = brass-boxed
        battle number, ahead = hairline number), the honest carry-over
        caption right-aligned.  Returns the y below the strip."""
        text = self.text
        camp = self.camp
        strip_h = LADDER_CHIP + 2 * 13
        draw_panel(text, x, y, HUB_CONTENT_W, strip_h, ticks=False)
        text.draw_text(x + PAD, y + (strip_h - small_lh) // 2, "LADDER",
                       MUTED, SMALL_SIZE)
        cx = x + PAD + text.text_width("LADDER", SMALL_SIZE) + 24
        cy = y + (strip_h - LADDER_CHIP) // 2
        done = list(camp.grades)
        for i in range(camp.n_battles):
            if i < len(done):
                g = done[i]
                bg, border = GRADE_TINTS.get(g, (None, None))
                gcol = GRADE_COLS.get(g, TEXT_COL)
                if bg is not None:
                    text.draw_rect(cx, cy, LADDER_CHIP, LADDER_CHIP,
                                   (*bg, 1.0))
                lab = g
            elif i == camp.battle_idx and not camp.complete:
                border, gcol = ACCENT, ACCENT           # the CURRENT slot
                lab = str(i + 1)
            else:
                border, gcol = LINE_COL, DISABLED       # still ahead
                lab = str(i + 1)
            text.draw_lines([(cx, cy), (cx + LADDER_CHIP, cy),
                             (cx + LADDER_CHIP, cy + LADDER_CHIP),
                             (cx, cy + LADDER_CHIP), (cx, cy)],
                            (*(border or LINE_COL), 1.0), 1.0)
            lw = text.text_width(lab, SMALL_SIZE)
            text.draw_text(round(cx + (LADDER_CHIP - lw) / 2),
                           round(cy + (LADDER_CHIP - small_lh) / 2),
                           lab, gcol, SMALL_SIZE)
            cx += LADDER_CHIP + 8
        cap_w = text.text_width(CARRY_CAPTION, SMALL_SIZE)
        text.draw_text(x + HUB_CONTENT_W - PAD - cap_w,
                       y + (strip_h - small_lh) // 2, CARRY_CAPTION,
                       FAINT, SMALL_SIZE)
        return y + strip_h + GRID_GAP

    def _ammo_plate(self, x, y, w, small_lh) -> float:
        """AMMO LEDGER plate (mock 05): one 5px bar meter per carried weapon —
        own-strike pools fill green, the SAM pools amber; an unconfigured
        (0-cap) pool renders at 40%.  Returns the plate's bottom y."""
        text = self.text
        rows = ledger_rows(self.camp)
        # Configured pools first, unfitted (0-cap) pools sink dim to the
        # bottom (mock 05's reading order); stable within each band.
        rows.sort(key=lambda r: r[2] == 0)
        head_band = 12 + small_lh + 7
        row_h = 34
        plate_h = head_band + len(rows) * row_h + 10
        draw_panel(text, x, y, w, plate_h, ticks=False)
        draw_plate_header(text, x + PAD, y + 12, w - 2 * PAD,
                          "AMMO LEDGER", OK_COL)
        ry = y + head_band + 4
        bar_x = x + PAD + LEDGER_LABEL_W
        bar_w = w - 2 * PAD - LEDGER_LABEL_W - LEDGER_VALUE_W - 12
        for label, cur, cap in rows:
            configured = cap > 0
            a = 1.0 if configured else 0.4
            fam = WARN if label.startswith("S-300") else OK_COL
            text.draw_text(x + PAD, ry + (row_h - small_lh) // 2, label,
                           (*MUTED[:3], a), SMALL_SIZE)
            gauge_bar(text, bar_x, ry + (row_h - 5) // 2, bar_w, 5,
                      (cur / cap) if configured else 0.0, (*fam, a))
            val = f"{cur}/{cap}"
            vw = text.text_width(val, SMALL_SIZE)
            text.draw_text(x + w - PAD - vw, ry + (row_h - small_lh) // 2,
                           val, (*TEXT_COL[:3], a), SMALL_SIZE)
            ry += row_h
        return y + plate_h

    def _intel_plate(self, x, y, w, small_lh, body_lh) -> float:
        """NEXT BATTLE - INTEL plate (mock 05): the upcoming battle's
        escalated enemy counts in the hostile family, the seed in faint,
        and the derived escalation caption under a hairline.  Returns the
        plate's bottom y."""
        text = self.text
        rows = next_battle_preview(self.camp)
        cap = escalation_caption(self.camp)
        inner_w = w - 2 * PAD
        # Measured greedy wrap of the caption into <=2 lines (a heavy
        # escalation band names many axes; clipping would lie by omission).
        cap_lines = []
        if cap:
            line = ""
            for word in cap.split(" "):
                cand = (line + " " + word).strip()
                if line and text.text_width(cand, SMALL_SIZE) > inner_w:
                    cap_lines.append(line)
                    line = word
                else:
                    line = cand
            if line:
                cap_lines.append(line)
            cap_lines = cap_lines[:2]
        cap_h = (len(cap_lines) * (small_lh + 2) + 12) if cap_lines else 0
        head_band = 12 + small_lh + 7
        plate_h = head_band + len(rows) * ROW_H + cap_h + 10
        draw_panel(text, x, y, w, plate_h, ticks=False)
        draw_plate_header(text, x + PAD, y + 12, w - 2 * PAD,
                          "NEXT BATTLE - INTEL", DANGER)
        ry = y + head_band
        for i, (label, val) in enumerate(rows):
            if i:
                text.draw_lines([(x + PAD, ry), (x + w - PAD, ry)],
                                (*ROW_DIVIDER, 1.0), 1.0)
            ty = ry + (ROW_H - body_lh) // 2
            text.draw_text(x + PAD, ty, label, MUTED)
            vcol = FAINT if label == "SEED" else DANGER
            vw = text.text_width(val)
            text.draw_text(x + w - PAD - vw, ty, val, vcol)
            ry += ROW_H
        if cap_lines:
            text.draw_lines([(x + PAD, ry + 2), (x + w - PAD, ry + 2)],
                            (*LINE_COL, 1.0), 1.0)
            cy = ry + 8
            for ln in cap_lines:
                text.draw_text(x + PAD, cy, ln, FAINT, SMALL_SIZE)
                cy += small_lh + 2
        return y + plate_h
