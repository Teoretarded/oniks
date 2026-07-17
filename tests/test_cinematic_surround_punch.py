"""Surround-ring hole punch: coarse chunks must not double-draw the
fine LiDAR core (the 'overlapping mountains' report, 2026-07-17).

GL-free.  A ring-1 chunk that covers part of the core keeps only its
outside-the-core triangles plus a tucked crack-cover band straddling
the border; a chunk fully outside the core is untouched.
"""

from __future__ import annotations

import numpy as np

from world.cinematic_scene import build_tile_arrays, punch_core_hole


def _chunk(size=4000.0, cells=20):
    """A flat haloed chunk grid -> (verts, indices)."""
    n = cells + 3
    h = np.full((n, n), 50.0, dtype=np.float32)
    return build_tile_arrays(h, size / cells, size, skirt_drop=70.0)


def _tri_centers(verts, indices, x0, z0):
    tri = indices.reshape(-1, 3)
    px = verts[:, 0][tri] + x0
    pz = verts[:, 2][tri] + z0
    return px.mean(axis=1), pz.mean(axis=1)


def test_punch_removes_interior_keeps_border_band():
    core = (-2000.0, -2000.0, 2000.0, 2000.0)
    margin = 64.0
    verts, indices = _chunk()
    # Chunk x,z in [-4000, 0]: its NE quadrant covers core ground.
    x0 = z0 = -4000.0
    pv, pi = punch_core_hole(verts, indices, x0, z0, core, margin)
    assert pv is verts                      # vertices untouched
    assert len(pi) < len(indices)           # something was removed
    assert len(pi) % 3 == 0
    cx, cz = _tri_centers(pv, pi, x0, z0)
    # No surviving triangle sits fully interior: every one has a
    # vertex within `margin + one cell` of the core border or outside.
    cell = 4000.0 / 20
    deep = ((cx > core[0] + margin + cell) & (cx < core[2] - margin - cell)
            & (cz > core[1] + margin + cell) & (cz < core[3] - margin - cell))
    assert not deep.any()
    # The crack-cover band survives: triangles straddling the border.
    near = ((np.abs(cx) < 2000.0 + cell) & (np.abs(cz) < 2000.0 + cell)
            & ((np.abs(cx) > 2000.0 - margin - cell)
               | (np.abs(cz) > 2000.0 - margin - cell)))
    assert near.any()


def test_punch_noop_outside_core():
    core = (-2000.0, -2000.0, 2000.0, 2000.0)
    verts, indices = _chunk()
    # Chunk far to the east: no overlap at all.
    pv, pi = punch_core_hole(verts, indices, 8000.0, -4000.0, core)
    assert pv is verts and pi is indices    # exact no-op, zero copies
