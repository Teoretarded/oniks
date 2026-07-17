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
        # Expansion rings (tools/bake_cinematic_ring.py): same chunk
        # schema at coarser cells — 64 km of 2 m-source alps (surround2)
        # and the ~160 km GLO-30 horizon (surround3).
        self.surround2 = [SceneTile(scene_dir, rec)
                          for rec in m.get("surround2", [])]
        self.surround3 = [SceneTile(scene_dir, rec)
                          for rec in m.get("surround3", [])]

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
        self._sur_x1, self._sur_z1 = x1, z1
        self.ext_x0, self.ext_x1 = x0, x1
        self.ext_z0, self.ext_z1 = z0, z1
        # Far rings: fine-to-coarse physics mosaics; the walkable world
        # (and the ICBM target designator) now ends at the LAST ring.
        self._far = []
        for tiles in (self.surround2, self.surround3):
            fld = self._build_ring_field(tiles)
            if fld is not None:
                self._far.append(fld)
                self.ext_x0 = min(self.ext_x0, fld[2])
                self.ext_z0 = min(self.ext_z0, fld[3])
                self.ext_x1 = max(self.ext_x1, fld[4])
                self.ext_z1 = max(self.ext_z1, fld[5])

    def _build_ring_field(self, tiles):
        """(field, cell, x0, z0, x1, z1) mosaic for one uniform ring."""
        if not tiles:
            return None
        x0 = min(t.x0 for t in tiles)
        z0 = min(t.z0 for t in tiles)
        x1 = max(t.x0 + t.size for t in tiles)
        z1 = max(t.z0 + t.size for t in tiles)
        size = tiles[0].size
        with np.load(tiles[0].hgt_path) as z:
            n_in = z["h"].shape[0] - 2
        cell = size / (n_in - 1)
        nx = int(round((x1 - x0) / cell)) + 1
        nz = int(round((z1 - z0) / cell)) + 1
        field = np.full((nz, nx), np.nan, dtype=np.float32)
        for t in tiles:
            with np.load(t.hgt_path) as zf:
                inner = zf["h"][1:-1, 1:-1]
            ix = int(round((t.x0 - x0) / cell))
            iz = int(round((t.z0 - z0) / cell))
            field[iz:iz + n_in, ix:ix + n_in] = inner
        return (field, cell, x0, z0, x1, z1)

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

    def _far_h(self, x: float, z: float) -> float:
        """Fine-to-coarse expansion rings; NaN when off every ring."""
        for field, cell, fx0, fz0, fx1, fz1 in getattr(self, "_far", []):
            if not (fx0 <= x <= fx1 and fz0 <= z <= fz1):
                continue
            gx = min(max((x - fx0) / cell, 0.0), field.shape[1] - 1.001)
            gz = min(max((z - fz0) / cell, 0.0), field.shape[0] - 1.001)
            i0, j0 = int(gx), int(gz)
            fxw, fzw = gx - i0, gz - j0
            h00 = float(field[j0, i0]);     h10 = float(field[j0, i0 + 1])
            h01 = float(field[j0 + 1, i0]); h11 = float(field[j0 + 1, i0 + 1])
            h = ((h00 * (1 - fxw) + h10 * fxw) * (1 - fzw)
                 + (h01 * (1 - fxw) + h11 * fxw) * fzw)
            if np.isfinite(h):
                return h
        return float("nan")

    def ground_h(self, x: float, z: float) -> float:
        """Walkable height at (x, z): 1 m LiDAR bare earth inside the
        core, the coarse surround field beyond it, then the expansion
        rings — blended across the core border so the seam never forms
        a phantom cliff."""
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
        if (self._sur_x0 <= x <= self._sur_x1
                and self._sur_z0 <= z <= self._sur_z1):
            s = self._surround_h(x, z)
            if np.isfinite(s):
                return s
        return self._far_h(x, z)

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
        return not np.isfinite(self.ground_h(x, z))

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


# ---------------------------------------------------------------- silo survey

def _winmax(a: np.ndarray, r: int) -> np.ndarray:
    """Dense (2r+1)-window maximum via shifted maxima (small r only)."""
    out = a.copy()
    n0, n1 = a.shape
    for dj in range(-r, r + 1):
        j0, j1 = max(dj, 0), min(n0 + dj, n0)
        s0, s1 = max(-dj, 0), min(n0 - dj, n0)
        for di in range(-r, r + 1):
            i0, i1 = max(di, 0), min(n1 + di, n1)
            t0, t1 = max(-di, 0), min(n1 - di, n1)
            np.maximum(out[s0:s1, t0:t1], a[j0:j1, i0:i1],
                       out=out[s0:s1, t0:t1])
    return out


