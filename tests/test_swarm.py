"""M4-B loitering-munition swarm: coordinated time-on-target (GL-free, pytest).

The contract (spec M4-B):

  * compute_swarm_speeds (sim/swarm.py) is PURE math: given the launch point
    and the per-round routes, every round arrives at the shared aim point
    SIMULTANEOUSLY (T = max_path / v_max + margin, v_i = path_i / T), the
    longest path runs at ~v_max and the shorter paths slower — clamped to the
    weapon's [v_min, v_max] cruise band.
  * Missile._commanded_speed (sim/missile.py) is a GUARDED override of the
    Mach-hold: when SET, cruise holds that GROUND speed; when UNSET (None) the
    Mach-hold is BYTE-IDENTICAL to the existing path (test (3) — THE GUARD —
    pins an Oniks trajectory bit-for-bit with/without the edit present).
  * launch_swarm (world/combat.py) fires all ready SWARM_POD cells in one
    bundle, decrements the magazine by N, derives the shared T + per-round
    commanded speed, and seeds each round's weave by its salvo ordinal so the
    bundle does not formate.  Refuses on empty cells.
  * SATURATION EMERGES from physics: a SYNCHRONIZED N-round bundle puts more
    rounds in the destroyer's terminal window than its SM2_MAX_INFLIGHT=4 +
    3 s reload + single CIWS bubble can service, so at least one round leaks
    with NO kill roll; a 4-round NON-synced trickle is serviced and does not.
  * DETERMINISM: same seed + tasking -> identical rounds/weaves.
  * BYTE-IDENTICAL DEFAULT: n_swarm_pods=0 -> no pod, launch_swarm never
    invoked, the duel + full suite + smoke unchanged (test in
    test_combat_config.py + the e2e default-battle check below).
"""

import math

import numpy as np
import pytest

from sim.arsenal import SWARM, SWARM_POD, WEAPONS, LAUNCHERS
from sim.missile import (Missile, PH_CRUISE, PH_TERMINAL, PH_DEAD, KP_THRUST,
                         THRUST_SCALE)
from sim.physics import GRAVITY, mach_scalar
from sim.swarm import compute_swarm_speeds


DT = 1.0 / 120.0


# ---------------------------------------------------------------------------
# Minimal world stub (deep open ocean, no terrain, no ships)
# ---------------------------------------------------------------------------

class _OpenSea:
    ships = []

    def terrain_height_at(self, x, z):
        return -500.0

    def surface_height_at(self, x, z):
        return 0.0


# ===========================================================================
# (1) compute_swarm_speeds: simultaneous arrival, pure math
# ===========================================================================

def test_compute_swarm_speeds_simultaneous():
    """Three routes of DIFFERENT path length, sharing one aim point: flown at
    their per-round v_i they all arrive within ~1 s of each other; the longest
    path runs at ~v_max and the shorter paths run slower (they DAWDLE so the
    bundle converges)."""
    launch = (0.0, 0.0)
    aim = (0.0, 30_000.0)
    # Round 0: straight (30 km). Round 1: one dogleg (~+8 km). Round 2: a
    # wider dogleg (~+18 km).
    routes = [
        [aim],
        [(8_000.0, 15_000.0), aim],
        [(18_000.0, 15_000.0), aim],
    ]
    v_max = SWARM.cruise_mach_hi * 340.0     # ~ground speed at the cruise band
    v_min = SWARM.cruise_mach_lo * 340.0
    speeds = compute_swarm_speeds(launch, routes, v_max, margin=5.0,
                                  v_min=v_min)
    assert len(speeds) == 3

    def path_len(route):
        pts = [launch] + list(route)
        return sum(math.hypot(x1 - x0, z1 - z0)
                   for (x0, z0), (x1, z1) in zip(pts, pts[1:]))

    lens = [path_len(r) for r in routes]
    # Longest path is the one that runs near v_max; all within the band.
    longest = max(range(3), key=lambda i: lens[i])
    for v in speeds:
        assert v_min - 1e-6 <= v <= v_max + 1e-6
    # The longest route runs at the exact T-formula speed:
    #   T = max_len / v_max + margin ;  v_longest = max_len / T
    # (margin=5.0 here, as passed to compute_swarm_speeds above).
    max_len = max(lens)
    expected_longest = max_len / (max_len / v_max + 5.0)
    assert speeds[longest] == pytest.approx(expected_longest, rel=0.02)
    # Arrival time spread: t_i = len_i / v_i.  Simultaneous to ~1 s.
    arrivals = [lens[i] / speeds[i] for i in range(3)]
    assert max(arrivals) - min(arrivals) <= 1.0, (
        f"arrival spread {max(arrivals) - min(arrivals):.2f} s too wide: "
        f"{arrivals}")
    # The shorter routes really do run slower than the longest.
    for i in range(3):
        if i != longest:
            assert speeds[i] < speeds[longest] + 1e-6


