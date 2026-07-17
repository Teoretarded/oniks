"""6-DOF rigid-body flight dynamics (pure numpy, GL-free, zero RNG).

TEST-MAP ONLY for now (plan: docs/plans/sixdof_plan_2026-07-17.md).
Nothing in combat imports this; future weapon integration is a separate
phase behind a CombatConfig flag (default OFF, Law 4).

What is genuinely simulated, per 120 Hz step:

* Thrust is produced AT the nozzle and pointed by the nozzle: any gimbal
  deflection or fixed misalignment produces a real torque r x F. Two
  engine laws:
      fan     T = throttle * T0 * (rho/rho0)          (air-breathing —
              thrust starves with altitude; a marginal-T/W vehicle has a
              hard hover ceiling at  h = H * ln(T0/W))
      rocket  T = mdot*ve + (pe - pa)*Ae              (momentum + nozzle
              pressure term — real rockets GAIN thrust as pa drops)
* Aerodynamic axial drag + normal force act at the center of pressure,
  not the CG: positive static margin weathercocks, negative margin
  tumbles. Nobody scripts "tumble"; it emerges from the torque.
* Euler's rotational equation in the body frame including the w x Iw
  gyroscopic term. Test motors have unlimited propellant, so mass and
  inertia stay fixed and a demo never changes character because it timed out.
* Quaternion attitude, renormalized every step.
* Flat-ground resting contact (a launch stand, not a physics engine).

Frames: world X=east Y=up Z=north (locked convention); body +Z = nose,
quaternion rotates body -> world. All state float64.
"""

from __future__ import annotations

from dataclasses import dataclass

import math

import numpy as np

from sim.physics import (GRAVITY, RHO0, air_density_scalar,
                         air_pressure_scalar)

SCALE_HEIGHT = 8500.0            # matches sim.physics exponential laws
_UP = np.array([0.0, 1.0, 0.0])

# Mouse disturbance spring. It is deliberately a *pure moment*: the force at
# the clicked point is paired with an equal counter-force at the CG. This lets
# a tester upset attitude without hoisting a 40 kg rocket into the sky with
# the mouse. The old 1,000 N translational grab was the source of that bug.
GRAB_KP = 120.0                  # indicated N per meter of stretch
GRAB_KD = 20.0                   # N s/m damping at the picked point
GRAB_MAX_N = 150.0               # bounded attitude disturbance


# --------------------------------------------------------------------------
# definitions


@dataclass
class SixDofDef:
    """Physical definition of a 6-DOF article. SI units throughout."""

    name: str
    dry_mass: float               # kg
    fuel_mass: float              # kg
    length: float                 # m (body axis)
    diameter: float               # m
    engine: str = "fan"           # "fan" | "rocket"
    thrust_sl: float = 0.0        # N, fan: sea-level static at throttle 1
    exhaust_velocity: float = 2200.0   # m/s, rocket momentum term
    mdot: float = 0.0             # kg/s, rocket propellant flow at throttle 1
    exit_area: float = 0.0        # m^2, rocket nozzle exit
    exit_pressure: float = 70_000.0    # Pa, rocket nozzle design exit
    fuel_rate: float = 0.0        # kg/s at throttle 1 (fan fuel draw)
    fixed_mass: bool = True       # test motor: no depletion / no burnout
    # Geometry along the body +Z axis, measured from the geometric center:
    nozzle_z: float = 0.0         # thrust application point (tail < 0)
    cg_z: float = 0.0             # CG position (wet)
    cg_z_dry: float = 0.0         # CG position with fuel exhausted
    cp_z: float = 0.0             # aero center of pressure
    # Aerodynamics:
    cd0: float = 0.6              # axial drag coefficient
    cn_alpha: float = 6.0         # normal-force slope per radian
    damp: float = 12.0            # pitch/yaw damping derivative
    damp_roll: float = -1.0       # roll damping (-1 => same as damp; a
                                  # slender body's real roll damping is
                                  # far smaller than its pitch damping)
    # Spin stabilization: canted nozzles produce a roll moment
    # thrust * sin(cant) * arm while the motor burns.
    spin_cant_rad: float = 0.0
    spin_arm: float = 0.1         # m, tangential moment arm of the cant
    # Thrust-vector flight control (0 gains = no FCS fitted):
    fcs_kp: float = 0.0           # rad gimbal per rad attitude error
    fcs_kd: float = 0.0           # rad gimbal per rad/s body rate
    gimbal_limit_rad: float = 0.0
    gimbal_rate_rad_s: float = 0.0
    # Optional reusable prototype systems. These remain ordinary force and
    # torque producers; the article factories merely choose which are fitted.
    controller: str = "none"       # none | returner | pulse_hover
    rcs_torque: float = 0.0         # N m per axis, independent of atmosphere
    rcs_kp: float = 0.0
    rcs_kd: float = 0.0
    airbrake_drag_mult: float = 1.0
    airbrake_damp_mult: float = 1.0
    airbrake_cp_z: float | None = None
    # Failure knobs:
    misalign_rad: float = 0.0     # fixed thrust misalignment (pitch plane)

    @property
    def ref_area(self) -> float:
        return math.pi * (0.5 * self.diameter) ** 2

    @property
    def roll_damp(self) -> float:
        return self.damp if self.damp_roll < 0.0 else self.damp_roll


