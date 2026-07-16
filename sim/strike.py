"""StrikeMissile / HarmMissile: enemy strike weapons phase machines.

Covers:
  StrikeMissile — base class for Tomahawk-class and JASSM-class cruise
    missiles.  Phases:
      EJECT  — VLS vertical eject / air-drop free-fall (no guidance)
      BOOST  — booster burn with pitch-over toward cruise heading
      CLIMB  — altitude capture toward cruise_alt using altitude-hold PD
      CRUISE — terrain-following at cruise_alt AGL toward target
      TERMINAL — horizontal range < TERMINAL_RANGE_M: shallow dive
      DEAD   — post-impact or fuel exhaustion below sea level

  HarmMissile — anti-radiation missile.  Extends StrikeMissile with a
    loft profile and passive radar homing: homes on an emitting Radar
    object with proportional navigation; if the radar goes silent it
    freezes the last-known aim point and adds a deterministic miss
    offset drawn from a seeded Generator (CEP-degraded: 150-400 m ring);
    re-locks the live radar position when it re-emits.

Duck-type contract (what game/sandbox.py _draw_missiles / _missile_effects
/ _loop_sources reads from each missile in world.missiles):
  pos         (3,) float64, world position
  vel         (3,) float64, world velocity
  body_dir    (3,) float64 optional body attitude (getattr fallback to vel)
  alive       bool
  phase       int -- must NOT be in sim.missile.CAP_ON_PHASES (PH_EJECT /
              PH_RIDEOUT / PH_PITCHOVER) nor SPH_EJECT / SPH_BOOST.
              The render layer checks isinstance(m, SamMissile) first so
              StrikeMissile instances fall through to the Oniks mesh
              (placeholder until Phase 4 adds dedicated models).
  prev_pos    (3,) float64, position at start of last step (damage sweep)
  impact_pos  (3,) float64 or None -- set on ground impact or fuse kill

Integration duck-type (COMBAT Phase 3, world/combat.py + sim/contacts.py):
  is_hostile  True (class attr): sim/bases.apply_missile_hits_structures is
              fed only hostile rounds, so a player Oniks overflying its own
              TEL can never demolish the base. Missile/SamMissile default
              False via getattr.
  is_air      True (class attr): the gated ContactBoard treats a strike
              missile like an air entity (fast refresh cadence).
  radar_size  "missile" (class attr): ContactBoard._seen passes this size
              class to the radar gate, so the player radar's 120 km missile
              ring applies instead of the 350 km fighter ring.
  aircraft_id str (property): the board's track id for this round.

Axes: X east, Y up, Z north (locked conventions).  All SI float64.
Physics: semi-implicit Euler at the 120 Hz fixed step.
"""

from __future__ import annotations

import math

import numpy as np

from sim.aero import (ALPHA_TAX, AP_TAU_STRIKE, CL_MAX_STRIKE, QS_FLOOR,
                      autopilot_step_scalar, lag_gain,
                      project_perpendicular_scalar, q_scalar)
from sim.guidance import (STEER_GAIN, STEER_MAX_A,
                          altitude_hold_accel, pn_accel)
from sim.flight_computer import (AirframeEnvelope, FlightMode, FlightState,
                                 MissionSnapshot, OnlineFlightComputer)
from sim.physics import (GRAVITY, cd_from_mach_scalar, drag_force_scalar,
                         mach_scalar)

# ---------------------------------------------------------------------------
# Phase constants (above sim.missile 0-8 and sim.sam 0-4 ranges)
# ---------------------------------------------------------------------------
SPH_STRIKE_EJECT    = 20   # VLS eject / air-drop free-fall
SPH_STRIKE_BOOST    = 21   # booster burn with pitch-over (VLS only)
SPH_STRIKE_CLIMB    = 22   # altitude capture to cruise_alt
SPH_STRIKE_CRUISE   = 23   # terrain-following cruise
SPH_STRIKE_TERMINAL = 24   # shallow dive onto target
SPH_STRIKE_DEAD     = 25   # post-impact / fuel exhaustion

PHASE_LABELS = {
    SPH_STRIKE_EJECT:    "EJECT",
    SPH_STRIKE_BOOST:    "BOOST",
    SPH_STRIKE_CLIMB:    "CLIMB",
    SPH_STRIKE_CRUISE:   "CRUISE",
    SPH_STRIKE_TERMINAL: "TERMINAL",
    SPH_STRIKE_DEAD:     "DEAD",
}

# ---------------------------------------------------------------------------
# Tuning constants (research-grounded where documented)
# ---------------------------------------------------------------------------

# Altitude-hold PD gains for terrain-following cruise.  kd ~ 2*sqrt(kp) is
# near-critically damped.  Max accel 30 m/s^2 is sufficient to pull a slow
# turbofan cruise missile up from ground-hugging to 50 m AGL without
# excessive ballooning.
CRUISE_ALT_KP = 0.40     # 1/s^2
CRUISE_ALT_KD = 1.26     # 1/s  (~2*sqrt(0.4) = 1.265)
CRUISE_ALT_MAX_A = 30.0  # m/s^2

