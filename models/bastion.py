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
from models.common import PALETTE, rot_x, rot_z

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

# The real K-340P carries the stowed pair inside a tall, faceted weather
# enclosure.  These dimensions fit that enclosure around the locked launch
# pivot without moving the launch mouth used by world/world.py.
SHROUD_Z0, SHROUD_Z1 = -6.72, 3.30
SHROUD_TOP = 3.78

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
    tube_c = PALETTE["oniks_body"]
    for sx in (1.0, -1.0):
        x = sx * CAN_X
        b.add_mesh(make_cylinder(CAN_R, CAN_LEN, 24, tube_c, axis="z",
                                 offset=(x, 0.0, z_mid)))
        # Mouth cover, tail exhaust ring, and the segmented TPK hoops visible
        # in both parade and deployed views.
        b.add_mesh(make_cylinder(COLLAR_R, COLLAR_LEN, 24, green, axis="z",
                                 offset=(x, 0.0, mouth_z - COLLAR_LEN * 0.5)))
        b.add_mesh(make_cylinder(CAN_R * 0.92, 0.045, 24,
                                 PALETTE["canvas_khaki"], axis="z",
                                 offset=(x, 0.0, mouth_z - 0.023)))
        b.add_mesh(make_cylinder(COLLAR_R, COLLAR_LEN, 24,
                                 PALETTE["exhaust_ring"], axis="z",
                                 offset=(x, 0.0,
                                         -PIVOT_BACK + COLLAR_LEN * 0.5)))
        for zc in (-1.35, 0.05, 1.45, 2.85, 4.25, 5.65):
            b.add_mesh(make_cylinder(CAN_R + 0.03, 0.16, 24, green, axis="z",
                                     offset=(x, 0.0, zc)))
    # Shared lifting cradle: cross-ties, central hydraulic spine, and the
    # narrow cable tray between the two containers.
    for zs in (-1.8, 0.8, 3.4, 5.85):
        b.add_mesh(make_box((2.0 * (CAN_X + CAN_R), 0.16, 0.26), green,
                            offset=(0.0, -0.12, zs)))
    b.add_mesh(make_box((0.22, 0.32, 7.8), dark,
                        offset=(0.0, -0.42, 1.45)))
    b.add_mesh(make_cylinder(0.10, 6.9, 12, PALETTE["pipe"], axis="z",
                             offset=(0.0, -0.65, 1.25)))
    return b.build()


def _add_cab(b: MeshBuilder, green: tuple, dark: tuple, glass: tuple) -> None:
    """Faceted MZKT-7930 cab with the K-340P's wide three-pane windscreen."""
    cab_mid_z = (CAB_Z0 + CAB_Z1) * 0.5
    b.add_mesh(make_box((CAB_W, CAB_TOP - RAIL_TOP, CAB_Z1 - CAB_Z0), green,
                        offset=(0.0, (RAIL_TOP + CAB_TOP) * 0.5, cab_mid_z)))
    # Roof brow and three separate panes; mullions are an important front-view
    # signature and prevent the cab reading as one glass slab.
    b.add_mesh(make_box((CAB_W, 0.22, 0.34), green),
               rotation=rot_x(math.radians(7.0)),
               offset=(0.0, CAB_TOP - 0.02, CAB_Z1 - 0.10))
    for x in (-0.86, 0.0, 0.86):
        b.add_mesh(make_box((0.73, 0.66, 0.055), glass,
                            offset=(x, CAB_TOP - 0.55, CAB_Z1 + 0.025)))
    # Cab doors, side glazing, and paired mirrors.
    for sx in (1.0, -1.0):
        b.add_mesh(make_box((0.055, 0.58, 0.95), glass,
                            offset=(sx * (CAB_W * 0.5 + 0.02), CAB_TOP - 0.58,
                                    CAB_Z1 - 0.66)))
        b.add_mesh(make_box((0.045, 1.08, 1.05), dark,
                            offset=(sx * (CAB_W * 0.5 + 0.025), 1.62,
                                    CAB_Z1 - 0.72)))
        b.add_mesh(make_cylinder(0.025, 0.34, 8, dark, axis="x",
                                 offset=(sx * 1.58, 2.63, CAB_Z1 - 0.45)))
        b.add_mesh(make_box((0.055, 0.42, 0.24), PALETTE["radome"],
                            offset=(sx * 1.76, 2.63, CAB_Z1 - 0.45)))

    # Heavy bumper, winch/grille, tow points, and split lamp clusters.
    b.add_mesh(make_box((CAB_W, 0.30, 0.24), dark,
                        offset=(0.0, 0.84, CAB_Z1 + 0.09)))
    b.add_mesh(make_box((1.52, 0.50, 0.055), PALETTE["tire"],
                        offset=(0.0, 1.43, CAB_Z1 + 0.035)))
    for y in (1.28, 1.43, 1.58):
        b.add_mesh(make_box((1.42, 0.035, 0.065), green,
                            offset=(0.0, y, CAB_Z1 + 0.07)))
    for sx in (1.0, -1.0):
        b.add_mesh(make_cylinder(0.13, 0.07, 12, PALETTE["radar_white"],
                                 axis="z", offset=(sx * 1.05, 1.42,
                                                   CAB_Z1 + 0.12)))
        b.add_mesh(make_box((0.18, 0.10, 0.08), PALETTE["canvas_khaki"],
                            offset=(sx * 1.05, 1.13, CAB_Z1 + 0.12)))


