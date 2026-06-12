"""ContactBoard visible_fn gating (COMBAT fog of war, spec section 3)."""

import numpy as np

from sim.contacts import (DETECT_DELAY_S, TRACK_DROP_S, VIS_CHECK_PERIOD,
                          ContactBoard)

DT = 1.0 / 120.0


class FakeShip:
    """Minimal Ship duck-type for the board (pos/velocity/alive/ship_id)."""

    def __init__(self, sid="s0", pos=(0.0, 0.0, 50_000.0)):
        self.ship_id = sid
        self.pos = np.array(pos, dtype=np.float64)
        self.alive = True

    def velocity(self):
        return np.array([0.0, 0.0, 8.0])


def run(board, ents, seconds, t0=0.0):
    t = t0
    steps = int(round(seconds / DT))
    for _ in range(steps):
        t += DT
        board.update(ents, DT, t)
    return t


def test_none_gate_keeps_legacy_instant_tracking():
    board = ContactBoard((0.0, 0.0))
    board.update([FakeShip()], DT, DT)
    assert "s0" in board.tracks


def test_invisible_entity_never_tracks():
    board = ContactBoard((0.0, 0.0), visible_fn=lambda p, c: False)
    run(board, [FakeShip()], 10.0)
    assert board.tracks == {}


def test_track_forms_only_after_detect_delay():
    board = ContactBoard((0.0, 0.0), visible_fn=lambda p, c: True)
    ship = FakeShip()
    t = run(board, [ship], DETECT_DELAY_S * 0.5)
    assert board.tracks == {}                 # half the delay: not yet
    run(board, [ship], DETECT_DELAY_S, t0=t)  # well past it: tracked
    assert "s0" in board.tracks


def test_lost_track_coasts_then_drops():
    seen = {"v": True}
    board = ContactBoard((0.0, 0.0), visible_fn=lambda p, c: seen["v"])
    ship = FakeShip()
    t = run(board, [ship], DETECT_DELAY_S + 1.0)
    assert "s0" in board.tracks
    seen["v"] = False                         # radar killed / target masked
    t = run(board, [ship], TRACK_DROP_S * 0.5, t0=t)
    assert "s0" in board.tracks               # coasting, not dropped yet
    assert board.tracks["s0"]["age"] > 1.0    # estimate is aging (map fades)
    run(board, [ship], TRACK_DROP_S, t0=t)
    assert board.tracks == {}                 # stale: dropped


def test_gate_receives_size_class():
    classes = []

    def gate(pos, size_class):
        classes.append(size_class)
        return True

    board = ContactBoard((0.0, 0.0), visible_fn=gate)
    run(board, [FakeShip()], VIS_CHECK_PERIOD * 3)
    assert set(classes) == {"ship"}
