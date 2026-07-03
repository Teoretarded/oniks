"""GameState base + state machine + the menu/pause/settings screens (Task UI).

Visual language: "WARDROOM DUSK" (normative: Assets of oinks/ui_design/
handoff/ONIKS-UI-SPEC.md; docs/research/ui_reference.md is the engine-
constraint substrate it extends).  Petrol/dusk field, warm-cream text,
ONE brass accent reserved for selection + weapons, plates with hairline
borders + brass-dim corner brackets, 56 pt space-tracked title, 40 px rows
with hover fill + 3 px left focus bar + 80 ms press flash, 14 pt footers.
The fog-of-war COLOR LAW lives in the palette block below. The settings screen is the
rebind UI: click/ENTER -> PRESS KEY capture, ESC cancels, conflicts offer an
atomic ENTER-swap, R resets a row, RESET DEFAULTS double-ENTER confirms —
every successful change is written to disk immediately (game/keybinds.py).

All input flows run headless (LOCKED test convention): OpenGL imports and
the TextRenderer are deferred to ``enter``/``render``, so unit tests drive
``handle_event`` directly on constructed states.
"""

from __future__ import annotations

import math

import pygame

from engine.text import BODY_SIZE, HEADER_SIZE, SMALL_SIZE, TITLE_SIZE
from game.keybinds import (ACTIONS, RESERVED_KEYS, key_display, normalize_key)

# --- Visual-language palette: "WARDROOM DUSK" ------------------------------------
# Normative: Assets of oinks/ui_design/handoff/ONIKS-UI-SPEC.md (locked 2a).
# COLOR LAW (never mix families): sensor ESTIMATES/beliefs -> teal; own-force
# TRUTH -> green; HOSTILE -> dusk-red (age = opacity); brass/gold -> selection
# + weapons ONLY; cream/muted neutrals carry all other text.

BG0 = (0.039, 0.067, 0.078)         # bg-app  #0A1114  menu/setup field
BG1 = (0.078, 0.106, 0.094)         # plate   #141B18  panel fill
BG2 = (0.114, 0.149, 0.125)         # plate-selected #1D2620 row focus fill
LINE_COL = (0.173, 0.212, 0.188)    # hairline #2C3630 borders, dividers
ROW_DIVIDER = (0.133, 0.188, 0.169)  # in-plate row separators #22302B
ACCENT = (0.910, 0.722, 0.294)      # brass   #E8B84B  selection + weapons ONLY
ACCENT_DIM = (0.541, 0.435, 0.208)  # brass-dim #8A6F35 corner ticks
DANGER = (0.910, 0.416, 0.290)      # hostile #E86A4A  vampires, threats, C/D
HOSTILE_AGED = (0.910, 0.529, 0.361)  # aged contact #E8875C (opacity also fades)
OK_COL = (0.624, 0.851, 0.541)      # ok      #9FD98A  own-force truth, S/A
WARN = (0.851, 0.643, 0.255)        # warn    #D9A441  reload timers, B grade
TEXT_COL = (0.937, 0.902, 0.816)    # text    #EFE6D0  warm-cream values
MUTED = (0.608, 0.659, 0.576)       # muted   #9BA893  labels
FAINT = (0.431, 0.541, 0.502)       # faint   #6E8A80  captions, PAR annotations
DISABLED = (0.361, 0.416, 0.376)    # disabled #5C6A60 greyed rows
BELIEF = (0.494, 0.831, 0.816)      # belief  #7ED4D0  estimates — NEVER truth
PRESS_FILL = (0.192, 0.251, 0.184)  # press   #31402F  80ms press-state fill
HINT_COL = (0.541, 0.478, 0.298)    # hint-bar text #8A7A4C
HINT_BAR_BG = (0.055, 0.067, 0.055)  # hint strip ink #0E110E (draw ~0.88 alpha)
HINT_HAIRLINE = (0.180, 0.165, 0.110)  # hint strip top hairline #2E2A1C
BRASS_KEY_BORDER = (0.290, 0.235, 0.133)  # brass key border #4A3C22
BRASS_KEY_BG = (0.129, 0.106, 0.063)      # brass key fill  #211B10
PLATE_INK = (0.051, 0.071, 0.063)   # HUD plate ink over 3D #0D1210 (@0.93)

# --- FORENSICS ledger paper (approved mock: ledger2_final_debrief.html) ---------
# NEW token family — light paper on the dark desk.  These are DOCUMENT INKS
# (a typed after-action sheet), not the HUD phosphor families above; never
# repurpose the HUD tokens for the paper, or these for the HUD.
PAPER_BG = (0.918, 0.878, 0.784)     # paper sheet        #EAE0C8
PAPER_FIELD = (0.906, 0.867, 0.761)  # plot field fill    #E7DDC2
PAPER_SELECT = (0.875, 0.827, 0.706) # selected stub fill #DFD3B4
PAPER_TAG = (0.937, 0.902, 0.804)    # pin-label fill     #EFE6CD
PAPER_INK = (0.149, 0.125, 0.059)    # typed ink          #26200F
PAPER_MUTED = (0.420, 0.384, 0.314)  # muted ink          #6B6250
PAPER_HATCH = (0.725, 0.678, 0.553)  # ground residue     #B9AD8D
PAPER_DESK = (0.082, 0.063, 0.035)   # desk field         #151009
PAPER_DESK_EDGE = (0.043, 0.031, 0.016)  # desk vignette edge #0B0804
PAPER_CHIP_BG = (0.055, 0.043, 0.024)    # clock chip fill    #0E0B06
PAPER_CHIP_EDGE = (0.227, 0.184, 0.110)  # clock chip border  #3A2F1C
PAPER_CHIP_TEXT = (0.851, 0.643, 0.255)  # clock chip amber   #D9A441
PAPER_CHIP_MUTED = (0.420, 0.353, 0.208) # clock chip dim     #6B5A35
PAPER_HEADLINE = (0.541, 0.478, 0.298)   # desk header text   #8A7A4C
INK_RED = (0.659, 0.208, 0.165)      # loss/intercept ink #A8352A
INK_TEAL = (0.125, 0.392, 0.494)     # plotted-path ink   #20647E
INK_AMBER = (0.541, 0.435, 0.208)    # fuel/illum ink     #8A6F35
INK_GREEN = (0.227, 0.420, 0.259)    # hit/launcher ink   #3A6B42
INK_VIOLET = (0.373, 0.294, 0.541)   # spare lane ink     #5F4B8A

