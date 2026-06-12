"""Procedural E-3 Sentry-class AWACS model.

Real scale: 46.6 m long, 44.4 m wingspan.
Model space: forward = +Z (nose at +z_max), up = +Y,
origin at the center of mass (mid-fuselage). Pure numpy, GL-free.

Key visual signatures reproduced in stylised low-poly:
  - Long tube fuselage (modified Boeing 707 airframe).
  - Four underwing turbofan pods (two per wing, cylinders).
  - Swept trapezoidal main wings.
  - T-tail: horizontal stabilisers on top of the vertical fin.
  - THE signature: a 9.1 m diameter rotodome disc on two dorsal struts
    above the aft fuselage (~z = −4 m from centre).
  - Gray/white livery: fuselage light gray, dome white.
"""

from __future__ import annotations

import math

from engine.meshdata import MeshBuilder, MeshData, make_box, make_cylinder, make_fin, make_lathe
from models.common import PALETTE, rot_x, rot_y, rot_z

# ---------------------------------------------------------------------------
# Geometry constants — all in real metres, +Z forward
# ---------------------------------------------------------------------------

# Full length 46.6 m; origin at mid-fuselage.
_HALF_L = 23.3          # m  (46.6 / 2)
_HALF_SPAN = 22.2       # m  (44.4 / 2)

# Rotodome: 9.1 m diameter disc, 1.8 m thick, on two struts above aft fuselage.
_DOME_RADIUS = 4.55     # m  (9.1 m diameter / 2)
_DOME_THICK  = 1.8      # m

_SEG = 28               # lathe/cylinder segments

# Colours
_GREY  = PALETTE["aircraft_grey"]
_DARK  = PALETTE["aircraft_dark"]
_WHITE = PALETTE["radar_white"]
_EXHAUST = PALETTE["exhaust_ring"]

_ROT_MIRROR = rot_z(math.pi)   # +X wing -> -X wing

# Fuselage profile: tube body, tapered nose, rounded tail.
# (z, radius) — +z is nose end.
_FUSELAGE_PROFILE = [
    (-_HALF_L, 0.0),        # tail tip (closed)
    (-20.0, 1.30),
    (-16.0, 1.60),
    (-10.0, 1.80),
    ( -4.0, 1.90),
    (  4.0, 1.90),
    ( 12.0, 1.88),
    ( 18.0, 1.75),
    ( 21.0, 1.40),
    ( 22.5, 0.80),
    (_HALF_L, 0.0),         # nose tip (closed)
]

_NOSE_CAP = [
    (21.5, 0.82),
    (_HALF_L, 0.0),
]


def _main_wings(b: MeshBuilder) -> None:
    """Swept Boeing 707-style main wings, four pylons/pods per pair.

    Root chord 10.0 m, tip chord 3.0 m, semi-span 20.0 m, sweep 5.0 m.
    Wing root leading edge at z ≈ +2 m, y ≈ −0.8 m (bottom of fuselage).
    """
    wing = make_fin(10.0, 3.0, 20.0, 5.0, 0.30, _GREY)
    b.add_mesh(wing, offset=(1.90, -0.80, 2.0))
    b.add_mesh(wing, rotation=_ROT_MIRROR, offset=(-1.90, -0.80, 2.0))


def _engine_pods(b: MeshBuilder) -> None:
    """Four TF33 turbofan pods slung under the wings on pylons.

    Two pods per wing; inboard at 6 m span, outboard at 12 m span.
    Each pod: radius 0.65 m, length 5.5 m. Dark nozzle ring at the aft end.
    Pylons are thin vertical struts between pod and wing.
    """
    pod_y  = -2.60   # pod centreline height (below wing)
    pylon_h = 1.20   # pylon strut height

    for sx in (1.0, -1.0):          # starboard / port
        for span_x in (6.0, 12.0):  # inboard / outboard pod position
            pod_z = 2.0 - span_x * 0.25   # swept-back: inboard pod a bit fwd
            px = sx * span_x
            # Turbofan pod body
            b.add_mesh(make_cylinder(0.65, 5.5, 18, _GREY, axis="z",
                                     offset=(px, pod_y, pod_z)))
            # Dark intake lip (forward rim)
            b.add_mesh(make_cylinder(0.63, 0.5, 18, _DARK, axis="z",
                                     offset=(px, pod_y, pod_z + 2.80)))
            # Dark exhaust nozzle (aft rim)
            b.add_mesh(make_cylinder(0.60, 0.5, 18, _EXHAUST, axis="z",
                                     offset=(px, pod_y, pod_z - 2.80)))
            # Pylon strut (thin box)
            b.add_mesh(make_box((0.25, pylon_h, 1.2), _GREY,
                                offset=(px, pod_y + 0.65 + pylon_h * 0.5, pod_z)))


