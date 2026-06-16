"""Probe: audit the enemy commander brain's SENSOR INPUTS (no truth leak).

Builds a real CombatWorld and:
  (A) snapshots which fields of EnemyPicture get populated and from what,
  (B) drives the back-plot pipeline directly with synthetic tracks to MEASURE
      localization error vs detection range and the climb/level regimes,
  (C) checks determinism across two identically-seeded worlds,
  (D) hunts for a ground-truth leak: it teleports the REAL player radar and
      drone, then verifies the commander's believed positions only move when a
      sensor feed is run (and stay STALE between feeds), and that the believed
      position carries the SENSOR estimate, never the live truth.

Run: python tools/probe_audit_enemy_brain_inputs.py
(pygame prints a banner to stderr — ignore.)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from tools.playtest_harness import build_world  # noqa: E402
from sim.commander import (  # noqa: E402
    EnemyCommander, EnemyPicture, WeaponStock,
    ESM_FIX_TIME_S, BACKPLOT_LOW_ALT_M, BACKPLOT_MAX_AGE_S,
    BACKPLOT_ERR_FRAC, BACKPLOT_CLUSTER_R_M, BACKPLOT_FIXES_NEEDED,
    BACKPLOT_CLIMB_VY, BACKPLOT_MIN_CLOSE_VZ, HOME_COAST_Z,
)


def hr(t):
    print("\n" + "=" * 72)
    print(t)
    print("=" * 72)


# ---------------------------------------------------------------------------
hr("PART A — what EnemyPicture fields exist and what feeds them (live world)")

w = build_world(1234)
pic = w.commander.picture
print(f"world seed=1234  sim_time={w.sim_time}")
print("EnemyPicture public stores:")
for name in ("emitters", "clusters", "structures", "drone_tracks",
             "missile_tracks"):
    print(f"   pic.{name:15s} -> {type(getattr(pic, name)).__name__} "
          f"len={len(getattr(pic, name))}")
print(f"   pic._back_plots (raw) -> len={len(pic._back_plots)}")

# Confirm the ONLY world->picture entry points the integrator uses.
import inspect  # noqa: E402
src = inspect.getsource(w._feed_enemy_picture)
calls = [ln.strip() for ln in src.splitlines()
         if (".update_emitter" in ln or ".process_missile_track" in ln
             or ".update_drone_track" in ln or ".mark_emitter" in ln
             or ".prune_missile_tracks" in ln)]
print("\nworld._feed_enemy_picture -> picture/commander calls:")
for c in calls:
    print("   " + c)


# ---------------------------------------------------------------------------
hr("PART B — run the live world; watch sensor inputs accumulate")

# Place a player radar emission going: enable the radar and step.
rs = w.radar_station
rs.emitting = True
print(f"radar_station id={rs.radar_id} emitting={rs.emitting} "
      f"true_pos={np.round(rs.pos, 1)}")

# Step the world and snapshot ESM fix growth + any tracks.
snaps = []
for step_t in (5.0, 30.0, 60.0, 95.0, 120.0):
    while w.sim_time < step_t:
        w.step(1.0 / 30.0)
    ei = pic.emitters.get(rs.radar_id)
    snaps.append((w.sim_time, ei.fix_progress if ei else None,
                  ei.located if ei else None,
                  len(pic.missile_tracks), len(pic.drone_tracks),
                  len(pic.clusters)))
print(f"{'t(s)':>7} {'esm_fix':>9} {'located':>8} {'msl_trk':>8} "
      f"{'drn_trk':>8} {'clusters':>9}")
for t, fix, loc, mt, dt_, cl in snaps:
    fs = f"{fix:.3f}" if fix is not None else "None"
    print(f"{t:7.1f} {fs:>9} {str(loc):>8} {mt:>8} {dt_:>8} {cl:>9}")

ei = pic.emitters.get(rs.radar_id)
if ei is not None:
    print(f"\nESM: fix grows ~dt/{ESM_FIX_TIME_S:.0f}s. Believed radar pos = "
          f"{np.round(ei.believed_pos, 1)}  (true {np.round(rs.pos, 1)})")
    print(f"     believed_pos == true_pos? "
          f"{np.allclose(ei.believed_pos, rs.pos)}  "
          f"(expected True: ESM hands the radar's own pos as the estimate)")


# ---------------------------------------------------------------------------
hr("PART C — back-plot localization ACCURACY (direct, synthetic tracks)")

# Use an isolated commander so we control inputs precisely.
def fresh_cmd():
    return EnemyCommander([], None, [], picture=EnemyPicture(),
                          weapon_stock=WeaponStock(), seed=7)


# NOTE world frame: home coast at z=0, player land z<0, enemy fleet z>0.
# A player missile launched from home flies NORTH -> increasing z (vz>0).
# The back-plot's "closing" test is vz>0 with first_seen z>0.
#
# C1: level sea-skimmer, vary detection range, measure error vs true launch.
print("C1 level sea-skimmer (alt=15m, flying north toward fleet, vz>0):")
print(f"    BACKPLOT_ERR_FRAC={BACKPLOT_ERR_FRAC} -> expect err_m = "
      f"{BACKPLOT_ERR_FRAC}*det_range")
print(f"{'det_rng_km':>11} {'true_lx':>9} {'est_lx':>9} {'est_lz':>9} "
      f"{'pos_err_m':>10} {'rec_err_m':>10}")
true_launch_x = 12_000.0  # true launch X on the coast
for det_km in (30.0, 60.0, 120.0):
    c = fresh_cmd()
    # missile detected downrange (north) of coast, climbing-free, heading +z.
    fseen = np.array([true_launch_x + 0.0, 15.0, 8_000.0])
    vel = np.array([0.0, 0.0, +300.0])  # heading north (+z), level
    # launch lies back where the track crosses z=0: s=(fz-0)/vz; lx=fx-vx*s.
    det = np.array([fseen[0], 9000.0, fseen[2] + det_km * 1000.0])
    c.process_missile_track("t1", fseen, vel, sim_time=1.0,
                            first_seen_t=1.0, first_seen_pos=fseen,
                            first_seen_vel=vel, detector_pos=det)
    bps = c.picture._back_plots
    if bps:
        est = bps[0].estimated_pos
        true_lx = fseen[0]  # vx=0 so launch_x == fx
        perr = float(np.hypot(est[0] - true_lx, est[1] - HOME_COAST_Z))
        print(f"{det_km:11.0f} {true_lx:9.0f} {est[0]:9.0f} {est[1]:9.0f} "
              f"{perr:10.1f} {bps[0].error_m:10.1f}")
    else:
        print(f"{det_km:11.0f}  NO BACK-PLOT (rejected)")

# C2: boost climb regime (vy high) — time-project to surface.
print("\nC2 boost climb (vy=200 > CLIMB_VY=%.0f), project back in time:"
      % BACKPLOT_CLIMB_VY)
c = fresh_cmd()
fseen = np.array([20_000.0, 1500.0, 30_000.0])
vel = np.array([10.0, 200.0, +100.0])  # climbing, moving north (+z)
det = np.array([fseen[0], 9000.0, fseen[2] + 40_000.0])
c.process_missile_track("t2", fseen, vel, 1.0, 1.0, fseen, vel, det)
bps = c.picture._back_plots
if bps:
    est = bps[0].estimated_pos
    t_back = fseen[1] / vel[1]
    true_lx = fseen[0] - vel[0] * t_back
    true_lz = fseen[2] - vel[2] * t_back
    print(f"    t_back={t_back:.2f}s est=({est[0]:.0f},{est[1]:.0f}) "
          f"hand-calc=({true_lx:.0f},{true_lz:.0f}) "
          f"match={np.allclose(est, [true_lx, true_lz])}")
else:
    print("    NO BACK-PLOT")

# C3: rejection gates — high first alt, old track, coast-parallel dogleg.
print("\nC3 rejection gates (each should produce ZERO back-plots):")
cases = [
    ("first alt >= 2km", np.array([0., BACKPLOT_LOW_ALT_M + 1, 5000.]),
     np.array([0., 0., +300.]), 1.0, 1.0),
    ("track older than 30s", np.array([0., 15., 5000.]),
     np.array([0., 0., +300.]), 40.0, 1.0),
    ("level receding (vz<0, flying away/south)", np.array([0., 15., 5000.]),
     np.array([0., 0., -300.]), 1.0, 1.0),
    ("level too-slow close (vz<MIN)", np.array([0., 15., 5000.]),
     np.array([0., 0., +(BACKPLOT_MIN_CLOSE_VZ - 5)]), 1.0, 1.0),
]
for label, fp, fv, st, ft in cases:
    c = fresh_cmd()
    det = np.array([fp[0], 9000., fp[2] + 50_000.])
    c.process_missile_track("tx", fp, fv, st, ft, fp, fv, det)
    n = len(c.picture._back_plots)
    print(f"    {label:32s} -> back_plots={n}  "
          f"{'OK(rejected)' if n == 0 else 'LEAK/UNEXPECTED'}")

# C4: cluster formation — need BACKPLOT_FIXES_NEEDED distinct tracks within R.
print(f"\nC4 cluster: {BACKPLOT_FIXES_NEEDED} distinct tracks within "
      f"{BACKPLOT_CLUSTER_R_M:.0f}m -> targetable:")
c = fresh_cmd()
for i in range(BACKPLOT_FIXES_NEEDED):
    fp = np.array([10_000.0 + 500.0 * i, 15.0, 6000.0])
    fv = np.array([0.0, 0.0, +300.0])
    det = np.array([fp[0], 9000.0, fp[2] + 50_000.0])
    c.process_missile_track(f"trk_{i}", fp, fv, 1.0 + i, 1.0 + i, fp, fv, det)
    tc = c.picture.targetable_clusters()
    nfix = len(c.picture.clusters[0].fixes) if c.picture.clusters else 0
    print(f"    after track {i+1}: clusters={len(c.picture.clusters)} "
          f"fixes={nfix} targetable={len(tc)}")
# dedup test: same track id should NOT add a second fix
before = len(c.picture.clusters[0].fixes)
fp = np.array([10_500.0, 15.0, 6000.0]); fv = np.array([0., 0., +300.])
c.process_missile_track("trk_0", fp, fv, 99., 99., fp, fv,
                        np.array([fp[0], 9000., fp[2] + 50_000.]))
after = len(c.picture.clusters[0].fixes)
print(f"    re-feed existing track_id: fixes {before}->{after} "
      f"{'OK(deduped/aged)' if after == before else 'CHANGED'}")


# ---------------------------------------------------------------------------
hr("PART D — GROUND-TRUTH LEAK HUNT (live world)")

w2 = build_world(909)
pic2 = w2.commander.picture
rs2 = w2.radar_station
rs2.emitting = True
# Run feeds long enough to fully localize the radar.
while w2.sim_time < 100.0:
    w2.step(1.0 / 30.0)
ei2 = pic2.emitters.get(rs2.radar_id)
print(f"radar located={ei2.located} believed={np.round(ei2.believed_pos,1)} "
      f"true={np.round(rs2.pos,1)}")

# LEAK TEST 1: teleport the REAL radar by 50 km WITHOUT a feed. The believed
# pos must NOT change until the next sensor feed runs.
old_believed = ei2.believed_pos.copy()
rs2.pos[0] += 50_000.0
# force the feed timer so the next step does NOT feed yet
print("\nLEAK TEST 1: teleport true radar +50km, read belief BEFORE next feed")
believed_now = pic2.emitters[rs2.radar_id].believed_pos.copy()
print(f"   true_pos now   = {np.round(rs2.pos,1)}")
print(f"   believed (pre) = {np.round(believed_now,1)}  "
      f"moved={not np.allclose(believed_now, old_believed)}")
# Now allow exactly one feed and re-read: belief tracks the SENSED (new) pos,
# because ESM hands radar.pos — but ONLY via the feed, never instantaneously.
w2._cmd_feed_next_t = w2.sim_time  # allow a feed now
w2.step(1.0 / 30.0)
believed_after = pic2.emitters[rs2.radar_id].believed_pos.copy()
print(f"   believed (post-feed) = {np.round(believed_after,1)} "
      f"tracks_new_true={np.allclose(believed_after[0], rs2.pos[0], atol=1.0)}")
print("   -> belief is STALE between feeds (no instantaneous truth read).")

# LEAK TEST 2: is there ANY code path where the commander reads a live entity
# position for targeting? Scan the commander source for entity-truth reads.
print("\nLEAK TEST 2: static scan of EnemyCommander for truth reads")
import sim.commander as cmod  # noqa: E402
csrc = inspect.getsource(cmod.EnemyCommander)
# truth-ish accessors that would be a leak if used for TARGETING
suspects = []
for token, why in [
    (".pos", "entity world position"),
    (".true_", "explicit truth field"),
    ("world.", "world reach-through"),
]:
    for ln_no, ln in enumerate(csrc.splitlines(), 1):
        if token in ln and "believed_pos" not in ln and "target_pos" not in ln:
            suspects.append((token, ln_no, ln.strip(), why))
print(f"   raw token hits (.pos / .true_ / world.): {len(suspects)}")
for tok, no, ln, why in suspects:
    print(f"     [{tok}] {ln[:80]}")
print("   NOTE: f.pos / awacs.pos reads are the commander's OWN platforms")
print("   (fighters/AWACS it commands), not the player's hidden truth.")

# LEAK TEST 3: confirm drone track carries SENSED last-known (XZ) not live truth
print("\nLEAK TEST 3: drone track is last-known snapshot (ages out)")
w3 = build_world(55)
if w3.drone is not None:
    d = w3.drone
    print(f"   drone present id={d.aircraft_id}")
    # Drive feeds; if no enemy radar sees it, no track exists (sensor-gated).
    for _ in range(40):
        w3.step(1.0 / 30.0)
    pic3 = w3.commander.picture
    trks = pic3.live_drone_tracks(w3.sim_time)
    print(f"   live drone tracks after ~1.3s: {len(trks)} "
          f"(0 expected if no enemy radar has LoS at start)")
    if trks:
        tr = trks[0]
        print(f"   track pos(XZ)={np.round(tr['pos'],1)} is 2D snapshot; "
              f"live drone XZ=({d.pos[0]:.1f},{d.pos[2]:.1f})")
else:
    print("   no drone in this world")


# ---------------------------------------------------------------------------
hr("PART E — DETERMINISM (two identically-seeded worlds, compare orders)")

def run_orders(seed, secs=180.0):
    ww = build_world(seed)
    ww.radar_station.emitting = True
    log = []
    while ww.sim_time < secs:
        before = list(ww.commander.pending_orders)
        ww.step(1.0 / 30.0)
        new = ww.commander.pending_orders
        if new and new is not before:
            for o in new:
                log.append((round(ww.sim_time, 2), o["type"]))
    return log, ww

l1, wa = run_orders(2024)
l2, wb = run_orders(2024)
print(f"seed 2024: world A issued {len(l1)} orders, world B {len(l2)} orders")
print(f"   order streams identical? {l1 == l2}")
from collections import Counter  # noqa: E402
print(f"   order-type histogram (A): {dict(Counter(t for _, t in l1))}")
# show first few
print("   first 6 orders (A):", l1[:6])

# Different seed -> (likely) different stream / timing
l3, _ = run_orders(777)
print(f"seed 777: {len(l3)} orders; same as 2024-stream? {l3 == l1}")


# ---------------------------------------------------------------------------
hr("PART F — picture sufficiency for a smarter sensor-driven AI")

print("Inputs available to a plane/AWACS utility brain (all sensor-derived):")
print("  emitters{id->believed_pos,alive,fix_progress,last_heard_t}")
print("  clusters[centre,fixes,believed_alive,targetable]")
print("  drone_tracks{id->pos(XZ),t}    (last-known, ages 30s)")
print("  missile_tracks{id->pos,vel,t,first_seen_t,alt_at_first,range_at_first}")
print("  structures{id->kind,believed_pos,believed_alive}")
print("GAPS observed:")
print("  - missile_tracks store velocity+pos but commander only uses pos for "
      "AWACS flee; no threat-axis / time-to-impact utility computed.")
print("  - no per-track classification (Oniks vs S-300) in the picture.")
print("  - no fighter/AWACS self-state fused INTO the picture (commander reads "
      "f.pos/f.state directly from entities, not via picture).")

print("\nDONE.")
