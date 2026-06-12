"""Enemy air entities for COMBAT mode (pure numpy, GL-free, SI units, +Y up).

Contains:

  AirBase        — shared interface over the two fighter recovery sites.
                   Wraps either a Structure (the airfield) or a Carrier.
  nearest_surviving_base — module-level helper.

  Carrier        — CVN-class carrier ship (subclasses Destroyer because the
                   navigation pattern is identical; see design note below).

  Fighter        — F/A-18E-class air entity with a full PARKED … PARKED
                   state machine, fuel accounting, and a forward-cone nose radar.

  Awacs          — E-2/E-3-class racetrack orbiter with a wide-area radar and
                   a flee() method for the commander (wired in Phase 5b).

Design notes
------------
Carrier subclasses Destroyer
    The carrier shares the same racetrack station-keeping logic, the same
    damage ladder (alive/burning/sinking/gone inherited from Ship), and the same
    OBB.  Subclassing Destroyer reuses all of that without copy-paste.  The only
    behavioural difference is that the carrier has no active radar in 5a (doctrine:
    it runs silent under AWACS / escort umbrella) and larger dimensions / more HP.
    One could instead subclass Ship directly, but then the racetrack builder and
    radar-sync code would have to be reproduced — worse separation than the extra
    level of inheritance.

Fighter nose-radar cone
    The spec says "forward cone ±60 deg".  Rather than adding optional fields to
    Radar (breaking existing callers) we wrap the Radar in FighterRadar, which
    delegates to Radar.detects but adds an angular prefilter against the fighter's
    current heading.  Existing Radar objects are untouched.

Axes / conventions (locked)
    X = east, Y = up (altitude), Z = north; heading 0 = +Z, clockwise from above.
    All distances in metres, speeds in m/s, times in seconds, float64.
"""

from __future__ import annotations

import math
import collections
from typing import Optional, Union

import numpy as np

import sim.radar as _radar_mod
from sim.enemy_ships import Destroyer, _build_racetrack
from sim.ships import (BURN_TIME, SHIP_TYPES, ST_ALIVE, ST_BURNING,
                       TURN_RATE as SHIP_TURN_RATE)

# ---------------------------------------------------------------------------
# Carrier ship registration
# ---------------------------------------------------------------------------
# Nimitz/Ford-class: 333 m long, 40 m beam, 30 m flight-deck height.
# HP 6 — takes multiple Oniks hits before going down (spec §5.4).
SHIP_TYPES["carrier"] = dict(
    length=333.0,
    beam=40.0,
    height=30.0,
    speed=12.0,    # ~23 kt operational speed
    hp=6,
)

# ---------------------------------------------------------------------------
# Tuning constants — all named with units and justification
# ---------------------------------------------------------------------------

# Fighter cruise speed: F/A-18E typical subsonic cruise ~240 m/s (~Mach 0.7).
FIGHTER_CRUISE_MPS: float = 240.0

# Fighter patrol altitude: 9 000 m — comparable to a typical CAP altitude.
FIGHTER_ALT_M: float = 9_000.0

# Fighter turn rate: ~3 deg/s sustained bank-to-bank at cruise altitude.
# Real F/A-18 sustained turn is ~6 deg/s at sea-level; at altitude ~3 deg/s.
FIGHTER_TURN_RATE: float = math.radians(3.0)   # rad/s

# Fighter endurance: 2 400 s (~40 min) of airborne time before bingo.
# Rationale: combat radius ~740 km at cruise gives ~2×740/240 ≈ 3 700 s
# for a full round trip, so 2 400 s is a conservative internal-fuel fraction
# ensuring a fighter RTBs with reserve before true fuel exhaustion.
FIGHTER_ENDURANCE_S: float = 2_400.0

# Bingo fuel threshold: 20 % of total endurance remaining forces RTB.
FIGHTER_BINGO_FRAC: float = 0.20

# Takeoff/climb speed (slower while in ground effect climbing out).
FIGHTER_CLIMB_SPEED_MPS: float = 120.0

# Climb vertical rate: ~30 m/s (~6 000 ft/min), typical fighter climb.
FIGHTER_CLIMB_RATE_MPS: float = 30.0

# Landing descent rate: gentle 5 m/s (300 ft/min), carrier/airfield compatible.
FIGHTER_DESCENT_RATE_MPS: float = 5.0

# Rearm time: 90 s per fighter, one at a time per base (spec §5.1).
REARM_S: float = 90.0

# Racetrack half-length for the fighter patrol orbit.
FIGHTER_ORBIT_HALF_LEN_M: float = 50_000.0  # 50 km legs — wide CAP coverage

# Map-edge egress distance: fighters fly to this distance from world centre
# when both bases dead before transitioning to GONE.
MAP_EDGE_EGRESS_M: float = 700_000.0   # 700 km, safely beyond the scenario area

# Nose-radar forward half-cone: ±60 deg.
FIGHTER_RADAR_FOV_HALF: float = math.radians(60.0)