# Heading-steer gains (same as sim/guidance.py exported constants).
_STEER_GAIN = STEER_GAIN   # 2.2  1/s
_STEER_MAX_A = STEER_MAX_A  # 60.0 m/s^2

# Climb: transition to CRUISE when this fraction of cruise_alt is reached.
CLIMB_TO_CRUISE_FRAC = 0.92

# Terminal phase: begin shallow dive when horizontal range < this value.
TERMINAL_RANGE_M = 8_000.0   # m (spec §8: "horizontal distance < 8 km")

# Two-stage TLAM-style terminal (integration fix, COMBAT Phase 3): inside
# TERMINAL the missile HOLDS the terrain-following deck until this commit
# range, then flies pure PN onto the aim point. A straight PN run from the
# full 8 km arming range dies on any coastal ridge that crosses the sight
# line — measured on the Phase 3 map: the player radar station (ground
# 144 m ASL) hides behind a 159 m crest 2.5 km out on the destroyer
# approach bearing, so a sea-skimmer committing at 8 km impacts the crest
# every time. Committing at 2 km is past that crest while leaving ~8 s of
# PN convergence at Mach 0.74 (~250 m/s) — ample for the < 2 deg path bend.
TERMINAL_COMMIT_RANGE_M = 2_000.0   # m

# Terminal dive target altitude: a point well below ground so the PD
# drives the nose down and the missile hits the surface.
TERMINAL_DIVE_ALT = -200.0   # m (below ground — ensures PD commands descent)

# Terrain-slope lookahead for the altitude-hold AGL correction.
TERRAIN_LOOKAHEAD = 500.0    # m

# Speed controller: thrust = clip(KP*(target_mach - mach)*SCALE + drag_ff,
# 0, max_thrust).  Drag feedforward removes steady-state error; the gain
# multiplied by THRUST_SCALE produces a large P-term that saturates to
# max_thrust immediately, giving maximum acceleration until cruise Mach is
# reached.  Same pattern as sim/missile.py.
KP_THRUST = 1.0
THRUST_SCALE = 1.0e5   # N per Mach of error — large enough to saturate

# Minimum speed for control authority (below this a subsonic missile sinks).
STALL_SPEED = 60.0     # m/s

# VLS booster pitch-over: after the cold-gas eject beat the solid booster
# fires and pitch-control vanes tip the missile from vertical toward the
# cruise heading.  Rate chosen so a 12 s booster has the missile nearly
# horizontal by burnout (90 deg / 6 s = 15 deg/s).  Using 20 deg/s so
# there is margin even if the booster runs short.
BOOST_PITCH_RATE = math.radians(20.0)   # rad/s path rotation toward horizontal

# HARM miss-offset ring when target radar goes silent (spec §8).
HARM_MISS_MIN_M = 150.0   # m
HARM_MISS_MAX_M = 400.0   # m


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _surface_at(world, x: float, z: float) -> float:
    """Surface height (max of terrain and sea level 0)."""
    f = getattr(world, "surface_height_at", None)
    if f is not None:
        return f(x, z)
    return max(float(world.terrain_height_at(x, z)), 0.0)


def _steer_scalar(vx: float, vz: float, desired_heading: float):
    """Heading-hold lateral accel (x, z) components, plain floats."""
    horiz_speed = math.hypot(vx, vz)
    if horiz_speed < 1e-9:
        return 0.0, 0.0
    heading = math.atan2(vx, vz)
    err = (desired_heading - heading + math.pi) % (2.0 * math.pi) - math.pi
    a_lat = _STEER_GAIN * err * horiz_speed
    a_lat = min(max(a_lat, -_STEER_MAX_A), _STEER_MAX_A)
    s = a_lat / horiz_speed
    return vz * s, -vx * s


def _rotate_toward_scalar(hx, hy, hz, dx, dy, dz, max_angle):
    """Rodrigues rotation: rotate unit (hx,hy,hz) toward (dx,dy,dz) by
    at most max_angle radians.  Plain floats (same as sim/sam.py)."""
    c = hx * dx + hy * dy + hz * dz
    c = min(max(c, -1.0), 1.0)
    angle = math.acos(c)
    if angle <= max_angle or angle < 1e-12:
        return dx, dy, dz
    ax = hy * dz - hz * dy
    ay = hz * dx - hx * dz
    az = hx * dy - hy * dx
    n = math.sqrt(ax * ax + ay * ay + az * az)
    if n < 1e-12:
        ax, ay, az = (1.0, 0.0, 0.0) if abs(hx) < 0.9 else (0.0, 1.0, 0.0)
        d = ax * hx + ay * hy + az * hz
        ax, ay, az = ax - hx * d, ay - hy * d, az - hz * d
        n = math.sqrt(ax * ax + ay * ay + az * az)
    ax, ay, az = ax / n, ay / n, az / n
    s, co = math.sin(max_angle), math.cos(max_angle)
    k = (1.0 - co) * (ax * hx + ay * hy + az * hz)
    return (hx * co + (ay * hz - az * hy) * s + ax * k,
            hy * co + (az * hx - ax * hz) * s + ay * k,
            hz * co + (ax * hy - ay * hx) * s + az * k)


