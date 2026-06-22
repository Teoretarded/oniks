"""M5 #5 byte-identical gate: a same-seed multi-thousand-step digest of the
DEFAULT-config CombatWorld that ALSO hashes the enemy commander's PICTURE
(commander.picture.emitters + _back_plots + clusters) — the exact state the
decoy emitter / corner reflector touch.

The hash must be IDENTICAL before the M5 #5 decoy change (HEAD) and after it,
with BOTH new counts (n_decoys + n_corner_reflectors) at their default 0.  This
is the load-bearing honesty gate: at 0 NO decoy emitter and NO reflector is
built, none appears in _emitters() / the ELINT feed / the EnemyPicture, the
reflector back-plot bias is never applied, and the picture (emitters +
back-plots + clusters) is BIT-IDENTICAL to today.

Runs the default battle deterministically (no wall-clock, no input), fires a
couple of Oniks salvos to wake the fleet/defense/commander streams, steps
several thousand ticks, and SHA-256-hashes every dynamic datum plus the full
commander picture every 50 steps.

Run: python tools/wf_decoy_digest.py   (prints the digest; exit 0)
"""

import hashlib
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from world.combat import CombatWorld
from world.combat_config import CombatConfig

DT = 1.0 / 120.0


def _f(h, x):
    h.update(struct.pack("<d", float(x)))


def _vec(h, v):
    for c in v:
        _f(h, c)


def _hash_picture(h, pic):
    """Hash the ENEMY commander picture: emitters + raw back-plots + clusters.

    This is what a decoy emitter (a new EmitterIntel) and a corner reflector (an
    extra/biased BackPlotEntry -> new/biased cluster centroid) would perturb, so
    a byte-identical digest proves the both-zero default never touches it."""
    # Emitters: sorted by id for a stable order.
    ems = sorted(pic.emitters.items(), key=lambda kv: kv[0])
    h.update(struct.pack("<i", len(ems)))
    for eid, ei in ems:
        h.update(eid.encode("utf-8"))
        h.update(b"|")
        _vec(h, ei.believed_pos)
        h.update(b"\x01" if ei.alive else b"\x00")
        _f(h, ei.fix_progress)
        _f(h, ei.last_heard_t)
    # Raw back-plots: append-order is part of the contract.
    h.update(struct.pack("<i", len(pic._back_plots)))
    for bp in pic._back_plots:
        _vec(h, bp.estimated_pos)
        _f(h, bp.error_m)
        _f(h, bp.sim_time)
        h.update(str(bp.track_id).encode("utf-8"))
        h.update(b"|")
    # Clusters: centroid + fix count + alive belief + targetable.
    h.update(struct.pack("<i", len(pic.clusters)))
    for c in pic.clusters:
        _vec(h, c.centre)
        h.update(struct.pack("<i", len(c.fixes)))
        h.update(b"\x01" if c.believed_alive else b"\x00")
        h.update(b"\x01" if c.targetable else b"\x00")


def digest(steps=6000, seed=1337):
    cfg = CombatConfig(seed=seed)
    cw = CombatWorld(cfg)
    h = hashlib.sha256()

    # Fire two Oniks salvos at the deep band to wake the defense + commander +
    # the back-plot pipeline (so emitters/back_plots/clusters carry live state).
    targets = [np.array([0.0, 0.0, 200_000.0]),
               np.array([40_000.0, 0.0, 260_000.0])]
    fired = 0
    for i in range(steps):
        if i == 60 and fired < 1:
            cw.launch("hi-lo", targets[0]); fired = 1
        if i == 1200 and fired < 2:
            cw.launch("lo-lo", targets[1]); fired = 2
        cw.step(DT)
        if i % 50 == 0:
            for s in cw.ships:
                _vec(h, s.pos)
                h.update(struct.pack("<i", int(s.state)))
                h.update(struct.pack("<i", int(getattr(s, "sm2_ammo", 0))))
                h.update(struct.pack("<i", int(getattr(s, "sm6_ammo", 0))))
                h.update(struct.pack("<i",
                         int(getattr(s, "tomahawk_ammo", 0))))
            for m in cw.missiles:
                _vec(h, m.pos)
                _vec(h, m.vel)
                h.update(b"\x01" if m.alive else b"\x00")
            h.update(struct.pack("<i", len(cw.events)))
            h.update(struct.pack("<i", len(cw.missiles)))
            # THE M5 #5 GATE: the enemy picture must be bit-identical at 0.
            _hash_picture(h, cw.commander.picture)
    # Final snapshot.
    h.update(struct.pack("<i", len(cw.missiles)))
    for s in cw.ships:
        _vec(h, s.pos)
    _hash_picture(h, cw.commander.picture)
    return h.hexdigest()


if __name__ == "__main__":
    d = digest()
    print("M5_DECOY_DIGEST", d)
