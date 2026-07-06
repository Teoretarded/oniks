"""game/sensor_log.py — the raw receiver-event recorder (GL-free).

The forensics panes' LIVE data source (approved variations: micro-ledger
strip, plot board).  A pure observer over the PLAYER PICTURE stores only —
world.contacts.tracks / world.emitter_contacts / world.sub_contacts — it
never reads truth positions and never writes sim state.  Events carry the
BELIEF pos the picture holds.  Deterministic: driven by the sim clock only.
"""

import numpy as np

from game.sensor_log import (
    LOG_CAP, REFRESH_LOG_PERIOD_S, SensorLog,
)

DT = 1.0 / 120.0


class _Contacts:
    def __init__(self):
        self.tracks = {}


class _World:
    def __init__(self):
        self.sim_time = 0.0
        self.missiles = []
        self.contacts = _Contacts()
        self.emitter_contacts = {}
        self.sub_contacts = {}

    def tick(self, dt=DT):
        self.sim_time += dt


class _WarnRound:
    """Hostile round whose track arrives via the launch-warning channel."""

    def __init__(self, cid):
        self.aircraft_id = cid
        self.launch_warning = True
        self.alive = True


def _track(x=10_000.0, z=50_000.0, kind="oniks"):
    return dict(pos=np.array([x, 300.0, z]), vel=np.zeros(3), age=0.0,
                t_next=0.0, is_air=True, kind=kind, size="missile")


def _run(w, log, steps):
    for _ in range(steps):
        w.tick()
        log.update(w)


# ------------------------------------------------------------------ radar

def test_track_formation_logs_one_radar_event():
    w = _World(); log = SensorLog()
    _run(w, log, 3)
    w.contacts.tracks["tk_01"] = _track()
    _run(w, log, 5)
    evs = [e for e in log.events if e["lane"] == "radar"]
    assert len(evs) == 1
    e = evs[0]
    assert e["label"] == "TRACK FORMED"
    assert e["ref"] == "tk_01"
    assert e["pos"] == (10_000.0, 50_000.0)


def test_track_refresh_is_cadence_capped():
    w = _World(); log = SensorLog()
    trk = _track()
    w.contacts.tracks["tk_01"] = trk
    _run(w, log, 2)
    # Age keeps resetting (constant refreshes) for less than the log cadence:
    # only the formation event may exist.
    for _ in range(int(REFRESH_LOG_PERIOD_S / DT) - 60):
        w.tick()
        trk["age"] = 0.0
        trk["pos"] = trk["pos"] + 1.0
        log.update(w)
    assert len([e for e in log.events if e["lane"] == "radar"]) == 1
    # Past the cadence: exactly one REFRESH is logged.
    for _ in range(180):
        w.tick()
        trk["age"] = 0.0
        log.update(w)
    radar = [e for e in log.events if e["lane"] == "radar"]
    assert len(radar) == 2
    assert radar[1]["label"] == "TRACK REFRESH"


def test_track_drop_logs_at_last_known_pos():
    w = _World(); log = SensorLog()
    w.contacts.tracks["tk_01"] = _track(x=7_000.0, z=9_000.0)
    _run(w, log, 2)
    del w.contacts.tracks["tk_01"]
    _run(w, log, 2)
    drop = [e for e in log.events if e["label"] == "TRACK DROPPED"]
    assert len(drop) == 1
    assert drop[0]["pos"] == (7_000.0, 9_000.0)


# ------------------------------------------------------------- launch warn

def test_launch_warning_track_logs_on_lwarn_lane():
    w = _World(); log = SensorLog()
    w.missiles.append(_WarnRound("sm2_07"))
    w.contacts.tracks["sm2_07"] = _track(kind="sm2")
    _run(w, log, 2)
    evs = [e for e in log.events if e["lane"] == "lwarn"]
    assert len(evs) == 1
    assert evs[0]["label"] == "LAUNCH CUE"
    assert evs[0]["ref"] == "sm2_07"
    assert not [e for e in log.events if e["lane"] == "radar"]


# ------------------------------------------------------------------ elint

