"""Per-feature LOD terrain: static meshes sampled from the heightfield.

Geometry is pure numpy (unit tests import this module, so no GL imports at
module level — the ``Terrain`` class defers them to ``__init__``).

Implementation note (vs the naive "build all features x LODs at load"):
sampling ``terrain_height`` at 60 m over every feature is ~28M points
(minutes of load time, ~1 GB of VBOs), so large features are split into
~26 km tiles and the LODs stream in:

- LOD2 (1200 m) for every land tile is built at load — cheap, and every
  tile is always drawable.
- LOD1 (300 m) tiles are built lazily (one tile per frame) as the camera
  comes within range; their height grids are kept.
- LOD0 (60 m) is derived in milliseconds by Catmull-Rom upsampling the
  stored LOD1 grid instead of re-sampling ``terrain_height`` (whose finest
  noise wavelength is ~400 m, so 300 m samples already capture nearly all
  real detail). Built LOD0 meshes are cached with farthest-tile eviction.

Tile meshes are uploaded relative to their tile center and drawn at the
float64 center position (camera-relative, LOCKED convention: no jitter).
"""

from __future__ import annotations

import numpy as np

from engine.meshdata import MeshData, make_grid
from world.generation import ISLANDS, terrain_height

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

# Vertex colors by height/slope
_SAND = (0.62, 0.56, 0.42)
_GRASS = (0.35, 0.40, 0.26)
_ROCK = (0.46, 0.42, 0.38)
_HIGH_ROCK = (0.52, 0.50, 0.48)


def _sample_heights(rect, cell: float, margin: int = 0):
    """Sample terrain_height on a regular grid covering ``rect`` (+ optional
    ``margin`` extra rows/cols each side). Returns (xs, zs, heights)."""
    x0, x1, z0, z1 = rect
    nx = max(1, int(round((x1 - x0) / cell)))
    nz = max(1, int(round((z1 - z0) / cell)))
    xs = x0 + np.arange(-margin, nx + margin + 1, dtype=np.float64) * ((x1 - x0) / nx)
    zs = z0 + np.arange(-margin, nz + margin + 1, dtype=np.float64) * ((z1 - z0) / nz)
    return xs, zs, terrain_height(xs[None, :], zs[:, None])


def _mesh_from_heights(xs, zs, heights, h_ref=None) -> MeshData:
    """Clamp, colorize by height/slope, and grid-mesh a sampled heightfield.

    ``h_ref`` is the reference peak height for the high-rock band (pass the
    feature-wide max so tile colors don't seam); defaults to the local max.
    """
    h = np.maximum(heights, -4.0)             # hide the seabed under the ocean
    dhdz, dhdx = np.gradient(h, zs, xs)
    slope = np.hypot(dhdx, dhdz)
    hmax = float(h.max()) if h_ref is None else float(h_ref)
    colors = np.empty(h.shape + (3,), dtype=np.float32)
    colors[:] = _GRASS
    colors[h < 6.0] = _SAND
    colors[slope > 0.5] = _ROCK
    colors[h > 0.6 * hmax] = _HIGH_ROCK
    return make_grid(xs, zs, h, colors)


def build_feature_mesh(rect, cell: float, h_ref=None) -> MeshData | None:
    """Terrain mesh for ``rect`` at ``cell`` resolution; None if all ocean."""
    xs, zs, h = _sample_heights(rect, cell)
    if float(h.max()) <= 0.0:
        return None                            # rect entirely ocean: skip
    return _mesh_from_heights(xs, zs, h, h_ref)


_CR_CACHE: dict[tuple[int, int], np.ndarray] = {}


