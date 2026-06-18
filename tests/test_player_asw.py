"""M5 player ASW weapon: depth-reaching prosecution of a localized boat.

Contracts (spec 03, feature 5):
  (a) firing with NO subsurface track -> None (refused; can't shoot blind).
  (b) a SHARP fix within ASW_SEEKER_BASKET_M of the real sub -> acquire +
      Submarine.kill().
  (c) a COARSE datum beyond the basket -> miss (sub survives) — the kill emerges
      from fix quality vs the basket (physics-not-dice), not a roll.
  (d) the ASW round is is_hostile=False and cannot damage player structures.
  (e) killing the last sub flips victorious True when the other win sub-
      conditions already hold.
  (f) determinism: same setup -> same outcome.
"""

from __future__ import annotations

import numpy as np
import pytest

from sim.asw import AswRound, ASW_SEEKER_BASKET_M
from sim.submarine import Submarine
from world.combat import CombatWorld
from world.combat_config import CombatConfig

DT = 1.0 / 120.0
BASE = np.array([0.0, 0.0, 0.0], dtype=np.float64)


def _sub_at(xz, seed=1337):
    return Submarine(anchor_xz=xz, rng=np.random.default_rng([seed, 13]),
                     kalibr_ammo=0, base_xz=(0.0, 0.0))


def _fly(rnd, max_s=400.0):
    """Step the round to completion; return whether it ended alive."""
    for _ in range(int(max_s / DT)):
        rnd.update(DT)
        if not rnd.alive:
            break
    return rnd.alive


# ---------------------------------------------------------------------------
# (a) no blind fire
# ---------------------------------------------------------------------------

def test_launch_asw_refused_without_track():
    """launch_asw returns None when there is no subsurface track (even with
    ASW ammo) — the find-then-kill discipline (no blind sub-sweeping)."""
    cw = CombatWorld(CombatConfig(seed=1337, n_subs=1, asw_ammo=4,
                                  sub_kalibr_ammo=0))
    assert cw.asw_ammo_left == 4
    assert not cw.sub_contacts          # nothing localized yet
    assert cw.launch_asw() is None
    assert cw.asw_ammo_left == 4        # no round consumed


def test_launch_asw_refused_at_zero_ammo():
    """Even with a track, 0 ASW ammo refuses."""
    cw = CombatWorld(CombatConfig(seed=1337, n_subs=1, asw_ammo=0))
    sub = cw.subs[0]
    cw.sub_contacts[sub.sub_id] = dict(
        pos=sub.pos.copy(), quality=500.0, kind="sub", last_heard=0.0,
        age=0.0, t_drop=1e9, sub_id=sub.sub_id)
    assert cw.launch_asw() is None


# ---------------------------------------------------------------------------
# (b) sharp fix -> kill ; (c) coarse fix -> miss  (physics-not-dice)
# ---------------------------------------------------------------------------

def test_sharp_fix_within_basket_kills():
    """A SHARP fix on the real sub position -> the round acquires + kills."""
    sub = _sub_at((0.0, 100_000.0))
    # Fix sits right on truth, quality well inside the basket.
    fix_xz = (float(sub.pos[0]) + 100.0, float(sub.pos[2]) - 100.0)
    rnd = AswRound(BASE, fix_xz, fix_quality=400.0, target_sub=sub)
    _fly(rnd)
    assert not sub.alive, "a sharp fix within the basket must kill the boat"
    assert rnd.acquired


def test_coarse_datum_beyond_basket_misses():
    """A COARSE datum whose fix sits FAR from the boat (error beyond the basket)
    -> the round splashes on the fix but the boat is not in the basket -> miss
    (sub survives).  Kill emergence from fix quality vs basket, not a roll."""
    sub = _sub_at((0.0, 100_000.0))
    # The believed fix is 8 km off the real boat (a stale datum after it ran).
    fix_xz = (float(sub.pos[0]) + 8_000.0, float(sub.pos[2]) + 8_000.0)
    rnd = AswRound(BASE, fix_xz, fix_quality=8_000.0, target_sub=sub)
    _fly(rnd)
    assert sub.alive, "a fix beyond the basket must miss (boat survives)"
    assert not rnd.acquired


