"""HUD F1-overlay rows (game/hud.py, GL-free): generated live from the
binding table so the overlay can never lie after a rebind."""

import pygame

from game.hud import F1_LABEL, overlay_rows, salvo_readout
from game.keybinds import Keybinds


def test_overlay_rows_track_the_live_binding_table(tmp_path):
    kb = Keybinds(str(tmp_path / "settings.json"))
    rows = overlay_rows(kb)
    headers = [r[1] for r in rows if r[0] == "header"]
    assert headers == ["ENGAGEMENT", "SIMULATION", "CAMERA", "SYSTEM"]
    table = {label: key for kind, label, key in
             (r for r in rows if r[0] == "row")}
    assert table["LAUNCH WEAPON"] == "SPACE"
    assert table["CONTROLS OVERLAY"] == "F1"
    kb.rebind("launch", pygame.K_l)               # the overlay cannot lie
    rows = overlay_rows(kb)
    table = {label: key for kind, label, key in
             (r for r in rows if r[0] == "row")}
    assert table["LAUNCH WEAPON"] == "L"


def test_micro_label_copy_exact():
    assert F1_LABEL == "F1 CONTROLS"              # spec §4.1 exact string


# --------------------------------------------------------------- M6 salvo row

class _FakeQueue:
    def __init__(self, active=False, count_left=0):
        self.active = active
        self.count_left = count_left


class _FakeSandbox:
    def __init__(self, mode="ripple", queue=None):
        self.salvo_mode = mode
        self._salvo = queue if queue is not None else _FakeQueue()


def test_salvo_readout_none_on_legacy_path():
    class _Bare:                                  # no _salvo / salvo_mode
        pass
    assert salvo_readout(_Bare()) is None


def test_salvo_readout_shows_mode_at_rest():
    label, value, _col = salvo_readout(_FakeSandbox(mode="fan"))
    assert label == "SALVO" and value == "FAN"


def test_salvo_readout_shows_queue_progress_while_active():
    sb = _FakeSandbox(mode="tot", queue=_FakeQueue(active=True, count_left=3))
    label, value, _col = salvo_readout(sb)
    assert label == "SALVO" and "TOT" in value and "3" in value
