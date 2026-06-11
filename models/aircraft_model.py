"""Enemy aircraft models: the 30 m maritime patrol type and the 20 m fast type.

Both are a fuselage lathe (tapered nose and tail, dark radome nose cap),
straight trapezoidal main wings (mirrored make_fin pair), a tailplane pair
and a vertical fin. The patrol type carries two dark underwing engine
nacelles; the fast type gets a canopy hump and a dark tail nozzle instead.
Sizes per the locked numbers: patrol 30 x 35 m, fast 20 x 14 m.

Model space per LOCKED CONVENTIONS: forward = +Z (nose at max z), up = +Y,
real meters, origin at the center of mass (mid-fuselage). Pure numpy, GL-free.
"""

from __future__ import annotations

import math

from engine.meshdata import MeshBuilder, MeshData, make_box, make_cylinder, make_fin, make_lathe
from models.common import PALETTE, rot_z

SEG = 26                       # fuselage lathe segments

_ROT_MIRROR = rot_z(math.pi)             # right wing -> left wing
_ROT_UPRIGHT = rot_z(math.pi * 0.5)      # fin span +X -> +Y (vertical fin)


def _airframe(b: MeshBuilder, profile_grey, nose_cap, wing, wing_at,
              tail, tail_at, vfin, vfin_at) -> None:
    """Shared assembly: fuselage lathe + dark nose + mirrored wing/tailplane
    pairs + upright vertical fin. ``*_at`` are (x, y, z) root offsets."""
    grey = PALETTE["aircraft_grey"]
    b.add_mesh(make_lathe(profile_grey, SEG, grey))
    b.add_mesh(make_lathe(nose_cap, SEG, PALETTE["aircraft_dark"]))
    wx, wy, wz = wing_at
    b.add_mesh(wing, offset=(wx, wy, wz))
    b.add_mesh(wing, rotation=_ROT_MIRROR, offset=(-wx, wy, wz))
    tx, ty, tz = tail_at
    b.add_mesh(tail, offset=(tx, ty, tz))
    b.add_mesh(tail, rotation=_ROT_MIRROR, offset=(-tx, ty, tz))
    b.add_mesh(vfin, rotation=_ROT_UPRIGHT, offset=vfin_at)


def build_patrol_aircraft() -> MeshData:
    """30 m / 35 m-span four-corner patroller (two underwing nacelles)."""
    b = MeshBuilder()
    profile = [(-15.0, 0.0), (-14.0, 0.35), (-12.0, 0.85), (-8.0, 1.28),
               (-2.0, 1.45), (4.0, 1.45), (8.5, 1.32), (11.5, 1.05),
               (13.4, 0.62)]
    nose = [(13.4, 0.62), (15.0, 0.0)]
    wing = make_fin(4.2, 1.8, 16.3, 1.2, 0.35, PALETTE["aircraft_grey"])
    tail = make_fin(2.4, 1.0, 5.5, 0.9, 0.22, PALETTE["aircraft_grey"])
    vfin = make_fin(3.0, 1.4, 4.4, 1.6, 0.22, PALETTE["aircraft_grey"])
    _airframe(b, profile, nose,
              wing, (1.2, -0.35, 3.2),
              tail, (0.35, 0.2, -11.2),
              vfin, (0.0, 0.5, -11.7))
    # two underwing engine nacelles, slung tangent to the wing underside
    for sx in (1.0, -1.0):
        b.add_mesh(make_cylinder(0.52, 3.6, 18, PALETTE["aircraft_dark"],
                                 axis="z", offset=(sx * 4.8, -1.05, 3.4)))
    return b.build()


def build_fast_aircraft() -> MeshData:
    """20 m / 14 m-span fast type: slimmer, swept, canopy + dark nozzle."""
    b = MeshBuilder()
    profile = [(-9.4, 0.34), (-7.0, 0.62), (-3.0, 0.82), (2.0, 0.82),
               (5.5, 0.72), (8.0, 0.48)]
    nose = [(8.0, 0.48), (10.0, 0.0)]
    wing = make_fin(3.2, 1.1, 6.25, 2.1, 0.22, PALETTE["aircraft_grey"])
    tail = make_fin(1.7, 0.7, 2.55, 1.0, 0.15, PALETTE["aircraft_grey"])
    vfin = make_fin(2.4, 0.9, 2.9, 1.5, 0.16, PALETTE["aircraft_grey"])
    _airframe(b, profile, nose,
              wing, (0.75, -0.15, 1.8),
              tail, (0.45, 0.0, -7.6),
              vfin, (0.0, 0.45, -7.2))
    # dark exhaust: flat tail disc + short band closing the fuselage
    b.add_mesh(make_lathe([(-10.0, 0.0), (-10.0, 0.30), (-9.4, 0.34)], SEG,
                          PALETTE["exhaust_ring"]))
    # canopy hump on the spine ahead of the wing
    b.add_mesh(make_box((0.62, 0.45, 1.6), PALETTE["aircraft_dark"],
                        offset=(0.0, 0.78, 4.8)))
    return b.build()
