"""Procedural Arleigh Burke-class destroyer model.

Real scale: 155 m overall length, 20 m beam (Flight IIA hull).
Model space: forward = +Z (bow at +77.5 m), up = +Y,
origin at the WATERLINE CENTER (y = 0, z = 0 midship).
Only ~6 m of draft is modelled below the waterline — the ocean
is opaque so the rest never shows.

Key visual signatures reproduced in stylised low-poly:
  - Flared bow with clipper rake, low transom stern.
  - Boxy superstructure with four flat SPY-1D phased-array panels,
    one on each diagonal face of the deckhouse, angled ~20 deg outboard.
  - Single raked lattice-style mast above the deckhouse.
  - Two funnel stacks (fore and aft of amidships).
  - Forward 32-cell Mk 41 VLS field (frames 20-40 m fwd of midship).
  - Aft 64-cell Mk 41 VLS field (frames 10-50 m aft of midship).
  - 5-inch/62 Mk 45 gun turret on the forward forecastle.
  - Two CIWS (Phalanx) mounts: fwd-starboard of bridge, aft-port.

Triangle budget is intentionally comparable to build_warship() — roughly
the same primitive count, not 10x.

Pure numpy / GL-free.
"""

from __future__ import annotations

import math

from engine.meshdata import MeshBuilder, MeshData, make_box, make_cylinder, make_lathe
from models.common import PALETTE, rot_x, rot_y, rot_z, sphere_profile

# Modelled draft (below waterline). Keep small: the ocean hides the rest.
_DRAFT = 6.0

