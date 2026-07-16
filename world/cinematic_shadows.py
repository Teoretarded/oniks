"""Pre-baked terrain shadow masks for the cinematic light moods (GL-free).

The cinematic sun is a handful of FIXED directions (one per light mood),
so terrain self-shadowing — the Jungfrau wall actually darkening the
valley at golden hour (user report 2026-07-16: 'the mountains don't give
shadows') — can be baked once per mood instead of paying for a runtime
shadow map.  The bake is a classic heightfield shadow sweep: processing
grid lines away from the sun, each cell inherits the running shadow
height of its sun-side neighbour (lowered by the sun slope) and is
shadowed by however far that line still clears its own ground.  O(N)
per mood, a couple of hundred ms for a 16 x 16 km scene.

Masks cache to ``shadow_<mood>.npz`` in the scene dir, keyed on the sun
direction and grid geometry, so every later visit is a disk read.

GL-free by design (unit-tested headless); ``world/cinematic_terrain.py``
uploads the mask as an R8 texture and the terrain/tree shaders multiply
their sun term by it.
"""

from __future__ import annotations

import os

import numpy as np

SOFT_M = 7.0          # m below the shadow line for FULL shadow (penumbra)
MAX_RES = 2048        # widest mask axis (16 km scene -> ~8 m cells)


def _bilinear(grid: np.ndarray, gx: np.ndarray, gz: np.ndarray):
    """Vectorized bilinear sample of ``grid`` at fractional indices."""
    nz, nx = grid.shape
    gx = np.clip(gx, 0.0, nx - 1.001)
    gz = np.clip(gz, 0.0, nz - 1.001)
    i0 = gx.astype(np.int64)
    j0 = gz.astype(np.int64)
    fx = (gx - i0).astype(np.float32)
    fz = (gz - j0).astype(np.float32)
    g = grid
    return ((g[j0, i0] * (1 - fx) + g[j0, i0 + 1] * fx) * (1 - fz)
            + (g[j0 + 1, i0] * (1 - fx) + g[j0 + 1, i0 + 1] * fx) * fz)


def compose_height_field(scene, max_res: int = MAX_RES):
    """One height grid over the scene's widest extent (surround included).

    Returns ``(field float32 (nz, nx) row 0 = south, x0, z0, cell)``.
    Core cells come from the 1 m LiDAR bare earth, the ring from the
    coarse surround mosaic; NaN holes sink far below ground so they can
    never cast."""
    x0, x1 = scene.ext_x0, scene.ext_x1
    z0, z1 = scene.ext_z0, scene.ext_z1
    cell = max((max(x1 - x0, z1 - z0)) / max_res, 2.0)
    nx = int(round((x1 - x0) / cell)) + 1
    nz = int(round((z1 - z0) / cell)) + 1
    xs = x0 + np.arange(nx, dtype=np.float64) * cell
    zs = z0 + np.arange(nz, dtype=np.float64) * cell
    xg, zg = np.meshgrid(xs, zs)
    sur = getattr(scene, "_sur", None)
    if sur is not None:
        field = _bilinear(sur, (xg - scene._sur_x0) / scene._sur_cell,
                          (zg - scene._sur_z0) / scene._sur_cell)
    else:
        field = np.full((nz, nx), -1e4, dtype=np.float32)
    core = ((xg >= scene.x0) & (xg <= scene.x1)
            & (zg >= scene.z0) & (zg <= scene.z1))
    if core.any():
        field[core] = _bilinear(scene._dtm,
                                (xg[core] - scene.x0) / scene._cell,
                                (zg[core] - scene.z0) / scene._cell)
    field = np.asarray(field, dtype=np.float32)
    field[~np.isfinite(field)] = -1e4
    return field, float(x0), float(z0), float(cell)


def _shift_frac(a: np.ndarray, o: float) -> np.ndarray:
    """Sample 1-D ``a`` at fractional index offset +o; outside -> -inf
    (no terrain casts in from beyond the field).  An integer offset only
    needs j0 in range — requiring j1 too silently killed the last lateral
    line under axis-aligned sun (GPT-5.6 review 2026-07-16)."""
    n = len(a)
    idx = np.arange(n, dtype=np.float64) + o
    j0 = np.floor(idx).astype(np.int64)
    f = (idx - j0).astype(np.float32)
    j1 = j0 + 1
    valid = (j0 >= 0) & ((j1 <= n - 1) | ((f <= 1e-6) & (j0 <= n - 1)))
    j0c = np.clip(j0, 0, n - 1)
    j1c = np.clip(j1, 0, n - 1)
    out = a[j0c] * (1.0 - f) + a[j1c] * f
    out[~valid] = -np.inf
    return out


