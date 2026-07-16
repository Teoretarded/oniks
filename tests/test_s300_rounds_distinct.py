"""The 48N6 and 40N6 must fly GENUINELY differently (player complaint: they
look identical in-envelope).  Locked contracts, measured off the real
SamMissile flight model (GL-free, deterministic — truth-target flyoff):

  * the 40N6 lofts to a CLEARLY higher apogee than the 48N6 on the same shot,
    while the 48N6 keeps its current medium arc;
  * both rounds still KILL in-envelope (the high loft must not break close
    kills, including a moving target);
  * the 40N6 reaches a target the 48N6 cannot (its longer legs);
  * the 40N6's terminal handover happens AFTER the loft dive is established
    (not at apogee) — the fix for the BUGHUNT 'overshoots/wallows on close
    targets' note: a higher loft handed over at apogee would wallow.

Physics, not dice: every assertion is a measured flight outcome.
"""

import numpy as np

from sim.arsenal import N40N6, S300
from sim.sam import SPH_TERMINAL, SamMissile

DT = 1.0 / 120.0
LAUNCH = np.array([0.0, 5.0, 0.0])


class _World:   # minimal stub: open ocean, no ships (mirrors test_sam.py)
    ships = []

    def terrain_height_at(self, x, z):
        return -50.0


class _StaticTarget:
    def __init__(self, pos):
        self.pos = np.array(pos, dtype=np.float64)
        self.alive = True

    def velocity(self):
        return np.zeros(3)

    def kill(self):
        self.alive = False


class _MovingTarget:
    """Constant-velocity crossing target — exposes the terminal-handover
    geometry that a static target (always killable by a 20 g terminal) hides."""

    def __init__(self, pos, vel):
        self.pos = np.array(pos, dtype=np.float64)
        self.vel = np.array(vel, dtype=np.float64)
        self.alive = True

    def velocity(self):
        return self.vel

    def kill(self):
        self.alive = False

    def update(self, dt):
        self.pos = self.pos + self.vel * dt


def _flyoff(sam_def, target, max_t=320.0, track_update_s=None):
    """Step the real flight model against ``target`` (static or moving) and
    report apogee, closest approach, terminal-handover altitude, outcome."""
    w = _World()
    track_pos = target.pos.copy()
    track_vel = target.velocity().copy()

    def estimate():
        return track_pos.copy(), track_vel.copy()

    m = SamMissile(
        sam_def, LAUNCH.copy(), target,
        contact_estimate_fn=(estimate if track_update_s is not None else None))
    apogee = 0.0
    closest = float("inf")
    handover_alt = None
    altitude_48 = None
    next_track_t = 0.0
    while m.alive and m.t < max_t:
        if hasattr(target, "update"):
            target.update(DT)
        if (track_update_s is not None
                and m.t + 1e-12 >= next_track_t):
            np.copyto(track_pos, target.pos)
            np.copyto(track_vel, target.velocity())
            next_track_t = m.t + track_update_s
        m.update(DT, w)
        if handover_alt is None and m.phase >= SPH_TERMINAL:
            handover_alt = float(m.pos[1])
        apogee = max(apogee, float(m.pos[1]))
        closest = min(closest, float(np.linalg.norm(m.pos - target.pos)))
        if altitude_48 is None and m.t >= 48.0:
            altitude_48 = float(m.pos[1])
    return dict(apogee=apogee, closest=closest, t=m.t,
                killed=m.killed_target, self_destructed=m.self_destructed,
                handover_alt=handover_alt, altitude_48=altitude_48)


# --- the headline: a clearly higher arc ---------------------------------------

