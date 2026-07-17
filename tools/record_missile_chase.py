"""Record a missile's flight as VIDEO + synchronized telemetry (AI eyes).

usage: python -m tools.record_missile_chase [oniks|s300]
           [--cam hero|side|chase] [--fps N] [--max-s S] [--range-km R]
           [--out NAME]
       (defaults: oniks --cam hero --fps 6 --max-s 90 --range-km 120)

Purpose (AI-testability, 2026-07-17): "what if the AI could also SEE the
missile fly?"  This boots the real app hidden, fires through the real
launch pipeline (muzzle blast, plumes, trails and all), and follows the
round with a chase camera, capturing:

    renders/chase/<out>/frames/frame_0000.png ...   (one per 1/fps sim-s)
    renders/chase/<out>/telemetry.json               (per-frame flight data)
    renders/chase/<out>/telemetry_full.jsonl         (EVERY 120 Hz substep —
                                                      the complete numeric
                                                      record, ~7200 rows/min)
    renders/chase/<out>/chase.mp4                    (ffmpeg, if on PATH)
    renders/chase/<out>/strip_N.png                  (8-frame contact
                                                      sheets — the quick
                                                      AI-readable view)

Graph the run afterwards with `python -m tools.plot_chase_telemetry <out>`
— stacked time-series panels (gamma vs FC command, AoA, Mach, alt, g, turn
rate, heading) plus a printed anomaly summary. The plot is the fast way to
spot a spin-out, a 180, or guidance divergence before opening any frame.

Camera modes (chosen 2026-07-17 by rendering all three and looking):
    hero   (default)  three-quarter front on the sun side — the airframe
                      is large and lit, nose attitude and plume both read
    side   true side profile — exact body pitch / AoA measurement with no
           foreshortening (the body is smaller in frame than hero)
    chase  the v1 behind-and-above framing — good trail, poor attitude
           (kept for comparison with pre-2026-07-17 captures)

Telemetry per frame (row N pairs 1:1 with frame_N.png):
    t / pos / vel / speed_mps / mach / phase / fuel_kg / alive   (v1 fields)
    gamma_deg        flight-path angle of the velocity vector
    heading_deg      ground-track heading (0 = +Z, clockwise)
    body_pitch_deg   pitch of the slew-limited body axis (body_dir)
    aoa_deg          angle between body axis and velocity — visual AoA
    g_peak           peak proper acceleration (g) over the sim substeps
                     since the previous frame — measured, not guessed
    turn_rate_dps    peak path rotation rate over the same substeps
    alt_agl_m        height above the local surface
    dist_to_go_km    range to the live target (or the launch aim point)
    fc               flight-computer command, when the weapon flies one:
                     mode / cmd_gamma_deg / alt_ref_m / target_mach /
                     normal_g / terminal_commit / plan_id.  Compare
                     cmd_gamma_deg against gamma_deg to see how far the
                     airframe lags its own guidance.

Frame files pair 1:1 with telemetry rows, so a reviewing AI can read the
numbers, open the exact frame where something looks wrong, and cite both.
Recording ends at impact/death (+2 s of aftermath) or --max-s.
"""

from __future__ import annotations

import json
import math
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
G0 = 9.80665
GRAV = np.array([0.0, -G0, 0.0])
UP = np.array([0.0, 1.0, 0.0])
# Horizontal component of the renderer sun direction (see screenshot
# harness _SUN_YAW): the camera stands on this side so the airframe is lit
# rather than silhouetted.
SUN_H = np.array([0.35, 0.0, 0.55])
SUN_H = SUN_H / np.linalg.norm(SUN_H)


def _launch(state, weapon: str, range_km: float):
    """Fire through the real platform pipeline (render_launch_sequences).

    Returns (missile, aim_point) — the aim point is the fallback range
    reference for weapons without a live target object."""
    if weapon == "oniks":
        state.target_point = np.array([0.0, 0.0, range_km * 1_000.0])
        m = state.request_launch()
        aim = np.asarray(state.target_point, dtype=np.float64).copy()
    else:                                        # s300 vs the air patrol
        for _ in range(int(2.0 / PHYS_DT)):      # air tracks form
            state.sim_step(PHYS_DT)
        state.cycle_platform()                   # bastion -> s300
        state.tactical_map.selected_contact = "air_patrol_00"
        m = state.request_launch()
        aim = None
    assert m is not None, f"{weapon} launch refused"
    return m, aim


def _cam_basis(m):
    v = np.asarray(m.vel, dtype=np.float64)
    speed = float(np.linalg.norm(v))
    fwd = v / speed if speed > 1.0 else np.array([0.0, 0.0, 1.0])
    side = np.cross(fwd, UP)
    n = float(np.linalg.norm(side))
    side = side / n if n > 1e-6 else np.array([1.0, 0.0, 0.0])
    if float(side @ SUN_H) < 0.0:
        side = -side                             # stand on the lit side
    return fwd, side, speed


