"""GL-free input, camera, and chamber checks for the hidden testing lab."""

from types import SimpleNamespace

import numpy as np
import pygame
import pytest

from engine.meshdata import make_box
from game.testing_catalog import get_asset, mesh_metadata
from game.testing_lab import TestingLabState, build_inspection_chamber


class _Recorder:
    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


class _FakeText:
    def __init__(self):
        self.labels = []
        self.lines = []

    def draw_text(self, _x, _y, value, *_args, **_kwargs):
        self.labels.append(str(value))

    def draw_lines(self, points, color, width=1.5):
        self.lines.append((tuple(points), tuple(color), width))

    def draw_rect(self, *_args, **_kwargs):
        pass

    def text_width(self, value, _size=None):
        return len(str(value)) * 7


class _App:
    def __init__(self, feedback_dir="testing_feedback"):
        self.window = SimpleNamespace()
        self.renderer = SimpleNamespace()
        self.audio = _Recorder()
        self.ui_prefs = SimpleNamespace(get=lambda _key: "high")
        self.testing_feedback_dir = str(feedback_dir)
        self.bug_shot_path = None
        self.screenshot_requested = False
        self.closed = 0

    def close_testing_lab(self):
        self.closed += 1


def _key(key, unicode="", mod=0):
    return pygame.event.Event(
        pygame.KEYDOWN, key=key, unicode=unicode, mod=mod, scancode=0)


def test_lab_defaults_to_oniks_and_freezes_simulation():
    state = TestingLabState(_App())
    assert state.selected_asset().id == "oniks"
    assert state.category == "ALL"
    assert state.effective_time_scale() == 0.0
    assert state.loaded_asset is None


def test_f6_switches_between_asset_inspector_and_missile_lab():
    state = TestingLabState(_App())
    assert state.lab_mode == "assets"
    state.handle_event(_key(pygame.K_F6))
    assert state.lab_mode == "flight"
    state.handle_event(_key(pygame.K_F6))
    assert state.lab_mode == "assets"


def test_flight_plot_axes_and_clicked_selection_use_white_track():
    state = TestingLabState(_App())
    state.text = _FakeText()
    state._preview_box = (400, 20, 1500, 850)
    trajectories = (
        ({"x_m": 0, "z_m": 0, "altitude_m": 0,
          "t_s": 0, "speed_mps": 0},
         {"x_m": 0, "z_m": 100_000, "altitude_m": 10_000,
          "t_s": 100, "speed_mps": 900}),
        ({"x_m": 0, "z_m": 0, "altitude_m": 0,
          "t_s": 0, "speed_mps": 0},
         {"x_m": 0, "z_m": 120_000, "altitude_m": 20_000,
          "t_s": 120, "speed_mps": 1_100}),
    )
    results = (
        {"run": 1, "performance_rank": 2, "performance_score": 80.0,
         "hit": True, "apogee_km": 10.0, "impact_speed_mps": 900.0,
         "flight_time_s": 100.0, "closest_m": 20.0},
        {"run": 2, "performance_rank": 1, "performance_score": 95.0,
         "hit": True, "apogee_km": 20.0, "impact_speed_mps": 1_100.0,
         "flight_time_s": 120.0, "closest_m": 10.0},
    )
    state.flight_batch = SimpleNamespace(
        trajectories=trajectories, results=results, ranked_indices=(1, 0),
        hit_rate=1.0, median_closest_m=15.0, median_apogee_km=15.0)
    state.selected_flight_run = 1

    state._draw_flight_plots(1600, 900)

    assert any(label.startswith("SELECT #02") for label in state.text.labels)
    assert "120" in state.text.labels   # exact distance/time axis tick
    assert any(color == (1.0, 1.0, 1.0, 0.98)
               for _points, color, _width in state.text.lines)
    assert any(color == (0.18, 0.48, 1.0, 0.42)
               for _points, color, _width in state.text.lines)