def test_40n6_lofts_clearly_higher_than_48n6_in_envelope():
    """Same high in-envelope shot (120 km @ 18 km): the 40N6 climbs much
    higher than the 48N6 — the visible discriminator the player asked for.
    The 48N6 keeps its current medium arc (~32 km)."""
    tgt = [0.0, 18_000.0, 120_000.0]
    r48 = _flyoff(S300, _StaticTarget(tgt))
    r40 = _flyoff(N40N6, _StaticTarget(tgt))
    # 48N6 unchanged medium arc (~32 km).
    assert r48["apogee"] <= 34_000.0, f"48N6 apogee drifted: {r48['apogee']:.0f} m"
    # 40N6 lofts clearly higher — well above the 48N6's medium-arc ceiling.
    assert r40["apogee"] >= 36_000.0, f"40N6 apogee too low: {r40['apogee']:.0f} m"
    # ...and the gap is unmistakable, not the old ~0 m.  This is the real
    # distinctness contract: the player must SEE a meaningfully taller arc.
    assert r40["apogee"] - r48["apogee"] >= 5_000.0, (
        f"arcs too similar: 48N6 {r48['apogee']:.0f} m vs "
        f"40N6 {r40['apogee']:.0f} m")


# --- both still hit in-envelope -----------------------------------------------

def test_both_rounds_kill_high_in_envelope_target():
    tgt = [0.0, 15_000.0, 120_000.0]
    assert _flyoff(S300, _StaticTarget(tgt))["killed"]
    assert _flyoff(N40N6, _StaticTarget(tgt))["killed"]


def test_40n6_kills_close_moving_target_no_overshoot():
    """The raised loft must not make the 40N6 sail past a close high target.
    Moving (300 m/s crossing) at 60 km @ 18 km — a real terminal-geometry
    test, not a sitting duck."""
    r = _flyoff(N40N6, _MovingTarget([0.0, 18_000.0, 60_000.0],
                                     [300.0, 0.0, 0.0]))
    assert r["killed"], f"40N6 overshot the close mover: closest {r['closest']:.0f} m"


# --- the 40N6 reaches where the 48N6 cannot -----------------------------------

def test_40n6_reaches_beyond_48n6_envelope():
    """A 250 km @ 22 km target: the 48N6 dies short (energy self-destruct),
    the 40N6 connects."""
    tgt = [0.0, 22_000.0, 250_000.0]
    r48 = _flyoff(S300, _StaticTarget(tgt))
    r40 = _flyoff(N40N6, _StaticTarget(tgt))
    assert not r48["killed"], "48N6 should NOT reach 250 km"
    assert r48["closest"] > S300.fuse_radius
    assert r40["killed"], f"40N6 should reach 250 km (closest {r40['closest']:.0f} m)"


# --- the overshoot fix: dive established before handover, not at apogee --------

def test_40n6_dive_established_before_terminal_handover():
    """Deep shot (120 km @ 8 km — target well below the loft apogee): the
    40N6 must have begun its dive before terminal PN takes over.  Handing
    over at apogee is the BUGHUNT 'wallow'; the loft must fade outside the
    terminal gate so the dive onto the target is already established."""
    r = _flyoff(N40N6, _StaticTarget([0.0, 8_000.0, 120_000.0]))
    assert r["handover_alt"] is not None, "40N6 never reached terminal"
    assert r["handover_alt"] <= r["apogee"] - 5_000.0, (
        f"40N6 handed over at apogee (wallow): apogee {r['apogee']:.0f} m, "
        f"handover {r['handover_alt']:.0f} m")


def test_40n6_long_crossing_shot_preserves_loft_and_kills():
    """Regression for the live 340 km low-snake trajectory.

    The previous all-infeasible ranking held the round below 1 km at T+48 s
    with ~300 km still to go.  A long crossing shot must retain the online
    balanced-energy loft and remain inside the honest 40N6 envelope.
    """
    target = _MovingTarget([0.0, 6_500.0, 340_000.0],
                           [230.0, 0.0, 0.0])
    r = _flyoff(N40N6, target, max_t=460.0, track_update_s=5.0)
    assert r["killed"], (
        f"40N6 missed 340 km crossing target by {r['closest']:.0f} m")
    assert r["altitude_48"] is not None and r["altitude_48"] >= 20_000.0
    assert 25_000.0 <= r["apogee"] <= 40_000.0
