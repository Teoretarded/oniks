"""P-800 Oniks missile model (and its drop-away booster), built procedurally.

Real dimensions: 8.9 m long, body diameter 0.67 m. Model space: forward = +Z
(nose at z = +4.45), origin at mid-body (the missile's center of rotation).
The signature look is the annular nose intake: the outer body ends in a ring
lip and a dark shock cone sits inset inside it, running out to the nose tip.

Pure numpy / GL-free (returns ``MeshData``; callers upload via engine.mesh).
"""

from __future__ import annotations

import math

import numpy as np

from engine.meshdata import MeshBuilder, MeshData, make_cylinder, make_fin, make_lathe
from models.common import PALETTE, rot_z

SEG = 32                 # lathe/cylinder segments

# Body stations (z, meters from mid-body origin; nose at +4.45)
_TAIL_Z = -4.45
_TAIL_R = 0.30           # flat tail radius
_BOAT_Z = -3.95          # boat-tail blends into the full-width mid-body here
_BODY_R = 0.335          # mid-body radius (diameter 0.67)
_OGIVE_Z = 1.80          # ogive taper begins
_LIP_Z = 3.90            # ring-intake lip
_LIP_R = 0.24
_CONE_BASE_Z = 3.72      # shock cone base (inset behind the lip)
_CONE_BASE_R = 0.20
_NOSE_Z = 4.45           # shock cone tip = nose

_EXH_Z = -4.30           # dark exhaust ring covers the last 15 cm of tail


def _ogive_profile():
    """Convex taper from the mid-body to the intake lip: (z, r) points."""
    pts = []
    for z in np.linspace(_OGIVE_Z, _LIP_Z, 8)[1:]:
        t = (z - _OGIVE_Z) / (_LIP_Z - _OGIVE_Z)
        pts.append((float(z), _BODY_R - (_BODY_R - _LIP_R) * t ** 1.8))
    return pts


def build_oniks() -> MeshData:
    b = MeshBuilder()
    body_c = PALETTE["missile_body"]
    radome_c = PALETTE["radome"]
    fin_c = PALETTE["fin"]
    exh_c = PALETTE["exhaust_ring"]

    # exhaust ring: dark flat tail disc + short dark boat-tail band
    exh_r = _TAIL_R + (_BODY_R - _TAIL_R) * (_EXH_Z - _TAIL_Z) / (_BOAT_Z - _TAIL_Z)
    b.add_mesh(make_lathe([(_TAIL_Z, 0.0), (_TAIL_Z, _TAIL_R), (_EXH_Z, exh_r)],
                          SEG, exh_c))
    # main body: boat-tail -> cylinder -> ogive -> intake lip
    profile = [(_EXH_Z, exh_r), (_BOAT_Z, _BODY_R), (_OGIVE_Z, _BODY_R)]
    profile += _ogive_profile()
    b.add_mesh(make_lathe(profile, SEG, body_c))
    # lip face: thin forward-facing ring closing the body wall thickness
    b.add_mesh(make_lathe([(_LIP_Z, _LIP_R), (_LIP_Z, _LIP_R - 0.015)], SEG, body_c))
    # intake duct: inward-facing funnel from the lip back to the cone base
    b.add_mesh(make_lathe([(_LIP_Z, _LIP_R - 0.015), (_CONE_BASE_Z, _CONE_BASE_R)],
                          SEG, radome_c))
    # inset shock cone (radome) out to the nose tip
    b.add_mesh(make_lathe([(_CONE_BASE_Z, _CONE_BASE_R), (_NOSE_Z, 0.0)],
                          SEG, radome_c))

    # 4 clipped-delta fins, X pattern (45 deg off vertical), roots buried in
    # the body wall so the exposed span is the full 0.55 m.
    fin = make_fin(1.6, 0.55, 0.55, 0.9, 0.04, fin_c, offset=(0.30, 0.0, -2.6))
    for k in range(4):
        b.add_mesh(fin, rotation=rot_z(math.radians(45.0 + 90.0 * k)))
    # 4 small tail strakes, + pattern (interleaved with the fins)
    strake = make_fin(0.7, 0.3, 0.30, 0.25, 0.03, fin_c, offset=(0.28, 0.0, -3.75))
    for k in range(4):
        b.add_mesh(strake, rotation=rot_z(math.radians(90.0 * k)))
    return b.build()


# Booster stations (own model space: origin at booster mid-cylinder)
_BST_LEN = 2.0
_BST_R = 0.30
_BELL_Z = -1.35          # nozzle bell exit plane
_BELL_R = 0.26


def build_oniks_booster() -> MeshData:
    """2.0 m solid booster (r 0.30) + nozzle bell; drawn attached behind the
    missile tail during EJECT/BOOST (front face at local z = +1.0)."""
    b = MeshBuilder()
    b.add_mesh(make_cylinder(_BST_R, _BST_LEN, SEG, PALETTE["booster"],
                             axis="z", cap_ends=True))
    exh_c = PALETTE["exhaust_ring"]
    # nozzle: dark exit disc + outward bell narrowing toward the casing
    b.add_mesh(make_lathe([(_BELL_Z, 0.0), (_BELL_Z, _BELL_R),
                           (-_BST_LEN * 0.5 - 0.02, 0.14)], SEG, exh_c))
    return b.build()
