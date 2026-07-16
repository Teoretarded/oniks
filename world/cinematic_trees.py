"""Instanced-looking crossed-billboard trees for cinematic terrain.

Each baked tree expands to two crossed vertical quads in one static tile
VBO.  Tiles are uploaded lazily on first visible draw, while one procedural
RGBA atlas is shared by the scene.  Positions remain tile-local in the VBO;
the draw path subtracts the float64 camera eye before the float32 model
translation reaches the GPU boundary.

The module deliberately performs no OpenGL import at module import time.
That keeps :func:`build_tree_arrays` usable by headless tests; OpenGL and
``engine.shader`` are loaded only when :class:`CinematicTrees` is created.
The shader follows the renderer's locked fragment log-depth convention and
shared haze block.  World axes are X east, Y up, Z north.
"""

from __future__ import annotations

import os
import re

import numpy as np
from PIL import Image

from engine.shaderlib import HAZE_GLSL


TREE_DRAW_DIST = 2500.0
ATLAS_COLUMNS = 3
ATLAS_CELL_PX = 256
ATLAS_WIDTH_PX = ATLAS_COLUMNS * ATLAS_CELL_PX
UV_HEIGHT_SCALE = 65536.0


TREE_VERT = """
#version 330 core
layout(location=0) in vec3 a_pos;
layout(location=1) in vec2 a_uv;
layout(location=2) in vec3 a_tint;
uniform mat4 u_proj, u_view_rot, u_model;
uniform vec2 u_tile_xz;
uniform float u_time;
out vec2 v_uv;
out vec3 v_tint;
out vec3 v_view_vec;
out vec2 v_world_xz;
out float v_flogz;
void main(){
    // Top V is a tiny height payload (height / 65536), visually
    // indistinguishable from v=0.  Base V remains 1.  This preserves the
    // fixed pos3/uv2/tint3 layout while giving the top vertices exact sway.
    float top = 1.0 - step(0.5, a_uv.y);
    float tree_height = top * a_uv.y * 65536.0;
    vec3 p = a_pos;
    vec2 world_xz = a_pos.xz + u_tile_xz;
    float wave = sin(u_time * 0.9
                   + dot(world_xz, vec2(0.071, 0.113)))
               * tree_height * 0.012 * top;
    p.xz += vec2(0.78, 0.63) * wave;
    vec4 world_rel = u_model * vec4(p, 1.0);
    v_uv = a_uv;
    v_tint = a_tint;
    v_view_vec = world_rel.xyz;
    v_world_xz = world_xz;
    gl_Position = u_proj * u_view_rot * world_rel;
    gl_Position.z = 0.0;
    v_flogz = 1.0 + gl_Position.w;
}
"""


TREE_FRAG = """
#version 330 core
in vec2 v_uv;
in vec3 v_tint;
in vec3 v_view_vec;
in vec2 v_world_xz;
in float v_flogz;
uniform sampler2D u_atlas;
uniform sampler2D u_shadow;            // baked per-mood terrain shadow
uniform vec4 u_shadow_rect;
uniform float u_shadow_str;
uniform vec3 u_sun_color;
uniform float u_log_depth_fcoef;
uniform float u_hemi_gain;
out vec4 frag;
""" + HAZE_GLSL + """
void main(){
    vec4 texel = texture(u_atlas, v_uv);
    if (texel.a < 0.5) discard;
    gl_FragDepth = log2(max(v_flogz, 1e-6))
                 * (u_log_depth_fcoef * 0.5);

    // A soft crown normal supplies stable form lighting to both crossed
    // planes without exposing their geometric orientation.
    float crown_x = fract(v_uv.x * 3.0) * 2.0 - 1.0;
    vec3 n = normalize(vec3(crown_x * 0.55, 0.78, 0.36));
    float raw = dot(n, u_sun_dir);
    float ndl = clamp((raw + 0.4) / 1.4, 0.0, 1.0);
    ndl *= ndl;
    vec3 hemi = mix(vec3(0.24, 0.22, 0.19), vec3(0.35, 0.42, 0.52),
                    n.y * 0.5 + 0.5);
    vec3 albedo = texel.rgb * (vec3(0.52) + v_tint * 1.45);
    // Trees stand in the same baked mountain shadow as the ground.
    vec2 suv = (v_world_xz - u_shadow_rect.xy) * u_shadow_rect.zw;
    float shadow = texture(u_shadow, suv).r * u_shadow_str;
    float sun_vis = 1.0 - shadow * 0.92;
    vec3 lit = albedo * (u_sun_color * ndl * 0.82 * sun_vis
                         + hemi * 1.05 * u_hemi_gain
                           * (1.0 - shadow * 0.22));
    frag = vec4(apply_haze(lit, v_view_vec, u_cam_alt), 1.0);
}
"""


