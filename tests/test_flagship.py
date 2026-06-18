"""M5 Flagship CEC datalink-hub behavior (spec 05 d).

  * flagship ALIVE -> an escort forms an SM-2 track via the flagship/AWACS cue
    BEFORE its OWN SPY-1 has LOS (the launch occurs);
  * flagship DEAD -> the SAME geometry yields NO remote-cued launch (own-sensor
    fallback) AND the surviving escorts' effective TRACK_FORM_S rises;
  * NO-TRUTH: a cue radar that cannot itself detect the target gives no cue
    (the controller reads only the cue radars' detections, never player truth);
  * determinism: a replayed CEC scenario is bit-identical.

Geometry (probe-measured): an escort 60 km from a low (30 m alt) inbound — UNDER
the escort's own SPY-1 horizon (~40-50 km for a 30 m target) but inside its SM-2
envelope — with a flagship 18 km from the threat that DOES hold it.  With the
flagship cue the escort tracks-and-shoots; without it the escort is blind.
"""

import math

import numpy as np
import pytest

from sim.arsenal import ONIKS, SM2
from sim.enemy_defense import ShipDefense, TRACK_FORM_S, SM2_MAX_INFLIGHT
from sim.enemy_ship_classes import Flagship, GeneralDestroyer
from sim.missile import PH_CRUISE, Missile
from sim.sam import SamMissile
from sim.ships import ST_GONE

DT = 1.0 / 120.0
ESC = (-40_000.0, 320_000.0)               # verified open water
ALT = 30.0                                  # above SM2's 25 m floor, very low
THREAT_Z = ESC[1] - 60_000.0               # 60 km south of the escort
THREAT = (ESC[0], ALT, THREAT_Z)
FLAG = (ESC[0], THREAT_Z + 18_000.0)        # 18 km from the threat (it sees it)


class _StubWorld:
    def __init__(self):
        self.missiles = []
        self.events = []
        self.sim_time = 0.0


def _oniks(pos, vel):
    m = Missile(ONIKS, np.array(pos, dtype=np.float64), 0.0, "lo-lo",
                np.array([0.0, 0.0, 0.0]))
    m.vel[:] = vel
    m.prev_pos[:] = m.pos
    m.phase = PH_CRUISE
    return m


def _sams(world):
    return [m for m in world.missiles
            if isinstance(m, SamMissile) and m.weapon is SM2]


def _run_cec(flag_alive, seed=0, hold=TRACK_FORM_S + 1.0):
    """Run the escort's fire control for ``hold`` s of a near-stationary low
    inbound it cannot see, with a flagship cue that is live iff ``flag_alive``.
    Returns (n_sams, world)."""
    esc = GeneralDestroyer("esc", ESC)
    flag = Flagship("flag", FLAG)
    if not flag_alive:
        flag.state = ST_GONE
    w = _StubWorld()
    # ~stationary so the target stays low + in-band for the whole window.
    w.missiles.append(_oniks(THREAT, (0.0, 0.0, 5.0)))
    cue = lambda: [flag.radar] if flag.alive else []   # noqa: E731
    sd = ShipDefense(esc, np.random.default_rng(seed), cue_radars_fn=cue)
    for _ in range(int(round(hold / DT))):
        w.sim_time += DT
        esc.update(DT)
        flag.update(DT)
        sd.step(w, DT)
    return len(_sams(w)), w, esc, flag


# ---------------------------------------------------------------------------
# 1. Escort's own SPY-1 is blind to this geometry (the cue is load-bearing)
# ---------------------------------------------------------------------------

def test_escort_own_radar_cannot_see_but_flagship_can():
    esc = GeneralDestroyer("esc", ESC)
    flag = Flagship("flag", FLAG)
    assert not esc.radar.detects(np.array(THREAT), "missile"), (
        "geometry invalid: the escort must NOT see the threat on its own")
    assert flag.radar.detects(np.array(THREAT), "missile"), (
        "geometry invalid: the flagship must hold the threat")


# ---------------------------------------------------------------------------
# 2. ALIVE flagship -> remote-cued launch; DEAD flagship -> no launch
# ---------------------------------------------------------------------------

def test_alive_flagship_cue_enables_escort_launch():
    n, _w, _esc, _flag = _run_cec(flag_alive=True)
    assert n == 1, "an escort must launch on the flagship's remote cue"


def test_dead_flagship_no_remote_cued_launch():
    n, _w, _esc, _flag = _run_cec(flag_alive=False)
    assert n == 0, ("with the flagship dead the escort falls back to its own "
                    "SPY-1, which has no LOS -> no launch")


# ---------------------------------------------------------------------------
# 3. NO-TRUTH: a cue radar that cannot detect the target gives no cue
# ---------------------------------------------------------------------------

