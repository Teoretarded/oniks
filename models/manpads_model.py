"""MANPADS launcher + missile mesh builders (walk-mode weapons).

Model space follows the project convention: forward = +Z, up = +Y, real
meters, missile origin at mid-body. Launchers are built with the tube
axis along +Z, origin at the tube center, and hang their gripstock /
battery / sights below and beside the tube — the rig positions them at
the player's shoulder.

Proportions and distinctive features from the reference photos listed in
docs/research/manpads_reference.md:
- Igla-S: thin olive tube, sausage battery under the forward tube, the
  needle standoff probe on a tripod ahead of the seeker ball.
- Stinger: bell muzzle, boxy gripstock, fold-down IFF antenna grid,
  BCU cylinder slanting down-forward, near-hemispherical seeker dome.
- Piorun: Grom/Igla lineage with a squarer grip unit and a rectangular
  sight bracket over the tube.
- Starstreak: fat dark canister with a clipped-on grey aiming unit, and
  the missile a two-stage stack carrying three tungsten darts.
"""

from __future__ import annotations

import math

import numpy as np

from engine.meshdata import (MeshBuilder, MeshData, make_box, make_cylinder,
                             make_fin, make_lathe)
from models.common import PALETTE, rot_x, rot_z

SEG = 24
SEG_LOW = 12

OLIVE = PALETTE["mil_green"]
OLIVE_DARK = PALETTE["mil_green_dark"]
GREY = PALETTE["tube_grey"]
DARK = PALETTE["radome"]
BODY = PALETTE["missile_body"]
FIN = PALETTE["fin"]
KHAKI = PALETTE["canvas_khaki"]


def _ogive(z0, r0, z1, r1, n=7, power=1.6):
    pts = []
    for z in np.linspace(z0, z1, n)[1:]:
        t = (z - z0) / (z1 - z0)
        pts.append((float(z), float(r0 - (r0 - r1) * t ** power)))
    return pts


def _cruciform(b, fin, angle0=45.0):
    for k in range(4):
        b.add_mesh(fin, rotation=rot_z(math.radians(angle0 + 90.0 * k)))


def _pair(b, fin, angle0=0.0):
    b.add_mesh(fin, rotation=rot_z(math.radians(angle0)))
    b.add_mesh(fin, rotation=rot_z(math.radians(angle0 + 180.0)))


# ------------------------------------------------------------------ missiles

def _igla_family_missile(length: float, body_col, band_col) -> MeshBuilder:
    """Shared Igla/Piorun airframe: 72 mm tube, seeker ball behind the
    needle standoff probe on its tripod, one steered canard pair + fixed
    strakes, four swept folding tail fins."""
    b = MeshBuilder()
    r = 0.036
    tail, nose = -length * 0.5, length * 0.5
    dome_z = nose - 0.10                 # seeker ball starts here
    probe_z = nose - 0.045               # needle probe base
    # nozzle + body
    b.add_mesh(make_lathe([(tail, 0.0), (tail, 0.028), (tail + 0.05, r)],
                          SEG, DARK))
    b.add_mesh(make_lathe([(tail + 0.05, r), (dome_z - 0.16, r)], SEG,
                          body_col))
    # seeker section band + glass ball
    b.add_mesh(make_lathe([(dome_z - 0.16, r), (dome_z, r)], SEG, band_col))
    b.add_mesh(make_lathe([(dome_z, r)] + _ogive(dome_z, r, probe_z, 0.012,
                                                 n=6, power=0.62), SEG, DARK))
    # the needle: tripod legs + standoff probe with a tiny cone tip
    for k in range(3):
        leg = make_cylinder(0.0022, 0.075, 6, GREY, axis="z",
                            offset=(0.016, 0.0, probe_z + 0.012))
        b.add_mesh(leg, rotation=rot_z(math.radians(120.0 * k)))
    b.add_mesh(make_cylinder(0.004, nose - probe_z, 8, GREY, axis="z",
                             offset=(0.0, 0.0, (probe_z + nose) * 0.5)))
    b.add_mesh(make_lathe([(nose - 0.012, 0.006), (nose, 0.0)], 8, GREY))
    # steered canards (one pair) + fixed strakes (rotated 90)
    canard = make_fin(0.055, 0.03, 0.042, 0.028, 0.004, FIN,
                      offset=(r * 0.9, 0.0, dome_z - 0.30))
    _pair(b, canard, 0.0)
    strake = make_fin(0.09, 0.07, 0.02, 0.012, 0.004, FIN,
                      offset=(r * 0.95, 0.0, dome_z - 0.42))
    _pair(b, strake, 90.0)
    # four swept folding tail fins
    tf = make_fin(0.085, 0.045, 0.075, 0.055, 0.004, FIN,
                  offset=(r * 0.9, 0.0, tail + 0.14))
    _cruciform(b, tf, 45.0)
    return b


