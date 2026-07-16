"""Baked real-world cinematic scenes: manifest + samplers (GL-free).

A scene is a directory under ``assets/cinematic/<name>/`` produced by
``tools/bake_cinematic_map.py`` from open-license geodata (swisstopo LiDAR,
USGS 3DEP).  This module is the GL-free half: it loads the manifest and the
physics rasters and answers height/obstacle queries for the walker and unit
tests.  ``world/cinematic_terrain.py`` owns the GL half (tile meshes and
textures) and reads the same manifest.

Local coordinates are the engine's LOCKED axes: X east, Z north, Y up,
meters, with the scene origin (``origin_e/n/alt`` in the manifest) mapping
projected easting/northing/altitude into a small local frame.

Baked layout (all files relative to the scene dir):
- ``scene.json``      manifest: origin, bounds, tile table, spawn, credits
- ``dtm_1m.npy``      float32 (nz, nx) bare-earth heights, row 0 = south
- ``obstacle.npy``    uint8 (nz, nx), 1 = impassable (LiDAR surface rises
                      more than a ledge above bare earth: trees, buildings)
- per-tile ``*_hgt.npz``: dsm_1m/2m/4m/20m height grids and matched
  clutter_* grids (surface rise above bare earth), all WITH a 1-cell
  halo; plus ``*_tex.jpg`` / ``*_mid.jpg`` orthophoto textures
"""

from __future__ import annotations

import json
import os

import numpy as np

SCENES_ROOT = os.path.join("assets", "cinematic")


class SceneTile:
    """One render tile record (core km tile or coarse surround chunk) —
    meshes live GL-side."""

    __slots__ = ("x0", "z0", "size", "hgt_path", "tex_path", "mid_path")

    def __init__(self, scene_dir: str, rec: dict):
        self.x0 = float(rec["x0"])
        self.z0 = float(rec["z0"])
        self.size = float(rec["size"])
        self.hgt_path = os.path.join(scene_dir, rec["hgt"])
        self.tex_path = os.path.join(scene_dir, rec["tex"])
        self.mid_path = (os.path.join(scene_dir, rec["mid"])
                         if "mid" in rec else None)


