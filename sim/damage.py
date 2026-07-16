"""Damage: segment-vs-OBB hit test and warhead application (pure numpy, GL-free).

The missile moves several meters per 120 Hz step at terminal speed, so impacts
are detected with a swept segment (prev_pos -> pos) against each ship's hull
OBB or compound hit volumes — a point sample would tunnel through a beam-on
hull.
"""

import math

import numpy as np

from sim.missile import PH_DEAD
from sim.ships import BURN_TIME, ST_ALIVE, ST_BURNING, ST_SINKING

_EPS = 1e-12


def segment_obb_entry_fraction(p0, p1, center, half, rot3x3):
    """Return the segment's entry fraction into an OBB, or ``None``.

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
                return None                       # parallel and outside the slab
        else:
            ta = (-half[i] - q0[i]) / d[i]
            tb = (half[i] - q0[i]) / d[i]
            if ta > tb:
                ta, tb = tb, ta
            t_enter = max(t_enter, ta)
            t_exit = min(t_exit, tb)
            if t_enter > t_exit:
                return None
    return t_enter


def segment_hits_obb(p0, p1, center, half, rot3x3):
    """True if segment p0->p1 intersects the oriented box."""
    return segment_obb_entry_fraction(
        p0, p1, center, half, rot3x3) is not None


def apply_missile_hits(missiles, ships, effects_out, damage_model="legacy"):
    """Swept hit test of every live missile against every hittable ship.

    On a hit: ship loses 1 hp and starts BURNING (or SINKING at 0 hp), the
    missile dies with impact_pos at the segment midpoint, and a
    ("ship_hit", pos) effect is appended for particles/audio.

    A conservative sphere prefilter rejects nearly every pair before the
    OBB math (Task 22 perf): a hit needs a segment point inside a hit volume,
    which lies within ``ship.hit_reach`` of ``ship.pos``, and every
    segment point is within the step length of ``m.pos`` — so any pair
    farther apart than the sum cannot possibly hit. Ship positions are
    pulled into plain floats once per call (Task GATE perf: this runs per
    120 Hz substep and the prefilter math dominates).
    """
    hittable = [(ship,) + tuple(ship.pos.tolist()) + (ship.hit_reach,)
                for ship in ships if ship.state in (ST_ALIVE, ST_BURNING)]
    if not hittable:
        return
    for m in missiles:
        if not m.alive:
            continue
        # Side check (2026-06-18 audit): ships are all enemy-side, so only the
        # player's anti-ship rounds (is_hostile False — Oniks/Zircon, and the
        # M4 ASBM) may damage a hull.  Enemy interceptors (SM-2/SM-6) and strike
        # rounds carry is_hostile=True and must never OBB-hit an enemy ship
        # (a sister-ship friendly-fire kill).  Mirrors the Pantsir/structure
        # sweeps' getattr(m, "is_hostile", False) convention.
        if getattr(m, "is_hostile", False):
            continue
        mx, my, mz = m.pos.tolist()
        ppx, ppy, ppz = m.prev_pos.tolist()
        seg = math.sqrt((mx - ppx) ** 2 + (my - ppy) ** 2 + (mz - ppz) ** 2)
        for ship, sx, sy, sz, hit_reach in hittable:
            dx = mx - sx
            dy = my - sy
            dz = mz - sz
            reach = hit_reach + seg
            if dx * dx + dy * dy + dz * dz > reach * reach:
                continue                          # provably out of reach
            if ship.state not in (ST_ALIVE, ST_BURNING):
                continue                          # sunk by an earlier missile
            if ship is getattr(m, "launch_platform", None):
                continue        # a deck-launched SAM starts INSIDE its own
                #                 ship's OBB — never a self-hit (Phase 2)
            # Most ships expose one historical hull OBB. Rebuilt silhouettes
            # may expose a small compound set (for example a carrier's wide,
            # thin flight deck and offset island). The fallback keeps older
            # test/integration doubles that only implement obb() valid.
            hit_obbs = getattr(ship, "hit_obbs", None)
            volumes = hit_obbs() if hit_obbs is not None else (ship.obb(),)
            entries = [
                t for center, half, rot in volumes
                if (t := segment_obb_entry_fraction(
                    m.prev_pos, m.pos, center, half, rot)) is not None
            ]
            if not entries:
                continue
            # Compound volumes can overlap. Subsystem forensics/damage must
            # start at the first real surface crossed, not the segment midpoint
            # or the entry of an unrelated broad hull box.
            t_entry = min(entries)
            entry_world = m.prev_pos + (m.pos - m.prev_pos) * t_entry
            impact = (m.prev_pos + m.pos) * 0.5
            m.alive = False
            m.phase = PH_DEAD
            m.impact_pos = impact.copy()
            # Forensics stamps (WRITE-ONLY): the debrief flight recorder
            # reads these off the dead round; NO sim code ever does — the
            # digest contract is untouched.
            m.death_cause = ("hit", str(getattr(ship, "ship_type", "ship")))
            m.killed_by = ship
            if damage_model == "subsystem":
                # 2026-07-06 subsystem model (sim/damage_model.py): hit
                # location + KE + warhead resolve module knockouts, breaches
                # and fires; flooding/cook-off decide the sinking, not hp.
                # Deferred import keeps the legacy path's import graph (and
                # module-load order) byte-identical when the flag is off.
                from sim import damage_model as _dm
                _dm.resolve_hit(
                    ship, m, impact, effects_out, entry_world=entry_world)
            else:
                ship.hp -= 1
                if ship.hp > 0:
                    ship.state = ST_BURNING
                    ship.burn_timer = BURN_TIME   # a fresh hit restarts the fire
                else:
                    ship.state = ST_SINKING
            effects_out.append(("ship_hit", impact.copy()))
            break                                 # this missile is spent
