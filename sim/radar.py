"""Functional radar model (pure numpy, GL-free) — COMBAT fog of war.

A Radar detects a target when ALL of:
  * the radar is alive and emitting,
  * ground range <= its max range for the target's size class
    ("ship" / "fighter" / "missile" / "stealth"),
  * the target is above the radar horizon (earth curvature),
  * terrain does not block the straight sight line.

RadarNetwork is one side's datalink: a target is visible to the side when
ANY of its radars detects it — destroying a radar instantly removes its
coverage. ``RadarNetwork.visible`` is the ``ContactBoard`` gate
(sim/contacts.py). No beam scanning / RCS math (spec: functional model).
"""

from __future__ import annotations

import math

import numpy as np

from world.generation import terrain_height_scalar

HORIZON_K = 4_120.0     # m per sqrt(m): d = K*(sqrt(h_radar) + sqrt(h_tgt))
LOS_STEP_M = 2_000.0    # terrain sight-line sample spacing


def radar_horizon_m(h_radar_m: float, h_target_m: float) -> float:
    """4/3-earth radar horizon (meters) between two altitudes (meters ASL)."""
    return HORIZON_K * (math.sqrt(max(h_radar_m, 0.0))
                        + math.sqrt(max(h_target_m, 0.0)))


def terrain_blocks(a, b, height_fn=terrain_height_scalar) -> bool:
    """True when terrain rises above the straight sight line a -> b (both
    (x, y, z) meters). Samples every LOS_STEP_M, endpoints excluded so a
    radar can never block itself with its own hilltop."""
    ax, ay, az = float(a[0]), float(a[1]), float(a[2])
    bx, by, bz = float(b[0]), float(b[1]), float(b[2])
    n = int(math.hypot(bx - ax, bz - az) // LOS_STEP_M)
    for i in range(1, n):
        t = i / n
        if height_fn(ax + (bx - ax) * t, az + (bz - az) * t) \
                > ay + (by - ay) * t:
            return True
    return False


class Radar:
    """One radar: site position (x, y_ground, z) float64, antenna height
    above the site, max detection range per size class. ``alive`` clears on
    destruction (Phase 3 wires HP); ``emitting`` is the radar-silence switch
    (a silent radar sees nothing — and can't be passively located later)."""

    def __init__(self, radar_id: str, pos, antenna_m: float, ranges: dict):
        self.radar_id = radar_id
        self.pos = np.asarray(pos, dtype=np.float64)
        self.antenna_m = float(antenna_m)
        self.ranges = dict(ranges)      # size class -> max range (m)
        self.alive = True
        self.emitting = True

    @property
    def antenna_alt(self) -> float:
        return float(self.pos[1]) + self.antenna_m

    def detects(self, target_pos, size_class: str, jammers=()) -> bool:
        if not (self.alive and self.emitting):
            return False
        # Empty path (default): byte-identical to the pre-EW gate — the raw
        # range lookup, untouched. Only consult the EW burn-through field
        # when one or more jammers are present (M3-F1, sim/ew.py).
        if not jammers:
            max_range = self.ranges.get(size_class, 0.0)
        else:
            from sim import ew
            max_range = ew.effective_range(self, size_class, target_pos, jammers)
        dx = float(target_pos[0]) - float(self.pos[0])
        dz = float(target_pos[2]) - float(self.pos[2])
        rng = math.hypot(dx, dz)
        if rng > max_range:
            return False
        if rng > radar_horizon_m(self.antenna_alt, float(target_pos[1])):
            return False
        return not terrain_blocks(
            (self.pos[0], self.antenna_alt, self.pos[2]), target_pos)


class RadarNetwork:
    """One side's shared track sources: visible == any live radar detects."""

    def __init__(self, radars=()):
        self.radars = list(radars)

    def visible(self, target_pos, size_class: str, jammers=()) -> bool:
        return any(r.detects(target_pos, size_class, jammers=jammers)
                   for r in self.radars)
