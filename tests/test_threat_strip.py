"""Threat-Warning strip pure helper threat_rows (M1): the fog-pierced inbound
board. Reads ONLY the gated contact picture — never world.missiles truth."""

import copy

import numpy as np

from game.hud import TTI_CRIT_S, TTI_WARN_S, threat_rows


class _Board:
    def __init__(self, tracks):
        self.tracks = tracks

    def estimated_pos(self, sid, now):
        t = self.tracks[sid]
        return t["pos"] + t["vel"] * t["age"]


class _World:
    def __init__(self, tracks, missiles=()):
        self.contacts = _Board(tracks)
        self.missiles = list(missiles)
        self.sim_time = 0.0


def _track(pos, vel, *, is_air=True, kind="tomahawk", size="missile", age=0.0):
    return dict(pos=np.array(pos, float), vel=np.array(vel, float), age=age,
                t_next=0.0, is_air=is_air, kind=kind, size=size)


BASE = (0.0, 0.0)   # friendly asset at the origin (x, z)


def test_empty_board_yields_no_rows():
    assert threat_rows(_World({}), BASE, 0.0) == []


def test_only_air_hostile_kind_tracks_appear():
    w = _World({
        "tom": _track((10000, 50, 0), (-300, 0, 0)),
        "ship": _track((20000, 0, 0), (0, 0, 0), is_air=False, kind=None,
                       size="ship"),
        "fighter": _track((30000, 9000, 0), (-200, 0, 0), kind=None,
                          size="fighter"),
    })
    rows = threat_rows(w, BASE, 0.0)
    assert len(rows) == 1
    assert rows[0].sid == "tom"


def test_rows_sort_by_tti_ascending_and_severity_bands():
    w = _World({
        "near": _track((2000, 50, 0), (-300, 0, 0)),
        "mid":  _track((12000, 50, 0), (-300, 0, 0)),
        "far":  _track((30000, 50, 0), (-300, 0, 0)),
    })
    rows = threat_rows(w, BASE, 0.0)
    ttis = [r.tti for r in rows]
    assert ttis == sorted(ttis)
    sev = {r.sid: r.severity for r in rows}
    assert sev["near"] == "DANGER"      # < TTI_CRIT_S (20 s)
    assert sev["mid"] == "WARN"         # < TTI_WARN_S (60 s)
    assert sev["far"] == "MUTED"        # >= TTI_WARN_S


def test_outbound_track_has_none_tti_and_sorts_last():
    w = _World({
        "in":  _track((5000, 50, 0), (-300, 0, 0)),
        "out": _track((5000, 50, 0), (+300, 0, 0)),
    })
    rows = threat_rows(w, BASE, 0.0)
    assert rows[-1].sid == "out"
    assert rows[-1].tti is None


def test_fog_undetected_hostile_never_appears():
    """LOAD-BEARING: a hostile in world.missiles but NOT in contacts.tracks
    must NOT appear — the strip reads the gated picture, not truth."""
    class _M:
        is_hostile = True
        pos = np.array([1000.0, 50.0, 0.0])

        def velocity(self):
            return np.array([-300.0, 0.0, 0.0])

    w = _World({}, missiles=[_M()])
    assert threat_rows(w, BASE, 0.0) == []


def test_determinism_same_tracks_same_rows():
    t = {"a": _track((8000, 50, 0), (-250, 0, 0)),
         "b": _track((4000, 50, 0), (-250, 0, 0))}
    r1 = threat_rows(_World(copy.deepcopy(t)), BASE, 0.0)
    r2 = threat_rows(_World(copy.deepcopy(t)), BASE, 0.0)
    key = lambda rs: [(x.sid, x.tti, x.severity) for x in rs]
    assert key(r1) == key(r2)
