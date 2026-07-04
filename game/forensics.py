"""FORENSICS / SHOT DEBRIEF — the after-action ledger screen.

Implements the APPROVED mock ``Assets of oinks/ui_prototypes/
ledger2_final_debrief.html`` (render: .../renders/ledger2_final_debrief.png):
a light paper sheet on the dark desk, counter row, clickable round stubs, and
the two 1:1 plots.

ACCURACY CONTRACT (user-locked): both plots are polylines drawn DIRECTLY from
``CombatState.flight_recorder.path_of(rec)`` samples — no smoothing, no
interpolation, no schematic shapes.  Side view: altitude x cumulative ground
distance (running sum of hypot(dx, dz)); top-down: the same samples' x/z at
UNIFORM scale.  Square ticks mark every 8th sample; the death anchor sits at
the exact recorded death position; a dashed planned-remainder runs to the
recorded aim point when the round died short.

FOG DISPLAY GATE (user-locked): mid-battle the sheet names a killer ONLY when
the cause channel recorded observed=True (the killer was itself a track at
kill time); otherwise it shows LOST - UNCONFIRMED.  Post-battle everything
may be named but an unobserved attribution is flagged RECONSTRUCTED.

THE SIM NEVER PAUSES under this screen (tactical-map pattern: an overlay the
state renders instead of the HUD; sim_step continues untouched).  The live
T+ clock chip + inbound count prove it to the player.

BLACK BOX / SENSORS tabs and the sensor-lane strip are NOT visually approved
yet: they render as "AWAITING DESIGN" placeholders — deliberately undesigned.

Engine constraints honored: ASCII-only monospace atlas, font sizes 14/18/28
only, flat rects + thin draw_lines polylines, no rounded corners.  GL touches
happen only inside draw(); the module imports headless (pure helpers are
unit-tested in tests/test_forensics_pure.py).
"""

from __future__ import annotations

import math

import numpy as np
import pygame

from engine.text import BODY_SIZE, HEADER_SIZE, SMALL_SIZE
from game.states import (
    HINT_BAR_BG, HINT_COL, INK_AMBER, INK_GREEN, INK_RED, INK_TEAL,
    PAPER_BG, PAPER_CHIP_BG, PAPER_CHIP_EDGE, PAPER_CHIP_MUTED,
    PAPER_CHIP_TEXT, PAPER_DESK, PAPER_DESK_EDGE, PAPER_FIELD, PAPER_HATCH,
    PAPER_HEADLINE, PAPER_INK, PAPER_MUTED, PAPER_SELECT, PAPER_TAG,
)

# ------------------------------------------------------------------ display maps

# Stub prefixes for the round kinds the player can fire; anything else falls
# back to the first three characters upper-cased (48n6 -> 48N).
_KIND_PREFIX = {"oniks": "ONX", "zircon": "ZRC"}

# Hull-classification codes for hit/ciws details (ship_type -> ledger code).
_SHIP_CODES = {"destroyer": "DDG", "carrier": "CV", "frigate": "FFG",
               "cargo": "AK", "transport": "AK", "lcac": "LCAC"}

# Interceptor display names (weapon_id -> ledger name).
_WEAPON_NAMES = {"sm2": "SM-2", "sm6": "SM-6", "aim9x": "AIM-9X",
                 "48n6": "48N6", "40n6": "40N6", "57e6": "57E6",
                 "9m317": "9M317"}

# Paper inks by semantic key (the pure helpers return keys, not colors,
# so the display logic stays testable headless).
_INKS = {"ink": PAPER_INK, "muted": PAPER_MUTED, "red": INK_RED,
         "teal": INK_TEAL, "amber": INK_AMBER, "green": INK_GREEN}

# Interceptor cause codes (the counter row's INTERCEPTED bucket).
_INTERCEPT_CODES = ("sam", "a2a", "ciws", "pantsir")

# Phase labels that get an event pin on the side plot (the early launch
# phases all sit within the first km and would stack at the origin).
_PIN_LABELS = ("CRUISE", "DESCENT", "TERMINAL")


# ------------------------------------------------------------------ pure helpers

def stub_id(rec) -> str:
    """Ledger id for a record: ONX-3 / ZRC-1 / 48N-2."""
    kind = str(rec["kind"])
    prefix = _KIND_PREFIX.get(kind, kind[:3].upper())
    return f"{prefix}-{rec['seq']}"


def _ship_code(detail) -> str:
    return _SHIP_CODES.get(str(detail), str(detail).upper()[:4] or "SHIP")


def _weapon_name(detail) -> str:
    return _WEAPON_NAMES.get(str(detail), str(detail).upper())


def tally(recs, battle_over: bool = True) -> dict:
    """The counter row, derived from recorder causes only (no invented
    numbers): fired / hit / intercepted / other loss / observed /
    unconfirmed.  Live rounds count only toward FIRED.

    FOG: mid-battle (``battle_over=False``) an UNOBSERVED loss counts only
    toward FIRED + UNCONFIRMED — classifying it as INTERCEPTED while its
    own stub reads "LOST?" leaked the loss CLASS before the sensors
    justified it.  Post-battle everything is classified (the default, so
    every existing caller/test is byte-identical)."""
    t = {"fired": len(recs), "hit": 0, "intercepted": 0, "other": 0,
         "observed": 0, "unconfirmed": 0}
    for rec in recs:
        cause = rec.get("cause")
        if cause is None:
            continue
        code = cause["code"]
        if code == "hit":
            t["hit"] += 1
        elif battle_over or cause["observed"]:
            if code in _INTERCEPT_CODES:
                t["intercepted"] += 1
            else:
                t["other"] += 1
        if cause["observed"]:
            t["observed"] += 1
        else:
            t["unconfirmed"] += 1
    return t


