"""Camera controllers. Task 9 ships FreeCam only; the cinematic suite
(chase/orbit/target/launcher + CameraRig transitions) arrives in Task 17.

Pure numpy state — GL-free, unit-testable headless.
"""

from __future__ import annotations

import numpy as np

# Free-cam speed tiers (m/s): base / SHIFT (x40) / CTRL+SHIFT (x400).
FREE_SPEEDS = (60.0, 2_400.0, 24_000.0)
MOUSE_SENS = 0.0028                 # radians per mouse pixel
_PITCH_LIMIT = np.radians(89.0)     # stay short of the poles (basis degenerates)
_UP = np.array([0.0, 1.0, 0.0])


class FreeCam:
    """Free-flying camera: float64 position + yaw/pitch orientation.

    Yaw follows the LOCKED heading convention (0 = +Z north, increasing
    clockwise seen from above); pitch is radians above the horizon.
    """

    def __init__(self, pos, yaw: float = 0.0, pitch: float = 0.0):
        self.pos = np.asarray(pos, dtype=np.float64).copy()
        self.yaw = float(yaw)
        self.pitch = float(pitch)

    def look(self, dx_px: float, dy_px: float) -> None:
        """Apply mouse motion in pixels: drag right turns right (clockwise),
        drag down pitches down."""
        self.yaw += dx_px * MOUSE_SENS
        self.pitch = float(np.clip(self.pitch - dy_px * MOUSE_SENS,
                                   -_PITCH_LIMIT, _PITCH_LIMIT))

    @property
    def forward(self) -> np.ndarray:
        cp = np.cos(self.pitch)
        return np.array([np.sin(self.yaw) * cp,
                         np.sin(self.pitch),
                         np.cos(self.yaw) * cp])

    @property
    def right(self) -> np.ndarray:
        """Horizontal right vector (east when facing north)."""
        return np.array([np.cos(self.yaw), 0.0, -np.sin(self.yaw)])

    def move(self, dt: float, fwd: float, strafe: float, lift: float,
             speed: float) -> None:
        """Translate: ``fwd`` along the view direction, ``strafe`` along the
        horizontal right vector, ``lift`` along world up. Axis inputs are
        -1/0/+1; the combined direction is normalized so diagonals are not
        faster."""
        v = self.forward * fwd + self.right * strafe + _UP * lift
        n = float(np.linalg.norm(v))
        if n > 1e-9:
            self.pos += v * (speed * dt / n)

    def apply(self, camera) -> None:
        """Write position/orientation into an engine Camera (float64 eye)."""
        camera.eye = self.pos.copy()
        camera.set_orientation(self.forward)
