"""ICBM models: Minuteman III + Sarmat missiles and their silo compounds.

Every dimension traces to docs/research/icbm_reference_2026-07-17.md
(visual signature checklists 1.6 / 2.6):

- ``build_minuteman_iii()`` — the 18.3 x 1.68 m three-stage pencil
  (10.9:1): one shoulder taper above S1, near-black interstage bands, a
  thin raceway conduit, conical dark Mk21 shroud.
- ``build_sarmat()`` — the 35.3 x 3.0 m green-black monster: common-
  diameter stack, blunt rounded fairing with the pale nose-cap seam,
  four-chamber nozzle hint at the tail.
- ``build_minuteman_lf()`` / ``build_minuteman_lf_door()`` — the launch
  facility: concrete apron, clean round tube mouth (3.66 m bore that
  SWALLOWS the 1.68 m airframe, checklist 10), rails, personnel hatch,
  antenna bumps, the banal security fence — and the 110 t rectangular
  closure door as a SEPARATE mesh the state slides open along +Z.
- ``build_sarmat_silo()`` / ``build_sarmat_silo_lid()`` — the low
  concrete mesa, ~6 m tube with the TPK rim visible in the mouth, and
  the massive circular lid (separate mesh, slides +Z on rails).

Model space per LOCKED CONVENTIONS: forward = +Z (missiles: nose +Z,
origin mid-body, drawn vertical by the state), up = +Y, real meters,
silos origin at tube center ground level. Pure numpy, GL-free.
"""

from __future__ import annotations

import math

import numpy as np

from engine.meshdata import (MeshBuilder, MeshData, make_box, make_cylinder,
                             make_lathe)
from models.common import PALETTE, rot_x

SEG = 28

# make_lathe revolves around +Z; this stands the result up along +Y
# (silo collars, bore discs, lid dome). Missiles stay nose-+Z unrotated.
_VERT = rot_x(-math.pi / 2.0)


def _add_vlathe(b: MeshBuilder, profile, color, segments: int = SEG) -> None:
    """Add a lathe whose profile (height_y, radius) stands along +Y."""
    b.add_mesh(make_lathe(profile, segments, color), rotation=_VERT)

# --- Minuteman III stack stations (base at -L/2, nose at +L/2) -------------
MM3_LEN = 18.3
MM3_R1 = 0.84                  # stage-1 radius (1.68 m dia)
MM3_R23 = 0.66                 # stages 2/3 (1.32 m class)
MM3_S1_LEN = 8.4
MM3_INTER_LEN = 0.6            # tapered interstage
MM3_S2_LEN = 3.0
MM3_SKIRT_LEN = 0.3
MM3_S3_LEN = 2.3
MM3_SHROUD_LEN = 3.7           # cylinder shoulder + cone + tip

# --- Sarmat stack -----------------------------------------------------------
SAR_LEN = 35.3
SAR_R = 1.5
SAR_FAIR_LEN = 4.4             # blunt rounded fairing
SAR_SEAM_Z = 2.0               # S1/S2 seam station (model z)

# --- Minuteman launch facility ---------------------------------------------
LF_TUBE_R = 1.83               # 12 ft bore
LF_COLLAR_R = 2.15
LF_DOOR_SIZE = (5.6, 1.05, 7.8)    # 110 t, 3.5 ft thick slab
LF_DOOR_Y = 0.62               # door underside rides just over the collar
LF_DOOR_CLOSED_Z = 0.3         # roughly centered on the tube
LF_DOOR_OPEN_DZ = 8.6          # full slide along +Z
LF_FENCE_HALF = 19.0           # ~40 m square compound

# --- Sarmat silo -------------------------------------------------------------
SAR_TUBE_R = 3.1               # ~6 m class tube
SAR_TPK_R = 1.68               # TPK rim visible in the mouth
SAR_LID_R = 4.4
SAR_LID_H = 1.25
SAR_LID_OPEN_DZ = 10.5
SAR_LID_Y = 1.15


# ------------------------------------------------------------------ missiles