# Grade families (spec §9): S/A green, B amber, C/D dusk-red; D adds the shame
# treatment (tinted bg + flat inset ring + blink).  (bg, border) per letter.
GRADE_COLS = {"S": OK_COL, "A": OK_COL, "B": WARN, "C": DANGER, "D": DANGER}
GRADE_TINTS = {
    "S": ((0.102, 0.141, 0.094), (0.243, 0.353, 0.235)),   # #1A2418 / #3E5A3C
    "A": ((0.102, 0.141, 0.094), (0.243, 0.353, 0.235)),
    "B": ((0.129, 0.106, 0.063), (0.290, 0.235, 0.133)),   # #211B10 / #4A3C22
    "C": ((0.141, 0.078, 0.071), (0.227, 0.149, 0.125)),   # #241412 / #3A2620
    "D": ((0.227, 0.102, 0.078), (0.290, 0.149, 0.125)),   # #3A1A14 / #4A2620
}
GRADE_VERDICTS = {"S": "FLAWLESS", "A": "CLEAN", "B": "ADEQUATE",
                  "C": "BELOW PAR", "D": "REVIEW ORDERED"}

# --- Layout grid (§1.5) + interaction constants (§1.4) --------------------------

COL_W = 560                         # menu/settings content column width
ROW_H = 40                          # interactive row pitch
GROUP_H = 24                        # settings group sub-header height
PAD = 16                            # panel inner padding
FOCUS_BAR_W = 3                     # selected-row left bar
TICK_LEG = 16.0                     # corner tick leg length (px, spec §5)
TICK_W = 2.0                        # corner tick stroke
RULE_CAP = 28.0                     # brass cap length on header rules (§5)
RULE_CAP_W = 3.0                    # brass cap stroke
PANEL_ALPHA = 0.92                  # menu panel fill alpha
PRESS_FLASH_S = 0.08                # press-flash duration before firing
PRESS_FLASH_A = 0.22                # press-flash fill alpha
FOOTER_MARGIN = 24                  # footer offset from screen edges
MENU_DIM_A = 0.45                   # main-menu scene dim (unused: flat BG0)
PAUSE_DIM_A = 0.65                  # pause dim over the frozen frame
WHEEL_ROWS = 3                      # settings rows per wheel notch
BTN_H = 32                          # settings button box height

GAME_VERSION = "v0.5.0"
BUILD_DATE = "2026-07-03"

TITLE_TEXT = "O N I K S"            # space-tracked (monospace atlas, §1.3)
SUBTITLE_TEXT = "ANTI-SHIP MISSILE SIMULATION"
FOOTER_LEFT = f"ONIKS PROTO {GAME_VERSION} - {BUILD_DATE}"
FOOTER_HINTS = "UP/DN SELECT  ENTER OK"

MAIN_ITEMS = ("SANDBOX", "COMBAT", "CAMPAIGN", "SETTINGS", "QUIT")
PAUSE_ITEMS = ("RESUME", "SETTINGS", "MAIN MENU")
CONFIRM_MAIN_MENU = "MAIN MENU - ENTER AGAIN TO CONFIRM"
CONFIRM_RESET = "ENTER AGAIN TO CONFIRM"
PAUSE_PANEL_W = 460
PAUSE_FOOTER = "ESC RESUME"

SETTINGS_HEADER = "SETTINGS / KEYBINDS"
SETTINGS_FOOTER = "ENTER REBIND   ESC BACK   R RESET ROW"
PRESS_KEY_TEXT = "[ PRESS KEY ]"
RESET_LABEL = "RESET DEFAULTS"
BACK_LABEL = "BACK"


def move_selection(idx: int, delta: int, count: int) -> int:
    """Step the selected index with wrap-around (empty list stays at 0)."""
    return (idx + delta) % count if count else 0


def _fmt_clock(t: float) -> str:
    """Sim clock as MM:SS, growing to H:MM:SS past an hour."""
    t = max(0.0, float(t))
    hh, rem = divmod(int(t), 3600)
    mm, ss = divmod(rem, 60)
    return f"{hh}:{mm:02d}:{ss:02d}" if hh else f"{mm:02d}:{ss:02d}"


# --- Shared panel chrome (§1.2): fill + 1px border + amber corner ticks ---------

def draw_panel(text, x, y, w, h, alpha=PANEL_ALPHA, tick_col=ACCENT_DIM,
               strip=False, ticks=True, fill=None) -> None:
    """Wardroom PLATE (spec §5): BG1 fill, 1px hairline border, a 1px
    top inset highlight (rgba 255,255,255,.05 — the powered-surface cue),
    and the corner-tick brackets (16px legs, 2px, brass-dim) at top-left +
    bottom-right.  ``strip`` adds the 2px brass powered-on strip (0.12
    alpha) along the top inner edge of the ACTIVE panel; ``ticks=False``
    drops the brackets for quiet in-grid plates (hero plates keep them);
    ``fill`` overrides the fill RGB (the HUD's darker over-3D ink)."""
    x, y, w, h = round(x), round(y), round(w), round(h)
    f = fill if fill is not None else BG1
    text.draw_rect(x, y, w, h, (*f, alpha))
    text.draw_lines([(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)],
                    (*LINE_COL, 1.0), 1.0)
    text.draw_rect(x + 1, y + 1, w - 2, 1, (1.0, 1.0, 1.0, 0.05))
    if ticks:
        # Spec §5: L-brackets on the top-left + bottom-right corners only.
        text.draw_lines([(x + TICK_LEG, y), (x, y), (x, y + TICK_LEG)],
                        (*tick_col, 1.0), TICK_W)
        text.draw_lines([(x + w - TICK_LEG, y + h), (x + w, y + h),
                         (x + w, y + h - TICK_LEG)], (*tick_col, 1.0), TICK_W)
    if strip:
        text.draw_rect(x + 1, y + 2, w - 2, 2, (*ACCENT, 0.12))


def draw_header_rule(text, x, y, w) -> None:
    """RULE WITH CAP (§5): 1px hairline; 28x3px brass cap flush left."""
    text.draw_lines([(x, y), (x + w, y)], (*LINE_COL, 1.0), 1.0)
    text.draw_lines([(x, y), (x + RULE_CAP, y)], (*ACCENT, 1.0), RULE_CAP_W)