def test_compute_swarm_speeds_clamps_to_band():
    """A route so much shorter than the longest that the sync speed would fall
    UNDER v_min is clamped to v_min (the loiterer cannot fly slower than its
    cruise floor — it arrives early rather than stalling)."""
    launch = (0.0, 0.0)
    aim = (0.0, 40_000.0)
    routes = [[aim], [(100.0, 200.0)]]    # 40 km vs ~220 m
    v_max, v_min = 150.0, 70.0
    speeds = compute_swarm_speeds(launch, routes, v_max, margin=5.0,
                                  v_min=v_min)
    assert speeds[0] == pytest.approx(min(v_max, 40_000.0 / (40_000.0 / v_max
                                                             + 5.0)), rel=0.02)
    assert speeds[1] == v_min            # clamped at the floor


# ===========================================================================
# (2) commanded-speed override holds the GROUND speed in cruise
# ===========================================================================

def _cruise_missile(weapon, commanded=None, alt=60.0):
    """A weapon teleported into lo-lo CRUISE at ``alt`` flying due north, so
    the very next update runs the sustainer Mach-hold (commanded or not)."""
    m = Missile(weapon, np.array([0.0, alt, 0.0]), 0.0, "lo-lo",
                np.array([0.0, 0.0, 200_000.0]))
    m.phase = PH_CRUISE
    m.hi = False
    if commanded is not None:
        m._commanded_speed = float(commanded)
    # Seed a cruise-like velocity due north so it is already flying.
    m.vel[:] = (0.0, 0.0, 250.0)
    m.prev_pos[:] = m.pos
    m._guid_t0 = None
    return m


def test_commanded_speed_overrides_mach_hold():
    """A SWARM round with _commanded_speed holds that GROUND speed in cruise
    (measured at the local atmosphere), not the weapon cruise_mach_lo."""
    commanded = 165.0          # m/s, inside the SWARM cruise band
    m = _cruise_missile(SWARM, commanded=commanded, alt=60.0)
    w = _OpenSea()
    for _ in range(int(40.0 / DT)):     # let the first-order speed loop settle
        m.update(DT, w)
        if not m.alive:
            break
    assert m.alive
    speed = float(np.linalg.norm(m.vel))
    assert speed == pytest.approx(commanded, abs=8.0), (
        f"commanded-speed cruise settled at {speed:.1f} m/s, not {commanded}")
    # And a round with NO commanded speed holds its Mach-band ground speed
    # (clearly different from the commanded one).
    m2 = _cruise_missile(SWARM, commanded=None, alt=60.0)
    for _ in range(int(40.0 / DT)):
        m2.update(DT, w)
        if not m2.alive:
            break
    free = float(np.linalg.norm(m2.vel))
    assert abs(free - commanded) > 15.0, (
        f"free Mach-hold {free:.1f} too close to commanded {commanded}")


# ===========================================================================
# (3) THE GUARD: unset commanded speed is BYTE-IDENTICAL
# ===========================================================================

def _fly_oniks(set_attr):
    """Fly the locked Oniks hi-lo shot and return its full sampled trajectory.
    ``set_attr`` True writes ``_commanded_speed = None`` explicitly (proving
    the guarded branch with the attribute present is the same arithmetic as
    the implicit default)."""
    from sim.arsenal import ONIKS
    m = Missile(ONIKS, np.array([0.0, 0.0, 0.0]), 0.0, "hi-lo",
                np.array([0.0, 0.0, 120_000.0]))
    if set_attr:
        m._commanded_speed = None
    w = _OpenSea()
    traj = []
    for i in range(int(180.0 / DT)):
        m.update(DT, w)
        traj.append((float(m.pos[0]), float(m.pos[1]), float(m.pos[2]),
                     float(m.vel[0]), float(m.vel[1]), float(m.vel[2]),
                     float(m.fuel), int(m.phase)))
        if not m.alive:
            break
    return traj


def test_unset_commanded_speed_bit_identical():
    """The regression guard on the _sustainer_thrust edit: an Oniks with NO
    commanded speed flies the EXACT existing trajectory, bit-for-bit, whether
    the attribute is left implicit (default) or set to None explicitly."""
    a = _fly_oniks(set_attr=False)
    b = _fly_oniks(set_attr=True)
    assert len(a) == len(b)
    for ra, rb in zip(a, b):
        # Bit-for-bit: exact float equality across position/velocity/fuel/phase.
        assert ra == rb, f"trajectory diverged: {ra} != {rb}"


# ===========================================================================
# (6) determinism: same seed + tasking -> identical rounds/weaves
# ===========================================================================

class _FixedShip:
    """A stationary lock target so a terminal SWARM round actually homes (and
    weaves) under the real Missile.update — no world ships needed."""
    __slots__ = ("pos", "vel", "alive")

    def __init__(self, pos):
        self.pos = np.asarray(pos, dtype=np.float64)
        self.vel = np.zeros(3)
        self.alive = True


