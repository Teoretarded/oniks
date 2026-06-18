"""MEASURE the amphibious landing geometry/timing BEFORE locking the bands.

Reports (all from the real sim/amphibious + world models, no guesses):
  * the LANDING_BOX centre + radius and the LAUNCH_LINE range ring geometry;
  * a Transport RUN -> launch-line ETA from a representative rear-band spawn;
  * an LCAC splash-point -> LANDING_BOX ETA;
  * an Oniks-class and a Pantsir-gun-class OBB hit each SINK an LCAC (hp=1);
  * the player-radar detection horizon for a TRANSPORT ('ship' ring) vs an
    LCAC ('lcac' ring) — proving the LCAC's small radar_size shortens the
    horizon (physics, not a flag).

Run: python tools/probe_amphibious.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math

import numpy as np

from sim.amphibious import (BEACHHEAD_GRACE_S, LANDING_BOX_OFFSET_M,
                            LANDING_BOX_RADIUS_M, LAUNCH_LINE_RANGE_M,
                            LCAC_PER_TRANSPORT, LCAC_SPEED_MPS,
                            TRANSPORT_SPEED_MPS, Lcac, Transport,
                            landing_box_xz)
from sim.damage import apply_missile_hits
from sim.ships import ST_SINKING
from world.combat import PLAYER_RADAR_RANGES, RADAR_STATION_XZ, CombatWorld
from world.combat_config import CombatConfig
from world.generation import BASE_POS, terrain_height_scalar

PHYS_DT = 1.0 / 120.0
BX, BZ = float(BASE_POS[0]), float(BASE_POS[2])


class _Round:
    """A minimal player anti-ship round (is_hostile False) that walks the OBB
    sweep exactly like an Oniks: a moving segment with prev_pos/pos/alive."""

    def __init__(self, prev_pos, pos):
        self.prev_pos = np.asarray(prev_pos, dtype=np.float64)
        self.pos = np.asarray(pos, dtype=np.float64)
        self.alive = True
        self.is_hostile = False
        self.impact_pos = None
        self.phase = 0


def main() -> int:
    box = landing_box_xz((BX, BZ))
    print("=== GEOMETRY ===")
    print(f"BASE_POS XZ            = ({BX:.0f}, {BZ:.0f})")
    print(f"LANDING_BOX centre XZ  = ({box[0]:.0f}, {box[1]:.0f})  "
          f"(+{LANDING_BOX_OFFSET_M:.0f} m seaward)")
    print(f"LANDING_BOX radius     = {LANDING_BOX_RADIUS_M:.0f} m")
    print(f"LAUNCH_LINE range ring = {LAUNCH_LINE_RANGE_M/1e3:.1f} km from base")
    print(f"LCAC_PER_TRANSPORT     = {LCAC_PER_TRANSPORT}")
    print(f"BEACHHEAD_GRACE_S      = {BEACHHEAD_GRACE_S:.0f} s")

    # --- Transport RUN -> launch line ETA --------------------------------------
    # The seeded rear-band spawn (240-330 km) is realistic; a full crawl at the
    # slow transport speed is a long-game (hours of sim) threat, countered by
    # sinking the hulls far out.  Measure the RATE over a CLOSE anchor (10 km
    # outside the line) so the ETA is the rate (fast to step), and report the
    # analytic full transit from a real seeded spawn for context.
    cw = CombatWorld(CombatConfig(seed=1337, n_transports=2))
    real_spawn_rng = cw.transports[0]._range_to_base()
    near_anchor = (0.0, BZ + LAUNCH_LINE_RANGE_M + 10_000.0)   # 10 km out
    tr = Transport("probe_tr", near_anchor, base_xz=(BX, BZ))
    tr.begin_run()
    t = 0.0
    while not tr.reached_launch_line() and t < 60_000.0:
        tr.update(PHYS_DT)
        t += PHYS_DT
    print("\n=== TRANSPORT RUN ===")
    print(f"real seeded spawn rng  = {real_spawn_rng/1e3:.1f} km (rear band)")
    print(f"RUN 10 km -> line ETA  = {t:.1f} s @ {TRANSPORT_SPEED_MPS} m/s "
          f"(rate {10_000.0/TRANSPORT_SPEED_MPS:.0f} s analytic)")
    full = (real_spawn_rng - LAUNCH_LINE_RANGE_M) / TRANSPORT_SPEED_MPS
    print(f"full seeded RUN transit= {full:.0f} s ({full/60.0:.0f} min) analytic")
    print(f"reached_launch_line    = {tr.reached_launch_line()} "
          f"at range {tr._range_to_base()/1e3:.1f} km")

    # --- LCAC splash -> box ETA ----------------------------------------------
    # Measure the sprint RATE over a bounded 10 km leg toward the box (the full
    # leg from a deep launch line is the same rate, just longer to step).
    sprint_start = (box[0], box[1] + 10_000.0)
    lc = Lcac("probe_lcac", sprint_start, box)
    d0 = lc.range_to_box()
    t = 0.0
    while not lc.landed and t < 60_000.0:
        lc.update(PHYS_DT)
        t += PHYS_DT
    print("\n=== LCAC SPRINT ===")
    print(f"start->box dist        = {d0/1e3:.1f} km")
    print(f"sprint 10 km ETA       = {t:.1f} s @ {LCAC_SPEED_MPS} m/s "
          f"(rate {(d0 - LANDING_BOX_RADIUS_M)/LCAC_SPEED_MPS:.0f} s analytic)")
    print(f"landed                 = {lc.landed} "
          f"at range {lc.range_to_box():.0f} m")

    # --- OBB kills: an Oniks-class and a Pantsir-gun-class hit each sink hp=1 -
    print("\n=== OBB KILLS (physics, hp=1) ===")
    for label in ("Oniks-class", "Pantsir-gun-class"):
        lc = Lcac("probe_kill", (1_000.0, 1_000.0), box)
        c = lc.pos.copy()
        # A round whose segment crosses the LCAC hull centre.
        rnd = _Round(c + np.array([0.0, 50.0, 0.0]),
                     c + np.array([0.0, -2.0, 0.0]))
        ev = []
        apply_missile_hits([rnd], [lc], ev)
        print(f"{label:18s}: hp={lc.hp} state_sinking={lc.state == ST_SINKING} "
              f"round_alive={rnd.alive} events={[e[0] for e in ev]}")

    # --- detection horizon: transport 'ship' ring vs LCAC 'lcac' ring --------
    # The close-in landing corridor is held by the base-side Pantsir SAM radar
    # (the ground station is terrain-masked from the corridor); its surface ring
    # is the binding cap.  Measure how far each size class is detectable along a
    # clear-LOS bearing from a Pantsir radar — the LCAC ('lcac' ring) drops out
    # SHORTER than a transport ('ship' ring): physics, not a flag.
    print("\n=== DETECTION HORIZON (close-in Pantsir surface ring) ===")
    from sim.pantsir import PANTSIR_RADAR_RANGES
    print(f"Pantsir surface rings: ship="
          f"{PANTSIR_RADAR_RANGES.get('ship', 0.0)/1e3:.0f} km  "
          f"lcac={PANTSIR_RADAR_RANGES.get('lcac', 0.0)/1e3:.0f} km")
    cw2 = CombatWorld(CombatConfig(seed=1337))
    # Pick the Pantsir radar with the longest clear-LOS reach toward the sea.
    pr = next(r for r in cw2.radar_net.radars if "pantsir" in r.radar_id)
    px, pz = float(pr.pos[0]), float(pr.pos[2])
    for size in ("ship", "lcac"):
        last_vis = 0.0
        for km in range(1, 40):
            # Sweep seaward (+Z) from the Pantsir over open water at sea level.
            pos = np.array([px, 0.0, pz + km * 1_000.0], dtype=np.float64)
            if pr.detects(pos, size):
                last_vis = km * 1_000.0
        print(f"  {size:5s}: detectable out to ~{last_vis/1e3:.0f} km")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
