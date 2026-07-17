"""Terrain-deformation contracts: impact craters in CinematicScene.

GL-free.  Craters are a runtime height delta over the baked data —
physics (ground_h) and the renderer's rebuild grids read the SAME
math, so boots and pixels agree by construction.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from world.cinematic_scene import CinematicScene, halo_axes


@pytest.fixture()
def flat_scene(tmp_path):
    """A 256 m flat core at y = 10, no surround."""
    nx = nz = 257
    np.save(tmp_path / "dtm_1m.npy",
            np.full((nz, nx), 10.0, dtype=np.float32))
    np.save(tmp_path / "obstacle.npy", np.zeros((nz, nx), dtype=np.uint8))
    meta = {
        "name": "flat", "title": "FLAT", "subtitle": "TEST",
        "attribution": "test data", "epsg": 2056,
        "origin_e": 0.0, "origin_n": 0.0, "origin_alt": 100.0,
        "x0": 0.0, "x1": 256.0, "z0": 0.0, "z1": 256.0,
        "dtm": {"cell": 1.0, "file": "dtm_1m.npy"},
        "obstacle": {"cell": 1.0, "file": "obstacle.npy"},
        "spawn": {"x": 128.0, "z": 128.0, "yaw_deg": 0.0},
        "s300": {"x": 200.0, "z": 200.0, "yaw_deg": 180.0},
        "tiles": [], "surround": [],
    }
    (tmp_path / "scene.json").write_text(json.dumps(meta), encoding="utf-8")
    return tmp_path


def test_crater_bowl_rim_and_reach(flat_scene):
    sc = CinematicScene(str(flat_scene))
    base = sc.ground_h(128.0, 128.0)
    assert base == pytest.approx(10.0)
    sc.add_crater(128.0, 128.0, radius_m=20.0, depth_m=8.0)
    assert sc.crater_rev == 1
    # Center: the full depth is gone.
    assert sc.ground_h(128.0, 128.0) == pytest.approx(10.0 - 8.0, abs=0.2)
    # Half-radius: inside the bowl, meaningfully below grade.
    assert sc.ground_h(138.0, 128.0) < 10.0 - 3.0
    # The lip just outside the rim rises ABOVE grade (ejecta).
    assert sc.ground_h(128.0 + 21.5, 128.0) > 10.0 + 0.5
    # Beyond 1.7 R the world is untouched.
    assert sc.ground_h(128.0 + 40.0, 128.0) == pytest.approx(10.0)
    assert sc.ground_h(30.0, 30.0) == pytest.approx(10.0)


def test_crater_grid_matches_point_sampler(flat_scene):
    """The renderer's vectorized rebuild grid must be the SAME math as
    the walker's point sampler."""
    sc = CinematicScene(str(flat_scene))
    sc.add_crater(100.0, 140.0, radius_m=25.0, depth_m=10.0)
    sc.add_crater(160.0, 90.0, radius_m=12.0, depth_m=4.0)
    xs = np.arange(60.0, 200.0, 7.0)
    zs = np.arange(60.0, 200.0, 7.0)
    baked = np.full((len(zs), len(xs)), 10.0)   # the flat scene surface
    grid = sc.crater_delta_grid(xs, zs, baked)
    for j in range(0, len(zs), 3):
        for i in range(0, len(xs), 3):
            assert grid[j, i] == pytest.approx(
                sc.crater_delta(float(xs[i]), float(zs[j])), abs=1e-4)


def test_crater_cap_retires_oldest(flat_scene):
    sc = CinematicScene(str(flat_scene))
    for k in range(sc.CRATER_CAP + 8):
        sc.add_crater(10.0 + k, 10.0, radius_m=2.0, depth_m=1.0)
    assert len(sc._craters) == sc.CRATER_CAP
    assert sc.crater_rev == sc.CRATER_CAP + 8


def test_craters_intersecting_since_rev(flat_scene):
    sc = CinematicScene(str(flat_scene))
    sc.add_crater(50.0, 50.0, radius_m=10.0, depth_m=4.0)
    rev_after_first = sc.crater_rev
    sc.add_crater(200.0, 200.0, radius_m=10.0, depth_m=4.0)
    # Rect around the SECOND crater, only-new filter.
    hits = sc.craters_intersecting(180.0, 180.0, 220.0, 220.0,
                                   since_rev=rev_after_first)
    assert len(hits) == 1 and hits[0][0] == 200.0
    # The first crater is invisible to a since_rev filter...
    assert sc.craters_intersecting(30.0, 30.0, 70.0, 70.0,
                                   since_rev=rev_after_first) == []
    # ...but visible without one.
    assert len(sc.craters_intersecting(30.0, 30.0, 70.0, 70.0)) == 1


def test_walker_and_designation_see_the_crater(flat_scene):
    """ground_h is the single source: a crater is instantly walkable
    (the bowl) and the T-designation ray lands on the new surface."""
    sc = CinematicScene(str(flat_scene))
    sc.add_crater(128.0, 128.0, radius_m=30.0, depth_m=12.0)
    assert not sc.blocked(128.0, 128.0)
    # Bilinear-consistent: nearby samples interpolate smoothly.
    h1 = sc.ground_h(128.0, 128.0)
    h2 = sc.ground_h(128.5, 128.0)
    assert abs(h1 - h2) < 0.5


