"""Procedural Boeing E-3 Sentry AWACS model.

Reference scale: 46.6 m long, 44.4 m span, with a 9.1 m x 1.8 m rotodome.
The E-3 is a modified Boeing 707 and therefore has a conventional low
horizontal tail, not a T-tail.  Forward = +Z, up = +Y; pure numpy/GL-free.
"""

from __future__ import annotations

import math

from engine.meshdata import (MeshBuilder, MeshData, make_box, make_cylinder,
                             make_fin, make_lathe)
from models.common import PALETTE, rot_z

_HALF_L = 23.3
_DOME_RADIUS = 4.55
_DOME_THICKNESS = 1.8
_SEG = 30

_GREY = PALETTE["aircraft_grey"]
_DARK = PALETTE["aircraft_dark"]
_WHITE = PALETTE["radar_white"]
_EXHAUST = PALETTE["exhaust_ring"]
_ROT_MIRROR = rot_z(math.pi)


def _main_wings(b: MeshBuilder) -> None:
    # Boeing 707 planform: strongly swept low wing.  The former 5 m sweep over
    # a 20 m semispan looked nearly straight from above.
    wing = make_fin(10.4, 2.8, 20.0, 10.4, 0.30, _GREY)
    b.add_mesh(wing, offset=(2.2, -0.62, 5.0))
    b.add_mesh(wing, rotation=_ROT_MIRROR, offset=(-2.2, -0.62, 5.0))


def _engine_pods(b: MeshBuilder) -> None:
    # Tapered TF33 nacelles with visible inlet and exhaust apertures.
    pod = [
        (-2.80, 0.42), (-2.48, 0.64), (-1.5, 0.72), (1.85, 0.74),
        (2.48, 0.56), (2.78, 0.22),
    ]
    for sx in (1.0, -1.0):
        for span_x in (6.2, 12.3):
            x = sx * span_x
            z = 5.0 - 10.4 * (span_x / 20.0)
            b.add_mesh(make_lathe(pod, 22, _GREY),
                       offset=(x, -2.25, z))
            b.add_mesh(make_cylinder(0.53, 0.16, 20, _DARK, axis="z",
                                     offset=(x, -2.25, z + 2.76)))
            b.add_mesh(make_cylinder(0.47, 0.22, 20, _EXHAUST, axis="z",
                                     offset=(x, -2.25, z - 2.76)))
            b.add_mesh(make_box((0.28, 1.08, 1.35), _GREY,
                                offset=(x, -1.38, z + 0.15)))


def _tail(b: MeshBuilder) -> None:
    # Upright single fin.  +90 degrees maps make_fin's +X span to +Y.
    vfin = make_fin(8.0, 3.2, 6.60, 3.05, 0.24, _GREY)
    b.add_mesh(vfin, rotation=rot_z(math.pi * 0.5),
               offset=(0.0, 1.55, -15.30))

    # Conventional 707 tailplane through the lower fin/fuselage junction.
    stabilizer = make_fin(6.2, 2.2, 8.0, 3.15, 0.22, _GREY)
    b.add_mesh(stabilizer, offset=(0.0, 1.35, -14.75))
    b.add_mesh(stabilizer, rotation=_ROT_MIRROR,
               offset=(0.0, 1.35, -14.75))


def _rotodome(b: MeshBuilder) -> None:
    centre_y = 5.40
    centre_z = -4.00

    # White saucer with the thin dark antenna-window band around its rim.
    b.add_mesh(make_cylinder(_DOME_RADIUS, _DOME_THICKNESS, 36, _WHITE,
                             axis="y", offset=(0.0, centre_y, centre_z)))
    b.add_mesh(make_cylinder(_DOME_RADIUS + 0.07, 0.44, 36,
                             PALETTE["radome"], axis="y",
                             offset=(0.0, centre_y, centre_z)))

    # Two fore/aft support pylons; daylight remains visible below the dome.
    base_y = 1.88
    top_y = centre_y - _DOME_THICKNESS * 0.5
    height = top_y - base_y
    for dz in (-2.35, 2.35):
        b.add_mesh(make_box((0.52, height, 0.62), _GREY,
                            offset=(0.0, base_y + height * 0.5,
                                    centre_z + dz)))


def build_awacs() -> MeshData:
    """Build the E-3 Sentry-class airborne warning aircraft."""
    b = MeshBuilder()

    fuselage = [
        (-_HALF_L, 0.0), (-21.0, 1.15), (-17.0, 1.62), (-10.0, 1.82),
        (-3.0, 1.90), (7.0, 1.90), (15.0, 1.80), (19.5, 1.53),
        (21.7, 1.02), (22.75, 0.48), (_HALF_L, 0.0),
    ]
    b.add_mesh(make_lathe(fuselage, _SEG, _GREY))
    b.add_mesh(make_lathe([(21.35, 1.13), (22.3, 0.72),
                           (22.9, 0.36), (_HALF_L, 0.0)],
                          _SEG, _DARK))

    # Four simple cockpit panes keep the nose readable without textures.
    for sx in (-1.0, 1.0):
        b.add_mesh(make_box((0.62, 0.44, 0.08), _DARK,
                            offset=(sx * 0.53, 0.83, 21.72)))

    _main_wings(b)
    _engine_pods(b)
    _tail(b)
    _rotodome(b)
    return b.build()