def make_test_hopper(misalign_deg: float = 0.0,
                     unstable: bool = False,
                     engine: str = "fan") -> "SixDofBody":
    """The TEST MAP article: very light for its 3 m size, two engine
    variants on the SAME airframe with the SAME barely-lifts sea-level
    thrust — and opposite fates, straight from the physics:

    fan     T = T0 * rho/rho0: starves with altitude => hard hover
            ceiling ~ 1.2 km. It physically cannot fly away.
    rocket  T = mdot*ve + (pe - pa)*Ae: ~435 N at sea level (the nozzle
            is overexpanded down low, the pressure term COSTS thrust),
            growing to ~690 N at 8.5 km — altitude helps it, so it
            accelerates away until the 15 kg of propellant burn out
            (~50 s), then falls back. The atmosphere that caps the fan
            frees the rocket.
    """
    wet = 40.0
    d = SixDofDef(
        name="TEST HOPPER",
        dry_mass=25.0, fuel_mass=wet - 25.0,
        length=3.0, diameter=0.36,
        engine=engine,
        thrust_sl=1.15 * wet * GRAVITY,     # fan: ~451 N static
        fuel_rate=0.05,                     # fan: ~5 min of hover
        exhaust_velocity=2000.0,            # rocket: momentum term 600 N
        mdot=0.30,
        exit_area=0.004,
        exit_pressure=60_000.0,             # overexpanded at sea level
        nozzle_z=-1.45,
        cg_z=-0.15, cg_z_dry=-0.05,
        cp_z=(0.45 if unstable else -0.75),  # CP ahead of CG => tumbles
        cd0=0.8, cn_alpha=5.0, damp=10.0,
        misalign_rad=math.radians(misalign_deg),
    )
    return SixDofBody(d)


def make_spin_dart(misalign_deg: float = 1.5,
                   spin: bool = True) -> "SixDofBody":
    """Unguided rocket dart. With canted nozzles it spins up during the
    burn and gyroscopic stiffness averages the misalignment torque into a
    tight corkscrew — the whole reason unguided rockets spin. Fly the
    same dart with spin=False and the same bent motor walks it off
    course."""
    d = SixDofDef(
        name="SPIN DART",
        dry_mass=14.0, fuel_mass=8.0,
        length=1.8, diameter=0.16,
        engine="rocket",
        exhaust_velocity=1800.0, mdot=0.5,     # 900 N momentum, 16 s burn
        exit_area=0.002, exit_pressure=80_000.0,
        nozzle_z=-0.85,
        cg_z=-0.05, cg_z_dry=0.02,
        cp_z=-0.35,                            # mildly stable fins
        cd0=0.5, cn_alpha=4.0, damp=6.0, damp_roll=0.008,
        spin_cant_rad=math.radians(2.4) if spin else 0.0,
        spin_arm=0.07,
        airbrake_drag_mult=2.2, airbrake_damp_mult=12.0,
        airbrake_cp_z=-0.55,
        misalign_rad=math.radians(misalign_deg),
    )
    return SixDofBody(d)


def make_tvc_stick(misalign_deg: float = 2.0) -> "SixDofBody":
    """A DELIBERATELY unstable rocket (CP ahead of CG) balancing on
    thrust-vector control — the landing-booster problem. A PD loop
    drives a rate-limited gimbal (an actuator, not an oracle). F toggles
    the FCS: on, it climbs arrow-straight through a bent motor and mouse
    yanks; off, the same airframe departs within seconds."""
    d = SixDofDef(
        name="TVC STICK",
        dry_mass=30.0, fuel_mass=20.0,
        length=3.6, diameter=0.30,
        engine="rocket",
        exhaust_velocity=2200.0, mdot=0.5,     # 1100 N momentum, 40 s burn
        exit_area=0.006, exit_pressure=65_000.0,
        nozzle_z=-1.75,
        cg_z=-0.30, cg_z_dry=-0.10,
        cp_z=0.25,                             # UNSTABLE without the FCS
        cd0=0.6, cn_alpha=5.0, damp=8.0,
        fcs_kp=4.0, fcs_kd=1.1,
        gimbal_limit_rad=math.radians(8.0),
        gimbal_rate_rad_s=math.radians(90.0),
        misalign_rad=math.radians(misalign_deg),
    )
    return SixDofBody(d)


def make_tractor(misalign_deg: float = 2.0) -> "SixDofBody":
    """Goddard's pendulum-rocket fallacy, live: the motor sits at the
    NOSE pulling the vehicle like a pendant. Intuition says hanging from
    the engine is stable; physics says the thrust rotates with the body,
    so it tips over exactly like the tail-pusher. Same mass and thrust
    as the hopper's rocket variant — only the nozzle moved."""
    wet = 40.0
    d = SixDofDef(
        name="TRACTOR",
        dry_mass=25.0, fuel_mass=wet - 25.0,
        length=3.0, diameter=0.36,
        engine="rocket",
        exhaust_velocity=2000.0, mdot=0.30,
        exit_area=0.004, exit_pressure=60_000.0,
        nozzle_z=+1.30,                        # the engine is on TOP
        cg_z=-0.15, cg_z_dry=-0.05,
        cp_z=-0.75,
        cd0=0.8, cn_alpha=5.0, damp=10.0,
        misalign_rad=math.radians(misalign_deg),
    )
    return SixDofBody(d)


