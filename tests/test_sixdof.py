"""6-DOF rigid-body contracts (plan: docs/plans/sixdof_plan_2026-07-17.md).

GL-free. Every behavior here must EMERGE from the physics — no branch in
sim/sixdof.py may special-case any of these outcomes.
"""

import math

import numpy as np

from models.test_rocket import (build_flip_brake, build_gyro_gimbal,
                                build_pulse_lander, build_rcs_needle,
                                build_returner)
from sim.physics import GRAVITY
from sim.sixdof import (SCALE_HEIGHT, configure_flip_brake_scenario,
                        configure_rcs_scenario, configure_returner_scenario,
                        make_flip_brake, make_gyro_gimbal, make_pulse_lander,
                        make_rcs_needle, make_returner, make_spin_dart,
                        make_test_hopper, make_tractor, make_tvc_stick)

DT = 1.0 / 120.0


def _no_burn(body):
    """Constant-mass variant so analytic predictions are exact."""
    body.d.fuel_rate = 0.0
    return body


def _run(body, seconds, dt=DT):
    for _ in range(int(round(seconds / dt))):
        body.step(dt)
    return body


def test_five_new_prototype_models_are_real_nonempty_geometry():
    for builder in (build_returner, build_gyro_gimbal, build_flip_brake,
                    build_rcs_needle, build_pulse_lander):
        mesh = builder()
        assert len(mesh.vertices) > 0
        assert len(mesh.indices) > 0
        assert np.all(np.isfinite(mesh.vertices))


def test_liftoff_at_sea_level():
    b = _no_burn(make_test_hopper())
    b.ignite()
    _run(b, 2.0)
    assert not b.on_ground
    assert b.pos[1] > 3.0


def test_hover_ceiling_emerges():
    """Measured 2026-07-17: static ceiling 1188 m; the light low-drag
    article overshoots on momentum to 1598 m then phugoids around the
    equilibrium, settling into a 1088-1308 m band by t=400 s. The
    atmosphere caps it as a bounded oscillation, not a hard lid."""
    b = _no_burn(make_test_hopper())
    ceiling = SCALE_HEIGHT * math.log(
        b.d.thrust_sl / (b.mass * GRAVITY))
    b.ignite()
    peak = 0.0
    late_lo, late_hi = float("inf"), 0.0
    for i in range(int(600.0 / DT)):
        b.step(DT)
        alt = float(b.pos[1])
        peak = max(peak, alt)
        if i * DT >= 400.0:
            late_lo = min(late_lo, alt)
            late_hi = max(late_hi, alt)
    # Momentum overshoot is energy-bounded, never a runaway.
    assert peak > 0.85 * ceiling
    assert peak < 1.45 * ceiling
    # After the phugoid damps it orbits the analytic ceiling.
    assert late_lo > 0.85 * ceiling
    assert late_hi < 1.18 * ceiling


def test_fan_thrust_decays_with_altitude():
    b = _no_burn(make_test_hopper())
    b.ignite()
    t_sea = b._thrust_magnitude(0.0)
    t_high = b._thrust_magnitude(3000.0)
    assert t_high < 0.75 * t_sea


def test_rocket_thrust_grows_with_altitude():
    b = _no_burn(make_test_hopper())
    b.d.engine = "rocket"
    b.d.mdot = 2.0
    b.d.exhaust_velocity = 2200.0
    b.d.exit_area = 0.05
    b.d.exit_pressure = 70_000.0
    b.ignite()
    assert b._thrust_magnitude(20_000.0) > b._thrust_magnitude(0.0)


def _flying(body, tilt_deg=6.0):
    """Place the body in a vertical 70 m/s climb with a small nose tilt."""
    body.pos[:] = (0.0, 800.0, 0.0)
    body.vel[:] = (0.0, 70.0, 0.0)
    a = math.radians(90.0 - tilt_deg) * 0.5
    # Rotation about x mapping nose from +Z toward up-with-tilt.
    body.quat[:] = (math.cos(a), -math.sin(a), 0.0, 0.0)
    body.omega[:] = 0.0
    body.on_ground = False
    return body


def test_static_stability_recovers():
    b = _flying(_no_burn(make_test_hopper()))
    b.ignite()
    first = None
    for _ in range(int(4.0 / DT)):
        b.step(DT)
        if first is None:
            first = b.alpha_rad
    assert first > 0.01
    assert b.alpha_rad < 0.6 * first


