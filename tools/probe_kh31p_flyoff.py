"""MEASURE FIRST — Kh-31P player ARM flyoff probe (M2-T2).

Fly a PlayerArmMissile(KH31P, ...) against a stationary EMITTING sim.radar.Radar
at a sweep of ground ranges and report, per range:
    peak Mach reached, time of flight, closest approach, HIT/MISS.

The StrikeMissile speed controller is tuned for SUBSONIC cruise; a Mach-3
cruise_mach is NOT free. This probe is the ground truth used to TUNE the KH31P
constants in sim/arsenal.py and to LOCK the envelope test ranges in
tests/test_kh31p_arm.py — never assume the airframe behaves.

Pattern mirrors tools/probe_zircon_traj.py / tools/compare_s300_rounds.py:
a GL-free deterministic flyoff over a flat-ground stub world.

Run:  python tools/probe_kh31p_flyoff.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from sim.arsenal import KH31P
from sim.radar import Radar
from sim.strike import PlayerArmMissile
from sim.physics import mach_scalar

PHYS_DT = 1.0 / 120.0
GROUND_H = 100.0          # m, flat dry-land ground height for the emitter
LAUNCH_GROUND_H = 100.0   # m, launcher ground height (same shelf)


class _FlatWorld:
    """Minimal GL-free world: flat dry land at GROUND_H everywhere."""

    ships = []

    def terrain_height_at(self, x, z):
        return GROUND_H

    def surface_height_at(self, x, z):
        return GROUND_H


def _make_emitter(ground_range_m):
    """Stationary emitting ground radar ground_range_m down-range (+Z)."""
    pos = (0.0, GROUND_H, ground_range_m)
    r = Radar("probe_emitter", pos, antenna_m=18.0,
              ranges={"missile": 200_000.0, "ship": 200_000.0,
                      "fighter": 200_000.0})
    r.alive = True
    r.emitting = True
    return r


def _flyoff(ground_range_m, max_t=300.0, silence_at_t=None):
    """Fly one ARM at an emitter ground_range_m away. Returns metrics dict.

    silence_at_t: if set, the emitter stops emitting at that ToF (for the
    silence-CEP behaviour check); None = emits the whole flight.
    """
    world = _FlatWorld()
    radar = _make_emitter(ground_range_m)
    # Launch from the player shelf, slight forward toss (air/rail release).
    launch_pos = np.array([0.0, LAUNCH_GROUND_H + 5.0, 0.0], dtype=np.float64)
    # 15-degree ELEVATED rail kick (mirrors world/combat.py launch_arm —
    # energy-model re-pin 2026-07-05: a level toss below stall speed sinks).
    vel0 = np.array([0.0, math.sin(math.radians(15.0)) * 60.0,
                     math.cos(math.radians(15.0)) * 60.0], dtype=np.float64)
    rng = np.random.default_rng([1337, 8])
    m = PlayerArmMissile(KH31P, launch_pos, vel0, radar, rng)

    peak_mach = 0.0
    closest = float("inf")
    fuel_out_t = None
    fuel_out_range = None
    silenced = False
    while m.alive and m.t < max_t:
        if (silence_at_t is not None and not silenced
                and m.t >= silence_at_t):
            radar.emitting = False
            silenced = True
        m.update(PHYS_DT, world)
        if fuel_out_t is None and m.fuel <= 0.0:
            fuel_out_t = m.t
            fuel_out_range = math.hypot(float(m.pos[0]),
                                        float(m.pos[2])) / 1000.0
        spd = float(np.linalg.norm(m.vel))
        peak_mach = max(peak_mach, mach_scalar(spd, float(m.pos[1])))
        # Closest approach to the TRUE radar position (3-D).
        d = float(np.linalg.norm(m.pos - radar.pos))
        closest = min(closest, d)
    hit = (not radar.alive) and (closest < KH31P.fuse_radius * 1.0001)
    return dict(rng_km=ground_range_m / 1000.0, peak_mach=peak_mach,
                tof=m.t, closest=closest, hit=hit,
                radar_alive=radar.alive, fuel_out_t=fuel_out_t,
                fuel_out_range=fuel_out_range)


def main():
    print("=== KH31P player ARM flyoff (emitting ground radar; lofted glide) ===")
    print(f"    booster {KH31P.booster_thrust:.0f} N x {KH31P.booster_time:.1f} s | "
          f"sustain {KH31P.max_thrust:.0f} N | isp {KH31P.isp:.0f} s | "
          f"fuel {KH31P.fuel_mass:.0f} kg")
    print(f"    cruise_mach {KH31P.cruise_mach:.1f} | cruise_alt "
          f"{KH31P.cruise_alt/1000:.0f} km | max_range "
          f"{KH31P.max_range/1000:.0f} km | fuse {KH31P.fuse_radius:.0f} m")
    print()
    print(f"  {'range':>7} {'peakMach':>9} {'ToF(s)':>8} {'closest(m)':>11} "
          f"{'result':>7} {'fuelout@':>10}")
    for rng_km in (60, 90, 110, 130, 140, 160):
        r = _flyoff(rng_km * 1000.0)
        fo = ("-" if r['fuel_out_range'] is None
              else f"{r['fuel_out_range']:.0f}km/{r['fuel_out_t']:.0f}s")
        print(f"  {r['rng_km']:6.0f}km {r['peak_mach']:9.2f} {r['tof']:8.1f} "
              f"{r['closest']:11.1f} {'HIT' if r['hit'] else 'MISS':>7} "
              f"{fo:>10}")

    print()
    print("=== silence-CEP check (emit 90 km shot, then go silent @ t=40 s) ===")
    rs = _flyoff(90_000.0, silence_at_t=40.0)
    print(f"  90km silenced@40s: closest={rs['closest']:.1f} m "
          f"radar_alive={rs['radar_alive']} "
          f"(expect survives: closest in 150..400 m ring)")


if __name__ == "__main__":
    main()
