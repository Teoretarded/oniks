"""Tests for models/pantsir.py — Pantsir-S1 SHORAD vehicle model.

Mirrors the model-test pattern from tests/test_models.py and
tests/test_destroyer_model.py:
  - build_pantsir() returns a non-empty MeshData with correct dtypes.
  - Basic mesh sanity: finite float32 verts, unit normals, valid indices,
    index count divisible by 3.
  - Vertex count in a sane band (not a bare box, not a subdivision hero).
  - Bounding box within 20% of real-world target:
      width  ≈ 3.0 m (chassis + outriggers)
      height ≈ 5.0 m (incl. radar drum on turret top)
      length ≈ 8.0 m (chassis)
  - Symmetric about x = 0 (|max_x + min_x| < 0.5 m).
  - Sits on the ground: min_y >= -0.2 m (wheels at y ≈ 0).
  - Turret above deck: geometry well above FRAME_TOP.
  - Canister blocks present on both sides (tube_grey on ±X).
  - Radar components present (radar_white colour used).
  - Barrels (cannon) present: thin cylinders reaching forward of the turret.
"""

import numpy as np
import pytest

from engine.meshdata import MeshData
from models.common import PALETTE
from models.pantsir import build_pantsir

# ---------------------------------------------------------------------------
# Target dimensions (real-world, SI metres)
# ---------------------------------------------------------------------------
TARGET_WIDTH_M  = 3.0    # chassis width spec (LOCKED)
TARGET_HEIGHT_M = 5.0    # approx incl. search radar
TARGET_LENGTH_M = 8.0    # chassis length (LOCKED)
TOL             = 0.20   # ±20 % tolerance


# ---------------------------------------------------------------------------
# Shared fixture + helpers
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def pantsir() -> MeshData:
    return build_pantsir()


def _pos(md: MeshData) -> np.ndarray:
    """Return all vertex positions as (N, 3) float array."""
    return md.vertices[:, :3].astype(np.float64)


def _color_mask(md: MeshData, key: str) -> np.ndarray:
    """Boolean mask of vertices matching PALETTE[key] (atol 1e-4)."""
    return np.all(np.isclose(md.vertices[:, 6:9], PALETTE[key], atol=1e-4),
                  axis=1)


# ---------------------------------------------------------------------------
# 1. Build correctness
# ---------------------------------------------------------------------------

def test_build_returns_meshdata(pantsir):
    assert isinstance(pantsir, MeshData)


def test_vertices_non_empty(pantsir):
    assert pantsir.vertices.shape[0] > 0, "vertices array is empty"
    assert pantsir.indices.shape[0] > 0, "indices array is empty"


def test_vertex_dtype(pantsir):
    assert pantsir.vertices.dtype == np.float32, "vertices must be float32"
    assert pantsir.indices.dtype == np.uint32, "indices must be uint32"


def test_vertex_columns(pantsir):
    assert pantsir.vertices.shape[1] == 9, (
        "expected 9 floats per vertex: pos3 norm3 color3"
    )


# ---------------------------------------------------------------------------
# 2. Mesh sanity
# ---------------------------------------------------------------------------

def test_finite_vertices(pantsir):
    assert np.isfinite(pantsir.vertices).all(), "non-finite value in vertices"


def test_unit_normals(pantsir):
    n = pantsir.vertices[:, 3:6]
    norms = np.linalg.norm(n, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-3), "normals not unit length"


def test_valid_indices(pantsir):
    assert pantsir.indices.max() < len(pantsir.vertices), "index out of range"


def test_index_count_multiple_of_3(pantsir):
    assert len(pantsir.indices) % 3 == 0, (
        "index count not divisible by 3 — not all-triangle mesh"
    )


# ---------------------------------------------------------------------------
# 3. Vertex count sane band
# ---------------------------------------------------------------------------

def test_vertex_count_sane_band(pantsir):
    n = len(pantsir.vertices)
    assert 500 <= n <= 40_000, (
        f"vertex count {n} outside expected band [500, 40000]"
    )


# ---------------------------------------------------------------------------
# 4. Bounding box within ±20% of target dimensions
# ---------------------------------------------------------------------------

def test_width_approx_3m(pantsir):
    pos = _pos(pantsir)
    width = float(pos[:, 0].max() - pos[:, 0].min())
    assert abs(width - TARGET_WIDTH_M) / TARGET_WIDTH_M <= TOL, (
        f"width {width:.2f} m deviates > 20% from {TARGET_WIDTH_M} m"
    )


def test_height_approx_5m(pantsir):
    pos = _pos(pantsir)
    height = float(pos[:, 1].max() - pos[:, 1].min())
    assert abs(height - TARGET_HEIGHT_M) / TARGET_HEIGHT_M <= TOL, (
        f"height {height:.2f} m deviates > 20% from {TARGET_HEIGHT_M} m"
    )


def test_length_approx_8m(pantsir):
    pos = _pos(pantsir)
    length = float(pos[:, 2].max() - pos[:, 2].min())
    assert abs(length - TARGET_LENGTH_M) / TARGET_LENGTH_M <= TOL, (
        f"length {length:.2f} m deviates > 20% from {TARGET_LENGTH_M} m"
    )


# ---------------------------------------------------------------------------
# 5. Symmetry about x = 0
# ---------------------------------------------------------------------------

