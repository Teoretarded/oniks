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


def test_home_coast_cliff_band():
    """S5 terrain pass: the shoreline rises into a real cliff band — ~45 m
    gained within 600 m inland of the waterline (locked: ~45 m over ~300 m
    after a short foreshore), everywhere along the home coast."""
    for x in (-150_000.0, -60_000.0, 0.0, 40_000.0, 120_000.0, 250_000.0):
        zs = np.arange(3_000.0, -1_200.0, -10.0)        # north -> south
        h = G.terrain_height(np.full_like(zs, x), zs)
        zw = zs[np.nonzero(h > 0.0)[0][0]]              # first land point
        rise = (G.terrain_height_scalar(x, zw - 600.0)
                - G.terrain_height_scalar(x, zw))
        assert rise > 38.0, f"no cliff band at x={x}: rise {rise:.1f} m"


def test_cliff_band_height_continuity():
    """The cliff band must stay comfortably under the 30 m anti-cliff step
    bound at 50 m sampling (the rise is ~45 m spread over ~300 m)."""
    for x in (-150_000.0, 0.0, 120_000.0):
        zs = np.arange(-2_000.0, 3_000.0, 50.0)
        h = G.terrain_height(np.full_like(zs, x), zs)
        assert np.abs(np.diff(h)).max() < 20.0

def test_terrain_never_exceeds_max_height_bound():
    """TERRAIN_MAX_HEIGHT is a strict upper bound (missiles above it skip
    ground-impact queries — Task 22 perf): sample the world densely plus
    every island peak neighborhood."""
    x = np.linspace(-340_000, 340_000, 900)
    z = np.linspace(-40_000, 560_000, 900)
    assert G.terrain_height(x[None, :], z[:, None]).max() < G.TERRAIN_MAX_HEIGHT
    for cx, cz, r, peak in G.ISLANDS:
        xs = np.linspace(cx - r, cx + r, 300)
        zs = np.linspace(cz - r, cz + r, 300)
        h = G.terrain_height(xs[None, :], zs[:, None])
        assert h.max() < G.TERRAIN_MAX_HEIGHT


def test_scalar_fast_path_bit_identical():
    """terrain_height_scalar (Task 22 perf fast path) must be bit-identical
    to the vectorized terrain_height everywhere: open ocean, coasts, island
    interiors/shores/skirts, deep shelf, land, and the exact mask edges its
    conservative skipping logic keys on."""
    rng = np.random.default_rng(22)
    xs = list(rng.uniform(-340_000.0, 340_000.0, 400))
    zs = list(rng.uniform(-40_000.0, 560_000.0, 400))
    # Hand-picked stress points: base, coast bands, shelf cutoffs, mid ocean.
    for x, z in [(0.0, -600.0), (0.0, 1_000.0), (0.0, 2_500.0),
                 (0.0, 14_500.0), (0.0, 14_499.9), (0.0, 150_000.0),
                 (0.0, 485_500.0), (0.0, 499_000.0), (0.0, 530_000.0),
                 (12_345.6, 200_000.0),
                 # cliff-band crossings (S5): foreshore, mid-rise, cliff top
                 (0.0, 300.0), (0.0, 0.0), (0.0, -150.0), (0.0, -450.0),
                 (40_000.0, 200.0), (40_000.0, -300.0), (0.0, 501_500.0)]:
        xs.append(x); zs.append(z)
    # Island center / shoreline / skirt / just-outside for every island.
    for cx, cz, r, _peak in G.ISLANDS:
        for d in (0.0, 0.5 * r, 0.999 * r, float(r), 1.001 * r, 1.8 * r):
            xs.append(cx + d); zs.append(cz)
            xs.append(cx); zs.append(cz - d)
    expect = G.terrain_height(np.array(xs), np.array(zs))
    for x, z, e in zip(xs, zs, expect):
        got = G.terrain_height_scalar(x, z)
        assert got == e, f"mismatch at ({x}, {z}): {got!r} != {e!r}"
