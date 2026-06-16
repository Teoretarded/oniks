"""AUDIT PROBE: player recon drone low-observability vs enemy detection.

Measures (not reads comments):
  1. The 'stealth' detection range of every enemy sensor class against the
     drone's radar_size, swept metre-by-metre, vs the configured ranges.
  2. Whether the drone is INVISIBLE just outside the stealth ring and
     DETECTED just inside it ("the drone can sneak").
  3. Horizon-limited reach: does the 18 km cruise altitude let the 30 km
     stealth ring actually realize, or does the radar horizon cap it lower?
  4. The ship SM-2 / SM-6 drone-hunt TRIGGER ranges: at what ground range
     a destroyer's fire control forms a track and launches.
  5. Determinism: same seed -> same detection edge.

Run:  python tools/probe_audit_drone_stealth.py
(prints a pygame banner to stderr — ignore)
"""

import os
import sys
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from sim.radar import Radar, radar_horizon_m
from sim.recon import ReconDrone, DRONE_ALT_M, DRONE_SPEED_MPS
from sim.arsenal import SM2, SM6
import sim.enemy_defense as ed
from sim.enemy_ships import _SPY1_RANGES, _SPY1_ANTENNA_M, Destroyer
from sim.enemy_air import FIGHTER_RADAR_RANGES, AWACS_RADAR_RANGES
from world.combat import _ENEMY_RADAR_RANGES, _ENEMY_RADAR_ANTENNA_M, PLAYER_RADAR_RANGES


def hr(title):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def flat0(x, z):
    """Flat terrain at sea level — isolate range/horizon from terrain LOS."""
    return 0.0


# ---------------------------------------------------------------------------
# 1. Configured stealth ranges of every enemy sensor class
# ---------------------------------------------------------------------------
hr("1. CONFIGURED 'stealth'-class detection ranges (m) per sensor")
print(f"  drone.radar_size        = {ReconDrone.radar_size!r}")
print(f"  drone cruise altitude   = {DRONE_ALT_M:,.0f} m")
print(f"  SPY-1 (destroyer)       stealth = {_SPY1_RANGES['stealth']:>10,.0f}  (ship={_SPY1_RANGES['ship']:,.0f})")
print(f"  Enemy ground radar      stealth = {_ENEMY_RADAR_RANGES['stealth']:>10,.0f}  (ship={_ENEMY_RADAR_RANGES['ship']:,.0f})")
print(f"  AWACS                   stealth = {AWACS_RADAR_RANGES['stealth']:>10,.0f}  (fighter={AWACS_RADAR_RANGES['fighter']:,.0f})")
print(f"  Fighter nose radar      stealth = {FIGHTER_RADAR_RANGES['stealth']:>10,.0f}  (fighter={FIGHTER_RADAR_RANGES['fighter']:,.0f})")
print(f"  Player station (ref)    stealth = {PLAYER_RADAR_RANGES['stealth']:>10,.0f}")
print(f"  ship-class ratio: drone detected at "
      f"{100*_SPY1_RANGES['stealth']/_SPY1_RANGES['ship']:.1f}% of SPY-1 ship range")


# ---------------------------------------------------------------------------
# 2. MEASURED detection edge: sweep the drone outward, find where detects()
#    flips. SPY-1 antenna 20 m, drone at 18 km — check horizon doesn't cap.
# ---------------------------------------------------------------------------
hr("2. MEASURED detection edge per sensor (flat sea, drone @ 18 km alt)")


def sweep_edge(radar, alt, max_test, label, step=50.0):
    """Walk the drone east from the radar; return last detected & first miss."""
    last_det = None
    first_miss = None
    r = step
    while r <= max_test:
        tgt = np.array([float(radar.pos[0]) + r, alt, float(radar.pos[2])])
        det = radar.detects(tgt, "stealth")
        if det:
            last_det = r
        elif last_det is not None and first_miss is None:
            first_miss = r
            break
        r += step
    cfg = radar.ranges["stealth"]
    horizon = radar_horizon_m(radar.antenna_alt, alt)
    cap = "RANGE" if cfg <= horizon else "HORIZON"
    print(f"  {label:24s} cfg={cfg:>9,.0f}  horizon={horizon:>10,.0f}  "
          f"limiter={cap:7s}  last_DET={ (last_det or 0):>9,.0f}  "
          f"first_MISS={ (first_miss or 0):>9,.0f}")
    return last_det, first_miss, cfg, horizon


