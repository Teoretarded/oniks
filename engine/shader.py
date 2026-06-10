"""GLSL shader program: compile, link, cached uniform setters.

Matrices are uploaded with ``transpose=GL_TRUE`` so numpy's standard math
convention (translation in the last column, ``M @ v_col``) reads correctly
in GLSL (LOCKED convention).
"""

from __future__ import annotations

import numpy as np
from OpenGL.GL import (
    GL_COMPILE_STATUS,
    GL_FRAGMENT_SHADER,
    GL_LINK_STATUS,
    GL_TRUE,
    GL_VERTEX_SHADER,
    glAttachShader,
    glCompileShader,
    glCreateProgram,
    glCreateShader,
    glDeleteProgram,
    glDeleteShader,
    glGetProgramInfoLog,
    glGetProgramiv,
    glGetShaderInfoLog,
    glGetShaderiv,
    glGetUniformLocation,
    glLinkProgram,
    glShaderSource,
    glUniform1f,
    glUniform1i,
    glUniform2f,
    glUniform3f,
    glUniformMatrix4fv,
    glUseProgram,
)

_STAGE_NAMES = {GL_VERTEX_SHADER: "vertex", GL_FRAGMENT_SHADER: "fragment"}


def _decode(log) -> str:
    return log.decode("utf-8", "replace") if isinstance(log, bytes) else str(log)


def _compile_stage(stage: int, src: str) -> int:
    sid = glCreateShader(stage)
    glShaderSource(sid, src)
    glCompileShader(sid)
    if not glGetShaderiv(sid, GL_COMPILE_STATUS):
        log = _decode(glGetShaderInfoLog(sid))
        glDeleteShader(sid)
        raise RuntimeError(
            f"{_STAGE_NAMES.get(stage, stage)} shader compile failed:\n{log}")
    return sid


class Shader:
    """A linked GL program with a uniform-location cache."""

    def __init__(self, vert_src: str, frag_src: str):
        self.program = glCreateProgram()
        self._locs: dict[str, int] = {}
        vs = _compile_stage(GL_VERTEX_SHADER, vert_src)
        fs = _compile_stage(GL_FRAGMENT_SHADER, frag_src)
        glAttachShader(self.program, vs)
        glAttachShader(self.program, fs)
        glLinkProgram(self.program)
        glDeleteShader(vs)
        glDeleteShader(fs)
        if not glGetProgramiv(self.program, GL_LINK_STATUS):
            log = _decode(glGetProgramInfoLog(self.program))
            glDeleteProgram(self.program)
            raise RuntimeError(f"shader program link failed:\n{log}")

    def use(self) -> None:
        glUseProgram(self.program)

    def _loc(self, name: str) -> int:
        loc = self._locs.get(name)
        if loc is None:
            loc = glGetUniformLocation(self.program, name)
            self._locs[name] = loc
        return loc

    # Unknown uniform names (loc -1, e.g. optimized out) are silently ignored.

    def set_mat4(self, name: str, m) -> None:
        loc = self._loc(name)
        if loc != -1:
            glUniformMatrix4fv(loc, 1, GL_TRUE,
                               np.ascontiguousarray(m, np.float32))

    def set_vec3(self, name: str, v) -> None:
        loc = self._loc(name)
        if loc != -1:
            glUniform3f(loc, float(v[0]), float(v[1]), float(v[2]))

    def set_vec2(self, name: str, v) -> None:
        loc = self._loc(name)
        if loc != -1:
            glUniform2f(loc, float(v[0]), float(v[1]))

    def set_float(self, name: str, x) -> None:
        loc = self._loc(name)
        if loc != -1:
            glUniform1f(loc, float(x))

    def set_int(self, name: str, i) -> None:
        loc = self._loc(name)
        if loc != -1:
            glUniform1i(loc, int(i))
