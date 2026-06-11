"""S-300 battery models: the 5P85-style 4-tube TEL and the 48N6 interceptor.

``build_s300_tel(elevation_deg)`` is a ~13 m 8-wheel MAZ-style chassis with a
flat-front cab and FOUR launch tubes (r 0.55, len 8.2) in a 2x2 block on the
rear bed. The block pivots about +X near the rear (0 = stowed flat along the
chassis, 90 = vertical); rotating the stowed over/under pair upright turns it
into the side-by-side two-deep arrangement of the real launcher. Deliberately
distinct from the Bastion TEL silhouette: boxy flat cab vs wedge, 4-tube grey
block vs 2 green canisters.

``build_s300_missile()`` is the 7.5 x 0.515 m 48N6: ogive nose with a dark
radome tip, clean cylinder, 4 small cruciform strakes near mid-body and 4
clipped tail fins. Origin at mid-body, forward = +Z (nose at +3.75).

Model space per LOCKED CONVENTIONS: forward = +Z, up = +Y, real meters,
origin at the ground center (TEL) / mid-body (missile). Pure numpy, GL-free.
"""

from __future__ import annotations

import math

import numpy as np

from engine.meshdata import (MeshBuilder, MeshData, make_box, make_cylinder,
                             make_fin, make_lathe)
from models.common import PALETTE, rot_x, rot_z

SEG = 28                       # lathe/cylinder segments

# --- TEL: chassis ---------------------------------------------------------------
CHASSIS_L = 13.0
CHASSIS_W = 3.05
FRAME_BOT = 0.55               # deck underside (ground clearance)
FRAME_TOP = 1.45               # flat bed height

# Flat-front cab on the bed nose (front face flush with the chassis front)
CAB_W, CAB_H, CAB_L = 3.05, 1.75, 2.6
CAB_TOP = FRAME_TOP + CAB_H    # 3.2

# Equipment housing behind the cab (generator / erector hydraulics)
ENG_W, ENG_H, ENG_L = 2.5, 0.75, 1.5

# Wheels: 8 tires (4 axles: 2 forward under the cab, 2 aft under the block)
TIRE_R = 0.70
TIRE_W = 0.50
AXLE_Z = (5.0, 3.4, -3.3, -4.9)
TIRE_X = CHASSIS_W * 0.5 - 0.10

# --- TEL: launch-tube block ------------------------------------------------------
TUBE_R = 0.55
TUBE_LEN = 8.2
TUBE_X = 0.63                  # half the side-by-side spacing
PAIR_DY = 1.28                 # stowed vertical gap lower->upper tube centers
PIVOT_BACK = 1.6               # pivot-to-tail distance along the tube
PIVOT_Y = FRAME_TOP + TUBE_R + 0.10   # stowed lower pair rests on the bed
PIVOT_Z = -4.9
CAP_R = 0.58                   # end-cap collar radius
CAP_LEN = 0.16

# Outriggers: 4 jack boxes clear of the tires
RIG_SIZE = (0.7, 0.9, 0.5)
RIG_X = 1.55
RIG_Z = (1.0, -6.2)

# Mouth of a LOWER tube relative to the pivot, along the tube axis (world/
# world.py Task S4 derives the vertical-launch mouth point from these).
MOUTH_RUN = TUBE_LEN - PIVOT_BACK


