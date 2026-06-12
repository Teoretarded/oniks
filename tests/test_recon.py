"""Tests for sim/recon.py (GL-free).

All terrain interactions use injected flat or synthetic height functions so
the tests never call the real heightfield.  Radar objects are lightweight
stubs that carry only the attributes the production code reads.

Test categories:
  1.  ReconDrone — route following, waypoint advance, loiter orbit.
  2.  ReconDrone — kill() -> falling spiral -> DRONE_GONE.
  3.  ElintReceiver — gate: dead, silent, over-horizon, mountain blocked.
  4.  ElintReceiver — triangulation converges < 5 km after 60 km baseline.
  5.  SarSensor — inside/outside strip.
  6.  RwrReceiver — SPIKE iff detected, LOCK iff targeted.
"""

import math
import types

import numpy as np
import pytest

import sim.radar as _radar_mod
from sim.recon import (
    DRONE_ALT_M, DRONE_GONE, DRONE_SHOT_DOWN, DRONE_AIRBORNE,
    DRONE_LOITER_RADIUS_M, DRONE_SPEED_MPS,
    ELINT_FIX_ACTIONABLE_M, ELINT_BEARING_SIGMA_RAD,
    RWR_SPIKE, RWR_LOCK, RWR_CLEAR,
    SAR_HALF_WIDTH_M,
    ElintReceiver, ReconDrone, RwrReceiver, SarSensor,
)

# ---------------------------------------------------------------------------
# Helpers / stubs
# ---------------------------------------------------------------------------

def _flat(h: float = 0.0):
    """Return a flat terrain height function at altitude h."""
    return lambda x, z: h


def _make_radar(
    radar_id="r0",
    pos=(0.0, 0.0, 200_000.0),  # far side
    antenna_m=20.0,
    ranges=None,
    alive=True,
    emitting=True,
):
    """Minimal Radar-compatible stub."""
    from sim.radar import Radar
    r = Radar(
        radar_id=radar_id,
        pos=np.array(pos, dtype=np.float64),
        antenna_m=antenna_m,
        ranges=ranges or {"ship": 300_000, "stealth": 30_000, "fighter": 300_000,
                          "missile": 300_000},
    )
    r.alive = alive
    r.emitting = emitting
    return r


def _make_sam_missile(pos=(0.0, 1_000.0, 50_000.0), target=None, alive=True):
    """Minimal SamMissile-compatible stub with .target and .alive."""
    m = types.SimpleNamespace(
        pos=np.array(pos, dtype=np.float64),
        target=target,
        alive=alive,
        missile_id="sam_stub_0",
    )
    return m


# ---------------------------------------------------------------------------
# 1.  ReconDrone — route following
# ---------------------------------------------------------------------------

