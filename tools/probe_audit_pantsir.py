"""AUDIT PROBE: player Pantsir-S1 (57E6 SAM channel + 30 mm gun) point defense.

Measures, never trusts comments:
  A. PANTSIR_57E6 / gun static parameters (sanity).
  B. Radar detection geometry (range/horizon gating).
  C. Track formation timing (sustained-detection gate).
  D. 57E6 SAM channel: does it launch? at what ground range? does it kill an
     inbound strike missile, and at what intercept range? (deterministic + 1 seed)
  E. 30 mm gun channel ALONE (SAM disabled): does it engage and kill inside
     4 km? Measure empirical Pk vs range across many seeds.
  F. Full-engagement statistics: N seeded runs, SAM+gun, leak rate.
  G. Determinism: same seed -> identical outcome.
  H. Real CombatWorld wiring sanity.

Run:  python tools/probe_audit_pantsir.py   (ignore the pygame banner on stderr)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math
import numpy as np

from sim.arsenal import PANTSIR_57E6, HARM
from sim.pantsir import (Pantsir, _UnitDefense, _Pantsir30mmGun, _RelTarget,
                         TRACK_FORM_S, VIS_CHECK_PERIOD, SAM_MIN_RANGE_M,
                         MISSILE_RELOAD_S, GUN_RANGE_M, PANTSIR_MAX_INFLIGHT,
                         PANTSIR_RADAR_RANGES)
from sim.strike import StrikeMissile
from sim.radar import radar_horizon_m
from world.generation import terrain_height_scalar

DT = 1.0 / 120.0

# Use a realistic, near-flat terrain patch so the geometry matches the game:
# the Pantsir sits ON terrain (Y = ground height), the radar antenna clears
# the ground, and inbound threats cruise ABOVE terrain.  We pick the terrain
# height at the deployment site and treat the local patch as flat at that
# height for the StubWorld physics (the real terrain rolls 70-100 m here).
SITE_X, SITE_Z = 0.0, 0.0
GROUND = terrain_height_scalar(SITE_X, SITE_Z)   # ~76 m
# Clear-air skim margin above ground for the inbound sea/land-skimmer.
SKIM = 40.0


# ---------------------------------------------------------------------------
# Minimal world stub.  terrain_height_at returns the local ground height so
# the SamMissile + StrikeMissile terrain/surface checks are self-consistent
# with where we place everything.
# ---------------------------------------------------------------------------
class StubWorld:
    def __init__(self):
        self.missiles = []
        self.events = []
        self.sim_time = 0.0

    def terrain_height_at(self, x, z):
        return GROUND


def make_inbound_strike(start_x, alt, target_xz, speed=270.0):
    """A hostile HARM-class strike missile flying toward -X (toward the
    Pantsir).  Pre-set with level inbound velocity; we drive its kinematics
    each step.  alt is ABSOLUTE (ASL)."""
    m = StrikeMissile(
        HARM,
        pos_f64=np.array([start_x, alt, SITE_Z]),
        vel_f64=np.array([-speed, 0.0, 0.0]),
        target_xz=target_xz,
        target_y=GROUND,
    )
    return m


def fly_strike_simple(m, dt):
    """Advance a strike missile on a straight level inbound leg WITHOUT its
    own phase machine (keeps the kinematics clean and controllable for
    intercept-range measurement).  Updates prev_pos so the SAM fuse segment
    check works."""
    np.copyto(m.prev_pos, m.pos)
    m.pos += m.vel * dt
    m.t += dt


def banner(t):
    print("\n" + "=" * 72)
    print(t)
    print("=" * 72)


# ===========================================================================
banner("A. STATIC PARAMETERS (57E6 SamDef + 30 mm gun)")
w = PANTSIR_57E6
print(f"  57E6 max_range          = {w.max_range:>10,.0f} m")
print(f"  57E6 terminal_range     = {w.terminal_range:>10,.0f} m")
print(f"  57E6 fuse_radius        = {w.fuse_radius:>10,.1f} m")
print(f"  57E6 max_g              = {w.max_g:>10,.0f} g")
print(f"  57E6 min_intercept_alt  = {w.min_intercept_alt:>10,.1f} m")
print(f"  57E6 max_intercept_alt  = {w.max_intercept_alt:>10,.0f} m")
print(f"  57E6 self_destruct_t    = {w.self_destruct_t:>10,.0f} s")
print(f"  57E6 self_destruct_spd  = {w.self_destruct_speed:>10,.0f} m/s")
g = _Pantsir30mmGun(700, np.random.default_rng(0))
print(f"  gun ENGAGE_RANGE        = {g._ENGAGE_RANGE:>10,.0f} m")
print(f"  gun R_NEAR / R_FAR      = {g._R_NEAR:>6,.0f} / {g._R_FAR:,.0f} m")
print(f"  gun P_NEAR / P_FAR      = {g._P_NEAR:>6.2f} / {g._P_FAR:.2f}")
print(f"  gun rd/s effective      = {g._ROUNDS_PER_SECOND:>10,.0f}")
print(f"  controller gates: TRACK_FORM={TRACK_FORM_S}s VIS={VIS_CHECK_PERIOD}s "
      f"SAM_MIN={SAM_MIN_RANGE_M:,.0f}m RELOAD={MISSILE_RELOAD_S}s "
      f"MAX_INFLIGHT={PANTSIR_MAX_INFLIGHT}")
print(f"  radar ranges            = {PANTSIR_RADAR_RANGES}")
# rounds per burst from inherited Ciws cadence (BURST_FIRE_TIME=1.0)
import sim.ciws as _c
print(f"  gun rounds/burst        = {int(g._ROUNDS_PER_SECOND * _c.BURST_FIRE_TIME)}"
      f"  (BURST_FIRE={_c.BURST_FIRE_TIME}s PAUSE={_c.BURST_PAUSE_TIME}s)")


# ===========================================================================
banner("B. RADAR DETECTION GEOMETRY (missile-class target)")
print(f"  (Pantsir on terrain at Y={GROUND:.1f} m; antenna +5 m; threats ASL)")
unit = Pantsir("p", np.array([SITE_X, GROUND, SITE_Z]),
               missile_ammo=12, gun_ammo=700, rng=np.random.default_rng(1))
ant = float(unit.radar.antenna_alt)
for rng_m, alt in [(35_000, GROUND + 40), (30_000, GROUND + 40),
                   (29_000, GROUND + 40), (20_000, GROUND + 40),
                   (10_000, GROUND + 20), (4_000, GROUND + 20)]:
    tp = np.array([SITE_X + float(rng_m), float(alt), SITE_Z])
    det = unit.radar.detects(tp, "missile")
    hor = radar_horizon_m(ant, float(alt))
    print(f"  ground_range={rng_m:>7,d} m  alt={alt:>6.0f} m ASL  "
          f"horizon={hor:>9,.0f} m  detects={det}")


# ===========================================================================
banner("C. TRACK FORMATION TIMING")
sw = StubWorld()
unit = Pantsir("p", np.array([SITE_X, GROUND, SITE_Z]),
               missile_ammo=12, gun_ammo=700, rng=np.random.default_rng(2))
ud = _UnitDefense(unit)
# A target sitting still well inside radar range; we just step tracking.
m = make_inbound_strike(15_000.0, GROUND + 60.0, (SITE_X, SITE_Z))
m.vel[:] = 0.0  # hold still: measure pure track-form gate timing
sw.missiles.append(m)
formed_at = None
for i in range(int(3.0 / DT)):
    sw.sim_time = i * DT
    ud._update_tracks(sw.missiles, sw.sim_time, DT)
    st = ud._tracks.get(id(m))
    if st and ud._tracked(st, sw.sim_time) and formed_at is None:
        formed_at = sw.sim_time
        break
print(f"  track formed at t = {formed_at:.3f} s  (TRACK_FORM_S={TRACK_FORM_S}, "
      f"VIS_CHECK_PERIOD={VIS_CHECK_PERIOD})")


# ===========================================================================
banner("D. 57E6 SAM CHANNEL — full intercept of an inbound strike missile")


def run_sam_intercept(seed, start_x=18_000.0, alt=80.0, speed=270.0,
                      sam_enabled=True, gun_enabled=True, max_t=120.0,
                      verbose=False):
    """One deterministic engagement.  Returns dict of measured outcomes."""
    sw = StubWorld()
    unit = Pantsir("p", np.array([SITE_X, GROUND, SITE_Z]),
                   missile_ammo=(12 if sam_enabled else 0),
                   gun_ammo=(700 if gun_enabled else 0),
                   rng=np.random.default_rng(seed))
    ud = _UnitDefense(unit)
    structures = []  # no structures: tti = inf, ranking still picks the threat

    m = make_inbound_strike(SITE_X + start_x, GROUND + alt, (SITE_X, SITE_Z),
                            speed=speed)
    sw.missiles.append(m)

    def grng():  # ground range of the threat from the Pantsir site
        return math.hypot(float(m.pos[0]) - SITE_X, float(m.pos[2]) - SITE_Z)

    sam_launch_range = None
    sam_launch_count = 0
    gun_bursts = 0
    kill_kind = None       # "sam" / "gun_fuse?" -> we detect by which event
    kill_range = None      # ground range of the threat at the moment it died
    intercept_alt = None
    steps = int(max_t / DT)
    for i in range(steps):
        sw.sim_time = i * DT
        # advance the inbound threat kinematically (straight level)
        if m.alive:
            fly_strike_simple(m, DT)
        # advance any 57E6 rounds in flight (real SamMissile physics)
        for mis in sw.missiles:
            if mis is m:
                continue
            if mis.alive:
                mis.update(DT, sw)
        # step the Pantsir fire control (tracks, SAM launch, gun)
        n_ev_before = len(sw.events)
        ud.step(sw, DT, structures)
        # inspect new events
        for kind, pos in sw.events[n_ev_before:]:
            if kind == "pantsir_launch":
                sam_launch_count += 1
                # record ground range of the THREAT at launch moment
                if sam_launch_range is None:
                    sam_launch_range = grng()
            elif kind == "pantsir_gun":
                gun_bursts += 1
            elif kind == "pantsir_kill":
                if kill_kind is None:
                    kill_kind = "gun"
        # detect SAM fuse kill: the threat dies but no pantsir_kill event was
        # emitted this step (the 57E6 fuse sets m.alive=False directly).
        if not m.alive and kill_range is None:
            kill_range = grng()
            intercept_alt = float(m.pos[1])
            if kill_kind is None:
                kill_kind = "sam_fuse"
            if verbose:
                print(f"    threat died t={sw.sim_time:.2f}s "
                      f"range={kill_range:,.0f}m alt={intercept_alt:,.0f}m "
                      f"via={kill_kind}")
            break
        # threat reached the base (leaked)
        if m.alive and grng() < 50.0:
            break

    leaked = m.alive
    return dict(seed=seed, leaked=leaked, kill_kind=kill_kind,
                kill_range=kill_range, intercept_alt=intercept_alt,
                sam_launch_range=sam_launch_range,
                sam_launch_count=sam_launch_count, gun_bursts=gun_bursts,
                t_end=sw.sim_time, threat_alive=m.alive)


r = run_sam_intercept(seed=100, verbose=True)
print(f"  SAM+gun seed=100: leaked={r['leaked']} kill_via={r['kill_kind']}")
print(f"    first SAM launch when threat at ground range = "
      f"{r['sam_launch_range']:,.0f} m" if r['sam_launch_range'] else
      "    no SAM launched")
print(f"    SAM launches fired = {r['sam_launch_count']}")
if r['kill_range'] is not None:
    print(f"    INTERCEPT at ground range {r['kill_range']:,.0f} m, "
          f"alt {r['intercept_alt']:,.0f} m")


# ===========================================================================
banner("E. 30 mm GUN CHANNEL ALONE (SAM disabled) — engage + Pk vs range")
# Run a stationary-target gun engagement to measure empirical burst Pk at a
# fixed slant range, comparing to the spec ramp.
def gun_pk_at_range(slant, n=4000):
    """Fire complete bursts at a target held at fixed slant range; measure the
    fraction of bursts that kill.  Drives _Pantsir30mmGun.engage directly with
    a stub relative-frame target moving inbound (closing>0)."""

    class T:
        def __init__(self):
            self.pos = np.array([slant, 0.0, 0.0])
            self.alive = True

        def velocity(self):
            return np.array([-300.0, 0.0, 0.0])  # closing

    kills = 0
    bursts = 0
    rng = np.random.default_rng(7)
    # one gun, fire many bursts; reset target.alive each burst
    gun = _Pantsir30mmGun(10 ** 9, rng)
    t = T()
    # We need many completed bursts; the burst cadence completes every
    # (PAUSE+FIRE) seconds.  Step dt and count completed bursts via events.
    steps = 0
    while bursts < n and steps < n * 400:
        steps += 1
        t.alive = True if t is not None else True
        evs = gun.engage(t, DT)
        for kind, _ in evs:
            if kind == "pantsir_gun":
                bursts += 1
            if kind == "pantsir_kill":
                kills += 1
        # keep target alive so the gun keeps firing bursts (we only sample Pk)
        t.alive = True
    return kills / bursts if bursts else float("nan"), bursts


for slant in [4000.0, 3000.0, 2000.0, 1000.0, 500.0]:
    pk, nb = gun_pk_at_range(slant, n=3000)
    # expected from ramp
    if slant <= 1000.0:
        exp = 0.55
    elif slant >= 4000.0:
        exp = 0.15
    else:
        tt = (slant - 1000.0) / (4000.0 - 1000.0)
        exp = 0.55 + tt * (0.15 - 0.55)
    print(f"  slant={slant:>6,.0f} m  empirical Pk/burst={pk:.3f}  "
          f"expected={exp:.3f}  (n={nb} bursts)")

# Now a realistic gun-only intercept: SAM disabled, threat must get inside 4 km.
banner("E2. GUN-ONLY intercept run (SAM ammo=0), 12 seeds")
gun_only_kills = 0
gun_only_ranges = []
for s in range(12):
    rr = run_sam_intercept(seed=200 + s, start_x=8_000.0, alt=30.0,
                           sam_enabled=False, gun_enabled=True)
    if not rr['leaked']:
        gun_only_kills += 1
        gun_only_ranges.append(rr['kill_range'])
print(f"  gun-only kills: {gun_only_kills}/12")
if gun_only_ranges:
    print(f"  gun kill ground-range: min={min(gun_only_ranges):,.0f} "
          f"max={max(gun_only_ranges):,.0f} "
          f"mean={sum(gun_only_ranges)/len(gun_only_ranges):,.0f} m")


# ===========================================================================
banner("F. FULL-ENGAGEMENT STATISTICS (SAM+gun), 24 seeds, lo-lo sea-skimmer")
kills = 0
leaks = 0
sam_kills = 0
gun_kills = 0
launch_ranges = []
intercept_ranges = []
for s in range(24):
    rr = run_sam_intercept(seed=300 + s, start_x=18_000.0, alt=60.0,
                           speed=270.0)
    if rr['leaked']:
        leaks += 1
    else:
        kills += 1
        if rr['kill_kind'] == 'gun':
            gun_kills += 1
        else:
            sam_kills += 1
        if rr['kill_range'] is not None:
            intercept_ranges.append(rr['kill_range'])
    if rr['sam_launch_range']:
        launch_ranges.append(rr['sam_launch_range'])
print(f"  kills={kills}/24  leaks={leaks}/24  "
      f"(sam_fuse_kills={sam_kills} gun_kills={gun_kills})")
if launch_ranges:
    print(f"  SAM launch ground-range: min={min(launch_ranges):,.0f} "
          f"max={max(launch_ranges):,.0f} "
          f"mean={sum(launch_ranges)/len(launch_ranges):,.0f} m")
if intercept_ranges:
    print(f"  intercept ground-range: min={min(intercept_ranges):,.0f} "
          f"max={max(intercept_ranges):,.0f} "
          f"mean={sum(intercept_ranges)/len(intercept_ranges):,.0f} m")


# ===========================================================================
banner("F2. SAM-ONLY (gun disabled) + FAST Mach-2 threat (680 m/s)")
# SAM-only slow threat: isolate the missile channel kill behaviour.
sam_only_kills = 0
sam_only_ranges = []
for s in range(12):
    rr = run_sam_intercept(seed=400 + s, start_x=18_000.0, alt=60.0,
                           speed=270.0, gun_enabled=False)
    if not rr['leaked']:
        sam_only_kills += 1
        if rr['kill_range']:
            sam_only_ranges.append(rr['kill_range'])
print(f"  SAM-only kills (slow 270 m/s): {sam_only_kills}/12")
if sam_only_ranges:
    print(f"    intercept range mean={sum(sam_only_ranges)/len(sam_only_ranges):,.0f} m")
# Fast Mach-2 cruise threat, full SAM+gun.
fast_kills = 0
fast_leaks = 0
fast_ranges = []
fast_via = {"sam_fuse": 0, "gun": 0}
for s in range(12):
    rr = run_sam_intercept(seed=500 + s, start_x=19_000.0, alt=80.0,
                           speed=680.0)
    if rr['leaked']:
        fast_leaks += 1
    else:
        fast_kills += 1
        fast_via[rr['kill_kind']] = fast_via.get(rr['kill_kind'], 0) + 1
        if rr['kill_range']:
            fast_ranges.append(rr['kill_range'])
print(f"  FAST 680 m/s SAM+gun: kills={fast_kills}/12 leaks={fast_leaks}/12 "
      f"via={fast_via}")
if fast_ranges:
    print(f"    intercept range min={min(fast_ranges):,.0f} "
          f"max={max(fast_ranges):,.0f} "
          f"mean={sum(fast_ranges)/len(fast_ranges):,.0f} m")


# ===========================================================================
banner("G. DETERMINISM — same seed twice")
a = run_sam_intercept(seed=999)
b = run_sam_intercept(seed=999)
same = (a['kill_kind'] == b['kill_kind']
        and a['leaked'] == b['leaked']
        and (a['kill_range'] is None) == (b['kill_range'] is None)
        and (a['kill_range'] is None
             or abs(a['kill_range'] - b['kill_range']) < 1e-6))
print(f"  run1: kind={a['kill_kind']} leaked={a['leaked']} "
      f"kill_range={a['kill_range']}")
print(f"  run2: kind={b['kill_kind']} leaked={b['leaked']} "
      f"kill_range={b['kill_range']}")
print(f"  DETERMINISTIC = {same}")


# ===========================================================================
banner("H. REAL CombatWorld wiring sanity")
try:
    from world.combat import CombatWorld
    from world.combat_config import CombatConfig
    cw = CombatWorld(CombatConfig(seed=7))
    print(f"  n pantsirs            = {len(cw.pantsirs)}")
    net = getattr(cw, "radar_net", None)
    net_radars = getattr(net, "radars", []) if net is not None else []
    for u in cw.pantsirs:
        terr = cw.terrain_height_at(float(u.pos[0]), float(u.pos[2]))
        print(f"    {u.unit_id}: pos=({u.pos[0]:,.0f},{u.pos[2]:,.0f}) "
              f"Y={u.pos[1]:.1f} (terrain {terr:.1f}) "
              f"missile_ammo={u.missile_ammo} gun_ammo={u.gun_ammo} "
              f"alive={u.alive} radar_in_net={u.radar in net_radars}")
    print(f"  has pantsir_defense controller = "
          f"{hasattr(cw, 'pantsir_defense')}")
except Exception as e:
    import traceback
    print("  CombatWorld build FAILED:")
    traceback.print_exc()

print("\n[probe complete]")
