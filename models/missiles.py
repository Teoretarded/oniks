"""Dedicated non-Oniks missile mesh builders.

Model space follows the project convention: forward = +Z, up = +Y, real
meters, origin at missile mid-body. Builders are pure MeshData.
"""

from __future__ import annotations

import math

import numpy as np

from engine.meshdata import (MeshBuilder, MeshData, make_box, make_cylinder,
                             make_fin, make_lathe, make_wedge)
from models.common import PALETTE, rot_x, rot_z
from models.s300 import build_s300_missile

SEG = 28
SEG_LOW = 16


def _ogive(z0: float, r0: float, z1: float, r1: float,
           n: int = 8, power: float = 1.6) -> list[tuple[float, float]]:
    pts = []
    for z in np.linspace(z0, z1, n)[1:]:
        t = (z - z0) / (z1 - z0)
        pts.append((float(z), float(r0 - (r0 - r1) * t ** power)))
    return pts


def _add_cruciform(builder: MeshBuilder, fin: MeshData,
                   angle0_deg: float = 45.0) -> None:
    for k in range(4):
        builder.add_mesh(fin, rotation=rot_z(math.radians(angle0_deg + 90.0 * k)))


def _add_pair(builder: MeshBuilder, fin: MeshData, angle_deg: float = 0.0) -> None:
    builder.add_mesh(fin, rotation=rot_z(math.radians(angle_deg)))
    builder.add_mesh(fin, rotation=rot_z(math.radians(angle_deg + 180.0)))


def _band(builder: MeshBuilder, radius: float, z: float, width: float,
          color, segments: int = SEG) -> None:
    builder.add_mesh(make_cylinder(radius, width, segments, color, axis="z",
                                   cap_ends=False, offset=(0.0, 0.0, z)))


def build_tomahawk() -> MeshData:
    """BGM-109 Tomahawk in cruise: tube body, straight pop-out wings,
    cruciform tail, ventral F107 intake and small tail nozzle."""
    b = MeshBuilder()
    body = PALETTE["missile_body"]
    fin_c = (0.72, 0.74, 0.74)
    dark = PALETTE["radome"]

    tail, nose = -3.125, 3.125
    r = 0.2635
    profile = [
        (tail, 0.17), (tail + 0.22, r * 0.92), (-2.25, r),
        (2.25, r),
    ]
    profile += _ogive(2.25, r, nose, 0.0, n=9, power=1.35)
    b.add_mesh(make_lathe(profile, SEG, body))
    _band(b, r + 0.006, -1.65, 0.05, (0.70, 0.70, 0.68))
    _band(b, r + 0.006, 0.65, 0.05, (0.70, 0.70, 0.68))

    # Two long straight wings pop from slots just aft of center.
    wing = make_fin(0.86, 0.72, 1.04, 0.08, 0.035, fin_c,
                    offset=(r * 0.92, 0.0, 0.34))
    _add_pair(b, wing)
    slot = make_box((0.04, 0.035, 0.95), PALETTE["exhaust_ring"],
                    offset=(r + 0.012, -0.03, 0.25))
    _add_pair(b, slot)

    # Cruciform pneumatic tail fins.
    tail_fin = make_fin(0.62, 0.38, 0.38, 0.18, 0.032, fin_c,
                        offset=(r * 0.86, 0.0, -2.32))
    _add_cruciform(b, tail_fin, 45.0)

    # Ventral turbofan intake under the aft body and a dark nozzle.
    b.add_mesh(make_wedge((0.34, 0.28, 0.74), dark),
               rotation=rot_x(math.radians(180.0)),
               offset=(0.0, -r - 0.10, -1.45))
    b.add_mesh(make_cylinder(0.13, 0.12, SEG_LOW, dark, axis="z",
                             offset=(0.0, 0.0, tail + 0.06)))
    return b.build()


