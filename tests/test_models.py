"""Model builder tests: every builder returns a finite mesh with unit normals;
key real-world dimensions are enforced (GL-free; builders use engine.meshdata)."""

import numpy as np

from models.bastion import build_bastion_tel
from models.common import PALETTE
from models.oniks import build_oniks, build_oniks_booster


def _check(md):
    assert md.vertices.dtype == np.float32 and md.indices.dtype == np.uint32
    assert md.indices.max() < len(md.vertices)
    assert np.isfinite(md.vertices).all()
    n = md.vertices[:, 3:6]
    assert np.allclose(np.linalg.norm(n, axis=1), 1.0, atol=1e-3)


def test_all_builders_finite_unit_normals():
    for md in (build_oniks(), build_oniks_booster(),
               build_bastion_tel(elevation_deg=0.0),
               build_bastion_tel(elevation_deg=88.0)):
        _check(md)


def test_oniks_dimensions():
    md = build_oniks()
    z = md.vertices[:, 2]
    # 8.9 m long within 1 cm, mid-body origin (nose at +4.45)
    assert abs((z.max() - z.min()) - 8.9) <= 0.01
    assert abs(z.max() - 4.45) <= 0.01
    # body diameter 0.67 m: body-colored lathe stays within r 0.34
    body = np.all(np.isclose(md.vertices[:, 6:9], PALETTE["missile_body"],
                             atol=1e-4), axis=1)
    assert body.any()
    r = np.linalg.norm(md.vertices[body, 0:2], axis=1)
    assert r.max() <= 0.34


def test_booster_dimensions():
    md = build_oniks_booster()
    r = np.linalg.norm(md.vertices[:, 0:2], axis=1)
    assert abs(r.max() - 0.30) <= 0.01


def test_tel_fits_box_when_elevated():
    md = build_bastion_tel(elevation_deg=88.0)
    p = md.vertices[:, 0:3]
    ext = p.max(axis=0) - p.min(axis=0)
    assert ext[0] <= 4.0    # width (east-west)
    assert ext[1] <= 10.0   # height with canisters raised
    assert ext[2] <= 13.0   # length (north-south)
    assert p[:, 1].min() >= -0.01  # nothing below the ground plane


def test_tel_elevation_raises_canisters():
    stowed = build_bastion_tel(elevation_deg=0.0)
    raised = build_bastion_tel(elevation_deg=88.0)
    assert raised.vertices[:, 1].max() > stowed.vertices[:, 1].max() + 4.0
