"""SPECTATE mode (sandbox war 2026-07-06) — GL-free, plain pytest.

Contract:
  - MODES stays the LOCKED five (spectate lives OUTSIDE the C cycle);
    set_mode('spectate') is valid, C from spectate re-enters at 'chase';
  - SpectateSubject proxies pos/vel/alive onto any entity LIVE (ships
    expose velocity() not .vel; a parked fighter's alive is False via
    the raw _alive flag; positions track, never copy);
  - spectate mode frames the subject with the orbit controller (eye
    settles within the orbit zoom band of the subject);
  - SandboxWorld.spectate_roster: hostile rounds first, enemy hulls,
    subs, AIRBORNE enemy air only (no hangar queens), then civilians +
    patrols;
  - resolve_contact_entity: ship track ids, hostile-round ids (the
    strike board), and subsurface datum ids all resolve to live
    entities; a dead hull resolves to None.
"""

import numpy as np
import pytest

from engine.camera import Camera
from game.cameras import (MODES, ORBIT_DIST_MAX, SPECTATE_MODE,
                          TRANSITION_TIME, CameraRig, SpectateSubject)
from world.sandbox_world import SandboxWorld

DT = 1.0 / 60.0


def ocean(x, z):
    return -45.0


class _Mover:
    """Entity with velocity() (the ship convention), no .vel attr."""

    def __init__(self):
        self.pos = np.array([100.0, 0.0, 200.0])
        self.alive = True

    def velocity(self):
        return np.array([3.0, 0.0, 4.0])


# --------------------------------------------------------------- rig contract

def test_modes_locked_and_spectate_valid():
    assert MODES == ["chase", "orbit", "target", "launcher", "free"]
    rig = CameraRig(Camera(), terrain_height_fn=ocean)
    rig.set_mode(SPECTATE_MODE)
    assert rig.mode == SPECTATE_MODE
    assert rig.cycle_mode() == "chase"      # C re-enters the classic cycle


def test_spectate_frames_the_subject():
    rig = CameraRig(Camera(), terrain_height_fn=ocean)
    rig.set_mode(SPECTATE_MODE)
    subject = SpectateSubject(_Mover(), "MOVER")
    for _ in range(int((TRANSITION_TIME + 3.0) / DT)):
        rig.update(DT, missile=subject)
    d = float(np.linalg.norm(rig.camera.eye - subject.pos))
    assert d <= ORBIT_DIST_MAX + 1.0        # inside the orbit zoom band


# ------------------------------------------------------------ subject adapter

def test_subject_proxies_live_state():
    e = _Mover()
    s = SpectateSubject(e, "MOVER")
    assert np.allclose(s.vel, (3.0, 0.0, 4.0))     # velocity() fallback
    e.pos = np.array([500.0, 10.0, -50.0])
    assert np.allclose(s.pos, e.pos)               # tracks, never copies
    e.alive = False
    assert s.alive is False


def test_subject_prefers_raw_life_flag():
    class Parked:
        pos = np.zeros(3)
        _alive = True
        alive = False          # hangar semantics (parked fighter)
    assert SpectateSubject(Parked(), "F").alive is True


# ------------------------------------------------------------- world roster

def test_roster_orders_and_filters():
    from sim.enemy_air import FS_PARKED, Fighter
    w = SandboxWorld()
    roster = w.spectate_roster()
    kinds = [r["kind"] for r in roster]
    assert {"ship", "sub", "civilian", "patrol"} <= set(kinds)
    # No hangar queens: every parked fighter is excluded.
    parked = {id(f) for f in w._fighter_list if f.state == FS_PARKED}
    assert all(id(r["entity"]) not in parked for r in roster)
    # A director-ordered round jumps to the head of the cycle.
    dd = next(u["uid"] for u in w.director_units()
              if u["kind"] == "destroyer" and u["ready"])
    ok, _ = w.director_order(dd, (0.0, 0.0))
    assert ok
    roster = w.spectate_roster()
    assert roster[0]["kind"] == "missile"
    assert "TOMAHAWK" in roster[0]["label"]


def test_resolve_contact_entities():
    w = SandboxWorld()
    # Ship track id == ship_id.
    dd = next(s for s in w.ships if s.ship_id == "destroyer_00")
    ent, label = w.resolve_contact_entity("destroyer_00")
    assert ent is dd and "DESTROYER" in label
    # Hostile round: the strike board keys the contact by aircraft_id.
    ok, _ = w.director_order(dd.ship_id, (0.0, 0.0))
    assert ok
    w.step(1.0 / 120.0)                     # board picks the round up
    m = next(x for x in w.missiles if getattr(x, "is_hostile", False))
    ent, label = w.resolve_contact_entity(m.aircraft_id)
    assert ent is m and "TOMAHAWK" in label
    # Subsurface datum -> the boat itself.
    sub = w.subs[0]
    ok, _ = w.director_order(sub.sub_id, (0.0, 0.0))
    assert ok
    datum_id = f"{sub.sub_id}_datum"
    assert datum_id in w.sub_contacts
    ent, label = w.resolve_contact_entity(datum_id)
    assert ent is sub
    # A dead hull resolves to None.
    from sim.ships import ST_SINKING
    dd.state = ST_SINKING
    assert w.resolve_contact_entity("destroyer_00") is None
