"""Geometry-to-gameplay envelope contracts for rebuilt static assets."""

from __future__ import annotations

import numpy as np
import pytest

from models.airfield import build_airfield
from models.bastion import build_bastion_tel
from models.pantsir import build_pantsir
from models.s300 import build_s300_tel
from models.support_assets import (
    build_buk_telar,
    build_cbr_radar,
    build_corner_reflector,
    build_decoy_emitter,
    build_swarm_pod,
)
from sim.bases import DIMS_TEL
from world.combat import (
    AIRFIELD_DIMS,
    CBR_STRUCT_DIMS,
    CR_STRUCT_DIMS,
    DECOY_STRUCT_DIMS,
    PANTSIR_STRUCT_DIMS,
    SWARM_POD_STRUCT_DIMS,
    _BUK_STRUCT_DIMS,
)


def _assert_mesh_inside_structure(builder, dims, tolerance=0.02):
    vertices = builder().vertices[:, :3]
    lo = vertices.min(axis=0)
    hi = vertices.max(axis=0)
    length, beam, height = dims
    assert lo[0] >= -beam * 0.5 - tolerance
    assert hi[0] <= beam * 0.5 + tolerance
    assert lo[1] >= -tolerance
    assert hi[1] <= height + tolerance
    assert lo[2] >= -length * 0.5 - tolerance
    assert hi[2] <= length * 0.5 + tolerance


@pytest.mark.parametrize("builder", (
    lambda: build_bastion_tel(elevation_deg=0.0),
    lambda: build_bastion_tel(elevation_deg=88.0),
    lambda: build_s300_tel(elevation_deg=0.0),
    lambda: build_s300_tel(elevation_deg=90.0),
))
def test_shared_tel_volume_contains_every_launch_state(builder):
    _assert_mesh_inside_structure(builder, DIMS_TEL)


@pytest.mark.parametrize(("builder", "dims"), (
    (build_pantsir, PANTSIR_STRUCT_DIMS),
    (build_buk_telar, _BUK_STRUCT_DIMS),
    (build_swarm_pod, SWARM_POD_STRUCT_DIMS),
    (build_cbr_radar, CBR_STRUCT_DIMS),
    (build_decoy_emitter, DECOY_STRUCT_DIMS),
    (build_corner_reflector, CR_STRUCT_DIMS),
    (build_airfield, AIRFIELD_DIMS),
))
def test_dedicated_structure_volumes_contain_visual_mesh(builder, dims):
    _assert_mesh_inside_structure(builder, dims)


def test_structure_dimension_order_is_length_z_beam_x_height_y():
    length, beam, height = PANTSIR_STRUCT_DIMS
    assert np.array((beam * 0.5, height * 0.5, length * 0.5)) == pytest.approx(
        (1.8, 2.5, 4.2)
    )
