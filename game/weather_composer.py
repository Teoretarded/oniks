"""Pure data model for the Graphics-tab Weather Composer.

The four custom cards are independent: any number may be non-OFF.  This file
contains no pygame or GL imports, so preference validation, summaries, cache
signatures, and UI tests all share one canonical ordering.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sim.atmosphere import (CloudLayerSpec, CloudMorphology, ConvectiveKind,
                            HighCloudSpec, SupercellSpec, WeatherPreset,
                            weather_recipe_key)


LOW_OPTIONS = ("off", "scattered", "broken", "deck")
MID_OPTIONS = ("off", "scattered", "broken", "massive")
HIGH_OPTIONS = ("off", "wispy", "dense", "sheet")
CONVECTIVE_OPTIONS = ("off", "towering", "supercell", "storm line")

CUSTOM_PREF_KEYS = (
    "cloud_custom_low",
    "cloud_custom_mid",
    "cloud_custom_high",
    "cloud_custom_convective",
)

CUSTOM_OPTIONS = {
    CUSTOM_PREF_KEYS[0]: LOW_OPTIONS,
    CUSTOM_PREF_KEYS[1]: MID_OPTIONS,
    CUSTOM_PREF_KEYS[2]: HIGH_OPTIONS,
    CUSTOM_PREF_KEYS[3]: CONVECTIVE_OPTIONS,
}

CUSTOM_DEFAULTS = {
    "cloud_custom_low": "scattered",
    "cloud_custom_mid": "off",
    "cloud_custom_high": "wispy",
    "cloud_custom_convective": "off",
}

QUICK_WEATHER_PRESETS = (
    "battle",
    "clear",
    "fair",
    "partly cloudy",
    "overcast",
    "high cirrus",
    "towering cumulus",
    "thunderstorm",
    "custom",
)


@dataclass(frozen=True)
class LayerCard:
    title: str
    key: str
    altitude: str
    options: tuple[str, ...]
    recommended: str


LAYER_CARDS = (
    LayerCard("LOW", CUSTOM_PREF_KEYS[0], "0.3-3.2 KM", LOW_OPTIONS,
              "scattered"),
    LayerCard("MID", CUSTOM_PREF_KEYS[1], "1.5-6.5 KM", MID_OPTIONS,
              "scattered"),
    LayerCard("HIGH", CUSTOM_PREF_KEYS[2], "8-12 KM", HIGH_OPTIONS,
              "wispy"),
    LayerCard("CONVECTIVE", CUSTOM_PREF_KEYS[3], "0.4-22 KM",
              CONVECTIVE_OPTIONS, "towering"),
)


def _read(source, key: str):
    if isinstance(source, Mapping):
        return source.get(key, CUSTOM_DEFAULTS[key])
    getter = getattr(source, "get", None)
    if getter is None:
        raise TypeError("custom weather source must be a mapping or expose get()")
    try:
        return getter(key)
    except (KeyError, TypeError):
        return CUSTOM_DEFAULTS[key]


def custom_selection(source) -> dict[str, str]:
    """Return a validated copy of the four custom layer choices."""

    out = {}
    for key in CUSTOM_PREF_KEYS:
        value = _read(source, key)
        out[key] = value if value in CUSTOM_OPTIONS[key] else CUSTOM_DEFAULTS[key]
    return out


def canonical_custom_tuple(selection) -> tuple[str, str, str, str]:
    """Stable Low/Mid/High/Convective tuple for signatures and caches."""

    clean = custom_selection(selection)
    return tuple(clean[key] for key in CUSTOM_PREF_KEYS)


def cycle_custom_value(key: str, current: str, delta: int) -> str:
    values = CUSTOM_OPTIONS[key]
    try:
        index = values.index(current)
    except ValueError:
        index = 0
    return values[(index + int(delta)) % len(values)]


def toggle_custom_value(key: str, current: str) -> str:
    """OFF -> recommended; any enabled style -> OFF."""

    card = next(card for card in LAYER_CARDS if card.key == key)
    return card.recommended if current == "off" else "off"


def weather_summary(override: str, selection) -> str:
    """Compact human-readable summary for the Graphics row and composer."""

    mode = str(override).strip().lower()
    if mode != "custom":
        if mode == "battle":
            return "BATTLE SETUP"
        if mode in QUICK_WEATHER_PRESETS:
            return mode.upper()
        return "BATTLE SETUP"

    clean = custom_selection(selection)
    names = ("LOW", "MID", "HIGH", "CB")
    enabled = [f"{name} {clean[key].upper()}"
               for name, key in zip(names, CUSTOM_PREF_KEYS)
               if clean[key] != "off"]
    return "CUSTOM: " + (" + ".join(enabled) if enabled else "CLEAR")


def compose_custom_weather(selection) -> WeatherPreset:
    """Translate the four UI cards into one renderer-ready weather recipe."""

    low, mid, high, convective = canonical_custom_tuple(selection)
    off = CloudLayerSpec(0.0, 1.0, 0.0, 0.0,
                         CloudMorphology.CUMULUS, enabled=False)
    low_specs = {
        "off": off,
        "scattered": CloudLayerSpec(
            550.0, 2_800.0, 0.28, 0.90, CloudMorphology.CUMULUS),
        "broken": CloudLayerSpec(
            450.0, 3_250.0, 0.56, 1.02, CloudMorphology.CUMULUS),
        "deck": CloudLayerSpec(
            260.0, 1_900.0, 0.92, 1.12, CloudMorphology.STRATUS),
    }
    mid_specs = {
        "off": off,
        "scattered": CloudLayerSpec(
            2_200.0, 5_400.0, 0.26, 0.86, CloudMorphology.CUMULUS),
        "broken": CloudLayerSpec(
            1_650.0, 7_200.0, 0.48, 1.04, CloudMorphology.TOWERING),
        "massive": CloudLayerSpec(
            1_100.0, 5_700.0, 0.88, 1.12, CloudMorphology.STRATUS),
    }
    high_specs = {
        "off": HighCloudSpec(),
        "wispy": HighCloudSpec(cirrus_coverage=0.34,
                                strata_coverage=0.04,
                                altitude_m=10_700.0),
        "dense": HighCloudSpec(cirrus_coverage=0.72,
                                strata_coverage=0.22,
                                altitude_m=11_200.0),
        "sheet": HighCloudSpec(cirrus_coverage=0.32,
                                strata_coverage=0.78,
                                altitude_m=9_600.0),
    }
    convective_specs = {
        "off": (SupercellSpec(), 0.0, 0.0, (3.0, 1.05)),
        "towering": (SupercellSpec(
            kind=ConvectiveKind.TOWERING,
            count_range=(3, 5),
            base_range_m=(650.0, 1_250.0),
            top_range_m=(9_000.0, 13_000.0),
            overshoot_range_m=(0.0, 500.0),
            core_radius_range_m=(18_000.0, 33_000.0),
            anvil_spread_range=(1.15, 1.75),
            density_scale=1.04), 0.0, 0.0, (4.0, 1.4)),
        "supercell": (SupercellSpec(
            kind=ConvectiveKind.SUPERCELL,
            count_range=(1, 2),
            base_range_m=(420.0, 1_050.0),
            top_range_m=(15_000.0, 19_500.0),
            overshoot_range_m=(1_000.0, 2_500.0),
            core_radius_range_m=(25_000.0, 42_000.0),
            anvil_spread_range=(1.7, 2.65),
            density_scale=1.30), 22.0, 1.0, (7.0, 2.5)),
        "storm line": (SupercellSpec(
            kind=ConvectiveKind.STORM_LINE,
            count_range=(4, 6),
            base_range_m=(350.0, 900.0),
            top_range_m=(13_000.0, 17_000.0),
            overshoot_range_m=(600.0, 1_650.0),
            core_radius_range_m=(22_000.0, 42_000.0),
            anvil_spread_range=(2.0, 3.1),
            density_scale=1.22), 30.0, 1.0, (10.0, 3.2)),
    }
    cells, precip, storm, wind = convective_specs[convective]
    active = sum(value != "off" for value in (low, mid, high, convective))
    return WeatherPreset(
        7, "CUSTOM", low_specs[low], mid_specs[mid], high_specs[high],
        precip_mmh=precip,
        storm=storm,
        optical_density_scale=1.0 if active else 0.0,
        wind_ms=wind,
        supercells=cells,
    )


def custom_recipe_digest(selection) -> str:
    return weather_recipe_key(compose_custom_weather(selection))
