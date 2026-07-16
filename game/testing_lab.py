"""Hidden F3 asset inspection lab.

The lab is intentionally reached only from the main menu's raw F3 handler.
It owns no simulation state: procedural meshes are loaded one at a time into
an adaptive, true-scale inspection chamber, while weather catalog entries use
the real V2 cloud and presentation systems as full-size environments.

OpenGL work is deferred to :meth:`TestingLabState.enter`, matching the other
game states' headless-input convention.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
import math
import os
import threading

import numpy as np
import pygame

from engine.camera import Camera
from engine.meshdata import MeshBuilder, make_box
from engine.text import BODY_SIZE, HEADER_SIZE, SMALL_SIZE
from game.states import (
    ACCENT,
    ACCENT_DIM,
    BELIEF,
    BG0,
    BG2,
    DANGER,
    DISABLED,
    FAINT,
    LINE_COL,
    MUTED,
    OK_COL,
    PAPER_BG,
    PAPER_INK,
    PAPER_MUTED,
    PLATE_INK,
    TEXT_COL,
    GameState,
    draw_panel,
)
from game.testing_catalog import (
    CATEGORIES,
    TestAsset,
    filter_assets,
    load_mesh_data,
    mesh_metadata,
    write_testing_feedback,
)
from game.missile_workbench import (
    ALTITUDES_KM,
    RANGES_KM,
    RUN_COUNTS,
    TELEMETRY_LEVELS,
    TRACK_UPDATES_S,
    VARIATIONS,
    WEAPONS,
    WEAPON_LABELS,
    WorkbenchConfig,
    cycle_value,
    run_batch,
)
from tools.probe_sam_flight_computer import MOTION_VELOCITIES
from world.cinematic_scene import list_scenes


SIDEBAR_W = 372
SCREEN_PAD = 16
PREVIEW_TOP = 16
PREVIEW_BOTTOM = 58
LIST_ROW_H = 30
FEEDBACK_TYPES = (
    "BUG",
    "VISUAL",
    "GEOMETRY",
    "SCALE",
    "MATERIAL",
    "PERFORMANCE",
    "SUGGESTION",
)
WEATHER_QUALITIES = ("low", "med", "high", "ultra")


def _clamp(value: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, float(value)))


def _inside(pos, rect) -> bool:
    if rect is None:
        return False
    x0, y0, x1, y1 = rect
    return x0 <= pos[0] <= x1 and y0 <= pos[1] <= y1


def _nice_axis_ceiling(value: float) -> float:
    """Round a positive plot limit to four readable grid intervals."""
    value = max(float(value), 1e-9)
    rough = value / 4.0
    magnitude = 10.0 ** math.floor(math.log10(rough))
    scaled = rough / magnitude
    step = next((candidate for candidate in (1.0, 2.0, 2.5, 4.0, 5.0, 10.0)
                 if candidate >= scaled), 10.0) * magnitude
    return step * math.ceil(value / step)


def build_inspection_chamber(stats: dict):
    """Build a sparse open frame and scale grid around one centered mesh."""

    dims = np.maximum(np.asarray(stats["dimensions"], dtype=np.float64), 0.01)
    radius = max(float(stats["radius"]), 0.1)
    room_x = max(dims[0] * 0.78, radius * 0.76, 1.5)
    room_z = max(dims[2] * 0.78, radius * 0.76, 1.5)
    object_low = -dims[1] * 0.5
    pedestal_h = _clamp(radius * 0.10, 0.15, max(0.35, radius * 0.30))
    pedestal_top = object_low - max(0.03, radius * 0.004)
    floor_y = pedestal_top - pedestal_h
    ceiling_y = max(dims[1] * 0.72, radius * 0.72, 1.5)
    beam = max(0.025, min(room_x, room_z) * 0.012)
    grid_w = max(0.012, min(room_x, room_z) * 0.004)

    floor_col = (0.085, 0.115, 0.105)
    grid_col = (0.265, 0.335, 0.295)
    frame_col = (0.48, 0.385, 0.18)
    pedestal_col = (0.22, 0.235, 0.215)
    b = MeshBuilder()
    b.add_mesh(make_box((room_x * 2.0, beam, room_z * 2.0), floor_col),
               offset=(0.0, floor_y - beam * 0.5, 0.0))

    # Eleven divisions make object scale readable without a dense moire field.
    for i in range(-5, 6):
        x = room_x * i / 5.0
        z = room_z * i / 5.0
        b.add_mesh(make_box((grid_w, grid_w, room_z * 2.0), grid_col),
                   offset=(x, floor_y + grid_w * 0.5, 0.0))
        b.add_mesh(make_box((room_x * 2.0, grid_w, grid_w), grid_col),
                   offset=(0.0, floor_y + grid_w * 0.5, z))

    ped_x = max(dims[0] * 1.10, radius * 0.20, 0.8)
    ped_z = max(dims[2] * 1.10, radius * 0.20, 0.8)
    b.add_mesh(make_box((ped_x, pedestal_h, ped_z), pedestal_col),
               offset=(0.0, pedestal_top - pedestal_h * 0.5, 0.0))

    height = ceiling_y - floor_y
    for x in (-room_x, room_x):
        for z in (-room_z, room_z):
            b.add_mesh(make_box((beam, height, beam), frame_col),
                       offset=(x, floor_y + height * 0.5, z))
    for z in (-room_z, room_z):
        b.add_mesh(make_box((room_x * 2.0, beam, beam), frame_col),
                   offset=(0.0, ceiling_y, z))
    for x in (-room_x, room_x):
        b.add_mesh(make_box((beam, beam, room_z * 2.0), frame_col),
                   offset=(x, ceiling_y, 0.0))
    return b.build()


class TestingLabState(GameState):
    """Hidden catalog, true-scale preview camera, and feedback workflow."""

    __test__ = False

    def __init__(self, app):
        super().__init__(app)
        self.window = app.window
        self.renderer = app.renderer
        self.camera = Camera(fov_y_deg=55.0, near=0.05)

        # Catalog navigation remains GL-free and is safe in unit tests.
        self.category_index = 0
        self.query = ""
        self.search_active = False
        all_assets = filter_assets()
        self.selected = next(
            (i for i, asset in enumerate(all_assets) if asset.id == "oniks"), 0)
        self.scroll = 0
        self.ui_hidden = False

        # Deferred scene resources.
        self._gl = None
        self._Mesh = None
        self.text = None
        self.sky = None
        self.model_mesh = None
        self.chamber_mesh = None
        self.clouds = None
        self.weather_fx = None
        self.weather_overlay = None
        self.effect_driver = None        # EFFECTS tab: looping fx driver
        self.effect_fx = None            # its GL-free particle pools
        self._particle_renderer = None   # lazy, reused across effects
        self.loaded_asset: TestAsset | None = None
        self.mesh_stats: dict | None = None
        self.model_pos = np.zeros(3, dtype=np.float64)
        self.backend = "---"
        self._disposed = False

        # Dedicated unrestricted orbit camera (airfield-safe and belly-safe).
        self.target = np.zeros(3, dtype=np.float64)
        self.orbit_az = math.radians(35.0)
        self.orbit_el = math.radians(18.0)
        self.orbit_dist = 20.0
        self.min_dist = 0.2
        self.max_dist = 100.0
        self._home_pose = None
        self.auto_orbit = False
        self._drag_button = None
        self._last_mouse = (0, 0)
        self.angle_entry_active = False
        self.angle_entry = ""
        self._clean_capture = None
        self.last_capture_path = None

        prefs = getattr(app, "ui_prefs", None)
        quality = prefs.get("cloud_quality") if prefs is not None else "high"
        self.weather_quality = quality if quality in WEATHER_QUALITIES else "high"
        self.seed = 7
        self.loaded_seed = 0
        self.loaded_weather_quality = "---"
        self.cloud_time = 0.0
        self.weather_paused = False
        self._weather_frame = None

        # Render-populated hit rectangles.
        self._preview_box = None
        self._row_rects: list[tuple[int, tuple]] = []
        self._category_prev_rect = None
        self._category_next_rect = None
        self._search_rect = None
        self._search_clear_rect = None
        self._generate_rect = None
        self._sidebar_box = None
        self._list_capacity = 1

        self.feedback = None
        self.last_report_path = None
        self.status = "SELECT AN ASSET AND PRESS GENERATE"
        self.status_left = 4.0
        self.status_danger = False

        # F6 / tab: production-physics missile batch workbench.  The worker is
        # deliberately GL-free; the main thread only polls immutable results.
        self.lab_mode = "assets"
        self.flight_config = WorkbenchConfig()
        self.flight_batch = None
        self.flight_progress = (0, 0)
        self.flight_error = None
        self.selected_flight_run = None
        self.flight_run_scroll = 0
        self._flight_future = None
        self._flight_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="missile-workbench")
        self._flight_cancel = threading.Event()
        self._tab_asset_rect = None
        self._tab_flight_rect = None

        # CINEMATIC tab: baked real-world walkabout scenes (F7).
        self.cinema_scenes = list_scenes()
        self.cinema_sel = 0
        self._tab_cinema_rect = None
        self._cinema_row_rects: list[tuple[int, tuple]] = []
        self._cinema_enter_rect = None
        self._cinema_meta_cache: dict[str, dict] = {}
        self._flight_control_rects = {}
        self._flight_run_rect = None
        self._flight_result_rects = []
        self._flight_results_box = None

    # -------------------------------------------------------------- lifecycle

    def enter(self) -> None:
        pygame.event.set_grab(False)
        pygame.mouse.set_visible(True)
        if self._gl is None:
            import OpenGL.GL as gl
            from engine.mesh import Mesh
            from world.sky import Sky

            self._gl = gl
            self._Mesh = Mesh
            self.text = self.app.ui_text()
            self.sky = Sky()
        if self.loaded_asset is None:
            self.generate_selected(show_loading=False)

    def leave(self) -> None:
        self._drag_button = None
        pygame.event.set_grab(False)
        pygame.mouse.set_visible(True)
        self.app.audio.stop_loops()

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        if self.feedback is not None:
            self._cancel_feedback(show_status=False)
        self._destroy_preview()
        self._flight_cancel.set()
        self._flight_executor.shutdown(wait=False, cancel_futures=True)
        if self._particle_renderer is not None:
            self._particle_renderer.delete()
            self._particle_renderer = None
        if self.sky is not None:
            self.sky.delete()
            self.sky = None

    def effective_time_scale(self) -> float:
        return 0.0

    # --------------------------------------------------------------- catalog

    @property
    def category(self) -> str:
        return CATEGORIES[self.category_index]

    def visible_assets(self) -> tuple[TestAsset, ...]:
        return filter_assets(self.category, self.query)

    def selected_asset(self) -> TestAsset | None:
        assets = self.visible_assets()
        if not assets:
            return None
        self.selected = min(max(0, self.selected), len(assets) - 1)
        return assets[self.selected]

    def _move_selection(self, delta: int) -> None:
        assets = self.visible_assets()
        if not assets:
            self.selected = self.scroll = 0
            return
        self.selected = (self.selected + int(delta)) % len(assets)
        self.app.audio.ui_click()

    def _scroll_selection(self, delta: int) -> None:
        """Wheel navigation clamps at the list ends instead of wrapping."""
        assets = self.visible_assets()
        if not assets:
            self.selected = self.scroll = 0
            return
        old = self.selected
        self.selected = max(0, min(len(assets) - 1,
                                   self.selected + int(delta)))
        if self.selected != old:
            self.app.audio.ui_click()

    def _change_category(self, delta: int) -> None:
        self.category_index = (self.category_index + int(delta)) % len(CATEGORIES)
        self.selected = self.scroll = 0
        self.app.audio.ui_click()

    def _destroy_preview(self) -> None:
        for name in ("model_mesh", "chamber_mesh", "clouds", "weather_overlay"):
            resource = getattr(self, name, None)
            if resource is not None:
                try:
                    resource.delete()
                except Exception:
                    pass
                setattr(self, name, None)
        self.weather_fx = None
        self._weather_frame = None
        self.effect_driver = None
        self.effect_fx = None
        self.loaded_asset = None
        self.mesh_stats = None

    def generate_selected(self, show_loading: bool = True) -> bool:
        asset = self.selected_asset()
        if asset is None or self._Mesh is None:
            self._show_status("NO ASSET SELECTED", danger=True)
            return False
        if show_loading:
            self.app._draw_loading_frame(f"GENERATING {asset.label}...")
        self._destroy_preview()
        try:
            if asset.kind == "mesh":
                md = load_mesh_data(asset)
                stats = mesh_metadata(md)
                self.model_mesh = self._Mesh(md)
                self.chamber_mesh = self._Mesh(build_inspection_chamber(stats))
                self.mesh_stats = stats
                self.model_pos = -np.asarray(stats["center"], dtype=np.float64)
                self.backend = "PROCEDURAL MESH / LIT"
                self.loaded_seed = 0
                self.loaded_weather_quality = "---"
                self._frame_mesh(stats)
            elif asset.kind == "effect":
                self._generate_effect(asset)
            else:
                self._generate_weather(asset)
            self.loaded_asset = asset
            self._show_status(f"GENERATED {asset.label}")
            self.app.audio.ui_click()
            return True
        except Exception as exc:
            self._destroy_preview()
            self.backend = "FAILED"
            self._show_status(
                f"GENERATION FAILED: {type(exc).__name__}: {exc}", danger=True,
                seconds=6.0)
            print(f"[testing-lab] failed to generate {asset.id}: {exc}")
            return False

    def _activate_selected(self) -> bool:
        """Generate the focused row and reveal it after a filtered search."""
        asset = self.selected_asset()
        if asset is None or not self.generate_selected():
            return False
        if self.query:
            self.query = ""
            self.search_active = False
            assets = self.visible_assets()
            self.selected = next(
                (i for i, item in enumerate(assets) if item.id == asset.id), 0)
            self.scroll = max(0, self.selected - self._list_capacity // 2)
        return True

    def _frame_mesh(self, stats: dict) -> None:
        radius = max(float(stats["radius"]), 0.1)
        fit = radius / max(math.sin(self.camera.fov_y * 0.5), 0.1) * 1.22
        self.target = np.zeros(3, dtype=np.float64)
        self.orbit_az = math.radians(35.0)
        self.orbit_el = math.radians(18.0)
        self.orbit_dist = fit
        self.min_dist = max(radius * 1.02, 0.12)
        self.max_dist = max(fit * 6.0, self.min_dist * 2.0)
        self._save_home_pose()
        self._apply_camera()

    def _generate_effect(self, asset: TestAsset) -> None:
        """EFFECTS tab: a looping particle driver + the raised TEL for
        scale on the launch-family effects."""
        import importlib

        from engine.particles import ParticleRenderer
        from game.cinematic_missiles import CinematicEffects

        mod = importlib.import_module(asset.module)
        driver = getattr(mod, asset.builder)(**asset.kwargs)
        self.effect_driver = driver
        self.effect_fx = CinematicEffects(seed=5)
        if self._particle_renderer is None:
            self._particle_renderer = ParticleRenderer()
        if any(k in asset.id for k in ("launch", "pad_blast", "cold_eject",
                                       "ignition")):
            from models.s300 import build_s300_tel
            self.model_mesh = self._Mesh(build_s300_tel(elevation_deg=90.0))
            self.model_pos = np.zeros(3, dtype=np.float64)
        self.backend = "PARTICLE FX / LOOPING"
        self.loaded_seed = 5
        self.loaded_weather_quality = "---"
        dist = float(getattr(driver, "cam_dist", 50.0))
        self.target = np.array([0.0, dist * 0.22, 0.0], dtype=np.float64)
        self.orbit_az = math.radians(35.0)
        self.orbit_el = math.radians(8.0)
        self.orbit_dist = dist
        self.min_dist = 2.0
        self.max_dist = dist * 8.0
        self._save_home_pose()
        self._apply_camera()

    def _generate_weather(self, asset: TestAsset) -> None:
        from game.weather_effects import (
            WeatherEffectsController,
            WeatherOverlayRenderer,
        )
        from sim.atmosphere import weather_preset
        from world.clouds_v2 import CloudsV2

        spec = weather_preset(asset.preset_id)
        self.clouds = CloudsV2(
            self.seed, quality=self.weather_quality, weather_preset=spec)
        self.weather_fx = WeatherEffectsController(self.seed, spec)
        self.weather_overlay = WeatherOverlayRenderer()
        actual = getattr(self.clouds, "backend_name", "v2")
        if bool(getattr(self.clouds, "using_v2", False)):
            actual = "v2"
        self.backend = str(actual).upper()
        self.loaded_seed = self.seed
        self.loaded_weather_quality = self.weather_quality
        self.cloud_time = 0.0
        self.weather_paused = False
        self._frame_weather(spec)

    def _frame_weather(self, spec) -> None:
        from sim.atmosphere import (
            CONVECTIVE_DOMAIN_M,
            WEATHER_TILE_M,
            build_storm_cells,
            build_supercells,
        )

        cells = build_supercells(self.seed, spec)
        if cells:
            cell = max(
                cells,
                key=lambda c: ((c.top_m + c.overshoot_m)
                               * c.core_radius_m * c.intensity),
            )
            self.target = np.array([
                cell.x * CONVECTIVE_DOMAIN_M,
                (cell.base_m + cell.top_m + cell.overshoot_m) * 0.48,
                cell.z * CONVECTIVE_DOMAIN_M,
            ], dtype=np.float64)
            upwind = np.array([
                -math.cos(cell.heading_rad), 0.0,
                -math.sin(cell.heading_rad),
            ])
            self.orbit_az = math.atan2(upwind[0], upwind[2])
            self.orbit_el = math.radians(7.0)
            self.orbit_dist = max(cell.core_radius_m * 1.75, 18_000.0)
        else:
            storms = build_storm_cells(self.seed, spec)
            if storms:
                cell = max(storms, key=lambda c: c.radius_m * c.intensity)
                x, z = cell.x * WEATHER_TILE_M, cell.z * WEATHER_TILE_M
                distance = max(cell.radius_m * 1.6, 12_000.0)
            else:
                x = z = WEATHER_TILE_M * 0.5
                distance = 18_000.0
            tops = [layer.top_m for layer in (spec.lower, spec.upper)
                    if layer.enabled]
            base = next((layer.base_m for layer in (spec.lower, spec.upper)
                         if layer.enabled), 300.0)
            if max(spec.high.cirrus_coverage,
                   spec.high.strata_coverage) > 0.0:
                tops.append(spec.high.altitude_m)
            top = max(tops, default=3_000.0)
            self.target = np.array([x, (base + top) * 0.5, z],
                                   dtype=np.float64)
            self.orbit_az = math.radians(215.0)
            self.orbit_el = math.radians(-2.0)
            self.orbit_dist = distance
        self.min_dist = max(self.orbit_dist * 0.18, 250.0)
        self.max_dist = self.orbit_dist * 5.0
        self._save_home_pose()
        self._apply_camera()
        self._reset_cloud_history()

    # --------------------------------------------------------------- camera

    def _save_home_pose(self) -> None:
        self._home_pose = (
            self.target.copy(), self.orbit_az, self.orbit_el,
            self.orbit_dist, self.min_dist, self.max_dist,
        )

    def reset_camera(self) -> None:
        if self._home_pose is None:
            return
        target, az, el, distance, min_d, max_d = self._home_pose
        self.target = target.copy()
        self.orbit_az, self.orbit_el = az, el
        self.orbit_dist = distance
        self.min_dist, self.max_dist = min_d, max_d
        self.auto_orbit = False
        self._apply_camera()
        self._reset_cloud_history()

    def snap_view(self, number: int) -> None:
        if number == 0:
            self.reset_camera()
            return
        views = {
            1: (0.0, 0.0),
            2: (90.0, 0.0),
            3: (180.0, 0.0),
            4: (math.degrees(self.orbit_az), 90.0),
            5: (math.degrees(self.orbit_az), -90.0),
            6: (math.degrees(self.orbit_az), 45.0),
            7: (math.degrees(self.orbit_az), 70.0),
        }
        if number not in views:
            return
        az, el = views[number]
        self.set_view_angles(az, el)

    def set_view_angles(self, azimuth_deg: float,
                        elevation_deg: float) -> None:
        """Set an exact orbit pose entered by the inspector operator."""

        azimuth = float(azimuth_deg)
        elevation = float(elevation_deg)
        if not math.isfinite(azimuth) or not math.isfinite(elevation):
            raise ValueError("view angles must be finite")
        if not -90.0 <= elevation <= 90.0:
            raise ValueError("elevation must be between -90 and 90 degrees")
        self.orbit_az = math.radians(azimuth % 360.0)
        self.orbit_el = math.radians(elevation)
        self.auto_orbit = False
        self._apply_camera()
        self._reset_cloud_history()

    def _start_angle_entry(self) -> None:
        self.angle_entry_active = True
        self.angle_entry = ""
        self.auto_orbit = False
        self._show_status("TYPE AZIMUTH,ELEVATION - EXAMPLE 45,70")

    def _angle_entry_event(self, ev) -> None:
        if ev.type != pygame.KEYDOWN:
            return
        if ev.key == pygame.K_ESCAPE:
            self.angle_entry_active = False
            self.angle_entry = ""
            self._show_status("EXACT VIEW CANCELLED")
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            parts = self.angle_entry.replace(",", " ").split()
            try:
                if len(parts) != 2:
                    raise ValueError("enter AZ,EL")
                self.set_view_angles(float(parts[0]), float(parts[1]))
            except (TypeError, ValueError) as exc:
                self._show_status(f"INVALID VIEW: {exc}", danger=True,
                                  seconds=5.0)
                return
            self.angle_entry_active = False
            self.angle_entry = ""
            self._show_status(
                f"VIEW SET  AZ {math.degrees(self.orbit_az) % 360:.1f}  "
                f"EL {math.degrees(self.orbit_el):+.1f}")
            self.app.audio.ui_click()
        elif ev.key == pygame.K_BACKSPACE:
            self.angle_entry = self.angle_entry[:-1]
        else:
            char = getattr(ev, "unicode", "")
            if (char in "0123456789+-., "
                    and len(self.angle_entry) < 32):
                self.angle_entry += char

    def _apply_camera(self) -> None:
        ce = math.cos(self.orbit_el)
        offset = np.array([
            math.sin(self.orbit_az) * ce,
            math.sin(self.orbit_el),
            math.cos(self.orbit_az) * ce,
        ], dtype=np.float64) * self.orbit_dist
        self.camera.set_look(self.target + offset, self.target)

    def _orbit(self, dx: float, dy: float) -> None:
        # Match the normal game orbit camera: the view follows the pointer.
        self.orbit_az = (self.orbit_az + dx * 0.008) % (2.0 * math.pi)
        self.orbit_el = _clamp(
            self.orbit_el - dy * 0.008,
            math.radians(-90.0), math.radians(90.0))
        self.auto_orbit = False
        self._apply_camera()

    def _zoom(self, steps: float) -> None:
        self.orbit_dist = _clamp(
            self.orbit_dist * math.exp(-float(steps) * 0.14),
            self.min_dist, self.max_dist)
        self._apply_camera()

    def _reset_cloud_history(self) -> None:
        if self.clouds is not None and hasattr(self.clouds, "reset_history"):
            self.clouds.reset_history("testing-lab")

    @staticmethod
    def _angle_file_component(value: float) -> str:
        rounded = int(round(value))
        return f"p{rounded:03d}" if rounded >= 0 else f"m{abs(rounded):03d}"

    def _request_clean_capture(self) -> None:
        """Queue a clean, angle-labelled screenshot for the App back buffer."""

        asset = self.loaded_asset
        if asset is None:
            self._show_status("GENERATE AN ASSET BEFORE TAKING A PHOTO",
                              danger=True)
            return
        if getattr(self.app, "bug_shot_path", None):
            self._show_status("A SCREENSHOT IS ALREADY PENDING", danger=True)
            return
        base = getattr(self.app, "testing_capture_dir",
                       os.path.join("renders", "model_inspector"))
        base = base or os.path.join("renders", "model_inspector")
        os.makedirs(base, exist_ok=True)
        azimuth = math.degrees(self.orbit_az) % 360.0
        elevation = math.degrees(self.orbit_el)
        stem = (
            f"{asset.id}_az{int(round(azimuth)) % 360:03d}_"
            f"el{self._angle_file_component(elevation)}"
        )
        path = os.path.join(base, f"{stem}.png")
        suffix = 2
        while os.path.exists(path):
            path = os.path.join(base, f"{stem}_{suffix:02d}.png")
            suffix += 1
        self._clean_capture = {
            "path": path,
            "restore_ui": self.ui_hidden,
        }
        self.last_capture_path = os.path.abspath(path)
        self.ui_hidden = True
        self.app.bug_shot_path = path
        self.app.audio.ui_click()

    def _finish_clean_capture_if_ready(self) -> None:
        capture = self._clean_capture
        if capture is None or getattr(self.app, "bug_shot_path", None):
            return
        self.ui_hidden = capture["restore_ui"]
        self._clean_capture = None
        self._show_status(f"PHOTO SAVED: {os.path.basename(capture['path'])}",
                          seconds=5.0)

    # ------------------------------------------------------ missile workbench

    def _set_lab_mode(self, mode: str) -> None:
        if mode not in ("assets", "flight", "cinematic") \
                or mode == self.lab_mode:
            return
        if mode == "cinematic":
            # Rescan on entry: a bake may have finished since the lab
            # opened, and the sel must stay in range if scenes vanished.
            self.cinema_scenes = list_scenes()
            self.cinema_sel = min(self.cinema_sel,
                                  max(0, len(self.cinema_scenes) - 1))
            self._cinema_meta_cache.clear()
        self.lab_mode = mode
        self.search_active = False
        self.angle_entry_active = False
        self._drag_button = None
        self.app.audio.ui_click()

    def _cycle_flight_setting(self, name: str, delta: int) -> None:
        cfg = self.flight_config
        values = {
            "weapon": WEAPONS,
            "range_km": RANGES_KM,
            "altitude_km": ALTITUDES_KM,
            "motion": tuple(MOTION_VELOCITIES),
            "track_update_s": TRACK_UPDATES_S,
            "runs": RUN_COUNTS,
            "variation": VARIATIONS,
            "telemetry": TELEMETRY_LEVELS,
        }[name]
        self.flight_config = replace(
            cfg, **{name: cycle_value(values, getattr(cfg, name), delta)})
        self.app.audio.ui_click()

    def _start_flight_batch(self) -> bool:
        if self._flight_future is not None and not self._flight_future.done():
            self._show_status("MISSILE BATCH ALREADY RUNNING", danger=True)
            return False
        self._flight_cancel.clear()
        self.flight_progress = (0, self.flight_config.runs)
        self.flight_error = None
        root = getattr(self.app, "testing_flight_dir", "testing_flights")

        def progress(done, total):
            self.flight_progress = (done, total)

        self._flight_future = self._flight_executor.submit(
            run_batch, self.flight_config, root, progress,
            self._flight_cancel.is_set)
        self._show_status(
            f"RUNNING {self.flight_config.runs} PRODUCTION LAUNCHES",
            seconds=3600.0)
        self.app.audio.ui_click()
        return True

    def _poll_flight_batch(self) -> None:
        future = self._flight_future
        if future is None or not future.done():
            return
        self._flight_future = None
        try:
            self.flight_batch = future.result()
            self.selected_flight_run = self.flight_batch.ranked_indices[0]
            self.flight_run_scroll = 0
            count = len(self.flight_batch.results)
            self._show_status(
                f"{count} RUNS COMPLETE // {self.flight_batch.output_dir}",
                seconds=8.0)
        except Exception as exc:
            self.flight_error = f"{type(exc).__name__}: {exc}"
            self._show_status(f"BATCH FAILED: {self.flight_error}",
                              danger=True, seconds=8.0)

    def _flight_lab_event(self, ev) -> None:
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                self.app.close_testing_lab()
            elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_g):
                self._start_flight_batch()
            return
        if ev.type == pygame.MOUSEWHEEL:
            pos = self._wheel_pointer(ev)
            if _inside(pos, self._flight_results_box) and self.flight_batch:
                maximum = max(0, len(self.flight_batch.results) - 1)
                self.flight_run_scroll = max(
                    0, min(maximum, self.flight_run_scroll - int(ev.y)))
            return
        if ev.type != pygame.MOUSEBUTTONDOWN or ev.button not in (1, 3):
            return
        pos = getattr(ev, "pos", self._last_mouse)
        if _inside(pos, self._tab_asset_rect):
            self._set_lab_mode("assets")
            return
        if _inside(pos, self._tab_cinema_rect):
            self._set_lab_mode("cinematic")
            return
        if ev.button == 1:
            for index, rect in self._flight_result_rects:
                if _inside(pos, rect):
                    self.selected_flight_run = index
                    self.app.audio.ui_click()
                    return
        delta = -1 if ev.button == 3 else 1
        for name, rect in self._flight_control_rects.items():
            if _inside(pos, rect):
                self._cycle_flight_setting(name, delta)
                return
        if _inside(pos, self._flight_run_rect):
            self._start_flight_batch()

    # ------------------------------------------------------- cinematic tab

    def _cinema_meta(self, scene_dir: str) -> dict:
        """scene.json facts for the postcard (cached; {} on any error)."""
        meta = self._cinema_meta_cache.get(scene_dir)
        if meta is None:
            import json
            try:
                with open(os.path.join(scene_dir, "scene.json"),
                          encoding="utf-8") as f:
                    meta = json.load(f)
            except (OSError, ValueError):
                meta = {}
            self._cinema_meta_cache[scene_dir] = meta
        return meta

    def _launch_cinematic(self) -> None:
        if not self.cinema_scenes:
            self._show_status("NO BAKED SCENES - RUN "
                              "tools/bake_cinematic_map.py", danger=True)
            return
        self.cinema_sel = min(self.cinema_sel, len(self.cinema_scenes) - 1)
        _, _, _, scene_dir = self.cinema_scenes[self.cinema_sel]
        if not self._cinema_meta(scene_dir):
            # A corrupt/missing manifest must fail HERE with a status line,
            # not crash the state machine halfway through enter().
            self._show_status("SCENE MANIFEST UNREADABLE - REBAKE IT",
                              danger=True)
            return
        self.app.audio.ui_click()
        self.app.open_cinematic(scene_dir)

    def _cinematic_lab_event(self, ev) -> None:
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                self.app.close_testing_lab()
            elif ev.key == pygame.K_UP and self.cinema_scenes:
                self.cinema_sel = (self.cinema_sel - 1) % len(
                    self.cinema_scenes)
            elif ev.key == pygame.K_DOWN and self.cinema_scenes:
                self.cinema_sel = (self.cinema_sel + 1) % len(
                    self.cinema_scenes)
            elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_g):
                self._launch_cinematic()
            return
        if ev.type != pygame.MOUSEBUTTONDOWN or ev.button != 1:
            return
        pos = getattr(ev, "pos", self._last_mouse)
        if _inside(pos, self._tab_asset_rect):
            self._set_lab_mode("assets")
            return
        if _inside(pos, self._tab_flight_rect):
            self._set_lab_mode("flight")
            return
        for index, rect in self._cinema_row_rects:
            if _inside(pos, rect):
                already = index == self.cinema_sel
                self.cinema_sel = index
                if already:
                    self._launch_cinematic()
                else:
                    self.app.audio.ui_click()
                return
        if _inside(pos, self._cinema_enter_rect):
            self._launch_cinematic()

    # ---------------------------------------------------------------- input

    def handle_event(self, ev) -> None:
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_F6:
            # From assets AND cinematic, F6 goes to the missile lab (the
            # cinematic tab's button is labelled MISSILE [F6]).
            self._set_lab_mode(
                "assets" if self.lab_mode == "flight" else "flight")
            return
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_F7:
            self._set_lab_mode(
                "cinematic" if self.lab_mode != "cinematic" else "assets")
            return
        if self.lab_mode == "cinematic":
            self._cinematic_lab_event(ev)
            return
        if self.lab_mode == "flight":
            self._flight_lab_event(ev)
            return
        if (ev.type == pygame.KEYDOWN and ev.key == pygame.K_F3
                and self.feedback is None):
            self.open_feedback()
            return
        if self.feedback is not None:
            if not self.feedback["armed"]:
                self._feedback_event(ev)
            return
        if self.angle_entry_active and ev.type == pygame.KEYDOWN:
            self._angle_entry_event(ev)
            return
        if self.search_active and ev.type == pygame.KEYDOWN:
            self._search_event(ev)
            return
        if self.search_active and ev.type == pygame.MOUSEBUTTONDOWN:
            pos = getattr(ev, "pos", self._last_mouse)
            if not _inside(pos, self._search_rect):
                # Clicking a result/category/preview commits the query and
                # continues through normal pointer dispatch in the same event.
                self.search_active = False

        if ev.type == pygame.KEYDOWN:
            key = ev.key
            if key == pygame.K_ESCAPE:
                self.app.close_testing_lab()
            elif key == pygame.K_F2:
                self._request_clean_capture()
            elif key == pygame.K_TAB:
                self.ui_hidden = not self.ui_hidden
            elif key == pygame.K_SLASH:
                self.search_active = True
            elif key == pygame.K_BACKSPACE and self.query:
                self.query = ""
                self.selected = self.scroll = 0
            elif key == pygame.K_UP:
                self._move_selection(-1)
            elif key == pygame.K_DOWN:
                self._move_selection(1)
            elif key == pygame.K_LEFT:
                self._change_category(-1)
            elif key == pygame.K_RIGHT:
                self._change_category(1)
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_g):
                self._activate_selected()
            elif key == pygame.K_SPACE:
                self.auto_orbit = not self.auto_orbit
            elif key in (pygame.K_r, pygame.K_0, pygame.K_KP0):
                self.reset_camera()
            elif pygame.K_1 <= key <= pygame.K_7:
                self.snap_view(key - pygame.K_0)
            elif pygame.K_KP1 <= key <= pygame.K_KP7:
                self.snap_view(key - pygame.K_KP0)
            elif key == pygame.K_e:
                self._start_angle_entry()
            elif key == pygame.K_a:
                self._orbit(-12.0, 0.0)
            elif key == pygame.K_d:
                self._orbit(12.0, 0.0)
            elif key == pygame.K_w:
                self._orbit(0.0, -8.0)
            elif key == pygame.K_s:
                self._orbit(0.0, 8.0)
            elif key == pygame.K_n:
                delta = -1 if getattr(ev, "mod", 0) & pygame.KMOD_SHIFT else 1
                self.seed = max(0, self.seed + delta)
                self._show_status(f"SEED {self.seed} - PRESS GENERATE")
            elif key == pygame.K_q:
                i = WEATHER_QUALITIES.index(self.weather_quality)
                self.weather_quality = WEATHER_QUALITIES[(i + 1) % len(
                    WEATHER_QUALITIES)]
                self._show_status(
                    f"QUALITY {self.weather_quality.upper()} - PRESS GENERATE")
            elif key == pygame.K_t and self.loaded_asset is not None \
                    and self.loaded_asset.kind == "weather":
                self.weather_paused = not self.weather_paused
                self._show_status(
                    "WEATHER PAUSED" if self.weather_paused else "WEATHER PLAYING")
        elif ev.type == pygame.MOUSEMOTION:
            self._last_mouse = ev.pos
            if self._drag_button is not None:
                rel = getattr(ev, "rel", (0, 0))
                self._orbit(rel[0], rel[1])
            elif not self.ui_hidden:
                for index, rect in self._row_rects:
                    if _inside(ev.pos, rect):
                        self.selected = index
                        break
        elif ev.type == pygame.MOUSEBUTTONDOWN:
            self._mouse_down(ev)
        elif ev.type == pygame.MOUSEBUTTONUP:
            if ev.button == self._drag_button:
                self._drag_button = None
        elif ev.type == pygame.MOUSEWHEEL:
            pos = self._wheel_pointer(ev)
            steps = -ev.y if getattr(ev, "flipped", False) else ev.y
            self._handle_wheel(steps, pos)

    def _wheel_pointer(self, ev) -> tuple[int, int]:
        """Use pygame-ce's wheel coordinates, then the live cursor, then cache."""
        mx = getattr(ev, "mouse_x", None)
        my = getattr(ev, "mouse_y", None)
        if mx is not None and my is not None:
            return int(mx), int(my)
        if pygame.display.get_init():
            try:
                return tuple(int(v) for v in pygame.mouse.get_pos())
            except pygame.error:
                pass
        return self._last_mouse

    def _handle_wheel(self, steps: float, pos) -> None:
        self._last_mouse = pos
        if not steps:
            return
        over_sidebar = (not self.ui_hidden and
                        (_inside(pos, self._sidebar_box)
                         or (self._sidebar_box is None
                             and pos[0] <= SIDEBAR_W + SCREEN_PAD)))
        if over_sidebar:
            self._scroll_selection(-int(math.copysign(
                max(1, round(abs(steps) * 3)), steps)))
        elif _inside(pos, self._preview_box):
            self._zoom(steps)

    def _mouse_down(self, ev) -> None:
        pos = getattr(ev, "pos", self._last_mouse)
        if ev.button in (4, 5):
            self._handle_wheel(1 if ev.button == 4 else -1, pos)
            return
        if ev.button not in (1, 3):
            return
        if not self.ui_hidden and ev.button == 1 \
                and _inside(pos, self._tab_flight_rect):
            self._set_lab_mode("flight")
            return
        if not self.ui_hidden and ev.button == 1 \
                and _inside(pos, self._tab_cinema_rect):
            self._set_lab_mode("cinematic")
            return
        if not self.ui_hidden and ev.button == 1:
            if _inside(pos, self._category_prev_rect):
                self._change_category(-1)
                return
            if _inside(pos, self._category_next_rect):
                self._change_category(1)
                return
            if _inside(pos, self._search_clear_rect):
                self.query = ""
                self.search_active = False
                self.selected = self.scroll = 0
                self.app.audio.ui_click()
                return
            if _inside(pos, self._search_rect):
                self.search_active = True
                return
            if _inside(pos, self._generate_rect):
                self._activate_selected()
                return
            for index, rect in self._row_rects:
                if _inside(pos, rect):
                    self.selected = index
                    self._activate_selected()
                    return
        if _inside(pos, self._preview_box):
            self._drag_button = ev.button
            self._last_mouse = pos

    def _search_event(self, ev) -> None:
        if ev.type != pygame.KEYDOWN:
            return
        if ev.key == pygame.K_ESCAPE:
            self.search_active = False
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self.search_active = False
        elif ev.key == pygame.K_BACKSPACE:
            self.query = self.query[:-1]
            self.selected = self.scroll = 0
        else:
            ch = getattr(ev, "unicode", "")
            if ch and ch.isprintable() and len(self.query) < 48:
                self.query += ch
                self.selected = self.scroll = 0

    # ------------------------------------------------------------- feedback

    def open_feedback(self) -> None:
        if self.loaded_asset is None:
            self._show_status("GENERATE AN ASSET BEFORE FILING FEEDBACK",
                              danger=True)
            return
        base = getattr(self.app, "testing_feedback_dir", "testing_feedback")
        base = base or "testing_feedback"
        os.makedirs(base, exist_ok=True)
        shot = os.path.join(base, "_pending_lab_shot.png")
        self.app.bug_shot_path = shot
        self.feedback = {
            "note": "", "type_index": 0, "shot": shot, "armed": True,
        }
        self.app.audio.ui_click()

    def _feedback_event(self, ev) -> None:
        if ev.type != pygame.KEYDOWN:
            return
        if ev.key == pygame.K_ESCAPE:
            self._cancel_feedback()
        elif ev.key == pygame.K_TAB:
            delta = -1 if getattr(ev, "mod", 0) & pygame.KMOD_SHIFT else 1
            self.feedback["type_index"] = (
                self.feedback["type_index"] + delta) % len(FEEDBACK_TYPES)
            self.app.audio.ui_click()
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._file_feedback()
        elif ev.key == pygame.K_BACKSPACE:
            if getattr(ev, "mod", 0) & pygame.KMOD_CTRL:
                note = self.feedback["note"].rstrip()
                self.feedback["note"] = (
                    note.rsplit(" ", 1)[0] if " " in note else "")
            else:
                self.feedback["note"] = self.feedback["note"][:-1]
        else:
            ch = getattr(ev, "unicode", "")
            if ch and ch.isprintable() and len(self.feedback["note"]) < 2_000:
                self.feedback["note"] += ch

    def _cancel_feedback(self, show_status: bool = True) -> None:
        ui = self.feedback
        if ui is None:
            return
        if getattr(self.app, "bug_shot_path", None) == ui["shot"]:
            self.app.bug_shot_path = None
        try:
            if os.path.exists(ui["shot"]):
                os.remove(ui["shot"])
        except OSError:
            pass
        self.feedback = None
        if show_status:
            self._show_status("FEEDBACK CANCELLED")

    def _file_feedback(self) -> None:
        ui = self.feedback
        asset = self.loaded_asset
        if ui is None or asset is None:
            return
        from game.blackbox import git_commit

        details = {
            "builder": asset.builder_ref,
            "builder_kwargs": asset.kwargs,
            "proxy_for": asset.proxy_for,
            "tags": asset.tags,
            "backend": self.backend,
        }
        if asset.kind == "weather":
            details.update({
                "weather_quality": self.loaded_weather_quality,
                "requested_weather_quality": self.weather_quality,
                "requested_seed": self.seed,
                "weather_time_s": self.cloud_time,
                "weather_paused": self.weather_paused,
            })
        else:
            details.update({"scale": 1.0, "forward_axis": "+Z",
                            "up_axis": "+Y"})
        context = {
            "asset": asset,
            "seed": self.loaded_seed,
            "camera": {
                "eye": self.camera.eye,
                "forward": self.camera.forward,
                "target": self.target,
                "azimuth_deg": math.degrees(self.orbit_az),
                "elevation_deg": math.degrees(self.orbit_el),
                "distance_m": self.orbit_dist,
            },
            "mesh_stats": self.mesh_stats,
            "note": ui["note"],
            "type": FEEDBACK_TYPES[ui["type_index"]],
            "screenshot_name": "screenshot.png",
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "commit": git_commit(),
            "details": details,
        }
        base = getattr(self.app, "testing_feedback_dir", "testing_feedback")
        base = base or "testing_feedback"
        try:
            report = write_testing_feedback(base, context)
            folder = os.path.dirname(report)
            if os.path.exists(ui["shot"]):
                os.replace(ui["shot"], os.path.join(folder, "screenshot.png"))
            self.last_report_path = os.path.abspath(report)
            self.feedback = None
            self._show_status(f"FEEDBACK FILED: {os.path.basename(folder)}",
                              seconds=5.0)
            self.app.audio.ui_click()
        except Exception as exc:
            self._show_status(f"FEEDBACK FAILED: {exc}", danger=True,
                              seconds=6.0)

    # ---------------------------------------------------------------- render

    def render(self, dt_real: float) -> None:
        if self._gl is None:
            return
        self._poll_flight_batch()
        self._finish_clean_capture_if_ready()
        dt = _clamp(dt_real, 0.0, 0.05)
        if self.status_left > 0.0:
            self.status_left = max(0.0, self.status_left - dt_real)
        if self.auto_orbit and self.feedback is None:
            self.orbit_az = (self.orbit_az + dt * 0.32) % (2.0 * math.pi)
            self._apply_camera()

        self._apply_camera()
        self._advance_weather(dt)
        w, h = self.window.size()
        px = min(w - 1, SIDEBAR_W + SCREEN_PAD * 2)
        py = PREVIEW_TOP
        pw = max(1, w - px - SCREEN_PAD)
        ph = max(1, h - py - PREVIEW_BOTTOM)
        self._preview_box = (px, py, px + pw, py + ph)

        gl = self._gl
        gl.glDisable(gl.GL_SCISSOR_TEST)
        gl.glViewport(0, 0, w, h)
        gl.glClearColor(*BG0, 1.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)

        # GL's origin is bottom-left; UI rectangles use top-left coordinates.
        gy = h - (py + ph)
        gl.glEnable(gl.GL_SCISSOR_TEST)
        gl.glScissor(px, gy, pw, ph)
        gl.glViewport(px, gy, pw, ph)
        self.renderer.begin(self.camera, pw / max(ph, 1))
        self._bind_cloud_shadows()
        self.sky.draw(self.renderer)
        if self.lab_mode == "assets" and self.model_mesh is not None:
            if self.chamber_mesh is not None and self.orbit_el > math.radians(-8):
                self.renderer.draw_mesh(self.chamber_mesh, np.zeros(3))
            self.renderer.draw_mesh(self.model_mesh, self.model_pos)
        if self.lab_mode == "assets" and self.clouds is not None:
            if hasattr(self.clouds, "using_v2"):
                self.clouds.draw(self.renderer, self.camera, self.cloud_time,
                                 view_id="testing-lab")
            else:
                self.clouds.draw(self.renderer, self.camera, self.cloud_time)
        if (self.lab_mode == "assets" and self.weather_overlay is not None
                and self._weather_frame is not None):
            self.weather_overlay.draw(
                self._weather_frame, self.cloud_time,
                self.weather_fx.overlay_seed)
        if (self.lab_mode == "assets" and self.effect_driver is not None
                and self.effect_fx is not None):
            if not self.weather_paused:      # T pauses effects too
                self.effect_driver.step(self.effect_fx, dt)
                self.effect_fx.update(dt)
            self._particle_renderer.draw(self.renderer, self.effect_fx)

        gl.glDisable(gl.GL_SCISSOR_TEST)
        gl.glViewport(0, 0, w, h)
        drew_text = False
        if not self.ui_hidden:
            self._draw_ui(w, h)
            drew_text = True
        if self.feedback is not None and not self.feedback["armed"]:
            self._draw_feedback_overlay(w, h)
            drew_text = True
        if drew_text:
            self.text.flush(w, h)
        if self.feedback is not None:
            # The App captures this first, clean frame after render and before
            # swap.  The paper overlay begins on the following frame.
            self.feedback["armed"] = False

    def _advance_weather(self, dt: float) -> None:
        if self.weather_fx is None:
            self._weather_frame = None
            return
        if not self.weather_paused:
            self.cloud_time += dt
            update = self.weather_fx.advance(dt, self.camera.eye)
            self._weather_frame = update.frame
            for cue in update.thunder:
                if cue.gain > 0.01:
                    self.app.audio.play("boom_far", gain=cue.gain)
        else:
            self._weather_frame = self.weather_fx.sample(self.camera.eye)

    def _bind_cloud_shadows(self) -> None:
        if self.clouds is not None and getattr(self.clouds, "enabled", False):
            self.clouds.bind_shadow_uniforms(
                self.renderer.lit, 6, self.camera, self.cloud_time)
            return
        self.renderer.lit.use()
        self.renderer.lit.set_float("u_cloud_amt", 0.0)

    # ------------------------------------------------------------------- UI

    def _draw_ui(self, w: int, h: int) -> None:
        if self.lab_mode == "flight":
            self._draw_flight_lab_ui(w, h)
            return
        if self.lab_mode == "cinematic":
            self._draw_cinematic_ui(w, h)
            return
        text = self.text
        panel_h = max(1, h - SCREEN_PAD * 2)
        self._sidebar_box = (SCREEN_PAD, SCREEN_PAD,
                             SCREEN_PAD + SIDEBAR_W, SCREEN_PAD + panel_h)
        draw_panel(text, SCREEN_PAD, SCREEN_PAD, SIDEBAR_W, panel_h,
                   fill=PLATE_INK, strip=True)
        x = SCREEN_PAD + 16
        text.draw_text(x, 27, "TEST LAB // INTERNAL", ACCENT, SMALL_SIZE)
        text.draw_text(x, 49, "ASSET INSPECTOR", TEXT_COL, HEADER_SIZE)
        self._tab_flight_rect = (x + 206, 24, x + 338, 48)
        text.draw_lines(
            [(x + 206, 24), (x + 338, 24), (x + 338, 48),
             (x + 206, 48), (x + 206, 24)], (*ACCENT_DIM, 1.0), 1.0)
        text.draw_text(x + 216, 29, "MISSILE LAB [F6]", MUTED, SMALL_SIZE)
        self._tab_cinema_rect = (x + 206, 52, x + 338, 76)
        text.draw_lines(
            [(x + 206, 52), (x + 338, 52), (x + 338, 76),
             (x + 206, 76), (x + 206, 52)], (*ACCENT_DIM, 1.0), 1.0)
        text.draw_text(x + 216, 57, "CINEMATIC [F7]", MUTED, SMALL_SIZE)

        y = 91
        self._category_prev_rect = (x, y, x + 32, y + 26)
        self._category_next_rect = (x + SIDEBAR_W - 64, y,
                                    x + SIDEBAR_W - 32, y + 26)
        text.draw_text(x + 9, y + 3, "<", ACCENT)
        text.draw_text(x + SIDEBAR_W - 54, y + 3, ">", ACCENT)
        cat = self.category
        cw = text.text_width(cat, SMALL_SIZE)
        text.draw_text(x + (SIDEBAR_W - 32 - cw) * 0.5, y + 5,
                       cat, TEXT_COL, SMALL_SIZE)

        sy = 124
        self._search_rect = (x, sy, x + SIDEBAR_W - 32, sy + 30)
        text.draw_rect(x, sy, SIDEBAR_W - 32, 30, (*BG0, 0.92))
        text.draw_lines([(x, sy), (x + SIDEBAR_W - 32, sy),
                         (x + SIDEBAR_W - 32, sy + 30), (x, sy + 30),
                         (x, sy)],
                        (*(ACCENT if self.search_active else LINE_COL), 1.0),
                        1.0)
        query = self.query + ("_" if self.search_active else "")
        self._search_clear_rect = ((x + SIDEBAR_W - 58, sy,
                                    x + SIDEBAR_W - 32, sy + 30)
                                   if self.query else None)
        search_label = f"/ {query or 'SEARCH MODELS'}"
        search_width = SIDEBAR_W - (72 if self.query else 50)
        text.draw_text(x + 9, sy + 6,
                       self._ellipsize(search_label, search_width, SMALL_SIZE),
                       TEXT_COL if query else FAINT, SMALL_SIZE)
        if self.query:
            text.draw_text(x + SIDEBAR_W - 51, sy + 6, "X",
                           ACCENT, SMALL_SIZE)

        list_top = 164
        list_bottom = max(list_top + LIST_ROW_H, h - 242)
        capacity = max(1, int((list_bottom - list_top) // LIST_ROW_H))
        self._list_capacity = capacity
        assets = self.visible_assets()
        if assets:
            self.selected = min(self.selected, len(assets) - 1)
            if self.selected < self.scroll:
                self.scroll = self.selected
            elif self.selected >= self.scroll + capacity:
                self.scroll = self.selected - capacity + 1
            self.scroll = min(self.scroll, max(0, len(assets) - capacity))
        else:
            self.selected = self.scroll = 0
        self._row_rects = []
        for slot, index in enumerate(range(
                self.scroll, min(len(assets), self.scroll + capacity))):
            asset = assets[index]
            ry = list_top + slot * LIST_ROW_H
            rect = (x, ry, x + SIDEBAR_W - 32, ry + LIST_ROW_H)
            self._row_rects.append((index, rect))
            focused = index == self.selected
            if focused:
                text.draw_rect(x, ry, SIDEBAR_W - 32, LIST_ROW_H,
                               (*BG2, 1.0))
                text.draw_rect(x, ry, 3, LIST_ROW_H, (*ACCENT, 1.0))
            loaded = self.loaded_asset is not None \
                and self.loaded_asset.id == asset.id
            prefix = "* " if loaded else "  "
            label = self._ellipsize(prefix + asset.label, SIDEBAR_W - 58,
                                    SMALL_SIZE)
            col = ACCENT if focused else OK_COL if loaded else MUTED
            text.draw_text(x + 9, ry + 6, label, col, SMALL_SIZE)
        if not assets:
            text.draw_text(x + 9, list_top + 8, "NO MATCHING ASSETS",
                           DANGER, SMALL_SIZE)

        button_y = h - 224
        self._generate_rect = (x, button_y, x + SIDEBAR_W - 32,
                               button_y + 36)
        selected = self.selected_asset()
        button_col = ACCENT if selected is not None else DISABLED
        text.draw_rect(x, button_y, SIDEBAR_W - 32, 36, (*BG2, 1.0))
        text.draw_lines([(x, button_y), (x + SIDEBAR_W - 32, button_y),
                         (x + SIDEBAR_W - 32, button_y + 36),
                         (x, button_y + 36), (x, button_y)],
                        (*button_col, 1.0), 1.0)
        label = "GENERATE [G / ENTER]"
        lw = text.text_width(label, SMALL_SIZE)
        text.draw_text(x + (SIDEBAR_W - 32 - lw) * 0.5, button_y + 8,
                       label, button_col, SMALL_SIZE)

        info_y = button_y + 48
        if selected is not None:
            text.draw_text(x, info_y, f"ID  {selected.id}", FAINT, SMALL_SIZE)
            proxy = (f"PROXY FOR {selected.proxy_for.upper()}"
                     if selected.proxy_for else selected.kind.upper())
            text.draw_text(x, info_y + 20, proxy,
                           DANGER if selected.proxy_for else BELIEF, SMALL_SIZE)
            tags = " / ".join(selected.tags[:3]).upper()
            text.draw_text(x, info_y + 40,
                           self._ellipsize(tags, SIDEBAR_W - 32, SMALL_SIZE),
                           MUTED, SMALL_SIZE)
            text.draw_text(x, info_y + 65,
                           "1 FRONT  2 SIDE  3 REAR  4 TOP  5 BOTTOM",
                           FAINT, SMALL_SIZE)
            text.draw_text(x, info_y + 85,
                           "6 HIGH45  7 HIGH70  E EXACT AZ,EL",
                           FAINT, SMALL_SIZE)
            text.draw_text(x, info_y + 105,
                           "N SEED  Q QUALITY  T WEATHER PAUSE",
                           FAINT, SMALL_SIZE)

        self._draw_preview_info(w, h)
        px0, py0, px1, py1 = self._preview_box
        text.draw_lines([(px0, py0), (px1, py0), (px1, py1),
                         (px0, py1), (px0, py0)], (*ACCENT_DIM, 1.0), 1.0)
        footer = ("DRAG ORBIT  WHEEL ZOOM  E EXACT VIEW  F2 CLEAN SHOT  "
                  "/ SEARCH  F3 FEEDBACK  TAB CLEAN  ESC MENU")
        text.draw_rect(px0, h - 43, px1 - px0, 27, (*PLATE_INK, 0.94))
        text.draw_text(px0 + 10, h - 38,
                       self._ellipsize(footer, px1 - px0 - 20, SMALL_SIZE),
                       ACCENT_DIM, SMALL_SIZE)

    def _draw_cinematic_ui(self, w: int, h: int) -> None:
        """The CINEMATIC tab: a location gallery over the dusk sky.
        Sidebar lists baked scenes; the preview side is a minimal
        'postcard' plate for the selected one (ui_reference §2.1 idiom:
        plates + 1px rules, no glow)."""
        text = self.text
        panel_h = max(1, h - SCREEN_PAD * 2)
        self._sidebar_box = (SCREEN_PAD, SCREEN_PAD,
                             SCREEN_PAD + SIDEBAR_W, SCREEN_PAD + panel_h)
        draw_panel(text, SCREEN_PAD, SCREEN_PAD, SIDEBAR_W, panel_h,
                   fill=PLATE_INK, strip=True)
        x = SCREEN_PAD + 16
        text.draw_text(x, 27, "TEST LAB // INTERNAL", ACCENT, SMALL_SIZE)
        text.draw_text(x, 49, "CINEMATIC", TEXT_COL, HEADER_SIZE)
        self._tab_asset_rect = (x + 206, 24, x + 338, 48)
        text.draw_lines(
            [(x + 206, 24), (x + 338, 24), (x + 338, 48),
             (x + 206, 48), (x + 206, 24)], (*ACCENT_DIM, 1.0), 1.0)
        text.draw_text(x + 216, 29, "ASSETS [F7]", MUTED, SMALL_SIZE)
        self._tab_flight_rect = (x + 206, 52, x + 338, 76)
        text.draw_lines(
            [(x + 206, 52), (x + 338, 52), (x + 338, 76),
             (x + 206, 76), (x + 206, 52)], (*ACCENT_DIM, 1.0), 1.0)
        text.draw_text(x + 216, 57, "MISSILE [F6]", MUTED, SMALL_SIZE)

        text.draw_text(x, 95, "REAL PLACES, 1:1 - WALK THE GROUND AND",
                       MUTED, SMALL_SIZE)
        text.draw_text(x, 113, "WATCH A LIVE S-300 SHOT FROM WHERE YOU STAND",
                       MUTED, SMALL_SIZE)

        row_h = 54
        list_top = 150
        self._cinema_row_rects = []
        if not self.cinema_scenes:
            text.draw_text(x, list_top + 8, "NO BAKED SCENES ON DISK",
                           DANGER, SMALL_SIZE)
            text.draw_text(x, list_top + 30,
                           "RUN tools/fetch_cinematic_data.py THEN",
                           FAINT, SMALL_SIZE)
            text.draw_text(x, list_top + 48,
                           "tools/bake_cinematic_map.py", FAINT, SMALL_SIZE)
        for i, (name, title, subtitle, _d) in enumerate(self.cinema_scenes):
            ry = list_top + i * row_h
            rect = (x, ry, x + SIDEBAR_W - 32, ry + row_h - 6)
            self._cinema_row_rects.append((i, rect))
            focused = i == self.cinema_sel
            if focused:
                text.draw_rect(x, ry, SIDEBAR_W - 32, row_h - 6, (*BG2, 1.0))
                text.draw_rect(x, ry, 3, row_h - 6, (*ACCENT, 1.0))
            text.draw_text(x + 12, ry + 7, title,
                           ACCENT if focused else TEXT_COL, BODY_SIZE)
            text.draw_text(x + 12, ry + 29,
                           self._ellipsize(subtitle, SIDEBAR_W - 56,
                                           SMALL_SIZE),
                           MUTED if focused else FAINT, SMALL_SIZE)

        button_y = h - 224
        self._cinema_enter_rect = (x, button_y, x + SIDEBAR_W - 32,
                                   button_y + 36)
        col = ACCENT if self.cinema_scenes else DISABLED
        text.draw_rect(x, button_y, SIDEBAR_W - 32, 36, (*BG2, 1.0))
        text.draw_lines([(x, button_y), (x + SIDEBAR_W - 32, button_y),
                         (x + SIDEBAR_W - 32, button_y + 36),
                         (x, button_y + 36), (x, button_y)], (*col, 1.0),
                        1.0)
        label = "WALK HERE [G / ENTER]"
        lw = text.text_width(label, SMALL_SIZE)
        text.draw_text(x + (SIDEBAR_W - 32 - lw) * 0.5, button_y + 8,
                       label, col, SMALL_SIZE)
        info_y = button_y + 48
        text.draw_text(x, info_y, "WASD WALK  SHIFT RUN  SPACE JUMP",
                       FAINT, SMALL_SIZE)
        text.draw_text(x, info_y + 20, "L LAUNCH AGAIN  ESC RETURN",
                       FAINT, SMALL_SIZE)
        text.draw_text(x, info_y + 48, "SOURCES: SWISSTOPO / USGS OPEN DATA",
                       FAINT, SMALL_SIZE)
        text.draw_text(x, info_y + 66, "TERRAIN 0.5M LIDAR - ORTHO 10CM",
                       FAINT, SMALL_SIZE)

        # Postcard plate over the sky backdrop.
        px0, py0, px1, py1 = self._preview_box
        if self.cinema_scenes:
            _n, title, subtitle, sdir = self.cinema_scenes[self.cinema_sel]
            meta = self._cinema_meta(sdir)
            pw = min(560, px1 - px0 - 80)
            ph = 190
            cx = (px0 + px1) // 2
            cy = (py0 + py1) // 2
            bx = cx - pw // 2
            by = cy - ph // 2
            draw_panel(text, bx, by, pw, ph, fill=PLATE_INK, strip=True)
            text.draw_text(bx + 24, by + 22, title, TEXT_COL, HEADER_SIZE,
                           scale=1.6)
            text.draw_text(bx + 24, by + 66, subtitle, ACCENT, SMALL_SIZE)
            text.draw_lines([(bx + 24, by + 96), (bx + pw - 24, by + 96)],
                            (*LINE_COL, 1.0), 1.0)
            if meta:
                km_x = (meta["x1"] - meta["x0"]) / 1000.0
                km_z = (meta["z1"] - meta["z0"]) / 1000.0
                facts = (f"AREA {km_x:g} X {km_z:g} KM   "
                         f"BASE ALT {meta['origin_alt']:.0f} M ASL")
            else:
                facts = "OPEN-DATA LIDAR TERRAIN"
            text.draw_text(bx + 24, by + 110, facts, MUTED, SMALL_SIZE)
            text.draw_text(bx + 24, by + 132,
                           "LIDAR GROUND TRUTH   S-300 BATTERY ON SITE",
                           MUTED, SMALL_SIZE)
            text.draw_text(bx + 24, by + 154,
                           "SOUND ARRIVES AT 343 M/S - COUNT THE SECONDS",
                           FAINT, SMALL_SIZE)
        text.draw_lines([(px0, py0), (px1, py0), (px1, py1),
                         (px0, py1), (px0, py0)], (*ACCENT_DIM, 1.0), 1.0)
        footer = ("UP/DOWN SELECT  ENTER WALK  F7 ASSETS  F6 MISSILE LAB  "
                  "ESC MENU")
        text.draw_rect(px0, h - 43, px1 - px0, 27, (*PLATE_INK, 0.94))
        text.draw_text(px0 + 10, h - 38,
                       self._ellipsize(footer, px1 - px0 - 20, SMALL_SIZE),
                       ACCENT_DIM, SMALL_SIZE)

    def _draw_flight_lab_ui(self, w: int, h: int) -> None:
        text = self.text
        px0, py0, px1, py1 = self._preview_box
        # The analysis surface is intentionally neutral: trajectories should
        # read like black-box plots, not inherit the 3-D sky backdrop.
        text.draw_rect(px0, py0, px1 - px0, py1 - py0,
                       (0.0, 0.0, 0.0, 1.0))
        panel_h = max(1, h - SCREEN_PAD * 2)
        self._sidebar_box = (SCREEN_PAD, SCREEN_PAD,
                             SCREEN_PAD + SIDEBAR_W, SCREEN_PAD + panel_h)
        draw_panel(text, SCREEN_PAD, SCREEN_PAD, SIDEBAR_W, panel_h,
                   fill=PLATE_INK, strip=True)
        x = SCREEN_PAD + 16
        text.draw_text(x, 27, "TEST LAB // INTERNAL", ACCENT, SMALL_SIZE)
        text.draw_text(x, 49, "MISSILE FLIGHT LAB", TEXT_COL, HEADER_SIZE)
        self._tab_asset_rect = (x + 238, 24, x + 338, 48)
        text.draw_lines(
            [(x + 238, 24), (x + 338, 24), (x + 338, 48),
             (x + 238, 48), (x + 238, 24)], (*ACCENT_DIM, 1.0), 1.0)
        text.draw_text(x + 249, 29, "ASSETS [F6]", MUTED, SMALL_SIZE)
        self._tab_cinema_rect = (x + 238, 52, x + 338, 76)
        text.draw_lines(
            [(x + 238, 52), (x + 338, 52), (x + 338, 76),
             (x + 238, 76), (x + 238, 52)], (*ACCENT_DIM, 1.0), 1.0)
        text.draw_text(x + 249, 57, "CINEMA [F7]", MUTED, SMALL_SIZE)

        cfg = self.flight_config
        rows = (
            ("weapon", "PLATFORM / ROUND", WEAPON_LABELS[cfg.weapon]),
            ("range_km", "TARGET RANGE", f"{cfg.range_km:g} KM"),
            ("altitude_km", "TARGET ALT", f"{cfg.altitude_km:g} KM"),
            ("motion", "TARGET MOTION", cfg.motion.upper()),
            ("track_update_s", "TRACK REFRESH", f"{cfg.track_update_s:g} S"),
            ("runs", "BATCH SIZE", str(cfg.runs)),
            ("variation", "CASE SPREAD", f"{cfg.variation * 100:.0f}%"),
            ("telemetry", "TELEMETRY", cfg.telemetry.upper()),
        )
        self._flight_control_rects = {}
        y = 100
        for name, label, value in rows:
            text.draw_text(x, y, label, MUTED, SMALL_SIZE)
            rect = (x, y + 18, x + SIDEBAR_W - 32, y + 46)
            self._flight_control_rects[name] = rect
            text.draw_rect(rect[0], rect[1], rect[2] - rect[0],
                           rect[3] - rect[1], (*BG0, 0.92))
            text.draw_lines(
                [(rect[0], rect[1]), (rect[2], rect[1]),
                 (rect[2], rect[3]), (rect[0], rect[3]),
                 (rect[0], rect[1])], (*LINE_COL, 1.0), 1.0)
            text.draw_text(rect[0] + 9, rect[1] + 5, "<", ACCENT, SMALL_SIZE)
            value_w = text.text_width(value, SMALL_SIZE)
            text.draw_text(rect[0] + (rect[2] - rect[0] - value_w) * 0.5,
                           rect[1] + 5, value, TEXT_COL, SMALL_SIZE)
            text.draw_text(rect[2] - 20, rect[1] + 5, ">", ACCENT, SMALL_SIZE)
            y += 53

        self._flight_run_rect = (x, y + 4, x + SIDEBAR_W - 32, y + 44)
        running = self._flight_future is not None and not self._flight_future.done()
        run_col = BELIEF if running else ACCENT
        text.draw_rect(x, y + 4, SIDEBAR_W - 32, 40, (*BG2, 1.0))
        text.draw_lines(
            [(x, y + 4), (x + SIDEBAR_W - 32, y + 4),
             (x + SIDEBAR_W - 32, y + 44), (x, y + 44), (x, y + 4)],
            (*run_col, 1.0), 1.0)
        if running:
            done, total = self.flight_progress
            label = f"RUNNING {done}/{total}"
        else:
            label = "RUN BATCH [G / ENTER]"
        lw = text.text_width(label, SMALL_SIZE)
        text.draw_text(x + (SIDEBAR_W - 32 - lw) * 0.5, y + 14,
                       label, run_col, SMALL_SIZE)

        self._draw_flight_run_ledger(x, y + 56, h - 32)

        self._draw_flight_plots(w, h)
        text.draw_lines([(px0, py0), (px1, py0), (px1, py1),
                         (px0, py1), (px0, py0)], (*ACCENT_DIM, 1.0), 1.0)
        footer = ("LMB NEXT  RMB PREVIOUS  ENTER RUN  "
                  "OUTPUT: SUMMARY.JSON / RUNS.CSV / BLACKBOX.JSONL")
        text.draw_rect(px0, h - 43, px1 - px0, 27, (*PLATE_INK, 0.94))
        text.draw_text(px0 + 10, h - 38,
                       self._ellipsize(footer, px1 - px0 - 20, SMALL_SIZE),
                       ACCENT_DIM, SMALL_SIZE)

    def _draw_flight_run_ledger(self, x: float, top: float,
                                bottom: float) -> None:
        text = self.text
        width = SIDEBAR_W - 32
        text.draw_text(x, top,
                       "RUN RANK // HIT55 CLOSE20 SPD10 TIME10 ALT5",
                       FAINT, SMALL_SIZE)
        header_y = top + 22
        text.draw_text(x, header_y,
                       "RK SCORE RUN  H  TIME  SPD  APOGEE",
                       MUTED, SMALL_SIZE)
        rows_top = header_y + 22
        row_h = 25
        self._flight_results_box = (x, rows_top, x + width, bottom)
        self._flight_result_rects = []
        batch = self.flight_batch
        if batch is None:
            text.draw_text(x, rows_top + 6, "NO BATCH RESULTS", FAINT,
                           SMALL_SIZE)
            return
        capacity = max(1, int((bottom - rows_top) // row_h))
        maximum = max(0, len(batch.ranked_indices) - capacity)
        self.flight_run_scroll = min(maximum, self.flight_run_scroll)
        visible = batch.ranked_indices[
            self.flight_run_scroll:self.flight_run_scroll + capacity]
        for slot, index in enumerate(visible):
            row = batch.results[index]
            ry = rows_top + slot * row_h
            rect = (x, ry, x + width, ry + row_h)
            self._flight_result_rects.append((index, rect))
            selected = index == self.selected_flight_run
            if selected:
                text.draw_rect(x, ry, width, row_h, (0.08, 0.18, 0.31, 0.95))
                text.draw_rect(x, ry, 3, row_h, (1.0, 1.0, 1.0, 1.0))
            hit = "H" if row["hit"] else "M"
            label = (
                f"{int(row['performance_rank']):02d} "
                f"{float(row['performance_score']):5.1f} "
                f"#{int(row['run']):02d}  {hit} "
                f"{float(row['flight_time_s']):4.0f} "
                f"{float(row['impact_speed_mps']):4.0f} "
                f"{float(row['apogee_km']):5.1f}")
            color = ((1.0, 1.0, 1.0) if selected else
                     OK_COL if row["hit"] else DANGER)
            text.draw_text(x + 7, ry + 5,
                           self._ellipsize(label, width - 12, SMALL_SIZE),
                           color, SMALL_SIZE)

    def _draw_flight_plots(self, w: int, h: int) -> None:
        text = self.text
        px0, py0, px1, py1 = self._preview_box
        left, right = px0 + 66, px1 - 20
        top, bottom = py0 + 98, py1 - 42
        split = top + (bottom - top) * 0.62
        altitude_bottom = split - 24
        speed_top = split + 34
        text.draw_text(px0 + 16, py0 + 14,
                       "PRODUCTION 120 HZ BLACK-BOX TRAJECTORIES",
                       TEXT_COL, SMALL_SIZE)
        batch = self.flight_batch
        if batch is None:
            text.draw_text(left, top + 20,
                           "CONFIGURE A CASE AND RUN A BATCH",
                           FAINT, SMALL_SIZE)
            return

        trajectories = batch.trajectories
        range_limit = _nice_axis_ceiling(max(
            1.0,
            max(math.hypot(float(row["x_m"]), float(row["z_m"])) / 1000.0
                for trace in trajectories for row in trace)))
        altitude_limit = _nice_axis_ceiling(max(
            1.0, max(float(row["altitude_m"]) / 1000.0
                     for trace in trajectories for row in trace)))
        time_limit = _nice_axis_ceiling(max(
            1.0, max(float(row["t_s"])
                     for trace in trajectories for row in trace)))
        speed_limit = _nice_axis_ceiling(max(
            1.0, max(float(row["speed_mps"])
                     for trace in trajectories for row in trace)))
        grid_col = (0.24, 0.29, 0.31, 0.48)
        axis_col = (0.48, 0.55, 0.57, 0.90)
        text.draw_text(left, top - 24, "ALTITUDE (KM) / DOWNRANGE (KM)",
                       MUTED, SMALL_SIZE)
        text.draw_text(left, speed_top - 24, "SPEED (M/S) / TIME (S)",
                       MUTED, SMALL_SIZE)

        # Four exact intervals on both charts: horizontal labels are Y values,
        # baseline labels are X values.  Limits are rounded upward, never down.
        for tick in range(5):
            fraction = tick / 4.0
            ay = altitude_bottom - fraction * (altitude_bottom - top)
            ax = left + fraction * (right - left)
            sy = bottom - fraction * (bottom - speed_top)
            sx = ax
            text.draw_lines([(left, ay), (right, ay)], grid_col, 1.0)
            text.draw_lines([(ax, top), (ax, altitude_bottom)],
                            grid_col, 1.0)
            text.draw_lines([(left, sy), (right, sy)], grid_col, 1.0)
            text.draw_lines([(sx, speed_top), (sx, bottom)], grid_col, 1.0)
            alt_label = f"{altitude_limit * fraction:.0f}"
            speed_label = f"{speed_limit * fraction:.0f}"
            range_label = f"{range_limit * fraction:.0f}"
            time_label = f"{time_limit * fraction:.0f}"
            text.draw_text(left - text.text_width(alt_label, SMALL_SIZE) - 8,
                           ay - 7, alt_label, FAINT, SMALL_SIZE)
            text.draw_text(left - text.text_width(speed_label, SMALL_SIZE) - 8,
                           sy - 7, speed_label, FAINT, SMALL_SIZE)
            text.draw_text(
                ax - text.text_width(range_label, SMALL_SIZE) * 0.5,
                altitude_bottom + 5, range_label, FAINT, SMALL_SIZE)
            text.draw_text(
                sx - text.text_width(time_label, SMALL_SIZE) * 0.5,
                bottom + 5, time_label, FAINT, SMALL_SIZE)
        text.draw_lines([(left, top), (left, altitude_bottom),
                         (right, altitude_bottom)], axis_col, 1.2)
        text.draw_lines([(left, speed_top), (left, bottom), (right, bottom)],
                        axis_col, 1.2)
        text.draw_text(px0 + 8, top - 24, "KM", FAINT, SMALL_SIZE)
        text.draw_text(px0 + 8, speed_top - 24, "M/S", FAINT, SMALL_SIZE)

        selected_index = self.selected_flight_run
        if selected_index is None or not 0 <= selected_index < len(trajectories):
            selected_index = batch.ranked_indices[0]
            self.selected_flight_run = selected_index
        order = [index for index in range(len(trajectories))
                 if index != selected_index] + [selected_index]
        for index in order:
            trace = trajectories[index]
            altitude_points = []
            speed_points = []
            for row in trace:
                rng = math.hypot(float(row["x_m"]), float(row["z_m"])) / 1000.0
                alt = float(row["altitude_m"]) / 1000.0
                t = float(row["t_s"])
                speed = float(row["speed_mps"])
                altitude_points.append((
                    left + (right - left) * rng / range_limit,
                    altitude_bottom
                    - (altitude_bottom - top) * alt / altitude_limit))
                speed_points.append((
                    left + (right - left) * t / time_limit,
                    bottom - (bottom - speed_top) * speed / speed_limit))
            selected = index == selected_index
            col = ((1.0, 1.0, 1.0, 0.98) if selected
                   else (0.18, 0.48, 1.0, 0.42))
            width = 2.4 if selected else 1.0
            text.draw_lines(altitude_points, col, width)
            text.draw_lines(speed_points, col, width)

        hits = int(round(batch.hit_rate * len(batch.results)))
        summary = (f"HIT {hits}/{len(batch.results)}  "
                   f"MED CLOSEST {batch.median_closest_m:.0f} M  "
                   f"MED APOGEE {batch.median_apogee_km:.1f} KM")
        text.draw_text(px0 + 16, py0 + 34, summary,
                       OK_COL if batch.hit_rate >= 0.9 else DANGER, SMALL_SIZE)
        selected_row = batch.results[selected_index]
        selected_summary = (
            f"SELECT #{int(selected_row['run']):02d}  "
            f"RANK {int(selected_row['performance_rank'])}  "
            f"SCORE {float(selected_row['performance_score']):.1f}  "
            f"{'HIT' if selected_row['hit'] else 'MISS'}  "
            f"APOGEE {float(selected_row['apogee_km']):.1f} KM  "
            f"IMPACT {float(selected_row['impact_speed_mps']):.0f} M/S  "
            f"TIME {float(selected_row['flight_time_s']):.0f} S  "
            f"CLOSE {float(selected_row['closest_m']):.0f} M")
        text.draw_text(
            px0 + 16, py0 + 54,
            self._ellipsize(selected_summary, px1 - px0 - 32, SMALL_SIZE),
            (1.0, 1.0, 1.0), SMALL_SIZE)

    def _draw_preview_info(self, w: int, h: int) -> None:
        px0, py0, px1, _ = self._preview_box
        iw = min(440, max(260, px1 - px0 - 24))
        ih = 126
        ix, iy = px0 + 12, py0 + 12
        draw_panel(self.text, ix, iy, iw, ih, fill=PLATE_INK, ticks=False)
        asset = self.loaded_asset
        if asset is None:
            self.text.draw_text(ix + 12, iy + 12, "NO ASSET GENERATED",
                                DANGER, SMALL_SIZE)
            if self.status_left > 0.0:
                self.text.draw_text(
                    ix + 12, iy + 40,
                    self._ellipsize(self.status, iw - 24, SMALL_SIZE),
                    DANGER if self.status_danger else ACCENT, SMALL_SIZE)
            return
        self.text.draw_text(ix + 12, iy + 10,
                            self._ellipsize(asset.label, iw - 24),
                            TEXT_COL)
        self.text.draw_text(ix + 12, iy + 36,
                            f"{asset.category} / {self.backend}",
                            BELIEF, SMALL_SIZE)
        if self.mesh_stats is not None:
            d = self.mesh_stats["dimensions"]
            line = (f"1:1  {d[0]:.2f} x {d[1]:.2f} x {d[2]:.2f} M  |  "
                    f"{self.mesh_stats['triangles']} TRI")
        else:
            state = "PAUSED" if self.weather_paused else "PLAY"
            line = (f"SEED {self.loaded_seed}  "
                    f"{self.loaded_weather_quality.upper()}  "
                    f"T+{self.cloud_time:05.1f}S  {state}")
        self.text.draw_text(ix + 12, iy + 58,
                            self._ellipsize(line, iw - 24, SMALL_SIZE),
                            MUTED, SMALL_SIZE)
        if self.angle_entry_active:
            entered = self.angle_entry or "AZ,EL"
            cam = f"SET EXACT VIEW > {entered}_"
        else:
            cam = (f"AZ {math.degrees(self.orbit_az) % 360:05.1f}  "
                   f"EL {math.degrees(self.orbit_el):+05.1f}  "
                   f"R {self.orbit_dist:.1f} M")
        self.text.draw_text(ix + 12, iy + 79, cam, MUTED, SMALL_SIZE)
        if self.status_left > 0.0:
            self.text.draw_text(ix + 12, iy + 100,
                                self._ellipsize(self.status, iw - 24, SMALL_SIZE),
                                DANGER if self.status_danger else ACCENT,
                                SMALL_SIZE)

    def _draw_feedback_overlay(self, w: int, h: int) -> None:
        ui = self.feedback
        text = self.text
        text.draw_rect(0, 0, w, h, (0.0, 0.0, 0.0, 0.48))
        pw = min(980, w - 64)
        ph = 210
        px = (w - pw) * 0.5
        py = h - ph - 28
        text.draw_rect(px, py, pw, ph, (*PAPER_BG, 0.98))
        asset = self.loaded_asset.label if self.loaded_asset else "NO ASSET"
        text.draw_text(px + 20, py + 14,
                       f"TEST FEEDBACK // {asset}", PAPER_INK, SMALL_SIZE)
        kind = FEEDBACK_TYPES[ui["type_index"]]
        text.draw_text(px + 20, py + 42,
                       f"TYPE  < {kind} >   [TAB / SHIFT+TAB]",
                       PAPER_MUTED, SMALL_SIZE)
        note = ui["note"] + "_"
        lines = self._wrap(note, pw - 40, max_lines=4)
        for i, line in enumerate(lines):
            text.draw_text(px + 20, py + 70 + i * 24, line, PAPER_INK)
        text.draw_text(px + 20, py + ph - 30,
                       "TYPE NOTE   ENTER FILE + SCREENSHOT   ESC CANCEL",
                       PAPER_MUTED, SMALL_SIZE)

    def _wrap(self, value: str, width: float, max_lines: int) -> list[str]:
        if not value:
            return [""]
        lines, current = [], ""
        for char in value:
            candidate = current + char
            if current and self.text.text_width(candidate) > width:
                lines.append(current)
                current = char
            else:
                current = candidate
        lines.append(current)
        return lines[-max_lines:]

    def _ellipsize(self, value: str, width: float,
                   size: int = BODY_SIZE) -> str:
        value = str(value)
        if self.text.text_width(value, size) <= width:
            return value
        suffix = "..."
        while value and self.text.text_width(value + suffix, size) > width:
            value = value[:-1]
        return value.rstrip() + suffix

    def _show_status(self, message: str, *, danger: bool = False,
                     seconds: float = 3.0) -> None:
        self.status = str(message)
        self.status_left = float(seconds)
        self.status_danger = bool(danger)


__all__ = ("TestingLabState", "build_inspection_chamber")
