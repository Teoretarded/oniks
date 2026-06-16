"""AUDIT PROBE: enemy ship SM-6 long-range SAM (sim/arsenal.py SM6,
sim/sam.py SamMissile, sim/enemy_defense.py).

Measures, never trusts comments:

  A. RAW KINEMATIC ENVELOPE — fire a clean SM6 SamMissile (no noise) at a
     non-maneuvering air target across ground range x altitude. Records
     kill/miss, time-to-intercept, miss distance, intercept altitude,
     and the death cause. This isolates the FLIGHT physics from the noise
     model and exposes any dead zones.

  B. DRONE ENGAGEMENT (as the ship actually fires it) — StealthTargetSam
     with SM6, vs the real ReconDrone at 18 km, sweeping ground range,
     N seeded shots each -> kill fraction (the emergent accuracy).

  C. DETERMINISM — same seed twice must be bit-identical.

  D. FULL BATTLE WIRING — build a CombatWorld, park the drone in the SM-6
     band past the SM-2 22 km drone cap, step, and confirm a destroyer
     actually launches an SM-6 round (sim/enemy_defense._try_sm6_launch).

Run: python tools/probe_audit_sm6.py   (ignore the pygame banner on stderr)
"""

import os
import sys
from math import hypot

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

import sim.enemy_defense as ed
from sim.arsenal import SM6
from sim.sam import SamMissile, PHASE_LABELS
from sim.enemy_defense import StealthTargetSam
from sim.recon import ReconDrone

DT = 1.0 / 120.0
DECK = np.array([0.0, 10.0, 0.0])     # Mk 41 deck height (VLS_DECK_M)
ILLUM = (0.0, 20.0, 0.0)              # SPY-1 illuminator height
DETECT_RANGE = 30_000.0              # SPY-1 'stealth' class range


class _OpenSea:
    """Minimal world stub: open ocean, no terrain mask, no ships."""
    ships = []

    def terrain_height_at(self, x, z):
        return -500.0


class _AirTarget:
    """Non-maneuvering air target: straight constant-velocity flight.
    Duck-types as a SamMissile target (pos / velocity() / alive / kill())."""

    def __init__(self, pos, vel):
        self.pos = np.asarray(pos, dtype=np.float64).copy()
        self.vel = np.asarray(vel, dtype=np.float64).copy()
        self.alive = True

    def velocity(self):
        return self.vel

    def kill(self):
        self.alive = False

    def update(self, dt):
        if self.alive:
            self.pos += self.vel * dt


def _illum_fn():
    return ILLUM


# --------------------------------------------------------------- A: envelope


def fly_clean(range_m, alt_m, speed=250.0, heading="cross", max_t=320.0):
    """One clean (noise-free) SM6 intercept of a constant-velocity target.

    Returns dict with kill, miss_m, t_intercept, intercept_alt, apogee,
    cause, max_speed.
    """
    if heading == "cross":          # crossing target (north-bound)
        vel = (0.0, 0.0, speed)
        tpos = (range_m, alt_m, -10_000.0)
    elif heading == "in":           # inbound toward the ship
        vel = (-speed, 0.0, 0.0)
        tpos = (range_m, alt_m, 0.0)
    else:                           # away / receding
        vel = (speed, 0.0, 0.0)
        tpos = (range_m, alt_m, 0.0)
    tgt = _AirTarget(tpos, vel)

    def contact():                  # honest fire-control fix (no noise)
        return (tgt.pos.copy(), tgt.vel.copy())

    sam = SamMissile(SM6, DECK, tgt, contact_estimate_fn=contact,
                     rng=None, illuminator_pos_fn=_illum_fn)
    w = _OpenSea()
    t = 0.0
    apogee = 0.0
    max_speed = 0.0
    min_miss = 1e18
    intercept_alt = None
    while sam.alive and t < max_t:
        tgt.update(DT)
        sam.update(DT, w)
        t += DT
        apogee = max(apogee, float(sam.pos[1]))
        sp = float(np.linalg.norm(sam.vel))
        max_speed = max(max_speed, sp)
        d = hypot(hypot(sam.pos[0] - tgt.pos[0], sam.pos[1] - tgt.pos[1]),
                  sam.pos[2] - tgt.pos[2])
        if d < min_miss:
            min_miss = d
            intercept_alt = float(sam.pos[1])
    cause = ("kill" if sam.killed_target
             else "selfdestruct" if sam.self_destructed
             else "ground/timeout")
    return dict(kill=sam.killed_target, miss_m=min_miss, t=t,
                intercept_alt=intercept_alt, apogee=apogee, cause=cause,
                max_speed=max_speed)


