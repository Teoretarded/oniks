"""SALVO / ripple-fire scheduler (M6) — pure, headless, GL-free.

The salvo is a thin SCHEDULER over the existing per-tube launch path: it never
introduces a new outcome roll (each round flies the same physics) and never
reads enemy truth (it counts only the player's OWN ready tubes — friendly
own-force logistics, exempt from the radar gate exactly like the battery
panel).  These tests pin the spec's five contracts against a FAKE world that
mimics the launch contract (``launch``/``launch_sam`` fire the next ready tube
and return the round, or None when none are ready), so the logic is proven
without GL or a full CombatWorld.

Contracts (spec 07 §SALVO test contracts):
  (a) RIPPLE with N ready tubes + interval I launches exactly N rounds at
      t=0, I, 2I, ... and then stops (count_left -> 0).
  (b) a salvo never fires a RELOADING/EMPTY tube: when the world returns None
      (no ready tube) the queue no-ops that beat and clears gracefully.
  (c) determinism: same seed+config+target -> identical FAN aim points across
      two runs (the FAN offset is a SEEDED deterministic child stream).
  (d) TOT: per-round launch delays are monotone with flight time so estimated
      arrivals coincide (longer-flight rounds launch FIRST).
  (e) the salvo respects the active platform (an s300 salvo calls launch_sam).
"""

import numpy as np
import pytest

from game.salvo import (FAN_TAG, RIPPLE_INTERVAL_S, SALVO_MODES, SalvoQueue,
                        fan_offset, next_salvo_mode, ready_tube_count,
                        tot_delays)


# --------------------------------------------------------------- fake world

class _FakeWorld:
    """Mimics the CombatWorld launch contract for the scheduler: a finite pool
    of ready tubes that ``launch``/``launch_sam`` drain one per call, returning
    a sentinel round (recording the aim) or None when dry.  Also exposes the
    tube dicts the ready-count helper reads, and a _config.seed for FAN."""

    def __init__(self, n_oniks_ready=4, n_s300_ready=0, seed=1337):
        self._oniks_tubes = [{"loaded": i < n_oniks_ready, "reload_left": 0.0}
                             for i in range(8)]
        self._s300_tubes = [{"reload_left": (0.0 if i < n_s300_ready else 5.0)}
                            for i in range(4)]
        self.sam_ammo = n_s300_ready
        self._config = type("C", (), {"seed": seed})()
        self.oniks_launches = []
        self.sam_launches = []

    # --- the launch contract the scheduler drives -------------------------
    def launch(self, profile, target_point, waypoints=(), weapon_id="oniks"):
        tube = next((t for t in self._oniks_tubes
                     if t["loaded"] and t["reload_left"] <= 0.0), None)
        if tube is None:
            return None
        tube["loaded"] = False
        tube["reload_left"] = 1.0
        rnd = {"aim": np.asarray(target_point, dtype=float).copy(),
               "weapon": weapon_id}
        self.oniks_launches.append(rnd)
        return rnd

    def launch_sam(self, aircraft_id, round_id="48n6"):
        tube = next((t for t in self._s300_tubes if t["reload_left"] <= 0.0
                     and self.sam_ammo > 0), None)
        if tube is None:
            return None
        tube["reload_left"] = 1.0
        self.sam_ammo -= 1
        rnd = {"target": aircraft_id, "round": round_id}
        self.sam_launches.append(rnd)
        return rnd


def _drive(queue, world, total_t, dt=1.0 / 120.0):
    """Step a queue to completion, recording (sim_t, fired?) per launch."""
    t = 0.0
    fired_times = []
    n = int(round(total_t / dt))
    for _ in range(n):
        before = len(world.oniks_launches) + len(world.sam_launches)
        queue.tick(dt, world)
        after = len(world.oniks_launches) + len(world.sam_launches)
        if after > before:
            fired_times.append(t)
        t += dt
    return fired_times


# ----------------------------------------------------------------- mode cycle

def test_salvo_modes_are_the_three_doctrine_modes():
    assert SALVO_MODES == ("ripple", "fan", "tot")


