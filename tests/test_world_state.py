"""WorldState wiring (Task 18): spawns, stepping, launch, events, realtime lock.

GL-free: world.world imports only sim/world/models geometry modules.
"""

import numpy as np

from sim.arsenal import BASTION, ONIKS
from sim.missile import PH_BOOST, PH_CRUISE, PH_EJECT, PH_TERMINAL, Missile
from sim.ships import ST_BURNING
from world import generation
from world.world import CANISTER_MOUTH_OFFSET, WorldState, launch_realtime_lock

DT = 1.0 / 120.0
FAR_NORTH = np.array([0.0, 0.0, 100_000.0])


def test_init_spawns_ships_sites_contacts():
    ws = WorldState()
    assert len(ws.ships) == len(generation.SHIP_SPAWNS)
    ids = [s.ship_id for s in ws.ships]
    assert len(set(ids)) == len(ids)                      # unique ids
    for ship, spawn in zip(ws.ships, generation.SHIP_SPAWNS):
        assert ship.ship_type == spawn["ship_type"]
        assert ship.speed == spawn["speed"]               # spawn speed override
    assert ws.sites is generation.SITES
    assert ws.missiles == []
    assert ws.sim_time == 0.0
    assert ws.launcher_armed                              # ready at start


def test_terrain_height_at_matches_generation():
    ws = WorldState()
    for x, z in ((0.0, -5_000.0), (40_000.0, 200_000.0), (52_000.0, 140_000.0)):
        expect = float(generation.terrain_height(np.array([x]), np.array([z]))[0])
        assert ws.terrain_height_at(x, z) == expect


def test_step_advances_ships_time_and_contacts():
    ws = WorldState()
    p0 = ws.ships[0].pos.copy()
    for _ in range(120):
        ws.step(DT)
    assert abs(ws.sim_time - 1.0) < 1e-9
    assert np.linalg.norm(ws.ships[0].pos - p0) > 1.0     # ship sailed
    assert len(ws.contacts.tracks) == len(ws.ships)       # all tracked


def test_launch_spawns_missile_at_canister_mouth():
    ws = WorldState()
    target = np.array([10_000.0, 0.0, 100_000.0])
    m = ws.launch("hi-lo", target)
    assert m is not None and m in ws.missiles
    base = np.array(generation.BASE_POS)
    assert np.allclose(m.pos, base + CANISTER_MOUTH_OFFSET)
    # mouth of the raised canister: ~10 m above the TEL's ground plane
    assert 9.0 < CANISTER_MOUTH_OFFSET[1] < 10.5
    assert m.phase == PH_EJECT
    # bearing to the target from the actual spawn point (canister mouth)
    expected_heading = float(np.arctan2(target[0] - m.pos[0],
                                        target[2] - m.pos[2]))
    assert abs(m.heading - expected_heading) < 1e-9


def test_launcher_reload_gates_and_rearms():
    ws = WorldState()
    assert ws.launch("hi-lo", FAR_NORTH) is not None
    assert not ws.launcher_armed
    assert ws.launch("hi-lo", FAR_NORTH) is None          # still reloading
    assert len(ws.missiles) == 1
    for _ in range(int(BASTION.reload_s / DT) + 2):
        ws.step(DT)
    assert ws.launcher_armed
    assert ws.launch("lo-lo", FAR_NORTH) is not None


def _falling_missile(pos):
    """A stalled missile dropping straight down (no thrust authority)."""
    m = Missile(ONIKS, pos, 0.0, "lo-lo",
                target_point=np.array([pos[0], 0.0, pos[2] + 10_000.0]))
    m.phase = PH_TERMINAL
    m.fuel = 0.0
    m.vel = np.array([0.0, -50.0, 0.0])
    return m


def test_water_impact_emits_splash_and_prunes_missile():
    ws = WorldState()
    m = _falling_missile(np.array([0.0, 30.0, 50_000.0]))  # open ocean
    ws.missiles.append(m)
    for _ in range(300):
        ws.step(DT)
        if not m.alive:
            break
    kinds = [ev[0] for ev in ws.events]
    assert "splash" in kinds
    pos = next(ev[1] for ev in ws.events if ev[0] == "splash")
    assert pos[1] == 0.0                                  # at the water surface
    assert m not in ws.missiles                           # dead missiles pruned


def test_ground_impact_emits_ground_hit():
    ws = WorldState()
    h = ws.terrain_height_at(0.0, -5_000.0)
    assert h > 0.0                                        # home continent land
    m = _falling_missile(np.array([0.0, h + 30.0, -5_000.0]))
    ws.missiles.append(m)
    for _ in range(300):
        ws.step(DT)
        if not m.alive:
            break
    kinds = [ev[0] for ev in ws.events]
    assert "ground_hit" in kinds
    pos = next(ev[1] for ev in ws.events if ev[0] == "ground_hit")
    assert pos[1] > 0.0                                   # on terrain


def test_ship_hit_emits_event_and_burns_ship():
    ws = WorldState()
    ship = ws.ships[0]
    aim = ship.pos + np.array([0.0, 4.0, 0.0])            # mid-hull
    start = ship.pos + np.array([0.0, 8.0, -500.0])
    m = Missile(ONIKS, start, 0.0, "lo-lo",
                target_point=np.array([ship.pos[0], 0.0, ship.pos[2]]))
    m.phase = PH_TERMINAL
    d = aim - start
    m.vel = d / np.linalg.norm(d) * 300.0
    ws.missiles.append(m)
    hit = False
    for _ in range(600):
        ws.step(DT)
        if any(ev[0] == "ship_hit" for ev in ws.events):
            hit = True
            break
    assert hit
    assert ship.state == ST_BURNING                       # cargo hp 2 -> burning
    assert m not in ws.missiles


def test_launch_realtime_lock_follows_phase():
    ws = WorldState()
    assert not launch_realtime_lock(ws.missiles)          # nothing in flight
    m = ws.launch("hi-lo", FAR_NORTH)
    assert m.phase == PH_EJECT
    assert launch_realtime_lock(ws.missiles)
    m.phase = PH_BOOST
    assert launch_realtime_lock(ws.missiles)
    m.phase = PH_CRUISE
    assert not launch_realtime_lock(ws.missiles)          # auto-restore point
    m.phase = PH_BOOST
    m.alive = False
    assert not launch_realtime_lock(ws.missiles)          # dead missiles ignored
