"""Regression checks for testing-lab pointer interactions.

These tests intentionally stop at the state/input boundary.  Preview generation
is replaced with a small state fake so no OpenGL context is required.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pygame
import pytest

from game.testing_catalog import get_asset
from game.testing_lab import SIDEBAR_W, TestingLabState


class _Recorder:
    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


class _App:
    def __init__(self):
        self.window = SimpleNamespace()
        self.renderer = SimpleNamespace()
        self.audio = _Recorder()
        self.ui_prefs = SimpleNamespace(get=lambda _key: "high")
        self.screenshot_requested = False

    def close_testing_lab(self):
        pass


def _click(pos, button=1):
    return pygame.event.Event(
        pygame.MOUSEBUTTONDOWN,
        pos=pos,
        button=button,
    )


def _key(key, unicode=""):
    return pygame.event.Event(
        pygame.KEYDOWN,
        key=key,
        unicode=unicode,
        mod=0,
        scancode=0,
    )


def _wheel(pos, y):
    return pygame.event.Event(
        pygame.MOUSEWHEEL,
        x=0,
        y=y,
        mouse_x=pos[0],
        mouse_y=pos[1],
        flipped=False,
        touch=False,
    )


def _row_index(state: TestingLabState, asset_id: str) -> int:
    return next(
        index
        for index, asset in enumerate(state.visible_assets())
        if asset.id == asset_id
    )


def _install_row(state: TestingLabState, asset_id: str):
    """Expose one catalog row at a stable location without rendering the UI."""

    index = _row_index(state, asset_id)
    rect = (24, 180, SIDEBAR_W - 24, 210)
    state._row_rects = [(index, rect)]
    return ((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)


def test_testmap_disturbance_tool_requires_p_and_disarms_cleanly():
    from sim.sixdof import make_test_hopper

    state = TestingLabState(_App())
    state.lab_mode = "testmap"
    state.testmap_body = make_test_hopper()
    assert not state.testmap_force_mode

    state._testmap_event(_key(pygame.K_p))
    assert state.testmap_force_mode
    state.testmap_body.set_grab([0.0, 0.0, 1.0], [2.0, 2.0, 0.0])
    state._testmap_grabbing = True
    state._testmap_pick_z = 1.0

    state._testmap_event(_key(pygame.K_p))
    assert not state.testmap_force_mode
    assert not state._testmap_grabbing
    assert state._testmap_pick_z is None
    assert state.testmap_body.grab_point_body is None


def test_testmap_roster_focuses_on_hands_on_physics_experiments():
    roster = TestingLabState.TESTMAP_ROSTER
    assert roster == ("TEST HOPPER", "SPIN DART", "TVC STICK",
                      "GYRO-GIMBAL", "FLIP BRAKE", "RCS NEEDLE")
    assert not set(("TRACTOR", "RETURNER", "PULSE LANDER")) & set(roster)


def test_spin_and_tvc_new_controls_mutate_live_body_without_reset():
    from sim.sixdof import make_spin_dart, make_tvc_stick

    state = TestingLabState(_App())
    state.lab_mode = "testmap"
    state.testmap_article = state.TESTMAP_ROSTER.index("SPIN DART")
    state.testmap_body = make_spin_dart()
    spin_body = state.testmap_body
    state._testmap_event(_key(pygame.K_g))
    assert state.testmap_body is spin_body
    assert not spin_body.spin_enabled
    state._testmap_event(_key(pygame.K_x))
    assert spin_body.spin_direction < 0.0
    state._testmap_event(_key(pygame.K_b))
    assert spin_body.airbrake_deployed

    state.testmap_article = state.TESTMAP_ROSTER.index("TVC STICK")
    state.testmap_body = make_tvc_stick()
    tvc_body = state.testmap_body
    state._testmap_event(_key(pygame.K_t))
    state._testmap_event(_key(pygame.K_f))
    state._testmap_event(_key(pygame.K_i))
    state._testmap_event(_key(pygame.K_j))
    state._testmap_event(_key(pygame.K_y))
    state._testmap_event(_key(pygame.K_n))
    assert state.testmap_body is tvc_body
    assert tvc_body.fcs_target_mode == "LEAN 12 DEG"
    assert not tvc_body.fcs_on
    assert tvc_body.gimbal[0] > 0.0
    assert tvc_body.gimbal[1] < 0.0
    assert tvc_body.gimbal_authority == 1.75
    assert tvc_body.gimbal_jammed


def test_rcs_needle_has_manual_pitch_yaw_and_roll_pulses():
    from sim.sixdof import make_rcs_needle

    state = TestingLabState(_App())
    state.lab_mode = "testmap"
    state.testmap_article = state.TESTMAP_ROSTER.index("RCS NEEDLE")
    state.testmap_body = make_rcs_needle()
    state.testmap_body.rcs_hold_on = False

    for key, expected in ((pygame.K_i, (1.0, 0.0, 0.0)),
                          (pygame.K_l, (0.0, -1.0, 0.0)),
                          (pygame.K_q, (0.0, 0.0, 1.0)),
                          (pygame.K_e, (0.0, 0.0, -1.0))):
        state._testmap_event(_key(key))
        assert tuple(state.testmap_body.rcs_pulse) == expected
        assert state.testmap_body.rcs_pulse_left > 0.0


def test_horizontal_preview_drag_tracks_mouse_direction():
    state = TestingLabState(_App())
    state._preview_box = (SIDEBAR_W + 40, 20, SIDEBAR_W + 700, 600)
    start = state.orbit_az

    state.handle_event(_click((SIDEBAR_W + 200, 200)))
    state.handle_event(pygame.event.Event(
        pygame.MOUSEMOTION,
        pos=(SIDEBAR_W + 176, 200),
        rel=(-24, 0),
        buttons=(1, 0, 0),
    ))

    signed_change = math.remainder(state.orbit_az - start, math.tau)
    assert signed_change < 0.0, "dragging left must orbit left"


def test_vertical_preview_drag_up_raises_camera():
    state = TestingLabState(_App())
    state._preview_box = (SIDEBAR_W + 40, 20, SIDEBAR_W + 700, 600)
    start = state.orbit_el

    state.handle_event(_click((SIDEBAR_W + 200, 200)))
    state.handle_event(pygame.event.Event(
        pygame.MOUSEMOTION,
        pos=(SIDEBAR_W + 200, 176),
        rel=(0, -24),
        buttons=(1, 0, 0),
    ))

    assert state.orbit_el > start, "dragging up must raise camera elevation"


@pytest.mark.parametrize("legacy_button", [None, 4, 5])
def test_sidebar_wheel_never_zooms_preview(legacy_button):
    state = TestingLabState(_App())
    sidebar_pos = (SIDEBAR_W // 2, 200)
    state._last_mouse = sidebar_pos
    state.orbit_dist = 20.0
    state.min_dist = 1.0
    state.max_dist = 100.0

    if legacy_button is None:
        event = pygame.event.Event(
            pygame.MOUSEWHEEL,
            x=0,
            y=-1,
            flipped=False,
            touch=False,
        )
    else:
        event = _click(sidebar_pos, button=legacy_button)
    state.handle_event(event)

    assert state.orbit_dist == pytest.approx(20.0)


def test_modern_wheel_uses_event_position_instead_of_stale_mouse():
    state = TestingLabState(_App())
    state._preview_box = (SIDEBAR_W + 40, 20, SIDEBAR_W + 700, 600)
    state._last_mouse = (SIDEBAR_W + 200, 200)
    state.selected = 5
    state.orbit_dist = 20.0
    state.min_dist = 1.0
    state.max_dist = 100.0

    state.handle_event(_wheel((SIDEBAR_W // 2, 200), -1))

    assert state.selected > 5
    assert state.orbit_dist == pytest.approx(20.0)


def test_wheel_outside_sidebar_and_preview_does_nothing():
    state = TestingLabState(_App())
    state._preview_box = (SIDEBAR_W + 40, 20, SIDEBAR_W + 700, 600)
    state._last_mouse = (SIDEBAR_W // 2, 200)
    state.selected = 5
    state.orbit_dist = 20.0
    state.min_dist = 1.0
    state.max_dist = 100.0

    state.handle_event(_wheel((SIDEBAR_W + 200, 700), 1))

    assert state.selected == 5
    assert state.orbit_dist == pytest.approx(20.0)


def test_wheel_inside_preview_still_zooms():
    state = TestingLabState(_App())
    preview_pos = (SIDEBAR_W + 200, 200)
    state._preview_box = (SIDEBAR_W + 40, 20, SIDEBAR_W + 700, 600)
    state._last_mouse = (SIDEBAR_W // 2, 200)
    state.selected = 5
    state.orbit_dist = 20.0
    state.min_dist = 1.0
    state.max_dist = 100.0

    state.handle_event(_wheel(preview_pos, 1))

    assert state.selected == 5
    assert state.orbit_dist < 20.0


def test_missile_lab_result_click_selects_that_white_track():
    state = TestingLabState(_App())
    state.lab_mode = "flight"
    state._flight_result_rects = [(7, (24, 640, 360, 665))]

    state.handle_event(_click((100, 650)))

    assert state.selected_flight_run == 7


def test_missile_lab_result_wheel_scrolls_the_ranked_ledger():
    state = TestingLabState(_App())
    state.lab_mode = "flight"
    state._flight_results_box = (24, 640, 360, 880)
    state.flight_batch = SimpleNamespace(results=tuple(range(100)))

    state.handle_event(_wheel((100, 700), -1))

    assert state.flight_run_scroll == 1


def test_sidebar_wheel_selection_clamps_at_both_ends():
    state = TestingLabState(_App())
    sidebar_pos = (SIDEBAR_W // 2, 200)
    last = len(state.visible_assets()) - 1

    state.selected = 0
    state.handle_event(_wheel(sidebar_pos, 1))
    assert state.selected == 0

    state.selected = last
    state.handle_event(_wheel(sidebar_pos, -1))
    assert state.selected == last


def test_row_click_selects_and_activates_proxy(monkeypatch):
    state = TestingLabState(_App())
    generated = []

    def fake_generate(show_loading=True):
        asset = state.selected_asset()
        generated.append(asset.id)
        state.loaded_asset = asset
        return True

    monkeypatch.setattr(state, "generate_selected", fake_generate)
    click_pos = _install_row(state, "swarm_loiterer")

    state.handle_event(_click(click_pos))

    assert state.selected_asset().id == "swarm_loiterer"
    assert state.loaded_asset == get_asset("swarm_loiterer")
    assert generated == ["swarm_loiterer"]


def test_active_search_allows_result_click_and_blurs(monkeypatch):
    state = TestingLabState(_App())
    generated = []

    def fake_generate(show_loading=True):
        asset = state.selected_asset()
        generated.append(asset.id)
        state.loaded_asset = asset
        return True

    monkeypatch.setattr(state, "generate_selected", fake_generate)
    state._search_rect = (24, 124, SIDEBAR_W - 24, 154)
    state.handle_event(_key(pygame.K_SLASH, "/"))
    for char in "cloud":
        state.handle_event(_key(ord(char), char))
    assert state.search_active
    assert [asset.id for asset in state.visible_assets()] == ["partly_cloudy"]

    state.handle_event(_click(_install_row(state, "partly_cloudy")))

    assert not state.search_active
    assert state.query == ""
    assert state.loaded_asset == get_asset("partly_cloudy")
    assert generated == ["partly_cloudy"]


def test_search_clear_hit_target_restores_full_catalog():
    state = TestingLabState(_App())
    state.query = "cloud"
    state.search_active = True
    state._search_rect = (24, 124, SIDEBAR_W - 24, 154)
    state._search_clear_rect = (SIDEBAR_W - 54, 124,
                                SIDEBAR_W - 24, 154)

    state.handle_event(_click((SIDEBAR_W - 36, 139)))

    assert state.query == ""
    assert not state.search_active
    assert len(state.visible_assets()) > 40


def test_weather_row_does_not_lock_out_later_mesh_selection(monkeypatch):
    state = TestingLabState(_App())
    generated = []

    def fake_generate(show_loading=True):
        asset = state.selected_asset()
        generated.append(asset.id)
        state.loaded_asset = asset
        return True

    monkeypatch.setattr(state, "generate_selected", fake_generate)

    state.handle_event(_click(_install_row(state, "thunderstorm")))
    assert state.loaded_asset.kind == "weather"

    state.handle_event(_click(_install_row(state, "oniks")))

    assert state.selected_asset().id == "oniks"
    assert state.loaded_asset.kind == "mesh"
    assert generated == ["thunderstorm", "oniks"]
