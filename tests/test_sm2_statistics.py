"""SM-2 low-altitude physics contract (Phase 3 gate, GL-free, plain pytest).

Two mechanisms, locked statistically — outcomes EMERGE from physics, never
from probability rolls (user law):

  1. Multipath tracking noise (sim/sam.py MULTIPATH_*): below 150 m the
     position the SM-2 guides on wanders (per-axis OU process). Fixed-seed
     batches against a straight 680 m/s sea-skimmer (the fast stub-target
     harness style of tests/test_enemy_defense.py / test_sm2_ciws.py — full
     seeded battles live in tools/probe_sm2_batch.py):
       - low batch (3-round engagements vs the 60 m lo-lo cruise, the real
         shoot-shoot-look doctrine) kill fraction within [0.2, 0.65]
         (two-sided: the sea-skimmer must be HARD but not invulnerable;
         measured 0.458 at the locked sigma, matching the full-battle
         kill-per-engagement of 0.50),
       - high batch (3 km) kill fraction >= 0.75 (noise is zero up there),
       - no-noise control (rng None) kills an even LOWER 12 m skimmer every
         time (the misses come from the noise, not a broken interceptor).
  2. Terminal lock-break on terrain mask (sim/sam.py LOS_CHECK_PERIOD_S):
     a masked illuminator line of sight snaps the lock — the missile
     coasts on the frozen estimate and misses; LOS restored -> reacquire
     -> kill. Island-hugging routes are a genuine evasion tactic.

Bands were MEASURED before locking (tools/probe_sm2_batch.py sweep,
docs/combat_build_log.md 'Phase 3 gate'): at the locked sigma the low batch
sits mid-band; the asserts catch a future 2x drift in either direction.
"""

import math

import numpy as np

from sim.arsenal import SM2
from sim.sam import (MULTIPATH_ALT_M, MULTIPATH_SIGMA_M, SPH_MIDCOURSE,
                     SPH_TERMINAL, SamMissile)

DT = 1.0 / 120.0
DECK = np.array([0.0, 10.0, 0.0])      # Mk 41 deck height above the waterline


class _OpenSea:
    """Minimal world stub: deep ocean everywhere (no terrain mask)."""

    ships = []

    def terrain_height_at(self, x, z):
        return -500.0


class _WallSea:
    """Open sea plus a 200 m ridge across z in [7_900, 10_500] (>= 2 km deep
    so sim/radar.terrain_blocks' 2 km sampling can never step over it). The
    synthetic island that masks a sea-level illuminator's line of sight."""

    ships = []

    def terrain_height_at(self, x, z):
        return 200.0 if 7_900.0 <= z <= 10_500.0 else -500.0


class _Skimmer:
    """Straight-line constant-velocity missile-like target (duck-types
    pos / velocity() / alive, no kill() — same stub as test_sm2_ciws)."""

    def __init__(self, pos, vel):
        self.pos = np.asarray(pos, dtype=np.float64).copy()
        self._vel = np.asarray(vel, dtype=np.float64).copy()
        self.alive = True

    def velocity(self):
        return self._vel

    def update(self, dt):
        if self.alive:
            self.pos += self._vel * dt


def _engage(sam, target, world, t_max=90.0):
    """Step target-then-SAM until the SAM dies or t_max; returns the
    minimum point-sampled separation."""
    t = 0.0
    min_d = float("inf")
    while sam.alive and t < t_max:
        target.update(DT)
        sam.update(DT, world)
        t += DT
        d = float(np.linalg.norm(sam.pos - target.pos))
        min_d = min(min_d, d)
    return min_d


def _skim_shot(alt, seed):
    """One SM-2 vs a 680 m/s inbound at ``alt``, 42 km out (the real
    engagement geometry: the SPY-1 horizon tracks a skimmer near 50 km and
    the round goes out moments later — closer launches dive too steeply off
    the loft and splash even WITHOUT noise, the accepted 'wasted close-in
    low shot' regime), noise seeded with ``seed`` (None = clean guidance).
    Returns True on a fuse kill."""
    target = _Skimmer([0.0, alt, 42_000.0], [0.0, 0.0, -680.0])
    rng = None if seed is None else np.random.default_rng(seed)
    sam = SamMissile(SM2, DECK, target, rng=rng)
    _engage(sam, target, _OpenSea())
    return sam.killed_target


