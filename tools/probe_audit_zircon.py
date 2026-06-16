"""Audit probe: player Zircon hypersonic flight path (sim/missile.py + ZIRCON).

Builds a minimal stationary-ship world and flies the Zircon Missile object
directly (no GL, no CombatWorld needed for the core physics). Exercises hi-lo
and lo-lo profiles across 80-300 km vs a stationary ship and PRINTS numbers:
apogee, vmax (m/s and Mach), closest approach, hit/miss, terminal speed, and
whether the high cruise is preserved (peak cruise altitude / time spent high).

Also confirms the DESCENT_BASELINE_MACH descent-scaling fix holds (the Mach-8
round must bleed altitude ~3.1x faster than the Oniks baseline or it overflies).

Run:  python tools/probe_audit_zircon.py     (pygame banner on stderr — ignore)
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from sim.arsenal import ZIRCON, ONIKS  # noqa: E402
from sim.missile import (Missile, DESCENT_BASELINE_MACH, PH_DEAD, PH_TERMINAL,  # noqa: E402
                         PH_CRUISE, PH_DESCENT, PHASE_LABELS)
from sim.physics import mach_scalar, speed_of_sound_scalar  # noqa: E402

PHYS_DT = 1.0 / 120.0   # match main.PHYS_DT (120 Hz sim)


class StationaryShip:
    """Minimal targetable: a fixed point at sea level (the seeker locks it)."""
    def __init__(self, x, z, y=8.0):
        self.pos = np.array([float(x), float(y), float(z)], dtype=np.float64)
        self.vel = np.zeros(3)
        self.alive = True


class FlatSeaWorld:
    """Open-water world stub: surface is y=0 everywhere, one ship list."""
    def __init__(self, ships):
        self.ships = ships

    def surface_height_at(self, x, z):
        return 0.0

    def terrain_height_at(self, x, z):
        return 0.0


def fly(weapon, profile, range_m, max_t=400.0):
    """Launch a missile from origin at a stationary ship ``range_m`` north.
    Returns a dict of measured flight metrics."""
    ship = StationaryShip(0.0, range_m)
    world = FlatSeaWorld([ship])
    target = np.array([0.0, 0.0, range_m], dtype=np.float64)
    heading = math.atan2(0.0, range_m)   # due north
    m = Missile(weapon, [0.0, 0.0, 0.0], heading, profile, target,
                target_ship=ship)

    apogee = 0.0
    vmax = 0.0
    vmax_alt = 0.0
    closest = float("inf")
    closest_t = 0.0
    cruise_peak_alt = 0.0          # peak alt reached while in CRUISE phase
    time_above_10k = 0.0           # s spent above 10 km (high-cruise preserved?)
    descent_entry_alt = None
    descent_entry_range = None
    terminal_speed = None
    phases_seen = []
    last_phase = None
    n = int(max_t / PHYS_DT)
    for _ in range(n):
        m.update(PHYS_DT, world)
        p = m.pos
        v = m.vel
        alt = float(p[1])
        spd = float(math.sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2]))
        if alt > apogee:
            apogee = alt
        if spd > vmax:
            vmax = spd
            vmax_alt = alt
        if alt > 10_000.0:
            time_above_10k += PHYS_DT
        if m.phase == PH_CRUISE and alt > cruise_peak_alt:
            cruise_peak_alt = alt
        if m.phase != last_phase:
            phases_seen.append((PHASE_LABELS.get(m.phase, "?"),
                                round(m.t, 1), round(alt, 0),
                                round(m._dist_to_target(), 0)))
            if m.phase == PH_DESCENT and descent_entry_alt is None:
                descent_entry_alt = alt
                descent_entry_range = m._dist_to_target()
            if m.phase == PH_TERMINAL and terminal_speed is None:
                terminal_speed = spd
            last_phase = m.phase
        # 3D miss distance to the ship aim point (closest approach)
        d3 = float(math.sqrt((p[0]-ship.pos[0])**2 + (p[1]-ship.pos[1])**2
                             + (p[2]-ship.pos[2])**2))
        if d3 < closest:
            closest = d3
            closest_t = m.t
        if not m.alive:
            break

    impact_spd = None
    impact_alt = None
    if m.impact_pos is not None:
        impact_alt = float(m.impact_pos[1])
        impact_spd = float(math.sqrt(m.vel[0]**2 + m.vel[1]**2 + m.vel[2]**2))

    # 2D horizontal distance of final/impact point past or short of target
    fdx = float(m.pos[0] - target[0])
    fdz = float(m.pos[2] - target[2])
    overshoot = fdz - 0.0   # north offset of final pos vs ship (target at +z)
    return dict(
        range_km=range_m / 1000.0, profile=profile,
        apogee_km=apogee / 1000.0,
        vmax=vmax, vmax_mach=vmax / speed_of_sound_scalar(vmax_alt),
        cruise_peak_km=cruise_peak_alt / 1000.0,
        time_above_10k=time_above_10k,
        descent_entry_km=(descent_entry_alt / 1000.0
                          if descent_entry_alt is not None else None),
        descent_entry_range_km=(descent_entry_range / 1000.0
                                if descent_entry_range is not None else None),
        terminal_speed=terminal_speed,
        closest_m=closest, closest_t=closest_t,
        impact_alt=impact_alt, impact_spd=impact_spd,
        final_pos=(round(float(m.pos[0]), 1), round(float(m.pos[1]), 1),
                   round(float(m.pos[2]), 1)),
        overshoot_m=overshoot,
        alive=m.alive, phase=PHASE_LABELS.get(m.phase, "?"),
        flight_t=m.t, phases=phases_seen,
    )


def fmt(r):
    hit = "HIT" if r["closest_m"] <= 25.0 else (
        "near" if r["closest_m"] <= 200.0 else "MISS")
    imp = (f"impact alt={r['impact_alt']:.1f}m spd={r['impact_spd']:.0f}m/s"
           if r["impact_alt"] is not None else "no-impact(alive)")
    return (f"{r['profile']:5s} {r['range_km']:5.0f}km | "
            f"apogee {r['apogee_km']:6.2f}km | "
            f"vmax {r['vmax']:6.0f}m/s (M{r['vmax_mach']:.2f}) | "
            f"cruise_peak {r['cruise_peak_km']:5.2f}km t>10k {r['time_above_10k']:5.1f}s | "
            f"closest {r['closest_m']:8.1f}m [{hit}] t={r['closest_t']:.1f}s | "
            f"{imp} | flight {r['flight_t']:.1f}s end={r['phase']}")


def main():
    print("=" * 110)
    print("ZIRCON descent-scale check")
    print(f"  ZIRCON.cruise_mach_hi = {ZIRCON.cruise_mach_hi}")
    print(f"  DESCENT_BASELINE_MACH = {DESCENT_BASELINE_MACH}")
    z_scale = max(1.0, ZIRCON.cruise_mach_hi / DESCENT_BASELINE_MACH)
    o_scale = max(1.0, ONIKS.cruise_mach_hi / DESCENT_BASELINE_MACH)
    print(f"  Zircon _descent_scale = {z_scale:.4f}  (Oniks = {o_scale:.4f}, must be 1.0)")
    print(f"  ZIRCON cruise_alt_hi={ZIRCON.cruise_alt_hi}m  lo_alt={ZIRCON.lo_alt}m "
          f"skim_alt={ZIRCON.skim_alt}m terminal_range={ZIRCON.terminal_range}m")
    print("=" * 110)

    ranges = [80_000, 100_000, 150_000, 200_000, 250_000, 300_000]

    print("\n--- ZIRCON hi-lo ---")
    hi_results = []
    for rg in ranges:
        r = fly(ZIRCON, "hi-lo", rg)
        hi_results.append(r)
        print("  " + fmt(r))

    print("\n--- ZIRCON lo-lo ---")
    lo_results = []
    for rg in ranges:
        r = fly(ZIRCON, "lo-lo", rg)
        lo_results.append(r)
        print("  " + fmt(r))

    # Baseline: Oniks hi-lo 150 km for comparison (descent-scale must be 1.0).
    print("\n--- ONIKS hi-lo 150km (baseline, _descent_scale must be 1.0) ---")
    ob = fly(ONIKS, "hi-lo", 150_000)
    print("  " + fmt(ob))

    # Determinism check: same launch twice must be bit-identical.
    print("\n--- determinism (ZIRCON hi-lo 150km x2) ---")
    a = fly(ZIRCON, "hi-lo", 150_000)
    b = fly(ZIRCON, "hi-lo", 150_000)
    same = (a["closest_m"] == b["closest_m"] and a["apogee_km"] == b["apogee_km"]
            and a["vmax"] == b["vmax"] and a["final_pos"] == b["final_pos"])
    print(f"  identical={same}  closest a={a['closest_m']:.4f} b={b['closest_m']:.4f}  "
          f"apogee a={a['apogee_km']:.4f} b={b['apogee_km']:.4f}")

    # Phase timeline detail for one representative hi-lo shot.
    print("\n--- phase timeline: ZIRCON hi-lo 200km (phase, t_s, alt_m, range_to_tgt_m) ---")
    rdetail = fly(ZIRCON, "hi-lo", 200_000)
    for ph in rdetail["phases"]:
        print(f"  {ph}")

    print("\n=== SUMMARY ===")
    hi_hits = sum(1 for r in hi_results if r["closest_m"] <= 25.0)
    lo_hits = sum(1 for r in lo_results if r["closest_m"] <= 25.0)
    print(f"  hi-lo hits (<=25m): {hi_hits}/{len(hi_results)}")
    print(f"  lo-lo hits (<=25m): {lo_hits}/{len(lo_results)}")
    print(f"  hi-lo apogee range: {min(r['apogee_km'] for r in hi_results):.2f}"
          f" - {max(r['apogee_km'] for r in hi_results):.2f} km")
    print(f"  hi-lo vmax range: {min(r['vmax'] for r in hi_results):.0f}"
          f" - {max(r['vmax'] for r in hi_results):.0f} m/s "
          f"(M{min(r['vmax_mach'] for r in hi_results):.1f}"
          f"-M{max(r['vmax_mach'] for r in hi_results):.1f})")
    print(f"  hi-lo time>10km: {min(r['time_above_10k'] for r in hi_results):.1f}"
          f" - {max(r['time_above_10k'] for r in hi_results):.1f} s")


if __name__ == "__main__":
    main()
