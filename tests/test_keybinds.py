"""game/keybinds.py — action->key table + JSON persistence (GL-free).

Covers the Task UI binding contract: complete defaults matching the current
README bindings, pygame key-name round-trip persistence at a versioned JSON
path, missing/unknown/corrupt-file recovery, atomic conflict swaps, reserved
ESC/F1 handling, numpad aliasing and per-row / global reset.
"""

import json

import pygame
import pytest

from game.keybinds import (ACTIONS, RESERVED_KEYS, SETTINGS_VERSION, Keybinds,
                           key_display, normalize_key, settings_path)

ACTION_IDS = [a.id for a in ACTIONS]


@pytest.fixture
def path(tmp_path):
    return str(tmp_path / "settings.json")


@pytest.fixture
def kb(path):
    return Keybinds(path)


# ------------------------------------------------------------- registry

def test_registry_covers_every_plan_action():
    for aid in ("launch", "map", "camera_mode", "cycle_platform",
                "profile_hi_lo", "profile_lo_lo", "pause", "frame_step",
                "time_down", "time_up", "screenshot", "subject_prev",
                "subject_next", "clear_waypoints", "menu", "controls_overlay",
                "freecam_fwd", "freecam_back", "freecam_left",
                "freecam_right", "freecam_up", "freecam_down"):
        assert aid in ACTION_IDS


def test_registry_ids_and_default_keys_unique():
    assert len(ACTION_IDS) == len(set(ACTION_IDS))
    defaults = [a.default for a in ACTIONS]
    assert len(defaults) == len(set(defaults))


def test_defaults_match_current_bindings(kb):
    assert kb.key_for("launch") == pygame.K_SPACE
    assert kb.key_for("map") == pygame.K_m
    assert kb.key_for("camera_mode") == pygame.K_c
    assert kb.key_for("cycle_platform") == pygame.K_TAB
    assert kb.key_for("pause") == pygame.K_p
    assert kb.key_for("frame_step") == pygame.K_n
    assert kb.key_for("time_down") == pygame.K_MINUS
    assert kb.key_for("time_up") == pygame.K_EQUALS
    assert kb.key_for("screenshot") == pygame.K_F2
    assert kb.key_for("subject_prev") == pygame.K_LEFTBRACKET
    assert kb.key_for("subject_next") == pygame.K_RIGHTBRACKET
    assert kb.key_for("clear_waypoints") == pygame.K_x
    assert kb.key_for("menu") == pygame.K_ESCAPE
    assert kb.key_for("controls_overlay") == pygame.K_F1
    assert kb.key_for("freecam_fwd") == pygame.K_w
    assert kb.key_for("freecam_down") == pygame.K_q
    # M6 salvo / ripple-fire (spec 07): F empties the ready tubes, Y cycles the
    # mode.  Both keys were unclaimed by every prior default.
    assert kb.key_for("salvo_fire") == pygame.K_f
    assert kb.key_for("salvo_mode") == pygame.K_y
    # M6 AUTO-TIME-WARP (spec 07): T toggles event-aware auto pacing.  T was
    # unclaimed by every prior default.
    assert kb.key_for("auto_warp_toggle") == pygame.K_t


def test_reserved_rows_are_esc_and_f1_only():
    reserved = [a.id for a in ACTIONS if a.reserved]
    assert sorted(reserved) == ["controls_overlay", "menu"]
    assert RESERVED_KEYS == frozenset({pygame.K_ESCAPE, pygame.K_F1})


def test_every_action_has_label_and_group(kb):
    groups = {a.group for a in ACTIONS}
    assert groups == {"ENGAGEMENT", "SIMULATION", "CAMERA", "SYSTEM"}
    for a in ACTIONS:
        assert a.label.strip() and a.label == a.label.upper()


# ------------------------------------------------------------- lookups

def test_action_for_and_matches(kb):
    assert kb.action_for(pygame.K_SPACE) == "launch"
    assert kb.action_for(pygame.K_F9) is None
    assert kb.matches("launch", pygame.K_SPACE)
    assert not kb.matches("launch", pygame.K_l)


def test_numpad_aliases_normalize(kb):
    assert normalize_key(pygame.K_KP_MINUS) == pygame.K_MINUS
    assert normalize_key(pygame.K_KP_PLUS) == pygame.K_EQUALS
    assert normalize_key(pygame.K_KP_ENTER) == pygame.K_RETURN
    assert normalize_key(pygame.K_a) == pygame.K_a
    assert kb.matches("time_down", pygame.K_KP_MINUS)
    assert kb.matches("time_up", pygame.K_KP_PLUS)


def test_key_display_names(kb):
    assert kb.name_for("launch") == "SPACE"
    assert kb.name_for("map") == "M"
    assert kb.name_for("subject_prev") == "["
    assert kb.name_for("screenshot") == "F2"
    assert key_display(None) == "---"


# --------------------------------------------------------- persistence

