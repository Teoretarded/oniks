"""GRAPHICS settings tab (2026-07-05): prefs schema, pure helpers, and the
density plumbing into the particle pools. GL-free."""

import numpy as np
import pytest

from engine.particles import Effects
from game.states import (GRAPHICS_ROWS, SETTINGS_TABS, cycle_value,
                         graphics_value_label)
from game.ui_prefs import DEFAULTS, DENSITY_SCALE, UiPrefs
from game.weather_composer import (CONVECTIVE_OPTIONS, CUSTOM_DEFAULTS,
                                   HIGH_OPTIONS, LOW_OPTIONS, MID_OPTIONS)


def test_settings_has_two_tabs():
    assert SETTINGS_TABS == ("KEYBINDS", "GRAPHICS")


def test_every_graphics_row_is_schema_valid(tmp_path):
    """Each row's key exists in the prefs schema and EVERY offered value
    survives a set/get round trip (the validator accepts it)."""
    p = UiPrefs(str(tmp_path / "prefs.json"))
    for _label, key, values in GRAPHICS_ROWS:
        assert key in DEFAULTS
        for v in values:
            p.set(key, v)
            assert p.get(key) == v


def test_cycle_value_wraps_and_snaps():
    vals = ("low", "med", "high", "ultra")
    assert cycle_value(vals, "med", 1) == "high"
    assert cycle_value(vals, "ultra", 1) == "low"          # wrap forward
    assert cycle_value(vals, "low", -1) == "ultra"         # wrap back
    assert cycle_value(vals, "corrupt", 1) == "low"        # snap on unknown


def test_value_labels():
    assert graphics_value_label(True) == "ON"
    assert graphics_value_label(False) == "OFF"
    assert graphics_value_label("med") == "MED"


def test_density_pref_persists_and_scales(tmp_path):
    path = str(tmp_path / "prefs.json")
    p = UiPrefs(path)
    assert p.particle_density_scale() == DENSITY_SCALE["med"] == 1.0
    p.set("particle_density", "ultra")
    assert UiPrefs(path).particle_density_scale() == 2.0


def test_cloud_v2_rollout_prefs_are_safe_and_persist(tmp_path):
    path = str(tmp_path / "prefs.json")
    p = UiPrefs(path)
    assert p.get("cloud_renderer") == "v2"
    assert p.get("cloud_quality") == "high"
    assert p.get("cloud_weather_override") == "battle"
    p.set("cloud_renderer", "v2")
    p.set("cloud_quality", "low")
    p.set("cloud_weather_override", "thunderstorm")
    loaded = UiPrefs(path)
    assert loaded.get("cloud_renderer") == "v2"
    assert loaded.get("cloud_quality") == "low"
    assert loaded.get("cloud_weather_override") == "thunderstorm"


def test_weather_composer_prefs_validate_and_persist(tmp_path):
    path = str(tmp_path / "prefs.json")
    p = UiPrefs(path)
    assert {k: p.get(k) for k in CUSTOM_DEFAULTS} == CUSTOM_DEFAULTS
    options = {
        "cloud_custom_low": LOW_OPTIONS,
        "cloud_custom_mid": MID_OPTIONS,
        "cloud_custom_high": HIGH_OPTIONS,
        "cloud_custom_convective": CONVECTIVE_OPTIONS,
    }
    for key, values in options.items():
        for value in values:
            p.set(key, value)
            assert p.get(key) == value
    p.set_many({"cloud_weather_override": "custom",
                "cloud_custom_low": "deck",
                "cloud_custom_mid": "massive",
                "cloud_custom_high": "sheet",
                "cloud_custom_convective": "storm line"})
    loaded = UiPrefs(path)
    assert loaded.get("cloud_weather_override") == "custom"
    assert loaded.get("cloud_custom_low") == "deck"
    assert loaded.get("cloud_custom_mid") == "massive"
    assert loaded.get("cloud_custom_high") == "sheet"
    assert loaded.get("cloud_custom_convective") == "storm line"


def test_set_many_is_one_save_and_unknown_key_is_atomic(tmp_path):
    p = UiPrefs(str(tmp_path / "prefs.json"))
    saves = []
    p.save = lambda: saves.append(dict(p.values))
    p.set_many({"cloud_custom_low": "broken",
                "cloud_custom_high": "dense"})
    assert len(saves) == 1
    assert p.get("cloud_custom_low") == "broken"
    before = dict(p.values)
    with pytest.raises(KeyError):
        p.set_many({"cloud_custom_low": "deck", "not_a_pref": True})
    assert p.values == before
    assert len(saves) == 1


def test_set_many_invalid_known_value_uses_default(tmp_path):
    p = UiPrefs(str(tmp_path / "prefs.json"))
    p.set_many({"cloud_custom_low": "impossible",
                "cloud_custom_mid": "massive"})
    assert p.get("cloud_custom_low") == CUSTOM_DEFAULTS["cloud_custom_low"]
    assert p.get("cloud_custom_mid") == "massive"


def test_density_scales_particle_emissions():
    """The same muzzle blast at ULTRA density spawns about twice the LOW
    particles — the RTX-3050 budget knob really moves the load."""
    counts = {}
    for name, density in (("low", 0.5), ("ultra", 2.0)):
        fx = Effects(seed=7)
        fx.density = density
        fx.muzzle_blast(np.array([0.0, 5.0, 0.0]))
        counts[name] = (int(fx.smoke.alive.sum()) + int(fx.fire.alive.sum()))
    assert counts["ultra"] >= 3 * counts["low"]


def test_launch_fx_minimal_cuts_launch_smoke():
    full = Effects(seed=7)
    full.muzzle_blast(np.array([0.0, 5.0, 0.0]))
    minimal = Effects(seed=7)
    minimal.launch_fx = 0.4
    minimal.muzzle_blast(np.array([0.0, 5.0, 0.0]))
    n_full = int(full.smoke.alive.sum()) + int(full.fire.alive.sum())
    n_min = int(minimal.smoke.alive.sum()) + int(minimal.fire.alive.sum())
    assert n_min < 0.6 * n_full