def test_no_truth_cue_radar_blind_means_no_cue():
    """Mock the geometry so the cue radar ALSO cannot detect the target (place
    the 'flagship' as far from the threat as the escort).  The controller reads
    only the cue radars' detections, never the player's truth, so a blind cue
    yields no track and no launch."""
    esc = GeneralDestroyer("esc", ESC)
    blind_flag = Flagship("blind", ESC)        # co-located with the escort:
    #                                            same blind horizon as the escort
    assert not blind_flag.radar.detects(np.array(THREAT), "missile")
    w = _StubWorld()
    w.missiles.append(_oniks(THREAT, (0.0, 0.0, 5.0)))
    cue = lambda: [blind_flag.radar]           # noqa: E731
    sd = ShipDefense(esc, np.random.default_rng(0), cue_radars_fn=cue)
    for _ in range(int(round((TRACK_FORM_S + 1.0) / DT))):
        w.sim_time += DT
        esc.update(DT)
        blind_flag.update(DT)
        sd.step(w, DT)
    assert _sams(w) == [], "a cue radar that cannot SEE the target must not cue"


# ---------------------------------------------------------------------------
# 4. Determinism: a replayed CEC scenario is bit-identical
# ---------------------------------------------------------------------------

def test_cec_launch_is_deterministic():
    n1, w1, _e1, _f1 = _run_cec(flag_alive=True, seed=12345)
    n2, w2, _e2, _f2 = _run_cec(flag_alive=True, seed=12345)
    assert n1 == n2 == 1
    p1 = _sams(w1)[0].pos
    p2 = _sams(w2)[0].pos
    assert np.array_equal(p1, p2), "same seed must replay the SM-2 bit-identical"


# ---------------------------------------------------------------------------
# 5. World-level: flagship death raises escort TRACK_FORM_S + emits the event
# ---------------------------------------------------------------------------

def test_world_flagship_death_degrades_cohesion_and_emits_event():
    """The world latches the flagship alive->dead edge: the surviving escorts'
    per-unit _track_form_s rises above the default (cohesion loss) and a
    'datalink_degraded' event fires EXACTLY once."""
    from world.combat import CombatWorld, FLAGSHIP_DEAD_COHESION_FACTOR
    from world.combat_config import CombatConfig

    cw = CombatWorld(CombatConfig(seed=1337, n_destroyers=3, n_flagship=1))
    assert cw.flagship is not None
    escorts = [s for s in cw.ships
               if getattr(s, "ship_class_role", None) in
               ("general", "air_defense", "ground_attack")]
    assert escorts, "expected escorts to degrade"
    # Before death: every escort is on the default delay.
    for s in escorts:
        assert s._track_form_s == pytest.approx(TRACK_FORM_S)

    # Kill the flagship; step once so defense.step clears its radar and the
    # edge check fires.
    cw.flagship.state = ST_GONE
    n_events_before = len(cw.events)
    cw.step(DT)

    expected = TRACK_FORM_S * FLAGSHIP_DEAD_COHESION_FACTOR
    for s in escorts:
        assert s._track_form_s == pytest.approx(expected), (
            f"escort {s.ship_id} cohesion not degraded")
    degraded = [e for e in cw.events[n_events_before:]
                if e[0] == "datalink_degraded"]
    assert len(degraded) == 1, "datalink_degraded must fire exactly once"

    # Idempotent: another step does NOT re-fire the event or re-bump.
    n2 = len(cw.events)
    cw.step(DT)
    again = [e for e in cw.events[n2:] if e[0] == "datalink_degraded"]
    assert again == [], "the degradation edge must fire only once"


def test_world_flagship_radar_drops_from_cue_set_on_death():
    """SENSOR-honest: the live flagship's SPY-1 is in the escorts' cue set; a
    dead flagship's radar drops out (it fails the alive gate)."""
    from world.combat import CombatWorld
    from world.combat_config import CombatConfig

    cw = CombatWorld(CombatConfig(seed=1337, n_destroyers=2, n_flagship=1))
    assert cw.flagship.radar in cw._enemy_cue_radars()
    cw.flagship.state = ST_GONE
    cw.step(DT)   # defense.step clears the sunk flagship's radar.alive
    assert cw.flagship.radar not in cw._enemy_cue_radars()


def test_default_world_has_no_flagship_and_no_degradation():
    """Byte-identical guard: the default fleet has no flagship, so the CEC
    machinery is fully inert (no event, no cohesion change ever)."""
    from world.combat import CombatWorld
    from world.combat_config import CombatConfig

    cw = CombatWorld(CombatConfig())
    assert cw.flagship is None
    for _ in range(60):
        cw.step(DT)
    assert not any(e[0] == "datalink_degraded" for e in cw.events)
    for s in cw.ships:
        if hasattr(s, "_track_form_s"):
            assert s._track_form_s == pytest.approx(TRACK_FORM_S)
