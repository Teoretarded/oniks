"""ICBM model + silo-survey contracts (research doc checklists 1.6/2.6).

GL-free: meshes are numpy MeshData; the survey runs on synthetic arrays.
"""

from __future__ import annotations

import numpy as np

from models.icbm import (
    LF_DOOR_OPEN_DZ,
    LF_TUBE_R,
    MM3_LEN,
    MM3_R1,
    SAR_LEN,
    SAR_R,
    SAR_TPK_R,
    SAR_TUBE_R,
    build_minuteman_iii,
    build_minuteman_lf,
    build_minuteman_lf_door,
    build_sarmat,
    build_sarmat_silo,
    build_sarmat_silo_lid,
)
from world.cinematic_scene import survey_silo_candidates


def test_minuteman_iii_proportions():
    md = build_minuteman_iii()
    v = md.vertices
    assert len(v) and len(md.indices) % 3 == 0
    zmin, zmax = float(v[:, 2].min()), float(v[:, 2].max())
    assert abs((zmax - zmin) - MM3_LEN) < 0.05          # 18.3 m stack
    r = np.hypot(v[:, 0], v[:, 1]).max()
    assert MM3_R1 <= r <= MM3_R1 + 0.35                 # 1.68 m class body


def test_sarmat_proportions_dwarf_the_minuteman():
    md = build_sarmat()
    v = md.vertices
    zmin, zmax = float(v[:, 2].min()), float(v[:, 2].max())
    assert abs((zmax - zmin) - SAR_LEN) < 0.05          # 35.3 m
    r = np.hypot(v[:, 0], v[:, 1]).max()
    assert SAR_R <= r <= SAR_R + 0.1
    # Checklist 2.6-1: freight train vs pencil.
    assert SAR_LEN / MM3_LEN > 1.9
    assert SAR_R / MM3_R1 > 1.7


def test_silo_tubes_swallow_their_missiles():
    # Checklist 1.6-10: the 3.66 m tube swallows the 1.68 m airframe.
    assert LF_TUBE_R >= MM3_R1 * 2.0
    # Sarmat rides in a TPK that itself sits in a ~6 m class tube.
    assert SAR_TPK_R > SAR_R
    assert SAR_TUBE_R > SAR_TPK_R * 1.5


def test_silo_builders_and_doors_nonempty_and_deterministic():
    for fn in (build_minuteman_lf, build_minuteman_lf_door,
               build_sarmat_silo, build_sarmat_silo_lid,
               build_minuteman_iii, build_sarmat):
        a, b = fn(), fn()
        assert len(a.vertices) > 0
        assert np.array_equal(a.vertices, b.vertices)
        assert np.array_equal(a.indices, b.indices)
    assert LF_DOOR_OPEN_DZ > 7.0     # the slab clears the 3.66 m mouth


# ---------------------------------------------------------------- the survey

def _valley(n=512, cell=8.0):
    """Synthetic scene: flat floor strip |x-2048| < 700, walls beyond."""
    xs = np.arange(n) * cell
    gx = np.broadcast_to(xs[None, :], (n, n))
    d = np.maximum(0.0, (np.abs(gx - 2048.0) - 700.0) * 0.6)
    return d.astype(np.float32)


def test_survey_prefers_flat_floor_at_watching_distance():
    dtm = _valley()
    obstacle = np.zeros_like(dtm, dtype=np.uint8)
    spawn = (2048.0, 2048.0)
    avoid = (2048.0, 3300.0)         # pretend S-300 pad up-valley
    cands = survey_silo_candidates(dtm, obstacle, 8.0, 0.0, 0.0,
                                   spawn, avoid_xz=avoid)
    assert cands
    _s, x, z = cands[0]
    assert abs(x - 2048.0) < 700.0                   # on the floor
    dist = np.hypot(x - spawn[0], z - spawn[1])
    assert 1200.0 <= dist <= 3200.0                  # visible, not close
    assert np.hypot(x - avoid[0], z - avoid[1]) >= 250.0


def test_survey_rejects_obstacles_and_stays_deterministic():
    dtm = _valley()
    obstacle = np.zeros_like(dtm, dtype=np.uint8)
    # Forest over the whole south half of the floor.
    obstacle[:256, :] = 1
    spawn = (2048.0, 2048.0)
    c1 = survey_silo_candidates(dtm, obstacle, 8.0, 0.0, 0.0, spawn)
    c2 = survey_silo_candidates(dtm, obstacle, 8.0, 0.0, 0.0, spawn)
    assert c1 == c2 and c1
    _s, x, z = c1[0]
    assert z > 256 * 8.0 - 40.0      # never inside the forest half
