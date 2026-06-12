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

Phase 4 — the recon drone (spec §4.3):

  * One ReconDrone (sim/recon.py) lives in ``self.drone`` — NOT in
    ``self.aircraft``: the aircraft list feeds contact pictures (the
    player's today, the ENEMY's in Phase 5), and the drone is friendly
    telemetry on the player side, never a contact.
  * ELINT: every step (on a cadence) the drone passively listens to every
    enemy radar — the emitter list is rebuilt from the ships' radars each
    pass, so future emitters (AWACS, ground radars) join by construction.
    An ACTIONABLE triangulated fix (quality < 5 km, heard recently)
    injects/refreshes a track for the matching SHIP in the player picture
    (emitter_id -> ship via the '{ship_id}_spy1' radar mount), with the
    estimate error mapped onto track AGE so the map draws it as a fading
    uncertain contact (mapping documented at ELINT_AGE_MAX_S below).
    A silenced emitter stops refreshing: the track coasts and drops like
    any lost track (intel aging).
  * SAR: the ContactBoard's visibility gate is extended — a SURFACE
    target is 'seen' when the radar net sees it OR the live drone's SAR
    strip covers it, so a silent hull overflown by the drone forms a
    track through the board's normal sustained-detection flow.
  * RWR: SPIKE when any enemy radar holds the drone, LOCK when an SM-2 is
    inbound on it (the destroyers engage a detected drone —
    sim/enemy_defense.py drone channel).
  * Respawn: a shot-down drone starts DRONE_RESPAWN_S; the falling
    airframe keeps spiralling in ``self.drone_wrecks`` (crash events fire
    when it hits) and the replacement spawns at the base with a CLEARED
    route when the timer runs out.

Later phases stack the air war, Pantsir and the commander AI on this
shell.