@pytest.fixture()
def peak_scene(tmp_path):
    """A 256 m scene: valley floor y = 10 with a 120 m cone at center."""
    nx = nz = 257
    r = np.hypot(np.arange(nx)[None, :] - 128.0,
                 np.arange(nz)[:, None] - 128.0)
    dtm = (10.0 + np.clip(120.0 * (1.0 - r / 60.0), 0.0, None)
           ).astype(np.float32)
    np.save(tmp_path / "dtm_1m.npy", dtm)
    np.save(tmp_path / "obstacle.npy", np.zeros((nz, nx), dtype=np.uint8))
    meta = {
        "name": "peak", "title": "PEAK", "subtitle": "TEST",
        "attribution": "test data", "epsg": 2056,
        "origin_e": 0.0, "origin_n": 0.0, "origin_alt": 100.0,
        "x0": 0.0, "x1": 256.0, "z0": 0.0, "z1": 256.0,
        "dtm": {"cell": 1.0, "file": "dtm_1m.npy"},
        "obstacle": {"cell": 1.0, "file": "obstacle.npy"},
        "spawn": {"x": 20.0, "z": 20.0, "yaw_deg": 0.0},
        "s300": {"x": 30.0, "z": 30.0, "yaw_deg": 180.0},
        "tiles": [], "surround": [],
    }
    (tmp_path / "scene.json").write_text(json.dumps(meta), encoding="utf-8")
    return tmp_path


def test_crater_decapitates_a_summit(peak_scene):
    """Cut-to-target contract: a crater centered on a summit removes
    the top by the full crater depth (not a draped relative dent), the
    cut never FILLS terrain, and the far field stays untouched."""
    sc = CinematicScene(str(peak_scene))
    summit = sc.ground_h(128.0, 128.0)
    assert summit == pytest.approx(130.0, abs=0.5)
    slope_before = sc.ground_h(160.0, 128.0)      # r=32: mid-slope
    far_before = sc.ground_h(20.0, 20.0)          # valley floor
    sc.add_crater(128.0, 128.0, radius_m=80.0, depth_m=35.0)
    # Summit: cut to gz_h - depth (two-sided: not less, not more).
    assert sc.ground_h(128.0, 128.0) == pytest.approx(summit - 35.0,
                                                      abs=0.5)
    # Mid-slope sits far below the bowl's target surface: cut-only
    # means it is never raised toward it (lip ejecta < 8 m allowed).
    slope_after = sc.ground_h(160.0, 128.0)
    assert slope_after <= slope_before + 0.22 * 35.0 + 0.5
    assert slope_after >= slope_before - 0.5      # and no cut out here
    # Far field: bit-identical.
    assert sc.ground_h(20.0, 20.0) == pytest.approx(far_before, abs=1e-6)


def test_nuclear_crater_dims_scale():
    """Fireball-anchored sizing: 300 kt ~ 360 m radius, 1 Mt ~ 590 m,
    monotonic in yield, depth locked to radius/2.5 (two-sided so the
    spectacle can't quietly shrink OR explode past realism)."""
    from world.cinematic_scene import nuclear_crater_dims
    r300, d300 = nuclear_crater_dims(300.0)
    r1000, d1000 = nuclear_crater_dims(1000.0)
    assert 320.0 < r300 < 400.0
    assert 550.0 < r1000 < 630.0
    assert r300 < r1000
    assert d300 == pytest.approx(r300 / 2.5)
    assert d1000 == pytest.approx(r1000 / 2.5)


def test_halo_axes_match_stored_dsm_grids(flat_scene):
    """Regression (2026-07-17 crash): the renderer's crater-delta grid
    must be the SAME shape as the stored haloed DSMs.  A 1 km tile
    stores (503, 503) at 2 m, (253, 253) at 4 m, (53, 53) at 20 m —
    the old n+2 axes produced 252 and broadcast-crashed _apply_craters
    the moment a crater touched a fine tile."""
    for cell, want in ((2.0, 503), (4.0, 253), (20.0, 53)):
        xs, zs = halo_axes(3000.0, -1000.0, 1000.0, cell)
        assert len(xs) == want and len(zs) == want
        # Two-sided: exactly one halo cell each side, not zero, not two.
        assert xs[0] == pytest.approx(3000.0 - cell)
        assert xs[-1] == pytest.approx(3000.0 + 1000.0 + cell)
        assert zs[0] == pytest.approx(-1000.0 - cell)
        assert zs[-1] == pytest.approx(-1000.0 + 1000.0 + cell)
    # And the delta grid built on those axes broadcasts onto the DSM.
    sc = CinematicScene(str(flat_scene))
    sc.add_crater(128.0, 128.0, radius_m=40.0, depth_m=15.0)
    xs, zs = halo_axes(0.0, 0.0, 256.0, 4.0)
    dsm_like = np.full((len(zs), len(xs)), 10.0, np.float32)
    summed = dsm_like + sc.crater_delta_grid(xs, zs, dsm_like)
    assert summed.shape == dsm_like.shape
    assert summed.min() < 0.0            # the bowl actually landed
