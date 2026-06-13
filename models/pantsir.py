"""Pantsir-S1 short-range SHORAD system model.

``build_pantsir()`` is the ~8 m KAMAZ-style 8×8 heavy truck chassis carrying
a central rotating turret with:
  - TWO blocks of 6 missile canisters (12 × 57E6, 6 canisters per side) boxy
    tubes angled slightly upward, one block per side of the turret,
  - Twin 30 mm 2A38M cannon barrels mounted below/between the tube blocks on
    each side (two long thin cylinders, the signature "horns"),
  - A flat phased-array tracking radar panel on the turret front face,
  - A search-radar drum on top of the turret (small cylinder / disc).

Real-world references (Pantsir-S1, export "SA-22 Greyhound"):
  - Chassis: KAMAZ-6560 8×8, ~10.8 m long, ~2.57 m wide (body), ~3 m wide
    with mudguards; combat weight ~24 t.  We model the armoured cab + rear
    equipment bay at 8.0 m × 3.0 m (slightly generous for visual clarity).
  - Turret ring diameter ~1.6 m; turret body ~2.0 m wide × ~1.8 m tall.
  - 57E6 canisters: roughly 0.30 m × 0.30 m square cross-section, ~3.2 m
    long; 6 stacked 3-high × 2-wide per side on oblique launch rails.
  - 2A38M barrel length ~2.4 m exposed, diameter ~0.06 m.
  - Tracking radar: 1E20 flat array ~0.8 m × 0.8 m on the turret nose.
  - Search radar: small drum ~0.55 m diameter × 0.25 m, on the turret top.

Model space per LOCKED CONVENTIONS: forward = +Z, up = +Y, real meters,
origin at the ground center.  Wheels at y ≈ 0, chassis top at y ≈ FRAME_TOP.

Pure numpy, GL-free.
"""

from __future__ import annotations

import math

import numpy as np

from engine.meshdata import (MeshBuilder, MeshData, make_box,
                             make_cylinder, make_wedge)
from models.common import PALETTE, rot_x, rot_y, rot_z

# ---------------------------------------------------------------------------
# Segment count for cylinders / lathe — matches s300.py low-poly style
# ---------------------------------------------------------------------------
SEG = 16        # barrels / turret drum — fewer than S-300 (shorter features)
SEG_TIRE = 14   # tires

# ---------------------------------------------------------------------------
# Chassis dimensions (KAMAZ-6560 8×8)
# Length 8.0 m is the armoured body box; the real chassis is ~10.8 m but we
# keep the visual block compact to match the game's stylised density.
# Width 3.0 m matches the spec requirement.
# ---------------------------------------------------------------------------
CHASSIS_L   = 8.0   # m  length along +Z
CHASSIS_W   = 3.0   # m  width along ±X (incl. mudguard bulge)
FRAME_BOT   = 0.50  # m  deck underside (ground clearance)
FRAME_TOP   = 1.30  # m  flat deck height above ground

# Armoured cab: boxy flat-front box on the nose
CAB_W = 2.80   # m
CAB_H = 1.70   # m  (cab top at FRAME_TOP + CAB_H = 3.0 m)
CAB_L = 2.60   # m

# Rear equipment / powerpack bay (lower than the cab)
BAY_W = 2.80
BAY_H = 1.10
BAY_L = 2.40

# ---------------------------------------------------------------------------
# Wheels: 8 tires on 4 axles (8×8)
# 4 axles equally spaced under the chassis.
# ---------------------------------------------------------------------------
TIRE_R   = 0.58    # m radius
TIRE_W   = 0.38    # m width
# Axle z-positions (origin = chassis centre)
_HALF_L  = CHASSIS_L * 0.5
AXLE_Z   = (
    _HALF_L - 0.90,   # fwd axle 1 (under cab)
    _HALF_L - 2.00,   # fwd axle 2
    -_HALF_L + 2.00,  # rear axle 1
    -_HALF_L + 0.90,  # rear axle 2
)
TIRE_X   = CHASSIS_W * 0.5 - TIRE_W * 0.10   # inside chassis edge (S-300 pattern)

# ---------------------------------------------------------------------------
# Outrigger stabiliser jacks (2 pairs, fore + aft)
# Tucked inside / at the chassis side wall so they do not widen the bbox.
# ---------------------------------------------------------------------------
RIG_SIZE = (0.65, 0.85, 0.45)   # (w, h, d)
RIG_X    = CHASSIS_W * 0.5 - RIG_SIZE[0] * 0.55   # inside chassis half-width
RIG_Z    = (_HALF_L - 0.5, -_HALF_L + 0.5)

