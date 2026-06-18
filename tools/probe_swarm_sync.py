"""Probe: measure the loitering-munition swarm's coordinated time-on-target.

Two probes (run headless, deep open ocean, no kill rolls):

  sync    — flies an N-round SYNCHRONIZED bundle over doglegged routes of
            different length and reports each round's arrival time at the aim
            point + the spread (s).  A synced bundle must land within ~1-2 s.
  speeds  — prints the per-round path length, commanded ground speed, and the
            measured cruise speed so the time-on-target math is visible.

Usage:
    python tools/probe_swarm_sync.py            # both probes, N=6
    python tools/probe_swarm_sync.py --n 8
"""

import argparse
import math
import sys

import numpy as np

sys.path.insert(0, ".")

from sim.arsenal import SWARM            # noqa: E402
from sim.missile import Missile, PH_CRUISE, PH_DEAD  # noqa: E402
from sim.swarm import compute_swarm_speeds          # noqa: E402

DT = 1.0 / 120.0
_SAT_ALT = 28.0


class _OpenSea:
    ships = []

    def terrain_height_at(self, x, z):
        return -500.0

    def surface_height_at(self, x, z):
        return 0.0


def _path_len(launch, route):
    pts = [launch] + list(route)
    return sum(math.hypot(x1 - x0, z1 - z0)
               for (x0, z0), (x1, z1) in zip(pts, pts[1:]))


def _fan_routes(launch, aim, n):
    """N routes onto one aim point with increasing dogleg width (different
    path lengths — exactly what the sync math must equalize in time)."""
    routes = []
    midz = (launch[1] + aim[1]) * 0.5
    for i in range(n):
        if i == 0:
            routes.append([aim])
        else:
            width = (i / (n - 1)) * 20_000.0
            routes.append([(aim[0] + width, midz), aim])
    return routes


class _LevelSwarm(Missile):
    """A SWARM round flown DEAD-LEVEL through its route waypoints at the
    commanded ground speed — isolates the time-on-target MATH from the
    airframe's slow lo-lo terminal dive (see tests/test_swarm.py)."""

    def update(self, dt, world):
        if not self.alive:
            return
        np.copyto(self.prev_pos, self.pos)
        self.t += dt
        # Steer toward the current waypoint at the commanded speed; pop it on
        # arrival (the pure path-following the sync math assumes).
        wx, wz = self.route[0]
        dx, dz = wx - self.pos[0], wz - self.pos[2]
        dist = math.hypot(dx, dz)
        v = self._commanded_speed
        if dist <= v * dt and len(self.route) > 1:
            self.route.pop(0)
            wx, wz = self.route[0]
            dx, dz = wx - self.pos[0], wz - self.pos[2]
            dist = math.hypot(dx, dz) or 1.0
        inv = v / (dist or 1.0)
        self.vel[:] = (dx * inv, 0.0, dz * inv)
        self.pos += self.vel * dt


def _make_round(launch, route, commanded, salvo):
    aim = np.array([route[-1][0], _SAT_ALT, route[-1][1]], dtype=np.float64)
    pos = np.array([launch[0], _SAT_ALT, launch[1]], dtype=np.float64)
    wp = tuple(route[:-1])
    m = _LevelSwarm(SWARM, pos, 0.0, "lo-lo", aim, waypoints=wp, salvo=salvo)
    m.phase = PH_CRUISE
    m.hi = False
    m._commanded_speed = float(commanded)
    return m, aim


def probe_sync(n):
    launch = (0.0, 0.0)
    aim = (0.0, 35_000.0)
    routes = _fan_routes(launch, aim, n)
    v_max = SWARM.cruise_mach_hi * 340.0
    v_min = SWARM.cruise_mach_lo * 340.0
    speeds = compute_swarm_speeds(launch, routes, v_max, margin=5.0,
                                  v_min=v_min)
    world = _OpenSea()
    rounds = [_make_round(launch, routes[i], speeds[i], i) for i in range(n)]
    arrivals = [None] * n
    t = 0.0
    while t < 600.0 and any(a is None for a in arrivals):
        for i, (m, aimpt) in enumerate(rounds):
            if arrivals[i] is not None:
                continue
            m.update(DT, world)
            d = math.hypot(m.pos[0] - aimpt[0], m.pos[2] - aimpt[2])
            if d < 150.0 or m.phase == PH_DEAD:
                arrivals[i] = t
        t += DT
    print(f"=== SYNC probe (N={n}) ===")
    print(f"{'rnd':>3} {'path_km':>8} {'cmd_v':>7} {'arrive_s':>9}")
    for i in range(n):
        L = _path_len(launch, routes[i])
        a = arrivals[i]
        print(f"{i:>3} {L/1000:>8.2f} {speeds[i]:>7.1f} "
              f"{(a if a is not None else float('nan')):>9.2f}")
    got = [a for a in arrivals if a is not None]
    if got:
        spread = max(got) - min(got)
        print(f"arrival spread: {spread:.2f} s  ({len(got)}/{n} arrived)")
    return arrivals


