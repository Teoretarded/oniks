"""world/sandbox_world.py — the WAR SANDBOX world (GL-free, plain pytest).

A1 contract (docs/plans/sandbox_war_2026-07-06.md):
  - CombatWorld defaults enemy_weapons_free True (every existing battle
    byte-identical); SandboxWorld defaults False (passive until ordered);
  - the toybox roster spawns: typed combat fleet + carrier + subs +
    enemy air, AND the legacy civilian lane traffic + patrol racetracks;
  - the player picture is ALL-SEEING (ungated board, fog latches open);
  - a hostile round closing on the fleet draws NO enemy fire while
    passive — and draws a real SM-2 once weapons-free (same geometry,
    the flag is the only difference);
  - the sandbox never latches defeated/victorious (the base class WOULD
    have — asserted through the base property on the same instance).

Inbound forcing reuses the established test_enemy_defense.py pattern: a
real Missile teleported into mid-cruise (isinstance filters see it), so
the SM-2 chain runs the same physics the combat suite already pins.
"""

import numpy as np
import pytest

from sim.arsenal import ONIKS
from sim.enemy_ships import Destroyer
from sim.missile import PH_CRUISE, Missile
from sim.sam import SamMissile
from sim.ships import Ship
from world.combat import CombatWorld
from world.sandbox_world import SANDBOX_CONFIG, SandboxWorld
from world.world import WorldState

DT = 1.0 / 120.0

# Inbound forcing geometry: cruise altitude over any radar horizon, well
# outside SM2_MIN_RANGE_M, close enough that the SPY-1 sees it instantly.
INBOUND_SHORT_M = 30_000.0      # spawn 30 km short of the target hull
INBOUND_ALT_M = 14_000.0        # hi-lo cruise band (test_enemy_defense.py)
INBOUND_SPEED = 680.0           # m/s closing


def _closest_destroyer(w):
    """The combat hull nearest the base (reliable SPY-1 geometry)."""
    from world.generation import BASE_POS
    hulls = [s for s in w.ships if isinstance(s, Destroyer)]
    return min(hulls, key=lambda s: float(
        np.hypot(s.pos[0] - BASE_POS[0], s.pos[2] - BASE_POS[2])))


def _force_inbound(w, ship):
    """A real Oniks in mid-cruise, INBOUND_SHORT_M south of ``ship`` and
    closing (the test_enemy_defense.py teleport pattern)."""
    pos = (float(ship.pos[0]), INBOUND_ALT_M,
           float(ship.pos[2]) - INBOUND_SHORT_M)
    m = Missile(ONIKS, np.array(pos, dtype=np.float64), 0.0, "hi-lo",
                np.array([ship.pos[0], 0.0, ship.pos[2]]))
    m.vel[:] = (0.0, 0.0, INBOUND_SPEED)
    m.prev_pos[:] = m.pos
    m.phase = PH_CRUISE
    w.missiles.append(m)
    return m


def _hostile_rounds(w):
    return [m for m in w.missiles if getattr(m, "is_hostile", False)]


# ---------------------------------------------------------------------------
# Flag defaults
# ---------------------------------------------------------------------------

def test_combat_default_weapons_free():
    assert CombatWorld().enemy_weapons_free is True


def test_sandbox_default_passive():
    assert SandboxWorld().enemy_weapons_free is False


# ---------------------------------------------------------------------------
# Toybox roster
# ---------------------------------------------------------------------------

