"""Per-feature LOD terrain: static meshes sampled from the heightfield.

Geometry is pure numpy (unit tests import this module, so no GL imports at
module level — the ``Terrain`` class defers them to ``__init__``).

Implementation note (vs the naive "build all features x LODs at load"):
sampling ``terrain_height`` at 60 m over every feature is ~28M points
(minutes of load time, ~1 GB of VBOs), so large features are split into
~26 km tiles and the LODs stream in:

- LOD2 (1200 m) for every land tile is built at load — cheap, and every
  tile is always drawable.
- LOD1 (300 m) and LOD0 (60 m) meshes are built incrementally as the
  camera comes within range: a full build costs ~50 ms (3 dropped frames),
  so each build is a generator that does one small slice of work — a few
  heightfield rows, one gradient pass, one vertex band — per step, and
  ``draw`` runs steps only until a ~5 ms per-frame budget is spent. (A
  worker thread was tried first: PyOpenGL releases the GIL around every
  GL call, and re-acquiring behind a numpy-busy worker convoyed frames to
  35-75 ms, far worse than budgeted main-thread slices.) Until a tile's
  finer mesh is ready, the next coarser LOD draws in its place.
- LOD0 heights come from Catmull-Rom upsampling the stored LOD1 grid
  instead of re-sampling ``terrain_height`` (whose finest noise wavelength
  is ~400 m, so 300 m samples already capture nearly all real detail).
  Built LOD0 meshes are cached with farthest-tile eviction.

Tiles are sampled with a halo so normals and slope colors use central
differences across tile edges (no lighting seams), and vertices are
re-centered on the tile origin in float64 BEFORE the float32 cast (LOCKED
precision convention); the float64 center is re-applied at draw time via
the camera-relative model matrix — no jitter.
"""

from __future__ import annotations

import math
import time

import numpy as np

from engine.meshdata import MeshData, make_grid
from world.generation import ISLANDS, SEED, fbm, terrain_height

FEATURES = [  # (name, x0, x1, z0, z1) bounding rects
    ("home", -340_000.0, 340_000.0, -40_000.0, 12_000.0),
    ("enemy", -340_000.0, 340_000.0, 488_000.0, 560_000.0),
] + [
    (f"island_{i}", cx - 2.2 * r, cx + 2.2 * r, cz - 2.2 * r, cz + 2.2 * r)
    for i, (cx, cz, r, _peak) in enumerate(ISLANDS)
]

LODS = [(60.0, 30_000.0), (300.0, 130_000.0), (1200.0, 1e12)]  # (cell_m, max_draw_dist)

_TILE = 26_000.0          # max tile edge (m); features split so LOD picks stay local
_LOD0_FACTOR = int(round(LODS[1][0] / LODS[0][0]))  # LOD1 -> LOD0 upsample factor (5)
_LOD0_CACHE_MAX = 16      # max live LOD0 meshes (~6.8 MB of vertices each)
_LOD1_MARGIN = 2          # coarse halo cells: 1 for gradients + 1 for Catmull-Rom
_MAX_PENDING = 6          # build backlog cap: a fast camera shouldn't queue stale tiles
_BUILD_BUDGET_S = 0.004   # per-frame build budget; sized so at most ONE ~5 ms
                          # sampling step runs per frame (terrain_height has a
                          # ~2.6 ms fixed dispatch cost, so steps can't be finer)
_SAMPLE_ROWS = 4          # heightfield rows sampled per build step (~5 ms)
_BAND_ROWS = 64           # fine-grid rows meshed per build step (~2.5 ms)

# Vertex colors (S5 terrain look pass): noise-mottled grass/scrub base,
# slope-blended rock exposure, shoreline sand band, height brightening.
_SAND = (0.62, 0.56, 0.42)
_GRASS = (0.32, 0.38, 0.23)     # lush low grass (mottle low end)
_SCRUB = (0.45, 0.42, 0.26)     # dry scrub patches (mottle high end)
_ROCK = (0.46, 0.42, 0.38)
_HIGH_ROCK = (0.52, 0.50, 0.48)
_MOTTLE_CELL = 1_800.0          # medium-frequency patch wavelength (m)
_MOTTLE_SEED = SEED + 9


