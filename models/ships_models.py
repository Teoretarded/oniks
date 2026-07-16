"""Procedural surface-ship models.

All dimensions are metres.  Model space is shared with ``sim.ships``:
forward = +Z, up = +Y, starboard = +X, and the origin is the waterline at
midships.  The meshes deliberately keep only a shallow underwater body because
the ocean is opaque, but their visible length and beam match the simulation.

Reference silhouettes used for this pass:

* cargo: Briese Wenchong II 1900 feeder (172 x 27.5 m; adapted to the game's
  existing 180 x 28 m merchant collider), including its four-hold/eight-hatch
  deck plan;
* tanker: a conventional double-hull Aframax crude carrier.  The former model
  mixed an oil tanker's pipe deck with two LNG spheres; this one stays a tanker;
* warship: the 150 x 19 m game hull is styled after the 151 x 19.7 m
  Constellation-class frigate;
* transport: a compacted San Antonio-class LPD silhouette on the game's
  existing 200 x 32 m transport collider;
* LCAC: the game's 27 x 14 m collider, very close to the US Navy's
  28 x 14.7 m legacy LCAC.

Pure numpy / GL-free.
"""

from __future__ import annotations

import math

import numpy as np

from engine.meshdata import (MeshBuilder, MeshData, make_box, make_cylinder,
                             make_wedge)
from models.common import PALETTE, rot_x, rot_y, rot_z

_DRAFT = 2.0


# ---------------------------------------------------------------------------
# Shared hull/detail helpers
# ---------------------------------------------------------------------------

def _vee(beam: float, height: float, length: float, color) -> MeshData:
    """Pointed, flared bow prism with its aft face at local z=0."""
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
    """Box-transom hull with a two-level raked, pointed bow."""
    if bow_top is None:
        bow_top = freeboard
    half_l = length * 0.5
    base_z = half_l - bow_len
    depth = _DRAFT + freeboard
    b.add_mesh(make_box((beam, depth, base_z + half_l), color,
                        offset=(0.0, (freeboard - _DRAFT) * 0.5,
                                (base_z - half_l) * 0.5)))
    b.add_mesh(_vee(beam, split + _DRAFT, bow_len - rake, color),
               offset=(0.0, -_DRAFT, base_z))
    b.add_mesh(_vee(beam, bow_top - split, bow_len, color),
               offset=(0.0, split, base_z))


def _castle(b: MeshBuilder, z: float, deck_y: float, width: float,
            height: float, depth_z: float, wing_w: float,
            *, color=None) -> float:
    """Aft merchant accommodation/bridge block; return its roof height."""
    white = color or PALETTE["tank_white"]
    dark = PALETTE["radome"]
    b.add_mesh(make_box((width, height, depth_z), white,
                        offset=(0.0, deck_y + height * 0.5, z)))
    top = deck_y + height
    b.add_mesh(make_box((wing_w, 2.5, depth_z * 0.72), white,
                        offset=(0.0, top + 1.25, z + 1.0)))
    # Bridge windows are split into panes, which reads much better from 45 deg.
    pane_w = (wing_w - 2.0) / 7.0
    for i in range(7):
        x = -0.5 * (wing_w - 2.0) + pane_w * (i + 0.5)
        b.add_mesh(make_box((pane_w * 0.78, 0.85, 0.24), dark,
                            offset=(x, top + 1.45,
                                    z + 1.0 + depth_z * 0.36)))
    return top + 2.5


def _funnel(b: MeshBuilder, x: float, z: float, y0: float, height: float,
            color, radius: float = 1.6) -> None:
    b.add_mesh(make_cylinder(radius, height, 16, color, axis="y",
                             offset=(x, y0 + height * 0.5, z)))
    b.add_mesh(make_cylinder(radius + 0.08, 0.55, 16, PALETTE["radome"],
                             axis="y", offset=(x, y0 + height - 0.15, z)))


