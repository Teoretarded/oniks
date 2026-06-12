"""One-shot annotated map probe: open the tactical map in COMBAT, mark the
destroyer patrol anchors (red), the player radar station and base (cyan).

Run: python tools/probe_map_anchors.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame

from main import App, PHYS_DT


def main() -> int:
    from game import tactical_map as tm
    from world.combat import DESTROYER_SPAWNS, RADAR_STATION_XZ
    from world.generation import BASE_POS

    app = App(hidden=True)
    app.start_combat()
    state = app.state
    state.map_open = True
    deadline = time.time() + 120.0
    while time.time() < deadline:           # wait out the async pixel build
        state.sim_step(PHYS_DT)
        state.render(PHYS_DT)
        if tm.get_map_pixels() is not None:
            break
    for _ in range(5):                      # settle frames with the real map
        state.sim_step(PHYS_DT)
        state.render(PHYS_DT)
    surf = app.window.read_pixels_to_surface()
    view = state.tactical_map.view

    import math

    import numpy as np

    from world.spawn_zones import (CARRIER_RANGE_MAX_M, CARRIER_RANGE_MIN_M,
                                   ZONE_HALF_ANGLE_DEG, ZONE_RANGE_MAX_M,
                                   ZONE_RANGE_MIN_M, sample_fleet)

    base = (float(BASE_POS[0]), float(BASE_POS[2]))

    def ring(xz, color, r_px, w=4):
        sx, sy = view.world_to_screen((float(xz[0]), float(xz[1])))
        pygame.draw.circle(surf, color, (int(sx), int(sy)), r_px, w)

    def sector(r_in, r_out, color, w=3):
        """Sector outline: two arcs + two radial edges, in screen space."""
        bearings = [math.radians(b) for b in
                    np.linspace(-ZONE_HALF_ANGLE_DEG, ZONE_HALF_ANGLE_DEG, 60)]
        for r, brgs in ((r_in, bearings), (r_out, bearings[::-1])):
            pts = [view.world_to_screen((base[0] + r * math.sin(b),
                                         base[1] + r * math.cos(b)))
                   for b in brgs]
            pygame.draw.lines(surf, color, False,
                              [(int(x), int(y)) for x, y in pts], w)
        for b in (bearings[0], bearings[-1]):
            p0 = view.world_to_screen((base[0] + r_in * math.sin(b),
                                       base[1] + r_in * math.cos(b)))
            p1 = view.world_to_screen((base[0] + r_out * math.sin(b),
                                       base[1] + r_out * math.cos(b)))
            pygame.draw.line(surf, color, (int(p0[0]), int(p0[1])),
                             (int(p1[0]), int(p1[1])), w)

    # White: the one spawn zone ("the black"). Orange: the carrier's deep band.
    sector(ZONE_RANGE_MIN_M, ZONE_RANGE_MAX_M, (235, 235, 235))
    sector(CARRIER_RANGE_MIN_M, CARRIER_RANGE_MAX_M, (255, 160, 40))
    # One sampled fleet (seed 1337, 10 destroyers): red dots + orange carrier.
    f = sample_fleet(np.random.default_rng(1337), 10)
    for p in f["destroyers"]:
        ring(p, (255, 60, 60), 10, 3)
    ring(f["carrier"], (255, 160, 40), 16, 4)
    ring(RADAR_STATION_XZ, (80, 220, 255), 24)            # cyan: radar stn
    ring((BASE_POS[0], BASE_POS[2]), (80, 220, 255), 24)  # cyan: bastion base
    _ = DESTROYER_SPAWNS                    # current fixed pins (not drawn)
    path = os.path.join("renders", "map_anchors.png")
    os.makedirs("renders", exist_ok=True)
    pygame.image.save(surf, path)
    print(f"[probe] {os.path.abspath(path)}")
    pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
