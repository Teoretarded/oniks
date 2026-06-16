"""AWACS radar detection + datalink cue audit probe.

Measures, never trusts comments:
  1. AWACS radar max detection range per size class (fighter/missile/ship/stealth)
     by binary-searching the distance at which Radar.detects flips True->False.
  2. Horizon behaviour: a sea-skimming (low-alt) target vs a high target; the
     look-down geometry the back-plot pipeline depends on.
  3. The datalink CUE path in a REAL CombatWorld:
       - is the AWACS radar in the commander's detector set (_enemy_sensor_radars)?
       - is the AWACS radar in the destroyer cue set (_enemy_cue_radars)?
       - does an AWACS-only detection of a player missile push a track into the
         EnemyPicture (commander.picture.missile_tracks)?
       - does an AWACS-only detection of the recon drone push a drone track?
  4. Determinism: same seed -> identical AWACS spawn pos + radar ranges.

Run: python tools/probe_audit_awacs.py   (ignore the pygame banner on stderr)
"""

import os
import sys
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from sim.enemy_air import Awacs, AWACS_RADAR_RANGES, AWACS_ALT_M
from sim.radar import radar_horizon_m


def banner(t):
    print("\n" + "=" * 70)
    print(t)
    print("=" * 70)


def measure_flat_range(radar, size_class, target_alt, step=500.0, cap=600_000.0):
    """Walk a target outward at fixed altitude; return the last range that
    detects True (the effective detection range for that altitude)."""
    last_true = -1.0
    r = step
    while r <= cap:
        # place target due north of the radar at the requested altitude
        tpos = np.array([float(radar.pos[0]),
                         target_alt,
                         float(radar.pos[2]) + r], dtype=np.float64)
        if radar.detects(tpos, size_class):
            last_true = r
        r += step
    return last_true


banner("1. AWACS RADAR — CONFIGURED RANGES (sim/enemy_air.py AWACS_RADAR_RANGES)")
for k, v in AWACS_RADAR_RANGES.items():
    print(f"  {k:8s}: {v/1000:8.1f} km")
print(f"  AWACS altitude (AWACS_ALT_M)      : {AWACS_ALT_M/1000:.2f} km")

# Build a lone AWACS with a flat radar position so horizon/terrain don't
# confound the pure range-class measurement. We set pos directly.
aw = Awacs("probe_awacs", (-40_000.0, 405_000.0), (40_000.0, 435_000.0))
print(f"  AWACS spawn pos                   : "
      f"x={aw.pos[0]:.0f} y={aw.pos[1]:.0f} z={aw.pos[2]:.0f}")
print(f"  radar antenna_alt (pos[1]+offset) : {aw.radar.antenna_alt:.1f} m")
print(f"  radar emitting / alive            : "
      f"{aw.radar.emitting} / {aw.radar.alive}")

banner("2. MEASURED DETECTION RANGE per size class (target at SAME altitude as AWACS,"
       "\n   so horizon never gates -- isolates the range-class clamp)")
print(f"   {'class':8s} {'configured':>12s} {'measured':>12s} {'match?':>8s}")
for sc in ("fighter", "missile", "ship", "stealth"):
    cfg = AWACS_RADAR_RANGES[sc]
    meas = measure_flat_range(aw.radar, sc, target_alt=AWACS_ALT_M, step=500.0,
                              cap=AWACS_RADAR_RANGES["fighter"] + 50_000.0)
    ok = "YES" if abs(meas - cfg) <= 600.0 else "NO"
    print(f"   {sc:8s} {cfg/1000:9.1f} km {meas/1000:9.1f} km {ok:>8s}")

banner("3. HORIZON GATING vs target altitude (look-down vs sea-skimmer)\n"
       "   AWACS at 9.1 km. Theoretical 4/3-earth horizon (sim/radar.py).")
print(f"   {'tgt_alt':>9s} {'horizon_km':>11s} {'meas_fighter_km':>16s} "
      f"{'meas_missile_km':>16s}")
