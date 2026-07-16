"""Run the deterministic Cloud V2 visual and quantitative acceptance matrix.

The suite launches each probe in a fresh process so OpenGL resources, weather
environment overrides, and temporal histories cannot leak between presets.
Use ``--dry-run`` to print the exact reproducible command matrix.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from tools.cloud_probe_metrics import PRESET_NAMES


ROOT = Path(__file__).resolve().parents[1]


def visual_commands(seed: int, quality: str) -> list[list[str]]:
    commands = []
    for preset in range(len(PRESET_NAMES)):
        commands.append([
            sys.executable, "-m", "tools.probe_cloud_shots", str(seed),
            "--renderer", "v2", "--quality", quality,
            "--preset", str(preset), "--preset-views",
        ])
    # Representative vertical coverage: fair cumulus, thin high cirrus, storm.
    for preset in (1, 4, 6):
        commands.append([
            sys.executable, "-m", "tools.probe_cloud_shots", str(seed),
            "--renderer", "v2", "--quality", quality,
            "--preset", str(preset), "--altitude-sweep",
        ])
    return commands


def orbit_commands(seed: int, quality: str) -> list[list[str]]:
    """One fresh process and one 20-view contact sheet per weather preset."""
    return [[
        sys.executable, "-m", "tools.probe_cloud_shots", str(seed),
        "--renderer", "v2", "--quality", quality,
        "--preset", str(preset), "--orbit-matrix",
    ] for preset in range(len(PRESET_NAMES))]


def quantitative_commands(seed: int, quality: str,
                          require_lightning: bool = True) -> list[list[str]]:
    close_report = f"renders/cloud_accept_close_{quality}_seed{seed}.json"
    still_report = f"renders/cloud_accept_stationary_{quality}_seed{seed}.json"
    storm_report = f"renders/cloud_accept_storm_{quality}_seed{seed}.json"
    commands = [
        [sys.executable, "-m", "tools.probe_cloud_flight", str(seed),
         "--renderer", "v2", "--quality", quality, "--preset", "1",
         "--spec", "docs/examples/flight_close_approach_v2.json",
         "--override-spec-seed",
         "--gate", "--gate-profile", "approach", "--repeat-check",
         "--report", close_report],
        [sys.executable, "-m", "tools.probe_cloud_flight", str(seed),
         "--renderer", "v2", "--quality", quality, "--preset", "2",
         "--spec", "docs/examples/flight_stationary_v2.json",
         "--override-spec-seed",
         "--gate", "--gate-profile", "stationary", "--freeze-cloud-time",
         "--repeat-check", "--report", still_report],
        [sys.executable, "-m", "tools.probe_cloud_flight", str(seed),
         "--renderer", "v2", "--quality", quality, "--preset", "6",
         "--spec", "docs/examples/flight_storm_underbelly_lightning.json",
         "--override-spec-seed",
         "--gate", "--gate-profile", "motion", "--report", storm_report],
    ]
    if require_lightning:
        commands[-1].append("--expect-lightning")
    return commands


def command_matrix(seed: int, quality: str, mode: str,
                   require_lightning: bool = True) -> list[list[str]]:
    commands = []
    if mode in ("visual", "all"):
        commands.extend(visual_commands(seed, quality))
    if mode == "orbit":
        commands.extend(orbit_commands(seed, quality))
    if mode in ("quantitative", "all"):
        commands.extend(quantitative_commands(seed, quality,
                                              require_lightning))
    return commands


def _display_command(command: list[str]) -> str:
    return subprocess.list2cmdline(command)


def run_suite(seed: int, quality: str, mode: str, dry_run: bool,
              require_lightning: bool, manifest: Path) -> int:
    commands = command_matrix(seed, quality, mode, require_lightning)
    results = []
    failed = False
    for index, command in enumerate(commands, 1):
        shown = _display_command(command)
        print(f"[cloud-suite] {index}/{len(commands)} {shown}")
        if dry_run:
            results.append({"command": command, "returncode": None})
            continue
        completed = subprocess.run(command, cwd=ROOT, text=True,
                                   capture_output=True, check=False)
        if completed.stdout:
            print(completed.stdout, end="")
        if completed.stderr:
            print(completed.stderr, end="", file=sys.stderr)
        results.append({
            "command": command,
            "returncode": int(completed.returncode),
            "stdout_tail": completed.stdout.splitlines()[-20:],
            "stderr_tail": completed.stderr.splitlines()[-20:],
        })
        failed |= completed.returncode != 0

    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({
        "schema": 1,
        "seed": seed,
        "quality": quality,
        "mode": mode,
        "require_lightning": require_lightning,
        "dry_run": dry_run,
        "preset_names": list(PRESET_NAMES),
        "results": results,
    }, indent=2), encoding="utf-8")
    print(f"[cloud-suite] wrote {manifest}")
    return 1 if failed else 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--quality", choices=("low", "med", "high", "ultra"),
                        default="high")
    parser.add_argument("--mode", choices=("visual", "orbit", "quantitative", "all"),
                        default="all")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-missing-lightning", action="store_true",
                        help="collect storm watch metrics without gating a flash")
    parser.add_argument("--manifest", type=Path,
                        default=Path("renders/cloud_acceptance_manifest.json"))
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    return run_suite(args.seed, args.quality, args.mode, args.dry_run,
                     not args.allow_missing_lightning, args.manifest)


if __name__ == "__main__":
    raise SystemExit(main())
