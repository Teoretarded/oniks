"""Dedicated procedural models for formerly invisible or proxy platforms.

These builders are intentionally GL-free and use the same metres/+Z-forward
convention as the rest of ``models``.  They cover the Buk TELAR, swarm launch
pod, counter-battery radar, emitter decoy, corner reflector, S-300 pad, and the
Project-636-style diesel submarine used by the simulation.
"""

from __future__ import annotations

import math

from engine.meshdata import (
    MeshBuilder,
    MeshData,
    make_box,
    make_cylinder,
    make_fin,
    make_lathe,
    make_wedge,
)
from models.common import PALETTE, rot_x, rot_z

_GREEN = PALETTE["mil_green"]
_GREEN_DARK = PALETTE["mil_green_dark"]
_TIRE = PALETTE["tire"]
_TUBE = PALETTE["tube_grey"]
_RADAR = PALETTE["radar_white"]
_METAL = PALETTE["pipe"]
_GLASS = PALETTE["aircraft_dark"]


# Six launch-mouth offsets shared by the procedural 9A317-style TELAR and the
# live Buk battery.  Keeping these model-authoritative prevents the renderer
# and launch simulation from drifting when the rack geometry changes.
BUK_CANISTER_ELEVATION = math.radians(24.0)
BUK_CANISTER_LENGTH = 5.0
BUK_MOUTH_CAP_DEPTH = 0.09
_BUK_TUBE_CENTERS = tuple(
    (x, y, -0.35 + row * 0.08 + column * 0.02)
    for row, y in enumerate((2.50, 3.02))
    for column, x in enumerate((-0.62, 0.0, 0.62))
)
_BUK_MOUTH_RUN = BUK_CANISTER_LENGTH * 0.5 + BUK_MOUTH_CAP_DEPTH
BUK_MOUTH_OFFSETS = tuple(
    (
        x,
        y + math.sin(BUK_CANISTER_ELEVATION) * _BUK_MOUTH_RUN,
        z + math.cos(BUK_CANISTER_ELEVATION) * _BUK_MOUTH_RUN,
    )
    for x, y, z in _BUK_TUBE_CENTERS
)


def _track(builder: MeshBuilder, side: float) -> None:
    x = side * 1.62
    builder.add_mesh(make_box((0.52, 0.82, 8.3), _TIRE,
                              offset=(x, 0.62, -0.15)))
    for z in (-3.15, -1.90, -0.65, 0.65, 1.90, 3.15):
        builder.add_mesh(make_cylinder(
            0.40, 0.58, 12, _GREEN_DARK, axis="x",
            offset=(side * 1.66, 0.61, z - 0.15)))
    for z in (-3.70, 3.65):
        builder.add_mesh(make_cylinder(
            0.48, 0.60, 12, _GREEN_DARK, axis="x",
            offset=(side * 1.66, 0.67, z - 0.15)))


