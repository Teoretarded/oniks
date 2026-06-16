"""Probe: enemy FIGHTER onboard sensing (nose radar).

Measures what a Fighter can SENSE on its own via FighterRadar:
  * forward-cone half-angle (claimed +-60 deg)
  * max range per size class (fighter/ship/missile/stealth)
  * horizon gating vs the 18 km recon drone (the hard case)
  * emit/alive gates (parked / silent fighter sees nothing)
  * how the world wires the nose radar into the EnemyPicture + drone reacquire
  * determinism of the whole chain across two identical seeded runs

Run: python tools/probe_audit_fighter_radar.py   (ignore the pygame banner on stderr)
"""
import os
import sys
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from sim.enemy_air import (  # noqa: E402
    Fighter, FighterRadar, AirBase,
    FIGHTER_RADAR_FOV_HALF, FIGHTER_RADAR_RANGES, FIGHTER_ALT_M,
    FS_PARKED, FS_ON_STATION, FS_TRANSIT,
)
from sim.radar import radar_horizon_m  # noqa: E402


def banner(t):
    print("\n" + "=" * 70)
    print(t)
    print("=" * 70)


# ---------------------------------------------------------------------------
# A bare fighter we can drive directly (no GL, no full world).
# ---------------------------------------------------------------------------
class _Site:
    def __init__(self, xz, y=0.0):
        self.alive = True
        self.pos = np.array([xz[0], y, xz[1]], dtype=np.float64)


def make_fighter(pos_xyz, heading=0.0):
    base = AirBase(_Site((pos_xyz[0], pos_xyz[2]), y=pos_xyz[1]))
    f = Fighter("PROBE1", base, patrol_anchor_xz=(pos_xyz[0], pos_xyz[2]))
    f.pos[:] = pos_xyz
    f.heading = heading
    f.state = FS_ON_STATION          # airborne so .alive is True
    f.radar.emitting = True
    # Sync radar pos + heading the way Fighter.update() does each tick.
    f.radar.pos[0] = f.pos[0]
    f.radar.pos[1] = f.pos[1]
    f.radar.pos[2] = f.pos[2]
    f.radar._heading_ref = f.heading
    return f


banner("1. CONE HALF-ANGLE  (claimed +-60 deg)")
print(f"FIGHTER_RADAR_FOV_HALF = {math.degrees(FIGHTER_RADAR_FOV_HALF):.1f} deg")
# Fighter at 9 km, heading 0 (=+Z). Put a fighter-size target at 50 km on a
# bearing we sweep. 50 km is well inside the 110 km fighter range and inside
# the horizon at these altitudes, so only the cone gate can fail.
f = make_fighter([0.0, FIGHTER_ALT_M, 0.0], heading=0.0)
R = 50_000.0
TGT_ALT = FIGHTER_ALT_M
last_in = None
edges = []
prev = None
for deg in range(0, 181, 1):
    br = math.radians(deg)
    tgt = [R * math.sin(br), TGT_ALT, R * math.cos(br)]
    got = f.radar.detects(tgt, "fighter")
    if prev is not None and got != prev:
        edges.append(deg)
    prev = got
print(f"detect transitions (deg off nose) at bearings: {edges}")
print(f"  -> measured one-sided cut-off ~= {edges[0] if edges else 'n/a'} deg "
      f"(expected 60)")
# Spot checks
for deg in (0, 30, 59, 60, 61, 90):
    br = math.radians(deg)
    tgt = [R * math.sin(br), TGT_ALT, R * math.cos(br)]
    print(f"  bearing {deg:3d} deg off nose: detects={f.radar.detects(tgt,'fighter')}")


banner("2. MAX RANGE PER SIZE CLASS  (on-boresight, co-altitude)")
print(f"declared FIGHTER_RADAR_RANGES = {FIGHTER_RADAR_RANGES}")
f = make_fighter([0.0, FIGHTER_ALT_M, 0.0], heading=0.0)
for cls, declared in FIGHTER_RADAR_RANGES.items():
    # binary search the boresight detection range at co-altitude (horizon huge)
    lo, hi = 0.0, declared * 2.0
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        tgt = [0.0, FIGHTER_ALT_M, mid]   # dead ahead (+Z)
        if f.radar.detects(tgt, cls):
            lo = mid
        else:
            hi = mid
    print(f"  {cls:8s}: measured max detect range = {lo/1000:7.2f} km  "
          f"(declared {declared/1000:.1f} km)")


banner("3. HORIZON GATE vs the 18 km RECON DRONE (size class 'stealth')")
# Drone cruises at DRONE_ALT_M = 18 000 m, class 'stealth' (11 km nose range).
# Fighter at the 9 km CAP altitude. Is 11 km even reachable given horizon?
DRONE_ALT = 18_000.0
horizon = radar_horizon_m(FIGHTER_ALT_M, DRONE_ALT)
print(f"4/3-earth horizon (fighter 9 km vs drone 18 km) = {horizon/1000:.0f} km")
print(f"stealth nose range = {FIGHTER_RADAR_RANGES['stealth']/1000:.0f} km "
      f"-> range, not horizon, is the binding limit")