def make_returner() -> "SixDofBody":
    """Reusable booster demonstrator: deep-throttling engine, wide gimbal,
    and cold-gas attitude jets. Its controller still works only through those
    bounded actuators; it receives no scripted position correction."""
    d = SixDofDef(
        name="RETURNER", dry_mass=54.0, fuel_mass=16.0,
        length=4.8, diameter=0.52, engine="rocket",
        exhaust_velocity=2450.0, mdot=1.50, exit_area=0.010,
        exit_pressure=72_000.0, nozzle_z=-2.30,
        cg_z=-0.28, cg_z_dry=-0.15, cp_z=-1.15,
        cd0=0.65, cn_alpha=4.5, damp=12.0,
        fcs_kp=5.2, fcs_kd=1.8,
        gimbal_limit_rad=math.radians(18.0),
        gimbal_rate_rad_s=math.radians(120.0),
        controller="returner", rcs_torque=900.0,
        rcs_kp=1200.0, rcs_kd=320.0,
    )
    body = SixDofBody(d)
    body.autopilot_on = True
    body.rcs_hold_on = True
    return body


def make_gyro_gimbal() -> "SixDofBody":
    """The spin-dart/TVC hybrid: an unstable core with canted roll jets and
    a rate-limited two-axis gimbal. Either stabilizer can be disabled live."""
    d = SixDofDef(
        name="GYRO-GIMBAL", dry_mass=24.0, fuel_mass=12.0,
        length=2.7, diameter=0.24, engine="rocket",
        exhaust_velocity=2050.0, mdot=0.62, exit_area=0.004,
        exit_pressure=76_000.0, nozzle_z=-1.30,
        cg_z=-0.12, cg_z_dry=-0.04, cp_z=0.18,
        cd0=0.55, cn_alpha=4.8, damp=7.0, damp_roll=0.012,
        spin_cant_rad=math.radians(2.0), spin_arm=0.10,
        fcs_kp=3.8, fcs_kd=1.0,
        gimbal_limit_rad=math.radians(10.0),
        gimbal_rate_rad_s=math.radians(100.0),
        misalign_rad=math.radians(2.5),
        airbrake_drag_mult=1.8, airbrake_damp_mult=4.0,
    )
    return SixDofBody(d)


def make_flip_brake() -> "SixDofBody":
    """Unpowered high-alpha re-entry article with deployable drag petals.
    Deployment increases projected drag and shifts the aerodynamic load aft."""
    d = SixDofDef(
        name="FLIP BRAKE", dry_mass=44.0, fuel_mass=6.0,
        length=3.2, diameter=0.42, engine="rocket",
        exhaust_velocity=2100.0, mdot=0.42, exit_area=0.005,
        exit_pressure=70_000.0, nozzle_z=-1.52,
        cg_z=-0.10, cg_z_dry=-0.04, cp_z=0.12,
        cd0=0.55, cn_alpha=4.0, damp=5.0,
        airbrake_drag_mult=5.5, airbrake_damp_mult=5.0,
        airbrake_cp_z=-1.20,
    )
    return SixDofBody(d)


def make_rcs_needle() -> "SixDofBody":
    """Thin-air attitude demonstrator. Four reaction jets produce real body
    torque even at zero airspeed; no gimballed main engine is fitted."""
    d = SixDofDef(
        name="RCS NEEDLE", dry_mass=20.0, fuel_mass=5.0,
        length=2.5, diameter=0.20, engine="rocket",
        exhaust_velocity=1900.0, mdot=0.28, exit_area=0.0025,
        exit_pressure=55_000.0, nozzle_z=-1.20,
        cg_z=-0.08, cg_z_dry=-0.02, cp_z=-0.38,
        cd0=0.48, cn_alpha=3.8, damp=4.5, damp_roll=0.01,
        rcs_torque=48.0, rcs_kp=62.0, rcs_kd=18.0,
    )
    body = SixDofBody(d)
    body.rcs_hold_on = True
    return body


def make_pulse_lander() -> "SixDofBody":
    """A throttleless lander. Its controller can only request full thrust or
    zero thrust, pulse-width-modulating a fixed motor to climb and hover."""
    wet = 46.0
    d = SixDofDef(
        name="PULSE LANDER", dry_mass=32.0, fuel_mass=wet - 32.0,
        length=2.9, diameter=0.48, engine="rocket",
        exhaust_velocity=1900.0, mdot=0.42, exit_area=0.005,
        exit_pressure=70_000.0, nozzle_z=-1.38,
        cg_z=-0.18, cg_z_dry=-0.08, cp_z=-0.82,
        cd0=0.80, cn_alpha=4.8, damp=11.0,
        fcs_kp=4.0, fcs_kd=1.2,
        gimbal_limit_rad=math.radians(7.0),
        gimbal_rate_rad_s=math.radians(80.0),
        controller="pulse_hover",
    )
    body = SixDofBody(d)
    body.autopilot_on = True
    body.target_altitude = 55.0
    return body


