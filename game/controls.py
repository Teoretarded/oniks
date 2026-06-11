"""Key bindings (final, also in README):

    ESC menu | M map | C camera | TAB platform (Bastion <-> S-300)
    SPACE launch | 1/2 profile hi-lo/lo-lo
    P pause | N frame-step | - / = time accel down/up (1,2,4,8,16) | F2 screenshot
    [ / ] camera subject cycle (missiles -> active TEL -> selected contact)
    free cam: WASD QE, mouse look (RMB drag), SHIFT fast, CTRL+SHIFT very fast
    orbit cam: RMB/LMB drag rotates around the subject, wheel zooms 8-600 m
    chase cam: wheel adjusts the follow distance 25-120 m
    map (while open): LMB target, RMB waypoint, X clear waypoints,
    wheel zoom at cursor, MMB drag / arrow keys pan

While the map is open its interactions consume events first; everything it
doesn't claim (SPACE, P, time accel, M itself...) falls through to the
normal bindings. Time accel refuses to exceed 1x while a missile is in
the launch cinematic — the requested rate is kept here and the sandbox auto-restores
it once the launch reaches CLIMB/CRUISE.
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
            self.release()

    def release(self) -> None:
        """End a mouse-look drag (button-up, or the state is left mid-drag)."""
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
    clamps it to 1x while a launch cinematic is playing.
    """

    def __init__(self, sandbox):
        self.sandbox = sandbox
        self.free = FreeCamControls(sandbox.rig.freecam)
        self._scale_idx = 0
        self._orbit_drag = False        # RMB/LMB orbit drag live (Task CAM)

    @property
    def requested_scale(self) -> float:
        return TIME_SCALES[self._scale_idx]

    def handle_event(self, ev) -> None:
        sandbox = self.sandbox
        # The open tactical map gets first claim on events (mouse + X).
        consumed = sandbox.map_open and sandbox.tactical_map.handle_event(ev)
        if not consumed and ev.type == pygame.KEYDOWN:
            self._handle_key(ev.key)
        # Orbit drags die on ANY button-up, even one the map consumed, so
        # opening the map mid-drag can never wedge the rotate state.
        if ev.type == pygame.MOUSEBUTTONUP and ev.button in (1, 3):
            self._orbit_drag = False
        if not consumed and not sandbox.map_open:
            self._handle_camera_mouse(ev)
        # Forward to the free cam while in free mode — and also while a
        # mouse-look drag is live, so leaving free mode (or opening the map)
        # mid-drag still sees the button-up and releases the grab.
        if self.free._looking or (not consumed and not sandbox.map_open
                                  and sandbox.rig.mode == "free"):
            self.free.handle_event(ev)      # RMB mouse-look grab

    def _handle_camera_mouse(self, ev) -> None:
        """Task CAM mouse layer: wheel zoom (orbit/chase ranges live in
        game/cameras.py) and the orbit-mode RMB/LMB rotate drag."""
        rig = self.sandbox.rig
        if ev.type == pygame.MOUSEWHEEL:
            rig.zoom(ev.y)
        elif (ev.type == pygame.MOUSEBUTTONDOWN and ev.button in (1, 3)
                and rig.mode == "orbit"):
            self._orbit_drag = True
        elif (ev.type == pygame.MOUSEMOTION and self._orbit_drag
                and rig.mode == "orbit"):
            rig.orbit_drag(ev.rel[0], ev.rel[1])

    def release_mouse(self) -> None:
        """Drop any live mouse-look/orbit drag (sandbox.leave safety)."""
        self.free.release()
        self._orbit_drag = False

    def _handle_key(self, key) -> None:
        sandbox = self.sandbox
        app = sandbox.app
        if key == pygame.K_ESCAPE:
            app.open_menu()                 # sim freezes; RESUME continues
        elif key == pygame.K_m:
            sandbox.map_open = not sandbox.map_open
            app.audio.ui_click()
        elif key == pygame.K_c:
            sandbox.rig.cycle_mode()
        elif key == pygame.K_TAB:
            sandbox.cycle_platform()
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
        elif key == pygame.K_LEFTBRACKET:
            sandbox.cycle_camera_subject(-1)
        elif key == pygame.K_RIGHTBRACKET:
            sandbox.cycle_camera_subject(+1)
        elif key in (pygame.K_MINUS, pygame.K_KP_MINUS):
            self._scale_idx = max(0, self._scale_idx - 1)
        elif key in (pygame.K_EQUALS, pygame.K_KP_PLUS):
            self._scale_idx = min(len(TIME_SCALES) - 1, self._scale_idx + 1)
        elif key == pygame.K_F2:
            app.screenshot_requested = True

    def update(self, dt_real: float) -> None:
        """Per-frame held-key poll (free-cam flight only, real time)."""
        if self.sandbox.rig.mode == "free":
            self.free.update(dt_real)
