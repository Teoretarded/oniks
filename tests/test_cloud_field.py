"""GL-free V2 weather/cloud-field contracts."""

import inspect

import numpy as np

from sim.atmosphere import (
    CONVECTIVE_DOMAIN_M, CloudMorphology, ConvectiveKind,
    WEATHER_PRESET_NAMES, build_control_fields, build_storm_cells,
    build_supercells, cloud_style, state_for_preset, vertical_profile,
    weather_preset, weather_recipe_key,
)
from game.weather_composer import compose_custom_weather, custom_recipe_digest
from world.cloud_field import (
    CIRRUS_N, DENSITY_TILE_M, FIELD_CACHE_VERSION, LOWER_SHAPE,
    OCCUPANCY_BLOCK, STORM_OCCUPANCY_BLOCK, STORM_SHAPE, UPPER_SHAPE,
    build_cloud_field, build_occupancy, cache_path,
)


def _custom(low="off", mid="off", high="off", convective="off"):
    return compose_custom_weather({
        "cloud_custom_low": low,
        "cloud_custom_mid": mid,
        "cloud_custom_high": high,
        "cloud_custom_convective": convective,
    })


def _assert_field_arrays(field):
    expected = {
        "lower_density": LOWER_SHAPE,
        "upper_density": UPPER_SHAPE,
        "storm_density": STORM_SHAPE,
        "lower_occupancy": tuple(n // OCCUPANCY_BLOCK for n in LOWER_SHAPE),
        "upper_occupancy": tuple(n // OCCUPANCY_BLOCK for n in UPPER_SHAPE),
        "storm_occupancy": tuple(
            n // STORM_OCCUPANCY_BLOCK for n in STORM_SHAPE),
        "cirrus": (CIRRUS_N, CIRRUS_N, 2),
        "shadow": (CIRRUS_N, CIRRUS_N),
    }
    for name, shape in expected.items():
        arr = getattr(field, name)
        assert arr.shape == shape
        assert arr.dtype == np.uint8


def test_preset_table_and_static_state():
    assert WEATHER_PRESET_NAMES == (
        "CLEAR", "FAIR", "PARTLY CLOUDY", "OVERCAST", "HIGH CIRRUS",
        "TOWERING CUMULUS", "THUNDERSTORM",
    )
    assert weather_preset("partly_cloudy").preset_id == 2
    fair = state_for_preset(1)
    assert fair.precip_mmh == 0.0
    assert fair.density_scale == 0.0  # default weather is physics-neutral
    high = state_for_preset(4)
    assert high.coverage > 0.0 and high.cloud_base_m > 9_000.0
    storm = state_for_preset(6)
    assert storm.cloud_top_m == 20_700.0
    assert storm.precip_mmh > 0.0 and storm.storm == 1.0


def test_profiles_are_bounded_and_distinct():
    h = np.linspace(-0.2, 1.2, 101, dtype=np.float32)
    profiles = [vertical_profile(h, kind) for kind in CloudMorphology]
    for profile in profiles:
        assert profile.dtype == np.float32
        assert np.all((profile >= 0.0) & (profile <= 1.0))
        assert profile[0] == 0.0 and profile[-1] == 0.0
    assert not np.array_equal(profiles[0], profiles[1])
    assert profiles[2][70] > profiles[1][70]  # towering survives higher


def test_controls_and_storm_cells_are_component_deterministic():
    a = build_control_fields(42, 64)
    b = build_control_fields(42, 64)
    c = build_control_fields(43, 64)
    for name in ("mass", "puff", "strata", "tower", "warp", "base",
                 "height", "shear", "cirrus"):
        aa, bb, cc = getattr(a, name), getattr(b, name), getattr(c, name)
        assert np.array_equal(aa, bb)
        assert not np.array_equal(aa, cc)
        assert aa.dtype == np.float32
        assert 0.0 <= float(aa.min()) <= float(aa.max()) <= 1.0
    # Legacy ambient cells and the independent convective field have separate
    # streams. Thunderstorm no longer stamps its towers into ambient layers.
    partly = build_storm_cells(42, 2)
    assert partly == build_storm_cells(42, 2)
    assert partly != build_storm_cells(43, 2)
    assert build_storm_cells(42, 6) == ()
    thunder = build_supercells(42, 6)
    assert thunder == build_supercells(42, 6)
    assert thunder != build_supercells(43, 6)
    assert all(cell.kind == ConvectiveKind.SUPERCELL for cell in thunder)


def test_supercells_are_unique_across_the_800km_domain():
    assert CONVECTIVE_DOMAIN_M == 800_000.0
    recipe = _custom(convective="storm line")
    cells = build_supercells(42, recipe)
    assert recipe.supercells.count_range[0] <= len(cells) \
        <= recipe.supercells.count_range[1]
    assert len({(cell.x, cell.z) for cell in cells}) == len(cells)
    assert all(0.0 <= cell.x * CONVECTIVE_DOMAIN_M < CONVECTIVE_DOMAIN_M
               and 0.0 <= cell.z * CONVECTIVE_DOMAIN_M < CONVECTIVE_DOMAIN_M
               for cell in cells)
    for attr in ("top_m", "core_radius_m", "anvil_spread", "tilt_m"):
        values = [getattr(cell, attr) for cell in cells]
        assert len(set(values)) == len(values)
    assert all(cell.top_m > cell.base_m for cell in cells)
    assert all(cell.anvil_spread > 1.0 for cell in cells)


def test_seeded_supercell_phenotypes_are_repeatable_and_varied():
    same = build_supercells(7, "thunderstorm")
    assert same == build_supercells(7, "thunderstorm")
    assert all(0 <= cell.variant < 4 for cell in same)
    observed = {
        cell.variant
        for seed in range(12)
        for cell in build_supercells(seed, "thunderstorm")
    }
    assert observed == {0, 1, 2, 3}


def test_macro_geography_is_large_and_not_quadrant_tiled():
    assert DENSITY_TILE_M >= 180_000.0
    controls = build_control_fields(7, 128)
    for name in ("mass", "puff", "strata", "tower", "warp", "base",
                 "height", "shear", "cirrus"):
        field = getattr(controls, name)
        assert not np.array_equal(field[:64, :64], field[:64, 64:])
        assert not np.array_equal(field[:64, :64], field[64:, :64])
    assert cloud_style(7) != cloud_style(8)


def test_field_shapes_ranges_and_seed_determinism():
    a = build_cloud_field(7, "fair", cache_dir=None)
    b = build_cloud_field(7, "fair", cache_dir=None)
    c = build_cloud_field(8, "fair", cache_dir=None)
    _assert_field_arrays(a)
    for name in ("lower_density", "upper_density", "lower_occupancy",
                 "upper_occupancy", "storm_density", "storm_occupancy",
                 "cirrus", "shadow"):
        assert np.array_equal(getattr(a, name), getattr(b, name))
    assert not np.array_equal(a.lower_density, c.lower_density)
    assert int(a.lower_density.max()) > 0
    assert int(a.shadow.max()) > 0
    assert (a.lower_occupancy > 0).mean() < 0.90  # honest empty-space benefit

    # Cloud bottoms and ceilings vary across columns and across seeds; the
    # nominal layer bounds are only a containing slab, never a flat shape.
    active = a.lower_density > 0
    columns = active.any(axis=0)
    bases = np.argmax(active, axis=0)[columns]
    tops = (active.shape[0] - np.argmax(active[::-1], axis=0))[columns]
    assert np.ptp(bases) >= 5
    assert np.ptp(tops) >= 16
    active_c = c.lower_density > 0
    columns_c = active_c.any(axis=0)
    seed_bases = np.where(columns, np.argmax(active, axis=0), -1)
    other_bases = np.where(columns_c, np.argmax(active_c, axis=0), -1)
    seed_tops = np.where(
        columns, active.shape[0] - np.argmax(active[::-1], axis=0), -1)
    other_tops = np.where(
        columns_c, active_c.shape[0] - np.argmax(active_c[::-1], axis=0), -1)
    assert not np.array_equal(seed_bases, other_bases)
    assert not np.array_equal(seed_tops, other_tops)


def test_mixed_weather_has_genuinely_separate_altitude_bands():
    field = build_cloud_field(17, "partly cloudy", cache_dir=None)
    assert field.lower_density.any() and field.upper_density.any()

    def peak_altitude(density, base, top):
        profile = density.mean(axis=(1, 2))
        index = int(np.argmax(profile))
        return base + (index + 0.5) / len(profile) * (top - base)

    lower_peak = peak_altitude(field.lower_density, field.lower_base_m,
                               field.lower_top_m)
    upper_peak = peak_altitude(field.upper_density, field.upper_base_m,
                               field.upper_top_m)
    assert upper_peak - lower_peak > 1_500.0


def test_custom_recipe_can_mix_low_mid_high_and_supercells():
    recipe = _custom("broken", "scattered", "wispy", "supercell")
    field = build_cloud_field(17, recipe, cache_dir=None)
    _assert_field_arrays(field)
    assert field.lower_density.any()
    assert field.upper_density.any()
    assert field.cirrus.any()
    assert field.storm_density.any()
    assert field.recipe_key == weather_recipe_key(recipe)
    assert field.recipe_key == custom_recipe_digest({
        "cloud_custom_low": "broken",
        "cloud_custom_mid": "scattered",
        "cloud_custom_high": "wispy",
        "cloud_custom_convective": "supercell",
    })
    assert field.storm_base_m < field.storm_top_m
    assert field.storm_top_m > field.upper_top_m


def test_recipe_components_do_not_reshuffle_other_baked_fields():
    ambient = _custom("broken", "massive", "dense", "off")
    stormy = _custom("broken", "massive", "dense", "supercell")
    a = build_cloud_field(29, ambient, cache_dir=None)
    b = build_cloud_field(29, stormy, cache_dir=None)
    for name in ("lower_density", "upper_density", "cirrus"):
        assert np.array_equal(getattr(a, name), getattr(b, name))
    assert not a.storm_density.any()
    assert b.storm_density.any()

    no_high = _custom("broken", "massive", "off", "supercell")
    c = build_cloud_field(29, no_high, cache_dir=None)
    for name in ("lower_density", "upper_density", "storm_density"):
        assert np.array_equal(getattr(b, name), getattr(c, name))
    assert not c.cirrus.any()


def test_clear_and_high_cirrus_are_isolated_from_volumetric_layers():
    clear = build_cloud_field(11, "clear", cache_dir=None)
    high = build_cloud_field(11, "high cirrus", cache_dir=None)
    for field in (clear, high):
        assert not field.lower_density.any()
        assert not field.upper_density.any()
        assert not field.storm_density.any()
        assert not field.lower_occupancy.any()
        assert not field.upper_occupancy.any()
        assert not field.storm_occupancy.any()
    assert not clear.cirrus.any() and not clear.shadow.any()
    assert high.cirrus[..., 0].max() > 0
    assert high.shadow.max() > 0


def test_cirrus_direction_and_texture_are_seed_unique():
    a = build_cloud_field(7, "high cirrus", cache_dir=None)
    b = build_cloud_field(8, "high cirrus", cache_dir=None)
    ca = a.cirrus[..., 0].astype(np.float32).ravel()
    cb = b.cirrus[..., 0].astype(np.float32).ravel()
    assert cloud_style(7).cirrus_wave != cloud_style(8).cirrus_wave
    assert abs(float(ca.mean()) - float(cb.mean())) < 8.0
    assert float(np.corrcoef(ca, cb)[0, 1]) < 0.50


def test_thunderstorm_uses_an_independent_convective_volume():
    field = build_cloud_field(19, "thunderstorm", cache_dir=None)
    assert field.lower_density.any() and field.upper_density.any()
    assert field.storm_density.any() and field.storm_occupancy.any()
    assert field.storm_density.shape != field.lower_density.shape
    assert field.storm_top_m > field.upper_top_m
    assert build_storm_cells(19, "thunderstorm") == ()
    assert build_supercells(19, "thunderstorm")


def test_occupancy_is_conservative_and_periodically_dilated():
    field = build_cloud_field(23, "partly cloudy", cache_dir=None)
    for density, occupancy in (
        (field.lower_density, field.lower_occupancy),
        (field.upper_density, field.upper_occupancy),
        (field.storm_density, field.storm_occupancy),
    ):
        b = (STORM_OCCUPANCY_BLOCK if density.shape == STORM_SHAPE
             else OCCUPANCY_BLOCK)
        pooled = density.reshape(
            density.shape[0] // b, b, density.shape[1] // b, b,
            density.shape[2] // b, b).max(axis=(1, 3, 5)) > 0
        assert np.all(occupancy[pooled] == 255)

    # A cloud touching x=0 must occupy the wrapped neighbor cell too, so
    # trilinear support at the repeat seam can never be skipped.
    density = np.zeros((8, 8, 8), dtype=np.uint8)
    density[4, 4, 0] = 255
    occupancy = build_occupancy(density, block=2)
    assert occupancy[2, 2, 0] == 255
    assert occupancy[2, 2, -1] == 255


def test_cache_roundtrip_and_corruption_regeneration(tmp_path):
    first = build_cloud_field(31, 5, cache_dir=tmp_path)
    path = cache_path(tmp_path, 31, 5)
    assert path.name == f"cloudfield_{FIELD_CACHE_VERSION}_seed31_p5.npz"
    assert path.exists()
    second = build_cloud_field(31, 5, cache_dir=tmp_path)
    assert np.array_equal(first.upper_density, second.upper_density)
    assert np.array_equal(first.storm_density, second.storm_density)

    path.write_bytes(b"not an npz")
    rebuilt = build_cloud_field(31, 5, cache_dir=tmp_path)
    assert np.array_equal(first.upper_density, rebuilt.upper_density)
    with np.load(path, allow_pickle=False) as z:
        assert z["cache_version"].item() == FIELD_CACHE_VERSION


def test_custom_recipe_digest_prevents_cache_collisions(tmp_path):
    wispy = _custom(high="wispy")
    dense = _custom(high="dense")
    wispy_path = cache_path(tmp_path, 31, wispy)
    dense_path = cache_path(tmp_path, 31, dense)
    assert wispy_path != dense_path
    assert weather_recipe_key(wispy) in wispy_path.name
    assert weather_recipe_key(dense) in dense_path.name
    a = build_cloud_field(31, wispy, cache_dir=tmp_path)
    b = build_cloud_field(31, dense, cache_dir=tmp_path)
    assert wispy_path.exists() and dense_path.exists()
    assert a.recipe_key != b.recipe_key
    assert not np.array_equal(a.cirrus, b.cirrus)


def test_density_bake_has_no_camera_input():
    params = inspect.signature(build_cloud_field).parameters
    assert set(params) == {"seed", "preset", "cache_dir"}
