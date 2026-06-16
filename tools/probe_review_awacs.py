"""Game-test probe (review loop): AWACS EMCON silent window.

Contract (b): when a player missile TRACK is within the commander's flee range
of the AWACS, awacs.radar.emitting goes False (silent window opens) within the
flee dwell; it re-emits when the threat clears; and it does NOT get stuck silent
over a long run.

We aim a HIGH player Oniks straight at the AWACS so a track forms and closes
inside AWACS_FLEE_RANGE_M (100 km), watch emitting flip False, let the missile
fly past / die, and confirm emitting returns True. We also run a LONG no-threat
control to prove the AWACS does not silence itself spuriously and never gets
stuck silent.

No-cheat note: the trigger is picture.live_missile_tracks (sensor-derived), and
the AWACS only flees when a TRACK exists — verified separately in the cheat probe.

Run: python tools/probe_review_awacs.py   (ignore the pygame banner on stderr)
"""
from __future__ import annotations

import math
import numpy as np

from world.combat import CombatWorld
from world.combat_config import CombatConfig
from sim.commander import AWACS_FLEE_RANGE_M
from sim.arsenal import ONIKS
from sim.missile import Missile

DT = 0.10


def _spawn_oniks_at(world, aim_xyz, standoff_m, bearing_deg, profile="hi-lo"):
    """Player Oniks launched standoff_m from the aim point on the given
    compass bearing (deg, 0=+z/north, 90=+x/east), flying back toward it.

    bearing_deg selects WHERE the launch point sits relative to the AWACS so
    the run-in line can be chosen to avoid the destroyer screen (the screen
    sits east/south of the AWACS; a launch to the WEST gives the round a clear
    approach so the EMCON trigger is actually exercised)."""
    ax, az = float(aim_xyz[0]), float(aim_xyz[2])
    br = math.radians(bearing_deg)
    ux = ax + math.sin(br) * standoff_m
    uz = az + math.cos(br) * standoff_m
    heading = math.degrees(math.atan2(ax - ux, az - uz))
    pos = np.array([ux, 12.0, uz], dtype=np.float64)
    target_point = np.array([ax, 0.0, az], dtype=np.float64)
    m = Missile(ONIKS, pos, heading, profile, target_point)
    world.missiles.append(m)
    return m


def run_threat(seed):
    """Fire an Oniks at the AWACS; record the emitting trace + track range."""
    world = CombatWorld(CombatConfig(seed=seed))
    awacs = world.awacs
    aim = awacs.pos.copy()
    # 150 km standoff WEST of the AWACS (bearing 270): a clear run-in that
    # skirts the destroyer screen (east/south of the AWACS) so the track
    # forms outside flee range then actually closes inside it.
    oniks = _spawn_oniks_at(world, aim, 150_000.0, bearing_deg=270.0)

    trace = []          # (t, emitting, track_dist_to_awacs_or_None)
    t = 0.0
    silent_opened = False
    silent_open_t = None
    reemit_t = None
    strobe_flips = 0
    last_emit = awacs.radar.emitting
    max_silent_run = 0.0
    cur_silent_run = 0.0
    while t < 300.0:
        world.step(DT)
        t += DT
        em = awacs.radar.emitting
        # nearest player missile track distance to the AWACS (sensor picture)
        tracks = world.commander.picture.live_missile_tracks(world.sim_time)
        td = None
        for mt in tracks:
            d = math.hypot(float(mt["pos"][0]) - float(awacs.pos[0]),
                           float(mt["pos"][2]) - float(awacs.pos[2]))
            td = d if td is None else min(td, d)
        if em != last_emit:
            strobe_flips += 1
            last_emit = em
        if not em:
            cur_silent_run += DT
            max_silent_run = max(max_silent_run, cur_silent_run)
            if not silent_opened:
                silent_opened = True
                silent_open_t = t
        else:
            cur_silent_run = 0.0
            if silent_opened and reemit_t is None:
                reemit_t = t
        trace.append((t, em, td))
    end_emit = awacs.radar.emitting
    return dict(silent_opened=silent_opened, silent_open_t=silent_open_t,
                reemit_t=reemit_t, end_emit=end_emit, strobe_flips=strobe_flips,
                max_silent_run=max_silent_run, awacs_alive=awacs.alive,
                t_end=t)


def run_control(seed, dur=420.0):
    """No player missile at all — AWACS should stay emitting the whole time."""
    world = CombatWorld(CombatConfig(seed=seed))
    awacs = world.awacs
    t = 0.0
    silent_steps = 0
    n = 0
    while t < dur:
        world.step(DT)
        t += DT
        n += 1
        if awacs.alive and not awacs.radar.emitting:
            silent_steps += 1
    return dict(silent_steps=silent_steps, n=n, end_emit=awacs.radar.emitting,
                awacs_alive=awacs.alive)


def main():
    print("=== AWACS EMCON PROBE ===")
    print(f"AWACS_FLEE_RANGE_M={AWACS_FLEE_RANGE_M/1000:.0f} km")
    print()
    seeds = [1, 2, 3]
    print("THREAT (Oniks aimed at AWACS, 150 km standoff):")
    n_open = n_reemit = 0
    worst_silent = 0.0
    for s in seeds:
        r = run_threat(s)
        n_open += int(r["silent_opened"])
        n_reemit += int(r["reemit_t"] is not None or r["end_emit"])
        worst_silent = max(worst_silent, r["max_silent_run"])
        ot = f"{r['silent_open_t']:.1f}s" if r["silent_open_t"] else "never"
        rt = f"{r['reemit_t']:.1f}s" if r["reemit_t"] else "n/a"
        print(f"  seed {s}: silent_opened={r['silent_opened']} at {ot:>7} "
              f"reemit={rt:>7} end_emit={r['end_emit']} "
              f"flips={r['strobe_flips']} max_silent_run={r['max_silent_run']:.1f}s "
              f"alive={r['awacs_alive']}")
    print(f"  -> opened silent window {n_open}/{len(seeds)}, "
          f"recovered emit {n_reemit}/{len(seeds)}, "
          f"worst continuous silent run {worst_silent:.1f}s")
    print()

    print("CONTROL (no player missile, 420 s):")
    n_clean = 0
    for s in seeds:
        r = run_control(s)
        clean = r["silent_steps"] == 0 and r["end_emit"]
        n_clean += int(clean)
        print(f"  seed {s}: silent_steps={r['silent_steps']}/{r['n']} "
              f"end_emit={r['end_emit']} (clean={clean})")
    print(f"  -> stayed emitting cleanly {n_clean}/{len(seeds)}")
    print()

    pass_b_open = n_open == len(seeds)
    pass_b_recover = n_reemit == len(seeds)
    pass_b_nostick = n_clean == len(seeds) and worst_silent < 200.0
    print(f"PASS(b-silences)={pass_b_open}  PASS(b-recovers)={pass_b_recover}  "
          f"PASS(b-no-stuck-silent)={pass_b_nostick}")


if __name__ == "__main__":
    main()
