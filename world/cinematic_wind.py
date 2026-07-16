"""Altitude-dependent wind for cinematic scenes, from MEASURED data.

``tools/fetch_cinematic_wind.py`` bakes a year of hourly reanalysis into
``wind_profile.json`` per scene: per-altitude, per-time-of-day statistics
(median + p90 speed, prevailing direction, steadiness).  This module is
the GL-free runtime half: it interpolates that profile over height so a
smoke column feels the light thermally-driven valley wind at the pad and
the hard westerlies above the ridgeline — measurably different layers,
exactly what the real Lauterbrunnen data shows (~1 m/s at the floor,
~12 m/s median at 5.6 km).

Physics-not-dice ([[physics-not-dice]]): everything here is measured
statistics plus a DETERMINISTIC band-limited gust series (incommensurate
sines seeded by the scene name) — same second, same wind, every run.

Axes are the engine's LOCKED frame: X east, Y up, Z north; the profile's
u/v (east/north) map straight onto X/Z.  Scene Y is origin-relative:
ASL = y + origin_alt.
"""

from __future__ import annotations

import json
import math
import os
import zlib

import numpy as np

# Fallback when a scene has no baked profile: the old hand-tuned light
# valley breeze (kept so tests and unbaked scenes behave as before).
FALLBACK_WIND = np.array([2.4, 0.0, 1.0], dtype=np.float32)

# Light-mood id -> profile time-of-day band.
BAND_FOR_MOOD = {"noon": "day", "alpine": "day", "golden": "evening",
                 "grey": "morning", "night": "night"}

_TWO_PI = 2.0 * math.pi