f = make_fighter([0.0, FIGHTER_ALT_M, 0.0], heading=0.0)
for d_km in (5, 10, 11, 12, 15):
    tgt = [0.0, DRONE_ALT, d_km * 1000.0]
    print(f"  drone dead ahead at {d_km:2d} km ground range, 18 km alt: "
          f"detects(stealth)={f.radar.detects(tgt, 'stealth')}")
# Now from the intercept ceiling (snap-up climb target)
f2 = make_fighter([0.0, 15_500.0, 0.0], heading=0.0)
print("  -- fighter snapped up to 15.5 km ceiling --")
for d_km in (10, 11, 12):
    tgt = [0.0, DRONE_ALT, d_km * 1000.0]
    print(f"  drone at {d_km:2d} km ground range: "
          f"detects(stealth)={f2.radar.detects(tgt, 'stealth')}")


banner("4. EMIT / ALIVE / AIRBORNE GATES")
f = make_fighter([0.0, FIGHTER_ALT_M, 0.0], heading=0.0)
tgt = [0.0, FIGHTER_ALT_M, 40_000.0]   # dead ahead, in range
print(f"airborne + emitting : detects fighter @40km = {f.radar.detects(tgt,'fighter')}")
f.radar.emitting = False
print(f"radar silent        : detects = {f.radar.detects(tgt,'fighter')}")
f.radar.emitting = True
f.radar.alive = False
print(f"radar dead          : detects = {f.radar.detects(tgt,'fighter')}")
f.radar.alive = True
# Parked fighter: world only adds radars of f.alive fighters; a parked
# fighter's .alive is False, so it's excluded from the picture entirely.
fp = make_fighter([0.0, 0.0, 0.0], heading=0.0)
fp.state = FS_PARKED
print(f"parked fighter .alive = {fp.alive} (False -> excluded from "
      f"world _enemy_sensor_radars())")


banner("5. RAW vs CONE: does cone-gating actually subtract coverage?")
# Compare a plain Radar (AWACS-style, no cone) vs the FighterRadar at the
# same boresight target placed behind the nose.
f = make_fighter([0.0, FIGHTER_ALT_M, 0.0], heading=0.0)  # nose = +Z
behind = [0.0, FIGHTER_ALT_M, -40_000.0]   # 40 km dead astern, in range
print(f"target 40 km DEAD ASTERN, in range:")
print(f"  FighterRadar.detects(fighter) = {f.radar.detects(behind,'fighter')} "
      f"(cone should reject)")
print(f"  underlying Radar.detects      = "
      f"{f.radar._radar.detects(behind,'fighter')} (no cone)")


banner("6. WORLD WIRING + DRONE REACQUIRE + DETERMINISM (full CombatWorld)")
try:
    from tools.playtest_harness import build_world
    from sim.enemy_air import Fighter as _F

    def run(seed, steps=60 * 90):
        w = build_world(seed)
        # Confirm fighter nose radars are in the commander's sensor set.
        sensors = w._enemy_sensor_radars()
        n_fighter_radars = sum(1 for r in sensors
                               if isinstance(r, FighterRadar))
        n_air = len(getattr(w, "_fighter_list", []))
        # Step the sim; watch for any fighter nose-radar drone reacquire and
        # any drone track entering the picture.
        reacq = 0
        max_track = 0
        airborne_seen = 0
        for _ in range(steps):
            from main import PHYS_DT
            w.step(PHYS_DT)
            for fr in getattr(w, "_fighter_list", []):
                if fr.alive:
                    airborne_seen = max(airborne_seen, 1)
            dt_tracks = len(w.commander.picture.drone_tracks)
            max_track = max(max_track, dt_tracks)
            # count fighters in entity-pursuit (own radar reacquired the drone)
            for fr in getattr(w, "_fighter_list", []):
                if getattr(fr, "_intercept_target", None) is not None:
                    reacq += 1
        return dict(n_fighter_radars=n_fighter_radars, n_air=n_air,
                    max_drone_tracks=max_track, reacq_ticks=reacq,
                    any_airborne=airborne_seen,
                    sim_time=round(w.sim_time, 2))

    try:
        from main import PHYS_DT  # noqa: F401
        a = run(7)
        b = run(7)
        print(f"seed 7 run A: {a}")
        print(f"seed 7 run B: {b}")
        print(f"DETERMINISTIC (A==B): {a == b}")
    except Exception as e:
        import traceback
        print("world-step probe failed:", e)
        traceback.print_exc()
except Exception as e:
    import traceback
    print("world build failed:", e)
    traceback.print_exc()

print("\nDONE")
