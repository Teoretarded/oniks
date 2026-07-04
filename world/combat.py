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

from sim.arsenal import (BASTION_K, BUK_AGILE, BUK_LONG, BUK_TEL, KALIBR_PL,
                         KH31P, N40N6, ONIKS, S300, S300_TEL, SWARM, SWARM_POD,
                         TOMAHAWK, ZIRCON)
from sim.asbm import AsbmMissile
from sim.bases import (DIMS_TEL as _BUK_STRUCT_DIMS, HP_S300_TEL as _BUK_STRUCT_HP,
                       Structure, apply_missile_hits_structures)
from sim.commander import (EnemyCommander, BACKPLOT_ERR_FRAC,
                           back_plot_surface)
from sim.contacts import ContactBoard, TRACK_DROP_S, _kind_of, _size_of
from sim.counter_battery import CBR_ANTENNA_M, CBR_RANGES, CbrTracker
from sim.decoys import CornerReflector, DecoyEmitter, biased_back_plot
import sim.ew as ew
from sim.enemy_air import (FS_ON_STATION, FS_PARKED, FS_TAKEOFF, FS_TRANSIT,
                           LOADOUT_CAP, LOADOUT_SEAD, LOADOUT_STRIKE,
                           AirBase, Awacs, Carrier, Fighter, JammerAircraft)
from sim.enemy_defense import (DRONE_ENGAGE_RANGE_M, TRACK_FORM_S, VLS_DECK_M,
                               EnemyDefenseController)
from sim.amphibious import (BEACHHEAD_GRACE_S, LCAC_PER_TRANSPORT, Lcac,
                            Transport, landing_box_xz)
from sim.enemy_ships import Destroyer
from sim.enemy_ship_classes import (AirDefenseShip, Flagship, GeneralDestroyer,
                                    GroundAttackShip)
from sim.enemy_strikes import SALVO_PERIOD_S, SALVO_SIZE, EnemyStrikeController
from sim.missile import Missile
from sim.pantsir import Pantsir, PantsirDefenseController
from sim.radar import Radar, RadarNetwork
from sim.recon import (ACOUSTIC_FIX_ACTIONABLE_M, AcousticReceiver, DRONE_GONE,
                       DRONE_SPEED_MPS, ELINT_FIX_ACTIONABLE_M,
                       ElintReceiver, ReconDrone, RwrReceiver, SarSensor)
from sim.sam import SamMissile
from sim.strike import PlayerArmMissile, StrikeMissile
from sim.submarine import Submarine
from sim.swarm import compute_swarm_speeds
from world.combat_config import CombatConfig, DEFAULT as _DEFAULT_CONFIG
from world import generation
from world.generation import BASE_POS, SEED, terrain_height_scalar
from world.spawn_zones import sample_fleet, sample_subs
from world.world import (CANISTER_MOUTH_OFFSET, SAM_MOUTH_OFFSETS, SAM_TEL_POS,
                         WorldState)

# Player ground radar station: home-coast shelf east of the base (the same
# raised cliff band that carries the S-300 pad; the on-land pin is LOCKED
# by tests/test_combat_world.py — nudge z south if generation ever changes).
RADAR_STATION_XZ = (40_000.0, -6_000.0)
PLAYER_RADAR_SPACING_M = 28_000.0
RADAR_ANTENNA_M = 18.0          # radome center above the slab
ONIKS_LAUNCHER_SPACING_M = 6.0  # side-by-side gap between Oniks TELs (~2.9 m wide)
S300_LAUNCHER_SPACING_M = 8.0   # side-by-side gap between S-300 TELs (~3.05 m wide)

# --- M5 #4 SHOOT-AND-SCOOT relocate (player action; NO config field) ----------
# A firing TEL (Bastion / S-300 / Buk) can be ordered to a new map position
# after it shoots; while it drives it is COMMITTED (cannot launch), and on
# arrival its pad, every launch tube, AND its destructible Structure all move to
# the new pad, so the enemy's stale back-plot points at empty dirt (the headline
# dodge — physics-not-dice, never a roll).  These two constants size the move.
# Open-source K-300P / Buk road march: a TEL convoys at ~40 km/h on a prepared
# road, and emplace/displace (jacks, erector, cabling) is a fixed ~30-40 s dwell.
RELOCATE_SPEED_MPS = 12.0      # ~43 km/h TEL road-march drive speed
RELOCATE_SETUP_S = 35.0        # emplace/displace dwell EACH END (committed, not
#                                yet moving) — total committed time is
#                                2*RELOCATE_SETUP_S + drive_distance/RELOCATE_SPEED_MPS
PLAYER_RADAR_RANGES = {         # size class -> max detection range (m)
    "ship": 350_000.0, "fighter": 350_000.0,
    "missile": 120_000.0, "stealth": 35_000.0,
    # M5 #1 amphibious: the LCAC is a tiny air-cushion craft with a small RCS —
    # the player radar holds it at a MUCH shorter range than a full 'ship'
    # contact, so it is "hard to catch close in" (the threat EMERGES from this
    # shorter ring + the radar horizon, NOT a probability flag).  Adding this key
    # is byte-identical at n_transports=0 (nothing rates 'lcac' until an LCAC
    # splashes) and never alters the 'ship'/'fighter'/'missile'/'stealth' rings.
    "lcac": 60_000.0,
}

# --- M5 Buk mid-SAM site (config-driven, n_buk default 0) ----------------------
# A medium-range gap-filler battery on dry land MIDWAY between the home base
# (x=0) and the S-300 site (x=85 km) — filling the Pantsir(20km)<->S-300(150km)
# coverage seam.  Terrain ~150 m here (dry land, verified).
BUK_SITE_XZ = (42_000.0, -5_000.0)
BUK_LAUNCHER_SPACING_M = 8.0    # side-by-side gap between Buk TELs
# The 9S36 fire-control radar joins radar_net (like the Pantsir radar): it
# extends the gated AIR picture over the seam at the medium-SAM band, but its
# 'ship'/surface range is kept MODEST so it does NOT over-extend the surface
# picture (the 18 m station + drone SAR already cover the sea).  Antenna 8 m
# (taller than the Pantsir's 5 m mast, well under the 18 m station tower).
BUK_RADAR_ANTENNA_M = 8.0
BUK_RADAR_RANGES = {            # size class -> max detection range (m)
    "fighter": 90_000.0,        # medium-SAM air search (a touch beyond the
    "missile": 90_000.0,        #   9M317's ~70 km reach)
    "stealth": 30_000.0,        # reduced SNR for low-observable targets
    "ship":    50_000.0,        # MODEST surface range (do not over-extend)
    # M5 #1 amphibious: a tiny LCAC is held only at the reduced low-observable
    # ring (vs a 'ship' 50 km) — byte-identical at n_transports=0 (nothing rates
    # 'lcac' until a splash).
    "lcac":    30_000.0,
}
# Buk struct: same soft-skinned TEL class as the S-300 (sim/bases.py 's300_tel'
# HP/dims), reused EXPLICITLY (_BUK_STRUCT_DIMS / _BUK_STRUCT_HP, imported at the
# top) because 'buk_tel' is not in the locked sim/bases.py tables.  ``defeated``
# checks only bastion_tel, so a Buk death never trips the lose condition (mirror
# of the Pantsir / swarm-pod wrappers).

# --- M5 #3 CBR counter-battery / early-warning radar (config-driven, default 0) ---
# A fixed PLAYER ground radar sited on the home coast, just inland of the
# waterline (clear sea LOS, like the Bastion emplacement).  Its set + ranges live
# in sim/counter_battery.py (CBR_ANTENNA_M=35 m tall mast, CBR_RANGES with a LONG
# 190 km 'missile' reach but SHORT 'ship'/'fighter' rings — a missile-WARNING set
# that COMPLEMENTS the 18 m station, not a second area-search radar).  The CBR
# Radar joins radar_net (so inbound Tomahawk/JASSM/HARM tracks surface EARLIER on
# the ContactBoard) and EMITS (honest cost: ESM-locatable + HARM-able).  The CBR
# Structure reuses the player radar-station OBB/HP defaults; on_destroyed clears
# the Radar's ``alive`` so the net coverage + the emitter feed drop the node
# (mirror of the radar-station / Buk / Pantsir wrappers).  ``defeated`` checks
# only bastion_tel, so a CBR death never trips the lose condition.  With n_cbr=0
# NOTHING is built (byte-identical default battle).
CBR_SITE_XZ = (8_000.0, -1_500.0)   # home coast, just inland of the z=0 waterline
CBR_LAUNCHER_SPACING_M = 12.0       # side-by-side gap for multiple CBR masts

# M5 #5 ESM decoy emitter + corner-reflector decoy placement (fixed home-coast
# emplacements, like the radar-station / CBR / Buk sites — the player's static
# spoofers, deterministic so a same-seed battle replays bit-for-bit; the reserved
# [seed, 10] stream is therefore unused, mirroring the CBR's deterministic site).
#   DECOY: its own coastal bait site, well clear of the real radar station + every
#   firing TEL so a HARM drawn onto it is purely wasted (the enemy localizes the
#   emission and the EXISTING _doctrine_blind sends a package at the decoy id).
#   CORNER REFLECTOR: a few km EAST of the Bastion pad on the coast-setback line
#   (z = HOME_COAST_Z - BACKPLOT_COAST_SETBACK_M = -300) where a real level-skimmer
#   launch back-plots — close enough (< sim.decoys.CR_INFLUENCE_M = 8 km) to capture
#   that launch's fix, but >> SEEKER_BASKET_M from every real firing TEL so the
#   biased cluster scatters the salvo onto empty dirt.
DECOY_SITE_XZ = (20_000.0, -1_500.0)   # isolated coastal bait emitter site
DECOY_SPACING_M = 600.0                # gap between multiple decoy masts
DECOY_STRUCT_DIMS = (3.0, 3.0, 8.0)    # a cheap mast/cab footprint
DECOY_STRUCT_HP = 1                    # soft: one HARM/TLAM hit kills the bait
CR_SITE_XZ = (5_000.0, -300.0)         # fake coastal battery point off the pad
CR_SPACING_M = 1_500.0                 # gap between multiple reflector clusters
CR_STRUCT_DIMS = (4.0, 4.0, 4.0)       # an inflatable corner-reflector cluster
CR_STRUCT_HP = 1                       # soft: a round into it is a satisfying waste
DECOY_RNG_TAG = 10                     # reserved determinism tag (placement is fixed)

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

# M5 flagship CEC degradation: when the datalink hub sinks the surviving
# escorts lose fleet cohesion — their effective continuous-visibility delay
# before a fire-control track forms (sim/enemy_defense TRACK_FORM_S, read per
# unit via getattr) is multiplied by this factor.  A bigger TRACK_FORM_S means
# the escort must hold a target LONGER on its own SPY-1 before it can shoot, so
# the leaderless fleet reacts measurably slower.  Sized so the delay clearly
# exceeds the default 1.5 s (2x -> 3.0 s) without being so large the escorts
# stop defending themselves entirely.
FLAGSHIP_DEAD_COHESION_FACTOR = 2.0

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

# --- M4-B loitering swarm pod ---------------------------------------------------
# The bundle-launch pods sit beside the Oniks battery at the home base.  Each
# pod is a destructible Structure (a soft-skinned multi-cell box: two
# 250 kg-class hits mission-kill it, same ladder as the Pantsir) wrapped around
# the shared cell magazine; killing every pod struct does NOT trip the lose
# condition (only bastion_tel does — mirror of the Pantsir wrapper).
SWARM_POD_SPACING_M = 7.0       # gap between pods, side by side
SWARM_POD_OFFSET = (0.0, 0.0, -40.0)   # m from BASE_POS (set back from the TELs)
SWARM_POD_STRUCT_HP = 2
SWARM_POD_STRUCT_DIMS = (4.0, 5.0, 2.4)   # (X beam, Z length, Y height)
# Multi-axis attack spread: each round detours through its own lateral spread
# waypoint (a different attack bearing) before converging on the shared aim
# point — the realistic loitering-swarm geometry that splits the defender's
# fire across bearings.  The spread is scaled to the run-in distance (a
# FRACTION of the launch->first-tail range, capped) so the per-round arcs differ
# by a meaningful amount the time-on-target math equalizes, on both short and
# long shots.  The outer arcs run near v_max; the inner ones dawdle.
SWARM_FAN_FRAC = 0.18           # lateral spread as a fraction of run-in range
SWARM_FAN_MAX_HALF_WIDTH_M = 12_000.0   # cap on the half-width
SWARM_FAN_SPREAD_FRAC = 0.33    # how far out the spread waypoint sits

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

# --- M5 submarine warfare + ASW (acoustic domain) -------------------------------
ACOUSTIC_LISTEN_PERIOD_S = 0.5   # s between buoy listening passes (= ELINT)
ACOUSTIC_FIX_PERIOD_S = 1.0      # s between acoustic triangulation + injection
SUB_FRESH_S = 6.0                # s since last heard for a buoy fix to count LIVE
SUB_SALVO_SIZE = 2               # Kalibr rounds per salvo (a small SSK salvo)
# Surveyed-coordinate CEP (m): the boat shoots a coarse fixed-installation
# belief (truth-free, like the GPS/INS Tomahawks).  Tuned so a salvo against a
# base cluster usually lands inside SEEKER_BASKET_M and can kill a TEL (the hit
# EMERGES from this CEP vs the basket — physics-not-dice), but is not pinpoint.
SUB_KALIBR_CEP_M = 250.0

