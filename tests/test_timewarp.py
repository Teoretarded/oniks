"""AUTO-TIME-WARP (M6) — pure TimeWarpDirector + the fog-safe drop predicates.

Headless: the director is pure (no pygame/GL) and the drop predicates take a
duck-typed fake world, so the whole feature is unit-testable without a window.

Contracts under test (spec 07 §AUTO-TIME-WARP test contracts):
  (a) target 8x, no drop -> settles at 8x after the ramp;
  (b) drop_active -> eases to 1x within the ramp AND stays (dwell) >= 1 s after
      the drop clears (debounce so a flickering horizon track can't strobe);
  (c) ramp-back reaches the target within ~1.5 s;
  (d) launch lock still forces 1x (regression: launch_realtime_lock unchanged);
  (e) FOG-OF-WAR (LOAD-BEARING): an UNDETECTED hostile (in world.missiles,
      is_hostile, absent from _strike_board / contacts.tracks) does NOT trigger
      inbound_detected -> no drop;
  (f) DETERMINISM: warp is a pure multiplier on accumulated sim time, so the
      same seed stepped to the same sim_time at 1x vs 8x pacing yields identical
      commander / back-plot state.
"""

import numpy as np
import pytest

from game.timewarp import (DWELL_S, RAMP_S, TimeWarpDirector, drop_cause,
                           event_drop, inbound_detected, intercept_window,
                           own_terminal)


# --------------------------------------------------------------- pure director

def _settle(director, target, drop=False, dt=1 / 60.0, t_max=6.0):
    """Tick the director with a fixed (target, drop) until it converges or
    t_max real seconds elapse; return the final effective scale."""
    eff = director.tick(dt, target, drop)
    t = 0.0
    while t < t_max:
        eff = director.tick(dt, target, drop)
        t += dt
    return eff


def test_idle_no_drop_settles_at_target():
    # (a) target 8x with no drop -> returns 8x after the ramp settles.
    d = TimeWarpDirector()
    assert _settle(d, 8.0, drop=False) == pytest.approx(8.0, abs=1e-3)


def test_target_1x_is_immediate():
    # Degenerate target == 1x: nothing to ramp, effective stays 1x.
    d = TimeWarpDirector()
    assert d.tick(1 / 60.0, 1.0, False) == pytest.approx(1.0, abs=1e-6)


def test_drop_eases_to_1x_within_the_ramp():
    # (b) part 1: a sustained drop eases the effective scale down to 1x within
    # the ramp window (RAMP_S covers an 8x span; give it generous slack).
    d = TimeWarpDirector()
    _settle(d, 8.0, drop=False)                 # parked at 8x
    eff = d.tick(1 / 60.0, 8.0, True)
    t = 0.0
    dt = 1 / 60.0
    while t < RAMP_S * 2:
        eff = d.tick(dt, 8.0, True)
        t += dt
    assert eff == pytest.approx(1.0, abs=1e-3)


def test_drop_holds_1x_through_dwell_after_clear():
    # (b) part 2: after the drop clears the warp stays at 1x for the real-time
    # DWELL (>= 1 s) before it is allowed to ramp back (debounce).
    d = TimeWarpDirector()
    _settle(d, 8.0, drop=False)
    _settle(d, 8.0, drop=True)                  # down to 1x, drop held
    assert d.tick(1 / 60.0, 8.0, False) == pytest.approx(1.0, abs=1e-3)
    # Tick through just UNDER the dwell with the drop now CLEAR: still 1x.
    dt = 1 / 60.0
    t = 0.0
    eff = 1.0
    while t < DWELL_S - 4 * dt:                  # stop safely short of the edge
        eff = d.tick(dt, 8.0, False)
        t += dt
    assert eff == pytest.approx(1.0, abs=1e-3), "must hold 1x through the dwell"
    assert DWELL_S >= 1.0                        # the contract minimum


def test_ramp_back_reaches_target_after_dwell():
    # (c) once the dwell expires the warp eases back and reaches the target
    # within ~RAMP_S of ramp time.
    d = TimeWarpDirector()
    _settle(d, 8.0, drop=False)
    _settle(d, 8.0, drop=True)
    # Clear the drop and run past dwell + ramp.
    eff = _settle(d, 8.0, drop=False, t_max=DWELL_S + RAMP_S * 2)
    assert eff == pytest.approx(8.0, abs=1e-3)