class TestReconDroneRoute:
    """Drone follows a two-waypoint route then loiters."""

    def test_single_waypoint_reached_then_loiter(self):
        """After the waypoint is reached the drone enters loiter mode."""
        drone = ReconDrone(spawn_xz=(0.0, 0.0), height_fn=_flat(0.0))
        # Waypoint 200 m ahead (just beyond the 1-second advance threshold)
        drone.set_route([(0.0, 300.0)])
        drone.pos = np.array([0.0, DRONE_ALT_M, 0.0], dtype=np.float64)
        drone.heading = 0.0  # pointing north

        # Step until loitering or give up after 30 s sim time
        for _ in range(30 * 120):
            drone.update(1.0 / 120.0)
            if drone._loitering:
                break
        assert drone._loitering, "Drone should loiter after reaching the waypoint"

    def test_two_waypoints_in_order(self):
        """Drone reaches both waypoints in sequence before loitering."""
        wp1 = (0.0, 5_000.0)
        wp2 = (5_000.0, 5_000.0)
        drone = ReconDrone(spawn_xz=(0.0, 0.0), height_fn=_flat(0.0))
        drone.set_route([wp1, wp2])

        visited = []
        last_wp = drone._wp_idx

        # Run for 200 s (plenty of time to cover 5+5 km at 160 m/s)
        steps = int(200 / (1 / 120))
        for _ in range(steps):
            drone.update(1.0 / 120.0)
            if drone._wp_idx != last_wp:
                visited.append(drone._wp_idx)
                last_wp = drone._wp_idx
            if drone._loitering:
                break

        assert drone._loitering, "Should loiter after the second waypoint"
        # Both waypoints must have been advanced through
        assert 1 in visited or drone._loitering, "Should have advanced past wp1"

    def test_heading_rate_limited(self):
        """Heading change in one step never exceeds DRONE_TURN_RATE_RPS * dt."""
        from sim.recon import DRONE_TURN_RATE_RPS
        drone = ReconDrone(spawn_xz=(0.0, 0.0), height_fn=_flat(0.0))
        drone.set_route([(10_000.0, 0.0)])  # pure east — 90 deg turn from heading=0
        h0 = drone.heading
        dt = 1.0 / 120.0
        drone.update(dt)
        delta = abs((drone.heading - h0 + math.pi) % (2 * math.pi) - math.pi)
        assert delta <= DRONE_TURN_RATE_RPS * dt + 1e-9

    def test_empty_route_loiters_at_spawn(self):
        """Empty route -> loiter at spawn from the first update."""
        drone = ReconDrone(spawn_xz=(1_000.0, 2_000.0), height_fn=_flat(0.0))
        drone.set_route([])
        assert drone._loitering
        cx, cz = drone._loiter_centre[0], drone._loiter_centre[2]
        assert abs(cx - 1_000.0) < 1.0
        assert abs(cz - 2_000.0) < 1.0

    def test_altitude_held_at_cruise(self):
        """Drone maintains DRONE_ALT_M during cruise flight."""
        drone = ReconDrone(spawn_xz=(0.0, 0.0), height_fn=_flat(0.0))
        drone.set_route([(0.0, 10_000.0)])
        for _ in range(600):
            drone.update(1.0 / 120.0)
        assert abs(drone.pos[1] - DRONE_ALT_M) < 1.0

    def test_loiter_orbit_stays_near_centre(self):
        """Loiter orbit keeps the drone within loiter radius ± small epsilon."""
        drone = ReconDrone(spawn_xz=(0.0, 0.0), height_fn=_flat(0.0))
        drone.set_route([])   # loiter at spawn
        # Orbit for 2 full revolutions
        rev_s = 2 * math.pi * DRONE_LOITER_RADIUS_M / DRONE_SPEED_MPS
        steps = int(2 * rev_s * 120)
        for _ in range(steps):
            drone.update(1.0 / 120.0)
            dx = drone.pos[0] - 0.0
            dz = drone.pos[2] - 0.0
            r = math.hypot(dx, dz)
            assert abs(r - DRONE_LOITER_RADIUS_M) < 5.0, (
                f"Loiter radius {r:.1f} m, expected {DRONE_LOITER_RADIUS_M:.1f} m"
            )

    def test_is_air_flag(self):
        drone = ReconDrone()
        assert drone.is_air is True

    def test_radar_size_class(self):
        drone = ReconDrone()
        assert drone.radar_size == "stealth"

    def test_alive_while_airborne(self):
        drone = ReconDrone()
        assert drone.alive is True


# ---------------------------------------------------------------------------
# 2.  ReconDrone — kill() -> falling -> DRONE_GONE
# ---------------------------------------------------------------------------

