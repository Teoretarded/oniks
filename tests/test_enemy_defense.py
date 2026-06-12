"""sim/enemy_defense.py — destroyer fire control (GL-free, plain pytest).

Coverage (spec §5.2 + integration contract):
  - a hi-lo Oniks at cruise altitude 100 km out is detected over the
    horizon, a track forms after the sustained-detection delay and an SM-2
    launch is drawn (joins world.missiles with the integration flags set);
  - a lo-lo sea-skimmer 100 km out stays under the radar horizon: no
    track, no launch;
  - ammo, the 3 s fire-control reload and the 4-round in-flight cap are
    respected;
  - a dead destroyer launches nothing and its SPY-1 goes dark;
  - the CIWS path kills a tracked leaker: missile dead, impact bookkeeping
    set, burst/kill events forwarded into world.events;
  - sim/damage.py never lets a deck-launched SAM OBB-hit its own ship.

Geometry note: the destroyer anchor reuses the verified open-water spawn
from world/combat.py so Radar.detects' terrain ray crosses deep sea only.
"""

import math

import numpy as np

from sim.arsenal import ONIKS, SM2
from sim.damage import apply_missile_hits
from sim.enemy_defense import (SM2_MAX_INFLIGHT, SM2_MIN_RANGE_M,
                               TRACK_FORM_S, EnemyDefenseController)
from sim.enemy_ships import Destroyer
from sim.missile import PH_CRUISE, Missile
from sim.sam import SamMissile
from sim.ships import ST_SINKING

DT = 1.0 / 120.0
ANCHOR = (-40_000.0, 320_000.0)     # verified open water (world/combat.py)


class _StubWorld:
    """Just what the controller touches: missiles, events, sim_time."""

    def __init__(self):
        self.missiles = []
        self.events = []
        self.sim_time = 0.0


class _ZeroRng:
    """Duck-typed rng whose every kill roll succeeds (Pk > 0 always)."""

    def random(self):
        return 0.0


def _oniks(pos, vel, profile="hi-lo"):
    """A real Missile teleported into mid-cruise (the controller's hostile
    filter is an isinstance check, so stubs would not be seen)."""
    m = Missile(ONIKS, np.array(pos, dtype=np.float64), 0.0, profile,
                np.array([0.0, 0.0, 0.0]))
    m.vel[:] = vel
    m.prev_pos[:] = m.pos
    m.phase = PH_CRUISE
    return m


def _run(ctrl, world, destroyer, seconds):
    """Advance reload timers + controller for ``seconds`` of sim time."""
    for _ in range(int(round(seconds / DT))):
        world.sim_time += DT
        destroyer.update(DT)
        ctrl.step(world, DT)


def _sams(world):
    return [m for m in world.missiles if isinstance(m, SamMissile)]


# ---------------------------------------------------------------------------
# Detection -> SM-2 launch
# ---------------------------------------------------------------------------

def test_hi_oniks_at_100km_draws_sm2_launch():
    d = Destroyer("dd_hi", ANCHOR)
    ctrl = EnemyDefenseController([d])
    w = _StubWorld()
    # 14 km cruise altitude, 100 km south of the ship, closing north.
    w.missiles.append(_oniks((ANCHOR[0], 14_000.0, ANCHOR[1] - 100_000.0),
                             (0.0, 0.0, 680.0)))
    _run(ctrl, w, d, TRACK_FORM_S + 1.0)
    sams = _sams(w)
    assert len(sams) == 1, "tracked hi flyer in envelope must draw a shot"
    sam = sams[0]
    assert sam.weapon is SM2
    assert sam.launch_cinematic is False    # no player time-accel lock
    assert sam.launch_platform is d         # damage.py self-hit exemption
    assert d.sm2_ammo == 23
    assert d.sm2_reload_timer > 0.0
    # The shot rides the contact picture: estimate is near the truth.
    est_pos, est_vel = sam.contact_estimate_fn()
    truth = w.missiles[0].pos
    assert math.hypot(est_pos[0] - truth[0],
                      est_pos[2] - truth[2]) < 2_000.0
    assert est_vel[2] > 0.0