def _cone(r0: float, r1: float, length: float, z0: float, color,
          segments: int = SEG) -> MeshData:
    """Tapered ring (lathe) from radius r0 at z0 to r1 at z0+length."""
    return make_lathe([(z0, r0), (z0 + length, r1)], segments, color)


def build_minuteman_iii() -> MeshData:
    """LGM-30G: slim off-white 3-stage pencil, origin mid-body, nose +Z."""
    b = MeshBuilder()
    body = PALETTE["icbm_white"]
    band = PALETTE["icbm_band"]
    base = -MM3_LEN * 0.5
    z = base
    # Stage 1 + nozzle hint below the base plane is unnecessary: the tube
    # hides the tail; a dark base disc reads right when it climbs.
    b.add_mesh(make_lathe([(z, 0.0), (z, MM3_R1)], SEG, band))
    b.add_mesh(make_cylinder(MM3_R1, MM3_S1_LEN, SEG, body, axis="z",
                             offset=(0.0, 0.0, z + MM3_S1_LEN * 0.5)))
    z += MM3_S1_LEN
    # Interstage: black band + shoulder taper (signature 2).
    b.add_mesh(make_cylinder(MM3_R1 + 0.01, 0.35, SEG, band, axis="z",
                             offset=(0.0, 0.0, z + 0.12)))
    b.add_mesh(_cone(MM3_R1, MM3_R23, MM3_INTER_LEN, z, body))
    z += MM3_INTER_LEN
    b.add_mesh(make_cylinder(MM3_R23, MM3_S2_LEN, SEG, body, axis="z",
                             offset=(0.0, 0.0, z + MM3_S2_LEN * 0.5)))
    z += MM3_S2_LEN
    b.add_mesh(make_cylinder(MM3_R23 + 0.01, MM3_SKIRT_LEN, SEG, band,
                             axis="z",
                             offset=(0.0, 0.0, z + MM3_SKIRT_LEN * 0.5)))
    z += MM3_SKIRT_LEN
    b.add_mesh(make_cylinder(MM3_R23, MM3_S3_LEN, SEG, body, axis="z",
                             offset=(0.0, 0.0, z + MM3_S3_LEN * 0.5)))
    z += MM3_S3_LEN
    # Shroud: short shoulder, cone, rounded dark tip (signature 2).
    shoulder = 0.7
    b.add_mesh(make_cylinder(MM3_R23, shoulder, SEG, PALETTE["shroud_dark"],
                             axis="z", offset=(0.0, 0.0, z + shoulder * 0.5)))
    z += shoulder
    cone_len = MM3_SHROUD_LEN - shoulder - 0.25
    b.add_mesh(make_lathe([(z, MM3_R23), (z + cone_len, 0.16),
                           (z + MM3_SHROUD_LEN - shoulder, 0.0)],
                          SEG, PALETTE["shroud_dark"]))
    # Raceway conduit: the thin dark cable duct running up one side.
    b.add_mesh(make_box((0.14, 0.10, MM3_S1_LEN + MM3_S2_LEN + 1.0), band,
                        offset=(MM3_R1 * 0.82, 0.0,
                                base + (MM3_S1_LEN + MM3_S2_LEN) * 0.55)))
    return b.build()


def _sarmat_fairing_profile(z0: float) -> list:
    """Blunt rounded ogive (signature 2.6-2): cosine cap, no sharp tip."""
    pts = []
    for a in np.linspace(0.0, math.pi * 0.5, 7):
        pts.append((z0 + SAR_FAIR_LEN * math.sin(a),
                    SAR_R * math.cos(a) * (1.0 - 0.12 * math.sin(a))))
    pts[-1] = (z0 + SAR_FAIR_LEN, 0.0)
    return pts