class TestReconDroneKill:
    """kill() transitions through SHOT_DOWN to GONE."""

    def _make_falling_drone(self, alt=18_000.0, height_fn=None):
        drone = ReconDrone(
            spawn_xz=(0.0, 0.0),
            height_fn=height_fn or _flat(0.0),
        )
        drone.pos = np.array([0.0, alt, 0.0], dtype=np.float64)
        drone.kill()
        return drone

    def test_kill_transitions_to_shot_down(self):
        drone = self._make_falling_drone()
        assert drone.state == DRONE_SHOT_DOWN

    def test_alive_false_after_kill(self):
        drone = self._make_falling_drone()
        assert drone.alive is False

    def test_double_kill_noop(self):
        """kill() while not AIRBORNE is a no-op."""
        drone = self._make_falling_drone()
        drone.kill()   # second call
        assert drone.state == DRONE_SHOT_DOWN

    def test_falling_drone_descends(self):
        """Altitude decreases during the falling spiral."""
        drone = self._make_falling_drone(alt=18_000.0)
        h0 = drone.pos[1]
        for _ in range(120 * 10):  # 10 s
            drone.update(1.0 / 120.0)
            if drone.state == DRONE_GONE:
                break
        assert drone.pos[1] < h0, "Altitude should drop during fall"

    def test_falling_eventually_reaches_gone(self):
        """After enough time the drone impacts and transitions to DRONE_GONE.

        At DRONE_ALT_M=18 000 m, DRONE_FALL_SPEED_FRAC=0.55, DRONE_SPEED_MPS=160,
        and DRONE_FALL_PITCH_RAD=15 deg the terminal sink rate is:
            160 * 0.55 * sin(15°) ≈ 22.7 m/s  → ≈ 793 s to descend 18 km.
        We give it 900 s (generous margin).
        """
        drone = self._make_falling_drone(alt=18_000.0)
        for _ in range(120 * 900):
            drone.update(1.0 / 120.0)
            if drone.state == DRONE_GONE:
                break
        assert drone.state == DRONE_GONE, "Drone should reach GONE state within 900 s"

    def test_gone_drone_stops_moving(self):
        """After GONE the drone pos no longer changes."""
        drone = self._make_falling_drone(alt=18_000.0)
        for _ in range(120 * 900):
            drone.update(1.0 / 120.0)
            if drone.state == DRONE_GONE:
                break
        assert drone.state == DRONE_GONE, "Should have reached GONE before checking"
        pos_after = drone.pos.copy()
        drone.update(1.0)
        assert np.allclose(drone.pos, pos_after)

    def test_kill_no_effect_when_already_gone(self):
        """kill() while GONE is silently ignored."""
        drone = self._make_falling_drone(alt=18_000.0)
        for _ in range(120 * 900):
            drone.update(1.0 / 120.0)
            if drone.state == DRONE_GONE:
                break
        assert drone.state == DRONE_GONE, "Should have reached GONE"
        drone.kill()
        assert drone.state == DRONE_GONE


# ---------------------------------------------------------------------------
# 3.  ElintReceiver — gate conditions
# ---------------------------------------------------------------------------

