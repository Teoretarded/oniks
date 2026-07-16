"""GL-free contracts for dedicated support-platform geometry."""

from __future__ import annotations

import pytest

from game.testing_catalog import mesh_metadata
from models.support_assets import (
    build_buk_telar,
    build_cbr_radar,
    build_corner_reflector,
    build_decoy_emitter,
    build_sam_pad,
    build_submarine,
    build_swarm_pod,
)


@pytest.mark.parametrize("builder", (
    build_buk_telar,
    build_cbr_radar,
    build_corner_reflector,
    build_decoy_emitter,
    build_sam_pad,
    build_submarine,
    build_swarm_pod,
))
def test_support_builder_returns_detailed_valid_mesh(builder):
    stats = mesh_metadata(builder())
    assert stats["triangles"] >= 70
    assert all(value > 0.0 for value in stats["dimensions"])


def test_project_636_submarine_keeps_reference_dimensions():
    dims = mesh_metadata(build_submarine())["dimensions"]
    assert dims[0] == pytest.approx(9.9, abs=0.05)
    assert dims[2] == pytest.approx(74.71, abs=0.10)  # propeller beyond hull
    assert dims[1] >= 11.0


def test_swarm_pod_fits_its_gameplay_structure_envelope():
    dims = mesh_metadata(build_swarm_pod())["dimensions"]
    assert dims[0] <= 4.0
    assert dims[2] <= 5.0
    assert dims[1] <= 2.5


def test_buk_is_a_compact_tracked_telar_not_an_s300_proxy():
    stats = mesh_metadata(build_buk_telar())
    assert 8.0 <= stats["dimensions"][2] <= 10.0
    assert 3.0 <= stats["dimensions"][0] <= 4.0
    assert stats["triangles"] > 1_500


def test_cbr_radar_braces_stay_inside_the_site_footprint():
    dims = mesh_metadata(build_cbr_radar())["dimensions"]
    assert dims[0] < 12.0
    assert dims[2] < 9.0
