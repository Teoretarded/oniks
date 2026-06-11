"""P-800 Oniks missile model v2 — the Task OM2 reference build.

Built to the Top-10 signature list of docs/research/oniks_reference.md:
annular nose intake with a sharp dark cone protruding 0.45 m ahead of a
knife-edge lip at ~73% of body diameter, a DEEP BLACK annulus recessed
0.42 m, an ogive shoulder swelling to the full 0.67 m diameter over 1.4 m,
a clean tube body with a pair of slim flank cable raceways, four huge-root
clipped-delta wings (2.3 m root, 0.55 m exposed span, X orientation) on the
rear half, four small in-line tail rudders, gull-grey/grey-green skin, dark
dielectric cone, red tail cap accent.

Model space: forward = +Z, origin at mid-body. Bare round 8.6 m (cone tip at
+4.30); with the SUO nose cap fitted the round is 8.9 m (cap apex at +4.60 —
the reference's TPK-round figure). ``build_oniks(nose_cap=, wings_folded=)``
gives the launch variants Task LC animates (folded = surfaces rotated flat
against the body for the in-tube/first-instants look; they snap to X within
~0.2 s of exit). ``build_oniks_nose_cap()`` is the jettisoned cap part (also
the pulse-jet carrier visual). There is NO external booster model: the real
booster hides inside the ramjet duct and leaves as a slug out the nozzle
(game/sandbox.py owns that small dark cylinder).

Pure numpy / GL-free (returns ``MeshData``; callers upload via engine.mesh).
"""

from __future__ import annotations

import math

import numpy as np

from engine.meshdata import (MeshBuilder, MeshData, make_box, make_cylinder,
                             make_fin, make_lathe)
from models.common import PALETTE, rot_z

SEG = 32                 # lathe/cylinder segments

# Body stations (z, meters from mid-body origin; bare cone tip at +4.30)
_TAIL_Z = -4.30
_TAIL_R = 0.30           # nozzle exit radius
_RED_Z = -4.21           # red tail cap band ends here
_DARK_Z = -4.10          # dark nozzle ring band ends here
_BOAT_Z = -3.80          # boat-tail blends into the full-width mid-body
_BODY_R = 0.335          # mid-body radius (diameter 0.67)
_SHLD_Z = 2.45           # ogive shoulder begins (1.4 m run to the lip)
_LIP_Z = 3.85            # intake lip plane
_LIP_R = 0.245           # lip outer radius (~73% of body diameter)
_LIP_INNER = 0.235       # knife-edge wall thickness
_DUCT_Z = 3.43           # shock-cone base, buried 0.42 m behind the lip
_DUCT_R = 0.205
_NOSE_Z = 4.30           # cone tip: protrudes 0.45 m ahead of the lip

# SUO nose cap: skirt joins the ogive at +3.25, apex at +4.60 (8.9 m round)
_CAP_BASE_Z = 3.25
_CAP_R = 0.31            # skirt radius — a touch proud of the ogive beneath
CAP_LEN = 1.35           # base-to-apex (sandbox tumbling-part scale)

# Wings: clipped delta, root 55-83% of length, exposed span 0.55 (total
# span 1.70 with the 0.67 body), LE sweep ~60 deg. Roots sunk to r 0.30.
_ROOT_R = 0.30
_WING_LE_Z = -0.45
_WING = dict(root_chord=2.30, tip_chord=1.25, span=0.55, sweep=0.95,
             thickness=0.05)
# Tail rudders: small in-line clipped deltas on the boat-tail.
_RUD_LE_Z = -3.65
_RUD = dict(root_chord=0.55, tip_chord=0.22, span=0.30, sweep=0.32,
            thickness=0.035)
# Fold: surfaces rotate about their root-chord hinge until they lie back
# against the hull (flat plates cannot truly wrap the 0.71 m TPK bore, so
# the folded look trades exact containment for the right silhouette).
_WING_FOLD = math.radians(118.0)
_RUD_FOLD = math.radians(95.0)

# Cable raceways: slim half-round blisters on the flanks, 2.0-4.4 m from
# the nose (z +2.30 down to -0.10), slightly above the body mid-line.
_RACE_LEN = 2.4
_RACE_MID_Z = 1.10
_RACE_R = 0.030


def _boat_r(z: float) -> float:
    """Boat-tail radius at station z (linear from the nozzle to full body)."""
    return _TAIL_R + (_BODY_R - _TAIL_R) * (z - _TAIL_Z) / (_BOAT_Z - _TAIL_Z)


def _ogive_profile(z_end: float):
    """Convex shoulder from the mid-body toward the lip: (z, r) points."""
    pts = []
    for z in np.linspace(_SHLD_Z, z_end, 8)[1:]:
        t = (z - _SHLD_Z) / (_LIP_Z - _SHLD_Z)
        pts.append((float(z), _BODY_R - (_BODY_R - _LIP_R) * t ** 1.8))
    return pts


def _cap_profile():
    """The SUO cap cone in its own space (base ring at z=0, apex at CAP_LEN):
    slightly convex so the capped nose reads as one smooth ogive-cone
    (brahmos_display_drdo01.jpg look)."""
    pts = [(0.0, _CAP_R)]
    for t in np.linspace(0.0, 1.0, 7)[1:]:
        pts.append((float(CAP_LEN * t), float(_CAP_R * (1.0 - t ** 1.7))))
    return pts


