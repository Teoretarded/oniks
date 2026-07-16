"""Procedural Nimitz-class aircraft carrier.

Reference dimensions are the US Navy's 332.85 m overall length, 40.84 m
waterline beam and 76.8 m maximum flight-deck width.  Model space is +Z bow,
+Y up, +X starboard, with the origin at the waterline amidships.

The previous mesh was a 333 x 76.8 m rectangle plus a second rotated rectangle;
its fake bow extended 15 m past the official length and its 60 m box-island hid
the deck shape.  This version builds one recognizable flight-deck planform,
tapered hull, compact island, elevators, four catapult tracks, arresting area,
sponsons and deck markings.  Pure numpy / GL-free.
"""

from __future__ import annotations

import math

import numpy as np

from engine.meshdata import MeshBuilder, MeshData, make_box, make_cylinder
from models.common import PALETTE, rot_x, rot_y

_LENGTH = 333.0
_HALF_L = _LENGTH * 0.5
_HULL_BEAM = 40.84
_DECK_BEAM = 76.8
_DRAFT = 9.0                 # visual draft; the opaque ocean hides the keel
_FREEBOARD = 7.5

_HULL = PALETTE["haze_gray"]
_DECK = PALETTE["haze_gray_deck"]
_SS = PALETTE["haze_gray_dark"]
_DARK = PALETTE["aircraft_dark"]
_BLACK = PALETTE["radome"]
_WHITE = PALETTE["radar_white"]
_YELLOW = PALETTE["container_c"]


def _extruded_planform(points_xz, y0: float, y1: float, color) -> MeshData:
    """Flat-shaded vertical extrusion of a convex XZ planform.

    Input winding is normalized internally.  This small helper gives ships a
    real bow/deck outline without importing GL or adding a general mesh library.
    """
    pts = [(float(x), float(z)) for x, z in points_xz]
    if len(pts) < 3:
        raise ValueError("planform needs at least three points")
    area2 = sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
                - pts[(i + 1) % len(pts)][0] * pts[i][1]
                for i in range(len(pts)))
    # Clockwise in the usual XZ drawing gives +Y winding in XYZ space.
    if area2 > 0.0:
        pts.reverse()

    verts = []
    idx = []
    n = len(pts)
    for x, z in pts:
        verts.append((x, y1, z, 0.0, 1.0, 0.0, *color))
    for i in range(1, n - 1):
        idx.extend((0, i, i + 1))
    bottom = len(verts)
    for x, z in pts:
        verts.append((x, y0, z, 0.0, -1.0, 0.0, *color))
    for i in range(1, n - 1):
        idx.extend((bottom, bottom + i + 1, bottom + i))

    for i in range(n):
        j = (i + 1) % n
        x0, z0 = pts[i]
        x1, z1 = pts[j]
        dx, dz = x1 - x0, z1 - z0
        length = math.hypot(dx, dz)
        nx, nz = -dz / length, dx / length
        base = len(verts)
        verts.extend(((x0, y0, z0, nx, 0.0, nz, *color),
                      (x1, y0, z1, nx, 0.0, nz, *color),
                      (x1, y1, z1, nx, 0.0, nz, *color),
                      (x0, y1, z0, nx, 0.0, nz, *color)))
        idx.extend((base, base + 1, base + 2,
                    base, base + 2, base + 3))
    return MeshData(np.asarray(verts, dtype=np.float32),
                    np.asarray(idx, dtype=np.uint32))


def _hull(b: MeshBuilder) -> float:
    """Tapered waterline body; return flight-deck base height."""
    hull_plan = (
        (-15.5, -_HALF_L), (-20.0, -125.0), (-20.42, 70.0),
        (-17.5, 128.0), (-7.5, 158.0), (0.0, _HALF_L),
        (7.5, 158.0), (17.5, 128.0), (20.42, 70.0),
        (20.0, -125.0), (15.5, -_HALF_L),
    )
    b.add_mesh(_extruded_planform(hull_plan, -_DRAFT, _FREEBOARD, _HULL))

    # Dark hangar/elevator apertures break up the slab sides at oblique views.
    for x in (-20.46, 20.46):
        for z in (-92.0, -25.0, 45.0):
            b.add_mesh(make_box((0.18, 3.0, 24.0), _BLACK,
                                offset=(x, 4.6, z)))
    return _FREEBOARD + 0.45


