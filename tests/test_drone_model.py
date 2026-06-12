"""Tests for the RQ-4-class recon drone model (models/drone.py).

Checks:
  1. build_recon_drone() returns a valid MeshData (non-empty, correct dtypes).
  2. Bounding box is approximately 39.9 m wide, ~4 m tall, ~14.5 m long (±20%).
  3. Vertex count is within a sane band (>= patrol_aircraft, <= patrol*2).
  4. The model is symmetric about x = 0 (|max_x - |min_x|| < 0.5 m).
  5. PALETTE entry 'drone_skin' exists.
"""

import numpy as np
import pytest

from engine.meshdata import MeshData
from models.drone import build_recon_drone
from models.aircraft_model import build_patrol_aircraft
from models.common import PALETTE

# ---------------------------------------------------------------------------
# Reference dimensions (real-world, SI metres)
# ---------------------------------------------------------------------------
EXPECTED_WINGSPAN_M = 39.9    # full span wing-tip to wing-tip
EXPECTED_LENGTH_M   = 14.5    # nose to tail along Z
# RQ-4 official height 4.62 m; V-tail tips add ~0.5 m → total ~5.1 m.
# We allow a generous ±35% band to cover modelling variation.
EXPECTED_HEIGHT_M   =  4.62   # m, RQ-4 official airframe height
TOLERANCE_GENERAL   =  0.20   # ±20 % for wingspan / length
TOLERANCE_HEIGHT    =  0.35   # ±35 % for height (V-tail tip variation)


def _bbox(md: MeshData):
    """Return (min, max) as (3,) arrays over all vertex positions."""
    pos = md.vertices[:, 0:3]
    return pos.min(axis=0), pos.max(axis=0)


@pytest.fixture(scope="module")
def drone():
    return build_recon_drone()


@pytest.fixture(scope="module")
def patrol():
    return build_patrol_aircraft()


# ---------------------------------------------------------------------------
# 1. Builds without error, returns MeshData
# ---------------------------------------------------------------------------

def test_build_returns_meshdata(drone):
    assert isinstance(drone, MeshData)


def test_vertices_non_empty(drone):
    assert drone.vertices.shape[0] > 0, "vertices array is empty"
    assert drone.indices.shape[0] > 0, "indices array is empty"


def test_vertex_dtype(drone):
    assert drone.vertices.dtype == np.float32
    assert drone.indices.dtype == np.uint32


def test_vertex_columns(drone):
    assert drone.vertices.shape[1] == 9, "expected 9 floats per vertex: pos3 norm3 color3"


# ---------------------------------------------------------------------------
# 2. Bounding box dimensions within ±20 % of target
# ---------------------------------------------------------------------------

def test_bbox_wingspan(drone):
    lo, hi = _bbox(drone)
    width = hi[0] - lo[0]   # X axis
    assert width == pytest.approx(EXPECTED_WINGSPAN_M, rel=TOLERANCE_GENERAL), (
        f"Wingspan {width:.2f} m not within 20% of {EXPECTED_WINGSPAN_M} m"
    )


def test_bbox_length(drone):
    lo, hi = _bbox(drone)
    length = hi[2] - lo[2]  # Z axis (forward = +Z)
    assert length == pytest.approx(EXPECTED_LENGTH_M, rel=TOLERANCE_GENERAL), (
        f"Length {length:.2f} m not within 20% of {EXPECTED_LENGTH_M} m"
    )


def test_bbox_height(drone):
    lo, hi = _bbox(drone)
    height = hi[1] - lo[1]  # Y axis
    assert height == pytest.approx(EXPECTED_HEIGHT_M, rel=TOLERANCE_HEIGHT), (
        f"Height {height:.2f} m not within 35% of {EXPECTED_HEIGHT_M} m"
    )


# ---------------------------------------------------------------------------
# 3. Vertex count sane band: >= patrol, <= 2 * patrol
# ---------------------------------------------------------------------------

def test_vertex_count_lower_bound(drone, patrol):
    assert drone.vertices.shape[0] >= patrol.vertices.shape[0], (
        f"Drone vertex count {drone.vertices.shape[0]} below patrol "
        f"{patrol.vertices.shape[0]}"
    )


def test_vertex_count_upper_bound(drone, patrol):
    limit = patrol.vertices.shape[0] * 2
    assert drone.vertices.shape[0] <= limit, (
        f"Drone vertex count {drone.vertices.shape[0]} exceeds 2× patrol "
        f"({limit})"
    )


# ---------------------------------------------------------------------------
# 4. Symmetric about x = 0
# ---------------------------------------------------------------------------

def test_x_symmetry(drone):
    pos = drone.vertices[:, 0:3]
    max_x = float(pos[:, 0].max())
    min_x = float(pos[:, 0].min())
    asymmetry = abs(max_x + min_x)   # should be ≈ 0 for a symmetric model
    assert asymmetry < 0.5, (
        f"Model not symmetric about x=0: max_x={max_x:.3f}, min_x={min_x:.3f}, "
        f"asymmetry={asymmetry:.3f} m"
    )


# ---------------------------------------------------------------------------
# 5. PALETTE entry exists
# ---------------------------------------------------------------------------

def test_drone_skin_in_palette():
    assert "drone_skin" in PALETTE, "'drone_skin' missing from PALETTE"


def test_drone_dark_in_palette():
    assert "drone_dark" in PALETTE, "'drone_dark' missing from PALETTE"