def probe_saturation(n, seeds=8):
    """Synced vs spaced-trickle leak contrast vs ONE destroyer (sea-skim,
    deep ocean, CIWS off so the SM-2 channel + its in-flight cap is the
    isolated saturator).  The swarm rounds fly dead-level at the run-in
    altitude (scenario forcing — the airframe's slow lo-lo terminal dive is a
    separate tuning concern; here we isolate the DEFENCE throughput).  Prints
    the per-seed hits (a destroyer sinks at 3) for both modes."""
    import numpy as np
    from sim.enemy_defense import ShipDefense
    from sim.enemy_ships import Destroyer
    from sim.damage import apply_missile_hits
    from sim.missile import PH_CRUISE

    class _LevelSwarm(Missile):
        def update(self, dt, world):
            if not self.alive:
                return
            np.copyto(self.prev_pos, self.pos)
            self.t += dt
            self.pos += self.vel * dt

    def _mk(xz, aim, v, salvo, alt):
        pos = np.array([xz[0], alt, xz[1]], dtype=np.float64)
        m = _LevelSwarm(SWARM, pos, 0.0, "lo-lo", aim, salvo=salvo)
        m.is_hostile = False
        m.phase = PH_CRUISE
        m.hi = False
        m._commanded_speed = v
        dd = np.array([aim[0] - pos[0], 0.0, aim[2] - pos[2]])
        dd /= np.linalg.norm(dd)
        m.vel[:] = dd * v
        m.prev_pos[:] = m.pos
        return m

    def _run(synced, alt=28.0, run_in=55_000.0, v=120.0, seed=0,
             spacing=28.0, tmax=900.0):
        d = Destroyer("d", (0.0, 0.0), heading_deg=0.0)
        d.pos[:] = (0.0, 0.0, 0.0)
        d.ciws_ammo = 0

        class _W:
            def __init__(s):
                s.ships = [d]
                s.missiles = []
                s.events = []
                s.sim_time = 0.0

            def terrain_height_at(s, x, z):
                return -500.0

            def surface_height_at(s, x, z):
                return 0.0

        w = _W()
        defense = ShipDefense(d, np.random.default_rng(seed))
        aim = np.array([0.0, alt, 0.0])
        hits = 0
        t = 0.0
        nextr = 0
        if synced:
            for i in range(n):
                w.missiles.append(_mk(((i - n / 2) * 25.0, run_in), aim, v, i, alt))
        while t < tmax:
            if not synced and nextr < n and t >= nextr * spacing:
                w.missiles.append(_mk((0.0, run_in), aim, v, nextr, alt))
                nextr += 1
            w.sim_time = t
            d.sm2_reload_timer = max(0.0, d.sm2_reload_timer - DT)
            for x in w.missiles:
                x.update(DT, w)
            defense.step(w, DT)
            before = len(w.events)
            apply_missile_hits(
                [x for x in w.missiles if getattr(x, "weapon", None) is SWARM],
                w.ships, w.events)
            hits += sum(1 for k, _ in w.events[before:] if k == "ship_hit")
            w.missiles = [x for x in w.missiles if x.alive]
            t += DT
            if (synced or nextr >= n) and not any(
                    getattr(x, "weapon", None) is SWARM for x in w.missiles):
                break
        return hits

    syn = [_run(True, seed=s) for s in range(seeds)]
    tr = [_run(False, seed=s) for s in range(seeds)]
    print(f"=== SATURATION probe (N={n}, {seeds} seeds, sea-skim, CIWS off) ===")
    print(f"  synced  hits/seed: {syn}  (sum {sum(syn)}, min {min(syn)})")
    print(f"  trickle hits/seed: {tr}  (sum {sum(tr)}, max {max(tr)})")
    print(f"  synced sum > trickle sum: {sum(syn) > sum(tr)}")
    return syn, tr


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--mode", choices=("sync", "sat", "both"), default="both")
    args = ap.parse_args()
    if args.mode in ("sync", "both"):
        probe_sync(args.n)
    if args.mode in ("sat", "both"):
        probe_saturation(args.n)
