"""The M-key orbit view: a true-scale textured Earth under the scene.

The globe is NOT a UI map (user order 2026-07-17: "you're not looking
at a map, you're looking at the world from a different distance").  A
6,371 km sphere skinned with NASA Blue Marble sits with its surface at
sea level directly below the baked terrain, rotated so the scene's
real latitude/longitude faces up.  From the valley it is hidden behind
the Alps (correct: it IS the planet's curvature horizon); as the M-key
camera rides up, the rings shrink into a patch of the real Alps on the
real Earth with zero hand-off tricks — one continuous camera flight.

GL-free math (frames, lat/lon <-> local) lives at module top for the
unit tests; the EarthGlobe class is the GL half.
"""

from __future__ import annotations

import json
import math
import os

import numpy as np

EARTH_R = 6_371_000.0
EARTH_DIR = os.path.join("assets", "cinematic", "earth")


def lv95_to_wgs84(e: float, n: float):
    """swisstopo approximate formulas (lon, lat in degrees)."""
    y = (e - 2_600_000.0) / 1_000_000.0
    x = (n - 1_200_000.0) / 1_000_000.0
    lon = (2.6779094 + 4.728982 * y + 0.791484 * y * x
           + 0.1306 * y * x * x - 0.0436 * y ** 3) * 100.0 / 36.0
    lat = (16.9023892 + 3.238272 * x - 0.270978 * y * y
           - 0.002528 * x * x - 0.0447 * y * y * x
           - 0.0140 * x ** 3) * 100.0 / 36.0
    return lon, lat


def scene_latlon(meta: dict):
    """(lat, lon) of the scene origin from its manifest."""
    if "latlon" in meta:
        return float(meta["latlon"][0]), float(meta["latlon"][1])
    if meta.get("epsg") == 2056:
        lon, lat = lv95_to_wgs84(float(meta["origin_e"]),
                                 float(meta["origin_n"]))
        return lat, lon
    return 46.6, 7.9                       # a safe alpine default


def geo_unit(lat_deg: float, lon_deg: float) -> np.ndarray:
    """Unit vector of a lat/lon on the geo sphere (y = north pole)."""
    la = math.radians(lat_deg)
    lo = math.radians(lon_deg)
    return np.array([math.cos(la) * math.cos(lo),
                     math.sin(la),
                     math.cos(la) * math.sin(lo)])


def geo_frame(lat0: float, lon0: float) -> np.ndarray:
    """3x3 mapping geo-sphere vectors into the LOCKED local frame
    (X east, Y up, Z north) anchored at (lat0, lon0)."""
    up = geo_unit(lat0, lon0)
    north_pole = np.array([0.0, 1.0, 0.0])
    east = np.cross(up, north_pole)        # up x pole = TRUE east
    east /= max(float(np.linalg.norm(east)), 1e-12)
    north = np.cross(east, up)             # east x up = TRUE north
    return np.stack([east, up, north])     # rows: local = M @ geo


def latlon_to_local(lat: float, lon: float, lat0: float, lon0: float):
    """Equirectangular tangent-plane approximation (fine to ~150 km)."""
    x = math.radians(lon - lon0) * EARTH_R * math.cos(math.radians(lat0))
    z = math.radians(lat - lat0) * EARTH_R
    return x, z


def local_to_latlon(x: float, z: float, lat0: float, lon0: float):
    lat = lat0 + math.degrees(z / EARTH_R)
    lon = lon0 + math.degrees(
        x / (EARTH_R * math.cos(math.radians(lat0))))
    return lat, lon


def load_earth_meta():
    p = os.path.join(EARTH_DIR, "earth.json")
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


