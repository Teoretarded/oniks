"""S-300 battery models: the 5P85-style 4-tube TEL and the 48N6 interceptor.

``build_s300_tel(elevation_deg)`` is a ~13 m 8-wheel MAZ-style chassis with a
flat-front cab and FOUR launch tubes (r 0.55, len 8.2) in a 2x2 block. Task
OM2 proportions per docs/research/s300_reference.md: the block pivots about
+X at the REAR overhang (stowed tubes overhang the tail, mouths just behind
the F3S cabin; erected just aft of the rear axles), tube tops reach ~9.1 m
when erect ? towering ~2.6x over the cab ? with black dome bottom caps
hanging ~0.6 m off the ground, 4 clamp rings segmenting each barrel, khaki
canvas mouth covers, and the boxy sloped-roof F3S electronics cabin directly
behind the cab. Deliberately distinct from the Bastion TEL silhouette: boxy
flat cab vs wedge, 4-tube grey block vs 2 green canisters.

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
                             make_fin, make_lathe, make_wedge)
from models.common import PALETTE, rot_x, rot_z

SEG = 28                       # lathe/cylinder segments

# --- TEL: chassis ---------------------------------------------------------------
CHASSIS_L = 13.0
CHASSIS_W = 3.05
FRAME_BOT = 0.55               # deck underside (ground clearance)
FRAME_TOP = 1.45               # flat bed height

# Flat-front cab on the bed nose (front face flush with the chassis front)
CAB_W, CAB_H, CAB_L = 3.05, 2.05, 2.6
CAB_TOP = FRAME_TOP + CAB_H    # 3.5

# F3S electronics cabin directly behind the cab (5P85S "master"): boxy,
# nearly cab-tall, with a sloped-roof wedge dropping toward the cab.
F3S_W, F3S_H, F3S_L = 2.9, 1.7, 2.5
F3S_Z = CHASSIS_L * 0.5 - CAB_L - F3S_L * 0.5 - 0.05   # z center: 1.3..3.8
F3S_ROOF_H = 0.35

# Wheels: 8 tires (4 axles: 2 forward under the cab, 2 aft clear of the
# erected block on the rear overhang)
TIRE_R = 0.70
TIRE_W = 0.50
AXLE_Z = (5.0, 3.4, -2.6, -4.2)
TIRE_X = CHASSIS_W * 0.5 - 0.10

# --- TEL: launch-tube block ------------------------------------------------------
TUBE_R = 0.55
TUBE_LEN = 8.2
TUBE_X = 0.63                  # half the side-by-side spacing
PAIR_DY = 1.28                 # stowed vertical gap lower->upper tube centers
PIVOT_BACK = 1.1               # pivot-to-tail distance along the tube
PIVOT_Y = FRAME_TOP + TUBE_R   # stowed lower pair rests on the bed (2.0)
PIVOT_Z = -5.9                 # rear overhang: erect block aft of the axles
CAP_R = 0.58                   # mouth-cover collar radius (khaki canvas)
CAP_LEN = 0.16
RING_R = TUBE_R + 0.035        # clamp ring radius (proud of the barrel)
RING_LEN = 0.12
RING_RUNS = (-0.5, 1.6, 3.7, 5.8)   # ring stations along the tube axis
# Extra narrow seams reproduce the strongly segmented TPK silhouette while
# retaining RING_RUNS as the public/reference set used by older tests/tools.
DETAIL_RING_RUNS = (0.55, 2.65, 4.75, 6.72)
DOME_DEPTH = 0.30              # black dome bottom cap bulge

# Outriggers: 4 jack boxes clear of the tires and the erected block
RIG_SIZE = (0.7, 0.9, 0.5)
RIG_X = 1.62
RIG_Z = (1.0, -6.2)

# Mouth of a LOWER tube relative to the pivot, along the tube axis (world/
# world.py Task S4 derives the vertical-launch mouth point from these).
MOUTH_RUN = TUBE_LEN - PIVOT_BACK   # 7.1: erect tops at PIVOT_Y + 7.1 = 9.1 m


def _dome_profile() -> list:
    """(z, r) lathe points for the black dome bottom cap bulging backward
    from the tube tail plane at z = -PIVOT_BACK."""
    pts = [(-PIVOT_BACK - DOME_DEPTH, 0.0)]
    for a in np.linspace(np.pi * 0.5, 0.0, 5)[1:]:
        pts.append((-PIVOT_BACK - DOME_DEPTH * math.sin(a),
                    TUBE_R * math.cos(a)))
    return pts


def _tube_block(dark_green: tuple) -> MeshData:
    """The 2x2 tube assembly in pivot space: tube axes along +Z spanning
    z in [-PIVOT_BACK, MOUTH_RUN]; lower pair at dy 0, upper at dy PAIR_DY.
    Each barrel carries 4 clamp rings, a khaki canvas mouth cover and a
    black dome bottom cap (s300_reference.md signatures 4 and 10)."""
    b = MeshBuilder()
    tube_c = PALETTE["tube_grey"]
    ring_c = PALETTE["tube_ring"]
    z_mid = MOUTH_RUN * 0.5 - PIVOT_BACK * 0.5
    dome = make_lathe(_dome_profile(), SEG, PALETTE["exhaust_ring"])
    for dy in (0.0, PAIR_DY):
        for sx in (1.0, -1.0):
            off = (sx * TUBE_X, dy, 0.0)
            b.add_mesh(make_cylinder(TUBE_R, TUBE_LEN, SEG, tube_c, axis="z",
                                     offset=(off[0], off[1], z_mid)))
            # khaki canvas cover collar at the mouth, dome cap at the tail
            b.add_mesh(make_cylinder(CAP_R, CAP_LEN, SEG,
                                     PALETTE["canvas_khaki"], axis="z",
                                     offset=(off[0], off[1],
                                             MOUTH_RUN - CAP_LEN * 0.5)))
            b.add_mesh(make_cylinder(CAP_R * 0.92, 0.045, SEG,
                                     PALETTE["canvas_khaki"], axis="z",
                                     offset=(off[0], off[1],
                                             MOUTH_RUN - 0.023)))
            b.add_mesh(dome, offset=off)
            # clamp rings segmenting the barrel
            for zr in RING_RUNS + DETAIL_RING_RUNS:
                b.add_mesh(make_cylinder(RING_R, RING_LEN, SEG, ring_c,
                                         axis="z",
                                         offset=(off[0], off[1], zr)))
            # Narrow external cable/umbilical conduit on each outer barrel.
            b.add_mesh(make_box((0.07, 0.10, 6.75), dark_green,
                                offset=(off[0] + math.copysign(TUBE_R, off[0]),
                                        off[1] - 0.38, 2.25)))
    # inter-tube frame: a + of plates between the four tubes at 3 stations
    green = PALETTE["s300_green"]
    for zs in (-0.7, 2.6, 5.2):
        b.add_mesh(make_box((2.0 * (TUBE_X + TUBE_R), 0.14, 0.30), green,
                            offset=(0.0, PAIR_DY * 0.5, zs)))
        b.add_mesh(make_box((0.14, PAIR_DY + 2.0 * TUBE_R, 0.30), green,
                            offset=(0.0, PAIR_DY * 0.5, zs)))
    # Erecting spine and U-shaped umbilical bridge between the four tubes.
    b.add_mesh(make_box((0.26, PAIR_DY + 1.15, 7.35), dark_green,
                        offset=(0.0, PAIR_DY * 0.5, 2.15)))
    b.add_mesh(make_box((1.42, 0.12, 0.20), dark_green,
                        offset=(0.0, PAIR_DY + TUBE_R - 0.08, 6.32)))
    for sx in (-1.0, 1.0):
        b.add_mesh(make_box((0.12, 0.40, 0.20), dark_green,
                            offset=(sx * 0.65, PAIR_DY + TUBE_R - 0.25, 6.32)))
    return b.build()


def _add_maz_cab(b: MeshBuilder, green: tuple, dark: tuple) -> None:
    """Asymmetric MAZ-7910 nose: left crew cab, right engine housing."""
    front_z = CHASSIS_L * 0.5
    cab_z = front_z - CAB_L * 0.5

    # The 5P85's split nose is its most important non-tube identifier.
    driver_x = -0.78
    b.add_mesh(make_box((1.36, CAB_H, CAB_L), green,
                        offset=(driver_x, FRAME_TOP + CAB_H * 0.5, cab_z)))
    b.add_mesh(make_box((1.52, 1.48, CAB_L - 0.08), green,
                        offset=(0.72, FRAME_TOP + 0.74, cab_z - 0.02)))

    # Sloped two-pane glazing on the driver module, side window, and door.
    for x in (-1.06, -0.52):
        b.add_mesh(make_box((0.44, 0.58, 0.065), PALETTE["radome"]),
                   rotation=rot_x(math.radians(5.0)),
                   offset=(x, CAB_TOP - 0.57, front_z + 0.025))
    b.add_mesh(make_box((0.055, 0.52, 0.90), PALETTE["radome"],
                        offset=(-1.48, CAB_TOP - 0.61, cab_z + 0.12)))
    b.add_mesh(make_box((0.045, 1.00, 0.96), dark,
                        offset=(-1.49, 1.88, cab_z - 0.48)))

    # Right-side radiator grille: deep recess plus vertical slats.
    b.add_mesh(make_box((1.24, 0.66, 0.055), PALETTE["tire"],
                        offset=(0.72, 2.02, front_z + 0.03)))
    for x in np.linspace(0.18, 1.26, 7):
        b.add_mesh(make_box((0.045, 0.59, 0.075), dark,
                            offset=(float(x), 2.02, front_z + 0.07)))

    # Bumper, lamps, tow bar, roof lamp and mirror.
    b.add_mesh(make_box((CHASSIS_W, 0.28, 0.24), dark,
                        offset=(0.0, FRAME_BOT + 0.14, front_z + 0.10)))
    b.add_mesh(make_cylinder(0.065, 2.10, 10, dark, axis="x",
                             offset=(0.0, 0.92, front_z + 0.08)))
    for x in (-1.05, 1.06):
        b.add_mesh(make_cylinder(0.15, 0.075, 12, PALETTE["radar_white"],
                                 axis="z", offset=(x, 1.45, front_z + 0.14)))
    b.add_mesh(make_cylinder(0.13, 0.20, 12, PALETTE["radar_white"], axis="y",
                             offset=(-0.82, CAB_TOP + 0.10, cab_z + 0.35)))
    b.add_mesh(make_cylinder(0.025, 0.30, 8, dark, axis="x",
                             offset=(-1.61, 2.70, cab_z + 0.34)))
    b.add_mesh(make_box((0.055, 0.38, 0.22), PALETTE["radome"],
                        offset=(-1.76, 2.70, cab_z + 0.34)))


def _add_f3s_cabin(b: MeshBuilder, green: tuple, dark: tuple) -> None:
    """Electronics cabin with the canvas cover and tie-downs seen on 5P85S."""
    b.add_mesh(make_box((F3S_W, F3S_H, F3S_L), green,
                        offset=(0.0, FRAME_TOP + F3S_H * 0.5, F3S_Z)))
    b.add_mesh(make_wedge((F3S_W, F3S_ROOF_H, F3S_L), green,
                          offset=(0.0, FRAME_TOP + F3S_H + F3S_ROOF_H * 0.5,
                                  F3S_Z)))
    canvas = PALETTE["canvas_khaki"]
    for sx in (-1.0, 1.0):
        b.add_mesh(make_box((0.055, F3S_H - 0.16, F3S_L - 0.14), canvas,
                            offset=(sx * (F3S_W * 0.5 + 0.02),
                                    FRAME_TOP + F3S_H * 0.5, F3S_Z)))
        # Three vertical tie-down straps per side.
        for zz in (F3S_Z - 0.78, F3S_Z, F3S_Z + 0.78):
            b.add_mesh(make_box((0.065, F3S_H - 0.08, 0.055), dark,
                                offset=(sx * (F3S_W * 0.5 + 0.055),
                                        FRAME_TOP + F3S_H * 0.5, zz)))
    b.add_mesh(make_box((F3S_W - 0.16, F3S_H - 0.12, 0.055), canvas,
                        offset=(0.0, FRAME_TOP + F3S_H * 0.5,
                                F3S_Z - F3S_L * 0.5 - 0.02)))


def build_s300_tel(elevation_deg: float = 0.0) -> MeshData:
    b = MeshBuilder()
    green = PALETTE["s300_green"]
    dark = PALETTE["mil_green_dark"]

    # Twin ladder rails with a thin deck, rather than one featureless slab.
    b.add_mesh(make_box((CHASSIS_W, 0.24, CHASSIS_L), green,
                        offset=(0.0, FRAME_TOP - 0.12, 0.0)))
    for sx in (-1.0, 1.0):
        b.add_mesh(make_box((0.34, FRAME_TOP - FRAME_BOT, CHASSIS_L - 0.25),
                            dark,
                            offset=(sx * 0.92,
                                    (FRAME_BOT + FRAME_TOP) * 0.5, -0.05)))
    for zc in (-5.35, -3.0, -0.5, 2.0, 4.75):
        b.add_mesh(make_box((2.36, 0.14, 0.24), dark,
                            offset=(0.0, 0.78, zc)))

    _add_maz_cab(b, green, dark)
    _add_f3s_cabin(b, green, dark)

    # 8 wheels + mudguard strips over each axle pair
    for za in AXLE_Z:
        for sx in (1.0, -1.0):
            b.add_mesh(make_cylinder(TIRE_R, TIRE_W, 18, PALETTE["tire"],
                                     axis="x", offset=(sx * TIRE_X, TIRE_R, za)))
            b.add_mesh(make_cylinder(0.27, TIRE_W + 0.06, 14, dark,
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
    # cradle beam under the stowed tube noses (mouths now reach z ~1.2)
    b.add_mesh(make_box((2.3, 0.22, 0.45), dark,
                        offset=(0.0, FRAME_TOP + 0.11, 0.8)))

    # Four auto-levelling jacks: stowed close to the chassis in travel and
    # lowered onto pads with the tube block erect.
    deployed = abs(float(elevation_deg)) > 5.0
    for zr in RIG_Z:
        for sx in (1.0, -1.0):
            if deployed:
                b.add_mesh(make_box((0.68, 0.18, 0.34), dark,
                                    offset=(sx * 1.60, 0.98, zr)))
                b.add_mesh(make_box((0.18, 0.94, 0.18), dark,
                                    offset=(sx * 1.82, 0.49, zr)))
                b.add_mesh(make_box((0.34, 0.08, 0.46), PALETTE["tire"],
                                    offset=(sx * 1.82, 0.04, zr)))
            else:
                b.add_mesh(make_box((0.24, 0.84, 0.44), dark,
                                    offset=(sx * 1.42, 0.88, zr)))
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