spy1 = Radar("spy1", np.array([0.0, 0.0, 0.0]), _SPY1_ANTENNA_M, dict(_SPY1_RANGES))
gnd = Radar("gnd", np.array([0.0, 0.0, 0.0]), _ENEMY_RADAR_ANTENNA_M, dict(_ENEMY_RADAR_RANGES))
# AWACS: airborne platform at 9.1 km, antenna offset 0 -> antenna at body alt.
awacs = Radar("awacs", np.array([0.0, 9_100.0, 0.0]), 0.0, dict(AWACS_RADAR_RANGES))
# Fighter nose radar at, say, 8 km alt.
fighter = Radar("ftr", np.array([0.0, 8_000.0, 0.0]), 0.0, dict(FIGHTER_RADAR_RANGES))

import sim.radar as radar_mod
_orig_height = radar_mod.terrain_height_scalar
radar_mod.terrain_height_scalar = flat0  # neutralize terrain default in terrain_blocks

sweep_edge(spy1, DRONE_ALT_M, 40_000.0, "SPY-1 (ship, ant 20 m)")
sweep_edge(gnd, DRONE_ALT_M, 40_000.0, "Ground radar (ant 18 m)")
sweep_edge(awacs, DRONE_ALT_M, 50_000.0, "AWACS (alt 9.1 km)")
sweep_edge(fighter, DRONE_ALT_M, 20_000.0, "Fighter nose (alt 8 km)")


# ---------------------------------------------------------------------------
# 3. "Can sneak": is the drone detected INSIDE the ring and INVISIBLE just
#    outside, for a SPY-1?
# ---------------------------------------------------------------------------
hr("3. CAN-SNEAK test (SPY-1): detection inside ring, blind outside")
edge = _SPY1_RANGES["stealth"]
for r in (edge - 5_000.0, edge - 100.0, edge + 100.0, edge + 5_000.0):
    tgt = np.array([r, DRONE_ALT_M, 0.0])
    print(f"  ground range {r:>9,.0f} m -> detects(stealth) = "
          f"{spy1.detects(tgt, 'stealth')}")
# Contrast: would a normal ship-class target (e.g. enemy thinks it's a ship)
# be seen way past the stealth ring? (Shows low-observability actually buys range.)
tgt_far = np.array([edge + 50_000.0, DRONE_ALT_M, 0.0])
print(f"  --- at {edge+50_000.0:,.0f} m: as 'stealth'={spy1.detects(tgt_far,'stealth')}  "
      f"as 'ship'={spy1.detects(tgt_far,'ship')}  (low-obs hides the drone where a ship would show)")


# ---------------------------------------------------------------------------
# 4. SM-2 / SM-6 drone-hunt trigger ranges (the fire-control gate)
# ---------------------------------------------------------------------------
hr("4. Drone-hunt engagement gates (ground range, m)")
print(f"  SM2_MIN_RANGE_M            = {ed.SM2_MIN_RANGE_M:>9,.0f}")
print(f"  DRONE_ENGAGE_RANGE_M (SM2) = {ed.DRONE_ENGAGE_RANGE_M:>9,.0f}  <- SM-2 drone cap")
print(f"  SM2.max_range              = {SM2.max_range:>9,.0f}")
print(f"  SM6 band start             = {ed.DRONE_ENGAGE_RANGE_M:>9,.0f}  -> SM6.max_range={SM6.max_range:,.0f}")
print(f"  SM2 intercept alt band     = [{SM2.min_intercept_alt:,.0f}, {SM2.max_intercept_alt:,.0f}]  drone@{DRONE_ALT_M:,.0f}")
print(f"  SM6 intercept alt band     = [{SM6.min_intercept_alt:,.0f}, {SM6.max_intercept_alt:,.0f}]")
print(f"  DRONE_SM2_MAX_INFLIGHT     = {ed.DRONE_SM2_MAX_INFLIGHT}   SM6_MAX_INFLIGHT={ed.SM6_MAX_INFLIGHT}")
print(f"  TRACK_FORM_S (sustain)     = {ed.TRACK_FORM_S} s   VIS_CHECK_PERIOD={ed.VIS_CHECK_PERIOD} s")

