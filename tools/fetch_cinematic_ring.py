"""Fetch the map-EXPANSION rings for a cinematic scene (2026-07-17).

Two tiers beyond the existing core + 16 km surround
(docs/icbm_run_log_2026-07-17.md — user go: extend Lauterbrunnen by
80-150 km):

- R2 "alps ring": 64 x 64 km of swissALTI3D 2 m DTM + SWISSIMAGE 2 m
  ortho, per-km STAC tiles (~0.3-0.8 MB each, ~3-5 GB total), skipping
  every km tile the core/surround already covers.  Parallel, resumable
  (existing non-empty files are skipped), separate r2_manifest.json.
- R3 "horizon ring": Copernicus GLO-30 30 m DEM 1-degree COG tiles from
  the public AWS bucket (no auth), covering ~±80-100 km.  Attribution
  required: "produced using Copernicus WorldDEM-30 (c) DLR e.V. 2010-14
  and (c) Airbus Defence and Space GmbH, provided under COPERNICUS by
  the European Union and ESA".  The far ring renders with procedural
  alpine tint, so no far imagery is fetched.

Usage: python tools/fetch_cinematic_ring.py [lauterbrunnen] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.fetch_cinematic_data import (   # noqa: E402
    COLLECTIONS,
    SCENES,
    _lv95_to_wgs84_bbox,
    _pick_asset,
    _stac_items,
)

# R2 rect per scene: 64 x 64 km centred on the core (inclusive km tiles).
RINGS = {
    "lauterbrunnen": {
        "r2_e_km": (2603, 2666),
        "r2_n_km": (1127, 1190),
        # GLO-30 1-degree tiles: lat/lon lower-left corners, 3x3 around
        # 46.59N 7.91E (~±80-100 km with margin).
        "glo30": [(lat, lon) for lat in (45, 46, 47)
                  for lon in (6, 7, 8)],
    },
}

GLO30 = ("https://copernicus-dem-30m.s3.amazonaws.com/"
         "Copernicus_DSM_COG_10_N{lat:02d}_00_E{lon:03d}_00_DEM/"
         "Copernicus_DSM_COG_10_N{lat:02d}_00_E{lon:03d}_00_DEM.tif")
WORKERS = 8


def _download(session: requests.Session, href: str, dest: str,
              dry: bool) -> int:
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return os.path.getsize(dest)
    if dry:
        return 0
    tmp = dest + ".part"
    for attempt in range(4):
        try:
            with session.get(href, stream=True, timeout=600) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            os.replace(tmp, dest)
            return os.path.getsize(dest)
        except Exception as exc:                       # noqa: BLE001
            print(f"  retry {attempt + 1} {os.path.basename(dest)}: {exc}",
                  flush=True)
            time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"gave up on {href}")


def fetch_ring(scene_name: str, dry: bool) -> None:
    scene = SCENES[scene_name]
    ring = RINGS[scene_name]
    root = os.path.join("data", "cinematic_raw", scene_name)
    os.makedirs(root, exist_ok=True)
    session = requests.Session()

    re0, re1 = ring["r2_e_km"]
    rn0, rn1 = ring["r2_n_km"]
    # Everything the core + surround already fetched is excluded.
    se0, se1 = scene.get("surround_e_km", scene["e_km"])
    sn0, sn1 = scene.get("surround_n_km", scene["n_km"])
    bbox = _lv95_to_wgs84_bbox(re0 * 1000, rn0 * 1000,
                               (re1 + 1) * 1000, (rn1 + 1) * 1000)
    manifest = {"scene": scene_name, "r2_e_km": [re0, re1],
                "r2_n_km": [rn0, rn1], "files": [],
                "glo30_attribution":
                    "Far terrain: Copernicus WorldDEM-30 (c) DLR e.V. "
                    "2010-2014 and (c) Airbus Defence and Space GmbH, "
                    "provided under COPERNICUS by the EU and ESA"}

    for kind, collection in (("r2dtm", COLLECTIONS["dtm"]),
                             ("r2ortho", COLLECTIONS["ortho"])):
        print(f"[{scene_name}] {kind}: querying {collection} "
              f"(64 km ring, paginated) ...", flush=True)
        items = _stac_items(collection, bbox, session)
        per_tile: dict = {}
        for it in items:
            parts = it["id"].rsplit("_", 1)[-1]
            try:
                e_km, n_km = (int(v) for v in parts.split("-"))
            except ValueError:
                continue
            if not (re0 <= e_km <= re1 and rn0 <= n_km <= rn1):
                continue
            if se0 <= e_km <= se1 and sn0 <= n_km <= sn1:
                continue                       # core/surround covers it
            prev = per_tile.get((e_km, n_km))
            if prev is None or (it["properties"]["datetime"]
                                > prev["properties"]["datetime"]):
                per_tile[(e_km, n_km)] = it
        print(f"  {len(per_tile)} ring tiles", flush=True)

        jobs = []
        for (e_km, n_km), it in sorted(per_tile.items()):
            picked = _pick_asset(it, 2.0)
            if picked is None:
                continue
            _name, href, gsd = picked
            dest = os.path.join(root, f"{kind}_{e_km}_{n_km}_{gsd:g}m.tif")
            jobs.append((href, dest, gsd, it["id"]))
        total, done = 0, 0
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futs = {pool.submit(_download, session, href, dest, dry):
                    (dest, gsd, iid, href)
                    for href, dest, gsd, iid in jobs}
            for fut in as_completed(futs):
                dest, gsd, iid, href = futs[fut]
                try:
                    total += fut.result()
                except Exception as exc:               # noqa: BLE001
                    print(f"  !! {os.path.basename(dest)}: {exc}",
                          flush=True)
                    continue
                manifest["files"].append(
                    {"file": os.path.basename(dest), "kind": kind,
                     "gsd_m": gsd, "item": iid, "href": href})
                done += 1
                if done % 250 == 0:
                    print(f"  {done}/{len(jobs)} "
                          f"(~{total / 1e6:.0f} MB)", flush=True)
        print(f"  {kind}: {done}/{len(jobs)} files, ~{total / 1e6:.0f} MB",
              flush=True)

    glo_dir = os.path.join(root, "glo30")
    os.makedirs(glo_dir, exist_ok=True)
    for lat, lon in ring["glo30"]:
        href = GLO30.format(lat=lat, lon=lon)
        dest = os.path.join(glo_dir, os.path.basename(href))
        print(f"[glo30] {os.path.basename(dest)}", flush=True)
        try:
            _download(session, href, dest, dry)
            manifest["files"].append({"file": f"glo30/{os.path.basename(dest)}",
                                      "kind": "glo30", "gsd_m": 30.0,
                                      "href": href})
        except Exception as exc:                       # noqa: BLE001
            print(f"  !! glo30 {lat}/{lon}: {exc}", flush=True)

    if not dry:
        with open(os.path.join(root, "r2_manifest.json"), "w",
                  encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        print(f"[{scene_name}] r2_manifest.json written "
              f"({len(manifest['files'])} files)", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scene", choices=sorted(RINGS), nargs="?",
                    default="lauterbrunnen")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    fetch_ring(args.scene, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
