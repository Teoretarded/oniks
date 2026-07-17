"""Bake the map-expansion rings into an existing cinematic scene.

Consumes tools/fetch_cinematic_ring.py output and APPENDS to the scene's
scene.json (the core/surround bake is untouched):

- "surround2": 64 x 64 km from swissALTI3D 2 m + SWISSIMAGE 2 m ->
  16 km chunks, 64 m mesh cells, 2048 px textures (8 m/px), same npz/jpg
  schema as "surround" (h grid carries the usual 1-cell halo + pad row).
- "surround3": ~160 x 160 km from Copernicus GLO-30 -> 40 km chunks,
  250 m mesh cells, PROCEDURAL alpine tint baked into 512 px textures
  (altitude + slope palette; at 40-100 km the far ring is haze-dominated
  silhouettes, so baked tint reads right and needs no far imagery).

Chunks fully covered by a finer layer are skipped; partially covered
ones are tucked 12 m under it (same no-z-fight trick as "surround").

Usage: python tools/bake_cinematic_ring.py [lauterbrunnen]
"""

from __future__ import annotations

import json
import math
import os
import sys

import numpy as np
import tifffile
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RAW_ROOT = os.path.join("data", "cinematic_raw")
OUT_ROOT = os.path.join("assets", "cinematic")

R2_CHUNK_KM = 16
R2_CELL_M = 64
R2_TEX = 2048
R2_PX_KM = 125                     # 8 m assembly grid (RAM-friendly)
R3_EXTENT_KM = 160                 # total extent, centred on the scene
R3_CHUNK_KM = 40
R3_CELL_M = 250
R3_TEX = 512
TUCK_M = 18.0


def _scene_json(scene: str) -> dict:
    with open(os.path.join(OUT_ROOT, scene, "scene.json"),
              encoding="utf-8") as f:
        return json.load(f)


def _finer_field(chunks: list, out_dir: str):
    """(field, cell, x0, z0, x1, z1) mosaic of an already-baked chunk
    list (scene.json schema) so coarser rings can clamp UNDER it.
    Tucking against foreign data (GLO-30 canopy heights) let ring slabs
    breach the LiDAR valley floor — the user's black square/lines."""
    if not chunks:
        return None
    x0 = min(c["x0"] for c in chunks)
    z0 = min(c["z0"] for c in chunks)
    x1 = max(c["x0"] + c["size"] for c in chunks)
    z1 = max(c["z0"] + c["size"] for c in chunks)
    size = chunks[0]["size"]
    with np.load(os.path.join(out_dir, chunks[0]["hgt"])) as z:
        n_in = z["h"].shape[0] - 2
    cell = size / (n_in - 1)
    nx = int(round((x1 - x0) / cell)) + 1
    nz = int(round((z1 - z0) / cell)) + 1
    field = np.full((nz, nx), np.nan, np.float32)
    for c in chunks:
        with np.load(os.path.join(out_dir, c["hgt"])) as zf:
            inner = zf["h"][1:-1, 1:-1]
        ix = int(round((c["x0"] - x0) / cell))
        iz = int(round((c["z0"] - z0) / cell))
        field[iz:iz + n_in, ix:ix + n_in] = inner
    return (field, cell, x0, z0, x1, z1)


def _clamp_under(grid: np.ndarray, xs: np.ndarray, zs: np.ndarray,
                 finer, tuck: float) -> np.ndarray:
    """Force every cell that lies inside the finer field's rect to sit
    at least ``tuck`` below the finer surface (nearest-sample)."""
    field, cell, fx0, fz0, fx1, fz1 = finer
    inside = ((xs[None, :] >= fx0) & (xs[None, :] <= fx1)
              & (zs[:, None] >= fz0) & (zs[:, None] <= fz1))
    if not inside.any():
        return grid
    ii = np.clip(np.round((xs - fx0) / cell).astype(int),
                 0, field.shape[1] - 1)
    jj = np.clip(np.round((zs - fz0) / cell).astype(int),
                 0, field.shape[0] - 1)
    # MIN over a 3x3 finer-field window: a coarse cell interpolating
    # between clamped posts can still bulge ABOVE the finer surface
    # mid-cell on knife ridges (user report: uncolored blobs all over
    # the massif faces).  Clamping to the local minimum kills that.
    lim = None
    for dj in (-1, 0, 1):
        j2 = np.clip(jj + dj, 0, field.shape[0] - 1)
        for di in (-1, 0, 1):
            i2 = np.clip(ii + di, 0, field.shape[1] - 1)
            v = field[j2[:, None], i2[None, :]]
            lim = v if lim is None else np.fmin(lim, v)
    lim = lim - tuck
    ok = inside & np.isfinite(lim)
    out = np.where(ok, np.minimum(grid, lim), grid)
    return np.where(inside & ~np.isfinite(lim), grid - tuck, out)