# Fighter nose-radar ranges (metres) by target size class (spec §3).
FIGHTER_RADAR_RANGES: dict = {
    "fighter": 110_000.0,
    "ship":     80_000.0,
    "missile":  60_000.0,
    "stealth":  11_000.0,   # 10% of 110 km — drone is very hard to detect
}

# AWACS altitude: 9 100 m (spec §5.3 "orbits deep", ~30 000 ft).
AWACS_ALT_M: float = 9_100.0

# AWACS cruise speed: 130 m/s (~E-2C cruise ~250 kt, E-3 ~460 kt; 130 m/s is
# E-2C territory — the slower platform matches the "orbit deep" role).
AWACS_CRUISE_MPS: float = 130.0

# AWACS radar ranges (metres) by target size class (spec §5.3).
AWACS_RADAR_RANGES: dict = {
    "fighter": 400_000.0,
    "ship":    350_000.0,
    "missile": 350_000.0,
    "stealth":  40_000.0,  # look-down vs drone: 10% of 400 km
}

# AWACS radar antenna altitude above the aircraft body — the aircraft IS the
# antenna platform; we use the aircraft altitude itself (pos[1]).
AWACS_ANTENNA_OFFSET_M: float = 0.0

# AWACS flee speed: same as cruise (unarmed: just run flat-out).
AWACS_FLEE_SPEED_MPS: float = AWACS_CRUISE_MPS

# Orbit half-length for the AWACS racetrack.
AWACS_ORBIT_HALF_LEN_M: float = 80_000.0

# Carrier racetrack geometry.
CARRIER_PATROL_RADIUS_M: float = 15_000.0  # 15 km legs (slow hull, small orbit)

# Kill-spiral attitude (shared by Fighter and Awacs; same shape as the
# Aircraft/ReconDrone spirals): bank/pitch ramp in over the transition,
# driving both the falling flight path AND the render pitch/roll
# properties the draw pass reads (game/combat.py rot conventions).
FALL_BANK_RAD: float = math.radians(25.0)
FALL_PITCH_RAD: float = math.radians(12.0)
FALL_TRANSITION_S: float = 2.5

# ---------------------------------------------------------------------------
# Fighter state constants
# ---------------------------------------------------------------------------
(
    FS_PARKED,
    FS_TAKEOFF,
    FS_TRANSIT,
    FS_ON_STATION,
    FS_RTB,
    FS_LANDING,
    FS_REARMING,
    FS_WINCHESTER_EGRESS,
    FS_GONE,
) = range(9)


# ---------------------------------------------------------------------------
# AirBase — shared interface
# ---------------------------------------------------------------------------

class AirBase:
    """Shared recovery interface over an airfield Structure or a Carrier.

    Parameters
    ----------
    site :
        Either a ``sim.bases.Structure`` (airfield, player-side or enemy
        airfield) or a ``Carrier`` instance.  Both expose ``.alive`` and
        ``.pos`` — that is the full duck-type contract required here.

    The rearm queue is a simple FIFO deque.  Only one fighter rearms at a
    time per base (spec §5.1).  ``can_recover`` is True when the base is
    alive — even during rearming another fighter can arrive and queue up.
    """

    def __init__(self, site):
        self._site = site
        self.parked: list = []          # fighters currently parked
        self._rearm_queue: collections.deque = collections.deque()
        self._rearm_timer: float = 0.0  # counts down; 0 = queue is idle

    # --- passthrough properties -----------------------------------------------

    @property
    def alive(self) -> bool:
        return bool(self._site.alive)

    @property
    def pos(self) -> np.ndarray:
        """World-space 3D position of the base (float64 (3,))."""
        p = self._site.pos
        # Structures store full 3-D pos; Carrier.pos is also 3-D (Ship).
        return np.asarray(p, dtype=np.float64)

    @property
    def can_recover(self) -> bool:
        """True when the base is alive (queue can grow even while rearming)."""
        return self.alive

    # --- rearm machinery -------------------------------------------------------

    def request_rearm(self, fighter: "Fighter") -> None:
        """Fighter calls this on landing; joins the FIFO queue."""
        if fighter not in self._rearm_queue and fighter not in self.parked:
            self._rearm_queue.append(fighter)

    def update(self, dt: float) -> None:
        """Advance the rearm queue; fires fighter.rearm_complete() when done."""
        if not self._rearm_queue:
            self._rearm_timer = 0.0
            return
        if self._rearm_timer <= 0.0:
            # Start rearming the head of the queue.
            self._rearm_timer = REARM_S
        self._rearm_timer -= dt
        if self._rearm_timer <= 0.0:
            fighter = self._rearm_queue.popleft()
            self.parked.append(fighter)
            fighter._rearm_complete()


# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------

def nearest_surviving_base(
    pos: np.ndarray,
    bases: list[AirBase],
) -> Optional[AirBase]:
    """Return the nearest alive AirBase to *pos*, or None if all are dead."""
    best: Optional[AirBase] = None
    best_dist: float = math.inf
    px, pz = float(pos[0]), float(pos[2])
    for base in bases:
        if not base.alive:
            continue
        bpos = base.pos
        d = math.hypot(float(bpos[0]) - px, float(bpos[2]) - pz)
        if d < best_dist:
            best_dist = d
            best = base
    return best