def test_emitter_heard_then_reheard_capped():
    w = _World(); log = SensorLog()
    w.emitter_contacts["em_04"] = dict(
        pos=np.array([40_000.0, 0.0, 90_000.0]), kind="SPY-1",
        quality=900.0, last_heard=0.0, age=0.0)
    _run(w, log, 2)
    heard = [e for e in log.events if e["lane"] == "elint"]
    assert len(heard) == 1 and heard[0]["label"] == "EMITTER HEARD"
    # Refresh last_heard continuously: capped to one RE-HEARD per cadence.
    for _ in range(int(REFRESH_LOG_PERIOD_S / DT) + 240):
        w.tick()
        w.emitter_contacts["em_04"]["last_heard"] = w.sim_time
        log.update(w)
    elint = [e for e in log.events if e["lane"] == "elint"]
    assert len(elint) == 2
    assert elint[1]["label"] == "RE-HEARD"


# --------------------------------------------------------------- acoustic

def test_sub_fix_reheard_is_cadence_capped():
    """A boat held by buoys refreshes its fix every few seconds — the strip
    logs the FIRST fix, then at most one row per log cadence (like radar
    refreshes), or the acoustic lane drowns the whole window."""
    w = _World(); log = SensorLog()
    fix = dict(pos=np.array([-30_000.0, 0.0, 60_000.0]), quality=1_400.0,
               kind="sub", last_heard=0.0, age=0.0, t_drop=1e9,
               sub_id="ssk_1")
    w.sub_contacts["ssk_1"] = fix
    _run(w, log, 2)
    for _ in range(int(REFRESH_LOG_PERIOD_S / DT) + 240):
        w.tick()
        fix["last_heard"] = w.sim_time         # heard EVERY step
        log.update(w)
    ac = [e for e in log.events if e["lane"] == "acoustic"]
    assert len(ac) == 2                        # first fix + ONE capped update


def test_sub_fix_and_datum_log_with_quality():
    w = _World(); log = SensorLog()
    w.sub_contacts["ssk_1"] = dict(
        pos=np.array([-30_000.0, 0.0, 60_000.0]), quality=1_400.0,
        kind="sub", last_heard=0.0, age=0.0, t_drop=999.0, sub_id="ssk_1")
    w.sub_contacts["ssk_1_datum"] = dict(
        pos=np.array([-31_000.0, 0.0, 61_000.0]), quality=2_000.0,
        kind="datum", last_heard=0.0, age=0.0, t_drop=999.0, sub_id="ssk_1")
    _run(w, log, 2)
    ac = [e for e in log.events if e["lane"] == "acoustic"]
    labels = sorted(e["label"] for e in ac)
    assert labels == ["ACOUSTIC FIX", "LAUNCH DATUM"]
    fix = next(e for e in ac if e["label"] == "ACOUSTIC FIX")
    assert fix["quality"] == 1_400.0


# ------------------------------------------------------------ housekeeping

def test_ring_buffer_caps_event_count():
    w = _World(); log = SensorLog()
    for i in range(LOG_CAP + 50):
        w.tick()
        w.contacts.tracks[f"tk_{i}"] = _track()
        log.update(w)
        del w.contacts.tracks[f"tk_{i}"]
        log.update(w)
    assert len(log.events) == LOG_CAP


def test_events_between_filters_by_time():
    w = _World(); log = SensorLog()
    w.contacts.tracks["tk_a"] = _track()
    _run(w, log, 2)                       # ~0.017 s
    for _ in range(1200):                 # ~10 s quiet
        w.tick()
        log.update(w)
    w.contacts.tracks["tk_b"] = _track()
    _run(w, log, 2)
    late = log.events_between(5.0, 99.0)
    assert [e["ref"] for e in late] == ["tk_b"]


def test_deterministic_same_run_same_events():
    def battle():
        w = _World(); log = SensorLog()
        w.contacts.tracks["tk_a"] = _track()
        _run(w, log, 300)
        del w.contacts.tracks["tk_a"]
        _run(w, log, 300)
        return [(e["t"], e["lane"], e["label"], e["ref"])
                for e in log.events]
    assert battle() == battle()
