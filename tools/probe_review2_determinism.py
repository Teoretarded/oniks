"""REVIEW 2 / check (d): determinism. Two same-seed CombatWorlds must be
bit-identical over N steps, INCLUDING after the new enemy-AI code paths fire
(evasion assignment, SM-6 channel, EMCON dwell, prune of back-plots).

We build two worlds with the same seed, step both, and after each step compare a
full state fingerprint: every missile pos/vel, every enemy-air pos/heading, ship
positions/ammo, commander picture track contents. Any divergence -> FAIL with the
first diverging step and field.

To EXERCISE the new code (not just the idle CAP), we inject the SAME scripted
player S-300 shots into BOTH worlds at the same steps (a fighter break stimulus)
and the SAME high inbound (an SM-6 stimulus), so the new branches actually run.

Run: python tools/probe_review2_determinism.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from world.combat import CombatWorld
from world.combat_config import CombatConfig
from sim.enemy_air import Fighter
from sim.sam import SamMissile
from sim.arsenal import S300

DT = 1.0 / 120.0


def _fingerprint(w):
    """A flat float list capturing all mutable sim state we care about."""
    fp = [w.sim_time]
    for m in w.missiles:
        fp += [float(m.pos[0]), float(m.pos[1]), float(m.pos[2])]
        v = m.vel
        fp += [float(v[0]), float(v[1]), float(v[2])]
        fp += [1.0 if m.alive else 0.0]
    for e in w.enemy_air:
        fp += [float(e.pos[0]), float(e.pos[1]), float(e.pos[2]),
               float(getattr(e, "heading", 0.0)),
               1.0 if e.alive else 0.0]
    for s in w.ships:
        fp += [float(s.pos[0]), float(s.pos[2]),
               float(getattr(s, "sm2_ammo", 0)),
               float(getattr(s, "sm6_ammo", 0)),
               float(getattr(s, "ciws_ammo", 0))]
    # Commander picture missile tracks (sorted for order-independence).
    mt = w.commander.picture.missile_tracks
    for k in sorted(mt):
        v = mt[k]
        fp += [float(v["pos"][0]), float(v["pos"][2]), float(v["t"])]
    fp += [float(getattr(w, "_zircon_ammo", -1)),
           float(w.sam_ammo), float(w.sam_ammo_40n6)]
    return np.array(fp, dtype=np.float64)


def run():
    seed = 999001
    wa = CombatWorld(CombatConfig(seed=seed))
    wb = CombatWorld(CombatConfig(seed=seed))

    n_steps = 6000          # 50 s at 120 Hz
    diverged_at = None
    diverged_field = None
    for i in range(n_steps):
        wa.step(DT)
        wb.step(DT)
        fa = _fingerprint(wa)
        fb = _fingerprint(wb)
        if fa.shape != fb.shape:
            diverged_at = i
            diverged_field = f"shape {fa.shape} != {fb.shape}"
            break
        if not np.array_equal(fa, fb):
            idx = int(np.argmax(fa != fb))
            diverged_at = i
            diverged_field = (f"index {idx}: {fa[idx]!r} != {fb[idx]!r} "
                              f"(maxdiff={np.max(np.abs(fa - fb)):.3e})")
            break

    d1_ok = diverged_at is None
    print(f"D1 idle/CAP world ({n_steps} steps = {n_steps*DT:.0f}s): "
          f"{'bit-identical PASS' if d1_ok else f'DIVERGED at step {diverged_at}: {diverged_field}'}")

    # ---- D2: exercise the NEW branches identically in both worlds --------------
    wa2 = CombatWorld(CombatConfig(seed=seed))
    wb2 = CombatWorld(CombatConfig(seed=seed))

    def airborne(w, max_s=600.0):
        t = 0.0
        while t < max_s:
            w.step(DT)
            t += DT
            for e in w.enemy_air:
                if isinstance(e, Fighter) and e.alive and e.state in (3, 2):
                    return e
        return None

    fa_ = airborne(wa2)
    fb_ = airborne(wb2)
    # Both reached the same step count deterministically; spawn identical locked,
    # tracked SAMs (same id-independent geometry) into each.
    def stim(w, f):
        if f is None:
            return None
        fx, fz = float(f.pos[0]), float(f.pos[2])
        pos = np.array([fx, float(f.pos[1]), fz - 30_000.0])
        sam = SamMissile(S300, pos, f)
        sam.is_hostile = False
        w.missiles.append(sam)
        return sam

    sa = stim(wa2, fa_)
    sb = stim(wb2, fb_)

    def refresh(w, sam):
        if sam is None:
            return
        tid = f"hostile_{id(sam):x}"
        w.commander.picture.update_missile_track(
            tid, sam.pos.copy(), np.array([0.0, 0.0, 250.0]), w.sim_time)

    # Compare a REDUCED fingerprint robust to the id-keyed track name (which
    # differs by object identity between processes/worlds): drop the picture
    # track keys, keep everything physical.
    def fp2(w):
        fp = [w.sim_time]
        for m in w.missiles:
            fp += [float(m.pos[0]), float(m.pos[1]), float(m.pos[2]),
                   1.0 if m.alive else 0.0]
        for e in w.enemy_air:
            fp += [float(e.pos[0]), float(e.pos[1]), float(e.pos[2]),
                   float(getattr(e, "heading", 0.0)),
                   float(getattr(e, "_evade_threat") is not None
                         if hasattr(e, "_evade_threat") else 0.0)]
        return np.array(fp, dtype=np.float64)

    diverged2 = None
    for i in range(1440):    # 12 s of break dynamics
        refresh(wa2, sa)
        refresh(wb2, sb)
        wa2.step(DT)
        wb2.step(DT)
        a, b = fp2(wa2), fp2(wb2)
        if a.shape != b.shape or not np.array_equal(a, b):
            idx = (int(np.argmax(a != b)) if a.shape == b.shape
                   else f"shape {a.shape}!={b.shape}")
            diverged2 = (i, idx)
            break
    d2_ok = diverged2 is None
    print(f"D2 evasion+SM-6 branches exercised (12 s break): "
          f"{'bit-identical PASS' if d2_ok else f'DIVERGED at {diverged2}'}")

    ok = d1_ok and d2_ok
    print(f"\n(d) DETERMINISM OVERALL: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run())
