"""SandboxState: wires sim + world + render + input into the playable game.

Owns the WorldState, the Terrain/Ocean/Sky renderers, the Effects pools +
particle renderer and the cinematic CameraRig. ``sim_step`` advances the
world and turns sim happenings into effects (launch plumes, exhaust trail,
explosions / splashes / deck fires, jettisoned parts' ballistic tumbles);
``render`` draws the scene in the fixed order sky -> terrain -> ocean ->
sites -> ships -> aircraft -> TELs -> missiles -> particles -> HUD/map
overlay. The tactical map (M) replaces the HUD while open and drives the
player intent fields (target_point / waypoints). Audio rides the same
seams: launch / boom / splash one-shots fire where the effects do, and
per-missile booster/cruise loops are reconciled every frame in ``render``.

Task LC launch cinematics (normative: docs/research/oniks_launch_sequence.md
and s300_reference.md): the Oniks hot launch fires a muzzle blast at t = 0,
feeds a cream-white column through the ride-out, pulses orange nose jets in
the pitch-over, shoots the nose cap FORWARD at the high-thrust handover
(dark-grey boost trail, 4x plume), and ram-ejects the booster slug at Mach-2
burnout — after which the thick trail STOPS (near-transparent ramjet). The
S-300 cold launch blows its tube cover at t = 0, coasts unlit through the
hang, then erupts in an ignition fireball + smoke donut.

Task S4 adds the second platform: TAB toggles ``active_platform`` between
the Bastion and the S-300 battery at the SAM site; SPACE routes by platform
with target-type validation (Oniks: ship contact / surface point; S-300:
air contact only — anything else flashes a one-line HUD hint).

GL-touching module (imports world.sky etc.) — never imported by unit tests.
"""

from __future__ import annotations

import math

import numpy as np

from engine import math3d
from engine.camera import Camera
from engine.mesh import Mesh
from engine.meshdata import make_box, make_cylinder
from engine.particles import Effects, ParticleRenderer
from engine.text import TextRenderer
from game.cameras import (LAUNCHER_LOOK_UP, CameraRig, StaticSubject,
                          next_subject, subject_cycle_order)
from game.controls import (PLATFORMS_SANDBOX, SandboxControls,
                           next_platform)
from game.hud import HUD
from game.salvo import (RIPPLE_INTERVAL_S, SALVO_MODES, SalvoQueue,
                       next_salvo_mode, ready_tube_count, tot_delays)
from game.states import GameState
from game.timewarp import event_drop
from game import tactical_map
from game.tactical_map import TacticalMap
from models.aircraft_model import build_fast_aircraft, build_patrol_aircraft
from models.bastion import build_bastion_tel
from models.common import PALETTE, rot_x, rot_y, rot_z
from models.missiles import (build_40n6, build_48n6, build_57e6,
                             build_aim9x, build_harm, build_jassm,
                             build_kh31p, build_sm2, build_sm6,
                             build_tomahawk, build_zircon)
from models.oniks import build_oniks, build_oniks_nose_cap
from models.s300 import build_s300_tel
from models.ships_models import build_cargo, build_tanker, build_warship
from models.structures import (build_fuel_depot, build_harbor,
                               build_radar_station)
from sim.aircraft import AC_FALLING, AC_GONE
from sim.a2a import IrMissile
from sim.arsenal import N40N6
from sim.missile import (PH_BOOST, PH_CLIMB, PH_CRUISE, PH_DESCENT, PH_EJECT,
                         PH_PITCHOVER, PH_RIDEOUT, PH_TERMINAL)
from sim.physics import GRAVITY
from sim.sam import SPH_BOOST, SPH_EJECT, SamMissile
from sim.strike import SPH_STRIKE_BOOST, StrikeMissile
from sim.ships import ST_BURNING, ST_GONE, ST_SINKING
from world.generation import BASE_POS
from world.ocean import Ocean
from world.sky import Sky
from world.terrain import Terrain
from world.world import (LAUNCH_ELEV_DEG, SAM_TEL_POS, WorldState,
                         launch_realtime_lock)

# --- Tuning constants ---------------------------------------------------------

MISSILE_HALF_LEN = 4.30        # m, Oniks origin -> tail (models.oniks _TAIL_Z)
RAMJET_PHASES = (PH_CLIMB, PH_CRUISE, PH_DESCENT, PH_TERMINAL)
LAUNCH_TRAIL_PHASES = (PH_RIDEOUT, PH_PITCHOVER)   # cream-column ribbon feed
# Oniks model variants through the launch (Task OM2): folded wings in the
# tube and the first instants, then capped-deployed until the SUO cap is
# shot off at the PITCHOVER -> BOOST seam, then the bare round.
CAP_ON_PHASES = (PH_EJECT, PH_RIDEOUT, PH_PITCHOVER)
WING_DEPLOY_AFTER_EXIT = 0.2   # s after muzzle clear: surfaces snap to X
DEDICATED_MISSILE_IDS = frozenset(
    ("tomahawk", "jassm", "harm", "kh31p", "s300", "40n6", "sm2",
     "pantsir_57e6", "zircon", "sm6")
)
# Rounds WITHOUT a dedicated mesh render the closest existing silhouette
# instead of defaulting to the (ramjet-intake, 3-ton) Oniks body: the
# sub-launched Kalibr is a Tomahawk-class subsonic cruise round; the Buk
# 9M317 is an S-300-family SAM rod, the slim agile 9M338 reads like the
# 57E6 stick; the Bastion-K ASBM is the big ballistic 40N6 rod; a 55 kg
# swarm loiterer is closest to the small AIM-9X airframe.  Each gets a
# real mesh in the deferred model pass; these keep the SCALE honest.
MISSILE_MESH_ALIAS = {
    "kalibr":     "tomahawk",
    "buk_9m317":  "s300",
    "buk_9m338":  "pantsir_57e6",
    "asbm":       "40n6",
    "swarm":      "aim9x",
}
# Hulls without a dedicated mesh render the closest existing silhouette
# (same rationale as MISSILE_MESH_ALIAS; the destroyer fallback stays for
# genuinely unknown types).
SHIP_MESH_ALIAS = {
    "transport": "cargo",
    "lcac":      "warship",
}


def _missile_mesh_key(m) -> str:
    """Return the render mesh key for a live missile-like object."""
    weapon = getattr(m, "weapon", None)
    weapon_id = getattr(weapon, "weapon_id", None)
    if weapon_id in DEDICATED_MISSILE_IDS:
        return weapon_id
    if weapon_id in MISSILE_MESH_ALIAS:
        return MISSILE_MESH_ALIAS[weapon_id]
    if isinstance(m, IrMissile):
        return "aim9x"
    return "oniks"

# Sustainer exhaust: a small, very short-lived additive jet right at the
# nozzle (the boost plume's big puffs read as a fireball chain at Mach 2
# and blind the chase camera that flies through them). Fed on a period
# accumulator like the nose puffs/deck fires (Task GATE perf: a 120 Hz
# per-substep feed for every cruising round was the top sim_step cost);
# sizes/lives are bumped so the wake stays continuous at the wider spacing.
RAMJET_EMIT_PERIOD = 1.0 / 60.0               # s (sim) between exhaust feeds
RAMJET_FIRE_LIFE = (0.08, 0.16)               # s
RAMJET_FIRE_SIZE = (0.55, 1.3)                # m birth -> death
RAMJET_FIRE_COLORS = (np.array((0.95, 0.85, 0.65)),
                      np.array((1.0, 0.45, 0.12)))
RAMJET_EXHAUST_SPEED = 18.0                   # m/s backward puff ejection
# Near-transparent ramjet wake: a faint short-lived haze (the thick launch
# trail STOPS at burnout — oniks_launch_sequence.md §4.6).
RAMJET_HAZE_LIFE = (0.5, 0.9)                 # s
RAMJET_HAZE_SIZE = (0.7, 3.4)                 # m birth -> death
RAMJET_HAZE_COLORS = (np.array((0.82, 0.82, 0.84)),
                      np.array((0.78, 0.78, 0.80)))

# Boost trail ribbon points are darker grey than the cream ride-out column.
TRAIL_BOOST_COL = (0.38, 0.37, 0.36)

# Jettisoned parts (visual-only ballistic tumbles, Task LC):
# nose cap — shot FORWARD off the nose by the pull-away motors, then the
# missile out-accelerates it and it falls behind (RU2240489C1). The slight
# lateral kick (the pull-away nozzles are angled) drifts it clear of the
# freshly lit plume so the 'dark chunk hanging in mid-air' beat reads.
CAP_FWD_KICK = 14.0            # m/s forward impulse at separation
CAP_SIDE_KICK = 2.0            # m/s lateral drift out of the plume axis
CAP_DROP_KICK = 3.5            # m/s downward: the cap sinks below the path
CAP_DRAG = 0.9                 # 1/s exponential decay (light cone, draggy)
CAP_TUMBLE_RATE = 7.0          # rad/s
CAP_LIFE = 8.0                 # s before despawn
CAP_NOSE_AHEAD = 3.25          # m, missile origin -> the cap-base joint
#                                (models.oniks _CAP_BASE_Z: the part spawns
#                                exactly where the attached cap sat)
# booster slug — ram-ejected out the nozzle at burnout, brief.
SLUG_BACK_KICK = 45.0          # m/s backward ejection relative to the missile
SLUG_DRAG = 1.4                # 1/s (blunt slug into a Mach-2 stream)
SLUG_TUMBLE_RATE = 9.0         # rad/s
SLUG_LIFE = 5.0                # s before despawn
SLUG_TAIL_BACK = 5.0           # m, missile origin -> spawn point at the tail
# tube-cover fragments — blown clear at t = 0 (both launchers).
COVER_LIFE = 4.0
COVER_DRAG = 0.8
COVER_TUMBLE_RATE = 6.0
COVER_KICKS = ((4.5, 10.0, 2.0), (-3.5, 12.0, -1.5), (1.0, 14.0, -4.0))

# Nose-cap pulse jets: orange puff cadence while the pitch-over turns.
NOSE_PUFF_PERIOD = 0.22        # s (sim) between pulse-jet events

SHIP_FIRE_PERIOD = 1.0 / 25.0  # s (sim) between deck-fire emissions per ship
SHIP_FIRE_VIS_RANGE = 30_000.0 # m: deck fires emit only near the camera
SHIP_FIRE_DECK_FRAC = 0.35     # fire sits this fraction of hull height up

EXPLOSION_SCALE_SHIP = 1.6     # warhead against a hull (+ splash alongside)
EXPLOSION_SCALE_GROUND = 1.3   # warhead into terrain
EXPLOSION_SCALE_AIR = 1.2      # SAM proximity kill at altitude (no spray)
EXPLOSION_SCALE_SELFD = 0.7    # SAM self-destruct pop
SPLASH_SCALE = 1.4             # clean water impact

SHIP_HIT_SPLASH_MAX_Y = 8.0    # hull hits below this height also splash


class _NullTrail:
    """add_point sink for the EXHAUST TRAILS=OFF graphics pref — callers
    keep their one-line feed; nothing is stored or drawn."""

    def add_point(self, pos, col=None) -> bool:
        return False


