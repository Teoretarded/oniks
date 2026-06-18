"""M5 Buk UI surfaces: the buk_round_panel pure helper, the tube_cells buk
branch, the gated TAB platform cycle, and the V round cycle on the buk
platform.  All headless / GL-free.
"""

from __future__ import annotations

import numpy as np

from game.controls import (PLATFORMS_COMBAT, combat_platforms, next_platform)
from game.hud import buk_round_panel, tube_cells
from sim.arsenal import BUK_AGILE, BUK_LONG, BUK_TEL
from world.combat import CombatWorld
from world.combat_config import CombatConfig


# ---------------------------------------------------------------------------
# combat_platforms: the buk tab is GATED on n_buk
# ---------------------------------------------------------------------------

def test_combat_platforms_default_is_byte_identical():
    """n_buk=0 + no swarm -> EXACTLY the legacy three-platform cycle (no buk
    tab) so the default battle is byte-identical."""
    cw = CombatWorld(CombatConfig(seed=1337))
    assert combat_platforms(cw) == PLATFORMS_COMBAT
    assert "buk" not in combat_platforms(cw)


def test_combat_platforms_inserts_buk_after_s300_when_armed():
    """n_buk>0 -> the buk platform appears in the cycle, right after s300."""
    cw = CombatWorld(CombatConfig(seed=1337, n_buk=1))
    plats = combat_platforms(cw)
    assert "buk" in plats
    assert plats.index("buk") == plats.index("s300") + 1
    # TAB from s300 lands on buk; TAB from buk continues to drone.
    assert next_platform("s300", plats) == "buk"
    assert next_platform("buk", plats) == "drone"


def test_combat_platforms_buk_and_swarm_compose():
    """Both gated platforms compose: bastion, s300, buk, drone, swarm."""
    cw = CombatWorld(CombatConfig(seed=1337, n_buk=1, n_swarm_pods=1))
    plats = combat_platforms(cw)
    assert plats == ("bastion", "s300", "buk", "drone", "swarm")


# ---------------------------------------------------------------------------
# buk_round_panel pure helper
# ---------------------------------------------------------------------------

def test_buk_round_panel_armed_both_rounds():
    cw = CombatWorld(CombatConfig(seed=1337, n_buk=1))
    s, _c, name, ammo = buk_round_panel(cw, "9m317")
    assert s == "ARMED"
    assert name == BUK_LONG.display_name.upper()
    assert f"9M317 6/{BUK_TEL.ammo}" in ammo and f"9M338 6/{BUK_TEL.ammo}" in ammo
    s2, _c2, name2, _ammo2 = buk_round_panel(cw, "9m338")
    assert s2 == "ARMED"
    assert name2 == BUK_AGILE.display_name.upper()


def test_buk_round_panel_empty_pool():
    cw = CombatWorld(CombatConfig(seed=1337, n_buk=1))
    cw.buk_9m317_ammo = 0
    s, _c, _name, ammo = buk_round_panel(cw, "9m317")
    assert s == "EMPTY"
    assert "9M317 0/" in ammo                 # both pools always shown


def test_buk_round_panel_reloading():
    cw = CombatWorld(CombatConfig(seed=1337, n_buk=1))
    cw.buk_9m338_ammo = 0
    cw._buk_9m338_mag_reload_left = 10.0      # refill in progress
    cw.buk_9m338_ammo = 1                     # stock present but refill pending
    s, _c, _name, _ammo = buk_round_panel(cw, "9m338")
    assert s == "RELOADING"


# ---------------------------------------------------------------------------
# tube_cells buk branch
# ---------------------------------------------------------------------------

def test_tube_cells_buk_default_world_empty():
    """n_buk=0 -> no buk tubes -> [] (byte-identical default)."""
    cw = CombatWorld(CombatConfig(seed=1337))
    assert tube_cells(cw, "buk") == []


def test_tube_cells_buk_fresh_all_ready():
    cw = CombatWorld(CombatConfig(seed=1337, n_buk=1))
    cells = tube_cells(cw, "buk")
    assert len(cells) == len(cw._buk_tubes)
    assert cells
    assert all(state == "READY" and frac == 1.0
               for (_l, state, frac) in cells)


def test_tube_cells_buk_mid_reload():
    cw = CombatWorld(CombatConfig(seed=1337, n_buk=1))
    cw._buk_tubes[0]["reload_left"] = cw._buk_tube_reload_s * 0.5
    cells = tube_cells(cw, "buk")
    _l, state0, frac0 = cells[0]
    assert state0 == "RELOADING"
    assert 0.0 < frac0 < 1.0
    assert all(c[1] == "READY" for c in cells[1:])


def test_tube_cells_buk_empty_pools():
    cw = CombatWorld(CombatConfig(seed=1337, n_buk=1))
    cw.buk_9m317_ammo = 0
    cw.buk_9m338_ammo = 0
    cells = tube_cells(cw, "buk")
    assert all(state == "EMPTY" for (_l, state, _f) in cells)


# ---------------------------------------------------------------------------
# V round cycle on the buk platform
# ---------------------------------------------------------------------------

class _StubAudio:
    def ui_click(self):
        pass


class _StubApp:
    def __init__(self):
        self.audio = _StubAudio()


class _CycleSandbox:
    """Minimal stand-in exercising SandboxState.cycle_sam_round's
    platform-dispatch without GL."""

    def __init__(self, platform):
        from game.sandbox import SandboxState
        self.active_platform = platform
        self.sam_round = "48n6"
        self.buk_round = "9m317"
        self.app = _StubApp()
        self.cycle_sam_round = SandboxState.cycle_sam_round.__get__(self)

    def show_hint(self, *a, **k):
        pass


def test_v_cycles_buk_round_on_buk_platform():
    sb = _CycleSandbox("buk")
    assert sb.cycle_sam_round() == "9m338"
    assert sb.buk_round == "9m338"
    assert sb.sam_round == "48n6", "the S-300 round must be untouched on buk"
    assert sb.cycle_sam_round() == "9m317"      # wraps back


def test_v_still_cycles_s300_round_off_buk_platform():
    sb = _CycleSandbox("s300")
    assert sb.cycle_sam_round() == "40n6"
    assert sb.sam_round == "40n6"
    assert sb.buk_round == "9m317", "the Buk round must be untouched off buk"
