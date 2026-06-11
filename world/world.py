"""WorldState: the live simulation world — ships, sites, missiles, contacts.

Pure numpy / GL-free (LOCKED test convention): imports only sim modules,
world.generation and the bastion model *constants* (engine.meshdata is
numpy-only). The render/effects side lives in game/sandbox.py, which drains
``WorldState.events`` each sim step:

    ("ship_hit", pos)         missile struck a ship hull (sim/damage.py)
    ("splash", pos)           missile hit the water surface (pos[1] == 0)
    ("ground_hit", pos)       missile hit terrain (pos[1] > 0)
    ("aircraft_down", pos)    falling aircraft crashed on terrain (pos[1] > 0)
    ("aircraft_splash", pos)  falling aircraft hit the sea (pos[1] == 0)

All positions float64, SI units, axes per LOCKED CONVENTIONS.
"""

from __future__ import annotations

import numpy as np

from models import bastion
from sim.aircraft import AC_FALLING, AC_GONE, Aircraft
from sim.arsenal import BASTION, ONIKS
from sim.contacts import ContactBoard
from sim.damage import apply_missile_hits
from sim.missile import PH_BOOST, PH_EJECT, Missile
from sim.ships import Ship
from world.generation import (AIRCRAFT_SPAWNS, BASE_POS, LANES, SEED,
                              SHIP_SPAWNS, SITES, terrain_height_scalar)

# --- Launcher tuning ----------------------------------------------------------

LAUNCH_ELEV_DEG = 88.0      # raised-canister elevation (matches the TEL model)

# Mouth of the raised starboard canister relative to the TEL origin (= ground
# center at BASE_POS): the canister pivots about +X at (CAN_X, PIVOT_Y,
# PIVOT_Z) and its mouth sits CAN_LEN - PIVOT_BACK along the elevated axis.
_MOUTH_RUN = bastion.CAN_LEN - bastion.PIVOT_BACK
_ELEV = np.radians(LAUNCH_ELEV_DEG)
CANISTER_MOUTH_OFFSET = np.array([
    bastion.CAN_X,
    bastion.PIVOT_Y + _MOUTH_RUN * np.sin(_ELEV),
    bastion.PIVOT_Z + _MOUTH_RUN * np.cos(_ELEV),
])


def launch_realtime_lock(missiles) -> bool:
    """True while any live missile is in EJECT/BOOST: time accel is forced to
    1x so the launch always plays real-time (requested rate auto-restores once
    every missile reaches CLIMB/CRUISE — the caller re-evaluates each frame)."""
    return any(m.alive and m.phase in (PH_EJECT, PH_BOOST) for m in missiles)


class WorldState:
    """Owns every simulated entity and steps them at the fixed physics rate."""

    def __init__(self, rng_seed: int = SEED):
        self.rng = np.random.default_rng(rng_seed)
        self.ships = [self._spawn_ship(i, spawn)
                      for i, spawn in enumerate(SHIP_SPAWNS)]
        self.aircraft = [Aircraft(s["aircraft_id"], s["aircraft_type"],
                                  s["anchor_a"], s["anchor_b"])
                         for s in AIRCRAFT_SPAWNS]
        self.sites = SITES
        self.missiles: list[Missile] = []
        self.contacts = ContactBoard((BASE_POS[0], BASE_POS[2]))
        self.sim_time = 0.0
        self.events: list[tuple[str, np.ndarray]] = []
        self.reload_left = 0.0          # s until the launcher is ARMED again

    @staticmethod
    def _spawn_ship(i: int, spawn: dict) -> Ship:
        ship = Ship(f"{spawn['ship_type']}_{i:02d}", spawn["ship_type"],
                    LANES[spawn["lane_index"]], spawn["lane_t0"])
        ship.speed = float(spawn["speed"])     # per-spawn speed override
        return ship

    @property
    def launcher_armed(self) -> bool:
        return self.reload_left <= 0.0

    def terrain_height_at(self, x: float, z: float) -> float:
        """Scalar heightfield query (generation's bit-identical fast path)."""
        return terrain_height_scalar(x, z)

    # ------------------------------------------------------------------ step

    def step(self, dt: float) -> None:
        """Advance ships, aircraft, missiles, damage and the contact board by
        ``dt``; emit effects events and prune dead missiles."""
        self.sim_time += dt
        if self.reload_left > 0.0:
            self.reload_left = max(0.0, self.reload_left - dt)
        for ship in self.ships:
            ship.update(dt)
        for ac in self.aircraft:
            was_falling = ac.state == AC_FALLING
            ac.update(dt)
            if was_falling and ac.state == AC_GONE:   # impact ends the spiral
                kind = ("aircraft_down" if ac.impact_pos[1] > 1e-6
                        else "aircraft_splash")
                self.events.append((kind, ac.impact_pos.copy()))
        flying = [m for m in self.missiles if m.alive]
        for m in flying:
            m.update(dt, self)
        # Missiles that died inside update() hit the surface; ship hits are
        # applied next (disjoint sets — apply_missile_hits skips dead ones).
        surface_dead = [m for m in flying if not m.alive]
        apply_missile_hits(self.missiles, self.ships, self.events)
        for m in surface_dead:
            kind = "ground_hit" if m.impact_pos[1] > 1e-6 else "splash"
            self.events.append((kind, m.impact_pos.copy()))
        if any(not m.alive for m in self.missiles):
            self.missiles = [m for m in self.missiles if m.alive]
        self.contacts.update(self.ships, dt, self.sim_time)
        self.contacts.update(self.aircraft, dt, self.sim_time)

    def drain_events(self) -> list:
        """Return and clear the pending effects events."""
        events, self.events = self.events, []
        return events

    # ---------------------------------------------------------------- launch

    def launch(self, profile: str, target_point, waypoints=()):
        """Fire an Oniks from the base TEL at ``target_point`` (float64 (3,),
        sea level) via optional (x, z) ``waypoints``. Returns the Missile, or
        None while the launcher is reloading."""
        if not self.launcher_armed:
            return None
        base = np.array(BASE_POS, dtype=np.float64)
        pos = base + CANISTER_MOUTH_OFFSET
        tp = np.asarray(target_point, dtype=np.float64)
        fx, fz = waypoints[0] if len(waypoints) else (tp[0], tp[2])
        heading = float(np.arctan2(fx - pos[0], fz - pos[2]))
        m = Missile(ONIKS, pos, heading, profile, tp, waypoints=waypoints)
        self.missiles.append(m)
        self.reload_left = BASTION.reload_s
        return m
