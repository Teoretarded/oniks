"""S-300 definitions + SamMissile flight model tests (Task S2, GL-free).

Covers: SamDef/S300/S300_TEL locked numbers and registries; cold catapult
launch (vertical, no lateral drift); boost performance (Mach > 4 by burnout,
loft above 8 km on a long shot); e2e intercepts at 60 km (crossing, < 90 s),
130 km (long) and 40 km (maneuvering fast type); honest miss + self-destruct
at 200 km; surface impact; midcourse-on-contact-estimate; determinism.
"""

import math

import numpy as np
import pytest

from sim.aircraft import AC_ALIVE, AC_FALLING, Aircraft
from sim.arsenal import LAUNCHERS, S300, S300_TEL, SAMS
from sim.physics import GRAVITY, mach_scalar
from sim.sam import (SPH_BOOST, SPH_DEAD, SPH_EJECT, SPH_MIDCOURSE,
                     SPH_TERMINAL, SamMissile)

DT = 1.0 / 120.0
LAUNCH_POS = np.array([0.0, 5.0, 0.0])     # tube mouth a few meters up


class _World:   # minimal stub: open ocean, no ships
    ships = []

    def terrain_height_at(self, x, z):
        return -50.0


def _sam(target, estimate_fn=None):
    return SamMissile(S300, LAUNCH_POS, target, contact_estimate_fn=estimate_fn)


def _crossing_patrol(rng_m, ac_type="patrol"):
    """Aircraft spawned rng_m due west of the launcher, first racetrack leg
    due north — crossing the launcher's line of sight. The track width fits
    a 180-degree turn for either type (fast needs ~18.4 km)."""
    width = 16_000.0 if ac_type == "patrol" else 20_000.0
    return Aircraft("air_t", ac_type,
                    (-rng_m, 0.0), (-rng_m + width, 70_000.0))


def _engage(m, ac, t_max):
    """Step aircraft-then-missile (world.step order) until the missile dies
    or t_max. Returns (elapsed sim time, min point-sampled separation)."""
    w = _World()
    t = 0.0
    min_d = float("inf")
    while m.alive and t < t_max:
        ac.update(DT)
        m.update(DT, w)
        t += DT
        d = float(np.linalg.norm(m.pos - ac.pos))
        min_d = min(min_d, d)
    return t, min_d


# --- definitions (locked numbers) ---------------------------------------------

def test_s300_definition_locked_numbers():
    assert S300.weapon_id == "s300"
    assert S300.display_name == "S-300 48N6"
    assert S300.length == 7.5 and S300.diameter == 0.515
    assert S300.launch_mass == 1900.0 and S300.propellant_mass == 1020.0
    # Task LC true cold launch: catapult to ~20 m apex, ignition via the
    # delay unit 1.0-1.5 s after tube exit at near-zero vertical speed
    # (s300_reference.md §1 timeline) — the hang pause is sacred.
    assert S300.eject_speed == 18.0
    assert 1.0 <= S300.eject_time <= 1.5
    assert S300.motor_thrust == 200_000.0 and S300.motor_time == 12.0
    # mdot = thrust / (240 * 9.81): the 12 s burn consumes the propellant load
    assert S300.isp == 240.0
    mdot = S300.motor_thrust / (S300.isp * GRAVITY)
    assert mdot * S300.motor_time == pytest.approx(S300.propellant_mass, rel=0.01)
    assert S300.ref_area == pytest.approx(0.208, abs=1e-3)
    assert S300.max_g == 25.0 and S300.fuse_radius == 25.0
    assert S300.terminal_range == 20_000.0
    assert S300.max_range == 150_000.0
    assert S300.self_destruct_t == 180.0 and S300.self_destruct_speed == 250.0
    assert S300.min_intercept_alt == 100.0
    assert S300.max_intercept_alt == 25_000.0
    assert S300.launch_mass > S300.propellant_mass
    assert SAMS["s300"] is S300


def test_s300_tel_definition():
    assert S300_TEL.launcher_id == "s300_tel"
    assert S300_TEL.display_name == "5P85 TEL"
    assert S300_TEL.weapon_ids == ("s300",)
    assert S300_TEL.reload_s == 8.0
    assert S300_TEL.tubes == 4 and S300_TEL.ammo == 4
    assert LAUNCHERS["s300_tel"] is S300_TEL
    assert LAUNCHERS["bastion"].reload_s == 18.0    # v1 entry untouched


# --- launch phases --------------------------------------------------------------

