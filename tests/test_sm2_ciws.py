"""SM-2 interceptor definition, SamMissile vs missile-like target, and CIWS
unit tests (GL-free, plain pytest).

Coverage:
  SM2 def — field sanity (range 150 km, mass 1340 kg, VLS eject pattern).
  SamMissile(weapon=SM2) — launches and reaches the target area against a
    synthetic straight-line missile-like target using a frozen contact
    estimate, mirroring the test_sam.py pattern.
  Ciws — never fires beyond 2 km; seeded rng kills a slow close target
    within a few bursts; ammo depletes and gun goes silent.
"""

import math

import numpy as np
import pytest

from sim.arsenal import SM2, SM2_VLS, SAMS, LAUNCHERS
from sim.ciws import (Ciws, BURST_FIRE_TIME, BURST_PAUSE_TIME,
                      ENGAGE_RANGE, ROUNDS_PER_SECOND)
from sim.physics import GRAVITY
from sim.sam import (SPH_BOOST, SPH_DEAD, SPH_EJECT, SPH_MIDCOURSE,
                     SPH_TERMINAL, SamMissile)

DT = 1.0 / 120.0
LAUNCH_POS = np.array([0.0, 10.0, 0.0])   # deck-height above waterline


# ---------------------------------------------------------------------------
# Minimal world stub (open ocean, no terrain)
# ---------------------------------------------------------------------------

class _World:
    ships = []

    def terrain_height_at(self, x, z):
        return -500.0   # deep ocean everywhere


# ---------------------------------------------------------------------------
# Synthetic straight-line missile target (duck-types pos/velocity/alive)
# ---------------------------------------------------------------------------

class _FlyingMissile:
    """Straight-line constant-velocity missile-like target.  No ``kill()``
    method — exercises the duck-typed fuse path in SamMissile._fuse_check."""

    def __init__(self, pos, vel):
        self.pos = np.asarray(pos, dtype=np.float64).copy()
        self._vel = np.asarray(vel, dtype=np.float64).copy()
        self.alive = True

    def velocity(self):
        return self._vel.copy()

    def update(self, dt):
        if self.alive:
            self.pos += self._vel * dt


def _incoming_missile(range_m, alt=300.0, speed=680.0):
    """An Oniks-class cruise missile flying due south at ``speed`` m/s,
    starting ``range_m`` north of the launcher at ``alt`` metres."""
    pos = np.array([0.0, alt, range_m])
    vel = np.array([0.0, 0.0, -speed])   # heading south toward launcher
    return _FlyingMissile(pos, vel)


def _sam_sm2(target, estimate_fn=None):
    return SamMissile(SM2, LAUNCH_POS, target, contact_estimate_fn=estimate_fn)


def _engage(m, target, t_max):
    """Step target-then-SAM until the SAM dies or t_max. Returns elapsed
    sim time and minimum sampled separation."""
    w = _World()
    t = 0.0
    min_d = float("inf")
    while m.alive and t < t_max:
        target.update(DT)
        m.update(DT, w)
        t += DT
        d = float(np.linalg.norm(m.pos - target.pos))
        min_d = min(min_d, d)
    return t, min_d


# ===========================================================================
# 1. SM-2 definition sanity
# ===========================================================================

def test_sm2_range_and_mass():
    assert SM2.max_range == 150_000.0, "spec §9: 150 km"
    assert SM2.launch_mass == 1340.0, "spec §5.2: 1340 kg"


def test_sm2_field_sanity():
    assert SM2.weapon_id == "sm2"
    assert SM2.display_name == "SM-2 Block IIIB"
    assert SM2.length == 6.55 and SM2.diameter == pytest.approx(0.343)
    assert SM2.launch_mass > SM2.propellant_mass
    # VLS eject: short gas-pulse (≤0.5 s) — much shorter than S-300's 1.5 s hang.
    assert SM2.eject_time <= 0.5
    assert SM2.eject_speed > 0.0
    # Motor delivers enough energy to reach the 150 km envelope.
    assert SM2.motor_thrust > 50_000.0
    assert SM2.motor_time > 5.0
    assert SM2.isp == 240.0
    # mdot consistency: thrust / (isp * g) * burn_time ≈ propellant_mass (±5%)
    mdot = SM2.motor_thrust / (SM2.isp * GRAVITY)
    burned = mdot * SM2.motor_time
    assert burned == pytest.approx(SM2.propellant_mass, rel=0.05), (
        f"Motor burns {burned:.0f} kg but propellant_mass={SM2.propellant_mass} kg")
    assert SM2.ref_area == pytest.approx(math.pi * (SM2.diameter / 2) ** 2,
                                         rel=1e-3)
    assert SM2.fuse_radius > 0.0 and SM2.fuse_radius <= 30.0
    assert SM2.terminal_range > 0.0
    assert SM2.max_g >= 20.0
    assert SM2.self_destruct_t > 100.0
    assert SM2.min_intercept_alt >= 0.0
    assert SM2.max_intercept_alt >= 10_000.0


