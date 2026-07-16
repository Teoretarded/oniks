"""Scriptable cloud flight recorder.

Default run preserves the original three passes:

    python -m tools.probe_cloud_flight [seed]

Custom choreography:

    python -m tools.probe_cloud_flight --spec docs/examples/flight_barrel_roll.json

Outputs per shot:
* renders/flight_{name}_seed{N}.gif
* renders/flight_{name}_sheet1.png
* renders/flight_{name}_sheet2.png
* stdout per-frame center-crop mean absolute diff metrics
* stdout center-crop FFT coherence metrics against frame 0
* stdout upper-half cloud mask component/fraction stability metrics
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pygame

from tools.cloud_probe_metrics import (gate_failures, lightning_metrics,
                                       repeat_metrics, sequence_metrics)

MAX_FRAMES = 300
DEFAULT_FPS = 10.0
DEFAULT_SEC = 5.0
START_DIST_M = 9_000.0
END_DIST_M = 2_000.0
TILE_W, TILE_H = 500, 281
COHERENCE_PAIRS = (37, 75, 150, 299)
MASK_MARGIN = 12.0
MIN_COMPONENT_PIXELS = 16
DIRECT_MAX_W, DIRECT_MAX_H = 256, 144


class SpecError(ValueError):
    pass


def _vec3(value, field: str) -> np.ndarray:
    if not (isinstance(value, list) and len(value) == 3):
        raise SpecError(f"{field} must be a 3-number list")
    try:
        return np.array([float(value[0]), float(value[1]), float(value[2])],
                        dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise SpecError(f"{field} must contain only numbers") from exc


def _smooth(u: float) -> float:
    return u * u * (3.0 - 2.0 * u)


def _shot_name(name: str) -> str:
    if not isinstance(name, str) or not name:
        raise SpecError("name must be a non-empty string")
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip())
    if not safe:
        raise SpecError("name must contain at least one safe filename character")
    return safe[:80]


def find_cluster(seed: int):
    """Densest ~9 km cloud cluster block near the play area."""
    from world.clouds import CLOUD_BASE_M, CLOUD_TOP_M, WEATHER_N, \
        WEATHER_TILE_M, build_noise
    w = build_noise(seed)["weather"]
    cov, top = w[:, :, 0], w[:, :, 2]
    b = 16
    nb = WEATHER_N // b
    cb = cov.reshape(nb, b, nb, b).mean(axis=(1, 3))
    tb = top.reshape(nb, b, nb, b).mean(axis=(1, 3))
    best, best_ij = -1.0, (0, 0)
    for j in range(nb):
        for i in range(nb):
            x = (i + 0.5) * b / WEATHER_N * WEATHER_TILE_M
            z = (j + 0.5) * b / WEATHER_N * WEATHER_TILE_M
            if not (-1.0 <= x <= 120_000.0 and -1.0 <= z <= 120_000.0):
                continue
            if cb[j, i] > best:
                best, best_ij = float(cb[j, i]), (i, j)
    i, j = best_ij
    tx = (i + 0.5) * b / WEATHER_N * WEATHER_TILE_M
    tz = (j + 0.5) * b / WEATHER_N * WEATHER_TILE_M
    top_m = CLOUD_BASE_M + float(tb[j, i]) * (CLOUD_TOP_M - CLOUD_BASE_M)
    center_y = CLOUD_BASE_M + 0.5 * (top_m - CLOUD_BASE_M)
    print(f"[flight] cluster at ({tx/1000:.1f}, {tz/1000:.1f}) km, "
          f"coverage {best:.2f}, center {center_y/1000:.1f} km, "
          f"est top {top_m/1000:.1f} km")
    return {
        "center": np.array([tx, center_y, tz], dtype=np.float64),
        "top": float(top_m),
        "coverage": best,
    }


def find_cluster_v2(seed: int, preset: int = 1):
    """Densest V2 cluster plus real inside/edge/outside test positions."""
    from sim.atmosphere import (CONVECTIVE_DOMAIN_M, ConvectiveKind,
                                build_supercells, weather_preset)
    from world.cloud_field import DENSITY_TILE_M, build_cloud_field
    from world.clouds import WEATHER_N, WEATHER_TILE_M, build_noise
    from world.clouds_v2 import _MACRO_BIAS
    spec = weather_preset(preset)
    field = build_cloud_field(seed, spec)
    # Towering-cumulus and thunderstorm acceptance must target the upper
    # tower/anvil field. Picking the always-dense lower deck frames empty dark
    # sky and falsely suggests that the storm has no vertical development.
    storm_domain = bool(field.storm_density.any())
    if storm_domain:
        volume = field.storm_density
        base_m, top_m = field.storm_base_m, field.storm_top_m
    elif spec.preset_id in (5, 6) and field.upper_density.any():
        volume = field.upper_density
        base_m, top_m = field.upper_base_m, field.upper_top_m
    else:
        volume = field.lower_density
        base_m, top_m = field.lower_base_m, field.lower_top_m
    if not volume.any():
        volume = field.upper_density
        base_m, top_m = field.upper_base_m, field.upper_top_m
    if not volume.any():
        raise SpecError("selected V2 preset has no volumetric cloud cluster")
    column = volume.max(axis=0).astype(np.float32) / 255.0
    n = int(volume.shape[2])
    selected_cell = None
    if storm_domain:
        tile_m = CONVECTIVE_DOMAIN_M
        score = column
        cells = build_supercells(seed, spec)
        selected_cell = max(
            cells,
            # Prefer a mature/anvil-bearing phenotype for silhouette review
            # when the seed also contains a pulse/calvus cell. Both remain in
            # gameplay; this only chooses the more informative probe target.
            key=lambda cell: (
                cell.kind == ConvectiveKind.TOWERING or cell.variant != 1,
                (cell.top_m + cell.overshoot_m)
                * cell.core_radius_m * cell.intensity,
            ),
        )
        tx = selected_cell.x * tile_m
        tz = selected_cell.z * tile_m
        fi = int(np.floor((tx % tile_m) / tile_m * n)) % n
        fj = int(np.floor((tz % tile_m) / tile_m * n)) % n
        macro = None
        b = 1
        blocks = score
        j, i = fj, fi
    else:
        tile_m = DENSITY_TILE_M
        world_coord = ((np.arange(WEATHER_N, dtype=np.float64) + 0.5)
                       / WEATHER_N * WEATHER_TILE_M)
        field_idx = np.floor(
            np.mod(world_coord, tile_m) / tile_m * n).astype(np.intp)
        repeated = column[field_idx[:, None], field_idx[None, :]]
        weather = build_noise(seed)["weather"][..., 0]
        bias = _MACRO_BIAS.get(spec.preset_id, 0.28)
        u = np.clip((np.clip(weather + bias, 0.0, 1.0)
                     - 0.27) / (0.68 - 0.27), 0.0, 1.0)
        macro = u * u * (3.0 - 2.0 * u)
        score = repeated * macro
        b = 16
        blocks = score.reshape(WEATHER_N // b, b, WEATHER_N // b, b).mean(
            axis=(1, 3))
        j, i = np.unravel_index(int(np.argmax(blocks)), blocks.shape)
        tx = (i + 0.5) * b / WEATHER_N * WEATHER_TILE_M
        tz = (j + 0.5) * b / WEATHER_N * WEATHER_TILE_M
        fi = int(np.floor((tx % tile_m) / tile_m * n)) % n
        fj = int(np.floor((tz % tile_m) / tile_m * n)) % n
    ring = np.arange(-6, 7)
    xi = (fi + ring) % n
    zi = (fj + ring) % n
    vertical = volume[:, zi[:, None], xi[None, :]].mean(axis=(1, 2))
    occupied = np.flatnonzero(vertical > 2.0)
    if occupied.size:
        y0 = base_m + (occupied[0] + 0.5) / len(vertical) * (top_m - base_m)
        y1 = base_m + (occupied[-1] + 0.5) / len(vertical) * (top_m - base_m)
    else:
        y0, y1 = base_m, top_m
    center_y = 0.5 * (y0 + y1)
    best = float(blocks[j, i])

    # Find a genuine horizontal exit from this cluster.  Fixed offsets are
    # unreliable because the 65 km detail field repeats inside a much larger
    # weather region; an apparent "outside" point can land in another lobe.
    y_index = int(np.clip(
        (center_y - base_m) / max(top_m - base_m, 1.0) * len(vertical),
        0, len(vertical) - 1))
    density_slice = volume[y_index].astype(np.float32) / 255.0

    def runtime_density(x: float, z: float) -> float:
        dfi = int(np.floor((x % tile_m) / tile_m * n)) % n
        dfj = int(np.floor((z % tile_m) / tile_m * n)) % n
        value = float(density_slice[dfj, dfi])
        if macro is None:
            return value
        wi = int(np.floor((x % WEATHER_TILE_M) / WEATHER_TILE_M
                          * WEATHER_N)) % WEATHER_N
        wj = int(np.floor((z % WEATHER_TILE_M) / WEATHER_TILE_M
                          * WEATHER_N)) % WEATHER_N
        return float(value * macro[wj, wi])

    if selected_cell is not None:
        # View from upwind: the rotating tower stays in front and its displaced
        # anvil trails behind, producing the recognizable supercell profile.
        direction = np.array([-np.cos(selected_cell.heading_rad), 0.0,
                              -np.sin(selected_cell.heading_rad)])
        # ``heading`` is the down-shear/anvil direction, so its negative is
        # the clean upwind profile view. The baked rotating updraft occupies
        # only the inner system footprint; use that visible core boundary.
        boundary = selected_cell.core_radius_m * 0.58
    else:
        step_m = 500.0
        boundary = None
        direction = np.array([0.0, 0.0, 1.0], dtype=np.float64)
        for angle in np.linspace(0.0, 2.0 * np.pi, 24, endpoint=False):
            ray = np.array([np.sin(angle), 0.0, np.cos(angle)],
                           dtype=np.float64)
            samples = [runtime_density(tx + ray[0] * radius,
                                       tz + ray[2] * radius)
                       for radius in np.arange(0.0, 30_000.0 + step_m,
                                               step_m)]
            for k in range(2, len(samples) - 12):
                if max(samples[k:k + 12]) < 0.01:
                    radius = k * step_m
                    if boundary is None or radius < boundary:
                        boundary = radius
                        direction = ray
                    break
        if boundary is None:
            boundary = 12_000.0

    center = np.array([tx, center_y, tz], dtype=np.float64)
    edge = center + direction * (boundary + 750.0)
    outside = center + direction * (boundary
                                    + (35_000.0 if storm_domain else 6_000.0))
    if selected_cell is None:
        orbit_radius = boundary
    elif selected_cell.kind == ConvectiveKind.TOWERING:
        # Towering cells have no baked anvil; their authored anvil-spread
        # range must not push inspection cameras a hundred kilometres away.
        orbit_radius = max(boundary, selected_cell.core_radius_m * 0.85)
    else:
        anvil_length = (0.72, 0.58, 1.00, 0.68)[
            int(selected_cell.variant) % 4]
        orbit_radius = max(
            boundary,
            selected_cell.core_radius_m * selected_cell.anvil_spread
            * max(selected_cell.aspect, 0.86) * anvil_length,
        )
    print(f"[flight] V2 cluster at ({tx/1000:.1f}, {tz/1000:.1f}) km, "
          f"density {best:.2f}, center {center_y/1000:.1f} km, "
          f"est top {y1/1000:.1f} km, edge {boundary/1000:.1f} km")
    return {
        "center": center,
        "edge": edge,
        "outside": outside,
        "top": float(y1),
        "coverage": best,
        "domain": "storm" if storm_domain else "ambient",
        "base": float(y0),
        "radius": float(orbit_radius),
        "variant": (int(selected_cell.variant)
                    if selected_cell is not None else None),
        "boundary": float(boundary),
    }


def _resolve_cluster_offset(value, cluster, field: str) -> np.ndarray:
    if isinstance(value, dict):
        if set(value.keys()) == {"cluster_offset"}:
            return cluster["center"] + _vec3(value["cluster_offset"], field)
        if set(value.keys()) == {"cluster_point"}:
            name = value["cluster_point"]
            if name not in ("center", "edge", "outside"):
                raise SpecError(
                    f"{field}.cluster_point must be center, edge, or outside")
            return np.asarray(cluster[name], dtype=np.float64).copy()
        raise SpecError(
            f"{field} object must contain cluster_offset or cluster_point")
    raise SpecError(f"{field} must be a 3-number list, 'auto', "
                    "or a cluster-relative object")


def _resolve_point(value, field: str, segment: dict, previous_end, cluster):
    if isinstance(value, list):
        return _vec3(value, field)
    if isinstance(value, dict):
        return _resolve_cluster_offset(value, cluster, field)
    if value == "auto":
        if previous_end is not None:
            return previous_end.copy()
        if "cluster_offset" in segment:
            return cluster["center"] + _vec3(segment["cluster_offset"],
                                             f"{field}.cluster_offset")
        raise SpecError(f"{field}='auto' on the first segment requires "
                        "cluster_offset")
    if value == "cluster_offset":
        if "cluster_offset" not in segment:
            raise SpecError(f"{field}='cluster_offset' requires cluster_offset")
        return cluster["center"] + _vec3(segment["cluster_offset"],
                                         f"{field}.cluster_offset")
    raise SpecError(f"{field} must be a 3-number list, 'auto', "
                    "'cluster_offset', or a cluster-relative object")


def _resolve_look(value, pos, velocity, cluster, field: str):
    if value == "cluster":
        return cluster["center"]
    if value == "velocity":
        n = float(np.linalg.norm(velocity))
        if n < 1e-6:
            raise SpecError(f"{field}='velocity' needs segment motion")
        return pos + velocity / n * 1000.0
    if isinstance(value, list):
        return _vec3(value, field)
    if isinstance(value, dict):
        return _resolve_cluster_offset(value, cluster, field)
    raise SpecError(f"{field} must be 'cluster', 'velocity', a 3-number list, "
                    "or a cluster-relative object")


def _yaw_pitch_to(pos, target):
    d = np.asarray(target, dtype=np.float64) - np.asarray(pos, dtype=np.float64)
    n = float(np.linalg.norm(d))
    if n < 1e-6:
        raise SpecError("look target must not equal camera position")
    yaw = math.atan2(float(d[0]), float(d[2]))
    pitch = math.asin(max(-1.0, min(1.0, float(d[1]) / n)))
    return yaw, pitch


def _validate_segment(seg: dict, idx: int) -> dict:
    if not isinstance(seg, dict):
        raise SpecError(f"segments[{idx}] must be an object")
    if "sec" not in seg:
        raise SpecError(f"segments[{idx}].sec is required")
    try:
        sec = float(seg["sec"])
    except (TypeError, ValueError) as exc:
        raise SpecError(f"segments[{idx}].sec must be a number") from exc
    if sec <= 0.0:
        raise SpecError(f"segments[{idx}].sec must be > 0")
    ease = seg.get("ease", "linear")
    if ease not in ("linear", "smooth"):
        raise SpecError(f"segments[{idx}].ease must be 'linear' or 'smooth'")
    if "from" not in seg or "to" not in seg:
        raise SpecError(f"segments[{idx}] requires from and to")
    look = seg.get("look", "cluster")
    roll = seg.get("roll_deg", [0.0, 0.0])
    if not (isinstance(roll, list) and len(roll) == 2):
        raise SpecError(f"segments[{idx}].roll_deg must be [start,end]")
    try:
        roll = [float(roll[0]), float(roll[1])]
    except (TypeError, ValueError) as exc:
        raise SpecError(f"segments[{idx}].roll_deg must contain numbers") from exc
    out = dict(seg)
    out["sec"] = sec
    out["ease"] = ease
    out["look"] = look
    out["roll_deg"] = roll
    return out


def load_spec(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SpecError(f"cannot read spec {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SpecError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SpecError("spec root must be an object")
    seed = int(data.get("seed", 7))
    fps = float(data.get("fps", DEFAULT_FPS))
    if fps <= 0.0:
        raise SpecError("fps must be > 0")
    segments = data.get("segments")
    if not isinstance(segments, list) or not segments:
        raise SpecError("segments must be a non-empty list")
    checked = [_validate_segment(seg, i) for i, seg in enumerate(segments)]
    total = sum(max(2, int(round(seg["sec"] * fps))) for seg in checked)
    if total > MAX_FRAMES:
        raise SpecError(f"spec has {total} frames; cap is {MAX_FRAMES}")
    return {
        "seed": seed,
        "fps": fps,
        "name": _shot_name(data.get("name", path.stem)),
        "segments": checked,
    }


def default_specs(seed: int, cluster) -> list[dict]:
    tx, center_y, tz = cluster["center"]
    top_m = cluster["top"]
    if "outside" in cluster:
        approach = np.asarray(cluster["outside"], dtype=np.float64) \
            - np.asarray(cluster["center"], dtype=np.float64)
        approach[1] = 0.0
        approach /= max(float(np.linalg.norm(approach)), 1e-6)
        start_xz = np.array([tx, tz]) + approach[[0, 2]] * max(
            START_DIST_M, float(np.linalg.norm(
                np.asarray(cluster["outside"])[[0, 2]] - np.array([tx, tz]))))
        end_xz = np.array([tx, tz]) + approach[[0, 2]] * 500.0
    else:
        ang = math.atan2(6_400.0, 6_400.0)
        start_xz = np.array([tx - START_DIST_M * math.sin(ang),
                             tz - START_DIST_M * math.cos(ang)])
        end_xz = np.array([tx - END_DIST_M * math.sin(ang),
                           tz - END_DIST_M * math.cos(ang)])
    specs = []
    passes = (
        ("below", 1_000.0, 0.55 * top_m),
        ("center", 800.0 + 0.45 * (top_m - 800.0), None),
        ("above", top_m + 1_800.0, 0.85 * top_m),
    )
    for name, alt, aim_y in passes:
        aim = alt if aim_y is None else aim_y
        specs.append({
            "seed": seed,
            "fps": DEFAULT_FPS,
            "name": name,
            "segments": [{
                "sec": DEFAULT_SEC,
                "from": [start_xz[0], alt, start_xz[1]],
                "to": [end_xz[0], alt, end_xz[1]],
                "ease": "linear",
                "look": [tx, aim, tz],
                "roll_deg": [0.0, 0.0],
            }],
        })
    # A forward-looking, high-speed spectator pass models the missile camera
    # that originally exposed camera-relative morphing and edge pop.
    specs.append({
        "seed": seed,
        "fps": DEFAULT_FPS,
        "name": "missile_follow",
        "segments": [{
            "sec": DEFAULT_SEC,
            "from": [start_xz[0], center_y, start_xz[1]],
            "to": [end_xz[0], center_y, end_xz[1]],
            "ease": "linear",
            "look": "velocity",
            "roll_deg": [0.0, 0.0],
        }],
    })
    return specs


def _grab(window):
    from OpenGL.GL import GL_RGB, GL_UNSIGNED_BYTE, glReadPixels
    w, h = window.size()
    buf = glReadPixels(0, 0, w, h, GL_RGB, GL_UNSIGNED_BYTE)
    return pygame.image.frombytes(buf, (w, h), "RGB", True)


def _downsample_field(field: np.ndarray, max_w: int = DIRECT_MAX_W,
                      max_h: int = DIRECT_MAX_H,
                      dtype=np.float16) -> np.ndarray:
    """Deterministically point-sample a GPU field into a bounded metric grid."""
    src = np.asarray(field)
    height, width = src.shape
    ys = np.linspace(0, height - 1, min(height, max_h)).astype(np.intp)
    xs = np.linspace(0, width - 1, min(width, max_w)).astype(np.intp)
    return np.asarray(src[np.ix_(ys, xs)], dtype=dtype)


def _capture_v2_buffers(state, view_id: str = "main"):
    """Read resolved V2 cloud luminance/alpha/first-hit depth.

    Returns ``None`` for legacy/off. OpenGL imports and private V2 target
    access stay inside this diagnostic seam so normal imports remain GL-free.
    """
    clouds = getattr(state, "clouds", None)
    if not getattr(clouds, "using_v2", False):
        return None
    target = getattr(clouds, "_views", {}).get(str(view_id))
    if target is None or not target.history_valid:
        return None
    resolved = target.history[target.history_index]
    from OpenGL import GL as gl
    previous_fbo = int(gl.glGetIntegerv(gl.GL_READ_FRAMEBUFFER_BINDING))
    previous_buffer = int(gl.glGetIntegerv(gl.GL_READ_BUFFER))

    def pixels(raw):
        if isinstance(raw, (bytes, bytearray, memoryview)):
            return np.frombuffer(raw, dtype=np.float32)
        return np.asarray(raw, dtype=np.float32).reshape(-1)

    try:
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, resolved.fbo)
        gl.glReadBuffer(gl.GL_COLOR_ATTACHMENT0)
        rgba_raw = gl.glReadPixels(0, 0, target.width, target.height,
                                   gl.GL_RGBA, gl.GL_FLOAT)
        rgba = pixels(rgba_raw).reshape(
            target.height, target.width, 4)
        gl.glReadBuffer(gl.GL_COLOR_ATTACHMENT1)
        depth_raw = gl.glReadPixels(0, 0, target.width, target.height,
                                    gl.GL_RED, gl.GL_FLOAT)
        depth = pixels(depth_raw).reshape(
            target.height, target.width)
    finally:
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, previous_fbo)
        gl.glReadBuffer(previous_buffer)
    # Orientation does not affect aggregate metrics, but top-left order keeps
    # future debug image dumps aligned with pygame screenshots.
    rgba = np.flipud(rgba)
    depth = np.flipud(depth)
    alpha = np.clip(rgba[..., 3], 0.0, 1.0)
    rgb = np.maximum(rgba[..., :3], 0.0)
    luma = rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722
    return (_downsample_field(alpha),
            _downsample_field(depth, dtype=np.float32),
            _downsample_field(luma))


def _coherence_pair(a: np.ndarray, b: np.ndarray) -> tuple[float, tuple[int, int]]:
    a0 = a.astype(np.float32) - float(a.mean())
    b0 = b.astype(np.float32) - float(b.mean())
    norm = float(np.linalg.norm(a0) * np.linalg.norm(b0))
    if norm <= 1e-6:
        return 0.0, (0, 0)
    corr = np.fft.ifft2(np.fft.fft2(a0) * np.conj(np.fft.fft2(b0))).real
    corr /= norm
    peak_idx = np.unravel_index(int(np.argmax(corr)), corr.shape)
    peak = max(0.0, min(1.0, float(corr[peak_idx])))
    dx, dy = int(peak_idx[0]), int(peak_idx[1])
    if dx > corr.shape[0] // 2:
        dx -= corr.shape[0]
    if dy > corr.shape[1] // 2:
        dy -= corr.shape[1]
    return peak, (dx, dy)


def _cloud_mask_stats(arr: np.ndarray) -> tuple[int, float]:
    rgb = arr.astype(np.float32)
    lum = rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722
    upper = lum[:, :TILE_H // 2]
    # Use side strips as the local sky/backdrop estimate so a cloud filling
    # the center of the frame does not raise its own threshold.
    strip_w = max(8, upper.shape[0] // 10)
    backdrop = np.concatenate((upper[:strip_w, :].ravel(),
                               upper[-strip_w:, :].ravel()))
    thresh = float(np.median(backdrop)) + MASK_MARGIN
    mask = upper > thresh
    components = _count_components(mask)
    return components, float(mask.mean())


def _count_components(mask: np.ndarray) -> int:
    h, w = int(mask.shape[1]), int(mask.shape[0])
    seen = np.zeros(mask.shape, dtype=np.bool_)
    count = 0
    for x in range(w):
        for y in range(h):
            if seen[x, y] or not mask[x, y]:
                continue
            stack = [(x, y)]
            seen[x, y] = True
            size = 0
            while stack:
                cx, cy = stack.pop()
                size += 1
                for nx, ny in ((cx - 1, cy), (cx + 1, cy),
                               (cx, cy - 1), (cx, cy + 1)):
                    if (0 <= nx < w and 0 <= ny < h
                            and not seen[nx, ny] and mask[nx, ny]):
                        seen[nx, ny] = True
                        stack.append((nx, ny))
            if size >= MIN_COMPONENT_PIXELS:
                count += 1
    return count


def _apply_camera(state, pos, target, roll_rad):
    yaw, pitch = _yaw_pitch_to(pos, target)
    state.rig.freecam.pos = np.asarray(pos, dtype=np.float64)
    state.rig.freecam.yaw = yaw
    state.rig.freecam.pitch = pitch
    state.rig.freecam.roll = float(roll_rad)
    state.rig.update(0.0, None)


def _settle_terrain(state):
    for _ in range(240):
        state.render(1 / 60)
        if not state.terrain._jobs:
            break


def _frames_for_spec(spec: dict, cluster) -> list[tuple[np.ndarray, np.ndarray, float]]:
    fps = float(spec["fps"])
    previous_end = None
    frames = []
    for idx, segment in enumerate(spec["segments"]):
        start = _resolve_point(segment["from"], f"segments[{idx}].from",
                               segment, previous_end, cluster)
        end = _resolve_point(segment["to"], f"segments[{idx}].to",
                             segment, previous_end, cluster)
        n = max(2, int(round(float(segment["sec"]) * fps)))
        ease = segment["ease"]
        roll0, roll1 = segment["roll_deg"]
        velocity = end - start
        for f in range(n):
            u0 = f / (n - 1)
            u = _smooth(u0) if ease == "smooth" else u0
            pos = start * (1.0 - u) + end * u
            target = _resolve_look(segment["look"], pos, velocity, cluster,
                                   f"segments[{idx}].look")
            if float(np.linalg.norm(target - pos)) < 1e-6:
                vn = float(np.linalg.norm(velocity))
                if vn > 1e-6:
                    target = pos + velocity / vn * 1000.0
                else:
                    target = pos + np.array([0.0, 0.0, 1000.0],
                                            dtype=np.float64)
            roll = math.radians(roll0 + (roll1 - roll0) * u0)
            frames.append((pos, target, roll))
        previous_end = end
    if len(frames) > MAX_FRAMES:
        raise SpecError(f"resolved spec has {len(frames)} frames; "
                        f"cap is {MAX_FRAMES}")
    return frames


def render_spec(state, spec: dict, cluster, gate_profile: str = "auto",
                freeze_cloud_time: bool = False) -> dict:
    from main import PHYS_DT
    from PIL import Image
    name, seed, fps = spec["name"], int(spec["seed"]), float(spec["fps"])
    path_frames = _frames_for_spec(spec, cluster)
    sim_per_frame = max(1, round((1.0 / fps) / PHYS_DT))
    _apply_camera(state, path_frames[0][0], path_frames[0][1],
                  path_frames[0][2])
    _settle_terrain(state)
    state._cloud_time = 0.0
    clouds = getattr(state, "clouds", None)
    if clouds is not None and hasattr(clouds, "reset_history"):
        clouds.reset_history("main")
    requested = getattr(state, "_cloud_signature", ("legacy",))[0]
    if requested == "v2" and not getattr(clouds, "using_v2", False):
        raise SpecError("requested V2 but renderer entered legacy fallback")

    frames = []
    direct_alpha, direct_depth, direct_luma = [], [], []
    for pos, target, roll in path_frames:
        _apply_camera(state, pos, target, roll)
        for _ in range(sim_per_frame):
            state.sim_step(PHYS_DT)
        state.render(0.0 if freeze_cloud_time else 1.0 / fps)
        direct = _capture_v2_buffers(state)
        if direct is not None:
            alpha, depth, luma = direct
            direct_alpha.append(alpha)
            direct_depth.append(depth)
            direct_luma.append(luma)
        surf = _grab(state.window)
        frames.append(pygame.transform.smoothscale(surf, (TILE_W, TILE_H)))

    arrs = [pygame.surfarray.array3d(fr).astype(np.int16) for fr in frames]
    crop = (slice(TILE_W // 4, 3 * TILE_W // 4),
            slice(TILE_H // 4, 3 * TILE_H // 4))
    diffs = [float(np.abs(a2[crop] - a1[crop]).mean())
             for a1, a2 in zip(arrs, arrs[1:])]
    if diffs:
        print(f"[flight] {name}: frame diff mean {np.mean(diffs):.2f}, "
              f"max {np.max(diffs):.2f} (0-255)")
        print(f"[flight] {name}: per-frame diffs "
              + ",".join(f"{d:.2f}" for d in diffs))
    else:
        print(f"[flight] {name}: one frame, no diff metric")

    grays = [arr[crop].astype(np.float32).mean(axis=2) for arr in arrs]
    for idx in COHERENCE_PAIRS:
        if idx >= len(grays):
            continue
        peak, (dx, dy) = _coherence_pair(grays[0], grays[idx])
        print(f"[flight] {name}: coherence 0-{idx} peak {peak:.3f} "
              f"offset ({dx},{dy}) px")

    mask_stats = [_cloud_mask_stats(arr) for arr in arrs]
    counts = np.array([c for c, _ in mask_stats], dtype=np.int32)
    fracs = np.array([f for _, f in mask_stats], dtype=np.float32)
    if len(counts) > 1:
        count_d = np.diff(counts)
        frac_d = np.diff(fracs)
        max_comp_jump = int(np.max(np.abs(count_d)))
        max_comp_drop = int(max(0, -np.min(count_d)))
        worst_frac_drop = float(max(0.0, -np.min(frac_d)))
        worst_frac_step = float(np.max(np.abs(frac_d)))
    else:
        max_comp_jump = 0
        max_comp_drop = 0
        worst_frac_drop = 0.0
        worst_frac_step = 0.0
    print(f"[flight] {name}: structure max_comp_change {max_comp_jump}, "
          f"max_comp_disappear {max_comp_drop}, "
          f"worst_mask_drop {worst_frac_drop:.4f}, "
          f"worst_mask_step {worst_frac_step:.4f}, "
          f"mask_start {fracs[0]:.4f}, mask_end {fracs[-1]:.4f}")
    print(f"[flight] {name}: structure components "
          + ",".join(str(int(c)) for c in counts))
    print(f"[flight] {name}: structure mask_frac "
          + ",".join(f"{float(f):.4f}" for f in fracs))

    metric_profile = gate_profile
    if metric_profile == "auto":
        positions = np.asarray([frame[0] for frame in path_frames])
        stationary = bool(np.allclose(positions, positions[0], atol=1e-6))
        metric_profile = ("stationary" if stationary else
                          "approach" if any(token in name.lower() for token in
                          ("approach", "missile", "500m", "pop")) else "motion")
    direct_metrics = None
    failures = []
    if direct_alpha:
        direct_metrics = sequence_metrics(direct_alpha, direct_depth)
        failures = gate_failures(direct_metrics, metric_profile)
        verdict = "PASS" if not failures else "FAIL"
        print(f"[flight] {name}: direct {metric_profile} {verdict} "
              f"alpha_p95={direct_metrics['alpha_mae_p95']:.5f} "
              f"coverage_drop={direct_metrics['max_coverage_drop']:.5f} "
              f"component_disappear={direct_metrics['max_component_disappear']}")
        for failure in failures:
            print(f"[flight] {name}: gate {failure}")

    pil = [Image.fromarray(pygame.surfarray.array3d(fr).swapaxes(0, 1))
           for fr in frames]
    clouds = getattr(state, "clouds", None)
    backend = getattr(clouds, "backend_name", "off")
    quality = getattr(clouds, "quality", "native")
    tag = f"{backend}_{quality}"
    gif = f"renders/flight_{name}_{tag}_seed{seed}.gif"
    pil[0].save(gif, save_all=True, append_images=pil[1:],
                duration=int(1000 / fps), loop=0)
    print(f"[flight] wrote {gif}")

    font = pygame.font.SysFont("consolas", 14)
    picks = np.linspace(0, len(frames) - 1, 24).astype(int)
    for sheet_i in range(2):
        sheet = pygame.Surface((TILE_W * 3, TILE_H * 4))
        for k in range(12):
            idx = int(picks[sheet_i * 12 + k])
            th = frames[idx].copy()
            th.blit(font.render(f"{name} f{idx}", True,
                                (255, 220, 40), (0, 0, 0)), (6, 6))
            sheet.blit(th, ((k % 3) * TILE_W, (k // 3) * TILE_H))
        path = f"renders/flight_{name}_{tag}_sheet{sheet_i + 1}.png"
        pygame.image.save(sheet, path)
        print(f"[flight] wrote {path}")

    report = {
        "name": name,
        "seed": seed,
        "fps": fps,
        "renderer": backend,
        "quality": quality,
        "profile": metric_profile,
        "rgb": {
            "frame_diff_mean": float(np.mean(diffs)) if diffs else 0.0,
            "frame_diff_max": float(np.max(diffs)) if diffs else 0.0,
            "max_component_change": max_comp_jump,
            "max_component_disappear": max_comp_drop,
            "worst_mask_drop": worst_frac_drop,
            "worst_mask_step": worst_frac_step,
        },
        "direct": direct_metrics,
        "failures": failures,
        "artifacts": [gif,
                      *[f"renders/flight_{name}_{tag}_sheet{i}.png"
                        for i in (1, 2)]],
    }
    # Storm underbelly watches additionally report localized luminance pulses.
    if any(token in name.lower()
           for token in ("lightning", "storm_underbelly")):
        # Lightning is composited by WeatherEffects after the cloud FBO, so
        # detect the final player-visible pulse rather than cloud-only luma.
        composite_luma = []
        for arr in arrs:
            rgb = arr.astype(np.float32) / 255.0
            composite_luma.append(
                rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152
                + rgb[..., 2] * 0.0722)
        report["lightning"] = lightning_metrics(composite_luma)
        print(f"[flight] {name}: lightning flashes "
              f"{report['lightning']['flash_count']} brightest "
              f"{report['lightning']['brightest_pulse']:.4f}")
    return report


def repeat_check(state, spec: dict, cluster) -> dict:
    """Replay identical camera/cloud-clock choreography twice on V2 buffers."""
    path_frames = _frames_for_spec(spec, cluster)
    fps = float(spec["fps"])
    clouds = getattr(state, "clouds", None)
    if not getattr(clouds, "using_v2", False):
        raise SpecError("repeat check requires an active V2 renderer")

    def replay():
        state._cloud_time = 0.0
        clouds.reset_history("main")
        alpha_frames, depth_frames = [], []
        for pos, target, roll in path_frames:
            _apply_camera(state, pos, target, roll)
            state.render(1.0 / fps)
            direct = _capture_v2_buffers(state)
            if direct is None:
                raise SpecError("V2 direct buffer unavailable during repeat check")
            alpha, depth, _luma = direct
            alpha_frames.append(alpha)
            depth_frames.append(depth)
        return alpha_frames, depth_frames

    alpha_a, depth_a = replay()
    alpha_b, depth_b = replay()
    metrics = repeat_metrics(alpha_a, alpha_b, depth_a, depth_b)
    print(f"[flight] {spec['name']}: repeat alpha_mae "
          f"{metrics['alpha_mae_mean']:.7f}, mismatch "
          f"{metrics['alpha_mismatch_ratio_max']:.7f}, depth_rel_p95 "
          f"{metrics['depth_rel_p95_max']:.7f}")
    return metrics


def _apply_wind0_patch():
    import world.clouds as clouds_mod
    old = "const float WIND_MS       = 3.0;"
    new = "const float WIND_MS       = 0.0;"
    if old not in clouds_mod.CLOUD_FRAG:
        raise SpecError("wind0 patch target not found in CLOUD_FRAG")
    clouds_mod.CLOUD_FRAG = clouds_mod.CLOUD_FRAG.replace(old, new)
    print("[flight] WIND_MS patched to 0.0 for this run")


def _apply_lod0_patch():
    import world.clouds as clouds_mod
    replacements = {
        "float lod_b = clamp(log2(dt_step / 46.9), 0.0, 6.0);":
            "float lod_b = 0.0;",
        "float lod_d = clamp(log2(dt_step / 37.5), 0.0, 4.0);":
            "float lod_d = 0.0;",
        "float lod_w = clamp(log2(dt_step / 586.0), 0.0, 5.0);":
            "float lod_w = 0.0;",
    }
    frag = clouds_mod.CLOUD_FRAG
    for old, new in replacements.items():
        if old not in frag:
            raise SpecError(f"lod0 patch target not found: {old}")
        frag = frag.replace(old, new)
    clouds_mod.CLOUD_FRAG = frag
    print("[flight] texture LOD patched to 0.0 for this run")


def _apply_nojitter_patch():
    import world.clouds as clouds_mod
    old = "float noise0 = hash12(gl_FragCoord.xy);"
    new = "float noise0 = 0.0;"
    if old not in clouds_mod.CLOUD_FRAG:
        raise SpecError("nojitter patch target not found in CLOUD_FRAG")
    clouds_mod.CLOUD_FRAG = clouds_mod.CLOUD_FRAG.replace(old, new)
    print("[flight] screen-space jitter patched to 0.0 for this run")


def _apply_noskip_patch():
    import world.clouds as clouds_mod
    old = "if (mist_run >= 8) skip_mul = min(skip_mul * 2.0, 5.0);"
    new = "skip_mul = 1.0;"
    if old not in clouds_mod.CLOUD_FRAG:
        raise SpecError("noskip patch target not found in CLOUD_FRAG")
    clouds_mod.CLOUD_FRAG = clouds_mod.CLOUD_FRAG.replace(old, new)
    print("[flight] mist skip-ahead patched off for this run")


def _apply_skipcap2_patch():
    import world.clouds as clouds_mod
    old = "if (mist_run >= 8) skip_mul = min(skip_mul * 2.0, 5.0);"
    new = "if (mist_run >= 8) skip_mul = min(skip_mul * 2.0, 2.0);"
    if old not in clouds_mod.CLOUD_FRAG:
        raise SpecError("skipcap2 patch target not found in CLOUD_FRAG")
    clouds_mod.CLOUD_FRAG = clouds_mod.CLOUD_FRAG.replace(old, new)
    print("[flight] mist skip-ahead cap patched to 2.0 for this run")


def _prepare_state(seed: int, wind0: bool = False, lod0: bool = False,
                   nojitter: bool = False, noskip: bool = False,
                   skipcap2: bool = False, renderer: str = "legacy",
                   quality: str = "high", preset: int = 1):
    from main import App, PHYS_DT
    from world.combat_config import CombatConfig

    if wind0:
        _apply_wind0_patch()
    if lod0:
        _apply_lod0_patch()
    if nojitter:
        _apply_nojitter_patch()
    if noskip:
        _apply_noskip_patch()
    if skipcap2:
        _apply_skipcap2_patch()
    os.environ["ONIKS_CLOUD_RENDERER"] = renderer
    os.environ["ONIKS_CLOUD_QUALITY"] = quality
    app = App(hidden=True)
    app.start_combat(CombatConfig(seed=seed, weather_preset=preset))
    state = app.state
    for _ in range(120):
        state.sim_step(PHYS_DT)
    state.hud_visible = False
    state.rig.set_mode("free")
    return app, state


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("seed", nargs="?", type=int, default=7,
                   help="seed for the built-in default shots")
    p.add_argument("--spec", type=Path,
                   help="JSON choreography spec")
    p.add_argument("--override-spec-seed", action="store_true",
                   help="use positional seed even when the JSON names a seed")
    p.add_argument("--wind0", action="store_true",
                   help="patch CLOUD_FRAG WIND_MS to 0.0 for this run")
    p.add_argument("--lod0", action="store_true",
                   help="diagnostic: force textureLod levels to 0.0")
    p.add_argument("--nojitter", action="store_true",
                   help="diagnostic: disable screen-space march jitter")
    p.add_argument("--noskip", action="store_true",
                   help="diagnostic: disable low-density mist skip-ahead")
    p.add_argument("--skipcap2", action="store_true",
                   help="diagnostic: cap mist skip-ahead at 2x")
    p.add_argument("--renderer", choices=("legacy", "v2"), default="legacy")
    p.add_argument("--quality", choices=("low", "med", "high", "ultra"),
                   default="high")
    p.add_argument("--preset", type=int, choices=range(7), default=1)
    p.add_argument("--gate-profile",
                   choices=("auto", "stationary", "approach", "motion"),
                   default="auto",
                   help="direct V2 metric thresholds (default: infer per shot)")
    p.add_argument("--gate", action="store_true",
                   help="exit 1 when any direct V2 metric gate fails")
    p.add_argument("--repeat-check", action="store_true",
                   help="replay each choreography twice and compare V2 buffers")
    p.add_argument("--expect-lightning", action="store_true",
                   help="require at least one localized pulse in lightning shots")
    p.add_argument("--freeze-cloud-time", action="store_true",
                   help="hold weather time fixed (stationary sampling gate)")
    p.add_argument("--report", type=Path,
                   help="JSON report path (default: renders/cloud_metrics_*.json)")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        if args.spec is not None:
            specs = [load_spec(args.spec)]
            seed = int(args.seed if args.override_spec_seed else specs[0]["seed"])
            if args.override_spec_seed:
                specs[0]["seed"] = seed
        else:
            seed = int(args.seed)
            specs = None
        diagnostics = (args.wind0 or args.lod0 or args.nojitter
                       or args.noskip or args.skipcap2)
        if args.renderer != "legacy" and diagnostics:
            raise SpecError("shader patch diagnostics are legacy-only")
        if args.gate and args.renderer != "v2":
            raise SpecError("direct metric gates require --renderer v2")
        cluster = (find_cluster_v2(seed, args.preset)
                   if args.renderer == "v2" else find_cluster(seed))
        if specs is None:
            specs = default_specs(seed, cluster)
        os.makedirs("renders", exist_ok=True)
        app, state = _prepare_state(seed, wind0=args.wind0, lod0=args.lod0,
                                    nojitter=args.nojitter, noskip=args.noskip,
                                    skipcap2=args.skipcap2,
                                    renderer=args.renderer,
                                    quality=args.quality,
                                    preset=args.preset)
        reports = []
        try:
            for spec in specs:
                report = render_spec(state, spec, cluster,
                                     gate_profile=args.gate_profile,
                                     freeze_cloud_time=args.freeze_cloud_time)
                if args.repeat_check:
                    report["repeat"] = repeat_check(state, spec, cluster)
                reports.append(report)
        finally:
            state.dispose()
            pygame.quit()
        if args.expect_lightning:
            watches = [report for report in reports if "lightning" in report]
            if not watches:
                reports[0]["failures"].append("no lightning watch shot was captured")
            elif not any(report["lightning"]["flash_count"] >= 1
                         for report in watches):
                watches[0]["failures"].append(
                    "no deterministic lightning pulse detected")
        report_path = args.report or Path(
            f"renders/cloud_metrics_{args.renderer}_{args.quality}_"
            f"p{args.preset}_seed{seed}.json")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": 1,
            "seed": seed,
            "preset": args.preset,
            "requested_renderer": args.renderer,
            "quality": args.quality,
            "shots": reports,
        }
        report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"[flight] wrote {report_path}")
        failed = [f"{report['name']}: {failure}"
                  for report in reports for failure in report["failures"]]
        if args.gate and failed:
            print("[flight] acceptance FAIL", file=sys.stderr)
            for failure in failed:
                print(f"[flight] {failure}", file=sys.stderr)
            return 1
        return 0
    except SpecError as exc:
        print(f"[flight] spec error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