def test_rebind_saves_versioned_key_names(kb, path):
    assert kb.rebind("launch", pygame.K_l)
    data = json.loads(open(path, encoding="utf-8").read())
    assert data["version"] == SETTINGS_VERSION
    assert data["bindings"]["launch"] == "l"
    assert data["bindings"]["map"] == "m"


def test_round_trip_through_a_fresh_instance(kb, path):
    kb.rebind("launch", pygame.K_l)
    kb2 = Keybinds(path)
    assert kb2.key_for("launch") == pygame.K_l
    assert kb2.key_for("map") == pygame.K_m


def test_missing_ids_fill_from_defaults(path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "bindings": {"map": "j"}}, f)
    kb = Keybinds(path)
    assert kb.key_for("map") == pygame.K_j
    assert kb.key_for("launch") == pygame.K_SPACE


def test_unknown_ids_and_bad_values_ignored(path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "bindings": {
            "warp_drive": "z", "launch": "not a key name",
            "map": ["j", "k"]}}, f)
    kb = Keybinds(path)
    assert kb.action_for(pygame.K_z) is None
    assert kb.key_for("launch") == pygame.K_SPACE      # bad name -> default
    assert kb.key_for("map") == pygame.K_j             # list: first valid


def test_corrupt_file_renamed_bad_and_regenerated(path, tmp_path):
    with open(path, "w", encoding="utf-8") as f:
        f.write("{ this is not json")
    kb = Keybinds(path)
    assert kb.key_for("launch") == pygame.K_SPACE
    assert (tmp_path / "settings.json.bad").exists()
    data = json.loads(open(path, encoding="utf-8").read())
    assert data["bindings"]["launch"] == "space"


def test_duplicate_keys_in_file_keep_first_claimer(path):
    # Hand-edited file binds the same key twice: the first action (registry
    # order) keeps it, the second falls back to its default — and when that
    # default is the very key in dispute, the row loads unbound, never
    # silently aliased.
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "bindings": {"map": "c",
                                              "camera_mode": "c"}}, f)
    kb = Keybinds(path)
    assert kb.key_for("map") == pygame.K_c
    assert kb.key_for("camera_mode") is None
    assert kb.name_for("camera_mode") == "---"


def test_file_cannot_steal_reserved_keys(path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "bindings": {"launch": "escape",
                                              "menu": "q"}}, f)
    kb = Keybinds(path)
    assert kb.key_for("launch") == pygame.K_SPACE      # reserved key refused
    assert kb.key_for("menu") == pygame.K_ESCAPE       # reserved row pinned


def test_missing_file_loads_defaults_without_writing(path, tmp_path):
    kb = Keybinds(path)
    assert kb.key_for("launch") == pygame.K_SPACE
    assert not (tmp_path / "settings.json").exists()


def test_settings_path_is_appdata_oniks(monkeypatch):
    monkeypatch.setenv("APPDATA", r"C:\fake\AppData\Roaming")
    p = settings_path()
    assert p == r"C:\fake\AppData\Roaming\ONIKS\settings.json"
    monkeypatch.delenv("APPDATA")
    assert settings_path().endswith("settings.json")   # game-dir fallback


# ------------------------------------------------------ rebind / conflicts

def test_conflict_query(kb):
    assert kb.conflict("map", pygame.K_c) == "camera_mode"
    assert kb.conflict("map", pygame.K_m) is None      # own key: no conflict
    assert kb.conflict("map", pygame.K_j) is None


def test_conflict_rebind_swaps_atomically(kb):
    assert kb.rebind("map", pygame.K_c)
    assert kb.key_for("map") == pygame.K_c
    assert kb.key_for("camera_mode") == pygame.K_m     # took map's old key
    keys = [kb.key_for(a.id) for a in ACTIONS]
    assert len(keys) == len(set(keys))                 # still injective


def test_rebind_refuses_reserved(kb):
    assert not kb.rebind("menu", pygame.K_q)           # reserved action
    assert not kb.rebind("controls_overlay", pygame.K_o)
    assert not kb.rebind("map", pygame.K_ESCAPE)       # reserved key
    assert not kb.rebind("map", pygame.K_F1)
    assert kb.key_for("map") == pygame.K_m


def test_reset_row_swaps_back(kb):
    kb.rebind("map", pygame.K_c)                       # map=c, camera=m
    kb.reset_row("map")
    assert kb.key_for("map") == pygame.K_m
    assert kb.key_for("camera_mode") == pygame.K_c     # atomic swap back


def test_reset_all_restores_every_default(kb, path):
    kb.rebind("launch", pygame.K_l)
    kb.rebind("map", pygame.K_j)
    kb.reset_all()
    for a in ACTIONS:
        assert kb.key_for(a.id) == a.default
    kb2 = Keybinds(path)                               # reset persisted too
    assert kb2.key_for("launch") == pygame.K_SPACE


def test_rows_follow_registry_order(kb):
    rows = kb.rows()
    assert [a.id for a, _ in rows] == ACTION_IDS
    assert all(k == a.default for a, k in rows)