def _vertical_fin(b: MeshBuilder) -> None:
    """Single upright vertical fin with T-tail configuration.

    make_fin spans in +X (span from root to tip); we rotate it upright with
    rot_z(-π/2) so span goes into +Y.
    Root chord 8.0 m, tip chord 3.5 m, span 6.5 m, sweep 3.0 m.
    """
    rot_upright = rot_z(-0.5 * math.pi)
    vfin = make_fin(8.0, 3.5, 6.5, 3.0, 0.22, _GREY)
    b.add_mesh(vfin, rotation=rot_upright, offset=(0.0, 1.70, -16.0))


def _horizontal_stabs(b: MeshBuilder) -> None:
    """T-tail horizontal stabilisers atop the vertical fin (~y = 8.2 m).

    Root chord 5.0 m, tip chord 2.0 m, semi-span 8.0 m, sweep 3.0 m.
    """
    stab = make_fin(5.0, 2.0, 8.0, 3.0, 0.20, _GREY)
    b.add_mesh(stab, offset=(0.0, 8.2, -18.0))
    b.add_mesh(stab, rotation=_ROT_MIRROR, offset=(0.0, 8.2, -18.0))


def _rotodome(b: MeshBuilder) -> None:
    """9.1 m diameter rotodome on two dorsal struts above aft fuselage.

    The rotodome is modelled as a flattened disc (squashed cylinder) plus
    a white top and bottom — the characteristic flying saucer silhouette.
    Two rectangular struts connect it to the fuselage spine.

    Centre of the disc is ~2.8 m above the fuselage centreline, at z ≈ −4.0 m.
    """
    dome_cy = 2.80    # dome centre y above fuselage centreline
    dome_cz = -4.00   # dome centre z (aft of centre)

    # Disc body: a wide, flat cylinder (axis = y so it lies horizontal)
    b.add_mesh(make_cylinder(_DOME_RADIUS, _DOME_THICK, _SEG + 4, _WHITE,
                             axis="y",
                             offset=(0.0, dome_cy + 1.90, dome_cz)))

    # Grey band around the disc edge (the rotating antenna housing)
    b.add_mesh(make_cylinder(_DOME_RADIUS + 0.08, _DOME_THICK * 0.6, 12, _GREY,
                             axis="y",
                             offset=(0.0, dome_cy + 1.90, dome_cz)))

    # Two vertical struts from fuselage top (~y = 1.9 m) to disc bottom
    # Struts are thin boxes, spaced ±2.5 m in z
    strut_base_y = 1.90   # top of fuselage at this z
    strut_top_y  = dome_cy + 1.90 - _DOME_THICK * 0.5 - 0.1
    strut_h = strut_top_y - strut_base_y

    for sz in (-2.5, 2.5):
        b.add_mesh(make_box((0.30, strut_h, 0.30), _GREY,
                            offset=(0.0,
                                    strut_base_y + strut_h * 0.5,
                                    dome_cz + sz)))


def build_awacs() -> MeshData:
    """E-3 Sentry AWACS: 46.6 m long, 44.4 m span, gray/white.

    Signature: 9.1 m diameter rotodome on two dorsal struts aft of centre.
    Four underwing engine pods. T-tail. Unarmed.
    Model space: forward = +Z, up = +Y, origin at mid-fuselage.
    """
    b = MeshBuilder()

    # Main fuselage tube
    b.add_mesh(make_lathe(_FUSELAGE_PROFILE, _SEG, _GREY))
    # Dark nose radome
    b.add_mesh(make_lathe(_NOSE_CAP, _SEG, _DARK))

    # Lifting surfaces
    _main_wings(b)
    _vertical_fin(b)
    _horizontal_stabs(b)

    # Four underwing engine pods
    _engine_pods(b)

    # THE signature: rotodome
    _rotodome(b)

    return b.build()