for talt in (0.0, 50.0, 500.0, 2_000.0, 9_100.0):
    hz = radar_horizon_m(aw.radar.antenna_alt, talt)
    mf = measure_flat_range(aw.radar, "fighter", talt, step=1000.0, cap=450_000.0)
    mm = measure_flat_range(aw.radar, "missile", talt, step=1000.0, cap=400_000.0)
    print(f"   {talt:7.0f} m {hz/1000:9.1f} km {mf/1000:13.1f} km "
          f"{mm/1000:13.1f} km")
print("   (note: terrain_blocks samples real terrain along the LOS; at sea the\n"
      "    surface is z<0 land / sea -- a low target far north may be over open\n"
      "    sea so the gate is horizon, not terrain.)")

banner("4. STEALTH (recon drone) detection: drone cruises at 18 km")
hz_drone = radar_horizon_m(aw.radar.antenna_alt, 18_000.0)
meas_drone = measure_flat_range(aw.radar, "stealth", 18_000.0, step=500.0, cap=80_000.0)
print(f"   stealth class configured range    : "
      f"{AWACS_RADAR_RANGES['stealth']/1000:.1f} km")
print(f"   horizon to an 18 km target        : {hz_drone/1000:.1f} km "
      f"(>> stealth range, so range-class is the limiter)")
print(f"   measured stealth detect range     : {meas_drone/1000:.1f} km")

banner("5. DATALINK CUE PATH in a REAL CombatWorld")
import pygame  # noqa
from world.combat import CombatWorld
from world.combat_config import CombatConfig

SEED = 7
world = CombatWorld(CombatConfig(seed=SEED))
print(f"   world built, seed={SEED}")
print(f"   world.awacs alive                 : {world.awacs.alive}")
print(f"   world.awacs radar ranges          : "
      f"{ {k: round(v/1000,1) for k,v in world.awacs.radar.ranges.items()} }")

# 5a. Is the AWACS radar in the commander's detector set?
detectors = world._enemy_sensor_radars()
awacs_in_detectors = any(r is world.awacs.radar for r in detectors)
print(f"   _enemy_sensor_radars() count      : {len(detectors)}")
print(f"   AWACS radar in detector set?      : {awacs_in_detectors}")

# 5b. Is the AWACS radar in the destroyer cue set?
cues = world._enemy_cue_radars()
awacs_in_cues = any(r is world.awacs.radar for r in cues)
print(f"   _enemy_cue_radars() count         : {len(cues)}")
print(f"   AWACS radar in destroyer cues?    : {awacs_in_cues}")

# 5c. AWACS-ONLY missile track feed. We kill every OTHER detector so only the
# AWACS can see, then place a player missile right under the AWACS at low alt
# (a fresh, young, low launch -> exactly what the back-plot pipeline wants).
banner("6. AWACS-ONLY missile detection -> EnemyPicture track + back-plot")

# Silence/kill all non-AWACS detectors so the cue is unambiguously the AWACS.
for s in world.ships:
    s.radar.emitting = False
for f in world._fighter_list:
    f.radar.emitting = False
# radar_station ESM (player emitter) - leave; it only drives emitter_intel.

detectors2 = world._enemy_sensor_radars()
live_emitting = [r.radar_id for r in detectors2 if r.alive and r.emitting]
print(f"   live+emitting detectors after silencing others: {live_emitting}")

# Craft a synthetic player missile object the feed loop will accept:
#   isinstance (Missile|SamMissile), alive, not hostile, no launch_platform.
from sim.missile import Missile

# Position it a bit north of the AWACS, low and fast climbing (back-plot eligible).
ax, ay, az = world.awacs.pos
mpos = np.array([ax + 5_000.0, 1_200.0, az - 30_000.0], dtype=np.float64)
mvel = np.array([0.0, 120.0, -300.0], dtype=np.float64)  # climbing + closing south

