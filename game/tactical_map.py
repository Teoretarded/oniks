"""Full-world tactical map: zoom/pan view, terrain texture, contact picture,
route planning and launch (opened with M from the sandbox).

Layered like engine.text (LOCKED test convention): the module itself is
GL-free — ``MapView`` (world<->screen transform), ``pick_contact`` and the
waypoint helpers are pure and unit-tested headless; ``build_map_pixels``
colorizes ``terrain_height`` with plain numpy. Only ``TacticalMap.__init__``
imports OpenGL (texture + one textured background quad); every overlay is
queued through the sandbox's shared ``TextRenderer``.

Screen coords: origin top-left, pixels. World: X = east (right), Z = north
(up on the map). All world math float64.
"""

from __future__ import annotations

import hashlib
import math
import os
import threading

import numpy as np
import pygame

from engine.text import BODY_SIZE, HEADER_SIZE
from sim.arsenal import ONIKS, S300
from sim.sam import SamMissile
from world.generation import (BASE_POS, DEFAULT_FIELD, LANES, SAM_SITE_POS,
                              SEED, SITES, terrain_height,
                              terrain_height_scalar)

# --- Map texture extent (plan-fixed) ------------------------------------------

MAP_TEX_N = 1024               # texels per side of the colorized height grid
MAP_X_MIN, MAP_X_MAX = -350_000.0, 350_000.0
MAP_Z_MIN, MAP_Z_MAX = -50_000.0, 560_000.0

# --- View tuning ---------------------------------------------------------------

ZOOM_MIN_MPP = 12.0            # m/px, plan-fixed zoom clamp (closest)
ZOOM_MAX_MPP = 800.0           # m/px, plan-fixed zoom clamp (widest)
ZOOM_STEP = 1.3                # mpp factor per wheel notch
FIT_MARGIN = 1.06              # first-open view: whole world + 6% border
PAN_KEY_PX_S = 900.0           # arrow-key pan speed, screen px per real second

PICK_RADIUS_PX = 14.0          # plan-fixed contact click-pick radius
MAX_WAYPOINTS = 8              # planned-route waypoint cap (RMB appends refuse)

# --- Overlay tuning ------------------------------------------------------------

TRAIL_SPACING_M = 1_500.0      # min world distance between missile trail dots
CONTACT_FADE_S = 120.0         # contact age at which the triangle is fully dim
CONTACT_MIN_ALPHA = 0.35       # faded floor (still visible)
RING_SPACING_M = 100_000.0     # range rings every 100 km around base
RING_COUNT = 6                 # out to 600 km (covers the enemy coast)
RING_SEGMENTS = 128
SEEKER_ARC_SEGMENTS = 16

BACKDROP_RGBA = (0.01, 0.02, 0.02, 0.78)     # dims the 3D scene behind the map
MAP_ALPHA = 0.96                             # terrain texture opacity

# Wardroom Dusk (spec §2 world / §7 symbology + the color LAW): hostile
# contacts dusk-red (age = opacity), beliefs teal, own-force truth green,
# brass strictly for selection + the player's aim/plan.
LANE_COL = (0.106, 0.227, 0.259, 0.60)       # bathymetry-toned lane polylines
RING_COL = (0.165, 0.290, 0.278, 0.85)       # range rings #2A4A47
RING_TEXT_COL = (0.431, 0.541, 0.502, 0.75)  # ring labels — faint
SAM_RING_COL = (0.541, 0.435, 0.208, 0.60)   # engagement ring — brass-dim
SAM_LOW_RING_M = 22_000.0    # m — MEASURED 48N6 kill reach vs a 50 m skimmer
#                              (tools/probe_s300_vs_tomahawk.py: kill at 20 km,
#                              energy-dead at 35+; the dashed honesty ring)
SITE_COL = (0.910, 0.416, 0.290, 0.95)       # enemy land sites — hostile
BASE_COL = (0.624, 0.851, 0.541, 0.95)       # player platform stars — own
PLATFORM_DIM = 0.55                          # inactive platform star fade
CONTACT_COL = (0.910, 0.416, 0.290)          # contact triangles — hostile
#                                              (age fades ALPHA, the aged-
#                                               contact idiom of mock 01)
SELECT_COL = (0.910, 0.722, 0.294, 1.00)     # selected-contact ring — brass
MISSILE_COL = (0.624, 0.851, 0.541, 1.00)    # live missile diamonds — own
MISSILE_ROUTE_COL = (0.624, 0.851, 0.541, 0.30)  # missile's remaining route
TRAIL_COL = (0.750, 0.900, 0.690, 0.75)      # missile trail dots
PLAN_COL = (0.541, 0.435, 0.208, 0.80)       # planned waypoint chain — brass-dim
TARGET_COL = (0.910, 0.722, 0.294, 1.00)     # target cross — the player's AIM
SEEKER_COL = (0.910, 0.722, 0.294, 0.40)     # seeker-basket cone preview
HEADER_COL = (0.910, 0.722, 0.294, 1.0)      # brass
STATUS_COL = (0.937, 0.902, 0.816, 1.0)      # warm cream
ARMED_COL = (0.624, 0.851, 0.541, 1.0)
RELOAD_COL = (0.851, 0.643, 0.255, 1.0)
HINT_COL = (0.541, 0.478, 0.298, 0.95)       # hint-bar text
PANEL_RGBA = (0.051, 0.071, 0.063, 0.88)     # over-map plate ink

# Phase 4 — recon drone + ELINT overlays. The drone draws at its TRUE
# position (friendly telemetry, not a contact) in the OWN-FORCE green
# family (color LAW; mock 01: green diamond outline + orbit) — glyph SHAPE
# separates it from an own missile, hue separates it from any contact.
DRONE_COL = (0.624, 0.851, 0.541, 1.00)      # drone diamond
DRONE_DEAD_COL = (0.624, 0.851, 0.541, 0.45)  # falling wreck, dimmed
DRONE_ROUTE_COL = (0.624, 0.851, 0.541, 0.35)  # tasked route polyline
ELINT_RAY_COL = (0.494, 0.831, 0.816, 0.22)  # bearing rays — BELIEF teal
ELINT_CIRCLE_COL = (0.494, 0.831, 0.816, 0.50)  # fix circles — BELIEF teal
ELINT_RAY_LEN_M = 250_000.0    # ray length: a bearing has no range; long
#                                enough to cross the whole battlespace
ELINT_CIRCLE_MAX_M = 30_000.0  # only draw circles once the fix error is
#                                inside this (else the circle is just noise
#                                filling the map)
ELINT_CIRCLE_SEGMENTS = 48
DRONE_DIAMOND_PX = 7.0
DRONE_RECON_HINT = "DRONE: RECON ONLY"       # LMB/SPACE with drone active

# M2-T4 — localized enemy EMITTER glyphs (the player's passive-SIGINT picture,
# world.emitter_contacts).  Rendered in the SENSOR-ESTIMATE idiom (a faded
# diamond-in-ring), distinct from friendly cyan/green and from the amber
# ship/air contact symbols, so the player reads them as a BELIEF (fog-honest
# est_pos), never as friendly truth.  The uncertainty ring reuses the ELINT
# circle colour/segments; the diamond reuses the ELINT estimate hue.
EMITTER_COL = ELINT_CIRCLE_COL               # BELIEF teal (never truth)
EMITTER_SEL_COL = (0.910, 0.722, 0.294, 0.95)  # brass ring when ARM-selected
EMITTER_DIAMOND_PX = 6.0
EMITTER_RING_PX = 11.0                        # minimum on-screen ring radius
EMITTER_RING_SEGMENTS = ELINT_CIRCLE_SEGMENTS

# M5 ASW (UI-wiring pass) — sonobuoys are PLAYER-OWNED truth (cyan family,
# like the drone); subsurface contacts (world.sub_contacts) are ACOUSTIC
# BELIEF (estimate-violet family, like ELINT/SIGINT): an inverted chevron at
# the est_pos + an uncertainty circle from the fix quality.  A 'datum' kind
# (the launch-transient back-plot) draws dimmer than a buoy cross-fix.  ASW
# rounds in flight are own-force truth (missile green, small).
BUOY_COL = (0.624, 0.851, 0.541, 0.80)       # sonobuoy cross + ring — own
BUOY_PX = 4.0
SUB_FIX_COL = (0.494, 0.831, 0.816, 0.85)    # cross-fix chevron — BELIEF teal
SUB_DATUM_COL = (0.494, 0.831, 0.816, 0.45)  # stale datum chevron, dimmed
SUB_CHEVRON_PX = 7.0
SUB_CIRCLE_MAX_M = 30_000.0                  # same clutter gate as ELINT
ASW_ROUND_COL = (0.624, 0.851, 0.541, 0.95)  # own prosecution round
ASW_ROUND_PX = 4.0
BUOY_ARMED_TEXT = "BUOY DROP ARMED"          # chrome tag while modal

# M3-F5 — the JAMMED corridor band + shrunken effective ring.  Drawn from the
# SENSOR-BELIEVED jammer fix/bearing the sim publishes into world.ew_state
# (FOG / NO CHEAT — never a real jammer's truth).  Reuses the existing belief
# token (ELINT_CIRCLE_COL / EMITTER_COL, the estimate-violet hue already used for
# the SIGINT picture) so the corridor reads as a BELIEF overlay, not friendly
# truth — the same idiom, drawn as a dashed/translucent variant via an alpha
# tweak only (no new hard-coded hue).  The wedge is a corridor from the believed
# jammer toward the DEFENDED BASE (the threat axis — see _jam_overlay axis calc,
# NOT "toward the coast"); the player net's collapsed effective ring is a DASHED
# circle (vs the solid clear range ring).
JAM_WEDGE_EDGE_COL = (*ELINT_CIRCLE_COL[:3], 0.45)  # belief idiom, translucent
#                                                     corridor edge polyline
JAM_RING_COL = (*ELINT_CIRCLE_COL[:3], 0.55)        # belief idiom, dashed
#                                                     shrunken effective ring
JAM_BEAMWIDTH_RAD = math.radians(22.0)        # fixed corridor half-angle * 2 (a
#                                               readable beamwidth, not an RF
#                                               datum) — narrows as the player
#                                               kills/closes the jammer is a
#                                               later polish; fixed for now
JAM_WEDGE_LEN_M = 600_000.0     # corridor length: across the whole battlespace
#                                 (a bearing/standoff jammer has no near edge)
JAM_RING_SEGMENTS = 64          # dashed-ring resolution (even -> clean dashes)
JAM_RING_DASH = 2               # draw every-other segment -> a dashed circle

