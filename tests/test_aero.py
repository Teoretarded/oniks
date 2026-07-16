"""Energy-model contracts (plan: docs/plans/energy_physics_graphics_2026-07-05.md,
research: docs/research/missile_energy_autopilot_2026-07-05.md).

The user's bug report, verbatim: "I can right-click anywhere on the map, it
will do a 180, it won't lose any speed." These tests lock the physics that
makes turning COST energy: induced drag ~ n^2/q, available g ~ q, achieved
accel lags command, and thrust refills the budget slowly — never instantly.
GL-free; tune the gains in sim/aero.py + the per-weapon fields, never these
contracts.
"""

import math

import numpy as np

from sim import aero
from sim.arsenal import ONIKS, S300
from sim.missile import PH_CRUISE, Missile
from sim.physics import GRAVITY, speed_of_sound_scalar
from sim.sam import SPH_MIDCOURSE, SamMissile

DT = 1.0 / 120.0


class _World:   # minimal stub: open ocean (the test_retarget.py pattern)
    ships = []

    def terrain_height_at(self, x, z):
        return -50.0


class _Target:  # SamMissile target duck-type: far, static, alive
    def __init__(self, pos):
        self.pos = np.asarray(pos, dtype=np.float64)
        self.alive = True

    def velocity(self):
        return np.zeros(3)


def _cruising_oniks(profile, alt, mach, heading_z=1.0,
                    target=(0.0, 0.0, 400_000.0)):
    """An Oniks dropped straight into steady cruise (launch phases skipped)."""
    m = Missile(ONIKS, np.array([0.0, alt, 0.0]), 0.0, profile,
                np.asarray(target, dtype=np.float64))
    m.phase = PH_CRUISE
    v = mach * speed_of_sound_scalar(alt)
    m.vel = np.array([0.0, 0.0, heading_z * v])
    m.body_dir = np.array([0.0, 0.0, heading_z])
    return m


def _heading_err_to_south(m) -> float:
    """|wrapped| angle between current horizontal heading and due south."""
    hd = math.atan2(float(m.vel[0]), float(m.vel[2]))
    return abs((hd - math.pi + math.pi) % (2.0 * math.pi) - math.pi)


def _run_180(alt, mach, timeout_s=240.0):
    """Cruise 5 s straight, retarget 180 degrees behind, run to completion.

    Returns (v0, min_speed, turn_time_s, speeds_after_turn) where
    turn_time_s is retarget -> heading within 15 deg of south, and
    speeds_after_turn covers the 120 s after the retarget command."""
    w = _World()
    m = _cruising_oniks("hi-lo" if alt > 5_000.0 else "lo-lo", alt, mach)
    for _ in range(int(5.0 / DT)):          # settle onto the Mach-hold
        m.update(DT, w)
    v0 = float(np.linalg.norm(m.vel))
    assert m.retarget(np.array([0.0, 0.0, -400_000.0])), "retarget refused"
    min_speed = v0
    turn_time = None
    speeds = []
    steps = int(timeout_s / DT)
    for i in range(steps):
        m.update(DT, w)
        assert m.alive, "missile died mid-maneuver"
        s = float(np.linalg.norm(m.vel))
        if i * DT <= 120.0:
            speeds.append(s)
        min_speed = min(min_speed, s)
        if turn_time is None and _heading_err_to_south(m) < math.radians(15.0):
            turn_time = i * DT
        if turn_time is not None and i * DT > 120.0:
            break
    assert turn_time is not None, "180-degree turn never completed"
    return v0, min_speed, turn_time, speeds


# --- pure aero functions -----------------------------------------------------

def test_available_g_shrinks_with_dynamic_pressure():
    """n_avail = q*S*CLmax/(m*g): halving speed quarters the available g,
    and at 14 km the Oniks physically cannot pull its flat 11 g rating."""
    S, m = ONIKS.ref_area, ONIKS.launch_mass
    cl = aero.CL_MAX_CRUISE
    a_fast = aero.accel_limit_scalar(aero.q_scalar(680.0, 60.0), S, m, cl)
    a_slow = aero.accel_limit_scalar(aero.q_scalar(340.0, 60.0), S, m, cl)
    assert abs(a_slow / a_fast - 0.25) < 1e-6
    a_high = aero.accel_limit_scalar(aero.q_scalar(752.0, 14_000.0), S, m, cl)
    assert a_high < 11.0 * GRAVITY * 0.5, (
        "an Oniks at 14 km must NOT have its full 11 g available")


def test_induced_drag_scales_with_load_squared_and_inverse_q():
    """D_i = k*L^2/(q*S): double the lift -> 4x the drag; half the q ->
    double the drag."""
    q = aero.q_scalar(680.0, 60.0)
    s = ONIKS.ref_area
    d1 = aero.induced_drag_scalar(100_000.0, q, s, 0.2)
    d2 = aero.induced_drag_scalar(200_000.0, q, s, 0.2)
    d3 = aero.induced_drag_scalar(100_000.0, q * 0.5, s, 0.2)
    assert abs(d2 / d1 - 4.0) < 1e-9
    assert abs(d3 / d1 - 2.0) < 1e-9


# --- the user's bug, as physics ----------------------------------------------

