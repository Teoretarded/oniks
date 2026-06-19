"""M5 #3 MEASURE the player COUNTER-BATTERY / EARLY-WARNING RADAR (CBR).

The CBR is a fixed PLAYER ground radar that (a) catches INBOUND strike tracks
EARLY (tall mast + long missile-class range) so the player gets a threat strip
with time-to-impact, and (b) BACK-PLOTS the SHOOTER using the SHARED
sim.commander.back_plot_surface() helper to produce a counter-fire CUE at the
launching ship/fighter.  It EMITS (honest cost), does NOT auto-fire.

This probe QUANTIFIES (print measured numbers, NO asserts — the probe idiom):

  1. EARLY-WARNING LEAD: at what sim_time does the CBR (tall 35 m mast + 190 km
     missile range) first DETECT a synthetic inbound sea-skimming Tomahawk vs
     the bare 18 m / 120 km RADAR STATION alone?  (The CBR should see it
     EARLIER / farther out — a longer warning.)

  2. SHOOTER-CUE ERROR: feed the CBR a young, low inbound track whose launch
     ship XZ is known, run the back-plot, and print the cue's shooter_xz error
     vs the TRUE launch ship + the error_m floor (det_range*BACKPLOT_ERR_FRAC).

  3. TTI SANITY: the threat TTI for a closing track vs a near-coincident
     analytic d/|v| estimate.

  4. SYMMETRY: the SAME (first_pos, first_vel) fed to back_plot_surface() via
     the CBR path and via the enemy commander path returns IDENTICAL output.

Run: python tools/probe_cbr.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from sim.radar import Radar, radar_horizon_m
from sim.commander import back_plot_surface, BACKPLOT_ERR_FRAC
from sim.counter_battery import (
    CbrTracker, CBR_ANTENNA_M, CBR_RANGES,
)
from world.combat import (
    RADAR_ANTENNA_M, PLAYER_RADAR_RANGES, RADAR_STATION_XZ,
)
from world.generation import terrain_height_scalar


class _Track:
    """Duck-typed inbound round: pos/vel/alive + a stable id (mirror of the
    StrikeMissile attributes the world feeds the tracker)."""

    is_hostile = True
    radar_size = "missile"

    def __init__(self, tid, pos, vel, alive=True):
        self.aircraft_id = tid
        self.pos = np.asarray(pos, dtype=np.float64)
        self.vel = np.asarray(vel, dtype=np.float64)
        self.alive = alive

    def velocity(self):
        return self.vel


class _Struct:
    def __init__(self, xz):
        self.pos = np.array([xz[0], 0.0, xz[1]], dtype=np.float64)


def _fmt(x):
    return "None" if x is None else f"{x:,.1f}"


def main():
    print("#" * 72)
    print("# CBR PROBE  (counter-battery / early-warning radar)")
    print(f"#   CBR    : antenna {CBR_ANTENNA_M} m, missile range "
          f"{CBR_RANGES['missile']:,.0f} m")
    print(f"#   STATION: antenna {RADAR_ANTENNA_M} m, missile range "
          f"{PLAYER_RADAR_RANGES['missile']:,.0f} m")
    print(f"#   BACKPLOT_ERR_FRAC = {BACKPLOT_ERR_FRAC}")
    print("#" * 72)

    # Site both radars at a FLAT over-water datum (height_fn == 0) so the
    # comparison is PURE mast-height + range-class — no coastal hill raising one
    # set's horizon or terrain-masking the inbound (the world wiring sites the
    # real CBR on the coast; this probe isolates the physics).
    rx, rz = 0.0, 0.0
    ry = 0.0
    flat = lambda x, z: 0.0
    cbr = Radar("cbr_probe", (rx, ry, rz), CBR_ANTENNA_M, CBR_RANGES,
                height_fn=flat)
    station = Radar("station_probe", (rx, ry, rz),
                    RADAR_ANTENNA_M, PLAYER_RADAR_RANGES, height_fn=flat)

    # ---- 1. EARLY-WARNING LEAD ------------------------------------------------
    # A sea-skimming Tomahawk inbound from the NORTH at 15 m AGL, 250 m/s,
    # starting 230 km out and closing straight toward the radars over flat water.
    # Walk it in and record the first detect of each radar.
    v = 250.0
    start_range = 230_000.0
    alt = 15.0
    cbr_first = None
    stn_first = None
    DT = 0.5
    t = 0.0
    rng = start_range
    while rng > 0 and t < 2000.0:
        # Inbound from +z (north): pos z decreasing toward the station z.
        pos = np.array([rx, alt, rz + rng], dtype=np.float64)
        if cbr_first is None and cbr.detects(pos, "missile"):
            cbr_first = (t, rng)
        if stn_first is None and station.detects(pos, "missile"):
            stn_first = (t, rng)
        if cbr_first and stn_first:
            break
        rng -= v * DT
        t += DT

    print("\n=== 1. EARLY-WARNING LEAD (sea-skim Tomahawk, 15 m AGL, 250 m/s) ===")
    print(f"  CBR     first detect: t={_fmt(cbr_first[0]) if cbr_first else 'NEVER':>8}"
          f"  at range {_fmt(cbr_first[1]) if cbr_first else 'NEVER'} m")
    print(f"  STATION first detect: t={_fmt(stn_first[0]) if stn_first else 'NEVER':>8}"
          f"  at range {_fmt(stn_first[1]) if stn_first else 'NEVER'} m")
    if cbr_first and stn_first:
        lead_s = stn_first[0] - cbr_first[0]
        lead_m = cbr_first[1] - stn_first[1]
        print(f"  --> CBR early-detection LEAD: {lead_s:,.1f} s  "
              f"({lead_m:,.0f} m farther out)")
    print(f"  (horizon @ 35 m vs 15 m skimmer = "
          f"{radar_horizon_m(CBR_ANTENNA_M, alt):,.0f} m; "
          f"@ 18 m = {radar_horizon_m(RADAR_ANTENNA_M, alt):,.0f} m)")

    # ---- 2. SHOOTER-CUE ERROR -------------------------------------------------
    # A young, low boost-climbing inbound just off a launch ship 60 km north of
    # the coast.  The CBR back-plots the shooter.  We feed it as a fresh track
    # and read the cue.
    ship_xz = (12_000.0, 60_000.0)        # true launch ship XZ (north, at sea)
    tracker = CbrTracker(cbr)
    # First-detection state: low + climbing (vy >= BACKPLOT_CLIMB_VY) just after
    # launch, a few km downrange of the ship toward the coast.
    first_pos = np.array([ship_xz[0] + 600.0, 900.0, ship_xz[1] - 4_000.0],
                         dtype=np.float64)
    first_vel = np.array([40.0, 120.0, -300.0], dtype=np.float64)
    tr = _Track("inbound_cue", first_pos, first_vel)
    out = tracker.step([tr], [_Struct((rx, rz))], sim_time=0.0)
    cues = out["cues"]
    print("\n=== 2. SHOOTER-CUE ERROR (young low climbing inbound) ===")
    print(f"  true launch ship XZ: {ship_xz}")
    if cues:
        c = cues[0]
        sx, sz = c["shooter_xz"]
        err = math.hypot(sx - ship_xz[0], sz - ship_xz[1])
        print(f"  cue shooter_xz:      ({sx:,.1f}, {sz:,.1f})")
        print(f"  cue error vs ship:   {err:,.1f} m")
        print(f"  cue error_m (floor): {c['error_m']:,.1f} m "
              f"(= det_range*{BACKPLOT_ERR_FRAC})")
    else:
        print("  (no cue produced)")

    # ---- 3. TTI SANITY --------------------------------------------------------
    print("\n=== 3. TTI SANITY ===")
    threats = out["threats"]
    if threats:
        th = threats[0]
        # analytic: ground distance to the structure / horizontal speed
        ex = float(first_pos[0]); ez = float(first_pos[2])
        d = math.hypot(rx - ex, rz - ez)
        speed3 = math.sqrt(float(first_vel[0])**2 + float(first_vel[1])**2
                           + float(first_vel[2])**2)
        analytic = d / speed3
        print(f"  threat TTI (tracker): {th['tti']:,.1f} s")
        print(f"  analytic d/|v|:       {analytic:,.1f} s")
    else:
        print("  (no threat produced)")

    # ---- 4. SYMMETRY ----------------------------------------------------------
    print("\n=== 4. SYMMETRY (CBR path == enemy commander path) ===")
    same_in_pos = first_pos.copy()
    same_in_vel = first_vel.copy()
    enemy_out = back_plot_surface(same_in_pos, same_in_vel)
    cbr_out = tracker._shooter_xz(same_in_pos, same_in_vel)
    print(f"  enemy back_plot_surface(): {enemy_out}")
    print(f"  CBR _shooter_xz()        : {cbr_out}")
    print(f"  IDENTICAL: {enemy_out == cbr_out}")


if __name__ == "__main__":
    main()
