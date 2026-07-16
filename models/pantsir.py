"""Pantsir-S1 short-range SHORAD system model.

``build_pantsir()`` is the ~8 m KAMAZ-style 8×8 heavy truck chassis carrying
a central rotating turret with:
  - TWO racks of 6 cylindrical missile canisters (12 × 57E6), one per side,
  - Twin 30 mm 2A38M cannon barrels mounted below/between the tube blocks on
    each side (two long thin cylinders, the signature "horns"),
  - A flat phased-array tracking radar panel on the turret front face,
  - A broad rectangular target-acquisition array over the turret.

Real-world references (Pantsir-S1, export "SA-22 Greyhound"):
  - Chassis: KAMAZ-6560 8×8, 10.2 m curb / 11.365 m gross length and 2.55 m
    wide.  We retain the game's established 8.0 m × 3.0 m stylised envelope.
  - Turret ring diameter ~1.6 m; turret body ~2.0 m wide × ~1.8 m tall.
  - 57E6 canisters: ~3.2 m long; 6 stacked 3-high × 2-wide per side.
  - 2A38M barrel length ~2.4 m exposed, diameter ~0.06 m.
  - Tracking radar: 1E20 flat array ~0.8 m × 0.8 m on the turret nose.
  - Target-acquisition radar: broad rectangular array on a central pedestal.

Model space per LOCKED CONVENTIONS: forward = +Z, up = +Y, real meters,
origin at the ground center.  Wheels at y ≈ 0, chassis top at y ≈ FRAME_TOP.

Pure numpy, GL-free.
"""

from __future__ import annotations

import math

import numpy as np

from engine.meshdata import (MeshBuilder, MeshData, make_box,
                             make_cylinder, make_lathe, make_wedge)
from models.common import PALETTE, rot_x, sphere_profile

# ---------------------------------------------------------------------------
# Segment count for cylinders / lathe — matches s300.py low-poly style
# ---------------------------------------------------------------------------
SEG = 16        # barrels / turret drum — fewer than S-300 (shorter features)
SEG_TIRE = 14   # tires

# ---------------------------------------------------------------------------
# Chassis dimensions (KAMAZ-6560 8×8)
# Length 8.0 m is the armoured body box; the real chassis is longer, but we
# keep the visual block compact to match the game's established scale.
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
# Missile canister blocks  (6 cylindrical TPKs per side: 3 high × 2 wide)
# Canisters are 3.2 m long and separated across each retention rack.
# Stacked 3-high, 2-deep on a launch rail angled up ~8° (slight upward tilt
# for visual clarity; real Pantsir canisters angle ~0-10° in stowed position).
# Blocks are offset ±X from the turret centre, at turret mid-height.
# ---------------------------------------------------------------------------
CAN_W = 0.38    # m  canister width/height (READABILITY: fattened from
#                     the scale 0.32 so the 3x2 pack reads as tubes, not
#                     a slatted slab, at gameplay distance)
CAN_L = 3.20    # m  canister length

# 3 rows (stacked vertically), 2 columns (fore-aft)
_COLS = 2
_ROWS = 3
CAN_COL_DZ = CAN_L * 0.52    # fore-aft spacing centre-to-centre
CAN_ROW_DY = CAN_W + 0.04    # vertical pitch

# Block centre position relative to turret centre
BLOCK_X    = TURRET_W * 0.5 + 0.45   # stand-off: the packs must read as
#                     SEPARATE angled blocks flanking the turret (flush
#                     mounting merged them into the box — orbit critique)
BLOCK_Y    = TURRET_Y + TURRET_H * 0.55   # roughly mid-height of the turret box
BLOCK_Z    = TURRET_Z + 0.10

# Slight upward elevation angle for canisters (cosmetic "ready" look)
# Legacy constant retained for downstream callers that imported it.
CAN_ELEV   = math.radians(20.0)
CAN_VISUAL_ELEV = math.radians(4.0)

# Rail frame connecting the block to the turret (thin boxy strut each side)
RAIL_W = TURRET_W * 0.5 + BLOCK_X + CAN_L * 0.2
RAIL_H = 0.12
RAIL_L = 0.25

