"""Deterministic online energy-aware flight planning for guided missiles.

This module deliberately does *not* own launch sequencing, seekers, fuses, or
the 120 Hz point-mass integrator.  It is a small receding-horizon flight
computer shared by :mod:`sim.missile`, :mod:`sim.strike`, and :mod:`sim.sam`:

* production code supplies the live state, the true remaining route, and a
  terrain-height callback;
* the computer evaluates a bounded set of vertical corridors with a coarse
  spatial rollout using the same atmosphere/aerodynamic helpers as the sim;
* the selected command is cached for ``REPLAN_INTERVAL_S`` and contains a
  flight-path-normal acceleration command plus predicted terminal energy;
* launch phases remain completely outside this module.

The rollout is intentionally an engagement-sim predictor, not a second
high-fidelity dynamics engine.  Its job is to answer "which broad vertical
corridor leaves the best reachable terminal state?" cheaply and repeatedly.
All candidate ordering and tie-breaking is fixed, so identical inputs are bit
deterministic on the same Python/numpy build.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import math
from typing import Callable, Sequence

from sim.aero import (ALPHA_TAX, CL_MAX_CRUISE, CL_MAX_STRIKE,
                      induced_drag_scalar, lag_gain, q_scalar)
from sim.physics import (GRAVITY, cd_from_mach_scalar, drag_force_scalar,
                         mach_scalar, speed_of_sound_scalar)


REPLAN_INTERVAL_S = 0.25
MAX_ROLLOUT_STEPS = 224
TERMINAL_ROLLOUT_STEPS = 64
DEBUG_PATH_STRIDE = 8
PATH_RESPONSE_TAU_S = 0.8
LINE_CLEAR_SAMPLES = 16

_GAMMA_EPS = math.radians(0.75)
_EPS = 1e-9


class FlightMode(IntEnum):
    """Internal vertical intent; host machines map this to legacy phases."""

    CLIMB = 0
    CRUISE = 1
    DESCEND = 2
    TERMINAL = 3


@dataclass(frozen=True, slots=True)
class AirframeEnvelope:
    """Airframe/propulsion limits needed by the online predictor.

    ``preferred_alt_m`` is ASL unless ``preferred_alt_is_agl`` is true.
    ``path_normal_accel_mps2`` emitted by the computer is a *kinematic path*
    command (positive pulls flight-path angle upward); gravity compensation is
    the executor's responsibility.
    """

    ref_area_m2: float
    cl_max: float
    max_g: float
    k_induced: float
    dry_mass_kg: float
    fuel_capacity_kg: float
    max_thrust_n: float
    isp_s: float
    thrust_tau_s: float
    preferred_mach: float
    low_mach: float
    preferred_alt_m: float
    preferred_alt_is_agl: bool
    deck_agl_m: float
    max_climb_gamma_rad: float
    max_descent_gamma_rad: float
    terminal_speed_min_mps: float
    fuel_reserve_kg: float = 0.0
    control_lookahead_m: float = 10_000.0
    altitude_preview_m: float = 10_000.0
    terminal_capture_fraction: float | None = None
    latch_infeasible_midcourse: bool = False
    energy_fallback_floor_fraction: float = 0.5
    energy_fallback_min_range_m: float = 100_000.0
    energy_fallback_near_scale: float = 2.5
    energy_fallback_far_scale: float = 5.0
    long_range_control_lookahead_m: float | None = None
    long_range_control_start_m: float = 120_000.0
    long_range_control_full_m: float = 200_000.0
    corridor_switch_penalty: float = 1.0
    corridor_min_hold_s: float = 0.5

    def __post_init__(self) -> None:
        positive = {
            "ref_area_m2": self.ref_area_m2,
            "cl_max": self.cl_max,
            "max_g": self.max_g,
            "dry_mass_kg": self.dry_mass_kg,
            "isp_s": self.isp_s,
            "preferred_mach": self.preferred_mach,
            "low_mach": self.low_mach,
            "terminal_speed_min_mps": self.terminal_speed_min_mps,
        }
        for name, value in positive.items():
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and > 0")
        if self.max_thrust_n < 0.0 or self.thrust_tau_s < 0.0:
            raise ValueError("thrust values must be non-negative")
        if self.fuel_capacity_kg < 0.0 or self.fuel_reserve_kg < 0.0:
            raise ValueError("fuel values must be non-negative")
        if (not math.isfinite(self.control_lookahead_m)
                or self.control_lookahead_m <= 0.0):
            raise ValueError("control_lookahead_m must be finite and > 0")
        if (not math.isfinite(self.altitude_preview_m)
                or self.altitude_preview_m <= 0.0):
            raise ValueError("altitude_preview_m must be finite and > 0")
        if (self.terminal_capture_fraction is not None
                and not (0.0 < self.terminal_capture_fraction <= 1.0)):
            raise ValueError("terminal_capture_fraction must be in (0, 1]")
        if not (0.0 < self.energy_fallback_floor_fraction <= 1.0):
            raise ValueError(
                "energy_fallback_floor_fraction must be in (0, 1]")
        if (not math.isfinite(self.energy_fallback_min_range_m)
                or self.energy_fallback_min_range_m < 0.0):
            raise ValueError(
                "energy_fallback_min_range_m must be finite and >= 0")
        if (not math.isfinite(self.energy_fallback_near_scale)
                or self.energy_fallback_near_scale <= 0.0):
            raise ValueError("energy_fallback_near_scale must be finite and > 0")
        if (not math.isfinite(self.energy_fallback_far_scale)
                or self.energy_fallback_far_scale
                <= self.energy_fallback_near_scale):
            raise ValueError(
                "energy_fallback_far_scale must exceed near scale")
        if (self.long_range_control_lookahead_m is not None
                and (not math.isfinite(self.long_range_control_lookahead_m)
                     or self.long_range_control_lookahead_m <= 0.0)):
            raise ValueError(
                "long_range_control_lookahead_m must be finite and > 0")
        if (not math.isfinite(self.long_range_control_start_m)
                or not math.isfinite(self.long_range_control_full_m)
                or self.long_range_control_start_m < 0.0
                or self.long_range_control_full_m
                <= self.long_range_control_start_m):
            raise ValueError("long-range control interval is invalid")
        if (not math.isfinite(self.corridor_switch_penalty)
                or self.corridor_switch_penalty < 0.0):
            raise ValueError(
                "corridor_switch_penalty must be finite and >= 0")
        if (not math.isfinite(self.corridor_min_hold_s)
                or self.corridor_min_hold_s < 0.0):
            raise ValueError("corridor_min_hold_s must be finite and >= 0")
        if not (0.0 < self.max_climb_gamma_rad < math.pi * 0.5):
            raise ValueError("max_climb_gamma_rad must be in (0, pi/2)")
        if not (0.0 < self.max_descent_gamma_rad < math.pi * 0.5):
            raise ValueError("max_descent_gamma_rad must be in (0, pi/2)")

    @classmethod
    def from_weapon(cls, weapon, family: str, profile: str | None = None):
        """Build an envelope from an existing ``WeaponDef``/``StrikeDef``.

        This duck-typed factory keeps arsenal and missile constructors
        unchanged.  It intentionally derives conservative defaults from fields
        already present; weapon-specific policy can later instantiate the
        dataclass directly without changing this module's API.
        """

        family = str(family).lower()
        if family not in ("missile", "strike", "arm"):
            raise ValueError("family must be 'missile', 'strike', or 'arm'")

        fuel = max(0.0, float(weapon.fuel_mass))
        dry = max(1.0, float(weapon.launch_mass) - fuel)
        cl_default = CL_MAX_CRUISE if family == "missile" else CL_MAX_STRIKE
        cl_max = float(getattr(weapon, "cl_max", 0.0) or cl_default)
        k_ind = float(getattr(weapon, "k_induced", 0.0)
                      or (ALPHA_TAX / cl_max))
        thrust_tau = max(0.0, float(getattr(weapon, "thrust_tau", 0.0)))

        if family == "missile":
            hi = profile == "hi-lo"
            preferred_mach = float(
                weapon.cruise_mach_hi if hi else weapon.cruise_mach_lo)
            low_mach = float(weapon.cruise_mach_lo)
            preferred_alt = float(
                weapon.cruise_alt_hi if hi else weapon.lo_alt)
            # The low-level *midcourse* deck is the declared lo-lo altitude.
            # Terminal skim altitude is a separate mission handover value;
            # using it here made the planner cruise an Oniks at 12 m instead
            # of its 60 m low-level band and left no terrain-follow margin.
            deck_agl = float(weapon.lo_alt)
            # Existing per-weapon sink fields remain physical envelope hints,
            # never a fixed descent clock.
            sink = float(getattr(weapon, "descent_max_sink", 0.0))
            ref_speed = max(low_mach * 340.3, 1.0)
            descent_gamma = (math.atan2(sink, ref_speed) if sink > 0.0
                             else math.radians(25.0 if hi else 5.0))
            preferred_is_agl = False
        else:
            preferred_mach = low_mach = float(weapon.cruise_mach)
            preferred_alt = float(weapon.cruise_alt)
            deck_agl = min(preferred_alt, 60.0)
            weapon_id = str(getattr(weapon, "weapon_id", ""))
            if family == "arm" and weapon_id == "kh31p":
                # The legacy 3.5 km PD command naturally zoomed the Kh-31P
                # into a measured 15-20 km energy loft.  Make that usable
                # optimizer ceiling explicit rather than relying on overshoot.
                preferred_alt = 16_000.0
            preferred_is_agl = family != "arm" and weapon_id not in {
                "harm", "kh31p"
            }
            descent_gamma = math.radians(40.0 if family == "arm" else 18.0)

        min_terminal = max(30.0, low_mach * 340.3 * 0.65)
        return cls(
            ref_area_m2=float(weapon.ref_area),
            cl_max=cl_max,
            max_g=float(weapon.max_g),
            k_induced=k_ind,
            dry_mass_kg=dry,
            fuel_capacity_kg=fuel,
            max_thrust_n=max(0.0, float(weapon.max_thrust)),
            isp_s=float(weapon.isp),
            thrust_tau_s=thrust_tau,
            preferred_mach=preferred_mach,
            low_mach=low_mach,
            preferred_alt_m=preferred_alt,
            preferred_alt_is_agl=preferred_is_agl,
            deck_agl_m=max(0.0, deck_agl),
            max_climb_gamma_rad=math.radians(
                45.0 if family == "arm" else 20.0),
            max_descent_gamma_rad=min(math.radians(40.0),
                                      max(math.radians(5.0), descent_gamma)),
            terminal_speed_min_mps=min_terminal,
            fuel_reserve_kg=0.05 * fuel,
            control_lookahead_m=(2_000.0 if family == "arm" else 10_000.0),
            altitude_preview_m=(2_000.0 if family == "arm" else 10_000.0),
        )


@dataclass(frozen=True, slots=True)
class FlightState:
    """Live state sampled from a production missile at a replan instant."""

    pos: Sequence[float]
    vel: Sequence[float]
    mass_kg: float
    fuel_kg: float
    thrust_actual_n: float = 0.0
    time_s: float = 0.0


@dataclass(frozen=True, slots=True)
class MissionSnapshot:
    """Current mission geometry supplied by the host flight machine.

    ``path_xz`` contains every *remaining* waypoint followed by the final
    target.  The current position is deliberately not included; it comes from
    :class:`FlightState`, preventing direct-target distance from silently
    replacing true route distance.
    """

    path_xz: Sequence[Sequence[float]]
    target_y_m: float = 0.0
    preferred_altitude_m: float | None = None
    terminal_handover_alt_m: float | None = None
    terminal_handover_range_m: float | None = None
    allow_high: bool = True
    terminal_armed: bool = True
    terminal_latched: bool = False
    terminal_commit_max_m: float = 2_000.0

    def __post_init__(self) -> None:
        if len(self.path_xz) == 0:
            raise ValueError("path_xz must contain at least the final target")
        if self.terminal_commit_max_m < 0.0:
            raise ValueError("terminal_commit_max_m must be non-negative")
        if (self.terminal_handover_alt_m is not None
                and not math.isfinite(self.terminal_handover_alt_m)):
            raise ValueError("terminal_handover_alt_m must be finite")
        if (self.terminal_handover_range_m is not None
                and (not math.isfinite(self.terminal_handover_range_m)
                     or self.terminal_handover_range_m < 0.0)):
            raise ValueError("terminal_handover_range_m must be finite and >= 0")
        if (self.preferred_altitude_m is not None
                and not math.isfinite(self.preferred_altitude_m)):
            raise ValueError("preferred_altitude_m must be finite")


@dataclass(frozen=True, slots=True)
class EnergyPrediction:
    """Predicted state at the final target for one selected corridor."""

    feasible: bool
    route_range_m: float
    time_to_go_s: float
    terminal_speed_mps: float
    terminal_fuel_kg: float
    terminal_specific_energy_jkg: float
    energy_margin_jkg: float
    min_clearance_m: float
    terminal_altitude_error_m: float
    rollout_samples: int
    corridor: str
    cost: float


@dataclass(frozen=True, slots=True)
class FlightCommand:
    """Cached command consumed by each 120 Hz inner-loop executor."""

    mode: FlightMode
    target_path_gamma_rad: float
    path_normal_accel_mps2: float
    altitude_ref_asl_m: float
    vertical_rate_ref_mps: float
    target_mach: float
    terminal_commit: bool
    prediction: EnergyPrediction
    plan_id: int


@dataclass(frozen=True, slots=True)
class FlightComputerCandidateDebug:
    """One real rollout considered by the latest online replan."""

    name: str
    selected: bool
    feasible: bool
    cost: float
    terminal_speed_mps: float
    terminal_fuel_kg: float
    energy_margin_jkg: float
    min_clearance_m: float
    terminal_altitude_error_m: float
    path_world: tuple[tuple[float, float, float], ...]


@dataclass(frozen=True, slots=True)
class FlightComputerDebugSnapshot:
    """Read-only visualization data from the latest production replan."""

    plan_id: int
    selected: str
    route_range_m: float
    gamma_command_rad: float
    path_accel_mps2: float
    candidates: tuple[FlightComputerCandidateDebug, ...]


@dataclass(frozen=True, slots=True)
class _Corridor:
    name: str
    kind: str
    profile_penalty: float
    preferred_fraction: float = 0.5


@dataclass(frozen=True, slots=True)
class _RolloutResult:
    prediction: EnergyPrediction
    immediate_alt_ref: float
    immediate_gamma_ref: float
    target_mach: float
    debug_path: tuple[tuple[float, float, float], ...] = ()


@dataclass(frozen=True, slots=True)
class _RouteStep:
    distance_m: float
    surface_m: float
    next_surface_m: float
    curvature_radpm: float
    remaining_m: float


@dataclass(frozen=True, slots=True)
class _RolloutGrid:
    steps: tuple[_RouteStep, ...]
    immediate_step_m: float


def route_arc_length_m(pos: Sequence[float],
                       path_xz: Sequence[Sequence[float]]) -> float:
    """True horizontal arc length through all remaining path points."""

    px, pz = float(pos[0]), float(pos[2])
    total = 0.0
    for point in path_xz:
        x, z = float(point[0]), float(point[1])
        total += math.hypot(x - px, z - pz)
        px, pz = x, z
    return total


class _RouteGeometry:
    """Small polyline helper used only during a bounded replan."""

    __slots__ = ("points", "segments", "total")

    def __init__(self, pos: Sequence[float],
                 path_xz: Sequence[Sequence[float]]):
        pts = [(float(pos[0]), float(pos[2]))]
        pts.extend((float(p[0]), float(p[1])) for p in path_xz)
        segments = []
        total = 0.0
        for (x0, z0), (x1, z1) in zip(pts, pts[1:]):
            dx, dz = x1 - x0, z1 - z0
            length = math.hypot(dx, dz)
            if length <= _EPS:
                continue
            heading = math.atan2(dx, dz)
            segments.append((total, total + length, x0, z0, dx, dz,
                             length, heading))
            total += length
        self.points = pts
        self.segments = tuple(segments)
        self.total = total

    def sample(self, distance_m: float) -> tuple[float, float, float]:
        if not self.segments:
            x, z = self.points[-1]
            return x, z, 0.0
        s = min(max(float(distance_m), 0.0), self.total)
        for s0, s1, x0, z0, dx, dz, length, heading in self.segments:
            if s <= s1 + _EPS:
                f = min(max((s - s0) / length, 0.0), 1.0)
                return x0 + dx * f, z0 + dz * f, heading
        *_, x0, z0, dx, dz, _length, heading = self.segments[-1]
        return x0 + dx, z0 + dz, heading

    def curvature(self, distance_m: float, probe_m: float) -> float:
        if self.total <= _EPS:
            return 0.0
        s0 = max(0.0, distance_m - probe_m)
        s1 = min(self.total, distance_m + probe_m)
        if s1 - s0 <= _EPS:
            return 0.0
        h0 = self.sample(s0)[2]
        h1 = self.sample(s1)[2]
        dh = (h1 - h0 + math.pi) % (2.0 * math.pi) - math.pi
        return dh / (s1 - s0)


def _clip(value: float, lo: float, hi: float) -> float:
    return min(max(value, lo), hi)


def _speed(vel: Sequence[float]) -> float:
    vx, vy, vz = float(vel[0]), float(vel[1]), float(vel[2])
    return math.sqrt(vx * vx + vy * vy + vz * vz)


def _flight_path_gamma(vel: Sequence[float]) -> float:
    return math.atan2(float(vel[1]),
                      math.hypot(float(vel[0]), float(vel[2])))


class OnlineFlightComputer:
    """Bounded deterministic receding-horizon vertical flight computer."""

    def __init__(self, envelope: AirframeEnvelope,
                 replan_interval_s: float = REPLAN_INTERVAL_S):
        if replan_interval_s <= 0.0 or not math.isfinite(replan_interval_s):
            raise ValueError("replan_interval_s must be finite and > 0")
        self.envelope = envelope
        self.replan_interval_s = float(replan_interval_s)
        self._since_replan = 0.0
        self._dirty = True
        self._mission_signature = None
        self._command: FlightCommand | None = None
        self._plan_id = 0
        self._terminal_latched = False
        self._energy_fallback_latched = False
        self._energy_fallback_fraction = 0.5
        self._long_range_control_blend = 0.0
        self._last_gamma_cmd = 0.0
        self._last_corridor: str | None = None
        self._corridor_age_s = 0.0
        self._debug_enabled = False
        self._debug_snapshot: FlightComputerDebugSnapshot | None = None

    @property
    def last_command(self) -> FlightCommand | None:
        return self._command

    @property
    def replan_count(self) -> int:
        return self._plan_id

    @property
    def debug_enabled(self) -> bool:
        return self._debug_enabled

    @property
    def debug_snapshot(self) -> FlightComputerDebugSnapshot | None:
        return self._debug_snapshot

    def set_debug_enabled(self, enabled: bool) -> None:
        """Collect decimated paths only while the in-camera overlay is on."""

        enabled = bool(enabled)
        if enabled == self._debug_enabled:
            return
        self._debug_enabled = enabled
        self._debug_snapshot = None
        self._dirty = True

    def invalidate(self, reason: str = "external") -> None:
        """Force the next update to replan; ``reason`` is telemetry-ready."""

        del reason  # Reserved for integration telemetry without affecting API.
        self._dirty = True

    def force_terminal(self) -> None:
        """Latch terminal intent (used when an existing seeker is committed)."""

        self._terminal_latched = True
        self._dirty = True

    def update(self, dt: float, state: FlightState, mission: MissionSnapshot,
               surface_height_at: Callable[[float, float], float]) -> FlightCommand:
        if dt < 0.0 or not math.isfinite(dt):
            raise ValueError("dt must be finite and non-negative")
        signature = self._signature(mission)
        if signature != self._mission_signature:
            self._mission_signature = signature
            self._dirty = True
        if mission.terminal_latched and not self._terminal_latched:
            self._terminal_latched = True
            self._dirty = True

        self._since_replan += dt
        self._corridor_age_s += dt
        due = self._command is None or self._since_replan + 1e-12 >= \
            self.replan_interval_s
        if self._dirty or due:
            if due and self._command is not None:
                self._since_replan %= self.replan_interval_s
            else:
                self._since_replan = 0.0
            self._command = self._replan(state, mission, surface_height_at)
            self._dirty = False
        return self._command

    @staticmethod
    def _signature(mission: MissionSnapshot):
        path = tuple((float(p[0]), float(p[1])) for p in mission.path_xz)
        return (path, float(mission.target_y_m),
                (None if mission.preferred_altitude_m is None else
                 float(mission.preferred_altitude_m)),
                (None if mission.terminal_handover_alt_m is None else
                 float(mission.terminal_handover_alt_m)),
                (None if mission.terminal_handover_range_m is None else
                 float(mission.terminal_handover_range_m)),
                bool(mission.allow_high),
                bool(mission.terminal_armed), bool(mission.terminal_latched),
                float(mission.terminal_commit_max_m))

    def _corridors(self, mission: MissionSnapshot) -> tuple[_Corridor, ...]:
        env = self.envelope
        if mission.allow_high and not env.preferred_alt_is_agl:
            return (
                _Corridor("preferred", "preferred", 0.0),
                _Corridor("mid", "mid", 1.5),
                _Corridor("hold", "hold", 3.0),
                _Corridor("deck", "deck", 7.0),
                _Corridor("direct", "direct", 15.0),
            )
        return (
            _Corridor("deck", "deck", 0.0),
            _Corridor("preferred", "preferred", 0.5),
            _Corridor("hold", "hold", 2.0),
            _Corridor("mid", "mid", 3.0),
            _Corridor("direct", "direct", 12.0),
        )

    def _control_lookahead(self, route_range_m: float) -> float:
        env = self.envelope
        long_value = env.long_range_control_lookahead_m
        if long_value is None:
            return env.control_lookahead_m
        blend = _clip(
            (route_range_m - env.long_range_control_start_m)
            / (env.long_range_control_full_m
               - env.long_range_control_start_m), 0.0, 1.0)
        if self._energy_fallback_latched and not self._terminal_latched:
            # Preserve the horizon chosen for the original long shot.  Letting
            # it collapse as range counted down erased the optimized coast and
            # made a 300 km receding intercept run out of energy 434 m short.
            self._long_range_control_blend = max(
                self._long_range_control_blend, blend)
            blend = self._long_range_control_blend
        return (env.control_lookahead_m
                + blend * (long_value - env.control_lookahead_m))

    def _replan(self, state: FlightState, mission: MissionSnapshot,
                surface_height_at: Callable[[float, float], float]) -> FlightCommand:
        route = _RouteGeometry(state.pos, mission.path_xz)
        grid = self._build_rollout_grid(route, mission, surface_height_at)
        energy_active = (self._energy_fallback_latched
                         and not self._terminal_latched)
        # Once a long-range round has latched the continuous energy corridor,
        # the five ordinary corridors cannot be selected until terminal.  Do
        # not spend ~80% of batch runtime recomputing rejected alternatives.
        # F5/FULL telemetry still requests them explicitly for comparison.
        if energy_active and not self._debug_enabled:
            results = []
        else:
            candidates = self._corridors(mission)
            results = [self._rollout(c, route, grid, state, mission,
                                     surface_height_at)
                       for c in candidates]

        feasible_results = [
            (index, result) for index, result in enumerate(results)
            if result.prediction.feasible]

        # A long mission can initially make every finite-horizon candidate
        # miss its terminal speed/altitude tolerance.  Ranking those failed
        # rollouts by smallest terrain/altitude deficit made the controller
        # choose HOLD/DECK, throw away the boost loft, and skim hundreds of
        # kilometres until impact.  Preserve energy instead with a continuous
        # corridor: medium shots retain the preferred loft, while increasing
        # range smoothly blends toward the drag-efficient 50/50 altitude.
        # The reference is still recomputed from live state, target,
        # atmosphere and terrain every replan; the latch stabilizes the
        # objective, not the path.
        fallback_near = max(
            self.envelope.energy_fallback_min_range_m,
            self.envelope.energy_fallback_near_scale
            * self.envelope.preferred_alt_m)
        fallback_far = max(
            fallback_near + 1.0,
            self.envelope.energy_fallback_far_scale
            * self.envelope.preferred_alt_m)
        long_high_mission = (
            self.envelope.latch_infeasible_midcourse
            and mission.allow_high
            and not self.envelope.preferred_alt_is_agl
            and route.total >= fallback_near)
        if (not energy_active and not feasible_results
                and long_high_mission):
            blend = _clip(
                (route.total - fallback_near)
                / (fallback_far - fallback_near), 0.0, 1.0)
            floor = self.envelope.energy_fallback_floor_fraction
            self._energy_fallback_fraction = 1.0 - (1.0 - floor) * blend
            self._energy_fallback_latched = True

        debug_results = list(results)
        if self._energy_fallback_latched and not self._terminal_latched:
            energy_corridor = _Corridor(
                "energy", "energy", 0.0,
                self._energy_fallback_fraction)
            best = self._rollout(
                energy_corridor, route, grid, state, mission,
                surface_height_at)
            debug_results.append(best)
        else:
            def rank(item):
                index, result = item
                pred = result.prediction
                if pred.feasible:
                    return 0, pred.cost, index
                clearance_deficit = max(0.0, -pred.min_clearance_m)
                energy_deficit = max(0.0, -pred.energy_margin_jkg)
                fuel_deficit = max(0.0, self.envelope.fuel_reserve_kg
                                   - pred.terminal_fuel_kg)
                altitude_deficit = abs(pred.terminal_altitude_error_m)
                deficit = (clearance_deficit * 1.0e7
                           + energy_deficit * 1.0e3
                           + fuel_deficit * 1.0e5
                           + altitude_deficit * 1.0e4
                           + pred.cost)
                return 1, deficit, index

            _, best = min(enumerate(results), key=rank)
            # A broad vertical mode is not a 4 Hz actuator.  Hold the current
            # corridor briefly when both old and new predictions have the
            # same feasibility class.  A newly feasible escape path may
            # always interrupt the dwell, as may terminal guidance below.
            if (self._last_corridor is not None
                    and self._corridor_age_s
                    < self.envelope.corridor_min_hold_s
                    and not self._terminal_latched
                    and best.prediction.corridor != self._last_corridor):
                previous = next(
                    (result for result in results
                     if result.prediction.corridor == self._last_corridor),
                    None)
                if (previous is not None
                        and (previous.prediction.feasible
                             or not best.prediction.feasible)):
                    best = previous
        gamma_ref = best.immediate_gamma_ref
        speed = max(_speed(state.vel), 1.0)
        gamma_now = _flight_path_gamma(state.vel)
        q = q_scalar(speed, float(state.pos[1]))
        a_q = q * self.envelope.ref_area_m2 * self.envelope.cl_max \
            / max(float(state.mass_kg), 1.0)
        a_cap = min(self.envelope.max_g * GRAVITY, a_q)
        path_a = _clip((gamma_ref - gamma_now) * speed / PATH_RESPONSE_TAU_S,
                       -a_cap, a_cap)

        remaining = route.total
        terminal_clear = self._terminal_line_clear(
            state, mission, surface_height_at)
        commit = self._terminal_latched or (
            mission.terminal_armed
            and remaining <= mission.terminal_commit_max_m
            and terminal_clear)
        if commit:
            self._terminal_latched = True
            mode = FlightMode.TERMINAL
        elif gamma_ref > _GAMMA_EPS:
            mode = FlightMode.CLIMB
        elif gamma_ref < -_GAMMA_EPS:
            mode = FlightMode.DESCEND
        else:
            mode = FlightMode.CRUISE

        self._plan_id += 1
        switched_corridor = (
            self._last_corridor is not None
            and best.prediction.corridor != self._last_corridor)
        self._last_gamma_cmd = gamma_ref
        self._last_corridor = best.prediction.corridor
        if switched_corridor:
            self._corridor_age_s = 0.0
        if self._debug_enabled:
            self._debug_snapshot = FlightComputerDebugSnapshot(
                plan_id=self._plan_id,
                selected=best.prediction.corridor,
                route_range_m=remaining,
                gamma_command_rad=gamma_ref,
                path_accel_mps2=path_a,
                candidates=tuple(
                    FlightComputerCandidateDebug(
                        name=result.prediction.corridor,
                        selected=result is best,
                        feasible=result.prediction.feasible,
                        cost=result.prediction.cost,
                        terminal_speed_mps=(
                            result.prediction.terminal_speed_mps),
                        terminal_fuel_kg=result.prediction.terminal_fuel_kg,
                        energy_margin_jkg=(
                            result.prediction.energy_margin_jkg),
                        min_clearance_m=(
                            result.prediction.min_clearance_m),
                        terminal_altitude_error_m=(
                            result.prediction.terminal_altitude_error_m),
                        path_world=result.debug_path,
                    )
                    for result in debug_results),
            )
        return FlightCommand(
            mode=mode,
            target_path_gamma_rad=gamma_ref,
            path_normal_accel_mps2=path_a,
            altitude_ref_asl_m=best.immediate_alt_ref,
            vertical_rate_ref_mps=speed * math.sin(gamma_ref),
            target_mach=best.target_mach,
            terminal_commit=commit,
            prediction=best.prediction,
            plan_id=self._plan_id,
        )

    @staticmethod
    def _build_rollout_grid(
            route: _RouteGeometry, mission: MissionSnapshot,
            surface_height_at: Callable[[float, float], float]
            ) -> _RolloutGrid:
        total = route.total
        if total <= _EPS:
            return _RolloutGrid((), 0.0)
        # Non-uniform bounded grid: long-range weapons get coarse far-field
        # samples, while 64 samples are always reserved for the final 20 km
        # (or the whole route when shorter).  Unlike a capped uniform step,
        # this reaches even a 2,000 km target within MAX_ROLLOUT_STEPS without
        # sacrificing terminal-impact resolution.
        terminal_zone = min(
            total, max(20_000.0, 4.0 * mission.terminal_commit_max_m))
        far_length = total - terminal_zone
        far_budget = MAX_ROLLOUT_STEPS - TERMINAL_ROLLOUT_STEPS
        far_step = (far_length / far_budget if far_length > _EPS else 0.0)
        terminal_step = terminal_zone / TERMINAL_ROLLOUT_STEPS
        step_sizes = []
        if far_length > _EPS:
            step_sizes.extend([far_step] * (far_budget - 1))
            step_sizes.append(far_length - far_step * (far_budget - 1))
        if terminal_zone > _EPS:
            step_sizes.extend([terminal_step] * (TERMINAL_ROLLOUT_STEPS - 1))
            step_sizes.append(
                terminal_zone - terminal_step * (TERMINAL_ROLLOUT_STEPS - 1))

        travelled = 0.0
        steps = []
        for ds in step_sizes:
            x, z, _ = route.sample(travelled)
            nx, nz, _ = route.sample(travelled + ds)
            steps.append(_RouteStep(
                distance_m=ds,
                surface_m=float(surface_height_at(x, z)),
                next_surface_m=float(surface_height_at(nx, nz)),
                curvature_radpm=route.curvature(
                    travelled, max(ds, 500.0)),
                remaining_m=total - travelled,
            ))
            travelled += ds
        immediate = far_step if far_length > _EPS else terminal_step
        return _RolloutGrid(tuple(steps), immediate)

    def _rollout(self, corridor: _Corridor, route: _RouteGeometry,
                 grid: _RolloutGrid,
                 state: FlightState, mission: MissionSnapshot,
                 surface_height_at: Callable[[float, float], float]
                 ) -> _RolloutResult:
        env = self.envelope
        total = route.total
        initial_alt = float(state.pos[1])
        initial_speed = max(_speed(state.vel), 1.0)
        gamma = _clip(_flight_path_gamma(state.vel),
                      -env.max_descent_gamma_rad, env.max_climb_gamma_rad)
        fuel = max(0.0, float(state.fuel_kg))
        nonfuel_mass = max(env.dry_mass_kg,
                           float(state.mass_kg) - fuel)
        thrust_actual = max(0.0, float(state.thrust_actual_n))
        altitude = initial_alt
        speed = initial_speed
        time_s = 0.0
        min_clearance = float("inf")
        samples = 0
        debug_path = ([(float(state.pos[0]), initial_alt,
                        float(state.pos[2]))]
                      if self._debug_enabled else None)

        if total <= _EPS:
            terminal_energy = 0.5 * speed * speed + GRAVITY * altitude
            required = (0.5 * env.terminal_speed_min_mps ** 2
                        + GRAVITY * mission.target_y_m)
            prediction = EnergyPrediction(
                feasible=altitude >= mission.target_y_m - 1.0,
                route_range_m=0.0,
                time_to_go_s=0.0,
                terminal_speed_mps=speed,
                terminal_fuel_kg=fuel,
                terminal_specific_energy_jkg=terminal_energy,
                energy_margin_jkg=terminal_energy - required,
                min_clearance_m=altitude - float(surface_height_at(
                    float(state.pos[0]), float(state.pos[2]))),
                terminal_altitude_error_m=altitude - mission.target_y_m,
                rollout_samples=0,
                corridor=corridor.name,
                cost=corridor.profile_penalty,
            )
            path = (() if debug_path is None else tuple(debug_path))
            return _RolloutResult(prediction, mission.target_y_m, 0.0,
                                  env.low_mach, path)

        lookahead_limit = self._control_lookahead(total)
        control_lookahead = min(lookahead_limit, max(total, 1.0))
        altitude_preview = min(env.altitude_preview_m, max(total, 1.0))
        look_x, look_z, _ = route.sample(altitude_preview)
        # Terrain following is predictive: command clearance over the higher
        # of the local surface and the surface down the control lookahead.
        # Waiting until a coastal slope is directly underneath the vehicle is
        # too late for a lagged, lift-limited autopilot.
        s0 = max(grid.steps[0].surface_m,
                 float(surface_height_at(look_x, look_z)))
        immediate_alt = self._desired_altitude(
            corridor, initial_alt, initial_alt, s0,
            max(0.0, total - altitude_preview), total, mission)
        terminal_now = (self._terminal_latched
                        or (mission.terminal_armed
                            and total <= mission.terminal_commit_max_m))
        # Once terminal is committed the reference is the actual LOS flight
        # path to the aim point.  Using the ordinary 10 km corridor lookahead
        # here makes a missile 30 km out aim for sea level in 10 km and splash
        # short; terminal geometry must use the full range-to-go.
        # Grid spacing is a rollout/performance detail, not a control
        # lookahead.  Coupling the two made short missions command the full
        # dive limit toward a deck reference only ~750 m ahead, leaving no
        # room to flare.  The live controller looks up to 10 km down-route,
        # matching the predictor below.
        immediate_lookahead = total if terminal_now else control_lookahead
        immediate_gamma = self._gamma_reference(
            initial_alt, immediate_alt, max(immediate_lookahead, 1.0), env)

        for route_step in grid.steps:
            ds = route_step.distance_m
            surface = route_step.surface_m
            next_surface = route_step.next_surface_m
            remaining = route_step.remaining_m
            desired_alt = self._desired_altitude(
                corridor, initial_alt, altitude, surface, remaining, total,
                mission)
            terminal_segment = (self._terminal_latched
                                or (mission.terminal_armed and remaining <=
                                    mission.terminal_commit_max_m))
            lookahead = (remaining if terminal_segment else
                         min(lookahead_limit, max(ds, remaining)))
            gamma_ref = self._gamma_reference(
                altitude, desired_alt, lookahead, env)

            mass = max(1.0, nonfuel_mass + fuel)
            q = q_scalar(speed, altitude)
            a_cap = min(env.max_g * GRAVITY,
                        q * env.ref_area_m2 * env.cl_max / mass)
            curvature = route_step.curvature_radpm
            a_turn = _clip(speed * speed * curvature, -a_cap, a_cap)
            support = GRAVITY * math.cos(gamma)
            vertical_cap = math.sqrt(max(a_cap * a_cap - a_turn * a_turn, 0.0))
            wanted_gamma_rate = (gamma_ref - gamma) / PATH_RESPONSE_TAU_S
            wanted_lift_vertical = support + speed * wanted_gamma_rate
            lift_vertical = _clip(wanted_lift_vertical,
                                  -vertical_cap, vertical_cap)
            gamma_rate = (lift_vertical - support) / max(speed, 1.0)

            ground_speed = max(speed * math.cos(gamma), 20.0)
            step_dt = ds / ground_speed
            gamma = _clip(gamma + gamma_rate * step_dt,
                          -env.max_descent_gamma_rad,
                          env.max_climb_gamma_rad)

            mach = mach_scalar(speed, altitude)
            parasite = drag_force_scalar(
                speed, altitude, cd_from_mach_scalar(mach), env.ref_area_m2)
            total_lift_accel = math.hypot(lift_vertical, a_turn)
            induced = induced_drag_scalar(
                mass * total_lift_accel, q, env.ref_area_m2, env.k_induced)
            drag = parasite + induced

            on_low_deck = desired_alt <= (
                surface + max(4.0 * env.deck_agl_m, 100.0))
            low_energy_leg = (gamma_ref < -_GAMMA_EPS
                              or remaining <= mission.terminal_commit_max_m
                              or on_low_deck)
            target_mach = (env.low_mach if low_energy_leg
                           else env.preferred_mach)
            target_speed = target_mach * speed_of_sound_scalar(altitude)
            desired_axial = (target_speed - speed) / 5.0
            thrust_cmd = _clip(drag + mass * desired_axial,
                               0.0, env.max_thrust_n)
            if env.thrust_tau_s > 0.0:
                thrust_actual += ((thrust_cmd - thrust_actual)
                                  * lag_gain(step_dt, env.thrust_tau_s))
            else:
                thrust_actual = thrust_cmd
            if fuel <= 0.0:
                thrust = 0.0
                thrust_actual = 0.0
            else:
                thrust = thrust_actual
                burn = thrust / (env.isp_s * GRAVITY) * step_dt
                if burn > fuel:
                    scale = fuel / max(burn, _EPS)
                    thrust *= scale
                    burn = fuel
                fuel -= burn

            axial = ((thrust - drag) / mass
                     - GRAVITY * math.sin(gamma))
            speed = max(1.0, speed + axial * step_dt)
            altitude += math.tan(gamma) * ds
            time_s += step_dt
            samples += 1
            min_clearance = min(min_clearance,
                                altitude - next_surface)
            if (debug_path is not None
                    and (samples % DEBUG_PATH_STRIDE == 0
                         or samples == len(grid.steps))):
                travelled = total - remaining + ds
                x, z, _ = route.sample(travelled)
                debug_path.append((x, altitude, z))

        if min_clearance == float("inf"):
            min_clearance = altitude - float(surface_height_at(
                float(state.pos[0]), float(state.pos[2])))
        terminal_energy = 0.5 * speed * speed + GRAVITY * altitude
        required_energy = (0.5 * env.terminal_speed_min_mps ** 2
                           + GRAVITY * mission.target_y_m)
        margin = terminal_energy - required_energy
        altitude_error = altitude - mission.target_y_m
        altitude_tolerance = max(100.0, env.deck_agl_m * 2.0)
        feasible = (samples <= MAX_ROLLOUT_STEPS
                    and min_clearance >= -1e-6
                    and speed >= env.terminal_speed_min_mps
                    and fuel + 1e-9 >= env.fuel_reserve_kg
                    and abs(altitude_error) <= altitude_tolerance)

        fuel_used = max(0.0, float(state.fuel_kg) - fuel)
        command_change = abs(immediate_gamma - self._last_gamma_cmd)
        # Receding-horizon candidates often cross by fractions of one cost
        # unit as their coarse grid advances.  Treat changing the broad
        # vertical objective like a real guidance-mode transition: a new
        # corridor must save enough fuel/time to pay this hysteresis cost.
        # This suppresses rapid MID/PREFERRED/DECK chatter without freezing a
        # path; a materially better live solution still wins immediately.
        switch_cost = (
            env.corridor_switch_penalty
            if (self._last_corridor is not None
                and corridor.name != self._last_corridor)
            else 0.0)
        cost = (fuel_used
                + 0.002 * time_s
                + corridor.profile_penalty
                + 2.0 * command_change
                + switch_cost)
        prediction = EnergyPrediction(
            feasible=feasible,
            route_range_m=total,
            time_to_go_s=time_s,
            terminal_speed_mps=speed,
            terminal_fuel_kg=fuel,
            terminal_specific_energy_jkg=terminal_energy,
            energy_margin_jkg=margin,
            min_clearance_m=min_clearance,
            terminal_altitude_error_m=altitude_error,
            rollout_samples=samples,
            corridor=corridor.name,
            cost=cost,
        )
        immediate_on_low_deck = immediate_alt <= (
            s0 + max(4.0 * env.deck_agl_m, 100.0))
        target_mach = (env.low_mach
                       if (immediate_gamma < -_GAMMA_EPS
                           or immediate_on_low_deck)
                       else env.preferred_mach)
        path = (() if debug_path is None else tuple(debug_path))
        return _RolloutResult(prediction, immediate_alt, immediate_gamma,
                              target_mach, path)

    def _desired_altitude(self, corridor: _Corridor, initial_alt: float,
                          altitude: float, surface: float, remaining: float,
                          total: float, mission: MissionSnapshot) -> float:
        env = self.envelope
        deck = surface + env.deck_agl_m
        if mission.preferred_altitude_m is not None:
            preferred = mission.preferred_altitude_m
        else:
            preferred = (surface + env.preferred_alt_m
                         if env.preferred_alt_is_agl else env.preferred_alt_m)
        if corridor.kind == "deck":
            base = deck
        elif corridor.kind == "preferred":
            base = max(deck, preferred)
        elif corridor.kind == "hold":
            base = max(deck, initial_alt)
        elif corridor.kind == "mid":
            base = max(deck, 0.5 * (initial_alt + preferred))
        elif corridor.kind == "energy":
            base = max(
                deck,
                initial_alt + corridor.preferred_fraction
                * (preferred - initial_alt))
        else:  # direct: linear energy-saving path toward the terminal aim.
            progress = 1.0 - remaining / max(total, _EPS)
            base = initial_alt + (mission.target_y_m - initial_alt) * progress
            base = max(deck, base)
        if not mission.allow_high:
            # A low-observable/terrain-follow mission treats its declared
            # cruise altitude as a ceiling, not merely a soft preference.
            base = min(base, max(deck, preferred))

        # Backwards terminal reach envelope.  It is recomputed from the live
        # altitude/range every replan, so descent is an online feasibility
        # decision rather than a fixed preprogrammed range gate.
        # Use a conservative fraction of the instantaneous physical dive
        # limit and reserve a capture buffer near the target.  Waiting until
        # the mathematical max-angle line is crossed ignores autopilot/path
        # response and predictably arrives high.
        handover_alt = (mission.target_y_m
                        if mission.terminal_handover_alt_m is None else
                        mission.terminal_handover_alt_m)
        # A deck-level handover must reserve substantially more flare/capture
        # distance than a diving terminal handover.  Diving rounds can safely
        # retain altitude and use roughly two thirds of their certified dive
        # envelope; sea skimmers use roughly forty percent plus a longer
        # forward control preview so inner-
        # loop lag cannot carry them through the surface before level-off.
        deck_handover = handover_alt <= (mission.target_y_m
                                         + max(4.0 * env.deck_agl_m, 100.0))
        capture_fraction = (env.terminal_capture_fraction
                            if env.terminal_capture_fraction is not None else
                            0.45 if deck_handover else 0.65)
        capture_gamma = max(math.radians(3.0),
                            capture_fraction * env.max_descent_gamma_rad)
        handover_range = (
            mission.terminal_commit_max_m
            if mission.terminal_handover_range_m is None else
            mission.terminal_handover_range_m)
        usable_range = max(
            0.0, remaining - handover_range)
        terminal_ceiling = (handover_alt
                            + math.tan(capture_gamma) * usable_range)
        base = min(base, terminal_ceiling)
        if (self._terminal_latched
                or (mission.terminal_armed
                    and remaining <= mission.terminal_commit_max_m)):
            base = handover_alt if deck_handover else mission.target_y_m
        # Do not intentionally command through terrain before terminal commit.
        if remaining > handover_range:
            base = max(base, deck)
        return base

    @staticmethod
    def _gamma_reference(altitude: float, desired_altitude: float,
                         lookahead_m: float,
                         env: AirframeEnvelope) -> float:
        gamma = math.atan2(desired_altitude - altitude,
                           max(lookahead_m, 1.0))
        return _clip(gamma, -env.max_descent_gamma_rad,
                     env.max_climb_gamma_rad)

    @staticmethod
    def _terminal_line_clear(
            state: FlightState, mission: MissionSnapshot,
            surface_height_at: Callable[[float, float], float]) -> bool:
        tx, tz = float(mission.path_xz[-1][0]), float(mission.path_xz[-1][1])
        x0, y0, z0 = (float(state.pos[0]), float(state.pos[1]),
                      float(state.pos[2]))
        for i in range(1, LINE_CLEAR_SAMPLES):
            f = i / LINE_CLEAR_SAMPLES
            x = x0 + (tx - x0) * f
            z = z0 + (tz - z0) * f
            y = y0 + (mission.target_y_m - y0) * f
            if y <= float(surface_height_at(x, z)):
                return False
        return True
