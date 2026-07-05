"""Tests: IrMissile (AIM-9X-class) + 40N6 player SAM + fighter employment.

Covers (spec §5.1 + §4.3b + task brief):

1. IR lock honours aspect-dependent range bands (rear 8 km, front 4 km).
2. IR launch produces NO RWR spike on the drone.
3. Kinematic miss beyond energy: target at 12 km crossing — missile falls
   short (self-destructs without fuse trigger).
4. 40N6 SamDef sanity: weapon_id, max_range, motor, fuse_radius, seeker mode.
5. 40N6 active-seeker kill: illuminator_pos_fn=None (own seeker), no
   illuminator dependency — kills a high-altitude target.
6. 40N6 refuses sub-4 km-alt targets (min_intercept_alt envelope gate).
7. launch_sam round selection: separate ammo pools; '48n6' and '40n6' both
   work; combined pool drains correctly.
8. Fighter execute_order transitions:
   a. execute_order("intercept") sets state to TRANSIT, radar emitting=True.
   b. execute_order("strike") sets state to TRANSIT, radar emitting=False.
   c. execute_order("cap") sets radar emitting=True.
   d. execute_order("rtb") sets radar emitting=False.
   e. Winchester after empty hardpoints triggers RTB.
9. assign_loadout applied on next launch (not immediately).

All tests are GL-free, pure numpy/math.
"""

import math
import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Stub world (flat, no ships) — the same minimal pattern used in test_sam.py
# ---------------------------------------------------------------------------

class _FlatWorld:
    ships = []

    def terrain_height_at(self, x, z):
        return -100.0


# ---------------------------------------------------------------------------
# 1. IR lock honours range/aspect bands
# ---------------------------------------------------------------------------

from sim.a2a import (
    IrMissile, IR_LOCK_RANGE_REAR_M, IR_LOCK_RANGE_FRONT_M,
    _ir_lock_range_m, _aspect_angle_rad,
    IRP_BOOST, IRP_COAST, IRP_DEAD,
)


def test_ir_lock_range_rear():
    """At 0 deg aspect (pure tail) lock range == IR_LOCK_RANGE_REAR_M."""
    r = _ir_lock_range_m(0.0)
    assert abs(r - IR_LOCK_RANGE_REAR_M) < 1.0, f"rear lock range={r}"


def test_ir_lock_range_front():
    """At pi rad aspect (pure head-on) lock range == IR_LOCK_RANGE_FRONT_M."""
    r = _ir_lock_range_m(math.pi)
    assert abs(r - IR_LOCK_RANGE_FRONT_M) < 1.0, f"front lock range={r}"


def test_ir_lock_range_beam():
    """At 90 deg aspect (beam shot) lock range is the midpoint 6 km."""
    r = _ir_lock_range_m(math.pi / 2.0)
    expected_mid = (IR_LOCK_RANGE_REAR_M + IR_LOCK_RANGE_FRONT_M) / 2.0
    assert abs(r - expected_mid) < 200.0, f"beam lock range={r}, expected~{expected_mid}"


def test_ir_aspect_ok_rear_within_range():
    """Rear shot at 7 km (same altitude, 3D distance = 7 km) should lock."""
    # Keep both at same altitude so 3D distance equals horizontal.
    alt = 9_000.0
    shooter = np.array([0.0, alt, 0.0])
    target  = np.array([0.0, alt, 7_000.0])   # 7 km north — pure rear
    tvel    = np.array([0.0, 0.0, 160.0])      # flying north (away)
    can_lock, lock_r = IrMissile.aspect_ok(shooter, target, tvel,
                                            shooter_heading_rad=0.0)
    assert can_lock, f"rear-7km should lock, lock_r={lock_r}"


def test_ir_aspect_ok_rear_beyond_range():
    """Rear shot at 10 km (same altitude) should NOT lock (> 8 km rear band)."""
    alt = 9_000.0
    shooter = np.array([0.0, alt, 0.0])
    target  = np.array([0.0, alt, 10_000.0])
    tvel    = np.array([0.0, 0.0, 160.0])
    can_lock, _ = IrMissile.aspect_ok(shooter, target, tvel,
                                       shooter_heading_rad=0.0)
    assert not can_lock, "10 km rear should exceed lock range"


