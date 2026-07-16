"""Pure optimal-guidance helpers for point-mass flight models.

The functions in this module know only vectors and scalar limits.  They have no
dependency on game entities, phases, weapons, or world state, which keeps them
suitable for deterministic unit tests and reuse by each missile family.

Axes are not assumed by the maths.  Callers may use the game's X=east, Y=up,
Z=north convention directly.
"""

from __future__ import annotations

import math
from typing import NamedTuple

import numpy as np


DEFAULT_MIN_TGO = 0.05
DEFAULT_MAX_TGO = 3_600.0
DEFAULT_CLOSING_EPS = 1e-6
DEFAULT_RANGE_EPS = 1e-9


class TimeToGoEstimate(NamedTuple):
    """Bounded constant-velocity time-to-go estimate and its diagnostics.

    ``raw_tgo`` is range/closing-speed while the current geometry is closing.
    Otherwise it is the positive constant-speed intercept root obtained by
    allowing the missile to turn instantaneously; it is ``inf`` when no such
    root exists.  ``tgo`` is always clamped to the requested finite interval.
    """

    tgo: float
    raw_tgo: float
    closing_speed: float
    range_m: float
    closing: bool
    clamped_low: bool
    clamped_high: bool


def _vec3(value, name: str) -> np.ndarray:
    arr = np.asarray(value, dtype=np.float64)
    if arr.shape != (3,):
        raise ValueError(f"{name} must have shape (3,), got {arr.shape}")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must contain only finite values")
    return arr


def _validate_estimator_limits(min_tgo: float, max_tgo: float,
                               closing_epsilon: float,
                               range_epsilon: float):
    min_tgo = float(min_tgo)
    max_tgo = float(max_tgo)
    closing_epsilon = float(closing_epsilon)
    range_epsilon = float(range_epsilon)
    if not math.isfinite(min_tgo) or min_tgo <= 0.0:
        raise ValueError("min_tgo must be finite and > 0")
    if not math.isfinite(max_tgo) or max_tgo < min_tgo:
        raise ValueError("max_tgo must be finite and >= min_tgo")
    if not math.isfinite(closing_epsilon) or closing_epsilon < 0.0:
        raise ValueError("closing_epsilon must be finite and >= 0")
    if not math.isfinite(range_epsilon) or range_epsilon <= 0.0:
        raise ValueError("range_epsilon must be finite and > 0")
    return min_tgo, max_tgo, closing_epsilon, range_epsilon


def _validate_max_accel(max_accel: float) -> float:
    max_accel = float(max_accel)
    if not math.isfinite(max_accel) or max_accel < 0.0:
        raise ValueError("max_accel must be finite and >= 0")
    return max_accel


def _positive_intercept_root(rel_pos: np.ndarray, missile_speed: float,
                             target_vel: np.ndarray) -> float:
    """Earliest positive root of |r + vt*t| = missile_speed*t."""
    a = float(target_vel @ target_vel) - missile_speed * missile_speed
    b = 2.0 * float(rel_pos @ target_vel)
    c = float(rel_pos @ rel_pos)
    scale = max(abs(a), missile_speed * missile_speed,
                float(target_vel @ target_vel), 1.0)
    linear_eps = 1e-12 * scale
    roots = []
    if abs(a) <= linear_eps:
        if abs(b) > 1e-12:
            root = -c / b
            if root > 0.0 and math.isfinite(root):
                roots.append(root)
    else:
        disc = b * b - 4.0 * a * c
        # Roundoff can make a tangent solution microscopically negative.
        disc_eps = 1e-12 * max(b * b, abs(4.0 * a * c), 1.0)
        if disc >= -disc_eps:
            root_disc = math.sqrt(max(disc, 0.0))
            denom = 2.0 * a
            for root in ((-b - root_disc) / denom,
                         (-b + root_disc) / denom):
                if root > 0.0 and math.isfinite(root):
                    roots.append(root)
    return min(roots) if roots else math.inf


