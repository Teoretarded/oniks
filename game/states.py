"""GameState base + state machine. MenuState arrives with Task 21.

States receive the App (window, renderer, paused/frame_step flags) and
implement the three loop callbacks dispatched by main.App.run:
``handle_event`` / ``sim_step`` / ``render``.
"""

from __future__ import annotations


class GameState:
    """Base state: no-op callbacks + enter/leave hooks for the machine."""

    def __init__(self, app):
        self.app = app

    def enter(self) -> None:
        pass

    def leave(self) -> None:
        pass

    def handle_event(self, ev) -> None:
        pass

    def sim_step(self, dt: float) -> None:
        pass

    def render(self, dt_real: float) -> None:
        pass

    def effective_time_scale(self) -> float:
        """Sim seconds per real second this frame (states may clamp it)."""
        return 1.0


class StateMachine:
    """Holds the active state; ``switch`` runs the leave/enter hooks."""

    def __init__(self):
        self.current: GameState | None = None

    def switch(self, state: GameState | None) -> None:
        if self.current is not None:
            self.current.leave()
        self.current = state
        if state is not None:
            state.enter()