# Launch-transient back-plot (the free, always-on ASW fix when the boat shoots):
# a coarse subsurface DATUM injected at the surveyed launch point with error that
# grows with the boat's range from the base.  The fairness backbone — every salvo
# leaves a trail even with no buoys, but it is COARSE (a cue, not a snipe) and
# FADES fast (the boat immediately runs).
BACKPLOT_DATUM_ERR_FRAC = 0.04   # datum 1-sigma error == 4% of launch range
BACKPLOT_DATUM_FADE_S = 45.0     # s the launch datum lives before it drops
# Prosecution belief: set HIGH on a datum / buoy localize, decays so the boat's
# evade lengthens right after it is heard, then it settles again.
SUB_THREAT_ON_DATUM = 1.0        # belief set when a salvo is back-plotted
SUB_THREAT_ON_FIX = 0.7          # belief set when buoys localize the boat
SUB_THREAT_DECAY_PER_S = 0.01    # belief decay (1/s) -> ~100 s to forget a datum

# Acoustic fix error -> subsurface-track age mapping (mirrors the ELINT mapping):
# a freshly-actionable 6 km fix injects as a nearly-stale track, a razor fix as a
# fresh one, so the map chevron sharpens as the cross-fix improves.
SUB_FIX_AGE_MAX_S = BACKPLOT_DATUM_FADE_S


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
        # M4-A Bastion-K ASBM pool (scarce lofted top-attack anti-ship rounds).
        # DEFAULT 0 -> launch('asbm') returns None and the round is never offered
        # (the B cycle / HUD strip gate on this being a non-None, > 0 pool), so
        # the out-of-the-box battle is byte-identical.
        self._asbm_ammo = int(config.asbm_ammo)
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
        # M4-B loitering swarm: the bundle-launch pod magazine.  DEFAULT
        # n_swarm_pods=0 -> _swarm_cells=0, no pod struct, launch_swarm returns
        # None: the out-of-the-box battle is byte-identical (no pod built, the
        # round never spawns).  _build_swarm_pods sets _swarm_pod_positions
        # (used by the structures below + any renderer) and the shared cell
        # magazine + its config-driven refill timer.
        self._swarm_fired = 0
        self._build_swarm_pods(config.n_swarm_pods,
                               config.swarm_cells_per_pod,
                               config.swarm_mag_reload_s)
        # M5 Buk mid-SAM battery + its 9S36 radar.  DEFAULT n_buk=0 -> NO battery
        # built, NO 9S36 joins radar_net, the pools stay 0, and launch_buk
        # returns None: the out-of-the-box battle is byte-identical (no Buk
        # touches the default battle or the duel path).  _build_buk_battery sets
        # _buk_launcher_positions / _buk_tubes (used by the structures below +
        # any renderer), seeds the 9M317 / 9M338 pools, and — when n_buk>0 —
        # appends the 9S36 Radar to self.radar_net.  Built AFTER _build_contacts
        # ran in super().__init__ (radar_net exists).  DETERMINISM: launch_buk
        # constructs each SamMissile with rng=None (no per-launch multipath
        # draw — identical to the player launch_sam path), so the Buk draws
        # NOTHING from any child stream and cannot collide with the player-ARM/
        # EW [seed, 8] stream (self._arm_rng above).  The round's distinct
        # behaviour EMERGES from the SamDef fields, not from noise — fully
        # deterministic (tests/test_buk_launch.py::test_buk_launch_determinism).
        self.n_buk = int(config.n_buk)
        self._buk_9m317_mag_cap = int(config.buk_9m317_ammo)
        self._buk_9m338_mag_cap = int(config.buk_9m338_ammo)
        self._buk_mag_reload_s = float(config.buk_mag_reload_s)
        self._buk_9m317_mag_reload_left = 0.0
        self._buk_9m338_mag_reload_left = 0.0
        self.buk_9m317_ammo = 0
        self.buk_9m338_ammo = 0
        self._buk_launcher_positions: list = []
        self._buk_tubes: list = []
        self._buk_radars: list = []
        self._buk_tube_reload_s = float(BUK_TEL.reload_s)
        self._build_buk_battery(self.n_buk)

        # M5 #3 CBR counter-battery / early-warning radar(s).  DEFAULT n_cbr=0 ->
        # NO CBR Radar/Structure built, NOTHING joins radar_net, the tracker list
        # stays empty, and world.cbr_threats / cbr_cues are empty: the out-of-the-
        # box battle is byte-identical.  _build_cbr (when n_cbr>0) builds each CBR
        # Radar, appends it to self.radar_net (so inbound strike tracks surface
        # earlier on the ContactBoard), and creates one CbrTracker per radar.
        # Built AFTER _build_contacts ran in super().__init__ (radar_net exists),
        # like the Buk battery above.  The CbrTrackers add NO RNG (the back-plot
        # is deterministic — the reserved [seed, 9] stream is unused).  The CBR
        # Structures are appended to self.structures below (with the other
        # destructible wrappers) so a single ``structures`` list still owns them.
        self.n_cbr = int(config.n_cbr)
        self._cbr_radars: list = []
        self._cbr_trackers: list = []
        self.cbr_threats: list = []
        self.cbr_cues: list = []
        self._build_cbr(self.n_cbr)

        # M5 #5 ESM DECOYS + CORNER-REFLECTORS.  DEFAULT n_decoys=0 /
        # n_corner_reflectors=0 -> both lists stay EMPTY: no decoy emitter is
        # built (absent from the _feed_enemy_picture emitter accrual), no reflector
        # is built (the back-plot bias hook is never reached), so the enemy picture
        # (emitters + back-plots + clusters) is BYTE-IDENTICAL.  The decoy EMITTER
        # is a DecoyEmitter (radar duck-type, EMPTY ranges -> bait, never detects)
        # the enemy ESM hears on the SAME accrual as the radar station + CBR; the
        # CORNER-REFLECTOR is a passive false RF return that biases a REAL launch's
        # back-plot through the SHARED back_plot_surface path.  The destructible
        # Structures are appended below with the other wrappers.  Placement is
        # fixed/deterministic (the reserved [seed, DECOY_RNG_TAG=10] stream unused).
        self.n_decoys = int(config.n_decoys)
        self.n_corner_reflectors = int(config.n_corner_reflectors)
        self._decoy_emitters: list = []
        self._corner_reflectors: list = []
        self._build_decoys(self.n_decoys, self.n_corner_reflectors)

        # M5 #1: a Transport subclasses Destroyer for the hull/damage/racetrack,
        # but it is NOT a combatant — it carries no radar (radar is None) and no
        # weapons, so it must be EXCLUDED from the fire-control / strike /
        # commander destroyer rosters (an included transport would crash the
        # defense controller's self.ship.radar.detects call and is doctrinally
        # wrong).  At n_transports=0 there are no Transports, so this filter
        # removes nothing -> byte-identical.
        destroyers = [s for s in self.ships
                      if isinstance(s, Destroyer)
                      and not isinstance(s, Transport)]
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
        # M4-B: one destructible Structure per loitering-swarm pod (kind
        # "swarm_pod" is NOT in sim/bases.py's locked HP/dims tables, so dims +
        # hp pass explicitly here, like the Pantsir wrapper).  ``defeated``
        # checks only bastion_tel, so a pod death never trips the lose
        # condition.  Empty list when n_swarm_pods=0 (byte-identical default).
        for i, ppos in enumerate(self._swarm_pod_positions):
            self.structures.append(Structure(
                f"swarm_pod_{i:02d}", "swarm_pod", ppos.copy(),
                dims=SWARM_POD_STRUCT_DIMS, hp=SWARM_POD_STRUCT_HP))
        # M5: one destructible Structure per Buk TEL (kind "buk_tel" is NOT in
        # sim/bases.py's locked tables, so dims + hp pass explicitly — the
        # soft-skinned S-300 TEL class).  on_destroyed clears the paired 9S36
        # Radar's ``alive`` so the net coverage vanishes with the node (mirror of
        # the radar-station / Pantsir wrapper).  ``defeated`` checks only
        # bastion_tel, so a Buk death never trips the lose condition.  Empty list
        # when n_buk=0 (byte-identical default).
        for i, lpos in enumerate(self._buk_launcher_positions):
            radar = self._buk_radars[i] if i < len(self._buk_radars) else None
            self.structures.append(Structure(
                f"buk_tel_{i:02d}", "buk_tel", lpos.copy(),
                dims=_BUK_STRUCT_DIMS, hp=_BUK_STRUCT_HP,
                on_destroyed=lambda _s, _r=radar: (
                    setattr(_r, "alive", False) if _r is not None else None)))
        # M5 #3: one destructible Structure per CBR mast.  Kind "radar_station"
        # reuses the player radar-station OBB/HP defaults (in sim/bases.py's
        # locked tables, like the enemy ground radars).  on_destroyed clears the
        # paired CBR Radar's ``alive`` so the net coverage AND the emitter feed
        # drop the node (the _feed_enemy_picture CBR accrual gates on r.alive +
        # emitting — mirror of the radar-station / Buk wrapper).  ``defeated``
        # checks only bastion_tel, so a CBR death never trips the lose condition.
        # Empty list when n_cbr=0 (byte-identical default).
        for i, r in enumerate(self._cbr_radars):
            # r.pos[1] is the SITE terrain height (the Buk convention — the mast
            # height is added inside Radar.antenna_alt), so the Structure ground
            # centre is r.pos directly.
            self.structures.append(Structure(
                f"cbr_{i:02d}", "radar_station", np.asarray(r.pos).copy(),
                on_destroyed=lambda _s, _r=r: setattr(_r, "alive", False)))
        # M5 #5: one destructible Structure per DECOY emitter.  Kind "decoy" is NOT
        # in sim/bases.py's locked HP/dims tables, so dims + hp pass explicitly
        # (soft: HP=1 so a HARM/TLAM kills the bait on the first hit).  on_destroyed
        # clears the DecoyEmitter.alive so the _feed_enemy_picture decoy accrual
        # goes ``heard`` False and the fix decays — the bait drops out of the enemy
        # picture with its mast.  ``defeated`` checks only bastion_tel, so a decoy
        # death never trips the lose condition.  Empty at n_decoys=0 (byte-id).
        for d in self._decoy_emitters:
            self.structures.append(Structure(
                f"{d.radar_id}_struct", "decoy", np.asarray(d.pos).copy(),
                dims=DECOY_STRUCT_DIMS, hp=DECOY_STRUCT_HP,
                on_destroyed=lambda _s, _d=d: setattr(_d, "alive", False)))
        # M5 #5: one destructible Structure per CORNER REFLECTOR (kind "corner_
        # reflector", explicit dims + HP=1).  on_destroyed clears the reflector's
        # ``alive`` so the back-plot bias hook stops planting biased fixes — the
        # spoof dies with the decoy.  A round that aims at the reflector-biased
        # cluster centroid finds THIS structure within the seeker basket (a
        # satisfying waste) until it is rubble, then dirt.  ``defeated`` checks only
        # bastion_tel, so a reflector death never trips the lose condition.  Empty
        # at n_corner_reflectors=0 (byte-identical default).
        for cr in self._corner_reflectors:
            self.structures.append(Structure(
                f"{cr.reflector_id}_struct", "corner_reflector",
                np.asarray(cr.pos).copy(),
                dims=CR_STRUCT_DIMS, hp=CR_STRUCT_HP,
                on_destroyed=lambda _s, _c=cr: setattr(_c, "alive", False)))
        # ---- M5 #4 SHOOT-AND-SCOOT: relocatable firing-TEL registry ----
        # GENERIC over the THREE firing TELs the back-plot targets (Bastion /
        # S-300 / Buk): one descriptor per launcher binds its live pad position,
        # its launch tubes, and its destructible Structure so ONE
        # _step_relocations drives all of them.  The radar station, Pantsir,
        # swarm pod and CBR are NOT relocatable in v1 (fixed sites — keeps scope
        # to the firing TELs).  Each descriptor's relocate state DEFAULTS to idle
        # (dest=None, committed=False, move_left_s=0) so a battle that never calls
        # request_relocate is byte-identical: _step_relocations is a pure no-op
        # and the arm gates' "and not committed" clause is vacuously True.  Built
        # here (after every firing-TEL Structure exists) by pairing each launcher
        # position list with its tube list and the matching kind-tagged Structure.
        self._relocatable = self._build_relocatable_registry()
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
        self._drone_count = int(config.n_drones)
        self.drone = (self._spawn_drone(recon_rng)
                      if self._drone_count > 0 else None)
        self.drone_wrecks: list[ReconDrone] = []   # falling airframes
        self.elint = ElintReceiver(
            rng=recon_rng, height_fn=self._height_fn)
        self.sar = SarSensor()
        self.rwr = RwrReceiver(
            drone_id=(self.drone.aircraft_id if self.drone is not None
                      else None),
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
        # ---- M5 flagship (CEC datalink hub, DEFAULT n_flagship=0 -> None) ----
        # The flagship's live SPY-1 cues the escorts via _enemy_cue_radars (CEC
        # remote cue).  When it SINKS its radar goes dark (ShipDefense.step's
        # dead-ship branch) and drops out of the cue set automatically, AND the
        # escorts' cohesion degrades (their effective TRACK_FORM_S rises) — a
        # SENSOR-honest nerf: the fleet falls back to own-SPY-1 and reacts
        # slower with the datalink down.  _flagship_alive latches the
        # alive->dead edge so the cohesion bump + 'datalink_degraded' event
        # fire exactly once.  None (the byte-identical default) leaves every
        # path untouched.
        self.flagship = next(
            (s for s in self.ships if isinstance(s, Flagship)), None)
        self._flagship_was_alive = (self.flagship is not None
                                    and self.flagship.alive)
        self._datalink_degraded = False
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
        self.awacs_units: list[Awacs] = []
        for i in range(int(config.n_awacs)):
            dx = i * 25_000.0
            awacs = Awacs(
                f"awacs_{i:02d}",
                (AWACS_ANCHOR_A_XZ[0] + dx, AWACS_ANCHOR_A_XZ[1]),
                (AWACS_ANCHOR_B_XZ[0] + dx, AWACS_ANCHOR_B_XZ[1]),
                height_fn=self._height_fn)
            self.awacs_units.append(awacs)
            self.enemy_air.append(awacs)
        self.awacs = self.awacs_units[0] if self.awacs_units else None
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

        # ---- M5: submarine warfare + ASW acoustic domain ----
        # BYTE-IDENTICAL DEFAULT: with config.n_subs == 0 self.subs stays empty,
        # NO acoustic receiver work runs, _step_acoustic_sensors / sub stepping /
        # launch-datum injection are all no-ops, place_sonobuoy + launch_asw
        # return None (0 stock), and victorious is unchanged (no subs to require
        # dead).  FRESH child streams: [seed, 13] sub (state-machine jitter +
        # spawn), [seed, 14] sonar (buoy bearing noise) — tags 3-8/12 are TAKEN,
        # 8 is the ARM stream (do NOT reuse).
        self._sub_rng = np.random.default_rng([rng_seed, 13])
        self._sonar_rng = np.random.default_rng([rng_seed, 14])
        self.subs = self._spawn_subs(config, self._sub_rng)
        # Player sonobuoy field: a finite stock placed during the match.  Each
        # entry is a (3,) world position (X, depth, Z).  AcousticReceiver hears
        # every sub via every placed buoy (no horizon/terrain — acoustics).
        self.sonobuoys: list[np.ndarray] = []
        self._sonobuoy_stock = int(config.n_sonobuoys)
        self.acoustic = AcousticReceiver(rng=self._sonar_rng)
        self._acoustic_next_t = 0.0
        self._sub_fix_next_t = 0.0
        # Player ASW prosecution rounds (kill a localized boat).
        self._asw_ammo = int(config.asw_ammo)
        self.asw_rounds: list = []
        # Subsurface track store (the player picture's sub fixes + launch datums)
        # — kept SEPARATE from contacts.tracks so every existing radar-picture
        # consumer stays byte-identical.  sub_id|datum_id -> dict(pos, age,
        # quality, kind, last_heard, t_drop).
        self.sub_contacts: dict = {}
        # Per-sub sensor-honest prosecution belief (0..1) the SubCommander reads
        # to evade: set HIGH when the boat was just datum'd / a buoy localized
        # it, decays over time.  Keyed by sub_id.  NEVER a truth read.
        self._sub_threat: dict[str, float] = {}

        # ---- M5 #1: amphibious landing force + the TIMED beachhead lose-path ----
        # BYTE-IDENTICAL DEFAULT: with config.n_transports == 0 NO Transport/LCAC
        # is built (self.transports + self.lcacs are empty -> the lists below
        # gather the few transports already placed in self.ships at 0 count, i.e.
        # none), _step_amphibious is a pure no-op, the beachhead clock never
        # starts (it only starts when an LCAC reaches the box, impossible with no
        # transports), and defeated trips ONLY on the bastion_tel clause.  FRESH
        # child stream [seed, 15] for the LCAC splash scatter (tags 3-8/12/13/14
        # are TAKEN, 9/10/11 RESERVED — 15 is the world-owned amphibious stream).
        self._amphib_rng = np.random.default_rng([rng_seed, 15])
        self._beachhead_grace_s = float(
            getattr(config, "beachhead_grace_s", BEACHHEAD_GRACE_S))
        # The coast LANDING_BOX (a short hop seaward of the base).
        self._landing_box_xz = landing_box_xz(
            (float(BASE_POS[0]), float(BASE_POS[2])))
        # The landing force lives in self.ships (visible + counts for victory);
        # these are convenience views, gathered from self.ships so they always
        # reflect the live roster (LCACs splashed mid-match are appended to
        # self.ships and picked up here on the next gather).  self.lcacs starts
        # empty (LCACs only exist after a splash).
        self.transports: list = [s for s in self.ships
                                 if isinstance(s, Transport)]
        self.lcacs: list = []
        self._lcac_seq = 0            # monotonic id counter for splashed LCACs
        # Beachhead clock: None until the FIRST LCAC reaches the box, then counts
        # down from _beachhead_grace_s.  defeat trips when it hits 0 AND any
        # committed craft is still alive; clearing them all CANCELS the loss.
        self._beachhead_left: float | None = None
        self._beachhead_lost = False  # latched True only on an honest expiry

    # --- M6 campaign carry-forward -----------------------------------------
    def apply_initial_state(self, initial_state: dict | None) -> None:
        """Campaign carry-forward: overwrite the offensive magazine pools from a
        prior battle's snapshot (game/campaign.world_snapshot).

        Called by the CAMPAIGN launch path AFTER construction — exactly the way
        ``_arm_magazines`` overrides the base counters, one step later — so a
        battle inherits the ammo it ended the previous battle with.  The default
        single-battle path NEVER calls this (a None/empty state is a no-op), so
        the out-of-the-box battle is byte-identical.  Keys are LIVE world
        attribute names so the ingest is a flat, schema-free setattr (campaign
        carries state OUTSIDE the locked CombatConfig).

        v1 carries AMMO ONLY.  Base-damage carry-forward is deferred: a carried-
        dead structure must fire its on_destroyed closure (else the live
        radar/Pantsir desyncs) and a destroyed bastion means the campaign is LOST
        (not a pre-defeated next battle) — both belong with the campaign-loop pass
        (critique F2/F16/F19).  Any unrecognised key (e.g. a future structure_hp)
        is ignored here, so it can never silently corrupt structure state."""
        if not initial_state:
            return
        for attr in ("_oniks_ammo", "_zircon_ammo", "_asbm_ammo", "_kh31p_ammo",
                     "sam_ammo", "sam_ammo_40n6"):
            if attr in initial_state:
                setattr(self, attr, int(initial_state[attr]))

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
        """Seeded TYPED fleet generation via world/spawn_zones.sample_fleet.

        The carrier (always 1) plus the config-driven typed roster (general
        destroyers + the M5 classes: flagship / aaw / ground_attack) are placed
        using a numpy SeedSequence child off the world seed (tag [seed, 3] —
        never colliding with defense/recon/commander/pantsir streams at tags
        6/4/5/6 respectively).  All hulls get a heading toward BASE_POS.
        _config is set BEFORE super().__init__ so this method finds it.

        BYTE-IDENTICAL: with n_flagship=n_aaw=n_ground_attack=0 (the default)
        the typed mixer draws EXACTLY today's layout and only GeneralDestroyer
        hulls are built — and GeneralDestroyer is numerically the legacy
        Destroyer (sim/enemy_ship_classes.py), so the default battle replays
        bit-for-bit.  The general hulls keep the legacy ``destroyer_{i:02d}``
        ids in the legacy order; the new classes append after.
        """
        import math as _math
        config = getattr(self, "_config", _DEFAULT_CONFIG)
        fleet_rng = np.random.default_rng([config.seed, 3])
        n_flagship = int(getattr(config, "n_flagship", 0))
        n_aaw = int(getattr(config, "n_aaw", 0))
        n_ground_attack = int(getattr(config, "n_ground_attack", 0))
        # M5 #1 amphibious transports: the REAR band of sample_fleet, drawn
        # AFTER every legacy + M5 placement (the LOCKED draw order in
        # tests/test_spawn_zones.py), so n_transports=0 is byte-identical.
        n_transports = int(getattr(config, "n_transports", 0))
        # M3-F4: dodge the ACTIVE preset field's islands (preset 0 == the
        # module default, so the rng draw order + result are byte-identical to
        # the legacy fleet on the default map). _height_fn is bound before
        # super().__init__ calls this, so it is always available here.
        layout = sample_fleet(
            fleet_rng, config.n_destroyers, height_fn=self._height_fn,
            n_flagship=n_flagship, n_aaw=n_aaw,
            n_ground_attack=n_ground_attack, n_transports=n_transports)

        bx, bz = float(BASE_POS[0]), float(BASE_POS[2])

        def _heading(anchor_xz):
            ax, az = anchor_xz
            return _math.degrees(_math.atan2(bx - ax, bz - az))

        ships = []
        # General destroyers: GeneralDestroyer == legacy Destroyer numerically,
        # keeping the legacy ids/order (byte-identical default).
        for i, xz in enumerate(layout["general"]):
            ships.append(GeneralDestroyer(
                f"destroyer_{i:02d}", xz, heading_deg=_heading(xz)))

        # M5 typed escorts (no-ops at count 0 -> byte-identical).
        for i, xz in enumerate(layout["aaw"]):
            ships.append(AirDefenseShip(
                f"aaw_destroyer_{i:02d}", xz, heading_deg=_heading(xz)))
        for i, xz in enumerate(layout["ground_attack"]):
            ships.append(GroundAttackShip(
                f"ground_attack_destroyer_{i:02d}", xz,
                heading_deg=_heading(xz)))
        if layout["flagship"] is not None:
            ships.append(Flagship(
                "flagship_00", layout["flagship"],
                heading_deg=_heading(layout["flagship"])))

        ships.append(Carrier(
            "carrier_00", layout["carrier"],
            heading_deg=_heading(layout["carrier"])))

        # M5 #1 amphibious transports (no-op at count 0 -> byte-identical: the
        # 'transports' list is empty so nothing appends and the default fleet is
        # exactly ["destroyer"*n, "carrier"]).  Each Transport is a soft-skinned
        # LHD hull in self.ships -> it COUNTS toward victory (ships-count-for-win)
        # and is OBB-damaged by the same sweep as a destroyer.  It carries NO
        # radar (Transport.radar is None) so it never enters the ELINT/_emitters
        # path (the world guards every self.ships radar walk).  Heading toward
        # BASE_POS so it is already aimed at its launch line.
        bx_, bz_ = float(BASE_POS[0]), float(BASE_POS[2])
        for i, xz in enumerate(layout.get("transports", [])):
            ships.append(Transport(
                f"transport_{i:02d}", xz, base_xz=(bx_, bz_),
                heading_deg=_heading(xz),
                embarked_lcac=LCAC_PER_TRANSPORT))

        return ships

    def _spawn_subs(self, config, sub_rng) -> list:
        """M5: build the enemy diesel SSK roster (NOT added to self.ships — the
        sub is invisible to radar by construction).  BYTE-IDENTICAL DEFAULT:
        n_subs == 0 returns [] WITHOUT drawing from sub_rng or calling
        sample_subs, so nothing about the default battle changes.  Each boat is
        anchored in the deep-open-water sub band (80-140 km, closer than the
        carrier so its scaled Kalibr reaches the base) on the dedicated
        [seed, 13] stream — it never perturbs the fleet rng."""
        n = int(getattr(config, "n_subs", 0))
        if n <= 0:
            return []
        bx, bz = float(BASE_POS[0]), float(BASE_POS[2])
        anchors = sample_subs(sub_rng, n, height_fn=self._height_fn)
        subs = []
        for i, xz in enumerate(anchors):
            subs.append(Submarine(
                anchor_xz=xz, rng=sub_rng,
                kalibr_ammo=int(getattr(config, "sub_kalibr_ammo", 0)),
                base_xz=(bx, bz), sub_id=f"ssk_{i:02d}"))
        return subs

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
                pos=(xpos, ypos, zpos),
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

    def _player_radar_xz(self, idx: int) -> tuple[float, float]:
        if idx <= 0:
            return RADAR_STATION_XZ
        x, z = RADAR_STATION_XZ
        sign = -1.0 if idx % 2 else 1.0
        step = (idx + 1) // 2
        return (x + sign * PLAYER_RADAR_SPACING_M * step,
                z - PLAYER_RADAR_SPACING_M * step)

    def _spawn_sites(self):
        n = int(getattr(self._config, "n_player_radars", 1))
        if n <= 1:
            return COMBAT_SITES
        sites = []
        for i in range(n):
            xz = self._player_radar_xz(i)
            sites.append({"id": f"radar_player_{i:02d}", "kind": "radar",
                          "pos": xz, "name": "RADAR STN (FRIENDLY)"})
        return sites

    def _build_contacts(self) -> ContactBoard:
        n = int(getattr(self._config, "n_player_radars", 1))
        self.player_radars: list[Radar] = []
        for i in range(max(1, n)):
            x, z = self._player_radar_xz(i)
            radar = Radar(
                f"radar_player_{i:02d}",
                (x, terrain_height_scalar(x, z), z),
                RADAR_ANTENNA_M, PLAYER_RADAR_RANGES,
                height_fn=self._height_fn)
            self.player_radars.append(radar)
        self.radar_station = self.player_radars[0]
        self.radar_net = RadarNetwork(list(self.player_radars))
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
        # SAR images any SURFACE contact the drone overflies — a 'ship' OR (M5 #1)
        # an 'lcac' landing craft (both are surface hulls; SAR never images air).
        # At n_transports=0 nothing rates 'lcac', so adding it is byte-identical.
        drone = getattr(self, "drone", None)
        return (size_class in ("ship", "lcac") and drone is not None
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
        # M5 #1: a Transport / LCAC carries NO radar mount (radar is None) — the
        # fog contract is that they NEVER emit, so they are skipped here and can
        # never join the ELINT picture (found by radar/SAR geometry only).  At
        # n_transports=0 there are none, so this filter is a no-op (byte-id).
        ems = [(s.radar.radar_id, s.radar) for s in self.ships
               if getattr(s, "radar", None) is not None]
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
            radars = [s.radar for s in self.ships
                      if getattr(s, "radar", None) is not None]
            radars.extend(e.radar for e in self.enemy_air if e.alive)
            self.rwr.update(drone.pos, radars,
                            [m for m in self.missiles
                             if m.alive and isinstance(m, SamMissile)])
        if now >= self._fix_next_t:
            self._fix_next_t = now + ELINT_FIX_PERIOD_S
            self._inject_elint_tracks(now)
            self._inject_emitter_contacts(now)   # M2-T1 passive-SIGINT picture

    # ------------------------------------------------------------------
    # M5: submarine warfare + ASW (acoustic domain)
    # ------------------------------------------------------------------

    def _step_subs(self, dt: float) -> None:
        """Advance every living sub's state machine and, on the tick a boat
        fires, spawn its Kalibr salvo + inject the launch-transient datum.

        BYTE-IDENTICAL DEFAULT: self.subs is empty with n_subs=0, so this whole
        method is a no-op (the loop never runs).  The boat reads ONLY its own
        sensor-honest prosecution belief (self._sub_threat) — NEVER truth."""
        now = self.sim_time
        for sub in self.subs:
            # Decay the per-sub prosecution belief (it forgets being heard).
            tid = sub.sub_id
            if tid in self._sub_threat:
                self._sub_threat[tid] = max(
                    0.0, self._sub_threat[tid] - SUB_THREAT_DECAY_PER_S * dt)
            if not sub.alive:
                continue
            threat = self._sub_threat.get(tid, 0.0)
            aim = sub.step(dt, threat_level=threat)
            if aim is not None:
                self._fire_kalibr_salvo(sub, aim)

    # ---------------------------------------------------- M5 #1 amphibious
    def _committed_craft(self) -> list:
        """Every craft of the landing force the player must clear: ALL alive
        transports (committed once built — sink them or they splash) + ALL alive
        LCACs.  A WORLD-OUTCOME tally (it may read sim truth, exactly like the
        defeated/victorious properties) — NOT an AI-brain read."""
        out = [t for t in self.transports if t.alive]
        out.extend(lc for lc in self.lcacs if lc.alive)
        return out

    def _step_amphibious(self, dt: float) -> None:
        """Step the amphibious layer + beachhead bookkeeping.

        BYTE-IDENTICAL DEFAULT: self.transports is empty with n_transports=0, so
        the transport loop never runs, no LCAC is ever splashed, the beachhead
        clock never starts (it only starts when an LCAC reaches the box), and
        _beachhead_lost stays False -> defeated is unchanged (bastion clause
        only).  The transports/LCACs themselves are stepped by the BASE step
        (they are in self.ships); this method owns ONLY the SPLASH event (a
        reached-launch-line transport disgorges its LCACs) and the beachhead
        countdown.  An LCAC splashed THIS tick joins self.ships + self.lcacs and
        is stepped on the NEXT base step (the established reactive convention)."""
        if not self.transports and not self.lcacs:
            return
        # SPLASH: any RUNning transport that crossed its launch line this tick
        # disgorges exactly LCAC_PER_TRANSPORT craft at its pos (a small seeded
        # fan-out from the [seed, 15] stream), then drifts dead.  Sinking a
        # transport BEFORE the line removes its embarked LCACs (they never spawn).
        for tr in self.transports:
            if not tr.alive:
                continue
            if tr.reached_launch_line():
                self._splash_lcacs(tr)
        # Beachhead clock: start it the instant the FIRST LCAC enters the box.
        if self._beachhead_left is None:
            if any(getattr(lc, "landed", False) and lc.alive
                   for lc in self.lcacs):
                self._beachhead_left = self._beachhead_grace_s
        else:
            # A landing is in progress.  If the player has cleared EVERY
            # committed craft the loss is CANCELLED (a real save): the clock
            # resets and the lose-flag can never trip.
            if not self._committed_craft():
                self._beachhead_left = None
            else:
                self._beachhead_left = max(0.0, self._beachhead_left - dt)
                if self._beachhead_left <= 0.0:
                    self._beachhead_lost = True

    def _splash_lcacs(self, tr) -> None:
        """Spawn the transport's embarked LCACs at its pos (with a small seeded
        scatter on the [seed, 15] stream) aimed at the LANDING_BOX, append them
        to self.ships (so they are visible + OBB-damaged + count for victory)
        and self.lcacs, then latch the transport SPLASHed (it never splashes
        twice and drifts dead)."""
        n = int(getattr(tr, "embarked_lcac", LCAC_PER_TRANSPORT))
        tx, tz = float(tr.pos[0]), float(tr.pos[2])
        for _ in range(n):
            # Seeded splash scatter (a few hundred m fan-out so the craft do not
            # stack on one pixel) — drawn from the world-owned [seed, 15] stream.
            sx = tx + float(self._amphib_rng.normal(0.0, 300.0))
            sz = tz + float(self._amphib_rng.normal(0.0, 300.0))
            lc = Lcac(f"lcac_{self._lcac_seq:03d}", (sx, sz),
                      self._landing_box_xz)
            self._lcac_seq += 1
            self.ships.append(lc)
            self.lcacs.append(lc)
        tr.mark_splashed()

    @property
    def beachhead_active(self) -> bool:
        """True while a beachhead grace clock is running (an LCAC has landed and
        not all committed craft are cleared yet).  False at n_transports=0."""
        return self._beachhead_left is not None

    @property
    def beachhead_left(self) -> float | None:
        """Seconds left on the beachhead grace clock, or None if no landing is
        in progress (the HUD reads this for the countdown — DEFERRED)."""
        return self._beachhead_left

    def _fire_kalibr_salvo(self, sub, aim) -> None:
        """Spawn the sub's Kalibr salvo at the SURVEYED base coords (a coarse
        known-installation belief + CEP, truth-free — like the GPS/INS
        Tomahawks), then inject the launch-transient back-plot datum.  The
        rounds are radar-gated StrikeMissiles (launch_warning=False); terminal
        acquisition reuses _refine_strike_aim so the base hit EMERGES from the
        CEP vs SEEKER_BASKET_M (physics-not-dice)."""
        tx, tz, _ = aim
        # Surveyed-coordinate CEP (a coarse fixed-installation belief): jitter
        # the aim with the sub stream so the salvo is deterministic per battle.
        cep = SUB_KALIBR_CEP_M
        tx += float(self._sub_rng.normal(0.0, cep))
        tz += float(self._sub_rng.normal(0.0, cep))
        ax, az, ay = self._refine_strike_aim(tx, tz)
        n = min(SUB_SALVO_SIZE, sub.kalibr_ammo)
        for _ in range(n):
            breach = sub.pos.copy()
            breach[1] = 0.0      # the round breaches the surface to fly
            m = StrikeMissile(
                KALIBR_PL, breach,
                np.array([0.0, KALIBR_PL.eject_speed, 0.0]),
                (ax, az), target_y=ay)
            m.launch_cinematic = False
            m.launch_platform = sub   # damage.py: never self-OBB-hit the launcher
            self.missiles.append(m)
            sub.kalibr_ammo -= 1
        # The launch-transient back-plot datum (the free always-on ASW fix).
        self._inject_launch_datum(sub)

    def _inject_launch_datum(self, sub) -> None:
        """A coarse subsurface DATUM at the boat's surface launch point ± error
        (error grows with the boat's range from the base — the back-plot is a
        cue, not a snipe), fading over BACKPLOT_DATUM_FADE_S.  Also sets the
        boat's sensor-honest prosecution belief HIGH so the SubCommander knows
        it was loud and lengthens its evade.  NO TRUTH LEAK: the datum carries
        error and is the LAUNCH point, never the boat's live post-launch pos."""
        now = self.sim_time
        lx, lz = float(sub.pos[0]), float(sub.pos[2])
        rng_m = float(np.hypot(lx - float(BASE_POS[0]),
                               lz - float(BASE_POS[2])))
        err = BACKPLOT_DATUM_ERR_FRAC * rng_m
        ex = lx + float(self._sub_rng.normal(0.0, err))
        ez = lz + float(self._sub_rng.normal(0.0, err))
        did = f"{sub.sub_id}_datum"
        self.sub_contacts[did] = dict(
            pos=np.array([ex, 0.0, ez], dtype=np.float64),
            quality=max(err, 1.0), kind="datum", last_heard=now,
            age=SUB_FIX_AGE_MAX_S, t_drop=now + BACKPLOT_DATUM_FADE_S,
            sub_id=sub.sub_id)
        # Sensor-honest: the boat WAS loud (it shot), so it believes it may be
        # localized — set HIGH (it lengthens its own evade; never a truth read).
        self._sub_threat[sub.sub_id] = SUB_THREAT_ON_DATUM

    def _step_acoustic_sensors(self) -> None:
        """Buoy listening + acoustic triangulation on their cadences (mirror of
        _step_recon_sensors).  No-op with no buoys / no subs (byte-identical
        default)."""
        if not self.subs or not self.sonobuoys:
            # Still age out stale subsurface contacts so a dropped fix clears.
            self._age_sub_contacts()
            return
        now = self.sim_time
        if now >= self._acoustic_next_t:
            self._acoustic_next_t = now + ACOUSTIC_LISTEN_PERIOD_S
            self.acoustic.update(self.subs, self.sonobuoys, sim_time=now)
        if now >= self._sub_fix_next_t:
            self._sub_fix_next_t = now + ACOUSTIC_FIX_PERIOD_S
            self._inject_sub_track(now)
        self._age_sub_contacts()

    def _inject_sub_track(self, now: float) -> None:
        """Actionable acoustic cross-fixes -> subsurface tracks in the player
        picture (mirror of _inject_elint_tracks, in the acoustic domain).  Gates:
        the fix must be actionable, the sub heard within SUB_FRESH_S.  The fix
        carries the TRIANGULATED est_pos (the buoy belief) — NEVER the sub's
        truth pos.  Localizing the boat also raises its prosecution belief."""
        for sub in self.subs:
            if not sub.alive:
                continue
            sid = sub.sub_id
            heard = self.acoustic.last_heard(sid)
            if heard is None or now - heard > SUB_FRESH_S:
                continue
            quality = self.acoustic.fix_quality(sid)
            if quality >= ACOUSTIC_FIX_ACTIONABLE_M:
                continue
            est = self.acoustic.est_pos(sid)
            if est is None:
                continue
            age = SUB_FIX_AGE_MAX_S * quality / ACOUSTIC_FIX_ACTIONABLE_M
            self.sub_contacts[sid] = dict(
                pos=est.copy(), quality=quality, kind="sub", last_heard=now,
                age=age, t_drop=now + SUB_FRESH_S, sub_id=sid)
            # The boat is being prosecuted (a buoy cross-fixed it): raise its
            # belief so it evades — but only UP TO the localize level (a datum
            # is louder/scarier).  Sensor-honest: set because buoys heard it.
            self._sub_threat[sid] = max(self._sub_threat.get(sid, 0.0),
                                        SUB_THREAT_ON_FIX)

    def _age_sub_contacts(self) -> None:
        """Drop subsurface contacts past their fade window (the boat ran)."""
        now = self.sim_time
        for cid in [c for c, v in self.sub_contacts.items()
                    if now >= v.get("t_drop", 0.0)]:
            del self.sub_contacts[cid]

    def place_sonobuoy(self, xz):
        """Player tasking verb: drop a passive sonobuoy at world point ``xz``
        (a map-clicked (x, z) or (x, y, z)).  Consumes one from the finite
        stock; returns the buoy position, or None when stock is empty (refuses
        at 0).  BYTE-IDENTICAL DEFAULT: n_sonobuoys=0 -> stock 0 -> always
        None."""
        if self._sonobuoy_stock <= 0:
            return None
        bx = float(xz[0])
        bz = float(xz[-1])
        buoy = np.array([bx, -15.0, bz], dtype=np.float64)
        self.sonobuoys.append(buoy)
        self._sonobuoy_stock -= 1
        return buoy

    @property
    def sonobuoys_left(self) -> int:
        return self._sonobuoy_stock

    def launch_asw(self, track_id=None):
        """Player ASW prosecution: fire a round at a LOCALIZED subsurface track
        (a buoy cross-fix or a fresh launch datum) — NEVER blind.  Returns the
        AswRound, or None when there is no subsurface track or no ASW ammo.

        Physics-not-dice: the round flies to the FIX (the believed pos, not
        truth); whether it kills emerges from the fix quality vs the acoustic
        seeker basket inside AswRound (sim/asw.py).  is_hostile=False so it can
        never damage player structures."""
        if self._asw_ammo <= 0:
            return None
        # Resolve the target subsurface track: the named one, else the freshest
        # (smallest quality / youngest) localized contact.
        contact = None
        if track_id is not None:
            contact = self.sub_contacts.get(track_id)
        if contact is None:
            live = [v for v in self.sub_contacts.values()]
            if live:
                contact = min(live, key=lambda v: v.get("quality", float("inf")))
        if contact is None:
            return None      # no fix -> refuse (can't shoot blind)
        from sim.asw import AswRound
        fix_xz = (float(contact["pos"][0]), float(contact["pos"][2]))
        quality = float(contact.get("quality", float("inf")))
        target_sub = self._resolve_sub(contact.get("sub_id"))
        rnd = AswRound(np.array(BASE_POS, dtype=np.float64),
                       fix_xz, fix_quality=quality, target_sub=target_sub)
        self.asw_rounds.append(rnd)
        self._asw_ammo -= 1
        return rnd

    @property
    def asw_ammo_left(self) -> int:
        return self._asw_ammo

    def _resolve_sub(self, sub_id):
        """Map a subsurface contact's sub_id back to the live Submarine (the ASW
        round's terminal basket checks the fix vs THIS boat's truth — the kill
        emerges from fix quality vs basket, the round never reads truth to
        guide)."""
        if sub_id is None:
            return None
        for sub in self.subs:
            if sub.sub_id == sub_id and sub.alive:
                return sub
        return None

    def _step_asw_rounds(self, dt: float) -> None:
        """Fly the player ASW rounds; a basket-acquire calls Submarine.kill().
        No-op when self.asw_rounds is empty (byte-identical default)."""
        if not self.asw_rounds:
            return
        for rnd in self.asw_rounds:
            rnd.update(dt)
        self.asw_rounds = [r for r in self.asw_rounds if r.alive]

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
        by_emitter = {s.radar.radar_id: s for s in self.ships
                      if getattr(s, "radar", None) is not None}
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
            # M5 #1: a radar-less Transport/LCAC is not an emitter — it can never
            # be ARM-targeted (no mount to home on).  Skip it (no-op at count 0).
            if getattr(s, "radar", None) is None:
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

    def _check_flagship_cec(self) -> None:
        """M5 CEC degradation on the flagship alive->dead edge.

        Two effects, both SENSOR-honest (no player-truth read):
          1. The remote CUE evaporates — handled passively in
             _enemy_cue_radars (the dead hub's radar fails the alive gate), so
             escorts already fall back to own-SPY-1.  Nothing to do here.
          2. COHESION drops — the surviving escorts' effective TRACK_FORM_S
             rises (FLAGSHIP_DEAD_COHESION_FACTOR), so each must hold a target
             LONGER on its own radar before a fire-control track forms.  We
             raise the per-unit ``_track_form_s`` knob the controller reads via
             getattr; the carrier (silent, no offense) is skipped.

        Latched on the edge so the bump + the 'datalink_degraded' event fire
        EXACTLY once.  A None flagship (byte-identical default) never enters."""
        flagship = getattr(self, "flagship", None)
        if flagship is None or self._datalink_degraded:
            return
        if self._flagship_was_alive and not flagship.alive:
            self._datalink_degraded = True
            base = TRACK_FORM_S * FLAGSHIP_DEAD_COHESION_FACTOR
            for s in self.ships:
                if s is flagship or isinstance(s, Carrier):
                    continue
                # Raise (never lower) the escort's track-formation delay.
                s._track_form_s = max(
                    getattr(s, "_track_form_s", TRACK_FORM_S), base)
            self.events.append(("datalink_degraded", flagship.pos.copy()))
        self._flagship_was_alive = flagship.alive

    def _enemy_cue_radars(self):
        """Datalink cueing sources beyond own-ship SPY-1 (spec section 3:
        "enemy ships rely on their own radar or AWACS cueing"): the live
        AWACS radar, any live enemy ground radars, AND (M5) the live FLAGSHIP
        SPY-1 — the CEC datalink hub.  They join the enemy picture, cueing the
        escorts so an escort can form an SM-2 track on a target the flagship
        holds before its OWN SPY-1 has line of sight.

        SENSOR-honest flagship degradation: when the flagship SINKS its radar
        goes dark (ShipDefense.step clears radar.alive on a dead ship) and the
        ``r.alive`` gate below DROPS it from the cue set automatically — the
        escorts lose the remote cue and fall back to own-SPY-1.  This never
        reads player truth; it only removes a dead emitter from the datalink.

        Resolved lazily — the defense controller is built before the AWACS and
        before _spawn_enemy_radars in __init__."""
        cues = []
        cues.extend(a.radar for a in getattr(self, "awacs_units", [])
                    if a.alive)
        for r in getattr(self, "_enemy_ground_radars", []):
            if r.alive:
                cues.append(r)
        # M5 CEC hub: the flagship's own SPY-1, only while the hull lives AND
        # the radar is up.  A dead/silent flagship contributes nothing — the
        # remote cue evaporates exactly as the doctrine demands.
        flagship = getattr(self, "flagship", None)
        if (flagship is not None and flagship.alive
                and flagship.radar.alive and flagship.radar.emitting):
            cues.append(flagship.radar)
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
        legacy aircraft list stays empty in COMBAT.

        Hostile STRIKE ROUNDS (Tomahawk/JASSM/HARM/Kalibr) live in
        self.missiles keyed by the same aircraft_id their track carries —
        this docstring always promised them as S-300 targets, but the
        lookup never searched the missile list, so launch_sam returned a
        silent None for EVERY anti-missile shot (live playtest 2026-07-03:
        'I can't intercept the missiles').  Anti-cruise-missile defense is
        the real S-300's bread and butter; now it resolves."""
        ent = super()._find_air_entity(aircraft_id)
        if ent is not None:
            return ent
        ent = next((e for e in self.enemy_air
                    if e.aircraft_id == aircraft_id), None)
        if ent is not None:
            return ent
        return next((m for m in self.missiles
                     if m.alive and getattr(m, "is_hostile", False)
                     and getattr(m, "aircraft_id", None) == aircraft_id),
                    None)

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
        # M5 #1: a radar-less Transport/LCAC is not a sensor (radar is None) —
        # skip it (no-op at n_transports=0 -> byte-identical).
        radars = [s.radar for s in self.ships
                  if s.alive and not isinstance(s, Carrier)
                  and getattr(s, "radar", None) is not None]
        radars.extend(a.radar for a in getattr(self, "awacs_units", [])
                      if a.alive)
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
        any_awacs_alive = any(a.alive for a in getattr(self, "awacs_units", []))
        heard = (radar.alive and radar.emitting
                 and (any(s.alive for s in self.ships)
                      or any_awacs_alive
                      or any(f.alive for f in self._fighter_list)))
        pic.update_emitter(radar.radar_id, radar.pos, heard, dt_s, now)
        if heard:
            # Re-illumination is EVIDENCE: a radar believed killed by a
            # HARM package that is heard again flips back to alive.
            pic.mark_emitter_alive(radar.radar_id)

        # M5 #3 HONEST COST: every live, emitting CBR mast is a PLAYER emitter the
        # enemy ESM can localize (and the commander can HARM) — the SAME accrual
        # as the radar station above (functional-ESM model: no range gate against
        # a search set; gated only on the emitter being alive + emitting and an
        # enemy platform surviving to hear it).  Killing the CBR Structure clears
        # its radar.alive (the wrapper's on_destroyed), so ``heard`` goes False
        # and the fix DECAYS — the node drops out of the picture with its mast.
        # At n_cbr=0 _cbr_radars is empty -> this loop is a no-op (byte-identical).
        any_enemy_alive = (any(s.alive for s in self.ships)
                           or any_awacs_alive
                           or any(f.alive for f in self._fighter_list))
        for cbr in self._cbr_radars:
            cbr_heard = (cbr.alive and cbr.emitting and any_enemy_alive)
            pic.update_emitter(cbr.radar_id, cbr.pos, cbr_heard, dt_s, now)
            if cbr_heard:
                pic.mark_emitter_alive(cbr.radar_id)

        # M5 #5 ESM DECOY EMITTERS: each live, emitting decoy is a PLAYER emitter
        # the enemy ESM hears on the SAME functional-ESM accrual as the radar
        # station + CBR (no range gate; gated on alive + emitting + an enemy
        # platform surviving to hear it).  A matured fix is a real, located
        # EmitterIntel the EXISTING _doctrine_blind will send a HARM package at
        # (the bait is wasted) — NO commander decision code is touched, the AI is
        # fooled only because its sensors genuinely heard the decoy.  Killing the
        # decoy Structure clears decoy.alive (the wrapper's on_destroyed) -> heard
        # goes False and the fix DECAYS.  At n_decoys=0 _decoy_emitters is empty ->
        # this loop is a no-op (byte-identical default battle).
        for d in self._decoy_emitters:
            d_heard = (d.alive and d.emitting and any_enemy_alive)
            pic.update_emitter(d.radar_id, d.pos, d_heard, dt_s, now)
            if d_heard:
                pic.mark_emitter_alive(d.radar_id)

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
            # M5 #5 corner-reflector bias hook: remember whether this launch was
            # ALREADY back-plotted, then run the normal enemy back-plot.  If a
            # REAL fix was planted THIS step (the enemy genuinely localized the
            # launch) AND a live reflector lies within its influence of the honest
            # plot, mirror an EXTRA biased BackPlotEntry (sim.decoys.biased_back_
            # plot -> the SHARED back_plot_surface path) — a real false-return
            # geometry, never a miss flag.  Gated on _corner_reflectors so
            # n_corner_reflectors=0 leaves the back-plot pipeline byte-identical.
            reflect = bool(self._corner_reflectors)
            had_bp = reflect and any(
                bp.track_id == rec["track_id"] for bp in pic._back_plots)
            self.commander.process_missile_track(
                rec["track_id"], m.pos, m.vel, now, rec["first_t"],
                rec["first_pos"], rec["first_vel"], rec["det_pos"],
                kind=getattr(getattr(m, "weapon", None), "weapon_id", None))
            if reflect and not had_bp and any(
                    bp.track_id == rec["track_id"] for bp in pic._back_plots):
                self._inject_reflector_backplots(rec, now)
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
            # M5 #1: a radar-less Transport/LCAC has no mount to un-silence; skip
            # it (no-op at n_transports=0).
            if getattr(ship, "radar", None) is None:
                continue
            if (not ship.radar.emitting
                    and self._drone_track_in_sector(ship, now)):
                ship.radar.emitting = True

    # ------------------------------------------------------- order execution

    def _execute_commander_order(self, order: dict) -> None:
        """Route one commander order dict (schema: sim/commander.py) onto
        the owning entity/system."""
        kind = order["type"]
        if kind == "transport_run":
            # M5 #1: release every loitering transport into its beeline RUN.
            # Idempotent (a running/splashed transport is unaffected); a no-op
            # when none are built.  The commander decided this from its SENSOR
            # picture only (sim/commander._doctrine_amphibious) — no truth read.
            for tr in self.transports:
                tr.begin_run()
        elif kind == "vector_to_drone":
            self._vector_fighter_to_drone(order)
        elif kind == "awacs_flee":
            if self.awacs is not None and self.awacs.alive:
                self.awacs.flee(order["threat_pos"])
                # EMCON: a fleeing AWACS runs SILENT — emitting while bugging
                # out only refines the player's ELINT fix and feeds a
                # radiation-homing terminal; the fleet leans on ship/ground
                # cueing during the silent window (Phase 8 smarter AWACS).
                self.awacs.radar.emitting = False
        elif kind == "awacs_resume":
            if self.awacs is not None and self.awacs.alive:
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
                # degradation lives in sim/strike.py.  Resolve the order's
                # emitter id to the live emitter the commander chose to blind
                # (the radar station, a CBR mast, or an ESM DECOY) so the round
                # physically chases THAT emission — a HARM drawn onto a decoy must
                # fly at the decoy, not the real radar (else the M5 #5 bait is
                # inert in real play).  Defaults to the radar station, so with no
                # CBR/decoy built the only emitter id resolves to radar_station ->
                # BYTE-IDENTICAL to the legacy hardcode.  One child rng per jet
                # seeds the deterministic miss offsets.
                f.execute_order({
                    "type": "sead",
                    "target_radar": self._emitter_by_id(order["target_id"]),
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
        # M5: GroundAttack hulls own the deep TLAM bank — drain THOSE cells
        # FIRST so the dedicated land-attack ship spends its magazine before
        # the general/AAW escorts dip into their token self-defense TLAM.  A
        # stable sort keyed on (NOT ground-attack) preserves the legacy ship
        # order within each group, so with NO ground-attack ships (the
        # byte-identical default) the iteration order is UNCHANGED.
        ordered = sorted(
            self.ships,
            key=lambda s: 0 if getattr(s, "ship_class_role", None)
            == "ground_attack" else 1)
        for ship in ordered:
            if isinstance(ship, Carrier):
                continue                     # carriers carry no TLAM
            # getattr guard: LCACs ride in self.ships but carry no TLAM bank
            # (a bare attribute read crashed the salvo mid-landing).
            while (len(rounds) < SALVO_SIZE and ship.alive
                   and getattr(ship, "tomahawk_ammo", 0) > 0):
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
            # NEWEST-first: a rearmed jet re-tasked while its previous
            # mission's rounds are still flying is in TWO open missions;
            # first-match booked the release to the OLD one, so the new
            # mission completed with released==0 and its HARM BDA
            # (mark_emitter_destroyed) never fired.
            rec = next((mi for mi in reversed(self._cmd_missions)
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
    def _bastion_lost(self) -> bool:
        """The legacy lose clause: every Bastion TEL structure is dead (no Oniks
        = no offense)."""
        return all(not s.alive for s in self.structures
                   if s.kind == "bastion_tel")

    @property
    def defeated(self) -> bool:
        """Spec 2.2 lose condition, NOW two orthogonal clauses ORed:
          (a) every Bastion TEL structure is dead (no Oniks = no offense); OR
          (b) M5 #1 BEACHHEAD: an LCAC reached the LANDING_BOX and the player
              did NOT clear ALL committed craft before the grace clock expired.
        BYTE-IDENTICAL DEFAULT: with n_transports=0 the beachhead clock never
        starts (no LCAC can reach the box), so _beachhead_lost is always False
        and defeated reduces to the bastion clause exactly (the regression).
        The sim keeps running so the player can watch; full end-screens come in
        the later UI pass."""
        return self._bastion_lost or self._beachhead_lost

    @property
    def defeat_cause(self):
        """Which lose clause tripped, for the HUD banner (DEFERRED wiring):
        'bastion' | 'beachhead' | None.  The bastion clause takes precedence if
        both happen to hold (losing the battery is the terminal state)."""
        if self._bastion_lost:
            return "bastion"
        if self._beachhead_lost:
            return "beachhead"
        return None

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
        # M5: ALL enemy subs must also be dead (the second lose-path: the player
        # MUST find + kill the boat).  BYTE-IDENTICAL DEFAULT: self.subs is empty
        # with n_subs=0, so this all() is vacuously True and victory is unchanged.
        if not all(not sub.alive for sub in getattr(self, "subs", [])):
            return False
        return True

    # ----------------------------------------------- M5 #4 SHOOT-AND-SCOOT
    #
    # The relocate mechanic is GENERIC over a "relocatable launcher" so the
    # Oniks Bastion, S-300, and Buk firing TELs reuse ONE implementation.  Each
    # descriptor in self._relocatable binds a launcher's LIVE pad position array
    # (the same object stored in the battery's _*_launcher_positions list — so
    # mutating it in place moves the renderer + structure source of truth), its
    # launch tubes, the per-tube mouth offsets (captured at build, so the tube
    # 'pos' can be recomputed from the moved pad — the load-bearing honesty
    # link), and the matching destructible Structure.  Relocate state defaults
    # to idle, so a battle that never calls request_relocate is byte-identical.

    def _build_relocatable_registry(self) -> list:
        """Pair every firing-TEL launcher with its tubes + Structure into one
        relocatable-launcher descriptor list.  Called once in __init__ AFTER all
        firing-TEL Structures exist.  The radar station / Pantsir / swarm pod /
        CBR are intentionally absent (fixed sites in v1).  Returns [] when no
        firing TEL is built (cannot happen — n_oniks/n_s300 floor at 1 — but the
        Buk slice is empty at n_buk=0, byte-identical)."""
        reg: list = []
        specs = (
            ("bastion_tel", self._oniks_launcher_positions, self._oniks_tubes,
             len(self._oniks_tubes) // max(1, len(self._oniks_launcher_positions))),
            ("s300_tel", self._s300_launcher_positions, self._s300_tubes,
             len(self._s300_tubes) // max(1, len(self._s300_launcher_positions))),
            ("buk_tel", self._buk_launcher_positions, self._buk_tubes,
             (len(self._buk_tubes) // max(1, len(self._buk_launcher_positions)))
             if self._buk_launcher_positions else 0),
        )
        structs_by_kind: dict[str, list] = {}
        for s in self.structures:
            structs_by_kind.setdefault(s.kind, []).append(s)
        for kind, positions, tubes, per in specs:
            kstructs = structs_by_kind.get(kind, [])
            for i, lpos in enumerate(positions):
                my_tubes = tubes[i * per:(i + 1) * per]
                # A Buk TEL carries its 9S36 fire-control radar ON the
                # vehicle: pair it into the descriptor so a relocate moves
                # the radar with the TEL (it used to stay at the old pad).
                radar = (self._buk_radars[i]
                         if kind == "buk_tel" and i < len(self._buk_radars)
                         else None)
                # Mouth offset of each tube from THIS launcher's current pad
                # (the pads are still the originals here, so the offset is exact;
                # re-pinning tube pos = moved pad + offset reproduces the geometry
                # at the new site — the moving-Structure honesty link).
                offsets = [np.asarray(t["pos"], dtype=np.float64) - lpos
                           for t in my_tubes]
                struct = kstructs[i] if i < len(kstructs) else None
                reg.append({
                    "kind": kind,
                    "platform": struct.structure_id if struct else f"{kind}_{i:02d}",
                    "pos": lpos,              # SAME ndarray as the battery list
                    "tubes": my_tubes,
                    "offsets": offsets,
                    "structure": struct,
                    "radar": radar,           # on-vehicle radar, or None
                    # relocate state — DEFAULT IDLE (byte-identical no-op)
                    "dest": None,             # (2,) target xz, or None
                    "committed": False,
                    "move_left_s": 0.0,
                })
        # A destroyed firing TEL must STOP FIRING: chain an on_destroyed onto
        # each descriptor's Structure marking its tube slice DEAD (and dropping
        # any loaded round — the canisters die with the vehicle).  Without
        # this, every enemy SEAD/back-plot strike on a TEL was cosmetic: the
        # rubble kept firing at full rate.  Chains (never replaces) the
        # existing callback — the Buk TEL's 9S36 radar kill stays live.
        for d in reg:
            struct = d["structure"]
            if struct is None:
                continue
            prev = struct.on_destroyed

            def _tubes_dead(s, _d=d, _prev=prev):
                for t in _d["tubes"]:
                    t["dead"] = True
                    t["loaded"] = False
                if _prev is not None:
                    _prev(s)

            struct.on_destroyed = _tubes_dead
        return reg

    def _relocatable_for(self, platform):
        """Resolve a relocate descriptor by platform id (the Structure id, e.g.
        'bastion_tel_00') or by passing the Structure object itself.  Returns the
        descriptor dict or None."""
        pid = getattr(platform, "structure_id", platform)
        for d in self._relocatable:
            if d["platform"] == pid or d["structure"] is platform:
                return d
        return None

    def _launcher_committed(self, tube) -> bool:
        """True while the tube is UNAVAILABLE: its launcher is COMMITTED to a
        relocate (driving or in the emplace/displace dwell) — OR the tube is
        DEAD because its TEL Structure was destroyed (the registry's
        on_destroyed marks the slice).  Every launch gate / armed property in
        all three batteries routes through this predicate, so a killed TEL
        stops firing everywhere at once.  Both flags are absent until set, so
        the default battle is byte-identical."""
        return bool(tube.get("committed", False)) or bool(tube.get("dead",
                                                                   False))

    def request_relocate(self, platform, dest_xz) -> bool:
        """Order a firing TEL to SHOOT-AND-SCOOT to ``dest_xz`` (a map xz).

        PLAYER ACTION (no config field).  On success the launcher is COMMITTED
        immediately — its arm gate goes False and any launch is refused — and a
        deterministic constant-speed drive (RELOCATE_SPEED_MPS) plus a fixed
        emplace/displace dwell (RELOCATE_SETUP_S each end) begins.  The pad,
        every tube, and the Structure stay at the OLD site (so the enemy's stale
        back-plot still points there) until ARRIVAL, when _step_relocations
        re-pins all of them to the new pad and clears the commit (re-armed if
        ammo/reload allow).  Reload timers KEEP RUNNING while driving (the tube
        re-cocks en route).

        Returns False (no-op) when the platform is unknown, already committed (a
        2nd request is refused), or dead — and True when the relocate is booked.
        DETERMINISM: no RNG, no wall-clock (the [seed,11] tag stays reserved)."""
        d = self._relocatable_for(platform)
        if d is None:
            return False
        if d["committed"]:
            return False                      # refuse a 2nd request mid-move
        struct = d["structure"]
        if struct is not None and not struct.alive:
            return False                      # a dead TEL cannot drive
        dest = np.asarray(dest_xz, dtype=np.float64).reshape(-1)[:2]
        # Drive distance is ground range from the CURRENT pad to the destination.
        dx = float(dest[0]) - float(d["pos"][0])
        dz = float(dest[1]) - float(d["pos"][2])
        drive_s = float(np.hypot(dx, dz)) / RELOCATE_SPEED_MPS
        d["dest"] = dest.copy()
        d["committed"] = True
        d["move_left_s"] = 2.0 * RELOCATE_SETUP_S + drive_s
        for t in d["tubes"]:
            t["committed"] = True             # disarm this launcher's tubes
        return True

    def _step_relocations(self, dt: float) -> None:
        """Advance every committed relocate; re-pin the pad, EVERY tube, and the
        Structure to the new pad on arrival.  A PURE NO-OP while every launcher
        is idle (committed=False) — so the default battle is byte-identical.

        On arrival (move_left_s reaches 0): set the launcher pad ndarray to the
        destination at the destination's terrain height, recompute each tube's
        pos = pad + its baked mouth offset, move the Structure .pos (its OBB
        rebuilds from .pos PER QUERY in sim/bases.py, so the damage sweep follows
        the move with no desync), clear the commit, and re-arm the tubes."""
        for d in self._relocatable:
            if not d["committed"]:
                continue                      # idle launcher: nothing to do
            d["move_left_s"] = max(0.0, d["move_left_s"] - dt)
            if d["move_left_s"] > 0.0:
                continue                      # still displacing / driving / emplacing
            # Killed mid-drive: the wreck stays where it was hit — never move
            # a dead Structure to the new pad or re-arm its (dead) tubes.
            struct = d["structure"]
            if struct is not None and not struct.alive:
                for t in d["tubes"]:
                    t["committed"] = False    # dead flag still blocks the gates
                d["committed"] = False
                d["dest"] = None
                continue
            # --- ARRIVAL: snap pad + tubes + Structure to the new pad ---
            dest = d["dest"]
            ny = float(terrain_height_scalar(float(dest[0]), float(dest[1])))
            pad = d["pos"]
            pad[0] = float(dest[0])
            pad[1] = ny
            pad[2] = float(dest[1])
            for t, off in zip(d["tubes"], d["offsets"]):
                t["pos"] = pad + off          # recompute mouth from the moved pad
                t["committed"] = False        # re-arm this launcher's tube
            if struct is not None:
                struct.pos = pad.copy()       # OBB recomputes from .pos per query
            radar = d.get("radar")
            if radar is not None and getattr(radar, "alive", True):
                # The 9S36 rides ON the Buk TEL: move it with the vehicle so
                # its coverage (and the emitter the enemy back-plots) tracks
                # the new pad instead of haunting the old one.
                radar.pos[0] = pad[0]
                radar.pos[1] = pad[1]
                radar.pos[2] = pad[2]
            d["committed"] = False
            d["dest"] = None

    @property
    def launcher_armed(self) -> bool:
        """Salvo gate: armed while ANY Oniks tube is loaded and re-cocked, and
        the battery is not yet rubble (every bastion_tel structure dead).  M5 #4:
        a tube whose launcher is COMMITTED to a relocate is NOT available (the
        'and not committed' clause — vacuously True while idle, byte-identical)."""
        if self.defeated:
            return False
        return any(t["loaded"] and t["reload_left"] <= 0.0
                   and not self._launcher_committed(t)
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
        if weapon_id == "asbm":
            # The Bastion-K ASBM is a SamMissile subclass on a SHIP contact
            # estimate (NOT a Missile on a surface point), so it has its own
            # spawn path: resolve the nearest tracked SHIP to the aim point and
            # delegate to launch_asbm (fog-honest: the round flies the stale
            # ContactBoard picture; only the terminal MaRV sees truth).
            tp = np.asarray(target_point, dtype=np.float64)
            ship_id = self._nearest_ship_contact(tp)
            return self.launch_asbm(ship_id)
        if weapon_id == "zircon":
            if self._zircon_ammo is None or self._zircon_ammo <= 0:
                return None
            weapon = ZIRCON
        else:
            weapon = ONIKS
        # M5 #4: a tube whose launcher is COMMITTED to a relocate cannot fire
        # (the 'and not committed' clause — vacuously True while idle).
        tube = next((t for t in self._oniks_tubes
                     if t["loaded"] and t["reload_left"] <= 0.0
                     and not self._launcher_committed(t)), None)
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

    def _nearest_ship_contact(self, aim_pos):
        """The ship contact id whose dead-reckoned estimate is nearest the aim
        point (ground range), or None when no SHIP track is held.  FOG-HONEST:
        reads only the ContactBoard picture (never world.ships truth), so the
        ASBM is aimed at what the player actually SEES — a salvo on a stale
        ship track is aimed at the stale estimate, which is exactly the miss
        the physics-not-dice contract turns on."""
        import math as _math
        ax, az = float(aim_pos[0]), float(aim_pos[2])
        best_id, best_d = None, float("inf")
        for cid, trk in self.contacts.tracks.items():
            if trk.get("is_air"):
                continue                      # ships only (ASBM is anti-ship)
            est = self.contacts.estimated_pos(cid, self.sim_time)
            d = _math.hypot(float(est[0]) - ax, float(est[2]) - az)
            if d < best_d:
                best_id, best_d = cid, d
        return best_id

    def launch_asbm(self, ship_id):
        """Fire one Bastion-K ASBM at the SHIP contact ``ship_id`` (M4-A).

        The lofted quasi-ballistic top-attack anti-ship round: it flies
        BOOST/MIDCOURSE on the dead-reckoned ContactBoard estimate (stale
        picture, fog-honest) and only the terminal MaRV seeker (sim/asbm.py)
        sees truth — so a shot launched on a frozen/stale track MISSES a ship
        that moved away (physics, not dice).  Fires from the same Bastion TEL
        tube as the Oniks/Zircon and draws from the scarce ``_asbm_ammo`` pool.

        Returns the AsbmMissile, or None if any gate fails:
          * defeated / empty pool (default config asbm_ammo=0 -> never offered);
          * ``ship_id`` is None or not a live SHIP track (the FOG GATE — the
            player may only target a ship the sensor picture HOLDS);
          * the track does not resolve to a live Ship entity (it just sank);
          * no Bastion tube is ready.
        """
        if self.defeated:
            return None
        if self._asbm_ammo is None or self._asbm_ammo <= 0:
            return None
        track = self.contacts.tracks.get(ship_id)
        if track is None or track.get("is_air"):
            return None
        target = next((s for s in self.ships
                       if s.ship_id == ship_id and s.alive), None)
        if target is None:
            return None
        # M5 #4: a relocating Bastion TEL cannot fire its ASBM either.
        tube = next((t for t in self._oniks_tubes
                     if t["loaded"] and t["reload_left"] <= 0.0
                     and not self._launcher_committed(t)), None)
        if tube is None:
            return None
        m = AsbmMissile(BASTION_K, tube["pos"].copy(), target,
                        contact_estimate_fn=self._contact_estimate(ship_id))
        # Player round (fog-of-war / camera-cycle gates skip only hostile rounds).
        m.is_hostile = False
        self.oniks_fired += 1
        self.missiles.append(m)
        tube["loaded"] = False
        tube["reload_left"] = self._oniks_tube_reload_s
        self._asbm_ammo -= 1
        return m

    # ----------------------------------------------------- M4-B swarm pod
    def _build_swarm_pods(self, n: int, cells_per_pod: int,
                          mag_reload_s: float) -> None:
        """N loitering-swarm pods set back from the Oniks battery, sharing one
        cell magazine (_swarm_cells, capacity _swarm_mag_cap).  Sets
        _swarm_pod_positions (used by the destructible structures + renderer).
        DEFAULT n=0 -> NO pod, _swarm_cells=0, launch_swarm returns None: the
        out-of-the-box battle is byte-identical (the round never spawns)."""
        base = np.array(BASE_POS, dtype=np.float64)
        off = np.asarray(SWARM_POD_OFFSET, dtype=np.float64)
        n = max(0, int(n))
        self._swarm_pod_positions = []
        for i in range(n):
            dx = (i - (n - 1) * 0.5) * SWARM_POD_SPACING_M
            self._swarm_pod_positions.append(base + off + np.array([dx, 0.0, 0.0]))
        self._swarm_cell_cap_per_pod = max(0, int(cells_per_pod))
        cap = n * self._swarm_cell_cap_per_pod
        self._swarm_cells = cap                  # cells loaded and ready
        self._swarm_mag_cap = cap
        self._swarm_mag_reload_s = float(mag_reload_s)
        self._swarm_mag_reload_left = 0.0

    def launch_swarm(self, profile, aim_point, waypoints=(), sync=True):
        """Bundle-fire EVERY ready swarm cell at ``aim_point`` for a coordinated
        time-on-target (M4-B).  One Missile(SWARM, ...) per ready cell, fanned
        across the launch front so the per-round path lengths differ; the shared
        T and per-round commanded GROUND speed come from
        sim/swarm.compute_swarm_speeds (pure math, deterministic), and each
        round's weave is seeded by its salvo ordinal so the bundle does not
        formate.  The cell magazine is decremented by N; the empty pool then
        runs the config-driven refill timer.

        ``sync`` True  -> the per-round commanded speeds self-adjust so the
                          rounds arrive simultaneously (the saturation mode);
                 False -> every round runs at v_max (a plain MAX-speed bundle,
                          no time-on-target — the trickle/compare mode).

        Returns the list of spawned rounds, or None when no cell is ready
        (default config swarm pods 0 -> always None: byte-identical battle).
        """
        if self.defeated:
            return None
        n = int(getattr(self, "_swarm_cells", 0) or 0)
        if n <= 0:
            return None
        base = np.array(BASE_POS, dtype=np.float64)
        tp = np.asarray(aim_point, dtype=np.float64)
        route_tail = [(float(x), float(z)) for (x, z) in waypoints]
        route_tail.append((float(tp[0]), float(tp[2])))
        # Each round fans out to its OWN lateral spread waypoint roughly a third
        # of the way to the aim point (the realistic "spread the attack axes"
        # swarm geometry: multiple bearings saturate the point defense), then
        # converges on the shared route tail.  The outer rounds fly a measurably
        # LONGER arc than the inner ones, so the time-on-target math has real
        # path-length differences to equalize — the inner rounds DAWDLE while
        # the outer ones run near v_max so the whole bundle arrives together.
        # ALL rounds share ONE launch point (the pod front centre).  The fan is
        # synthesised purely via the per-round spread WAYPOINTS below, not by
        # spawning each round from its own pod — so SWARM_POD_SPACING_M and the
        # _swarm_pod_positions list are render/destructibility-only (the visible
        # pods sit side by side; every round emerges from this shared XZ).  This
        # keeps the time-on-target math self-consistent: compute_swarm_speeds
        # takes a single launch_xz and the path lengths are measured from it.
        launch_xz = (float(base[0]),
                     float(base[2] + SWARM_POD_OFFSET[2]))
        first_tail = route_tail[0]
        # The lateral axis is perpendicular to the launch -> first-tail bearing.
        dx = first_tail[0] - launch_xz[0]
        dz = first_tail[1] - launch_xz[1]
        d = float(np.hypot(dx, dz)) or 1.0
        perp = (-dz / d, dx / d)               # right-hand horizontal perp
        half_width = min(SWARM_FAN_MAX_HALF_WIDTH_M, d * SWARM_FAN_FRAC)
        # Spread waypoint sits SWARM_FAN_SPREAD_FRAC of the way out toward the
        # first tail point, offset laterally per round (the attack-axis spread).
        sf = SWARM_FAN_SPREAD_FRAC
        spread_base = (launch_xz[0] + dx * sf, launch_xz[1] + dz * sf)
        per_round_routes = []
        for i in range(n):
            frac = 0.0 if n == 1 else (-1.0 + 2.0 * i / (n - 1))
            off = frac * half_width
            spread = (spread_base[0] + perp[0] * off,
                      spread_base[1] + perp[1] * off)
            per_round_routes.append([spread, *route_tail])
        v_max = SWARM.cruise_mach_hi * 340.0
        v_min = SWARM.cruise_mach_lo * 340.0
        rounds = []
        if sync:
            # ONE shared time-on-target T across the whole fan via the pure
            # compute_swarm_speeds (deterministic, no RNG / wall-clock).
            speeds = compute_swarm_speeds(launch_xz, per_round_routes, v_max,
                                          margin=8.0, v_min=v_min)
        else:
            speeds = [v_max] * n
        # Spawn at the launcher AGL the rest of the codebase uses
        # (terrain_height_scalar AT the spawn XZ, cf. lines 534/560/663/884):
        # base[1] is the terrain height under BASE_POS, but the pod front sits
        # SWARM_POD_OFFSET[2] back where the terrain is ~1.3 m HIGHER, so a
        # round spawned at base[1] starts underground and goes PH_DEAD on
        # frame 1.  Evaluating terrain at launch_xz puts it on the surface.
        spawn_y = float(terrain_height_scalar(launch_xz[0], launch_xz[1]))
        for i in range(n):
            pos = np.array([launch_xz[0], spawn_y, launch_xz[1]],
                           dtype=np.float64)
            # The round's own waypoints: its lateral spread point, then the
            # shared player waypoints (the aim point is the Missile target).
            spread = per_round_routes[i][0]
            rnd_wps = (spread,) + tuple(waypoints)
            fx, fz = rnd_wps[0]
            heading = float(np.arctan2(fx - pos[0], fz - pos[2]))
            m = Missile(SWARM, pos, heading, profile, tp,
                        waypoints=rnd_wps, salvo=self._swarm_fired)
            m.is_hostile = False
            m._commanded_speed = float(speeds[i])
            self._swarm_fired += 1
            self.missiles.append(m)
            rounds.append(m)
        self._swarm_cells = 0                      # the whole bundle launched
        if self._swarm_mag_cap and self._swarm_mag_cap > 0:
            self._swarm_mag_reload_left = self._swarm_mag_reload_s
        return rounds

    def _step_swarm_pod(self, dt: float) -> None:
        """Cell-magazine refill: once a bundle empties the pool the reload timer
        runs and refills it to capacity (renewable, rate-limited — the same
        mechanic as the Oniks magazine).  No-op when no pod is configured."""
        if getattr(self, "_swarm_mag_cap", 0) <= 0:
            return
        if self._swarm_cells <= 0 and self._swarm_mag_reload_left > 0.0:
            self._swarm_mag_reload_left = max(
                0.0, self._swarm_mag_reload_left - dt)
            if self._swarm_mag_reload_left <= 0.0:
                self._swarm_cells = self._swarm_mag_cap

    def _step_oniks_tubes(self, dt: float) -> None:
        """Per-tube reload: a fired tube re-cocks over _oniks_tube_reload_s,
        then pulls a round from the magazine reserve (rounds beyond the
        currently-loaded tubes). A re-cocked-but-empty tube also reloads the
        moment the magazine refills, so renewable ammo keeps feeding the
        battery (mirrors the single-launcher refill)."""
        for t in self._oniks_tubes:
            if t["reload_left"] > 0.0:
                t["reload_left"] = max(0.0, t["reload_left"] - dt)
            if (not t["loaded"] and t["reload_left"] <= 0.0
                    and not t.get("dead", False)):
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
        and at least one S-300 tube re-cocked.  M5 #4: a tube whose launcher is
        COMMITTED to a relocate is excluded (vacuously True while idle)."""
        if self.sam_ammo <= 0:
            return False
        if self._s300_48n6_mag_reload_left > 0.0:
            return False
        return any(t["reload_left"] <= 0.0 and not self._launcher_committed(t)
                   for t in self._s300_tubes)

    @property
    def sam_40n6_launcher_armed(self) -> bool:
        """40N6 salvo gate: a 40N6 round in the pool, no refill pending, and a
        tube re-cocked (and the launcher not relocate-committed — M5 #4)."""
        if self.sam_ammo_40n6 <= 0:
            return False
        if self._s300_40n6_mag_reload_left > 0.0:
            return False
        return any(t["reload_left"] <= 0.0 and not self._launcher_committed(t)
                   for t in self._s300_tubes)

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
        # M5 #4: skip a tube whose launcher is relocate-committed.
        tube = next((t for t in self._s300_tubes
                     if t["reload_left"] <= 0.0
                     and not self._launcher_committed(t)), None)
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

    # ----------------------------------------------------- M5 Buk mid-SAM battery
    #
    # The medium-range gap-filler (Pantsir 20 km <-> S-300 150 km).  EXACT mirror
    # of the S-300 salvo battery: N TELs side by side at BUK_SITE_XZ, each with a
    # 6-tube block; the 9M317 / 9M338 pools are shared across all tubes; each tube
    # re-cocks on its own timer (salvo, no firerate gate).  The 9S36 fire-control
    # radar of each TEL JOINS self.radar_net (like the Pantsir radar) so the
    # battery honestly extends the gated AIR picture over the seam.  With n_buk=0
    # NOTHING is built (byte-identical default battle).
    #
    # FOG / NO CHEAT: launch_buk reads world.contacts.tracks (is_air) only — never
    # truth; the SamMissile then guides on the gated ContactBoard dead-reckoned
    # estimate and uses truth ONLY at the terminal fuse (identical to the S-300).

    def _build_buk_battery(self, n: int) -> None:
        """Build N Buk TELs side by side at the Buk site (n=0 -> nothing).  Sets
        _buk_launcher_positions / _buk_tubes / _buk_radars, seeds the shared
        9M317 / 9M338 pools, and appends each TEL's 9S36 Radar to radar_net."""
        if n <= 0:
            return
        bx, bz = BUK_SITE_XZ
        by = terrain_height_scalar(bx, bz)
        mouths = [np.asarray(o, dtype=np.float64) for o in SAM_MOUTH_OFFSETS]
        for i in range(n):
            dx = (i - (n - 1) * 0.5) * BUK_LAUNCHER_SPACING_M
            lpos = np.array([bx + dx, by, bz], dtype=np.float64)
            self._buk_launcher_positions.append(lpos)
            # Tube mouths reuse the S-300 canister offsets, clamped to the
            # 6-tube block (the offset tuple is only a cosmetic muzzle point).
            for k in range(BUK_TEL.tubes):
                mouth = mouths[k % len(mouths)]
                self._buk_tubes.append({"pos": lpos + mouth,
                                        "reload_left": 0.0})
            # 9S36 fire-control radar joins the player net (mirror of the
            # Pantsir radar): coverage is immediate, and the paired Buk
            # Structure's on_destroyed drops it on death.
            radar = Radar(
                radar_id=f"buk_9s36_{i:02d}",
                pos=(float(lpos[0]), by, float(lpos[2])),
                antenna_m=BUK_RADAR_ANTENNA_M,
                ranges=BUK_RADAR_RANGES,
                height_fn=self._height_fn,
            )
            self._buk_radars.append(radar)
            self.radar_net.radars.append(radar)
        # Seed the shared pools (the whole configured magazine).
        self.buk_9m317_ammo = self._buk_9m317_mag_cap
        self.buk_9m338_ammo = self._buk_9m338_mag_cap

    # ----------------------------------------------- M5 #3 CBR early-warning radar

    def _build_cbr(self, n: int) -> None:
        """Build N CBR masts side by side at the CBR site (n=0 -> nothing built,
        byte-identical default).  Each CBR Radar (tall 35 m mast + LONG
        missile-warning range, SHORT surface/air rings — sim/counter_battery.py)
        JOINS self.radar_net so inbound strike tracks surface EARLIER on the
        ContactBoard, and gets a paired CbrTracker.  The destructible CBR
        Structures + their on_destroyed (drop the radar from the net + emitter
        feed) are appended in __init__ with the other wrappers.  Adds NO RNG (the
        back-plot is deterministic)."""
        if n <= 0:
            return
        cx, cz = CBR_SITE_XZ
        cy = terrain_height_scalar(cx, cz)
        for i in range(n):
            dx = (i - (n - 1) * 0.5) * CBR_LAUNCHER_SPACING_M
            # pos[1] is the SITE terrain height (the Buk/station convention — the
            # tall mast is added inside Radar.antenna_alt = pos[1] + antenna_m, so
            # the 35 m mast raises the horizon datum to ~terrain+35 m).
            radar = Radar(
                radar_id=f"cbr_{i:02d}",
                pos=(cx + dx, cy, cz),
                antenna_m=CBR_ANTENNA_M,
                ranges=CBR_RANGES,
                height_fn=self._height_fn,
            )
            self._cbr_radars.append(radar)
            self.radar_net.radars.append(radar)
            self._cbr_trackers.append(CbrTracker(radar))

    def _step_cbr(self) -> None:
        """Step every CbrTracker against THIS tick's inbound hostile rounds, then
        publish the merged read-only ``cbr_threats`` / ``cbr_cues`` accessors.

        FOG / NO CHEAT: each tracker reads ONLY the rounds its own CBR Radar
        physically ``detects()`` (range / horizon / terrain) — the inbound set is
        the live HOSTILE land-attack StrikeMissiles + hostile interceptors
        (SamMissile is_hostile) the enemy has fired; the tracker gates them and
        back-plots the SHOOTER via the SHARED back_plot_surface() helper.  It does
        NOT auto-fire.  At n_cbr=0 _cbr_trackers is empty -> threats/cues stay
        empty (byte-identical default battle)."""
        # Reset publishes even when no tracker runs (empty at n_cbr=0).
        self.cbr_threats = []
        self.cbr_cues = []
        if not self._cbr_trackers:
            return
        # The inbound HOSTILE rounds to back-plot: enemy land-attack strike rounds
        # (StrikeMissile is_hostile) and enemy interceptors (SamMissile is_hostile,
        # e.g. SM-2/SM-6).  Player rounds (is_hostile False) are never fed.
        inbound = [m for m in self.missiles
                   if m.alive and getattr(m, "is_hostile", False)
                   and isinstance(m, (StrikeMissile, SamMissile))]
        now = self.sim_time
        for tracker in self._cbr_trackers:
            out = tracker.step(inbound, self.structures, now)
            self.cbr_threats.extend(out["threats"])
            self.cbr_cues.extend(out["cues"])

    # --------------------------------------------- M5 #5 ESM decoys + reflectors

    def _build_decoys(self, n_decoys: int, n_reflectors: int) -> None:
        """Build N decoy emitters + M corner reflectors at their fixed home-coast
        sites (both 0 -> nothing built, byte-identical default).  Placement is
        DETERMINISTIC (no RNG -> a same-seed battle replays bit-for-bit; the
        reserved [seed, DECOY_RNG_TAG] stream is unused, mirroring the CBR site).
        Each decoy is a DecoyEmitter (radar duck-type, EMPTY ranges -> heard by the
        enemy ESM but NEVER detects anything); each reflector is a passive
        CornerReflector.  Their destructible Structures are appended in __init__."""
        dx0, dz = DECOY_SITE_XZ
        for i in range(max(0, int(n_decoys))):
            x = dx0 + i * DECOY_SPACING_M
            y = float(terrain_height_scalar(x, dz))
            self._decoy_emitters.append(
                DecoyEmitter(f"decoy_{i:02d}",
                             np.array([x, y, dz], dtype=np.float64)))
        cx0, cz = CR_SITE_XZ
        for i in range(max(0, int(n_reflectors))):
            x = cx0 + i * CR_SPACING_M
            y = float(terrain_height_scalar(x, cz))
            self._corner_reflectors.append(
                CornerReflector(f"corner_reflector_{i:02d}",
                                np.array([x, y, cz], dtype=np.float64)))

    def _inject_reflector_backplots(self, rec: dict, now: float) -> None:
        """Plant ONE biased BackPlotEntry per live corner reflector that lies
        within its influence of THIS launch's honest back-plot.

        Called from _feed_enemy_picture ONLY when the enemy genuinely back-plotted
        the launch this step (so the spoof always rides a REAL sensor event).  The
        biased XZ comes from the SHARED back_plot_surface (via biased_back_plot),
        and the EXTRA fix is added through the SAME add_back_plot path the enemy
        uses — a real false-return geometry, NEVER a miss flag or truth edit.  A
        reflector out of influence (biased == the honest plot) plants nothing, and
        each reflector plants at most ONE fix per launch (a distinct track id), so
        BACKPLOT_FIXES_NEEDED distinct launches form a normal cluster on the decoy
        coast that the EXISTING commander targets like any other."""
        pic = self.commander.picture
        first_pos = rec["first_pos"]
        first_vel = rec["first_vel"]
        plain = back_plot_surface(first_pos, first_vel)
        if plain is None:
            return
        det = rec["det_pos"]
        det_range = float(np.hypot(float(first_pos[0]) - float(det[0]),
                                   float(first_pos[2]) - float(det[2])))
        error_m = det_range * BACKPLOT_ERR_FRAC
        for cr in self._corner_reflectors:
            if not cr.alive:
                continue
            biased = biased_back_plot(first_pos, first_vel, cr)
            if biased is None or biased == plain:
                continue                       # reflector out of influence
            cr_track_id = f"{rec['track_id']}_cr_{cr.reflector_id}"
            if any(bp.track_id == cr_track_id for bp in pic._back_plots):
                continue                       # already planted for this launch
            pic.add_back_plot(
                estimated_xz=np.array([biased[0], biased[1]],
                                      dtype=np.float64),
                error_m=error_m, sim_time=now, track_id=cr_track_id)

    def _emitter_by_id(self, emitter_id):
        """Resolve an enemy-picture emitter id to the live PLAYER emitter object a
        HARM seeker should home: the radar station, a CBR mast, or an ESM DECOY.
        Defaults to the radar station, so with no CBR/decoy built the only emitter
        id resolves to self.radar_station -> byte-identical to the legacy SEAD
        hardcode (the resolver only ever diverges when a decoy/CBR is built)."""
        if emitter_id == self.radar_station.radar_id:
            return self.radar_station
        for r in self._cbr_radars:
            if r.radar_id == emitter_id:
                return r
        for d in self._decoy_emitters:
            if d.radar_id == emitter_id:
                return d
        return self.radar_station

    @property
    def buk_9m317_launcher_armed(self) -> bool:
        """9M317 salvo gate: a round in the pool, no magazine refill pending,
        and at least one Buk tube re-cocked (and not relocate-committed — M5 #4,
        vacuously True while idle)."""
        if self.buk_9m317_ammo <= 0:
            return False
        if self._buk_9m317_mag_reload_left > 0.0:
            return False
        return any(t["reload_left"] <= 0.0 and not self._launcher_committed(t)
                   for t in self._buk_tubes)

    @property
    def buk_9m338_launcher_armed(self) -> bool:
        """9M338 salvo gate: a 9M338 round in the pool, no refill pending, and a
        tube re-cocked (and not relocate-committed — M5 #4)."""
        if self.buk_9m338_ammo <= 0:
            return False
        if self._buk_9m338_mag_reload_left > 0.0:
            return False
        return any(t["reload_left"] <= 0.0 and not self._launcher_committed(t)
                   for t in self._buk_tubes)

    def launch_buk(self, aircraft_id, round_id: str = "9m317"):
        """Salvo Buk launch at the AIR contact ``aircraft_id``: fire the
        selected round (9M317 long / 9M338 agile) from the next READY tube (no
        firerate gate while tubes are loaded); that tube then reloads on its own
        timer.  The two rounds draw from their own pools.  Returns the
        SamMissile, or None (no Buk / cold / empty / refill pending / invalid
        track / no ready tube).

        FOG / NO CHEAT: reads ONLY world.contacts.tracks (is_air) — never truth.
        The SamMissile then guides on the gated dead-reckoned estimate and uses
        truth ONLY at the terminal fuse (identical to launch_sam)."""
        if round_id == "9m338":
            if not self.buk_9m338_launcher_armed:
                return None
            weapon_def = BUK_AGILE
        else:
            if not self.buk_9m317_launcher_armed:
                return None
            weapon_def = BUK_LONG
        track = self.contacts.tracks.get(aircraft_id)
        if track is None or not track.get("is_air"):
            return None
        target = self._find_air_entity(aircraft_id)
        if target is None:
            return None
        # M5 #4: skip a tube whose launcher is relocate-committed.
        tube = next((t for t in self._buk_tubes
                     if t["reload_left"] <= 0.0
                     and not self._launcher_committed(t)), None)
        if tube is None:
            return None
        m = SamMissile(weapon_def, tube["pos"].copy(), target,
                       contact_estimate_fn=self._contact_estimate(aircraft_id))
        self.missiles.append(m)
        tube["reload_left"] = self._buk_tube_reload_s
        if round_id == "9m338":
            self.buk_9m338_ammo -= 1
            if self.buk_9m338_ammo <= 0:
                self.buk_9m338_ammo = 0
                self._buk_9m338_mag_reload_left = self._buk_mag_reload_s
        else:
            self.buk_9m317_ammo -= 1
            if self.buk_9m317_ammo <= 0:
                self.buk_9m317_ammo = 0
                self._buk_9m317_mag_reload_left = self._buk_mag_reload_s
        return m

    def _step_buk_tubes(self, dt: float) -> None:
        """Per-tube Buk reload + the two shared magazine-refill timers (mirror
        of the S-300 tube reload + the base-step mag timers).  No-op when no Buk
        is built (empty tube list, the refill timers stay 0)."""
        for t in self._buk_tubes:
            if t["reload_left"] > 0.0:
                t["reload_left"] = max(0.0, t["reload_left"] - dt)
        if self._buk_9m317_mag_reload_left > 0.0:
            self._buk_9m317_mag_reload_left = max(
                0.0, self._buk_9m317_mag_reload_left - dt)
            if self._buk_9m317_mag_reload_left <= 0.0:
                self.buk_9m317_ammo = self._buk_9m317_mag_cap
        if self._buk_9m338_mag_reload_left > 0.0:
            self._buk_9m338_mag_reload_left = max(
                0.0, self._buk_9m338_mag_reload_left - dt)
            if self._buk_9m338_mag_reload_left <= 0.0:
                self.buk_9m338_ammo = self._buk_9m338_mag_cap

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
        self._step_buk_tubes(dt)          # M5 per-tube Buk reload + mag refills
        # M5 #4 SHOOT-AND-SCOOT: advance any committed relocate; re-pin the pad +
        # tubes + Structure on arrival.  PURE NO-OP while every launcher is idle
        # (the byte-identical default) — reload timers above keep running so a
        # tube re-cocks WHILE driving (the mid-reload-relocate regression).
        self._step_relocations(dt)
        self._step_swarm_pod(dt)          # M4-B swarm cell-magazine refill
        self._step_drones(dt)
        # M5: step the enemy subs BEFORE the strikes/defense layers so a Kalibr
        # salvo a boat fires THIS tick joins self.missiles and flies on the NEXT
        # base step (the same reactive convention as the defense/strikes
        # launches).  No-op with n_subs=0 (self.subs empty) -> byte-identical.
        self._step_subs(dt)
        # M5 #1: step the amphibious layer alongside the subs (after the base
        # step ran the transports/LCACs' own update() + the OBB sweep): SPLASH a
        # transport that reached its launch line (its LCACs join self.ships and
        # fly on the NEXT base step — the established reactive convention) and
        # tick the beachhead clock.  No-op with n_transports=0 (no transports/
        # LCACs) -> byte-identical default battle.
        self._step_amphibious(dt)
        self._step_enemy_air(dt)
        self.defense.step(self, dt)
        # M5: detect the flagship CEC-hub alive->dead edge AFTER defense.step
        # (which clears a sunk ship's radar.alive); bump escort cohesion once.
        self._check_flagship_cec()
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
        # M5 #3: step the CBR early-warning tracker AFTER the contact/strike
        # layers are current this frame (so it sees this tick's inbound rounds),
        # like _step_acoustic_sensors.  It reads the live hostile rounds gated by
        # each CBR Radar.detects() (FOG); publishes the read-only cbr_threats /
        # cbr_cues.  No-op at n_cbr=0 (empty publishes) -> byte-identical.
        self._step_cbr()
        self._step_recon_sensors()
        # M5: the player's passive sonobuoy net + acoustic triangulation, then
        # the in-flight ASW rounds (a basket-acquire kills a boat).  Both no-op
        # with n_subs=0 (self.subs empty) -> byte-identical default battle.
        self._step_acoustic_sensors()
        self._step_asw_rounds(dt)
        self._update_airfield_intel()
        # M3-F5: publish the read-only EW legibility summary LAST, after the
        # jammers + the recon/SIGINT picture are current this step.  Pure read:
        # it derives the burn-through from sim/ew (single source of truth) and
        # the believed jammer fix/bearing from the ELINT picture — it touches no
        # sim state, so the default battle stays byte-identical.
        self._publish_ew_state()
