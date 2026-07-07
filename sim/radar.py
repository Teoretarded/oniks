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
from dataclasses import dataclass

import numpy as np

from sim.clutter import CLUTTER_ALT_M, sea_clutter_range_factor
from world.generation import terrain_height_scalar

HORIZON_K = 4_120.0     # m per sqrt(m): d = K*(sqrt(h_radar) + sqrt(h_tgt))
LOS_STEP_M = 2_000.0    # terrain sight-line sample spacing (long range)
# Close-in sampling (2026-06-18 audit fix): the coarse 2 km step took ZERO
# interior samples for any sight line under ~4 km (int(dist // 2000) == 0..1)
# and could step over a narrow ridge, so a coastal crest a few km out never
# masked a low target. Inside LOS_FINE_RANGE_M we step finely so close-range
# terrain masks honestly; beyond it the legacy 2 km step is kept (long-range
# behaviour byte-identical + bounded cost at 600 km).
LOS_FINE_STEP_M = 400.0
LOS_FINE_RANGE_M = 6_000.0


@dataclass(frozen=True)
class ScanDef:
    """HOW a radar searches (R-P0, spec PART 2 §9). The paint layer sits
    ABOVE ``detects`` — detects() stays the instantaneous range/horizon/
    terrain gate; ScanDef decides WHEN the beam is actually on a bearing.

    kind:
      * "staring"  — continuous coverage (fixed phased-array faces, SPY-1):
                     every bearing is always painted.
      * "rotating" — mechanical sweep; the beam crosses a bearing once per
                     ``period_s`` and dwells beamwidth/360 of the period.
      * "sector"   — electronically revisited wedge ``sector_deg`` wide
                     about the radar's ``boresight_deg``; bearings inside
                     revisit every ``period_s``, outside are NEVER painted.
    """
    kind: str
    period_s: float
    beamwidth_deg: float
    sector_deg: float


STARING = ScanDef("staring", 0.0, 360.0, 360.0)


def _bearing_deg(from_pos, to_pos) -> float:
    """Bearing 0 = +Z (north), increasing clockwise (LOCKED convention)."""
    return math.degrees(math.atan2(float(to_pos[0]) - float(from_pos[0]),
                                   float(to_pos[2]) - float(from_pos[2]))) \
        % 360.0


def _ang_diff_deg(a: float, b: float) -> float:
    """Smallest absolute angular difference, degrees, in [0, 180]."""
    return abs((a - b + 180.0) % 360.0 - 180.0)


def radar_horizon_m(h_radar_m: float, h_target_m: float) -> float:
    """4/3-earth radar horizon (meters) between two altitudes (meters ASL)."""
    return HORIZON_K * (math.sqrt(max(h_radar_m, 0.0))
                        + math.sqrt(max(h_target_m, 0.0)))


