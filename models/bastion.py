"""Bastion coastal-battery TEL (transporter-erector-launcher) model.

An ~12 m 8-wheel military truck carrying TWO Oniks launch canisters side by
side. ``build_bastion_tel(elevation_deg)`` rotates the canisters about +X
(pivot near the canister tail) — 0 deg = stowed flat on the bed, 88 deg =
raised for launch; the rear ends swing down inside the hull like an S-300
erector so the raised battery stays under 10 m tall.

Task S5 art pass: the front is now an articulated cab — a tall short crew
cab separated from the equipment bay by a visible engine-deck gap — with a
raked windshield, side windows, headlights and a bumper; a dark recessed
chassis rail runs the full length under the green bodywork; each axle gets
a dark wheel-well plate (cutout illusion) under proud mudguard strips; the
canisters gain mouth covers, tail exhaust rings, reinforcing collars, an
inter-canister support frame and a cable conduit, all erecting as one block.

Model space: forward = +Z (cab at max Z), up = +Y, origin at ground center.
Pure numpy / GL-free.
"""

from __future__ import annotations

import math

from engine.meshdata import MeshBuilder, MeshData, make_box, make_cylinder
from models.common import PALETTE, rot_x

# Equipment bay (missile bay behind the cab): low, full width
HULL_W = 2.9
HULL_BOTTOM = 0.3
HULL_H = 2.6
HULL_TOP = HULL_BOTTOM + HULL_H            # 2.9
BAY_Z0, BAY_Z1 = -5.75, 3.35               # bay front stops short of the cab
HULL_L = 11.5                              # overall body length (bay + cab)

# Chassis frame rail: dark, slightly recessed band under the bodywork
RAIL_TOP = 0.68

# Articulated cab: tall short box at the very front + engine deck in the gap
CAB_Z0, CAB_Z1 = 4.05, 5.75
CAB_W = 2.9
CAB_TOP = 3.30

# Wheels: 8 tires (4 per side), r 0.65, axles at the tire radius
TIRE_R = 0.65
TIRE_W = 0.45
AXLE_Z = (4.3, 2.9, -2.7, -4.1)
TIRE_X = HULL_W * 0.5 - 0.10               # hubs poke just past the hull side

# Launch canisters: two capped cylinders r 0.45, len 9.4 on the bed.
# Pivot sits PIVOT_BACK from the canister tail so the raised pair tops out
# below 10 m while the tail swings down hidden inside the hull.
CAN_R = 0.45
CAN_LEN = 9.4
PIVOT_BACK = 2.8                            # pivot-to-tail distance
CAN_X = 0.55                                # half the side-by-side spacing
PIVOT_Y = HULL_TOP + CAN_R                  # stowed axis rests on the roof
PIVOT_Z = -4.0
COLLAR_R = 0.49                             # end caps / reinforcing collars
COLLAR_LEN = 0.18

# Outriggers: 4 jack boxes at the corner overhangs (clear of the tires)
RIG_SIZE = (0.8, 0.9, 0.5)
RIG_X = 1.55
RIG_Z = (5.4, -5.4)


def _canister_block(green: tuple, dark: tuple) -> MeshData:
    """Both canisters + their shared hardware in pivot space (tube axes
    along +Z spanning z in [-PIVOT_BACK, CAN_LEN - PIVOT_BACK]) so the
    whole assembly erects as one unit."""
    b = MeshBuilder()
    mouth_z = CAN_LEN - PIVOT_BACK             # 6.6
    z_mid = mouth_z * 0.5 - PIVOT_BACK * 0.5
    for sx in (1.0, -1.0):
        x = sx * CAN_X
        b.add_mesh(make_cylinder(CAN_R, CAN_LEN, 24, dark, axis="z",
                                 offset=(x, 0.0, z_mid)))
        # mouth cover (green collar) + tail exhaust ring (near-black)
        b.add_mesh(make_cylinder(COLLAR_R, COLLAR_LEN, 24, green, axis="z",
                                 offset=(x, 0.0, mouth_z - COLLAR_LEN * 0.5)))
        b.add_mesh(make_cylinder(COLLAR_R, COLLAR_LEN, 24,
                                 PALETTE["exhaust_ring"], axis="z",
                                 offset=(x, 0.0,
                                         -PIVOT_BACK + COLLAR_LEN * 0.5)))
        # two reinforcing collars along each tube
        for zc in (0.8, 4.0):
            b.add_mesh(make_cylinder(CAN_R + 0.03, 0.16, 24, green, axis="z",
                                     offset=(x, 0.0, zc)))
    # support frame: plates tying the pair together at three stations
    for zs in (-1.8, 1.6, 5.0):
        b.add_mesh(make_box((2.0 * (CAN_X + CAN_R), 0.16, 0.30), green,
                            offset=(0.0, 0.0, zs)))
    # cable conduit running between the canisters
    b.add_mesh(make_box((0.16, 0.30, 7.4), dark, offset=(0.0, 0.0, 1.7)))
    return b.build()