def draw_plate_header(text, x, y, w, label, chip_col, *, active=False) -> float:
    """PLATE HEADER (§5): 8x8 family-color chip + 14pt muted label, then a
    hairline rule across the plate's inner width.  ``active`` renders the
    label in brass (the selected-platform variant, widget sheet 08).
    Returns the content y just below the rule."""
    lh = text.line_height(SMALL_SIZE)
    text.draw_rect(round(x), round(y + (lh - 8) / 2), 8, 8, (*chip_col, 1.0))
    text.draw_text(x + 16, y, label, (ACCENT if active else MUTED), SMALL_SIZE)
    ry = round(y + lh + 6)
    text.draw_lines([(x, ry), (x + w, ry)], (*LINE_COL, 1.0), 1.0)
    return float(ry + 1)


def draw_brass_key(text, x, y, w, h, label, *, focused=False, pressed=False,
                   size=SMALL_SIZE) -> None:
    """BRASS KEY (§5/§6): bordered #4A3C22 plate, #211B10 fill, brass CAPS
    label centered.  FOCUS adds the flat 2px translucent brass ring; PRESS
    inverts (brass fill, dark text) for the 80ms flash."""
    x, y, w, h = round(x), round(y), round(w), round(h)
    if pressed:
        text.draw_rect(x, y, w, h, (*ACCENT, 1.0))
        lab_col = BG0
    else:
        text.draw_rect(x, y, w, h, (*BRASS_KEY_BG, 1.0))
        lab_col = ACCENT
    text.draw_lines([(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)],
                    (*BRASS_KEY_BORDER, 1.0), 1.0)
    if focused and not pressed:
        # Flat ring: a 2px brass outline inset 2px (no blur — stacked rects).
        text.draw_lines([(x + 2, y + 2), (x + w - 2, y + 2),
                         (x + w - 2, y + h - 2), (x + 2, y + h - 2),
                         (x + 2, y + 2)], (*ACCENT, 0.55), 2.0)
    lh = text.line_height(size)
    tw = text.text_width(label, size)
    text.draw_text(round(x + (w - tw) / 2), round(y + (h - lh) / 2), label,
                   lab_col, size)


def draw_hint_bar(text, w, h, hint) -> float:
    """HINT BAR (§5): full-width bottom strip — translucent ink band, 1px
    warm hairline on top, dot-separated 14pt hint text centered.  Returns
    the strip's top edge y (callers keep content above it)."""
    lh = text.line_height(SMALL_SIZE)
    bar_h = lh + 14
    y = h - bar_h
    text.draw_rect(0, y, w, bar_h, (*HINT_BAR_BG, 0.88))
    text.draw_lines([(0, y), (w, y)], (*HINT_HAIRLINE, 1.0), 1.0)
    tw = text.text_width(hint, SMALL_SIZE)
    text.draw_text(round((w - tw) / 2), y + 7, hint, HINT_COL, SMALL_SIZE)
    return float(y)


# --- Widget primitive library (spec 08): the shared UI vocabulary ---------------
#
# Pure, GL-free draw helpers that every later COMBAT surface composes from.
# They only touch the TextRenderer draw + measurement API (draw_text/draw_rect/
# draw_lines/text_width/line_height), so a FakeText recorder unit-tests them
# headless. Colors come ONLY from the palette tokens above — never a literal
# RGB at a call site. The in-game (alpha 0.55) variants live in
# game/hud_widgets.py and delegate straight back here via the ``alpha=`` param.

# Semantic state -> palette token. Encodes the load-bearing fog-of-war color
# contract (ui_reference.md, MEMORY "physics not dice"): friendly/ready/armed
# read OK_COL green; reloading/transient read WARN amber; inbound/destroyed/
# terminal read DANGER red; labels read MUTED; the single brand accent is
# ACCENT. Sensor-estimate data must look different from friendly truth.
SEMANTIC_COLORS = {
    "READY": OK_COL,         # confirmed-good / own forces -> green
    "ARMED": OK_COL,
    "FRIENDLY": OK_COL,
    "RELOADING": WARN,       # in-flux / momentary -> amber
    "TRANSIENT": WARN,
    "EMPTY": DISABLED,       # spent tube / no round to chamber -> greyed
    "INBOUND": DANGER,       # threat / killed / final -> red
    "DESTROYED": DANGER,
    "TERMINAL": DANGER,
    "ESTIMATE": BELIEF,      # sensor guess: teal belief family, never truth
    "LABEL": MUTED,          # field labels / secondary copy -> muted
    "ACCENT": ACCENT,        # the one brand accent
    "DISABLED": DISABLED,    # greyed / unavailable
}

# Derived (single source of truth): the recognised state tokens are exactly the
# SEMANTIC_COLORS keys, so tests parametrize over this without a parallel list.
SEMANTIC_STATES = tuple(SEMANTIC_COLORS)

BADGE_PAD_X = 6.0           # horizontal padding either side of a badge label
BADGE_PAD_Y = 3.0           # vertical padding above/below a badge label
BADGE_FILL_A = 0.18         # badge body fill alpha (the tinted state wash)
COMPASS_SEG = 24            # bearing-ring segments (360 / 24 = 15 deg steps)
COMPASS_TICK = 4.0          # radial bearing-tick length (px, inward from rim)
COMPASS_N_LEN = 5.0         # length of the North marker tick above the ring
THUMB_W = 4                 # scroll-list thumb width (px); track is THUMB_TRACK
THUMB_TRACK = 2             # scroll-list track width (px)


def _clamp01(v: float) -> float:
    """Clamp ``v`` into [0, 1]."""
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else float(v)


def badge(text, label, x, y, state, size=SMALL_SIZE, *, alpha=BADGE_FILL_A) -> float:
    """A small status pill at (x, y): one tinted fill + one 1px border
    polyline + one centered CAPS label. Color is ``SEMANTIC_COLORS[state]``;
    unknown states fall back to MUTED. Returns the badge WIDTH (for layout).

    ``alpha`` is the body-fill alpha: the menu default is the faint
    ``BADGE_FILL_A`` tint; the HUD variant passes the 0.55 panel alpha so the
    pill reads as in-game chrome (see game/hud_widgets.py). The border + label
    are always opaque so the badge stays legible over the battle.
    """
    col = SEMANTIC_COLORS.get(state, MUTED)[:3]
    lab = str(label).upper()
    lh = text.line_height(size)
    tw = text.text_width(lab, size)
    w = round(tw + 2 * BADGE_PAD_X)
    h = round(lh + 2 * BADGE_PAD_Y)
    x, y = round(x), round(y)
    # Body wash in the state color at the requested fill alpha, then a 1px
    # closed border.
    text.draw_rect(x, y, w, h, (*col, alpha))
    text.draw_lines([(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)],
                    (*col, 1.0), 1.0)
    # Centered label.
    tx = round(x + (w - tw) / 2.0)
    ty = round(y + (h - lh) / 2.0)
    text.draw_text(tx, ty, lab, (*col, 1.0), size)
    return float(w)


