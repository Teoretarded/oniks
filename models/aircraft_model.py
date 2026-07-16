"""Procedural models for the sandbox patrol and fast aircraft.

The legacy dimensions are preserved because ``sim.aircraft`` uses them as
locked gameplay data.  The visual references are now explicit:

* patrol: Dassault/Breguet Atlantique 2-class, scaled to 30 x 35 m;
* fast: Sukhoi Su-35-class, scaled to 20 x 14 m.

Model space is real metres, forward = +Z, up = +Y, with the origin close to
the centre of mass.  Builders are pure numpy/GL-free and return ``MeshData``.
"""

from __future__ import annotations

import math

from engine.meshdata import (MeshBuilder, MeshData, make_box, make_cylinder,
                             make_fin, make_lathe)
from models.common import PALETTE, rot_z

_SEG = 28
_GREY = PALETTE["aircraft_grey"]
_DARK = PALETTE["aircraft_dark"]
_EXHAUST = PALETTE["exhaust_ring"]
_ROT_MIRROR = rot_z(math.pi)


def _mirrored_plate(builder: MeshBuilder, plate: MeshData,
                    offset: tuple[float, float, float]) -> None:
    """Add a +X plate and its -X mirror."""
    x, y, z = offset
    builder.add_mesh(plate, offset=(x, y, z))
    builder.add_mesh(plate, rotation=_ROT_MIRROR, offset=(-x, y, z))


def _add_propeller(builder: MeshBuilder, x: float, y: float, z: float) -> None:
    """Four-blade turboprop propeller and spinner, facing +Z."""
    blade = make_box((0.16, 3.35, 0.09), _DARK)
    for angle in (math.radians(45.0), math.radians(135.0)):
        builder.add_mesh(blade, rotation=rot_z(angle), offset=(x, y, z))
    builder.add_mesh(make_cylinder(0.28, 0.48, 16, _GREY, axis="z",
                                   offset=(x, y, z + 0.12)))


def build_patrol_aircraft() -> MeshData:
    """30 m x 35 m Atlantique-2-class maritime patrol aircraft.

    The high wing, twin turboprops, bilobed fuselage/weapon bay, glazed nose,
    ventral radar fairing and conventional tail are the primary recognition
    cues.  The exact legacy bounding length/span are retained.
    """
    b = MeshBuilder()

    # Pressurised upper lobe.  The slight upward offset leaves room for the
    # long lower weapons-bay lobe that defines the Atlantique side profile.
    upper = [
        (-15.0, 0.0), (-14.1, 0.42), (-12.2, 1.05), (-8.5, 1.38),
        (-2.0, 1.48), (5.0, 1.46), (9.5, 1.28), (12.7, 0.88),
        (13.8, 0.55),
    ]
    b.add_mesh(make_lathe(upper, _SEG, _GREY), offset=(0.0, 0.25, 0.0))

    # Lower lobe / weapons bay.  It overlaps the upper tube instead of
    # floating below it, producing the characteristic vertical oval section.
    lower = [
        (-10.5, 0.0), (-9.2, 0.55), (-6.5, 0.84), (4.5, 0.90),
        (8.0, 0.72), (10.2, 0.20), (10.5, 0.0),
    ]
    b.add_mesh(make_lathe(lower, 24, _GREY), offset=(0.0, -0.68, 0.0))

    # Glazed observation/radome nose.  It closes the upper fuselage at +15 m.
    nose = [(13.8, 0.55), (14.45, 0.42), (15.0, 0.0)]
    b.add_mesh(make_lathe(nose, _SEG, _DARK), offset=(0.0, 0.25, 0.0))

    # High, nearly straight high-aspect-ratio wing.
    wing = make_fin(5.0, 1.65, 16.3, 1.55, 0.30, _GREY)
    _mirrored_plate(b, wing, (1.2, 0.72, 3.35))

    # Conventional horizontal tail and the large single vertical tail.
    tail = make_fin(3.0, 1.05, 5.45, 1.15, 0.20, _GREY)
    _mirrored_plate(b, tail, (0.35, 0.58, -10.8))
    vfin = make_fin(4.0, 1.35, 4.35, 1.8, 0.22, _GREY)
    b.add_mesh(vfin, rotation=rot_z(math.pi * 0.5),
               offset=(0.0, 0.72, -11.0))

    # Twin Tyne-class turboprop nacelles integrated into the wing.
    nacelle = [
        (-2.15, 0.38), (-1.80, 0.62), (-0.8, 0.73), (1.45, 0.72),
        (2.00, 0.48), (2.28, 0.20),
    ]
    for sx in (1.0, -1.0):
        x = sx * 5.15
        b.add_mesh(make_lathe(nacelle, 22, _GREY),
                   offset=(x, 0.18, 2.72))
        # Dark annulus behind the spinner makes the intake readable head-on.
        b.add_mesh(make_cylinder(0.50, 0.16, 18, _DARK, axis="z",
                                 offset=(x, 0.18, 4.95)))
        _add_propeller(b, x, 0.18, 5.18)

    # Search radar fairing under the forward weapons-bay lobe.
    b.add_mesh(make_cylinder(0.62, 0.34, 20, _DARK, axis="y",
                             offset=(0.0, -1.63, 2.4)))
    return b.build()