def test_cold_launch_vertical_no_lateral_drift():
    ac = _crossing_patrol(60_000.0)
    m = _sam(ac)
    w = _World()
    for _ in range(int(1.0 / DT)):
        m.update(DT, w)
    assert m.phase == SPH_EJECT                  # still hanging, unlit
    assert m.pos[0] == LAUNCH_POS[0] and m.pos[2] == LAUNCH_POS[2]
    assert m.pos[1] > LAUNCH_POS[1]
    assert 0.0 < m.vel[1] < S300.eject_speed     # gravity only: decelerating
    # Ignition shortly after the hang; BOOST stays pure vertical only for
    # BOOST_VERTICAL_TIME (researched: the declination is visibly under way
    # inside the first second after ignition - s300_tipover_physics.md).
    while m.phase == SPH_EJECT:
        m.update(DT, w)
    for _ in range(int(0.25 / DT)):              # inside the vertical window
        m.update(DT, w)
    assert m.phase == SPH_BOOST
    assert m.pos[0] == LAUNCH_POS[0] and m.pos[2] == LAUNCH_POS[2]
    assert m.vel[0] == 0.0 and m.vel[2] == 0.0
    assert m.vel[1] > 0.0                        # the motor is burning
    for _ in range(int(1.0 / DT)):               # ... and by +1.25 s the
        m.update(DT, w)                          # programmed turn has begun
    assert m.vel[0] != 0.0 or m.vel[2] != 0.0


def test_eject_hang_apex_and_ignition_delay():
    """Task LC cold-launch signature: catapult out, visibly decelerate to
    near-zero vertical speed 18-32 m up, motor lights 1.0-1.5 s after exit."""
    ac = _crossing_patrol(60_000.0)
    mouth = np.array([0.0, 9.0, 0.0])            # erect tube mouth height
    m = SamMissile(S300, mouth, ac)
    w = _World()
    apex = 0.0
    vy_at_ignition = None
    t_ignition = None
    while m.phase == SPH_EJECT and m.t < 3.0:
        vy_before = float(m.vel[1])
        m.update(DT, w)
        if m.phase == SPH_EJECT:
            apex = max(apex, float(m.pos[1]))
        else:
            vy_at_ignition = vy_before
            t_ignition = m.t
    assert m.phase == SPH_BOOST                  # it did light
    assert 18.0 <= apex <= 32.0                  # the hang happens up high
    assert abs(vy_at_ignition) < 4.0             # near-zero at light-off
    assert 1.0 <= t_ignition <= 1.55             # the pause is sacred


def test_tipover_rate_matches_footage():
    """Gas-vane tip-over, frame-timed footage contract (normative:
    s300_tipover_physics.md - S-300P war shot: ~30 deg off vertical ~1 s
    after ignition, ~60 deg at ~2 s, declination complete in 1.5-2.5 s).
    The PATH (smoke column) lags the body slightly, so the path must reach
    30 deg between 0.8 and 2.4 s after ignition - the lower bound guards
    against the old instant-corner regime (which got there in ~0.4 s), the
    upper against a sluggish autopilot. Supersedes the first research
    pass's eyeballed 'within 150 m' bound."""
    ac = _crossing_patrol(60_000.0)
    m = SamMissile(S300, np.array([0.0, 9.0, 0.0]), ac)
    w = _World()
    t_ignition = None
    tilt = 0.0
    while m.t < 8.0:
        ac.update(DT)
        m.update(DT, w)
        if t_ignition is None and m.phase == SPH_BOOST:
            t_ignition = m.t
        speed = float(np.linalg.norm(m.vel))
        if speed > 1e-6 and m.phase == SPH_BOOST:
            tilt = math.degrees(math.acos(min(float(m.vel[1]) / speed, 1.0)))
            if tilt >= 30.0:
                break
    assert t_ignition is not None
    assert tilt >= 30.0                              # the kink happened
    dt_30 = m.t - t_ignition
    assert 0.8 <= dt_30 <= 2.4, f"path hit 30 deg {dt_30:.2f} s after ignition"


def test_boost_reaches_mach4_by_burnout_and_lofts_above_8km():
    ac = _crossing_patrol(130_000.0)
    m = _sam(ac)
    w = _World()
    burnout_mach = 0.0
    peak_alt = 0.0
    for _ in range(int(45.0 / DT)):
        ac.update(DT)
        m.update(DT, w)
        peak_alt = max(peak_alt, float(m.pos[1]))
        if m.phase == SPH_BOOST:
            burnout_mach = mach_scalar(float(np.linalg.norm(m.vel)),
                                       float(m.pos[1]))
    assert m.alive and m.phase in (SPH_MIDCOURSE, SPH_TERMINAL)
    assert m.propellant == 0.0
    assert burnout_mach > 4.0                    # last sample while boosting
    assert peak_alt > 8_000.0                    # high shot lofts


# --- e2e intercepts --------------------------------------------------------------

def test_crossing_patrol_at_60km_killed_under_90s():
    ac = _crossing_patrol(60_000.0)
    m = _sam(ac)
    t, _ = _engage(m, ac, t_max=90.0)
    assert ac.state == AC_FALLING                # proximity kill -> spiral
    assert not m.alive and m.phase == SPH_DEAD
    assert m.impact_pos is not None
    assert float(np.linalg.norm(m.impact_pos - ac.pos)) <= S300.fuse_radius
    assert t < 90.0