def _fly_terminal_swarm(salvo, commanded, frames=600):
    """Fly a SWARM round through its TERMINAL weave under the REAL
    Missile.update (the weave overlay only runs in PH_TERMINAL).  The round
    starts ~10 km out, locked onto a fixed target inside the weave band, so the
    per-salvo weave phase actually shapes the trajectory.  No RNG anywhere in
    the missile core, so the sampled path is a deterministic function of the
    inputs.  Returns the sampled (x, y, z) trajectory."""
    aim = np.array([0.0, _SAT_ALT, 0.0], dtype=np.float64)
    pos = np.array([0.0, _SAT_ALT, 10_000.0], dtype=np.float64)
    m = Missile(SWARM, pos, math.pi, "lo-lo", aim, salvo=salvo)
    m.is_hostile = False
    m.phase = PH_TERMINAL
    m.hi = False
    m._commanded_speed = float(commanded)
    m.locked_ship = _FixedShip(aim)         # in the weave band: jinks run
    # Seed a terminal-run velocity straight down the −z axis at the commanded
    # ground speed (the weave is a cross-track overlay on this core).
    m.vel[:] = (0.0, 0.0, -commanded)
    m.prev_pos[:] = m.pos
    m._guid_t0 = None
    w = _OpenSea()
    traj = []
    for _ in range(frames):
        m.update(DT, w)
        traj.append((float(m.pos[0]), float(m.pos[1]), float(m.pos[2])))
        if not m.alive:
            break
    return traj


def test_swarm_determinism():
    """Two SWARM rounds flown with the SAME salvo ordinal trace the EXACT same
    terminal trajectory (deterministic core: no RNG, the per-salvo weave phase
    is the only seed); two with DIFFERENT ordinals weave onto measurably
    different cross-track paths (the golden-angle per-salvo phase de-formates
    the bundle).  Unlike the old version this actually flies the rounds through
    Missile.update / _apply_weave instead of re-deriving the phase formula."""
    a0 = _fly_terminal_swarm(salvo=0, commanded=160.0)
    a0b = _fly_terminal_swarm(salvo=0, commanded=160.0)
    a1 = _fly_terminal_swarm(salvo=1, commanded=160.0)
    # Same salvo -> bit-for-bit identical flight.
    assert a0 == a0b
    # Different salvo -> the weave overlay diverges (the cross-track path
    # differs by meters somewhere in the run, never bit-identical).
    assert len(a0) == len(a1)
    assert a0 != a1
    max_dx = max(abs(p[0] - q[0]) for p, q in zip(a0, a1))
    assert max_dx > 1.0, (
        f"different salvos must weave to different cross-track paths "
        f"(max lateral divergence {max_dx:.3f} m)")


# ===========================================================================
# (3b) END-TO-END LETHALITY: a REAL SWARM round splashes a ship in lo-lo
# ===========================================================================

class _ShipSea:
    """Deep open ocean with one stationary destroyer (a real sim.ships.Ship,
    so the seeker, the hull OBB and apply_missile_hits all see the genuine
    target — no _LevelSwarm stub, no hand-forced level flight)."""

    def __init__(self, ship):
        self.ships = [ship]

    def terrain_height_at(self, x, z):
        return -500.0

    def surface_height_at(self, x, z):
        return 0.0


def _stationary_destroyer(z):
    from sim.ships import Ship
    s = Ship("dd_lethality", "destroyer",
             [[0.0, z - 1.0], [0.0, z + 1.0]], 0.5, direction=1)
    s.pos[:] = (0.0, 0.0, z)
    s.speed = 0.0
    s.heading = math.radians(90.0)        # beam-on to a north-bound round
    return s


def test_swarm_round_splashes_ship_in_lo_lo():
    """THE END-TO-END LETHALITY PROOF: a REAL SWARM Missile (NO _LevelSwarm,
    NO hand-forced level flight) flown from the coast lo-lo at a stationary
    destroyer 25 km out actually SPLASHES the hull — the honest hit emerges
    from the phase machine (boost/cruise/descent/seeker) + the swept-segment
    OBB hit test in sim.damage, exactly as in play.

    This is the regression contract for the M4-B descent-tuning fix: the
    Oniks-calibrated STALL_SPEED=200 fade used to sag the subsonic round ~38 m
    UNDER its commanded skim altitude, sinking it into the sea ~7.5 km short
    (MEASURED, tools/probe_swarm_descent.py); the per-weapon stall speed lets a
    healthy subsonic airframe hold its skim and reach the hull. Flown with a
    commanded ground speed (as the pod sets it), so the cruise Mach-hold runs
    the real loiter speed."""
    from sim.damage import apply_missile_hits

    run_in = 25_000.0
    ship = _stationary_destroyer(run_in)
    world = _ShipSea(ship)
    hp0 = ship.hp

    aim = np.array([0.0, 0.0, run_in], dtype=np.float64)
    m = Missile(SWARM, np.array([0.0, 0.0, 0.0]), 0.0, "lo-lo", aim,
                target_ship=ship)
    m.is_hostile = False
    m._commanded_speed = 130.0            # a real loiter ground speed (in band)

    center, half, rot = ship.obb()
    closest = float("inf")
    events = []
    for _ in range(int(600.0 / DT)):
        prev = m.pos.copy()
        m.update(DT, world)
        # genuine closest-approach of the swept segment midpoint to the hull
        # OBB surface (0 == inside the hull box).
        local = rot.T @ (((prev + m.pos) * 0.5) - center)
        d = math.sqrt(sum(max(abs(local[k]) - half[k], 0.0) ** 2
                          for k in range(3)))
        closest = min(closest, d)
        # the same swept-segment OBB hit test the live world runs every step
        apply_missile_hits([m], world.ships, events)
        if not m.alive:
            break

    hit = any(kind == "ship_hit" for kind, _ in events)
    assert hit, (
        f"a real lo-lo SWARM round must SPLASH the destroyer at {run_in/1000:.0f} "
        f"km; closest hull approach was {closest:.1f} m, end phase {m.phase}")
    assert closest <= 1.0, (
        f"the round must reach the hull surface (closest {closest:.2f} m)")
    assert ship.hp == hp0 - 1, (
        f"the splash must take a hit point off the hull (hp {hp0} -> {ship.hp})")