def _estimate_from_vectors(mis_pos: np.ndarray, mis_vel: np.ndarray,
                           tgt_pos: np.ndarray, tgt_vel: np.ndarray,
                           min_tgo: float, max_tgo: float,
                           closing_epsilon: float,
                           range_epsilon: float) -> TimeToGoEstimate:
    rel_pos = tgt_pos - mis_pos
    rel_vel = tgt_vel - mis_vel
    range2 = float(rel_pos @ rel_pos)
    if range2 <= range_epsilon * range_epsilon:
        return TimeToGoEstimate(min_tgo, 0.0, 0.0, math.sqrt(range2),
                                False, True, False)

    range_m = math.sqrt(range2)
    closing_speed = -float(rel_pos @ rel_vel) / range_m
    closing = closing_speed > closing_epsilon
    if closing:
        raw_tgo = range_m / closing_speed
    else:
        raw_tgo = _positive_intercept_root(
            rel_pos, math.sqrt(float(mis_vel @ mis_vel)), tgt_vel)

    if not math.isfinite(raw_tgo):
        return TimeToGoEstimate(max_tgo, math.inf, closing_speed, range_m,
                                False, False, True)
    if raw_tgo < min_tgo:
        return TimeToGoEstimate(min_tgo, raw_tgo, closing_speed, range_m,
                                closing, True, False)
    if raw_tgo > max_tgo:
        return TimeToGoEstimate(max_tgo, raw_tgo, closing_speed, range_m,
                                closing, False, True)
    return TimeToGoEstimate(raw_tgo, raw_tgo, closing_speed, range_m,
                            closing, False, False)


def estimate_time_to_go(mis_pos, mis_vel, tgt_pos, tgt_vel, *,
                        min_tgo: float = DEFAULT_MIN_TGO,
                        max_tgo: float = DEFAULT_MAX_TGO,
                        closing_epsilon: float = DEFAULT_CLOSING_EPS,
                        range_epsilon: float = DEFAULT_RANGE_EPS,
                        ) -> TimeToGoEstimate:
    """Estimate closing speed and a safe time-to-go under constant velocity.

    Closing geometry uses the conventional ``range / closing_speed`` estimate.
    Non-closing geometry reports ``closing=False`` and uses an idealized
    constant-speed intercept root only to provide a finite planning horizon.
    Guidance functions below do not feed that optimistic root into ZEM; they
    use bounded pursuit until positive closure is established.
    """
    limits = _validate_estimator_limits(
        min_tgo, max_tgo, closing_epsilon, range_epsilon)
    mp = _vec3(mis_pos, "mis_pos")
    mv = _vec3(mis_vel, "mis_vel")
    tp = _vec3(tgt_pos, "tgt_pos")
    tv = _vec3(tgt_vel, "tgt_vel")
    return _estimate_from_vectors(mp, mv, tp, tv, *limits)


def project_normal(vector, velocity) -> np.ndarray:
    """Return ``vector`` with its component along ``velocity`` removed.

    At exactly zero speed there is no defined along-track direction, so the
    input vector is returned unchanged.  For every nonzero finite velocity the
    projection is exact even at extremely small speeds.
    """
    vec = _vec3(vector, "vector")
    vel = _vec3(velocity, "velocity")
    speed2 = float(vel @ vel)
    if speed2 <= np.finfo(np.float64).tiny:
        return vec.copy()
    return vec - vel * (float(vec @ vel) / speed2)


def _limit_norm(vector: np.ndarray, max_norm: float) -> np.ndarray:
    norm2 = float(vector @ vector)
    if max_norm == 0.0:
        return np.zeros(3, dtype=np.float64)
    if norm2 <= max_norm * max_norm:
        return np.asarray(vector, dtype=np.float64)
    return vector * (max_norm / math.sqrt(norm2))


