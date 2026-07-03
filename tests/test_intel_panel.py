"""contact_intel pure helper (M1, re-keyed by the classification spec): the
fog-of-war track inspector. CLASS/TYPE/ID are earned by TRACK DWELL
(sim/contacts.classify — knowledge is monotonic); confidence + quality are
sensor-derived staleness (age), never the real entity."""

import numpy as np

from game.hud import AGE_CLASSIFIED_S, contact_intel
from sim.contacts import CLASSIFY_DWELL


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


def _track(pos, vel, *, is_air, kind, size, age, first_seen=None):
    t = dict(pos=np.array(pos, float), vel=np.array(vel, float), age=age,
             t_next=0.0, is_air=is_air, kind=kind, size=size)
    if first_seen is not None:
        t["first_seen"] = first_seen
    return t


ORIGIN = (0.0, 0.0)


def test_none_sid_returns_none():
    assert contact_intel(_World({}), None, ORIGIN, 0.0) is None


def test_new_track_reads_unknown_until_dwell_earns_it():
    """A track that JUST formed shows brg/rng/speed but no class/type —
    the free-instant-ID bug the classification spec removed."""
    w = _World({"s": _track((10000, 0, 0), (0, 0, 5000), is_air=False,
                            kind=None, size="ship", age=0.0,
                            first_seen=0.0)})
    d = contact_intel(w, "s", ORIGIN, 0.0)      # dwell = 0
    assert d["id"] == "UNKNOWN"
    assert d["cls"] == "UNKNOWN"
    assert d["label"] == "UNK"
    assert d["kind"] is None                    # type withheld
    assert d["confidence"] >= 0.8               # ...but the FIX is fresh
    assert d["speed"] >= 0.0                    # kinematics always shown


def test_dwelled_track_is_identified_high_confidence():
    t_ident = CLASSIFY_DWELL["ship"][1]
    w = _World({"s": _track((10000, 0, 0), (0, 0, 5000), is_air=False,
                            kind=None, size="ship", age=0.0,
                            first_seen=0.0)})
    d = contact_intel(w, "s", ORIGIN, t_ident)  # dwell earned the type
    assert d["id"] == "IDENTIFIED"
    assert d["confidence"] >= 0.8
    assert d["dead_reckoned"] is False


def test_stale_track_keeps_knowledge_but_degrades_quality():
    """Knowledge is MONOTONIC: a coasting track keeps its earned ID; what
    degrades is position quality (DR flag + low Q + fading confidence)."""
    t_ident = CLASSIFY_DWELL["ship"][1]
    w = _World({"s": _track((10000, 0, 0), (0, 0, 0), is_air=False,
                            kind=None, size="ship", age=30.0,
                            first_seen=0.0)})
    d = contact_intel(w, "s", ORIGIN, t_ident + 30.0)
    assert d["id"] == "IDENTIFIED"              # never regresses
    assert d["dead_reckoned"] is True
    assert d["quality"] <= 3                    # Q3 at 30 s stale
    assert d["confidence"] < 0.8


def test_class_from_sensor_size_not_truth():
    """Once dwell earns the class, it comes from the SIZE stamp (sensor
    provenance), never the real entity."""
    dw = 30.0                                   # past every t_class
    w = _World({
        "m": _track((5000, 50, 0), (-100, 0, 0), is_air=True, kind="harm",
                    size="missile", age=0.0, first_seen=0.0),
        "f": _track((5000, 9000, 0), (-100, 0, 0), is_air=True, kind=None,
                    size="fighter", age=0.0, first_seen=0.0),
        "s": _track((5000, 0, 0), (0, 0, 0), is_air=False, kind=None,
                    size="ship", age=0.0, first_seen=0.0),
    })
    assert contact_intel(w, "m", ORIGIN, dw)["cls"] == "MISSILE"
    assert contact_intel(w, "f", ORIGIN, dw)["cls"] == "AIR"
    assert contact_intel(w, "s", ORIGIN, dw)["cls"] == "SURFACE"


def test_legacy_track_without_first_seen_stays_identified():
    """Back-compat: old fixtures/probes without the stamp keep today's
    instant-ID behavior (no crashes, no silent UNK regressions)."""
    w = _World({"s": _track((10000, 0, 0), (0, 0, 0), is_air=False,
                            kind=None, size="ship", age=0.0)})
    assert contact_intel(w, "s", ORIGIN, 0.0)["id"] == "IDENTIFIED"


def test_course_from_velocity_compass():
    w = _World({"s": _track((10000, 0, 0), (100, 0, 0), is_air=False,
                            kind=None, size="ship", age=0.0)})
    d = contact_intel(w, "s", ORIGIN, 0.0)
    assert abs(d["course"] - 90.0) <= 1.0     # +x velocity -> heading 090