def _helipad_mark(b: MeshBuilder, y: float, z: float, radius: float,
                  color=None) -> None:
    """Eight small tangent bars forming a cheap, readable landing circle."""
    c = color or PALETTE["radar_white"]
    for k in range(8):
        a = 2.0 * math.pi * k / 8.0
        b.add_mesh(make_box((0.35, 0.08, radius * 0.72), c),
                   rotation=rot_y(-a),
                   offset=(math.sin(a) * radius, y,
                           z + math.cos(a) * radius))
    # H bars
    b.add_mesh(make_box((radius * 0.85, 0.09, 0.28), c),
               offset=(0.0, y + 0.01, z))
    for x in (-radius * 0.42, radius * 0.42):
        b.add_mesh(make_box((0.25, 0.09, radius * 0.9), c),
                   offset=(x, y + 0.01, z))


def _vls_cells(b: MeshBuilder, z: float, y: float, blocks: int = 1,
               *, block_spacing: float = 5.0) -> None:
    """Visible 4x8 hatch pattern; one block is a 32-cell Mk 41 group."""
    dark = PALETTE["aircraft_dark"]
    centers = [0.0] if blocks == 1 else [
        (i - (blocks - 1) * 0.5) * block_spacing for i in range(blocks)]
    for cx in centers:
        for ix in range(4):
            for iz in range(8):
                x = cx + (ix - 1.5) * 1.05
                zz = z + (iz - 3.5) * 0.92
                b.add_mesh(make_box((0.82, 0.16, 0.70), dark,
                                    offset=(x, y, zz)))


# ---------------------------------------------------------------------------
# Container feeder
# ---------------------------------------------------------------------------

def build_cargo() -> MeshData:
    """180 x 28 m container feeder with correctly scaled visible box rows."""
    length, beam, free = 180.0, 28.0, 6.0
    deck_top = free + 0.26
    hull_c = PALETTE["cargo_hull"]
    b = MeshBuilder()
    _hull(b, length, beam, free, bow_len=22.0, rake=8.0, split=2.0,
          color=hull_c, bow_top=7.0)

    # Main weather deck + raised forecastle.  The thin dark coaming exposes the
    # hold/bay rhythm from overhead instead of reading as one flat slab.
    b.add_mesh(make_box((beam - 1.4, 0.45, 151.0), PALETTE["cargo_deck"],
                        offset=(0.0, free, -12.5)))
    b.add_mesh(make_box((beam - 3.0, 0.45, 25.0), PALETTE["cargo_deck"],
                        offset=(0.0, 7.0, 67.0)))

    # Nine bays, nine visible rows across, 2-4 tiers.  Individual ISO-like
    # boxes retain seams and believable scale while staying comfortably low-poly.
    cont = ("container_a", "container_b", "container_c")
    bay_z = np.linspace(-50.0, 48.0, 9)
    tiers = (3, 4, 4, 4, 3, 4, 3, 3, 2)  # visibility wedge toward the bow
    for ib, zc in enumerate(bay_z):
        for col in range(9):
            xc = (col - 4) * 2.55
            # Break a few upper corners so the load looks operational, not a cube.
            nt = tiers[ib] - (1 if (ib + col) % 7 == 0 else 0)
            for tier in range(max(1, nt)):
                key = cont[(ib * 5 + col * 3 + tier) % len(cont)]
                b.add_mesh(make_box((2.34, 2.35, 10.7), PALETTE[key],
                                    offset=(xc,
                                            deck_top + 1.18 + 2.42 * tier,
                                            float(zc))))

    roof_y = _castle(b, z=-78.0, deck_y=deck_top, width=19.0,
                     height=10.5, depth_z=14.0, wing_w=24.0)
    _funnel(b, 0.0, -82.0, roof_y - 0.4, 3.0, hull_c, radius=1.55)

    # Lifeboats, forward mast, anchors and mooring winches are small but strong
    # recognition cues at oblique angles.
    for x in (-11.1, 11.1):
        b.add_mesh(make_cylinder(0.75, 4.2, 10, PALETTE["container_c"],
                                 axis="z", offset=(x, 12.4, -76.0)))
    mast_y = 7.2
    b.add_mesh(make_cylinder(0.18, 7.0, 8, PALETTE["pipe"], axis="y",
                             offset=(0.0, mast_y + 3.5, 71.0)))
    b.add_mesh(make_cylinder(0.12, 8.0, 8, PALETTE["pipe"], axis="x",
                             offset=(0.0, mast_y + 6.2, 71.0)))
    for x in (-7.5, 7.5):
        b.add_mesh(make_cylinder(0.65, 0.35, 12, PALETTE["radome"], axis="z",
                                 offset=(x, 3.0, 87.7)))
    return b.build()


