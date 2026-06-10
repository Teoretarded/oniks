"""Camera: float64 eye, basis vectors, view/proj matrices (pure numpy, GL-free).

The eye stays float64 ALWAYS. Rendering is camera-relative: callers take
``rel(pos)`` (float64 difference) and cast to float32 at the GPU boundary,
so there is zero jitter even 600 km from the origin.
"""

import numpy as np

from engine import math3d


class Camera:
    def __init__(self, fov_y_deg=62.0, near=0.5, far=900_000.0):
        self.fov_y = np.radians(fov_y_deg)
        self.near = float(near)
        self.far = float(far)
        self.eye = np.zeros(3, dtype=np.float64)  # float64 ALWAYS
        self.forward = np.array([0.0, 0.0, 1.0])
        self.up = np.array([0.0, 1.0, 0.0])

    def set_look(self, eye_f64, target_f64):
        """Place the eye and aim at target; recompute forward/right/up."""
        self.eye = np.asarray(eye_f64, dtype=np.float64).copy()
        self.set_orientation(np.asarray(target_f64, dtype=np.float64) - self.eye)

    def set_orientation(self, forward, up=(0, 1, 0)):
        """Set forward direction (re-orthonormalized against up hint)."""
        rot = math3d.rotation_from_forward(forward, up)
        self.forward = rot[:, 2]
        self.up = rot[:, 1]

    @property
    def right(self):
        return np.cross(self.up, self.forward)

    def view_rot(self) -> np.ndarray:
        """(4,4) rotation-only view matrix (eye at origin)."""
        return math3d.view_rotation(self.right, self.up, self.forward)

    def proj(self, aspect) -> np.ndarray:
        """(4,4) perspective projection matrix."""
        return math3d.perspective(self.fov_y, aspect, self.near, self.far)

    def rel(self, pos_f64) -> np.ndarray:
        """Camera-relative position: (pos - eye) in float64; caller casts f32."""
        return np.asarray(pos_f64, dtype=np.float64) - self.eye
