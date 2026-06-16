"""Fighter RWR-driven evasion (Phase 8, sensor-driven): a fighter breaks when
its RWR shows a player SAM GUIDING ON IT (target lock) — but the break GEOMETRY
comes from the enemy's own dead-reckoned missile TRACK of that SAM (the picture
store the SM-2/SM-6 fire off), never the SAM's true position. No cheat:
  * locked + tracked  -> break (RWR cue + datalink geometry)
  * locked but UNSEEN -> no break (can't dodge what the fleet can't place)
  * tracked but NOT locked on this fighter -> no break (no false proximity dodge)
"""

import numpy as np

from world.combat import CombatWorld, FIGHTER_RWR_REACT_RANGE_M
from world.combat_config import CombatConfig
from sim.enemy_air import Fighter
from sim.arsenal import S300
from sim.sam import SamMissile


def _a_fighter(w):
    return next(e for e in w.enemy_air if isinstance(e, Fighter))


def _inject_track(w, sam):
    """Mirror _feed_enemy_picture: the enemy senses this player SAM."""
    w.commander.picture.update_missile_track(
        f"hostile_{id(sam):x}", sam.pos.copy(), sam.vel.copy(),
        sim_time=w.sim_time)


def test_fighter_breaks_on_locked_and_tracked_sam():
    """A player SAM guiding on the fighter, held as a sensor track 50 km out
    (inside the RWR react range), triggers a break — using the TRACK geometry."""
    w = CombatWorld(CombatConfig(seed=7))
    f = _a_fighter(w)
    sam = SamMissile(S300, f.pos + np.array([50_000.0, 0.0, 0.0]), f)
    w.missiles.append(sam)
    _inject_track(w, sam)
    assert 50_000.0 < FIGHTER_RWR_REACT_RANGE_M
    w._assign_air_threats()
    assert f._evade_threat is not None, \
        "locked + tracked SAM must break the fighter (RWR cue + datalink track)"


def test_no_break_when_locked_but_not_sensed():
    """No cheat: a SAM guiding on the fighter but NOT held as a track (the fleet
    can't see it) yields no break — the geometry came from a sensor track, not
    the SAM's true position."""
    w = CombatWorld(CombatConfig(seed=7))
    f = _a_fighter(w)
    sam = SamMissile(S300, f.pos + np.array([50_000.0, 0.0, 0.0]), f)
    w.missiles.append(sam)
    # deliberately do NOT inject a track
    w._assign_air_threats()
    assert f._evade_threat is None, \
        "locked but unseen SAM must NOT break the fighter (no truth read)"


def test_no_break_when_tracked_but_not_locked_on_this_fighter():
    """A tracked SAM guiding on a DIFFERENT fighter must not break this one —
    a fighter dodges only what its RWR says is locked on IT, no proximity dodge."""
    w = CombatWorld(CombatConfig(seed=7))
    f = _a_fighter(w)
    other = next(e for e in w.enemy_air
                 if isinstance(e, Fighter) and e is not f)
    sam = SamMissile(S300, f.pos + np.array([10_000.0, 0.0, 0.0]), other)
    w.missiles.append(sam)
    _inject_track(w, sam)
    w._assign_air_threats()
    assert f._evade_threat is None, \
        "a SAM locked on another fighter must not break this one (no cheat)"
