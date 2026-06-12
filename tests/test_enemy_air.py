"""Tests for sim/enemy_air.py — Fighter, Awacs, Carrier, AirBase (GL-free).

Coverage:
  1. AirBase / rearm queue
  2. nearest_surviving_base
  3. Carrier registration and station-keeping
  4. Carrier 6-HP damage ladder
  5. Fighter full lifecycle PARKED -> ... -> PARKED with rearm queue
  6. Bingo fuel forces RTB
  7. Both bases dead -> WINCHESTER_EGRESS -> GONE at map edge
  8. nearest_surviving_base switches when the airfield Structure dies
  9. AWACS orbit + flee turns away
 10. Nose-radar cone: target behind NOT detected; ahead IS detected
 11. AWACS sees a 60 m skimmer at 200 km but NOT stealth beyond 40 km
"""

import math
import types

import numpy as np
import pytest

from sim.enemy_air import (
    AWACS_ALT_M,
    AWACS_RADAR_RANGES,
    AWACS_CRUISE_MPS,
    FIGHTER_ALT_M,
    FIGHTER_BINGO_FRAC,
    FIGHTER_CRUISE_MPS,
    FIGHTER_ENDURANCE_S,
    FIGHTER_RADAR_FOV_HALF,
    MAP_EDGE_EGRESS_M,
    REARM_S,
    AirBase,
    Awacs,
    Carrier,
    Fighter,
    FighterRadar,
    FS_GONE,
    FS_ON_STATION,
    FS_PARKED,
    FS_REARMING,
    FS_RTB,
    FS_TAKEOFF,
    FS_TRANSIT,
    FS_WINCHESTER_EGRESS,
    nearest_surviving_base,
)
from sim.ships import SHIP_TYPES, ST_ALIVE, ST_BURNING, ST_SINKING, ST_GONE


# ---------------------------------------------------------------------------
# Helpers / stubs
# ---------------------------------------------------------------------------

def _make_stub_structure(pos_xz=(0.0, 600_000.0), alive=True):
    """Minimal duck-type Structure stub (no imports from sim.bases needed)."""
    s = types.SimpleNamespace()
    s.pos = np.array([pos_xz[0], 0.0, pos_xz[1]], dtype=np.float64)
    s.alive = alive
    return s


def _make_airfield_base(pos_xz=(0.0, 600_000.0)):
    return AirBase(_make_stub_structure(pos_xz))


def _make_carrier_base(pos_xz=(0.0, 250_000.0)):
    c = Carrier("cv_test", anchor_xz=pos_xz, heading_deg=0.0)
    return AirBase(c)


# ---------------------------------------------------------------------------
# 1. AirBase / rearm queue
# ---------------------------------------------------------------------------

class TestAirBase:
    def test_alive_reflects_site(self):
        ab = _make_airfield_base()
        assert ab.alive is True
        ab._site.alive = False
        assert ab.alive is False

    def test_pos_is_3d(self):
        ab = _make_airfield_base((1000.0, 600_000.0))
        assert ab.pos.shape == (3,)
        assert float(ab.pos[0]) == pytest.approx(1000.0)
        assert float(ab.pos[2]) == pytest.approx(600_000.0)

    def test_can_recover_true_when_alive(self):
        ab = _make_airfield_base()
        assert ab.can_recover is True

    def test_can_recover_false_when_dead(self):
        ab = _make_airfield_base()
        ab._site.alive = False
        assert ab.can_recover is False

    def test_rearm_queue_one_at_a_time(self):
        """Two fighters queue; only one rearms at a time; second waits."""
        ab = _make_airfield_base()
        f1 = Fighter("f1", ab, (0.0, 500_000.0))
        f2 = Fighter("f2", ab, (0.0, 500_000.0))
        # Manually place both in the queue.
        f1.state = FS_REARMING
        f2.state = FS_REARMING
        ab.request_rearm(f1)
        ab.request_rearm(f2)
        assert len(ab._rearm_queue) == 2

        # Tick REARM_S - 1 seconds: first fighter not done yet.
        ab.update(REARM_S - 1.0)
        assert f1.state == FS_REARMING
        assert len(ab._rearm_queue) == 2

        # Cross the threshold: first fighter completes.
        ab.update(2.0)
        assert f1.state == FS_PARKED
        assert len(ab.parked) == 1
        # Second still in queue.
        assert len(ab._rearm_queue) == 1

    def test_rearm_full_cycle_two_fighters(self):
        """Both fighters eventually reach PARKED after REARM_S × 2."""
        ab = _make_airfield_base()
        f1 = Fighter("f1", ab, (0.0, 500_000.0))
        f2 = Fighter("f2", ab, (0.0, 500_000.0))
        f1.state = FS_REARMING
        f2.state = FS_REARMING
        ab.request_rearm(f1)
        ab.request_rearm(f2)
        total = 0.0
        dt = 1.0
        while (f1.state != FS_PARKED or f2.state != FS_PARKED) and total < 300.0:
            ab.update(dt)
            total += dt
        assert f1.state == FS_PARKED
        assert f2.state == FS_PARKED
        assert total == pytest.approx(REARM_S * 2, abs=2.0)


