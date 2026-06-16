"""Widget primitive library (game/states.py + game/hud_widgets.py): the shared
UI vocabulary. Pure + headless — a FakeText recorder captures the draw calls
(no GL), mirroring engine.text.TextRenderer's draw + measurement API."""

import math

import pytest

from game.states import (SEMANTIC_COLORS, SEMANTIC_STATES, badge, gauge_bar,
                         mini_compass)


class FakeText:
    """Records draw_* calls; stubs the measurement API deterministically."""

    def __init__(self):
        self.rects = []   # (x, y, w, h, rgba)
        self.lines = []   # (points, rgba, width)
        self.texts = []   # (x, y, s, color, size)

    def draw_rect(self, x, y, w, h, rgba):
        self.rects.append((x, y, w, h, tuple(rgba)))

    def draw_lines(self, points, rgba, width=1.5):
        self.lines.append(([tuple(p) for p in points], tuple(rgba), width))

    def draw_text(self, x, y, s, color=(1.0, 1.0, 1.0), size=18, scale=1.0):
        self.texts.append((x, y, s, tuple(color), size))

    def text_width(self, s, size=18):
        return float(len(s)) * (size * 0.6)

    def line_height(self, size=18):
        return int(size * 1.3)


def test_badge_emits_one_rect_one_border_one_text_and_returns_width():
    ft = FakeText()
    w = badge(ft, "READY", 100, 50, "READY")
    assert len(ft.rects) == 1            # exactly one fill
    assert len(ft.lines) == 1            # exactly one border polyline
    assert len(ft.texts) == 1            # exactly one centered label
    assert isinstance(w, (int, float)) and w > 0
    assert ft.texts[0][2] == "READY"     # CAPS state label


def test_badge_text_uses_semantic_color():
    ft = FakeText()
    badge(ft, "INBOUND", 0, 0, "INBOUND")
    assert ft.texts[0][3][:3] == tuple(SEMANTIC_COLORS["INBOUND"])[:3]


@pytest.mark.parametrize("state", SEMANTIC_STATES)
def test_semantic_colors_total_over_states(state):
    assert state in SEMANTIC_COLORS
    c = SEMANTIC_COLORS[state]
    assert len(c) in (3, 4) and all(0.0 <= float(v) <= 1.0 for v in c)


def test_gauge_bar_frac_zero_draws_no_fill():
    ft = FakeText()
    gauge_bar(ft, 10, 10, 100, 8, 0.0, (1.0, 1.0, 1.0))
    fills = [r for r in ft.rects if r[4][:3] == (1.0, 1.0, 1.0) and r[2] > 0]
    assert fills == []


def test_gauge_bar_frac_one_fills_full_width():
    ft = FakeText()
    W = 100
    gauge_bar(ft, 10, 10, W, 8, 1.0, (1.0, 1.0, 1.0))
    fills = [r for r in ft.rects if r[4][:3] == (1.0, 1.0, 1.0)]
    assert fills and abs(fills[-1][2] - W) <= 1.0


@pytest.mark.parametrize("frac,expected", [(-0.5, 0.0), (0.0, 0.0),
                                           (0.5, 0.5), (1.0, 1.0), (3.0, 1.0)])
def test_gauge_bar_clamps_fraction(frac, expected):
    ft = FakeText()
    W = 200
    gauge_bar(ft, 0, 0, W, 8, frac, (1.0, 1.0, 1.0))
    fills = [r for r in ft.rects if r[4][:3] == (1.0, 1.0, 1.0) and r[2] > 0]
    got = (fills[-1][2] / W) if fills else 0.0
    assert abs(got - expected) <= 0.01


def test_mini_compass_radial_tick_at_bearing():
    ft = FakeText()
    cx, cy, r = 100.0, 100.0, 20.0
    brg = 47.0                              # not a 15-degree ring vertex
    mini_compass(ft, cx, cy, r, [brg])
    th = math.radians(brg)
    tip = (cx + r * math.sin(th), cy - r * math.cos(th))
    pts = [p for ln in ft.lines for p in ln[0]]
    assert any(math.hypot(px - tip[0], py - tip[1]) <= 2.0
               for px, py in pts), "no bearing tick at the 47-degree outer radius"


