"""Volumetric clouds (F3-P4; spec: weather_system_design_2026-07-07.md
PART 2 §12 + the locked F3 conventions).

TWO HALVES, one module:

* The BAKE half (this top section) is pure NumPy — importable by unit
  tests and, in W-P6, by ``sim/atmosphere.py`` (the CPU/GPU single-source
  contract: the density the sim queries IS the density the GPU draws).
  Seeded ``default_rng([seed, 17])`` (tag 17 — the F3-reserved stream).
  Every field is PERIODIC so the GPU textures REPEAT seamlessly.

* The GL half (``Clouds``) defers every GL import to ``__init__``
  (sky.py pattern; never imported by unit tests): uploads the baked
  textures, draws one fullscreen raymarch pass LAST into the default
  framebuffer — depth TEST on (terrain/ships occlude clouds via the
  slab-entry log depth), depth WRITE off, premultiplied blend,
  ``apply_haze`` on the result.  Animation clock = SIM time (replays
  identical), never wall clock.

Determinism guard (LOCKED): no sim module imports this file
(tests/test_cloud_bake.py greps for offenders).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

# --- bake constants -------------------------------------------------------------
BASE_N = 128          # base Perlin-Worley texture, voxels per axis
DETAIL_N = 32         # detail Worley texture
WEATHER_N = 512       # weathermap texels per axis
CACHE_VERSION = "v1"  # bump when the bake recipe changes (invalidates caches)

# World-space scales (metres) — consumed by the shader AND (W-P6) the CPU
# density query, so they live here as the single source of truth.
CLOUD_BASE_M = 300.0        # slab bottom
CLOUD_TOP_M = 14_000.0      # slab top (supercell ceiling)
WEATHER_TILE_M = 300_000.0  # weathermap repeat period
BASE_TILE_M = 6_000.0       # base-noise repeat period
DETAIL_TILE_M = 1_200.0     # detail-noise repeat period


# --- periodic value noise (vectorized, float32) ---------------------------------

def _fade(t):
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def _perlin_grid(rng, freq: int, dims: int) -> np.ndarray:
    """Periodic unit-gradient lattice, (freq,)*dims + (dims,) float32."""
    g = rng.standard_normal((freq,) * dims + (dims,)).astype(np.float32)
    g /= np.linalg.norm(g, axis=-1, keepdims=True) + 1e-9
    return g


def _perlin3(rng, n: int, freq: int) -> np.ndarray:
    """Periodic 3D Perlin, (n, n, n) float32 roughly in [-1, 1].  Fully
    vectorized: 8 corner gathers of (n,n,n,3) float32 (~25 MB each at
    128³, transient) — the slice-looped version measured 15+ s, this is
    sub-second."""
    g = _perlin_grid(rng, freq, 3)
    c = np.arange(n, dtype=np.float32) * (freq / n)
    i0 = c.astype(np.int64) % freq
    i1 = (i0 + 1) % freq
    f = (c - np.floor(c)).astype(np.float32)
    u = _fade(f)
    ax = (slice(None), None, None)
    ay = (None, slice(None), None)
    az = (None, None, slice(None))
    acc = None
    for xi, wx, dx in ((i0, 1.0 - u, f), (i1, u, f - 1.0)):
        for yi, wy, dy in ((i0, 1.0 - u, f), (i1, u, f - 1.0)):
            for zi, wz, dz in ((i0, 1.0 - u, f), (i1, u, f - 1.0)):
                gv = g[xi[:, None, None], yi[None, :, None],
                       zi[None, None, :]]              # (n, n, n, 3)
                d = (gv[..., 0] * dx[ax] + gv[..., 1] * dy[ay]
                     + gv[..., 2] * dz[az])
                w = wx[ax] * wy[ay] * wz[az]
                acc = d * w if acc is None else acc + d * w
    return acc


def _perlin2(rng, n: int, freq: int) -> np.ndarray:
    """Periodic 2D Perlin, (n, n) float32 roughly in [-1, 1]."""
    g = _perlin_grid(rng, freq, 2)
    c = np.arange(n, dtype=np.float32) * (freq / n)
    i0 = c.astype(np.int64) % freq
    i1 = (i0 + 1) % freq
    f = (c - np.floor(c)).astype(np.float32)
    u = _fade(f)
    acc = np.zeros((n, n), dtype=np.float32)
    for xi, wx, dx in ((i0, 1.0 - u[:, None], f[:, None]),
                       (i1, u[:, None], f[:, None] - 1.0)):
        for yi, wy, dy in ((i0, 1.0 - u[None, :], f[None, :]),
                           (i1, u[None, :], f[None, :] - 1.0)):
            gv = g[xi[:, None], yi[None, :]]               # (n, n, 2)
            acc += (gv[..., 0] * dx + gv[..., 1] * dy) * (wx * wy)
    return acc


def _fbm(noise_fn, rng, n: int, freq0: int, octaves: int) -> np.ndarray:
    """Normalized fbm in [0, 1]."""
    total = None
    amp, freq, norm = 1.0, freq0, 0.0
    for _ in range(octaves):
        layer = noise_fn(rng, n, freq) * amp
        total = layer if total is None else total + layer
        norm += amp
        amp *= 0.5
        freq *= 2
    total /= norm
    return np.clip(total * 0.5 + 0.5, 0.0, 1.0).astype(np.float32)


def _worley(rng, n: int, cells: int, dims: int) -> np.ndarray:
    """Periodic inverted Worley in [0, 1] (1 at feature points, 0 far),
    (n,)*dims float32.  Block-wise: the volume reshapes into per-cell
    blocks so each of the 3^dims neighbor offsets is ONE broadcast over
    (cells^dims, block^dims) with a tiny per-CELL feature gather — the
    per-pixel-gather version measured ~7 s per 128³ octave; this is
    sub-second."""
    assert n % cells == 0
    bs = n // cells
    pts = rng.random((cells,) * dims + (dims,)).astype(np.float32)
    pts_flat = pts.reshape(-1, dims)                      # (C, dims)
    # Block-local pixel coords in CELL units, shared by every cell:
    local_1d = (np.arange(bs, dtype=np.float32) + 0.5) / bs   # (bs,)
    local = np.stack(np.meshgrid(*([local_1d] * dims), indexing="ij"),
                     axis=-1).reshape(1, -1, dims)        # (1, bs^d, dims)
    cell_idx_1d = np.arange(cells)
    cell_grid = np.stack(np.meshgrid(*([cell_idx_1d] * dims),
                                     indexing="ij"),
                         axis=-1).reshape(-1, dims)       # (C, dims)
    best = np.full((cells ** dims, bs ** dims), np.inf, dtype=np.float32)
    offsets = np.stack(np.meshgrid(*([(-1, 0, 1)] * dims),
                                   indexing="ij"), -1).reshape(-1, dims)
    strides = np.array([cells ** (dims - 1 - d) for d in range(dims)])
    for off in offsets:
        nb = (cell_grid + off) % cells                    # (C, dims)
        nb_flat = nb @ strides                            # (C,)
        # Feature point position RELATIVE to each cell's own origin:
        p_rel = (pts_flat[nb_flat] + off).astype(np.float32)[:, None, :]
        delta = local - p_rel                             # (C, bs^d, dims)
        d2 = np.einsum("cpd,cpd->cp", delta, delta)
        np.minimum(best, d2, out=best)
    # Un-blockify: (cells, cells, cells, bs, bs, bs) -> interleaved axes.
    vol = best.reshape((cells,) * dims + (bs,) * dims)
    order = []
    for d in range(dims):
        order += [d, dims + d]
    dist = np.sqrt(vol.transpose(order).reshape((n,) * dims))
    dist /= np.sqrt(dims)                                 # ~[0, 1]
    return np.clip(1.0 - dist * 1.6, 0.0, 1.0).astype(np.float32)


def _remap(x, a, b, c, d):
    return c + (x - a) / np.maximum(b - a, 1e-6) * (d - c)


# --- the bake --------------------------------------------------------------------

def build_noise(seed: int, cache_dir=Path("cache")) -> dict:
    """The three cloud fields, seeded ``default_rng([seed, 17])`` (tag 17):

    * ``base``    (128³): Perlin-Worley — fbm Perlin remapped by Worley
      billows (Schneider/Nubis recipe) — the cloud SHAPES.
    * ``detail``  (32³): Worley — edge erosion.
    * ``weather`` (512²×3): R coverage / G type / B top-height fraction —
      WHERE clouds are and WHAT KIND (PART 2 §12; v1 bakes the FAIR/PARTLY
      mix, preset knobs arrive with W-P6).  All periodic.

    ``cache_dir`` None disables the disk cache (tests); otherwise
    ``cache/clouds_v1_seed{seed}.npz`` makes the bake one-time per seed.
    """
    cache = None
    if cache_dir is not None:
        cache = Path(cache_dir) / f"clouds_{CACHE_VERSION}_seed{seed}.npz"
        if cache.exists():
            z = np.load(cache)
            return {"base": z["base"], "detail": z["detail"],
                    "weather": z["weather"]}

    rng = np.random.default_rng([int(seed), 17])

    # Base: fbm Perlin carved by Worley billows.  The raw fbm sits in a
    # compressed ~[0.3, 0.7] band — stretch to full range first so the
    # shader's coverage threshold has real contrast to bite on.
    perlin = _fbm(_perlin3, rng, BASE_N, 4, 3)
    perlin = np.clip(_remap(perlin, 0.30, 0.70, 0.0, 1.0), 0.0, 1.0)
    worley = (_worley(rng, BASE_N, 4, 3) * 0.625
              + _worley(rng, BASE_N, 8, 3) * 0.25
              + _worley(rng, BASE_N, 16, 3) * 0.125)
    base = np.clip(_remap(perlin, worley - 1.0, 1.0, 0.0, 1.0),
                   0.0, 1.0).astype(np.float32)

    # Detail: three Worley octaves, erodes cloud edges in the shader.
    detail = (_worley(rng, DETAIL_N, 2, 3) * 0.5
              + _worley(rng, DETAIL_N, 4, 3) * 0.3
              + _worley(rng, DETAIL_N, 8, 3) * 0.2).astype(np.float32)

    # Weathermap: coverage / type / top-height (FAIR/PARTLY default mix).
    cov_n = _fbm(_perlin2, rng, WEATHER_N, 5, 4)
    # Threshold shaping: honest gaps AND honest clouds (test contract) —
    # roughly 35-55% coverage with soft edges.
    coverage = np.clip(_remap(cov_n, 0.45, 0.75, 0.0, 1.0), 0.0, 1.0)
    type_n = _fbm(_perlin2, rng, WEATHER_N, 3, 2)      # low-freq type bands
    top_n = _fbm(_perlin2, rng, WEATHER_N, 4, 3)
    # Type channel (PART 2 §12): mostly fair cumulus, patches of towering
    # where the type noise runs hot; stratus/supercell/cirrus arrive with
    # the W-P6 preset knobs.
    ctype = np.clip(_remap(type_n, 0.30, 0.80, 0.25, 0.55), 0.0, 1.0)
    top = np.clip(0.15 + 0.5 * top_n * ctype / 0.55, 0.0, 1.0)
    weather = np.stack([coverage, ctype, top], axis=-1).astype(np.float32)

    out = {"base": base, "detail": detail, "weather": weather}
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache, **out)
    return out
