"""Menu / pause / settings logic (game/states.py) — GL-free.

Rendering is deferred to ``enter``/``render`` (LOCKED convention), so the
screens' input flows run headless against stub apps: item navigation and
the 80 ms press-flash deferral, the pause menu's MAIN MENU double-ENTER
confirm, and the full settings rebind state machine (listen -> capture,
ESC cancel, conflict -> ENTER swap, R reset row, RESET DEFAULTS confirm,
wheel/auto scroll).
"""

import pygame
import pytest

from game.keybinds import ACTIONS, Keybinds
from game.states import (GROUP_H, MAIN_ITEMS, PAUSE_ITEMS, ROW_H, MenuState,
                         PauseState, SettingsState, move_selection,
                         settings_entries, scroll_to_focus, visible_count)


def key_event(key):
    return pygame.event.Event(pygame.KEYDOWN, key=key, mod=0, scancode=0)


class Recorder:
    def __getattr__(self, name):
        return lambda *a, **k: None


class FakeStates:
    def __init__(self):
        self.current = None

    def switch(self, state):
        self.current = state


class FakeApp:
    def __init__(self, kb=None):
        self.keybinds = kb
        self.audio = Recorder()
        self.states = FakeStates()
        self.menu = "MENU"
        self.sandbox = None
        self.running = True
        self.started = 0
        self.settings_from = []
        self.resumed = 0
        self.quit_to_menu_calls = 0

    def start_sandbox(self):
        self.started += 1

    def start_combat(self):
        self.combat_started = getattr(self, "combat_started", 0) + 1

    def open_settings(self, back_to):
        self.settings_from.append(back_to)

    def resume(self):
        self.resumed += 1

    def quit_to_menu(self):
        self.quit_to_menu_calls += 1


@pytest.fixture
def kb(tmp_path):
    return Keybinds(str(tmp_path / "settings.json"))


# ------------------------------------------------------------ pure helpers

def test_move_selection_wraps_both_ways():
    assert move_selection(0, 1, 3) == 1
    assert move_selection(2, 1, 3) == 0
    assert move_selection(0, -1, 3) == 2
    assert move_selection(1, -1, 3) == 0
    assert move_selection(0, 1, 0) == 0


def test_menu_and_pause_items_per_spec():
    assert MAIN_ITEMS == ("SANDBOX", "COMBAT", "SETTINGS", "QUIT")
    assert PAUSE_ITEMS == ("RESUME", "SETTINGS", "MAIN MENU")


def test_settings_entries_grouped_in_registry_order():
    entries = settings_entries()
    headers = [e[1] for e in entries if e[0] == "header"]
    actions = [e[1].id for e in entries if e[0] == "action"]
    assert headers == ["ENGAGEMENT", "SIMULATION", "CAMERA", "SYSTEM"]
    assert actions == [a.id for a in ACTIONS]
    # every action row sits under its own group's header
    group = None
    for e in entries:
        if e[0] == "header":
            group = e[1]
        elif e[0] == "action":
            assert e[1].group == group


def test_settings_entries_conflict_subrow_follows_its_action():
    entries = settings_entries(conflict_aid="map")
    kinds = [(k, getattr(v, "id", v)) for k, v in entries]
    i = kinds.index(("action", "map"))
    assert kinds[i + 1] == ("conflict", "map")
    assert sum(1 for k, _ in kinds if k == "conflict") == 1


def test_visible_count_walks_mixed_heights():
    entries = settings_entries()      # header 24 + rows 40
    assert visible_count(entries, 0, GROUP_H + 2 * ROW_H) == 3
    assert visible_count(entries, 0, GROUP_H + 2 * ROW_H - 1) == 2
    assert visible_count(entries, 0, 10_000) == len(entries)


def test_scroll_to_focus_keeps_target_visible_with_lookahead():
    entries = settings_entries()
    view_h = GROUP_H + 4 * ROW_H      # header + 4 rows fit
    # focus above the window snaps up with one row of lookahead
    assert scroll_to_focus(entries, 10, 3, view_h) == 2
    # focus already comfortably visible: no movement
    assert scroll_to_focus(entries, 0, 2, view_h) == 0
    # focus below: scrolls down until visible + 1 lookahead row
    s = scroll_to_focus(entries, 0, 8, view_h)
    n = visible_count(entries, s, view_h)
    assert s + 1 <= 8 < s + n - 1 or s + n >= len(entries)
    # last entry reachable
    last = len(entries) - 1
    s = scroll_to_focus(entries, 0, last, view_h)
    assert last < s + visible_count(entries, s, view_h)


