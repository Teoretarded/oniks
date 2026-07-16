"""Bake raw cinematic geodata into runtime scene assets.

Reads the rasters fetched by ``tools/fetch_cinematic_data.py`` from
``data/cinematic_raw/<scene>/`` and writes ``assets/cinematic/<scene>/``
in the layout documented in :mod:`world.cinematic_scene`.

Every resampled grid is bilinear-sampled from ONE scene-wide 0.5 m mosaic
at exact corner-aligned coordinates, so abutting tiles share bit-identical
edge vertices (the same no-seam convention as world/terrain.py).  Heights
are stored float32: float16's 1 m quantization at alpine altitudes bands
normals and stairsteps the walker.

Usage:
    python tools/bake_cinematic_map.py lauterbrunnen
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np
import tifffile
from PIL import Image

Image.MAX_IMAGE_PIXELS = 120_000_000

RAW_ROOT = os.path.join("data", "cinematic_raw")
OUT_ROOT = os.path.join("assets", "cinematic")

TILE_M = 1000.0            # render tile edge (matches the km source tiles)
TEX_PX = 4096              # near orthophoto texture per tile (~25 cm)
MID_PX = 1024              # far orthophoto texture per tile (~1 m)
OBSTACLE_RISE = 2.5        # m of DSM-above-DTM that makes a cell a wall
LEDGE_CLEAR = 0.55         # walkable clutter tolerance (walker STEP_LEDGE)

# Scene authoring: titles, where the player spawns and where the S-300
# battery should stand, in projected coordinates (LV95 / UTM).  The bake
# snaps both onto flat open ground found in the actual data.
SCENE_SPECS = {
    "lauterbrunnen": {
        "title": "LAUTERBRUNNEN",
        "subtitle": "BERNESE OBERLAND, SWITZERLAND - 46.59N 7.91E",
        # Village center from the swisstopo WGS84->LV95 approximation for
        # 46.5936 N 7.9077 E (the first bake trusted a from-memory easting
        # and spawned the player on the west wall, 1 km south).
        # Open meadow at the village's SW edge: clear sightlines down the
        # U-valley (round-3 audit: the village-center spawn put the player
        # in a street canyon of orthophoto-smeared house walls).
        "spawn_en": (2_635_940.0, 1_159_880.0),
        "look_en": (2_635_700.0, 1_158_800.0),    # down the U-valley, south
        "s300_range_m": (1_100.0, 1_700.0),       # dramatic but legible
    },
    "yosemite": {
        "title": "YOSEMITE VALLEY",
        "subtitle": "SIERRA NEVADA, CALIFORNIA - 37.72N 119.64W",
        # El Capitan Meadow (UTM 11N), staring up the 900 m granite face;
        # the battery goes east, up-valley toward the village meadows.
        "spawn_en": (267_637.0, 4_177_855.0),
        "look_en": (269_900.0, 4_178_900.0),
        "s300_range_m": (1_100.0, 1_800.0),
    },
}


def _load_manifest(scene: str) -> dict:
    with open(os.path.join(RAW_ROOT, scene, "manifest.json"),
              encoding="utf-8") as f:
        return json.load(f)


def _mosaic(scene: str, kind: str, e0_km: int, n0_km: int,
            e_tiles: int, n_tiles: int) -> np.ndarray:
    """Scene-wide 0.5 m raster mosaic, row 0 = SOUTH edge (ascending z)."""
    px_per_km = 2000
    out = np.full((n_tiles * px_per_km, e_tiles * px_per_km), np.nan,
                  dtype=np.float32)
    raw_dir = os.path.join(RAW_ROOT, scene)
    for fn in sorted(os.listdir(raw_dir)):
        if not (fn.startswith(kind + "_") and fn.endswith(".tif")):
            continue
        parts = fn[:-4].split("_")
        e_km, n_km = int(parts[1]), int(parts[2])
        if not (e0_km <= e_km < e0_km + e_tiles
                and n0_km <= n_km < n0_km + n_tiles):
            continue          # stale tile from an older scene rect
        a = tifffile.imread(os.path.join(raw_dir, fn))
        if a.shape != (px_per_km, px_per_km):
            raise ValueError(f"{fn}: unexpected shape {a.shape}")
        a = np.flipud(a.astype(np.float32))      # row 0 = north -> south
        j0 = (n_km - n0_km) * px_per_km
        i0 = (e_km - e0_km) * px_per_km
        out[j0:j0 + px_per_km, i0:i0 + px_per_km] = a
    if np.isnan(out).any():
        # LiDAR voids (water, occlusion): fill from the column mean so the
        # mesh never spikes; the affected cells are rare and off-trail.
        col_mean = np.nanmean(out, axis=0)
        out = np.where(np.isnan(out), col_mean[None, :], out)
    return out


def _sample(mosaic: np.ndarray, xs: np.ndarray, zs: np.ndarray,
            cell: float = 0.5) -> np.ndarray:
    """Bilinear sample at local coords (pixel CENTERS at (i+0.5)*cell)."""
    gx = np.clip(xs / cell - 0.5, 0.0, mosaic.shape[1] - 1.001)
    gz = np.clip(zs / cell - 0.5, 0.0, mosaic.shape[0] - 1.001)
    i0 = gx.astype(np.int64)
    j0 = gz.astype(np.int64)
    fx = (gx - i0)[None, :]
    fz = (gz - j0)[:, None]
    m = mosaic
    top = m[j0[:, None], i0[None, :]] * (1 - fx) \
        + m[j0[:, None], i0[None, :] + 1] * fx
    bot = m[j0[:, None] + 1, i0[None, :]] * (1 - fx) \
        + m[j0[:, None] + 1, i0[None, :] + 1] * fx
    return (top * (1 - fz) + bot * fz).astype(np.float32)


def _blur3(a: np.ndarray) -> np.ndarray:
    """One separable [1,2,1]/4 smoothing pass (edges clamped)."""
    p = np.pad(a, 1, mode="edge")
    h = (p[1:-1, :-2] + 2.0 * p[1:-1, 1:-1] + p[1:-1, 2:]) * 0.25
    p = np.pad(h, ((1, 1), (0, 0)), mode="edge")
    return ((p[:-2, :] + 2.0 * p[1:-1, :] + p[2:, :]) * 0.25).astype(
        np.float32)


def _grid(x0: float, x1: float, step: float, halo: float = 0.0) -> np.ndarray:
    n = int(round((x1 - x0) / step))
    h = int(round(halo / step))
    return x0 + np.arange(-h, n + h + 1, dtype=np.float64) * step


def _flat_open_spot(dtm, obstacle, cell, x0, z0, want_xz, radius_m,
                    ring=None, toward=None, floor_band_m=30.0):
    """Snap ``want_xz`` to the flattest open cell within ``radius_m`` (or
    within a (min,max) ``ring`` of it): lowest slope, no obstacles in a
    12 m box, deterministic argmin — no RNG (physics-not-dice house rule).

    Candidates are held to the local valley floor (within ``floor_band_m``
    of the search area's lowest ground) so a flat LEDGE on a cliff wall
    never wins, and ``toward`` (a unit-ish xz direction) restricts a ring
    search to the half-plane down-range of it."""
    gz, gx = dtm.shape
    xs = (np.arange(gx) * cell + x0)
    zs = (np.arange(gz) * cell + z0)
    dx = xs[None, :] - want_xz[0]
    dz = zs[:, None] - want_xz[1]
    dist = np.hypot(dx, dz)
    mask = dist <= radius_m if ring is None else \
        (dist >= ring[0]) & (dist <= ring[1])
    if toward is not None:
        tx, tz = toward
        mask &= (dx * tx + dz * tz) > 0.35 * dist
    if mask.any():
        floor = float(dtm[mask].min())
        mask &= dtm <= floor + floor_band_m
    # local slope magnitude (central differences)
    gy, gxx = np.gradient(dtm.astype(np.float32), cell)
    slope = np.hypot(gy, gxx)
    # obstacle-free 12 m neighborhood via a box sum on the 0/1 mask
    k = max(1, int(6.0 / cell))
    obs = obstacle.astype(np.float32)
    box = np.cumsum(np.cumsum(obs, axis=0), axis=1)
    pad = np.zeros((gz + 1, gx + 1), dtype=np.float32)
    pad[1:, 1:] = box
    j0 = np.clip(np.arange(gz) - k, 0, gz); j1 = np.clip(np.arange(gz) + k + 1, 0, gz)
    i0 = np.clip(np.arange(gx) - k, 0, gx); i1 = np.clip(np.arange(gx) + k + 1, 0, gx)
    area = pad[j1[:, None], i1[None, :]] - pad[j0[:, None], i1[None, :]] \
        - pad[j1[:, None], i0[None, :]] + pad[j0[:, None], i0[None, :]]
    # A light distance cost keeps the pick NEAR the author's point instead
    # of drifting to the flattest scree fan in range (round-4 audit).
    score = slope + (area > 0.0) * 1e3 + (~mask) * 1e6 + dist * 0.002
    j, i = np.unravel_index(int(np.argmin(score)), score.shape)
    return float(xs[i]), float(zs[j]), score


def _clear_los(dtm, cell, x0, z0, a_xz, a_h, b_xz, b_h,
               clearance: float = 1.0) -> bool:
    """True when the straight eye->target ray clears the DSM-free ground
    line (sampled every ~4 m, bare earth + clearance)."""
    ax, az = a_xz
    bx, bz = b_xz
    n = max(2, int(math.hypot(bx - ax, bz - az) / 4.0))
    ts = np.linspace(0.0, 1.0, n + 1)[1:-1]
    for t in ts:
        x = ax + (bx - ax) * t
        z = az + (bz - az) * t
        ray_h = a_h + (b_h - a_h) * t
        gi = int(round((x - x0) / cell))
        gj = int(round((z - z0) / cell))
        gj = min(max(gj, 0), dtm.shape[0] - 1)
        gi = min(max(gi, 0), dtm.shape[1] - 1)
        if float(dtm[gj, gi]) + clearance > ray_h:
            return False
    return True


def _bake_surround(scene, man, out_dir, origin_e, origin_n, origin_alt,
                   cx0, cx1, cz0, cz1, dtm05) -> list:
    """Coarse far-terrain ring: 2 m DTM + ortho -> 32 m chunk meshes.

    Kills the world-ends-here bubble.  Chunk cells INSIDE the core rect
    are tucked 8 m below the fine terrain so the two never z-fight; the
    core's own skirts hide the seam."""
    if "surround_e_km" not in man:
        return []
    se0, se1 = man["surround_e_km"]
    sn0, sn1 = man["surround_n_km"]
    e_tiles = se1 - se0 + 1
    n_tiles = sn1 - sn0 + 1
    raw_dir = os.path.join(RAW_ROOT, scene)
    px_km = 500                              # 2 m pixels per km
    print(f"[{scene}] surround: mosaicking {e_tiles}x{n_tiles} km at 2 m")
    dem = np.full((n_tiles * px_km, e_tiles * px_km), np.nan, np.float32)
    rgb = np.zeros((n_tiles * px_km, e_tiles * px_km, 3), np.uint8)
    for fn in sorted(os.listdir(raw_dir)):
        is_d = fn.startswith("sdtm_")
        is_o = fn.startswith("sortho_")
        if not (is_d or is_o) or not fn.endswith(".tif"):
            continue
        parts = fn[:-4].split("_")
        e_km, n_km = int(parts[1]), int(parts[2])
        if not (se0 <= e_km <= se1 and sn0 <= n_km <= sn1):
            continue
        a = tifffile.imread(os.path.join(raw_dir, fn))
        if a.shape[0] != px_km:
            a = np.asarray(Image.fromarray(
                a if is_o else a.astype(np.float32)).resize(
                    (px_km, px_km),
                    Image.BILINEAR), dtype=a.dtype)
        j0 = (n_km - sn0) * px_km
        i0 = (e_km - se0) * px_km
        if is_d:
            dem[j0:j0 + px_km, i0:i0 + px_km] = \
                np.flipud(a.astype(np.float32)) - origin_alt
        else:
            rgb[j0:j0 + px_km, i0:i0 + px_km] = np.flipud(a)[..., :3]
    # Core hole: fill DEM from the fine mosaic (downsampled), imagery
    # from the already-baked mid textures; heights tucked 8 m down.
    man_e0, _ = man["e_km"]
    man_n0, _ = man["n_km"]
    for n_km in range(man_n0, man["n_km"][1] + 1):
        for e_km in range(man_e0, man["e_km"][1] + 1):
            j0 = (n_km - sn0) * px_km
            i0 = (e_km - se0) * px_km
            cj0 = (n_km - man_n0) * 2000
            ci0 = (e_km - man_e0) * 2000
            block = dtm05[cj0:cj0 + 2000:4, ci0:ci0 + 2000:4]
            dem[j0:j0 + px_km, i0:i0 + px_km] = block - 8.0
            mid = os.path.join(out_dir, f"tile_{e_km}_{n_km}_mid.jpg")
            if os.path.exists(mid):
                img = np.asarray(Image.open(mid).convert("RGB").resize(
                    (px_km, px_km), Image.BILINEAR))
                rgb[j0:j0 + px_km, i0:i0 + px_km] = np.flipud(img)
    if np.isnan(dem).any():
        col = np.nanmean(np.where(np.isnan(dem), np.nan, dem), axis=0)
        col = np.where(np.isnan(col), 0.0, col)
        dem = np.where(np.isnan(dem), col[None, :], dem).astype(np.float32)

    sx0 = se0 * 1000.0 - origin_e            # ring origin, scene-local
    sz0 = sn0 * 1000.0 - origin_n
    chunk_km = 4
    out = []
    for cj in range(n_tiles // chunk_km):
        for ci in range(e_tiles // chunk_km):
            x0c = sx0 + ci * chunk_km * 1000.0
            z0c = sz0 + cj * chunk_km * 1000.0
            # Fully inside the core? The fine tiles already draw it.
            if (x0c >= cx0 and x0c + chunk_km * 1000.0 <= cx1
                    and z0c >= cz0 and z0c + chunk_km * 1000.0 <= cz1):
                continue
            step_px = 16                     # 32 m grid from 2 m pixels
            n_cells = chunk_km * 1000 // 32
            gj0 = cj * chunk_km * px_km
            gi0 = ci * chunk_km * px_km
            grid = np.empty((n_cells + 3, n_cells + 3), np.float32)
            for jj in range(n_cells + 3):
                sj = min(max(gj0 + (jj - 1) * step_px, 0), dem.shape[0] - 1)
                row = dem[sj, max(gi0 - step_px, 0):
                          gi0 + (n_cells + 2) * step_px:step_px]
                row = np.pad(row, (0, max(0, n_cells + 3 - len(row))),
                             mode="edge")
                grid[jj] = row[:n_cells + 3]
            base = f"surround_{ci}_{cj}"
            tex = Image.fromarray(
                np.flipud(rgb[gj0:gj0 + chunk_km * px_km,
                              gi0:gi0 + chunk_km * px_km]))
            tex = tex.resize((1024, 1024), Image.LANCZOS)
            tex.save(os.path.join(out_dir, base + ".jpg"), quality=85)
            np.savez_compressed(os.path.join(out_dir, base + "_hgt.npz"),
                                h=grid)
            out.append({"x0": x0c, "z0": z0c,
                        "size": chunk_km * 1000.0,
                        "hgt": base + "_hgt.npz", "tex": base + ".jpg"})
    print(f"  surround: {len(out)} chunks")
    return out


def bake(scene: str) -> None:
    spec = SCENE_SPECS[scene]
    man = _load_manifest(scene)
    e0_km, e1_km = man["e_km"]
    n0_km, n1_km = man["n_km"]
    e_tiles = e1_km - e0_km + 1
    n_tiles = n1_km - n0_km + 1
    origin_e = (e0_km + e_tiles / 2.0) * 1000.0
    origin_n = (n0_km + n_tiles / 2.0) * 1000.0
    x0, x1 = -e_tiles * 500.0, e_tiles * 500.0
    z0, z1 = -n_tiles * 500.0, n_tiles * 500.0
    out_dir = os.path.join(OUT_ROOT, scene)
    os.makedirs(out_dir, exist_ok=True)

    print(f"[{scene}] mosaicking DTM/DSM at 0.5 m ...")
    dtm05 = _mosaic(scene, "dtm", e0_km, n0_km, e_tiles, n_tiles)
    dsm05 = _mosaic(scene, "dsm", e0_km, n0_km, e_tiles, n_tiles)
    origin_alt = float(np.floor(dtm05.min()))
    dtm05 -= origin_alt
    dsm05 -= origin_alt
    clutter05 = np.maximum(dsm05 - dtm05, 0.0)
    print(f"  origin alt {origin_alt:.0f} m ASL, relief "
          f"{dtm05.min():.0f}..{dtm05.max():.0f} m")

    # Physics rasters at 1 m (corner-aligned local grid).
    xs1 = _grid(0.0, (x1 - x0), 1.0) + 0.0
    zs1 = _grid(0.0, (z1 - z0), 1.0) + 0.0
    dtm1 = _sample(dtm05, xs1, zs1)
    dsm1 = _sample(dsm05, xs1, zs1)
    clutter = dsm1 - dtm1
    obstacle = (clutter > OBSTACLE_RISE).astype(np.uint8)
    np.save(os.path.join(out_dir, "dtm_1m.npy"), dtm1)
    np.save(os.path.join(out_dir, "obstacle.npy"), obstacle)
    print(f"  dtm_1m {dtm1.shape} ({dtm1.nbytes / 1e6:.0f} MB), "
          f"obstacles {100.0 * obstacle.mean():.1f}% of cells")

    # Spawn + S-300 pad, snapped onto real flat open ground.
    sx = spec["spawn_en"][0] - origin_e
    sz = spec["spawn_en"][1] - origin_n
    spawn = _flat_open_spot(dtm1, obstacle, 1.0, x0, z0, (sx, sz),
                            140.0)[:2]
    lx = spec["look_en"][0] - origin_e
    lz = spec["look_en"][1] - origin_n
    look = np.array([lx - spawn[0], lz - spawn[1]])
    look = look / max(np.linalg.norm(look), 1e-9)
    _px, _pz, pad_score = _flat_open_spot(
        dtm1, obstacle, 1.0, x0, z0, spawn, 0.0,
        ring=spec["s300_range_m"], toward=(float(look[0]), float(look[1])))
    # The whole mode is WATCHING the launch: walk the flattest candidates
    # in order and take the first pad the spawn can actually see (eye
    # 1.7 m to canister top ~6 m over bare earth + 1 m clearance).
    spawn_h = float(dtm1[int(round(spawn[1] - z0)),
                         int(round(spawn[0] - x0))])
    order = np.argsort(pad_score.ravel())[:400]
    pad = (_px, _pz)
    for flat_idx in order:
        j, i = np.unravel_index(int(flat_idx), pad_score.shape)
        cand = (float(i + x0), float(j + z0))
        cand_h = float(dtm1[j, i])
        if _clear_los(dsm1, 1.0, x0, z0, spawn, spawn_h + 1.7,
                      cand, cand_h + 6.0):
            pad = cand
            break
    yaw = math.degrees(math.atan2(pad[0] - spawn[0], pad[1] - spawn[1]))
    print(f"  spawn ({spawn[0]:.0f}, {spawn[1]:.0f})  "
          f"s300 pad ({pad[0]:.0f}, {pad[1]:.0f})  "
          f"range {math.hypot(pad[0]-spawn[0], pad[1]-spawn[1]):.0f} m")

    # Per-tile render grids + textures.
    tiles = []
    raw_dir = os.path.join(RAW_ROOT, scene)
    ortho_by_tile = {}
    for fn in os.listdir(raw_dir):
        if fn.startswith("ortho_") and fn.endswith(".tif"):
            parts = fn[:-4].split("_")
            ortho_by_tile[(int(parts[1]), int(parts[2]))] = fn
    for n_km in range(n0_km, n1_km + 1):
        for e_km in range(e0_km, e1_km + 1):
            tx0 = e_km * 1000.0 - origin_e
            tz0 = n_km * 1000.0 - origin_n
            lx0, lz0 = tx0 - x0, tz0 - z0        # mosaic-local offsets
            grids = {}
            # LOD steps must divide TILE_M exactly or coarse tiles shrink
            # and leave gaps at their east/north edges (20 m: 50 cells).
            # Each LOD also stores CLUTTER (DSM - DTM: canopy/roof rise) so
            # the shader can tell a limestone wall from a house's side.
            # Clutter is sampled from the MOSAIC-level field and blurred
            # with the same kernel as its DSM — blurring only the DSM and
            # subtracting a raw DTM manufactured >100 m of fake canopy on
            # cliffs (GPT-5.6 review: 62,605 corrupted L1 samples).
            for name, step in (("1m", 1.0), ("2m", 2.0), ("4m", 4.0),
                               ("20m", 20.0)):
                xs = _grid(lx0, lx0 + TILE_M, step, halo=step)
                zs = _grid(lz0, lz0 + TILE_M, step, halo=step)
                dsm_g = _sample(dsm05, xs, zs)
                clutter_g = _sample(clutter05, xs, zs)
                if step >= 4.0:
                    # Coarse LODs: one [1,2,1]^2 pass rounds the aliased
                    # canopy needles into crowns; cliffs barely move.
                    dsm_g = _blur3(dsm_g)
                    clutter_g = _blur3(clutter_g)
                grids["dsm_" + name] = dsm_g
                grids["clutter_" + name] = clutter_g
            base = f"tile_{e_km}_{n_km}"
            ortho_fn = ortho_by_tile.get((e_km, n_km))
            if ortho_fn is None:
                raise FileNotFoundError(f"no ortho for tile {e_km}/{n_km}")
            tex_path = os.path.join(out_dir, base + "_tex.jpg")
            mid_path = os.path.join(out_dir, base + "_mid.jpg")
            if not (os.path.exists(tex_path) and os.path.exists(mid_path)):
                img = tifffile.imread(os.path.join(raw_dir, ortho_fn))
                pil = Image.fromarray(img)
                tex = pil.resize((TEX_PX, TEX_PX), Image.LANCZOS)
                mid = tex.resize((MID_PX, MID_PX), Image.LANCZOS)
                tex.save(tex_path, quality=88, subsampling=1)
                mid.save(mid_path, quality=88)
            np.savez_compressed(os.path.join(out_dir, base + "_hgt.npz"),
                                **grids)
            tiles.append({"x0": tx0, "z0": tz0, "size": TILE_M,
                          "hgt": base + "_hgt.npz",
                          "tex": base + "_tex.jpg",
                          "mid": base + "_mid.jpg"})
            print(f"  tile {e_km}/{n_km} baked")

    surround = _bake_surround(scene, man, out_dir, origin_e, origin_n,
                              origin_alt, x0, x1, z0, z1, dtm05)

    meta = {
        "name": scene,
        "title": spec["title"],
        "subtitle": spec["subtitle"],
        # The font atlas is ASCII: fold the glyphs older raw manifests used.
        "attribution": (man.get("attribution", "")
                        .replace("©", "(c)").replace("—", "-")),
        "epsg": man.get("epsg"),
        "origin_e": origin_e, "origin_n": origin_n,
        "origin_alt": origin_alt,
        "x0": x0, "x1": x1, "z0": z0, "z1": z1,
        "dtm": {"cell": 1.0, "file": "dtm_1m.npy"},
        "obstacle": {"cell": 1.0, "file": "obstacle.npy"},
        "spawn": {"x": spawn[0], "z": spawn[1], "yaw_deg": yaw},
        "s300": {"x": pad[0], "z": pad[1], "yaw_deg": yaw + 180.0},
        "tiles": tiles,
        "surround": surround,
    }
    with open(os.path.join(out_dir, "scene.json"), "w",
              encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    total = sum(os.path.getsize(os.path.join(out_dir, fn))
                for fn in os.listdir(out_dir))
    print(f"[{scene}] baked -> {out_dir}  ({total / 1e6:.0f} MB)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scene", nargs="?", default="lauterbrunnen",
                    choices=sorted(SCENE_SPECS))
    args = ap.parse_args()
    bake(args.scene)


if __name__ == "__main__":
    sys.exit(main())
