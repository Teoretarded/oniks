"""WAR SANDBOX visual gate -> renders/sandbox_war_<scene>.png.

usage: python -m tools.shoot_sandbox_war [scene ...]   (default: all)

Boots App(hidden=True), enters a SandboxWarState (the menu SANDBOX path)
and shoots the port's proof scenes: the passive fleet (destroyer +
carrier meshes in the sandbox), the civilian traffic still sailing its
lanes, the enemy airfield on the coast, and the tactical map with the
all-seeing picture.  Same LOD warm-up discipline as
tools/screenshot_harness.py.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pygame

from main import PHYS_DT, App
from world.generation import BASE_POS

OUT_DIR = "renders"
MAX_WARMUP_FRAMES = 1200


def _set_cam(state, pos, yaw: float, pitch: float) -> None:
    state.rig.set_mode("free")
    freecam = state.rig.freecam
    freecam.pos = np.asarray(pos, dtype=np.float64).copy()
    freecam.yaw = float(yaw)
    freecam.pitch = float(pitch)


def _aim(state, pos, target) -> None:
    d = np.asarray(target, np.float64) - np.asarray(pos, np.float64)
    yaw = float(np.arctan2(d[0], d[2]))
    pitch = float(np.arctan2(d[1], np.hypot(d[0], d[2])))
    _set_cam(state, pos, yaw, pitch)


def _fly(state, seconds: float) -> None:
    for _ in range(int(round(seconds / PHYS_DT))):
        state.sim_step(PHYS_DT)


def _closest_destroyer(world):
    from sim.enemy_ships import Destroyer
    hulls = [s for s in world.ships if isinstance(s, Destroyer)]
    return min(hulls, key=lambda s: float(
        np.hypot(s.pos[0] - BASE_POS[0], s.pos[2] - BASE_POS[2])))


def _scene_overview(s) -> None:
    """The classic 3 km overview: base headland, lanes, traffic."""
    _fly(s, 2.0)
    _set_cam(s, (BASE_POS[0], BASE_POS[1] + 3000.0, -2_000.0), 0.0, -0.42)


def _scene_destroyer(s) -> None:
    """The nearest enemy destroyer, broadside from 400 m — the combat mesh
    rendering inside the sandbox is THE Phase A2 visual proof."""
    _fly(s, 2.0)
    dd = _closest_destroyer(s.world)
    p = dd.pos.copy()
    _aim(s, p + np.array([320.0, 60.0, -260.0]), p + np.array([0.0, 8.0, 0.0]))


def _scene_carrier(s) -> None:
    """The carrier on its 280 km station, quarter view."""
    _fly(s, 2.0)
    p = s.world.carrier.pos.copy()
    _aim(s, p + np.array([420.0, 70.0, -340.0]), p + np.array([0.0, 12.0, 0.0]))


def _scene_airfield(s) -> None:
    """The enemy airfield + parked fighters band on the far coast."""
    _fly(s, 2.0)
    p = s.world.airfield.pos.copy()
    _aim(s, p + np.array([600.0, 180.0, -900.0]), p + np.array([0.0, 10.0, 0.0]))


def _scene_map(s) -> None:
    """The tactical map over the base: the all-seeing picture must show the
    civilian lanes AND the enemy fleet/airfield markers with no fog."""
    _fly(s, 3.0)                      # a few board refresh periods
    s.map_open = True
    _set_cam(s, (BASE_POS[0], BASE_POS[1] + 3000.0, -2_000.0), 0.0, -0.42)


def _scene_director(s) -> None:
    """The director panel open over the map, a ready destroyer ARMED —
    the Phase C layout gate (panel vs the BOARD columns + rail)."""
    _fly(s, 3.0)
    s.map_open = True
    s.director.toggle()
    uid = next(u["uid"] for u in s.world.director_units()
               if u["kind"] == "destroyer" and u["ready"])
    rows = s.director.rows()
    s.director.sel = next(i for i, r in enumerate(rows)
                          if r["kind"] == "unit"
                          and r["unit"]["uid"] == uid)
    s.director.activate()               # armed: CLICK MAP TO LAUNCH banner
    _set_cam(s, (BASE_POS[0], BASE_POS[1] + 3000.0, -2_000.0), 0.0, -0.42)


def _scene_director_strike(s) -> None:
    """A director-ordered Tomahawk salvo 20 s into its flight, panel open:
    the hostile breadcrumbs on the all-seeing map + the spent VLS row."""
    _fly(s, 2.0)
    dd = _closest_destroyer(s.world)
    ok, msg = s.world.director_order(
        dd.ship_id, (float(BASE_POS[0]), float(BASE_POS[2])))
    if not ok:   # closest hull may be the TLAM-less AAW escort: pick armed
        uid = next(u["uid"] for u in s.world.director_units()
                   if u["kind"] == "destroyer" and u["ready"])
        ok, msg = s.world.director_order(
            uid, (float(BASE_POS[0]), float(BASE_POS[2])))
    assert ok, msg
    _fly(s, 20.0)
    s.map_open = True
    s.director.toggle()
    _set_cam(s, (BASE_POS[0], BASE_POS[1] + 3000.0, -2_000.0), 0.0, -0.42)


SCENES = {
    "overview": _scene_overview,
    "destroyer": _scene_destroyer,
    "carrier": _scene_carrier,
    "airfield": _scene_airfield,
    "map": _scene_map,
    "director": _scene_director,
    "director_strike": _scene_director_strike,
}


def shoot(app: App, name: str) -> str:
    from game.sandbox_war import SandboxWarState
    app.states.switch(SandboxWarState(app))
    app.sandbox = app.state
    app.state.hud_visible = name in ("map", "director", "director_strike")
    SCENES[name](app.state)
    terrain = getattr(app.state, "terrain", None)
    for _ in range(MAX_WARMUP_FRAMES):
        app.state.render(0.0)
        if terrain is None or not terrain._jobs:
            break
    app.state.render(0.0)
    surf = app.window.read_pixels_to_surface()
    path = os.path.join(OUT_DIR, f"sandbox_war_{name}.png")
    pygame.image.save(surf, path)
    return os.path.abspath(path)


def main(argv: list[str]) -> None:
    names = argv or list(SCENES)
    unknown = [n for n in names if n not in SCENES]
    if unknown:
        raise SystemExit(
            f"unknown scene(s) {unknown}; choose from {list(SCENES)}")
    os.makedirs(OUT_DIR, exist_ok=True)
    app = App(hidden=True)
    for name in names:
        print(f"saved {shoot(app, name)}")
    pygame.quit()


if __name__ == "__main__":
    main(sys.argv[1:])