# ---------------------------------------------------------------------------
# Aframax crude tanker
# ---------------------------------------------------------------------------

def build_tanker() -> MeshData:
    """240 x 40 m conventional Aframax tanker with a real pipe/tank deck."""
    length, beam, free = 240.0, 40.0, 5.5
    deck_top = free + 0.26
    hull_c = PALETTE["tanker_hull"]
    deck_c = PALETTE["tanker_deck"]
    pipe_c = PALETTE["pipe"]
    b = MeshBuilder()
    _hull(b, length, beam, free, bow_len=27.0, rake=9.0, split=1.6,
          color=hull_c, bow_top=6.5)
    b.add_mesh(make_box((beam - 1.8, 0.5, 204.0), deck_c,
                        offset=(0.0, free, -8.0)))

    # Six longitudinal stations x port/starboard = twelve cargo tanks.  Low
    # hatch covers, vent risers and transverse headers communicate oil tanker;
    # there are deliberately no LNG/Moss spheres.
    stations = (-61.0, -33.0, -5.0, 23.0, 51.0, 79.0)
    for iz, zz in enumerate(stations):
        for x in (-9.0, 9.0):
            b.add_mesh(make_box((7.0, 0.32, 10.0), PALETTE["warship_deck"],
                                offset=(x, deck_top + 0.16, zz)))
            b.add_mesh(make_cylinder(0.42, 1.0, 10, pipe_c, axis="y",
                                     offset=(x, deck_top + 0.75, zz)))
        b.add_mesh(make_cylinder(0.32, 28.0, 10, pipe_c, axis="x",
                                 offset=(0.0, deck_top + 0.65, zz)))

    # Longitudinal cargo lines and elevated centre catwalk.
    for x in (-5.0, 0.0, 5.0):
        b.add_mesh(make_cylinder(0.38, 166.0, 12, pipe_c, axis="z",
                                 offset=(x, deck_top + 0.62, 12.0)))
    walk_y = deck_top + 2.75
    b.add_mesh(make_box((2.2, 0.22, 171.0), PALETTE["cargo_deck"],
                        offset=(0.0, walk_y, 9.0)))
    for zz in np.linspace(-70.0, 88.0, 9):
        for x in (-1.4, 1.4):
            b.add_mesh(make_box((0.18, 2.7, 0.18), PALETTE["cargo_deck"],
                                offset=(x, deck_top + 1.35, float(zz))))

    # Amidships manifold platform and hose-handling cranes.
    b.add_mesh(make_box((31.0, 0.4, 10.0), PALETTE["cargo_deck"],
                        offset=(0.0, deck_top + 1.0, 2.0)))
    for x in (-16.0, 16.0):
        b.add_mesh(make_cylinder(0.22, 7.0, 8, pipe_c, axis="y",
                                 offset=(x, deck_top + 3.5, 2.0)))
        b.add_mesh(make_cylinder(0.14, 6.0, 8, pipe_c, axis="x",
                                 offset=(x - math.copysign(2.5, x),
                                         deck_top + 6.7, 2.0)))

    roof_y = _castle(b, z=-107.0, deck_y=deck_top, width=25.0,
                     height=8.5, depth_z=15.0, wing_w=31.0)
    _funnel(b, 0.0, -111.0, roof_y - 0.5, 3.2, deck_c, radius=2.0)
    for x in (-16.0, 16.0):
        b.add_mesh(make_cylinder(0.82, 4.8, 10, PALETTE["container_c"],
                                 axis="z", offset=(x, 12.5, -103.0)))

    # Foremast and bow mooring machinery.
    b.add_mesh(make_cylinder(0.20, 9.0, 8, pipe_c, axis="y",
                             offset=(0.0, deck_top + 4.5, 96.0)))
    b.add_mesh(make_cylinder(0.12, 10.0, 8, pipe_c, axis="x",
                             offset=(0.0, deck_top + 8.0, 96.0)))
    for x in (-8.0, 8.0):
        b.add_mesh(make_cylinder(0.8, 0.4, 12, PALETTE["radome"], axis="y",
                                 offset=(x, deck_top + 0.45, 105.0)))
    return b.build()


