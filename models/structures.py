"""Procedural land/coast structure models: radar station, fuel depot, harbor.

Real scale (meters). Model space: forward = +Z, up = +Y, origin at the
GROUND CENTER (y = 0 is the local ground / quay waterline; the harbor's quay
walls reach 1.5 m below it, everything else sits on or above it).

Pure numpy / GL-free (returns ``MeshData``; callers upload via engine.mesh).
"""

from __future__ import annotations

import math

import numpy as np

from engine.meshdata import (MeshBuilder, MeshData, make_box, make_cylinder,
                             make_lathe, make_wedge)
from models.common import PALETTE, rot_x, rot_y, rot_z, sphere_profile


def _add_lattice_tower(b: MeshBuilder, y0: float, y1: float) -> None:
    """Four-leg braced tower sized to the radar station's existing 22 m OBB."""
    steel = PALETTE["mil_green_dark"]
    leg = 1.82
    for x in (-leg, leg):
        for z in (-leg, leg):
            b.add_mesh(make_box((0.28, y1 - y0, 0.28), steel,
                                offset=(x, (y0 + y1) * 0.5, z)))

    band_h = 3.0
    diag_len = math.hypot(2.0 * leg, band_h)
    angle = math.atan2(2.0 * leg, band_h)
    yy = y0
    while yy + band_h <= y1 + 1e-6:
        cy = yy + band_h * 0.5
        for x in (-leg, leg):
            for a in (-angle, angle):
                b.add_mesh(make_box((0.14, diag_len, 0.14), steel),
                           rotation=rot_x(a), offset=(x, cy, 0.0))
        for z in (-leg, leg):
            for a in (-angle, angle):
                b.add_mesh(make_box((0.14, diag_len, 0.14), steel),
                           rotation=rot_z(a), offset=(0.0, cy, z))
        yy += band_h

    # Maintenance ladder on the east face.
    for z in (-0.25, 0.25):
        b.add_mesh(make_box((0.10, y1 - y0 - 0.4, 0.10), PALETTE["pipe"],
                            offset=(leg + 0.18, (y0 + y1) * 0.5, z)))
    for yy in np.arange(y0 + 0.4, y1 - 0.2, 0.55):
        b.add_mesh(make_box((0.10, 0.055, 0.58), PALETTE["pipe"],
                            offset=(leg + 0.18, float(yy), 0.0)))


def build_radar_station() -> MeshData:
    """Braced radar tower, spherical radome, platform, and service plant."""
    conc = PALETTE["concrete"]
    b = MeshBuilder()
    b.add_mesh(make_box((12.0, 1.2, 12.0), conc, offset=(0.0, 0.6, 0.0)))
    # Concrete shoes, steel lattice, top service platform and radome pedestal.
    for x in (-1.82, 1.82):
        for z in (-1.82, 1.82):
            b.add_mesh(make_box((0.90, 0.60, 0.90), conc,
                                offset=(x, 1.50, z)))
    _add_lattice_tower(b, 1.8, 13.8)
    b.add_mesh(make_box((5.2, 0.35, 5.2), PALETTE["pipe"],
                        offset=(0.0, 13.98, 0.0)))
    b.add_mesh(make_cylinder(1.15, 1.20, 20, conc, axis="y",
                             offset=(0.0, 14.58, 0.0)))
    # Radome center/radius are unchanged, preserving the established height.
    b.add_mesh(make_lathe(sphere_profile(3.4), 24, PALETTE["radar_white"]),
               offset=(0.0, 17.4, 0.0))

    # Service hut moved inside the 14 x 14 m gameplay collider; add door,
    # ventilation bank, generator and cable trench instead of bare boxes.
    hut_x = 4.35
    b.add_mesh(make_box((3.1, 2.8, 3.7), conc, offset=(hut_x, 1.4, 0.7)))
    b.add_mesh(make_box((3.35, 0.30, 3.95), PALETTE["mil_green_dark"],
                        offset=(hut_x, 2.90, 0.7)))
    b.add_mesh(make_box((0.055, 1.90, 1.00), PALETTE["mil_green_dark"],
                        offset=(5.93, 1.24, 0.40)))
    for zz in (0.35, 0.70, 1.05):
        b.add_mesh(make_box((0.07, 0.18, 0.22), PALETTE["tire"],
                            offset=(5.94, 2.20, zz)))
    b.add_mesh(make_box((2.1, 1.5, 1.25), PALETTE["mil_green_dark"],
                        offset=(3.95, 0.75, -2.65)))
    for zz in (-2.95, -2.65, -2.35):
        b.add_mesh(make_box((2.14, 0.08, 0.08), PALETTE["tire"],
                            offset=(3.95, 0.95, zz)))
    b.add_mesh(make_box((0.48, 0.18, 4.6), PALETTE["pipe"],
                        offset=(2.65, 0.18, -0.35)))
    return b.build()


