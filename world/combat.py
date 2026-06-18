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

from sim.arsenal import KH31P, N40N6, ONIKS, S300, S300_TEL, TOMAHAWK, ZIRCON
from sim.bases import Structure, apply_missile_hits_structures
from sim.commander import EnemyCommander
from sim.contacts import ContactBoard, TRACK_DROP_S, _kind_of, _size_of
import sim.ew as ew
from sim.enemy_air import (FS_ON_STATION, FS_PARKED, FS_TAKEOFF, FS_TRANSIT,
                           LOADOUT_CAP, LOADOUT_SEAD, LOADOUT_STRIKE,
                           AirBase, Awacs, Carrier, Fighter, JammerAircraft)
from sim.enemy_defense import (DRONE_ENGAGE_RANGE_M, VLS_DECK_M,
                               EnemyDefenseController)
from sim.enemy_ships import Destroyer
from sim.enemy_strikes import SALVO_PERIOD_S, SALVO_SIZE, EnemyStrikeController
from sim.missile import Missile
from sim.pantsir import Pantsir, PantsirDefenseController
from sim.radar import Radar, RadarNetwork
from sim.recon import (DRONE_GONE, DRONE_SPEED_MPS, ELINT_FIX_ACTIONABLE_M,
                       ElintReceiver, ReconDrone, RwrReceiver, SarSensor)
from sim.sam import SamMissile
from sim.strike import PlayerArmMissile, StrikeMissile
from world.combat_config import CombatConfig, DEFAULT as _DEFAULT_CONFIG
from world import generation
from world.generation import BASE_POS, SEED, terrain_height_scalar
from world.spawn_zones import sample_fleet
from world.world import (CANISTER_MOUTH_OFFSET, SAM_MOUTH_OFFSETS, SAM_TEL_POS,
                         WorldState)

# Player ground radar station: home-coast shelf east of the base (the same
# raised cliff band that carries the S-300 pad; the on-land pin is LOCKED
# by tests/test_combat_world.py — nudge z south if generation ever changes).
RADAR_STATION_XZ = (40_000.0, -6_000.0)
RADAR_ANTENNA_M = 18.0          # radome center above the slab
ONIKS_LAUNCHER_SPACING_M = 6.0  # side-by-side gap between Oniks TELs (~2.9 m wide)
S300_LAUNCHER_SPACING_M = 8.0   # side-by-side gap between S-300 TELs (~3.05 m wide)
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

# M3-F2 escort jammer: standoff orbit deep behind the carrier screen (carrier
# band ~280 km, AWACS deeper at 405-435 km).  The jammer loiters BETWEEN them
# (~310 km) so its 200 W corridor collapses the player's 350 km ring from
# ahead of the fleet without parking it inside the player's reach.  The
# commander re-anchors this orbit toward the believed-emitter bearing
# (JammerAircraft.station_to); these are the spawn legs before the first STATION
# order.  40 km cross-track legs (JAMMER_ORBIT_HALF_LEN_M).
JAMMER_ANCHOR_A_XZ = (-30_000.0, 310_000.0)
JAMMER_ANCHOR_B_XZ = (30_000.0, 330_000.0)

# Standing CAP (commander-managed since 5b): the racetrack anchor sits
# over the destroyer screen (anchors at z 150/170 km) so the CAP orbits
# the fleet it protects.
FIGHTER_CAP_ANCHOR_XZ = (0.0, 160_000.0)
CAP_TARGET_AIRBORNE = 2     # fighters kept up (out of the 4 fielded)
FIGHTER_RWR_REACT_RANGE_M = 60_000.0  # a player SAM GUIDING ON this fighter (RWR
#                                       lock) makes it break this far out — react
#                                       to the lock, not just the close geometry,
#                                       so the jet has time to actually defeat it.
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

# --- Phase 6: Pantsir-S1 point defense (spec §4.2) ----------------------------

# Pantsir deployment sites guarding the player base.  Default 2 units
# (PANTSIR_COUNT — armory-bound in Phase 7): one shielding the Bastion TEL
# (the lose-condition asset, BASE_POS), one at the S-300 / radar cluster.
# Each site is PROBE-MEASURED for dry land AND clear northward LOS over the
# terrain to inbound sea-skimmers (threats ingress from the enemy continent
# at +z; terrain heights 94 m / 158 m, antenna 5 m up clears the ridge to
# 20 km against a 50 m TLAM and to 2 km against a 15 m terminal-diver).  A
# valley site would let the ridge mask the very sea-skimmers the unit
# exists to kill — do NOT move these without re-running the LOS sweep.  Y is
# set from terrain_height_scalar at construction (mirrors the S-300 TEL
# pin).  Offset > SEEKER_BASKET_M from the asset each guards (1.2 km E of
# the Bastion, 1.3 km W of the S-300 TEL): a Pantsir sits OUTSIDE the
# terminal-seeker basket of the cluster it protects, so a back-plotted
# JASSM/TLAM aim refinement (_refine_strike_aim) still acquires the TEL it
# is meant to kill, never the adjacent SHORAD vehicle — verified against
# the measured Oniks back-plot cluster (34.8, -861.7) in the Phase-5b
# kill-chain tests, which this placement must not perturb.
PANTSIR_COUNT = 2
PANTSIR_SPAWNS = (
    # Bastion guard: 1.2 km EAST of the TEL — clear LOS to +z, outside the
    # bastion cluster's seeker basket so it never steals the JASSM aim.
    {"unit_id": "pantsir_00", "xz": (1_200.0, -600.0)},
    # S-300 / radar-cluster guard: 1.3 km WEST of the S-300 TEL.
    {"unit_id": "pantsir_01", "xz": (83_700.0, -3_500.0)},
)

# Pantsir own destructibility: a thin-skinned SHORAD vehicle — two
# 250 kg-class HARM/JASSM hits mission-kill it (same ladder as the TEL
# vehicles in sim/bases.py; the radar mast is soft, the chassis is not).
# A dedicated 'pantsir' Structure kind is not added to sim/bases.py
# (locked file boundary); the generic TEL dims/HP default is the right
# class, so the wrapper is built with explicit hp + dims here.
PANTSIR_STRUCT_HP = 2
# sim/bases.py Structure.obb reads dims as (length=X, beam=Z, height=Y).  The
# models/pantsir.py body is built with its chassis LONG axis along +Z (the
# threat-ingress bearing the model faces; X span 3.44 m, Z span 8.19 m — the
# Z length is LOCKED by tests/test_pantsir_model.py::test_length_approx_8m).
# So the OBB footprint is (beam_X=3.0, length_Z=8.0): the box long side runs
# +Z with the hull, NOT +X.  Height 4.6 m tops the turret (model Y 4.58 m).
PANTSIR_STRUCT_DIMS = (3.0, 8.0, 4.6)   # (X beam, Z length, Y height)