def test_next_salvo_mode_cycles_and_wraps():
    assert next_salvo_mode("ripple") == "fan"
    assert next_salvo_mode("fan") == "tot"
    assert next_salvo_mode("tot") == "ripple"
    assert next_salvo_mode("garbage") == "ripple"   # unknown -> first


# ------------------------------------------------------- ready-tube counting

def test_ready_tube_count_oniks_counts_only_loaded_recocked_tubes():
    w = _FakeWorld(n_oniks_ready=3)
    assert ready_tube_count(w, "bastion") == 3


def test_ready_tube_count_excludes_reloading_tube():
    w = _FakeWorld(n_oniks_ready=4)
    w._oniks_tubes[0]["loaded"] = False
    w._oniks_tubes[0]["reload_left"] = 2.0            # mid-reload, not ready
    assert ready_tube_count(w, "bastion") == 3


def test_ready_tube_count_s300_counts_recocked_tubes_with_ammo():
    w = _FakeWorld(n_s300_ready=2)
    assert ready_tube_count(w, "s300") == 2


def test_ready_tube_count_sandbox_world_is_zero():
    class _S:                                          # no tube dicts
        pass
    assert ready_tube_count(_S(), "bastion") == 0
    assert ready_tube_count(_S(), "s300") == 0


# ------------------------------------------------------ (a) RIPPLE timing

def test_ripple_fires_exactly_n_ready_tubes_at_the_interval_then_stops():
    w = _FakeWorld(n_oniks_ready=4)
    q = SalvoQueue()
    q.start("bastion", mode="ripple", count=ready_tube_count(w, "bastion"),
            interval=1.5, profile="hi-lo", target_point=(0.0, 0.0, 100_000.0))
    fired = _drive(q, w, total_t=7.0)
    assert len(w.oniks_launches) == 4                 # exactly the ready tubes
    assert q.count_left == 0 and not q.active
    # t = 0, 1.5, 3.0, 4.5 (within a single 120 Hz step quantisation).
    assert fired[0] == pytest.approx(0.0, abs=1.0 / 60.0)
    for k, want in enumerate((0.0, 1.5, 3.0, 4.5)):
        assert fired[k] == pytest.approx(want, abs=1.0 / 60.0)


def test_ripple_default_interval_used_when_unspecified():
    w = _FakeWorld(n_oniks_ready=2)
    q = SalvoQueue()
    q.start("bastion", mode="ripple", count=2, profile="hi-lo",
            target_point=(0.0, 0.0, 100_000.0))
    fired = _drive(q, w, total_t=2 * RIPPLE_INTERVAL_S + 1.0)
    assert len(w.oniks_launches) == 2
    assert fired[1] == pytest.approx(RIPPLE_INTERVAL_S, abs=1.0 / 60.0)


# --------------------------------------------- (b) never fires an empty tube

def test_salvo_stops_gracefully_when_magazine_drains_mid_salvo():
    # Queue asks for 4 but only 2 tubes are actually ready: the world returns
    # None on beats 3-4; the queue must no-op them and clear (not hang/crash).
    w = _FakeWorld(n_oniks_ready=2)
    q = SalvoQueue()
    q.start("bastion", mode="ripple", count=4, interval=0.5,
            profile="hi-lo", target_point=(0.0, 0.0, 100_000.0))
    _drive(q, w, total_t=4.0)
    assert len(w.oniks_launches) == 2                 # only the ready tubes flew
    assert not q.active and q.count_left == 0


def test_idle_queue_tick_is_a_noop():
    w = _FakeWorld(n_oniks_ready=4)
    q = SalvoQueue()
    q.tick(1.0, w)                                    # never started
    assert not w.oniks_launches and not q.active


# ----------------------------------------------------- (c) FAN determinism

def test_fan_offset_is_deterministic_per_seed_and_ordinal():
    a = fan_offset(1337, 0)
    b = fan_offset(1337, 0)
    assert np.allclose(a, b)                          # same seed+ordinal


def test_fan_offset_varies_by_ordinal_and_seed():
    assert not np.allclose(fan_offset(1337, 0), fan_offset(1337, 1))
    assert not np.allclose(fan_offset(1337, 0), fan_offset(42, 0))