def _igla_missile() -> MeshData:
    return _igla_family_missile(1.635, (0.72, 0.73, 0.68),
                                (0.30, 0.32, 0.30)).build()


def _piorun_missile() -> MeshData:
    b = _igla_family_missile(1.596, (0.66, 0.68, 0.64), (0.22, 0.24, 0.26))
    # Piorun's proximity-fuse collar just behind the seeker section.
    b.add_mesh(make_cylinder(0.0375, 0.05, SEG, (0.16, 0.17, 0.19), axis="z",
                             cap_ends=False, offset=(0.0, 0.0, 0.52)))
    return b.build()


def _stinger_missile() -> MeshData:
    b = MeshBuilder()
    r = 0.035
    length = 1.52
    tail, nose = -length * 0.5, length * 0.5
    b.add_mesh(make_lathe([(tail, 0.0), (tail, 0.026), (tail + 0.04, r)],
                          SEG, DARK))
    b.add_mesh(make_lathe([(tail + 0.04, r), (nose - 0.22, r)], SEG, BODY))
    # near-hemispherical IR/UV dome behind a short conical tip
    b.add_mesh(make_lathe([(nose - 0.22, r)]
                          + _ogive(nose - 0.22, r, nose, 0.0, n=8,
                                   power=0.55), SEG, DARK))
    # seeker-section wrap
    b.add_mesh(make_cylinder(r + 0.002, 0.06, SEG, (0.45, 0.47, 0.50),
                             axis="z", cap_ends=False,
                             offset=(0.0, 0.0, nose - 0.30)))
    # 4 pop-out nose canards + 4 folding tail fins
    canard = make_fin(0.05, 0.028, 0.048, 0.03, 0.004, FIN,
                      offset=(r * 0.9, 0.0, nose - 0.36))
    _cruciform(b, canard, 0.0)
    tf = make_fin(0.08, 0.05, 0.088, 0.05, 0.004, FIN,
                  offset=(r * 0.9, 0.0, tail + 0.12))
    _cruciform(b, tf, 45.0)
    return b.build()


def _starstreak_missile() -> MeshData:
    """The HVM stack: second-stage motor with the three-dart cluster in
    its nose fairing."""
    b = MeshBuilder()
    r = 0.065
    length = 1.40
    tail, nose = -length * 0.5, length * 0.5
    b.add_mesh(make_lathe([(tail, 0.0), (tail, 0.05), (tail + 0.06, r)],
                          SEG, DARK))
    b.add_mesh(make_lathe([(tail + 0.06, r), (nose - 0.42, r)], SEG,
                          OLIVE_DARK))
    b.add_mesh(make_lathe([(nose - 0.42, r)]
                          + _ogive(nose - 0.42, r, nose, 0.0, n=8,
                                   power=1.1), SEG, OLIVE))
    # dart noses peeking around the fairing seam
    for k in range(3):
        dart_tip = make_lathe([(nose - 0.44, 0.011), (nose - 0.30, 0.0)],
                              8, (0.35, 0.34, 0.36))
        b.add_mesh(dart_tip, rotation=rot_z(math.radians(120.0 * k)),
                   offset=(math.cos(math.radians(90.0 + 120.0 * k)) * 0.032,
                           math.sin(math.radians(90.0 + 120.0 * k)) * 0.032,
                           0.0))
    tf = make_fin(0.11, 0.06, 0.09, 0.06, 0.005, FIN,
                  offset=(r * 0.9, 0.0, tail + 0.14))
    _cruciform(b, tf, 45.0)
    return b.build()


