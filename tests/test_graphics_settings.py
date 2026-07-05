"""GRAPHICS settings tab (2026-07-05): prefs schema, pure helpers, and the
density plumbing into the particle pools. GL-free."""

import numpy as np

from engine.particles import Effects
from game.states import (GRAPHICS_ROWS, SETTINGS_TABS, cycle_value,
                         graphics_value_label)
from game.ui_prefs import DEFAULTS, DENSITY_SCALE, UiPrefs


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
