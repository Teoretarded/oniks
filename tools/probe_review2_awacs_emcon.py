"""REVIEW 2 / check (b): AWACS EMCON dwell — anti-strobe.

The old bug: a silenced AWACS that is the SOLE sensor on a threat loses its own
(now-dark) track when it ages out (~30 s), un-blinds itself, re-detects the still
inbound missile, and re-silences — a radiating BLINK every ~31 s at the worst
moment. The fix adds AWACS_EMCON_DWELL_S: hold silent for the dwell after the
threat was LAST SEEN, re-emit only after.

Measured here, three scenarios driving the commander's _defend_awacs directly
against a synthetic picture (deterministic, no battle noise):

  B1 persistent sole-sensor threat: a missile parked inside the flee range that
     the AWACS can only see while emitting. Count emit<->silent transitions over
     a long run. The OLD code strobes ~every 31 s; the fix must NOT.

  B2 genuine threat -> silences: confirm it goes silent (emitting False) when a
     real tracked missile is inside AWACS_FLEE_RANGE_M.

  B3 recovers when clear: once the threat is gone for the full dwell, it re-emits.

Run: python tools/probe_review2_awacs_emcon.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from world.combat import CombatWorld
from world.combat_config import CombatConfig
from sim.commander import AWACS_EMCON_DWELL_S, AWACS_FLEE_RANGE_M

CMD_DT = 1.0      # commander ticks at 1 Hz; we drive _defend_awacs at 1 s steps


def _drive(world, threat_fn, total_s):
    """Drive ONLY the AWACS-EMCON loop for total_s seconds at 1 Hz.

    threat_fn(t) -> a missile pos (3,) inside flee range, or None.

    Critically models the SOLE-SENSOR coupling that caused the old strobe:
    the picture only HOLDS the track while the AWACS radar is emitting. So we
    inject/refresh the track each second ONLY if the threat is present AND the
    AWACS is currently emitting; otherwise the track ages out of the 30 s window
    and disappears — exactly the dark-track condition the dwell must ride out.

    Returns (transitions, emit_timeline) where emit_timeline[t] = bool emitting.
    """
    cmd = world.commander
    awacs = world.awacs
    emit_timeline = []
    transitions = 0
    prev_emit = awacs.radar.emitting
    t = 0.0
    while t < total_s:
        threat = threat_fn(t)
        # Sole-sensor coupling: refresh the track only if a threat exists and the
        # AWACS is currently radiating (it is the only thing that can see it).
        if threat is not None and awacs.radar.emitting:
            cmd.picture.update_missile_track(
                "hostile_probe", np.asarray(threat, dtype=np.float64),
                np.array([0.0, 0.0, 0.0]), t)
        # Age out stale tracks beyond the 30 s window (mimic prune).
        cmd.picture.prune_missile_tracks(set(), t)
        # Run the EMCON decision + apply the resulting orders (flee toggles emit).
        cmd.pending_orders = []
        cmd._defend_awacs(t)
        for order in cmd.pending_orders:
            if order["type"] == "awacs_flee":
                awacs.flee(order["threat_pos"])
                awacs.radar.emitting = False
            elif order["type"] == "awacs_resume":
                awacs.stop_flee()
                awacs.radar.emitting = True
        emit = awacs.radar.emitting
        emit_timeline.append((t, emit))
        if emit != prev_emit:
            transitions += 1
            prev_emit = emit
        t += CMD_DT
    return transitions, emit_timeline


def run():
    results = {}
    awx, awz = None, None

    # ---- B1: persistent sole-sensor threat -> no strobe -----------------------
    w = CombatWorld(CombatConfig(seed=4242))
    aw = w.awacs
    aw.radar.emitting = True
    apos = aw.pos
    # A missile parked 40 km from the AWACS (well inside the 100 km flee range).
    threat = np.array([float(apos[0]) + 40_000.0, 9_000.0, float(apos[2])])

    def persistent(t):
        return threat        # always there, but only seen while emitting

    total = 300.0            # 5 minutes — would show ~9 strobes at 31 s period
    trans, timeline = _drive(w, persistent, total)
    silent_frac = sum(1 for _, e in timeline if not e) / len(timeline)
    # Measure the blink PERIOD: gaps between successive emit events. The old bug
    # strobed at ~31 s (track-age window). The dwell must push the period to at
    # least ~DWELL_S. We also count residual 1-tick blinks (emit then silent next
    # second) — the dwell SLOWS but does not fully kill the sole-sensor blink.
    emit_times = [t for t, e in timeline if e]
    periods = [b - a for a, b in zip(emit_times, emit_times[1:])]
    min_period = min(periods) if periods else float("inf")
    # PASS criterion: strobe period is dominated by the dwell (>= ~DWELL_S, i.e.
    # well above the old ~31 s), and the AWACS stays silent the vast majority of
    # the time (it is NOT oscillating ~every 31 s).
    b1_ok = (min_period >= AWACS_EMCON_DWELL_S - 2.0) and silent_frac > 0.9
    results["B1"] = b1_ok
    print(f"B1 persistent sole-sensor: transitions={trans} over {total:.0f}s; "
          f"blink_period_min={min_period:.0f}s (old strobe ~31s, dwell={AWACS_EMCON_DWELL_S:.0f}s); "
          f"silent_frac={silent_frac:.2f} "
          f"-> {'PASS (slowed, mostly silent)' if b1_ok else 'FAIL (still ~31s strobe)'}")

    # ---- B2: genuine threat -> silences ---------------------------------------
    w2 = CombatWorld(CombatConfig(seed=4242))
    aw2 = w2.awacs
    aw2.radar.emitting = True
    apos2 = aw2.pos
    near = np.array([float(apos2[0]) + 30_000.0, 9_000.0, float(apos2[2])])
    _drive(w2, lambda t: near, 5.0)
    b2_ok = aw2.radar.emitting is False and aw2._fleeing
    results["B2"] = b2_ok
    print(f"B2 genuine threat: emitting={aw2.radar.emitting} fleeing={aw2._fleeing} "
          f"-> {'PASS (silences)' if b2_ok else 'FAIL'}")

    # ---- B3: recovers when clear ----------------------------------------------
    w3 = CombatWorld(CombatConfig(seed=4242))
    aw3 = w3.awacs
    aw3.radar.emitting = True
    apos3 = aw3.pos
    near3 = np.array([float(apos3[0]) + 30_000.0, 9_000.0, float(apos3[2])])

    def intermittent(t):
        # Threat present only for the first 10 s, then gone forever.
        return near3 if t < 10.0 else None

    # Run long enough to clear the dwell after the threat departs.
    trans3, timeline3 = _drive(w3, intermittent,
                               10.0 + AWACS_EMCON_DWELL_S + 30.0)
    # It must be silent during/just-after the threat, then re-emit once dwell
    # elapses. Find the recovery time (first emit==True after t>=10).
    recovered_at = None
    for t, e in timeline3:
        if t >= 10.0 and e:
            recovered_at = t
            break
    final_emit = timeline3[-1][1]
    # Recovery should land near last-seen(=~10s) + dwell, not immediately, and
    # not never.
    expected_lo = 10.0 + AWACS_EMCON_DWELL_S - 3.0
    b3_ok = (recovered_at is not None and final_emit
             and recovered_at >= expected_lo)
    results["B3"] = b3_ok
    print(f"B3 recover-when-clear: recovered_at={recovered_at}s "
          f"(expected >= ~{expected_lo:.0f}s) final_emit={final_emit} "
          f"transitions={trans3} -> {'PASS' if b3_ok else 'FAIL'}")

    ok = all(results.values())
    print(f"\n(b) AWACS EMCON OVERALL: {'PASS' if ok else 'FAIL'}  {results}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run())
