"""Procedural Nimitz-class aircraft carrier model.

Real scale: 333 m overall length, 76.8 m flight-deck beam (maximum),
~41 m waterline beam (hull).
Model space: forward = +Z (bow at +166.5 m), up = +Y,
origin at the WATERLINE CENTER (y = 0 is the waterline, z = 0 midship).

Key visual signatures reproduced in stylised low-poly:
  - Massive slab hull with flat-topped flight deck.
  - Overhanging ANGLED flight deck (the angled-deck section extends to port,
    offset from the hull centreline — the carrier's most distinctive feature).
  - Island superstructure starboard-aft, with a tall mast.
  - Flight-deck markings: landing threshold stripe (dark green strip).

Multiple Oniks hits needed to sink (high HP): reflected by the sheer
mass of geometry (a very large mesh), but HP is a sim/bases.py concern,
not a model concern.

Draft modelled ~9 m (Nimitz draws ~11.9 m; the ocean hides the rest).
"""

from __future__ import annotations

import math

from engine.meshdata import MeshBuilder, MeshData, make_box, make_cylinder, make_lathe
from models.common import PALETTE, rot_x, rot_y, rot_z, sphere_profile

# ---------------------------------------------------------------------------
# Geometry constants — all real metres, +Z forward
# ---------------------------------------------------------------------------

_LENGTH   = 333.0   # m  overall length
_HALF_L   = 166.5   # m  half length
_HULL_BEAM = 41.0   # m  waterline hull beam
_DECK_BEAM = 76.8   # m  max flight-deck beam (overhanging port)
_DRAFT     =  9.0   # m  modelled draft below waterline
_FREEBOARD =  7.5   # m  hull freeboard above waterline at midship

# Colour aliases
_HULL  = PALETTE["haze_gray"]
_DECK  = PALETTE["haze_gray_deck"]
_SS    = PALETTE["haze_gray_dark"]    # island superstructure
_WHITE = PALETTE["radar_white"]
_MARK  = PALETTE["mil_green_dark"]    # deck markings / runway lines


def _hull_body(b: MeshBuilder) -> float:
    """Add the main hull slab and return deck_y (top of flight deck base)."""
    total_depth = _DRAFT + _FREEBOARD
    half_total = total_depth * 0.5

    # Main rectangular hull box (waterline beam)
    b.add_mesh(make_box(
        (_HULL_BEAM, total_depth, _LENGTH), _HULL,
        offset=(0.0, (_FREEBOARD - _DRAFT) * 0.5, 0.0),
    ))

    # Bow bulge: taper the forward 30 m slightly with a smaller box on top
    # (clipper-style: just a wedge box sticking above the main hull forward)
    bow_taper_z = _HALF_L - 15.0   # start of bow taper
    b.add_mesh(make_box(
        (_HULL_BEAM - 4.0, _FREEBOARD * 0.6, 30.0), _HULL,
        offset=(0.0, _FREEBOARD * 0.7, bow_taper_z + 15.0 - _HALF_L + _HALF_L),
    ))

    deck_y = _FREEBOARD + 0.5   # top of hull + deck plate thickness
    return deck_y


def _flight_deck(b: MeshBuilder, deck_y: float) -> None:
    """Flat flight deck slab spanning the full hull length.

    The deck overhangs port (−X) by ~18 m beyond the hull beam,
    and starboard (+X) by ~9 m, giving the 76.8 m total beam.
    The slab is offset slightly to port relative to hull centreline.
    """
    # Full deck plate at the flight deck level
    b.add_mesh(make_box(
        (_DECK_BEAM, 0.6, _LENGTH), _DECK,
        offset=(-(_DECK_BEAM * 0.5 - _HULL_BEAM * 0.5 - 9.0),
                deck_y + 0.3,
                0.0),
    ))


