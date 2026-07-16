"""AI-friendly repeated full-physics missile batch runner.

Example:
    python tools/run_missile_workbench.py --weapon 40n6 --range-km 90 \
        --altitude-km 6.5 --motion cross --runs 100 --variation 0.05
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from game.missile_workbench import (  # noqa: E402
    TELEMETRY_LEVELS,
    VARIATIONS,
    WEAPONS,
    WorkbenchConfig,
    run_batch,
)
from tools.probe_sam_flight_computer import MOTION_VELOCITIES  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weapon", choices=WEAPONS, default="40n6")
    parser.add_argument("--range-km", type=float, default=90.0)
    parser.add_argument("--altitude-km", type=float, default=6.5)
    parser.add_argument("--motion", choices=tuple(MOTION_VELOCITIES),
                        default="cross")
    parser.add_argument("--track-update-s", type=float, default=1.0)
    parser.add_argument("--runs", type=int, default=100)
    parser.add_argument("--variation", type=float, default=0.05,
                        help="fractional spread around range/altitude/cadence")
    parser.add_argument("--telemetry", choices=TELEMETRY_LEVELS,
                        default="fast",
                        help="fast records flight tracks; full also records "
                             "every rejected planner candidate")
    parser.add_argument("--output", default="testing_flights")
    args = parser.parse_args()
    if args.variation < 0.0 or args.variation > max(VARIATIONS):
        parser.error(f"--variation must be between 0 and {max(VARIATIONS)}")
    config = WorkbenchConfig(
        weapon=args.weapon,
        range_km=args.range_km,
        altitude_km=args.altitude_km,
        motion=args.motion,
        track_update_s=args.track_update_s,
        runs=args.runs,
        variation=args.variation,
        telemetry=args.telemetry,
    )

    def progress(done, total):
        print(f"[missile-workbench] {done}/{total}", file=sys.stderr)

    batch = run_batch(config, args.output, progress)
    print(json.dumps({
        "output_dir": batch.output_dir,
        "runs": len(batch.results),
        "hit_rate": batch.hit_rate,
        "median_closest_m": batch.median_closest_m,
        "median_apogee_km": batch.median_apogee_km,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
