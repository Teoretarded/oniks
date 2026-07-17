"""Fetch the M-globe Earth data: NASA Blue Marble Next Generation.

Public domain (NASA Visible Earth, credit "NASA Earth Observatory").
Downloads the 21600x10800 topo+bathy JPEG (~40 MB) and bakes two
GL-ready textures under assets/cinematic/earth/:

- earth_8k.jpg   (8192x4096)  — the globe skin
- earth_2k.jpg   (2048x1024)  — far/LEO mip seed + fallback

Resumable: existing non-empty outputs are kept.
Usage: python tools/fetch_cinematic_earth.py
"""

from __future__ import annotations

import io
import json
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OUT_DIR = os.path.join("assets", "cinematic", "earth")
RAW = os.path.join("data", "cinematic_raw", "earth")
# Candidate mirrors, most-wanted first (NASA renumbers imagerecords).
CANDIDATES = (
    "https://eoimages.gsfc.nasa.gov/images/imagerecords/73000/73909/"
    "world.topo.bathy.200412.3x21600x10800.jpg",
    "https://eoimages.gsfc.nasa.gov/images/imagerecords/74000/74418/"
    "world.200407.3x21600x10800.jpg",
    "https://eoimages.gsfc.nasa.gov/images/imagerecords/57000/57752/"
    "land_shallow_topo_21600.tif",
)
ATTRIBUTION = ("Earth imagery: NASA Earth Observatory Blue Marble "
               "Next Generation (public domain)")


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(RAW, exist_ok=True)
    out8 = os.path.join(OUT_DIR, "earth_8k.jpg")
    out2 = os.path.join(OUT_DIR, "earth_2k.jpg")
    meta = os.path.join(OUT_DIR, "earth.json")
    if (os.path.exists(out8) and os.path.getsize(out8) > 0
            and os.path.exists(out2)):
        print("earth textures already baked")
        return 0
    raw = None
    for url in CANDIDATES:
        dest = os.path.join(RAW, os.path.basename(url))
        if os.path.exists(dest) and os.path.getsize(dest) > 1_000_000:
            raw = dest
            break
        try:
            print(f"fetching {url}", flush=True)
            with requests.get(url, stream=True, timeout=900) as r:
                r.raise_for_status()
                tmp = dest + ".part"
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            os.replace(tmp, dest)
            raw = dest
            break
        except Exception as exc:                    # noqa: BLE001
            print(f"  !! {exc}", flush=True)
    if raw is None:
        print("no Blue Marble source reachable")
        return 1
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None                   # 233 MP source
    img = Image.open(raw).convert("RGB")
    print(f"source {img.size}", flush=True)
    img.resize((8192, 4096), Image.LANCZOS).save(out8, quality=88)
    img.resize((2048, 1024), Image.LANCZOS).save(out2, quality=88)
    with open(meta, "w", encoding="utf-8") as f:
        json.dump({"attribution": ATTRIBUTION,
                   "source": os.path.basename(raw)}, f, indent=1)
    print("baked earth_8k.jpg + earth_2k.jpg")
    return 0


if __name__ == "__main__":
    sys.exit(main())
