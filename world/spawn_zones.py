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


def is_open_water(x: float, z: float, height_fn=terrain_height_scalar) -> bool:
    """Open water at (x, z) and across the patrol clearance disc: center
    plus 4 cardinal offsets all below CLEAR_DEPTH_M (cheap 5-point probe
    of the 9 km box, matching the Phase-2 anchor sweep contract).

    ``height_fn`` defaults to the module terrain (byte-identical for existing
    callers); M3-F4 passes the ACTIVE preset field's scalar so the fleet
    rejection-sampler dodges the preset's seeded mid-ocean islands, not just
    the default map's."""
    for dx, dz in ((0.0, 0.0), (CLEAR_RADIUS_M, 0.0), (-CLEAR_RADIUS_M, 0.0),
                   (0.0, CLEAR_RADIUS_M), (0.0, -CLEAR_RADIUS_M)):
        if height_fn(x + dx, z + dz) > CLEAR_DEPTH_M:
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
           r_mode: float, r_max: float,
           height_fn=terrain_height_scalar) -> tuple[float, float]:
    """Rejection-sample one open-water, separated point in a band."""
    for _ in range(_MAX_TRIES):
        p = _sample_sector(rng, r_min, r_mode, r_max)
        if is_open_water(*p, height_fn=height_fn) and _far_enough(p, placed):
            placed.append(p)
            return p
    raise RuntimeError("spawn zone could not place a hull "
                       f"(band {r_min/1e3:.0f}-{r_max/1e3:.0f} km, "
                       f"{len(placed)} already placed)")


# M5 doctrinal bands (toward the player coast = smaller range):
#   * carrier + flagship: the DEEP central band (high-value, hang back).  The
#     flagship rides the carrier's escort ring so the CEC hub stays close to
#     the asset it protects.
#   * aaw: FORWARD toward ZONE_RANGE_MIN — the air-defense picket leans into the
#     threat axis (it shoots the inbound raid first).
#   * ground_attack: the MID band (the general screen band) — it loiters to
#     range the back-plot, neither deep nor exposed.
#   * transports: the REAR (deepest) band — amphibious shipping hides behind
#     the carrier (n_transports=0 here; the band exists for a later feature).
# TODO(M5+ amphibious-landing, handoff 05): n_transports is intentionally
#   UNWIRED from CombatConfig / world.combat._spawn_ships — there is no transport
#   hull class yet.  This sampler path + the TRANSPORT_* bands + the four
#   spawn_zones tests are forward-scaffolding for the amphibious-landing feature;
#   wire n_transports through CombatConfig (+ CLAMP_TRANSPORTS + a Transport hull
#   in sim/enemy_ship_classes.py) when that milestone lands.  Inert (count 0) and
#   byte-identical-safe until then.
AAW_RANGE_MIN_M = ZONE_RANGE_MIN_M           # 110 km — forward picket
AAW_RANGE_MODE_M = 140_000.0                  # peaks nearer the player than the
AAW_RANGE_MAX_M = 200_000.0                   #   general screen's 180 km mode
TRANSPORT_RANGE_MIN_M = CARRIER_RANGE_MIN_M   # rear, with / behind the carrier
TRANSPORT_RANGE_MODE_M = CARRIER_RANGE_MODE_M
TRANSPORT_RANGE_MAX_M = CARRIER_RANGE_MAX_M


def _place_escort_ring(rng, placed, carrier, height_fn):
    """Rejection-sample one open-water, separated point on the carrier's
    20-35 km escort ring (the legacy escort draw, factored out)."""
    for _ in range(_MAX_TRIES):
        ang = rng.uniform(0.0, 2.0 * math.pi)
        off = rng.uniform(*ESCORT_OFFSET_M)
        p = (carrier[0] + off * math.sin(ang),
             carrier[1] + off * math.cos(ang))
        if is_open_water(*p, height_fn=height_fn) and _far_enough(p, placed):
            placed.append(p)
            return p
    raise RuntimeError("could not place a carrier escort")


