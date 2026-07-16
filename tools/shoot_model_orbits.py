"""360-degree audit renders for every vehicle and structure in the game.

For each in-scope model, the audit samples a sphere rather than one shallow
orbit: 8 azimuths at level, 45-degree underside, 45-degree overhead, and
70-degree overhead elevations, plus exact top and bottom views. Full-resolution
frames, per-elevation contact sheets, and one overview sheet are written. A
camera-facing inspection light keeps undersides readable, and oversized sites
may define close-detail regions in addition to their full-model orbit. Missiles,
ammunition, debris, and weather presets are intentionally excluded.

Outputs default to ``documentation and research/02_vehicle_structure_models/
renders/current``. Set ``ORBIT_OUT_DIR`` to keep a separate before/after run.

Run: python tools/shoot_model_orbits.py [asset_id ...]   (default: all)
"""

from __future__ import annotations

import json
import math
import os
import sys

import numpy as np
import pygame

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playtest_harness import Battle
import engine.renderer as renderer_config
from engine.mesh import Mesh
from game.testing_catalog import TEST_ASSETS, load_mesh_data, mesh_metadata

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.environ.get(
    "ORBIT_OUT_DIR",
    os.path.join(
        REPO_ROOT, "documentation and research",
        "02_vehicle_structure_models", "renders", "current",
    ),
)
POS = np.array([0.0, 3000.0, 80_000.0], dtype=np.float64)  # clean sky bg
TILE_W, TILE_H = 480, 270
COLS, ROWS = 4, 2
AZIMUTHS = (0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0)
ELEVATIONS = (-45.0, 0.0, 45.0, 70.0)
POLAR_VIEWS = ((0.0, 90.0), (0.0, -90.0))
IN_SCOPE_CATEGORIES = frozenset(("GROUND", "STRUCTURES", "AIRCRAFT", "SHIPS"))
DETAIL_REGIONS = {
    # The complete 2.5 km installation remains in the main orbit. These local
    # inspection regions keep its small but important facilities readable too.
    "airfield": (
        ("runway_18_threshold", (0.0, 1.0, 1110.0), 72.0),
        ("runway_36_threshold", (0.0, 1.0, -1110.0), 72.0),
        ("hangar_apron", (128.0, 10.0, 0.0), 82.0),
        ("tower_taxiway", (150.0, 18.0, 180.0), 88.0),
    ),
}
DETAIL_VIEWS = tuple((azimuth, 20.0) for azimuth in AZIMUTHS) + (
    (0.0, 70.0), (0.0, 90.0),
)


def _assets():
    """Stable-id catalog for every non-munition vehicle and structure."""

    return {
        asset.id: asset for asset in TEST_ASSETS
        if asset.kind == "mesh" and asset.category in IN_SCOPE_CATEGORIES
    }


class StaticModel:
    """Frozen level entity carrying a bare mesh for the orbit camera."""

    def __init__(self, pos):
        self.pos = np.array(pos, dtype=np.float64)
        self.prev_pos = self.pos.copy()
        self.body_dir = np.array([0.0, 0.0, 1.0], dtype=np.float64)
        self.vel = np.array([0.0, 0.0, 1.0], dtype=np.float64)
        self.alive = True


def _extent(meshdata) -> tuple[float, np.ndarray]:
    """Return framing radius and center offset from a mesh bounding box."""

    vertices = meshdata.vertices[:, :3]
    lo, hi = vertices.min(axis=0), vertices.max(axis=0)
    center = (lo + hi) * 0.5
    radius = float(np.linalg.norm(hi - lo)) * 0.5
    return max(radius, 2.0), center


def _signed_angle(value: float) -> str:
    rounded = int(round(value))
    return f"p{rounded:03d}" if rounded >= 0 else f"m{abs(rounded):03d}"


def _label_tile(tile: pygame.Surface, asset_id: str, azimuth: float,
                elevation: float) -> None:
    if not pygame.font.get_init():
        pygame.font.init()
    font = pygame.font.Font(None, 24)
    label = f"{asset_id}   AZ {azimuth:03.0f} DEG   EL {elevation:+.0f} DEG"
    ink = font.render(label, True, (235, 241, 232))
    pad = 7
    plate = pygame.Surface((ink.get_width() + pad * 2,
                            ink.get_height() + pad * 2), pygame.SRCALPHA)
    plate.fill((8, 13, 15, 205))
    plate.blit(ink, (pad, pad))
    tile.blit(plate, (10, 10))


