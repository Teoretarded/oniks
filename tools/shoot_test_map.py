"""Visual audit of the F3 lab TEST MAP tab (6-DOF test chamber).

usage: python -m tools.shoot_test_map

Boots the real app hidden, enters the lab's TEST MAP mode, and captures:

    renders/test_map_pad.png        the article resting on the pad
    renders/test_map_close.png      close orbit of the new model
    renders/test_map_force_tool.png thrust/CG/CP overlays + armed pick box
    renders/test_map_hover_N.png    powered flight at t = 2 / 8 / 20 s
    renders/test_map_tipover_N.png  2 deg thrust misalignment at t = 2 / 5 s
    renders/test_map_proto_*.png    focused manual-control prototypes

Read the PNGs after every model/physics change (CLAUDE.md: render, don't
guess)."""

from __future__ import annotations

import math
import os
import sys

import pygame

from main import PHYS_DT, App

OUT = "renders"


def _shot(app, lab, name: str) -> None:
    lab.render(0.0)
    surf = app.window.read_pixels_to_surface()
    path = os.path.join(OUT, f"{name}.png")
    pygame.image.save(surf, path)
    print("saved", path)


def _fly(app, lab, seconds: float, shots: dict[float, str]) -> None:
    """Step real 120 Hz physics, screenshotting at the marked times."""
    pending = sorted(shots.items())
    steps = int(round(seconds / PHYS_DT))
    for i in range(steps):
        lab.sim_step(PHYS_DT)
        t = lab.testmap_body.t
        if pending and t >= pending[0][0]:
            _shot(app, lab, pending.pop(0)[1])
    for _, name in pending:
        _shot(app, lab, name)


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    app = App(hidden=True)
    app.open_testing_lab()
    lab = app.testing_lab
    lab._set_lab_mode("testmap")
    lab.ui_hidden = True

    # 1. On the pad, wide.
    lab.orbit_dist = 14.0
    lab.orbit_el = math.radians(14.0)
    lab._apply_camera()
    _shot(app, lab, "test_map_pad")

    # 2. Close orbit of the new model.
    lab.orbit_dist = 5.5
    lab.orbit_az = math.radians(120.0)
    lab.orbit_el = math.radians(6.0)
    lab._apply_camera()
    _shot(app, lab, "test_map_close")

    # 2b. UI + instrumentation audit on the favorite spin experiment.
    lab.testmap_article = 1
    lab._reset_testmap_body()
    lab.orbit_dist = 7.0
    lab.orbit_az = math.radians(120.0)
    lab._apply_camera()
    lab.ui_hidden = False
    lab.testmap_body.ignite()
    lab.sim_step(PHYS_DT)
    lab.testmap_force_mode = True
    lab._testmap_pick_z = 0.5
    _shot(app, lab, "test_map_spin_ui")
    lab.testmap_force_mode = False
    lab._testmap_pick_z = None
    lab.ui_hidden = True

    # 3. Powered flight: climb-out frames.
    lab.testmap_article = 0
    lab._reset_testmap_body()
    lab.orbit_dist = 16.0
    lab.orbit_az = math.radians(35.0)
    lab.orbit_el = math.radians(10.0)
    lab.testmap_body.ignite()
    _fly(app, lab, 21.0, {2.0: "test_map_hover_0",
                          8.0: "test_map_hover_1",
                          20.0: "test_map_hover_2"})

    # 4. The failure demo: 2 deg thrust misalignment tips it over.
    lab.testmap_misaligned = True
    lab._reset_testmap_body()
    lab.orbit_dist = 16.0
    lab.testmap_body.ignite()
    _fly(app, lab, 5.5, {2.0: "test_map_tipover_0",
                         5.0: "test_map_tipover_1"})
    lab.testmap_misaligned = False

    # 5. Focused roster line-up. Automatic landing/hover articles remain in
    # the physics module, but are intentionally archived from this UI.
    for index, tag in ((1, "dart"), (2, "stick"), (3, "proto_gyro"),
                       (4, "proto_flip"), (5, "proto_rcs")):
        lab.testmap_article = index
        lab._reset_testmap_body()
        lab.orbit_dist = max(7.0, lab.testmap_body.d.length * 3.0)
        lab.orbit_az = math.radians(120.0)
        lab.orbit_el = math.radians(8.0)
        lab._apply_camera()
        _shot(app, lab, f"test_map_{tag}")

    # 6. The TVC stick balancing in flight (FCS fighting the bent motor).
    lab.testmap_article = 2
    lab._reset_testmap_body()
    lab.orbit_dist = 14.0
    lab.testmap_body.ignite()
    _fly(app, lab, 6.0, {5.5: "test_map_stick_balance"})

    # 7. Focused prototype motion audits.
    lab.testmap_article = 3                  # combined spin + TVC
    lab._reset_testmap_body()
    lab.testmap_body.ignite()
    lab.orbit_dist = 12.0
    _fly(app, lab, 8.0, {7.5: "test_map_gyro_flight"})

    lab.testmap_article = 4                  # brake geometry + dynamics
    lab._reset_testmap_body()
    lab.testmap_body.airbrake_deployed = True
    lab.orbit_dist = 12.0
    _shot(app, lab, "test_map_flip_open")
    _fly(app, lab, 6.0, {5.5: "test_map_flip_braking"})

    lab.testmap_article = 5                  # manual thin-air RCS
    lab._reset_testmap_body()
    lab.orbit_dist = 11.0
    lab.testmap_body.pulse_rcs((1.0, 0.0, 0.0), duration=2.0)
    _fly(app, lab, 2.0, {1.8: "test_map_rcs_manual_pulse"})

    lab.testmap_article = 0
    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
