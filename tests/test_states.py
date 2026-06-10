"""Menu logic tests (pure helpers in game/states.py — GL-free)."""

from game.states import (ITEM_QUIT, ITEM_RESUME, ITEM_SANDBOX, menu_items,
                         move_selection)


def test_menu_items_without_sandbox():
    assert menu_items(False) == [ITEM_SANDBOX, ITEM_QUIT]


def test_menu_items_with_sandbox_gains_resume_first():
    assert menu_items(True) == [ITEM_RESUME, ITEM_SANDBOX, ITEM_QUIT]


def test_move_selection_wraps_both_ways():
    assert move_selection(0, 1, 3) == 1
    assert move_selection(2, 1, 3) == 0
    assert move_selection(0, -1, 3) == 2
    assert move_selection(1, -1, 3) == 0


def test_move_selection_empty_list_stays_zero():
    assert move_selection(0, 1, 0) == 0
