"""GL renderer for baked cinematic scenes: textured LiDAR terrain tiles.

GL-touching module (never imported by unit tests — geometry building lives
in :mod:`world.cinematic_scene`).  Three LOD rings per 1 km tile, all drawn
with ONE textured shader so there is never a material seam:

- L0 (< ~650 m):  2 m LiDAR surface mesh (4K texture carries the detail)
- L1 (< ~2.8 km): 4 m mesh
- L2 (rest):      20 m mesh

Every tile's 4096px orthophoto (~25 cm) is decoded on a thread pool and
uploaded ONCE at scene load — driver-compressed where the driver agrees
(verified via GL_TEXTURE_COMPRESSED, with a 2048px RGB8 fallback), so the
walk loop never uploads a texture.  Runtime streaming is meshes only: the
nearest L0_LIVE_MAX tiles inside L0_DIST build their 2 m mesh on a worker
thread (numpy releases the GIL; the GL upload runs on the main thread),
with load/evict hysteresis, one-shot failure memo and stale-result
discard (GPT-5.6 review 2026-07-16).

Cross-LOD cracks: same-LOD tile edges are bit-identical by construction
(one mosaic, corner-aligned samples — the coarse-LOD blur windows are
fully inside the shared halo, so blurring preserves this), but a coarse
edge can sit tens of metres from the fine truth on cliff tiles.  Each
LOD's perimeter skirt is therefore sized from the tile's OWN measured
edge deltas against its other LODs, plus margin, instead of a fixed drop.

The vertex/fragment pair follows the renderer's LOCKED conventions:
camera-relative positions, exact per-pixel logarithmic depth, the shared
haze block.  Steep bare faces get procedural banded rock (the orthophoto
has no pixels for walls), steep forested faces get crown-noise canopy in
wall-plane coordinates, and a fading value noise breaks up texture
magnification near the boots.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import ctypes

import numpy as np
from OpenGL.GL import (
    GL_ARRAY_BUFFER,
    GL_CLAMP_TO_EDGE,
    GL_COMPRESSED_RGB,
    GL_ELEMENT_ARRAY_BUFFER,
    GL_FALSE,
    GL_FLOAT,
    GL_LINEAR,
    GL_LINEAR_MIPMAP_LINEAR,
    GL_RGB,
    GL_RGB8,
    GL_STATIC_DRAW,
    GL_TEXTURE0,
    GL_TEXTURE_2D,
    GL_TEXTURE_COMPRESSED,
    GL_TEXTURE_MAG_FILTER,
    GL_TEXTURE_MIN_FILTER,
    GL_TEXTURE_WRAP_S,
    GL_TEXTURE_WRAP_T,
    GL_TRIANGLES,
    GL_TRUE,
    GL_UNPACK_ALIGNMENT,
    GL_UNSIGNED_BYTE,
    GL_UNSIGNED_INT,
    glActiveTexture,
    glBindBuffer,
    glBindTexture,
    glBindVertexArray,
    glBufferData,
    glDeleteBuffers,
    glDeleteTextures,
    glDeleteVertexArrays,
    glDrawElements,
    glEnableVertexAttribArray,
    glGenBuffers,
    glGenerateMipmap,
    glGenTextures,
    glGenVertexArrays,
    glGetFloatv,
    glGetTexLevelParameteriv,
    glPixelStorei,
    glTexImage2D,
    glTexParameterf,
    glTexParameteri,
    glUniformMatrix4fv,
    glVertexAttribPointer,
)
from PIL import Image

from engine.shader import Shader
from engine.shaderlib import HAZE_GLSL
from world.cinematic_scene import SKIRT_MARGIN, build_tile_arrays, \
    halo_axes, punch_core_hole, skirt_drops

# EXT_texture_filter_anisotropic constants (core-adopted everywhere real).
_GL_TEXTURE_MAX_ANISOTROPY = 0x84FE
_GL_MAX_TEXTURE_MAX_ANISOTROPY = 0x84FF

L0_DIST = 650.0            # m: fine-mesh ring (load threshold)
L0_EVICT_DIST = 800.0      # m: unload threshold (hysteresis band)
L1_DIST = 2800.0           # m: 4 m ring; 20 m beyond
L0_LIVE_MAX = 4            # streamed L0 tiles kept resident

TERRAIN_VERT = """
#version 330 core
layout(location=0) in vec3 a_pos; layout(location=1) in vec3 a_nrm;
layout(location=2) in vec2 a_uv; layout(location=3) in float a_clutter;
uniform mat4 u_proj, u_view_rot, u_model;
uniform vec2 u_tile_xz;               // tile origin: world-continuous noise
out vec3 v_nrm; out vec2 v_uv; out vec3 v_view_vec; out float v_flogz;
out vec3 v_world; out float v_clutter;
void main(){
    vec4 world_rel = u_model * vec4(a_pos, 1.0);
    v_view_vec = world_rel.xyz;
    v_nrm = a_nrm;                    // tiles never rotate: model is a move
    v_uv = a_uv;
    v_clutter = a_clutter;
    v_world = vec3(a_pos.x + u_tile_xz.x, a_pos.y, a_pos.z + u_tile_xz.y);
    gl_Position = u_proj * u_view_rot * world_rel;
    gl_Position.z = 0.0;              // exact log depth in the fragment
    v_flogz = 1.0 + gl_Position.w;
}
"""

TERRAIN_FRAG = """
#version 330 core
in vec3 v_nrm; in vec2 v_uv; in vec3 v_view_vec; in float v_flogz;
in vec3 v_world; in float v_clutter;
uniform sampler2D u_tex;
uniform sampler2D u_shadow;            // baked per-mood terrain shadow
uniform vec4 u_shadow_rect;            // (x0, z0, 1/w, 1/h) world -> uv
uniform float u_shadow_str;            // 0 = no mask bound
uniform vec3 u_sun_color;
uniform float u_log_depth_fcoef;
uniform float u_hemi_gain;
out vec4 frag;
""" + HAZE_GLSL + """
float vnoise(vec2 p){
    vec2 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float a = fract(sin(dot(i, vec2(127.1, 311.7))) * 43758.5453);
    float b = fract(sin(dot(i + vec2(1, 0), vec2(127.1, 311.7))) * 43758.5453);
    float c = fract(sin(dot(i + vec2(0, 1), vec2(127.1, 311.7))) * 43758.5453);
    float d = fract(sin(dot(i + vec2(1, 1), vec2(127.1, 311.7))) * 43758.5453);
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}
void main(){
    gl_FragDepth = log2(max(v_flogz, 1e-6)) * (u_log_depth_fcoef * 0.5);
    vec3 albedo = texture(u_tex, v_uv).rgb;
    // Close-range detail: value noise breaks the 25 cm orthophoto blur at
    // boot level, fading out by 60 m so distant slopes stay photo-true.
    float d = length(v_view_vec);
    float detail_amt = (1.0 - smoothstep(10.0, 60.0, d)) * 0.16;
    float detail = vnoise(v_world.xz * 3.1) * 0.5
                 + vnoise(v_world.xz * 11.7) * 0.3
                 + vnoise(v_world.xz * 29.3) * 0.2;
    albedo *= 1.0 + (detail - 0.5) * 2.0 * detail_amt;
    vec3 n = normalize(v_nrm);
    // Forest on steep ground smears into green curtains (the orthophoto
    // paints canopy TOPS onto near-vertical LOD walls).  Re-texture those
    // faces with crown-scale value noise in WALL-PLANE coordinates (xz
    // barely varies up a vertical face) so slope forests read as massed
    // canopy instead of stripes.
    float steep_raw = 1.0 - smoothstep(0.35, 0.72, n.y);
    float forest = steep_raw * smoothstep(2.0, 6.0, v_clutter);
    if (forest > 0.001) {
        vec2 wp = vec2(v_world.x + v_world.z, v_world.y);
        float crowns = vnoise(wp * 0.35) * 0.6 + vnoise(wp * 1.4) * 0.4;
        vec3 canopy = mix(vec3(0.10, 0.16, 0.08), vec3(0.26, 0.36, 0.16),
                          crowns);
        albedo = mix(albedo, canopy, forest * 0.85);
    }
    // Cliff rock: an orthophoto is shot from ABOVE, so near-vertical faces
    // only get a smeared pixel column.  Where the surface leaves the
    // photo's view (n.y falling), blend to procedural limestone with
    // height-banded strata + grain so the 400 m walls read as rock ...
    // ... but ONLY on bare earth: trees and roofs are steep too, and rock-
    // painting a village turns it into standing stones (audit round 2).
    float steep = 1.0 - smoothstep(0.35, 0.72, n.y);
    steep *= 1.0 - smoothstep(1.0, 3.0, v_clutter);
    if (steep > 0.001) {
        float band = vnoise(vec2(v_world.y * 0.09,
                                 (v_world.x + v_world.z) * 0.012));
        float grain = vnoise(v_world.xz * 1.7 + v_world.y * 0.31);
        float macro = vnoise(v_world.xz * 0.02 + v_world.y * 0.011);
        vec3 rock = mix(vec3(0.34, 0.31, 0.27), vec3(0.55, 0.52, 0.46),
                        band);
        rock *= (0.72 + grain * 0.52) * (0.82 + macro * 0.36);
        albedo = mix(albedo, rock, steep * 0.92);
    }
    float raw = dot(n, u_sun_dir);
    float ndl = clamp((raw + 0.4) / 1.4, 0.0, 1.0);
    ndl *= ndl;
    vec3 hemi = mix(vec3(0.24, 0.22, 0.19), vec3(0.35, 0.42, 0.52),
                    n.y * 0.5 + 0.5);
    // Baked terrain shadow (per light mood): the Jungfrau wall really
    // darkens the valley at golden hour.  Shadowed ground keeps most of
    // its sky light but loses the sun term.
    vec2 suv = (v_world.xz - u_shadow_rect.xy) * u_shadow_rect.zw;
    float shadow = texture(u_shadow, suv).r * u_shadow_str;
    float sun_vis = 1.0 - shadow * 0.92;
    float sky_vis = 1.0 - shadow * 0.22;
    // The orthophoto already contains baked sun+sky: lift the lighting mix
    // toward flat so real shadows in the photo aren't double-darkened.
    vec3 lit = albedo * (u_sun_color * ndl * 0.85 * sun_vis
                         + hemi * 1.15 * u_hemi_gain * sky_vis);
    frag = vec4(apply_haze(lit, v_view_vec, u_cam_alt), 1.0);
}
"""


class _TexturedMesh:
    """VAO for the 9-float [pos3 nrm3 uv2 clutter1] tile layout."""

    def __init__(self, verts: np.ndarray, indices: np.ndarray):
        verts = np.ascontiguousarray(verts, dtype=np.float32)
        indices = np.ascontiguousarray(indices, dtype=np.uint32)
        self.index_count = int(indices.size)
        self.vao = glGenVertexArrays(1)
        self.vbo = glGenBuffers(1)
        self.ebo = glGenBuffers(1)
        glBindVertexArray(self.vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
        glBufferData(GL_ARRAY_BUFFER, verts.nbytes, verts, GL_STATIC_DRAW)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices,
                     GL_STATIC_DRAW)
        stride = 36
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride,
                              ctypes.c_void_p(0))
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride,
                              ctypes.c_void_p(12))
        glVertexAttribPointer(2, 2, GL_FLOAT, GL_FALSE, stride,
                              ctypes.c_void_p(24))
        glVertexAttribPointer(3, 1, GL_FLOAT, GL_FALSE, stride,
                              ctypes.c_void_p(32))
        for loc in (0, 1, 2, 3):
            glEnableVertexAttribArray(loc)
        glBindVertexArray(0)

    def draw(self) -> None:
        glBindVertexArray(self.vao)
        glDrawElements(GL_TRIANGLES, self.index_count, GL_UNSIGNED_INT, None)
        glBindVertexArray(0)

    def delete(self) -> None:
        if self.vao:
            glDeleteVertexArrays(1, [self.vao])
            glDeleteBuffers(2, [self.vbo, self.ebo])
            self.vao = 0


def _upload_texture(rgb: np.ndarray) -> int:
    """Upload RGB uint8, mipmapped + clamped.  Asks for driver compression
    and VERIFIES it took (GL_TEXTURE_COMPRESSED); if the driver refused,
    re-uploads a half-size RGB8 so 16 resident 4K tiles can't blow VRAM."""
    tid = glGenTextures(1)
    glBindTexture(GL_TEXTURE_2D, tid)
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
    data = np.ascontiguousarray(rgb)
    glTexImage2D(GL_TEXTURE_2D, 0, GL_COMPRESSED_RGB, data.shape[1],
                 data.shape[0], 0, GL_RGB, GL_UNSIGNED_BYTE, data)
    compressed = glGetTexLevelParameteriv(GL_TEXTURE_2D, 0,
                                          GL_TEXTURE_COMPRESSED)
    if not compressed and data.shape[0] > 2048:
        half = np.asarray(Image.fromarray(data).resize(
            (data.shape[1] // 2, data.shape[0] // 2), Image.BILINEAR))
        data = np.ascontiguousarray(half)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB8, data.shape[1],
                     data.shape[0], 0, GL_RGB, GL_UNSIGNED_BYTE, data)
    glGenerateMipmap(GL_TEXTURE_2D)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER,
                    GL_LINEAR_MIPMAP_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
    try:
        max_aniso = glGetFloatv(_GL_MAX_TEXTURE_MAX_ANISOTROPY)
        glTexParameterf(GL_TEXTURE_2D, _GL_TEXTURE_MAX_ANISOTROPY,
                        min(8.0, float(max_aniso)))
    except Exception:            # noqa: BLE001 — ext missing: mips suffice
        pass
    glPixelStorei(GL_UNPACK_ALIGNMENT, 4)
    glBindTexture(GL_TEXTURE_2D, 0)
    return tid


class _Tile:
    __slots__ = ("rec", "x0", "z0", "size", "mesh_l1", "mesh_l2", "tex",
                 "mesh_l0", "l0_future", "l0_failed", "l0_skirt", "y_mid",
                 "radius")

    def __init__(self, rec):
        self.rec = rec
        self.x0, self.z0, self.size = rec.x0, rec.z0, rec.size
        self.mesh_l1 = None
        self.mesh_l2 = None
        self.tex = 0
        self.mesh_l0 = None
        self.l0_future = None
        self.l0_failed = False
        self.l0_skirt = SKIRT_MARGIN
        self.y_mid = 0.0
        self.radius = rec.size

    def dist(self, eye) -> float:
        """2D distance from the eye to the tile rect (0 inside)."""
        dx = max(self.x0 - eye[0], 0.0, eye[0] - (self.x0 + self.size))
        dz = max(self.z0 - eye[2], 0.0, eye[2] - (self.z0 + self.size))
        return float(np.hypot(dx, dz))


def _build_l0_arrays(hgt_path: str, size: float, skirt: float,
                     delta2=None):
    """Worker-thread half of an L0 stream-in: mesh arrays only.
    ``delta2``: optional crater height delta on the same haloed grid."""
    with np.load(hgt_path) as z:
        h = z["dsm_2m"]
        clutter = z["clutter_2m"]
    if delta2 is not None:
        h = h + delta2
    return build_tile_arrays(h, 2.0, size, skirt_drop=skirt,
                             clutter=clutter)


def _scorch_rgb(tex_path: str, x0: float, z0: float, size: float,
                craters) -> np.ndarray:
    """Worker-thread: decode a tile texture and burn crater scorch into
    it (dark ash disc, radial falloff).  Row 0 = NORTH per the baked UV
    convention."""
    rgb = np.asarray(Image.open(tex_path).convert("RGB"),
                     dtype=np.float32)
    hpx, wpx = rgb.shape[0], rgb.shape[1]
    ash = np.array([46.0, 42.0, 39.0])
    for c in craters:
        cx, cz, r = c[0], c[1], c[2]
        reach = r * 1.45
        c0 = max(0, int((cx - reach - x0) / size * wpx))
        c1 = min(wpx, int((cx + reach - x0) / size * wpx) + 1)
        r0 = max(0, int((1.0 - (cz + reach - z0) / size) * hpx))
        r1 = min(hpx, int((1.0 - (cz - reach - z0) / size) * hpx) + 1)
        if c0 >= c1 or r0 >= r1:
            continue
        px = x0 + (np.arange(c0, c1) + 0.5) / wpx * size
        pz = z0 + (1.0 - (np.arange(r0, r1) + 0.5) / hpx) * size
        rr = np.hypot(px[None, :] - cx, pz[:, None] - cz) / reach
        m = np.clip(1.0 - rr, 0.0, 1.0) ** 1.4
        patch = rgb[r0:r1, c0:c1]
        rgb[r0:r1, c0:c1] = (patch * (1.0 - 0.82 * m[..., None])
                             + ash[None, None] * (0.82 * m[..., None]))
    return rgb.astype(np.uint8)


def _decode_tex(path: str) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)


class CinematicTerrain:
    """All render tiles of one scene + the mesh streaming state machine."""

    def __init__(self, scene):
        self.scene = scene
        self.shader = Shader(TERRAIN_VERT, TERRAIN_FRAG)
        self._u_model = None
        self._pool = ThreadPoolExecutor(max_workers=2,
                                        thread_name_prefix="cine-l0")
        # Baked mood shadow (upload_shadow_mask/set_shadow): unit 1.
        self.shadow_tex = 0
        self.shadow_rect = (0.0, 0.0, 1.0, 1.0)
        self.shadow_str = 0.0
        self._shadow_texs: list = []       # every uploaded mask (disposal)
        self.tiles = []
        try:
            decode_futs = {}
            for rec in scene.tiles:
                decode_futs[rec.hgt_path] = self._pool.submit(
                    _decode_tex, rec.tex_path)
            for rec in scene.tiles:
                t = _Tile(rec)
                with np.load(rec.hgt_path) as z:
                    h2, h4, h20 = z["dsm_2m"], z["dsm_4m"], z["dsm_20m"]
                    c4, c20 = z["clutter_4m"], z["clutter_20m"]
                drops = skirt_drops(h2, h4, h20)
                t.l0_skirt = drops[0]
                t.y_mid = float(h4.mean())
                t.radius = float(np.hypot(rec.size * 0.71,
                                          (h4.max() - h4.min()) * 0.5) + 1.0)
                t.mesh_l1 = _TexturedMesh(
                    *build_tile_arrays(h4, 4.0, rec.size,
                                       skirt_drop=drops[1], clutter=c4))
                t.mesh_l2 = _TexturedMesh(
                    *build_tile_arrays(h20, 20.0, rec.size,
                                       skirt_drop=drops[2], clutter=c20))
                t.tex = _upload_texture(decode_futs[rec.hgt_path].result())
                self.tiles.append(t)
            # Coarse surround ring + expansion rings: always-drawn far
            # chunks so the world keeps going past the fine scene —
            # heterogeneous chunk sizes are fine (cell derives per rec).
            self.surround = []
            for rec in (list(getattr(scene, "surround", []))
                        + list(getattr(scene, "surround2", []))
                        + list(getattr(scene, "surround3", []))):
                with np.load(rec.hgt_path) as z:
                    h = z["h"]
                mesh = _TexturedMesh(*punch_core_hole(
                    *build_tile_arrays(h, rec.size / (h.shape[0] - 3),
                                       rec.size, skirt_drop=70.0),
                    rec.x0, rec.z0,
                    (scene.x0, scene.z0, scene.x1, scene.z1)))
                rgb = np.asarray(Image.open(rec.tex_path).convert("RGB"),
                                 dtype=np.uint8)
                tex = _upload_texture(rgb)
                y_mid = float(h.mean())
                radius = float(np.hypot(rec.size * 0.71,
                                        (h.max() - h.min()) * 0.5) + 1.0)
                self.surround.append([mesh, tex, rec.x0, rec.z0, rec.size,
                                      y_mid, radius, rec])
        except Exception:
            self.dispose()
            raise
        self._crater_seen = 0          # scene.crater_rev consumed so far
        self._scorch_futs = []         # (future, kind, ref) pending swaps
        self._disposed = False

    # ---------------------------------------------------------- streaming

    def update(self, eye) -> None:
        """Build/evict L0 meshes around the eye (meshes only — every
        texture is already resident), and fold in new impact craters."""
        if self.scene.crater_rev != self._crater_seen:
            self._apply_craters()
        self._poll_scorch()
        ranked = sorted(self.tiles, key=lambda t: t.dist(eye))
        want = {t for t in ranked[:L0_LIVE_MAX] if t.dist(eye) < L0_DIST}
        for t in self.tiles:
            f = t.l0_future
            if f is None:
                continue
            if t not in want and not f.done():
                if f.cancel():
                    t.l0_future = None
                continue
            if f.done():
                t.l0_future = None
                try:
                    verts, indices = f.result()
                except Exception as exc:       # noqa: BLE001 — memo + L1
                    t.l0_failed = True
                    print(f"[cinematic] L0 build failed for "
                          f"{t.rec.hgt_path}: {exc}")
                    continue
                if t in want:                  # stale results are dropped
                    t.mesh_l0 = _TexturedMesh(verts, indices)
        for t in want:
            if (t.mesh_l0 is None and t.l0_future is None
                    and not t.l0_failed):
                t.l0_future = self._pool.submit(
                    _build_l0_arrays, t.rec.hgt_path, t.size, t.l0_skirt,
                    self._tile_delta(t, cell=2.0))
        live = [t for t in self.tiles if t.mesh_l0 is not None]
        for t in live:
            beyond_cap = t not in want and len(live) > L0_LIVE_MAX
            if t.dist(eye) > L0_EVICT_DIST or beyond_cap:
                t.mesh_l0.delete()
                t.mesh_l0 = None
                live.remove(t)

    # ------------------------------------------------------------ craters

    def _tile_delta(self, t, cell: float, baked=None):
        """Haloed crater delta grid for a core tile at ``cell`` m, or
        None when no crater touches it (the common case).  ``baked``
        is the tile's stored DSM at that cell (loaded on demand when
        omitted) — cut-to-target carving needs the real surface."""
        sc = self.scene
        if not getattr(sc, "_craters", None):
            return None
        if not sc.craters_intersecting(t.x0, t.z0, t.x0 + t.size,
                                       t.z0 + t.size):
            return None
        if baked is None:
            with np.load(t.rec.hgt_path) as z:
                baked = z[f"dsm_{int(cell)}m"]
        xs, zs = halo_axes(t.x0, t.z0, t.size, cell)
        return sc.crater_delta_grid(xs, zs, baked)

    def _apply_craters(self) -> None:
        """Rebuild meshes + queue texture scorch for every tile/chunk a
        NEW crater touches (impact moment: the blast masks the work)."""
        sc = self.scene
        since = self._crater_seen
        self._crater_seen = sc.crater_rev
        for t in self.tiles:
            news = sc.craters_intersecting(t.x0, t.z0, t.x0 + t.size,
                                           t.z0 + t.size, since_rev=since)
            if not news:
                continue
            with np.load(t.rec.hgt_path) as z:
                h2, h4, h20 = z["dsm_2m"], z["dsm_4m"], z["dsm_20m"]
                c4, c20 = z["clutter_4m"], z["clutter_20m"]
            d4 = self._tile_delta(t, cell=4.0, baked=h4)
            d20 = self._tile_delta(t, cell=20.0, baked=h20)
            drops = skirt_drops(h2, h4, h20)
            if t.mesh_l1 is not None:
                t.mesh_l1.delete()
            if t.mesh_l2 is not None:
                t.mesh_l2.delete()
            t.mesh_l1 = _TexturedMesh(*build_tile_arrays(
                h4 + (d4 if d4 is not None else 0.0), 4.0, t.size,
                skirt_drop=drops[1], clutter=c4))
            t.mesh_l2 = _TexturedMesh(*build_tile_arrays(
                h20 + (d20 if d20 is not None else 0.0), 20.0, t.size,
                skirt_drop=drops[2], clutter=c20))
            if t.mesh_l0 is not None:      # re-stream with the crater
                t.mesh_l0.delete()
                t.mesh_l0 = None
            if t.l0_future is not None:
                t.l0_future.cancel()
                t.l0_future = None
            t.l0_failed = False
            all_craters = sc.craters_intersecting(
                t.x0, t.z0, t.x0 + t.size, t.z0 + t.size)
            self._scorch_futs.append((self._pool.submit(
                _scorch_rgb, t.rec.tex_path, t.x0, t.z0, t.size,
                all_craters), "tile", t))
        for entry in self.surround:
            mesh, tex, x0, z0, size, y_mid, radius, rec = entry
            news = sc.craters_intersecting(x0, z0, x0 + size, z0 + size,
                                           since_rev=since)
            if not news:
                continue
            with np.load(rec.hgt_path) as z:
                h = z["h"]
            cell = size / (h.shape[0] - 3)
            xs = x0 + (np.arange(h.shape[1], dtype=np.float64) - 1.0) * cell
            zs = z0 + (np.arange(h.shape[0], dtype=np.float64) - 1.0) * cell
            h = h + sc.crater_delta_grid(xs, zs, h)
            entry[0].delete()
            entry[0] = _TexturedMesh(*punch_core_hole(
                *build_tile_arrays(h, cell, size, skirt_drop=70.0),
                x0, z0, (sc.x0, sc.z0, sc.x1, sc.z1)))
            all_craters = sc.craters_intersecting(x0, z0, x0 + size,
                                                  z0 + size)
            self._scorch_futs.append((self._pool.submit(
                _scorch_rgb, rec.tex_path, x0, z0, size, all_craters),
                "chunk", entry))

    def _poll_scorch(self) -> None:
        """GL thread: swap in finished scorched textures."""
        still = []
        for fut, kind, ref in self._scorch_futs:
            if not fut.done():
                still.append((fut, kind, ref))
                continue
            try:
                rgb = fut.result()
            except Exception as exc:       # noqa: BLE001 — keep old tex
                print(f"[cinematic] scorch failed: {exc}")
                continue
            new_tex = _upload_texture(rgb)
            if kind == "tile":
                if ref.tex:
                    glDeleteTextures([ref.tex])
                ref.tex = new_tex
            else:
                if ref[1]:
                    glDeleteTextures([ref[1]])
                ref[1] = new_tex
        self._scorch_futs = still

    # ------------------------------------------------------------ shadows

    def upload_shadow_mask(self, mask) -> int:
        """Upload a baked uint8 shadow mask (row 0 = south) as an R8
        texture; returns the GL id (kept for disposal)."""
        import OpenGL.GL as gl
        mask = np.ascontiguousarray(mask, dtype=np.uint8)
        tid = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, tid)
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        gl.glTexImage2D(GL_TEXTURE_2D, 0, gl.GL_R8, mask.shape[1],
                        mask.shape[0], 0, gl.GL_RED, GL_UNSIGNED_BYTE, mask)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glPixelStorei(GL_UNPACK_ALIGNMENT, 4)
        glBindTexture(GL_TEXTURE_2D, 0)
        self._shadow_texs.append(tid)
        return tid

    def set_shadow(self, tex: int, rect) -> None:
        """Select the active mood mask (tex 0 disables shadowing)."""
        self.shadow_tex = int(tex)
        self.shadow_rect = tuple(float(v) for v in rect)
        self.shadow_str = 1.0 if tex else 0.0

    def _bind_shadow(self) -> None:
        import OpenGL.GL as gl
        self.shader.set_int("u_shadow", 1)
        self.shader.set_float("u_shadow_str", self.shadow_str)
        self.shader.set_vec4("u_shadow_rect", self.shadow_rect)
        gl.glActiveTexture(gl.GL_TEXTURE1)
        glBindTexture(GL_TEXTURE_2D, self.shadow_tex)
        gl.glActiveTexture(GL_TEXTURE0)

    # ------------------------------------------------------------- draw

    def draw(self, renderer, camera) -> None:
        renderer.set_common(self.shader)
        self.shader.set_int("u_tex", 0)
        self._bind_shadow()
        if self._u_model is None:
            self._u_model = self.shader._loc("u_model")
        eye = camera.eye
        fwd = camera.forward
        glActiveTexture(GL_TEXTURE0)
        model = np.zeros((4, 4), dtype=np.float32)
        model[0, 0] = model[1, 1] = model[2, 2] = model[3, 3] = 1.0
        for mesh, tex, sx0, sz0, size, y_mid, radius, _rec in self.surround:
            cx = sx0 + size * 0.5 - eye[0]
            cy = y_mid - eye[1]
            cz = sz0 + size * 0.5 - eye[2]
            if (cx * fwd[0] + cy * fwd[1] + cz * fwd[2]) < -radius:
                continue
            model[0, 3] = sx0 - eye[0]
            model[1, 3] = -eye[1]
            model[2, 3] = sz0 - eye[2]
            self.shader.set_vec2("u_tile_xz", (sx0, sz0))
            glBindTexture(GL_TEXTURE_2D, tex)
            glUniformMatrix4fv(self._u_model, 1, GL_TRUE, model)
            mesh.draw()
        for t in self.tiles:
            cx = t.x0 + t.size * 0.5 - eye[0]
            cy = t.y_mid - eye[1]
            cz = t.z0 + t.size * 0.5 - eye[2]
            if (cx * fwd[0] + cy * fwd[1] + cz * fwd[2]) < -t.radius:
                continue
            d = t.dist(eye)
            if d < L0_EVICT_DIST and t.mesh_l0 is not None:
                mesh = t.mesh_l0
            elif d < L1_DIST:
                mesh = t.mesh_l1
            else:
                mesh = t.mesh_l2
            model[0, 3] = t.x0 - eye[0]
            model[1, 3] = -eye[1]
            model[2, 3] = t.z0 - eye[2]
            self.shader.set_vec2("u_tile_xz", (t.x0, t.z0))
            glBindTexture(GL_TEXTURE_2D, t.tex)
            glUniformMatrix4fv(self._u_model, 1, GL_TRUE, model)
            mesh.draw()
        glBindTexture(GL_TEXTURE_2D, 0)

    # ---------------------------------------------------------- lifecycle

    def dispose(self) -> None:
        if getattr(self, "_disposed", False):
            return
        self._disposed = True
        self._pool.shutdown(wait=False, cancel_futures=True)
        if getattr(self, "_shadow_texs", None):
            glDeleteTextures(self._shadow_texs)
            self._shadow_texs = []
            self.shadow_tex = 0
        for mesh, tex, *_rest in getattr(self, "surround", []):
            mesh.delete()
            if tex:
                glDeleteTextures([tex])
        self.surround = []
        for t in self.tiles:
            for mesh in (t.mesh_l0, t.mesh_l1, t.mesh_l2):
                if mesh is not None:
                    mesh.delete()
            if t.tex:
                glDeleteTextures([t.tex])
            t.mesh_l0 = t.mesh_l1 = t.mesh_l2 = None
            t.tex = 0
        self.shader.delete()
