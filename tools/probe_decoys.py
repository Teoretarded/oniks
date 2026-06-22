"""M5 #5 MEASURE the ESM DECOY EMITTER + CORNER-REFLECTOR back-plot decoys.

Two cheap player spoofers, both fooling the enemy AI because its SENSORS are
fooled (NEVER a truth edit / miss flag):

  (1) a DECOY EMITTER radiates a radar-like signature -> the enemy ESM fixes it
      and the commander schedules a HARM package at the WORTHLESS decoy id
      (the HARM is wasted on bait).

  (2) a CORNER REFLECTOR plants a false RF return near a fake coastal point ->
      the enemy's launch back-plot is biased toward the reflector, a LaunchCluster
      forms on the decoy coast, and a TLAM/JASSM salvo refines onto EMPTY ground
      (the real TEL survives).

This probe QUANTIFIES (print measured numbers, NO asserts — the probe idiom):

  1. HARM DIVERSION: with the decoy EMITTING and the real radar SILENT, which
     emitter id does the enemy commander schedule its HARM package against?
     (-> the decoy id == HARM wasted on bait.)

  2. DECOY DETECTS NOTHING: confirm the decoy emitter's radar.detects() returns
     False for a target sitting right on top of it (empty ranges -> bait, not a
     sensor).

  3. REFLECTOR-BIASED CLUSTER: feed a real player launch's first-seen geometry
     through the back-plot, WITH and WITHOUT a nearby corner reflector, and print
     the cluster centroid offset toward the reflector vs the real pad.

  4. STALE-CLUSTER -> DIRT: a TLAM aimed at the reflector-biased centroid runs
     _refine_strike_aim and finds NO real structure within SEEKER_BASKET_M ->
     ground level (empty dirt), so the real TEL survives.

  5. SYMMETRY: the SAME (first_pos, first_vel) fed to back_plot_surface() and to
     the decoy bias helper at zero influence returns the un-biased plot (the
     bias is an ADD to the same shared geometry, never a separate path).

Run: python tools/probe_decoys.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from sim.commander import (
    EnemyCommander, back_plot_surface, BACKPLOT_ERR_FRAC,
    BACKPLOT_FIXES_NEEDED, BACKPLOT_CLUSTER_R_M,
)
from sim.decoys import (
    DecoyEmitter, CornerReflector, biased_back_plot, DECOY_RANGES,
)
from world.combat import CombatWorld, RADAR_STATION_XZ, SEEKER_BASKET_M
from world.combat_config import CombatConfig
from world.generation import terrain_height_scalar

DT = 1.0 / 120.0


def _fmt(x):
    return "None" if x is None else f"{x:,.1f}"


def main():
    print("#" * 72)
    print("# DECOY PROBE  (ESM decoy emitter + corner-reflector back-plot decoy)")
    print(f"#   DECOY_RANGES = {DECOY_RANGES}  (empty -> never detects)")
    print(f"#   BACKPLOT_ERR_FRAC = {BACKPLOT_ERR_FRAC}")
    print(f"#   SEEKER_BASKET_M = {SEEKER_BASKET_M}")
    print("#" * 72)

    # ---- 1. HARM DIVERSION ----------------------------------------------------
    # A world with 1 decoy + the real radar SILENCED: the only located emitter the
    # commander can find is the decoy, so it schedules the HARM at the decoy id.
    cfg = CombatConfig(seed=1337, n_decoys=1, n_corner_reflectors=0)
    cw = CombatWorld(cfg)
    cw.radar_station.emitting = False        # real eyes go dark
    decoy_ids = [d.radar_id for d in cw._decoy_emitters]
    print("\n=== 1. HARM DIVERSION (decoy lit, real radar SILENT) ===")
    print(f"  real radar id   : {cw.radar_station.radar_id} (emitting={cw.radar_station.emitting})")
    print(f"  decoy emitter id: {decoy_ids}")
    harm_target = None
    for i in range(int(200 * 120)):    # up to 200 s for the ESM fix to mature
        cw.step(DT)
        for rec in cw._cmd_missions:
            if rec["kind"] == "harm_package":
                harm_target = rec["target_id"]
                break
        if harm_target is not None:
            break
    print(f"  HARM scheduled vs target_id: {harm_target}  "
          f"(decoy? {harm_target in decoy_ids})")

    # ---- 2. DECOY DETECTS NOTHING --------------------------------------------
    print("\n=== 2. DECOY DETECTS NOTHING (empty ranges -> bait, not a sensor) ===")
    d = cw._decoy_emitters[0]
    on_top = np.array([float(d.pos[0]), 10.0, float(d.pos[2])], dtype=np.float64)
    for size in ("ship", "fighter", "missile", "stealth"):
        print(f"  decoy.detects(on-top target, {size:>8}) = {d.detects(on_top, size)}")

    # ---- 3. REFLECTOR-BIASED CLUSTER -----------------------------------------
    # A real player launch from the Bastion pad (the first Oniks TEL).  Its
    # level-skimmer first-seen geometry back-plots to ~the home coast; a corner
    # reflector planted on a FAKE coast point off to one side biases the plot
    # toward it, so the cluster centroid moves AWAY from the real pad.
    pad = cw._oniks_launcher_positions[0]
    pad_xz = (float(pad[0]), float(pad[2]))
    # A real player Oniks: launched from the home coast pad, flying NORTH (vz > 0,
    # z increasing toward the enemy) as a level sea-skimmer.  First detected a few
    # km downrange (north) of the pad; the back-plot projects it back to the coast.
    first_pos = np.array([pad_xz[0] + 200.0, 30.0, 5_000.0], dtype=np.float64)
    first_vel = np.array([10.0, 0.0, 250.0], dtype=np.float64)
    plain = back_plot_surface(first_pos, first_vel)
    # Reflector planted ~6 km EAST of the real back-plot, on the coast.
    refl_xz = (plain[0] + 6_000.0, plain[1])
    reflector = CornerReflector("cr_probe", np.array([refl_xz[0], 0.0, refl_xz[1]]))
    biased = biased_back_plot(first_pos, first_vel, reflector)
    print("\n=== 3. REFLECTOR-BIASED CLUSTER ===")
    print(f"  real pad XZ           : ({pad_xz[0]:,.1f}, {pad_xz[1]:,.1f})")
    print(f"  plain back-plot XZ    : ({plain[0]:,.1f}, {plain[1]:,.1f})")
    print(f"  reflector XZ          : ({refl_xz[0]:,.1f}, {refl_xz[1]:,.1f})")
    if biased is not None:
        print(f"  BIASED back-plot XZ   : ({biased[0]:,.1f}, {biased[1]:,.1f})")
        d_real = math.hypot(biased[0] - pad_xz[0], biased[1] - pad_xz[1])
        d_refl = math.hypot(biased[0] - refl_xz[0], biased[1] - refl_xz[1])
        print(f"  biased plot dist to real pad : {d_real:,.1f} m")
        print(f"  biased plot dist to reflector: {d_refl:,.1f} m  "
              f"(reflector pulls the cluster off the pad)")

    # ---- 4. STALE-CLUSTER -> DIRT (real TEL survives) -------------------------
    # A salvo aimed at the reflector-biased centroid runs _refine_strike_aim: if
    # NO live structure sits within SEEKER_BASKET_M of the decoy coast point, the
    # round flies into empty dirt.
    print("\n=== 4. REFLECTOR CENTROID -> _refine_strike_aim -> DIRT ===")
    cw2 = CombatWorld(CombatConfig(seed=1337, n_decoys=0, n_corner_reflectors=0))
    if biased is not None:
        ax, az, ay = cw2._refine_strike_aim(biased[0], biased[1])
        nearest = min(
            (math.hypot(float(s.pos[0]) - biased[0],
                        float(s.pos[2]) - biased[1])
             for s in cw2.structures if s.alive), default=float("inf"))
        on_struct = nearest < SEEKER_BASKET_M
        print(f"  aim at biased centroid -> ({ax:,.1f}, {az:,.1f}, y={ay:,.1f})")
        print(f"  nearest LIVE structure : {nearest:,.1f} m  "
              f"(< basket {SEEKER_BASKET_M}? {on_struct})")
        print(f"  --> {'HIT a structure' if on_struct else 'EMPTY DIRT (TEL survives)'}")

    # ---- 5. SYMMETRY ----------------------------------------------------------
    print("\n=== 5. SYMMETRY (zero-influence bias == plain back-plot) ===")
    far = CornerReflector("cr_far", np.array([plain[0] + 9e9, 0.0, plain[1]]))
    zero_bias = biased_back_plot(first_pos, first_vel, far)
    print(f"  plain back_plot_surface() : {plain}")
    print(f"  far-reflector bias        : {zero_bias}")
    if plain is not None and zero_bias is not None:
        drift = math.hypot(zero_bias[0] - plain[0], zero_bias[1] - plain[1])
        print(f"  drift (should be ~0)      : {drift:,.3f} m")


if __name__ == "__main__":
    main()