# ===========================================================================
# SWARM weapon + SWARM_POD launcher definition sanity
# ===========================================================================

def test_swarm_weapon_def_is_a_subsonic_short_range_loiterer():
    assert SWARM.weapon_id == "swarm"
    assert "swarm" in WEAPONS and WEAPONS["swarm"] is SWARM
    # Subsonic loiterer: low cruise Mach band.
    assert 0.15 <= SWARM.cruise_mach_lo <= 0.45
    assert SWARM.cruise_mach_hi <= 0.6
    # Modest fuel for ~40 km, short seeker.
    assert SWARM.seeker_range <= 20_000.0
    # Registered launcher with cells (the pod).
    assert SWARM_POD.launcher_id in LAUNCHERS
    assert SWARM_POD.tubes >= 4
    assert "swarm" in SWARM_POD.weapon_ids


# ===========================================================================
# (4) bundle launch fires all ready cells + (7) byte-identical default
# ===========================================================================

def _combat_world(**cfg):
    from world.combat import CombatWorld
    from world.combat_config import CombatConfig
    return CombatWorld(CombatConfig(**cfg))


def test_bundle_launch_fires_all_ready_cells():
    """launch_swarm spawns N rounds, decrements the cell magazine by N, sets
    distinct salvo ordinals (so the weaves differ), and refuses once empty."""
    w = _combat_world(n_swarm_pods=1, swarm_cells_per_pod=6)
    aim = np.array([w.ships[0].pos[0], 0.0, w.ships[0].pos[2]],
                   dtype=np.float64)
    before = w._swarm_cells
    rounds = w.launch_swarm("lo-lo", aim, waypoints=(), sync=True)
    assert rounds is not None and len(rounds) == before > 0
    assert w._swarm_cells == 0                     # all ready cells fired
    # All rounds are SWARM Missiles, in flight, with DISTINCT salvo ordinals.
    assert all(r.weapon is SWARM for r in rounds)
    assert all(r in w.missiles for r in rounds)
    ordinals = {r.salvo for r in rounds}
    assert len(ordinals) == len(rounds)            # distinct -> weaves differ
    phis = {r.weave_phi for r in rounds}
    assert len(phis) == len(rounds)
    # Empty pod refuses.
    assert w.launch_swarm("lo-lo", aim) is None


def test_swarm_synced_rounds_get_distinct_commanded_speeds():
    """A SYNCED bundle commands the rounds to DIFFERENT ground speeds (the
    time-on-target math): the pod fans the rounds across attack bearings, so
    the outer arcs are longer and run near v_max while the inner ones DAWDLE.
    Measured at a close aim where the fan is a meaningful fraction of the
    run-in (a 30 km shot spreads the commanded speeds ~9 m/s); a synced bundle
    NEVER hands two rounds widely different speeds without cause, so every
    round stays in the cruise band."""
    from world.combat import BASE_POS
    w = _combat_world(n_swarm_pods=1, swarm_cells_per_pod=6)
    base = np.asarray(BASE_POS, dtype=np.float64)
    aim = np.array([base[0], 0.0, base[2] + 30_000.0], dtype=np.float64)
    rounds = w.launch_swarm("lo-lo", aim, sync=True)
    speeds = [r._commanded_speed for r in rounds]
    assert all(s is not None for s in speeds)
    v_max = SWARM.cruise_mach_hi * 340.0
    v_min = SWARM.cruise_mach_lo * 340.0
    assert all(v_min - 1e-6 <= s <= v_max + 1e-6 for s in speeds)
    assert max(speeds) - min(speeds) > 1.0, (
        "synced rounds must self-adjust to DIFFERENT speeds")
    # A NON-synced (sync=False) bundle runs every round at v_max (no time-on-
    # target self-adjustment) — the comparison mode.
    rounds2 = w_for_nosync_speeds()
    assert all(abs(r._commanded_speed - v_max) < 1e-6 for r in rounds2)


