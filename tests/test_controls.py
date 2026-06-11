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