def test_ir_aspect_ok_front_within_range():
    """Head-on shot at 3.5 km should lock (within 4 km front band).

    Head-on geometry: target is SOUTH of shooter, flying NORTH (toward shooter).
    Shooter faces south (heading = pi).  LOS = south, tvel = north -> aspect = pi.
    """
    alt = 9_000.0
    shooter = np.array([0.0, alt, 0.0])
    target  = np.array([0.0, alt, -3_500.0])   # target 3.5 km south
    tvel    = np.array([0.0, 0.0, 160.0])       # flying NORTH toward shooter
    can_lock, _ = IrMissile.aspect_ok(shooter, target, tvel,
                                       shooter_heading_rad=math.pi)
    assert can_lock, "3.5 km head-on should lock"


def test_ir_aspect_ok_front_beyond_range():
    """Head-on shot at 5 km should NOT lock (> 4 km front band)."""
    alt = 9_000.0
    shooter = np.array([0.0, alt, 0.0])
    target  = np.array([0.0, alt, -5_000.0])
    tvel    = np.array([0.0, 0.0, 160.0])       # flying NORTH toward shooter
    can_lock, _ = IrMissile.aspect_ok(shooter, target, tvel,
                                       shooter_heading_rad=math.pi)
    assert not can_lock, "5 km head-on exceeds 4 km front band"


def test_ir_obs_limit_refused():
    """Off-boresight > 25 deg should refuse the shot even if within range."""
    shooter = np.array([0.0, 9_000.0, 0.0])
    # Target 5 km to the east (90 deg off boresight), fighter faces north
    target  = np.array([5_000.0, 18_000.0, 1_000.0])
    tvel    = np.array([0.0, 0.0, 160.0])  # flying north
    # Fighter heading = 0 (north), target is mostly east -> OBS > 25 deg
    can_lock, _ = IrMissile.aspect_ok(shooter, target, tvel,
                                       shooter_heading_rad=0.0)
    assert not can_lock, "OBS > 25 deg should refuse the shot"


# ---------------------------------------------------------------------------
# 2. No RWR spike on IR launch — drone state unchanged
# ---------------------------------------------------------------------------

from sim.recon import RwrReceiver, RWR_CLEAR, RWR_SPIKE, RWR_LOCK


def test_ir_launch_no_rwr_spike():
    """Firing an IrMissile must NOT change the drone's RWR state.

    Contract: IR is a passive seeker — zero RF emission.  The drone's RWR
    SPIKE detector only watches active radars; the LOCK detector only watches
    SamMissile targets.  An IrMissile targeting the drone registers on neither
    channel (no radar_id attribute; not a SamMissile).
    """
    # Minimal drone stub: the RWR only needs .pos and .aircraft_id
    class _DroneStub:
        aircraft_id = "drone_00"
        pos = np.array([0.0, 18_000.0, 6_000.0])
        alive = True
        def velocity(self):
            return np.array([0.0, 0.0, 160.0])

    drone = _DroneStub()
    rwr = RwrReceiver(drone_id="drone_00",
                      height_fn=lambda x, z: -100.0)

    # Launch the missile.
    shooter_pos = np.array([0.0, 9_000.0, 0.0])
    shooter_vel = np.array([0.0, 0.0, 240.0])
    missile = IrMissile(shooter_pos, shooter_vel, drone)

    # RWR update: pass the missile in the 'enemy_missiles' list.
    # The RWR checks for SamMissile.target.aircraft_id == drone.aircraft_id.
    # IrMissile has a .target but no .radar or .radar_id — it must be silent.
    rwr.update(
        drone_pos=drone.pos,
        enemy_radars=[],                 # no active radars
        enemy_missiles=[missile],        # the IR missile IS in-flight
    )

    # The RWR must show CLEAR (not LOCK) because IrMissile is not a SamMissile
    # and the RWR LOCK gate specifically checks for the 'target.aircraft_id'
    # on objects in enemy_missiles.  IrMissile.target IS the drone, but
    # the RWR lock gate also requires aircraft_id matching; that check IS
    # present in sim/recon.py.  Confirm no alerts at all.
    alerts = rwr.alerts()
    assert len(alerts) == 0, (
        f"IR launch must not spike the RWR; got alerts={alerts}"
    )


# ---------------------------------------------------------------------------
# 3. Kinematic miss: target at 12 km crossing, missile falls short
# ---------------------------------------------------------------------------