def _catmull_rom_weights(n_cells: int, factor: int) -> np.ndarray:
    """(n_cells*factor+1, n_cells+3) interpolation matrix mapping a coarse
    sample row (with a 1-sample margin each side) to factor-x fine samples."""
    key = (n_cells, factor)
    w = _CR_CACHE.get(key)
    if w is None:
        n_out = n_cells * factor + 1
        k = np.arange(n_out)
        j = np.minimum(k // factor, n_cells - 1)   # coarse cell index
        t = k / factor - j
        t2, t3 = t * t, t * t * t
        w = np.zeros((n_out, n_cells + 3))
        w[k, j] = -0.5 * t3 + t2 - 0.5 * t
        w[k, j + 1] = 1.5 * t3 - 2.5 * t2 + 1.0
        w[k, j + 2] = -1.5 * t3 + 2.0 * t2 + 0.5 * t
        w[k, j + 3] = 0.5 * t3 - 0.5 * t2
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
        self.h1 = None                     # LOD1 heights incl. 1-cell margin


class Terrain:
    """GL wrapper: tiles the features, streams LOD meshes, draws by distance."""

    def __init__(self, report: bool = True):
        from engine.mesh import Mesh       # deferred: keep module GL-free
        self._Mesh = Mesh
        self.tiles: list[_Tile] = []
        self._lod0_live: list[_Tile] = []
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
                    xs, zs, h = _sample_heights(rect, LODS[2][0])
                    if float(h.max()) > 0.0:
                        sampled.append((rect, xs, zs, h))
            if not sampled:
                continue
            h_ref = max(float(h.max()) for _r, _x, _z, h in sampled)
            for rect, xs, zs, h in sampled:
                tile = _Tile(rect, h_ref)
                md = _mesh_from_heights(xs, zs, h, h_ref)
                tile.meshes[2] = self._upload(md, tile)
                total_verts += len(md.vertices)
                self.tiles.append(tile)
        if report:
            print(f"[terrain] {len(self.tiles)} land tiles, "
                  f"{total_verts:,} LOD2 vertices (LOD0/LOD1 stream in)")

    def _upload(self, md: MeshData, tile: _Tile):
        """Re-center vertices on the tile origin and upload (LOCKED: GPU
        float32 is camera/tile-relative; the float64 center is applied at
        draw time via the camera-relative model matrix)."""
        md.vertices[:, 0] -= np.float32(tile.center[0])
        md.vertices[:, 2] -= np.float32(tile.center[2])
        return self._Mesh(md)

    def _build_lod1(self, tile: _Tile) -> None:
        xs, zs, h = _sample_heights(tile.rect, LODS[1][0], margin=1)
        tile.nx, tile.nz = len(xs) - 3, len(zs) - 3   # interior cell counts
        tile.h1 = h
        md = _mesh_from_heights(xs[1:-1], zs[1:-1], h[1:-1, 1:-1], tile.h_ref)
        tile.meshes[1] = self._upload(md, tile)

    def _build_lod0(self, tile: _Tile) -> None:
        wx = _catmull_rom_weights(tile.nx, _LOD0_FACTOR)
        wz = _catmull_rom_weights(tile.nz, _LOD0_FACTOR)
        h_fine = wz @ tile.h1 @ wx.T
        x0, x1, z0, z1 = tile.rect
        xs = np.linspace(x0, x1, tile.nx * _LOD0_FACTOR + 1)
        zs = np.linspace(z0, z1, tile.nz * _LOD0_FACTOR + 1)
        md = _mesh_from_heights(xs, zs, h_fine, tile.h_ref)
        tile.meshes[0] = self._upload(md, tile)
        self._lod0_live.append(tile)

    def _evict_lod0(self, camera) -> None:
        while len(self._lod0_live) > _LOD0_CACHE_MAX:
            far = max(self._lod0_live,
                      key=lambda t: float(np.linalg.norm(camera.rel(t.center))))
            far.meshes[0].delete()
            far.meshes[0] = None
            self._lod0_live.remove(far)

    def draw(self, renderer) -> None:
        cam = renderer.camera
        budget = 1                          # lazy mesh builds per frame
        for tile in self.tiles:
            rel = cam.rel(tile.center)
            if float(np.dot(rel, cam.forward)) < -tile.radius:
                continue                    # entirely behind the camera
            dist = float(np.linalg.norm(rel))
            lod = next(k for k, (_c, mx) in enumerate(LODS) if dist <= mx)
            if budget > 0 and lod <= 1 and tile.meshes[1] is None:
                self._build_lod1(tile)
                budget -= 1
            if budget > 0 and lod == 0 and tile.meshes[0] is None \
                    and tile.h1 is not None:
                self._build_lod0(tile)
                self._evict_lod0(cam)
                budget -= 1
            while tile.meshes[lod] is None:  # fall back while streaming
                lod += 1
            renderer.draw_mesh(tile.meshes[lod], tile.center)