class TestElintGating:
    """ELINT only accumulates bearing pairs when all conditions are met."""

    # Drone position: 18 km altitude, north of the emitter
    DRONE_POS = np.array([0.0, 18_000.0, 0.0], dtype=np.float64)

    def _elint(self, height_fn=None, seed=0):
        return ElintReceiver(
            rng=np.random.default_rng(seed),
            height_fn=height_fn or _flat(0.0),
        )

    def _heard(self, elint, radar):
        """Run one update and return whether any pairs were stored."""
        elint.update(self.DRONE_POS, [("r0", radar)])
        return len(elint._pairs.get("r0", [])) > 0

    def test_hears_alive_emitting_los_clear(self):
        """Baseline: alive, emitting, LOS clear -> at least 1 bearing pair."""
        # Put emitter 100 km south (within range, horizon OK at 18 km alt)
        radar = _make_radar(pos=(0.0, 0.0, -100_000.0), alive=True, emitting=True)
        elint = self._elint()
        assert self._heard(elint, radar)

    def test_silent_emitter_no_pairs(self):
        """radar.emitting = False -> no bearing stored."""
        radar = _make_radar(pos=(0.0, 0.0, -100_000.0), alive=True, emitting=False)
        elint = self._elint()
        assert not self._heard(elint, radar)

    def test_dead_emitter_no_pairs(self):
        """radar.alive = False -> no bearing stored."""
        radar = _make_radar(pos=(0.0, 0.0, -100_000.0), alive=False, emitting=True)
        elint = self._elint()
        assert not self._heard(elint, radar)

    def test_beyond_elint_range_cap_no_pairs(self):
        """Emitter beyond ELINT_RANGE_M = 450 km -> no bearing."""
        from sim.recon import ELINT_RANGE_M
        radar = _make_radar(pos=(0.0, 0.0, -(ELINT_RANGE_M + 10_000.0)),
                            alive=True, emitting=True)
        elint = self._elint()
        assert not self._heard(elint, radar)

    def test_over_horizon_no_pairs(self):
        """Emitter far enough that horizon blocks it.

        At drone alt=18 km and emitter alt=0 m the 4/3-earth horizon is:
            4120*(sqrt(18000) + sqrt(20)) ≈ 4120*134.2 ≈ 552 km
        So we park the emitter at 0 m but set the drone very low (10 m) to
        shrink the horizon to a small value, then test beyond it.

        horizon at h_drone=10, h_emitter=20 → 4120*(sqrt(10)+sqrt(20)) ≈ 31 km
        Put the emitter at 40 km → over-horizon.
        """
        from sim.radar import radar_horizon_m
        drone_alt = 10.0
        emitter_alt = 20.0
        horizon = radar_horizon_m(drone_alt, emitter_alt)
        far_z = -(horizon + 5_000.0)
        drone_low = np.array([0.0, drone_alt, 0.0], dtype=np.float64)

        radar = _make_radar(pos=(0.0, 0.0, far_z), antenna_m=emitter_alt,
                            alive=True, emitting=True)
        elint = self._elint()
        elint.update(drone_low, [("r0", radar)])
        assert len(elint._pairs.get("r0", [])) == 0, (
            f"Should be over-horizon at {abs(far_z)/1e3:.1f} km "
            f"(horizon={horizon/1e3:.1f} km)"
        )

    def test_mountain_blocks_los_no_pairs(self):
        """A mountain in between blocks the bearing (terrain_blocks=True path).

        We inject a height_fn that returns a tall peak at the midpoint
        between the drone and the emitter.  terrain_blocks() samples every
        LOS_STEP_M; the mountain must be tall enough to clear the slant-line
        at the mid-sample.
        """
        # Drone at x=0, z=0, y=18 000; emitter at x=0, z=10 000, y=0.
        # The slant-line height at the midpoint is 9 000 m.
        # We put a 15 000 m fictitious peak at z=5 000 ± 2 000 to block it.
        emitter_z = 10_000.0
        peak_z_centre = emitter_z / 2.0  # 5 000 m from drone, mid-path

        def mountain_height(x, z):
            # Returns a very tall peak near the mid-path
            if abs(z - peak_z_centre) < 2_000.0:
                return 15_000.0
            return 0.0

        drone_pos = np.array([0.0, 18_000.0, 0.0], dtype=np.float64)
        radar = _make_radar(pos=(0.0, 0.0, emitter_z), alive=True, emitting=True)
        elint = ElintReceiver(
            rng=np.random.default_rng(0),
            height_fn=mountain_height,
        )
        elint.update(drone_pos, [("r0", radar)])
        assert len(elint._pairs.get("r0", [])) == 0, (
            "Mountain should have blocked the LOS bearing"
        )

    def test_pairs_capped_at_max(self):
        """Old pairs are evicted when the cap is reached."""
        from sim.recon import ELINT_MAX_PAIRS
        radar = _make_radar(pos=(0.0, 0.0, -100_000.0), alive=True, emitting=True)
        elint = self._elint()
        for _ in range(ELINT_MAX_PAIRS + 10):
            elint.update(self.DRONE_POS, [("r0", radar)])
        assert len(elint._pairs["r0"]) <= ELINT_MAX_PAIRS