def _record_arrays(
    x,
    z,
    base_y,
    height,
    radius,
    tint,
    species,
) -> tuple[np.ndarray, ...]:
    """Validate and normalize one set of tree record arrays."""
    arrays = tuple(np.asarray(a) for a in
                   (x, z, base_y, height, radius, species))
    x, z, base_y, height, radius, species = (a.ravel() for a in arrays)
    tint = np.asarray(tint)
    n = x.size
    if not all(a.size == n for a in (z, base_y, height, radius, species)):
        raise ValueError("tree record arrays must have equal lengths")
    if tint.shape != (n, 3):
        raise ValueError("tint must have shape (N, 3)")
    return (x.astype(np.float32, copy=False),
            z.astype(np.float32, copy=False),
            base_y.astype(np.float32, copy=False),
            height.astype(np.float32, copy=False),
            radius.astype(np.float32, copy=False),
            tint.astype(np.float32, copy=False),
            species.astype(np.uint8, copy=False))


def build_tree_arrays(
    x,
    z=None,
    base_y=None,
    height=None,
    radius=None,
    tint=None,
    species=None,
) -> tuple[np.ndarray, np.ndarray]:
    """Build GL-free crossed-quad geometry from baked tree records.

    ``x`` may be a mapping/``np.load`` result containing all seven named
    arrays, or the arrays may be passed separately.  Returns float32 verts
    with layout ``[pos3 uv2 tint3]`` (eight vertices per tree) and uint32
    triangle indices (twelve per tree).  Both quads span exactly
    ``base_y .. base_y + height`` and have width ``2 * radius``.

    The tiny top-V value packs height for the vertex shader's wind sway;
    it stays within the species atlas column and within the normal [0, 1]
    UV range.  At 45 m it moves less than 0.36 atlas pixels from v=0.
    """
    if z is None and all(v is None for v in
                         (base_y, height, radius, tint, species)):
        records = x
        x = records["x"]
        z = records["z"]
        base_y = records["base_y"]
        height = records["height"]
        radius = records["radius"]
        tint = records["tint"]
        species = records["species"]
    if any(v is None for v in (z, base_y, height, radius, tint, species)):
        raise ValueError("all tree record arrays are required")

    x, z, base_y, height, radius, tint, species = _record_arrays(
        x, z, base_y, height, radius, tint, species)
    n = x.size
    verts = np.empty((n, 8, 8), dtype=np.float32)
    indices = np.empty((n, 12), dtype=np.uint32)
    if n == 0:
        return verts.reshape(0, 8), indices.ravel()

    top_y = base_y + height
    # One-pixel inset prevents neighbouring atlas columns bleeding in mips.
    sp = np.clip(species.astype(np.int32), 0, ATLAS_COLUMNS - 1)
    u0 = (sp * ATLAS_CELL_PX + 1.0) / ATLAS_WIDTH_PX
    u1 = ((sp + 1) * ATLAS_CELL_PX - 1.0) / ATLAS_WIDTH_PX
    v_top = np.minimum(height / np.float32(UV_HEIGHT_SCALE),
                       np.float32(0.49))

    # Quad A: east-west plane at constant Z.
    verts[:, 0, 0:3] = np.stack((x - radius, base_y, z), axis=1)
    verts[:, 1, 0:3] = np.stack((x + radius, base_y, z), axis=1)
    verts[:, 2, 0:3] = np.stack((x + radius, top_y, z), axis=1)
    verts[:, 3, 0:3] = np.stack((x - radius, top_y, z), axis=1)
    # Quad B: north-south plane at constant X.
    verts[:, 4, 0:3] = np.stack((x, base_y, z - radius), axis=1)
    verts[:, 5, 0:3] = np.stack((x, base_y, z + radius), axis=1)
    verts[:, 6, 0:3] = np.stack((x, top_y, z + radius), axis=1)
    verts[:, 7, 0:3] = np.stack((x, top_y, z - radius), axis=1)

    for left, right, top_right, top_left in ((0, 1, 2, 3),
                                             (4, 5, 6, 7)):
        verts[:, left, 3] = u0
        verts[:, right, 3] = u1
        verts[:, top_right, 3] = u1
        verts[:, top_left, 3] = u0
        verts[:, left, 4] = 1.0
        verts[:, right, 4] = 1.0
        verts[:, top_right, 4] = v_top
        verts[:, top_left, 4] = v_top
    verts[:, :, 5:8] = tint[:, None, :]

    base = np.arange(n, dtype=np.uint32)[:, None] * np.uint32(8)
    pattern = np.array([0, 2, 1, 0, 3, 2,
                        4, 6, 5, 4, 7, 6], dtype=np.uint32)
    indices[:] = base + pattern[None, :]
    return np.ascontiguousarray(verts.reshape(n * 8, 8)), indices.ravel()


