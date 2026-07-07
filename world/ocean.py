"""Ring-LOD ocean: concentric grid rings around the camera + ocean shader.

Geometry is pure numpy (unit tests import this module, so no GL imports at
module level — the ``Ocean`` class defers them to ``__init__``).

Ring scheme: ring 0 is a solid grid out to its outer radius; each later ring
is a square annulus from 2 cells inside the previous ring's outer edge (the
overlap hides the seam when rings snap independently). Per frame each ring's
model translation is the camera xz snapped DOWN to that ring's own cell size,
so vertices always land on fixed world-space grid lines — waves never swim.
The shader receives the snapped origin (``u_world_origin``) and computes wave
phase from true world xz.

Vertices: y = 0, normal +Y; color.r carries the wave weight (1 near, 0 far),
g/b unused — the ocean shader computes color.
"""

from __future__ import annotations

import numpy as np

from engine import math3d
from engine.meshdata import MeshData
from engine.shaderlib import HAZE_GLSL

RINGS = [  # (outer_radius_m, cell_m, wave_weight)
    (2_000, 16, 1.0),
    (8_000, 64, 1.0),
    (32_000, 256, 0.0),
    (130_000, 1_500, 0.0),
    (700_000, 12_000, 0.0),
]

# F3-P1 Douglas sea state -> wave-amplitude scale (u_sea_amp).  Douglas
# significant wave heights (mid-band, m): 0/0.03/0.3/0.88/1.88/3.25/5.0/
# 7.5/11.5/16, normalized to state 3 (0.88 m = today's implicit sea, so
# scale(3) == 1.0 EXACTLY — the locked identity).  Pure vertical sine
# displacement cannot self-intersect, so the tall states are honest, just
# steep.  Visual-only: the sim NEVER reads this (clutter physics lives in
# sim/clutter.py — the F3 determinism guard).
_SEA_AMP_TABLE = (0.0, 0.06, 0.34, 1.0, 2.14, 3.69, 5.68, 8.52, 13.07,
                  18.18)


def sea_amp_scale(sea_state: int) -> float:
    """Gerstner/sine amplitude multiplier for a Douglas sea state 0-9
    (clamped).  State 3 returns exactly 1.0 (byte-identical default)."""
    return _SEA_AMP_TABLE[min(max(int(sea_state), 0), 9)]


def _build_ring(outer: float, cell: float, hole_half: float,
                wave_weight: float) -> MeshData:
    """Square grid out to >= ``outer`` with the quads whose footprint lies
    entirely inside the centered square hole of half-width ``hole_half``
    removed (hole_half <= 0 -> solid grid). Unused vertices are compacted."""
    n = int(np.ceil(outer / cell))
    coords = np.arange(-n, n + 1, dtype=np.float64) * cell  # (W,)
    w = 2 * n + 1
    # A grid interval is inside the hole iff both endpoints are.
    inside = np.abs(coords) <= hole_half
    seg_in = inside[:-1] & inside[1:]
    keep = ~(seg_in[None, :] & seg_in[:, None])  # (rows=z segs, cols=x segs)

    grid = np.arange(w * w, dtype=np.int64).reshape(w, w)  # rows=z, cols=x
    v00 = grid[:-1, :-1][keep]
    v10 = grid[:-1, 1:][keep]
    v01 = grid[1:, :-1][keep]
    v11 = grid[1:, 1:][keep]
    idx = np.stack((v00, v11, v10, v00, v01, v11), axis=1).ravel()

    used = np.zeros(w * w, dtype=bool)
    used[idx] = True
    remap = np.cumsum(used, dtype=np.int64) - 1
    indices = remap[idx].astype(np.uint32)

    gx, gz = np.meshgrid(coords, coords)  # gx varies along cols, gz along rows
    v = np.zeros((int(used.sum()), 9), dtype=np.float32)
    v[:, 0] = gx.ravel()[used]
    v[:, 2] = gz.ravel()[used]
    v[:, 4] = 1.0           # normal +Y (displaced analytically in the shader)
    v[:, 6] = wave_weight   # color.r = wave weight
    return MeshData(v, indices)


def build_ocean_rings() -> list[MeshData]:
    rings: list[MeshData] = []
    for i, (outer, cell, ww) in enumerate(RINGS):
        hole_half = 0.0 if i == 0 else RINGS[i - 1][0] - 2.0 * cell
        rings.append(_build_ring(outer, cell, hole_half, ww))
    return rings


