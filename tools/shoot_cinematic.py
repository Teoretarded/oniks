"""Visual audit for cinematic mode: boot the real app (hidden GL window),
enter a baked scene, stream terrain in, run the scripted S-300 launch and
save screenshots at the moments that matter.  Run after any change to the
bake, terrain renderer, walker or state.

Run: python tools/shoot_cinematic.py [scene_name]
Outputs: renders/cinematic_audit/*.png
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

OUT = os.path.join("renders", "cinematic_audit")


def shot(app, name: str) -> None:
    os.makedirs(OUT, exist_ok=True)
    pygame.image.save(app.window.read_pixels_to_surface(),
                      os.path.join(OUT, f"{name}.png"))
    print(f"[shot] {name}.png", flush=True)


def frames(state, n: int, sim: bool = True) -> None:
    for _ in range(n):
        if sim:
            state.sim_step(PHYS_DT)
            state.sim_step(PHYS_DT)      # 2 sim steps per drawn frame (~60fps)
        state.render(1 / 60.0)


def wait_for_l0(state, timeout_s: float = 45.0) -> bool:
    """Render until every tile within L0 range of the eye has its 4K mesh."""
    from world.cinematic_terrain import L0_DIST
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout_s:
        frames(state, 5, sim=False)
        eye = np.array(state.walker.eye, dtype=np.float64)
        near = [t for t in state.terrain.tiles if t.dist(eye) < L0_DIST]
        if near and all(t.mesh_l0 is not None for t in near):
            return True
    return False


def aim(state, yaw_deg: float, pitch_deg: float = 0.0) -> None:
    state.walker.yaw = math.radians(yaw_deg)
    state.walker.pitch = math.radians(pitch_deg)


def set_mood(state, mood_id: str) -> None:
    from game.cinematic import MOODS
    state.mood_i = next(i for i, m in enumerate(MOODS) if m.id == mood_id)
    state._apply_mood()


def wait_for_shadow(state, mood_id: str, timeout_s: float = 40.0) -> bool:
    """Render until the mood's baked shadow mask is uploaded + applied."""
    t0 = time.perf_counter()
    while (mood_id not in state._shadow_texs
           and time.perf_counter() - t0 < timeout_s):
        frames(state, 3, sim=False)
    ok = mood_id in state._shadow_texs
    state._apply_shadow(mood_id)
    return ok


def sim_only(state, seconds: float) -> None:
    for _ in range(int(seconds / PHYS_DT)):
        state.sim_step(PHYS_DT)


