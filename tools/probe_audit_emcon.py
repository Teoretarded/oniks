"""Probe: enemy emissions control (EMCON) audit.

Question: Is the enemy smart about turning its radar OFF? Do enemy radars /
AWACS manage emissions, ever going silent to deny the drone ELINT/RWR, or do
they emit constantly?

We MEASURE three things:

  A. INITIAL emit states of every enemy radar (truth, at t=0).
  B. The commander's _defend_ship_radars doctrine in ISOLATION: drive it with
     synthetic drone-only / missile-only pictures and count the SHIP_SILENT /
     SHIP_EMIT orders it produces. (Unit-level: does the brain decide?)
  C. The INTEGRATED world: fly a drone near a destroyer and step the full
     CombatWorld; record when each enemy radar's .emitting flag flips. Also
     track the AWACS emit flag the whole time. (System-level: does it apply?)

Run:  python tools/probe_audit_emcon.py   (pygame banner -> stderr, ignore)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from world.combat import CombatWorld
from world.combat_config import CombatConfig
from sim.commander import EnemyCommander, EnemyPicture
from sim.enemy_air import Carrier


SEED = 12345


def emit_state(radar):
    return bool(getattr(radar, "emitting", None)) and bool(getattr(radar, "alive", True))


def section(t):
    print("\n" + "=" * 72)
    print(t)
    print("=" * 72)


# ---------------------------------------------------------------------------
# A. Initial emit states
# ---------------------------------------------------------------------------
def probe_initial_states(world):
    section("A. INITIAL ENEMY RADAR EMIT STATES (t=0, ground truth)")
    rows = []
    for s in world.ships:
        kind = "CARRIER" if isinstance(s, Carrier) else "destroyer"
        rows.append((f"{s.ship_id} ({kind})", emit_state(s.radar)))
    rows.append((f"{world.awacs.aircraft_id} (AWACS)", emit_state(world.awacs.radar)))
    grnd = getattr(world, "_enemy_ground_radars", [])
    for r in grnd:
        rows.append((f"{r.radar_id} (ground radar)", emit_state(r)))
    for f in world._fighter_list:
        rows.append((f"{f.aircraft_id} (fighter nose, parked)",
                     emit_state(f.radar)))
    for name, e in rows:
        print(f"  {name:42s} emitting={e}")
    n_emit = sum(1 for _, e in rows if e)
    print(f"\n  -> {n_emit}/{len(rows)} enemy radars EMITTING at start.")
    return rows


# ---------------------------------------------------------------------------
# B. Commander EMCON doctrine in isolation
# ---------------------------------------------------------------------------
class _FakeRadar:
    def __init__(self):
        self.emitting = True
        self.alive = True


class _FakeShip:
    def __init__(self, sid):
        self.ship_id = sid
        self.alive = True
        self.pos = np.zeros(3, dtype=np.float64)
        self.radar = _FakeRadar()


def probe_doctrine_isolated():
    section("B. COMMANDER _defend_ship_radars DOCTRINE (isolated, 4 cases)")
    results = {}

    def run_case(label, drone, missile):
        ships = [_FakeShip("d0"), _FakeShip("d1")]
        # one ship starts silent so we can observe an EMIT order too
        ships[1].radar.emitting = False
        pic = EnemyPicture()
        cmd = EnemyCommander([], None, ships, picture=pic, seed=0)
        now = 5.0
        if drone:
            pic.update_drone_track("drone_00",
                                   np.array([10_000.0, 20_000.0]), now)
        if missile:
            pic.update_missile_track("hostile_1",
                                     np.array([5_000.0, 0.0, 30_000.0]),
                                     np.array([-200.0, 0.0, -300.0]), now)
        cmd._next_tick = now            # force a tick
        orders = cmd.tick(now, 1.0)
        emcon = [o for o in orders if o["type"] in ("ship_silent", "ship_emit")]
        sil = [o["ship_id"] for o in emcon if o["type"] == "ship_silent"]
        emt = [o["ship_id"] for o in emcon if o["type"] == "ship_emit"]
        print(f"  {label:38s} -> silent={sil}  emit={emt}")
        results[label] = (sil, emt)

    run_case("no drone, no missile (quiet)", False, False)
    run_case("DRONE only (recon threat)", True, False)
    run_case("MISSILE only (inbound)", False, True)
    run_case("DRONE + MISSILE (self-defense wins)", True, True)
    return results


# ---------------------------------------------------------------------------
# C. Integrated world: drone near a destroyer
# ---------------------------------------------------------------------------
def probe_integrated(world):
    section("C. INTEGRATED WORLD: drone parked over a destroyer, 600 s")
    # Pick the destroyer nearest the fleet anchor and park the drone right on
    # top of it so the enemy picture forms a drone track in that ship's sector.
    dest = next(s for s in world.ships if not isinstance(s, Carrier))
    print(f"  Target ship: {dest.ship_id} at "
          f"({dest.pos[0]:.0f}, {dest.pos[2]:.0f})")

    drone = world.drone
    if drone is None:
        print("  !! no drone present; cannot run integrated drone test")
        return None

    # The real CombatWorld.step() runs the drone autopilot (_step_drones) which
    # flies the drone home toward the base every step, overriding any pin we set
    # BEFORE step(). To exercise the EMCON path with a sustained drone track in
    # the ship's sector we disable the drone autopilot and instead re-pin the
    # drone position at the start of each step (the rest of step() -- commander
    # feed, tick, order execution -- runs unmodified, real code).
    def _pinned_drone_step(dt, _w=world, _d=dest):
        if _w.drone is not None and _w.drone.alive:
            _w.drone.pos[0] = _d.pos[0]
            _w.drone.pos[2] = _d.pos[2]
            _w.drone.pos[1] = 18_000.0
    world._step_drones = _pinned_drone_step  # type: ignore[assignment]

    dt = 1.0
    n_steps = 600

    # Per-ship flip log: first time each enemy radar goes silent / re-emits.
    log = {s.ship_id: {"first_silent": None, "first_reemit": None,
                       "silent_ticks": 0, "is_carrier": isinstance(s, Carrier)}
           for s in world.ships}
    awacs_emit_ticks = 0
    awacs_total = 0
    drone_tracked_ticks = 0

    prev = {s.ship_id: emit_state(s.radar) for s in world.ships}

    for i in range(n_steps):
        t = world.sim_time
        world.step(dt)   # patched _step_drones re-pins the drone over the ship
        drone = world.drone

        # Did the commander picture form a drone track this step?
        if world.commander.picture.live_drone_tracks(world.sim_time):
            drone_tracked_ticks += 1

        for s in world.ships:
            cur = emit_state(s.radar)
            if not cur:
                log[s.ship_id]["silent_ticks"] += 1
            if prev[s.ship_id] and not cur and log[s.ship_id]["first_silent"] is None:
                log[s.ship_id]["first_silent"] = t
            if (not prev[s.ship_id]) and cur and \
                    log[s.ship_id]["first_silent"] is not None and \
                    log[s.ship_id]["first_reemit"] is None:
                log[s.ship_id]["first_reemit"] = t
            prev[s.ship_id] = cur

        awacs_total += 1
        if emit_state(world.awacs.radar):
            awacs_emit_ticks += 1
        if drone is None:
            # drone got shot down; stop pinning
            pass

    print(f"\n  drone track held by enemy picture: "
          f"{drone_tracked_ticks}/{n_steps} steps")
    print(f"\n  Per-ship EMCON behaviour over {n_steps} s:")
    any_silent = False
    for sid, d in log.items():
        tag = "CARRIER" if d["is_carrier"] else "destroyer"
        if d["silent_ticks"] > 0:
            any_silent = True
        print(f"    {sid:14s} ({tag:9s}) silent_ticks={d['silent_ticks']:4d}"
              f"  first_silent={d['first_silent']}"
              f"  first_reemit={d['first_reemit']}")

    print(f"\n  AWACS emitting: {awacs_emit_ticks}/{awacs_total} steps "
          f"(silent {awacs_total - awacs_emit_ticks} steps)")
    print(f"\n  -> Any DESTROYER ever went silent? "
          f"{any(d['silent_ticks'] > 0 and not d['is_carrier'] for d in log.values())}")
    return log, awacs_emit_ticks, awacs_total, drone_tracked_ticks


# ---------------------------------------------------------------------------
# C2. Drone FAR away (out of SM-2 engage window) -> clean silence test
# ---------------------------------------------------------------------------
def probe_integrated_far(world):
    section("C2. INTEGRATED: drone tracked but FAR from ship (out of engage gate)")
    from sim.enemy_defense import DRONE_ENGAGE_RANGE_M
    print(f"  DRONE_ENGAGE_RANGE_M = {DRONE_ENGAGE_RANGE_M:.0f} m "
          f"(SM-2 drone-engage window; inside this a silent ship re-lights)")

    dest = next(s for s in world.ships if not isinstance(s, Carrier))
    drone = world.drone
    if drone is None:
        print("  !! no drone")
        return None

    # Place the drone so an enemy radar can still SEE it (within stealth-class
    # detect range of the AWACS / a ship) but it sits OUTSIDE the SM-2 engage
    # window of the chosen ship, so the silence gate should NOT veto silence.
    # Offset along +X from the ship by engage_range + 5 km.
    off = DRONE_ENGAGE_RANGE_M + 5_000.0
    dt = 1.0
    n_steps = 400

    def _pinned_far_step(dt, _w=world, _d=dest, _off=off):
        if _w.drone is not None and _w.drone.alive:
            _w.drone.pos[0] = _d.pos[0] + _off
            _w.drone.pos[2] = _d.pos[2]
            _w.drone.pos[1] = 18_000.0
    world._step_drones = _pinned_far_step  # type: ignore[assignment]

    log = {s.ship_id: {"silent_ticks": 0, "first_silent": None,
                       "is_carrier": isinstance(s, Carrier)}
           for s in world.ships}
    prev = {s.ship_id: emit_state(s.radar) for s in world.ships}
    tracked = 0
    in_gate = 0
    for i in range(n_steps):
        t = world.sim_time
        world.step(dt)
        if world.commander.picture.live_drone_tracks(world.sim_time):
            tracked += 1
        # is the (pinned) drone inside the engage gate of dest?
        d = float(np.hypot(off, 0.0))
        if d <= DRONE_ENGAGE_RANGE_M:
            in_gate += 1
        for s in world.ships:
            cur = emit_state(s.radar)
            if not cur:
                log[s.ship_id]["silent_ticks"] += 1
            if prev[s.ship_id] and not cur and log[s.ship_id]["first_silent"] is None:
                log[s.ship_id]["first_silent"] = t
            prev[s.ship_id] = cur

    print(f"  drone offset from ship = {off:.0f} m  "
          f"(in engage gate: {in_gate}/{n_steps} steps)")
    print(f"  drone track held: {tracked}/{n_steps} steps")
    for sid, d in log.items():
        tag = "CARRIER" if d["is_carrier"] else "destroyer"
        print(f"    {sid:14s} ({tag:9s}) silent_ticks={d['silent_ticks']:4d}"
              f"  first_silent={d['first_silent']}")
    return log, tracked, in_gate


def main():
    print(f"SEED = {SEED}")
    world = CombatWorld(CombatConfig(seed=SEED))
    probe_initial_states(world)
    probe_doctrine_isolated()
    probe_integrated(world)
    # fresh world for the far test (the near test may have shot the drone down)
    world2 = CombatWorld(CombatConfig(seed=SEED))
    probe_integrated_far(world2)
    print("\nDONE")


if __name__ == "__main__":
    main()
