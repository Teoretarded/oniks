"""Blast felling: trees inside a crater's scorch zone must go down.

GL-free — fell_mask is the pure filter _ensure_mesh applies when a
tile carries craters.
"""

from __future__ import annotations

import numpy as np

from world.cinematic_trees import fell_mask


def test_fell_mask_zones():
    # Tile at (1000, 2000); trees along a line east of the crater.
    xs = np.array([0.0, 100.0, 130.0, 200.0, 500.0])   # tile-local
    zs = np.zeros(5)
    # Crater at world (1000, 2000) = tile-local (0, 0), R = 100:
    # felling reach 1.4 * R = 140.
    craters = [(1000.0, 2000.0, 100.0, 40.0, 555.0)]
    keep = fell_mask(xs, zs, 1000.0, 2000.0, craters)
    assert keep.tolist() == [False, False, False, True, True]


def test_fell_mask_multiple_craters_and_empty():
    xs = np.array([0.0, 300.0])
    zs = np.array([0.0, 0.0])
    keep = fell_mask(xs, zs, 0.0, 0.0, [])
    assert keep.all()                      # no craters: everything stands
    keep = fell_mask(xs, zs, 0.0, 0.0,
                     [(0.0, 0.0, 50.0), (300.0, 0.0, 50.0)])
    assert not keep.any()                  # each tree inside one blast
