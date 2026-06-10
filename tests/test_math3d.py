import numpy as np
from engine.math3d import (perspective, rotation_from_forward, compose,
                           view_rotation, heading_to_forward, forward_to_heading)

def test_heading_roundtrip():
    for h in [0.0, 0.5, np.pi/2, np.pi, -2.3]:
        f = heading_to_forward(h)
        assert np.allclose(f[1], 0.0)
        assert np.isclose(np.mod(forward_to_heading(f) - h + np.pi, 2*np.pi) - np.pi, 0.0, atol=1e-12)

def test_rotation_from_forward_orthonormal():
    R = rotation_from_forward(np.array([1.0, 2.0, 3.0]))
    assert np.allclose(R.T @ R, np.eye(3), atol=1e-12)
    assert np.isclose(np.linalg.det(R), 1.0, atol=1e-12)
    # model +Z maps to normalized forward
    assert np.allclose(R @ np.array([0,0,1.0]), np.array([1,2,3])/np.linalg.norm([1,2,3]), atol=1e-12)

def test_rotation_from_forward_vertical_fallback():
    R = rotation_from_forward(np.array([0.0, 1.0, 0.0]))
    assert np.allclose(R.T @ R, np.eye(3), atol=1e-9)

def test_compose_places_translation():
    M = compose(np.eye(3), np.array([10.0, 20.0, 30.0]))
    assert np.allclose(M[:3, 3], [10, 20, 30])
    assert np.allclose(M[3], [0, 0, 0, 1])

def test_perspective_maps_near_far():
    P = perspective(np.radians(60), 16/9, 1.0, 1000.0)
    near_clip = P @ np.array([0, 0, -1.0, 1.0])
    far_clip = P @ np.array([0, 0, -1000.0, 1.0])
    assert np.isclose(near_clip[2] / near_clip[3], -1.0)
    assert np.isclose(far_clip[2] / far_clip[3], 1.0)

def test_view_rotation_world_forward_maps_to_minus_z():
    f = np.array([0.0, 0.0, 1.0]); r = np.array([1.0, 0.0, 0.0]); u = np.array([0.0, 1.0, 0.0])
    V = view_rotation(r, u, f)
    v = V @ np.array([0, 0, 5.0, 1.0])   # point 5m north, camera facing north
    assert np.allclose(v[:3], [0, 0, -5.0])
