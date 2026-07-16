"""Procedural F/A-18E/F Super Hornet airframe.

Reference scale: 18.5 m long and 13.68 m span (model nominal 18.3 x 13.6).
The mesh is designed to read correctly from plan, side, front and rear views:
large LEX shoulders, rectangular side intakes, separated twin engines,
outward-canted twin tails and all-moving stabilators.  Forward = +Z, up = +Y.
"""

from __future__ import annotations

import math

from engine.meshdata import (MeshBuilder, MeshData, make_box, make_cylinder,
                             make_fin, make_lathe)
from models.common import PALETTE, rot_z

_GREY = PALETTE["aircraft_grey"]
_DARK = PALETTE["aircraft_dark"]
_EXHAUST = PALETTE["exhaust_ring"]
_SEG = 26
_ROT_MIRROR = rot_z(math.pi)


def _mirrored_plate(builder: MeshBuilder, plate: MeshData,
                    offset: tuple[float, float, float]) -> None:
    x, y, z = offset
    builder.add_mesh(plate, offset=(x, y, z))
    builder.add_mesh(plate, rotation=_ROT_MIRROR, offset=(-x, y, z))


def _add_lex_and_wings(b: MeshBuilder) -> None:
    # The LEX begins beside the cockpit and broadens into the wing root.  The
    # old placement began behind the wing, losing the defining plan silhouette.
    lex = make_fin(5.45, 2.55, 2.25, 2.70, 0.22, _GREY)
    _mirrored_plate(b, lex, (0.52, -0.08, 4.55))

    wing = make_fin(5.05, 1.35, 5.90, 2.70, 0.30, _GREY)
    _mirrored_plate(b, wing, (0.90, -0.15, 1.75))

    # Empty wingtip launch rails remain part of the vehicle when stores are
    # omitted.  They stay inside the nominal 13.6 m span.
    for sx in (1.0, -1.0):
        b.add_mesh(make_box((0.14, 0.14, 1.55), _GREY,
                            offset=(sx * 6.70, -0.16, -1.55)))


def _add_tail(b: MeshBuilder) -> None:
    stabilator = make_fin(3.25, 0.82, 3.35, 1.65, 0.24, _GREY)
    _mirrored_plate(b, stabilator, (0.78, -0.25, -4.95))

    # A make_fin span begins along +X.  Rotating by 90-cant degrees gives an
    # up/outboard span.  The former rot_x composition pointed the fins below
    # the belly and leaned them fore/aft instead of outboard.
    fin = make_fin(3.35, 1.05, 3.20, 1.75, 0.26, _GREY)
    cant = math.radians(27.0)
    b.add_mesh(fin, rotation=rot_z(math.pi * 0.5 - cant),
               offset=(1.05, 0.34, -5.00))
    b.add_mesh(fin, rotation=rot_z(math.pi * 0.5 + cant),
               offset=(-1.05, 0.34, -5.00))


def _add_engines_and_intakes(b: MeshBuilder) -> None:
    # Tapered F414 nacelles own the rear silhouette; the centre fuselage ends
    # ahead of them, avoiding the old single rocket-like tail point.
    nacelle = [
        (-2.70, 0.46), (-2.35, 0.59), (1.55, 0.62),
        (2.05, 0.54), (2.20, 0.42),
    ]
    for sx in (1.0, -1.0):
        x = sx * 0.95
        b.add_mesh(make_lathe(nacelle, 22, _GREY),
                   offset=(x, -0.20, -6.45))
        b.add_mesh(make_cylinder(0.50, 0.40, 22, _EXHAUST, axis="z",
                                 offset=(x, -0.20, -8.95)))

        # Super Hornet's rectangular, outward-canted-looking inlet openings.
        b.add_mesh(make_box((0.78, 0.68, 0.14), _DARK,
                            offset=(sx * 1.05, -0.28, 1.82)))
        # Short intake trunk keeps a 45-degree view from seeing a black card.
        b.add_mesh(make_box((0.82, 0.76, 1.55), _GREY,
                            offset=(sx * 1.05, -0.27, 1.05)))


def _add_canopy(b: MeshBuilder, two_seat: bool) -> None:
    if two_seat:
        profile = [(-2.05, 0.0), (-1.70, 0.37), (0.85, 0.54),
                   (1.45, 0.31), (1.70, 0.0)]
        centre_z = 4.00
    else:
        profile = [(-1.38, 0.0), (-1.05, 0.38), (0.62, 0.52),
                   (1.10, 0.29), (1.30, 0.0)]
        centre_z = 4.35
    b.add_mesh(make_lathe(profile, 20, _DARK),
               offset=(0.0, 0.72, centre_z))

    if two_seat:
        # Canopy bow separating the tandem cockpits on the F/EA airframe.
        b.add_mesh(make_box((1.02, 0.08, 0.10), _GREY,
                            offset=(0.0, 1.16, 3.65)))


def _build_fighter_airframe(two_seat: bool = False) -> MeshData:
    """Private shared E/F airframe used by the fighter and Growler builders."""
    b = MeshBuilder()

    # Narrow nose/forward fuselage, ending before the separated exhausts.
    fuselage = [
        (-7.15, 0.32), (-5.7, 0.58), (-2.2, 0.76), (2.5, 0.79),
        (5.2, 0.70), (7.25, 0.48), (8.45, 0.25), (9.15, 0.0),
    ]
    b.add_mesh(make_lathe(fuselage, _SEG, _GREY))
    b.add_mesh(make_lathe([(7.20, 0.49), (8.45, 0.25), (9.15, 0.0)],
                          _SEG, _DARK))

    # Broad centrebody between the two intake/engine tunnels.
    b.add_mesh(make_box((2.55, 0.62, 6.10), _GREY,
                        offset=(0.0, -0.12, -1.55)))

    _add_lex_and_wings(b)
    _add_engines_and_intakes(b)
    _add_tail(b)
    _add_canopy(b, two_seat)
    return b.build()


def build_fighter() -> MeshData:
    """Build the single-seat F/A-18E-class fighter mesh."""
    return _build_fighter_airframe(two_seat=False)