def main() -> None:
    scene = sys.argv[1] if len(sys.argv) > 1 else "lauterbrunnen"
    app = App(hidden=True)

    # --- the lab tab UI first (it needs no scene assets) ---
    app.open_testing_lab()
    lab = app.state
    lab.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F7,
                                        unicode="", mod=0, scancode=0))
    lab.render(1 / 60.0)
    lab.render(1 / 60.0)
    shot(app, "00_lab_cinematic_tab")

    # --- into the scene ---
    app.open_cinematic(os.path.join("assets", "cinematic", scene))
    state = app.state                    # launches are manual-only now
    frames(state, 10)
    print("streaming L0 ...", flush=True)
    ok = wait_for_l0(state)
    print(f"L0 ready: {ok}", flush=True)

    # Spawn view toward the pad (the bake aims spawn yaw at the S-300).
    frames(state, 10)
    shot(app, "01_spawn_toward_pad")

    # Look at the west valley wall, then down the valley axis.
    aim(state, 270.0, 18.0)
    frames(state, 5)
    shot(app, "02_west_cliffs")
    aim(state, 180.0, 6.0)
    frames(state, 5)
    shot(app, "03_down_valley")

    # Launch: cold eject, ignition, boost, high in the sky.  Timings track
    # the variant's researched script (ignition ~0.9 s after tube exit).
    pad = state._pad
    eye = np.array(state.walker.eye, dtype=np.float64)
    to_pad = pad - eye
    yaw = math.degrees(math.atan2(to_pad[0], to_pad[2]))
    aim(state, yaw, 2.0)
    state._fire()
    ignite = state.launch.variant.ignite_delay
    frames(state, int(ignite * 0.7 / PHYS_DT / 2))       # mid cold eject
    shot(app, "04_cold_eject")
    aim(state, yaw, 4.0)
    frames(state, int((ignite * 0.3 + 0.35) / PHYS_DT / 2))
    shot(app, "05_ignition")
    aim(state, yaw, 14.0)
    frames(state, int(2.0 / PHYS_DT / 2))
    shot(app, "06_boost_climb")
    aim(state, yaw, 45.0)
    frames(state, int(3.5 / PHYS_DT / 2))
    shot(app, "07_high_in_sky")

    # Binoculars on the trail.
    state.zoom_i = 2
    state._zoom_fade = 1.0
    aim(state, yaw, 30.0)
    frames(state, 5)
    shot(app, "09_binoculars")

    # Spotter: line + diamond unzoomed, then auto-track at high zoom.
    state.zoom_i = 0
    state._zoom_fade = 0.0
    state.spot = True
    aim(state, yaw - 25.0, 10.0)             # deliberately off-target
    frames(state, 3)
    shot(app, "15_spotter_line")
    state.zoom_i = 4                         # 20x: the tracker takes over
    state._zoom_fade = 1.0
    frames(state, int(1.5 / PHYS_DT / 2))
    shot(app, "16_spotter_tracking")
    state.spot = False
    state.zoom_i = 0
    state._zoom_fade = 0.0

    # The column hanging there half a minute later, drifting on the wind.
    for _ in range(int(20.0 / PHYS_DT)):
        state.sim_step(PHYS_DT)
    aim(state, yaw, 10.0)
    frames(state, 5)
    shot(app, "10_column_after_20s")

    # Light rigs with PRE-BAKED terrain shadows: golden hour must lay the
    # ridge shadows across the valley (user report: no mountain shadows).
    set_mood(state, "golden")
    print("shadow bake (golden):", wait_for_shadow(state, "golden"),
          flush=True)
    frames(state, 5)
    shot(app, "11_golden_hour_shadows")
    aim(state, 300.0, 10.0)
    frames(state, 5)
    shot(app, "11b_golden_westward")
    set_mood(state, "grey")
    wait_for_shadow(state, "grey")
    frames(state, 5)
    shot(app, "17_grey_morning")
    set_mood(state, "night")
    wait_for_shadow(state, "night")
    aim(state, yaw, 8.0)
    frames(state, 5)
    shot(app, "18_night")

    # Rolling fog: give a grey morning 90 simulated seconds to build,
    # then look across the valley and up at the icy heights.
    set_mood(state, "grey")
    sim_only(state, 90.0)
    aim(state, 270.0, 14.0)
    frames(state, 5)
    shot(app, "19_fog_on_the_heights")
    aim(state, 180.0, 2.0)
    frames(state, 5)
    shot(app, "20_fog_down_valley")

    # The pad cloud must LINGER: a fresh round, then the drifting ground
    # cloud at +12 s and +35 s (it used to vanish in seconds).  Stand
    # 250 m from the pad — from the spawn a moraine hides the cloud's
    # lower half and the shot proves nothing.
    set_mood(state, "noon")
    wait_for_shadow(state, "noon")
    wk = state.walker
    pad = state._pad
    wk.x, wk.z = float(pad[0]) - 180.0, float(pad[2]) + 175.0
    wk.y = state.scene.ground_h(wk.x, wk.z)
    wk.vx = wk.vy = wk.vz = 0.0
    wk.on_ground = True
    eye = np.array(wk.eye, dtype=np.float64)
    yaw_pad = math.degrees(math.atan2(pad[0] - eye[0], pad[2] - eye[2]))
    state._fire()
    sim_only(state, 12.0)
    aim(state, yaw_pad, 4.0)
    frames(state, 5)
    shot(app, "21_pad_cloud_12s")
    sim_only(state, 23.0)
    frames(state, 5)
    shot(app, "22_pad_cloud_35s")

    # Surround ground: stand 5+ km OUTSIDE the LiDAR core (this used to
    # be 'NO GROUND THERE') and look back into the scene.
    wk = state.walker
    wk.x, wk.z = 5200.0, 1500.0
    wk.y = state.scene.ground_h(wk.x, wk.z)
    wk.vx = wk.vy = wk.vz = 0.0
    wk.on_ground = True
    aim(state, 250.0, 0.0)
    frames(state, 10)
    shot(app, "23_standing_on_surround")
    set_mood(state, "alpine")
    frames(state, 5)
    shot(app, "24_alpine_from_surround")

    # Director overlay + freecam marker.
    state.ui_open = True
    frames(state, 3)
    shot(app, "12_director_ui")
    state.ui_open = False
    state._toggle_freecam()
    frames(state, 3)
    shot(app, "13_freecam_marker")
    state._toggle_freecam()

    # Walk 60 m and confirm ground-level detail + headbob-height framing.
    aim(state, yaw - 120.0, -4.0)
    kd = {pygame.K_w: True}
    real = pygame.key.get_pressed

    class _Keys(dict):
        def __getitem__(self, k):        # default-False key map
            return self.get(k, False)

    pygame.key.get_pressed = lambda: _Keys(kd)   # type: ignore
    try:
        frames(state, int(8.0 / PHYS_DT / 2))
    finally:
        pygame.key.get_pressed = real    # type: ignore
    frames(state, 5)
    shot(app, "08_after_walk_ground_detail")

    print("audit complete ->", OUT, flush=True)
    app.close_cinematic()
    app.close_testing_lab()
    pygame.quit()


if __name__ == "__main__":
    main()
