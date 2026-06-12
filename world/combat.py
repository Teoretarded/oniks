"""CombatWorld: the COMBAT-mode world (Phase 1 — fog-of-war shell).

Keeps the terrain, the Bastion/Oniks battery and the S-300; spawns NONE of
the sandbox traffic (no ship lanes, no patrol aircraft, no enemy-coast
sites). The contact picture is radar-gated (sim/radar.py): the player's
ground radar station is the side's only set of eyes — the S-300 cannot
engage what the station does not see. Later phases stack enemies, Pantsir,
base damage and the commander AI on this shell.

Pure numpy / GL-free (LOCKED test convention), like world.world.
"""

from __future__ import annotations

from sim.contacts import ContactBoard
from sim.radar import Radar, RadarNetwork
from world.generation import BASE_POS, terrain_height_scalar
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


class CombatWorld(WorldState):
    """WorldState variant: empty traffic, radar-gated contact picture."""

    def _spawn_ships(self):
        return []

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