def test_unstable_article_tumbles():
    """Measured 2026-07-17: CP-ahead-of-CG article flails end over end —
    alpha sustained at 60-75 deg while pitch swings +84 to -68 deg. The
    departure signature is sustained huge alpha PLUS the pitch range
    (alpha alone tops out near 75 deg because the velocity vector chases
    the tumbling body)."""
    b = _flying(_no_burn(make_test_hopper(unstable=True)))
    b.ignite()
    worst = 0.0
    p_lo, p_hi = 90.0, -90.0
    for _ in range(int(15.0 / DT)):
        b.step(DT)
        worst = max(worst, b.alpha_rad)
        p = b.pitch_deg()
        p_lo, p_hi = min(p_lo, p), max(p_hi, p)
    assert worst > math.radians(45.0)     # flow detached, way past stall
    assert p_hi - p_lo > 100.0            # nose explored half the sky


def test_misaligned_thrust_tips_it_over():
    clean = _no_burn(make_test_hopper())
    bent = _no_burn(make_test_hopper(misalign_deg=2.0))
    clean.ignite()
    bent.ignite()
    lowest_clean, lowest_bent = 90.0, 90.0
    for _ in range(int(10.0 / DT)):
        clean.step(DT)
        bent.step(DT)
        lowest_clean = min(lowest_clean, clean.pitch_deg())
        lowest_bent = min(lowest_bent, bent.pitch_deg())
    assert lowest_clean > 80.0            # straight engine flies straight
    assert lowest_bent < 30.0             # bent engine tips the vehicle


def test_rocket_variant_climbs_past_fan_ceiling():
    """Same airframe, rocket motor: ~435 N at sea level (overexpanded
    nozzle costs thrust down low) but thrust GROWS as pressure drops, so
    unlike the fan it climbs through the fan's ~1.2 km equilibrium. The
    proving-ground motor is unlimited and mass remains fixed."""
    b = make_test_hopper(engine="rocket")
    b.ignite()
    _run(b, 60.0)
    fan_ceiling = SCALE_HEIGHT * math.log(
        b.d.thrust_sl / (b.mass * GRAVITY))
    assert b.pos[1] > 1.2 * fan_ceiling


def test_grab_pull_at_nose_torques_and_topples():
    """The mouse spring acts AT the grabbed point: pulling the nose
    sideways must rotate the vehicle (torque), not just slide it."""
    b = make_test_hopper()
    b.set_grab(np.array([0.0, 0.0, 1.4]),          # the nose
               np.array([4.0, 4.5, 0.0]))          # pull up and sideways
    for _ in range(int(3.0 / DT)):
        b.step(DT)
        b.move_grab(np.array([4.0, 4.5, 0.0]))
    assert b.pitch_deg() < 55.0                    # it leaned toward the pull
    assert b.grab_force_n > 100.0                  # the spring is working
    b.clear_grab()
    assert b.grab_force_n == 0.0


def test_disturbance_tool_cannot_lift_it_off_the_pad():
    """The mouse applies a force couple: attitude torque, zero net lift."""
    b = make_test_hopper()
    b.set_grab(np.array([0.0, 0.0, 0.0]),
               np.array([0.0, 12.0, 0.0]))
    for _ in range(int(4.0 / DT)):
        b.step(DT)
    assert b.on_ground
    assert math.isclose(float(b.pos[1]), b.d.length * 0.5, abs_tol=1e-9)
    assert b.grab_force_n <= 150.0


def test_test_motor_never_burns_out_or_changes_mass():
    b = make_test_hopper(engine="rocket")
    fuel, mass = b.fuel, b.mass
    b.ignite()
    _run(b, 60.0)
    assert b.engine_on
    assert b.fuel == fuel
    assert b.mass == mass
    assert b.thrust_n > 0.0