def test_ramp_back_timing_within_one_and_a_half_seconds():
    # (c) timing: measured ramp-back of an 8x step completes within ~1.5 s of
    # sim ticks once the dwell has elapsed (RAMP_S is the nominal ramp).
    d = TimeWarpDirector()
    _settle(d, 8.0, drop=False)
    _settle(d, 8.0, drop=True)
    dt = 1 / 60.0
    # Burn the dwell first (drop clear).
    t = 0.0
    while t < DWELL_S + dt:
        d.tick(dt, 8.0, False)
        t += dt
    # Now time the ramp-back.
    t = 0.0
    eff = d.tick(dt, 8.0, False)
    while eff < 8.0 - 1e-3 and t < 5.0:
        eff = d.tick(dt, 8.0, False)
        t += dt
    assert t <= RAMP_S + 0.2, f"ramp-back took {t:.2f}s (RAMP_S={RAMP_S})"


def test_manual_target_change_during_ramp_is_followed():
    # The player retains manual override: lowering the target mid-ramp eases to
    # the NEW target, never overshooting the old one.
    d = TimeWarpDirector()
    _settle(d, 16.0, drop=False)
    eff = _settle(d, 2.0, drop=False)
    assert eff == pytest.approx(2.0, abs=1e-3)


# ----------------------------------------------------------- fog-safe predicates

class _Missile:
    def __init__(self, aircraft_id="m0", is_hostile=False, phase_label="CRUISE",
                 alive=True):
        self.aircraft_id = aircraft_id
        self.is_hostile = is_hostile
        self.phase_label = phase_label
        self.alive = alive


class _SamMissile:
    """A friendly SAM round (no is_hostile attr — getattr falls back False)."""

    def __init__(self, phase_label="MIDCOURSE", alive=True):
        self.phase_label = phase_label
        self.alive = alive


class _FakeContacts:
    def __init__(self, tracks=None):
        self.tracks = tracks if tracks is not None else {}


class _FakeWorld:
    def __init__(self, missiles=None, strike_board=None, tracks=None,
                 pantsirs=None):
        self.missiles = missiles if missiles is not None else []
        self._strike_board = strike_board if strike_board is not None else {}
        self.contacts = _FakeContacts(tracks)
        self.pantsirs = pantsirs if pantsirs is not None else []


def test_inbound_detected_true_only_when_radar_holds_the_strike():
    # A hostile strike round that the player's radar HOLDS (its id is in BOTH
    # the strike board AND contacts.tracks with is_air) drops the warp.
    hostile = _Missile(aircraft_id="tlam0", is_hostile=True)
    w = _FakeWorld(
        missiles=[hostile],
        strike_board={"tlam0": hostile},
        tracks={"tlam0": dict(is_air=True, pos=np.zeros(3))})
    assert inbound_detected(w)
    assert event_drop(w)


def test_inbound_undetected_hostile_does_not_drop_FOG_LOAD_BEARING():
    # (e) LOAD-BEARING FOG TEST: a sea-skimming Tomahawk under the horizon —
    # is_hostile, alive, in world.missiles, in the strike board (the world
    # knows it exists) — but NOT in contacts.tracks (the radar has not detected
    # it).  inbound_detected MUST stay False or the auto-warp leaks the threat.
    undetected = _Missile(aircraft_id="tlam_lo", is_hostile=True)
    w = _FakeWorld(
        missiles=[undetected],
        strike_board={"tlam_lo": undetected},   # world truth knows it
        tracks={})                              # radar does NOT hold it
    assert not inbound_detected(w)
    assert not event_drop(w)


def test_inbound_ignores_non_air_and_non_strike_tracks():
    # A surface ship track (is_air False) and a player-launched air track whose
    # id is NOT a hostile strike must not trigger inbound_detected.
    hostile = _Missile(aircraft_id="h0", is_hostile=True)
    w = _FakeWorld(
        missiles=[hostile],
        strike_board={"h0": hostile},
        tracks={
            "h0": dict(is_air=False),            # surface contact -> no drop
            "own_round": dict(is_air=True),      # air, but not a strike id
        })
    assert not inbound_detected(w)


def test_own_terminal_true_for_player_round_in_terminal():
    # (own-round, truth OK): a player (NOT hostile) Missile in TERMINAL drops.
    w = _FakeWorld(missiles=[_Missile(phase_label="TERMINAL", is_hostile=False)])
    assert own_terminal(w)
    assert event_drop(w)