# Colour aliases so the body below stays readable.
_HULL = PALETTE["haze_gray"]
_DECK = PALETTE["haze_gray_deck"]
_SS   = PALETTE["haze_gray_dark"]   # superstructure slightly darker
_WHITE = PALETTE["radar_white"]
_DARK  = PALETTE["radome"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _vee_bow(beam: float, height: float, length: float, color) -> MeshData:
    """Symmetric V-bow block used by ``_hull_body``.

    Two make_wedge halves rotated ±90° about Z give a tapered, flared bow
    face. Origin at the aft face of the vee; the stem is at z = +length.
    """
    b = MeshBuilder()
    from engine.meshdata import make_wedge
    half = make_wedge((height, beam * 0.5, length), color)
    q = beam * 0.25
    b.add_mesh(half, rotation=rot_z(0.5 * math.pi),
               offset=(-q, height * 0.5, length * 0.5))
    b.add_mesh(half, rotation=rot_z(-0.5 * math.pi),
               offset=(q, height * 0.5, length * 0.5))
    return b.build()


def _hull_body(b: MeshBuilder) -> float:
    """Add hull shell to builder; return deck_y (top of main deck)."""
    length = 155.0
    beam   = 20.0
    free   = 7.0     # freeboard at midship (m above waterline)
    bow_len = 28.0   # length of bow vee section
    rake   = 9.0     # lower bow tier cut-back (clipper lean)
    split  = 2.0     # y where lower/upper bow tiers meet

    half_l = length * 0.5        # 77.5
    bow_start_z = half_l - bow_len   # 49.5: where the vee begins

    total_depth = _DRAFT + free

    # Main box hull (keel to main deck, from stern to bow-vee start)
    box_len = bow_start_z + half_l   # 127 m
    b.add_mesh(make_box(
        (beam, total_depth, box_len), _HULL,
        offset=(0.0, (free - _DRAFT) * 0.5, (bow_start_z - half_l) * 0.5),
    ))

    # Lower bow vee (from keel to split, cut back by rake)
    b.add_mesh(_vee_bow(beam, split + _DRAFT, bow_len - rake, _HULL),
               offset=(0.0, -_DRAFT, bow_start_z))

    # Upper bow vee (from split to deck — sheer rises to free + 1.5 m)
    bow_top = free + 1.5
    b.add_mesh(_vee_bow(beam, bow_top - split, bow_len, _HULL),
               offset=(0.0, split, bow_start_z))

    # Transom stern: low, flat — just a thin wedge to square off the tail
    b.add_mesh(make_box(
        (beam - 2.0, total_depth * 0.55, 3.0), _HULL,
        offset=(0.0, (free - _DRAFT) * 0.5 - total_depth * 0.225, -half_l + 1.5),
    ))

    return free + 0.25   # deck_y


def _weather_deck(b: MeshBuilder, deck_y: float) -> None:
    """Flat weather deck plate; a thin hull-coloured bulwark rim stays visible."""
    b.add_mesh(make_box(
        (18.0, 0.35, 153.0), _DECK,
        offset=(0.0, deck_y, -1.0),
    ))


def _vls_field(b: MeshBuilder, z_center: float, cells: int,
               deck_y: float) -> None:
    """Mk 41 VLS cells: individual hatch plates at deck level.

    cells=32 → one 4×8 block; cells=64 → two 4×8 blocks side by side.
    Individual lids retain the signature grid in high-angle renders.
    """
    panel_color = PALETTE["aircraft_dark"]
    block_centers = (0.0,) if cells == 32 else (-2.65, 2.65)
    for bx in block_centers:
        for ix in range(4):
            for iz in range(8):
                x = bx + (ix - 1.5) * 1.02
                z = z_center + (iz - 3.5) * 0.92
                b.add_mesh(make_box(
                    (0.80, 0.18, 0.70), panel_color,
                    offset=(x, deck_y + 0.18, z),
                ))


def _gun_turret(b: MeshBuilder, deck_y: float) -> None:
    """Mk 45 5-inch gun: cylindrical barbette + boxy shield + barrel."""
    z_gun = 62.0  # fwd on forecastle
    barbette_y = deck_y + 0.9
    # barbette drum
    b.add_mesh(make_cylinder(2.2, 1.8, 16, _SS, axis="y",
                             offset=(0.0, barbette_y, z_gun)))
    # gun shield (boxy shroud; READABILITY: scaled up ~1.4x — the stock
    # 3.2 m box vanished at gameplay distance)
    b.add_mesh(make_box(
        (4.4, 2.8, 5.0), PALETTE["haze_gray_dark"],
        offset=(0.0, barbette_y + 1.0 + 1.4, z_gun),
    ))
    # gun barrel: fattened so it exists at distance (same doctrine as the
    # Pantsir gun horns)
    b.add_mesh(
        make_cylinder(0.30, 10.0, 8, PALETTE["haze_gray_dark"], axis="z"),
        rotation=rot_x(-math.radians(5.0)),
        offset=(0.0, barbette_y + 2.9, z_gun + 3.0),
    )


def _superstructure(b: MeshBuilder, deck_y: float) -> None:
    """Multi-level deckhouse with SPY-1D radar panels.

    Three stacked blocks stepping aft-to-fwd, then the four SPY panels
    as thin boxes rotated ~20° on each face of the primary deckhouse block.
    """
    # Block 1 — primary deckhouse (widest, tallest)
    blk1_z   =  10.0
    blk1_h   =   9.0
    blk1_bot = deck_y
    b.add_mesh(make_box(
        (14.0, blk1_h, 28.0), _SS,
        offset=(0.0, blk1_bot + blk1_h * 0.5, blk1_z),
    ))
    # Dark bridge window band across the forward face
    b.add_mesh(make_box(
        (13.5, 1.2, 0.3), _DARK,
        offset=(0.0, blk1_bot + blk1_h - 1.6, blk1_z + 14.0),
    ))

    # Block 2 — upper bridge/combat information centre
    blk2_z   =  12.0
    blk2_bot = blk1_bot + blk1_h
    blk2_h   =   4.5
    b.add_mesh(make_box(
        (11.0, blk2_h, 18.0), _SS,
        offset=(0.0, blk2_bot + blk2_h * 0.5, blk2_z),
    ))

    # Block 3 — flag bridge / upper level
    blk3_bot = blk2_bot + blk2_h
    blk3_h   =   3.0
    b.add_mesh(make_box(
        (9.0, blk3_h, 10.0), _SS,
        offset=(0.0, blk3_bot + blk3_h * 0.5, 14.0),
    ))

    # --- SPY-1D phased-array panels -------------------------------------------
    # Four panels, one per quadrant of the deckhouse, tilted ~20° outboard.
    # Represented as thin flat boxes (0.3 m thick) on the four diagonal faces
    # of the deckhouse at blk1 height.  Each is rotated rot_y(±45°) then
    # rot_x(+20°) so it faces out and slightly up.
    panel_w   = 5.5   # width along face
    panel_h_m = 4.5   # panel height
    panel_t   = 0.25  # thickness
    panel_y   = blk1_bot + blk1_h * 0.55
    panel_z   = blk1_z
    panel_r   = 10.3  # radial offset — MUST clear the deckhouse volume
    #                 (8.0 * sin45 = 5.66 m sat INSIDE the 14 m-wide box: the
    #                  panels were swallowed and invisible — orbit critique)

    spy_color = PALETTE["aircraft_dark"]  # the arrays read DARKER than the
    #                 haze-gray house on the real ship; same tone = invisible
    # The SPY panels on an Arleigh Burke are on the four oblique faces of the
    # octagonal deckhouse.  We place them at ±45° from the ship's axis, tilted
    # 20° from vertical (leaning outboard/upward).
    for sign_x, sign_z in ((1.0, 1.0), (-1.0, 1.0),
                           (-1.0, -1.0), (1.0, -1.0)):
        azimuth = math.atan2(sign_x, sign_z)   # 45°, 135°, -135°, -45°
        # Position: on the deckhouse perimeter at 45° diagonal
        px = sign_x * panel_r * math.sin(math.pi * 0.25)
        pz = panel_z + sign_z * panel_r * math.sin(math.pi * 0.25)
        # Rotation: face outboard (rot_y = azimuth), tilt 20° outboard (rot_x)
        rot = rot_y(azimuth) @ rot_x(math.radians(20.0))
        b.add_mesh(
            make_box((panel_w, panel_h_m, panel_t), spy_color),
            rotation=rot,
            offset=(px, panel_y, pz),
        )


def _mast(b: MeshBuilder, deck_y: float) -> None:
    """Single raked lattice mast: main column + two spreader arms + radar ball."""
    # mast base sits on top of block 3
    # block 3 top = deck_y + 9 + 4.5 + 3 = deck_y + 16.5
    mast_base_y = deck_y + 16.5
    mast_z      = 14.0

    # main column, raked aft 5°
    col_h = 14.0
    b.add_mesh(
        make_cylinder(0.55, col_h, 10, PALETTE["haze_gray_dark"], axis="y"),
        rotation=rot_x(math.radians(5.0)),   # lean aft
        offset=(0.0, mast_base_y + col_h * 0.5, mast_z),
    )
    # cross-spreader arm at mid-height
    arm_y = mast_base_y + col_h * 0.55
    b.add_mesh(make_cylinder(0.12, 8.0, 8, _SS, axis="x",
                             offset=(0.0, arm_y, mast_z)))
    # radar ball / rotating search radar at the top
    b.add_mesh(
        make_lathe(sphere_profile(0.9, bands=8), 14, _WHITE),
        offset=(0.0, mast_base_y + col_h + 0.8, mast_z),
    )


def _stacks(b: MeshBuilder, deck_y: float) -> None:
    """Two funnel stacks, slightly raked aft."""
    ss_top_y = deck_y + 9.0   # top of block 1
    rake = rot_x(math.radians(7.0))

    # Forward stack — between deckhouse blocks 1 and aft VLS
    for z_stack, height in ((3.0, 5.5), (-8.0, 4.5)):
        b.add_mesh(
            make_box((4.0, height, 5.0), _SS),
            rotation=rake,
            offset=(0.0, ss_top_y + height * 0.5, z_stack),
        )
        # dark cap
        b.add_mesh(make_box(
            (3.6, 0.6, 4.4), _DARK,
            offset=(0.0, ss_top_y + height + 0.15, z_stack),
        ))


def _ciws_mount(b: MeshBuilder, x: float, z: float, deck_y: float) -> None:
    """Single Phalanx CIWS: cylindrical base + white spherical dome + barrel."""
    base_y = deck_y + 0.5
    # base drum
    b.add_mesh(make_cylinder(0.6, 1.0, 12, _SS, axis="y",
                             offset=(x, base_y, z)))
    # dome (small sphere lathe)
    dome_r = 0.55
    b.add_mesh(
        make_lathe(sphere_profile(dome_r, bands=7), 12, _WHITE),
        offset=(x, base_y + 1.0 + dome_r, z),
    )
    # short barrel stub
    b.add_mesh(
        make_cylinder(0.08, 1.4, 6, _SS, axis="z"),
        offset=(x, base_y + 1.3, z + dome_r * 0.5),
    )


def _helo_deck(b: MeshBuilder, deck_y: float) -> None:
    """Twin hangar, doors and a stern-contained helicopter landing deck."""
    dark = PALETTE["aircraft_dark"]
    # Hangar aft face is z=-61, leaving a real flight deck before the transom.
    b.add_mesh(make_box(
        (18.0, 6.0, 26.0), _SS,
        offset=(0.0, deck_y + 3.0, -48.0),
    ))
    for x in (-4.4, 4.4):
        b.add_mesh(make_box(
            (7.6, 4.2, 0.22), dark,
            offset=(x, deck_y + 2.35, -61.1),
        ))
    b.add_mesh(make_box(
        (19.0, 0.30, 16.5), PALETTE["warship_deck"],
        offset=(0.0, deck_y + 0.15, -69.2),
    ))

    # Broken circle + H is cheap geometry and makes the stern legible overhead.
    y = deck_y + 0.35
    for k in range(8):
        a = 2.0 * math.pi * k / 8.0
        b.add_mesh(make_box((0.24, 0.08, 2.3), _WHITE),
                   rotation=rot_y(-a),
                   offset=(math.sin(a) * 4.0, y,
                           -69.2 + math.cos(a) * 4.0))
    b.add_mesh(make_box((5.0, 0.08, 0.24), _WHITE,
                        offset=(0.0, y + 0.01, -69.2)))
    for x in (-2.45, 2.45):
        b.add_mesh(make_box((0.22, 0.08, 4.2), _WHITE,
                            offset=(x, y + 0.01, -69.2)))


def _side_details(b: MeshBuilder, deck_y: float) -> None:
    """RHIB recesses, torpedo tubes, anchors and life-raft canisters."""
    dark = PALETTE["radome"]
    for x in (-9.1, 9.1):
        b.add_mesh(make_box((0.24, 2.3, 12.0), dark,
                            offset=(x, deck_y + 1.5, -10.0)))
        for z in (-22.0, -17.0):
            b.add_mesh(make_cylinder(0.20, 2.2, 8, _SS, axis="x"),
                       rotation=rot_z(math.radians(9.0)),
                       offset=(x * 0.92, deck_y + 1.0, z))
        for z in (-33.0, -27.0, 25.0):
            b.add_mesh(make_cylinder(0.28, 1.5, 8, _WHITE, axis="z",
                                     offset=(x * 0.96,
                                             deck_y + 1.25, z)))
    for x in (-5.5, 5.5):
        b.add_mesh(make_cylinder(0.52, 0.22, 12, dark, axis="z",
                                 offset=(x, 4.0, 76.7)))


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def build_destroyer() -> MeshData:
    """Arleigh Burke DDG: 155 m × 20 m, haze-gray, SPY-1D panels, Mk 45 gun,
    two VLS fields, two stacks, single mast, two CIWS mounts.

    Model space: forward = +Z, up = +Y, origin at the waterline center.
    """
    b = MeshBuilder()

    # Hull shell — returns the deck y-coordinate
    deck_y = _hull_body(b)

    # Weather deck plate
    _weather_deck(b, deck_y)

    # Forward 32-cell VLS (Mk 41, frames fwd of bridge)
    _vls_field(b, z_center=40.0, cells=32, deck_y=deck_y)

    # Aft 64-cell VLS (Mk 41), immediately forward of the twin hangars.
    _vls_field(b, z_center=-27.0, cells=64, deck_y=deck_y)

    # 5-inch gun turret on the forecastle
    _gun_turret(b, deck_y)

    # Superstructure with SPY panels
    _superstructure(b, deck_y)

    # Mast
    _mast(b, deck_y)

    # Two stacks (fore and aft of amidships)
    _stacks(b, deck_y)

    # CIWS #1 — forward starboard of bridge
    _ciws_mount(b, x=+6.0, z=27.0, deck_y=deck_y)
    # CIWS #2 — aft port
    _ciws_mount(b, x=-6.0, z=-42.0, deck_y=deck_y)

    _helo_deck(b, deck_y)
    _side_details(b, deck_y)

    return b.build()