def build_buk_telar() -> MeshData:
    """9A317-inspired tracked TELAR with six game-authoritative canisters."""

    builder = MeshBuilder()
    _track(builder, -1.0)
    _track(builder, 1.0)
    builder.add_mesh(make_box((3.15, 0.70, 8.25), _GREEN,
                              offset=(0.0, 1.18, -0.10)))
    builder.add_mesh(make_wedge((3.05, 1.55, 2.25), _GREEN,
                                offset=(0.0, 2.25, 3.00)))
    # Windscreen and small side windows identify the crew end at +Z.
    builder.add_mesh(make_box((2.15, 0.55, 0.10), _GLASS,
                              offset=(0.0, 2.55, 4.14)))
    for side in (-1.0, 1.0):
        builder.add_mesh(make_box((0.08, 0.45, 0.72), _GLASS,
                                  offset=(side * 1.53, 2.45, 3.05)))

    # Turret, six-canister pack, and hydraulic elevation cradle.
    builder.add_mesh(make_cylinder(1.25, 0.45, 16, _GREEN_DARK, axis="y",
                                   offset=(0.0, 1.78, -0.65)))
    builder.add_mesh(make_box((2.7, 0.30, 2.0), _GREEN_DARK,
                              offset=(0.0, 2.08, -0.55)))
    rotation = rot_x(-BUK_CANISTER_ELEVATION)
    axis = (
        0.0,
        math.sin(BUK_CANISTER_ELEVATION),
        math.cos(BUK_CANISTER_ELEVATION),
    )
    for center, mouth in zip(_BUK_TUBE_CENTERS, BUK_MOUTH_OFFSETS):
        builder.add_mesh(
            make_cylinder(0.22, BUK_CANISTER_LENGTH, 12, _TUBE, axis="z"),
            offset=center, rotation=rotation)
        # Cap centre sits one half-depth behind the actual launch mouth.
        cap_center = tuple(
            mouth[i] - axis[i] * BUK_MOUTH_CAP_DEPTH * 0.5
            for i in range(3)
        )
        builder.add_mesh(make_cylinder(
            0.235, BUK_MOUTH_CAP_DEPTH, 12, PALETTE["canvas_khaki"],
            axis="z"), offset=cap_center, rotation=rotation)

    # Vehicle-mounted 9S36-style rectangular phased-array panel.
    builder.add_mesh(make_box((0.30, 2.0, 0.30), _GREEN_DARK,
                              offset=(0.0, 3.15, 2.20)))
    builder.add_mesh(make_box((2.25, 1.35, 0.20), _RADAR,
                              offset=(0.0, 4.15, 2.23)))
    builder.add_mesh(make_box((1.85, 1.0, 0.08), (0.24, 0.27, 0.25),
                              offset=(0.0, 4.15, 2.10)))
    return builder.build()


def build_swarm_pod() -> MeshData:
    """Compact palletized twelve-cell loitering-munition launcher."""

    builder = MeshBuilder()
    builder.add_mesh(make_box((3.8, 0.24, 4.8), _GREEN_DARK,
                              offset=(0.0, 0.20, 0.0)))
    # Four levelling jacks and foot pads.
    for x in (-1.72, 1.72):
        for z in (-2.15, 2.15):
            builder.add_mesh(make_cylinder(0.10, 0.55, 8, _METAL, axis="y",
                                           offset=(x, 0.27, z)))
            builder.add_mesh(make_box((0.48, 0.08, 0.48), _METAL,
                                      offset=(x, 0.04, z)))
    # Rear control/power cabinet.
    builder.add_mesh(make_box((3.2, 1.45, 1.05), _GREEN,
                              offset=(0.0, 0.98, -1.72)))
    builder.add_mesh(make_box((2.65, 0.62, 0.06), _GLASS,
                              offset=(0.0, 1.12, -2.28)))

    # Four columns x three rows of rectangular launch cells, angled 12 deg.
    angle = math.radians(12.0)
    rotation = rot_x(-angle)
    for row, y in enumerate((0.72, 1.28, 1.84)):
        for x in (-1.23, -0.41, 0.41, 1.23):
            builder.add_mesh(make_box((0.66, 0.42, 3.05), _TUBE),
                             offset=(x, y, 0.40 + row * 0.04),
                             rotation=rotation)
            builder.add_mesh(make_box((0.57, 0.34, 0.06),
                                      PALETTE["canvas_khaki"]),
                             offset=(x,
                                     y + math.sin(angle) * 1.56,
                                     0.40 + row * 0.04
                                     + math.cos(angle) * 1.56),
                             rotation=rotation)
    return builder.build()


def _lattice_side(builder: MeshBuilder, x: float) -> None:
    # Two vertical rails and diagonal braces in the Y/Z plane.
    for z in (-0.72, 0.72):
        builder.add_mesh(make_box((0.12, 29.0, 0.12), _METAL,
                                  offset=(x, 16.0, z)))
    diagonal = math.hypot(3.0, 1.44)
    angle = math.atan2(3.0, 1.44)
    for y in range(3, 29, 3):
        # Rotate around the brace centre before placing it in the bay.  Baking
        # the offset into the child mesh would orbit the brace around the site.
        builder.add_mesh(make_box((0.12, 0.12, diagonal), _METAL),
                         offset=(x, float(y), 0.0),
                         rotation=rot_x(angle if y % 6 else -angle))


