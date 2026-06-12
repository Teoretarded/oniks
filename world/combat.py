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

Phase 5a — the air war scaffolding (spec §5.1/5.3/5.4/5.5; weapons
employment, the commander AI and AIM-9X/JASSM/HARM delivery are 5b):

  * Exactly ONE Carrier (sim/enemy_air.py) joins ``self.ships`` at a FIXED
    deep anchor inside the spawn-zone carrier band — it is Oniks-targetable,
    walks the ship damage ladder and feeds the gated contact picture like
    any hull (full seeded placement via world/spawn_zones.sample_fleet is
    Phase 7).  Its radar exists but is silent (5a doctrine).
  * The enemy AIRFIELD is a destructible Structure on the enemy continent
    in ``self.enemy_structures`` — swept against PLAYER cruise missiles
    each step (mirror of the hostile-vs-player-base pass; is_hostile keeps
    the two sides' rounds out of each other's sweep).  Fog of war for
    fixed installations: the 3D world always shows the real geometry, but
    the tactical MAP only gains the site marker once a player sensor has
    actually imaged it (``airfield_known``, latched — installations don't
    move, so knowledge never ages out like a moving track).
  * Fighters (2 at the airfield + 2 on the carrier) and one AWACS live in
    ``self.enemy_air`` — NOT ``self.aircraft``: that list is the legacy
    sandbox traffic that feeds the LEGACY all-seeing board and several
    sandbox-only code paths; enemy air is stepped and fed to the gated
    player picture explicitly here.  A standing-CAP scheduler keeps
    ~CAP_TARGET_AIRBORNE fighters rotating (launch -> racetrack over the
    fleet -> bingo RTB to the nearest surviving base -> rearm -> next);
    the 5b commander replaces it.
  * Enemy picture symmetry: the AWACS radar is a datalink CUE for every
    destroyer's fire control (sim/enemy_defense.py cue_radars_fn) — a
    ship may form and engage a missile/drone track the AWACS holds before
    its own SPY-1 sees it; terminal SARH illumination stays own-ship.
  * The drone's ELINT/RWR emitter lists now include the AWACS (always
    emitting in 5a) and airborne fighters' nose radars — passively
    locatable by construction.