def test_ir_kinematic_miss_12km_crossing():
    """A drone 12 km away crossing at DRONE_SPEED_MPS — the missile was
    launched beyond the 8 km rear lock range so aspect_ok() should refuse it.
    If somehow launched anyway (manual IrMissile construction at 12 km), the
    missile must self-destruct without triggering the fuse.
    """
    DT = 1.0 / 120.0
    T_MAX = 90.0   # s; kinematic miss must happen well before the flight envelope

    # Drone at 12 km range, crossing (heading east) at drone cruise speed.
    class _CrossingDrone:
        def __init__(self):
            self.pos = np.array([12_000.0, 18_000.0, 0.0], dtype=np.float64)
            self.alive = True
        def velocity(self):
            return np.array([160.0, 0.0, 0.0], dtype=np.float64)

    drone = _CrossingDrone()

    shooter_pos = np.array([0.0, 9_000.0, 0.0])
    shooter_vel = np.array([0.0, 0.0, 240.0])  # north at cruise

    # Verify aspect_ok refuses the 12 km shot (should be beyond 8 km range).
    tvel = drone.velocity()
    can_lock, _ = IrMissile.aspect_ok(shooter_pos, drone.pos, tvel,
                                       shooter_heading_rad=math.atan2(
                                           float(drone.pos[0] - shooter_pos[0]),
                                           float(drone.pos[2] - shooter_pos[2])
                                       ))
    # Range check: 12 km > 8 km -> should refuse
    dist = float(np.linalg.norm(drone.pos - shooter_pos))
    assert dist > IR_LOCK_RANGE_REAR_M, "test setup: drone must be beyond rear lock range"
    assert not can_lock, "aspect_ok must refuse 12 km beyond rear range"

    # Construct the missile manually (bypasses the lock check) to verify
    # kinematic behavior: the missile will guide on a target it can barely
    # hold and self-destruct.
    m = IrMissile(shooter_pos, shooter_vel, drone)
    w = _FlatWorld()
    t = 0.0
    while m.alive and t < T_MAX:
        # Update drone position (crossing east)
        drone.pos = drone.pos + drone.velocity() * DT
        m.update(DT, w)
        t += DT

    assert not m.alive, "missile must be dead (kinematic miss or self-destruct)"
    assert not m.killed_target, (
        "fuse must NOT have triggered on a 12 km crossing target launched beyond lock range"
    )


# ---------------------------------------------------------------------------
# 4. 40N6 SamDef sanity check
# ---------------------------------------------------------------------------

from sim.arsenal import N40N6, N40N6_AMMO, SAMS


def test_40n6_def_sanity():
    """40N6 definition: locked physical parameters."""
    assert N40N6.weapon_id == "40n6"
    assert N40N6.max_range == pytest.approx(380_000.0)
    assert N40N6.min_intercept_alt == pytest.approx(4_000.0)
    assert N40N6.fuse_radius == pytest.approx(25.0)
    assert N40N6.motor_thrust > 200_000.0, "40N6 motor must exceed 48N6 200 kN"
    assert N40N6.motor_time > 12.0, "40N6 burn must exceed 48N6 12 s"
    assert N40N6.terminal_range > 20_000.0, "40N6 seeker range must exceed 48N6 20 km"
    # Active seeker mode: no illuminator field in SamDef (the sam.py
    # illuminator_pos_fn=None means own-seeker, which IS the active mode).
    # We can't check illuminator_pos_fn here — it is a runtime kwarg.
    # Confirm the registry entry exists.
    assert "40n6" in SAMS
    assert SAMS["40n6"] is N40N6
    # Stock constant.
    assert N40N6_AMMO == 2


# ---------------------------------------------------------------------------
# 5. 40N6 active-seeker kill (illuminator_pos_fn=None)
# ---------------------------------------------------------------------------

from sim.sam import SamMissile, SPH_DEAD
from sim.aircraft import AC_ALIVE, AC_FALLING, Aircraft


def test_40n6_active_seeker_kill():
    """40N6 with illuminator_pos_fn=None (own seeker) kills a high-altitude
    aircraft at ~100 km.  No illuminator object needed — ARH mode.
    """
    DT = 1.0 / 120.0
    T_MAX = 200.0  # s; 100 km shot should connect in ~100-150 s

    # High-altitude crossing target: ~100 km range, 20 km altitude.
    target = Aircraft("f1", "patrol",
                      (-100_000.0, 20_000.0),
                      (-80_000.0, 90_000.0))
    # Force to cruise altitude.
    target.pos[:] = [-100_000.0, 20_000.0, 0.0]

    launch_pos = np.array([0.0, 160.0, 0.0])   # TEL on the coastal shelf

    # illuminator_pos_fn=None == ARH / active-seeker mode (spec §4.3b).
    m = SamMissile(N40N6, launch_pos, target, illuminator_pos_fn=None)

    w = _FlatWorld()
    t = 0.0
    while m.alive and t < T_MAX:
        target.update(DT)
        m.update(DT, w)
        t += DT

    assert m.killed_target, (
        f"40N6 active-seeker must kill 100 km / 20 km altitude target "
        f"(no illuminator); alive={m.alive}, killed={m.killed_target}, t={t:.1f}"
    )


