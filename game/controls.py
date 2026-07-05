"""Sandbox input: every action routed through the rebindable Keybinds table.

Default bindings (rebind in SETTINGS; persisted to %APPDATA%\\ONIKS):

    ESC pause menu | M map | C camera | TAB platform (Bastion <-> S-300)
    SPACE launch | 1/2 profile hi-lo/lo-lo | R radar emissions (COMBAT)
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
from game.timewarp import TimeWarpDirector, drop_cause

# Time-acceleration ladder stepped by - / = .  M6 AUTO-TIME-WARP extends it
# past 16x to (1,2,4,8,16,32,64); the App loop caps at 64 sim steps/frame, so
# 64x is the documented practical ceiling (higher would saturate the step
# guard rather than run faster).  Existing default play never climbs past the
# old top (the byte-identical default starts at index 0 = 1x).
TIME_SCALES = (1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0)

# TAB platform cycles (Phase 4): SANDBOX keeps the original two-platform
# toggle; COMBAT adds the recon drone as a third tasking platform
# (bastion -> s300 -> drone -> ...). Pure data + helper so the cycle is
# unit-testable headless (game/sandbox.py is GL-touching).
PLATFORMS_SANDBOX = ("bastion", "s300")
# COMBAT TAB cycle: M4-B adds the loitering-swarm pod as a tasking platform
# (... -> swarm) ONLY when a pod is armed (n_swarm_pods > 0); M5 inserts the
# Buk mid-SAM (bastion -> s300 -> buk -> ...) ONLY when a Buk is built
# (n_buk > 0).  The default battle keeps the three-platform cycle so it is
# byte-identical.  combat_platforms() builds the right tuple from the world.
PLATFORMS_COMBAT = ("bastion", "s300", "drone")
PLATFORMS_COMBAT_SWARM = ("bastion", "s300", "drone", "swarm")


def combat_platforms(world) -> tuple:
    """The COMBAT TAB cycle for ``world``: the base three-platform cycle, with
    the Buk mid-SAM inserted after the S-300 when a Buk is built
    (``n_buk`` > 0), and the loitering-swarm pod appended last when a pod is
    armed (``_swarm_mag_cap`` > 0).  Pure + headless: reads only count/magazine
    attributes, so the byte-identical default battle (n_buk == 0, no pod)
    returns EXACTLY ``PLATFORMS_COMBAT`` and never grows a tab."""
    has_buk = getattr(world, "n_buk", 0) > 0
    has_swarm = getattr(world, "_swarm_mag_cap", 0) > 0
    if not has_buk and not has_swarm:
        return PLATFORMS_COMBAT          # byte-identical default cycle
    platforms = ["bastion", "s300"]
    if has_buk:
        platforms.append("buk")          # the mid-SAM, after the S-300
    platforms.append("drone")
    if has_swarm:
        platforms.append("swarm")
    return tuple(platforms)


def next_platform(current: str, platforms) -> str:
    """The next platform in the TAB cycle (wraps; an unknown current —
    never expected — lands on the first entry rather than crashing)."""
    try:
        i = platforms.index(current)
    except ValueError:
        return platforms[0]
    return platforms[(i + 1) % len(platforms)]


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

    M6 AUTO-TIME-WARP: also owns an ``auto_warp`` toggle + a pure
    :class:`TimeWarpDirector`.  When auto-warp is ON the - / = ladder sets the
    TARGET warp and the director auto-drops to 1x on important events (passed
    in each frame by the sandbox), then eases back.  When OFF the director is
    untouched and ``effective_time_scale`` uses the legacy launch-lock path —
    so the default battle (auto-warp OFF) stays byte-identical.
    """

    def __init__(self, sandbox):
        self.sandbox = sandbox
        self.free = FreeCamControls(sandbox.rig.freecam,
                                    sandbox.app.keybinds)
        self._scale_idx = 0
        self._orbit_drag = False        # RMB/LMB orbit drag live (Task CAM)
        # M6 auto-time-warp: OFF by default (byte-identical), so the director
        # is dormant until the player presses the auto_warp_toggle key.
        self.auto_warp = False
        self.warp_director = TimeWarpDirector()

    @property
    def requested_scale(self) -> float:
        return TIME_SCALES[self._scale_idx]

    def toggle_auto_warp(self) -> bool:
        """T (auto_warp_toggle binding): flip auto-time-warp ON/OFF.  Turning
        it ON re-bases the director on the current requested rate (no stale
        ease); turning it OFF leaves the requested rate as-is so the player
        keeps manual control.  Returns the new state."""
        self.auto_warp = not self.auto_warp
        if self.auto_warp:
            self.warp_director.reset(self.requested_scale)
        return self.auto_warp

    def handle_event(self, ev) -> None:
        sandbox = self.sandbox
        # The open tactical map gets first claim on events (mouse + X).
        consumed = sandbox.map_open and sandbox.tactical_map.handle_event(ev)
        if not consumed and ev.type == pygame.KEYDOWN:
            self._handle_key(ev.key)
        # Mouse parity (2026-07-05): a LMB on a registered HUD panel
        # dispatches its bound ACTION through the same dispatcher the key
        # path uses (one dispatcher — click and key can never diverge).
        # A registered panel with no action still consumes the click: a
        # click on a plate must never start a camera drag behind it.
        if (not consumed and not sandbox.map_open
                and ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1):
            ui = getattr(sandbox, "ui", None)
            item = ui.hit(*ev.pos) if ui is not None else None
            if item is not None:
                if item.get("action"):
                    self.dispatch_action(item["action"])
                return
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
        self.dispatch_action(self.sandbox.app.keybinds.action_for(key))

    def dispatch_action(self, action) -> None:
        """The ONE action dispatcher — key bindings and registered-panel
        clicks both land here, so mouse and keyboard cannot drift."""
        sandbox = self.sandbox
        app = sandbox.app
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
        elif action == "radar_toggle":
            sandbox.toggle_radar()
        elif action == "sam_round":
            sandbox.cycle_sam_round()
        elif action == "oniks_weapon":
            sandbox.cycle_oniks_weapon()
        elif action == "swarm_arrival_mode":
            sandbox.toggle_swarm_arrival_mode()
        elif action == "jam":
            sandbox.toggle_jam()
        elif action == "salvo_fire":
            sandbox.request_salvo()
        elif action == "salvo_mode":
            sandbox.cycle_salvo_mode()
        elif action == "buoy_drop":
            sandbox.toggle_buoy_drop()
        elif action == "asw_launch":
            sandbox.request_asw()
        elif action == "battery_panel":
            sandbox.toggle_battery_panel()
        elif action == "forensics":
            sandbox.toggle_forensics()
        elif action == "auto_warp_toggle":
            sandbox.toggle_auto_warp()
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
        elif action == "bug_report":
            sandbox.report_bug()
        elif action == "controls_overlay":  # reserved: always F1
            sandbox.toggle_controls_overlay()

    def update(self, dt_real: float) -> None:
        """Per-frame held-key poll (free-cam flight only, real time).

        Also advances the M6 auto-time-warp director here (the one existing
        per-frame real-dt seam), so ``effective_time_scale`` can read the eased
        scale next frame without any main-loop change.  When auto-warp is OFF
        the director is left dormant (the sandbox uses the legacy launch-lock
        path), keeping the default battle byte-identical.
        """
        if self.sandbox.rig.mode == "free":
            self.free.update(dt_real)
        if self.auto_warp:
            drop = self.sandbox.warp_drop_active()
            # Latch the cause into the director: the event predicates name it
            # (INBOUND/TERMINAL/INTERCEPT); a drop with no firing predicate is
            # the launch-cinematic / salvo lock.  The HUD reads the LATCHED
            # tag so it cannot flicker off during the dwell hold.
            cause = (drop_cause(self.sandbox.world) or "LAUNCH") if drop \
                else None
            self.warp_director.tick(dt_real, self.requested_scale, drop,
                                    cause=cause)
