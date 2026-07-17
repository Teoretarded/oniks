"""M orbit view contracts: the GL-free globe math.

The sphere is anchored so the scene's true lat/lon faces local +Y and
its surface touches sea level under the origin; lat/lon <-> local uses
the tangent-plane approximation (good to metres across the rings).
"""

from __future__ import annotations

import math

import numpy as np

from world.earth_globe import (
    EARTH_R,
    build_globe_arrays,
    geo_frame,
    geo_unit,
    latlon_to_local,
    local_to_latlon,
    lv95_to_wgs84,
    scene_latlon,
)


def test_scene_latlon_from_lv95():
    """Lauterbrunnen's origin lands on the real village."""
    lon, lat = lv95_to_wgs84(2636000.0, 1159000.0)
    assert abs(lat - 46.586) < 0.02
    assert abs(lon - 7.905) < 0.02
    lat2, lon2 = scene_latlon({"epsg": 2056, "origin_e": 2636000.0,
                               "origin_n": 1159000.0})
    assert (lat2, lon2) == (lat, lon)


def test_latlon_local_roundtrip():
    lat0, lon0 = 46.586, 7.905
    for x, z in ((0.0, 0.0), (25_000.0, -60_000.0), (-79_000.0, 79_000.0)):
        lat, lon = local_to_latlon(x, z, lat0, lon0)
        x2, z2 = latlon_to_local(lat, lon, lat0, lon0)
        assert math.hypot(x2 - x, z2 - z) < 1.0


def test_geo_frame_maps_anchor_up_east_north():
    lat0, lon0 = 46.586, 7.905
    m = geo_frame(lat0, lon0)
    up = m @ geo_unit(lat0, lon0)
    assert np.allclose(up, [0.0, 1.0, 0.0], atol=1e-9)
    # A point slightly north maps to +Z, slightly east to +X.
    n = m @ geo_unit(lat0 + 0.01, lon0)
    assert n[2] > 0.0 and abs(n[0]) < 1e-6
    e = m @ geo_unit(lat0, lon0 + 0.01)
    assert e[0] > 0.0
    # Orthonormal right-handed.
    assert np.allclose(m @ m.T, np.eye(3), atol=1e-12)
    assert np.linalg.det(m) > 0.99


def test_globe_arrays_touch_sea_level_under_the_origin():
    # The SHIPPED resolution: grid sag under the anchor must stay
    # sub-kilometre or the horizon floats visibly.
    verts, idx, center_y = build_globe_arrays(46.586, 7.905, 760.0)
    assert center_y == -(EARTH_R + 760.0)
    # The highest vertex is the anchor-facing pole of the rotated
    # sphere: surface = center + R = sea level in local frame.
    top = float(verts[:, 1].max())
    assert abs((center_y + top) - (-760.0)) < 600.0
    # UVs cover the map with row 0 = north.
    assert verts[:, 6].min() >= 0.0 and verts[:, 6].max() <= 1.0
    assert verts[:, 7].min() >= 0.0 and verts[:, 7].max() <= 1.0
    assert idx.max() < len(verts)
