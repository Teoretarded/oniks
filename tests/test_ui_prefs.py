"""UI preference store (2026-07-05): the user's revert switch.

The command-board map layout and the launch-cinema PiP are TOGGLEABLE and
PERSISTED — 'make it so that it can be changed, chopped, and reverted'.
Same robustness contract as the keybinds store: never crash on config,
quarantine an unparseable file, unknown keys ignored, missing keys fill
from defaults.
"""

from game.ui_prefs import DEFAULTS, UiPrefs


def test_defaults_board_layout_and_cinema_on(tmp_path):
    p = UiPrefs(str(tmp_path / "ui_prefs.json"))
    assert p.get("map_layout") == "board"
    assert p.get("launch_cinema") is True
    assert DEFAULTS["map_layout"] == "board"


def test_set_persists_and_reloads(tmp_path):
    path = str(tmp_path / "ui_prefs.json")
    p = UiPrefs(path)
    p.set("map_layout", "classic")
    p.set("launch_cinema", False)
    q = UiPrefs(path)
    assert q.get("map_layout") == "classic"
    assert q.get("launch_cinema") is False


def test_unknown_keys_ignored_and_bad_values_fall_back(tmp_path):
    path = tmp_path / "ui_prefs.json"
    path.write_text('{"map_layout": "neon", "mystery": 7}', encoding="utf-8")
    p = UiPrefs(str(path))
    assert p.get("map_layout") == "board"      # invalid value -> default
    assert p.get("launch_cinema") is True      # missing -> default


def test_unparseable_file_is_quarantined(tmp_path):
    path = tmp_path / "ui_prefs.json"
    path.write_text("{nope", encoding="utf-8")
    p = UiPrefs(str(path))
    assert p.get("map_layout") == "board"
    p.set("map_layout", "classic")             # regenerates cleanly
    assert UiPrefs(str(path)).get("map_layout") == "classic"


def test_toggle_helpers(tmp_path):
    p = UiPrefs(str(tmp_path / "ui_prefs.json"))
    assert p.toggle_map_layout() == "classic"
    assert p.toggle_map_layout() == "board"
    assert p.toggle_launch_cinema() is False
    assert p.toggle_launch_cinema() is True