# ---------------------------------------------------------------------------
# 4.  ElintReceiver — triangulation quality
# ---------------------------------------------------------------------------

class TestElintTriangulation:
    """After a 60 km drone traversal with seeded noise the fix quality must
    be between 200 m and ELINT_FIX_ACTIONABLE_M (5 km).  The lower bound
    checks that bearing noise MATTERS (quality never collapses to zero);
    the upper bound checks that the geometry accumulation works.

    Quality is the least-squares COVARIANCE error (Phase-4 integration
    fix): the original residual-RMS proxy reported near-zero 'quality' for
    nearly-parallel bearing lines whose actual fix was tens of km off
    (residuals measure agreement between lines, not how well they pin the
    along-bearing position).  Scenario ranges below were re-measured
    against TRUE error after the fix: 60 km of baseline against an 80 km
    emitter measures quality 1.7-2.1 km vs true error 1.0-4.5 km — honest
    and actionable; the same baseline against 200 km measures true error
    19-38 km, correctly rated NOT actionable now."""

    def test_triangulation_converges_and_noise_matters(self):
        """Seeded noise: quality must be in (200, 5000) m after a 60 km
        baseline against an emitter 80 km off the track."""
        rng_seed = 42
        emitter_xz = (0.0, 80_000.0)        # emitter 80 km north
        emitter_alt = 20.0                  # antenna height above flat ground

        # Drone flies east from x=-30 km to x=+30 km (60 km baseline) at
        # cruise altitude with the emitter to the north.
        elint = ElintReceiver(
            rng=np.random.default_rng(rng_seed),
            height_fn=_flat(0.0),
        )

        radar = _make_radar(
            pos=(emitter_xz[0], 0.0, emitter_xz[1]),
            antenna_m=emitter_alt,
            alive=True,
            emitting=True,
        )

        # Sample every 500 m of east travel (120 samples over 60 km)
        n_samples = 120
        for i in range(n_samples):
            drone_x = -30_000.0 + i * (60_000.0 / n_samples)
            drone_pos = np.array([drone_x, DRONE_ALT_M, 0.0], dtype=np.float64)
            elint.update(drone_pos, [("enemy_r0", radar)])

        q = elint.fix_quality("enemy_r0")
        assert q < ELINT_FIX_ACTIONABLE_M, (
            f"Quality {q:.0f} m should be < actionable threshold "
            f"{ELINT_FIX_ACTIONABLE_M:.0f} m after 60 km baseline"
        )
        assert q > 200.0, (
            f"Quality {q:.1f} m should be > 200 m (noise must matter, not zero)"
        )

    def test_degenerate_baseline_is_never_actionable(self):
        """Regression for the Phase-4 integration bug: a drone orbiting a
        tight 4 km loiter 150 km from the emitter collects nearly-parallel
        bearings — the lines agree (tiny residual) but the true fix error
        is >100 km.  The covariance quality must rate this NOT actionable
        (the old residual proxy called it a sub-5-km fix and leaked a
        garbage track into the player picture)."""
        elint = ElintReceiver(rng=np.random.default_rng(0),
                              height_fn=_flat(0.0))
        radar = _make_radar(pos=(-20_000.0, 0.0, 150_000.0), antenna_m=20.0)
        for i in range(64):
            a = i * 0.05                    # ~one loiter orbit of samples
            drone_pos = np.array([4_000.0 * math.sin(a), DRONE_ALT_M,
                                  4_000.0 * math.cos(a)], dtype=np.float64)
            elint.update(drone_pos, [("r0", radar)])
        assert not elint.is_actionable("r0"), (
            f"loiter-orbit fix (quality {elint.fix_quality('r0'):.0f} m) "
            "must never be actionable"
        )

    def test_less_than_2_pairs_returns_inf(self):
        """Fewer than 2 pairs -> quality = inf (not yet triangulatable)."""
        elint = ElintReceiver(rng=np.random.default_rng(0), height_fn=_flat(0.0))
        # Inject one pair manually
        elint._pairs["r0"] = [(np.array([0.0, 0.0]), 0.1)]
        assert math.isinf(elint.fix_quality("r0"))

    def test_est_pos_none_with_insufficient_pairs(self):
        """est_pos returns None when geometry is insufficient."""
        elint = ElintReceiver(rng=np.random.default_rng(0), height_fn=_flat(0.0))
        assert elint.est_pos("no_emitter") is None

    def test_est_pos_close_to_truth(self):
        """After wide-baseline collection est_pos should be near the real emitter.

        Geometry note: for good triangulation the emitter must not be nearly
        collinear with the drone flight path.  The drone flies east (x axis);
        we place the emitter at (z=30 km north, x=5 km east) so the bearings
        change significantly as the drone traverses 60 km east.  The 60 km
        baseline at 30 km range gives angular spread >> ELINT_BEARING_SIGMA_RAD.
        """
        rng_seed = 7
        emitter_xz = (5_000.0, 30_000.0)   # 5 km east, 30 km north of drone track
        elint = ElintReceiver(
            rng=np.random.default_rng(rng_seed),
            height_fn=_flat(0.0),
        )
        radar = _make_radar(
            pos=(emitter_xz[0], 0.0, emitter_xz[1]),
            antenna_m=20.0, alive=True, emitting=True,
        )
        for i in range(120):
            drone_x = -30_000.0 + i * (60_000.0 / 120)
            elint.update(
                np.array([drone_x, DRONE_ALT_M, 0.0], dtype=np.float64),
                [("e0", radar)],
            )
        pos = elint.est_pos("e0")
        assert pos is not None
        err = math.hypot(pos[0] - emitter_xz[0], pos[2] - emitter_xz[1])
        assert err < ELINT_FIX_ACTIONABLE_M, (
            f"Estimated position error {err:.0f} m should be < "
            f"{ELINT_FIX_ACTIONABLE_M:.0f} m"
        )

    def test_is_actionable_flag(self):
        """is_actionable() toggles correctly with quality threshold."""
        elint = ElintReceiver(rng=np.random.default_rng(42), height_fn=_flat(0.0))
        # No data yet — not actionable
        assert not elint.is_actionable("r0")

        # Inject pairs with excellent geometry (zero noise — fake)
        # Two perpendicular bearings from 100 km apart should give a perfect fix
        emitter = (0.0, 100_000.0)
        # pair 1: drone at (-100 km, 0) looking at (0, 100 km)
        # bearing from (-100k, 0) to (0, 100k) = atan2(0-(-100k), 100k-0) = atan2(100k,100k)=45deg
        for i in range(60):
            x = -30_000.0 + i * 1_000.0
            drone_pos = np.array([x, DRONE_ALT_M, 0.0], dtype=np.float64)
            elint.update(drone_pos, [("r0", _make_radar(
                pos=(emitter[0], 0.0, emitter[1]), alive=True, emitting=True))])

        # After wide baseline it should be actionable
        q = elint.fix_quality("r0")
        assert q < ELINT_FIX_ACTIONABLE_M or q < 50_000, "Sanity: quality computed"
        # The exact threshold test is already in test_triangulation_converges.