def _tube_block(dark_green: tuple) -> MeshData:
    """The 2x2 tube assembly in pivot space: tube axes along +Z spanning
    z in [-PIVOT_BACK, MOUTH_RUN]; lower pair at dy 0, upper at dy PAIR_DY."""
    b = MeshBuilder()
    tube_c = PALETTE["tube_grey"]
    z_mid = MOUTH_RUN * 0.5 - PIVOT_BACK * 0.5
    for dy in (0.0, PAIR_DY):
        for sx in (1.0, -1.0):
            off = (sx * TUBE_X, dy, 0.0)
            b.add_mesh(make_cylinder(TUBE_R, TUBE_LEN, SEG, tube_c, axis="z",
                                     offset=(off[0], off[1], z_mid)))
            # end-cap collars: green covers at the mouth, dark ring at the tail
            b.add_mesh(make_cylinder(CAP_R, CAP_LEN, SEG, dark_green, axis="z",
                                     offset=(off[0], off[1],
                                             MOUTH_RUN - CAP_LEN * 0.5)))
            b.add_mesh(make_cylinder(CAP_R, CAP_LEN, SEG,
                                     PALETTE["exhaust_ring"], axis="z",
                                     offset=(off[0], off[1],
                                             -PIVOT_BACK + CAP_LEN * 0.5)))
    # inter-tube frame: a + of plates between the four tubes at 3 stations
    green = PALETTE["s300_green"]
    for zs in (-0.9, 2.4, 5.7):
        b.add_mesh(make_box((2.0 * (TUBE_X + TUBE_R), 0.14, 0.30), green,
                            offset=(0.0, PAIR_DY * 0.5, zs)))
        b.add_mesh(make_box((0.14, PAIR_DY + 2.0 * TUBE_R, 0.30), green,
                            offset=(0.0, PAIR_DY * 0.5, zs)))
    return b.build()


def build_s300_tel(elevation_deg: float = 0.0) -> MeshData:
    b = MeshBuilder()
    green = PALETTE["s300_green"]
    dark = PALETTE["mil_green_dark"]

    # flat bed + boxy flat-front cab + dark windshield band proud of the face
    b.add_mesh(make_box((CHASSIS_W, FRAME_TOP - FRAME_BOT, CHASSIS_L), green,
                        offset=(0.0, (FRAME_BOT + FRAME_TOP) * 0.5, 0.0)))
    b.add_mesh(make_box((CAB_W, CAB_H, CAB_L), green,
                        offset=(0.0, FRAME_TOP + CAB_H * 0.5,
                                CHASSIS_L * 0.5 - CAB_L * 0.5)))
    b.add_mesh(make_box((2.55, 0.62, 0.08), PALETTE["radome"],
                        offset=(0.0, CAB_TOP - 0.55, CHASSIS_L * 0.5 + 0.02)))
    # side windows: dark plates on both cab flanks
    for sx in (1.0, -1.0):
        b.add_mesh(make_box((0.08, 0.55, 1.1), PALETTE["radome"],
                            offset=(sx * (CAB_W * 0.5 + 0.02), CAB_TOP - 0.58,
                                    CHASSIS_L * 0.5 - 0.85)))
    # front bumper lip below the cab face
    b.add_mesh(make_box((CHASSIS_W, 0.28, 0.25), dark,
                        offset=(0.0, FRAME_BOT + 0.14, CHASSIS_L * 0.5 + 0.1)))
    # equipment housing behind the cab
    b.add_mesh(make_box((ENG_W, ENG_H, ENG_L), dark,
                        offset=(0.0, FRAME_TOP + ENG_H * 0.5,
                                CHASSIS_L * 0.5 - CAB_L - ENG_L * 0.5 - 0.2)))

    # 8 wheels + mudguard strips over each axle pair
    for za in AXLE_Z:
        for sx in (1.0, -1.0):
            b.add_mesh(make_cylinder(TIRE_R, TIRE_W, 18, PALETTE["tire"],
                                     axis="x", offset=(sx * TIRE_X, TIRE_R, za)))
    for zc in ((AXLE_Z[0] + AXLE_Z[1]) * 0.5, (AXLE_Z[2] + AXLE_Z[3]) * 0.5):
        for sx in (1.0, -1.0):
            b.add_mesh(make_box((0.6, 0.08, 2.9), dark,
                                offset=(sx * TIRE_X, 2.0 * TIRE_R + 0.10, zc)))
    # side equipment lockers between the axle groups (fills the bare frame)
    for sx in (1.0, -1.0):
        b.add_mesh(make_box((0.40, 0.72, 2.1), dark,
                            offset=(sx * (CHASSIS_W * 0.5 - 0.22), 0.95, 0.1)))

    # the 2x2 tube block, elevated about +X at the pivot
    elev = rot_x(-math.radians(elevation_deg))  # rot_x(-a) tips +Z up to +Y
    b.add_mesh(_tube_block(dark), rotation=elev, offset=(0.0, PIVOT_Y, PIVOT_Z))
    # trunnion bearings at the pivot
    for sx in (1.0, -1.0):
        b.add_mesh(make_box((0.3, 0.9, 0.7), dark,
                            offset=(sx * (TUBE_X + TUBE_R + 0.2),
                                    FRAME_TOP + 0.45, PIVOT_Z)))
    # cradle beam under the stowed tube noses
    b.add_mesh(make_box((2.3, 0.22, 0.45), dark,
                        offset=(0.0, FRAME_TOP + 0.11, 1.4)))

    # 4 outrigger jacks
    for zr in RIG_Z:
        for sx in (1.0, -1.0):
            b.add_mesh(make_box(RIG_SIZE, dark,
                                offset=(sx * RIG_X, RIG_SIZE[1] * 0.5, zr)))
    return b.build()


