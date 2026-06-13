"""Tests for CombatSetupState (game/combat_setup.py) and CombatEndOverlay
(game/combat_end.py).  All logic runs headless -- mirrors tests/test_states.py.

Coverage contract:
  - seed editing: digit accumulation, BACKSPACE, ENTER commits, ESC cancels
  - seed: LEFT/RIGHT nudge, R randomize (deterministic), no host RNG
  - steppers: clamp at min and max, step size
  - page toggle: TAB switches page, resets selection
  - build_config(): returns a CombatConfig with the edited values, clamped
  - START fires the start_cb with the correct config after the press-flash
  - ESC returns to the main menu
  - CombatEndOverlay: three options correct, selecting fires right callback,
    ESC fires MAIN MENU callback
"""

import pygame
import pytest

from game.combat_end import CombatEndOverlay
from game.combat_setup import (
    CombatSetupState,
    _LCG_A, _LCG_C, _LCG_MOD, _SEED_MAX,
    _PAGE_WORLD, _PAGE_ARMORY, _PAGE_NAMES,
)
from world.combat_config import CombatConfig


# ------------------------------------------------------------------ helpers

def key_event(key, unicode=""):
    return pygame.event.Event(pygame.KEYDOWN, key=key, mod=0,
                               scancode=0, unicode=unicode)


class Recorder:
    """Swallows any method call and records nothing (audio stub)."""
    def __getattr__(self, name):
        return lambda *a, **k: None


class FakeStates:
    def __init__(self):
        self.current = None

    def switch(self, state):
        self.current = state


class FakeApp:
    def __init__(self):
        self.audio  = Recorder()
        self.states = FakeStates()
        self.menu   = "MENU_SENTINEL"
        self.running = True
        self.combat_configs: list = []

    def start_combat_with(self, cfg):
        self.combat_configs.append(cfg)

    def ui_text(self):
        raise RuntimeError("GL not available in headless tests")


# ------------------------------------------------------------------ fixtures

@pytest.fixture
def app():
    return FakeApp()


@pytest.fixture
def setup(app):
    """CombatSetupState wired to FakeApp.start_combat_with as start_cb."""
    return CombatSetupState(app, app.start_combat_with)


@pytest.fixture
def end_victory(app):
    app.rematch_calls    = 0
    app.new_battle_calls = 0
    app.menu_calls       = 0
    return CombatEndOverlay(
        app, victory=True,
        rematch_cb   = lambda: setattr(app, "rematch_calls",    app.rematch_calls    + 1),
        new_battle_cb= lambda: setattr(app, "new_battle_calls", app.new_battle_calls + 1),
        menu_cb      = lambda: setattr(app, "menu_calls",       app.menu_calls       + 1),
    )


@pytest.fixture
def end_defeat(app):
    app.rematch_calls    = 0
    app.new_battle_calls = 0
    app.menu_calls       = 0
    return CombatEndOverlay(
        app, victory=False,
        rematch_cb   = lambda: setattr(app, "rematch_calls",    app.rematch_calls    + 1),
        new_battle_cb= lambda: setattr(app, "new_battle_calls", app.new_battle_calls + 1),
        menu_cb      = lambda: setattr(app, "menu_calls",       app.menu_calls       + 1),
    )


# ================================================================== CombatSetupState

# ---------------------------------------------------------------- page toggle

def test_page_toggle_tab_key(setup):
    assert setup._page == _PAGE_WORLD
    setup.handle_event(key_event(pygame.K_TAB))
    assert setup._page == _PAGE_ARMORY
    setup.handle_event(key_event(pygame.K_TAB))
    assert setup._page == _PAGE_WORLD


def test_page_toggle_resets_selection(setup):
    setup.handle_event(key_event(pygame.K_DOWN))   # move off row 0
    assert setup._sel != 0
    setup.handle_event(key_event(pygame.K_TAB))
    assert setup._sel == 0


