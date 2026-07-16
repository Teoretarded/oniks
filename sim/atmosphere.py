"""GL-free weather and cloud-field definitions.

This module is the data-side source of truth for the V2 cloud renderer.  It
contains no pygame, OpenGL, or ``world`` imports, so simulation code can use
the same presets, profiles, and seeded control fields later without depending
on a renderer.

The V2 field is deliberately camera-independent.  A battle seed selects one
periodic weather geography; presets only change how that geography is read.
Changing a recipe component cannot reshuffle the others because every
component has its own ``default_rng([seed, 17, component])`` stream.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import hashlib

import numpy as np


CLOUD_STREAM_TAG = 17
WEATHER_TILE_M = 300_000.0
CONVECTIVE_DOMAIN_M = 800_000.0


class CloudMorphology(IntEnum):
    """Low-frequency cloud shapes baked into a volumetric layer."""

    STRATUS = 0
    CUMULUS = 1
    TOWERING = 2
    CUMULONIMBUS = 3


class ConvectiveKind(IntEnum):
    """Independent sparse convective systems layered over ambient weather."""

    NONE = 0
    TOWERING = 1
    SUPERCELL = 2
    STORM_LINE = 3


@dataclass(frozen=True)
class CloudLayerSpec:
    """One independently bounded volumetric cloud layer."""

    base_m: float
    top_m: float
    coverage: float
    density_scale: float
    morphology: CloudMorphology
    enabled: bool = True


@dataclass(frozen=True)
class HighCloudSpec:
    """Cheap high-altitude 2D clouds, separate from the volume march."""

    cirrus_coverage: float = 0.0
    strata_coverage: float = 0.0
    altitude_m: float = 10_000.0


@dataclass(frozen=True)
class SupercellSpec:
    """Recipe for sparse, battle-scale convective systems.

    These clouds live in their own 800 km domain rather than the repeating
    ambient density tile.  Count ranges are resolved deterministically from
    the battle seed.
    """

    kind: ConvectiveKind = ConvectiveKind.NONE
    count_range: tuple[int, int] = (0, 0)
    base_range_m: tuple[float, float] = (600.0, 900.0)
    top_range_m: tuple[float, float] = (10_000.0, 12_000.0)
    overshoot_range_m: tuple[float, float] = (0.0, 0.0)
    core_radius_range_m: tuple[float, float] = (15_000.0, 25_000.0)
    anvil_spread_range: tuple[float, float] = (1.2, 1.8)
    density_scale: float = 1.0

    @property
    def enabled(self) -> bool:
        return (self.kind != ConvectiveKind.NONE
                and self.count_range[1] > 0
                and self.density_scale > 0.0)


@dataclass(frozen=True)
class WeatherPreset:
    preset_id: int
    name: str
    lower: CloudLayerSpec
    upper: CloudLayerSpec
    high: HighCloudSpec
    storm_cell_count: int = 0
    precip_mmh: float = 0.0
    storm: float = 0.0
    optical_density_scale: float = 0.0
    wind_ms: tuple[float, float] = (3.0, 1.05)
    supercells: SupercellSpec = SupercellSpec()


@dataclass(frozen=True)
class WeatherState:
    """Static state represented by a preset at battle start.

    A future schedule may interpolate these values, but the field geography
    remains fixed and translates only by ``wind_ms``.
    """

    coverage: float
    cloud_base_m: float
    cloud_top_m: float
    density_scale: float
    precip_mmh: float
    storm: float
    wind_ms: tuple[float, float]


@dataclass(frozen=True)
class StormCell:
    """Seeded, individually shaped convective cell.

    Positions are normalized periodic weather-tile coordinates.  The other
    values are deliberately independent so a storm system is not a row of
    identical circular towers with one shared ceiling.
    """

    x: float
    z: float
    radius_m: float
    intensity: float
    top_fraction: float
    base_fraction: float
    aspect: float
    heading_rad: float
    anvil_spread: float


@dataclass(frozen=True)
class Supercell:
    """One seed-unique convective system in the non-repeating domain."""

    x: float
    z: float
    core_radius_m: float
    intensity: float
    base_m: float
    top_m: float
    overshoot_m: float
    aspect: float
    heading_rad: float
    anvil_spread: float
    tilt_m: float
    kind: ConvectiveKind
    # Seeded visual phenotype.  The field bake maps this stable 0..3 value to
    # incus, pulse/calvus, strongly sheared, and multi-updraft silhouettes.
    # Keeping it in the data model makes variation inspectable and repeatable.
    variant: int


@dataclass(frozen=True)
class CloudStyle:
    """Seed-only scalar style parameters shared by the field bake.

    Integer cirrus wave vectors keep the 2D map exactly periodic while still
    giving every seed a different streak direction and wavelength.
    """

    lower_phase: float
    upper_phase: float
    shear_x: float
    shear_z: float
    cirrus_wave: tuple[int, int]
    cirrus_cross_wave: tuple[int, int]
    cirrus_phase: float
    cirrus_warp: float


@dataclass(frozen=True)
class ControlFields:
    """Seeded periodic 2D basis shared by every preset for one battle."""

    mass: np.ndarray
    puff: np.ndarray
    strata: np.ndarray
    tower: np.ndarray
    warp: np.ndarray
    base: np.ndarray
    height: np.ndarray
    shear: np.ndarray
    cirrus: np.ndarray


_OFF = CloudLayerSpec(0.0, 1.0, 0.0, 0.0,
                      CloudMorphology.CUMULUS, enabled=False)

# Seven visual presets cover the requested clear, mixed, deck, high-cloud,
# towering, and severe-weather skies.  FAIR remains the default/identity sky.
WEATHER_PRESETS: tuple[WeatherPreset, ...] = (
    WeatherPreset(0, "CLEAR", _OFF, _OFF, HighCloudSpec()),
    WeatherPreset(
        1, "FAIR",
        CloudLayerSpec(600.0, 2_700.0, 0.28, 0.88,
                       CloudMorphology.CUMULUS),
        _OFF,
        HighCloudSpec(cirrus_coverage=0.06),
    ),
    WeatherPreset(
        2, "PARTLY CLOUDY",
        CloudLayerSpec(550.0, 3_200.0, 0.52, 1.00,
                       CloudMorphology.CUMULUS),
        CloudLayerSpec(1_800.0, 6_500.0, 0.18, 0.82,
                       CloudMorphology.TOWERING),
        HighCloudSpec(cirrus_coverage=0.10),
        storm_cell_count=3,
        optical_density_scale=1.0,
    ),
    WeatherPreset(
        3, "OVERCAST",
        CloudLayerSpec(300.0, 1_650.0, 0.92, 1.10,
                       CloudMorphology.STRATUS),
        CloudLayerSpec(1_500.0, 4_200.0, 0.42, 0.72,
                       CloudMorphology.STRATUS),
        HighCloudSpec(cirrus_coverage=0.08, strata_coverage=0.48,
                      altitude_m=8_500.0),
        optical_density_scale=1.0,
    ),
    WeatherPreset(
        4, "HIGH CIRRUS",
        _OFF, _OFF,
        HighCloudSpec(cirrus_coverage=0.62, strata_coverage=0.18,
                      altitude_m=10_500.0),
        wind_ms=(8.0, 2.0),
    ),
    WeatherPreset(
        5, "TOWERING CUMULUS",
        CloudLayerSpec(650.0, 3_400.0, 0.42, 1.00,
                       CloudMorphology.CUMULUS),
        CloudLayerSpec(1_500.0, 7_200.0, 0.22, 1.05,
                       CloudMorphology.TOWERING),
        HighCloudSpec(cirrus_coverage=0.12),
        storm_cell_count=3,
        optical_density_scale=1.0,
        wind_ms=(4.0, 1.4),
        supercells=SupercellSpec(
            kind=ConvectiveKind.TOWERING,
            count_range=(3, 5),
            base_range_m=(650.0, 1_200.0),
            top_range_m=(8_500.0, 12_500.0),
            overshoot_range_m=(0.0, 450.0),
            core_radius_range_m=(16_000.0, 31_000.0),
            anvil_spread_range=(1.15, 1.75),
            density_scale=1.02,
        ),
    ),
    WeatherPreset(
        6, "THUNDERSTORM",
        # Sparse feeder/scud fields frame the independent supercell instead
        # of hiding it inside the old full low deck + detached upper blanket.
        CloudLayerSpec(450.0, 2_800.0, 0.28, 0.96,
                       CloudMorphology.CUMULUS),
        CloudLayerSpec(1_800.0, 6_800.0, 0.08, 0.88,
                       CloudMorphology.TOWERING),
        HighCloudSpec(cirrus_coverage=0.08, strata_coverage=0.0,
                      altitude_m=12_000.0),
        storm_cell_count=0,
        precip_mmh=22.0,
        storm=1.0,
        optical_density_scale=1.5,
        wind_ms=(7.0, 2.5),
        supercells=SupercellSpec(
            kind=ConvectiveKind.SUPERCELL,
            count_range=(1, 2),
            base_range_m=(450.0, 1_050.0),
            top_range_m=(14_500.0, 18_500.0),
            overshoot_range_m=(850.0, 2_200.0),
            core_radius_range_m=(24_000.0, 40_000.0),
            anvil_spread_range=(1.65, 2.55),
            density_scale=1.24,
        ),
    ),
)

WEATHER_PRESET_NAMES = tuple(p.name for p in WEATHER_PRESETS)
DEFAULT_WEATHER_PRESET = 1


def weather_preset(value: int | str | WeatherPreset) -> WeatherPreset:
    """Resolve a preset id/name/object, rejecting ambiguous bad values."""

    if isinstance(value, WeatherPreset):
        return value
    if isinstance(value, str):
        key = value.strip().upper().replace("_", " ")
        for preset in WEATHER_PRESETS:
            if preset.name == key:
                return preset
        raise ValueError(f"unknown weather preset {value!r}")
    index = int(value)
    if index < 0 or index >= len(WEATHER_PRESETS):
        raise ValueError(f"weather preset index out of range: {index}")
    return WEATHER_PRESETS[index]


def weather_recipe_key(value: int | str | WeatherPreset) -> str:
    """Stable cache/signature key for built-in or composed weather."""

    preset = weather_preset(value)
    if (0 <= preset.preset_id < len(WEATHER_PRESETS)
            and preset == WEATHER_PRESETS[preset.preset_id]):
        return f"p{preset.preset_id}"

    def layer_key(layer: CloudLayerSpec):
        return (round(layer.base_m, 3), round(layer.top_m, 3),
                round(layer.coverage, 5), round(layer.density_scale, 5),
                int(layer.morphology), bool(layer.enabled))

    high = preset.high
    cells = preset.supercells
    payload = (
        layer_key(preset.lower), layer_key(preset.upper),
        (round(high.cirrus_coverage, 5),
         round(high.strata_coverage, 5), round(high.altitude_m, 3)),
        int(preset.storm_cell_count), round(preset.precip_mmh, 4),
        round(preset.storm, 4), round(preset.optical_density_scale, 4),
        tuple(round(v, 4) for v in preset.wind_ms), int(cells.kind),
        tuple(int(v) for v in cells.count_range),
        tuple(round(v, 3) for v in cells.base_range_m),
        tuple(round(v, 3) for v in cells.top_range_m),
        tuple(round(v, 3) for v in cells.overshoot_range_m),
        tuple(round(v, 3) for v in cells.core_radius_range_m),
        tuple(round(v, 4) for v in cells.anvil_spread_range),
        round(cells.density_scale, 4),
    )
    digest = hashlib.blake2b(repr(payload).encode("ascii"),
                             digest_size=8).hexdigest()
    return f"c{digest}"


def state_for_preset(value: int | str | WeatherPreset) -> WeatherState:
    preset = weather_preset(value)
    layers = tuple(layer for layer in (preset.lower, preset.upper)
                   if layer.enabled)
    high_coverage = max(preset.high.cirrus_coverage,
                        preset.high.strata_coverage)
    if layers:
        base = min(layer.base_m for layer in layers)
        top = max(layer.top_m for layer in layers)
        coverage = max(max(layer.coverage for layer in layers), high_coverage)
        if high_coverage > 0.0:
            base = min(base, preset.high.altitude_m - 500.0)
            top = max(top, preset.high.altitude_m + 500.0)
    elif high_coverage > 0.0:
        base = preset.high.altitude_m - 500.0
        top = preset.high.altitude_m + 500.0
        coverage = high_coverage
    else:
        base = top = coverage = 0.0
    if preset.supercells.enabled:
        base = (min(base, preset.supercells.base_range_m[0])
                if coverage > 0.0 else preset.supercells.base_range_m[0])
        top = max(top, preset.supercells.top_range_m[1]
                  + preset.supercells.overshoot_range_m[1])
        coverage = max(coverage, 0.18)
    return WeatherState(coverage, base, top, preset.optical_density_scale,
                        preset.precip_mmh, preset.storm, preset.wind_ms)


def _smoothstep01(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def vertical_profile(h, morphology: CloudMorphology):
    """Density envelope at normalized height ``h`` for one morphology.

    Accepts a scalar or NumPy array. Values outside [0, 1] are exactly zero.
    """

    arr = np.asarray(h, dtype=np.float32)
    inside = (arr >= 0.0) & (arr <= 1.0)
    x = np.clip(arr, 0.0, 1.0)
    morph = CloudMorphology(morphology)
    if morph == CloudMorphology.STRATUS:
        bottom = _smoothstep01(x / 0.10)
        top = 1.0 - _smoothstep01((x - 0.72) / 0.28)
        profile = bottom * top
    elif morph == CloudMorphology.CUMULUS:
        bottom = _smoothstep01(x / 0.13)
        top = 1.0 - _smoothstep01((x - 0.54) / 0.46)
        profile = bottom * top * (0.82 + 0.18 * x)
    elif morph == CloudMorphology.TOWERING:
        bottom = _smoothstep01(x / 0.08)
        top = 1.0 - _smoothstep01((x - 0.78) / 0.22)
        profile = bottom * top * (0.68 + 0.32 * x)
    else:
        bottom = _smoothstep01(x / 0.06)
        cap = 1.0 - _smoothstep01((x - 0.90) / 0.10)
        # A broad upper shoulder leaves room for the separately stamped anvil.
        profile = bottom * cap * (0.72 + 0.28 * x)
    out = np.where(inside, profile, 0.0).astype(np.float32)
    return float(out) if out.ndim == 0 else out


def _fade(t):
    return t * t * (3.0 - 2.0 * t)


def _periodic_value_noise(rng, size: int, cells: int) -> np.ndarray:
    """Fast periodic 2D value noise in [0, 1]."""

    lattice = rng.random((cells, cells), dtype=np.float32)
    coord = np.arange(size, dtype=np.float32) * (cells / float(size))
    i0 = np.floor(coord).astype(np.intp) % cells
    i1 = (i0 + 1) % cells
    f = _fade(coord - np.floor(coord))
    fx = f[None, :]
    fz = f[:, None]
    # Array convention throughout the field bake is [z, x].
    a = lattice[i0[:, None], i0[None, :]]
    b = lattice[i0[:, None], i1[None, :]]
    c = lattice[i1[:, None], i0[None, :]]
    d = lattice[i1[:, None], i1[None, :]]
    x0 = a * (1.0 - fx) + b * fx
    x1 = c * (1.0 - fx) + d * fx
    return (x0 * (1.0 - fz) + x1 * fz).astype(np.float32)


def periodic_fbm2(seed: int, component: int, size: int,
                  frequencies: tuple[int, ...]) -> np.ndarray:
    """A deterministic component-isolated periodic fBm field."""

    rng = np.random.default_rng(
        [int(seed), CLOUD_STREAM_TAG, int(component)])
    total = np.zeros((int(size), int(size)), dtype=np.float32)
    amplitude = 1.0
    norm = 0.0
    for cells in frequencies:
        total += _periodic_value_noise(rng, int(size), int(cells)) * amplitude
        norm += amplitude
        amplitude *= 0.5
    return (total / norm).astype(np.float32)


def build_control_fields(seed: int, size: int = 256) -> ControlFields:
    """Build the seed-only weather geography used by every V2 preset."""

    n = int(size)
    if n <= 0:
        raise ValueError("control-field size must be positive")
    return ControlFields(
        # Non-harmonic octave counts avoid the visibly nested 2/4/8 motifs of
        # the first field recipe while retaining exact periodicity.
        mass=periodic_fbm2(seed, 1, n, (2, 5, 11)),
        puff=periodic_fbm2(seed, 2, n, (7, 17, 31)),
        strata=periodic_fbm2(seed, 3, n, (1, 4, 9)),
        tower=periodic_fbm2(seed, 4, n, (3, 8, 19)),
        warp=periodic_fbm2(seed, 5, n, (2, 7, 13)),
        base=periodic_fbm2(seed, 6, n, (3, 10, 23)),
        height=periodic_fbm2(seed, 7, n, (2, 6, 15)),
        shear=periodic_fbm2(seed, 8, n, (5, 12, 29)),
        cirrus=periodic_fbm2(seed, 9, n, (1, 6, 17)),
    )


def cloud_style(seed: int) -> CloudStyle:
    """Return component-isolated, seed-unique scalar morphology controls."""

    rng = np.random.default_rng([int(seed), CLOUD_STREAM_TAG, 60])
    wave_pairs = ((5, 1), (7, 2), (8, 3), (9, 4), (11, 3),
                  (12, 5), (13, 4), (14, 3))
    wave = wave_pairs[int(rng.integers(0, len(wave_pairs)))]
    # A second integer vector bends/cross-hatches the main streaks without
    # introducing a non-periodic arbitrary-angle seam.
    cross = (-wave[1], wave[0])
    return CloudStyle(
        lower_phase=float(rng.uniform(0.0, 2.0 * np.pi)),
        upper_phase=float(rng.uniform(0.0, 2.0 * np.pi)),
        shear_x=float(rng.uniform(-8.0, 8.0)),
        shear_z=float(rng.uniform(-8.0, 8.0)),
        cirrus_wave=wave,
        cirrus_cross_wave=cross,
        cirrus_phase=float(rng.uniform(0.0, 2.0 * np.pi)),
        cirrus_warp=float(rng.uniform(1.5, 3.8)),
    )


def build_storm_cells(seed: int,
                      preset: int | str | WeatherPreset) -> tuple[StormCell, ...]:
    """Return deterministic, separated cells from one stable stream prefix."""

    count = weather_preset(preset).storm_cell_count
    if count <= 0:
        return ()
    rng = np.random.default_rng([int(seed), CLOUD_STREAM_TAG, 40])
    cells = []
    for _ in range(count):
        # Best-candidate placement prevents nine-cell storm presets collapsing
        # into one overlapping blob.  A fixed candidate count preserves the
        # prefix contract between PARTLY and THUNDERSTORM.
        candidates = rng.random((10, 2))
        if cells:
            best = None
            best_clearance = -1.0
            for candidate in candidates:
                clearance = min(
                    np.hypot(
                        min(abs(float(candidate[0]) - cell.x),
                            1.0 - abs(float(candidate[0]) - cell.x)),
                        min(abs(float(candidate[1]) - cell.z),
                            1.0 - abs(float(candidate[1]) - cell.z)),
                    ) for cell in cells)
                if clearance > best_clearance:
                    best, best_clearance = candidate, clearance
            position = best
        else:
            position = candidates[0]
        cells.append(StormCell(
            x=float(position[0]),
            z=float(position[1]),
            radius_m=float(rng.uniform(11_000.0, 34_000.0)),
            intensity=float(rng.uniform(0.68, 1.0)),
            top_fraction=float(rng.uniform(0.66, 1.0)),
            base_fraction=float(rng.uniform(0.0, 0.14)),
            aspect=float(rng.uniform(0.68, 1.48)),
            heading_rad=float(rng.uniform(0.0, 2.0 * np.pi)),
            anvil_spread=float(rng.uniform(1.25, 2.25)),
        ))
    return tuple(cells)


def build_supercells(seed: int,
                     preset: int | str | WeatherPreset) -> tuple[Supercell, ...]:
    """Resolve sparse convective systems without repeating across the map."""

    spec = weather_preset(preset).supercells
    if not spec.enabled:
        return ()
    rng = np.random.default_rng([int(seed), CLOUD_STREAM_TAG, 41])
    lo, hi = (int(spec.count_range[0]), int(spec.count_range[1]))
    count = int(rng.integers(lo, hi + 1))
    positions: list[np.ndarray] = []

    if spec.kind == ConvectiveKind.STORM_LINE:
        heading = float(rng.uniform(0.0, 2.0 * np.pi))
        along = np.array([np.sin(heading), np.cos(heading)])
        across = np.array([-along[1], along[0]])
        center = rng.uniform(0.28, 0.58, size=2)
        spacing = float(rng.uniform(0.055, 0.085))
        for index in range(count):
            offset = (index - (count - 1) * 0.5) * spacing
            jitter = float(rng.uniform(-0.018, 0.018))
            positions.append(np.clip(center + along * offset
                                     + across * jitter, 0.07, 0.73))
    else:
        # Keep systems inside the 0..600 km playable geography of the larger
        # 800 km domain, then maximize separation so every silhouette reads.
        for _ in range(count):
            candidates = rng.uniform(0.07, 0.73, size=(18, 2))
            if positions:
                candidate = max(
                    candidates,
                    key=lambda p: min(float(np.linalg.norm(p - q))
                                      for q in positions),
                )
            else:
                candidate = candidates[0]
            positions.append(np.asarray(candidate, dtype=np.float64))

    cells = []
    for position in positions:
        radius = float(rng.uniform(*spec.core_radius_range_m))
        top = float(rng.uniform(*spec.top_range_m))
        overshoot = float(rng.uniform(*spec.overshoot_range_m))
        cells.append(Supercell(
            x=float(position[0]),
            z=float(position[1]),
            core_radius_m=radius,
            intensity=float(rng.uniform(0.78, 1.0)),
            base_m=float(rng.uniform(*spec.base_range_m)),
            top_m=top,
            overshoot_m=overshoot,
            aspect=float(rng.uniform(0.72, 1.55)),
            heading_rad=float(rng.uniform(0.0, 2.0 * np.pi)),
            anvil_spread=float(rng.uniform(*spec.anvil_spread_range)),
            tilt_m=float(rng.uniform(radius * 0.12, radius * 0.38)),
            kind=spec.kind,
            variant=int(rng.integers(0, 4)),
        ))
    return tuple(cells)
