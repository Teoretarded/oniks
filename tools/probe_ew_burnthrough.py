"""Calibration probe for the M3-F1 EW burn-through field model (sim/ew.py).

MEASURE-FIRST: sweep a single jammer's standoff distance and log the
burn-through range that the player station's 350 km ship ring collapses to at
each standoff. Confirms (1) MONOTONICITY of burn-through in standoff and
(2) that the DEFAULT Growler-class jammer at its default standoff collapses
the ring to roughly HALF (~175 km), the spec's calibration target.

Run:  python tools/probe_ew_burnthrough.py
The default-case burn-through/effective range is what the LOCKED calibration
test band in tests/test_ew_field.py::test_calibration_band is pinned to.
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

import sim.ew as ew  # noqa: E402
from sim.radar import Radar  # noqa: E402

# Player station geometry (mirrors world/combat.py).
RADAR_POS = (40_000.0, 0.0, -6_000.0)
RADAR_ANTENNA_M = 18.0
SHIP_RING_M = 350_000.0
PLAYER_RANGES = {
    "ship": SHIP_RING_M, "fighter": SHIP_RING_M,
    "missile": 120_000.0, "stealth": 35_000.0,
}

# Flat sea-level terrain so LOS is always clear during the sweep (the field
# model itself is what we're calibrating, not horizon/terrain masking).
FLAT = lambda x, z: -100.0


class Jammer:
    def __init__(self, pos, jam_power_w):
        self.pos = np.asarray(pos, dtype=np.float64)
        self.jam_power_w = float(jam_power_w)


def main() -> int:
    radar = Radar("probe", RADAR_POS, RADAR_ANTENNA_M, dict(PLAYER_RANGES))
    tgt = (RADAR_POS[0] + 100_000.0, 0.0, RADAR_POS[2])  # nominal threat

    print(f"EW_CAL              = {ew.EW_CAL:.6e}")
    print(f"default jam_power_w = {ew.EW_DEFAULT_JAM_POWER_W:.1f} W")
    print(f"default standoff    = {ew.EW_DEFAULT_STANDOFF_M/1000:.0f} km")
    print(f"close-in floor      = {ew.EW_CLOSE_FLOOR_M/1000:.1f} km")
    print(f"ship ring (max)     = {SHIP_RING_M/1000:.0f} km")
    print()
    print(f"{'standoff_km':>12} {'burn_through_km':>16} {'effective_km':>14}")
    print("-" * 46)

    standoffs = [50_000.0, 75_000.0, 100_000.0, 120_000.0, 150_000.0,
                 180_000.0, 210_000.0, 250_000.0, 300_000.0]
    prev_bt = -1.0
    monotonic = True
    for so in standoffs:
        jam = Jammer((RADAR_POS[0], ew.EW_DEFAULT_JAMMER_ALT_M,
                      RADAR_POS[2] + so), ew.EW_DEFAULT_JAM_POWER_W)
        bt = ew.burn_through_range(radar, tgt, [jam], height_fn=FLAT)
        eff = ew.effective_range(radar, "ship", tgt, [jam], height_fn=FLAT)
        bt_km = bt / 1000.0 if math.isfinite(bt) else float("inf")
        marker = ""
        if so == ew.EW_DEFAULT_STANDOFF_M:
            marker = "   <- DEFAULT"
        print(f"{so/1000:>12.0f} {bt_km:>16.1f} {eff/1000:>14.1f}{marker}")
        if bt < prev_bt:
            monotonic = False
        prev_bt = bt

    print("-" * 46)
    print(f"MONOTONIC (burn-through rises with standoff): {monotonic}")

    # The locked default case.
    jam = Jammer((RADAR_POS[0], ew.EW_DEFAULT_JAMMER_ALT_M,
                  RADAR_POS[2] + ew.EW_DEFAULT_STANDOFF_M),
                 ew.EW_DEFAULT_JAM_POWER_W)
    eff_default = ew.effective_range(radar, "ship", tgt, [jam], height_fn=FLAT)
    half = SHIP_RING_M / 2.0
    print(f"\nDEFAULT effective range = {eff_default/1000:.1f} km "
          f"(half-ring target = {half/1000:.0f} km, "
          f"ratio = {eff_default/half:.3f})")

    if not monotonic:
        print("FAIL: burn-through not monotonic in standoff")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
