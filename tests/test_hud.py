"""HUD F1-overlay rows (game/hud.py, GL-free): generated live from the
binding table so the overlay can never lie after a rebind."""

import pygame

from game.hud import F1_LABEL, overlay_rows
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
