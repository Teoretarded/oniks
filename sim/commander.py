"""Enemy commander AI — the brain on the enemy side (pure numpy, GL-free).

ORDER SCHEMA
============
Every order issued by EnemyCommander is a plain dict.  The integrator
(world/combat.py or a Phase-5b wiring layer) reads it and calls into the
relevant entity.  Defined schemas:

  VECTOR_TO_DRONE:
      {"type": "vector_to_drone", "fighter_id": str,
       "target_pos": np.ndarray,   # last-known XZ of the drone
       "aim9x": True}
      Instructs the named fighter to fly toward target_pos and engage with
      its IR missiles once close enough.  The fighter's own nose-radar
      reacquire + IR lock logic is downstream; the commander only says "go".

  AWACS_FLEE:
      {"type": "awacs_flee", "threat_pos": np.ndarray}
      Passed to Awacs.flee(); issued when a player missile track is within
      AWACS_FLEE_RANGE_M.

  AWACS_RESUME:
      {"type": "awacs_resume"}
      Passed to Awacs.stop_flee(); issued when no player missile track is
      within AWACS_FLEE_RANGE_M.

  SHIP_SILENT:
      {"type": "ship_silent", "ship_id": str}
      Tell the ship's radar to go silent (emitting = False).

  SHIP_EMIT:
      {"type": "ship_emit", "ship_id": str}
      Tell the ship's radar to start emitting (for self-defense).

  GROUND_RADAR_SILENT / GROUND_RADAR_EMIT:
      {"type": "ground_radar_silent"|"ground_radar_emit", "radar_id": str}
      ARM-EMCON (M2-T3): toggle an enemy coastal ground radar's emission. The
      commander silences a ground radar that SENSES an inbound ARM track
      (kind=="kh31p") within ARM_EMCON_RANGE_M (silence is the only counter a
      SAM-less ground radar has), and re-emits once the threat is clear and the
      dwell has elapsed.

  HARM_PACKAGE:
      {"type": "harm_package",
       "target_pos": np.ndarray,           # believed player radar XZ
       "target_id": str,                   # structure id in the enemy picture
       "fighter_ids": list[str],           # exactly 2 fighters
       "harms_per_fighter": int,           # 2
       "ingress_alt_m": float,             # HARM_INGRESS_ALT_M = 150
       "standoff_m": float}                # HARM_STANDOFF_M = 90_000
      Instructs two fighters to fly a HARM strike package.  Ingress LOW
      inside the player radar horizon-extended envelope, pop to cruise alt
      and release at standoff.

  JASSM_PACKAGE:
      {"type": "jassm_package",
       "target_pos": np.ndarray,           # believed bastion XZ
       "target_id": str,                   # cluster id
       "fighter_ids": list[str],           # exactly 2 fighters
       "jassms_per_fighter": int,          # 2
       "standoff_m": float}                # JASSM_STANDOFF_M = 250_000
      Instructs two fighters to release JASSMs at the cluster from standoff.

  TOMAHAWK_SALVO:
      {"type": "tomahawk_salvo",
       "target_pos": np.ndarray,           # believed bastion XZ
       "target_id": str}                   # cluster id
      Triggers EnemyStrikeController-style Tomahawk salvo at a bastion
      cluster (the docstring seam).  The integrator calls
      commander.fire_tomahawk_at(target_pos) or wires its own salvo
      mechanism; the order signals intent.

INTEL MODEL
===========
The commander holds an EnemyPicture: a side-level intel store derived
entirely from sensor events the enemy side can physically observe.
No truth peeking — every targeting decision traces to a sensor event.

  emitter_intel: emitter_id -> {"pos": ..., "alive": bool, "fix": float}
      Built from ESM localization progress (generalized from
      sim/enemy_strikes.py): a fix accumulates while the radar emits and
      any enemy sensor can hear it.

  launch_back_plots: list of BackPlotEntry
      When an enemy radar (typically the AWACS look-down) holds a track on
      a player missile whose first-detected altitude is < BACKPLOT_LOW_ALT_M
      and first-detected age is < BACKPLOT_MAX_AGE_S, the observed velocity
      is extrapolated backward to the surface to estimate the launch site.
      Error grows with detection range (BACKPLOT_ERR_FRAC * range).
      After BACKPLOT_FIXES_NEEDED distinct back-plots cluster within
      BACKPLOT_CLUSTER_R_M, the cluster is TARGETABLE.

  known_structures: structure_id -> {"pos": ..., "alive": bool, "kind": str}
      Radar station: located via ESM fix.
      Bastion clusters: located via back-plot accumulation.
      A structure is marked alive=False when a friendly weapon records an
      impact on it (observed outcome); it is marked alive=True again when
      the emitter re-lights (the belief is reset by evidence).

DOCTRINE (priority order, evaluated each tick)
===============================================
1. DEFEND:
   - Vector the nearest armed CAP fighter at any drone track the picture
     holds (AIM-9X hunt order VECTOR_TO_DRONE).
   - AWACS: flee when any player missile track closes to AWACS_FLEE_RANGE_M;
     resume orbit when clear.
   - Ship radar silence: SILENT when a drone track exists in the picture
     and the ship's sector is quiet; EMIT when inbound missile tracks exist
     (self-defense beats stealth).
   - ARM-EMCON (M2-T3): a SENSED ARM track (kind=="kh31p") within
     ARM_EMCON_RANGE_M of a ship OR ground radar -> that radar goes SILENT for
     ARM_EMCON_DWELL_S (overriding ship self-defense — emitting feeds the ARM
     seeker; silence degrades the live ARM to its CEP ring). Sensor-triggered
     off the picture track, never the ARM's truth.

2. BLIND:
   While the player radar station is believed alive and located, and HARM
   stock remains, schedule HARM strike packages
   (2 fighters, 2 HARM each, HARM_INGRESS_ALT_M = 150 m inside the
    radar's horizon-extended envelope, pop to HARM_STANDOFF_M = 90 km).

3. KILL:
   While a bastion cluster is targetable:
   - JASSM packages (2 fighters x 2 JASSM, JASSM_STANDOFF_M = 250 km).
   - Tomahawk salvos (TOMAHAWK_SALVO orders at the cluster).

DETERMINISM
===========
Given the same seed and the same sequence of picture updates the commander
produces identical orders.  Internal random state is carried by a single
np.random.Generator seeded once at construction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

# ---------------------------------------------------------------------------
# Module-level constants (all named with units and justification comments)
# ---------------------------------------------------------------------------

# ESM fix accumulation: generalised from sim/enemy_strikes.py.
ESM_FIX_TIME_S: float = 90.0       # s of cumulative emission for a full fix
ESM_DECAY_FACTOR: float = 0.5      # silent decay rate = half the accrual rate

# Back-plot geometry (spec section 6 "back-plot launch point").
BACKPLOT_LOW_ALT_M: float = 2_000.0   # m; missile must be below this when
#                                        first detected to back-plot cleanly
BACKPLOT_MAX_AGE_S: float = 30.0      # s; track age at first detection must
#                                        be <= this (young track = fresh launch)
BACKPLOT_ERR_FRAC: float = 0.02       # error = detection range × this fraction
#                                        (2% of range: at 50 km = 1 km error)
BACKPLOT_CLUSTER_R_M: float = 3_000.0  # m cluster radius — back-plots within
#                                         this distance belong to one launch site
BACKPLOT_FIXES_NEEDED: int = 3        # distinct launches before targetable
# The player ("home") coastline sits at z = 0 in world.generation (land at
# z < 0, the enemy continent to the north). A level sea-skimmer's launch point
# lies back along its ground track where that track crosses this shoreline — the
# enemy knows the coast geometry; the bearing fixes WHERE along it the round was
# fired. (A boost-phase climb is instead back-projected in time to the surface.)
HOME_COAST_Z: float = 0.0
BACKPLOT_CLIMB_VY: float = 50.0       # m/s; above this the round is still in its
#                                       boost climb near launch -> time-project
#                                       to the surface (accurate close in). At or
#                                       below it the round is in level cruise far
#                                       downrange -> project the track to the coast.
BACKPLOT_MIN_CLOSE_VZ: float = 50.0   # m/s; a level track must be closing toward
#                                       the coast at least this fast to localize
#                                       (a coast-parallel / receding dogleg is not).

# AWACS flee range (spec section 6 "AWACS: order flee when any player missile
# track closes within ...").
AWACS_FLEE_RANGE_M: float = 100_000.0  # m
AWACS_EMCON_DWELL_S: float = 60.0     # s the AWACS holds SILENT after a threat
#   was last seen, before re-emitting. EMCON anti-strobe: a silenced AWACS that
#   is the sole sensor on the threat loses its own (now-dark) track when it ages
#   out (~30 s), which would otherwise make it un-blind itself and re-detect the
#   still-inbound missile — a radiating blink at the worst moment. The dwell
#   rides out the whole terminal threat window (a missile within the 100 km flee
#   range closes in well under this) so the radar comes back up only once the
#   sky is genuinely clear. Re-emits immediately if NO threat for the dwell.

# ARM-EMCON (M2-T3): an enemy radar that SENSES an inbound anti-radiation
# missile track (kind == "kh31p") within this threat radius goes SILENT for a
# dwell — the counter to the player Kh-31P. Emitting would feed the ARM's
# passive seeker, so silence (which degrades the live ARM to its seeded CEP
# ring — "a silenced radar usually survives") OVERRIDES the ship self-defense
# emit. 60 km sits inside the Kh-31P's measured ~130 km reach with margin: the
# radar darks well before the round closes to a terminal lock, but not so far
# out that every distant snooper pins it silent.
ARM_EMCON_RANGE_M: float = 60_000.0   # m; sensed-ARM threat radius -> EMCON
ARM_EMCON_DWELL_S: float = AWACS_EMCON_DWELL_S  # 60 s; hold silent after the
#   ARM track was last seen (mirrors the AWACS EMCON anti-strobe: a radar that
#   un-blinds the instant its own dark track ages out re-radiates at the worst
#   moment — the dwell rides out the terminal threat window).

# M3-F2 escort jammer (Growler) doctrine. The jammer is a fat always-on beacon
# the player can ELINT-localize + SEAD; the brain (_defend_jammer) trades the
# corridor for survival when threatened — exactly the AWACS EMCON pattern.
JAMMER_THREAT_RANGE_M: float = 90_000.0  # m; a sensed inbound ARM/SAM missile
#   track within this radius of the jammer makes it LIFT the jam (go dark) — the
#   jammer's emission is what a radiation-homing seeker chases, so lifting (which
#   degrades the live round) is the survivable counter, mirroring ARM-EMCON.
#   90 km is wider than the ship ARM_EMCON_RANGE_M (the slow, deep, defenceless
#   jammer reacts earlier than a SAM-armed hull) yet inside a closing round's
#   terminal window, so a far snooper does not pin the corridor down.
JAMMER_FLEE_RANGE_M: float = 90_000.0    # m; a closing missile track inside this
#   radius ALSO orders a flee toward the carrier (same trigger geometry as the
#   lift — the jammer both darks AND runs; reuses the AWACS flee()).
JAMMER_EMCON_DWELL_S: float = AWACS_EMCON_DWELL_S  # 60 s; hold the jam LIFTED
#   after the threat track was last seen before re-radiating — the AWACS EMCON
#   anti-strobe dwell, so the corridor does not blink the instant the jammer's
#   own dark track ages out (re-illuminating at the worst moment).
JAMMER_RESTATION_EPS_RAD: float = math.radians(3.0)  # the believed-emitter
#   bearing must move at least this much before the jammer re-stations its orbit
#   — anti-strobe so a jittering ESM fix doesn't re-issue a station order every
#   tick (mirrors the AWACS/ARM "enter once" discipline for the STATION half).
# Standoff distance (m) from the fleet centroid the commanded STATION point
# sits along the believed-emitter bearing.  MUST match the flight model's
# sim.enemy_air.JAMMER_STANDOFF_M (and sim.ew.EW_DEFAULT_STANDOFF_M) so the
# calibrated burn-through holds — kept as a doctrine constant here to avoid a
# circular import of the flight module at module load.
JAMMER_STANDOFF_M: float = 150_000.0

# Strike geometry (spec section 6 mission generator).
HARM_INGRESS_ALT_M: float = 150.0     # m AGL ingress altitude for HARM package
HARM_STANDOFF_M: float = 90_000.0     # m HARM launch standoff (within HARM
#                                        max range, outside player radar horizon)
JASSM_STANDOFF_M: float = 250_000.0   # m JASSM launch standoff (outside S-300
#                                        max range 150 km — gives ~100 km margin)

# Weapon magazine stocks per platform (spec section 6 mission generator).
AIRFIELD_JASSM: int = 8
AIRFIELD_HARM: int = 8
CARRIER_JASSM: int = 6
CARRIER_HARM: int = 6
# AIM-9X: unlimited pairs at rearm (spec §5.1 "2 × AIM-9X-class IR missiles").
# The magazine never runs out; we represent it as a large pool per fighter
# for stock checks (each fighter carries 2 per sortie, unlimited at rearm).
AIM9X_PER_FIGHTER: int = 2

# Commander tick cadence (spec section 6: "~1 Hz").
COMMANDER_TICK_S: float = 1.0   # s between doctrine evaluations

# HARM fighters approach inside the player radar horizon before popping; using
# the player's horizon-vs-fighter as a proxy for "when the player can see us"
# gives a conservative estimate — we subtract a safety margin to stay masked.
# Derived: player radar antenna 18 m, fighter 9 000 m → horizon ~393 km vs
# the radar station for a high-flying fighter.  The ingress at 150 m reduces
# the combined horizon to ~37 km.  We use the param HARM_STANDOFF_M as the
# pop-up point instead of computing this live — the mission generator passes
# it to the fighter as a standoff parameter; execution is downstream.


# ---------------------------------------------------------------------------
# Internal data structures
# ---------------------------------------------------------------------------

@dataclass
class EmitterIntel:
    """What the enemy side knows about one player radar emitter."""
    emitter_id: str
    believed_pos: np.ndarray          # (3,) float64, XYZ estimate
    alive: bool = True
    fix_progress: float = 0.0         # 0..1; 1 = firing-quality fix
    last_heard_t: float = -1.0        # sim_time of last ESM interception

    @property
    def located(self) -> bool:
        # Use >= (1 - epsilon) to handle floating-point accumulation near the
        # limit (90 integer dt steps of 1/90 each may land at 0.9999...84).
        return self.fix_progress >= (1.0 - 1e-9)


@dataclass
class BackPlotEntry:
    """One back-plotted launch-site estimate."""
    estimated_pos: np.ndarray   # (2,) XZ estimate
    error_m: float              # 1-sigma position error (detection range × frac)
    sim_time: float             # when this estimate was produced
    track_id: str               # missile track that generated this fix


@dataclass
class LaunchCluster:
    """A grouping of back-plot estimates that has accumulated enough fixes
    to be considered a confirmed launch site."""
    centre: np.ndarray          # (2,) XZ centroid of the cluster
    fixes: list[BackPlotEntry] = field(default_factory=list)
    believed_alive: bool = True

    @property
    def targetable(self) -> bool:
        """True once BACKPLOT_FIXES_NEEDED distinct launches have been observed
        from within BACKPLOT_CLUSTER_R_M of the cluster centre."""
        return len(self.fixes) >= BACKPLOT_FIXES_NEEDED and self.believed_alive


@dataclass
class KnownStructure:
    """Enemy-side belief about a player fixed structure."""
    structure_id: str
    kind: str                   # "radar_station" | "bastion_cluster"
    believed_pos: np.ndarray    # (3,) XYZ
    believed_alive: bool = True


# ---------------------------------------------------------------------------
# EnemyPicture — the enemy-side intel store
# ---------------------------------------------------------------------------

class EnemyPicture:
    """Enemy side's sensor-derived picture of the player.

    Updated by EnemyCommander.update_picture() each tick.  Nothing here
    peeks at simulation truth — all fields are derived from sensor events
    passed in from the outside.
    """

    def __init__(self) -> None:
        # Emitter localization (ESM fix, generalised from enemy_strikes.py)
        self.emitters: dict[str, EmitterIntel] = {}

        # Back-plot launch-site estimates (raw, per-missile)
        self._back_plots: list[BackPlotEntry] = []

        # Clustered launch sites (confirmed after BACKPLOT_FIXES_NEEDED fixes)
        self.clusters: list[LaunchCluster] = []

        # Known player structures (radar station + bastion clusters)
        self.structures: dict[str, KnownStructure] = {}

        # Drone tracks: aircraft_id -> last-known pos (XZ) + sim_time
        self.drone_tracks: dict[str, dict] = {}

        # Player missile tracks: track_id -> {"pos", "vel", "alt_at_first",
        # "range_at_first", "age_at_first", "first_seen_t"}
        self.missile_tracks: dict[str, dict] = {}

    # --------------------------------------------------------------------- ESM

    def update_emitter(
        self,
        emitter_id: str,
        believed_pos: np.ndarray,
        is_emitting: bool,
        dt: float,
        sim_time: float,
    ) -> None:
        """Advance the ESM localization fix for one emitter.

        Called by EnemyCommander.tick() for every enemy radar that has LoS to
        the emitter.  Mirrors the accrual/decay math from enemy_strikes.py.
        """
        ei = self.emitters.get(emitter_id)
        if ei is None:
            ei = EmitterIntel(
                emitter_id=emitter_id,
                believed_pos=np.asarray(believed_pos, dtype=np.float64).copy(),
            )
            self.emitters[emitter_id] = ei

        ei.believed_pos[:] = believed_pos   # track the last-known position

        if is_emitting:
            ei.fix_progress = min(1.0, ei.fix_progress + dt / ESM_FIX_TIME_S)
            ei.last_heard_t = sim_time
        else:
            ei.fix_progress = max(
                0.0, ei.fix_progress - ESM_DECAY_FACTOR * dt / ESM_FIX_TIME_S)

    def mark_emitter_destroyed(self, emitter_id: str) -> None:
        ei = self.emitters.get(emitter_id)
        if ei is not None:
            ei.alive = False

    def mark_emitter_alive(self, emitter_id: str) -> None:
        """Re-illuminate event (radar turned back on) resets the belief."""
        ei = self.emitters.get(emitter_id)
        if ei is not None:
            ei.alive = True

    # --------------------------------------------------------- back-plot

    def add_back_plot(
        self,
        estimated_xz: np.ndarray,   # (2,) float64
        error_m: float,
        sim_time: float,
        track_id: str,
    ) -> None:
        """Record one back-plotted launch-site estimate and update clusters."""
        entry = BackPlotEntry(
            estimated_pos=np.asarray(estimated_xz, dtype=np.float64).copy(),
            error_m=error_m,
            sim_time=sim_time,
            track_id=track_id,
        )
        self._back_plots.append(entry)
        self._update_clusters(entry)

    def _update_clusters(self, entry: BackPlotEntry) -> None:
        """Add the entry to an existing cluster within BACKPLOT_CLUSTER_R_M,
        or start a new cluster.

        A cluster grows when its centre is within the cluster radius of the
        new estimate.  On each addition the centroid is recalculated from all
        fixes in the cluster.  Track ids are deduplicated: a single missile
        can only contribute one fix per cluster (prevents a single long-track
        from satisfying BACKPLOT_FIXES_NEEDED by itself)."""
        ep = entry.estimated_pos
        for cluster in self.clusters:
            dist = math.hypot(
                float(ep[0]) - float(cluster.centre[0]),
                float(ep[1]) - float(cluster.centre[1]),
            )
            if dist <= BACKPLOT_CLUSTER_R_M:
                # Deduplicate: same track_id already represented?
                existing_ids = {f.track_id for f in cluster.fixes}
                if entry.track_id not in existing_ids:
                    cluster.fixes.append(entry)
                    # Recompute centroid
                    xs = [f.estimated_pos[0] for f in cluster.fixes]
                    zs = [f.estimated_pos[1] for f in cluster.fixes]
                    cluster.centre = np.array(
                        [sum(xs) / len(xs), sum(zs) / len(zs)],
                        dtype=np.float64,
                    )
                return
        # No matching cluster — start one
        new_cluster = LaunchCluster(centre=ep.copy())
        new_cluster.fixes.append(entry)
        self.clusters.append(new_cluster)

    def targetable_clusters(self) -> list[LaunchCluster]:
        return [c for c in self.clusters if c.targetable]

    # ---------------------------------------------------------- drone tracks

    def update_drone_track(
        self,
        aircraft_id: str,
        pos_xz: np.ndarray,
        sim_time: float,
    ) -> None:
        self.drone_tracks[aircraft_id] = {
            "pos": np.asarray(pos_xz, dtype=np.float64).copy(),
            "t": sim_time,
        }

    def clear_drone_track(self, aircraft_id: str) -> None:
        self.drone_tracks.pop(aircraft_id, None)

    def live_drone_tracks(self, now: float, max_age: float = 30.0) -> list[dict]:
        """Drone tracks last updated within max_age seconds."""
        return [
            {"id": aid, **v}
            for aid, v in self.drone_tracks.items()
            if now - v["t"] <= max_age
        ]

    # ------------------------------------------------------- missile tracks

    def update_missile_track(
        self,
        track_id: str,
        pos: np.ndarray,
        vel: np.ndarray,
        sim_time: float,
        first_seen_t: Optional[float] = None,
        alt_at_first: Optional[float] = None,
        range_at_first: Optional[float] = None,
        kind: Optional[str] = None,
    ) -> None:
        """Record or refresh an enemy-radar missile track.

        ``kind`` is the enemy's SENSOR CLASSIFICATION of the inbound (e.g.
        "kh31p" for a detected player anti-radiation missile) — fed by the world
        when an enemy radar detects the round, analogous to the player's contact
        stamps. It is fog-honest (the enemy's belief), NOT a truth read. Additive
        and optional: existing callers pass nothing -> kind None."""
        mt = self.missile_tracks.get(track_id)
        if mt is None:
            mt = {
                "pos": pos.copy(),
                "vel": vel.copy(),
                "t": sim_time,
                "first_seen_t": first_seen_t if first_seen_t is not None else sim_time,
                "alt_at_first": alt_at_first,
                "range_at_first": range_at_first,
                "kind": kind,
            }
            self.missile_tracks[track_id] = mt
        else:
            mt["pos"] = pos.copy()
            mt["vel"] = vel.copy()
            mt["t"] = sim_time
            mt["kind"] = kind   # refresh the sensor classification on update

    def live_missile_tracks(self, now: float, max_age: float = 30.0) -> list[dict]:
        return [
            {"id": tid, **v}
            for tid, v in self.missile_tracks.items()
            if now - v["t"] <= max_age
        ]

    def prune_missile_tracks(self, live_ids: set, now: float) -> None:
        """Remove tracks for missiles that no longer exist, and bound the raw
        back-plot guard list (append-only, one entry per detected launch) so it
        cannot grow unbounded over a long match. A back-plot entry is kept while
        its track is still live OR it is recent (a fix only seeds within
        BACKPLOT_MAX_AGE_S of launch, so an older entry for a gone track can
        never re-trigger and is safe to drop — the clusters retain their own
        fixes independently)."""
        self.missile_tracks = {
            k: v for k, v in self.missile_tracks.items()
            if k in live_ids or now - v["t"] <= 30.0
        }
        self._back_plots = [
            bp for bp in self._back_plots
            if bp.track_id in live_ids
            or now - bp.sim_time <= BACKPLOT_MAX_AGE_S
        ]


# ---------------------------------------------------------------------------
# MissionState — one active strike package
# ---------------------------------------------------------------------------

@dataclass
class MissionState:
    """Tracks the state of a strike package currently in progress."""
    mission_type: str      # "harm_package" | "jassm_package" | "tomahawk_salvo"
    target_id: str
    fighter_ids: list[str]
    jassm_consumed: int = 0
    harm_consumed: int = 0
    # Tomahawk salvos draw from the weapon controller; just record the order.
    order_issued: bool = False


# ---------------------------------------------------------------------------
# Weapon stock (enemy side, per the mission generator constants)
# ---------------------------------------------------------------------------

class WeaponStock:
    """Tracks remaining JASSM / HARM magazines across the airfield and carrier."""

    def __init__(self) -> None:
        self.airfield_jassm: int = AIRFIELD_JASSM
        self.airfield_harm: int = AIRFIELD_HARM
        self.carrier_jassm: int = CARRIER_JASSM
        self.carrier_harm: int = CARRIER_HARM

    @property
    def total_jassm(self) -> int:
        return self.airfield_jassm + self.carrier_jassm

    @property
    def total_harm(self) -> int:
        return self.airfield_harm + self.carrier_harm

    def can_arm_harm_package(self, harms_needed: int = 4) -> bool:
        """True when there are enough HARMs for one full package."""
        return self.total_harm >= harms_needed

    def can_arm_jassm_package(self, jassms_needed: int = 4) -> bool:
        """True when there are enough JASSMs for one full package."""
        return self.total_jassm >= jassms_needed

    def consume_harm(self, count: int) -> None:
        """Deduct HARMs from magazines (airfield first)."""
        for _ in range(count):
            if self.airfield_harm > 0:
                self.airfield_harm -= 1
            elif self.carrier_harm > 0:
                self.carrier_harm -= 1

    def consume_jassm(self, count: int) -> None:
        """Deduct JASSMs from magazines (airfield first)."""
        for _ in range(count):
            if self.airfield_jassm > 0:
                self.airfield_jassm -= 1
            elif self.carrier_jassm > 0:
                self.carrier_jassm -= 1


# ---------------------------------------------------------------------------
# EnemyCommander
# ---------------------------------------------------------------------------

class EnemyCommander:
    """Enemy side strategic commander (spec section 6).

    Ticks at COMMANDER_TICK_S (1 Hz) cadence; stepped from world/combat.py
    alongside defense and strikes controllers.  Deterministic given a fixed
    seed and the same sequence of picture updates.

    Parameters
    ----------
    fighters :
        List of Fighter objects (sim/enemy_air.py) — the air wing.
    awacs :
        The Awacs orbiter (sim/enemy_air.py).
    destroyers :
        List of Destroyer / Carrier ships — ship radar silence is ordered
        here; the ships' own fire control (enemy_defense.py) still handles
        SM-2 launches autonomously.
    picture :
        EnemyPicture instance (may be shared with / populated by the world).
        If None, one is created internally (useful for tests).
    weapon_stock :
        WeaponStock instance.  If None, full stocks are assumed.
    seed :
        RNG seed for determinism.  Same seed + same picture sequence = same
        orders.
    """

    def __init__(
        self,
        fighters: list,
        awacs,
        destroyers: list,
        picture: Optional[EnemyPicture] = None,
        weapon_stock: Optional[WeaponStock] = None,
        seed: int = 0,
        ground_radars: Optional[list] = None,
        jammers: Optional[list] = None,
    ) -> None:
        self.fighters = list(fighters)
        self.awacs = awacs
        self.destroyers = list(destroyers)
        # Enemy ground radars (sim.radar.Radar): wired in like destroyers so the
        # ARM-EMCON doctrine (_defend_ground_radars) can read their positions.
        # Default empty -> the n==0 / test paths Just Work.
        self.ground_radars = list(ground_radars) if ground_radars else []
        # M3-F2 escort jammers (sim.enemy_air.JammerAircraft): wired in like the
        # AWACS so _defend_jammer can station/lift/flee them. Default empty ->
        # the n_jammers==0 default battle builds none, never touching this path.
        self.jammers = list(jammers) if jammers else []
        self.picture: EnemyPicture = (picture
                                      if picture is not None else EnemyPicture())
        self.stock: WeaponStock = (weapon_stock
                                   if weapon_stock is not None else WeaponStock())
        self._rng = np.random.default_rng(seed)

        # Tick state
        self._next_tick: float = 0.0   # sim_time at which the next tick fires

        # Pending orders queue: cleared each tick and handed to the integrator
        self.pending_orders: list[dict] = []

        # Active missions: prevent duplicate packages
        self._active_missions: list[MissionState] = []

        # M5 #1 amphibious release: latched True once the commander has ordered
        # TRANSPORT_RUN, so the order is emitted EXACTLY ONCE (the world applies
        # it idempotently, but a once-flag keeps pending_orders clean and the
        # decision deterministic).  The release reads ONLY self.picture (a
        # sensor belief that the player base is LOCALIZED) — never truth.
        self._amphibious_released: bool = False

        # AWACS flee state (tracks whether a flee order is currently in effect)
        self._awacs_fleeing: bool = False
        self._awacs_silent_until: float = 0.0   # EMCON dwell clock (see _defend_awacs)

        # ARM-EMCON state (M2-T3), mirroring the AWACS _awacs_fleeing flag +
        # _awacs_silent_until dwell clock, but PER ship / ground radar:
        #   *_arm_emcon: ids the commander is currently holding SILENT for an ARM
        #     (so it only un-silences what IT silenced — never overrides an
        #     externally-set radar state, exactly like the AWACS resume gate).
        #   *_arm_silent_until: id -> sim_time the silent dwell expires.
        # Anti-strobe: the dwell is refreshed each tick the ARM is seen.
        self._ship_arm_emcon: set[str] = set()
        self._ship_arm_silent_until: dict[str, float] = {}
        self._ground_arm_emcon: set[str] = set()
        self._ground_arm_silent_until: dict[str, float] = {}

        # M3-F2 escort-jammer EMCON state (mirrors the AWACS dwell, PER jammer):
        #   *_jammer_lifted: aircraft_ids whose jam the commander is HOLDING
        #     LIFTED for an inbound threat (only re-jams what IT lifted).
        #   *_jammer_lift_until: id -> sim_time the lift dwell expires.
        #   *_jammer_fleeing: ids currently under a flee order (anti-spam).
        self._jammer_lifted: set[str] = set()
        self._jammer_lift_until: dict[str, float] = {}
        self._jammer_fleeing: set[str] = set()
        # Last commanded station bearing per jammer (rad) — a STATION order is
        # re-issued only when the believed bearing MOVES past JAMMER_RESTATION_
        # EPS_RAD or after a lift, so normal operation never strobes jam orders.
        self._jammer_station_bearing: dict[str, float] = {}

    # ------------------------------------------------------------------ tick

    def tick(self, sim_time: float, dt: float) -> list[dict]:
        """Evaluate doctrine at 1 Hz.

        Returns the list of NEW orders issued this tick (also stored in
        ``self.pending_orders`` for the integrator to consume).  The integrator
        should clear pending_orders after reading it each step.
        """
        if sim_time < self._next_tick:
            return []
        self._next_tick = sim_time + COMMANDER_TICK_S
        self.pending_orders = []

        # --- DOCTRINE (evaluated top-down; all branches run, no short-circuit
        # --- because all four categories can generate orders simultaneously)

        self._doctrine_defend(sim_time)
        self._doctrine_blind(sim_time)
        self._doctrine_kill(sim_time)
        self._doctrine_amphibious(sim_time)

        return list(self.pending_orders)

    # ---------------------------------------------------------------- defend

    def _doctrine_defend(self, sim_time: float) -> None:
        """DEFEND: drone vectoring, AWACS flee, ship + ground radar silence,
        escort-jammer station/lift/flee."""
        self._defend_vs_drone(sim_time)
        self._defend_awacs(sim_time)
        self._defend_ship_radars(sim_time)
        self._defend_ground_radars(sim_time)
        self._defend_jammer(sim_time)

    def _sensed_arm_within(self, sim_time: float, pos, range_m: float) -> bool:
        """True when the SENSED picture holds a live ARM-kind missile track
        (kind == "kh31p") within ``range_m`` (ground-plane) of ``pos``.

        NO-CHEAT: reads ONLY the EnemyPicture's sensed tracks (mt["pos"],
        mt["kind"]) and the supplied radar position — never the ARM's truth."""
        px, pz = float(pos[0]), float(pos[2])
        for mt in self.picture.live_missile_tracks(sim_time):
            if mt.get("kind") != "kh31p":
                continue
            mpos = mt["pos"]
            if math.hypot(float(mpos[0]) - px,
                          float(mpos[2]) - pz) <= range_m:
                return True
        return False

    def _defend_vs_drone(self, sim_time: float) -> None:
        """Vector the nearest armed CAP fighter at any live drone track."""
        drone_tracks = self.picture.live_drone_tracks(sim_time)
        if not drone_tracks:
            return
        # Pick the most recent drone track (could be multiple drones in future)
        target_track = max(drone_tracks, key=lambda t: t["t"])
        target_pos = target_track["pos"]   # XZ

        # Find the nearest airborne fighter that could be armed with AIM-9X
        best_fighter = None
        best_dist = math.inf
        from sim.enemy_air import (FS_TAKEOFF, FS_TRANSIT, FS_ON_STATION)
        airborne_states = (FS_TAKEOFF, FS_TRANSIT, FS_ON_STATION)
        for f in self.fighters:
            if not f.alive or f.state not in airborne_states:
                continue
            dist = math.hypot(
                float(f.pos[0]) - float(target_pos[0]),
                float(f.pos[2]) - float(target_pos[1]),  # XZ in track
            )
            if dist < best_dist:
                best_dist = dist
                best_fighter = f

        if best_fighter is not None:
            target_3d = np.array(
                [float(target_pos[0]), 0.0, float(target_pos[1])],
                dtype=np.float64,
            )
            self.pending_orders.append({
                "type": "vector_to_drone",
                "fighter_id": best_fighter.aircraft_id,
                "target_pos": target_3d,
                "aim9x": True,
            })

    def _defend_awacs(self, sim_time: float) -> None:
        """Issue AWACS flee / resume orders based on missile tracks."""
        if self.awacs is None or not self.awacs.alive:
            return
        missile_tracks = self.picture.live_missile_tracks(sim_time)
        awacs_pos = self.awacs.pos   # (3,) XYZ

        threat_pos = None
        for mt in missile_tracks:
            mpos = mt["pos"]
            dist = math.hypot(
                float(mpos[0]) - float(awacs_pos[0]),
                float(mpos[2]) - float(awacs_pos[2]),
            )
            if dist <= AWACS_FLEE_RANGE_M:
                threat_pos = mpos
                break

        if threat_pos is not None:
            # Refresh the EMCON silent-dwell while the threat is seen.
            self._awacs_silent_until = sim_time + AWACS_EMCON_DWELL_S
            if not self._awacs_fleeing:
                # Enter flee+silent ONCE (anti-strobe: don't re-spam the order
                # every tick — the AWACS just runs flat-out from the bearing).
                self._awacs_fleeing = True
                self.pending_orders.append({
                    "type": "awacs_flee",
                    "threat_pos": threat_pos.copy(),
                })
        elif self._awacs_fleeing and sim_time >= self._awacs_silent_until:
            # No threat seen AND the silent dwell has elapsed: come back up.
            # Holding through the dwell stops a sole-sensor AWACS from un-blinding
            # itself the instant its own dark track ages out (the ~31 s strobe).
            self._awacs_fleeing = False
            self.pending_orders.append({"type": "awacs_resume"})

    def _defend_ship_radars(self, sim_time: float) -> None:
        """Manage per-ship radar silence.

        Priority (top wins):
          * ARM-EMCON (M2-T3): a SENSED ARM track (kind=="kh31p") within
            ARM_EMCON_RANGE_M of the ship's radar -> SILENT for the dwell.
            This OVERRIDES self-defense: emitting would feed the ARM's passive
            seeker, so going dark (which degrades the live ARM to its CEP ring)
            is the survivable counter. Anti-strobe: silent once, held through
            the dwell (per-ship _ship_arm_silent_until clock), then the normal
            logic resumes.
          * Inbound missile tracks (non-ARM) -> EMIT (self-defense beats stealth).
          * Drone track exists (recon threat) and no inbound missiles -> SILENT.
          * Neither -> no change.
        """
        missile_tracks = self.picture.live_missile_tracks(sim_time)
        drone_tracks = self.picture.live_drone_tracks(sim_time)
        has_inbound = len(missile_tracks) > 0
        drone_present = len(drone_tracks) > 0

        for ship in self.destroyers:
            if not ship.alive:
                continue
            radar = getattr(ship, "radar", None)
            if radar is None:
                continue

            # --- ARM-EMCON override (highest priority) ---
            # Use the ship's own position (the SPY-1 is co-located — the world
            # slaves radar.pos to ship.pos each step; sim/enemy_ships.py) so the
            # check mirrors _defend_awacs (which uses awacs.pos).
            sid = ship.ship_id
            arm_threat = self._sensed_arm_within(
                sim_time, ship.pos, ARM_EMCON_RANGE_M)
            if arm_threat:
                # Refresh the dwell each tick the ARM is seen (anti-strobe).
                self._ship_arm_silent_until[sid] = sim_time + ARM_EMCON_DWELL_S
            holding = sid in self._ship_arm_emcon
            if arm_threat or (holding
                              and sim_time < self._ship_arm_silent_until.get(
                                  sid, 0.0)):
                # Hold SILENT through the dwell; enter the EMCON ONCE (anti-spam:
                # only order silent if the radar is currently up).
                if not holding:
                    self._ship_arm_emcon.add(sid)
                    if radar.emitting:
                        self.pending_orders.append({
                            "type": "ship_silent",
                            "ship_id": sid,
                        })
                continue   # ARM hold overrides the self-defense / stealth logic
            # ARM threat clear AND dwell elapsed: release the EMCON hold. We do
            # NOT force-emit here — the normal self-defense / stealth logic below
            # decides the post-EMCON state (so an external silence is respected).
            self._ship_arm_emcon.discard(sid)

            if has_inbound:
                # Self-defense outranks stealth (non-ARM inbound)
                if not radar.emitting:
                    self.pending_orders.append({
                        "type": "ship_emit",
                        "ship_id": ship.ship_id,
                    })
            elif drone_present:
                # Drone is a threat to the ship's radar emissions
                if radar.emitting:
                    self.pending_orders.append({
                        "type": "ship_silent",
                        "ship_id": ship.ship_id,
                    })

    def _defend_ground_radars(self, sim_time: float) -> None:
        """ARM-EMCON for the enemy coastal ground radars (M2-T3).

        Ground radars have no SAM self-defense — silence is their ONLY counter
        to an inbound ARM. A SENSED ARM track (kind=="kh31p") within
        ARM_EMCON_RANGE_M -> SILENT for the dwell; once the threat is gone and
        the dwell has elapsed, resume emitting. Anti-strobe via a per-radar
        _ground_arm_silent_until clock (mirrors the ship/AWACS EMCON).

        NO-CHEAT: the trigger reads ONLY the sensed picture track + the radar's
        own position (see _sensed_arm_within), never the ARM's truth. With no
        ARM ever fired (kh31p_ammo=0) no kind=="kh31p" track exists, so this
        never silences -> byte-identical default battle.
        """
        for radar in self.ground_radars:
            if not getattr(radar, "alive", False):
                continue
            rid = radar.radar_id
            arm_threat = self._sensed_arm_within(
                sim_time, radar.pos, ARM_EMCON_RANGE_M)
            if arm_threat:
                self._ground_arm_silent_until[rid] = (
                    sim_time + ARM_EMCON_DWELL_S)
            holding = rid in self._ground_arm_emcon
            if arm_threat or (holding
                              and sim_time < self._ground_arm_silent_until.get(
                                  rid, 0.0)):
                # Hold SILENT; enter the EMCON ONCE (only order silent if the
                # radar is actually up — anti-spam).
                if not holding:
                    self._ground_arm_emcon.add(rid)
                    if radar.emitting:
                        self.pending_orders.append({
                            "type": "ground_radar_silent",
                            "radar_id": rid,
                        })
            elif holding:
                # Threat clear AND dwell elapsed: release the EMCON and bring the
                # radar back up — but ONLY because WE silenced it (the radar is
                # in our EMCON set). We never re-emit a radar silenced elsewhere.
                self._ground_arm_emcon.discard(rid)
                if not radar.emitting:
                    self.pending_orders.append({
                        "type": "ground_radar_emit",
                        "radar_id": rid,
                    })

    # ---------------------------------------------------------------- jammer

    def _fleet_centroid_xz(self) -> Optional[np.ndarray]:
        """The (x, z) centroid of the live destroyer screen — the jammer's own
        side's positions (NOT a truth read of the player).  None if the screen
        is gone (the jammer then holds its current orbit)."""
        pts = [(float(s.pos[0]), float(s.pos[2]))
               for s in self.destroyers if getattr(s, "alive", False)]
        if not pts:
            return None
        return np.array([sum(p[0] for p in pts) / len(pts),
                         sum(p[1] for p in pts) / len(pts)],
                        dtype=np.float64)

    def _loudest_believed_emitter_xz(self) -> Optional[np.ndarray]:
        """The (x, z) BELIEF estimate of the loudest player emitter the picture
        holds — the EmitterIntel with the HIGHEST fix progress (else, the most
        targetable back-plot cluster centroid).  NO-CHEAT: reads ONLY the
        sensor-derived EnemyPicture (believed_pos / cluster centres), NEVER the
        real player radar/launcher truth.  None if the side believes nothing."""
        best_ei = None
        for ei in self.picture.emitters.values():
            if not ei.alive:
                continue
            if best_ei is None or ei.fix_progress > best_ei.fix_progress:
                best_ei = ei
        if best_ei is not None and best_ei.fix_progress > 0.0:
            bp = best_ei.believed_pos
            return np.array([float(bp[0]), float(bp[2])], dtype=np.float64)
        # Fallback: the strongest back-plot launch cluster centroid (XZ).
        best_c = None
        for c in self.picture.clusters:
            if not c.believed_alive:
                continue
            if best_c is None or len(c.fixes) > len(best_c.fixes):
                best_c = c
        if best_c is not None:
            return np.array([float(best_c.centre[0]), float(best_c.centre[1])],
                            dtype=np.float64)
        return None

    def _defend_jammer(self, sim_time: float) -> None:
        """STATION / LIFT / FLEE the escort jammer(s) — NO-CHEAT, sensor-only.

        Per live jammer:
          * THREAT (lift + flee): a sensed inbound missile track within
            JAMMER_THREAT_RANGE_M of the jammer -> LIFT the jam (going dark
            denies a radiation-homing seeker its beacon, degrading the round —
            the ARM-EMCON logic) and FLEE toward the rear (reuse the AWACS
            flee()).  Anti-strobe: enter ONCE, refresh the dwell each tick the
            threat is seen, HOLD the lift through JAMMER_EMCON_DWELL_S after it
            was last seen (no per-tick strobe), THEN re-jam + stop fleeing.
          * STATION (no threat): aim the orbit on the fleet-centroid ->
            LOUDEST-BELIEVED-emitter bearing (the EnemyPicture belief, never
            truth).  If nothing is believed, hold the current orbit.

        Determinism: a pure function of the picture + the side's own positions
        + sim_time; NO RNG, no wallclock.
        """
        if not self.jammers:
            return
        missile_tracks = self.picture.live_missile_tracks(sim_time)
        centroid = self._fleet_centroid_xz()
        belief = self._loudest_believed_emitter_xz()

        for jam in self.jammers:
            if not getattr(jam, "alive", False):
                continue
            jid = jam.aircraft_id
            jpos = jam.pos   # the jammer's OWN position (own-side, not truth)

            # --- inbound-threat gate (mirrors the AWACS / ARM EMCON) ---
            threat_pos = None
            for mt in missile_tracks:
                mpos = mt["pos"]
                if math.hypot(float(mpos[0]) - float(jpos[0]),
                              float(mpos[2]) - float(jpos[2])) \
                        <= JAMMER_THREAT_RANGE_M:
                    threat_pos = mpos
                    break

            if threat_pos is not None:
                # Refresh the lift dwell while the threat is seen (anti-strobe).
                self._jammer_lift_until[jid] = sim_time + JAMMER_EMCON_DWELL_S
                if jid not in self._jammer_lifted:
                    # Enter lift ONCE (anti-spam) — and flee ONCE.
                    self._jammer_lifted.add(jid)
                    self.pending_orders.append({
                        "type": "jammer_lift",
                        "aircraft_id": jid,
                        "threat_pos": np.asarray(threat_pos,
                                                 dtype=np.float64).copy(),
                    })
                if (math.hypot(float(threat_pos[0]) - float(jpos[0]),
                               float(threat_pos[2]) - float(jpos[2]))
                        <= JAMMER_FLEE_RANGE_M
                        and jid not in self._jammer_fleeing):
                    self._jammer_fleeing.add(jid)
                    self.pending_orders.append({
                        "type": "jammer_flee",
                        "aircraft_id": jid,
                        "threat_pos": np.asarray(threat_pos,
                                                 dtype=np.float64).copy(),
                    })
                continue   # threatened: no stationing this tick

            # Threat clear: hold the lift through the dwell (no self-strobe).
            if (jid in self._jammer_lifted
                    and sim_time < self._jammer_lift_until.get(jid, 0.0)):
                continue

            # Threat clear AND any lift dwell elapsed.  Compute the STATION
            # bearing off BELIEF (None if nothing believed -> hold current orbit).
            station_xz = None
            bearing = None
            if centroid is not None and belief is not None:
                bearing = math.atan2(float(belief[0]) - float(centroid[0]),
                                     float(belief[1]) - float(centroid[1]))
                station_xz = np.array([
                    float(centroid[0]) + JAMMER_STANDOFF_M * math.sin(bearing),
                    float(centroid[1]) + JAMMER_STANDOFF_M * math.cos(bearing),
                ], dtype=np.float64)

            was_lifted = jid in self._jammer_lifted
            self._jammer_lifted.discard(jid)
            self._jammer_fleeing.discard(jid)

            # Decide whether to (re-)issue a jam/station order.  Emit when:
            #   * we are coming out of a lift (must turn the corridor back on), OR
            #   * the believed bearing has MOVED past the re-station epsilon
            #     (or this is the first station) — otherwise hold (anti-strobe:
            #     steady-state operation issues no per-tick order spam).
            restation = False
            if bearing is not None:
                last = self._jammer_station_bearing.get(jid)
                if last is None or abs(
                        (bearing - last + math.pi) % (2.0 * math.pi) - math.pi
                ) >= JAMMER_RESTATION_EPS_RAD:
                    restation = True
            if not (was_lifted or restation):
                continue

            order = {"type": "jammer_jam", "aircraft_id": jid}
            if station_xz is not None:
                order["station_xz"] = station_xz
                order["bearing"] = bearing
                self._jammer_station_bearing[jid] = bearing
            self.pending_orders.append(order)

    # ----------------------------------------------------------------- blind

    def _doctrine_blind(self, sim_time: float) -> None:
        """BLIND: schedule HARM packages while the player radar is believed
        alive and located AND HARM stock remains.

        Spec doctrine order: BLIND comes before KILL (the commander first
        tries to remove the player's eyes before attacking the TELs).
        No HARM package is generated if HARM stock is empty — it would be
        a paper order."""
        # Check whether there is already an active HARM mission
        active_harm = any(m.mission_type == "harm_package"
                          for m in self._active_missions)
        if active_harm:
            return

        # Does the picture hold the player radar station?
        radar_intel = self._believed_radar_station()
        if radar_intel is None:
            return   # not located — nothing to BLIND
        if not radar_intel.alive:
            return   # believed destroyed — move on

        if not self.stock.can_arm_harm_package(harms_needed=4):
            return   # Winchester on HARM — cannot generate package

        fighters = self._select_fighters_for_strike(2)
        if len(fighters) < 2:
            return   # not enough ready fighters

        target_3d = np.array(
            [float(radar_intel.believed_pos[0]),
             float(radar_intel.believed_pos[1]),
             float(radar_intel.believed_pos[2])],
            dtype=np.float64,
        )
        mission = MissionState(
            mission_type="harm_package",
            target_id=radar_intel.emitter_id,
            fighter_ids=[f.aircraft_id for f in fighters],
            harm_consumed=4,
        )
        self._active_missions.append(mission)
        self.stock.consume_harm(4)

        self.pending_orders.append({
            "type": "harm_package",
            "target_pos": target_3d.copy(),
            "target_id": radar_intel.emitter_id,
            "fighter_ids": [f.aircraft_id for f in fighters],
            "harms_per_fighter": 2,
            "ingress_alt_m": HARM_INGRESS_ALT_M,
            "standoff_m": HARM_STANDOFF_M,
        })

    # ------------------------------------------------------------------ kill

    def _doctrine_kill(self, sim_time: float) -> None:
        """KILL: JASSM packages + Tomahawk salvos at targetable bastion clusters.

        Doctrine priority (spec section 6): BLIND comes before KILL.
        The JASSM branch is GATED: no JASSM package is issued while the player
        radar station is believed alive AND HARM stock remains.  The commander
        must first attempt to blind the player before launching strike packages.
        If the radar is alive but HARM stock is exhausted the gate releases the
        JASSM branch — we cannot blind, but we can still attempt to kill.
        Tomahawk salvos run regardless of the radar belief (cruise missiles fly
        on GPS/INS, not dependent on the radar being blind).

        Only fires when at least one cluster is targetable.  One JASSM mission
        and one Tomahawk salvo per cluster per tick (the integrator throttles
        further via the base fighter availability and Tomahawk reload timer
        from enemy_strikes.py).
        """
        targetable = self.picture.targetable_clusters()
        if not targetable:
            return

        # Blind-before-kill gate for JASSM: while the player radar station is
        # believed alive (located + not destroyed), suppress JASSM packages
        # entirely.  The commander must not launch air-to-ground strikes against
        # the Bastion while the player's radar network is still up — doctrine
        # requires blinding the enemy before exposing strike aircraft in a
        # defended SAM environment (spec section 6 "Find -> Blind -> Kill").
        # If HARM stock is exhausted the gate remains: the commander is
        # effectively stalled at BLIND and cannot proceed to KILL until the
        # radar station is either destroyed or belief changes.
        # Blind-before-kill, but NOT a deadlock: the gate holds JASSM only while
        # the radar is believed alive AND we still have the HARM stock to keep
        # trying to blind it. Once HARM is winchester we can no longer blind, so
        # the gate releases and the commander strikes anyway (the documented
        # intent above). With the radar alive the strike fighters run the
        # player's S-300 gauntlet — the intended skill check, and the only way
        # the enemy ever reaches the base while the player keeps the radar on.
        radar_alive = self._believed_radar_station() is not None
        jassm_gated = radar_alive and self.stock.can_arm_harm_package(harms_needed=4)

        for cluster in targetable:
            cid = f"cluster_{id(cluster)}"

            # Check whether there is already an active JASSM mission for this
            # cluster (one active package per cluster at a time).
            active_jassm = any(
                m.mission_type == "jassm_package" and m.target_id == cid
                for m in self._active_missions
            )

            if (not active_jassm
                    and not jassm_gated      # blind-before-kill gate
                    and self.stock.can_arm_jassm_package(jassms_needed=4)):
                fighters = self._select_fighters_for_strike(2)
                if len(fighters) >= 2:
                    target_3d = np.array(
                        [float(cluster.centre[0]), 0.0, float(cluster.centre[1])],
                        dtype=np.float64,
                    )
                    mission = MissionState(
                        mission_type="jassm_package",
                        target_id=cid,
                        fighter_ids=[f.aircraft_id for f in fighters],
                        jassm_consumed=4,
                    )
                    self._active_missions.append(mission)
                    self.stock.consume_jassm(4)
                    self.pending_orders.append({
                        "type": "jassm_package",
                        "target_pos": target_3d.copy(),
                        "target_id": cid,
                        "fighter_ids": [f.aircraft_id for f in fighters],
                        "jassms_per_fighter": 2,
                        "standoff_m": JASSM_STANDOFF_M,
                    })

            # Always issue a Tomahawk salvo order alongside or instead of JASSM
            # (Tomahawk inventory is managed by EnemyStrikeController; the
            # commander issues the intent and the integration layer routes it).
            active_tlam = any(
                m.mission_type == "tomahawk_salvo" and m.target_id == cid
                for m in self._active_missions
            )
            if not active_tlam:
                target_3d = np.array(
                    [float(cluster.centre[0]), 0.0, float(cluster.centre[1])],
                    dtype=np.float64,
                )
                mission = MissionState(
                    mission_type="tomahawk_salvo",
                    target_id=cid,
                    fighter_ids=[],
                )
                self._active_missions.append(mission)
                self.pending_orders.append({
                    "type": "tomahawk_salvo",
                    "target_pos": target_3d.copy(),
                    "target_id": cid,
                })

    # ----------------------------------------------------------- amphibious

    def _base_is_localized(self) -> bool:
        """Sensor-only belief that the player BASE is localized enough to commit
        an amphibious landing: the picture holds either a CONFIRMED launch
        cluster (a back-plotted Bastion site — ``targetable_clusters``) OR a
        LOCATED player radar-station emitter fix.  Both are derived purely from
        sensor events fed into self.picture (ESM fixes / missile back-plots) —
        NEVER a live player-TEL/missile truth read.  This is the SAME belief the
        KILL/BLIND doctrines already act on, reused as the landing trigger."""
        if self.picture.targetable_clusters():
            return True
        return self._believed_radar_station() is not None

    def _doctrine_amphibious(self, sim_time: float) -> None:
        """AMPHIBIOUS: release the transports (TRANSPORT_RUN) ONCE the sensor
        picture localizes the player base.  Sensor belief in, a single
        TRANSPORT_RUN order out — deterministic, no truth read.  Latched so the
        order fires exactly once; the integrator applies it idempotently to
        every loitering transport (a no-op when none are built)."""
        if self._amphibious_released:
            return
        if self._base_is_localized():
            self._amphibious_released = True
            self.pending_orders.append({"type": "transport_run"})

    # --------------------------------------------------------- helpers

    def _believed_radar_station(self) -> Optional[EmitterIntel]:
        """Return the EmitterIntel for the player radar station if located and
        believed alive; None otherwise."""
        for ei in self.picture.emitters.values():
            if ei.located and ei.alive:
                return ei
        return None

    def _select_fighters_for_strike(self, needed: int) -> list:
        """Return up to ``needed`` fighters that are PARKED and rearmed at a
        live base (ready to launch immediately).  Deterministic: fighters are
        iterated in construction order; the RNG is not used here (ordering is
        stable)."""
        from sim.enemy_air import FS_PARKED, AirBase
        available = []
        for f in self.fighters:
            if len(available) >= needed:
                break
            if f.state != FS_PARKED:
                continue
            if not f._alive:
                continue
            # Must be at a live base
            if not f._base.alive:
                continue
            available.append(f)
        return available

    def complete_mission(self, mission_type: str, target_id: str) -> None:
        """Mark an active mission as completed (called by the integrator after
        the package has expended its weapons or been recalled)."""
        self._active_missions = [
            m for m in self._active_missions
            if not (m.mission_type == mission_type and m.target_id == target_id)
        ]

    # ------------------------------------------------------- back-plot seam

    def process_missile_track(
        self,
        track_id: str,
        pos: np.ndarray,          # current position (3,) XYZ
        vel: np.ndarray,          # current velocity (3,) XYZ
        sim_time: float,
        first_seen_t: float,
        first_seen_pos: np.ndarray,  # position when first detected (3,) XYZ
        first_seen_vel: np.ndarray,  # velocity when first detected
        detector_pos: np.ndarray,    # (3,) XYZ position of the detecting sensor
        kind: Optional[str] = None,  # enemy sensor classification (e.g. "kh31p")
    ) -> None:
        """Process an enemy-radar missile track for the back-plot pipeline.

        Called by the integrator (or the commander's own tick, when it has
        access to the track store) for every player missile track the enemy
        picture holds.

        Back-plot criteria (spec: "when any enemy radar holds a track on a
        player Oniks/SAM whose flight time is young — first detected while
        altitude < BACKPLOT_LOW_ALT_M and within BACKPLOT_MAX_AGE_S of launch"):
          1. First-detected altitude < BACKPLOT_LOW_ALT_M (2 km): a missile
             at cruise altitude cannot back-plot to the surface cleanly.
          2. Track age at first detection < BACKPLOT_MAX_AGE_S: a 30 s window
             from the launch moment ensures the velocity vector is still
             pointing close to the launch azimuth (the missile hasn't turned
             much yet).

        Error model: Gaussian-equivalent 1-sigma = detection range × BACKPLOT_ERR_FRAC.
        The AWACS look-down geometry is the main collector because it has
        wide area coverage at low slant range vs a climbing missile — verified
        in tests via a detector altitude assertion.
        """
        # Update the general missile track record first
        alt_at_first = float(first_seen_pos[1])
        det_range = math.hypot(
            float(first_seen_pos[0]) - float(detector_pos[0]),
            float(first_seen_pos[2]) - float(detector_pos[2]),
        )
        self.picture.update_missile_track(
            track_id, pos, vel, sim_time,
            first_seen_t=first_seen_t,
            alt_at_first=alt_at_first,
            range_at_first=det_range,
            kind=kind,
        )

        # --- Back-plot eligibility check ---
        # Spec: "first detected while its altitude < 2 km and within
        # BACKPLOT_MAX_AGE_S of launch", interpreted as:
        #   (a) first_seen altitude < BACKPLOT_LOW_ALT_M, AND
        #   (b) the track has only been known for < BACKPLOT_MAX_AGE_S
        #       (sim_time - first_seen_t).
        # We only back-plot on the FIRST detection event (fresh track), not on
        # every subsequent update — one fix per launch event.
        track_known_s = sim_time - first_seen_t
        if track_known_s > BACKPLOT_MAX_AGE_S:
            return   # track is too old to back-plot
        if alt_at_first >= BACKPLOT_LOW_ALT_M:
            return   # first detection was too high

        # Only back-plot once per track (the first time this function is called
        # for this track_id with a fresh track_known_s near 0).
        # We do this by checking if this track_id has already seeded a back-plot
        # in any cluster or raw back-plot list.
        already_plotted = any(
            bp.track_id == track_id for bp in self.picture._back_plots
        )
        if already_plotted:
            return

        # Extrapolate first_seen_pos backward by the track age at first detection
        # (i.e., the time from launch to first detection) to get the surface
        # launch point.  We don't know the actual time-since-launch, so we
        # use the observed velocity at first detection and project backward
        # until Y reaches 0 (surface).
        vx = float(first_seen_vel[0])
        vy = float(first_seen_vel[1])
        vz = float(first_seen_vel[2])
        fx = float(first_seen_pos[0])
        fy = float(first_seen_pos[1])
        fz = float(first_seen_pos[2])

        # Back-project the launch point from the first-detection track. Two
        # regimes — the old single fy/vy time-to-surface projection was
        # degenerate for level flight and slid level-cruise estimates tens of km
        # the WRONG way (measured ~150 km downrange, into the enemy's quadrant),
        # so the enemy could never localize a sea-skimming launch:
        if vy >= BACKPLOT_CLIMB_VY:
            # Boost climb caught near launch: project backward in time to the
            # surface (y = 0). Accurate while the round is still climbing.
            t_back = fy / vy
            launch_x = fx - vx * t_back
            launch_z = fz - vz * t_back
        else:
            # Level sea-skimmer: the launch is far behind it, off the bottom of
            # the time-to-surface math. Intersect the horizontal ground track
            # with the known home coastline instead. A coast-parallel or
            # receding track (a deliberate dogleg) cannot be localized -> no fix.
            dz = fz - HOME_COAST_Z
            if vz <= BACKPLOT_MIN_CLOSE_VZ or dz <= 0.0:
                return
            s = dz / vz
            launch_x = fx - vx * s
            launch_z = HOME_COAST_Z

        error_m = det_range * BACKPLOT_ERR_FRAC

        self.picture.add_back_plot(
            estimated_xz=np.array([launch_x, launch_z], dtype=np.float64),
            error_m=error_m,
            sim_time=sim_time,
            track_id=track_id,
        )

    # ------------------------------------------------------- step seam

    def step(self, sim_time: float, dt: float) -> list[dict]:
        """World step seam: called every world step, returns orders on tick
        boundaries.  Equivalent to tick() but respects the cadence gate.
        Non-tick steps return an empty list."""
        return self.tick(sim_time, dt)