# ---------------------------------------------------------------------------
# Carrier — CVN-class carrier ship
# ---------------------------------------------------------------------------

class Carrier(Destroyer):
    """CVN-class enemy aircraft carrier (spec §5.4).

    Subclasses Destroyer to reuse the racetrack station-keeping loop and the
    full ALIVE→BURNING→SINKING→GONE damage ladder unchanged.

    No active radar in Phase 5a: the carrier runs silent under its AWACS /
    escort umbrella (doctrine; ``self.radar.emitting = False`` is set in
    __init__ so ELINT cannot hear it).  The radar *object* exists so Phase 5b
    can flip ``.emitting`` to True without structural changes.
    """

    def __init__(
        self,
        ship_id: str,
        anchor_xz,
        heading_deg: float = 0.0,
        patrol_radius_m: float = CARRIER_PATROL_RADIUS_M,
    ):
        # Destroyer.__init__ uses ship_type='destroyer'; we pass it through
        # but then overwrite spec attrs from the 'carrier' entry we just added
        # to SHIP_TYPES.  We also suppress its SPY-1 radar (silent doctrine).
        super().__init__(
            ship_id=ship_id,
            anchor_xz=anchor_xz,
            heading_deg=heading_deg,
            patrol_radius_m=patrol_radius_m,
            sm2_ammo=0,       # carrier has no SAMs in Phase 5a
            ciws_ammo=0,
            tomahawk_ammo=0,
        )
        # Overwrite the ship-type-derived dimensions and HP with carrier spec.
        spec = SHIP_TYPES["carrier"]
        self.ship_type = "carrier"
        self.length = spec["length"]
        self.beam   = spec["beam"]
        self.height = spec["height"]
        self.speed  = spec["speed"]
        self.hp     = spec["hp"]

        # Silent radar — carrier does not emit in Phase 5a.
        self.radar.emitting = False

    # Carrier is not air-borne.
    is_air = False

    def update(self, dt: float) -> None:
        """Destroyer update plus CVN damage control: a carrier with hit
        points remaining CONTAINS a burn instead of sinking from it.

        The inherited ladder makes any single hit eventually terminal
        (BURNING -> SINKING when burn_timer runs out) — correct for the
        thin-hulled destroyers, but it would void the spec's "big HP pool,
        multiple Oniks hits" (§5.4): one leaker would doom the carrier.
        A CVN's damage-control parties put out a single-hit fire, so when
        the burn timer expires with hp > 0 the fire is declared contained
        and the ship resumes ALIVE.  Only hp exhaustion sinks her —
        sim/damage.py already flips straight to SINKING at hp <= 0, and a
        fresh hit restarts the fire with a full burn timer."""
        if self.state == ST_BURNING and self.hp > 0 and self.burn_timer <= dt:
            self.state = ST_ALIVE
            self.burn_timer = BURN_TIME
        super().update(dt)


# ---------------------------------------------------------------------------
# Fighter nose radar — forward-cone gating wrapper
# ---------------------------------------------------------------------------

class FighterRadar:
    """Wraps sim.radar.Radar with a ±FOV_HALF forward cone check.

    The underlying Radar handles horizon math and terrain LOS.  This wrapper
    adds an angular prefilter: if the target's bearing relative to the
    fighter's heading lies outside ±FIGHTER_RADAR_FOV_HALF the return is
    False without even querying the underlying radar.  This keeps the existing
    Radar API unchanged (no optional fields added).

    ``pos`` and ``antenna_m`` are delegated straight through so the underlying
    radar stays in sync via the fighter's own update logic.
    """

    def __init__(self, radar_id: str, pos: np.ndarray, antenna_m: float):
        self._radar = _radar_mod.Radar(
            radar_id=radar_id,
            pos=pos,
            antenna_m=antenna_m,
            ranges=dict(FIGHTER_RADAR_RANGES),
        )
        self._heading_ref: float = 0.0   # set by Fighter each update

    # --- passthrough attributes -----------------------------------------------

    @property
    def radar_id(self) -> str:
        return self._radar.radar_id

    @property
    def pos(self) -> np.ndarray:
        return self._radar.pos

    @pos.setter
    def pos(self, v) -> None:
        self._radar.pos = v

    @property
    def antenna_m(self) -> float:
        return self._radar.antenna_m

    @property
    def antenna_alt(self) -> float:
        """Antenna altitude ASL (Radar passthrough): pos[1] + antenna_m —
        the drone's ELINT receiver reads this for its horizon check
        (sim/recon.py), so passive sensing sees the true sensor height."""
        return self._radar.antenna_alt

    @property
    def alive(self) -> bool:
        return self._radar.alive

    @alive.setter
    def alive(self, v: bool) -> None:
        self._radar.alive = v

    @property
    def emitting(self) -> bool:
        return self._radar.emitting

    @emitting.setter
    def emitting(self, v: bool) -> None:
        self._radar.emitting = v

    @property
    def ranges(self) -> dict:
        return self._radar.ranges

    # --- cone-gated detection -------------------------------------------------

    def detects(self, target_pos, size_class: str) -> bool:
        """True only when target is within the ±60 deg forward cone AND the
        underlying Radar.detects() returns True."""
        if not (self._radar.alive and self._radar.emitting):
            return False
        # Angular gate in the XZ plane (heading 0 = +Z, clockwise from above).
        dx = float(target_pos[0]) - float(self._radar.pos[0])
        dz = float(target_pos[2]) - float(self._radar.pos[2])
        if dx == 0.0 and dz == 0.0:
            return False
        bearing = math.atan2(dx, dz)
        err = (bearing - self._heading_ref + math.pi) % (2.0 * math.pi) - math.pi
        if abs(err) > FIGHTER_RADAR_FOV_HALF:
            return False
        return self._radar.detects(target_pos, size_class)


