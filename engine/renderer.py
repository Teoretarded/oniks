"""Renderer: lit-mesh shader, frame begin, draw_mesh, fog/sun uniforms, culling.

This is the render boundary (LOCKED): positions arrive float64, are made
camera-relative via ``camera.rel`` and only then cast to float32, so there
is zero jitter even 600 km from the origin. Logarithmic depth keeps
z-precision over the 900 km far plane: the fragment shader writes the exact
per-pixel log depth (gl_FragDepth) while the vertex shader outputs z = 0 so
the near plane clips exactly at the camera plane — vertex-only log depth
interpolates linearly across triangles, which both mis-sorts and mis-clips
huge triangles (1.2 km terrain LOD2 cells) at grazing angles (Task 16b).

GL-touching module: never imported by unit tests.
"""

from __future__ import annotations

import numpy as np
from OpenGL.GL import (
    GL_COLOR_BUFFER_BIT,
    GL_CW,
    GL_DEPTH_BUFFER_BIT,
    glClear,
    glClearColor,
    glFrontFace,
)

from engine import math3d
from engine.shader import Shader
from engine.shaderlib import HAZE_GLSL

LIT_VERT = """
#version 330 core
layout(location=0) in vec3 a_pos; layout(location=1) in vec3 a_nrm; layout(location=2) in vec3 a_col;
uniform mat4 u_proj, u_view_rot, u_model;
out vec3 v_nrm; out vec3 v_col; out vec3 v_view_vec; out float v_flogz;
void main(){
    vec4 world_rel = u_model * vec4(a_pos, 1.0);      // camera-relative world
    v_view_vec = world_rel.xyz;
    v_nrm = mat3(u_model) * a_nrm;
    v_col = a_col;
    gl_Position = u_proj * u_view_rot * world_rel;
    // Depth comes from the fragment shader (exact per-pixel log depth via
    // v_flogz) — vertex-interpolated log depth mis-sorts and mis-clips
    // huge triangles (1.2 km terrain LOD2 cells) at grazing angles
    // (Task 16b). z = 0 makes the near plane clip exactly at the camera
    // plane (the only z linear in w does that) and disables far z-clipping,
    // which is fine: draws are culled at MAX_DRAW_DIST < FAR anyway.
    gl_Position.z = 0.0;
    v_flogz = 1.0 + gl_Position.w;
}
"""

LIT_FRAG = """
#version 330 core
in vec3 v_nrm; in vec3 v_col; in vec3 v_view_vec; in float v_flogz;
uniform vec3 u_sun_color;
uniform float u_log_depth_fcoef;
out vec4 frag;
""" + HAZE_GLSL + """
void main(){
    gl_FragDepth = log2(max(v_flogz, 1e-6)) * (u_log_depth_fcoef * 0.5);
    vec3 n = normalize(v_nrm);
    float ndl = max(dot(n, u_sun_dir), 0.0);
    vec3 hemi = mix(vec3(0.18,0.16,0.14), vec3(0.35,0.42,0.52), n.y*0.5+0.5);
    vec3 v = normalize(-v_view_vec);
    vec3 hv = normalize(v + u_sun_dir);
    float spec = pow(max(dot(n, hv), 0.0), 48.0) * 0.25;
    vec3 col = v_col * (u_sun_color * ndl + hemi) + u_sun_color * spec * step(0.01, ndl);
    frag = vec4(apply_haze(col, v_view_vec, u_cam_alt), 1.0);
}
"""


def _normalize(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    return v / np.linalg.norm(v)


SUN_DIR = _normalize([0.35, 0.42, 0.55])
SUN_COLOR = (1.0, 0.96, 0.88)
HAZE_DENSITY = 2.5e-5
HAZE_COLOR = (0.62, 0.70, 0.80)
SUN_HAZE_COLOR = (0.95, 0.86, 0.72)

FAR = 900_000.0
MAX_DRAW_DIST = 700_000.0

_IDENTITY3 = np.eye(3, dtype=np.float64)


class Renderer:
    """Owns the lit shader and per-frame camera matrices; culls and draws."""

    def __init__(self):
        # The LOCKED axes (X east, Y up, Z north) are a left-handed world,
        # so the (det -1) view rotation mirrors winding: model-space CCW
        # front faces arrive clockwise in NDC. Declare front = CW once.
        glFrontFace(GL_CW)
        self.lit = Shader(LIT_VERT, LIT_FRAG)
        self.far = FAR
        self.fcoef = 2.0 / np.log2(self.far + 1.0)
        self.camera = None
        self.proj = np.eye(4, dtype=np.float64)
        self.view_rot = np.eye(4, dtype=np.float64)

    def begin(self, camera, aspect) -> None:
        """Clear to haze color, store camera, compute proj/view_rot once."""
        glClearColor(HAZE_COLOR[0], HAZE_COLOR[1], HAZE_COLOR[2], 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        self.camera = camera
        self.proj = camera.proj(aspect)
        self.view_rot = camera.view_rot()
        self.set_common(self.lit)

    def set_common(self, shader: Shader) -> None:
        """Bind ``shader`` and set the common frame uniforms on it."""
        shader.use()
        shader.set_mat4("u_proj", self.proj)
        shader.set_mat4("u_view_rot", self.view_rot)
        shader.set_vec3("u_sun_dir", SUN_DIR)
        shader.set_vec3("u_sun_color", SUN_COLOR)
        shader.set_vec3("u_haze_color", HAZE_COLOR)
        shader.set_vec3("u_sun_haze_color", SUN_HAZE_COLOR)
        shader.set_float("u_haze_density", HAZE_DENSITY)
        shader.set_float("u_cam_alt", self.camera.eye[1])
        shader.set_float("u_log_depth_fcoef", self.fcoef)

    def draw_mesh(self, mesh, pos_f64, rot3x3=None, scale=1.0) -> None:
        """Draw ``mesh`` at a float64 world position with the lit shader.

        Culls when farther than MAX_DRAW_DIST or when the whole bounding
        sphere is behind the camera plane.
        """
        cam = self.camera
        rel = cam.rel(pos_f64)
        if float(np.linalg.norm(rel)) > MAX_DRAW_DIST:
            return
        if float(np.dot(rel, cam.forward)) < -mesh.radius * scale:
            return
        rot = _IDENTITY3 if rot3x3 is None else rot3x3
        model = math3d.compose(rot, rel.astype(np.float32), scale)
        self.lit.use()
        self.lit.set_mat4("u_model", model)
        mesh.draw()
