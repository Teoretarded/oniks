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

PREFS_FILE = "ui_prefs.json"

# key -> (default, validator)
_SCHEMA = {
    "map_layout": ("board", lambda v: v in ("board", "classic")),
    "launch_cinema": (True, lambda v: isinstance(v, bool)),
}
DEFAULTS = {k: d for k, (d, _) in _SCHEMA.items()}


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
        default, valid = _SCHEMA[key]
        self.values[key] = value if valid(value) else default
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