def test_lo_skimmer_at_100km_is_under_the_horizon():
    d = Destroyer("dd_lo", ANCHOR)
    ctrl = EnemyDefenseController([d])
    w = _StubWorld()
    skimmer = _oniks((ANCHOR[0], 15.0, ANCHOR[1] - 100_000.0),
                     (0.0, 0.0, 680.0), profile="lo-lo")
    w.missiles.append(skimmer)
    assert not d.radar.detects(skimmer.pos, "missile")
    _run(ctrl, w, d, 5.0)
    assert _sams(w) == []
    assert d.sm2_ammo == 24


def test_track_needs_sustained_detection():
    """No launch before TRACK_FORM_S of continuous visibility."""
    d = Destroyer("dd_delay", ANCHOR)
    ctrl = EnemyDefenseController([d])
    w = _StubWorld()
    w.missiles.append(_oniks((ANCHOR[0], 14_000.0, ANCHOR[1] - 100_000.0),
                             (0.0, 0.0, 680.0)))
    _run(ctrl, w, d, TRACK_FORM_S - 0.5)
    assert _sams(w) == []


# ---------------------------------------------------------------------------
# Magazine / reload / in-flight caps
# ---------------------------------------------------------------------------

def test_reload_paces_launches():
    """Default 3 s fire-control reload: exactly one round in the first
    4 s (track at ~1.5 s, second shot not before ~4.5 s), two by 5.5 s."""
    d = Destroyer("dd_pace", ANCHOR)
    ctrl = EnemyDefenseController([d])
    w = _StubWorld()
    w.missiles.append(_oniks((ANCHOR[0], 14_000.0, ANCHOR[1] - 100_000.0),
                             (0.0, 0.0, 680.0)))
    _run(ctrl, w, d, 4.0)
    assert len(_sams(w)) == 1
    _run(ctrl, w, d, 1.5)
    assert len(_sams(w)) == 2


def test_ammo_cap_respected():
    d = Destroyer("dd_ammo", ANCHOR, sm2_ammo=2)
    ctrl = EnemyDefenseController([d])
    w = _StubWorld()
    w.missiles.append(_oniks((ANCHOR[0], 14_000.0, ANCHOR[1] - 100_000.0),
                             (0.0, 0.0, 680.0)))
    for _ in range(int(12.0 / DT)):
        w.sim_time += DT
        d.update(DT)
        d.sm2_reload_timer = 0.0        # remove the pacing: ammo is the gate
        ctrl.step(w, DT)
    assert len(_sams(w)) == 2
    assert d.sm2_ammo == 0


def test_inflight_cap_is_four():
    d = Destroyer("dd_cap", ANCHOR)     # 24 rounds available
    ctrl = EnemyDefenseController([d])
    w = _StubWorld()
    w.missiles.append(_oniks((ANCHOR[0], 14_000.0, ANCHOR[1] - 100_000.0),
                             (0.0, 0.0, 680.0)))
    for _ in range(int(10.0 / DT)):
        w.sim_time += DT
        d.update(DT)
        d.sm2_reload_timer = 0.0        # in-flight cap is the only gate
        ctrl.step(w, DT)
    # The launched SAMs are never stepped here, so all stay in flight.
    assert len(_sams(w)) == SM2_MAX_INFLIGHT
    assert d.sm2_ammo == 24 - SM2_MAX_INFLIGHT


def test_dead_destroyer_launches_nothing():
    d = Destroyer("dd_dead", ANCHOR)
    d.state = ST_SINKING
    ctrl = EnemyDefenseController([d])
    w = _StubWorld()
    w.missiles.append(_oniks((ANCHOR[0], 14_000.0, ANCHOR[1] - 100_000.0),
                             (0.0, 0.0, 680.0)))
    _run(ctrl, w, d, 5.0)
    assert _sams(w) == []
    assert d.sm2_ammo == 24
    assert d.radar.alive is False       # sinking ship's SPY-1 is dark


