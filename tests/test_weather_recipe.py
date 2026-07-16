"""GL-free contracts for composed weather recipes."""

from game.weather_composer import (CUSTOM_PREF_KEYS, compose_custom_weather,
                                   custom_recipe_digest)
from sim.atmosphere import ConvectiveKind, weather_recipe_key


def _selection(low="off", mid="off", high="off", convective="off"):
    return dict(zip(CUSTOM_PREF_KEYS, (low, mid, high, convective)))


def test_mixed_recipe_keeps_all_four_weather_components():
    selection = _selection("broken", "scattered", "wispy", "supercell")
    recipe = compose_custom_weather(selection)
    assert recipe.preset_id == 7 and recipe.name == "CUSTOM"
    assert recipe.lower.enabled and recipe.upper.enabled
    assert recipe.high.cirrus_coverage > 0.0
    assert recipe.supercells.enabled
    assert recipe.supercells.kind == ConvectiveKind.SUPERCELL
    assert recipe.precip_mmh > 0.0 and recipe.storm == 1.0


def test_recipe_digest_is_canonical_stable_and_order_independent():
    selection = _selection("deck", "broken", "dense", "storm line")
    reversed_selection = dict(reversed(tuple(selection.items())))
    digest = custom_recipe_digest(selection)
    assert digest == custom_recipe_digest(reversed_selection)
    assert digest == weather_recipe_key(compose_custom_weather(selection))
    assert digest.startswith("c") and len(digest) == 17


def test_changing_one_card_only_changes_its_recipe_component():
    base = compose_custom_weather(
        _selection("scattered", "broken", "wispy", "supercell"))

    high_changed = compose_custom_weather(
        _selection("scattered", "broken", "sheet", "supercell"))
    assert high_changed.lower == base.lower
    assert high_changed.upper == base.upper
    assert high_changed.supercells == base.supercells
    assert high_changed.high != base.high

    storm_changed = compose_custom_weather(
        _selection("scattered", "broken", "wispy", "storm line"))
    assert storm_changed.lower == base.lower
    assert storm_changed.upper == base.upper
    assert storm_changed.high == base.high
    assert storm_changed.supercells != base.supercells


def test_distinct_component_recipes_have_distinct_cache_keys():
    recipes = (
        _selection("scattered", "off", "off", "off"),
        _selection("off", "scattered", "off", "off"),
        _selection("off", "off", "wispy", "off"),
        _selection("off", "off", "off", "towering"),
    )
    keys = {custom_recipe_digest(recipe) for recipe in recipes}
    assert len(keys) == len(recipes)