# --- 48N6 missile ----------------------------------------------------------------
# Body stations (z, meters from mid-body origin; nose at +3.75)
_TAIL_Z = -3.75
_TAIL_R = 0.21                 # nozzle exit radius (dark tail disc)
_BOAT_Z = -3.42                # boat-tail blends into the full body here
_BODY_R = 0.2575               # diameter 0.515
_OGIVE_Z = 1.55                # ogive taper begins
_TIP_BASE_Z = 3.32             # dark radome tip cone starts
_TIP_BASE_R = 0.085
_NOSE_Z = 3.75


def _ogive_profile():
    """Convex taper from the cylinder to the radome base: (z, r) points."""
    pts = []
    for z in np.linspace(_OGIVE_Z, _TIP_BASE_Z, 8)[1:]:
        t = (z - _OGIVE_Z) / (_TIP_BASE_Z - _OGIVE_Z)
        pts.append((float(z), _BODY_R - (_BODY_R - _TIP_BASE_R) * t ** 1.7))
    return pts


def build_s300_missile() -> MeshData:
    b = MeshBuilder()
    body_c = PALETTE["missile_body"]
    fin_c = PALETTE["fin"]

    # dark nozzle: flat tail disc + short boat-tail band
    boat_r = _TAIL_R + (_BODY_R - _TAIL_R) * 0.45
    b.add_mesh(make_lathe([(_TAIL_Z, 0.0), (_TAIL_Z, _TAIL_R),
                           (_TAIL_Z + 0.15, boat_r)], SEG,
                          PALETTE["exhaust_ring"]))
    # body: boat-tail -> clean cylinder -> ogive
    profile = [(_TAIL_Z + 0.15, boat_r), (_BOAT_Z, _BODY_R),
               (_OGIVE_Z, _BODY_R)]
    profile += _ogive_profile()
    b.add_mesh(make_lathe(profile, SEG, body_c))
    # dark radome tip out to the nose point
    b.add_mesh(make_lathe([(_TIP_BASE_Z, _TIP_BASE_R), (_NOSE_Z, 0.0)], SEG,
                          PALETTE["radome"]))

    # 4 clipped tail fins, X pattern, roots buried in the body wall
    fin = make_fin(1.05, 0.45, 0.52, 0.55, 0.035, fin_c,
                   offset=(0.235, 0.0, -2.55))
    for k in range(4):
        b.add_mesh(fin, rotation=rot_z(math.radians(45.0 + 90.0 * k)))
    # 4 small cruciform strakes near mid-body
    strake = make_fin(0.9, 0.55, 0.16, 0.25, 0.03, fin_c,
                      offset=(0.24, 0.0, 0.85))
    for k in range(4):
        b.add_mesh(strake, rotation=rot_z(math.radians(45.0 + 90.0 * k)))
    return b.build()