_NULL_TRAIL = _NullTrail()

LAUNCH_PUFF_COUNT = 22         # cold-launch gas puff at the canister mouth

CRUISE_LOOP_GAIN = 1.0         # ramjet loop gain (low level baked in the wav)
BOOSTER_LOOP_GAIN = 1.0        # booster roar loop gain (high-thrust mode)
RIDEOUT_LOOP_GAIN = 0.55       # muffled low-thrust roar before the slam

# Camera shake kicks (amplitudes in m at the event, falling off to zero at
# 2 km — game/cameras.py SHAKE_RANGE). Storyboard: step 2 (muzzle blast) is
# the biggest, step 8 (full grunt) the deepest, S-300 ignition in between.
SHAKE_MUZZLE = 0.9             # Oniks in-tube ignition breaching the muzzle
SHAKE_SLAM = 0.6               # Oniks high-thrust mode lighting at ~120 m
SHAKE_SAM_IGNITION = 0.8       # S-300 fireball at the hang apex

TEL_ERECT_TIME = 4.0           # s for the canisters to swing 0 <-> 88 deg
TEL_ELEV_STEPS = 12            # prebaked TEL meshes across the elevation arc

# --- S-300 battery + aircraft (Task S4) -----------------------------------------

SAM_HALF_LEN = 3.75            # m, 48N6 mid-body origin -> tail (models.s300)
SAM_PAD_SIZE = (22.0, 2.4, 19.0)   # concrete pad slab under the 5P85 TEL

AIRCRAFT_DRAW_RANGE = 60_000.0     # m: a 30 m airframe is sub-pixel beyond
AIRCRAFT_SMOKE_PERIOD = 1.0 / 30.0 # s (sim) between falling-smoke emissions
AIRCRAFT_SMOKE_VIS_RANGE = 40_000.0  # emit the spiral's trail near the camera

# Harbor KILO is a waterline model on the ENEMY coast (land toward +z): the
# mesh is drawn at y = 0 this far seaward (-z) of the foreshore site marker,
# putting the quay fingers in the shallows and the shore apron on the beach.
HARBOR_SEAWARD_OFFSET = -260.0

HINT_SECONDS = 2.5             # HUD flash time for invalid-launch hints
HINT_S300_AIR = "S-300: SELECT AIR TARGET"
HINT_S300_EMPTY = "S-300: BATTERY EMPTY"
HINT_S300_NO_TUBE = "S-300: NO READY TUBE / TARGET LOST"
# Phase 5b round select (V): the 40N6 very-long-range round shares the TEL
# with the 48N6 (sim/arsenal.py N40N6; separate 2-round stock).
HINT_ROUND_48N6 = "S-300: 48N6 SELECTED"
HINT_ROUND_40N6 = "S-300: 40N6 SELECTED (HIGH TARGETS, 380 KM)"
HINT_40N6_LOW = "40N6: TARGET BELOW 4 KM ENGAGEMENT FLOOR"
HINT_40N6_EMPTY = "40N6: ROUNDS EXPENDED"
# M5 Buk mid-SAM round select (V) on the buk platform: 9M317 long reach <->
# 9M338 agile (sim/arsenal.py BUK_LONG / BUK_AGILE; separate 2-round stocks).
HINT_BUK_AIR = "BUK: SELECT AIR TARGET"
HINT_BUK_EMPTY = "BUK: BATTERY EMPTY"
HINT_ROUND_9M317 = "BUK: 9M317 SELECTED (LONG REACH, 70 KM)"
HINT_ROUND_9M338 = "BUK: 9M338 SELECTED (AGILE, 40 KM)"
HINT_ONIKS_SURFACE = "ONIKS HITS SHIPS ONLY - TAB TO S-300 FOR AIR"
HINT_ZIRCON = "ZIRCON SELECTED - hypersonic"
HINT_ZIRCON_RANGE = "ZIRCON: TARGET BEYOND FUEL RANGE - WILL FALL SHORT"
HINT_ONIKS_SEL = "ONIKS SELECTED"
# M2-T4 player Kh-31P anti-radiation (SEAD) round. Selected with B (3-way
# cycle, gated on ARM ammo); fired at a LOCALIZED enemy emitter chosen on the
# tactical map (tactical_map.selected_emitter, fog-honest SIGINT picture).
HINT_ARM_SEL = "KH-31P ANTI-RADIATION SELECTED"
HINT_ARM_NO_EMITTER = "KH-31P: SELECT AN EMITTER"
# M4-A Bastion-K quasi-ballistic top-attack ASBM. Selected with B (4-way cycle,
# gated on asbm_ammo); fired at a SHIP contact (it flies the dead-reckoned
# picture and dives near-vertically onto the hull). The stale-track hint warns
# the player that a salvo on an aged ship track aims at the STALE estimate —
# the physics-not-dice miss the round turns on.
HINT_ASBM_SEL = "BASTION-K ASBM SELECTED - lofted top-attack"
HINT_ASBM_NO_SHIP = "BASTION-K: NO SHIP CONTACT TO TARGET"
HINT_ASBM_STALE = "BASTION-K: SHIP TRACK STALE - LOFT MAY MISS A MOVER"
# Zircon fuel-limited effective reach vs a surface target (measured,
# tools/probe_zircon_traj.py): hi-lo ~250 km, lo-lo ~150 km — past these it
# coasts fuel-starved and splashes short. Warn the player instead of a silent whiff.
ZIRCON_RANGE_HILO_M = 250_000.0
ZIRCON_RANGE_LOLO_M = 150_000.0
HINT_RADAR_EMITTING = "RADAR: EMITTING"
HINT_RADAR_SILENT = "RADAR: SILENT"
HINT_RADAR_DESTROYED = "RADAR: DESTROYED"
# M3-F4 drone EW pod (J): toggles the self-protect / escort jammer on the
# active recon drone. Hot -> collapses the enemy radar net (a salvo leaks) but
# deafens the drone's own ELINT (going loud).
HINT_JAM_ON = "DRONE EW POD: HOT - NET DEGRADED, OWN ELINT LOUD"
HINT_JAM_OFF = "DRONE EW POD: COLD"
HINT_JAM_UNAVAILABLE = "DRONE EW POD: NOT FITTED"
HINT_JAM_NO_DRONE = "DRONE EW POD: NO DRONE AIRBORNE"
HINT_JAM_WRONG_PLATFORM = "DRONE EW POD: SELECT THE DRONE (TAB)"
# M5 ASW UI (U buoy-drop mode / K ASW launch).  The buoy is dropped by the
# NEXT LMB on the tactical map; the ASW round flies to the freshest LOCALIZED
# subsurface fix (never blind — world.launch_asw refuses without one).
HINT_BUOY_ARMED = "BUOY DROP ARMED - LMB ON MAP PLACES A SONOBUOY"
HINT_BUOY_OFF = "BUOY DROP OFF"
HINT_BUOY_EMPTY = "NO SONOBUOYS LEFT"
HINT_BUOY_UNFITTED = "SONOBUOYS: NOT FITTED (SETUP > DEFENSE)"
HINT_BUOY_DROPPED = "SONOBUOY AWAY ({n} LEFT)"
HINT_ASW_AWAY = "ASW ROUND AWAY - RUNNING TO THE FIX"
HINT_ASW_EMPTY = "ASW MAGAZINE EMPTY"
HINT_ASW_UNFITTED = "ASW: NOT FITTED (SETUP > DEFENSE)"
HINT_ASW_NO_FIX = "NO LOCALIZED SUBSURFACE FIX (CROSS-FIX WITH BUOYS)"
# M6 salvo / ripple-fire (F): empty every ready tube of the active platform in
# a controlled ripple.  The hints flash the mode + the count fired; an empty
# battery or no-target salvo flashes the single-fire reason via request_launch.
HINT_SALVO_RIPPLE = "SALVO: RIPPLE %d TUBES"
HINT_SALVO_FAN = "SALVO: FAN %d TUBES"
HINT_SALVO_TOT = "SALVO: TIME-ON-TARGET %d TUBES"
HINT_SALVO_NONE = "SALVO: NO READY TUBES"
HINT_SALVO_MODE_RIPPLE = "SALVO MODE: RIPPLE"
HINT_SALVO_MODE_FAN = "SALVO MODE: FAN (multi-axis)"
HINT_SALVO_MODE_TOT = "SALVO MODE: TIME-ON-TARGET"
# TOT flight-time estimate: a coarse sea-level cruise speed (m/s) for the loft
# stagger.  Read per-weapon from the WeaponDef cruise Mach when available;
# this is the conservative fallback (~Mach 2 at sea level) so a salvo on a world
# without a resolvable speed still staggers sensibly instead of bundling.
SALVO_TOT_FALLBACK_SPEED = 680.0
HINT_DRONE_RECON = tactical_map.DRONE_RECON_HINT   # SPACE with the drone
#                              platform active fires nothing (Phase 4);
#                              one string, shared with the map's LMB hint

_UP = np.array([0.0, 1.0, 0.0])


def _vhat(m) -> np.ndarray:
    """Missile unit velocity (vertical fallback while still in the tube)."""
    v = m.vel
    speed = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return v / speed if speed > 1e-9 else _UP.copy()


class _FallingPart:
    """Visual-only jettisoned part: ballistic fall + end-over-end tumble.
    Covers the Oniks nose cap (forward kick), the ram-ejected booster slug
    and the blown tube-cover fragments (Task LC dropped-part pattern)."""

    def __init__(self, pos, vel, forward, drag, tumble, life):
        self.pos = np.asarray(pos, dtype=np.float64).copy()
        self.vel = np.asarray(vel, dtype=np.float64).copy()
        self._rot0 = math3d.rotation_from_forward(forward)
        self._drag = float(drag)
        self._tumble = float(tumble)
        self._life = float(life)
        self.angle = 0.0
        self.t = 0.0

    def update(self, dt: float) -> None:
        self.t += dt
        self.vel *= np.exp(-self._drag * dt)
        self.vel[1] -= GRAVITY * dt
        self.pos += self.vel * dt
        self.angle += self._tumble * dt

    @property
    def rot(self) -> np.ndarray:
        return self._rot0 @ rot_x(self.angle)

    def expired(self, surface_y: float) -> bool:
        return self.t >= self._life or self.pos[1] <= surface_y


