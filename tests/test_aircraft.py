"""Aircraft racetrack patrol / falling-spiral tests + world wiring + spawn layout.

Task S1 (S-300 expansion): patrol aircraft mirroring the Ship API shape,
AIRCRAFT_SPAWNS / SAM_SITE_POS world constants, and WorldState aircraft
stepping with ("aircraft_down", pos) / ("aircraft_splash", pos) events.
GL-free per the locked test convention.
"""

import math

import numpy as np
import pytest

from sim.aircraft import (AC_ALIVE, AC_FALLING, AC_GONE, AIRCRAFT_TYPES,
                          FALL_BANK, FALL_PITCH, FALL_SPEED_FRAC, TURN_RATE,
                          Aircraft)
from world import generation
from world.world import WorldState

DT = 1.0 / 120.0


def _patrol(anchor_a=(0.0, 0.0), anchor_b=(16_000.0, 60_000.0),
            aircraft_id="air_t", aircraft_type="patrol"):
    return Aircraft(aircraft_id, aircraft_type, anchor_a, anchor_b)


# --- type table + spawn state ---------------------------------------------------

def test_locked_type_numbers():
    assert AIRCRAFT_TYPES["patrol"] == dict(length=30.0, wingspan=35.0,
                                            speed=170.0, alt=6500.0, hp=1)
    assert AIRCRAFT_TYPES["fast"] == dict(length=20.0, wingspan=14.0,
                                          speed=240.0, alt=4000.0, hp=1)
    assert TURN_RATE == pytest.approx(math.radians(1.5))


def test_spawn_state_mirrors_ship_api():
    ac = _patrol()
    assert ac.pos.dtype == np.float64
    assert ac.pos[1] == AIRCRAFT_TYPES["patrol"]["alt"]   # y = altitude
    assert ac.state == AC_ALIVE and ac.alive
    assert ac.is_air
    assert ac.hp == 1
    assert ac.aircraft_id == "air_t"
    v = ac.velocity()
    assert v.shape == (3,) and v[1] == 0.0                # level flight
    assert np.array_equal(ac.vel, v)                      # duck-typed alias


# --- racetrack -------------------------------------------------------------------

def test_racetrack_stays_within_anchor_bbox_plus_5km():
    ac = _patrol()
    dt = 0.5
    lo = np.array([0.0, 0.0]) - 5_000.0
    hi = np.array([16_000.0, 60_000.0]) + 5_000.0
    mid_crossings = 0
    prev_north = ac.pos[2] > 30_000.0
    for _ in range(int(1_800.0 / dt)):                    # > 2 full laps
        ac.update(dt)
        assert lo[0] <= ac.pos[0] <= hi[0], f"x strayed to {ac.pos[0]:.0f}"
        assert lo[1] <= ac.pos[2] <= hi[1], f"z strayed to {ac.pos[2]:.0f}"
        north = ac.pos[2] > 30_000.0
        if north != prev_north:
            mid_crossings += 1
            prev_north = north
    assert mid_crossings >= 3                             # it actually laps


def test_speed_correct_per_type():
    for ac_type, spec in AIRCRAFT_TYPES.items():
        ac = _patrol(anchor_b=(20_000.0, 60_000.0), aircraft_type=ac_type)
        assert float(np.linalg.norm(ac.velocity())) == pytest.approx(spec["speed"])
        p0 = ac.pos.copy()
        for _ in range(120):                              # 60 s on the first leg
            ac.update(0.5)
        moved = float(np.linalg.norm(ac.pos - p0))
        assert moved == pytest.approx(spec["speed"] * 60.0, rel=0.01)
        assert ac.pos[1] == spec["alt"]                   # altitude held


def test_turn_rate_limited_to_1p5_deg_per_s():
    ac = _patrol()
    dt = 0.5
    max_step = 0.0
    prev_h = ac.heading
    for _ in range(int(700.0 / dt)):                      # includes corner turns
        ac.update(dt)
        dh = abs((ac.heading - prev_h + np.pi) % (2.0 * np.pi) - np.pi)
        max_step = max(max_step, dh)
        prev_h = ac.heading
    assert max_step <= math.radians(1.5) * dt * 1.0001
    assert max_step > 0.0                                 # it did actually turn