class CinematicScene:
    """A loaded scene: manifest fields + physics samplers."""

    def __init__(self, scene_dir: str):
        self.dir = scene_dir
        with open(os.path.join(scene_dir, "scene.json"), encoding="utf-8") as f:
            self.meta = json.load(f)
        m = self.meta
        self.name = m["name"]
        self.title = m["title"]
        self.subtitle = m.get("subtitle", "")
        self.attribution = m.get("attribution", "")
        self.x0, self.x1 = float(m["x0"]), float(m["x1"])
        self.z0, self.z1 = float(m["z0"]), float(m["z1"])
        self.origin_alt = float(m["origin_alt"])
        self.spawn = m["spawn"]
        self.s300 = m.get("s300")
        self.tiles = [SceneTile(scene_dir, rec) for rec in m["tiles"]]
        self.surround = [SceneTile(scene_dir, rec)
                         for rec in m.get("surround", [])]

        dtm = m["dtm"]
        self._cell = float(dtm["cell"])
        self._dtm = np.load(os.path.join(scene_dir, dtm["file"]))
        self._obstacle = np.load(os.path.join(scene_dir,
                                              m["obstacle"]["file"]))
        self._nz, self._nx = self._dtm.shape
        self._load_surround_field(scene_dir)

    def _load_surround_field(self, scene_dir: str) -> None:
        """Assemble the coarse surround chunks into ONE walkable height
        mosaic so the world doesn't end at the LiDAR core ('NO GROUND
        THERE', user report 2026-07-16).  The physics field is built from
        the SAME grids the renderer meshes, so boots and pixels agree.
        Missing chunks stay NaN — not ground."""
        self.ext_x0, self.ext_x1 = self.x0, self.x1
        self.ext_z0, self.ext_z1 = self.z0, self.z1
        self._sur = None
        if not self.surround:
            return
        x0 = min(t.x0 for t in self.surround)
        z0 = min(t.z0 for t in self.surround)
        x1 = max(t.x0 + t.size for t in self.surround)
        z1 = max(t.z0 + t.size for t in self.surround)
        size = self.surround[0].size
        with np.load(self.surround[0].hgt_path) as z:
            n_in = z["h"].shape[0] - 2          # interior posts per chunk
        cell = size / (n_in - 1)
        nx = int(round((x1 - x0) / cell)) + 1
        nz = int(round((z1 - z0) / cell)) + 1
        field = np.full((nz, nx), np.nan, dtype=np.float32)
        for t in self.surround:
            with np.load(t.hgt_path) as zf:
                inner = zf["h"][1:-1, 1:-1]
            ix = int(round((t.x0 - x0) / cell))
            iz = int(round((t.z0 - z0) / cell))
            field[iz:iz + n_in, ix:ix + n_in] = inner
        self._sur = field
        self._sur_cell = cell
        self._sur_x0, self._sur_z0 = x0, z0
        self.ext_x0, self.ext_x1 = x0, x1
        self.ext_z0, self.ext_z1 = z0, z1

    # ---------------------------------------------------------- samplers

    # Core->surround transition band (m): inside the core but this close
    # to its border, heights blend toward the coarse field so the seam is
    # walkable instead of a bare 32 m-vs-1 m data cliff.
    BLEND_BAND_M = 48.0

    def _core_h(self, x: float, z: float) -> float:
        gx = (x - self.x0) / self._cell
        gz = (z - self.z0) / self._cell
        gx = min(max(gx, 0.0), self._nx - 1.001)
        gz = min(max(gz, 0.0), self._nz - 1.001)
        i0, j0 = int(gx), int(gz)
        fx, fz = gx - i0, gz - j0
        d = self._dtm
        h00 = float(d[j0, i0]);     h10 = float(d[j0, i0 + 1])
        h01 = float(d[j0 + 1, i0]); h11 = float(d[j0 + 1, i0 + 1])
        return ((h00 * (1 - fx) + h10 * fx) * (1 - fz)
                + (h01 * (1 - fx) + h11 * fx) * fz)

    def _surround_h(self, x: float, z: float) -> float:
        """Bilinear on the coarse mosaic; NaN when off-field/hole."""
        s = self._sur
        gx = (x - self._sur_x0) / self._sur_cell
        gz = (z - self._sur_z0) / self._sur_cell
        gx = min(max(gx, 0.0), s.shape[1] - 1.001)
        gz = min(max(gz, 0.0), s.shape[0] - 1.001)
        i0, j0 = int(gx), int(gz)
        fx, fz = gx - i0, gz - j0
        h00 = float(s[j0, i0]);     h10 = float(s[j0, i0 + 1])
        h01 = float(s[j0 + 1, i0]); h11 = float(s[j0 + 1, i0 + 1])
        return ((h00 * (1 - fx) + h10 * fx) * (1 - fz)
                + (h01 * (1 - fx) + h11 * fx) * fz)

    def ground_h(self, x: float, z: float) -> float:
        """Walkable height at (x, z): 1 m LiDAR bare earth inside the
        core, the coarse surround field beyond it, blended across the
        core border so the seam never forms a phantom cliff."""
        inside = (self.x0 <= x <= self.x1 and self.z0 <= z <= self.z1)
        if self._sur is None:
            return self._core_h(x, z)
        if inside:
            edge = min(x - self.x0, self.x1 - x,
                       z - self.z0, self.z1 - z)
            if edge >= self.BLEND_BAND_M:
                return self._core_h(x, z)
            s = self._surround_h(x, z)
            if not np.isfinite(s):
                return self._core_h(x, z)
            w = edge / self.BLEND_BAND_M
            return self._core_h(x, z) * w + s * (1.0 - w)
        return self._surround_h(x, z)

    def blocked(self, x: float, z: float) -> bool:
        """True where the LiDAR surface is a wall (tree/building cell in
        the core) or off every height field — the walkable world now ends
        at the SURROUND data, not at the fine core."""
        gx = (x - self.x0) / self._cell
        gz = (z - self.z0) / self._cell
        if (0.0 <= gx < self._nx - 1 and 0.0 <= gz < self._nz - 1):
            return bool(self._obstacle[int(gz + 0.5), int(gx + 0.5)])
        if self._sur is None:
            return True
        if not (self.ext_x0 <= x <= self.ext_x1
                and self.ext_z0 <= z <= self.ext_z1):
            return True
        return not np.isfinite(self._surround_h(x, z))

    # ------------------------------------------------------------ spawn

    def spawn_pos_yaw(self):
        s = self.spawn
        return (float(s["x"]), float(s["z"])), float(
            np.radians(s.get("yaw_deg", 0.0)))