# ---------------------------------------------------------------------------
# StrikeMissile
# ---------------------------------------------------------------------------

class StrikeMissile:
    """Phase-machine cruise missile for Tomahawk-class and JASSM-class.

    Parameters
    ----------
    weapon : StrikeDef
        Arsenal definition (sim.arsenal.TOMAHAWK / JASSM).
    pos_f64 : array-like (3,)
        World-space launch / release position (m).
    vel_f64 : array-like (3,)
        Initial velocity at the start of the EJECT phase.
        - VLS (Tomahawk): (0, eject_speed, 0) — vertical.
        - Air-drop (JASSM): aircraft release velocity vector.
    target_xz : (float, float)
        (x, z) ground target coordinates (m).
    target_y : float
        Terminal aim altitude ASL (m). 0.0 = sea-level target (default,
        ships/coastal points). Structures standing on elevated terrain MUST
        pass their mid-height here: terminal PN flies a straight line onto
        the aim point, so aiming at y=0 under a target on the 150 m coastal
        shelf would ground the missile kilometres short, while mid-height
        maximizes the swept-segment crossing of the structure OBB.
    """

    # COMBAT Phase 3 integration flags (see module docstring): every strike
    # missile in the sim is enemy-launched, feeds the player picture as an
    # air contact and is gated at the radar's missile-class range.
    is_hostile = True
    is_air = True
    radar_size = "missile"
    # Phase 8 launch-warning: Tomahawk/JASSM/HARM are radar-gated — the player
    # only sees them once the radar physically detects them. SM-2 and AIM-9X
    # override this to True (seen the instant they fire).
    launch_warning = False

    def __init__(self, weapon, pos_f64, vel_f64, target_xz, target_y=0.0):
        self.weapon = weapon
        self.pos = np.asarray(pos_f64, dtype=np.float64).copy()
        self.prev_pos = self.pos.copy()
        self.vel = np.asarray(vel_f64, dtype=np.float64).copy()
        self.target_x = float(target_xz[0])
        self.target_z = float(target_xz[1])
        self.target_y = float(target_y)
        # body_dir for the render layer (optional duck-type; fallback to vel).
        self.body_dir = np.array([0.0, 0.0, 1.0], dtype=np.float64)
        self.phase = SPH_STRIKE_EJECT
        self.t = 0.0
        self.fuel = float(weapon.fuel_mass)
        self.alive = True
        self.impact_pos = None
        # Phase timing accumulators.
        self._eject_elapsed = 0.0
        self._boost_elapsed = 0.0
        # Determine if this is a VLS-style (no initial horizontal speed)
        # or air-launched (has horizontal speed already).
        horiz_speed = math.hypot(float(self.vel[0]), float(self.vel[2]))
        self._is_vls = (horiz_speed < 5.0 and weapon.booster_thrust > 0.0)
        # Track whether we launched ABOVE cruise_alt (JASSM from high alt)
        # so the CLIMB->CRUISE transition waits until we have descended.
        self._launched_above_cruise = (
            float(self.pos[1]) > weapon.cruise_alt * 2.0)
        # Energy model (sim/aero.py, plan 2026-07-05): guided-phase accel is
        # q-limited, autopilot-lagged, and charged as induced drag; the
        # cruise engine spools on thrust_tau.
        self._cl_max = (weapon.cl_max if weapon.cl_max > 0.0
                        else CL_MAX_STRIKE)
        self._k_ind = (weapon.k_induced if weapon.k_induced > 0.0
                       else ALPHA_TAX / self._cl_max)
        self._ap_tau = (weapon.autopilot_tau if weapon.autopilot_tau > 0.0
                        else AP_TAU_STRIKE)
        self._thrust_tau = weapon.thrust_tau
        self._ap_x = self._ap_y = self._ap_z = 0.0  # achieved-accel lag state
        self._thrust_act = 0.0                      # spooled cruise thrust
        fc_family = ("arm" if str(weapon.weapon_id) in ("harm", "kh31p")
                     else "strike")
        self._fc = OnlineFlightComputer(
            AirframeEnvelope.from_weapon(weapon, fc_family))
        self._fc_command = None

    # --- duck-type properties ------------------------------------------------

    @property
    def mass(self) -> float:
        return self.weapon.launch_mass - (self.weapon.fuel_mass - self.fuel)

    @property
    def phase_label(self) -> str:
        return PHASE_LABELS.get(self.phase, "---")

    @property
    def aircraft_id(self) -> str:
        """ContactBoard track id (is_air entities key on aircraft_id).
        Stable for the object's lifetime — exactly what the board needs."""
        return f"strike_{id(self):x}"

    def velocity(self):
        """World-space velocity (3,) float64 — shared targetable duck-type."""
        return self.vel

    # --- helpers -------------------------------------------------------------

    def _dist_to_target(self) -> float:
        tx, _ty, tz = self._flight_target_point()
        dx = self.pos[0] - tx
        dz = self.pos[2] - tz
        return math.hypot(dx, dz)

    def _route_heading(self) -> float:
        tx, _ty, tz = self._flight_target_point()
        return math.atan2(tx - self.pos[0], tz - self.pos[2])

    def _flight_target_point(self):
        """Numeric target supplied to the entity-free flight computer."""
        return self.target_x, self.target_y, self.target_z

    def _flight_computer_step(self, dt, world):
        tx, ty, tz = self._flight_target_point()
        state = FlightState(
            pos=(float(self.pos[0]), float(self.pos[1]), float(self.pos[2])),
            vel=(float(self.vel[0]), float(self.vel[1]), float(self.vel[2])),
            mass_kg=float(self.mass), fuel_kg=float(self.fuel),
            thrust_actual_n=float(self._thrust_act), time_s=float(self.t))
        surface_at_target = _surface_at(world, float(tx), float(tz))
        is_arm = str(self.weapon.weapon_id) in ("harm", "kh31p")
        handover_alt = (float(ty) + math.tan(math.radians(25.0))
                        * TERMINAL_RANGE_M if is_arm else
                        surface_at_target + float(self.weapon.cruise_alt))
        mission = MissionSnapshot(
            path_xz=((float(tx), float(tz)),),
            target_y_m=float(ty),
            terminal_handover_alt_m=handover_alt,
            allow_high=is_arm,
            terminal_armed=True,
            terminal_latched=self.phase == SPH_STRIKE_TERMINAL,
            terminal_commit_max_m=TERMINAL_RANGE_M)
        self._fc_command = self._fc.update(
            dt, state, mission,
            lambda x, z: _surface_at(world, x, z))
        return self._fc_command

    def _online_midcourse_guidance(self, speed: float, vx: float,
                                   vy: float, vz: float, dt: float,
                                   world) -> tuple:
        """Follow the cached online plan with the 120 Hz inner loop."""
        gx, gz = _steer_scalar(vx, vz, self._route_heading())
        gy = 0.0
        command = self._fc_command
        if command is None:
            command = self._flight_computer_step(dt, world)

        hspeed = math.hypot(vx, vz)
        if speed > 1e-9 and hspeed > 1e-9:
            gamma = math.atan2(vy, hspeed)
            # FlightCommand carries kinematic path-normal acceleration;
            # the executor supplies the normal lift needed against gravity.
            lift_n = (command.path_normal_accel_mps2
                      + GRAVITY * math.cos(gamma))
            nx = -vx * vy / (speed * hspeed)
            ny = hspeed / speed
            nz = -vz * vy / (speed * hspeed)
            gx += nx * lift_n
            gy += ny * lift_n
            gz += nz * lift_n
        return gx, gy, gz

    def _skim_ref(self, alt: float, vs: float, world) -> tuple:
        """AGL altitude and corrected vertical speed for terrain-following."""
        px, pz = float(self.pos[0]), float(self.pos[2])
        s0 = _surface_at(world, px, pz)
        vx, vz = float(self.vel[0]), float(self.vel[2])
        hspeed = math.hypot(vx, vz)
        if hspeed < 1e-9:
            return alt - s0, vs
        scale = TERRAIN_LOOKAHEAD / hspeed
        s1 = _surface_at(world, px + vx * scale, pz + vz * scale)
        return alt - s0, vs - (s1 - s0) / TERRAIN_LOOKAHEAD * hspeed

    def _cruise_thrust(self, m_now: float, drag_ff: float, dt: float) -> float:
        """Mach-hold thrust (P + drag feedforward); burns cruise fuel."""
        if self.fuel <= 0.0:
            return 0.0
        w = self.weapon
        target_mach = (self._fc_command.target_mach
                       if self._fc_command is not None else w.cruise_mach)
        thrust = KP_THRUST * (target_mach - m_now) * THRUST_SCALE + drag_ff
        thrust = min(max(thrust, 0.0), w.max_thrust)
        if self._thrust_tau > 0.0:
            # Engine spool (energy model): turbofan/turbojet thrust cannot
            # step in one tick; fuel burns on the ACTUAL spooled thrust.
            self._thrust_act += ((thrust - self._thrust_act)
                                 * lag_gain(dt, self._thrust_tau))
            thrust = self._thrust_act
        self.fuel = max(0.0, self.fuel - thrust / (w.isp * GRAVITY) * dt)
        return thrust

    def _boost_thrust(self, dt: float) -> float:
        """Booster thrust; burns from fuel budget while booster_time lasts."""
        w = self.weapon
        if w.booster_thrust <= 0.0 or self._boost_elapsed >= w.booster_time:
            return 0.0
        self._boost_elapsed += dt
        self.fuel = max(0.0, self.fuel
                        - w.booster_thrust / (w.isp * GRAVITY) * dt)
        return w.booster_thrust

    # --- main step -----------------------------------------------------------

    def update(self, dt: float, world) -> None:
        if not self.alive:
            return

        np.copyto(self.prev_pos, self.pos)
        self.t += dt

        alt = float(self.pos[1])
        vx, vy, vz = self.vel.tolist()
        speed = math.sqrt(vx * vx + vy * vy + vz * vz)
        if speed > 1e-9:
            inv = 1.0 / speed
            hx, hy, hz = vx * inv, vy * inv, vz * inv
        else:
            hx, hy, hz = 0.0, 1.0, 0.0

        # --- phase transitions -----------------------------------------------

        if self.phase == SPH_STRIKE_EJECT:
            self._eject_elapsed += dt
            if self._eject_elapsed >= self.weapon.eject_time:
                if self._is_vls:
                    self.phase = SPH_STRIKE_BOOST
                else:
                    # Air-launched: motor ignites, go straight to CLIMB.
                    self.phase = SPH_STRIKE_CLIMB

        if self.phase == SPH_STRIKE_BOOST:
            # Booster exhausted -> CLIMB.
            if self._boost_elapsed >= self.weapon.booster_time:
                self.phase = SPH_STRIKE_CLIMB

        if self.phase in (SPH_STRIKE_CLIMB,
                          SPH_STRIKE_CRUISE,
                          SPH_STRIKE_TERMINAL):
            command = self._flight_computer_step(dt, world)
            if self.phase != SPH_STRIKE_TERMINAL:
                if command.mode is FlightMode.TERMINAL:
                    self.phase = SPH_STRIKE_TERMINAL
                elif self.phase == SPH_STRIKE_CLIMB:
                    is_arm = str(self.weapon.weapon_id) in ("harm", "kh31p")
                    if (is_arm and alt >= (CLIMB_TO_CRUISE_FRAC
                                           * self.weapon.cruise_alt)):
                        # The planner owns the loft command; once the declared
                        # capture basket is reached, passive homing owns the
                        # rest of the ARM flight instead of spending ramjet
                        # fuel waiting for vertical rate to decay to zero.
                        self.phase = SPH_STRIKE_CRUISE
                    elif (command.mode is FlightMode.CLIMB
                            or (self._launched_above_cruise
                                and (command.mode is FlightMode.DESCEND
                                     or command.prediction.corridor ==
                                     "hold"))):
                        # The public CLIMB stage covers altitude capture in
                        # either direction.  A high-release ARM may elect to
                        # hold energy first; that is still pre-cruise capture.
                        self.phase = SPH_STRIKE_CLIMB
                    else:
                        self.phase = SPH_STRIKE_CRUISE
                # Once the broad cruise stage is established, later online
                # climb/descend corrections do not chatter the public label.

        # --- forces ----------------------------------------------------------

        thrust = 0.0
        drag = 0.0
        gx = gy = gz = 0.0

        if self.phase == SPH_STRIKE_EJECT:
            # Free-fall / cold-gas eject: gravity only, drag included.
            drag = drag_force_scalar(
                speed, alt, cd_from_mach_scalar(mach_scalar(speed, alt)),
                self.weapon.ref_area)

        elif self.phase == SPH_STRIKE_BOOST:
            # VLS booster: tip the velocity from vertical toward the cruise
            # heading using a smooth pitch-over (Rodrigues rotation toward
            # the horizontal cruise direction), then burn hard.
            # Target cruise direction: horizontal toward the target.
            hdg = self._route_heading()
            cruise_dir_x = math.sin(hdg)
            cruise_dir_z = math.cos(hdg)
            # Rotate the velocity unit vector toward horizontal cruise dir.
            tx, ty, tz = cruise_dir_x, 0.0, cruise_dir_z
            # Clamp rotation to BOOST_PITCH_RATE * dt per step.
            hx, hy, hz = _rotate_toward_scalar(hx, hy, hz, tx, ty, tz,
                                               BOOST_PITCH_RATE * dt)
            vx, vy, vz = hx * speed, hy * speed, hz * speed
            self.vel[0] = vx
            self.vel[1] = vy
            self.vel[2] = vz
            # Gravity compensation: cancel the path-bending component of
            # gravity so the pitch-over rate is what the vanes command
            # (same pattern as sim/missile.py PITCHOVER phase).
            gx = -GRAVITY * hy * hx
            gy = GRAVITY * (1.0 - hy * hy)
            gz = -GRAVITY * hy * hz
            thrust = self._boost_thrust(dt)
            drag = drag_force_scalar(
                speed, alt, cd_from_mach_scalar(mach_scalar(speed, alt)),
                self.weapon.ref_area)

        elif self.phase in (SPH_STRIKE_CLIMB,
                            SPH_STRIKE_CRUISE,
                            SPH_STRIKE_TERMINAL):
            m_now = mach_scalar(speed, alt)
            q = q_scalar(speed, alt)
            qs = q * self.weapon.ref_area
            drag = qs * cd_from_mach_scalar(m_now)
            gx, gy, gz = self._guidance(alt, vy, speed, vx, vz, dt, world)
            gx, gy, gz = project_perpendicular_scalar(
                gx, gy, gz, vx, vy, vz)
            # --- energy model (sim/aero.py; plan 2026-07-05): q-limit the
            # command, lag it through the autopilot, charge the achieved
            # lift as induced drag — turning costs speed here too.
            gx, gy, gz = autopilot_step_scalar(
                gx, gy, gz, self._ap_x, self._ap_y, self._ap_z,
                dt=dt, tau=self._ap_tau, q=q,
                ref_area=self.weapon.ref_area, mass=max(self.mass, 1.0),
                cl_max=self._cl_max,
                structural_limit=self.weapon.max_g * GRAVITY)
            self._ap_x, self._ap_y, self._ap_z = gx, gy, gz
            lift = self.mass * math.sqrt(gx * gx + gy * gy + gz * gz)
            drag += self._k_ind * lift * lift / max(qs, QS_FLOOR)
            # Booster still running during CLIMB (VLS after pitch-over).
            bt = self._boost_thrust(dt)
            thrust = bt if bt > 0.0 else self._cruise_thrust(m_now, drag, dt)

        # --- semi-implicit Euler ---------------------------------------------
        coef = (thrust - drag) / max(self.mass, 1.0)
        vx += (hx * coef + gx) * dt
        vy += (hy * coef + gy - GRAVITY) * dt
        vz += (hz * coef + gz) * dt
        self.vel[0] = vx
        self.vel[1] = vy
        self.vel[2] = vz

        px = float(self.pos[0]) + vx * dt
        py = float(self.pos[1]) + vy * dt
        pz = float(self.pos[2]) + vz * dt
        self.pos[0] = px
        self.pos[1] = py
        self.pos[2] = pz

        # --- body attitude for render ----------------------------------------
        sp = math.sqrt(vx * vx + vy * vy + vz * vz)
        if sp > 1e-9:
            inv = 1.0 / sp
            self.body_dir[0] = vx * inv
            self.body_dir[1] = vy * inv
            self.body_dir[2] = vz * inv

        # --- ground impact ---------------------------------------------------
        surface = _surface_at(world, px, pz)
        if py <= surface:
            self.pos[1] = max(surface, py)
            self.impact_pos = self.pos.copy()
            self.phase = SPH_STRIKE_DEAD
            self.alive = False
            return

        # --- fuel-exhausted self-termination ----------------------------------
        # When fuel is gone the turbofan / motor has flamed out.  A missile
        # with no thrust decelerates and eventually falls below its minimum
        # flying speed.  We declare it dead once it crosses STALL_SPEED so
        # the test suite does not have to wait for the multi-minute passive
        # glide to the surface.  (Real Tomahawk: terminal-phase arming fuse
        # detonates the warhead shortly after flameout with no target in range.)
        new_speed = math.sqrt(vx * vx + vy * vy + vz * vz)
        if (self.fuel <= 0.0
                and new_speed < STALL_SPEED
                and self.phase not in (SPH_STRIKE_EJECT,
                                       SPH_STRIKE_BOOST,
                                       SPH_STRIKE_DEAD)):
            self.impact_pos = self.pos.copy()
            self.phase = SPH_STRIKE_DEAD
            self.alive = False

    def _guidance(self, alt: float, vs: float, speed: float,
                  vx: float, vz: float, dt: float, world) -> tuple:
        """Guidance accel (gx, gy, gz) plain floats, gravity-comp included.
        Called for CLIMB, CRUISE, and TERMINAL phases."""
        w = self.weapon

        if self.phase in (SPH_STRIKE_CLIMB, SPH_STRIKE_CRUISE):
            gx, gy, gz = self._online_midcourse_guidance(
                speed, vx, vs, vz, dt, world)

        elif self.phase == SPH_STRIKE_TERMINAL:
            tx, ty, tz = self._flight_target_point()
            if (self._dist_to_target() > TERMINAL_COMMIT_RANGE_M
                    or alt < ty):
                # Stage 1: stay on the terrain-following deck — the armed
                # round still rides the terrain over any ridge between it
                # and the target (see TERMINAL_COMMIT_RANGE_M).  The
                # ``alt < target_y`` clause (5b): commit to the straight
                # PN line only once AT-OR-ABOVE the aim point — a target
                # on a cliff top approached from the sea otherwise gets a
                # committed line that grazes the rising slope under it
                # (measured: a JASSM on the player base died 1.3 km short
                # on the coastal rise).  Riding the deck UP the slope
                # until level with the aim point turns the final commit
                # into a short, clear descent; aim heights are structure
                # mid-OBB (well under cruise_alt AGL), so the condition
                # always releases before overflight.
                gx, gz = _steer_scalar(vx, vz, self._route_heading())
                agl, agl_vs = self._skim_ref(alt, vs, world)
                gy = altitude_hold_accel(agl, agl_vs, w.cruise_alt,
                                         CRUISE_ALT_KP, CRUISE_ALT_KD,
                                         CRUISE_ALT_MAX_A) + GRAVITY
            else:
                # Stage 2: committed — PN on the target point (target_y =
                # aim altitude ASL; structure shots pass the OBB mid-height,
                # see __init__ doc).
                tgt_pos = np.array([tx, ty, tz], dtype=np.float64)
                a = pn_accel(self.pos, self.vel, tgt_pos, np.zeros(3))
                gx = float(a[0])
                gy = float(a[1]) + GRAVITY
                gz = float(a[2])
                # G-limiter for PN path.
                gmax = w.max_g * GRAVITY
                n2 = gx * gx + gy * gy + gz * gz
                if n2 > gmax * gmax:
                    k = gmax / math.sqrt(n2)
                    gx *= k
                    gy *= k
                    gz *= k
                return gx, gy, gz
        else:
            return 0.0, GRAVITY, 0.0

        # Control authority fades below stall speed: the entire guidance
        # output scales to zero (including gravity compensation), so the
        # missile sinks when it runs out of airspeed — a fuel-exhausted
        # missile that decelerates below stall will eventually hit the
        # surface under the uncompensated gravity pull.
        if speed < STALL_SPEED:
            k = (speed / STALL_SPEED) ** 2
            gx *= k
            gy *= k
            gz *= k

        # G-limiter.
        gmax = w.max_g * GRAVITY
        n2 = gx * gx + gy * gy + gz * gz
        if n2 > gmax * gmax:
            k = gmax / math.sqrt(n2)
            gx *= k
            gy *= k
            gz *= k

        return gx, gy, gz


