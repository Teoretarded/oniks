"""Deterministic 600 km world generation: seeded hash noise, terrain heightfield,
shipping lanes, land sites, ship spawns.

Pure numpy, GL-free. All distances in meters (SI). Axes: X = east, Z = north.
`terrain_height` is THE single source of truth for the world's shape; everything
(terrain meshes, collision, placement) derives from it.

Layout (see plan LOCKED CONVENTIONS):
  - Home continent coastline wiggles around z = 0; land at z < coast.
  - Enemy continent coastline around z = ENEMY_COAST_Z; land at z > coast.
  - Hand-placed islands between z = 60 km and z = 420 km (plus two outliers).
  - Ocean rendered at y = 0; seabed is negative terrain height.
"""

import math

import numpy as np

SEED = 1337
WORLD_HALF = 350_000.0
ENEMY_COAST_Z = 500_000.0     # note: beyond WORLD_HALF in z; drawable band z in [-40_000, 560_000]

# Strict upper bound on terrain_height anywhere (Task 22 perf): the tallest
# island peak is 430 m scaled by (0.4 + 0.6 * fbm) with fbm < 1, and the
# continents top out under 145 m — so no terrain ever reaches this. Flyers
# above it can skip ground-impact queries entirely (sim/missile.py).
TERRAIN_MAX_HEIGHT = 430.0


def _hash01(ix, iz, seed):
    # ix, iz int64 arrays -> uniform [0,1) float64
    h = (ix.astype(np.int64) * 374761393 + iz.astype(np.int64) * 668265263 + seed * 982451653) & 0x7FFFFFFF
    h = (h ^ (h >> 13)) * 1274126177 & 0x7FFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFFFF) / float(0x1000000)


def value_noise(x, z, cell, seed):
    """Bilinear-interpolated lattice noise with smoothstep weights -> [0,1) float64."""
    gx = np.asarray(x, dtype=np.float64) / cell
    gz = np.asarray(z, dtype=np.float64) / cell
    ix = np.floor(gx).astype(np.int64)
    iz = np.floor(gz).astype(np.int64)
    fx = gx - ix
    fz = gz - iz
    wx = fx * fx * (3.0 - 2.0 * fx)
    wz = fz * fz * (3.0 - 2.0 * fz)
    n00 = _hash01(ix, iz, seed)
    n10 = _hash01(ix + 1, iz, seed)
    n01 = _hash01(ix, iz + 1, seed)
    n11 = _hash01(ix + 1, iz + 1, seed)
    nx0 = n00 + (n10 - n00) * wx
    nx1 = n01 + (n11 - n01) * wx
    return nx0 + (nx1 - nx0) * wz


def fbm(x, z, cell, octaves, seed, gain=0.5, lacunarity=2.0):
    """Standard fractal sum of value noise, normalized to [0,1]."""
    total = 0.0
    amp = 1.0
    amp_sum = 0.0
    c = float(cell)
    for i in range(octaves):
        total = total + amp * value_noise(x, z, c, seed + i * 101)
        amp_sum += amp
        amp *= gain
        c /= lacunarity
    return total / amp_sum


