"""SandboxControls key routing through the Keybinds table (Task UI).

``_handle_key`` is exercised directly with stub sandbox/app objects — no
window, no GL. The contract: every action resolves through app.keybinds
(rebinds redirect it), ESC stays hardwired to the pause menu, numpad time
keys alias, and F1 toggles the controls overlay.
"""

import pygame
import pytest

from game.controls import TIME_SCALES, SandboxControls
from game.keybinds import Keybinds


class Recorder:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append(name)
        return record


class FakeRig:
    def __init__(self, log):
        self.log = log
        self.mode = "launcher"
        self.freecam = object()

    def cycle_mode(self):
        self.log.append("cycle_mode")
        return self.mode


class FakeApp:
    def __init__(self, kb):
        self.keybinds = kb
        self.audio = Recorder()
        self.paused = False
        self.frame_step = False
        self.screenshot_requested = False
        self.opened_pause = 0

    def open_pause(self):
        self.opened_pause += 1


class FakeSandbox:
    def __init__(self, kb):
        self.app = FakeApp(kb)
        self.log = []
        self.rig = FakeRig(self.log)
        self.map_open = False
        self.profile = "hi-lo"
        self.controls_overlay = False

    def request_launch(self):
        self.log.append("launch")

    def cycle_platform(self):
        self.log.append("cycle_platform")

    def cycle_camera_subject(self, step=1):
        self.log.append(f"subject{step:+d}")

    def toggle_controls_overlay(self):
        self.controls_overlay = not self.controls_overlay
        self.log.append("overlay")

    def request_salvo(self):
        self.log.append("salvo_fire")

    def cycle_salvo_mode(self):
        self.log.append("salvo_mode")

    def toggle_buoy_drop(self):
        self.log.append("buoy_drop")

    def request_asw(self):
        self.log.append("asw_launch")

    def toggle_auto_warp(self):
        # M6 auto-time-warp: the key dispatches to the SandboxControls method
        # (the real sandbox forwards to it); record the dispatch here so the
        # binding test can assert the key routed.
        self.log.append("auto_warp_toggle")
        return self.app.keybinds  # unused; mirror real return shape harmlessly


@pytest.fixture
def ctl(tmp_path):
    kb = Keybinds(str(tmp_path / "settings.json"))
    return SandboxControls(FakeSandbox(kb))


def test_default_bindings_dispatch(ctl):
    sb = ctl.sandbox
    ctl._handle_key(pygame.K_SPACE)
    ctl._handle_key(pygame.K_TAB)
    ctl._handle_key(pygame.K_c)
    assert sb.log == ["launch", "cycle_platform", "cycle_mode"]
    ctl._handle_key(pygame.K_m)
    assert sb.map_open
    ctl._handle_key(pygame.K_2)
    assert sb.profile == "lo-lo"
    ctl._handle_key(pygame.K_1)
    assert sb.profile == "hi-lo"


def test_rebound_key_fires_and_old_key_goes_dead(ctl):
    sb = ctl.sandbox
    sb.app.keybinds.rebind("launch", pygame.K_l)
    ctl._handle_key(pygame.K_SPACE)
    assert sb.log == []                      # old key: nothing
    ctl._handle_key(pygame.K_l)
    assert sb.log == ["launch"]


def test_escape_opens_pause_menu(ctl):
    ctl._handle_key(pygame.K_ESCAPE)
    assert ctl.sandbox.app.opened_pause == 1


def test_f1_toggles_controls_overlay(ctl):
    sb = ctl.sandbox
    ctl._handle_key(pygame.K_F1)
    assert sb.controls_overlay
    ctl._handle_key(pygame.K_F1)
    assert not sb.controls_overlay


def test_pause_and_frame_step(ctl):
    app = ctl.sandbox.app
    ctl._handle_key(pygame.K_n)
    assert not app.frame_step                # N only steps while paused
    ctl._handle_key(pygame.K_p)
    assert app.paused
    ctl._handle_key(pygame.K_n)
    assert app.frame_step


def test_subject_cycle_brackets(ctl):
    ctl._handle_key(pygame.K_LEFTBRACKET)
    ctl._handle_key(pygame.K_RIGHTBRACKET)
    assert ctl.sandbox.log == ["subject-1", "subject+1"]


def test_time_scale_steps_and_numpad_aliases(ctl):
    assert ctl.requested_scale == TIME_SCALES[0]
    ctl._handle_key(pygame.K_EQUALS)
    ctl._handle_key(pygame.K_KP_PLUS)
    assert ctl.requested_scale == TIME_SCALES[2]
    ctl._handle_key(pygame.K_KP_MINUS)
    assert ctl.requested_scale == TIME_SCALES[1]
    ctl._handle_key(pygame.K_MINUS)
    ctl._handle_key(pygame.K_MINUS)          # clamped at the floor
    assert ctl.requested_scale == TIME_SCALES[0]