Phase 5b — the commander runs the war (spec §6):

  * One EnemyCommander (sim/commander.py) ticks at 1 Hz on a SENSOR-ONLY
    EnemyPicture fed here on a 0.25 s cadence (the defense controllers'
    VIS_CHECK_PERIOD): ESM accrual on the player radar while any enemy
    platform survives to hear it, player missile tracks from whichever
    SPY-1/AWACS/nose radar physically detects them (first-seen metadata
    recorded for the launch back-plot), drone tracks from the same
    radars.  Fog of war is symmetric — no commander decision reads truth.
  * Orders are executed here: HARM/JASSM strike packages launch PARKED
    fighters (silent ingress, release ranges in sim/enemy_air.py), the
    HARMs home on the actual radar EMITTER (silence degrades them — the
    sim/strike.py physics), Tomahawk salvos draw the destroyers'
    magazines at back-plotted launch clusters, the AWACS flees inbound
    missile tracks, ships silence/raise their radars per the threat
    picture, and fighters get vectored at drone tracks (nose-radar
    reacquire -> AIM-9X, all passive on the drone's RWR).
  * Strike aim refinement: JASSM/TLAM carry terminal scene-matching
    seekers (IIR/DSMAC class) — a round whose BELIEVED aim point falls
    within SEEKER_BASKET_M of a player structure acquires it terminally;
    a back-plot error beyond the basket hits dirt.  Kill probability
    emerges from back-plot accuracy vs the basket, never a roll.
  * The 5a standing-CAP scheduler is REPLACED by commander-managed CAP:
    same rotation rules, but only while no strike package is active (the
    parked pool belongs to the mission generator).
  * ``victorious`` (spec 2.2 win): every enemy ship dead AND the airfield
    dead.  Phase 5 fields no enemy ground radars — they join the
    condition with the Phase-7 setup-screen counts.

Pure numpy / GL-free (LOCKED test convention), like world.world.
"""

from __future__ import annotations

import numpy as np

from sim.arsenal import TOMAHAWK
from sim.bases import Structure, apply_missile_hits_structures
from sim.commander import EnemyCommander
from sim.contacts import ContactBoard, TRACK_DROP_S
from sim.enemy_air import (FS_ON_STATION, FS_PARKED, FS_TAKEOFF, FS_TRANSIT,
                           LOADOUT_CAP, LOADOUT_SEAD, LOADOUT_STRIKE,
                           AirBase, Awacs, Carrier, Fighter)
from sim.enemy_defense import (DRONE_ENGAGE_RANGE_M, VLS_DECK_M,
                               EnemyDefenseController)
from sim.enemy_ships import Destroyer
from sim.enemy_strikes import SALVO_PERIOD_S, SALVO_SIZE, EnemyStrikeController
from sim.missile import Missile
from sim.radar import Radar, RadarNetwork
from sim.recon import (DRONE_GONE, DRONE_SPEED_MPS, ELINT_FIX_ACTIONABLE_M,
                       ElintReceiver, ReconDrone, RwrReceiver, SarSensor)
from sim.sam import SamMissile
from sim.strike import StrikeMissile
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

# --- Phase 5a: enemy air order of battle ----------------------------------------

# Enemy airfield: probed dry land on the enemy continent near the requested
# (60 km, 520 km) area.  (60_000, 516_000) measured 138.8-142.9 m of terrain
# across the full 2.5 km runway footprint (x +-250 m, z +-1400 m) — the
# flattest on-land candidate of a 20-cell sweep (spread 4.1 m; neighbours
# ran 12-22 m).  LOCKED by tests/test_phase5a_e2e.py on-land pins — nudge
# if generation ever changes.
AIRFIELD_XZ = (60_000.0, 516_000.0)

# Airfield OBB, Structure dims order (length=X, beam=Z, height=Y): the
# models/airfield.py runway runs along +Z (2 500 m) with the taxiway,
# hangars and tower spread ~205 m across +X; the box pads both so a
# terminal-diving Oniks anywhere over the installation registers.  Height
# 50 m tops the 47 m tower mast.
AIRFIELD_DIMS = (450.0, 2_600.0, 50.0)

# Airfield HP: a dispersed 2.5 km installation — cratering the runway AND
# flattening the hangars takes several 250 kg-class warheads (spec §5.5
# "destroyable"; more than the 2-hit vehicle TELs, under the carrier's 6).
AIRFIELD_HP = 4

# The map marker shown once the installation has been imaged (same dict
# shape as COMBAT_SITES/world.generation SITES so the tactical map's site
# drawing consumes it unchanged).
AIRFIELD_SITE = {"id": "airfield_enemy_00", "kind": "airfield",
                 "pos": AIRFIELD_XZ, "name": "ENEMY AIRFIELD"}

# Carrier: FIXED anchor inside the spawn-zone carrier band (spec §5.1b;
# world/spawn_zones.py CARRIER_RANGE_MIN/MODE/MAX 240-330 km — 280 km IS
# the band mode).  (0, 280_000) verified open water: terrain -92.5 m at
# the anchor and spawn_zones.is_open_water (the 9 km clearance disc) True.
# Seeded placement via sample_fleet lands in Phase 7.
CARRIER_ANCHOR_XZ = (0.0, 280_000.0)
CARRIER_HEADING_DEG = 90.0      # east-west racetrack, beam-on to the player

# AWACS: racetrack rectangle around the requested (0, 420_000) deep area —
# 80 km legs at 9.1 km altitude, 405-435 km from the base: outside the
# player radar's 350 km 'fighter' range AND the S-300 envelope (it orbits
# deep and only a 5b 40N6 — or a fled orbit — changes that).
AWACS_ANCHOR_A_XZ = (-40_000.0, 405_000.0)
AWACS_ANCHOR_B_XZ = (40_000.0, 435_000.0)

# Standing CAP (commander-managed since 5b): the racetrack anchor sits
# over the destroyer screen (anchors at z 150/170 km) so the CAP orbits
# the fleet it protects.
FIGHTER_CAP_ANCHOR_XZ = (0.0, 160_000.0)
CAP_TARGET_AIRBORNE = 2     # fighters kept up (out of the 4 fielded)
CAP_SCHED_PERIOD_S = 5.0    # s between scheduler checks; also staggers
#                             launches (at most one fighter rolls per check)

# --- Phase 5b: the commander's integration cadences + strike physics ----------

CMD_FEED_PERIOD_S = 0.25    # s between enemy-picture sensor feeds — matches
#                             the defense controllers' VIS_CHECK_PERIOD (the
#                             terrain-LOS ray inside Radar.detects is the
#                             budget item; 120 Hz feeding would be ~30x the
#                             cost for zero doctrine value at a 1 Hz brain)
CMD_WEAPON_PERIOD_S = 1.0   # s between fighter release_weapons sweeps (the
#                             commander tick rate; release gates are ranges,
#                             so a 1 s quantization moves a release point by
#                             ~240 m at cruise — irrelevant at 100+ km)

# Terminal scene-matching seeker basket (JASSM IIR / Tomahawk Blk IV
# DSMAC-class): the round's INS flies to the BELIEVED coordinates; in the
# terminal scene the imaging/correlation seeker acquires a structure within
# this radius of the aim point (real DSMAC/IIR acquisition baskets are
# quoted around a kilometre of INS drift).  Static targets mean the
# acquisition decision can be evaluated at ORDER time without changing the
# outcome.  Fog honesty: the gate runs on the believed aim point — a
# back-plot error beyond the basket puts the round in the dirt, so strike
# effectiveness EMERGES from sensor geometry, never from a roll.
SEEKER_BASKET_M = 1_000.0

# Terminal aim height over the acquired structure: OBB mid-height (the
# sim/strike.py target_y doc — aiming at ground level under a target on
# the 150 m coastal shelf grounds the round short).
def _structure_aim_y(s: Structure) -> float:
    return float(s.pos[1]) + s.dims[2] * 0.5

AIRFIELD_FIGHTERS = 2       # parked at the airfield at spawn
CARRIER_FIGHTERS = 2        # parked on the carrier at spawn

INTEL_CHECK_PERIOD_S = 1.0  # s between fixed-installation intel checks
#                             (cheap: a range gate rejects the radar path
#                             instantly; SAR is a hypot)

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
        # The carrier (a Destroyer subclass) is covered too — zero SM-2/
        # CIWS ammo makes its unit inert in 5a, and the seam is already
        # right when 5b arms the escorts' picture.  cue_radars_fn is the
        # AWACS datalink (built below; the closure resolves lazily).
        self.defense = EnemyDefenseController(
            destroyers, rng=np.random.default_rng(rng_seed),
            cue_radars_fn=self._enemy_cue_radars)
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

        # ---- Phase 5a: enemy air order of battle ----
        ax, az = AIRFIELD_XZ
        self.airfield = Structure(
            "airfield_enemy_00", "airfield",
            np.array([ax, terrain_height_scalar(ax, az), az]),
            dims=AIRFIELD_DIMS, hp=AIRFIELD_HP)
        # Enemy fixed installations, swept against PLAYER cruise missiles
        # (the mirror of self.structures vs hostile rounds) in step().
        self.enemy_structures = [self.airfield]
        carrier = next(s for s in self.ships if isinstance(s, Carrier))
        self.carrier = carrier
        # Recovery sites in NEAREST-SURVIVING-base priority order is the
        # fighters' own logic; list order here only seeds the round-robin
        # launch rotation (airfield first).
        self.air_bases = [AirBase(self.airfield), AirBase(carrier)]
        self.enemy_air: list = []
        roster = ([self.air_bases[0]] * AIRFIELD_FIGHTERS
                  + [self.air_bases[1]] * CARRIER_FIGHTERS)
        for i, base in enumerate(roster):
            fighter = Fighter(f"fighter_{i:02d}", base,
                              FIGHTER_CAP_ANCHOR_XZ)
            base.parked.append(fighter)
            self.enemy_air.append(fighter)
        self.awacs = Awacs("awacs_00", AWACS_ANCHOR_A_XZ, AWACS_ANCHOR_B_XZ)
        self.enemy_air.append(self.awacs)
        self._cap_next_t = 0.0
        self._cap_base_idx = 0          # round-robin launch base pointer
        # Fog of war for fixed installations: latched once ANY player
        # sensor images the airfield (installations don't move — the
        # marker persists, unlike a moving track that ages out).
        self.airfield_known = False
        self._intel_next_t = 0.0

        # ---- Phase 5b: the enemy commander ----
        # Seeded with the world seed (determinism contract); the child
        # generator (SeedSequence [seed, 5] — phase tag, never colliding
        # with the defense [seed] or recon [seed, 4] streams) seeds the
        # HARM miss offsets per launch.
        self._fighter_list = [e for e in self.enemy_air
                              if isinstance(e, Fighter)]
        self.commander = EnemyCommander(
            self._fighter_list, self.awacs, destroyers, seed=rng_seed)
        self._cmd_rng = np.random.default_rng([rng_seed, 5])
        self._cmd_feed_next_t = 0.0
        self._cmd_weapon_next_t = 0.0
        # id(missile) -> first-seen sensor record for the back-plot feed.
        self._cmd_missile_intel: dict[int, dict] = {}
        # Integrator-side mission execution records (fighters + spawned
        # rounds per active commander mission; completion + BDA run here).
        self._cmd_missions: list[dict] = []

    def _spawn_ships(self):
        ships = [Destroyer(s["ship_id"], s["anchor_xz"],
                           heading_deg=s["heading_deg"])
                 for s in DESTROYER_SPAWNS]
        # Always exactly ONE carrier (spec §5.4) at the fixed deep anchor.
        ships.append(Carrier("carrier_00", CARRIER_ANCHOR_XZ,
                             heading_deg=CARRIER_HEADING_DEG))
        return ships

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
        from the live entity lists so emitter platforms join the ELINT
        picture by construction.  Phase 5a: ship mounts (the carrier's is
        silent — doctrine flag, never heard) plus every AIRBORNE enemy
        air radar — the AWACS emits whenever it flies (5a doctrine) and a
        fighter's nose radar searches only while the jet is up
        (``alive`` is the airborne flag: parked/rearming/dead airframes
        radiate nothing)."""
        ems = [(s.radar.radar_id, s.radar) for s in self.ships]
        ems.extend((e.radar.radar_id, e.radar)
                   for e in self.enemy_air if e.alive)
        return ems

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
            # Threat emitters = ship mounts + airborne enemy air radars
            # (same airborne gate as _emitters): a fighter nose radar
            # sweeping the drone SPIKEs the RWR like any other radar.
            radars = [s.radar for s in self.ships]
            radars.extend(e.radar for e in self.enemy_air if e.alive)
            self.rwr.update(drone.pos, radars,
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

    # ---------------------------------------------------------------- phase 5a

    def _enemy_cue_radars(self):
        """Datalink cueing sources beyond own-ship SPY-1 (spec section 3:
        "enemy ships rely on their own radar or AWACS cueing"): the live
        AWACS radar.  Resolved lazily — the defense controller is built
        before the AWACS in __init__ but only calls this from step()."""
        awacs = getattr(self, "awacs", None)
        if awacs is not None and awacs.alive:
            return [awacs.radar]
        return []

    def _step_enemy_air(self, dt: float) -> None:
        """Rearm queues, the standing-CAP scheduler, then every enemy
        airframe; crash events fire exactly when an impact lands (both
        Fighter and Awacs set impact_pos once, at the spiral's end —
        winchester egress reaches GONE without an impact, no event)."""
        for base in self.air_bases:
            base.update(dt)
        if self.sim_time >= self._cap_next_t:
            self._cap_next_t = self.sim_time + CAP_SCHED_PERIOD_S
            self._commander_cap()
        for e in self.enemy_air:
            had_impact = e.impact_pos is not None
            if isinstance(e, Fighter):
                e.update(dt, self.air_bases)
            else:
                e.update(dt)
            if not had_impact and e.impact_pos is not None:
                kind = ("aircraft_down" if e.impact_pos[1] > 1e-6
                        else "aircraft_splash")
                self.events.append((kind, e.impact_pos.copy()))

    def _commander_cap(self) -> None:
        """Commander-managed standing CAP (5b — replaces the 5a scheduler
        with the SAME rotation rules, gated on the mission picture): keep
        ~CAP_TARGET_AIRBORNE fighters up while NO strike package is
        active — the parked pool belongs to the mission generator, so a
        rearming SEAD jet is never re-tasked to CAP under an active
        package.  Outbound states count as airborne; an RTB/landing
        fighter frees its slot so the next one rolls.  At most ONE launch
        per check (natural stagger), drawn round-robin across the LIVE
        bases.  Fighters parked at a dead base never launch (a cratered
        runway flies no sorties — spec §5.5)."""
        if any(rec["kind"] in ("harm_package", "jassm_package")
               for rec in self._cmd_missions):
            return                      # strike packages own the flight line
        airborne = sum(1 for e in self.enemy_air
                       if isinstance(e, Fighter)
                       and e.state in (FS_TAKEOFF, FS_TRANSIT,
                                       FS_ON_STATION))
        if airborne >= CAP_TARGET_AIRBORNE:
            return
        n = len(self.air_bases)
        for k in range(n):
            base = self.air_bases[(self._cap_base_idx + k) % n]
            if not base.alive:
                continue
            for fighter in list(base.parked):
                if fighter.state == FS_PARKED:
                    fighter.assign_loadout(LOADOUT_CAP)
                    fighter.launch(FIGHTER_CAP_ANCHOR_XZ)
                    self._cap_base_idx = (self._cap_base_idx + k + 1) % n
                    return

    def _find_air_entity(self, aircraft_id):
        """world.world hook override: air contacts in COMBAT are enemy
        air (fighters/AWACS) or hostile strike rounds — the S-300 launch/
        retarget lookups and the sandbox camera find them here.  The
        legacy aircraft list stays empty in COMBAT."""
        ent = super()._find_air_entity(aircraft_id)
        if ent is not None:
            return ent
        return next((e for e in self.enemy_air
                     if e.aircraft_id == aircraft_id), None)

    @property
    def known_enemy_sites(self) -> list:
        """Enemy fixed installations the player side has actually IMAGED
        (fog of war for structures): the tactical map draws these as site
        markers; an unseen installation is simply absent from the map.
        The 3D scene is not gated — the geometry physically exists."""
        return [AIRFIELD_SITE] if self.airfield_known else []

    def _update_airfield_intel(self) -> None:
        """Latch ``airfield_known`` when any player sensor sees the
        airfield: the drone's SAR strip (the designed path — a surface
        'structure' is imaged exactly like a silent hull) or, for
        completeness, the radar net (in practice the 516 km pin sits far
        past the player radar's range, so SAR overflight is the game)."""
        if self.airfield_known or self.sim_time < self._intel_next_t:
            return
        self._intel_next_t = self.sim_time + INTEL_CHECK_PERIOD_S
        pos = self.airfield.pos
        drone = self.drone
        if (drone is not None and drone.alive
                and self.sar.detects(drone.pos, pos)):
            self.airfield_known = True
        elif self.radar_net.visible(pos, "ship"):
            self.airfield_known = True

    # ---------------------------------------------------------------- phase 5b

    def _enemy_sensor_radars(self) -> list:
        """The live enemy sensor set feeding the commander's picture:
        destroyer SPY-1s (the carrier's mount stays silent — doctrine),
        the AWACS, and every AIRBORNE fighter nose radar (FighterRadar
        applies its own emit + forward-cone gates inside detects)."""
        radars = [s.radar for s in self.ships
                  if s.alive and not isinstance(s, Carrier)]
        if self.awacs.alive:
            radars.append(self.awacs.radar)
        radars.extend(f.radar for f in self._fighter_list if f.alive)
        return radars

    def _step_commander(self, dt: float) -> None:
        """Feed the sensor-only picture (0.25 s cadence), tick the brain
        (1 Hz, internal gate), execute its orders, sweep the fighters'
        weapon-release checks (1 Hz) and close out finished missions."""
        now = self.sim_time
        if now >= self._cmd_feed_next_t:
            self._cmd_feed_next_t = now + CMD_FEED_PERIOD_S
            self._feed_enemy_picture(CMD_FEED_PERIOD_S, now)
        for order in self.commander.step(now, dt):
            self._execute_commander_order(order)
        if now >= self._cmd_weapon_next_t:
            self._cmd_weapon_next_t = now + CMD_WEAPON_PERIOD_S
            self._release_fighter_weapons()
        self._update_commander_missions(now)

    def _feed_enemy_picture(self, dt_s: float, now: float) -> None:
        """Sensor events -> EnemyPicture.  Every entry traces to a live
        enemy sensor: ESM accrual only while the player radar EMITS and
        an enemy platform survives to hear it (the enemy_strikes.py
        functional-ESM model — no range gate against a megawatt search
        set); missile/drone tracks only from a radar whose detects()
        physically passes (range class + horizon + terrain LOS)."""
        pic = self.commander.picture
        radar = self.radar_station
        heard = (radar.alive and radar.emitting
                 and (any(s.alive for s in self.ships)
                      or self.awacs.alive
                      or any(f.alive for f in self._fighter_list)))
        pic.update_emitter(radar.radar_id, radar.pos, heard, dt_s, now)
        if heard:
            # Re-illumination is EVIDENCE: a radar believed killed by a
            # HARM package that is heard again flips back to alive.
            pic.mark_emitter_alive(radar.radar_id)

        detectors = self._enemy_sensor_radars()

        # Player missiles -> track store + launch back-plot (first-seen
        # metadata recorded at the first physical detection).  Filter:
        # player rounds only — the Oniks (Missile) and the S-300/40N6
        # (SamMissile with no launch_platform; enemy SM-2s carry their
        # launching ship there, sim/enemy_defense.py).
        live_keys = set()
        for m in self.missiles:
            if not m.alive or getattr(m, "is_hostile", False):
                continue
            if not isinstance(m, (Missile, SamMissile)):
                continue
            if getattr(m, "launch_platform", None) is not None:
                continue
            key = id(m)
            live_keys.add(key)
            rec = self._cmd_missile_intel.get(key)
            if rec is None:
                det = next((r for r in detectors
                            if r.detects(m.pos, "missile")), None)
                if det is None:
                    continue                    # nobody sees it yet
                rec = dict(track_id=f"hostile_{key:x}", first_t=now,
                           first_pos=m.pos.copy(), first_vel=m.vel.copy(),
                           det_pos=np.asarray(det.pos,
                                              dtype=np.float64).copy())
                self._cmd_missile_intel[key] = rec
            elif not any(r.detects(m.pos, "missile") for r in detectors):
                continue                        # track coasts, no refresh
            self.commander.process_missile_track(
                rec["track_id"], m.pos, m.vel, now, rec["first_t"],
                rec["first_pos"], rec["first_vel"], rec["det_pos"])
        self._cmd_missile_intel = {
            k: v for k, v in self._cmd_missile_intel.items()
            if k in live_keys}

        # The drone -> a last-known-position track while any enemy radar
        # holds it at its 'stealth' class range.
        drone = self.drone
        if (drone is not None and drone.alive
                and any(r.detects(drone.pos, drone.radar_size)
                        for r in detectors)):
            pic.update_drone_track(
                drone.aircraft_id,
                np.array([float(drone.pos[0]), float(drone.pos[2])]), now)

        self._drone_sector_alert(now)

    def _drone_track_in_sector(self, ship, now: float) -> bool:
        """True when the PICTURE's drone track (last-known + a closing
        allowance of the drone type's known cruise speed per second of
        staleness — class intel, not truth) could be inside this ship's
        SM-2 drone-engagement range.  The 'sector is quiet' test behind
        the silence doctrine."""
        for tr in self.commander.picture.live_drone_tracks(now):
            age = now - tr["t"]
            d = float(np.hypot(float(tr["pos"][0]) - float(ship.pos[0]),
                               float(tr["pos"][1]) - float(ship.pos[2])))
            if d - DRONE_SPEED_MPS * age <= DRONE_ENGAGE_RANGE_M:
                return True
        return False

    def _drone_sector_alert(self, now: float) -> None:
        """Spec §4.3 'once detected ... silent ships may light up': a
        SILENT destroyer whose sector holds a drone track inside the
        engagement window raises its radar to kill the snooper — at that
        range the drone's SAR is imaging the hull regardless of
        emissions, so silence buys nothing and costs the shot.  The
        symmetric gate lives in _execute_commander_order: a SHIP_SILENT
        order is refused while the sector is hot."""
        for ship in self.ships:
            if not ship.alive or isinstance(ship, Carrier):
                continue                    # carrier doctrine: always dark
            if (not ship.radar.emitting
                    and self._drone_track_in_sector(ship, now)):
                ship.radar.emitting = True

    # ------------------------------------------------------- order execution

    def _execute_commander_order(self, order: dict) -> None:
        """Route one commander order dict (schema: sim/commander.py) onto
        the owning entity/system."""
        kind = order["type"]
        if kind == "vector_to_drone":
            self._vector_fighter_to_drone(order)
        elif kind == "awacs_flee":
            if self.awacs.alive:
                self.awacs.flee(order["threat_pos"])
        elif kind == "awacs_resume":
            if self.awacs.alive:
                self.awacs.stop_flee()
        elif kind in ("ship_silent", "ship_emit"):
            ship = next((s for s in self.ships
                         if s.ship_id == order["ship_id"]), None)
            if ship is None or not ship.alive:
                return
            if (kind == "ship_silent"
                    and self._drone_track_in_sector(ship, self.sim_time)):
                # 'Sector is quiet' gate (commander doctrine docstring):
                # silence denies ELINT only against a FAR snooper; one
                # already inside the engagement window is imaging the
                # hull on SAR — keep the radar up and kill it instead
                # (the spec §4.3 reaction, see _drone_sector_alert).
                return
            ship.radar.emitting = (kind == "ship_emit")
        elif kind in ("harm_package", "jassm_package"):
            self._launch_strike_package(order, sead=(kind == "harm_package"))
        elif kind == "tomahawk_salvo":
            self._fire_tomahawk_salvo(order)

    def _vector_fighter_to_drone(self, order: dict) -> None:
        """Drone-hunt vectoring (spec §5.1 hunt loop).  The commander
        names the nearest airborne fighter; the integrator may redirect
        to the nearest airborne fighter NOT flying a strike package (a
        package is never broken for a drone) that still carries AIM-9X.
        The fighter flies at the LAST-KNOWN track point with its nose
        radar searching; only once its OWN radar physically reacquires
        the drone (11 km 'stealth' cone) does it steer on the entity —
        continuous truth steering is gated behind an own-sensor event."""
        drone = self.drone
        if drone is None or not drone.alive:
            return
        named = next((f for f in self._fighter_list
                      if f.aircraft_id == order["fighter_id"]), None)
        candidates = [named] if named is not None else []
        candidates += [f for f in self._fighter_list if f is not named]
        hunter = None
        for f in candidates:
            if (f is not None and f.alive
                    and f.state in (FS_TAKEOFF, FS_TRANSIT, FS_ON_STATION)
                    and f._strike_target_xz is None
                    and "aim9x" in f.hardpoints):
                hunter = f
                break
        if hunter is None:
            return
        if (hunter._intercept_target is not None
                and getattr(hunter._intercept_target, "alive", False)):
            # Already in entity pursuit: the fighter's own tracking beats
            # a stale 1 Hz vector.  Re-vectoring here would CLEAR the
            # pursuit every time the overtaking jet's nose cone swings
            # off the target for a beat (measured in the 5b probes).
            return
        if hunter.radar.detects(drone.pos, drone.radar_size):
            hunter.execute_order({"type": "intercept", "target": drone})
            return
        # Not reacquired yet: head for last-known, radar searching.  The
        # commander re-issues the vector each tick while the track lives,
        # so the steering point refreshes at 1 Hz.
        hunter.execute_order({"type": "intercept"})
        tp = order["target_pos"]
        if hunter.state in (FS_TRANSIT, FS_ON_STATION):
            hunter._set_transit_to(
                np.array([float(tp[0]), float(tp[2])]))
            hunter.state = FS_TRANSIT

    def _refine_strike_aim(self, tx: float, tz: float):
        """Terminal scene-matching acquisition (SEEKER_BASKET_M doc): the
        nearest LIVE player structure within the basket of the believed
        aim point becomes the terminal aim (OBB mid-height); otherwise
        the round flies into the believed coordinates at ground level."""
        best = None
        best_d = SEEKER_BASKET_M
        for s in self.structures:
            if not s.alive:
                continue
            d = float(np.hypot(float(s.pos[0]) - tx, float(s.pos[2]) - tz))
            if d < best_d:
                best, best_d = s, d
        if best is not None:
            return (float(best.pos[0]), float(best.pos[2]),
                    _structure_aim_y(best))
        return tx, tz, max(terrain_height_scalar(tx, tz), 0.0)

    def _launch_strike_package(self, order: dict, sead: bool) -> None:
        """Launch a 2-ship HARM/JASSM package per the commander order:
        arm the loadout, roll the jets at the believed target, wire the
        weapon-release fields (sim/enemy_air.py release_weapons does the
        rest at its range gates).  The order's fighters were PARKED at
        live bases when the commander selected them this same tick."""
        tp = order["target_pos"]
        tx, tz = float(tp[0]), float(tp[2])
        if sead:
            aim_y = 0.0                      # HARMs chase emissions
        else:
            tx, tz, aim_y = self._refine_strike_aim(tx, tz)
        mission = dict(kind=order["type"], target_id=order["target_id"],
                       fighters=[], missiles=[], released=0)
        for fid in order["fighter_ids"]:
            f = next((x for x in self._fighter_list
                      if x.aircraft_id == fid), None)
            if f is None or f.state != FS_PARKED:
                continue
            f.assign_loadout(LOADOUT_SEAD if sead else LOADOUT_STRIKE)
            f.launch(patrol_anchor_xz=(tx, tz))
            if f.state != FS_TAKEOFF:
                continue                     # dead base refused the roll
            if sead:
                # The HARMs home on the actual EMITTER object — the
                # seeker physically chases emissions and the silence
                # degradation lives in sim/strike.py.  One child rng per
                # jet seeds the deterministic miss offsets.
                f.execute_order({
                    "type": "sead",
                    "target_radar": self.radar_station,
                    "rng": np.random.default_rng(
                        int(self._cmd_rng.integers(2 ** 63)))})
            else:
                f.execute_order({"type": "strike", "target_y": aim_y})
            # Target set AFTER the order (the order's standoff_xz key is
            # deliberately omitted: it would force FS_TRANSIT and skip
            # the takeoff climb of a jet that is still on the runway).
            f._strike_target_xz = np.array([tx, tz], dtype=np.float64)
            mission["fighters"].append(f)
        if mission["fighters"]:
            self._cmd_missions.append(mission)
        else:
            # Nothing rolled (bases died since selection): close the
            # commander's mission so it can re-plan.
            self.commander.complete_mission(order["type"],
                                            order["target_id"])

    def _fire_tomahawk_salvo(self, order: dict) -> None:
        """TOMAHAWK_SALVO order -> a SALVO_SIZE salvo from the surviving
        destroyers' magazines at the back-plotted cluster (the
        enemy_strikes.py launch pattern, aimed by the same terminal
        scene-matching refinement as the JASSMs).  The next salvo at this
        cluster unlocks after SALVO_PERIOD_S once these rounds are done."""
        tp = order["target_pos"]
        tx, tz, aim_y = self._refine_strike_aim(float(tp[0]), float(tp[2]))
        rounds = []
        for ship in self.ships:
            if isinstance(ship, Carrier):
                continue                     # carriers carry no TLAM
            while (len(rounds) < SALVO_SIZE and ship.alive
                   and ship.tomahawk_ammo > 0):
                deck = ship.pos + np.array([0.0, VLS_DECK_M, 0.0])
                m = StrikeMissile(
                    TOMAHAWK, deck,
                    np.array([0.0, TOMAHAWK.eject_speed, 0.0]),
                    (tx, tz), target_y=aim_y)
                m.launch_cinematic = False   # no 1x lock for enemy launches
                m.launch_platform = ship     # damage.py: never self-OBB-hit
                self.missiles.append(m)
                ship.tomahawk_ammo -= 1
                rounds.append(m)
            if len(rounds) >= SALVO_SIZE:
                break
        if rounds:
            self._cmd_missions.append(dict(
                kind="tomahawk_salvo", target_id=order["target_id"],
                fighters=[], missiles=rounds, released=len(rounds),
                complete_at=self.sim_time + SALVO_PERIOD_S))
        # Magazines dry: leave the commander's mission active forever —
        # there is nothing left to schedule at this cluster.

    def _release_fighter_weapons(self) -> None:
        """Sweep every live fighter's release gates (1 Hz — the checks
        are range compares; the rounds themselves fly at 120 Hz once
        spawned into self.missiles) and book new rounds to their
        missions for completion tracking."""
        for f in self._fighter_list:
            if not f._alive:
                continue
            new = f.release_weapons(self.missiles, bases=self.air_bases)
            if not new:
                continue
            rec = next((mi for mi in self._cmd_missions
                        if f in mi["fighters"]), None)
            if rec is not None:
                rec["missiles"].extend(new)
                rec["released"] += len(new)

    def _update_commander_missions(self, now: float) -> None:
        """Close out finished missions: every package jet is done (dead,
        or off its ingress states) and every released round is dead.
        HARM completion runs BDA — the package reports weapons on the
        emitter, so the commander BELIEVES the radar dead until it is
        heard emitting again (evidence resets the belief; a silenced
        radar that survived its CEP-offset impacts therefore 'plays
        dead' exactly as long as it stays silent)."""
        still = []
        for rec in self._cmd_missions:
            if rec["kind"] == "tomahawk_salvo":
                if (now >= rec["complete_at"]
                        and all(not m.alive for m in rec["missiles"])):
                    self.commander.complete_mission(rec["kind"],
                                                    rec["target_id"])
                else:
                    still.append(rec)
                continue
            fighters_done = all(
                (not f._alive) or f.state not in (FS_TAKEOFF, FS_TRANSIT,
                                                  FS_ON_STATION)
                for f in rec["fighters"])
            if fighters_done and all(not m.alive for m in rec["missiles"]):
                self.commander.complete_mission(rec["kind"],
                                                rec["target_id"])
                if rec["kind"] == "harm_package" and rec["released"] > 0:
                    self.commander.picture.mark_emitter_destroyed(
                        rec["target_id"])
            else:
                still.append(rec)
        self._cmd_missions = still

    # ---------------------------------------------------------------- phase 3

    @property
    def defeated(self) -> bool:
        """Spec 2.2 lose condition: every Bastion TEL structure is dead
        (no Oniks = no offense). The sim keeps running so the player can
        watch; full end-screens come in Phase 7."""
        return all(not s.alive for s in self.structures
                   if s.kind == "bastion_tel")

    @property
    def victorious(self) -> bool:
        """Spec 2.2 win condition: all enemy ships (incl. the carrier)
        AND the enemy airfield destroyed.  Phase 5 fields no enemy
        GROUND radars — they join this conjunction when the Phase-7
        setup screen adds their counts.  Like ``defeated``, the sim
        keeps running (full end-screens are Phase 7); the HUD mirrors
        the defeat banner with a VICTORY one."""
        return (all(not s.alive for s in self.ships)
                and not self.airfield.alive)

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
        flight and the enemy air war, then the enemy defenses and
        strikes: rounds launched here join ``self.missiles`` and are
        flown by the NEXT base step, exactly like a player launch this
        frame. Finally the two structure sweeps run (hostile rounds vs
        the player base; player cruise missiles vs the enemy airfield),
        the strike rounds and the enemy air feed the player picture and
        the recon sensors run."""
        super().step(dt)
        self._step_drones(dt)
        self._step_enemy_air(dt)
        self.defense.step(self, dt)
        self.strikes.step(self, dt)
        # Phase 5b: the commander — fed and ticked after the reactive
        # layers so rounds its orders spawn join self.missiles this step
        # and fly on the NEXT base step (the same convention as defense/
        # strikes launches).
        self._step_commander(dt)
        apply_missile_hits_structures(
            [m for m in self.missiles if getattr(m, "is_hostile", False)],
            self.structures, self.events)
        # The mirror sweep: only PLAYER cruise missiles (sim.missile
        # Missile — the Oniks; never hostile by construction) demolish
        # enemy installations.  Interceptors (SamMissile both sides) and
        # hostile strike rounds are excluded by the isinstance filter.
        apply_missile_hits_structures(
            [m for m in self.missiles if isinstance(m, Missile)],
            self.enemy_structures, self.events)
        self._update_strike_contacts(dt)
        # Enemy air -> the gated player picture: fighters/AWACS are air
        # entities (radar_size 'fighter'), tracked once the radar net
        # physically sees them — horizon math already right for a 9 km
        # CAP vs the mast-height station.
        self.contacts.update(self.enemy_air, dt, self.sim_time)
        self._step_recon_sensors()
        self._update_airfield_intel()
