"""Visual-signature checks for the rebuilt cargo harbor."""

from __future__ import annotations

import numpy as np

from models.common import PALETTE
from models.structures import build_harbor


def _mask(mesh, key):
    return np.all(np.isclose(mesh.vertices[:, 6:9], PALETTE[key], atol=1e-4),
                  axis=1)


def test_harbor_has_overhead_readable_cargo_and_crane_detail():
    mesh = build_harbor()
    points = mesh.vertices[:, :3]
    assert len(mesh.indices) // 3 >= 1_500
    assert points[:, 0].min() <= -52.0 and points[:, 0].max() >= 52.0
    assert points[:, 2].min() <= -85.0 and points[:, 2].max() >= 150.0

    containers = (_mask(mesh, "container_a") | _mask(mesh, "container_b")
                  | _mask(mesh, "container_c"))
    assert containers.sum() >= 1_000
    assert points[containers, 1].max() >= 9.0


def test_harbor_has_fenders_bollards_and_high_ship_to_shore_cranes():
    mesh = build_harbor()
    points = mesh.vertices[:, :3]
    tire = points[_mask(mesh, "tire")]
    steel = points[_mask(mesh, "pipe")]
    assert len(tire) >= 600
    assert tire[:, 1].min() < 0.0
    assert steel[:, 1].max() >= 18.0
    assert points[:, 1].max() >= 22.5