def test_screenshot_flag(ctl):
    ctl._handle_key(pygame.K_F2)
    assert ctl.sandbox.app.screenshot_requested


def test_salvo_keys_dispatch(ctl):
    # M6 salvo: F empties the ready tubes in a ripple; Y cycles the mode.
    sb = ctl.sandbox
    ctl._handle_key(pygame.K_f)
    ctl._handle_key(pygame.K_y)
    assert sb.log == ["salvo_fire", "salvo_mode"]


def test_asw_keys_dispatch(ctl):
    # M5 ASW UI: U arms buoy-drop mode; K fires an ASW round at the fix.
    sb = ctl.sandbox
    ctl._handle_key(pygame.K_u)
    ctl._handle_key(pygame.K_k)
    assert sb.log == ["buoy_drop", "asw_launch"]


def test_extended_time_ladder_reaches_64x():
    # M6 AUTO-TIME-WARP extends the ladder to (1,2,4,8,16,32,64).
    assert TIME_SCALES == (1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0)


def test_time_up_climbs_past_the_old_16x_top(ctl):
    # The old ladder topped at 16x; = now climbs to 32x then 64x and clamps.
    for _ in range(6):
        ctl._handle_key(pygame.K_EQUALS)
    assert ctl.requested_scale == 64.0
    ctl._handle_key(pygame.K_EQUALS)             # clamped at the ceiling
    assert ctl.requested_scale == 64.0


def test_auto_warp_toggle_key_dispatches(ctl):
    # M6: T routes to the sandbox auto-warp toggle.
    sb = ctl.sandbox
    ctl._handle_key(pygame.K_t)
    assert sb.log == ["auto_warp_toggle"]


def test_auto_warp_toggle_flips_controls_state(ctl):
    # The SandboxControls method itself flips the flag + re-bases the director.
    assert not ctl.auto_warp
    assert ctl.toggle_auto_warp() is True
    assert ctl.auto_warp
    assert ctl.toggle_auto_warp() is False
    assert not ctl.auto_warp


def test_real_sandboxstate_defines_the_auto_warp_forwarder():
    # REGRESSION (the masked BLOCKER): the key dispatch calls
    # sandbox.toggle_auto_warp() on the REAL SandboxState — which previously had
    # NO such method (hasattr was False), so pressing T crashed and the whole
    # auto-warp feature was unreachable.  The FakeSandbox stub above forwards,
    # masking it.  Assert the real class actually defines the forwarder, mirror-
    # ing the other dispatched actions that exist on SandboxState.
    from game.sandbox import SandboxState
    for action in ("toggle_battery_panel", "cycle_salvo_mode", "request_salvo",
                   "request_launch", "toggle_auto_warp"):
        assert hasattr(SandboxState, action), (
            f"SandboxState is missing {action} — the key dispatch would crash")


def test_real_forwarder_routes_the_T_key_to_the_director(tmp_path):
    # INTEGRATION (not the FakeSandbox stub): drive _handle_key(K_t) through a
    # sandbox whose toggle_auto_warp IS the REAL SandboxState.toggle_auto_warp
    # bound method, wired to a REAL SandboxControls + director.  Pressing T must
    # flip controls.auto_warp (and re-base the director) WITHOUT raising — the
    # end-to-end path the masked stub never exercised.
    from game.sandbox import SandboxState

    class _Freecam:
        pass

    class _Rig:
        mode = "launcher"
        freecam = _Freecam()

    class _RealForwarderSandbox:
        """Minimal SandboxState-shaped host: a REAL SandboxControls + the REAL
        forwarder bound onto it, so the dispatch hits production code."""

        def __init__(self, kb):
            self.app = FakeApp(kb)
            self.rig = _Rig()
            self.map_open = False
            self.controls = SandboxControls(self)

        # The REAL forwarder (calls self.controls.toggle_auto_warp() +
        # self.app.audio.ui_click()), bound here so the dispatch path is real.
        toggle_auto_warp = SandboxState.toggle_auto_warp

    kb = Keybinds(str(tmp_path / "settings.json"))
    sb = _RealForwarderSandbox(kb)
    ctl = sb.controls
    assert not ctl.auto_warp
    ctl._handle_key(pygame.K_t)                  # must not raise (the BLOCKER)
    assert ctl.auto_warp                         # forwarder reached the director
    assert ctl.warp_director.effective == pytest.approx(1.0)  # re-based at 1x
    assert "ui_click" in sb.app.audio.calls      # forwarder's UX click fired
    ctl._handle_key(pygame.K_t)
    assert not ctl.auto_warp