def stub_status(cause, battle_over: bool) -> tuple:
    """(text, ink_key) for a round stub.  THE FOG GATE lives here: an
    unobserved killer is never named mid-battle; post-battle it is named
    with a '?' reconstruction flag."""
    if cause is None:
        return ("IN AIR", "teal")
    code, detail, observed = cause["code"], cause["detail"], cause["observed"]
    if code == "hit":
        label = _ship_code(detail) if detail else "TGT"
        return (f"HIT {label}", "green")
    if code in _INTERCEPT_CODES:
        if not observed and not battle_over:
            return ("LOST?", "muted")
        name = ("CIWS" if code == "ciws" else "GUN" if code == "pantsir"
                else _weapon_name(detail) if detail else "INT")
        flag = "?" if not observed else ""
        return (f"{name} X{flag}", "red")
    if code == "fuel":
        return ("FUEL", "amber")
    if code == "impact":
        return ("SPLASH", "muted")
    return ("LOST?", "muted")


def cause_headline(cause, battle_over: bool) -> str:
    """The finding line for the selected round (right column)."""
    if cause is None:
        return "IN FLIGHT"
    code, detail, observed = cause["code"], cause["detail"], cause["observed"]
    if code == "hit":
        return f"TARGET HIT - {_ship_code(detail)}" if detail \
            else "TARGET HIT"
    if code in _INTERCEPT_CODES:
        if code == "ciws":
            name = "CIWS" + (f" ({_ship_code(detail)})" if detail else "")
        elif code == "pantsir":
            name = "PANTSIR GUN"
        else:
            name = _weapon_name(detail) if detail else "INTERCEPTOR"
        if observed:
            return f"KILLED BY {name} - OBSERVED"
        if battle_over:
            return f"KILLED BY {name} - RECONSTRUCTED (NOT OBSERVED)"
        return "LOST - UNCONFIRMED"
    if code == "fuel":
        return "FUEL EXHAUSTED"
    if code == "impact":
        return "SURFACE IMPACT"
    return "LOST - UNCONFIRMED"


def cumulative_ground_km(path: np.ndarray) -> np.ndarray:
    """Running ground distance (km) per sample — the side plot's x axis.
    1:1 from the samples: sum of hypot(dx, dz) legs; altitude never leaks
    into distance.  path is the recorder's (N, 4) (t, x, y, z)."""
    if len(path) == 0:
        return np.zeros(0)
    dx = np.diff(path[:, 1])
    dz = np.diff(path[:, 3])
    legs = np.hypot(dx, dz)
    return np.concatenate(([0.0], np.cumsum(legs))) / 1_000.0


def fmt_clock(t: float) -> str:
    t = max(0.0, float(t))
    return f"T+{int(t // 60):02d}:{int(t % 60):02d}"


# ------------------------------------------------------------------ the screen

_TABS = ("LEDGER", "BLACK BOX", "SENSORS")
_STUB_CAP = 14              # stubs drawn before the +N MORE spill marker

_FOOT_HINT = ("CLICK STUB - RETYPE   UP/DN LEAF   1/2/3 VIEW   "
              "J/ESC BACK - SIM DOES NOT PAUSE")


