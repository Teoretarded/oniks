"""Scripted scenes -> renders/<scene>.png for visual review.

usage: python -m tools.screenshot_harness [scene ...]   (default: all)

Creates App(hidden=True) at 1600x900, sets up the named scene, steps the sim
N times (so ocean waves have phase), lets the streamed terrain LODs finish,
renders ONE final frame and saves it via window.read_pixels_to_surface() +
pygame.image.save. Prints saved paths.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pygame

from game.cameras import TRANSITION_TIME
from main import PHYS_DT, App
from sim.missile import PH_CRUISE
from world.generation import BASE_POS

OUT_DIR = "renders"
SIM_STEPS = 240                  # 2 s of ocean-wave phase
MAX_WARMUP_FRAMES = 1200         # cap on terrain LOD streaming warm-up


def _set_cam(state, pos, yaw: float, pitch: float) -> None:
    state.rig.set_mode("free")   # free mode enters with no blend
    freecam = state.rig.freecam
    freecam.pos = np.asarray(pos, dtype=np.float64).copy()
    freecam.yaw = float(yaw)
    freecam.pitch = float(pitch)


def _aim(state, pos, target) -> None:
    """Place the free camera at ``pos`` looking at ``target``."""
    d = np.asarray(target, np.float64) - np.asarray(pos, np.float64)
    yaw = float(np.arctan2(d[0], d[2]))
    pitch = float(np.arctan2(d[1], np.hypot(d[0], d[2])))
    _set_cam(state, pos, yaw, pitch)


_BX, _BY, _BZ = BASE_POS
# Sun azimuth (heading of renderer SUN_DIR's horizontal component).
_SUN_YAW = float(np.arctan2(0.35, 0.55))


# --- flight scenes (Task 18): the sandbox sim drives the missile -------------

def _fly(state, seconds: float, until=None) -> None:
    """Step the sandbox sim, optionally stopping when ``until()`` is true."""
    for _ in range(int(round(seconds / PHYS_DT))):
        state.sim_step(PHYS_DT)
        if until is not None and until():
            return


def _scene_launch(s) -> None:
    """t = +2.0 s after launch: missile mid-boost over the raised TEL."""
    m = s.world.launch("hi-lo", np.array([0.0, 0.0, 120_000.0]))
    s.followed = m
    _fly(s, 2.0)
    # frame the TEL (bottom) and the climbing missile + plume (top): aim 40%
    # of the way up so the launcher stays inside the lower frame edge
    base = np.array(BASE_POS)
    _aim(s, (_BX + 62.0, _BY + 22.0, _BZ - 55.0), base + (m.pos - base) * 0.4)


def _scene_cruise(s) -> None:
    """Chase cam mid-flight: established hi-profile cruise at 14 km."""
    m = s.world.launch("hi-lo", np.array([0.0, 0.0, 250_000.0]))
    s.followed = m
    _fly(s, 120.0, until=lambda: m.phase == PH_CRUISE)
    _fly(s, 20.0)                    # level off on the cruise alt + grow a trail
    s.rig.set_mode("chase")
    s.rig.update(TRANSITION_TIME + 0.05, m)   # finish the blend (cam snaps)


def _scene_terminal(s) -> None:
    """Sea-skim 300 m short of a tanker, seeker locked, broadside camera."""
    tanker = next(sh for sh in s.world.ships
                  if sh.ship_type == "tanker" and sh.pos[2] < 60_000.0)
    lead = tanker.pos + tanker.velocity() * 60.0      # rough launch lead
    m = s.world.launch("lo-lo", np.array([lead[0], 0.0, lead[2]]))
    s.followed = m
    _fly(s, 180.0,
         until=lambda: (not m.alive
                        or np.linalg.norm(m.pos - tanker.pos) <= 300.0))
    # over-the-shoulder: camera behind-abeam the sea-skimming missile,
    # looking down the attack line at the tanker beyond
    line = tanker.pos - m.pos
    line_hat = line / max(np.linalg.norm(line), 1e-9)
    perp = np.cross(line_hat, (0.0, 1.0, 0.0))
    if perp[0] < 0.0:
        perp = -perp                 # abeam on the sun (east) side: hulls lit
    _aim(s, m.pos - line_hat * 40.0 + perp * 45.0 + (0.0, 10.0, 0.0),
         m.pos + line_hat * 60.0)

# --- models showcase: every vehicle/weapon model on a flat concrete pad ----
# The pad is a quay just offshore (water ~50 m deep, home cliffs as backdrop).
# Historically it ALSO dodged the pre-Task-16b vertex-log-depth artifact on
# huge terrain triangles; that is fixed now (see base_ground scene), but the
# offshore composition is kept.
PAD_X, PAD_Z = 800.0, 3_000.0
PAD_TOP = 2.5                       # quay deck height above sea level (m)
# ships anchor in a bow-to-stern line in open water NW of the pad (so the
# broadside camera sees all three without overlap); structures get their own
# pad east of it, with the harbor (a waterline model) in open water beyond
FLEET_X, FLEET_Z = PAD_X - 300.0, PAD_Z + 500.0
SHORE_X, SHORE_Z = PAD_X + 320.0, PAD_Z + 60.0
HARBOR_Z = SHORE_Z + 280.0

SCENES = {
    # cam 3000 m above base looking north (whole bay in view; pulled 1.4 km
    # south of the base point so the home headland frames the bottom)
    "overview": lambda s: _set_cam(s, (_BX, _BY + 3000.0, -2_000.0),
                                   0.0, -0.42),
    # cam 80 m alt, 2 km offshore (coast at x=0 sits at z~1000), looking
    # back south at the cliffs
    "coast": lambda s: _set_cam(s, (_BX, 80.0, 3_000.0), np.pi, -0.04),
    # cam 8 m above water mid-ocean looking at the sun (wave/glint check;
    # slight pitch up puts the sun disc at the frame top)
    "ocean_low": lambda s: _set_cam(s, (40_000.0, 8.0, 200_000.0),
                                    _SUN_YAW, 0.04),
    # cam 2.5 m above the terrain near the base, looking north-east along the
    # coastline at a grazing angle: huge terrain LOD cells nearly edge-on is
    # the worst case for log-depth interpolation (Task 16b regression scene).
    # Offset 25 m east of BASE_POS so the TEL parked there stays out of frame.
    "base_ground": lambda s: _set_cam(s, (_BX + 25.0, _BY + 2.5, _BZ),
                                      np.pi / 4.0, -0.02),
    # models lineup from 3 orbit angles (models face north = +Z)
    "models_front": lambda s: _aim(s, (PAD_X + 20.0, PAD_TOP + 7.0, PAD_Z + 26.0),
                                   (PAD_X - 1.0, PAD_TOP + 2.5, PAD_Z - 1.0)),
    "models_side": lambda s: _aim(s, (PAD_X + 28.0, PAD_TOP + 4.5, PAD_Z - 12.0),
                                  (PAD_X + 9.0, PAD_TOP + 1.5, PAD_Z + 1.0)),
    "models_high": lambda s: _aim(s, (PAD_X + 26.0, PAD_TOP + 25.0, PAD_Z - 28.0),
                                  (PAD_X - 2.0, PAD_TOP, PAD_Z + 1.0)),
    # ships (bow-to-stern line heading north): broadside, bow quarter, plan
    "models_fleet_side": lambda s: _aim(s, (FLEET_X + 500.0, 40.0, FLEET_Z + 30.0),
                                        (FLEET_X, 5.0, FLEET_Z + 30.0)),
    "models_fleet_quarter": lambda s: _aim(s, (FLEET_X + 260.0, 22.0, FLEET_Z + 480.0),
                                           (FLEET_X - 20.0, 5.0, FLEET_Z + 100.0)),
    "models_fleet_high": lambda s: _aim(s, (FLEET_X + 40.0, 400.0, FLEET_Z - 360.0),
                                        (FLEET_X, 0.0, FLEET_Z + 40.0)),
    # structures pad (radar station + fuel depot) and the harbor
    "models_shore_front": lambda s: _aim(s, (SHORE_X + 150.0, 25.0, SHORE_Z - 140.0),
                                         (SHORE_X - 5.0, 8.0, SHORE_Z)),
    "models_shore_harbor": lambda s: _aim(s, (SHORE_X + 150.0, 30.0, HARBOR_Z - 170.0),
                                          (SHORE_X - 10.0, 4.0, HARBOR_Z - 20.0)),
    "models_shore_high": lambda s: _aim(s, (SHORE_X + 80.0, 380.0, SHORE_Z + 40.0),
                                        (SHORE_X, 0.0, SHORE_Z + 150.0)),
    # flight scenes (Task 18): scripted launches, the scene steps its own sim
    "launch": _scene_launch,
    "cruise": _scene_cruise,
    "terminal": _scene_terminal,
}
# Flight scenes advance the sim themselves to a precise moment, so shoot()
# must not add its own wave-phase steps on top.
SCENE_STEPS = {"launch": 0, "cruise": 0, "terminal": 0}
MODEL_SCENES = ("models_front", "models_side", "models_high",
                "models_fleet_side", "models_fleet_quarter", "models_fleet_high",
                "models_shore_front", "models_shore_harbor", "models_shore_high")

_model_draws: list | None = None    # [(Mesh, pos_f64), ...] built lazily


def _pad_mesh(hx: float, hz: float):
    """Concrete quay pad: deck grid tessellated ~4 m + skirt walls in ~8 m
    segments. (The tessellation worked around the pre-Task-16b vertex-only
    log depth, where one giant quad lost the depth test to the finely
    tessellated ocean at grazing angles; fragment-shader depth made it
    unnecessary, but it is cheap and kept.)"""
    from engine.meshdata import MeshBuilder, make_box, make_grid
    from models.common import PALETTE

    b = MeshBuilder()
    nx, nz = round(hx / 2.0) + 1, round(hz / 2.0) + 1
    xs = np.linspace(-hx, hx, nx)
    zs = np.linspace(-hz, hz, nz)
    cols = np.empty((nz, nx, 3), dtype=np.float32)
    cols[:] = PALETTE["concrete"]
    b.add_mesh(make_grid(xs, zs, np.zeros((nz, nx)), cols))
    nsx = max(1, round(hx / 4.0))                 # north + south walls
    seg = 2.0 * hx / nsx
    for i in range(nsx):
        x0 = -hx + seg * (i + 0.5)
        for sz in (1.0, -1.0):
            b.add_mesh(make_box((seg, 4.0, 0.6), PALETTE["concrete"],
                                offset=(x0, -2.02, sz * (hz - 0.3))))
    nsz = max(1, round(hz / 4.0))                 # east + west walls
    seg = 2.0 * hz / nsz
    for i in range(nsz):
        z0 = -hz + seg * (i + 0.5)
        for sx in (1.0, -1.0):
            b.add_mesh(make_box((0.6, 4.0, seg), PALETTE["concrete"],
                                offset=(sx * (hx - 0.3), -2.02, z0)))
    return b.build()


def _ensure_model_draws() -> list:
    """Build the showcase meshes once (needs the GL context to exist)."""
    global _model_draws
    if _model_draws is not None:
        return _model_draws
    from engine.mesh import Mesh
    from engine.meshdata import MeshBuilder, make_box
    from models.bastion import build_bastion_tel
    from models.common import PALETTE
    from models.oniks import build_oniks, build_oniks_booster
    from models.ships_models import build_cargo, build_tanker, build_warship
    from models.structures import (build_fuel_depot, build_harbor,
                                   build_radar_station)

    # display stands under the missile + booster assembly
    stands = MeshBuilder()
    for z in (-5.2, -2.0, 2.0):
        stands.add_mesh(make_box((0.35, 0.95, 0.5), PALETTE["concrete"],
                                 offset=(0.0, 0.475, z)))
    p = np.array([PAD_X, PAD_TOP, PAD_Z], dtype=np.float64)
    f = np.array([FLEET_X, 0.0, FLEET_Z], dtype=np.float64)
    s = np.array([SHORE_X, PAD_TOP, SHORE_Z], dtype=np.float64)
    # diagonal spread so the NE "front" camera sees each silhouette clear
    _model_draws = [
        (Mesh(_pad_mesh(24.0, 15.0)), p),                        # deck at PAD_TOP
        (Mesh(build_bastion_tel(elevation_deg=88.0)), p + (-12.0, 0.0, 7.0)),
        (Mesh(build_bastion_tel(elevation_deg=0.0)), p + (1.0, 0.0, 1.0)),
        (Mesh(stands.build()), p + (13.0, 0.0, -5.0)),
        (Mesh(build_oniks()), p + (13.0, 0.95, -5.0)),
        (Mesh(build_oniks_booster()), p + (13.0, 0.95, -10.45)),  # behind tail
        # ships at anchor (waterline origins) in a bow-to-stern line
        (Mesh(build_tanker()), f + (0.0, 0.0, -200.0)),
        (Mesh(build_cargo()), f + (0.0, 0.0, 60.0)),
        (Mesh(build_warship()), f + (0.0, 0.0, 280.0)),
        # structures pad: fuel depot west half, radar station east edge
        (Mesh(_pad_mesh(70.0, 40.0)), s),
        (Mesh(build_fuel_depot()), s + (-25.0, 0.0, 0.0)),
        (Mesh(build_radar_station()), s + (45.0, 0.0, -12.0)),
        # harbor floats on its own (quay tops 2.5 m over the waterline)
        (Mesh(build_harbor()),
         np.array([SHORE_X, 0.0, HARBOR_Z], dtype=np.float64)),
    ]
    return _model_draws


def _render_frame(app: App, name: str) -> None:
    app.state.render(0.0)
    if name in MODEL_SCENES:
        for mesh, pos in _ensure_model_draws():
            app.renderer.draw_mesh(mesh, pos)


def shoot(app: App, name: str) -> str:
    if name in SCENE_STEPS:
        # Flight scenes script a launch: start from a fresh sandbox so the
        # launcher is armed and the sky is empty regardless of scene order.
        from game.sandbox import SandboxState
        app.states.switch(SandboxState(app))
    SCENES[name](app.state)
    for _ in range(SCENE_STEPS.get(name, SIM_STEPS)):
        app.state.sim_step(PHYS_DT)
    # Terrain LOD0/LOD1 meshes stream in over frames (budgeted builds);
    # draw until the build queue drains so the still shows full detail.
    for _ in range(MAX_WARMUP_FRAMES):
        _render_frame(app, name)
        if not app.state.terrain._jobs:
            break
    _render_frame(app, name)
    surf = app.window.read_pixels_to_surface()
    path = os.path.join(OUT_DIR, f"{name}.png")
    pygame.image.save(surf, path)
    return os.path.abspath(path)


def main(argv: list[str]) -> None:
    names = argv or list(SCENES)
    # "models" expands to the three orbit angles of the showcase pad
    names = [m for n in names
             for m in (MODEL_SCENES if n == "models" else (n,))]
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
