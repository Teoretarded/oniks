"""Phase 7 end-to-end: the setup-screen flow, the end screen and the
fog-of-war enemy ground radars wired through the real states.

Scope (the INTEGRATION seam — the input/clamp logic of CombatSetupState and
CombatEndOverlay themselves is pinned by tests/test_combat_setup.py; the
config-driven world internals by tests/test_combat_config.py):

  * menu COMBAT -> CombatSetupState (not straight into the battle)
  * CombatSetupState START -> app.start_combat(config) with the edited config
  * the end-screen callbacks fire the right App flow (REMATCH replays the
    SAME config, NEW BATTLE re-opens setup, MAIN MENU quits)
  * enemy ground radars: imaged-only map markers (fog of war) + win-condition
  * sandbox is untouched: no setup screen, Oniks stays infinite

All logic is GL-free / headless (deferred-enter convention): the states'
handle_event is driven directly, GL is never touched.
"""

from __future__ import annotations

import numpy as np
import pygame
import pytest

from game.combat_end import CombatEndOverlay
from game.combat_setup import CombatSetupState
from game.states import MenuState
from sim.ships import ST_GONE
from world.combat import CombatWorld
from world.combat_config import DEFAULT, CombatConfig

DT = 1.0 / 120.0


# ------------------------------------------------------------------ headless app

def key_event(key, unicode=""):
    return pygame.event.Event(pygame.KEYDOWN, key=key, mod=0,
                              scancode=0, unicode=unicode)


class Recorder:
    """Swallows any attribute access as a no-op callable (audio stub)."""
    def __getattr__(self, name):
        return lambda *a, **k: None


class FakeStates:
    def __init__(self):
        self.current = None
        self.history: list = []

    def switch(self, state):
        self.current = state
        self.history.append(state)


class FakeApp:
    """The App surface the menu / setup / end states touch — records the
    Phase-7 flow without a GL context."""

    def __init__(self, kb=None):
        self.keybinds = kb
        self.audio = Recorder()
        self.states = FakeStates()
        self.menu = "MENU_SENTINEL"
        self.running = True
        # flow recorders
        self.setup_opened = 0
        self.combat_configs: list = []
        self.quit_calls = 0

    # --- the real App methods the states call (signatures must match) ---
    def open_combat_setup(self):
        self.setup_opened += 1
        # mirror the real App: switch to a fresh setup state
        self.states.switch(CombatSetupState(self, self.start_combat))

    def start_combat(self, config=None):
        self.combat_configs.append(config)

    def quit_to_menu(self):
        self.quit_calls += 1

    def ui_text(self):
        raise RuntimeError("GL not available in headless tests")


@pytest.fixture
def app():
    return FakeApp()


# ---------------------------------------------------------------------------
# 1. menu COMBAT -> setup screen (NOT straight into the battle)
# ---------------------------------------------------------------------------

def test_menu_combat_opens_setup_not_battle(app):
    menu = MenuState(app)
    menu._fire("COMBAT")
    assert app.setup_opened == 1
    assert app.combat_configs == []          # battle NOT started yet
    assert isinstance(app.states.current, CombatSetupState)


# ---------------------------------------------------------------------------
# 2. setup START -> start_combat(config) with the edited config
# ---------------------------------------------------------------------------

def test_setup_start_calls_start_combat_with_edited_config(app):
    setup = CombatSetupState(app, app.start_combat)
    # Edit a couple of fields off the default through the public input path.
    setup._fields["n_destroyers"] = 5
    setup._fields["oniks_ammo"] = 3
    # Activate START (selects the action row, then runs the press-flash out).
    setup._sel = setup._row_count() - 1      # START is the last row
    setup._activate_current()
    assert setup._pending is True
    assert app.combat_configs == []          # 80 ms flash first
    setup._tick_pending(0.05)
    assert app.combat_configs == []
    setup._tick_pending(0.05)
    # Fired: exactly one config, carrying the edits, clamped + frozen.
    assert len(app.combat_configs) == 1
    cfg = app.combat_configs[0]
    assert isinstance(cfg, CombatConfig)
    assert cfg.n_destroyers == 5
    assert cfg.oniks_ammo == 3