# ---------------------------------------------------------------------------
# Turret (central, rotates about +Y; stowed forward, modelled as fixed)
# Turret sits on the chassis mid-deck, centred at z = 0.
# ---------------------------------------------------------------------------
TURRET_W  = 2.10   # m  turret base ring housing
TURRET_H  = 2.20   # m  main turret box height (raised to give ~5 m total)
TURRET_L  = 2.10   # m  turret fore-aft depth
TURRET_Y  = FRAME_TOP               # bottom of turret at deck level
TURRET_CY = TURRET_Y + TURRET_H * 0.5   # turret box centre y
TURRET_Z  = 0.20   # slight forward bias (signature: radar faces forward)

# Turret ring bearing drum under the main box
RING_R    = 0.82   # m  outer radius
RING_H    = 0.25   # m  height

# ---------------------------------------------------------------------------
# Missile canister blocks  (6 canisters per side: 3 high × 2 deep)
# Canisters: boxy square-section 0.30 m × 0.30 m, length 3.2 m.
# Stacked 3-high, 2-deep on a launch rail angled up ~8° (slight upward tilt
# for visual clarity; real Pantsir canisters angle ~0-10° in stowed position).
# Blocks are offset ±X from the turret centre, at turret mid-height.
# ---------------------------------------------------------------------------
CAN_W = 0.32    # m  canister width/height (square cross-section)
CAN_L = 3.20    # m  canister length

# 3 rows (stacked vertically), 2 columns (fore-aft)
_COLS = 2
_ROWS = 3
CAN_COL_DZ = CAN_L * 0.52    # fore-aft spacing centre-to-centre
CAN_ROW_DY = CAN_W + 0.04    # vertical pitch

# Block centre position relative to turret centre
BLOCK_X    = TURRET_W * 0.5 + 0.05   # flush with / just outside the turret face
BLOCK_Y    = TURRET_Y + TURRET_H * 0.55   # roughly mid-height of the turret box
BLOCK_Z    = TURRET_Z + 0.10

# Slight upward elevation angle for canisters (cosmetic "ready" look)
CAN_ELEV   = math.radians(8.0)   # 8° tip-up about ±X axis

# Rail frame connecting the block to the turret (thin boxy strut each side)
RAIL_W = TURRET_W * 0.5 + BLOCK_X + CAN_L * 0.2
RAIL_H = 0.12
RAIL_L = 0.25

# ---------------------------------------------------------------------------
# Twin 2A38M cannon barrels (per side)
# Mounted at the outer/lower edge of the turret box, one barrel per "horn".
# Real 2A38M: ~2.4 m barrel exposed, 30 mm bore.
# ---------------------------------------------------------------------------
BARREL_R   = 0.040   # m  radius (30 mm bore → ~80 mm OD with jacket)
BARREL_L   = 2.50    # m  exposed barrel length
# Small gun housing box (autoloader drum behind the barrel)
GUN_BOX    = (0.35, 0.38, 0.45)
# Position (relative to origin): below the canister block, outboard of turret
BARREL_X   = BLOCK_X + CAN_W * 0.5 + 0.08   # beyond canister block outer face
BARREL_Y   = TURRET_Y + 0.60                 # low on the turret, above deck
BARREL_Z   = TURRET_Z + BARREL_L * 0.5 + 0.30  # tips point forward

# ---------------------------------------------------------------------------
# Tracking radar (flat phased-array plate on turret front face)
# 1E20 array ~0.8 × 0.8 m, 0.10 m thick, flush-mounted on the +Z face.
# ---------------------------------------------------------------------------
TRACK_W   = 0.82   # m
TRACK_H   = 0.82   # m
TRACK_T   = 0.10   # m  depth / thickness
TRACK_Y   = TURRET_Y + TURRET_H * 0.55   # centred on the turret face
TRACK_Z   = TURRET_Z + TURRET_L * 0.5 + TRACK_T * 0.5   # proud of the face

# ---------------------------------------------------------------------------
# Search radar drum on turret top + short pedestal mast (adds ~0.9 m height)
# Total target: FRAME_TOP(1.3) + TURRET_H(2.2) + MAST(0.9) + SRCH_H(0.25) ≈ 4.65 m
# which is within 20% of the 5.0 m target.
# ---------------------------------------------------------------------------
SRCH_R    = 0.28   # m  radius
SRCH_H    = 0.25   # m  height (drum)
SRCH_MAST = 0.75   # m  pedestal mast under the drum
SRCH_Y    = TURRET_Y + TURRET_H + SRCH_MAST + 0.08   # sits on mast top

# ---------------------------------------------------------------------------
# Colour aliases
# ---------------------------------------------------------------------------
_GREEN = PALETTE["mil_green"]
_DARK  = PALETTE["mil_green_dark"]
_RADAR = PALETTE["radar_white"]
_TIRE  = PALETTE["tire"]
_RADOME = PALETTE["radome"]


# ---------------------------------------------------------------------------
# Internal sub-builders
# ---------------------------------------------------------------------------

