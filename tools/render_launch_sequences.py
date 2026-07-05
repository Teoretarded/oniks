"""Launch-sequence frame STRIPS — the watchable launch record.

usage: python -m tools.render_launch_sequences [oniks s300 ...]

For each weapon this fires the REAL in-game launch pipeline (sandbox
request_launch — muzzle blast, cover debris, plumes and all), steps the
120 Hz sim to a set of frame-timed snapshot moments (chosen from the
normative docs: oniks_launch_sequence.md beats, s300_reference.md
eject/hang/ignition), renders each moment with a chase camera, and
composites the frames into one horizontal contact strip:

    renders/launch/<id>_strip.png    (frames labeled t=+X.Xs)

Together with tools/probe_launch_kinematics.py (per-tick CSV + JSON) this
is the plan's launch-review pair: the probe gives any AI the numbers, the
strip gives humans (and vision models) the LOOK. Needs a GPU/GL context.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pygame

from main import PHYS_DT, App
from tools.screenshot_harness import _aim, _render_frame

OUT_DIR = os.path.join("renders", "launch")
FRAME_W, FRAME_H = 400, 225          # per-frame cell in the strip
WARMUP_FRAMES = 240                  # terrain LOD stream-in before frame 0

# Frame-timed snapshot moments per weapon (from the normative docs).
SNAPS = {
    # in-tube ignition / ride-out / pitch-over / cap-off / boost / streak
    "oniks": (0.4, 1.3, 2.2, 3.0, 4.1, 5.6, 8.0, 12.0),
    # cover blow / catapult rise / the hang / ignition / tip-over / boost
    "s300": (0.4, 1.0, 1.4, 1.7, 2.2, 3.2, 5.0, 8.0),
}


def _fly_until(state, m, t_snap: float) -> None:
    while m.t < t_snap and getattr(m, "alive", False):
        state.sim_step(PHYS_DT)


def _launch(state, weapon):
    """Fire through the real platform pipeline (screenshot-harness recipes)."""
    if weapon == "oniks":
        state.target_point = np.array([0.0, 0.0, 120_000.0])
        m = state.request_launch()
    else:                                        # s300 vs the air patrol
        for _ in range(int(2.0 / PHYS_DT)):      # air tracks form
            state.sim_step(PHYS_DT)
        state.cycle_platform()                   # bastion -> s300
        state.tactical_map.selected_contact = "air_patrol_00"
        m = state.request_launch()
    assert m is not None, f"{weapon} launch refused"
    return m


def _chase_cam(state, weapon, m) -> None:
    """Frame the missile with its launcher/column: side-on, pulled back as
    the round climbs so both the airframe and the smoke column read."""
    origin = (np.array(state._tel_pos, dtype=np.float64) if weapon == "oniks"
              else np.asarray(state._sam_tel_pos, dtype=np.float64))
    alt = float(m.pos[1]) - float(origin[1])
    # Dolly out with the climb but CAP it, and once the round is properly
    # airborne frame the MISSILE (with trail behind), not the empty middle
    # (milestone critique 2026-07-06: the last strip frames lost the round
    # to a runaway dolly).
    back = min(40.0 + alt * 0.9, 300.0)
    frac = 0.62 if alt < 600.0 else 0.9
    look = origin + (m.pos - origin) * frac
    _aim(state, look + np.array([back, max(6.0, min(alt * 0.18, 60.0)),
                                 -back * 0.75]), look)


def render_strip(app: App, weapon: str) -> str:
    from game.sandbox import SandboxState
    app.states.switch(SandboxState(app))     # fresh armed launcher, empty sky
    state = app.state
    state.hud_visible = False
    m = _launch(state, weapon)
    # Terrain LOD warm-up before the first snap (position the cam first).
    _chase_cam(state, weapon, m)
    for _ in range(WARMUP_FRAMES):
        _render_frame(app, "launch_strip")
        terrain = getattr(state, "terrain", None)
        if terrain is None or not terrain._jobs:
            break
    font = pygame.font.SysFont("consolas", 16)
    strip = pygame.Surface((FRAME_W * len(SNAPS[weapon]), FRAME_H))
    for i, t_snap in enumerate(SNAPS[weapon]):
        _fly_until(state, m, t_snap)
        _chase_cam(state, weapon, m)
        _render_frame(app, "launch_strip")
        surf = app.window.read_pixels_to_surface()
        cell = pygame.transform.smoothscale(surf, (FRAME_W, FRAME_H))
        label = font.render(
            f"t=+{t_snap:.1f}s  {m.phase_label}", True, (255, 220, 120))
        cell.blit(label, (8, 6))
        strip.blit(cell, (FRAME_W * i, 0))
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{weapon}_strip.png")
    pygame.image.save(strip, path)
    return os.path.abspath(path)


def main(argv) -> int:
    names = argv or list(SNAPS)
    unknown = [n for n in names if n not in SNAPS]
    if unknown:
        raise SystemExit(f"unknown weapon(s) {unknown}; choose from "
                         f"{list(SNAPS)}")
    app = App(hidden=True)
    for name in names:
        print(f"saved {render_strip(app, name)}")
    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