# --------------------------------------------------------------- main menu

def test_menu_starts_on_sandbox_and_navigates(kb):
    menu = MenuState(FakeApp(kb))
    assert tuple(menu.items) == MAIN_ITEMS
    assert menu.sel == 0
    menu.handle_event(key_event(pygame.K_DOWN))
    assert menu.items[menu.sel] == "COMBAT"
    menu.handle_event(key_event(pygame.K_UP))
    assert menu.items[menu.sel] == "SANDBOX"


def test_menu_combat_item_starts_combat(kb):
    menu = MenuState(FakeApp(kb))
    menu._fire("COMBAT")
    assert menu.app.combat_started == 1


def test_menu_press_flash_defers_then_fires(kb):
    app = FakeApp(kb)
    menu = MenuState(app)
    menu.handle_event(key_event(pygame.K_RETURN))
    assert app.started == 0               # 80 ms flash first
    menu._tick_pending(0.05)
    assert app.started == 0
    menu._tick_pending(0.05)
    assert app.started == 1


def test_menu_settings_and_quit(kb):
    app = FakeApp(kb)
    menu = MenuState(app)
    menu.handle_event(key_event(pygame.K_DOWN))
    menu.handle_event(key_event(pygame.K_DOWN))   # SANDBOX -> COMBAT -> SETTINGS
    menu.handle_event(key_event(pygame.K_RETURN))
    menu._tick_pending(0.1)
    assert app.settings_from == [menu]
    menu.handle_event(key_event(pygame.K_DOWN))   # SETTINGS -> QUIT
    menu.handle_event(key_event(pygame.K_RETURN))
    menu._tick_pending(0.1)
    assert app.running is False


def test_menu_escape_quits_app(kb):
    app = FakeApp(kb)
    MenuState(app).handle_event(key_event(pygame.K_ESCAPE))
    assert app.running is False


def test_menu_freezes_sim():
    assert MenuState(FakeApp()).effective_time_scale() == 0.0


# -------------------------------------------------------------- pause menu

def test_pause_escape_resumes(kb):
    app = FakeApp(kb)
    pause = PauseState(app)
    assert tuple(pause.items) == PAUSE_ITEMS
    pause.handle_event(key_event(pygame.K_ESCAPE))
    assert app.resumed == 1


def test_pause_resume_item_fires_after_flash(kb):
    app = FakeApp(kb)
    pause = PauseState(app)
    pause.handle_event(key_event(pygame.K_RETURN))
    pause._tick_pending(0.1)
    assert app.resumed == 1


def test_pause_main_menu_needs_double_enter(kb):
    app = FakeApp(kb)
    pause = PauseState(app)
    pause.handle_event(key_event(pygame.K_DOWN))
    pause.handle_event(key_event(pygame.K_DOWN))  # MAIN MENU
    pause.handle_event(key_event(pygame.K_RETURN))
    pause._tick_pending(0.1)
    assert app.quit_to_menu_calls == 0            # armed, not fired
    assert pause.confirm_armed
    pause.handle_event(key_event(pygame.K_RETURN))
    pause._tick_pending(0.1)
    assert app.quit_to_menu_calls == 1


def test_pause_moving_selection_disarms_confirm(kb):
    app = FakeApp(kb)
    pause = PauseState(app)
    pause.handle_event(key_event(pygame.K_UP))    # wrap to MAIN MENU
    pause.handle_event(key_event(pygame.K_RETURN))
    assert pause.confirm_armed
    pause.handle_event(key_event(pygame.K_UP))
    assert not pause.confirm_armed
    pause.handle_event(key_event(pygame.K_RETURN))
    pause._tick_pending(0.1)
    assert app.quit_to_menu_calls == 0


# ---------------------------------------------------------------- settings

@pytest.fixture
def settings(kb):
    app = FakeApp(kb)
    state = SettingsState(app)
    state.back_to = "BACK_TARGET"
    return state


