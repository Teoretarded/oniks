import numpy as np
from engine.meshdata import (MeshBuilder, make_box, make_cylinder, make_lathe,
                             make_fin, make_grid)

def _check(md):
    assert md.vertices.dtype == np.float32 and md.indices.dtype == np.uint32
    assert md.indices.max() < len(md.vertices)
    assert np.isfinite(md.vertices).all()
    n = md.vertices[:, 3:6]
    assert np.allclose(np.linalg.norm(n, axis=1), 1.0, atol=1e-3)

def test_box():
    md = make_box((2, 4, 6), (1, 0, 0))
    _check(md)
    assert len(md.vertices) == 24 and len(md.indices) == 36
    assert np.allclose(md.vertices[:, :3].min(axis=0), [-1, -2, -3])
    assert np.allclose(md.vertices[:, :3].max(axis=0), [1, 2, 3])

def test_lathe_cone():
    md = make_lathe([(0.0, 1.0), (2.0, 0.0)], 16, (0.5, 0.5, 0.5))
    _check(md)
    assert np.isclose(md.vertices[:, 2].max(), 2.0)          # tip at z=2
    r = np.linalg.norm(md.vertices[:, :2], axis=1)
    assert r.max() <= 1.0 + 1e-5

def test_cylinder_axis_z():
    md = make_cylinder(0.5, 4.0, 12, (0, 1, 0))
    _check(md)
    assert np.isclose(md.vertices[:, 2].max(), 2.0)          # centered: z in [-2, 2]
    assert np.isclose(md.vertices[:, 2].min(), -2.0)

def test_builder_merge_and_transform():
    b = MeshBuilder()
    b.add_mesh(make_box((1, 1, 1), (1, 1, 1)))
    Rz90 = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1.0]])
    b.add_mesh(make_box((1, 1, 1), (1, 1, 1)), offset=(5, 0, 0), rotation=Rz90)
    md = b.build()
    _check(md)
    assert len(md.vertices) == 48 and len(md.indices) == 72
    assert md.vertices[:, 0].max() > 4.0

def test_grid_heightfield():
    xs = np.linspace(0, 10, 6); zs = np.linspace(0, 10, 5)
    h = np.zeros((5, 6)); h[2, 3] = 4.0
    c = np.ones((5, 6, 3), dtype=np.float32) * 0.5
    md = make_grid(xs, zs, h, c)
    _check(md)
    assert len(md.vertices) == 30 and len(md.indices) == 5 * 4 * 6  # (5-1)*(6-1)*2 tris * 3