class ForensicsScreen:
    """The ledger overlay owned by CombatState (GL only inside draw)."""

    def __init__(self, state):
        self.state = state              # CombatState: recorder, world, text
        self.selected = 0
        self.tab = 0
        self._stub_rects: list = []     # (index, x0, y0, x1, y1)
        self._tab_rects: list = []

    # ------------------------------------------------------------- helpers

    def _recs(self) -> list:
        return self.state.flight_recorder.rounds()

    def _battle_over(self) -> bool:
        return getattr(self.state, "_end_overlay", None) is not None

    def close(self) -> None:
        self.state.forensics_open = False

    # --------------------------------------------------------------- input

    def handle_event(self, ev) -> bool:
        """True = consumed.  F1/F2 (overlay/screenshot) pass through; every
        other input is the sheet's while it is open (keyboard path for every
        mouse affordance: UP/DN leaf stubs, 1/2/3 tabs, J/ESC close)."""
        if ev.type == pygame.KEYDOWN:
            key = ev.key
            if key in (pygame.K_F1, pygame.K_F2):
                return False            # reserved: controls overlay/shot
            app = self.state.app
            if key == pygame.K_ESCAPE or app.keybinds.matches("forensics",
                                                              key):
                self.close()
                app.audio.ui_click()
                return True
            n = len(self._recs())
            if key in (pygame.K_UP, pygame.K_LEFT):
                if n:
                    self.selected = (self.selected - 1) % n
                    app.audio.ui_click()
                return True
            if key in (pygame.K_DOWN, pygame.K_RIGHT):
                if n:
                    self.selected = (self.selected + 1) % n
                    app.audio.ui_click()
                return True
            if key in (pygame.K_1, pygame.K_KP1):
                self.tab = 0
                app.audio.ui_click()
                return True
            if key in (pygame.K_2, pygame.K_KP2):
                self.tab = 1
                app.audio.ui_click()
                return True
            if key in (pygame.K_3, pygame.K_KP3):
                self.tab = 2
                app.audio.ui_click()
                return True
            return True                 # the sheet owns the keyboard
        if ev.type == pygame.MOUSEWHEEL:
            n = len(self._recs())
            if n and ev.y:
                self.selected = (self.selected - (1 if ev.y > 0 else -1)) % n
                self.state.app.audio.ui_click()
            return True
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            for i, x0, y0, x1, y1 in self._stub_rects:
                if x0 <= ev.pos[0] <= x1 and y0 <= ev.pos[1] <= y1:
                    self.selected = i
                    self.state.app.audio.ui_click()
                    return True
            for i, x0, y0, x1, y1 in self._tab_rects:
                if x0 <= ev.pos[0] <= x1 and y0 <= ev.pos[1] <= y1:
                    self.tab = i
                    self.state.app.audio.ui_click()
                    return True
            return True
        if ev.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
            return True
        return False

    # ---------------------------------------------------------------- draw

    def draw(self, w: int, h: int) -> None:
        text = self.state.text
        self._stub_rects = []
        self._tab_rects = []

        # Desk: flat field + darker edge bands (no gradients in this engine).
        text.draw_rect(0, 0, w, h, (*PAPER_DESK, 1.0))
        edge = int(h * 0.09)
        text.draw_rect(0, 0, w, edge, (*PAPER_DESK_EDGE, 0.55))
        text.draw_rect(0, h - edge, w, edge, (*PAPER_DESK_EDGE, 0.55))

        # Desk header + the live no-pause proof chip.
        text.draw_text(int(w * 0.021), int(h * 0.02),
                       "FORENSICS / SHOT DEBRIEF - LEDGER",
                       PAPER_HEADLINE, SMALL_SIZE)
        self._clock_chip(text, w, h)

        # The paper sheet.
        px = int(w * 0.0573)
        py = int(h * 0.048)
        pw = w - 2 * px
        ph = h - py - int(h * 0.052)
        text.draw_rect(px, py, pw, ph, (*PAPER_BG, 1.0))

        pad = max(18, int(pw * 0.021))
        x0 = px + pad
        y = py + int(pad * 0.62)
        inner_w = pw - 2 * pad

        recs = self._recs()
        battle_over = self._battle_over()
        if recs:
            self.selected = max(0, min(self.selected, len(recs) - 1))

        # Masthead + double rule.
        text.draw_text(x0, y, "SHOT DEBRIEF - AFTER-ACTION LEDGER",
                       PAPER_INK, HEADER_SIZE)
        state_note = ("ENGAGEMENT ENDED - UNOBSERVED KILLS FLAGGED "
                      "RECONSTRUCTED" if battle_over else
                      "ENGAGEMENT IN PROGRESS - ONLY SENSOR-OBSERVED KILLS "
                      "ARE NAMED")
        sheet_note = (f"SHEET {self.selected + 1} / {len(recs)} - "
                      if recs else "")
        note = sheet_note + state_note
        nw = text.text_width(note, SMALL_SIZE)
        text.draw_text(x0 + inner_w - nw,
                       y + text.line_height(HEADER_SIZE)
                       - text.line_height(SMALL_SIZE) - 2,
                       note, PAPER_MUTED, SMALL_SIZE)
        y += text.line_height(HEADER_SIZE) + 6
        text.draw_rect(x0, y, inner_w, 1, (*PAPER_INK, 1.0))
        text.draw_rect(x0, y + 3, inner_w, 1, (*PAPER_INK, 1.0))
        y += 12

        # Counter row + clerk's note (derived numbers only).
        y = self._counter_row(text, x0, y, inner_w, recs, battle_over)

        # Stub row.
        y = self._stub_row(text, x0, y, inner_w, recs, battle_over)

        if not recs:
            msg = "NO ROUNDS RECORDED YET - FIRE SOMETHING"
            mw = text.text_width(msg, BODY_SIZE)
            text.draw_text(x0 + (inner_w - mw) * 0.5, y + int(ph * 0.28),
                           msg, PAPER_MUTED, BODY_SIZE)
            self._foot(text, x0, py, ph, inner_w, recs)
            self._hint_bar(text, w, h)
            text.flush(w, h)
            return

        rec = recs[self.selected]
        path = self.state.flight_recorder.path_of(rec)

        # Side-view hero plot.
        sid = stub_id(rec)
        text.draw_text(x0, y, f"{sid} - RECORDED FLIGHT PATH - SIDE VIEW, "
                              f"PLOTTED 1:1 FROM THE PATH RECORDER "
                              f"(SQUARE TICKS = SAMPLES)",
                       PAPER_MUTED, SMALL_SIZE)
        y += text.line_height(SMALL_SIZE) + 4
        plot_h = int(ph * 0.30)
        self._side_plot(text, x0, y, inner_w, plot_h, rec, path, battle_over)
        y += plot_h + 12

        # Bottom row: top-down (left) + tabs/finding (right).
        bottom_h = py + ph - y - int(pad * 1.7)
        map_w = int(inner_w * 0.52)
        self._top_down(text, x0, y, map_w, bottom_h, rec, path)
        rx = x0 + map_w + pad
        self._right_column(text, rx, y, x0 + inner_w - rx, bottom_h, recs,
                           rec, battle_over)

        self._foot(text, x0, py, ph, inner_w, recs)
        self._hint_bar(text, w, h)
        text.flush(w, h)

    # ------------------------------------------------------------ chrome bits

    def _clock_chip(self, text, w: int, h: int) -> None:
        world = self.state.world
        clock = fmt_clock(getattr(world, "sim_time", 0.0))
        inbound = self._inbound_count(world)
        tail = f" - SIM RUNNING - INBOUND {inbound}"
        cw = text.text_width(clock, BODY_SIZE)
        tw = text.text_width(tail, BODY_SIZE)
        lh = text.line_height(BODY_SIZE)
        bx = w - int(w * 0.021) - (cw + tw) - 32
        by = int(h * 0.014)
        bw = cw + tw + 32
        bh = lh + 14
        text.draw_rect(bx, by, bw, bh, (*PAPER_CHIP_BG, 1.0))
        self._rect_border(text, bx, by, bw, bh, (*PAPER_CHIP_EDGE, 1.0), 1.0)
        text.draw_text(bx + 16, by + 7, clock, PAPER_CHIP_TEXT, BODY_SIZE)
        text.draw_text(bx + 16 + cw, by + 7, tail, PAPER_CHIP_MUTED,
                       BODY_SIZE)

    @staticmethod
    def _inbound_count(world) -> int:
        """Hostile rounds ON THE PLAYER PICTURE (fog-honest: counts missile-
        class air tracks in world.contacts.tracks, never truth)."""
        contacts = getattr(world, "contacts", None)
        tracks = getattr(contacts, "tracks", None) or {}
        return sum(1 for trk in tracks.values()
                   if trk.get("is_air") and trk.get("size") == "missile")

    def _hint_bar(self, text, w: int, h: int) -> None:
        lh = text.line_height(SMALL_SIZE)
        hw = text.text_width(_FOOT_HINT, SMALL_SIZE)
        hy = h - lh - 10
        text.draw_rect(0, hy - 6, w, lh + 16, (*HINT_BAR_BG, 0.88))
        text.draw_text((w - hw) * 0.5, hy, _FOOT_HINT, HINT_COL, SMALL_SIZE)

    def _foot(self, text, x0, py, ph, inner_w, recs) -> None:
        line = (f"SHEET {self.selected + 1} OF {len(recs)} - UP/DN LEAFS "
                f"THE LEDGER - ALL PLOTS 1:1 FROM RECORDED SAMPLES"
                if recs else "THE LEDGER FILES ONE SHEET PER ROUND FIRED")
        lh = self.state.text.line_height(SMALL_SIZE)
        text.draw_text(x0, py + ph - lh - 10, line, PAPER_MUTED, SMALL_SIZE)

    # ------------------------------------------------------------- counters

    def _counter_row(self, text, x0, y, inner_w, recs,
                     battle_over: bool = True) -> int:
        t = tally(recs, battle_over)
        boxes = (("FIRED", t["fired"], PAPER_INK, PAPER_INK),
                 ("HIT", t["hit"], INK_GREEN, INK_GREEN),
                 ("INTERCEPTED", t["intercepted"], INK_RED, INK_RED),
                 ("OTHER LOSS", t["other"], PAPER_INK, PAPER_MUTED),
                 ("OBSERVED", t["observed"], INK_GREEN, INK_GREEN),
                 ("UNCONFIRMED", t["unconfirmed"], PAPER_MUTED, PAPER_MUTED))
        bw = min(150, int(inner_w * 0.088))
        bh = (text.line_height(HEADER_SIZE) + text.line_height(SMALL_SIZE)
              + 12)
        gap = 14
        for i, (label, value, border, ink) in enumerate(boxes):
            bx = x0 + i * (bw + gap)
            dashed = label == "UNCONFIRMED"
            self._rect_border(text, bx, y, bw, bh, (*border, 1.0), 2.0,
                              dashed=dashed)
            v = str(value)
            vw = text.text_width(v, HEADER_SIZE)
            text.draw_text(bx + (bw - vw) * 0.5, y + 5, v, ink, HEADER_SIZE)
            lw = text.text_width(label, SMALL_SIZE)
            text.draw_text(bx + (bw - lw) * 0.5,
                           y + 7 + text.line_height(HEADER_SIZE), label,
                           PAPER_MUTED, SMALL_SIZE)
        # Clerk's note: derived facts only (no invented analysis — the sim
        # does not produce tactical advice).
        nx = x0 + 6 * (bw + gap) + 6
        if nx < x0 + inner_w - 260:
            text.draw_text(nx, y, "CLERK'S NOTE", PAPER_MUTED, SMALL_SIZE)
            lh = text.line_height(SMALL_SIZE)
            line1 = (f"{t['hit']} HIT / {t['intercepted']} INTERCEPTED / "
                     f"{t['other']} OTHER LOSS OF {t['fired']} FIRED.")
            line2 = (f"{t['unconfirmed']} LOSS(ES) UNCONFIRMED - KILLER NOT "
                     f"ON THE PICTURE AT LOSS TIME."
                     if t["unconfirmed"] else
                     "EVERY CLOSED SHEET IS SENSOR-OBSERVED.")
            text.draw_text(nx, y + lh + 4, line1, PAPER_INK, SMALL_SIZE)
            text.draw_text(nx, y + 2 * lh + 8, line2, PAPER_INK, SMALL_SIZE)
        return y + bh + 10

    # ------------------------------------------------------------ stub row

    def _stub_row(self, text, x0, y, inner_w, recs, battle_over) -> int:
        lh = text.line_height(SMALL_SIZE)
        bh = lh + 10
        if not recs:
            return y + 4
        shown = recs[:_STUB_CAP]
        gap = 7
        bw = (inner_w - gap * (len(shown) - 0)) / max(len(shown), 8)
        ink_border = {"green": INK_GREEN, "red": INK_RED, "amber": INK_AMBER,
                      "teal": INK_TEAL, "muted": PAPER_MUTED,
                      "ink": PAPER_INK}
        for i, rec in enumerate(shown):
            bx = x0 + i * (bw + gap)
            status, ink_key = stub_status(rec.get("cause"), battle_over)
            col = ink_border[ink_key]
            selected = i == self.selected
            if selected:
                text.draw_rect(bx, y, bw, bh, (*PAPER_SELECT, 1.0))
                self._rect_border(text, bx, y, bw, bh, (*PAPER_INK, 1.0),
                                  3.0)
            else:
                self._rect_border(text, bx, y, bw, bh, (*col, 1.0), 1.0,
                                  dashed=ink_key == "muted")
            sid = stub_id(rec)
            label = f"{sid} {status}" + (" <" if selected else "")
            # Clip by dropping the status first if the box is narrow.
            if text.text_width(label, SMALL_SIZE) > bw - 10:
                label = sid + (" <" if selected else "")
            text.draw_text(bx + 6, y + 5, label,
                           _INKS[ink_key] if not selected else PAPER_INK,
                           SMALL_SIZE)
            self._stub_rects.append((i, bx, y, bx + bw, y + bh))
        if len(recs) > _STUB_CAP:
            text.draw_text(x0 + inner_w - 90, y + 5,
                           f"+{len(recs) - _STUB_CAP} MORE", PAPER_MUTED,
                           SMALL_SIZE)
        y += bh + 4
        text.draw_text(x0, y, "CLICK A STUB - THE SHEET RETYPES FOR THAT "
                              "ROUND", PAPER_MUTED, SMALL_SIZE)
        return y + lh + 6

    # ------------------------------------------------------------ side plot

    def _side_plot(self, text, x0, y0, pw, ph, rec, path,
                   battle_over) -> None:
        text.draw_rect(x0, y0, pw, ph, (*PAPER_FIELD, 1.0))
        self._rect_border(text, x0, y0, pw, ph, (*PAPER_INK, 1.0), 2.0)
        if len(path) < 2:
            text.draw_text(x0 + 12, y0 + 10, "AWAITING SAMPLES...",
                           PAPER_MUTED, SMALL_SIZE)
            return
        lh = text.line_height(SMALL_SIZE)
        ml, mr, mt, mb = 78, 26, 26, 34         # plot margins
        gx0, gy0 = x0 + ml, y0 + mt             # graph origin (top-left)
        gw, gh = pw - ml - mr, ph - mt - mb

        km = cumulative_ground_km(path)
        alt = path[:, 2]
        dist_end = float(km[-1])

        # Planned remainder: ground distance still to run to the aim point.
        rem_km = 0.0
        target_xz = rec.get("target_xz")
        died_short = (rec.get("death") is not None
                      and rec.get("cause") is not None
                      and rec["cause"]["code"] != "hit")
        if died_short and target_xz is not None:
            dxt = target_xz[0] - path[-1, 1]
            dzt = target_xz[1] - path[-1, 3]
            rem_km = math.hypot(dxt, dzt) / 1_000.0

        x_max = max(25.0, math.ceil((dist_end + rem_km) / 25.0) * 25.0)
        y_max = max(2_500.0, math.ceil(float(alt.max()) / 2_500.0) * 2_500.0)

        def X(d_km):
            return gx0 + d_km / x_max * gw

        def Y(a_m):
            return gy0 + gh - max(0.0, a_m) / y_max * gh

        # Grid + real axes.
        n_y = int(y_max / 2_500.0)
        for i in range(n_y + 1):
            a = i * 2_500.0
            yy = Y(a)
            text.draw_rect(gx0, yy, gw, 1, (*INK_TEAL, 0.22))
            label = f"{int(a):,} M"
            text.draw_text(x0 + 6, yy - lh * 0.5, label, PAPER_MUTED,
                           SMALL_SIZE)
        k = 0.0
        while k <= x_max + 1e-9:
            xx = X(k)
            text.draw_rect(xx, gy0, 1, gh, (*INK_TEAL, 0.18))
            text.draw_text(xx - 10, y0 + ph - mb + 6, f"{int(k)} KM",
                           PAPER_MUTED, SMALL_SIZE)
            k += 25.0

        # Ground line + hatch residue.
        gy = Y(0.0)
        text.draw_rect(gx0, gy, gw, 2, (*PAPER_INK, 1.0))
        hx = gx0
        while hx < gx0 + gw - 8:
            text.draw_rect(hx, gy + 3, 8, 10, (*INK_AMBER, 0.25))
            text.draw_rect(hx + 8, gy + 3, 8, 10, (*INK_AMBER, 0.12))
            hx += 16

        # TEL origin marker.
        text.draw_rect(gx0 - 8, gy - 10, 16, 10, (*INK_GREEN, 1.0))
        text.draw_text(gx0 - 14, gy + 15, "TEL", INK_GREEN, SMALL_SIZE)

        # THE 1:1 POLYLINE — direct from samples, no smoothing.
        pts = [(X(km[i]), Y(alt[i])) for i in range(len(km))]
        text.draw_lines(pts, (*INK_TEAL, 1.0), 2.0)
        for i in range(0, len(pts), 8):         # square ticks = samples
            sx, sy = pts[i]
            text.draw_rect(sx - 2.5, sy - 2.5, 5, 5, (*INK_TEAL, 1.0))

        plot_bounds = (x0 + 3, y0 + 3, x0 + pw - 3, y0 + ph - 3)

        # Launch pin.
        self._pin(text, pts[0][0], pts[0][1],
                  f"LAUNCH {fmt_clock(rec['launch_t'])}", PAPER_INK, up=40,
                  bounds=plot_bounds)

        # Phase-event pins (the recorder's own phase_label transitions).
        t_col = path[:, 0]
        stagger = 0
        for ev_t, label in rec.get("events", ()):
            if label not in _PIN_LABELS:
                continue
            i = int(np.searchsorted(t_col, ev_t - 1e-9))
            i = min(i, len(pts) - 1)
            tag = f"{label} {fmt_clock(ev_t)}"
            if label == "CRUISE":
                tag = f"CRUISE {int(round(alt[i])):,} M"
            self._pin(text, pts[i][0], pts[i][1], tag, PAPER_INK,
                      up=54 + stagger, bounds=plot_bounds)
            stagger = (stagger + 26) % 78

        # Death anchor + flag / or the hit end.
        death = rec.get("death")
        cause = rec.get("cause")
        if death is not None and cause is not None:
            dxp, dyp = pts[-1]
            status, ink_key = stub_status(cause, battle_over)
            col = _INKS["red"] if ink_key == "red" else _INKS[ink_key]
            extra = (f" - {int(round(rem_km))} KM SHORT" if rem_km > 0.5
                     else "")
            when = fmt_clock(death["t"])
            if cause["code"] == "hit":
                flag = f"HIT {when} - {status}"
            elif status == "LOST?":             # fog-gated: no killer named
                flag = f"LOST {when} - UNCONFIRMED{extra}"
            else:
                flag = f"LOST {when} - {status}{extra}"
            self._x_anchor(text, dxp, dyp, col)
            self._pin(text, dxp, dyp, flag, col, up=110, anchor_gap=20,
                      bounds=plot_bounds)

        # Dashed planned remainder to the aim point (died short only).
        if rem_km > 0.5:
            self._dashed(text, pts[-1][0], gy, X(dist_end + rem_km), gy,
                         (*PAPER_HATCH, 1.0), 2.0)
            tx = X(dist_end + rem_km)
            self._diamond(text, tx, gy - 6, 7, (*INK_RED, 1.0))
            text.draw_text(min(tx - 30, x0 + pw - 96), gy - 6 - 2 * lh - 8,
                           "AIM POINT", INK_RED, SMALL_SIZE)
            text.draw_text(min(tx - 30, x0 + pw - 96), gy - 6 - lh - 6,
                           "NOT REACHED", INK_RED, SMALL_SIZE)

    # ------------------------------------------------------------- top-down

    def _top_down(self, text, x0, y0, pw, ph, rec, path) -> None:
        text.draw_text(x0, y0, "TOP-DOWN - GROUND TRACK PLOTTED 1:1 FROM "
                               "THE SAME SAMPLES - UNIFORM SCALE",
                       PAPER_MUTED, SMALL_SIZE)
        lh = text.line_height(SMALL_SIZE)
        fy = y0 + lh + 4
        fh = ph - lh - 4
        text.draw_rect(x0, fy, pw, fh, (*PAPER_FIELD, 1.0))
        self._rect_border(text, x0, fy, pw, fh, (*PAPER_INK, 1.0), 2.0)
        if len(path) < 2 or fh < 60:
            return

        xs = path[:, 1]
        zs = path[:, 3]
        pts_w = [(float(x), float(z)) for x, z in zip(xs, zs)]
        extra = []
        target_xz = rec.get("target_xz")
        if target_xz is not None:
            extra.append((float(target_xz[0]), float(target_xz[1])))
        all_pts = pts_w + extra
        min_x = min(p[0] for p in all_pts)
        max_x = max(p[0] for p in all_pts)
        min_z = min(p[1] for p in all_pts)
        max_z = max(p[1] for p in all_pts)
        span_x = max(max_x - min_x, 1_000.0)
        span_z = max(max_z - min_z, 1_000.0)
        margin = 26
        # UNIFORM scale (the contract): one px/m for both axes.
        scale = min((pw - 2 * margin) / span_x, (fh - 2 * margin) / span_z)
        cx = (min_x + max_x) * 0.5
        cz = (min_z + max_z) * 0.5

        def PX(wx):
            return x0 + pw * 0.5 + (wx - cx) * scale

        def PZ(wz):
            return fy + fh * 0.5 - (wz - cz) * scale

        # 25 km world grid at the same uniform scale.
        grid = 25_000.0
        gx = math.floor((cx - pw / scale) / grid) * grid
        while gx < cx + pw / scale:
            sx = PX(gx)
            if x0 + 2 < sx < x0 + pw - 2:
                text.draw_rect(sx, fy + 2, 1, fh - 4, (*INK_TEAL, 0.14))
            gx += grid
        gz = math.floor((cz - fh / scale) / grid) * grid
        while gz < cz + fh / scale:
            sz = PZ(gz)
            if fy + 2 < sz < fy + fh - 2:
                text.draw_rect(x0 + 2, sz, pw - 4, 1, (*INK_TEAL, 0.14))
            gz += grid

        # The 1:1 track + sample ticks.
        pts = [(PX(px_), PZ(pz_)) for px_, pz_ in pts_w]
        text.draw_lines(pts, (*PAPER_INK, 1.0), 2.0)
        for i in range(0, len(pts), 8):
            sx, sy = pts[i]
            text.draw_rect(sx - 2.5, sy - 2.5, 5, 5, (*PAPER_INK, 1.0))

        # Launch square (green) + event number boxes + death X + aim point.
        text.draw_rect(pts[0][0] - 4, pts[0][1] - 4, 8, 8, (*INK_GREEN, 1.0))
        text.draw_text(pts[0][0] + 7, pts[0][1] - 4, "TEL", INK_GREEN,
                       SMALL_SIZE)
        t_col = path[:, 0]
        n_ev = 0
        for ev_t, label in rec.get("events", ()):
            if label not in _PIN_LABELS:
                continue
            n_ev += 1
            i = min(int(np.searchsorted(t_col, ev_t - 1e-9)), len(pts) - 1)
            bx, by = pts[i][0] - 9, pts[i][1] - 22
            text.draw_rect(bx, by, 18, 18, (*PAPER_TAG, 1.0))
            self._rect_border(text, bx, by, 18, 18, (*PAPER_INK, 1.0), 1.0)
            text.draw_text(bx + 5, by + 2, str(n_ev), PAPER_INK, SMALL_SIZE)
        cause = rec.get("cause")
        if rec.get("death") is not None and cause is not None:
            col = (INK_GREEN if cause["code"] == "hit" else INK_RED)
            self._x_anchor(text, pts[-1][0], pts[-1][1], col)
        if target_xz is not None and cause is not None \
                and cause["code"] != "hit":
            tx, tz = PX(target_xz[0]), PZ(target_xz[1])
            self._dashed(text, pts[-1][0], pts[-1][1], tx, tz,
                         (*PAPER_HATCH, 1.0), 1.5)
            self._diamond(text, tx, tz, 7, (*INK_RED, 1.0))

        cap = (f"UNIFORM SCALE {scale * 1_000.0:.1f} PX/KM - GRID 25 KM - "
               f"SQUARE TICKS = SAMPLES")
        cw = text.text_width(cap, SMALL_SIZE)
        text.draw_text(x0 + pw - cw - 8, fy + fh - lh - 6, cap, PAPER_MUTED,
                       SMALL_SIZE)

    # --------------------------------------------------------- right column

    def _right_column(self, text, x0, y0, pw, ph, recs, rec,
                      battle_over) -> None:
        lh = text.line_height(SMALL_SIZE)
        blh = text.line_height(BODY_SIZE)
        # Tab strip (BLACK BOX / SENSORS: present, deliberately undesigned).
        tx = x0
        for i, label in enumerate(_TABS):
            tw = text.text_width(label, SMALL_SIZE)
            active = i == self.tab
            col = PAPER_INK if active else PAPER_MUTED
            text.draw_text(tx, y0, f"[{i + 1}] {label}", col, SMALL_SIZE)
            full_w = text.text_width(f"[{i + 1}] {label}", SMALL_SIZE)
            if active:
                text.draw_rect(tx, y0 + lh + 1, full_w, 2, (*PAPER_INK, 1.0))
            self._tab_rects.append((i, tx, y0, tx + full_w, y0 + lh + 3))
            tx += full_w + 22
        y = y0 + lh + 12

        if self.tab != 0:
            box_h = ph - (y - y0) - 8
            self._rect_border(text, x0, y, pw, box_h, (*PAPER_MUTED, 1.0),
                              1.0, dashed=True)
            msg = "AWAITING DESIGN"
            mw = text.text_width(msg, BODY_SIZE)
            text.draw_text(x0 + (pw - mw) * 0.5, y + box_h * 0.42, msg,
                           PAPER_MUTED, BODY_SIZE)
            sub = f"{_TABS[self.tab]} PANE IS NOT DESIGNED YET"
            sw = text.text_width(sub, SMALL_SIZE)
            text.draw_text(x0 + (pw - sw) * 0.5, y + box_h * 0.42 + blh + 4,
                           sub, PAPER_MUTED, SMALL_SIZE)
            return

        # LEDGER tab. Sensor-lane strip: not visually approved -> placeholder.
        strip_h = max(int(ph * 0.22), lh * 2 + 16)
        self._rect_border(text, x0, y, pw, strip_h, (*PAPER_MUTED, 1.0), 1.0,
                          dashed=True)
        text.draw_text(x0 + 10, y + 6, "SENSOR RECORD", PAPER_MUTED,
                       SMALL_SIZE)
        msg = "AWAITING DESIGN"
        mw = text.text_width(msg, SMALL_SIZE)
        text.draw_text(x0 + (pw - mw) * 0.5, y + strip_h * 0.5 - lh * 0.5,
                       msg, PAPER_MUTED, SMALL_SIZE)
        y += strip_h + 12

        # The finding: killer bar + headline (fog-gated).
        cause = rec.get("cause")
        headline = cause_headline(cause, battle_over)
        col = (INK_GREEN if cause is not None and cause["code"] == "hit"
               else INK_TEAL if cause is None
               else INK_AMBER if cause["code"] in ("fuel", "impact")
               else INK_RED)
        text.draw_rect(x0, y, 4, blh + 6, (*col, 1.0))
        text.draw_text(x0 + 12, y + 3, headline, col, BODY_SIZE)
        y += blh + 10
        path = self.state.flight_recorder.path_of(rec)
        if len(path) >= 2:
            km = cumulative_ground_km(path)
            fact = (f"RAN {km[-1]:.1f} KM OVER "
                    f"{path[-1, 0] - path[0, 0]:.0f} S - "
                    f"{len(path)} RECORDED SAMPLES")
            text.draw_text(x0 + 12, y, fact, PAPER_MUTED, SMALL_SIZE)
            y += lh + 12

        # Same-cause cross-reference (derived from the cause channel only).
        # FOG: mid-battle the grouping may only span OBSERVED causes —
        # keying an unobserved "LOST?" sheet on its true cause under an
        # observed sheet leaked attribution the sensors never justified.
        if cause is not None and (battle_over or cause["observed"]):
            same = [r for r in recs
                    if r is not rec and r.get("cause") is not None
                    and (battle_over or r["cause"]["observed"])
                    and r["cause"]["code"] == cause["code"]
                    and r["cause"]["detail"] == cause["detail"]]
            if same:
                text.draw_text(x0, y, "SAME-CAUSE LOSSES - CROSS-REFERENCE",
                               PAPER_MUTED, SMALL_SIZE)
                y += lh + 4
                for other in same[:4]:
                    sheet = recs.index(other) + 1
                    status, _ = stub_status(other["cause"], battle_over)
                    text.draw_text(x0, y, f"{stub_id(other)} - SHEET "
                                          f"{sheet} - {status}",
                                   PAPER_INK, SMALL_SIZE)
                    y += lh + 2
                y += 8

        # The stamp (closed sheets only).
        if cause is not None:
            status, ink_key = stub_status(cause, battle_over)
            stamp = (f"{status} - " + ("OBSERVED" if cause["observed"]
                                       else "UNCONFIRMED"))
            scol = _INKS["green" if cause["code"] == "hit" else
                         "red" if ink_key == "red" else "muted"]
            sw = text.text_width(stamp, BODY_SIZE)
            sx = x0 + pw - sw - 36
            sy = y0 + ph - blh - 26
            self._rect_border(text, sx - 12, sy - 8, sw + 24, blh + 16,
                              (*scol, 1.0), 2.0)
            text.draw_text(sx, sy, stamp, scol, BODY_SIZE)

    # ---------------------------------------------------------- draw helpers

    @staticmethod
    def _rect_border(text, x, y, w, h, rgba, width=1.0, dashed=False):
        if not dashed:
            text.draw_lines([(x, y), (x + w, y), (x + w, y + h), (x, y + h),
                             (x, y)], rgba, width)
            return
        # Dashed border: fixed-pitch dashes per edge (ASCII-flat idiom).
        def edge(ax, ay, bx, by):
            length = math.hypot(bx - ax, by - ay)
            n = max(1, int(length // 12))
            for i in range(n):
                f0 = i / n
                f1 = f0 + 0.55 / n
                text.draw_lines([(ax + (bx - ax) * f0, ay + (by - ay) * f0),
                                 (ax + (bx - ax) * f1, ay + (by - ay) * f1)],
                                rgba, width)
        edge(x, y, x + w, y)
        edge(x + w, y, x + w, y + h)
        edge(x + w, y + h, x, y + h)
        edge(x, y + h, x, y)

    @staticmethod
    def _dashed(text, x0, y0, x1, y1, rgba, width=2.0):
        length = math.hypot(x1 - x0, y1 - y0)
        if length < 1e-6:
            return
        n = max(1, int(length // 24))
        for i in range(n):
            f0 = i / n
            f1 = f0 + 0.5 / n
            text.draw_lines([(x0 + (x1 - x0) * f0, y0 + (y1 - y0) * f0),
                             (x0 + (x1 - x0) * f1, y0 + (y1 - y0) * f1)],
                            rgba, width)

    @staticmethod
    def _diamond(text, cx, cy, r, rgba):
        text.draw_lines([(cx, cy - r), (cx + r, cy), (cx, cy + r),
                         (cx - r, cy), (cx, cy - r)], rgba, 2.0)

    @staticmethod
    def _x_anchor(text, cx, cy, col):
        """Red-circled X at the exact recorded death position."""
        r = 15
        pts = [(cx + r * math.cos(a), cy + r * math.sin(a))
               for a in np.linspace(0.0, 2.0 * math.pi, 17)]
        text.draw_lines(pts, (*col, 1.0), 2.0)
        s = 6
        text.draw_lines([(cx - s, cy - s), (cx + s, cy + s)], (*col, 1.0),
                        2.0)
        text.draw_lines([(cx - s, cy + s), (cx + s, cy - s)], (*col, 1.0),
                        2.0)

    def _pin(self, text, px_, py_, label, col, up=50, anchor_gap=0,
             bounds=None):
        """A flag pinned on a plotted point: 2px stem + 1px-bordered label
        (the mock's plotting-table language).  ``bounds`` (x0, y0, x1, y1)
        keeps the flag INSIDE its plot frame — a pin near the frame top
        flips below its point instead of escaping the sheet."""
        lh = text.line_height(SMALL_SIZE)
        lw = text.text_width(label, SMALL_SIZE)
        box_h = lh + 8
        if bounds is None:
            bounds = (6, 6, 10_000.0, 10_000.0)
        bx0, by0, bx1, by1 = bounds
        flip = py_ - up - box_h - 3 < by0       # no room above: pin DOWN
        if flip:
            drop = min(up, by1 - py_ - box_h - 3)
            drop = max(drop, anchor_gap + 12)
            text.draw_rect(px_, py_ + anchor_gap, 2, drop - anchor_gap,
                           (*col, 1.0))
            by = py_ + drop + 5
        else:
            stem_top = py_ - up
            text.draw_rect(px_, stem_top, 2, up - anchor_gap, (*col, 1.0))
            by = stem_top - lh - 8
        bx = px_ - lw * 0.5
        bx = min(max(bx, bx0 + 8), bx1 - lw - 8)
        text.draw_rect(bx - 6, by - 3, lw + 12, lh + 8, (*PAPER_TAG, 1.0))
        self._rect_border(text, bx - 6, by - 3, lw + 12, lh + 8,
                          (*col, 1.0), 1.0)
        text.draw_text(bx, by, label, col, SMALL_SIZE)
