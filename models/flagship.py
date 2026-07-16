"""Procedural Ticonderoga-class guided-missile cruiser flagship.

The model follows the game's 173 x 17 x 33 metre flagship envelope and keeps
the class-defining equipment readable in high-angle audit views: two 61-cell
Mk 41 VLS fields, two lattice masts, four SPY-1 array faces, two Mk 45 guns,
twin helicopter hangars, and a marked stern flight deck.

Primary references:

* U.S. Navy cruiser fact file (567 ft length, 55 ft beam, armament/aircraft):
  https://www.navy.mil/Resources/Fact-Files/Display-FactFiles/Article/2169861/cruisers-cg/
* U.S. Navy Mk 41 fact file (CG 52-73 platform integration):
  https://www.navy.mil/Resources/Fact-Files/Display-FactFiles/Article/2167856/mk-41-vls/
* U.S. Fleet Forces flight-deck photograph:
  https://www.usff.navy.mil/Press-Room/Photo-Gallery/igphoto/2003060952/

Pure numpy / GL-free. Model space: forward = +Z, up = +Y, starboard = +X,
with the origin at the waterline near midships.
"""

from __future__ import annotations

import math

from engine.meshdata import (MeshBuilder, MeshData, make_box, make_cylinder,
                             make_lathe, make_wedge)
from models.common import PALETTE, rot_x, rot_y, rot_z, sphere_profile

_LENGTH = 173.0
_BEAM = 17.0
_DRAFT = 5.0
_DECK_Y = 6.5

_HULL = PALETTE["haze_gray"]
_DECK = PALETTE["haze_gray_deck"]
_HOUSE = PALETTE["haze_gray_dark"]
_DARK = PALETTE["aircraft_dark"]
_WHITE = PALETTE["radar_white"]


def _vee_bow(beam: float, height: float, length: float, color) -> MeshData:
    """Pointed bow prism whose aft face is at local z=0."""

    b = MeshBuilder()
    half = make_wedge((height, beam * 0.5, length), color)
    quarter_beam = beam * 0.25
    b.add_mesh(half, rotation=rot_z(math.pi * 0.5),
               offset=(-quarter_beam, height * 0.5, length * 0.5))
    b.add_mesh(half, rotation=rot_z(-math.pi * 0.5),
               offset=(quarter_beam, height * 0.5, length * 0.5))
    return b.build()


def _add_hull(b: MeshBuilder) -> None:
    """Add a full-scale Spruance-derived hull inside the exact game bounds."""

    half_length = _LENGTH * 0.5
    bow_length = 30.0
    bow_start = half_length - bow_length
    depth = _DRAFT + _DECK_Y

    # Square transom and long fine parallel body.
    body_length = bow_start + half_length
    b.add_mesh(make_box(
        (_BEAM, depth, body_length), _HULL,
        offset=(0.0, (_DECK_Y - _DRAFT) * 0.5,
                (bow_start - half_length) * 0.5),
    ))
    # Two-tier bow gives a pointed waterline and a little forecastle sheer.
    split_y = 1.5
    b.add_mesh(_vee_bow(_BEAM, split_y + _DRAFT, bow_length - 7.0, _HULL),
               offset=(0.0, -_DRAFT, bow_start))
    b.add_mesh(_vee_bow(_BEAM, _DECK_Y - split_y, bow_length, _HULL),
               offset=(0.0, split_y, bow_start))

    b.add_mesh(make_box((16.4, 0.30, 170.0), _DECK,
                        offset=(0.0, _DECK_Y + 0.02, -1.0)))


def _add_vls_field(b: MeshBuilder, z_center: float) -> None:
    """Add one overhead-readable 61-cell Mk 41 launcher field."""

    # An 8 x 8 grid with three omitted service/access positions reads as the
    # cruiser's 61-cell launcher without spending geometry on hidden wells.
    omitted = {(0, 0), (0, 7), (7, 7)}
    for row in range(8):
        for col in range(8):
            if (row, col) in omitted:
                continue
            x = (col - 3.5) * 0.82
            z = z_center + (row - 3.5) * 0.84
            b.add_mesh(make_box(
                (0.66, 0.16, 0.68), _DARK,
                offset=(x, _DECK_Y + 0.22, z),
            ))
    # Pale perimeter makes each launcher bank legible against the deck.
    for x in (-3.55, 3.55):
        b.add_mesh(make_box((0.12, 0.10, 7.2), _WHITE,
                            offset=(x, _DECK_Y + 0.24, z_center)))
    for z in (z_center - 3.55, z_center + 3.55):
        b.add_mesh(make_box((7.2, 0.10, 0.12), _WHITE,
                            offset=(0.0, _DECK_Y + 0.24, z)))


