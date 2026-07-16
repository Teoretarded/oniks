"""Focused regressions for CombatState's normal render tail."""

from types import SimpleNamespace

import pytest

from game.combat import CombatState
from game.sandbox import SandboxState


@pytest.mark.parametrize(
    ("map_open", "expected"),
    (
        (False, ["base", "bug_tail"]),
        (True, ["base", "map_rail", "bug_tail"]),
    ),
)
def test_normal_render_always_finishes_with_bug_tail(
        monkeypatch, map_open, expected):
    """The annotate arm clears after a normal frame; the map rail is gated."""
    calls = []
    state = object.__new__(CombatState)
    state._pantsir_engage_left = 0.0
    state.hitcam = SimpleNamespace(
        active=False, tick=lambda _dt: calls.append("hitcam_tick"))
    state.forensics_open = False
    state._end_overlay = None
    state.map_open = map_open
    state.window = SimpleNamespace(size=lambda: (1600, 900))
    state._draw_map_rail = lambda _w, _h: calls.append("map_rail")
    state._render_bug_tail = lambda _w, _h: calls.append("bug_tail")

    monkeypatch.setattr(
        SandboxState, "render", lambda _self, _dt: calls.append("base"))

    CombatState.render(state, 1.0 / 60.0)

    assert calls[0] == "hitcam_tick"
    assert calls[1:] == expected
    assert calls[-1] == "bug_tail"
