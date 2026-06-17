"""M3-F3: ELINT bearing-sigma elevation under enemy barrage jamming.

Barrage noise from an enemy escort jammer (the M3-F2 Growler) raises the noise
floor at the drone's PASSIVE ELINT receiver, which widens the angular error
(sigma) on every bearing taken against a REAL emitter.  The drone's existing
least-squares triangulation already turns bearing sigma into a position-quality
CRLB, so raising sigma HONESTLY worsens the fix — no flat penalty, no dice:

    sigma_eff = ELINT_BEARING_SIGMA_RAD * (1.0 + EW_ELINT_SIGMA_K * floor)

where ``floor = ew.noise_floor_at(drone_pos, jammers)`` is the pure-geometry
jam noise floor (RNG-free).  The randomness is STILL only the one existing
seeded gaussian draw in ElintReceiver.update.

THE LOAD-BEARING REGRESSION GATE: ``jammers=()`` (the default) -> floor == 0 ->
sigma_eff == ELINT_BEARING_SIGMA_RAD EXACTLY -> the draw is BYTE-IDENTICAL to
today (same self._rng sequence), so every existing recon/ELINT test passes
unchanged.

These tests are written FIRST (TDD): they fail until noise_floor_at + the
update sigma scaling land.
"""

from __future__ import annotations

import math

import numpy as np

import sim.ew as ew
from sim.recon import (
    ELINT_BEARING_SIGMA_RAD,
    ELINT_FIX_ACTIONABLE_M,
    EW_ELINT_SIGMA_K,
    ElintReceiver,
)


# ---------------------------------------------------------------------------
# Helpers / stubs (mirrors tests/test_recon.py + tests/test_ew_field.py style)
# ---------------------------------------------------------------------------

def _flat(h: float = 0.0):
    return lambda x, z: h


def _make_radar(radar_id="r0", pos=(0.0, 0.0, 80_000.0), antenna_m=20.0,
                alive=True, emitting=True):
    from sim.radar import Radar
    r = Radar(
        radar_id=radar_id,
        pos=np.array(pos, dtype=np.float64),
        antenna_m=antenna_m,
        ranges={"ship": 300_000, "stealth": 30_000, "fighter": 300_000,
                "missile": 300_000},
    )
    r.alive = alive
    r.emitting = emitting
    return r


class _Jammer:
    """Minimal duck-typed jammer: ``.pos`` (3,) + ``.jam_power_w`` (watts)."""

    def __init__(self, pos, jam_power_w):
        self.pos = np.asarray(pos, dtype=np.float64)
        self.jam_power_w = float(jam_power_w)


# A cross-track traverse: drone flies east x=-30..+30 km at cruise alt with the
# emitter 80 km north — the SAME geometry the recon triangulation test uses
# (a determined player's wide-baseline pass).  500 m sampling -> 120 stored
# pairs (well past the spacing gate).
EMITTER_POS = (0.0, 0.0, 80_000.0)
EMITTER_ID = "enemy_r0"
DRONE_ALT = 18_000.0
N_SAMPLES = 120
TRAVERSE_M = 60_000.0


def _drone_positions(n=N_SAMPLES):
    return [
        np.array([-30_000.0 + i * (TRAVERSE_M / n), DRONE_ALT, 0.0],
                 dtype=np.float64)
        for i in range(n)
    ]


def _run_pass(seed, jammers=None, n=N_SAMPLES, with_kwarg=True):
    """Run a full cross-track pass; return the receiver.

    ``jammers`` None + with_kwarg False  -> update called WITHOUT the kwarg
    (the legacy signature) so we can prove byte-identity against jammers=().
    """
    elint = ElintReceiver(rng=np.random.default_rng(seed), height_fn=_flat(0.0))
    radar = _make_radar(pos=EMITTER_POS, antenna_m=20.0)
    for dp in _drone_positions(n):
        if with_kwarg:
            elint.update(dp, [(EMITTER_ID, radar)],
                         jammers=() if jammers is None else jammers)
        else:
            elint.update(dp, [(EMITTER_ID, radar)])
    return elint


def _default_growler():
    """A jammer at the EW default standoff geometry, sitting beyond the emitter
    so its LOS to the drone is clear over flat terrain (north of the track)."""
    return _Jammer(
        (0.0, ew.EW_DEFAULT_JAMMER_ALT_M,
         EMITTER_POS[2] + ew.EW_DEFAULT_STANDOFF_M),
        ew.EW_DEFAULT_JAM_POWER_W,
    )


# ---------------------------------------------------------------------------
# noise_floor_at — pure geometry, RNG-free, monotone, zero without jammers
# ---------------------------------------------------------------------------