def build_cbr_radar() -> MeshData:
    """Tall counter-battery / missile-warning radar with a broad array."""

    builder = MeshBuilder()
    builder.add_mesh(make_box((7.5, 0.45, 7.5), PALETTE["concrete"],
                              offset=(0.0, 0.225, 0.0)))
    builder.add_mesh(make_box((5.4, 2.8, 4.2), _GREEN,
                              offset=(4.5, 1.4, -1.2)))
    for x in (-0.72, 0.72):
        _lattice_side(builder, x)
    # Cross braces on both X/Y faces.
    diagonal = math.hypot(3.0, 1.44)
    angle = math.atan2(3.0, 1.44)
    for z in (-0.72, 0.72):
        for y in range(3, 29, 3):
            builder.add_mesh(make_box((diagonal, 0.12, 0.12), _METAL),
                             offset=(0.0, float(y), z),
                             rotation=rot_z(angle if y % 6 else -angle))
    builder.add_mesh(make_cylinder(0.35, 2.0, 12, _METAL, axis="y",
                                   offset=(0.0, 31.0, 0.0)))
    builder.add_mesh(make_box((7.0, 3.5, 0.35), _RADAR,
                              offset=(0.0, 33.2, 0.0)))
    builder.add_mesh(make_box((6.35, 2.85, 0.10), (0.30, 0.34, 0.32),
                              offset=(0.0, 33.2, -0.23)))
    return builder.build()


def build_decoy_emitter() -> MeshData:
    """Soft 8 m emitter decoy: generator cabinet, mast, and fake panel."""

    builder = MeshBuilder()
    builder.add_mesh(make_box((2.5, 0.22, 2.5), _GREEN_DARK,
                              offset=(0.0, 0.11, 0.0)))
    builder.add_mesh(make_box((2.0, 1.65, 1.45), _GREEN,
                              offset=(0.0, 0.95, -0.45)))
    builder.add_mesh(make_box((1.45, 0.55, 0.06), _GLASS,
                              offset=(0.0, 1.05, -1.20)))
    builder.add_mesh(make_cylinder(0.11, 6.2, 8, _METAL, axis="y",
                                   offset=(0.0, 4.65, 0.42)))
    builder.add_mesh(make_box((1.9, 1.0, 0.12), _RADAR,
                              offset=(0.0, 7.55, 0.42)))
    builder.add_mesh(make_cylinder(0.05, 2.4, 6, _METAL, axis="x",
                                   offset=(0.0, 7.55, 0.32)))
    return builder.build()


def _trihedral(builder: MeshBuilder, offset) -> None:
    x, y, z = offset
    color = (0.76, 0.78, 0.76)
    builder.add_mesh(make_box((1.55, 0.06, 1.55), color,
                              offset=(x, y, z)))
    builder.add_mesh(make_box((0.06, 1.55, 1.55), color,
                              offset=(x - 0.75, y + 0.75, z)))
    builder.add_mesh(make_box((1.55, 1.55, 0.06), color,
                              offset=(x, y + 0.75, z - 0.75)))


def build_corner_reflector() -> MeshData:
    """Three ground-mounted trihedral radar reflectors within a 4 m cluster."""

    builder = MeshBuilder()
    builder.add_mesh(make_box((3.9, 0.12, 3.9), _GREEN_DARK,
                              offset=(0.0, 0.06, 0.0)))
    for offset in ((-0.85, 0.45, -0.65), (0.85, 0.45, -0.65),
                   (0.0, 1.65, 0.75)):
        _trihedral(builder, offset)
    for x in (-1.6, 1.6):
        builder.add_mesh(make_cylinder(0.07, 1.2, 6, _METAL, axis="y",
                                       offset=(x, 0.6, 1.55)))
    return builder.build()