def gauge_bar(text, x, y, w, h, frac, col, *, ticks=0, alpha=1.0) -> None:
    """A horizontal gauge at (x, y): a 1px LINE track box, then a filled
    portion of width ``w * clamp(frac, 0, 1)`` in ``col``. No fill quad is
    emitted when frac <= 0. ``ticks`` (>0) draws evenly-spaced vertical tick
    marks across the track. ``alpha`` scales the fill alpha for the HUD variant.
    """
    x, y, w, h = round(x), round(y), round(w), round(h)
    # Track outline (LINE_COL, 1px closed box).
    text.draw_lines([(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)],
                    (*LINE_COL, 1.0), 1.0)
    f = _clamp01(frac)
    if f > 0.0:
        fw = round(w * f)
        if fw > 0:
            c = col[:3]
            a = (col[3] if len(col) > 3 else 1.0) * alpha
            text.draw_rect(x, y, fw, h, (*c, a))
    if ticks and ticks > 0:
        for i in range(1, int(ticks)):
            tx = round(x + w * i / float(ticks))
            text.draw_lines([(tx, y), (tx, y + h)], (*LINE_COL, 1.0), 1.0)


def mini_compass(text, cx, cy, r, bearings) -> None:
    """A bearing rose centered at (cx, cy), radius ``r``: a closed ring drawn
    as a 24-segment polyline (15 deg steps) starting at North, an "N" tick at
    the top, and one short radial tick per bearing. Bearing 0 = North = up,
    clockwise; screen y grows downward, so a tick's OUTER tip sits at
    ``(cx + r*sin(theta), cy - r*cos(theta))`` with ``theta = radians(bearing)``.
    """
    # The ring: vertices at every 15 deg, closed back to North.
    ring = []
    for i in range(COMPASS_SEG + 1):
        a = math.radians(i * (360.0 / COMPASS_SEG))
        ring.append((cx + r * math.sin(a), cy - r * math.cos(a)))
    text.draw_lines(ring, (*LINE_COL, 1.0), 1.0)
    # North marker: a short accent tick poking up above the rim at bearing 0.
    text.draw_lines([(cx, cy - r), (cx, cy - r - COMPASS_N_LEN)],
                    (*ACCENT, 1.0), 1.5)
    # One radial bearing tick per bearing: from just inside the rim out to the
    # rim. The outer tip lands exactly on the radius (the locked contract).
    for brg in bearings:
        th = math.radians(float(brg))
        s, c = math.sin(th), math.cos(th)
        outer = (cx + r * s, cy - r * c)
        inner = (cx + (r - COMPASS_TICK) * s, cy - (r - COMPASS_TICK) * c)
        text.draw_lines([inner, outer], (*WARN, 1.0), 1.5)


TAB_UNDERLINE_DY = 2        # gap (px) between tab baseline and its underline
TAB_UNDERLINE_W = 1.5       # active-tab underline stroke (matches combat_setup)


def tab_strip(text, x, y, labels, active, size=SMALL_SIZE, *,
              gap=PAD, tab_w=None) -> None:
    """An underline-tab row at (x, y): the active label in ACCENT (the rest
    MUTED), each active one carrying a ``TAB_UNDERLINE_W`` px ACCENT underline.
    Pure; emits no fill quads.

    Two column layouts:
      * ``tab_w is None`` (default) — labels are packed left-to-right by their
        measured width with ``gap`` px between them (the generic strip).
      * ``tab_w`` given — fixed-grid layout: tab ``i`` sits at ``x + i*tab_w``
        regardless of label width (combat_setup's even-column tab bar). In this
        mode the call is byte-identical to combat_setup.py's old inline loop:
        same text x/y, same label-color token passed through unchanged, and the
        underline runs from ``(x+i*tab_w, y+lh+TAB_UNDERLINE_DY)`` to
        ``(x+i*tab_w + text_width(label), ...)`` in ACCENT at TAB_UNDERLINE_W.
    """
    lh = text.line_height(size)
    tx = float(x)
    for i, lab in enumerate(labels):
        is_active = (i == active)
        col = ACCENT if is_active else MUTED
        lw = text.text_width(str(lab), size)
        if tab_w is not None:
            # Fixed-grid mode: each tab on an even column at integer x, the
            # label color token passed through unchanged, and the underline
            # endpoints left un-rounded — byte-identical to combat_setup's loop.
            ix = x + i * tab_w
            text.draw_text(ix, y, str(lab), col, size)
            ux1 = ix + lw
        else:
            # Generic left-packed mode: round the column origin and the
            # underline end (the historical default behavior).
            ix = round(tx)
            text.draw_text(ix, y, str(lab), (*col, 1.0), size)
            ux1 = round(ix + lw)
        if is_active:
            uy = y + lh + TAB_UNDERLINE_DY
            text.draw_lines([(ix, uy), (ux1, uy)],
                            (*ACCENT, 1.0), TAB_UNDERLINE_W)
        tx += lw + gap


# --- Settings display list + scroll math (pure, unit-tested) --------------------

def settings_entries(conflict_aid: str | None = None) -> list[tuple]:
    """Display rows in registry order: ("header", group) sub-headers,
    ("action", ActionDef) rows, and — while a conflict is pending — one
    ("conflict", action_id) sub-row directly under the conflicted row."""
    entries: list[tuple] = []
    group = None
    for a in ACTIONS:
        if a.group != group:
            group = a.group
            entries.append(("header", group))
        entries.append(("action", a))
        if conflict_aid == a.id:
            entries.append(("conflict", a.id))
    return entries


def entry_height(entry) -> int:
    return ROW_H if entry[0] == "action" else GROUP_H


