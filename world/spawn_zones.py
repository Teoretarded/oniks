"""Seeded fleet spawn zones for COMBAT (pure numpy, GL-free).

One zone, one mechanism (user direction: "just make it the black"):
the fleet spawns inside an ocean SECTOR fanning out from the player base
toward the enemy coast, range band 110-300 km. Density is shaped by
sampling the range from a TRIANGULAR distribution peaking at 180 km —
anywhere in the sector is possible, the middle band is most likely, the
edges taper off. No two-tier zones, no special cases.

The carrier is different: it samples from a deeper band (240-330 km,
escorted and hanging back), so it usually sits beyond lo-lo Oniks fuel
range — finding it is the recon game, reaching it is the hi-lo/saturation
(or future long-range weapon) game. Up to two destroyers place as escorts
20-35 km off the carrier; the rest screen forward in the main zone.

Placement contracts (LOCKED by tests/test_spawn_zones.py):
  * deterministic per seed (same Generator state -> same fleet),
  * every hull in verified open water (terrain < -10 m across a 9 km
    clearance disc, so patrol boxes never beach),
  * >= 25 km separation between hulls (10+ ships spread, never clump),
  * sector half-angle 50 deg about +z keeps everything in mid-ocean.

Wired into CombatWorld generation in Phase 7 (setup screen / seed entry);
until then tools/probe_map_anchors.py renders the zone and a sample fleet.
"""

from __future__ import annotations

import math

import numpy as np

from world.generation import BASE_POS, terrain_height_scalar

# Main screen zone (destroyers and future escorts/combatants)
ZONE_RANGE_MIN_M = 110_000.0     # inside: too close to the player's coast
ZONE_RANGE_MODE_M = 180_000.0    # triangular peak: most ships near here
ZONE_RANGE_MAX_M = 300_000.0     # outer taper (hi-lo / standoff territory)
ZONE_HALF_ANGLE_DEG = 50.0       # sector about +z (toward the enemy coast)

# Carrier band: deep, screened, usually beyond lo-lo reach (~230 km flown)
CARRIER_RANGE_MIN_M = 240_000.0
CARRIER_RANGE_MODE_M = 280_000.0
CARRIER_RANGE_MAX_M = 330_000.0

ESCORT_OFFSET_M = (20_000.0, 35_000.0)   # ring around the carrier
MIN_SEPARATION_M = 25_000.0              # hull-to-hull spacing floor
CLEAR_DEPTH_M = -10.0                    # "open water" depth requirement
CLEAR_RADIUS_M = 9_000.0                 # patrol box must fit in open water
_MAX_TRIES = 200                         # rejection-sampling cap per hull

_BASE_XZ = (float(BASE_POS[0]), float(BASE_POS[2]))


def is_open_water(x: float, z: float) -> bool:
    """Open water at (x, z) and across the patrol clearance disc: center
    plus 4 cardinal offsets all below CLEAR_DEPTH_M (cheap 5-point probe
    of the 9 km box, matching the Phase-2 anchor sweep contract)."""
    for dx, dz in ((0.0, 0.0), (CLEAR_RADIUS_M, 0.0), (-CLEAR_RADIUS_M, 0.0),
                   (0.0, CLEAR_RADIUS_M), (0.0, -CLEAR_RADIUS_M)):
        if terrain_height_scalar(x + dx, z + dz) > CLEAR_DEPTH_M:
            return False
    return True


def _sample_sector(rng: np.random.Generator, r_min: float, r_mode: float,
                   r_max: float) -> tuple[float, float]:
    """One (x, z) draw: triangular range, uniform bearing in the sector."""
    rng_m = rng.triangular(r_min, r_mode, r_max)
    bearing = math.radians(rng.uniform(-ZONE_HALF_ANGLE_DEG,
                                       ZONE_HALF_ANGLE_DEG))
    return (_BASE_XZ[0] + rng_m * math.sin(bearing),
            _BASE_XZ[1] + rng_m * math.cos(bearing))


def _far_enough(p: tuple[float, float], placed: list) -> bool:
    return all(math.hypot(p[0] - q[0], p[1] - q[1]) >= MIN_SEPARATION_M
               for q in placed)


def _place(rng: np.random.Generator, placed: list, r_min: float,
           r_mode: float, r_max: float) -> tuple[float, float]:
    """Rejection-sample one open-water, separated point in a band."""
    for _ in range(_MAX_TRIES):
        p = _sample_sector(rng, r_min, r_mode, r_max)
        if is_open_water(*p) and _far_enough(p, placed):
            placed.append(p)
            return p
    raise RuntimeError("spawn zone could not place a hull "
                       f"(band {r_min/1e3:.0f}-{r_max/1e3:.0f} km, "
                       f"{len(placed)} already placed)")


def sample_fleet(rng: np.random.Generator, n_destroyers: int) -> dict:
    """Seeded fleet layout: {'carrier': (x, z), 'destroyers': [(x, z)...]}.

    Carrier first (deep band), then up to 2 escorts on its 20-35 km ring,
    then the remaining destroyers screening in the main zone."""
    placed: list[tuple[float, float]] = []
    carrier = _place(rng, placed, CARRIER_RANGE_MIN_M, CARRIER_RANGE_MODE_M,
                     CARRIER_RANGE_MAX_M)
    destroyers: list[tuple[float, float]] = []
    for _ in range(min(2, n_destroyers)):           # carrier escorts
        for _ in range(_MAX_TRIES):
            ang = rng.uniform(0.0, 2.0 * math.pi)
            off = rng.uniform(*ESCORT_OFFSET_M)
            p = (carrier[0] + off * math.sin(ang),
                 carrier[1] + off * math.cos(ang))
            if is_open_water(*p) and _far_enough(p, placed):
                placed.append(p)
                destroyers.append(p)
                break
        else:
            raise RuntimeError("could not place a carrier escort")
    for _ in range(max(0, n_destroyers - 2)):       # forward screen
        destroyers.append(_place(rng, placed, ZONE_RANGE_MIN_M,
                                 ZONE_RANGE_MODE_M, ZONE_RANGE_MAX_M))
    return {"carrier": carrier, "destroyers": destroyers}
