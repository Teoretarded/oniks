"""Tests for CampaignHubState (game/campaign_screen.py) + the campaign-mode
CombatEndOverlay rows + the CAMPAIGN menu item.  All logic runs headless --
mirrors tests/test_combat_setup.py (GL binds only in enter()/render(), which
these tests never call)."""

import os

import pygame
import pytest

import game.campaign as campaign
from game.campaign_screen import (
    ABANDON, BACK, NEW_CAMPAIGN, START_BATTLE, START_CAMPAIGN,
    CampaignHubState, ladder_text, ledger_rows, next_battle_preview,
    _BATTLES_LO, _BATTLES_HI,
)
from game.combat_end import CombatEndOverlay
from game.states import MAIN_ITEMS
from world.combat_config import CombatConfig


def key_event(key):
    return pygame.event.Event(pygame.KEYDOWN, key=key, mod=0,
                              scancode=0, unicode="")


class Recorder:
    def __getattr__(self, name):
        return lambda *a, **k: None


class FakeStates:
    def __init__(self):
        self.current = None

    def switch(self, state):
        self.current = state


class FakeApp:
    def __init__(self):
        self.audio = Recorder()
        self.states = FakeStates()
        self.menu = "MENU_SENTINEL"
        self.campaign = None
        self.campaign_battle = False
        self.battle_starts = 0

    def start_campaign_battle(self):
        self.battle_starts += 1

    def ui_text(self):
        raise RuntimeError("GL not available in headless tests")


@pytest.fixture
def app():
    return FakeApp()


@pytest.fixture
def save_path(tmp_path):
    return str(tmp_path / "campaign.json")


@pytest.fixture
def hub(app, save_path):
    return CampaignHubState(app, save_path=save_path)


# ------------------------------------------------------------------ menu item

def test_campaign_is_a_main_menu_item():
    assert "CAMPAIGN" in MAIN_ITEMS


# ------------------------------------------------------------------ modes

def test_fresh_mode_when_no_save(hub):
    assert hub.mode == "fresh"
    assert hub.options == (START_CAMPAIGN, BACK)


def test_in_progress_mode_with_live_campaign(app, save_path):
    app.campaign = campaign.new_campaign(777, n_battles=4)
    hub = CampaignHubState(app, save_path=save_path)
    assert hub.mode == "in_progress"
    assert hub.options == (START_BATTLE, ABANDON, BACK)


def test_complete_mode(app, save_path):
    camp = campaign.new_campaign(777, n_battles=2)
    camp.battle_idx = 2
    app.campaign = camp
    hub = CampaignHubState(app, save_path=save_path)
    assert hub.mode == "complete"
    assert hub.options == (NEW_CAMPAIGN, BACK)


def test_hub_loads_save_lazily(app, save_path):
    camp = campaign.new_campaign(4242, n_battles=5)
    camp.grades.append("A")
    camp.battle_idx = 1
    campaign.save(camp, save_path)
    hub = CampaignHubState(app, save_path=save_path)
    assert hub.mode == "in_progress"
    assert app.campaign.seed == 4242
    assert app.campaign.grades == ["A"]


# ------------------------------------------------------------------ fresh flow

def test_start_campaign_creates_saves_and_launches(hub, app, save_path):
    hub._seed = 999
    hub._battles = 4
    hub._sel = next(i for i, r in enumerate(hub._rows())
                    if r.get("label") == START_CAMPAIGN)
    hub.handle_event(key_event(pygame.K_RETURN))
    hub._tick_pending(0.1)
    assert app.campaign is not None
    assert app.campaign.seed == 999
    assert app.campaign.n_battles == 4
    assert app.battle_starts == 1
    assert os.path.exists(save_path)


def test_fresh_battles_stepper_clamps(hub):
    hub._sel = next(i for i, r in enumerate(hub._rows())
                    if r.get("field") == "battles")
    hub._battles = _BATTLES_HI
    hub.handle_event(key_event(pygame.K_RIGHT))
    assert hub._battles == _BATTLES_HI
    hub._battles = _BATTLES_LO
    hub.handle_event(key_event(pygame.K_LEFT))
    assert hub._battles == _BATTLES_LO