# ---------------------------------------------------------------------------
# CIWS kill path
# ---------------------------------------------------------------------------

def test_ciws_kills_tracked_leaker():
    d = Destroyer("dd_ciws", ANCHOR)
    ctrl = EnemyDefenseController([d], rng=_ZeroRng())
    w = _StubWorld()
    # Leaker 1.2 km out at 60 m, closing — inside the gun, under the SM-2
    # minimum range so the gun is the only defense that may engage.
    assert 1_200.0 < SM2_MIN_RANGE_M
    leaker = _oniks((ANCHOR[0], 60.0, ANCHOR[1] - 1_200.0),
                    (0.0, 0.0, 680.0), profile="lo-lo")
    w.missiles.append(leaker)
    _run(ctrl, w, d, 5.0)
    assert _sams(w) == [], "leaker under SM2_MIN_RANGE_M must not draw SAMs"
    assert leaker.alive is False
    assert leaker.impact_pos is not None        # bookkeeping for effects
    kinds = [k for k, _ in w.events]
    assert "ciws_burst" in kinds
    assert "ciws_kill" in kinds
    kill_pos = next(p for k, p in w.events if k == "ciws_kill")
    assert math.hypot(kill_pos[0] - d.pos[0],
                      kill_pos[2] - d.pos[2]) < 2_500.0
    assert d.ciws_ammo < 1500                   # rounds were spent


def test_ciws_silent_against_untracked_target():
    """Inside 2 km but with no formed track yet, the gun holds fire."""
    d = Destroyer("dd_hold", ANCHOR)
    ctrl = EnemyDefenseController([d], rng=_ZeroRng())
    w = _StubWorld()
    w.missiles.append(_oniks((ANCHOR[0], 60.0, ANCHOR[1] - 1_200.0),
                             (0.0, 0.0, 680.0), profile="lo-lo"))
    _run(ctrl, w, d, TRACK_FORM_S - 0.5)
    assert d.ciws_ammo == 1500
    assert w.events == []


# ---------------------------------------------------------------------------
# Event classification: a mid-air fuse kill is an intercept, not a splash
# ---------------------------------------------------------------------------

def test_interceptor_kill_classifies_as_oniks_intercepted():
    """world.step: a missile that dies with impact_pos None (an interceptor
    fuse killed it mid-air) must emit ("oniks_intercepted", pos) — never a
    splash/ground_hit — and get its impact bookkeeping backfilled."""
    from world.world import WorldState

    class _FuseKilled:
        def __init__(self):
            self.pos = np.array([0.0, 5_000.0, 50_000.0])
            self.prev_pos = self.pos.copy()
            self.vel = np.zeros(3)
            self.alive = True
            self.impact_pos = None

        def update(self, dt, world):
            self.alive = False      # fuse kill: no surface was ever touched

    ws = WorldState()
    stub = _FuseKilled()
    ws.missiles.append(stub)
    ws.step(DT)
    kinds = [k for k, _ in ws.drain_events()]
    assert "oniks_intercepted" in kinds
    assert "splash" not in kinds and "ground_hit" not in kinds
    assert stub.impact_pos is not None


# ---------------------------------------------------------------------------
# Deck launch never self-hits (sim/damage.py exemption)
# ---------------------------------------------------------------------------

def test_deck_launched_sam_exempt_from_own_obb():
    d = Destroyer("dd_self", ANCHOR)
    target = _oniks((ANCHOR[0], 14_000.0, ANCHOR[1] - 100_000.0),
                    (0.0, 0.0, 680.0))
    sam = SamMissile(SM2, d.pos + np.array([0.0, 10.0, 0.0]), target)
    sam.launch_platform = d
    # First eject substeps: the whole swept segment is inside the hull OBB.
    sam.update(DT, type("W", (), {"terrain_height_at":
                                  staticmethod(lambda x, z: -500.0)})())
    events = []
    apply_missile_hits([sam], [d], events)
    assert sam.alive is True
    assert d.hp == 3
    assert events == []