# ---------------------------------------------------------------------------
# 6. 40N6 refuses sub-4 km-alt targets via launch_sam
# ---------------------------------------------------------------------------

from world.world import WorldState


def _combat_world_for_sam_test():
    """Minimal WorldState with enough mocking to test launch_sam selection."""
    ws = WorldState()
    return ws


def test_40n6_refuses_low_altitude():
    """launch_sam('40n6') returns None when target altitude < 4,000 m."""
    ws = WorldState()

    # Inject a fake contact at 1,000 m altitude.
    class _FakeTrack:
        pass

    import numpy as np
    fake_pos = np.array([0.0, 1_000.0, 10_000.0])
    fake_vel = np.array([0.0, 0.0, 200.0])
    ws.contacts.tracks["low_target"] = {
        "pos": fake_pos,
        "vel": fake_vel,
        "age": 0.5,
        "is_air": True,
    }

    # Inject a fake target entity.
    class _FakeTarget:
        aircraft_id = "low_target"
        pos = fake_pos
        alive = True
        def velocity(self):
            return fake_vel

    ws.aircraft.append(_FakeTarget())

    # Attempt the 40N6 shot — must be refused (sub-4 km altitude).
    result = ws.launch_sam("low_target", round_id="40n6")
    assert result is None, (
        "launch_sam('40n6') must refuse targets below 4,000 m altitude"
    )


# ---------------------------------------------------------------------------
# 7. launch_sam round selection: separate ammo pools
# ---------------------------------------------------------------------------

def test_launch_sam_round_selection():
    """48n6 and 40n6 ammo pools drain separately; mixed shots work."""
    ws = WorldState()
    initial_48n6 = ws.sam_ammo
    initial_40n6 = ws.sam_ammo_40n6

    # Inject a high-altitude target (valid for 40n6).
    import numpy as np
    fake_pos_hi = np.array([0.0, 20_000.0, 10_000.0])
    fake_vel    = np.array([0.0, 0.0, 200.0])
    ws.contacts.tracks["hi_target"] = {
        "pos": fake_pos_hi,
        "vel": fake_vel,
        "age": 0.5,
        "is_air": True,
    }

    class _HiTarget:
        aircraft_id = "hi_target"
        pos = fake_pos_hi
        alive = True
        def velocity(self):
            return fake_vel
        def kill(self):
            pass

    tgt = _HiTarget()
    ws.aircraft.append(tgt)

    # Fire a 48N6.
    m1 = ws.launch_sam("hi_target", round_id="48n6")
    assert m1 is not None, "48N6 shot must succeed"
    assert ws.sam_ammo == initial_48n6 - 1, "48N6 ammo must decrease by 1"
    assert ws.sam_ammo_40n6 == initial_40n6, "40N6 ammo must be unchanged"

    # Reload (advance time past the reload timer).
    ws.sam_reload_left = 0.0

    # Fire a 40N6.
    m2 = ws.launch_sam("hi_target", round_id="40n6")
    assert m2 is not None, "40N6 shot must succeed for high-alt target"
    assert ws.sam_ammo == initial_48n6 - 1, "48N6 ammo must still be unchanged"
    assert ws.sam_ammo_40n6 == initial_40n6 - 1, "40N6 ammo must decrease by 1"


def test_launch_sam_40n6_exhausted():
    """Once 40N6 ammo runs out, further 40n6 shots return None."""
    ws = WorldState()

    import numpy as np
    fake_pos = np.array([0.0, 20_000.0, 10_000.0])
    fake_vel = np.array([0.0, 0.0, 200.0])
    ws.contacts.tracks["hi2"] = {
        "pos": fake_pos, "vel": fake_vel,
        "age": 0.5, "is_air": True,
    }

    class _HiTarget2:
        aircraft_id = "hi2"
        pos = fake_pos
        alive = True
        def velocity(self):
            return fake_vel
        def kill(self):
            pass

    ws.aircraft.append(_HiTarget2())

    # Fire all 40N6 rounds.
    fired = 0
    for _ in range(N40N6_AMMO + 1):
        ws.sam_reload_left = 0.0
        r = ws.launch_sam("hi2", round_id="40n6")
        if r is not None:
            fired += 1

    assert fired == N40N6_AMMO, (
        f"Expected exactly {N40N6_AMMO} 40N6 shots before empty; fired={fired}"
    )
    assert ws.sam_ammo_40n6 == 0


