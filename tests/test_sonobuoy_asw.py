"""M5 player passive sonobuoy field (acoustic triangulation counter).

Contracts (spec 03, feature 3):
  (a) ONE buoy hearing the boat yields a bearing but NOT an actionable fix
      (bearing-only, no range — the same property ElintReceiver enforces).
  (b) TWO+ buoys with baseline -> an actionable fix that sharpens with more
      buoys/time.
  (c) a QUIET APPROACH sub at range R is NOT heard while a LAUNCH-transient sub
      at R IS (noise-floor physics).
  (d) NO horizon/terrain gate — a buoy behind a coastal ridge from the sub STILL
      hears it (the load-bearing divergence from ElintReceiver).
  (e) determinism under [seed, 14].
  (f) placement consumes stock and refuses at zero.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from sim.recon import (AcousticReceiver, SONOBUOY_RANGE_M,
                       ACOUSTIC_FIX_ACTIONABLE_M, ACOUSTIC_DETECT_FLOOR)
from sim.submarine import (Submarine, SUB_APPROACH, SUB_LAUNCH,
                          SUB_NOISE_APPROACH)
from world.combat import CombatWorld
from world.combat_config import CombatConfig

DT = 1.0 / 120.0


def _sub_at(xz, state, transient=False, seed=1337):
    s = Submarine(anchor_xz=xz, rng=np.random.default_rng([seed, 13]),
                  kalibr_ammo=4, base_xz=(0.0, 0.0))
    s.state = state
    s.launch_transient = transient
    return s


def _buoy(x, z):
    return np.array([x, -15.0, z], dtype=np.float64)


# ---------------------------------------------------------------------------
# (a) one buoy -> bearing only, no actionable fix
# ---------------------------------------------------------------------------

def test_one_buoy_no_actionable_fix():
    sub = _sub_at((0.0, 100_000.0), SUB_LAUNCH, transient=True)
    ar = AcousticReceiver(rng=np.random.default_rng([1337, 14]))
    for _ in range(20):
        ar.update([sub], [_buoy(0.0, 85_000.0)], sim_time=0.0)
    assert ar.hearing_count(sub.sub_id) == 1, "one buoy must hear it"
    assert not ar.is_actionable(sub.sub_id), (
        "a single buoy is bearing-only — no actionable cross-fix")
    assert not math.isfinite(ar.fix_quality(sub.sub_id))


# ---------------------------------------------------------------------------
# (b) two+ buoys -> actionable fix that sharpens
# ---------------------------------------------------------------------------

def test_two_buoys_actionable_and_sharpens():
    sub = _sub_at((0.0, 100_000.0), SUB_LAUNCH, transient=True)
    truth = (float(sub.pos[0]), float(sub.pos[2]))

    # Two buoys with a real cross-fix baseline.
    ar2 = AcousticReceiver(rng=np.random.default_rng([1337, 14]))
    for _ in range(30):
        ar2.update([sub], [_buoy(-15_000.0, 85_000.0), _buoy(15_000.0, 85_000.0)],
                   sim_time=0.0)
    assert ar2.hearing_count(sub.sub_id) == 2
    assert ar2.is_actionable(sub.sub_id), "two buoys with baseline -> actionable"
    q2 = ar2.fix_quality(sub.sub_id)
    est = ar2.est_pos(sub.sub_id)
    err = float(np.hypot(est[0] - truth[0], est[2] - truth[1]))
    assert err < ACOUSTIC_FIX_ACTIONABLE_M, "the fix must land near truth"

    # Three buoys -> a SHARPER (smaller) quality than two.
    ar3 = AcousticReceiver(rng=np.random.default_rng([1337, 14]))
    for _ in range(30):
        ar3.update([sub], [_buoy(-15_000.0, 85_000.0), _buoy(0.0, 80_000.0),
                           _buoy(15_000.0, 85_000.0)], sim_time=0.0)
    q3 = ar3.fix_quality(sub.sub_id)
    assert q3 < q2, "more buoys must sharpen the cross-fix quality"


# ---------------------------------------------------------------------------
# (c) noise-floor physics: quiet creep unheard, loud transient heard
# ---------------------------------------------------------------------------

def test_quiet_sub_unheard_loud_transient_heard():
    """At a fixed range R (placed so the cross-fix buoys are ~15 km off), a
    QUIET APPROACH boat is NOT heard while a LOUD LAUNCH transient IS."""
    buoys = [_buoy(-15_000.0, 90_000.0), _buoy(15_000.0, 90_000.0)]
    # quiet APPROACH boat (~15 km from each buoy -> beyond the quiet detect range)
    quiet = _sub_at((0.0, 100_000.0), SUB_APPROACH, transient=False)
    ar_q = AcousticReceiver(rng=np.random.default_rng([1337, 14]))
    for _ in range(10):
        ar_q.update([quiet], buoys, sim_time=0.0)
    assert ar_q.hearing_count(quiet.sub_id) == 0, (
        "a quiet creeping boat at this range must be unheard (noise-floor)")

    # loud LAUNCH-transient boat at the SAME position IS heard.
    loud = _sub_at((0.0, 100_000.0), SUB_LAUNCH, transient=True)
    ar_l = AcousticReceiver(rng=np.random.default_rng([1337, 14]))
    for _ in range(10):
        ar_l.update([loud], buoys, sim_time=0.0)
    assert ar_l.hearing_count(loud.sub_id) >= 2, (
        "a loud launch transient at the same range must be heard by the field")


# ---------------------------------------------------------------------------
# (d) NO horizon / terrain gate (the load-bearing divergence)
# ---------------------------------------------------------------------------

def test_no_terrain_gate_a_ridge_does_not_block():
    """A buoy behind a (hypothetical) coastal ridge from the sub STILL hears it:
    AcousticReceiver.update takes NO height_fn and never calls terrain_blocks /
    radar_horizon_m.  Compare against ElintReceiver, which WOULD block a
    LOS-occluded emitter.  Here we assert the acoustic path ignores terrain by
    construction: hearing depends ONLY on noise-vs-range, not LOS."""
    import inspect
    src = inspect.getsource(AcousticReceiver.update)
    assert "terrain_blocks" not in src, (
        "acoustic update must NOT terrain-gate (sound travels under the surface)")
    assert "radar_horizon" not in src, (
        "acoustic update must NOT horizon-gate")
    # Behavioural: the heard() floor is pure noise-vs-range, independent of any
    # terrain between buoy and boat (there is no LOS argument at all).
    loud = _sub_at((0.0, 100_000.0), SUB_LAUNCH, transient=True)
    ar = AcousticReceiver(rng=np.random.default_rng([1337, 14]))
    # Buoy close enough to hear; the sub is at -120 m "under" any ridge.
    ar.update([loud], [_buoy(0.0, 90_000.0)], sim_time=0.0)
    assert ar.hearing_count(loud.sub_id) == 1


# ---------------------------------------------------------------------------
# (e) determinism under [seed, 14]
# ---------------------------------------------------------------------------

def test_acoustic_determinism():
    def run():
        sub = _sub_at((0.0, 100_000.0), SUB_LAUNCH, transient=True, seed=99)
        ar = AcousticReceiver(rng=np.random.default_rng([99, 14]))
        for _ in range(15):
            ar.update([sub], [_buoy(-15_000.0, 85_000.0),
                              _buoy(15_000.0, 85_000.0)], sim_time=0.0)
        est = ar.est_pos(sub.sub_id)
        return (round(float(ar.fix_quality(sub.sub_id)), 6),
                round(float(est[0]), 6), round(float(est[2]), 6))
    assert run() == run()


# ---------------------------------------------------------------------------
# (f) placement consumes stock + refuses at zero
# ---------------------------------------------------------------------------

def test_place_sonobuoy_consumes_stock_and_refuses_at_zero():
    cw = CombatWorld(CombatConfig(seed=1337, n_subs=1, n_sonobuoys=2))
    assert cw.sonobuoys_left == 2
    b0 = cw.place_sonobuoy((10_000.0, 90_000.0))
    assert b0 is not None
    assert cw.sonobuoys_left == 1
    assert len(cw.sonobuoys) == 1
    cw.place_sonobuoy((-10_000.0, 90_000.0))
    assert cw.sonobuoys_left == 0
    # Refuses at zero.
    assert cw.place_sonobuoy((0.0, 90_000.0)) is None
    assert cw.sonobuoys_left == 0
    assert len(cw.sonobuoys) == 2


def test_zero_stock_refuses_immediately():
    cw = CombatWorld(CombatConfig(seed=1337, n_subs=1, n_sonobuoys=0))
    assert cw.sonobuoys_left == 0
    assert cw.place_sonobuoy((0.0, 90_000.0)) is None


# ---------------------------------------------------------------------------
# end-to-end: a placed buoy field forms a subsurface track on a loud boat
# ---------------------------------------------------------------------------

def test_buoy_field_forms_subsurface_track_in_world():
    """A field placed across a loud (launching) boat's position localizes it into
    the world's sub_contacts (the player picture)."""
    cw = CombatWorld(CombatConfig(seed=1337, n_subs=1, n_sonobuoys=3,
                                  sub_kalibr_ammo=4))
    sub = cw.subs[0]
    sx, sz = float(sub.pos[0]), float(sub.pos[2])
    # Drop a cross-fix field that BRACKETS the boat in range (two buoys nearer
    # the base, one PAST the boat) — the real ASW lesson: surround the contact
    # so the bearings pin range, not just cluster on one side.
    cw.place_sonobuoy((sx - 15_000.0, sz - 10_000.0))
    cw.place_sonobuoy((sx + 15_000.0, sz - 10_000.0))
    cw.place_sonobuoy((sx, sz + 5_000.0))
    sub.state = SUB_LAUNCH
    sub.launch_transient = True
    formed = False
    for _ in range(int(4.0 / DT)):
        sub.launch_transient = True   # hold the loud signature for the test
        cw._step_acoustic_sensors()
        cw.sim_time += DT
        if sub.sub_id in cw.sub_contacts:
            formed = True
            break
    assert formed, "a tight buoy field on a loud boat must form a subsurface track"