def _add_weather_enclosure(b: MeshBuilder, green: tuple, dark: tuple,
                           deployed: bool = False) -> None:
    """K-340P equipment enclosure in its closed or launch-ready state."""
    z_mid = (SHROUD_Z0 + SHROUD_Z1) * 0.5
    z_len = SHROUD_Z1 - SHROUD_Z0
    # Lower service body and upper equipment volume.
    b.add_mesh(make_box((HULL_W, 1.45, z_len), green,
                        offset=(0.0, RAIL_TOP + 0.725, z_mid)))
    if deployed:
        # The real launcher keeps its tall side body but opens the long roof
        # around the erecting pair.  Separate walls and near-vertical hinged
        # lids make that opening explicit instead of letting the tubes appear
        # to pass through a closed solid box.
        for sx in (1.0, -1.0):
            b.add_mesh(make_box((0.42, 1.62, z_len - 0.12), green,
                                offset=(sx * 1.15, 2.99, z_mid)))
            b.add_mesh(make_box((1.18, 0.12, z_len - 0.10), green),
                       rotation=rot_z(math.radians(72.0 * sx)),
                       offset=(sx * 1.43, 3.24, z_mid))
    else:
        b.add_mesh(make_box((2.72, 1.62, z_len - 0.12), green,
                            offset=(0.0, 2.18 + 0.81, z_mid)))
        # Broad flat roof with chamfered shoulders, matching the K-340P's
        # covered travel silhouette.
        b.add_mesh(make_box((1.52, 0.12, z_len - 0.10), green,
                            offset=(0.0, SHROUD_TOP - 0.06, z_mid)))
        for sx in (1.0, -1.0):
            angle = math.radians(-14.0 * sx)
            b.add_mesh(make_box((1.05, 0.12, z_len - 0.10), green),
                       rotation=rot_z(angle),
                       offset=(sx * 1.02, SHROUD_TOP - 0.19, z_mid))

    for sx in (1.0, -1.0):
        # Service-door outlines and ventilation bank on the long flanks.
        for zc in (-3.8, -1.2, 1.35):
            b.add_mesh(make_box((0.045, 0.88, 1.55), dark,
                                offset=(sx * (HULL_W * 0.5 + 0.02), 2.25, zc)))
        for zv in (-0.35, 0.0, 0.35):
            b.add_mesh(make_box((0.055, 0.055, 1.10), PALETTE["tire"],
                                offset=(sx * (HULL_W * 0.5 + 0.045),
                                        2.86 + zv, 2.45)))
    # Rear access bulkhead and hinge line.
    b.add_mesh(make_box((2.72, 2.70, 0.16), dark,
                        offset=(0.0, 2.20, SHROUD_Z0 - 0.02)))
    b.add_mesh(make_box((2.30, 0.08, 0.20), green,
                        offset=(0.0, 3.42, SHROUD_Z0 - 0.12)))
    # Closed forward wall hides the tube mouths in the travel configuration.
    if not deployed:
        b.add_mesh(make_box((2.72, 2.70, 0.16), green,
                            offset=(0.0, 2.20, SHROUD_Z1 + 0.02)))