def test_long_shot_130km_killed():
    ac = _crossing_patrol(130_000.0)
    m = _sam(ac)
    t, _ = _engage(m, ac, t_max=S300.self_destruct_t + 5.0)
    assert ac.state == AC_FALLING
    assert not m.alive and m.phase == SPH_DEAD
    assert float(np.linalg.norm(m.impact_pos - ac.pos)) <= S300.fuse_radius
    assert t < S300.self_destruct_t


def test_out_of_envelope_200km_honest_miss_and_self_destruct():
    ac = _crossing_patrol(200_000.0)
    m = _sam(ac)
    t, min_d = _engage(m, ac, t_max=S300.self_destruct_t + 10.0)
    assert ac.state == AC_ALIVE                  # the target survives
    assert not m.alive and m.phase == SPH_DEAD   # honest energy death
    assert m.impact_pos is not None
    assert m.impact_pos[1] > 1_000.0             # airborne self-destruct
    assert min_d > 5_000.0                       # never got close


def test_maneuvering_fast_type_at_40km_killed():
    ac = _crossing_patrol(40_000.0, ac_type="fast")
    m = _sam(ac)
    t, _ = _engage(m, ac, t_max=90.0)
    assert ac.state == AC_FALLING
    assert not m.alive and m.phase == SPH_DEAD
    assert float(np.linalg.norm(m.impact_pos - ac.pos)) <= S300.fuse_radius


# --- guidance sources ------------------------------------------------------------

def test_contact_estimate_drives_midcourse_seeker_corrects():
    """Boost/midcourse fly the (stale, offset) CONTACT estimate; the terminal
    seeker and the proximity fuse use truth — the kill still happens."""
    ac = _crossing_patrol(60_000.0)
    offset = np.array([3_000.0, 0.0, -2_000.0])
    phases_seen = []

    def estimate():
        phases_seen.append(m.phase)
        return ac.pos + offset, ac.velocity()

    m = _sam(ac, estimate_fn=estimate)
    _engage(m, ac, t_max=120.0)
    assert ac.state == AC_FALLING                # killed despite stale picture
    assert phases_seen                           # the estimate WAS consulted
    assert all(ph < SPH_TERMINAL for ph in phases_seen)   # never in terminal


# --- death modes -----------------------------------------------------------------

def test_surface_impact_kills_the_missile():
    ac = _crossing_patrol(200_000.0)
    m = _sam(ac)
    w = _World()
    m.phase = SPH_MIDCOURSE
    m.propellant = 0.0
    m.t = 30.0
    m.pos[:] = (0.0, 50.0, 1_000.0)
    m.prev_pos[:] = m.pos
    m.vel[:] = (0.0, -400.0, 200.0)              # diving, speed > 250 m/s
    for _ in range(40):
        m.update(DT, w)
        if not m.alive:
            break
    assert not m.alive and m.phase == SPH_DEAD
    assert m.impact_pos is not None and m.impact_pos[1] == 0.0   # the sea


# --- determinism -----------------------------------------------------------------

def test_determinism_bit_identical_reruns():
    runs = []
    for _ in range(2):
        ac = _crossing_patrol(60_000.0)
        m = _sam(ac)
        w = _World()
        for _ in range(int(30.0 / DT)):
            ac.update(DT)
            m.update(DT, w)
        runs.append((m.pos.copy(), m.vel.copy(), m.phase, m.t))
    assert np.array_equal(runs[0][0], runs[1][0])
    assert np.array_equal(runs[0][1], runs[1][1])
    assert runs[0][2] == runs[1][2] and runs[0][3] == runs[1][3]


# --- Turn dynamics (user feedback 2026-06-11: no instant path kinks) ----------

def test_sam_tilt_rate_is_continuous():
    # The gas-vane tip-over is violent but must be CONTINUOUS: the rate can
    # change at most TILT_ACCEL*dt (~1.3 deg/s) per tick, so a step-to-step
    # jump beyond a small margin is the old single-tick kink (the unslewed
    # code commanded the full g-limited rate — hundreds of deg/s at catapult
    # speed — in one step).
    ac = _crossing_patrol(60_000.0)
    sam = _sam(ac)
    w = _World()
    rates = []
    prev_dir = None
    for _ in range(int(10.0 / DT)):
        sam.update(DT, w)
        ac.update(DT)
        if not sam.alive:
            break
        v = sam.vel
        s = float(np.linalg.norm(v))
        if s < 1.0:
            continue
        d = (v / s).copy()
        if prev_dir is not None:
            c = min(1.0, max(-1.0, float(d @ prev_dir)))
            rates.append(math.degrees(math.acos(c)) / DT)
        prev_dir = d
    jumps = [abs(b - a) for a, b in zip(rates, rates[1:])]
    assert max(jumps) < 4.0
