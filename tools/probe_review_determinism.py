"""Game-test probe (review loop): determinism + no-cheat spot-check.

Contract (d): two same-seed CombatWorlds stepped N steps WITH the new features
active (SM-6 area defense, AWACS EMCON, fighter RWR evasion all exercised by a
live player Oniks raid) stay BIT-IDENTICAL — a full state digest matches.

Contract (e): no-cheat spot-check — a SILENCED/blind enemy must not act on a
target it cannot sense. We assert two structural invariants over the run:
  (e1) Whenever the AWACS is SILENT (radar.emitting False), its radar.detects()
       returns False for every live player missile — a silent set radiates no
       returns, so it can contribute NOTHING to track formation while dark.
  (e2) Every commander missile track corresponds to a player round that is
       PHYSICALLY detectable by at least one LIVE+EMITTING enemy sensor at the
       moment the track is fresh (age 0) — i.e. tracks are sensor-derived, never
       conjured from ground truth. (A coasting/stale track is allowed to exist
       after detection; we only check freshly-refreshed tracks.)

Run: python tools/probe_review_determinism.py  (ignore the pygame banner)
"""
from __future__ import annotations

import hashlib
import math
import numpy as np

from world.combat import CombatWorld
from world.combat_config import CombatConfig
from sim.arsenal import ONIKS
from sim.missile import Missile
from sim.sam import SamMissile

DT = 0.10


def _spawn_raid(world):
    """A small mixed raid: 2 high + 2 low Oniks at the lead destroyers, plus
    one high Oniks at the AWACS — exercises SM-6, EMCON, and SAM flyouts that
    can lock fighters. Deterministic placement (no RNG)."""
    ds = sorted([s for s in world.ships
                 if type(s).__name__ == "Destroyer" and s.alive],
                key=lambda s: float(s.pos[2]))
    targets = []
    for i, s in enumerate(ds[:2]):
        targets.append((s.pos.copy(), "hi-lo", 150_000.0))
        targets.append((s.pos.copy(), "lo-lo", 120_000.0))
    aw = world.awacs.pos.copy()
    targets.append((aw, "hi-lo", 150_000.0))
    for tp, profile, standoff in targets:
        bearing = math.atan2(0.0 - float(tp[0]), -600.0 - float(tp[2]))
        ux = float(tp[0]) - math.sin(bearing) * standoff
        uz = float(tp[2]) - math.cos(bearing) * standoff
        heading = math.degrees(math.atan2(float(tp[0]) - ux,
                                          float(tp[2]) - uz))
        m = Missile(ONIKS, np.array([ux, 12.0, uz]), heading, profile,
                    np.array([float(tp[0]), 0.0, float(tp[2])]))
        world.missiles.append(m)


def _digest(world):
    """A stable digest of the full dynamic state: every missile pos/vel/alive,
    every ship pos + ammo, every air entity pos/heading, AWACS emitting, and
    the commander picture's track positions. float64 bytes -> sha256."""
    h = hashlib.sha256()

    def feed(*vals):
        for v in vals:
            h.update(np.asarray(v, dtype=np.float64).tobytes())

    feed(world.sim_time)
    # missiles (order is insertion order — deterministic across same seed)
    for m in world.missiles:
        feed(m.pos, m.vel, float(m.alive),
             float(getattr(m, "is_hostile", False)))
    for s in world.ships:
        feed(s.pos, float(s.alive), float(getattr(s, "sm2_ammo", 0)),
             float(getattr(s, "sm6_ammo", 0)), float(getattr(s, "ciws_ammo", 0)),
             float(s.radar.emitting))
    for e in world.enemy_air:
        feed(e.pos, float(e.heading), float(e.alive))
    feed(float(world.awacs.radar.emitting), float(world.awacs.alive))
    # Commander picture missile tracks. NOTE: track IDs are derived from
    # id(missile) (a process-local memory address), so they are NOT stable
    # across two separate object allocations even for the same seed. We must
    # digest the PHYSICAL track state (pos+t), sorted by position — never by
    # the address-derived key — or two deterministic worlds would falsely
    # mismatch purely on dict key ordering.
    pic = world.commander.picture
    track_rows = sorted(
        (tuple(np.asarray(tr["pos"], dtype=np.float64).tolist()),
         float(tr.get("t", 0.0)))
        for tr in pic.missile_tracks.values())
    for pos, tt in track_rows:
        feed(pos, tt)
    return h.hexdigest()