def _colorize(xs, zs, h, slope, h_ref: float) -> np.ndarray:
    """(len(zs), len(xs), 3) float32 vertex colors. A pure elementwise
    function of world position + local height/slope, so abutting tiles get
    bit-identical colors at shared vertices (seam test) regardless of tile
    rect. ``h_ref`` is the feature-wide peak height (keeps the high-rock
    band and brightening from seaming between tiles)."""
    grass, scrub = np.array(_GRASS), np.array(_SCRUB)
    rock, high_rock, sand = (np.array(_ROCK), np.array(_HIGH_ROCK),
                             np.array(_SAND))
    # noise-driven grass/scrub mottling, contrast-stretched around fbm's mean
    m = fbm(xs[None, :], zs[:, None], _MOTTLE_CELL, 3, _MOTTLE_SEED)
    m = np.clip((m - 0.34) / 0.32, 0.0, 1.0)[..., None]
    colors = grass + (scrub - grass) * m
    # slope-driven rock exposure: blends in from 0.09, fully rock by 0.24
    # (the coastal cliff band tops out at slope ~0.23 -> a rock face, while
    # rolling inland noise at ~0.04 and island shoulders stay vegetated)
    t = np.clip((slope - 0.09) / 0.15, 0.0, 1.0)[..., None]
    colors += (rock - colors) * t
    # high-altitude rock cap, blended over the feature's top fifth only
    # (lower start values grey out whole coastal plateaus — the pre-S5 band
    # began at 0.6 * h_ref and washed the SAM-site hilltop concrete-grey)
    c = np.clip((h - 0.80 * h_ref) / (0.15 * h_ref), 0.0, 1.0)[..., None]
    colors += (high_rock - colors) * c
    # shoreline sand band fading out over h in [3, 7] m
    s = np.clip((h - 3.0) / 4.0, 0.0, 1.0)[..., None]
    colors = sand + (colors - sand) * s
    # subtle height-based brightening so relief reads from altitude
    colors *= (0.88 + 0.20 * np.clip(h / max(h_ref, 1.0), 0.0, 1.0))[..., None]
    return colors.astype(np.float32)


def _grid_coords(rect, cell: float, margin: int = 0):
    """Regular grid coordinates covering ``rect`` (+ ``margin`` extra rows/
    cols each side). Returns (xs, zs) float64."""
    x0, x1, z0, z1 = rect
    nx = max(1, int(round((x1 - x0) / cell)))
    nz = max(1, int(round((z1 - z0) / cell)))
    xs = x0 + np.arange(-margin, nx + margin + 1, dtype=np.float64) * ((x1 - x0) / nx)
    zs = z0 + np.arange(-margin, nz + margin + 1, dtype=np.float64) * ((z1 - z0) / nz)
    return xs, zs


def _sample_heights(rect, cell: float, margin: int = 0):
    """Sample terrain_height on a regular grid covering ``rect`` (+ optional
    ``margin`` extra rows/cols each side). Returns (xs, zs, heights)."""
    xs, zs = _grid_coords(rect, cell, margin)
    return xs, zs, terrain_height(xs[None, :], zs[:, None])


def _grid_mesh_steps(xs, zs, h, colors, dhdx, dhdz, center):
    """Generator: assemble interior-grid MeshData in ``_BAND_ROWS`` row bands
    (yields None between bands, finally yields the MeshData). All inputs are
    already interior-trimmed; positions are re-centered on ``center`` in
    float64 before the float32 cast. Triangle order matches ``make_grid``."""
    cx, cz = (0.0, 0.0) if center is None else center
    w, hgt = len(xs), len(zs)
    xs32 = (xs - cx).astype(np.float32)
    zs32 = (zs - cz).astype(np.float32)
    v = np.empty((hgt * w, 9), dtype=np.float32)
    for r0 in range(0, hgt, _BAND_ROWS):
        r1 = min(r0 + _BAND_ROWS, hgt)
        vb = v[r0 * w:r1 * w].reshape(r1 - r0, w, 9)
        gx, gz = dhdx[r0:r1], dhdz[r0:r1]
        inv = 1.0 / np.sqrt(gx * gx + 1.0 + gz * gz)
        vb[:, :, 0] = xs32[None, :]
        vb[:, :, 1] = h[r0:r1]
        vb[:, :, 2] = zs32[r0:r1, None]
        vb[:, :, 3] = -gx * inv
        vb[:, :, 4] = inv
        vb[:, :, 5] = -gz * inv
        vb[:, :, 6:9] = colors[r0:r1]
        yield None
    idx = np.empty((hgt - 1) * (w - 1) * 6, dtype=np.uint32)
    cols = np.arange(w - 1, dtype=np.uint32)
    for r0 in range(0, hgt - 1, _BAND_ROWS):
        r1 = min(r0 + _BAND_ROWS, hgt - 1)
        base = (np.arange(r0, r1, dtype=np.uint32)[:, None] * np.uint32(w)
                + cols[None, :])
        v00, v10 = base, base + np.uint32(1)
        v01 = base + np.uint32(w)
        v11 = v01 + np.uint32(1)
        block = np.stack((v00, v11, v10, v00, v01, v11), axis=2)
        idx[r0 * (w - 1) * 6:r1 * (w - 1) * 6] = block.ravel()
        yield None
    yield MeshData(v, idx)


