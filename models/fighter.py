"""Procedural F/A-18E Super Hornet-class fighter model.

Real scale: 18.3 m long, 13.6 m wing span.
Model space: forward = +Z (nose at +z_max), up = +Y,
origin at the center of mass (mid-fuselage). Pure numpy, GL-free.

Key visual signatures reproduced in stylised low-poly:
  - Pointed nose leading to a broad, flat-sided fuselage.
  - Leading-Edge Extension (LEX) strakes from cockpit to wing root —
    the Super Hornet's most recognisable feature when seen from above.
  - Twin-engine nacelles flanking the tail boom.
  - Trapezoidal main wings swept back, positioned mid-fuselage.
  - Twin canted vertical tails (cant ~27 deg outboard) — the
    signature silhouette that distinguishes it from single-tail types.
  - Horizontal stabilators mirrored port/starboard at the tail.
  - Haze-gray paint throughout; dark exhausts.

Density: at most 3× build_fast_aircraft() vertex count as per spec.
"""

from __future__ import annotations

import math

from engine.meshdata import MeshBuilder, MeshData, make_box, make_cylinder, make_fin, make_lathe
from models.common import PALETTE, rot_x, rot_y, rot_z

# ---------------------------------------------------------------------------
# Geometry constants — all in real metres, +Z forward
# ---------------------------------------------------------------------------

# Full length 18.3 m; origin at mid-fuselage (z = 0).
# Nose tip at +9.15 m, tail end at -9.15 m.
_HALF_L = 9.15          # m; half of 18.3 m total length
_HALF_SPAN = 6.8        # m; half of 13.6 m wingspan (tip-to-tip)

# Fuselage profile for make_lathe (z, radius) — circular cross-section
# approximation; the real F/A-18E has a wider, flatter mid-section but the
# lathe gives the right plan-view silhouette and is consistent with
# build_fast_aircraft().
_SEG = 22               # lathe/cylinder segments (GL-quality budget)

_FUSELAGE_PROFILE = [
    (-_HALF_L, 0.0),      # tail end (closed)
    (-7.5, 0.55),
    (-5.0, 0.72),
    (-2.0, 0.82),
    (1.5, 0.85),
    (4.5, 0.80),
    (6.5, 0.62),
    (8.0, 0.40),
    (_HALF_L, 0.0),       # nose tip (closed)
]

_NOSE_CAP = [
    (7.0, 0.42),
    (_HALF_L, 0.0),
]

# Colours
_GREY = PALETTE["aircraft_grey"]
_DARK = PALETTE["aircraft_dark"]
_EXHAUST = PALETTE["exhaust_ring"]

# Rotation helpers
_ROT_MIRROR = rot_z(math.pi)   # flip +X wing to -X wing


def _lex_strake(b: MeshBuilder) -> None:
    """Leading-Edge Extension strakes from ~z=+4 (cockpit) to wing root at z≈+1.

    Each strake is a thin trapezoidal plate (make_fin) mounted port/starboard
    just below the fuselage spine, swept forward.  Root chord ~ 4 m, tip
    chord ~ 1.5 m, span ~ 2.2 m, sweep 2.0 m.
    """
    # make_fin args: (root_chord, tip_chord, span, sweep, thickness, color)
    # span extends in +X; chords along -Z (aft).
    # We place the root leading edge at z = +4.5, x = 0.55 (just off the centreline).
    # READABILITY: plate thicknesses are ~1.7x scale — a 0.12 m plate is
    # invisible edge-on at gameplay distance (the whole planform vanished
    # at level camera elevations; orbit critique 2026-07-03).
    lex = make_fin(4.0, 1.5, 2.2, 2.0, 0.22, _GREY)
    # Starboard (+X side)
    b.add_mesh(lex, offset=(0.55, -0.30, 0.50))
    # Port (-X side): mirror in X using rot_z(π)
    b.add_mesh(lex, rotation=_ROT_MIRROR, offset=(-0.55, -0.30, 0.50))


def _main_wings(b: MeshBuilder) -> None:
    """Trapezoidal main wings, mid-fuselage, moderately swept.

    Root chord 4.5 m, tip chord 1.6 m, semi-span 6.0 m, sweep 2.5 m.
    Wing root leading edge at z ≈ +1.5 m, y ≈ −0.25 m.
    """
    wing = make_fin(4.5, 1.6, 6.0, 2.5, 0.34, _GREY)
    # Starboard
    b.add_mesh(wing, offset=(0.85, -0.25, 1.5))
    # Port
    b.add_mesh(wing, rotation=_ROT_MIRROR, offset=(-0.85, -0.25, 1.5))


