"""Probe: quantify the energy model — what does a turn COST now?

usage: python -m tools.probe_energy_bleed

Measures (GL-free, deterministic, no rng):
  1. Sea-level Oniks lo-lo cruise, 180-degree retarget: speed-vs-time,
     min speed, turn completion time, recovery time back to 95% cruise.
  2. The same 180 at 14 km (hi cruise): turn time comparison (q-limited g).
  3. Burned-out S-300 coast at 10 km: aligned coast vs 90-degree crossing
     turn, deceleration over 3 s (research worked-example B analogue).

Prints a table; exit 0 always (a measurement tool, not a gate). The
two-sided regression bands derived from these numbers live in
tests/test_aero.py — re-run this probe BEFORE touching any of them.
"""

import math

import numpy as np

from sim.arsenal import ONIKS, S300
from sim.missile import PH_CRUISE, Missile
from sim.physics import speed_of_sound_scalar
from sim.sam import SPH_MIDCOURSE, SamMissile

DT = 1.0 / 120.0


class _World:
    ships = []

    def terrain_height_at(self, x, z):
        return -50.0


class _Target:
    def __init__(self, pos):
        self.pos = np.asarray(pos, dtype=np.float64)
        self.alive = True

    def velocity(self):
        return np.zeros(3)


def _cruise(profile, alt, mach):
    m = Missile(ONIKS, np.array([0.0, alt, 0.0]), 0.0, profile,
                np.array([0.0, 0.0, 400_000.0]))
    m.phase = PH_CRUISE
    m.vel = np.array([0.0, 0.0, mach * speed_of_sound_scalar(alt)])
    m.body_dir = np.array([0.0, 0.0, 1.0])
    return m


def run_180(alt, mach, label):
    w = _World()
    m = _cruise("hi-lo" if alt > 5_000.0 else "lo-lo", alt, mach)
    for _ in range(int(5.0 / DT)):
        m.update(DT, w)
    v0 = float(np.linalg.norm(m.vel))
    m.retarget(np.array([0.0, 0.0, -400_000.0]))
    min_speed, turn_t, rec_t = v0, None, None
    for i in range(int(240.0 / DT)):
        m.update(DT, w)
        s = float(np.linalg.norm(m.vel))
        min_speed = min(min_speed, s)
        hd = math.atan2(float(m.vel[0]), float(m.vel[2]))
        err = abs((hd - math.pi + math.pi) % (2.0 * math.pi) - math.pi)
        if turn_t is None and err < math.radians(15.0):
            turn_t = i * DT
        if turn_t is not None and rec_t is None and s >= 0.95 * v0:
            rec_t = i * DT
        if rec_t is not None:
            break
    print(f"{label}: cruise {v0:6.1f} m/s | min {min_speed:6.1f} "
          f"({100.0 * min_speed / v0:4.1f}%) | 180deg in "
          f"{turn_t if turn_t is not None else float('nan'):6.1f} s | "
          f"95% back at {rec_t if rec_t is not None else float('nan'):6.1f} s")
    return v0, min_speed, turn_t, rec_t


def sam_coast(aligned):
    w = _World()
    sam = SamMissile(S300, np.array([0.0, 10_000.0, 0.0]),
                     _Target((0.0, 10_000.0, 150_000.0)))
    sam.phase = SPH_MIDCOURSE
    sam.propellant = 0.0
    sam.vel = np.array([0.0, 0.0, 1200.0])
    if aligned:
        # Live flight-computer commanded path direction (the production path;
        # the old _aim_direction helper was removed 2026-07-17).
        cmd = sam._flight_computer_step(
            DT, w, 0.0, 10_000.0, 0.0, 0.0, 0.0, 1200.0)
        dx, dy, dz = sam._command_direction(
            0.0, 10_000.0, 0.0, sam._fc_aim, cmd)
        sam.vel = np.array([dx, dy, dz]) * 1200.0
    else:
        sam.vel = np.array([1.0, 0.0, 0.0]) * 1200.0
    sam.body_dir = sam.vel / np.linalg.norm(sam.vel)
    v0 = float(np.linalg.norm(sam.vel))
    for _ in range(int(3.0 / DT)):
        sam.update(DT, w)
    loss = v0 - float(np.linalg.norm(sam.vel))
    print(f"S-300 coast 10 km {'ALIGNED ' if aligned else 'CROSSING'}: "
          f"lost {loss:6.1f} m/s in 3 s ({loss / 3.0:5.1f} m/s^2 avg)")
    return loss


if __name__ == "__main__":
    print("=== energy-bleed probe (docs/plans/energy_physics_graphics"
          "_2026-07-05.md) ===")
    run_180(60.0, ONIKS.cruise_mach_lo, "Oniks lo-lo  60 m 180deg")
    run_180(14_000.0, ONIKS.cruise_mach_hi, "Oniks hi-lo 14 km 180deg")
    sam_coast(aligned=True)
    sam_coast(aligned=False)
