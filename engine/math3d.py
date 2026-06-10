"""Pure-numpy 3D math helpers: projection, rotation, compose.

Conventions (see plan LOCKED CONVENTIONS):
- Axes: X = east, Y = up, Z = north. Heading h (radians): 0 = +Z, clockwise from above.
- All matrices are (4,4) or (3,3) np.float64, standard math convention
  (translation in the last column, M @ v_col).
- Angles in radians.
"""

import numpy as np


def perspective(fov_y, aspect, near, far) -> np.ndarray:
    """Standard OpenGL perspective projection matrix, (4,4) float64."""
    f = 1.0 / np.tan(fov_y * 0.5)
    m = np.zeros((4, 4), dtype=np.float64)
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = (2.0 * far * near) / (near - far)
    m[3, 2] = -1.0
    return m


def rotation_from_forward(forward, up=(0, 1, 0)) -> np.ndarray:
    """(3,3) float64 rotation. Columns = object axes in world:
    col0=right, col1=up, col2=forward (model +Z maps to forward)."""
    f = np.asarray(forward, dtype=np.float64)
    f = f / np.linalg.norm(f)
    u = np.asarray(up, dtype=np.float64)
    r = np.cross(u, f)
    if np.linalg.norm(r) < 1e-9:  # looking straight up/down
        r = np.cross(np.array([0.0, 0.0, 1.0]), f)
    r = r / np.linalg.norm(r)
    u = np.cross(f, r)
    return np.column_stack((r, u, f))


def compose(rotation3x3, translation3, scale=1.0) -> np.ndarray:
    """(4,4) float64: rotation * scale in upper-left, translation in last column."""
    m = np.eye(4, dtype=np.float64)
    m[:3, :3] = np.asarray(rotation3x3, dtype=np.float64) * scale
    m[:3, 3] = np.asarray(translation3, dtype=np.float64)
    return m


def view_rotation(right, up, forward) -> np.ndarray:
    """(4,4) camera rotation-only view matrix: rows = right, up, -forward
    (OpenGL looks down -Z)."""
    m = np.eye(4, dtype=np.float64)
    m[0, :3] = np.asarray(right, dtype=np.float64)
    m[1, :3] = np.asarray(up, dtype=np.float64)
    m[2, :3] = -np.asarray(forward, dtype=np.float64)
    return m


def heading_to_forward(h) -> np.ndarray:
    """Unit forward vector for heading h: [sin h, 0, cos h]."""
    return np.array([np.sin(h), 0.0, np.cos(h)], dtype=np.float64)


def forward_to_heading(f) -> float:
    """Heading (radians) of forward vector f: atan2(f[0], f[2])."""
    return float(np.arctan2(f[0], f[2]))