def _chase_cam(state, m, mode: str) -> None:
    """Place the camera for this frame (re-aimed every rendered frame, so
    distances stay exact regardless of speed)."""
    fwd, side, speed = _cam_basis(m)
    pos = np.asarray(m.pos, dtype=np.float64)
    if mode == "chase":
        # v1 framing: pull back with speed, slight side offset.
        back = 45.0 + 0.06 * speed
        eye = pos - fwd * back + side * (back * 0.45)
        eye = eye + np.array([0.0, 12.0 + 0.02 * speed, 0.0])
        look = pos + fwd * 30.0
    elif mode == "hero":
        # Three-quarter front: nose, attitude, oncoming trail.
        d = 46.0 + 0.015 * speed
        eye = pos + fwd * (0.55 * d) + side * (0.8 * d)
        eye = eye + np.array([0.0, 0.18 * d, 0.0])
        look = pos
    else:                                        # side profile
        d = 52.0 + 0.018 * speed
        eye = pos + side * d + np.array([0.0, 6.0 + 0.004 * speed, 0.0])
        look = pos + fwd * 8.0                   # slight lead: nose reads
    floor = state.world.surface_height_at(float(eye[0]), float(eye[2])) + 3.0
    eye[1] = max(float(eye[1]), floor)
    _aim(state, eye, look)


def _angles(m):
    """(gamma, heading, body_pitch, aoa) in degrees from live state."""
    v = np.asarray(m.vel, dtype=np.float64)
    speed = float(np.linalg.norm(v))
    if speed > 1.0:
        gamma = math.degrees(math.atan2(
            float(v[1]), float(np.hypot(v[0], v[2]))))
        heading = math.degrees(math.atan2(float(v[0]), float(v[2]))) % 360.0
    else:
        gamma = 90.0 if float(v[1]) >= 0.0 else -90.0
        heading = 0.0
    body = getattr(m, "body_dir", None)
    if body is not None:
        b = np.asarray(body, dtype=np.float64)
        bn = float(np.linalg.norm(b))
        body_pitch = math.degrees(math.atan2(
            float(b[1]), float(np.hypot(b[0], b[2]))))
        if speed > 1.0 and bn > 1e-9:
            cosa = float(np.clip((b @ v) / (bn * speed), -1.0, 1.0))
            aoa = math.degrees(math.acos(cosa))
        else:
            aoa = 0.0
    else:
        body_pitch, aoa = gamma, 0.0
    return gamma, heading, body_pitch, aoa


def _fc_snapshot(m):
    cmd = getattr(m, "_fc_command", None)
    if cmd is None:
        return None
    return {
        "mode": getattr(cmd.mode, "name", str(cmd.mode)),
        "cmd_gamma_deg": round(math.degrees(
            float(cmd.target_path_gamma_rad)), 2),
        "alt_ref_m": round(float(cmd.altitude_ref_asl_m), 1),
        "target_mach": round(float(cmd.target_mach), 2),
        "normal_g": round(float(cmd.path_normal_accel_mps2) / G0, 2),
        "terminal_commit": bool(cmd.terminal_commit),
        "plan_id": int(cmd.plan_id),
    }