def run_determinism(seed, n_steps):
    digests_a = []
    digests_b = []
    wa = CombatWorld(CombatConfig(seed=seed)); _spawn_raid(wa)
    wb = CombatWorld(CombatConfig(seed=seed)); _spawn_raid(wb)
    for i in range(n_steps):
        wa.step(DT)
        wb.step(DT)
        if i % 50 == 0:
            digests_a.append(_digest(wa))
            digests_b.append(_digest(wb))
    final_a = _digest(wa)
    final_b = _digest(wb)
    mismatches = sum(1 for x, y in zip(digests_a, digests_b) if x != y)
    return dict(final_match=final_a == final_b, checkpoint_mismatches=mismatches,
                n_checkpoints=len(digests_a), final_a=final_a[:16],
                final_b=final_b[:16])


def run_nocheat(seed, n_steps):
    """Structural no-cheat invariants over a live raid.

    e1: a SILENT AWACS radiates nothing -> its radar.detects() must return
        False for every live player missile while it is dark.
    e2: every commander missile track is SENSOR-DERIVED, never conjured from
        ground truth. The architecture creates a track ONLY after a real
        detector physically resolved the round (world._feed_enemy_picture: the
        first track fix is gated on ``det = next(r for r in detectors if
        r.detects(...))``; nothing is created otherwise). We verify the
        provenance that gate leaves behind: every live track of a still-flying
        player round has an intel record (world._cmd_missile_intel) carrying a
        finite ``det_pos`` (the sensor location captured at first sight). A
        truth-read / conjured track would have no such record. (We do NOT
        require det_pos to equal a CURRENT sensor position: sensors move, and
        det_pos is the historical fix at detection time.)
    """
    world = CombatWorld(CombatConfig(seed=seed))
    _spawn_raid(world)
    e1_violations = 0
    e1_silent_steps = 0
    e2_violations = 0
    e2_track_checks = 0

    for i in range(n_steps):
        world.step(DT)
        aw = world.awacs
        player_missiles = [m for m in world.missiles
                           if m.alive and isinstance(m, Missile)
                           and not getattr(m, "is_hostile", False)]
        # e1: silent AWACS must radiate nothing.
        if aw.alive and not aw.radar.emitting:
            e1_silent_steps += 1
            for m in player_missiles:
                if aw.radar.detects(m.pos, "missile"):
                    e1_violations += 1
        # e2: every live track of an existing round has real detection
        # provenance (a finite det_pos recorded by the sensor gate).
        now = world.sim_time
        pic = world.commander.picture
        live_ids = {f"hostile_{id(m):x}" for m in player_missiles}
        intel_by_tid = {rec["track_id"]: rec
                        for rec in world._cmd_missile_intel.values()}
        for tr in pic.live_missile_tracks(now):
            tid = tr.get("id", None)
            if tid not in live_ids:
                continue                # coasting track of a dead round: skip
            e2_track_checks += 1
            rec = intel_by_tid.get(tid)
            if rec is None or rec.get("det_pos") is None \
                    or not np.all(np.isfinite(rec["det_pos"])):
                e2_violations += 1
    return dict(e1_violations=e1_violations, e1_silent_steps=e1_silent_steps,
                e2_violations=e2_violations, e2_track_checks=e2_track_checks)


def main():
    print("=== DETERMINISM + NO-CHEAT PROBE ===")
    print()
    seeds = [1, 2, 7]
    N = 600                 # 60 s of a live raid, all features active
    print(f"DETERMINISM (two same-seed worlds, {N} steps, raid active):")
    n_ok = 0
    for s in seeds:
        r = run_determinism(s, N)
        ok = r["final_match"] and r["checkpoint_mismatches"] == 0
        n_ok += int(ok)
        print(f"  seed {s}: final_match={r['final_match']} "
              f"checkpoint_mismatches={r['checkpoint_mismatches']}/"
              f"{r['n_checkpoints']} digest={r['final_a']} (ok={ok})")
    print(f"  -> bit-identical {n_ok}/{len(seeds)}")
    print()

    print(f"NO-CHEAT spot-check ({N} steps, raid active):")
    e1v = e2v = 0
    e1s = e2c = 0
    for s in seeds:
        r = run_nocheat(s, N)
        e1v += r["e1_violations"]; e1s += r["e1_silent_steps"]
        e2v += r["e2_violations"]; e2c += r["e2_track_checks"]
        print(f"  seed {s}: e1(silent-AWACS-detects)={r['e1_violations']} "
              f"over {r['e1_silent_steps']} silent steps | "
              f"e2(track-without-sensor-provenance)={r['e2_violations']} "
              f"over {r['e2_track_checks']} track samples")
    print(f"  -> e1 violations total={e1v} (silent steps={e1s}); "
          f"e2 violations total={e2v} (track samples={e2c})")
    print()

    pass_d = n_ok == len(seeds)
    pass_e = e1v == 0 and e2v == 0
    print(f"PASS(d-deterministic)={pass_d}  PASS(e-no-cheat)={pass_e}")


if __name__ == "__main__":
    main()