def build_fast_aircraft() -> MeshData:
    """20 m x 14 m Su-35-class fast aircraft.

    This replaces the old single-nozzle, single-tail missile silhouette with
    a blended twin-engine airframe, broad LERX, twin canted fins and large
    all-moving stabilators while preserving the legacy footprint.
    """
    b = MeshBuilder()

    # Slender forward fuselage.  It terminates ahead of the nozzles so the
    # two aft nacelles, rather than a needle tail, own the rear silhouette.
    fuselage = [
        (-7.2, 0.34), (-5.6, 0.64), (-2.0, 0.78), (2.8, 0.76),
        (6.0, 0.62), (8.2, 0.42), (9.35, 0.18), (10.0, 0.0),
    ]
    b.add_mesh(make_lathe(fuselage, _SEG, _GREY))
    b.add_mesh(make_lathe([(8.15, 0.43), (9.35, 0.18), (10.0, 0.0)],
                          _SEG, _DARK))

    # Long leading-edge root extensions blend the narrow nose into the wing.
    lerx = make_fin(5.0, 2.15, 2.25, 2.35, 0.24, _GREY)
    _mirrored_plate(b, lerx, (0.52, -0.10, 4.15))

    wing = make_fin(5.25, 1.15, 6.15, 2.65, 0.28, _GREY)
    _mirrored_plate(b, wing, (0.85, -0.18, 1.75))

    # Separate engine tunnels and exhausts.
    nacelle = [
        (-3.30, 0.42), (-2.95, 0.61), (1.9, 0.65), (2.7, 0.56),
        (3.0, 0.42),
    ]
    for sx in (1.0, -1.0):
        x = sx * 0.98
        b.add_mesh(make_lathe(nacelle, 22, _GREY),
                   offset=(x, -0.22, -6.70))
        b.add_mesh(make_cylinder(0.50, 0.34, 20, _EXHAUST, axis="z",
                                 offset=(x, -0.22, -9.83)))
        # Rectangular side intake under each LERX.
        b.add_mesh(make_box((0.72, 0.66, 0.16), _DARK,
                            offset=(sx * 0.98, -0.30, 0.95)))

    # Bubble canopy (a small raised lathe, not a rectangular block).
    canopy = [(-1.65, 0.0), (-1.25, 0.38), (0.55, 0.48),
              (1.25, 0.32), (1.55, 0.0)]
    b.add_mesh(make_lathe(canopy, 18, _DARK), offset=(0.0, 0.72, 4.35))

    # Large stabilators.
    stab = make_fin(3.35, 0.85, 3.5, 1.75, 0.22, _GREY)
    _mirrored_plate(b, stab, (0.72, -0.18, -5.25))

    # Twin fins canted 18 degrees outboard.  A fin starts with span +X; a
    # rotation of 90-cant degrees points its span up and out on the right.
    fin = make_fin(3.35, 1.10, 3.10, 1.65, 0.24, _GREY)
    cant = math.radians(18.0)
    b.add_mesh(fin, rotation=rot_z(math.pi * 0.5 - cant),
               offset=(0.92, 0.38, -5.55))
    b.add_mesh(fin, rotation=rot_z(math.pi * 0.5 + cant),
               offset=(-0.92, 0.38, -5.55))

    return b.build()