def record(app: App, weapon: str, fps: float, max_s: float,
           range_km: float, cam: str = "side", out: str | None = None) -> str:
    from game.sandbox import SandboxState
    app.states.switch(SandboxState(app))
    state = app.state
    state.hud_visible = False
    m, aim = _launch(state, weapon, range_km)

    out_dir = os.path.join(OUT_ROOT, out or weapon)
    frames_dir = os.path.join(out_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    for old in os.listdir(frames_dir):
        os.remove(os.path.join(frames_dir, old))

    _chase_cam(state, m, cam)
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
    prev_vel = np.asarray(m.vel, dtype=np.float64).copy()
    peak_g = 0.0
    peak_turn = 0.0
    substep = 0
    full_f = open(os.path.join(out_dir, "telemetry_full.jsonl"), "w",
                  encoding="utf-8")
    while True:
        state.sim_step(PHYS_DT)
        substep += 1
        v_now = np.asarray(m.vel, dtype=np.float64).copy()
        inst_g = 0.0
        inst_turn = 0.0
        # Skip the first few substeps: the spawn/eject velocity appears
        # instantaneously, which would read as a fake multi-hundred-g spike.
        if m.alive and substep > 5:
            # Proper (felt) acceleration and path rotation, sampled at the
            # full 120 Hz so between-frame spikes are not lost.
            proper = (v_now - prev_vel) / PHYS_DT - GRAV
            inst_g = float(np.linalg.norm(proper)) / G0
            peak_g = max(peak_g, inst_g)
            n0 = float(np.linalg.norm(prev_vel))
            n1 = float(np.linalg.norm(v_now))
            if n0 > 1.0 and n1 > 1.0:
                cosang = float(np.clip(
                    (prev_vel @ v_now) / (n0 * n1), -1.0, 1.0))
                inst_turn = math.degrees(math.acos(cosang)) / PHYS_DT
                peak_turn = max(peak_turn, inst_turn)
        prev_vel = v_now
        t = float(m.t)
        if m.alive:
            # The complete numeric record: one compact row per 120 Hz
            # substep, independent of the render/frame cadence.
            f_gamma, f_heading, _f_bp, f_aoa = _angles(m)
            f_alt = float(m.pos[1])
            f_speed = float(np.linalg.norm(v_now))
            cmd = getattr(m, "_fc_command", None)
            full_f.write(json.dumps({
                "t": round(t, 4),
                "alt": round(f_alt, 1),
                "mach": round(f_speed / speed_of_sound_scalar(f_alt), 3),
                "gamma_deg": round(f_gamma, 2),
                "heading_deg": round(f_heading, 2),
                "aoa_deg": round(f_aoa, 2),
                "g": round(inst_g, 2),
                "turn_dps": round(inst_turn, 1),
                "phase": m.phase_label,
                "cmd_gamma_deg": (round(math.degrees(
                    float(cmd.target_path_gamma_rad)), 2)
                    if cmd is not None else None),
                "target_mach": (round(float(cmd.target_mach), 2)
                                if cmd is not None else None),
                "alt_ref_m": (round(float(cmd.altitude_ref_asl_m), 1)
                              if cmd is not None else None),
            }, separators=(",", ":")) + "\n")
        if aftermath_until is None and not m.alive:
            aftermath_until = t + AFTERMATH_S
        if aftermath_until is not None and t >= aftermath_until:
            break
        if t >= max_s:
            break
        if t + 1e-9 < next_frame_t:
            continue
        next_frame_t += frame_dt
        _chase_cam(state, m, cam)
        state.render(0.0)
        surf = app.window.read_pixels_to_surface()
        cell = pygame.transform.smoothscale(surf, (FRAME_W, FRAME_H))
        pygame.image.save(
            cell, os.path.join(frames_dir, f"frame_{frame_i:04d}.png"))
        speed = float(np.linalg.norm(m.vel))
        gamma, heading, body_pitch, aoa = _angles(m)
        alt = float(m.pos[1])
        agl = alt - float(state.world.surface_height_at(
            float(m.pos[0]), float(m.pos[2])))
        tgt = getattr(m, "target", None)
        ref = getattr(tgt, "pos", None) if tgt is not None else aim
        dist_km = (float(np.linalg.norm(
            np.asarray(ref, dtype=np.float64) - m.pos)) / 1000.0
            if ref is not None else None)
        telemetry.append({
            "frame": frame_i, "t": round(t, 3),
            "pos": [round(float(x), 1) for x in m.pos],
            "vel": [round(float(x), 1) for x in m.vel],
            "speed_mps": round(speed, 1),
            "mach": round(speed / speed_of_sound_scalar(alt), 3),
            "phase": m.phase_label,
            "gamma_deg": round(gamma, 2),
            "heading_deg": round(heading, 1),
            "body_pitch_deg": round(body_pitch, 2),
            "aoa_deg": round(aoa, 2),
            "g_peak": round(peak_g, 2),
            "turn_rate_dps": round(peak_turn, 1),
            "alt_agl_m": round(agl, 1),
            "dist_to_go_km": (round(dist_km, 2)
                              if dist_km is not None else None),
            "fc": _fc_snapshot(m),
            "fuel_kg": round(float(getattr(m, "fuel",
                                           getattr(m, "propellant", 0.0))),
                             1),
            "alive": bool(m.alive),
        })
        peak_g = 0.0
        peak_turn = 0.0
        frame_i += 1

    full_f.close()
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
                    f"alt {rec['pos'][1]:.0f}m", True, (255, 220, 120))
                att = font.render(
                    f"fp{rec['gamma_deg']:+.0f} aoa{rec['aoa_deg']:.1f} "
                    f"{rec['g_peak']:.1f}g", True, (168, 216, 104))
                img.blit(label, (8, 6))
                img.blit(att, (8, 24))
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
    cam, out = "hero", None
    it = iter(argv)
    for a in it:
        if a == "--fps":
            fps = float(next(it))
        elif a == "--max-s":
            max_s = float(next(it))
        elif a == "--range-km":
            range_km = float(next(it))
        elif a == "--cam":
            cam = next(it)
        elif a == "--out":
            out = next(it)
        else:
            weapon = a
    if weapon not in ("oniks", "s300"):
        raise SystemExit("weapon must be oniks or s300")
    if cam not in ("side", "hero", "chase"):
        raise SystemExit("--cam must be side, hero or chase")
    app = App(hidden=True)
    out_dir = record(app, weapon, fps, max_s, range_km, cam, out)
    print(f"saved {out_dir}")
    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