def _engagement(alt, seed, rounds=3, spacing_s=3.0, range_m=48_000.0):
    """One ENGAGEMENT: ``rounds`` SM-2s fired ``spacing_s`` apart (the
    destroyer's fire-control reload — sim/enemy_ships.py) at one inbound
    skimmer; each round gets a child noise Generator off the seed exactly
    like sim/enemy_defense.py spawns them. True when any round connects."""
    parent = np.random.default_rng(seed)
    target = _Skimmer([0.0, alt, range_m], [0.0, 0.0, -680.0])
    w = _OpenSea()
    sams = []
    launched = 0
    next_launch = 0.0
    t = 0.0
    while t < 120.0:
        if launched < rounds and t >= next_launch and target.alive:
            sams.append(SamMissile(
                SM2, DECK, target,
                rng=np.random.default_rng(int(parent.integers(2 ** 63)))))
            launched += 1
            next_launch = t + spacing_s
        target.update(DT)
        for s in sams:
            if s.alive:
                s.update(DT, w)
        t += DT
        if not target.alive:
            return True
        if launched == rounds and not any(s.alive for s in sams):
            return False
    return not target.alive


# ===========================================================================
# 1. Multipath noise statistics (fixed seeds: deterministic batches)
# ===========================================================================

def test_low_engagement_kill_fraction_in_band():
    """60 m lo-lo cruise batch, 3-round engagements: the multipath wander
    must defeat the 20 m fuse often — but not always. Two-sided band per
    the gate contract (measured 11/24 = 0.458 at the locked sigma)."""
    kills = sum(_engagement(60.0, seed) for seed in range(24))
    frac = kills / 24.0
    assert 0.2 <= frac <= 0.65, (
        f"low-altitude engagement kill fraction {frac:.2f} ({kills}/24) "
        f"outside [0.2, 0.65] — sigma drifted? "
        f"(MULTIPATH_SIGMA_M={MULTIPATH_SIGMA_M})")


def test_high_target_kill_fraction_stays_high():
    """3 km target batch with the SAME rng wiring: sigma is zero above
    MULTIPATH_ALT_M, so altitude keeps the SM-2 near-certain."""
    assert 3_000.0 > MULTIPATH_ALT_M
    kills = sum(_skim_shot(3_000.0, seed) for seed in range(10))
    assert kills / 10.0 >= 0.75, (
        f"high-altitude batch killed only {kills}/10 — noise must not "
        f"reach above MULTIPATH_ALT_M")


def test_no_noise_control_kills_low_skimmer_every_time():
    """rng None = clean guidance: the same 12 m skimmer dies every time
    across three ranges. The low-batch misses are the NOISE, not a broken
    interceptor (two-sided control for the band above)."""
    for rng_m in (42_000.0, 48_000.0, 55_000.0):
        target = _Skimmer([0.0, 12.0, rng_m], [0.0, 0.0, -680.0])
        sam = SamMissile(SM2, DECK, target)
        _engage(sam, target, _OpenSea())
        assert sam.killed_target, f"clean SM-2 missed the skimmer at {rng_m} m"


def test_noise_decays_above_threshold():
    """The OU error built up against a low target decays (tau) once the
    target climbs out of the multipath region — no frozen offset."""
    target = _Skimmer([0.0, 30.0, 30_000.0], [0.0, 0.0, -680.0])
    sam = SamMissile(SM2, DECK, target, rng=np.random.default_rng(7))
    w = _OpenSea()
    for _ in range(int(2.0 / DT)):          # build error against 30 m target
        sam.update(DT, w)
    assert abs(sam._mp_x) + abs(sam._mp_y) + abs(sam._mp_z) > 0.0
    target.pos[1] = 5_000.0                  # target now far above threshold
    for _ in range(int(3.0 / DT)):           # 6 tau: e^-6 ~ 0.25%
        sam.update(DT, w)
    assert abs(sam._mp_x) < 1.0
    assert abs(sam._mp_y) < 1.0
    assert abs(sam._mp_z) < 1.0


# ===========================================================================
# 2. Terminal lock-break on terrain mask
# ===========================================================================

def _midcourse_sam(pos, vel, target, illuminator_pos_fn=None):
    """An SM-2 teleported into burnt-out midcourse flight (the same direct
    state setup as test_sam.py's surface-impact test) so the terminal
    handover happens on the first update."""
    sam = SamMissile(SM2, pos, target, illuminator_pos_fn=illuminator_pos_fn)
    sam.phase = SPH_MIDCOURSE
    sam.propellant = 0.0
    sam.t = 20.0
    sam.vel[:] = vel
    sam.prev_pos[:] = sam.pos
    return sam


