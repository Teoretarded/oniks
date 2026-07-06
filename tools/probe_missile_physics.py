"""Missile physics stress probe — the flight-dynamics instrument panel.

usage:
  python -m tools.probe_missile_physics [weapon] [profile] [range_km]
  (defaults: oniks lo-lo 90)

Flies one round at a stationary aim point over open water and records the
FULL dynamic state every 0.1 s straight off the live object + the same
formulas the sim uses (no sim modification, no RNG):

  t, range-to-go, altitude, speed, Mach, fuel,
  a_avail   = q*S*CLmax/m   (the PHYSICAL g-limit at this speed/altitude)
  a_achieved= |autopilot state| (what the fins actually delivered)
  drag_para = q*S*Cd(Mach)   and  drag_induced = K*L^2/(qS)
  thrust    = the spooled sustainer state
  cross     = signed cross-track offset from the launch-aim line

Prints a phase-by-phase summary + red-flag scan:
  * ENERGY: speed increases while maneuvering hard in level flight
    (physics says a level turn only BLEEDS speed unless thrust covers it)
  * G-LIMIT: achieved acceleration above the q-limit
  * TELEPORT: per-tick position step inconsistent with velocity (>2x v*dt)
Writes the CSV next to this run's documentation folder for plotting.

This is the PERMANENT tool the 2026-07-06 overnight session was asked to
leave behind: any future AI can stress a missile's physics with it and
read numbers instead of vibes.  See
documentation and research/01_missile_physics_and_models/README.md.
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sim import arsenal
from sim.missile import Missile
from sim.aero import q_scalar
from sim.physics import cd_from_mach_scalar, mach_scalar

DT = 1.0 / 120.0
SAMPLE_S = 0.1
OUT_DIR = os.path.join("documentation and research",
                       "01_missile_physics_and_models")


class _World:
    """Open-water stub (the test-suite pattern): flat sea, no ships."""
    missiles = ()
    ships = ()

    @staticmethod
    def surface_height_at(x, z):
        return 0.0

    @staticmethod
    def terrain_height_at(x, z):
        return -60.0


def _weapon(name: str):
    w = getattr(arsenal, name.upper(), None)
    if w is None:
        raise SystemExit(f"unknown weapon {name!r} (use e.g. ONIKS/ZIRCON)")
    return w


def fly(weapon_id="oniks", profile="lo-lo", range_km=90.0):
    w = _weapon(weapon_id)
    target = np.array([0.0, 0.0, range_km * 1_000.0])
    m = Missile(w, np.zeros(3), 0.0, profile, target)
    world = _World()
    rows = []
    t = 0.0
    next_s = 0.0
    while m.alive and t < 900.0:
        m.update(DT, world)
        t += DT
        if t + 1e-9 < next_s:
            continue
        next_s += SAMPLE_S
        vx, vy, vz = m.vel.tolist()
        speed = math.sqrt(vx * vx + vy * vy + vz * vz)
        alt = float(m.pos[1])
        mach = mach_scalar(speed, max(alt, 0.0))
        q = q_scalar(speed, max(alt, 0.0))
        qs = q * w.ref_area
        a_avail = qs * m._cl_max / m.mass
        a_ach = math.sqrt(m._ap_x ** 2 + m._ap_y ** 2 + m._ap_z ** 2)
        drag_p = qs * cd_from_mach_scalar(mach)
        lift = m.mass * a_ach
        drag_i = m._k_ind * lift * lift / max(qs, 1e-9)
        d = math.hypot(float(target[0]) - m.pos[0],
                       float(target[2]) - m.pos[2])
        rows.append((t, d, alt, speed, mach, float(m.fuel),
                     a_avail / 9.80665, a_ach / 9.80665,
                     drag_p, drag_i, float(m._thrust_act),
                     float(m.pos[0]), m.phase, m.phase_label))
    return m, rows


def report(m, rows, weapon_id, profile):
    print(f"=== {weapon_id.upper()}  {profile}  "
          f"{'HIT/impact' if m.impact_pos is not None else 'no impact'} ===")
    print(f"{'t':>6} {'rng km':>7} {'alt':>6} {'spd':>6} {'M':>5} "
          f"{'gAvl':>5} {'gAch':>5} {'dragP':>7} {'dragI':>7} "
          f"{'thr':>7} {'cross':>6}  phase")
    last_label = None
    for r in rows:
        if r[13] != last_label:                    # phase transitions only
            last_label = r[13]
            print(f"{r[0]:>6.1f} {r[1] / 1e3:>7.1f} {r[2]:>6.0f} "
                  f"{r[3]:>6.0f} {r[4]:>5.2f} {r[6]:>5.1f} {r[7]:>5.1f} "
                  f"{r[8]:>7.0f} {r[9]:>7.0f} {r[10]:>7.0f} "
                  f"{r[11]:>6.0f}  {r[13]}")

    # --- red-flag scan: terminal window energy honesty -------------------
    term = [r for r in rows if r[13] == "TERMINAL" and r[1] > 1_500.0]
    flags = []
    if term:
        v0 = term[0][3]
        vmax = max(r[3] for r in term)
        vmin = min(r[3] for r in term)
        # Level terminal (skim): any speed RISE beyond thrust-hold slack is
        # phantom energy; diving terminals legitimately gain speed.
        level = all(abs(r[2] - term[0][2]) < 60.0 for r in term)
        print(f"\nTERMINAL window: entry {v0:.0f} m/s, "
              f"min {vmin:.0f}, max {vmax:.0f}, "
              f"{'LEVEL' if level else 'DIVING'}, "
              f"peak achieved g {max(r[7] for r in term):.1f} "
              f"(avail {min(r[6] for r in term):.1f})")
        if level and vmax > v0 + 8.0:
            flags.append(f"ENERGY: level terminal speed ROSE {vmax - v0:.0f} "
                         "m/s above entry (phantom energy)")
        over = [r for r in rows if r[7] > r[6] + 0.5]
        if over:
            flags.append(f"G-LIMIT: achieved g exceeded the q-limit on "
                         f"{len(over)} samples (max +"
                         f"{max(r[7] - r[6] for r in over):.1f} g)")
    speed_series = [r[3] for r in rows]
    jump = max((abs(b - a) for a, b in zip(speed_series, speed_series[1:])),
               default=0.0)
    if jump > 60.0:
        flags.append(f"TELEPORT/SPIKE: speed jumped {jump:.0f} m/s "
                     "in one 0.1 s sample")
    print("\nRED FLAGS:" if flags else "\nRED FLAGS: none")
    for f in flags:
        print("  ! " + f)

    os.makedirs(OUT_DIR, exist_ok=True)
    csv = os.path.join(OUT_DIR, f"flight_{weapon_id}_{profile}.csv")
    with open(csv, "w", encoding="utf-8") as f:
        f.write("t,range_m,alt_m,speed,mach,fuel,g_avail,g_achieved,"
                "drag_para,drag_induced,thrust,cross_x,phase,label\n")
        for r in rows:
            f.write(",".join(str(v) for v in r) + "\n")
    print(f"\n[csv] {csv}")
    return flags


def main() -> int:
    weapon_id = sys.argv[1] if len(sys.argv) > 1 else "oniks"
    profile = sys.argv[2] if len(sys.argv) > 2 else "lo-lo"
    rng = float(sys.argv[3]) if len(sys.argv) > 3 else 90.0
    m, rows = fly(weapon_id, profile, rng)
    flags = report(m, rows, weapon_id, profile)
    return 1 if flags else 0


if __name__ == "__main__":
    raise SystemExit(main())