def test_fresh_seed_randomize_deterministic(app, save_path):
    a = CampaignHubState(app, save_path=save_path)
    b = CampaignHubState(FakeApp(), save_path=save_path)
    a.handle_event(key_event(pygame.K_r))
    b.handle_event(key_event(pygame.K_r))
    assert a._seed == b._seed          # LCG, no host RNG


# ------------------------------------------------------------------ in-progress flow

def test_start_battle_calls_app(app, save_path):
    app.campaign = campaign.new_campaign(777)
    hub = CampaignHubState(app, save_path=save_path)
    hub._sel = 0                       # START BATTLE
    hub.handle_event(key_event(pygame.K_RETURN))
    hub._tick_pending(0.1)
    assert app.battle_starts == 1


def test_abandon_deletes_save_and_returns_to_fresh(app, save_path):
    camp = campaign.new_campaign(777)
    campaign.save(camp, save_path)
    app.campaign = camp
    hub = CampaignHubState(app, save_path=save_path)
    hub._sel = 1                       # ABANDON
    hub.handle_event(key_event(pygame.K_RETURN))
    hub._tick_pending(0.1)
    assert app.campaign is None
    assert not os.path.exists(save_path)
    assert hub.mode == "fresh"


def test_esc_returns_to_menu(hub, app):
    hub.handle_event(key_event(pygame.K_ESCAPE))
    assert app.states.current == "MENU_SENTINEL"


# ------------------------------------------------------------------ pure helpers

def test_ladder_text_pads_unplayed_battles():
    camp = campaign.new_campaign(1, n_battles=4)
    camp.grades.extend(["S", "B"])
    assert ladder_text(camp) == "S B - -"


def test_ledger_rows_read_caps_for_fresh_ledger():
    camp = campaign.new_campaign(1)
    rows = dict(ledger_rows(camp, CombatConfig(seed=1)))
    assert rows["ONIKS"] == "8/8"          # empty ledger reads cap/cap


def test_ledger_rows_show_carried_counts():
    camp = campaign.new_campaign(1)
    camp.ledger = {"oniks": 3}
    rows = dict(ledger_rows(camp, CombatConfig(seed=1)))
    assert rows["ONIKS"] == "3/8"


def test_next_battle_preview_escalates_with_battle_idx():
    camp = campaign.new_campaign(1, n_battles=8)
    camp.battle_idx = 4
    preview = dict(next_battle_preview(camp))
    base = CombatConfig(seed=1)
    assert int(preview["DESTROYERS"]) == base.n_destroyers + 4


# ------------------------------------------------------------------ end overlay

def _overlay(app, campaign_cb):
    calls = {"menu": 0}
    return CombatEndOverlay(
        app, victory=True,
        rematch_cb=lambda: None,
        new_battle_cb=lambda: None,
        menu_cb=lambda: calls.__setitem__("menu", calls["menu"] + 1),
        campaign_cb=campaign_cb), calls


def test_end_overlay_campaign_mode_rows(app):
    ov, _ = _overlay(app, campaign_cb=lambda: None)
    assert ov.options == ("CONTINUE CAMPAIGN", "MAIN MENU")


def test_end_overlay_legacy_rows_unchanged(app):
    ov = CombatEndOverlay(app, victory=True, rematch_cb=lambda: None,
                          new_battle_cb=lambda: None, menu_cb=lambda: None)
    assert ov.options == ("REMATCH", "NEW BATTLE", "MAIN MENU")


def test_end_overlay_continue_fires_campaign_cb(app):
    fired = []
    ov, _ = _overlay(app, campaign_cb=lambda: fired.append(1))
    ov._sel = 0
    ov.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN,
                                       mod=0, scancode=0, unicode=""))
    ov._tick_pending(0.1)
    assert fired == [1]
