"""Render the 48N6 vs 40N6 flyoff trajectories (altitude vs downrange) to SVG."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

with open("tools/flyoff_traj.json", encoding="utf-8") as f:
    DATA = json.load(f)

W, H = 860, 470
ML, MR, MT, MB = 70, 220, 40, 52
PW, PH = W - ML - MR, H - MT - MB
XMAX, YMAX = 380_000.0, 52_000.0

COLORS = {"close 60km @ 15km": "#7aa2f7",
          "in-envelope 120km @ 18km": "#5fd3bc",
          "medium 200km @ 20km": "#e0b341",
          "long 300km @ 24km": "#e0653f",
          "v-long 360km @ 26km": "#bb6fce"}


def sx(x):
    return ML + (x / XMAX) * PW


def sy(y):
    return MT + PH - (y / YMAX) * PH


def main():
    out = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" '
           f'font-family="Consolas,monospace">',
           f'<rect x="0" y="0" width="{W}" height="{H}" fill="#0d1117"/>',
           f'<text x="{ML}" y="22" fill="#e6edf3" font-size="15">'
           f'S-300 48N6 (solid) vs 40N6 (dashed) - altitude vs downrange</text>']
    for kmx in range(0, 381, 40):
        x = sx(kmx * 1000)
        out.append(f'<line x1="{x:.1f}" y1="{MT}" x2="{x:.1f}" y2="{MT+PH}" '
                   f'stroke="#ffffff12"/>')
        out.append(f'<text x="{x:.1f}" y="{MT+PH+18}" fill="#8b949e" '
                   f'font-size="11" text-anchor="middle">{kmx}</text>')
    out.append(f'<text x="{ML+PW/2:.0f}" y="{H-8}" fill="#8b949e" '
               f'font-size="12" text-anchor="middle">downrange (km)</text>')
    for kmy in range(0, 53, 10):
        y = sy(kmy * 1000)
        out.append(f'<line x1="{ML}" y1="{y:.1f}" x2="{ML+PW}" y2="{y:.1f}" '
                   f'stroke="#ffffff12"/>')
        out.append(f'<text x="{ML-8}" y="{y+4:.1f}" fill="#8b949e" '
                   f'font-size="11" text-anchor="end">{kmy}</text>')
    out.append(f'<text x="18" y="{MT+PH/2:.0f}" fill="#8b949e" font-size="12" '
               f'text-anchor="middle" transform="rotate(-90 18 {MT+PH/2:.0f})">'
               f'altitude (km)</text>')

    ly = MT + 8
    for key, traj in DATA.items():
        geom, rnd = [s.strip() for s in key.split("|")]
        col = COLORS.get(geom, "#ffffff")
        dash = ' stroke-dasharray="7 4"' if rnd == "40N6" else ""
        pts = " ".join(f"{sx(p[0]):.1f},{sy(p[1]):.1f}"
                       for p in traj if p[0] >= 0 and p[1] >= 0)
        out.append(f'<polyline points="{pts}" fill="none" stroke="{col}" '
                   f'stroke-width="2.1"{dash} opacity="0.95"/>')
        out.append(f'<line x1="{W-MR+10}" y1="{ly}" x2="{W-MR+40}" y2="{ly}" '
                   f'stroke="{col}" stroke-width="2.1"{dash}/>')
        out.append(f'<text x="{W-MR+46}" y="{ly+4}" fill="#c9d1d9" '
                   f'font-size="11">{rnd} {geom.split(" ")[0]}</text>')
        ly += 22
    out.append(f'<text x="{W-MR+10}" y="{ly+14}" fill="#e0653f" font-size="10.5">'
               f'48N6 self-destructs</text>')
    out.append(f'<text x="{W-MR+10}" y="{ly+28}" fill="#e0653f" font-size="10.5">'
               f'at 180 s -&gt; short</text>')
    out.append('</svg>')
    svg = "\n".join(out)
    with open("tools/s300_flyoff.svg", "w", encoding="utf-8") as fh:
        fh.write(svg)
    print("[plot] wrote tools/s300_flyoff.svg")


if __name__ == "__main__":
    main()
