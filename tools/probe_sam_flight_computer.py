"""Full-physics SAM flight-computer launch matrix and trajectory recorder.

Unlike ``sweep_flight_computer.py`` (fast bounded-rollout validation), this
probe steps the production :class:`sim.sam.SamMissile` at 120 Hz.  It is meant
for detecting ugly emergent paths: low-altitude snakes, corridor thrashing,
late handovers, energy-starved terminal turns, and range/altitude cliffs.

Examples
--------
Quick 40N6 matrix as a table::

    python tools/probe_sam_flight_computer.py --mode quick

One exact case plus a planner-cadence trajectory trace::

    python tools/probe_sam_flight_computer.py --ranges-km 340 \
        --altitudes-km 6.5 --motions cross \
        --trace-output tools/40n6_340km_cross.json

Machine-readable full matrix::

    python tools/probe_sam_flight_computer.py --mode full --format json
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import sys
from dataclasses import asdict, dataclass, replace

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sim.arsenal import SAMS  # noqa: E402
from sim.aero import q_scalar  # noqa: E402
from sim.physics import mach_scalar  # noqa: E402
from sim.sam import SPH_TERMINAL, SamMissile  # noqa: E402


DT = 1.0 / 120.0
TRACE_INTERVAL_S = 0.5       # SAM planner cadence: captures every replan
MOTION_VELOCITIES = {
    "static": (0.0, 0.0, 0.0),
    "cross": (230.0, 0.0, 0.0),
    "away": (0.0, 0.0, 230.0),
    "toward": (0.0, 0.0, -230.0),
    "climb": (180.0, 35.0, 0.0),
}

QUICK_RANGES_KM = (120.0, 250.0, 340.0)
QUICK_ALTITUDES_KM = (6.5, 12.0, 24.0)
QUICK_MOTIONS = ("static", "cross", "away")

FULL_RANGES_KM = (60.0, 120.0, 200.0, 250.0, 300.0, 320.0, 340.0, 360.0)
FULL_ALTITUDES_KM = (4.0, 6.5, 9.0, 12.0, 18.0, 24.0, 30.0)
FULL_MOTIONS = ("static", "cross", "away", "toward", "climb")


class _FlatWorld:
    ships = []

    @staticmethod
    def terrain_height_at(_x, _z):
        return -50.0


class _Target:
    def __init__(self, range_m: float, altitude_m: float,
                 velocity_mps: tuple[float, float, float]):
        self.pos = np.array([0.0, altitude_m, range_m], dtype=np.float64)
        self.vel = np.array(velocity_mps, dtype=np.float64)
        self.alive = True

    def velocity(self):
        return self.vel

    def update(self, dt: float):
        self.pos += self.vel * dt

    def kill(self):
        self.alive = False


@dataclass(frozen=True, slots=True)
class ProbeResult:
    weapon: str
    range_km: float
    altitude_km: float
    motion: str
    track_update_s: float
    hit: bool
    self_destructed: bool
    flight_time_s: float
    closest_m: float
    apogee_km: float
    altitude_t48_km: float | None
    range_t48_km: float | None
    speed_t48_mps: float | None
    handover_altitude_km: float | None
    handover_speed_mps: float | None
    impact_speed_mps: float
    corridor_switches: int
    path_length_km: float


def _parse_numbers(value: str) -> tuple[float, ...]:
    values = tuple(float(item.strip()) for item in value.split(",")
                   if item.strip())
    if not values or any(not math.isfinite(item) or item <= 0.0
                         for item in values):
        raise argparse.ArgumentTypeError(
            "expected comma-separated finite positive numbers")
    return values


def _parse_motions(value: str) -> tuple[str, ...]:
    values = tuple(item.strip().lower() for item in value.split(",")
                   if item.strip())
    invalid = [item for item in values if item not in MOTION_VELOCITIES]
    if not values or invalid:
        raise argparse.ArgumentTypeError(
            f"motions must be from {','.join(MOTION_VELOCITIES)}")
    return values


def run_case(weapon_id: str, range_km: float, altitude_km: float,
             motion: str, *, track_update_s: float = 1.0,
             trace: bool = False,
             planner_detail: bool = False,
             planner_overrides: dict | None = None,
             weapon_overrides: dict | None = None
             ) -> tuple[ProbeResult, list[dict]]:
    """Fly one deterministic production missile case over flat terrain."""

    weapon = SAMS[weapon_id]
    if weapon_overrides:
        weapon = replace(weapon, **weapon_overrides)
    target = _Target(range_km * 1_000.0, altitude_km * 1_000.0,
                     MOTION_VELOCITIES[motion])
    track_pos = target.pos.copy()
    track_vel = target.vel.copy()
    track_age = [0.0]

    def estimate():
        # Production contact boards dead-reckon the last radar fix with its
        # measured velocity.  Returning the frozen fix here manufactured a
        # 115 m half-cadence bias against a 230 m/s crosser and made agile
        # point-defence rounds look inaccurate when their real input is not.
        return (track_pos + track_vel * track_age[0]), track_vel.copy()

    missile = SamMissile(
        weapon, np.array([0.0, 5.0, 0.0], dtype=np.float64), target,
        contact_estimate_fn=estimate)
    if planner_overrides:
        missile._fc.envelope = replace(
            missile._fc.envelope, **planner_overrides)
    if planner_detail:
        missile._fc.set_debug_enabled(True)
    world = _FlatWorld()
    next_track_t = 0.0
    next_trace_t = 0.0
    trajectory: list[dict] = []
    apogee = 0.0
    closest = float("inf")
    altitude_t48 = range_t48 = speed_t48 = None
    handover_altitude = handover_speed = None
    path_length = 0.0
    previous_pos = missile.pos.copy()
    previous_corridor = None
    corridor_switches = 0

    while missile.alive and missile.t < weapon.self_destruct_t + 0.1:
        target.update(DT)
        track_age[0] += DT
        if track_update_s <= 0.0 or missile.t + 1e-12 >= next_track_t:
            np.copyto(track_pos, target.pos)
            np.copyto(track_vel, target.vel)
            track_age[0] = 0.0
            next_track_t = missile.t + max(track_update_s, DT)

        missile.update(DT, world)
        speed = float(np.linalg.norm(missile.vel))
        distance = float(np.linalg.norm(missile.pos - target.pos))
        path_length += float(np.linalg.norm(missile.pos - previous_pos))
        np.copyto(previous_pos, missile.pos)
        apogee = max(apogee, float(missile.pos[1]))
        closest = min(closest, distance)

        command = missile._fc_command
        corridor = (command.prediction.corridor
                    if command is not None else None)
        if (previous_corridor is not None and corridor is not None
                and corridor != previous_corridor):
            corridor_switches += 1
        if corridor is not None:
            previous_corridor = corridor

        if altitude_t48 is None and missile.t >= 48.0:
            altitude_t48 = float(missile.pos[1]) / 1_000.0
            range_t48 = distance / 1_000.0
            speed_t48 = speed
        if handover_altitude is None and missile.phase >= SPH_TERMINAL:
            handover_altitude = float(missile.pos[1]) / 1_000.0
            handover_speed = speed

        if trace and missile.t + 1e-12 >= next_trace_t:
            prediction = command.prediction if command is not None else None
            debug = missile._fc.debug_snapshot
            trajectory.append({
                "t_s": round(missile.t, 3),
                "x_m": round(float(missile.pos[0]), 3),
                "altitude_m": round(float(missile.pos[1]), 3),
                "z_m": round(float(missile.pos[2]), 3),
                "speed_mps": round(speed, 3),
                "target_range_m": round(distance, 3),
                "phase": int(missile.phase),
                "corridor": corridor,
                "mach": round(mach_scalar(speed, float(missile.pos[1])), 4),
                "dynamic_pressure_pa": round(
                    q_scalar(speed, float(missile.pos[1])), 3),
                "propellant_kg": round(float(missile.propellant), 4),
                "mass_kg": round(float(missile.mass), 4),
                "gamma_command_deg": (None if command is None else round(
                    math.degrees(command.target_path_gamma_rad), 4)),
                "path_accel_g": (None if command is None else round(
                    command.path_normal_accel_mps2 / 9.81, 5)),
                "altitude_reference_m": (None if command is None else round(
                    command.altitude_ref_asl_m, 3)),
                "plan_id": None if command is None else command.plan_id,
                "predicted_feasible": (None if prediction is None else
                                       prediction.feasible),
                "predicted_terminal_speed_mps": (
                    None if prediction is None else round(
                        prediction.terminal_speed_mps, 3)),
                "energy_margin_jkg": (None if prediction is None else round(
                    prediction.energy_margin_jkg, 3)),
                "terminal_altitude_error_m": (
                    None if prediction is None else round(
                        prediction.terminal_altitude_error_m, 3)),
                "planner_candidates": ([] if debug is None else [
                    {
                        "name": candidate.name,
                        "selected": candidate.selected,
                        "feasible": candidate.feasible,
                        "cost": round(candidate.cost, 5),
                        "terminal_speed_mps": round(
                            candidate.terminal_speed_mps, 3),
                        "energy_margin_jkg": round(
                            candidate.energy_margin_jkg, 3),
                        "min_clearance_m": round(
                            candidate.min_clearance_m, 3),
                        "terminal_altitude_error_m": round(
                            candidate.terminal_altitude_error_m, 3),
                        "path_world": candidate.path_world,
                    }
                    for candidate in debug.candidates]),
            })
            next_trace_t += TRACE_INTERVAL_S

    result = ProbeResult(
        weapon=weapon_id,
        range_km=range_km,
        altitude_km=altitude_km,
        motion=motion,
        track_update_s=track_update_s,
        hit=bool(missile.killed_target),
        self_destructed=bool(missile.self_destructed),
        flight_time_s=missile.t,
        closest_m=closest,
        apogee_km=apogee / 1_000.0,
        altitude_t48_km=altitude_t48,
        range_t48_km=range_t48,
        speed_t48_mps=speed_t48,
        handover_altitude_km=handover_altitude,
        handover_speed_mps=handover_speed,
        impact_speed_mps=float(np.linalg.norm(missile.vel)),
        corridor_switches=corridor_switches,
        path_length_km=path_length / 1_000.0,
    )
    return result, trajectory


def _table(results: list[ProbeResult]) -> str:
    header = (
        "weapon  rng  alt motion   hit  t48-alt apogee hand-alt hand-v "
        "closest switches time")
    rows = [header, "-" * len(header)]
    for item in results:
        t48 = "--" if item.altitude_t48_km is None else \
            f"{item.altitude_t48_km:7.1f}"
        hand_alt = "--" if item.handover_altitude_km is None else \
            f"{item.handover_altitude_km:7.1f}"
        hand_speed = "--" if item.handover_speed_mps is None else \
            f"{item.handover_speed_mps:6.0f}"
        rows.append(
            f"{item.weapon:6} {item.range_km:4.0f} {item.altitude_km:4.1f} "
            f"{item.motion:7} {'YES' if item.hit else ' no':>3} {t48:>7} "
            f"{item.apogee_km:6.1f} {hand_alt:>7} {hand_speed:>6} "
            f"{item.closest_m:7.0f} {item.corridor_switches:8d} "
            f"{item.flight_time_s:5.0f}")
    return "\n".join(rows)


def _csv(results: list[ProbeResult]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(asdict(results[0])))
    writer.writeheader()
    writer.writerows(asdict(item) for item in results)
    return output.getvalue().rstrip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weapon", choices=tuple(SAMS), default="40n6")
    parser.add_argument("--mode", choices=("quick", "full"), default="quick")
    parser.add_argument("--format", choices=("table", "json", "csv"),
                        default="table")
    parser.add_argument("--ranges-km", type=_parse_numbers)
    parser.add_argument("--altitudes-km", type=_parse_numbers)
    parser.add_argument("--motions", type=_parse_motions)
    parser.add_argument("--track-update-s", type=float, default=1.0)
    parser.add_argument("--trace-output",
                        help="write one-second trajectories to this JSON file")
    args = parser.parse_args()

    if not math.isfinite(args.track_update_s) or args.track_update_s < 0.0:
        parser.error("--track-update-s must be finite and >= 0")
    if args.mode == "quick":
        default_ranges = QUICK_RANGES_KM
        default_altitudes = QUICK_ALTITUDES_KM
        default_motions = QUICK_MOTIONS
    else:
        default_ranges = FULL_RANGES_KM
        default_altitudes = FULL_ALTITUDES_KM
        default_motions = FULL_MOTIONS
    ranges = args.ranges_km or default_ranges
    altitudes = args.altitudes_km or default_altitudes
    motions = args.motions or default_motions

    results = []
    traces = {}
    for range_km in ranges:
        for altitude_km in altitudes:
            for motion in motions:
                result, trajectory = run_case(
                    args.weapon, range_km, altitude_km, motion,
                    track_update_s=args.track_update_s,
                    trace=bool(args.trace_output),
                    planner_detail=bool(args.trace_output))
                results.append(result)
                if args.trace_output:
                    key = f"{args.weapon}_{range_km:g}km_{altitude_km:g}km_{motion}"
                    traces[key] = trajectory

    if args.format == "json":
        print(json.dumps([asdict(item) for item in results], indent=2))
    elif args.format == "csv":
        print(_csv(results))
    else:
        print(_table(results))

    if args.trace_output:
        path = os.path.abspath(args.trace_output)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(traces, handle, indent=2)
        print(f"[trace] wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
