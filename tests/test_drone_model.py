"""Focused geometry tests for the RQ-4-class recon drone model."""

import numpy as np
import pytest

from engine.meshdata import MeshData
from models.common import PALETTE
from models.drone import build_recon_drone

EXPECTED_WINGSPAN_M = 39.9
EXPECTED_LENGTH_M = 14.5
EXPECTED_HEIGHT_M = 4.62
TOLERANCE_GENERAL = 0.20
TOLERANCE_HEIGHT = 0.35


def _bbox(md: MeshData):
    pos = md.vertices[:, 0:3]
    return pos.min(axis=0), pos.max(axis=0)


@pytest.fixture(scope="module")
def drone():
    return build_recon_drone()


def test_build_returns_meshdata(drone):
    assert isinstance(drone, MeshData)


def test_vertices_non_empty(drone):
    assert drone.vertices.shape[0] > 0
    assert drone.indices.shape[0] > 0


def test_vertex_layout_and_dtype(drone):
    assert drone.vertices.shape[1] == 9
    assert drone.vertices.dtype == np.float32
    assert drone.indices.dtype == np.uint32


def test_bbox_wingspan(drone):
    lo, hi = _bbox(drone)
    assert hi[0] - lo[0] == pytest.approx(
        EXPECTED_WINGSPAN_M, rel=TOLERANCE_GENERAL
    )


def test_bbox_length(drone):
    lo, hi = _bbox(drone)
    assert hi[2] - lo[2] == pytest.approx(
        EXPECTED_LENGTH_M, rel=TOLERANCE_GENERAL
    )


def test_bbox_height(drone):
    lo, hi = _bbox(drone)
    assert hi[1] - lo[1] == pytest.approx(
        EXPECTED_HEIGHT_M, rel=TOLERANCE_HEIGHT
    )


def test_vertex_count_sane(drone):
    assert 500 <= drone.vertices.shape[0] <= 4_000


def test_x_symmetry(drone):
    pos = drone.vertices[:, 0:3]
    assert abs(float(pos[:, 0].max()) + float(pos[:, 0].min())) < 0.5


def test_vtail_points_up_and_outboard(drone):
    """Catch the former rotation bug that put both fins below the UAV."""
    pos = drone.vertices[:, 0:3]
    skin = np.all(np.isclose(drone.vertices[:, 6:9], PALETTE["drone_skin"],
                             atol=1e-4), axis=1)
    tips = pos[skin & (pos[:, 2] < -4.0) & (pos[:, 1] > 2.0)]
    assert len(tips)
    assert (tips[:, 0] > 0.5).any()
    assert (tips[:, 0] < -0.5).any()
    assert float(pos[:, 1].min()) > -1.5


def test_drone_palette_entries():
    assert "drone_skin" in PALETTE
    assert "drone_dark" in PALETTE
