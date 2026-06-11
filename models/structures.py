"""Procedural land/coast structure models: radar station, fuel depot, harbor.

Real scale (meters). Model space: forward = +Z, up = +Y, origin at the
GROUND CENTER (y = 0 is the local ground / quay waterline; the harbor's quay
walls reach 1.5 m below it, everything else sits on or above it).

Pure numpy / GL-free (returns ``MeshData``; callers upload via engine.mesh).
"""

from __future__ import annotations

import math

import numpy as np

from engine.meshdata import MeshBuilder, MeshData, make_box, make_cylinder, make_lathe
from models.common import PALETTE, rot_x, sphere_profile


def build_radar_station() -> MeshData:
    """Concrete base slab, two-step tower, white radome ball, crew hut."""
    conc = PALETTE["concrete"]
    b = MeshBuilder()
    b.add_mesh(make_box((12.0, 1.2, 12.0), conc, offset=(0.0, 0.6, 0.0)))
    # tower: two stacked boxes, the upper one narrower (simplified lattice)
    b.add_mesh(make_box((4.5, 7.0, 4.5), conc, offset=(0.0, 1.2 + 3.5, 0.0)))
    b.add_mesh(make_box((3.0, 7.0, 3.0), conc, offset=(0.0, 8.2 + 3.5, 0.0)))
    # radome: white sphere swallowing the tower top
    b.add_mesh(make_lathe(sphere_profile(3.4), 24, PALETTE["radar_white"]),
               offset=(0.0, 17.4, 0.0))
    # crew hut beside the slab, dark flat roof
    b.add_mesh(make_box((5.0, 3.0, 4.0), conc, offset=(9.0, 1.5, 1.0)))
    b.add_mesh(make_box((5.4, 0.4, 4.4), PALETTE["mil_green_dark"],
                        offset=(9.0, 3.1, 1.0)))
    return b.build()


def build_fuel_depot() -> MeshData:
    """6 white storage tanks (r 8, h 12, domed tops) in 2 rows, central
    manifold pipes, per-tank stub pipes, pump house."""
    white = PALETTE["tank_white"]
    pipe_c = PALETTE["pipe"]
    b = MeshBuilder()
    # dome cap: quarter-ellipse profile revolved, tipped up (+Z -> +Y)
    dome = make_lathe([(3.2 * math.sin(t), 8.0 * math.cos(t))
                       for t in np.linspace(0.0, 0.5 * math.pi, 7)],
                      28, white)
    up = rot_x(-0.5 * math.pi)
    for xx in (-20.0, 0.0, 20.0):
        for zz in (-11.0, 11.0):
            b.add_mesh(make_cylinder(8.0, 12.0, 28, white, axis="y",
                                     offset=(xx, 6.0, zz)))
            b.add_mesh(dome, rotation=up, offset=(xx, 12.0, zz))
            # stub from the tank wall to the central manifold
            b.add_mesh(make_cylinder(0.3, 8.4, 10, pipe_c, axis="z",
                                     offset=(xx, 0.9, math.copysign(4.6, zz))))
    # twin manifold pipes running the row, into the pump house
    for sz in (-0.7, 0.7):
        b.add_mesh(make_cylinder(0.45, 62.0, 12, pipe_c, axis="x",
                                 offset=(1.0, 0.9, sz)))
    b.add_mesh(make_box((8.0, 4.0, 6.0), PALETTE["concrete"],
                        offset=(34.0, 2.0, 0.0)))
    b.add_mesh(make_box((8.5, 0.4, 6.5), PALETTE["mil_green_dark"],
                        offset=(34.0, 4.1, 0.0)))
    return b.build()


def build_harbor() -> MeshData:
    """2 concrete finger quays (tops 2.5 m above water), 3 warehouses,
    2 gantry cranes with booms over the basin between the quays, and a
    shore apron at the +z end: a paved pad joining the quay roots to the
    rising foreshore behind the port (Task GATE — the model is placed at
    the waterline with land toward +z; the apron hides the beach seam)."""
    conc = PALETTE["concrete"]
    b = MeshBuilder()
    for xx in (-38.0, 38.0):
        b.add_mesh(make_box((24.0, 4.0, 170.0), conc, offset=(xx, 0.5, 0.0)))
    quay_top = 2.5
    # shore apron: spans the full port width, top just above the quay decks,
    # bottom below the waterline so the slab sits into the beach.
    b.add_mesh(make_box((104.0, 3.4, 90.0), conc, offset=(0.0, 1.3, 105.0)))
    # warehouses: concrete walls, steel-blue roofs
    for xx, zz in ((-38.0, -50.0), (-38.0, 10.0), (38.0, -30.0)):
        b.add_mesh(make_box((16.0, 8.0, 44.0), conc,
                            offset=(xx, quay_top + 4.0, zz)))
        b.add_mesh(make_box((16.6, 0.7, 45.0), PALETTE["container_b"],
                            offset=(xx, quay_top + 8.1, zz)))
    # gantry cranes (mustard yellow) on the east quay, booms over the basin
    yellow = PALETTE["container_c"]
    for cz in (30.0, 65.0):
        cx = 38.0
        for sx in (-6.0, 6.0):
            for sz in (-5.0, 5.0):
                b.add_mesh(make_box((0.9, 16.0, 0.9), yellow,
                                    offset=(cx + sx, quay_top + 8.0, cz + sz)))
        for sz in (-5.0, 5.0):                     # twin boom girders
            b.add_mesh(make_box((30.0, 1.4, 0.9), yellow,
                                offset=(cx - 9.0, quay_top + 16.7, cz + sz)))
        for sx in (-6.0, 6.0):                     # cross ties over the legs
            b.add_mesh(make_box((1.0, 1.4, 11.0), yellow,
                                offset=(cx + sx, quay_top + 16.7, cz)))
        b.add_mesh(make_box((5.0, 2.6, 8.0), yellow,
                            offset=(cx + 2.0, quay_top + 18.7, cz)))
    return b.build()