def build_jassm() -> MeshData:
    """AGM-158 JASSM: compact faceted low-observable body, trapezoid wings,
    clipped tail controls and a flush dorsal intake."""
    b = MeshBuilder()
    body = (0.62, 0.66, 0.66)
    panel = (0.52, 0.56, 0.56)
    dark = PALETTE["radome"]
    tail, nose = -2.135, 2.135

    # Low-poly cylinder gives the faceted, chined fuselage instead of a round tube.
    r = 0.225
    profile = [
        (tail, 0.12), (tail + 0.28, r * 0.92), (-1.15, r),
        (1.12, r),
    ]
    profile += _ogive(1.12, r, nose, 0.0, n=7, power=1.15)
    b.add_mesh(make_lathe(profile, 10, body, smooth=False))

    # Flat stealth panels over the round-ish core.
    b.add_mesh(make_box((0.34, 0.08, 2.55), panel, offset=(0.0, 0.20, -0.15)))
    b.add_mesh(make_box((0.42, 0.05, 2.15), panel, offset=(0.0, -0.20, -0.15)))
    b.add_mesh(make_wedge((0.38, 0.16, 0.72), dark),
               offset=(0.0, 0.31, -1.32))

    wing = make_fin(1.25, 0.70, 1.04, 0.62, 0.035, (0.56, 0.60, 0.60),
                    offset=(0.19, 0.0, 0.18))
    _add_pair(b, wing)
    tail_fin = make_fin(0.46, 0.24, 0.32, 0.24, 0.028, (0.50, 0.54, 0.54),
                        offset=(0.18, 0.0, -1.56))
    _add_cruciform(b, tail_fin, 45.0)
    _band(b, r + 0.004, 1.18, 0.045, (0.86, 0.77, 0.22), segments=10)
    return b.build()


def build_harm() -> MeshData:
    """AGM-88 HARM: slim white tube, tan seeker nose, four large mid fins
    and four smaller tail fins."""
    b = MeshBuilder()
    body = PALETTE["missile_body"]
    fin_c = (0.78, 0.78, 0.76)
    tan = (0.74, 0.66, 0.48)

    tail, nose = -2.085, 2.085
    r = 0.127
    profile = [(tail, 0.09), (tail + 0.18, r), (1.50, r),
               (1.86, 0.075), (nose, 0.0)]
    b.add_mesh(make_lathe(profile, SEG, body))
    b.add_mesh(make_lathe([(1.56, 0.118), (1.92, 0.073), (nose, 0.0)],
                          SEG, tan))
    for z, col in ((1.18, (0.82, 0.76, 0.20)), (0.62, (0.55, 0.17, 0.12)),
                   (-0.78, (0.70, 0.64, 0.45))):
        _band(b, r + 0.004, z, 0.05, col)

    mid = make_fin(0.72, 0.34, 0.31, 0.22, 0.026, fin_c,
                   offset=(r * 0.92, 0.0, 0.20))
    _add_cruciform(b, mid, 45.0)
    tail_fin = make_fin(0.48, 0.26, 0.26, 0.18, 0.024, fin_c,
                        offset=(r * 0.92, 0.0, -1.48))
    _add_cruciform(b, tail_fin, 45.0)
    b.add_mesh(make_cylinder(0.070, 0.08, SEG_LOW, PALETTE["exhaust_ring"],
                             axis="z", offset=(0.0, 0.0, tail + 0.04)))
    return b.build()