# ---------------------------------------------------------------------------
# 2. nearest_surviving_base
# ---------------------------------------------------------------------------

class TestNearestSurvivingBase:
    def test_returns_closer_base(self):
        pos = np.array([0.0, 0.0, 0.0], dtype=np.float64)
        near = AirBase(_make_stub_structure((0.0, 10_000.0)))
        far  = AirBase(_make_stub_structure((0.0, 50_000.0)))
        result = nearest_surviving_base(pos, [near, far])
        assert result is near

    def test_skips_dead_base(self):
        pos = np.array([0.0, 0.0, 0.0], dtype=np.float64)
        dead = AirBase(_make_stub_structure((0.0, 10_000.0), alive=False))
        alive = AirBase(_make_stub_structure((0.0, 50_000.0)))
        result = nearest_surviving_base(pos, [dead, alive])
        assert result is alive

    def test_returns_none_all_dead(self):
        pos = np.array([0.0, 0.0, 0.0], dtype=np.float64)
        dead1 = AirBase(_make_stub_structure((0.0, 10_000.0), alive=False))
        dead2 = AirBase(_make_stub_structure((0.0, 50_000.0), alive=False))
        result = nearest_surviving_base(pos, [dead1, dead2])
        assert result is None

    def test_switches_when_airfield_dies(self):
        """Simulates the spec requirement: nearest_surviving_base picks the
        carrier once the airfield Structure is killed."""
        pos = np.array([0.0, 0.0, 0.0], dtype=np.float64)
        airfield_struct = _make_stub_structure((0.0, 50_000.0))
        airfield = AirBase(airfield_struct)
        carrier_site = Carrier("cv_switch", (0.0, 200_000.0))
        carrier_base = AirBase(carrier_site)

        # Airfield closer → preferred.
        result = nearest_surviving_base(pos, [airfield, carrier_base])
        assert result is airfield

        # Kill the airfield.
        airfield_struct.alive = False
        result = nearest_surviving_base(pos, [airfield, carrier_base])
        assert result is carrier_base


# ---------------------------------------------------------------------------
# 3. Carrier registration and station-keeping
# ---------------------------------------------------------------------------

