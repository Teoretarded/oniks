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

MAX_FRAMES = 300
DEFAULT_FPS = 10.0
DEFAULT_SEC = 5.0
START_DIST_M = 9_000.0
END_DIST_M = 2_000.0
TILE_W, TILE_H = 500, 281


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


def _resolve_cluster_offset(value, cluster, field: str) -> np.ndarray:
    if isinstance(value, dict):
        if set(value.keys()) != {"cluster_offset"}:
            raise SpecError(f"{field} object must be {{'cluster_offset': [...]}}")
        return cluster["center"] + _vec3(value["cluster_offset"], field)
    raise SpecError(f"{field} must be a 3-number list, 'auto', "
                    "or {'cluster_offset': [...]}")


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
                    "'cluster_offset', or {'cluster_offset': [...]}")


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
                    "or {'cluster_offset': [...]}")


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
    ang = math.atan2(6_400.0, 6_400.0)
    specs = []
    passes = (
        ("below", 1_000.0, 0.55 * top_m),
        ("center", 800.0 + 0.45 * (top_m - 800.0), None),
        ("above", top_m + 1_800.0, 0.85 * top_m),
    )
    for name, alt, aim_y in passes:
        aim = alt if aim_y is None else aim_y
        sx = tx - START_DIST_M * math.sin(ang)
        sz = tz - START_DIST_M * math.cos(ang)
        ex = tx - END_DIST_M * math.sin(ang)
        ez = tz - END_DIST_M * math.cos(ang)
        specs.append({
            "seed": seed,
            "fps": DEFAULT_FPS,
            "name": name,
            "segments": [{
                "sec": DEFAULT_SEC,
                "from": [sx, alt, sz],
                "to": [ex, alt, ez],
                "ease": "linear",
                "look": [tx, aim, tz],
                "roll_deg": [0.0, 0.0],
            }],
        })
    return specs


def _grab(window):
    from OpenGL.GL import GL_RGB, GL_UNSIGNED_BYTE, glReadPixels
    w, h = window.size()
    buf = glReadPixels(0, 0, w, h, GL_RGB, GL_UNSIGNED_BYTE)
    return pygame.image.frombytes(buf, (w, h), "RGB", True)


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
            roll = math.radians(roll0 + (roll1 - roll0) * u0)
            frames.append((pos, target, roll))
        previous_end = end
    if len(frames) > MAX_FRAMES:
        raise SpecError(f"resolved spec has {len(frames)} frames; "
                        f"cap is {MAX_FRAMES}")
    return frames


def render_spec(state, spec: dict, cluster) -> None:
    from main import PHYS_DT
    from PIL import Image
    name, seed, fps = spec["name"], int(spec["seed"]), float(spec["fps"])
    path_frames = _frames_for_spec(spec, cluster)
    sim_per_frame = max(1, round((1.0 / fps) / PHYS_DT))
    _apply_camera(state, path_frames[0][0], path_frames[0][1],
                  path_frames[0][2])
    _settle_terrain(state)

    frames = []
    for pos, target, roll in path_frames:
        _apply_camera(state, pos, target, roll)
        for _ in range(sim_per_frame):
            state.sim_step(PHYS_DT)
        state.render(1 / 60)
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

    pil = [Image.fromarray(pygame.surfarray.array3d(fr).swapaxes(0, 1))
           for fr in frames]
    gif = f"renders/flight_{name}_seed{seed}.gif"
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
        path = f"renders/flight_{name}_sheet{sheet_i + 1}.png"
        pygame.image.save(sheet, path)
        print(f"[flight] wrote {path}")


def _prepare_state(seed: int):
    from main import App, PHYS_DT
    from world.clouds import Clouds

    app = App(hidden=True)
    app.start_sandbox()
    state = app.state
    if state.clouds is not None:
        state.clouds.delete()
    state.clouds = Clouds(seed)
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
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        if args.spec is not None:
            specs = [load_spec(args.spec)]
            seed = int(specs[0]["seed"])
        else:
            seed = int(args.seed)
            specs = None
        cluster = find_cluster(seed)
        if specs is None:
            specs = default_specs(seed, cluster)
        os.makedirs("renders", exist_ok=True)
        app, state = _prepare_state(seed)
        try:
            for spec in specs:
                render_spec(state, spec, cluster)
        finally:
            pygame.quit()
        return 0
    except SpecError as exc:
        print(f"[flight] spec error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
