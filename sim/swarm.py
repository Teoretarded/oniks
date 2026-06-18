"""Loitering-munition swarm coordination (pure math, GL-free) — M4-B.

The swarm's coordinated time-on-target is PURE arithmetic — no RNG, no
wall-clock, deterministic for a given tasking (user law: physics, not dice):

    T = max_path / v_max + margin            (the shared time-on-target)
    v_i = path_i / T   clamped to [v_min, v_max]

The LONGEST route runs at ~v_max; every shorter route DAWDLES at v_i < v_max
so the whole bundle converges on the aim point at the same instant T.  A route
so short that v_i would fall under the loiterer's cruise floor is clamped to
v_min (it arrives a little early rather than stalling — a subsonic airframe
cannot fly below its minimum-control speed).

The per-round v_i is fed to Missile._commanded_speed (sim/missile.py), which
holds it as a GROUND speed through cruise.  This module is headless-unit-
testable in isolation (tests/test_swarm.py) and feeds world.launch_swarm
(world/combat.py).
"""

from __future__ import annotations

import math


def route_length(launch_xz, route) -> float:
    """Total ground path length from ``launch_xz`` (x, z) through the ordered
    (x, z) ``route`` waypoints (the final entry is the aim point) — the
    segment-hypot sum used by the time-on-target math."""
    lx, lz = float(launch_xz[0]), float(launch_xz[1])
    total = 0.0
    px, pz = lx, lz
    for (wx, wz) in route:
        wx, wz = float(wx), float(wz)
        total += math.hypot(wx - px, wz - pz)
        px, pz = wx, wz
    return total


def compute_swarm_speeds(launch_xz, per_round_routes, v_max,
                         margin=5.0, v_min=0.0):
    """Per-round cruise GROUND speeds for a simultaneous time-on-target.

    ``launch_xz``        : (x, z) bundle launch point (shared).
    ``per_round_routes`` : list of routes, one per round; each route is an
                           ordered list of (x, z) waypoints ending at the aim
                           point.  Path length is the segment-hypot sum from
                           ``launch_xz`` through the route.
    ``v_max``            : max cruise ground speed (the longest path flies ~this).
    ``margin``           : seconds added to the shared time T (terminal run-in /
                           settle slack so even the fastest round is not pinned
                           hard at v_max).
    ``v_min``            : cruise floor; a v_i below it is clamped (the round
                           arrives slightly early rather than stalling).

    Returns ``[v_i]`` aligned to ``per_round_routes``.  Empty input -> [].
    """
    if not per_round_routes:
        return []
    lengths = [route_length(launch_xz, r) for r in per_round_routes]
    max_len = max(lengths)
    if max_len <= 0.0 or v_max <= 0.0:
        # Degenerate tasking (everyone already on the aim point): every round
        # runs at the floor (or v_max if no floor) — nothing to synchronize.
        fallback = v_min if v_min > 0.0 else v_max
        return [fallback for _ in lengths]
    T = max_len / v_max + float(margin)
    speeds = []
    for L in lengths:
        v = L / T if T > 0.0 else v_max
        if v > v_max:
            v = v_max
        if v < v_min:
            v = v_min
        speeds.append(v)
    return speeds