def _angled_deck(b: MeshBuilder, deck_y: float) -> None:
    """The angled-deck landing area: a second deck plate offset to port and
    rotated ~9 degrees relative to the ship's axis.

    This is the most iconic carrier feature. The angled deck runs from about
    z = −40 m (aft) to z = +80 m (forward of amidships), offset to port.
    """
    # Angled deck: approximately 250 m long, 28 m wide, angled ~9 deg to port.
    angle_rad = math.radians(9.0)

    # We represent it as a slightly wider, thinner box rotated about Y axis
    # (rotation in the horizontal plane) and offset to port.
    rot = rot_y(-angle_rad)   # −angle rotates +Z toward −X (port sweep)

    b.add_mesh(
        make_box((28.0, 0.3, 250.0), _DECK),
        rotation=rot,
        offset=(-12.0, deck_y + 0.62, 0.0),
    )

    # Landing threshold stripe (dark green band at the aft end of angle deck)
    b.add_mesh(
        make_box((28.0, 0.35, 8.0), _MARK),
        rotation=rot,
        offset=(-12.0, deck_y + 0.64, -85.0),
    )


def _island(b: MeshBuilder, deck_y: float) -> None:
    """Island superstructure: starboard side, about z = −20 to +20 m of centre.

    Three stacked blocks + a prominent mast + radar rotodome.
    The island sits on the starboard edge of the flight deck.
    """
    # Island x offset: starboard edge of flight deck ≈ _HULL_BEAM/2 + 9 m
    # minus the island width ≈ 18 m → island centre at about +28 m from CL
    island_x = 28.0   # starboard centre of island
    island_z = -10.0  # z centre (slightly aft of midship)

    # Primary island block
    blk1_h = 12.0
    b.add_mesh(make_box(
        (18.0, blk1_h, 60.0), _SS,
        offset=(island_x, deck_y + blk1_h * 0.5, island_z),
    ))

    # Secondary level (narrower, taller)
    blk2_h = 8.0
    b.add_mesh(make_box(
        (14.0, blk2_h, 40.0), _SS,
        offset=(island_x, deck_y + blk1_h + blk2_h * 0.5, island_z),
    ))

    # Mast column above the island
    mast_base_y = deck_y + blk1_h + blk2_h
    mast_h = 30.0
    b.add_mesh(make_cylinder(0.6, mast_h, 12, _SS, axis="y",
                             offset=(island_x, mast_base_y + mast_h * 0.5,
                                     island_z)))

    # Radar/antenna arm
    b.add_mesh(make_cylinder(0.2, 14.0, 8, _SS, axis="x",
                             offset=(island_x, mast_base_y + mast_h * 0.80,
                                     island_z)))

    # Radar ball at mast top
    b.add_mesh(
        make_lathe(sphere_profile(1.2, bands=8), 16, _WHITE),
        offset=(island_x, mast_base_y + mast_h + 1.2, island_z),
    )


def _sponsons(b: MeshBuilder, deck_y: float) -> None:
    """Sponson pods fore and aft for CIWS and weapons mounts (simplified boxes)."""
    # Forward sponson — port side
    b.add_mesh(make_box(
        (6.0, 1.0, 14.0), _SS,
        offset=(-(_HULL_BEAM * 0.5 + 3.0), deck_y + 0.5, 140.0),
    ))
    # Aft sponson — starboard side
    b.add_mesh(make_box(
        (6.0, 1.0, 14.0), _SS,
        offset=((_HULL_BEAM * 0.5 + 3.0), deck_y + 0.5, -140.0),
    ))


def build_carrier() -> MeshData:
    """Nimitz-class CVN: 333 m × 76.8 m flight deck, haze-gray.

    Signature: overhanging angled flight deck, starboard island with tall mast.
    Waterline origin (y = 0 at waterline, z = 0 at midship).
    """
    b = MeshBuilder()

    deck_y = _hull_body(b)

    # Main flight deck slab
    _flight_deck(b, deck_y)

    # Angled landing deck (the carrier's most distinctive feature)
    _angled_deck(b, deck_y)

    # Island superstructure with mast (starboard aft)
    _island(b, deck_y)

    # Sponsons
    _sponsons(b, deck_y)

    return b.build()