def build_fuel_depot() -> MeshData:
    """Six API-style vertical tanks with cone roofs, bund, piping and access."""
    white = PALETTE["tank_white"]
    pipe_c = PALETTE["pipe"]
    b = MeshBuilder()
    # Fixed shallow cone roof, tipped from the lathe's +Z axis to +Y.
    roof = make_lathe([(0.0, 8.0), (0.18, 7.96), (1.30, 0.0)],
                      28, white, smooth=False)
    up = rot_x(-0.5 * math.pi)
    for xx in (-20.0, 0.0, 20.0):
        for zz in (-11.0, 11.0):
            b.add_mesh(make_cylinder(8.0, 12.0, 28, white, axis="y",
                                     offset=(xx, 6.0, zz)))
            b.add_mesh(roof, rotation=up, offset=(xx, 12.0, zz))
            # Horizontal shell-course seams and a heavier roof curb.
            for yy in (2.0, 4.0, 6.0, 8.0, 10.0, 11.96):
                b.add_mesh(make_cylinder(8.055, 0.075, 28,
                                         PALETTE["radar_white"], axis="y",
                                         offset=(xx, yy, zz)))

            sign = math.copysign(1.0, zz)
            # Correct inner-wall stub to the central manifold, valve and shell
            # manhole.  The old 8.4 m stub overshot both connection points.
            b.add_mesh(make_cylinder(0.28, 2.30, 12, pipe_c, axis="z",
                                     offset=(xx, 0.88, sign * 1.85)))
            b.add_mesh(make_cylinder(0.30, 0.10, 12,
                                     PALETTE["mil_green_dark"], axis="y",
                                     offset=(xx, 1.28, sign * 0.82)))
            b.add_mesh(make_cylinder(0.46, 0.20, 16,
                                     PALETTE["mil_green_dark"], axis="z",
                                     offset=(xx, 1.05, sign * 2.96)))

            # Roof vent, outside access ladder, sampling platform and rails.
            b.add_mesh(make_cylinder(0.18, 0.72, 12, pipe_c, axis="y",
                                     offset=(xx + 1.15, 13.32, zz)))
            ladder_z = zz + sign * 8.08
            for dx in (-0.28, 0.28):
                b.add_mesh(make_box((0.07, 11.8, 0.07), pipe_c,
                                    offset=(xx + dx, 6.1, ladder_z)))
            for yy in np.arange(0.55, 12.0, 0.62):
                b.add_mesh(make_box((0.64, 0.045, 0.07), pipe_c,
                                    offset=(xx, float(yy), ladder_z)))
            b.add_mesh(make_box((2.05, 0.12, 1.10), pipe_c,
                                offset=(xx, 12.22, zz + sign * 7.45)))
            for dx in (-0.92, 0.92):
                b.add_mesh(make_box((0.07, 0.75, 0.07), pipe_c,
                                    offset=(xx + dx, 12.62,
                                            zz + sign * 7.45)))

    # Impervious floor and secondary-containment walls around the tank group.
    b.add_mesh(make_box((61.0, 0.08, 39.6), PALETTE["concrete"],
                        offset=(0.0, 0.04, 0.0)))
    for x in (-30.5, 30.5):
        b.add_mesh(make_box((0.38, 1.20, 40.0), PALETTE["concrete"],
                            offset=(x, 0.60, 0.0)))
    for z in (-19.8, 19.8):
        b.add_mesh(make_box((61.0, 1.20, 0.38), PALETTE["concrete"],
                            offset=(0.0, 0.60, z)))

    # Twin manifold pipes, supports and isolation valves into the pump house.
    for sz in (-0.7, 0.7):
        b.add_mesh(make_cylinder(0.45, 62.0, 12, pipe_c, axis="x",
                                 offset=(1.0, 0.9, sz)))
    for xx in (-25.0, -15.0, -5.0, 5.0, 15.0, 25.0):
        b.add_mesh(make_box((0.50, 0.72, 2.20), PALETTE["concrete"],
                            offset=(xx, 0.36, 0.0)))
        b.add_mesh(make_cylinder(0.30, 0.10, 12,
                                 PALETTE["mil_green_dark"], axis="y",
                                 offset=(xx, 1.42, 0.0)))

    b.add_mesh(make_box((8.0, 4.0, 6.0), PALETTE["concrete"],
                        offset=(34.0, 2.0, 0.0)))
    # Gabled pump-house roof, personnel door and ventilation louvers.
    roof_half = make_wedge((8.5, 1.15, 3.25), PALETTE["mil_green_dark"])
    b.add_mesh(roof_half, offset=(34.0, 4.58, 1.625))
    b.add_mesh(roof_half, rotation=rot_y(math.pi),
               offset=(34.0, 4.58, -1.625))
    b.add_mesh(make_box((0.055, 2.35, 1.20), PALETTE["mil_green_dark"],
                        offset=(38.03, 1.35, 0.0)))
    for zz in (-1.55, -1.15, 1.15, 1.55):
        b.add_mesh(make_box((0.06, 0.22, 0.28), PALETTE["tire"],
                            offset=(38.04, 2.85, zz)))
    return b.build()