class TestCarrier:
    def test_carrier_in_ship_types(self):
        assert "carrier" in SHIP_TYPES

    def test_carrier_hp_is_6(self):
        assert SHIP_TYPES["carrier"]["hp"] == 6

    def test_carrier_dimensions(self):
        spec = SHIP_TYPES["carrier"]
        assert spec["length"] == pytest.approx(333.0)
        assert spec["beam"]   == pytest.approx(40.0)
        assert spec["speed"]  == pytest.approx(12.0)

    def test_carrier_is_not_air(self):
        c = Carrier("cv1", (100_000.0, 250_000.0))
        assert c.is_air is False

    def test_carrier_station_keeps(self):
        """After 600 s the carrier stays within patrol_radius + slack of anchor."""
        anchor = np.array([100_000.0, 250_000.0])
        patrol_r = 15_000.0
        c = Carrier("cv2", anchor, heading_deg=45.0, patrol_radius_m=patrol_r)
        from sim.ships import SHIP_TYPES as _ST
        # Conservative outer bound (mirrors the destroyer loiter test).
        from sim.enemy_ships import _RACETRACK_HALF_WIDTH
        speed = c.speed
        bound = patrol_r + _RACETRACK_HALF_WIDTH + c.length + speed * 1.0
        max_dist = 0.0
        for _ in range(600):
            c.update(1.0)
            dist = math.hypot(float(c.pos[0]) - float(anchor[0]),
                              float(c.pos[2]) - float(anchor[1]))
            max_dist = max(max_dist, dist)
        assert max_dist <= bound, f"carrier drifted {max_dist:.0f} m; limit {bound:.0f} m"

    def test_carrier_radar_silent_by_default(self):
        c = Carrier("cv3", (0.0, 250_000.0))
        assert c.radar.emitting is False

    def test_carrier_radar_can_be_enabled(self):
        c = Carrier("cv4", (0.0, 250_000.0))
        c.radar.emitting = True
        assert c.radar.emitting is True

    def test_carrier_alive_initially(self):
        c = Carrier("cv5", (0.0, 250_000.0))
        assert c.alive is True


# ---------------------------------------------------------------------------
# 4. Carrier 6-HP damage ladder
# ---------------------------------------------------------------------------

class TestCarrierDamage:
    def _hit(self, ship):
        """Apply one hit using the same pattern as the existing test suite."""
        from sim.ships import BURN_TIME, ST_BURNING, ST_SINKING
        ship.hp -= 1
        if ship.hp > 0:
            ship.state = ST_BURNING
            ship.burn_timer = BURN_TIME
        else:
            ship.state = ST_SINKING

    def test_hp_starts_at_6(self):
        c = Carrier("cv_hp", (0.0, 250_000.0))
        assert c.hp == 6

    def test_burning_after_first_hit(self):
        c = Carrier("cv_h1", (0.0, 250_000.0))
        self._hit(c)
        assert c.state == ST_BURNING
        assert c.hp == 5

    def test_sinking_after_six_hits(self):
        c = Carrier("cv_h6", (0.0, 250_000.0))
        for _ in range(6):
            self._hit(c)
        assert c.state == ST_SINKING
        assert c.hp == 0

    def test_sinking_transitions_to_gone(self):
        from sim.ships import SINK_GONE_TIME
        c = Carrier("cv_gone", (0.0, 250_000.0))
        c.state = ST_SINKING
        for _ in range(int(SINK_GONE_TIME) + 10):
            c.update(1.0)
        assert c.state == ST_GONE

    def test_dead_carrier_not_alive(self):
        c = Carrier("cv_dead", (0.0, 250_000.0))
        c.state = ST_SINKING
        assert c.alive is False


# ---------------------------------------------------------------------------
# 5. Fighter full lifecycle
# ---------------------------------------------------------------------------