# ---------------------------------------------------------------------------
# 8. Fighter execute_order state transitions
# ---------------------------------------------------------------------------

from sim.enemy_air import (
    Fighter, AirBase, FS_TRANSIT, FS_ON_STATION, FS_RTB, FS_PARKED,
    LOADOUT_CAP, LOADOUT_STRIKE, LOADOUT_SEAD,
)
from sim.bases import Structure


def _make_base():
    """A minimal AirBase backed by a Structure stub."""
    class _StructStub:
        alive = True
        pos = np.array([0.0, 0.0, 0.0], dtype=np.float64)

    return AirBase(_StructStub())


def _make_airborne_fighter(base=None):
    """Fighter in ON_STATION state (airborne, radar emitting off by default)."""
    if base is None:
        base = _make_base()
    f = Fighter("f_test", base, patrol_anchor_xz=(0.0, 10_000.0))
    f.state = FS_ON_STATION
    f.pos[:] = [0.0, 9_000.0, 0.0]
    f._speed = 240.0
    f._alive = True
    f._hardpoints = list(LOADOUT_CAP)
    return f


def test_execute_order_intercept_sets_transit_and_radar_on():
    """execute_order('intercept') -> TRANSIT state, radar emitting=True."""
    f = _make_airborne_fighter()

    class _TargetStub:
        pos = np.array([10_000.0, 18_000.0, 20_000.0], dtype=np.float64)
        alive = True
        def velocity(self):
            return np.array([0.0, 0.0, 160.0], dtype=np.float64)

    f.execute_order({"type": "intercept", "target": _TargetStub()})

    assert f.state == FS_TRANSIT, f"intercept -> TRANSIT, got state={f.state}"
    assert f.radar.emitting, "intercept -> radar ON"


def test_execute_order_strike_sets_transit_and_radar_off():
    """execute_order('strike') -> TRANSIT, radar emitting=False (silent ingress)."""
    f = _make_airborne_fighter()
    f.radar.emitting = True  # start emitting, verify it turns off

    f.execute_order({
        "type": "strike",
        "standoff_xz": np.array([50_000.0, 200_000.0]),
    })

    assert f.state == FS_TRANSIT, f"strike -> TRANSIT, got state={f.state}"
    assert not f.radar.emitting, "strike ingress -> radar SILENT"


def test_execute_order_cap_radar_on():
    """execute_order('cap') while on station -> radar emitting=True."""
    f = _make_airborne_fighter()
    f.radar.emitting = False  # simulate a silent state

    f.execute_order({"type": "cap"})

    assert f.radar.emitting, "CAP -> radar ON"


def test_execute_order_rtb():
    """execute_order('rtb') -> radar off; state heading toward RTB."""
    f = _make_airborne_fighter()
    f.radar.emitting = True
    base = _make_base()

    f.execute_order({"type": "rtb", "bases": [base]})

    assert not f.radar.emitting, "RTB -> radar OFF"
    # State should be FS_RTB or FS_TRANSIT toward base
    assert f.state in (FS_RTB, FS_TRANSIT), f"RTB order -> state={f.state}"


def test_execute_order_intercept_empty_target():
    """execute_order('intercept') without a target sets radar on but no crash."""
    f = _make_airborne_fighter()
    f.execute_order({"type": "intercept"})   # no 'target' key
    assert f.radar.emitting, "intercept (no target) -> radar stays ON"
    assert f._intercept_target is None


# ---------------------------------------------------------------------------
# 9. assign_loadout applied on next launch (hardpoints empty until launch)
# ---------------------------------------------------------------------------

def test_assign_loadout_applied_on_launch():
    """Hardpoints should be empty at spawn; assigned loadout fills on launch."""
    base = _make_base()
    f = Fighter("f_loadout_test", base, patrol_anchor_xz=(0.0, 10_000.0))

    # Freshly created fighter: parked, hardpoints empty.
    assert f._hardpoints == [], "spawned fighter must have no hardpoints"

    # Assign a STRIKE loadout.
    f.assign_loadout(LOADOUT_STRIKE)
    assert f._hardpoints == [], "hardpoints must stay empty until launch"

    # Launch: hardpoints filled from the pending loadout.
    f.launch()
    assert list(f._hardpoints) == list(LOADOUT_STRIKE), (
        f"after launch hardpoints should be {LOADOUT_STRIKE!r}, "
        f"got {f._hardpoints!r}"
    )