def test_unpowered_tumbling_body_dissipates_and_hits_ground():
    """Regression for the reported floating/velocity-regain failure.

    A sideways, rotating, engine-off stick must lose mechanical energy to
    broadside drag and hit the plate. It cannot become a lossless looping wing.
    """
    b = make_tvc_stick()
    b.pos[:] = (0.0, 500.0, 0.0)
    b.vel[:] = (30.0, -20.0, 0.0)
    b.omega[:] = (1.0, 0.5, 0.2)
    b.on_ground = False
    e0 = 0.5 * b.mass * float(b.vel @ b.vel) + b.mass * GRAVITY * b.pos[1]
    peak_e = e0
    for _ in range(int(20.0 / DT)):
        b.step(DT)
        energy = (0.5 * b.mass * float(b.vel @ b.vel)
                  + b.mass * GRAVITY * b.pos[1])
        peak_e = max(peak_e, energy)
        if b.on_ground:
            break
    assert b.on_ground
    assert peak_e <= 1.001 * e0


def _flight_tilt_deg(b):
    v = b.vel
    s = float(np.linalg.norm(v))
    if s < 1.0:
        return 0.0
    return math.degrees(math.acos(max(-1.0, min(1.0, float(v[1]) / s))))


def test_spin_stabilization_beats_bent_motor():
    """Measured 2026-07-17: identical 1.5 deg bent motors. The canted-
    nozzle dart spins to ~42 rad/s and gyroscopic stiffness holds its
    worst tilt to ~42 deg, 767 m up at t=8 s; the unspun dart loops past
    horizontal (worst 133 deg) and craters 84 m from the pad."""
    spun = make_spin_dart(spin=True)
    unspun = make_spin_dart(spin=False)
    spun.ignite()
    unspun.ignite()
    worst_s, worst_u = 0.0, 0.0
    for _ in range(int(8.0 / DT)):
        spun.step(DT)
        unspun.step(DT)
        worst_s = max(worst_s, _flight_tilt_deg(spun))
        worst_u = max(worst_u, _flight_tilt_deg(unspun))
    assert float(spun.omega[2]) > 25.0        # it spun up
    assert worst_s < 55.0                     # and flew usably straight
    assert spun.pos[1] > 300.0                # still climbing
    assert worst_u > 100.0                    # the unspun one looped over
    assert unspun.pos[1] < 10.0               # and hit the plate


def test_tvc_fcs_balances_unstable_stick():
    """The stick's CP is AHEAD of its CG: aerodynamically doomed. With
    the FCS on, the gimbal (settling near -2 deg to null the bent motor)
    holds it vertical; the same airframe with the FCS off departs."""
    on = make_tvc_stick()
    off = make_tvc_stick()
    off.fcs_on = False
    on.ignite()
    off.ignite()
    lowest_on, lowest_off = 90.0, 90.0
    for _ in range(int(8.0 / DT)):
        on.step(DT)
        off.step(DT)
        lowest_on = min(lowest_on, on.pitch_deg())
        lowest_off = min(lowest_off, off.pitch_deg())
    assert lowest_on > 80.0
    assert lowest_off < 0.0


def test_tractor_pendulum_fallacy():
    """Goddard's fallacy: the motor at the NOSE pulling does not make a
    stable pendulum — thrust rotates with the body, so a bent motor tips
    it exactly like a tail-pusher (measured: to -23 deg within 10 s)."""
    b = make_tractor()
    b.ignite()
    lowest = 90.0
    for _ in range(int(10.0 / DT)):
        b.step(DT)
        lowest = min(lowest, b.pitch_deg())
    assert lowest < 30.0


def test_strong_wind_weathercocks_the_hopper_into_the_wind():
    """Measured 2026-07-17 (and it surprised us): a 14 m/s crosswind on
    the slow-climbing stable hopper does NOT push it downwind — the aft
    CP weathercocks the nose INTO the relative wind (pitch +90 -> +7 deg
    by t=6 s), the body-fixed thrust then drags it 160 m UPWIND, and it
    plows in. Real weathervane physics; nobody scripted it."""
    b = _no_burn(make_test_hopper())
    b.wind = np.array([14.0, 0.0, 0.0])
    b.ignite()
    lowest = 90.0
    for _ in range(int(12.0 / DT)):
        b.step(DT)
        lowest = min(lowest, b.pitch_deg())
    assert lowest < 30.0                      # it weathercocked hard
    assert float(b.pos[0]) < -20.0            # and went UPWIND, not down