def _mesh_steps(xs, zs, heights, h_ref: float, margin: int, center):
    """Generator: clamp, colorize by height/slope, and grid-mesh a sampled
    heightfield in sub-frame-budget steps; finally yields the MeshData.

    Requires ``margin`` >= 1: the halo rows/cols feed central-difference
    normals and slope colors (so abutting tiles agree exactly along shared
    edges) and are trimmed from the emitted mesh. ``h_ref`` is the
    reference peak height for the high-rock band (pass the feature-wide
    max so tile colors don't seam)."""
    m = margin
    big_h, big_w = heights.shape
    h = np.maximum(heights, -4.0)              # hide the seabed under the ocean
    yield None
    si, sj = slice(m, big_h - m), slice(m, big_w - m)
    span_x = xs[m + 1:big_w - m + 1] - xs[m - 1:big_w - m - 1]
    dhdx = (h[si, m + 1:big_w - m + 1] - h[si, m - 1:big_w - m - 1]) / span_x[None, :]
    yield None
    span_z = zs[m + 1:big_h - m + 1] - zs[m - 1:big_h - m - 1]
    dhdz = (h[m + 1:big_h - m + 1, sj] - h[m - 1:big_h - m - 1, sj]) / span_z[:, None]
    yield None
    hi = h[si, sj]
    slope = np.hypot(dhdx, dhdz)
    yield None
    colors = _colorize(xs[sj], zs[si], hi, slope, float(h_ref))
    yield None
    yield from _grid_mesh_steps(xs[sj], zs[si], hi, colors, dhdx, dhdz, center)


def _mesh_from_heights(xs, zs, heights, h_ref=None, margin: int = 0,
                       center=None) -> MeshData:
    """Synchronous mesh build (load-time / tests). With ``margin`` >= 1 this
    drains ``_mesh_steps`` (the exact streaming code path); the margin-0
    path keeps one-sided edge gradients via ``make_grid``."""
    if margin:
        ref = float(np.maximum(heights, -4.0).max()) if h_ref is None else h_ref
        return next(out for out in _mesh_steps(xs, zs, heights, ref, margin,
                                               center) if out is not None)
    h = np.maximum(heights, -4.0)
    dhdz, dhdx = np.gradient(h, zs, xs)
    slope = np.hypot(dhdx, dhdz)
    hmax = float(h.max()) if h_ref is None else float(h_ref)
    return make_grid(xs, zs, h, _colorize(xs, zs, h, slope, hmax))


def build_feature_mesh(rect, cell: float, h_ref=None) -> MeshData | None:
    """Terrain mesh for ``rect`` at ``cell`` resolution; None if all ocean."""
    xs, zs, h = _sample_heights(rect, cell)
    if float(h.max()) <= 0.0:
        return None                            # rect entirely ocean: skip
    return _mesh_from_heights(xs, zs, h, h_ref)


_CR_CACHE: dict[tuple[int, int], np.ndarray] = {}


def _catmull_rom_weights(n_cells: int, factor: int) -> np.ndarray:
    """(n_cells*factor + 3, n_cells + 5) interpolation matrix mapping a
    coarse sample row (with a 2-sample margin each side) to factor-x fine
    samples covering the interior plus one fine-sample halo each side (the
    halo feeds cross-tile central-difference normals)."""
    key = (n_cells, factor)
    w = _CR_CACHE.get(key)
    if w is None:
        n_out = n_cells * factor + 3
        k = np.arange(n_out)
        pos = (k - 1) / factor                 # fine position in coarse cells
        j = np.floor(pos).astype(np.int64)     # coarse cell index, -1..n_cells
        t = pos - j
        t2, t3 = t * t, t * t * t
        w = np.zeros((n_out, n_cells + 5))     # column i+2 = coarse sample i
        w[k, j + 1] = -0.5 * t3 + t2 - 0.5 * t
        w[k, j + 2] = 1.5 * t3 - 2.5 * t2 + 1.0
        w[k, j + 3] = -1.5 * t3 + 2.0 * t2 + 0.5 * t
        w[k, j + 4] = 0.5 * t3 - 0.5 * t2
        _CR_CACHE[key] = w
    return w