def build_aim9x() -> MeshData:
    """AIM-9X Sidewinder: very small tube, glass seeker, forward
    double-delta canards and rear rolleron fins."""
    b = MeshBuilder()
    body = (0.72, 0.74, 0.70)
    dark = PALETTE["radome"]
    fin_c = (0.49, 0.51, 0.50)

    tail, nose = -1.50, 1.50
    r = 0.0635
    profile = [(tail, 0.045), (tail + 0.16, r), (1.08, r),
               (1.32, 0.052), (nose, 0.0)]
    b.add_mesh(make_lathe(profile, SEG_LOW, body))
    b.add_mesh(make_lathe([(1.18, 0.058), (1.38, 0.040), (nose, 0.0)],
                          SEG_LOW, dark))
    _band(b, r + 0.003, 0.60, 0.045, (0.90, 0.72, 0.18), segments=SEG_LOW)
    _band(b, r + 0.003, 0.12, 0.045, (0.72, 0.18, 0.12), segments=SEG_LOW)

    # AIM-9X forward strakes: small double-delta canards near the seeker.
    canard_a = make_fin(0.34, 0.10, 0.17, 0.18, 0.014, fin_c,
                        offset=(r * 0.92, 0.0, 0.83))
    canard_b = make_fin(0.22, 0.05, 0.12, 0.08, 0.012, fin_c,
                        offset=(r * 0.92, 0.0, 0.67))
    _add_cruciform(b, canard_a, 45.0)
    _add_cruciform(b, canard_b, 45.0)

    tail_fin = make_fin(0.42, 0.20, 0.22, 0.20, 0.018, fin_c,
                        offset=(r * 0.90, 0.0, -1.02))
    _add_cruciform(b, tail_fin, 45.0)
    roller = make_cylinder(0.018, 0.04, 8, PALETTE["exhaust_ring"], axis="x")
    for k in range(4):
        b.add_mesh(roller, rotation=rot_z(math.radians(45.0 + 90.0 * k)),
                   offset=(0.23, 0.0, -1.31))
    return b.build()


def build_48n6() -> MeshData:
    """S-300 48N6. Kept as the existing reference-built 48N6 model."""
    return build_s300_missile()


def build_40n6() -> MeshData:
    """40N6 long-range SAM: longer 48N6-family body, clean midsection,
    active-seeker nose band and slightly larger tail controls."""
    b = MeshBuilder()
    body = PALETTE["missile_body"]
    fin_c = PALETTE["fin"]
    tail, nose = -4.00, 4.00
    r = 0.2575

    profile = [(tail, 0.19), (tail + 0.28, r), (1.90, r)]
    profile += _ogive(1.90, r, 3.55, 0.078, n=8, power=1.75)
    b.add_mesh(make_lathe(profile, SEG, body))
    b.add_mesh(make_lathe([(3.55, 0.078), (nose, 0.0)], SEG,
                          PALETTE["radome"]))
    _band(b, r + 0.004, 2.40, 0.07, (0.55, 0.60, 0.63))
    _band(b, r + 0.004, -0.35, 0.05, (0.76, 0.78, 0.78))

    tail_fin = make_fin(1.14, 0.48, 0.54, 0.58, 0.035, fin_c,
                        offset=(0.235, 0.0, -2.86))
    _add_cruciform(b, tail_fin, 45.0)
    # Tiny aft conduit fairings only; keep the mid-body much cleaner than 48N6.
    conduit = make_fin(0.55, 0.28, 0.10, 0.15, 0.020, fin_c,
                       offset=(0.248, 0.0, -0.35))
    _add_cruciform(b, conduit, 45.0)
    b.add_mesh(make_cylinder(0.15, 0.10, SEG_LOW, PALETTE["exhaust_ring"],
                             axis="z", offset=(0.0, 0.0, tail + 0.05)))
    return b.build()