def test_setup_esc_returns_to_menu(app):
    setup = CombatSetupState(app, app.start_combat)
    setup.handle_event(key_event(pygame.K_ESCAPE))
    assert app.states.current is app.menu
    assert app.combat_configs == []


def test_setup_config_reaches_a_real_world():
    """The config the setup screen builds constructs a matching CombatWorld
    (the full flow's payload — the screen's promise to the world)."""
    setup = CombatSetupState(FakeApp(), lambda c: None)
    setup._fields["seed"] = 4242
    setup._fields["n_destroyers"] = 5
    setup._fields["n_enemy_radars"] = 4
    setup._fields["oniks_ammo"] = 6
    cfg = setup.build_config()
    w = CombatWorld(cfg)
    assert [s.ship_type for s in w.ships] == ["destroyer"] * 5 + ["carrier"]
    assert len(w.enemy_radars) == 4
    assert w._oniks_ammo == 6 and w._oniks_mag_cap == 6


# ---------------------------------------------------------------------------
# 3. end-screen callbacks fire the right App flow
# ---------------------------------------------------------------------------

def _end_overlay(app, victory, config):
    """A CombatEndOverlay wired exactly like game/combat.py does it."""
    return CombatEndOverlay(
        app, victory,
        rematch_cb=lambda: app.start_combat(config),
        new_battle_cb=app.open_combat_setup,
        menu_cb=app.quit_to_menu)


def test_end_rematch_replays_same_config(app):
    cfg = CombatConfig(seed=77, n_destroyers=4)
    overlay = _end_overlay(app, victory=True, config=cfg)
    overlay._activate("REMATCH")
    overlay._tick_pending(0.05)
    overlay._tick_pending(0.05)
    assert app.combat_configs == [cfg]       # SAME config object replayed
    assert app.setup_opened == 0


def test_end_new_battle_reopens_setup(app):
    overlay = _end_overlay(app, victory=False, config=DEFAULT)
    overlay._activate("NEW BATTLE")
    overlay._tick_pending(0.05)
    overlay._tick_pending(0.05)
    assert app.setup_opened == 1
    assert app.combat_configs == []          # setup screen, not a battle


def test_end_main_menu_quits(app):
    overlay = _end_overlay(app, victory=True, config=DEFAULT)
    overlay._activate("MAIN MENU")
    overlay._tick_pending(0.05)
    overlay._tick_pending(0.05)
    assert app.quit_calls == 1


def test_end_esc_fires_main_menu(app):
    overlay = _end_overlay(app, victory=False, config=DEFAULT)
    overlay.handle_event(key_event(pygame.K_ESCAPE))
    overlay._tick_pending(0.05)
    overlay._tick_pending(0.05)
    assert app.quit_calls == 1


def test_end_overlay_victory_and_defeat_banner():
    """The banner reflects the outcome the integrator passes."""
    win = CombatEndOverlay(FakeApp(), True, lambda: None, lambda: None,
                           lambda: None)
    lose = CombatEndOverlay(FakeApp(), False, lambda: None, lambda: None,
                            lambda: None)
    assert win.victory is True
    assert lose.victory is False
    assert win.options == ("REMATCH", "NEW BATTLE", "MAIN MENU")


# ---------------------------------------------------------------------------
# 4. enemy ground radars: fog-of-war map markers + win condition
# ---------------------------------------------------------------------------

def test_enemy_radar_absent_from_map_until_imaged():
    """Fixed-installation fog of war: an enemy ground radar is NOT a map
    marker until a player sensor images it; the 3D geometry exists regardless
    (world.enemy_radars is always populated)."""
    w = CombatWorld(CombatConfig(seed=1337, n_enemy_radars=2))
    assert len(w.enemy_radars) == 2          # geometry exists
    assert w.known_enemy_sites == []         # but no map marker yet