class _Tile:
    __slots__ = ("rect", "center", "radius", "h_ref", "meshes",
                 "nx", "nz", "h1")

    def __init__(self, rect, h_ref: float):
        x0, x1, z0, z1 = rect
        self.rect = rect
        self.center = np.array([(x0 + x1) * 0.5, 0.0, (z0 + z1) * 0.5])
        self.radius = float(np.hypot(x1 - x0, z1 - z0)) * 0.5 + 500.0
        self.h_ref = h_ref
        self.meshes = [None, None, None]   # per-LOD GPU meshes
        self.nx = self.nz = 0              # LOD1 grid cell counts
        self.h1 = None                     # LOD1 heights incl. margin


def _lod1_job(tile: _Tile):
    """Incremental LOD1 build: sample the heightfield a few rows per step,
    then mesh it. Stores the height grid on the tile for the LOD0 upsample;
    the final yield is the MeshData."""
    cell = LODS[1][0]
    xs, zs = _grid_coords(tile.rect, cell, _LOD1_MARGIN)
    h = np.empty((len(zs), len(xs)), dtype=np.float64)
    for r0 in range(0, len(zs), _SAMPLE_ROWS):
        r1 = min(r0 + _SAMPLE_ROWS, len(zs))
        h[r0:r1] = terrain_height(xs[None, :], zs[r0:r1, None])
        yield None
    tile.nx = len(xs) - 1 - 2 * _LOD1_MARGIN   # interior cell counts
    tile.nz = len(zs) - 1 - 2 * _LOD1_MARGIN
    tile.h1 = h
    yield from _mesh_steps(xs, zs, h, tile.h_ref, _LOD1_MARGIN,
                           (tile.center[0], tile.center[2]))


def _lod0_job(tile: _Tile):
    """Incremental LOD0 build: Catmull-Rom upsample of the stored LOD1 grid
    (one matmul step), then banded meshing. The final yield is the MeshData."""
    wx = _catmull_rom_weights(tile.nx, _LOD0_FACTOR)
    wz = _catmull_rom_weights(tile.nz, _LOD0_FACTOR)
    h_fine = wz @ tile.h1 @ wx.T               # interior + 1 fine-sample halo
    yield None
    x0, x1, z0, z1 = tile.rect
    fx = (x1 - x0) / (tile.nx * _LOD0_FACTOR)
    fz = (z1 - z0) / (tile.nz * _LOD0_FACTOR)
    xs = x0 + (np.arange(tile.nx * _LOD0_FACTOR + 3, dtype=np.float64) - 1.0) * fx
    zs = z0 + (np.arange(tile.nz * _LOD0_FACTOR + 3, dtype=np.float64) - 1.0) * fz
    yield from _mesh_steps(xs, zs, h_fine, tile.h_ref, 1,
                           (tile.center[0], tile.center[2]))


