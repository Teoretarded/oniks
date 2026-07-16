"""Fullscreen binocular mask for cinematic mode (GL-touching).

One alpha-blended quad over the 3D frame: two soft-edged circles of clear
glass, black everywhere else, with a hairline center post and a mil dot —
the classic handheld-binocular frame.  ``strength`` fades the mask in as
the player rolls the wheel."""

from __future__ import annotations

import numpy as np
from OpenGL.GL import (
    GL_ARRAY_BUFFER,
    GL_BLEND,
    GL_CULL_FACE,
    GL_DEPTH_TEST,
    GL_FALSE,
    GL_FLOAT,
    GL_ONE_MINUS_SRC_ALPHA,
    GL_SRC_ALPHA,
    GL_STATIC_DRAW,
    GL_TRIANGLE_STRIP,
    glBindBuffer,
    glBindVertexArray,
    glBlendFunc,
    glBufferData,
    glDeleteBuffers,
    glDeleteVertexArrays,
    glDisable,
    glDrawArrays,
    glEnable,
    glEnableVertexAttribArray,
    glGenBuffers,
    glGenVertexArrays,
    glVertexAttribPointer,
)

from engine.shader import Shader

_VERT = """
#version 330 core
layout(location=0) in vec2 a_pos;
out vec2 v_ndc;
void main(){ v_ndc = a_pos; gl_Position = vec4(a_pos, 0.0, 1.0); }
"""

_FRAG = """
#version 330 core
in vec2 v_ndc;
uniform float u_aspect;
uniform float u_strength;      // 0 = invisible, 1 = full mask
out vec4 frag;
void main(){
    vec2 p = vec2(v_ndc.x * u_aspect, v_ndc.y);
    float r = 0.62;
    float dl = length(p - vec2(-0.33, 0.0));
    float dr = length(p - vec2( 0.33, 0.0));
    float glass = min(dl, dr);                 // inside either barrel
    float mask = smoothstep(r - 0.045, r + 0.01, glass);
    // Hairline reticle in the right barrel only, fading with the mask.
    float post = (abs(p.x - 0.33) < 0.0016 && abs(p.y) < 0.30) ? 0.35 : 0.0;
    float alpha = max(mask, post) * u_strength;
    frag = vec4(0.0, 0.0, 0.0, min(alpha, 0.985));
}
"""


class BinocularOverlay:
    def __init__(self):
        self.shader = Shader(_VERT, _FRAG)
        quad = np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype=np.float32)
        self.vao = glGenVertexArrays(1)
        self.vbo = glGenBuffers(1)
        glBindVertexArray(self.vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
        glBufferData(GL_ARRAY_BUFFER, quad.nbytes, quad, GL_STATIC_DRAW)
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 8, None)
        glEnableVertexAttribArray(0)
        glBindVertexArray(0)

    def draw(self, aspect: float, strength: float) -> None:
        if strength <= 0.001:
            return
        glDisable(GL_DEPTH_TEST)
        glDisable(GL_CULL_FACE)      # engine front face is CW: don't cull
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        self.shader.use()
        self.shader.set_float("u_aspect", aspect)
        self.shader.set_float("u_strength", min(1.0, strength))
        glBindVertexArray(self.vao)
        glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
        glBindVertexArray(0)
        glEnable(GL_CULL_FACE)
        glEnable(GL_DEPTH_TEST)

    def delete(self) -> None:
        if self.vao:
            glDeleteVertexArrays(1, [self.vao])
            glDeleteBuffers(1, [self.vbo])
            self.vao = 0
            self.shader.delete()