def test_determinism_two_instances_identical():
    a = _patrol()
    b = _patrol()
    for _ in range(2_000):                                # 1000 s incl. corners
        a.update(0.5)
        b.update(0.5)
    assert np.array_equal(a.pos, b.pos)
    assert a.heading == b.heading
    a.kill()
    b.kill()
    for _ in range(500):                                  # falling is bit-equal too
        a.update(1.0 / 30.0)
        b.update(1.0 / 30.0)
    assert np.array_equal(a.pos, b.pos)
    assert a.state == b.state


# --- falling spiral ---------------------------------------------------------------

def test_kill_starts_falling_and_untracks():
    ac = _patrol()
    ac.kill()
    assert ac.state == AC_FALLING
    assert not ac.alive
    ac.kill()                                             # idempotent on the dead
    assert ac.state == AC_FALLING


def test_falling_spiral_attitude_speed_and_descent():
    ac = _patrol(anchor_a=(0.0, 140_000.0), anchor_b=(16_000.0, 200_000.0))
    ac.kill()
    dt = 1.0 / 30.0
    turned = 0.0
    prev_h = ac.heading
    for _ in range(int(10.0 / dt)):                       # 10 s into the spiral
        ac.update(dt)
        turned += abs((ac.heading - prev_h + np.pi) % (2.0 * np.pi) - np.pi)
        prev_h = ac.heading
    assert ac.roll == pytest.approx(FALL_BANK)            # 25 deg bank
    assert ac.pitch == pytest.approx(-FALL_PITCH)         # 12 deg nose down
    v = ac.velocity()
    speed = float(np.linalg.norm(v))
    assert speed == pytest.approx(FALL_SPEED_FRAC * 170.0, rel=1e-6)
    assert v[1] == pytest.approx(-speed * math.sin(FALL_PITCH), rel=1e-6)
    assert ac.pos[1] < 6_500.0 - 100.0                    # descending for real
    assert turned > math.radians(15.0)                    # it spirals, not a line


def test_falling_reaches_gone_on_water_impact():
    ac = _patrol(anchor_a=(0.0, 140_000.0), anchor_b=(16_000.0, 200_000.0))
    ac.pos[1] = 600.0                                     # shorten the fall
    ac.kill()
    dt = 1.0 / 30.0
    for _ in range(int(90.0 / dt)):
        ac.update(dt)
        if ac.state == AC_GONE:
            break
    assert ac.state == AC_GONE
    assert ac.impact_pos is not None
    assert ac.impact_pos[1] == 0.0                        # splashed at sea level
    assert np.array_equal(ac.velocity(), np.zeros(3))
    p = ac.pos.copy()
    ac.update(dt)                                         # GONE aircraft never move
    assert np.array_equal(ac.pos, p)


def test_falling_over_land_impacts_on_terrain():
    ac = _patrol()
    ac.pos = np.array([0.0, 200.0, -5_000.0])             # home continent land
    ac.kill()
    dt = 1.0 / 30.0
    for _ in range(int(90.0 / dt)):
        ac.update(dt)
        if ac.state == AC_GONE:
            break
    assert ac.state == AC_GONE
    assert ac.impact_pos[1] > 5.0                         # on the terrain, not sea


# --- world constants (generation) --------------------------------------------------

def test_sam_site_pos_on_land():
    x, y, z = generation.SAM_SITE_POS
    assert x == 85_000.0 and z == -3_500.0                # frozen nominal site
    h = float(generation.terrain_height(np.array([x]), np.array([z]))[0])
    assert h > 5.0                                        # dry land, per plan
    assert y == h


