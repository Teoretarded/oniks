"""Probe to verify the M4-B saturation finding: is the leak from the in-flight
cap (simultaneity) or from magazine exhaustion (Winchester)?

Measures, vs ONE destroyer (CIWS off, SM-2 only):
  * lone round: hits + SM-2 spent
  * synced-8: hits + SM-2 spent + remaining ammo, FINITE and INFINITE ammo
  * spaced trickle (spacing >> engagement duration): hits + SM-2 spent,
    FINITE and INFINITE ammo

Run: python tools/probe_swarm_satcheck.py
"""
import sys
import math

import numpy as np

sys.path.insert(0, ".")

from sim.arsenal import SWARM                                   # noqa: E402
from sim.missile import Missile, PH_CRUISE                      # noqa: E402
from sim.enemy_defense import ShipDefense, SM2_MAX_INFLIGHT     # noqa: E402
from sim.enemy_ships import Destroyer                           # noqa: E402
from sim.damage import apply_missile_hits                       # noqa: E402

DT = 1.0 / 120.0
_SAT_ALT = 28.0
_SAT_RUN_IN = 45_000.0
_SAT_V = 110.0


class _LevelSwarm(Missile):
    def update(self, dt, world):
        if not self.alive:
            return
        np.copyto(self.prev_pos, self.pos)
        self.t += dt
        self.pos += self.vel * dt


class _W:
    def __init__(self, d):
        self.ships = [d]
        self.missiles = []
        self.events = []
        self.sim_time = 0.0

    def terrain_height_at(self, x, z):
        return -500.0

    def surface_height_at(self, x, z):
        return 0.0


def _mk(xz, aim, v, salvo):
    pos = np.array([xz[0], _SAT_ALT, xz[1]], dtype=np.float64)
    m = _LevelSwarm(SWARM, pos, 0.0, "lo-lo", aim, salvo=salvo)
    m.is_hostile = False
    m.phase = PH_CRUISE
    m.hi = False
    m._commanded_speed = float(v)
    dd = np.array([aim[0] - pos[0], 0.0, aim[2] - pos[2]])
    dd /= np.linalg.norm(dd)
    m.vel[:] = dd * v
    m.prev_pos[:] = m.pos
    return m


def run(n, seed, synced, ammo=None, spacing=None, fan_m=25.0, tmax=4000.0):
    d = Destroyer("d", (0.0, 0.0), heading_deg=0.0)
    d.pos[:] = (0.0, 0.0, 0.0)
    d.ciws_ammo = 0
    if ammo is not None:
        d.sm2_ammo = ammo
    start_ammo = d.sm2_ammo
    w = _W(d)
    defense = ShipDefense(d, np.random.default_rng(seed))
    aim = np.array([0.0, _SAT_ALT, 0.0], dtype=np.float64)
    if synced:
        for i in range(n):
            w.missiles.append(
                _mk(((i - n / 2) * fan_m, _SAT_RUN_IN), aim, _SAT_V, i))
    hits = 0
    peak = 0
    t = 0.0
    nextr = 0
    while t < tmax:
        if not synced and nextr < n and t >= nextr * spacing:
            w.missiles.append(_mk((0.0, _SAT_RUN_IN), aim, _SAT_V, nextr))
            nextr += 1
        w.sim_time = t
        d.sm2_reload_timer = max(0.0, d.sm2_reload_timer - DT)
        for m in w.missiles:
            m.update(DT, w)
        defense.step(w, DT)
        before = len(w.events)
        apply_missile_hits(
            [m for m in w.missiles if getattr(m, "weapon", None) is SWARM],
            w.ships, w.events)
        hits += sum(1 for k, _ in w.events[before:] if k == "ship_hit")
        peak = max(peak, len(defense._inflight))
        w.missiles = [m for m in w.missiles if m.alive]
        t += DT
        if (synced or nextr >= n) and not any(
                getattr(m, "weapon", None) is SWARM for m in w.missiles):
            break
    return dict(hits=hits, peak=peak, spent=start_ammo - d.sm2_ammo,
                remaining=d.sm2_ammo)


if __name__ == "__main__":
    BIG = 100000
    print("LONE round, finite default ammo (24):")
    for s in range(3):
        print("  seed", s, run(1, s, synced=True))

    print("\nSYNCED 8, finite default ammo (24):")
    for s in range(3):
        print("  seed", s, run(8, s, synced=True))

    print("\nSYNCED 8, INFINITE ammo:")
    for s in range(3):
        print("  seed", s, run(8, s, synced=True, ammo=BIG))

    # Engagement duration of a lone round ~ run_in/v = 45000/110 ~ 409 s.
    # Space the trickle well beyond that so each round is faced alone.
    print("\nTRICKLE 8, spacing 600s, INFINITE ammo:")
    for s in range(3):
        print("  seed", s, run(8, s, synced=False, ammo=BIG, spacing=600.0))

    print("\nTRICKLE 8, spacing 600s, finite default ammo (24):")
    for s in range(3):
        print("  seed", s, run(8, s, synced=False, ammo=24, spacing=600.0))

    print("\nTRICKLE 4, spacing 600s, finite default ammo (24):")
    for s in range(3):
        print("  seed", s, run(4, s, synced=False, ammo=24, spacing=600.0))
