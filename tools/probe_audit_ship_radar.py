"""AUDIT PROBE: enemy ship search radar (SPY-1) detection + horizon.

Measures sim/radar.py Radar.detects() as wired onto the enemy Destroyer's
SPY-1 (sim/enemy_ships.py) and as exercised through world/combat.py. PRINTS
numbers. Run: python tools/probe_audit_ship_radar.py  (pygame banner -> stderr).

What we measure
---------------
 1. radar_horizon_m(): the closed-form 4/3-earth horizon (sanity vs formula).
 2. SPY-1 max detection range vs TARGET ALTITUDE (the horizon wall) for each
    size class — esp. sea-skimmers (15 m) vs high cruise vs the 30 km stealth.
 3. Range-class gating: does ship/fighter/missile/stealth each cap correctly?
 4. The exact detection-range step as a target climbs (horizon vs nominal cap).
 5. Determinism: detects() is pure geometry -> identical across runs.
 6. World-wired check: build a CombatWorld, pull a real Destroyer.radar and
    confirm its pos tracks the hull and the same numbers hold in situ.
 7. Terrain LOS: place a target behind nothing (open sea) -> detects; confirm
    the LOS sampler does not spuriously block over flat water.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from sim.radar import Radar, radar_horizon_m, terrain_blocks, HORIZON_K  # noqa: E402
from sim.enemy_ships import Destroyer, _SPY1_ANTENNA_M, _SPY1_RANGES  # noqa: E402


def hr(title):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


# Build a standalone SPY-1 the same way the Destroyer does: mast at the
# waterline (y=0 -> sea level), antenna 20 m up.  IMPORTANT: place it over
# OPEN WATER (a real destroyer anchor) — the home continent at the map origin
# sits ~75 m ASL, which would put the 20 m mast *below* surrounding terrain
# and make the terrain LOS sampler block everything (a probe artifact, not a
# radar property).  Real destroyer anchors measure terrain ~ -100 m.
SEA_ANCHOR = (-20_000.0, 0.0, 150_000.0)   # destroyer_00 anchor: water ~-137 m


def fresh_spy1(pos=SEA_ANCHOR):
    return Radar("probe_spy1", pos, _SPY1_ANTENNA_M, dict(_SPY1_RANGES))


def max_detect_range(radar, size_class, target_alt, hi=400_000.0, tol=1.0):
    """Binary-search the max ground range at which detects() is True for a
    target at altitude `target_alt`. Returns None if never detected even at
    range 0 (shouldn't happen)."""
    # sweep along +Z out to sea from the radar mast (deep open water there:
    # the destroyer anchors are at z 150-280 km over terrain ~ -100 m).
    rx, _, rz = float(radar.pos[0]), float(radar.pos[1]), float(radar.pos[2])

    def det(rng):
        return radar.detects((rx, target_alt, rz + rng), size_class)
    if not det(0.0):
        return None
    lo, h = 0.0, hi
    if det(h):
        return h  # capped by nominal range, not horizon
    while h - lo > tol:
        mid = 0.5 * (lo + h)
        if det(mid):
            lo = mid
        else:
            h = mid
    return lo


def main():
    hr("1) radar_horizon_m() closed form  (HORIZON_K = %.1f)" % HORIZON_K)
    print(f"  antenna_alt = {_SPY1_ANTENNA_M:.1f} m (SPY-1 array)")
    for h_t in (0.0, 5.0, 15.0, 50.0, 100.0, 1000.0, 9000.0, 18000.0):
        d = radar_horizon_m(_SPY1_ANTENNA_M, h_t)
        # manual check
        man = HORIZON_K * (math.sqrt(_SPY1_ANTENNA_M) + math.sqrt(h_t))
        print(f"  h_target={h_t:8.1f} m -> horizon = {d/1000:8.2f} km   "
              f"(formula check {man/1000:8.2f} km, match={abs(d-man)<1e-6})")

    hr("2) SPY-1 MAX DETECTION RANGE vs TARGET ALTITUDE (open sea, flat water)")
    print("   nominal ranges: " + ", ".join(
        f"{k}={v/1000:.0f}km" for k, v in _SPY1_RANGES.items()))
    radar = fresh_spy1()
    profiles = [
        ("missile",  15.0,  "sea-skimmer Oniks/Zircon terminal (15 m)"),
        ("missile",  50.0,  "low TLAM-class cruise (50 m)"),
        ("missile", 1000.0, "Oniks lo-lo midcourse-ish (1 km)"),
        ("missile",14000.0, "Oniks hi-lo apex (14 km)"),
        ("ship",      10.0,  "enemy/merchant hull mast (10 m)"),
        ("fighter", 9000.0,  "fighter at 9 km"),
        ("fighter",  100.0,  "low fighter (100 m)"),
        ("stealth",18000.0,  "recon drone cruise (18 km)"),
        ("stealth",   50.0,  "low stealth (50 m)"),
    ]
    for sc, alt, label in profiles:
        rng = max_detect_range(radar, sc, alt)
        horizon = radar_horizon_m(radar.antenna_alt, alt)
        nominal = _SPY1_RANGES[sc]
        wall = "HORIZON" if rng is not None and rng < nominal - 100 else "NOMINAL"
        rng_km = "none" if rng is None else f"{rng/1000:7.2f}"
        print(f"  [{sc:7}] alt={alt:8.1f}m  detect<= {rng_km} km  "
              f"(horizon {horizon/1000:7.2f} km, cap {nominal/1000:.0f} km) "
              f"-> limited by {wall:7}  | {label}")

    hr("3) RANGE-CLASS GATING — same target alt, different size_class lookups")
    radar = fresh_spy1()
    alt = 100.0
    for sc in ("ship", "fighter", "missile", "stealth", "BOGUS_CLASS"):
        # at a fixed 28 km the stealth cap (30 km) is still in play; vary alt high
        rng = max_detect_range(radar, sc, alt)
        rng_km = "none (cap 0?)" if rng is None else f"{rng/1000:.2f} km"
        print(f"  size_class={sc:12} (alt {alt:.0f} m): max detect = {rng_km}")
    print("  NOTE: unknown size_class -> ranges.get(...,0.0) -> never detects.")

    hr("4) DETECTION RANGE STEPS as a sea-skimmer climbs (the horizon wall)")
    radar = fresh_spy1()
    print("  size_class=missile; the cap is 300 km but horizon dominates low:")
    for alt in (0.0, 5.0, 10.0, 15.0, 25.0, 50.0, 100.0, 300.0,
                1000.0, 5000.0, 15000.0):
        rng = max_detect_range(radar, "missile", alt)
        rng_km = "none" if rng is None else f"{rng/1000:8.2f}"
        print(f"   alt={alt:9.1f} m -> detect range {rng_km} km")

    hr("5) DETERMINISM — detects() is pure geometry")
    r1 = fresh_spy1()
    r2 = fresh_spy1()
    rx, rz = float(r1.pos[0]), float(r1.pos[2])
    pts = [(rx + np.random.default_rng(i).uniform(0, 60000),
            np.random.default_rng(i + 100).uniform(0, 200),
            rz + np.random.default_rng(i + 200).uniform(0, 60000))
           for i in range(2000)]
    a = [r1.detects(p, "missile") for p in pts]
    b = [r2.detects(p, "missile") for p in pts]
    print(f"  2000 random points: identical={a == b}, "
          f"#detected={sum(a)}/{len(a)}")
    # repeat call stability (a 30 m target 20 km out: inside horizon)
    p = (rx, 30.0, rz + 20000.0)
    calls = [r1.detects(p, "missile") for _ in range(5)]
    print(f"  same point x5 (20km,30m): {calls}")

    hr("6) WORLD-WIRED — real Destroyer.radar in a CombatWorld")
    from world.combat import CombatWorld
    from world.combat_config import CombatConfig
    from sim.enemy_ships import Destroyer as _D
    w = CombatWorld(CombatConfig(seed=7))
    dests = [s for s in w.ships if isinstance(s, _D) and type(s).__name__ == "Destroyer"]
    print(f"  destroyers found: {len(dests)}")
    for d in dests:
        r = d.radar
        print(f"  {d.ship_id}: hull=({d.pos[0]/1000:.1f},{d.pos[2]/1000:.1f})km "
              f"radar_pos=({r.pos[0]/1000:.1f},{r.pos[2]/1000:.1f})km "
              f"antenna_alt={r.antenna_alt:.1f}m alive={r.alive} emit={r.emitting} "
              f"ranges={ {k:int(v) for k,v in r.ranges.items()} }")
    # step the world a bit; confirm radar.pos tracks the moving hull
    d0 = dests[0]
    before = (float(d0.pos[0]), float(d0.pos[2]))
    rbefore = (float(d0.radar.pos[0]), float(d0.radar.pos[2]))
    for _ in range(600):  # ~5 s at 120 Hz
        w.step(1.0 / 120.0)
    after = (float(d0.pos[0]), float(d0.pos[2]))
    rafter = (float(d0.radar.pos[0]), float(d0.radar.pos[2]))
    moved = math.hypot(after[0] - before[0], after[1] - before[1])
    sync_err = math.hypot(rafter[0] - after[0], rafter[1] - after[1])
    print(f"  after 5 s: hull moved {moved:.1f} m; radar->hull sync error "
          f"= {sync_err:.3e} m (should be ~0)")

    # alive flag follows ship death (ShipDefense.step sets it)
    print(f"  d0.radar.alive before kill: {d0.radar.alive}")

    hr("7) TERRAIN LOS over open water (terrain_blocks must NOT spuriously block)")
    radar = fresh_spy1()
    rx, rz = float(radar.pos[0]), float(radar.pos[2])
    # target 40 km further out to sea, 100 m alt, straight over deep water
    a = (rx, radar.antenna_alt, rz)
    b = (rx, 100.0, rz + 40000.0)
    blocked = terrain_blocks(a, b)
    print(f"  open-sea LOS 0->40km @100m: terrain_blocks={blocked} "
          f"(expect False over water)")
    # detection that depends on LOS
    print(f"  detects(+40km,100m,missile) = {radar.detects(b, 'missile')}")
    # CONTRAST: the same radar placed at the map origin (home continent,
    # terrain ~75 m) — mast is BELOW the land, so LOS is blocked: this is the
    # artifact that bit the first probe run, shown deliberately.
    land_radar = Radar("land", (0.0, 0.0, 0.0), _SPY1_ANTENNA_M, dict(_SPY1_RANGES))
    bl = (0.0, 100.0, 40000.0)
    print(f"  [contrast] radar on land@origin: terrain_blocks="
          f"{terrain_blocks((0.0, land_radar.antenna_alt, 0.0), bl)} "
          f"(mast 20m sits under ~75m terrain)")

    hr("8) SUMMARY NUMBERS for the finding")
    radar = fresh_spy1()
    skim = max_detect_range(radar, "missile", 15.0)
    skim5 = max_detect_range(radar, "missile", 5.0)
    high = max_detect_range(radar, "missile", 14000.0)
    drone = max_detect_range(radar, "stealth", 18000.0)
    ship10 = max_detect_range(radar, "ship", 10.0)
    print(f"  sea-skimmer 15 m  : {skim/1000:.1f} km  (vs 300 km cap)")
    print(f"  sea-skimmer  5 m  : {skim5/1000:.1f} km")
    print(f"  hi cruise  14 km  : {high/1000:.1f} km")
    print(f"  recon drone 18 km : {drone/1000:.1f} km (stealth cap 30 km)")
    print(f"  hull mast 10 m    : {ship10/1000:.1f} km  (vs 300 km cap)")


if __name__ == "__main__":
    main()
