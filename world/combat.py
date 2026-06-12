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
event stream like any other round.

Phase 3 — the enemy strikes back:

  * The player base is destructible: ``self.structures`` (sim/bases.py)
    holds the Bastion TEL, the S-300 TEL and the radar station. Each step
    every HOSTILE missile (``is_hostile`` flag, sim/strike.py — a player
    Oniks overflying its own base can never demolish it) is swept against
    the structure OBBs; hits emit ("base_hit", pos) and, on a kill,
    ("base_destroyed", pos) into the effects event stream.
  * Killing the radar-station STRUCTURE clears the Radar's ``alive`` via
    its on_destroyed callback: coverage vanishes instantly, the contact
    picture coasts and drops (sim/contacts.py handles that already).
  * The destroyers run an EnemyStrikeController (sim/enemy_strikes.py):
    ESM localization of the emitting radar station -> Tomahawk salvos.
    Radar silence (Radar.emitting, toggled from the HUD layer) is the
    player's counter: silent radars can't be located — and can't see.
  * Inbound hostile strike missiles feed the gated ContactBoard as air
    entities (radar_size "missile"), so the player's picture shows them
    once his radar physically can — a 50 m sea-skimming Tomahawk stays
    under the horizon until it is close, exactly per spec section 3.
  * ``defeated`` flips when every Bastion TEL structure is dead (spec 2.2
    lose condition); ``launcher_armed`` then locks so ``launch`` returns
    None. In Phase 3 the enemy cannot actually find the TELs (they don't
    emit — module docstring of sim/enemy_strikes.py); the property is
    wired now so the Phase-4 commander AI plugs straight in.

Later phases stack the air war, Pantsir and the commander AI on this
shell.

Pure numpy / GL-free (LOCKED test convention), like world.world.
"""

from __future__ import annotations

import numpy as np

from sim.bases import Structure, apply_missile_hits_structures
from sim.contacts import ContactBoard
from sim.enemy_defense import EnemyDefenseController
from sim.enemy_ships import Destroyer
from sim.enemy_strikes import EnemyStrikeController
from sim.radar import Radar, RadarNetwork
from world.generation import BASE_POS, SEED, terrain_height_scalar
from world.world import SAM_TEL_POS, WorldState

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
        destroyers = [s for s in self.ships if isinstance(s, Destroyer)]
        # The enemy side's fire control: CIWS randomness derives from the
        # world seed so a battle replays exactly (determinism contract).
        self.defense = EnemyDefenseController(
            destroyers, rng=np.random.default_rng(rng_seed))
        # Phase 3: ESM localization -> Tomahawk salvos at the radar station.
        self.strikes = EnemyStrikeController(destroyers, self.radar_station)
        # Destructible player base (sim/bases.py). The radar-station
        # structure's death clears the Radar itself: coverage vanishes,
        # the picture coasts and drops (already automatic downstream).
        rx, rz = RADAR_STATION_XZ
        self.structures = [
            Structure("bastion_tel_00", "bastion_tel",
                      np.array(BASE_POS, dtype=np.float64)),
            Structure("s300_tel_00", "s300_tel", SAM_TEL_POS.copy()),
            Structure("radar_station_00", "radar_station",
                      np.array([rx, terrain_height_scalar(rx, rz), rz]),
                      on_destroyed=lambda _s: setattr(
                          self.radar_station, "alive", False)),
        ]
        # Hostile strike rounds currently fed to the contact board, keyed
        # by track id. Dead rounds stay in the feed until the board drops
        # their track (the same one-refresh linger sunk ships get) so no
        # ghost contact can coast forever after a kill.
        self._strike_board: dict[str, object] = {}

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

    # ---------------------------------------------------------------- phase 3

    @property
    def defeated(self) -> bool:
        """Spec 2.2 lose condition: every Bastion TEL structure is dead
        (no Oniks = no offense). The sim keeps running so the player can
        watch; full end-screens come in Phase 7."""
        return all(not s.alive for s in self.structures
                   if s.kind == "bastion_tel")

    @property
    def launcher_armed(self) -> bool:
        """Reload gate AND the TEL structure still standing: ``launch``
        returns None forever once the Bastion is rubble."""
        return WorldState.launcher_armed.fget(self) and not self.defeated

    def _update_strike_contacts(self, dt: float) -> None:
        """Feed live hostile strike missiles to the gated board as air
        entities (sim/strike.py carries is_air/radar_size/aircraft_id).
        Rounds that died this step stay in the feed until the board drops
        their track — mirroring how sunk ships linger in self.ships."""
        for m in self.missiles:
            if m.alive and getattr(m, "is_hostile", False):
                self._strike_board[m.aircraft_id] = m
        if not self._strike_board:
            return
        self.contacts.update(list(self._strike_board.values()),
                             dt, self.sim_time)
        self._strike_board = {
            cid: m for cid, m in self._strike_board.items()
            if m.alive or cid in self.contacts.tracks}

    # ------------------------------------------------------------------ step

    def step(self, dt: float) -> None:
        """Base step (ships, missiles, damage, contacts), then the enemy
        defenses and strikes: rounds launched here join ``self.missiles``
        and are flown by the NEXT base step, exactly like a player launch
        this frame. Finally the hostile rounds are swept against the base
        structures and fed to the player picture."""
        super().step(dt)
        self.defense.step(self, dt)
        self.strikes.step(self, dt)
        apply_missile_hits_structures(
            [m for m in self.missiles if getattr(m, "is_hostile", False)],
            self.structures, self.events)
        self._update_strike_contacts(dt)
