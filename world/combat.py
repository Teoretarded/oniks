"""CombatWorld: the COMBAT-mode world (Phase 2 — enemy ships that fight back).

Keeps the terrain, the Bastion/Oniks battery and the S-300; spawns NONE of
the sandbox traffic (no ship lanes, no patrol aircraft, no enemy-coast
sites). The contact picture is radar-gated (sim/radar.py): the player's
ground radar station is the side's only set of eyes — the S-300 cannot
engage what the station does not see.

Phase 2 adds two Destroyers (sim/enemy_ships.py) loitering at sea off the
enemy coast. They live in ``self.ships``, so the player's gated
ContactBoard, the tactical-map targeting and the Oniks OBB damage ladder
all apply unchanged — and because their hulls sit 160+ km from the
player's mast-height radar, fog of war hides them until something flies
high enough to look over the horizon (while staying inside the lo-lo
Oniks fuel range, so both attack profiles can genuinely reach them). Their SM-2/CIWS defenses are stepped
by the EnemyDefenseController (sim/enemy_defense.py) right after the base
world step, so enemy interceptors join ``self.missiles`` and the effects
event stream like any other round. Later phases stack strikes, Pantsir,
base damage and the commander AI on this shell.

Pure numpy / GL-free (LOCKED test convention), like world.world.
"""

from __future__ import annotations

import numpy as np

from sim.contacts import ContactBoard
from sim.enemy_defense import EnemyDefenseController
from sim.enemy_ships import Destroyer
from sim.radar import Radar, RadarNetwork
from world.generation import BASE_POS, SEED, terrain_height_scalar
from world.world import WorldState

# Player ground radar station: home-coast shelf east of the base (the same
# raised cliff band that carries the S-300 pad; the on-land pin is LOCKED
# by tests/test_combat_world.py — nudge z south if generation ever changes).
RADAR_STATION_XZ = (40_000.0, -6_000.0)
RADAR_ANTENNA_M = 18.0          # radome center above the slab
PLAYER_RADAR_RANGES = {         # size class -> max detection range (m)
    "ship": 350_000.0, "fighter": 350_000.0,
    "missile": 120_000.0, "stealth": 35_000.0,
}

COMBAT_SITES = [
    {"id": "radar_player_00", "kind": "radar",
     "pos": RADAR_STATION_XZ, "name": "RADAR STN (FRIENDLY)"},
]

# Enemy destroyers: anchors verified open water (terrain < -74 m across an
# 18x18 km box around each anchor — re-run the sweep if generation ever
# changes). Placement contract (Phase 2 balance pass): both anchors sit
# 150-175 km from the base, INSIDE the lo-lo Oniks fuel range (~230 km
# flown — beyond it the spec's "lo-lo is king" profile could never reach
# them), yet still 160+ km from the player radar station, far past its
# ~50-75 km horizon against a hull at sea level: the player picture stays
# empty until something looks down over the curve (smoke_combat asserts it).
DESTROYER_SPAWNS = (
    {"ship_id": "destroyer_00", "anchor_xz": (-20_000.0, 150_000.0),
     "heading_deg": 120.0},
    {"ship_id": "destroyer_01", "anchor_xz": (20_000.0, 170_000.0),
     "heading_deg": 15.0},
)


class CombatWorld(WorldState):
    """WorldState variant: destroyers at sea, radar-gated contact picture."""

    def __init__(self, rng_seed: int = SEED):
        super().__init__(rng_seed)
        # The enemy side's fire control: CIWS randomness derives from the
        # world seed so a battle replays exactly (determinism contract).
        self.defense = EnemyDefenseController(
            [s for s in self.ships if isinstance(s, Destroyer)],
            rng=np.random.default_rng(rng_seed))

    def _spawn_ships(self):
        return [Destroyer(s["ship_id"], s["anchor_xz"],
                          heading_deg=s["heading_deg"])
                for s in DESTROYER_SPAWNS]

    def _spawn_aircraft(self):
        return []

    def _spawn_sites(self):
        return COMBAT_SITES

    def _build_contacts(self) -> ContactBoard:
        x, z = RADAR_STATION_XZ
        self.radar_station = Radar(
            "radar_player_00", (x, terrain_height_scalar(x, z), z),
            RADAR_ANTENNA_M, PLAYER_RADAR_RANGES)
        self.radar_net = RadarNetwork([self.radar_station])
        return ContactBoard((BASE_POS[0], BASE_POS[2]),
                            visible_fn=self.radar_net.visible)

    def step(self, dt: float) -> None:
        """Base step (ships, missiles, damage, contacts), then the enemy
        defenses: SM-2s launched here join ``self.missiles`` and are flown
        by the NEXT base step, exactly like a player launch this frame."""
        super().step(dt)
        self.defense.step(self, dt)