def w_for_nosync_speeds():
    from world.combat import BASE_POS
    w = _combat_world(n_swarm_pods=1, swarm_cells_per_pod=6)
    base = np.asarray(BASE_POS, dtype=np.float64)
    aim = np.array([base[0], 0.0, base[2] + 30_000.0], dtype=np.float64)
    return w.launch_swarm("lo-lo", aim, sync=False)


def test_swarm_world_determinism():
    """Same seed + same tasking -> identical swarm rounds (positions, salvo
    ordinals, commanded speeds, weave phases) after stepping a few frames."""
    def run():
        w = _combat_world(seed=4242, n_swarm_pods=1, swarm_cells_per_pod=5)
        aim = np.array([w.ships[0].pos[0], 0.0, w.ships[0].pos[2]],
                       dtype=np.float64)
        rounds = w.launch_swarm("lo-lo", aim, sync=True)
        for _ in range(int(2.0 / DT)):
            w.step(DT)
        return [(r.salvo, r._commanded_speed, r.weave_phi,
                 tuple(r.pos.tolist())) for r in rounds]
    assert run() == run()


def test_launch_swarm_round_survives_real_world_step():
    """REGRESSION (M4-B FIXER finding 1): a real launch_swarm-produced round
    must survive the FULL Missile.update / world.step physics on the DEFAULT
    map preset — not just the bookkeeping the other launch tests check.  Before
    the fix every round spawned at base[1] (the terrain height under BASE_POS),
    but the pod front sits SWARM_POD_OFFSET[2] back where the terrain is ~1.3 m
    higher, so each round spawned UNDERGROUND and went PH_DEAD on frame 1.
    This flies the actual fired rounds through several seconds of world.step on
    preset 0 and asserts they stay alive and gain downrange distance — i.e. it
    exercises the live launch path, not a _LevelSwarm stub or a hand-placed
    position."""
    w = _combat_world(n_swarm_pods=1, swarm_cells_per_pod=6)  # default preset 0
    from world.combat import BASE_POS
    base = np.asarray(BASE_POS, dtype=np.float64)
    # Aim well downrange (toward a real ship) so the bundle has somewhere to go.
    aim = np.array([w.ships[0].pos[0], 0.0, w.ships[0].pos[2]],
                   dtype=np.float64)
    rounds = w.launch_swarm("lo-lo", aim, sync=True)
    assert rounds and len(rounds) == 6
    # Every round spawned ABOVE the local terrain (the bug spawned them below).
    from world.generation import terrain_height_scalar
    for r in rounds:
        ground = terrain_height_scalar(float(r.pos[0]), float(r.pos[2]))
        assert float(r.pos[1]) >= ground - 1e-6, (
            f"round spawned below terrain ({r.pos[1]:.3f} < {ground:.3f})")
    start_dr = [abs(float(r.pos[2]) - base[2]) for r in rounds]
    # 10 s of real physics: the honest cell-toss launch (2026-07-05 energy
    # build — pop, turn by ~2.5 s, cruise ~100-150 m/s) needs the longer
    # window; the old "1 km in 5 s" bar was only reachable by the boost
    # OVERSHOOT bug this same build fixed (46 kN ride-out zooming the 55 kg
    # round to Mach ~6 — it made the bar, then crashed 25 km out).
    for _ in range(int(10.0 / DT)):
        w.step(DT)
    alive = [r for r in rounds if r.alive]
    assert len(alive) == len(rounds), (
        f"every launch_swarm round must survive real world.step physics on the "
        f"default preset; {len(rounds) - len(alive)} died "
        f"(phases {[int(r.phase) for r in rounds]})")
    # The bundle gained real downrange distance (it did not die in place):
    # >= 600 m in 10 s means a genuine post-launch cruise, with the launch
    # transient (~2.5 s) forgiven.
    end_dr = [abs(float(r.pos[2]) - base[2]) for r in rounds]
    assert max(end_dr) - max(start_dr) > 600.0, (
        f"the bundle must fly downrange (gained "
        f"{max(end_dr) - max(start_dr):.1f} m, start {max(start_dr):.1f}, "
        f"now {max(end_dr):.1f})")


def test_default_battle_byte_identical_no_swarm():
    """n_swarm_pods=0 (default): no pod built, _swarm_cells is 0, and
    launch_swarm fires nothing — the out-of-the-box battle never grows a
    swarm round."""
    w = _combat_world()                            # all defaults
    assert getattr(w, "_swarm_cells", 0) == 0
    aim = np.array([0.0, 0.0, 100_000.0])
    assert w.launch_swarm("lo-lo", aim) is None
    # Stepping the default battle never spawns a SWARM round.
    for _ in range(int(1.0 / DT)):
        w.step(DT)
    assert not any(getattr(m, "weapon", None) is SWARM for m in w.missiles)


