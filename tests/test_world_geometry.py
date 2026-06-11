import numpy as np
from world.ocean import build_ocean_rings, RINGS
from world.terrain import (build_feature_mesh, _catmull_rom_weights,
                           _mesh_from_heights, _sample_heights)

def test_ocean_rings_flat_and_finite():
    rings = build_ocean_rings()
    assert len(rings) == len(RINGS)
    for md in rings:
        assert np.isfinite(md.vertices).all()
        assert np.allclose(md.vertices[:, 1], 0.0)
    # inner disk fine, outer ring reaches 700 km
    assert np.linalg.norm(rings[-1].vertices[:, [0, 2]], axis=1).max() >= 690_000

def test_ocean_vertex_budget():
    total = sum(len(md.vertices) for md in build_ocean_rings())
    assert total < 400_000

def test_feature_mesh_island():
    md = build_feature_mesh((-38_000-20_000, -38_000+20_000, 95_000-20_000, 95_000+20_000), 300.0)
    assert md is not None
    assert md.vertices[:, 1].max() > 100.0       # island peak present
    assert md.vertices[:, 1].min() >= -4.01      # clamped

def test_terrain_color_mottling_and_brightening():
    """S5 terrain look: vertex colors carry noise-driven grass/scrub
    mottling, blended slope-rock exposure and height-based brightening —
    far more shades than the old 4 flat bands, all finite and in [0, 1]."""
    md = build_feature_mesh((-58_000.0, -18_000.0, 75_000.0, 115_000.0), 300.0)
    cols = md.vertices[:, 6:9]
    assert np.isfinite(cols).all()
    assert cols.min() >= 0.0 and cols.max() <= 1.0
    land = md.vertices[:, 1] > 8.0               # off the sand band
    uniq = np.unique(np.round(cols[land].astype(np.float64), 4), axis=0)
    assert len(uniq) > 200                       # old banding: exactly 4


def test_catmull_rom_weights_shape_and_partition_of_unity():
    n, f = 7, 5
    w = _catmull_rom_weights(n, f)
    # interior fine samples + 1 halo sample each side; coarse margin = 2
    assert w.shape == (n * f + 3, n + 5)
    assert np.allclose(w.sum(axis=1), 1.0)       # partition of unity

def test_catmull_rom_exact_at_knots_and_linear_precision():
    n, f = 6, 5
    w = _catmull_rom_weights(n, f)
    rng = np.random.default_rng(7)
    y = rng.standard_normal(n + 5)               # coarse samples at -2..n+2
    fine = w @ y
    knots = 1 + np.arange(n + 1) * f             # fine indices of knots 0..n
    assert np.allclose(fine[knots], y[2:2 + n + 1], atol=1e-12)
    # linear precision: a straight line is reproduced exactly everywhere
    coarse_x = np.arange(-2.0, n + 3.0)
    fine_x = (np.arange(n * f + 3) - 1.0) / f
    assert np.allclose(w @ (3.0 * coarse_x - 1.25), 3.0 * fine_x - 1.25)

def test_sample_heights_margin_extends_grid():
    rect = (-48_000.0, -28_000.0, 85_000.0, 105_000.0)
    cell = 500.0
    xs0, zs0, h0 = _sample_heights(rect, cell)
    xs2, zs2, h2 = _sample_heights(rect, cell, margin=2)
    assert len(xs2) == len(xs0) + 4 and len(zs2) == len(zs0) + 4
    assert np.allclose(np.diff(xs2), cell) and np.allclose(np.diff(zs2), cell)
    assert np.allclose(xs2[2:-2], xs0) and np.allclose(zs2[2:-2], zs0)
    assert np.allclose(h2[2:-2, 2:-2], h0)       # margin only adds, never shifts

def test_adjacent_tile_normals_and_colors_match_at_seam():
    # Two abutting tiles over island_0, built the way Terrain streams them
    # (sampling halo + float64 tile-centered re-centering): central-difference
    # normals and slope colors must agree exactly along the shared edge.
    cell = 300.0
    rect_a = (-47_000.0, -38_000.0, 90_000.0, 99_000.0)
    rect_b = (-38_000.0, -29_000.0, 90_000.0, 99_000.0)
    mds = []
    for rect in (rect_a, rect_b):
        xs, zs, h = _sample_heights(rect, cell, margin=2)
        center = (0.5 * (rect[0] + rect[1]), 0.5 * (rect[2] + rect[3]))
        mds.append(_mesh_from_heights(xs, zs, h, h_ref=220.0, margin=2,
                                      center=center))
    w = 31                                       # 9 km / 300 m + 1 per side
    va = mds[0].vertices.reshape(w, w, 9)
    vb = mds[1].vertices.reshape(w, w, 9)
    assert np.allclose(va[:, -1, 0], 4_500.0)    # tile-local x (recentered)
    assert np.allclose(vb[:, 0, 0], -4_500.0)
    assert np.array_equal(va[:, -1, 1], vb[:, 0, 1])    # heights
    assert np.allclose(va[:, -1, 3:6], vb[:, 0, 3:6], atol=1e-7)  # normals
    assert np.array_equal(va[:, -1, 6:9], vb[:, 0, 6:9])          # colors