# --- Phase 7: enemy ground radars (spec §5.5, config.n_enemy_radars) -----------
# Enemy ground radar deployment: on the enemy continent (z >= 500 km, dry land
# guaranteed).  X positions are drawn uniformly in the band below.  Z is fixed
# at _ENEMY_RADAR_Z_BASE (502 km — comfortably on the continent, probed dry).
# Antenna height and detection ranges mirror the PLAYER radar station above.
_ENEMY_RADAR_Z_BASE: float = 502_000.0       # m — dry land on enemy continent
_ENEMY_RADAR_ANTENNA_M: float = 18.0         # m — matches player radar mast
_ENEMY_RADAR_RANGES: dict = {               # size class -> max range (m)
    "ship":     200_000.0,
    "fighter":  200_000.0,
    "missile":  100_000.0,
    "stealth":  30_000.0,
}
_ENEMY_RADAR_X_RANGE: tuple = (-60_000.0, 60_000.0)  # X placement band (m)

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

    def __init__(self, config: CombatConfig = _DEFAULT_CONFIG,
                 rng_seed: int | None = None):
        """Construct the combat world from a CombatConfig.

        The legacy ``rng_seed`` keyword is kept for backward-compat:
        if supplied it OVERRIDES config.seed (old call sites like
        ``CombatWorld(rng_seed=42)`` keep working without change).
        Note: rng_seed alone (positional) will NOT work; callers that
        used ``CombatWorld()`` (no args) or ``CombatWorld(rng_seed=N)``
        are unchanged.  New callers pass a CombatConfig.
        """
        if rng_seed is None:
            rng_seed = config.seed
        # _config must be set BEFORE super().__init__ because _spawn_ships
        # is called from there and reads it.
        self._config = config
        # M3-terrain F3/F4: the ONE active terrain field for this map, built
        # once here and threaded to every sensor (player AND enemy) so they
        # read a single terrain truth — no fog asymmetry, no truth leak.
        # make_field(map_preset, seed) selects the map: preset 0 (the default)
        # returns generation.DEFAULT_FIELD (byte-identical to the legacy module
        # functions — the out-of-the-box battle is unchanged), presets 1-3 add
        # seeded mid-ocean island terrain ([seed, 12]) while keeping the
        # home/enemy coast cluster geometry stable. This ONE assignment swaps
        # the whole field everywhere at once. Set BEFORE super().__init__
        # because _build_contacts (player radar) runs there. terrain_height_at
        # / surface_height_at (used by the SAM / missile / strike LOS) are
        # overridden to read THIS field too.
        self.height_field = generation.make_field(config.map_preset, config.seed)
        # Bind the scalar query ONCE so every sensor stores the SAME callable
        # object (a fresh ``field.height_scalar`` access makes a new bound
        # method each time — equal but not identical; caching it lets the
        # no-cheat symmetry assertion check object identity and lets a preset
        # rebind one attribute to swap the whole field).
        self._height_fn = self.height_field.height_scalar
        super().__init__(rng_seed)

        # Wire the finite-magazine armory AFTER super().__init__ so the
        # per-shot counters (sam_ammo, sam_ammo_40n6) are overwritten.
        self._arm_magazines(
            oniks_ammo=config.oniks_ammo,
            oniks_mag_reload_s=config.oniks_mag_reload_s,
            s300_48n6_ammo=config.s300_48n6_ammo,
            s300_40n6_ammo=config.s300_40n6_ammo,
            s300_mag_reload_s=config.s300_mag_reload_s,
        )
        # Phase 8: multi-launcher salvo battery. Each Oniks TEL has 2 tubes;
        # each SPACE press fires the next READY tube (no firerate gate while
        # tubes are loaded), and that tube alone reloads from the shared
        # magazine pool. ``_build_oniks_battery`` sets _oniks_launcher_positions
        # (used by the structures below + the renderer).
        self._build_oniks_battery(config.n_oniks)
        self._build_s300_battery(config.n_s300)
        self._zircon_ammo = int(config.zircon_ammo)   # scarce hypersonic pool
        # M2-T2: player Kh-31P anti-radiation pool (scarce SEAD rounds) +
        # its seeded miss-offset stream.  The ARM stream is the SeedSequence
        # child [rng_seed, 8] — phase tag 8, reserved here so it can NEVER
        # collide with the existing child streams (fleet [seed,3], recon
        # [seed,4], commander [seed,5], pantsir [seed,6], enemy-radar [seed,7]).
        # Each PlayerArmMissile launch is constructed with THIS generator, so
        # the silence-CEP miss offset is deterministic per battle (same seed ->
        # same offset; physics-not-dice contract).
        self._kh31p_ammo = int(config.kh31p_ammo)
        self._arm_rng = np.random.default_rng([rng_seed, 8])
        # (missile, Structure) bindings for ARM ground-radar victory credit;
        # see _apply_arm_radar_kills (kept apart from self.missiles because the
        # base step prunes dead rounds before the credit pass runs).
        self._arm_radar_bindings: list[tuple] = []

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
        # One destructible bastion_tel Structure per Oniks launcher: ``defeated``
        # trips only when ALL are rubble, so the battery keeps firing while at
        # least one TEL survives.
        self.structures = [
            Structure(f"bastion_tel_{i:02d}", "bastion_tel", lpos.copy())
            for i, lpos in enumerate(self._oniks_launcher_positions)
        ]
        self.structures += [
            Structure(f"s300_tel_{i:02d}", "s300_tel", lpos.copy())
            for i, lpos in enumerate(self._s300_launcher_positions)
        ]
        self.structures.append(
            Structure("radar_station_00", "radar_station",
                      np.array([rx, terrain_height_scalar(rx, rz), rz]),
                      on_destroyed=lambda _s: setattr(
                          self.radar_station, "alive", False)))

        # ---- Phase 6: Pantsir-S1 point defense (spec §4.2, config-driven) ----
        # Player-side mirror of the destroyers' SM-2/CIWS auto-defense: each
        # Pantsir auto-engages inbound hostile STRIKE missiles tracked by its
        # own 30 km radar.  Determinism: a child generator off the world seed
        # (SeedSequence [seed, 6] — phase tag, never colliding with the
        # defense [seed], recon [seed, 4] or commander [seed, 5] streams)
        # seeds every unit; each 57E6 launch then draws one integer for its
        # round's multipath noise (sim/pantsir.py).  DUAL ROLE: the Pantsir
        # radars JOIN self.radar_net, so they also extend the player CONTACT
        # picture at 30 km — the S-300 can now form and engage low inbound
        # threats the 18 m ground-radar station misses under the horizon
        # (point-defense sensor + network node).  Each unit is wrapped in a
        # Structure for its OWN destructibility (a HARM/JASSM that finds it
        # kills it); on_destroyed clears Pantsir.alive AND drops its radar
        # from the net (mirror of the radar-station structure's death — the
        # network coverage vanishes with the node).
        n_pantsir = config.n_pantsir
        self._pantsir_rng = np.random.default_rng([rng_seed, 6])
        self.pantsirs: list[Pantsir] = []
        pantsir_spawns = self._pantsir_spawns(n_pantsir, rng_seed)
        for spec in pantsir_spawns:
            px, pz = spec["xz"]
            pos = np.array([px, terrain_height_scalar(px, pz), pz],
                           dtype=np.float64)
            unit = Pantsir(
                spec["unit_id"], pos,
                missile_ammo=config.pantsir_57e6_ammo,
                gun_ammo=config.pantsir_gun_ammo,
                rng=np.random.default_rng(
                    int(self._pantsir_rng.integers(2 ** 63))),
                radar_network=self.radar_net)
            # Arm the Pantsir magazine-refill mechanic.
            unit.arm_magazine(config.pantsir_mag_reload_s)
            self.pantsirs.append(unit)
            # Destructible wrapper: the closure binds THIS unit (default-arg
            # capture so the loop variable is frozen per structure).  Kind
            # "pantsir" is not in sim/bases.py's default HP/dims tables (a
            # LOCKED file), so dims + hp are passed EXPLICITLY here; the kind
            # string is then used only by ``defeated`` (which checks
            # bastion_tel) — a Pantsir death never trips the lose condition.
            self.structures.append(Structure(
                f"{spec['unit_id']}_struct", "pantsir", pos.copy(),
                dims=PANTSIR_STRUCT_DIMS, hp=PANTSIR_STRUCT_HP,
                on_destroyed=lambda _s, u=unit: u.kill()))
        # The controller defends EVERY player structure (Bastion/S-300/radar
        # + the Pantsirs themselves): it prioritises the threat closest in
        # time-to-impact to any protected asset.  Stepped in step() AFTER the
        # commander/strikes spawn this frame's hostile rounds so a Pantsir
        # reacts on the NEXT base step (same ordering as the other defense
        # layers — documented at the step() call site).
        self.pantsir_defense = PantsirDefenseController(
            self.pantsirs, structures=self.structures)

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
        # M3-F4: the player EW pod is AVAILABLE only when config.player_jammer is
        # set (mirror of n_jammers/kh31p_ammo OFF-by-default gates).  DEFAULT 0 ->
        # the pod is never armed: the drone's jam_active can never go True (the
        # JAM control + the world both gate on this), so _active_player_jammers()
        # is always empty and the enemy detection / own-ELINT paths stay
        # byte-identical.  When set, a freshly spawned drone starts STARTS COLD
        # (jam_active False) — the player toggles it loud with the JAM key.
        self._player_jammer = bool(config.player_jammer)
        self.drone = self._spawn_drone(recon_rng)
        self.drone_wrecks: list[ReconDrone] = []   # falling airframes
        self.elint = ElintReceiver(
            rng=recon_rng, height_fn=self._height_fn)
        self.sar = SarSensor()
        self.rwr = RwrReceiver(
            drone_id=self.drone.aircraft_id,
            height_fn=self._height_fn)
        self._drone_respawn_left = 0.0
        self._elint_next_t = 0.0
        self._fix_next_t = 0.0
        self._rwr_next_t = 0.0
        # ---- M2-T1: passive-SIGINT emitter picture ----
        # Heard enemy emitters (ship SPY-1 + airborne AWACS/fighter radars +
        # ground radars) the drone has LOCALIZED via ELINT triangulation,
        # surfaced as targetable EMITTER contacts.  A SEPARATE store from
        # contacts.tracks (the active-radar contact picture): the SIGINT
        # picture is distinct intel and keeping it apart leaves every
        # contacts.tracks consumer (threat strip / intel panel / map /
        # determinism) byte-identical.  emitter_id -> dict(pos (3,),
        # kind (str label), quality (m), last_heard (s), age (s)).
        self.emitter_contacts: dict = {}

        # ---- M3-F5: published EW legibility summary ----
        # A read-only summary the UI (HUD radar_jam_row + tactical _jam_overlay)
        # reads each frame: whether an enemy jammer is active, the player net's
        # burn-through range (from sim/ew.effective_range — the single source of
        # truth), and the SENSOR-BELIEVED jammer fix/bearing (the drone ELINT
        # est_pos / latest bearing — never a real jammer's truth).  Initialised
        # INACTIVE so the byte-identical default battle reads "no jammer" before
        # the first step; recomputed at the end of every step() from
        # already-stepped state (it changes NO sim result — pure read-only).
        self.ew_state: dict = {
            "active": False, "burn_through_m": None,
            "jammer_fix_xz": None, "jammer_bearing": None,
        }

        # ---- Phase 5a: enemy air order of battle ----
        ax, az = AIRFIELD_XZ
        self.airfield = Structure(
            "airfield_enemy_00", "airfield",
            np.array([ax, terrain_height_scalar(ax, az), az]),
            dims=AIRFIELD_DIMS, hp=AIRFIELD_HP)
        # Enemy fixed installations, swept against PLAYER cruise missiles
        # (the mirror of self.structures vs hostile rounds) in step().
        self.enemy_structures = [self.airfield]

        # ---- Enemy ground radars (spec §5.5, config.n_enemy_radars) ----------
        # Each radar is a Structure on the enemy continent (dry-land pin) with
        # a Radar that joins the ENEMY sensor picture (cue for destroyers +
        # commander).  They are valid Oniks targets (swept in the
        # apply_missile_hits_structures pass against PLAYER cruise missiles)
        # and contribute to the victorious win condition.
        self.enemy_radars: list[tuple] = []   # (Structure, Radar)
        self._spawn_enemy_radars(config.n_enemy_radars, rng_seed)

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
                              FIGHTER_CAP_ANCHOR_XZ,
                              height_fn=self._height_fn)
            base.parked.append(fighter)
            self.enemy_air.append(fighter)
        self.awacs = Awacs("awacs_00", AWACS_ANCHOR_A_XZ, AWACS_ANCHOR_B_XZ,
                           height_fn=self._height_fn)
        self.enemy_air.append(self.awacs)
        # ---- M3-F2 escort jammers (config.n_jammers, DEFAULT 0) ----
        # Each is enemy_air (NOT a Ship): a standoff Growler whose always-on
        # emitter collapses the player radar via sim/ew.py. n_jammers=0 builds
        # NONE -> _active_enemy_jammers() empty -> _player_visible passes
        # jammers=() -> byte-identical. Deterministic placement: a fixed deep
        # anchor (no RNG — the brain stations off BELIEF, not a seeded spawn);
        # extra jammers fan out across the standoff band.
        self._jammers: list[JammerAircraft] = []
        for j in range(config.n_jammers):
            ax = (JAMMER_ANCHOR_A_XZ[0] + j * 70_000.0,
                  JAMMER_ANCHOR_A_XZ[1])
            bx = (JAMMER_ANCHOR_B_XZ[0] + j * 70_000.0,
                  JAMMER_ANCHOR_B_XZ[1])
            jammer = JammerAircraft(f"jammer_{j:02d}", ax, bx,
                                    height_fn=self._height_fn)
            self._jammers.append(jammer)
            self.enemy_air.append(jammer)
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
            self._fighter_list, self.awacs, destroyers, seed=rng_seed,
            ground_radars=self._enemy_ground_radars,
            jammers=self._jammers)
        self._cmd_rng = np.random.default_rng([rng_seed, 5])
        self._cmd_feed_next_t = 0.0
        self._cmd_weapon_next_t = 0.0
        # id(missile) -> first-seen sensor record for the back-plot feed.
        self._cmd_missile_intel: dict[int, dict] = {}
        # Integrator-side mission execution records (fighters + spawned
        # rounds per active commander mission; completion + BDA run here).
        self._cmd_missions: list[dict] = []

    # --- terrain accessors (M3-terrain F3) --------------------------------
    # Override WorldState's module-shim accessors to read THIS world's active
    # HeightField, so the SAM / missile / strike terrain LOS (which call
    # world.terrain_height_at / world.surface_height_at) share the exact field
    # the radars and recon sensors use. For the default map this is
    # generation.DEFAULT_FIELD, so the result is byte-identical to the legacy
    # terrain_height_scalar / surface_height_scalar.
    def terrain_height_at(self, x: float, z: float) -> float:
        return self.height_field.height_scalar(x, z)

    def surface_height_at(self, x: float, z: float) -> float:
        return self.height_field.surface_scalar(x, z)

    def _spawn_ships(self):
        """Seeded fleet generation via world/spawn_zones.sample_fleet.

        The carrier (always 1) and config.n_destroyers destroyers are placed
        using a numpy SeedSequence child off the world seed (tag [seed, 3] —
        never colliding with defense/recon/commander/pantsir streams at tags
        6/4/5/6 respectively).  All hulls get a heading toward BASE_POS.
        _config is set BEFORE super().__init__ so this method finds it.
        """
        import math as _math
        config = getattr(self, "_config", _DEFAULT_CONFIG)
        fleet_rng = np.random.default_rng([config.seed, 3])
        # M3-F4: dodge the ACTIVE preset field's islands (preset 0 == the
        # module default, so the rng draw order + result are byte-identical to
        # the legacy fleet on the default map). _height_fn is bound before
        # super().__init__ calls this, so it is always available here.
        layout = sample_fleet(fleet_rng, config.n_destroyers,
                              height_fn=self._height_fn)

        bx, bz = float(BASE_POS[0]), float(BASE_POS[2])

        def _heading(anchor_xz):
            ax, az = anchor_xz
            return _math.degrees(_math.atan2(bx - ax, bz - az))

        ships = []
        for i, xz in enumerate(layout["destroyers"]):
            ships.append(Destroyer(
                f"destroyer_{i:02d}", xz,
                heading_deg=_heading(xz)))

        ships.append(Carrier(
            "carrier_00", layout["carrier"],
            heading_deg=_heading(layout["carrier"])))

        return ships

    @staticmethod
    def _pantsir_spawns(n: int, seed: int) -> list[dict]:
        """Deterministic Pantsir pad sites for up to n units.

        The first min(n, PANTSIR_COUNT) use the LOCKED probe-measured pads
        from PANTSIR_SPAWNS.  Units beyond PANTSIR_COUNT are generated from
        a child rng at offsets around the base (maintains SEEKER_BASKET_M
        clearance from the TEL clusters they guard).
        """
        import math as _math
        spawns = list(PANTSIR_SPAWNS[:min(n, PANTSIR_COUNT)])
        if n > PANTSIR_COUNT:
            bx = float(BASE_POS[0])
            bz = float(BASE_POS[2])
            extra = n - PANTSIR_COUNT
            for j in range(extra):
                angle = _math.radians(
                    (j / extra) * 360.0 + 45.0)
                radius = 1_700.0 + j * 200.0
                px = bx + radius * _math.sin(angle)
                pz = bz + radius * _math.cos(angle)
                spawns.append({
                    "unit_id": f"pantsir_{PANTSIR_COUNT + j:02d}",
                    "xz": (px, pz),
                })
        return spawns[:n]

    def _spawn_enemy_radars(self, n: int, seed: int) -> None:
        """Place n enemy ground radars on the enemy continent.

        Deterministic: a SeedSequence child off [seed, 7] draws X positions
        uniformly in _ENEMY_RADAR_X_RANGE.  All radars sit at z =
        _ENEMY_RADAR_Z_BASE on dry land (enemy continent land z > 500 km).

        Each radar:
        - Is a Structure in self.enemy_structures (swept vs player Oniks).
        - Owns a Radar in the enemy sensor picture (feeds destroyers/commander
          via _enemy_cue_radars — extended to include ground radars).
        - Carries a tactical-map site-marker dict (same shape as AIRFIELD_SITE)
          shown only once a player sensor images it (fog of war; latched in
          _update_airfield_intel, surfaced by known_enemy_sites).
        - on_destroy: clears its Radar.alive.
        """
        # Fog of war for the radar installations: ids the player side has
        # IMAGED (latched, like airfield_known — fixed installations never
        # age out of knowledge).  Built unconditionally so the n==0 path is
        # consistent with the n>0 path for downstream getattr-free access.
        self._enemy_radar_known: set = set()
        self._enemy_radar_sites: list = []
        if n <= 0:
            self._enemy_ground_radars: list = []
            return

        radar_rng = np.random.default_rng([seed, 7])
        x_lo, x_hi = _ENEMY_RADAR_X_RANGE
        self._enemy_ground_radars = []

        for i in range(n):
            xpos = float(radar_rng.uniform(x_lo, x_hi))
            zpos = _ENEMY_RADAR_Z_BASE
            ypos = terrain_height_scalar(xpos, zpos)
            pos = np.array([xpos, ypos, zpos], dtype=np.float64)
            radar_id = f"enemy_radar_{i:02d}"

            r = Radar(
                radar_id=radar_id,
                pos=(xpos, ypos + _ENEMY_RADAR_ANTENNA_M, zpos),
                antenna_m=_ENEMY_RADAR_ANTENNA_M,
                ranges=_ENEMY_RADAR_RANGES,
                height_fn=self._height_fn,
            )
            self._enemy_ground_radars.append(r)

            # Structure: reuses the player radar-station OBB/HP defaults.
            struct = Structure(
                radar_id, "radar_station", pos,
                on_destroyed=lambda _s, _r=r: setattr(_r, "alive", False))
            self.enemy_structures.append(struct)
            self.enemy_radars.append((struct, r))
            # Map marker (consumed by known_enemy_sites once imaged).
            self._enemy_radar_sites.append(
                {"id": radar_id, "kind": "radar",
                 "pos": (xpos, zpos), "name": "ENEMY RADAR"})

    def _spawn_aircraft(self):
        return []

    def _spawn_sites(self):
        return COMBAT_SITES

    def _build_contacts(self) -> ContactBoard:
        x, z = RADAR_STATION_XZ
        self.radar_station = Radar(
            "radar_player_00", (x, terrain_height_scalar(x, z), z),
            RADAR_ANTENNA_M, PLAYER_RADAR_RANGES,
            height_fn=self._height_fn)
        self.radar_net = RadarNetwork([self.radar_station])
        return ContactBoard((BASE_POS[0], BASE_POS[2]),
                            visible_fn=self._player_visible)

    def _active_enemy_jammers(self) -> list:
        """The live enemy escort-jammer emitters currently radiating the
        barrage corridor — the duck-typed jammers (``.pos`` + ``.jam_power_w``)
        the sim/ew.py field model consumes when gating the player radar.

        With config.n_jammers=0 NO jammer is built, so this is EMPTY and
        _player_visible passes ``jammers=()`` (the byte-identical legacy path —
        the EW field model is never consulted).  The field model itself
        LOS-gates each jammer against the victim radar, so we need only filter
        to live, emitting beacons here."""
        return [j.emitter for j in getattr(self, "_jammers", [])
                if j.alive and j.emitter.emitting]

    def _active_player_jammers(self) -> list:
        """The live player EW-pod beacon currently radiating the barrage
        corridor — the duck-typed jammer (``.pos`` + ``.jam_power_w``) the
        sim/ew.py field model consumes when gating the ENEMY radars (so a salvo
        leaks under a degraded SPY-1/AWACS picture) and when raising the drone's
        OWN ELINT noise floor (the self-deafen cost of going loud).

        The mirror of _active_enemy_jammers(): with config.player_jammer=0 NO
        pod is built (the drone's ``jam_active`` never goes True either), so this
        is EMPTY and the enemy missile-detection calls receive ``jammers=()``
        (the byte-identical legacy path — the EW field model is never consulted).
        A pod that is built but toggled OFF (jam_active False), or a config with
        player_jammer=0 (the pod never armed), likewise yields an empty list."""
        if not getattr(self, "_player_jammer", False):
            return []
        drone = getattr(self, "drone", None)
        if (drone is not None and drone.alive
                and getattr(drone, "jam_active", False)
                and getattr(drone, "pod_emitter", None) is not None):
            return [drone.pod_emitter]
        return []

    def _player_self_deafen_jammers(self) -> list:
        """The hot pod's SELF-DEAFEN beacon — fed to the drone's OWN
        elint.update so going loud raises the drone's passive noise floor by the
        calibrated, BOUNDED DRONE_POD_SELF_DEAFEN_FLOOR (a fixed co-channel
        desense, NOT the enemy-facing pod power, so it never walls off the
        player's own localization).  Same gate as _active_player_jammers (armed
        + alive + hot); empty otherwise -> the ELINT floor is unchanged
        (byte-identical default)."""
        if not getattr(self, "_player_jammer", False):
            return []
        drone = getattr(self, "drone", None)
        if (drone is not None and drone.alive
                and getattr(drone, "jam_active", False)
                and getattr(drone, "self_deafen_emitter", None) is not None):
            return [drone.self_deafen_emitter]
        return []

    def _player_visible(self, pos, size_class: str) -> bool:
        """The player picture's visibility gate: the radar net, OR (Phase
        4) the live drone's SAR strip for SURFACE targets — every surface
        entity rates 'ship' today, and SAR never images air targets, so a
        silent hull overflown by the drone enters the picture through the
        board's normal sustained-detection flow. Guarded with getattr:
        the board is built in super().__init__ before the drone exists.

        M3-F2: any active enemy escort jammer collapses the radar-net range
        ring via the EW burn-through field model (sim/ew.py) — passed through
        as ``jammers``.  Empty (the default n_jammers=0) -> byte-identical."""
        if self.radar_net.visible(pos, size_class,
                                  jammers=self._active_enemy_jammers()):
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
                          spawn_xz=(BASE_POS[0], BASE_POS[2]), rng=rng,
                          height_fn=self._height_fn)

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
        radiate nothing).  Phase 7: live enemy ground radars also emit
        (always-on coastal installations)."""
        ems = [(s.radar.radar_id, s.radar) for s in self.ships]
        ems.extend((e.radar.radar_id, e.radar)
                   for e in self.enemy_air if e.alive)
        # Enemy ground radars: always emitting while alive.
        ems.extend((r.radar_id, r)
                   for r in getattr(self, "_enemy_ground_radars", [])
                   if r.alive)
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
            # M3-F3: active enemy barrage jammers raise the passive ELINT noise
            # floor at the drone, widening the bearing sigma (sim/ew.noise_floor_at
            # -> sim/recon sigma scaling) so real-emitter fixes get HONESTLY
            # softer.  n_jammers=0 -> _active_enemy_jammers() empty -> floor 0 ->
            # byte-identical to the legacy draw.
            # M3-F4 self-deafen cost: when the drone's OWN EW pod is hot, its
            # SELF-DEAFEN beacon (a calibrated, BOUNDED floor — NOT the loud
            # enemy-facing pod power) ALSO joins the drone's own noise floor, so
            # a hot pod heavily-but-finitely softens the player's own ELINT fixes
            # (going loud blinds your own ESM, without ever walling localization
            # off).  player_jammer=0 / pod OFF -> _player_self_deafen_jammers()
            # empty -> no extra floor -> byte-identical.
            elint_jammers = (self._active_enemy_jammers()
                             + self._player_self_deafen_jammers())
            self.elint.update(drone.pos, self._emitters(), sim_time=now,
                              jammers=elint_jammers)
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
            self._inject_emitter_contacts(now)   # M2-T1 passive-SIGINT picture

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
                t_next=now + ELINT_FIX_PERIOD_S, is_air=False,
                kind=_kind_of(ship), size=_size_of(ship))

    def _player_targetable_emitters(self) -> dict:
        """Resolver: emitter_id -> (kind_label, live Radar obj, owner) for
        EVERY alive enemy emitter the player could ARM-target (M2-T2 homes
        the ARM on the returned Radar).

        Built from the SAME live sources _emitters() scans so the targetable
        set stays in sync with what the drone can hear: every alive ship's
        SPY-1 (the carrier's is silent so it is never HEARD, but it remains a
        valid target so it is listed here), each airborne enemy-air radar
        (AWACS vs FIGHTER labelled by entity type), and every live ground
        radar.  This reads live entities purely as the world's own bookkeeping
        (like _emitters()); the player only LEARNS of an emitter through the
        localized emitter_contacts subset (no truth leak — see
        _inject_emitter_contacts)."""
        tgt: dict = {}
        for s in self.ships:
            if not s.alive:
                continue
            tgt[s.radar.radar_id] = ("SPY-1", s.radar, s)
        for e in self.enemy_air:
            if not e.alive:
                continue
            # JammerAircraft subclasses Awacs — test it FIRST so the Growler
            # gets its own label (and so its empty-ranges beacon is correctly
            # surfaced as a player-targetable emitter for SEAD).
            if isinstance(e, JammerAircraft):
                kind = "JAMMER"
            elif isinstance(e, Awacs):
                kind = "AWACS"
            else:
                kind = "FIGHTER"
            tgt[e.radar.radar_id] = (kind, e.radar, e)
        for r in getattr(self, "_enemy_ground_radars", []):
            if not r.alive:
                continue
            tgt[r.radar_id] = ("GND RADAR", r, r)
        return tgt

    def _inject_emitter_contacts(self, now: float) -> None:
        """Heard + localized enemy emitters -> the passive-SIGINT picture
        (self.emitter_contacts), a store SEPARATE from contacts.tracks.

        Mirrors _inject_elint_tracks' freshness/actionable gates, but the fix
        carries the TRIANGULATED est_pos (the drone's ELINT belief) plus a
        kind label — never the radar's true position as ground truth.  Gates
        per emitter the drone reports hearing AND that resolves to a live
        targetable emitter (unknown ids skipped):
          * heard within ELINT_FRESH_S (silence => the contact ages out),
          * fix actionable (quality < ELINT_FIX_ACTIONABLE_M),
          * est_pos available.
        The error rides the contact AGE on the same ELINT_AGE_MAX_S mapping
        the ship fixes use.  Deterministic: no RNG."""
        resolver = self._player_targetable_emitters()
        for eid in self.elint.heard_emitters():
            entry = resolver.get(eid)
            if entry is None:
                continue                      # unknown / dead emitter
            kind = entry[0]
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
            self.emitter_contacts[eid] = dict(
                pos=est.copy(), kind=kind, quality=quality,
                last_heard=now, age=age)
        # Age out any emitter whose stored fix is no longer fresh: a silenced
        # emitter stops refreshing and drops from the SIGINT picture.
        for eid in [e for e, c in self.emitter_contacts.items()
                    if now - c["last_heard"] > ELINT_FRESH_S]:
            del self.emitter_contacts[eid]

    def _believed_jammer_fix(self):
        """The drone's SENSOR-BELIEVED jammer location, fog-honest — NEVER a
        real jammer entity's truth.  Returns ``(fix_xz, bearing)`` where:

          * ``fix_xz`` is the localized ELINT est_pos (x, z) of a heard JAMMER
            emitter taken from ``self.emitter_contacts`` (kind == "JAMMER",
            already gated fresh + actionable by _inject_emitter_contacts), or
            None when no jammer is localized yet;
          * ``bearing`` is the latest raw ELINT bearing (rad) to a heard but
            UN-localized jammer, used to draw the open bearing wedge before a
            fix exists, or None when the jammer hasn't been heard at all.

        With no ELINT picture / no jammer heard this is ``(None, None)`` and the
        band is absent (the fog intent: the player feels the degraded range via
        the HUD row but cannot place the source).  Pure read of the belief
        stores; touches no truth and no sim state."""
        fix_xz = None
        # Localized fix first (the strong belief): the SIGINT picture only ever
        # holds the est_pos triangulation, never radar truth.
        for c in self.emitter_contacts.values():
            if str(c.get("kind")) == "JAMMER":
                p = c["pos"]
                fix_xz = (float(p[0]), float(p[2]))
                break
        # Bearing fallback: a jammer heard on ELINT but not yet localized.
        bearing = None
        elint = getattr(self, "elint", None)
        if elint is not None:
            resolver = self._player_targetable_emitters()
            for eid in elint.heard_emitters():
                entry = resolver.get(eid)
                if entry is None or entry[0] != "JAMMER":
                    continue
                latest = elint.latest_bearing(eid)
                if latest is not None:
                    bearing = float(latest[1])
                    break
        return fix_xz, bearing

    def _publish_ew_state(self) -> None:
        """Recompute self.ew_state from already-stepped state (read-only — it
        changes NO sim result, so determinism is untouched).  With no active
        enemy jammer the state is INACTIVE and the legacy byte-identical path is
        preserved (the EW field model is never consulted).  The burn-through km
        comes from sim/ew.effective_range for the player ship-ring radar under
        the live enemy jammers — the SINGLE SOURCE OF TRUTH (never recomputed)."""
        jammers = self._active_enemy_jammers()
        if not jammers:
            self.ew_state = {
                "active": False, "burn_through_m": None,
                "jammer_fix_xz": None, "jammer_bearing": None,
            }
            return
        radar = self.radar_station
        burn_through_m = ew.effective_range(radar, "ship", radar.pos, jammers)
        fix_xz, bearing = self._believed_jammer_fix()
        self.ew_state = {
            "active": True,
            "burn_through_m": float(burn_through_m),
            "jammer_fix_xz": fix_xz,
            "jammer_bearing": bearing,
        }

    # ---------------------------------------------------------------- phase 5a

    def _enemy_cue_radars(self):
        """Datalink cueing sources beyond own-ship SPY-1 (spec section 3:
        "enemy ships rely on their own radar or AWACS cueing"): the live
        AWACS radar AND any live enemy ground radars (they join the enemy
        picture, cueing destroyers like the AWACS).  Resolved lazily —
        the defense controller is built before the AWACS and before
        _spawn_enemy_radars in __init__."""
        cues = []
        awacs = getattr(self, "awacs", None)
        if awacs is not None and awacs.alive:
            cues.append(awacs.radar)
        for r in getattr(self, "_enemy_ground_radars", []):
            if r.alive:
                cues.append(r)
        return cues

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
        self._assign_air_threats()
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

    def _assign_air_threats(self) -> None:
        """Flag each airborne Fighter with the player SAM it should break from
        (Phase 8 aircraft evasion) — SENSOR-DRIVEN, no truth read:

          * TRIGGER = RWR lock: a player SAM whose seeker/illuminator is guiding
            on THIS fighter (its .target is this airframe). Detecting that you
            are being locked is a genuine radar-warning-receiver event.
          * GEOMETRY = the enemy's own dead-reckoned missile TRACK of that SAM
            (the SAME picture store the SM-2/SM-6 fire off, populated by
            _feed_enemy_picture) — never the SAM's real position. A SAM that is
            locked on the fighter but NOT held as a track (the fleet can't see
            it) yields no firing-solution geometry, so no break: the fighter
            cannot dodge what neither it nor its datalink can place.

        Reacts out to FIGHTER_RWR_REACT_RANGE_M so the jet has room to defeat
        the shot. None clears the flag."""
        now = self.sim_time
        # Dead-reckoned XZ of every inbound player SAM the enemy SENSES.
        track_xz: dict[str, tuple] = {}
        for tr in self.commander.picture.live_missile_tracks(now):
            p, v = tr["pos"], tr["vel"]
            age = now - tr["t"]
            track_xz[tr["id"]] = (float(p[0]) + float(v[0]) * age,
                                  float(p[2]) + float(v[2]) * age)
        locks = [m for m in self.missiles
                 if isinstance(m, SamMissile) and m.alive
                 and not getattr(m, "is_hostile", False)]
        for e in self.enemy_air:
            if not isinstance(e, Fighter):
                continue
            threat_xz = None
            best = FIGHTER_RWR_REACT_RANGE_M
            for m in locks:
                tgt_id = getattr(getattr(m, "target", None),
                                 "aircraft_id", None)
                if tgt_id != e.aircraft_id:
                    continue            # not locked on this fighter: no RWR cue
                tp = track_xz.get(f"hostile_{id(m):x}")
                if tp is None:
                    continue            # locked but unseen: no track geometry
                d = float(np.hypot(tp[0] - e.pos[0], tp[1] - e.pos[2]))
                if d < best:
                    best, threat_xz = d, tp
            e._evade_threat = threat_xz

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
        The 3D scene is not gated — the geometry physically exists.

        Phase 7: the airfield AND every imaged enemy ground radar (spec
        §5.5) — both latched once a player sensor sees them, so the map
        fills in as the drone images the coast."""
        sites = [AIRFIELD_SITE] if self.airfield_known else []
        known = getattr(self, "_enemy_radar_known", ())
        for site in getattr(self, "_enemy_radar_sites", ()):
            if site["id"] in known:
                sites.append(site)
        return sites

    def _update_airfield_intel(self) -> None:
        """Latch the fixed-installation map markers (fog of war) when any
        player sensor images them: the drone's SAR strip (the designed
        path — a surface 'structure' is imaged exactly like a silent hull)
        or the radar net.  Covers the airfield AND, Phase 7, the enemy
        ground radars.  Gated only on the shared INTEL_CHECK_PERIOD_S
        cadence (NOT on airfield_known — radars may still be unknown after
        the airfield latches)."""
        if self.sim_time < self._intel_next_t:
            return
        self._intel_next_t = self.sim_time + INTEL_CHECK_PERIOD_S
        if not self.airfield_known and self._sensor_images(self.airfield.pos):
            self.airfield_known = True
        known = self._enemy_radar_known
        for struct, _r in getattr(self, "enemy_radars", ()):
            if struct.structure_id in known:
                continue
            if self._sensor_images(struct.pos):
                known.add(struct.structure_id)

    def _sensor_images(self, pos) -> bool:
        """True when a live player sensor images the surface point ``pos``:
        the drone's SAR strip (the imaging path for fixed installations) or
        the radar net at the 'ship' size class.  The shared gate behind the
        airfield and enemy-radar fog-of-war latches."""
        drone = self.drone
        if (drone is not None and drone.alive
                and self.sar.detects(drone.pos, pos)):
            return True
        return bool(self.radar_net.visible(pos, "ship"))

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
        # launching ship there, sim/enemy_defense.py).  The player ARM
        # (PlayerArmMissile, a StrikeMissile) is ALSO fed so an enemy radar
        # that physically detects it forms a kind=="kh31p" track — the only
        # thing that makes M2-T3 ARM-EMCON reachable in real play (M2 GATE
        # Finding 1).  The ARM is is_hostile=False and carries
        # launch_platform=self (a self-hit guard set at launch, NOT an
        # enemy-round marker), so it must bypass the launch_platform gate
        # below; the gate stays for the SamMissile case it was written for.
        live_keys = set()
        for m in self.missiles:
            if not m.alive or getattr(m, "is_hostile", False):
                continue
            is_player_arm = isinstance(m, PlayerArmMissile)
            if not (is_player_arm or isinstance(m, (Missile, SamMissile))):
                continue
            if (not is_player_arm
                    and getattr(m, "launch_platform", None) is not None):
                continue
            key = id(m)
            live_keys.add(key)
            # M3-F4: an active PLAYER EW pod collapses the enemy radar net via
            # the same burn-through field model (sim/ew.py).  The pod bites HERE
            # — a player missile that an enemy SPY-1/AWACS would track with the
            # pod OFF leaks under the degraded picture (its track stops forming /
            # refreshing).  Empty (player_jammer=0 or pod OFF) -> jammers=() ->
            # byte-identical to the legacy detection.  NO-CHEAT: the enemy still
            # only reacts to its OWN degraded detects(), never a truth read.
            pjam = self._active_player_jammers()
            rec = self._cmd_missile_intel.get(key)
            if rec is None:
                det = next((r for r in detectors
                            if r.detects(m.pos, "missile", jammers=pjam)), None)
                if det is None:
                    continue                    # nobody sees it yet
                rec = dict(track_id=f"hostile_{key:x}", first_t=now,
                           first_pos=m.pos.copy(), first_vel=m.vel.copy(),
                           det_pos=np.asarray(det.pos,
                                              dtype=np.float64).copy())
                self._cmd_missile_intel[key] = rec
            elif not any(r.detects(m.pos, "missile", jammers=pjam)
                         for r in detectors):
                continue                        # track coasts, no refresh
            # kind = the enemy's sensor CLASSIFICATION of the inbound (e.g.
            # "kh31p" for a detected player ARM) — drives the ARM-EMCON counter
            # (M2-T3). Fog-honest: stamped only on a physical detection above,
            # never a truth read of the round's intent.
            self.commander.process_missile_track(
                rec["track_id"], m.pos, m.vel, now, rec["first_t"],
                rec["first_pos"], rec["first_vel"], rec["det_pos"],
                kind=getattr(getattr(m, "weapon", None), "weapon_id", None))
        self._cmd_missile_intel = {
            k: v for k, v in self._cmd_missile_intel.items()
            if k in live_keys}
        # Bound the commander's track store: drop records for missiles that no
        # longer exist and have aged out (mirrors the world intel prune above
        # and live_missile_tracks' 30 s window). Without this the picture's
        # missile_tracks dict grows unbounded over a long match.
        pic.prune_missile_tracks(
            {f"hostile_{k:x}" for k in live_keys}, now)

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
                # EMCON: a fleeing AWACS runs SILENT — emitting while bugging
                # out only refines the player's ELINT fix and feeds a
                # radiation-homing terminal; the fleet leans on ship/ground
                # cueing during the silent window (Phase 8 smarter AWACS).
                self.awacs.radar.emitting = False
        elif kind == "awacs_resume":
            if self.awacs.alive:
                self.awacs.stop_flee()
                self.awacs.radar.emitting = True   # threat clear: sensor back up
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
        elif kind in ("ground_radar_silent", "ground_radar_emit"):
            # ARM-EMCON for enemy ground radars (M2-T3): a silenced radar
            # denies the inbound ARM its emission (degrading it to the CEP
            # ring). Toggle the matching _enemy_ground_radars entry; a dead
            # radar ignores the order.
            radar = next((r for r in getattr(self, "_enemy_ground_radars", [])
                          if r.radar_id == order["radar_id"]), None)
            if radar is None or not radar.alive:
                return
            radar.emitting = (kind == "ground_radar_emit")
        elif kind in ("jammer_jam", "jammer_lift", "jammer_flee"):
            # M3-F2 escort-jammer orders (sim/commander._defend_jammer):
            #   jammer_jam  -> radiate the corridor + (re)station the orbit on
            #                  the believed-emitter bearing,
            #   jammer_lift -> go dark (deny a radiation-homing seeker its
            #                  beacon — degrades the inbound round),
            #   jammer_flee -> turn tail and run from the sensed threat.
            jammer = next((j for j in getattr(self, "_jammers", [])
                           if j.aircraft_id == order["aircraft_id"]), None)
            if jammer is None or not jammer.alive:
                return
            if kind == "jammer_lift":
                jammer.emitter.emitting = False
            elif kind == "jammer_flee":
                jammer.flee(order["threat_pos"])
            else:  # jammer_jam
                jammer.emitter.emitting = True
                jammer.stop_flee()
                station = order.get("station_xz")
                if station is not None and "bearing" in order:
                    jammer.station_to(station, float(order["bearing"]))
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
        """Spec 2.2 win condition: all enemy ships (incl. carrier) AND
        all enemy ground radars AND the enemy airfield destroyed.
        Like ``defeated``, the sim keeps running after this trips
        (full end-screens in Phase 7); the HUD mirrors the defeat
        banner with a VICTORY banner."""
        if not all(not s.alive for s in self.ships):
            return False
        if not self.airfield.alive:
            pass  # airfield dead — check radars below
        else:
            return False
        # All enemy ground radars must also be destroyed.
        for struct, _r in getattr(self, "enemy_radars", []):
            if struct.alive:
                return False
        return True

    @property
    def launcher_armed(self) -> bool:
        """Salvo gate: armed while ANY Oniks tube is loaded and re-cocked, and
        the battery is not yet rubble (every bastion_tel structure dead)."""
        if self.defeated:
            return False
        return any(t["loaded"] and t["reload_left"] <= 0.0
                   for t in self._oniks_tubes)

    # ----------------------------------------------------- Oniks salvo battery

    def _build_oniks_battery(self, n: int) -> None:
        """N Oniks TELs side by side at BASE_POS, each with 2 launch tubes
        (port + starboard canister mouths). Sets _oniks_launcher_positions and
        _oniks_tubes; the starting magazine (_oniks_ammo) loads as many tubes
        as it can, the remainder is the reload reserve."""
        base = np.array(BASE_POS, dtype=np.float64)
        star = np.asarray(CANISTER_MOUTH_OFFSET, dtype=np.float64)
        port = np.array([-star[0], star[1], star[2]])   # mirror across the hull
        n = max(1, int(n))
        self._oniks_launcher_positions = []
        self._oniks_tubes = []
        for i in range(n):
            dx = (i - (n - 1) * 0.5) * ONIKS_LAUNCHER_SPACING_M
            lpos = base + np.array([dx, 0.0, 0.0])
            self._oniks_launcher_positions.append(lpos)
            for mouth in (star, port):
                self._oniks_tubes.append(
                    {"pos": lpos + mouth, "loaded": False, "reload_left": 0.0})
        cap = (self._oniks_ammo if self._oniks_ammo is not None
               else len(self._oniks_tubes))
        for i, t in enumerate(self._oniks_tubes):
            t["loaded"] = i < cap
        self._oniks_tube_reload_s = float(self._oniks_mag_reload_s)

    def launch(self, profile, target_point, waypoints=(), weapon_id="oniks"):
        """Fire the next READY Bastion tube (salvo: no firerate gate while tubes
        are loaded), either an Oniks or - when selected (B) - the scarce
        hypersonic Zircon (its own ammo pool). The fired tube reloads on its own
        timer. Returns the Missile, or None when no tube is ready / Zircon dry."""
        if self.defeated:
            return None
        if weapon_id == "zircon":
            if self._zircon_ammo is None or self._zircon_ammo <= 0:
                return None
            weapon = ZIRCON
        else:
            weapon = ONIKS
        tube = next((t for t in self._oniks_tubes
                     if t["loaded"] and t["reload_left"] <= 0.0), None)
        if tube is None:
            return None
        pos = tube["pos"]
        tp = np.asarray(target_point, dtype=np.float64)
        fx, fz = waypoints[0] if len(waypoints) else (tp[0], tp[2])
        heading = float(np.arctan2(fx - pos[0], fz - pos[2]))
        m = Missile(weapon, pos.copy(), heading, profile, tp,
                    waypoints=waypoints, salvo=self.oniks_fired)
        self.oniks_fired += 1
        self.missiles.append(m)
        tube["loaded"] = False
        tube["reload_left"] = self._oniks_tube_reload_s
        if weapon_id == "zircon":
            self._zircon_ammo -= 1
        elif self._oniks_ammo is not None:
            self._oniks_ammo -= 1
            # Pool empty: run the magazine refill (renewable ammo, preserved
            # from the single-launcher mechanic). The base step restores
            # _oniks_ammo to _oniks_mag_cap when the timer expires; the tubes
            # then reload from it.
            if self._oniks_ammo <= 0 and self._oniks_mag_cap is not None:
                self._oniks_ammo = 0
                self._oniks_mag_reload_left = self._oniks_mag_reload_s
        return m

    def _step_oniks_tubes(self, dt: float) -> None:
        """Per-tube reload: a fired tube re-cocks over _oniks_tube_reload_s,
        then pulls a round from the magazine reserve (rounds beyond the
        currently-loaded tubes). A re-cocked-but-empty tube also reloads the
        moment the magazine refills, so renewable ammo keeps feeding the
        battery (mirrors the single-launcher refill)."""
        for t in self._oniks_tubes:
            if t["reload_left"] > 0.0:
                t["reload_left"] = max(0.0, t["reload_left"] - dt)
            if not t["loaded"] and t["reload_left"] <= 0.0:
                loaded = sum(1 for u in self._oniks_tubes if u["loaded"])
                if (self._oniks_ammo or 0) - loaded > 0:
                    t["loaded"] = True

    # ----------------------------------------------------- S-300 salvo battery

    def _build_s300_battery(self, n: int) -> None:
        """N S-300 TELs side by side at the SAM site, each with the erected
        4-tube block. Sets _s300_launcher_positions and _s300_tubes; the
        48N6/40N6 pools (sam_ammo / sam_ammo_40n6) are shared across all tubes,
        and each tube re-cocks on its own timer (salvo: no firerate gate)."""
        base = np.asarray(SAM_TEL_POS, dtype=np.float64)
        mouths = [np.asarray(o, dtype=np.float64) for o in SAM_MOUTH_OFFSETS]
        n = max(1, int(n))
        self._s300_launcher_positions = []
        self._s300_tubes = []
        for i in range(n):
            dx = (i - (n - 1) * 0.5) * S300_LAUNCHER_SPACING_M
            lpos = base + np.array([dx, 0.0, 0.0])
            self._s300_launcher_positions.append(lpos)
            for mouth in mouths:
                self._s300_tubes.append({"pos": lpos + mouth,
                                         "reload_left": 0.0})
        self._s300_tube_reload_s = float(S300_TEL.reload_s)
        # The battery pool is the full configured magazine, not the legacy
        # 4-tube block (_arm_magazines capped sam_ammo at S300_TEL.ammo=4 for a
        # single launcher; a multi-launcher battery needs the whole pool).
        if self._s300_48n6_mag_cap is not None:
            self.sam_ammo = self._s300_48n6_mag_cap
        if self._s300_40n6_mag_cap is not None:
            self.sam_ammo_40n6 = self._s300_40n6_mag_cap

    @property
    def sam_launcher_armed(self) -> bool:
        """48N6 salvo gate: a round in the pool, no magazine refill pending,
        and at least one S-300 tube re-cocked."""
        if self.sam_ammo <= 0:
            return False
        if self._s300_48n6_mag_reload_left > 0.0:
            return False
        return any(t["reload_left"] <= 0.0 for t in self._s300_tubes)

    @property
    def sam_40n6_launcher_armed(self) -> bool:
        """40N6 salvo gate: a 40N6 round in the pool, no refill pending, and a
        tube re-cocked."""
        if self.sam_ammo_40n6 <= 0:
            return False
        if self._s300_40n6_mag_reload_left > 0.0:
            return False
        return any(t["reload_left"] <= 0.0 for t in self._s300_tubes)

    def launch_sam(self, aircraft_id, round_id: str = "48n6"):
        """Salvo S-300 launch: fire the selected round from the next READY tube
        (no firerate gate while tubes are loaded); that tube then reloads on its
        own timer. 48N6/40N6 draw from their own pools. Returns the SamMissile,
        or None (cold / empty / invalid track / out of envelope / no ready tube)."""
        if round_id == "40n6":
            if not self.sam_40n6_launcher_armed:
                return None
            weapon_def = N40N6
        else:
            if not self.sam_launcher_armed:
                return None
            weapon_def = S300
        track = self.contacts.tracks.get(aircraft_id)
        if track is None or not track.get("is_air"):
            return None
        if round_id == "40n6" and \
                float(track["pos"][1]) < weapon_def.min_intercept_alt:
            return None                       # 40N6 refuses sub-4 km targets
        target = self._find_air_entity(aircraft_id)
        if target is None:
            return None
        tube = next((t for t in self._s300_tubes if t["reload_left"] <= 0.0),
                    None)
        if tube is None:
            return None
        m = SamMissile(weapon_def, tube["pos"].copy(), target,
                       contact_estimate_fn=self._contact_estimate(aircraft_id))
        self.missiles.append(m)
        tube["reload_left"] = self._s300_tube_reload_s
        if round_id == "40n6":
            self.sam_ammo_40n6 -= 1
            if self.sam_ammo_40n6 <= 0 and self._s300_40n6_mag_cap is not None:
                self.sam_ammo_40n6 = 0
                self._s300_40n6_mag_reload_left = self._s300_mag_reload_s
        else:
            self.sam_ammo -= 1
            if self.sam_ammo <= 0 and self._s300_48n6_mag_cap is not None:
                self.sam_ammo = 0
                self._s300_48n6_mag_reload_left = self._s300_mag_reload_s
        return m

    def _step_s300_tubes(self, dt: float) -> None:
        """Per-tube S-300 reload: each fired tube re-cocks over its own timer."""
        for t in self._s300_tubes:
            if t["reload_left"] > 0.0:
                t["reload_left"] = max(0.0, t["reload_left"] - dt)

    # ----------------------------------------------------- Kh-31P player ARM
    #
    # INTENDED TARGETS / RANGE GAP (M2 GATE Finding 2-geometry, doc-only):
    #   The Kh-31P ARM (~130 km reach) is an anti-EMITTER SEAD round whose
    #   reachable prey are the SHIP SPY-1s, the AWACS when dragged in close,
    #   and fighter radars — NOT the win-condition INLAND ground radars
    #   (those sit at z~502 km, ~505 km away, far beyond ARM range, and are
    #   killed by Oniks / strike packages by design). The ground-radar
    #   victory-credit path below (_arm_radar_bindings -> _apply_arm_radar_kills)
    #   is sound and stays in place for closer / future engagements where a
    #   ground radar IS within reach — it simply does not fire in the default
    #   inland geometry. Do NOT extend ARM range or relocate the radars to
    #   "fix" this; that is a balance decision out of scope for the gate.
    def launch_arm(self, emitter_id):
        """Fire one Kh-31P player anti-radiation missile at a LOCALIZED enemy
        emitter (M2-T2).  The player SEAD round: it homes passively on the
        live emitting radar (the reused HarmMissile machine), not on truth.

        Returns the PlayerArmMissile, or None if any gate fails:
          * ``_kh31p_ammo <= 0`` — empty pool (default config has 0, so the
            out-of-the-box battle never offers an ARM);
          * ``emitter_id`` is None, or NOT in ``self.emitter_contacts`` — the
            FOG GATE: the player may only ARM an emitter the drone's passive
            SIGINT has LOCALIZED (no truth leak / no-cheat contract); an
            un-localized or unknown emitter is un-targetable;
          * the emitter does not resolve to a live targetable Radar via
            ``_player_targetable_emitters()`` (e.g. it just died).

        On success: spawn a PlayerArmMissile from a Bastion launcher mouth
        (reusing the Oniks battery's first launcher position — the player's
        coastal SEAD shooter sits with the strike battery; documented choice),
        homing on the resolved LIVE Radar, seeded by ``self._arm_rng``
        ([seed, 8]); decrement the pool; set ``launch_platform`` so the
        structure sweep can't self-hit; tag the ground-radar Structure (if
        any) for the victory-credit sync (``_apply_arm_radar_kills``).
        Mirrors ``launch_sam``'s ammo/None-gate structure.
        """
        if self._kh31p_ammo <= 0:
            return None
        # FOG GATE: only a LOCALIZED emitter (passive-SIGINT picture) is
        # targetable — never a truth-only entity the player hasn't heard.
        if emitter_id is None or emitter_id not in self.emitter_contacts:
            return None
        entry = self._player_targetable_emitters().get(emitter_id)
        if entry is None:
            return None                          # localized but no live radar
        _kind, target_radar, _owner = entry
        if not getattr(target_radar, "alive", False):
            return None

        # Launch position: the first Oniks launcher mouth (the SEAD round ships
        # with the coastal strike battery; the Bastion TEL is the player's only
        # ground launcher in COMBAT). Reuse a tube position for the muzzle point.
        if self._oniks_tubes:
            launch_pos = np.asarray(self._oniks_tubes[0]["pos"],
                                    dtype=np.float64).copy()
        else:
            launch_pos = np.asarray(BASE_POS, dtype=np.float64).copy()
        # Brief forward toss toward the emitter so the air-launched CLIMB phase
        # has a heading to steer (mirrors a rail kick; magnitude is the same
        # eject beat the HARM uses — small vs the boost that follows).
        import math as _math
        ex = float(target_radar.pos[0]) - float(launch_pos[0])
        ez = float(target_radar.pos[2]) - float(launch_pos[2])
        hdg = _math.atan2(ex, ez)
        vel0 = np.array([_math.sin(hdg) * 60.0, 0.0, _math.cos(hdg) * 60.0],
                        dtype=np.float64)

        m = PlayerArmMissile(KH31P, launch_pos, vel0, target_radar,
                             self._arm_rng)
        # launch_platform: defensive (the ARM is is_hostile=False and is not a
        # sim.missile.Missile, so it traverses NEITHER structure sweep — it can
        # never hit the player base nor auto-credit enemy structures; the
        # victory credit is the explicit binding below). Mirrors launch_sam.
        m.launch_platform = self

        self.missiles.append(m)
        self._kh31p_ammo -= 1

        # Victory-credit binding (spec risk #2): if the target is an enemy
        # GROUND radar, register (missile, Structure) so a fuse kill also flips
        # the Structure dead (the win condition checks struct.alive, NOT
        # radar.alive — see ``victorious``).  The binding is kept SEPARATE from
        # self.missiles because the base step() PRUNES dead missiles before
        # CombatWorld.step() reaches _apply_arm_radar_kills(); the binding
        # holds its own missile ref so the credit survives the prune.  Ship /
        # air radar kills carry no Structure and are not bound here.
        for struct, r in getattr(self, "enemy_radars", []):
            if r is target_radar:
                self._arm_radar_bindings.append((m, struct))
                break
        return m

    def _apply_arm_radar_kills(self) -> None:
        """Victory-credit sync for the player ARM (spec risk #2).

        A PlayerArmMissile fuse sets ``target_radar.alive = False`` directly
        (HarmMissile._fuse_check), but the win condition (``victorious``) and
        the on-map kill bookkeeping key on the enemy-radar STRUCTURE's
        ``alive`` flag, not the Radar's.  The ARM is a StrikeMissile (not a
        sim.missile.Missile), so it does NOT travel the
        ``apply_missile_hits_structures`` enemy-structure sweep that the Oniks
        uses — and the base step() prunes it from self.missiles the moment it
        dies.  So this works off ``self._arm_radar_bindings`` (set at launch):
        for every bound ARM whose radar has genuinely been fused dead (radar
        dead AND no silence miss offset — a CEP near-miss leaves the radar
        alive, so this never fires on a survived-emitter shot), kill the
        Structure via ``s.hit()`` so its ``on_destroyed`` runs and the win
        condition advances.  Emits the same ('base_hit'/'base_destroyed')
        events the Oniks sweep does so the renderer/HUD react identically.
        Resolved or spent bindings are dropped so the list cannot grow without
        bound.

        Attribution (M2 GATE Finding 4): when two ARMs bind the SAME ground
        radar, the credit/``base_hit`` event must come from the round that
        ACTUALLY fused, not merely the first binding in list order — otherwise
        the impact-event position can be stamped from a round that never
        detonated (impact_pos None -> struct.pos fallback) while its twin was
        the real killer. We therefore process bindings sorted so a fused round
        (``impact_pos is not None``) is preferred over an unfused one for the
        same struct. The win condition is unaffected either way (it keys on
        ``struct.alive``); this only sharpens the event coordinates."""
        if not self._arm_radar_bindings:
            return
        # Prefer a binding whose round actually fused (impact_pos set) so a
        # shared-struct credit takes the real detonation's coordinates. Stable
        # sort: same-struct fused rounds float ahead of unfused; cross-struct
        # order is otherwise preserved (single-ARM-per-radar is unchanged).
        ordered = sorted(
            self._arm_radar_bindings,
            key=lambda b: 0 if b[0].impact_pos is not None else 1)
        survivors = []
        for m, struct in ordered:
            if not struct.alive:
                continue                          # already credited / dead
            radar_dead = not m.target_radar.alive
            genuine_hit = (radar_dead
                           and getattr(m, "_miss_offset", None) is None)
            if genuine_hit:
                impact = (np.asarray(m.impact_pos, dtype=np.float64).copy()
                          if m.impact_pos is not None
                          else np.asarray(struct.pos, dtype=np.float64).copy())
                # One warhead = one ``hit``.  Enemy radar Structures are HP 1
                # (sim.bases HP_RADAR_STATION), so a single ARM destroys one —
                # matching the spec ("one-shots a soft radar").  If a radar's
                # HP is ever raised >1, the round below drops the binding after
                # one hit (it is spent), leaving the Radar blinded but the
                # Structure standing until further ARMs finish it — revisit
                # this site (loop to dead, or re-bind) if hardened radars land.
                struct.hit()
                self.events.append(("base_hit", impact.copy()))
                if not struct.alive:
                    self.events.append(("base_destroyed", impact.copy()))
                continue                          # binding resolved
            if not m.alive:
                # Round spent without a genuine hit (silence CEP miss, or a
                # surface impact short of the emitter): drop the binding.
                continue
            survivors.append((m, struct))         # still in flight
        self._arm_radar_bindings = survivors

    def _update_strike_contacts(self, dt: float) -> None:
        """Feed hostile rounds to the player picture. Two channels:

        * Launch-warning rounds (enemy SM-2, AIM-9X — ``launch_warning=True``)
          are seen the INSTANT they fire: their track is injected straight into
          the picture, bypassing the radar gate (an RWR / IR launch cue).
        * Everything else (Tomahawk/JASSM/HARM) stays radar-gated via the board,
          so the player only sees them once the radar physically detects them.

        Rounds that died this step linger one refresh (gated) or are dropped
        immediately (warning cue) — the threat is gone, so the cue clears."""
        for m in self.missiles:
            if m.alive and getattr(m, "is_hostile", False):
                self._strike_board[m.aircraft_id] = m
        if not self._strike_board:
            return
        gated = []
        for cid, m in self._strike_board.items():
            if getattr(m, "launch_warning", False):
                if m.alive:                       # instant launch cue (no gate)
                    self.contacts.tracks[cid] = dict(
                        pos=np.asarray(m.pos, dtype=np.float64).copy(),
                        vel=np.asarray(m.velocity(), dtype=np.float64).copy(),
                        age=0.0, t_next=self.sim_time, is_air=True,
                        kind=(getattr(getattr(m, "weapon", None), "weapon_id",
                                      None)
                              or getattr(m, "weapon_id", None)),
                        size=getattr(m, "radar_size", "missile"))
                else:
                    self.contacts.tracks.pop(cid, None)   # round gone — clear
            else:
                gated.append(m)                   # radar-gated (Tomahawk/JASSM)
        if gated:
            self.contacts.update(gated, dt, self.sim_time)
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
        self._step_oniks_tubes(dt)        # per-tube Oniks salvo reload
        self._step_s300_tubes(dt)         # per-tube S-300 salvo reload
        self._step_drones(dt)
        self._step_enemy_air(dt)
        self.defense.step(self, dt)
        self.strikes.step(self, dt)
        # Phase 5b: the commander — fed and ticked after the reactive
        # layers so rounds its orders spawn join self.missiles this step
        # and fly on the NEXT base step (the same convention as defense/
        # strikes launches).
        self._step_commander(dt)
        # Phase 6: the player's Pantsir point defense — stepped AFTER the
        # commander/strikes have spawned this frame's hostile rounds so a
        # Pantsir forms its track and launches a 57E6 that flies on the
        # NEXT base step (same reactive convention as self.defense/strikes;
        # the 57E6 then walks the structure sweep below as a friendly round
        # that is_hostile=False, so it can never demolish the base it
        # guards).  Runs BEFORE the hostile-vs-base sweep so a kill this
        # frame removes the round before it can be tested against a TEL on
        # the next — but a round the Pantsir FAILS to stop still reaches
        # the sweep and ends the battle (the layer is a shield, not a wall;
        # verified both ways in tests/test_phase6_e2e.py).
        self.pantsir_defense.step(self, dt)
        # Enemy land-attack rounds demolish the player base, but interceptors
        # flagged is_hostile (enemy SM-2/SM-6 = SamMissile) must NOT score a base
        # kill just because they cross a TEL's OBB (F3 fix) - exclude them.
        apply_missile_hits_structures(
            [m for m in self.missiles if getattr(m, "is_hostile", False)
             and not isinstance(m, SamMissile)],
            self.structures, self.events)
        # The mirror sweep: only PLAYER cruise missiles (sim.missile
        # Missile — the Oniks; never hostile by construction) demolish
        # enemy installations.  Interceptors (SamMissile both sides) and
        # hostile strike rounds are excluded by the isinstance filter.
        apply_missile_hits_structures(
            [m for m in self.missiles if isinstance(m, Missile)],
            self.enemy_structures, self.events)
        # M2-T2 victory-credit sync: a player ARM (PlayerArmMissile, a
        # StrikeMissile — NOT a sim.missile.Missile, so it skips BOTH sweeps
        # above) that fused on an enemy GROUND radar flips the radar dead but
        # not its Structure; bridge that to the win condition here.
        self._apply_arm_radar_kills()
        self._update_strike_contacts(dt)
        # Enemy air -> the gated player picture: fighters/AWACS are air
        # entities (radar_size 'fighter'), tracked once the radar net
        # physically sees them — horizon math already right for a 9 km
        # CAP vs the mast-height station.
        self.contacts.update(self.enemy_air, dt, self.sim_time)
        self._step_recon_sensors()
        self._update_airfield_intel()
        # M3-F5: publish the read-only EW legibility summary LAST, after the
        # jammers + the recon/SIGINT picture are current this step.  Pure read:
        # it derives the burn-through from sim/ew (single source of truth) and
        # the believed jammer fix/bearing from the ELINT picture — it touches no
        # sim state, so the default battle stays byte-identical.
        self._publish_ew_state()
