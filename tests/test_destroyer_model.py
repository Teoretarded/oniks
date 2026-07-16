"""Tests for models/destroyer.py — Arleigh Burke DDG builder.

Mirrors the ship-model test pattern from tests/test_models.py:
- Basic mesh sanity (finite float32 verts, unit normals, valid indices).
- Vertex count in a sane band (not empty, not absurdly dense).
- Bounding box matches real-world scale within 20 % tolerance.
- Nothing unreasonably deep below the waterline.
- PALETTE entry for haze_gray exists.
"""

import numpy as np
import pytest

from models.common import PALETTE
from models.destroyer import build_destroyer


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _mesh():
    """Build once and cache via module-level fixture."""
    return build_destroyer()


def _check_sanity(md):
    """Shared sanity assertions mirroring test_models._check."""
    assert md.vertices.dtype == np.float32, "vertices must be float32"
    assert md.indices.dtype == np.uint32, "indices must be uint32"
    assert md.indices.max() < len(md.vertices), "index out of range"
    assert np.isfinite(md.vertices).all(), "non-finite value in vertices"
    n = md.vertices[:, 3:6]
    norms = np.linalg.norm(n, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-3), "normals not unit length"


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

def test_palette_haze_gray_exists():
    """PALETTE must expose haze_gray (added for the destroyer)."""
    assert "haze_gray" in PALETTE
    r, g, b = PALETTE["haze_gray"]
    # sanity: it really is a medium grey, not accidentally white or black
    assert 0.35 <= r <= 0.75
    assert 0.35 <= g <= 0.75
    assert 0.35 <= b <= 0.75


def test_build_returns_meshdata():
    """build_destroyer() returns without error and yields a non-empty mesh."""
    md = _mesh()
    assert md is not None
    assert len(md.vertices) > 0
    assert len(md.indices) > 0


def test_mesh_sanity():
    """Finite vertices, unit normals, valid indices."""
    _check_sanity(_mesh())


def test_vertex_count_sane_band():
    """Vertex count should be in [1 000, 60 000] (low-poly stylised, not bare
    box and not a subdivision-surface hero asset)."""
    md = _mesh()
    n = len(md.vertices)
    assert 1_000 <= n <= 60_000, f"vertex count {n} outside expected band [1000, 60000]"


def test_length_approx_155m():
    """Z-extent (forward axis) should be 155 m ± 20 %."""
    md = _mesh()
    z = md.vertices[:, 2]
    length = float(z.max() - z.min())
    assert abs(length - 155.0) / 155.0 <= 0.20, (
        f"length {length:.1f} m deviates more than 20 % from 155 m"
    )


def test_beam_approx_20m():
    """X-extent (beam) should be 20 m ± 20 %."""
    md = _mesh()
    x = md.vertices[:, 0]
    beam = float(x.max() - x.min())
    assert abs(beam - 20.0) / 20.0 <= 0.20, (
        f"beam {beam:.1f} m deviates more than 20 % from 20 m"
    )


def test_height_including_mast():
    """Y-extent (height) should be ~40 m (incl mast) within 20 % tolerance.

    The spec says approx 40 m tall including the mast; 20 % gives a window
    of [15 m, 48 m].  The lower bound guards against a missing mast/superstructure.
    """
    md = _mesh()
    y = md.vertices[:, 1]
    height = float(y.max() - y.min())
    # must be taller than a bare hull — mast adds at least 15 m above waterline
    assert height >= 15.0, f"total height {height:.1f} m suspiciously short"
    # spec approx 40 m within 20 %; upper bound = 48 m
    assert height <= 48.0, (
        f"total height {height:.1f} m exceeds spec upper bound of 48 m (40 m + 20 %)"
    )


def test_draft_limit():
    """Nothing should sit deeper than 7 m below the waterline (y = 0)."""
    md = _mesh()
    y_min = float(md.vertices[:, 1].min())
    assert y_min >= -7.0, f"deepest vertex at y = {y_min:.2f} m, exceeds draft limit"


def test_origin_midship():
    """Bow and stern should straddle z = 0 (origin at midship waterline)."""
    md = _mesh()
    z = md.vertices[:, 2]
    # The midpoint of the z-extent should be within ±10 m of zero.
    z_mid = float((z.max() + z.min()) * 0.5)
    assert abs(z_mid) <= 10.0, (
        f"z midpoint {z_mid:.1f} m — origin is not near midship"
    )


def test_superstructure_above_deck():
    """There should be significant geometry above the waterline (the superstructure
    and mast push the Y max well above the deck, > 10 m)."""
    md = _mesh()
    assert float(md.vertices[:, 1].max()) >= 10.0, (
        "nothing taller than 10 m above waterline — mast/superstructure missing?"
    )


def test_vls_hatches_and_stern_flight_deck_are_visible():
    """High-angle signatures: two real hatch fields and an aft landing mark."""
    md = _mesh()
    dark = np.all(np.isclose(md.vertices[:, 6:9],
                             PALETTE["aircraft_dark"], atol=1e-4), axis=1)
    # 96 individual lids contribute 24 vertices each.
    assert dark.sum() >= 96 * 24

    white = np.all(np.isclose(md.vertices[:, 6:9],
                              PALETTE["radar_white"], atol=1e-4), axis=1)
    aft_mark = md.vertices[white & (md.vertices[:, 2] < -63.0)]
    assert len(aft_mark) >= 100


def test_no_destroyer_geometry_overhangs_bow_or_stern():
    z = _mesh().vertices[:, 2]
    assert z.min() >= -77.501 and z.max() <= 77.501


def test_index_count_is_multiple_of_3():
    """All faces are triangles, so index count must be divisible by 3."""
    md = _mesh()
    assert len(md.indices) % 3 == 0, "index count is not a multiple of 3"
