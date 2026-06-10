import numpy as np
from world.ocean import build_ocean_rings, RINGS
from world.terrain import build_feature_mesh

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
