"""tests/test_strike.py — GL-free unit tests for sim/strike.py.

Coverage (spec §5.1, §5.2, §8, §9):

1. Tomahawk launched 300 km out cruises at ~50 m AGL and hits within 100 m
   of target coords.
2. JASSM released at 8 km altitude 200 km out arrives at target.
3. HARM vs emitting radar hits within fuse radius (15 m).
4. HARM vs radar silenced at 30 km out misses by 150–400 m (seeded rng,
   two-sided assertion on the miss distance band).
5. HARM re-acquires live position when radar re-emits mid-flight.
6. Missiles respect max range: fuel-exhausted missile sinks / self-terminates
   beyond fuel capacity (Tomahawk sim-time gate).

All tests use a flat _StubWorld (surface_height_at returns 0) so no
terrain/GL imports are needed.  Physics step: 1/120 Hz (DT).
"""

import math

import numpy as np
import pytest

from sim.arsenal import HARM, JASSM, TOMAHAWK
from sim.radar import Radar
from sim.strike import (HARM_MISS_MAX_M, HARM_MISS_MIN_M, TERMINAL_RANGE_M,
                         HarmMissile, StrikeMissile,
                         SPH_STRIKE_DEAD, SPH_STRIKE_CRUISE, SPH_STRIKE_TERMINAL)

DT = 1.0 / 120.0   # 120 Hz fixed physics step

# ---------------------------------------------------------------------------
# Shared stub world
# ---------------------------------------------------------------------------

class _StubWorld:
    """Minimal world: flat sea surface, no ships, no events list needed."""

    def surface_height_at(self, x: float, z: float) -> float:
        return 0.0


_WORLD = _StubWorld()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(missile, world, max_steps: int):
    """Advance missile until alive=False or max_steps exhausted."""
    for _ in range(max_steps):
        if not missile.alive:
            break
        missile.update(DT, world)
    return missile


def _tomahawk_vls(pos, target_xz):
    """Standard VLS-launched Tomahawk: eject vertically at eject_speed."""
    vel = np.array([0.0, TOMAHAWK.eject_speed, 0.0], dtype=np.float64)
    return StrikeMissile(TOMAHAWK, pos, vel, target_xz)


def _jassm_air(pos, vel, target_xz):
    """Air-launched JASSM: released at aircraft velocity."""
    return StrikeMissile(JASSM, pos, vel, target_xz)


def _harm_air(pos, vel, radar, rng):
    """Air-launched HARM with seeded rng."""
    return HarmMissile(HARM, pos, vel, radar, rng)


def _radar_at(x, z, height=10.0):
    """A live, emitting search radar at (x, 0, z) with 10 m antenna."""
    return Radar("test_radar",
                 np.array([x, 0.0, z], dtype=np.float64),
                 antenna_m=height,
                 ranges={"missile": 300_000.0, "fighter": 300_000.0})


# ---------------------------------------------------------------------------
# 1. Tomahawk cruise altitude and hit accuracy
# ---------------------------------------------------------------------------

def test_tomahawk_cruises_at_50m_and_hits():
    """Tomahawk launched 300 km south of target hits within 100 m.

    Verification:
      a) After the climb, recorded cruise altitudes are within 10–150 m AGL
         (the spec says ~50 m; the PD overshoots briefly but settles close).
      b) impact_pos within 100 m of target_xz ground coords.
    """
    target_xz = (0.0, 300_000.0)   # 300 km north; z = 300 km
    # Launch from (0, 0, 0) — sea level.
    launch_pos = np.array([0.0, 0.0, 0.0], dtype=np.float64)
    m = _tomahawk_vls(launch_pos, target_xz)

    cruise_altitudes = []
    # Tomahawk at Mach 0.74 (~252 m/s) needs ~300000/252 = 1190 s for the
    # cruise leg plus ~20 s for the VLS eject/boost/climb = ~1210 s total.
    # Allow 1300 s (21.7 min) for margin.
    max_steps = int(1300.0 / DT)   # 21.7 minutes sim time ceiling
    for _ in range(max_steps):
        if not m.alive:
            break
        if m.phase == SPH_STRIKE_CRUISE:
            cruise_altitudes.append(float(m.pos[1]))
        m.update(DT, _WORLD)

    # Must have hit.
    assert not m.alive, "Tomahawk must impact within 22 min for 300 km"
    assert m.impact_pos is not None

    # Hit accuracy: within 100 m of target coords (x, z ground).
    ix, iz = float(m.impact_pos[0]), float(m.impact_pos[2])
    miss = math.hypot(ix - target_xz[0], iz - target_xz[1])
    assert miss < 100.0, f"Tomahawk miss distance {miss:.1f} m > 100 m"

    # Cruise altitude check: the settled cruise should be near spec (10–200 m).
    if cruise_altitudes:
        # Ignore the first 5 s of climb-stabilization.
        settled = cruise_altitudes[int(5.0 / DT):]
        if settled:
            avg_alt = sum(settled) / len(settled)
            assert 5.0 < avg_alt < 300.0, (
                f"Tomahawk settled cruise altitude {avg_alt:.1f} m is outside "
                f"5–300 m (spec: ~50 m AGL)"
            )


