"""F3-P4 screenshot gate: render the cloud pass from 3 named viewpoints
hidden and save PNGs to renders/ for eyeball judgment against the
references (WT Dagor cumulus bank / Nubis figures).

Run:  python -m tools.probe_cloud_shots [seed]
"""

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pygame

from tools.cloud_probe_metrics import ALTITUDE_SWEEP_M, PRESET_VIEW_PLAN

VIEWS = (
    # name, cam pos (x, y, z), yaw, pitch
    ("ground_horizon", (0.0, 60.0, 5_000.0), 0.0, 0.12),
    ("inside_layer", (0.0, 1_400.0, 40_000.0), 0.3, 0.05),
    ("above_looking_down", (0.0, 9_000.0, 60_000.0), 0.0, -0.5),
    ("high_lookdown", (0.0, 17_500.0, 60_000.0), 0.0, -1.2),
    ("far_field", (0.0, 2_000.0, 5_000.0), 0.0, 0.02),
)

# Full inspection matrix requested by art review: four compass positions at
# level, 45 degrees above/below, and near-polar top/bottom views.  The polar
# views use 89 degrees internally because the camera basis is undefined at an
# exact pole, but retain the requested +/-90 labels.
ORBIT_AZIMUTHS_DEG = (0, 90, 180, 270)
ORBIT_ELEVATIONS_DEG = (0, 45, 90, -45, -90)
ORBIT_TILE = (400, 225)


def _look_target(pos, yaw: float, pitch: float, distance: float = 10_000.0):
    cp = float(np.cos(pitch))
    direction = np.array([np.sin(yaw) * cp, np.sin(pitch),
                          np.cos(yaw) * cp], dtype=np.float64)
    return np.asarray(pos, dtype=np.float64) + direction * distance


def _base_views():
    return {name: (name, np.asarray(pos, dtype=np.float64),
                   _look_target(pos, yaw, pitch))
            for name, pos, yaw, pitch in VIEWS}


def preset_gate_views(seed: int, preset: int):
    """Return the deterministic named view matrix for one V2 preset."""
    from sim.atmosphere import weather_preset
    from tools.probe_cloud_flight import find_cluster_v2

    spec = weather_preset(preset)
    base = _base_views()
    views = dict(base)
    high_y = float(spec.high.altitude_m)
    high_anchor = np.array([0.0, high_y, 40_000.0], dtype=np.float64)
    views.update({
        "high_cirrus_below": ("high_cirrus_below",
                               high_anchor + (-8_000.0, -3_000.0, -8_000.0),
                               high_anchor),
        "high_cirrus_edge": ("high_cirrus_edge",
                              high_anchor + (-10_000.0, 0.0, -10_000.0),
                              high_anchor + (0.0, 0.0, 10_000.0)),
        "high_cirrus_above": ("high_cirrus_above",
                               high_anchor + (-5_000.0, 4_000.0, -5_000.0),
                               high_anchor),
    })

    cluster = None
    if preset not in (0, 4):
        cluster = find_cluster_v2(seed, preset)
        c = np.asarray(cluster["center"], dtype=np.float64)
        outside = np.asarray(cluster["outside"], dtype=np.float64)
        edge = np.asarray(cluster["edge"], dtype=np.float64)
        top = float(cluster["top"])
        direction = outside - c
        direction[1] = 0.0
        direction /= max(float(np.linalg.norm(direction)), 1e-6)
        tower_wide = outside.copy()
        tower_wide[1] = 3_200.0
        tower_above_far = c + direction * 22_000.0
        tower_above_far[1] = top + 16_000.0
        storm_above_far = c + direction * 24_000.0
        storm_above_far[1] = top + 18_000.0
        storm_wide = tower_wide.copy()
        if preset == 6:
            # The resolver supplies the clean upwind side of the independent
            # supercell. Sit above the ambient mid deck so it cannot wash out
            # the tower/anvil profile being accepted.
            storm_wide = outside.copy()
            storm_wide[1] = 8_500.0
        under = np.array([c[0] - 4_000.0,
                          max(60.0, float(spec.lower.base_m) - 700.0),
                          c[2] - 4_000.0])
        views.update({
            "cluster_outside": ("cluster_outside", outside, c),
            "cluster_edge": ("cluster_edge", edge, c),
            "cluster_inside": ("cluster_inside", c, c + (2_000.0, 0.0, 0.0)),
            "cluster_above": ("cluster_above",
                              np.array([c[0] - 5_000.0, top + 5_000.0,
                                        c[2] - 5_000.0]), c),
            "deck_underbelly": ("deck_underbelly", under, c),
            "tower_underbelly": ("tower_underbelly", under, c),
            "tower_wide": ("tower_wide", tower_wide,
                           np.array([c[0], min(top * 0.66, 6_500.0), c[2]])),
            "tower_above_far": ("tower_above_far", tower_above_far, c),
            "storm_underbelly": ("storm_underbelly", under, c),
            "storm_tower_wide": ("storm_tower_wide", storm_wide,
                                 np.array([c[0], top * 0.54, c[2]])),
            "storm_anvil": ("storm_anvil",
                            np.array([c[0] - 12_000.0, top - 2_000.0,
                                      c[2] - 12_000.0]),
                            np.array([c[0], top - 1_000.0, c[2]])),
            "storm_above": ("storm_above",
                            np.array([c[0] - 7_000.0, top + 7_000.0,
                                      c[2] - 7_000.0]), c),
            "storm_above_far": ("storm_above_far", storm_above_far, c),
            "lightning_watch": ("lightning_watch", under, c),
        })
    planned = PRESET_VIEW_PLAN[int(preset)]
    return tuple(views[name] for name in planned), cluster