# ---------------------------------------------------------------------------
# Twin 2A38M cannon barrels (per side)
# Mounted at the outer/lower edge of the turret box, one barrel per "horn".
# Real 2A38M: ~2.4 m barrel exposed, 30 mm bore.
# ---------------------------------------------------------------------------
BARREL_R   = 0.095   # m  radius (READABILITY: ~2.4x the scale jacket —
#                     a 4 cm cylinder is subpixel at gameplay distance;
#                     the twin gun horns are a Pantsir signature)
BARREL_L   = 3.10    # m  exposed barrel length (slightly stretched)
# Small gun housing box (autoloader drum behind the barrel)
GUN_BOX    = (0.35, 0.38, 0.45)
# Position (relative to origin): directly BENEATH the canister block (the
# real 2A38M horns sit under/inboard of the missile packs).  Mounting them
# OUTBOARD of the packs pushed the hull bbox to 3.89 m — 30% over the 3.0 m
# width contract (tests/test_pantsir_model.py); under the packs the widest
# geometry is the canister retention rings (±1.71 m -> 3.42 m, in band).
BARREL_X   = BLOCK_X                        # centred under the canister block
BARREL_Y   = TURRET_Y + 0.60                 # low on the turret, above deck
BARREL_Z   = TURRET_Z + BARREL_L * 0.5 + 0.30  # tips point forward

# ---------------------------------------------------------------------------
# Tracking radar (flat phased-array plate on turret front face)
# 1E20 array ~0.8 × 0.8 m, 0.10 m thick, flush-mounted on the +Z face.
# ---------------------------------------------------------------------------
TRACK_W   = 0.95   # m
TRACK_H   = 0.95   # m
TRACK_T   = 0.18   # m  depth (stands PROUD of the face; flush was invisible)
TRACK_Y   = TURRET_Y + TURRET_H * 0.55   # centred on the turret face
TRACK_Z   = TURRET_Z + TURRET_L * 0.5 + TRACK_T * 0.5   # proud of the face

# ---------------------------------------------------------------------------
# Legacy search-radar dimensions retained for compatible imports; SRCH_R/H
# now size the circular IFF element above the broad acquisition panel.
# ---------------------------------------------------------------------------
SRCH_R    = 0.28   # m  radius
SRCH_H    = 0.25   # m  height (drum)
SRCH_MAST = 0.75   # m  pedestal mast under the drum
SRCH_Y    = TURRET_Y + TURRET_H + SRCH_MAST + 0.08   # sits on mast top

