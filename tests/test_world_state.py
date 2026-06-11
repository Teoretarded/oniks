"""WorldState wiring (Task 18): spawns, stepping, launch, events, realtime lock.

Task S4 adds the S-300 battery: launch_sam (contact-estimate aiming, tube
mouths, 8 s reload, 4-round ammo) and the SAM death events (sam_kill /
sam_self_destruct classified apart from splash / ground_hit).

GL-free: world.world imports only sim/world/models geometry modules.
"""

import numpy as np

from sim.aircraft import AC_ALIVE, AC_FALLING
from sim.arsenal import BASTION, ONIKS, S300, S300_TEL
from sim.missile import (PH_BOOST, PH_CRUISE, PH_EJECT, PH_PITCHOVER,
                         PH_RIDEOUT, PH_TERMINAL, Missile)
from sim.sam import SPH_EJECT, SPH_MIDCOURSE, SPH_TERMINAL, SamMissile
from sim.ships import ST_BURNING
from world import generation
from world.world import (CANISTER_MOUTH_OFFSET, SAM_MOUTH_OFFSETS,
                         SAM_TEL_POS, WorldState, launch_realtime_lock)

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
    assert len(ws.contacts.tracks) == len(ws.ships) + len(ws.aircraft)  # all tracked


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


# --- Task S4: S-300 battery wiring ---------------------------------------------

def test_launch_sam_spawns_at_tube_mouth_with_contact_aim():
    ws = WorldState()
    ws.step(DT)                                   # first board update: tracks
    m = ws.launch_sam("air_patrol_00")
    assert m is not None and m in ws.missiles
    assert np.allclose(m.pos, SAM_TEL_POS + SAM_MOUTH_OFFSETS[0])
    assert m.phase == SPH_EJECT
    assert m.phase_label == "EJECT"               # HUD duck-typed property
    assert not ws.sam_launcher_armed              # 8 s tube-to-tube reload
    assert ws.sam_ammo == S300_TEL.ammo - 1
    # The missile aims at the CONTACT estimate, not the aircraft truth:
    # nudge the track fix east and the estimate must follow the track.
    trk = ws.contacts.tracks["air_patrol_00"]
    trk["pos"] = trk["pos"] + np.array([500.0, 0.0, 0.0])
    est_pos, est_vel = m.contact_estimate_fn()
    board_est = ws.contacts.estimated_pos("air_patrol_00", ws.sim_time)
    assert np.allclose(est_pos, board_est)
    assert np.allclose(est_vel, trk["vel"])
    assert not np.allclose(est_pos, ws.aircraft[0].pos)      # stale != truth
    # Track drops mid-flight: the estimate falls back to the last fix.
    del ws.contacts.tracks["air_patrol_00"]
    fb_pos, fb_vel = m.contact_estimate_fn()
    assert np.allclose(fb_pos, est_pos) and np.allclose(fb_vel, est_vel)


def test_launch_sam_requires_a_live_air_track():
    ws = WorldState()
    assert ws.launch_sam("air_patrol_00") is None   # no tracks before step 1
    ws.step(DT)
    assert ws.launch_sam("cargo_00") is None        # surface track: refused
    assert ws.launch_sam("bogus_id") is None
    assert ws.sam_ammo == S300_TEL.ammo             # nothing was spent


def test_launch_sam_reload_and_ammo_gate():
    ws = WorldState()
    ws.step(DT)
    ids = ("air_patrol_00", "air_patrol_01", "air_patrol_02", "air_fast_03")
    for tube, cid in enumerate(ids):
        m = ws.launch_sam(cid)
        assert m is not None
        assert np.allclose(m.pos, SAM_TEL_POS + SAM_MOUTH_OFFSETS[tube])
        assert ws.launch_sam(cid) is None           # reloading: gated
        for _ in range(int(S300_TEL.reload_s / DT) + 2):
            ws.step(DT)
    assert ws.sam_ammo == 0
    assert not ws.sam_launcher_armed                # empty battery stays cold
    assert ws.launch_sam("air_patrol_00") is None


def test_sam_fuse_kill_emits_sam_kill_event_and_drops_aircraft():
    ws = WorldState()
    ws.step(DT)
    ac = ws.aircraft[0]
    start = ac.pos + np.array([1_500.0, 200.0, -1_500.0])
    m = SamMissile(S300, start, ac)
    m.phase = SPH_TERMINAL                          # straight to terminal PN
    aim = ac.pos + ac.velocity() * (2_200.0 / 800.0)
    d = aim - start
    m.vel = d / np.linalg.norm(d) * 800.0
    ws.missiles.append(m)
    killed = False
    for _ in range(600):
        ws.step(DT)
        if any(ev[0] == "sam_kill" for ev in ws.events):
            killed = True
            break
    assert killed
    pos = next(ev[1] for ev in ws.events if ev[0] == "sam_kill")
    assert pos[1] > 1_000.0                         # the kill is at altitude
    assert ac.state == AC_FALLING
    assert m not in ws.missiles                     # dead missiles pruned


def test_sam_self_destruct_emits_event_not_ground_hit():
    ws = WorldState()
    ws.step(DT)
    ac = ws.aircraft[2]                             # far patrol (z ~ 180+ km)
    m = SamMissile(S300, np.array([0.0, 15_000.0, 0.0]), ac)
    m.phase = SPH_MIDCOURSE
    m.vel = np.array([0.0, 0.0, 600.0])
    m.t = S300.self_destruct_t + 1.0                # flight clock expired
    ws.missiles.append(m)
    ws.step(DT)
    kinds = [ev[0] for ev in ws.events]
    assert "sam_self_destruct" in kinds
    assert "ground_hit" not in kinds                # not misread as a strike
    pos = next(ev[1] for ev in ws.events if ev[0] == "sam_self_destruct")
    assert pos[1] > 10_000.0
    assert ac.state == AC_ALIVE                     # honest miss


def test_oniks_phase_label_duck_typing():
    ws = WorldState()
    m = ws.launch("hi-lo", FAR_NORTH)
    assert m.phase_label == "IGNITION"          # Task LC hot-launch labels
    m.phase = PH_RIDEOUT
    assert m.phase_label == "RIDE-OUT"
    m.phase = PH_PITCHOVER
    assert m.phase_label == "PITCH-OVER"
    m.phase = PH_TERMINAL
    assert m.phase_label == "TERMINAL"


def test_launch_realtime_lock_follows_phase():
    ws = WorldState()
    assert not launch_realtime_lock(ws.missiles)          # nothing in flight
    m = ws.launch("hi-lo", FAR_NORTH)
    assert m.phase == PH_EJECT
    assert launch_realtime_lock(ws.missiles)
    for ph in (PH_RIDEOUT, PH_PITCHOVER, PH_BOOST):       # whole cinematic
        m.phase = ph
        assert launch_realtime_lock(ws.missiles)
    m.phase = PH_CRUISE
    assert not launch_realtime_lock(ws.missiles)          # auto-restore point
    m.phase = PH_BOOST
    m.alive = False
    assert not launch_realtime_lock(ws.missiles)          # dead missiles ignored