def altitude_gate_views(seed: int, preset: int):
    """Seven fixed altitudes aimed at the preset's resolved cloud region."""
    from sim.atmosphere import weather_preset
    from tools.probe_cloud_flight import find_cluster_v2
    spec = weather_preset(preset)
    if preset in (0, 4):
        target = np.array([0.0, float(spec.high.altitude_m), 40_000.0])
    else:
        target = np.asarray(find_cluster_v2(seed, preset)["center"],
                            dtype=np.float64)
    views = []
    for altitude in ALTITUDE_SWEEP_M:
        pos = np.array([target[0] - 12_000.0, altitude,
                        target[2] - 12_000.0], dtype=np.float64)
        views.append((f"alt_{altitude/1000:g}km", pos, target.copy()))
    return tuple(views)


def orbit_matrix_views(seed: int, preset: int):
    """Return the deterministic 4x5 full-surround inspection matrix.

    Every entry is ``(name, position, target, roll)``.  Radius is derived from
    the resolved formation rather than a camera-relative LOD, so the same seed
    and preset always frame the same cloud geography.
    """
    from sim.atmosphere import weather_preset
    from tools.probe_cloud_flight import find_cluster_v2

    spec = weather_preset(preset)
    cluster = None
    if preset == 0:
        target = np.array([40_000.0, 3_000.0, 40_000.0], dtype=np.float64)
        radius = 60_000.0
    elif preset == 4:
        target = np.array([40_000.0, float(spec.high.altitude_m), 40_000.0],
                          dtype=np.float64)
        radius = 70_000.0
    else:
        cluster = find_cluster_v2(seed, preset)
        target = np.asarray(cluster["center"], dtype=np.float64).copy()
        # Aim at the visual center of the complete containing slab; the local
        # density center can sit too low for anvils and too high for scud.
        target[1] = 0.5 * (float(cluster["base"]) + float(cluster["top"]))
        horizontal = float(cluster["radius"])
        vertical = float(cluster["top"]) - float(cluster["base"])
        minimum = 24_000.0 if preset in (1, 2) else 35_000.0
        radius = max(minimum, horizontal * 1.35, vertical * 2.4)
        if preset == 3:  # a deck is geography, not a discrete little object
            radius = max(radius, 70_000.0)

    views = []
    for elevation_label in ORBIT_ELEVATIONS_DEG:
        elevation = math.radians(
            89.0 if elevation_label == 90
            else -89.0 if elevation_label == -90
            else elevation_label)
        ce, se = math.cos(elevation), math.sin(elevation)
        for azimuth_deg in ORBIT_AZIMUTHS_DEG:
            azimuth = math.radians(azimuth_deg)
            if elevation_label == -90:
                # A true straight-up view cannot be both far below a 500 m
                # cloud base and above the world plane. Sample four seeded
                # points beneath the resolved core instead; each camera looks
                # vertically upward while remaining in usable atmospheric
                # haze, producing an honest readable underside.
                under_radius = (18_000.0 if cluster is None else
                                max(2_000.0,
                                    min(18_000.0,
                                        float(cluster["boundary"]) * 0.90)))
                horizontal = np.array([
                    math.sin(azimuth), 0.0, math.cos(azimuth)
                ], dtype=np.float64) * under_radius
                position = target + horizontal
                position[1] = 60.0
                view_target = position.copy()
                view_target[0] += math.sin(azimuth) * 1.0
                view_target[2] += math.cos(azimuth) * 1.0
                view_target[1] = (float(cluster["top"])
                                  if cluster is not None else target[1])
            else:
                offset = np.array([
                    math.sin(azimuth) * ce,
                    se,
                    math.cos(azimuth) * ce,
                ], dtype=np.float64) * radius
                position = target + offset
                view_target = target.copy()
            name = f"orbit_el{elevation_label:+03d}_az{azimuth_deg:03d}"
            roll = azimuth if abs(elevation_label) == 90 else 0.0
            views.append((name, position, view_target, roll))
    return tuple(views), cluster


