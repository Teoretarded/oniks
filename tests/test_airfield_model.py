"""Geometry contracts for the detailed procedural airfield."""

from __future__ import annotations

import numpy as np

from game.testing_catalog import mesh_metadata
from models.airfield import build_airfield


def test_airfield_keeps_true_scale_footprint_and_adds_operational_detail():
    mesh = build_airfield()
    stats = mesh_metadata(mesh)

    assert stats["dimensions"][2] == 2500.0
    assert 200.0 <= stats["dimensions"][0] <= 220.0
    assert 45.0 <= stats["dimensions"][1] <= 50.0
    assert stats["triangles"] > 2_000


def test_airfield_has_distinct_pavement_marking_and_guidance_materials():
    mesh = build_airfield()
    colors = np.unique(np.round(mesh.vertices[:, 6:9], 3), axis=0)
    expected = (
        (0.135, 0.145, 0.150),  # runway asphalt
        (0.880, 0.880, 0.820),  # white runway paint / lamps
        (0.860, 0.690, 0.120),  # taxiway guidance
        (0.100, 0.340, 0.720),  # taxi edge lamps
    )
    for color in expected:
        assert np.any(np.all(np.isclose(colors, color, atol=0.002), axis=1))


def test_threshold_and_centreline_paint_sits_above_runway_surface():
    mesh = build_airfield()
    vertices = mesh.vertices
    white = np.all(np.isclose(vertices[:, 6:9], (0.88, 0.88, 0.82),
                              atol=0.002), axis=1)
    paint = vertices[white]

    assert np.any((np.abs(paint[:, 2]) > 1200.0) & (paint[:, 1] > 0.36))
    assert np.any((np.abs(paint[:, 0]) < 1.0) & (paint[:, 1] > 0.36))
