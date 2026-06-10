"""Key bindings — free-cam part (Task 9). The full game bindings (pause,
frame-step, time accel, launch, map) arrive with the sandbox state.

Free cam: WASD move, QE down/up, mouse look (right-drag), SHIFT x40 speed,
CTRL+SHIFT x400.
"""

from __future__ import annotations

import pygame

from game.cameras import FREE_SPEEDS


class FreeCamControls:
    """Drives a FreeCam: right-drag mouse look events + per-frame key polls."""

    def __init__(self, freecam):
        self.freecam = freecam
        self._looking = False

    def handle_event(self, ev) -> None:
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 3:
            self._looking = True
            pygame.mouse.set_visible(False)
            pygame.event.set_grab(True)
            pygame.mouse.get_rel()              # flush stale motion
        elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 3:
            self._looking = False
            pygame.event.set_grab(False)
            pygame.mouse.set_visible(True)

    def update(self, dt_real: float) -> None:
        """Poll held keys/mouse and move the camera (real time, unscaled)."""
        if self._looking:
            dx, dy = pygame.mouse.get_rel()
            self.freecam.look(dx, dy)
        keys = pygame.key.get_pressed()
        mods = pygame.key.get_mods()
        if mods & pygame.KMOD_SHIFT and mods & pygame.KMOD_CTRL:
            speed = FREE_SPEEDS[2]
        elif mods & pygame.KMOD_SHIFT:
            speed = FREE_SPEEDS[1]
        else:
            speed = FREE_SPEEDS[0]
        fwd = keys[pygame.K_w] - keys[pygame.K_s]
        strafe = keys[pygame.K_d] - keys[pygame.K_a]
        lift = keys[pygame.K_e] - keys[pygame.K_q]
        if fwd or strafe or lift:
            self.freecam.move(dt_real, fwd, strafe, lift, speed)