def build_sm2() -> MeshData:
    """SM-2 Block IIIB/ER game round: slender Standard Missile body with
    tail controls and a darker booster/nozzle section."""
    b = MeshBuilder()
    body = (0.83, 0.84, 0.80)
    fin_c = (0.60, 0.62, 0.62)
    tail, nose = -3.275, 3.275
    r = 0.1715

    profile = [(tail, 0.13), (tail + 0.28, r), (2.24, r)]
    profile += _ogive(2.24, r, nose, 0.0, n=8, power=1.25)
    b.add_mesh(make_lathe(profile, SEG, body))
    _band(b, r + 0.006, -2.30, 0.38, PALETTE["booster"])
    _band(b, r + 0.006, 0.98, 0.06, (0.72, 0.22, 0.18))
    _band(b, r + 0.006, 1.28, 0.05, (0.86, 0.76, 0.20))

    tail_fin = make_fin(0.86, 0.38, 0.37, 0.42, 0.030, fin_c,
                        offset=(r * 0.92, 0.0, -2.36))
    _add_cruciform(b, tail_fin, 45.0)
    b.add_mesh(make_cylinder(0.09, 0.11, SEG_LOW, PALETTE["exhaust_ring"],
                             axis="z", offset=(0.0, 0.0, tail + 0.055)))
    return b.build()


def build_57e6() -> MeshData:
    """Pantsir 57E6: two-stage bicaliber missile, fat rear booster and thin
    forward dart with small tail-control fins."""
    b = MeshBuilder()
    dart_c = (0.78, 0.78, 0.72)
    booster_c = (0.42, 0.36, 0.28)
    fin_c = PALETTE["fin"]
    tail, nose = -1.585, 1.585

    # Thin dart/sustainer forward of the booster.
    b.add_mesh(make_lathe([(-0.28, 0.038), (1.34, 0.038), (nose, 0.0)],
                          SEG_LOW, dart_c))
    # Fat, short booster aft: the key bicaliber signature.
    b.add_mesh(make_lathe([(tail, 0.072), (tail + 0.18, 0.085),
                           (-0.36, 0.085), (-0.20, 0.045)],
                          SEG_LOW, booster_c))
    _band(b, 0.088, -0.30, 0.07, (0.77, 0.56, 0.12), segments=SEG_LOW)
    _band(b, 0.041, 0.44, 0.035, (0.74, 0.20, 0.14), segments=SEG_LOW)

    booster_fin = make_fin(0.42, 0.18, 0.23, 0.18, 0.018, fin_c,
                           offset=(0.080, 0.0, -1.02))
    _add_cruciform(b, booster_fin, 45.0)
    dart_fin = make_fin(0.24, 0.08, 0.10, 0.10, 0.012, fin_c,
                        offset=(0.038, 0.0, -0.20))
    _add_cruciform(b, dart_fin, 45.0)
    b.add_mesh(make_cylinder(0.045, 0.07, 10, PALETTE["exhaust_ring"],
                             axis="z", offset=(0.0, 0.0, tail + 0.035)))
    return b.build()


