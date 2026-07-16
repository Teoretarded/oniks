"""Capture deterministic views of one custom Weather Composer recipe."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pygame

from game.weather_composer import (CUSTOM_PREF_KEYS, compose_custom_weather,
                                   custom_recipe_digest, custom_selection)


SHORT_KEYS = dict(zip(("low", "mid", "high", "convective"),
                      CUSTOM_PREF_KEYS))


def load_recipe(path: Path) -> dict[str, str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("weather recipe must be a JSON object")
    expanded = {SHORT_KEYS.get(key, key): value for key, value in raw.items()}
    unknown = set(expanded) - set(CUSTOM_PREF_KEYS)
    if unknown:
        raise ValueError(f"unknown weather recipe keys: {sorted(unknown)}")
    return custom_selection(expanded)


def _save(window, path: Path) -> None:
    from OpenGL.GL import GL_RGB, GL_UNSIGNED_BYTE, glReadPixels
    w, h = window.size()
    buf = glReadPixels(0, 0, w, h, GL_RGB, GL_UNSIGNED_BYTE)
    surf = pygame.image.frombytes(buf, (w, h), "RGB", True)
    pygame.image.save(surf, str(path))
    print(f"[composer-probe] wrote {path}")


def _views(cluster, high_altitude: float):
    center = np.asarray(cluster["center"], dtype=np.float64)
    outside = np.asarray(cluster["outside"], dtype=np.float64)
    top = float(cluster["top"])
    direction = outside - center
    direction[1] = 0.0
    direction /= max(float(np.linalg.norm(direction)), 1e-6)
    side = outside.copy()
    side[1] = 7_800.0
    ground = outside + direction * 25_000.0
    ground[1] = 60.0
    anvil = outside + direction * 110_000.0
    anvil[1] = max(10_000.0, top - 4_200.0)
    above = center + direction * 45_000.0
    above[1] = top + 18_000.0
    high = center + direction * 260_000.0
    high[1] = high_altitude + 2_600.0
    high_target = high + np.array([-direction[2] * 55_000.0,
                                   -2_600.0,
                                   direction[0] * 55_000.0])
    return (
        ("three_band_ground", ground,
         np.array([center[0], top * 0.42, center[2]])),
        ("supercell_side", side,
         np.array([center[0], top * 0.52, center[2]])),
        ("anvil_profile", anvil,
         np.array([center[0], top * 0.82, center[2]])),
        ("above_system", above, center),
        ("high_layer", high,
         high_target),
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--quality", choices=("low", "med", "high", "ultra"),
                        default="high")
    parser.add_argument("--view", choices=("three_band_ground", "supercell_side",
                                            "anvil_profile", "above_system",
                                            "high_layer"))
    args = parser.parse_args(argv)

    os.chdir(Path(__file__).resolve().parents[1])
    os.environ["ONIKS_CLOUD_RENDERER"] = "v2"
    os.environ["ONIKS_CLOUD_QUALITY"] = args.quality
    os.environ["ONIKS_CLOUD_WEATHER"] = "custom"
    from main import App, PHYS_DT
    from tools.probe_cloud_flight import find_cluster_v2
    from world.combat_config import CombatConfig

    selection = load_recipe(args.recipe)
    recipe = compose_custom_weather(selection)
    digest = custom_recipe_digest(selection)
    cluster = find_cluster_v2(args.seed, recipe)
    app = App(hidden=True)
    app.ui_prefs.values.update(selection)
    app.ui_prefs.values["cloud_weather_override"] = "custom"
    app.start_combat(CombatConfig(seed=args.seed, weather_preset=1))
    state = app.state
    try:
        if not getattr(state.clouds, "using_v2", False):
            raise RuntimeError("custom recipe entered legacy fallback")
        for _ in range(120):
            state.sim_step(PHYS_DT)
        state.hud_visible = False
        state.rig.set_mode("free")
        Path("renders").mkdir(exist_ok=True)
        for name, pos, target in _views(cluster, recipe.high.altitude_m):
            if args.view is not None and name != args.view:
                continue
            delta = target - pos
            state.rig.freecam.pos = pos
            state.rig.freecam.yaw = float(np.arctan2(delta[0], delta[2]))
            state.rig.freecam.pitch = float(np.arcsin(np.clip(
                delta[1] / max(float(np.linalg.norm(delta)), 1e-6), -1, 1)))
            state.rig.update(0.0, None)
            for _ in range(240):
                state.render(1 / 60)
                if not state.terrain._jobs:
                    break
            state.render(1 / 60)
            _save(state.window, Path(
                f"renders/weather_{digest}_{args.quality}_{name}_seed{args.seed}.png"))
    finally:
        state.dispose()
        pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