class SandboxState(GameState):
    """The playable game: launch Oniks strikes from the Bastion battery."""

    # TAB cycle (game/controls.py): CombatState overrides with the
    # three-platform COMBAT cycle that includes the recon drone.
    PLATFORMS = PLATFORMS_SANDBOX

    def __init__(self, app):
        super().__init__(app)
        self.window = app.window
        self.renderer = app.renderer
        self.world = self._build_world()
        self.camera = Camera()
        self._pip_cam = Camera()     # the map's LAUNCH CINEMA viewport
        self.rig = CameraRig(self.camera)
        self.sky = Sky()
        self.ocean = Ocean()
        # M3-F4: render the ACTIVE map field so the 3D coast/islands match the
        # field the sim masks LOS with. CombatWorld carries a per-preset
        # height_field; the sandbox WorldState has none (default map).
        self.terrain = Terrain(field=getattr(self.world, "height_field", None))
        self.effects = Effects(seed=4)
        self.particles = ParticleRenderer()
        self.controls = SandboxControls(self)
        self.text = TextRenderer()      # shared by the HUD and the map
        self.hud = HUD(self.text)
        self.hud_visible = True
        self.controls_overlay = False   # F1: live binding-table overlay
        # M6 per-battery STATUS PANEL: O toggles the EXPANDED full battery board
        # (every player tube's LOADED/RELOADING/EMPTY + magazine + refill).
        # Pure UI toggle — adds ZERO sim/world data, so the default battle stays
        # byte-identical by construction (the world never reads this flag).
        self.battery_panel_open = False

        # Player intent (driven by the tactical map)
        self.profile = "hi-lo"
        self.target_point = None        # float64 (3,) aim point (alt for air)
        self.waypoints: list = []       # (x, z) flown before the target
        # M4-B loitering-swarm arrival mode: "sync" (coordinated time-on-target,
        # the saturation default) or "max" (plain max-speed bundle).  Toggled by
        # the swarm_arrival_mode key (game/keybinds.py).
        self.swarm_arrival_mode = "sync"
        # M6 salvo / ripple-fire: a thin scheduler that empties the ready tubes
        # of the active platform over the existing per-tube launch path.  Owned
        # HERE (not the world — the world stays single-shot/deterministic) and
        # ticked from sim_step BEFORE world.step so queued launches enter the
        # frame.  Idle by default -> byte-identical (it never touches the world
        # until the player presses the salvo key).
        self.salvo_mode = "ripple"      # Y cycles RIPPLE -> FAN -> TOT
        self._salvo = SalvoQueue()
        self.buoy_drop_armed = False    # U: next map LMB drops a sonobuoy
        self.followed = None            # camera subject the cinematic rig
        #                                 tracks: a missile, a TEL
        #                                 StaticSubject or a contact entity
        self.map_open = False           # M toggles the tactical map
        self.tactical_map = TacticalMap(self)
        # Map texture pixels build in a daemon thread (seconds of numpy):
        # kicked here, under the BUILDING WORLD frame, so the first M press
        # never blocks the main thread (it shows BUILDING MAP if early).
        # M3-F4: build the ACTIVE map field (world.height_field) so a seeded
        # preset colorizes its OWN terrain; the sandbox/default world has none
        # (-> the byte-identical default map).
        tactical_map.ensure_map_pixels_async(
            getattr(self.world, "height_field", None))
        self.active_platform = "bastion"   # TAB toggles bastion <-> s300
        self.sam_round = "48n6"         # V toggles the S-300 round (5b)
        self.buk_round = "9m317"        # V toggles the Buk round (M5) on buk
        self.oniks_weapon = "oniks"     # B toggles Oniks <-> Zircon (Phase 8)
        self.hint_text = ""             # transient HUD hint line
        self.hint_left = 0.0            # real seconds the hint stays up
        # Per-frame UI hit/tag registry (AI-testability build 2026-07-05):
        # draw sites register their rects each render; clicks route through
        # it, the F3 bug reporter tags from it, tools audit overlaps on it.
        from game.ui_registry import UiRegistry
        self.ui = UiRegistry()

        # Effects bookkeeping
        self._trails: dict[int, object] = {}      # id(missile) -> TrailRibbon
        self._parts: list[tuple] = []   # (mesh, _FallingPart) tumbling debris
        self._fire_acc: dict[str, float] = {}     # ship_id -> emission debt
        self._ac_smoke_acc: dict[str, float] = {} # falling aircraft debt
        self._puff_acc: dict[int, float] = {}     # nose pulse-jet debt
        self._ramjet_acc: dict[int, float] = {}   # cruise exhaust feed debt
        self._tel_frac = 1.0            # canister elevation 0..1 (armed = up)

        self._build_meshes()

        # Orbit/chase subject anchors for the two TELs (Task CAM): aim at
        # canister mid-height so the orbit cam frames the vehicle, not its
        # wheels. Persistent objects — the [ / ] cycle matches by identity.
        self._tel_subjects = {
            "bastion": StaticSubject(self._tel_pos + _UP * LAUNCHER_LOOK_UP,
                                     "BASTION TEL"),
            "s300": StaticSubject(self._sam_tel_pos + _UP * LAUNCHER_LOOK_UP,
                                  "S-300 TEL"),
        }

    def _build_world(self):
        """The session's world; CombatState overrides (game/combat.py)."""
        return WorldState()

    # ------------------------------------------------------------ GL meshes

    @staticmethod
    def _slug_meshdata():
        """Spent booster slug: a small dark cylinder ram-ejected at burnout."""
        return make_cylinder(0.17, 0.9, 14, PALETTE["exhaust_ring"],
                             axis="z", cap_ends=True)

    def _build_meshes(self) -> None:
        # Oniks launch variants (Task OM2): folded+capped in the tube,
        # capped through ride-out/pitch-over, bare for the rest of flight.
        self._mesh_oniks = Mesh(build_oniks())
        self._mesh_oniks_capped = Mesh(build_oniks(nose_cap=True))
        self._mesh_oniks_folded = Mesh(build_oniks(nose_cap=True,
                                                   wings_folded=True))
        self._mesh_cap = Mesh(build_oniks_nose_cap())
        self._mesh_slug = Mesh(self._slug_meshdata())
        self._mesh_cover = Mesh(make_box((0.6, 0.09, 0.6),
                                         PALETTE["exhaust_ring"]))
        self._ship_meshes = {"cargo": Mesh(build_cargo()),
                             "tanker": Mesh(build_tanker()),
                             "warship": Mesh(build_warship())}
        builders = {"radar": build_radar_station, "depot": build_fuel_depot,
                    "harbor": build_harbor}
        self._site_draws = []
        for site in self.world.sites:
            x, z = site["pos"]
            if site["kind"] == "harbor":
                # Waterline model (Task GATE): the quays stand in the water
                # seaward of the foreshore site marker (enemy coast: land is
                # +z, sea is -z) with the model's shore apron joining the
                # beach behind them.
                pos = np.array([x, 0.0, z + HARBOR_SEAWARD_OFFSET],
                               dtype=np.float64)
            else:
                y = max(self.world.terrain_height_at(x, z), 0.0)
                pos = np.array([x, y, z], dtype=np.float64)
            self._site_draws.append((Mesh(builders[site["kind"]]()), pos))
        self._tel_meshes = [Mesh(build_bastion_tel(elevation_deg=e))
                            for e in np.linspace(0.0, LAUNCH_ELEV_DEG,
                                                 TEL_ELEV_STEPS)]
        self._tel_pos = np.array(BASE_POS, dtype=np.float64)
        # Phase 8: the renderer draws one TEL per position here (default single;
        # CombatState replaces these with the multi-launcher battery layout).
        self._tel_positions = [self._tel_pos]
        # S-300 battery: pad slab + permanently erected 4-tube TEL + 48N6
        self._mesh_sam_pad = Mesh(make_box(SAM_PAD_SIZE, PALETTE["concrete"],
                                           offset=(0.0, -SAM_PAD_SIZE[1] * 0.5,
                                                   0.0)))
        self._mesh_s300_tel = Mesh(build_s300_tel(elevation_deg=90.0))
        self._missile_meshes = {
            "tomahawk": Mesh(build_tomahawk()),
            "jassm": Mesh(build_jassm()),
            "harm": Mesh(build_harm()),
            "kh31p": Mesh(build_kh31p()),
            "aim9x": Mesh(build_aim9x()),
            "s300": Mesh(build_48n6()),
            "40n6": Mesh(build_40n6()),
            "sm2": Mesh(build_sm2()),
            "sm6": Mesh(build_sm6()),
            "pantsir_57e6": Mesh(build_57e6()),
            "zircon": Mesh(build_zircon()),
        }
        self._mesh_s300_missile = self._missile_meshes["s300"]
        self._sam_tel_pos = SAM_TEL_POS.copy()
        self._sam_tel_positions = [self._sam_tel_pos]
        self._aircraft_meshes = {"patrol": Mesh(build_patrol_aircraft()),
                                 "fast": Mesh(build_fast_aircraft())}

    # --------------------------------------------------------------- intent

    def cycle_platform(self) -> str:
        """TAB: the next platform in the class's cycle; the launcher cam
        re-anchors AND the camera subject follows the platform you just
        selected (playtest 2026-07-05: TAB onto the drone left the camera
        parked on the Bastion TEL — you never SAW what you selected).
        _platform_subject returns the flying drone for the drone platform,
        else the platform's TEL StaticSubject."""
        self.active_platform = next_platform(self.active_platform,
                                             self.PLATFORMS)
        self.rig.set_launcher_pos(self._platform_anchor())
        subj = self._platform_subject()
        if subj is not None and subj is not self.followed:
            self.followed = subj
            self.rig.retarget()
        self.app.audio.ui_click()
        return self.active_platform

    def _platform_anchor(self):
        """Launcher-cam ground anchor for the active platform."""
        return (self._sam_tel_pos if self.active_platform == "s300"
                else self._tel_pos)

    def _platform_subject(self):
        """The active platform's [ / ] cycle entry: a TEL StaticSubject
        here; CombatState returns the flying drone for the drone
        platform."""
        return self._tel_subjects[
            self.active_platform if self.active_platform
            in self._tel_subjects else "bastion"]

    def show_hint(self, text: str, seconds: float = HINT_SECONDS) -> None:
        """Flash a one-line HUD hint (invalid launch selection etc.)."""
        self.hint_text = text
        self.hint_left = seconds

    def toggle_controls_overlay(self) -> None:
        """F1 (reserved binding): the controls overlay generated live from
        the binding table. An overlay, not a menu — the sim keeps running."""
        self.controls_overlay = not self.controls_overlay
        self.app.audio.ui_click()

    def toggle_forensics(self) -> None:
        """J (forensics binding): the FORENSICS/DEBRIEF ledger is COMBAT-only
        (it reads the CombatState flight recorder) — graceful no-op hint in
        SANDBOX, same convention as the other combat-only actions."""
        self.show_hint("FORENSICS LEDGER: COMBAT ONLY")

    def report_bug(self) -> None:
        """F3 (bug_report binding): the BLACK BOX bug flag is COMBAT-only
        (it stamps the battle ledger and bundles its trail) — graceful
        no-op hint in SANDBOX, same convention as toggle_forensics."""
        self.show_hint("BUG REPORT: COMBAT ONLY")

    def toggle_director(self) -> None:
        """I (director binding): the RED-FORCE DIRECTOR panel lives on the
        WAR SANDBOX's tactical map (game/sandbox_war.py overrides this) —
        graceful no-op hint everywhere else, same convention as
        toggle_forensics.  In COMBAT the red force answers to its own
        commander, never to the player."""
        self.show_hint("DIRECTOR: WAR SANDBOX ONLY")

    def toggle_map_layout(self) -> None:
        """F4 (map_layout binding): flip the tactical map BOARD <-> CLASSIC
        (the 2026-07-05 command-board test's revert switch, persisted)."""
        prefs = getattr(self.app, "ui_prefs", None)
        if prefs is None:
            return
        new = prefs.toggle_map_layout()
        self.show_hint(f"MAP LAYOUT: {new.upper()}")
        self.app.audio.ui_click()

    def toggle_launch_cinema(self) -> None:
        """F5 (launch_cinema binding): the launch-cinema PiP on the map."""
        prefs = getattr(self.app, "ui_prefs", None)
        if prefs is None:
            return
        new = prefs.toggle_launch_cinema()
        self.show_hint("LAUNCH CINEMA: " + ("ON" if new else "OFF"))
        self.app.audio.ui_click()

    def toggle_battery_panel(self) -> None:
        """O (battery_panel binding): toggle the EXPANDED per-battery STATUS
        PANEL (every player Oniks/S-300 tube's LOADED/RELOADING/EMPTY + the
        magazine pool + refill timers).  An overlay, not a menu — the sim keeps
        running; player-only own-force telemetry, no enemy state."""
        self.battery_panel_open = not self.battery_panel_open
        self.app.audio.ui_click()

    def toggle_auto_warp(self) -> bool:
        """T (auto_warp_toggle binding): flip M6 AUTO-TIME-WARP on/off.

        The toggle state + director live on :class:`SandboxControls`; this is
        the SandboxState-side forwarder the key dispatch calls (mirroring
        toggle_battery_panel / cycle_salvo_mode), so the binding reaches the
        director.  Pure UI/pacing — auto-warp OFF keeps the default battle
        byte-identical (the director stays dormant).  Returns the new state."""
        new_state = self.controls.toggle_auto_warp()
        self.app.audio.ui_click()
        return new_state

    def toggle_radar(self) -> None:
        """R (radar_toggle binding): flip the player radar station's
        emissions — the COMBAT counter to ESM localization. Silent radars
        can't be located, but can't see either: the picture coasts (already
        automatic). SANDBOX worlds have no radar_station: graceful no-op."""
        radar = getattr(self.world, "radar_station", None)
        if radar is None:
            return
        if not radar.alive:
            self.show_hint(HINT_RADAR_DESTROYED)
            return
        radar.emitting = not radar.emitting
        self.show_hint(HINT_RADAR_EMITTING if radar.emitting
                       else HINT_RADAR_SILENT)
        self.app.audio.ui_click()

    def toggle_jam(self) -> None:
        """J (jam binding): toggle the recon drone's EW pod (M3-F4) — ONLY when
        the drone platform is active and a drone is airborne.  Hot: the pod
        radiates the barrage corridor that collapses the ENEMY radar net so a
        sea-skim salvo leaks, at the cost of deafening the drone's OWN passive
        ELINT.  Gated on the world having ARMED the pod (config.player_jammer):
        an unfitted pod is a graceful no-op hint.  SANDBOX worlds (no drone /
        no _player_jammer) are graceful no-ops."""
        if self.active_platform != "drone":
            self.show_hint(HINT_JAM_WRONG_PLATFORM)
            return
        if not getattr(self.world, "_player_jammer", False):
            self.show_hint(HINT_JAM_UNAVAILABLE)
            return
        drone = getattr(self.world, "drone", None)
        if drone is None or not drone.alive:
            self.show_hint(HINT_JAM_NO_DRONE)
            return
        drone.set_jam(not drone.jam_active)
        self.show_hint(HINT_JAM_ON if drone.jam_active else HINT_JAM_OFF)
        self.app.audio.ui_click()

    def toggle_buoy_drop(self) -> None:
        """U (buoy_drop binding): arm/disarm BUOY-DROP mode — while armed the
        next LMB on the tactical map places a passive sonobuoy at the clicked
        point (M5 ASW).  Refuses (hint) with an empty stock; SANDBOX worlds
        (no sonobuoys_left) are graceful no-ops."""
        if self.buoy_drop_armed:
            self.buoy_drop_armed = False
            self.show_hint(HINT_BUOY_OFF)
            self.app.audio.ui_click()
            return
        if int(getattr(self.world, "sonobuoys_left", 0)) <= 0:
            # "Left" vs "never fitted": a battle configured with zero buoys
            # points the player at the setup page instead of implying they
            # spent a stock they never had.
            fitted = int(getattr(getattr(self.world, "_config", None),
                                 "n_sonobuoys", 0)) > 0
            self.show_hint(HINT_BUOY_EMPTY if fitted else HINT_BUOY_UNFITTED)
            return
        self.buoy_drop_armed = True
        self.show_hint(HINT_BUOY_ARMED)
        self.app.audio.ui_click()

    def map_drop_buoy(self, world_xz) -> bool:
        """A map LMB while buoy-drop is armed: place the buoy at the clicked
        world point.  Disarms automatically when the stock runs out.  Returns
        True when a buoy was placed (the click is consumed)."""
        place = getattr(self.world, "place_sonobuoy", None)
        if place is None or not self.buoy_drop_armed:
            return False
        buoy = place(world_xz)
        if buoy is None:
            self.buoy_drop_armed = False
            self.show_hint(HINT_BUOY_EMPTY)
            return True                    # the click was still a drop attempt
        left = int(getattr(self.world, "sonobuoys_left", 0))
        if left <= 0:
            self.buoy_drop_armed = False
        self.show_hint(HINT_BUOY_DROPPED.format(n=left))
        self.app.audio.ui_click()
        return True

    def request_asw(self) -> None:
        """K (asw_launch binding): fire an ASW round at the freshest LOCALIZED
        subsurface fix (a buoy cross-fix or a fresh launch datum).  The world
        verb refuses blind shots and empty magazines; hints say which.
        SANDBOX worlds (no launch_asw) are graceful no-ops."""
        launch = getattr(self.world, "launch_asw", None)
        if launch is None:
            return
        if int(getattr(self.world, "asw_ammo_left", 0)) <= 0:
            fitted = int(getattr(getattr(self.world, "_config", None),
                                 "asw_ammo", 0)) > 0
            self.show_hint(HINT_ASW_EMPTY if fitted else HINT_ASW_UNFITTED)
            return
        rnd = launch()
        if rnd is None:
            self.show_hint(HINT_ASW_NO_FIX)
            return
        self.show_hint(HINT_ASW_AWAY)
        self.app.audio.ui_click()

    def cycle_sam_round(self) -> str:
        """V (sam_round binding): toggle the SAM round for the ACTIVE platform.

        On the buk platform (M5) it cycles the Buk round — 9M317 long reach
        <-> 9M338 agile (sim/arsenal.py BUK_LONG / BUK_AGILE; separate 2-round
        stocks) — and returns ``self.buk_round``.

        On the S-300 platform (the default for V) it toggles 48N6 (4 rounds)
        <-> 40N6 (very-long-range vs HIGH targets, 2 rounds, ACTIVE terminal
        seeker) and returns ``self.sam_round``.  The HUD/map readouts show the
        selection and both stocks."""
        if self.active_platform == "buk":
            self.buk_round = "9m338" if self.buk_round == "9m317" else "9m317"
            self.show_hint(HINT_ROUND_9M338 if self.buk_round == "9m338"
                           else HINT_ROUND_9M317)
            self.app.audio.ui_click()
            return self.buk_round
        self.sam_round = "40n6" if self.sam_round == "48n6" else "48n6"
        self.show_hint(HINT_ROUND_40N6 if self.sam_round == "40n6"
                       else HINT_ROUND_48N6)
        self.app.audio.ui_click()
        return self.sam_round

    def cycle_oniks_weapon(self) -> str:
        """B (oniks_weapon binding): cycle the Bastion round.

        Base 2-way (LOCKED default UX): P-800 Oniks (default) <-> hypersonic
        3M22 Zircon (scarce, M5+ - punches through the SM-2 screen).  Both fire
        from the same TEL tubes.

        M2-T4: when the world carries a Kh-31P ARM pool (kh31p_ammo > 0 from the
        setup armory), the cycle EXTENDS to 3-way oniks->zircon->kh31p->oniks so
        the player can select the anti-radiation round.  The ARM is GATED OUT of
        the cycle when the pool is empty/absent (None or 0): the default battle
        (kh31p_ammo == 0) keeps the EXACT 2-way oniks<->zircon UX, byte-identical
        — zircon wraps straight back to oniks, kh31p is never reachable.

        From kh31p the cycle always returns to oniks (even if the pool drained
        to 0 mid-battle), so the player can never get stuck on an empty ARM.

        M4-A: when the world carries a Bastion-K ASBM pool (asbm_ammo > 0) the
        cycle EXTENDS again to include 'asbm' after zircon:
        oniks->zircon->asbm->kh31p->oniks.  Each scarce round is GATED OUT when
        its pool is empty/absent (None or 0): the default battle (asbm_ammo ==
        kh31p_ammo == 0) keeps the EXACT 2-way oniks<->zircon UX, byte-identical
        — zircon wraps straight back to oniks.  Any stray selection returns to
        oniks, so the player can never get stuck on an empty pool."""
        arm_available = getattr(self.world, "_kh31p_ammo", 0) not in (None, 0)
        asbm_available = getattr(self.world, "_asbm_ammo", 0) not in (None, 0)
        if self.oniks_weapon == "oniks":
            self.oniks_weapon = "zircon"
        elif self.oniks_weapon == "zircon":
            # Step onto the next stocked scarce round (ASBM, then ARM); else
            # wrap to oniks (the 2-way default-battle path — byte-identical).
            self.oniks_weapon = ("asbm" if asbm_available
                                 else "kh31p" if arm_available else "oniks")
        elif self.oniks_weapon == "asbm":
            self.oniks_weapon = "kh31p" if arm_available else "oniks"
        else:                                   # kh31p (or any stray) -> oniks
            self.oniks_weapon = "oniks"
        if self.oniks_weapon == "zircon":
            hint = HINT_ZIRCON
        elif self.oniks_weapon == "asbm":
            hint = HINT_ASBM_SEL
        elif self.oniks_weapon == "kh31p":
            hint = HINT_ARM_SEL
        else:
            hint = HINT_ONIKS_SEL
        self.show_hint(hint)
        self.app.audio.ui_click()
        return self.oniks_weapon

    def toggle_swarm_arrival_mode(self) -> str:
        """H (swarm_arrival_mode binding): toggle the loitering-swarm bundle
        between SYNC (coordinated time-on-target — the saturation default) and
        MAX (plain max-speed bundle, no self-adjustment).  A graceful no-op off
        the SWARM platform other than flipping the stored mode."""
        self.swarm_arrival_mode = ("max" if self.swarm_arrival_mode == "sync"
                                   else "sync")
        self.app.audio.ui_click()
        return self.swarm_arrival_mode

    def _selected_air_track(self):
        """The selected contact's track if it is a live air track, else None."""
        sid = self.tactical_map.selected_contact
        track = self.world.contacts.tracks.get(sid) if sid is not None else None
        return track if track is not None and track.get("is_air") else None

    def _selected_entity(self):
        """The Ship/Aircraft behind the map's selected contact (None when
        nothing is selected or the entity is gone). Air contacts resolve
        through the world's _find_air_entity hook so COMBAT enemy air
        (fighters/AWACS, world/combat.py) is found like sandbox traffic."""
        sid = self.tactical_map.selected_contact
        track = self.world.contacts.tracks.get(sid) if sid is not None else None
        if track is None:
            return None
        if track.get("is_air"):
            return self.world._find_air_entity(sid)
        return next((s for s in self.world.ships if s.ship_id == sid), None)

    def cycle_camera_subject(self, step: int = 1):
        """[ / ] (Task CAM): cycle the orbit/chase camera subject through
        newest missile -> other in-flight missiles -> active TEL ->
        selected contact's entity, with a smooth rig blend onto each.
        Hostile strike rounds (Phase 3) are fog-of-war gated everywhere
        the player gets intel, so the cycle skips them too — otherwise
        [ / ] would chase-cam an undetected Tomahawk far beyond the radar
        horizon. SANDBOX rounds never carry is_hostile: behavior unchanged."""
        order = subject_cycle_order([m for m in self.world.missiles
                                     if not getattr(m, "is_hostile", False)],
                                    self._platform_subject(),
                                    self._selected_entity())
        subj = next_subject(order, self.followed, step)
        if subj is not None and subj is not self.followed:
            self.followed = subj
            self.rig.retarget()
            self.app.audio.ui_click()
        return self.followed

    def request_launch(self):
        """SPACE, routed by the active platform with target-type validation:
        the Oniks takes ship contacts / surface points, the S-300 takes air
        contacts only, the recon drone fires nothing — anything else
        flashes a HUD hint and does not fire."""
        if self.active_platform == "drone":
            self.show_hint(HINT_DRONE_RECON)
            return None
        if self.active_platform == "swarm":
            return self._request_swarm_launch()
        if self.active_platform == "buk":
            return self._request_buk_launch()
        if self.active_platform == "s300":
            return self._request_sam_launch()
        if self.oniks_weapon == "kh31p":
            return self._request_arm_launch()
        if self._selected_air_track() is not None:
            self.show_hint(HINT_ONIKS_SURFACE)
            return None
        if self.target_point is None:
            return None
        if self.oniks_weapon == "asbm":
            # M4-A: the ASBM is anti-ship and flies the dead-reckoned ship
            # picture (NOT the hi-lo/lo-lo cruise envelope — skip that warning).
            # It needs a SHIP contact near the aim point; warn (do not block) on
            # a stale track, since the loft commits to the stale estimate and a
            # mover can walk out from under it (physics-not-dice miss).
            ship_id = self.world._nearest_ship_contact(self.target_point)
            if ship_id is None:
                self.show_hint(HINT_ASBM_NO_SHIP)
                return None
            trk = self.world.contacts.tracks.get(ship_id)
            if trk is not None and float(trk.get("age", 0.0)) > 5.0:
                self.show_hint(HINT_ASBM_STALE)
            m = self.world.launch(self.profile, self.target_point,
                                  tuple(self.waypoints), weapon_id="asbm")
            if m is not None:
                self.followed = m
                self.rig.retarget()
                self.effects.muzzle_blast(
                    m.pos, ground_y=float(self._tel_pos[1]) + 1.5)
                self._spawn_cover_debris(m.pos)
                self.app.audio.play("launch", pos=m.pos)
                self.rig.kick_shake(SHAKE_MUZZLE, pos=m.pos)
            return m
        if self.oniks_weapon == "zircon":
            # Fuel-aware range warning (the Zircon coasts to a stall past its
            # envelope and splashes short — see ZIRCON_RANGE_*). Informational:
            # the shot still fires (the target may be closing), the player is told.
            base = np.asarray(BASE_POS, dtype=np.float64)
            rng_to_tgt = float(np.hypot(self.target_point[0] - base[0],
                                        self.target_point[2] - base[2]))
            envelope = (ZIRCON_RANGE_LOLO_M if self.profile == "lo-lo"
                        else ZIRCON_RANGE_HILO_M)
            if rng_to_tgt > envelope:
                self.show_hint(HINT_ZIRCON_RANGE)
        m = self.world.launch(self.profile, self.target_point,
                              tuple(self.waypoints),
                              weapon_id=self.oniks_weapon)
        if m is not None:
            self.followed = m
            self.rig.retarget()         # smooth swing onto the new round
            # Hot launch t = 0: muzzle fireball + pink-grey cloud + ground
            # wash + the canister cap blown off in chunks (storyboard step 2).
            self.effects.muzzle_blast(m.pos,
                                      ground_y=float(self._tel_pos[1]) + 1.5)
            self._spawn_cover_debris(m.pos)
            self.app.audio.play("launch", pos=m.pos)
            self.rig.kick_shake(SHAKE_MUZZLE, pos=m.pos)
        return m

    def _request_arm_launch(self):
        """SPACE with the Kh-31P selected (M2-T4): fire the player ARM at the
        emitter selected on the tactical map.  The ARM homes on a LOCALIZED
        enemy radar (passive SIGINT, fog-honest) rather than a surface/air
        contact — so it needs a selected EMITTER, NOT a target_point.

        No emitter selected -> flash HINT_ARM_NO_EMITTER, return None (no fire).
        Otherwise call ``world.launch_arm(eid)``; on success follow the round +
        retarget the rig and play the same launch effects as the Oniks path
        (the ARM ships with the coastal strike battery and fires from the same
        TEL mouth, world/combat.py launch_arm)."""
        eid = getattr(self.tactical_map, "selected_emitter", None)
        if eid is None:
            self.show_hint(HINT_ARM_NO_EMITTER)
            return None
        launch_arm = getattr(self.world, "launch_arm", None)
        m = launch_arm(eid) if launch_arm is not None else None
        if m is not None:
            self.followed = m
            self.rig.retarget()             # smooth swing onto the new round
            self.effects.muzzle_blast(m.pos,
                                      ground_y=float(self._tel_pos[1]) + 1.5)
            self._spawn_cover_debris(m.pos)
            self.app.audio.play("launch", pos=m.pos)
            self.rig.kick_shake(SHAKE_MUZZLE, pos=m.pos)
        return m

    def _request_swarm_launch(self):
        """SPACE with the SWARM pod active (M4-B): bundle-fire every ready cell
        at the map aim point for a coordinated time-on-target.  The pod takes a
        SURFACE point (like the Oniks), NOT an air track.  ``swarm_arrival_mode``
        selects SYNC (time-on-target saturation) vs MAX (plain max-speed
        bundle).  No aim point / empty pod -> no fire.  Returns the FIRST
        spawned round (the camera follows it), or None."""
        if self.target_point is None:
            return None
        launch_swarm = getattr(self.world, "launch_swarm", None)
        if launch_swarm is None:
            return None
        rounds = launch_swarm(self.profile, self.target_point,
                              tuple(self.waypoints),
                              sync=(self.swarm_arrival_mode == "sync"))
        if not rounds:
            return None
        m = rounds[0]
        self.followed = m
        self.rig.retarget()
        # The whole bundle clears the pods together: one muzzle effect per round.
        for r in rounds:
            self.effects.muzzle_blast(
                r.pos, ground_y=float(self._tel_pos[1]) + 1.5)
        self._spawn_cover_debris(m.pos)
        self.app.audio.play("launch", pos=m.pos)
        self.rig.kick_shake(SHAKE_MUZZLE, pos=m.pos)
        return m

    def _request_sam_launch(self):
        track = self._selected_air_track()
        if track is None:
            self.show_hint(HINT_S300_AIR)
            return None
        if self.sam_round == "40n6":
            # Round-specific gates surfaced as hints BEFORE the launch
            # call (launch_sam returns a bare None for every refusal):
            # empty 40N6 stock, and the 4 km engagement floor checked on
            # the CONTACT picture — the player acts on what they know.
            if self.world.sam_ammo_40n6 <= 0:
                self.show_hint(HINT_40N6_EMPTY)
                return None
            # Judge the DISPLAYED altitude (dead-reckoned estimate), the
            # same number the contact card shows — the stale raw fix
            # false-denied climbing targets (playtest 2026-07-05).
            est_alt = float(self.world.contacts.estimated_pos(
                self.tactical_map.selected_contact,
                self.world.sim_time)[1])
            if est_alt < N40N6.min_intercept_alt:
                self.show_hint(HINT_40N6_LOW)
                return None
        elif self.world.sam_ammo <= 0:
            self.show_hint(HINT_S300_EMPTY)
            return None
        m = self.world.launch_sam(self.tactical_map.selected_contact,
                                  round_id=self.sam_round)
        if m is not None:
            self.followed = m
            self.rig.retarget()             # smooth swing onto the new round
            # True cold launch t = 0: tube cover shot off + a grey-white gas
            # puff — NO flame until the hang-apex ignition.
            self._launch_puff(m.pos)
            self._spawn_cover_debris(m.pos)
            self.app.audio.play("launch", pos=m.pos)
        else:
            # A refused launch must never be a dead key (live playtest:
            # SPACE at a Tomahawk track did nothing, silently) — every
            # pre-gate above already hinted, so what remains is a cycling
            # tube or a track whose entity just died.
            self.show_hint(HINT_S300_NO_TUBE)
        return m

    def _request_buk_launch(self):
        """SPACE with the buk platform active (M5): fire the selected Buk round
        (9M317 long / 9M338 agile) at the air contact selected on the tactical
        map.  Mirror of _request_sam_launch: needs an AIR track; surfaces the
        empty-pool gate as a hint BEFORE the launch call (world.launch_buk
        returns a bare None for every refusal); fires the SAME hot rail-launch
        puff effects.  SANDBOX worlds have no launch_buk -> graceful no-op."""
        track = self._selected_air_track()
        if track is None:
            self.show_hint(HINT_BUK_AIR)
            return None
        launch_buk = getattr(self.world, "launch_buk", None)
        if launch_buk is None:
            return None
        armed = (self.world.buk_9m338_launcher_armed
                 if self.buk_round == "9m338"
                 else self.world.buk_9m317_launcher_armed)
        if not armed:
            self.show_hint(HINT_BUK_EMPTY)
            return None
        m = launch_buk(self.tactical_map.selected_contact,
                       round_id=self.buk_round)
        if m is not None:                   # None while the tube reloads
            self.followed = m
            self.rig.retarget()
            self._launch_puff(m.pos)
            self._spawn_cover_debris(m.pos)
            self.app.audio.play("launch", pos=m.pos)
        return m

    def _spawn_cover_debris(self, mouth_pos) -> None:
        """Tube-cover fragments blown clear of the muzzle at t = 0."""
        for i, kick in enumerate(COVER_KICKS):
            fwd = np.array([math.sin(1.1 + 2.1 * i), 0.35,
                            math.cos(1.1 + 2.1 * i)])
            self._parts.append((self._mesh_cover, _FallingPart(
                mouth_pos, np.array(kick, dtype=np.float64), fwd,
                COVER_DRAG, COVER_TUMBLE_RATE * (1.0 + 0.2 * i), COVER_LIFE)))

    # ----------------------------------------------------------------- salvo

    def cycle_salvo_mode(self) -> str:
        """Y (salvo_mode binding): cycle the salvo mode RIPPLE -> FAN -> TOT and
        flash the selection.  Pure UI state — does not fire anything."""
        self.salvo_mode = next_salvo_mode(self.salvo_mode)
        hint = {"ripple": HINT_SALVO_MODE_RIPPLE,
                "fan": HINT_SALVO_MODE_FAN,
                "tot": HINT_SALVO_MODE_TOT}[self.salvo_mode]
        self.show_hint(hint)
        self.app.audio.ui_click()
        return self.salvo_mode

    def request_salvo(self):
        """F (salvo_fire binding): empty every currently-ready tube of the
        active platform in a controlled ripple (the SM-2 saturation king move).

        Reuses request_launch's per-platform target validation by firing the
        FIRST round through it (so an invalid selection flashes the SAME hint
        and nothing queues) — then queues the REMAINING ready tubes on the salvo
        scheduler.  A quick single press therefore still single-fires when only
        one tube is ready; with N ready it ripples all N.  Only the Bastion
        (Oniks/Zircon) and S-300 platforms salvo; other platforms (drone /
        swarm / buk) fall back to a single request_launch."""
        platform = self.active_platform
        if platform not in ("bastion", "s300"):
            return self.request_launch()        # no salvo for these platforms
        if platform == "bastion" and self.oniks_weapon == "kh31p":
            # The ARM homes on a selected EMITTER via its own launch path;
            # queued bastion beats call world.launch, which knows no "kh31p"
            # and silently fired ONIKS rounds at the stale surface aim point.
            return self.request_launch()
        ready = ready_tube_count(self.world, platform,
                                 sam_round=getattr(self, "sam_round", "48n6"))
        if ready <= 0:
            # Let request_launch surface the precise empty/reload/no-target hint.
            self.request_launch()
            return None
        # Fire the first round through the normal single-fire path so all the
        # target-type validation, hints, effects and camera anchor are reused.
        first = self.request_launch()
        if first is None:
            return None                          # validation failed: nothing queues
        remaining = ready - 1
        self._start_salvo(platform, remaining)
        count_total = remaining + 1
        hint = {"ripple": HINT_SALVO_RIPPLE,
                "fan": HINT_SALVO_FAN,
                "tot": HINT_SALVO_TOT}[self.salvo_mode]
        self.show_hint(hint % count_total)
        return first

    def _start_salvo(self, platform: str, remaining: int) -> None:
        """Arm the scheduler for the ``remaining`` tubes after the first round
        already fired through request_launch.  No-op when nothing remains."""
        if remaining <= 0:
            return
        seed = int(getattr(getattr(self.world, "_config", None), "seed", 0) or 0)
        if platform == "s300":
            self._salvo.start(
                "s300", mode=self.salvo_mode, count=remaining,
                interval=RIPPLE_INTERVAL_S,
                target_id=self.tactical_map.selected_contact,
                round_id=self.sam_round, seed=seed)
            return
        # Bastion Oniks/Zircon: queue the remaining tubes at the same aim point.
        offsets = None
        if self.salvo_mode == "tot" and self.target_point is not None:
            # TOT stagger from a coarse per-round flight-time estimate: every
            # remaining round flies the SAME aim point here (a single surface
            # target), so the ranges are equal and the delays collapse to 0 —
            # the stagger is meaningful once FAN spreads the aim (future) or for
            # multiple aim points.  Computed deterministically all the same.
            base = np.asarray(BASE_POS, dtype=np.float64)
            rng = float(np.hypot(self.target_point[0] - base[0],
                                 self.target_point[2] - base[2]))
            offsets = tot_delays([rng] * remaining, SALVO_TOT_FALLBACK_SPEED)
        self._salvo.start(
            "bastion", mode=self.salvo_mode, count=remaining,
            interval=RIPPLE_INTERVAL_S, profile=self.profile,
            target_point=self.target_point, weapon_id=self.oniks_weapon,
            seed=seed, offsets=offsets, waypoints=tuple(self.waypoints))

    def _tick_salvo(self, dt: float) -> None:
        """Advance the salvo BEFORE world.step so a due round enters this frame.
        Each launched round gets the same launch effects + camera anchor as a
        single fire (the queue calls world.launch / world.launch_sam, which
        returns None for a tube that turned out RELOADING/EMPTY — a graceful
        no-op beat)."""
        if not self._salvo.active:
            return
        # The queue calls world.launch / world.launch_sam, which append the new
        # round and return it (or return None for a tube that turned out
        # RELOADING/EMPTY — a graceful no-op beat).  A returned round is always
        # the player's OWN freshly-launched missile, so applying friendly launch
        # effects to it reads no enemy state.
        rnd = self._salvo.tick(dt, self.world)
        if rnd is not None:
            self._apply_launch_fx(rnd)

    def _apply_launch_fx(self, m) -> None:
        """The shared per-round launch presentation (camera anchor + muzzle /
        cold-launch effects + audio + shake), reused by single-fire and salvo.
        Oniks/Zircon/ASBM fire a hot muzzle blast; the S-300 a cold-launch puff
        (no flame until the hang-apex ignition)."""
        self.followed = m
        self.rig.retarget()
        # AsbmMissile subclasses SamMissile for the flight machine but fires
        # from the Bastion battery — a hot muzzle launch like the docstring
        # says, not the S-300 cold puff (the bare isinstance routed a
        # salvo-queued ASBM to the wrong presentation).
        from sim.asbm import AsbmMissile
        if isinstance(m, SamMissile) and not isinstance(m, AsbmMissile):
            self._launch_puff(m.pos)
            self._spawn_cover_debris(m.pos)
            self.app.audio.play("launch", pos=m.pos)
            return
        self.effects.muzzle_blast(m.pos, ground_y=float(self._tel_pos[1]) + 1.5)
        self._spawn_cover_debris(m.pos)
        self.app.audio.play("launch", pos=m.pos)
        self.rig.kick_shake(SHAKE_MUZZLE, pos=m.pos)

    def warp_drop_active(self) -> bool:
        """The OR of every reason the effective time scale must sit at 1x: the
        launch cinematic lock, an in-flight salvo window, and (M6 auto-warp)
        the fog-safe event-drop predicates (inbound DETECTED / own terminal /
        intercept window).  FOG-SAFE: ``event_drop`` reads only the player's
        detected picture for the inbound case (an undetected hostile never
        drops the warp).  Used both as the legacy hard 1x lock and as the
        ``drop_active`` fed to the auto-warp director."""
        return (launch_realtime_lock(self.world.missiles)
                or self._salvo.active
                or event_drop(self.world))

    def effective_time_scale(self) -> float:
        """The time scale fed to the App loop's accumulator.

        AUTO-WARP OFF (default, byte-identical): the requested accel, hard-
        forced to 1x through the launch cinematic / a queued salvo (the legacy
        behaviour — event drops are NOT applied so existing play is unchanged).

        AUTO-WARP ON: the smoothly-eased scale the director computed from
        ``warp_drop_active`` on the previous frame's real-dt tick — it auto-
        drops to 1x on important events (+ a >=1 s debounce dwell) and ramps
        back toward the requested target.  The warp stays a PURE multiplier on
        accumulated sim time, so the commander / back-plot is bit-identical at
        any warp for a given seed.
        """
        ctl = self.controls
        if getattr(ctl, "auto_warp", False):
            return ctl.warp_director.effective
        if launch_realtime_lock(self.world.missiles) or self._salvo.active:
            return 1.0
        return ctl.requested_scale

    # ------------------------------------------------------------ sim step

    def handle_event(self, ev) -> None:
        self.controls.handle_event(ev)

    def sim_step(self, dt: float) -> None:
        world = self.world
        # M6 salvo: fire any queued ripple round BEFORE world.step so the new
        # round enters this frame's physics (idle queue -> no-op, byte-identical).
        self._tick_salvo(dt)
        prev = [(m, m.phase) for m in world.missiles]
        world.step(dt)
        self.tactical_map.record(world)     # map trails + tracked target
        live = {id(m) for m in world.missiles}

        self._missile_effects(world.missiles, dt)
        for m, phase in prev:               # launch-sequence seams (Task LC)
            if id(m) not in live:
                continue
            if isinstance(m, SamMissile):
                if phase == SPH_EJECT and m.phase == SPH_BOOST:
                    self._sam_ignition(m)   # hang ends: fireball + donut
                continue
            if phase == PH_PITCHOVER and m.phase == PH_BOOST:
                self._cap_jettison(m)       # cap shot forward + full grunt
            elif phase == PH_BOOST and m.phase in RAMJET_PHASES:
                self._slug_ejection(m)      # burnout: slug out the nozzle
        for key in list(self._trails):      # finish trails of dead missiles
            if key not in live:
                self._trails.pop(key).finished = True
                self._puff_acc.pop(key, None)
        for key in list(self._ramjet_acc):  # drop dead rounds' feed debt
            if key not in live:
                del self._ramjet_acc[key]

        events = world.drain_events()
        # Ledger tap (AI-testability build): CombatState records the drained
        # effect events into the battle ledger; the base class ignores them.
        # Pure observation — the effects loop below consumes the same list.
        self._on_world_events(events)
        for kind, pos in events:
            if kind == "ship_hit":
                self.effects.explosion(pos, EXPLOSION_SCALE_SHIP,
                                       water=pos[1] < SHIP_HIT_SPLASH_MAX_Y)
                self.app.audio.boom(pos)
            elif kind in ("splash", "aircraft_splash"):
                self.effects.splash(pos, scale=SPLASH_SCALE)
                self.app.audio.play("splash", pos=pos)
            elif kind in ("sam_kill", "oniks_intercepted", "ciws_kill",
                          "pantsir_kill"):
                # Air burst, no water spray: a fuse kill on an aircraft, an
                # interceptor downing an Oniks, a CIWS kill and a Pantsir
                # 57E6/30 mm kill all read as the same mid-air explosion
                # (COMBAT Phase 2/6 event kinds).
                self.effects.explosion(pos, EXPLOSION_SCALE_AIR)
                self.app.audio.play("boom_far", pos=pos)
            elif kind == "sam_self_destruct":
                self.effects.explosion(pos, EXPLOSION_SCALE_SELFD)
                self.app.audio.play("boom_far", pos=pos)
            elif kind == "base_hit":
                # Enemy strike round into a base structure (Phase 3).
                self.effects.explosion(pos, EXPLOSION_SCALE_GROUND)
                self.app.audio.boom(pos)
            elif kind == "base_destroyed":
                # The killing hit also emitted base_hit at the same point:
                # the structure's secondary blast stacks on the warhead's.
                self.effects.explosion(pos, EXPLOSION_SCALE_SHIP)
                self.app.audio.boom(pos)
            elif kind in ("ciws_burst", "pantsir_gun"):
                # Shell burst near the target: a few grey flak puffs, no
                # audio (the gun is kilometers away from any camera that
                # is not already deafened by the explosion that follows).
                # The Pantsir 30 mm reuses the same CIWS flak visual.
                self.effects.smoke.emit(
                    3, pos, 6.0, (0.0, 2.0, 0.0), 5.0, (0.4, 0.9),
                    (1.5, 5.0), ((0.55, 0.55, 0.57), (0.40, 0.40, 0.42)),
                    self.effects.rng)
            elif kind == "pantsir_launch":
                # 57E6 rail launch (Phase 6): an ignition fireball + boom at
                # the launcher.  The round itself ALSO gets the standard SAM
                # ignition fireball when its EJECT->BOOST seam is detected in
                # _missile_effects, so this is the muzzle cue at the vehicle.
                self.effects.ignition_fireball(pos)
                self.app.audio.play("boom_near", pos=pos)
            else:                           # ground_hit / aircraft_down
                self.effects.explosion(pos, EXPLOSION_SCALE_GROUND)
                self.app.audio.boom(pos)

        self._ship_fires(dt)
        self._aircraft_smoke(dt)
        self._update_parts(dt)
        self._update_tel(dt)
        # GRAPHICS settings act LIVE: refresh the emission knobs from the
        # persisted prefs each frame (a cheap dict read — the settings tab
        # needs no plumbing back into the sandbox).
        prefs = getattr(self.app, "ui_prefs", None)
        if prefs is not None:
            self.effects.density = prefs.particle_density_scale()
            self.effects.launch_fx = (1.0 if prefs.get("launch_smoke")
                                      == "full" else 0.4)
        self.effects.update(dt)

    def _on_world_events(self, events) -> None:
        """Hook for the battle ledger (CombatState overrides).  The base
        sandbox keeps no ledger — a deliberate no-op."""

    def _missile_effects(self, missiles, dt: float) -> None:
        """Exhaust trail feed + plume emission for every live missile.

        Runs per 120 Hz substep: positions/directions are plain-float
        tuples (Task GATE perf — no numpy temporaries per missile per
        substep; every consumer coerces with np.asarray as needed)."""
        fx = self.effects
        for m in missiles:
            key = id(m)
            px, py, pz = m.pos.tolist()
            vx, vy, vz = m.vel.tolist()
            speed = math.sqrt(vx * vx + vy * vy + vz * vz)
            if speed > 1e-9:
                inv = 1.0 / speed
                hx, hy, hz = vx * inv, vy * inv, vz * inv
            else:
                hx, hy, hz = 0.0, 1.0, 0.0
            if isinstance(m, SamMissile):
                if m.phase == SPH_BOOST:    # torch + trail END at burnout
                    tail = (px - hx * SAM_HALF_LEN, py - hy * SAM_HALF_LEN,
                            pz - hz * SAM_HALF_LEN)
                    self._trail_for(key).add_point(tail)
                    fx.booster_plume(tail, (hx, hy, hz), 1.0)
                continue
            if isinstance(m, StrikeMissile):
                # Phase 3 enemy strikes: solid-booster torch + trail only.
                # The turbofan/sustainer cruise shows no plume (a smokeless
                # Tomahawk at 50 m AGL 150 km out would be sub-pixel anyway);
                # dedicated wake/model polish is Phase-7 backlog.
                if m.phase == SPH_STRIKE_BOOST:
                    tail = (px - hx * MISSILE_HALF_LEN,
                            py - hy * MISSILE_HALF_LEN,
                            pz - hz * MISSILE_HALF_LEN)
                    self._trail_for(key).add_point(tail)
                    fx.booster_plume(tail, (hx, hy, hz), 1.0)
                continue
            tail = (px - hx * MISSILE_HALF_LEN, py - hy * MISSILE_HALF_LEN,
                    pz - hz * MISSILE_HALF_LEN)
            if m.phase in LAUNCH_TRAIL_PHASES:      # the heavy cream column
                self._trail_for(key).add_point(tail)
                fx.rideout_plume(tail, (hx, hy, hz))
                if m.phase == PH_PITCHOVER:
                    self._nose_puffs(m, np.array((hx, hy, hz)), dt)
            elif m.phase == PH_BOOST:               # 4x bloom, grey trail
                self._trail_for(key).add_point(tail, col=TRAIL_BOOST_COL)
                fx.boost_plume(tail, (hx, hy, hz))
            elif m.phase in RAMJET_PHASES and m.fuel > 0.0:
                # Near-transparent ramjet: tiny jet + faint haze, NO ribbon.
                # Period-fed (sim time), not per-substep — dt < period, so
                # at most one emission per step and no catch-up clumping.
                acc = self._ramjet_acc.get(key, RAMJET_EMIT_PERIOD) + dt
                if acc < RAMJET_EMIT_PERIOD:
                    self._ramjet_acc[key] = acc
                    continue
                self._ramjet_acc[key] = acc - RAMJET_EMIT_PERIOD
                fx.fire.emit(
                    1, tail, 0.3,
                    (-hx * RAMJET_EXHAUST_SPEED, -hy * RAMJET_EXHAUST_SPEED,
                     -hz * RAMJET_EXHAUST_SPEED), 2.0,
                    RAMJET_FIRE_LIFE, RAMJET_FIRE_SIZE,
                    RAMJET_FIRE_COLORS, fx.rng)
                fx.smoke.emit(
                    1, tail, 0.4, (-hx * 4.0, -hy * 4.0, -hz * 4.0), 1.0,
                    RAMJET_HAZE_LIFE, RAMJET_HAZE_SIZE,
                    RAMJET_HAZE_COLORS, fx.rng)

    def _trail_for(self, key):
        prefs = getattr(self.app, "ui_prefs", None)
        if prefs is not None and not prefs.get("exhaust_trails"):
            return _NULL_TRAIL      # EXHAUST TRAILS pref OFF: feed a sink
        trail = self._trails.get(key)
        if trail is None:
            trail = self._trails[key] = self.effects.add_trail()
        return trail

    def _nose_puffs(self, m, v, dt: float) -> None:
        """Orange pulse-jet puffs at the NOSE while the pitch-over turns —
        sideways, against the turn (the jets push the nose over)."""
        key = id(m)
        acc = self._puff_acc.get(key, NOSE_PUFF_PERIOD)  # first puff at once
        if acc < NOSE_PUFF_PERIOD:
            self._puff_acc[key] = acc + dt
            return
        self._puff_acc[key] = 0.0
        nose = m.pos + v * CAP_NOSE_AHEAD
        side = np.cross(v, _UP)
        n = float(np.linalg.norm(side))
        side = side / n if n > 1e-9 else np.array([1.0, 0.0, 0.0])
        up_ish = np.cross(side, v)
        self.effects.nose_puff(nose, up_ish + side * 0.3)

    def _cap_jettison(self, m) -> None:
        """End of tip-over: the pull-away motors shoot the nose cap FORWARD;
        the missile out-accelerates it on the freshly lit high-thrust mode.
        Sound: the cap CRACK over the roar, then the full-thrust slam."""
        v = _vhat(m)
        side = np.cross(v, _UP)
        n = float(np.linalg.norm(side))
        side = side / n if n > 1e-9 else np.array([1.0, 0.0, 0.0])
        kick = (m.vel + v * CAP_FWD_KICK + side * CAP_SIDE_KICK
                - _UP * CAP_DROP_KICK)
        self._parts.append((self._mesh_cap, _FallingPart(
            m.pos + v * CAP_NOSE_AHEAD, kick, v,
            CAP_DRAG, CAP_TUMBLE_RATE, CAP_LIFE)))
        self.app.audio.play("cap_crack", pos=m.pos)
        self.app.audio.play("slam", pos=m.pos)
        self.rig.kick_shake(SHAKE_SLAM, pos=m.pos)

    def _slug_ejection(self, m) -> None:
        """Mach-2 burnout: ram air expels the spent booster slug out the
        nozzle; the thick launch trail STOPS here."""
        v = _vhat(m)
        self._parts.append((self._mesh_slug, _FallingPart(
            m.pos - v * SLUG_TAIL_BACK, m.vel - v * SLUG_BACK_KICK, v,
            SLUG_DRAG, SLUG_TUMBLE_RATE, SLUG_LIFE)))
        trail = self._trails.pop(id(m), None)
        if trail is not None:
            trail.finished = True       # ages out; no new points in cruise

    def _sam_ignition(self, m) -> None:
        """S-300 motor light-off at the hang apex: instantaneous fireball
        wider than the missile + the expanding smoke donut, a detonation-
        grade boom (boom_near family) and a camera shake pulse — ending the
        1.5 s of near-silence."""
        v = _vhat(m)
        self.effects.ignition_fireball(m.pos - v * SAM_HALF_LEN)
        self.app.audio.play("boom_near", pos=m.pos)
        self.rig.kick_shake(SHAKE_SAM_IGNITION, pos=m.pos)

    def _launch_puff(self, mouth_pos) -> None:
        """Cold-launch gas puff at the canister mouth (the eject is unlit)."""
        self.effects.smoke.emit(
            LAUNCH_PUFF_COUNT, mouth_pos, 1.2, (0.0, 4.0, 0.0), 3.0,
            (1.5, 3.0), (2.0, 9.0),
            ((0.85, 0.84, 0.82), (0.55, 0.55, 0.58)), self.effects.rng)

    def _ship_fires(self, dt: float) -> None:
        """Deck fire + smoke for burning/sinking ships near the camera."""
        eye = self.camera.eye
        for ship in self.world.ships:
            if ship.state not in (ST_BURNING, ST_SINKING):
                self._fire_acc.pop(ship.ship_id, None)
                continue
            sp = ship.pos
            dx = sp[0] - eye[0]
            dy = sp[1] - eye[1]
            dz = sp[2] - eye[2]
            if math.sqrt(dx * dx + dy * dy + dz * dz) > SHIP_FIRE_VIS_RANGE:
                continue
            acc = self._fire_acc.get(ship.ship_id, 0.0) + dt
            if acc >= SHIP_FIRE_PERIOD:         # deck temp only when emitting
                deck = ship.pos + _UP * (ship.height * SHIP_FIRE_DECK_FRAC)
                while acc >= SHIP_FIRE_PERIOD:
                    acc -= SHIP_FIRE_PERIOD
                    self.effects.ship_fire(deck)
            self._fire_acc[ship.ship_id] = acc

    def _aircraft_smoke(self, dt: float) -> None:
        """Black smoke + flame streaming behind a falling aircraft (the S1
        kill ladder), emitted only near the camera like the deck fires."""
        eye = self.camera.eye
        for ac in self.world.aircraft:
            if ac.state != AC_FALLING:
                self._ac_smoke_acc.pop(ac.aircraft_id, None)
                continue
            p = ac.pos
            dx = p[0] - eye[0]
            dy = p[1] - eye[1]
            dz = p[2] - eye[2]
            if (math.sqrt(dx * dx + dy * dy + dz * dz)
                    > AIRCRAFT_SMOKE_VIS_RANGE):
                continue
            acc = self._ac_smoke_acc.get(ac.aircraft_id, 0.0) + dt
            rng = self.effects.rng
            while acc >= AIRCRAFT_SMOKE_PERIOD:
                acc -= AIRCRAFT_SMOKE_PERIOD
                self.effects.smoke.emit(
                    1, p, 1.5, (0.0, 2.0, 0.0), 2.5, (3.0, 7.0), (2.5, 14.0),
                    ((0.10, 0.10, 0.10), (0.30, 0.30, 0.32)), rng)
                self.effects.fire.emit(
                    1, p, 1.0, (0.0, 1.0, 0.0), 2.0, (0.25, 0.6), (1.5, 3.5),
                    ((1.0, 0.75, 0.30), (0.85, 0.22, 0.05)), rng)
            self._ac_smoke_acc[ac.aircraft_id] = acc

    def _update_parts(self, dt: float) -> None:
        for _, p in self._parts:
            p.update(dt)
        self._parts = [
            (mesh, p) for mesh, p in self._parts
            if not p.expired(self.world.surface_height_at(
                float(p.pos[0]), float(p.pos[2])))]

    def _update_tel(self, dt: float) -> None:
        """Swing the canisters up when armed, down while reloading."""
        target = 1.0 if self.world.launcher_armed else 0.0
        step = dt / TEL_ERECT_TIME
        delta = min(max(target - self._tel_frac, -step), step)
        self._tel_frac = min(max(self._tel_frac + delta, 0.0), 1.0)

    # ---------------------------------------------------------------- audio

    def _loop_sources(self) -> dict:
        """Per-missile engine loops for AudioManager.update_loops: the Oniks
        rides a low-gain booster roar through IGNITION/RIDE-OUT/PITCH-OVER
        (the 'rising roar'), full gain through the high-thrust BOOST, then
        the ramjet hiss; the S-300 roars only while its motor burns (the
        eject hang is near-silent — that pause is sacred). Empty while
        paused (a frozen sim should not roar)."""
        if self.app.paused:
            return {}
        sources = {}
        for m in self.world.missiles:
            if isinstance(m, SamMissile):   # solid motor roar, silent coast
                if m.phase == SPH_BOOST:
                    sources[id(m)] = ("booster", m.pos, BOOSTER_LOOP_GAIN)
            elif m.phase in (PH_EJECT, PH_RIDEOUT, PH_PITCHOVER):
                sources[id(m)] = ("booster", m.pos, RIDEOUT_LOOP_GAIN)
            elif m.phase == PH_BOOST:
                sources[id(m)] = ("booster", m.pos, BOOSTER_LOOP_GAIN)
            elif m.phase in RAMJET_PHASES and m.fuel > 0.0:
                sources[id(m)] = ("cruise", m.pos, CRUISE_LOOP_GAIN)
        return sources

    # ----------------------------------------------------------- state hooks

    def leave(self) -> None:
        """ESC to menu: silence the engine loops, release any mouse grab."""
        self.app.audio.stop_loops()
        self.controls.release_mouse()

    def dispose(self) -> None:
        """Free this session's GL objects (called when SANDBOX restarts)."""
        meshes = ([self._mesh_oniks, self._mesh_oniks_capped,
                   self._mesh_oniks_folded, self._mesh_cap, self._mesh_slug,
                   self._mesh_cover, self._mesh_sam_pad, self._mesh_s300_tel]
                  + list(self._missile_meshes.values())
                  + list(self._aircraft_meshes.values())
                  + list(self._ship_meshes.values()) + self._tel_meshes
                  + [mesh for mesh, _ in self._site_draws])
        for mesh in meshes:
            mesh.delete()
        self.terrain.delete()
        self.ocean.delete()
        self.sky.delete()
        self.particles.delete()
        self.tactical_map.delete()
        self.text.delete()

    # --------------------------------------------------------------- render

    def render(self, dt_real: float) -> None:
        # Fresh UI hit/tag registry every frame: draw sites re-register
        # their rects below (mouse parity + F3 tagging + overlap oracle).
        self.ui.begin_frame()
        self.controls.update(dt_real)            # free-cam flies in real time
        self.rig.update(dt_real, self.followed)
        if self.hint_left > 0.0:
            self.hint_left = max(0.0, self.hint_left - dt_real)
        audio = self.app.audio
        audio.set_listener(self.camera.eye)      # gains follow the camera
        audio.update_loops(self._loop_sources())
        w, h = self.window.size()
        self._draw_scene(w, h)
        if self.map_open:
            self.tactical_map.update(dt_real)   # arrow-key panning
            self.tactical_map.draw(w, h)
            # F1 must work over the MAP too (it silently no-oped: the overlay
            # only drew inside hud.draw, which the map branch skips).
            if self.controls_overlay:
                self.hud._controls_overlay(self, w, h)
                self.hud.text.flush(w, h)
            # LAUNCH CINEMA PiP (2026-07-05, F5/chip toggle): a corner
            # viewport showing the launching round cinematically while the
            # cinematic lock is live.
            if self._launch_pip_active():
                self._draw_launch_pip(w, h)
        elif self.hud_visible:
            self.hud.draw(self, w, h)

    def _launch_pip_active(self) -> bool:
        """The map LAUNCH CINEMA PiP runs only while the pref is ON and a
        launch cinematic is actually playing (the same realtime-lock window
        that pins the time scale to 1x)."""
        prefs = getattr(self.app, "ui_prefs", None)
        if prefs is None or not prefs.get("launch_cinema"):
            return False
        return launch_realtime_lock(self.world.missiles)

    def _draw_launch_pip(self, w: int, h: int) -> None:
        """Second scene pass into a scissored corner viewport: a side-on
        cinematic of the newest own round leaving the rail, over the map.
        Fill cost is the small viewport; it runs ONLY for the seconds the
        launch cinematic is live.  Toggle: F5 or the board's CINEMA chip."""
        m = next((mm for mm in reversed(self.world.missiles)
                  if not getattr(mm, "is_hostile", False)), None)
        if m is None:
            return
        from OpenGL import GL as gl

        from game.states import ACCENT_DIM, FAINT
        pw, ph = max(64, int(w * 0.24)), max(64, int(h * 0.26))
        px, py = w - pw - 16, h - ph - 110      # above the corner readout
        v = _vhat(m)
        side = np.array([v[2], 0.0, -v[0]])
        n = math.hypot(side[0], side[2])
        side = side / n if n > 1e-6 else np.array([1.0, 0.0, 0.0])
        eye = m.pos + side * 60.0 - v * 25.0 + _UP * 18.0
        self._pip_cam.set_look(eye, m.pos)
        gly = h - py - ph                       # GL origin: bottom-left
        gl.glEnable(gl.GL_SCISSOR_TEST)
        gl.glScissor(px, gly, pw, ph)
        gl.glViewport(px, gly, pw, ph)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        cam = self.camera
        self.camera = self._pip_cam
        try:
            self._draw_scene(pw, ph)
        finally:
            self.camera = cam
            gl.glDisable(gl.GL_SCISSOR_TEST)
            gl.glViewport(0, 0, w, h)
        # Frame + caption, drawn in the normal full-screen batch.
        text = self.text
        text.draw_lines([(px, py), (px + pw, py), (px + pw, py + ph),
                         (px, py + ph), (px, py)], (*ACCENT_DIM, 1.0), 1.0)
        from engine.text import SMALL_SIZE
        label = "LAUNCH CINEMA [F5]"
        text.draw_text(px + 8, py + ph - text.line_height(SMALL_SIZE) - 4,
                       label, FAINT, SMALL_SIZE)
        text.flush(w, h)
        self.ui.add("map.launch_cinema", px, py, pw, ph,
                    code="game/sandbox.py:_draw_launch_pip")

    def render_frozen(self) -> None:
        """The 3D scene exactly as last framed — no input/rig/audio updates,
        no HUD/map overlay. The pause menu draws this, then dims it."""
        w, h = self.window.size()
        self._draw_scene(w, h)

    def _draw_scene(self, w: int, h: int) -> None:
        self.renderer.begin(self.camera, w / h)
        self.sky.draw(self.renderer)
        self.terrain.draw(self.renderer)
        self.ocean.draw(self.renderer, self.camera, self.world.sim_time)
        for mesh, pos in self._site_draws:
            self.renderer.draw_mesh(mesh, pos)
        self._draw_ships()
        self._draw_aircraft()
        self._draw_tel()
        self._draw_missiles()
        self.particles.draw(self.renderer, self.effects)

    def _draw_ships(self) -> None:
        for ship in self.world.ships:
            if ship.state == ST_GONE:
                continue
            rot = rot_y(ship.heading) @ rot_z(ship.list_angle)
            # M5 #1: a Transport / LCAC has no dedicated mesh yet (DEFERRED) —
            # render on the closest existing hull: a TRANSPORT is a boxy
            # merchant (cargo mesh), an LCAC a small craft (warship mesh) —
            # a landing force must never read as a destroyer squadron.  Any
            # other unknown type still falls back to the destroyer hull.
            mesh = self._ship_meshes.get(ship.ship_type)
            if mesh is None:
                alias = SHIP_MESH_ALIAS.get(ship.ship_type)
                mesh = (self._ship_meshes.get(alias)
                        or self._ship_meshes.get("destroyer")
                        or next(iter(self._ship_meshes.values()), None))
                if mesh is None:
                    continue
            self.renderer.draw_mesh(mesh, ship.pos, rot)

    def _draw_aircraft(self) -> None:
        """Aircraft within visual range: yaw + the falling spiral's
        pitch/roll (rot_x(a) noses DOWN for a > 0; rot_z(a) lifts the +X
        right wing — hence both signs flipped)."""
        eye = self.camera.eye
        for ac in self.world.aircraft:
            if ac.state == AC_GONE:
                continue
            p = ac.pos
            dx = p[0] - eye[0]
            dy = p[1] - eye[1]
            dz = p[2] - eye[2]
            if (dx * dx + dy * dy + dz * dz
                    > AIRCRAFT_DRAW_RANGE * AIRCRAFT_DRAW_RANGE):
                continue                        # sub-pixel: skip the draw
            rot = rot_y(ac.heading) @ rot_x(-ac.pitch) @ rot_z(-ac.roll)
            self.renderer.draw_mesh(self._aircraft_meshes[ac.aircraft_type],
                                    p, rot)

    def _draw_tel(self) -> None:
        idx = int(round(self._tel_frac * (TEL_ELEV_STEPS - 1)))
        for pos in self._tel_positions:
            self.renderer.draw_mesh(self._tel_meshes[idx], pos)
        for pos in self._sam_tel_positions:
            self.renderer.draw_mesh(self._mesh_sam_pad, pos)
            self.renderer.draw_mesh(self._mesh_s300_tel, pos)

    def _draw_missiles(self) -> None:
        for m in self.world.missiles:
            # Body attitude, not the velocity vector: the airframe visibly
            # rotates ahead of the flight path through a turn (sim/missile.py
            # _update_body). _vhat stays the fallback for missiles without it.
            v = getattr(m, "body_dir", None)
            if v is None:
                v = _vhat(m)
            rot = math3d.rotation_from_forward(v)
            mesh_key = _missile_mesh_key(m)
            if mesh_key != "oniks":
                mesh = self._missile_meshes[mesh_key]
            elif m.phase in CAP_ON_PHASES:
                # launch variants: folded surfaces snap to X shortly after
                # muzzle clear; the SUO cap stays on until PITCHOVER ends
                deploy_t = m.weapon.eject_time + WING_DEPLOY_AFTER_EXIT
                mesh = (self._mesh_oniks_folded if m.t < deploy_t
                        else self._mesh_oniks_capped)
            else:
                mesh = self._mesh_oniks
            self.renderer.draw_mesh(mesh, m.pos, rot)
        for mesh, p in self._parts:     # tumbling caps / slugs / covers
            self.renderer.draw_mesh(mesh, p.pos, p.rot)
