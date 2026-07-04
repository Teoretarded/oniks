"""Regression tests for the 2026-07-04 improvement-roadmap confirmed bug
fixes (docs/research/improvement_roadmap_2026-07-04.md):

  1. Terminal seeker re-lock: a locked ship that dies mid-flight
     (ALIVE/BURNING -> SINKING/GONE) drops the lock and the seeker
     re-acquires a LIVE hull instead of flying PN onto the wreck
     (sim/missile.py _guidance PH_TERMINAL).
  2. Swept surface-impact test: a fast round whose single 120 Hz substep
     straddles a narrow terrain crest impacts it instead of tunneling
     through (sim/missile.py _swept_surface_hit, shared with sim/sam.py);
     short steps keep the legacy endpoint-only query byte-for-byte.
  3. TimeWarpDirector latches the drop-cause tag through the DWELL
     debounce so the HUD "(auto: ...)" label cannot flicker off while the
     warp still sits at 1x (game/timewarp.py).
  4. CombatEndOverlay reads world.defeat_cause: a beachhead loss shows
     BEACHHEAD ESTABLISHED, not the hardcoded bastion string
     (game/combat_end.py).
"""

import math

import numpy as np

from sim.arsenal import ONIKS
from sim.missile import (Missile, PH_DEAD, PH_TERMINAL, SWEEP_SAMPLE_M,
                         _swept_surface_hit)
from sim.ships import ST_SINKING, Ship
from game.timewarp import DWELL_S, TimeWarpDirector

DT = 1.0 / 120.0


# --- helpers -------------------------------------------------------------------

class _OpenWater:
    ships = []

    def terrain_height_at(self, x, z):
        return -50.0


class _WorldWithShips(_OpenWater):
    def __init__(self, ships):
        self.ships = ships


class _CrestWorld(_OpenWater):
    """Open water with one narrow 400 m terrain crest band across z."""

    def __init__(self, z0, z1, height=400.0):
        self.z0, self.z1, self.height = z0, z1, height

    def terrain_height_at(self, x, z):
        return self.height if self.z0 <= z <= self.z1 else -50.0


def _ship_at(sid, x, z):
    """A stationary-lane cargo ship whose pos is exactly (x, z)."""
    return Ship(sid, "cargo", [(x, z), (x, z + 1.0)], 0.0)


def _terminal_missile(pos, vel, target=(0.0, 0.0, 200_000.0)):
    """A Missile hand-placed straight into its terminal leg."""
    m = Missile(ONIKS, np.array([0.0, 60.0, 0.0]), heading=0.0,
                profile="lo-lo", target_point=np.array(target))
    m.phase = PH_TERMINAL
    m.pos = np.array(pos, dtype=np.float64)
    m.prev_pos = m.pos.copy()
    m.vel = np.array(vel, dtype=np.float64)
    return m


# --- 1. terminal re-lock on a dead target ---------------------------------------

def test_terminal_lock_acquires_nearest_alive_ship():
    a = _ship_at("a", 0.0, 8_000.0)
    b = _ship_at("b", 300.0, 9_000.0)
    w = _WorldWithShips([a, b])
    m = _terminal_missile([0.0, 15.0, 0.0], [0.0, 0.0, 750.0],
                          target=(0.0, 0.0, 8_000.0))
    m.update(DT, w)
    assert m.locked_ship is a


def test_terminal_relock_redistributes_off_a_sinking_hull():
    """The lead round sank the locked hull: the follow-on drops the dead
    lock next step and re-acquires the surviving ship in the cone."""
    a = _ship_at("a", 0.0, 8_000.0)
    b = _ship_at("b", 300.0, 9_000.0)
    w = _WorldWithShips([a, b])
    m = _terminal_missile([0.0, 15.0, 0.0], [0.0, 0.0, 750.0],
                          target=(0.0, 0.0, 8_000.0))
    m.update(DT, w)
    assert m.locked_ship is a
    a.state = ST_SINKING                      # lead round's kill lands
    assert not a.alive
    m.update(DT, w)
    assert m.locked_ship is b                 # lock dropped + re-acquired


def test_terminal_relock_with_no_live_hull_falls_back_to_target_point():
    """All hulls dead: the lock clears and the round flies on without
    crashing (PN onto target_point / skim fallback)."""
    a = _ship_at("a", 0.0, 8_000.0)
    w = _WorldWithShips([a])
    m = _terminal_missile([0.0, 15.0, 0.0], [0.0, 0.0, 750.0],
                          target=(0.0, 0.0, 8_000.0))
    m.update(DT, w)
    assert m.locked_ship is a
    a.state = ST_SINKING
    m.update(DT, w)
    assert m.locked_ship is None
    assert m.alive                            # keeps flying, no exception