OCEAN_VERT = """
#version 330 core
layout(location=0) in vec3 a_pos; layout(location=1) in vec3 a_nrm; layout(location=2) in vec3 a_col;
uniform mat4 u_proj, u_view_rot, u_model;
uniform vec2 u_world_origin;
uniform float u_time;
uniform float u_sea_amp;   // F3-P1: Douglas sea-state amplitude scale (1.0 = state 3)
out vec3 v_nrm; out vec3 v_view_vec; out float v_flogz;
void main(){
    vec2 wxz = a_pos.xz + u_world_origin;   // true world xz -> waves don't swim
    float ww = a_col.r;                      // wave weight
    // 4 directional sines: dir, spatial freq (rad/m), amplitude (m), speed (m/s).
    // d3 (S5 glint pass) heads down the golden angle (2.39996 rad) with a 37 m
    // wavelength — irrational-ish vs the others, so the four phases never
    // re-align into the repeating interference lattice three waves made.
    vec2  d0 = vec2( 0.78,  0.62), d1 = vec2(-0.45, 0.89), d2 = vec2(0.95, -0.31), d3 = vec2(0.675, -0.737);
    float f0 = 6.2831853/22.0,     f1 = 6.2831853/59.0,    f2 = 6.2831853/13.0,    f3 = 6.2831853/37.0;
    float a0 = 0.35,               a1 = 0.55,              a2 = 0.18,              a3 = 0.26;
    float s0 = 4.0,                s1 = 6.5,               s2 = 3.1,               s3 = 4.7;
    float p0 = dot(d0, wxz)*f0 + u_time*s0*f0;
    float p1 = dot(d1, wxz)*f1 + u_time*s1*f1;
    float p2 = dot(d2, wxz)*f2 + u_time*s2*f2;
    float p3 = dot(d3, wxz)*f3 + u_time*s3*f3;
    float y = ww * u_sea_amp * (a0*sin(p0) + a1*sin(p1) + a2*sin(p2) + a3*sin(p3));
    float c0 = a0*f0*cos(p0), c1 = a1*f1*cos(p1), c2 = a2*f2*cos(p2), c3 = a3*f3*cos(p3);
    float na = ww * u_sea_amp;   // slope terms scale with the amplitude
    v_nrm = normalize(vec3(-na*(c0*d0.x + c1*d1.x + c2*d2.x + c3*d3.x),
                           1.0,
                           -na*(c0*d0.y + c1*d1.y + c2*d2.y + c3*d3.y)));
    vec4 world_rel = u_model * vec4(a_pos.x, y, a_pos.z, 1.0);  // camera-relative
    v_view_vec = world_rel.xyz;
    gl_Position = u_proj * u_view_rot * world_rel;
    // Depth comes from the fragment shader (exact per-pixel log depth via
    // v_flogz); z = 0 clips at the camera plane — see the lit shader in
    // engine/renderer.py (Task 16b).
    gl_Position.z = 0.0;
    v_flogz = 1.0 + gl_Position.w;
}
"""

OCEAN_FRAG = """
#version 330 core
in vec3 v_nrm; in vec3 v_view_vec; in float v_flogz;
uniform vec3 u_sun_color;
uniform float u_log_depth_fcoef;
out vec4 frag;
""" + HAZE_GLSL + """
void main(){
    gl_FragDepth = log2(max(v_flogz, 1e-6)) * (u_log_depth_fcoef * 0.5);
    vec3 n = normalize(v_nrm);
    vec3 v = normalize(-v_view_vec);
    vec3 col = mix(vec3(0.045, 0.14, 0.21), u_haze_color,
                   pow(1.0 - max(dot(n, v), 0.0), 5.0));      // deep water + fresnel
    vec3 hv = normalize(v + u_sun_dir);
    // Sun glint, faded with distance (S5 glint pass): a sharp pow(600)
    // everywhere turned the periodically-sampled mid-distance waves into a
    // repeating dot lattice. Far water gets a broader, dimmer highlight
    // (unresolved micro-glints), near water keeps crisp sparkle.
    float gt = clamp(length(v_view_vec) / 9000.0, 0.0, 1.0);
    float spow = mix(600.0, 140.0, gt);
    float sint = mix(1.2, 0.30, gt);
    col += u_sun_color * pow(max(dot(n, hv), 0.0), spow) * sint;
    frag = vec4(apply_haze(col, v_view_vec, u_cam_alt), 1.0);
}
"""


class Ocean:
    """GL wrapper: uploads the ring meshes once, draws them camera-snapped."""

    def __init__(self):
        from engine.mesh import Mesh        # deferred: keep module GL-free
        from engine.shader import Shader
        self.meshes = [Mesh(md) for md in build_ocean_rings()]
        self.shader = Shader(OCEAN_VERT, OCEAN_FRAG)

    def draw(self, renderer, camera, time: float,
             sea_amp: float = 1.0) -> None:
        renderer.set_common(self.shader)
        self.shader.set_float("u_time", float(time) % 3600.0)
        # F3-P1: default 1.0 keeps every legacy caller byte-identical.
        self.shader.set_float("u_sea_amp", float(sea_amp))
        for (_outer, cell, _ww), mesh in zip(RINGS, self.meshes):
            sx = np.floor(camera.eye[0] / cell) * cell
            sz = np.floor(camera.eye[2] / cell) * cell
            rel = camera.rel(np.array([sx, 0.0, sz]))  # float64 -> f32 at upload
            self.shader.set_mat4("u_model", math3d.compose(np.eye(3), rel))
            self.shader.set_vec2("u_world_origin", (sx, sz))
            mesh.draw()

    def delete(self) -> None:
        for mesh in self.meshes:
            mesh.delete()
        self.meshes = []
