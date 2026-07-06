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

The three panes (approved proto_panels round, 2026-07-06 — variation C of
each) all feed LIVE data:
  * SENSOR RECORD micro-ledger (LEDGER tab, right column): raw receiver
    rows from ``CombatState.sensor_log`` in the selected round's window.
  * BLACK BOX density deck (tab 2): kind-per-lane density of the SHIPPED
    BattleLedger (``CombatState.ledger.records``) over the whole battle +
    the pointed-at window's exact records.  LEFT/RIGHT moves the window.
  * SENSORS plot board (tab 3): raw sensor GEOMETRY in space — belief
    paints aging by opacity, ELINT rays, launch-warn rays, acoustic
    uncertainty rings — never a fused conclusion.  (Pencil calls + AAR
    grading: a later pass, once the grading rules are designed.)

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
    INK_VIOLET, PAPER_BG, PAPER_CHIP_BG, PAPER_CHIP_EDGE, PAPER_CHIP_MUTED,
    PAPER_CHIP_TEXT, PAPER_DESK, PAPER_DESK_EDGE, PAPER_FIELD, PAPER_HATCH,
    PAPER_HEADLINE, PAPER_INK, PAPER_MUTED, PAPER_SELECT, PAPER_TAG,
)
from world.generation import BASE_POS

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
         "teal": INK_TEAL, "amber": INK_AMBER, "green": INK_GREEN,
         "violet": INK_VIOLET}

# Receiver lanes (game/sensor_log.py) -> display name + ink key.
_LANE_LABEL = {"radar": "RADAR", "lwarn": "L-WARN", "elint": "ELINT",
               "acoustic": "ACOUSTIC"}
_LANE_INK = {"radar": "teal", "lwarn": "amber", "elint": "violet",
             "acoustic": "green"}

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


# ------------------------------------------------- BLACK BOX deck (pure)

# The density deck's lanes = the ledger's record kinds (top-to-bottom).  A
# DENIED cmd rides the hint lane (the denial channel gets its own ink).
_DECK_LANES = ("cmd", "hint", "evt", "toggle", "loss", "mark", "hash")

_DECK_LANE_LABEL = {"cmd": "CMD", "hint": "HINT / DENIED", "evt": "EVT",
                    "toggle": "TOGGLE", "loss": "LOSS", "mark": "MARK (F3)",
                    "hash": "HASH"}

_DECK_LANE_INK = {"cmd": "teal", "hint": "red", "evt": "green",
                  "toggle": "amber", "loss": "red", "mark": "amber",
                  "hash": "muted"}


def ledger_lane(record) -> str | None:
    """Deck lane for a BattleLedger record (None = not a lane: header/end)."""
    kind = record.get("rec")
    if kind == "cmd" and not record.get("ok", True):
        return "hint"                   # denial: rides the refusal lane
    return kind if kind in _DECK_LANES else None


def bin_lane_counts(records, t0: float, t1: float, nbins: int) -> dict:
    """Per-lane event counts in ``nbins`` equal time bins over [t0, t1)
    (pure — the deck's density strips).  Records without a lane or outside
    the range are ignored."""
    span = max(t1 - t0, 1e-9)
    bins = {lane: [0] * nbins for lane in _DECK_LANES}
    for r in records:
        lane = ledger_lane(r)
        t = r.get("t")
        if lane is None or t is None:
            continue
        if not t0 <= t < t1:
            continue
        i = min(int((t - t0) / span * nbins), nbins - 1)
        bins[lane][i] += 1
    return bins


def _fmt_val(v) -> str:
    """Compact arg rendering for the tape: 3-vectors/2-vectors as km."""
    if isinstance(v, (list, tuple)) and len(v) in (2, 3) \
            and all(isinstance(x, (int, float)) for x in v):
        return f"({v[0] / 1e3:+.1f},{v[-1] / 1e3:+.1f})KM"
    if isinstance(v, float):
        return f"{v:.1f}"
    return str(v)


