"""Pure metrics and suite definitions for deterministic cloud playtests.

No pygame/OpenGL imports live here.  Unit tests use synthetic alpha/depth
sequences, while the GPU probes feed the same functions downsampled V2 render
targets.  The metrics intentionally measure cloud alpha rather than sky RGB:
dark storm clouds and bright fair-weather clouds must be judged identically.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


ALPHA_THRESHOLD = 0.05
MIN_COMPONENT_PIXELS = 8

PRESET_NAMES = (
    "clear", "fair", "partly_cloudy", "overcast", "high_cirrus",
    "towering_cumulus", "thunderstorm",
)

# Deterministic visual coverage.  Clear deliberately has no cluster view;
# high cirrus uses shell-specific views; storm owns the underbelly/watch views.
PRESET_VIEW_PLAN = {
    0: ("ground_horizon", "high_cirrus_below"),
    1: ("cluster_outside", "cluster_edge", "cluster_inside", "cluster_above"),
    2: ("ground_horizon", "cluster_outside", "cluster_edge", "cluster_above"),
    3: ("deck_underbelly", "inside_layer", "above_looking_down"),
    4: ("high_cirrus_below", "high_cirrus_edge", "high_cirrus_above"),
    5: ("tower_underbelly", "tower_wide", "tower_above_far",
        "cluster_edge"),
    6: ("storm_underbelly", "storm_tower_wide", "storm_anvil",
        "storm_above_far", "lightning_watch"),
}

ALTITUDE_SWEEP_M = (60.0, 1_000.0, 4_000.0, 10_000.0,
                    17_500.0, 30_000.0, 50_000.0)


@dataclass(frozen=True)
class GateProfile:
    max_alpha_mae_p95: float
    max_coverage_drop: float
    max_coverage_step: float
    max_component_disappear: int
    min_coverage_max: float


GATE_PROFILES = {
    # Fixed camera and fixed cloud clock after temporal warm-up.
    "stationary": GateProfile(0.003, 0.005, 0.005, 0, 0.01),
    # Camera flies toward one resolved cloud mass. Perspective can change
    # coverage, but a large one-frame loss is the old skip/pop failure.
    "approach": GateProfile(0.035, 0.030, 0.045, 3, 0.01),
    # General moving-camera diagnostic used by below/inside/above sweeps.
    "motion": GateProfile(0.050, 0.050, 0.070, 6, 0.01),
}


def component_count(mask: np.ndarray,
                    min_pixels: int = MIN_COMPONENT_PIXELS) -> int:
    """Count 4-connected mask components at least ``min_pixels`` large."""
    src = np.asarray(mask, dtype=np.bool_)
    if src.ndim != 2:
        raise ValueError("component mask must be 2D")
    height, width = src.shape
    seen = np.zeros_like(src)
    count = 0
    for y in range(height):
        for x in range(width):
            if seen[y, x] or not src[y, x]:
                continue
            seen[y, x] = True
            stack = [(y, x)]
            size = 0
            while stack:
                cy, cx = stack.pop()
                size += 1
                for ny, nx in ((cy - 1, cx), (cy + 1, cx),
                               (cy, cx - 1), (cy, cx + 1)):
                    if (0 <= ny < height and 0 <= nx < width
                            and src[ny, nx] and not seen[ny, nx]):
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            if size >= int(min_pixels):
                count += 1
    return count


def _percentile(values, q: float) -> float:
    return float(np.percentile(values, q)) if values else 0.0


def sequence_metrics(alpha_frames, depth_frames=None,
                     threshold: float = ALPHA_THRESHOLD) -> dict:
    """Summarize adjacent-frame morph/pop behavior from cloud-only buffers."""
    alpha = [np.asarray(frame, dtype=np.float32) for frame in alpha_frames]
    if not alpha:
        raise ValueError("at least one alpha frame is required")
    shape = alpha[0].shape
    if len(shape) != 2 or any(frame.shape != shape for frame in alpha):
        raise ValueError("alpha frames must share one 2D shape")

    masks = [frame >= float(threshold) for frame in alpha]
    coverage = [float(mask.mean()) for mask in masks]
    components = [component_count(mask) for mask in masks]
    alpha_mae = [float(np.abs(b - a).mean())
                 for a, b in zip(alpha, alpha[1:])]
    coverage_delta = np.diff(np.asarray(coverage, dtype=np.float32))
    component_delta = np.diff(np.asarray(components, dtype=np.int32))

    depth_rel_p95 = []
    if depth_frames is not None:
        depth = [np.asarray(frame, dtype=np.float32) for frame in depth_frames]
        if len(depth) != len(alpha) or any(frame.shape != shape for frame in depth):
            raise ValueError("depth frames must match the alpha sequence")
        for da, db, ma, mb in zip(depth, depth[1:], masks, masks[1:]):
            valid = (ma & mb & (da > 0.0) & (db > 0.0)
                     & np.isfinite(da) & np.isfinite(db))
            if valid.any():
                rel = np.abs(db[valid] - da[valid]) / np.maximum(da[valid], 1.0)
                depth_rel_p95.append(float(np.percentile(rel, 95)))

    return {
        "frame_count": len(alpha),
        "buffer_shape": [int(shape[0]), int(shape[1])],
        "coverage_start": coverage[0],
        "coverage_end": coverage[-1],
        "coverage_min": min(coverage),
        "coverage_max": max(coverage),
        "max_coverage_drop": (float(max(0.0, -coverage_delta.min()))
                              if len(coverage_delta) else 0.0),
        "max_coverage_step": (float(np.abs(coverage_delta).max())
                              if len(coverage_delta) else 0.0),
        "component_start": components[0],
        "component_end": components[-1],
        "max_component_change": (int(np.abs(component_delta).max())
                                 if len(component_delta) else 0),
        "max_component_disappear": (int(max(0, -component_delta.min()))
                                    if len(component_delta) else 0),
        "alpha_mae_mean": float(np.mean(alpha_mae)) if alpha_mae else 0.0,
        "alpha_mae_p95": _percentile(alpha_mae, 95),
        "alpha_mae_max": max(alpha_mae, default=0.0),
        "depth_rel_p95_max": max(depth_rel_p95, default=0.0),
    }


def repeat_metrics(alpha_a, alpha_b, depth_a=None, depth_b=None) -> dict:
    """Compare two replays of identical camera/cloud-clock choreography."""
    if len(alpha_a) != len(alpha_b) or not alpha_a:
        raise ValueError("repeat runs must be non-empty and equally long")
    alpha_mae = []
    alpha_max = []
    mismatch = []
    depth_rel = []
    for index, (a, b) in enumerate(zip(alpha_a, alpha_b)):
        aa = np.asarray(a, dtype=np.float32)
        bb = np.asarray(b, dtype=np.float32)
        if aa.shape != bb.shape or aa.ndim != 2:
            raise ValueError("repeat alpha frames must share one 2D shape")
        delta = np.abs(bb - aa)
        alpha_mae.append(float(delta.mean()))
        alpha_max.append(float(delta.max()))
        mismatch.append(float((delta > (1.0 / 255.0)).mean()))
        if depth_a is not None and depth_b is not None:
            da = np.asarray(depth_a[index], dtype=np.float32)
            db = np.asarray(depth_b[index], dtype=np.float32)
            valid = ((aa >= ALPHA_THRESHOLD) & (bb >= ALPHA_THRESHOLD)
                     & (da > 0.0) & (db > 0.0)
                     & np.isfinite(da) & np.isfinite(db))
            if valid.any():
                rel = np.abs(db[valid] - da[valid]) / np.maximum(da[valid], 1.0)
                depth_rel.append(float(np.percentile(rel, 95)))
    return {
        "frame_count": len(alpha_a),
        "alpha_mae_mean": float(np.mean(alpha_mae)),
        "alpha_mae_max": max(alpha_max),
        "alpha_mismatch_ratio_max": max(mismatch),
        "depth_rel_p95_max": max(depth_rel, default=0.0),
    }


def lightning_metrics(luma_frames, flash_threshold: float = 0.08) -> dict:
    """Detect localized positive luminance pulses in a fixed-camera watch.

    The 99.5th percentile rejects a single hot pixel but still catches a
    localized in-cloud flash.  This is deliberately a detector, not proof of
    realism; storm captures still require contact-sheet/GIF review.
    """
    luma = [np.asarray(frame, dtype=np.float32) for frame in luma_frames]
    if len(luma) < 2:
        raise ValueError("lightning detection needs at least two frames")
    shape = luma[0].shape
    if len(shape) != 2 or any(frame.shape != shape for frame in luma):
        raise ValueError("luminance frames must share one 2D shape")
    pulses = []
    for previous, current in zip(luma, luma[1:]):
        positive = np.maximum(current - previous, 0.0)
        pulses.append(float(np.percentile(positive, 99.5)))
    return {
        "frame_count": len(luma),
        "flash_threshold": float(flash_threshold),
        "flash_count": int(sum(value >= flash_threshold for value in pulses)),
        "brightest_pulse": max(pulses, default=0.0),
        "pulse_p95": _percentile(pulses, 95),
    }


def gate_failures(metrics: dict, profile: str) -> list[str]:
    """Return stable, human-readable failures for one metric profile."""
    try:
        gate = GATE_PROFILES[profile]
    except KeyError as exc:
        raise ValueError(f"unknown cloud metric profile {profile!r}") from exc
    failures = []
    checks = (
        ("alpha_mae_p95", gate.max_alpha_mae_p95),
        ("max_coverage_drop", gate.max_coverage_drop),
        ("max_coverage_step", gate.max_coverage_step),
        ("max_component_disappear", gate.max_component_disappear),
    )
    for name, limit in checks:
        value = metrics.get(name)
        if value is None:
            failures.append(f"missing metric {name}")
        elif value > limit:
            failures.append(f"{name}={value:.6g} > {limit:.6g}")
    coverage = metrics.get("coverage_max")
    if coverage is None:
        failures.append("missing metric coverage_max")
    elif coverage < gate.min_coverage_max:
        failures.append(
            f"coverage_max={coverage:.6g} < {gate.min_coverage_max:.6g}")
    return failures