class TestFighterLifecycle:
    def test_parked_to_rearming_and_back(self):
        """Full lifecycle: PARKED -> TAKEOFF -> TRANSIT -> ON_STATION ->
        RTB -> LANDING -> REARMING -> PARKED (via rearm queue)."""
        ab = _make_airfield_base((0.0, 600_000.0))
        patrol_anchor = np.array([50_000.0, 700_000.0])
        f = Fighter("f_lc", ab, patrol_anchor)
        bases = [ab]

        assert f.state == FS_PARKED

        f.launch()
        assert f.state == FS_TAKEOFF

        # Run until ON_STATION or timeout.
        dt = 1.0
        t = 0.0
        while f.state not in (FS_ON_STATION,) and t < 3000.0:
            f.update(dt, bases)
            ab.update(dt)
            t += dt
        assert f.state == FS_ON_STATION, f"stuck in state {f.state} after {t:.0f}s"

        # Force RTB (simulate bingo).
        f._fuel_s = f._bingo_s + 1.0
        t = 0.0
        while f.state not in (FS_REARMING, FS_PARKED) and t < 3000.0:
            f.update(dt, bases)
            ab.update(dt)
            t += dt
        assert f.state in (FS_REARMING, FS_PARKED), (
            f"stuck in state {f.state} after {t:.0f}s")

        # Run rearm queue to completion.
        t = 0.0
        while f.state != FS_PARKED and t < 200.0:
            ab.update(dt)
            t += dt
        assert f.state == FS_PARKED, f"fighter still {f.state} after rearm cycle"

    def test_fighter_is_air_true(self):
        ab = _make_airfield_base()
        f = Fighter("f_air", ab, (0.0, 500_000.0))
        assert f.is_air is True

    def test_aircraft_id(self):
        ab = _make_airfield_base()
        f = Fighter("my_fighter", ab, (0.0, 500_000.0))
        assert f.aircraft_id == "my_fighter"

    def test_velocity_zero_when_parked(self):
        ab = _make_airfield_base()
        f = Fighter("f_vel", ab, (0.0, 500_000.0))
        assert np.allclose(f.velocity(), np.zeros(3))

    def test_velocity_nonzero_when_airborne(self):
        ab = _make_airfield_base()
        f = Fighter("f_vel2", ab, (0.0, 500_000.0))
        f.launch()
        f.update(1.0, [ab])
        v = f.velocity()
        assert np.linalg.norm(v) > 0.0

    def test_alive_false_when_parked(self):
        ab = _make_airfield_base()
        f = Fighter("f_ap", ab, (0.0, 500_000.0))
        assert f.alive is False    # parked = not targetable

    def test_alive_true_when_in_transit(self):
        ab = _make_airfield_base()
        f = Fighter("f_tr", ab, (0.0, 500_000.0))
        f.launch()
        for _ in range(10):
            f.update(1.0, [ab])
        assert f.alive is True


# ---------------------------------------------------------------------------
# 6. Bingo fuel forces RTB
# ---------------------------------------------------------------------------

class TestBingoFuel:
    def test_bingo_triggers_rtb(self):
        """Setting fuel to bingo causes the fighter to transition to RTB."""
        ab = _make_airfield_base((0.0, 600_000.0))
        patrol = np.array([0.0, 700_000.0])
        f = Fighter("f_bingo", ab, patrol)
        bases = [ab]
        f.launch()
        # Fly to ON_STATION.
        dt = 1.0
        t = 0.0
        while f.state != FS_ON_STATION and t < 3000.0:
            f.update(dt, bases)
            t += dt
        assert f.state == FS_ON_STATION

        # Force bingo.
        f._fuel_s = f._bingo_s + 1.0
        f.update(dt, bases)  # one tick to trigger
        assert f.state == FS_RTB, f"expected RTB, got state {f.state}"

    def test_bingo_threshold(self):
        """Bingo threshold is 20% of total endurance."""
        ab = _make_airfield_base()
        f = Fighter("f_b2", ab, (0.0, 500_000.0))
        expected_bingo = FIGHTER_ENDURANCE_S * (1.0 - FIGHTER_BINGO_FRAC)
        assert f._bingo_s == pytest.approx(expected_bingo)


# ---------------------------------------------------------------------------
# 7. Both bases dead -> WINCHESTER_EGRESS -> GONE
# ---------------------------------------------------------------------------