def build_harbor() -> MeshData:
    """Compact cargo harbor with two finger piers and a shore apron.

    The navigation footprint is unchanged, but the rebuilt site adds the
    features that make a working port readable from overhead: coping strips,
    fenders, bollards, ladders, crane rails, braced ship-to-shore cranes,
    pitched warehouses, doors/vents, container stacks, and apron markings.
    """
    conc = PALETTE["concrete"]
    dark = PALETTE["tire"]
    steel = PALETTE["pipe"]
    glass = PALETTE["aircraft_dark"]
    yellow = PALETTE["container_c"]
    roof_color = PALETTE["container_b"]
    b = MeshBuilder()

    # Quay walls run 1.5 m below the sea surface; working decks top at +2.5 m.
    for xx in (-38.0, 38.0):
        b.add_mesh(make_box((24.0, 4.0, 170.0), conc, offset=(xx, 0.5, 0.0)))
    quay_top = 2.5

    # Inner-basin coping, rubber fenders, mooring bollards, and wall ladders.
    for edge_x in (-25.8, 25.8):
        b.add_mesh(make_box((0.45, 0.16, 166.0), yellow,
                            offset=(edge_x, quay_top + 0.08, 0.0)))
        for z in range(-72, 73, 18):
            b.add_mesh(make_box((0.65, 3.0, 2.2), dark,
                                offset=(edge_x, 0.35, float(z))))
        deck_x = edge_x + (0.75 if edge_x < 0.0 else -0.75)
        for z in range(-70, 71, 20):
            b.add_mesh(make_cylinder(
                0.32, 0.65, 8, dark, axis="y",
                offset=(deck_x, quay_top + 0.325, float(z))))
        for z in (-58.0, 2.0, 58.0):
            for dz in (-0.42, 0.42):
                b.add_mesh(make_box((0.10, 3.2, 0.10), steel,
                                    offset=(edge_x, 0.9, z + dz)))
            for y in np.arange(-0.35, 2.35, 0.48):
                b.add_mesh(make_box((0.18, 0.08, 1.0), steel,
                                    offset=(edge_x, float(y), z)))

    # Shore apron joins the quay roots to the rising foreshore behind the port.
    b.add_mesh(make_box((104.0, 3.4, 90.0), conc, offset=(0.0, 1.3, 105.0)))
    b.add_mesh(make_box((8.0, 0.08, 82.0), PALETTE["aircraft_dark"],
                        offset=(0.0, 3.04, 106.0)))
    for z in range(72, 141, 14):
        b.add_mesh(make_box((0.22, 0.10, 7.0), yellow,
                            offset=(0.0, 3.10, float(z))))

    # Pitched warehouses with basin-facing loading doors and roof ventilators.
    roof_rise = 2.2
    roof_angle = math.atan2(roof_rise, 8.0)
    roof_slope = math.hypot(8.0, roof_rise)
    for xx, zz in ((-38.0, -50.0), (-38.0, 10.0), (38.0, -30.0)):
        b.add_mesh(make_box((16.0, 8.0, 44.0), conc,
                            offset=(xx, quay_top + 4.0, zz)))
        roof = make_box((roof_slope, 0.55, 45.0), roof_color)
        b.add_mesh(roof, offset=(xx - 4.0, quay_top + 9.1, zz),
                   rotation=rot_z(roof_angle))
        b.add_mesh(roof, offset=(xx + 4.0, quay_top + 9.1, zz),
                   rotation=rot_z(-roof_angle))
        inner_x = xx + (8.04 if xx < 0.0 else -8.04)
        b.add_mesh(make_box((0.14, 4.7, 15.0), glass,
                            offset=(inner_x, quay_top + 2.35, zz)))
        for dz in (-5.0, 0.0, 5.0):
            b.add_mesh(make_box((0.18, 4.8, 0.18), steel,
                                offset=(inner_x, quay_top + 2.4, zz + dz)))
        for dz in (-15.5, 15.5):
            b.add_mesh(make_box((0.16, 2.4, 1.3), glass,
                                offset=(inner_x, quay_top + 1.2, zz + dz)))
        for dz in (-11.0, 11.0):
            b.add_mesh(make_cylinder(
                0.38, 1.25, 8, steel, axis="y",
                offset=(xx, quay_top + 10.55, zz + dz)))

    # ISO-like container stacks flank the central apron service road.
    container_colors = (PALETTE["container_a"], PALETTE["container_b"],
                        PALETTE["container_c"])
    for row, z in enumerate((83.0, 98.0, 116.0)):
        for column, x in enumerate((-31.0, -23.5, 23.5, 31.0)):
            levels = 2 + ((row + column) % 2)
            for level in range(levels):
                color = container_colors[(row + column + level) % 3]
                cy = 3.0 + 1.275 + 2.55 * level
                b.add_mesh(make_box((6.1, 2.55, 12.2), color,
                                    offset=(x, cy, z)))
                for dx in (-2.0, 0.0, 2.0):
                    b.add_mesh(make_box((0.10, 2.25, 0.10), steel,
                                        offset=(x + dx, cy, z - 6.12)))

    # Braced ship-to-shore cranes: twin booms reach over the basin and carry
    # visible trolleys, hoist lines, and spreader bars.
    for cz in (30.0, 65.0):
        leg_x = (31.5, 44.0)
        for sx in leg_x:
            for sz in (-5.0, 5.0):
                b.add_mesh(make_box((0.9, 16.0, 0.9), yellow,
                                    offset=(sx, quay_top + 8.0, cz + sz)))
        brace_len = math.hypot(12.5, 13.5)
        brace_angle = math.atan2(12.5, 13.5)
        for sz in (-5.0, 5.0):
            brace = make_box((0.32, brace_len, 0.32), yellow)
            b.add_mesh(brace, offset=(37.75, quay_top + 8.0, cz + sz),
                       rotation=rot_z(brace_angle))
            b.add_mesh(brace, offset=(37.75, quay_top + 8.0, cz + sz),
                       rotation=rot_z(-brace_angle))
            b.add_mesh(make_box((57.0, 1.15, 0.75), yellow,
                                offset=(16.0, quay_top + 16.7, cz + sz)))
        for sx in leg_x:
            b.add_mesh(make_box((1.0, 1.4, 11.0), yellow,
                                offset=(sx, quay_top + 16.7, cz)))
        b.add_mesh(make_box((6.0, 3.2, 8.0), yellow,
                            offset=(41.0, quay_top + 19.0, cz)))
        trolley_x = -4.0
        b.add_mesh(make_box((3.8, 1.4, 7.6), dark,
                            offset=(trolley_x, quay_top + 15.8, cz)))
        for zoff in (-2.2, 2.2):
            b.add_mesh(make_box((0.10, 11.0, 0.10), steel,
                                offset=(trolley_x, quay_top + 10.1,
                                        cz + zoff)))
        b.add_mesh(make_box((5.8, 0.35, 7.5), yellow,
                            offset=(trolley_x, quay_top + 4.55, cz)))
        for sx in leg_x:
            b.add_mesh(make_box((0.22, 0.12, 100.0), steel,
                                offset=(sx, quay_top + 0.08, 25.0)))
    return b.build()
