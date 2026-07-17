"""Sky dome + shader: UV sphere centered on the camera, gradient + sun disc.

GL module (never imported by unit tests). Drawn FIRST each frame with depth
writes off so everything else paints over it; the dome follows the camera
(vertex positions ARE camera-relative), so no model matrix is needed.
"""

from __future__ import annotations

import numpy as np
from OpenGL.GL import (
    GL_CULL_FACE,
    GL_FALSE,
    GL_TRUE,
    glDepthMask,
    glDisable,
    glEnable,
)

from engine.mesh import Mesh
from engine.meshdata import MeshData
from engine.shader import Shader

SKY_RADIUS = 800_000.0


def build_sky_dome(radius: float = SKY_RADIUS, stacks: int = 16,
                   segments: int = 32) -> MeshData:
    """Full UV sphere (the camera can look below the horizon). Pure numpy."""
    phi = np.linspace(-np.pi / 2.0, np.pi / 2.0, stacks + 1)
    theta = np.linspace(0.0, 2.0 * np.pi, segments, endpoint=False)
    ph, th = np.meshgrid(phi, theta, indexing="ij")  # (stacks+1, segments)
    d = np.stack((np.cos(ph) * np.sin(th), np.sin(ph), np.cos(ph) * np.cos(th)),
                 axis=-1).reshape(-1, 3)
    v = np.zeros((len(d), 9), dtype=np.float32)
    v[:, 0:3] = d * radius
    v[:, 3:6] = -d                       # inward normals (unused by the shader)
    grid = np.arange((stacks + 1) * segments).reshape(stacks + 1, segments)
    a = grid[:-1, :]
    b = np.roll(grid[:-1, :], -1, axis=1)
    c = np.roll(grid[1:, :], -1, axis=1)
    e = grid[1:, :]
    # winding irrelevant: culling is disabled while the dome draws.
    # Pole rows collapse one triangle of each quad to zero area (a == b at
    # the south pole, c == e at the north pole), so drop those: the other
    # triangle of each quad fans from the pole and covers the cap alone.
    t0 = np.stack((a, c, b), axis=-1)[1:]    # skip south-pole row
    t1 = np.stack((a, e, c), axis=-1)[:-1]   # skip north-pole row
    idx = np.concatenate((t0.ravel(), t1.ravel()))
    return MeshData(v, idx.astype(np.uint32))


SKY_VERT = """
#version 330 core
layout(location=0) in vec3 a_pos;
uniform mat4 u_proj, u_view_rot;
uniform float u_log_depth_fcoef;
out vec3 v_dir;
void main(){
    v_dir = a_pos;
    gl_Position = u_proj * u_view_rot * vec4(a_pos, 1.0);
    gl_Position.z = (log2(max(1e-6, 1.0 + gl_Position.w)) * u_log_depth_fcoef - 1.0) * gl_Position.w;
}
"""

SKY_FRAG = """
#version 330 core
in vec3 v_dir;
uniform vec3 u_sun_dir, u_sun_haze_color;
uniform vec3 u_horizon_col, u_zenith_col, u_disc_col;
uniform float u_space_k;               // 0 ground .. 1 hard vacuum

float hash13(vec3 p){
    p = fract(p * 0.1031);
    p += dot(p, p.zyx + 31.32);
    return fract((p.x + p.y) * p.z);
}
vec3 hash33(vec3 p){
    p = fract(p * vec3(0.1031, 0.1030, 0.0973));
    p += dot(p, p.yxz + 33.33);
    return fract((p.xxy + p.yxx) * p.zyx);
}
// Procedural starfield: one candidate star per angular cell, a few
// bright, most invisible; plus a faint fixed Milky Way band.
vec3 stars(vec3 dir){
    vec3 g = dir * 220.0;
    vec3 id = floor(g);
    vec3 rnd = hash33(id);
    float d = length(g - (id + 0.15 + rnd * 0.7));
    float mag = pow(hash13(id + 7.0), 18.0);
    float disc = smoothstep(0.55, 0.0, d);
    vec3 tint = mix(vec3(0.72, 0.78, 1.00), vec3(1.00, 0.92, 0.80),
                    hash13(id + 3.0));
    float mw = pow(1.0 - abs(dot(dir, normalize(vec3(0.35, 0.9, 0.2)))),
                   3.0);
    return tint * disc * mag * 3.2 + vec3(0.030, 0.034, 0.050) * mw;
}

out vec4 frag;
void main(){
    vec3 dir = normalize(v_dir);
    vec3 atmo = mix(u_horizon_col, u_zenith_col,
                    pow(max(dir.y, 0.0), 0.45));
    // The atmosphere thins away with altitude; space is near-black
    // with stars, so the M ride keeps one continuous sky.
    vec3 space = vec3(0.002, 0.003, 0.006) + stars(dir);
    vec3 col = mix(atmo, space, u_space_k);
    float sd = dot(dir, u_sun_dir);
    float e0 = mix(0.9996, 0.99985, u_space_k);   // sharper disc in
    float e1 = mix(0.9999, 0.99995, u_space_k);   // vacuum, same sun
    col = mix(col, u_disc_col, smoothstep(e0, e1, sd));
    col += pow(max(sd, 0.0), 32.0) * 0.25 * u_sun_haze_color
           * (1.0 - u_space_k);                   // haze glow only in air
    frag = vec4(col, 1.0);
}
"""

# Default gradient: the daytime blue every non-cinematic mode has always
# drawn (the uniforms exist so cinematic light moods can restage the sky).
HORIZON_COL = (0.70, 0.78, 0.86)
ZENITH_COL = (0.18, 0.38, 0.62)
DISC_COL = (1.0, 1.0, 1.0)


class Sky:
    """GL wrapper: uploads the dome once; draw() with depth writes off."""

    def __init__(self):
        self.mesh = Mesh(build_sky_dome())
        self.shader = Shader(SKY_VERT, SKY_FRAG)
        self.horizon_col = HORIZON_COL
        self.zenith_col = ZENITH_COL
        self.disc_col = DISC_COL
        self.space_k = 0.0             # 0 ground .. 1 orbit (stars)

    def set_colors(self, horizon=None, zenith=None, disc=None) -> None:
        """Restage the dome for a light mood (None keeps a default)."""
        self.horizon_col = horizon or HORIZON_COL
        self.zenith_col = zenith or ZENITH_COL
        self.disc_col = disc or DISC_COL

    def draw(self, renderer) -> None:
        renderer.set_common(self.shader)
        self.shader.set_vec3("u_horizon_col", self.horizon_col)
        self.shader.set_vec3("u_zenith_col", self.zenith_col)
        self.shader.set_vec3("u_disc_col", self.disc_col)
        self.shader.set_float("u_space_k", self.space_k)
        glDepthMask(GL_FALSE)
        glDisable(GL_CULL_FACE)            # dome is viewed from inside
        self.mesh.draw()
        glEnable(GL_CULL_FACE)
        glDepthMask(GL_TRUE)

    def delete(self) -> None:
        self.mesh.delete()
        self.shader.delete()