def _grab_frame(window):
    from OpenGL.GL import GL_RGB, GL_UNSIGNED_BYTE, glReadPixels
    w, h = window.size()
    buf = glReadPixels(0, 0, w, h, GL_RGB, GL_UNSIGNED_BYTE)
    return pygame.image.frombytes(buf, (w, h), "RGB", True)


def _save_frame(window, path):
    surf = _grab_frame(window)
    pygame.image.save(surf, str(path))
    print(f"[shots] wrote {path}")
    return surf


def _save_orbit_sheet(frames, labels, path, preset_name: str, seed: int):
    tile_w, tile_h = ORBIT_TILE
    header_h = 34
    sheet = pygame.Surface((tile_w * len(ORBIT_AZIMUTHS_DEG),
                            header_h + tile_h * len(ORBIT_ELEVATIONS_DEG)))
    sheet.fill((8, 12, 18))
    font = pygame.font.SysFont("consolas", 16)
    title = font.render(
        f"{preset_name}  |  SEED {seed}  |  rows elevation / columns azimuth",
        True, (255, 220, 72))
    sheet.blit(title, (8, 8))
    for index, (frame, label) in enumerate(zip(frames, labels)):
        thumb = pygame.transform.smoothscale(frame, (tile_w, tile_h))
        tag = font.render(label, True, (255, 220, 72), (0, 0, 0))
        thumb.blit(tag, (6, 6))
        sheet.blit(thumb, ((index % 4) * tile_w,
                           header_h + (index // 4) * tile_h))
    pygame.image.save(sheet, str(path))
    print(f"[shots] wrote {path}")


def main(seed: int = 7, renderer: str = "legacy", quality: str = "high",
         preset: int = 1, view: str | None = None,
         cluster_views: bool = False, preset_views: bool = False,
         altitude_sweep: bool = False, orbit_matrix: bool = False) -> int:
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from main import App, PHYS_DT
    from world.combat_config import CombatConfig
    os.environ["ONIKS_CLOUD_RENDERER"] = renderer
    os.environ["ONIKS_CLOUD_QUALITY"] = quality
    # A user's saved Graphics override must never relabel every acceptance
    # capture as the same weather.  Probes follow CombatConfig explicitly.
    os.environ["ONIKS_CLOUD_WEATHER"] = "battle"
    app = App(hidden=True)
    app.start_combat(CombatConfig(seed=seed, weather_preset=preset))
    s = app.state
    try:
        for _ in range(120):
            s.sim_step(PHYS_DT)          # settle particles / streams
        os.makedirs("renders", exist_ok=True)
        s.hud_visible = False
        s.rig.set_mode("free")
        if orbit_matrix:
            # Orbit sheets are cloud-asset inspections.  Screen-space rain,
            # lightning and storm darkness are valuable in gameplay but can
            # completely hide the requested below/underbelly silhouettes.
            s.weather_overlay.draw = lambda *args, **kwargs: None
            s.terrain.draw = lambda *args, **kwargs: None
            s.ocean.draw = lambda *args, **kwargs: None
        views = tuple((name, np.asarray(pos, dtype=np.float64),
                       _look_target(pos, yaw, pitch))
                      for name, pos, yaw, pitch in VIEWS)
        if cluster_views and renderer == "v2":
            from tools.probe_cloud_flight import find_cluster_v2
            cluster = find_cluster_v2(seed, preset)
            c = cluster["center"]
            top = cluster["top"]
            # name, position, explicit target
            views = (
                ("cluster_outside", cluster["outside"], c),
                ("cluster_edge", cluster["edge"], c),
                ("cluster_inside", c, c + (2000.0, 0.0, 0.0)),
                ("cluster_above", np.array([c[0] - 5000.0, top + 5000.0,
                                             c[2] - 5000.0]),
                 c),
            )
        if preset_views:
            if renderer != "v2":
                raise RuntimeError("preset views require --renderer v2")
            views, _cluster = preset_gate_views(seed, preset)
        if altitude_sweep:
            if renderer != "v2":
                raise RuntimeError("altitude sweep requires --renderer v2")
            views = altitude_gate_views(seed, preset)
        if orbit_matrix:
            if renderer != "v2":
                raise RuntimeError("orbit matrix requires --renderer v2")
            views, _cluster = orbit_matrix_views(seed, preset)
        captured = 0
        orbit_frames = []
        orbit_labels = []
        for entry in views:
            name, pos, target = entry[:3]
            roll = float(entry[3]) if len(entry) > 3 else 0.0
            if view is not None and name != view:
                continue
            target = np.asarray(target, dtype=np.float64)
            delta = target - np.asarray(pos, dtype=np.float64)
            s.rig.freecam.pos = np.asarray(pos, dtype=np.float64)
            s.rig.freecam.yaw = float(np.arctan2(delta[0], delta[2]))
            s.rig.freecam.pitch = float(np.arcsin(
                np.clip(delta[1] / max(np.linalg.norm(delta), 1e-6), -1, 1)))
            s.rig.freecam.roll = roll
            s.rig.update(0.0, None)
            if orbit_matrix:
                # The gameplay freecam is correctly ground-clamped.  Asset
                # inspection needs a true spherical orbit, including cameras
                # below the world plane, so drive the render camera directly.
                s.camera.set_look(pos, target)
                s.camera.roll = roll
            settle_limit = 240 if captured == 0 else 40
            for _ in range(settle_limit):  # let terrain LOD stream for the view
                s.render(1 / 60)
                if not s.terrain._jobs:
                    break
            s.render(1 / 60)
            clouds = getattr(s, "clouds", None)
            actual = getattr(clouds, "backend_name", "off")
            if renderer == "v2" and not getattr(clouds, "using_v2", False):
                raise RuntimeError("requested V2 capture entered legacy fallback")
            frame = _save_frame(
                s.window,
                f"renders/clouds_{actual}_{quality}_p{preset}_{name}_seed{seed}.png")
            if orbit_matrix:
                orbit_frames.append(frame)
                orbit_labels.append(name.replace("orbit_", ""))
            captured += 1
        if captured == 0:
            raise RuntimeError(f"view {view!r} is not in the selected view set")
        if orbit_matrix and view is None:
            from sim.atmosphere import weather_preset
            _save_orbit_sheet(
                orbit_frames, orbit_labels,
                f"renders/cloud_orbit_{actual}_{quality}_p{preset}_seed{seed}.png",
                weather_preset(preset).name, seed)
    finally:
        s.dispose()
        pygame.quit()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Capture cloud gate views.")
    parser.add_argument("seed", nargs="?", type=int, default=7)
    parser.add_argument("--renderer", choices=("legacy", "v2"), default="legacy")
    parser.add_argument("--quality", choices=("low", "med", "high", "ultra"),
                        default="high")
    parser.add_argument("--preset", type=int, choices=range(7), default=1)
    parser.add_argument(
        "--view",
        choices=tuple(sorted(
            {v[0] for v in VIEWS}
            | {name for plan in PRESET_VIEW_PLAN.values() for name in plan}
            | {"cluster_outside", "cluster_edge", "cluster_inside",
               "cluster_above"}
            | {f"orbit_el{el:+03d}_az{az:03d}"
               for el in ORBIT_ELEVATIONS_DEG
               for az in ORBIT_AZIMUTHS_DEG}
            | {f"alt_{altitude/1000:g}km" for altitude in ALTITUDE_SWEEP_M})))
    parser.add_argument("--cluster-views", action="store_true",
                        help="capture outside/edge/inside/above around a V2 cluster")
    parser.add_argument("--preset-views", action="store_true",
                        help="capture the deterministic view plan for this preset")
    parser.add_argument("--altitude-sweep", action="store_true",
                        help="capture the 0.06/1/4/10/17.5/30/50 km sweep")
    parser.add_argument("--orbit-matrix", action="store_true",
                        help="capture 4 azimuths at 0/+45/+90/-45/-90 degrees")
    args = parser.parse_args()
    raise SystemExit(main(args.seed, args.renderer, args.quality, args.preset,
                          args.view, args.cluster_views, args.preset_views,
                          args.altitude_sweep, args.orbit_matrix))
