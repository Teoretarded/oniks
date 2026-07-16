"""Guidance laws: proportional navigation, altitude hold, waypoint steering.

Pure functions on float64 numpy arrays -- no OpenGL, no game state.
Axes follow the locked conventions: X = east, Y = up, Z = north; heading 0 is
+Z (north) increasing clockwise seen from above. (Scalar internals use the
math module: these run per missile per 120 Hz substep — Task 22 perf.)
"""

import math

import numpy as np

# --- Tuning constants (controller gains) -------------------------------------

# True proportional navigation gain. 3-5 is the classic range; 4 intercepts
# crossing and head-on targets within the ~11 g lateral limit used in tests.
PN_GAIN = 4.0

# Altitude-hold PD gains. kp [1/s^2] pulls toward the target altitude, kd
# [1/s] damps vertical speed (near critically damped: kd ~ 2*sqrt(kp)).
# max accel ~3.5 g keeps the sea-skim push-over gentle.
ALT_HOLD_KP = 0.35
ALT_HOLD_KD = 1.1
ALT_HOLD_MAX_A = 35.0

# Heading steering: lateral accel = gain * heading_error * horizontal_speed,
# clipped to ~6 g for the cruise turn toward the next waypoint.
STEER_GAIN = 2.2
STEER_MAX_A = 60.0

# A waypoint counts as reached inside this horizontal radius (m).
WAYPOINT_RADIUS = 2_500.0


def pn_accel(mis_pos, mis_vel, tgt_pos, tgt_vel, n_gain=PN_GAIN):
    """True 3D proportional navigation.

    ``a = N * Vc * (omega_LOS x v_hat)`` where ``Vc`` is the positive
    closing speed.  The returned acceleration is perpendicular to missile
    velocity, so guidance changes direction without creating kinetic energy.
    A receding/non-closing target produces no PN command; midcourse/explicit
    guidance must first establish a closing collision course.
    """
    r = tgt_pos - mis_pos
    v_rel = tgt_vel - mis_vel
    r2 = float(r @ r)
    if r2 < 1.0:
        return np.zeros(3)
    speed = float(np.linalg.norm(mis_vel))
    if speed < 1e-9:
        return np.zeros(3)
    rmag = math.sqrt(r2)
    rhat = r / rmag
    closing = max(0.0, -float(v_rel @ rhat))
    if closing <= 0.0:
        return np.zeros(3)
    omega = np.cross(r, v_rel) / r2          # LOS angular-rate vector
    vhat = mis_vel / speed
    return n_gain * closing * np.cross(omega, vhat)


def gravity_compensation_accel(vel, gravity=9.81):
    """Aerodynamic acceleration that cancels only gravity perpendicular to
    the flight path.

    Cancelling world-vertical gravity outright lets lift do positive work in
    a climb.  Real lift/autopilot acceleration is normal to velocity; the
    along-track gravity component must remain so climbing spends energy and
    descending regains it.
    """
    speed = float(np.linalg.norm(vel))
    if speed < 1e-9:
        return np.zeros(3)
    vhat = vel / speed
    up = np.array([0.0, 1.0, 0.0])
    return gravity * (up - vhat * float(vhat[1]))


def altitude_hold_accel(alt, vspeed, target_alt,
                        kp=ALT_HOLD_KP, kd=ALT_HOLD_KD, max_a=ALT_HOLD_MAX_A):
    """PD vertical accel command (positive = up), gravity NOT included."""
    a = kp * (target_alt - alt) - kd * vspeed
    return min(max(a, -max_a), max_a)


def steer_heading_accel(vel, desired_heading, gain=STEER_GAIN, max_a=STEER_MAX_A):
    """Horizontal accel perpendicular to velocity that turns current heading
    toward desired. Returns (3,) float64 with zero vertical component."""
    vx, vz = float(vel[0]), float(vel[2])
    horiz_speed = math.hypot(vx, vz)
    if horiz_speed < 1e-9:
        return np.zeros(3)
    heading = math.atan2(vx, vz)
    # Wrap the error to [-pi, pi] so the turn always goes the short way.
    err = (desired_heading - heading + math.pi) % (2.0 * math.pi) - math.pi
    a_lat = gain * err * horiz_speed
    a_lat = min(max(a_lat, -max_a), max_a)
    # Right-hand (clockwise-from-above, heading-increasing) horizontal normal.
    s = a_lat / horiz_speed
    return np.array([vz * s, 0.0, -vx * s])


def waypoint_reached(pos, wp, radius=WAYPOINT_RADIUS) -> bool:
    """True when the horizontal (XZ) distance from pos to wp is under radius."""
    dx = float(pos[0]) - float(wp[0])
    dz = float(pos[2]) - float(wp[2])
    return dx * dx + dz * dz < radius * radius