def bake_shadow_mask(field: np.ndarray, cell: float, sun_dir,
                     soft_m: float = SOFT_M) -> np.ndarray:
    """uint8 shadow amount per cell (0 = lit, 255 = fully shadowed).

    ``sun_dir`` points TOWARD the sun (renderer convention).  The sweep
    walks the grid away from the sun along the dominant horizontal axis;
    the running shadow height drops by the sun slope each step and picks
    up every ridge it crosses."""
    d = np.asarray(sun_dir, dtype=np.float64)
    d = d / np.linalg.norm(d)
    if d[1] <= 0.005:                    # sun below the horizon: all dark
        return np.full(field.shape, 255, dtype=np.uint8)
    h_mag = float(np.hypot(d[0], d[2]))
    if h_mag < 1e-6:                     # zenith: nothing casts
        return np.zeros(field.shape, dtype=np.uint8)
    f = np.asarray(field, dtype=np.float32)
    nz, nx = f.shape
    out = np.zeros((nz, nx), dtype=np.float32)
    inv_soft = 1.0 / max(soft_m, 1e-3)
    if abs(d[0]) >= abs(d[2]):
        # Sweep along x, away from the sun; blocker is one column sunward,
        # laterally offset by the ray's z drift per x cell.
        step = -1 if d[0] > 0 else 1     # propagation direction (indices)
        o = d[2] / abs(d[0])             # z drift per column, in cells
        drop = np.float32(d[1] / abs(d[0]) * cell)
        order = range(nx - 2, -1, -1) if step == -1 else range(1, nx)
        S = f[:, nx - 1 if step == -1 else 0].copy()
        for i in order:
            s_prop = _shift_frac(S, o) - drop
            col = f[:, i]
            np.clip((s_prop - col) * inv_soft, 0.0, 1.0, out=out[:, i])
            S = np.maximum(col, s_prop)
    else:
        step = -1 if d[2] > 0 else 1
        o = d[0] / abs(d[2])             # x drift per row, in cells
        drop = np.float32(d[1] / abs(d[2]) * cell)
        order = range(nz - 2, -1, -1) if step == -1 else range(1, nz)
        S = f[nz - 1 if step == -1 else 0, :].copy()
        for j in order:
            s_prop = _shift_frac(S, o) - drop
            row = f[j, :]
            np.clip((s_prop - row) * inv_soft, 0.0, 1.0, out=out[j, :])
            S = np.maximum(row, s_prop)
    # One 3x3 box pass: melts single-cell stair-stepping off ridgelines.
    p = np.pad(out, 1, mode="edge")
    out = (p[:-2, :-2] + p[:-2, 1:-1] + p[:-2, 2:]
           + p[1:-1, :-2] + p[1:-1, 1:-1] + p[1:-1, 2:]
           + p[2:, :-2] + p[2:, 1:-1] + p[2:, 2:]) / 9.0
    return np.round(out * 255.0).astype(np.uint8)


def shadow_rect(field_shape, x0: float, z0: float, cell: float) -> tuple:
    """(x0, z0, 1/width, 1/height) uniform for the terrain shader: maps
    world xz onto the mask's [0, 1]^2 (mask row 0 = south = v 0).

    Offset by half a cell so a grid POST lands on its texel CENTER under
    GL_LINEAR — edge-mapping shifted every shadow by ~half a mask cell
    (GPT-5.6 review 2026-07-16)."""
    nz, nx = field_shape
    return (x0 - 0.5 * cell, z0 - 0.5 * cell,
            1.0 / (nx * cell), 1.0 / (nz * cell))


def _terrain_fingerprint(scene) -> np.ndarray:
    """Small stable signature of the scene geometry the mask depends on:
    extent + a strided checksum of the core DTM — a rebaked scene must
    invalidate its cached shadows (GPT-5.6 review 2026-07-16)."""
    core = np.asarray(scene._dtm[::64, ::64], dtype=np.float64)
    return np.array([scene.ext_x0, scene.ext_x1, scene.ext_z0,
                     scene.ext_z1, float(core.sum()),
                     float(core.max()), core.shape[0] * 1e6
                     + core.shape[1]], dtype=np.float64)


def bake_mood_mask(scene, mood_id: str, sun_dir,
                   cache: bool = True):
    """Bake (or load the cached) mask for one light mood.

    Returns ``(mask uint8 (nz, nx), rect)``."""
    d = np.round(np.asarray(sun_dir, dtype=np.float64)
                 / np.linalg.norm(sun_dir), 5)
    fp = _terrain_fingerprint(scene)
    path = os.path.join(scene.dir, f"shadow_{mood_id}.npz")
    if cache and os.path.isfile(path):
        try:
            with np.load(path) as z:
                if (np.array_equal(z["sun_dir"], d)
                        and int(z["max_res"]) == MAX_RES
                        and np.allclose(z["fingerprint"], fp)):
                    mask = z["mask"]
                    rect = tuple(float(v) for v in z["rect"])
                    return mask, rect
        except (OSError, ValueError, KeyError):
            pass
    field, x0, z0, cell = compose_height_field(scene)
    mask = bake_shadow_mask(field, cell, d)
    rect = shadow_rect(field.shape, x0, z0, cell)
    if cache:
        tmp = f"{path}.{os.getpid()}.tmp"
        try:
            with open(tmp, "wb") as fh:      # atomic: temp + replace
                np.savez_compressed(fh, mask=mask, sun_dir=d,
                                    rect=np.asarray(rect,
                                                    dtype=np.float64),
                                    max_res=MAX_RES, fingerprint=fp)
            os.replace(tmp, path)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass                      # read-only dir: bake per session
    return mask, rect