def test_rearm_restores_hardpoints():
    """After rearming, hardpoints are replenished from the pending loadout."""
    base = _make_base()
    f = Fighter("f_rearm", base, patrol_anchor_xz=(0.0, 10_000.0))
    f.assign_loadout(LOADOUT_CAP)
    f.launch()
    assert list(f._hardpoints) == list(LOADOUT_CAP)

    # Exhaust weapons.
    f._hardpoints.clear()
    assert f.winchester

    # Assign a new loadout and trigger rearm completion.
    f.assign_loadout(LOADOUT_SEAD)
    f._rearm_complete()

    assert list(f._hardpoints) == list(LOADOUT_SEAD), (
        f"rearm must apply pending loadout; got {f._hardpoints!r}"
    )


def test_winchester_triggers_rtb():
    """release_weapons() with empty hardpoints calls RTB."""
    f = _make_airborne_fighter()
    f._hardpoints.clear()   # already winchester
    base = _make_base()
    # The release_weapons() call should flip state to RTB when winchester.
    # Pass an empty world_missiles list to avoid actual missile creation.
    world_missiles = []
    # We need to provide bases via the intercept_target = None path; the
    # execute_order("rtb") is called internally without bases — so state
    # will not flip to FS_RTB (no bases arg).  The test checks that
    # winchester is True and the execute_order("rtb") path was invoked
    # by checking the radar emitting flag (RTB order sets it False).
    f.radar.emitting = True
    f.release_weapons(world_missiles)
    # The fighter called execute_order({"type": "rtb"}) internally.
    # No bases arg -> _rtb may not flip to FS_RTB, but radar must be off.
    assert not f.radar.emitting, "winchester -> RTB order -> radar OFF"


# ---------------------------------------------------------------------------
# 8. 40N6 floor judges the DISPLAYED estimate, not the stale fix
#    Regression (live playtest 2026-07-05): a climbing target whose stale
#    radar fix sat below 4 km was denied with 'BELOW 4KM ENGAGEMENT FLOOR'
#    while the contact card showed 4.7-5.0 km.  The card displays the
#    dead-reckoned estimate (hud.intel_snapshot alt = estimated_pos()[1]);
#    the envelope gate must judge the SAME number — the player acts on
#    what they SEE.  Two-sided: the zero-rate low test above still refuses.
# ---------------------------------------------------------------------------


def _climbing_track():
    fix = np.array([0.0, 3_600.0, 10_000.0])     # stale fix below the floor
    vel = np.array([0.0, 80.0, 200.0])           # climbing +80 m/s
    # displayed estimate: 3,600 + 80*15 = 4,800 m — ABOVE the 4,000 m floor
    return {"pos": fix, "vel": vel, "age": 15.0, "is_air": True}


def test_40n6_floor_judges_displayed_estimate_sandbox_world():
    ws = WorldState()
    ws.contacts.tracks["climber"] = _climbing_track()

    class _FakeTarget:
        aircraft_id = "climber"
        pos = np.array([0.0, 4_800.0, 13_000.0])
        alive = True

        def velocity(self):
            return np.array([0.0, 80.0, 200.0])

    ws.aircraft.append(_FakeTarget())
    m = ws.launch_sam("climber", round_id="40n6")
    assert m is not None, (
        "40N6 must fire at a target DISPLAYED above the floor (est 4,800 m) "
        "even when the stale fix reads 3,600 m — gate on what the card shows"
    )


def test_40n6_floor_judges_displayed_estimate_combat_world():
    from world.combat import CombatWorld
    from world.combat_config import CombatConfig
    w = CombatWorld(CombatConfig(seed=1337))
    w.contacts.tracks["climber"] = _climbing_track()

    class _FakeTarget:
        aircraft_id = "climber"
        pos = np.array([0.0, 4_800.0, 13_000.0])
        alive = True

        def velocity(self):
            return np.array([0.0, 80.0, 200.0])

    w.aircraft.append(_FakeTarget())
    m = w.launch_sam("climber", round_id="40n6")
    assert m is not None, (
        "combat launch_sam must gate the 40N6 floor on the dead-reckoned "
        "estimate the card displays, not the stale fix"
    )