def test_noise_floor_zero_without_jammers():
    pos = np.array([0.0, DRONE_ALT, 0.0], dtype=np.float64)
    assert ew.noise_floor_at(pos, ()) == 0.0
    assert ew.noise_floor_at(pos, []) == 0.0


def test_noise_floor_monotone_closer_louder():
    pos = np.array([0.0, DRONE_ALT, 0.0], dtype=np.float64)
    far = _Jammer((0.0, 12_000.0, 200_000.0), 200.0)
    near = _Jammer((0.0, 12_000.0, 100_000.0), 200.0)
    loud = _Jammer((0.0, 12_000.0, 200_000.0), 800.0)
    f_far = ew.noise_floor_at(pos, [far])
    f_near = ew.noise_floor_at(pos, [near])
    f_loud = ew.noise_floor_at(pos, [loud])
    assert f_far > 0.0
    # closer jammer -> louder floor at the receiver (1/R^2)
    assert f_near > f_far
    # more power -> louder floor
    assert f_loud > f_far


def test_noise_floor_is_pure_no_rng():
    """noise_floor_at is deterministic and sim/ew.py imports no RNG."""
    pos = np.array([0.0, DRONE_ALT, 0.0], dtype=np.float64)
    jam = _default_growler()
    vals = [ew.noise_floor_at(pos, [jam]) for _ in range(5)]
    assert len(set(vals)) == 1
    import inspect
    src = inspect.getsource(ew)
    assert "import random" not in src
    assert "np.random" not in src and "numpy.random" not in src


# ---------------------------------------------------------------------------
# THE REGRESSION GATE: jammers=() is BYTE-IDENTICAL to the legacy call.
# ---------------------------------------------------------------------------

def test_no_jammer_byte_identical():
    """jammers=() produces the EXACT same bearing pairs / est_pos / fix_quality
    as the same-seed receiver called WITHOUT the jammers kwarg at all."""
    seed = 1234
    a = _run_pass(seed, jammers=(), with_kwarg=True)     # explicit empty
    b = _run_pass(seed, jammers=None, with_kwarg=False)  # legacy signature

    pa = a._pairs[EMITTER_ID]
    pb = b._pairs[EMITTER_ID]
    assert len(pa) == len(pb)
    for (xz_a, br_a), (xz_b, br_b) in zip(pa, pb):
        # bearings must be BIT-identical (same self._rng draw, floor==0)
        assert br_a == br_b
        assert np.array_equal(xz_a, xz_b)

    qa = a.fix_quality(EMITTER_ID)
    qb = b.fix_quality(EMITTER_ID)
    assert qa == qb
    ea = a.est_pos(EMITTER_ID)
    eb = b.est_pos(EMITTER_ID)
    assert np.array_equal(ea, eb)


# ---------------------------------------------------------------------------
# The physics: jam widens the fix (worse quality), monotone in the floor.
# ---------------------------------------------------------------------------

def test_jam_widens_fix_quality():
    """SAME geometry + seed -> a LARGER (worse) fix_quality WITH a jammer up
    than without, and louder/closer jam -> worse still (monotone in floor)."""
    seed = 7
    no_jam = _run_pass(seed, jammers=())
    quiet = _run_pass(seed, jammers=[_Jammer(
        (0.0, 12_000.0, EMITTER_POS[2] + 300_000.0), ew.EW_DEFAULT_JAM_POWER_W)])
    loud = _run_pass(seed, jammers=[_Jammer(
        (0.0, 12_000.0, EMITTER_POS[2] + 120_000.0), ew.EW_DEFAULT_JAM_POWER_W)])

    q_none = no_jam.fix_quality(EMITTER_ID)
    q_quiet = quiet.fix_quality(EMITTER_ID)
    q_loud = loud.fix_quality(EMITTER_ID)
    assert math.isfinite(q_none)
    # jam must worsen the fix
    assert q_quiet > q_none
    # a closer (louder-at-receiver) jammer worsens it more
    assert q_loud > q_quiet