# ---------------------------------------------------------------------------
# Fighter
# ---------------------------------------------------------------------------

class Fighter:
    """F/A-18E-class enemy fighter with a full PARKED … PARKED state machine.

    State transitions
    -----------------
    PARKED       : sitting at a base waiting for orders (fuel full, armed).
    TAKEOFF      : rolling out from the base position and climbing.
    TRANSIT      : flying a waypoint list toward a patrol anchor.
    ON_STATION   : flying a racetrack orbit at the patrol anchor.
    RTB          : heading back to nearest surviving base.
    LANDING      : final descent onto the base, slowing to stop.
    REARMING     : on the ground; rearm queue at the base ticks this down.
    WINCHESTER_EGRESS : both bases dead; fly to map edge then GONE.
    GONE         : removed from simulation.

    Fuel accounting
    ---------------
    ``_fuel_s`` counts airborne seconds.  At FIGHTER_ENDURANCE_S × (1 −
    FIGHTER_BINGO_FRAC) the fighter is forced to RTB regardless of state.

    Nose radar
    ----------
    FighterRadar wraps a Radar with a ±60 deg forward cone.  The antenna
    altitude tracks pos[1] (the aircraft's current altitude).
    """

    is_air: bool = True
    radar_size: str = "fighter"   # ContactBoard size-class

    def __init__(
        self,
        aircraft_id: str,
        base: AirBase,
        patrol_anchor_xz,
    ):
        self.aircraft_id = aircraft_id
        self._base = base           # starting base (may be re-selected on RTB)
        self._patrol_anchor_xz = np.asarray(patrol_anchor_xz, dtype=np.float64)

        self.state: int = FS_PARKED
        self.pos: np.ndarray = base.pos.copy()
        self.pos[1] = 0.0           # on the ground
        self.heading: float = 0.0
        self._speed: float = 0.0    # current airspeed m/s

        self._fuel_s: float = 0.0   # airborne seconds consumed
        self._bingo_s: float = FIGHTER_ENDURANCE_S * (1.0 - FIGHTER_BINGO_FRAC)

        # Waypoint list for TRANSIT; consumed in order.
        self._waypoints: list[np.ndarray] = []

        # Racetrack for ON_STATION (two corner pairs in XZ).
        self._orbit_wps: Optional[np.ndarray] = None   # shape (4, 2)
        self._orbit_wp: int = 0

        # Nose radar — pos shares the same array object as self.pos so the
        # sync in update() is just setting the Y component.
        self.radar = FighterRadar(
            radar_id=f"{aircraft_id}_radar",
            pos=self.pos.copy(),
            antenna_m=0.0,   # antenna IS the aircraft; pos[1] is the altitude
        )
        # alive flag for kill spiral (AC_FALLING analogue)
        self._alive: bool = True
        self._falling: bool = False
        self._fall_t: float = 0.0
        self.impact_pos: Optional[np.ndarray] = None
        self.hp: int = 1

    # -----------------------------------------------------------------------
    # Duck-type interface (ContactBoard / seeker)
    # -----------------------------------------------------------------------

    @property
    def alive(self) -> bool:
        """Targetable: in the air and not destroyed."""
        return (self._alive and
                self.state not in (FS_PARKED, FS_REARMING, FS_GONE))

    def velocity(self) -> np.ndarray:
        if not self._alive or self.state in (FS_PARKED, FS_REARMING, FS_GONE):
            return np.zeros(3, dtype=np.float64)
        sp = self._speed
        hx = math.sin(self.heading)
        hz = math.cos(self.heading)
        if self.state == FS_TAKEOFF:
            vy = FIGHTER_CLIMB_RATE_MPS
        elif self.state == FS_LANDING:
            vy = -FIGHTER_DESCENT_RATE_MPS
        else:
            vy = 0.0
        return np.array([hx * sp, vy, hz * sp], dtype=np.float64)

    @property
    def vel(self) -> np.ndarray:
        return self.velocity()

    @property
    def pitch(self) -> float:
        """Render attitude (Aircraft convention: + = nose up): level in
        controlled flight, ramping nose-down through the kill spiral —
        the same numbers the falling flight path integrates."""
        if self._falling:
            frac = min(1.0, self._fall_t / FALL_TRANSITION_S)
            return -FALL_PITCH_RAD * frac
        return 0.0

    @property
    def roll(self) -> float:
        """Render attitude (+ = right wing down); banks into the spiral."""
        if self._falling:
            frac = min(1.0, self._fall_t / FALL_TRANSITION_S)
            return FALL_BANK_RAD * frac
        return 0.0

    # -----------------------------------------------------------------------
    # Kill spiral (mirrors Aircraft.kill())
    # -----------------------------------------------------------------------

    def kill(self) -> None:
        """One hit kills a fighter (hp=1); triggers a falling spiral."""
        if not self._alive:
            return
        self.hp -= 1
        if self.hp <= 0:
            self._alive = False
            self._falling = True
            self._fall_t = 0.0

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _turn_toward(self, target_x: float, target_z: float, dt: float) -> None:
        """Rate-limited heading turn toward (target_x, target_z)."""
        dx = target_x - float(self.pos[0])
        dz = target_z - float(self.pos[2])
        if abs(dx) < 1.0 and abs(dz) < 1.0:
            return
        bearing = math.atan2(dx, dz)
        err = (bearing - self.heading + math.pi) % (2.0 * math.pi) - math.pi
        limit = FIGHTER_TURN_RATE * dt
        self.heading += min(max(err, -limit), limit)
        self.heading = (self.heading + math.pi) % (2.0 * math.pi) - math.pi

    def _move_horizontal(self, speed: float, dt: float) -> None:
        self.pos[0] += math.sin(self.heading) * speed * dt
        self.pos[2] += math.cos(self.heading) * speed * dt

    def _bingo(self) -> bool:
        """True when airborne fuel is at or below bingo threshold."""
        return self._fuel_s >= self._bingo_s

    def _set_transit_to(self, dest_xz: np.ndarray) -> None:
        """Set up a single-waypoint TRANSIT to the given XZ destination."""
        wp = np.array([float(dest_xz[0]), FIGHTER_ALT_M, float(dest_xz[1])],
                      dtype=np.float64)
        self._waypoints = [wp]

    def _build_orbit(self, anchor_xz: np.ndarray) -> None:
        """Build the ON_STATION racetrack around the patrol anchor."""
        self._orbit_wps = _build_racetrack(
            anchor_xz=anchor_xz,
            heading_deg=0.0,
            patrol_radius_m=FIGHTER_ORBIT_HALF_LEN_M,
        )
        self._orbit_wp = 0

    def _advance_orbit_wp(self) -> None:
        wx = float(self._orbit_wps[self._orbit_wp, 0])
        wz = float(self._orbit_wps[self._orbit_wp, 1])
        dx = wx - float(self.pos[0])
        dz = wz - float(self.pos[2])
        dist = math.hypot(dx, dz)
        behind = (dx * math.sin(self.heading)
                  + dz * math.cos(self.heading)) < 0.0
        turn_r = FIGHTER_CRUISE_MPS / FIGHTER_TURN_RATE
        if dist < turn_r or (behind and dist < 2.0 * turn_r):
            self._orbit_wp = (self._orbit_wp + 1) % 4

    # -----------------------------------------------------------------------
    # State handlers called from update()
    # -----------------------------------------------------------------------

    def _update_takeoff(self, dt: float) -> None:
        """Roll and climb from the base until FIGHTER_ALT_M is reached."""
        # Head toward the patrol anchor while climbing.
        ax, az = float(self._patrol_anchor_xz[0]), float(self._patrol_anchor_xz[1])
        self._turn_toward(ax, az, dt)
        # Accelerate from rest to climb speed while still near ground.
        if self._speed < FIGHTER_CLIMB_SPEED_MPS:
            self._speed = min(self._speed + 20.0 * dt, FIGHTER_CLIMB_SPEED_MPS)
        self._move_horizontal(self._speed, dt)
        self.pos[1] = min(self.pos[1] + FIGHTER_CLIMB_RATE_MPS * dt,
                          FIGHTER_ALT_M)
        if self.pos[1] >= FIGHTER_ALT_M - 1.0:
            self.pos[1] = FIGHTER_ALT_M
            self._speed = FIGHTER_CRUISE_MPS
            self._set_transit_to(self._patrol_anchor_xz)
            self.state = FS_TRANSIT

    def _update_transit(self, dt: float) -> None:
        """Fly waypoints; transition to ON_STATION on last waypoint reached."""
        if not self._waypoints:
            # No waypoints: build the orbit and go on station.
            self._build_orbit(self._patrol_anchor_xz)
            self.state = FS_ON_STATION
            return
        wp = self._waypoints[0]
        tx, tz = float(wp[0]), float(wp[2])
        self._turn_toward(tx, tz, dt)
        self._move_horizontal(FIGHTER_CRUISE_MPS, dt)
        # Waypoint reached when within one turn-radius.
        turn_r = FIGHTER_CRUISE_MPS / FIGHTER_TURN_RATE
        dx = tx - float(self.pos[0])
        dz = tz - float(self.pos[2])
        if math.hypot(dx, dz) < turn_r:
            self._waypoints.pop(0)

    def _update_on_station(self, dt: float) -> None:
        """Racetrack orbit at the patrol anchor."""
        self._advance_orbit_wp()
        wx = float(self._orbit_wps[self._orbit_wp, 0])
        wz = float(self._orbit_wps[self._orbit_wp, 1])
        self._turn_toward(wx, wz, dt)
        self._move_horizontal(FIGHTER_CRUISE_MPS, dt)

    def _rtb(self, bases: list[AirBase]) -> None:
        """Select nearest surviving base and set up RTB transit."""
        target = nearest_surviving_base(self.pos, bases)
        if target is None:
            # Both bases dead: egress to map edge.
            self.state = FS_WINCHESTER_EGRESS
            # Fly in current heading — the egress update will handle it.
            return
        self._base = target
        self.state = FS_RTB

    def _update_rtb(self, dt: float) -> None:
        """Fly toward the assigned recovery base."""
        bpos = self._base.pos
        tx, tz = float(bpos[0]), float(bpos[2])
        self._turn_toward(tx, tz, dt)
        self._move_horizontal(FIGHTER_CRUISE_MPS, dt)
        dx = tx - float(self.pos[0])
        dz = tz - float(self.pos[2])
        dist = math.hypot(dx, dz)
        # Within landing approach distance → start descent.
        if dist < 5_000.0:
            self.state = FS_LANDING

    def _update_landing(self, dt: float) -> None:
        """Descend and decelerate; enter REARMING when on the ground."""
        bpos = self._base.pos
        tx, tz = float(bpos[0]), float(bpos[2])
        self._turn_toward(tx, tz, dt)
        if self._speed > 50.0:
            self._speed = max(50.0, self._speed - 40.0 * dt)
        self._move_horizontal(self._speed, dt)
        self.pos[1] = max(0.0, self.pos[1] - FIGHTER_DESCENT_RATE_MPS * dt)
        if self.pos[1] <= 0.0:
            self.pos[1] = 0.0
            self._speed = 0.0
            self.pos[0] = float(bpos[0])
            self.pos[2] = float(bpos[2])
            self.state = FS_REARMING
            self._fuel_s = 0.0       # will be reset to full on rearm_complete
            self._base.request_rearm(self)

    def _update_winchester_egress(self, dt: float) -> None:
        """Fly to the map edge, then set GONE."""
        self._move_horizontal(FIGHTER_CRUISE_MPS, dt)
        dist_from_origin = math.hypot(float(self.pos[0]), float(self.pos[2]))
        if dist_from_origin >= MAP_EDGE_EGRESS_M:
            self.state = FS_GONE
            self._alive = False

    def _update_falling(self, dt: float) -> None:
        """Simple spiral descent: roll in, pitch down, impact (constants
        shared with the pitch/roll render properties above)."""
        from sim.physics import GRAVITY
        from world.generation import TERRAIN_MAX_HEIGHT, terrain_height_scalar
        self._fall_t += dt
        frac = min(1.0, self._fall_t / FALL_TRANSITION_S)
        roll = FALL_BANK_RAD * frac
        pitch = -FALL_PITCH_RAD * frac
        sp = FIGHTER_CRUISE_MPS * (1.0 - 0.4 * frac)
        omega = GRAVITY * math.tan(roll) / max(sp, 1.0)
        self.heading = (self.heading + omega * dt + math.pi) % (2.0 * math.pi) - math.pi
        hs = sp * math.cos(pitch)
        self.pos[0] += math.sin(self.heading) * hs * dt
        self.pos[2] += math.cos(self.heading) * hs * dt
        self.pos[1] += sp * math.sin(pitch) * dt
        if self.pos[1] > TERRAIN_MAX_HEIGHT:
            return
        surface = max(terrain_height_scalar(float(self.pos[0]),
                                             float(self.pos[2])), 0.0)
        if self.pos[1] <= surface:
            self.pos[1] = surface
            self.impact_pos = self.pos.copy()
            self._falling = False
            self.state = FS_GONE

    # -----------------------------------------------------------------------
    # Called by AirBase when rearm is complete
    # -----------------------------------------------------------------------

    def _rearm_complete(self) -> None:
        """Base calls this when the fighter's rearm slot completes."""
        self._fuel_s = 0.0              # fresh fuel
        self.state = FS_PARKED
        # Do NOT auto-launch here — the commander AI does that in Phase 5b.

    # -----------------------------------------------------------------------
    # Launch
    # -----------------------------------------------------------------------

    def launch(self, patrol_anchor_xz=None) -> None:
        """Transition from PARKED to TAKEOFF.  Optionally update the patrol anchor."""
        if self.state != FS_PARKED:
            return
        if patrol_anchor_xz is not None:
            self._patrol_anchor_xz = np.asarray(patrol_anchor_xz, dtype=np.float64)
        # Remove from base parked list (if there).
        if self in self._base.parked:
            self._base.parked.remove(self)
        self.state = FS_TAKEOFF
        self._speed = 0.0

    # -----------------------------------------------------------------------
    # Main update
    # -----------------------------------------------------------------------

    def update(self, dt: float, bases: Optional[list[AirBase]] = None) -> None:
        """Advance one sim step.  ``bases`` must be provided for RTB decisions."""
        if self.state == FS_GONE:
            return

        # Falling spiral (killed in flight).
        if self._falling:
            self._update_falling(dt)
            return

        # Fuel accounting: only while airborne.
        airborne = self.state not in (FS_PARKED, FS_REARMING, FS_GONE)
        if airborne:
            self._fuel_s += dt
            if self._bingo() and self.state not in (FS_RTB, FS_LANDING,
                                                     FS_WINCHESTER_EGRESS):
                if bases:
                    self._rtb(bases)
                return  # handle RTB next tick

        # State dispatch.
        if self.state == FS_PARKED:
            pass  # waiting for launch() call
        elif self.state == FS_TAKEOFF:
            self._update_takeoff(dt)
        elif self.state == FS_TRANSIT:
            self._update_transit(dt)
        elif self.state == FS_ON_STATION:
            self._update_on_station(dt)
        elif self.state == FS_RTB:
            # Check that the assigned base is still alive; re-select if not.
            if not self._base.alive and bases:
                self._rtb(bases)
            self._update_rtb(dt)
        elif self.state == FS_LANDING:
            self._update_landing(dt)
        elif self.state == FS_REARMING:
            pass   # AirBase.update() ticks the rearm queue
        elif self.state == FS_WINCHESTER_EGRESS:
            self._update_winchester_egress(dt)

        # Sync nose-radar position to the fighter's current pos.
        self.radar.pos[0] = self.pos[0]
        self.radar.pos[1] = self.pos[1]
        self.radar.pos[2] = self.pos[2]
        self.radar._heading_ref = self.heading


