"""Procedural ship models: cargo freighter, tanker, warship.

Real scale (meters). Model space: forward = +Z (bow at +length/2), up = +Y,
origin at the WATERLINE CENTER (y = 0 is the waterline, z = 0 is midship).
Hulls draw only ~2 m of draft — the ocean is opaque, so the missing
underwater body never shows and everything stays above y = -2.

Pure numpy / GL-free (returns ``MeshData``; callers upload via engine.mesh).
"""

from __future__ import annotations

import math

import numpy as np

from engine.meshdata import (MeshBuilder, MeshData, make_box, make_cylinder,
                             make_lathe, make_wedge)
from models.common import PALETTE, rot_x, rot_z, sphere_profile

_DRAFT = 2.0                 # modeled draft (m below waterline) for all hulls


def _vee(beam: float, height: float, length: float, color) -> MeshData:
    """Pointed bow block: full-width vertical back face at z = 0, sharp stem
    edge at z = +length, flat top/bottom (y spans 0..height). Two vertical
    wedges (``make_wedge`` spun ±90° about Z) meeting on the centerline."""
    b = MeshBuilder()
    half = make_wedge((height, beam * 0.5, length), color)
    q = beam * 0.25
    b.add_mesh(half, rotation=rot_z(0.5 * math.pi),
               offset=(-q, height * 0.5, length * 0.5))
    b.add_mesh(half, rotation=rot_z(-0.5 * math.pi),
               offset=(q, height * 0.5, length * 0.5))
    return b.build()


def _hull(b: MeshBuilder, length: float, beam: float, freeboard: float,
          bow_len: float, rake: float, split: float, color,
          bow_top: float | None = None) -> None:
    """Box hull + two-tier pointed bow with a raked stem.

    The upper bow tier runs out to the full +length/2 while the lower tier is
    cut back ``rake`` m, so the stem leans forward going up (clipper rake).
    ``split`` is the model y where the tiers meet; ``bow_top`` lets the fore
    deck rise above ``freeboard`` (warship sheer).
    """
    if bow_top is None:
        bow_top = freeboard
    half_l = length * 0.5
    base_z = half_l - bow_len                    # bow tiers start here
    depth = _DRAFT + freeboard
    b.add_mesh(make_box((beam, depth, base_z + half_l), color,
                        offset=(0.0, (freeboard - _DRAFT) * 0.5,
                                (base_z - half_l) * 0.5)))
    b.add_mesh(_vee(beam, split + _DRAFT, bow_len - rake, color),
               offset=(0.0, -_DRAFT, base_z))
    b.add_mesh(_vee(beam, bow_top - split, bow_len, color),
               offset=(0.0, split, base_z))


def _castle(b: MeshBuilder, z: float, deck_y: float, width: float,
            height: float, depth_z: float, wing_w: float) -> None:
    """White aft bridge castle: main block, wider bridge-wing deck on top,
    dark window band across the wing face (faces forward, +Z)."""
    white = PALETTE["tank_white"]
    dark = PALETTE["radome"]
    b.add_mesh(make_box((width, height, depth_z), white,
                        offset=(0.0, deck_y + height * 0.5, z)))
    top = deck_y + height
    b.add_mesh(make_box((wing_w, 2.3, depth_z * 0.7), white,
                        offset=(0.0, top + 1.15, z + 1.0)))
    b.add_mesh(make_box((wing_w - 1.0, 1.0, 0.3), dark,
                        offset=(0.0, top + 1.15, z + 1.0 + depth_z * 0.35)))


def build_cargo() -> MeshData:
    """180 x 28 m container freighter: rust-red hull, raked bow, 2 rows x 5
    stacks of containers, white bridge castle aft, funnel."""
    length, beam, free = 180.0, 28.0, 6.0
    deck_top = free + 0.25
    hull_c = PALETTE["cargo_hull"]
    b = MeshBuilder()
    _hull(b, length, beam, free, bow_len=22.0, rake=8.0, split=2.0,
          color=hull_c)
    # weather deck plate, inset so a hull-colored bulwark rim shows
    b.add_mesh(make_box((beam - 1.6, 0.5, 152.0), PALETTE["cargo_deck"],
                        offset=(0.0, free, -12.0)))
    # 2 rows x 5 container stacks, alternating colors + varied stack heights
    cont = ("container_a", "container_b", "container_c")
    heights = (8.0, 11.0, 9.0, 11.0, 8.0)
    for i, zc in enumerate((-50.0, -28.0, -6.0, 16.0, 38.0)):
        h = heights[i]
        for j, xc in enumerate((-6.8, 6.8)):
            b.add_mesh(make_box((11.0, h, 17.0), PALETTE[cont[(2 * i + j) % 3]],
                                offset=(xc, deck_top + h * 0.5, zc)))
    _castle(b, z=-78.0, deck_y=deck_top, width=18.0, height=15.0,
            depth_z=10.0, wing_w=24.0)
    # funnel on the castle roof, aft (hull-red with a dark cap)
    b.add_mesh(make_cylinder(1.7, 5.0, 20, hull_c, axis="y",
                             offset=(0.0, deck_top + 15.0 + 2.5, -81.0)))
    b.add_mesh(make_cylinder(1.75, 0.9, 20, PALETTE["radome"], axis="y",
                             offset=(0.0, deck_top + 15.0 + 4.8, -81.0)))
    return b.build()