def _flight_deck(b: MeshBuilder, deck_y: float) -> None:
    """Asymmetric carrier planform with angled port landing area."""
    # Widest port point = -40.0, widest starboard point = +36.8 => 76.8 m.
    deck_plan = (
        (-22.0, -_HALF_L), (-35.0, -132.0), (-40.0, -58.0),
        (-34.0, 38.0), (-22.0, 132.0), (-8.0, 160.0),
        (0.0, _HALF_L), (10.0, 160.0), (25.0, 137.0),
        (33.0, 93.0), (36.8, 22.0), (34.0, -91.0),
        (24.0, -_HALF_L),
    )
    b.add_mesh(_extruded_planform(deck_plan, deck_y, deck_y + 0.65, _DECK))

    mark_y = deck_y + 0.69
    # Angled landing strip and centerline (roughly 9 degrees to port).
    angle = math.radians(-9.0)
    b.add_mesh(make_box((25.0, 0.09, 225.0), PALETTE["warship_deck"]),
               rotation=rot_y(angle), offset=(-10.0, mark_y, -20.0))
    b.add_mesh(make_box((0.72, 0.11, 205.0), _WHITE),
               rotation=rot_y(angle), offset=(-10.0, mark_y + 0.02, -19.0))
    # Landing threshold and four arresting wires.
    b.add_mesh(make_box((24.0, 0.12, 2.2), _WHITE), rotation=rot_y(angle),
               offset=(-25.0, mark_y + 0.03, -117.0))
    for i in range(4):
        b.add_mesh(make_box((25.0, 0.09, 0.28), _YELLOW),
                   rotation=rot_y(angle),
                   offset=(-20.5 + i * 0.9, mark_y + 0.04,
                           -83.0 + i * 5.0))

    # Two bow and two waist catapult tracks.
    for x in (-7.2, 7.2):
        b.add_mesh(make_box((0.62, 0.10, 100.0), _WHITE,
                            offset=(x, mark_y + 0.03, 108.0)))
    for x, z in ((-17.0, 20.0), (-22.0, -18.0)):
        b.add_mesh(make_box((0.58, 0.10, 100.0), _WHITE),
                   rotation=rot_y(angle), offset=(x, mark_y + 0.03, z))

    # Deck-edge safety stripe follows the most readable long edges.
    for x, z, length, a in ((34.0, 65.0, 85.0, 0.0),
                            (32.0, -105.0, 93.0, 0.0),
                            (-34.0, -90.0, 70.0, angle)):
        b.add_mesh(make_box((0.35, 0.08, length), _YELLOW),
                   rotation=rot_y(a), offset=(x, mark_y + 0.02, z))

    # Four deck-edge elevators: three starboard, one port.
    elevator_c = PALETTE["warship_deck"]
    for x, z in ((31.0, 93.0), (31.2, 18.0), (30.8, -92.0),
                 (-34.5, -105.0)):
        b.add_mesh(make_box((10.5, 0.14, 16.0), elevator_c,
                            offset=(x, mark_y + 0.02, z)))
        b.add_mesh(make_box((0.28, 0.16, 15.0), _WHITE,
                            offset=(x, mark_y + 0.04, z)))