def configure_returner_scenario(body: "SixDofBody", index: int) -> None:
    """Place a Returner in one of three deterministic landing challenges."""
    scenarios = (
        ((160.0, 1200.0, -110.0), (-25.0, -150.0, 18.0),
         (0.65, -0.72, 0.25), (0.35, -0.20, 0.15)),
        ((-260.0, 1600.0, 180.0), (50.0, -175.0, -32.0),
         (-0.55, -0.70, 0.45), (-0.45, 0.30, -0.18)),
        ((130.0, 650.0, 210.0), (24.0, -105.0, -40.0),
         (0.25, -0.82, -0.52), (0.20, 0.40, -0.25)),
    )
    body.scenario_index = int(index) % len(scenarios)
    pos, vel, axis, omega = scenarios[body.scenario_index]
    body.pos[:] = pos
    body.vel[:] = vel
    body.set_attitude_axis(axis)
    body.omega[:] = omega
    body.on_ground = False
    body.engine_on = True
    body.throttle = 0.0
    body.autopilot_on = True
    body.rcs_hold_on = True
    body.controller_phase = "COAST"


def configure_flip_brake_scenario(body: "SixDofBody", index: int) -> None:
    """Deterministic high-energy entries for the deployable-brake article."""
    scenarios = (
        ((0.0, 1400.0, 0.0), (85.0, -105.0, 10.0),
         (0.92, 0.12, 0.37), (0.65, -0.35, 0.20)),
        ((0.0, 2600.0, 0.0), (-120.0, -155.0, 45.0),
         (-0.60, 0.18, 0.78), (-0.80, 0.25, 0.45)),
    )
    body.scenario_index = int(index) % len(scenarios)
    pos, vel, axis, omega = scenarios[body.scenario_index]
    body.pos[:] = pos
    body.vel[:] = vel
    body.set_attitude_axis(axis)
    body.omega[:] = omega
    body.on_ground = False
    body.engine_on = False
    body.throttle = 0.0
    body.airbrake_deployed = False


def configure_rcs_scenario(body: "SixDofBody", index: int) -> None:
    """Thin-air tumble where only reaction jets have useful authority."""
    scenarios = (
        ((0.0, 18_000.0, 0.0), (35.0, -35.0, 15.0),
         (0.80, 0.12, 0.58), (1.2, -0.9, 0.65)),
        ((0.0, 30_000.0, 0.0), (-70.0, -20.0, 25.0),
         (-0.35, -0.25, 0.90), (-1.4, 0.8, -0.55)),
    )
    body.scenario_index = int(index) % len(scenarios)
    pos, vel, axis, omega = scenarios[body.scenario_index]
    body.pos[:] = pos
    body.vel[:] = vel
    body.set_attitude_axis(axis)
    body.omega[:] = omega
    body.on_ground = False
    body.engine_on = False
    body.throttle = 0.0
    body.rcs_hold_on = True
    body.attitude_target_world = _UP.copy()


# --------------------------------------------------------------------------
# quaternion helpers (w, x, y, z)


def quat_to_mat(q: np.ndarray) -> np.ndarray:
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ])


def _quat_derivative(q: np.ndarray, omega_body: np.ndarray) -> np.ndarray:
    w, x, y, z = q
    ox, oy, oz = omega_body
    return 0.5 * np.array([
        -x * ox - y * oy - z * oz,
        w * ox + y * oz - z * oy,
        w * oy + z * ox - x * oz,
        w * oz + x * oy - y * ox,
    ])


# --------------------------------------------------------------------------
# the body


