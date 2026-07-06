"""game/director.py DirectorModel — pure panel logic (GL-free, plain pytest).

Phase C contract (docs/plans/sandbox_war_2026-07-06.md): selection wraps
and skips unselectable rows, ENTER arms target mode on a ready unit (and
refuses a not-ready one with a message), an armed map click issues the
world order exactly once and disarms, the AUTO-ENGAGE row toggles the
world flag, and dead units are never selectable.  The draw half is
GL-touching and exercised by tools/shoot_sandbox_war.py instead.
"""

import numpy as np

from game.director import ROW_TOGGLE, ROW_UNIT, DirectorModel
from sim.ships import ST_SINKING
from world.sandbox_world import SandboxWorld


def _model():
    w = SandboxWorld()
    m = DirectorModel(w)
    m.open = True
    return w, m


def _row_index(m, uid):
    for i, row in enumerate(m.rows()):
        if row["kind"] == ROW_UNIT and row["unit"]["uid"] == uid:
            return i
    raise AssertionError(f"no row for {uid}")


def _armed_destroyer_uid(w):
    return next(u["uid"] for u in w.director_units()
                if u["kind"] == "destroyer" and u["ready"])


def test_model_select_and_arm():
    w, m = _model()
    rows = m.rows()
    assert rows[0]["kind"] == ROW_TOGGLE
    # Wrap: stepping backwards from the top lands on the LAST selectable.
    m.sel = 0
    m.move(-1)
    selectable = [i for i, r in enumerate(m.rows()) if r["selectable"]]
    assert m.sel == selectable[-1]
    # Arm a ready destroyer: ENTER sets target mode.
    uid = _armed_destroyer_uid(w)
    m.sel = _row_index(m, uid)
    msg = m.activate()
    assert m.armed_uid == uid
    assert "CLICK MAP" in msg
    # A not-ready unit refuses to arm and says why.
    empty = next((u for u in w.director_units()
                  if u["kind"] == "destroyer" and u["alive"]
                  and not u["ready"]), None)
    if empty is not None:
        m.armed_uid = None
        m.sel = _row_index(m, empty["uid"])
        msg = m.activate()
        assert m.armed_uid is None
        assert "NOT READY" in msg


def test_model_click_issues_order_and_disarms():
    w, m = _model()
    uid = _armed_destroyer_uid(w)
    ship = next(s for s in w.ships if s.ship_id == uid)
    before = ship.tomahawk_ammo
    m.sel = _row_index(m, uid)
    m.activate()
    assert m.armed_uid == uid
    tx, tz = float(ship.pos[0]) + 30_000.0, float(ship.pos[2]) - 50_000.0
    ok, msg = m.click((tx, tz))
    assert ok, msg
    assert m.armed_uid is None
    assert ship.tomahawk_ammo < before
    # Not armed: a plain map click returns None (the caller just eats it).
    assert m.click((tx, tz)) is None


def test_model_autoengage_row_toggles_world_flag():
    w, m = _model()
    assert w.enemy_weapons_free is False
    m.sel = 0
    msg = m.activate()
    assert w.enemy_weapons_free is True and "ON" in msg
    msg = m.activate()
    assert w.enemy_weapons_free is False and "OFF" in msg


def test_model_dead_units_not_selectable():
    w, m = _model()
    uid = _armed_destroyer_uid(w)
    ship = next(s for s in w.ships if s.ship_id == uid)
    ship.state = ST_SINKING
    dead_idx = _row_index(m, uid)
    assert not m.rows()[dead_idx]["selectable"]
    m.sel = 0
    visited = set()
    for _ in range(2 * len(m.rows())):
        m.move(+1)
        visited.add(m.sel)
    assert dead_idx not in visited


def test_model_cancel_backs_out_one_level():
    w, m = _model()
    uid = _armed_destroyer_uid(w)
    m.sel = _row_index(m, uid)
    m.activate()
    assert m.armed_uid == uid
    assert m.cancel() is True            # first ESC: disarm only
    assert m.armed_uid is None and m.open is True
    assert m.cancel() is True            # second ESC: close
    assert m.open is False
    assert m.cancel() is False           # closed: not consumed
