"""Fetch + bake a REAL-WORLD wind profile for a cinematic scene.

One year of hourly archived weather-model analyses (open-meteo.com
historical forecast API, CC-BY-4.0 — the plain ERA5 archive endpoint
does NOT serve pressure levels, verified 2026-07-16) at the scene's
true coordinates: 10 m / 100 m winds plus the pressure levels from the
valley floor to well above the summits.  The raw year is cached under
``data/cinematic_raw/wind/`` and distilled into
``assets/cinematic/<scene>/wind_profile.json`` — per-altitude, per-time-
of-day statistics (median + p90 speed, vector-prevailing direction) that
``world/cinematic_wind.py`` interpolates at runtime.

Physics-not-dice: the profile is MEASURED statistics, not invented
numbers; runtime gusts are a deterministic band-limited series scaled by
the measured p50->p90 spread ([[physics-not-dice]]).

Usage:
    python tools/fetch_cinematic_wind.py lauterbrunnen [yosemite ...]
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
import urllib.request

import numpy as np

RAW_DIR = os.path.join("data", "cinematic_raw", "wind")
SCENES_ROOT = os.path.join("assets", "cinematic")

# ERA5 pressure levels that bracket alpine scenes: ~110 m to ~5.6 km ASL.
PRESSURE_LEVELS = (1000, 950, 925, 900, 850, 800, 700, 600, 500)

# Time-of-day bands matched to the cinematic light moods (local hours).
# Every hour of the year lands in exactly one band.
MOOD_BANDS = {
    "night":   (22, 23, 0, 1, 2, 3, 4),
    "morning": (5, 6, 7, 8, 9),          # grey morning
    "day":     (10, 11, 12, 13, 14, 15, 16),   # alpine / noon
    "evening": (17, 18, 19, 20, 21),     # golden hour
}


# ------------------------------------------------------------ projections

def lv95_to_wgs84(e: float, n: float) -> tuple:
    """Swiss LV95 -> WGS84 (swisstopo approximate formulas, ~1 m)."""
    y = (e - 2_600_000.0) / 1_000_000.0
    x = (n - 1_200_000.0) / 1_000_000.0
    lon = (2.6779094 + 4.728982 * y + 0.791484 * y * x
           + 0.1306 * y * x * x - 0.0436 * y * y * y) * 100.0 / 36.0
    lat = (16.9023892 + 3.238272 * x - 0.270978 * y * y
           - 0.002528 * x * x - 0.0447 * y * y * x
           - 0.0140 * x * x * x) * 100.0 / 36.0
    return lat, lon


def utm_to_wgs84(e: float, n: float, zone: int) -> tuple:
    """UTM northern hemisphere -> WGS84 (standard series, ~1 m)."""
    a = 6378137.0
    f = 1.0 / 298.257222101          # GRS80 (NAD83)
    k0 = 0.9996
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    m = (n - 0.0) / k0
    mu = m / (a * (1 - e2 / 4 - 3 * e2 * e2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
           + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
           + (151 * e1 ** 3 / 96) * math.sin(6 * mu)
           + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    sp, cp = math.sin(phi), math.cos(phi)
    c1 = ep2 * cp * cp
    t1 = (sp / cp) ** 2
    n1 = a / math.sqrt(1 - e2 * sp * sp)
    r1 = a * (1 - e2) / (1 - e2 * sp * sp) ** 1.5
    d = (e - 500_000.0) / (n1 * k0)
    lat = phi - (n1 * sp / cp / r1) * (
        d * d / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * ep2) * d ** 4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * ep2
           - 3 * c1 * c1) * d ** 6 / 720)
    lon0 = math.radians((zone - 1) * 6 - 180 + 3)
    lon = lon0 + (d - (1 + 2 * t1 + c1) * d ** 3 / 6
                  + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * ep2
                     + 24 * t1 * t1) * d ** 5 / 120) / cp
    return math.degrees(lat), math.degrees(lon)


def scene_latlon(meta: dict) -> tuple:
    epsg = int(meta["epsg"])
    e, n = float(meta["origin_e"]), float(meta["origin_n"])
    if epsg == 2056:
        return lv95_to_wgs84(e, n)
    if 26901 <= epsg <= 26923:          # NAD83 UTM north zones
        return utm_to_wgs84(e, n, epsg - 26900)
    if 32601 <= epsg <= 32660:          # WGS84 UTM north zones
        return utm_to_wgs84(e, n, epsg - 32600)
    raise SystemExit(f"unsupported EPSG {epsg} — add a projection")


# ------------------------------------------------------------------ fetch

def _api_url(lat: float, lon: float, start: str, end: str) -> str:
    hourly = ["wind_speed_10m", "wind_direction_10m",
              "wind_speed_100m", "wind_direction_100m"]
    for p in PRESSURE_LEVELS:
        hourly += [f"wind_speed_{p}hPa", f"wind_direction_{p}hPa",
                   f"geopotential_height_{p}hPa"]
    return ("https://historical-forecast-api.open-meteo.com/v1/forecast"
            f"?latitude={lat:.4f}&longitude={lon:.4f}"
            f"&start_date={start}&end_date={end}"
            f"&hourly={','.join(hourly)}"
            "&wind_speed_unit=ms&timezone=auto")


def _quarters(start: str, end: str) -> list:
    """Split [start, end] into ~91-day chunks (keeps each request
    comfortably under the API limits)."""
    from datetime import date, timedelta
    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    out = []
    while s <= e:
        q_end = min(s + timedelta(days=90), e)
        out.append((s.isoformat(), q_end.isoformat()))
        s = q_end + timedelta(days=1)
    return out


def _fetch_chunk(name: str, lat: float, lon: float,
                 start: str, end: str) -> dict:
    cache = os.path.join(RAW_DIR, f"{name}_{start}_{end}.json")
    if os.path.isfile(cache):
        with open(cache, encoding="utf-8") as fh:
            return json.load(fh)
    url = _api_url(lat, lon, start, end)
    print(f"[wind] {name}: fetching {start}..{end}")
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=180) as resp:
                raw = json.load(resp)
            break
        except Exception as exc:        # noqa: BLE001 — retry then die loud
            if attempt == 3:
                raise
            print(f"[wind] retry {attempt + 1} after: {exc}")
            time.sleep(5.0 * (attempt + 1))
    if "hourly" not in raw:
        raise SystemExit(f"API answered without hourly data: {raw}")
    with open(cache, "w", encoding="utf-8") as fh:
        json.dump(raw, fh)
    print(f"[wind] {name}: cached {os.path.getsize(cache)/1e6:.1f} MB "
          f"({start}..{end})")
    return raw


def fetch_year(name: str, lat: float, lon: float,
               start: str, end: str) -> dict:
    """Concatenated quarterly chunks spanning [start, end]."""
    os.makedirs(RAW_DIR, exist_ok=True)
    chunks = [_fetch_chunk(name, lat, lon, s, e)
              for s, e in _quarters(start, end)]
    merged = chunks[0]
    for extra in chunks[1:]:
        for key, vals in extra["hourly"].items():
            if key in merged["hourly"]:
                merged["hourly"][key] = merged["hourly"][key] + vals
    return merged


# ---------------------------------------------------------------- distill

def _vector_stats(speed: np.ndarray, direction: np.ndarray) -> dict:
    """Per-level stats. Direction is meteorological (FROM, deg).

    u = eastward, v = northward component of the flow (TOWARD)."""
    ok = np.isfinite(speed) & np.isfinite(direction)
    speed, direction = speed[ok], direction[ok]
    if len(speed) == 0:
        return None
    rad = np.radians(direction)
    u = -speed * np.sin(rad)            # met convention: dir is FROM
    v = -speed * np.cos(rad)
    um, vm = float(u.mean()), float(v.mean())
    prevailing = (math.degrees(math.atan2(-um, -vm))) % 360.0
    return {
        "n": int(len(speed)),
        "speed_mean": round(float(speed.mean()), 3),
        "speed_p50": round(float(np.percentile(speed, 50)), 3),
        "speed_p90": round(float(np.percentile(speed, 90)), 3),
        "speed_p99": round(float(np.percentile(speed, 99)), 3),
        "dir_from_deg": round(prevailing, 1),
        "u_mean": round(um, 3),          # mean flow vector (TOWARD, m/s)
        "v_mean": round(vm, 3),
        # Mean resultant length: 1 = direction locked, 0 = no prevailing.
        "dir_steadiness": round(float(np.hypot(um, vm)
                                      / max(speed.mean(), 1e-9)), 3),
    }


def distill(raw: dict, name: str, lat: float, lon: float,
            start: str, end: str) -> dict:
    h = raw["hourly"]
    hours = np.array([int(t[11:13]) for t in h["time"]], dtype=np.int32)

    def col(key):
        vals = h.get(key)
        if vals is None:
            return np.full(len(h["time"]), np.nan)
        return np.array([np.nan if x is None else x for x in vals],
                        dtype=np.float64)

    levels = []
    # Surface-relative levels first: model 10 m / 100 m above ground.
    elev = float(raw.get("elevation", 0.0))
    for tag, agl in (("10m", 10.0), ("100m", 100.0)):
        spd, drc = col(f"wind_speed_{tag}"), col(f"wind_direction_{tag}")
        rec = {"level": tag, "alt_m_asl": round(elev + agl, 1),
               "all": _vector_stats(spd, drc)}
        for band, hrs in MOOD_BANDS.items():
            mask = np.isin(hours, hrs)
            rec[band] = _vector_stats(spd[mask], drc[mask])
        levels.append(rec)
    for p in PRESSURE_LEVELS:
        spd = col(f"wind_speed_{p}hPa")
        drc = col(f"wind_direction_{p}hPa")
        gph = col(f"geopotential_height_{p}hPa")
        alt = float(np.nanmean(gph)) if np.isfinite(gph).any() else None
        if alt is None:
            continue
        rec = {"level": f"{p}hPa", "alt_m_asl": round(alt, 1),
               "all": _vector_stats(spd, drc)}
        for band, hrs in MOOD_BANDS.items():
            mask = np.isin(hours, hrs)
            rec[band] = _vector_stats(spd[mask], drc[mask])
        levels.append(rec)
    levels = [rec for rec in levels if rec["all"] is not None]
    levels.sort(key=lambda r: r["alt_m_asl"])
    return {
        "name": name, "lat": round(lat, 4), "lon": round(lon, 4),
        "grid_elevation_m": elev,
        "period": [start, end],
        "hours": int(len(hours)),
        "source": ("ERA5 reanalysis (ECMWF) via open-meteo.com archive "
                   "API, CC-BY-4.0, hourly"),
        "bands": {k: list(v) for k, v in MOOD_BANDS.items()},
        "levels": levels,
    }


def valley_axis_deg(scene_dir: str) -> float | None:
    """Prevailing valley axis from the baked DTM: PCA of the valley-floor
    cell positions (cells within 180 m of the scene's low point).  Purely
    data-derived; returns None when the scene has no meaningful valley."""
    dtm_path = os.path.join(scene_dir, "dtm_1m.npy")
    if not os.path.isfile(dtm_path):
        return None
    d = np.load(dtm_path, mmap_mode="r")[::8, ::8].astype(np.float64)
    floor = d < (d.min() + 180.0)
    if floor.sum() < 64:
        return None
    zi, xi = np.nonzero(floor)
    pts = np.stack([xi - xi.mean(), zi - zi.mean()])
    cov = pts @ pts.T / pts.shape[1]
    evals, evecs = np.linalg.eigh(cov)
    ax = evecs[:, int(np.argmax(evals))]     # (x, z) grid = (east, north)
    ang = math.degrees(math.atan2(ax[0], ax[1])) % 180.0
    return round(ang, 1)


def main(argv: list) -> None:
    names = argv or ["lauterbrunnen", "yosemite"]
    # The most recent COMPLETE year (ERA5 publishes ~5 days behind).
    start, end = "2025-07-01", "2026-06-30"
    for name in names:
        scene_dir = os.path.join(SCENES_ROOT, name)
        with open(os.path.join(scene_dir, "scene.json"),
                  encoding="utf-8") as fh:
            meta = json.load(fh)
        lat, lon = scene_latlon(meta)
        print(f"[wind] {name}: {lat:.4f} N {lon:.4f} E")
        raw = fetch_year(name, lat, lon, start, end)
        profile = distill(raw, name, lat, lon, start, end)
        ax = valley_axis_deg(scene_dir)
        if ax is not None:
            profile["valley_axis_deg"] = ax
        out = os.path.join(scene_dir, "wind_profile.json")
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(profile, fh, indent=1)
        print(f"[wind] {name}: wrote {out} "
              f"({len(profile['levels'])} levels)")
        for rec in profile["levels"]:
            a = rec["all"]
            print(f"    {rec['level']:>8} {rec['alt_m_asl']:7.0f} m  "
                  f"p50 {a['speed_p50']:5.1f}  p90 {a['speed_p90']:5.1f} "
                  f"m/s  from {a['dir_from_deg']:5.1f} deg  "
                  f"steadiness {a['dir_steadiness']:.2f}")


if __name__ == "__main__":
    main(sys.argv[1:])
