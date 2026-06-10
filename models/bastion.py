"""Bastion coastal-battery TEL (transporter-erector-launcher) model.

An ~12 m 8-wheel military truck carrying TWO Oniks launch canisters side by
side. ``build_bastion_tel(elevation_deg)`` rotates the canisters about +X
(pivot near the canister tail) — 0 deg = stowed flat on the bed, 88 deg =
raised for launch; the rear ends swing down inside the hull like an S-300
erector so the raised battery stays under 10 m tall.

Model space: forward = +Z (cab at max Z), up = +Y, origin at ground center.
Pure numpy / GL-free.
"""

from __future__ import annotations

import math

import numpy as np

from engine.meshdata import MeshBuilder, MeshData, make_box, make_cylinder, make_wedge
from models.common import PALETTE, rot_x

# Hull (chassis + equipment body): one long box, low ground clearance
HULL_L = 11.5
HULL_W = 2.9
HULL_H = 2.6
HULL_BOTTOM = 0.3
HULL_TOP = HULL_BOTTOM + HULL_H            # 2.9

# Cab: wedge on the hull roof at the front (slope = windshield, faces +Z)
CAB_W, CAB_H, CAB_L = 2.9, 1.0, 2.4

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

# Outriggers: 4 jack boxes at the corner overhangs (clear of the tires)
RIG_SIZE = (0.8, 0.9, 0.5)
RIG_X = 1.55
RIG_Z = (5.4, -5.4)


def build_bastion_tel(elevation_deg: float = 0.0) -> MeshData:
    b = MeshBuilder()
    green = PALETTE["mil_green"]
    dark = PALETTE["mil_green_dark"]

    # hull + cab
    b.add_mesh(make_box((HULL_W, HULL_H, HULL_L), green,
                        offset=(0.0, HULL_BOTTOM + HULL_H * 0.5, 0.0)))
    b.add_mesh(make_wedge((CAB_W, CAB_H, CAB_L), green,
                          offset=(0.0, HULL_TOP + CAB_H * 0.5,
                                  HULL_L * 0.5 - CAB_L * 0.5)))
    # dark windshield plate laid on the cab slope (slope normal: (0, 2.4, 1.0))
    ws_tilt = rot_x(-(0.5 * math.pi - math.atan2(CAB_H, CAB_L)))
    b.add_mesh(make_box((2.3, 0.5, 0.08), PALETTE["radome"]), rotation=ws_tilt,
               offset=(0.0, HULL_TOP + CAB_H * 0.5 + 0.04,
                       HULL_L * 0.5 - CAB_L * 0.5 + 0.02))

    # 8 wheels
    for za in AXLE_Z:
        for sx in (1.0, -1.0):
            b.add_mesh(make_cylinder(TIRE_R, TIRE_W, 18, PALETTE["tire"],
                                     axis="x", offset=(sx * TIRE_X, TIRE_R, za)))

    # two launch canisters, elevated about +X at the pivot
    elev = rot_x(-math.radians(elevation_deg))   # rot_x(-a) tips +Z up toward +Y
    can = make_cylinder(CAN_R, CAN_LEN, 24, dark, axis="z",
                        offset=(0.0, 0.0, CAN_LEN * 0.5 - PIVOT_BACK))
    for sx in (1.0, -1.0):
        b.add_mesh(can, rotation=elev, offset=(sx * CAN_X, PIVOT_Y, PIVOT_Z))
    # cradle beam under the canisters' front end (stays on the roof)
    b.add_mesh(make_box((2.2, 0.25, 0.5), dark,
                        offset=(0.0, HULL_TOP + 0.125, 2.6)))

    # 4 outrigger jacks
    for zr in RIG_Z:
        for sx in (1.0, -1.0):
            b.add_mesh(make_box(RIG_SIZE, dark,
                                offset=(sx * RIG_X, RIG_SIZE[1] * 0.5, zr)))
    return b.build()