def test_basket_boundary_is_the_discriminator():
    """The basket is THE discriminator: a fix just inside kills, just outside
    misses (two-sided, the kill is geometry not a roll)."""
    sub = _sub_at((0.0, 100_000.0))
    inside = (float(sub.pos[0]) + ASW_SEEKER_BASKET_M * 0.5,
              float(sub.pos[2]))
    r_in = AswRound(BASE, inside, fix_quality=ASW_SEEKER_BASKET_M * 0.5,
                    target_sub=sub)
    _fly(r_in)
    assert not sub.alive

    sub2 = _sub_at((0.0, 100_000.0))
    outside = (float(sub2.pos[0]) + ASW_SEEKER_BASKET_M * 2.0,
               float(sub2.pos[2]))
    r_out = AswRound(BASE, outside, fix_quality=ASW_SEEKER_BASKET_M * 2.0,
                     target_sub=sub2)
    _fly(r_out)
    assert sub2.alive


# ---------------------------------------------------------------------------
# (d) player-side: cannot damage player structures
# ---------------------------------------------------------------------------

def test_asw_round_is_not_hostile():
    """The ASW round is is_hostile=False, so the base-damage sweep excludes it
    (like the friendly Pantsir 57E6)."""
    sub = _sub_at((0.0, 100_000.0))
    rnd = AswRound(BASE, (0.0, 100_000.0), fix_quality=500.0, target_sub=sub)
    assert getattr(rnd, "is_hostile", True) is False


def test_asw_does_not_appear_in_hostile_base_sweep():
    """End-to-end: an ASW round flying over the base never demolishes a TEL
    (it is filtered out of the hostile-vs-structures sweep)."""
    cw = CombatWorld(CombatConfig(seed=1337, n_subs=1, asw_ammo=1))
    sub = cw.subs[0]
    cw.sub_contacts[sub.sub_id] = dict(
        pos=sub.pos.copy(), quality=500.0, kind="sub", last_heard=0.0,
        age=0.0, t_drop=1e9, sub_id=sub.sub_id)
    bastions_before = [s.alive for s in cw.structures if s.kind == "bastion_tel"]
    cw.launch_asw()
    for _ in range(120 * 60):
        cw.step(DT)
    bastions_after = [s.alive for s in cw.structures if s.kind == "bastion_tel"]
    assert bastions_before == bastions_after, (
        "the player ASW round must never demolish the player base")


# ---------------------------------------------------------------------------
# (e) killing the last sub flips victorious
# ---------------------------------------------------------------------------

def test_killing_last_sub_flips_victory():
    """With all other win sub-conditions met, the ASW kill of the last boat
    flips victorious True."""
    from sim.ships import ST_GONE
    cw = CombatWorld(CombatConfig(seed=1337, n_subs=1, asw_ammo=1,
                                  n_enemy_radars=0))
    sub = cw.subs[0]
    for s in cw.ships:
        s.state = ST_GONE
    cw.airfield.alive = False
    assert not cw.victorious
    # Localize on truth + prosecute.
    cw.sub_contacts[sub.sub_id] = dict(
        pos=sub.pos.copy(), quality=400.0, kind="sub", last_heard=0.0,
        age=0.0, t_drop=1e9, sub_id=sub.sub_id)
    cw.launch_asw()
    for _ in range(120 * 200):
        cw.step(DT)
        if cw.victorious:
            break
    assert not sub.alive
    assert cw.victorious


# ---------------------------------------------------------------------------
# (f) determinism
# ---------------------------------------------------------------------------

def test_asw_outcome_deterministic():
    """Same fix + same boat -> same acquire/kill outcome + same splash pos."""
    out = []
    for _ in range(2):
        sub = _sub_at((0.0, 100_000.0))
        rnd = AswRound(BASE, (float(sub.pos[0]) + 200.0, float(sub.pos[2])),
                       fix_quality=500.0, target_sub=sub)
        _fly(rnd)
        out.append((sub.alive, rnd.acquired,
                    round(float(rnd.pos[0]), 3), round(float(rnd.pos[2]), 3)))
    assert out[0] == out[1]