def _canister_block(sx: float) -> MeshData:
    """Build 6 missile canisters for one side (sx = +1 for right / -1 for left).

    Each canister is a thin boxy cylinder (square cross-section approximated as
    a box for visual efficiency).  The block is arranged 3-high × 2-deep,
    slightly elevated (CAN_ELEV) about the X axis to give the "ready-to-fire"
    tilt.
    """
    b = MeshBuilder()
    can_c = PALETTE["tube_grey"]
    ring_c = PALETTE["tube_ring"]

    # Local coords before rotation: canisters extend along +Z, origin at block.
    dy_offsets = [i * CAN_ROW_DY - ((_ROWS - 1) * CAN_ROW_DY * 0.5)
                  for i in range(_ROWS)]
    dz_offsets = [i * CAN_COL_DZ - ((_COLS - 1) * CAN_COL_DZ * 0.5)
                  for i in range(_COLS)]

    for dy in dy_offsets:
        for dz in dz_offsets:
            # Canister tube (box; square cross-section)
            b.add_mesh(make_box((CAN_W, CAN_W, CAN_L), can_c,
                                offset=(0.0, dy, dz)))
            # Front cap / muzzle cover (darker thin slab)
            b.add_mesh(make_box((CAN_W - 0.04, CAN_W - 0.04, 0.06),
                                _DARK,
                                offset=(0.0, dy, dz + CAN_L * 0.5)))
            # One clamp ring per canister at ~mid-length
            b.add_mesh(make_box((CAN_W + 0.04, CAN_W + 0.04, 0.08),
                                ring_c,
                                offset=(0.0, dy, dz)))

    # Build in local space then apply elevation tilt and lateral offset.
    local_md = b.build()
    # Elevation about X (sx side sign handled by rotating about ±X):
    # Positive elev tips the +Z nose up for both sides.
    elev = rot_x(-CAN_ELEV) if sx > 0 else rot_x(-CAN_ELEV)

    b2 = MeshBuilder()
    b2.add_mesh(local_md, rotation=elev,
                offset=(sx * BLOCK_X, BLOCK_Y, BLOCK_Z))
    return b2.build()


def _cannon_barrels(sx: float) -> MeshData:
    """Twin cannon barrels for one side (sx = +1 right / -1 left).

    Each barrel is a thin cylinder along +Z.  A small boxy housing sits at
    the breech end.  The barrels are side-by-side with ~0.13 m vertical gap.
    """
    b = MeshBuilder()
    for dy_off in (-0.065, +0.065):
        b.add_mesh(make_cylinder(BARREL_R, BARREL_L, SEG, _DARK, axis="z",
                                 offset=(sx * BARREL_X,
                                         BARREL_Y + dy_off,
                                         BARREL_Z)))
    # gun housing / autoloader drum box at the rear of the barrels
    bx = GUN_BOX[0]
    b.add_mesh(make_box(GUN_BOX, _DARK,
                        offset=(sx * BARREL_X,
                                BARREL_Y,
                                TURRET_Z - GUN_BOX[2] * 0.5)))
    return b.build()


