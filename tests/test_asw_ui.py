"""M5 ASW UI-wiring tests: the sandbox verbs (U buoy-drop mode / K ASW
launch) + the map-click drop against a REAL CombatWorld (n_subs>0), all
headless (the verbs live on SandboxState but touch only world/show_hint/
audio/buoy_drop_armed, so they run on a bare host shim)."""

import numpy as np
import pytest

from game.sandbox import (
    HINT_ASW_NO_FIX, HINT_ASW_UNFITTED, HINT_BUOY_ARMED, HINT_BUOY_EMPTY,
    HINT_BUOY_OFF, HINT_BUOY_UNFITTED, SandboxState,
)
from world.combat import CombatWorld
from world.combat_config import CombatConfig


class Recorder:
    def __getattr__(self, name):
        return lambda *a, **k: None


class _App:
    audio = Recorder()


class _Host:
    """Bare shim exposing exactly what the ASW verbs read (unbound-call
    pattern: SandboxState.toggle_buoy_drop(host))."""

    def __init__(self, world):
        self.world = world
        self.app = _App()
        self.buoy_drop_armed = False
        self.hints = []

    def show_hint(self, text, seconds=None):
        self.hints.append(text)


@pytest.fixture(scope="module")
def asw_world():
    return CombatWorld(CombatConfig(seed=1337, n_subs=1, n_sonobuoys=2,
                                    asw_ammo=1, sub_kalibr_ammo=4))


def test_toggle_refuses_with_zero_stock():
    """A battle that never FITTED buoys points at the setup page (the live
    playtest hit 'NO SONOBUOYS LEFT' having deployed nothing — misleading);
    a battle that HAD stock and spent it says empty."""
    host = _Host(CombatWorld(CombatConfig(seed=1337)))   # n_sonobuoys=0
    SandboxState.toggle_buoy_drop(host)
    assert host.buoy_drop_armed is False
    assert host.hints == [HINT_BUOY_UNFITTED]

    spent = CombatWorld(CombatConfig(seed=1337, n_subs=1, n_sonobuoys=1,
                                     sub_kalibr_ammo=4))
    spent.place_sonobuoy((0.0, 90_000.0))                # exhaust the stock
    host2 = _Host(spent)
    SandboxState.toggle_buoy_drop(host2)
    assert host2.hints == [HINT_BUOY_EMPTY]


def test_toggle_arms_and_disarms(asw_world):
    host = _Host(asw_world)
    SandboxState.toggle_buoy_drop(host)
    assert host.buoy_drop_armed is True
    assert host.hints[-1] == HINT_BUOY_ARMED
    SandboxState.toggle_buoy_drop(host)
    assert host.buoy_drop_armed is False
    assert host.hints[-1] == HINT_BUOY_OFF


def test_map_drop_places_buoy_and_exhausts_stock():
    world = CombatWorld(CombatConfig(seed=1337, n_subs=1, n_sonobuoys=2,
                                     sub_kalibr_ammo=4))
    host = _Host(world)
    SandboxState.toggle_buoy_drop(host)
    assert SandboxState.map_drop_buoy(host, (5_000.0, 90_000.0))
    assert len(world.sonobuoys) == 1
    assert np.allclose(world.sonobuoys[0][[0, 2]], (5_000.0, 90_000.0))
    assert host.buoy_drop_armed is True          # stock left: stays armed
    assert SandboxState.map_drop_buoy(host, (9_000.0, 95_000.0))
    assert len(world.sonobuoys) == 2
    assert host.buoy_drop_armed is False         # stock exhausted: disarms


def test_map_drop_noop_when_not_armed(asw_world):
    host = _Host(asw_world)
    assert SandboxState.map_drop_buoy(host, (0.0, 0.0)) is False


def test_request_asw_refuses_blind_then_kills_off_a_fix():
    """End-to-end: no fix -> refuse; a bracketing buoy field on a LOUD boat
    forms a fix; the ASW round launched at it acquires + kills the sub."""
    from sim.submarine import SUB_LAUNCH

    world = CombatWorld(CombatConfig(seed=1337, n_subs=1, n_sonobuoys=3,
                                     asw_ammo=2, sub_kalibr_ammo=4))
    host = _Host(world)
    DT = 1.0 / 120.0

    # (a) no localized fix yet -> the verb refuses with the right hint
    SandboxState.request_asw(host)
    assert host.hints == [HINT_ASW_NO_FIX]
    assert world.asw_ammo_left == 2

    # (b) bracket the boat with buoys, hold it loud, wait for the cross-fix
    sub = world.subs[0]
    sx, sz = float(sub.pos[0]), float(sub.pos[2])
    world.place_sonobuoy((sx - 15_000.0, sz - 10_000.0))
    world.place_sonobuoy((sx + 15_000.0, sz - 10_000.0))
    world.place_sonobuoy((sx, sz + 8_000.0))
    sub.state = SUB_LAUNCH
    for _ in range(int(6.0 / DT)):
        sub.launch_transient = True
        world._step_acoustic_sensors()
        world.sim_time += DT
        if sub.sub_id in world.sub_contacts:
            break
    assert sub.sub_id in world.sub_contacts, "buoy field must localize the boat"

    # (c) fire: the round flies the FIX; the terminal basket resolves the kill
    host.hints.clear()
    SandboxState.request_asw(host)
    assert world.asw_ammo_left == 1
    assert len(world.asw_rounds) == 1
    for _ in range(int(400.0 / DT)):
        world._step_asw_rounds(DT)
        if not world.asw_rounds:
            break
    assert not sub.alive, "a sharp cross-fix inside the basket must kill"


def test_request_asw_unfitted_magazine_hint():
    world = CombatWorld(CombatConfig(seed=1337, n_subs=1, sub_kalibr_ammo=4))
    host = _Host(world)                          # asw_ammo NEVER fitted
    SandboxState.request_asw(host)
    assert host.hints == [HINT_ASW_UNFITTED]
