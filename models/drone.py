"""RQ-4-class stealth recon drone 3D model.

Real scale: 14.5 m long, 39.9 m wingspan.
Signature features:
  - Long thin high-aspect-ratio wings (39.9 m span, ~2 m chord at root)
  - Bulbous whale-nose front (large sensor/radome blister)
  - Slim fuselage / tail boom
  - V-tail (two canted fins, no conventional horizontal stabiliser)
  - Dorsal engine hump with intake behind the wing root
  - No canopy (uncrewed)
  - Light pale-grey skin ('drone_skin' added to PALETTE)

Model space per LOCKED CONVENTIONS:
  forward = +Z (nose at max z), up = +Y, real meters,
  origin at fuselage centre-of-mass (mid-fuselage).
Pure numpy, GL-free.
"""

from __future__ import annotations

import math

from engine.meshdata import MeshBuilder, MeshData, make_box, make_fin, make_lathe
from models.common import PALETTE, rot_x, rot_z

# ---------------------------------------------------------------------------
# Palette extension – pale grey drone skin.
# RQ-4 Global Hawk is painted FS 36375 'Light Ghost Grey'; linear-RGB approx.
# We match the existing 'radar_white' (#D9DBDA) tone but slightly cooler.
# ---------------------------------------------------------------------------
PALETTE.setdefault("drone_skin", (0.82, 0.83, 0.85))   # pale cool grey
PALETTE.setdefault("drone_dark", (0.36, 0.37, 0.40))   # engine intake / belly

# Fuselage lathe resolution – same density as aircraft_model.py
_SEG = 26

# Mirror right side to left
_ROT_MIRROR = rot_z(math.pi)

# V-tail cant angle: RQ-4 V-tail is ~35° from vertical on each side.
_VTAIL_CANT_DEG = 35.0
_VTAIL_CANT_RAD = math.radians(_VTAIL_CANT_DEG)