class TestWinchesterEgress:
    def test_winchester_egress_when_both_dead(self):
        """If both bases are dead when RTB is triggered, state goes to
        WINCHESTER_EGRESS and eventually GONE at MAP_EDGE_EGRESS_M."""
        airfield_struct = _make_stub_structure((0.0, 600_000.0))
        carrier_ship = Carrier("cv_win", (0.0, 250_000.0))

        ab1 = AirBase(airfield_struct)
        ab2 = AirBase(carrier_ship)
        bases = [ab1, ab2]

        patrol = np.array([0.0, 700_000.0])
        f = Fighter("f_win", ab1, patrol)
        f.launch()

        # Wait until airborne.
        dt = 1.0
        t = 0.0
        while f.state == FS_TAKEOFF and t < 300.0:
            f.update(dt, bases)
            t += dt

        # Kill both bases.
        airfield_struct.alive = False
        carrier_ship.hp = 0
        carrier_ship.state = ST_SINKING

        # Force bingo so RTB is triggered.
        f._fuel_s = f._bingo_s + 1.0
        f.update(dt, bases)  # triggers RTB -> winchester
        assert f.state == FS_WINCHESTER_EGRESS

        # Fly until GONE.
        t = 0.0
        while f.state != FS_GONE and t < 10_000.0:
            f.update(dt, bases)
            t += dt
        assert f.state == FS_GONE

    def test_winchester_holds_when_both_die_inside_approach(self):
        """Regression: both bases dying while the fighter is RTB INSIDE the
        5 km landing-approach gate must still egress (spec 5.1: both
        destroyed -> map edge), never re-enter LANDING at the dead base.
        (The RTB handler used to run after the winchester decision and
        clobbered it via the approach-distance gate.)"""
        airfield_struct = _make_stub_structure((0.0, 0.0))
        carrier_ship = Carrier("cv_appr", (100_000.0, 0.0))
        ab1 = AirBase(airfield_struct)
        ab2 = AirBase(carrier_ship)
        bases = [ab1, ab2]

        f = Fighter("f_appr", ab1, (0.0, 50_000.0))
        f.state = FS_RTB
        f.pos = np.array([0.0, 3_000.0, 4_000.0])  # 4 km out, on approach
        f._speed = 240.0

        airfield_struct.alive = False
        carrier_ship.hp = 0
        carrier_ship.state = ST_SINKING

        f.update(1.0, bases)
        assert f.state == FS_WINCHESTER_EGRESS

        t = 0.0
        while f.state != FS_GONE and t < 10_000.0:
            f.update(1.0, bases)
            t += 1.0
        assert f.state == FS_GONE
        # Never touched the dead base's ground queue.
        assert f not in ab1._rearm_queue and f not in ab1.parked


# ---------------------------------------------------------------------------
# 8. nearest_surviving_base switches when airfield dies (integration)
# ---------------------------------------------------------------------------

class TestNearestBaseSwitches:
    def test_rtb_switches_to_carrier_on_airfield_death(self):
        """Fighter RTB-ing to an airfield that dies mid-approach re-selects
        the carrier on the next update tick."""
        airfield_struct = _make_stub_structure((0.0, 600_000.0))
        carrier_ship = Carrier("cv_sw2", (0.0, 250_000.0))
        ab1 = AirBase(airfield_struct)
        ab2 = AirBase(carrier_ship)
        bases = [ab1, ab2]

        f = Fighter("f_sw", ab1, (0.0, 700_000.0))
        f.launch()
        dt = 1.0
        # Get airborne.
        for _ in range(30):
            f.update(dt, bases)

        # Force RTB toward airfield.
        f._fuel_s = f._bingo_s + 1.0
        f.update(dt, bases)
        assert f.state == FS_RTB
        assert f._base is ab1

        # Kill the airfield.
        airfield_struct.alive = False

        # One more update: fighter should notice its base is dead.
        f.update(dt, bases)
        # Now it should have switched to ab2 (or to WINCHESTER if only carrier matters).
        assert f._base is ab2 or f.state == FS_WINCHESTER_EGRESS


# ---------------------------------------------------------------------------
# 9. AWACS orbit + flee
# ---------------------------------------------------------------------------