def test_determinism():
    def run():
        b = make_test_hopper(misalign_deg=1.0)
        b.ignite()
        _run(b, 20.0)
        return b.state_repr()
    assert run() == run()


def test_quaternion_stays_normalized():
    b = _no_burn(make_test_hopper(misalign_deg=2.0))
    b.ignite()
    for _ in range(10_000):
        b.step(DT)
        assert abs(float(np.linalg.norm(b.quat)) - 1.0) < 1e-9


def test_ground_rest_is_still():
    b = make_test_hopper()
    start = b.pos.copy()
    _run(b, 5.0)
    assert b.on_ground
    assert np.allclose(b.pos, start, atol=1e-9)
    assert float(np.linalg.norm(b.vel)) == 0.0


def test_returner_three_off_angle_scenarios_land_on_pad_softly():
    """The controller receives state, then acts only through bounded RCS,
    gimbal and throttle. All three high-energy presets must physically close."""
    for scenario in range(3):
        b = make_returner()
        configure_returner_scenario(b, scenario)
        for _ in range(int(90.0 / DT)):
            b.step(DT)
            if b.controller_phase in ("LANDED", "CRASHED"):
                break
        assert b.controller_phase == "LANDED"
        assert float(np.linalg.norm(b.pos[[0, 2]])) < 6.0
        assert b.touchdown_speed < 4.0


def test_gyro_gimbal_combines_two_independent_stabilizers():
    both = make_gyro_gimbal()
    spin_only = make_gyro_gimbal()
    spin_only.fcs_on = False
    neither = make_gyro_gimbal()
    neither.fcs_on = False
    neither.spin_enabled = False
    for b in (both, spin_only, neither):
        b.ignite()
        _run(b, 10.0)
    assert both.pitch_deg() > 80.0 and both.pos[1] > 800.0
    assert spin_only.pos[1] > 100.0       # gyro alone buys real survivability
    assert neither.on_ground              # bent unstable core without either


def test_flip_brake_deployment_dissipates_speed_and_rotation():
    closed = make_flip_brake()
    opened = make_flip_brake()
    configure_flip_brake_scenario(closed, 0)
    configure_flip_brake_scenario(opened, 0)
    opened.airbrake_deployed = True
    _run(closed, 8.0)
    _run(opened, 8.0)
    assert float(np.linalg.norm(opened.vel)) < 0.7 * float(np.linalg.norm(closed.vel))
    assert float(np.linalg.norm(opened.omega)) < float(np.linalg.norm(closed.omega))
    assert opened.current_cp_z() < opened.d.cg_z


def test_rcs_hold_has_authority_in_thin_air():
    controlled = make_rcs_needle()
    free = make_rcs_needle()
    configure_rcs_scenario(controlled, 0)
    configure_rcs_scenario(free, 0)
    free.rcs_hold_on = False
    _run(controlled, 8.0)
    _run(free, 8.0)
    assert float(np.linalg.norm(controlled.omega)) < 0.05
    assert float(np.linalg.norm(free.omega)) > 0.2


def test_pulse_lander_hovers_using_only_full_or_zero_thrust():
    b = make_pulse_lander()
    states = set()
    for _ in range(int(30.0 / DT)):
        b.step(DT)
        states.add((b.engine_on, b.throttle))
    assert abs(float(b.pos[1]) - (0.5 * b.d.length + b.target_altitude)) < 2.0
    assert (True, 1.0) in states
    assert (False, 0.0) in states


def test_spin_dart_roll_brake_can_kill_the_spin_live():
    free = make_spin_dart()
    braked = make_spin_dart()
    for b in (free, braked):
        b.ignite()
        _run(b, 5.0)
    braked.airbrake_deployed = True
    _run(free, 3.0)
    _run(braked, 3.0)
    assert abs(float(braked.omega[2])) < 0.2 * abs(float(free.omega[2]))


def test_tvc_live_target_and_jam_controls_change_the_outcome():
    lean = make_tvc_stick()
    jammed = make_tvc_stick()
    lean.fcs_target_mode = "LEAN 12 DEG"
    jammed.gimbal_jammed = True
    lean.ignite()
    jammed.ignite()
    _run(lean, 10.0)
    _run(jammed, 10.0)
    assert 70.0 < lean.pitch_deg() < 85.0
    assert jammed.pitch_deg() < 0.0
