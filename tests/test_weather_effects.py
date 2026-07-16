"""Pure contracts for deterministic weather presentation."""

import numpy as np
import pytest

from game.weather_effects import (PRESENTATION_TUNING, WEATHER_OVERLAY_FRAG,
                                  WeatherEffectsController, lightning_pulse)
from game.weather_composer import compose_custom_weather
from sim.atmosphere import CONVECTIVE_DOMAIN_M, WEATHER_PRESETS


def _under_first_cell(controller, altitude=100.0):
    cell = controller.storm_cells[0]
    return np.array([cell.x * CONVECTIVE_DOMAIN_M, altitude,
                     cell.z * CONVECTIVE_DOMAIN_M], dtype=np.float64)


def test_tuning_covers_every_preset_and_fair_is_exact_noop():
    assert len(PRESENTATION_TUNING) == len(WEATHER_PRESETS) == 7
    fair = WeatherEffectsController(7, "fair")
    update = fair.advance(30.0, (0.0, 100.0, 0.0))
    assert update.frame.darkness == 0.0
    assert update.frame.rain == 0.0
    assert update.frame.lightning == 0.0
    assert update.thunder == ()


def test_thunderstorm_is_local_dark_and_rain_stops_above_clouds():
    fx = WeatherEffectsController(19, "thunderstorm")
    under = _under_first_cell(fx)
    wet = fx.sample(under)
    dry = fx.sample((under[0] + 90_000.0, under[1], under[2]))
    high = fx.sample((under[0], 30_000.0, under[2]))
    assert wet.local_storm > 0.7
    assert wet.darkness > dry.darkness
    assert wet.rain > 0.3
    assert high.rain == 0.0
    assert high.darkness == 0.0


def test_custom_supercell_drives_local_rain_darkness_and_lightning():
    recipe = compose_custom_weather({
        "cloud_custom_low": "broken",
        "cloud_custom_mid": "scattered",
        "cloud_custom_high": "wispy",
        "cloud_custom_convective": "supercell",
    })
    fx = WeatherEffectsController(19, recipe)
    under = _under_first_cell(fx)
    wet = fx.sample(under)
    far = fx.sample((under[0] + 140_000.0, under[1], under[2]))
    assert wet.local_storm > 0.7
    assert wet.darkness > far.darkness
    assert wet.rain > 0.3

    flashes = []
    thunder = []
    for _ in range(400):
        update = fx.advance(0.1, under)
        flashes.append(update.frame.lightning)
        thunder.extend(update.thunder)
    assert max(flashes) > 0.0
    assert thunder


def test_custom_weather_without_convective_cells_has_no_storm_effects():
    recipe = compose_custom_weather({
        "cloud_custom_low": "deck",
        "cloud_custom_mid": "broken",
        "cloud_custom_high": "dense",
        "cloud_custom_convective": "off",
    })
    fx = WeatherEffectsController(19, recipe)
    update = fx.advance(30.0, (0.0, 100.0, 0.0))
    assert fx.storm_cells == ()
    assert update.frame.rain == 0.0
    assert update.frame.lightning == 0.0
    assert update.thunder == ()


def test_lightning_and_thunder_schedule_is_seed_deterministic():
    a = WeatherEffectsController(77, 6)
    b = WeatherEffectsController(77, 6)
    c = WeatherEffectsController(78, 6)
    camera = _under_first_cell(a)
    cues_a, cues_b = [], []
    flash_a, flash_b = [], []
    for _ in range(400):
        ua = a.advance(0.1, camera)
        ub = b.advance(0.1, camera)
        flash_a.append(ua.frame.lightning)
        flash_b.append(ub.frame.lightning)
        cues_a.extend(ua.thunder)
        cues_b.extend(ub.thunder)
    assert flash_a == flash_b
    assert cues_a == cues_b
    assert max(flash_a) > 0.0
    assert cues_a
    assert c._next_lightning != a._next_lightning


def test_schedule_is_chunk_invariant_for_a_stationary_camera():
    a = WeatherEffectsController(91, 6)
    b = WeatherEffectsController(91, 6)
    camera = _under_first_cell(a)
    cues_a = list(a.advance(30.0, camera).thunder)
    cues_b = []
    for _ in range(300):
        cues_b.extend(b.advance(0.1, camera).thunder)
    assert cues_a == cues_b
    assert a.time == pytest.approx(b.time)
    assert a._next_lightning == b._next_lightning
    fa, fb = a.sample(camera), b.sample(camera)
    assert fa.darkness == pytest.approx(fb.darkness)
    assert fa.rain == pytest.approx(fb.rain)
    assert fa.lightning == pytest.approx(fb.lightning)
    assert fa.local_storm == pytest.approx(fb.local_storm)


def test_configure_noop_preserves_schedule_and_real_change_resets():
    fx = WeatherEffectsController(5, 6)
    fx.advance(2.0, _under_first_cell(fx))
    next_before = fx._next_lightning
    assert fx.configure(5, 6) is False
    assert fx.time == 2.0 and fx._next_lightning == next_before
    assert fx.configure(5, 3) is True
    assert fx.time == 0.0 and fx.preset_id == 3
    assert fx._next_lightning == float("inf")


def test_lightning_pulse_and_overlay_shader_contract():
    assert lightning_pulse(-1.0) == 0.0
    assert lightning_pulse(0.0) == 1.0
    assert lightning_pulse(0.17) > 0.0
    assert lightning_pulse(1.0) == 0.0
    assert "rain_layer" in WEATHER_OVERLAY_FRAG
    assert "u_darkness" in WEATHER_OVERLAY_FRAG
    assert "u_lightning" in WEATHER_OVERLAY_FRAG


def test_controller_does_not_own_or_mutate_physics_world():
    fx = WeatherEffectsController(3, 6)
    assert not hasattr(fx, "world")
    before = fx.preset.precip_mmh
    fx.advance(1.0, _under_first_cell(fx))
    assert fx.preset.precip_mmh == before


def test_negative_programmatic_seed_is_still_deterministic():
    a = WeatherEffectsController(-7, 6)
    b = WeatherEffectsController(-7, 6)
    assert a.storm_cells == b.storm_cells
    assert a._next_lightning == b._next_lightning