def test_catalog_navigation_search_and_reserved_system_keys(tmp_path):
    app = _App(tmp_path)
    state = TestingLabState(app)

    state.handle_event(_key(pygame.K_RIGHT))
    assert state.category == "GROUND"
    state.handle_event(_key(pygame.K_LEFT))
    assert state.category == "ALL"

    state.handle_event(_key(pygame.K_SLASH, "/"))
    assert state.search_active
    for ch in "carrier":
        state.handle_event(_key(ord(ch), ch))
    assert [a.id for a in state.visible_assets()] == ["carrier"]
    state.handle_event(_key(pygame.K_RETURN, "\r"))
    assert not state.search_active

    state.loaded_asset = get_asset("oniks")
    state.handle_event(_key(pygame.K_F2))
    assert app.bug_shot_path.endswith("oniks_az035_elp018.png")
    assert state.ui_hidden
    state.handle_event(_key(pygame.K_ESCAPE))
    assert app.closed == 1


def test_feedback_arms_clean_capture_cycles_type_and_cancels(tmp_path):
    app = _App(tmp_path)
    state = TestingLabState(app)
    state.loaded_asset = get_asset("oniks")
    state.open_feedback()

    assert state.feedback["armed"]
    assert app.bug_shot_path.endswith("_pending_lab_shot.png")
    state.feedback["armed"] = False
    state.handle_event(_key(pygame.K_TAB))
    state.handle_event(_key(pygame.K_x, "x"))
    assert state.feedback["type_index"] == 1
    assert state.feedback["note"] == "x"
    state.handle_event(_key(pygame.K_ESCAPE))
    assert state.feedback is None
    assert app.bug_shot_path is None


def test_unrestricted_camera_frames_large_assets_and_reaches_bottom_view():
    state = TestingLabState(_App())
    stats = {
        "radius": 1_254.0,
        "dimensions": (205.0, 47.0, 2_500.0),
    }
    state._frame_mesh(stats)
    assert state.orbit_dist > 2_500.0
    assert state.max_dist > state.orbit_dist
    state.snap_view(5)
    assert np.degrees(state.orbit_el) == pytest.approx(-90.0)
    assert state.camera.eye[1] < state.target[1]
    state.snap_view(4)
    assert np.degrees(state.orbit_el) == pytest.approx(90.0)
    assert state.camera.eye[1] > state.target[1]


def test_exact_angle_entry_accepts_overhead_and_signed_views():
    state = TestingLabState(_App())

    state.handle_event(_key(pygame.K_e, "e"))
    for char in "-45,70":
        state.handle_event(_key(ord(char) if char not in ",-" else
                                (pygame.K_COMMA if char == "," else
                                 pygame.K_MINUS), char))
    state.handle_event(_key(pygame.K_RETURN, "\r"))

    assert not state.angle_entry_active
    assert np.degrees(state.orbit_az) == pytest.approx(315.0)
    assert np.degrees(state.orbit_el) == pytest.approx(70.0)
    assert state.camera.eye[1] > state.target[1]

    state.set_view_angles(90.0, 90.0)
    assert np.degrees(state.orbit_el) == pytest.approx(90.0)
    assert np.isfinite(state.camera.view_rot()).all()


def test_exact_angle_entry_rejects_invalid_elevation():
    state = TestingLabState(_App())
    state.handle_event(_key(pygame.K_e, "e"))
    for char in "45,100":
        key = pygame.K_COMMA if char == "," else ord(char)
        state.handle_event(_key(key, char))
    state.handle_event(_key(pygame.K_RETURN, "\r"))

    assert state.angle_entry_active
    assert state.status_danger


def test_inspection_chamber_is_nonempty_and_surrounds_model_bbox():
    source = make_box((2.0, 4.0, 6.0), (1.0, 1.0, 1.0))
    stats = mesh_metadata(source)
    chamber = build_inspection_chamber(stats)
    chamber_stats = mesh_metadata(chamber)
    assert chamber_stats["vertices"] > source.vertices.shape[0]
    assert chamber_stats["triangles"] > len(source.indices) // 3
    assert chamber_stats["dimensions"][0] > stats["dimensions"][0]
    assert chamber_stats["dimensions"][1] > stats["dimensions"][1]
    assert chamber_stats["dimensions"][2] > stats["dimensions"][2]
