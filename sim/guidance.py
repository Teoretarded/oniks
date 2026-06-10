"""Guidance laws: proportional navigation, altitude hold, waypoint steering.

Pure functions on float64 numpy arrays -- no OpenGL, no game state.
Axes follow the locked conventions: X = east, Y = up, Z = north; heading 0 is
+Z (north) increasing clockwise seen from above.
"""

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
    """True 3D proportional navigation. Returns commanded accel (3,) float64,
    perpendicular component only (drop any along-velocity component)."""
    r = tgt_pos - mis_pos
    v_rel = tgt_vel - mis_vel
    r2 = float(r @ r)
    if r2 < 1.0:
        return np.zeros(3)
    omega = np.cross(r, v_rel) / r2          # LOS rotation rate vector
    # Sign note: with v_rel target-relative (tgt - mis), n * cross(v_rel, omega)
    # already accelerates INTO the LOS rotation (verified by the head-on and
    # crossing intercept tests); negating it steers away and diverges.
    a = n_gain * np.cross(v_rel, omega)
    vhat = mis_vel / max(np.linalg.norm(mis_vel), 1e-9)
    return a - vhat * (a @ vhat)


def altitude_hold_accel(alt, vspeed, target_alt,
                        kp=ALT_HOLD_KP, kd=ALT_HOLD_KD, max_a=ALT_HOLD_MAX_A):
    """PD vertical accel command (positive = up), gravity NOT included."""
    return float(np.clip(kp * (target_alt - alt) - kd * vspeed, -max_a, max_a))


def steer_heading_accel(vel, desired_heading, gain=STEER_GAIN, max_a=STEER_MAX_A):
    """Horizontal accel perpendicular to velocity that turns current heading
    toward desired. Returns (3,) float64 with zero vertical component."""
    vx, vz = float(vel[0]), float(vel[2])
    horiz_speed = float(np.hypot(vx, vz))
    if horiz_speed < 1e-9:
        return np.zeros(3)
    heading = np.arctan2(vx, vz)
    # Wrap the error to [-pi, pi] so the turn always goes the short way.
    err = (desired_heading - heading + np.pi) % (2.0 * np.pi) - np.pi
    a_lat = float(np.clip(gain * err * horiz_speed, -max_a, max_a))
    # Right-hand (clockwise-from-above, heading-increasing) horizontal normal.
    right = np.array([vz, 0.0, -vx]) / horiz_speed
    return a_lat * right


def waypoint_reached(pos, wp, radius=WAYPOINT_RADIUS) -> bool:
    """True when the horizontal (XZ) distance from pos to wp is under radius."""
    dx = float(pos[0]) - float(wp[0])
    dz = float(pos[2]) - float(wp[2])
    return dx * dx + dz * dz < radius * radius