Pure numpy / GL-free (LOCKED test convention), like world.world.
"""

from __future__ import annotations

import numpy as np

from sim.bases import Structure, apply_missile_hits_structures
from sim.contacts import ContactBoard, TRACK_DROP_S
from sim.enemy_defense import EnemyDefenseController
from sim.enemy_ships import Destroyer
from sim.enemy_strikes import EnemyStrikeController
from sim.radar import Radar, RadarNetwork
from sim.recon import (DRONE_GONE, ELINT_FIX_ACTIONABLE_M, ElintReceiver,
                       ReconDrone, RwrReceiver, SarSensor)
from sim.sam import SamMissile
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

# --- Phase 4: recon drone ------------------------------------------------------

DRONE_COUNT = 1             # drones fielded (spec 4.3 default; the Phase-7
#                             armory/setup screen exposes this — the wiring
#                             below is single-drone, multi-drone lands with
#                             the setup screen)
DRONE_RESPAWN_S = 300.0     # s from shot-down to the replacement spawning
#                             at the base ("a replacement arrives after a
#                             long timer", spec 4.3; armory-configurable in
#                             Phase 7)

# Sensor cadences: the ELINT terrain-LOS ray (up to ~225 heightfield
# samples per emitter at the 450 km cap) and the lstsq triangulation are
# far too heavy for 120 Hz — both run on cadences, like every other sensor
# in the codebase (ContactBoard VIS_CHECK_PERIOD, enemy_defense
# VIS_CHECK_PERIOD).
ELINT_LISTEN_PERIOD_S = 0.5   # s between passive listening passes
ELINT_FIX_PERIOD_S = 1.0      # s between triangulation + track-injection
RWR_PERIOD_S = 0.25           # s between RWR threat refreshes (matches the
#                               destroyers' own fire-control cadence)
ELINT_FRESH_S = 5.0           # s since last heard for a fix to count as
#                               LIVE intel: a silenced emitter stops
#                               refreshing the picture within seconds and
#                               its track ages out (intel aging)

# ELINT error -> track age mapping: the board/map have ONE staleness axis
# (track age: alpha fade on the map, TRACK_DROP_S drop) so the fix error
# is expressed on it. A freshly-ACTIONABLE 5 km fix injects as an almost-
# stale track (ELINT_AGE_MAX_S, just under the 90 s drop so it lives), a
# razor 500 m fix as a ~8 s fresh one — the map contact visibly sharpens
# as the geometry improves, and if injection stops the track is already
# deep into its coast-out.
ELINT_AGE_MAX_S = TRACK_DROP_S - 10.0   # 80 s: error == actionable bound
#                                         -> nearly-dropped track


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

        # ---- Phase 4: the recon drone + its sensor suite ----
        # Sensors are SIDE-level intel and persist across respawns (bearing
        # pairs already collected keep triangulating); the drone is the
        # disposable platform. All sensor randomness comes from one child
        # generator off the world seed (SeedSequence [seed, 4] — phase tag
        # — so it can never collide with the defense controller's stream).
        self._recon_rng = np.random.default_rng([rng_seed, 4])
        recon_rng = self._recon_rng
        self.drone = self._spawn_drone(recon_rng)
        self.drone_wrecks: list[ReconDrone] = []   # falling airframes
        self.elint = ElintReceiver(rng=recon_rng)
        self.sar = SarSensor()
        self.rwr = RwrReceiver(drone_id=self.drone.aircraft_id)
        self._drone_respawn_left = 0.0
        self._elint_next_t = 0.0
        self._fix_next_t = 0.0
        self._rwr_next_t = 0.0

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
                            visible_fn=self._player_visible)

    def _player_visible(self, pos, size_class: str) -> bool:
        """The player picture's visibility gate: the radar net, OR (Phase
        4) the live drone's SAR strip for SURFACE targets — every surface
        entity rates 'ship' today, and SAR never images air targets, so a
        silent hull overflown by the drone enters the picture through the
        board's normal sustained-detection flow. Guarded with getattr:
        the board is built in super().__init__ before the drone exists."""
        if self.radar_net.visible(pos, size_class):
            return True
        drone = getattr(self, "drone", None)
        return (size_class == "ship" and drone is not None
                and drone.alive and self.sar.detects(drone.pos, pos))

    # ---------------------------------------------------------------- phase 4

    def _spawn_drone(self, rng) -> ReconDrone:
        """A fresh drone at the base: cruise altitude, empty route (it
        loiters over the base until tasked). DRONE_COUNT is 1 until the
        Phase-7 setup screen; the id stays 'drone_00' so the side-level
        RWR filter survives respawns."""
        return ReconDrone(aircraft_id="drone_00",
                          spawn_xz=(BASE_POS[0], BASE_POS[2]), rng=rng)

    @property
    def drone_respawn_left(self) -> float:
        """s until the replacement drone arrives (0 while one is up)."""
        return self._drone_respawn_left

    def _step_drones(self, dt: float) -> None:
        """Fly the active drone and the falling wrecks; start the respawn
        timer when the active one is shot down; spawn the replacement at
        the base (route cleared by construction) when it runs out."""
        # Wrecks first, so a drone killed THIS step is not double-stepped.
        for wreck in self.drone_wrecks:
            wreck.update(dt)
            if wreck.state == DRONE_GONE and wreck.impact_pos is not None:
                kind = ("aircraft_down" if wreck.impact_pos[1] > 1e-6
                        else "aircraft_splash")
                self.events.append((kind, wreck.impact_pos.copy()))
        self.drone_wrecks = [w for w in self.drone_wrecks
                             if w.state != DRONE_GONE]
        drone = self.drone
        if drone is not None:
            drone.update(dt)
            if not drone.alive:             # SM-2 fuse called kill()
                self.drone_wrecks.append(drone)
                self.drone = None
                self._drone_respawn_left = DRONE_RESPAWN_S
        elif self._drone_respawn_left > 0.0:
            self._drone_respawn_left = max(
                0.0, self._drone_respawn_left - dt)
            if self._drone_respawn_left <= 0.0:
                self.drone = self._spawn_drone(self._recon_rng)

    def _emitters(self):
        """(emitter_id, radar) per enemy radar mount, rebuilt every pass
        from the live ship list so future emitter platforms (AWACS,
        ground radars — Phase 5) join the ELINT picture by construction."""
        return [(s.radar.radar_id, s.radar) for s in self.ships]

    def _step_recon_sensors(self) -> None:
        """ELINT / RWR / fix-injection on their cadences (see the period
        constants above) — only while a drone is up: a dead platform
        hears nothing, and the intel it already produced ages out."""
        drone = self.drone
        if drone is None or not drone.alive:
            return
        now = self.sim_time
        if now >= self._elint_next_t:
            self._elint_next_t = now + ELINT_LISTEN_PERIOD_S
            self.elint.update(drone.pos, self._emitters(), sim_time=now)
        if now >= self._rwr_next_t:
            self._rwr_next_t = now + RWR_PERIOD_S
            self.rwr.update(drone.pos, [s.radar for s in self.ships],
                            [m for m in self.missiles
                             if m.alive and isinstance(m, SamMissile)])
        if now >= self._fix_next_t:
            self._fix_next_t = now + ELINT_FIX_PERIOD_S
            self._inject_elint_tracks(now)

    def _inject_elint_tracks(self, now: float) -> None:
        """Actionable ELINT fixes -> player-picture tracks.

        The emitter is a ship mount ('{ship_id}_spy1'), so the fix maps
        onto the SHIP's contact id — the same track the radar net or SAR
        would feed, and a valid Oniks target. The estimate error rides
        the track's AGE (ELINT_AGE_MAX_S mapping above): the map draws a
        faded, uncertain contact that sharpens as the geometry improves.
        Gates: the fix must be actionable, the emitter heard within
        ELINT_FRESH_S (silence = the track coasts out and drops — intel
        aging), and a FRESHER existing fix (younger age, e.g. live SAR
        imaging) is never overwritten with a worse one."""
        by_emitter = {s.radar.radar_id: s for s in self.ships}
        for eid in self.elint.heard_emitters():
            ship = by_emitter.get(eid)
            if ship is None or not ship.alive:
                continue
            heard = self.elint.last_heard(eid)
            if heard is None or now - heard > ELINT_FRESH_S:
                continue
            quality = self.elint.fix_quality(eid)
            if quality >= ELINT_FIX_ACTIONABLE_M:
                continue
            est = self.elint.est_pos(eid)
            if est is None:
                continue
            age = ELINT_AGE_MAX_S * quality / ELINT_FIX_ACTIONABLE_M
            track = self.contacts.tracks.get(ship.ship_id)
            if track is not None and track["age"] < age:
                continue
            self.contacts.tracks[ship.ship_id] = dict(
                pos=est.copy(), vel=np.zeros(3), age=age,
                t_next=now + ELINT_FIX_PERIOD_S, is_air=False)

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
        """Base step (ships, missiles, damage, contacts), then the drone
        flight, then the enemy defenses and strikes: rounds launched here
        join ``self.missiles`` and are flown by the NEXT base step,
        exactly like a player launch this frame. Finally the hostile
        rounds are swept against the base structures, the strike rounds
        are fed to the player picture and the recon sensors run."""
        super().step(dt)
        self._step_drones(dt)
        self.defense.step(self, dt)
        self.strikes.step(self, dt)
        apply_missile_hits_structures(
            [m for m in self.missiles if getattr(m, "is_hostile", False)],
            self.structures, self.events)
        self._update_strike_contacts(dt)
        self._step_recon_sensors()
