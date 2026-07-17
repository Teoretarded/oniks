"""Cinematic mode: stand in a real place and watch an S-300 launch.

Reached only from the hidden F3 lab's CINEMATIC tab.  The scene is baked
1:1 from open LiDAR + orthophoto data (world/cinematic_scene.py), the
player is a walking human (game/walker.py — gravity, eye height), and the
S-300 battery stands on surveyed flat ground at true range, so a launch
looks exactly as it would from that spot: real angular size, real terrain
occlusion, and sound arriving late at 343 m/s.

Fullscreen and chromeless: a title card and data credit fade away, then
the world is yours —

- WHEEL   binoculars (zoom stages + hand sway, manual look, no tracking)
- F       freecam (fly anywhere; WHEEL sets speed; LEFT CLICK teleports
          the walker to the terrain under the center marker)
- G       the DIRECTOR overlay: location / round / light / sky
- K       cycle the missile round (each has its own burn + smoke identity)
- L       launch (the only trigger — nothing fires on its own)
- ESC     back (closes UI/zoom first)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pygame

from engine.camera import Camera
from engine import math3d
import engine.renderer as renderer_mod
from engine.text import BODY_SIZE, HEADER_SIZE, SMALL_SIZE
from game.cinematic_icbm import (ICBM_BY_ID, ICBMS, IcbmLaunch,
                                 NuclearBurst)
from game.cinematic_missiles import (
    CinematicEffects,
    GuidedLaunch,
    ScriptedLaunch,
    VARIANTS,
    next_variant,
)
from game.cinematic_weapons import WeaponRig
from game.states import GameState
from game.walker import Walker
from world.cinematic_scene import CinematicScene, he_crater_dims, \
    nuclear_crater_dims

MOUSE_SENS = 0.0022          # rad per pixel at the native FOV
HEADBOB_HZ_PER_M = 1.0 / 0.75
HEADBOB_AMP = 0.028
SPEED_OF_SOUND = 343.0       # m/s — the launch is HEARD late, 1:1
BASE_FOV = 68.0
# Wheel stages out to 100x (0.68 deg). Past ~10x the handheld sway makes
# free-holding hopeless — that's what I-key tracking is for.
BINO_FOVS = (BASE_FOV, 30.0, 14.0, 7.0, 3.4, 1.7, 0.68)
FREECAM_SPEED0 = 45.0        # m/s, wheel-scaled
TELEPORT_MAX_M = 220_000.0   # ray reach: the world now ends at ring 3

# Fresh overlay palette — deliberately NOT the game's brass terminal ink:
# near-black glass, hairline white rules, one cool accent.
UI_GLASS = (0.02, 0.03, 0.045, 0.86)
UI_GLASS_SOFT = (0.02, 0.03, 0.045, 0.62)
UI_HAIR = (1.0, 1.0, 1.0, 0.14)
UI_TXT = (0.93, 0.95, 0.97)
UI_DIM = (0.52, 0.58, 0.65)
UI_ACC = (0.55, 0.85, 1.0)

@dataclass(frozen=True)
class Mood:
    """One light rig: sun + haze + sky dome + ambient gains.  Sun dirs
    are FIXED per mood, which is what lets terrain shadows be pre-baked
    (world/cinematic_shadows.py)."""
    id: str
    label: str
    sun_dir: tuple
    sun_color: tuple
    haze_color: tuple
    sun_haze_color: tuple
    haze_density: float
    hemi_gain: float = 1.0       # hemispheric sky light multiplier
    light_gain: float = 1.0      # reflective-particle light multiplier
    sky_horizon: tuple = None    # None -> the sky dome's stock daylight
    sky_zenith: tuple = None
    sky_disc: tuple = None


MOODS = (
    Mood("alpine", "ALPINE",
         # Crisp thin-air light: high cool sun, very little haze, the
         # deep blue zenith of 2000 m clarity.
         (0.30, 0.68, 0.42), (1.0, 0.98, 0.94),
         (0.55, 0.66, 0.82), (0.80, 0.85, 0.95), 1.3e-5,
         hemi_gain=1.05,
         sky_horizon=(0.66, 0.76, 0.88), sky_zenith=(0.10, 0.28, 0.58)),
    Mood("noon", "NOON",
         (0.35, 0.42, 0.55), (1.0, 0.96, 0.88),
         (0.62, 0.70, 0.80), (0.95, 0.86, 0.72), 2.5e-5),
    Mood("golden", "GOLDEN HOUR",
         (0.62, 0.13, 0.45), (1.0, 0.66, 0.38),
         (0.72, 0.62, 0.55), (1.0, 0.60, 0.32), 3.6e-5,
         hemi_gain=0.92, light_gain=0.95,
         sky_horizon=(0.88, 0.64, 0.42), sky_zenith=(0.22, 0.28, 0.46)),
    Mood("grey", "GREY MORNING",
         # LOW diffuse sun (user report: the old grey morning hung the
         # sun near the zenith) — 16 deg up in the north-east.
         (0.42, 0.20, 0.58), (0.55, 0.57, 0.60),
         (0.60, 0.64, 0.68), (0.70, 0.72, 0.74), 5.0e-5,
         hemi_gain=1.08, light_gain=0.9,
         sky_horizon=(0.70, 0.73, 0.77), sky_zenith=(0.42, 0.47, 0.54),
         sky_disc=(0.82, 0.83, 0.85)),
    Mood("night", "NIGHT",
         # Moonlit: a dim blue key light standing in for the moon, the
         # sky nearly black, ambient and smoke lighting crushed.
         (-0.50, 0.30, -0.35), (0.10, 0.115, 0.16),
         (0.045, 0.06, 0.10), (0.08, 0.10, 0.16), 2.8e-5,
         hemi_gain=0.16, light_gain=0.22,
         sky_horizon=(0.05, 0.07, 0.12), sky_zenith=(0.008, 0.015, 0.04),
         sky_disc=(0.85, 0.88, 0.92)),
)

# Sky presets: (weather preset id from sim.atmosphere, label).
SKIES = ((0, "CLEAR"), (1, "FAIR"), (2, "BROKEN"), (3, "OVERCAST"),
         (6, "STORM"))

# Launcher roster: the S-300 pad plus one strategic launcher per weapon
# (silo compound, or the submerged boat for water-launched rounds).
LAUNCHERS = (("s300", "S-300 PAD", "THE COLD-LAUNCH CLASSIC"),) + tuple(
    (s.id,
     f"{s.label} {'SSBN' if s.water_launch else 'SILO'}",
     s.blurb) for s in ICBMS)
# Coast time-warp ladder while an ICBM flies ('.' cycles).
WARPS = (1.0, 8.0, 30.0)

# M orbit view: pure camera play onto a real Earth (world/earth_globe).
GLOBE_ASCEND_S = 5.0         # ride up to orbit (and back down)
GLOBE_ALT0 = 500_000.0       # LEO entry altitude (user: "500 km out")
GLOBE_ALT_MIN = 80_000.0
GLOBE_ALT_MAX = 20_000_000.0


class CinematicState(GameState):
    """Walkable 1:1 real-world location viewer (see module docstring)."""

    def __init__(self, app, scene_dir: str):
        super().__init__(app)
        self.scene_dir = scene_dir
        self.camera = Camera(fov_y_deg=BASE_FOV, near=0.15)
        self._gl = None
        self.text = None
        self.scene = None
        self.terrain = None
        self.trees = None
        self.sky = None
        self.effects = None
        self.particles = None
        self.overlay = None
        self.clouds = None
        self.cloud_time = 0.0
        self._sky_off = np.zeros(3)  # world shift: parks weather overhead
        self._sky_cam = None
        self.tel_mesh = None
        self.missile_mesh = None
        self.wind = None             # WindProfile once the scene loads
        self.fog = None              # CinematicFog once the scene loads
        self._shadow_pool = None     # mood shadow bake worker
        self._shadow_futs = {}
        self._shadow_texs = {}
        self.walker = None
        self.launches: list = []     # every live round (salvo-friendly)
        self._bursts: list = []      # live NuclearBurst timelines
        self.t = 0.0
        self._min_relaunch_s = 2.5   # L works again this soon after a shot
        self._sound_queue = []       # (due_t, name, pos, gain)
        self._pad = None
        self._pad_yaw = 0.0
        self._tube_top = 9.1
        self._disposed = False

        # Player-facing state.
        self.variant = VARIANTS[0]
        self.mood_i = 0
        self.sky_i = 0
        self.zoom_i = 0              # BINO_FOVS index
        self._zoom_fade = 0.0
        self.freecam = False
        self.fc_pos = np.zeros(3, dtype=np.float64)
        self.fc_speed = FREECAM_SPEED0
        self.ui_open = False
        self._ui_rects: list = []    # (kind, index, rect)
        self._toast = ""
        self._toast_left = 0.0
        self.spot = False            # I: highlight + line to the missile;
                                     # zoomed-in it becomes auto-tracking
        self._shake = 0.0            # observer shake, arrives WITH the boom
        self._shake_queue = []       # (due_t, amplitude)
        self.weapons = WeaponRig()   # F1: shoulder-fired weapons (GL-free)

        # ICBM battery (docs/plans/icbm_cinematic_plan_2026-07-17.md).
        self.launcher_i = 0          # LAUNCHERS index (0 = S-300 pad)
        self.icbm_target = None      # np (3,) designated ground point
        self.icbm_targets: list = []  # MIRV: every live mark, in order
        self._lake_site = None       # np (3,) open water (Trident)

        # M orbit view (world/earth_globe): camera-play state machine.
        self.globe = None            # EarthGlobe once built (GL)
        self.globe_mode = "off"      # off / ascend / orbit / descend
        self.globe_t = 0.0
        self.globe_lat = 0.0         # camera nadir on the planet
        self.globe_lon = 0.0
        self.globe_alt = GLOBE_ALT0  # height above sea level (m)
        self._g_anchor = (0.0, 0.0)  # the player's lat/lon at M-press
        self._g_eye0 = None          # walker/freecam pose at M-press
        self._g_fwd0 = None
        self._g_desc0 = None         # (lat, lon, alt) at descend start
        self._space_k = 0.0          # 0 = in the air, 1 = in space
        self.follow = False          # C: chase cam on the newest round
        self.warp_i = 0              # WARPS index (ICBM flight only)
        self._silo_site = None       # np (3,) surveyed compound center
        self._silo_yaw = 0.0         # rails/door slide away from spawn
        self._door_anim = {s.id: 0.0 for s in ICBMS}
        self.silo_meshes = {}        # id -> (compound, door) GL meshes
        self.icbm_meshes = {}        # id -> missile mesh
        self._chase_eye = None       # smoothed chase-cam position

    # ------------------------------------------------------------ lifecycle

    def enter(self) -> None:
        try:
            self._enter()
        except Exception:
            # A partial enter must not leak its GL objects — dispose() is
            # tolerant of half-built state (every field starts None).
            self.dispose()
            raise

    def _enter(self) -> None:
        if self._gl is None:
            import OpenGL.GL as gl
            from engine.mesh import Mesh
            from engine.particles import ParticleRenderer
            from game.cinematic_overlay import BinocularOverlay
            from models.s300 import build_s300_missile, build_s300_tel
            from world.cinematic_terrain import CinematicTerrain
            from world.cinematic_trees import CinematicTrees
            from world.sky import Sky

            self._gl = gl
            self.text = self.app.ui_text()
            self.scene = CinematicScene(self.scene_dir)
            self.terrain = CinematicTerrain(self.scene)
            self.trees = CinematicTrees(self.scene_dir, self.scene.tiles)
            self.sky = Sky()
            # Measured wind profile (tools/fetch_cinematic_wind.py): the
            # column drifts on a year of real per-altitude statistics.
            from world.cinematic_wind import (WindProfile,
                                              ridge_floor_from_scene)
            floor_y, ridge_y = ridge_floor_from_scene(self.scene)
            self.wind = WindProfile.load(self.scene_dir,
                                         self.scene.origin_alt,
                                         floor_y=floor_y, ridge_y=ridge_y)
            self.effects = CinematicEffects(seed=3, wind_profile=self.wind)
            # Rolling terrain fog: icy peaks always, valley floor only in
            # the low-sun moods (world/cinematic_fog.py).
            from world.cinematic_fog import CinematicFog
            self.fog = CinematicFog(self.scene, self.effects.fog,
                                    wind_profile=self.wind)
            self.particles = ParticleRenderer()
            self.overlay = BinocularOverlay()
            tel_md = build_s300_tel(elevation_deg=90.0)
            self._tube_top = (float(tel_md.vertices[:, 1].max())
                              if len(tel_md.vertices) else 9.1)
            self.tel_mesh = Mesh(tel_md)
            self.missile_mesh = Mesh(build_s300_missile())
            from models.icbm import (build_minuteman_iii,
                                     build_minuteman_lf,
                                     build_minuteman_lf_door,
                                     build_sarmat, build_sarmat_silo,
                                     build_sarmat_silo_lid,
                                     build_trident)
            self.silo_meshes = {
                "mm3": (Mesh(build_minuteman_lf()),
                        Mesh(build_minuteman_lf_door())),
                "sarmat": (Mesh(build_sarmat_silo()),
                           Mesh(build_sarmat_silo_lid())),
            }
            self.icbm_meshes = {"mm3": Mesh(build_minuteman_iii()),
                                "sarmat": Mesh(build_sarmat()),
                                "trident": Mesh(build_trident())}

            self._start_shadow_bakes()
            (sx, sz), yaw = self.scene.spawn_pos_yaw()
            self.walker = Walker(self.scene.ground_h, self.scene.blocked,
                                 pos=(sx, sz), yaw=yaw)
            s3 = self.scene.s300
            px, pz = float(s3["x"]), float(s3["z"])
            self._pad = np.array([px, self.scene.ground_h(px, pz), pz],
                                 dtype=np.float64)
            # Missiles lean AWAY from the spawn: the plume unveils toward
            # the valley instead of dumping the smoke column onto the lens.
            self._pad_yaw = math.atan2(px - sx, pz - sz)
            # ICBM silo: deterministic survey (flat, clear, LOS, watching
            # distance) — the compound door slides AWAY from the spawn.
            from world.cinematic_scene import (survey_lake_site,
                                               survey_silo_site)
            cx, cz = survey_silo_site(self.scene)
            self._silo_site = np.array(
                [cx, self.scene.ground_h(cx, cz), cz], dtype=np.float64)
            self._silo_yaw = math.atan2(cx - sx, cz - sz)
            # Open water for the sub-launched rounds (None: no lake).
            lake = survey_lake_site(self.scene)
            self._lake_site = None
            if lake is not None:
                lx, lz = lake
                self._lake_site = np.array(
                    [lx, self.scene.ground_h(lx, lz), lz],
                    dtype=np.float64)
            self._apply_mood()
        pygame.event.set_grab(True)
        pygame.mouse.set_visible(False)
        pygame.mouse.get_rel()               # flush the grab-jump delta

    def leave(self) -> None:
        pygame.event.set_grab(False)
        pygame.mouse.set_visible(True)
        self._restore_light()

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self._restore_light()
        if self._shadow_pool is not None:
            self._shadow_pool.shutdown(wait=False, cancel_futures=True)
            self._shadow_pool = None
            self._shadow_futs = {}
        for res in (self.terrain, self.trees, self.sky, self.particles,
                    self.tel_mesh, self.missile_mesh, self.overlay,
                    self.clouds, self.weapons, self.globe):
            if res is None:
                continue
            fn = getattr(res, "dispose", None) or getattr(res, "delete",
                                                          None)
            if fn is not None:
                fn()

    def effective_time_scale(self) -> float:
        """1x always — except the '.' warp while a TARGETED round flies
        (ICBM or a guided pad round; scripted shows stay realtime)."""
        if self.warp_i > 0 and any(
                isinstance(m, (IcbmLaunch, GuidedLaunch)) and not m.done
                for m in self.launches):
            return WARPS[self.warp_i]
        return 1.0

    # ------------------------------------------------------------ lighting

    def _apply_mood(self) -> None:
        m = MOODS[self.mood_i]
        r = self.app.renderer
        d = np.asarray(m.sun_dir, dtype=np.float64)
        r.sun_dir = d / np.linalg.norm(d)
        r.sun_color = m.sun_color
        r.haze_color = m.haze_color
        r.sun_haze_color = m.sun_haze_color
        r.haze_density = m.haze_density
        r.hemi_gain = m.hemi_gain
        r.light_gain = m.light_gain
        if self.sky is not None:
            self.sky.set_colors(m.sky_horizon, m.sky_zenith, m.sky_disc)
        # The wind rides the time of day with the light: grey morning is
        # calm drainage flow, noon the up-valley thermal wind (measured
        # bands from the scene's wind profile).
        if self.wind is not None:
            self.wind.set_mood(m.id)
        if self.fog is not None:
            self.fog.set_mood(m.id)
        self._apply_shadow(m.id)

    def _restore_light(self) -> None:
        r = self.app.renderer
        r.alt_offset = 0.0
        r.sun_dir = renderer_mod.SUN_DIR
        r.sun_color = renderer_mod.SUN_COLOR
        r.haze_color = renderer_mod.HAZE_COLOR
        r.sun_haze_color = renderer_mod.SUN_HAZE_COLOR
        r.haze_density = renderer_mod.HAZE_DENSITY
        r.hemi_gain = 1.0
        r.light_gain = 1.0

    # ------------------------------------------------------ baked shadows

    def _start_shadow_bakes(self) -> None:
        """Kick every mood's terrain-shadow bake onto a worker thread
        (disk-cached: after the first visit these come back instantly).
        Uploads happen on the GL thread in _poll_shadows."""
        from concurrent.futures import ThreadPoolExecutor
        from world.cinematic_shadows import bake_mood_mask
        self._shadow_pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="cine-shadow")
        self._shadow_futs = {
            m.id: self._shadow_pool.submit(bake_mood_mask, self.scene,
                                           m.id, m.sun_dir)
            for m in MOODS
        }
        self._shadow_texs = {}       # mood id -> (gl tex, rect)

    def _poll_shadows(self) -> None:
        """GL thread: upload finished bakes; apply the current mood's."""
        if not self._shadow_futs:
            return
        done = [mid for mid, f in self._shadow_futs.items() if f.done()]
        for mid in done:
            f = self._shadow_futs.pop(mid)
            try:
                mask, rect = f.result()
            except Exception as exc:     # noqa: BLE001 — unshadowed, loud
                print(f"[cinematic] shadow bake failed for {mid}: {exc}")
                continue
            tex = self.terrain.upload_shadow_mask(mask)
            self._shadow_texs[mid] = (tex, rect)
            if MOODS[self.mood_i].id == mid:
                self._apply_shadow(mid)

    def _apply_shadow(self, mood_id: str) -> None:
        """Point terrain + trees at the mood's mask (no-op until baked)."""
        if self.terrain is None:
            return
        tex, rect = self._shadow_texs.get(mood_id, (0, (0, 0, 1, 1)))
        self.terrain.set_shadow(tex, rect)
        if self.trees is not None:
            self.trees.shadow_tex = self.terrain.shadow_tex
            self.trees.shadow_rect = self.terrain.shadow_rect
            self.trees.shadow_str = self.terrain.shadow_str

    def _apply_sky(self) -> None:
        preset_id, label = SKIES[self.sky_i]
        if self.clouds is not None:
            self.clouds.delete()
            self.clouds = None
        self._sky_off = np.zeros(3)
        if preset_id != 0:
            from sim.atmosphere import CONVECTIVE_DOMAIN_M, weather_preset
            from world.clouds_v2 import CloudsV2
            prefs = getattr(self.app, "ui_prefs", None)
            quality = prefs.get("cloud_quality") if prefs else "high"
            self.clouds = CloudsV2(7, quality=quality or "high",
                                   weather_preset=weather_preset(preset_id))
            # The cloud fields are anchored to a battle-sized world (the
            # regional weather texture spans 300 km; the storm domain is
            # 800 km) and our valley occupies a 4 km dot of it — so the
            # picked weather could easily be happening somewhere ELSE
            # (user report: 'storm clouds are all the way out there').
            # Bias regional coverage up so the preset is overhead, and
            # for storms shift the whole sky so the densest supercell
            # column sits over the scene.
            self.clouds._macro_bias = max(
                float(getattr(self.clouds, "_macro_bias", 0.0)), 0.55)
            field = getattr(self.clouds, "_field", None)
            occ = getattr(field, "storm_occupancy", None)
            if occ is not None and np.asarray(occ).any():
                col = np.asarray(occ, dtype=np.float32).sum(axis=0)
                iv, iu = np.unravel_index(int(col.argmax()), col.shape)
                dom = float(CONVECTIVE_DOMAIN_M)
                cx = (iu + 0.5) / col.shape[1] * dom
                cz = (iv + 0.5) / col.shape[0] * dom
                cx = ((cx + dom * 0.5) % dom) - dom * 0.5
                cz = ((cz + dom * 0.5) % dom) - dom * 0.5
                self._sky_off = np.array([cx, 0.0, cz])
        self._say(f"SKY {label}")

    def _cloud_camera(self):
        """The camera the clouds see: the real one, world-shifted so the
        chosen weather actually happens HERE."""
        if not np.any(self._sky_off):
            return self.camera
        if self._sky_cam is None:
            self._sky_cam = Camera(fov_y_deg=BASE_FOV, near=0.15)
        c = self._sky_cam
        c.fov_y = self.camera.fov_y
        c.eye = self.camera.eye + self._sky_off
        c.forward = self.camera.forward
        c.up = self.camera.up
        return c

    def _say(self, msg: str) -> None:
        self._toast = msg
        self._toast_left = 2.2

    # ---------------------------------------------------------------- input

    def handle_event(self, ev) -> None:
        # Weapons first: F1 locker, sight/designate/fire clicks. Consumes
        # ESC only while its locker is open (game/cinematic_weapons.py).
        if self.weapons.handle_event(ev, self):
            return
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            if self.globe_mode in ("ascend", "orbit"):
                self._globe_return()
            elif self.ui_open:
                self.ui_open = False
            elif self.zoom_i > 0:
                self.zoom_i = 0
            else:
                self.app.close_cinematic()
            return
        if self.walker is None:          # events before enter() are no-ops
            return
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_g:
            self.ui_open = not self.ui_open
            pygame.event.set_grab(not self.ui_open)
            pygame.mouse.set_visible(self.ui_open)
            return
        if self.ui_open:
            self._ui_event(ev)
            return
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_SPACE and not self.freecam:
                self.walker.jump()
            elif ev.key == pygame.K_l:
                self._fire()
            elif ev.key == pygame.K_k:
                self.variant = next_variant(self.variant.id)
                self._say(f"ROUND {self.variant.label} - "
                          f"{self.variant.blurb}")
            elif ev.key == pygame.K_f:
                self._toggle_freecam()
            elif ev.key == pygame.K_i:
                self.spot = not self.spot
                self._say("SPOTTER ON - TRACKS WHILE ZOOMED"
                          if self.spot else "SPOTTER OFF")
            elif ev.key == pygame.K_t:
                self._designate_target()
            elif ev.key == pygame.K_c:
                self.follow = not self.follow
                self._say("CHASE CAM" if self.follow else "CHASE CAM OFF")
            elif ev.key == pygame.K_m:
                self._toggle_globe()
            elif ev.key == pygame.K_PERIOD:
                if any(isinstance(m, (IcbmLaunch, GuidedLaunch))
                       and not m.done for m in self.launches):
                    self.warp_i = (self.warp_i + 1) % len(WARPS)
                    self._say(f"TIME X{WARPS[self.warp_i]:.0f}")
                else:
                    self._say("TIME WARP NEEDS A BIRD IN FLIGHT")
        elif ev.type == pygame.MOUSEMOTION:
            rx, ry = getattr(ev, "rel", (0, 0))
            if self.globe_mode == "orbit":
                # Drag scrubs the planet under the camera; pan rate
                # scales with altitude so it always feels 1:1.
                deg = min(max(0.055 * self.globe_alt / 1.0e6, 0.004),
                          0.6)
                self.globe_lon += rx * deg
                self.globe_lat = float(np.clip(
                    self.globe_lat - ry * deg, -85.0, 85.0))
                return
            if self.globe_mode != "off":
                return                     # riding the elevator: no look
            sens = MOUSE_SENS * (self._fov() / BASE_FOV)
            self.walker.look(rx * sens, -ry * sens)
        elif ev.type == pygame.MOUSEWHEEL:
            if self.globe_mode == "orbit":
                self.globe_alt = float(np.clip(
                    self.globe_alt * (1.3 ** -ev.y),
                    GLOBE_ALT_MIN, GLOBE_ALT_MAX))
                self._say(f"ALT {self.globe_alt / 1000.0:.0f} KM")
                return
            if self.freecam:
                self.fc_speed = float(np.clip(
                    self.fc_speed * (1.25 ** ev.y), 4.0, 1200.0))
                self._say(f"FREECAM {self.fc_speed:.0f} M/S")
            else:
                old = self.zoom_i
                self.zoom_i = int(np.clip(self.zoom_i + ev.y, 0,
                                          len(BINO_FOVS) - 1))
                if self.zoom_i != old and self.zoom_i > 0:
                    self._say(f"BINOCULARS {BASE_FOV / self._fov():.0f}X")
        elif (ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1
              and self.freecam):
            self._teleport_to_view()

    # --------------------------------------------------------- orbit view

    def _toggle_globe(self) -> None:
        """M: ride the camera to LEO over your own position (and back).
        Not a map — the same world from a different distance."""
        if self.globe_mode in ("ascend", "orbit"):
            self._globe_return()
            return
        if self.globe_mode == "descend":
            return                       # already riding down
        if self.terrain is None:
            return                       # headless / not entered yet
        if self.globe is None:
            try:
                from world.earth_globe import EarthGlobe
                self.globe = EarthGlobe(self.scene)
            except Exception as exc:     # noqa: BLE001 — data missing
                self._say("NO EARTH DATA - RUN fetch_cinematic_earth")
                print(f"[cinematic] globe unavailable: {exc}")
                return
        from world.earth_globe import local_to_latlon
        eye = np.asarray(self._eye(), dtype=np.float64)
        anchor = local_to_latlon(float(eye[0]), float(eye[2]),
                                 self.globe.lat0, self.globe.lon0)
        self._g_anchor = anchor
        self.globe_lat, self.globe_lon = anchor
        self.globe_alt = GLOBE_ALT0
        self._g_eye0 = eye.copy()
        yaw, pitch = self.walker.yaw, self.walker.pitch
        cp = math.cos(pitch)
        self._g_fwd0 = np.array([math.sin(yaw) * cp, math.sin(pitch),
                                 math.cos(yaw) * cp])
        self.globe_t = 0.0
        self.globe_mode = "ascend"
        self.zoom_i = 0
        self._say("ORBIT VIEW - DRAG PANS   WHEEL ALT   "
                  "T MARKS CENTER   M RETURNS")

    def _globe_return(self) -> None:
        self._g_desc0 = (self.globe_lat, self.globe_lon, self.globe_alt)
        self.globe_t = 0.0
        self.globe_mode = "descend"
        self._say("RETURNING")

    def _globe_pose(self, dt_real: float):
        """Advance the orbit state machine; (eye, forward, up) for the
        camera this frame."""
        from world.earth_globe import EARTH_R, geo_unit, geo_frame
        g = self.globe
        frame = geo_frame(g.lat0, g.lon0)
        center = np.array([0.0, g.center_y, 0.0])

        def pose_at(lat, lon, alt):
            unit = frame @ geo_unit(lat, lon)
            north = frame @ np.array(
                [-math.sin(math.radians(lat)) * math.cos(math.radians(lon)),
                 math.cos(math.radians(lat)),
                 -math.sin(math.radians(lat)) * math.sin(math.radians(lon))])
            eye = center + unit * (EARTH_R + alt)
            return eye, -unit, north

        self.globe_t += max(dt_real, 0.0)
        a0 = float(self._g_eye0[1]) + self.scene.origin_alt
        a0 = max(a0, 50.0)
        if self.globe_mode == "ascend":
            f = min(self.globe_t / GLOBE_ASCEND_S, 1.0)
            f = f * f * (3.0 - 2.0 * f)
            alt = a0 * (GLOBE_ALT0 / a0) ** f
            eye_n, fwd_n, up_n = pose_at(*self._g_anchor, alt)
            # First rise, then tip over: view blends late (f^2).
            b = f * f
            fwd = self._g_fwd0 * (1.0 - b) + fwd_n * b
            up = np.array([0.0, 1.0, 0.0]) * (1.0 - b) + up_n * b
            eye0 = self._g_eye0 + np.array([0.0, alt - a0, 0.0])
            eye = eye0 * (1.0 - f) + eye_n * f
            if self.globe_t >= GLOBE_ASCEND_S:
                self.globe_mode = "orbit"
            return eye, fwd, up
        if self.globe_mode == "descend":
            f = min(self.globe_t / GLOBE_ASCEND_S, 1.0)
            f = f * f * (3.0 - 2.0 * f)
            lat0, lon0, alt0 = self._g_desc0
            lat = lat0 + (self._g_anchor[0] - lat0) * f
            lon = lon0 + (self._g_anchor[1] - lon0) * f
            alt = alt0 * (a0 / alt0) ** f
            eye_n, fwd_n, up_n = pose_at(lat, lon, alt)
            b = (1.0 - f) ** 2
            fwd = self._g_fwd0 * (1.0 - b) + fwd_n * b
            up = np.array([0.0, 1.0, 0.0]) * (1.0 - b) + up_n * b
            eye0 = self._g_eye0 + np.array([0.0, alt - a0, 0.0])
            eye = eye0 * f + eye_n * (1.0 - f)
            if self.globe_t >= GLOBE_ASCEND_S:
                self.globe_mode = "off"
                self._apply_mood()       # restore haze/sky exactly
            return eye, fwd, up
        eye, fwd, up = pose_at(self.globe_lat, self.globe_lon,
                               self.globe_alt)
        return eye, fwd, up

    def _toggle_freecam(self) -> None:
        self.freecam = not self.freecam
        if self.freecam:
            self.zoom_i = 0
            self.fc_pos = np.array(self.walker.eye, dtype=np.float64)
            self._say("FREECAM - LEFT CLICK TELEPORTS")
        else:
            self._say("WALK MODE")

    def _fov(self) -> float:
        if not self.freecam:
            ads = self.weapons.fov_override()   # weapon sight wins
            if ads is not None:
                return ads
        return BINO_FOVS[0] if self.freecam else BINO_FOVS[self.zoom_i]

    # ------------------------------------------------------------ teleport

    def _view_ground_hit(self, p: np.ndarray, direction=None):
        """March the view ray from ``p`` onto the bare-earth field.
        Returns the clamped hit point or None (shared by the freecam
        teleport and T target designation)."""
        d = (np.array(direction, dtype=np.float64) if direction is not None
             else np.array(self.walker.forward(), dtype=np.float64))
        hit = None
        t, step = 0.0, 8.0
        # The walkable world spans the full SURROUND extent (16 x 16 km on
        # scenes that bake one), not just the fine LiDAR core.
        sc = self.scene
        wx0 = getattr(sc, "ext_x0", sc.x0)
        wx1 = getattr(sc, "ext_x1", sc.x1)
        wz0 = getattr(sc, "ext_z0", sc.z0)
        wz1 = getattr(sc, "ext_z1", sc.z1)
        while t < TELEPORT_MAX_M:
            t += step
            q = p + d * t
            if not (wx0 <= q[0] <= wx1 and wz0 <= q[2] <= wz1):
                continue     # freecam can be OUTSIDE the world looking in
            g = self.scene.ground_h(q[0], q[2])
            if np.isfinite(g) and g >= q[1]:
                lo, hi = t - step, t
                for _ in range(14):
                    mid = 0.5 * (lo + hi)
                    q = p + d * mid
                    if self.scene.ground_h(q[0], q[2]) >= q[1]:
                        hi = mid
                    else:
                        lo = mid
                hit = p + d * hi
                break
        if hit is not None:
            # The bisection's low end can sit OUTSIDE the world (the ray
            # entered it mid-segment) where the border-clamped sampler
            # invents ground — nudge a near-miss inside, refuse the rest
            # (GPT-5.6 review 2026-07-16: landed at x = -8008).
            hit[0] = float(np.clip(hit[0], wx0 + 1.0, wx1 - 1.0))
            hit[2] = float(np.clip(hit[2], wz0 + 1.0, wz1 - 1.0))
            q = p + d * hi
            if math.hypot(q[0] - hit[0], q[2] - hit[2]) > step + 1.0:
                hit = None
        return hit

    def _teleport_to_view(self) -> None:
        """Drop the walker onto the terrain under the freecam marker."""
        hit = self._view_ground_hit(self.fc_pos.copy())
        if hit is None:
            self._say("NO GROUND THERE")
            return
        w = self.walker
        w.x, w.z = float(hit[0]), float(hit[2])
        w.y = w.ground_h(w.x, w.z)
        w.vx = w.vy = w.vz = 0.0
        w.on_ground = True
        self.freecam = False
        self._say("TELEPORTED")

    def _designate_target(self) -> None:
        """T: mark the ground point under the view ray.  In chase cam
        the WALKER's view is stale — the mark must follow the ray the
        player actually sees, i.e. the camera's (user report: rounds
        'not going where I mark').  From ORBIT the reticle (screen
        center = the camera nadir) is the mark."""
        if self.globe_mode == "orbit" and self.globe is not None:
            from world.earth_globe import latlon_to_local
            lx, lz = latlon_to_local(self.globe_lat, self.globe_lon,
                                     self.globe.lat0, self.globe.lon0)
            sc = self.scene
            if not (sc.ext_x0 <= lx <= sc.ext_x1
                    and sc.ext_z0 <= lz <= sc.ext_z1):
                d_km = math.hypot(lx, lz) / 1000.0
                self._say(f"OUTSIDE THE BAKED WORLD - {d_km:.0f} KM OUT")
                return
            g = sc.ground_h(lx, lz)
            if not np.isfinite(g):
                self._say("NO TERRAIN DATA UNDER THE RETICLE")
                return
            hit = np.array([lx, g, lz], dtype=np.float64)
        else:
            if self.follow and self.launch is not None:
                eye = np.array(self.camera.eye, dtype=np.float64)
                direction = np.array(self.camera.forward,
                                     dtype=np.float64)
            else:
                eye = np.array(self._eye(), dtype=np.float64)
                direction = None
            hit = self._view_ground_hit(eye, direction)
        if hit is None:
            self._say("NO GROUND UNDER THE MARK")
            return
        hit[1] = self.scene.ground_h(float(hit[0]), float(hit[2]))
        self.icbm_target = hit
        # MIRV weapons collect marks up to the bus capacity; every
        # other launcher keeps single-mark behaviour (list of one).
        lid = LAUNCHERS[self.launcher_i][0]
        cap = 1
        if lid in ICBM_BY_ID:
            cap = max(1, ICBM_BY_ID[lid].mirv_count)
        if cap <= 1 or len(self.icbm_targets) >= cap:
            self.icbm_targets = [hit]
        else:
            self.icbm_targets.append(hit)
        n = len(self.icbm_targets)
        site = self._launch_site(lid)
        if site is not None:
            rng = math.hypot(hit[0] - site[0], hit[2] - site[2])
            tag = f"TARGET {n}/{cap} SET" if cap > 1 else "TARGET SET"
            self._say(f"{tag} - {rng / 1000.0:.1f} KM OUT")
        else:
            self._say("TARGET SET")

    def _launch_site(self, lid: str):
        """Where this launcher fires from: lake for water launch."""
        if lid in ICBM_BY_ID and ICBM_BY_ID[lid].water_launch:
            return self._lake_site
        if lid == "s300":
            return self._pad
        return self._silo_site

    # ----------------------------------------------------------- launching

    @property
    def launch(self):
        """The newest round in the air (spotter/tracker target)."""
        for m in reversed(self.launches):
            if not m.done:
                return m
        return None

    def _fire(self) -> None:
        """L: the selected launcher fires — S-300 salvo rules on the pad,
        one-bird-per-silo rules for the ICBMs."""
        lid = LAUNCHERS[self.launcher_i][0]
        if lid != "s300":
            self._fire_icbm(lid)
            return
        last = None
        for m in reversed(self.launches):
            if isinstance(m, ScriptedLaunch):
                last = m
                break
        if (last is not None and not last.done
                and last.t < self._min_relaunch_s):
            self._say(f"TUBE CYCLING - "
                      f"{self._min_relaunch_s - last.t:.1f} S")
            return
        if self.icbm_target is not None:
            # Universal T-targeting: with a mark set, the pad round
            # flies its computed fastest route to it (user order
            # 2026-07-17); the scripted show only fires unmarked.
            m = GuidedLaunch(self.variant, self._pad, self._pad_yaw,
                             self._tube_top, tuple(self.icbm_target),
                             self.scene.ground_h,
                             origin_alt=self.scene.origin_alt)
            if not m.feasible:
                self._say(f"{self.variant.label}: NO ROUTE TO THE MARK "
                          f"(RANGE {self.variant.range_km:.0f} KM)")
                return
            rng = math.hypot(self.icbm_target[0] - self._pad[0],
                             self.icbm_target[2] - self._pad[2])
            self._say(f"{self.variant.label} AWAY - "
                      f"{rng / 1000.0:.1f} KM TO THE MARK")
        else:
            m = ScriptedLaunch(self.variant, self._pad, self._pad_yaw,
                               self._tube_top)
        self.launches.append(m)
        mouth = self._pad + np.array([0.0, self._tube_top, 0.0])
        m.eject_fx(self.effects, mouth, float(self._pad[1]))
        self._queue_sound("pop", mouth, gain=0.5)

    def _fire_icbm(self, lid: str) -> None:
        """One bird per launcher; needs a designated target (T)."""
        spec = ICBM_BY_ID[lid]
        site = self._launch_site(lid)
        if site is None:
            self._say("NO OPEN WATER IN THIS SCENE"
                      if spec.water_launch else "NO SILO SURVEYED")
            return
        if self.icbm_target is None:
            self._say("NO TARGET - AIM AND PRESS T")
            return
        for m in self.launches:
            if isinstance(m, IcbmLaunch) and not m.done \
                    and m.spec.id == lid:
                self._say("BIRD IN FLIGHT - LAUNCHER EMPTY")
                return
        marks = [tuple(t) for t in self.icbm_targets] \
            or [tuple(self.icbm_target)]
        m = IcbmLaunch(spec, silo=tuple(site),
                       target=marks[0],
                       targets=marks if len(marks) > 1 else None,
                       ground_h=self.scene.ground_h,
                       door_open=self._door_anim.get(lid, 0.0) >= 0.99)
        self.launches.append(m)
        rng = math.hypot(marks[0][0] - site[0], marks[0][2] - site[2])
        extra = f" - {len(marks)} MARKS" if len(marks) > 1 else ""
        self._say(f"{spec.label} AWAY - {rng / 1000.0:.1f} KM"
                  f" SHOT{extra}")

    # ------------------------------------------------------------------ sim

    def sim_step(self, dt: float) -> None:
        if self.walker is None:
            return
        self.t += dt
        self.cloud_time += dt
        if self._toast_left > 0.0:
            self._toast_left = max(0.0, self._toast_left - dt)

        fwd = strafe = 0.0
        sprint = False
        if (pygame.display.get_init() and not self.ui_open
                and self.globe_mode == "off"):
            keys = pygame.key.get_pressed()
            fwd = (1.0 if keys[pygame.K_w] else 0.0) - \
                  (1.0 if keys[pygame.K_s] else 0.0)
            strafe = (1.0 if keys[pygame.K_d] else 0.0) - \
                     (1.0 if keys[pygame.K_a] else 0.0)
            sprint = keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]
            if self.freecam:
                up = (1.0 if keys[pygame.K_SPACE] else 0.0) - \
                     (1.0 if keys[pygame.K_LCTRL] else 0.0)
                self._freecam_move(dt, fwd, strafe, up, sprint)
                fwd = strafe = 0.0
        if not self.freecam:
            self.walker.step(dt, fwd, strafe, sprint)
        self._zoom_fade += ((1.0 if self.zoom_i > 0 else 0.0)
                            - self._zoom_fade) * min(1.0, dt * 9.0)

        # Launches are MANUAL only (L / director UI) — no auto-fire timer;
        # the pad stays quiet until the player asks for a round.
        for m in self.launches:
            if m.done:
                continue
            events: list = []
            m.step(dt, events)
            for kind, pos in events:
                if kind == "ignite":
                    m.ignition_fx(self.effects, pos)
                    self._queue_sound("boom", pos)
                    eye = np.asarray(self._eye(), dtype=np.float64)
                    delay = float(np.linalg.norm(pos - eye)) \
                        / SPEED_OF_SOUND
                    amp = m.variant.shake_amp
                    self._shake_queue.append((self.t + delay, amp))
                    if amp >= 1.0:            # the monster: double thump
                        self._shake_queue.append(
                            (self.t + delay + 0.22, 0.35))
                elif kind == "pad_blast":
                    m.pad_blast_fx(self.effects, pos)
                elif kind == "pad_roll":
                    m.pad_roll_fx(self.effects, pos)
                elif kind == "door":
                    self._queue_sound("pop", pos, gain=0.35)
                elif kind == "eject":
                    m.eject_fx(self.effects, pos)
                    self._queue_sound("pop", pos, gain=0.9)
                elif kind == "pallet":
                    m.pallet_fx(self.effects, pos)
                elif kind == "smoke_ring":
                    m.smoke_ring_fx(self.effects, pos)
                elif kind == "stage":
                    m.stage_fx(self.effects, pos)
                elif kind == "mirv_sep":
                    m.stage_fx(self.effects, pos)
                    self._say(f"RV AWAY - "
                              f"{len(getattr(m, '_rvs', []))} RELEASED")
                elif kind == "term":
                    m.term_fx(self.effects, pos)
                    self._say("THRUST TERMINATED - BALLISTIC ARC")
                elif kind == "cutoff":
                    self._say("ENGINE CUTOFF - BALLISTIC ARC")
                elif kind == "impact":
                    self._queue_sound("boom", pos)
                    eye = np.asarray(self._eye(), dtype=np.float64)
                    delay = float(np.linalg.norm(pos - eye)) \
                        / SPEED_OF_SOUND
                    if isinstance(m, IcbmLaunch):
                        # The nuclear timeline replaces the old
                        # conventional puff (user green-lit; Glasstone
                        # numbers in NuclearBurst).
                        self._bursts.append(NuclearBurst(
                            pos, m.impact_yield_kt(), float(pos[1])))
                        self._shake_queue.append((self.t + delay, 4.5))
                        self._say("DETONATION")
                    else:
                        m.impact_fx(self.effects, pos)
                        self._shake_queue.append((self.t + delay, 2.2))
                        self._say("IMPACT")
                    self._spawn_crater(m, pos)
            m.emit(self.effects, dt)
        # Shoulder weapons fly AFTER the targets moved (their rounds home
        # on the fresh positions; a kill marks the launch done for the
        # prune below).
        self.weapons.update(dt, self)
        # No TrailRibbon: the user hates the skinny white line — the
        # per-meter smoke column IS the trail.  Spent rounds are pruned;
        # their smoke lives on in the pools.
        self.launches = [m for m in self.launches if not m.done]
        # Silo doors: ride an active bird's own door clock open, then
        # walk shut a while after the silo goes quiet.
        for sid in self._door_anim:
            live = next((m for m in self.launches
                         if isinstance(m, IcbmLaunch)
                         and m.spec.id == sid), None)
            if live is not None:
                self._door_anim[sid] = max(self._door_anim[sid],
                                           live.door_frac)
            else:
                self._door_anim[sid] = max(
                    0.0, self._door_anim[sid] - dt / 8.0)
        if not any(isinstance(m, (IcbmLaunch, GuidedLaunch))
                   for m in self.launches):
            self.warp_i = 0          # warp is a targeted-flight tool only
        # Nuclear bursts run their own long timelines after the rounds
        # are pruned (flash -> fireball -> stem -> cap -> ground ring).
        if self._bursts:
            crowd = len(self._bursts)
            for b in self._bursts:
                b.step(dt)
                if self.effects is not None:
                    b.emit(self.effects, dt, crowd=crowd)
            self._bursts = [b for b in self._bursts if not b.done]
        if self.effects is not None:
            self.effects.update(dt)
        if self.fog is not None:
            self.fog.step(dt)

        self._shake *= math.exp(-dt / 0.5)
        due_shake = [q for q in self._shake_queue if q[0] <= self.t]
        if due_shake:
            self._shake_queue = [q for q in self._shake_queue
                                 if q[0] > self.t]
            for _, amp in due_shake:
                self._shake = max(self._shake, amp)

        eye = self._eye()
        self.app.audio.set_listener(np.asarray(eye, dtype=np.float64))
        due = [q for q in self._sound_queue if q[0] <= self.t]
        if due:
            self._sound_queue = [q for q in self._sound_queue
                                 if q[0] > self.t]
            for _, name, pos, gain in due:
                # The SAMPLE is chosen when the wavefront ARRIVES, by how
                # far it traveled: a 1 km ignition is a heavy delayed boom,
                # not a close-up crack (sound-physics pass, user report).
                dist = float(np.linalg.norm(
                    np.asarray(pos, dtype=np.float64)
                    - np.asarray(eye, dtype=np.float64)))
                if name == "boom":
                    self.app.audio.boom(pos)
                elif name == "pop":
                    if dist < 2500.0:       # eject pop: inaudible far out
                        self.app.audio.play("boom_far", pos=pos,
                                            gain=gain * 0.6)
                else:
                    self.app.audio.play(name, pos=pos, gain=gain)

    def _spawn_crater(self, m, pos) -> None:
        """Terrain deformation at impact: crater size from the round.
        Nuclear: fireball-anchored destroyed zone (cinematic_scene.
        nuclear_crater_dims); conventional: cube-root HE scaling."""
        add = getattr(self.scene, "add_crater", None)
        if add is None:                # fakes/tests without the overlay
            return
        if isinstance(m, IcbmLaunch):
            w_kt = (m.impact_yield_kt()
                    if hasattr(m, "impact_yield_kt") else m.spec.yield_kt)
            radius, depth = nuclear_crater_dims(w_kt)
        elif isinstance(m, GuidedLaunch):
            radius, depth = he_crater_dims(m.variant.warhead_kg)
        else:
            return
        add(float(pos[0]), float(pos[2]), radius, depth)

    def _freecam_move(self, dt, fwd, strafe, up, sprint) -> None:
        yaw, pitch = self.walker.yaw, self.walker.pitch
        cp = math.cos(pitch)
        d = np.array([math.sin(yaw) * cp, math.sin(pitch),
                      math.cos(yaw) * cp])
        right = np.array([math.cos(yaw), 0.0, -math.sin(yaw)])
        v = d * fwd + right * strafe + np.array([0.0, 1.0, 0.0]) * up
        n = np.linalg.norm(v)
        if n > 1e-6:
            speed = self.fc_speed * (4.0 if sprint else 1.0)
            self.fc_pos += (v / n) * speed * dt

    def _queue_sound(self, name: str, pos, gain: float = 1.0) -> None:
        eye = np.asarray(self._eye(), dtype=np.float64)
        delay = float(np.linalg.norm(np.asarray(pos) - eye)) / SPEED_OF_SOUND
        self._sound_queue.append((self.t + delay, name, np.asarray(pos),
                                  gain))

    def _eye(self):
        return tuple(self.fc_pos) if self.freecam else self.walker.eye

    # ---------------------------------------------------------------- render

    def render(self, dt_real: float) -> None:
        if self._gl is None:
            return
        gl = self._gl
        self._poll_shadows()
        w, h = self.app.window.size()
        gl.glViewport(0, 0, w, h)

        walker = self.walker
        eye = np.array(self._eye(), dtype=np.float64)
        if not self.freecam:
            moving = math.hypot(walker.vx, walker.vz) > 0.3
            if walker.on_ground and moving and self.zoom_i == 0:
                eye[1] += math.sin(walker.walked * 2.0 * math.pi
                                   * HEADBOB_HZ_PER_M) * HEADBOB_AMP
        if self._shake > 0.01:
            # The boom's ground-shock in the legs: fast decaying jitter,
            # scaled way down from the consult's ground-displacement figure.
            s = self._shake * 0.06
            eye[0] += math.sin(self.t * 47.0) * s
            eye[1] += math.sin(self.t * 61.0 + 1.3) * s * 1.4
            eye[2] += math.sin(self.t * 53.0 + 2.1) * s
        self.camera.eye = eye
        # I + binoculars = tracker: steer the view toward the missile at a
        # human panning rate (the launch is never teleport-snapped).
        if (self.spot and self.zoom_i > 0 and not self.freecam
                and self.launch is not None and not self.launch.done):
            rel = self.launch.pos - eye
            want_yaw = math.atan2(rel[0], rel[2])
            want_pitch = math.atan2(rel[1], math.hypot(rel[0], rel[2]))
            blend = min(1.0, dt_real * 5.0)
            dyaw = (want_yaw - walker.yaw + math.pi) % (2 * math.pi) - math.pi
            walker.yaw = (walker.yaw + dyaw * blend) % (2 * math.pi)
            walker.pitch += (want_pitch - walker.pitch) * blend
        yaw, pitch = walker.yaw, walker.pitch
        if self.zoom_i > 0 and not self.freecam:
            # Handheld sway: grows with magnification, calms when still.
            amp = 0.0011 * (1.0 - self._fov() / BASE_FOV)
            yaw = yaw + (math.sin(self.t * 1.13)
                         + 0.6 * math.sin(self.t * 2.71)) * amp
            pitch = pitch + (math.sin(self.t * 0.97 + 1.7)
                             + 0.5 * math.sin(self.t * 2.23)) * amp
        cp = math.cos(pitch)
        self.camera.fov_y = math.radians(self._fov())
        self.camera.set_orientation(np.array(
            [math.sin(yaw) * cp, math.sin(pitch), math.cos(yaw) * cp]))
        # C: chase cam — ride just behind/beside the newest round and
        # WATCH it fly (smoothed so staging kicks don't snap the view).
        if (self.follow and self.launch is not None
                and not self.launch.done and self.globe_mode == "off"):
            m = self.launch
            spec_len = getattr(getattr(m, "spec", None), "length_m", 8.0)
            dist = max(60.0, spec_len * 7.0)
            hd = m.heading()
            side = np.cross(hd, np.array([0.0, 1.0, 0.0]))
            ns = float(np.linalg.norm(side))
            side = side / ns if ns > 1e-6 else np.array([1.0, 0.0, 0.0])
            # Mostly LATERAL: the airframe silhouettes against the sky
            # instead of hiding inside its own exhaust glow (audit r3).
            want = (m.pos - hd * dist * 0.55 + side * dist * 0.85
                    + np.array([0.0, dist * 0.18, 0.0]))
            if self._chase_eye is None:
                self._chase_eye = want.copy()
            blend = min(1.0, dt_real * 3.0)
            self._chase_eye += (want - self._chase_eye) * blend
            eye = self._chase_eye
            look = m.pos + hd * spec_len * 0.5 - eye
            n = float(np.linalg.norm(look))
            if n > 1e-6:
                self.camera.fov_y = math.radians(BASE_FOV)
                self.camera.set_orientation(look / n)
            self.camera.eye = eye
        else:
            self._chase_eye = None

        # M orbit view: the camera rides to LEO and back — the SAME
        # world pass keeps rendering (the sphere hides under the Alps
        # at walking height; from up high the rings sit on the planet).
        if self.globe_mode != "off" and self.globe is not None:
            g_eye, g_fwd, g_up = self._globe_pose(dt_real)
            self.camera.fov_y = math.radians(BASE_FOV)
            self.camera.eye = g_eye
            self.camera.set_orientation(g_fwd, g_up)
            eye = g_eye
        # Sky -> space blend with camera altitude (ASL).
        mood = MOODS[self.mood_i]
        if self.globe_mode != "off":
            alt_asl = float(self.camera.eye[1]) + self.scene.origin_alt
            k = float(np.clip((alt_asl - 12_000.0) / 60_000.0, 0.0, 1.0))
            self._space_k = k
            r = self.app.renderer
            space = (0.004, 0.006, 0.012)
            r.haze_color = tuple(
                mc * (1.0 - k) + sc * k
                for mc, sc in zip(mood.haze_color, space))
            r.haze_density = mood.haze_density * (1.0 - k) + 1e-9 * k
        else:
            self._space_k = 0.0

        self.terrain.update(eye)
        self.trees.apply_craters(self.scene)
        self.app.renderer.alt_offset = self.scene.origin_alt
        self.app.renderer.begin(self.camera, w / max(h, 1))
        if self.clouds is not None and getattr(self.clouds, "enabled", True):
            self.clouds.bind_shadow_uniforms(self.app.renderer.lit, 6,
                                             self._cloud_camera(),
                                             self.cloud_time)
        else:
            self.app.renderer.lit.use()
            self.app.renderer.lit.set_float("u_cloud_amt", 0.0)
        # One continuous sky for the whole M ride: the dome keeps
        # drawing into orbit, thinning to black + stars via u_space_k
        # (the old hard cutoff at 0.55 left a bland flat clear color).
        self.sky.space_k = self._space_k
        self.sky.draw(self.app.renderer)
        if self.globe_mode != "off" and self.globe is not None:
            self.globe.draw(self.app.renderer, self.camera)
        self.terrain.draw(self.app.renderer, self.camera)
        self.trees.draw(self.app.renderer, self.camera, self.t)

        yaw_rot = math3d.rotation_from_forward(
            np.array([math.sin(self._pad_yaw + math.pi), 0.0,
                      math.cos(self._pad_yaw + math.pi)]))
        self.app.renderer.draw_mesh(self.tel_mesh, self._pad, yaw_rot)
        self._draw_silo()
        for m in self.launches:
            if m.done:
                continue
            fwd_v = m.axis if m.ignited else np.array([0.0, 1.0, 0.0])
            rot = math3d.rotation_from_forward(fwd_v)
            if isinstance(m, IcbmLaunch):
                if not m.rv_only:      # post-boost bus is metres long and
                    mesh = self.icbm_meshes.get(m.spec.id)   # tens of km up
                    if mesh is not None:
                        mid = m.pos + m.axis * (m.spec.length_m * 0.5)
                        self.app.renderer.draw_mesh(mesh, mid, rot)
                continue
            self.app.renderer.draw_mesh(self.missile_mesh, m.pos, rot)
        self.weapons.draw_world(self)
        if self.clouds is not None and self._space_k < 0.5:
            cloud_cam = self._cloud_camera()
            if hasattr(self.clouds, "using_v2"):
                self.clouds.draw(self.app.renderer, cloud_cam,
                                 self.cloud_time, view_id="cinematic")
            else:
                self.clouds.draw(self.app.renderer, cloud_cam,
                                 self.cloud_time)
        self.particles.draw(self.app.renderer, self.effects)
        self.overlay.draw(w / max(h, 1), self._zoom_fade)

        self._draw_hud(w, h)

    def _silo_draw_id(self):
        """Which compound stands at the surveyed site: an active bird's
        own silo wins (never yank the ground out from under the smoke),
        else the selected launcher's."""
        for m in self.launches:
            if isinstance(m, IcbmLaunch) and not m.done:
                return m.spec.id
        lid = LAUNCHERS[self.launcher_i][0]
        return lid if lid != "s300" else None

    def _draw_silo(self) -> None:
        sid = self._silo_draw_id()
        if sid is None or self._silo_site is None \
                or sid not in self.silo_meshes:
            return
        from models.icbm import (LF_DOOR_CLOSED_Z, LF_DOOR_OPEN_DZ,
                                 LF_DOOR_SIZE, LF_DOOR_Y,
                                 SAR_LID_H, SAR_LID_OPEN_DZ)
        fwd = np.array([math.sin(self._silo_yaw), 0.0,
                        math.cos(self._silo_yaw)])
        rot = math3d.rotation_from_forward(fwd)
        compound, door = self.silo_meshes[sid]
        self.app.renderer.draw_mesh(compound, self._silo_site, rot)
        frac = self._door_anim.get(sid, 0.0)
        if sid == "mm3":
            local = np.array([0.0, LF_DOOR_Y + LF_DOOR_SIZE[1] * 0.5,
                              LF_DOOR_CLOSED_Z + frac * LF_DOOR_OPEN_DZ])
        else:
            local = np.array([0.0, 1.5 + SAR_LID_H * 0.5,
                              frac * SAR_LID_OPEN_DZ])
        self.app.renderer.draw_mesh(door, self._silo_site + rot @ local,
                                    rot)

    # ------------------------------------------------------------- overlay

    def _screen_pos(self, w: int, h: int, world_pos):
        """Project a world point to pixels; None when behind the camera."""
        rel = np.asarray(world_pos, dtype=np.float64) - self.camera.eye
        clip = (self.camera.proj(w / max(h, 1))
                @ self.camera.view_rot() @ np.append(rel, 1.0))
        if clip[3] <= 0.05:
            return None
        return (float((clip[0] / clip[3] * 0.5 + 0.5) * w),
                float((1.0 - (clip[1] / clip[3] * 0.5 + 0.5)) * h))

    def _draw_spotter(self, w: int, h: int) -> bool:
        """The I-key aid: a hairline from screen center to the missile, a
        diamond on it, and a range/speed readout."""
        if not (self.spot and self.launch is not None
                and not self.launch.done):
            return False
        m = self.launch
        sp = self._screen_pos(w, h, m.pos)
        text = self.text
        cx, cy = w * 0.5, h * 0.5
        if sp is None:
            text.draw_text(cx - 60, 40, "MISSILE BEHIND YOU",
                           (*UI_ACC, 0.8), SMALL_SIZE)
            return True
        x, y = sp
        dx, dy = x - cx, y - cy
        dist_px = math.hypot(dx, dy)
        if dist_px > 26.0:
            # Stop the line short of the diamond so it never covers it.
            t0 = 18.0 / dist_px
            t1 = 1.0 - 14.0 / dist_px
            text.draw_lines([(cx + dx * t0, cy + dy * t0),
                             (cx + dx * t1, cy + dy * t1)],
                            (*UI_ACC, 0.55), 1.0)
        s = 9.0
        text.draw_lines([(x, y - s), (x + s, y), (x, y + s), (x - s, y),
                         (x, y - s)], (*UI_ACC, 0.95), 1.0)
        rng_km = float(np.linalg.norm(
            m.pos - np.asarray(self._eye()))) / 1000.0
        mach = float(np.linalg.norm(m.vel)) / 320.0
        label = f"{m.variant.label}  {rng_km:.1f} KM  M{mach:.1f}"
        text.draw_text(x + 14, y - 8, label, (*UI_ACC, 0.9), SMALL_SIZE)
        return True

    def _draw_target_marker(self, w: int, h: int) -> None:
        """Every designated aim point: warm diamonds + range tags
        (MIRV weapons can hold several marks)."""
        marks = self.icbm_targets or (
            [self.icbm_target] if self.icbm_target is not None else [])
        if not marks:
            return
        text = self.text
        col = (1.0, 0.62, 0.30)
        for i, mark in enumerate(marks):
            sp = self._screen_pos(w, h, mark + np.array([0.0, 2.0, 0.0]))
            if sp is None:
                continue
            x, y = sp
            s = 7.0
            text.draw_lines([(x, y - s), (x + s, y), (x, y + s),
                             (x - s, y), (x, y - s)], (*col, 0.95), 1.0)
            text.draw_lines([(x, y - s - 6), (x, y - s - 14)],
                            (*col, 0.7), 1.0)
            rng_km = float(np.linalg.norm(
                mark - np.asarray(self._eye()))) / 1000.0
            tag = (f"TGT {i + 1} {rng_km:.1f} KM" if len(marks) > 1
                   else f"TGT {rng_km:.1f} KM")
            text.draw_text(x + 12, y + 6, tag, (*col, 0.9), SMALL_SIZE)

    def _draw_hud(self, w: int, h: int) -> None:
        text = self.text
        drew = self._draw_spotter(w, h)
        self._draw_target_marker(w, h)
        if not self.ui_open:
            if LAUNCHERS[self.launcher_i][0] != "s300":
                hint = ("AIM + T SETS TARGET   L LAUNCHES"
                        if self.icbm_target is None else
                        "L LAUNCHES   C CHASE CAM   . TIME WARP")
                text.draw_text(28, h - 30, hint, (*UI_DIM, 0.85),
                               SMALL_SIZE)
            elif self.icbm_target is not None:
                text.draw_text(28, h - 30,
                               "L FLIES TO YOUR MARK   T MOVES IT",
                               (*UI_DIM, 0.85), SMALL_SIZE)
        fade = 1.0 - max(0.0, min(1.0, (self.t - 5.0) / 2.0))
        if fade > 0.0:
            title = self.scene.title
            tw = text.text_width(title, HEADER_SIZE)
            text.draw_text((w - tw) * 0.5, int(h * 0.78), title,
                           (*UI_TXT, fade), HEADER_SIZE)
            sub = self.scene.subtitle
            sw = text.text_width(sub, SMALL_SIZE)
            text.draw_text((w - sw) * 0.5, int(h * 0.78) + 34, sub,
                           (*UI_ACC, fade), SMALL_SIZE)
            cred = self.scene.attribution
            cw = text.text_width(cred, SMALL_SIZE)
            text.draw_text((w - cw) * 0.5, h - 30, cred,
                           (*UI_DIM, fade * 0.9), SMALL_SIZE)
            drew = True
        hint_fade = 1.0 - max(0.0, min(1.0, (self.t - 11.0) / 2.0))
        if self.t > 6.0 and hint_fade > 0.0:
            hint = ("WASD WALK   WHEEL BINOCULARS   I SPOTTER   F FREECAM"
                    "   G DIRECTOR   F1 WEAPONS   K ROUND   L LAUNCH"
                    "   M ORBIT   ESC EXIT")
            hw = text.text_width(hint, SMALL_SIZE)
            text.draw_text((w - hw) * 0.5, h - 56, hint,
                           (*UI_DIM, hint_fade), SMALL_SIZE)
            drew = True
        if self.freecam or self.globe_mode == "orbit":
            # Center marker: a dot + four ticks (teleport / orbit aim).
            cx, cy = w // 2, h // 2
            text.draw_rect(cx - 2, cy - 2, 4, 4, (*UI_ACC, 1.0))
            for dx, dy, rw, rh in ((-14, -1, 8, 2), (7, -1, 8, 2),
                                   (-1, -14, 2, 8), (-1, 7, 2, 8)):
                text.draw_rect(cx + dx, cy + dy, rw, rh, (*UI_ACC, 0.85))
            drew = True
        if self.globe_mode == "orbit":
            text.draw_text(28, h - 56,
                           f"ORBIT {self.globe_alt / 1000.0:6.0f} KM   "
                           f"{self.globe_lat:6.2f}N {self.globe_lon:6.2f}E",
                           (*UI_ACC, 0.9), SMALL_SIZE)
            text.draw_text(28, h - 30,
                           "DRAG PANS   WHEEL ALT   T MARKS CENTER   "
                           "L LAUNCHES   M RETURNS",
                           (*UI_DIM, 0.85), SMALL_SIZE)
            if self.globe is not None:
                cred = self.globe.attribution
                cw = text.text_width(cred, SMALL_SIZE)
                text.draw_text(w - cw - 24, h - 30, cred,
                               (*UI_DIM, 0.6), SMALL_SIZE)
            drew = True
        if self._toast_left > 0.0:
            a = min(1.0, self._toast_left / 0.4)
            tw = text.text_width(self._toast, BODY_SIZE)
            text.draw_rect((w - tw) * 0.5 - 14, int(h * 0.86) - 8,
                           tw + 28, 34, (*UI_GLASS_SOFT[:3], 0.55 * a))
            text.draw_text((w - tw) * 0.5, int(h * 0.86), self._toast,
                           (*UI_TXT, a), BODY_SIZE)
            drew = True
        if self.weapons.draw_hud(self, w, h):
            drew = True
        if self.ui_open:
            self._draw_director(w, h)
            drew = True
        if drew:
            text.flush(w, h)

    # -------------------------------------------------------- director UI

    def _rows(self):
        """(kind, index, label, blurb, selected) for every director row."""
        rows = []
        from world.cinematic_scene import list_scenes
        for i, (_n, title, _sub, sdir) in enumerate(list_scenes()):
            rows.append(("scene", i, title, "",
                         sdir.replace("\\", "/") ==
                         self.scene_dir.replace("\\", "/")))
        for i, (lid, label, blurb) in enumerate(LAUNCHERS):
            rows.append(("launcher", i, label, blurb,
                         i == self.launcher_i))
        for i, v in enumerate(VARIANTS):
            rows.append(("round", i, v.label, v.blurb,
                         v.id == self.variant.id))
        for i, m in enumerate(MOODS):
            rows.append(("light", i, m.label, "", i == self.mood_i))
        for i, (_pid, label) in enumerate(SKIES):
            rows.append(("sky", i, label, "", i == self.sky_i))
        return rows

    def _draw_director(self, w: int, h: int) -> None:
        text = self.text
        pw = 384
        x0 = w - pw - 36
        y0 = 42
        y1 = h - 42
        text.draw_rect(x0, y0, pw, y1 - y0, UI_GLASS)
        text.draw_rect(x0, y0, pw, 1, UI_HAIR)
        text.draw_rect(x0, y1 - 1, pw, 1, UI_HAIR)
        text.draw_rect(x0, y0, 1, y1 - y0, UI_HAIR)
        text.draw_rect(x0 + pw - 1, y0, 1, y1 - y0, UI_HAIR)
        x = x0 + 26
        text.draw_text(x, y0 + 20, "DIRECTOR", UI_TXT, HEADER_SIZE,
                       scale=1.25)
        text.draw_text(x, y0 + 52, self.scene.title, UI_ACC, SMALL_SIZE)
        text.draw_rect(x, y0 + 76, pw - 52, 1, UI_HAIR)

        headers = {"scene": "LOCATION", "launcher": "LAUNCHER",
                   "round": "ROUND", "light": "LIGHT", "sky": "SKY"}
        self._ui_rects = []
        y = y0 + 92
        last_kind = None
        mx, my = pygame.mouse.get_pos()
        for kind, i, label, blurb, selected in self._rows():
            if kind != last_kind:
                if last_kind is not None:
                    y += 10
                text.draw_text(x, y, headers[kind], UI_DIM, SMALL_SIZE)
                y += 24
                last_kind = kind
            row_h = 40 if blurb else 28
            rect = (x0 + 14, y - 4, x0 + pw - 14, y - 4 + row_h)
            self._ui_rects.append((kind, i, rect))
            hovered = (rect[0] <= mx <= rect[2]
                       and rect[1] <= my <= rect[3])
            if selected:
                text.draw_rect(rect[0], rect[1], 2, row_h, (*UI_ACC, 0.95))
            if hovered and not selected:
                text.draw_rect(rect[0], rect[1], rect[2] - rect[0], row_h,
                               (1.0, 1.0, 1.0, 0.05))
            col = UI_TXT if (selected or hovered) else UI_DIM
            text.draw_text(x + 12, y, label, col, BODY_SIZE)
            if blurb:
                text.draw_text(x + 12, y + 19, blurb,
                               (*UI_DIM, 0.85), SMALL_SIZE)
            y += row_h + 2
        text.draw_text(x, y1 - 30,
                       "CLICK TO APPLY   G OR ESC CLOSES",
                       (*UI_DIM, 0.9), SMALL_SIZE)

    def _ui_event(self, ev) -> None:
        if ev.type != pygame.MOUSEBUTTONDOWN or ev.button != 1:
            return
        pos = getattr(ev, "pos", (0, 0))
        for kind, i, rect in self._ui_rects:
            if not (rect[0] <= pos[0] <= rect[2]
                    and rect[1] <= pos[1] <= rect[3]):
                continue
            if kind == "launcher":
                self.launcher_i = i
                lid, label, _b = LAUNCHERS[i]
                if lid != "s300" and self.icbm_target is None:
                    self._say(f"{label} - AIM + T TO SET A TARGET")
                else:
                    self._say(label)
            elif kind == "round":
                self.variant = VARIANTS[i]
                self._say(f"ROUND {self.variant.label}")
            elif kind == "light":
                self.mood_i = i
                self._apply_mood()
                self._say(f"LIGHT {MOODS[i].label}")
            elif kind == "sky":
                self.sky_i = i
                self._apply_sky()
            elif kind == "scene":
                from world.cinematic_scene import list_scenes
                scenes = list_scenes()
                if i < len(scenes):
                    sdir = scenes[i][3]
                    if sdir.replace("\\", "/") != \
                            self.scene_dir.replace("\\", "/"):
                        self.app.open_cinematic(sdir)
            return