def test_settings_focus_walks_nonreserved_actions_then_buttons(settings):
    focusables = settings.focusables
    reserved = {a.id for a in ACTIONS if a.reserved}
    assert focusables[-2:] == ["RESET", "BACK"]
    assert [aid for aid in focusables[:-2]] == [
        a.id for a in ACTIONS if not a.reserved]
    assert not reserved & set(focusables)


def test_settings_enter_listens_then_captures(settings):
    kb = settings.app.keybinds
    settings.handle_event(key_event(pygame.K_RETURN))
    assert settings.listening == "launch"
    settings.handle_event(key_event(pygame.K_j))
    assert settings.listening is None
    assert kb.key_for("launch") == pygame.K_j     # saved immediately


def test_settings_escape_cancels_listening(settings):
    kb = settings.app.keybinds
    settings.handle_event(key_event(pygame.K_RETURN))
    settings.handle_event(key_event(pygame.K_ESCAPE))
    assert settings.listening is None
    assert kb.key_for("launch") == pygame.K_SPACE
    # and the screen did NOT navigate away
    assert settings.app.states.current is None


def test_settings_reserved_key_capture_cancels(settings):
    kb = settings.app.keybinds
    settings.handle_event(key_event(pygame.K_RETURN))
    settings.handle_event(key_event(pygame.K_F1))
    assert settings.listening is None
    assert kb.key_for("launch") == pygame.K_SPACE


def test_settings_conflict_offers_swap(settings):
    kb = settings.app.keybinds
    # focus TACTICAL MAP (3rd non-reserved action)
    settings.focus = settings.focusables.index("map")
    settings.handle_event(key_event(pygame.K_RETURN))
    settings.handle_event(key_event(pygame.K_c))
    assert settings.conflict == ("map", pygame.K_c, "camera_mode")
    assert kb.key_for("map") == pygame.K_m        # nothing applied yet
    settings.handle_event(key_event(pygame.K_RETURN))
    assert settings.conflict is None
    assert kb.key_for("map") == pygame.K_c
    assert kb.key_for("camera_mode") == pygame.K_m


def test_settings_conflict_escape_cancels(settings):
    kb = settings.app.keybinds
    settings.focus = settings.focusables.index("map")
    settings.handle_event(key_event(pygame.K_RETURN))
    settings.handle_event(key_event(pygame.K_c))
    settings.handle_event(key_event(pygame.K_ESCAPE))
    assert settings.conflict is None
    assert kb.key_for("map") == pygame.K_m
    assert kb.key_for("camera_mode") == pygame.K_c


def test_settings_r_resets_focused_row(settings):
    kb = settings.app.keybinds
    kb.rebind("launch", pygame.K_j)
    settings.focus = settings.focusables.index("launch")
    settings.handle_event(key_event(pygame.K_r))
    assert kb.key_for("launch") == pygame.K_SPACE


def test_settings_reset_defaults_needs_confirm(settings):
    kb = settings.app.keybinds
    kb.rebind("launch", pygame.K_j)
    settings.focus = settings.focusables.index("RESET")
    settings.handle_event(key_event(pygame.K_RETURN))
    assert settings.reset_armed
    assert kb.key_for("launch") == pygame.K_j
    settings.handle_event(key_event(pygame.K_RETURN))
    assert not settings.reset_armed
    assert kb.key_for("launch") == pygame.K_SPACE


def test_settings_moving_focus_disarms_reset(settings):
    settings.focus = settings.focusables.index("RESET")
    settings.handle_event(key_event(pygame.K_RETURN))
    settings.handle_event(key_event(pygame.K_UP))
    assert not settings.reset_armed


def test_settings_back_and_escape_return(settings):
    settings.focus = settings.focusables.index("BACK")
    settings.handle_event(key_event(pygame.K_RETURN))
    assert settings.app.states.current == "BACK_TARGET"
    settings.app.states.current = None
    settings.handle_event(key_event(pygame.K_ESCAPE))
    assert settings.app.states.current == "BACK_TARGET"


def test_settings_wheel_scrolls_three_rows(settings):
    assert settings.scroll_idx == 0
    settings.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-1))
    assert settings.scroll_idx == 3
    settings.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=1))
    settings.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=1))
    assert settings.scroll_idx == 0               # clamped at the top


def test_settings_freezes_sim(settings):
    assert settings.effective_time_scale() == 0.0
