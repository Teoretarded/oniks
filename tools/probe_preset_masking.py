"""Probe: M3-terrain F4 seeded map presets actually mask LOS.

For each preset (0 OPEN SEA / 1 ARCHIPELAGO / 2 NARROW STRAIT / 3 FJORD COAST)
this reports:
  * the field's island count + tallest peak,
  * whether the open-water duel corridor stays CLEAR (must, on every preset —
    the Oniks-vs-SM-2 duel runs in deep mid-ocean), and
  * whether a sea-skim sight line across a mid-ocean island is MASKED (must, on
    presets 1-3 — terrain is finally consulted), reporting the worst clearance.

It also confirms the byte-identical gate (preset 0 == the default field) and
the cluster-stability gate (the base/SAM/radar/airfield pins read identical
terrain on every preset).

Run: python tools/probe_preset_masking.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from sim.radar import terrain_blocks
from world.generation import (DEFAULT_FIELD, HeightField, MAP_PRESET_COUNT,
                              make_field)
from world.combat_config import MAP_PRESET_NAMES

SEED = 1337

# Deep mid-ocean duel corridor (must stay clear on every preset).
DUEL_A = (0.0, 20.0, 150_000.0)
DUEL_B = (0.0, 20.0, 330_000.0)

# Cluster pins that must read identical terrain on every preset.
PINS = [
    ("base", 0.0, -600.0), ("SAM", 85_000.0, -3_500.0),
    ("radar", 40_000.0, -6_000.0), ("airfield", 60_000.0, 516_000.0),
    ("enemy_radar_band", 0.0, 502_000.0),
]


def worst_clearance(field, a, b, n=400):
    """Max (terrain - sight line) over fine sampling — > 0 means truly masked."""
    ax, ay, az = a
    bx, by, bz = b
    worst = -1e9
    for i in range(1, n):
        t = i / n
        x = ax + (bx - ax) * t
        z = az + (bz - az) * t
        line = ay + (by - ay) * t
        worst = max(worst, field.height_scalar(x, z) - line)
    return worst


def find_masked_pair(field):
    """A sensor/target pair a tall island masks (sensor S of the island, low
    target N of it). Returns (a, b, peak, worst) or None."""
    for cx, cz, r, peak in field.islands:
        if peak < 120.0 or not (60_000.0 < cz < 440_000.0):
            continue
        a = (cx, 20.0, cz - 1.5 * r)
        b = (cx, 8.0, cz + 1.5 * r)
        if terrain_blocks(a, b, height_fn=field.height_scalar):
            return a, b, peak, worst_clearance(field, a, b)
    return None


def main() -> int:
    ok = True

    # Byte-identical gate.
    xs = np.linspace(-340_000, 340_000, 400)
    zs = np.linspace(-40_000, 560_000, 400)
    p0 = make_field(0, SEED)
    same = np.array_equal(p0.height(xs[None, :], zs[:, None]),
                          HeightField().height(xs[None, :], zs[:, None]))
    print(f"preset 0 IS default field: {p0 is DEFAULT_FIELD}   "
          f"byte-identical heights: {same}")
    ok = ok and (p0 is DEFAULT_FIELD) and same

    ref = make_field(0, SEED)
    print("\npreset                 islands  tallest   duel-clear   masked? "
          "(worst clearance)")
    for p in range(MAP_PRESET_COUNT):
        field = make_field(p, SEED)
        tallest = max((isl[3] for isl in field.islands), default=0.0)
        duel_clear = not terrain_blocks(DUEL_A, DUEL_B,
                                        height_fn=field.height_scalar)
        pair = find_masked_pair(field)
        if p == 0:
            masked_str = "n/a (open sea)"
            preset_ok = duel_clear
        else:
            preset_ok = duel_clear and pair is not None
            masked_str = (f"MASKED (+{pair[3]:.0f} m)" if pair
                          else "NONE FOUND (FAIL)")
        ok = ok and preset_ok
        print(f"  {p} {MAP_PRESET_NAMES[p]:<14} {len(field.islands):>7}  "
              f"{tallest:>6.0f} m   {'clear' if duel_clear else 'BLOCKED':<10}  "
              f"{masked_str}")
        # Cluster stability.
        for name, x, z in PINS:
            if field.height_scalar(x, z) != ref.height_scalar(x, z):
                print(f"      CLUSTER DRIFT at {name} ({x}, {z})")
                ok = False

    print(f"\n{'ALL CHECKS PASS' if ok else 'CHECKS FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
