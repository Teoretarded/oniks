"""Plot a chase recording's telemetry as stacked time-series panels (PNG).

usage: python -m tools.plot_chase_telemetry [name]     (default: oniks)
       where <name> is a folder under renders/chase/ made by
       tools.record_missile_chase.

Reads telemetry_full.jsonl (every 120 Hz substep) when present, falling
back to the per-frame telemetry.json. Writes <dir>/telemetry_plot.png:

    flight-path angle vs the FC's commanded angle   (guidance tracking)
    AoA                                             (body vs path)
    Mach vs FC target Mach                          (energy management)
    altitude vs FC altitude reference               (corridor tracking)
    proper acceleration (g)                         (loads)
    path turn rate (deg/s)                          (spin-outs live here)
    heading, unwrapped                              (a 180 = a 180 step)

and prints an anomaly summary (worst guidance gap, peak AoA/g/turn rate,
biggest 1-second heading swing, each with its timestamp) so a reviewing AI
can jump straight from the number to the matching video frame
(frame = t * fps, default fps 6).

Pure pygame surface drawing — no GL, no display, no new dependencies.
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np
import pygame

CHASE_ROOT = os.path.join("renders", "chase")
W = 1400
PANEL_H = 128
PAD_L, PAD_R, PAD_TOP, PAD_BOT = 74, 16, 34, 30
GAP = 10

BG = (13, 17, 20)
PANEL_BG = (20, 26, 31)
GRID = (35, 44, 51)
INK = (215, 222, 226)
DIM = (138, 150, 158)
HUD = (168, 216, 104)      # actual series
CMD = (224, 180, 92)       # FC-commanded series
MARK = (201, 111, 94)      # anomaly marker
PHASE = (90, 120, 140)


def _load(out_dir: str):
    """-> dict of np arrays (None-> nan) with unified keys + phase list."""
    full = os.path.join(out_dir, "telemetry_full.jsonl")
    rows = []
    if os.path.exists(full):
        with open(full, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        src = "telemetry_full.jsonl (120 Hz)"
    else:
        with open(os.path.join(out_dir, "telemetry.json"),
                  encoding="utf-8") as f:
            for r in json.load(f):
                fc = r.get("fc") or {}
                rows.append({
                    "t": r["t"], "alt": r["pos"][1], "mach": r["mach"],
                    "gamma_deg": r["gamma_deg"],
                    "heading_deg": r["heading_deg"],
                    "aoa_deg": r["aoa_deg"], "g": r["g_peak"],
                    "turn_dps": r["turn_rate_dps"], "phase": r["phase"],
                    "cmd_gamma_deg": fc.get("cmd_gamma_deg"),
                    "target_mach": fc.get("target_mach"),
                    "alt_ref_m": fc.get("alt_ref_m"),
                })
        src = "telemetry.json (per-frame fallback)"
    keys = ("t", "alt", "mach", "gamma_deg", "heading_deg", "aoa_deg",
            "g", "turn_dps", "cmd_gamma_deg", "target_mach", "alt_ref_m")
    data = {k: np.array([np.nan if r.get(k) is None else float(r[k])
                         for r in rows]) for k in keys}
    data["phase"] = [r["phase"] for r in rows]
    return data, src


def _heading_unwrapped(deg: np.ndarray) -> np.ndarray:
    return np.degrees(np.unwrap(np.radians(deg)))


def _fmt(v: float) -> str:
    a = abs(v)
    if a >= 1000.0:
        return f"{v:,.0f}"
    if a >= 10.0:
        return f"{v:.0f}"
    return f"{v:.2f}"


def _draw_panel(surf, font, small, y0, title, t, series, phase_marks,
                mark_peak=False):
    """series: list of (values, color, label). Returns anomaly (t, v) of
    the |max| point of the first series when mark_peak."""
    x0, x1 = PAD_L, W - PAD_R
    y1 = y0 + PANEL_H
    pygame.draw.rect(surf, PANEL_BG, (x0, y0, x1 - x0, PANEL_H))
    vals = np.concatenate([v[np.isfinite(v)] for v, _, _ in series
                           if np.isfinite(v).any()])
    lo, hi = (float(vals.min()), float(vals.max())) if vals.size else (0, 1)
    if hi - lo < 1e-6:
        lo, hi = lo - 1.0, hi + 1.0
    lo, hi = lo - 0.06 * (hi - lo), hi + 0.06 * (hi - lo)
    t0, t1 = float(t[0]), float(t[-1])

    def sx(tv):
        return x0 + (tv - t0) / max(t1 - t0, 1e-9) * (x1 - x0)

    def sy(v):
        return y1 - (v - lo) / (hi - lo) * PANEL_H

    if lo < 0.0 < hi:                       # zero line
        pygame.draw.line(surf, GRID, (x0, sy(0)), (x1, sy(0)))
    for tv, _label in phase_marks:          # phase boundaries
        px = sx(tv)
        pygame.draw.line(surf, PHASE, (px, y0), (px, y1))
    for v, color, _label in series:
        pts, run = [], []
        for i in range(len(t)):
            if np.isfinite(v[i]):
                run.append((sx(t[i]), sy(v[i])))
            elif len(run) > 1:
                pts.append(run)
                run = []
            else:
                run = []
        if len(run) > 1:
            pts.append(run)
        for seg in pts:
            pygame.draw.aalines(surf, color, False, seg)
    peak = None
    if mark_peak:
        v = series[0][0]
        fin = np.isfinite(v)
        if fin.any():
            i = int(np.nanargmax(np.abs(np.where(fin, v, 0.0))))
            peak = (float(t[i]), float(v[i]))
            pygame.draw.circle(surf, MARK, (int(sx(t[i])), int(sy(v[i]))), 4, 1)
    surf.blit(font.render(title, True, INK), (x0, y0 - 20))
    lx = x0 + font.size(title)[0] + 18
    for _v, color, label in series:
        s = small.render(label, True, color)
        surf.blit(s, (lx, y0 - 18))
        lx += s.get_width() + 14
    surf.blit(small.render(_fmt(hi), True, DIM), (8, y0 - 2))
    surf.blit(small.render(_fmt(lo), True, DIM), (8, y1 - 14))
    return peak


def plot(out_dir: str) -> str:
    data, src = _load(out_dir)
    t = data["t"]
    heading_u = _heading_unwrapped(data["heading_deg"])
    gap = data["gamma_deg"] - data["cmd_gamma_deg"]      # nan where no FC

    phases = data["phase"]
    phase_marks = [(float(t[i]), phases[i]) for i in range(1, len(phases))
                   if phases[i] != phases[i - 1]]

    panels = [
        ("flight-path angle (deg)",
         [(data["gamma_deg"], HUD, "actual"),
          (data["cmd_gamma_deg"], CMD, "FC command")], False),
        ("AoA (deg)", [(data["aoa_deg"], HUD, "aoa")], True),
        ("Mach", [(data["mach"], HUD, "actual"),
                  (data["target_mach"], CMD, "FC target")], False),
        ("altitude (m)", [(data["alt"], HUD, "actual"),
                          (data["alt_ref_m"], CMD, "FC reference")], False),
        ("proper acceleration (g)", [(data["g"], HUD, "g")], True),
        ("path turn rate (deg/s)", [(data["turn_dps"], HUD, "turn")], True),
        ("heading, unwrapped (deg)", [(heading_u, HUD, "heading")], False),
    ]

    H = PAD_TOP + len(panels) * (PANEL_H + GAP + 22) + PAD_BOT
    pygame.font.init()
    font = pygame.font.SysFont("consolas", 15)
    small = pygame.font.SysFont("consolas", 12)
    surf = pygame.Surface((W, H))
    surf.fill(BG)
    title = f"{os.path.basename(out_dir)} — {len(t)} rows from {src}"
    surf.blit(font.render(title, True, INK), (PAD_L, 8))

    peaks = {}
    y = PAD_TOP + 22
    for name, series, mark in panels:
        marks = phase_marks if name.startswith("flight-path") else \
            [(tv, "") for tv, _ in phase_marks]
        peaks[name] = _draw_panel(surf, font, small, y, name, t, series,
                                  marks, mark)
        y += PANEL_H + GAP + 22
    # Phase labels along the top panel.
    for tv, label in phase_marks:
        x = PAD_L + (tv - t[0]) / max(t[-1] - t[0], 1e-9) * (W - PAD_L - PAD_R)
        surf.blit(small.render(label, True, PHASE), (int(x) + 3, PAD_TOP + 24))
    # Time ticks on the last panel's baseline.
    step = 10.0 if t[-1] - t[0] > 30 else 5.0
    tick = np.arange(np.ceil(t[0] / step) * step, t[-1], step)
    for tv in tick:
        x = PAD_L + (tv - t[0]) / max(t[-1] - t[0], 1e-9) * (W - PAD_L - PAD_R)
        surf.blit(small.render(f"{tv:.0f}s", True, DIM), (int(x) - 8, H - 20))

    out_png = os.path.join(out_dir, "telemetry_plot.png")
    pygame.image.save(surf, out_png)

    # ---- anomaly summary ----------------------------------------------
    def _peak_line(name, arr, unit=""):
        fin = np.isfinite(arr)
        if not fin.any():
            return f"  {name:<26} n/a"
        i = int(np.nanargmax(np.abs(np.where(fin, arr, 0.0))))
        return f"  {name:<26} {arr[i]:+8.2f}{unit}  at t={t[i]:.2f}s"

    # Biggest heading swing inside any sliding 1 s window.
    swing_line = "  180-detector (1s swing)    n/a"
    if len(t) > 2:
        dtm = float(np.median(np.diff(t)))
        w = max(2, int(round(1.0 / max(dtm, 1e-6))))
        if len(heading_u) > w:
            sw = np.abs(heading_u[w:] - heading_u[:-w])
            i = int(np.argmax(sw))
            swing_line = (f"  {'180-detector (1s swing)':<26} "
                          f"{sw[i]:+8.2f}deg at t={t[i]:.2f}s")
    print(f"rows: {len(t)}  span: {t[0]:.2f}-{t[-1]:.2f}s  source: {src}")
    print("anomaly summary (|peak| with timestamp):")
    print(_peak_line("guidance gap (act-cmd)", gap, "deg"))
    print(_peak_line("AoA", data["aoa_deg"], "deg"))
    print(_peak_line("proper accel", data["g"], "g"))
    print(_peak_line("turn rate", data["turn_dps"], "dps"))
    print(swing_line)
    print(f"saved {os.path.abspath(out_png)}")
    return out_png


def main(argv: list[str]) -> int:
    name = argv[0] if argv else "oniks"
    out_dir = name if os.path.isdir(name) else os.path.join(CHASE_ROOT, name)
    if not os.path.isdir(out_dir):
        raise SystemExit(f"no chase recording at {out_dir}")
    plot(out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