def sample_fleet(rng: np.random.Generator, n_destroyers: int,
                 height_fn=terrain_height_scalar,
                 *, n_flagship: int = 0, n_aaw: int = 0,
                 n_ground_attack: int = 0, n_transports: int = 0) -> dict:
    """Seeded TYPED fleet roster.  Returns:

        {'carrier': (x, z),
         'flagship': (x, z) | None,
         'aaw': [(x, z)...],
         'ground_attack': [(x, z)...],
         'general': [(x, z)...],
         'transports': [(x, z)...],
         'destroyers': [(x, z)...]}     # == 'general' (back-compat alias)

    DRAW ORDER (the byte-identical contract): carrier (deep) -> up to 2 general
    escorts on the carrier ring -> the rest of the general screen -> THEN the
    new roles (flagship, aaw, ground_attack, transports).  Each new-role loop
    draws NOTHING when its count is 0, and the new draws come AFTER the entire
    legacy sequence, so with n_flagship=n_aaw=n_ground_attack=n_transports=0
    the rng stream and every placement are bit-for-bit today's fleet — the
    'general'/'destroyers' list is then EXACTLY the legacy 'destroyers' output.

    Bands (spec 05 e): carrier/flagship deep-central, aaw forward (toward
    ZONE_RANGE_MIN), ground_attack mid (the general screen band), transports
    rear.  Every hull is open-water (9 km disc) + >= 25 km separated for any
    mix (the shared rejection sampler enforces both).

    ``height_fn`` defaults to the module terrain (byte-identical for the
    default map); M3-F4 callers pass the ACTIVE preset field's scalar."""
    placed: list[tuple[float, float]] = []
    carrier = _place(rng, placed, CARRIER_RANGE_MIN_M, CARRIER_RANGE_MODE_M,
                     CARRIER_RANGE_MAX_M, height_fn=height_fn)
    # --- legacy general-destroyer sequence (UNCHANGED draw order) ---
    general: list[tuple[float, float]] = []
    for _ in range(min(2, n_destroyers)):           # carrier escorts
        general.append(_place_escort_ring(rng, placed, carrier, height_fn))
    for _ in range(max(0, n_destroyers - 2)):       # forward screen
        general.append(_place(rng, placed, ZONE_RANGE_MIN_M,
                              ZONE_RANGE_MODE_M, ZONE_RANGE_MAX_M,
                              height_fn=height_fn))

    # --- M5 typed roles (all loops are no-ops at count 0 -> byte-identical) ---
    # Flagship: rides the carrier escort ring (deep-central, near its asset).
    flagship = None
    if n_flagship > 0:
        flagship = _place_escort_ring(rng, placed, carrier, height_fn)

    # AAW: the FORWARD air-defense picket.
    aaw: list[tuple[float, float]] = []
    for _ in range(max(0, n_aaw)):
        aaw.append(_place(rng, placed, AAW_RANGE_MIN_M, AAW_RANGE_MODE_M,
                          AAW_RANGE_MAX_M, height_fn=height_fn))

    # Ground attack: the MID (general screen) band.
    ground_attack: list[tuple[float, float]] = []
    for _ in range(max(0, n_ground_attack)):
        ground_attack.append(_place(rng, placed, ZONE_RANGE_MIN_M,
                                    ZONE_RANGE_MODE_M, ZONE_RANGE_MAX_M,
                                    height_fn=height_fn))

    # Transports: the REAR (deep) band, behind the carrier.
    transports: list[tuple[float, float]] = []
    for _ in range(max(0, n_transports)):
        transports.append(_place(rng, placed, TRANSPORT_RANGE_MIN_M,
                                 TRANSPORT_RANGE_MODE_M, TRANSPORT_RANGE_MAX_M,
                                 height_fn=height_fn))

    return {
        "carrier": carrier,
        "flagship": flagship,
        "aaw": aaw,
        "ground_attack": ground_attack,
        "general": general,
        "transports": transports,
        # Back-compat alias: every existing caller / test reads 'destroyers'
        # as the general-destroyer placements.
        "destroyers": general,
    }