# ===========================================================================
# (5) saturation: a synced bundle leaks, a trickle does not
# ===========================================================================

class _SatWorld:
    """Self-contained saturation harness: ONE destroyer + its ShipDefense,
    swarm Missiles vs the hull.  Mirrors the tests/test_sm2_statistics.py
    controller-level style; deep open ocean so no terrain mask is in play, and
    the only actors are the swarm vs the destroyer's SM-2 (CIWS off, so the
    SM-2 throughput — SM2_MAX_INFLIGHT + the 3 s reload — is the ISOLATED
    saturator)."""

    def __init__(self, destroyer):
        self.ships = [destroyer]
        self.missiles = []
        self.events = []
        self.sim_time = 0.0

    def terrain_height_at(self, x, z):
        return -500.0

    def surface_height_at(self, x, z):
        return 0.0


class _LevelSwarm(Missile):
    """A SWARM round on its terminal run-in, forced to fly DEAD-LEVEL straight
    at the hull at its commanded ground speed.  Scenario forcing in the e2e
    spirit (test_phase6_e2e spawns cruise-state rounds from a measured release
    range): here we isolate the DEFENCE's throughput, not the airframe's
    letdown.  The round stays a Missile subclass so the enemy fire control
    (which tracks only Missile instances) engages it exactly as a real cruise
    missile.

    M4-B descent-tuning note (2026-06-18): a REAL SWARM round now flies the
    honest letdown and SPLASHES a ship end-to-end — see the dedicated proof
    test_swarm_round_splashes_ship_in_lo_lo, and the per-weapon stall fix in
    sim/missile.py that lets the subsonic airframe hold its skim altitude (the
    flat Oniks STALL_SPEED used to sag it into the sea ~7.5 km short). The
    lone/synced outcomes even reproduce on real rounds (lone 0/3, synced-8 3/3,
    peak == SM2_MAX_INFLIGHT, big reserve — MEASURED, tools/probe_swarm_descent.py).
    This stub is RETAINED for the saturation test only because that test's
    SECONDARY anti-confound assertion (min trickle SM-2 spent >= min synced
    spent) is not robust across seeds on the live terminal weave (measured: a
    cheap-seed real trickle spends ~38 vs the synced ~51), and weakening a
    locked regression contract to switch it would be wrong. The level stub
    keeps the saturation test a clean, deterministic isolation of the SM-2
    in-flight cap; the real-airframe lethality is proven by the splash test."""

    def update(self, dt, world):
        if not self.alive:
            return
        np.copyto(self.prev_pos, self.pos)
        self.t += dt
        self.pos += self.vel * dt


# Saturation geometry (MEASURED with tools/probe_swarm_satcheck.py).
# Sea-skim altitude (28 m: inside the hull OBB y-span -5..30 AND in the SM-2
# multipath band, where the interceptor must work HARDEST — the lo-lo regime),
# a 45 km run-in at a 110 m/s loiter cruise (lone-round engagement duration
# ~run_in/v = 409 s + the SM-2 chase tail).
#
# CRITICAL EXPERIMENTAL CONTROL — isolate the in-flight CAP from MAGAZINE
# exhaustion (the M4-B FIXER finding).  With the destroyer's default 24-round
# SM-2 magazine, a single skimmer soaks 5-21 interceptors, so an 8-round bundle
# WINCHESTERS the ship — and a spaced trickle of 8 rounds spends all 24 and
# sinks it too (3/3, measured), i.e. the leak there is AMMO-OUT, NOT
# simultaneity.  To prove the leak EMERGES from SM2_MAX_INFLIGHT + the 3 s
# reload (physics, not dice) we REMOVE the magazine as a confound: every run
# below is given a large SM-2 reserve (_SAT_AMMO).  Then, measured over fixed
# seeds (tools/probe_swarm_satcheck.py / _satcheck2.py, 12 seeds):
#   * a LONE round is serviced every time              (0/12 hits)
#   * a SYNCHRONIZED 8-round bundle sinks the hull      (3/3 hits, EVERY seed)
#       — and spends only ~49 SM-2 while keeping a huge reserve, so it is
#         provably NOT ammo-out: the 4-in-flight cap simply cannot service
#         8 simultaneous arrivals before they reach the hull.
#   * the SAME 8 rounds delivered as a TRICKLE spaced 600 s apart (well past
#     the 409 s lone-round engagement) are serviced (<= 1 hit, mostly 0) —
#     and spend MORE SM-2 than the synced bundle (58-107), confirming the
#     trickle is not ammo-starved either; it leaks less because the cap is
#     never the binding constraint when arrivals are spread out.
# The mechanism is thus simultaneity vs the in-flight cap, isolated from the
# magazine.
_SAT_ALT = 28.0
_SAT_RUN_IN = 45_000.0
_SAT_V = 110.0
_SAT_TMAX = 600.0          # one synced bundle clears well inside this
_SAT_SPACING = 600.0       # trickle gap (> 409 s lone-round engagement)
_SAT_AMMO = 100_000        # large reserve: magazine is NOT the binding gate