def terrain_blocks(a, b, height_fn=terrain_height_scalar) -> bool:
    """True when terrain rises above the straight sight line a -> b (both
    (x, y, z) meters). Endpoints are excluded (``range(1, n)``) so a radar can
    never block itself with its own hilltop. Sample spacing is LOS_FINE_STEP_M
    inside LOS_FINE_RANGE_M (so a close coastal crest masks a low target — the
    old coarse step took no interior samples under ~4 km) and the legacy
    LOS_STEP_M beyond it (byte-identical long-range behaviour + bounded cost)."""
    ax, ay, az = float(a[0]), float(a[1]), float(a[2])
    bx, by, bz = float(b[0]), float(b[1]), float(b[2])
    dist = math.hypot(bx - ax, bz - az)
    if dist <= LOS_FINE_RANGE_M:
        n = max(2, int(math.ceil(dist / LOS_FINE_STEP_M)))
    else:
        n = int(dist // LOS_STEP_M)
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

    def __init__(self, radar_id: str, pos, antenna_m: float, ranges: dict,
                 height_fn=terrain_height_scalar, scan: ScanDef = STARING,
                 band: str = "S", phase0_s: float = 0.0, sea_state: int = 3):
        self.radar_id = radar_id
        self.pos = np.asarray(pos, dtype=np.float64)
        self.antenna_m = float(antenna_m)
        self.ranges = dict(ranges)      # size class -> max range (m)
        self.alive = True
        self.emitting = True
        # R-P0 scan model (spec PART 2 §9): defaults (STARING) keep every
        # existing construction byte-identical — a staring radar is always
        # painting, which IS the legacy functional behavior. ``band`` is
        # the frequency band tag consumed by W-P10 rain attenuation.
        # ``boresight_deg`` is the sector center: a float for fixed sectors
        # or a zero-arg callable for slewed/body-fixed ones (fighter nose).
        self.scan = scan
        self.band = band
        self.phase0_s = float(phase0_s)
        self.boresight_deg = 0.0
        # F3-P2 sea clutter (sim/clutter.py): Douglas state this radar's sea
        # sits at.  Default 3 == identity by construction (the factor is
        # exactly 1.0), so every existing construction is byte-identical.
        self.sea_state = int(sea_state)
        # M3-terrain F3: the terrain height function for this radar's LOS
        # check. Default == the module shim terrain_height_scalar, so existing
        # callers stay byte-identical; world/combat.py threads the active
        # HeightField so player AND enemy read ONE terrain truth (no asymmetry).
        self._height_fn = height_fn

    @property
    def antenna_alt(self) -> float:
        return float(self.pos[1]) + self.antenna_m

    # --- R-P0 paint scheduling (closed-form — no per-tick sweeping) ---------

    def _boresight_now(self) -> float:
        b = self.boresight_deg
        return float(b()) if callable(b) else float(b)

    def next_paint_t(self, target_pos, now: float) -> float:
        """Earliest t >= now at which the search beam is on the target's
        bearing. STARING: now (continuous). SECTOR: next revisit tick when
        the bearing is inside the wedge, math.inf when outside. ROTATING:
        the next crossing of boresight(t) = 360*(t - phase0)/period."""
        s = self.scan
        if s.kind == "staring":
            return now
        if s.kind == "sector":
            if _ang_diff_deg(_bearing_deg(self.pos, target_pos),
                             self._boresight_now()) > s.sector_deg * 0.5:
                return math.inf
            k = math.ceil((now - self.phase0_s) / s.period_s - 1e-9)
            return self.phase0_s + max(k, 0) * s.period_s
        # rotating
        brg = _bearing_deg(self.pos, target_pos)
        t_first = self.phase0_s + brg / 360.0 * s.period_s
        k = math.ceil((now - t_first) / s.period_s - 1e-9)
        return t_first + max(k, 0) * s.period_s

    def painted(self, target_pos, now: float, window: float) -> bool:
        """True when a paint occurred inside [now - window, now] (rotating
        beams additionally count their dwell time across the bearing)."""
        s = self.scan
        if s.kind == "staring":
            return True
        nxt = self.next_paint_t(target_pos, now - window)
        if nxt == math.inf:
            return False
        dwell = (s.beamwidth_deg / 360.0 * s.period_s
                 if s.kind == "rotating" else 0.0)
        return nxt <= now + dwell

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
        # F3-P2 sea clutter: a low-flying small target competes with the
        # sea return (docs/research/sea_clutter.md).  State 3 (the default)
        # multiplies by exactly 1.0 — identity by construction; ships/
        # aircraft at altitude and surface hulls are untouched.
        tgt_alt = float(target_pos[1])
        if size_class in ("missile", "stealth") and tgt_alt < CLUTTER_ALT_M:
            max_range *= sea_clutter_range_factor(self.sea_state, tgt_alt)
        dx = float(target_pos[0]) - float(self.pos[0])
        dz = float(target_pos[2]) - float(self.pos[2])
        rng = math.hypot(dx, dz)
        if rng > max_range:
            return False
        if rng > radar_horizon_m(self.antenna_alt, float(target_pos[1])):
            return False
        return not terrain_blocks(
            (self.pos[0], self.antenna_alt, self.pos[2]), target_pos,
            height_fn=self._height_fn)


class RadarNetwork:
    """One side's shared track sources: visible == any live radar detects."""

    def __init__(self, radars=()):
        self.radars = list(radars)

    def visible(self, target_pos, size_class: str, jammers=()) -> bool:
        return any(r.detects(target_pos, size_class, jammers=jammers)
                   for r in self.radars)

    def paint_state(self, target_pos, size_class: str, now: float,
                    window: float, jammers=()):
        """Scanned-mode network answer (R-P0): ``(seen, next_paint)``.

        seen — some live radar both detects (range/horizon/terrain/EW) AND
        painted the bearing inside [now - window, now].
        next_paint — earliest upcoming paint among the radars whose
        ``detects`` passes right now (math.inf when none can see it): the
        ContactBoard schedules its next refresh on this."""
        seen, nxt = False, math.inf
        for r in self.radars:
            if not r.detects(target_pos, size_class, jammers=jammers):
                continue
            nxt = min(nxt, r.next_paint_t(target_pos, now))
            if r.painted(target_pos, now, window):
                seen = True
        return seen, nxt