class _TreeMesh:
    """One VAO, static VBO and static index buffer for a tile."""

    __slots__ = ("gl", "vao", "vbo", "ebo", "index_count")

    def __init__(self, gl, verts: np.ndarray, indices: np.ndarray):
        import ctypes

        self.gl = gl
        verts = np.ascontiguousarray(verts, dtype=np.float32)
        indices = np.ascontiguousarray(indices, dtype=np.uint32)
        self.index_count = int(indices.size)
        self.vao = gl.glGenVertexArrays(1)
        self.vbo = gl.glGenBuffers(1)
        self.ebo = gl.glGenBuffers(1)
        gl.glBindVertexArray(self.vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, verts.nbytes, verts,
                        gl.GL_STATIC_DRAW)
        gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, self.ebo)
        gl.glBufferData(gl.GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices,
                        gl.GL_STATIC_DRAW)
        stride = 32
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, stride,
                                 ctypes.c_void_p(0))
        gl.glVertexAttribPointer(1, 2, gl.GL_FLOAT, gl.GL_FALSE, stride,
                                 ctypes.c_void_p(12))
        gl.glVertexAttribPointer(2, 3, gl.GL_FLOAT, gl.GL_FALSE, stride,
                                 ctypes.c_void_p(20))
        for loc in (0, 1, 2):
            gl.glEnableVertexAttribArray(loc)
        gl.glBindVertexArray(0)

    def draw(self) -> None:
        self.gl.glBindVertexArray(self.vao)
        self.gl.glDrawElements(self.gl.GL_TRIANGLES, self.index_count,
                               self.gl.GL_UNSIGNED_INT, None)
        self.gl.glBindVertexArray(0)

    def delete(self) -> None:
        if self.vao:
            self.gl.glDeleteVertexArrays(1, [self.vao])
            self.gl.glDeleteBuffers(2, [self.vbo, self.ebo])
            self.vao = self.vbo = self.ebo = 0


class _Tile:
    """Tree-file record plus lazy GPU mesh for one terrain tile."""

    __slots__ = ("path", "x0", "z0", "size", "y_mid", "radius",
                 "mesh", "failed")

    def __init__(self, path: str, x0: float, z0: float, size: float):
        self.path = path
        self.x0, self.z0, self.size = float(x0), float(z0), float(size)
        self.mesh = None
        self.failed = False
        with np.load(path) as records:
            base = np.asarray(records["base_y"], dtype=np.float32)
            tops = base + np.asarray(records["height"], dtype=np.float32)
        low = float(base.min())
        high = float(tops.max())
        self.y_mid = (low + high) * 0.5
        self.radius = float(np.hypot(size * 0.71, (high - low) * 0.5) + 1.0)

    def rect_dist(self, eye) -> float:
        """Horizontal distance from an eye point to this tile rectangle."""
        dx = max(self.x0 - eye[0], 0.0,
                 eye[0] - (self.x0 + self.size))
        dz = max(self.z0 - eye[2], 0.0,
                 eye[2] - (self.z0 + self.size))
        return float(np.hypot(dx, dz))


def _tree_path(scene_dir: str, rec) -> str:
    """Resolve a SceneTile/dict record to its baked trees file."""
    if isinstance(rec, dict):
        hgt = rec["hgt"]
    else:
        hgt = rec.hgt_path
    name = os.path.basename(hgt)
    match = re.fullmatch(r"tile_(.+)_hgt\.npz", name)
    if not match:
        raise ValueError(f"unexpected cinematic tile name: {name}")
    return os.path.join(scene_dir, "trees_" + match.group(1) + ".npz")


def _tile_fields(rec) -> tuple[float, float, float]:
    if isinstance(rec, dict):
        return float(rec["x0"]), float(rec["z0"]), float(rec["size"])
    return float(rec.x0), float(rec.z0), float(rec.size)


def _upload_atlas(gl, path: str) -> int:
    """Upload the shared RGBA atlas with mipmapped linear filtering."""
    with Image.open(path) as image:
        rgba = np.ascontiguousarray(np.asarray(image.convert("RGBA"),
                                               dtype=np.uint8))
    texture = gl.glGenTextures(1)
    gl.glBindTexture(gl.GL_TEXTURE_2D, texture)
    gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
    gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8,
                    rgba.shape[1], rgba.shape[0], 0,
                    gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, rgba)
    gl.glGenerateMipmap(gl.GL_TEXTURE_2D)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER,
                       gl.GL_LINEAR_MIPMAP_LINEAR)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER,
                       gl.GL_LINEAR)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S,
                       gl.GL_CLAMP_TO_EDGE)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T,
                       gl.GL_CLAMP_TO_EDGE)
    gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 4)
    gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
    return texture