def _add_gun(b: MeshBuilder, z: float, forward: bool) -> None:
    """Mk 45 mount with a low shield and clearly directed barrel."""

    base_y = _DECK_Y + 0.55
    direction = 1.0 if forward else -1.0
    b.add_mesh(make_cylinder(1.65, 1.10, 16, _HOUSE, axis="y",
                             offset=(0.0, base_y, z)))
    b.add_mesh(make_box((3.4, 2.25, 3.8), _HOUSE,
                        offset=(0.0, base_y + 1.5, z)))
    barrel_z = z + direction * 4.6
    b.add_mesh(make_cylinder(0.18, 7.2, 10, _DARK, axis="z"),
               rotation=rot_x(-direction * math.radians(4.0)),
               offset=(0.0, base_y + 2.0, barrel_z))


def _add_bridge_and_arrays(b: MeshBuilder) -> None:
    """Tall cruiser deckhouses, bridge glazing, and four SPY-1 faces."""

    # Forward command block: the tall, slab-sided Ticonderoga signature.
    b.add_mesh(make_box((13.4, 7.6, 27.0), _HOUSE,
                        offset=(0.0, _DECK_Y + 3.8, 27.0)))
    b.add_mesh(make_box((11.2, 3.0, 17.0), _HOUSE,
                        offset=(0.0, _DECK_Y + 9.1, 29.0)))
    # Split bridge panes on the forward face.
    for x in (-4.6, -3.05, -1.52, 0.0, 1.52, 3.05, 4.6):
        b.add_mesh(make_box((1.15, 0.78, 0.22), PALETTE["radome"],
                            offset=(x, _DECK_Y + 9.7, 37.6)))

    # Aft sensor/hangar block. Twin doors are intentionally visible from aft.
    b.add_mesh(make_box((13.2, 7.0, 24.0), _HOUSE,
                        offset=(0.0, _DECK_Y + 3.5, -28.0)))
    b.add_mesh(make_box((10.5, 3.0, 14.0), _HOUSE,
                        offset=(0.0, _DECK_Y + 8.5, -24.5)))
    for x in (-3.25, 3.25):
        b.add_mesh(make_box((5.7, 4.6, 0.24), PALETTE["radome"],
                            offset=(x, _DECK_Y + 2.8, -40.1)))

    # Two arrays per deckhouse, mounted on the port/starboard slab faces.
    # Octagonal end caps read as SPY panels instead of generic dark windows.
    for x_sign in (-1.0, 1.0):
        for z, y in ((25.0, 11.9), (-25.0, 11.4)):
            b.add_mesh(make_cylinder(
                2.05, 0.22, 8, _DARK, axis="x", smooth=False,
                offset=(x_sign * 6.78, y, z),
            ))


def _add_lattice_mast(b: MeshBuilder, z: float, base_y: float,
                      top_y: float, width: float, *, large_array: bool) -> None:
    """Add one compact four-leg lattice mast and its radar furniture."""

    leg_height = top_y - base_y
    for x in (-width * 0.5, width * 0.5):
        for dz in (-1.05, 1.05):
            b.add_mesh(make_cylinder(0.14, leg_height, 8, _HOUSE, axis="y",
                                     offset=(x, base_y + leg_height * 0.5,
                                             z + dz)))

    # Three levels of crossed side bracing keep both masts readable from 360°.
    for level in range(3):
        y = base_y + (level + 0.55) * leg_height / 3.0
        for dz in (-1.05, 1.05):
            for angle in (-31.0, 31.0):
                b.add_mesh(make_box((width + 0.25, 0.13, 0.13), _HOUSE),
                           rotation=rot_z(math.radians(angle)),
                           offset=(0.0, y, z + dz))
        b.add_mesh(make_box((width + 1.8, 0.14, 0.16), _HOUSE,
                            offset=(0.0, y, z)))

    yard_y = top_y - 0.9
    b.add_mesh(make_cylinder(0.10, width + 5.2, 8, _HOUSE, axis="x",
                             offset=(0.0, yard_y, z)))
    b.add_mesh(make_cylinder(0.11, 2.0, 8, _HOUSE, axis="y",
                             offset=(0.0, top_y, z)))
    if large_array:
        # Wide SPS-49-style air-search screen, capped at y=28 m so the whole
        # mesh retains the simulation's 33 m keel-to-mast envelope.
        b.add_mesh(make_box((6.8, 1.8, 0.24), _DARK,
                            offset=(0.0, top_y + 0.3, z)))
    else:
        b.add_mesh(make_lathe(sphere_profile(0.65, bands=7), 12, _WHITE),
                   offset=(0.0, top_y + 0.45, z))