class WindProfile:
    """Interpolates a baked wind profile over scene height.

    ``wind_field(ys, t)`` is the vectorized pool hook ((n,) scene heights
    -> (n, 3) float32 m/s); ``wind_at(y, t)`` is the scalar emission
    helper.  ``set_band`` switches the time-of-day statistics with the
    light mood (grey morning is calm drainage flow; noon rides the
    up-valley thermal wind)."""

    CHANNEL_MAX = 0.7        # how hard the valley kills crosswind at floor

    def __init__(self, profile: dict, origin_alt: float,
                 floor_y: float = 0.0, ridge_y: float | None = None):
        self.profile = profile
        self.origin_alt = float(origin_alt)
        self.floor_y = float(floor_y)
        self.ridge_y = (float(ridge_y) if ridge_y is not None
                        else self.floor_y + 1400.0)
        axis = profile.get("valley_axis_deg")
        if axis is not None:
            a = math.radians(float(axis))
            self._axis = np.array([math.sin(a), math.cos(a)])   # (x, z)
        else:
            self._axis = None
        seed = zlib.crc32(str(profile.get("name", "scene")).encode())
        rng = np.random.default_rng(seed)        # fixed per scene: phases
        self._phase = rng.uniform(0.0, _TWO_PI, 6)
        self._bands = {}
        self.band = "day"
        self._prep_bands()

    # ----------------------------------------------------------- loading

    @classmethod
    def load(cls, scene_dir: str, origin_alt: float,
             floor_y: float = 0.0,
             ridge_y: float | None = None) -> "WindProfile | None":
        path = os.path.join(scene_dir, "wind_profile.json")
        if not os.path.isfile(path):
            return None
        try:
            with open(path, encoding="utf-8") as fh:
                profile = json.load(fh)
        except (OSError, ValueError):
            return None
        if not profile.get("levels"):
            return None
        return cls(profile, origin_alt, floor_y=floor_y, ridge_y=ridge_y)

    def _prep_bands(self) -> None:
        """Per band: sorted scene-height tables of (u, v, gust ratio,
        direction wobble) ready for np.interp."""
        for band in ("all", "night", "morning", "day", "evening"):
            ys, us, vs, r90, wob = [], [], [], [], []
            for rec in self.profile["levels"]:
                st = rec.get(band) or rec.get("all")
                if st is None:
                    continue
                y = float(rec["alt_m_asl"]) - self.origin_alt
                um, vm = float(st["u_mean"]), float(st["v_mean"])
                mag = math.hypot(um, vm)
                p50 = float(st["speed_p50"])
                p90 = float(st["speed_p90"])
                if mag > 1e-6:
                    u, v = um / mag * p50, vm / mag * p50
                else:
                    u = v = 0.0
                ys.append(y)
                us.append(u)
                vs.append(v)
                r90.append(p90 / max(p50, 0.1))
                # Unsteady direction (steadiness -> 0) wobbles further.
                wob.append((1.0 - float(st["dir_steadiness"])) * 0.9)
            order = np.argsort(ys)
            self._bands[band] = tuple(
                np.asarray(arr, dtype=np.float64)[order]
                for arr in (ys, us, vs, r90, wob))
        if self.band not in self._bands:
            self.band = "all"

    def set_band(self, band: str) -> None:
        if band in self._bands:
            self.band = band

    def set_mood(self, mood_id: str) -> None:
        self.set_band(BAND_FOR_MOOD.get(mood_id, "day"))

    # ---------------------------------------------------------- sampling

    def _gust01(self, t: float) -> float:
        """Deterministic 0..1 gustiness series (periods ~47/11/4 s)."""
        p = self._phase
        s = (0.55 * math.sin(_TWO_PI * t / 47.0 + p[0])
             + 0.33 * math.sin(_TWO_PI * t / 11.3 + p[1])
             + 0.12 * math.sin(_TWO_PI * t / 3.7 + p[2]))
        return 0.5 + 0.5 * max(-1.0, min(1.0, s))

    def _wobble01(self, t: float) -> float:
        """Deterministic -1..1 direction wobble series (slow)."""
        p = self._phase
        return (0.7 * math.sin(_TWO_PI * t / 83.0 + p[3])
                + 0.3 * math.sin(_TWO_PI * t / 19.0 + p[4]))

    def wind_field(self, ys: np.ndarray, t: float) -> np.ndarray:
        """(n,) scene heights -> (n, 3) float32 wind vectors at time t."""
        tab_y, tab_u, tab_v, tab_r, tab_w = self._bands[self.band]
        ys = np.asarray(ys, dtype=np.float64)
        u = np.interp(ys, tab_y, tab_u)
        v = np.interp(ys, tab_y, tab_v)
        # Measured gust band: speed breathes between p50 and p90.
        g = self._gust01(t)
        gain = 1.0 + (np.interp(ys, tab_y, tab_r) - 1.0) * g
        u *= gain
        v *= gain
        # Direction wobble, strongest where the year showed no prevailing
        # direction (valley thermals), calm where the westerlies are locked.
        theta = np.interp(ys, tab_y, tab_w) * self._wobble01(t)
        ct, st = np.cos(theta), np.sin(theta)
        u, v = u * ct - v * st, u * st + v * ct
        if self._axis is not None:
            # Valley channeling: below the ridgeline the crosswind dies
            # and flow follows the trench (fades out by ridge height).
            chan = np.clip((self.ridge_y - ys)
                           / max(self.ridge_y - self.floor_y, 1.0),
                           0.0, 1.0) * self.CHANNEL_MAX
            ax, az = self._axis
            along = u * ax + v * az
            u = along * ax + (u - along * ax) * (1.0 - chan)
            v = along * az + (v - along * az) * (1.0 - chan)
        out = np.zeros((len(ys), 3), dtype=np.float32)
        out[:, 0] = u
        out[:, 2] = v
        return out

    def wind_at(self, y: float, t: float) -> np.ndarray:
        """Scalar helper for emission code: (3,) float64 wind at height."""
        return self.wind_field(np.array([float(y)]), t)[0] \
            .astype(np.float64)


def ridge_floor_from_scene(scene) -> tuple:
    """(floor_y, ridge_y) estimated from the scene's own height data:
    floor = 5th percentile of the core bare earth, ridge = 80th
    percentile of the widest field available (surround if baked)."""
    core = np.asarray(scene._dtm[::4, ::4], dtype=np.float64)
    floor_y = float(np.percentile(core, 5.0))
    field = getattr(scene, "_sur", None)
    if field is not None:
        vals = field[np.isfinite(field)]
        ridge_y = float(np.percentile(vals, 80.0))
    else:
        ridge_y = float(np.percentile(core, 80.0))
    if ridge_y - floor_y < 200.0:            # flat scene: no channeling
        ridge_y = floor_y + 200.0
    return floor_y, ridge_y
