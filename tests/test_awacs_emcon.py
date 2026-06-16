"""AWACS EMCON (Phase 8): the AWACS is the enemy's widest sensor and, before
this, a free always-on beacon. A smarter AWACS runs SILENT while fleeing an
inbound threat — denying the player's ELINT a live emission to refine and a
radiation-homing terminal an emitter to chase — and re-emits once clear.
Sensor-only/no-cheat: the flee (and thus the silence) is driven by the picture's
missile tracks (sim/commander._defend_awacs), never ground truth."""

import numpy as np

from world.combat import CombatWorld
from world.combat_config import CombatConfig
from sim.commander import AWACS_FLEE_RANGE_M, AWACS_EMCON_DWELL_S


def test_awacs_silent_while_fleeing_then_re_emits():
    w = CombatWorld(CombatConfig(seed=7))
    assert w.awacs.radar.emitting, "AWACS emits by default"
    # Threatened -> the flee order also silences the radar.
    w._execute_commander_order(
        {"type": "awacs_flee", "threat_pos": w.awacs.pos.copy()})
    assert not w.awacs.radar.emitting, \
        "a fleeing AWACS must run silent (deny ELINT refine / radiation homing)"
    # Threat clears -> resume emitting (the fleet needs its widest sensor back).
    w._execute_commander_order({"type": "awacs_resume"})
    assert w.awacs.radar.emitting, "AWACS re-emits once the threat clears"


def test_awacs_emcon_is_sensor_driven_end_to_end():
    """A player missile track within AWACS_FLEE_RANGE_M (fed into the picture)
    makes the commander order the flee, which silences the AWACS — proving the
    silence chains off the SENSOR picture, not truth."""
    w = CombatWorld(CombatConfig(seed=7))
    ax, _, az = w.awacs.pos
    # Inject a missile track 60 km from the AWACS (< AWACS_FLEE_RANGE_M = 100 km).
    pos = np.array([ax, 9_000.0, az - 60_000.0], dtype=np.float64)
    w.commander.picture.update_missile_track(
        "hostile_probe", pos, np.array([0.0, 0.0, 300.0]), sim_time=w.sim_time)
    assert np.hypot(pos[0] - ax, pos[2] - az) < AWACS_FLEE_RANGE_M
    # Tick the commander and execute its orders (one full commander step).
    for order in w.commander.step(w.sim_time, 1.0):
        w._execute_commander_order(order)
    assert not w.awacs.radar.emitting, \
        "commander must silence the AWACS off a sensor missile track within flee range"


def test_awacs_emcon_dwell_prevents_strobe_and_spam():
    """Anti-strobe (SF-1): once silenced, the AWACS holds silent for the dwell
    after the threat track is last seen, instead of un-blinding itself the
    instant its own dark track ages out; and it issues at most ONE flee order
    while a threat persists (no per-tick order spam)."""
    w = CombatWorld(CombatConfig(seed=7))
    cmd = w.commander
    pic = cmd.picture
    ax, _, az = w.awacs.pos
    pos = np.array([ax, 9_000.0, az - 60_000.0], dtype=np.float64)
    pic.update_missile_track("hostile_probe", pos,
                             np.array([0.0, 0.0, 300.0]), sim_time=0.0)

    # First defend tick: enter flee+silent, exactly one flee order.
    cmd.pending_orders.clear()
    cmd._defend_awacs(0.0)
    flee = [o for o in cmd.pending_orders if o["type"] == "awacs_flee"]
    assert len(flee) == 1
    for o in cmd.pending_orders:
        w._execute_commander_order(o)
    assert not w.awacs.radar.emitting

    # Threat still present a tick later: NO second flee order (anti-spam).
    cmd.pending_orders.clear()
    cmd._defend_awacs(1.0)
    assert [o for o in cmd.pending_orders if o["type"] == "awacs_flee"] == []

    # Threat track gone, but WITHIN the dwell -> still silent (no resume).
    pic.missile_tracks.clear()
    cmd.pending_orders.clear()
    cmd._defend_awacs(AWACS_EMCON_DWELL_S * 0.5)
    assert [o for o in cmd.pending_orders if o["type"] == "awacs_resume"] == [], \
        "AWACS must hold silent through the dwell (no self-strobe)"

    # After the dwell, still no threat -> resume.
    cmd.pending_orders.clear()
    cmd._defend_awacs(AWACS_EMCON_DWELL_S + 2.0)
    resume = [o for o in cmd.pending_orders if o["type"] == "awacs_resume"]
    assert len(resume) == 1
    for o in cmd.pending_orders:
        w._execute_commander_order(o)
    assert w.awacs.radar.emitting
