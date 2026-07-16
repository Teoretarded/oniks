"""GL-free catalog, geometry metadata, and testing-feedback bundles."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
from pathlib import Path

import numpy as np
import pytest

from engine.meshdata import make_box
from game.testing_catalog import (
    CATEGORIES,
    TEST_ASSETS,
    TestAsset,
    filter_assets,
    get_asset,
    load_mesh_data,
    mesh_metadata,
    write_testing_feedback,
)


def test_catalog_ids_categories_and_entries_are_stable_and_immutable():
    ids = [asset.id for asset in TEST_ASSETS]
    assert len(ids) == len(set(ids))
    assert CATEGORIES == (
        "ALL", "GROUND", "STRUCTURES", "AIRCRAFT", "SHIPS",
        "MISSILES", "WEATHER",
    )
    assert all(asset.category in CATEGORIES[1:] for asset in TEST_ASSETS)
    assert all(asset.builder_ref.count(":") == 1 for asset in TEST_ASSETS)

    oniks = get_asset("  ONIKS  ")
    assert isinstance(oniks, TestAsset)
    with pytest.raises(FrozenInstanceError):
        oniks.label = "renamed"


def test_representative_assets_and_all_seven_weather_presets_exist():
    assert get_asset("oniks").category == "MISSILES"
    assert get_asset("carrier").builder_ref == "models.carrier:build_carrier"
    thunder = get_asset("thunderstorm")
    assert thunder.kind == "weather"
    assert thunder.preset_id == 6

    weather = [asset for asset in TEST_ASSETS if asset.category == "WEATHER"]
    assert [(asset.id, asset.preset_id) for asset in weather] == [
        ("clear", 0),
        ("fair", 1),
        ("partly_cloudy", 2),
        ("overcast", 3),
        ("high_cirrus", 4),
        ("towering_cumulus", 5),
        ("thunderstorm", 6),
    ]


def test_every_catalog_mesh_builder_loads_nonempty_meshdata():
    meshes = [asset for asset in TEST_ASSETS if asset.kind == "mesh"]
    assert len(meshes) == 51
    for asset in meshes:
        md = load_mesh_data(asset)
        stats = mesh_metadata(md)
        assert md.vertices.shape[1] == 9, asset.id
        assert stats["vertices"] > 0, asset.id
        assert stats["triangles"] > 0, asset.id
        assert stats["radius"] > 0.0, asset.id


def test_filter_assets_handles_category_query_tags_and_validation():
    ships = filter_assets("ships")
    assert {asset.id for asset in ships} == {
        "cargo", "tanker", "warship", "destroyer", "flagship", "carrier",
        "transport", "lcac", "submarine",
    }
    assert [asset.id for asset in filter_assets(query="supercell lightning")] == [
        "thunderstorm"
    ]
    assert get_asset("oniks_capped") in filter_assets("MISSILES", "launch variant")
    assert filter_assets("AIRCRAFT", "early warning") == (get_asset("awacs"),)

    with pytest.raises(ValueError, match="category"):
        filter_assets("NOT-A-CATEGORY")
    with pytest.raises(KeyError, match="unknown testing asset"):
        get_asset("not_real")
    with pytest.raises(TypeError, match="not a mesh"):
        load_mesh_data("thunderstorm")


def test_gameplay_aliases_are_explicit_searchable_proxies():
    expected = {
        "kalibr": "tomahawk",
        "buk_9m317": "48n6",
        "buk_9m338": "57e6",
        "asbm": "40n6",
        "swarm_loiterer": "aim9x",
    }
    for asset_id, target in expected.items():
        asset = get_asset(asset_id)
        assert asset.proxy_for == target
        assert "(PROXY)" in asset.label
        assert asset in filter_assets(asset.category, f"proxy for {target}")
        assert mesh_metadata(load_mesh_data(asset))["triangles"] > 0

    assert {asset.id for asset in filter_assets(query="PROXY")} == set(expected)


def test_mesh_metadata_reports_exact_bbox_center_dimensions_and_counts():
    md = make_box((2.0, 4.0, 6.0), (1.0, 1.0, 1.0),
                  offset=(3.0, -2.0, 5.0))
    stats = mesh_metadata(md)
    assert stats["bbox_min"] == pytest.approx((2.0, -4.0, 2.0))
    assert stats["bbox_max"] == pytest.approx((4.0, 0.0, 8.0))
    assert stats["dimensions"] == pytest.approx((2.0, 4.0, 6.0))
    assert stats["center"] == pytest.approx((3.0, -2.0, 5.0))
    assert stats["radius"] == pytest.approx(np.sqrt(14.0))
    assert stats["vertices"] == 24
    assert stats["triangles"] == 12


def test_mesh_metadata_rejects_empty_or_nonfinite_geometry():
    empty = type("Mesh", (), {
        "vertices": np.empty((0, 9), dtype=np.float32),
        "indices": np.empty(0, dtype=np.uint32),
    })()
    with pytest.raises(ValueError, match="no vertices"):
        mesh_metadata(empty)

    bad = make_box((1.0, 1.0, 1.0), (1.0, 1.0, 1.0))
    bad.vertices[0, 0] = np.nan
    with pytest.raises(ValueError, match="finite"):
        mesh_metadata(bad)


def _feedback_context():
    md = make_box((2.0, 4.0, 6.0), (1.0, 1.0, 1.0))
    return {
        "asset": get_asset("oniks"),
        "kind": "mesh",
        "category": "MISSILES",
        "seed": 42,
        "camera": {
            "eye": np.array([12.0, 4.0, -8.0]),
            "azimuth_deg": np.float32(135.0),
        },
        "mesh_stats": mesh_metadata(md),
        "note": "The folded wing clips through the canister.",
        "type": "visual bug",
        "screenshot_name": "../../unsafe folder/oniks shot.png",
        "timestamp": "2026-07-10T18:20:00+02:00",
        "commit": "abc1234",
        "details": {"variant": "tube exit"},
    }


def test_feedback_writer_numbers_bundles_and_records_sanitized_context(tmp_path):
    report1 = Path(write_testing_feedback(tmp_path, _feedback_context()))
    report2 = Path(write_testing_feedback(tmp_path, _feedback_context()))

    assert report1.parent.name == "feedback_001"
    assert report2.parent.name == "feedback_002"
    assert {path.name for path in report1.parent.iterdir()} == {
        "feedback.md", "context.json",
    }

    context = json.loads((report1.parent / "context.json").read_text("utf-8"))
    assert context["asset"] == "oniks"
    assert context["asset_label"] == "P-800 ONIKS"
    assert context["kind"] == "mesh"
    assert context["category"] == "MISSILES"
    assert context["seed"] == 42
    assert context["camera"]["eye"] == [12.0, 4.0, -8.0]
    assert context["mesh_stats"]["vertices"] == 24
    assert context["type"] == "visual_bug"
    assert context["screenshot_name"] == "oniks_shot.png"
    assert context["timestamp"] == "2026-07-10T18:20:00+02:00"
    assert context["commit"] == "abc1234"
    assert context["details"] == {"variant": "tube exit"}

    markdown = report1.read_text("utf-8")
    assert "P-800 ONIKS (`oniks`)" in markdown
    assert "The folded wing clips through the canister." in markdown
    assert "abc1234" in markdown
    assert "24 vertices / 12 triangles" in markdown


def test_feedback_writer_handles_weather_without_battle_or_mesh_fields(tmp_path):
    report = Path(write_testing_feedback(tmp_path, {
        "asset": "thunderstorm",
        "seed": 7,
        "camera": {"eye": [0.0, 2_000.0, 0.0]},
        "note": "Lightning repeats too quickly.",
        "type": "weather feedback",
        "screenshot": "storm.png",
    }))
    context = json.loads((report.parent / "context.json").read_text("utf-8"))
    assert context["asset"] == "thunderstorm"
    assert context["kind"] == "weather"
    assert context["category"] == "WEATHER"
    assert context["mesh_stats"] is None
    assert "tick" not in context
    assert "ledger" not in context
    assert "commands" not in context


def test_feedback_writer_rejects_spoofed_identity_and_nonfinite_camera(tmp_path):
    with pytest.raises(ValueError, match="does not match"):
        write_testing_feedback(tmp_path, {
            "asset": "carrier", "category": "MISSILES",
        })
    with pytest.raises(ValueError, match="non-finite"):
        write_testing_feedback(tmp_path, {
            "asset": "clear", "camera": {"azimuth": float("nan")},
        })