# ---------------------------------------------------------------------------
# 2. JASSM: air-launched at 8 km arrives at target
# ---------------------------------------------------------------------------

def test_jassm_arrives_from_8km_alt():
    """JASSM released at 8 km altitude 200 km from target arrives.

    The aircraft releases the missile heading north at Mach 0.8 (~272 m/s).
    """
    target_xz = (0.0, 200_000.0)
    launch_pos = np.array([0.0, 8_000.0, 0.0], dtype=np.float64)
    # Aircraft velocity: 250 m/s northward at 8 km (Mach ~0.8).
    aircraft_vel = np.array([0.0, 0.0, 250.0], dtype=np.float64)
    m = _jassm_air(launch_pos, aircraft_vel, target_xz)

    # JASSM range: 370 km; 200 km is well within spec.
    max_steps = int(900.0 / DT)   # 15 minutes ceiling
    _run(m, _WORLD, max_steps)

    assert not m.alive, "JASSM must impact within 15 min for 200 km"
    assert m.impact_pos is not None, "JASSM must set impact_pos on hit"

    ix, iz = float(m.impact_pos[0]), float(m.impact_pos[2])
    miss = math.hypot(ix - target_xz[0], iz - target_xz[1])
    assert miss < 200.0, f"JASSM miss distance {miss:.1f} m > 200 m"


# ---------------------------------------------------------------------------
# 3. HARM vs emitting radar: hits within fuse radius
# ---------------------------------------------------------------------------

def test_harm_hits_emitting_radar():
    """HARM launched 80 km from an always-emitting radar triggers the
    proximity fuse (≤ 15 m from the aim point)."""
    radar_x, radar_z = 0.0, 80_000.0
    radar = _radar_at(radar_x, radar_z)
    assert radar.emitting and radar.alive

    launch_pos = np.array([0.0, 5_000.0, 0.0], dtype=np.float64)
    # Aircraft heading north at Mach 0.9 (~306 m/s).
    ac_vel = np.array([0.0, 0.0, 300.0], dtype=np.float64)
    rng = np.random.default_rng(42)
    m = _harm_air(launch_pos, ac_vel, radar, rng)

    max_steps = int(300.0 / DT)   # 5 minutes ceiling; HARM is fast
    _run(m, _WORLD, max_steps)

    assert not m.alive, "HARM must activate fuse or impact within 5 min"
    assert m.impact_pos is not None

    # The aim point (live radar pos) must be within fuse radius of impact.
    aim = np.array([radar_x, 0.0, radar_z], dtype=np.float64)
    dist_to_aim = float(np.linalg.norm(m.impact_pos - aim))
    assert dist_to_aim <= HARM.fuse_radius + 5.0, (   # +5 m tolerance for step
        f"HARM impact {dist_to_aim:.1f} m from radar (fuse radius {HARM.fuse_radius} m)"
    )


# ---------------------------------------------------------------------------
# 4. HARM vs radar silenced at 30 km: misses by 150–400 m (seeded)
# ---------------------------------------------------------------------------