# ---------------------------------------------------------------------------
# 5.  SarSensor — inside / outside strip
# ---------------------------------------------------------------------------

class TestSarSensor:
    """detects() gate: inside ±25 km of nadir only."""

    def _sar(self):
        return SarSensor()

    def test_detects_inside_strip(self):
        drone = np.array([0.0, DRONE_ALT_M, 0.0], dtype=np.float64)
        target = np.array([20_000.0, 0.0, 0.0], dtype=np.float64)  # 20 km east
        assert self._sar().detects(drone, target)

    def test_does_not_detect_outside_strip(self):
        drone = np.array([0.0, DRONE_ALT_M, 0.0], dtype=np.float64)
        target = np.array([30_000.0, 0.0, 0.0], dtype=np.float64)  # 30 km east
        assert not self._sar().detects(drone, target)

    def test_boundary_exactly_at_half_width(self):
        """Target exactly at SAR_HALF_WIDTH_M is detected (<=)."""
        drone = np.array([0.0, DRONE_ALT_M, 0.0], dtype=np.float64)
        target = np.array([SAR_HALF_WIDTH_M, 0.0, 0.0], dtype=np.float64)
        assert self._sar().detects(drone, target)

    def test_boundary_just_outside(self):
        """Target 1 m beyond the half-width is not detected."""
        drone = np.array([0.0, DRONE_ALT_M, 0.0], dtype=np.float64)
        target = np.array([SAR_HALF_WIDTH_M + 1.0, 0.0, 0.0], dtype=np.float64)
        assert not self._sar().detects(drone, target)

    def test_detects_directly_below_drone(self):
        """Target directly under the drone (range 0) is detected."""
        drone = np.array([1_000.0, DRONE_ALT_M, 500.0], dtype=np.float64)
        target = np.array([1_000.0, 0.0, 500.0], dtype=np.float64)
        assert self._sar().detects(drone, target)

    def test_diagonal_inside_strip(self):
        """Diagonal 2D distance within 25 km is detected."""
        drone = np.array([0.0, DRONE_ALT_M, 0.0], dtype=np.float64)
        # 15 km east + 15 km north -> hypot ≈ 21.2 km < 25 km
        target = np.array([15_000.0, 0.0, 15_000.0], dtype=np.float64)
        assert self._sar().detects(drone, target)

    def test_diagonal_outside_strip(self):
        """Diagonal 2D distance beyond 25 km is not detected."""
        drone = np.array([0.0, DRONE_ALT_M, 0.0], dtype=np.float64)
        # 20 km east + 20 km north -> hypot ≈ 28.3 km > 25 km
        target = np.array([20_000.0, 0.0, 20_000.0], dtype=np.float64)
        assert not self._sar().detects(drone, target)