def build_zircon() -> MeshData:
    """3M22 Zircon/Tsirkon prototype.

    The public external shape is not well documented, so this is a cautious
    visual model from open references: about 9 m long, ~0.6 m class body,
    chined hypersonic lifting body, ventral scramjet inlet/duct, small clipped
    fins and a dark annular rear exhaust.
    """
    b = MeshBuilder()
    skin = (0.45, 0.48, 0.48)
    panel = (0.36, 0.39, 0.39)
    dark = PALETTE["intake_black"]
    fin_c = (0.38, 0.42, 0.42)
    tail, nose = -4.50, 4.50
    r = 0.30

    profile = [
        (tail, 0.20), (tail + 0.30, r * 0.92), (-2.70, r),
        (1.85, r), (3.55, 0.18), (nose, 0.0),
    ]
    b.add_mesh(make_lathe(profile, 14, skin, smooth=False))

    # Chined lifting body: flattened dorsal/ventral faces and sharp side rails.
    b.add_mesh(make_box((0.58, 0.10, 5.75), panel, offset=(0.0, 0.24, -0.20)))
    b.add_mesh(make_box((0.66, 0.08, 4.35), panel, offset=(0.0, -0.24, -0.58)))
    for sx in (1.0, -1.0):
        b.add_mesh(make_box((0.06, 0.10, 4.95), (0.30, 0.34, 0.34),
                            offset=(sx * 0.34, -0.03, -0.28)))

    # Long ventral scramjet inlet and exhaust channel.
    b.add_mesh(make_wedge((0.42, 0.24, 1.25), dark),
               rotation=rot_x(math.radians(180.0)),
               offset=(0.0, -0.40, 0.35))
    b.add_mesh(make_box((0.36, 0.09, 2.15), dark, offset=(0.0, -0.39, -1.00)))
    b.add_mesh(make_cylinder(0.17, 0.14, SEG_LOW, dark, axis="z",
                             offset=(0.0, 0.0, tail + 0.07)))

    # Small hypersonic control surfaces, kept shorter than Oniks wings.
    mid = make_fin(1.05, 0.46, 0.47, 0.55, 0.030, fin_c,
                   offset=(0.28, 0.0, -0.40))
    _add_pair(b, mid)
    ventral = make_fin(0.88, 0.34, 0.34, 0.40, 0.028, fin_c,
                       offset=(0.26, 0.0, -0.90))
    _add_cruciform(b, ventral, 45.0)
    tail_fin = make_fin(0.62, 0.28, 0.36, 0.30, 0.028, fin_c,
                        offset=(0.25, 0.0, -3.32))
    _add_cruciform(b, tail_fin, 45.0)

    _band(b, r + 0.006, 2.70, 0.06, (0.28, 0.31, 0.32), segments=14)
    return b.build()


def build_sm6() -> MeshData:
    """RIM-174 SM-6 / Standard ERAM prototype.

    Uses the public 6.55 m Standard Missile length with a narrow 0.343 m
    upper body and the distinctive fat 0.53 m Mk 72 booster aft.
    """
    b = MeshBuilder()
    body = (0.86, 0.86, 0.82)
    booster = (0.72, 0.73, 0.70)
    dark = PALETTE["radome"]
    fin_c = (0.64, 0.66, 0.64)
    tail, nose = -3.275, 3.275
    upper_r = 0.1715
    booster_r = 0.265

    # Fat booster and narrower Standard/AMRAAM-derived upper stage.
    b.add_mesh(make_lathe([(tail, 0.18), (tail + 0.18, booster_r),
                           (-1.62, booster_r), (-1.22, upper_r)],
                          SEG, booster))
    profile = [(-1.22, upper_r), (2.33, upper_r)]
    profile += _ogive(2.33, upper_r, 3.08, 0.07, n=7, power=1.35)
    b.add_mesh(make_lathe(profile, SEG, body))
    b.add_mesh(make_lathe([(3.08, 0.07), (nose, 0.0)], SEG, dark))

    _band(b, booster_r + 0.006, -2.78, 0.08, (0.42, 0.44, 0.42))
    _band(b, upper_r + 0.006, -0.82, 0.06, (0.78, 0.72, 0.22))
    _band(b, upper_r + 0.006, 1.58, 0.05, (0.70, 0.20, 0.16))
    _band(b, upper_r + 0.006, 2.42, 0.05, (0.20, 0.21, 0.20))

    # Booster steering fins: large span, root near the aft motor.
    boost_fin = make_fin(0.78, 0.42, 0.52, 0.38, 0.034, fin_c,
                         offset=(booster_r * 0.88, 0.0, -2.48))
    _add_cruciform(b, boost_fin, 45.0)
    # Upper-stage dorsal cable/fins are low-profile.
    upper_fin = make_fin(0.80, 0.32, 0.18, 0.35, 0.026, fin_c,
                         offset=(upper_r * 0.95, 0.0, 0.05))
    _add_cruciform(b, upper_fin, 45.0)
    b.add_mesh(make_cylinder(0.13, 0.12, SEG_LOW, PALETTE["exhaust_ring"],
                             axis="z", offset=(0.0, 0.0, tail + 0.06)))
    return b.build()