class Terrain:
    """GL wrapper: tiles the features, streams LOD meshes, draws by distance.

    LOD1/LOD0 builds run as generators on the main thread; ``draw`` advances
    them only until ``_BUILD_BUDGET_S`` of the frame is spent, so a ~50 ms
    build spreads over ~10-30 frames instead of dropping 3-4 of them.
    """

    def __init__(self, report: bool = True):
        from engine.mesh import Mesh       # deferred: keep module GL-free
        self._Mesh = Mesh
        self.tiles: list[_Tile] = []
        self._lod0_live: list[_Tile] = []
        self._jobs: list[tuple[_Tile, int, object]] = []  # FIFO (tile, lod, gen)
        self._pending: set[tuple[int, int]] = set()       # (tile id, lod)
        total_verts = 0
        for _name, x0, x1, z0, z1 in FEATURES:
            ntx = max(1, int(np.ceil((x1 - x0) / _TILE)))
            ntz = max(1, int(np.ceil((z1 - z0) / _TILE)))
            sx, sz = (x1 - x0) / ntx, (z1 - z0) / ntz
            sampled = []                   # land tiles: (rect, xs, zs, heights)
            for ti in range(ntz):
                for tj in range(ntx):
                    rect = (x0 + tj * sx, x0 + (tj + 1) * sx,
                            z0 + ti * sz, z0 + (ti + 1) * sz)
                    xs, zs, h = _sample_heights(rect, LODS[2][0], margin=1)
                    if float(h[1:-1, 1:-1].max()) > 0.0:
                        sampled.append((rect, xs, zs, h))
            if not sampled:
                continue
            h_ref = max(float(h[1:-1, 1:-1].max()) for _r, _x, _z, h in sampled)
            for rect, xs, zs, h in sampled:
                tile = _Tile(rect, h_ref)
                md = _mesh_from_heights(xs, zs, h, h_ref, margin=1,
                                        center=(tile.center[0], tile.center[2]))
                tile.meshes[2] = self._Mesh(md)
                total_verts += len(md.vertices)
                self.tiles.append(tile)
        if report:
            print(f"[terrain] {len(self.tiles)} land tiles, "
                  f"{total_verts:,} LOD2 vertices (LOD0/LOD1 stream in)")

    def _run_builds(self, camera) -> None:
        """Advance queued build generators until the frame budget is spent;
        upload (GL) each finished mesh as its build completes."""
        deadline = time.perf_counter() + _BUILD_BUDGET_S
        while self._jobs and time.perf_counter() < deadline:
            tile, lod, gen = self._jobs[0]
            out = next(gen)
            if out is None:
                continue
            self._jobs.pop(0)
            self._pending.discard((id(tile), lod))
            tile.meshes[lod] = self._Mesh(out)
            if lod == 0:
                self._lod0_live.append(tile)
                self._evict_lod0(camera)

    def _request(self, tile: _Tile, lod: int) -> None:
        """Queue the missing finer-LOD build. LOD0 waits for the tile's LOD1
        grid; the backlog cap bounds how stale a queued build can get when
        the camera moves fast."""
        if len(self._jobs) >= _MAX_PENDING:
            return
        if lod <= 1 and tile.meshes[1] is None:
            want, job = 1, _lod1_job
        elif lod == 0 and tile.meshes[0] is None and tile.h1 is not None:
            want, job = 0, _lod0_job
        else:
            return
        key = (id(tile), want)
        if key not in self._pending:
            self._pending.add(key)
            self._jobs.append((tile, want, job(tile)))

    def _evict_lod0(self, camera) -> None:
        while len(self._lod0_live) > _LOD0_CACHE_MAX:
            far = max(self._lod0_live,
                      key=lambda t: float(np.linalg.norm(camera.rel(t.center))))
            far.meshes[0].delete()
            far.meshes[0] = None
            self._lod0_live.remove(far)

    def draw(self, renderer) -> None:
        cam = renderer.camera
        self._run_builds(cam)
        # Scalar per-tile math (Task 22 perf: this loop runs over every land
        # tile each frame; numpy temporaries per tile dominated the pass).
        eye = cam.eye
        ex, ey, ez = eye[0], eye[1], eye[2]
        fwd = cam.forward
        fx, fy, fz = fwd[0], fwd[1], fwd[2]
        lod0_max, lod1_max = LODS[0][1], LODS[1][1]
        for tile in self.tiles:
            center = tile.center
            rx = center[0] - ex
            ry = center[1] - ey
            rz = center[2] - ez
            if (rx * fx + ry * fy + rz * fz) < -tile.radius:
                continue                    # entirely behind the camera
            dist = math.sqrt(rx * rx + ry * ry + rz * rz)
            lod = 0 if dist <= lod0_max else 1 if dist <= lod1_max else 2
            self._request(tile, lod)
            meshes = tile.meshes
            while meshes[lod] is None:       # fall back while streaming
                lod += 1
            renderer.draw_mesh(meshes[lod], center)

    def delete(self) -> None:
        """Drop queued builds and free all GPU meshes."""
        self._jobs.clear()
        self._pending.clear()
        for tile in self.tiles:
            for mesh in tile.meshes:
                if mesh is not None:
                    mesh.delete()
            tile.meshes = [None, None, None]
        self.tiles = []
        self._lod0_live = []
