import numpy as np
from engine.camera import Camera

def test_rel_subtracts_in_float64():
    c = Camera(); c.eye = np.array([500_000.0, 10.0, 500_000.0])
    r = c.rel(np.array([500_000.5, 10.0, 500_000.25]))
    assert r.dtype == np.float64
    assert np.allclose(r, [0.5, 0.0, 0.25], atol=1e-9)   # would fail in float32

def test_set_look_basis():
    c = Camera()
    c.set_look(np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 10.0]))
    assert np.allclose(c.forward, [0, 0, 1])
    assert np.allclose(c.right, [1, 0, 0])
    V = c.view_rot()
    assert np.allclose((V @ np.array([0, 0, 1.0, 0]))[:3], [0, 0, -1], atol=1e-12)
