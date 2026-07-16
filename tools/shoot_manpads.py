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


def stand_on_crest(state, rings=(1000, 1100, 1200, 1300, 900)) -> None:
    """Real gunner behaviour: find walkable ground on a ring around the
    pad with a genuinely clear sight line to the canister top (checked
    with the rig's own occlusion march, eye height AND launch height).
    Pass close rings for the eject-window Starstreak shot."""
    w = state.walker
    rig = state.weapons
    pad = state._pad
    tube_top = pad + np.array([0.0, 12.0, 0.0])
    d = np.array([pad[0] - w.x, pad[2] - w.z])
    dist = float(np.linalg.norm(d))
    d /= dist
    perp = np.array([-d[1], d[0]])
    # Keep >= 900 m standoff (a shorter Starstreak shot arrives still in
    # boost, before the fins can pull the gathering arc back down), and
    # sweep sideways onto the valley-side rises for a sight line over
    # the moraine mounds.
    _ = dist, perp
    sc = state.scene
    cands = []
    for r_ring in rings:
        for a_deg in range(0, 360, 12):
            a = math.radians(a_deg)
            x = float(pad[0]) + math.sin(a) * r_ring
            z = float(pad[2]) + math.cos(a) * r_ring
            if not (sc.x0 + 40 <= x <= sc.x1 - 40
                    and sc.z0 + 40 <= z <= sc.z1 - 40):
                continue
            cands.append((math.hypot(x - w.x, z - w.z), x, z, r_ring))
    cands.sort()                        # nearest to the spawn first
    for _dspawn, x, z, r_ring in cands:
        g0 = float(sc.ground_h(x, z))
        # walkable ground only — no perching on the valley wall (from a
        # cliff face the muzzle fires into rock)
        if not all(abs(float(sc.ground_h(x + dx, z + dz)) - g0) < 1.3
                   for dx, dz in ((4, 0), (-4, 0), (0, 4), (0, -4))):
            continue
        eye = np.array([x, g0 + 1.7, z])
        low = np.array([x, g0 + 0.9, z])
        # the eye must see the tube top AND the lower line must clear too
        # (the round leaves at ~1.5 m and sags before the fins bite)
        if rig._los_clear(state, eye, tube_top) \
                and rig._los_clear(state, low, tube_top):
            w.x, w.z = float(x), float(z)
            w.y = g0
            w.vx = w.vy = w.vz = 0.0
            w.on_ground = True
            print(f"[audit] firing position: ring {r_ring} m, "
                  f"{_dspawn:0.0f} m from spawn, LOS clear", flush=True)
            return
    print("[audit] WARNING: no LOS-clear spot found; staying at spawn",
          flush=True)


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
    stand_on_crest(state)                   # clear line to the pad first
    run_s(state, 0.5)
    equip(state, "igla_s")
    state._fire()                           # the target leaves the tube
    run_s(state, 0.7)
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

    # ---- 3b. Starstreak vs a fresh launch: the ONLY winnable shot is
    # the cold-eject window — pre-aimed from close standoff, fired the
    # instant the round leaves the tube, killed before its motor takes
    # it away. By ~0.6 s the window is shut (physics, not a timer).
    stand_on_crest(state, rings=(400, 450, 500, 550))
    run_s(state, 0.4)
    equip(state, "starstreak")
    pad_top = state._pad + np.array([0.0, state._tube_top + 3.0, 0.0])
    aim_at(state, pad_top)                   # pre-aimed at the tube
    run_s(state, 0.2)
    state._fire()
    run_s(state, 0.1)
    tgt2 = state.launches[-1]
    aim_at(state, tgt2.pos)
    click(state, 2)                          # beam onto the round
    assert rig.seek_state == "lock", "beam designation failed"
    click(state, 1)                          # fire immediately
    run_s(state, 0.5)
    aim_at(state, tgt2.pos)
    frames(state, 2, sim=False)
    shot(app, "26_starstreak_ride")
    kill2 = False
    last_fo = None
    for _ in range(int(10.0 / PHYS_DT / 2)):
        if not rig.flyouts:
            kill2 = tgt2.done
            break
        last_fo = rig.flyouts[0]
        aim_at(state, tgt2.pos)              # the operator rides the beam
        frames(state, 1)                     # steer EVERY frame
    frames(state, 2, sim=False)
    shot(app, "27_starstreak_kill")
    miss = None if last_fo is None else last_fo.rnd.miss_dist
    print(f"starstreak kill: {kill2} (closest "
          f"{'?' if miss is None else round(miss, 2)} m)", flush=True)
    run_s(state, 1.2)
    aim_at(state, tgt2.pos)
    frames(state, 2, sim=False)
    shot(app, "28_kill_debris_smoke")

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