def build_sam_pad() -> MeshData:
    """Concrete S-300 hardstand with painted safety box and cable channels."""

    builder = MeshBuilder()
    concrete = PALETTE["concrete"]
    yellow = (0.82, 0.66, 0.10)
    builder.add_mesh(make_box((24.0, 0.32, 24.0), concrete,
                              offset=(0.0, -0.16, 0.0)))
    for x in (-10.8, 10.8):
        builder.add_mesh(make_box((0.28, 0.05, 21.6), yellow,
                                  offset=(x, 0.025, 0.0)))
    for z in (-10.8, 10.8):
        builder.add_mesh(make_box((21.6, 0.05, 0.28), yellow,
                                  offset=(0.0, 0.025, z)))
    builder.add_mesh(make_box((0.28, 0.06, 18.0), _GREEN_DARK,
                              offset=(0.0, 0.03, -1.5)))
    return builder.build()


def build_submarine() -> MeshData:
    """Project-636/Kilo-inspired 73.8 x 9.9 m diesel-electric submarine."""

    builder = MeshBuilder()
    hull = (0.095, 0.105, 0.110)
    deck = (0.16, 0.18, 0.19)
    profile = [
        (-36.9, 0.18), (-34.0, 2.2), (-29.0, 4.2), (-21.0, 4.85),
        (17.0, 4.95), (26.0, 4.45), (33.0, 2.7), (36.9, 0.15),
    ]
    builder.add_mesh(make_lathe(profile, 32, hull, smooth=True))

    # Low rounded sail forward of midships.
    builder.add_mesh(make_box((3.8, 4.0, 9.5), deck,
                              offset=(0.0, 4.4, 5.0)))
    builder.add_mesh(make_wedge((3.8, 1.4, 9.5), deck,
                                offset=(0.0, 7.0, 5.0)))
    builder.add_mesh(make_box((3.1, 0.38, 7.2), (0.22, 0.24, 0.25),
                              offset=(0.0, 7.55, 4.8)))
    for x in (-0.45, 0.15, 0.65):
        builder.add_mesh(make_cylinder(0.09, 3.6, 8, _METAL, axis="y",
                                       offset=(x, 9.3, 5.5)))

    # Bow hydroplanes and cruciform stern control surfaces.
    plane = make_fin(4.0, 2.7, 4.0, 0.8, 0.18, deck)
    builder.add_mesh(plane, offset=(0.0, 0.0, 24.0))
    builder.add_mesh(plane, offset=(0.0, 0.0, 24.0),
                     rotation=rot_z(math.pi))
    stern = make_fin(5.0, 2.2, 4.2, 1.0, 0.22, deck)
    builder.add_mesh(stern, offset=(0.0, 0.0, -30.0))
    builder.add_mesh(stern, offset=(0.0, 0.0, -30.0),
                     rotation=rot_z(math.pi))
    builder.add_mesh(stern, offset=(0.0, 0.0, -30.0),
                     rotation=rot_z(math.pi * 0.5))
    builder.add_mesh(stern, offset=(0.0, 0.0, -30.0),
                     rotation=rot_z(-math.pi * 0.5))

    # Propeller hub and five blades.
    builder.add_mesh(make_cylinder(0.55, 1.1, 12, _METAL, axis="z",
                                   offset=(0.0, 0.0, -37.15)))
    blade = make_box((0.34, 3.8, 0.12), _METAL, offset=(0.0, 1.65, 0.0))
    for index in range(5):
        builder.add_mesh(blade, offset=(0.0, 0.0, -37.75),
                         rotation=rot_z(index * math.tau / 5.0))
    return builder.build()


__all__ = (
    "BUK_MOUTH_OFFSETS",
    "build_buk_telar",
    "build_cbr_radar",
    "build_corner_reflector",
    "build_decoy_emitter",
    "build_sam_pad",
    "build_submarine",
    "build_swarm_pod",
)