def _grid_from_dem(dem: np.ndarray, gj0: int, gi0: int, n_cells: int,
                   step: int) -> np.ndarray:
    """(n+3, n+3) height grid sampled every ``step`` px with edge pad —
    mirrors _bake_surround's layout (1-halo + closing row)."""
    grid = np.empty((n_cells + 3, n_cells + 3), np.float32)
    for jj in range(n_cells + 3):
        sj = min(max(gj0 + (jj - 1) * step, 0), dem.shape[0] - 1)
        row = dem[sj, max(gi0 - step, 0):gi0 + (n_cells + 2) * step:step]
        row = np.pad(row, (0, max(0, n_cells + 3 - len(row))), mode="edge")
        grid[jj] = row[:n_cells + 3]
    return grid


# ------------------------------------------------------------------- ring 2

def _bake_ring2(scene: str, man2: dict, sj: dict, out_dir: str) -> list:
    re0, re1 = man2["r2_e_km"]
    rn0, rn1 = man2["r2_n_km"]
    e_tiles = re1 - re0 + 1
    n_tiles = rn1 - rn0 + 1
    raw_dir = os.path.join(RAW_ROOT, scene)
    origin_e = sj["origin_e"]
    origin_n = sj["origin_n"]
    origin_alt = sj["origin_alt"]
    print(f"[{scene}] ring2: assembling {e_tiles}x{n_tiles} km at 8 m")
    dem = np.full((n_tiles * R2_PX_KM, e_tiles * R2_PX_KM), np.nan,
                  np.float32)
    rgb = np.zeros((n_tiles * R2_PX_KM, e_tiles * R2_PX_KM, 3), np.uint8)
    n_files = 0
    for fn in sorted(os.listdir(raw_dir)):
        is_d = fn.startswith("r2dtm_")
        is_o = fn.startswith("r2ortho_")
        if not (is_d or is_o) or not fn.endswith(".tif"):
            continue
        parts = fn[:-4].split("_")
        e_km, n_km = int(parts[1]), int(parts[2])
        if not (re0 <= e_km <= re1 and rn0 <= n_km <= rn1):
            continue
        try:
            a = tifffile.imread(os.path.join(raw_dir, fn))
        except Exception as exc:                       # noqa: BLE001
            print(f"  !! unreadable {fn}: {exc}")
            continue
        img = Image.fromarray(a if is_o else a.astype(np.float32))
        a = np.asarray(img.resize((R2_PX_KM, R2_PX_KM), Image.BILINEAR))
        j0 = (n_km - rn0) * R2_PX_KM
        i0 = (e_km - re0) * R2_PX_KM
        if is_d:
            dem[j0:j0 + R2_PX_KM, i0:i0 + R2_PX_KM] = \
                np.flipud(a.astype(np.float32)) - origin_alt
        else:
            rgb[j0:j0 + R2_PX_KM, i0:i0 + R2_PX_KM] = np.flipud(a)[..., :3]
        n_files += 1
    print(f"  {n_files} ring tiles mosaicked")
    # Holes (lakes, border gaps, missing tiles): fill DEM from the
    # GLO-30 mosaic — column-means built a black cliff wedge in probe
    # shot 43 — then column-means only as the last resort.
    nan = np.isnan(dem)
    if nan.any():
        tiles30 = _load_glo30(scene)
        if tiles30:
            jj, ii = np.nonzero(nan)
            e = re0 * 1000.0 + (ii + 0.5) * 8.0
            n = rn0 * 1000.0 + (jj + 0.5) * 8.0
            dem[jj, ii] = (_sample_glo30(tiles30, e, n)
                           - float(origin_alt))
            print(f"  {len(jj)} DEM hole px filled from GLO-30")
    if np.isnan(dem).any():
        col = np.nanmean(np.where(np.isnan(dem), np.nan, dem), axis=0)
        col = np.where(np.isnan(col), 0.0, col)
        dem = np.where(np.isnan(dem), col[None, :], dem).astype(np.float32)
    # Zero-RGB ortho gaps (grey patches, probe shot 44): paint the
    # alpine tint so holes read as terrain, not primer.
    black = rgb.sum(axis=2) == 0
    if black.any():
        h_asl = dem + float(origin_alt)
        dzdx = np.gradient(h_asl, 8.0, axis=1)
        dzdy = np.gradient(h_asl, 8.0, axis=0)
        tint = _alpine_tint(h_asl, np.hypot(dzdx, dzdy))
        rgb[black] = tint[black]
        print(f"  {int(black.sum())} ortho hole px tinted")

    # The existing surround (finer): chunks fully inside skip out,
    # partial overlaps clamp UNDER its baked surface.
    finer_sur = _finer_field(sj.get("surround", []), out_dir)
    if finer_sur is not None:
        sur_x0, sur_z0, sur_x1, sur_z1 = finer_sur[2:6]
    else:
        sur_x0 = sur_x1 = sur_z0 = sur_z1 = 0.0

    rx0 = re0 * 1000.0 - origin_e
    rz0 = rn0 * 1000.0 - origin_n
    step = R2_CELL_M // 8                    # px per mesh cell
    out = []
    for cj in range(n_tiles // R2_CHUNK_KM):
        for ci in range(e_tiles // R2_CHUNK_KM):
            x0c = rx0 + ci * R2_CHUNK_KM * 1000.0
            z0c = rz0 + cj * R2_CHUNK_KM * 1000.0
            x1c = x0c + R2_CHUNK_KM * 1000.0
            z1c = z0c + R2_CHUNK_KM * 1000.0
            if (x0c >= sur_x0 and x1c <= sur_x1
                    and z0c >= sur_z0 and z1c <= sur_z1):
                continue
            n_cells = R2_CHUNK_KM * 1000 // R2_CELL_M
            gj0 = cj * R2_CHUNK_KM * R2_PX_KM
            gi0 = ci * R2_CHUNK_KM * R2_PX_KM
            grid = _grid_from_dem(dem, gj0, gi0, n_cells, step)
            # Clamp the parts the finer surround already draws UNDER its
            # own baked surface (not a blind offset).
            xs = x0c + (np.arange(n_cells + 3) - 1) * float(R2_CELL_M)
            zs = z0c + (np.arange(n_cells + 3) - 1) * float(R2_CELL_M)
            if finer_sur is not None:
                grid = _clamp_under(grid, xs, zs, finer_sur, TUCK_M)
            base = f"surround2_{ci}_{cj}"
            tex = Image.fromarray(np.flipud(
                rgb[gj0:gj0 + R2_CHUNK_KM * R2_PX_KM,
                    gi0:gi0 + R2_CHUNK_KM * R2_PX_KM]))
            tex = tex.resize((R2_TEX, R2_TEX), Image.LANCZOS)
            tex.save(os.path.join(out_dir, base + ".jpg"), quality=82)
            np.savez_compressed(os.path.join(out_dir, base + "_hgt.npz"),
                                h=grid)
            out.append({"x0": x0c, "z0": z0c,
                        "size": R2_CHUNK_KM * 1000.0,
                        "hgt": base + "_hgt.npz", "tex": base + ".jpg"})
    print(f"  ring2: {len(out)} chunks")
    return out


# ---------------------------------------------------------- GLO-30 helpers

def _load_glo30(scene: str) -> dict:
    glo_dir = os.path.join(RAW_ROOT, scene, "glo30")
    tiles = {}
    if os.path.isdir(glo_dir):
        for fn in sorted(os.listdir(glo_dir)):
            if fn.endswith(".tif"):
                lat = int(fn.split("_N")[1][:2])
                lon = int(fn.split("_E")[1][:3])
                tiles[(lat, lon)] = tifffile.imread(
                    os.path.join(glo_dir, fn))
    return tiles


def _sample_glo30(tiles: dict, e: np.ndarray, n: np.ndarray) -> np.ndarray:
    """Bilinear GLO-30 heights at LV95 points (mirrors the ring-3 grid
    sampler for scattered hole-fill points)."""
    lon, lat = _lv95_to_wgs84(np.asarray(e, np.float64),
                              np.asarray(n, np.float64))
    out = np.zeros(lon.shape, np.float32)
    lat_i = np.floor(lat).astype(int)
    lon_i = np.floor(lon).astype(int)
    for (tlat, tlon), arr in tiles.items():
        m = (lat_i == tlat) & (lon_i == tlon)
        if not m.any():
            continue
        rows, cols = arr.shape
        fr = (1.0 - (lat - tlat)) * (rows - 1)
        fc = (lon - tlon) * (cols - 1)
        r0 = np.clip(fr.astype(int), 0, rows - 2)
        c0 = np.clip(fc.astype(int), 0, cols - 2)
        wr = np.clip(fr - r0, 0.0, 1.0)
        wc = np.clip(fc - c0, 0.0, 1.0)
        v = ((arr[r0, c0] * (1 - wc) + arr[r0, c0 + 1] * wc) * (1 - wr)
             + (arr[r0 + 1, c0] * (1 - wc)
                + arr[r0 + 1, c0 + 1] * wc) * wr)
        out = np.where(m, v.astype(np.float32), out)
    return out


# ------------------------------------------------------------------- ring 3

def _lv95_to_wgs84(e: np.ndarray, n: np.ndarray):
    """Vectorized swisstopo approx formulas (fetch tool's, arrayified)."""
    y = (e - 2_600_000.0) / 1_000_000.0
    x = (n - 1_200_000.0) / 1_000_000.0
    lon = (2.6779094 + 4.728982 * y + 0.791484 * y * x
           + 0.1306 * y * x * x - 0.0436 * y ** 3) * 100.0 / 36.0
    lat = (16.9023892 + 3.238272 * x - 0.270978 * y * y
           - 0.002528 * x * x - 0.0447 * y * y * x
           - 0.0140 * x ** 3) * 100.0 / 36.0
    return lon, lat


def _alpine_tint(h_asl: np.ndarray, slope: np.ndarray) -> np.ndarray:
    """Altitude+slope palette for the far ring (uint8 RGB): valley green
    -> subalpine forest -> rock -> snow, rock forced on steep faces."""
    h = np.clip(h_asl, 0.0, 4500.0)
    stops = np.array([
        [0.0, 96, 118, 74],       # valley grass
        [900.0, 74, 96, 60],      # forest
        [1900.0, 118, 112, 100],  # alpine rock/meadow mix
        [2600.0, 132, 128, 122],  # bare rock
        [3000.0, 224, 228, 232],  # snow
        [4500.0, 240, 243, 246],
    ], dtype=np.float64)
    rgbf = np.empty(h.shape + (3,), np.float64)
    for c in range(3):
        rgbf[..., c] = np.interp(h, stops[:, 0], stops[:, c + 1])
    rock = np.array([124.0, 118.0, 110.0])
    s = np.clip((slope - 0.55) / 0.5, 0.0, 1.0)[..., None]
    snowless = h[..., None] < 2800.0
    rgbf = np.where(snowless, rgbf * (1.0 - s) + rock[None, None] * s,
                    rgbf)
    return np.clip(rgbf, 0, 255).astype(np.uint8)


def _bake_ring3(scene: str, sj: dict, man2: dict, out_dir: str,
                finers: list) -> list:
    origin_e = sj["origin_e"]
    origin_n = sj["origin_n"]
    origin_alt = sj["origin_alt"]
    glo_dir = os.path.join(RAW_ROOT, scene, "glo30")
    tiles = {}
    for fn in sorted(os.listdir(glo_dir)):
        if not fn.endswith(".tif"):
            continue
        lat = int(fn.split("_N")[1][:2])
        lon = int(fn.split("_E")[1][:3])
        tiles[(lat, lon)] = tifffile.imread(os.path.join(glo_dir, fn))
    if not tiles:
        print("  !! no GLO-30 tiles; ring3 skipped")
        return []
    shp = next(iter(tiles.values())).shape
    print(f"[{scene}] ring3: {len(tiles)} GLO-30 tiles {shp}")

    half = R3_EXTENT_KM * 500.0
    n_post = int(R3_EXTENT_KM * 1000 / R3_CELL_M) + 3
    xs = -half + (np.arange(n_post) - 1) * float(R3_CELL_M)
    zs = -half + (np.arange(n_post) - 1) * float(R3_CELL_M)
    gx, gz = np.meshgrid(xs, zs)
    lon, lat = _lv95_to_wgs84(gx + origin_e, gz + origin_n)
    dem = np.zeros_like(gx, np.float32)
    lat_i = np.floor(lat).astype(int)
    lon_i = np.floor(lon).astype(int)
    for (tlat, tlon), arr in tiles.items():
        m = (lat_i == tlat) & (lon_i == tlon)
        if not m.any():
            continue
        rows, cols = arr.shape
        fr = (1.0 - (lat - tlat)) * (rows - 1)     # row 0 = north edge
        fc = (lon - tlon) * (cols - 1)
        r0 = np.clip(fr.astype(int), 0, rows - 2)
        c0 = np.clip(fc.astype(int), 0, cols - 2)
        wr = np.clip(fr - r0, 0.0, 1.0)
        wc = np.clip(fc - c0, 0.0, 1.0)
        v = ((arr[r0, c0] * (1 - wc) + arr[r0, c0 + 1] * wc) * (1 - wr)
             + (arr[r0 + 1, c0] * (1 - wc) + arr[r0 + 1, c0 + 1] * wc)
             * wr)
        dem = np.where(m, v.astype(np.float32), dem)
    dem_local = dem - float(origin_alt)

    # Finer coverage to tuck under: the R2 rect.
    re0, re1 = man2["r2_e_km"]
    rn0, rn1 = man2["r2_n_km"]
    r2x0, r2x1 = re0 * 1000.0 - origin_e, (re1 + 1) * 1000.0 - origin_e
    r2z0, r2z1 = rn0 * 1000.0 - origin_n, (rn1 + 1) * 1000.0 - origin_n

    n_chunks = R3_EXTENT_KM // R3_CHUNK_KM
    n_cells = R3_CHUNK_KM * 1000 // R3_CELL_M
    out = []
    for cj in range(n_chunks):
        for ci in range(n_chunks):
            x0c = -half + ci * R3_CHUNK_KM * 1000.0
            z0c = -half + cj * R3_CHUNK_KM * 1000.0
            x1c = x0c + R3_CHUNK_KM * 1000.0
            z1c = z0c + R3_CHUNK_KM * 1000.0
            if (x0c >= r2x0 and x1c <= r2x1
                    and z0c >= r2z0 and z1c <= r2z1):
                continue
            gj0 = cj * n_cells
            gi0 = ci * n_cells
            grid = dem_local[gj0:gj0 + n_cells + 3,
                             gi0:gi0 + n_cells + 3].copy()
            if grid.shape != (n_cells + 3, n_cells + 3):
                grid = np.pad(grid,
                              ((0, n_cells + 3 - grid.shape[0]),
                               (0, n_cells + 3 - grid.shape[1])),
                              mode="edge")
            cxs = x0c + (np.arange(n_cells + 3) - 1) * float(R3_CELL_M)
            czs = z0c + (np.arange(n_cells + 3) - 1) * float(R3_CELL_M)
            for finer in finers:
                grid = _clamp_under(grid, cxs, czs, finer, TUCK_M)
            # Baked tint from ASL height + slope.
            h_asl = grid[1:-2, 1:-2] + float(origin_alt)
            dzdx = np.gradient(h_asl, float(R3_CELL_M), axis=1)
            dzdy = np.gradient(h_asl, float(R3_CELL_M), axis=0)
            slope = np.hypot(dzdx, dzdy)
            tint = _alpine_tint(h_asl, slope)
            base = f"surround3_{ci}_{cj}"
            Image.fromarray(np.flipud(tint)).resize(
                (R3_TEX, R3_TEX), Image.BILINEAR).save(
                    os.path.join(out_dir, base + ".jpg"), quality=85)
            np.savez_compressed(os.path.join(out_dir, base + "_hgt.npz"),
                                h=grid.astype(np.float32))
            out.append({"x0": float(x0c), "z0": float(z0c),
                        "size": R3_CHUNK_KM * 1000.0,
                        "hgt": base + "_hgt.npz", "tex": base + ".jpg"})
    print(f"  ring3: {len(out)} chunks")
    return out


def main() -> None:
    scene = sys.argv[1] if len(sys.argv) > 1 else "lauterbrunnen"
    out_dir = os.path.join(OUT_ROOT, scene)
    sj = _scene_json(scene)
    with open(os.path.join(RAW_ROOT, scene, "r2_manifest.json"),
              encoding="utf-8") as f:
        man2 = json.load(f)
    sj["surround2"] = _bake_ring2(scene, man2, sj, out_dir)
    # Ring 3 clamps under BOTH finer layers' freshly-baked surfaces.
    finers3 = [f for f in (_finer_field(sj["surround2"], out_dir),
                           _finer_field(sj.get("surround", []), out_dir))
               if f is not None]
    sj["surround3"] = _bake_ring3(scene, sj, man2, out_dir, finers3)
    sj["far_attribution"] = man2.get("glo30_attribution", "")
    tmp = os.path.join(out_dir, "scene.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sj, f, indent=1)
    os.replace(tmp, os.path.join(out_dir, "scene.json"))
    print(f"[{scene}] scene.json updated "
          f"(+{len(sj['surround2'])} r2, +{len(sj['surround3'])} r3)")


if __name__ == "__main__":
    sys.exit(main())