def _smoothstep01(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


ISLANDS = [  # (cx, cz, radius_m, peak_m) — hand-placed, ~9 islands
    (-38_000, 95_000, 9_000, 220), (52_000, 140_000, 14_000, 380), (-120_000, 180_000, 7_000, 150),
    (18_000, 235_000, 11_000, 290), (140_000, 260_000, 16_000, 430), (-65_000, 310_000, 8_000, 180),
    (95_000, 355_000, 6_000, 120), (-150_000, 90_000, 5_000, 90), (-20_000, 405_000, 10_000, 240),
]

# Coast/terrain tuning constants
_COAST_WIGGLE = 2_500.0       # coastline wiggle amplitude (m)
_COAST_RAMP = 4_000.0         # land rises to full height over this distance from coast (m)
_SHELF_RAMP = -3.0            # continents extend underwater to -3x full height (continental shelf)
_ISLAND_SHORE_SLOPE = 400.0   # m of drop per island-radius outside the shoreline


def _continent(x, z, signed_dist, height_seed):
    """Continent contribution: ramps from 0 at the coast up to 55-145 m inland,
    and continues smoothly below 0 offshore (continental shelf) so the max() with
    the ocean floor never produces a cliff. `signed_dist` > 0 on the land side."""
    r = np.clip(signed_dist / _COAST_RAMP, _SHELF_RAMP, 1.0)
    return r * (55.0 + 90.0 * fbm(x, z, 8_000.0, 4, height_seed))


def terrain_height(x, z):
    """Vectorized float64 terrain height (m). > 0 is land; < 0 is seabed
    (ocean surface is rendered at y = 0). THE single source of truth."""
    x = np.asarray(x, dtype=np.float64)
    z = np.asarray(z, dtype=np.float64)
    x, z = np.broadcast_arrays(x, z)

    zeros = np.zeros_like(x)
    # Home continent: coast wiggles in [0, 2500] around z = 0; land rises to the south.
    home_coast = _COAST_WIGGLE * fbm(x, zeros, 30_000.0, 4, SEED + 1)
    h = _continent(x, z, home_coast - z, SEED + 2)

    # Enemy continent: mirrored — coast wiggles in [500_000 - 2500, 500_000]; land rises north.
    enemy_coast = ENEMY_COAST_Z - _COAST_WIGGLE * fbm(x, zeros, 30_000.0, 4, SEED + 3)
    h = np.maximum(h, _continent(x, z, z - enemy_coast, SEED + 4))

    # Islands: radial smoothstep falloff above water, steep (but continuous)
    # underwater skirt outside the shoreline so max() stays cliff-free.
    for k, (cx, cz, radius, peak) in enumerate(ISLANDS):
        d = np.sqrt((x - cx) ** 2 + (z - cz) ** 2)
        m = 1.0 - d / radius                    # > 0 inside the island
        lift = _smoothstep01(m) ** 1.5 * (peak * (0.4 + 0.6 * fbm(x, z, radius * 0.35, 4, SEED + 5 + 17 * k)))
        h_isl = np.where(m >= 0.0, lift, m * _ISLAND_SHORE_SLOPE)
        h = np.maximum(h, h_isl)

    # Ocean floor: gently rolling seabed, always well below the surface.
    floor = -60.0 - 80.0 * fbm(x, z, 20_000.0, 3, SEED + 6)
    return np.maximum(h, floor)


def is_land(x, z):
    return terrain_height(x, z) > 0.0


# --- scalar fast path (Task 22 perf) ------------------------------------------
#
# Per-missile surface checks, falling boosters and the camera ground clamp all
# query the heightfield at SINGLE points every sim step; the vectorized
# terrain_height costs ~5 ms per scalar call (numpy dispatch overhead on
# 1-element arrays times ~55 value_noise evaluations). The pure-Python path
# below is bit-identical (verified by tests/test_generation.py) and ~300x
# faster for scalars because it
#   - runs the identical float64 arithmetic without array machinery, and
#   - skips work that provably cannot change the final max():
#     * a continent whose shelf ramp is fully clamped (r == -3) contributes
#       at most -165 m, always below the ocean floor's worst case of -140 m;
#     * an island's fbm matters only strictly inside its shoreline (outside,
#       the skirt term m * slope needs no noise; at m == 0 the lift is 0);
#     * the ocean floor (max -60 m) is masked whenever h already >= -60 m.
#
# Integer note: every hash product fits in int64 (|h| <= 2^31 * 1274126177 <
# 2^63), so Python's arbitrary-precision ints and numpy's int64 agree exactly.

def _hash01_s(ix: int, iz: int, seed: int) -> float:
    h = (ix * 374761393 + iz * 668265263 + seed * 982451653) & 0x7FFFFFFF
    h = (h ^ (h >> 13)) * 1274126177 & 0x7FFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFFFF) / 16777216.0


def _value_noise_s(x: float, z: float, cell: float, seed: int) -> float:
    gx = x / cell
    gz = z / cell
    ix = math.floor(gx)
    iz = math.floor(gz)
    fx = gx - ix
    fz = gz - iz
    wx = fx * fx * (3.0 - 2.0 * fx)
    wz = fz * fz * (3.0 - 2.0 * fz)
    n00 = _hash01_s(ix, iz, seed)
    n10 = _hash01_s(ix + 1, iz, seed)
    n01 = _hash01_s(ix, iz + 1, seed)
    n11 = _hash01_s(ix + 1, iz + 1, seed)
    nx0 = n00 + (n10 - n00) * wx
    nx1 = n01 + (n11 - n01) * wx
    return nx0 + (nx1 - nx0) * wz


def _fbm_s(x: float, z: float, cell: float, octaves: int, seed: int) -> float:
    total = 0.0
    amp = 1.0
    amp_sum = 0.0
    c = float(cell)
    for i in range(octaves):
        total = total + amp * _value_noise_s(x, z, c, seed + i * 101)
        amp_sum += amp
        amp *= 0.5
        c /= 2.0
    return total / amp_sum


def _continent_s(x: float, z: float, signed_dist: float,
                 height_seed: int) -> float:
    r = signed_dist / _COAST_RAMP
    r = min(max(r, _SHELF_RAMP), 1.0)            # == np.clip order
    return r * (55.0 + 90.0 * _fbm_s(x, z, 8_000.0, 4, height_seed))


# Conservative skip bounds: a coast wiggles by at most _COAST_WIGGLE and the
# shelf ramp clamps _COAST_RAMP * |_SHELF_RAMP| past the coast line.
_HOME_SKIP_Z = _COAST_WIGGLE - _SHELF_RAMP * _COAST_RAMP            # 14_500
_ENEMY_SKIP_Z = ENEMY_COAST_Z - _COAST_WIGGLE + _SHELF_RAMP * _COAST_RAMP