SITE_HALF_PX = 5.0             # site square icon half-size
BASE_STAR_PX = 8.0             # base star spoke length
# Phase 6 — Pantsir SHORAD markers: small friendly diamonds near the base
# (point-defense nodes, distinct from the 8-spoke platform stars).  A dead
# unit dims to the DEAD alpha.
PANTSIR_COL = (0.624, 0.851, 0.541, 0.95)    # friendly point-defense green
PANTSIR_DEAD_COL = (0.624, 0.851, 0.541, 0.35)  # destroyed unit, dimmed
PANTSIR_DIAMOND_PX = 5.0
CONTACT_NOSE_PX = 9.0          # contact triangle: nose ahead of the estimate
CONTACT_BACK_PX = 5.0          # ... base behind it
CONTACT_HALF_PX = 5.0          # ... base half-width
AIR_DIAMOND_PX = 6.0           # air contact diamond half-size (Task S4)
SELECT_RING_PX = 11.0
MISSILE_DIAMOND_PX = 6.0
WAYPOINT_PX = 4.0              # waypoint diamond half-size
TARGET_CROSS_PX = 7.0
TRAIL_DOT_PX = 3.0
HINT_MARGIN = 10               # px from the bottom edge (matches the HUD)
INTEL_PANEL_X = 16             # px, docked contact-intel panel (top-left under
INTEL_PANEL_Y = 96             #     the map title; M1 click-contact inspector)

MAP_HINT = ("LMB target/missile  RMB waypoint  X clear  SPACE launch  "
            "TAB platform  WHEEL zoom  MMB/arrows pan  M close")

# Task RTG: refusal flash when a selected round can no longer be redirected.
COMMITTED_HINT = "COMMITTED"
SAM_NO_WAYPOINTS_HINT = "S-300: NO WAYPOINTS"
ONIKS_AIR_HINT = "ONIKS HITS SHIPS - TAB TO S-300 FOR AIR"

# --- Terrain colorize ramps (uint8 RGB endpoints) ------------------------------

WATER_DEEP = (8.0, 24.0, 54.0)
WATER_SHALLOW = (38.0, 92.0, 128.0)
WATER_FULL_DEPTH = 140.0       # m down at which the deep ramp saturates
SHORE_WATER = (96.0, 162.0, 168.0)           # bright shallow rim
SHORE_WATER_DEPTH = 4.0        # m of water that reads as shoreline
LAND_LOW = (58.0, 92.0, 54.0)
LAND_HIGH = (124.0, 100.0, 70.0)
LAND_FULL_HEIGHT = 145.0       # m up at which the brown ramp saturates
SAND = (166.0, 153.0, 116.0)
SAND_HEIGHT = 2.5              # m of land that reads as beach


def build_map_pixels(n: int = MAP_TEX_N, height_fn=terrain_height) -> np.ndarray:
    """Colorize the heightfield on an n x n grid over the map extent.

    Returns (n, n, 3) uint8, row 0 = north (z = MAP_Z_MAX), so it uploads
    directly as a GL texture with v=0 at the top of the map quad. Pure numpy.

    ``height_fn`` defaults to the module ``terrain_height`` (the default map,
    byte-identical for the cached texture); a caller can pass an active preset
    field's vectorized ``height`` to colorize a preset map.
    """
    xs = np.linspace(MAP_X_MIN, MAP_X_MAX, n)
    zs = np.linspace(MAP_Z_MAX, MAP_Z_MIN, n)          # row 0 = north
    h = height_fn(xs[None, :], zs[:, None])

    def lerp(c0, c1, t):
        t = np.clip(t, 0.0, 1.0)[..., None]
        return np.asarray(c0) + (np.asarray(c1) - np.asarray(c0)) * t

    img = np.empty(h.shape + (3,), dtype=np.float64)
    water = h < 0.0
    # Ocean blues: gamma < 1 keeps shelf/seabed variation visible near shore.
    tw = np.clip(-h / WATER_FULL_DEPTH, 0.0, 1.0) ** 0.7
    img[water] = lerp(WATER_SHALLOW, WATER_DEEP, tw)[water]
    # Land greens -> browns by height.
    img[~water] = lerp(LAND_LOW, LAND_HIGH, h / LAND_FULL_HEIGHT)[~water]
    # Shoreline highlight: bright shallow rim + a beach line on the land side.
    rim = water & (h > -SHORE_WATER_DEPTH)
    img[rim] = lerp(SHORE_WATER, WATER_SHALLOW,
                    -h / SHORE_WATER_DEPTH)[rim]
    img[~water & (h < SAND_HEIGHT)] = SAND
    return np.clip(img + 0.5, 0.0, 255.0).astype(np.uint8)


# --- Async map-pixel build with a disk cache ------------------------------------
#
# build_map_pixels measures seconds even with the masked terrain_height — far
# too long to run on the main thread when M is first pressed (the app went
# "Not Responding" for the whole build: user bug report 2026-06-12). The
# pixels are field-fixed, so: build ONCE per active field in a daemon thread
# (kicked off at sandbox construction, while the BUILDING WORLD frame shows),
# cache the result to disk keyed by field/size, and have the map draw a
# BUILDING MAP placeholder on the rare early M press. Module-level so a sandbox
# restart reuses the array.
#
# M3-F4 FOG FIX: the build is now keyed on the ACTIVE map field, not just the
# module SEED — a seeded preset (world.height_field != DEFAULT_FIELD) colorizes
# its OWN island terrain and caches/loads under its own key, so the 2D map
# shows the SAME field the sim masks LOS with (no perception/fog mismatch).
# The DEFAULT field keeps the EXACT legacy key/path -> the out-of-the-box
# (preset 0) map texture is byte-identical (the cached .npy is reused unchanged).

_pixels_lock = threading.Lock()
# key (see _field_key) -> built (n, n, 3) uint8 array.
_pixels_by_key: dict[object, np.ndarray] = {}
# key -> the daemon thread currently building it (at most one per key).
_pixels_threads: dict[object, threading.Thread] = {}


def _field_key(field):
    """A stable, hashable cache key for the active map ``field`` (or None == the
    default field).  The DEFAULT field returns None so it reuses the EXACT
    legacy in-memory slot + disk path (preset 0 byte-identical).  A preset field
    keys on the terrain that distinguishes its colorized pixels: the field seed,
    its per-field max ceiling and its island list (the only inputs that move a
    texel vs the default coast/floor noise)."""
    if field is None or field is DEFAULT_FIELD:
        return None
    islands = tuple(tuple(float(c) for c in isl) for isl in field.islands)
    return (int(field.seed), float(field.max_height), islands)