def _add_surfaces(b: MeshBuilder, params: dict, le_z: float, fold: float,
                  color) -> None:
    """Four clipped-delta surfaces in X orientation. ``fold`` rotates each
    panel about its root-chord hinge (0 = deployed straight out)."""
    fin = make_fin(params["root_chord"], params["tip_chord"], params["span"],
                   params["sweep"], params["thickness"], color)
    one = MeshBuilder()
    one.add_mesh(fin, rotation=rot_z(fold), offset=(_ROOT_R, 0.0, le_z))
    one_md = one.build()
    for k in range(4):
        b.add_mesh(one_md, rotation=rot_z(math.radians(45.0 + 90.0 * k)))


def build_oniks_nose_cap() -> MeshData:
    """The jettisoned SUO fairing: a 1.35 m dark cone (base at local z=0,
    apex forward at +Z) wearing its pulse-jet hardware — a dark ring band
    and four port bumps near the base (the 'small dark angular chunk' of
    the launch footage; pulse jets fire from here during pitch-over)."""
    b = MeshBuilder()
    radome_c = PALETTE["radome"]
    # base disc (visible while tumbling) + the convex cone shell
    b.add_mesh(make_lathe([(0.0, 0.0), (0.0, _CAP_R)], SEG, radome_c))
    b.add_mesh(make_lathe(_cap_profile(), SEG, radome_c))
    # pulse-jet collar: near-black band + four port bumps at 45 deg
    b.add_mesh(make_cylinder(_CAP_R + 0.004, 0.12, SEG,
                             PALETTE["intake_black"], axis="z",
                             cap_ends=False, offset=(0.0, 0.0, 0.10)))
    port = make_box((0.05, 0.022, 0.08), PALETTE["intake_black"],
                    offset=(_CAP_R - 0.01, 0.0, 0.10))
    for k in range(4):
        b.add_mesh(port, rotation=rot_z(math.radians(45.0 + 90.0 * k)))
    return b.build()


def build_oniks(nose_cap: bool = False, wings_folded: bool = False) -> MeshData:
    b = MeshBuilder()
    body_c = PALETTE["oniks_body"]
    wing_c = PALETTE["oniks_wing"]
    radome_c = PALETTE["radome"]

    # tail: red cap accent (display-round nozzle cover) + dark nozzle ring
    b.add_mesh(make_lathe([(_TAIL_Z, 0.0), (_TAIL_Z, _TAIL_R),
                           (_RED_Z, _boat_r(_RED_Z))], SEG,
                          PALETTE["tail_red"]))
    b.add_mesh(make_lathe([(_RED_Z, _boat_r(_RED_Z)),
                           (_DARK_Z, _boat_r(_DARK_Z))], SEG,
                          PALETTE["exhaust_ring"]))
    # main body: boat-tail -> clean cylinder -> ogive shoulder
    profile = [(_DARK_Z, _boat_r(_DARK_Z)), (_BOAT_Z, _BODY_R),
               (_SHLD_Z, _BODY_R)]
    if nose_cap:
        # ogive only up to the cap joint; the cap closes the nose
        profile += _ogive_profile(_CAP_BASE_Z)
        b.add_mesh(make_lathe(profile, SEG, body_c))
        b.add_mesh(build_oniks_nose_cap(), offset=(0.0, 0.0, _CAP_BASE_Z))
    else:
        profile += _ogive_profile(_LIP_Z)
        b.add_mesh(make_lathe(profile, SEG, body_c))
        # knife-edge lip face: thin forward-facing ring closing the wall
        b.add_mesh(make_lathe([(_LIP_Z, _LIP_R), (_LIP_Z, _LIP_INNER)], SEG,
                              body_c))
        # the DEEP BLACK annulus: duct funnel from the lip back to the cone
        # base. The profile runs BACKWARD in z on purpose — make_lathe's
        # normal/winding rule (n = (dz, -dr)) then faces the surface inward,
        # like a duct interior.
        b.add_mesh(make_lathe([(_LIP_Z, _LIP_INNER), (_DUCT_Z, _DUCT_R)], SEG,
                              PALETTE["intake_black"]))
        # the sharp dielectric shock cone punching out to the nose tip
        b.add_mesh(make_lathe([(_DUCT_Z, _DUCT_R), (_NOSE_Z, 0.0)], SEG,
                              radome_c))
        # tiny probe vane near the top of the nose section (armia2018 round)
        b.add_mesh(make_fin(0.16, 0.04, 0.09, 0.10, 0.018, radome_c),
                   rotation=rot_z(math.radians(90.0)),
                   offset=(0.0, 0.30, 3.05))

    # pair of slim cable raceways on the flanks (signature 7)
    for sx in (1.0, -1.0):
        b.add_mesh(make_cylinder(_RACE_R, _RACE_LEN, 10, wing_c, axis="z",
                                 cap_ends=True,
                                 offset=(sx * (_BODY_R + 0.012), 0.05,
                                         _RACE_MID_Z)))

    # wings + in-line tail rudders, X orientation (deployed or folded flat)
    _add_surfaces(b, _WING, _WING_LE_Z,
                  _WING_FOLD if wings_folded else 0.0, wing_c)
    _add_surfaces(b, _RUD, _RUD_LE_Z,
                  _RUD_FOLD if wings_folded else 0.0, wing_c)
    return b.build()