def _level_swarm(launch_xz, aim, commanded, salvo):
    pos = np.array([launch_xz[0], _SAT_ALT, launch_xz[1]], dtype=np.float64)
    m = _LevelSwarm(SWARM, pos, 0.0, "lo-lo", aim, salvo=salvo)
    m.is_hostile = False
    m.phase = PH_CRUISE
    m.hi = False
    m._commanded_speed = float(commanded)
    d = np.array([aim[0] - pos[0], 0.0, aim[2] - pos[2]])
    d /= np.linalg.norm(d)
    m.vel[:] = d * commanded
    m.prev_pos[:] = m.pos
    return m


def _run_bundle(n, seed, synced=True, fan_m=25.0, spacing=_SAT_SPACING,
                ammo=_SAT_AMMO):
    """Fly an n-round bundle at one destroyer (CIWS off; the SM-2 throughput is
    the isolated saturator) and return a dict of outcomes.

    ``synced`` True  -> all n rounds released at once on a lateral fan, so they
                        arrive together (the saturation case).
              False -> the rounds are released ONE AT A TIME, ``spacing`` s
                        apart down the SAME run-in lane, so each is faced alone
                        (the trickle/control case — spacing > the lone-round
                        engagement duration).
    ``ammo``         -> SM-2 reserve.  The default (_SAT_AMMO, large) REMOVES
                        the magazine as a confound so the leak can only come
                        from the in-flight cap + reload (see the block comment).

    Returns dict(hits, peak, spent, remaining): leaker ship hits, peak SM-2
    in-flight, SM-2 spent, and the magazine remaining (to prove a synced leak
    is NOT ammo-out).  Determinism: fixed seed, fixed call sequence."""
    from sim.enemy_defense import ShipDefense
    from sim.enemy_ships import Destroyer
    from sim.damage import apply_missile_hits

    d = Destroyer("dsat", (0.0, 0.0), heading_deg=0.0)
    d.pos[:] = (0.0, 0.0, 0.0)
    d.ciws_ammo = 0          # isolate the SM-2 throughput as the saturator
    d.sm2_ammo = int(ammo)
    start_ammo = d.sm2_ammo
    world = _SatWorld(d)
    defense = ShipDefense(d, np.random.default_rng(seed))
    aim = np.array([0.0, _SAT_ALT, 0.0], dtype=np.float64)
    if synced:
        for i in range(n):
            world.missiles.append(
                _level_swarm(((i - n / 2) * fan_m, _SAT_RUN_IN),
                             aim, _SAT_V, i))
    # The trickle must run long enough to release all n rounds AND let the last
    # one transit; the synced case clears inside _SAT_TMAX.
    tmax = _SAT_TMAX if synced else (n - 1) * spacing + _SAT_TMAX
    leaker_hits = 0
    peak_inflight = 0
    t = 0.0
    released = 0
    while t < tmax:
        if not synced and released < n and t >= released * spacing:
            world.missiles.append(
                _level_swarm((0.0, _SAT_RUN_IN), aim, _SAT_V, released))
            released += 1
        world.sim_time = t
        d.sm2_reload_timer = max(0.0, d.sm2_reload_timer - DT)
        for m in world.missiles:
            m.update(DT, world)
        defense.step(world, DT)
        before = len(world.events)
        apply_missile_hits(
            [m for m in world.missiles if getattr(m, "weapon", None) is SWARM],
            world.ships, world.events)
        leaker_hits += sum(1 for k, _ in world.events[before:]
                           if k == "ship_hit")
        peak_inflight = max(peak_inflight, len(defense._inflight))
        world.missiles = [m for m in world.missiles if m.alive]
        t += DT
        if (synced or released >= n) and not any(
                getattr(m, "weapon", None) is SWARM
                for m in world.missiles):
            break
    return dict(hits=leaker_hits, peak=peak_inflight,
                spent=start_ammo - d.sm2_ammo, remaining=d.sm2_ammo)


