"""Regression tests for lightweight playtest/probe helpers."""

import pygame


class _CycleState:
    def __init__(self):
        self.active_platform = "drone"
        self._order = ("bastion", "s300", "drone")

    def handle_event(self, ev):
        if ev.type != pygame.KEYDOWN or ev.key != pygame.K_TAB:
            return
        i = self._order.index(self.active_platform)
        self.active_platform = self._order[(i + 1) % len(self._order)]


def test_playtest_tab_to_reaches_bastion_from_drone():
    from tools.playtest_combat import tab_to

    state = _CycleState()

    assert tab_to(state, "bastion")
    assert state.active_platform == "bastion"


def test_playtest_fast_step_uses_coarse_chunks_for_long_recon():
    from tools.playtest_killchain import fast_step_plan

    chunks = fast_step_plan(2400.0)

    assert chunks[0] > 1.0 / 120.0
    assert sum(chunks) == 2400.0
    assert len(chunks) <= int(2400.0 / 0.25) + 1


def test_bughunt_probe_step_budget_is_bounded():
    import tools.probe_bughunt_m6 as probe

    assert probe.ALL_FEATURES_STEPS <= 1200
    assert probe.DETERMINISM_STEPS <= 600
    assert probe.LOSE_PATH_STEPS <= 2400
