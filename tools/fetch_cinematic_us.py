"""Fetch USGS open data for a US cinematic scene and normalize it into the
same raw-tile layout tools/bake_cinematic_map.py already consumes:

    data/cinematic_raw/<scene>/dtm_<e>_<n>_0.5m.tif    2000x2000 float32
    data/cinematic_raw/<scene>/dsm_<e>_<n>_0.5m.tif    (copy of dtm: 3DEP
                                                        is bare earth; no
                                                        canopy/roof grid)
    data/cinematic_raw/<scene>/ortho_<e>_<n>_0.5m.tif  2000x2000x3 uint8
    data/cinematic_raw/<scene>/manifest.json

Sources (both US public domain):
- USGS 3DEP 1 m DEM GeoTIFFs via the TNM Access API (already projected in
  the local UTM zone: crop + 2x bilinear upsample, no warp needed).
- USGS Imagery Only basemap (NAIP-derived) WMTS tiles at z17/z18, warped
  from WebMercator onto the UTM kilometer grid with a numpy inverse-UTM ->
  Mercator mapping.

Usage:
    python tools/fetch_cinematic_us.py yosemite [--dry-run]
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import sys
import time

import numpy as np
import requests
import tifffile
from PIL import Image

RAW_ROOT = os.path.join("data", "cinematic_raw")
TNM = "https://tnmaccess.nationalmap.gov/api/v1/products"
WMTS = ("https://basemap.nationalmap.gov/arcgis/rest/services/"
        "USGSImageryOnly/MapServer/tile/{z}/{y}/{x}")
IMAGERY_Z = 16            # the USGS tile cache tops out at 1:9,028 (z16,
                          # ~1.9 m/px at 37.7N) — z17 404s everywhere

# UTM kilometer-tile scenes.  Yosemite Valley, zone 11N (EPSG 26911):
# El Capitan on the west edge, Yosemite Falls + the village mid-scene,
# Sentinel and Half Dome walls on the south/east.
SCENES = {
    "yosemite": {
        "epsg": 26911,
        "zone": 11,
        "e_km": (267, 271),        # inclusive: El Capitan on the west edge
        "n_km": (4177, 4180),      # the valley runs NE: keep Cook's Meadow
        "attribution": "Terrain & imagery: USGS 3DEP / USGS Imagery "
                       "(NAIP) - public domain",
    },
}

_K0 = 0.9996
_A = 6_378_137.0
_E2 = 0.006_694_38                # WGS84/GRS80 e^2 (NAD83 ~ identical)


def _utm_to_ll(e: np.ndarray, n: np.ndarray, zone: int):
    """Inverse transverse Mercator (Krüger-style series, meter accuracy)."""
    e1sq = _E2 / (1.0 - _E2)
    m = (n / _K0)
    mu = m / (_A * (1 - _E2 / 4 - 3 * _E2 ** 2 / 64 - 5 * _E2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - _E2)) / (1 + math.sqrt(1 - _E2))
    j1 = 3 * e1 / 2 - 27 * e1 ** 3 / 32
    j2 = 21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32
    j3 = 151 * e1 ** 3 / 96
    j4 = 1097 * e1 ** 4 / 512
    fp = (mu + j1 * np.sin(2 * mu) + j2 * np.sin(4 * mu)
          + j3 * np.sin(6 * mu) + j4 * np.sin(8 * mu))
    sin_fp, cos_fp, tan_fp = np.sin(fp), np.cos(fp), np.tan(fp)
    c1 = e1sq * cos_fp ** 2
    t1 = tan_fp ** 2
    r1 = _A * (1 - _E2) / np.power(1 - _E2 * sin_fp ** 2, 1.5)
    n1 = _A / np.sqrt(1 - _E2 * sin_fp ** 2)
    d = (e - 500_000.0) / (n1 * _K0)
    q1 = n1 * tan_fp / r1
    q2 = d ** 2 / 2
    q3 = (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * e1sq) * d ** 4 / 24
    q4 = (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * e1sq
          - 3 * c1 ** 2) * d ** 6 / 720
    lat = fp - q1 * (q2 - q3 + q4)
    q5 = d
    q6 = (1 + 2 * t1 + c1) * d ** 3 / 6
    q7 = (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * e1sq
          + 24 * t1 ** 2) * d ** 5 / 120
    lon0 = math.radians(zone * 6 - 183)
    lon = lon0 + (q5 - q6 + q7) / cos_fp
    return np.degrees(lat), np.degrees(lon)


def _merc_px(lat, lon, z: int):
    """WebMercator tile-pixel coordinates (global px at zoom z)."""
    scale = 256 * (2 ** z)
    x = (lon + 180.0) / 360.0 * scale
    s = np.sin(np.radians(lat))
    y = (0.5 - np.log((1 + s) / (1 - s)) / (4 * math.pi)) * scale
    return x, y


class _TileCache:
    def __init__(self, session, z: int):
        self.session = session
        self.z = z
        self.tiles: dict = {}
        self.misses = 0

    def get(self, tx: int, ty: int) -> np.ndarray:
        key = (tx, ty)
        got = self.tiles.get(key)
        if got is None:
            url = WMTS.format(z=self.z, y=ty, x=tx)
            for attempt in range(4):
                try:
                    r = self.session.get(url, timeout=60)
                    if r.status_code == 404:
                        self.misses += 1
                        got = np.zeros((256, 256, 3), dtype=np.uint8)
                        break
                    r.raise_for_status()
                    got = np.asarray(
                        Image.open(io.BytesIO(r.content)).convert("RGB"),
                        dtype=np.uint8)
                    break
                except Exception:            # noqa: BLE001
                    time.sleep(1.5 * (attempt + 1))
            else:
                got = np.zeros((256, 256, 3), dtype=np.uint8)
            self.tiles[key] = got
        return got


def _warp_imagery(cache: _TileCache, e0: float, n0: float, zone: int,
                  out_px: int = 2000, cell: float = 0.5) -> np.ndarray:
    """Sample the WMTS mosaic onto a UTM km tile (nearest neighbour)."""
    es = e0 + (np.arange(out_px) + 0.5) * cell
    ns = n0 + 1000.0 - (np.arange(out_px) + 0.5) * cell   # row 0 = north
    ee, nn = np.meshgrid(es, ns)
    lat, lon = _utm_to_ll(ee, nn, zone)
    gx, gy = _merc_px(lat, lon, cache.z)
    gx_i = gx.astype(np.int64)
    gy_i = gy.astype(np.int64)
    out = np.empty((out_px, out_px, 3), dtype=np.uint8)
    tx0, tx1 = int(gx_i.min() // 256), int(gx_i.max() // 256)
    ty0, ty1 = int(gy_i.min() // 256), int(gy_i.max() // 256)
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            sel = ((gx_i // 256 == tx) & (gy_i // 256 == ty))
            if not sel.any():
                continue
            tile = cache.get(tx, ty)
            out[sel] = tile[gy_i[sel] % 256, gx_i[sel] % 256]
    return out


def _dem_products(session, bbox_ll) -> list:
    params = {
        "datasets": "Digital Elevation Model (DEM) 1 meter",
        "bbox": ",".join(f"{v:.6f}" for v in bbox_ll),
        "outputFormat": "JSON", "max": 100,
    }
    for attempt in range(4):
        try:
            r = session.get(TNM, params=params, timeout=120)
            r.raise_for_status()
            return r.json().get("items", [])
        except Exception as exc:              # noqa: BLE001 — flaky API
            print(f"  TNM retry {attempt + 1}: {exc}")
            time.sleep(4.0 * (attempt + 1))
    return []


def _read_geotiff_grid(path: str):
    with tifffile.TiffFile(path) as t:
        page = t.pages[0]
        scale = page.tags["ModelPixelScaleTag"].value
        tie = page.tags["ModelTiepointTag"].value
        a = page.asarray().astype(np.float32)
    e_nw, n_nw = float(tie[3]), float(tie[4])
    return a, e_nw, n_nw, float(scale[0])


def fetch_scene(scene_name: str, dry: bool) -> None:
    spec = SCENES[scene_name]
    zone = spec["zone"]
    e0_km, e1_km = spec["e_km"]
    n0_km, n1_km = spec["n_km"]
    root = os.path.join(RAW_ROOT, scene_name)
    os.makedirs(root, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = "oinks-proto-cinematic/1.0"

    # Scene corners -> lat/lon bbox for the DEM product query.
    ee = np.array([e0_km * 1000.0, (e1_km + 1) * 1000.0], dtype=np.float64)
    nn = np.array([n0_km * 1000.0, (n1_km + 1) * 1000.0], dtype=np.float64)
    lat, lon = _utm_to_ll(np.array([ee[0], ee[1], ee[0], ee[1]]),
                          np.array([nn[0], nn[0], nn[1], nn[1]]), zone)
    bbox = (float(lon.min()), float(lat.min()),
            float(lon.max()), float(lat.max()))
    print(f"[{scene_name}] bbox {bbox}")

    items = _dem_products(session, bbox)
    print(f"  {len(items)} 1m DEM products")
    dem_paths = []
    for it in items:
        url = it.get("downloadURL", "")
        if not url.lower().endswith(".tif"):
            continue
        dest = os.path.join(root, "src_" + os.path.basename(url))
        dem_paths.append(dest)
        if os.path.exists(dest) or dry:
            print(f"  have {os.path.basename(dest)}"
                  if os.path.exists(dest) else f"  would GET {url}")
            continue
        print(f"  GET {os.path.basename(url)}")
        with session.get(url, stream=True, timeout=1200) as r:
            r.raise_for_status()
            tmp = dest + ".part"
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        os.replace(tmp, dest)
    if not dem_paths:
        # TNM down but sources cached from a previous run: use them.
        dem_paths = [os.path.join(root, fn) for fn in os.listdir(root)
                     if fn.startswith("src_") and fn.endswith(".tif")]
        print(f"  falling back to {len(dem_paths)} cached source DEMs")
    if dry:
        return

    # Mosaic the source DEMs once (1 m), then cut 0.5 m km tiles.
    scene_e0 = e0_km * 1000.0
    scene_n0 = n0_km * 1000.0
    w_m = (e1_km - e0_km + 1) * 1000
    h_m = (n1_km - n0_km + 1) * 1000
    dem = np.full((h_m, w_m), np.nan, dtype=np.float32)   # 1 m, row 0 south
    # First writer wins in the mosaic: put the park's dedicated lidar DEM
    # ahead of any overlapping regional project.
    dem_paths.sort(key=lambda p: "YosemiteNP" not in p)
    for path in dem_paths:
        a, e_nw, n_nw, cell = _read_geotiff_grid(path)
        if abs(cell - 1.0) > 0.01:
            print(f"  !! {os.path.basename(path)} cell {cell} != 1m, skip")
            continue
        a = np.flipud(a)                                   # row 0 = south
        n_sw = n_nw - a.shape[0] * cell
        i0 = int(round(e_nw - scene_e0))
        j0 = int(round(n_sw - scene_n0))
        si0, sj0 = max(0, -i0), max(0, -j0)
        di0, dj0 = max(0, i0), max(0, j0)
        w = min(a.shape[1] - si0, w_m - di0)
        h = min(a.shape[0] - sj0, h_m - dj0)
        if w <= 0 or h <= 0:
            continue
        block = a[sj0:sj0 + h, si0:si0 + w]
        target = dem[dj0:dj0 + h, di0:di0 + w]
        dem[dj0:dj0 + h, di0:di0 + w] = np.where(np.isnan(target), block,
                                                 target)
    nan_frac = float(np.isnan(dem).mean())
    print(f"  DEM mosaic void fraction {nan_frac:.3f}")
    if nan_frac > 0.0:
        col = np.nanmean(dem, axis=0)
        dem = np.where(np.isnan(dem), col[None, :], dem)

    cache = _TileCache(session, IMAGERY_Z)
    manifest = {"scene": scene_name, "epsg": spec["epsg"],
                "e_km": [e0_km, e1_km], "n_km": [n0_km, n1_km],
                "attribution": spec["attribution"], "files": []}
    for n_km in range(n0_km, n1_km + 1):
        for e_km in range(e0_km, e1_km + 1):
            base = f"{e_km}_{n_km}_0.5m.tif"
            # DEM: crop the km + 2x bilinear upsample to the 0.5 m grid.
            i0 = (e_km - e0_km) * 1000
            j0 = (n_km - n0_km) * 1000
            block = dem[max(0, j0 - 1):j0 + 1002, max(0, i0 - 1):i0 + 1002]
            img = Image.fromarray(block, mode="F")
            up = np.asarray(img.resize((block.shape[1] * 2,
                                        block.shape[0] * 2),
                                       Image.BILINEAR), dtype=np.float32)
            lead_j = 2 if j0 > 0 else 0
            lead_i = 2 if i0 > 0 else 0
            tile = up[lead_j:lead_j + 2000, lead_i:lead_i + 2000]
            tile = np.flipud(tile)                       # file row 0 = north
            for kind in ("dtm", "dsm"):
                dest = os.path.join(root, f"{kind}_{base}")
                if not os.path.exists(dest):
                    tifffile.imwrite(
                        dest, tile,
                        extratags=[
                            (33550, "d", 3, (0.5, 0.5, 0.0)),
                            (33922, "d", 6,
                             (0.0, 0.0, 0.0, e_km * 1000.0,
                              (n_km + 1) * 1000.0, 0.0)),
                        ])
                manifest["files"].append({"file": f"{kind}_{base}",
                                          "kind": kind, "gsd_m": 0.5})
            dest = os.path.join(root, f"ortho_{base}")
            if not os.path.exists(dest):
                rgb = _warp_imagery(cache, e_km * 1000.0, n_km * 1000.0,
                                    zone)
                tifffile.imwrite(dest, rgb, compression="jpeg",
                                 extratags=[
                                     (33550, "d", 3, (0.5, 0.5, 0.0)),
                                     (33922, "d", 6,
                                      (0.0, 0.0, 0.0, e_km * 1000.0,
                                       (n_km + 1) * 1000.0, 0.0)),
                                 ])
            manifest["files"].append({"file": f"ortho_{base}",
                                      "kind": "ortho", "gsd_m": 0.5})
            print(f"  tile {e_km}/{n_km} ready "
                  f"({len(cache.tiles)} wmts tiles, {cache.misses} 404s)")
    with open(os.path.join(root, "manifest.json"), "w",
              encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"[{scene_name}] raw tiles ready -> {root}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scene", nargs="?", default="yosemite",
                    choices=sorted(SCENES))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    fetch_scene(args.scene, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