# ---------------------------------------------------------------------------
# HarmMissile
# ---------------------------------------------------------------------------

class HarmMissile(StrikeMissile):
    """AGM-88 HARM-class anti-radiation missile.

    Homes on a sim.radar.Radar object using proportional navigation while
    the target is alive and emitting.  Phase machine extends StrikeMissile:
      * EJECT (0.2 s free-fall) -> BOOST (solid motor 3 s, Mach 2)
      * CLIMB: lofts to HARM.cruise_alt (~9 km)
      * CRUISE: at loft altitude, PN-homes on radar
      * TERMINAL: inside TERMINAL_RANGE_M, pure PN dive
      * DEAD: fuse trigger or surface impact

    Radar-silence handling (spec §8):
      * While target.emitting and target.alive: aim on live pos.
      * If radar goes silent: freeze last-known pos, draw miss offset once
        (deterministic from seeded rng: uniform in HARM_MISS_MIN_M to
        HARM_MISS_MAX_M ring).  Spec: "a silenced radar usually survives."
      * If the radar re-emits: re-lock live position, clear miss offset.
      * Proximity fuse radius: 15 m (HARM.fuse_radius, spec §8).

    Parameters
    ----------
    weapon : StrikeDef  (sim.arsenal.HARM)
    pos_f64 : array-like (3,)
    vel_f64 : array-like (3,)  aircraft release velocity
    target_radar : sim.radar.Radar
    rng : numpy.random.Generator   seeded for deterministic miss offset
    """

    def __init__(self, weapon, pos_f64, vel_f64, target_radar, rng):
        super().__init__(weapon, pos_f64, vel_f64,
                         (float(target_radar.pos[0]),
                          float(target_radar.pos[2])))
        self.target_radar = target_radar
        self._rng = rng
        # Last-known radar position; updated while emitting, frozen on silence.
        self._aim_pos = np.asarray(target_radar.pos, dtype=np.float64).copy()
        # Miss offset applied when radar goes silent; drawn once on silence.
        self._miss_offset = None
        self._was_emitting = target_radar.alive and target_radar.emitting

    # --- radar tracking ------------------------------------------------------

    def _update_aim(self) -> None:
        """Update aim point from live or last-known radar position."""
        radar = self.target_radar
        emitting_now = radar.alive and radar.emitting
        if emitting_now:
            self._aim_pos[:] = radar.pos
            self._miss_offset = None
            self._was_emitting = True
        else:
            if self._was_emitting and self._miss_offset is None:
                # First silence: draw deterministic miss offset.
                angle = self._rng.uniform(0.0, 2.0 * math.pi)
                radius = self._rng.uniform(HARM_MISS_MIN_M, HARM_MISS_MAX_M)
                self._miss_offset = np.array(
                    [math.cos(angle) * radius,
                     0.0,
                     math.sin(angle) * radius], dtype=np.float64)
            self._was_emitting = False

    def _aim_point(self) -> np.ndarray:
        if self._miss_offset is not None:
            return self._aim_pos + self._miss_offset
        return self._aim_pos

    def _flight_target_point(self):
        """Current live/degraded ARM aim supplied to planning and steering."""
        aim = self._aim_point()
        return float(aim[0]), float(aim[1]), float(aim[2])

    # --- override guidance ---------------------------------------------------

    def _guidance(self, alt: float, vs: float, speed: float,
                  vx: float, vz: float, dt: float, world) -> tuple:
        """Use online midcourse flight control, then retain terminal PN."""
        w = self.weapon

        if self.phase in (SPH_STRIKE_CLIMB, SPH_STRIKE_CRUISE):
            return super()._guidance(alt, vs, speed, vx, vz, dt, world)

        if self.phase == SPH_STRIKE_TERMINAL:
            # PN homing on aim point (stationary ground target).
            aim = self._aim_point().copy()
            a = pn_accel(self.pos, self.vel, aim, np.zeros(3))
            gx = float(a[0])
            gy = float(a[1]) + GRAVITY
            gz = float(a[2])
            # G-limiter (separate from the base path below).
            gmax = w.max_g * GRAVITY
            n2 = gx * gx + gy * gy + gz * gz
            if n2 > gmax * gmax:
                k = gmax / math.sqrt(n2)
                gx *= k
                gy *= k
                gz *= k
            return gx, gy, gz
        return 0.0, GRAVITY, 0.0

    # --- proximity fuse ------------------------------------------------------

    def _fuse_check(self) -> bool:
        """Proximity fuse: swept segment prev_pos -> pos within fuse_radius
        of aim_point.  Returns True and sets alive=False if triggered."""
        aim = self._aim_point()
        ax, ay, az = self.prev_pos.tolist()
        bx, by, bz = self.pos.tolist()
        dx, dy, dz = bx - ax, by - ay, bz - az
        qx = float(aim[0]) - ax
        qy = float(aim[1]) - ay
        qz = float(aim[2]) - az
        denom = dx * dx + dy * dy + dz * dz
        s = 0.0 if denom < 1e-12 else min(max(
            (qx * dx + qy * dy + qz * dz) / denom, 0.0), 1.0)
        cx, cy, cz = ax + s * dx, ay + s * dy, az + s * dz
        mx = float(aim[0]) - cx
        my = float(aim[1]) - cy
        mz = float(aim[2]) - cz
        r2 = self.weapon.fuse_radius * self.weapon.fuse_radius
        if mx * mx + my * my + mz * mz <= r2:
            self.impact_pos = np.array([cx, cy, cz], dtype=np.float64)
            self.phase = SPH_STRIKE_DEAD
            self.alive = False
            if self._miss_offset is None and self.target_radar.alive:
                self.target_radar.alive = False
                # Forensics stamp (WRITE-ONLY, self-recorded): the debrief
                # flight recorder reads this off the dead round; NO sim code
                # ever does — the digest contract is untouched.
                self.death_cause = ("hit", "radar")
            return True
        return False

    # --- override update to add fuse -----------------------------------------

    def update(self, dt: float, world) -> None:
        if not self.alive:
            return

        # Update aim point before guidance runs in the base update.
        self._update_aim()

        # Delegate to base class (handles physics, phase transitions, impact).
        super().update(dt, world)

        # Proximity fuse check after integration.
        if self.alive:
            self._fuse_check()


# ---------------------------------------------------------------------------
# PlayerArmMissile (M2-T2 — player Kh-31P anti-radiation round)
# ---------------------------------------------------------------------------

class PlayerArmMissile(HarmMissile):
    """Player anti-radiation missile (Kh-31P-class, sim.arsenal.KH31P).

    The PLAYER counterpart to the enemy AGM-88 HarmMissile.  Reuses the
    HarmMissile flight/homing machine VERBATIM (loft climb, PN homing on an
    emitting sim.radar.Radar, seeded silence-CEP miss ring, re-lock on
    re-emit, proximity fuse).  The ONLY difference is the side flag:

      is_hostile = False   (class-attribute override)

    StrikeMissile sets ``is_hostile = True`` as a class attr; without this
    override the player's own ARM would be swept against the PLAYER base in
    world/combat.py ``apply_missile_hits_structures`` (hostile rounds vs the
    player structures) and could demolish the base it flew over.  A subclass
    is cleaner than mutating the instance: the flag is part of the type, so
    every PlayerArmMissile is friendly by construction and isinstance/class
    checks read true.

    Constructor signature is inherited unchanged:
        PlayerArmMissile(weapon, pos_f64, vel_f64, target_radar, rng)
    """

    is_hostile = False