# ---------------------------------------------------------------------------
# Constellation-inspired frigate
# ---------------------------------------------------------------------------

def build_warship() -> MeshData:
    """150 x 19 m modern frigate with VLS, NSM, integrated mast and hangar."""
    length, beam, free = 150.0, 19.0, 6.0
    hull_c = PALETTE["warship_hull"]
    deck_c = PALETTE["warship_deck"]
    ss = PALETTE["superstructure"]
    dark = PALETTE["aircraft_dark"]
    b = MeshBuilder()
    _hull(b, length, beam, free, bow_len=29.0, rake=9.0, split=1.5,
          color=hull_c, bow_top=7.4)
    b.add_mesh(make_box((17.4, 0.4, 116.0), deck_c,
                        offset=(0.0, free, -16.5)))
    deck_y = free + 0.22

    # Mk 110 57 mm and 32-cell Mk 41 field.
    b.add_mesh(make_cylinder(1.9, 1.1, 14, ss, axis="y",
                             offset=(0.0, deck_y + 0.55, 57.0)))
    b.add_mesh(make_wedge((3.5, 2.0, 4.5), ss),
               rotation=rot_x(math.pi), offset=(0.0, deck_y + 1.9, 57.0))
    b.add_mesh(make_cylinder(0.18, 7.0, 8, dark, axis="z"),
               rotation=rot_x(-math.radians(6.0)),
               offset=(0.0, deck_y + 2.7, 60.5))
    _vls_cells(b, z=39.0, y=deck_y + 0.16, blocks=1)

    # Low-observable forward house, bridge, and an integrated EASR mast.
    b.add_mesh(make_box((13.0, 5.0, 31.0), ss,
                        offset=(0.0, deck_y + 2.5, 16.0)))
    b.add_mesh(make_box((10.5, 4.0, 19.0), ss,
                        offset=(0.0, deck_y + 7.0, 19.0)))
    for x in np.linspace(-4.2, 4.2, 6):
        b.add_mesh(make_box((1.05, 0.75, 0.22), PALETTE["radome"],
                            offset=(float(x), deck_y + 8.2, 28.4)))
    mast_base = deck_y + 9.0
    b.add_mesh(make_box((5.2, 8.0, 5.2), ss,
                        offset=(0.0, mast_base + 4.0, 10.0)))
    # Three dark EASR faces around the integrated mast.
    for a in (0.0, 2.0 * math.pi / 3.0, -2.0 * math.pi / 3.0):
        b.add_mesh(make_box((3.0, 2.7, 0.18), dark), rotation=rot_y(a),
                   offset=(math.sin(a) * 2.7,
                           mast_base + 4.7,
                           10.0 + math.cos(a) * 2.7))
    b.add_mesh(make_cylinder(0.22, 5.0, 8, ss, axis="y",
                             offset=(0.0, mast_base + 10.5, 10.0)))
    b.add_mesh(make_cylinder(0.12, 7.0, 8, ss, axis="x",
                             offset=(0.0, mast_base + 12.2, 10.0)))

    # Funnel and two eight-round NSM banks amidships.
    b.add_mesh(make_box((5.0, 4.2, 7.0), ss),
               rotation=rot_x(math.radians(6.0)),
               offset=(0.0, deck_y + 7.1, -2.0))
    b.add_mesh(make_box((4.5, 0.6, 6.4), PALETTE["radome"],
                        offset=(0.0, deck_y + 9.2, -2.4)))
    for side in (-1.0, 1.0):
        for row in range(2):
            for col in range(4):
                b.add_mesh(make_box((0.62, 0.62, 4.2), dark),
                           rotation=rot_x(-math.radians(12.0)),
                           offset=(side * (3.8 + row * 0.85),
                                   deck_y + 1.4 + row * 0.72,
                                   -10.0 + (col - 1.5) * 1.0))

    # Twin-helo-sized hangar volume, dark doors, RHIB recesses and flight deck.
    b.add_mesh(make_box((13.0, 5.2, 25.0), ss,
                        offset=(0.0, deck_y + 2.6, -31.5)))
    for x in (-3.2, 3.2):
        b.add_mesh(make_box((5.2, 3.6, 0.22), dark,
                            offset=(x, deck_y + 2.1, -44.1)))
    for x in (-8.55, 8.55):
        b.add_mesh(make_box((0.25, 2.2, 9.0), PALETTE["radome"],
                            offset=(x, deck_y + 1.5, -15.0)))
    b.add_mesh(make_box((17.0, 0.38, 29.0), PALETTE["warship_deck"],
                        offset=(0.0, deck_y + 0.18, -59.7)))
    _helipad_mark(b, deck_y + 0.42, -60.0, 6.0)

    # Mk 49 RAM on the hangar roof.
    b.add_mesh(make_cylinder(0.75, 0.8, 12, ss, axis="y",
                             offset=(0.0, deck_y + 5.6, -37.0)))
    b.add_mesh(make_box((2.0, 1.4, 2.2), dark,
                        offset=(0.0, deck_y + 6.6, -37.0)))
    return b.build()