def build_recon_drone() -> MeshData:
    """Build the RQ-4-class recon drone.

    Dimensions (approximate real-world values, SI metres):
      - Length: 14.5 m  (fuselage z range ~ -7.25 .. +7.25)
      - Wingspan: 39.9 m (wing tip x ~ ±19.95)
      - Height: ~4 m (sensor blister + engine hump)

    The fuselage is a lathe with a pronounced bulbous nose blister that gives
    the whale-nose appearance.  The tail boom tapers to a very narrow diameter.
    Wings are extremely long-span, low-chord (high-aspect-ratio).
    V-tail fins are attached near the aft end and canted outward.
    A flat dorsal engine hump with intake sits on the fuselage spine just behind
    the wing root.
    """
    b = MeshBuilder()
    skin = PALETTE["drone_skin"]
    dark = PALETTE["drone_dark"]

    # ------------------------------------------------------------------
    # Fuselage lathe – (z, radius) profile.
    # Origin at z=0 (mid-fuselage).  Nose at +z, tail at -z.
    # The whale nose: the front 3 m bulges upward; modelled as a wider
    # radius in the lathe (gives the rounded blister in all directions;
    # the dorsal box below then forms the actual hump).
    # ------------------------------------------------------------------
    fuselage_profile = [
        (-7.25, 0.05),   # tail tip
        (-6.80, 0.18),
        (-5.50, 0.30),
        (-3.80, 0.42),
        (-1.50, 0.52),
        ( 0.00, 0.56),   # mid-body (widest cylindrical section)
        ( 2.00, 0.58),
        ( 3.50, 0.72),   # start of nose blister
        ( 5.00, 0.92),   # nose blister peak radius
        ( 6.00, 0.88),
        ( 6.80, 0.68),
        ( 7.10, 0.32),
        ( 7.25, 0.05),   # nose tip
    ]
    b.add_mesh(make_lathe(fuselage_profile, _SEG, skin))

    # ------------------------------------------------------------------
    # Nose radome cap: dark sensor dome on the front tip.
    # Short lathe covering the last 0.5 m of the nose.
    # ------------------------------------------------------------------
    nose_cap = [
        (6.80, 0.68),
        (7.10, 0.32),
        (7.25, 0.05),
    ]
    b.add_mesh(make_lathe(nose_cap, _SEG, dark))

    # ------------------------------------------------------------------
    # Main wings: very high aspect ratio.
    # make_fin(root_chord, tip_chord, span, sweep, thickness, color)
    # Origin at root leading edge; span along +X; chord along -Z.
    # Root placed so wing root LE is at z ~ +1.5 m (just ahead of CoM).
    # Span per side: 39.9 / 2 = 19.95 m.
    # Root chord: ~2.0 m   Tip chord: ~0.9 m   Sweep: ~1.5 m (modest)
    # ------------------------------------------------------------------
    wing_root_chord = 2.0   # m – realistic for RQ-4 class
    wing_tip_chord  = 0.9   # m
    wing_span       = 19.95 # m per side (half-span)
    wing_sweep      = 1.5   # m LE sweep from root to tip
    wing_thickness  = 0.14  # m – thin supercritical aerofoil

    wing = make_fin(wing_root_chord, wing_tip_chord, wing_span,
                    wing_sweep, wing_thickness, skin)

    # Wing root LE at x=0, z=+1.5 (origin at root LE for make_fin)
    # Offset so root sits at x=0 on the fuselage centreline; y=-0.3 (slight
    # anhedral gives low-wing appearance; RQ-4 is actually mid/high but the
    # lathe produces a circular cross-section so we mount at belly tangent).
    wing_z = 1.5    # z of root leading edge
    wing_y = -0.35  # y mount (mid-body height minus half thickness)

    b.add_mesh(wing, offset=(0.0,  wing_y, wing_z))                    # right
    b.add_mesh(wing, rotation=_ROT_MIRROR, offset=(0.0, wing_y, wing_z))  # left

    # ------------------------------------------------------------------
    # V-tail: two fins canted ~35° outward from vertical.
    # Placed at the very tail end of the fuselage.
    # Span (in the plane of each fin): ~3.0 m
    # Root chord: 2.2 m, tip chord: 1.0 m, sweep: 1.6 m
    # ------------------------------------------------------------------
    vtail_root_chord = 2.2
    vtail_tip_chord  = 1.0
    vtail_span       = 3.0
    vtail_sweep      = 1.6
    vtail_thickness  = 0.12

    vtail_fin = make_fin(vtail_root_chord, vtail_tip_chord, vtail_span,
                         vtail_sweep, vtail_thickness, skin)

    # The fin's span is along +X (from make_fin).  We rotate it so the span
    # points upward-and-outward at the cant angle.
    # rot_x(+angle) tips +X toward -Z; we need the fin to go up, so we
    # combine: first stand the fin upright (span along +Y) by rotating -90°
    # about Z, then cant outward by rotating about Z by the cant angle.
    # For the right fin (canted +X):
    #   Rotate fin so span goes upward (+Y direction): rot_z(-pi/2)
    #   Then tilt span outward (away from centreline, i.e., +X for right side):
    #   rot_x angle so top of fin swings to +X:
    #     right fin: rot_x(-cant)  (top leans right)
    # Compose as a single matrix multiplication.
    _upright = rot_z(-math.pi * 0.5)           # span: +X -> +Y
    _cant_right = rot_x(-_VTAIL_CANT_RAD)       # cant fin right
    _cant_left  = rot_x( _VTAIL_CANT_RAD)       # cant fin left

    vtail_rot_right = _cant_right @ _upright
    vtail_rot_left  = _cant_left  @ _upright

    # Root LE mounted at fuselage spine centreline at z ~ -5.5 m, y ~ +0.3 m.
    vtail_z = -5.5
    vtail_y =  0.30

    b.add_mesh(vtail_fin, rotation=vtail_rot_right,
               offset=( 0.0, vtail_y, vtail_z))
    b.add_mesh(vtail_fin, rotation=vtail_rot_left,
               offset=( 0.0, vtail_y, vtail_z))

    # ------------------------------------------------------------------
    # Dorsal engine hump: a rounded box sitting on the fuselage spine.
    # The RQ-4's single Rolls-Royce AE3007 is mounted dorsally with the
    # intake opening just behind the wing root.
    # Hump: ~2.8 m long, 0.9 m wide, 0.55 m tall (above fuselage top).
    # Placed at z ~ 0.0 .. -2.8 (just behind wing root).
    # ------------------------------------------------------------------
    hump_length = 2.8   # along Z
    hump_width  = 0.90
    hump_height = 0.55
    hump_center_z = -0.8
    hump_center_y =  0.56 + hump_height * 0.5   # sit on top of fuselage (~r=0.56)

    b.add_mesh(make_box((hump_width, hump_height, hump_length), skin,
                        offset=(0.0, hump_center_y, hump_center_z)))

    # Intake opening (dark rectangle on the front face of the hump).
    intake_w = 0.60
    intake_h = 0.32
    intake_z = hump_center_z + hump_length * 0.5 + 0.01   # front face
    b.add_mesh(make_box((intake_w, intake_h, 0.08), dark,
                        offset=(0.0, hump_center_y, intake_z)))

    # Exhaust nozzle (dark) at the aft end of the hump.
    exhaust_z = hump_center_z - hump_length * 0.5 - 0.01
    b.add_mesh(make_box((0.46, 0.30, 0.10), dark,
                        offset=(0.0, hump_center_y, exhaust_z)))

    return b.build()
