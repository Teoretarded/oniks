"""Visual audit for the walk-mode MANPADS rig: boot the real app hidden,
enter a baked cinematic scene, drive the F1 locker / designation / launch
through the actual event path and screenshot every player-facing moment
— locker UI, shouldered view models, ADS sight, IR lock HUD, corkscrew
flyout, kill fireball, Starstreak beam ride and ground impact.

Run: python tools/shoot_manpads.py [scene_name]
Outputs: renders/manpads_audit/*.png  (READ THEM — that is the audit)
"""

from __future__ import annotations

import math
import os
import sys
import time

import numpy as np
import pygame

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import App, PHYS_DT   # noqa: E402
from sim.manpads import WEAPON_BY_ID   # noqa: E402

OUT = os.path.join("renders", "manpads_audit")


def shot(app, name: str) -> None:
    os.makedirs(OUT, exist_ok=True)
    pygame.image.save(app.window.read_pixels_to_surface(),
                      os.path.join(OUT, f"{name}.png"))
    print(f"[shot] {name}.png", flush=True)


def frames(state, n: int, sim: bool = True) -> None:
    for _ in range(n):
        if sim:
            state.sim_step(PHYS_DT)
            state.sim_step(PHYS_DT)
        state.render(1 / 60.0)


def run_s(state, seconds: float) -> None:
    frames(state, max(int(seconds / PHYS_DT / 2), 1))


def key(state, k) -> None:
    state.handle_event(pygame.event.Event(pygame.KEYDOWN, key=k, unicode="",
                                          mod=0, scancode=0))


def click(state, button: int, pos=(0, 0)) -> None:
    state.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                          button=button, pos=pos))


def unclick(state, button: int, pos=(0, 0)) -> None:
    state.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP,
                                          button=button, pos=pos))


def aim_at(state, pos) -> None:
    eye = np.array(state.walker.eye, dtype=np.float64)
    rel = np.asarray(pos, dtype=np.float64) - eye
    state.walker.yaw = math.atan2(rel[0], rel[2])
    state.walker.pitch = math.atan2(rel[1], math.hypot(rel[0], rel[2]))


def equip(state, wid: str) -> None:
    """Through the real locker: open, draw once to lay out rows, click."""
    rig = state.weapons
    if not rig.locker_open:
        key(state, pygame.K_F1)
    frames(state, 2, sim=False)
    row = next(r for k, w, r in rig._ui_rects
               if k == "weapon" and w == wid)
    click(state, 1, ((row[0] + row[2]) // 2, (row[1] + row[3]) // 2))
    frames(state, 2, sim=False)
    assert rig.weapon is not None and rig.weapon.id == wid, \
        f"locker click failed for {wid}"


def wait_l0(state, timeout_s: float = 45.0) -> None:
    from world.cinematic_terrain import L0_DIST
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout_s:
        frames(state, 5, sim=False)
        eye = np.array(state.walker.eye, dtype=np.float64)
        near = [t for t in state.terrain.tiles if t.dist(eye) < L0_DIST]
        if near and all(t.mesh_l0 is not None for t in near):
            return


def main() -> None:
    scene = sys.argv[1] if len(sys.argv) > 1 else "lauterbrunnen"
    app = App(hidden=True)
    app.open_testing_lab()
    app.open_cinematic(os.path.join("assets", "cinematic", scene))
    state = app.state
    rig = state.weapons
    frames(state, 10)
    print("streaming L0 ...", flush=True)
    wait_l0(state)
    run_s(state, 6.5)                       # title card fades

    # ---- 1. the locker UI
    key(state, pygame.K_F1)
    frames(state, 2, sim=False)
    shot(app, "01_locker_ui")

    # ---- 2. shoulder views, hip + ADS, all four
    for i, wid in enumerate(("igla_s", "stinger", "piorun", "starstreak")):
        equip(state, wid)
        state.walker.pitch = math.radians(4.0)
        run_s(state, 0.3)
        shot(app, f"1{i}_shoulder_{wid}")
        click(state, 3)                     # RMB: sight up
        run_s(state, 0.5)
        shot(app, f"1{i}_ads_{wid}")
        unclick(state, 3)
        run_s(state, 0.2)

    # ---- 3. Igla vs a live S-300 round: tone, lock, fire, kill.
    # Shoot INSIDE the honest window — early boost, before the target
    # outruns the Igla (a 16 g climb-out is uncatchable from behind
    # once it passes the Igla's own speed).
    equip(state, "igla_s")
    state._fire()                           # the target leaves the tube
    run_s(state, 0.2)                       # still hanging in cold eject
    tgt = state.launch
    aim_at(state, tgt.pos)
    click(state, 2)                         # MMB designate
    frames(state, 2, sim=False)
    shot(app, "20_igla_tone")
    for _ in range(40):                     # hold aim through TONE->LOCK
        if rig.seek_state == "lock":
            break
        aim_at(state, tgt.pos)
        frames(state, 3)
    aim_at(state, tgt.pos)
    frames(state, 2, sim=False)
    shot(app, "21_igla_lock")
    click(state, 1)                         # LMB fire
    run_s(state, 0.25)
    shot(app, "22_igla_backblast")
    run_s(state, 1.1)
    if rig.flyouts:
        aim_at(state, rig.flyouts[0].rnd.pos)
    frames(state, 2, sim=False)
    shot(app, "23_igla_corkscrew_climb")
    killed = False
    for _ in range(int(14.0 / PHYS_DT / 6)):
        if not rig.flyouts:
            killed = tgt.done
            break
        aim_at(state, rig.flyouts[0].rnd.pos)
        frames(state, 3)
    aim_at(state, tgt.pos)
    frames(state, 2, sim=False)
    shot(app, "24_igla_intercept")
    print(f"igla kill: {killed}", flush=True)
    run_s(state, 1.5)
    shot(app, "25_after_intercept_smoke")

    # ---- 4. Starstreak onto a distant valley ground point (ride the aim)
    equip(state, "starstreak")
    state.walker.yaw += math.radians(25.0)
    for pitch in (-0.2, -0.5, -1.0, -1.8, -3.0):
        state.walker.pitch = math.radians(pitch)
        click(state, 2)                      # beam mark attempt
        if rig.ground_mark is not None:
            rng = float(np.linalg.norm(
                rig.ground_mark - np.array(state.walker.eye)))
            if rng >= 800.0:
                break
    frames(state, 2, sim=False)
    shot(app, "30_beam_mark")
    click(state, 1)
    run_s(state, 0.8)
    shot(app, "31_starstreak_away")
    for _ in range(int(8.0 / PHYS_DT / 6)):
        if not rig.flyouts:
            break
        frames(state, 3)
    frames(state, 2, sim=False)
    shot(app, "32_ground_impact")
    run_s(state, 1.2)
    shot(app, "33_impact_dust")

    print("done.", flush=True)
    app.shutdown() if hasattr(app, "shutdown") else None


if __name__ == "__main__":
    main()