def test_jam_needs_more_pairs_for_actionable():
    """Under jam, MORE distinct cross-track pairs are needed (on AVERAGE) to
    cross the actionable threshold than without jam.

    A single seed's threshold-crossing is NOT monotone in sigma — a wider
    draw can luck into an early crossing — so we measure the EXPECTED extra
    baseline by averaging the pairs-to-actionable over many seeds (the
    physically meaningful statement: louder noise costs more baseline in
    expectation).  The per-seed monotone effect lives in
    test_jam_widens_fix_quality (same baseline -> worse quality).  Also
    asserts a determined pass STILL localizes under the default Growler on
    EVERY seed (the spec risk: K too high -> never localizes)."""
    growler = _default_growler()
    seeds = range(20)

    def pairs_to_actionable(jammers, seed):
        elint = ElintReceiver(rng=np.random.default_rng(seed),
                              height_fn=_flat(0.0))
        radar = _make_radar(pos=EMITTER_POS, antenna_m=20.0)
        for k, dp in enumerate(_drone_positions(N_SAMPLES), start=1):
            elint.update(dp, [(EMITTER_ID, radar)], jammers=jammers)
            if elint.fix_quality(EMITTER_ID) < ELINT_FIX_ACTIONABLE_M:
                return k
        return None

    clear = [pairs_to_actionable((), s) for s in seeds]
    jam = [pairs_to_actionable([growler], s) for s in seeds]

    assert all(c is not None for c in clear), "clear pass must always localize"
    assert all(j is not None for j in jam), (
        "a DETERMINED cross-track pass must STILL localize under the default "
        "Growler on every seed (EW_ELINT_SIGMA_K too high if this fails)")

    avg_clear = sum(clear) / len(clear)
    avg_jam = sum(jam) / len(jam)
    assert avg_jam > avg_clear, (
        f"jam should need MORE pairs on average "
        f"(clear={avg_clear:.1f}, jam={avg_jam:.1f})")


# ---------------------------------------------------------------------------
# Determinism + jam lifting.
# ---------------------------------------------------------------------------

def test_determinism_same_seed_same_jammer():
    """Two same-seed receivers with the SAME jammer draw identical noisy
    bearings (the floor scaling is deterministic)."""
    seed = 555
    jam = _default_growler()
    a = _run_pass(seed, jammers=[jam])
    b = _run_pass(seed, jammers=[jam])
    pa = a._pairs[EMITTER_ID]
    pb = b._pairs[EMITTER_ID]
    assert len(pa) == len(pb) and len(pa) > 2
    for (_, br_a), (_, br_b) in zip(pa, pb):
        assert br_a == br_b
    assert a.fix_quality(EMITTER_ID) == b.fix_quality(EMITTER_ID)


def test_lifting_jam_restores_base_sigma():
    """When the jammer is removed on a later pass, sigma returns to base: the
    next draw uses base sigma (byte-identical to the no-jam draw at that step).

    Concretely: two receivers share a seed and the SAME bearing-pair history
    (built with the jammer up).  On the NEXT update one keeps the jammer up,
    the other lifts it (jammers=()).  The lifted one's new bearing must equal
    the base-sigma draw — i.e. it must DIFFER from the still-jammed draw, and
    match a base-sigma reference draw off the same rng state."""
    seed = 2024
    jam = _default_growler()
    radar = _make_radar(pos=EMITTER_POS, antenna_m=20.0)

    # Build identical jammed history on two receivers (and a reference whose
    # rng we will compare the lifted draw against).
    def build():
        e = ElintReceiver(rng=np.random.default_rng(seed), height_fn=_flat(0.0))
        for dp in _drone_positions(20):
            e.update(dp, [(EMITTER_ID, radar)], jammers=[jam])
        return e

    still_jammed = build()
    lifted = build()

    # One more step at a fresh cross-track position: jammed vs lifted.
    next_dp = np.array([35_000.0, DRONE_ALT, 0.0], dtype=np.float64)
    still_jammed.update(next_dp, [(EMITTER_ID, radar)], jammers=[jam])
    lifted.update(next_dp, [(EMITTER_ID, radar)], jammers=())

    br_jammed = still_jammed._pairs[EMITTER_ID][-1][1]
    br_lifted = lifted._pairs[EMITTER_ID][-1][1]

    # The two rng streams were identical up to this draw; the only difference
    # is sigma_eff.  Base sigma != jammed sigma so the SAME standard-normal
    # sample scales differently -> the drawn bearings differ.
    assert br_jammed != br_lifted

    # And the lifted draw must equal the base-sigma reconstruction: the noise
    # term is (drawn_bearing - true_bearing) normalised; with base sigma it is
    # exactly base_sigma * z, where z is the standard-normal the rng produced.
    true_bearing = math.atan2(
        EMITTER_POS[0] - next_dp[0], EMITTER_POS[2] - next_dp[2])
    noise_lifted = (br_lifted - true_bearing + math.pi) % (2 * math.pi) - math.pi
    noise_jammed = (br_jammed - true_bearing + math.pi) % (2 * math.pi) - math.pi
    # Same z, sigma_lifted = base, sigma_jammed = base*(1+K*floor) > base.
    # Compute the floor with the SAME flat height_fn the receiver used.
    floor = ew.noise_floor_at(next_dp, [jam], height_fn=_flat(0.0))
    ratio = 1.0 + EW_ELINT_SIGMA_K * floor
    assert ratio > 1.0
    # noise_jammed / noise_lifted == ratio (same z), within fp tolerance.
    assert abs(noise_jammed - noise_lifted * ratio) < 1e-9 * (abs(noise_jammed) + 1.0)
