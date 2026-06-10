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

import numpy as np
import pygame

from engine.text import BODY_SIZE, HEADER_SIZE
from sim.arsenal import ONIKS
from world.generation import BASE_POS, LANES, SITES, terrain_height

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

LANE_COL = (0.45, 0.60, 0.75, 0.38)          # dim shipping-lane polylines
RING_COL = (0.45, 0.75, 0.55, 0.22)          # dim range rings
RING_TEXT_COL = (0.55, 0.80, 0.62, 0.55)
SITE_COL = (1.00, 0.45, 0.35, 0.95)          # enemy land sites
BASE_COL = (0.45, 1.00, 0.55, 0.95)          # player base star
CONTACT_COL = (1.00, 0.78, 0.30)             # contact triangles (alpha by age)
SELECT_COL = (1.00, 0.95, 0.55, 1.00)        # selected-contact ring
MISSILE_COL = (0.55, 1.00, 0.70, 1.00)       # live missile diamonds
MISSILE_ROUTE_COL = (0.55, 1.00, 0.70, 0.30) # missile's remaining route
TRAIL_COL = (0.80, 1.00, 0.85, 0.75)         # missile trail dots
PLAN_COL = (0.40, 0.85, 1.00, 0.65)          # planned waypoint chain
TARGET_COL = (0.40, 0.90, 1.00, 1.00)        # target cross + circle
SEEKER_COL = (0.40, 0.85, 1.00, 0.50)        # seeker-basket cone preview
HEADER_COL = (0.95, 0.85, 0.45, 1.0)
STATUS_COL = (0.92, 0.97, 0.92, 1.0)
ARMED_COL = (0.45, 1.00, 0.55, 1.0)
RELOAD_COL = (1.00, 0.72, 0.25, 1.0)
HINT_COL = (0.85, 0.90, 0.85, 0.92)
PANEL_RGBA = (0.03, 0.06, 0.05, 0.55)

SITE_HALF_PX = 5.0             # site square icon half-size
BASE_STAR_PX = 8.0             # base star spoke length
CONTACT_NOSE_PX = 9.0          # contact triangle: nose ahead of the estimate
CONTACT_BACK_PX = 5.0          # ... base behind it
CONTACT_HALF_PX = 5.0          # ... base half-width
SELECT_RING_PX = 11.0
MISSILE_DIAMOND_PX = 6.0
WAYPOINT_PX = 4.0              # waypoint diamond half-size
TARGET_CROSS_PX = 7.0
TRAIL_DOT_PX = 3.0
HINT_MARGIN = 10               # px from the bottom edge (matches the HUD)

MAP_HINT = ("LMB target  RMB waypoint  X clear  SPACE launch  "
            "WHEEL zoom  MMB/arrows pan  M close")

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


def build_map_pixels(n: int = MAP_TEX_N) -> np.ndarray:
    """Colorize ``terrain_height`` on an n x n grid over the map extent.

    Returns (n, n, 3) uint8, row 0 = north (z = MAP_Z_MAX), so it uploads
    directly as a GL texture with v=0 at the top of the map quad. Pure numpy.
    """
    xs = np.linspace(MAP_X_MIN, MAP_X_MAX, n)
    zs = np.linspace(MAP_Z_MAX, MAP_Z_MIN, n)          # row 0 = north
    h = terrain_height(xs[None, :], zs[:, None])

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

