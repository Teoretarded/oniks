"""GPU mesh: VAO/VBO/EBO upload and indexed draw.

GL counterpart to the GL-free ``engine.meshdata`` (LOCKED split: unit tests
import the builder only; this module is never imported by tests).

Vertex layout (LOCKED): interleaved float32 ``[px py pz nx ny nz r g b]``
(9 floats, stride 36 bytes), uint32 indices, attribute locations
0=pos, 1=normal, 2=color.
"""

from __future__ import annotations

import ctypes

import numpy as np
from OpenGL.GL import (
    GL_ARRAY_BUFFER,
    GL_ELEMENT_ARRAY_BUFFER,
    GL_FALSE,
    GL_FLOAT,
    GL_STATIC_DRAW,
    GL_TRIANGLES,
    GL_UNSIGNED_INT,
    glBindBuffer,
    glBindVertexArray,
    glBufferData,
    glDeleteBuffers,
    glDeleteVertexArrays,
    glDrawElements,
    glEnableVertexAttribArray,
    glGenBuffers,
    glGenVertexArrays,
    glVertexAttribPointer,
)

from engine.meshdata import MeshData

_STRIDE = 36  # 9 floats * 4 bytes


class Mesh:
    """Uploads a MeshData to the GPU and draws it with glDrawElements."""

    def __init__(self, md: MeshData):
        vertices = np.ascontiguousarray(md.vertices, dtype=np.float32)
        indices = np.ascontiguousarray(md.indices, dtype=np.uint32)
        self.index_count = int(indices.size)
        # Bounding-sphere radius about the model origin (renderer culling).
        self.radius = (float(np.linalg.norm(vertices[:, 0:3], axis=1).max())
                       if len(vertices) else 0.0)

        self.vao = glGenVertexArrays(1)
        self.vbo = glGenBuffers(1)
        self.ebo = glGenBuffers(1)

        glBindVertexArray(self.vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo)
        glBufferData(GL_ARRAY_BUFFER, vertices.nbytes, vertices,
                     GL_STATIC_DRAW)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices,
                     GL_STATIC_DRAW)

        for loc, offset in ((0, 0), (1, 12), (2, 24)):
            glVertexAttribPointer(loc, 3, GL_FLOAT, GL_FALSE, _STRIDE,
                                  ctypes.c_void_p(offset))
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
            self.vbo = 0
            self.ebo = 0
            self.index_count = 0
