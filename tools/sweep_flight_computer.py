"""Deterministic brute-force sweep for :mod:`sim.flight_computer`.

The tool evaluates the *online planner only*; it does not integrate a live
missile or modify production state.  Each case varies launch altitude, route
range/shape, initial Mach, target altitude, and whether a high/loft corridor is
permitted.  Results expose the selected candidate corridor, predicted terminal
energy/fuel, and explicit failure reasons.

Examples::

    python -m tools.sweep_flight_computer --mode quick
    python -m tools.sweep_flight_computer --mode full --weapon zircon \
        --profile hi-lo --format csv --output renders/fc_zircon.csv
    python -m tools.sweep_flight_computer --mode quick --weapon tomahawk \
        --format json --output renders/fc_tlam.json

``quick`` is a 64-case CI/development matrix for the missile family and never
exceeds ``MAX_QUICK_CASES``.  ``full`` expands every requested axis but is hard
bounded by ``MAX_FULL_CASES``.  Candidate ordering, case ids, output rows, and
JSON keys are deterministic; there is no RNG or wall-clock input.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from dataclasses import asdict, dataclass
import io
import itertools
import json
import math
from pathlib import Path
import sys
from typing import Iterable, Sequence

# Allow both ``python -m tools.sweep_flight_computer`` and the more natural
# direct invocation shown by most repository tools.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sim.arsenal import (HARM, JASSM, KALIBR_PL, KH31P, ONIKS, SWARM,  # noqa: E402
                         TOMAHAWK, ZIRCON)
from sim.flight_computer import (AirframeEnvelope, FlightState,  # noqa: E402
                                 MissionSnapshot, OnlineFlightComputer,
                                 route_arc_length_m)
from sim.physics import speed_of_sound_scalar  # noqa: E402


MAX_QUICK_CASES = 64
MAX_FULL_CASES = 4_096

ROUTE_STRAIGHT = "straight"
ROUTE_DOGLEG_45 = "dogleg45"
ROUTE_DOGLEG_90 = "dogleg90"


_WEAPONS = {
    "oniks": (ONIKS, "missile", 340_000.0),
    "zircon": (ZIRCON, "missile", 250_000.0),
    "swarm": (SWARM, "missile", 50_000.0),
    "tomahawk": (TOMAHAWK, "strike", 2_000_000.0),
    "kalibr": (KALIBR_PL, "strike", 500_000.0),
    "jassm": (JASSM, "strike", 370_000.0),
    "harm": (HARM, "arm", 110_000.0),
    "kh31p": (KH31P, "arm", 140_000.0),
}


CSV_FIELDS = (
    "case_id", "weapon", "profile", "sweep_mode",
    "launch_alt_m", "range_m", "initial_mach", "target_alt_m",
    "route_kind", "allow_high", "route_arc_m",
    "selected_candidate", "command_mode", "command_gamma_deg",
    "normal_accel_mps2", "command_target_mach", "terminal_commit",
    "feasible", "failures", "terminal_speed_mps", "terminal_mach",
    "terminal_fuel_kg", "terminal_specific_energy_jkg",
    "energy_margin_jkg", "min_clearance_m", "terminal_alt_error_m",
    "time_to_go_s", "rollout_samples",
)


@dataclass(frozen=True, slots=True)
class SweepCase:
    """One deterministic planner input from the Cartesian sweep."""

    case_id: str
    weapon: str
    profile: str
    sweep_mode: str
    launch_alt_m: float
    range_m: float
    initial_mach: float
    target_alt_m: float
    route_kind: str
    allow_high: bool


def _unique(values: Iterable[float]) -> tuple[float, ...]:
    """Stable finite-float de-duplication (first occurrence wins)."""

    result = []
    seen = set()
    for value in values:
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("sweep axes must be finite")
        key = round(value, 9)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return tuple(result)


def weapon_setup(weapon_name: str, profile: str = "hi-lo"):
    """Return ``(weapon, family, nominal_range, envelope, normalized_profile)``."""

    name = str(weapon_name).lower()
    if name not in _WEAPONS:
        raise ValueError(f"unknown weapon {weapon_name!r}")
    weapon, family, nominal_range = _WEAPONS[name]
    if family == "missile":
        if profile not in ("hi-lo", "lo-lo"):
            raise ValueError("missile profile must be 'hi-lo' or 'lo-lo'")
        normalized_profile = profile
    else:
        normalized_profile = "-"
    envelope = AirframeEnvelope.from_weapon(
        weapon, family, profile if family == "missile" else None)
    return weapon, family, nominal_range, envelope, normalized_profile


def sweep_axes(mode: str, envelope: AirframeEnvelope,
               nominal_range_m: float) -> dict[str, tuple]:
    """Build deterministic envelope-relative quick/full axes."""

    mode = str(mode).lower()
    deck = max(5.0, envelope.deck_agl_m)
    preferred = max(deck, envelope.preferred_alt_m)
    if mode == "quick":
        high_launch = preferred if preferred > deck + 1.0 else 8_000.0
        return {
            "launch_alt_m": _unique((deck, high_launch)),
            "range_m": _unique((0.25 * nominal_range_m,
                                0.75 * nominal_range_m)),
            "initial_mach": _unique((max(0.2, 0.65 * envelope.low_mach),
                                     envelope.preferred_mach)),
            "target_alt_m": (0.0, 500.0),
            "route_kind": (ROUTE_STRAIGHT, ROUTE_DOGLEG_45),
            "allow_high": (False, True),
        }
    if mode != "full":
        raise ValueError("mode must be 'quick' or 'full'")
    return {
        "launch_alt_m": _unique((
            deck, 1_000.0, 5_000.0, preferred,
            max(8_000.0, 1.25 * preferred),
        )),
        "range_m": _unique(tuple(f * nominal_range_m for f in
                                  (0.10, 0.25, 0.50, 0.75, 1.0, 1.10))),
        "initial_mach": _unique((
            max(0.15, 0.35 * envelope.low_mach),
            max(0.2, 0.65 * envelope.low_mach),
            envelope.low_mach,
            envelope.preferred_mach,
            1.15 * envelope.preferred_mach,
        )),
        "target_alt_m": (0.0, 100.0, 500.0, 2_000.0),
        "route_kind": (ROUTE_STRAIGHT, ROUTE_DOGLEG_45,
                       ROUTE_DOGLEG_90),
        "allow_high": (False, True),
    }


def generate_cases(mode: str = "quick", weapon_name: str = "oniks",
                   profile: str = "hi-lo") -> tuple[SweepCase, ...]:
    """Generate the bounded Cartesian matrix in stable axis order."""

    _weapon, _family, nominal, envelope, normalized_profile = weapon_setup(
        weapon_name, profile)
    axes = sweep_axes(mode, envelope, nominal)
    combinations = itertools.product(
        axes["launch_alt_m"], axes["range_m"], axes["initial_mach"],
        axes["target_alt_m"], axes["route_kind"], axes["allow_high"])
    prefix = "q" if mode == "quick" else "f"
    cases = tuple(
        SweepCase(
            case_id=f"{prefix}{index:05d}",
            weapon=weapon_name.lower(),
            profile=normalized_profile,
            sweep_mode=mode,
            launch_alt_m=float(alt),
            range_m=float(distance),
            initial_mach=float(mach),
            target_alt_m=float(target_alt),
            route_kind=str(route),
            allow_high=bool(allow_high),
        )
        for index, (alt, distance, mach, target_alt, route, allow_high)
        in enumerate(combinations)
    )
    bound = MAX_QUICK_CASES if mode == "quick" else MAX_FULL_CASES
    if len(cases) > bound:
        raise RuntimeError(
            f"{mode} matrix generated {len(cases)} cases (bound {bound})")
    return cases


def route_for_case(case: SweepCase) -> tuple[tuple[float, float], ...]:
    """Build a straight or dogleg route ending at ``(0, range)``."""

    distance = case.range_m
    target = (0.0, distance)
    if case.route_kind == ROUTE_STRAIGHT:
        return (target,)
    if case.route_kind == ROUTE_DOGLEG_45:
        return ((0.25 * distance, 0.50 * distance), target)
    if case.route_kind == ROUTE_DOGLEG_90:
        return ((0.50 * distance, 0.0), target)
    raise ValueError(f"unknown route kind {case.route_kind!r}")


def _flat_surface(_x: float, _z: float) -> float:
    return 0.0


def _terminal_commit_range(weapon, family: str) -> float:
    if family == "missile":
        configured = float(getattr(weapon, "final_pn_range_m", 0.0))
        return configured if configured > 0.0 else 800.0
    if family == "arm":
        return 8_000.0
    return 2_000.0


def failure_codes(row: dict, envelope: AirframeEnvelope) -> tuple[str, ...]:
    """Explain every hard feasibility failure in deterministic order."""

    failures = []
    if row["min_clearance_m"] < -1e-6:
        failures.append("TERRAIN")
    if row["terminal_speed_mps"] < envelope.terminal_speed_min_mps:
        failures.append("TERMINAL_SPEED")
    if row["energy_margin_jkg"] < 0.0:
        failures.append("ENERGY")
    if row["terminal_fuel_kg"] + 1e-9 < envelope.fuel_reserve_kg:
        failures.append("FUEL_RESERVE")
    altitude_tolerance = max(100.0, 2.0 * envelope.deck_agl_m)
    if abs(row["terminal_alt_error_m"]) > altitude_tolerance:
        failures.append("TERMINAL_ALTITUDE")
    if not row["feasible"] and not failures:
        failures.append("UNREACHABLE")
    return tuple(failures)


def evaluate_case(case: SweepCase) -> dict:
    """Evaluate one planner case and return a CSV/JSON-safe result row."""

    weapon, family, _nominal, envelope, _profile = weapon_setup(
        case.weapon, case.profile if case.profile != "-" else "hi-lo")
    route = route_for_case(case)
    speed = case.initial_mach * speed_of_sound_scalar(case.launch_alt_m)
    state = FlightState(
        pos=(0.0, case.launch_alt_m, 0.0),
        vel=(0.0, 0.0, speed),
        mass_kg=envelope.dry_mass_kg + envelope.fuel_capacity_kg,
        fuel_kg=envelope.fuel_capacity_kg,
        thrust_actual_n=0.0,
    )
    mission = MissionSnapshot(
        path_xz=route,
        target_y_m=case.target_alt_m,
        allow_high=case.allow_high,
        terminal_commit_max_m=_terminal_commit_range(weapon, family),
    )
    command = OnlineFlightComputer(envelope).update(
        0.0, state, mission, _flat_surface)
    pred = command.prediction
    terminal_mach = pred.terminal_speed_mps / speed_of_sound_scalar(
        case.target_alt_m)
    row = {
        **asdict(case),
        "route_arc_m": route_arc_length_m(state.pos, route),
        "selected_candidate": pred.corridor,
        "command_mode": command.mode.name,
        "command_gamma_deg": math.degrees(command.target_path_gamma_rad),
        "normal_accel_mps2": command.path_normal_accel_mps2,
        "command_target_mach": command.target_mach,
        "terminal_commit": command.terminal_commit,
        "feasible": pred.feasible,
        "failures": "",
        "terminal_speed_mps": pred.terminal_speed_mps,
        "terminal_mach": terminal_mach,
        "terminal_fuel_kg": pred.terminal_fuel_kg,
        "terminal_specific_energy_jkg": pred.terminal_specific_energy_jkg,
        "energy_margin_jkg": pred.energy_margin_jkg,
        "min_clearance_m": pred.min_clearance_m,
        "terminal_alt_error_m": pred.terminal_altitude_error_m,
        "time_to_go_s": pred.time_to_go_s,
        "rollout_samples": pred.rollout_samples,
    }
    row["failures"] = ";".join(failure_codes(row, envelope)) or "NONE"
    return row


def run_sweep(cases: Sequence[SweepCase], limit: int | None = None) -> list[dict]:
    """Evaluate cases in order, optionally stopping at a positive hard limit."""

    if limit is not None:
        if limit <= 0:
            raise ValueError("limit must be > 0")
        cases = cases[:limit]
    return [evaluate_case(case) for case in cases]


def summarize(rows: Sequence[dict]) -> dict:
    """Aggregate feasibility, candidate choice, modes, and failure reasons."""

    candidates = Counter(row["selected_candidate"] for row in rows)
    modes = Counter(row["command_mode"] for row in rows)
    failures = Counter()
    for row in rows:
        for code in row["failures"].split(";"):
            if code != "NONE":
                failures[code] += 1
    margins = [float(row["energy_margin_jkg"]) for row in rows]
    return {
        "cases": len(rows),
        "feasible": sum(bool(row["feasible"]) for row in rows),
        "infeasible": sum(not bool(row["feasible"]) for row in rows),
        "candidate_counts": dict(sorted(candidates.items())),
        "command_mode_counts": dict(sorted(modes.items())),
        "failure_counts": dict(sorted(failures.items())),
        "min_energy_margin_jkg": min(margins) if margins else None,
        "max_energy_margin_jkg": max(margins) if margins else None,
    }


def csv_text(rows: Sequence[dict]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows({field: row[field] for field in CSV_FIELDS} for row in rows)
    return stream.getvalue()


def json_text(rows: Sequence[dict], metadata: dict) -> str:
    payload = {
        "metadata": metadata,
        "summary": summarize(rows),
        "cases": list(rows),
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def table_text(rows: Sequence[dict], metadata: dict) -> str:
    lines = [
        (f"flight-computer sweep: mode={metadata['mode']} "
         f"weapon={metadata['weapon']} profile={metadata['profile']} "
         f"cases={len(rows)}/{metadata['generated_cases']}"),
        (f"{'case':>6} {'alt':>7} {'rng':>7} {'M0':>5} {'tgtY':>6} "
         f"{'route':>9} {'loft':>4} {'cand':>9} {'Et margin':>10} "
         f"{'Vt':>7} {'fuel':>7} {'result':>18}"),
    ]
    for row in rows:
        lines.append(
            f"{row['case_id']:>6} {row['launch_alt_m']:7.0f} "
            f"{row['range_m']/1000:6.0f}k {row['initial_mach']:5.2f} "
            f"{row['target_alt_m']:6.0f} {row['route_kind']:>9} "
            f"{str(row['allow_high'])[0]:>4} "
            f"{row['selected_candidate']:>9} "
            f"{row['energy_margin_jkg']/1000:9.1f}k "
            f"{row['terminal_speed_mps']:7.0f} "
            f"{row['terminal_fuel_kg']:7.1f} {row['failures']:>18}"
        )
    summary = summarize(rows)
    lines.append(
        f"summary: feasible={summary['feasible']} "
        f"infeasible={summary['infeasible']} "
        f"candidates={summary['candidate_counts']} "
        f"failures={summary['failure_counts']}"
    )
    return "\n".join(lines) + "\n"


def _write_or_print(text: str, output: str | None) -> None:
    if output is None:
        sys.stdout.write(text)
        return
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("quick", "full"), default="quick")
    parser.add_argument("--weapon", choices=tuple(_WEAPONS), default="oniks")
    parser.add_argument("--profile", choices=("hi-lo", "lo-lo"),
                        default="hi-lo")
    parser.add_argument("--format", choices=("table", "csv", "json"),
                        default="table")
    parser.add_argument("--output", help="output file (stdout when omitted)")
    parser.add_argument("--limit", type=int,
                        help="evaluate only the first N deterministic cases")
    parser.add_argument("--fail-on-infeasible", action="store_true",
                        help="exit 1 when any evaluated case is infeasible")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cases = generate_cases(args.mode, args.weapon, args.profile)
    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit must be > 0")
    rows = run_sweep(cases, args.limit)
    normalized_profile = cases[0].profile if cases else args.profile
    metadata = {
        "mode": args.mode,
        "weapon": args.weapon,
        "profile": normalized_profile,
        "generated_cases": len(cases),
        "evaluated_cases": len(rows),
        "case_bound": MAX_QUICK_CASES if args.mode == "quick"
        else MAX_FULL_CASES,
    }
    if args.format == "csv":
        text = csv_text(rows)
    elif args.format == "json":
        text = json_text(rows, metadata)
    else:
        text = table_text(rows, metadata)
    _write_or_print(text, args.output)
    if args.fail_on_infeasible and any(not row["feasible"] for row in rows):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