def test_sm2_in_registries():
    assert SAMS["sm2"] is SM2
    assert LAUNCHERS["sm2_vls"] is SM2_VLS
    assert SM2_VLS.weapon_ids == ("sm2",)
    assert SM2_VLS.tubes > 0 and SM2_VLS.ammo > 0


# ===========================================================================
# 2. SamMissile(weapon=SM2) launch behaviour
# ===========================================================================

def test_sm2_vls_eject_is_brief():
    """VLS eject phase completes within 0.5 s (spec: short gas pulse)."""
    target = _incoming_missile(60_000.0)
    m = _sam_sm2(target)
    w = _World()
    while m.phase == SPH_EJECT and m.t < 2.0:
        m.update(DT, w)
    assert m.phase == SPH_BOOST, "VLS eject should complete within ~0.5 s"
    assert m.t <= 0.55, f"eject phase ran for {m.t:.3f} s, expected ≤0.55 s"


def test_sm2_boost_phase_accelerates():
    """After eject the motor burns and speed increases."""
    target = _incoming_missile(60_000.0)
    m = _sam_sm2(target)
    w = _World()
    # Step through eject.
    while m.phase == SPH_EJECT:
        m.update(DT, w)
    speed_at_boost = float(np.linalg.norm(m.vel))
    # Step 3 s into boost.
    for _ in range(int(3.0 / DT)):
        m.update(DT, w)
    speed_after = float(np.linalg.norm(m.vel))
    assert speed_after > speed_at_boost * 3.0, (
        "Speed should grow significantly during the motor burn")


def test_sm2_reaches_target_area_60km_missile():
    """SM-2 intercepts a 60 km straight-line cruise missile using a frozen
    contact estimate (mirrors the S-300 contact-estimate test pattern)."""
    target = _incoming_missile(60_000.0, alt=200.0, speed=680.0)
    offset = np.array([0.0, 0.0, 500.0])   # stale estimate slightly off

    def estimate():
        return target.pos + offset, target.velocity()

    m = _sam_sm2(target, estimate_fn=estimate)
    t, _ = _engage(m, target, t_max=SM2.self_destruct_t + 5.0)
    # The key assertion: the cruise missile target is killed.
    assert not target.alive, (
        f"SM-2 failed to intercept the 60 km cruise missile (elapsed {t:.1f} s)")
    assert m.killed_target
    assert m.impact_pos is not None
    # Intercept should happen well within the self-destruct window.
    assert t < SM2.self_destruct_t


def test_sm2_no_kill_method_on_missile_target():
    """Duck-typing: the target has no kill() — the fuse must set alive=False
    directly without raising AttributeError."""
    target = _incoming_missile(5_000.0, alt=50.0, speed=250.0)
    assert not hasattr(target, "kill")   # contract: no kill() method
    m = _sam_sm2(target)
    w = _World()
    # Step until the SAM reaches the fuse distance or times out.
    for _ in range(int(60.0 / DT)):
        if not m.alive:
            break
        target.update(DT)
        m.update(DT, w)
    # Whether or not it kills, it must not have raised an exception.
    # If the SAM reached the target it should have set alive=False.
    if m.killed_target:
        assert not target.alive
    # Sanity: the test ran without AttributeError (no kill() called).


@pytest.mark.slow
def test_sm2_intercepts_incoming_at_120km():
    """Long-range shot: SM-2 vs a cruise missile starting 120 km out.
    Validates the energy budget (motor + coast) reaches the 120 km bracket."""
    target = _incoming_missile(120_000.0, alt=300.0, speed=680.0)
    m = _sam_sm2(target)
    t, _ = _engage(m, target, t_max=SM2.self_destruct_t + 5.0)
    assert not target.alive, (
        f"SM-2 failed to intercept 120 km cruise missile ({t:.1f} s elapsed)")
    assert t < SM2.self_destruct_t


# ===========================================================================
# 3. Ciws unit tests
# ===========================================================================

def _make_target(pos, vel=(0.0, 0.0, 0.0)):
    return _FlyingMissile(pos, vel)


def test_ciws_no_fire_beyond_2km():
    """Gun must not fire at a target beyond the 2 000 m engagement range."""
    rng = np.random.default_rng(0)
    ciws = Ciws(ammo=1000, rng=rng)
    target = _make_target([0.0, 100.0, 2_500.0], [0.0, 0.0, -500.0])
    # Run for several seconds; ammo must remain full.
    ammo_before = ciws.ammo
    for _ in range(int(5.0 / DT)):
        ciws.engage(target, DT)
    assert ciws.ammo == ammo_before, (
        "CIWS fired at a target beyond the 2 000 m engagement range")