def build_dart() -> MeshData:
    """One Starstreak tungsten dart: a finned needle, 0.45 m."""
    b = MeshBuilder()
    r = 0.011
    tail, nose = -0.225, 0.225
    b.add_mesh(make_lathe([(tail, 0.0), (tail, r * 0.8), (tail + 0.02, r)],
                          SEG_LOW, DARK))
    b.add_mesh(make_lathe([(tail + 0.02, r), (nose - 0.14, r)], SEG_LOW,
                          (0.35, 0.34, 0.36)))
    b.add_mesh(make_lathe([(nose - 0.14, r)]
                          + _ogive(nose - 0.14, r, nose, 0.0, n=6,
                                   power=1.3), SEG_LOW, (0.30, 0.29, 0.31)))
    canard = make_fin(0.02, 0.012, 0.014, 0.008, 0.002, FIN,
                      offset=(r * 0.9, 0.0, nose - 0.17))
    _cruciform(b, canard, 45.0)
    tf = make_fin(0.035, 0.02, 0.022, 0.014, 0.002, FIN,
                  offset=(r * 0.9, 0.0, tail + 0.03))
    _cruciform(b, tf, 0.0)
    return b.build()


# ----------------------------------------------------------------- launchers

def _grip(b, z, col=DARK, tall=0.16):
    """Pistol-grip trigger unit hanging under the tube at z."""
    b.add_mesh(make_box((0.045, 0.075, 0.16), col, offset=(0.0, -0.085, z)))
    b.add_mesh(make_box((0.035, tall, 0.05), col,
                        offset=(0.0, -0.085 - tall * 0.5, z - 0.05)))


def _igla_launcher(length=1.70, r=0.041, sight_box=False) -> MeshData:
    b = MeshBuilder()
    # thin olive tube with a flared muzzle and a rear ring
    b.add_mesh(make_cylinder(r, length - 0.10, SEG, OLIVE, axis="z",
                             cap_ends=False))
    b.add_mesh(make_lathe([(length * 0.5 - 0.06, r),
                           (length * 0.5, r + 0.012)], SEG, OLIVE_DARK))
    b.add_mesh(make_lathe([(-length * 0.5, r + 0.008),
                           (-length * 0.5 + 0.05, r)], SEG, OLIVE_DARK))
    _grip(b, -0.18)
    # sausage ground-power battery slung under the forward tube
    bat = make_cylinder(0.032, 0.24, SEG_LOW, OLIVE_DARK, axis="z",
                        offset=(0.0, -r - 0.045, 0.32))
    b.add_mesh(bat, rotation=rot_x(math.radians(14.0)))
    if sight_box:
        # Piorun's rectangular sight bracket over the tube
        b.add_mesh(make_box((0.06, 0.07, 0.16), (0.18, 0.19, 0.21),
                            offset=(0.0, r + 0.05, 0.05)))
    else:
        # simple blade sight
        b.add_mesh(make_box((0.008, 0.05, 0.03), DARK,
                            offset=(0.0, r + 0.03, 0.28)))
    return b.build()