def _deterministic_normal(velocity: np.ndarray) -> np.ndarray:
    """Stable arbitrary normal used only for an exact target-behind case."""
    speed = math.sqrt(float(velocity @ velocity))
    if speed <= np.finfo(np.float64).tiny:
        return np.array([1.0, 0.0, 0.0])
    vhat = velocity / speed
    axis = np.zeros(3, dtype=np.float64)
    axis[int(np.argmin(np.abs(vhat)))] = 1.0
    normal = axis - vhat * float(axis @ vhat)
    return normal / math.sqrt(float(normal @ normal))


def _bounded_pursuit_from_relative(rel_pos: np.ndarray,
                                   mis_vel: np.ndarray,
                                   max_accel: float,
                                   range_epsilon: float) -> np.ndarray:
    range2 = float(rel_pos @ rel_pos)
    if range2 <= range_epsilon * range_epsilon or max_accel == 0.0:
        return np.zeros(3, dtype=np.float64)
    los = rel_pos / math.sqrt(range2)
    turn = project_normal(los, mis_vel)
    turn2 = float(turn @ turn)
    if turn2 <= 1e-24:
        speed2 = float(mis_vel @ mis_vel)
        if speed2 <= np.finfo(np.float64).tiny:
            turn = los
        else:
            alignment = float(los @ mis_vel) / math.sqrt(speed2)
            if alignment >= 0.0:
                # Straight ahead is already the best attainable direction.
                return np.zeros(3, dtype=np.float64)
            turn = _deterministic_normal(mis_vel)
        turn2 = float(turn @ turn)
    accel = turn * (max_accel / math.sqrt(turn2))
    # Re-project to eliminate the last few ulps of along-track roundoff.
    return _limit_norm(project_normal(accel, mis_vel), max_accel)


def bounded_pursuit_accel(mis_pos, mis_vel, tgt_pos, *,
                          max_accel: float,
                          range_epsilon: float = DEFAULT_RANGE_EPS,
                          ) -> np.ndarray:
    """Bounded normal acceleration that turns toward the current target LOS.

    An exactly anti-parallel target needs an arbitrary turn plane; the chosen
    plane is deterministic and based on the least-aligned Cartesian axis.
    """
    max_accel = _validate_max_accel(max_accel)
    range_epsilon = float(range_epsilon)
    if not math.isfinite(range_epsilon) or range_epsilon <= 0.0:
        raise ValueError("range_epsilon must be finite and > 0")
    mp = _vec3(mis_pos, "mis_pos")
    mv = _vec3(mis_vel, "mis_vel")
    tp = _vec3(tgt_pos, "tgt_pos")
    return _bounded_pursuit_from_relative(
        tp - mp, mv, max_accel, range_epsilon)


def _resolve_horizon(tgo, estimate: TimeToGoEstimate,
                     min_tgo: float, max_tgo: float):
    if tgo is None:
        return estimate.tgo, estimate.clamped_low
    requested = float(tgo)
    if not math.isfinite(requested) or requested <= 0.0:
        return min_tgo, True
    if requested < min_tgo:
        return min_tgo, True
    return min(requested, max_tgo), False


