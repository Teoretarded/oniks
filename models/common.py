"""Shared model-building helpers: the game-wide PALETTE + rotation matrices.

Pure numpy, GL-free. All builders work in model space (forward = +Z, up = +Y,
real meters) and return ``engine.meshdata.MeshData``.
"""

from __future__ import annotations

import math

import numpy as np

# Game-wide part colors (linear RGB). LOCKED by the plan — every model picks
# from here so the whole world shares one consistent look.
PALETTE = dict(
    missile_body=(0.82, 0.84, 0.86), radome=(0.16, 0.16, 0.18), fin=(0.55, 0.57, 0.60),
    booster=(0.70, 0.71, 0.72), exhaust_ring=(0.25, 0.22, 0.20),
    mil_green=(0.26, 0.31, 0.23), mil_green_dark=(0.20, 0.24, 0.18), tire=(0.10, 0.10, 0.11),
    cargo_hull=(0.48, 0.20, 0.16), cargo_deck=(0.62, 0.60, 0.55), container_a=(0.65, 0.25, 0.2),
    container_b=(0.22, 0.42, 0.55), container_c=(0.75, 0.65, 0.3),
    tanker_hull=(0.16, 0.17, 0.20), tanker_deck=(0.55, 0.30, 0.25), pipe=(0.7, 0.68, 0.6),
    warship_hull=(0.45, 0.49, 0.53), warship_deck=(0.38, 0.42, 0.46), superstructure=(0.55, 0.59, 0.63),
    haze_gray=(0.50, 0.53, 0.57), haze_gray_dark=(0.40, 0.43, 0.47), haze_gray_deck=(0.43, 0.46, 0.50),
    concrete=(0.58, 0.57, 0.54), radar_white=(0.85, 0.86, 0.84), tank_white=(0.80, 0.79, 0.75),
    s300_green=(0.30, 0.34, 0.26), tube_grey=(0.42, 0.44, 0.42),
    aircraft_grey=(0.58, 0.62, 0.68), aircraft_dark=(0.30, 0.33, 0.38),
    # Task OM2 reference builds (oniks_reference.md / s300_reference.md):
    # gull-grey/grey-green Oniks skin, body-toned wings a shade darker, the
    # DEEP BLACK intake annulus, the red tail cap accent; 5P85 tube clamp
    # rings and khaki canvas mouth covers.
    oniks_body=(0.70, 0.72, 0.67), oniks_wing=(0.63, 0.65, 0.60),
    intake_black=(0.04, 0.04, 0.05), tail_red=(0.55, 0.11, 0.09),
    tube_ring=(0.34, 0.37, 0.33), canvas_khaki=(0.47, 0.42, 0.30),
)


def rot_x(angle: float) -> np.ndarray:
    """(3,3) rotation about +X (right-handed: +Z tips toward -Y for angle>0)."""
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[1.0, 0.0, 0.0],
                     [0.0, c, -s],
                     [0.0, s, c]])


def rot_y(angle: float) -> np.ndarray:
    """(3,3) rotation about +Y (right-handed)."""
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, 0.0, s],
                     [0.0, 1.0, 0.0],
                     [-s, 0.0, c]])


def rot_z(angle: float) -> np.ndarray:
    """(3,3) rotation about +Z (right-handed: +X toward +Y for angle>0)."""
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, -s, 0.0],
                     [s, c, 0.0],
                     [0.0, 0.0, 1.0]])


def sphere_profile(radius: float, bands: int = 10) -> list[tuple[float, float]]:
    """(z, r) lathe profile for a full sphere of ``radius`` about the origin.

    Feed to ``make_lathe`` (which revolves around +Z); a sphere is symmetric,
    so the result works for any axis without rotation.
    """
    ts = np.linspace(math.pi, 0.0, bands + 1)
    return [(radius * math.cos(t), radius * math.sin(t)) for t in ts]