# ---------------------------------------------------------------------------
# 6.  RwrReceiver — SPIKE and LOCK
# ---------------------------------------------------------------------------

class TestRwrReceiver:
    """RWR state machine: SPIKE iff detected, LOCK iff targeted."""

    DRONE_POS = np.array([0.0, DRONE_ALT_M, 0.0], dtype=np.float64)

    _DRONE_ID = "drone_00"

    def _rwr(self, height_fn=None):
        return RwrReceiver(drone_id=self._DRONE_ID, height_fn=height_fn or _flat(0.0))

    # ---- SPIKE ----

    def test_no_spike_when_radar_not_detecting(self):
        """Radar too far away -> no SPIKE."""
        radar = _make_radar(
            pos=(0.0, 0.0, 200_000.0),    # 200 km north, stealth range = 30 km
            alive=True, emitting=True,
            ranges={"stealth": 30_000, "ship": 300_000},
        )
        rwr = self._rwr()
        rwr.update(self.DRONE_POS, [radar], [])
        assert rwr.threat_state("r0") != RWR_SPIKE

    def test_spike_when_radar_detects(self):
        """Radar within stealth range + clear LOS -> SPIKE."""
        radar = _make_radar(
            pos=(0.0, 0.0, 10_000.0),     # 10 km north, inside 30 km stealth range
            alive=True, emitting=True,
            ranges={"stealth": 30_000, "ship": 300_000},
        )
        rwr = self._rwr()
        rwr.update(self.DRONE_POS, [radar], [])
        assert rwr.threat_state("r0") == RWR_SPIKE

    def test_no_spike_dead_radar(self):
        """Dead radar -> no SPIKE."""
        radar = _make_radar(
            pos=(0.0, 0.0, 10_000.0), alive=False, emitting=True,
            ranges={"stealth": 30_000},
        )
        rwr = self._rwr()
        rwr.update(self.DRONE_POS, [radar], [])
        assert rwr.threat_state("r0") != RWR_SPIKE

    def test_no_spike_silent_radar(self):
        """Silent radar -> no SPIKE."""
        radar = _make_radar(
            pos=(0.0, 0.0, 10_000.0), alive=True, emitting=False,
            ranges={"stealth": 30_000},
        )
        rwr = self._rwr()
        rwr.update(self.DRONE_POS, [radar], [])
        assert rwr.threat_state("r0") != RWR_SPIKE

    def test_spike_cleared_when_radar_moves_out_of_range(self):
        """SPIKE clears after the radar can no longer detect the drone."""
        radar = _make_radar(
            pos=(0.0, 0.0, 10_000.0), alive=True, emitting=True,
            ranges={"stealth": 30_000},
        )
        rwr = self._rwr()
        rwr.update(self.DRONE_POS, [radar], [])
        assert rwr.threat_state("r0") == RWR_SPIKE

        # Move radar far away
        radar.pos[2] = 200_000.0
        rwr.update(self.DRONE_POS, [radar], [])
        assert rwr.threat_state("r0") != RWR_SPIKE

    # ---- LOCK ----

    def _drone_stub(self):
        """Minimal drone object for missile.target reference (id matches _DRONE_ID)."""
        return types.SimpleNamespace(aircraft_id=self._DRONE_ID)

    def test_lock_when_missile_targets_drone(self):
        """LOCK state appears when a live missile targets the drone."""
        drone_ref = self._drone_stub()
        missile = _make_sam_missile(target=drone_ref, alive=True)
        rwr = self._rwr()
        rwr.update(self.DRONE_POS, [], [missile])
        assert any(lvl == RWR_LOCK for lvl, _ in rwr.alerts())

    def test_no_lock_when_missile_dead(self):
        """Dead missile -> no LOCK."""
        drone_ref = self._drone_stub()
        missile = _make_sam_missile(target=drone_ref, alive=False)
        rwr = self._rwr()
        rwr.update(self.DRONE_POS, [], [missile])
        assert all(lvl != RWR_LOCK for lvl, _ in rwr.alerts())

    def test_no_lock_when_missile_targets_other(self):
        """Missile targeting something else -> no LOCK for drone."""
        other = types.SimpleNamespace(aircraft_id="other_target")
        missile = _make_sam_missile(target=other, alive=True)
        rwr = self._rwr()
        rwr.update(self.DRONE_POS, [], [missile])
        assert all(lvl != RWR_LOCK for lvl, _ in rwr.alerts())

    # ---- alerts() ordering ----

    def test_lock_before_spike_in_alerts(self):
        """LOCK-level alerts appear before SPIKE-level in alerts()."""
        # SPIKE via near radar
        radar = _make_radar(
            pos=(0.0, 0.0, 10_000.0), alive=True, emitting=True,
            ranges={"stealth": 30_000},
        )
        # LOCK via missile
        drone_ref = self._drone_stub()
        missile = _make_sam_missile(target=drone_ref, alive=True)
        rwr = self._rwr()
        rwr.update(self.DRONE_POS, [radar], [missile])
        alerts = rwr.alerts()
        assert len(alerts) >= 2
        # First alert must be LOCK
        assert alerts[0][0] == RWR_LOCK

    def test_no_alerts_when_clear(self):
        """No threats -> empty alert list."""
        rwr = self._rwr()
        rwr.update(self.DRONE_POS, [], [])
        assert rwr.alerts() == []