class TestAwacs:
    def _make_awacs(self):
        # Deep orbit: ~250-330 km from base
        return Awacs(
            "awacs_1",
            anchor_a_xz=(200_000.0, 600_000.0),
            anchor_b_xz=(300_000.0, 700_000.0),
        )

    def test_awacs_is_air_true(self):
        a = self._make_awacs()
        assert a.is_air is True

    def test_awacs_alive_initially(self):
        a = self._make_awacs()
        assert a.alive is True

    def test_awacs_starts_at_correct_altitude(self):
        a = self._make_awacs()
        assert float(a.pos[1]) == pytest.approx(AWACS_ALT_M)

    def test_awacs_orbits_stays_near_anchor(self):
        """After 1800 s the AWACS stays within the racetrack bounding box + slack."""
        a = self._make_awacs()
        ax_min, az_min = 200_000.0, 600_000.0
        ax_max, az_max = 300_000.0, 700_000.0
        slack = 100_000.0  # 100 km — generous for a racetrack
        for _ in range(1800):
            a.update(1.0)
            x, z = float(a.pos[0]), float(a.pos[2])
            assert ax_min - slack <= x <= ax_max + slack
            assert az_min - slack <= z <= az_max + slack

    def test_awacs_altitude_stays_constant(self):
        a = self._make_awacs()
        for _ in range(60):
            a.update(1.0)
        assert float(a.pos[1]) == pytest.approx(AWACS_ALT_M)

    def test_flee_turns_away_from_threat(self):
        """After flee() the AWACS should be converging toward the away-heading.

        We set the AWACS heading to already point south (180 deg) so we don't
        have to wait for the full turn.  Then we call flee() with a northern
        threat and confirm the heading stays near 180 (i.e. the fleeing logic
        is commanding the correct direction).
        """
        a = self._make_awacs()
        # Force the AWACS to a known position AND heading (south = 180 deg).
        a.pos[0] = 250_000.0
        a.pos[2] = 650_000.0
        a.heading = math.pi   # pointing south already
        threat_pos = np.array([250_000.0, 0.0, 750_000.0])  # north of AWACS
        a.flee(threat_pos)
        assert a._fleeing is True

        # The flee heading should be south (≈ π).
        assert abs(a._flee_heading - math.pi) < math.radians(5.0), (
            f"flee heading {math.degrees(a._flee_heading):.1f} deg, expected ~180")

        # Run 30 s: heading should remain in the southern half (90–270 deg).
        for _ in range(30):
            a.update(1.0)
        heading_deg = math.degrees(a.heading) % 360
        assert 90.0 <= heading_deg <= 270.0, (
            f"AWACS not fleeing south after 30 s: heading={heading_deg:.1f} deg")

    def test_flee_heading_directly_away(self):
        """flee() sets the flee heading to point away from the threat."""
        a = self._make_awacs()
        a.pos[0] = 0.0
        a.pos[2] = 0.0
        # Threat is to the east (positive X).
        threat = np.array([10_000.0, 0.0, 0.0])
        a.flee(threat)
        # flee_heading should point west (negative X, heading ~= -90 deg = 270 deg).
        away = math.atan2(
            float(a.pos[0]) - float(threat[0]),
            float(a.pos[2]) - float(threat[2]),
        )
        assert a._flee_heading == pytest.approx(away, abs=0.01)

    def test_stop_flee(self):
        a = self._make_awacs()
        a.flee(np.array([0.0, 0.0, 0.0]))
        assert a._fleeing is True
        a.stop_flee()
        assert a._fleeing is False


# ---------------------------------------------------------------------------
# 10. Nose-radar cone: behind NOT detected, ahead IS detected
# ---------------------------------------------------------------------------

class TestFighterNoseRadar:
    def _make_radar_at(self, pos_xz, heading_deg):
        pos = np.array([pos_xz[0], FIGHTER_ALT_M, pos_xz[1]], dtype=np.float64)
        r = FighterRadar("test_radar", pos, 0.0)
        r._heading_ref = math.radians(heading_deg)
        return r

    def test_target_ahead_detected(self):
        """Target dead ahead (0 deg relative) should be detected (if in range)."""
        r = self._make_radar_at((0.0, 0.0), 0.0)   # heading north
        # Target 50 km north at fighter altitude — well within 110 km range.
        target = np.array([0.0, FIGHTER_ALT_M, 50_000.0])
        # Must be within the cone and within range; terrain/horizon OK for peer alt.
        assert r.detects(target, "fighter") is True

    def test_target_behind_not_detected(self):
        """Target dead behind (180 deg relative) must NOT be detected."""
        r = self._make_radar_at((0.0, 0.0), 0.0)   # heading north
        # Target 50 km SOUTH = behind.
        target = np.array([0.0, FIGHTER_ALT_M, -50_000.0])
        assert r.detects(target, "fighter") is False

    def test_target_just_outside_cone_not_detected(self):
        """A target at exactly FOV_HALF + 1 deg is outside the cone."""
        r = self._make_radar_at((0.0, 0.0), 0.0)   # heading north
        # Bearing: FOV_HALF + 1 deg = 61 deg from north.
        angle = FIGHTER_RADAR_FOV_HALF + math.radians(1.0)
        dist = 50_000.0
        tx = math.sin(angle) * dist
        tz = math.cos(angle) * dist
        target = np.array([tx, FIGHTER_ALT_M, tz])
        assert r.detects(target, "fighter") is False

    def test_target_just_inside_cone_detected(self):
        """A target at FOV_HALF - 1 deg should pass the cone check (range OK)."""
        r = self._make_radar_at((0.0, 0.0), 0.0)
        angle = FIGHTER_RADAR_FOV_HALF - math.radians(1.0)
        dist = 50_000.0
        tx = math.sin(angle) * dist
        tz = math.cos(angle) * dist
        target = np.array([tx, FIGHTER_ALT_M, tz])
        assert r.detects(target, "fighter") is True

    def test_stealth_beyond_11km_not_detected(self):
        """Stealth target at 12 km is outside the 11 km stealth range."""
        r = self._make_radar_at((0.0, 0.0), 0.0)
        target = np.array([0.0, FIGHTER_ALT_M, 12_000.0])
        assert r.detects(target, "stealth") is False

    def test_stealth_within_11km_detected(self):
        """Stealth target at 8 km ahead should be detected."""
        r = self._make_radar_at((0.0, 0.0), 0.0)
        target = np.array([0.0, FIGHTER_ALT_M, 8_000.0])
        assert r.detects(target, "stealth") is True