# --- 2. swept surface-impact test ------------------------------------------------

def test_swept_hit_catches_crest_between_step_endpoints():
    """A ~13 m hypersonic substep straddling a 10 m crest: the endpoint-only
    legacy test misses (both endpoints over open water) but the swept test
    impacts inside the band."""
    w = _CrestWorld(4_996.0, 5_006.0)
    hit = _swept_surface_hit(w, 0.0, 100.0, 4_995.0,
                             0.0, 100.0, 5_008.3)
    assert hit is not None
    x, y, z = hit
    assert 4_996.0 <= z <= 5_006.0
    assert y == 400.0
    # the legacy endpoint check would NOT have fired:
    assert 100.0 > w.terrain_height_at(0.0, 5_008.3)


def test_swept_hit_short_step_matches_legacy_endpoint_query():
    """Steps <= SWEEP_SAMPLE_M add no interior samples: open water is a
    clean miss, and an endpoint at/below the surface impacts exactly at the
    endpoint (the legacy behaviour, byte-for-byte)."""
    w = _OpenWater()
    step = SWEEP_SAMPLE_M * 0.9
    assert _swept_surface_hit(w, 0.0, 5.0, 0.0, 0.0, 5.0, step) is None
    hit = _swept_surface_hit(w, 0.0, 5.0, 0.0, 0.0, -0.5, step)
    assert hit == (0.0, 0.0, step)            # water surface at the endpoint


def test_fast_missile_dies_on_crest_instead_of_tunneling():
    """Full Missile.update: a Mach-4.5-class round crossing the crest in one
    substep is killed at the crest."""
    w = _CrestWorld(4_996.0, 5_006.0)
    m = _terminal_missile([0.0, 100.0, 4_995.0], [0.0, 0.0, 1_600.0],
                          target=(0.0, 0.0, 200_000.0))
    m.update(DT, w)
    assert not m.alive
    assert m.phase == PH_DEAD
    assert 4_996.0 <= float(m.impact_pos[2]) <= 5_006.0
    assert float(m.impact_pos[1]) == 400.0


# --- 3. latched auto-warp cause tag ----------------------------------------------

def test_warp_cause_latches_through_dwell_then_clears():
    d = TimeWarpDirector()
    d.tick(1 / 60.0, 8.0, True, cause="INBOUND")
    assert d.cause == "INBOUND"
    # predicate clears: the dwell holds and the cause stays latched (the
    # shipped flicker read a fresh drop_cause -> None here).
    d.tick(1 / 60.0, 8.0, False)
    assert d.dropped
    assert d.cause == "INBOUND"
    # dwell expires: latch clears with it.
    d.tick(DWELL_S + 0.1, 8.0, False)
    assert not d.dropped
    assert d.cause is None


def test_warp_cause_none_during_drop_keeps_previous_latch():
    """Legacy tick(dt, req, drop) calls (no cause arg) never un-latch a
    live cause mid-drop."""
    d = TimeWarpDirector()
    d.tick(1 / 60.0, 8.0, True, cause="TERMINAL")
    d.tick(1 / 60.0, 8.0, True)               # no cause passed
    assert d.cause == "TERMINAL"


def test_warp_reset_clears_cause():
    d = TimeWarpDirector()
    d.tick(1 / 60.0, 8.0, True, cause="INTERCEPT")
    d.reset(4.0)
    assert d.cause is None


# --- 4. defeat-cause end-screen subtitle -----------------------------------------

def test_defeat_subtitle_map_covers_both_lose_clauses():
    from game.combat_end import _DEFEAT_SUBTITLES
    assert _DEFEAT_SUBTITLES["bastion"] == "ALL BASTION TELs DESTROYED"
    assert _DEFEAT_SUBTITLES["beachhead"] == "BEACHHEAD ESTABLISHED"


def test_end_overlay_threads_defeat_cause():
    from game.combat_end import CombatEndOverlay

    class _App:
        pass

    lose = CombatEndOverlay(_App(), False, lambda: None, lambda: None,
                            lambda: None, defeat_cause="beachhead")
    assert lose.defeat_cause == "beachhead"
    legacy = CombatEndOverlay(_App(), False, lambda: None, lambda: None,
                              lambda: None)
    assert legacy.defeat_cause is None        # legacy callers: bastion text