def _island(b: MeshBuilder, deck_y: float) -> None:
    """Compact starboard island with integrated funnel and sensor mast."""
    x0, z0 = 27.5, 14.0
    base_y = deck_y + 0.65

    # Stepped/faceted mass, far smaller than the former 18 x 60 m box.
    b.add_mesh(make_box((15.0, 8.5, 30.0), _SS,
                        offset=(x0, base_y + 4.25, z0)))
    b.add_mesh(make_box((12.0, 5.0, 22.0), _SS,
                        offset=(x0 - 0.5, base_y + 11.0, z0 + 2.0)))
    b.add_mesh(make_box((9.0, 3.5, 15.0), _SS,
                        offset=(x0 - 0.8, base_y + 15.25, z0 + 4.0)))

    # Bridge window band, pane-separated on the forward face.
    for x in np.linspace(x0 - 5.1, x0 + 4.2, 6):
        b.add_mesh(make_box((1.2, 0.78, 0.22), _BLACK,
                            offset=(float(x), base_y + 12.0, z0 + 13.1)))

    # Integrated funnel with black cap, then a braced mast and yardarms.
    b.add_mesh(make_box((6.0, 8.0, 7.0), _SS),
               rotation=rot_x(math.radians(5.0)),
               offset=(x0 + 0.2, base_y + 20.0, z0 - 2.0))
    b.add_mesh(make_box((5.5, 0.8, 6.5), _BLACK,
                        offset=(x0 + 0.2, base_y + 24.1, z0 - 2.3)))
    mast_y = base_y + 24.0
    for dx in (-1.3, 1.3):
        b.add_mesh(make_cylinder(0.22, 16.0, 8, _SS, axis="y",
                                 offset=(x0 + dx, mast_y + 8.0, z0 + 2.0)))
    for yy, length in ((mast_y + 5.0, 10.0),
                       (mast_y + 10.0, 14.0),
                       (mast_y + 14.5, 8.0)):
        b.add_mesh(make_cylinder(0.14, length, 8, _SS, axis="x",
                                 offset=(x0, yy, z0 + 2.0)))
    # Rectangular air-search sets are more characteristic than the old ball.
    b.add_mesh(make_box((5.5, 2.3, 0.20), _DARK,
                        offset=(x0, mast_y + 12.5, z0 + 2.2)))
    b.add_mesh(make_box((0.20, 2.8, 4.2), _DARK,
                        offset=(x0 + 1.6, mast_y + 7.5, z0 + 2.0)))


def _sponsons_and_defence(b: MeshBuilder, deck_y: float) -> None:
    """Edge sponsons with small RAM/CIWS shapes and life-raft pods."""
    placements = ((-23.5, 135.0), (28.0, -142.0),
                  (-34.0, -112.0), (31.0, 105.0))
    for i, (x, z) in enumerate(placements):
        # A shallow inboard bridge makes each projecting weapons platform a
        # real deck-edge sponson instead of an isolated rectangle in top view.
        inner_x = math.copysign(17.0, x)
        bridge_w = abs(x - inner_x) + 1.0
        b.add_mesh(make_box((bridge_w, 0.9, 8.5), _SS,
                            offset=((x + inner_x) * 0.5,
                                    deck_y + 0.25, z)))
        b.add_mesh(make_box((6.0, 1.1, 12.0), _SS,
                            offset=(x, deck_y + 0.45, z)))
        b.add_mesh(make_cylinder(0.72, 0.9, 12, _SS, axis="y",
                                 offset=(x, deck_y + 1.25, z)))
        if i % 2:
            b.add_mesh(make_box((1.8, 1.4, 2.0), _DARK,
                                offset=(x, deck_y + 2.3, z)))
        else:
            b.add_mesh(make_cylinder(0.58, 1.0, 12, _WHITE, axis="y",
                                     offset=(x, deck_y + 2.0, z)))

    for side in (-1.0, 1.0):
        for z in (-55.0, -25.0, 55.0):
            b.add_mesh(make_cylinder(0.55, 3.0, 10, PALETTE["container_c"],
                                     axis="z", offset=(side * 20.2, 4.5, z)))


def build_carrier() -> MeshData:
    """Return the improved Nimitz-class CVN mesh."""
    b = MeshBuilder()
    deck_y = _hull(b)
    _flight_deck(b, deck_y)
    _island(b, deck_y)
    _sponsons_and_defence(b, deck_y)
    return b.build()