GLOBE_VERT = """
#version 330 core
layout(location=0) in vec3 a_pos; layout(location=1) in vec3 a_nrm;
layout(location=2) in vec2 a_uv;
uniform mat4 u_proj, u_view_rot;
uniform vec3 u_offset;                 // sphere center - camera eye
out vec3 v_nrm; out vec2 v_uv; out vec3 v_view_vec; out float v_flogz;
void main(){
    vec3 world_rel = a_pos + u_offset;
    v_view_vec = world_rel;
    v_nrm = a_nrm;
    v_uv = a_uv;
    gl_Position = u_proj * u_view_rot * vec4(world_rel, 1.0);
    gl_Position.z = 0.0;               // exact log depth in the fragment
    v_flogz = 1.0 + gl_Position.w;
}
"""

GLOBE_FRAG = """
#version 330 core
in vec3 v_nrm; in vec2 v_uv; in vec3 v_view_vec; in float v_flogz;
uniform sampler2D u_tex;
uniform vec3 u_sun_dir;
uniform vec3 u_sun_color;
uniform float u_log_depth_fcoef;
out vec4 frag;
void main(){
    gl_FragDepth = log2(max(v_flogz, 1e-6)) * (u_log_depth_fcoef * 0.5);
    vec3 albedo = texture(u_tex, v_uv).rgb;
    vec3 n = normalize(v_nrm);
    float raw = dot(n, u_sun_dir);
    // Wide smooth terminator (~20 deg of twilight) between the sunlit
    // day and a moonlit blue night floor - the same sun vector the
    // terrain mood uses, so the split matches the scene lighting.
    float day = smoothstep(-0.16, 0.20, raw);
    vec3 lit = albedo * mix(vec3(0.035, 0.045, 0.070),
                            u_sun_color * 1.10, day);
    // Warm dusk band hugging the terminator on the day side.
    float dusk = exp(-raw * raw / 0.012);
    lit += albedo * vec3(0.50, 0.18, 0.02) * dusk * 0.30;
    // Atmosphere limb: fresnel rim, blue on the day side.
    vec3 vdir = normalize(-v_view_vec);
    float rim = pow(1.0 - clamp(dot(n, vdir), 0.0, 1.0), 3.0);
    lit += vec3(0.30, 0.52, 0.95) * rim * (0.10 + 0.55 * day);
    frag = vec4(lit, 1.0);
}
"""


def build_globe_arrays(lat0: float, lon0: float, origin_alt: float,
                       lat_segs: int = 128, lon_segs: int = 256):
    """(verts (N,8) [pos3 nrm3 uv2] sphere-CENTERED, indices, center_y).

    Vertices are rotated so (lat0, lon0) points at local +Y; the caller
    places the center at (0, center_y, 0) so the surface touches sea
    level (local y = -origin_alt) under the scene origin."""
    m = geo_frame(lat0, lon0)
    lats = np.linspace(-90.0, 90.0, lat_segs + 1)
    lons = np.linspace(-180.0, 180.0, lon_segs + 1)
    la = np.radians(lats)[:, None]
    lo = np.radians(lons)[None, :]
    gx = np.cos(la) * np.cos(lo)
    gy = np.sin(la) * np.broadcast_to(np.ones_like(lo), gx.shape)
    gz = np.cos(la) * np.sin(lo)
    geo = np.stack([gx, gy, gz], axis=-1).reshape(-1, 3)
    unit = geo @ m.T
    verts = np.empty((unit.shape[0], 8), np.float32)
    verts[:, 0:3] = (unit * EARTH_R).astype(np.float32)
    verts[:, 3:6] = unit.astype(np.float32)
    u = (lons[None, :] + 180.0) / 360.0
    v = (90.0 - lats[:, None]) / 180.0     # row 0 = north in the jpg
    verts[:, 6] = np.broadcast_to(u, gx.shape).reshape(-1)
    verts[:, 7] = np.broadcast_to(v, gx.shape).reshape(-1)
    idx = []
    w = lon_segs + 1
    for j in range(lat_segs):
        r0 = j * w
        r1 = (j + 1) * w
        for i in range(lon_segs):
            idx.extend((r0 + i, r1 + i, r1 + i + 1,
                        r0 + i, r1 + i + 1, r0 + i + 1))
    center_y = -(EARTH_R + float(origin_alt))
    return verts, np.asarray(idx, np.uint32), center_y