def test_hud_widgets_use_translucent_alpha():
    from game import hud_widgets
    ft = FakeText()
    hud_widgets.badge(ft, "READY", 0, 0, "READY")
    # at least one filled rect carries the 0.55 HUD alpha (vs menu 0.92)
    assert any(len(r[4]) == 4 and abs(r[4][3] - 0.55) <= 1e-6 for r in ft.rects)


# --- tab_strip + scroll_list coverage (own output, headless) -------------------

def test_tab_strip_active_tab_gets_accent_underline():
    from game.states import ACCENT, MUTED, tab_strip
    ft = FakeText()
    tab_strip(ft, 0, 0, ["ALPHA", "BRAVO", "CHARLIE"], active=1)
    # one label per tab, active one in ACCENT and the rest MUTED
    assert [t[2] for t in ft.texts] == ["ALPHA", "BRAVO", "CHARLIE"]
    assert ft.texts[1][3][:3] == tuple(ACCENT)[:3]
    assert ft.texts[0][3][:3] == tuple(MUTED)[:3]
    assert ft.texts[2][3][:3] == tuple(MUTED)[:3]
    # exactly one accent underline polyline under the active tab
    underlines = [ln for ln in ft.lines if ln[1][:3] == tuple(ACCENT)[:3]]
    assert len(underlines) == 1


def test_tab_strip_fixed_column_mode_matches_combat_setup_inline_loop():
    """REGRESSION (spec 08 F1): combat_setup.py's tab bar was an inline loop
    that positioned tab i at ``x + i*tab_w`` on an even grid. It now delegates
    to tab_strip(..., tab_w=...). This locks the fixed-column output to the old
    inline formula so a layout regression fails here.

    Old inline loop being reproduced (game/combat_setup.py, pre-refactor):
        for i, pname in enumerate(names):
            col = ACCENT if i == page else MUTED
            tx = x + i * tab_w
            draw_text(tx, y, pname, col, SMALL_SIZE)
            if i == page:
                pw = text_width(pname, SMALL_SIZE)
                draw_lines([(tx, y+lh+2), (tx+pw, y+lh+2)], (*ACCENT,1.0), 1.5)
    """
    from game.states import ACCENT, MUTED, SMALL_SIZE, tab_strip
    ft = FakeText()
    names = ["WORLD", "ARMORY"]
    x, y = 130, 76
    active = 1
    tab_w = 680 // len(names)        # combat_setup: SETUP_PANEL_W // n_pages

    tab_strip(ft, x, y, names, active, size=SMALL_SIZE, tab_w=tab_w)

    # One label per tab, each at its fixed grid column x + i*tab_w, at y, SIZE.
    assert len(ft.texts) == len(names)
    for i, (tx, ty, s, color, size) in enumerate(ft.texts):
        assert s == names[i]
        assert tx == x + i * tab_w           # fixed-grid x (NOT measured-width)
        assert ty == y
        assert size == SMALL_SIZE
        expected_col = ACCENT if i == active else MUTED
        assert tuple(color)[:3] == tuple(expected_col)[:3]
        # color token passed through unchanged (raw 3-tuple, like the inline loop)
        assert tuple(color) == tuple(expected_col)

    # Exactly one active-tab underline, in ACCENT at 1.5px, spanning the active
    # label from its grid column to that column + measured label width.
    lh = ft.line_height(SMALL_SIZE)
    uy = y + lh + 2
    ax = x + active * tab_w
    aw = ft.text_width(names[active], SMALL_SIZE)
    underlines = [ln for ln in ft.lines if ln[1][:3] == tuple(ACCENT)[:3]]
    assert len(underlines) == 1
    pts, rgba, width = underlines[0]
    assert pts == [(ax, uy), (ax + aw, uy)]
    assert rgba == (*ACCENT, 1.0)
    assert width == 1.5


def test_scroll_list_draws_only_visible_rows_with_thumb():
    from game.states import scroll_list
    ft = FakeText()
    drawn = []
    items = list(range(20))
    # view_h fits 4 rows of ROW_H; focus on item 0 so scroll stays at top
    scroll_list(ft, items, x=0, y=0, w=120, view_h=4 * 40, row_h=40,
                scroll=0, focus=0,
                draw_row=lambda it, i, rx, ry: drawn.append((it, ry)))
    # only the rows that fit are drawn (whole-row scroll)
    assert [d[0] for d in drawn] == [0, 1, 2, 3]
    # a scrollbar track + thumb are emitted (more items than fit)
    assert len(ft.rects) >= 2
