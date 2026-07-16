"""GL-free V2 cloud-field bake and cache.

The bake produces two stable world-space base-density volumes plus a
conservative, dilated occupancy hierarchy.  A renderer may skip an empty
occupancy cell to its boundary, but must never jump an arbitrary multiple of
the ray step.  Detail erosion is intentionally absent from the base volume:
render-time detail may remove density but must not create it, preserving the
occupancy guarantee.

Array convention for 3D data is ``[y, z, x]``.  Horizontal axes are periodic;
height is bounded.  All persisted/render-facing arrays are uint8.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from zipfile import BadZipFile

import numpy as np

from sim.atmosphere import (
    CONVECTIVE_DOMAIN_M, CloudMorphology, CloudStyle, ControlFields,
    ConvectiveKind, StormCell, Supercell, WEATHER_TILE_M, WeatherPreset,
    build_control_fields, build_storm_cells, build_supercells, cloud_style,
    vertical_profile, weather_preset, weather_recipe_key,
)


FIELD_CACHE_VERSION = "v13"
CONTROL_N = 256
CIRRUS_N = 512
# The first field repeated its entire macro geography every 65 km, making the
# same systems appear nine times across a 600 km battle.  A three-times wider
# tile keeps 256^2 base volumes affordable, leaves runtime detail to the
# renderer, and reduces exact repeats to roughly three across that view.
DENSITY_TILE_M = 196_608.0
LOWER_SHAPE = (48, CONTROL_N, CONTROL_N)   # y, z, x
UPPER_SHAPE = (64, CONTROL_N, CONTROL_N)
STORM_SHAPE = (96, 192, 192)
STORM_OCCUPANCY_BLOCK = 4
# Coarse 6.1 km horizontal cells let clear rays reach the 450 km horizon in a
# bounded number of exact DDA crossings. Density is still sampled from the
# full 256-wide volume once a conservative occupied cell is entered.
OCCUPANCY_BLOCK = 8


@dataclass(frozen=True)
class CloudField:
    seed: int
    preset_id: int
    recipe_key: str
    lower_density: np.ndarray
    upper_density: np.ndarray
    storm_density: np.ndarray
    lower_occupancy: np.ndarray
    upper_occupancy: np.ndarray
    storm_occupancy: np.ndarray
    cirrus: np.ndarray
    shadow: np.ndarray
    lower_base_m: float
    lower_top_m: float
    upper_base_m: float
    upper_top_m: float
    storm_base_m: float
    storm_top_m: float


def cache_path(cache_dir, seed: int, preset=1) -> Path:
    if isinstance(preset, str) and preset.startswith(("p", "c")):
        key = preset
    else:
        key = weather_recipe_key(preset)
    return (Path(cache_dir)
            / f"cloudfield_{FIELD_CACHE_VERSION}_seed{int(seed)}_{key}.npz")


def _smoothstep(x, lo: float, hi: float) -> np.ndarray:
    u = np.clip((np.asarray(x) - np.asarray(lo))
                / np.maximum(np.asarray(hi) - np.asarray(lo), 1e-6),
                0.0, 1.0)
    return (u * u * (3.0 - 2.0 * u)).astype(np.float32)


def _normalize_basis(value: np.ndarray) -> np.ndarray:
    """Robust 5..95% normalization used by local base/top controls."""

    lo = float(np.percentile(value, 5.0))
    hi = float(np.percentile(value, 95.0))
    return np.clip((value - lo) / max(hi - lo, 1e-6), 0.0, 1.0).astype(
        np.float32)


def _carrier(controls: ControlFields, morphology: CloudMorphology) -> np.ndarray:
    if morphology == CloudMorphology.STRATUS:
        value = 0.72 * controls.strata + 0.28 * controls.mass
    elif morphology == CloudMorphology.CUMULUS:
        value = 0.44 * controls.mass + 0.38 * controls.puff \
            + 0.18 * controls.tower
    elif morphology == CloudMorphology.TOWERING:
        value = 0.36 * controls.mass + 0.24 * controls.puff \
            + 0.40 * controls.tower
    else:
        value = 0.46 * controls.mass + 0.18 * controls.puff \
            + 0.36 * controls.tower
    return np.clip(value, 0.0, 1.0).astype(np.float32)


def _coverage_mask(carrier: np.ndarray, coverage: float) -> np.ndarray:
    # Choose the threshold from the seed's own distribution, so "coverage"
    # retains a useful meaning across seeds and morphologies. The narrow soft
    # edge avoids hard facets without turning tiny near-zero tails into broad
    # occupied regions.
    amount = float(np.clip(coverage, 0.0, 1.0))
    if amount <= 0.0:
        return np.zeros_like(carrier, dtype=np.float32)
    if amount >= 1.0:
        return np.ones_like(carrier, dtype=np.float32)
    threshold = float(np.quantile(carrier, 1.0 - amount))
    return _smoothstep(carrier, threshold - 0.035, threshold + 0.035)


def _cell_masks(size: int, cells: tuple[StormCell, ...]):
    """Periodic, rotated core/anvil masks plus local vertical bounds."""

    if not cells:
        zero = np.zeros((size, size), dtype=np.float32)
        one = np.ones_like(zero)
        return zero, zero.copy(), one, zero.copy(), one.copy()
    coord = (np.arange(size, dtype=np.float32) + 0.5) / float(size)
    xx = coord[None, :]
    zz = coord[:, None]
    core = np.zeros((size, size), dtype=np.float32)
    anvil = np.zeros_like(core)
    core_top = np.ones_like(core)
    core_base = np.zeros_like(core)
    anvil_top = np.ones_like(core)
    for cell in cells:
        # Signed shortest periodic displacement is required before rotation.
        dx = ((xx - cell.x + 0.5) % 1.0 - 0.5) * DENSITY_TILE_M
        dz = ((zz - cell.z + 0.5) % 1.0 - 0.5) * DENSITY_TILE_M
        # StormCell radii are authored for the 300 km weather geography.
        # Preserve that normalized footprint on this macro-density tile.
        r = cell.radius_m * (DENSITY_TILE_M / WEATHER_TILE_M)
        cs, sn = np.cos(cell.heading_rad), np.sin(cell.heading_rad)
        along = dx * cs + dz * sn
        across = -dx * sn + dz * cs
        core_q = np.sqrt(
            (along / max(r * cell.aspect, 1.0)) ** 2
            + (across / max(r / cell.aspect, 1.0)) ** 2)
        c = 1.0 - _smoothstep(core_q, 0.38, 1.0)

        # The anvil is broader, flatter, and displaced down-heading from its
        # updraft.  Each cell owns a different heading/aspect/spread.
        anvil_dx = dx - cs * r * 0.32
        anvil_dz = dz - sn * r * 0.32
        anvil_along = anvil_dx * cs + anvil_dz * sn
        anvil_across = -anvil_dx * sn + anvil_dz * cs
        anvil_q = np.sqrt(
            (anvil_along
             / max(r * cell.anvil_spread * max(cell.aspect, 0.8), 1.0)) ** 2
            + (anvil_across
               / max(r * cell.anvil_spread * 0.58, 1.0)) ** 2)
        a = 1.0 - _smoothstep(anvil_q, 0.48, 1.0)
        strength = c * cell.intensity
        stronger = strength > core
        core_top[stronger] = cell.top_fraction
        core_base[stronger] = cell.base_fraction
        np.maximum(core, strength, out=core)
        anvil_strength = a * cell.intensity
        stronger_anvil = anvil_strength > anvil
        anvil_top[stronger_anvil] = cell.top_fraction
        np.maximum(anvil, anvil_strength, out=anvil)
    return core, anvil, core_top, core_base, anvil_top


def _layer_density(spec, shape: tuple[int, int, int],
                   controls: ControlFields, cells: tuple[StormCell, ...],
                   style: CloudStyle, upper: bool) -> np.ndarray:
    ny, nz, nx = shape
    if not spec.enabled or spec.coverage <= 0.0 or spec.density_scale <= 0.0:
        return np.zeros(shape, dtype=np.uint8)

    carrier = _carrier(controls, spec.morphology)
    coverage = _coverage_mask(carrier, spec.coverage)
    core, anvil, core_top, core_base, anvil_top = _cell_masks(nx, cells)
    out = np.empty(shape, dtype=np.uint8)

    # Per-column ceilings stop every cloud sharing one flat preset top. The
    # same seed-stable controls produce low puffs, broad mature cumulus, and
    # taller cells inside a single layer without any camera-dependent LOD.
    height_basis = _normalize_basis(
        0.42 * controls.height + 0.28 * controls.tower
        + 0.18 * controls.puff + 0.12 * controls.mass)
    base_basis = _normalize_basis(
        0.58 * controls.base + 0.24 * controls.warp
        + 0.18 * controls.shear)
    if spec.morphology == CloudMorphology.STRATUS:
        column_base = 0.015 + 0.075 * base_basis
        column_top = 0.78 + 0.22 * height_basis
    elif spec.morphology == CloudMorphology.CUMULUS:
        column_base = 0.015 + 0.115 * base_basis
        column_top = 0.34 + 0.66 * np.power(height_basis, 0.72)
    elif spec.morphology == CloudMorphology.TOWERING:
        column_base = 0.01 + 0.085 * base_basis
        column_top = 0.48 + 0.52 * np.power(height_basis, 0.62)
    else:
        column_base = 0.005 + 0.055 * base_basis
        column_top = 0.68 + 0.32 * np.power(height_basis, 0.55)
    if cells and upper:
        column_top = np.maximum(column_top, core * core_top)
        column_base = np.where(core > 0.02,
                               np.minimum(column_base, core_base),
                               column_base)
    column_top = np.maximum(column_top, column_base + 0.16)

    for iy in range(ny):
        h = (iy + 0.5) / float(ny)
        local_h = ((h - column_base)
                   / np.maximum(column_top - column_base, 0.08))
        profile = vertical_profile(local_h, spec.morphology)
        # Integer periodic shifts add genuine 3D variation while retaining a
        # stable, cheap, seed-derived field. They never depend on the camera.
        phase = style.upper_phase if upper else style.lower_phase
        sx = int(round(np.sin(h * np.pi * 2.0 + phase) * 5.0
                       + style.shear_x * h))
        sz = int(round(np.cos(h * np.pi * 2.0 + phase) * 4.0
                       + style.shear_z * h))
        billow = np.roll(controls.puff, (sz, sx), axis=(0, 1))
        cross_billow = np.roll(controls.shear, (-sx * 2, sz * 2), axis=(0, 1))
        fine = (0.72 + 0.32 * (billow - 0.5)
                + 0.18 * (cross_billow - 0.5)
                + 0.12 * (controls.warp - 0.5))
        if spec.morphology == CloudMorphology.CUMULUS:
            shrink = 0.46 * np.power(np.clip(local_h, 0.0, 1.0), 1.18)
        elif spec.morphology == CloudMorphology.TOWERING:
            shrink = 0.26 * np.power(np.clip(local_h, 0.0, 1.0), 1.10)
        elif spec.morphology == CloudMorphology.CUMULONIMBUS:
            shrink = 0.12 * np.clip(local_h, 0.0, 1.0)
        else:
            shrink = 0.0
        footprint = np.clip((coverage - shrink) / np.maximum(1.0 - shrink, 1e-5),
                            0.0, 1.0)
        density = footprint * profile * fine

        if cells:
            if upper and spec.morphology in (CloudMorphology.TOWERING,
                                             CloudMorphology.CUMULONIMBUS):
                # Towers share the seeded cell core.  Cumulonimbus spreads a
                # broad anvil only near its top; it is not a detached layer.
                cell_h = ((h - core_base)
                          / np.maximum(core_top - core_base, 0.08))
                tower_profile = vertical_profile(cell_h, spec.morphology)
                cap_lo = np.maximum(core_top - 0.10, 0.0)
                cap_u = np.clip((h - cap_lo)
                                / np.maximum(core_top - cap_lo, 1e-6), 0.0, 1.0)
                variable_cap = 1.0 - cap_u * cap_u * (3.0 - 2.0 * cap_u)
                tower = (core * tower_profile * variable_cap
                         * (0.86 + 0.24 * billow))
                if spec.morphology == CloudMorphology.CUMULONIMBUS:
                    anvil_band = (
                        _smoothstep(h, anvil_top - 0.18, anvil_top - 0.10)
                        * (1.0 - _smoothstep(
                            h, anvil_top - 0.045, anvil_top + 0.015)))
                    tower = np.maximum(tower, anvil * anvil_band * 0.88)
                density = np.maximum(density, tower)
            elif not upper:
                # Low scud/deck remains horizontally aligned under the tower.
                scud_band = max(0.0, 1.0 - h * 1.35)
                scud = np.maximum(core, anvil * 0.58)
                density = np.maximum(density, scud * scud_band * 0.88)

        # Preserve headroom for lighting/erosion instead of saturating most
        # storm columns to 255. Tiny soft-mask tails are made exactly empty so
        # the conservative occupancy grid still has useful skip cells.
        density *= 0.58 + 0.20 * min(float(spec.density_scale), 1.5)
        density = np.where(density >= 0.018, density, 0.0)
        density = np.clip(density, 0.0, 0.96)
        out[iy] = (density * 255.0 + 0.5).astype(np.uint8)
    return out


def _supercell_density(preset: WeatherPreset,
                       cells: tuple[Supercell, ...],
                       controls: ControlFields) -> tuple[np.ndarray, float, float]:
    """Bake sparse, tilted towers/anvils in the non-repeating 800 km domain."""

    if not cells:
        return np.zeros(STORM_SHAPE, dtype=np.uint8), 0.0, 1.0
    ny, nz, nx = STORM_SHAPE
    coord_x = (np.arange(nx, dtype=np.float32) + 0.5) / nx \
        * CONVECTIVE_DOMAIN_M
    coord_z = (np.arange(nz, dtype=np.float32) + 0.5) / nz \
        * CONVECTIVE_DOMAIN_M
    xx = coord_x[None, :]
    zz = coord_z[:, None]
    base_m = max(0.0, min(cell.base_m for cell in cells) - 300.0)
    top_m = max(cell.top_m + cell.overshoot_m for cell in cells) + 250.0
    out = np.zeros(STORM_SHAPE, dtype=np.uint8)
    detail = (0.44 * controls.tower + 0.34 * controls.puff
              + 0.22 * controls.warp)

    for iy in range(ny):
        y = base_m + (iy + 0.5) / ny * (top_m - base_m)
        layer = np.zeros((nz, nx), dtype=np.float32)
        for cell in cells:
            depth = max(cell.top_m - cell.base_m, 1.0)
            local_h = (y - cell.base_m) / depth
            if local_h < -0.08 or y > cell.top_m + cell.overshoot_m:
                continue
            h = float(np.clip(local_h, 0.0, 1.0))
            cs, sn = np.cos(cell.heading_rad), np.sin(cell.heading_rad)
            # Updrafts lean down-shear with altitude instead of extruding a
            # vertical stamp. A second offset lobe creates a rotating, open
            # inflow side and prevents circular mushroom silhouettes.
            # ``core_radius_m`` describes the whole convective system's
            # footprint.  The rotating updraft itself must stay much slimmer
            # or a 17 km-tall supercell turns into a 90 km-wide pancake.
            # Four deterministic storm phenotypes.  The same world seed always
            # selects the same one, while adjacent cells need not share a
            # silhouette.  Values deliberately change proportions, not just
            # noise phase: incus, pulse/calvus, sheared, and multi-updraft.
            variant = int(cell.variant) % 4
            severe_tower_scale = (0.43, 0.50, 0.37, 0.45)[variant]
            tower_scale = (0.42 if cell.kind == ConvectiveKind.TOWERING
                           else severe_tower_scale)
            tower_radius = cell.core_radius_m * tower_scale
            tilt_gain = (0.48, 0.30, 0.78, 0.52)[variant]
            tilt = cell.tilt_m * tilt_gain * h ** 1.35
            cx = cell.x * CONVECTIVE_DOMAIN_M + cs * tilt
            cz = cell.z * CONVECTIVE_DOMAIN_M + sn * tilt
            dx = xx - cx
            dz = zz - cz
            along = dx * cs + dz * sn
            across = -dx * sn + dz * cs
            waist = (0.56, 0.64, 0.50, 0.58)[variant]
            crown = (0.52, 0.62, 0.46, 0.56)[variant]
            bulge = (waist + crown * np.sin(np.pi * h) ** 0.72
                     - (0.14 if variant == 1 else 0.17) * h ** 2.0)
            radius = max(tower_radius * bulge, 1.0)
            q = np.sqrt(
                (along / (radius * cell.aspect)) ** 2
                + (across / (radius / cell.aspect)) ** 2)
            q *= 1.0 + 0.30 * (detail - 0.5)
            core = 1.0 - _smoothstep(q, 0.48, 1.02)

            lobe_dx = along + tower_radius * 0.34
            lobe_dz = across - tower_radius * 0.22
            lobe_q = np.sqrt(
                (lobe_dx / (radius * 0.72)) ** 2
                + (lobe_dz / (radius * 0.58)) ** 2)
            rotating_lobe = (1.0 - _smoothstep(lobe_q, 0.34, 1.0)) * 0.72
            core = np.maximum(core, rotating_lobe)
            if variant == 3 and cell.kind != ConvectiveKind.TOWERING:
                # A neighboring mature updraft gives multicell systems a
                # stepped, asymmetric skyline instead of one repeated stamp.
                multi_along = along - tower_radius * 0.78
                multi_across = across + tower_radius * 0.52
                multi_q = np.sqrt(
                    (multi_along / max(radius * 0.68, 1.0)) ** 2
                    + (multi_across / max(radius * 0.58, 1.0)) ** 2)
                multi_height = 1.0 - _smoothstep(local_h, 0.68, 0.91)
                core = np.maximum(
                    core,
                    (1.0 - _smoothstep(multi_q, 0.38, 1.0))
                    * multi_height * 0.82,
                )
            morph = (CloudMorphology.TOWERING
                     if cell.kind == ConvectiveKind.TOWERING
                     else CloudMorphology.CUMULONIMBUS)
            tower = core * vertical_profile(local_h, morph)

            if cell.kind != ConvectiveKind.TOWERING:
                # A broad, wind-swept anvil is displaced from the tilted
                # updraft and occupies a deep upper band, not a flat plane.
                anvil_cx = (cell.x * CONVECTIVE_DOMAIN_M
                            + cs * cell.core_radius_m * 0.72)
                anvil_cz = (cell.z * CONVECTIVE_DOMAIN_M
                            + sn * cell.core_radius_m * 0.72)
                adx, adz = xx - anvil_cx, zz - anvil_cz
                aa = adx * cs + adz * sn
                ac = -adx * sn + adz * cs
                # Real supercell anvils spread mainly down-shear. A symmetric
                # ellipse put the observer under a 250 km ceiling before the
                # tower was even visible. Keep a tight upwind lip and an epic
                # trailing shield instead.
                anvil_length = (0.72, 0.58, 1.00, 0.68)[variant]
                anvil_width = (0.72, 0.72, 0.60, 0.72)[variant]
                downwind_scale = (cell.core_radius_m * cell.anvil_spread
                                  * max(cell.aspect, 0.86) * anvil_length)
                upwind_scale = cell.core_radius_m * 0.72
                along_scale = np.where(aa >= 0.0, downwind_scale,
                                       upwind_scale)
                anvil_q = np.sqrt(
                    (aa / np.maximum(along_scale, 1.0)) ** 2
                    + (ac / (cell.core_radius_m * cell.anvil_spread
                             * 0.50 * anvil_width)) ** 2)
                anvil_shape = 1.0 - _smoothstep(anvil_q, 0.46, 1.02)
                # The cap height/thickness undulates with seeded controls and
                # droops toward the spreading edge. This avoids a perfectly
                # flat flying-saucer slab while retaining the huge silhouette.
                rag = (0.58 * controls.height + 0.42 * controls.shear - 0.5)
                edge_droop = np.clip(anvil_q, 0.0, 1.0) ** 1.4
                local_hi = (cell.top_m + rag * depth * 0.075
                            - edge_droop * depth * 0.032
                            + max(120.0, cell.overshoot_m * 0.08))
                cap_depth = (0.17, 0.12, 0.20, 0.16)[variant]
                local_lo = (cell.top_m - depth * cap_depth
                            + rag * depth * 0.045
                            - edge_droop * depth * 0.07)
                anvil_band = (
                    _smoothstep(y, local_lo, local_lo + depth * 0.055)
                    * (1.0 - _smoothstep(
                        y, local_hi - depth * 0.055, local_hi)))
                # Pulse/calvus storms deliberately have no mature incus yet;
                # their overshooting crown is the silhouette. This prevents
                # every thunderstorm from inheriting the same detached disk.
                anvil_gain = (0.88, 0.0, 0.92, 0.75)[variant]
                tower = np.maximum(
                    tower, anvil_shape * anvil_band
                    * (0.78 + 0.22 * controls.strata) * anvil_gain)

                # Low shelf/wall-cloud structure wraps the inflow side while
                # leaving a rain-free notch beneath the rotating core.
                shelf_h = np.exp(-((local_h - 0.20) / 0.105) ** 2)
                shelf_ring = (_smoothstep(q, 0.48, 0.72)
                              * (1.0 - _smoothstep(q, 1.02, 1.32)))
                inflow = np.clip(0.62 - along
                                 / max(cell.core_radius_m * 2.4, 1.0),
                                 0.18, 1.0)
                tower = np.maximum(tower,
                                   shelf_ring * shelf_h * inflow * 0.68)

            if cell.overshoot_m > 0.0:
                # Compact dome above the main equilibrium top.
                oy = (y - (cell.top_m - depth * 0.035)) \
                    / max(cell.overshoot_m + depth * 0.035, 1.0)
                if 0.0 <= oy <= 1.0:
                    dome_gain = (0.32, 0.44, 0.28, 0.35)[variant]
                    dome_radius = cell.core_radius_m * (
                        dome_gain - min(dome_gain - 0.10, 0.24) * oy)
                    dome_q = np.sqrt(
                        (along / max(dome_radius * 0.88, 1.0)) ** 2
                        + (across / max(dome_radius, 1.0)) ** 2)
                    dome = (1.0 - _smoothstep(dome_q, 0.36, 1.0)) \
                        * (1.0 - _smoothstep(oy, 0.55, 1.0))
                    tower = np.maximum(tower, dome * 0.92)

            tower *= cell.intensity * preset.supercells.density_scale
            layer = np.maximum(layer, tower)

        layer = np.where(layer >= 0.014, layer, 0.0)
        out[iy] = (np.clip(layer, 0.0, 0.98) * 255.0 + 0.5).astype(
            np.uint8)
    return out, float(base_m), float(top_m)


def build_occupancy(density: np.ndarray,
                    block: int = OCCUPANCY_BLOCK) -> np.ndarray:
    """Max-pool then dilate a conservative periodic occupancy volume.

    Horizontal dilation wraps with the field. Vertical dilation is clamped to
    the layer rather than wrapping cloud tops into cloud bases.
    """

    arr = np.asarray(density)
    if arr.ndim != 3:
        raise ValueError("density must be a 3D [y,z,x] array")
    b = int(block)
    if b <= 0 or any(n % b for n in arr.shape):
        raise ValueError("occupancy block must evenly divide every axis")
    y, z, x = arr.shape
    pooled = arr.reshape(y // b, b, z // b, b, x // b, b).max(
        axis=(1, 3, 5)) > 0

    # One-cell dilation covers trilinear support and lets a future DDA stop at
    # a guaranteed-safe boundary. Use rolls only on periodic x/z.
    horizontal = np.zeros_like(pooled)
    for dz in (-1, 0, 1):
        for dx in (-1, 0, 1):
            horizontal |= np.roll(pooled, (dz, dx), axis=(1, 2))
    dilated = horizontal.copy()
    dilated[1:] |= horizontal[:-1]
    dilated[:-1] |= horizontal[1:]
    return (dilated.astype(np.uint8) * 255)


def _high_cloud_map(preset: WeatherPreset, controls: ControlFields,
                    style: CloudStyle) -> np.ndarray:
    high = preset.high
    if high.cirrus_coverage <= 0.0 and high.strata_coverage <= 0.0:
        return np.zeros((CIRRUS_N, CIRRUS_N, 2), dtype=np.uint8)

    n = CONTROL_N
    coord = np.arange(n, dtype=np.float32) / float(n)
    xx = coord[None, :]
    zz = coord[:, None]
    kx, kz = style.cirrus_wave
    cx, cz = style.cirrus_cross_wave
    phase_main = (2.0 * np.pi * (
        xx * kx + zz * kz + (controls.warp - 0.5) * style.cirrus_warp)
        + style.cirrus_phase)
    phase_cross = (2.0 * np.pi * (
        xx * cx + zz * cz + (controls.cirrus - 0.5) * 1.7)
        - style.cirrus_phase * 0.37)
    fibers = np.clip(0.5 + 0.34 * np.sin(phase_main)
                     + 0.16 * np.sin(phase_cross), 0.0, 1.0)
    streak_basis = (0.34 * controls.strata + 0.22 * controls.puff
                    + 0.22 * controls.cirrus + 0.22 * fibers)
    cirrus = _coverage_mask(streak_basis, high.cirrus_coverage)
    cirrus *= 0.60 + 0.40 * fibers

    strata_basis = (0.66 * controls.strata + 0.20 * controls.mass
                    + 0.14 * controls.cirrus)
    strata = _coverage_mask(strata_basis, high.strata_coverage)
    small = np.stack((cirrus, strata), axis=-1)
    full = np.repeat(np.repeat(small, 2, axis=0), 2, axis=1)
    return (np.clip(full, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def _shadow_map(lower: np.ndarray, upper: np.ndarray, storm: np.ndarray,
                cirrus: np.ndarray) -> np.ndarray:
    if storm.any():
        # Severe systems own the ground-darkening map. Their independent
        # 800 km period cannot be mixed with the ambient 196 km shadow map.
        severe = storm.max(axis=0).astype(np.float32) / 255.0
        # Resample to the renderer's fixed shadow-map contract even when the
        # independent storm field uses a non-power-of-two visual resolution.
        idx = np.floor(np.arange(CIRRUS_N, dtype=np.float32)
                       * severe.shape[0] / CIRRUS_N).astype(np.intp)
        severe = severe[idx[:, None], idx[None, :]]
        return (np.clip(severe * 0.94, 0.0, 1.0) * 255.0 + 0.5).astype(
            np.uint8)
    low = lower.max(axis=0).astype(np.float32) / 255.0
    high = upper.max(axis=0).astype(np.float32) / 255.0
    volume = np.maximum(low, high * 0.92)
    volume = np.repeat(np.repeat(volume, 2, axis=0), 2, axis=1)
    high_cirrus = cirrus[..., 0].astype(np.float32) / 255.0
    high_strata = cirrus[..., 1].astype(np.float32) / 255.0
    # Cirrus remains optically thin, but the densest streaks should register
    # a faint shadow rather than being disconnected from the shared field.
    thin = np.maximum(high_cirrus * 0.08, high_strata * 0.24)
    # Volume and high maps use different declared world periods. Never merge
    # them into one texture whose sampler can represent only one period.
    shadow = volume if volume.any() else thin
    return (np.clip(shadow, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def _metadata(field: CloudField) -> dict:
    return {
        "cache_version": np.asarray(FIELD_CACHE_VERSION),
        "seed": np.asarray(field.seed, dtype=np.int64),
        "preset_id": np.asarray(field.preset_id, dtype=np.int16),
        "recipe_key": np.asarray(field.recipe_key),
        "lower_density": field.lower_density,
        "upper_density": field.upper_density,
        "storm_density": field.storm_density,
        "lower_occupancy": field.lower_occupancy,
        "upper_occupancy": field.upper_occupancy,
        "storm_occupancy": field.storm_occupancy,
        "cirrus": field.cirrus,
        "shadow": field.shadow,
        "layer_bounds": np.asarray([
            field.lower_base_m, field.lower_top_m,
            field.upper_base_m, field.upper_top_m,
            field.storm_base_m, field.storm_top_m,
        ], dtype=np.float32),
    }


def _field_from_npz(z, seed: int, preset: WeatherPreset) -> CloudField:
    required = {
        "cache_version", "seed", "preset_id", "recipe_key",
        "lower_density", "upper_density", "storm_density",
        "lower_occupancy", "upper_occupancy", "storm_occupancy",
        "cirrus", "shadow", "layer_bounds",
    }
    if not required.issubset(z.files):
        raise ValueError("cloud-field cache is missing arrays")
    if str(z["cache_version"].item()) != FIELD_CACHE_VERSION:
        raise ValueError("cloud-field cache version mismatch")
    if int(z["seed"].item()) != int(seed):
        raise ValueError("cloud-field cache seed mismatch")
    if int(z["preset_id"].item()) != int(preset.preset_id):
        raise ValueError("cloud-field cache preset mismatch")
    recipe_key = weather_recipe_key(preset)
    if str(z["recipe_key"].item()) != recipe_key:
        raise ValueError("cloud-field cache recipe mismatch")

    arrays = {
        "lower_density": z["lower_density"],
        "upper_density": z["upper_density"],
        "storm_density": z["storm_density"],
        "lower_occupancy": z["lower_occupancy"],
        "upper_occupancy": z["upper_occupancy"],
        "storm_occupancy": z["storm_occupancy"],
        "cirrus": z["cirrus"],
        "shadow": z["shadow"],
    }
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
    for name, arr in arrays.items():
        if arr.shape != expected[name] or arr.dtype != np.uint8:
            raise ValueError(f"invalid cached {name}")
    bounds = np.asarray(z["layer_bounds"], dtype=np.float32)
    if bounds.shape != (6,) or not np.isfinite(bounds).all():
        raise ValueError("invalid cached layer bounds")
    expected_bounds = np.asarray([
        preset.lower.base_m, preset.lower.top_m,
        preset.upper.base_m, preset.upper.top_m,
        bounds[4], bounds[5],
    ], dtype=np.float32)
    if not np.array_equal(bounds[:4], expected_bounds[:4]):
        raise ValueError("cloud-field cache layer bounds mismatch")
    if not 0.0 <= bounds[4] < bounds[5]:
        raise ValueError("invalid cached storm bounds")
    for layer in (preset.lower, preset.upper):
        if layer.enabled and not layer.base_m < layer.top_m:
            raise ValueError("invalid cloud-field preset layer bounds")
    return CloudField(int(seed), int(preset.preset_id), recipe_key,
                      arrays["lower_density"], arrays["upper_density"],
                      arrays["storm_density"], arrays["lower_occupancy"],
                      arrays["upper_occupancy"], arrays["storm_occupancy"],
                      arrays["cirrus"], arrays["shadow"],
                      *(float(v) for v in bounds))


def _build(seed: int, preset: WeatherPreset) -> CloudField:
    controls = build_control_fields(seed, CONTROL_N)
    style = cloud_style(seed)
    cells = build_storm_cells(seed, preset)
    lower = _layer_density(preset.lower, LOWER_SHAPE, controls, cells,
                           style, upper=False)
    upper = _layer_density(preset.upper, UPPER_SHAPE, controls, cells,
                           style, upper=True)
    supercells = build_supercells(seed, preset)
    storm_controls = build_control_fields(seed, STORM_SHAPE[2])
    storm, storm_base, storm_top = _supercell_density(
        preset, supercells, storm_controls)
    lower_occ = build_occupancy(lower)
    upper_occ = build_occupancy(upper)
    storm_occ = build_occupancy(storm, STORM_OCCUPANCY_BLOCK)
    cirrus = _high_cloud_map(preset, controls, style)
    shadow = _shadow_map(lower, upper, storm, cirrus)
    return CloudField(
        int(seed), preset.preset_id, weather_recipe_key(preset),
        lower, upper, storm, lower_occ, upper_occ, storm_occ, cirrus, shadow,
        float(preset.lower.base_m), float(preset.lower.top_m),
        float(preset.upper.base_m), float(preset.upper.top_m),
        storm_base, storm_top,
    )


def build_cloud_field(seed: int, preset=1, cache_dir=Path("cache")) -> CloudField:
    """Build/load one deterministic V2 cloud field.

    ``cache_dir=None`` disables disk I/O for tests. Corrupt or stale caches
    regenerate safely. V2 names never collide with legacy ``clouds_v6`` files.
    """

    spec = weather_preset(preset)
    path = None if cache_dir is None else cache_path(cache_dir, seed, spec)
    if path is not None and path.exists():
        try:
            with np.load(path, allow_pickle=False) as z:
                return _field_from_npz(z, seed, spec)
        except (OSError, ValueError, KeyError, EOFError, BadZipFile):
            pass

    field = _build(int(seed), spec)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp")
        try:
            with open(temp, "wb") as fh:
                np.savez_compressed(fh, **_metadata(field))
            os.replace(temp, path)
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
    return field
