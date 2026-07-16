"""Fetch open-license real-world geodata for the F3 cinematic scenes.

Downloads source rasters into ``data/cinematic_raw/<scene>/`` (gitignored):

- Switzerland (swisstopo, open data — free use with attribution
  "© swisstopo", see https://www.swisstopo.admin.ch/en/terms-of-use):
    * swissALTI3D        0.5 m DTM (bare-earth LiDAR terrain)  [.tif COG]
    * swissSURFACE3D     0.5 m DSM (LiDAR surface: trees, roofs) [.tif COG]
    * SWISSIMAGE dop10   0.1 m / 2 m orthophoto                 [.tif COG]

- USA (USGS, public domain): fetched by tools/fetch_cinematic_us.py.

Every scene gets a ``manifest.json`` listing each file, its source
collection, resolution and the license line the in-game credits must show.

Usage:
    python tools/fetch_cinematic_data.py lauterbrunnen [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import requests

STAC = "https://data.geo.admin.ch/api/stac/v0.9"

# Scene = LV95 km-tile rectangle + which km tiles deserve 10 cm imagery.
# Lauterbrunnen: U-valley floor with the village at ~E2635.7/N1159.2 km,
# Staubbach falls on the west wall, 400 m cliffs both sides.
SCENES = {
    "lauterbrunnen": {
        "epsg": 2056,
        "e_km": (2634, 2637),      # inclusive km tile columns (E)
        "n_km": (1157, 1160),      # inclusive km tile rows (N)
        # Coarse 2 m ring so the world doesn't end at the scene edge:
        # Eiger/Moench/Jungfrau to the east, Interlaken valley north.
        "surround_e_km": (2628, 2643),
        "surround_n_km": (1151, 1166),
        # 10 cm imagery is only ~40 MB/km² (JPEG COG) — take it everywhere.
        "hires_tiles": {(e, n) for e in range(2634, 2638)
                        for n in range(1157, 1161)},
        # ASCII only: the in-game font atlas has no (c)/em-dash glyphs.
        "attribution": "Terrain & imagery: (c) swisstopo (swissALTI3D, "
                       "swissSURFACE3D, SWISSIMAGE) - open data",
    },
}

COLLECTIONS = {
    "dtm": "ch.swisstopo.swissalti3d",
    "dsm": "ch.swisstopo.swisssurface3d-raster",
    "ortho": "ch.swisstopo.swissimage-dop10",
}


def _tile_bbox_lv95(e_km: int, n_km: int):
    return e_km * 1000.0, n_km * 1000.0, (e_km + 1) * 1000.0, (n_km + 1) * 1000.0


def _stac_items(collection: str, bbox_wgs84, session) -> list:
    """All STAC items intersecting bbox (handles pagination)."""
    items, url = [], (f"{STAC}/collections/{collection}/items"
                     f"?bbox={','.join(f'{v:.6f}' for v in bbox_wgs84)}&limit=100")
    while url:
        r = session.get(url, timeout=60)
        r.raise_for_status()
        js = r.json()
        items += js.get("features", [])
        url = next((l["href"] for l in js.get("links", []) if l["rel"] == "next"),
                   None)
    return items


def _lv95_to_wgs84_bbox(e0, n0, e1, n1):
    """Approximate LV95 -> WGS84 for a bbox query (swisstopo's own approx
    formulas; STAC bbox filtering only needs ~100 m accuracy)."""
    def conv(e, n):
        y = (e - 2_600_000.0) / 1_000_000.0
        x = (n - 1_200_000.0) / 1_000_000.0
        lon = (2.6779094 + 4.728982 * y + 0.791484 * y * x
               + 0.1306 * y * x * x - 0.0436 * y ** 3) * 100.0 / 36.0
        lat = (16.9023892 + 3.238272 * x - 0.270978 * y * y
               - 0.002528 * x * x - 0.0447 * y * y * x
               - 0.0140 * x ** 3) * 100.0 / 36.0
        return lon, lat
    lo = conv(e0, n0)
    hi = conv(e1, n1)
    return lo[0], lo[1], hi[0], hi[1]


def _pick_asset(item: dict, want_gsd: float) -> tuple | None:
    """The .tif COG asset closest to want_gsd. Returns (name, href, gsd)."""
    best = None
    for name, asset in item.get("assets", {}).items():
        if not name.endswith(".tif"):
            continue
        gsd = float(asset.get("eo:gsd", 0.0) or 0.0)
        score = abs(gsd - want_gsd)
        if best is None or score < best[0]:
            best = (score, name, asset["href"], gsd)
    return best[1:] if best else None


def _download(session, href: str, dest: str, dry: bool) -> int:
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return os.path.getsize(dest)
    head = session.head(href, timeout=60, allow_redirects=True)
    size = int(head.headers.get("Content-Length", 0))
    print(f"  GET {os.path.basename(dest)}  ({size / 1e6:.1f} MB)")
    if dry:
        return size
    tmp = dest + ".part"
    with session.get(href, stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    os.replace(tmp, dest)
    return os.path.getsize(dest)


def fetch_scene(scene_name: str, dry: bool) -> None:
    scene = SCENES[scene_name]
    e0, e1 = scene["e_km"]
    n0, n1 = scene["n_km"]
    root = os.path.join("data", "cinematic_raw", scene_name)
    os.makedirs(root, exist_ok=True)
    session = requests.Session()

    bbox = _lv95_to_wgs84_bbox(e0 * 1000, n0 * 1000, (e1 + 1) * 1000,
                               (n1 + 1) * 1000)
    manifest = {"scene": scene_name, "epsg": scene["epsg"],
                "e_km": [e0, e1], "n_km": [n0, n1],
                "attribution": scene["attribution"], "files": []}

    for kind, collection in COLLECTIONS.items():
        print(f"[{scene_name}] {kind}: querying {collection} ...")
        items = _stac_items(collection, bbox, session)
        # newest item per km tile (collections carry multiple survey years)
        per_tile: dict = {}
        for it in items:
            parts = it["id"].rsplit("_", 1)[-1]          # "2634-1159"
            try:
                e_km, n_km = (int(v) for v in parts.split("-"))
            except ValueError:
                continue
            if not (e0 <= e_km <= e1 and n0 <= n_km <= n1):
                continue
            prev = per_tile.get((e_km, n_km))
            if prev is None or it["properties"]["datetime"] > prev["properties"]["datetime"]:
                per_tile[(e_km, n_km)] = it
        print(f"  {len(per_tile)} tiles in scene rect")
        total = 0
        for (e_km, n_km), it in sorted(per_tile.items()):
            if kind == "ortho":
                want = 0.1 if (e_km, n_km) in scene["hires_tiles"] else 2.0
            else:
                want = 0.5
            picked = _pick_asset(it, want)
            if picked is None:
                print(f"  !! no tif asset for {it['id']}")
                continue
            name, href, gsd = picked
            dest = os.path.join(root, f"{kind}_{e_km}_{n_km}_{gsd:g}m.tif")
            for attempt in range(3):
                try:
                    total += _download(session, href, dest, dry)
                    break
                except Exception as exc:                     # noqa: BLE001
                    print(f"  retry {attempt + 1}: {exc}")
                    time.sleep(2.0 * (attempt + 1))
            manifest["files"].append(
                {"file": os.path.basename(dest), "kind": kind,
                 "collection": collection, "item": it["id"],
                 "gsd_m": gsd, "href": href})
        print(f"  {kind} total ~{total / 1e6:.0f} MB")

    # Surround ring: 2 m DTM + 2 m ortho for every km tile in the outer
    # rect that is NOT part of the core scene (cheap: ~1-3 MB per tile).
    if "surround_e_km" in scene:
        se0, se1 = scene["surround_e_km"]
        sn0, sn1 = scene["surround_n_km"]
        sbox = _lv95_to_wgs84_bbox(se0 * 1000, sn0 * 1000,
                                   (se1 + 1) * 1000, (sn1 + 1) * 1000)
        manifest["surround_e_km"] = [se0, se1]
        manifest["surround_n_km"] = [sn0, sn1]
        for kind, collection in (("sdtm", COLLECTIONS["dtm"]),
                                 ("sortho", COLLECTIONS["ortho"])):
            print(f"[{scene_name}] {kind}: querying {collection} "
                  f"(surround ring) ...")
            items = _stac_items(collection, sbox, session)
            per_tile = {}
            for it in items:
                parts = it["id"].rsplit("_", 1)[-1]
                try:
                    e_km, n_km = (int(v) for v in parts.split("-"))
                except ValueError:
                    continue
                if not (se0 <= e_km <= se1 and sn0 <= n_km <= sn1):
                    continue
                if e0 <= e_km <= e1 and n0 <= n_km <= n1:
                    continue                     # the core covers it
                prev = per_tile.get((e_km, n_km))
                if prev is None or (it["properties"]["datetime"]
                                    > prev["properties"]["datetime"]):
                    per_tile[(e_km, n_km)] = it
            print(f"  {len(per_tile)} ring tiles")
            total = 0
            for (e_km, n_km), it in sorted(per_tile.items()):
                picked = _pick_asset(it, 2.0)
                if picked is None:
                    continue
                name, href, gsd = picked
                dest = os.path.join(root,
                                    f"{kind}_{e_km}_{n_km}_{gsd:g}m.tif")
                for attempt in range(3):
                    try:
                        total += _download(session, href, dest, dry)
                        break
                    except Exception as exc:     # noqa: BLE001
                        print(f"  retry {attempt + 1}: {exc}")
                        time.sleep(2.0 * (attempt + 1))
                manifest["files"].append(
                    {"file": os.path.basename(dest), "kind": kind,
                     "collection": collection, "item": it["id"],
                     "gsd_m": gsd, "href": href})
            print(f"  {kind} total ~{total / 1e6:.0f} MB")

    if not dry:
        with open(os.path.join(root, "manifest.json"), "w",
                  encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        print(f"[{scene_name}] manifest written ({len(manifest['files'])} files)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scene", choices=sorted(SCENES), nargs="?",
                    default="lauterbrunnen")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    fetch_scene(args.scene, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
