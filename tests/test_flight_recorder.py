"""FlightRecorder (game/flight_recorder.py) — the debrief's 1:1 data source.

The user-locked ACCURACY CONTRACT under test: samples are the round's EXACT
positions at fixed sim-clock boundaries (no interpolation), launch + death
anchors are exact, own rounds only, deterministic, and the recorder never
claims more than it saw (vanished rounds close at their last sample).
"""

import numpy as np

from game.flight_recorder import FlightRecorder


class _Round:
    def __init__(self, hostile=False, kind="oniks"):
        self.is_hostile = hostile
        self.alive = True
        self.weapon_id = kind
        self.pos = np.array([0.0, 0.0, 0.0])

    def fly_to(self, x, y, z):
        self.pos = np.array([float(x), float(y), float(z)])


class _World:
    def __init__(self):
        self.sim_time = 0.0
        self.missiles = []

    def tick(self, dt=1.0 / 120.0):
        self.sim_time += dt


DT = 1.0 / 120.0


def _run(world, rec, steps):
    for _ in range(steps):
        world.tick(DT)
        rec.update(world)


def test_samples_are_exact_positions_at_fixed_boundaries():
    w = _World(); r = FlightRecorder(sample_period=0.5)
    m = _Round(); w.missiles.append(m)
    poss = []
    for i in range(241):                     # 2.0 s of sim
        w.tick(DT)
        m.fly_to(i * 10.0, i * 2.0, 0.0)     # exact known positions
        rec_before = len(r.tracks)
        r.update(w)
        poss.append((w.sim_time, tuple(m.pos)))
    recs = r.rounds()
    assert len(recs) == 1
    path = r.path_of(recs[0])
    # launch anchor at first seen step, then one sample per 0.5 s crossing
    assert path.shape[0] == 5                # t0 + 4 boundary crossings in 2 s
    # every stored sample equals the EXACT position the round had that tick
    stored = {round(row[0], 6): (row[1], row[2], row[3]) for row in path}
    truth = {round(t, 6): p for t, p in poss}
    for t, p in stored.items():
        assert t in truth
        assert truth[t] == p                 # 1:1 — float-equal, no smoothing


def test_death_anchor_is_exact_and_recorded_once():
    w = _World(); r = FlightRecorder(sample_period=0.5)
    m = _Round(); w.missiles.append(m)
    _run(w, r, 30)
    m.fly_to(1234.5, 67.8, 9.0)
    m.alive = False
    _run(w, r, 3)                            # dead for several steps
    rec = r.rounds()[0]
    assert rec["death"] is not None
    assert tuple(rec["death"]["pos"]) == (1234.5, 67.8, 9.0)
    # closed: no further samples accumulate while it stays in the list
    n = len(rec["samples"])
    _run(w, r, 120)
    assert len(rec["samples"]) == n


def test_hostile_rounds_are_never_recorded():
    w = _World(); r = FlightRecorder()
    w.missiles.append(_Round(hostile=True, kind="sm6"))
    _run(w, r, 120)
    assert r.tracks == {}


def test_pruned_round_closes_at_exact_terminal_position():
    """The world prunes a dead round within its death step — the recorder
    holds the object, whose pos FREEZES at the true death point, so the
    close-out anchors that exact position (not the last boundary sample)."""
    w = _World(); r = FlightRecorder(sample_period=0.5)
    m = _Round(); w.missiles.append(m)
    _run(w, r, 70)                           # ~0.58 s: launch + 1 boundary
    m.fly_to(999.0, 5.0, 777.0)              # true terminal position
    w.missiles.clear()                       # pruned, no dead step observed
    w.tick(DT); r.update(w)
    rec = r.rounds()[0]
    assert rec["death"] is not None
    assert tuple(rec["death"]["pos"]) == (999.0, 5.0, 777.0)
    assert abs(rec["death"]["t"] - w.sim_time) < 1e-9
    assert tuple(rec["samples"][-1][1:]) == (999.0, 5.0, 777.0)


def test_deterministic_same_run_same_records():
    def battle():
        w = _World(); r = FlightRecorder(sample_period=0.5)
        m = _Round(); w.missiles.append(m)
        for i in range(600):
            w.tick(DT)
            m.fly_to(i * 3.0, 100.0 + i, i * 0.5)
            if i == 400:
                m.alive = False
            r.update(w)
        return r.path_of(r.rounds()[0])
    a, b = battle(), battle()
    assert np.array_equal(a, b)


def test_sequence_numbers_per_kind():
    w = _World(); r = FlightRecorder()
    a, b, c = _Round(kind="oniks"), _Round(kind="oniks"), _Round(kind="zircon")
    w.missiles += [a, b, c]
    _run(w, r, 2)
    kinds = sorted((rec["kind"], rec["seq"]) for rec in r.rounds())
    assert kinds == [("oniks", 1), ("oniks", 2), ("zircon", 1)]