def build_sarmat() -> MeshData:
    """RS-28: 35.3 x 3.0 m green-black stack, origin mid-body, nose +Z."""
    b = MeshBuilder()
    body = PALETTE["sarmat_dark"]
    base = -SAR_LEN * 0.5
    cyl_len = SAR_LEN - SAR_FAIR_LEN
    b.add_mesh(make_lathe([(base, 0.0), (base, SAR_R)], SEG,
                          PALETTE["exhaust_ring"]))
    b.add_mesh(make_cylinder(SAR_R, cyl_len, SEG, body, axis="z",
                             offset=(0.0, 0.0, base + cyl_len * 0.5)))
    # Four-chamber nozzle hint: a dark ring cluster proud of the base.
    for sx, sy in ((0.6, 0.6), (-0.6, 0.6), (0.6, -0.6), (-0.6, -0.6)):
        b.add_mesh(make_cylinder(0.34, 0.5, 12, PALETTE["exhaust_ring"],
                                 axis="z", offset=(sx, sy, base + 0.26)))
    # Stage seam + pale nose-cap seam ring (signatures 2 and the cap).
    b.add_mesh(make_cylinder(SAR_R + 0.015, 0.22, SEG, PALETTE["icbm_band"],
                             axis="z", offset=(0.0, 0.0, SAR_SEAM_Z)))
    b.add_mesh(make_cylinder(SAR_R + 0.015, 0.30, SEG,
                             PALETTE["sarmat_nose"], axis="z",
                             offset=(0.0, 0.0, base + cyl_len - 0.2)))
    b.add_mesh(make_lathe(_sarmat_fairing_profile(base + cyl_len), SEG,
                          body))
    return b.build()


# --------------------------------------------------------------------- silos

def _fence(b: MeshBuilder, half: float, post_gap: float) -> None:
    """The banal security fence: posts + two thin rails per side."""
    steel = PALETTE["silo_rail"]
    n = int((2.0 * half) / post_gap)
    for i in range(n + 1):
        d = -half + i * post_gap
        for px, pz in ((d, -half), (d, half), (-half, d), (half, d)):
            b.add_mesh(make_box((0.09, 1.9, 0.09), steel,
                                offset=(px, 0.95, pz)))
    for y in (0.9, 1.75):
        b.add_mesh(make_box((2.0 * half, 0.05, 0.05), steel,
                            offset=(0.0, y, -half)))
        b.add_mesh(make_box((2.0 * half, 0.05, 0.05), steel,
                            offset=(0.0, y, half)))
        b.add_mesh(make_box((0.05, 0.05, 2.0 * half), steel,
                            offset=(-half, y, 0.0)))
        b.add_mesh(make_box((0.05, 0.05, 2.0 * half), steel,
                            offset=(half, y, 0.0)))


def build_minuteman_lf() -> MeshData:
    """Minuteman launch facility WITHOUT the door (checklist 3/9/10):
    gravel-lot banality — apron, tube collar + black bore, door rails,
    personnel hatch, antenna bumps, fence."""
    b = MeshBuilder()
    conc = PALETTE["concrete"]
    b.add_mesh(make_box((22.0, 0.3, 26.0), conc, offset=(0.0, 0.15, 1.5)))
    # Tube collar and the clean metal RING of the open mouth.
    _add_vlathe(b, [(0.30, LF_TUBE_R), (0.30, LF_COLLAR_R),
                    (0.62, LF_COLLAR_R + 0.05), (0.62, LF_TUBE_R)],
                PALETTE["silo_door"])
    b.add_mesh(make_cylinder(LF_TUBE_R + 0.02, 0.34, SEG,
                             PALETTE["silo_rail"], axis="y",
                             offset=(0.0, 0.45, 0.0)))
    # The bore: a black disc just under the ring (the missile mesh rises
    # through it; the tube interior never needs real depth).
    _add_vlathe(b, [(0.36, 0.0), (0.36, LF_TUBE_R)], PALETTE["silo_bore"])
    # Door rails running +Z.
    for sx in (-1.0, 1.0):
        b.add_mesh(make_box((0.30, 0.22, 10.5), PALETTE["silo_rail"],
                            offset=(sx * (LF_DOOR_SIZE[0] * 0.5 + 0.35),
                                    0.42, 6.0)))
    # Personnel access hatch + soft-support boxes + antenna bumps.
    b.add_mesh(make_box((1.5, 0.55, 1.5), PALETTE["silo_door"],
                        offset=(-6.5, 0.55, -6.0)))
    b.add_mesh(make_box((1.1, 0.8, 1.6), conc, offset=(7.2, 0.65, -7.0)))
    for px, pz in ((8.0, 6.5), (-8.0, 8.0)):
        b.add_mesh(make_cylinder(0.32, 1.0, 12, PALETTE["radar_white"],
                                 axis="y", offset=(px, 0.75, pz)))
    _fence(b, LF_FENCE_HALF, 6.3)
    return b.build()


