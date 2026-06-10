import numpy as np
from world import generation as G

def test_deterministic():
    x = np.linspace(-300_000, 300_000, 500); z = np.linspace(-10_000, 550_000, 500)
    a = G.terrain_height(x, z); b = G.terrain_height(x, z)
    assert np.array_equal(a, b)

def test_base_on_land_and_high():
    h = G.terrain_height(np.array([G.BASE_POS[0]]), np.array([G.BASE_POS[2]]))[0]
    assert h > 30.0

def test_islands_have_land_and_ocean_between():
    for cx, cz, r, peak in G.ISLANDS:
        assert G.terrain_height(np.array([cx]), np.array([cz]))[0] > 20.0
    assert G.terrain_height(np.array([0.0]), np.array([150_000.0]))[0] < 0.0  # open ocean point

def test_lanes_stay_in_water():
    for lane in G.LANES:
        pts = np.array(lane)
        # sample densely along each segment
        for i in range(len(pts) - 1):
            t = np.linspace(0, 1, 50)[:, None]
            p = pts[i] * (1 - t) + pts[i+1] * t
            h = G.terrain_height(p[:, 0], p[:, 1])
            assert (h < -5.0).all(), f"lane {lane} touches land"

def test_sites_on_land():
    for s in G.SITES:
        h = G.terrain_height(np.array([s["pos"][0]]), np.array([s["pos"][1]]))[0]
        assert h > 5.0

def test_height_continuity():
    x = np.linspace(-50_000, 50_000, 2000); z = np.full(2000, 100_000.0)
    h = G.terrain_height(x, z)
    assert np.abs(np.diff(h)).max() < 30.0   # no cliffs from hashing artifacts at 50m sampling