def survey_silo_candidates(dtm: np.ndarray, obstacle: np.ndarray,
                           cell: float, x0: float, z0: float,
                           spawn_xz, avoid_xz=None,
                           dist_range=(1200.0, 3200.0),
                           box_m: float = 36.0, relief_max: float = 2.5,
                           band_lo: float = -40.0, band_hi: float = 140.0,
                           prefer_dist: float = 1800.0):
    """Ranked silo sites from the core grids (pure arrays, zero RNG).

    A silo compound wants a ~36 m flat, obstacle-free pad on the valley
    floor: local relief under ``relief_max`` over the box, no LiDAR
    obstacle cells, ``dist_range`` metres from the spawn (visible but
    not in your lap), height within [band_lo, band_hi] of the spawn
    (never up a wall / down a gorge), and away from ``avoid_xz`` (the
    S-300 pad).  Returns [(score, x, z)] sorted best-first; the caller
    validates finalists at full resolution (obstacles + line of sight).
    """
    step = max(1, int(round(8.0 / cell)))
    d = dtm[::step, ::step].astype(np.float32)
    ob = (obstacle[::step, ::step] > 0)
    csz = cell * step
    r = max(1, int(round(box_m * 0.5 / csz)))
    hi = _winmax(d, r)
    lo = -_winmax(-d, r)
    relief = hi - lo
    obs_any = _winmax(ob.astype(np.float32), r) > 0.0

    nz, nx = d.shape
    xs = x0 + np.arange(nx, dtype=np.float64) * csz
    zs = z0 + np.arange(nz, dtype=np.float64) * csz
    gx, gz = np.meshgrid(xs, zs)
    sx, sz = float(spawn_xz[0]), float(spawn_xz[1])
    dist = np.hypot(gx - sx, gz - sz)
    # Spawn height from the decimated grid (nearest cell is plenty).
    si = int(np.clip(round((sx - x0) / csz), 0, nx - 1))
    sj = int(np.clip(round((sz - z0) / csz), 0, nz - 1))
    dh = d - float(d[sj, si])

    ok = ((relief <= relief_max) & (~obs_any)
          & (dist >= dist_range[0]) & (dist <= dist_range[1])
          & (dh >= band_lo) & (dh <= band_hi))
    if avoid_xz is not None:
        ok &= (np.hypot(gx - float(avoid_xz[0]),
                        gz - float(avoid_xz[1])) >= 250.0)
    # Keep the box fully inside the core.
    m = r + 1
    ok[:m, :] = ok[-m:, :] = False
    ok[:, :m] = ok[:, -m:] = False
    if not ok.any():
        # Fallback pass: drop the distance window, keep it flat + clear.
        ok = (relief <= relief_max) & (~obs_any) & (dist >= 400.0)
        ok[:m, :] = ok[-m:, :] = False
        ok[:, :m] = ok[:, -m:] = False
        if not ok.any():
            return []
    score = relief + np.abs(dist - prefer_dist) * 0.002
    j, i = np.nonzero(ok)
    order = np.argsort(score[j, i], kind="stable")
    return [(float(score[j[k], i[k]]), float(xs[i[k]]), float(zs[j[k]]))
            for k in order[:400]]


def survey_silo_site(scene, eye_h: float = 1.7) -> tuple:
    """Pick THE silo site for a scene: best-ranked candidate that also
    passes full-resolution obstacle checks over the compound box and a
    bare-earth line-of-sight from the spawn (the whole mode is
    WATCHING — same rule the S-300 pad bake uses).  Deterministic."""
    (sx, sz), _yaw = scene.spawn_pos_yaw()
    avoid = None
    if scene.s300 is not None:
        avoid = (float(scene.s300["x"]), float(scene.s300["z"]))
    cands = survey_silo_candidates(scene._dtm, scene._obstacle,
                                   scene._cell, scene.x0, scene.z0,
                                   (sx, sz), avoid_xz=avoid)
    eye = np.array([sx, scene.ground_h(sx, sz) + eye_h, sz])
    best_fallback = None
    for _score, cx, cz in cands:
        if best_fallback is None:
            best_fallback = (cx, cz)
        # Full-res obstacle check across the compound box.
        clear = True
        for dx in (-16.0, 0.0, 16.0):
            for dz in (-16.0, 0.0, 16.0):
                if scene.blocked(cx + dx, cz + dz):
                    clear = False
                    break
            if not clear:
                break
        if not clear:
            continue
        # Terrain LOS: spawn eye to a point above the tube mouth.
        tgt = np.array([cx, scene.ground_h(cx, cz) + 4.0, cz])
        seen = True
        for f in np.linspace(0.06, 0.97, 48):
            p = eye + (tgt - eye) * f
            if scene.ground_h(float(p[0]), float(p[2])) > p[1] + 0.5:
                seen = False
                break
        if seen:
            return (cx, cz)
    return best_fallback if best_fallback is not None else (sx + 400.0, sz)