def _set_audit_light(azimuth: float, elevation: float) -> None:
    """Place a neutral key light behind the audit camera.

    Gameplay keeps its fixed sun. The evidence renderer needs inspectable
    undersides, so each isolated model receives a camera-facing studio light;
    this prevents -45/-90 views from collapsing into black silhouettes.
    """

    azimuth_rad = math.radians(azimuth)
    elevation_rad = math.radians(elevation)
    ce = math.cos(elevation_rad)
    renderer_config.SUN_DIR = np.array(
        [math.sin(azimuth_rad) * ce,
         math.sin(elevation_rad),
         math.cos(azimuth_rad) * ce],
        dtype=np.float64,
    )
    renderer_config.SUN_COLOR = (0.86, 0.85, 0.84)


def _shoot_detail_regions(battle: Battle, asset, draw_pos) -> list[dict]:
    """Capture close inspection orbits for oversized site sub-regions."""

    rows = []
    for region_id, center_local, radius in DETAIL_REGIONS.get(asset.id, ()):
        target = StaticModel(draw_pos + np.asarray(center_local, dtype=np.float64))
        distance = float(radius) * 2.75
        region_dir = os.path.join(OUT_DIR, "details", asset.id, region_id)
        os.makedirs(region_dir, exist_ok=True)
        sheet = pygame.Surface((TILE_W * 5, TILE_H * 2))
        sheet.fill((5, 8, 10))
        angle_paths = []
        for index, (azimuth, elevation) in enumerate(DETAIL_VIEWS):
            battle.follow(target, "orbit", dist=distance)
            rig = battle.state.rig
            rig._orbit_az = math.radians(azimuth)
            rig._orbit_el = math.radians(elevation)
            rig._orbit_dist = rig._orbit_dist_target = distance
            rig._orbit_idle = 0.0
            rig._blend_t = 10.0
            _set_audit_light(azimuth, elevation)
            battle.settle(3)
            frame = battle.app.window.read_pixels_to_surface()
            angle_path = os.path.join(
                region_dir,
                f"az_{int(azimuth):03d}_el_{_signed_angle(elevation)}.png",
            )
            pygame.image.save(frame, angle_path)
            angle_paths.append(os.path.relpath(angle_path, OUT_DIR))
            tile = pygame.transform.smoothscale(frame, (TILE_W, TILE_H))
            _label_tile(tile, f"{asset.id}/{region_id}", azimuth, elevation)
            sheet.blit(tile, ((index % 5) * TILE_W, (index // 5) * TILE_H))
        sheet_path = os.path.join(
            OUT_DIR, f"{asset.id}_detail_{region_id}.png")
        pygame.image.save(sheet, sheet_path)
        rows.append({
            "id": region_id,
            "center_local_m": list(center_local),
            "radius_m": radius,
            "distance_m": distance,
            "views_deg": [list(view) for view in DETAIL_VIEWS],
            "contact_sheet": os.path.relpath(sheet_path, OUT_DIR),
            "angle_renders": angle_paths,
        })
    return rows


def shoot(battle: Battle, asset, meshdata) -> dict[str, object]:
    """Render one asset from every audit azimuth and return its manifest row."""

    name = asset.id
    radius, center = _extent(meshdata)
    anchor = StaticModel(POS)
    draw_pos = POS - center
    battle.world.missiles[:] = []
    battle.state.hud_visible = False
    battle.state.map_open = False
    battle.state._site_draws.append((Mesh(meshdata), draw_pos))

    distance = radius * 2.75
    rig = battle.state.rig
    angle_dir = os.path.join(OUT_DIR, "angles", name)
    os.makedirs(angle_dir, exist_ok=True)
    angle_paths = []
    contact_sheets = []
    detail_regions = []
    overview = pygame.Surface((TILE_W * 8, TILE_H * 5))
    overview.fill((5, 8, 10))
    try:
        for elevation_index, elevation in enumerate(ELEVATIONS):
            sheet = pygame.Surface((TILE_W * COLS, TILE_H * ROWS))
            for index, azimuth in enumerate(AZIMUTHS):
                battle.follow(anchor, "orbit", dist=distance)
                rig._orbit_az = math.radians(azimuth)
                rig._orbit_el = math.radians(elevation)
                rig._orbit_dist = rig._orbit_dist_target = distance
                rig._orbit_idle = 0.0
                rig._blend_t = 10.0
                _set_audit_light(azimuth, elevation)
                battle.settle(3)
                frame = battle.app.window.read_pixels_to_surface()
                angle_path = os.path.join(
                    angle_dir,
                    f"az_{int(azimuth):03d}_el_{_signed_angle(elevation)}.png",
                )
                pygame.image.save(frame, angle_path)
                angle_paths.append(os.path.relpath(angle_path, OUT_DIR))
                tile = pygame.transform.smoothscale(frame, (TILE_W, TILE_H))
                _label_tile(tile, name, azimuth, elevation)
                sheet.blit(
                    tile,
                    ((index % COLS) * TILE_W, (index // COLS) * TILE_H),
                )
                overview.blit(tile, (index * TILE_W,
                                     elevation_index * TILE_H))
            sheet_path = os.path.join(
                OUT_DIR, f"{name}_el_{_signed_angle(elevation)}_orbit.png")
            pygame.image.save(sheet, sheet_path)
            contact_sheets.append(os.path.relpath(sheet_path, OUT_DIR))

        for polar_index, (azimuth, elevation) in enumerate(POLAR_VIEWS):
            battle.follow(anchor, "orbit", dist=distance)
            rig._orbit_az = math.radians(azimuth)
            rig._orbit_el = math.radians(elevation)
            rig._orbit_dist = rig._orbit_dist_target = distance
            rig._orbit_idle = 0.0
            rig._blend_t = 10.0
            _set_audit_light(azimuth, elevation)
            battle.settle(3)
            frame = battle.app.window.read_pixels_to_surface()
            angle_path = os.path.join(
                angle_dir,
                f"az_{int(azimuth):03d}_el_{_signed_angle(elevation)}.png",
            )
            pygame.image.save(frame, angle_path)
            angle_paths.append(os.path.relpath(angle_path, OUT_DIR))
            tile = pygame.transform.smoothscale(frame, (TILE_W, TILE_H))
            _label_tile(tile, name, azimuth, elevation)
            overview.blit(tile, (polar_index * TILE_W, 4 * TILE_H))
        detail_regions = _shoot_detail_regions(battle, asset, draw_pos)
    finally:
        mesh, _ = battle.state._site_draws.pop()
        mesh.delete()

    overview_path = os.path.join(OUT_DIR, f"{name}_overview.png")
    pygame.image.save(overview, overview_path)
    print(f"[orbit] {overview_path}")
    return {
        "asset_id": name,
        "label": asset.label,
        "category": asset.category,
        "proxy_for": asset.proxy_for,
        "azimuths_deg": list(AZIMUTHS),
        "elevations_deg": list(ELEVATIONS),
        "polar_views_deg": [list(view) for view in POLAR_VIEWS],
        "distance_m": distance,
        "overview_sheet": os.path.relpath(overview_path, OUT_DIR),
        "contact_sheets": contact_sheets,
        "angle_renders": angle_paths,
        "detail_regions": detail_regions,
        "mesh": mesh_metadata(meshdata),
    }


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    wanted = sys.argv[1:]
    assets = _assets()
    names = wanted or list(assets)
    unknown = sorted(set(names) - set(assets))
    if unknown:
        print(
            f"Unknown or out-of-scope asset ids: {', '.join(unknown)}",
            file=sys.stderr,
        )
        return 2

    battle = Battle(7)
    manifest = []
    try:
        for name in names:
            asset = assets[name]
            manifest.append(shoot(battle, asset, load_mesh_data(asset)))
    finally:
        battle.close()

    manifest_path = os.path.join(OUT_DIR, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump({"assets": manifest}, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(f"[orbit] {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