def test_masked_lock_freezes_estimate_and_misses():
    """Target running laterally BEHIND the synthetic island: the ship's
    illuminator line of sight is masked on every terminal check, so the
    lock snaps at handover — the missile flies to the frozen estimate
    (where the target WAS) while the real target sails away untouched."""
    target = _Skimmer([-6_000.0, 60.0, 12_000.0], [350.0, 0.0, 0.0])
    illum = lambda: (0.0, 20.0, 0.0)         # ship director at the origin
    sam = _midcourse_sam([0.0, 3_000.0, -2_000.0], [0.0, -50.0, 750.0],
                         target, illuminator_pos_fn=illum)
    w = _WallSea()
    sam.update(DT, w)                        # handover + first LOS check
    assert sam.phase == SPH_TERMINAL
    assert sam._lock_ok is False, "wall must mask the illuminator LOS"
    frozen = sam._lock_pos.copy()
    min_tgt = float("inf")
    min_frozen = float("inf")
    t = 0.0
    while sam.alive and t < 60.0:
        target.update(DT)
        sam.update(DT, w)
        t += DT
        assert sam._lock_ok is False         # never clears behind the wall
        min_tgt = min(min_tgt, float(np.linalg.norm(sam.pos - target.pos)))
        min_frozen = min(min_frozen,
                         float(np.linalg.norm(sam.pos - frozen)))
        assert np.array_equal(sam._lock_pos, frozen), "estimate must stay frozen"
    assert target.alive and not sam.killed_target
    assert min_tgt > SM2.fuse_radius * 4, (
        f"masked lock still passed {min_tgt:.0f} m from the live target")
    assert min_frozen < 150.0, (
        f"coasting round never converged on the frozen estimate "
        f"({min_frozen:.0f} m)")


def test_lock_reacquires_when_los_clears():
    """Target crossing OUT from behind the island toward the ship: terminal
    handover happens masked (coast), the LOS check clears once the target
    crosses the ridge line — the seeker reacquires and the kill lands."""
    # Energy-model re-pin (2026-07-05, argued): the old script started the
    # interceptor at 707 m/s — late-coast anemia that only ever killed
    # because corrections used to be energetically FREE. With induced drag
    # a decelerating round chasing a 6-s-stale frozen estimate falls into
    # the classic PN energy death-spiral (measured: bled to 336 m/s,
    # crossed 857 m high). Re-scripted at an honest mid-coast 1110 m/s
    # with a 3 s masked window: handover is still masked, the LOS still
    # clears mid-fly, and the reacquired kill lands at 13.5 m (measured).
    target = _Skimmer([0.0, 60.0, 12_000.0], [0.0, 0.0, -680.0])
    illum = lambda: (0.0, 20.0, 0.0)
    sam = _midcourse_sam([0.0, 3_500.0, 1_000.0], [0.0, -150.0, 1_100.0],
                         target, illuminator_pos_fn=illum)
    w = _WallSea()
    sam.update(DT, w)
    assert sam.phase == SPH_TERMINAL
    assert sam._lock_ok is False, "handover behind the wall starts masked"
    was_masked_then_clear = False
    t = 0.0
    while sam.alive and t < 60.0:
        target.update(DT)
        sam.update(DT, w)
        t += DT
        if sam._lock_ok:
            was_masked_then_clear = True
    assert was_masked_then_clear, "LOS never cleared — bad test geometry"
    assert sam.killed_target and not target.alive, (
        "reacquired lock must finish the intercept")


def test_player_s300_open_air_unaffected():
    """No illuminator + open terrain: the default (player S-300 style)
    seeker LOS never breaks and the no-rng round carries zero noise — the
    pre-existing aircraft contract is untouched by this gate."""
    target = _Skimmer([0.0, 8_000.0, 45_000.0], [0.0, 0.0, -250.0])
    sam = SamMissile(SM2, DECK, target)
    w = _OpenSea()
    saw_terminal = False
    t = 0.0
    while sam.alive and t < 120.0:
        target.update(DT)
        sam.update(DT, w)
        t += DT
        if sam.phase == SPH_TERMINAL:
            saw_terminal = True
            assert sam._lock_ok is True
    assert saw_terminal
    assert sam.killed_target
    assert sam._mp_x == 0.0 and sam._mp_y == 0.0 and sam._mp_z == 0.0
