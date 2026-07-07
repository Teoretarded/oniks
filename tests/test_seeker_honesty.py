"""R-P1 seeker honesty contracts (spec: weather_system_design_2026-07-07.md
PART 2 §10; plan: radar_scan_seeker_honesty_plan_2026-07-07.md).

The Oniks/Zircon active-radar terminal seeker must obey the same physics
its victims' radars obey: the radar horizon and terrain masking.  Before
this pass it read truth ships anywhere inside its gimbal cone — a 50 km
acquisition from a 12 m sea-skim is geometrically impossible (horizon to a
~18 m superstructure is ~32 km).
"""

import math

import numpy as np

from sim.arsenal import ONIKS
from sim.missile import Missile, SHIP_MAST_M


class _StubWorld:
    """Minimal duck-type for _acquire_lock: ships + the terrain query.
    radar_model='scanned' arms the honest-seeker gates (the game layer
    always plays scanned; 'functional' keeps the legacy truth-in-cone
    seeker for the byte-identity suite)."""

    def __init__(self, ships, height_fn=None, radar_model="scanned"):
        self.ships = ships
        self.radar_model = radar_model
        if height_fn is not None:
            self.terrain_height_at = height_fn
        else:
            self.terrain_height_at = lambda x, z: 0.0


class _Ship:
    def __init__(self, x, z, alive=True):
        self.pos = np.array([x, 15.0, z])
        self.alive = alive
        self.vel = np.zeros(3)

    def velocity(self):
        return self.vel


def _terminal_oniks(alt):
    """Bare Missile carrying only what _acquire_lock reads."""
    m = Missile.__new__(Missile)
    m.weapon = ONIKS
    m.pos = np.array([0.0, alt, 0.0])
    m.vel = np.array([0.0, 0.0, 680.0])     # flying north
    m.locked_ship = None
    return m


def test_oniks_seeker_horizon_limited():
    m = _terminal_oniks(alt=12.0)                       # 12 m sea-skim
    far = _Ship(0.0, 45_000.0)                          # beyond the horizon
    m._acquire_lock(_StubWorld([far]), speed=680.0)
    assert m.locked_ship is None
    near = _Ship(0.0, 25_000.0)                         # inside the horizon
    m._acquire_lock(_StubWorld([near]), speed=680.0)
    assert m.locked_ship is near


def test_oniks_seeker_blocked_by_island():
    def ridge(x, z):
        # 2 km wide so the long-range 2 km LOS sample step cannot straddle
        # it (terrain_blocks samples at z = 2000*i over this 18 km line).
        return 140.0 if 7_500.0 < z < 9_500.0 else 0.0
    m = _terminal_oniks(alt=12.0)
    hidden = _Ship(0.0, 18_000.0)
    m._acquire_lock(_StubWorld([hidden], ridge), speed=680.0)
    assert m.locked_ship is None
    # Same geometry, no ridge: the lock is there (two-sided).
    m2 = _terminal_oniks(alt=12.0)
    open_ship = _Ship(0.0, 18_000.0)
    m2._acquire_lock(_StubWorld([open_ship]), speed=680.0)
    assert m2.locked_ship is open_ship


def test_high_diver_keeps_long_acquisition():
    # A Zircon-style high diver looks DOWN past any surface horizon — the
    # gates must not nerf the designed high-altitude acquisition geometry.
    m = _terminal_oniks(alt=15_000.0)
    m.vel = np.array([0.0, -300.0, 600.0])
    far = _Ship(0.0, 45_000.0)
    m._acquire_lock(_StubWorld([far]), speed=671.0)
    assert m.locked_ship is far


def test_horizon_math_matches_radar_module():
    # The seeker uses the SAME horizon helper as every radar (one physics).
    from sim.radar import radar_horizon_m
    horizon = radar_horizon_m(12.0, 15.0 + SHIP_MAST_M)
    assert 28_000.0 < horizon < 40_000.0    # sanity band for the test geoms


def test_functional_world_keeps_legacy_seeker():
    # Byte-identity flag: a functional-model world (the whole legacy test
    # suite) keeps the old truth-in-cone seeker verbatim.
    m = _terminal_oniks(alt=12.0)
    far = _Ship(0.0, 45_000.0)
    m._acquire_lock(_StubWorld([far], radar_model="functional"), speed=680.0)
    assert m.locked_ship is far


# --- Task 6: SAM terminal seeker cone + ARH/SARH illuminator physics ----------

from sim.arsenal import S300, N40N6                        # noqa: E402
from sim.sam import SamMissile, SPH_MIDCOURSE, SPH_TERMINAL  # noqa: E402


class _AirTgt:
    def __init__(self, x, y, z):
        self.pos = np.array([x, y, z])
        self.alive = True

    def velocity(self):
        return np.zeros(3)

    def kill(self):
        self.alive = False


class _SamWorld:
    def __init__(self, radar_model="scanned"):
        self.radar_model = radar_model
        self.terrain_height_at = lambda x, z: 0.0


