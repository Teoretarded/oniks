"""Visual probe for the M orbit view (2026-07-17).

Shots into renders/cinematic_audit/: mid-ascent over the valley, LEO
over the Alps, the full Earth from 4,000 km, a low pass at 120 km, a
T-mark set from orbit, and the ride back down.

Usage: python tools/probe_globe.py [lauterbrunnen]
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pygame

from tools.shoot_cinematic import frames, set_mood, shot, wait_for_l0
from main import App


def main() -> None:
    scene = sys.argv[1] if len(sys.argv) > 1 else "lauterbrunnen"
    app = App(hidden=True)
    app.open_testing_lab()
    app.open_cinematic(os.path.join("assets", "cinematic", scene))
    state = app.state
    frames(state, 10)
    wait_for_l0(state)

    state._toggle_globe()
    assert state.globe_mode == "ascend", state.globe_mode
    print(f"globe anchor: {state._g_anchor}", flush=True)

    # Mid-ascent: the valley shrinking below, sky darkening.
    frames(state, int(2.2 * 60), sim=False)
    shot(app, "50_ascent_mid")
    # Orbit entry at 500 km.
    frames(state, int(3.5 * 60), sim=False)
    print(f"mode={state.globe_mode} alt={state.globe_alt/1000:.0f} km",
          flush=True)
    shot(app, "51_orbit_500km")

    # Zoom out to see the whole planet.
    state.globe_alt = 4_000_000.0
    frames(state, 5, sim=False)
    shot(app, "52_earth_4000km")

    # Terminator sweep: low golden sun puts the day/night line across
    # the visible disc; night mood shows the moonlit floor + stars.
    set_mood(state, "golden")
    frames(state, 5, sim=False)
    shot(app, "52b_terminator_golden")
    set_mood(state, "night")
    frames(state, 5, sim=False)
    shot(app, "52c_night_side_stars")
    set_mood(state, "alpine")
    frames(state, 5, sim=False)

    # Pan away (Italy-ish) and back.
    state.globe_lat -= 4.0
    state.globe_lon += 5.0
    frames(state, 5, sim=False)
    shot(app, "53_panned_southeast")
    state.globe_lat, state.globe_lon = state._g_anchor

    # Low pass at 120 km: the rings on the planet.
    state.globe_alt = 120_000.0
    frames(state, 5, sim=False)
    shot(app, "54_low_pass_120km")

    # T from orbit: mark the reticle (the anchor itself).
    state._designate_target()
    print(f"orbit mark: {state.icbm_target}", flush=True)
    frames(state, 3, sim=False)
    shot(app, "55_orbit_mark_set")

    # Ride back down.
    state._toggle_globe()
    frames(state, int(5.5 * 60), sim=False)
    print(f"mode after return: {state.globe_mode}", flush=True)
    shot(app, "56_back_on_the_ground")

    app.close_cinematic()
    app.close_testing_lab()
    pygame.quit()
    print("globe probe complete", flush=True)


if __name__ == "__main__":
    sys.exit(main())