# Broad target-acquisition array.  The legacy model reduced this signature to
# a tiny drum; these dimensions stay inside the locked game-scale chassis.
ACQ_W = 2.20
ACQ_H = 1.20
ACQ_T = 0.16
ACQ_Y = 4.02
ACQ_Z = TURRET_Z + 0.28

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

    The cylindrical TPKs form a 3-high × 2-wide rack, held near-horizontal at
    CAN_VISUAL_ELEV to match the production vehicle's travel silhouette.
    """
    b = MeshBuilder()
    can_c = PALETTE["tube_grey"]
    ring_c = PALETTE["tube_ring"]

    dy_offsets = [i * CAN_ROW_DY - ((_ROWS - 1) * CAN_ROW_DY * 0.5)
                  for i in range(_ROWS)]
    # The old code offset full-length tubes along their own axis, so every
    # pair interpenetrated.  The real second column lies across the rack.
    dx_offsets = (-0.12, 0.12)
    for dy in dy_offsets:
        for dx in dx_offsets:
            tube_r = 0.145
            b.add_mesh(make_cylinder(tube_r, CAN_L, SEG, can_c, axis="z",
                                     offset=(dx, dy, 0.0)))
            for zz in (-0.72, 0.62):
                b.add_mesh(make_cylinder(tube_r + 0.018, 0.07, SEG, ring_c,
                                         axis="z", offset=(dx, dy, zz)))
            b.add_mesh(make_cylinder(tube_r + 0.025, 0.075, SEG, _DARK,
                                     axis="z",
                                     offset=(dx, dy, CAN_L * 0.5 - 0.038)))

    # Retention cassette and rear mounting cheek.
    b.add_mesh(make_box((0.58, 0.10, CAN_L - 0.12), _DARK,
                        offset=(0.0, -0.61, -0.02)))
    b.add_mesh(make_box((0.08, 1.22, 0.18), _DARK,
                        offset=(0.0, 0.0, -1.35)))

    b2 = MeshBuilder()
    b2.add_mesh(b.build(), rotation=rot_x(-CAN_VISUAL_ELEV),
                offset=(sx * BLOCK_X, BLOCK_Y, BLOCK_Z))
    return b2.build()


def _cannon_barrels(sx: float) -> MeshData:
    """Twin cannon barrels for one side (sx = +1 right / -1 left).

    Each barrel is a thin cylinder along +Z.  A small boxy housing sits at
    the breech end.  The barrels are side-by-side with ~0.13 m vertical gap.
    """
    local = MeshBuilder()
    for dx_off in (-0.075, +0.075):
        local.add_mesh(make_cylinder(BARREL_R * 0.70, BARREL_L, SEG, _DARK,
                                     axis="z", offset=(dx_off, 0.0, 0.0)))
        local.add_mesh(make_cylinder(BARREL_R * 0.92, 0.22, SEG,
                                     PALETTE["exhaust_ring"], axis="z",
                                     offset=(dx_off, 0.0, BARREL_L * 0.5 - 0.11)))
    for zz in (-0.85, 0.15, 0.95):
        local.add_mesh(make_box((0.31, 0.18, 0.12), _DARK,
                                offset=(0.0, 0.0, zz)))
    b = MeshBuilder()
    b.add_mesh(local.build(), rotation=rot_x(math.radians(-15.0)),
               offset=(sx * BARREL_X, BARREL_Y, BARREL_Z))
    b.add_mesh(make_box((0.48, 0.48, 0.62), _DARK,
                        offset=(sx * BARREL_X, BARREL_Y, TURRET_Z - 0.05)))
    return b.build()


def _turret() -> MeshData:
    """Central turret assembly (without canister blocks or barrels, which are
    added separately for symmetry).  Includes:
      - Turret ring bearing drum,
      - Main turret box,
      - Tracking radar plate (forward),
      - Broad target-acquisition radar and IFF element (top).
    """
    b = MeshBuilder()

    # Bearing ring (drum at deck level)
    b.add_mesh(make_cylinder(RING_R, RING_H, SEG, _DARK, axis="y",
                             offset=(0.0, TURRET_Y + RING_H * 0.5, TURRET_Z)))

    # Low angular weapon cradle with a raised central sensor pedestal.
    b.add_mesh(make_box((TURRET_W, 0.72, TURRET_L), _GREEN,
                        offset=(0.0, TURRET_Y + 0.48, TURRET_Z)))
    b.add_mesh(make_wedge((TURRET_W - 0.18, 0.82, 1.42), _GREEN,
                          offset=(0.0, TURRET_Y + 1.10, TURRET_Z - 0.06)))
    b.add_mesh(make_box((0.82, 1.00, 0.92), _GREEN,
                        offset=(0.0, TURRET_Y + 1.74, TURRET_Z + 0.02)))

    # Tracking radar plate (front face, +Z)
    b.add_mesh(make_box((TRACK_W + 0.12, TRACK_H + 0.12, TRACK_T), _RADAR,
                        offset=(0.0, TRACK_Y, TRACK_Z)))
    b.add_mesh(make_box((TRACK_W - 0.08, TRACK_H - 0.08, 0.055), _RADOME,
                        offset=(0.0, TRACK_Y, TRACK_Z + TRACK_T * 0.55)))

    # Broad rectangular acquisition array, active face, rear ribs and IFF disc.
    b.add_mesh(make_box((0.52, 1.36, 0.48), _DARK,
                        offset=(0.0, 3.28, ACQ_Z - 0.12)))
    b.add_mesh(make_box((ACQ_W, ACQ_H, ACQ_T), _RADAR,
                        offset=(0.0, ACQ_Y, ACQ_Z)))
    b.add_mesh(make_box((ACQ_W - 0.14, ACQ_H - 0.14, 0.055), _RADOME,
                        offset=(0.0, ACQ_Y, ACQ_Z + ACQ_T * 0.58)))
    for xx in (-0.78, 0.0, 0.78):
        b.add_mesh(make_box((0.06, ACQ_H - 0.10, 0.12), _DARK,
                            offset=(xx, ACQ_Y, ACQ_Z - ACQ_T * 0.62)))
    b.add_mesh(make_cylinder(SRCH_R, SRCH_H, SEG, _RADAR, axis="y",
                             offset=(0.0, ACQ_Y + ACQ_H * 0.5 + 0.20,
                                     ACQ_Z - 0.08)))

    # Offset electro-optical ball with a small protective hood.
    b.add_mesh(make_lathe(sphere_profile(0.22, 8), SEG, _RADAR),
               offset=(-0.58, 2.72, TRACK_Z - 0.02))
    b.add_mesh(make_box((0.52, 0.12, 0.38), _DARK,
                        offset=(-0.58, 2.92, TRACK_Z - 0.08)))

    return b.build()


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def build_pantsir() -> MeshData:
    """Pantsir-S1 SHORAD vehicle: 8×8 chassis + turret + 12 missile canisters
    + twin 30 mm cannons + tracking and target-acquisition radars.

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
    # Split windscreen and roof brow reproduce the production KAMAZ cab.
    for x in (-0.68, 0.68):
        b.add_mesh(make_box((1.13, 0.55, 0.065), _RADOME),
                   rotation=rot_x(math.radians(4.0)),
                   offset=(x, FRAME_TOP + CAB_H - 0.40,
                           CHASSIS_L * 0.5 + 0.025))
    b.add_mesh(make_box((CAB_W, 0.16, 0.34), _GREEN,
                        offset=(0.0, FRAME_TOP + CAB_H - 0.02,
                                CHASSIS_L * 0.5 - 0.10)))
    # Side windows, door outlines, and paired mirrors.
    for sx in (1.0, -1.0):
        b.add_mesh(make_box((0.07, 0.42, 0.90), _RADOME,
                            offset=(sx * (CAB_W * 0.5 + 0.02),
                                    FRAME_TOP + CAB_H - 0.38,
                                    cab_cz + 0.10)))
        b.add_mesh(make_box((0.045, 0.96, 0.92), _DARK,
                            offset=(sx * (CAB_W * 0.5 + 0.025),
                                    FRAME_TOP + 0.82, cab_cz - 0.18)))
        b.add_mesh(make_cylinder(0.022, 0.24, 8, _DARK, axis="x",
                                 offset=(sx * 1.55, 2.52, cab_cz + 0.58)))
        b.add_mesh(make_box((0.045, 0.34, 0.22), _RADOME,
                            offset=(sx * 1.68, 2.52, cab_cz + 0.58)))
    # Front bumper
    b.add_mesh(make_box((CHASSIS_W, 0.24, 0.22), _DARK,
                        offset=(0.0, FRAME_BOT + 0.12, CHASSIS_L * 0.5 + 0.08)))
    b.add_mesh(make_box((1.46, 0.42, 0.055), _RADOME,
                        offset=(0.0, 1.72, CHASSIS_L * 0.5 + 0.035)))
    for y in (1.60, 1.72, 1.84):
        b.add_mesh(make_box((1.34, 0.035, 0.075), _GREEN,
                            offset=(0.0, y, CHASSIS_L * 0.5 + 0.07)))
    for sx in (-1.0, 1.0):
        b.add_mesh(make_cylinder(0.14, 0.07, 12, _RADAR, axis="z",
                                 offset=(sx * 1.02, 1.35,
                                         CHASSIS_L * 0.5 + 0.13)))

    # ------------------------------------------------------------------
    # Rear equipment / powerpack bay
    # ------------------------------------------------------------------
    bay_cz = -(CHASSIS_L * 0.5 - BAY_L * 0.5)
    b.add_mesh(make_box((BAY_W, BAY_H, BAY_L), _GREEN,
                        offset=(0.0, FRAME_TOP + BAY_H * 0.5, bay_cz)))
    for sx in (-1.0, 1.0):
        b.add_mesh(make_box((0.07, 1.08, 1.72), _DARK,
                            offset=(sx * (BAY_W * 0.5 + 0.02),
                                    FRAME_TOP + 0.72, bay_cz)))
        for zz in np.linspace(bay_cz - 0.62, bay_cz + 0.62, 6):
            b.add_mesh(make_box((0.095, 0.82, 0.055), _TIRE,
                                offset=(sx * (BAY_W * 0.5 + 0.06),
                                        FRAME_TOP + 0.72, float(zz))))

    # Spare wheels immediately behind the cab are prominent in high views.
    for sx in (-1.0, 1.0):
        b.add_mesh(make_cylinder(0.50, 0.18, SEG_TIRE, _TIRE, axis="x",
                                 offset=(sx * 1.38, 2.02, 1.26)))
        b.add_mesh(make_cylinder(0.20, 0.21, 12, _DARK, axis="x",
                                 offset=(sx * 1.38, 2.02, 1.26)))

    # ------------------------------------------------------------------
    # 8 wheels (4 axles × 2 sides)
    # ------------------------------------------------------------------
    for za in AXLE_Z:
        for sx in (1.0, -1.0):
            b.add_mesh(make_cylinder(TIRE_R, TIRE_W, SEG_TIRE, _TIRE,
                                     axis="x",
                                     offset=(sx * TIRE_X, TIRE_R, za)))
            b.add_mesh(make_cylinder(0.23, TIRE_W + 0.04, 12, _DARK,
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
            b.add_mesh(make_box((0.48, 0.16, 0.30), _DARK,
                                offset=(sx * 1.48, 0.98, zr)))
            b.add_mesh(make_box((0.16, 0.94, 0.16), _DARK,
                                offset=(sx * 1.64, 0.49, zr)))
            b.add_mesh(make_box((0.30, 0.07, 0.40), _TIRE,
                                offset=(sx * 1.64, 0.035, zr)))

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