def _twin_tails(b: MeshBuilder) -> None:
    """Twin canted vertical stabilisers — the Super Hornet signature.

    Each tail is canted ~27 deg outboard.  make_fin spans in +X (before
    rotation we tilt the whole thing via rot_z).  We use rot_z to rotate
    the fin from its natural +X span direction to a direction canted outboard,
    then offset it to the correct tail position.

    Tail geometry: root chord 3.2 m, tip chord 1.0 m, span 3.0 m, sweep 2.0 m.
    """
    # Cant angle outboard from vertical (27 degrees)
    cant_deg = 27.0
    cant_rad = math.radians(cant_deg)

    # make_fin naturally lies in the XZ plane (span along +X, chord along -Z).
    # We want it to stand upright (span along +Y) and canted outboard.
    # Step 1: rotate span from +X to +Y  →  rot_z(-π/2)
    # Step 2: cant outboard  →  rot_x(+cant_rad) for starboard (tips lean +X)
    rot_upright = rot_z(-0.5 * math.pi)
    rot_cant_stbd = rot_x(cant_rad)        # tips lean toward +X (outboard stbd)
    rot_cant_port = rot_x(-cant_rad)       # tips lean toward -X (outboard port)

    tail_fin = make_fin(3.2, 1.0, 3.0, 2.0, 0.30, _GREY)

    # Starboard: x = +1.0, at the tail end
    b.add_mesh(tail_fin,
               rotation=rot_cant_stbd @ rot_upright,
               offset=(1.00, 0.50, -5.8))
    # Port: symmetric
    b.add_mesh(tail_fin,
               rotation=rot_cant_port @ rot_upright,
               offset=(-1.00, 0.50, -5.8))


def _horizontal_stabs(b: MeshBuilder) -> None:
    """All-moving horizontal stabilators at the extreme tail, below the twin tails.

    Root chord 2.8 m, tip chord 0.9 m, span 3.2 m, sweep 1.8 m.
    """
    stab = make_fin(2.8, 0.9, 3.2, 1.8, 0.26, _GREY)
    b.add_mesh(stab, offset=(0.85, -0.55, -5.0))
    b.add_mesh(stab, rotation=_ROT_MIRROR, offset=(-0.85, -0.55, -5.0))


def _engine_nacelles(b: MeshBuilder) -> None:
    """Twin General Electric F414 engine nacelles flanking the tail boom.

    Each nacelle: a short cylinder with a dark exhaust nozzle ring at the aft end.
    Nacelle length ~4.5 m, radius ~0.55 m, centred at z ≈ −4.5 m, x ≈ ±1.1 m.
    """
    for sx in (1.0, -1.0):
        # Nacelle body
        b.add_mesh(make_cylinder(0.55, 4.5, _SEG, _GREY, axis="z",
                                 offset=(sx * 1.10, -0.20, -4.50)))
        # Dark exhaust nozzle band at the tail end
        b.add_mesh(make_cylinder(0.52, 0.6, _SEG, _EXHAUST, axis="z",
                                 offset=(sx * 1.10, -0.20, -6.60)))


def _cockpit(b: MeshBuilder) -> None:
    """Raised canopy hump at the fuselage spine just ahead of the wing root."""
    b.add_mesh(make_box((1.05, 0.62, 2.30), _DARK,
                        offset=(0.0, 0.95, 3.90)))


def build_fighter() -> MeshData:
    """F/A-18E Super Hornet-class fighter: 18.3 m × 13.6 m span, haze-gray.

    Signature features: LEX strakes, twin canted tails, twin engine nacelles.
    Model space: forward = +Z, up = +Y, origin at mid-fuselage waterline.
    """
    b = MeshBuilder()

    # Main fuselage via surface of revolution
    b.add_mesh(make_lathe(_FUSELAGE_PROFILE, _SEG, _GREY))
    # Dark nose radome/sensor cap
    b.add_mesh(make_lathe(_NOSE_CAP, _SEG, _DARK))

    # LEX strakes — the Super Hornet's primary visual signature
    _lex_strake(b)

    # Main wings
    _main_wings(b)

    # Twin canted vertical tails
    _twin_tails(b)

    # Horizontal stabilators
    _horizontal_stabs(b)

    # Twin engine nacelles
    _engine_nacelles(b)

    # Cockpit canopy
    _cockpit(b)

    return b.build()
