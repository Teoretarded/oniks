"""Pure model and headless input contracts for the Weather Composer."""

from types import SimpleNamespace

import pygame

from game.states import (GRAPHICS_ENTRIES, SettingsState,
                         WEATHER_COMPOSER_ACTION)
from game.ui_prefs import UiPrefs
from game.weather_composer import (
    CONVECTIVE_OPTIONS, CUSTOM_DEFAULTS, CUSTOM_PREF_KEYS, HIGH_OPTIONS,
    LOW_OPTIONS, MID_OPTIONS, QUICK_WEATHER_PRESETS, canonical_custom_tuple,
    custom_selection, cycle_custom_value, toggle_custom_value, weather_summary,
)


class _Audio:
    def __init__(self):
        self.clicks = 0

    def ui_click(self):
        self.clicks += 1


class _States:
    def __init__(self):
        self.target = None

    def switch(self, target):
        self.target = target


def _state(tmp_path):
    app = SimpleNamespace(
        ui_prefs=UiPrefs(str(tmp_path / "prefs.json")),
        audio=_Audio(), states=_States(), menu=object())
    state = SettingsState(app)
    state.tab = 1
    return state, app


def test_exact_custom_options_and_canonical_order():
    assert LOW_OPTIONS == ("off", "scattered", "broken", "deck")
    assert MID_OPTIONS == ("off", "scattered", "broken", "massive")
    assert HIGH_OPTIONS == ("off", "wispy", "dense", "sheet")
    assert CONVECTIVE_OPTIONS == (
        "off", "towering", "supercell", "storm line")
    mixed = {"cloud_custom_convective": "storm line",
             "cloud_custom_high": "dense",
             "cloud_custom_low": "deck",
             "cloud_custom_mid": "massive"}
    assert canonical_custom_tuple(mixed) == (
        "deck", "massive", "dense", "storm line")


def test_custom_selection_repairs_invalid_values_without_mutating_source():
    raw = dict(CUSTOM_DEFAULTS)
    raw["cloud_custom_low"] = "invalid"
    clean = custom_selection(raw)
    assert clean["cloud_custom_low"] == "scattered"
    assert raw["cloud_custom_low"] == "invalid"
    assert tuple(clean) == CUSTOM_PREF_KEYS


def test_summary_is_readable_for_quick_and_multiselect_custom():
    assert weather_summary("battle", CUSTOM_DEFAULTS) == "BATTLE SETUP"
    assert weather_summary("thunderstorm", CUSTOM_DEFAULTS) == "THUNDERSTORM"
    selection = dict(CUSTOM_DEFAULTS)
    selection.update(cloud_custom_low="broken",
                     cloud_custom_mid="massive",
                     cloud_custom_convective="supercell")
    summary = weather_summary("custom", selection)
    assert summary == (
        "CUSTOM: LOW BROKEN + MID MASSIVE + HIGH WISPY + "
        "CB SUPERCELL")


def test_cycle_and_toggle_are_independent_per_card():
    assert cycle_custom_value("cloud_custom_low", "broken", 1) == "deck"
    assert toggle_custom_value("cloud_custom_mid", "off") == "scattered"
    assert toggle_custom_value("cloud_custom_high", "dense") == "off"


def test_graphics_has_exactly_one_weather_composer_action():
    keys = [key for _label, key, _values in GRAPHICS_ENTRIES]
    assert keys.count(WEATHER_COMPOSER_ACTION) == 1
    assert "cloud_weather_override" not in keys


def test_keyboard_open_draft_cancel_does_not_persist(tmp_path):
    state, app = _state(tmp_path)
    state._gfx_focus = state._gfx_focusables().index(WEATHER_COMPOSER_ACTION)
    state._gfx_nav_key(pygame.K_RETURN)
    assert state._weather_open
    state._weather_focus = 1                 # LOW card
    state._weather_nav_key(pygame.K_SPACE)   # scattered -> off, draft only
    assert state._weather_draft_override == "custom"
    assert state._weather_draft["cloud_custom_low"] == "off"
    state._weather_nav_key(pygame.K_ESCAPE)
    assert not state._weather_open
    assert app.ui_prefs.get("cloud_weather_override") == "battle"
    assert app.ui_prefs.get("cloud_custom_low") == "scattered"


def test_keyboard_quick_preset_and_custom_apply(tmp_path):
    state, app = _state(tmp_path)
    state._open_weather_composer()
    assert state._weather_focus == 0
    state._weather_nav_key(pygame.K_RIGHT)  # battle -> clear
    assert state._weather_draft_override == QUICK_WEATHER_PRESETS[1]
    state._weather_nav_key(pygame.K_RETURN)  # quick commit
    assert app.ui_prefs.get("cloud_weather_override") == "clear"

    state._open_weather_composer()
    state._weather_focus = 4                 # convective
    state._weather_nav_key(pygame.K_RIGHT)   # off -> towering
    state._weather_focus = 5                 # APPLY
    state._weather_nav_key(pygame.K_RETURN)
    assert app.ui_prefs.get("cloud_weather_override") == "custom"
    assert app.ui_prefs.get("cloud_custom_convective") == "towering"


def test_mouse_card_toggle_and_apply_use_render_rect_contract(tmp_path):
    state, app = _state(tmp_path)
    state._open_weather_composer()
    state._weather_rects = [
        (2, "card", "cloud_custom_mid", (0, 0, 99, 99)),
        (5, "apply", "apply", (100, 0, 199, 99)),
    ]
    state._weather_mouse(pygame.event.Event(
        pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": (20, 20)}))
    assert state._weather_focus == 2
    assert state._weather_draft["cloud_custom_mid"] == "scattered"
    assert app.ui_prefs.get("cloud_custom_mid") == "off"
    state._weather_mouse(pygame.event.Event(
        pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": (120, 20)}))
    assert app.ui_prefs.get("cloud_weather_override") == "custom"
    assert app.ui_prefs.get("cloud_custom_mid") == "scattered"
