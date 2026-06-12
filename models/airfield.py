"""Procedural airfield model.

Real scale:
  - Runway: 2500 m long × 45 m wide × 0.5 m thick (concrete slab).
  - Parallel taxiway: 2500 m × 18 m, offset 80 m to the side.
  - Three hangar buildings (steel-blue roofs, concrete walls).
  - Control tower: narrow base + stepped upper portion.

Model space: forward = +Z (far end of runway at ~+1250 m),
up = +Y, origin at the GROUND CENTER (midpoint of the runway,
y = 0 at ground level).  Consistent with models/structures.py.

Pure numpy, GL-free.
"""

from __future__ import annotations

from engine.meshdata import MeshBuilder, MeshData, make_box, make_cylinder
from models.common import PALETTE

# ---------------------------------------------------------------------------
# Geometry constants — all real metres
# ---------------------------------------------------------------------------

_RUNWAY_LEN = 2500.0   # m  — minimum fighter runway length
_RUNWAY_W   =   45.0   # m
_RUNWAY_H   =    0.5   # m  — slab thickness (sits proud of the terrain)

_TAXI_W     =   18.0   # m  — parallel taxiway width
_TAXI_OFFSET =  80.0   # m  — lateral offset from runway centreline
_TAXI_LEN   = _RUNWAY_LEN

# Colours
_CONC  = PALETTE["concrete"]
_DARK  = PALETTE["aircraft_dark"]   # dark roof / tower glass bands
_ROOF  = PALETTE["container_b"]     # steel-blue hangar roofs (consistent with harbor)
_MARK  = PALETTE["mil_green_dark"]  # runway centreline stripe / taxiway edge lines


def _runway(b: MeshBuilder) -> None:
    """2500 m × 45 m concrete runway slab, centred at origin."""
    b.add_mesh(make_box((_RUNWAY_W, _RUNWAY_H, _RUNWAY_LEN), _CONC,
                        offset=(0.0, _RUNWAY_H * 0.5, 0.0)))
    # Centreline stripe (thin dark strip down the runway)
    b.add_mesh(make_box((1.5, _RUNWAY_H + 0.02, _RUNWAY_LEN), _MARK,
                        offset=(0.0, _RUNWAY_H * 0.5 + 0.01, 0.0)))


def _taxiway(b: MeshBuilder) -> None:
    """Parallel taxiway 80 m to the side of the runway centreline."""
    tx = _TAXI_OFFSET
    b.add_mesh(make_box((_TAXI_W, _RUNWAY_H, _TAXI_LEN), _CONC,
                        offset=(tx, _RUNWAY_H * 0.5, 0.0)))


def _hangars(b: MeshBuilder) -> None:
    """Three hangar buildings along the taxiway side apron.

    Each hangar: 60 m wide, 12 m tall, 40 m deep (along Z), concrete walls,
    steel-blue flat roof.  Hangars are spaced along z = −600, 0, +600 m.
    """
    hx = _TAXI_OFFSET + _TAXI_W * 0.5 + 35.0   # centre of hangar x
    for hz in (-600.0, 0.0, 600.0):
        wall_h = 12.0
        b.add_mesh(make_box((60.0, wall_h, 40.0), _CONC,
                            offset=(hx, wall_h * 0.5, hz)))
        b.add_mesh(make_box((61.0, 0.8, 41.0), _ROOF,
                            offset=(hx, wall_h + 0.4, hz)))


def _tower(b: MeshBuilder) -> None:
    """Air traffic control tower: narrow concrete shaft + glassed cab on top.

    Tower is placed to the side of the taxiway, near the midfield (z = 0).
    Real ATC towers: ~30–50 m tall.  We use 35 m.
    """
    tx = _TAXI_OFFSET + _TAXI_W * 0.5 + 90.0  # further out than hangars
    tz = 200.0                                 # ahead of midfield

    # Concrete shaft (bottom section, narrow)
    b.add_mesh(make_box((4.0, 25.0, 4.0), _CONC,
                        offset=(tx, 12.5, tz)))

    # Upper shaft (slightly wider — access stairs and equipment)
    b.add_mesh(make_box((5.0, 8.0, 5.0), _CONC,
                        offset=(tx, 29.0, tz)))

    # Glazed cab (dark-colored to represent glass): the viewing level on top
    b.add_mesh(make_box((7.0, 3.5, 7.0), _DARK,
                        offset=(tx, 36.75, tz)))

    # Roof slab
    b.add_mesh(make_box((7.5, 0.5, 7.5), _CONC,
                        offset=(tx, 38.75, tz)))

    # Antenna mast on top of tower
    b.add_mesh(make_cylinder(0.15, 8.0, 8, _CONC, axis="y",
                             offset=(tx, 39.0 + 4.0, tz)))


def build_airfield() -> MeshData:
    """Enemy-continent airfield: 2500 m runway + taxiway + 3 hangars + tower.

    Ground-centre origin: y = 0 at ground level, z = 0 at runway midpoint.
    The runway runs from z = −1250 m to z = +1250 m.
    All structures sit above y = 0.
    """
    b = MeshBuilder()
    _runway(b)
    _taxiway(b)
    _hangars(b)
    _tower(b)
    return b.build()
