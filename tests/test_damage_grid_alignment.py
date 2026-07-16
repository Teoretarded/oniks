"""Model-to-subsystem alignment contracts for rebuilt surface assets."""

from types import SimpleNamespace

import numpy as np
import pytest

import sim.damage_model as dm
from sim.amphibious import LCAC_DRAFT_M, Lcac


def _hull(ship_type="carrier", *, length=333.0, beam=40.0, height=30.0,
          draft=5.0):
    return SimpleNamespace(
        ship_type=ship_type,
        length=length,
        beam=beam,
        height=height,
        draft=draft,
    )


def _named(grid, name):
    return next(row for row in grid if row[0] == name)


def test_legacy_and_offset_rows_share_one_geometry_api():
    legacy = ("centered", 0.2, 0.4, -0.5, 0.5, 0.25, "c2")
    offset = ("starboard", 0.2, 0.4, -0.5, 0.5, 0.70, 0.20, "c2")

    assert dm._box_contains(legacy, 0.3, 0.0, 0.0)
    assert not dm._box_contains(legacy, 0.3, 0.0, 0.4)
    assert dm._box_contains(offset, 0.3, 0.0, 0.70)
    assert not dm._box_contains(offset, 0.3, 0.0, 0.0)


def test_nimitz_island_box_matches_rebuilt_starboard_geometry():
    island = _named(dm.NIMITZ_GRID, "island")
    center, half = dm._box_local_m(_hull(), island)

    assert island[1:3] == pytest.approx((0.497, 0.587))
    assert island[3:5] == pytest.approx((0.24, 1.40))
    assert center[0] == pytest.approx(27.5)
    assert half[0] == pytest.approx(8.0)
    assert dm._box_contains(island, 0.542, 0.8, 1.375)
    assert not dm._box_contains(island, 0.542, 0.8, 0.0)
    # Existing hitcam code still receives its historical seven-field shape.
    assert len(dm._hitcam_row(island)) == 7


def test_nimitz_hangar_stays_below_the_flight_deck_in_new_vertical_frame():
    hangar = _named(dm.NIMITZ_GRID, "hangar")
    assert hangar[3:5] == pytest.approx((0.00, 0.24))


def test_nimitz_magazine_names_follow_stern_to_bow_grid_axis():
    aft = _named(dm.NIMITZ_GRID, "magazine_aft")
    fwd = _named(dm.NIMITZ_GRID, "magazine_fwd")
    assert aft[1:3] == (0.30, 0.45)
    assert fwd[1:3] == (0.65, 0.75)


def test_burke_vls_fields_match_rebuilt_mesh_positions():
    aft = _named(dm.BURKE_GRID, "vls_aft_64")
    fwd = _named(dm.BURKE_GRID, "vls_fwd_32")
    assert aft[1:3] == pytest.approx((0.305, 0.347))
    assert fwd[1:3] == pytest.approx((0.737, 0.779))
    assert aft[3] > 0.0 and fwd[3] > 0.0  # cells sit on the visible deck


def test_burke_sensor_and_c2_boxes_contain_rebuilt_model_landmarks():
    """Cross-module contract for the procedural Burke's visible equipment."""
    hull = _hull(ship_type="destroyer", length=155.0, beam=20.0,
                 height=30.0, draft=6.0)
    hull.damage_height = 39.427433

    def grid_point(x_m, y_m, z_m):
        return (
            (z_m + hull.length * 0.5) / hull.length,
            y_m * dm.Y_TOP_FRAC / hull.damage_height,
            x_m / (hull.beam * 0.5),
        )

    panel_offset = 10.3 * np.sin(np.pi * 0.25)
    landmarks = {
        # SPY panel centres from models.destroyer._superstructure.
        "spy_aft": grid_point(7.28, 12.20, 10.0 - panel_offset),
        "spy_fwd": grid_point(7.28, 12.20, 10.0 + panel_offset),
        # Forward bridge glazing, mast trunk, and CIC/deckhouse interior.
        "bridge": grid_point(6.0, 14.65, 24.0),
        "mast": grid_point(0.0, 35.0, 14.0),
        "cic": grid_point(0.0, 8.0, 10.0),
    }
    for name, point in landmarks.items():
        assert dm._box_contains(_named(dm.BURKE_GRID, name), *point), name


def test_tico_grid_matches_rebuilt_flagship_equipment():
    aft_vls = _named(dm.TICO_GRID, "vls_aft_61")
    fwd_vls = _named(dm.TICO_GRID, "vls_fwd_61")
    spy_fwd = _named(dm.TICO_GRID, "spy_fwd")
    spy_aft = _named(dm.TICO_GRID, "spy_aft")

    assert aft_vls[1:3] == pytest.approx((0.190, 0.232))
    assert fwd_vls[1:3] == pytest.approx((0.789, 0.830))
    assert aft_vls[3:5] == pytest.approx((0.30, 0.37))
    assert fwd_vls[3:5] == pytest.approx((0.30, 0.37))
    assert np.mean(spy_fwd[1:3]) == pytest.approx(0.645)
    assert np.mean(spy_aft[1:3]) == pytest.approx(0.355)
    assert {"mast_fwd", "mast_aft", "hangar"} <= {
        row[0] for row in dm.TICO_GRID
    }


@pytest.mark.parametrize(
    ("ship_type", "expected_name"),
    [
        ("cargo", "cargo_holds"),
        ("tanker", "cargo_tanks"),
        ("warship", "frigate_vls_32"),
        ("transport", "well_deck"),
        ("lcac", "lcac_cushion"),
    ],
)
def test_surface_ship_types_have_distinct_module_grids(ship_type,
                                                        expected_name):
    ship = SimpleNamespace(ship_type=ship_type)
    names = {row[0] for row in dm.grid_for(ship)}
    assert expected_name in names


def test_grid_presence_does_not_make_merchants_warships():
    assert dm.DamageState(SimpleNamespace(ship_type="cargo")).n_comp \
        == dm.MERCHANT_COMPARTMENTS
    assert dm.DamageState(SimpleNamespace(ship_type="lcac")).n_comp \
        == dm.MERCHANT_COMPARTMENTS
    assert dm.DamageState(SimpleNamespace(ship_type="warship")).n_comp \
        == dm.N_COMPARTMENTS


def test_per_ship_draft_controls_vertical_grid_mapping():
    hull = _hull(ship_type="lcac", length=27.0, beam=14.0, height=4.0,
                 draft=1.0)
    waterline_local_y = -(hull.height - hull.draft) * 0.5
    assert dm.local_to_grid(hull, np.array([0.0, waterline_local_y, 0.0]))[1] \
        == pytest.approx(0.0)
    keel_local_y = waterline_local_y - hull.draft
    assert dm.local_to_grid(hull, np.array([0.0, keel_local_y, 0.0]))[1] \
        == pytest.approx(-1.0)


def test_lcac_owns_shallow_per_instance_draft():
    craft = Lcac("lcac_probe", (0.0, 100.0), (0.0, 0.0))
    assert craft.draft == LCAC_DRAFT_M == 1.0
    expected = np.sqrt(
        (craft.beam * 0.5) ** 2
        + craft.collision_height ** 2
        + (craft.length * 0.5) ** 2)
    assert craft.hit_reach == pytest.approx(expected)
    center, half, _rot = craft.obb()
    assert center[1] - half[1] == pytest.approx(-LCAC_DRAFT_M)
    assert center[1] + half[1] == pytest.approx(craft.collision_height)
