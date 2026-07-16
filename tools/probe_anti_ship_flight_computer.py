"""Full-production 120 Hz anti-ship missile trajectory harness."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
import json
import math
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sim.arsenal import WEAPONS  # noqa: E402
from sim.damage import apply_missile_hits  # noqa: E402
from sim.missile import Missile, PH_TERMINAL  # noqa: E402
from sim.ships import Ship  # noqa: E402


DT = 1.0 / 120.0
MOTIONS = ("static", "cross", "away", "toward", "diagonal")


class _World:
    radar_model = "functional"

    def __init__(self, ship):
        self.ships = [ship]
        self.missiles = []

    @staticmethod
    def surface_height_at(_x, _z):
        return 0.0

    @staticmethod
    def terrain_height_at(_x, _z):
        return -60.0


def _target_ship(range_m: float, motion: str) -> Ship:
    span = 2_000_000.0
    if motion in ("away", "toward"):
        lane = ((0.0, range_m - span), (0.0, range_m + span))
        direction = 1 if motion == "away" else -1
    elif motion == "cross":
        lane = ((-span, range_m), (span, range_m))
        direction = 1
    elif motion == "diagonal":
        lane = ((-span, range_m - span), (span, range_m + span))
        direction = 1
    elif motion == "static":
        lane = ((0.0, range_m - 1.0), (0.0, range_m + 1.0))
        direction = 1
    else:
        raise ValueError(f"unsupported motion {motion!r}")
    ship = Ship("target", "destroyer", lane, 0.5, direction=direction)
    if motion == "static":
        ship.speed = 0.0
    return ship


@dataclass(frozen=True, slots=True)
class AntiShipResult:
    weapon: str
    profile: str
    range_km: float
    motion: str
    hit: bool
    flight_time_s: float
    closest_m: float
    apogee_km: float
    impact_speed_mps: float
    terminal_speed_mps: float | None
    terminal_altitude_m: float | None
    terminal_fuel_kg: float | None
    fuel_left_kg: float
    path_length_km: float
    path_ratio: float
    corridor_switches: int


def run_case(weapon_id: str, profile: str, range_km: float, motion: str,
             *, planner_overrides: dict | None = None,
             weapon_overrides: dict | None = None,
             trace: bool = False,
             planner_detail: bool = False) -> tuple[AntiShipResult, list[dict]]:
    if weapon_id not in WEAPONS:
        raise ValueError(f"unknown anti-ship weapon {weapon_id!r}")
    if profile not in ("hi-lo", "lo-lo"):
        raise ValueError("profile must be hi-lo or lo-lo")
    weapon = WEAPONS[weapon_id]
    if weapon_overrides:
        weapon = replace(weapon, **weapon_overrides)
    ship = _target_ship(range_km * 1_000.0, motion)
    target_point = ship.pos.copy()
    missile = Missile(
        weapon, np.array([0.0, 5.0, 0.0], dtype=np.float64), 0.0,
        profile, target_point, target_ship=ship)
    if planner_overrides:
        missile._fc.envelope = replace(
            missile._fc.envelope, **planner_overrides)
    missile._fc.set_debug_enabled(planner_detail)
    world = _World(ship)
    world.missiles = [missile]
    trajectory = []
    next_trace = 0.0
    previous = missile.pos.copy()
    path_length = 0.0
    closest = float("inf")
    apogee = float(missile.pos[1])
    terminal_speed = terminal_altitude = terminal_fuel = None
    previous_corridor = None
    corridor_switches = 0
    hit = False
    max_time = 1_400.0 if weapon_id == "swarm" else 900.0

    while missile.alive and missile.t < max_time:
        ship.update(DT)
        missile.update(DT, world)
        apply_missile_hits([missile], [ship], [], damage_model="legacy")
        hit = getattr(missile, "killed_by", None) is ship
        path_length += float(np.linalg.norm(missile.pos - previous))
        np.copyto(previous, missile.pos)
        distance = float(np.linalg.norm(missile.pos - ship.pos))
        closest = min(closest, distance)
        apogee = max(apogee, float(missile.pos[1]))
        speed = float(np.linalg.norm(missile.vel))
        command = missile._fc_command
        corridor = command.prediction.corridor if command is not None else None
        if (previous_corridor is not None and corridor is not None
                and corridor != previous_corridor):
            corridor_switches += 1
        if corridor is not None:
            previous_corridor = corridor
        if (terminal_speed is None
                and (missile.phase == PH_TERMINAL
                     or missile._terminal_homing)):
            terminal_speed = speed
            terminal_altitude = float(missile.pos[1])
            terminal_fuel = float(missile.fuel)
        if trace and missile.t + 1e-12 >= next_trace:
            sample = {
                "t_s": round(float(missile.t), 3),
                "x_m": round(float(missile.pos[0]), 3),
                "altitude_m": round(float(missile.pos[1]), 3),
                "z_m": round(float(missile.pos[2]), 3),
                "speed_mps": round(speed, 3),
                "fuel_kg": round(float(missile.fuel), 3),
                "target_range_m": round(distance, 3),
                "phase": int(missile.phase),
                "corridor": corridor,
                "gamma_command_deg": (None if command is None else round(
                    math.degrees(command.target_path_gamma_rad), 3)),
            }
            snapshot = missile._fc.debug_snapshot
            if planner_detail and snapshot is not None:
                sample["candidates"] = [
                    {
                        "name": candidate.name,
                        "feasible": candidate.feasible,
                        "cost": round(float(candidate.cost), 3),
                        "terminal_speed_mps": round(
                            float(candidate.terminal_speed_mps), 3),
                        "terminal_fuel_kg": round(
                            float(candidate.terminal_fuel_kg), 3),
                        "energy_margin_jkg": round(
                            float(candidate.energy_margin_jkg), 3),
                        "clearance_m": round(
                            float(candidate.min_clearance_m), 3),
                        "altitude_error_m": round(
                            float(candidate.terminal_altitude_error_m), 3),
                    }
                    for candidate in snapshot.candidates]
            trajectory.append(sample)
            next_trace += 0.5

    impact_speed = float(np.linalg.norm(missile.vel))
    direct = max(math.hypot(range_km, float(ship.pos[1]) / 1_000.0), 1e-9)
    result = AntiShipResult(
        weapon=weapon_id, profile=profile, range_km=float(range_km),
        motion=motion, hit=bool(hit), flight_time_s=float(missile.t),
        closest_m=float(closest), apogee_km=apogee / 1_000.0,
        impact_speed_mps=impact_speed,
        terminal_speed_mps=terminal_speed,
        terminal_altitude_m=terminal_altitude,
        terminal_fuel_kg=terminal_fuel,
        fuel_left_kg=float(missile.fuel), path_length_km=path_length / 1_000.0,
        path_ratio=(path_length / 1_000.0) / direct,
        corridor_switches=corridor_switches)
    return result, trajectory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weapon", choices=tuple(WEAPONS), default="oniks")
    parser.add_argument("--profile", choices=("hi-lo", "lo-lo"),
                        default="hi-lo")
    parser.add_argument("--range-km", type=float, default=200.0)
    parser.add_argument("--motion", choices=MOTIONS, default="cross")
    parser.add_argument("--trace-output")
    parser.add_argument("--planner-detail", action="store_true")
    args = parser.parse_args()
    result, trajectory = run_case(
        args.weapon, args.profile, args.range_km, args.motion,
        trace=bool(args.trace_output), planner_detail=args.planner_detail)
    print(json.dumps(asdict(result), indent=2))
    if args.trace_output:
        with open(args.trace_output, "w", encoding="utf-8") as handle:
            json.dump(trajectory, handle, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
