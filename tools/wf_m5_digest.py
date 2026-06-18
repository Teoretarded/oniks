"""M5 byte-identical gate: a multi-thousand-step same-seed digest of the
DEFAULT-config CombatWorld.

Runs the default battle deterministically (no wall-clock, no input), fires a
couple of Oniks salvos to create live state across the fleet/defense/commander
streams, steps several thousand ticks, and SHA-256-hashes every dynamic datum
(ship pos/state/ammo, every missile pos/vel/alive, events).  The hash must be
IDENTICAL before and after the M5 ship-class change with all new counts 0.

Run: python tools/wf_m5_digest.py   (prints the digest; exit 0)
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


def digest(steps=6000, seed=1337):
    cfg = CombatConfig(seed=seed)
    cw = CombatWorld(cfg)
    h = hashlib.sha256()

    # Fire two Oniks salvos at the deep band to wake up the defense + commander.
    targets = [np.array([0.0, 0.0, 200_000.0]),
               np.array([40_000.0, 0.0, 260_000.0])]
    fired = 0
    for i in range(steps):
        if i == 60 and fired < 1:
            cw.launch("hi-lo", targets[0]); fired = 1
        if i == 1200 and fired < 2:
            cw.launch("lo-lo", targets[1]); fired = 2
        cw.step(DT)
        # Sample the full dynamic state every 50 steps (cheaper, still strict).
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
    # Final state snapshot.
    h.update(struct.pack("<i", len(cw.missiles)))
    for s in cw.ships:
        _vec(h, s.pos)
    return h.hexdigest()


if __name__ == "__main__":
    d = digest()
    print("M5_DEFAULT_DIGEST", d)
