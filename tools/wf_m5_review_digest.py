"""INDEPENDENT reviewer digest for the M5 byte-identical gate.

Deliberately samples MORE than the implementer's wf_m5_digest.py: ship id,
ship_type, hp, heading, all ammo counts, pos, state; full missile state; and
the event tuples (kind + position). Runs the DEFAULT config and must produce
the SAME hash on pre-change HEAD and the working tree.

Run: python tools/wf_m5_review_digest.py
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


def digest(steps=8000, seed=1337):
    cfg = CombatConfig(seed=seed)
    cw = CombatWorld(cfg)
    h = hashlib.sha256()

    # snapshot the static roster identity ONCE up front (ids/type/hp/heading)
    h.update(struct.pack("<i", len(cw.ships)))
    for s in cw.ships:
        h.update(s.ship_id.encode("utf-8"))
        h.update(b"|")
        h.update(str(s.ship_type).encode("utf-8"))
        h.update(b"|")
        h.update(struct.pack("<i", int(getattr(s, "hp", -1))))
        _f(h, float(getattr(s, "heading", 0.0)))
        _f(h, float(getattr(s, "length", 0.0)))
        _f(h, float(getattr(s, "beam", 0.0)))
        _f(h, float(getattr(s, "height", 0.0)))
        _f(h, float(getattr(s, "hit_reach", 0.0)))

    targets = [np.array([0.0, 0.0, 200_000.0]),
               np.array([40_000.0, 0.0, 260_000.0])]
    fired = 0
    for i in range(steps):
        if i == 60 and fired < 1:
            cw.launch("hi-lo", targets[0]); fired = 1
        if i == 1200 and fired < 2:
            cw.launch("lo-lo", targets[1]); fired = 2
        cw.step(DT)
        if i % 25 == 0:
            for s in cw.ships:
                _vec(h, s.pos)
                _f(h, float(getattr(s, "heading", 0.0)))
                h.update(struct.pack("<i", int(s.state)))
                h.update(struct.pack("<i", int(getattr(s, "sm2_ammo", 0))))
                h.update(struct.pack("<i", int(getattr(s, "sm6_ammo", 0))))
                h.update(struct.pack("<i", int(getattr(s, "ciws_ammo", 0))))
                h.update(struct.pack("<i",
                         int(getattr(s, "tomahawk_ammo", 0))))
            for m in cw.missiles:
                _vec(h, m.pos)
                _vec(h, m.vel)
                h.update(b"\x01" if m.alive else b"\x00")
            for ev in cw.events:
                h.update(str(ev[0]).encode("utf-8"))
            h.update(struct.pack("<i", len(cw.events)))
            h.update(struct.pack("<i", len(cw.missiles)))
    h.update(struct.pack("<i", len(cw.missiles)))
    for s in cw.ships:
        _vec(h, s.pos)
        h.update(struct.pack("<i", int(s.state)))
    return h.hexdigest()


if __name__ == "__main__":
    d = digest()
    print("M5_REVIEW_DIGEST", d)