def _sam_midcourse(sam_def, mpos, mvel, target, **kw):
    """A burned-out round parked at midcourse, one step from the handover
    check — only the phase machine is under test here."""
    m = SamMissile(sam_def, np.zeros(3), target, **kw)
    m.phase = SPH_MIDCOURSE
    m.pos = np.asarray(mpos, dtype=np.float64).copy()
    m.prev_pos = m.pos.copy()
    m.vel = np.asarray(mvel, dtype=np.float64).copy()
    m.propellant = 0.0
    m.t = 5.0
    return m


def _sam_terminal(sam_def, target, **kw):
    m = _sam_midcourse(sam_def, (0.0, 8_000.0, 0.0), (0.0, 0.0, 900.0),
                       target, **kw)
    m.phase = SPH_TERMINAL
    m._lock_pos = np.asarray(target.pos, dtype=np.float64).copy()
    m._los_next_t = 0.0
    return m


def test_sam_handover_requires_seeker_cone():
    # Target at 15 km due EAST of a round flying NORTH: inside the 20 km
    # range gate but 90 deg off the nose — a real seeker cannot acquire it.
    tgt = _AirTgt(15_000.0, 8_000.0, 0.0)
    m = _sam_midcourse(S300, (0.0, 8_000.0, 0.0), (0.0, 0.0, 900.0), tgt)
    m.update(1.0 / 120.0, _SamWorld("scanned"))
    assert m.phase == SPH_MIDCOURSE                     # cone refuses
    m2 = _sam_midcourse(S300, (0.0, 8_000.0, 0.0), (0.0, 0.0, 900.0), tgt)
    m2.update(1.0 / 120.0, _SamWorld("functional"))
    assert m2.phase == SPH_TERMINAL                     # legacy: range only


def test_sam_handover_cone_accepts_nose_target():
    tgt = _AirTgt(0.0, 8_000.0, 15_000.0)               # dead ahead
    m = _sam_midcourse(S300, (0.0, 8_000.0, 0.0), (0.0, 0.0, 900.0), tgt)
    m.update(1.0 / 120.0, _SamWorld("scanned"))
    assert m.phase == SPH_TERMINAL


def test_sarh_lock_dies_with_the_illuminator():
    ill = {"alive": True}
    tgt = _AirTgt(0.0, 8_000.0, 12_000.0)
    m = _sam_terminal(
        S300, tgt,
        illuminator_pos_fn=lambda: ((0.0, 5.0, 0.0) if ill["alive"]
                                    else None))
    m.update(1.0 / 120.0, _SamWorld("scanned"))
    assert m._lock_ok                                   # painting: lock holds
    ill["alive"] = False
    m._los_next_t = m.t                                 # force the re-check
    m.update(1.0 / 120.0, _SamWorld("scanned"))
    assert not m._lock_ok                               # frozen-point coast


def test_sarh_illuminator_off_sector_breaks_lock():
    tgt = _AirTgt(0.0, 8_000.0, 12_000.0)
    on_sector = {"v": True}
    m = _sam_terminal(S300, tgt,
                      illuminator_pos_fn=lambda: (0.0, 5.0, 0.0),
                      illuminator_ok_fn=lambda: on_sector["v"])
    m.update(1.0 / 120.0, _SamWorld("scanned"))
    assert m._lock_ok
    on_sector["v"] = False                              # FCR slewed away
    m._los_next_t = m.t
    m.update(1.0 / 120.0, _SamWorld("scanned"))
    assert not m._lock_ok


def test_arh_round_needs_no_illuminator():
    # 40N6: own seeker — no illuminator wired, the lock simply holds.
    tgt = _AirTgt(0.0, 8_000.0, 12_000.0)
    m = _sam_terminal(N40N6, tgt)
    m.update(1.0 / 120.0, _SamWorld("scanned"))
    assert m._lock_ok


# --- Task 7: AIM-9X in-flight gimbal FOV ---------------------------------------

def test_aim9x_loses_lock_past_gimbal():
    # Target teleported directly BEHIND the missile: a real seeker head
    # cannot look backwards — the lock is lost, the round self-destructs.
    from sim.a2a import IrMissile

    class _Drone:
        def __init__(self, pos):
            self.pos = np.asarray(pos, dtype=np.float64)
            self.alive = True

        def velocity(self):
            return np.array([0.0, 0.0, 60.0])

    class _W:
        terrain_height_at = staticmethod(lambda x, z: 0.0)
        radar_model = "scanned"

    drone = _Drone([0.0, 5_000.0, 5_000.0])
    m = IrMissile(np.array([0.0, 5_000.0, 0.0]),
                  np.array([0.0, 0.0, 300.0]), drone)   # flying north at it
    m.update(0.1, _W())
    assert m.alive                                       # nose-on: fine
    drone.pos = np.array([0.0, 5_000.0, -6_000.0])       # now BEHIND
    m.update(0.1, _W())
    assert not m.alive and m.self_destructed


def test_station_engagement_radar_exists_and_dies_with_station():
    from world.combat import CombatWorld
    from world.combat_config import CombatConfig
    w = CombatWorld(CombatConfig(radar_model="scanned"))
    eng = w.station_engagement
    assert eng.scan.kind == "sector" and eng.band == "X"
    assert eng.alive
    st = next(s for s in w.structures if s.kind == "radar_station")
    st.hp = 0
    st.alive = False
    st.on_destroyed(st)
    assert not w.radar_station.alive
    assert not eng.alive                                # dies with the mast