def _add_funnels_and_midships(b: MeshBuilder) -> None:
    """Twin funnels, Harpoon racks, CIWS, boats, and side details."""

    for z in (5.0, -8.0):
        b.add_mesh(make_box((4.6, 7.2, 5.4), _HOUSE),
                   rotation=rot_x(math.radians(5.0)),
                   offset=(0.0, _DECK_Y + 3.8, z))
        b.add_mesh(make_box((4.1, 0.55, 4.8), PALETTE["radome"],
                            offset=(0.0, _DECK_Y + 7.45, z - 0.25)))

    # Four paired Harpoon canister racks angled outboard around midships.
    for x in (-3.3, 3.3):
        for z in (-3.0, 0.0):
            angle = math.radians(14.0 if x > 0.0 else -14.0)
            b.add_mesh(make_box((1.15, 1.0, 4.0), PALETTE["tube_grey"]),
                       rotation=rot_y(angle),
                       offset=(x, _DECK_Y + 1.0, z))

    # Opposed Phalanx mounts.
    for x, z in ((6.5, 10.5), (-6.5, -43.0)):
        b.add_mesh(make_cylinder(0.55, 0.8, 12, _HOUSE, axis="y",
                                 offset=(x, _DECK_Y + 0.5, z)))
        b.add_mesh(make_lathe(sphere_profile(0.52, bands=6), 12, _WHITE),
                   offset=(x, _DECK_Y + 1.55, z))
        b.add_mesh(make_cylinder(0.07, 1.2, 6, _DARK, axis="z",
                                 offset=(x, _DECK_Y + 1.45, z + 0.55)))

    # RHIB recesses and life-raft canisters break up the long slab sides.
    for x in (-8.12, 8.12):
        b.add_mesh(make_box((0.18, 1.8, 10.5), PALETTE["radome"],
                            offset=(x, _DECK_Y + 1.1, -13.0)))
        for z in (-48.0, -16.0, 15.0, 44.0):
            b.add_mesh(make_cylinder(0.23, 1.15, 8, _WHITE, axis="z",
                                     offset=(x * 0.985, _DECK_Y + 1.1, z)))


def _add_helipad(b: MeshBuilder) -> None:
    """Marked stern helicopter deck, readable at 45/70/90 degree elevation."""

    z_center = -76.5
    b.add_mesh(make_box((16.1, 0.24, 18.5), PALETTE["warship_deck"],
                        offset=(0.0, _DECK_Y + 0.16, z_center)))
    y = _DECK_Y + 0.34
    radius = 5.7
    for index in range(12):
        angle = 2.0 * math.pi * index / 12.0
        b.add_mesh(make_box((0.22, 0.08, 1.9), _WHITE),
                   rotation=rot_y(-angle),
                   offset=(math.sin(angle) * radius, y,
                           z_center + math.cos(angle) * radius))
    b.add_mesh(make_box((5.0, 0.09, 0.24), _WHITE,
                        offset=(0.0, y + 0.01, z_center)))
    for x in (-2.4, 2.4):
        b.add_mesh(make_box((0.22, 0.09, 4.8), _WHITE,
                            offset=(x, y + 0.01, z_center)))


def build_flagship() -> MeshData:
    """Return the dedicated 173 m Ticonderoga-style command cruiser mesh."""

    b = MeshBuilder()
    _add_hull(b)
    _add_vls_field(b, 53.5)
    _add_vls_field(b, -50.0)
    _add_gun(b, 72.5, forward=True)
    _add_gun(b, -62.0, forward=False)
    _add_bridge_and_arrays(b)
    _add_funnels_and_midships(b)
    _add_lattice_mast(b, 16.0, 16.0, 26.8, 4.1, large_array=True)
    _add_lattice_mast(b, -24.0, 15.2, 24.4, 3.6, large_array=False)
    _add_helipad(b)
    return b.build()