# ---------------------------------------------------------------------------
# San Antonio-inspired amphibious transport dock
# ---------------------------------------------------------------------------

def build_transport() -> MeshData:
    """Dedicated 200 x 32 m LPD mesh matching ``SHIP_TYPES['transport']``."""
    length, beam, free = 200.0, 32.0, 7.0
    hull_c = PALETTE["haze_gray"]
    ss = PALETTE["haze_gray_dark"]
    deck_c = PALETTE["haze_gray_deck"]
    dark = PALETTE["aircraft_dark"]
    b = MeshBuilder()
    _hull(b, length, beam, free, bow_len=34.0, rake=10.0, split=2.0,
          color=hull_c, bow_top=9.0)
    deck_y = free + 0.25
    b.add_mesh(make_box((29.5, 0.45, 161.0), deck_c,
                        offset=(0.0, free, -17.5)))

    # Tall faceted mission/accommodation block forward of the hangar.
    b.add_mesh(make_box((25.0, 10.0, 58.0), ss,
                        offset=(0.0, deck_y + 5.0, 28.0)))
    b.add_mesh(make_box((20.0, 6.0, 35.0), ss,
                        offset=(0.0, deck_y + 13.0, 34.0)))
    for x in np.linspace(-8.2, 8.2, 7):
        b.add_mesh(make_box((1.25, 0.9, 0.24), PALETTE["radome"],
                            offset=(float(x), deck_y + 14.2, 51.6)))

    # The class-defining pair of enclosed sensor masts.
    for z_mast, h in ((25.0, 9.0), (5.0, 8.0)):
        base_y = deck_y + 16.0
        b.add_mesh(make_cylinder(3.3, h, 8, ss, axis="y", smooth=False,
                                 offset=(0.0, base_y + h * 0.5, z_mast)))
        b.add_mesh(make_cylinder(0.22, 4.0, 8, ss, axis="y",
                                 offset=(0.0, base_y + h + 2.0, z_mast)))
        b.add_mesh(make_cylinder(0.14, 7.0, 8, ss, axis="x",
                                 offset=(0.0, base_y + h + 3.3, z_mast)))

    # Hangar, twin doors and large two-spot stern flight deck.
    b.add_mesh(make_box((25.0, 8.0, 28.0), ss,
                        offset=(0.0, deck_y + 4.0, -21.0)))
    for x in (-6.0, 6.0):
        b.add_mesh(make_box((10.0, 5.5, 0.25), dark,
                            offset=(x, deck_y + 3.2, -35.1)))
    b.add_mesh(make_box((30.0, 0.42, 63.0), PALETTE["warship_deck"],
                        offset=(0.0, deck_y + 0.2, -67.5)))
    _helipad_mark(b, deck_y + 0.45, -52.0, 7.0)
    _helipad_mark(b, deck_y + 0.45, -80.0, 7.0)

    # Stern well-deck gate is the amphibious silhouette cue missing from the
    # old cargo proxy.  The dark inset is kept just inside the exact length.
    b.add_mesh(make_box((19.0, 5.2, 0.32), dark,
                        offset=(0.0, 2.7, -99.8)))
    b.add_mesh(make_box((21.0, 0.45, 9.0), deck_c),
               rotation=rot_x(math.radians(6.0)),
               offset=(0.0, 1.0, -94.5))

    # Small RAM/30-mm mounts at opposite corners; the transport remains
    # visually distinct from a destroyer because it has no VLS or SPY house.
    for x, z in ((-11.8, 64.0), (11.8, -33.0)):
        b.add_mesh(make_cylinder(0.7, 0.8, 12, ss, axis="y",
                                 offset=(x, deck_y + 0.4, z)))
        b.add_mesh(make_box((1.6, 1.2, 1.8), dark,
                            offset=(x, deck_y + 1.35, z)))
    return b.build()