def fmt_ledger_row(record, battle_over: bool) -> tuple:
    """(kind_label, text, ink_key) for one ledger record on the tape.

    FOG GATE: a LOSS row's cause was RECORDED in full, but the mid-battle
    display may not name an unobserved killer — it prints UNCONFIRMED until
    the AAR (same rule as the stubs)."""
    kind = record.get("rec")
    if kind == "cmd":
        ok = record.get("ok", True)
        args = record.get("args", {}) or {}
        brief = " ".join(f"{k}={_fmt_val(v)}"
                         for k, v in list(args.items())[:3])
        text = f"{record.get('verb', '?')} {brief} -> " \
               + ("OK" if ok else "DENIED")
        return ("CMD", text, "teal" if ok else "red")
    if kind == "hint":
        return ("HINT", f'"{record.get("text", "")}"', "red")
    if kind == "evt":
        pos = record.get("pos")
        where = (f" @ ({pos[0] / 1e3:+.1f}, {pos[-1] / 1e3:+.1f}) KM"
                 if isinstance(pos, (list, tuple)) and len(pos) >= 2 else "")
        return ("EVT", f"{record.get('kind', '?')}{where}", "green")
    if kind == "toggle":
        return ("TOGGLE",
                f"{record.get('name', '?')} -> "
                f"{str(record.get('value')).upper()}", "amber")
    if kind == "loss":
        rid = f"{str(record.get('kind', '?')).upper()}-{record.get('seq', 0)}"
        observed = bool(record.get("observed", False))
        code = str(record.get("code", "lost"))
        detail = str(record.get("detail", "") or "")
        if observed or battle_over:
            cause = code + (f"/{detail}" if detail else "")
            tag = "OBSERVED" if observed else "RECONSTRUCTED"
            return ("LOSS", f"{rid} CAUSE={cause.upper()} - {tag}", "red")
        return ("LOSS", f"{rid} LOST - UNCONFIRMED", "red")
    if kind == "hash":
        digest = str(record.get("digest", ""))[:8].upper()
        return ("HASH", f"STATE DIGEST {digest} (TICK "
                        f"{record.get('tick', 0)})", "muted")
    if kind == "mark":
        return ("MARK", f"F3 FLAG: {record.get('note', 'BUG')}", "amber")
    if kind == "header":
        return ("HDR", f"BATTLE SEED {record.get('seed', 0)} - COMMIT "
                       f"{record.get('commit', '') or '?'}", "muted")
    if kind == "end":
        return ("END", f"{str(record.get('outcome', '')).upper()} "
                       f"{record.get('grade', '')}".strip(), "ink")
    return (str(kind).upper()[:6], "", "muted")


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
        self.bb_offset = 0.0            # deck window shift (s, <= 0 = past)
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
            # On the BLACK BOX deck LEFT/RIGHT move the record window;
            # everywhere else they leaf the ledger like UP/DN.
            if self.tab == 1 and key in (pygame.K_LEFT, pygame.K_RIGHT):
                step = -30.0 if key == pygame.K_LEFT else 30.0
                now = float(getattr(self.state.world, "sim_time", 0.0))
                self.bb_offset = min(0.0, max(-(max(now - 90.0, 0.0)),
                                              self.bb_offset + step))
                app.audio.ui_click()
                return True
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

        # Side-view hero plot — LEDGER tab only: the full-band panes
        # (deck / plot board) take the whole sheet body instead.
        if self.tab == 0:
            sid = stub_id(rec)
            text.draw_text(x0, y, f"{sid} - RECORDED FLIGHT PATH - SIDE "
                                  f"VIEW, PLOTTED 1:1 FROM THE PATH "
                                  f"RECORDER (SQUARE TICKS = SAMPLES)",
                           PAPER_MUTED, SMALL_SIZE)
            y += text.line_height(SMALL_SIZE) + 4
            plot_h = int(ph * 0.30)
            self._side_plot(text, x0, y, inner_w, plot_h, rec, path,
                            battle_over)
            y += plot_h + 12

        # Bottom band: tab strip, then the ACTIVE pane (approved variation C
        # of each — LEDGER keeps the split layout; BLACK BOX / SENSORS own
        # the full band).
        y = self._tab_strip(text, x0, y)
        bottom_h = py + ph - y - int(pad * 1.7)
        if self.tab == 0:
            map_w = int(inner_w * 0.52)
            self._top_down(text, x0, y, map_w, bottom_h, rec, path)
            rx = x0 + map_w + pad
            self._right_column(text, rx, y, x0 + inner_w - rx, bottom_h,
                               recs, rec, battle_over)
        elif self.tab == 1:
            self._blackbox_deck(text, x0, y, inner_w, bottom_h, battle_over)
        else:
            self._plot_board(text, x0, y, inner_w, bottom_h)

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

    # ------------------------------------------------------------ tab strip

    def _tab_strip(self, text, x0, y0) -> int:
        """The 1/2/3 view strip above the bottom band; returns the band's
        top y.  Click OR number key switches (keyboard path law)."""
        lh = text.line_height(SMALL_SIZE)
        tx = x0
        for i, label in enumerate(_TABS):
            active = i == self.tab
            col = PAPER_INK if active else PAPER_MUTED
            full = f"[{i + 1}] {label}"
            text.draw_text(tx, y0, full, col, SMALL_SIZE)
            full_w = text.text_width(full, SMALL_SIZE)
            if active:
                text.draw_rect(tx, y0 + lh + 1, full_w, 2, (*PAPER_INK, 1.0))
            self._tab_rects.append((i, tx, y0, tx + full_w, y0 + lh + 3))
            tx += full_w + 22
        return y0 + lh + 10

    # --------------------------------------------------------- right column

    def _right_column(self, text, x0, y0, pw, ph, recs, rec,
                      battle_over) -> None:
        lh = text.line_height(SMALL_SIZE)
        blh = text.line_height(BODY_SIZE)
        y = y0

        # SENSOR RECORD micro-ledger (approved variation C): raw receiver
        # rows from the LIVE sensor log, filtered to this round's flight
        # window, newest last; the recorder's close-out is the struck row.
        strip_h = max(int(ph * 0.40), lh * 6 + 20)
        y = self._micro_ledger(text, x0, y, pw, strip_h, rec, battle_over)
        y += 12

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

    # --------------------------------------------------------- micro-ledger

    def _micro_ledger(self, text, x0, y0, pw, ph, rec, battle_over) -> int:
        """SENSOR RECORD as a typed table (approved variation C): one row
        per RAW receiver record inside the selected round's flight window —
        facts only, straight from the live SensorLog.  Returns bottom y."""
        lh = text.line_height(SMALL_SIZE)
        text.draw_text(x0, y0, "SENSOR RECORD - RAW RECEIVER ROWS - THIS "
                               "ROUND'S WINDOW", PAPER_MUTED, SMALL_SIZE)
        fy = y0 + lh + 4
        fh = ph - lh - 4
        text.draw_rect(x0, fy, pw, fh, (*PAPER_FIELD, 1.0))
        self._rect_border(text, x0, fy, pw, fh, (*PAPER_INK, 1.0), 2.0)

        log = getattr(self.state, "sensor_log", None)
        world = self.state.world
        now = float(getattr(world, "sim_time", 0.0))
        t0 = float(rec["launch_t"])
        death = rec.get("death")
        t1 = float(death["t"]) if death is not None else now
        events = log.events_between(t0, t1) if log is not None else []

        # Column layout: T+ | RECEIVER | RECORD | REF (right-aligned).
        cx_t, cx_rcv, cx_body = x0 + 10, x0 + 84, x0 + 176
        ref_w = 96
        row_h = lh + 4
        hy = fy + 5
        for cx, head in ((cx_t, "T+"), (cx_rcv, "RECEIVER"),
                         (cx_body, "RECORD")):
            text.draw_text(cx, hy, head, PAPER_MUTED, SMALL_SIZE)
        text.draw_text(x0 + pw - ref_w, hy, "REF", PAPER_MUTED, SMALL_SIZE)
        text.draw_rect(x0 + 4, hy + lh + 1, pw - 8, 1, (*PAPER_INK, 0.8))
        yy = hy + lh + 5

        rows_fit = max(int((fy + fh - yy - 4) // row_h), 1)
        cause = rec.get("cause")
        n_data = rows_fit - (1 if cause is not None else 0)
        clipped = max(0, len(events) - n_data)
        for e in events[clipped:] if n_data > 0 else []:
            lane_ink = _INKS[_LANE_INK.get(e["lane"], "muted")]
            text.draw_text(cx_t, yy, fmt_clock(e["t"])[2:], PAPER_MUTED,
                           SMALL_SIZE)
            text.draw_text(cx_rcv, yy, _LANE_LABEL.get(e["lane"], "?"),
                           lane_ink, SMALL_SIZE)
            text.draw_text(cx_body, yy, e["label"], PAPER_INK, SMALL_SIZE)
            ref = str(e["ref"]).upper()[:10]
            rw = text.text_width(ref, SMALL_SIZE)
            text.draw_text(x0 + pw - 10 - rw, yy, ref, PAPER_MUTED,
                           SMALL_SIZE)
            yy += row_h
        if cause is not None and death is not None and rows_fit > 0:
            status, ink_key = stub_status(cause, battle_over)
            col = _INKS[ink_key if ink_key != "muted" else "red"]
            text.draw_rect(x0 + 4, yy - 1, pw - 8, row_h, (*INK_RED, 0.08))
            text.draw_text(cx_t, yy, fmt_clock(death["t"])[2:], col,
                           SMALL_SIZE)
            text.draw_text(cx_rcv, yy, "RECORDER", col, SMALL_SIZE)
            text.draw_text(cx_body, yy, f"{stub_id(rec)} CLOSED - {status}",
                           col, SMALL_SIZE)
            yy += row_h
        if not events and cause is None:
            msg = ("NO RECEIVER RECORDS IN THIS WINDOW YET"
                   if log is not None else "NO SENSOR LOG THIS SESSION")
            text.draw_text(cx_t, yy, msg, PAPER_MUTED, SMALL_SIZE)
        if clipped > 0:
            note = f"+{clipped} EARLIER"
            nw = text.text_width(note, SMALL_SIZE)
            text.draw_text(x0 + pw - 10 - nw, fy + fh - lh - 4, note,
                           PAPER_MUTED, SMALL_SIZE)
        return fy + fh

    # -------------------------------------------------------- black box deck

    def _blackbox_deck(self, text, x0, y0, pw, ph, battle_over) -> None:
        """BLACK BOX (approved variation C): kind-per-lane density of the
        WHOLE battle ledger on top, the pointed-at window's exact records
        below.  Feeds CombatState.ledger.records — the shipped JSONL,
        nothing invented.  LEFT/RIGHT move the window."""
        lh = text.line_height(SMALL_SIZE)
        ledger = getattr(self.state, "ledger", None)
        records = getattr(ledger, "records", None)
        if not records:
            self._rect_border(text, x0, y0, pw, ph - 8, (*PAPER_MUTED, 1.0),
                              1.0, dashed=True)
            text.draw_text(x0 + 14, y0 + 12, "NO BATTLE LEDGER THIS "
                                             "SESSION", PAPER_MUTED,
                           SMALL_SIZE)
            return
        now = max(float(getattr(self.state.world, "sim_time", 0.0)), 1.0)

        # --- the deck: one density lane per record kind, full battle ---
        label_w = 132
        lane_h = lh + 8
        ruler_h = lh + 4
        deck_h = ruler_h + lane_h * len(_DECK_LANES) + 6
        text.draw_rect(x0, y0, pw, deck_h, (*PAPER_FIELD, 1.0))
        self._rect_border(text, x0, y0, pw, deck_h, (*PAPER_INK, 1.0), 2.0)
        gx0 = x0 + label_w
        gw = pw - label_w - 14
        nbins = 90
        bins = bin_lane_counts(records, 0.0, now, nbins)
        # Ruler.
        for frac, tag in ((0.0, "T+00"), (0.34, fmt_clock(now * 0.34)),
                          (0.67, fmt_clock(now * 0.67)), (1.0, fmt_clock(now))):
            tx = gx0 + frac * gw
            tw = text.text_width(tag, SMALL_SIZE)
            text.draw_text(min(tx, x0 + pw - tw - 8), y0 + 4, tag,
                           PAPER_MUTED, SMALL_SIZE)
        text.draw_rect(gx0, y0 + ruler_h, gw, 1, (*PAPER_INK, 0.5))
        yy = y0 + ruler_h + 2
        bin_w = gw / nbins
        for lane in _DECK_LANES:
            ink = _INKS[_DECK_LANE_INK[lane]]
            text.draw_text(x0 + 8, yy + 4, _DECK_LANE_LABEL[lane], ink,
                           SMALL_SIZE)
            for i, c in enumerate(bins[lane]):
                if c <= 0:
                    continue
                bar = min(lane_h - 6, 3 + 3 * c)
                text.draw_rect(gx0 + i * bin_w, yy + lane_h - 3 - bar,
                               max(bin_w - 2, 2), bar, (*ink, 0.9))
            if lane != _DECK_LANES[-1]:
                text.draw_rect(gx0, yy + lane_h - 1, gw, 1,
                               (*PAPER_INK, 0.12))
            yy += lane_h

        # The pointed-at window box across all lanes.
        win_s = 90.0
        w_t1 = max(min(now + self.bb_offset, now), min(win_s, now))
        w_t0 = max(0.0, w_t1 - win_s)
        wx0 = gx0 + (w_t0 / now) * gw
        wx1 = gx0 + (w_t1 / now) * gw
        self._rect_border(text, wx0, y0 + ruler_h + 1, max(wx1 - wx0, 6),
                          deck_h - ruler_h - 5, (*PAPER_INK, 1.0), 2.0)

        y = y0 + deck_h + 6
        text.draw_text(x0, y, f"WINDOW {fmt_clock(w_t0)} .. "
                              f"{fmt_clock(w_t1)} - LEFT/RIGHT MOVES - THE "
                              f"HASH LANE'S EVEN PULSE = REPLAY INTEGRITY",
                       PAPER_MUTED, SMALL_SIZE)
        y += lh + 6

        # --- the window table: exact records, newest last ---
        th = y0 + ph - y - lh - 10
        text.draw_rect(x0, y, pw, th, (*PAPER_FIELD, 1.0))
        self._rect_border(text, x0, y, pw, th, (*PAPER_INK, 1.0), 2.0)
        window = [r for r in records
                  if r.get("t") is not None and w_t0 <= r["t"] <= w_t1]
        row_h = lh + 4
        rows_fit = max(int((th - 10) // row_h), 1)
        clipped = max(0, len(window) - rows_fit)
        yy = y + 5
        for r in window[clipped:]:
            kind, body, ink_key = fmt_ledger_row(r, battle_over)
            ink = _INKS[ink_key]
            text.draw_text(x0 + 10, yy, fmt_clock(r["t"])[2:], PAPER_MUTED,
                           SMALL_SIZE)
            text.draw_text(x0 + 84, yy, kind, ink, SMALL_SIZE)
            body_x = x0 + 172
            max_w = pw - (body_x - x0) - 12
            while body and text.text_width(body, SMALL_SIZE) > max_w:
                body = body[:-4] + ".."
            text.draw_text(body_x, yy, body,
                           PAPER_INK if ink_key in ("teal", "green", "ink")
                           else ink, SMALL_SIZE)
            yy += row_h
        if clipped > 0:
            note = f"+{clipped} EARLIER IN WINDOW"
            nw = text.text_width(note, SMALL_SIZE)
            text.draw_text(x0 + pw - 10 - nw, y + th - lh - 4, note,
                           PAPER_MUTED, SMALL_SIZE)

        denied = sum(1 for r in records
                     if r.get("rec") == "cmd" and not r.get("ok", True))
        marks = sum(1 for r in records if r.get("rec") == "mark")
        text.draw_text(x0, y + th + 6,
                       f"{len(records)} RECORDS - {denied} DENIED - "
                       f"{marks} MARK(S) - EVERY ROW IS ONE LEDGER RECORD "
                       f"(REPLAYABLE BIT-EXACT)", PAPER_MUTED, SMALL_SIZE)

    # ----------------------------------------------------------- plot board

    def _plot_board(self, text, x0, y0, pw, ph) -> None:
        """SENSORS (approved variation C): raw sensor GEOMETRY in space —
        belief paints aging by opacity, ELINT/launch-warn bearing rays from
        the base, acoustic uncertainty rings, dropped-return X marks.  The
        board never fuses; conclusions stay yours."""
        lh = text.line_height(SMALL_SIZE)
        legend_w = 360
        bw = pw - legend_w - 18
        bh = ph - 8
        text.draw_rect(x0, y0, bw, bh, (*PAPER_FIELD, 1.0))
        self._rect_border(text, x0, y0, bw, bh, (*PAPER_INK, 1.0), 2.0)

        log = getattr(self.state, "sensor_log", None)
        world = self.state.world
        now = float(getattr(world, "sim_time", 0.0))
        events = list(log.events)[-160:] if log is not None else []
        base_xz = (float(BASE_POS[0]), float(BASE_POS[2]))
        buoys = [(float(b[0]), float(b[2]))
                 for b in getattr(world, "sonobuoys", ())]

        pts = [base_xz] + buoys + [e["pos"] for e in events
                                   if e["pos"] is not None]
        min_x = min(p[0] for p in pts) - 10_000.0
        max_x = max(p[0] for p in pts) + 10_000.0
        min_z = min(p[1] for p in pts) - 10_000.0
        max_z = max(p[1] for p in pts) + 10_000.0
        margin = 30
        scale = min((bw - 2 * margin) / max(max_x - min_x, 1_000.0),
                    (bh - 2 * margin) / max(max_z - min_z, 1_000.0))
        cx = (min_x + max_x) * 0.5
        cz = (min_z + max_z) * 0.5

        def PX(wx):
            return x0 + bw * 0.5 + (wx - cx) * scale

        def PZ(wz):
            return y0 + bh * 0.5 - (wz - cz) * scale

        # 25 km grid at the uniform scale.
        grid = 25_000.0
        gxx = math.floor(min_x / grid) * grid
        while gxx < max_x + grid:
            sx = PX(gxx)
            if x0 + 2 < sx < x0 + bw - 2:
                text.draw_rect(sx, y0 + 2, 1, bh - 4, (*INK_TEAL, 0.14))
            gxx += grid
        gzz = math.floor(min_z / grid) * grid
        while gzz < max_z + grid:
            sz = PZ(gzz)
            if y0 + 2 < sz < y0 + bh - 2:
                text.draw_rect(x0 + 2, sz, bw - 4, 1, (*INK_TEAL, 0.14))
            gzz += grid

        # Own-force fixtures (own truth is always allowed): base + buoys.
        bx, bz = PX(base_xz[0]), PZ(base_xz[1])
        text.draw_rect(bx - 7, bz - 5, 14, 10, (*INK_GREEN, 1.0))
        text.draw_text(bx - 20, bz + 9, "BASE", INK_GREEN, SMALL_SIZE)
        for wx, wz in buoys:
            sx, sz = PX(wx), PZ(wz)
            self._dash_circle(text, sx, sz, 5, (*INK_GREEN, 1.0), seg=8)

        # Raw sensor geometry, oldest first (fresh ink prints on top).
        fade_s = 240.0
        for e in events:
            if e["pos"] is None:
                continue
            ex, ez = PX(e["pos"][0]), PZ(e["pos"][1])
            if not (x0 + 4 < ex < x0 + bw - 4 and y0 + 4 < ez < y0 + bh - 4):
                continue
            age = max(0.0, now - e["t"])
            a = max(0.25, 1.0 - age / fade_s)
            lane = e["lane"]
            if lane == "radar":
                if e["label"] == "TRACK DROPPED":
                    s = 5
                    text.draw_lines([(ex - s, ez - s), (ex + s, ez + s)],
                                    (*INK_RED, a), 2.0)
                    text.draw_lines([(ex - s, ez + s), (ex + s, ez - s)],
                                    (*INK_RED, a), 2.0)
                else:
                    text.draw_rect(ex - 3, ez - 3, 6, 6, (*INK_TEAL, a))
            elif lane == "lwarn":
                # The RAY is the CUE moment; later refreshes just paint
                # (a board of every refresh ray drowns in amber).
                if e["label"] == "LAUNCH CUE":
                    text.draw_lines([(bx, bz), (ex, ez)],
                                    (*INK_AMBER, 0.5 * a), 2.5)
                if e["label"] == "TRACK DROPPED":
                    s = 5
                    text.draw_lines([(ex - s, ez - s), (ex + s, ez + s)],
                                    (*INK_AMBER, a), 2.0)
                    text.draw_lines([(ex - s, ez + s), (ex + s, ez - s)],
                                    (*INK_AMBER, a), 2.0)
                else:
                    text.draw_rect(ex - 3, ez - 3, 6, 6, (*INK_AMBER, a))
            elif lane == "elint":
                if e["label"] == "EMITTER HEARD":
                    text.draw_lines([(bx, bz), (ex, ez)],
                                    (*INK_VIOLET, 0.35 * a), 1.5)
                self._diamond(text, ex, ez, 6, (*INK_VIOLET, a))
            elif lane == "acoustic":
                r_px = max(10.0, float(e.get("quality") or 0.0) * scale)
                self._dash_circle(text, ex, ez, min(r_px, 90.0),
                                  (*INK_GREEN, a))
                if e["label"] == "LAUNCH DATUM":
                    self._diamond(text, ex, ez, 5, (*INK_GREEN, a))

        cap = (f"GRID 25 KM - UNIFORM {scale * 1_000.0:.2f} PX/KM - RAYS = "
               f"BEARINGS - RINGS = FIX UNCERTAINTY - PAINTS AGE BY OPACITY")
        cw = text.text_width(cap, SMALL_SIZE)
        text.draw_text(x0 + bw - cw - 8, y0 + bh - lh - 6, cap, PAPER_MUTED,
                       SMALL_SIZE)

        # Legend + newest-first raw feed.
        rx = x0 + bw + 18
        rw = pw - bw - 18
        y = y0
        text.draw_text(rx, y, "THE BOARD NEVER FUSES - YOU MAKE THE CALL",
                       PAPER_MUTED, SMALL_SIZE)
        y += lh + 6
        legend = (("SQUARE PAINT - ONE BELIEF FIX, AGES BY INK", "teal"),
                  ("HEAVY RAY - LAUNCH-WARNING CUE", "amber"),
                  ("THIN RAY + DIAMOND - ELINT EMITTER FIX", "violet"),
                  ("DASHED RING - ACOUSTIC UNCERTAINTY", "green"),
                  ("X - A TRACK THAT STOPPED COMING BACK", "red"))
        for line, ink_key in legend:
            text.draw_text(rx, y, line, _INKS[ink_key], SMALL_SIZE)
            y += lh + 2
        y += 8
        text.draw_text(rx, y, "RAW EVENTS - NEWEST FIRST", PAPER_MUTED,
                       SMALL_SIZE)
        y += lh + 4
        fh = y0 + ph - y - lh - 12
        text.draw_rect(rx, y, rw, fh, (*PAPER_FIELD, 1.0))
        self._rect_border(text, rx, y, rw, fh, (*PAPER_INK, 1.0), 1.0)
        row_h = lh + 4
        rows_fit = max(int((fh - 8) // row_h), 1)
        feed = log.latest(rows_fit) if log is not None else []
        yy = y + 4
        for e in feed:
            ink = _INKS[_LANE_INK.get(e["lane"], "muted")]
            text.draw_text(rx + 8, yy, fmt_clock(e["t"])[2:], PAPER_MUTED,
                           SMALL_SIZE)
            text.draw_text(rx + 74, yy, _LANE_LABEL.get(e["lane"], "?"),
                           ink, SMALL_SIZE)
            body = e["label"]
            ref = str(e["ref"]).upper()[:9]
            text.draw_text(rx + 168, yy, body, PAPER_INK, SMALL_SIZE)
            rw2 = text.text_width(ref, SMALL_SIZE)
            text.draw_text(rx + rw - 8 - rw2, yy, ref, PAPER_MUTED,
                           SMALL_SIZE)
            yy += row_h
        if not feed:
            text.draw_text(rx + 8, yy, "NO RECEIVER RECORDS YET",
                           PAPER_MUTED, SMALL_SIZE)
        text.draw_text(rx, y0 + ph - lh - 2,
                       "PENCIL CALLS + AAR GRADING - NEXT PASS",
                       PAPER_MUTED, SMALL_SIZE)

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
    def _dash_circle(text, cx, cy, r, rgba, seg: int = 20, width=1.5):
        """Dashed ring from alternating arc segments (flat-line idiom)."""
        for i in range(0, seg, 2):
            a0 = 2.0 * math.pi * i / seg
            a1 = 2.0 * math.pi * (i + 1) / seg
            text.draw_lines(
                [(cx + r * math.cos(a0), cy + r * math.sin(a0)),
                 (cx + r * math.cos(a1), cy + r * math.sin(a1))],
                rgba, width)

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