def test_own_terminal_ignores_hostile_terminal():
    # A HOSTILE round in terminal is NOT an "own terminal" event (that path is
    # the inbound predicate, which is fog-gated).
    w = _FakeWorld(missiles=[_Missile(phase_label="TERMINAL", is_hostile=True)])
    assert not own_terminal(w)


def test_own_terminal_ignores_dead_round():
    w = _FakeWorld(missiles=[_Missile(phase_label="TERMINAL", alive=False)])
    assert not own_terminal(w)


def test_intercept_window_true_for_friendly_sam_terminal():
    # A non-hostile SamMissile in TERMINAL (player S-300 / Pantsir 57E6) drops.
    w = _FakeWorld(missiles=[_SamMissile(phase_label="TERMINAL")])
    assert intercept_window(w)
    assert event_drop(w)


def test_intercept_window_false_when_no_terminal_sam():
    w = _FakeWorld(missiles=[_SamMissile(phase_label="MIDCOURSE")])
    assert not intercept_window(w)


class _FakePantsir:
    """Faithfully-shaped Pantsir: exposes the own-force ``engaging`` bool flag
    that sim/pantsir.py publishes (and that game/timewarp._pantsir_engaging
    reads).  alive defaults True."""

    def __init__(self, engaging=False, alive=True):
        self.engaging = engaging
        self.alive = alive


def test_intercept_window_true_for_engaging_pantsir_gun_only():
    # The gun-only engagement window (no 57E6 in the air): a live Pantsir with
    # its own-force ``engaging`` flag set drops the warp even with NO SAM round
    # in flight.  Fog-safe: ``engaging`` is own-force state, not enemy truth.
    w = _FakeWorld(pantsirs=[_FakePantsir(engaging=True)])
    assert intercept_window(w)
    assert event_drop(w)
    assert drop_cause(w) == "INTERCEPT"


def test_intercept_window_false_for_idle_pantsir():
    w = _FakeWorld(pantsirs=[_FakePantsir(engaging=False)])
    assert not intercept_window(w)


def test_intercept_window_ignores_dead_engaging_pantsir():
    # A dead unit prosecutes nothing (sim clears its flag), but be defensive:
    # an alive=False unit must not drop the warp even if the flag lingered.
    w = _FakeWorld(pantsirs=[_FakePantsir(engaging=True, alive=False)])
    assert not intercept_window(w)


def test_real_pantsir_publishes_engaging_flag_for_gun_only_window():
    # END-TO-END (real units in a real CombatWorld, no GL): a real Pantsir with
    # a FORMED fire-control track on a live inbound hostile but NO 57E6 in flight
    # (SAM ammo zeroed) must publish unit.engaging == True, so intercept_window's
    # gun-only branch is actually reachable in-game — the dead-code gap the
    # finding flagged.  Reuses the proven tools/smoke_combat.py w12 geometry
    # (an inbound Tomahawk at the Bastion-guard Pantsir) so the radar LOS /
    # terrain checks pass exactly as they do in a live battle.
    import numpy as np
    from sim.arsenal import TOMAHAWK
    from sim.strike import StrikeMissile
    from world.combat import CombatWorld
    from world.generation import BASE_POS

    PHYS_DT = 1.0 / 120.0
    w = CombatWorld()
    w.radar_station.emitting = False        # isolate from the commander
    for s in w.ships:
        s.tomahawk_ammo = 0
        s.sm2_ammo = 0                      # no friendly SAM in flight anywhere
    for p in w.pantsirs:
        p.missile_ammo = 0                 # NO SAM channel on ANY unit -> the
        p.gun.ammo = 0                     # ONLY intercept_window source left is
        #                                    the gun-engaging flag (zero the gun
        #                                    too so a kill never ends it early —
        #                                    the flag is the FIRE-CONTROL track,
        #                                    independent of the round count)
    p_bastion = w.pantsirs[0]
    assert p_bastion.engaging is False      # idle at construction (default init)

    inbound = StrikeMissile(
        TOMAHAWK,
        np.array([BASE_POS[0], 50.0, p_bastion.pos[2] + 18_000.0]),
        np.zeros(3), (BASE_POS[0], BASE_POS[2]), target_y=0.0)
    inbound.launch_platform = None
    w.missiles.append(inbound)

    saw_engaging = False
    saw_intercept_window = False
    for _ in range(int(120.0 / PHYS_DT)):
        w.step(PHYS_DT)
        # No friendly SAM round can exist (all SAM ammo zeroed), so the ONLY
        # way intercept_window can be True is the gun-engaging Pantsir flag.
        assert not any(_is_friendly_sam_in_flight(m) for m in w.missiles)
        if p_bastion.engaging:
            saw_engaging = True
            saw_intercept_window = saw_intercept_window or intercept_window(w)
        if not inbound.alive:
            break
    assert saw_engaging, "real Pantsir must publish the gun-only ENGAGING flag"
    assert saw_intercept_window, (
        "intercept_window must fire solely on the live gun-engaging flag")