# ---------------------------------------------------------------------------
# Landing Craft Air Cushion
# ---------------------------------------------------------------------------

def build_lcac() -> MeshData:
    """Dedicated 27 x 14 m LCAC with skirt, cargo lane and twin propulsors."""
    length = 27.0
    skirt = PALETTE["tire"]
    deck = PALETTE["cargo_deck"]
    metal = PALETTE["superstructure"]
    dark = PALETTE["aircraft_dark"]
    b = MeshBuilder()

    # Fabric skirt as a four-piece perimeter, leaving the centre visually open.
    for x in (-6.3, 6.3):
        b.add_mesh(make_box((1.4, 1.25, length), skirt,
                            offset=(x, 0.62, 0.0)))
    for z in (-12.8, 12.8):
        b.add_mesh(make_box((11.2, 1.25, 1.4), skirt,
                            offset=(0.0, 0.62, z)))
    b.add_mesh(make_box((11.1, 0.35, 23.0), deck,
                        offset=(0.0, 1.34, 0.0)))

    # Clear central cargo lane with bow/stern ramps and yellow guide stripes.
    for z in (-11.6, 11.6):
        b.add_mesh(make_box((7.2, 0.30, 2.2), metal,
                            offset=(0.0, 1.25, z)))
    for x in (-3.35, 3.35):
        b.add_mesh(make_box((0.18, 0.08, 20.0), PALETTE["container_c"],
                            offset=(x, 1.58, 0.0)))

    # Machinery sponsons and starboard control cabin.
    for x in (-5.0, 5.0):
        b.add_mesh(make_box((2.3, 1.6, 18.5), metal,
                            offset=(x, 2.05, -0.5)))
    b.add_mesh(make_box((2.8, 1.55, 5.2), PALETTE["radar_white"],
                        offset=(4.8, 3.12, 5.5)))
    b.add_mesh(make_box((2.45, 0.55, 0.18), PALETTE["radome"],
                        offset=(4.8, 3.28, 8.12)))

    # Four lift-fan housings read clearly from above.
    for x in (-4.8, 4.8):
        for z in (-3.5, 2.5):
            b.add_mesh(make_cylinder(0.95, 0.24, 14, dark, axis="y",
                                     offset=(x, 2.98, z)))

    # Twin aft shrouded propellers and crossed blades.  Their tops stay at the
    # sim's existing 4 m height, avoiding another visual/collider mismatch.
    for x in (-4.5, 4.5):
        b.add_mesh(make_cylinder(1.35, 0.42, 18, dark, axis="z",
                                 offset=(x, 2.58, -9.8)))
        b.add_mesh(make_box((2.25, 0.14, 0.14), PALETTE["pipe"]),
                   rotation=rot_z(math.radians(35.0)),
                   offset=(x, 2.58, -10.04))
        b.add_mesh(make_box((2.25, 0.14, 0.14), PALETTE["pipe"]),
                   rotation=rot_z(math.radians(-55.0)),
                   offset=(x, 2.58, -10.06))
        # Paired rudder slab behind each shroud.
        b.add_mesh(make_box((0.18, 2.2, 0.30), metal,
                            offset=(x, 2.55, -10.35)))

    # Navigation mast + two weapon pintles.
    b.add_mesh(make_cylinder(0.10, 1.1, 8, metal, axis="y",
                             offset=(4.8, 4.05, 5.5)))
    b.add_mesh(make_cylinder(0.08, 2.2, 8, metal, axis="x",
                             offset=(4.8, 4.4, 5.5)))
    for x in (-5.8, 5.8):
        b.add_mesh(make_cylinder(0.20, 0.45, 8, dark, axis="y",
                                 offset=(x, 3.05, 8.5)))
    return b.build()
