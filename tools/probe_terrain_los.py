"""Probe: terrain_blocks close-range LOS masking (2026-06-18 audit MEDIUM fix).

Reproduces the audit's real-map case at the player radar station and reports
whether a low target behind the close coastal crest is now masked, plus an
open-water sanity check (must stay CLEAR — the Oniks-vs-SM-2 duel runs there).

Run: python tools/probe_terrain_los.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sim.radar import (LOS_FINE_RANGE_M, LOS_FINE_STEP_M, LOS_STEP_M,
                       terrain_blocks)
from world.generation import HeightField

field = HeightField()
hf = field.height_scalar

# Player radar station (world/combat coords) — antenna ~18 m over its hill.
RX, RZ = 40_000.0, -6_000.0
ground = hf(RX, RZ)
antenna_alt = ground + 18.0
print(f"radar station ground={ground:.1f} m  antenna_alt={antenna_alt:.1f} m")

# Find the masking crest north of the station within 6 km.
peak, peak_dz = -1e9, 0.0
for dz in range(200, 6000, 50):
    h = hf(RX, RZ + dz)
    if h > peak:
        peak, peak_dz = h, dz
print(f"highest terrain within 6 km north: {peak:.1f} m at dz={peak_dz:.0f} m")


def los_blocked(target_dz, target_alt=10.0):
    a = (RX, antenna_alt, RZ)
    b = (RX, target_alt, RZ + target_dz)
    return terrain_blocks(a, b, height_fn=hf)


def worst_clearance(target_dz, target_alt=10.0):
    """Max (terrain - sight line) over fine sampling — >0 means truly masked."""
    a_alt, b_alt = antenna_alt, target_alt
    worst = -1e9
    for i in range(1, 200):
        t = i / 200.0
        z = RZ + target_dz * t
        line = a_alt + (b_alt - a_alt) * t
        worst = max(worst, hf(RX, z) - line)
    return worst

print(f"\nsampling: fine step {LOS_FINE_STEP_M:.0f} m within {LOS_FINE_RANGE_M:.0f} m,"
      f" else {LOS_STEP_M:.0f} m")
print("dz(km)  truth_worst(m)  terrain_blocks()")
for dz in (2500.0, 3000.0, 3500.0, 4000.0, 5000.0, 11_000.0):
    w = worst_clearance(dz)
    truth = "MASKED" if w > 0 else "clear"
    print(f"  {dz/1e3:4.1f}   {w:+8.1f} ({truth:6})   {los_blocked(dz)}")

# Open water (duel domain): two points far out to sea, deep ocean below — must
# be CLEAR regardless of sampling density (terrain < 0 everywhere on the line).
ow_a = (0.0, 60.0, 150_000.0)
ow_b = (0.0, 8_000.0, 350_000.0)
print(f"\nopen-water long LOS blocked? {terrain_blocks(ow_a, ow_b, height_fn=hf)}"
      f"  (expect False)")
# A short open-water sight line (sea-skim duel geometry) — must stay clear.
ow_short = terrain_blocks((0.0, 15.0, 200_000.0), (0.0, 15.0, 203_000.0),
                          height_fn=hf)
print(f"open-water short LOS blocked? {ow_short}  (expect False)")
