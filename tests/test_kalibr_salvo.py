"""M5 sub-launched Kalibr (3M14-PL) salvo.

Contracts (spec 03, feature 2):
  (a) a fired Kalibr is is_hostile=True, radar_size 'missile', launch_warning
      False (stays fog-gated — the fair telegraph is the acoustic transient).
  (b) launch_platform is set to the sub so sim/damage never self-hits it.
  (c) a salvo aimed within SEEKER_BASKET_M of a TEL acquires + can kill it via
      the shared _refine_strike_aim path (physics-not-dice base hit).
  (d) a salvo whose surveyed aim is beyond the basket hits dirt (no kill).
  (e) determinism: same seed -> same salvo count/positions.
"""

from __future__ import annotations

import numpy as np
import pytest

from sim.arsenal import KALIBR_PL, STRIKES
from sim.strike import StrikeMissile
from sim.submarine import Submarine
from world.combat import CombatWorld, SEEKER_BASKET_M
from world.combat_config import CombatConfig
from world.generation import BASE_POS

DT = 1.0 / 120.0


def test_kalibr_registered_and_scaled_down():
    """KALIBR_PL is a turbofan sea-skimmer (= TLAM) with max_range scaled DOWN
    so the boat is forced close (handoff 03: ~500 km, not the real 1500+ km)."""
    assert "kalibr" in STRIKES
    assert KALIBR_PL.cruise_mach < 1.0           # subsonic turbofan
    assert KALIBR_PL.cruise_alt <= 30.0          # sea-skimmer
    assert KALIBR_PL.max_range <= 600_000.0      # scaled DOWN (forces close)
    assert KALIBR_PL.max_range >= 400_000.0


def test_fired_kalibr_flags():
    """A spawned Kalibr is hostile, radar 'missile', launch_warning False."""
    m = StrikeMissile(KALIBR_PL, np.array([0.0, 0.0, 100_000.0]),
                      np.array([0.0, KALIBR_PL.eject_speed, 0.0]),
                      (0.0, 0.0))
    assert m.is_hostile is True
    assert m.radar_size == "missile"
    assert m.launch_warning is False, (
        "the Kalibr must stay fog-gated — no free launch ping")


def _fire_one_salvo(cw):
    """Force the (single) sub to fire one salvo this tick; return the spawned
    Kalibrs."""
    sub = cw.subs[0]
    before = len(cw.missiles)
    aim = (float(BASE_POS[0]), float(BASE_POS[2]), 0.0)
    cw._fire_kalibr_salvo(sub, aim)
    return [m for m in cw.missiles[before:]]


def test_salvo_launch_platform_is_the_sub():
    """Every fired Kalibr carries launch_platform == the sub (damage.py never
    self-OBB-hits the launcher) — and is a StrikeMissile."""
    cw = CombatWorld(CombatConfig(seed=1337, n_subs=1, sub_kalibr_ammo=4))
    rounds = _fire_one_salvo(cw)
    assert rounds, "the salvo must spawn rounds"
    for m in rounds:
        assert isinstance(m, StrikeMissile)
        assert m.launch_platform is cw.subs[0]
        assert m.is_hostile is True


def test_salvo_consumes_ammo():
    """Firing draws from the boat's Kalibr pool; it cannot over-fire."""
    cw = CombatWorld(CombatConfig(seed=1337, n_subs=1, sub_kalibr_ammo=3))
    sub = cw.subs[0]
    n0 = sub.kalibr_ammo
    rounds = _fire_one_salvo(cw)
    assert 1 <= len(rounds) <= n0
    assert sub.kalibr_ammo == n0 - len(rounds)


def test_salvo_within_basket_can_kill_a_tel():
    """A salvo aimed at the bastion cluster (surveyed base coords + small CEP)
    acquires a live TEL via _refine_strike_aim and demolishes it — the base hit
    EMERGES from the CEP vs the basket (physics-not-dice)."""
    # Disable the player's OWN point defense (n_pantsir=0) so the test isolates
    # the Kalibr->TEL terminal-acquire + base-damage mechanic, not whether the
    # Pantsir shoots the salvo down (that interception is verified elsewhere).
    cw = CombatWorld(CombatConfig(seed=1337, n_subs=1, sub_kalibr_ammo=8,
                                  n_pantsir=0))
    bastions = [s for s in cw.structures if s.kind == "bastion_tel"]
    assert bastions
    # Fire repeated salvos so enough warheads cross the TEL OBB to kill it.
    sub = cw.subs[0]
    cw._fire_kalibr_salvo(sub, (float(BASE_POS[0]), float(BASE_POS[2]), 0.0))
    killed = False
    for _ in range(120 * 1200):     # up to 20 min flight (subsonic, far out)
        cw.step(DT)
        if any(not s.alive for s in bastions):
            killed = True
            break
        if not any(m.alive for m in cw.missiles
                   if getattr(m, "weapon", None) is KALIBR_PL):
            break
    assert killed, "a surveyed salvo within the basket must be able to kill a TEL"


def test_aim_refinement_path_is_the_shared_strike_acquire():
    """_refine_strike_aim returns a live structure within the basket of the
    surveyed base coords (the same terminal acquire the TLAM/JASSM use)."""
    cw = CombatWorld(CombatConfig(seed=1337, n_subs=1))
    ax, az, ay = cw._refine_strike_aim(float(BASE_POS[0]), float(BASE_POS[2]))
    # The refined aim snaps onto a live structure (within the basket).
    near = min(float(np.hypot(s.pos[0] - ax, s.pos[2] - az))
               for s in cw.structures if s.alive)
    assert near < SEEKER_BASKET_M


def test_salvo_determinism():
    """Same seed -> same salvo size + same spawned round positions."""
    def run():
        cw = CombatWorld(CombatConfig(seed=4242, n_subs=1, sub_kalibr_ammo=4))
        rounds = _fire_one_salvo(cw)
        return [(round(float(m.pos[0]), 3), round(float(m.pos[2]), 3),
                 round(float(m.target_x), 3), round(float(m.target_z), 3))
                for m in rounds]
    assert run() == run()
