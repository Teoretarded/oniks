"""One-shot Phase 7 visual probe: the setup screen (both pages) + end overlay.

Run: python tools/probe_setup_screen.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame

from main import App


def save(app, name):
    pygame.image.save(app.window.read_pixels_to_surface(),
                      os.path.join("renders", name))
    print(f"[probe] renders/{name}")


def main() -> int:
    app = App(hidden=True)
    app.open_combat_setup()
    setup = app.state

    setup.render(0.016)
    save(app, "probe_setup_world.png")

    # Flip to the Armory page if a page toggle exists (try TAB).
    setup.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB,
                                          unicode="\t", mod=0))
    setup.render(0.016)
    save(app, "probe_setup_armory.png")

    # End overlay: victory + defeat banners.
    try:
        from game.combat_end import CombatEndOverlay
        for outcome, name in (("victory", "probe_end_victory.png"),
                              ("defeat", "probe_end_defeat.png")):
            ov = CombatEndOverlay(app, outcome,
                                  lambda: None, lambda: None, lambda: None)
            ov.render(0.016)
            save(app, name)
    except Exception as exc:           # overlay API differs: skip, not fatal
        print(f"[probe] end-overlay skipped: {exc!r}")
    pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
