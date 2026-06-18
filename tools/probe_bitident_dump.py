"""M4-B bit-identical proof: dump full per-substep trajectories for the LOCKED
weapons so a working-tree run can be byte-compared against the pre-change commit.

Flies (1) the Oniks hi-lo shot, (2) the Oniks lo-lo shot, (3) the Zircon hi-lo
shot, each over open ocean, sampling pos/vel/fuel/phase EVERY substep, and
writes them as exact-repr lines to stdout. Run it on HEAD and on the working
tree and ``diff`` the two dumps: a single differing line fails the proof.

Usage:
    git stash && python tools/probe_bitident_dump.py > /tmp/before.txt
    git stash pop && python tools/probe_bitident_dump.py > /tmp/after.txt
    diff /tmp/before.txt /tmp/after.txt   # must be empty
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sim.arsenal import ONIKS, ZIRCON          # noqa: E402
from sim.missile import Missile                # noqa: E402

DT = 1.0 / 120.0


class _OpenSea:
    ships = []

    def terrain_height_at(self, x, z):
        return -500.0

    def surface_height_at(self, x, z):
        return 0.0


def dump(tag, weapon, profile, target_z, max_t=200.0):
    m = Missile(weapon, np.array([0.0, 0.0, 0.0]), 0.0, profile,
                np.array([0.0, 0.0, target_z]))
    w = _OpenSea()
    out = []
    for _ in range(int(max_t / DT)):
        m.update(DT, w)
        out.append(
            f"{tag} {m.pos[0]!r} {m.pos[1]!r} {m.pos[2]!r} "
            f"{m.vel[0]!r} {m.vel[1]!r} {m.vel[2]!r} "
            f"{m.fuel!r} {int(m.phase)}")
        if not m.alive:
            break
    return out


def main():
    lines = []
    lines += dump("oniks_hilo", ONIKS, "hi-lo", 120_000.0)
    lines += dump("oniks_lolo", ONIKS, "lo-lo", 60_000.0)
    lines += dump("zircon_hilo", ZIRCON, "hi-lo", 200_000.0)
    sys.stdout.write("\n".join(lines))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
