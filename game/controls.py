"""Sandbox input: every action routed through the rebindable Keybinds table.

Default bindings (rebind in SETTINGS; persisted to %APPDATA%\\ONIKS):

    ESC pause menu | M map | C camera | TAB platform (Bastion <-> S-300)
    SPACE launch | 1/2 profile hi-lo/lo-lo
    P pause | N frame-step | - / = time accel down/up (1,2,4,8,16) | F2 screenshot
    [ / ] camera subject cycle (missiles -> active TEL -> selected contact)
    F1 controls overlay (generated live from the binding table)
    free cam: WASD QE, mouse look (RMB drag), SHIFT fast, CTRL+SHIFT very fast
    orbit cam: RMB/LMB drag rotates around the subject, wheel zooms 8-600 m
    chase cam: wheel adjusts the follow distance 25-120 m
    map (while open): LMB target, RMB waypoint, X (clear_waypoints binding)
    clears waypoints, wheel zoom at cursor, MMB drag / arrow keys pan

ESC and F1 are reserved (game/keybinds.py): ESC always reaches the pause
menu and F1 always reaches the overlay, no matter what the player rebinds.
Numpad -/+ alias onto the main-row time-accel keys via ``normalize_key``.

While the map is open its interactions consume events first; everything it
doesn't claim (SPACE, P, time accel, M itself...) falls through to the
normal bindings. Time accel refuses to exceed 1x while a missile is in
the launch cinematic — the requested rate is kept here and the sandbox auto-
restores it once the launch reaches CLIMB/CRUISE.
"""

from __future__ import annotations

import pygame

from game.cameras import FREE_SPEEDS

# Time-acceleration ladder stepped by - / = (plan-fixed).
TIME_SCALES = (1.0, 2.0, 4.0, 8.0, 16.0)


def _pressed(keys, key: int | None) -> bool:
    """Held-state of a bindable key (False for an unbound action)."""
    return bool(keys[key]) if key is not None else False


class FreeCamControls:
    """Drives a FreeCam: right-drag mouse look events + per-frame key polls
    (movement keys resolved through the binding table every poll)."""

    def __init__(self, freecam, keybinds):
        self.freecam = freecam
        self.keybinds = keybinds
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
        kf = self.keybinds.key_for
        fwd = _pressed(keys, kf("freecam_fwd")) - _pressed(
            keys, kf("freecam_back"))
        strafe = _pressed(keys, kf("freecam_right")) - _pressed(
            keys, kf("freecam_left"))
        lift = _pressed(keys, kf("freecam_up")) - _pressed(
            keys, kf("freecam_down"))
        if fwd or strafe or lift:
            self.freecam.move(dt_real, fwd, strafe, lift, speed)


class SandboxControls:
    """Full game bindings for SandboxState + free-cam passthrough.

    Owns the requested time-accel rate (TIME_SCALES index); the sandbox
    clamps it to 1x while a launch cinematic is playing.
    """

    def __init__(self, sandbox):
        self.sandbox = sandbox
        self.free = FreeCamControls(sandbox.rig.freecam,
                                    sandbox.app.keybinds)
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
        """Resolve the key through the binding table and dispatch."""
        sandbox = self.sandbox
        app = sandbox.app
        action = app.keybinds.action_for(key)
        if action == "menu":                # reserved: always ESC
            app.open_pause()                # sim freezes; RESUME continues
        elif action == "map":
            sandbox.map_open = not sandbox.map_open
            app.audio.ui_click()
        elif action == "camera_mode":
            sandbox.rig.cycle_mode()
        elif action == "cycle_platform":
            sandbox.cycle_platform()
        elif action == "launch":
            sandbox.request_launch()
        elif action == "profile_hi_lo":
            sandbox.profile = "hi-lo"
        elif action == "profile_lo_lo":
            sandbox.profile = "lo-lo"
        elif action == "pause":
            app.paused = not app.paused
        elif action == "frame_step":
            if app.paused:
                app.frame_step = True       # exactly one 120 Hz step
        elif action == "subject_prev":
            sandbox.cycle_camera_subject(-1)
        elif action == "subject_next":
            sandbox.cycle_camera_subject(+1)
        elif action == "time_down":
            self._scale_idx = max(0, self._scale_idx - 1)
        elif action == "time_up":
            self._scale_idx = min(len(TIME_SCALES) - 1, self._scale_idx + 1)
        elif action == "screenshot":
            app.screenshot_requested = True
        elif action == "controls_overlay":  # reserved: always F1
            sandbox.toggle_controls_overlay()

    def update(self, dt_real: float) -> None:
        """Per-frame held-key poll (free-cam flight only, real time)."""
        if self.sandbox.rig.mode == "free":
            self.free.update(dt_real)