class EarthGlobe:
    """GL half: the sphere mesh + Blue Marble texture + shader."""

    def __init__(self, scene):
        from OpenGL.GL import (GL_ARRAY_BUFFER, GL_ELEMENT_ARRAY_BUFFER,
                               GL_FALSE, GL_FLOAT, GL_STATIC_DRAW,
                               glBindBuffer, glBindVertexArray,
                               glBufferData, glEnableVertexAttribArray,
                               glGenBuffers, glGenVertexArrays,
                               glVertexAttribPointer)
        import ctypes
        from engine.shader import Shader
        meta = load_earth_meta()
        if meta is None:
            raise FileNotFoundError(
                "assets/cinematic/earth missing - run "
                "tools/fetch_cinematic_earth.py")
        self.attribution = meta.get("attribution", "NASA Blue Marble")
        self.lat0, self.lon0 = scene_latlon(scene.meta)
        verts, indices, self.center_y = build_globe_arrays(
            self.lat0, self.lon0, scene.origin_alt)
        self.shader = Shader(GLOBE_VERT, GLOBE_FRAG)
        self.index_count = int(indices.size)
        self.vao = glGenVertexArrays(1)
        self.vbo = glGenBuffers(1)
        self.ebo = glGenBuffers(1)
        glBindVertexArray(self.vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
        glBufferData(GL_ARRAY_BUFFER, verts.nbytes,
                     np.ascontiguousarray(verts), GL_STATIC_DRAW)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes,
                     np.ascontiguousarray(indices), GL_STATIC_DRAW)
        stride = 32
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride,
                              ctypes.c_void_p(0))
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride,
                              ctypes.c_void_p(12))
        glVertexAttribPointer(2, 2, GL_FLOAT, GL_FALSE, stride,
                              ctypes.c_void_p(24))
        for loc in (0, 1, 2):
            glEnableVertexAttribArray(loc)
        glBindVertexArray(0)
        tex_path = os.path.join(EARTH_DIR, "earth_8k.jpg")
        if not os.path.isfile(tex_path):
            tex_path = os.path.join(EARTH_DIR, "earth_2k.jpg")
        from PIL import Image
        from world.cinematic_terrain import _upload_texture
        rgb = np.asarray(Image.open(tex_path).convert("RGB"),
                         dtype=np.uint8)
        self.tex = _upload_texture(rgb)
        self._disposed = False

    def draw(self, renderer, camera) -> None:
        from OpenGL.GL import (GL_TEXTURE0, GL_TEXTURE_2D,
                               glActiveTexture, glBindTexture,
                               glBindVertexArray, glDrawElements,
                               GL_TRIANGLES, GL_UNSIGNED_INT)
        sh = self.shader
        sh.use()
        sh.set_mat4("u_proj", renderer.proj)
        sh.set_mat4("u_view_rot", renderer.view_rot)
        sh.set_vec3("u_sun_dir", renderer.sun_dir)
        sh.set_vec3("u_sun_color", renderer.sun_color)
        sh.set_float("u_log_depth_fcoef", renderer.fcoef)
        sh.set_int("u_tex", 0)
        eye = camera.eye
        sh.set_vec3("u_offset", (0.0 - eye[0], self.center_y - eye[1],
                                 0.0 - eye[2]))
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self.tex)
        glBindVertexArray(self.vao)
        glDrawElements(GL_TRIANGLES, self.index_count, GL_UNSIGNED_INT,
                       None)
        glBindVertexArray(0)
        glBindTexture(GL_TEXTURE_2D, 0)

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        from OpenGL.GL import (glDeleteBuffers, glDeleteTextures,
                               glDeleteVertexArrays)
        glDeleteVertexArrays(1, [self.vao])
        glDeleteBuffers(2, [self.vbo, self.ebo])
        if self.tex:
            glDeleteTextures([self.tex])
        self.shader.delete()