def build_bastion_tel(elevation_deg: float = 0.0) -> MeshData:
    b = MeshBuilder()
    green = PALETTE["mil_green"]
    dark = PALETTE["mil_green_dark"]
    black = PALETTE["tire"]
    glass = PALETTE["radome"]

    # chassis frame rail: dark recessed band, full length under the bodywork
    b.add_mesh(make_box((HULL_W - 0.16, RAIL_TOP - HULL_BOTTOM, HULL_L), black,
                        offset=(0.0, (HULL_BOTTOM + RAIL_TOP) * 0.5, 0.0)))

    # equipment bay (green body sits on the rail, overhanging it slightly)
    b.add_mesh(make_box((HULL_W, HULL_TOP - RAIL_TOP, BAY_Z1 - BAY_Z0), green,
                        offset=(0.0, (RAIL_TOP + HULL_TOP) * 0.5,
                                (BAY_Z0 + BAY_Z1) * 0.5)))
    # roof vents on the bay (visible from high/chase cameras)
    for zv in (-1.2, 0.2):
        b.add_mesh(make_box((0.9, 0.18, 1.0), dark,
                            offset=(-0.85, HULL_TOP + 0.09, zv)))

    # articulated cab: tall short box at the front, engine deck in the gap
    b.add_mesh(make_box((CAB_W, CAB_TOP - RAIL_TOP, CAB_Z1 - CAB_Z0), green,
                        offset=(0.0, (RAIL_TOP + CAB_TOP) * 0.5,
                                (CAB_Z0 + CAB_Z1) * 0.5)))
    b.add_mesh(make_box((2.3, 0.92, CAB_Z0 - BAY_Z1 + 0.1), dark,
                        offset=(0.0, RAIL_TOP + 0.46,
                                (BAY_Z1 + CAB_Z0) * 0.5)))
    # raked windshield plate proud of the cab face
    ws = rot_x(math.radians(8.0))              # top edge tips back
    b.add_mesh(make_box((2.45, 0.62, 0.07), glass), rotation=ws,
               offset=(0.0, CAB_TOP - 0.48, CAB_Z1 + 0.02))
    # side windows on both cab flanks
    for sx in (1.0, -1.0):
        b.add_mesh(make_box((0.06, 0.52, 1.05), glass,
                            offset=(sx * (CAB_W * 0.5 + 0.02), CAB_TOP - 0.50,
                                    CAB_Z1 - 0.70)))
    # headlights + front bumper
    for sx in (1.0, -1.0):
        b.add_mesh(make_box((0.32, 0.18, 0.06), PALETTE["radar_white"],
                            offset=(sx * 1.05, 1.42, CAB_Z1 + 0.02)))
    b.add_mesh(make_box((CAB_W, 0.28, 0.22), dark,
                        offset=(0.0, 0.82, CAB_Z1 + 0.08)))

    # 8 wheels, each in a dark wheel-well plate, mudguard strips per pair
    for za in AXLE_Z:
        for sx in (1.0, -1.0):
            b.add_mesh(make_box((0.07, 1.04, 1.36), black,
                                offset=(sx * (HULL_W * 0.5 + 0.015),
                                        HULL_BOTTOM + 0.52, za)))
            b.add_mesh(make_cylinder(TIRE_R, TIRE_W, 18, black,
                                     axis="x", offset=(sx * TIRE_X, TIRE_R, za)))
    for zc in ((AXLE_Z[0] + AXLE_Z[1]) * 0.5, (AXLE_Z[2] + AXLE_Z[3]) * 0.5):
        for sx in (1.0, -1.0):
            b.add_mesh(make_box((0.55, 0.09, 2.95), dark,
                                offset=(sx * TIRE_X, 1.40, zc)))

    # the canister pair + shared hardware, elevated about +X at the pivot
    elev = rot_x(-math.radians(elevation_deg))   # rot_x(-a) tips +Z up to +Y
    b.add_mesh(_canister_block(green, dark), rotation=elev,
               offset=(0.0, PIVOT_Y, PIVOT_Z))
    # trunnion bearings flanking the pivot, standing proud of the roof
    for sx in (1.0, -1.0):
        b.add_mesh(make_box((0.28, 0.85, 0.7), dark,
                            offset=(sx * (CAN_X + CAN_R + 0.18),
                                    HULL_TOP + 0.25, PIVOT_Z)))
    # cradle beam under the canisters' front end (stays on the roof)
    b.add_mesh(make_box((2.2, 0.25, 0.5), dark,
                        offset=(0.0, HULL_TOP + 0.125, 2.6)))

    # 4 outrigger jacks on splayed foot pads
    for zr in RIG_Z:
        for sx in (1.0, -1.0):
            b.add_mesh(make_box(RIG_SIZE, dark,
                                offset=(sx * RIG_X, RIG_SIZE[1] * 0.5, zr)))
            b.add_mesh(make_box((0.86, 0.08, 0.66), black,
                                offset=(sx * RIG_X, 0.04, zr)))
    return b.build()