class SixDofBody:
    """One rigid body integrated at the fixed sim step. Deterministic."""

    def __init__(self, d: SixDofDef, ground_h: float = 0.0):
        self.d = d
        self.ground_h = float(ground_h)
        self.t = 0.0
        self.fuel = float(d.fuel_mass)
        self.throttle = 0.0
        self.engine_on = False
        self.gimbal = np.zeros(2)            # rad, pitch/yaw deflection
        # Sitting on the pad, nose up: body +Z -> world +Y.
        base_to_center = 0.5 * d.length
        self.pos = np.array([0.0, self.ground_h + base_to_center, 0.0])
        self.vel = np.zeros(3)
        self.quat = np.array([math.cos(math.pi / 4.0),
                              -math.sin(math.pi / 4.0), 0.0, 0.0])
        self.omega = np.zeros(3)             # body frame, rad/s
        self.on_ground = True
        # Mouse grab: a spring from a body-fixed point to a world target.
        self.grab_point_body = None      # (3,) body frame, None = no grab
        self.grab_target = None          # (3,) world pull target
        self.grab_force_n = 0.0          # live readout
        # Environment + flight control.
        self.wind = np.zeros(3)          # world m/s, uniform
        self.fcs_on = d.fcs_kp > 0.0     # articles with gains boot enabled
        self.fcs_target_mode = "UPRIGHT"
        self.attitude_target_world = _UP.copy()
        self.gimbal_jammed = False
        self.gimbal_authority = 1.0
        self.spin_enabled = d.spin_cant_rad != 0.0
        self.spin_direction = 1.0
        self.airbrake_deployed = False
        self.autopilot_on = d.controller != "none"
        self.controller_phase = "MANUAL"
        self.target_altitude = 50.0
        self.landing_target = np.array([0.0, self.ground_h, 0.0])
        self.rcs_hold_on = False
        self.rcs_pulse = np.zeros(3)
        self.rcs_pulse_left = 0.0
        self.scenario_index = 0
        self.touchdown_speed = 0.0
        # Live readouts refreshed each step (for HUD/tests/probes).
        self.thrust_n = 0.0
        self.weight_n = self.mass * GRAVITY
        self.alpha_rad = 0.0

    # ---------------------------------------------------------- properties

    @property
    def mass(self) -> float:
        return self.d.dry_mass + self.fuel

    def _cg_z(self) -> float:
        if self.d.fixed_mass:
            return self.d.cg_z
        f = self.fuel / self.d.fuel_mass if self.d.fuel_mass > 0 else 0.0
        return self.d.cg_z_dry + (self.d.cg_z - self.d.cg_z_dry) * f

    def _inertia(self) -> np.ndarray:
        """Solid-cylinder tensor in the body frame (diag, kg m^2)."""
        m, r, length = self.mass, 0.5 * self.d.diameter, self.d.length
        i_ax = 0.5 * m * r * r
        i_tr = m * (3.0 * r * r + length * length) / 12.0
        return np.array([i_tr, i_tr, i_ax])

    def body_axis_world(self) -> np.ndarray:
        return quat_to_mat(self.quat) @ np.array([0.0, 0.0, 1.0])

    def pitch_deg(self) -> float:
        """Angle of the nose above the horizon."""
        return math.degrees(math.asin(
            max(-1.0, min(1.0, float(self.body_axis_world()[1])))))

    def predicted_ceiling(self) -> float:
        """Fan hover ceiling h = H ln(T0/W) at the CURRENT mass."""
        if self.d.engine != "fan" or self.d.thrust_sl <= 0.0:
            return 0.0
        ratio = self.d.thrust_sl / (self.mass * GRAVITY)
        return SCALE_HEIGHT * math.log(ratio) if ratio > 1.0 else 0.0

    # ------------------------------------------------------------- engine

    def _full_thrust(self, alt: float) -> float:
        """Available thrust at full command, independent of ignition state."""
        if self.d.engine == "fan":
            return self.d.thrust_sl * air_density_scalar(alt) / RHO0
        return (self.d.mdot * self.d.exhaust_velocity
                + (self.d.exit_pressure - air_pressure_scalar(alt))
                * self.d.exit_area)

    def _thrust_magnitude(self, alt: float) -> float:
        if not self.engine_on or self.throttle <= 0.0:
            return 0.0
        if not self.d.fixed_mass and self.fuel <= 0.0:
            return 0.0
        # Throttle scales chamber pressure as well as mass flow. The previous
        # lab formula left the pressure term at 100% while deeply throttled.
        return self.throttle * self._full_thrust(alt)

    # ------------------------------------------------------------ guidance

    @staticmethod
    def _unit_or(vector, fallback) -> np.ndarray:
        vector = np.asarray(vector, dtype=np.float64)
        mag = float(np.linalg.norm(vector))
        if mag < 1e-9:
            return np.asarray(fallback, dtype=np.float64).copy()
        return vector / mag

    def _update_guidance(self, dt: float, alt: float) -> None:
        """Update commands only; forces still pass through physical actuators."""
        d = self.d
        if d.controller == "returner" and self.autopilot_on:
            rest_y = self.ground_h + 0.5 * d.length
            h = max(0.0, float(self.pos[1]) - rest_y)
            if self.on_ground and self.t > 0.25:
                self.engine_on = False
                self.throttle = 0.0
                miss = float(np.linalg.norm(
                    self.pos[[0, 2]] - self.landing_target[[0, 2]]))
                self.controller_phase = ("LANDED" if miss < 6.0
                                         and self.touchdown_speed < 4.0
                                         else "CRASHED")
                self.attitude_target_world = _UP.copy()
                return

            full = max(self._full_thrust(alt), 1.0)
            max_net_up = max(1.0, full / self.mass - GRAVITY)
            down_speed = max(0.0, -float(self.vel[1]))
            stop_distance = down_speed * down_speed / (2.0 * max_net_up)
            coast_margin = 45.0 + 0.04 * h

            # Horizontal outer loop: demand a bounded lateral acceleration
            # toward the pad while damping crossrange velocity.
            horizontal = self.pos[[0, 2]] - self.landing_target[[0, 2]]
            hvel = self.vel[[0, 2]]
            a_h = -0.10 * horizontal - 0.75 * hvel
            a_h_mag = float(np.linalg.norm(a_h))
            if a_h_mag > 14.0:
                a_h *= 14.0 / a_h_mag

            horizontal_distance = float(np.linalg.norm(horizontal))
            correction_height = 5.0 * horizontal_distance
            if h > max(stop_distance + coast_margin, correction_height) \
                    and down_speed > 8.0:
                throttle = 0.0
                self.controller_phase = "COAST"
                # Point mostly retrograde before ignition; RCS has time to
                # settle the body without receiving free translational force.
                target = _UP.copy()
            else:
                if h < 45.0 and horizontal_distance > 4.0:
                    # Deliberately hold above the pad until crossrange error
                    # is gone—the visible "hover, translate, then settle"
                    # phase requested for the reusable-booster demo.
                    v_des = max(-3.0, min(3.0, (28.0 - h) * 0.35))
                    self.controller_phase = "PAD ACQUIRE"
                elif h < 12.0:
                    v_des = -max(0.22, min(1.8, h * 0.16))
                    self.controller_phase = "HOVER / FINAL"
                else:
                    v_des = -min(58.0, math.sqrt(2.0 * 3.2 * h))
                    self.controller_phase = "BRAKE"
                specific_up = max(1.5, GRAVITY + 0.95 *
                                  (v_des - float(self.vel[1])))
                target = np.array([a_h[0], specific_up, a_h[1]])
                throttle = self.mass * float(np.linalg.norm(target)) / full
                throttle = max(0.0, min(1.0, throttle))

            self.attitude_target_world = self._unit_or(target, _UP)
            self.engine_on = True
            self.throttle = throttle
            self.rcs_hold_on = True
            return

        if d.controller == "pulse_hover" and self.autopilot_on:
            target_y = self.ground_h + 0.5 * d.length + self.target_altitude
            error = target_y - float(self.pos[1])
            full = max(self._full_thrust(alt), 1.0)
            desired_specific = GRAVITY + 0.36 * error - 0.95 * float(self.vel[1])
            duty = max(0.0, min(1.0, self.mass * desired_specific / full))
            period = 0.32
            firing = (self.t % period) < duty * period
            self.engine_on = firing
            self.throttle = 1.0 if firing else 0.0
            self.attitude_target_world = _UP.copy()
            self.controller_phase = f"PWM {duty:03.0%}"
            return

        # Manual TVC target selections.
        if self.fcs_target_mode == "PROGRADE":
            self.attitude_target_world = self._unit_or(self.vel, _UP)
        elif self.fcs_target_mode == "LEAN 12 DEG":
            a = math.radians(12.0)
            self.attitude_target_world = np.array([math.sin(a), math.cos(a), 0.0])
        else:
            self.attitude_target_world = _UP.copy()

    # --------------------------------------------------------------- step

    def step(self, dt: float) -> None:
        d = self.d
        m = self.mass
        alt = float(self.pos[1])
        self._update_guidance(dt, alt)
        rot = quat_to_mat(self.quat)
        axis = rot @ np.array([0.0, 0.0, 1.0])
        cg = self._cg_z()

        force = np.array([0.0, -GRAVITY * m, 0.0])
        torque = np.zeros(3)                 # body frame
        damping_coeff = np.zeros(3)          # N m s, integrated exactly

        # -- thrust at the nozzle --------------------------------------
        thrust = self._thrust_magnitude(alt)
        self.thrust_n = thrust
        self.weight_n = m * GRAVITY

        # -- TVC flight computer: PD attitude hold through a real gimbal --
        # (gimbal deflection is rate-limited and saturates: an actuator,
        # not an oracle. Switch it off mid-flight and the same airframe
        # departs — that IS the demo.)
        if self.fcs_on and d.fcs_kp > 0.0 and thrust > 0.0 \
                and not self.gimbal_jammed:
            target_b = rot.T @ self.attitude_target_world
            # Rotation axis (body) taking the nose onto the target vector.
            ex, ey = -float(target_b[1]), float(target_b[0])
            gp_cmd = d.fcs_kp * ex - d.fcs_kd * float(self.omega[0])
            gy_cmd = -(d.fcs_kp * ey - d.fcs_kd * float(self.omega[1]))
            lim = d.gimbal_limit_rad * self.gimbal_authority
            rate = d.gimbal_rate_rad_s * dt
            for i, cmd in ((0, gp_cmd), (1, gy_cmd)):
                cmd = max(-lim, min(lim, cmd))
                cur = float(self.gimbal[i])
                self.gimbal[i] = cur + max(-rate, min(rate, cmd - cur))

        if thrust > 0.0:
            gp = float(self.gimbal[0]) + d.misalign_rad
            gy = float(self.gimbal[1])
            # Nozzle points thrust along body +Z, deflected in the body
            # x/y planes (small-angle exact via trig).
            dir_body = np.array([math.sin(gy),
                                 math.sin(gp) * math.cos(gy),
                                 math.cos(gp) * math.cos(gy)])
            force += rot @ (thrust * dir_body)
            r_body = np.array([0.0, 0.0, d.nozzle_z - cg])
            torque += np.cross(r_body, thrust * dir_body)
            if self.spin_enabled and d.spin_cant_rad != 0.0:
                # Canted nozzles: a roll moment for as long as it burns.
                torque[2] += (self.spin_direction * thrust
                              * math.sin(abs(d.spin_cant_rad)) * d.spin_arm)
            if not d.fixed_mass:
                rate = d.fuel_rate if d.engine == "fan" else d.mdot
                self.fuel = max(0.0, self.fuel - rate * self.throttle * dt)

        # -- aerodynamics at the CP (wind-relative) --------------------
        v_rel = self.vel - self.wind
        speed = float(np.linalg.norm(v_rel))
        rho = air_density_scalar(alt)
        self.alpha_rad = 0.0
        if speed > 0.5:
            v_hat = v_rel / speed
            q_bar = 0.5 * rho * speed * speed
            cos_a = max(-1.0, min(1.0, float(axis @ v_hat)))
            alpha = math.acos(cos_a)
            self.alpha_rad = alpha
            # Drag uses the actual projected area. The previous model kept
            # using only the tiny nose-on area when a rocket was broadside,
            # so a spent/tumbling stick could loop for minutes as if it were
            # a lossless wing. Side area supplies the missing high-alpha drag.
            sin_a = math.sin(alpha)
            projected_area = (d.ref_area * abs(cos_a)
                              + d.length * d.diameter * abs(sin_a))
            brake_drag = d.airbrake_drag_mult if self.airbrake_deployed else 1.0
            f_drag = -v_hat * q_bar * projected_area * d.cd0 * brake_drag
            force += f_drag
            # Normal force in the axis/flow plane, perpendicular to the
            # flow, pushing the body the way the nose leans (small-alpha:
            # the crossflow shoves the airframe sideways at the CP; with
            # the CP aft of the CG that torque weathercocks the nose back
            # into the wind).
            n_dir = axis - cos_a * v_hat
            n_norm = float(np.linalg.norm(n_dir))
            if n_norm > 1e-9 and alpha > 1e-6:
                n_dir = n_dir / n_norm
                # Cn_alpha * alpha is a small-angle law, not a valid 0..180
                # degree law. sin(2a)/2 preserves the linear slope near zero,
                # stalls at 45 degrees, and cannot invent huge lift backwards.
                cn = 0.5 * d.cn_alpha * math.sin(2.0 * alpha)
                f_normal = n_dir * (q_bar * d.ref_area * cn)
                force += f_normal
                r_body = np.array([0.0, 0.0, self.current_cp_z() - cg])
                # The normal load acts at CP and supplies static stability.
                # Axial drag is kept through the axis: applying its tiny
                # numerical off-axis residue at CP makes a perfectly vertical
                # hover flip at the apex for no physical disturbance.
                torque += np.cross(r_body, rot.T @ f_normal)
            # Rotational damping (needs airflow to bite); roll has its
            # own, far smaller, derivative on slender bodies.
            scale = (q_bar * d.ref_area * d.length * d.length
                     / max(speed, 20.0))
            brake_damp = (d.airbrake_damp_mult
                          if self.airbrake_deployed else 1.0)
            damping_coeff = (scale * brake_damp
                             * np.array([d.damp, d.damp, d.roll_damp]))

        # -- reaction-control jets: bounded torque, no atmosphere needed --
        if d.rcs_torque > 0.0:
            if self.rcs_hold_on:
                target_b = rot.T @ self.attitude_target_world
                error = np.array([-float(target_b[1]),
                                  float(target_b[0]), 0.0])
                rcs_cmd = d.rcs_kp * error - d.rcs_kd * self.omega
                mag = float(np.linalg.norm(rcs_cmd))
                if mag > d.rcs_torque:
                    rcs_cmd *= d.rcs_torque / mag
                torque += rcs_cmd
            if self.rcs_pulse_left > 0.0:
                pulse = self.rcs_pulse.copy()
                mag = float(np.linalg.norm(pulse))
                if mag > 1e-9:
                    torque += pulse / mag * d.rcs_torque
                self.rcs_pulse_left = max(0.0, self.rcs_pulse_left - dt)

        # -- mouse disturbance: force couple, hence torque but no lift --
        self.grab_force_n = 0.0
        if self.grab_point_body is not None and self.grab_target is not None:
            r_arm = self.grab_point_body - np.array([0.0, 0.0, cg])
            r_world = rot @ r_arm
            p_grab = self.pos + r_world
            v_grab = self.vel + rot @ np.cross(self.omega, r_arm)
            f = (GRAB_KP * (self.grab_target - p_grab) - GRAB_KD * v_grab)
            f_mag = float(np.linalg.norm(f))
            if f_mag > GRAB_MAX_N:
                f *= GRAB_MAX_N / f_mag
                f_mag = GRAB_MAX_N
            self.grab_force_n = f_mag
            # Equal and opposite force at the CG cancels translation. The
            # displayed force still has a real lever arm and real torque.
            torque += np.cross(r_arm, rot.T @ f)

        # -- integrate (semi-implicit Euler) ---------------------------
        self.vel += force / m * dt
        self.pos += self.vel * dt
        inertia = self._inertia()
        # Rotation update. The body is always axisymmetric
        # (I = diag(It, It, Ia)), so the gyroscopic term has an EXACT
        # solution: the transverse rate vector rotates in the body frame
        # at lambda = w_z (Ia - It)/It. Explicit Euler on w x Iw pumps
        # energy and blows up for a fast-spinning dart; the closed form
        # is unconditionally stable. Applied torque integrates
        # explicitly; substeps keep the quaternion update accurate at
        # high spin. Deterministic.
        n_sub = 1 + min(7, int(float(np.linalg.norm(self.omega))
                               * dt / 0.2))
        sdt = dt / n_sub
        i_tr, i_ax = float(inertia[0]), float(inertia[2])
        for _ in range(n_sub):
            lam = float(self.omega[2]) * (i_ax - i_tr) / i_tr
            c, s = math.cos(lam * sdt), math.sin(lam * sdt)
            wx, wy = float(self.omega[0]), float(self.omega[1])
            self.omega[0] = wx * c - wy * s
            self.omega[1] = wx * s + wy * c
            self.omega += (torque / inertia) * sdt
            # Linear aero-rate damping has the exact solution
            # w(t+dt)=w(t)*exp(-k/I*dt). Explicit Euler was unstable whenever
            # the roll time constant fell below one 120 Hz tick, turning a
            # harmless tumble into infinite angular velocity.
            self.omega *= np.exp(-damping_coeff / inertia * sdt)
            self.quat += _quat_derivative(self.quat, self.omega) * sdt
            self.quat /= np.linalg.norm(self.quat)

        # -- ground contact (launch-stand behavior) --------------------
        axis_y = float(axis[1])
        radial_y = math.sqrt(max(0.0, 1.0 - axis_y * axis_y))
        vertical_extent = (0.5 * d.length * abs(axis_y)
                           + 0.5 * d.diameter * radial_y)
        base_alt = float(self.pos[1]) - vertical_extent
        if base_alt <= self.ground_h + 1e-9 and self.vel[1] <= 0.0:
            if not self.on_ground:
                self.touchdown_speed = float(np.linalg.norm(self.vel))
            self.pos[1] = self.ground_h + vertical_extent
            if self.grab_point_body is None:
                self.vel[:] = 0.0
                self.omega[:] = 0.0
            else:
                # Grabbed on the pad: support it, but let pulls slide and
                # topple it instead of bolting it down.
                self.vel[1] = 0.0
            self.on_ground = True
        else:
            self.on_ground = False

        self.t += dt

    # ------------------------------------------------------------ control

    def set_grab(self, point_body, target_world) -> None:
        """Attach the mouse spring at a body-frame point."""
        self.grab_point_body = np.asarray(point_body, dtype=np.float64)
        self.grab_target = np.asarray(target_world, dtype=np.float64)

    def move_grab(self, target_world) -> None:
        if self.grab_point_body is not None:
            self.grab_target = np.asarray(target_world, dtype=np.float64)

    def clear_grab(self) -> None:
        self.grab_point_body = None
        self.grab_target = None
        self.grab_force_n = 0.0

    def grab_point_world(self):
        """World position of the grabbed body point (None when no grab)."""
        if self.grab_point_body is None:
            return None
        r_arm = self.grab_point_body - np.array([0.0, 0.0, self._cg_z()])
        return self.pos + quat_to_mat(self.quat) @ r_arm

    def body_point_world(self, z_body: float) -> np.ndarray:
        """World position of an axial body station measured from its center."""
        return self.pos + quat_to_mat(self.quat) @ np.array(
            [0.0, 0.0, float(z_body) - self._cg_z()])

    def nozzle_world(self) -> np.ndarray:
        return self.body_point_world(self.d.nozzle_z)

    def cg_world(self) -> np.ndarray:
        return self.pos.copy()

    def cp_world(self) -> np.ndarray:
        return self.body_point_world(self.current_cp_z())

    def thrust_direction_world(self) -> np.ndarray:
        """Direction of force on the vehicle, including gimbal/misalignment."""
        gp = float(self.gimbal[0]) + self.d.misalign_rad
        gy = float(self.gimbal[1])
        direction_body = np.array([math.sin(gy),
                                   math.sin(gp) * math.cos(gy),
                                   math.cos(gp) * math.cos(gy)])
        return quat_to_mat(self.quat) @ direction_body

    def current_cp_z(self) -> float:
        if self.airbrake_deployed and self.d.airbrake_cp_z is not None:
            return float(self.d.airbrake_cp_z)
        return float(self.d.cp_z)

    def ignite(self) -> None:
        self.engine_on = True
        if self.throttle <= 0.0:
            self.throttle = 1.0

    def cutoff(self) -> None:
        self.engine_on = False

    def pulse_rcs(self, axis_body, duration: float = 0.22) -> None:
        """Fire a bounded reaction jet pulse along a body-torque axis."""
        if self.d.rcs_torque <= 0.0:
            return
        self.rcs_pulse = np.asarray(axis_body, dtype=np.float64)
        self.rcs_pulse_left = max(0.0, float(duration))

    def nudge_gimbal(self, pitch_delta: float = 0.0,
                     yaw_delta: float = 0.0) -> bool:
        """Move the TVC actuator by hand while attitude hold is disabled."""
        if self.d.gimbal_limit_rad <= 0.0 or self.fcs_on \
                or self.gimbal_jammed:
            return False
        limit = self.d.gimbal_limit_rad * self.gimbal_authority
        self.gimbal[0] = max(-limit, min(
            limit, float(self.gimbal[0]) + float(pitch_delta)))
        self.gimbal[1] = max(-limit, min(
            limit, float(self.gimbal[1]) + float(yaw_delta)))
        return True

    def set_attitude_axis(self, direction_world) -> None:
        """Set scenario attitude so body +Z points along a world vector."""
        target = self._unit_or(direction_world, _UP)
        source = np.array([0.0, 0.0, 1.0])
        dot = max(-1.0, min(1.0, float(source @ target)))
        if dot < -0.999999:
            self.quat[:] = (0.0, 1.0, 0.0, 0.0)
            return
        cross = np.cross(source, target)
        q = np.array([1.0 + dot, cross[0], cross[1], cross[2]])
        self.quat[:] = q / np.linalg.norm(q)

    def state_repr(self) -> str:
        """Byte-stable digest string for determinism tests."""
        return repr((self.t, self.pos.tobytes(), self.vel.tobytes(),
                     self.quat.tobytes(), self.omega.tobytes(), self.fuel))