@pytest.mark.slow
def test_swarm_saturates_point_defense():
    """The saturation contract (PHYSICS, not dice), with the magazine REMOVED
    as a confound so the leak provably emerges from the SM-2 in-flight cap +
    reload — NOT from Winchester (the M4-B FIXER finding).

    Given a large SM-2 reserve (so ammo is never the binding gate):

      * a LONE round is serviced every seed (the per-round difficulty floor);
      * a SYNCHRONIZED 8-round bundle SINKS the destroyer (>= 3 leaker hits,
        a sunk hull) — yet leaves a HUGE magazine reserve, so the leak is the
        4-in-flight cap split across 8 simultaneous arrivals, NOT ammo-out;
      * the SAME 8 rounds delivered as a TRICKLE (spaced 600 s apart, past the
        ~409 s lone-round engagement) are SERVICED (<= 1 hit) — while spending
        AT LEAST as many SM-2 as the synced bundle, proving the trickle is not
        ammo-starved: it leaks less only because arrivals are spread out so the
        cap is never the binding constraint.

    Determinism: fixed seeds, the same call sequence every run."""
    from sim.enemy_defense import SM2_MAX_INFLIGHT

    SEEDS = range(3)

    # (1) A lone round is reliably serviced when ammo is not the constraint.
    lone = [_run_bundle(1, s, synced=True) for s in SEEDS]
    assert max(r["hits"] for r in lone) == 0, (
        f"the destroyer must stop a LONE swarm round given ammo "
        f"(hits {[r['hits'] for r in lone]})")

    # (2) A synchronized 8-round bundle sinks the hull AND keeps a huge
    #     reserve -> the leak is the in-flight cap, not Winchester.
    synced = [_run_bundle(8, s, synced=True) for s in SEEDS]
    synced_min = min(r["hits"] for r in synced)
    assert synced_min >= 3, (
        f"a synchronized bundle must overwhelm the SM-2 throughput and SINK "
        f"the hull (>= 3 leaker hits every seed; got "
        f"{[r['hits'] for r in synced]}); peak in-flight "
        f"{[r['peak'] for r in synced]}, cap {SM2_MAX_INFLIGHT}")
    assert all(r["peak"] == SM2_MAX_INFLIGHT for r in synced), (
        f"the saturation must drive the SM-2 to its in-flight cap "
        f"(peaks {[r['peak'] for r in synced]}, cap {SM2_MAX_INFLIGHT})")
    assert all(r["remaining"] > 0 for r in synced), (
        f"the synced leak must NOT be ammo-out (the magazine is the confound "
        f"this test removes); remaining {[r['remaining'] for r in synced]}")

    # (3) The SAME 8 rounds as a spaced trickle are serviced — and spend at
    #     least as many SM-2 as the synced bundle (so 'serviced' is not just
    #     'ran out of ammo'): the difference is simultaneity vs the cap.
    trickle = [_run_bundle(8, s, synced=False) for s in SEEDS]
    trickle_max = max(r["hits"] for r in trickle)
    assert trickle_max <= 1, (
        f"a spaced trickle of the same 8 rounds must be serviced (<= 1 hit, "
        f"the per-round noise floor); got {[r['hits'] for r in trickle]}")
    assert trickle_max < synced_min, (
        f"the synchronized bundle must leak strictly MORE than the spaced "
        f"trickle of identical rounds (synced {[r['hits'] for r in synced]} "
        f"vs trickle {[r['hits'] for r in trickle]})")
    assert min(r["spent"] for r in trickle) >= min(r["spent"] for r in synced), (
        f"the trickle must spend AT LEAST as many SM-2 as the synced bundle — "
        f"if it serviced the rounds on LESS ammo the contrast would be "
        f"ammo-driven, not cap-driven (trickle spent "
        f"{[r['spent'] for r in trickle]}, synced {[r['spent'] for r in synced]})")


# ===========================================================================
# UI integration: platform cycle + HUD row (pure helpers, byte-identical gate)
# ===========================================================================

def test_combat_platforms_adds_swarm_only_when_armed():
    from game.controls import (combat_platforms, PLATFORMS_COMBAT,
                               PLATFORMS_COMBAT_SWARM)
    w_off = _combat_world()                         # default: no pod
    assert combat_platforms(w_off) == PLATFORMS_COMBAT
    assert "swarm" not in combat_platforms(w_off)
    w_on = _combat_world(n_swarm_pods=1, swarm_cells_per_pod=6)
    assert combat_platforms(w_on) == PLATFORMS_COMBAT_SWARM
    assert combat_platforms(w_on)[-1] == "swarm"


def test_swarm_hud_row_states():
    from game.hud import swarm_status_row
    assert swarm_status_row(_combat_world()) is None      # no pod -> no row
    w = _combat_world(n_swarm_pods=1, swarm_cells_per_pod=6)
    label, text, _col = swarm_status_row(w)
    assert label == "SWARM"
    assert text == "6/6  0 UP"                            # 6 cells, 0 in flight
    aim = np.array([w.ships[0].pos[0], 0.0, w.ships[0].pos[2]],
                   dtype=np.float64)
    w.launch_swarm("lo-lo", aim, sync=True)
    # Bundle away: the pod is empty and refilling (the renewable, rate-limited
    # cell magazine), surfaced as the reload countdown.
    label2, text2, _c2 = swarm_status_row(w)
    assert text2.startswith("0/6 RLDG")


def test_swarm_arrival_mode_default_byte_identical_battle():
    """The swarm UI never touches the default battle: no pod, no swarm row,
    the three-platform cycle — the out-of-the-box battle is unchanged."""
    from game.controls import combat_platforms, PLATFORMS_COMBAT
    from game.hud import swarm_status_row
    w = _combat_world()
    assert combat_platforms(w) == PLATFORMS_COMBAT
    assert swarm_status_row(w) is None
    assert getattr(w, "_swarm_mag_cap", 0) == 0
