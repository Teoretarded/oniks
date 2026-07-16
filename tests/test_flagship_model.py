"""GL-free contracts for the dedicated Ticonderoga flagship model."""

from __future__ import annotations

import numpy as np
import pytest

from game.sandbox import SHIP_MESH_ALIAS
from game.testing_catalog import get_asset, mesh_metadata
from models.common import PALETTE
from models.flagship import build_flagship


@pytest.fixture(scope="module")
def flagship_mesh():
    return build_flagship()


def test_flagship_mesh_is_valid_and_detailed(flagship_mesh):
    assert flagship_mesh.vertices.dtype == np.float32
    assert flagship_mesh.indices.dtype == np.uint32
    assert np.isfinite(flagship_mesh.vertices).all()
    assert flagship_mesh.indices.max() < len(flagship_mesh.vertices)
    assert np.allclose(np.linalg.norm(flagship_mesh.vertices[:, 3:6], axis=1),
                       1.0, atol=1e-3)
    assert len(flagship_mesh.indices) // 3 >= 2_500


def test_flagship_matches_gameplay_envelope(flagship_mesh):
    dims = mesh_metadata(flagship_mesh)["dimensions"]
    assert dims[0] == pytest.approx(17.0, abs=0.05)
    assert dims[2] == pytest.approx(173.0, abs=0.05)
    assert dims[1] == pytest.approx(33.0, abs=0.10)


def test_twin_vls_fields_and_stern_helipad_read_from_overhead(flagship_mesh):
    vertices = flagship_mesh.vertices
    dark = np.all(np.isclose(vertices[:, 6:9], PALETTE["aircraft_dark"],
                             atol=1e-4), axis=1)
    # Two 61-cell fields, each hatch contributing 24 flat-shaded vertices.
    for z0 in (53.5, -50.0):
        field = vertices[dark & (np.abs(vertices[:, 2] - z0) < 4.2)
                         & (vertices[:, 1] < 7.0)]
        assert len(field) >= 61 * 24

    white = np.all(np.isclose(vertices[:, 6:9], PALETTE["radar_white"],
                              atol=1e-4), axis=1)
    assert len(vertices[white & (vertices[:, 2] < -69.0)]) >= 250


def test_catalog_and_burke_variant_routing_are_explicit():
    flagship = get_asset("flagship")
    assert flagship.builder_ref == "models.flagship:build_flagship"
    assert flagship.proxy_for is None
    assert SHIP_MESH_ALIAS == {
        "aaw_destroyer": "destroyer",
        "ground_attack_destroyer": "destroyer",
    }