def visible_count(entries, start: int, view_h: float) -> int:
    """How many entries from ``start`` fit FULLY in ``view_h`` pixels
    (scroll is whole-row, so partially visible rows never draw)."""
    used = 0.0
    n = 0
    for e in entries[start:]:
        used += entry_height(e)
        if used > view_h:
            break
        n += 1
    return n


def scroll_to_focus(entries, scroll_idx: int, target_idx: int,
                    view_h: float) -> int:
    """Smallest scroll motion keeping ``target_idx`` fully visible with a
    1-row lookahead margin (ui_reference.md §3.4)."""
    if target_idx <= scroll_idx:
        return max(0, target_idx - 1)
    s = scroll_idx
    while s < target_idx:
        n = visible_count(entries, s, view_h)
        if (target_idx < s + n - 1
                or (s + n >= len(entries) and target_idx < s + n)):
            break
        s += 1
    return s


def max_scroll(entries, view_h: float) -> int:
    """Topmost index that still shows the list tail (no over-scroll)."""
    used = 0.0
    s = len(entries) - 1
    for i in range(len(entries) - 1, -1, -1):
        used += entry_height(entries[i])
        if used > view_h:
            return min(i + 1, len(entries) - 1)
        s = i
    return 0


def scroll_list(text, items, *, x, y, w, view_h, row_h, scroll, focus,
                draw_row) -> int:
    """Uniform-row scroll viewport — the whole-row twin of visible_count/
    scroll_to_focus/max_scroll above (those handle heterogeneous settings
    rows; this one handles fixed-pitch lists, the common COMBAT case).

    Draws the window of ``items`` that fully fits ``view_h`` at pitch
    ``row_h``, starting at ``scroll`` (clamped so ``focus`` stays visible and
    the tail never over-scrolls). For each visible item it calls
    ``draw_row(item, index, row_x, row_y)`` — the caller owns row rendering.
    When the list overflows the viewport it also paints a ``THUMB_TRACK``-px
    LINE track and a ``THUMB_W``-px ACCENT_DIM thumb on the right edge.
    Returns the (clamped) scroll index actually used. Pure / headless.
    """
    n = len(items)
    if n == 0 or row_h <= 0:                     # nothing to show / bad pitch
        return 0
    cap = max(1, int(view_h // row_h))          # whole rows that fit
    top_max = max(0, n - cap)                   # tail-anchored max scroll
    s = max(0, min(int(scroll), top_max))
    # Keep focus on screen with the same 1-row lookahead idiom as settings.
    if focus < s:
        s = max(0, focus)
    elif focus >= s + cap:
        s = min(top_max, focus - cap + 1)
    end = min(n, s + cap)
    ry = y
    for i in range(s, end):
        draw_row(items[i], i, x, ry)
        ry += row_h
    if n > cap:
        # Track down the right edge, then a proportional thumb over it.
        bar_x = x + w - THUMB_W
        text.draw_rect(bar_x, y, THUMB_TRACK, view_h, (*LINE_COL, 1.0))
        thumb_h = max(row_h, view_h * cap / float(n))
        travel = view_h - thumb_h
        thumb_y = y + (travel * s / float(top_max) if top_max else 0.0)
        text.draw_rect(bar_x, round(thumb_y), THUMB_W, round(thumb_h),
                       (*ACCENT_DIM, 1.0))
    return s


# --- State machine ---------------------------------------------------------------

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


# --- Menu screens ----------------------------------------------------------------

class _ListScreen(GameState):
    """Shared row-list mechanics: wrap navigation, hover/click hit boxes and
    the 80 ms press-flash that defers the action one beat (§1.4). Subclasses
    define ``items`` and ``_fire(name)``; ``_tick_pending`` runs from render
    (or directly in headless tests)."""

    items: tuple = ()

    def __init__(self, app):
        super().__init__(app)
        self._gl = None
        self.text = None
        self.sel = 0
        self._rects: list = []          # per-item hit boxes, set by render
        self._pending: str | None = None
        self._pending_left = 0.0

    def enter(self) -> None:
        pygame.event.set_grab(False)    # in case a mouse-look drag was live
        pygame.mouse.set_visible(True)
        if self.text is None:
            import OpenGL.GL as gl
            self._gl = gl
            self.text = self.app.ui_text()
        self.sel = 0
        self._rects = []
        self._pending = None

    def effective_time_scale(self) -> float:
        return 0.0                      # menus freeze the sim

    # ------------------------------------------------------------- input

    def handle_event(self, ev) -> None:
        if self._pending is not None:
            return                      # one beat of press-flash: input off
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_UP:
                self._move(-1)
            elif ev.key == pygame.K_DOWN:
                self._move(1)
            elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._activate(self.items[self.sel])
            elif ev.key == pygame.K_ESCAPE:
                self._escape()
        elif ev.type == pygame.MOUSEMOTION:
            hit = self._hit(ev.pos)
            if hit is not None and hit != self.sel:
                self.sel = hit
                self._moved()
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            hit = self._hit(ev.pos)
            if hit is not None:
                self.sel = hit
                self._activate(self.items[hit])

    def _move(self, delta: int) -> None:
        self.sel = move_selection(self.sel, delta, len(self.items))
        self.app.audio.ui_click()
        self._moved()

    def _moved(self) -> None:
        pass                            # pause menu disarms its confirm here

    def _hit(self, pos):
        for i, (x0, y0, x1, y1) in enumerate(self._rects):
            if x0 <= pos[0] <= x1 and y0 <= pos[1] <= y1:
                return i
        return None

    def _activate(self, name: str) -> None:
        self.app.audio.ui_click()
        self._pending = name
        self._pending_left = PRESS_FLASH_S

    def _tick_pending(self, dt: float) -> None:
        if self._pending is None:
            return
        self._pending_left -= dt
        if self._pending_left <= 0.0:
            name, self._pending = self._pending, None
            self._fire(name)

    def _escape(self) -> None:
        pass

    def _fire(self, name: str) -> None:
        raise NotImplementedError

    # ------------------------------------------------------------- drawing

    def _draw_rows(self, x, y0, w, danger_items=(), warn_items=(),
                   text_for=None) -> None:
        """The item list: 40px rows, hover/selected fill + 3px left bar."""
        text = self.text
        self._rects = []
        lh = text.line_height(BODY_SIZE)
        for i, name in enumerate(self.items):
            y = y0 + i * ROW_H
            selected = i == self.sel
            col = MUTED
            if selected:
                col = (DANGER if name in danger_items
                       else WARN if name in warn_items else ACCENT)
                text.draw_rect(x, y, w, ROW_H, (*BG2, 1.0))
                text.draw_rect(x, y, FOCUS_BAR_W, ROW_H, (*col, 1.0))
            if self._pending == name:
                text.draw_rect(x, y, w, ROW_H, (*PRESS_FILL, 1.0))
            label = text_for(name) if text_for is not None else name
            text.draw_text(x + PAD, y + (ROW_H - lh) // 2, label, col)
            self._rects.append((x, y, x + w, y + ROW_H))


class MenuState(_ListScreen):
    """Main menu: SANDBOX / COMBAT / SETTINGS / QUIT over a flat BG0 field, with the
    corner-ticked title panel and the version footer (ui_reference.md §2.1).
    ESC at the title screen quits the app."""

    items = MAIN_ITEMS

    def _escape(self) -> None:
        self.app.running = False

    def _fire(self, name: str) -> None:
        if name == "QUIT":
            self.app.running = False
        elif name == "SANDBOX":
            self.app.start_sandbox()    # fresh world
        elif name == "COMBAT":
            self.app.open_combat_setup()  # setup screen, then the battle
        elif name == "CAMPAIGN":
            self.app.open_campaign()    # hub: resume the save or start fresh
        elif name == "SETTINGS":
            self.app.open_settings(self)

    def render(self, dt_real: float) -> None:
        self._tick_pending(dt_real)
        gl = self._gl
        gl.glClearColor(BG0[0], BG0[1], BG0[2], 1.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        w, h = self.app.window.size()
        text = self.text
        x = (w - COL_W) // 2

        # Title panel: corner ticks + powered-on strip, space-tracked title.
        title_lh = text.line_height(TITLE_SIZE)
        small_lh = text.line_height(SMALL_SIZE)
        panel_h = PAD + title_lh + 4 + small_lh + PAD
        draw_panel(text, x, 96, COL_W, panel_h, strip=True)
        text.draw_text(x + PAD, 96 + PAD, TITLE_TEXT, TEXT_COL, TITLE_SIZE)
        text.draw_text(x + PAD, 96 + PAD + title_lh + 4, SUBTITLE_TEXT,
                       MUTED, SMALL_SIZE)

        # Divider with the amber cap, then the item rows.
        rule_y = 96 + panel_h + 32
        draw_header_rule(text, x, rule_y, COL_W)
        self._draw_rows(x, rule_y + 24, COL_W, danger_items=("QUIT",))

        # Footer: version left, key hints right (both 14pt).
        fy = h - FOOTER_MARGIN - small_lh
        text.draw_text(FOOTER_MARGIN, fy, FOOTER_LEFT, DISABLED, SMALL_SIZE)
        hint_w = text.text_width(FOOTER_HINTS, SMALL_SIZE)
        text.draw_text(w - FOOTER_MARGIN - hint_w, fy, FOOTER_HINTS,
                       ACCENT_DIM, SMALL_SIZE)
        text.flush(w, h)


class PauseState(_ListScreen):
    """Pause menu over the frozen sim frame, dimmed 65% (§2.2): RESUME /
    SETTINGS / MAIN MENU, sim clock in the header, MAIN MENU double-ENTER
    confirmed (the session is discarded — data loss)."""

    items = PAUSE_ITEMS

    def __init__(self, app):
        super().__init__(app)
        self.confirm_armed = False

    def enter(self) -> None:
        super().enter()
        self.confirm_armed = False

    def _escape(self) -> None:
        self._fire("RESUME")

    def _moved(self) -> None:
        self.confirm_armed = False

    def _activate(self, name: str) -> None:
        if name == "MAIN MENU" and not self.confirm_armed:
            self.confirm_armed = True
            self.app.audio.ui_click()
            return
        super()._activate(name)

    def _fire(self, name: str) -> None:
        if name == "RESUME":
            self.app.resume()
        elif name == "SETTINGS":
            self.app.open_settings(self)
        elif name == "MAIN MENU":
            self.confirm_armed = False
            self.app.quit_to_menu()

    def render(self, dt_real: float) -> None:
        self._tick_pending(dt_real)
        w, h = self.app.window.size()
        text = self.text
        sandbox = self.app.sandbox
        if sandbox is not None:
            sandbox.render_frozen()     # the suspended scene, then dim it
        else:
            gl = self._gl
            gl.glClearColor(BG0[0], BG0[1], BG0[2], 1.0)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        text.draw_rect(0, 0, w, h, (*BG0, PAUSE_DIM_A))

        head_lh = text.line_height(HEADER_SIZE)
        small_lh = text.line_height(SMALL_SIZE)
        inner_w = PAUSE_PANEL_W - 2 * PAD
        panel_h = (PAD + head_lh + 2 + small_lh + 10 + 10
                   + len(self.items) * ROW_H + PAD)
        x = (w - PAUSE_PANEL_W) // 2
        y = (h - panel_h) // 2 - 40
        draw_panel(text, x, y, PAUSE_PANEL_W, panel_h, strip=True)
        text.draw_text(x + PAD, y + PAD, "PAUSED", ACCENT, HEADER_SIZE)
        clock = "T+" + _fmt_clock(sandbox.world.sim_time) if sandbox else "T+--:--"
        scale = (sandbox.controls.requested_scale if sandbox else 1.0)
        text.draw_text(x + PAD, y + PAD + head_lh + 2,
                       f"{clock}  x{scale:g}", MUTED, SMALL_SIZE)
        rule_y = y + PAD + head_lh + 2 + small_lh + 10
        draw_header_rule(text, x + PAD, rule_y, inner_w)
        self._draw_rows(x + PAD, rule_y + 10, inner_w,
                        warn_items=("MAIN MENU",),
                        text_for=self._row_text)
        if self.confirm_armed:          # armed row re-tints DANGER
            i = self.items.index("MAIN MENU")
            ry = rule_y + 10 + i * ROW_H
            lh = text.line_height(BODY_SIZE)
            if i == self.sel:
                text.draw_rect(x + PAD, ry, FOCUS_BAR_W, ROW_H, (*DANGER, 1.0))
            text.draw_text(x + 2 * PAD, ry + (ROW_H - lh) // 2,
                           CONFIRM_MAIN_MENU, DANGER)

        foot_w = text.text_width(PAUSE_FOOTER, SMALL_SIZE)
        text.draw_text((w - foot_w) // 2, y + panel_h + FOOTER_MARGIN,
                       PAUSE_FOOTER, ACCENT_DIM, SMALL_SIZE)
        text.flush(w, h)

    def _row_text(self, name: str) -> str:
        if name == "MAIN MENU" and self.confirm_armed:
            return ""                   # the DANGER overlay text replaces it
        return name


class SettingsState(GameState):
    """Settings / keybinds screen (§3): grouped two-column list, PRESS-KEY
    capture, conflict swap sub-row, per-row + global reset, wheel scroll.
    Reachable from the main menu AND the pause menu (``back_to``)."""

    def __init__(self, app):
        super().__init__(app)
        self._gl = None
        self.text = None
        self.back_to: GameState | None = None
        self.focusables = [a.id for a in ACTIONS if not a.reserved]
        self.focusables += ["RESET", "BACK"]
        self.focus = 0
        self.scroll_idx = 0
        self.listening: str | None = None       # action id capturing a key
        self.conflict: tuple | None = None      # (aid, key, other_aid)
        self.reset_armed = False
        self._pulse_t = 0.0             # PRESS KEY breathing fill clock
        self._flash: list | None = None         # [focusable, time_left]
        self._view_h = 480.0            # updated every render; test default
        self._hit_rects: list = []      # (focusable_index, rect) from render

    def enter(self) -> None:
        pygame.event.set_grab(False)
        pygame.mouse.set_visible(True)
        if self.text is None:
            import OpenGL.GL as gl
            self._gl = gl
            self.text = self.app.ui_text()
        self.focus = 0
        self.scroll_idx = 0
        self.listening = None
        self.conflict = None
        self.reset_armed = False
        self._hit_rects = []

    def effective_time_scale(self) -> float:
        return 0.0

    # --------------------------------------------------------------- input

    def handle_event(self, ev) -> None:
        if ev.type == pygame.KEYDOWN:
            if self.listening is not None:
                self._capture(ev.key)
            elif self.conflict is not None:
                self._resolve_conflict(ev.key)
            else:
                self._nav_key(ev.key)
        elif self.listening is None and self.conflict is None:
            self._mouse(ev)

    def _capture(self, key: int) -> None:
        """Next KEYDOWN while listening: bind it, or open the swap offer.
        ESC cancels; the reserved keys (ESC/F1) can never be captured."""
        aid = self.listening
        self.listening = None
        k = normalize_key(key)
        if k in RESERVED_KEYS:
            self.app.audio.ui_click()   # cancel beep
            return
        other = self.app.keybinds.conflict(aid, k)
        if other is None:
            self.app.keybinds.rebind(aid, k)
            self._flash = [aid, PRESS_FLASH_S]
            self.app.audio.ui_click()
        else:
            self.conflict = (aid, k, other)

    def _resolve_conflict(self, key: int) -> None:
        aid, k, _other = self.conflict
        if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.conflict = None
            self.app.keybinds.rebind(aid, k)    # atomic swap inside
            self._flash = [aid, PRESS_FLASH_S]
            self.app.audio.ui_click()
        elif key == pygame.K_ESCAPE:
            self.conflict = None
            self.app.audio.ui_click()

    def _nav_key(self, key: int) -> None:
        if key == pygame.K_UP:
            self._move_focus(-1)
        elif key == pygame.K_DOWN:
            self._move_focus(1)
        elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._activate(self.focusables[self.focus])
        elif key == pygame.K_r:
            target = self.focusables[self.focus]
            if target not in ("RESET", "BACK"):
                self.app.keybinds.reset_row(target)
                self._flash = [target, PRESS_FLASH_S]
                self.app.audio.ui_click()
        elif key == pygame.K_ESCAPE:
            self._back()

    def _mouse(self, ev) -> None:
        if ev.type == pygame.MOUSEWHEEL:
            entries = settings_entries()
            self.scroll_idx = max(0, min(
                self.scroll_idx - ev.y * WHEEL_ROWS,
                max_scroll(entries, self._view_h)))
        elif ev.type == pygame.MOUSEMOTION:
            hit = self._hit(ev.pos)
            if hit is not None and hit != self.focus:
                self.focus = hit
                self.reset_armed = False
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            hit = self._hit(ev.pos)
            if hit is not None:
                self.focus = hit
                self._activate(self.focusables[hit])

    def _hit(self, pos):
        for idx, (x0, y0, x1, y1) in self._hit_rects:
            if x0 <= pos[0] <= x1 and y0 <= pos[1] <= y1:
                return idx
        return None

    def _move_focus(self, delta: int) -> None:
        self.focus = move_selection(self.focus, delta, len(self.focusables))
        self.reset_armed = False
        self.app.audio.ui_click()
        target = self.focusables[self.focus]
        if target not in ("RESET", "BACK"):     # keep the row in view
            entries = settings_entries()
            idx = next(i for i, e in enumerate(entries)
                       if e[0] == "action" and e[1].id == target)
            self.scroll_idx = scroll_to_focus(entries, self.scroll_idx, idx,
                                              self._view_h)

    def _activate(self, target: str) -> None:
        if target == "BACK":
            self.app.audio.ui_click()
            self._back()
        elif target == "RESET":
            self.app.audio.ui_click()
            if self.reset_armed:
                self.reset_armed = False
                self.app.keybinds.reset_all()
                self._flash = ["RESET", PRESS_FLASH_S]
            else:
                self.reset_armed = True
        else:
            self.listening = target
            self.reset_armed = False
            self._pulse_t = 0.0
            self.app.audio.ui_click()

    def _back(self) -> None:
        self.app.states.switch(self.back_to or self.app.menu)

    # -------------------------------------------------------------- render

    def render(self, dt_real: float) -> None:
        self._pulse_t += dt_real
        if self._flash is not None:
            self._flash[1] -= dt_real
            if self._flash[1] <= 0.0:
                self._flash = None
        gl = self._gl
        gl.glClearColor(BG0[0], BG0[1], BG0[2], 1.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        w, h = self.app.window.size()
        text = self.text
        x = (w - COL_W) // 2
        self._hit_rects = []

        head_lh = text.line_height(HEADER_SIZE)
        small_lh = text.line_height(SMALL_SIZE)
        body_lh = text.line_height(BODY_SIZE)
        text.draw_text(x, 48, SETTINGS_HEADER, ACCENT, HEADER_SIZE)
        rule_y = 48 + head_lh + 8
        draw_header_rule(text, x, rule_y, COL_W)

        panel_y = rule_y + PAD
        panel_h = h - panel_y - 120     # buttons + footer live below
        draw_panel(text, x, panel_y, COL_W, panel_h, strip=True)

        # Column headers + divider.
        ch_y = panel_y + 8
        text.draw_text(x + PAD, ch_y, "ACTION", MUTED, SMALL_SIZE)
        bw = text.text_width("BINDING", SMALL_SIZE)
        text.draw_text(x + COL_W - PAD - 8 - bw, ch_y, "BINDING", MUTED,
                       SMALL_SIZE)              # right edge = binding cells
        div_y = ch_y + small_lh + 6
        text.draw_lines([(x + PAD, div_y), (x + COL_W - PAD, div_y)],
                        (*LINE_COL, 1.0), 1.0)

        # Scrolled rows (whole-row scroll: no partial rows, no scissor).
        top = div_y + 6
        bottom = panel_y + panel_h - 8
        self._view_h = float(bottom - top)
        entries = settings_entries(self.conflict[0] if self.conflict
                                   else None)
        self.scroll_idx = min(self.scroll_idx,
                              max_scroll(entries, self._view_h))
        y = top
        focused = self.focusables[self.focus]
        shown = 0
        for entry in entries[self.scroll_idx:]:
            eh = entry_height(entry)
            if y + eh > bottom:
                break
            self._draw_entry(entry, x, y, focused, small_lh, body_lh)
            y += eh
            shown += 1

        # Scrollbar: 2px LINE track, 4px ACCENT_DIM thumb (min 24px).
        track_x = x + COL_W - 6
        text.draw_rect(track_x + 1, top, 2, self._view_h, (*LINE_COL, 1.0))
        total = len(entries)
        if shown < total:
            frac = shown / total
            thumb_h = max(24.0, self._view_h * frac)
            denom = max(1, max_scroll(entries, self._view_h))
            t = min(1.0, self.scroll_idx / denom)
            ty = top + (self._view_h - thumb_h) * t
            text.draw_rect(track_x, ty, 4, thumb_h, (*ACCENT_DIM, 1.0))

        # Buttons + footer.
        by = panel_y + panel_h + PAD
        self._draw_button(x, by, RESET_LABEL if not self.reset_armed
                          else CONFIRM_RESET, "RESET", danger=self.reset_armed)
        bw_px = text.text_width(BACK_LABEL) + 2 * PAD
        self._draw_button(x + COL_W - bw_px, by, BACK_LABEL, "BACK")
        fy = h - FOOTER_MARGIN - small_lh
        text.draw_text(x, fy, SETTINGS_FOOTER, ACCENT_DIM, SMALL_SIZE)
        vw = text.text_width(GAME_VERSION, SMALL_SIZE)
        text.draw_text(x + COL_W - vw, fy, GAME_VERSION, DISABLED, SMALL_SIZE)
        text.flush(w, h)

    def _draw_entry(self, entry, x, y, focused, small_lh, body_lh) -> None:
        text = self.text
        kind = entry[0]
        if kind == "header":
            text.draw_text(x + PAD, y + (GROUP_H - small_lh) // 2, entry[1],
                           MUTED, SMALL_SIZE)
            return
        if kind == "conflict":
            aid, key, other = self.conflict
            other_label = next(a.label for a in ACTIONS if a.id == other)
            msg = (f"! {key_display(key)} IN USE: {other_label}"
                   " - ENTER SWAP / ESC CANCEL")
            text.draw_text(x + PAD, y + (GROUP_H - small_lh) // 2, msg,
                           DANGER, SMALL_SIZE)
            return
        a = entry[1]
        is_focus = a.id == focused
        label_col = (DISABLED if a.reserved
                     else ACCENT if is_focus else MUTED)
        value_col = DISABLED if a.reserved else TEXT_COL
        if is_focus:
            text.draw_rect(x, y, COL_W, ROW_H, (*BG2, 1.0))
            text.draw_rect(x, y, FOCUS_BAR_W, ROW_H, (*ACCENT, 1.0))
        if self._flash is not None and self._flash[0] == a.id:
            text.draw_rect(x, y, COL_W, ROW_H, (*PRESS_FILL, 1.0))
        ty = y + (ROW_H - body_lh) // 2
        text.draw_text(x + PAD, ty, a.label, label_col)
        if self.listening == a.id:
            # Breathing PRESS KEY cell: flat fill, sin alpha 0.10-0.20 @2Hz.
            alpha = 0.15 + 0.05 * math.sin(self._pulse_t * 4.0 * math.pi)
            cw = text.text_width(PRESS_KEY_TEXT) + PAD
            text.draw_rect(x + COL_W - 8 - PAD - cw, y + 4, cw + 8,
                           ROW_H - 8, (*ACCENT, alpha))
            vw = text.text_width(PRESS_KEY_TEXT)
            text.draw_text(x + COL_W - PAD - 8 - vw, ty, PRESS_KEY_TEXT,
                           ACCENT)
            return
        if self.conflict is not None and self.conflict[0] == a.id:
            value, value_col = key_display(self.conflict[1]), DANGER
        else:
            value = self.app.keybinds.name_for(a.id)
        vw = text.text_width(value)
        text.draw_text(x + COL_W - PAD - 8 - vw, ty, value, value_col)
        if not a.reserved:
            idx = self.focusables.index(a.id)
            self._hit_rects.append((idx, (x, y, x + COL_W, y + ROW_H)))

    def _draw_button(self, x, y, label, target, danger=False) -> None:
        text = self.text
        w = text.text_width(label) + 2 * PAD
        focused = self.focusables[self.focus] == target
        col = DANGER if danger else (ACCENT if focused else MUTED)
        if focused:
            text.draw_rect(x, y, w, BTN_H, (*BG2, 1.0))
        if self._flash is not None and self._flash[0] == target:
            text.draw_rect(x, y, w, BTN_H, (*PRESS_FILL, 1.0))
        text.draw_lines([(x, y), (x + w, y), (x + w, y + BTN_H),
                         (x, y + BTN_H), (x, y)], (*col, 1.0), 1.0)
        lh = text.line_height(BODY_SIZE)
        text.draw_text(x + PAD, y + (BTN_H - lh) // 2, label, col)
        idx = self.focusables.index(target)
        self._hit_rects.append((idx, (x, y, x + w, y + BTN_H)))