class CinematicTrees:
    """Lazy tile VBOs and the shared billboard atlas for one scene."""

    def __init__(self, scene_dir: str, tiles):
        import OpenGL.GL as gl
        from engine.shader import Shader

        self.gl = gl
        self.scene_dir = scene_dir
        self.shader = None
        self.texture = 0
        # Baked mood shadow, SHARED with the terrain: the state points
        # these at CinematicTerrain's uploaded mask.
        self.shadow_tex = 0
        self.shadow_rect = (0.0, 0.0, 1.0, 1.0)
        self.shadow_str = 0.0
        self.tiles: list[_Tile] = []
        self._disposed = False
        self._model = np.eye(4, dtype=np.float32)
        # A scene without a tree bake (no DSM data — Yosemite — or the
        # baker simply hasn't run) is a NO-TREES scene, not a crash:
        # disable before touching any GL state.
        atlas_path = os.path.join(scene_dir, "tree_atlas.png")
        self.enabled = os.path.isfile(atlas_path)
        if not self.enabled:
            print(f"[cinematic] no tree bake in {scene_dir} - "
                  f"run tools/bake_cinematic_trees.py to add forests")
            return
        try:
            self.shader = Shader(TREE_VERT, TREE_FRAG)
            self.texture = _upload_atlas(gl, atlas_path)
            for rec in tiles:
                path = _tree_path(scene_dir, rec)
                if os.path.isfile(path):
                    self.tiles.append(_Tile(path, *_tile_fields(rec)))
        except Exception:
            self.dispose()
            raise

    def _ensure_mesh(self, tile: _Tile) -> None:
        """Build and upload a tile once, memoizing load failures."""
        if tile.mesh is not None or tile.failed:
            return
        try:
            with np.load(tile.path) as records:
                verts, indices = build_tree_arrays(records)
            tile.mesh = _TreeMesh(self.gl, verts, indices)
        except Exception as exc:  # noqa: BLE001 - retain other forest tiles
            tile.failed = True
            print(f"[cinematic] tree VBO failed for {tile.path}: {exc}")

    def draw(self, renderer, camera, time: float) -> None:
        """Draw nearby, forward-facing tiles with two-sided alpha testing."""
        if not self.enabled or not self.tiles:
            return
        gl = self.gl
        renderer.set_common(self.shader)
        self.shader.set_int("u_atlas", 0)
        self.shader.set_float("u_time", time)
        # Shared mood shadow mask (owned/uploaded by CinematicTerrain).
        self.shader.set_int("u_shadow", 1)
        self.shader.set_float("u_shadow_str", self.shadow_str)
        self.shader.set_vec4("u_shadow_rect", self.shadow_rect)
        gl.glActiveTexture(gl.GL_TEXTURE1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.shadow_tex)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.texture)
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDisable(gl.GL_BLEND)
        gl.glDisable(gl.GL_CULL_FACE)
        try:
            eye = camera.eye
            fwd = camera.forward
            model = self._model
            for tile in self.tiles:
                if tile.rect_dist(eye) >= TREE_DRAW_DIST:
                    continue
                cx = tile.x0 + tile.size * 0.5 - eye[0]
                cy = tile.y_mid - eye[1]
                cz = tile.z0 + tile.size * 0.5 - eye[2]
                if cx * fwd[0] + cy * fwd[1] + cz * fwd[2] < -tile.radius:
                    continue
                self._ensure_mesh(tile)
                if tile.mesh is None:
                    continue
                # Subtract in float64, then assign into the float32 GPU matrix.
                model[0, 3] = tile.x0 - eye[0]
                model[1, 3] = -eye[1]
                model[2, 3] = tile.z0 - eye[2]
                self.shader.set_mat4("u_model", model)
                self.shader.set_vec2("u_tile_xz", (tile.x0, tile.z0))
                tile.mesh.draw()
        finally:
            gl.glEnable(gl.GL_CULL_FACE)
            gl.glBindTexture(gl.GL_TEXTURE_2D, 0)

    def dispose(self) -> None:
        """Delete all scene-owned GL objects; safe to call more than once."""
        if self._disposed:
            return
        self._disposed = True
        for tile in self.tiles:
            if tile.mesh is not None:
                tile.mesh.delete()
                tile.mesh = None
        if self.texture:
            self.gl.glDeleteTextures([self.texture])
            self.texture = 0
        if self.shader is not None:
            self.shader.delete()
            self.shader = None