def build_bastion_tel(elevation_deg: float = 0.0) -> MeshData:
    b = MeshBuilder()
    green = PALETTE["mil_green"]
    dark = PALETTE["mil_green_dark"]
    black = PALETTE["tire"]
    glass = PALETTE["radome"]

    # Ladder chassis and cross-members beneath the enclosed equipment body.
    b.add_mesh(make_box((HULL_W - 0.30, RAIL_TOP - HULL_BOTTOM, HULL_L), black,
                        offset=(0.0, (HULL_BOTTOM + RAIL_TOP) * 0.5, 0.0)))
    for zc in (-4.8, -2.2, 0.4, 3.0, 5.0):
        b.add_mesh(make_box((HULL_W - 0.08, 0.12, 0.24), dark,
                            offset=(0.0, 0.62, zc)))

    deployed = abs(float(elevation_deg)) > 5.0
    _add_weather_enclosure(b, green, dark, deployed=deployed)

    # Cab and the visible machinery gap separating it from the launcher box.
    _add_cab(b, green, dark, glass)
    b.add_mesh(make_box((2.3, 0.92, CAB_Z0 - BAY_Z1 + 0.1), dark,
                        offset=(0.0, RAIL_TOP + 0.46,
                                (BAY_Z1 + CAB_Z0) * 0.5)))

    # 8 wheels, recessed wells, proud hubs, and paired mudguard eyebrows.
    for za in AXLE_Z:
        for sx in (1.0, -1.0):
            b.add_mesh(make_box((0.07, 1.04, 1.36), black,
                                offset=(sx * (HULL_W * 0.5 + 0.015),
                                        HULL_BOTTOM + 0.52, za)))
            b.add_mesh(make_cylinder(TIRE_R, TIRE_W, 18, black,
                                     axis="x", offset=(sx * TIRE_X, TIRE_R, za)))
            b.add_mesh(make_cylinder(0.24, TIRE_W + 0.06, 14, dark,
                                     axis="x", offset=(sx * TIRE_X, TIRE_R, za)))
    for zc in ((AXLE_Z[0] + AXLE_Z[1]) * 0.5, (AXLE_Z[2] + AXLE_Z[3]) * 0.5):
        for sx in (1.0, -1.0):
            b.add_mesh(make_box((0.55, 0.09, 2.95), dark,
                                offset=(sx * TIRE_X, 1.40, zc)))

    # the canister pair + shared hardware, elevated about +X at the pivot
    elev = rot_x(-math.radians(elevation_deg))   # rot_x(-a) tips +Z up to +Y
    b.add_mesh(_canister_block(green, dark), rotation=elev,
               offset=(0.0, PIVOT_Y, PIVOT_Z))
    # Trunnion bearings and the two visible hydraulic lift rams.
    for sx in (1.0, -1.0):
        b.add_mesh(make_box((0.28, 0.85, 0.7), dark,
                            offset=(sx * (CAN_X + CAN_R + 0.18),
                                    HULL_TOP + 0.25, PIVOT_Z)))
        ram = make_cylinder(0.085, 2.35, 12, PALETTE["pipe"], axis="z")
        b.add_mesh(ram, rotation=rot_x(math.radians(-24.0)),
                   offset=(sx * 0.82, 2.48, -3.10))
    # cradle beam under the canisters' front end (stays on the roof)
    b.add_mesh(make_box((2.2, 0.25, 0.5), dark,
                        offset=(0.0, HULL_TOP + 0.125, 2.6)))

    # Four jacks: tucked against the body in travel, lowered and splayed with
    # the launcher raised.  The public elevation API stays the state driver.
    for zr in RIG_Z:
        for sx in (1.0, -1.0):
            if deployed:
                b.add_mesh(make_box((0.72, 0.18, 0.34), dark,
                                    offset=(sx * 1.58, 1.05, zr)))
                b.add_mesh(make_box((0.18, 1.02, 0.18), dark,
                                    offset=(sx * 1.78, 0.53, zr)))
                b.add_mesh(make_box((0.42, 0.08, 0.52), black,
                                    offset=(sx * 1.78, 0.04, zr)))
            else:
                b.add_mesh(make_box((0.24, 0.86, 0.44), dark,
                                    offset=(sx * 1.37, 0.90, zr)))
    return b.build()
