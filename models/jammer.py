"""Procedural EA-18G Growler escort-jammer model.

The Growler uses the two-seat F/A-18F airframe and adds three ALQ-99-class
jamming pods plus the ALQ-218 wingtip receiver fairings.  Stores are limited
to EW equipment: missiles and ammunition are intentionally omitted.
"""

from __future__ import annotations

import math

from engine.meshdata import (MeshBuilder, MeshData, make_box, make_cylinder,
                             make_lathe)
from models.common import PALETTE, rot_z
from models.fighter import _build_fighter_airframe

_POD = PALETTE["jammer_pod"]
_DARK = PALETTE["aircraft_dark"]
_GREY = PALETTE["aircraft_grey"]
_SEG = 18


def _alq99_pod(b: MeshBuilder, x: float, y: float, z: float,
               length: float, radius: float, pylon_to_y: float) -> None:
    """Add one tapered ALQ-99-class pod and its nose RAT."""
    half = length * 0.5
    profile = [
        (-half, 0.0), (-half + 0.32, radius * 0.72),
        (-half + 0.80, radius), (half - 0.58, radius),
        (half - 0.18, radius * 0.66), (half, radius * 0.30),
    ]
    b.add_mesh(make_lathe(profile, _SEG, _POD), offset=(x, y, z))

    rat_z = z + half + 0.16
    b.add_mesh(make_cylinder(radius * 0.34, 0.34, 14, _DARK, axis="z",
                             offset=(x, y, rat_z)))
    # Crossed blades make the ram-air turbine identifiable in a head-on shot.
    blade = make_box((0.055, radius * 1.45, 0.035), _DARK)
    b.add_mesh(blade, offset=(x, y, rat_z + 0.19))
    b.add_mesh(blade, rotation=rot_z(math.pi * 0.5),
               offset=(x, y, rat_z + 0.19))

    top_y = y + radius
    strut_h = pylon_to_y - top_y
    if strut_h > 0.0:
        b.add_mesh(make_box((0.20, strut_h, 0.95), _GREY,
                            offset=(x, top_y + strut_h * 0.5, z - 0.15)))


def _wingtip_receiver(b: MeshBuilder, x: float, y: float, z: float) -> None:
    """Tapered ALQ-218 wingtip receiver fairing."""
    profile = [(-1.05, 0.0), (-0.78, 0.15), (0.58, 0.19),
               (0.90, 0.12), (1.05, 0.0)]
    b.add_mesh(make_lathe(profile, 14, _POD), offset=(x, y, z))
    b.add_mesh(make_cylinder(0.105, 0.22, 12, _DARK, axis="z",
                             offset=(x, y, z + 0.91)))


def build_jammer() -> MeshData:
    """Build the two-seat EA-18G airframe and electronic-attack kit."""
    b = MeshBuilder()
    b.add_mesh(_build_fighter_airframe(two_seat=True))

    # Two wing pods and one centreline pod: the characteristic legacy
    # three-ALQ-99 configuration documented by the U.S. Navy.
    for sx in (1.0, -1.0):
        _alq99_pod(b, x=sx * 2.95, y=-0.96, z=-0.25,
                   length=3.75, radius=0.34, pylon_to_y=-0.15)
    _alq99_pod(b, x=0.0, y=-1.10, z=-0.55,
               length=4.10, radius=0.35, pylon_to_y=-0.72)

    for sx in (1.0, -1.0):
        _wingtip_receiver(b, x=sx * 6.75, y=-0.16, z=-1.45)

    # Small leading-edge receiver fairings reinforce the Growler identity at
    # 45-degree views without adding weapon stores.
    for sx in (1.0, -1.0):
        b.add_mesh(make_box((0.28, 0.16, 0.62), _POD,
                            offset=(sx * 2.05, -0.04, 1.78)))

    return b.build()