def pick_contact(view: MapView, board, sim_time: float, mouse_px):
    """ship_id of the contact whose dead-reckoned position is nearest to
    ``mouse_px`` within PICK_RADIUS_PX, else None."""
    best, best_d = None, PICK_RADIUS_PX
    for sid in board.tracks:
        est = board.estimated_pos(sid, sim_time)
        sx, sy = view.world_to_screen((est[0], est[2]))
        d = float(np.hypot(sx - float(mouse_px[0]), sy - float(mouse_px[1])))
        if d <= best_d:
            best, best_d = sid, d
    return best


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
        self._panning = False
        self._trails: dict[int, list] = {}   # id(missile) -> [(x, z), ...]

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
            if not m.alive:
                continue
            key = id(m)
            live.add(key)
            trail = self._trails.setdefault(key, [])
            p = (float(m.pos[0]), float(m.pos[2]))
            if (not trail or np.hypot(p[0] - trail[-1][0],
                                      p[1] - trail[-1][1]) >= TRAIL_SPACING_M):
                trail.append(p)
        for key in list(self._trails):
            if key not in live:
                del self._trails[key]

        if self.selected_contact is not None:
            if self.selected_contact in world.contacts.tracks:
                est = world.contacts.estimated_pos(self.selected_contact,
                                                   world.sim_time)
                self.sandbox.target_point = np.array([est[0], 0.0, est[2]])
            else:
                # Track dropped (ship sank / lost): the last estimate stays
                # as a plain coordinate target.
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
                if add_waypoint(self.sandbox.waypoints,
                                self.view.screen_to_world(ev.pos)):
                    self.sandbox.app.audio.ui_click()
                return True
            if ev.button in (4, 5):          # legacy wheel: MOUSEWHEEL handles
                return True
        if ev.type == pygame.MOUSEBUTTONUP and ev.button == 2:
            self._panning = False
            return True
        if ev.type == pygame.MOUSEMOTION and self._panning:
            self.view.pan_px(-ev.rel[0], -ev.rel[1])
            return True
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_x:
            clear_waypoints(self.sandbox.waypoints)
            self.sandbox.app.audio.ui_click()
            return True
        return False

    def _click_target(self, pos) -> None:
        """LMB: contact within PICK_RADIUS_PX -> tracked target; otherwise a
        plain coordinate target at the clicked point."""
        world = self.sandbox.world
        sid = pick_contact(self.view, world.contacts, world.sim_time, pos)
        self.selected_contact = sid
        if sid is not None:
            est = world.contacts.estimated_pos(sid, world.sim_time)
            self.sandbox.target_point = np.array([est[0], 0.0, est[2]])
        else:
            w = self.view.screen_to_world(pos)
            self.sandbox.target_point = np.array([w[0], 0.0, w[1]])

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
        self.text.draw_rect(0, 0, w, h, BACKDROP_RGBA)
        self.text.flush(w, h)
        self._draw_terrain_quad(w, h)
        self._rings()
        self._lanes()
        self._sites()
        self._base_star()
        self._plan_chain()
        self._seeker_cone()
        self._contacts()
        self._missiles()
        self._chrome(w, h)
        self.text.flush(w, h)

    # ------------------------------------------------------ terrain texture

    def _ensure_texture(self) -> None:
        if self.tex:
            return
        gl = self._gl
        pixels = np.ascontiguousarray(build_map_pixels())
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

    def _draw_terrain_quad(self, w: int, h: int) -> None:
        self._ensure_texture()
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

    def _lanes(self) -> None:
        for lane in LANES:
            self._poly_world(lane, LANE_COL, 1.5)

    def _sites(self) -> None:
        s = SITE_HALF_PX
        for site in SITES:
            sx, sy = self.view.world_to_screen(site["pos"])
            if not self._on_screen(sx, sy, pad=120.0):
                continue
            self.text.draw_lines([(sx - s, sy - s), (sx + s, sy - s),
                                  (sx + s, sy + s), (sx - s, sy + s),
                                  (sx - s, sy - s)], SITE_COL, 1.5)
            self.text.draw_text(sx + s + 4, sy - 9, site["name"], SITE_COL)

    def _base_star(self) -> None:
        sx, sy = self.view.world_to_screen((BASE_POS[0], BASE_POS[2]))
        if not self._on_screen(sx, sy, pad=60.0):
            return
        r, d = BASE_STAR_PX, BASE_STAR_PX * 0.7071
        for ax, ay, bx, by in ((-r, 0, r, 0), (0, -r, 0, r),
                               (-d, -d, d, d), (-d, d, d, -d)):
            self.text.draw_lines([(sx + ax, sy + ay), (sx + bx, sy + by)],
                                 BASE_COL, 1.5)
        self.text.draw_text(sx + r + 4, sy - 9, "BASE", BASE_COL)

    def _plan_chain(self) -> None:
        """Planned route: base -> waypoints -> target, with markers."""
        sandbox = self.sandbox
        chain = [(BASE_POS[0], BASE_POS[2])] + list(sandbox.waypoints)
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
        approaching the target point along the final route leg."""
        sandbox = self.sandbox
        tp = sandbox.target_point
        if tp is None:
            return
        weapon = ONIKS
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
        """Dead-reckoned contact triangles oriented by estimated course,
        alpha-fading with track age; the selected contact gets a ring."""
        world = self.sandbox.world
        board = world.contacts
        for sid, track in board.tracks.items():
            est = board.estimated_pos(sid, world.sim_time)
            sx, sy = self.view.world_to_screen((est[0], est[2]))
            if not self._on_screen(sx, sy):
                continue
            vel = track["vel"]
            course = (float(np.arctan2(vel[0], vel[2]))
                      if float(np.hypot(vel[0], vel[2])) > 1e-6 else 0.0)
            dx, dy = np.sin(course), -np.cos(course)    # screen heading
            px, py = -dy, dx                            # screen perpendicular
            fade = min(1.0, track["age"] / CONTACT_FADE_S)
            alpha = 1.0 - (1.0 - CONTACT_MIN_ALPHA) * fade
            nose = (sx + dx * CONTACT_NOSE_PX, sy + dy * CONTACT_NOSE_PX)
            left = (sx - dx * CONTACT_BACK_PX + px * CONTACT_HALF_PX,
                    sy - dy * CONTACT_BACK_PX + py * CONTACT_HALF_PX)
            right = (sx - dx * CONTACT_BACK_PX - px * CONTACT_HALF_PX,
                     sy - dy * CONTACT_BACK_PX - py * CONTACT_HALF_PX)
            self.text.draw_lines([nose, left, right, nose],
                                 CONTACT_COL + (alpha,), 1.5)
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
            for tx, tz in self._trails.get(id(m), ()):
                sx, sy = self.view.world_to_screen((tx, tz))
                if self._on_screen(sx, sy, pad=2.0):
                    self.text.draw_rect(sx - t * 0.5, sy - t * 0.5, t, t,
                                        TRAIL_COL)
            self._poly_world([(m.pos[0], m.pos[2])] + list(m.route),
                             MISSILE_ROUTE_COL, 1.0)
            sx, sy = self.view.world_to_screen((m.pos[0], m.pos[2]))
            if self._on_screen(sx, sy):
                self.text.draw_lines([(sx, sy - d), (sx + d, sy), (sx, sy + d),
                                      (sx - d, sy), (sx, sy - d)],
                                     MISSILE_COL, 2.0)

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
        if world.launcher_armed:
            status, col = "ARMED", ARMED_COL
        else:
            status = f"RELOADING {int(np.ceil(world.reload_left - 1e-9))} s"
            col = RELOAD_COL
        line = (f"{status}   {sandbox.profile.upper()}   "
                f"WPT {len(sandbox.waypoints)}   {self._target_text()}")
        lw = self.text.text_width(line)
        self.text.draw_text((w - lw) * 0.5, 16 + head_h, line, col)

        lh = self.text.line_height(BODY_SIZE)
        hw = self.text.text_width(MAP_HINT)
        hx, hy = (w - hw) * 0.5, h - lh - HINT_MARGIN
        self.text.draw_rect(hx - 10, hy - 4, hw + 20, lh + 8, PANEL_RGBA)
        self.text.draw_text(hx, hy, MAP_HINT, HINT_COL)

        mx, my = pygame.mouse.get_pos()
        wp = self.view.screen_to_world((mx, my))
        dx, dz = wp[0] - BASE_POS[0], wp[1] - BASE_POS[2]
        brg = int(round(np.degrees(np.arctan2(dx, dz)))) % 360
        readout = (f"X {wp[0] / 1e3:+8.1f}  Z {wp[1] / 1e3:+8.1f} km   "
                   f"BRG {brg:03d}  {np.hypot(dx, dz) / 1e3:6.1f} km")
        rw = self.text.text_width(readout)
        self.text.draw_text(w - rw - 14, hy - lh - 6, readout, HINT_COL)

    def _target_text(self) -> str:
        tp = self.sandbox.target_point
        if tp is None:
            return "TGT none"
        kind = ("TRK " + str(self.selected_contact).upper()
                if self.selected_contact is not None else "TGT")
        dx = float(tp[0]) - BASE_POS[0]
        dz = float(tp[2]) - BASE_POS[2]
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