def section_a():
    print("=" * 78)
    print("A. RAW KINEMATIC ENVELOPE (clean guidance, crossing target 250 m/s)")
    print("   SM6: max_range=%.0f km  alt band=[%.0f, %.0f] m  "
          "terminal=%.0f km" % (SM6.max_range / 1e3, SM6.min_intercept_alt,
                                SM6.max_intercept_alt, SM6.terminal_range / 1e3))
    print("=" * 78)
    ranges = [10_000, 30_000, 60_000, 100_000, 150_000, 200_000, 240_000]
    alts = [100, 1_000, 5_000, 12_000, 18_000, 25_000, 32_000]
    hdr = "alt\\rng  " + "".join(f"{r // 1000:>8d}km" for r in ranges)
    print(hdr)
    kill_grid = {}
    for a in alts:
        cells = []
        for r in ranges:
            res = fly_clean(r, a)
            kill_grid[(r, a)] = res
            mark = "K" if res["kill"] else "."
            cells.append(f"{mark}{res['miss_m']:6.0f}m")
        print(f"{a:6d}m " + "".join(f"{c:>10s}" for c in cells))
    print()
    print("   Legend: K=kill (miss within 20 m fuse), . = miss; number = "
          "closest approach (m)")
    print()
    # detail rows for a few representative cells
    print("   Detail (range, alt -> cause, t_intercept, intercept_alt, "
          "apogee, peak_speed):")
    for (r, a) in [(60_000, 12_000), (150_000, 18_000), (240_000, 25_000),
                   (30_000, 100), (10_000, 32_000), (240_000, 100)]:
        res = kill_grid[(r, a)]
        print(f"     R={r//1000:3d}km alt={a:5d}m -> {res['cause']:14s} "
              f"t={res['t']:6.1f}s  hit_alt={(res['intercept_alt'] or 0):7.0f}m "
              f"apogee={res['apogee']:7.0f}m  Vmax={res['max_speed']:5.0f}m/s")
    return kill_grid


def section_a_heading():
    print()
    print("-" * 78)
    print("A2. HEADING SENSITIVITY at R=120 km, alt=15 km (inbound/cross/away)")
    print("-" * 78)
    for hd in ("in", "cross", "away"):
        res = fly_clean(120_000, 15_000, speed=250.0, heading=hd)
        print(f"   {hd:5s}: {'KILL' if res['kill'] else 'MISS':4s}  "
              f"miss={res['miss_m']:7.0f}m  t={res['t']:6.1f}s  "
              f"cause={res['cause']}")


def section_a_floor():
    print()
    print("-" * 78)
    print("A3. LOW-ALTITUDE FLOOR PROBE (crossing target, varying alt at R=40km)")
    print("-" * 78)
    for a in (5, 15, 25, 50, 100, 200, 500):
        res = fly_clean(40_000, a)
        print(f"   alt={a:4d}m: {'KILL' if res['kill'] else 'MISS':4s}  "
              f"miss={res['miss_m']:7.0f}m  hit_alt={(res['intercept_alt'] or 0):6.0f}m"
              f"  cause={res['cause']}")


# ------------------------------------------------------- B: drone (as fired)


def drone_engage(range_m, seed, alt=18_000.0, dspeed_route=None):
    """StealthTargetSam(SM6) vs the real ReconDrone (the ship's actual round).
    Returns (killed, min_miss)."""
    drone = ReconDrone(spawn_xz=(range_m, -20_000.0),
                       height_fn=lambda x, z: -500.0)
    drone.pos[1] = alt
    drone.set_route([(range_m, 500_000.0)])     # straight north crosser
    sam = StealthTargetSam(
        SM6, DECK, drone,
        rng=np.random.default_rng(seed),
        illuminator_pos_fn=_illum_fn,
        detection_range_m=DETECT_RANGE)
    w = _OpenSea()
    t = 0.0
    min_miss = 1e18
    while sam.alive and t < 320.0:
        drone.update(DT)
        sam.update(DT, w)
        t += DT
        d = hypot(hypot(sam.pos[0] - drone.pos[0], sam.pos[1] - drone.pos[1]),
                  sam.pos[2] - drone.pos[2])
        min_miss = min(min_miss, d)
    return sam.killed_target, min_miss


