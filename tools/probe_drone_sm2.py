"""Measure SM-2 kill fraction vs the stealth recon drone (Phase 4 gate).

Sweeps STEALTH_SNR_SIGMA_MAX_M candidates x engagement ranges and prints
the kill fraction per cell, N seeded engagements each — the measurement
behind the locked constant in sim/enemy_defense.py (methodology of
tools/probe_sm2_batch.py: tune the PHYSICAL noise parameter until the
emergent statistics match the spec table, never touch outcomes directly).

Geometry per engagement: ship director at the origin (20 m), the real
ReconDrone crossing at ground range R, 18 km altitude, 160 m/s; one
StealthTargetSam fired at t = 0 guided on truth + the low-SNR error
(the fire-control dead-reckon adds nothing against a straight crosser).

Run: python tools/probe_drone_sm2.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

import sim.enemy_defense as ed
from sim.arsenal import SM2
from sim.recon import ReconDrone
from sim.enemy_defense import StealthTargetSam

DT = 1.0 / 120.0
DETECT_RANGE = 30_000.0          # SPY-1 'stealth' class range
DECK = np.array([0.0, 10.0, 0.0])


class _OpenSea:
    ships = []

    def terrain_height_at(self, x, z):
        return -500.0


def _illum():
    return (0.0, 20.0, 0.0)


def _engage(range_m: float, seed: int) -> bool:
    drone = ReconDrone(spawn_xz=(range_m, -20_000.0),
                       height_fn=lambda x, z: -500.0)
    drone.set_route([(range_m, 500_000.0)])     # straight north crosser
    sam = StealthTargetSam(
        SM2, DECK, drone,
        rng=np.random.default_rng(seed),
        illuminator_pos_fn=_illum,
        detection_range_m=DETECT_RANGE)
    w = _OpenSea()
    t = 0.0
    while sam.alive and t < 120.0:
        drone.update(DT)
        sam.update(DT, w)
        t += DT
    return sam.killed_target


def main():
    n = 15
    for sigma in (40.0, 60.0, 80.0):
        ed.STEALTH_SNR_SIGMA_MAX_M = sigma
        row = [f"sigma {sigma:5.0f}:"]
        for rng_m in (10_000.0, 20_000.0, 28_000.0):
            kills = sum(_engage(rng_m, 1000 + i) for i in range(n))
            row.append(f"R={rng_m / 1e3:4.0f} km {kills:2d}/{n}")
        print("  ".join(row))


if __name__ == "__main__":
    main()
