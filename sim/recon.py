"""Recon drone + passive/active sensor suite (pure numpy, GL-free, SI units).

ReconDrone
----------
High-altitude stealth ELINT/SAR aircraft, player-tasked via waypoints.

  * aircraft_id = 'drone_00' (default; overridable for multi-drone later)
  * is_air = True — duck-types into ContactBoard and the aircraft list.
  * radar_size = 'stealth' — enemy radars detect it at their 'stealth' range
    (~30 km for SPY-1, ~35 km for the player station; spec §4.3).

Flight model
  * Cruise at DRONE_ALT_M = 18 000 m, DRONE_SPEED_MPS = 160 m/s.
  * Rate-limited heading change: DRONE_TURN_RATE_RPS = 0.25 rad/s.
  * set_route([(x,z), ...]) — flies each waypoint in order, then loiters
    in a 4 km radius orbit around the last one.  Empty route = loiter at
    spawn position.
  * States: DRONE_AIRBORNE -> DRONE_SHOT_DOWN (kill() called) ->
    DRONE_GONE (hit ground after falling spiral).

ElintReceiver
-------------
Passive ELINT (emission intelligence) mounted on the drone.  Each call to
update(drone_pos, emitters, sim_time) scans a list of (emitter_id, radar)
pairs.  An emitter is HEARD when:
  * radar.alive and radar.emitting
  * range drone <-> emitter <= ELINT_RANGE_M cap
  * radar_horizon_m(drone_alt, emitter_antenna_alt) is not exceeded
  * terrain_blocks() returns False (LOS clear)

Each heard emitter accumulates a bearing fix (true bearing + gaussian noise
ELINT_BEARING_SIGMA_RAD, seeded rng).  Up to ELINT_MAX_PAIRS fixes are kept
per emitter; older pairs beyond the cap are dropped (FIFO).

Triangulation: given N (drone_pos, bearing) pairs for an emitter, the
estimated ground-plane (X,Z) position is found by weighted least squares
over the linear system:

    sin(theta) * (Z - Zd) - cos(theta) * (X - Xd) = 0    for each pair

i.e. A @ [X, Z]^T = b, where row i is [sin(theta_i), -cos(theta_i)] and
b_i = sin(theta_i)*Zd_i - cos(theta_i)*Xd_i.  With at least 2 non-parallel
pairs this gives a unique least-squares fix.  fix_quality() returns the
estimated position error in metres (singular covariance trace root); a fix
is ACTIONABLE when quality < ELINT_FIX_ACTIONABLE_M.

SarSensor
---------
Synthetic-aperture radar / optical look-down sensor.  Simple 2D strip
footprint of half-width SAR_HALF_WIDTH_M = 25 000 m centred under the drone
ground track.  detects(target_pos) returns True for SURFACE targets within
the strip.

RwrReceiver
-----------
Radar warning receiver (passive).  Exposes the current threat state per
emitter and synthesises .alerts() -> [(level, bearing_deg)] for the HUD.

  * SPIKE: an enemy radar currently detects the drone (radar.detects(drone_pos,
    'stealth') is True).
  * LOCK: an enemy SamMissile whose target is the drone is in-flight.

Locked conventions obeyed:
  * All maths: float64 numpy + math only.  No GL imports anywhere.
  * +Y up, X east, Z north (heading 0 = +Z, clockwise from above).
  * Named constants with unit suffixes and justification comments.
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

import numpy as np

from sim.radar import radar_horizon_m, terrain_blocks
# M5 acoustic domain: the sub's one-tick launch-transient spike level.  Imported
# at module top (sim.submarine has NO recon import, so this is cycle-free) so the
# AcousticReceiver hears the loud transient much farther than the steady noise.
from sim.submarine import SUB_LAUNCH_TRANSIENT

# ---------------------------------------------------------------------------
# Tuning constants (all SI, named with unit suffix where ambiguous)
# ---------------------------------------------------------------------------

# --- Drone airframe ---
DRONE_ALT_M: float = 18_000.0
# Justification: RQ-4 / Heron TP class cruises 15–20 km; 18 km sits above
# most SAMs' practical intercept band while keeping the SAR look-angle narrow.

DRONE_SPEED_MPS: float = 160.0
# Justification: ~580 km/h, mid-band for long-endurance MALE/HALE UAS.

DRONE_TURN_RATE_RPS: float = 0.25
# rad/s — gentle bank-limited turn at altitude; gives ~640 m turn radius.

DRONE_LOITER_RADIUS_M: float = 4_000.0
# 4 km orbit at the last waypoint (or spawn), generous enough to avoid
# banking hard; consistent with spec §4.3 "loiter orbit".

# --- Fall physics after kill ---
DRONE_FALL_BANK_RAD: float = math.radians(30.0)
# Tighter spiral than the patrol aircraft (smaller platform, faster).
DRONE_FALL_PITCH_RAD: float = math.radians(15.0)
DRONE_FALL_SPEED_FRAC: float = 0.55
DRONE_FALL_TRANSITION_S: float = 2.0  # s to ramp in the spiral

# --- ELINT receiver ---
ELINT_RANGE_M: float = 450_000.0
# Cap on passive hearing range.  Generous: large-aperture antennas on a high
# platform hear continental-range emissions; spec §4.3 "from far away".

ELINT_BEARING_SIGMA_RAD: float = 0.02
# ~1.1°.  Realistic for a single intercept from a SIGINT pod; accumulation of
# many fixes at different baseline positions drives the quality down.

ELINT_MAX_PAIRS: int = 64
# Cap on stored (drone_pos, bearing) pairs per emitter.  Keeps the least-
# squares matrix bounded; old pairs are evicted FIFO.

ELINT_MIN_PAIR_SPACING_M: float = 800.0
# A new pair is stored only once the drone has moved this far from the
# previous stored pair for that emitter (last_heard still refreshes —
# the emitter WAS heard, the bearing is just redundant).  Bearings taken
# closer together add sub-noise parallax (800 m subtends < sigma even at
# 40 km) and would flush the FIFO: at a 0.5 s listen cadence and 160 m/s
# the raw stream spans only ~5 km of baseline across 64 pairs — never
# enough geometry.  With the spacing gate the retained window spans
# 64 x 800 m ~ 51 km of track, the baseline triangulation actually needs.

ELINT_FIX_ACTIONABLE_M: float = 5_000.0
# Quality threshold below which the fix is good enough to cue a weapon.

EW_ELINT_SIGMA_K: float = 1.0
# M3-F3: how strongly an enemy barrage-jam noise floor widens the passive
# ELINT bearing sigma.  The per-bearing draw uses
#     sigma_eff = ELINT_BEARING_SIGMA_RAD * (1.0 + EW_ELINT_SIGMA_K * floor)
# where ``floor = ew.noise_floor_at(drone_pos, jammers)`` is the DIMENSIONLESS
# jam floor (sim/ew.noise_floor_at; ~1.0 for a nominal Growler at nominal
# standoff range, RNG-free).  CRITICAL: floor == 0 (the default jammers=()) ->
# 1.0 + K*0 == 1.0 EXACTLY -> sigma_eff == ELINT_BEARING_SIGMA_RAD bit-for-bit
# -> the seeded draw is BYTE-IDENTICAL to the no-jam path (the load-bearing
# regression gate).
#
# MODEST by design and CALIBRATED by tools/probe_ew_elint_sigma.py
# (run 2026-06-17, 24 seeds).  At the DEFAULT Growler geometry (200 W,
# EW_DEFAULT_STANDOFF ~150 km behind the screen ~= 230 km from a drone working
# 80 km emitters) the floor reads ~0.42, so sigma inflates ~1.42x and the
# full-pass fix quality is ~1.34x WORSE (probe mean; min 1.16, max 1.42) — a
# real, honest softening the CRLB reports, no flat penalty.  A determined
# cross-track pass STILL reaches an actionable fix under the default Growler on
# EVERY seed (0/24 failures); it just costs more baseline on average (probe:
# ~44.3 -> ~46.9 pairs, 1.06x), and a CLOSER/louder jammer (higher floor)
# softens the fix MORE, exactly as the 1/R**2 physics demands.  Calibrated DOWN
# from a trial K=1.5/2.0: those inflated the fix more (1.5-1.6x) but a moderately
# closer jammer then walled OFF localization entirely (the explicit spec risk:
# "too high and the player can never localize anything while jammed").  K=1.0
# keeps the jam a genuine cost without that wall.  NOTE the single-seed pairs-to-
# actionable is NOT monotone in sigma (a wider draw can luck into an early
# crossing); the monotone effects are the per-step quality (worse at fixed
# baseline) and the seed-AVERAGED pairs cost.

ELINT_CONSISTENCY_MULT: float = 2.0
# Angle-domain self-consistency gate (see _triangulate): a least-squares
# fix whose predicted bearings disagree with the measured ones by more
# than 2x the bearing sigma RMS is geometrically invalid (the min-norm
# collapse of near-parallel lines, or an emitter that moved) — its
# quality is inf, never actionable.  MEASURED: valid-geometry windows
# (60 km baseline, 30-80 km emitters, 8 seeds) sit at 0.71-1.42x sigma;
# degenerate loiter-arc fits that survive the geometry gate below
# measure 2.1-3.7x.

ELINT_MIN_GEOMETRY_RAD: float = 0.25
# Triangulation only counts when the TRUE observer baseline (bounding-box
# diagonal of the stored drone positions — noise cannot fake it) subtends
# at least this angle (~14 deg) at the estimate.  Below it, the bearing
# noise (sigma 0.02 rad) is a non-negligible fraction of the geometric
# spread and least-squares fits can overfit the noise into a confident
# wrong fix (measured: a 4 km loiter arc against a 150 km emitter
# produced transient 'sub-5-km' fixes ~20 km out with consistency under
# 2 sigma; every one had baseline/range < 0.15).  Physically: minutes of
# real cross-track flight are what sharpen the fix (spec §4.3).

# --- Acoustic receiver (M5 sonobuoy / ASW) ---
# The acoustic domain is a DISTINCT sensor domain from radar/ELINT: sound
# travels UNDER the surface, so a passive sonobuoy hears a submarine with NO
# radar horizon and NO terrain LOS (a buoy behind a coastal ridge from the boat
# STILL hears it).  This divergence from ElintReceiver is load-bearing.

SONOBUOY_RANGE_M: float = 35_000.0
# Short FLAT passive detection range (~35 km), much shorter than ELINT's
# continental reach: the player must PLACE buoys near where the boat will be
# (the tasking dilemma).  The actual heard range is further gated by the
# noise-floor-vs-range check below — a quiet creeping boat is heard much closer
# than this cap; a loud launch transient much of the way to it.

ACOUSTIC_BEARING_SIGMA_RAD: float = 0.045
# ~2.6 deg — WIDER than ELINT's 0.02 rad (1.1 deg): a passive hydrophone's
# bearing is coarser than a SIGINT pod's.  A cross-fix from two+ buoys still
# converges with baseline + time, just less sharply than ELINT (so a sharp sub
# fix takes a real buoy line, not one lucky buoy).

ACOUSTIC_DETECT_FLOOR: float = 0.18
# Detection floor (acoustic units / km).  A buoy hears the boat only when its
# radiated noise, attenuated by range, clears this floor:
#     heard  <=>  radiated_noise / (1 + range_km)  >=  ACOUSTIC_DETECT_FLOOR
# (spherical-spreading-ish 1/r falloff, kept simple + monotone).  Calibrated so
# a QUIET APPROACH boat (noise ~1.0) is heard only within ~4-5 km, while a LOUD
# LAUNCH transient (~40) is heard out near the full SONOBUOY_RANGE_M — the
# speed/quietness tradeoff bites exactly here (probe-measured below).

ACOUSTIC_FIX_ACTIONABLE_M: float = 6_000.0
# Quality threshold below which an acoustic cross-fix is good enough to cue the
# ASW weapon.  Slightly looser than ELINT's 5 km (the bearings are coarser); a
# fix this tight still sits well inside ASW_SEEKER_BASKET_M for a clean kill.

ACOUSTIC_CONSISTENCY_MULT: float = 2.0
# Same self-consistency multiplier as ELINT, applied to the WIDER acoustic sigma
# (so the band scales with the coarser bearings — the gate stays meaningful).

ACOUSTIC_MIN_GEOMETRY_RAD: float = 0.20
# Minimum true-baseline subtended angle (~11 deg) for an acoustic fix to count.
# Slightly looser than ELINT's 0.25 because buoys are static (a fixed field
# gives a clean fixed baseline, unlike the drone's swept ELINT arc).

ELINT_RANGE_TEST_SCALES: Tuple[float, float] = (0.5, 2.0)
# Range-observability (likelihood-ratio) gate: bearing-only least squares
# famously collapses range — from a short baseline an emitter at 25 km
# and one at 150 km produce near-identical bearing patterns, and the
# covariance evaluated AT the (wrong, near) estimate looks confident.
# So the fix only counts when sliding the estimate to half and double
# range (about the observation centroid, along the same line of sight)
# BREAKS the consistency band: if either alternative still fits the
# measured bearings, the data do not pin the range and quality is inf.
# Octave steps: a fix whose range is real localizes it well within a
# factor of two (the CRLB then reports the honest tighter error).

# --- M3-F4 self-protect / escort jammer pod ---
DRONE_POD_JAM_POWER_W: float = 200.0
# Effective in-band barrage power (W) of the podded jammer when hot.  The
# player's mirror of the Growler beacon: deliberately matched to the enemy
# JAMMER_POWER_W / ew.EW_DEFAULT_JAM_POWER_W (the calibrated game-balance figure
# the sim/ew.py burn-through field is tuned to) so a hot pod collapses an enemy
# SPY-1 ring by the SAME physics that an enemy Growler collapses the player's.
# A physics reviewer should re-measure against a real ALQ-99/249 pod once a
# dedicated player-EW calibration probe exists.

DRONE_POD_ENEMY_OFFSET_M: float = 1_000.0
# Tiny fixed offset (m) of the enemy-facing pod beacon from the airframe.  The
# pod is physically AT the drone (R ~ 0); offsetting the beacon 1 km keeps the
# sim/ew.py field math finite (no zero-range singularity) while being utterly
# negligible against the ENEMY radars it collapses (those sit 100+ km away, so a
# 1 km shift moves their burn-through ring by < 0.01%).  This is the pod the
# enemy detection path consumes.

DRONE_POD_SELF_DEAFEN_FLOOR: float = 0.75
# Self-deafen noise floor (DIMENSIONLESS, sim/ew.noise_floor_at units) the hot
# pod raises at the drone's OWN passive ELINT receiver.  The pod is ON the
# airframe, so its co-channel desense is a FIXED property of the podded
# transmitter, NOT a 1/R**2 geometry term (R~0 is meaningless / singular).  We
# therefore model the self-deafen as a CALIBRATED, BOUNDED floor rather than a
# distance.
#
# CALIBRATED (probe-style sweep, 20 seeds, in this file's build session):
# 0.75 is ~1.8x the nominal standoff-Growler floor (~0.42, M3-F3) — a genuinely
# HEAVIER cost than an external jammer, because the pod is co-located — yet via
# the recon sigma law sigma_eff = base*(1 + EW_ELINT_SIGMA_K*floor) it inflates
# the bearing sigma only 1.75x.  Measured effect of a determined 60-km-abeam,
# 64-pair cross-track pass on a real ground emitter: the fix quality is ~1.65x
# WORSE on average (every one of 20 seeds softer) but STILL actionable on EVERY
# seed (20/20).  This is the spec's "genuine cost, not a wall" line: the recon
# range-observability / consistency gates tip a fix to inf around sigma ~2x
# (floor ~1.0), so floors >= 1.0 WALL OFF localization entirely (the explicit
# spec risk: "too high and the player can never localize anything while
# jammed") — 0.75 sits deliberately below that knee.  Finite + bounded by
# construction: never a div-by-zero, never inf.  The self-deafen jammer is
# synthesised from this floor (a co-located beacon whose effective power
# back-solves to it), so the SAME deterministic sim/ew.noise_floor_at law
# carries it — no special-case branch, no new RNG.

# --- SAR sensor ---
SAR_HALF_WIDTH_M: float = 25_000.0
# Spec §4.3: "~50 km strip beneath the drone" → ±25 km half-width.

# --- RWR states ---
RWR_CLEAR = "CLEAR"
RWR_SPIKE = "SPIKE"     # search/track radar is illuminating
RWR_LOCK  = "LOCK"      # a missile is guiding on us

# --- Drone state enum ---
DRONE_AIRBORNE  = 0
DRONE_SHOT_DOWN = 1   # falling spiral (not yet impacted)
DRONE_GONE      = 2   # on the ground / destroyed

# Gravity constant (avoids circular import from sim.physics)
_GRAVITY_MPS2: float = 9.806_65


class ReconDrone:
    """High-altitude stealth ELINT/SAR drone.

    Parameters
    ----------
    aircraft_id : str
        Unique track id; default 'drone_00'.  Pass 'drone_01' etc. for
        future multi-drone configs.
    spawn_xz : (x, z) float pair
        Ground-plane spawn position (player base vicinity).
    rng : np.random.Generator, optional
        Seeded random generator shared with the rest of the sim so that
        bearing noise is deterministic in replays.  A fresh default_rng()
        is created if omitted (fine for tests).
    height_fn : callable (x, z) -> float, optional
        Terrain height function; defaults to world.generation.terrain_height_scalar.
        Tests may inject a flat lambda for isolation.
    """

    is_air    = True      # ContactBoard duck-type flag
    radar_size = "stealth"  # enemy radars detect at their 'stealth' range

    def __init__(
        self,
        aircraft_id: str = "drone_00",
        spawn_xz: Tuple[float, float] = (0.0, 0.0),
        rng: Optional[np.random.Generator] = None,
        height_fn=None,
    ):
        from world.generation import terrain_height_scalar
        self._height_fn = height_fn if height_fn is not None else terrain_height_scalar

        self.aircraft_id = aircraft_id
        self.heading: float = 0.0          # rad; 0 = north (+Z), CW
        self.state: int     = DRONE_AIRBORNE
        self._fall_t: float = 0.0          # s elapsed in falling state
        self.impact_pos: Optional[np.ndarray] = None

        sx, sz = float(spawn_xz[0]), float(spawn_xz[1])
        self.pos = np.array([sx, DRONE_ALT_M, sz], dtype=np.float64)

        # Waypoint route; loiter centre defaults to spawn
        self._route: List[Tuple[float, float]] = []
        self._wp_idx: int = 0
        self._loitering: bool = True
        self._loiter_centre: np.ndarray = np.array([sx, 0.0, sz], dtype=np.float64)
        self._loiter_angle: float = 0.0  # current orbit phase (rad)

        self._rng: np.random.Generator = (
            rng if rng is not None else np.random.default_rng()
        )

        # ---- M3-F4 self-protect / escort jammer pod ----
        # A podded barrage jammer the player toggles ON to collapse the ENEMY
        # radar net (sim/ew.py field model, applied against enemy radars in
        # world/combat.py) so a sea-skim salvo leaks — at the cost of going loud
        # (the hot pod deafens the drone's OWN passive ELINT).  ``jam_active``
        # is False by default: an OFF pod is never an active jammer, so the
        # enemy detection calls receive jammers=() and stay byte-identical.
        #
        # TWO duck-typed beacons (both Radar-shaped: ``.pos`` (3,) +
        # ``.jam_power_w``; empty ranges => never sensors), so the ONE
        # deterministic sim/ew.noise_floor_at / burn-through law serves both
        # uses without a special-case branch:
        #   * ``pod_emitter`` — the ENEMY-facing beacon at DRONE_POD_JAM_POWER_W,
        #     offset DRONE_POD_ENEMY_OFFSET_M from the airframe (finite field
        #     math; negligible against the 100+ km enemy radars it collapses).
        #     world/combat.py feeds THIS to the enemy missile-detection calls.
        #   * ``self_deafen_emitter`` — a co-located beacon whose power is
        #     BACK-SOLVED so its noise_floor_at the drone equals the calibrated,
        #     BOUNDED DRONE_POD_SELF_DEAFEN_FLOOR (a fixed co-channel desense, NOT
        #     a 1/R**2 wall).  world/combat.py feeds THIS to the drone's OWN
        #     elint.update so a hot pod softens the player's own fixes by a heavy
        #     but non-infinite amount.
        from sim.radar import Radar as _Radar
        self.pod_emitter = _Radar(
            radar_id=f"{aircraft_id}_pod",
            pos=self.pos.copy(),
            antenna_m=0.0,
            ranges={},
        )
        self.pod_emitter.jam_power_w = float(DRONE_POD_JAM_POWER_W)
        self.pod_emitter.emitting = True   # the BEACON radiates while jam_active

        # Back-solve the self-deafen beacon power so noise_floor_at(drone) lands
        # exactly on DRONE_POD_SELF_DEAFEN_FLOOR at the fixed enemy offset
        # distance:  floor = power * EW_NOISE_REF / R**2  =>
        #            power = floor * R**2 / EW_NOISE_REF.
        # (Lazy import to avoid a sim.ew<->recon import cycle.)
        import sim.ew as _ew
        self_power = (DRONE_POD_SELF_DEAFEN_FLOOR
                      * (DRONE_POD_ENEMY_OFFSET_M ** 2) / _ew.EW_NOISE_REF)
        self.self_deafen_emitter = _Radar(
            radar_id=f"{aircraft_id}_pod_self",
            pos=self.pos.copy(),
            antenna_m=0.0,
            ranges={},
        )
        self.self_deafen_emitter.jam_power_w = float(self_power)
        self.self_deafen_emitter.emitting = True
        self.jam_active: bool = False
        self._sync_pod()

    # ------------------------------------------------------------------
    # Public API — duck-type interop (ContactBoard, tactical map, RWR)
    # ------------------------------------------------------------------

    def set_jam(self, on: bool) -> None:
        """Toggle the EW pod (M3-F4).  ON: the pod radiates the barrage corridor
        that collapses the ENEMY radar net so a salvo leaks, and deafens the
        drone's own passive ELINT (the going-loud cost).  OFF (default): the pod
        is silent, contributes no jammer, byte-identical to the no-pod path."""
        self.jam_active = bool(on)

    def _sync_pod(self) -> None:
        """Keep both pod beacons glued to the airframe, OFFSET by the fixed
        enemy-offset distance so the sim/ew.py field math stays finite (the pod
        is physically at R~0; noise_floor_at / burn_through would otherwise
        singularly blow up).  Called every update() so the pod follows the drone.
        The offset is a fixed +X nudge (1 km << any real emitter range, so it is
        invisible to the enemy-radar collapse geometry; for the co-located
        self-deafen beacon it is the back-solve distance the power was tuned to)."""
        for em in (self.pod_emitter, self.self_deafen_emitter):
            em.pos[0] = self.pos[0] + DRONE_POD_ENEMY_OFFSET_M
            em.pos[1] = self.pos[1]
            em.pos[2] = self.pos[2]

    @property
    def alive(self) -> bool:
        """Targetable / trackable: in controlled flight (not shot down)."""
        return self.state == DRONE_AIRBORNE

    def velocity(self) -> np.ndarray:
        """World-space velocity (3,) float64."""
        if self.state == DRONE_AIRBORNE:
            sp = DRONE_SPEED_MPS
            return np.array([
                math.sin(self.heading) * sp,
                0.0,
                math.cos(self.heading) * sp,
            ], dtype=np.float64)
        if self.state == DRONE_SHOT_DOWN:
            return self._fall_velocity()
        return np.zeros(3, dtype=np.float64)

    @property
    def vel(self) -> np.ndarray:
        return self.velocity()

    @property
    def pitch(self) -> float:
        """Render attitude (Aircraft convention: + = nose up).  Level in
        cruise; the falling spiral ramps in the nose-down pitch over
        DRONE_FALL_TRANSITION_S, matching the flight physics above."""
        if self.state == DRONE_SHOT_DOWN:
            frac = min(1.0, self._fall_t / DRONE_FALL_TRANSITION_S)
            return -DRONE_FALL_PITCH_RAD * frac
        return 0.0

    @property
    def roll(self) -> float:
        """Render attitude (Aircraft convention: + = right wing down).
        Wings level in cruise; the falling spiral banks in over the same
        ramp that drives the banked-turn yaw rate."""
        if self.state == DRONE_SHOT_DOWN:
            frac = min(1.0, self._fall_t / DRONE_FALL_TRANSITION_S)
            return DRONE_FALL_BANK_RAD * frac
        return 0.0

    # ------------------------------------------------------------------
    # Waypoint / loiter
    # ------------------------------------------------------------------

    def set_route(self, waypoints: Sequence[Tuple[float, float]]) -> None:
        """Set the ordered waypoint route.  Call with an empty list to loiter
        in place (at the current position if not already loitering).
        Flying proceeds on the next update() call."""
        self._route = list(waypoints)
        self._wp_idx = 0
        if waypoints:
            self._loitering = False
        else:
            # No route: loiter where we currently are
            self._loitering = True
            self._loiter_centre = np.array(
                [self.pos[0], 0.0, self.pos[2]], dtype=np.float64
            )

    @property
    def route(self) -> List[Tuple[float, float]]:
        """Remaining (x, z) waypoints, oldest first (empty while loitering).
        Mirrors Missile.route so the tactical map's route-polyline drawing
        duck-types across both."""
        if self._loitering or self._wp_idx >= len(self._route):
            return []
        return [(float(w[0]), float(w[1]))
                for w in self._route[self._wp_idx:]]

    def append_waypoint(self, xz) -> bool:
        """RMB tasking from the tactical map: extend the remaining route
        with one more (x, z) leg (a loitering drone breaks orbit and flies
        to it).  Returns True (signature parity with Missile.append_waypoint
        — a recon drone is never 'committed')."""
        remaining = self.route
        remaining.append((float(xz[0]), float(xz[1])))
        self.set_route(remaining)
        return True

    def clear_route(self) -> None:
        """X from the tactical map: drop the remaining route and loiter at
        the current position."""
        self.set_route([])

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self, dt: float) -> None:
        if self.state == DRONE_GONE:
            return
        if self.state == DRONE_SHOT_DOWN:
            self._update_falling(dt)
            self._sync_pod()    # pod tracks the wreck (it never jams once dead)
            return
        # DRONE_AIRBORNE
        if self._loitering:
            self._update_loiter(dt)
        else:
            self._update_route(dt)
        # Hold altitude (no climb/descent model needed — spawns at cruise alt)
        self.pos[1] = DRONE_ALT_M
        self._sync_pod()        # keep the EW pod beacon glued to the airframe

    def _update_route(self, dt: float) -> None:
        """Steer toward the current waypoint; advance when close enough."""
        if self._wp_idx >= len(self._route):
            # All waypoints consumed — enter loiter at last point
            last = self._route[-1] if self._route else (self.pos[0], self.pos[2])
            self._loitering = True
            self._loiter_centre = np.array([float(last[0]), 0.0, float(last[1])],
                                           dtype=np.float64)
            return

        wx, wz = self._route[self._wp_idx]
        dx = float(wx) - self.pos[0]
        dz = float(wz) - self.pos[2]
        dist = math.hypot(dx, dz)

        # Advance when within one second of travel distance OR inside the
        # minimum turn radius (speed / turn-rate = 640 m, +5% margin): a
        # waypoint dropped inside the turning circle is kinematically
        # unreachable, and the old 160 m-only gate trapped the drone in a
        # permanent orbit around it (route stalled, loiter never entered).
        capture = max(DRONE_SPEED_MPS * 1.0,
                      DRONE_SPEED_MPS / DRONE_TURN_RATE_RPS * 1.05)
        if dist < capture:
            self._wp_idx += 1
            if self._wp_idx >= len(self._route):
                # Finished last waypoint — enter loiter
                self._loitering = True
                self._loiter_centre = np.array(
                    [float(wx), 0.0, float(wz)], dtype=np.float64
                )
                return
            wx, wz = self._route[self._wp_idx]
            dx = float(wx) - self.pos[0]
            dz = float(wz) - self.pos[2]

        # Rate-limited heading change
        target_heading = math.atan2(dx, dz)
        err = (target_heading - self.heading + math.pi) % (2.0 * math.pi) - math.pi
        limit = DRONE_TURN_RATE_RPS * dt
        self.heading += min(max(err, -limit), limit)
        self.heading = (self.heading + math.pi) % (2.0 * math.pi) - math.pi

        self.pos[0] += math.sin(self.heading) * DRONE_SPEED_MPS * dt
        self.pos[2] += math.cos(self.heading) * DRONE_SPEED_MPS * dt

    def _update_loiter(self, dt: float) -> None:
        """Circular orbit around _loiter_centre at DRONE_LOITER_RADIUS_M."""
        # Angular rate for the orbit circle: omega = speed / radius
        omega = DRONE_SPEED_MPS / DRONE_LOITER_RADIUS_M
        self._loiter_angle = (self._loiter_angle + omega * dt) % (2.0 * math.pi)
        cx, cz = self._loiter_centre[0], self._loiter_centre[2]
        self.pos[0] = cx + math.sin(self._loiter_angle) * DRONE_LOITER_RADIUS_M
        self.pos[2] = cz + math.cos(self._loiter_angle) * DRONE_LOITER_RADIUS_M
        # Keep heading tangent to the orbit (CW rotation)
        self.heading = (self._loiter_angle + math.pi / 2.0) % (2.0 * math.pi)

    # ------------------------------------------------------------------
    # Kill / falling
    # ------------------------------------------------------------------

    def kill(self) -> None:
        """SM-2 proximity kill: controlled flight ends, spiral descent begins."""
        if self.state != DRONE_AIRBORNE:
            return
        self.state = DRONE_SHOT_DOWN
        self._fall_t = 0.0

    def _fall_speed(self) -> float:
        frac = min(1.0, self._fall_t / DRONE_FALL_TRANSITION_S)
        return DRONE_SPEED_MPS * (1.0 - (1.0 - DRONE_FALL_SPEED_FRAC) * frac)

    def _fall_velocity(self) -> np.ndarray:
        sp = self._fall_speed()
        frac = min(1.0, self._fall_t / DRONE_FALL_TRANSITION_S)
        pitch = -DRONE_FALL_PITCH_RAD * frac
        hs = sp * math.cos(pitch)
        return np.array([
            math.sin(self.heading) * hs,
            sp * math.sin(pitch),
            math.cos(self.heading) * hs,
        ], dtype=np.float64)

    def _update_falling(self, dt: float) -> None:
        """Ramp in spiral bank/pitch; die when altitude reaches terrain."""
        from world.generation import TERRAIN_MAX_HEIGHT
        self._fall_t += dt
        frac = min(1.0, self._fall_t / DRONE_FALL_TRANSITION_S)
        roll  = DRONE_FALL_BANK_RAD  * frac
        pitch = DRONE_FALL_PITCH_RAD * frac  # stored positive; applied negative

        sp = self._fall_speed()
        # Banked-turn yaw rate: g * tan(bank) / speed
        omega = _GRAVITY_MPS2 * math.tan(roll) / max(sp, 1.0)
        self.heading = (
            self.heading + omega * dt + math.pi
        ) % (2.0 * math.pi) - math.pi

        hs = sp * math.cos(pitch)
        self.pos[0] += math.sin(self.heading) * hs * dt
        self.pos[2] += math.cos(self.heading) * hs * dt
        self.pos[1] += sp * math.sin(-pitch) * dt  # negative = descending

        if self.pos[1] > TERRAIN_MAX_HEIGHT:
            return
        surface = max(self._height_fn(float(self.pos[0]), float(self.pos[2])), 0.0)
        if self.pos[1] <= surface:
            self.pos[1] = surface
            self.impact_pos = self.pos.copy()
            self.state = DRONE_GONE


# ---------------------------------------------------------------------------
# ELINT receiver
# ---------------------------------------------------------------------------

class ElintReceiver:
    """Passive emission intelligence sensor mounted on the drone.

    Parameters
    ----------
    rng : np.random.Generator
        Shared sim RNG (seeded) so bearing noise is deterministic.
    height_fn : callable (x, z) -> float, optional
        Terrain height for LOS; defaults to world.generation.terrain_height_scalar.
    """

    def __init__(
        self,
        rng: Optional[np.random.Generator] = None,
        height_fn=None,
    ):
        from world.generation import terrain_height_scalar
        self._height_fn = height_fn if height_fn is not None else terrain_height_scalar
        self._rng: np.random.Generator = (
            rng if rng is not None else np.random.default_rng()
        )
        # emitter_id -> list of (drone_xz [2], bearing_rad)
        self._pairs: dict[str, list] = {}
        # emitter_id -> (fingerprint, (est_pos, quality)) memo for
        # _triangulate: the full solve measures ~210 us at the 64-pair cap
        # and the tactical map asks for fix_quality AND est_pos per emitter
        # per rendered FRAME (game/tactical_map.py _elint_overlay) — ~1.3 ms
        # a frame for 3 emitters, growing with every Phase-5 emitter. The
        # solve is recomputed only when the fingerprint (list identity,
        # length, per-emitter append counter) moves: update() bumps the
        # counter on every stored bearing (append + FIFO eviction included)
        # and a wholesale reassignment (tests) changes the list object.
        self._tri_cache: dict[str, tuple] = {}
        self._pair_seq: dict[str, int] = {}    # appends per emitter
        # emitter_id -> sim_time the emitter was last HEARD (integration
        # seam: the world only treats a fix as live intel while the emitter
        # was heard recently — stale pairs persist for triangulation but a
        # silenced emitter must stop refreshing the player picture).
        self._last_heard: dict[str, float] = {}
        # Solver tuning, held as INSTANCE attributes so a subclass (the M5
        # AcousticReceiver) can run the SAME _solve_triangulation with a wider
        # bearing sigma + its own actionable gate WITHOUT touching the ELINT
        # path.  Defaulting to the ELINT module constants keeps every existing
        # ElintReceiver result BYTE-IDENTICAL (same numbers, just read off self).
        self._bearing_sigma = ELINT_BEARING_SIGMA_RAD
        self._consistency_mult = ELINT_CONSISTENCY_MULT
        self._min_geometry_rad = ELINT_MIN_GEOMETRY_RAD
        self._fix_actionable_m = ELINT_FIX_ACTIONABLE_M

    # ------------------------------------------------------------------
    # Update — called every sim step by the integrator
    # ------------------------------------------------------------------

    def update(
        self,
        drone_pos: np.ndarray,
        emitters: Sequence[Tuple[str, object]],
        sim_time: float = 0.0,
        jammers: Sequence[object] = (),
    ) -> None:
        """Process one sim step of passive listening.

        Parameters
        ----------
        drone_pos : (3,) array  [x, y, z]
        emitters  : iterable of (emitter_id, radar) pairs.
                    Each radar is a sim.radar.Radar-compatible object with
                    .alive, .emitting, .pos, .antenna_alt.
        sim_time  : world clock (s); stamps ``last_heard`` per emitter so
                    the integrator can age intel.  Optional (defaults 0.0)
                    so sensor-level callers/tests stay signature-compatible.
        jammers   : M3-F3 — iterable of active enemy barrage jammers (duck-typed
                    ``.pos`` + ``.jam_power_w``).  Their noise floor at the drone
                    (sim/ew.noise_floor_at) widens the per-bearing sigma so a
                    REAL emitter's fix gets HONESTLY softer under jam (the CRLB
                    then reports a worse quality — physics, not a flat penalty).
                    DEFAULT () -> floor 0 -> sigma unchanged -> the seeded draw
                    is BYTE-IDENTICAL to the no-jammer path (regression gate).
        """
        dx = float(drone_pos[0])
        dy = float(drone_pos[1])
        dz = float(drone_pos[2])

        # Jam noise floor once per pass (lazy import to avoid a sim.ew<->recon
        # import cycle).  Empty jammers -> 0.0 -> sigma scale factor 1.0 ->
        # IDENTICAL draw to today.  RNG-free, pure geometry.
        if jammers:
            import sim.ew as _ew
            floor = _ew.noise_floor_at(drone_pos, jammers,
                                       height_fn=self._height_fn)
        else:
            floor = 0.0
        sigma_eff = ELINT_BEARING_SIGMA_RAD * (1.0 + EW_ELINT_SIGMA_K * floor)

        for emitter_id, radar in emitters:
            if not (radar.alive and radar.emitting):
                continue

            # Range cap (ELINT is generous but not infinite)
            ex = float(radar.pos[0])
            ey_antenna = float(radar.antenna_alt)
            ez = float(radar.pos[2])
            gnd_range = math.hypot(dx - ex, dz - ez)
            if gnd_range > ELINT_RANGE_M:
                continue

            # Radar-horizon check: can the drone actually receive at this range?
            if gnd_range > radar_horizon_m(dy, ey_antenna):
                continue

            # Terrain LOS (using the injected height_fn via a thin lambda so
            # terrain_blocks' height_fn parameter is honoured)
            emitter_3d = np.array([ex, ey_antenna, ez], dtype=np.float64)
            if terrain_blocks(drone_pos, emitter_3d,
                              height_fn=self._height_fn):
                continue

            # Heard — the emitter is live intel regardless of whether the
            # bearing below is stored (spacing gate).
            self._last_heard[emitter_id] = float(sim_time)

            pairs = self._pairs.setdefault(emitter_id, [])
            if pairs:
                last_xz = pairs[-1][0]
                if math.hypot(dx - float(last_xz[0]),
                              dz - float(last_xz[1])) \
                        < ELINT_MIN_PAIR_SPACING_M:
                    continue      # redundant parallax: keep the window wide

            # Accumulate a bearing fix with gaussian noise.  sigma_eff is the
            # base sigma scaled by the jam floor (== base when floor==0, so the
            # draw is byte-identical to the no-jam path).
            true_bearing = math.atan2(ex - dx, ez - dz)  # drone -> emitter
            noisy_bearing = true_bearing + float(
                self._rng.normal(0.0, sigma_eff)
            )
            # Normalise to (-pi, pi]
            noisy_bearing = (noisy_bearing + math.pi) % (2.0 * math.pi) - math.pi

            pairs.append((np.array([dx, dz], dtype=np.float64), noisy_bearing))
            if len(pairs) > ELINT_MAX_PAIRS:
                pairs.pop(0)      # FIFO eviction — oldest fix out
            # Invalidate the memoized triangulation (see _tri_cache)
            self._pair_seq[emitter_id] = \
                self._pair_seq.get(emitter_id, 0) + 1

    # ------------------------------------------------------------------
    # Triangulation helpers
    # ------------------------------------------------------------------

    def _triangulate(self, emitter_id: str) -> Tuple[Optional[np.ndarray], float]:
        """Memoized front-end for _solve_triangulation (cache rationale at
        ``_tri_cache``).  Callers must not mutate the returned array — the
        one integration consumer (world/combat.py) copies it."""
        pairs = self._pairs.get(emitter_id, [])
        if len(pairs) < 2:
            return None, float("inf")
        fp = (id(pairs), len(pairs), self._pair_seq.get(emitter_id, 0))
        cached = self._tri_cache.get(emitter_id)
        if cached is not None and cached[0] == fp:
            return cached[1]
        result = self._solve_triangulation(pairs)
        self._tri_cache[emitter_id] = (fp, result)
        return result

    def _solve_triangulation(
            self, pairs: list) -> Tuple[Optional[np.ndarray], float]:
        """Least-squares position estimate from stored bearing pairs.

        Coordinate system: X = east, Z = north.
        Bearing convention: theta = atan2(X_emitter - X_drone, Z_emitter - Z_drone),
        i.e. 0 = north (+Z), increasing clockwise — same as the rest of the sim.

        For each observation the emitter lies on the ray from (Xd, Zd) in
        direction (sin(theta), cos(theta)).  The cross-product constraint:

            cos(theta) * (X - Xd) = sin(theta) * (Z - Zd)
            cos(theta)*X - sin(theta)*Z = cos(theta)*Xd - sin(theta)*Zd

        Rearranged into A @ [X, Z]^T = b, row i:
            A_i = [cos(theta_i),  -sin(theta_i)]
            b_i = cos(theta_i)*Xdrone_i - sin(theta_i)*Zdrone_i

        With >= 2 non-collinear bearing lines this system is overdetermined and
        the least-squares solution gives the best-fit intersection.  The RMS of
        the residuals is a proxy for position uncertainty (metres).
        """
        rows_A = []
        rows_b = []
        for drone_xz, bearing in pairs:
            s = math.sin(bearing)
            c = math.cos(bearing)
            xd, zd = float(drone_xz[0]), float(drone_xz[1])
            rows_A.append([c, -s])
            rows_b.append(c * xd - s * zd)

        A = np.array(rows_A, dtype=np.float64)
        b = np.array(rows_b, dtype=np.float64)

        # numpy lstsq: tolerant of near-singular (returns best fit)
        x, residuals, rank, _ = np.linalg.lstsq(A, b, rcond=None)
        if rank < 2:
            return None, float("inf")
        est_pos = np.array([x[0], 0.0, x[1]], dtype=np.float64)

        # Quality: NOT the raw lstsq residual (Phase-4 integration bug).
        # Nearly-parallel bearing lines (a short baseline against a far
        # emitter) agree with each other almost perfectly — residual RMS
        # ~ 0 — while the along-bearing position is unconstrained
        # garbage, AND lstsq's minimum-norm solution collapses onto the
        # solution ridge nearest the origin, i.e. right next to the
        # drone (a base-loitering drone 150 km from an emitter produced
        # a 'sub-5-km' fix 125+ km off).  Worse, with FEW pairs the
        # bearing NOISE itself fakes angular diversity, so any metric
        # built from the measured bearings can be fooled.  Two defenses:
        #
        #   1. Angle-domain self-consistency: re-predict every bearing
        #      from the estimate; an RMS disagreement beyond
        #      ELINT_CONSISTENCY_MULT x the bearing sigma means the
        #      linear model is invalid (collapse, or a moving emitter
        #      smearing the pairs) — quality inf, never actionable.
        #   2. Cramer-Rao quality from the observation GEOMETRY: Fisher
        #      information J = (1/sigma^2) * sum_i (p_i p_i^T / r_i^2),
        #      p_i = unit vector perpendicular to the PREDICTED line of
        #      sight observer_i -> estimate, r_i = that range.  Built
        #      from true drone positions + the estimate only — noise
        #      cannot fake angular diversity here: clustered observers
        #      against a far source give parallel perpendiculars and a
        #      singular J (quality inf) no matter what the noisy
        #      bearings claim.  quality = sqrt(trace(inv(J))).
        n = len(pairs)
        ang_sq = 0.0
        j00 = j01 = j11 = 0.0
        range_sum = 0.0
        cx_sum = cz_sum = 0.0
        min_x = min_z = float("inf")
        max_x = max_z = float("-inf")
        for dxz, theta in pairs:
            ox, oz = float(dxz[0]), float(dxz[1])
            cx_sum += ox
            cz_sum += oz
            min_x, max_x = min(min_x, ox), max(max_x, ox)
            min_z, max_z = min(min_z, oz), max(max_z, oz)
            ddx = float(x[0]) - ox
            ddz = float(x[1]) - oz
            r2 = ddx * ddx + ddz * ddz
            if r2 < 1.0:
                return est_pos, float("inf")   # collapsed onto an observer
            range_sum += math.sqrt(r2)
            pred = math.atan2(ddx, ddz)
            d = (theta - pred + math.pi) % (2.0 * math.pi) - math.pi
            ang_sq += d * d
            # unit perp to LOS is (-ddz, ddx)/r: pp^T / r^2 = outer/r^4
            w = 1.0 / (r2 * r2)
            j00 += ddz * ddz * w
            j01 -= ddz * ddx * w
            j11 += ddx * ddx * w
        rms_ang = math.sqrt(ang_sq / n)
        band = self._consistency_mult * self._bearing_sigma
        if rms_ang > band:
            return est_pos, float("inf")
        # Geometry gate: the true baseline must subtend a real angle.
        baseline = math.hypot(max_x - min_x, max_z - min_z)
        if baseline < self._min_geometry_rad * (range_sum / n):
            return est_pos, float("inf")
        # Range-observability gate (ELINT_RANGE_TEST_SCALES doc): each
        # scaled alternative must FAIL the consistency band the estimate
        # passed, or the range is not actually pinned by the data.
        #
        # SURROUND EXCEPTION (M5 ASW): the range ridge this gate hunts exists
        # only when every observer sees the source from ONE SIDE (all of them
        # inside a half-plane through the estimate).  A sonobuoy field that
        # BRACKETS the boat — the textbook ASW pattern — puts the estimate
        # near the observer centroid, so the scaled alternatives barely move,
        # trivially re-fit the bearings, and the gate false-kills the BEST
        # geometry (measured: 4-buoy box, est error ~1 km, killed to inf).
        # When the estimate->observer directions leave no circular gap of
        # half a turn or more, no half-plane contains them all: range is
        # pinned by construction and the scale test is skipped (the CRLB
        # below still reports the honest error).  One-sided arcs always have
        # a gap >= pi, so ELINT drone-loiter geometry is untouched.
        cx = cx_sum / n
        cz = cz_sum / n
        surrounded = False
        if n >= 3:
            phis = sorted(math.atan2(float(dxz[0]) - float(x[0]),
                                     float(dxz[1]) - float(x[1]))
                          for dxz, _theta in pairs)
            max_gap = 2.0 * math.pi + phis[0] - phis[-1]
            for i in range(1, n):
                max_gap = max(max_gap, phis[i] - phis[i - 1])
            surrounded = max_gap < math.pi
        for scale in (() if surrounded else ELINT_RANGE_TEST_SCALES):
            ax = cx + (float(x[0]) - cx) * scale
            az = cz + (float(x[1]) - cz) * scale
            alt_sq = 0.0
            for dxz, theta in pairs:
                pred = math.atan2(ax - float(dxz[0]), az - float(dxz[1]))
                d = (theta - pred + math.pi) % (2.0 * math.pi) - math.pi
                alt_sq += d * d
            if math.sqrt(alt_sq / n) <= band:
                return est_pos, float("inf")
        sigma_eff = max(rms_ang, self._bearing_sigma)
        det = j00 * j11 - j01 * j01
        if det <= 1e-30:
            return est_pos, float("inf")       # geometry pins nothing
        # trace(inv(M)) for a 2x2 = trace(adj(M))/det = (j00 + j11)/det
        quality_m = max(sigma_eff * math.sqrt((j00 + j11) / det), 1.0)
        return est_pos, quality_m

    def fix_quality(self, emitter_id: str) -> float:
        """Estimated position error (m) for the given emitter.

        Returns inf when fewer than 2 bearing pairs are stored or the
        geometry is degenerate.  Decreases as bearing geometry improves
        (wider baseline, more pairs).
        """
        _, quality = self._triangulate(emitter_id)
        return quality

    def est_pos(self, emitter_id: str) -> Optional[np.ndarray]:
        """Best-estimate (X, Y=0, Z) surface position, or None if ungated."""
        pos, _ = self._triangulate(emitter_id)
        return pos

    def is_actionable(self, emitter_id: str) -> bool:
        """True when fix quality is below the actionable threshold
        (ELINT_FIX_ACTIONABLE_M for ELINT; the acoustic subclass overrides it)."""
        return self.fix_quality(emitter_id) < self._fix_actionable_m

    def heard_emitters(self) -> List[str]:
        """List of emitter ids for which at least one bearing pair exists."""
        return [eid for eid, pairs in self._pairs.items() if pairs]

    def last_heard(self, emitter_id: str) -> Optional[float]:
        """sim_time the emitter was last heard (the ``sim_time`` passed to
        update), or None when never heard.  The integrator gates the player
        picture on this: a silenced emitter's fix stops refreshing and the
        injected contact ages out like any lost track (intel aging)."""
        return self._last_heard.get(emitter_id)

    def latest_bearing(self, emitter_id: str) -> Optional[Tuple[np.ndarray, float]]:
        """Newest (drone_xz (2,), bearing_rad) pair for the emitter, or
        None.  The tactical map draws the live ELINT bearing ray from this
        intercept point along the heard bearing."""
        pairs = self._pairs.get(emitter_id)
        if not pairs:
            return None
        return pairs[-1]


# ---------------------------------------------------------------------------
# Acoustic receiver (M5 sonobuoy field / ASW)
# ---------------------------------------------------------------------------

class AcousticReceiver(ElintReceiver):
    """Passive acoustic triangulator for a player sonobuoy field.

    REUSES ElintReceiver's least-squares solver (_solve_triangulation: the same
    A @ [X, Z] = b cross-fix, CRLB quality, consistency/geometry/range-
    observability gates) VERBATIM, but the acoustic domain DIVERGES from radar/
    ELINT in two load-bearing ways:

      * NO radar horizon and NO terrain LOS — sound travels under the surface,
        so a buoy behind a coastal ridge from the boat STILL hears it.  ``update``
        therefore never calls radar_horizon_m / terrain_blocks (the property a
        test pins).
      * Detection is a NOISE-FLOOR-vs-RANGE physics check on the boat's
        ``radiated_noise()``, scaled by the wider ACOUSTIC_BEARING_SIGMA_RAD: a
        quiet creeping boat is heard only very close, a loud launch transient
        most of the way to the short SONOBUOY_RANGE_M cap.

    The observers are MANY STATIC buoys (vs ELINT's ONE moving drone).  Each
    step rebuilds, per sub, the (buoy_xz, bearing) pair list from the buoys that
    currently hear it — so the solver sees the live cross-fix geometry of the
    field.  ONE buoy -> one bearing, no actionable fix (bearing-only); TWO+ with
    baseline -> an actionable cross-fix that sharpens as more buoys hear it.

    Determinism: bearing noise is drawn from the injected child stream
    ([seed, 14] sonar) — same seed -> same fix.
    """

    def __init__(self, rng: Optional[np.random.Generator] = None):
        # No height_fn needed (acoustics ignore terrain) — pass a trivial one so
        # the base __init__ does not import the world terrain module.
        super().__init__(rng=rng, height_fn=lambda x, z: -10_000.0)
        # Override the solver tuning for the WIDER, looser acoustic domain.
        self._bearing_sigma = ACOUSTIC_BEARING_SIGMA_RAD
        self._consistency_mult = ACOUSTIC_CONSISTENCY_MULT
        self._min_geometry_rad = ACOUSTIC_MIN_GEOMETRY_RAD
        self._fix_actionable_m = ACOUSTIC_FIX_ACTIONABLE_M
        # sub_id -> count of buoys currently hearing it (for the bearing-only
        # vs cross-fix UI / gating).
        self._hearing_count: dict[str, int] = {}

    @staticmethod
    def heard(noise: float, range_m: float) -> bool:
        """Noise-floor-vs-range physics: a buoy hears a source of radiated
        ``noise`` at ``range_m`` only when the attenuated level clears the floor.
        Spherical-ish 1/r falloff (kept simple + monotone)."""
        if range_m > SONOBUOY_RANGE_M or noise <= 0.0:
            return False
        range_km = range_m / 1_000.0
        return (noise / (1.0 + range_km)) >= ACOUSTIC_DETECT_FLOOR

    def update(self, subs: Sequence[object], buoy_positions: Sequence[np.ndarray],
               sim_time: float = 0.0) -> None:
        """One acoustic listening pass.

        Parameters
        ----------
        subs : iterable of Submarine-compatible objects, each with ``.sub_id``,
               ``.pos`` (3,), ``.alive`` and ``.radiated_noise() -> float`` plus
               ``.launch_transient`` (a one-tick spike flag).
        buoy_positions : iterable of (x, y, z) or (x, z) buoy world positions.
        sim_time : world clock (s); stamps ``last_heard`` per sub.

        NO horizon / terrain calls (the acoustic divergence).  Rebuilds the
        per-sub pair list from the buoys hearing it THIS pass so the solver sees
        the live field geometry."""
        buoys_xz = [(float(b[0]), float(b[-1])) for b in buoy_positions]
        for sub in subs:
            if not getattr(sub, "alive", True):
                continue
            sid = getattr(sub, "sub_id", "ssk")
            sx = float(sub.pos[0])
            sz = float(sub.pos[2])
            # The launch transient is a far-louder one-tick spike heard much
            # farther than the steady radiated noise.
            noise = float(sub.radiated_noise())
            if getattr(sub, "launch_transient", False):
                noise = max(noise, SUB_LAUNCH_TRANSIENT)
            pairs = []
            for bx, bz in buoys_xz:
                rng_m = math.hypot(bx - sx, bz - sz)
                if not self.heard(noise, rng_m):
                    continue
                # True bearing buoy -> sub, plus seeded acoustic noise.
                true_bearing = math.atan2(sx - bx, sz - bz)
                noisy = true_bearing + float(
                    self._rng.normal(0.0, self._bearing_sigma))
                noisy = (noisy + math.pi) % (2.0 * math.pi) - math.pi
                pairs.append((np.array([bx, bz], dtype=np.float64), noisy))
            self._hearing_count[sid] = len(pairs)
            if pairs:
                self._last_heard[sid] = float(sim_time)
                # Fresh list object each pass -> the _triangulate cache key
                # (id(pairs), len, seq) moves, so the solve recomputes.
                self._pairs[sid] = pairs
                self._pair_seq[sid] = self._pair_seq.get(sid, 0) + 1
            else:
                # No buoy hears it this pass: drop the stored geometry (the fix
                # goes stale; the world ages the injected track out separately).
                self._pairs.pop(sid, None)

    def hearing_count(self, sub_id: str) -> int:
        """Number of buoys that heard the sub on the last pass (0 = silent,
        1 = bearing-only, 2+ = a cross-fix is possible)."""
        return self._hearing_count.get(sub_id, 0)


# ---------------------------------------------------------------------------
# SAR sensor
# ---------------------------------------------------------------------------

class SarSensor:
    """Synthetic-aperture / optical look-down sensor.

    A simple 2D strip of half-width SAR_HALF_WIDTH_M (±25 km) centred on
    the drone's ground-track point.  The integrator calls detects() to check
    whether a surface target falls within the footprint.

    Only surface (non-air) targets make sense here; the integrator is
    responsible for filtering.
    """

    def detects(self, drone_pos: np.ndarray, target_pos: np.ndarray) -> bool:
        """True when target_pos is within the SAR strip under the drone.

        The strip axis is the drone's heading (not used in this flat-earth
        approximation — spec calls for a simple 50 km wide strip, so we use
        a 2D cylinder / slab centred on the drone ground position).

        For a more accurate model the strip is defined by the perpendicular
        distance from the drone's nadir point in the cross-track direction;
        since spec says "50 km strip beneath the drone" and the drone flies
        a straight route, the cross-track half-width equals the full strip
        radius used here (any point within 25 km of nadir is imaged).
        """
        dx = float(target_pos[0]) - float(drone_pos[0])
        dz = float(target_pos[2]) - float(drone_pos[2])
        dist = math.hypot(dx, dz)
        return dist <= SAR_HALF_WIDTH_M


# ---------------------------------------------------------------------------
# RWR receiver
# ---------------------------------------------------------------------------

class RwrReceiver:
    """Radar Warning Receiver.

    Exposes per-threat state (SPIKE / LOCK / CLEAR) and emits the alert list
    consumed by the HUD.

    Parameters
    ----------
    drone_id : str, optional
        The aircraft_id of the drone this RWR is mounted on.  Used to filter
        the missile list: only missiles whose .target.aircraft_id matches
        this id produce a LOCK alert.  If None (not recommended), any live
        missile with a non-None target triggers a LOCK (legacy behaviour).
    height_fn : callable (x, z) -> float, optional
        Terrain height for the SPIKE LOS check (same one used by Radar.detects).
    """

    def __init__(self, drone_id: Optional[str] = None, height_fn=None):
        from world.generation import terrain_height_scalar
        self._height_fn = height_fn if height_fn is not None else terrain_height_scalar
        self._drone_id: Optional[str] = drone_id
        # emitter_id -> RWR_SPIKE | RWR_LOCK | RWR_CLEAR
        self._states: dict[str, str] = {}
        # emitter_id -> bearing_deg (for the HUD)
        self._bearings: dict[str, float] = {}

    # ------------------------------------------------------------------

    def update(
        self,
        drone_pos: np.ndarray,
        enemy_radars: Sequence[object],
        enemy_missiles: Sequence[object],
    ) -> None:
        """Refresh all threat states.

        Parameters
        ----------
        drone_pos      : (3,) float64 drone world position [x, y, z]
        enemy_radars   : iterable of sim.radar.Radar (or duck-type) objects
        enemy_missiles : iterable of in-flight enemy SAM rounds (sim.sam.SamMissile
                         duck-type); we check .target == drone for LOCK state.
        """
        dx = float(drone_pos[0])
        dz = float(drone_pos[2])

        # Reset all to CLEAR, then apply threats
        for k in self._states:
            self._states[k] = RWR_CLEAR

        # --- SPIKE: any enemy radar currently illuminates the drone -------
        for radar in enemy_radars:
            if not (radar.alive and radar.emitting):
                continue
            eid = radar.radar_id
            # Bearing: drone looking toward the radar emitter
            ex = float(radar.pos[0])
            ez = float(radar.pos[2])
            bearing_rad = math.atan2(ex - dx, ez - dz)
            bearing_deg = math.degrees(bearing_rad) % 360.0

            # Use Radar.detects() with our size class — exactly the same LOS
            # and horizon rules that active radar would use (passive-sensing
            # obeys the same geometry per locked conventions)
            if radar.detects(drone_pos, "stealth"):
                self._states[eid] = RWR_SPIKE
                self._bearings[eid] = bearing_deg
            else:
                if eid not in self._states:
                    self._states[eid] = RWR_CLEAR
                    self._bearings[eid] = bearing_deg

        # --- LOCK: an enemy radar-guided missile is targeting this drone ------
        # IR missiles (IrMissile, AIM-9X class) are PASSIVE seekers — they
        # generate no radar emission and must never trigger a LOCK alert.
        # A missile opts IN to RWR lock detection via the ``rwr_generates_lock``
        # class/instance attribute (default True for backward compat, but
        # IrMissile sets it False per the passive-seeker contract).
        for missile in enemy_missiles:
            if not getattr(missile, "alive", False):
                continue
            if not getattr(missile, "rwr_generates_lock", True):
                continue   # passive-seeker: no RWR event (IR, spec §5.1)
            tgt = getattr(missile, "target", None)
            if tgt is None:
                continue
            # Check that the missile is targeting THIS drone.  Compare by
            # aircraft_id when available; fall back to identity comparison.
            tgt_id = getattr(tgt, "aircraft_id", None)
            if self._drone_id is not None:
                # Strict: only register LOCK if this missile targets our drone id
                if tgt_id != self._drone_id:
                    continue
            # Record the LOCK state keyed by a stable missile identifier
            mid = getattr(missile, "missile_id",
                          getattr(missile, "aircraft_id", str(id(missile))))
            self._states[mid] = RWR_LOCK
            # Bearing toward the missile (not the launcher)
            mx = float(missile.pos[0])
            mz = float(missile.pos[2])
            bearing_rad = math.atan2(mx - dx, mz - dz)
            self._bearings[mid] = math.degrees(bearing_rad) % 360.0

    # ------------------------------------------------------------------

    def alerts(self) -> List[Tuple[str, float]]:
        """Return current alert list: [(level, bearing_deg), ...].

        level is RWR_SPIKE or RWR_LOCK (CLEAR threats are suppressed).
        LOCK alerts are listed before SPIKE alerts (higher priority).
        """
        result = []
        for eid, state in self._states.items():
            if state in (RWR_SPIKE, RWR_LOCK):
                result.append((state, self._bearings.get(eid, 0.0)))
        # LOCK first, then SPIKE
        result.sort(key=lambda t: (0 if t[0] == RWR_LOCK else 1, t[1]))
        return result

    def threat_state(self, emitter_id: str) -> str:
        """Current state string for a specific emitter id."""
        return self._states.get(emitter_id, RWR_CLEAR)