def test_page_world_has_seed_row(setup):
    assert setup._page == _PAGE_WORLD
    rows = setup._rows()
    kinds = [r["kind"] for r in rows]
    assert "seed" in kinds


def test_page_armory_has_only_steppers_and_action(setup):
    setup.handle_event(key_event(pygame.K_TAB))
    assert setup._page == _PAGE_ARMORY
    rows = setup._rows()
    for r in rows:
        assert r["kind"] in ("stepper", "action")


# ---------------------------------------------------------------- seed: digit editing

def test_seed_digits_accumulate(setup):
    """Typing digits on the seed row accumulates them in the buffer."""
    # Focus the seed row (it should be row 0 on the world page)
    seed_idx = next(i for i, r in enumerate(setup._rows()) if r["kind"] == "seed")
    setup._sel = seed_idx
    # Type three digits
    for ch in "42":
        setup.handle_event(key_event(pygame.K_4 if ch == "4" else pygame.K_2,
                                     unicode=ch))
    assert setup._seed_digits == "42"
    assert setup._seed_editing is True


def test_seed_digits_commit_on_enter(setup):
    seed_idx = next(i for i, r in enumerate(setup._rows()) if r["kind"] == "seed")
    setup._sel = seed_idx
    setup.handle_event(key_event(pygame.K_9, unicode="9"))
    setup.handle_event(key_event(pygame.K_9, unicode="9"))  # "99"
    setup.handle_event(key_event(pygame.K_RETURN))
    assert setup._seed_editing is False
    assert setup._fields["seed"] == 99


def test_seed_digits_esc_cancels_without_committing(setup):
    seed_idx = next(i for i, r in enumerate(setup._rows()) if r["kind"] == "seed")
    setup._sel = seed_idx
    original  = setup._fields["seed"]
    setup.handle_event(key_event(pygame.K_5, unicode="5"))
    setup.handle_event(key_event(pygame.K_ESCAPE))
    assert setup._seed_editing is False
    assert setup._fields["seed"] == original


def test_seed_digits_backspace(setup):
    seed_idx = next(i for i, r in enumerate(setup._rows()) if r["kind"] == "seed")
    setup._sel = seed_idx
    setup.handle_event(key_event(pygame.K_1, unicode="1"))
    setup.handle_event(key_event(pygame.K_2, unicode="2"))
    setup.handle_event(key_event(pygame.K_BACKSPACE))
    assert setup._seed_digits == "1"


def test_seed_lr_nudge(setup):
    seed_idx = next(i for i, r in enumerate(setup._rows()) if r["kind"] == "seed")
    setup._sel = seed_idx
    before = setup._fields["seed"]
    setup.handle_event(key_event(pygame.K_RIGHT))
    assert setup._fields["seed"] == before + 1
    setup.handle_event(key_event(pygame.K_LEFT))
    assert setup._fields["seed"] == before


def test_seed_r_randomizes_deterministically(setup):
    """R advances the LCG; same sequence from the same starting counter."""
    seed_idx = next(i for i, r in enumerate(setup._rows()) if r["kind"] == "seed")
    setup._sel = seed_idx
    # One R press
    setup.handle_event(key_event(pygame.K_r))
    expected_step1 = (0 * _LCG_A + _LCG_C) % _LCG_MOD & _SEED_MAX
    assert setup._fields["seed"] == expected_step1
    # Second R press
    setup.handle_event(key_event(pygame.K_r))
    expected_step2 = (expected_step1 * _LCG_A + _LCG_C) % _LCG_MOD & _SEED_MAX
    assert setup._fields["seed"] == expected_step2


def test_seed_clamp_max(setup):
    seed_idx = next(i for i, r in enumerate(setup._rows()) if r["kind"] == "seed")
    setup._sel = seed_idx
    setup._fields["seed"] = _SEED_MAX
    setup.handle_event(key_event(pygame.K_RIGHT))
    assert setup._fields["seed"] == _SEED_MAX   # clamped, not wrapped


