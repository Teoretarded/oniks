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


# ---------------------------------------------- command board (2026-07-05)

def test_board_contact_rows_fog_honest_and_sorted():
    """The board CONTACTS list — pure, reads only the gated picture.  Own
    (IFF) rounds are excluded (they live as map glyphs); hostile WEAPON
    tracks sort first by range, then other air, then surface."""
    from game.hud import board_contact_rows
    from world.combat import CombatWorld
    from world.combat_config import CombatConfig
    w = CombatWorld(CombatConfig(seed=1337))
    now = w.sim_time
    w.contacts.tracks.clear()
    import numpy as np

    def trk(kind, size, is_air, x, z):
        return dict(pos=np.array([x, 100.0, z]), vel=np.zeros(3), age=0.0,
                    t_next=0.0, is_air=is_air, kind=kind, size=size,
                    first_seen=now - 999.0)

    w.contacts.tracks["far_ship"] = trk(None, "ship", False, 0.0, 200_000.0)
    w.contacts.tracks["tomahawk"] = trk("tomahawk", "missile", True,
                                        0.0, 60_000.0)
    w.contacts.tracks["own_rnd"] = trk("oniks", "missile", True,
                                       0.0, 10_000.0)
    w.contacts.tracks["fighter"] = trk("fighter", "fighter", True,
                                       0.0, 90_000.0)
    rows = board_contact_rows(w, (0.0, 0.0), now)
    sids = [r["sid"] for r in rows]
    assert "own_rnd" not in sids               # IFF rounds are not contacts
    assert sids[0] == "tomahawk"               # hostile weapon first
    assert sids.index("fighter") < sids.index("far_ship")
    assert rows[0]["rng_km"] == 60.0
    assert rows[0]["label"]                    # ladder label, never empty


def test_sensor_picture_rows_reads_owned_state_only():
    from game.hud import sensor_picture_rows
    from world.combat import CombatWorld
    from world.combat_config import CombatConfig
    w = CombatWorld(CombatConfig(seed=1337))
    rows = dict((r[0], r[1]) for r in sensor_picture_rows(w))
    assert rows["RADAR"] == "EMITTING"
    assert "ELINT" in rows and "DRONE" in rows
    w.radar_station.emitting = False
    rows = dict((r[0], r[1]) for r in sensor_picture_rows(w))
    assert rows["RADAR"] == "SILENT"
