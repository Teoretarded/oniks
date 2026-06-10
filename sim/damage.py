"""Damage: segment-vs-OBB hit test and warhead application (pure numpy, GL-free).

The missile moves several meters per 120 Hz step at terminal speed, so impacts
are detected with a swept segment (prev_pos -> pos) against the ship hull OBB —
a point-in-box sample would tunnel straight through a beam-on hull.
"""

import numpy as np

from sim.missile import PH_DEAD
from sim.ships import BURN_TIME, ST_ALIVE, ST_BURNING, ST_SINKING

_EPS = 1e-12


def segment_hits_obb(p0, p1, center, half, rot3x3):
    """True if segment p0->p1 intersects the oriented box.

    The segment is transformed into the box's local frame (rot.T @ (p - center))
    and clipped against the three axis slabs [-half, +half] with the standard
    slab test, keeping the parametric overlap within t in [0, 1].
    """
    q0 = rot3x3.T @ (np.asarray(p0, dtype=np.float64) - center)
    q1 = rot3x3.T @ (np.asarray(p1, dtype=np.float64) - center)
    d = q1 - q0
    t_enter, t_exit = 0.0, 1.0
    for i in range(3):
        if abs(d[i]) < _EPS:
            if abs(q0[i]) > half[i]:
                return False                      # parallel and outside the slab
        else:
            ta = (-half[i] - q0[i]) / d[i]
            tb = (half[i] - q0[i]) / d[i]
            if ta > tb:
                ta, tb = tb, ta
            t_enter = max(t_enter, ta)
            t_exit = min(t_exit, tb)
            if t_enter > t_exit:
                return False
    return True


def apply_missile_hits(missiles, ships, effects_out):
    """Swept hit test of every live missile against every hittable ship.

    On a hit: ship loses 1 hp and starts BURNING (or SINKING at 0 hp), the
    missile dies with impact_pos at the segment midpoint, and a
    ("ship_hit", pos) effect is appended for particles/audio.
    """
    for m in missiles:
        if not m.alive:
            continue
        for ship in ships:
            if ship.state not in (ST_ALIVE, ST_BURNING):
                continue                          # sinking/gone: no longer hittable
            center, half, rot = ship.obb()
            if not segment_hits_obb(m.prev_pos, m.pos, center, half, rot):
                continue
            impact = (m.prev_pos + m.pos) * 0.5
            m.alive = False
            m.phase = PH_DEAD
            m.impact_pos = impact.copy()
            ship.hp -= 1
            if ship.hp > 0:
                ship.state = ST_BURNING
                ship.burn_timer = BURN_TIME       # a fresh hit restarts the fire
            else:
                ship.state = ST_SINKING
            effects_out.append(("ship_hit", impact.copy()))
            break                                 # this missile is spent