# Important contradiction check: SM-2 needs a 'stealth' DETECTION (30 km ring)
# to even form a track, but only LAUNCHES inside 22 km. SM-6 launches in the
# 22 km..(detect ring) band. But detection itself dies past 30 km, so SM-6's
# launch window vs the drone is only 22..30 km, NOT 22..240 km. Verify:
hr("4b. SM-6 vs drone: launch band gated by DETECTION, not SM6.max_range")
print("  A ship cannot TRACK the drone past its 30 km stealth ring, so even")
print("  though SM6.max_range = {:,.0f} m, the SM-6 drone window is".format(SM6.max_range))
print("  bounded above by the 30 km detection edge (need a track to launch).")
print(f"  -> effective SM-6 drone launch band ~ [22,000, {_SPY1_RANGES['stealth']:,.0f}] m")


# ---------------------------------------------------------------------------
# 5. End-to-end: a live ShipDefense, hand it a drone, sweep its position,
#    and observe WHEN it forms a track and launches. Measures the real gate.
# ---------------------------------------------------------------------------
hr("5. LIVE ShipDefense drone-hunt: track-form + launch range (seeded)")


class _MiniWorld:
    """Minimal world duck-type for ShipDefense.step."""
    def __init__(self, drone):
        self.missiles = []
        self.events = []
        self.sim_time = 0.0
        self.drone = drone


def run_engage(drone_x, seed=1234, dt=0.1, t_max=20.0, pin=False):
    """Place a stationary-ish drone at (drone_x, 18km, 0), a destroyer at origin,
    step the ShipDefense and report first track time and first launch range.
    pin=True clamps the drone to exactly (drone_x, 18km, 0) every step so the
    gate input ground range is exactly drone_x (no loiter drift)."""
    rng = np.random.default_rng(seed)
    ship = Destroyer("dd0", anchor_xz=np.array([0.0, 0.0]), sm2_ammo=8)
    ship.pos[:] = np.array([0.0, 0.0, 0.0])
    ship.radar.pos[:] = ship.pos
    # Give it ammo
    ship.sm2_ammo = 8
    ship.sm6_ammo = 4
    ship.sm2_reload_timer = 0.0
    ship.sm6_reload_timer = 0.0

    rng2 = np.random.default_rng(seed + 1)
    drone = ReconDrone("drone_00", spawn_xz=(drone_x, 0.0), rng=rng2,
                       height_fn=flat0)
    # Drone loiters in place at spawn -> sits ~drone_x from ship.
    drone.set_route([])

    defense = ed.ShipDefense(ship, rng)
    world = _MiniWorld(drone)

    first_track_t = None
    first_launch_t = None
    first_launch_kind = None
    launch_gr = None
    n = int(t_max / dt)
    for i in range(n):
        world.sim_time = i * dt
        drone.update(dt)
        if pin:
            drone.pos[:] = np.array([drone_x, DRONE_ALT_M, 0.0])
        # keep drone near drone_x ground range (loiter radius 4 km is fine)
        prev_n = len(world.missiles)
        defense.step(world, dt)
        # track formed?
        if first_track_t is None:
            for st in defense._drone_tracks.values():
                if defense._tracked(st, world.sim_time):
                    first_track_t = world.sim_time
                    break
        if first_launch_t is None and len(world.missiles) > prev_n:
            first_launch_t = world.sim_time
            m = world.missiles[-1]
            wpn = getattr(m, "weapon", None)
            first_launch_kind = getattr(wpn, "display_name", type(m).__name__)
            # ground range of the drone AT launch (the gate's actual input)
            launch_gr = math.hypot(float(drone.pos[0]), float(drone.pos[2]))
    # ground range now
    gr = math.hypot(float(drone.pos[0]) - 0.0, float(drone.pos[2]) - 0.0)
    detected = ship.radar.detects(drone.pos, "stealth")
    return dict(x=drone_x, gr=gr, detected=detected,
                track_t=first_track_t, launch_t=first_launch_t,
                kind=first_launch_kind, launch_gr=launch_gr,
                n_missiles=len(world.missiles))


print("  (drone loiters in a 4 km orbit around placed_x, so launch_gr is the")
print("   true ground range at the moment of the shot — that is the gate input)")
print(f"  {'placed_x':>10} {'launch_gr':>10} {'detect_now':>10} {'track@s':>8} "
      f"{'launch@s':>9} {'weapon':>10} {'#rounds':>8}")
