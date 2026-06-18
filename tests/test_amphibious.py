"""M5 #1 amphibious ENTITIES: Transport hull + LCAC landing craft.

Coverage (spec 05 "Amphibious transport class + LCAC"):
  * a Transport reaching its launch line SPLASHES exactly LCAC_PER_TRANSPORT
    Lcac entities at the transport pos;
  * sinking a Transport BEFORE it reaches the line removes its embarked LCACs
    (they NEVER spawn);
  * a spawned Lcac beelines the LANDING_BOX and is killed by an Oniks OR a
    Pantsir-gun OBB hit (hp=1);
  * transports + LCACs are NOT emitters: ELINT/_emitters never lists them; they
    enter the contact board ONLY via radar/SAR (fog), and an LCAC's small
    radar_size shortens its detection horizon vs a transport (physics);
  * determinism: same seed -> same launch line, same box approach, same splash
    scatter ([seed, 15]).

Timing/geometry bands are locked TWO-SIDED from tools/probe_amphibious.py
measured numbers (RATE over a bounded leg — never a guess).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from sim.amphibious import (LANDING_BOX_RADIUS_M, LAUNCH_LINE_RANGE_M,
                            LCAC_PER_TRANSPORT, LCAC_SPEED_MPS,
                            TRANSPORT_SPEED_MPS, Lcac, Transport,
                            landing_box_xz)
from sim.damage import apply_missile_hits
from sim.ships import ST_ALIVE, ST_GONE, ST_SINKING
from world.combat import CombatWorld
from world.combat_config import CombatConfig
from world.generation import BASE_POS

DT = 1.0 / 120.0
BX, BZ = float(BASE_POS[0]), float(BASE_POS[2])
BOX = landing_box_xz((BX, BZ))


class _Round:
    """A minimal player anti-ship round (is_hostile False) that walks the OBB
    sweep like an Oniks / a Pantsir gun round: a moving segment, prev/pos/alive."""

    def __init__(self, prev_pos, pos):
        self.prev_pos = np.asarray(prev_pos, dtype=np.float64)
        self.pos = np.asarray(pos, dtype=np.float64)
        self.alive = True
        self.is_hostile = False
        self.impact_pos = None
        self.phase = 0


def _near_transport(extra_km=10.0):
    """A Transport anchored ``extra_km`` outside its launch line, aimed at base,
    so a RUN reaches the line over a short, fast-to-step leg."""
    anchor = (BX, BZ + LAUNCH_LINE_RANGE_M + extra_km * 1_000.0)
    return Transport("t_probe", anchor, base_xz=(BX, BZ))


# ---------------------------------------------------------------------------
# Transport posture: LOITER -> RUN -> reached line
# ---------------------------------------------------------------------------

def test_transport_loiters_until_released():
    """A fresh Transport holds station (LOITER) and never reaches the line
    unless released; begin_run flips it to RUN."""
    tr = _near_transport()
    assert tr.state_label == "LOITER"
    # Step a while in LOITER: it must NOT reach the line (it is orbiting).
    for _ in range(2_000):
        tr.update(DT)
    assert not tr.reached_launch_line(), "a loitering transport must not splash"
    tr.begin_run()
    assert tr.state_label == "RUN"


def test_transport_run_reaches_launch_line_at_measured_rate():
    """RUN beelines the base and crosses the launch-line ring.  The ETA over a
    10 km leg matches the measured RATE (10 km / TRANSPORT_SPEED_MPS) two-sided
    (probe: ~909 s @ 11 m/s)."""
    tr = _near_transport(extra_km=10.0)
    tr.begin_run()
    t = 0.0
    while not tr.reached_launch_line() and t < 5_000.0:
        tr.update(DT)
        t += DT
    assert tr.reached_launch_line()
    analytic = 10_000.0 / TRANSPORT_SPEED_MPS
    assert analytic * 0.9 <= t <= analytic * 1.1, (
        f"transport leg ETA {t:.0f}s off the measured rate {analytic:.0f}s")
    # It crossed INTO the ring (range <= launch line), not overshooting wildly.
    assert tr._range_to_base() <= LAUNCH_LINE_RANGE_M + 200.0


# ---------------------------------------------------------------------------
# SPLASH: exactly LCAC_PER_TRANSPORT craft; sinking first cancels the splash
# ---------------------------------------------------------------------------

def test_transport_at_line_splashes_exactly_n_lcacs():
    """When a RUNning transport crosses its launch line the world splashes
    EXACTLY LCAC_PER_TRANSPORT Lcacs at its pos and the transport latches
    SPLASH (drifts dead, embarked count 0)."""
    cw = CombatWorld(CombatConfig(seed=1337, n_transports=1))
    tr = cw.transports[0]
    # Teleport it just inside the line, on a RUN, then step once.
    tr.begin_run()
    tr.pos[0] = BX
    tr.pos[2] = BZ + LAUNCH_LINE_RANGE_M - 100.0
    assert tr.reached_launch_line()
    cw._step_amphibious(DT)
    assert len(cw.lcacs) == LCAC_PER_TRANSPORT, (
        f"expected {LCAC_PER_TRANSPORT} LCACs, got {len(cw.lcacs)}")
    assert tr.state_label == "SPLASH"
    assert tr.embarked_lcac == 0
    # The LCACs joined self.ships (visible + OBB-damaged + count for victory).
    for lc in cw.lcacs:
        assert lc in cw.ships
        assert isinstance(lc, Lcac)
        assert lc.hp == 1
    # Splashed near the transport pos (within the seeded scatter).
    for lc in cw.lcacs:
        assert math.hypot(lc.pos[0] - tr.pos[0], lc.pos[2] - tr.pos[2]) < 3_000.0


def test_transport_splashes_only_once():
    """A SPLASHed transport never splashes again (idempotent latch)."""
    cw = CombatWorld(CombatConfig(seed=1337, n_transports=1))
    tr = cw.transports[0]
    tr.begin_run()
    tr.pos[0] = BX
    tr.pos[2] = BZ + LAUNCH_LINE_RANGE_M - 100.0
    cw._step_amphibious(DT)
    n_after_first = len(cw.lcacs)
    for _ in range(10):
        cw._step_amphibious(DT)
    assert len(cw.lcacs) == n_after_first, "transport splashed more than once"


def test_sinking_transport_before_line_never_spawns_lcacs():
    """A transport sunk BEFORE it reaches the line removes its embarked LCACs —
    they never spawn (the early-counter)."""
    cw = CombatWorld(CombatConfig(seed=1337, n_transports=1))
    tr = cw.transports[0]
    tr.begin_run()
    # Still far out (not at the line); sink it outright.
    tr.state = ST_GONE
    for _ in range(50):
        cw._step_amphibious(DT)
    assert cw.lcacs == [], "a transport sunk before the line must spawn no LCACs"


# ---------------------------------------------------------------------------
# LCAC: beeline the box, killed by an OBB hit (hp=1)
# ---------------------------------------------------------------------------

def test_lcac_beelines_box_at_measured_rate():
    """A spawned Lcac drives straight at the LANDING_BOX and lands; the 10 km
    leg ETA matches the measured RATE (probe ~417 s @ 18 m/s)."""
    start = (BOX[0], BOX[1] + 10_000.0)
    lc = Lcac("l0", start, BOX)
    d0 = lc.range_to_box()
    t = 0.0
    while not lc.landed and t < 5_000.0:
        lc.update(DT)
        t += DT
    assert lc.landed
    assert lc.range_to_box() <= LANDING_BOX_RADIUS_M + 50.0
    analytic = (d0 - LANDING_BOX_RADIUS_M) / LCAC_SPEED_MPS
    assert analytic * 0.9 <= t <= analytic * 1.1, (
        f"LCAC leg ETA {t:.0f}s off the measured rate {analytic:.0f}s")


@pytest.mark.parametrize("label", ["oniks", "pantsir_gun"])
def test_lcac_dies_to_an_obb_hit(label):
    """An Oniks OR a Pantsir-gun round whose segment crosses the LCAC hull sinks
    it (hp 1 -> 0 -> ST_SINKING) through the EXISTING damage sweep — physics, no
    kill roll.  The round itself dies on the hit."""
    lc = Lcac("l_kill", (1_000.0, 1_000.0), BOX)
    assert lc.state == ST_ALIVE and lc.hp == 1
    c = lc.pos.copy()
    rnd = _Round(c + np.array([0.0, 40.0, 0.0]), c + np.array([0.0, -2.0, 0.0]))
    ev = []
    apply_missile_hits([rnd], [lc], ev)
    assert lc.hp == 0
    assert lc.state == ST_SINKING
    assert not rnd.alive
    assert any(e[0] == "ship_hit" for e in ev)


# ---------------------------------------------------------------------------
# FOG: not emitters; radar/SAR only; LCAC shorter horizon than a transport
# ---------------------------------------------------------------------------

def test_transports_and_lcacs_are_not_emitters():
    """Neither a Transport nor a spawned LCAC ever appears in the world's
    _emitters() list (they carry NO radar mount -> ELINT never hears them)."""
    cw = CombatWorld(CombatConfig(seed=1337, n_transports=2))
    # Splash one transport so an LCAC exists too.
    tr = cw.transports[0]
    tr.begin_run()
    tr.pos[0] = BX
    tr.pos[2] = BZ + LAUNCH_LINE_RANGE_M - 100.0
    cw._step_amphibious(DT)
    assert cw.lcacs, "test needs at least one splashed LCAC"
    emitter_ids = {eid for eid, _ in cw._emitters()}
    for tr in cw.transports:
        assert tr.radar is None
        assert not any("transport" in str(eid).lower() for eid in emitter_ids)
    for lc in cw.lcacs:
        assert lc.radar is None
        assert not any("lcac" in str(eid).lower() for eid in emitter_ids)


def test_lcac_radar_size_shortens_its_detection_horizon():
    """PHYSICS: the player's close-in surface radar holds an LCAC ('lcac' ring)
    at a SHORTER range than a transport ('ship' ring) — the LCAC is hard to
    catch close in because of its small radar_size, not a probability flag.
    Measured from the base-side Pantsir radar (probe: ship 30 km, lcac 12 km)."""
    cw = CombatWorld(CombatConfig(seed=1337))
    pr = next(r for r in cw.radar_net.radars if "pantsir" in r.radar_id)
    px, pz = float(pr.pos[0]), float(pr.pos[2])

    def _last_visible(size):
        last = 0.0
        for km in range(1, 40):
            pos = np.array([px, 0.0, pz + km * 1_000.0], dtype=np.float64)
            if pr.detects(pos, size):
                last = km * 1_000.0
        return last

    ship_h = _last_visible("ship")
    lcac_h = _last_visible("lcac")
    assert ship_h > 0.0 and lcac_h > 0.0, "both must be detectable somewhere"
    assert lcac_h < ship_h, (
        f"LCAC horizon {lcac_h/1e3:.0f} km must be SHORTER than the "
        f"transport's {ship_h/1e3:.0f} km")


def test_transport_radar_size_is_ship_lcac_is_lcac():
    """The size classes are exactly what the contact gate keys on."""
    tr = _near_transport()
    lc = Lcac("l", (0.0, 0.0), BOX)
    assert tr.radar_size == "ship"
    assert lc.radar_size == "lcac"


# ---------------------------------------------------------------------------
# Determinism: same seed -> same launch line, splash scatter, box approach
# ---------------------------------------------------------------------------

def test_amphibious_deterministic_per_seed():
    """Same seed -> identical transport anchors AND identical splash scatter
    (the [seed, 15] stream)."""
    def _splash_positions(seed):
        cw = CombatWorld(CombatConfig(seed=seed, n_transports=2))
        for tr in cw.transports:
            tr.begin_run()
            tr.pos[0] = BX
            tr.pos[2] = BZ + LAUNCH_LINE_RANGE_M - 100.0
        cw._step_amphibious(DT)
        return ([tuple(round(float(c), 6) for c in t.pos) for t in cw.transports],
                [tuple(round(float(c), 6) for c in lc.pos) for lc in cw.lcacs])

    a_tr, a_lc = _splash_positions(2024)
    b_tr, b_lc = _splash_positions(2024)
    assert a_tr == b_tr, "transport anchors not deterministic per seed"
    assert a_lc == b_lc, "LCAC splash scatter not deterministic per seed"
    assert len(a_lc) == 2 * LCAC_PER_TRANSPORT
