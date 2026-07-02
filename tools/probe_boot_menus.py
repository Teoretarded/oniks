"""One-shot boot probe: menu -> setup -> battle -> pause -> resume -> map,
screenshotting each surface.  Exercises the real state-machine wiring the
smoke tools skip (they jump straight to start_combat).

Run: python tools/probe_boot_menus.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame

from main import App, PHYS_DT


def save(app, name):
    pygame.image.save(app.window.read_pixels_to_surface(),
                      os.path.join("renders", name))
    print(f"[boot] renders/{name}")


def key(app, k):
    app.state.handle_event(pygame.event.Event(pygame.KEYDOWN, key=k, mod=0,
                                              unicode=""))
    app.state.handle_event(pygame.event.Event(pygame.KEYUP, key=k, mod=0))


def settle(app, frames=10):
    """Render enough frames for any press-flash pending action to fire."""
    for _ in range(frames):
        app.state.render(1.0 / 60.0)


def main() -> int:
    app = App(hidden=True)
    print("[boot] state:", type(app.state).__name__)
    settle(app)
    save(app, "boot_01_menu.png")

    # Menu -> COMBAT (row 1)
    key(app, pygame.K_DOWN)
    key(app, pygame.K_RETURN)
    settle(app)
    print("[boot] state:", type(app.state).__name__)
    save(app, "boot_02_setup.png")

    # START the battle from the setup screen: selection WRAPS, so one UP from
    # row 0 lands on the last row (START); ENTER confirms.
    key(app, pygame.K_UP)
    key(app, pygame.K_RETURN)
    settle(app, 30)
    print("[boot] state:", type(app.state).__name__)

    # A few sim steps + a frame
    for _ in range(120):
        app.state.sim_step(PHYS_DT)
    settle(app, 3)
    save(app, "boot_03_battle.png")

    # Pause menu over the frozen frame
    key(app, pygame.K_ESCAPE)
    settle(app)
    print("[boot] state:", type(app.state).__name__)
    save(app, "boot_04_pause.png")

    # Resume
    key(app, pygame.K_ESCAPE)
    settle(app)
    print("[boot] state:", type(app.state).__name__)

    # Tactical map + F1 overlay
    key(app, pygame.K_m)
    settle(app, 3)
    save(app, "boot_05_map.png")
    key(app, pygame.K_F1)
    settle(app, 3)
    save(app, "boot_06_controls_overlay.png")

    print("[boot] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
