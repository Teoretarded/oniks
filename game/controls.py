"""Key bindings (final, also in README):

    ESC menu | M map | C camera | SPACE launch | 1/2 profile hi-lo/lo-lo
    P pause | N frame-step | - / = time accel down/up (1,2,4,8,16) | F2 screenshot
    free cam: WASD QE, mouse look (RMB drag), SHIFT fast, CTRL+SHIFT very fast

Plus T (temporary Task-18 debug, replaced by the Task-20 tactical map):
launch at the nearest contact. Time accel refuses to exceed 1x while a
missile is in EJECT/BOOST — the requested rate is kept here and the sandbox
auto-restores it once the launch reaches CLIMB/CRUISE.
"""

from __future__ import annotations

import pygame

from game.cameras import FREE_SPEEDS

# Time-acceleration ladder stepped by - / = (plan-fixed).
TIME_SCALES = (1.0, 2.0, 4.0, 8.0, 16.0)


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


class SandboxControls:
    """Full game bindings for SandboxState + free-cam passthrough.

    Owns the requested time-accel rate (TIME_SCALES index); the sandbox
    clamps it to 1x while a launch is in EJECT/BOOST.
    """

    def __init__(self, sandbox):
        self.sandbox = sandbox
        self.free = FreeCamControls(sandbox.rig.freecam)
        self._scale_idx = 0

    @property
    def requested_scale(self) -> float:
        return TIME_SCALES[self._scale_idx]

    def handle_event(self, ev) -> None:
        if ev.type == pygame.KEYDOWN:
            self._handle_key(ev.key)
        # Forward to the free cam while in free mode — and also while a
        # mouse-look drag is live, so leaving free mode mid-drag still sees
        # the button-up and releases the grab.
        if self.sandbox.rig.mode == "free" or self.free._looking:
            self.free.handle_event(ev)      # RMB mouse-look grab

    def _handle_key(self, key) -> None:
        sandbox = self.sandbox
        app = sandbox.app
        if key == pygame.K_m:
            sandbox.map_open = not sandbox.map_open   # map arrives in Task 20
        elif key == pygame.K_c:
            sandbox.rig.cycle_mode()
        elif key == pygame.K_SPACE:
            sandbox.request_launch()
        elif key == pygame.K_1:
            sandbox.profile = "hi-lo"
        elif key == pygame.K_2:
            sandbox.profile = "lo-lo"
        elif key == pygame.K_p:
            app.paused = not app.paused
        elif key == pygame.K_n:
            if app.paused:
                app.frame_step = True       # exactly one 120 Hz step
        elif key in (pygame.K_MINUS, pygame.K_KP_MINUS):
            self._scale_idx = max(0, self._scale_idx - 1)
        elif key in (pygame.K_EQUALS, pygame.K_KP_PLUS):
            self._scale_idx = min(len(TIME_SCALES) - 1, self._scale_idx + 1)
        elif key == pygame.K_F2:
            app.screenshot_requested = True
        elif key == pygame.K_t:
            # TEMPORARY (Task 18 debug): target + launch at the nearest
            # contact. The Task-20 tactical map replaces this with real
            # target selection.
            sandbox.debug_target_nearest()
            sandbox.request_launch()

    def update(self, dt_real: float) -> None:
        """Per-frame held-key poll (free-cam flight only, real time)."""
        if self.sandbox.rig.mode == "free":
            self.free.update(dt_real)