def test_aircraft_spawns_locked_layout():
    spawns = generation.AIRCRAFT_SPAWNS
    assert len(spawns) == 4
    ids = [s["aircraft_id"] for s in spawns]
    assert len(set(ids)) == 4
    assert all(i.startswith("air_") for i in ids)
    sx, _, sz = generation.SAM_SITE_POS
    in_env, out_env = [], []
    for s in spawns:
        spec = AIRCRAFT_TYPES[s["aircraft_type"]]
        ax, az = s["anchor_a"]
        bx, bz = s["anchor_b"]
        leg = max(abs(bx - ax), abs(bz - az))
        width = min(abs(bx - ax), abs(bz - az))
        assert 60_000.0 <= leg <= 100_000.0               # racetrack legs 60-100 km
        # a 180-degree turn at the type speed and 1.5 deg/s must fit inside
        assert width >= 2.0 * spec["speed"] / TURN_RATE
        corners = [(x, z) for x in (min(ax, bx), max(ax, bx))
                   for z in (min(az, bz), max(az, bz))]
        slant = [math.hypot(math.hypot(x - sx, z - sz), spec["alt"])
                 for x, z in corners]
        if max(slant) < 150_000.0:
            in_env.append(s)
        elif min(math.hypot(x - sx, z - sz) for x, z in corners) > 150_000.0:
            out_env.append(s)
    # two patrols engageable by the S300, one patrol + one fast beyond reach
    assert len(in_env) == 2
    assert all(s["aircraft_type"] == "patrol" for s in in_env)
    assert len(out_env) == 2
    assert {s["aircraft_type"] for s in out_env} == {"patrol", "fast"}


# --- WorldState wiring ---------------------------------------------------------------

def test_world_spawns_aircraft_from_generation():
    ws = WorldState()
    assert len(ws.aircraft) == len(generation.AIRCRAFT_SPAWNS)
    ids = [a.aircraft_id for a in ws.aircraft]
    assert len(set(ids)) == len(ids)
    for ac, spawn in zip(ws.aircraft, generation.AIRCRAFT_SPAWNS):
        assert ac.aircraft_id == spawn["aircraft_id"]
        assert ac.aircraft_type == spawn["aircraft_type"]
        assert ac.state == AC_ALIVE


def test_world_step_advances_aircraft_and_air_tracks():
    ws = WorldState()
    p0 = ws.aircraft[0].pos.copy()
    for _ in range(120):
        ws.step(DT)
    assert np.linalg.norm(ws.aircraft[0].pos - p0) > 100.0   # it flew
    for ac in ws.aircraft:
        track = ws.contacts.tracks[ac.aircraft_id]
        assert track["is_air"] is True
        assert track["pos"][1] == AIRCRAFT_TYPES[ac.aircraft_type]["alt"]
    ship_track = ws.contacts.tracks[ws.ships[0].ship_id]
    assert ship_track["is_air"] is False


def test_world_emits_aircraft_splash_on_water_impact():
    ws = WorldState()
    ac = ws.aircraft[0]                                   # spawns over open ocean
    ac.pos[1] = 80.0                                      # just above the sea
    ac.kill()
    for _ in range(3_000):
        ws.step(DT)
        if ac.state == AC_GONE:
            break
    assert ac.state == AC_GONE
    kinds = [ev[0] for ev in ws.events]
    assert "aircraft_splash" in kinds
    assert "aircraft_down" not in kinds
    pos = next(ev[1] for ev in ws.events if ev[0] == "aircraft_splash")
    assert pos[1] == 0.0                                  # at the water surface
    assert ac in ws.aircraft                              # wrecks stay listed


def test_world_emits_aircraft_down_on_terrain_impact():
    ws = WorldState()
    ac = ws.aircraft[1]
    ac.pos = np.array([0.0, 150.0, -5_000.0])             # over home land
    ac.kill()
    for _ in range(3_000):
        ws.step(DT)
        if ac.state == AC_GONE:
            break
    assert ac.state == AC_GONE
    kinds = [ev[0] for ev in ws.events]
    assert "aircraft_down" in kinds
    pos = next(ev[1] for ev in ws.events if ev[0] == "aircraft_down")
    assert pos[1] > 0.0                                   # on terrain
