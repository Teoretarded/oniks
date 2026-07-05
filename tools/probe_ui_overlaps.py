"""UI layout oracle probe (AI-testability build, 2026-07-05).

Boots the real game hidden, forces the layout situations a human hits
(battle HUD per platform; the map with BOTH a selected flying round and a
selected contact — the exact overlap reported in playtest 2026-07-05),
renders each, and asserts the per-frame UI registry reports ZERO
overlapping sibling panels.  This is how an AI 'looks' at the UI without
eyes: every registered panel's rect is checked geometrically.

Run: python tools/probe_ui_overlaps.py  -> PASS/FAIL lines, exit 0/1.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pygame

FAILS = []


def check(name, pairs):
    ok = pairs == []
    print(f"[probe] {'PASS' if ok else 'FAIL'}  {name}"
          + ("" if ok else f"  overlaps={pairs}"))
    if not ok:
        FAILS.append(name)


def main() -> int:
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from main import App, PHYS_DT
    app = App(hidden=True)
    app.start_combat()
    state = app.state

    # --- 3D HUD, every platform plate --------------------------------------
    for _ in range(len(state.PLATFORMS)):
        state.render(1 / 60)
        check(f"3D HUD [{state.active_platform}] has no overlapping panels",
              state.ui.overlaps())
        state.handle_event(pygame.event.Event(pygame.KEYDOWN,
                                              key=pygame.K_TAB))

    # --- the reported case: map + selected round + selected contact --------
    state.target_point = np.array([0.0, 0.0, 200_000.0])
    state.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
    for _ in range(240):
        state.sim_step(PHYS_DT)
    state.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_m))
    own = [m for m in state.world.missiles
           if not getattr(m, "is_hostile", False)]
    state.tactical_map.selected_missile = own[0] if own else None
    tracks = list(state.world.contacts.tracks)
    state.tactical_map.selected_contact = tracks[0] if tracks else None
    state.render(1 / 60)
    check("map + selected round + selected contact (playtest overlap case)",
          state.ui.overlaps())

    pygame.quit()
    print(f"[probe] {'ALL PASS' if not FAILS else f'{len(FAILS)} FAIL'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