def minimum_effort_zem_accel(mis_pos, mis_vel, tgt_pos, tgt_vel, *,
                             max_accel: float,
                             tgo: float | None = None,
                             min_tgo: float = DEFAULT_MIN_TGO,
                             max_tgo: float = DEFAULT_MAX_TGO,
                             closing_epsilon: float = DEFAULT_CLOSING_EPS,
                             range_epsilon: float = DEFAULT_RANGE_EPS,
                             ) -> np.ndarray:
    """Position-only minimum-effort ZEM command, normal to missile velocity.

    For horizon ``T``, ``ZEM = r + v_rel*T`` and the unconstrained command is
    ``a = 3*ZEM/T**2``.  Non-closing or pathologically short engagements use a
    deterministic bounded-pursuit command instead.  The returned vector always
    has Euclidean norm at most ``max_accel``.
    """
    max_accel = _validate_max_accel(max_accel)
    limits = _validate_estimator_limits(
        min_tgo, max_tgo, closing_epsilon, range_epsilon)
    min_tgo, max_tgo, closing_epsilon, range_epsilon = limits
    mp = _vec3(mis_pos, "mis_pos")
    mv = _vec3(mis_vel, "mis_vel")
    tp = _vec3(tgt_pos, "tgt_pos")
    tv = _vec3(tgt_vel, "tgt_vel")
    rel_pos = tp - mp
    if float(rel_pos @ rel_pos) <= range_epsilon * range_epsilon:
        return np.zeros(3, dtype=np.float64)
    estimate = _estimate_from_vectors(mp, mv, tp, tv, *limits)
    horizon, short_horizon = _resolve_horizon(
        tgo, estimate, min_tgo, max_tgo)
    if not estimate.closing or short_horizon:
        return _bounded_pursuit_from_relative(
            rel_pos, mv, max_accel, range_epsilon)

    zem = rel_pos + (tv - mv) * horizon
    command = project_normal(3.0 * zem / (horizon * horizon), mv)
    return _limit_norm(command, max_accel)


def genex_accel(mis_pos, mis_vel, tgt_pos, tgt_vel,
                 desired_missile_velocity, *,
                 max_accel: float,
                 tgo: float | None = None,
                 min_tgo: float = DEFAULT_MIN_TGO,
                 max_tgo: float = DEFAULT_MAX_TGO,
                 closing_epsilon: float = DEFAULT_CLOSING_EPS,
                 range_epsilon: float = DEFAULT_RANGE_EPS,
                 ) -> np.ndarray:
    """GENEX-style minimum-effort position + terminal-velocity command.

    ``desired_missile_velocity`` is an inertial velocity vector at intercept.
    With ``ZEM = r + v_rel*T`` and ``dv = desired_velocity - mis_vel``, the
    lag-free minimum-effort initial command is

        ``a = 6*ZEM/T**2 - 2*dv/T``.

    Longitudinal demand is removed because a point-mass aerodynamic autopilot
    can bend the flight path but cannot create along-track thrust.  The same
    bounded pursuit fallback as the position-only law handles non-closing and
    very short engagements.
    """
    max_accel = _validate_max_accel(max_accel)
    limits = _validate_estimator_limits(
        min_tgo, max_tgo, closing_epsilon, range_epsilon)
    min_tgo, max_tgo, closing_epsilon, range_epsilon = limits
    mp = _vec3(mis_pos, "mis_pos")
    mv = _vec3(mis_vel, "mis_vel")
    tp = _vec3(tgt_pos, "tgt_pos")
    tv = _vec3(tgt_vel, "tgt_vel")
    desired_vel = _vec3(desired_missile_velocity,
                        "desired_missile_velocity")
    rel_pos = tp - mp
    if float(rel_pos @ rel_pos) <= range_epsilon * range_epsilon:
        return np.zeros(3, dtype=np.float64)
    estimate = _estimate_from_vectors(mp, mv, tp, tv, *limits)
    horizon, short_horizon = _resolve_horizon(
        tgo, estimate, min_tgo, max_tgo)
    if not estimate.closing or short_horizon:
        return _bounded_pursuit_from_relative(
            rel_pos, mv, max_accel, range_epsilon)

    zem = rel_pos + (tv - mv) * horizon
    delta_velocity = desired_vel - mv
    command = (6.0 * zem / (horizon * horizon)
               - 2.0 * delta_velocity / horizon)
    command = project_normal(command, mv)
    return _limit_norm(command, max_accel)


__all__ = [
    "TimeToGoEstimate",
    "bounded_pursuit_accel",
    "estimate_time_to_go",
    "genex_accel",
    "minimum_effort_zem_accel",
    "project_normal",
]
