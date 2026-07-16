"""GL-free coverage for cinematic tree classification and geometry."""

from __future__ import annotations

import numpy as np
from PIL import Image

from tools.bake_cinematic_trees import (
    classify_tree_cells,
    generate_tree_atlas,
    thin_tree_cells,
)
from world.cinematic_trees import build_tree_arrays


def test_classification_accepts_green_tall_cell_and_rejects_grey_roof():
    clutter = np.zeros((7, 7), dtype=np.float32)  # 5 x 5 plus halo
    clutter[2, 2] = 12.0                         # inner row/col 1: tree
    clutter[4, 4] = 10.0                         # inner row/col 3: roof
    clutter[3, 2] = 1.5                          # green, but too short

    rgb = np.full((5, 5, 3), (110, 110, 110), dtype=np.uint8)
    # Image rows are north-first; inner/LiDAR rows are south-first.
    rgb[5 - 1 - 1, 1] = (45, 100, 38)
    rgb[5 - 1 - 2, 1] = (40, 105, 35)
    image = Image.fromarray(rgb, mode="RGB")

    mask = classify_tree_cells(clutter, image)
    assert mask.shape == (5, 5)
    assert mask[1, 1]
    assert not mask[3, 3]
    assert not mask[2, 1]


def test_thinning_is_deterministic_spaced_and_capped():
    rows, cols = np.indices((40, 40), dtype=np.int32)
    rows = rows.ravel()
    cols = cols.ravel()
    heights = (4.0 + ((rows * 7 + cols * 11) % 31)).astype(np.float32)

    a_r, a_c = thin_tree_cells(rows, cols, heights,
                               max_count=50, min_spacing=4.0)
    order = np.random.default_rng(42).permutation(rows.size)
    b_r, b_c = thin_tree_cells(rows[order], cols[order], heights[order],
                               max_count=50, min_spacing=4.0)

    assert a_r.size <= 50
    assert a_r.tobytes() == b_r.tobytes()
    assert a_c.tobytes() == b_c.tobytes()
    points = np.stack((a_r, a_c), axis=1).astype(np.float32)
    delta = points[:, None, :] - points[None, :, :]
    dist2 = np.sum(delta * delta, axis=2)
    dist2 += np.eye(points.shape[0], dtype=np.float32) * 1e9
    assert float(dist2.min()) >= 16.0


def test_tree_arrays_have_crossed_quads_layout_uvs_and_base_anchor():
    x = np.array([10.0, 30.0], dtype=np.float32)
    z = np.array([20.0, 40.0], dtype=np.float32)
    base = np.array([3.0, 7.0], dtype=np.float32)
    height = np.array([12.0, 25.0], dtype=np.float32)
    radius = np.array([2.0, 4.0], dtype=np.float32)
    tint = np.array([[0.2, 0.4, 0.1], [0.3, 0.5, 0.2]], np.float32)
    species = np.array([0, 2], dtype=np.uint8)

    verts, indices = build_tree_arrays(
        x, z, base, height, radius, tint, species)
    assert verts.shape == (16, 8)
    assert verts.dtype == np.float32
    assert indices.shape == (24,)
    assert indices.dtype == np.uint32
    assert int(indices.max()) < len(verts)
    assert 0.0 <= float(verts[:, 3:5].min())
    assert float(verts[:, 3:5].max()) <= 1.0

    for i in range(2):
        tree = verts[i * 8:(i + 1) * 8]
        assert float(tree[:, 1].min()) == base[i]
        assert float(tree[:, 1].max()) == base[i] + height[i]
        assert np.allclose(tree[:, 5:8], tint[i])
        # Four east-west vertices and four north-south vertices.
        assert np.ptp(tree[:4, 0]) == 2.0 * radius[i]
        assert np.ptp(tree[4:, 2]) == 2.0 * radius[i]
        lo, hi = species[i] / 3.0, (species[i] + 1) / 3.0
        assert np.all((tree[:, 3] >= lo) & (tree[:, 3] <= hi))


def test_procedural_atlas_rgba_transparency_and_distinct_columns():
    atlas = generate_tree_atlas(seed=123)
    rgba = np.asarray(atlas)
    assert atlas.mode == "RGBA"
    assert rgba.shape == (512, 768, 4)
    assert np.all(rgba[0, (0, 255, 256, 511, 512, 767), 3] == 0)

    columns = np.split(rgba, 3, axis=1)
    assert all(np.count_nonzero(col[..., 3]) > 1000 for col in columns)
    fingerprints = [col.tobytes() for col in columns]
    assert len(set(fingerprints)) == 3


def test_scene_without_tree_bake_disables_gracefully(tmp_path):
    """A scene dir with no tree_atlas.png (Yosemite: no DSM, no trees)
    must construct disabled and draw as a no-op — entering the scene
    crashed with FileNotFoundError before this guard (user report)."""
    from world.cinematic_trees import CinematicTrees
    trees = CinematicTrees(str(tmp_path), tiles=[])
    assert trees.enabled is False
    assert trees.tiles == []
    trees.draw(renderer=None, camera=None, time=0.0)   # no GL touched
    trees.dispose()
