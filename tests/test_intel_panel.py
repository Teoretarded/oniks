"""contact_intel pure helper (M1): the fog-of-war track inspector. CLASS +
confidence are sensor-derived (is_air + size + age), never the real entity."""

import numpy as np

from game.hud import AGE_CLASSIFIED_S, AGE_IDENTIFIED_S, contact_intel


class _Board:
    def __init__(self, tracks):
        self.tracks = tracks

    def estimated_pos(self, sid, now):
        t = self.tracks[sid]
        return t["pos"] + t["vel"] * t["age"]


class _World:
    def __init__(self, tracks):
        self.contacts = _Board(tracks)
        self.sim_time = 0.0


def _track(pos, vel, *, is_air, kind, size, age):
    return dict(pos=np.array(pos, float), vel=np.array(vel, float), age=age,
                t_next=0.0, is_air=is_air, kind=kind, size=size)


ORIGIN = (0.0, 0.0)


def test_none_sid_returns_none():
    assert contact_intel(_World({}), None, ORIGIN, 0.0) is None


def test_fresh_radar_track_is_identified_high_confidence():
    w = _World({"s": _track((10000, 0, 0), (0, 0, 5000), is_air=False,
                            kind=None, size="ship", age=0.0)})
    d = contact_intel(w, "s", ORIGIN, 0.0)
    assert d["id"] == "IDENTIFIED"
    assert d["confidence"] >= 0.8
    assert d["dead_reckoned"] is False


def test_stale_track_is_unknown_and_dead_reckoned():
    w = _World({"s": _track((10000, 0, 0), (0, 0, 0), is_air=False,
                            kind=None, size="ship", age=30.0)})
    d = contact_intel(w, "s", ORIGIN, 0.0)
    assert d["id"] == "UNKNOWN"
    assert d["dead_reckoned"] is True


def test_class_from_sensor_size_not_truth():
    w = _World({
        "m": _track((5000, 50, 0), (-100, 0, 0), is_air=True, kind="harm",
                    size="missile", age=0.0),
        "f": _track((5000, 9000, 0), (-100, 0, 0), is_air=True, kind=None,
                    size="fighter", age=0.0),
        "s": _track((5000, 0, 0), (0, 0, 0), is_air=False, kind=None,
                    size="ship", age=0.0),
    })
    assert contact_intel(w, "m", ORIGIN, 0.0)["cls"] == "MISSILE"
    assert contact_intel(w, "f", ORIGIN, 0.0)["cls"] == "AIR"
    assert contact_intel(w, "s", ORIGIN, 0.0)["cls"] == "SURFACE"


def test_course_from_velocity_compass():
    w = _World({"s": _track((10000, 0, 0), (100, 0, 0), is_air=False,
                            kind=None, size="ship", age=0.0)})
    d = contact_intel(w, "s", ORIGIN, 0.0)
    assert abs(d["course"] - 90.0) <= 1.0     # +x velocity -> heading 090