def _turret() -> MeshData:
    """Central turret assembly (without canister blocks or barrels, which are
    added separately for symmetry).  Includes:
      - Turret ring bearing drum,
      - Main turret box,
      - Tracking radar plate (forward),
      - Search radar drum (top).
    """
    b = MeshBuilder()

    # Bearing ring (drum at deck level)
    b.add_mesh(make_cylinder(RING_R, RING_H, SEG, _DARK, axis="y",
                             offset=(0.0, TURRET_Y + RING_H * 0.5, TURRET_Z)))

    # Main turret box
    b.add_mesh(make_box((TURRET_W, TURRET_H, TURRET_L), _GREEN,
                        offset=(0.0, TURRET_CY, TURRET_Z)))

    # Angled front face / sloped visor (small wedge across the top front edge)
    b.add_mesh(make_wedge((TURRET_W - 0.10, 0.28, 0.40), _DARK,
                          offset=(0.0,
                                  TURRET_Y + TURRET_H - 0.14,
                                  TURRET_Z + TURRET_L * 0.5)))

    # Tracking radar plate (front face, +Z)
    b.add_mesh(make_box((TRACK_W, TRACK_H, TRACK_T), _RADAR,
                        offset=(0.0, TRACK_Y, TRACK_Z)))

    # Pedestal mast under the search radar drum
    b.add_mesh(make_cylinder(0.12, SRCH_MAST, SEG, _DARK, axis="y",
                             offset=(0.0,
                                     TURRET_Y + TURRET_H + SRCH_MAST * 0.5,
                                     TURRET_Z)))

    # Search radar drum (on top of the mast, rotates about Y; fixed here)
    b.add_mesh(make_cylinder(SRCH_R, SRCH_H, SEG, _RADAR, axis="y",
                             offset=(0.0, SRCH_Y + SRCH_H * 0.5, TURRET_Z)))

    return b.build()


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def build_pantsir() -> MeshData:
    """Pantsir-S1 SHORAD vehicle: 8×8 chassis + turret + 12 missile canisters
    + twin 30 mm cannons + tracking and search radar.

    Real scale: chassis ~8.0 m × 3.0 m, 8 road wheels.

    Model space: forward = +Z, up = +Y, origin at ground centre.
    Min-Y (wheel bottoms) ≈ 0 (TIRE_R = 0.58 m, wheels sit on the ground).
    """
    b = MeshBuilder()

    # ------------------------------------------------------------------
    # Chassis frame + deck
    # ------------------------------------------------------------------
    b.add_mesh(make_box((CHASSIS_W, FRAME_TOP - FRAME_BOT, CHASSIS_L),
                        _GREEN,
                        offset=(0.0, (FRAME_BOT + FRAME_TOP) * 0.5, 0.0)))

    # ------------------------------------------------------------------
    # Armoured cab (forward)
    # ------------------------------------------------------------------
    cab_cy = FRAME_TOP + CAB_H * 0.5
    cab_cz = CHASSIS_L * 0.5 - CAB_L * 0.5
    b.add_mesh(make_box((CAB_W, CAB_H, CAB_L), _GREEN,
                        offset=(0.0, cab_cy, cab_cz)))
    # Windshield band (dark strip across the full cab face)
    b.add_mesh(make_box((CAB_W - 0.06, 0.55, 0.08), _RADOME,
                        offset=(0.0,
                                FRAME_TOP + CAB_H - 0.40,
                                CHASSIS_L * 0.5 + 0.02)))
    # Side windows
    for sx in (1.0, -1.0):
        b.add_mesh(make_box((0.07, 0.42, 0.90), _RADOME,
                            offset=(sx * (CAB_W * 0.5 + 0.02),
                                    FRAME_TOP + CAB_H - 0.38,
                                    cab_cz + 0.10)))
    # Front bumper
    b.add_mesh(make_box((CHASSIS_W, 0.24, 0.22), _DARK,
                        offset=(0.0, FRAME_BOT + 0.12, CHASSIS_L * 0.5 + 0.08)))

    # ------------------------------------------------------------------
    # Rear equipment / powerpack bay
    # ------------------------------------------------------------------
    bay_cz = -(CHASSIS_L * 0.5 - BAY_L * 0.5)
    b.add_mesh(make_box((BAY_W, BAY_H, BAY_L), _GREEN,
                        offset=(0.0, FRAME_TOP + BAY_H * 0.5, bay_cz)))

    # ------------------------------------------------------------------
    # 8 wheels (4 axles × 2 sides)
    # ------------------------------------------------------------------
    for za in AXLE_Z:
        for sx in (1.0, -1.0):
            b.add_mesh(make_cylinder(TIRE_R, TIRE_W, SEG_TIRE, _TIRE,
                                     axis="x",
                                     offset=(sx * TIRE_X, TIRE_R, za)))

    # Mudguard strips (thin dark slabs) over each axle pair
    for zc in (
        (AXLE_Z[0] + AXLE_Z[1]) * 0.5,
        (AXLE_Z[2] + AXLE_Z[3]) * 0.5,
    ):
        for sx in (1.0, -1.0):
            b.add_mesh(make_box((0.52, 0.07, 2.20), _DARK,
                                offset=(sx * TIRE_X,
                                        2.0 * TIRE_R + 0.08,
                                        zc)))

    # Side equipment lockers / toolboxes
    for sx in (1.0, -1.0):
        b.add_mesh(make_box((0.36, 0.58, 1.60), _DARK,
                            offset=(sx * (CHASSIS_W * 0.5 - 0.20),
                                    0.80,
                                    0.20)))

    # ------------------------------------------------------------------
    # 4 outrigger jacks (2 pairs: fore + aft)
    # ------------------------------------------------------------------
    for zr in RIG_Z:
        for sx in (1.0, -1.0):
            b.add_mesh(make_box(RIG_SIZE, _DARK,
                                offset=(sx * RIG_X,
                                        RIG_SIZE[1] * 0.5,
                                        zr)))

    # ------------------------------------------------------------------
    # Turret assembly (bearing drum, turret box, radars)
    # ------------------------------------------------------------------
    b.add_mesh(_turret())

    # ------------------------------------------------------------------
    # Canister blocks (left / right)
    # ------------------------------------------------------------------
    for sx in (1.0, -1.0):
        b.add_mesh(_canister_block(sx))

    # ------------------------------------------------------------------
    # Cannon barrels (left / right)
    # ------------------------------------------------------------------
    for sx in (1.0, -1.0):
        b.add_mesh(_cannon_barrels(sx))

    return b.build()