# ---------------------------------------------------------------------------
# 11. AWACS radar — look-down skimmer vs stealth range
# ---------------------------------------------------------------------------

class TestAwacsRadar:
    def _make_awacs_centered(self):
        """AWACS sitting at (0, AWACS_ALT_M, 0) — simplest LOS geometry."""
        a = Awacs("awacs_r", (-1000.0, -1000.0), (1000.0, 1000.0))
        # Override orbit position for a controlled test: place it at the origin.
        a.pos[:] = [0.0, AWACS_ALT_M, 0.0]
        a.radar.pos[:] = [0.0, AWACS_ALT_M, 0.0]
        return a

    def test_awacs_radar_ranges_correct(self):
        a = self._make_awacs_centered()
        assert a.radar.ranges["fighter"] == pytest.approx(400_000.0)
        assert a.radar.ranges["ship"]    == pytest.approx(350_000.0)
        assert a.radar.ranges["missile"] == pytest.approx(350_000.0)
        assert a.radar.ranges["stealth"] == pytest.approx( 40_000.0)

    def test_awacs_detects_skimmer_at_200km(self):
        """AWACS at 9 100 m should see a 60 m sea-skimmer at 200 km.

        Horizon: K*(sqrt(9100) + sqrt(60)) ≈ 4120*(95.4 + 7.7) ≈ 425 km.
        The target is at 200 km, well within the 350 km missile range and
        horizon.  Terrain is flat ocean (returns 0 or negative), so LOS is
        unblocked.
        """
        a = self._make_awacs_centered()
        # Skimmer at 200 km north, 60 m alt.
        target = np.array([0.0, 60.0, 200_000.0])
        assert a.radar.detects(target, "missile") is True

    def test_awacs_does_not_detect_stealth_beyond_40km(self):
        """Stealth target at 41 km must be outside the 40 km stealth range."""
        a = self._make_awacs_centered()
        target = np.array([0.0, FIGHTER_ALT_M, 41_000.0])
        assert a.radar.detects(target, "stealth") is False

    def test_awacs_detects_stealth_within_40km(self):
        """Stealth target at 35 km should be detected by AWACS radar."""
        a = self._make_awacs_centered()
        target = np.array([0.0, FIGHTER_ALT_M, 35_000.0])
        assert a.radar.detects(target, "stealth") is True

    def test_awacs_radar_emitting_by_default(self):
        """AWACS actively emits by default (unlike the carrier)."""
        a = self._make_awacs_centered()
        assert a.radar.emitting is True

    def test_awacs_silent_radar_sees_nothing(self):
        """When AWACS radar is silenced it detects nothing."""
        a = self._make_awacs_centered()
        a.radar.emitting = False
        target = np.array([0.0, FIGHTER_ALT_M, 50_000.0])
        assert a.radar.detects(target, "fighter") is False