def build_tile_arrays(h: np.ndarray, cell: float, size: float,
                      skirt_drop: float, clutter: np.ndarray | None = None):
    """Textured-tile geometry from a haloed height grid (GL-free).

    ``h`` is (n+2, n+2) float32 with a 1-cell halo, row 0 = south; the
    interior n x n vertices span tile-local x/z in [0, size].  Returns
    ``(verts (N, 9) float32 [px py pz nx ny nz u v clutter], indices
    uint32)``.  ``clutter`` (same shape as ``h``) is the LiDAR surface's
    rise above bare earth — the shader uses it to keep procedural cliff
    rock off trees and roofs; omitted it bakes as 0 (bare ground).

    UV convention: the baked orthophoto JPEGs keep the source raster's
    row 0 = NORTH, and GL samples v=0 at the first uploaded row, so
    v = 1 - z/size.  A perimeter skirt (edge ring dropped by
    ``skirt_drop``) hides cracks where neighbouring tiles draw at a
    different LOD; skirt winding keeps right-hand-rule normals pointing
    outward so backface culling never opens the seam.
    """
    h = np.asarray(h, dtype=np.float32)
    n = h.shape[0] - 2
    xs = (np.arange(n, dtype=np.float64) * cell).astype(np.float32)
    inner = h[1:-1, 1:-1]
    dhdx = (h[1:-1, 2:] - h[1:-1, :-2]) / np.float32(2.0 * cell)
    dhdz = (h[2:, 1:-1] - h[:-2, 1:-1]) / np.float32(2.0 * cell)
    inv = 1.0 / np.sqrt(dhdx * dhdx + dhdz * dhdz + 1.0)

    verts = np.empty((n * n, 9), dtype=np.float32)
    verts[:, 0] = np.broadcast_to(xs[None, :], (n, n)).ravel()
    verts[:, 1] = inner.ravel()
    verts[:, 2] = np.broadcast_to(xs[:, None], (n, n)).ravel()
    verts[:, 3] = (-dhdx * inv).ravel()
    verts[:, 4] = inv.ravel()
    verts[:, 5] = (-dhdz * inv).ravel()
    u = (xs / np.float32(size))
    verts[:, 6] = np.broadcast_to(u[None, :], (n, n)).ravel()
    verts[:, 7] = np.broadcast_to((1.0 - u)[:, None], (n, n)).ravel()
    if clutter is None:
        verts[:, 8] = 0.0
    else:
        verts[:, 8] = np.asarray(clutter,
                                 dtype=np.float32)[1:-1, 1:-1].ravel()

    grid = np.arange(n * n, dtype=np.uint32).reshape(n, n)
    v00 = grid[:-1, :-1].ravel()
    v10 = grid[:-1, 1:].ravel()
    v01 = grid[1:, :-1].ravel()
    v11 = grid[1:, 1:].ravel()
    indices = [np.stack((v00, v11, v10, v00, v01, v11), axis=1).ravel()]

    # Perimeter skirt: duplicate each edge ring dropped by skirt_drop.
    pieces = [verts]
    base = n * n

    def _skirt(edge_idx: np.ndarray, flip: bool):
        nonlocal base
        ring = verts[edge_idx].copy()
        ring[:, 1] -= np.float32(skirt_drop)
        pieces.append(ring)
        m = len(edge_idx)
        top = edge_idx.astype(np.uint32)
        bot = (base + np.arange(m, dtype=np.uint32))
        t0, t1 = top[:-1], top[1:]
        b0, b1 = bot[:-1], bot[1:]
        if flip:
            quads = np.stack((t0, b0, t1, t1, b0, b1), axis=1)
        else:
            quads = np.stack((t0, t1, b0, t1, b1, b0), axis=1)
        indices.append(quads.ravel())
        base += m

    _skirt(grid[0, :], flip=False)        # south edge, outward -Z
    _skirt(grid[-1, :], flip=True)        # north edge, outward +Z
    _skirt(grid[:, 0], flip=True)         # west edge,  outward -X
    _skirt(grid[:, -1], flip=False)       # east edge,  outward +X

    return (np.concatenate(pieces, axis=0),
            np.concatenate(indices).astype(np.uint32))


SKIRT_MARGIN = 3.0         # m beyond the measured cross-LOD edge delta


def _edge_ring(grid: np.ndarray) -> np.ndarray:
    """Concatenated interior-edge values of a haloed grid (S, N, W, E)."""
    inner = grid[1:-1, 1:-1]
    return np.concatenate((inner[0, :], inner[-1, :],
                           inner[:, 0], inner[:, -1]))


def skirt_drops(h2: np.ndarray, h4: np.ndarray, h20: np.ndarray) -> tuple:
    """Per-LOD skirt depths from measured cross-LOD edge deltas (GL-free).

    Shared tile edges are bit-identical at equal LOD (one mosaic,
    corner-aligned samples), so the gap a tile can open against a
    coarser/finer neighbour equals the delta between its OWN grids along
    that edge.  A tile's skirt must reach down by how far its edge can
    sit ABOVE the other LOD's surface; fixed 2/8/40 m skirts left holes
    of up to 64 m on cliff tiles (GPT-5.6 review 2026-07-16)."""
    e2 = _edge_ring(h2)
    e4 = _edge_ring(h4)
    e20 = _edge_ring(h20)
    e2_at4 = e2.reshape(4, -1)[:, ::2].ravel()      # 2 m ring at 4 m posts
    e4_at20 = e4.reshape(4, -1)[:, ::5].ravel()     # 4 m ring at 20 m posts
    e2_at20 = e2.reshape(4, -1)[:, ::10].ravel()
    d2 = max(0.0, float((e2_at4 - e4).max()), float((e2_at20 - e20).max()))
    d4 = max(0.0, float((e4 - e2_at4).max()), float((e4_at20 - e20).max()))
    d20 = max(0.0, float((e20 - e2_at20).max()),
              float((e20 - e4_at20).max()))
    return (d2 + SKIRT_MARGIN, d4 + SKIRT_MARGIN, d20 + SKIRT_MARGIN)


def list_scenes(root: str = SCENES_ROOT) -> list:
    """[(name, title, subtitle, dir)] for every baked scene on disk."""
    out = []
    if not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root)):
        manifest = os.path.join(root, name, "scene.json")
        if os.path.isfile(manifest):
            try:
                with open(manifest, encoding="utf-8") as f:
                    meta = json.load(f)
            except (OSError, ValueError):
                continue
            out.append((name, meta.get("title", name.upper()),
                        meta.get("subtitle", ""), os.path.join(root, name)))
    return out
