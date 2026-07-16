"""Persisted UI preferences (2026-07-05) — the player's revert switch.

The command-board map layout and the launch-cinema PiP shipped as a TEST:
both are toggleable in-game (map chrome chips + rebindable keys) and the
choice persists here — %APPDATA%\\ONIKS\\ui_prefs.json — so the player can
chop back to the CLASSIC layout at any moment without touching code.

Same never-crash-on-config contract as game/keybinds.py: an unparseable
file is quarantined to .bad and regenerated; unknown keys are ignored;
invalid values fall back to the defaults.  GL-free, unit-tested.
"""

from __future__ import annotations

import json
import os

from game.weather_composer import (CONVECTIVE_OPTIONS, CUSTOM_DEFAULTS,
                                   HIGH_OPTIONS, LOW_OPTIONS, MID_OPTIONS)

PREFS_FILE = "ui_prefs.json"
CLOUD_WEATHER_VALUES = ("battle", "clear", "fair", "partly cloudy",
                        "overcast", "high cirrus", "towering cumulus",
                        "thunderstorm", "custom")

# key -> (default, validator)
_SCHEMA = {
    "map_layout": ("board", lambda v: v in ("board", "classic")),
    "launch_cinema": (True, lambda v: isinstance(v, bool)),
    # --- GRAPHICS tab (settings screen, 2026-07-05) -----------------------
    "particle_density": ("med",
                         lambda v: v in ("low", "med", "high", "ultra")),
    "exhaust_trails": (True, lambda v: isinstance(v, bool)),
    "launch_smoke": ("full", lambda v: v in ("minimal", "full")),
    # V2 is the shipped default after passing the deterministic visual gates
    # at near-legacy High cost. Legacy remains selectable and is also the
    # automatic runtime fallback if V2 cannot compile or allocate.
    "cloud_renderer": ("v2", lambda v: v in ("legacy", "v2")),
    "cloud_quality": ("high",
                      lambda v: v in ("off", "low", "med", "high", "ultra")),
    # "battle" follows CombatConfig.weather_preset; the named choices are a
    # live visual override and make recipes reachable in sandbox/free-cam.
    "cloud_weather_override": (
        "battle", lambda v: v in CLOUD_WEATHER_VALUES),
    "cloud_custom_low": (CUSTOM_DEFAULTS["cloud_custom_low"],
                         lambda v: v in LOW_OPTIONS),
    "cloud_custom_mid": (CUSTOM_DEFAULTS["cloud_custom_mid"],
                         lambda v: v in MID_OPTIONS),
    "cloud_custom_high": (CUSTOM_DEFAULTS["cloud_custom_high"],
                          lambda v: v in HIGH_OPTIONS),
    "cloud_custom_convective": (
        CUSTOM_DEFAULTS["cloud_custom_convective"],
        lambda v: v in CONVECTIVE_OPTIONS),
}
DEFAULTS = {k: d for k, (d, _) in _SCHEMA.items()}

# Particle-emission multiplier per density step (the RTX-3050 budget knob:
# LOW halves every emit count, ULTRA doubles them; pool caps still bound
# the worst case).
DENSITY_SCALE = {"low": 0.5, "med": 1.0, "high": 1.5, "ultra": 2.0}


def prefs_path() -> str:
    base = os.getenv("APPDATA") or "."
    return os.path.join(base, "ONIKS", PREFS_FILE)


class UiPrefs:
    """The mutable pref table; every successful ``set`` saves immediately."""

    def __init__(self, path: str | None = None):
        self.path = path if path is not None else prefs_path()
        self.values = dict(DEFAULTS)
        self.load()

    def get(self, key: str):
        return self.values[key]

    def set(self, key: str, value) -> None:
        self.set_many({key: value})

    def set_many(self, changes) -> None:
        """Validate and persist a group as one atomic in-memory update.

        Unknown keys fail before mutation. Invalid known values retain the
        established ``set`` behavior and normalize to that key's default.
        """

        items = list(changes.items())
        for key, _value in items:
            if key not in _SCHEMA:
                raise KeyError(key)
        candidate = dict(self.values)
        for key, value in items:
            default, valid = _SCHEMA[key]
            candidate[key] = value if valid(value) else default
        self.values = candidate
        self.save()

    # ------------------------------------------------------------- toggles

    def toggle_map_layout(self) -> str:
        new = "classic" if self.get("map_layout") == "board" else "board"
        self.set("map_layout", new)
        return new

    def toggle_launch_cinema(self) -> bool:
        new = not self.get("launch_cinema")
        self.set("launch_cinema", new)
        return new

    def particle_density_scale(self) -> float:
        """Emission multiplier for the current particle_density pref."""
        return DENSITY_SCALE[self.get("particle_density")]

    # ---------------------------------------------------------- persistence

    def load(self) -> None:
        self.values = dict(DEFAULTS)
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("prefs is not a table")
        except (OSError, ValueError):
            try:
                os.replace(self.path, self.path + ".bad")
            except OSError:
                pass
            return
        for key, (default, valid) in _SCHEMA.items():
            v = data.get(key, default)
            self.values[key] = v if valid(v) else default

    def save(self) -> None:
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.values, f, indent=2)
        except OSError:
            pass                        # read-only disk: play on
