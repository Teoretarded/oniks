"""Probe: measured kill-per-burst of the physics CIWS/Pantsir gun model.

usage: python -m tools.probe_gun_physics

The 2026-07-17 rework replaced the flat Pk roll with an OU fire-control
tracking error gated against the dispersion-stream lethal radius
(sim/ciws.py).  This probe measures the ACTUAL kill-per-burst frequency at
fixed slant ranges over many seeds and prints it against the calibration
targets (the previous tuned Pk ramps):

    20 mm CIWS   : ~0.50 @ 800 m   ~0.15 @ 2000 m
    30 mm Pantsir: ~0.55 @ 1000 m  ~0.15 @ 4000 m

Run it BEFORE touching TRACK_SIGMA_MRAD / LETHAL_DISP_MRAD.  Measurement
tool, not a gate — exit 0 always (tests/test_sm2_ciws.py + the phase-6
e2e suite own the regression bands).
"""

from __future__ import annotations

import numpy as np

from sim.ciws import Ciws
from sim.pantsir import _Pantsir30mmGun

DT = 1.0 / 120.0
SEEDS = 400


class _Target:
    """Slow closer pinned near a fixed slant range (30 m/s barely moves the
    geometry across one 1.5 s burst cycle)."""

    def __init__(self, rng_m: float):
        self.pos = np.array([0.0, 30.0, rng_m], dtype=np.float64)
        self.alive = True

    def velocity(self):
        return np.array([0.0, 0.0, -30.0])

    def step(self, dt: float):
        self.pos[2] -= 30.0 * dt


def kill_per_burst(gun_cls, rng_m: float, seeds: int = SEEDS) -> float:
    kills = 0
    for seed in range(seeds):
        gun = gun_cls(ammo=10_000, rng=np.random.default_rng(seed))
        tgt = _Target(rng_m)
        # One full pause+fire cycle -> exactly one burst resolution.
        for _ in range(int(1.6 / DT)):
            gun.engage(tgt, DT)
            tgt.step(DT)
            if not tgt.alive:
                kills += 1
                break
    return kills / seeds


if __name__ == "__main__":
    print("=== gun-physics kill-per-burst probe "
          f"({SEEDS} seeds per cell) ===")
    for label, cls, cells, targets in (
            ("20mm CIWS   ", Ciws, (800.0, 1_400.0, 2_000.0),
             (0.50, None, 0.15)),
            ("30mm Pantsir", _Pantsir30mmGun, (1_000.0, 2_500.0, 4_000.0),
             (0.55, None, 0.15)),
    ):
        for rng_m, target in zip(cells, targets):
            p = kill_per_burst(cls, rng_m)
            want = f"  (target ~{target:.2f})" if target is not None else ""
            print(f"{label} @ {rng_m:6.0f} m : {p:.3f}{want}")