def test_ciws_fires_when_inside_range():
    """A target well inside 2 km and closing triggers firing."""
    rng = np.random.default_rng(1)
    ciws = Ciws(ammo=10_000, rng=rng)
    # Target 500 m directly ahead, closing fast (so closing > 0).
    target = _make_target([0.0, 0.0, 500.0], [0.0, 0.0, -300.0])
    all_events = []
    for _ in range(int(4.0 / DT)):
        events = ciws.engage(target, DT)
        all_events.extend(events)
        if not target.alive:
            break
    burst_events = [e for e in all_events if e[0] == "ciws_burst"]
    assert len(burst_events) > 0, "Expected at least one burst within 4 s"


def test_ciws_kills_slow_close_target_within_few_bursts():
    """With a seeded rng the CIWS kills a 400 m/s closing target before the
    ammo runs out and within a handful of burst cycles.  The rng is seeded
    so the outcome is deterministic — the kill happens on the first burst
    where Pk = 0.50 at point-blank range."""
    rng = np.random.default_rng(42)
    ciws = Ciws(ammo=10_000, rng=rng)
    # Dead-ahead target at 700 m (inside R_NEAR), closing at 400 m/s.
    target = _make_target([0.0, 0.0, 700.0], [0.0, 0.0, -400.0])
    kill_events = []
    # 5 s is generous — at the Pk values given this should resolve in 1-3 bursts.
    for _ in range(int(5.0 / DT)):
        events = ciws.engage(target, DT)
        kill_events.extend(e for e in events if e[0] == "ciws_kill")
        if not target.alive:
            break
    assert not target.alive, "Seeded CIWS failed to kill the close target"
    assert len(kill_events) >= 1
    # target.alive must be False when the kill event was emitted.
    kind, pos = kill_events[0]
    assert isinstance(pos, np.ndarray) and pos.shape == (3,)


def test_ciws_ammo_depletes_gun_goes_silent():
    """Once ammo reaches 0 the gun emits no more bursts or kills."""
    rng = np.random.default_rng(99)
    # Give enough rounds for exactly one burst.
    rounds_per_burst = int(ROUNDS_PER_SECOND * BURST_FIRE_TIME)
    ciws = Ciws(ammo=rounds_per_burst, rng=rng)
    # Use an immortal target (override kill to keep alive).
    target = _make_target([0.0, 0.0, 300.0], [0.0, 0.0, -50.0])
    # Step long enough to fire the first burst and exhaust ammo.
    for _ in range(int(4.0 / DT)):
        ciws.engage(target, DT)
        target.alive = True   # force it alive regardless of kill roll
    # Confirm ammo is gone.
    assert ciws.ammo == 0
    # Now step more; no burst events should appear.
    extra_events = []
    for _ in range(int(4.0 / DT)):
        extra_events.extend(ciws.engage(target, DT))
    burst_events = [e for e in extra_events if e[0] == "ciws_burst"]
    assert len(burst_events) == 0, "Gun fired after ammo was exhausted"


def test_ciws_receding_target_not_engaged():
    """A target that is moving away (closing rate ≤ 0) is not engaged."""
    rng = np.random.default_rng(7)
    ciws = Ciws(ammo=5000, rng=rng)
    # Target inside range but moving away (north, positive Z).
    target = _make_target([0.0, 0.0, 800.0], [0.0, 0.0, 300.0])
    ammo_before = ciws.ammo
    for _ in range(int(3.0 / DT)):
        ciws.engage(target, DT)
    assert ciws.ammo == ammo_before, (
        "CIWS fired at a receding target")


def test_ciws_burst_event_position_matches_target():
    """Burst event position is the target's position at the moment of firing."""
    rng = np.random.default_rng(5)
    ciws = Ciws(ammo=10_000, rng=rng)
    target = _make_target([0.0, 0.0, 500.0], [0.0, 0.0, -200.0])
    burst_events = []
    for _ in range(int(5.0 / DT)):
        events = ciws.engage(target, DT)
        burst_events.extend(e for e in events if e[0] == "ciws_burst")
        if not target.alive or burst_events:
            break
    assert burst_events, "No burst event generated"
    kind, pos = burst_events[0]
    assert pos.shape == (3,)
    # The burst position should be within the engagement range at the time of
    # firing (not necessarily the initial position since target moved).
    assert np.linalg.norm(pos) <= ENGAGE_RANGE + 1.0


def test_ciws_determinism():
    """Two runs with the same rng seed produce identical outcomes."""
    results = []
    for _ in range(2):
        rng = np.random.default_rng(17)
        ciws = Ciws(ammo=5000, rng=rng)
        target = _make_target([0.0, 0.0, 600.0], [0.0, 0.0, -300.0])
        log = []
        for _ in range(int(5.0 / DT)):
            events = ciws.engage(target, DT)
            log.extend(events)
            if not target.alive:
                break
        results.append((target.alive, ciws.ammo, len(log)))
    assert results[0] == results[1], "CIWS runs are not deterministic"
