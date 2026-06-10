"""Pygame window with an OpenGL 3.3 core profile context.

GL functions are only called inside ``Window`` methods, never at import time.
"""

from __future__ import annotations

import pygame
from OpenGL.GL import (
    GL_CULL_FACE,
    GL_DEPTH_TEST,
    GL_MULTISAMPLE,
    GL_PACK_ALIGNMENT,
    GL_RGB,
    GL_UNSIGNED_BYTE,
    glEnable,
    glPixelStorei,
    glReadPixels,
    glViewport,
)


class Window:
    """Owns the pygame display surface and the GL context."""

    def __init__(self, width: int = 1600, height: int = 900,
                 title: str = "ONIKS", hidden: bool = False):
        pygame.init()
        # GL attributes must be set BEFORE set_mode creates the context.
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 3)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK,
                                        pygame.GL_CONTEXT_PROFILE_CORE)
        pygame.display.gl_set_attribute(pygame.GL_DOUBLEBUFFER, 1)
        pygame.display.gl_set_attribute(pygame.GL_DEPTH_SIZE, 24)
        pygame.display.gl_set_attribute(pygame.GL_MULTISAMPLEBUFFERS, 1)
        pygame.display.gl_set_attribute(pygame.GL_MULTISAMPLESAMPLES, 4)

        flags = pygame.OPENGL | pygame.DOUBLEBUF
        flags |= pygame.HIDDEN if hidden else pygame.RESIZABLE
        pygame.display.set_mode((width, height), flags)
        pygame.display.set_caption(title)
        self._width = int(width)
        self._height = int(height)

        glEnable(GL_DEPTH_TEST)
        glEnable(GL_CULL_FACE)
        glEnable(GL_MULTISAMPLE)
        glViewport(0, 0, self._width, self._height)

    def swap(self) -> None:
        pygame.display.flip()

    def size(self) -> tuple[int, int]:
        return self._width, self._height

    def handle_resize(self, width: int, height: int) -> None:
        """Update the viewport after a pygame.VIDEORESIZE event."""
        self._width = max(1, int(width))
        self._height = max(1, int(height))
        glViewport(0, 0, self._width, self._height)

    def read_pixels_to_surface(self) -> pygame.Surface:
        """Read the back buffer into a pygame Surface (top row first)."""
        w, h = self._width, self._height
        glPixelStorei(GL_PACK_ALIGNMENT, 1)
        data = glReadPixels(0, 0, w, h, GL_RGB, GL_UNSIGNED_BYTE)
        surf = pygame.image.frombuffer(data, (w, h), "RGB")
        # GL rows start at the bottom; flip so row 0 is the top.
        return pygame.transform.flip(surf, False, True)