def _stinger_launcher() -> MeshData:
    b = MeshBuilder()
    length, r = 1.52, 0.045
    b.add_mesh(make_cylinder(r, length - 0.24, SEG, KHAKI, axis="z",
                             cap_ends=False, offset=(0.0, 0.0, -0.06)))
    # bell muzzle flare
    b.add_mesh(make_lathe([(length * 0.5 - 0.18, r),
                           (length * 0.5, r + 0.025)], SEG, KHAKI))
    # dark breech cone behind the shoulder
    b.add_mesh(make_lathe([(-length * 0.5 - 0.10, 0.02),
                           (-length * 0.5 + 0.06, r)], SEG, DARK))
    _grip(b, -0.22, col=(0.14, 0.15, 0.16))
    # gripstock body + BCU cylinder slanting down-forward
    b.add_mesh(make_box((0.06, 0.10, 0.30), (0.14, 0.15, 0.16),
                        offset=(0.0, -r - 0.04, -0.12)))
    bcu = make_cylinder(0.02, 0.14, SEG_LOW, (0.25, 0.26, 0.24), axis="y",
                        offset=(0.0, -r - 0.14, 0.02))
    b.add_mesh(bcu, rotation=rot_x(math.radians(-25.0)))
    # fold-down IFF antenna GRID under the muzzle half
    grid = MeshBuilder()
    for i in range(4):
        grid.add_mesh(make_box((0.002, 0.002, 0.16), GREY,
                               offset=(-0.03 + i * 0.02, 0.0, 0.0)))
    for j in range(3):
        grid.add_mesh(make_box((0.08, 0.002, 0.002), GREY,
                               offset=(0.0, 0.0, -0.07 + j * 0.07)))
    b.add_mesh(grid.build(), rotation=rot_x(math.radians(-50.0)),
               offset=(0.0, -r - 0.05, 0.38))
    # open-sight frame on top
    b.add_mesh(make_box((0.10, 0.07, 0.008), (0.20, 0.21, 0.22),
                        offset=(0.0, r + 0.045, 0.16)))
    return b.build()


def _starstreak_launcher() -> MeshData:
    b = MeshBuilder()
    length, r = 1.45, 0.075
    b.add_mesh(make_cylinder(r, length, SEG, (0.22, 0.26, 0.21), axis="z",
                             cap_ends=False))
    # rounded end rings
    b.add_mesh(make_lathe([(length * 0.5 - 0.04, r + 0.01),
                           (length * 0.5, r - 0.01)], SEG, OLIVE_DARK))
    b.add_mesh(make_lathe([(-length * 0.5, r - 0.01),
                           (-length * 0.5 + 0.04, r + 0.01)], SEG,
                          OLIVE_DARK))
    for z in (-0.35, 0.35):
        b.add_mesh(make_cylinder(r + 0.008, 0.05, SEG, OLIVE_DARK, axis="z",
                                 cap_ends=False, offset=(0.0, 0.0, z)))
    # clip-on aiming unit: grey box + forward monocular on the left side
    b.add_mesh(make_box((0.20, 0.18, 0.26), (0.34, 0.36, 0.38),
                        offset=(-r - 0.11, -0.02, 0.05)))
    b.add_mesh(make_cylinder(0.03, 0.12, SEG_LOW, DARK, axis="z",
                             offset=(-r - 0.11, 0.03, 0.23)))
    b.add_mesh(make_box((0.05, 0.09, 0.05), DARK,
                        offset=(-r - 0.11, -0.14, -0.04)))
    return b.build()


_MISSILES = {
    "igla_s": _igla_missile,
    "stinger": _stinger_missile,
    "piorun": _piorun_missile,
    "starstreak": _starstreak_missile,
}

_LAUNCHERS = {
    "igla_s": lambda: _igla_launcher(),
    "stinger": _stinger_launcher,
    "piorun": lambda: _igla_launcher(length=1.66, r=0.041, sight_box=True),
    "starstreak": _starstreak_launcher,
}


def build_missile(spec_id: str) -> MeshData:
    return _MISSILES[spec_id]()


def build_launcher(spec_id: str) -> MeshData:
    return _LAUNCHERS[spec_id]()
