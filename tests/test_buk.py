"""M5 Buk mid-SAM: the two SamDefs (9M317 long reach + 9M338 agile) and the
two-round-distinct flyoff (mirror of tests/test_s300_rounds_distinct.py).

The Buk fills the Pantsir(20km) <-> S-300(150km) gap with a medium-range TEL
carrying two rounds:
  * 9M317 (BUK_LONG)  — long reach (~70 km), medium loft, ~24 g;
  * 9M338 (BUK_AGILE) — agile sprint (~40 km), high g (~50), tight fuse.

CONTRACT (def-level, ordering — locked at write time, NOT measured):
  * 9M338 max_g > 9M317 max_g  (the agile round turns harder);
  * 9M317 max_range > 9M338 max_range  (the long round reaches farther);
  * both engage LOW (no 40N6-style 4 km floor).

DISTINCT (flyoff, MEASURED — physics not dice, every band is a measured flight
outcome reported by tools/probe_buk_rounds.py before it was locked here):
  * the agile 9M338 achieves a SMALLER miss vs a maneuvering target than the
    long 9M317 fired at the same crossing target;
  * the long 9M317 KILLS a target BEYOND the 9M338's range.
"""

import numpy as np

from sim.arsenal import BUK_AGILE, BUK_LONG, BUK_TEL
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
    geometry that a static target (always killable by a high-g terminal)
    hides."""

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


def _flyoff(sam_def, target, max_t=200.0):
    """Step the real flight model against ``target`` and report apogee,
    closest approach, terminal-handover altitude, outcome."""
    w = _World()
    m = SamMissile(sam_def, LAUNCH.copy(), target)
    apogee = 0.0
    closest = float("inf")
    handover_alt = None
    while m.alive and m.t < max_t:
        if hasattr(target, "update"):
            target.update(DT)
        m.update(DT, w)
        if handover_alt is None and m.phase >= SPH_TERMINAL:
            handover_alt = float(m.pos[1])
        apogee = max(apogee, float(m.pos[1]))
        closest = min(closest, float(np.linalg.norm(m.pos - target.pos)))
    return dict(apogee=apogee, closest=closest, t=m.t,
                killed=m.killed_target, self_destructed=m.self_destructed,
                handover_alt=handover_alt)


# --- def-level ordering contracts ---------------------------------------------

def test_both_buk_defs_physically_ordered_positive():
    """Every physical field on both rounds is positive (a SamMissile built from
    a zero/negative field would not integrate)."""
    for sd in (BUK_LONG, BUK_AGILE):
        assert sd.length > 0 and sd.diameter > 0
        assert sd.launch_mass > 0 and sd.propellant_mass > 0
        assert sd.propellant_mass < sd.launch_mass
        assert sd.motor_thrust > 0 and sd.motor_time > 0 and sd.isp > 0
        assert sd.ref_area > 0
        assert sd.max_g > 0 and sd.fuse_radius > 0
        assert 0 < sd.terminal_range < sd.max_range
        assert sd.self_destruct_t > 0 and sd.self_destruct_speed > 0
        assert sd.min_intercept_alt < sd.max_intercept_alt


def test_9m338_turns_harder_than_9m317():
    """The agile sprint round has the higher lateral-g ceiling (the CONTRACT
    discriminator: 9M338 max_g > 9M317 max_g)."""
    assert BUK_AGILE.max_g > BUK_LONG.max_g


def test_9m317_reaches_farther_than_9m338():
    """The long round has the bigger guided envelope (9M317 max_range >
    9M338 max_range)."""
    assert BUK_LONG.max_range > BUK_AGILE.max_range


def test_both_buk_rounds_engage_low_no_4km_floor():
    """Unlike the 40N6 (4 km active-seeker floor), BOTH Buk rounds engage low
    targets — the medium-SAM gap-filler must catch sea-skimmers and low
    movers.  Floors well under 100 m (the 48N6's floor), no 4 km gate."""
    assert BUK_LONG.min_intercept_alt < 100.0
    assert BUK_AGILE.min_intercept_alt < 100.0
    # explicitly NOT the 40N6's high floor
    assert BUK_LONG.min_intercept_alt < 4_000.0
    assert BUK_AGILE.min_intercept_alt < 4_000.0


def test_buk_tel_launcher_def():
    """BUK_TEL carries BOTH rounds on one TEL (the 9A317-class self-propelled
    launcher), with a positive tube count and ammo."""
    assert "buk_9m317" in BUK_TEL.weapon_ids
    assert "buk_9m338" in BUK_TEL.weapon_ids
    assert BUK_TEL.tubes >= 1
    assert BUK_TEL.reload_s > 0


# --- the headline: both rounds in their own envelope --------------------------

def test_both_buk_rounds_kill_in_their_own_envelope():
    """A close in-envelope shot (30 km @ 6 km): BOTH rounds kill a static
    target.  (Confirms the airframes guide+fuse honestly; the distinct bands
    are measured below.)"""
    tgt = [0.0, 6_000.0, 30_000.0]
    assert _flyoff(BUK_LONG, _StaticTarget(tgt))["killed"]
    assert _flyoff(BUK_AGILE, _StaticTarget(tgt))["killed"]


# --- DISTINCT (1): the agile round beats the long one on a hard close crosser -

def test_9m338_kills_hard_close_crosser_that_9m317_misses():
    """A fast crossing target at CLOSE range (12 km @ 4 km, 400 m/s crossing) —
    the terminal turn is tight, so the 24 g long 9M317 cannot pull the corner
    and sails past, while the 50 g agile 9M338 makes the turn and kills.  This
    is the agility discriminator the high max_g buys, EMERGING from the physics
    (no kill roll).  MEASURED band (tools/probe_buk_rounds.py + the close-crosser
    sweep): 9M338 closest ~7 m (KILL), 9M317 closest ~3 km (clean miss)."""
    cross = ([0.0, 4_000.0, 12_000.0], [400.0, 0.0, 0.0])
    r_long = _flyoff(BUK_LONG, _MovingTarget(*cross))
    r_agile = _flyoff(BUK_AGILE, _MovingTarget(*cross))
    assert r_agile["killed"], (
        f"9M338 should kill the hard close crosser "
        f"(closest {r_agile['closest']:.0f} m)")
    assert not r_long["killed"], (
        f"9M317 (24 g) should NOT pull the tight close corner "
        f"(closest {r_long['closest']:.0f} m)")
    # The agile round's miss is far tighter — the unmistakable distinctness.
    assert r_agile["closest"] < r_long["closest"], (
        f"9M338 miss {r_agile['closest']:.0f} m not tighter than "
        f"9M317 {r_long['closest']:.0f} m")


# --- DISTINCT (2): the long round reaches where the agile one cannot ----------

def test_9m317_kills_beyond_9m338_range():
    """A target BEYOND the 9M338's reach (60 km @ 8 km): the long 9M317
    connects, the agile 9M338 dies short (energy self-destruct / falls short).
    MEASURED band (tools/probe_buk_rounds.py)."""
    tgt = [0.0, 8_000.0, 60_000.0]
    r_long = _flyoff(BUK_LONG, _StaticTarget(tgt))
    r_agile = _flyoff(BUK_AGILE, _StaticTarget(tgt))
    assert r_long["killed"], (
        f"9M317 should reach 60 km (closest {r_long['closest']:.0f} m)")
    assert not r_agile["killed"], "9M338 should NOT reach 60 km"
    assert r_agile["closest"] > BUK_AGILE.fuse_radius