def test_180_retarget_bleeds_speed_and_recovers():
    """A sea-level 180-degree retarget BLEEDS >=12% of cruise speed and
    RECOVERS to >=90% within 120 s of the command (thrust refills the
    budget over tens of seconds — never instantly)."""
    v0, min_speed, _turn_time, speeds = _run_180(60.0, ONIKS.cruise_mach_lo)
    assert min_speed <= 0.88 * v0, (
        f"180 turn must cost speed: min {min_speed:.0f} vs cruise {v0:.0f}")
    tail = speeds[-int(10.0 / DT):]
    assert max(tail) >= 0.90 * v0, (
        f"cruise must recover by 120 s: got {max(tail):.0f} vs {v0:.0f}")
    assert min_speed > 150.0, "the turn must not stall the missile outright"


def test_turn_at_altitude_is_slower_and_wider():
    """The same 180 up at 14 km takes >=1.5x longer than at sea level:
    thin air caps available g, so the honest high-altitude signature is a
    slow, wide turn (not an instant flip)."""
    _, _, t_sea, _ = _run_180(60.0, ONIKS.cruise_mach_lo)
    _, _, t_high, _ = _run_180(14_000.0, ONIKS.cruise_mach_hi)
    assert t_high >= 1.5 * t_sea, (
        f"14 km turn ({t_high:.1f} s) must be much slower than sea level "
        f"({t_sea:.1f} s)")


def test_autopilot_lag_no_single_tick_accel_step():
    """Fins take time to bite: the turn rate one tick after the retarget
    command is under 25% of the peak turn rate of the whole maneuver."""
    w = _World()
    m = _cruising_oniks("lo-lo", 60.0, ONIKS.cruise_mach_lo)
    for _ in range(int(5.0 / DT)):
        m.update(DT, w)
    assert m.retarget(np.array([0.0, 0.0, -400_000.0]))

    def turn_rate(mis, steps=1):
        h0 = math.atan2(float(mis.vel[0]), float(mis.vel[2]))
        for _ in range(steps):
            mis.update(DT, w)
        h1 = math.atan2(float(mis.vel[0]), float(mis.vel[2]))
        d = (h1 - h0 + math.pi) % (2.0 * math.pi) - math.pi
        return abs(d) / (steps * DT)

    first_tick = turn_rate(m)
    peak = first_tick
    for _ in range(int(30.0 / DT)):
        peak = max(peak, turn_rate(m))
    assert first_tick < 0.25 * peak, (
        f"first-tick rate {math.degrees(first_tick):.1f} deg/s vs peak "
        f"{math.degrees(peak):.1f} deg/s: commanded accel must ramp, not step")


def test_straight_cruise_holds_mach():
    """The energy model must not tax straight flight: a lo-lo cruise leg
    still holds cruise Mach within 2% (thrust covers trim drag)."""
    w = _World()
    m = _cruising_oniks("lo-lo", 60.0, ONIKS.cruise_mach_lo)
    for _ in range(int(60.0 / DT)):
        m.update(DT, w)
    v = float(np.linalg.norm(m.vel))
    mach = v / speed_of_sound_scalar(float(m.pos[1]))
    assert abs(mach - ONIKS.cruise_mach_lo) <= 0.02 * ONIKS.cruise_mach_lo, (
        f"straight cruise drifted to Mach {mach:.3f}")


def test_sam_coast_turn_bleeds_speed():
    """A burned-out interceptor in a hard midcourse turn sheds speed far
    faster than one coasting straight — the induced-drag tax has no thrust
    to hide behind (research doc worked example B)."""
    w = _World()

    def coast(aligned, seconds=3.0):
        """Burned-out S-300 at 10 km / 1200 m/s vs a target 150 km north.
        ``aligned=True`` flies ALONG the live flight computer's commanded
        path direction (a true straight coast — the planner commands a
        climb, so a horizontal 'control' would secretly be a hard pull);
        ``aligned=False`` flies PERPENDICULAR to it, forcing the hard
        midcourse turn."""
        sam = SamMissile(S300, np.array([0.0, 10_000.0, 0.0]),
                         _Target((0.0, 10_000.0, 150_000.0)))
        sam.phase = SPH_MIDCOURSE
        sam.propellant = 0.0
        sam.vel = np.array([0.0, 0.0, 1200.0])
        if aligned:
            # The production-commanded 3D path direction: one flight-computer
            # step (the same call update() makes), then _command_direction.
            cmd = sam._flight_computer_step(
                DT, w, 0.0, 10_000.0, 0.0, 0.0, 0.0, 1200.0)
            dx, dy, dz = sam._command_direction(
                0.0, 10_000.0, 0.0, sam._fc_aim, cmd)
            sam.vel = np.array([dx, dy, dz]) * 1200.0
        else:
            sam.vel = np.array([1200.0, 0.0, 0.0])   # 90 deg off the aim
        sam.body_dir = sam.vel / np.linalg.norm(sam.vel)
        v0 = float(np.linalg.norm(sam.vel))
        for _ in range(int(seconds / DT)):
            sam.update(DT, w)
        return v0 - float(np.linalg.norm(sam.vel))

    straight_loss = coast(aligned=True)
    turning_loss = coast(aligned=False)
    # Re-pin 2026-07-06: the 4 g midcourse correction budget (MID_MAX_A_G)
    # deliberately softened midcourse turns — the old 2x ratio described
    # the unbudgeted 20 g yank. The surviving contract: a coasting turn
    # still costs measurably more than straight flight (measured delta
    # ~9 m/s over 3 s at the 10 km q-limited authority), and the
    # UNBUDGETED hard-turn tax is locked by the Missile-machine 180-degree
    # test above.
    assert turning_loss > straight_loss + 4.0, (
        f"hard coast turn lost {turning_loss:.0f} m/s vs straight "
        f"{straight_loss:.0f} m/s: turning must cost more than cruising")
