"""Atmosphere model and aerodynamic helpers (pure numpy, GL-free).

All quantities SI: meters, seconds, kilograms. Functions accept scalars or
numpy arrays and return the same shape. The ``*_scalar`` variants are
plain-float fast paths for per-missile per-step calls (Task 22 perf):
numpy's array dispatch costs more than the whole formula at size 1.
"""

import math

import numpy as np

# --- Physical constants (tuning lives here, never inline in formulas) -------
GRAVITY = 9.81                # m/s^2, standard gravity
RHO0 = 1.225                  # kg/m^3, sea-level air density (ISA)
DENSITY_SCALE_HEIGHT = 8500.0  # m, exponential atmosphere scale height

# Speed-of-sound profile: linear lapse in the troposphere, constant above.
SOS_SEA_LEVEL = 340.3         # m/s at 0 m altitude
SOS_LAPSE = 0.0039            # m/s lost per meter of altitude (troposphere)
TROPOPAUSE_ALT = 11_000.0     # m, above this the speed of sound is constant
SOS_STRATOSPHERE = 295.1      # m/s above the tropopause

# Drag-coefficient-vs-Mach curve for a slender supersonic missile:
# flat 0.30 subsonic, sharp transonic rise to 0.85 at M1.05, decaying back
# to 0.32 by M2.0 and settling at 0.30 above. np.interp clamps to the end
# values outside the table.
CD_MACH_POINTS = np.array([0.0, 0.80, 1.05, 2.0, 2.3])
CD_VALUES = np.array([0.30, 0.30, 0.85, 0.32, 0.30])


def air_density(alt_m):
    """Air density (kg/m^3) at altitude via exponential atmosphere."""
    return RHO0 * np.exp(-np.maximum(alt_m, 0.0) / DENSITY_SCALE_HEIGHT)


def speed_of_sound(alt_m):
    """Speed of sound (m/s): linear lapse below the tropopause, constant above."""
    a = np.where(
        np.asarray(alt_m) < TROPOPAUSE_ALT,
        SOS_SEA_LEVEL - SOS_LAPSE * np.maximum(alt_m, 0.0),
        SOS_STRATOSPHERE,
    )
    return a


def mach(speed, alt_m):
    """Mach number for a given speed (m/s) at altitude (m)."""
    return speed / speed_of_sound(alt_m)


def drag_force(speed, alt_m, cd, ref_area):
    """Aerodynamic drag magnitude (N): 0.5 * rho * v^2 * cd * S."""
    return 0.5 * air_density(alt_m) * speed**2 * cd * ref_area


def cd_from_mach(m):
    """Drag coefficient from Mach number (simple supersonic missile curve)."""
    return np.interp(m, CD_MACH_POINTS, CD_VALUES)


# --- scalar fast paths (Task 22 perf) ----------------------------------------

_CD_TABLE = list(zip(CD_MACH_POINTS.tolist(), CD_VALUES.tolist()))


def speed_of_sound_scalar(alt_m: float) -> float:
    """Plain-float speed_of_sound."""
    if alt_m < TROPOPAUSE_ALT:
        return SOS_SEA_LEVEL - SOS_LAPSE * max(alt_m, 0.0)
    return SOS_STRATOSPHERE


def mach_scalar(speed: float, alt_m: float) -> float:
    """Plain-float mach."""
    return speed / speed_of_sound_scalar(alt_m)


def drag_force_scalar(speed: float, alt_m: float, cd: float,
                      ref_area: float) -> float:
    """Plain-float drag_force (exponential-atmosphere density inlined)."""
    rho = RHO0 * math.exp(-max(alt_m, 0.0) / DENSITY_SCALE_HEIGHT)
    return 0.5 * rho * speed * speed * cd * ref_area


def cd_from_mach_scalar(m: float) -> float:
    """Plain-float cd_from_mach (same clamped piecewise-linear table)."""
    if m <= _CD_TABLE[0][0]:
        return _CD_TABLE[0][1]
    for (m0, c0), (m1, c1) in zip(_CD_TABLE, _CD_TABLE[1:]):
        if m <= m1:
            return c0 + (c1 - c0) * (m - m0) / (m1 - m0)
    return _CD_TABLE[-1][1]