def _map_cache_path(key) -> str:
    """Disk path for a built map array.  ``key is None`` (the default field)
    returns the EXACT legacy filename so the out-of-the-box map texture loads
    byte-identically; a preset key hashes to its own stable filename."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if key is None:
        name = f"map_pixels_v1_seed{SEED}_{MAP_TEX_N}.npy"
    else:
        # Deterministic, filesystem-safe digest of the field key (so the same
        # preset+seed reuses one file across restarts).
        digest = hashlib.sha1(repr(key).encode("utf-8")).hexdigest()[:16]
        name = f"map_pixels_v1_preset_{digest}_{MAP_TEX_N}.npy"
    return os.path.join(root, "cache", name)


def _build_or_load_pixels(key, height_fn) -> None:
    path = _map_cache_path(key)
    px = None
    try:
        arr = np.load(path)
        if arr.shape == (MAP_TEX_N, MAP_TEX_N, 3) and arr.dtype == np.uint8:
            px = arr
    except (OSError, ValueError):
        px = None                       # missing/corrupt cache: rebuild
    if px is None:
        px = build_map_pixels(height_fn=height_fn)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            np.save(path, px)
        except OSError:
            pass                        # cache is an optimization, never fatal
    with _pixels_lock:
        _pixels_by_key[key] = px


def ensure_map_pixels_async(field=None) -> None:
    """Start (at most one) background build/load of ``field``'s map pixel array.

    ``field`` is the active ``HeightField`` (``world.height_field``); None or the
    default field builds the byte-identical default map.  Idempotent per field:
    a second call for an already-built / in-flight field is a no-op."""
    key = _field_key(field)
    height_fn = (DEFAULT_FIELD.height if key is None else field.height)
    with _pixels_lock:
        if key in _pixels_by_key:
            return
        t = _pixels_threads.get(key)
        if t is not None and t.is_alive():
            return
        t = threading.Thread(target=_build_or_load_pixels,
                             args=(key, height_fn), daemon=True,
                             name="map-pixels-build")
        _pixels_threads[key] = t
        t.start()


def get_map_pixels(field=None):
    """The (n, n, 3) uint8 map array for ``field``, or None while still building.

    ``field`` is the active ``HeightField`` (None == the default map)."""
    with _pixels_lock:
        return _pixels_by_key.get(_field_key(field))


# --------------------------------------------------------------- pure view

class MapView:
    """World (x, z) <-> screen (px) transform with zoom + pan (pure, tested).

    Screen origin top-left; the view is centered on ``center_xz`` (float64)
    at ``meters_per_px`` scale, north up, east right.
    """

    def __init__(self, screen_w: float, screen_h: float,
                 center_xz=(0.0, (MAP_Z_MIN + MAP_Z_MAX) * 0.5),
                 meters_per_px: float = 400.0):
        self.screen_w = float(screen_w)
        self.screen_h = float(screen_h)
        self.center_xz = np.array(center_xz, dtype=np.float64)
        self.meters_per_px = float(np.clip(meters_per_px,
                                           ZOOM_MIN_MPP, ZOOM_MAX_MPP))

    def resize(self, screen_w: float, screen_h: float) -> None:
        self.screen_w = float(screen_w)
        self.screen_h = float(screen_h)

    def world_to_screen(self, xz) -> tuple:
        """World (x, z) -> screen (sx, sy) pixels (floats)."""
        mpp = self.meters_per_px
        return (self.screen_w * 0.5 + (float(xz[0]) - self.center_xz[0]) / mpp,
                self.screen_h * 0.5 - (float(xz[1]) - self.center_xz[1]) / mpp)

    def screen_to_world(self, px) -> np.ndarray:
        """Screen (sx, sy) pixels -> world (x, z) float64."""
        mpp = self.meters_per_px
        return np.array(
            [self.center_xz[0] + (float(px[0]) - self.screen_w * 0.5) * mpp,
             self.center_xz[1] + (self.screen_h * 0.5 - float(px[1])) * mpp])

    def zoom_at(self, cursor_px, factor: float) -> None:
        """Scale meters_per_px by ``factor`` (clamped), keeping the world
        point under ``cursor_px`` fixed on screen."""
        anchor = self.screen_to_world(cursor_px)
        self.meters_per_px = float(np.clip(self.meters_per_px * factor,
                                           ZOOM_MIN_MPP, ZOOM_MAX_MPP))
        mpp = self.meters_per_px
        self.center_xz[0] = anchor[0] - (float(cursor_px[0])
                                         - self.screen_w * 0.5) * mpp
        self.center_xz[1] = anchor[1] - (self.screen_h * 0.5
                                         - float(cursor_px[1])) * mpp
        self._clamp_center()

    def pan_px(self, dx: float, dy: float) -> None:
        """Shift the view by (dx, dy) screen pixels (+dx looks east, +dy
        looks south). An MMB drag passes the negated mouse delta."""
        self.center_xz[0] += dx * self.meters_per_px
        self.center_xz[1] -= dy * self.meters_per_px
        self._clamp_center()

    def _clamp_center(self) -> None:
        """Keep the view center inside the mapped world (can't get lost)."""
        self.center_xz[0] = float(np.clip(self.center_xz[0],
                                          MAP_X_MIN, MAP_X_MAX))
        self.center_xz[1] = float(np.clip(self.center_xz[1],
                                          MAP_Z_MIN, MAP_Z_MAX))


# ------------------------------------------------------------ pure helpers

def pick_contact(view: MapView, board, sim_time: float, mouse_px,
                 air_only=None):
    """contact_id of the track whose dead-reckoned position is nearest to
    ``mouse_px`` within PICK_RADIUS_PX, else None.

    air_only (Task S4 platform filter): True picks only air tracks (S-300
    active), False only surface tracks (Bastion active), None all.
    """
    best, best_d = None, PICK_RADIUS_PX
    for sid, track in board.tracks.items():
        if air_only is not None and bool(track.get("is_air")) != air_only:
            continue
        est = board.estimated_pos(sid, sim_time)
        sx, sy = view.world_to_screen((est[0], est[2]))
        d = float(np.hypot(sx - float(mouse_px[0]), sy - float(mouse_px[1])))
        if d <= best_d:
            best, best_d = sid, d
    return best


def pick_missile(view: MapView, missiles, mouse_px, include_hostile=False):
    """The live missile whose diamond is nearest to ``mouse_px`` within
    PICK_RADIUS_PX, else None (Task RTG selection). By default only own rounds
    are pickable; probe code can opt into hostile rounds explicitly. Pick PRIORITY over
    contacts is structural: ``TacticalMap._click_target`` tries missiles
    before the contact/coordinate flow."""
    best, best_d = None, PICK_RADIUS_PX
    for m in missiles:
        if not getattr(m, "alive", True):
            continue
        if getattr(m, "is_hostile", False) and not include_hostile:
            continue
        sx, sy = view.world_to_screen((m.pos[0], m.pos[2]))
        d = float(np.hypot(sx - float(mouse_px[0]), sy - float(mouse_px[1])))
        if d <= best_d:
            best, best_d = m, d
    return best


def pick_emitter(view: MapView, emitter_contacts, mouse_px):
    """emitter_id of the LOCALIZED emitter (world.emitter_contacts) whose
    est_pos belief is nearest to ``mouse_px`` within PICK_RADIUS_PX, else None
    (M2-T4 ARM target selection).  Pure / GL-free — mirrors ``pick_contact``.

    FOG / NO CHEAT: the pick resolves at the SIGINT ``pos`` (the drone's
    triangulated belief, the SAME vector the emitter glyph renders), never a
    radar truth position.  An empty picture or a miss returns None."""
    best, best_d = None, PICK_RADIUS_PX
    for eid, c in emitter_contacts.items():
        pos = c["pos"]
        sx, sy = view.world_to_screen((float(pos[0]), float(pos[2])))
        d = float(np.hypot(sx - float(mouse_px[0]), sy - float(mouse_px[1])))
        if d <= best_d:
            best, best_d = eid, d
    return best


def contact_symbol(track) -> str:
    """'air' (diamond + altitude tag) or 'surface' (course triangle)."""
    return "air" if track.get("is_air") else "surface"


def air_alt_text(alt_m: float) -> str:
    """The map's altitude tag next to an air diamond: 6500 -> '6.5k'."""
    return f"{alt_m / 1000.0:.1f}k"


def ground_aim_point(xz) -> np.ndarray:
    """Aim point (3,) float64 for a plain-coordinate map click: y at the
    local surface, so the terminal dive on an elevated land site aims at
    the ground there instead of at y = 0 underneath it (Task 23 spec
    acceptance: land targets explode). Sea level over water."""
    x, z = float(xz[0]), float(xz[1])
    return np.array([x, max(terrain_height_scalar(x, z), 0.0), z])


def add_waypoint(waypoints: list, xz) -> bool:
    """Append world (x, z) to the planned route; refuse when full."""
    if len(waypoints) >= MAX_WAYPOINTS:
        return False
    waypoints.append((float(xz[0]), float(xz[1])))
    return True


def clear_waypoints(waypoints: list) -> None:
    waypoints.clear()


# ----------------------------------------------------------------- GL side

MAP_VERT = """
#version 330 core
layout(location=0) in vec2 a_pos;   // screen pixels, origin top-left
layout(location=1) in vec2 a_uv;
uniform vec2 u_screen;
out vec2 v_uv;
void main(){
    vec2 ndc = vec2(a_pos.x * 2.0 / u_screen.x - 1.0,
                    1.0 - a_pos.y * 2.0 / u_screen.y);
    gl_Position = vec4(ndc, 0.0, 1.0);
    v_uv = a_uv;
}
"""

MAP_FRAG = """
#version 330 core
in vec2 v_uv;
uniform sampler2D u_tex;
uniform float u_alpha;
out vec4 frag;
void main(){ frag = vec4(texture(u_tex, v_uv).rgb, u_alpha); }
"""


class TacticalMap:
    """The M-key map screen: dims the 3D scene, draws the terrain texture
    through its own tiny shader, then queues every overlay on the sandbox's
    shared TextRenderer. GL-touching (init only) — never imported by tests."""

    def __init__(self, sandbox):
        import ctypes

        import OpenGL.GL as gl

        from engine.shader import Shader
        self._gl = gl
        self.sandbox = sandbox
        self.text = sandbox.text
        self.view: MapView | None = None     # sized at first draw
        self.selected_contact = None         # ship_id the target tracks
        self.selected_missile = None         # own round LMB-selected (RTG)
        self.selected_emitter = None         # emitter_id the ARM targets (M2-T4)
        self._panning = False
        # id(missile) -> (missile, [(x, z), ...]).  The STRONG missile ref
        # pins the object so CPython can never hand a new round the same
        # id() while its trail lives — without it a dead round's trail could
        # graft onto a freshly-allocated missile (id reuse).
        self._trails: dict[int, tuple] = {}

        self.shader = Shader(MAP_VERT, MAP_FRAG)
        self.tex = 0                         # terrain texture: first open
        self.vao = gl.glGenVertexArrays(1)
        self.vbo = gl.glGenBuffers(1)
        gl.glBindVertexArray(self.vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.vbo)
        for loc, offset in ((0, 0), (1, 8)):
            gl.glVertexAttribPointer(loc, 2, gl.GL_FLOAT, gl.GL_FALSE, 16,
                                     ctypes.c_void_p(offset))
            gl.glEnableVertexAttribArray(loc)
        gl.glBindVertexArray(0)

    # ------------------------------------------------------------ sim hook

    def record(self, world) -> None:
        """Per sim step: grow missile breadcrumb trails and keep the target
        point tracking the selected contact's dead-reckoned position."""
        live = set()
        for m in world.missiles:
            # Hostile strike rounds (Phase 3) are fog-of-war gated: they
            # reach the map only through the contact picture, never as
            # truth-position trails/diamonds like the player's own rounds.
            if not m.alive or getattr(m, "is_hostile", False):
                continue
            key = id(m)
            live.add(key)
            entry = self._trails.get(key)
            if entry is None or entry[0] is not m:
                entry = (m, [])
                self._trails[key] = entry
            trail = entry[1]
            p = (float(m.pos[0]), float(m.pos[2]))
            if (not trail or math.hypot(p[0] - trail[-1][0],
                                        p[1] - trail[-1][1]) >= TRAIL_SPACING_M):
                trail.append(p)
        for key in list(self._trails):
            if key not in live:
                del self._trails[key]

        if (self.selected_missile is not None
                and not self.selected_missile.alive):
            self.selected_missile = None     # splashed/expired: deselect

        if self.selected_contact is not None:
            track = world.contacts.tracks.get(self.selected_contact)
            if track is not None:
                est = world.contacts.estimated_pos(self.selected_contact,
                                                   world.sim_time)
                # Air targets keep their dead-reckoned altitude (the S-300
                # shot is made on the 3D contact estimate); surface targets
                # stay the sea-level Oniks aim point.
                y = float(est[1]) if track.get("is_air") else 0.0
                self.sandbox.target_point = np.array([est[0], y, est[2]])
            else:
                # Track dropped (ship sank / aircraft lost): the last
                # estimate stays as a plain coordinate target.
                self.selected_contact = None

    # --------------------------------------------------------------- input

    def handle_event(self, ev) -> bool:
        """Consume map interactions while open; False lets the event fall
        through to the normal sandbox bindings (M, SPACE, P, time accel...)."""
        if self.view is None:                # not drawn yet this session
            return False
        if ev.type == pygame.MOUSEWHEEL:
            self.view.zoom_at(pygame.mouse.get_pos(), ZOOM_STEP ** (-ev.y))
            return True
        if ev.type == pygame.MOUSEBUTTONDOWN:
            if ev.button == 1:
                self._click_target(ev.pos)
                self.sandbox.app.audio.ui_click()
                return True
            if ev.button == 2:
                self._panning = True
                return True
            if ev.button == 3:
                self._rmb_waypoint(self.view.screen_to_world(ev.pos))
                return True
            if ev.button in (4, 5):          # legacy wheel: MOUSEWHEEL handles
                return True
        if ev.type == pygame.MOUSEBUTTONUP and ev.button == 2:
            self._panning = False
            return True
        if ev.type == pygame.MOUSEMOTION and self._panning:
            self.view.pan_px(-ev.rel[0], -ev.rel[1])
            return True
        if (ev.type == pygame.KEYDOWN
                and self.sandbox.app.keybinds.matches("clear_waypoints",
                                                      ev.key)):
            self._clear_waypoints()
            return True
        return False

    def _live_drone(self):
        """The world's flying drone, or None (SANDBOX worlds carry none)."""
        drone = getattr(self.sandbox.world, "drone", None)
        return drone if drone is not None and drone.alive else None

    def _rmb_waypoint(self, wp) -> None:
        """RMB: append to the selected round's remaining route (Task RTG),
        else to the launch plan. A committed round flashes COMMITTED; a full
        route refuses silently (matches the plan-chain behavior). The S-300
        flies no route — with that platform active, planning waypoints is
        refused with a hint instead of silently lying on the map. The drone
        platform tasks the LIVE airframe directly (Phase 4): RMB extends
        its remaining route, capped like the launch plan."""
        m = self.selected_missile
        if m is not None:
            if isinstance(m, SamMissile):
                return                       # trackless: nothing to append to
            if m.append_waypoint(wp):
                self.sandbox.app.audio.ui_click()
            elif not m.retargetable:
                self.sandbox.show_hint(COMMITTED_HINT)
        elif self.sandbox.active_platform == "drone":
            drone = self._live_drone()
            if drone is not None and len(drone.route) < MAX_WAYPOINTS:
                drone.append_waypoint(wp)
                self.sandbox.app.audio.ui_click()
        elif self.sandbox.active_platform in ("s300", "buk"):
            self.sandbox.show_hint(SAM_NO_WAYPOINTS_HINT)
        elif add_waypoint(self.sandbox.waypoints, wp):
            self.sandbox.app.audio.ui_click()

    def _clear_waypoints(self) -> None:
        """X: clear the selected round's remaining waypoints (Task RTG),
        else the launch plan's — or the drone's tasked route (it breaks
        off and loiters where it is) when that platform is active."""
        m = self.selected_missile
        if m is not None:
            if not isinstance(m, SamMissile) and m.clear_route_waypoints():
                self.sandbox.app.audio.ui_click()
            return
        if self.sandbox.active_platform == "drone":
            drone = self._live_drone()
            if drone is not None:
                drone.clear_route()
                self.sandbox.app.audio.ui_click()
            return
        if self.sandbox.active_platform in ("s300", "buk"):
            return      # no plan chain to clear; don't wipe the hidden bastion plan
        clear_waypoints(self.sandbox.waypoints)
        self.sandbox.app.audio.ui_click()

    def _click_target(self, pos) -> None:
        """LMB: own missiles take pick priority (Task RTG) — first click
        selects/deselects a round; with a round selected the next click
        redirects it. Otherwise the launch-planning flow, routed by the
        active platform (Task S4): the S-300 picks air contacts only (a miss
        clears the selection); the Bastion picks surface contacts, falling
        back to a plain coordinate target."""
        sandbox = self.sandbox
        world = sandbox.world
        # M5 ASW: buoy-drop mode is MODAL — while armed (U) the click places
        # a sonobuoy at the clicked world point and is consumed (no targeting).
        if getattr(sandbox, "buoy_drop_armed", False):
            wp = self.view.screen_to_world(pos)
            if sandbox.map_drop_buoy((float(wp[0]), float(wp[1]))):
                return
        m = pick_missile(self.view,
                         [mm for mm in world.missiles
                          if not getattr(mm, "is_hostile", False)], pos)
        if m is not None:
            if m is self.selected_missile:
                self.selected_missile = None     # toggle off: back to planning
            else:
                self.selected_missile = m
                sandbox.followed = m             # HUD flight block + camera
                sandbox.rig.retarget()
            return
        if self.selected_missile is not None:
            self._retarget_selected(pos)
            return
        if sandbox.active_platform == "drone":
            # Phase 4: the drone is recon-only — LMB plans no launch.
            # RMB waypoints are the whole tasking language.
            sandbox.show_hint(DRONE_RECON_HINT)
            return
        if sandbox.active_platform == "bastion" and getattr(
                sandbox, "oniks_weapon", "oniks") == "kh31p":
            # M2-T4: with the ARM active the Bastion click selects a LOCALIZED
            # enemy EMITTER (the passive-SIGINT picture), NOT a ship/coordinate
            # target — the ARM homes on a radar, not an aim point.  A miss
            # clears the selection.  The existing contact/target click flow is
            # untouched for every other weapon/platform.
            self.selected_emitter = pick_emitter(
                self.view, world.emitter_contacts, pos)
            return
        # The Buk is a SAM battery too: without it in the air-pick tuple the
        # buk platform could never select an air target on the map (SPACE
        # then dead-ended on "SELECT AIR TARGET" forever).
        air = sandbox.active_platform in ("s300", "buk")
        sid = pick_contact(self.view, world.contacts, world.sim_time, pos,
                           air_only=air)
        self.selected_contact = sid
        if sid is not None:
            est = world.contacts.estimated_pos(sid, world.sim_time)
            y = float(est[1]) if air else 0.0
            sandbox.target_point = np.array([est[0], y, est[2]])
        elif air:
            sandbox.target_point = None     # empty sky: nothing to shoot
        else:
            # Oniks (anti-ship): a click with no surface contact is a ground
            # aim point. But if the player clicked an AIR contact (e.g. an
            # inbound SM-2), they meant to engage it — the Oniks can't, so cue
            # the S-300 instead of silently aiming at the sea below it.
            if pick_contact(self.view, world.contacts, world.sim_time, pos,
                            air_only=True) is not None:
                sandbox.show_hint(ONIKS_AIR_HINT)
                return
            sandbox.target_point = ground_aim_point(
                self.view.screen_to_world(pos))

    def _retarget_selected(self, pos) -> None:
        """LMB with a round selected: redirect it mid-flight (Task RTG).
        The Oniks takes a surface contact or a plain map point; the SAM takes
        an air contact (an empty-sky click does nothing). A committed round
        refuses and flashes COMMITTED on the map + HUD hint line."""
        sandbox = self.sandbox
        world = sandbox.world
        m = self.selected_missile
        if isinstance(m, SamMissile):
            sid = pick_contact(self.view, world.contacts, world.sim_time,
                               pos, air_only=True)
            if sid is None:
                return
            if not world.retarget_sam(m, sid):
                sandbox.show_hint(COMMITTED_HINT)
            return
        sid = pick_contact(self.view, world.contacts, world.sim_time, pos,
                           air_only=False)
        if sid is not None:
            est = world.contacts.estimated_pos(sid, world.sim_time)
            aim = np.array([est[0], 0.0, est[2]])
        else:
            aim = ground_aim_point(self.view.screen_to_world(pos))
        if not m.retarget(aim):
            sandbox.show_hint(COMMITTED_HINT)

    def _selected_is_air(self) -> bool:
        track = self.sandbox.world.contacts.tracks.get(self.selected_contact)
        return track is not None and bool(track.get("is_air"))

    def update(self, dt_real: float) -> None:
        """Arrow-key panning (held keys, real time)."""
        if self.view is None:
            return
        keys = pygame.key.get_pressed()
        dx = keys[pygame.K_RIGHT] - keys[pygame.K_LEFT]
        dy = keys[pygame.K_DOWN] - keys[pygame.K_UP]
        if dx or dy:
            self.view.pan_px(dx * PAN_KEY_PX_S * dt_real,
                             dy * PAN_KEY_PX_S * dt_real)

    # ---------------------------------------------------------------- draw

    def draw(self, w: int, h: int) -> None:
        if self.view is None:
            mpp = FIT_MARGIN * max((MAP_X_MAX - MAP_X_MIN) / w,
                                   (MAP_Z_MAX - MAP_Z_MIN) / h)
            self.view = MapView(w, h, meters_per_px=mpp)
        else:
            self.view.resize(w, h)

        # 1) dim the 3D scene, 2) terrain texture quad, 3) vector overlays.
        self._label_rects = []      # per-frame site/star label collision list
        self.text.draw_rect(0, 0, w, h, BACKDROP_RGBA)
        self.text.flush(w, h)
        self._draw_terrain_quad(w, h)
        self._rings()
        self._sam_ring()
        self._jam_overlay()
        self._lanes()
        self._sites()
        self._platform_stars()
        self._pantsir_markers()
        self._plan_chain()
        self._seeker_cone()
        self._elint_overlay()
        self._emitter_overlay()
        self._contacts()
        self._missiles()
        self._drone_overlay()
        self._asw_overlay()
        self._chrome(w, h)
        flight_h = 0.0
        if self.selected_missile is not None:    # Task RTG: live telemetry
            flight_h = self.sandbox.hud.draw_flight_block(
                self.sandbox, self.selected_missile)
        # Contact card AFTER the flight block, docked BELOW it when both are
        # up (they used to draw through each other at the same top-left
        # corner — playtest overlap, 2026-07-05).  16 = hud.MARGIN.
        if self.selected_contact is not None:
            intel_y = (max(INTEL_PANEL_Y, 16 + int(flight_h) + 8)
                       if flight_h else INTEL_PANEL_Y)
            ih = self.sandbox.hud._intel_panel(self.sandbox.world,
                                               self.selected_contact,
                                               self._platform_origin(),
                                               INTEL_PANEL_X, intel_y)
            if ih:
                from game.hud import INTEL_W
                self.sandbox.ui.add("map.intel_panel", INTEL_PANEL_X,
                                    intel_y, INTEL_W, ih,
                                    code="game/hud.py:_intel_panel")
        self.text.flush(w, h)

    # ------------------------------------------------------ terrain texture

    def _active_field(self):
        """The ACTIVE map terrain field (``world.height_field``), or None for a
        SANDBOX world (the default map).  M3-F4: the 2D map texture is keyed on
        and colorized from THIS field, so a seeded preset's 2D map shows the
        same islands the sim masks LOS with — matching the 3D Terrain renderer."""
        return getattr(self.sandbox.world, "height_field", None)

    def _ensure_texture(self) -> bool:
        """Upload the map texture once the async pixel build is done.
        Returns False (and kicks the build) while still pending — the
        terrain quad draws a BUILDING MAP placeholder instead of blocking
        the main thread for the whole build."""
        if self.tex:
            return True
        field = self._active_field()
        pixels = get_map_pixels(field)
        if pixels is None:
            ensure_map_pixels_async(field)
            return False
        gl = self._gl
        pixels = np.ascontiguousarray(pixels)
        self.tex = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.tex)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGB8, pixels.shape[1],
                        pixels.shape[0], 0, gl.GL_RGB, gl.GL_UNSIGNED_BYTE,
                        pixels)
        for pname, val in ((gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR),
                           (gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR),
                           (gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE),
                           (gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)):
            gl.glTexParameteri(gl.GL_TEXTURE_2D, pname, val)
        return True

    def _draw_terrain_quad(self, w: int, h: int) -> None:
        if not self._ensure_texture():
            msg = "BUILDING MAP..."
            tw = self.text.text_width(msg, HEADER_SIZE)
            self.text.draw_text((w - tw) * 0.5, (h - 28) * 0.5, msg,
                                HEADER_COL[:3], HEADER_SIZE)
            return
        gl = self._gl
        x0, y0 = self.view.world_to_screen((MAP_X_MIN, MAP_Z_MAX))  # NW corner
        x1, y1 = self.view.world_to_screen((MAP_X_MAX, MAP_Z_MIN))  # SE corner
        quad = np.array([[x0, y0, 0, 0], [x1, y0, 1, 0], [x1, y1, 1, 1],
                         [x0, y0, 0, 0], [x1, y1, 1, 1], [x0, y1, 0, 1]],
                        dtype=np.float32)
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glDisable(gl.GL_CULL_FACE)
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        self.shader.use()
        self.shader.set_vec2("u_screen", (float(w), float(h)))
        self.shader.set_float("u_alpha", MAP_ALPHA)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.tex)
        self.shader.set_int("u_tex", 0)
        gl.glBindVertexArray(self.vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, quad.nbytes, quad,
                        gl.GL_STREAM_DRAW)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 6)
        gl.glBindVertexArray(0)
        gl.glDisable(gl.GL_BLEND)
        gl.glEnable(gl.GL_CULL_FACE)
        gl.glEnable(gl.GL_DEPTH_TEST)

    # ------------------------------------------------------------- overlays

    def _on_screen(self, sx: float, sy: float, pad: float = 20.0) -> bool:
        return (-pad <= sx <= self.view.screen_w + pad
                and -pad <= sy <= self.view.screen_h + pad)

    def _poly_world(self, pts_xz, rgba, width=1.5) -> None:
        """Polyline through world (x, z) points (GL clips offscreen spans)."""
        self.text.draw_lines([self.view.world_to_screen(p) for p in pts_xz],
                             rgba, width)

    def _rings(self) -> None:
        """Range rings every 100 km around the base, labelled due north."""
        bx, bz = BASE_POS[0], BASE_POS[2]
        ang = np.linspace(0.0, 2.0 * np.pi, RING_SEGMENTS + 1)
        sin_a, cos_a = np.sin(ang), np.cos(ang)
        for i in range(1, RING_COUNT + 1):
            r = i * RING_SPACING_M
            cx, cy = self.view.world_to_screen((bx, bz))
            rpx = r / self.view.meters_per_px
            if (cx + rpx < 0 or cx - rpx > self.view.screen_w
                    or cy + rpx < 0 or cy - rpx > self.view.screen_h):
                continue
            self._poly_world(zip(bx + r * sin_a, bz + r * cos_a),
                             RING_COL, 1.0)
            lx, ly = self.view.world_to_screen((bx, bz + r))
            if self._on_screen(lx, ly):
                self.text.draw_text(lx + 4, ly - 18, f"{i * 100} km",
                                    RING_TEXT_COL)

    def _sam_ring(self) -> None:
        """The SELECTED round's guided envelope around the active SAM site,
        shown while a SAM platform is active (Task S4: it teaches what's in
        range; Phase 5b: the V round select swaps the ring — 48N6 150 km vs the
        40N6's 380 km high-target reach; M5: the Buk site swaps to 9M317 70 km
        vs 9M338 40 km when the buk platform is active)."""
        platform = self.sandbox.active_platform
        if platform == "buk":
            from sim.arsenal import BUK_AGILE, BUK_LONG
            from world.combat import BUK_SITE_XZ
            buk_round = getattr(self.sandbox, "buk_round", "9m317")
            weapon = BUK_AGILE if buk_round == "9m338" else BUK_LONG
            cx, cz = BUK_SITE_XZ[0], BUK_SITE_XZ[1]
            label = f"{buk_round.upper()} {weapon.max_range / 1e3:.0f} km"
        elif platform == "s300":
            from sim.arsenal import N40N6
            sam_round = getattr(self.sandbox, "sam_round", "48n6")
            weapon = N40N6 if sam_round == "40n6" else S300
            cx, cz = SAM_SITE_POS[0], SAM_SITE_POS[2]
            label = f"{sam_round.upper()} {weapon.max_range / 1e3:.0f} km"
        else:
            return
        ang = np.linspace(0.0, 2.0 * np.pi, RING_SEGMENTS + 1)
        r = weapon.max_range
        self._poly_world(zip(cx + r * np.sin(ang), cz + r * np.cos(ang)),
                         SAM_RING_COL, 1.5)
        lx, ly = self.view.world_to_screen((cx, cz + r))
        if self._on_screen(lx, ly):
            self.text.draw_text(lx + 4, ly - 18, label, SAM_RING_COL)
        # LOW-TARGET honesty ring (live playtest 2026-07-03: the 150 km ring
        # badly oversold the envelope vs sea-skimmers — the measured 48N6
        # kill reach vs a 50 m Tomahawk is ~20-25 km, energy + horizon
        # physics).  A dashed inner ring shows where LOW inbounds actually
        # die; drawn only for rounds whose max ring is far beyond it (the
        # 40N6 refuses low targets outright; the Buk rings are close-in).
        if platform == "s300" and sam_round != "40n6":
            rl = SAM_LOW_RING_M
            for a0 in range(0, RING_SEGMENTS, 8):     # dashed: 4-seg dashes
                seg = np.linspace(2 * np.pi * a0 / RING_SEGMENTS,
                                  2 * np.pi * (a0 + 4) / RING_SEGMENTS, 5)
                self._poly_world(
                    zip(cx + rl * np.sin(seg), cz + rl * np.cos(seg)),
                    SAM_RING_COL, 1.0)
            lx, ly = self.view.world_to_screen((cx, cz - rl))
            if self._on_screen(lx, ly):
                self.text.draw_text(lx + 4, ly + 6,
                                    f"LOW TGT ~{rl / 1e3:.0f} km",
                                    (*SAM_RING_COL[:3], 0.8))

    def _lanes(self) -> None:
        for lane in LANES:
            self._poly_world(lane, LANE_COL, 1.5)

    def _label_text(self, lx: float, ly: float, name: str, col) -> None:
        """Site/star label with per-frame collision nudging: clustered
        base-area installations (BASE / RADAR STN / SAM SITE) used to draw
        on top of each other into an unreadable garble at map zoom; each
        label now shifts down a row until it finds clear air."""
        if not hasattr(self, "_label_rects"):
            self._label_rects = []
        lw = self.text.text_width(name)
        y = ly
        for _ in range(6):
            rect = (lx, y, lx + lw, y + 16.0)
            if all(not (rect[0] < r[2] and rect[2] > r[0]
                        and rect[1] < r[3] and rect[3] > r[1])
                   for r in self._label_rects):
                break
            y += 16.0
        self._label_rects.append((lx, y, lx + lw, y + 16.0))
        self.text.draw_text(lx, y, name, col)

    def _sites(self) -> None:
        """Land-site squares: the world's own sites plus any DISCOVERED
        enemy installations (COMBAT Phase 5a fog of war for structures —
        world/combat.py known_enemy_sites holds the airfield only once a
        player sensor has imaged it; SANDBOX worlds have no such list)."""
        s = SITE_HALF_PX
        world = self.sandbox.world
        # Color LAW: the player's OWN installations (world.sites — e.g. the
        # friendly radar stations) wear own-force green; only DISCOVERED
        # enemy installations wear the hostile family.  (Both used to draw
        # in the one hostile site color — a pre-Wardroom miscolor.)
        groups = ((list(world.sites), BASE_COL),
                  (list(getattr(world, "known_enemy_sites", ())), SITE_COL))
        for sites, col in groups:
            for site in sites:
                sx, sy = self.view.world_to_screen(site["pos"])
                if not self._on_screen(sx, sy, pad=120.0):
                    continue
                self.text.draw_lines([(sx - s, sy - s), (sx + s, sy - s),
                                      (sx + s, sy + s), (sx - s, sy + s),
                                      (sx - s, sy - s)], col, 1.5)
                self._label_text(sx + s + 4, sy - 9, site["name"], col)

    def _platform_stars(self) -> None:
        """Both friendly platforms (Task S4): the active one full strength,
        the other dimmed."""
        active = self.sandbox.active_platform
        for xz, label, platform in (((BASE_POS[0], BASE_POS[2]),
                                     "BASE", "bastion"),
                                    ((SAM_SITE_POS[0], SAM_SITE_POS[2]),
                                     "SAM SITE", "s300")):
            sx, sy = self.view.world_to_screen(xz)
            if not self._on_screen(sx, sy, pad=60.0):
                continue
            a = 1.0 if platform == active else PLATFORM_DIM
            col = BASE_COL[:3] + (BASE_COL[3] * a,)
            r, d = BASE_STAR_PX, BASE_STAR_PX * 0.7071
            for ax, ay, bx, by in ((-r, 0, r, 0), (0, -r, 0, r),
                                   (-d, -d, d, d), (-d, d, d, -d)):
                self.text.draw_lines([(sx + ax, sy + ay), (sx + bx, sy + by)],
                                     col, 1.5)
            self._label_text(sx + r + 4, sy - 9, label, col)

    def _pantsir_markers(self) -> None:
        """Friendly Pantsir-S1 point-defense units near the base (COMBAT
        Phase 6): a small diamond per unit at its true position (static
        ground asset, not a fog-of-war contact).  A destroyed unit dims to
        the DEAD alpha.  SANDBOX worlds have no ``pantsirs`` list."""
        d = PANTSIR_DIAMOND_PX
        for unit in getattr(self.sandbox.world, "pantsirs", ()):
            sx, sy = self.view.world_to_screen((unit.pos[0], unit.pos[2]))
            if not self._on_screen(sx, sy, pad=40.0):
                continue
            col = PANTSIR_COL if unit.alive else PANTSIR_DEAD_COL
            self.text.draw_lines([(sx, sy - d), (sx + d, sy), (sx, sy + d),
                                  (sx - d, sy), (sx, sy - d)], col, 1.5)

    def _platform_origin(self) -> tuple:
        """(x, z) of the active platform (route chain / bearing origin)."""
        if self.sandbox.active_platform == "s300":
            return (SAM_SITE_POS[0], SAM_SITE_POS[2])
        if self.sandbox.active_platform == "buk":
            # The Buk battery sits at its own site — bearings/ranges from the
            # base pad disagreed with the HUD's own Buk plate.
            from world.combat import BUK_SITE_XZ
            return (BUK_SITE_XZ[0], BUK_SITE_XZ[1])
        return (BASE_POS[0], BASE_POS[2])

    def _plan_chain(self) -> None:
        """Planned route: active platform -> waypoints -> target, marked.
        The S-300 flies direct — its plan draws no waypoint chain (the
        bastion's planned waypoints persist hidden until TAB back)."""
        sandbox = self.sandbox
        if sandbox.active_platform == "s300":
            chain = [self._platform_origin()]
            tp = sandbox.target_point
            if tp is not None:
                chain.append((float(tp[0]), float(tp[2])))
                self._poly_world(chain, PLAN_COL, 1.5)
                sx, sy = self.view.world_to_screen((tp[0], tp[2]))
                c = TARGET_CROSS_PX
                self.text.draw_lines([(sx - c, sy - c), (sx + c, sy + c)],
                                     TARGET_COL, 2.0)
                self.text.draw_lines([(sx - c, sy + c), (sx + c, sy - c)],
                                     TARGET_COL, 2.0)
            return
        chain = [self._platform_origin()] + list(sandbox.waypoints)
        tp = sandbox.target_point
        if tp is not None:
            chain.append((float(tp[0]), float(tp[2])))
        if len(chain) > 1:
            self._poly_world(chain, PLAN_COL, 1.5)
        d = WAYPOINT_PX
        for i, wp in enumerate(sandbox.waypoints):
            sx, sy = self.view.world_to_screen(wp)
            self.text.draw_lines([(sx, sy - d), (sx + d, sy), (sx, sy + d),
                                  (sx - d, sy), (sx, sy - d)], PLAN_COL, 1.5)
            self.text.draw_text(sx + d + 3, sy - 9, str(i + 1), PLAN_COL)
        if tp is not None:
            sx, sy = self.view.world_to_screen((tp[0], tp[2]))
            c = TARGET_CROSS_PX
            self.text.draw_lines([(sx - c, sy - c), (sx + c, sy + c)],
                                 TARGET_COL, 2.0)
            self.text.draw_lines([(sx - c, sy + c), (sx + c, sy - c)],
                                 TARGET_COL, 2.0)

    def _seeker_cone(self) -> None:
        """Seeker-basket preview: the acquisition wedge the missile sweeps
        approaching the target point along the final route leg — drawn from
        the SELECTED round's own seeker (Zircon 60 km/30 deg, swarm
        12 km/40 deg...); it was hardcoded to the Oniks wedge, so the player
        planned final legs against a basket the round didn't have.  An air
        target has no surface acquisition basket."""
        sandbox = self.sandbox
        tp = sandbox.target_point
        if tp is None or self._selected_is_air():
            return
        from sim.arsenal import SWARM, ZIRCON
        if sandbox.active_platform == "swarm":
            weapon = SWARM
        elif getattr(sandbox, "oniks_weapon", "oniks") == "zircon":
            weapon = ZIRCON
        else:
            weapon = ONIKS      # oniks; asbm/kh31p keep the legacy preview
        tx, tz = float(tp[0]), float(tp[2])
        ox, oz = (sandbox.waypoints[-1] if sandbox.waypoints
                  else (BASE_POS[0], BASE_POS[2]))
        dx, dz = tx - ox, tz - oz
        n = float(np.hypot(dx, dz))
        if n < 1.0:
            return
        course = float(np.arctan2(dx, dz))   # approach heading at the target
        apex = (tx - dx / n * weapon.seeker_range,
                tz - dz / n * weapon.seeker_range)
        half = np.radians(weapon.seeker_half_angle_deg)
        arc = course + np.linspace(-half, half, SEEKER_ARC_SEGMENTS + 1)
        rim = [(apex[0] + weapon.seeker_range * np.sin(a),
                apex[1] + weapon.seeker_range * np.cos(a)) for a in arc]
        self._poly_world([rim[0], apex, rim[-1]], SEEKER_COL, 1.0)
        self._poly_world(rim, SEEKER_COL, 1.0)

    def _contacts(self) -> None:
        """Dead-reckoned contacts, alpha-fading with track age: course
        triangles for ships, diamonds + altitude tag for air (Task S4); the
        selected contact gets a ring."""
        world = self.sandbox.world
        board = world.contacts
        for sid, track in board.tracks.items():
            est = board.estimated_pos(sid, world.sim_time)
            sx, sy = self.view.world_to_screen((est[0], est[2]))
            if not self._on_screen(sx, sy):
                continue
            fade = min(1.0, track["age"] / CONTACT_FADE_S)
            alpha = 1.0 - (1.0 - CONTACT_MIN_ALPHA) * fade
            col = CONTACT_COL + (alpha,)
            if contact_symbol(track) == "air":
                d = AIR_DIAMOND_PX
                self.text.draw_lines(
                    [(sx, sy - d), (sx + d, sy), (sx, sy + d),
                     (sx - d, sy), (sx, sy - d)], col, 1.5)
                self.text.draw_text(sx + d + 3, sy - 9,
                                    air_alt_text(float(est[1])), col)
            else:
                vel = track["vel"]
                course = (float(np.arctan2(vel[0], vel[2]))
                          if float(np.hypot(vel[0], vel[2])) > 1e-6 else 0.0)
                dx, dy = np.sin(course), -np.cos(course)  # screen heading
                px, py = -dy, dx                          # screen perp
                nose = (sx + dx * CONTACT_NOSE_PX, sy + dy * CONTACT_NOSE_PX)
                left = (sx - dx * CONTACT_BACK_PX + px * CONTACT_HALF_PX,
                        sy - dy * CONTACT_BACK_PX + py * CONTACT_HALF_PX)
                right = (sx - dx * CONTACT_BACK_PX - px * CONTACT_HALF_PX,
                         sy - dy * CONTACT_BACK_PX - py * CONTACT_HALF_PX)
                self.text.draw_lines([nose, left, right, nose], col, 1.5)
            if sid == self.selected_contact:
                ang = np.linspace(0.0, 2.0 * np.pi, 17)
                self.text.draw_lines(
                    list(zip(sx + SELECT_RING_PX * np.cos(ang),
                             sy + SELECT_RING_PX * np.sin(ang))),
                    SELECT_COL, 1.5)

    def _missiles(self) -> None:
        """Live missile diamonds + remaining route lines + trail dots."""
        d = MISSILE_DIAMOND_PX
        t = TRAIL_DOT_PX
        for m in self.sandbox.world.missiles:
            if getattr(m, "is_hostile", False):
                continue        # fog of war: hostile rounds show as contacts
            for tx, tz in self._trails.get(id(m), (None, ()))[1]:
                sx, sy = self.view.world_to_screen((tx, tz))
                if self._on_screen(sx, sy, pad=2.0):
                    self.text.draw_rect(sx - t * 0.5, sy - t * 0.5, t, t,
                                        TRAIL_COL)
            route = list(getattr(m, "route", ()))       # SAMs fly trackless
            if route:
                self._poly_world([(m.pos[0], m.pos[2])] + route,
                                 MISSILE_ROUTE_COL, 1.0)
            sx, sy = self.view.world_to_screen((m.pos[0], m.pos[2]))
            if self._on_screen(sx, sy):
                self.text.draw_lines([(sx, sy - d), (sx + d, sy), (sx, sy + d),
                                      (sx - d, sy), (sx, sy - d)],
                                     MISSILE_COL, 2.0)
                if m is self.selected_missile:   # Task RTG highlight ring
                    ang = np.linspace(0.0, 2.0 * np.pi, 17)
                    self.text.draw_lines(
                        list(zip(sx + SELECT_RING_PX * np.cos(ang),
                                 sy + SELECT_RING_PX * np.sin(ang))),
                        SELECT_COL, 1.5)

    # ----------------------------------------------------- Phase 4 overlays

    def _drone_overlay(self) -> None:
        """The friendly drone at its TRUE position (telemetry, not a
        contact): cyan diamond + label + tasked-route polyline; falling
        wrecks draw dimmed without a route."""
        world = self.sandbox.world
        drones = list(getattr(world, "drone_wrecks", ()))
        drone = getattr(world, "drone", None)
        if drone is not None:
            drones.append(drone)
        d = DRONE_DIAMOND_PX
        for dr in drones:
            col = DRONE_COL if dr.alive else DRONE_DEAD_COL
            if dr.alive:
                route = dr.route
                if route:
                    self._poly_world([(dr.pos[0], dr.pos[2])] + route,
                                     DRONE_ROUTE_COL, 1.0)
                    for i, wp in enumerate(route):
                        sx, sy = self.view.world_to_screen(wp)
                        wd = WAYPOINT_PX
                        self.text.draw_lines(
                            [(sx, sy - wd), (sx + wd, sy), (sx, sy + wd),
                             (sx - wd, sy), (sx, sy - wd)],
                            DRONE_ROUTE_COL, 1.5)
                        self.text.draw_text(sx + wd + 3, sy - 9, str(i + 1),
                                            DRONE_ROUTE_COL)
            sx, sy = self.view.world_to_screen((dr.pos[0], dr.pos[2]))
            if not self._on_screen(sx, sy):
                continue
            self.text.draw_lines([(sx, sy - d), (sx + d, sy), (sx, sy + d),
                                  (sx - d, sy), (sx, sy - d)], col, 2.0)
            self.text.draw_lines([(sx - d * 0.5, sy), (sx + d * 0.5, sy)],
                                 col, 1.5)      # center bar: not a missile
            if dr.alive:
                self.text.draw_text(sx + d + 4, sy - 9, "DRONE", col)

    def _asw_overlay(self) -> None:
        """M5 ASW picture (render-only, fog-honest):
        - player sonobuoys at their TRUE drop points (player-owned hardware,
          cyan family) — a small cross + ring;
        - SUBSURFACE contacts (world.sub_contacts) at the acoustic BELIEF
          est_pos (estimate-violet family): an inverted chevron + an
          uncertainty circle from the fix quality; a stale launch DATUM draws
          dimmed vs a live buoy cross-fix;
        - own ASW rounds in flight (small green diamond).
        Never reads world.subs (the boat's truth)."""
        world = self.sandbox.world
        # Sonobuoys (player truth)
        for buoy in getattr(world, "sonobuoys", ()):
            sx, sy = self.view.world_to_screen((buoy[0], buoy[-1]))
            if not self._on_screen(sx, sy):
                continue
            b = BUOY_PX
            self.text.draw_lines([(sx - b, sy), (sx + b, sy)], BUOY_COL, 1.5)
            self.text.draw_lines([(sx, sy - b), (sx, sy + b)], BUOY_COL, 1.5)
            ang = np.linspace(0.0, 2.0 * np.pi, 17)
            self.text.draw_lines(
                list(zip(sx + 2.0 * b * np.cos(ang), sy + 2.0 * b * np.sin(ang))),
                (*BUOY_COL[:3], 0.35), 1.0)
        # Subsurface contacts (acoustic belief)
        for cid, c in getattr(world, "sub_contacts", {}).items():
            est = c.get("pos")
            if est is None:
                continue
            sx, sy = self.view.world_to_screen((float(est[0]), float(est[2])))
            if not self._on_screen(sx, sy):
                continue
            col = SUB_DATUM_COL if c.get("kind") == "datum" else SUB_FIX_COL
            d = SUB_CHEVRON_PX
            # Inverted chevron (points DOWN: subsurface)
            self.text.draw_lines([(sx - d, sy - d * 0.6), (sx, sy + d),
                                  (sx + d, sy - d * 0.6)], col, 2.0)
            label = "DATUM" if c.get("kind") == "datum" else "SSK FIX"
            self.text.draw_text(sx + d + 4, sy - 9, label, col)
            err = float(c.get("quality", float("inf")))
            if err < SUB_CIRCLE_MAX_M:
                ang = np.linspace(0.0, 2.0 * np.pi, ELINT_CIRCLE_SEGMENTS + 1)
                self._poly_world(
                    zip(float(est[0]) + err * np.sin(ang),
                        float(est[2]) + err * np.cos(ang)),
                    (*col[:3], 0.45), 1.0)
        # Own ASW rounds (player truth)
        for rnd in getattr(world, "asw_rounds", ()):
            if not getattr(rnd, "alive", False):
                continue
            sx, sy = self.view.world_to_screen((rnd.pos[0], rnd.pos[2]))
            if not self._on_screen(sx, sy):
                continue
            d = ASW_ROUND_PX
            self.text.draw_lines([(sx, sy - d), (sx + d, sy), (sx, sy + d),
                                  (sx - d, sy), (sx, sy - d)],
                                 ASW_ROUND_COL, 1.5)
            self.text.draw_text(sx + d + 3, sy - 9, "ASW", ASW_ROUND_COL)

    def _elint_overlay(self) -> None:
        """ELINT picture: faint bearing rays from the drone's latest
        intercept of each RECENTLY-heard emitter, and an uncertainty
        circle (radius = fix error) around each estimate once the error
        is inside ELINT_CIRCLE_MAX_M — the circle visibly shrinks as the
        drone's baseline improves the geometry."""
        world = self.sandbox.world
        elint = getattr(world, "elint", None)
        if elint is None:
            return
        from world.combat import ELINT_FRESH_S
        now = world.sim_time
        for eid in elint.heard_emitters():
            heard = elint.last_heard(eid)
            fresh = heard is not None and now - heard <= ELINT_FRESH_S
            if fresh:
                latest = elint.latest_bearing(eid)
                if latest is not None:
                    (ox, oz), brg = (latest[0][0], latest[0][1]), latest[1]
                    end = (ox + ELINT_RAY_LEN_M * math.sin(brg),
                           oz + ELINT_RAY_LEN_M * math.cos(brg))
                    self._poly_world([(ox, oz), end], ELINT_RAY_COL, 1.0)
            err = elint.fix_quality(eid)
            if not (err < ELINT_CIRCLE_MAX_M):
                continue
            est = elint.est_pos(eid)
            if est is None:
                continue
            ang = np.linspace(0.0, 2.0 * np.pi, ELINT_CIRCLE_SEGMENTS + 1)
            self._poly_world(
                zip(est[0] + err * np.sin(ang), est[2] + err * np.cos(ang)),
                ELINT_CIRCLE_COL, 1.0)

    def _emitter_overlay(self) -> None:
        """Localized enemy EMITTERS (M2-T4): the player's passive-SIGINT
        picture (world.emitter_contacts) drawn as faded diamond-in-ring glyphs
        at the SIGINT est_pos BELIEF — never radar truth (FOG / NO CHEAT).  The
        glyph is rendered in the sensor-estimate idiom (estimate-violet, the
        ELINT family) so it can never be misread as friendly truth or as a
        ship/air contact.  Always on whenever the picture is non-empty (the
        fog-honest SIGINT layer); when the ARM is the active Bastion weapon the
        currently-selected emitter gets a brighter ring.

        Render-only: this reads world.emitter_contacts (already injected by the
        sim) and touches NO sim state — no determinism change."""
        world = self.sandbox.world
        ec = getattr(world, "emitter_contacts", None)
        if not ec:
            return
        arm_active = (self.sandbox.active_platform == "bastion"
                      and getattr(self.sandbox, "oniks_weapon", "oniks")
                      == "kh31p")
        d = EMITTER_DIAMOND_PX
        ring_ang = np.linspace(0.0, 2.0 * np.pi, EMITTER_RING_SEGMENTS + 1)
        for eid, c in ec.items():
            pos = c["pos"]
            sx, sy = self.view.world_to_screen((float(pos[0]), float(pos[2])))
            if not self._on_screen(sx, sy):
                continue
            selected = arm_active and eid == self.selected_emitter
            glyph_col = EMITTER_SEL_COL if selected else EMITTER_COL
            # Diamond at the estimate.
            self.text.draw_lines(
                [(sx, sy - d), (sx + d, sy), (sx, sy + d),
                 (sx - d, sy), (sx, sy - d)], glyph_col, 1.5)
            # Uncertainty ring: the larger of the SIGINT fix error (world
            # metres -> px) and a readable minimum, so a tight fix still reads
            # as a ring rather than collapsing onto the diamond.
            err_px = float(c.get("quality", 0.0)) / self.view.meters_per_px
            r = max(EMITTER_RING_PX, err_px)
            self.text.draw_lines(
                list(zip(sx + r * np.cos(ring_ang),
                         sy + r * np.sin(ring_ang))), glyph_col, 1.0)
            kind = str(c.get("kind", "EMITTER"))
            if kind == "JAMMER":
                # Jammer-specific glyph: a noise-burst star — short radial
                # spokes from the diamond out to the ring — marking an emitter
                # that is RADIATING a broad barrage corridor rather than a
                # discrete search beam.  Same estimate-violet hue: still a
                # SIGINT belief at the est_pos, never radar truth.
                for k in range(8):
                    a = (k + 0.5) * (math.pi / 4.0)
                    ca, sa = math.cos(a), math.sin(a)
                    self.text.draw_lines(
                        [(sx + (d + 2.0) * ca, sy + (d + 2.0) * sa),
                         (sx + r * ca, sy + r * sa)], glyph_col, 1.0)
            self.text.draw_text(sx + d + 4, sy - 9, kind, glyph_col)

    def _jam_overlay(self) -> None:
        """The JAMMED corridor band + the player net's shrunken effective ring.

        FOG / NO CHEAT (load-bearing): every geometry here is anchored on the
        SENSOR-BELIEVED jammer fix/bearing the sim published into
        ``world.ew_state`` (the drone ELINT est_pos / bearing) — NEVER a real
        jammer entity's ``.pos``.  Reading a real jammer pos for the overlay
        would be a fog leak.

        Three cases keyed off ``ew_state``:
          * inactive / absent -> draw NOTHING (the byte-identical default).
          * localized fix (jammer_fix_xz set) -> a translucent CLOSED corridor
            wedge anchored at the believed fix, spanning a fixed beamwidth from
            the fix toward the DEFENDED BASE (the threat axis — atan2 to
            BASE_POS), plus the player net's collapsed effective ring as a
            DASHED circle around the net center.
          * bearing-only (jammer_fix_xz None but jammer_bearing set) -> an OPEN
            bearing wedge from the believed bearing with NO closed origin circle
            (the source can't be PLACED, only pointed at — the fog intent).
          * no sensor on the jammer at all (both None) -> the band is ABSENT
            (the player feels the degraded range via the HUD row alone).

        Render-only: reads world.ew_state + own radar_station.pos (own-truth,
        the net center) and touches NO sim state — no determinism change."""
        world = self.sandbox.world
        state = getattr(world, "ew_state", None)
        if not state or not state.get("active"):
            return
        fix_xz = state.get("jammer_fix_xz")
        bearing = state.get("jammer_bearing")

        if fix_xz is not None:
            # Localized: a CLOSED corridor wedge from the believed fix toward the
            # defended base (the threat axis), plus the dashed shrunken eff. ring.
            ox, oz = float(fix_xz[0]), float(fix_xz[1])
            # Corridor axis: from the believed jammer toward the player base
            # (the threat axis), so the wedge sweeps over the defended sector.
            axis = math.atan2(BASE_POS[0] - ox, BASE_POS[2] - oz)
            half = 0.5 * JAM_BEAMWIDTH_RAD
            left = (ox + JAM_WEDGE_LEN_M * math.sin(axis - half),
                    oz + JAM_WEDGE_LEN_M * math.cos(axis - half))
            right = (ox + JAM_WEDGE_LEN_M * math.sin(axis + half),
                     oz + JAM_WEDGE_LEN_M * math.cos(axis + half))
            # Closed triangle apex->left->right->apex (a placed corridor).
            self._poly_world([(ox, oz), left, right, (ox, oz)],
                             JAM_WEDGE_EDGE_COL, 1.5)
            self._shrunken_ring(world, state.get("burn_through_m"))
        elif bearing is not None:
            # Bearing-only: an OPEN wedge from the player net along the believed
            # bearing — two diverging edges, NO closed origin circle (the source
            # is un-localized, only pointed at).  Anchor the open wedge at the
            # net center (own-truth) since there is no placed jammer fix.
            cx, cz = self._net_center(world)
            half = 0.5 * JAM_BEAMWIDTH_RAD
            for edge in (bearing - half, bearing + half):
                end = (cx + JAM_WEDGE_LEN_M * math.sin(edge),
                       cz + JAM_WEDGE_LEN_M * math.cos(edge))
                self._poly_world([(cx, cz), end], JAM_WEDGE_EDGE_COL, 1.5)
        # both None -> nothing placed: the band is absent (the HUD row carries
        # the degraded-range feel on its own).

    def _net_center(self, world):
        """The player radar-net center in world (x, z) — own-truth (allowed):
        the net's own station position, used to anchor the shrunken ring and
        the open bearing wedge."""
        radar = getattr(world, "radar_station", None)
        if radar is not None:
            return float(radar.pos[0]), float(radar.pos[2])
        return float(BASE_POS[0]), float(BASE_POS[2])

    def _shrunken_ring(self, world, burn_through_m) -> None:
        """The player net's collapsed effective range as a DASHED circle around
        the net center — visibly distinct from the solid clear range rings.
        burn_through_m comes from world.ew_state (sim/ew.effective_range, the
        single source of truth); None -> no ring drawn."""
        if burn_through_m is None:
            return
        cx, cz = self._net_center(world)
        r = float(burn_through_m)
        seg = JAM_RING_SEGMENTS
        for i in range(0, seg, JAM_RING_DASH):
            a0 = 2.0 * math.pi * i / seg
            a1 = 2.0 * math.pi * (i + 1) / seg
            self._poly_world(
                [(cx + r * math.sin(a0), cz + r * math.cos(a0)),
                 (cx + r * math.sin(a1), cz + r * math.cos(a1))],
                JAM_RING_COL, 1.5)

    # --------------------------------------------------------------- chrome

    def _chrome(self, w: int, h: int) -> None:
        """Header + launcher status, bottom hint line, cursor readout."""
        sandbox = self.sandbox
        world = sandbox.world
        title = "TACTICAL MAP"
        head_h = self.text.line_height(HEADER_SIZE)
        tw = self.text.text_width(title, HEADER_SIZE)
        self.text.draw_rect((w - tw) * 0.5 - 14, 8, tw + 28,
                            head_h + 30, PANEL_RGBA)
        self.text.draw_text((w - tw) * 0.5, 12, title, HEADER_COL, HEADER_SIZE)
        if sandbox.active_platform == "drone":
            drone = getattr(world, "drone", None)
            if drone is not None and drone.alive:
                if drone.route:
                    line = (f"DRONE AIRBORNE   ALT {drone.pos[1] / 1e3:.1f} "
                            f"km   WPT {len(drone.route)}   RECON ONLY")
                    col = ARMED_COL
                else:
                    # Untasked-loiter cue (playtest 2026-07-05): an untasked
                    # drone finds NOTHING beyond the radar horizon — say so
                    # where the tasking happens, in amber.
                    line = ("DRONE LOITERING - NO ROUTE   "
                            "RMB PLACES RECON WAYPOINTS")
                    col = RELOAD_COL
            else:
                left = getattr(world, "drone_respawn_left", 0.0)
                line = (f"DRONE DOWN   RESPAWN "
                        f"{int(np.ceil(left - 1e-9))} s")
                col = RELOAD_COL
        elif sandbox.active_platform == "s300":
            # Phase 5b round select: the strip shows the SELECTED round's
            # readiness + both stocks (game/hud.py pure helper).
            from game.hud import s300_round_panel
            sam_round = getattr(sandbox, "sam_round", "48n6")
            status, col, _name, ammo_text = s300_round_panel(world,
                                                             sam_round)
            line = (f"S-300 {status}   RND {sam_round.upper()}   "
                    f"{ammo_text}   {self._target_text()}")
        elif sandbox.active_platform == "buk":
            # M5: the Buk gets its own strip — falling through to the else
            # displayed the BASTION's ARMED/RELOADING/profile while the Buk
            # was the active platform.
            from game.hud import buk_round_panel
            buk_round = getattr(sandbox, "buk_round", "9m317")
            status, col, _name, ammo_text = buk_round_panel(world, buk_round)
            line = (f"BUK {status}   RND {buk_round.upper()}   "
                    f"{ammo_text}   {self._target_text()}")
        else:
            if world.launcher_armed:
                status, col = "ARMED", ARMED_COL
            else:
                status = ("RELOADING "
                          f"{int(np.ceil(world.reload_left - 1e-9))} s")
                col = RELOAD_COL
            line = (f"{status}   {sandbox.profile.upper()}   "
                    f"WPT {len(sandbox.waypoints)}   {self._target_text()}")
        lw = self.text.text_width(line)
        self.text.draw_text((w - lw) * 0.5, 16 + head_h, line, col)

        # M5 ASW chrome: the finite buoy/ASW stocks (top-left, only when the
        # battle HAS them) + a bright modal tag while buoy-drop is armed.
        buoys = int(getattr(world, "sonobuoys_left", 0))
        asw = int(getattr(world, "asw_ammo_left", 0))
        if buoys > 0 or asw > 0 or getattr(world, "sonobuoys", None):
            asw_line = f"BUOYS {buoys}   ASW {asw}"
            self.text.draw_text(16, 16 + head_h, asw_line, STATUS_COL)
        if getattr(sandbox, "buoy_drop_armed", False):
            bw = self.text.text_width(BUOY_ARMED_TEXT)
            self.text.draw_rect(12, 12, bw + 16, head_h + 8, PANEL_RGBA)
            self.text.draw_text(20, 16, BUOY_ARMED_TEXT, HEADER_COL)

        lh = self.text.line_height(BODY_SIZE)
        hw = self.text.text_width(MAP_HINT)
        hx, hy = (w - hw) * 0.5, h - lh - HINT_MARGIN
        self.text.draw_rect(hx - 10, hy - 4, hw + 20, lh + 8, PANEL_RGBA)
        self.text.draw_text(hx, hy, MAP_HINT, HINT_COL)

        # Transient flash (COMMITTED etc., Task RTG): the map mirrors the
        # HUD's hint line, one row above the map hint bar.
        if sandbox.hint_left > 0.0 and sandbox.hint_text:
            fw = self.text.text_width(sandbox.hint_text)
            fx, fy = (w - fw) * 0.5, hy - lh - 16.0
            self.text.draw_rect(fx - 10, fy - 4, fw + 20, lh + 8, PANEL_RGBA)
            self.text.draw_text(fx, fy, sandbox.hint_text, RELOAD_COL)

        mx, my = pygame.mouse.get_pos()
        wp = self.view.screen_to_world((mx, my))
        dx, dz = wp[0] - BASE_POS[0], wp[1] - BASE_POS[2]
        brg = int(round(np.degrees(np.arctan2(dx, dz)))) % 360
        readout = (f"X {wp[0] / 1e3:+8.1f}  Z {wp[1] / 1e3:+8.1f} km   "
                   f"BRG {brg:03d}  {np.hypot(dx, dz) / 1e3:6.1f} km")
        rw = self.text.text_width(readout)
        self.text.draw_text(w - rw - 14, hy - lh - 6, readout, HINT_COL)

        # M1 fog-of-war surfaces, queued into THIS batch (the map flushes once
        # at the end of draw() — never flush here, that would double-flush):
        # the right-edge threat strip, TTI-origined on the player base.
        # (The contact-intel panel moved to draw() so it can dock BELOW the
        # selected round's flight block instead of overlapping it.)
        hud = self.sandbox.hud
        hud._threat_strip(self.sandbox, (BASE_POS[0], BASE_POS[2]), w, h)

    def _target_text(self) -> str:
        tp = self.sandbox.target_point
        if tp is None:
            return "TGT NONE"
        kind = ("TRK " + str(self.selected_contact).upper()
                if self.selected_contact is not None else "TGT")
        ox, oz = self._platform_origin()
        dx = float(tp[0]) - ox
        dz = float(tp[2]) - oz
        brg = int(round(np.degrees(np.arctan2(dx, dz)))) % 360
        return f"{kind} BRG {brg:03d} {np.hypot(dx, dz) / 1e3:.0f} km"

    def delete(self) -> None:
        gl = self._gl
        if self.vao:
            gl.glDeleteVertexArrays(1, [self.vao])
            gl.glDeleteBuffers(1, [self.vbo])
            self.vao = self.vbo = 0
        if self.tex:
            gl.glDeleteTextures(1, [self.tex])
            self.tex = 0