# Direct detector test (the gate the feed uses):
awacs_sees = world.awacs.radar.detects(mpos, "missile")
print(f"   AWACS.radar.detects(low climbing missile 'missile') : {awacs_sees}")
horizon_here = radar_horizon_m(world.awacs.radar.antenna_alt, float(mpos[1]))
slant = math.hypot(mpos[0]-ax, mpos[2]-az)
print(f"   ground range AWACS->missile        : {slant/1000:.1f} km")
print(f"   horizon AWACS->this missile        : {horizon_here/1000:.1f} km")

# Drive the real feed loop end to end. The feed gate is
# isinstance(m, (Missile, SamMissile)) AND not is_hostile AND launch_platform
# is None. Build a Missile WITHOUT running its heavy ctor (object.__new__) so it
# passes isinstance but carries exactly the geometry we want to test the cue.
made_real = True
try:
    m = object.__new__(Missile)        # real type, no flight-model init
    m.pos = mpos.copy()
    m.vel = mvel.copy()
    m.alive = True
    m.is_hostile = False
    m.launch_platform = None
except Exception as e:
    print(f"   (could not synthesize Missile: {e})")
    made_real = False

if made_real:
    world.missiles.append(m)
    pic = world.commander.picture
    before = dict(pic.missile_tracks)
    # Run a few feed cycles advancing sim_time past the feed cadence.
    for i in range(6):
        world.sim_time += 0.25
        world._feed_enemy_picture(0.25, world.sim_time)
    after = pic.missile_tracks
    new_tracks = [k for k in after if k not in before]
    print(f"   missile_tracks before feed         : {len(before)}")
    print(f"   missile_tracks after AWACS-only feed: {len(after)}")
    print(f"   NEW track ids                      : {new_tracks}")
    print(f"   back-plot fixes recorded           : {len(pic._back_plots)}")
    print(f"   launch clusters formed             : {len(pic.clusters)}")
    if pic._back_plots:
        bp = pic._back_plots[0]
        print(f"   first back-plot est XZ             : "
              f"x={bp.estimated_pos[0]:.0f} z={bp.estimated_pos[1]:.0f} "
              f"err={bp.error_m:.0f} m")

banner("7. AWACS-ONLY drone track feed")
drone = world.drone
if drone is not None:
    # Park the drone within AWACS stealth range, in the open, and re-run feed.
    drone._alive = True if hasattr(drone, "_alive") else None
    print(f"   drone present, alive={drone.alive}, "
          f"pos=({drone.pos[0]:.0f},{drone.pos[1]:.0f},{drone.pos[2]:.0f})")
    # Move drone to 20 km from AWACS at its cruise alt (inside 40 km stealth).
    drone.pos[0] = ax + 10_000.0
    drone.pos[1] = 18_000.0
    drone.pos[2] = az - 18_000.0
    sees_drone = world.awacs.radar.detects(drone.pos, drone.radar_size)
    d_ground = math.hypot(drone.pos[0]-ax, drone.pos[2]-az)
    print(f"   drone moved to {d_ground/1000:.1f} km from AWACS "
          f"(stealth range {AWACS_RADAR_RANGES['stealth']/1000:.0f} km)")
    print(f"   AWACS.radar.detects(drone,'stealth'): {sees_drone}")
    pic = world.commander.picture
    pic.drone_tracks.clear()
    world.sim_time += 0.25
    world._feed_enemy_picture(0.25, world.sim_time)
    dtracks = pic.live_drone_tracks(world.sim_time)
    print(f"   picture drone_tracks after feed    : {len(dtracks)} -> "
          f"{[t['id'] for t in dtracks]}")
else:
    print("   no drone in world")

banner("8. DETERMINISM — same seed twice")
w1 = CombatWorld(CombatConfig(seed=11))
w2 = CombatWorld(CombatConfig(seed=11))
same_pos = np.allclose(w1.awacs.pos, w2.awacs.pos)
same_rng = w1.awacs.radar.ranges == w2.awacs.radar.ranges
print(f"   AWACS spawn pos identical          : {same_pos} "
      f"({w1.awacs.pos.tolist()})")
print(f"   AWACS radar ranges identical       : {same_rng}")

print("\nDONE.")