def test_symmetric_about_x_zero(pantsir):
    pos = _pos(pantsir)
    asymmetry = abs(float(pos[:, 0].max()) + float(pos[:, 0].min()))
    assert asymmetry < 0.5, (
        f"model not symmetric about x=0: max_x={pos[:,0].max():.3f}, "
        f"min_x={pos[:,0].min():.3f}, |sum|={asymmetry:.3f} m"
    )


# ---------------------------------------------------------------------------
# 6. Ground plane — sits on the ground
# ---------------------------------------------------------------------------

def test_sits_on_ground(pantsir):
    pos = _pos(pantsir)
    y_min = float(pos[:, 1].min())
    assert y_min >= -0.20, (
        f"lowest vertex at y={y_min:.3f} m — vehicle floats or sinks below ground"
    )


def test_wheel_bottoms_near_ground(pantsir):
    """Wheel bottoms (min Y) should be within 0.10 m of y = 0."""
    from models.pantsir import TIRE_R
    pos = _pos(pantsir)
    # Tire-coloured vertices
    tire_mask = _color_mask(pantsir, "tire")
    assert tire_mask.any(), "no tire-coloured vertices found"
    y_tire_min = float(pos[tire_mask, 1].min())
    assert y_tire_min <= 0.10, (
        f"tire bottoms at y={y_tire_min:.3f} m — too high above ground"
    )


# ---------------------------------------------------------------------------
# 7. Turret / radar above deck
# ---------------------------------------------------------------------------

def test_turret_above_deck(pantsir):
    """Geometry should reach significantly above the chassis deck (~1.3 m)."""
    pos = _pos(pantsir)
    # Highest vertex should be well above the deck level
    from models.pantsir import FRAME_TOP
    assert float(pos[:, 1].max()) > FRAME_TOP + 2.0, (
        f"nothing above {FRAME_TOP + 2.0:.1f} m — turret/radar missing?"
    )


def test_radar_white_geometry_present(pantsir):
    """Tracking radar and search radar drum use radar_white palette colour."""
    mask = _color_mask(pantsir, "radar_white")
    assert mask.any(), "no radar_white geometry found — radar missing?"
    pos = _pos(pantsir)
    # Radar geometry must be above the chassis deck
    from models.pantsir import FRAME_TOP
    assert float(pos[mask, 1].max()) > FRAME_TOP, (
        "radar_white geometry is below the deck — placed incorrectly?"
    )


# ---------------------------------------------------------------------------
# 8. Missile canisters — present on both sides
# ---------------------------------------------------------------------------

def test_canister_blocks_both_sides(pantsir):
    """tube_grey canisters must exist on both the +X and -X sides."""
    mask = _color_mask(pantsir, "tube_grey")
    assert mask.any(), "no tube_grey canister geometry found"
    pos = _pos(pantsir)
    can_x = pos[mask, 0]
    assert (can_x > 0.3).any(), "no canisters found on the +X (right) side"
    assert (can_x < -0.3).any(), "no canisters found on the -X (left) side"


def test_twelve_canisters_implied_by_span(pantsir):
    """The canister blocks should span a vertical range consistent with
    3 rows (≥ 2 × CAN_W ≈ 0.64 m) and a longitudinal range consistent with
    2 columns (≥ 1 × CAN_L * 0.5 ≈ 1.6 m) on each side."""
    from models.pantsir import CAN_W, CAN_L
    mask = _color_mask(pantsir, "tube_grey")
    pos = _pos(pantsir)
    for side, selector in (("right (+X)", pos[mask, 0] > 0.3),
                           ("left (-X)", pos[mask, 0] < -0.3)):
        side_pos = pos[mask][selector]
        assert len(side_pos) > 0, f"no canisters on {side}"
        y_span = float(side_pos[:, 1].max() - side_pos[:, 1].min())
        z_span = float(side_pos[:, 2].max() - side_pos[:, 2].min())
        assert y_span >= CAN_W * 2.0, (
            f"{side}: canister y-span {y_span:.2f} m < 2×CAN_W ({CAN_W*2:.2f} m) "
            f"— fewer than 3 rows?"
        )
        assert z_span >= CAN_L * 0.5, (
            f"{side}: canister z-span {z_span:.2f} m < CAN_L/2 ({CAN_L*0.5:.2f} m) "
            f"— fewer than 2 columns?"
        )


# ---------------------------------------------------------------------------
# 9. Cannon barrels present and reach forward
# ---------------------------------------------------------------------------

def test_cannon_barrels_present(pantsir):
    """Barrel geometry (radome/dark colour, thin cylinder) must reach forward
    of the turret centre (z > TURRET_Z)."""
    from models.pantsir import TURRET_Z, BARREL_L
    # Barrels use _DARK = PALETTE["mil_green_dark"]
    mask = _color_mask(pantsir, "mil_green_dark")
    assert mask.any(), "no mil_green_dark geometry found (barrel/housing missing?)"
    pos = _pos(pantsir)
    # At least some dark geometry reaches well forward (barrel tips)
    dark_z_max = float(pos[mask, 2].max())
    assert dark_z_max > TURRET_Z + BARREL_L * 0.3, (
        f"dark geometry z_max={dark_z_max:.2f} m — cannon barrels not reaching forward"
    )
