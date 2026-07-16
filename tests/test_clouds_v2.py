"""Headless contracts for the staged Cloud V2 renderer."""

import numpy as np

from world.clouds_v2 import (CloudsV2, _COMPOSITE_FRAG, _QUALITY_SCALE,
                             _TEMPORAL_FRAG, _v2_raymarch_source)


def test_v2_raymarch_emits_first_hit_depth_and_disables_blind_skip():
    src = _v2_raymarch_source()
    assert "layout(location=1) out float cloud_depth;" in src
    assert "cloud_depth = max(t_hit, 0.0);" in src
    assert "skip_mul = min(skip_mul * 2.0, 5.0)" not in src
    assert "skip_mul = 1.0;" in src
    assert "u_high_occupancy" in src
    assert "for (int z = -1; z <= 1; ++z)" not in src


def test_severe_volume_has_no_camera_crossing_iteration_cutoff():
    src = _v2_raymarch_source("ultra")
    # A per-ray storm-occupancy budget caused a hard world-space boundary:
    # after crossing it, the ray stopped before clouds farther away.
    assert "storm_voxel_steps" not in src
    assert "storm_occ > 0.0" not in src


def test_high_occupancy_map_is_periodic_and_conservative():
    high = np.zeros((5, 5, 2), dtype=np.uint8)
    high[0, 0, 1] = 1
    occupied = CloudsV2._high_occupancy_map(high)
    assert occupied.dtype == np.uint8
    assert np.count_nonzero(occupied) == 9
    assert occupied[0, 0] == 255
    assert occupied[-1, -1] == 255


def test_quality_scales_are_ordered_and_bounded():
    scales = [_QUALITY_SCALE[k] for k in ("low", "med", "high", "ultra")]
    assert scales == sorted(scales)
    assert 0.0 < scales[0] < scales[-1] <= 1.0
    assert _QUALITY_SCALE["ultra"] == 0.40


def test_temporal_resolve_reprojects_clamps_and_rejects_depth():
    assert "u_prev_proj_view_rot" in _TEMPORAL_FRAG
    assert "u_wind_xz" in _TEMPORAL_FRAG
    assert "depth_tolerance" in _TEMPORAL_FRAG
    assert "history = clamp(history, lo, hi)" in _TEMPORAL_FRAG


def test_full_resolution_composite_uses_fast_common_path():
    assert "texture(u_cloud_color, uv)" in _COMPOSITE_FRAG
    assert "texture(u_cloud_depth, uv)" in _COMPOSITE_FRAG
    assert "if (ref <= 0.0)" in _COMPOSITE_FRAG
    assert "exp(-abs" not in _COMPOSITE_FRAG