# ---------------------------------------------------------------------------
# Awacs
# ---------------------------------------------------------------------------

class Awacs:
    """E-2/E-3-class enemy AWACS orbiter (spec §5.3).

    Orbits a deep anchor on a racetrack at AWACS_ALT_M.  Unarmed; flees
    threats via flee(threat_pos) which turns tail and holds max speed while
    the THREATENED state is set.  The commander clears it in Phase 5b; the
    method and the state exist now.

    Radar
    -----
    A standard sim.radar.Radar (no cone restriction — 360-degree look-down).
    antenna_m = 0 because the aircraft IS the antenna; the radar.pos[1] is
    kept equal to the aircraft altitude so horizon math uses the correct
    sensor elevation.
    """

    is_air: bool = True
    radar_size: str = "fighter"   # How it looks on the enemy radar picture

    def __init__(
        self,
        aircraft_id: str,
        anchor_a_xz,
        anchor_b_xz,
    ):
        """
        Parameters
        ----------
        aircraft_id :
            Unique string identifier.
        anchor_a_xz, anchor_b_xz :
            Opposite corners of the orbit rectangle in the XZ plane (metres).
        """
        self.aircraft_id = aircraft_id
        self.pos = np.zeros(3, dtype=np.float64)

        ax, az = float(anchor_a_xz[0]), float(anchor_a_xz[1])
        bx, bz = float(anchor_b_xz[0]), float(anchor_b_xz[1])
        x0, x1 = min(ax, bx), max(ax, bx)
        z0, z1 = min(az, bz), max(az, bz)
        self._corners = ((x0, z0), (x0, z1), (x1, z1), (x1, z0))
        self._wp = 1

        self.pos[0] = x0
        self.pos[1] = AWACS_ALT_M
        self.pos[2] = z0
        wx, wz = self._corners[self._wp]
        self.heading: float = math.atan2(wx - x0, wz - z0)
        self._speed: float = AWACS_CRUISE_MPS

        self.turn_radius: float = AWACS_CRUISE_MPS / math.radians(1.5)

        self._alive: bool = True
        self.hp: int = 1
        self._falling: bool = False
        self._fall_t: float = 0.0
        self.impact_pos: Optional[np.ndarray] = None

        # Flee state
        self._fleeing: bool = False
        self._flee_heading: float = self.heading

        # Radar — 360 deg, mounted at aircraft altitude.
        self.radar = _radar_mod.Radar(
            radar_id=f"{aircraft_id}_radar",
            pos=self.pos.copy(),   # kept in sync each update
            antenna_m=AWACS_ANTENNA_OFFSET_M,
            ranges=dict(AWACS_RADAR_RANGES),
        )

    # -----------------------------------------------------------------------
    # Duck-type interface
    # -----------------------------------------------------------------------

    @property
    def alive(self) -> bool:
        return self._alive and not self._falling

    def velocity(self) -> np.ndarray:
        if not self._alive:
            return np.zeros(3, dtype=np.float64)
        sp = self._speed
        return np.array([math.sin(self.heading) * sp, 0.0,
                         math.cos(self.heading) * sp], dtype=np.float64)

    @property
    def vel(self) -> np.ndarray:
        return self.velocity()

    @property
    def pitch(self) -> float:
        """Render attitude (+ = nose up): level orbit, spiral nose-down."""
        if self._falling:
            frac = min(1.0, self._fall_t / FALL_TRANSITION_S)
            return -FALL_PITCH_RAD * frac
        return 0.0

    @property
    def roll(self) -> float:
        """Render attitude (+ = right wing down); banks into the spiral."""
        if self._falling:
            frac = min(1.0, self._fall_t / FALL_TRANSITION_S)
            return FALL_BANK_RAD * frac
        return 0.0

    # -----------------------------------------------------------------------
    # Kill (same spiral pattern as Aircraft)
    # -----------------------------------------------------------------------

    def kill(self) -> None:
        if not self._alive:
            return
        self.hp -= 1
        if self.hp <= 0:
            self._alive = False
            self._falling = True
            self._fall_t = 0.0

    # -----------------------------------------------------------------------
    # Flee
    # -----------------------------------------------------------------------

    def flee(self, threat_pos) -> None:
        """Turn tail to the threat and hold max speed (commander calls this)."""
        dx = float(self.pos[0]) - float(threat_pos[0])
        dz = float(self.pos[2]) - float(threat_pos[2])
        if abs(dx) < 1.0 and abs(dz) < 1.0:
            return
        # Heading AWAY from threat: bearing + 180.
        toward = math.atan2(dx, dz)   # already inverted (away)
        self._flee_heading = toward
        self._fleeing = True

    def stop_flee(self) -> None:
        """Commander cancels flee order (Phase 5b)."""
        self._fleeing = False

    # -----------------------------------------------------------------------
    # Racetrack (mirrors Aircraft._advance_waypoint)
    # -----------------------------------------------------------------------

    def _advance_waypoint(self) -> None:
        wx, wz = self._corners[self._wp]
        dx = wx - float(self.pos[0])
        dz = wz - float(self.pos[2])
        dist = math.hypot(dx, dz)
        behind = (dx * math.sin(self.heading)
                  + dz * math.cos(self.heading)) < 0.0
        if dist < self.turn_radius or (behind and dist < 2.0 * self.turn_radius):
            self._wp = (self._wp + 1) % 4

    # -----------------------------------------------------------------------
    # Falling spiral (same as Aircraft._update_falling)
    # -----------------------------------------------------------------------

    def _update_falling(self, dt: float) -> None:
        from sim.physics import GRAVITY
        from world.generation import TERRAIN_MAX_HEIGHT, terrain_height_scalar
        self._fall_t += dt
        frac = min(1.0, self._fall_t / FALL_TRANSITION_S)
        roll = FALL_BANK_RAD * frac
        pitch = -FALL_PITCH_RAD * frac
        sp = AWACS_CRUISE_MPS * (1.0 - 0.4 * frac)
        omega = GRAVITY * math.tan(roll) / max(sp, 1.0)
        self.heading = (self.heading + omega * dt + math.pi) % (2.0 * math.pi) - math.pi
        hs = sp * math.cos(pitch)
        self.pos[0] += math.sin(self.heading) * hs * dt
        self.pos[2] += math.cos(self.heading) * hs * dt
        self.pos[1] += sp * math.sin(pitch) * dt
        if self.pos[1] > TERRAIN_MAX_HEIGHT:
            return
        surface = max(terrain_height_scalar(float(self.pos[0]),
                                             float(self.pos[2])), 0.0)
        if self.pos[1] <= surface:
            self.pos[1] = surface
            self.impact_pos = self.pos.copy()
            self._falling = False

    # -----------------------------------------------------------------------
    # Main update
    # -----------------------------------------------------------------------

    def update(self, dt: float) -> None:
        if not self._alive and not self._falling:
            return

        if self._falling:
            self._update_falling(dt)
            self.radar.pos[:] = self.pos
            return

        if self._fleeing:
            # Rate-limited turn toward flee heading.
            err = (self._flee_heading - self.heading + math.pi) % (2.0 * math.pi) - math.pi
            limit = math.radians(1.5) * dt
            self.heading += min(max(err, -limit), limit)
            self.heading = (self.heading + math.pi) % (2.0 * math.pi) - math.pi
            self._speed = AWACS_FLEE_SPEED_MPS
        else:
            self._advance_waypoint()
            wx, wz = self._corners[self._wp]
            dx = wx - float(self.pos[0])
            dz = wz - float(self.pos[2])
            if abs(dx) > 0.1 or abs(dz) > 0.1:
                bearing = math.atan2(dx, dz)
                err = (bearing - self.heading + math.pi) % (2.0 * math.pi) - math.pi
                limit = math.radians(1.5) * dt
                self.heading += min(max(err, -limit), limit)
                self.heading = (self.heading + math.pi) % (2.0 * math.pi) - math.pi
            self._speed = AWACS_CRUISE_MPS

        self.pos[0] += math.sin(self.heading) * self._speed * dt
        self.pos[2] += math.cos(self.heading) * self._speed * dt
        # Altitude is fixed for the AWACS (no climb/descend modelled here).
        self.pos[1] = AWACS_ALT_M

        # Keep radar in sync.
        self.radar.pos[0] = self.pos[0]
        self.radar.pos[1] = self.pos[1]   # antenna at aircraft altitude
        self.radar.pos[2] = self.pos[2]