def section_b():
    print()
    print("=" * 78)
    print("B. DRONE ENGAGEMENT as the ship fires it (StealthTargetSam + SM6)")
    print("   ReconDrone at 18 km alt; sigma scales (R/30km)^3 CLAMPED to 1.0")
    print("   STEALTH_SNR_SIGMA_MAX_M=%.0f  tau=%.1fs  detect_range=%.0f km"
          % (ed.STEALTH_SNR_SIGMA_MAX_M, ed.STEALTH_SNR_TAU_S,
             DETECT_RANGE / 1e3))
    print("=" * 78)
    n = 15
    for r in (25_000, 40_000, 60_000, 100_000, 150_000, 200_000):
        kills = 0
        misses = []
        for i in range(n):
            k, mm = drone_engage(r, 4000 + i)
            kills += k
            misses.append(mm)
        snr_frac = min(r / DETECT_RANGE, 1.0) ** 3
        print(f"   R={r//1000:3d}km  kills={kills:2d}/{n} "
              f"({kills/n:4.2f})  median_miss={sorted(misses)[n//2]:7.0f}m  "
              f"snr_sigma_frac={snr_frac:.2f}")


# ----------------------------------------------------------- C: determinism


def section_c():
    print()
    print("=" * 78)
    print("C. DETERMINISM (same seed twice -> identical trajectory)")
    print("=" * 78)

    def trace(seed):
        drone = ReconDrone(spawn_xz=(60_000.0, -20_000.0),
                           height_fn=lambda x, z: -500.0)
        drone.pos[1] = 18_000.0
        drone.set_route([(60_000.0, 500_000.0)])
        sam = StealthTargetSam(SM6, DECK, drone,
                               rng=np.random.default_rng(seed),
                               illuminator_pos_fn=_illum_fn,
                               detection_range_m=DETECT_RANGE)
        w = _OpenSea()
        t = 0.0
        while sam.alive and t < 320.0:
            drone.update(DT)
            sam.update(DT, w)
            t += DT
        return tuple(round(float(x), 6) for x in sam.pos), sam.killed_target, round(t, 4)

    a = trace(12345)
    b = trace(12345)
    c = trace(99999)
    print(f"   seed 12345 run1: pos={a[0]} kill={a[1]} t={a[2]}")
    print(f"   seed 12345 run2: pos={b[0]} kill={b[1]} t={b[2]}")
    print(f"   seed 99999     : pos={c[0]} kill={c[1]} t={c[2]}")
    print(f"   DETERMINISTIC (12345==12345): {a == b}")
    print(f"   seed actually matters (12345!=99999): {a != c}")


# --------------------------------------------------- D: full battle wiring


def section_d():
    print()
    print("=" * 78)
    print("D. FULL BATTLE WIRING (does a destroyer actually launch an SM-6?)")
    print("=" * 78)
    from playtest_harness import build_world

    print("   SPY-1 stealth detection caps at 30 km; the SM-6 drone channel")
    print("   only fires beyond DRONE_ENGAGE_RANGE_M=22 km. Sweep the loiter")
    print("   offset to find where the channel actually opens (the real window).")
    print()
    for off in (18_000.0, 20_000.0, 25_000.0, 35_000.0, 60_000.0):
        w = build_world(7, n_destroyers=6)
        ship = w.ships[0]
        lx = float(ship.pos[0]) + off
        lz = float(ship.pos[2])
        w.drone.pos[0], w.drone.pos[2] = lx, lz
        w.drone.pos[1] = 18_000.0
        w.drone.set_route([(lx, lz)])    # loiter; do NOT re-pin (breaks track)

        def sm6_used():
            return sum(max(0, 6 - getattr(s, "sm6_ammo", 6)) for s in w.ships)

        def sm2_used():
            return sum(max(0, 24 - getattr(s, "sm2_ammo", 24)) for s in w.ships)

        fired_t = None
        killed_t = None
        for _ in range(int(240.0 / DT)):
            pre = w.drone is not None and w.drone.alive
            w.step(DT)
            if sm6_used() > 0 and fired_t is None:
                fired_t = round(w.sim_time, 1)
            if pre and (w.drone is None or not w.drone.alive):
                killed_t = round(w.sim_time, 1)
                break
        dead = w.drone is None or not w.drone.alive
        print(f"   loiter {off/1000:4.0f} km: SM6_fired={sm6_used()}  "
              f"first_fire_t={fired_t}  SM2_used={sm2_used()}  "
              f"drone_dead={dead}  killed_t={killed_t}")


def main():
    grid = section_a()
    section_a_heading()
    section_a_floor()
    section_b()
    section_c()
    section_d()
    print()
    print("=" * 78)
    print("DONE")
    print("=" * 78)


if __name__ == "__main__":
    main()
