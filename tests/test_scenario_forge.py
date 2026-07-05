"""SCENARIO FORGE contracts (AI-testability build, 2026-07-05).

The forge lets a test (or an AI agent) spawn a precise tactical situation
in seconds instead of simulating minutes of enemy AI:

  * spawn_inbound routes through the REAL enemy strike round (the same
    StrikeDef + integration flags EnemyStrikeController fires) — never a
    parallel test-only missile.
  * run_until steps the real world.step loop to a condition with a hard
    timeout, draining events exactly like the live game loop.
  * set_battery adjusts only attributes the world already owns.

Determinism: same args -> byte-identical spawns (no RNG anywhere here).
"""

import math

import numpy as np

from world.combat import CombatWorld
from world.combat_config import CombatConfig
from world.scenario import (
    first_hostile_air_track, run_until, set_battery, spawn_inbound,
)

DT = 1.0 / 120.0


def _world(seed=1337):
    return CombatWorld(CombatConfig(seed=seed))


def test_spawn_inbound_places_real_hostile_rounds():
    w = _world()
    rounds = spawn_inbound(w, kind="tomahawk", bearing_deg=40.0,
                           range_km=80.0, n=3)
    assert len(rounds) == 3
    for m in rounds:
        assert m in w.missiles
        assert getattr(m, "is_hostile", False) is True
        assert m.launch_cinematic is False     # enemy rounds never 1x-lock
    # Placement: bearing/range polar offset from the aimed structure (the
    # player radar station by default), spaced along the bearing.
    station = w.radar_station.pos
    m0 = rounds[0]
    dx = float(m0.pos[0] - station[0])
    dz = float(m0.pos[2] - station[2])
    rng = math.hypot(dx, dz)
    brg = math.degrees(math.atan2(dx, dz)) % 360.0
    assert abs(rng - 80_000.0) < 1.0
    assert abs(brg - 40.0) < 0.01


def test_spawn_inbound_aims_at_the_radar_station():
    w = _world()
    (m,) = spawn_inbound(w, kind="tomahawk", bearing_deg=180.0, range_km=60.0)
    # The aim point is the station's surveyed coordinates — the same aim
    # EnemyStrikeController fires at (belly of the tower, not ground zero).
    assert abs(m.target_x - float(w.radar_station.pos[0])) < 1.0
    assert abs(m.target_z - float(w.radar_station.pos[2])) < 1.0
    assert abs(m.target_y - (float(w.radar_station.pos[1]) + 11.0)) < 0.5


def test_spawn_inbound_is_deterministic():
    a = _world(seed=3)
    b = _world(seed=3)
    ra = spawn_inbound(a, kind="jassm", bearing_deg=95.0, range_km=50.0, n=2)
    rb = spawn_inbound(b, kind="jassm", bearing_deg=95.0, range_km=50.0, n=2)
    for ma, mb in zip(ra, rb):
        assert np.array_equal(ma.pos, mb.pos)
        assert np.array_equal(ma.vel, mb.vel)


def test_spawned_inbound_closes_on_the_base():
    """The spawned round is a live flyer, not a prop: after 30 s of real
    stepping (VLS eject + climb-out + cruise) it has closed distance on
    the station.  Measured 2026-07-05: ~2.7 km closed at 20 s, cruise
    ~240 m/s thereafter -> >4 km by 30 s with margin."""
    w = _world()
    (m,) = spawn_inbound(w, kind="tomahawk", bearing_deg=10.0, range_km=40.0)
    station = w.radar_station.pos

    def dist():
        return math.hypot(float(m.pos[0] - station[0]),
                          float(m.pos[2] - station[2]))

    d0 = dist()
    run_until(w, lambda world: False, timeout_s=30.0, dt=DT)
    assert m.alive
    assert dist() < d0 - 4_000.0               # meaningfully inbound


def test_run_until_stops_on_condition_and_returns_true():
    """A 15 km sea-skimmer IS eventually detected (measured 2026-07-05: a
    45 km spawn tracks only at ~4.8 km from the station after 174 s — the
    skimmer rides under the radar horizon, the go-low mechanic working);
    from 15 km the horizon crossing lands well inside the 90 s budget."""
    w = _world()
    spawn_inbound(w, kind="tomahawk", bearing_deg=0.0, range_km=15.0)
    hit = run_until(w, first_hostile_air_track, timeout_s=90.0, dt=DT)
    assert hit is True
    assert first_hostile_air_track(w)


def test_run_until_times_out_and_returns_false():
    w = _world()
    t0 = w.sim_time
    hit = run_until(w, lambda world: False, timeout_s=2.0, dt=DT)
    assert hit is False
    assert abs((w.sim_time - t0) - 2.0) < 2 * DT


def test_set_battery_adjusts_only_owned_pools():
    w = _world()
    set_battery(w, oniks_ammo=2, sam_ammo=1, radar_emitting=False)
    assert w._oniks_ammo == 2
    assert w.sam_ammo == 1
    assert w.radar_station.emitting is False
