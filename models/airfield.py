"""Detailed procedural military airfield at real-world scale.

The model follows the game's +Z forward / +Y up convention.  It remains a
single GL-free ``MeshData`` asset, but now carries the visual language needed
to read as an operating airfield from both low and overhead cameras: asphalt
pavement, FAA-style white runway markings, yellow taxi guidance, connectors,
aprons, edge lights, gabled hangars, doors, roof equipment, and a control
tower.  The authoritative gameplay footprint remains 2,500 x 205 metres.
"""

from __future__ import annotations

import math

from engine.meshdata import MeshBuilder, MeshData, make_box, make_cylinder
from models.common import PALETTE, rot_z

# Real dimensions (metres).
_RUNWAY_LEN = 2500.0
_RUNWAY_W = 45.0
_PAVEMENT_H = 0.36
_TAXI_W = 18.0
_TAXI_OFFSET = 80.0
_MARK_H = 0.045

# Materials are deliberately high-contrast because the field is normally seen
# from several kilometres away.  All values are linear RGB like PALETTE.
_ASPHALT = (0.135, 0.145, 0.150)
_TAXI_ASPHALT = (0.165, 0.175, 0.180)
_APRON = (0.265, 0.270, 0.270)
_WHITE = (0.88, 0.88, 0.82)
_YELLOW = (0.86, 0.69, 0.12)
_BLUE_LIGHT = (0.10, 0.34, 0.72)
_CONCRETE = PALETTE["concrete"]
_GLASS = PALETTE["aircraft_dark"]
_ROOF = PALETTE["container_b"]


def _flat_box(builder: MeshBuilder, size_xz, color, x: float, z: float,
              y: float = _PAVEMENT_H + _MARK_H * 0.5) -> None:
    builder.add_mesh(make_box((size_xz[0], _MARK_H, size_xz[1]), color,
                              offset=(x, y, z)))


def _digit(builder: MeshBuilder, digit: str, x: float, z: float,
           flip: bool = False) -> None:
    """Build one block-style runway numeral from seven flat segments."""

    segments = {
        "0": "abcedf", "1": "bc", "2": "abged", "3": "abgcd",
        "4": "fgbc", "5": "afgcd", "6": "afgecd", "7": "abc",
        "8": "abcdefg", "9": "abfgcd",
    }[digit]
    # centres in the X/Z plane; horizontal bars are 5.5 x 1.0 m and
    # vertical bars are 1.0 x 5.5 m.
    definitions = {
        "a": ((0.0, 6.5), (5.5, 1.0)),
        "g": ((0.0, 0.0), (5.5, 1.0)),
        "d": ((0.0, -6.5), (5.5, 1.0)),
        "f": ((-3.0, 3.25), (1.0, 5.5)),
        "b": ((3.0, 3.25), (1.0, 5.5)),
        "e": ((-3.0, -3.25), (1.0, 5.5)),
        "c": ((3.0, -3.25), (1.0, 5.5)),
    }
    for name in segments:
        (sx, sz), size = definitions[name]
        if flip:
            sx, sz = -sx, -sz
        _flat_box(builder, size, _WHITE, x + sx, z + sz)


def _runway_markings(builder: MeshBuilder) -> None:
    # Edge stripes.
    for x in (-_RUNWAY_W * 0.5 + 0.55, _RUNWAY_W * 0.5 - 0.55):
        _flat_box(builder, (0.75, _RUNWAY_LEN - 6.0), _WHITE, x, 0.0)

    # Dashed centreline: 30 m paint / 30 m gap.
    for z in range(-1140, 1141, 60):
        _flat_box(builder, (0.75, 30.0), _WHITE, 0.0, float(z))

    # Threshold bars, aiming points, and touchdown-zone pairs at both ends.
    threshold_xs = tuple(-16.2 + index * 3.6 for index in range(10))
    for sign in (-1.0, 1.0):
        for x in threshold_xs:
            _flat_box(builder, (1.7, 30.0), _WHITE, x,
                      sign * (_RUNWAY_LEN * 0.5 - 28.0))
        _flat_box(builder, (5.5, 38.0), _WHITE, -8.0,
                  sign * (_RUNWAY_LEN * 0.5 - 300.0))
        _flat_box(builder, (5.5, 38.0), _WHITE, 8.0,
                  sign * (_RUNWAY_LEN * 0.5 - 300.0))
        for distance, length in ((150.0, 20.0), (450.0, 16.0),
                                 (600.0, 12.0)):
            z = sign * (_RUNWAY_LEN * 0.5 - distance)
            _flat_box(builder, (3.0, length), _WHITE, -9.0, z)
            _flat_box(builder, (3.0, length), _WHITE, 9.0, z)

    # Reciprocal runway designations.  They are geometric, so they remain
    # legible without textures or a font atlas.
    _digit(builder, "1", -5.0, 1110.0, flip=True)
    _digit(builder, "8", 5.0, 1110.0, flip=True)
    _digit(builder, "3", -5.0, -1110.0)
    _digit(builder, "6", 5.0, -1110.0)


def _runway(builder: MeshBuilder) -> None:
    builder.add_mesh(make_box((_RUNWAY_W, _PAVEMENT_H, _RUNWAY_LEN),
                              _ASPHALT,
                              offset=(0.0, _PAVEMENT_H * 0.5, 0.0)))
    _runway_markings(builder)

    # Raised runway edge lamps; 100 m spacing reads cleanly at long range.
    for z in range(-1200, 1201, 100):
        for x in (-23.7, 23.7):
            builder.add_mesh(make_cylinder(
                0.15, 0.50, 6, _WHITE, axis="y",
                offset=(x, _PAVEMENT_H + 0.25, float(z))))