def test_seed_clamp_min(setup):
    seed_idx = next(i for i, r in enumerate(setup._rows()) if r["kind"] == "seed")
    setup._sel = seed_idx
    setup._fields["seed"] = 0
    setup.handle_event(key_event(pygame.K_LEFT))
    assert setup._fields["seed"] == 0


# ---------------------------------------------------------------- steppers

def test_stepper_increments_by_step(setup):
    """DESTROYERS step=1: RIGHT increases by 1."""
    row_idx = next(i for i, r in enumerate(setup._rows())
                   if r.get("field") == "n_destroyers")
    setup._sel = row_idx
    before = setup._fields["n_destroyers"]
    setup.handle_event(key_event(pygame.K_RIGHT))
    assert setup._fields["n_destroyers"] == before + 1


def test_stepper_clamp_at_max(setup):
    """Stepper stops at hi and does not wrap."""
    row_idx = next(i for i, r in enumerate(setup._rows())
                   if r.get("field") == "n_destroyers")
    row = setup._rows()[row_idx]
    setup._sel = row_idx
    setup._fields["n_destroyers"] = row["hi"]
    setup.handle_event(key_event(pygame.K_RIGHT))
    assert setup._fields["n_destroyers"] == row["hi"]


def test_stepper_clamp_at_min(setup):
    """Stepper stops at lo and does not wrap."""
    row_idx = next(i for i, r in enumerate(setup._rows())
                   if r.get("field") == "n_destroyers")
    row = setup._rows()[row_idx]
    setup._sel = row_idx
    setup._fields["n_destroyers"] = row["lo"]
    setup.handle_event(key_event(pygame.K_LEFT))
    assert setup._fields["n_destroyers"] == row["lo"]


def test_reload_stepper_step_5(setup):
    """Reload rows step by 5 s per press."""
    setup.handle_event(key_event(pygame.K_TAB))    # armory page
    row_idx = next(i for i, r in enumerate(setup._rows())
                   if r.get("field") == "oniks_mag_reload_s")
    setup._sel = row_idx
    before = setup._fields["oniks_mag_reload_s"]
    setup.handle_event(key_event(pygame.K_RIGHT))
    assert setup._fields["oniks_mag_reload_s"] == before + 5


# ---------------------------------------------------------------- navigation

def test_nav_up_down_wraps(setup):
    setup._sel = 0
    setup.handle_event(key_event(pygame.K_UP))
    assert setup._sel == setup._row_count() - 1
    setup.handle_event(key_event(pygame.K_DOWN))
    assert setup._sel == 0


def test_esc_returns_to_menu(setup):
    setup.handle_event(key_event(pygame.K_ESCAPE))
    assert setup.app.states.current == "MENU_SENTINEL"


# ---------------------------------------------------------------- build_config

def test_build_config_returns_combatconfig_instance(setup):
    cfg = setup.build_config()
    assert isinstance(cfg, CombatConfig)


def test_build_config_reflects_edited_values(setup):
    setup._fields["seed"]         = 9999
    setup._fields["n_destroyers"] = 5
    setup._fields["oniks_ammo"]   = 20
    cfg = setup.build_config()
    assert cfg.seed         == 9999
    assert cfg.n_destroyers == 5
    assert cfg.oniks_ammo   == 20


def test_build_config_clamps_out_of_range(setup):
    """Values beyond clamp ranges are silently clamped by build_config."""
    setup._fields["n_destroyers"]   = 999   # max 12
    setup._fields["n_player_radars"]= 0     # min 1
    setup._fields["oniks_ammo"]     = 0     # min 1
    cfg = setup.build_config()
    assert cfg.n_destroyers    == 12
    assert cfg.n_player_radars == 1
    assert cfg.oniks_ammo      == 1


# ---------------------------------------------------------------- START

