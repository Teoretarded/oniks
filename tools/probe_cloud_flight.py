"""Cloud flight recorder (playtest round 4, 2026-07-07): stills can't show
temporal artifacts, so fly a scripted 5 s approach at the DENSEST cloud
cluster and record it three ways:

* renders/flight_{pass}_seed{N}.gif      — 10 fps GIF for the human
* renders/flight_{pass}_sheet{1,2}.png   — filmstrip contact sheets for
  an AI reviewer (12 frames each, chronological)
* stdout                                 — per-frame mean|diff| in a
  center crop (temporal-noise number: shimmer/popping shows as spikes)

Passes: below (under the cloud base looking up at the mass), center
(inside the layer band), above (over the tops looking down) — each flies
from ~9 km out to ~2 km from the cluster center.

Run:  python -m tools.probe_cloud_flight [seed]
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pygame

SEC = 5.0
FPS = 10.0
START_DIST_M = 9_000.0
END_DIST_M = 2_000.0
TILE_W, TILE_H = 500, 281


def find_cluster(seed: int):
    """Densest ~9 km cluster block near the play area, from the weathermap.

    World mapping mirrors the shader: wuv = wp.xz / 300 km, u -> array
    axis 1, v -> axis 0.  Search window covers the probe/battle area.
    """
    from world.clouds import WEATHER_N, WEATHER_TILE_M, build_noise
    w = build_noise(seed)["weather"]
    cov, top = w[:, :, 0], w[:, :, 2]
    b = 16                                     # 16 texels ~ 9.4 km blocks
    nb = WEATHER_N // b
    cb = cov.reshape(nb, b, nb, b).mean(axis=(1, 3))
    tb = top.reshape(nb, b, nb, b).mean(axis=(1, 3))
    best, best_ij = -1.0, (0, 0)
    for j in range(nb):
        for i in range(nb):
            x = (i + 0.5) * b / WEATHER_N * WEATHER_TILE_M
            z = (j + 0.5) * b / WEATHER_N * WEATHER_TILE_M
            # Window: the sweep/battle neighborhood (wraps not needed).
            if not (-1.0 <= x <= 120_000.0 and -1.0 <= z <= 120_000.0):
                continue
            if cb[j, i] > best:
                best, best_ij = cb[j, i], (i, j)
    i, j = best_ij
    tx = (i + 0.5) * b / WEATHER_N * WEATHER_TILE_M
    tz = (j + 0.5) * b / WEATHER_N * WEATHER_TILE_M
    top_m = 800.0 + float(tb[j, i]) * (14_000.0 - 800.0)
    print(f"[flight] cluster at ({tx/1000:.1f}, {tz/1000:.1f}) km, "
          f"coverage {best:.2f}, est top {top_m/1000:.1f} km")
    return tx, tz, top_m


def _grab(window):
    from OpenGL.GL import GL_RGB, GL_UNSIGNED_BYTE, glReadPixels
    w, h = window.size()
    buf = glReadPixels(0, 0, w, h, GL_RGB, GL_UNSIGNED_BYTE)
    return pygame.image.frombytes(buf, (w, h), "RGB", True)


def main(seed: int = 7) -> int:
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    tx, tz, top_m = find_cluster(seed)

    from main import App, PHYS_DT
    from PIL import Image
    app = App(hidden=True)
    app.start_sandbox()
    s = app.state
    for _ in range(120):
        s.sim_step(PHYS_DT)
    os.makedirs("renders", exist_ok=True)
    s.hud_visible = False
    s.rig.set_mode("free")

    passes = (
        ("below", 1_000.0, 0.55 * top_m),      # under the base, aim mid-mass
        ("center", 800.0 + 0.45 * (top_m - 800.0), None),  # aim own alt
        ("above", top_m + 1_800.0, 0.85 * top_m),
    )
    n_frames = int(SEC * FPS)
    sim_per_frame = max(1, round((1.0 / FPS) / PHYS_DT))

    for name, alt, aim_y in passes:
        aim = alt if aim_y is None else aim_y
        # Approach heading: from south-west of the cluster, at it.
        ang = math.atan2(tx - (tx - 6_400.0), tz - (tz - 6_400.0))  # 45 deg
        sx, sz = tx - START_DIST_M * math.sin(ang), \
                 tz - START_DIST_M * math.cos(ang)
        frames = []
        # LOD settle at the start point.
        s.rig.freecam.pos = np.array([sx, alt, sz], dtype=np.float64)
        s.rig.freecam.yaw = ang
        s.rig.freecam.pitch = 0.0
        s.rig.update(0.0, None)
        for _ in range(240):
            s.render(1 / 60)
            if not s.terrain._jobs:
                break
        for f in range(n_frames):
            u = f / (n_frames - 1)
            dist = START_DIST_M + (END_DIST_M - START_DIST_M) * u
            cx = tx - dist * math.sin(ang)
            cz = tz - dist * math.cos(ang)
            pitch = math.atan2(aim - alt, dist)
            s.rig.freecam.pos = np.array([cx, alt, cz], dtype=np.float64)
            s.rig.freecam.yaw = ang
            s.rig.freecam.pitch = pitch
            s.rig.update(0.0, None)
            for _ in range(sim_per_frame):
                s.sim_step(PHYS_DT)
            s.render(1 / 60)
            surf = _grab(s.window)
            frames.append(pygame.transform.smoothscale(surf,
                                                       (TILE_W, TILE_H)))
        # Temporal-noise number: mean |diff| between consecutive frames in
        # a center crop (cloud region), 0-255 scale.
        arrs = [pygame.surfarray.array3d(fr).astype(np.int16)
                for fr in frames]
        crop = (slice(TILE_W // 4, 3 * TILE_W // 4),
                slice(TILE_H // 4, 3 * TILE_H // 4))
        diffs = [float(np.abs(a2[crop] - a1[crop]).mean())
                 for a1, a2 in zip(arrs, arrs[1:])]
        print(f"[flight] {name}: frame diff mean {np.mean(diffs):.2f}, "
              f"max {np.max(diffs):.2f} (0-255)")
        # GIF for the human.
        pil = [Image.fromarray(
                   pygame.surfarray.array3d(fr).swapaxes(0, 1))
               for fr in frames]
        gif = f"renders/flight_{name}_seed{seed}.gif"
        pil[0].save(gif, save_all=True, append_images=pil[1:],
                    duration=int(1000 / FPS), loop=0)
        print(f"[flight] wrote {gif}")
        # Filmstrips for the AI reviewer: 2 sheets x 12 frames.
        font = pygame.font.SysFont("consolas", 14)
        picks = np.linspace(0, n_frames - 1, 24).astype(int)
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
    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 7))
