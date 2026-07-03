"""IrMissile: AIM-9X-class air-to-air infrared missile (pure numpy, GL-free).

Launched from a fighter to engage slow, hot-exhaust targets (primarily the
player's recon drone).  No radar, no RWR spike — IR is a PASSIVE seeker;
the drone's RWR sees nothing on launch or guidance.  The drone can only
infer a shot if it sees the fighter (via its nose radar ping on the RWR)
before the shot — once fired, the missile is silent.

Design:
    - Air-launched: inherits carrier pos/vel from the releasing fighter.
    - Length 3.0 m, 85 kg, Mach ~2.7 over release speed.
    - Motor burn 5 s + unpowered coast.
    - Max ~20 g sustained turn.
    - IR seeker lock:
        * Rear hemisphere (within 90 deg of target tail): IR_LOCK_RANGE_M = 8 km.
        * Front hemisphere: 4 km (cold airframe vs hot intake/exhaust).
        * Aspect computed as angle of missile-to-target LOS relative to the
          target's velocity vector.  lock_range = lerp(4 km, 8 km) based on
          |cos(aspect)|, rear-weighted.
    - Lock acquired at launch; lost if target leaves the aspect-adjusted range
      (a crossing shot that opens beyond range self-destructs — energy limited).
    - Terminal guidance: proportional navigation, prox fuse 8 m.
    - Kinematic miss: energy/geometry decides outcomes, no dice.  A shot
      launched beyond IR_LOCK_RANGE_M at the given aspect never acquires lock
      (returns None from IrMissile.launch_if_locked).
    - Off-boresight pre-launch: if launch_boresight_error_rad > OBS_LIMIT_RAD
      (~25 deg) the shot is not taken (returns None); the fighter must manoeuvre.
    - Flares/jamming: out of scope (Phase 5b; reserved).

RWR note:
    An IR launch does NOT spike the drone's RWR.  The seeker is passive; no
    radar emission occurs at any point in the engagement.  The drone learns of
    the shot only if it saw the fighter's nose radar ping before the shot was
    fired (a radar warning from the fighter's own emit, NOT from this missile).
    This is documented here because it is a deliberate design choice that differs
    from SAM engagements: model as NO RWR warning on IR launch.

Axes: X east, Y up, Z north (locked conventions).  All SI float64.
Phase machine: same enum range as sam.py but offset to avoid collision:
    IRP_BOOST, IRP_COAST, IRP_TERMINAL (collapses into coast — no midcourse
    / terminal distinction at short ranges), IRP_DEAD.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

from sim.guidance import pn_accel
from sim.missile import _surface_at
from sim.physics import (GRAVITY, cd_from_mach_scalar, drag_force_scalar,
                         mach_scalar)

# ---------------------------------------------------------------------------
# Phase constants (range 30-34 — well clear of sam.py 0-4 and strike.py 20-25)
# ---------------------------------------------------------------------------
IRP_BOOST    = 30
IRP_COAST    = 31
IRP_TERMINAL = 32   # alias for coast at short ranges (PN active throughout)
IRP_DEAD     = 33

PHASE_LABELS = {
    IRP_BOOST:    "BOOST",
    IRP_COAST:    "COAST",
    IRP_TERMINAL: "TERMINAL",
    IRP_DEAD:     "DEAD",
}

# ---------------------------------------------------------------------------
# Physical constants (research-grounded, documented)
# ---------------------------------------------------------------------------

# AIM-9X airframe geometry.
IR_LENGTH_M: float = 3.0        # m
IR_DIAMETER_M: float = 0.127    # m (5 in for the AIM-9 family)
IR_LAUNCH_MASS_KG: float = 85.0 # kg (AIM-9X cited ~85 kg)

# Propellant: solid dual-thrust motor, burn modelled as one 5 s stage.
IR_PROPELLANT_KG: float = 9.6   # kg solid propellant (AIM-9X motor ~10 kg)

# Motor: produces ~600 m/s delta-v over 5 s from rest (adds ~Mach 1.8 above
# release speed); with a fighter release at ~Mach 0.8-1.0 the burn-out speed
# is ~Mach 2.5-2.7.  Thrust sized: F = m*a, a = dV/dt = 600/5 = 120 m/s^2,
# avg mass ~80 kg, F ~ 9,600 N.  Using 10,000 N (round, covers losses).
IR_MOTOR_THRUST_N: float = 10_000.0   # N
IR_MOTOR_BURN_S: float = 5.0          # s (single-stage solid motor)
IR_ISP_S: float = 200.0               # s (solid propellant Isp, AIM-9 class)
IR_MDOT: float = IR_MOTOR_THRUST_N / (IR_ISP_S * GRAVITY)  # kg/s

# Aerodynamic reference area (pi*(d/2)^2).
IR_REF_AREA_M2: float = math.pi * (IR_DIAMETER_M / 2.0) ** 2

# Max lateral acceleration (20 g, sustained).
IR_MAX_G: float = 20.0

# Proximity fuse.
IR_FUSE_RADIUS_M: float = 8.0   # m (AIM-9X ~9 m claimed; using 8 m conservatively)

# Self-destruct: time out or coast speed floor.
IR_SELF_DESTRUCT_T_S: float = 60.0   # s (AIM-9X ~40-60 s endurance)
IR_SELF_DESTRUCT_SPEED_MPS: float = 100.0  # m/s coast speed floor

# --- IR seeker lock-on ranges ---
# Lock range scales with aspect angle: rear hemisphere up to 8 km (hot exhaust
# plume), front hemisphere 4 km (cold intake + body radiation).
# Aspect angle is the angle between the missile-to-target LOS and the target's
# velocity vector tail.  At 0 deg (pure rear) lock range = 8 km; at 90 deg
# (beam) lerp midpoint; at 180 deg (pure front) = 4 km.
# Lock function: range = 4 km + 4 km * (1 + cos(aspect)) / 2
#             = 4 km + 2 km * (1 + cos(aspect))
# which equals 8 km at 0 deg, 6 km at 90 deg, 4 km at 180 deg.
# Simplified per task spec: rear = 8 km, front = 4 km (linear blend).
IR_LOCK_RANGE_REAR_M: float = 8_000.0   # m — rear hemisphere, tail-chase
IR_LOCK_RANGE_FRONT_M: float = 4_000.0  # m — front hemisphere, head-on

# Off-boresight launch limit (OBS).  Beyond ~25 deg the seeker gimbal loses
# the target before the motor finishes; the shot is refused.
IR_OBS_LIMIT_RAD: float = math.radians(25.0)  # ~25 deg

# Terminal PN handover: already using PN throughout, so no distinct terminal
# handover range is needed — PN handles the full coast.
IR_TERMINAL_RANGE_M: float = 4_000.0


def _ir_lock_range_m(aspect_rad: float) -> float:
    """Compute aspect-dependent lock-on range.

    aspect_rad: angle between missile-to-target LOS and the target's velocity
    tail (0 = pure rear; pi = pure front).  Uses (1+cos)/2 weighting so the
    blend is smooth and physically motivated (rear IR emission dominates).
    """
    cos_a = math.cos(aspect_rad)
    # weight: 1.0 at rear (cos=+1), 0.0 at front (cos=-1)
    w = (1.0 + cos_a) / 2.0
    return IR_LOCK_RANGE_FRONT_M + w * (IR_LOCK_RANGE_REAR_M - IR_LOCK_RANGE_FRONT_M)


def _aspect_angle_rad(
    shooter_pos: np.ndarray,
    target_pos: np.ndarray,
    target_vel: np.ndarray,
) -> float:
    """Aspect angle: angle between the missile->target LOS and the target's
    velocity tail.  Returns value in [0, pi] — 0 = pure stern shot,
    pi = pure head-on."""
    los = target_pos - shooter_pos
    los_dist = float(np.linalg.norm(los))
    if los_dist < 1.0:
        return 0.0
    los_hat = los / los_dist
    tspeed = float(np.linalg.norm(target_vel))
    if tspeed < 1.0:
        # Stationary target: treat as a rear-hemisphere shot (conservative —
        # the target has no exhaust plume direction to define front vs rear).
        return 0.0
    tvel_hat = target_vel / tspeed
    # Aspect angle convention (0 = pure rear / tail-chase; pi = pure front /
    # head-on):
    #   A tail-chase: LOS points in the SAME direction as tvel (both north).
    #     cos = los_hat . tvel_hat = +1 -> aspect = 0 (rear).
    #   Head-on: LOS points OPPOSITE to tvel (LOS north, tvel south).
    #     cos = los_hat . tvel_hat = -1 -> aspect = pi (front).
    dot = float(los_hat @ tvel_hat)
    dot = min(max(dot, -1.0), 1.0)
    return math.acos(dot)


# ---------------------------------------------------------------------------
# IrMissile
# ---------------------------------------------------------------------------

class IrMissile:
    """AIM-9X-class air-to-air IR missile, air-launched from a fighter.

    Parameters
    ----------
    pos_f64 : (3,) float64
        Release position (tube mouth / pylon) in world space.
    vel_f64 : (3,) float64
        Release velocity — inherits the fighter's vel vector at drop.
    target : any duck-type with .pos (3,), .velocity()->(3,), .alive bool
        The intended target.  If the target dies after launch the missile
        self-destructs at IR_SELF_DESTRUCT_T_S.

    RWR contract:
        No radar emission at any point.  Drone RWR state is UNCHANGED by this
        launch.  The drone's RWR SPIKE comes only from the fighter's own nose
        radar before the shot — and ONLY when that radar is emitting.  After
        the shot the fighter may go radar-silent; the missile is already en
        route and passive.
    """

    # Duck-type flags for ContactBoard / world integration (mirrors StrikeMissile).
    # IR missiles are NOT hostile (player never fires them in Phase 5b); this
    # class is enemy-launched.  The world must set is_hostile = True on
    # enemy rounds.  Since enemy and player may share the class in future we
    # leave it False and let the world override via subclass or attribute.
    is_air: bool = True
    is_hostile: bool = True    # enemy-launched; hostile to player structures
    radar_size: str = "missile"
    # Passive seeker — MUST NOT trigger the drone's RWR LOCK alert.
    # The RWR LOCK gate checks this flag; False = the missile is invisible
    # to passive-warning systems (spec §5.1: "IR seekers are passive").
    rwr_generates_lock: bool = False
    # Phase 8: the player sees an AIM-9X the instant it is fired (IR launch
    # flash / MAWS cue), unlike the radar-gated Tomahawk.
    launch_warning: bool = True
    # M1: weapon classification for the contact-board ``kind`` stamp (the
    # threat strip / intel panel read it). IrMissile carries no WeaponDef, so
    # it names itself here — mirrors StrikeMissile/SamMissile's weapon.weapon_id.
    weapon_id: str = "aim9x"

    def __init__(
        self,
        pos_f64,
        vel_f64,
        target,
    ):
        self.pos = np.asarray(pos_f64, dtype=np.float64).copy()
        self.prev_pos = self.pos.copy()
        self.vel = np.asarray(vel_f64, dtype=np.float64).copy()
        self.target = target
        self.body_dir = self.vel.copy()
        _sp = float(np.linalg.norm(self.body_dir))
        if _sp > 1e-9:
            self.body_dir /= _sp

        self.phase = IRP_BOOST
        self.t = 0.0
        self._propellant = IR_PROPELLANT_KG
        self.alive = True
        self.impact_pos: Optional[np.ndarray] = None
        self.killed_target = False
        self.self_destructed = False
        self._fuse_r2 = IR_FUSE_RADIUS_M * IR_FUSE_RADIUS_M
        self._mass = IR_LAUNCH_MASS_KG

    # --- duck-type helpers --------------------------------------------------

    @property
    def mass(self) -> float:
        return self._mass

    @property
    def phase_label(self) -> str:
        return PHASE_LABELS.get(self.phase, "---")

    @property
    def aircraft_id(self) -> str:
        """ContactBoard track id (the gated player picture feeds hostile
        rounds as air entities keyed on aircraft_id — sim/strike.py
        StrikeMissile pattern).  Stable for the object's lifetime."""
        return f"ir_{id(self):x}"

    def velocity(self) -> np.ndarray:
        return self.vel.copy()

    # --- lock-on geometry check (static / pre-launch) -----------------------

    @staticmethod
    def aspect_ok(
        shooter_pos: np.ndarray,
        target_pos: np.ndarray,
        target_vel: np.ndarray,
        shooter_heading_rad: float,
    ) -> tuple[bool, float]:
        """Return (can_lock, lock_range_m) for a potential shot.

        Checks:
        1. Aspect-dependent IR lock range.
        2. Off-boresight limit (the missile must be within OBS_LIMIT_RAD of the
           shooter's current heading at the moment of launch).

        Parameters
        ----------
        shooter_pos    : (3,) float64, shooter world pos (m)
        target_pos     : (3,) float64, target world pos (m)
        target_vel     : (3,) float64, target velocity (m/s)
        shooter_heading_rad : float, fighter's current heading (0 = +Z, CW)

        Returns
        -------
        (can_lock: bool, lock_range_m: float)
            can_lock  — True when both range and OBS checks pass.
            lock_range_m — the aspect-dependent lock range (useful for the
                           caller to annotate a debug display).
        """
        # Aspect angle and resulting lock range.
        aspect = _aspect_angle_rad(shooter_pos, target_pos, target_vel)
        lock_r = _ir_lock_range_m(aspect)

        # Distance check.
        d = float(np.linalg.norm(target_pos - shooter_pos))
        if d > lock_r:
            return False, lock_r

        # Off-boresight check: angle between shooter heading and LOS.
        los = target_pos - shooter_pos
        los_dist = float(np.linalg.norm(los))
        if los_dist < 1.0:
            return True, lock_r
        # Shooter heading unit vector (XZ plane).
        hdg_x = math.sin(shooter_heading_rad)
        hdg_z = math.cos(shooter_heading_rad)
        los_x = float(los[0]) / los_dist
        los_z = float(los[2]) / los_dist
        cos_obs = hdg_x * los_x + hdg_z * los_z
        cos_obs = min(max(cos_obs, -1.0), 1.0)
        obs = math.acos(cos_obs)
        if obs > IR_OBS_LIMIT_RAD:
            return False, lock_r

        return True, lock_r

    # --- death helpers ------------------------------------------------------

    def _die(self, impact: np.ndarray) -> None:
        self.impact_pos = impact
        self.phase = IRP_DEAD
        self.alive = False

    def _fuse_check(self) -> bool:
        """Swept-segment proximity fuse against the TRUE target position.

        Returns True if triggered (target killed, missile dead).
        """
        if not self.target.alive:
            return False
        tp = self.target.pos
        ax, ay, az = self.prev_pos.tolist()
        bx, by, bz = self.pos.tolist()
        dx = bx - ax
        dy = by - ay
        dz = bz - az
        qx = float(tp[0]) - ax
        qy = float(tp[1]) - ay
        qz = float(tp[2]) - az
        denom = dx * dx + dy * dy + dz * dz
        if denom < 1e-12:
            s = 0.0
        else:
            s = min(max((qx * dx + qy * dy + qz * dz) / denom, 0.0), 1.0)
        cx = ax + s * dx
        cy = ay + s * dy
        cz = az + s * dz
        mx = float(tp[0]) - cx
        my = float(tp[1]) - cy
        mz = float(tp[2]) - cz
        if mx * mx + my * my + mz * mz <= self._fuse_r2:
            kill_fn = getattr(self.target, "kill", None)
            if kill_fn is not None:
                kill_fn()
            else:
                self.target.alive = False
            self.killed_target = True
            # Forensics stamps (WRITE-ONLY): the debrief flight recorder
            # reads these off the dead round; NO sim code ever does — the
            # digest contract is untouched.
            self.target.death_cause = ("a2a", str(self.weapon_id))
            self.target.killed_by = self
            self._die(np.array([cx, cy, cz]))
            return True
        return False

    # --- main update --------------------------------------------------------

    def update(self, dt: float, world) -> None:
        if not self.alive:
            return

        np.copyto(self.prev_pos, self.pos)
        self.t += dt

        px, py, pz = self.pos.tolist()
        vx, vy, vz = self.vel.tolist()
        speed = math.sqrt(vx * vx + vy * vy + vz * vz)
        if speed > 1e-9:
            inv = 1.0 / speed
            hx, hy, hz = vx * inv, vy * inv, vz * inv
        else:
            hx, hy, hz = 0.0, 0.0, 1.0

        # --- phase transitions ---
        if self.phase == IRP_BOOST and self._propellant <= 0.0:
            self.phase = IRP_COAST

        # --- guidance: PN throughout (no midcourse/terminal split at this
        #   short range — the missile is already heading roughly at the target
        #   at release; PN handles the intercept geometry immediately).
        gx = gy = gz = 0.0
        if self.target.alive:
            tpos = np.asarray(self.target.pos, dtype=np.float64)
            tvel = np.asarray(self.target.velocity(), dtype=np.float64)
            g = pn_accel(self.pos, self.vel, tpos, tvel)
            gx, gy, gz = float(g[0]), float(g[1]), float(g[2])
            gy += GRAVITY   # gravity compensation
            gmax = IR_MAX_G * GRAVITY
            n2 = gx * gx + gy * gy + gz * gz
            if n2 > gmax * gmax:
                k = gmax / math.sqrt(n2)
                gx *= k
                gy *= k
                gz *= k

        # --- forces ---
        thrust = 0.0
        if self.phase == IRP_BOOST:
            thrust = IR_MOTOR_THRUST_N
            self._propellant = max(0.0, self._propellant - IR_MDOT * dt)
            self._mass = IR_LAUNCH_MASS_KG - (IR_PROPELLANT_KG - self._propellant)

        drag = drag_force_scalar(
            speed, py, cd_from_mach_scalar(mach_scalar(speed, py)), IR_REF_AREA_M2
        )

        # --- semi-implicit Euler ---
        coef = (thrust - drag) / max(self._mass, 1.0)
        vx += (hx * coef + gx) * dt
        vy += (hy * coef + gy - GRAVITY) * dt
        vz += (hz * coef + gz) * dt
        self.vel[0] = vx
        self.vel[1] = vy
        self.vel[2] = vz

        px2 = px + vx * dt
        py2 = py + vy * dt
        pz2 = pz + vz * dt
        self.pos[0] = px2
        self.pos[1] = py2
        self.pos[2] = pz2

        # --- body direction ---
        sp2 = math.sqrt(vx * vx + vy * vy + vz * vz)
        if sp2 > 1e-9:
            inv = 1.0 / sp2
            self.body_dir[0] = vx * inv
            self.body_dir[1] = vy * inv
            self.body_dir[2] = vz * inv

        # --- proximity fuse (truth, target must be alive) ---
        if self._fuse_check():
            return

        # --- surface impact ---
        surface = _surface_at(world, px2, pz2)
        if py2 <= surface:
            self.pos[1] = surface
            self._die(self.pos.copy())
            return

        # --- kinematic miss / self-destruct ---
        new_speed = math.sqrt(vx * vx + vy * vy + vz * vz)
        if self.t > IR_SELF_DESTRUCT_T_S:
            self.self_destructed = True
            self._die(self.pos.copy())
            return
        if (self.phase == IRP_COAST and new_speed < IR_SELF_DESTRUCT_SPEED_MPS):
            # Energy exhausted — the missile is ballistic; if the target is
            # more than fuse_radius away at this point it is a kinematic miss.
            self.self_destructed = True
            self._die(self.pos.copy())
            return

        # --- range check: if the target has opened beyond the aspect-
        #   dependent lock range the seeker loses lock.  No reacquire.
        if self.target.alive:
            tpos = np.asarray(self.target.pos, dtype=np.float64)
            tvel = np.asarray(self.target.velocity(), dtype=np.float64)
            d = float(np.linalg.norm(tpos - self.pos))
            aspect = _aspect_angle_rad(self.pos, tpos, tvel)
            lock_r = _ir_lock_range_m(aspect)
            if d > lock_r * 2.0:
                # Well outside the seeker band — the lock is broken.  A
                # tail-chase that opens well past 8 km is kinematically lost.
                self.self_destructed = True
                self._die(self.pos.copy())
                return