def terrain_height_scalar(x: float, z: float) -> float:
    """Scalar terrain_height: bit-identical, ~300x faster for single points."""
    x = float(x)
    z = float(z)
    h = -1.0e30
    if z < _HOME_SKIP_Z:                          # home shelf not fully clamped
        home_coast = _COAST_WIGGLE * _fbm_s(x, 0.0, 30_000.0, 4, SEED + 1)
        h = _continent_s(x, z, home_coast - z, SEED + 2)
    if z > _ENEMY_SKIP_Z:                         # enemy shelf not fully clamped
        enemy_coast = ENEMY_COAST_Z - _COAST_WIGGLE * _fbm_s(
            x, 0.0, 30_000.0, 4, SEED + 3)
        e = _continent_s(x, z, z - enemy_coast, SEED + 4)
        if e > h:
            h = e
    for k, (cx, cz, radius, peak) in enumerate(ISLANDS):
        dx = x - cx
        dz = z - cz
        m = 1.0 - math.sqrt(dx * dx + dz * dz) / radius
        if m > 0.0:                               # inside: noise-lifted peak
            t = m if m < 1.0 else 1.0             # smoothstep01 (m > 0 here)
            s = t * t * (3.0 - 2.0 * t)
            h_isl = s ** 1.5 * (peak * (0.4 + 0.6 * _fbm_s(
                x, z, radius * 0.35, 4, SEED + 5 + 17 * k)))
        else:                                     # outside: plain skirt slope
            h_isl = m * _ISLAND_SHORE_SLOPE
        if h_isl > h:
            h = h_isl
    if h < -60.0:                                 # floor can win only here
        floor = -60.0 - 80.0 * _fbm_s(x, z, 20_000.0, 3, SEED + 6)
        if floor > h:
            h = floor
    return h


LANES = [  # 4 polylines (x, z) float64 crossing the ocean, dodging ISLANDS by >= 12 km
    # Lane 0: western route, home waters to enemy coast
    [(-220_000.0, 15_000.0), (-190_000.0, 150_000.0), (-210_000.0, 320_000.0), (-180_000.0, 480_000.0)],
    # Lane 1: central route threading between the island groups
    [(5_000.0, 10_000.0), (0.0, 180_000.0), (-15_000.0, 270_000.0), (10_000.0, 360_000.0), (0.0, 480_000.0)],
    # Lane 2: eastern route
    [(200_000.0, 12_000.0), (180_000.0, 200_000.0), (200_000.0, 300_000.0), (170_000.0, 470_000.0)],
    # Lane 3: east-west transit lane across mid-ocean
    [(-340_000.0, 205_000.0), (0.0, 198_000.0), (340_000.0, 205_000.0)],
]

SITES = [  # land targets: {id, kind, pos(x,z), name}
    {"id": "radar_alpha", "kind": "radar", "pos": (52_000 + 2_500, 140_000 - 3_000), "name": "RADAR STN ALPHA"},
    {"id": "depot_bravo", "kind": "depot", "pos": (140_000 - 4_000, 260_000 + 2_000), "name": "FUEL DEPOT BRAVO"},
    {"id": "harbor_kilo", "kind": "harbor", "pos": (30_000, 502_000), "name": "HARBOR KILO"},
]

# Player base: on home land near the coast, on the cliff top.
_BASE_X, _BASE_Z = 0.0, -600.0
BASE_POS = (_BASE_X, float(terrain_height(np.array([_BASE_X]), np.array([_BASE_Z]))[0]), _BASE_Z)

SHIP_SPAWNS = [  # 14 ships distributed over the lanes
    {"ship_type": "cargo",   "lane_index": 0, "lane_t0": 0.10, "speed": 8.0},
    {"ship_type": "tanker",  "lane_index": 0, "lane_t0": 0.35, "speed": 6.5},
    {"ship_type": "warship", "lane_index": 0, "lane_t0": 0.60, "speed": 13.0},
    {"ship_type": "cargo",   "lane_index": 0, "lane_t0": 0.85, "speed": 8.5},
    {"ship_type": "tanker",  "lane_index": 1, "lane_t0": 0.05, "speed": 6.0},
    {"ship_type": "cargo",   "lane_index": 1, "lane_t0": 0.30, "speed": 7.5},
    {"ship_type": "warship", "lane_index": 1, "lane_t0": 0.55, "speed": 14.0},
    {"ship_type": "cargo",   "lane_index": 1, "lane_t0": 0.80, "speed": 8.0},
    {"ship_type": "tanker",  "lane_index": 2, "lane_t0": 0.15, "speed": 7.0},
    {"ship_type": "warship", "lane_index": 2, "lane_t0": 0.45, "speed": 12.5},
    {"ship_type": "cargo",   "lane_index": 2, "lane_t0": 0.75, "speed": 9.0},
    {"ship_type": "cargo",   "lane_index": 3, "lane_t0": 0.20, "speed": 8.0},
    {"ship_type": "tanker",  "lane_index": 3, "lane_t0": 0.50, "speed": 6.5},
    {"ship_type": "warship", "lane_index": 3, "lane_t0": 0.80, "speed": 13.5},
]
