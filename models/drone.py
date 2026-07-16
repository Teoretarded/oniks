"""Procedural RQ-4 Global Hawk-class reconnaissance UAV.

Reference scale: 14.5 m long, 39.8/39.9 m span.  The model emphasizes the
Global Hawk's whale nose, extreme-aspect-ratio wing, dorsal single engine and
outward-canted V-tail.  Forward = +Z, up = +Y; pure numpy/GL-free.
"""

from __future__ import annotations

import math

from engine.meshdata import (MeshBuilder, MeshData, make_cylinder, make_fin,
                             make_lathe)
from models.common import PALETTE, rot_z

PALETTE.setdefault("drone_skin", (0.82, 0.83, 0.85))
PALETTE.setdefault("drone_dark", (0.36, 0.37, 0.40))

_SKIN = PALETTE["drone_skin"]
_DARK = PALETTE["drone_dark"]
_SEG = 28
_ROT_MIRROR = rot_z(math.pi)


def build_recon_drone() -> MeshData:
    """Build a dimensionally faithful RQ-4-class UAV mesh."""
    b = MeshBuilder()

    # Bulbous ISR nose tapering into a very slim aft boom.  The nose remains
    # airframe-coloured on the real aircraft; sensors sit behind the skin.
    fuselage = [
        (-7.25, 0.04), (-6.65, 0.18), (-5.3, 0.29), (-3.2, 0.40),
        (-0.5, 0.53), (2.0, 0.58), (3.5, 0.72), (4.8, 0.94),
        (5.8, 0.91), (6.55, 0.72), (7.05, 0.36), (7.25, 0.03),
    ]
    b.add_mesh(make_lathe(fuselage, _SEG, _SKIN))

    # Long, thin, mildly swept wing mounted through the upper fuselage.
    wing = make_fin(2.15, 0.82, 19.95, 1.55, 0.13, _SKIN)
    b.add_mesh(wing, offset=(0.0, 0.34, 1.55))
    b.add_mesh(wing, rotation=_ROT_MIRROR, offset=(0.0, 0.34, 1.55))

    # Correct V-tail geometry.  A +X fin rotated 90-cant degrees points up
    # and outboard; the previous rot_x composition leaned both fins fore/aft
    # and sent their span below the fuselage.
    tail = make_fin(2.30, 1.00, 3.00, 1.60, 0.12, _SKIN)
    cant = math.radians(35.0)
    b.add_mesh(tail, rotation=rot_z(math.pi * 0.5 - cant),
               offset=(0.18, 0.32, -4.65))
    b.add_mesh(tail, rotation=rot_z(math.pi * 0.5 + cant),
               offset=(-0.18, 0.32, -4.65))

    # Rounded dorsal engine nacelle.  It blends into the aft fuselage instead
    # of reading as the old rectangular rooftop box.
    engine = [
        (-1.85, 0.22), (-1.55, 0.39), (-0.9, 0.50), (0.75, 0.52),
        (1.25, 0.44), (1.55, 0.24), (1.65, 0.12),
    ]
    b.add_mesh(make_lathe(engine, 22, _SKIN),
               offset=(0.0, 0.76, -1.55))
    b.add_mesh(make_cylinder(0.38, 0.14, 18, _DARK, axis="z",
                             offset=(0.0, 0.76, 0.16)))
    b.add_mesh(make_cylinder(0.28, 0.16, 18, PALETTE["exhaust_ring"],
                             axis="z", offset=(0.0, 0.76, -3.46)))

    # Small ventral electro-optical/SAR fairing under the forward fuselage.
    sensor = [(-0.72, 0.0), (-0.48, 0.38), (0.0, 0.52),
              (0.48, 0.38), (0.72, 0.0)]
    b.add_mesh(make_lathe(sensor, 18, _DARK),
               offset=(0.0, -0.66, 4.55))

    return b.build()