def _is_friendly_sam_in_flight(m) -> bool:
    """A live non-hostile SAM round (used by the gun-only test to PROVE no SAM
    channel is contaminating the intercept_window assertion)."""
    from sim.sam import SamMissile
    return isinstance(m, SamMissile) and getattr(m, "alive", False)


def test_event_drop_false_on_empty_world():
    assert not event_drop(_FakeWorld())


def test_drop_cause_tags_and_priority():
    assert drop_cause(_FakeWorld()) is None
    # INBOUND (detected hostile strike) outranks an own terminal.
    hostile = _Missile(aircraft_id="h0", is_hostile=True)
    own = _Missile(phase_label="TERMINAL", is_hostile=False)
    w = _FakeWorld(
        missiles=[hostile, own],
        strike_board={"h0": hostile},
        tracks={"h0": dict(is_air=True)})
    assert drop_cause(w) == "INBOUND"
    # Own terminal alone -> TERMINAL.
    assert drop_cause(_FakeWorld(missiles=[own])) == "TERMINAL"
    # Friendly SAM terminal alone -> INTERCEPT.
    assert drop_cause(
        _FakeWorld(missiles=[_SamMissile(phase_label="TERMINAL")])
    ) == "INTERCEPT"


# --------------------------------------------------- launch-lock regression (d)

def test_launch_lock_still_forces_1x():
    # (d) The launch-cinematic 1x lock is unchanged: when the OR-of-predicates
    # passed to the director is True (launch lock active), it eases to 1x — the
    # director treats the launch lock identically to a drop predicate.
    from world.world import launch_realtime_lock, WorldState
    from sim.missile import PH_EJECT
    ws = WorldState()
    assert not launch_realtime_lock(ws.missiles)
    m = ws.launch("hi-lo", np.array([0.0, 0.0, 90_000.0]))
    assert m.phase == PH_EJECT
    assert launch_realtime_lock(ws.missiles)     # cinematic locks the clock
    d = TimeWarpDirector()
    _settle(d, 8.0, drop=False)
    eff = _settle(d, 8.0, drop=True)             # launch lock -> drop -> 1x
    assert eff == pytest.approx(1.0, abs=1e-3)


# ------------------------------------------------------------- determinism (f)

def test_warp_is_a_pure_multiplier_on_sim_time():
    # (f) Warp only governs how many fixed PHYS_DT steps a real frame consumes;
    # it never changes the physics.  Stepping the SAME seed to the SAME sim_time
    # with 1x pacing (1 step/frame) vs 8x pacing (8 steps/frame) must leave the
    # commander / back-plot picture bit-identical.
    from world.combat import CombatWorld
    from world.combat_config import CombatConfig

    PHYS_DT = 1.0 / 120.0
    n_steps = 600                                # 5 s of sim at 120 Hz

    def run(steps_per_frame):
        cw = CombatWorld(CombatConfig(seed=1337))
        done = 0
        while done < n_steps:
            for _ in range(min(steps_per_frame, n_steps - done)):
                cw.step(PHYS_DT)
                done += 1
        return cw

    slow = run(1)                                # 1x pacing
    fast = run(8)                                # 8x pacing
    assert slow.sim_time == pytest.approx(fast.sim_time, abs=1e-9)
    # Commander belief (sensor-derived) must match step-for-step.
    assert (len(slow.commander.picture._back_plots)
            == len(fast.commander.picture._back_plots))
    assert (len(slow.commander.picture.clusters)
            == len(fast.commander.picture.clusters))
    for a, b in zip(slow.commander.picture._back_plots,
                    fast.commander.picture._back_plots):
        np.testing.assert_array_equal(np.asarray(a.estimated_pos),
                                      np.asarray(b.estimated_pos))