def test_fan_salvo_aim_points_reproducible_across_two_runs():
    target = (10_000.0, 0.0, 120_000.0)
    aims = []
    for _ in range(2):
        w = _FakeWorld(n_oniks_ready=4, seed=2024)
        q = SalvoQueue()
        q.start("bastion", mode="fan", count=4, interval=0.5,
                profile="hi-lo", target_point=target)
        _drive(q, w, total_t=3.0)
        aims.append([r["aim"].copy() for r in w.oniks_launches])
    assert len(aims[0]) == 4
    for r0, r1 in zip(aims[0], aims[1]):
        assert np.allclose(r0, r1)                    # bit-identical aim points


def test_fan_spreads_rounds_off_the_single_aim_point():
    target = np.array([10_000.0, 0.0, 120_000.0])
    w = _FakeWorld(n_oniks_ready=4, seed=7)
    q = SalvoQueue()
    q.start("bastion", mode="fan", count=4, interval=0.5,
            profile="hi-lo", target_point=tuple(target))
    _drive(q, w, total_t=3.0)
    # At least one round's aim is meaningfully off the bare aim point (a fan).
    spreads = [float(np.hypot(r["aim"][0] - target[0], r["aim"][2] - target[2]))
               for r in w.oniks_launches]
    assert max(spreads) > 1.0


def test_ripple_aim_points_are_all_the_bare_target():
    target = np.array([10_000.0, 0.0, 120_000.0])
    w = _FakeWorld(n_oniks_ready=3, seed=7)
    q = SalvoQueue()
    q.start("bastion", mode="ripple", count=3, interval=0.5,
            profile="hi-lo", target_point=tuple(target))
    _drive(q, w, total_t=3.0)
    for r in w.oniks_launches:
        assert np.allclose(r["aim"], target)          # ripple: no spread


# ----------------------------------------------------------- (d) TOT delays

def test_tot_delays_monotone_with_flight_time():
    # Three rounds with INCREASING range -> increasing flight time. The longest
    # flight must launch FIRST (smallest delay), so delays are non-increasing in
    # range order, and the implied arrival times coincide within tolerance.
    ranges = [80_000.0, 120_000.0, 160_000.0]
    speed = 700.0
    delays = tot_delays(ranges, speed, margin=2.0)
    assert len(delays) == 3
    # Round with the longest range launches first (delay 0); shorter ranges wait.
    assert delays[2] == pytest.approx(0.0, abs=1e-6)
    assert delays[0] >= delays[1] >= delays[2]
    # Arrivals (delay + flight) coincide.
    arrivals = [d + r / speed for d, r in zip(delays, ranges)]
    assert max(arrivals) - min(arrivals) < 1e-6


def test_tot_delays_all_zero_for_equal_ranges():
    delays = tot_delays([100_000.0, 100_000.0], 700.0, margin=0.0)
    assert all(d == pytest.approx(0.0) for d in delays)


def test_tot_delays_degenerate_zero_speed_is_safe():
    delays = tot_delays([100_000.0], 0.0, margin=1.0)   # no divide-by-zero
    assert delays == [0.0]


# ----------------------------------------------- (e) platform routing (s300)

def test_s300_salvo_calls_launch_sam_with_the_air_track():
    w = _FakeWorld(n_oniks_ready=0, n_s300_ready=2)
    q = SalvoQueue()
    q.start("s300", mode="ripple", count=2, interval=0.5, target_id="awacs_00",
            round_id="48n6")
    _drive(q, w, total_t=2.0)
    assert len(w.sam_launches) == 2 and not w.oniks_launches
    assert all(r["target"] == "awacs_00" for r in w.sam_launches)
    assert all(r["round"] == "48n6" for r in w.sam_launches)


def test_s300_salvo_stops_when_battery_empties():
    w = _FakeWorld(n_oniks_ready=0, n_s300_ready=1)
    q = SalvoQueue()
    q.start("s300", mode="ripple", count=3, interval=0.3, target_id="awacs_00")
    _drive(q, w, total_t=2.0)
    assert len(w.sam_launches) == 1 and not q.active


def test_fan_tag_is_a_named_constant():
    assert isinstance(FAN_TAG, int)                   # the [seed, FAN_TAG, ...] tag