def test_sandbox_toybox_roster():
    w = SandboxWorld()
    from sim.enemy_air import Awacs, Fighter, JammerAircraft

    # Red force: the typed fleet + carrier (a Destroyer subclass).
    assert sum(isinstance(s, Destroyer) for s in w.ships) >= 4
    assert w.carrier in w.ships
    assert len(w.subs) >= 1
    assert all(s.kalibr_ammo > 0 for s in w.subs)
    assert sum(isinstance(e, Fighter) for e in w.enemy_air) >= 2
    assert any(isinstance(e, Awacs) for e in w.enemy_air)
    assert any(isinstance(e, JammerAircraft) for e in w.enemy_air)

    # Civilian traffic + patrol racetracks re-added (plain Ship hulls the
    # combat roster filters ignore).
    civilians = [s for s in w.ships if not isinstance(s, Destroyer)]
    assert len(civilians) == len(WorldState._spawn_ships(w))
    assert all(type(s) is Ship for s in civilians)
    assert len(w.aircraft) >= 4

    # Blue armory: every optional battery armed by SANDBOX_CONFIG.
    assert len(w.pantsirs) >= 2
    assert len(w._buk_launcher_positions) >= 1
    assert len(w._swarm_pod_positions) >= 1
    assert w.drone is not None
    assert w._asbm_ammo > 0 and w._kh31p_ammo > 0
    assert w.sonobuoys_left > 0 and w.asw_ammo_left > 0


def test_sandbox_civilians_outside_combat_rosters():
    """Traffic hulls must never enter a fire-control roster."""
    w = SandboxWorld()
    civilians = {s.ship_id for s in w.ships if not isinstance(s, Destroyer)}
    defense_ids = {sd.ship.ship_id for sd in w.defense.units}
    strike_ids = {d.ship_id for d in w.strikes.destroyers}
    assert not (civilians & defense_ids)
    assert not (civilians & strike_ids)


# ---------------------------------------------------------------------------
# All-seeing picture
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_sandbox_board_is_all_seeing():
    w = SandboxWorld()
    assert w.contacts.visible_fn is None
    for _ in range(int(10.0 / DT)):
        w.step(DT)
    tracked = set(w.contacts.tracks.keys())
    live = {s.ship_id for s in w.ships if s.alive}
    assert live <= tracked          # every hull, horizon be damned


def test_sandbox_fog_latches_open():
    w = SandboxWorld()
    assert w.airfield_known is True
    site_ids = {s["id"] for s in w.known_enemy_sites}
    assert "airfield_enemy_00" in site_ids
    for struct, _r in w.enemy_radars:
        assert struct.structure_id in site_ids
    # Radar infrastructure is still the real combat build (ESM/ARM need it).
    assert w.radar_station is w.player_radars[0]
    assert w.radar_net is not None


# ---------------------------------------------------------------------------
# Passive vs weapons-free (the same geometry, the flag the only difference)
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_sandbox_passive_never_fires():
    w = SandboxWorld()
    dd = _closest_destroyer(w)
    sm2_before = sum(s.sm2_ammo for s in w.ships if isinstance(s, Destroyer))
    kalibr_before = sum(s.kalibr_ammo for s in w.subs)
    _force_inbound(w, dd)
    for _ in range(int(15.0 / DT)):
        w.step(DT)
    assert _hostile_rounds(w) == []
    assert sum(s.sm2_ammo for s in w.ships
               if isinstance(s, Destroyer)) == sm2_before
    assert sum(s.kalibr_ammo for s in w.subs) == kalibr_before
    assert w.strikes.progress == 0.0        # ESM accrual gated with the rest
    assert w._cmd_missions == []            # commander brain never ordered


@pytest.mark.slow
def test_sandbox_weapons_free_defends():
    w = SandboxWorld()
    w.enemy_weapons_free = True
    dd = _closest_destroyer(w)
    _force_inbound(w, dd)
    for _ in range(int(15.0 / DT)):
        w.step(DT)
        if any(isinstance(m, SamMissile) for m in _hostile_rounds(w)):
            break
    assert any(isinstance(m, SamMissile) for m in _hostile_rounds(w)), \
        "weapons-free fleet must draw an SM-2 at a tracked inbound"
    assert w.strikes.progress > 0.0         # ESM accrual running again


# ---------------------------------------------------------------------------
# No session end
# ---------------------------------------------------------------------------

def test_sandbox_no_end_latch():
    w = SandboxWorld()
    for s in w.structures:
        if s.kind == "bastion_tel":
            s.alive = False
    w.step(DT)
    # The base class WOULD have tripped on this state; the sandbox never does.
    assert CombatWorld.defeated.fget(w) is True
    assert w.defeated is False
    assert w.defeat_cause is None
    assert w.victorious is False