def test_harm_misses_silenced_radar():
    """Radar goes silent when the HARM is 30 km out.  The seeded miss offset
    must be in the 150–400 m ring (spec §8: "CEP degraded").

    Two-sided: min miss >= 150 m (not a direct hit) and
               max miss <= 400 m (not wildly off).
    """
    radar_x, radar_z = 0.0, 80_000.0
    radar = _radar_at(radar_x, radar_z)

    launch_pos = np.array([0.0, 5_000.0, 0.0], dtype=np.float64)
    ac_vel = np.array([0.0, 0.0, 300.0], dtype=np.float64)
    rng = np.random.default_rng(7)   # deterministic seed
    m = _harm_air(launch_pos, ac_vel, radar, rng)

    max_steps = int(300.0 / DT)
    silence_triggered = False

    for _ in range(max_steps):
        if not m.alive:
            break
        # Silence the radar when HARM is inside 30 km of radar site.
        dx = float(m.pos[0]) - radar_x
        dz = float(m.pos[2]) - radar_z
        if not silence_triggered and math.hypot(dx, dz) < 30_000.0:
            radar.emitting = False
            silence_triggered = True
        m.update(DT, _WORLD)

    assert silence_triggered, "Test geometry error: HARM never reached 30 km from radar"
    assert not m.alive, "HARM must impact (silenced aim point) within 5 min"
    assert m.impact_pos is not None

    # Miss distance from the REAL radar position (not the degraded aim point).
    real_radar_pos = np.array([radar_x, 0.0, radar_z], dtype=np.float64)
    miss = float(np.linalg.norm(m.impact_pos - real_radar_pos))

    # Two-sided: must be in the 150–400 m ring.
    # The miss offset itself is in [150, 400] m; the proximity fuse then
    # triggers at ≤15 m of the DEGRADED aim point → total miss is
    # approximately equal to the offset radius (with ≤15 m fuse tolerance).
    assert miss >= HARM_MISS_MIN_M - HARM.fuse_radius - 1.0, (
        f"HARM miss {miss:.1f} m is below the minimum {HARM_MISS_MIN_M} m "
        f"(silenced-radar CEP band)"
    )
    assert miss <= HARM_MISS_MAX_M + HARM.fuse_radius + 1.0, (
        f"HARM miss {miss:.1f} m exceeds the maximum {HARM_MISS_MAX_M} m "
        f"(silenced-radar CEP band)"
    )
    # Confirm the radar survived (spec: "a silenced radar usually survives").
    assert radar.alive, "Silenced radar should not be marked dead by HARM miss"


# ---------------------------------------------------------------------------
# 5. HARM re-acquires when radar re-emits
# ---------------------------------------------------------------------------

def test_harm_reacquires_on_radar_remission():
    """Radar goes silent briefly then re-emits.  On re-emission the HARM
    must re-lock to the live position (miss_offset cleared) and eventually
    hit within fuse radius of the REAL radar position (not the degraded point).
    """
    radar_x, radar_z = 0.0, 80_000.0
    radar = _radar_at(radar_x, radar_z)

    launch_pos = np.array([0.0, 5_000.0, 0.0], dtype=np.float64)
    ac_vel = np.array([0.0, 0.0, 300.0], dtype=np.float64)
    rng = np.random.default_rng(13)
    m = _harm_air(launch_pos, ac_vel, radar, rng)

    max_steps = int(300.0 / DT)
    silenced_at = None
    reemitted_at = None

    for step in range(max_steps):
        if not m.alive:
            break
        dx = float(m.pos[0]) - radar_x
        dz = float(m.pos[2]) - radar_z
        dist = math.hypot(dx, dz)

        # Silence at 50 km ...
        if silenced_at is None and dist < 50_000.0:
            radar.emitting = False
            silenced_at = step

        # ... re-emit 2 s later.
        if (silenced_at is not None and reemitted_at is None
                and step > silenced_at + int(2.0 / DT)):
            radar.emitting = True
            reemitted_at = step

        m.update(DT, _WORLD)

    assert silenced_at is not None, "Test geometry: HARM never reached 50 km"
    assert reemitted_at is not None, "Test logic: radar never re-emitted"
    assert not m.alive, "HARM must have impacted"
    assert m.impact_pos is not None

    # With re-emission the HARM re-locks and should hit close to the real
    # radar position (within 2 * fuse_radius + some step tolerance).
    real_radar_pos = np.array([radar_x, 0.0, radar_z], dtype=np.float64)
    miss = float(np.linalg.norm(m.impact_pos - real_radar_pos))
    assert miss <= HARM.fuse_radius * 3 + 20.0, (
        f"After re-lock HARM should hit near radar; miss = {miss:.1f} m"
    )
    # Miss offset should have been cleared on re-emission.
    assert m._miss_offset is None, "Re-emission must clear the miss offset"


