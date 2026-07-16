"""Record a missile's flight as VIDEO + synchronized telemetry (AI eyes).

usage: python -m tools.record_missile_chase [oniks|s300] [--fps N]
           [--max-s S] [--range-km R]
       (defaults: oniks --fps 6 --max-s 90 --range-km 120)

Purpose (AI-testability, 2026-07-17): "what if the AI could also SEE the
missile fly?"  This boots the real app hidden, fires through the real
launch pipeline (muzzle blast, plumes, trails and all), and follows the
round with a chase camera, capturing:

    renders/chase/<weapon>/frames/frame_0000.png ...   (one per 1/fps sim-s)
    renders/chase/<weapon>/telemetry.json               (per-frame t/pos/vel/
                                                         mach/phase/fuel)
    renders/chase/<weapon>/chase.mp4                    (ffmpeg, if on PATH)
    renders/chase/<weapon>/strip_N.png                  (8-frame contact
                                                         sheets — the quick
                                                         AI-readable view)

Frame files pair 1:1 with telemetry rows, so a reviewing AI can read the
numbers, open the exact frame where something looks wrong, and cite both.
Recording ends at impact/death (+2 s of aftermath) or --max-s.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import numpy as np
import pygame

from main import PHYS_DT, App
from sim.physics import speed_of_sound_scalar
from tools.screenshot_harness import _aim

OUT_ROOT = os.path.join("renders", "chase")
FRAME_W, FRAME_H = 640, 360
STRIP_COLS = 8
WARMUP_FRAMES = 240
AFTERMATH_S = 2.0


def _launch(state, weapon: str, range_km: float):
    """Fire through the real platform pipeline (render_launch_sequences)."""
    if weapon == "oniks":
        state.target_point = np.array([0.0, 0.0, range_km * 1_000.0])
        m = state.request_launch()
    else:                                        # s300 vs the air patrol
        for _ in range(int(2.0 / PHYS_DT)):      # air tracks form
            state.sim_step(PHYS_DT)
        state.cycle_platform()                   # bastion -> s300
        state.tactical_map.selected_contact = "air_patrol_00"
        m = state.request_launch()
    assert m is not None, f"{weapon} launch refused"
    return m


def _chase_cam(state, m) -> None:
    """Behind-and-above chase framing: pull back with speed so a Mach-2
    round does not outrun its own frame, keep the horizon readable."""
    v = np.asarray(m.vel, dtype=np.float64)
    speed = float(np.linalg.norm(v))
    fwd = v / speed if speed > 1.0 else np.array([0.0, 0.0, 1.0])
    back = 45.0 + 0.06 * speed
    up = 12.0 + 0.02 * speed
    # Slight side offset so the trail reads instead of hiding the round.
    side = np.cross(fwd, np.array([0.0, 1.0, 0.0]))
    n = float(np.linalg.norm(side))
    side = side / n if n > 1e-9 else np.array([1.0, 0.0, 0.0])
    eye = m.pos - fwd * back + side * (back * 0.45)
    eye = eye + np.array([0.0, up, 0.0])
    # Never sink the camera under the sea/terrain.
    floor = state.world.surface_height_at(float(eye[0]), float(eye[2])) + 3.0
    eye[1] = max(float(eye[1]), floor)
    _aim(state, eye, m.pos + fwd * 30.0)


def record(app: App, weapon: str, fps: float, max_s: float,
           range_km: float) -> str:
    from game.sandbox import SandboxState
    app.states.switch(SandboxState(app))
    state = app.state
    state.hud_visible = False
    m = _launch(state, weapon, range_km)

    out_dir = os.path.join(OUT_ROOT, weapon)
    frames_dir = os.path.join(out_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    for old in os.listdir(frames_dir):
        os.remove(os.path.join(frames_dir, old))

    _chase_cam(state, m)
    for _ in range(WARMUP_FRAMES):               # terrain LOD stream-in
        state.render(0.0)
        terrain = getattr(state, "terrain", None)
        if terrain is None or not terrain._jobs:
            break

    telemetry = []
    frame_i = 0
    frame_dt = 1.0 / fps
    next_frame_t = 0.0
    aftermath_until = None
    while True:
        state.sim_step(PHYS_DT)
        t = float(m.t)
        if aftermath_until is None and not m.alive:
            aftermath_until = t + AFTERMATH_S
        if aftermath_until is not None and t >= aftermath_until:
            break
        if t >= max_s:
            break
        if t + 1e-9 < next_frame_t:
            continue
        next_frame_t += frame_dt
        _chase_cam(state, m)
        state.render(0.0)
        surf = app.window.read_pixels_to_surface()
        cell = pygame.transform.smoothscale(surf, (FRAME_W, FRAME_H))
        pygame.image.save(
            cell, os.path.join(frames_dir, f"frame_{frame_i:04d}.png"))
        speed = float(np.linalg.norm(m.vel))
        telemetry.append({
            "frame": frame_i, "t": round(t, 3),
            "pos": [round(float(x), 1) for x in m.pos],
            "vel": [round(float(x), 1) for x in m.vel],
            "speed_mps": round(speed, 1),
            "mach": round(speed / speed_of_sound_scalar(
                float(m.pos[1])), 3),
            "phase": m.phase_label,
            "fuel_kg": round(float(getattr(m, "fuel",
                                           getattr(m, "propellant", 0.0))),
                             1),
            "alive": bool(m.alive),
        })
        frame_i += 1

    with open(os.path.join(out_dir, "telemetry.json"), "w",
              encoding="utf-8") as f:
        json.dump(telemetry, f, indent=1)

    # Contact-sheet strips: 8 frames per row, evenly sampled — the quick
    # AI-readable view (an image tool call per strip, not per frame).
    font = pygame.font.SysFont("consolas", 14)
    if frame_i:
        sample = np.linspace(0, frame_i - 1, min(frame_i, STRIP_COLS * 3),
                             dtype=int)
        for s in range(0, len(sample), STRIP_COLS):
            row = sample[s:s + STRIP_COLS]
            strip = pygame.Surface((FRAME_W * len(row), FRAME_H))
            for c, fi in enumerate(row):
                img = pygame.image.load(
                    os.path.join(frames_dir, f"frame_{fi:04d}.png"))
                rec = telemetry[fi]
                label = font.render(
                    f"t={rec['t']:.1f}s {rec['phase']} M{rec['mach']:.2f} "
                    f"alt {rec['pos'][1]:.0f} m", True, (255, 220, 120))
                img.blit(label, (8, 6))
                strip.blit(img, (FRAME_W * c, 0))
            pygame.image.save(
                strip, os.path.join(out_dir, f"strip_{s // STRIP_COLS}.png"))

    # mp4 for humans (ffmpeg optional; frames+strips are the AI contract).
    if shutil.which("ffmpeg"):
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
             "-i", os.path.join(frames_dir, "frame_%04d.png"),
             "-pix_fmt", "yuv420p", os.path.join(out_dir, "chase.mp4")],
            check=False)
    return os.path.abspath(out_dir)


def main(argv: list[str]) -> int:
    weapon = "oniks"
    fps, max_s, range_km = 6.0, 90.0, 120.0
    it = iter(argv)
    for a in it:
        if a == "--fps":
            fps = float(next(it))
        elif a == "--max-s":
            max_s = float(next(it))
        elif a == "--range-km":
            range_km = float(next(it))
        else:
            weapon = a
    if weapon not in ("oniks", "s300"):
        raise SystemExit("weapon must be oniks or s300")
    app = App(hidden=True)
    out = record(app, weapon, fps, max_s, range_km)
    print(f"saved {out}")
    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