def build_minuteman_lf_door() -> MeshData:
    """The 110 t closure door slab, origin at ITS center: the state draws
    it at LF_DOOR_CLOSED_Z and slides it +Z by frac * LF_DOOR_OPEN_DZ,
    wedge (leading edge) first."""
    b = MeshBuilder()
    b.add_mesh(make_box(LF_DOOR_SIZE, PALETTE["silo_door"]))
    # Wedge-shaped debris-plow leading edge (research: it clears the path).
    b.add_mesh(make_box((LF_DOOR_SIZE[0], 0.5, 0.9), PALETTE["silo_rail"],
                        offset=(0.0, -0.2, LF_DOOR_SIZE[2] * 0.5 + 0.4)))
    return b.build()


def build_sarmat_silo() -> MeshData:
    """15P718M-class site: low concrete mesa, ~6 m tube, TPK rim visible
    in the mouth (checklist 8/10), lid rails, perimeter bollards."""
    b = MeshBuilder()
    conc = PALETTE["concrete"]
    b.add_mesh(make_box((34.0, 0.5, 34.0), conc, offset=(0.0, 0.25, 0.0)))
    b.add_mesh(make_box((26.0, 0.55, 26.0), conc, offset=(0.0, 0.78, 0.0)))
    # Tube collar, bore, and the TPK rim standing in the mouth.
    _add_vlathe(b, [(1.05, SAR_TUBE_R), (1.05, SAR_TUBE_R + 0.6),
                    (1.45, SAR_TUBE_R + 0.65), (1.45, SAR_TUBE_R)],
                PALETTE["silo_door"])
    _add_vlathe(b, [(1.10, 0.0), (1.10, SAR_TUBE_R)], PALETTE["silo_bore"])
    b.add_mesh(make_cylinder(SAR_TPK_R + 0.14, 0.7, SEG,
                             PALETTE["mil_green_dark"], axis="y",
                             offset=(0.0, 1.25, 0.0)))
    _add_vlathe(b, [(1.62, 0.0), (1.62, SAR_TPK_R)], PALETTE["silo_bore"])
    # Lid rails running +Z.
    for sx in (-1.0, 1.0):
        b.add_mesh(make_box((0.4, 0.3, 13.5), PALETTE["silo_rail"],
                            offset=(sx * (SAR_LID_R + 0.6), 0.95, 7.5)))
    # Perimeter bollards (the obstacle-grid security ring).
    for i in range(12):
        a = i * math.pi / 6.0
        b.add_mesh(make_box((0.35, 1.1, 0.35), conc,
                            offset=(15.5 * math.sin(a), 0.55,
                                    15.5 * math.cos(a))))
    _fence(b, 17.0, 5.7)
    return b.build()


def build_sarmat_silo_lid() -> MeshData:
    """The massive circular lid, origin at ITS center; slides +Z by
    frac * SAR_LID_OPEN_DZ on the rails."""
    b = MeshBuilder()
    b.add_mesh(make_cylinder(SAR_LID_R, SAR_LID_H, SEG,
                             PALETTE["silo_door"], axis="y"))
    b.add_mesh(make_lathe([(0.0, SAR_LID_R * 0.85),
                           (0.45, SAR_LID_R * 0.45), (0.55, 0.0)],
                          SEG, PALETTE["silo_door"]),
               rotation=_VERT, offset=(0.0, SAR_LID_H * 0.5, 0.0))
    return b.build()