def _find_start_idx(setup) -> int:
    return next(i for i, r in enumerate(setup._rows())
                if r.get("label") == "START")


def test_start_fires_callback_after_flash(setup):
    setup._sel = _find_start_idx(setup)
    setup.handle_event(key_event(pygame.K_RETURN))
    assert setup.app.combat_configs == []   # press-flash: not fired yet
    assert setup._pending is True

    setup._tick_pending(0.05)
    assert setup.app.combat_configs == []   # still within flash window

    setup._tick_pending(0.05)               # total > PRESS_FLASH_S (0.08 s)
    assert len(setup.app.combat_configs) == 1


def test_start_callback_receives_combatconfig(setup):
    setup._fields["seed"] = 42
    setup._sel = _find_start_idx(setup)
    setup.handle_event(key_event(pygame.K_RETURN))
    setup._tick_pending(0.1)
    assert len(setup.app.combat_configs) == 1
    cfg = setup.app.combat_configs[0]
    assert isinstance(cfg, CombatConfig)
    assert cfg.seed == 42


def test_input_blocked_during_flash(setup):
    """All input events are silently dropped while the press-flash is active."""
    setup._sel = _find_start_idx(setup)
    setup.handle_event(key_event(pygame.K_RETURN))
    before_sel = setup._sel
    # Navigating during the flash should do nothing
    setup.handle_event(key_event(pygame.K_UP))
    assert setup._sel == before_sel   # not moved


def test_effective_time_scale_is_zero(setup):
    assert setup.effective_time_scale() == 0.0


# ================================================================== CombatEndOverlay

def test_end_options_are_rematch_new_battle_menu(end_victory):
    assert end_victory.options == ("REMATCH", "NEW BATTLE", "MAIN MENU")


def test_end_victory_flag(end_victory, end_defeat):
    assert end_victory.victory is True
    assert end_defeat.victory  is False


def test_end_navigation_up_down(end_victory):
    app = end_victory.app
    assert end_victory._sel == 0
    end_victory.handle_event(key_event(pygame.K_DOWN))
    assert end_victory._sel == 1
    end_victory.handle_event(key_event(pygame.K_UP))
    assert end_victory._sel == 0
    # Wrap: UP at row 0
    end_victory.handle_event(key_event(pygame.K_UP))
    assert end_victory._sel == 2  # wraps to last


def test_end_rematch_fires_after_flash(end_victory):
    app = end_victory.app
    end_victory._sel = 0   # REMATCH
    end_victory.handle_event(key_event(pygame.K_RETURN))
    end_victory._tick_pending(0.05)
    assert app.rematch_calls == 0   # still flashing
    end_victory._tick_pending(0.05)
    assert app.rematch_calls == 1


def test_end_new_battle_fires_after_flash(end_victory):
    app = end_victory.app
    end_victory._sel = 1   # NEW BATTLE
    end_victory.handle_event(key_event(pygame.K_RETURN))
    end_victory._tick_pending(0.1)
    assert app.new_battle_calls == 1


def test_end_main_menu_fires_after_flash(end_victory):
    app = end_victory.app
    end_victory._sel = 2   # MAIN MENU
    end_victory.handle_event(key_event(pygame.K_RETURN))
    end_victory._tick_pending(0.1)
    assert app.menu_calls == 1


def test_end_esc_fires_main_menu(end_defeat):
    app = end_defeat.app
    end_defeat.handle_event(key_event(pygame.K_ESCAPE))
    end_defeat._tick_pending(0.1)
    assert app.menu_calls == 1


def test_end_input_blocked_during_flash(end_victory):
    end_victory._sel = 0
    end_victory.handle_event(key_event(pygame.K_RETURN))
    # During the flash all input is blocked
    end_victory.handle_event(key_event(pygame.K_DOWN))
    assert end_victory._sel == 0   # unchanged


def test_end_effective_time_scale_zero(end_victory):
    assert end_victory.effective_time_scale() == 0.0