def build_tanker() -> MeshData:
    """240 x 40 m tanker: black hull, low rust deck with 3 pipe runs and a
    raised center catwalk, white castle aft, 2 spherical LNG domes."""
    length, beam, free = 240.0, 40.0, 5.0
    deck_top = free + 0.25
    hull_c = PALETTE["tanker_hull"]
    b = MeshBuilder()
    _hull(b, length, beam, free, bow_len=26.0, rake=9.0, split=1.5,
          color=hull_c)
    b.add_mesh(make_box((beam - 2.0, 0.5, 204.0), PALETTE["tanker_deck"],
                        offset=(0.0, free, -14.0)))
    # 3 fore-deck pipe runs
    for x in (-4.5, 0.0, 4.5):
        b.add_mesh(make_cylinder(0.5, 130.0, 14, PALETTE["pipe"], axis="z",
                                 offset=(x, deck_top + 0.55, 18.0)))
    # raised center catwalk over the pipes (posts straddle the middle pipe)
    walk_c = PALETTE["cargo_deck"]
    b.add_mesh(make_box((2.6, 0.25, 134.0), walk_c,
                        offset=(0.0, deck_top + 3.0, 16.0)))
    for zz in np.linspace(-44.0, 76.0, 6):
        for sx in (1.8, -1.8):
            b.add_mesh(make_box((0.25, 3.0, 0.25), walk_c,
                                offset=(sx, deck_top + 1.5, float(zz))))
    # 2 spherical-ish gas domes (aft of the pipe runs)
    dome = make_lathe(sphere_profile(7.0), 28, PALETTE["tank_white"])
    for zz in (-62.0, -84.0):
        b.add_mesh(dome, offset=(0.0, free + 1.0, zz))
    _castle(b, z=-107.0, deck_y=deck_top, width=22.0, height=11.0,
            depth_z=10.0, wing_w=28.0)
    # funnel: rust-red with dark cap
    b.add_mesh(make_cylinder(2.1, 5.5, 20, PALETTE["tanker_deck"], axis="y",
                             offset=(0.0, deck_top + 11.0 + 2.75, -110.0)))
    b.add_mesh(make_cylinder(2.16, 1.0, 20, PALETTE["radome"], axis="y",
                             offset=(0.0, deck_top + 11.0 + 5.3, -110.0)))
    return b.build()


def build_warship() -> MeshData:
    """150 x 19 m frigate: haze grey, sheer raked bow with a forecastle
    break, stepped superstructure, mast, gun turret fwd, helo deck aft."""
    length, beam, free = 150.0, 19.0, 6.0
    hull_c = PALETTE["warship_hull"]
    ss = PALETTE["superstructure"]
    dark = PALETTE["radome"]
    b = MeshBuilder()
    # fore deck (bow vee top) rises to 7.5 — sheer line breaks at the vee base
    _hull(b, length, beam, free, bow_len=30.0, rake=10.0, split=1.5,
          color=hull_c, bow_top=7.5)
    b.add_mesh(make_box((17.5, 0.4, 117.0), PALETTE["warship_deck"],
                        offset=(0.0, free, -16.5)))
    deck_y = free + 0.2
    # gun turret on the fore deck + slightly elevated barrel
    b.add_mesh(make_cylinder(2.3, 2.0, 20, ss, axis="y",
                             offset=(0.0, 8.5, 52.0)))
    b.add_mesh(make_cylinder(0.24, 8.0, 10, ss, axis="z"),
               rotation=rot_x(-math.radians(8.0)), offset=(0.0, 9.1, 56.5))
    # VLS block between turret and bridge
    b.add_mesh(make_box((9.0, 0.9, 8.0), ss, offset=(0.0, deck_y + 0.45, 36.0)))
    # stepped superstructure: 3 blocks + dark bridge window band
    b.add_mesh(make_box((13.0, 5.0, 38.0), ss, offset=(0.0, deck_y + 2.5, 8.0)))
    b.add_mesh(make_box((10.5, 4.0, 24.0), ss, offset=(0.0, deck_y + 7.0, 10.0)))
    b.add_mesh(make_box((8.5, 3.2, 9.0), ss, offset=(0.0, deck_y + 10.6, 17.0)))
    b.add_mesh(make_box((8.0, 1.1, 0.3), dark, offset=(0.0, deck_y + 11.0, 21.4)))
    # mast (thin cylinders) + white radar ball
    mast_base = deck_y + 9.0                       # top of block 2
    b.add_mesh(make_cylinder(0.35, 9.0, 12, ss, axis="y",
                             offset=(0.0, mast_base + 4.5, 5.0)))
    b.add_mesh(make_cylinder(0.14, 5.0, 8, ss, axis="x",
                             offset=(0.0, mast_base + 6.8, 5.0)))
    b.add_mesh(make_lathe(sphere_profile(1.0, bands=8), 16,
                          PALETTE["radar_white"]),
               offset=(0.0, mast_base + 9.2, 5.0))
    # angular funnel with dark cap (aft of block 2 on block 1's roof)
    b.add_mesh(make_box((4.5, 3.4, 6.0), ss, offset=(0.0, deck_y + 6.7, -6.0)))
    b.add_mesh(make_box((4.0, 0.6, 5.4), dark, offset=(0.0, deck_y + 8.5, -6.0)))
    # hangar + flat helo deck aft
    b.add_mesh(make_box((11.0, 4.5, 16.0), ss, offset=(0.0, deck_y + 2.25, -27.0)))
    b.add_mesh(make_box((17.0, 0.45, 36.0), PALETTE["mil_green_dark"],
                        offset=(0.0, deck_y + 0.225, -56.0)))
    return b.build()