def test_enemy_radar_revealed_by_sar_overflight_and_latches():
    """A SAR transit over an enemy ground radar latches its map marker; the
    knowledge persists after the drone leaves (installations don't move)."""
    w = CombatWorld(CombatConfig(seed=1337, n_enemy_radars=2))
    struct, _r = w.enemy_radars[0]
    rx, rz = float(struct.pos[0]), float(struct.pos[2])
    # Fly the drone on a leg crossing directly over the radar.
    w.drone.pos[0], w.drone.pos[2] = rx, rz - 30_000.0
    w.drone.set_route([(rx, rz + 30_000.0)])
    revealed = False
    for _ in range(int(120.0 / DT)):
        w.step(DT)
        if struct.structure_id in w._enemy_radar_known:
            revealed = True
            break
    assert revealed, "SAR overflight never imaged the enemy radar"
    ids = [s["id"] for s in w.known_enemy_sites]
    assert struct.structure_id in ids
    # Latched: fly the drone far away, the marker stays.
    w.drone.pos[0], w.drone.pos[2] = 0.0, -600.0
    w.drone.set_route([])
    for _ in range(int(5.0 / DT)):
        w.step(DT)
    assert struct.structure_id in [s["id"] for s in w.known_enemy_sites]


def test_victory_requires_radars_dead():
    """Win condition (spec 2.2): with enemy ground radars present, victory is
    withheld until every ship + the airfield + every radar is destroyed."""
    w = CombatWorld(CombatConfig(seed=1337, n_enemy_radars=3))
    for s in w.ships:
        s.state = ST_GONE
    w.airfield.alive = False
    assert not w.victorious                   # radars still standing
    for struct, r in w.enemy_radars:
        struct.alive = False
        r.alive = False
    assert w.victorious


# ---------------------------------------------------------------------------
# 5. determinism end-to-end: same config -> same battle
# ---------------------------------------------------------------------------

def _fleet_anchors(w):
    return sorted((round(float(s.pos[0])), round(float(s.pos[2])))
                  for s in w.ships)


def _radar_pins(w):
    return sorted((round(float(s.pos[0])), round(float(s.pos[2])))
                  for s, _r in w.enemy_radars)


def test_same_config_identical_battle_setup():
    cfg = CombatConfig(seed=2024, n_destroyers=5, n_enemy_radars=3)
    a, b = CombatWorld(cfg), CombatWorld(cfg)
    assert _fleet_anchors(a) == _fleet_anchors(b)
    assert _radar_pins(a) == _radar_pins(b)


def test_different_seed_differs():
    base = CombatConfig(seed=1, n_destroyers=5, n_enemy_radars=3)
    other = CombatConfig(seed=2, n_destroyers=5, n_enemy_radars=3)
    assert _fleet_anchors(CombatWorld(base)) != _fleet_anchors(
        CombatWorld(other))


# ---------------------------------------------------------------------------
# 6. sandbox is untouched: no setup screen, Oniks infinite
# ---------------------------------------------------------------------------

def test_sandbox_menu_item_bypasses_setup(app):
    """SANDBOX never routes through the combat setup screen."""
    seen = {"sandbox": 0}
    app.start_sandbox = lambda: seen.__setitem__("sandbox",
                                                 seen["sandbox"] + 1)
    menu = MenuState(app)
    menu._fire("SANDBOX")
    assert seen["sandbox"] == 1
    assert app.setup_opened == 0
    assert app.combat_configs == []


def test_sandbox_oniks_stays_infinite():
    """The setup-screen armory is COMBAT-only — the sandbox WorldState keeps
    its infinite Oniks (no magazine)."""
    from world.world import WorldState
    ws = WorldState()
    assert ws._oniks_ammo is None
    tgt = np.array([0.0, 0.0, 150_000.0])
    for _ in range(12):
        assert ws.launch("hi-lo", tgt) is not None
        ws.reload_left = 0.0
