"""Launch filmstrips: every missile variant, whole burn, fixed camera.

Boots the real app hidden in the Lauterbrunnen scene, stands the observer
250 m from the pad, fires each round and captures frames at fixed times
(eject, ignition, early boost, mid boost, burnout, aged column), then
pastes them into one contact sheet per variant:

    renders/cinematic_audit/variant_<id>.png

Run after ANY change to game/cinematic_missiles.py and LOOK at the sheets.
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np
import pygame
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import App, PHYS_DT     # noqa: E402
from game.cinematic_missiles import CinematicEffects, VARIANTS  # noqa: E402

OUT = os.path.join("renders", "cinematic_audit")
CAPTURE_TS = (0.6, 1.4, 3.0, 7.0, 14.0, 26.0)
OBSERVER_RANGE = 250.0


def grab(app) -> Image.Image:
    surf = app.window.read_pixels_to_surface()
    data = pygame.image.tostring(surf, "RGB")
    return Image.frombytes("RGB", surf.get_size(), data)


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    app = App(hidden=True)
    app.open_cinematic(os.path.join("assets", "cinematic", "lauterbrunnen"))
    state = app.state
    state.next_auto_launch = 1e9

    # Stand 250 m from the pad with a clear look at it.
    pad = state._pad
    (sx, sz), _ = state.scene.spawn_pos_yaw()
    d = np.array([sx - pad[0], sz - pad[2]])
    d = d / np.linalg.norm(d)
    wx, wz = float(pad[0] + d[0] * OBSERVER_RANGE), \
        float(pad[2] + d[1] * OBSERVER_RANGE)
    w = state.walker
    w.x, w.z = wx, wz
    w.y = w.ground_h(wx, wz)
    w.on_ground = True
    yaw = math.atan2(pad[0] - wx, pad[2] - wz)

    for v in VARIANTS:
        state.variant = v
        state.launches = []
        state.effects = CinematicEffects(seed=3)   # clean pools per round
        state._sound_queue = []
        w.yaw, w.pitch = yaw, math.radians(6.0)
        state._fire()
        frames = []
        t_last = 0.0
        for tcap in CAPTURE_TS:
            steps = int((tcap - t_last) / PHYS_DT)
            for i in range(steps):
                state.sim_step(PHYS_DT)
                if i % 4 == 0:
                    pass                            # sim-only fast forward
            t_last = tcap
            # Aim: pad for the first three, then follow the round upward.
            if tcap >= 3.0 and state.launch is not None:
                rel = state.launch.pos - np.asarray(w.eye)
                w.yaw = math.atan2(rel[0], rel[2])
                w.pitch = min(math.radians(75.0), math.atan2(
                    rel[1], math.hypot(rel[0], rel[2])))
            for _ in range(3):
                state.render(1 / 60.0)
            img = grab(app)
            img = img.resize((img.width // 2, img.height // 2),
                             Image.LANCZOS)
            frames.append((tcap, img))
        fw, fh = frames[0][1].size
        sheet = Image.new("RGB", (fw * 3, fh * 2), (8, 8, 10))
        for i, (tcap, img) in enumerate(frames):
            sheet.paste(img, ((i % 3) * fw, (i // 3) * fh))
        path = os.path.join(OUT, f"variant_{v.id}.png")
        sheet.save(path)
        print(f"[filmstrip] {v.label}: {path}  "
              f"(cols t={CAPTURE_TS})", flush=True)

    app.close_cinematic()
    app.close_testing_lab()
    pygame.quit()


if __name__ == "__main__":
    main()
