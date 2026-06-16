"""tube_cells pure helper (M1-F4): per-tube READY/RELOADING/EMPTY readout for
the active launcher. Friendly own-force telemetry. SANDBOX -> []. Tested against
a real CombatWorld (poking tube dicts) so the helper matches the live structures."""

from game.hud import tube_cells


def _cw():
    from world.combat import CombatWorld
    return CombatWorld()                     # DEFAULT config


def test_sandbox_world_without_tubes_returns_empty():
    class _Sandbox:                          # no _oniks_tubes / _s300_tubes
        pass
    assert tube_cells(_Sandbox(), "bastion") == []
    assert tube_cells(_Sandbox(), "s300") == []


def test_fresh_oniks_battery_all_cells_ready():
    cw = _cw()
    cells = tube_cells(cw, "bastion")
    assert len(cells) == len(cw._oniks_tubes)
    assert cells, "expected at least one Oniks tube in the default battery"
    assert all(state == "READY" for (_label, state, _frac) in cells)
    assert all(frac == 1.0 for (_label, _state, frac) in cells)


def test_mid_reload_oniks_tube_is_reloading_frac_strictly_between_0_and_1():
    cw = _cw()
    t = cw._oniks_tubes[0]
    t["loaded"] = False
    t["reload_left"] = cw._oniks_tube_reload_s * 0.5      # halfway through
    cells = tube_cells(cw, "bastion")
    label0, state0, frac0 = cells[0]
    assert state0 == "RELOADING"
    assert 0.0 < frac0 < 1.0                              # two-sided (spec: frac in (0,1))
    assert all(c[1] == "READY" for c in cells[1:])        # the rest unaffected


def test_empty_magazine_oniks_cells_all_empty():
    cw = _cw()
    cw._oniks_ammo = 0
    for t in cw._oniks_tubes:
        t["loaded"] = False
        t["reload_left"] = 0.0
    assert all(state == "EMPTY" for (_l, state, _f) in tube_cells(cw, "bastion"))


def test_s300_cell_count_matches_tubes():
    cw = _cw()
    assert len(tube_cells(cw, "s300")) == len(cw._s300_tubes)


def test_determinism_same_world_same_cells():
    cw = _cw()
    assert tube_cells(cw, "bastion") == tube_cells(cw, "bastion")