for dx in (10_000.0, 18_000.0, 20_000.0, 22_000.0, 25_000.0, 28_000.0, 31_000.0, 40_000.0):
    r = run_engage(dx, pin=True)
    tt = f"{r['track_t']:.2f}" if r['track_t'] is not None else "none"
    lt = f"{r['launch_t']:.2f}" if r['launch_t'] is not None else "none"
    lg = f"{r['launch_gr']:,.0f}" if r['launch_gr'] is not None else "none"
    print(f"  {r['x']:>10,.0f} {lg:>10} {str(r['detected']):>10} "
          f"{tt:>8} {lt:>9} {str(r['kind']):>10} {r['n_missiles']:>8}")


# ---------------------------------------------------------------------------
# 5b. AWACS remote cue extends the SHIP's drone-track range to the AWACS ring
# ---------------------------------------------------------------------------
hr("5b. AWACS cue (40 km ring) lets a ship track the drone past its own 30 km")


def run_engage_cued(drone_x, seed=4242, dt=0.1, t_max=20.0):
    """Same as run_engage but the ship's fire control gets an AWACS cue radar
    co-located at origin (40 km stealth ring). Drone pinned at drone_x."""
    rng = np.random.default_rng(seed)
    ship = Destroyer("dd0", anchor_xz=np.array([0.0, 0.0]), sm2_ammo=8)
    ship.pos[:] = np.array([0.0, 0.0, 0.0])
    ship.radar.pos[:] = ship.pos
    ship.sm6_ammo = 4
    ship.sm2_reload_timer = ship.sm6_reload_timer = 0.0
    awacs_radar = Radar("awacs_cue", np.array([0.0, 9_100.0, 0.0]), 0.0,
                        dict(AWACS_RADAR_RANGES))
    defense = ed.ShipDefense(ship, rng, cue_radars_fn=lambda: [awacs_radar])
    rng2 = np.random.default_rng(seed + 1)
    drone = ReconDrone("drone_00", spawn_xz=(drone_x, 0.0), rng=rng2,
                       height_fn=flat0)
    drone.set_route([])
    world = _MiniWorld(drone)
    track_t = launch_t = launch_gr = kind = None
    for i in range(int(t_max / dt)):
        world.sim_time = i * dt
        drone.update(dt)
        drone.pos[:] = np.array([drone_x, DRONE_ALT_M, 0.0])
        prev_n = len(world.missiles)
        defense.step(world, dt)
        if track_t is None:
            for st in defense._drone_tracks.values():
                if defense._tracked(st, world.sim_time):
                    track_t = world.sim_time
                    break
        if launch_t is None and len(world.missiles) > prev_n:
            launch_t = world.sim_time
            kind = getattr(getattr(world.missiles[-1], "weapon", None),
                           "display_name", "?")
            launch_gr = drone_x
    own = ship.radar.detects(np.array([drone_x, DRONE_ALT_M, 0.0]), "stealth")
    return dict(x=drone_x, own_sees=own, track_t=track_t,
                launch_t=launch_t, kind=kind, n=len(world.missiles))


print(f"  {'placed_x':>10} {'own_SPY1_sees':>14} {'track@s':>8} {'launch@s':>9} {'weapon':>14} {'#':>3}")
for dx in (28_000.0, 33_000.0, 38_000.0, 42_000.0):
    r = run_engage_cued(dx)
    tt = f"{r['track_t']:.2f}" if r['track_t'] is not None else "none"
    lt = f"{r['launch_t']:.2f}" if r['launch_t'] is not None else "none"
    print(f"  {r['x']:>10,.0f} {str(r['own_sees']):>14} {tt:>8} {lt:>9} {str(r['kind']):>14} {r['n']:>3}")
print("  NOTE: track can form past the ship's own 30 km via the AWACS cue, but")
print("  the SM-6 ENVELOPE still gates on the dead-reckoned range vs SM6.max_range.")


# ---------------------------------------------------------------------------
# 6. Determinism: same seed -> identical launch outcome
# ---------------------------------------------------------------------------
hr("6. DETERMINISM: repeat seed=777 at 18 km twice")
a = run_engage(18_000.0, seed=777)
b = run_engage(18_000.0, seed=777)
print(f"  run A: track@{a['track_t']} launch@{a['launch_t']} kind={a['kind']} #={a['n_missiles']}")
print(f"  run B: track@{b['track_t']} launch@{b['launch_t']} kind={b['kind']} #={b['n_missiles']}")
print(f"  identical = {a == b}")

# restore
radar_mod.terrain_height_scalar = _orig_height
print("\n[done]")