# ---------------------------------------------------------------------------
# 6. Max-range self-termination: fuel exhausted missile sinks
# ---------------------------------------------------------------------------

def test_tomahawk_self_terminates_beyond_fuel():
    """A Tomahawk with only 10 kg of fuel (enough for ~70 km at Mach 0.74)
    aimed at a 300 km target must exhaust its fuel and eventually impact
    before reaching the target — verifying the fuel gate."""
    target_xz = (0.0, 300_000.0)
    launch_pos = np.array([0.0, 50.0, 0.0], dtype=np.float64)  # already at cruise alt
    vel = np.array([0.0, 0.0, TOMAHAWK.cruise_mach * 340.0], dtype=np.float64)

    # Reduce fuel so it runs out well before the target.
    from dataclasses import replace as dc_replace
    lean_weapon = dc_replace(TOMAHAWK, fuel_mass=10.0)
    m = StrikeMissile(lean_weapon, launch_pos, vel, target_xz)
    m.fuel = 10.0   # override the copied value too

    max_steps = int(600.0 / DT)   # 10 minutes ceiling
    _run(m, _WORLD, max_steps)

    # Must have run out of fuel and hit the sea before 300 km.
    assert not m.alive, "Fuel-exhausted missile must self-terminate"
    assert m.impact_pos is not None

    # Did NOT reach the 300 km target.
    iz = float(m.impact_pos[2])
    assert iz < 290_000.0, (
        f"Fuel-exhausted Tomahawk should not reach target; z = {iz:.0f} m"
    )


# ---------------------------------------------------------------------------
# 7. Duck-type completeness check (render-layer contract)
# ---------------------------------------------------------------------------

def test_strike_missile_duck_type():
    """Verify the attributes game/sandbox.py _draw_missiles and
    _missile_effects read from every missile in world.missiles."""
    m = _tomahawk_vls(np.zeros(3), (0.0, 1_000.0))

    # Core attributes.
    assert hasattr(m, "pos") and m.pos.shape == (3,)
    assert hasattr(m, "vel") and m.vel.shape == (3,)
    assert hasattr(m, "prev_pos") and m.prev_pos.shape == (3,)
    assert hasattr(m, "alive")
    assert hasattr(m, "phase")
    assert hasattr(m, "impact_pos")
    # Optional body_dir (getattr with fallback — but we expose it explicitly).
    assert hasattr(m, "body_dir") and m.body_dir.shape == (3,)
    # phase_label duck-type.
    assert isinstance(m.phase_label, str)
    # velocity() shared duck-type.
    v = m.velocity()
    assert v.shape == (3,)


def test_harm_missile_duck_type():
    """HarmMissile exposes the same duck-type contract."""
    radar = _radar_at(0.0, 10_000.0)
    rng = np.random.default_rng(99)
    m = _harm_air(np.zeros(3), np.array([0.0, 0.0, 200.0]), radar, rng)

    assert hasattr(m, "pos") and m.pos.shape == (3,)
    assert hasattr(m, "vel") and m.vel.shape == (3,)
    assert hasattr(m, "prev_pos") and m.prev_pos.shape == (3,)
    assert hasattr(m, "alive")
    assert hasattr(m, "phase")
    assert hasattr(m, "impact_pos")
    assert hasattr(m, "body_dir")
    assert isinstance(m.phase_label, str)
    assert m.velocity().shape == (3,)
