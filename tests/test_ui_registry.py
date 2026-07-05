"""UI registry contracts (AI-testability build, 2026-07-05).

The per-frame registry is the single source of truth for 'what is on
screen where': draw code registers every major panel (name + rect +
optional bound-action id + code pointer), clicks route through hit(),
the F3 bug reporter tags items from it, and overlaps() is the layout
oracle an AI test runs against a rendered frame.
"""

from game.ui_registry import UiRegistry


def test_register_hit_and_topmost_wins():
    ui = UiRegistry()
    ui.begin_frame()
    ui.add("hud.platform_plate", 16, 16, 300, 200, action="cycle_platform",
           code="game/hud.py:_block")
    ui.add("hud.weapon_row", 16, 60, 300, 24, action="oniks_weapon",
           code="game/hud.py:_block")
    item = ui.hit(100, 70)
    assert item["name"] == "hud.weapon_row"        # registered later = on top
    assert item["action"] == "oniks_weapon"
    assert ui.hit(100, 30)["name"] == "hud.platform_plate"
    assert ui.hit(2000, 2000) is None


def test_begin_frame_clears_the_previous_frame():
    ui = UiRegistry()
    ui.begin_frame()
    ui.add("a", 0, 0, 10, 10)
    ui.begin_frame()
    assert ui.hit(5, 5) is None
    assert ui.items == []


def test_overlaps_reports_intersecting_sibling_panels():
    ui = UiRegistry()
    ui.begin_frame()
    ui.add("hud.flight_block", 16, 16, 300, 260)
    ui.add("hud.intel_panel", 16, 96, 280, 300)    # overlaps the block
    ui.add("hud.clock_chip", 700, 16, 200, 40)     # clear of both
    pairs = ui.overlaps()
    assert pairs == [("hud.flight_block", "hud.intel_panel")]


def test_overlaps_ignores_declared_containers():
    ui = UiRegistry()
    ui.begin_frame()
    ui.add("hud.platform_plate", 16, 16, 300, 200)
    ui.add("hud.weapon_row", 16, 60, 300, 24, parent="hud.platform_plate")
    assert ui.overlaps() == []                     # a row INSIDE its plate