def _taxiway_and_aprons(builder: MeshBuilder) -> None:
    builder.add_mesh(make_box((_TAXI_W, _PAVEMENT_H, _RUNWAY_LEN),
                              _TAXI_ASPHALT,
                              offset=(_TAXI_OFFSET, _PAVEMENT_H * 0.5, 0.0)))
    _flat_box(builder, (0.30, _RUNWAY_LEN - 12.0), _YELLOW,
              _TAXI_OFFSET, 0.0)

    # Three runway connectors with continuous taxi centreline guidance.
    connector_x = (_RUNWAY_W * 0.5 +
                   (_TAXI_OFFSET - _TAXI_W * 0.5)) * 0.5
    connector_w = (_TAXI_OFFSET - _TAXI_W * 0.5) - _RUNWAY_W * 0.5
    for z in (-650.0, 0.0, 650.0):
        builder.add_mesh(make_box(
            (connector_w, _PAVEMENT_H, _TAXI_W), _TAXI_ASPHALT,
            offset=(connector_x, _PAVEMENT_H * 0.5, z)))
        _flat_box(builder, (connector_w, 0.30), _YELLOW, connector_x, z)

    # Blue edge lights along the parallel taxiway.
    for z in range(-1200, 1201, 160):
        for x in (_TAXI_OFFSET - _TAXI_W * 0.5 - 0.8,
                  _TAXI_OFFSET + _TAXI_W * 0.5 + 0.8):
            builder.add_mesh(make_cylinder(
                0.13, 0.36, 6, _BLUE_LIGHT, axis="y",
                offset=(x, _PAVEMENT_H + 0.18, float(z))))

    # Aprons sit beneath each hangar and connect directly to the taxiway.
    for z in (-600.0, 0.0, 600.0):
        builder.add_mesh(make_box(
            (78.0, _PAVEMENT_H, 92.0), _APRON,
            offset=(126.0, _PAVEMENT_H * 0.5 + 0.01, z)))
        _flat_box(builder, (37.0, 0.25), _YELLOW, 107.5, z,
                  y=_PAVEMENT_H + _MARK_H * 0.5 + 0.02)


def _hangars(builder: MeshBuilder) -> None:
    wall_h = 13.0
    width = 68.0
    depth = 48.0
    roof_rise = 5.0
    angle = math.atan2(roof_rise, width * 0.5)
    slope_len = math.hypot(width * 0.5, roof_rise)
    for z in (-600.0, 0.0, 600.0):
        x = 128.0
        builder.add_mesh(make_box((width, wall_h, depth), _CONCRETE,
                                  offset=(x, wall_h * 0.5, z)))
        # Two pitched steel roof planes with a ridge along Z.
        roof = make_box((slope_len, 0.72, depth + 1.5), _ROOF)
        builder.add_mesh(roof, offset=(x - width * 0.25,
                                      wall_h + roof_rise * 0.5, z),
                         rotation=rot_z(angle))
        builder.add_mesh(roof, offset=(x + width * 0.25,
                                      wall_h + roof_rise * 0.5, z),
                         rotation=rot_z(-angle))

        # Dark multi-panel door faces the taxiway; pale vertical seams keep it
        # from reading as a single solid cube.
        door_x = x - width * 0.5 - 0.04
        builder.add_mesh(make_box((0.18, 9.5, 34.0), _GLASS,
                                  offset=(door_x, 4.75, z)))
        for dz in (-11.3, 0.0, 11.3):
            builder.add_mesh(make_box((0.22, 9.6, 0.20), _CONCRETE,
                                      offset=(door_x - 0.04, 4.8, z + dz)))
        # Roof vents / exhaust cowls.
        for dz in (-12.0, 12.0):
            builder.add_mesh(make_cylinder(
                0.55, 1.3, 8, PALETTE["pipe"], axis="y",
                offset=(x, wall_h + roof_rise + 0.65, z + dz)))


def _tower(builder: MeshBuilder) -> None:
    x, z = 174.0, 210.0
    builder.add_mesh(make_box((5.5, 27.0, 5.5), _CONCRETE,
                              offset=(x, 13.5, z)))
    builder.add_mesh(make_box((7.0, 7.0, 7.0), _CONCRETE,
                              offset=(x, 30.5, z)))
    # Four dark glazed faces represented as a full cab with a pale floor/roof.
    builder.add_mesh(make_box((10.0, 4.2, 10.0), _GLASS,
                              offset=(x, 36.1, z)))
    builder.add_mesh(make_box((11.5, 0.55, 11.5), _CONCRETE,
                              offset=(x, 33.8, z)))
    builder.add_mesh(make_box((11.5, 0.65, 11.5), _ROOF,
                              offset=(x, 38.5, z)))
    builder.add_mesh(make_cylinder(0.18, 8.0, 8, PALETTE["pipe"], axis="y",
                                   offset=(x, 42.8, z)))
    builder.add_mesh(make_cylinder(1.15, 0.30, 16, PALETTE["radar_white"],
                                   axis="y", offset=(x, 46.9, z)))


def build_airfield() -> MeshData:
    """Build the enemy-continent runway complex as one true-scale mesh."""

    builder = MeshBuilder()
    _runway(builder)
    _taxiway_and_aprons(builder)
    _hangars(builder)
    _tower(builder)
    return builder.build()
