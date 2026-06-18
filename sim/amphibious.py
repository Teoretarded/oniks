"""Amphibious landing force for COMBAT mode (M5 #1): Transport hulls + LCAC
landing craft — the SECOND lose-path, orthogonal to "all TELs destroyed".

The loop (always counter-able):

    Transport (slow LHD-class hull, REAR spawn band) LOITERs on a racetrack
        | the enemy commander orders TRANSPORT_RUN from its SENSOR picture
        v
    RUN (beeline toward the player base)
        | reaches its LAUNCH LINE (an offshore range ring from the base)
        v
    SPLASH (spawns exactly LCAC_PER_TRANSPORT Lcac craft at the transport pos;
            the transport then DRIFTS dead-in-the-water — its mission is done)

    Lcac (fast, fragile hp=1 craft) beelines the LANDING_BOX near the base.
        | its pos enters the LANDING_BOX radius
        v
    a beachhead grace timer starts (world bookkeeping); if the player does not
    clear ALL committed craft before it expires the bastion is overrun.

PHYSICS NOT DICE: a transport / LCAC dies from the EXISTING OBB/fuse damage
sweep (sim/damage.apply_missile_hits) when an Oniks / Pantsir-gun round crosses
its hull — both are ordinary ``Ship`` entities in ``world.combat.ships`` (hp
1 for the LCAC -> one hit sinks it; the transport is tougher).  "Landing" is a
GEOMETRIC event (pos in the box), the grace countdown a deterministic clock.

FOG / NO EMITTERS: a Transport / Lcac carries NO radar mount (``radar = None``),
so it NEVER joins the world ELINT/_emitters path (mirrors the carrier running
dark — but the carrier still HAS a silent mount; these have none at all).  They
are found ONLY by the player RadarNetwork horizon + drone SAR (fog).  The LCAC
being "hard to catch close in" EMERGES from its small ``radar_size`` class
(``"lcac"``) shortening the player radar's detection ring (PLAYER_RADAR_RANGES)
vs a transport's full ``"ship"`` range — geometry, not a probability flag.

Pure numpy, GL-free.  Axes: X east, Y up, Z north.  All SI float64.
Determinism: the ONLY randomness is the LCAC splash scatter, drawn from the
injected child stream ([seed, 15]) the world owns — same seed -> same fan-out.
"""

from __future__ import annotations

import math

import numpy as np

from sim.enemy_ships import Destroyer
from sim.ships import (HULL_DRAFT, SHIP_TYPES, ST_ALIVE, ST_BURNING, ST_GONE,
                       ST_SINKING, Ship)

# ---------------------------------------------------------------------------
# Geometry / timing constants (research-grounded; the landing economy)
# ---------------------------------------------------------------------------
# The LANDING BOX: a coast lodgement just seaward of the player base.  An LCAC
# whose pos enters this radius has "landed" (the beachhead event).  Placed a
# short hop off BASE_POS toward the open sea (+Z is the threat axis), well
# inside the Pantsir/Buk bubble so a leaker is still killable on the beach.
LANDING_BOX_OFFSET_M = 6_000.0    # m seaward of the base (toward +Z threat axis)
LANDING_BOX_RADIUS_M = 2_500.0    # m: an LCAC inside this has landed

# The LAUNCH LINE: an offshore range ring from the base.  A Transport on its RUN
# splashes its LCACs the instant it crosses INTO this ring — far enough out that
# the player has a real window to sink the transports before they ever splash,
# close enough that the LCAC sprint is a finite dash (not a half-map crawl).
LAUNCH_LINE_RANGE_M = 45_000.0    # m from the base: transports splash here

# Speeds (m/s).  A transport is a slow LHD-class hull; the LCAC is a fast
# air-cushion craft (the "hard to catch close in" sprinter).
TRANSPORT_SPEED_MPS = 11.0        # ~21 kn LHD-class beeline
LCAC_SPEED_MPS      = 18.0        # ~35 kn air-cushion sprint to the beach

# How many LCACs each transport disgorges at the launch line.
LCAC_PER_TRANSPORT = 3

# The beachhead grace clock default (s): once the FIRST LCAC reaches the box the
# player has this long to clear EVERY committed craft (transports + LCACs) or
# the bastion is overrun.  A POSITIVE default is safe at n_transports=0 because
# the timer only ever STARTS when an LCAC reaches the box (impossible with no
# transports built) — the byte-identical gate is geometric, not numeric.
BEACHHEAD_GRACE_S = 180.0

# Transport racetrack loiter radius (m) while it waits for the RUN order — a
# modest box in the rear band (it is not a combatant, it just holds station).
TRANSPORT_PATROL_RADIUS_M = 6_000.0

# ---------------------------------------------------------------------------
# Transport nav/posture states
# ---------------------------------------------------------------------------
TRANSPORT_LOITER = 0    # racetrack station-keeping in the rear band
TRANSPORT_RUN    = 1    # beeline toward the base (commander released it)
TRANSPORT_SPLASH = 2    # reached the launch line: LCACs away, drift dead

TRANSPORT_STATE_LABELS = {
    TRANSPORT_LOITER: "LOITER",
    TRANSPORT_RUN:    "RUN",
    TRANSPORT_SPLASH: "SPLASH",
}

# ---------------------------------------------------------------------------
# SHIP_TYPES registration (dims/HP) — the transport hull
# ---------------------------------------------------------------------------
# A slow LHD/LST-class amphibious ship: large/long, modest HP (a soft-skinned
# auxiliary, not a warship — easier to sink than a Burke once you reach it).
# The renderer falls back to the existing destroyer/ship mesh until a dedicated
# hull lands (DEFERRED).
SHIP_TYPES["transport"] = dict(
    length=200.0, beam=32.0, height=28.0, speed=TRANSPORT_SPEED_MPS, hp=2)

# The LCAC: a tiny air-cushion craft.  hp=1 -> a single OBB/fuse hit sinks it.
SHIP_TYPES["lcac"] = dict(
    length=27.0, beam=14.0, height=4.0, speed=LCAC_SPEED_MPS, hp=1)


def _heading_toward(src_xz, dst_xz):
    """Compass heading (rad, 0 = +Z north, CW) from src to dst (XZ)."""
    dx = float(dst_xz[0]) - float(src_xz[0])
    dz = float(dst_xz[1]) - float(src_xz[1])
    return math.atan2(dx, dz)


class Transport(Destroyer):
    """Slow LHD-class amphibious transport — a ``Destroyer`` subclass so it
    inherits the racetrack loiter, the damage ladder (ALIVE/BURNING/SINKING/
    GONE) and the hull OBB unchanged.  Differences:

      * dims/HP/speed from SHIP_TYPES['transport'] (soft-skinned, slow);
      * NO radar mount (``radar = None``) — it emits NOTHING, so the world's
        ELINT/_emitters path never lists it (the fog contract);
      * light/zero self-defense (sm2/ciws/tomahawk all 0);
      * a LOITER -> RUN -> SPLASH posture: it holds station until the commander
        releases it, RUNs a beeline to its LAUNCH LINE, then SPLASHes its
        embarked LCACs and drifts dead-in-the-water.

    The world (world/combat._step_amphibious) drives the posture: it calls
    ``begin_run()`` on the commander's sensor-only release and reads
    ``reached_launch_line()`` to spawn the LCACs.  This class owns ONLY the
    kinematics + the embarked count — never any truth read.
    """

    # No SPY-1: a transport runs dark.  ``radar = None`` (set after super().
    # __init__ overwrites the Destroyer-built mount) is the emitter contract —
    # the world guards every self.ships radar walk with ``getattr(s,'radar')``.
    is_air = False

    def __init__(self, ship_id, anchor_xz, base_xz=(0.0, 0.0),
                 heading_deg=0.0, embarked_lcac=LCAC_PER_TRANSPORT):
        # Build as a Destroyer with ZERO offensive/defensive magazines, then
        # overwrite the hull from SHIP_TYPES['transport'].
        super().__init__(ship_id, anchor_xz, heading_deg=heading_deg,
                         patrol_radius_m=TRANSPORT_PATROL_RADIUS_M,
                         sm2_ammo=0, ciws_ammo=0, tomahawk_ammo=0)
        self.sm6_ammo = 0
        spec = SHIP_TYPES["transport"]
        self.ship_type = "transport"
        self.length = spec["length"]
        self.beam = spec["beam"]
        self.height = spec["height"]
        self.speed = spec["speed"]
        self.hp = spec["hp"]
        # Recompute the OBB bounding-sphere reach for the NEW dims with the SAME
        # formula Ship.__init__ uses (damage.py's pair prefilter relies on it).
        self.hit_reach = (0.5 * math.sqrt(
            self.beam ** 2 + (self.height + HULL_DRAFT) ** 2 + self.length ** 2)
            + 0.5 * (self.height - HULL_DRAFT))
        # The emitter contract: a transport carries NO radar mount.  The
        # Destroyer ctor built one (self.radar); drop it to None so the world's
        # guarded self.ships radar walks (ELINT/_emitters/RWR) skip it and it is
        # NEVER heard — found by radar/SAR geometry only.
        self.radar = None

        self._base_xz = (float(base_xz[0]), float(base_xz[1]))
        self.embarked_lcac = int(embarked_lcac)
        self.transport_state = TRANSPORT_LOITER
        self._splashed = False
        # The launch line where it will splash (a range ring from the base).
        self.launch_line_range_m = LAUNCH_LINE_RANGE_M

    @property
    def state_label(self) -> str:
        return TRANSPORT_STATE_LABELS.get(self.transport_state, "---")

    @property
    def radar_size(self) -> str:
        """Full ``"ship"`` size class — a transport is a large surface contact
        the player radar net detects at its full surface range (vs the LCAC's
        shorter ``"lcac"`` ring).  Explicit so the contact gate is unambiguous
        (ships default to ``"ship"`` via getattr, but we state it for clarity)."""
        return "ship"

    def _range_to_base(self) -> float:
        return math.hypot(self.pos[0] - self._base_xz[0],
                          self.pos[2] - self._base_xz[1])

    def begin_run(self) -> None:
        """Release the transport from LOITER into its beeline RUN (called by the
        world on the commander's sensor-only TRANSPORT_RUN order).  Idempotent:
        a transport already running / splashed is unaffected."""
        if self.transport_state == TRANSPORT_LOITER:
            self.transport_state = TRANSPORT_RUN

    def reached_launch_line(self) -> bool:
        """True once a RUNning transport has crossed INTO its launch-line ring
        (range-to-base <= launch_line_range_m) and has not yet splashed."""
        return (self.transport_state == TRANSPORT_RUN
                and not self._splashed
                and self._range_to_base() <= self.launch_line_range_m)

    def mark_splashed(self) -> None:
        """The world has spawned this transport's LCACs — latch SPLASH so it
        never splashes twice and drifts dead-in-the-water from here on."""
        self._splashed = True
        self.embarked_lcac = 0
        self.transport_state = TRANSPORT_SPLASH

    # -- navigation override -------------------------------------------------

    def update(self, dt):
        """LOITER reuses the Destroyer racetrack; RUN beelines the base; SPLASH
        drifts (no propulsion).  The damage ladder is reproduced from
        Destroyer.update so BURNING/SINKING/GONE behave identically; there is no
        radar to sync (the transport runs dark)."""
        if self.transport_state == TRANSPORT_LOITER:
            # Pure Destroyer racetrack loiter.  Destroyer.update() syncs
            # self.radar at the end — but ours is None, so call the GRANDPARENT
            # path by replicating Destroyer.update WITHOUT the radar sync.
            self._update_loiter(dt)
            return
        # RUN / SPLASH: damage ladder first (verbatim from Ship.update), then a
        # straight beeline (RUN) or a dead drift (SPLASH).
        if self.state == ST_GONE:
            return
        if self.state == ST_SINKING:
            from sim.ships import LIST_MAX, LIST_RAMP_TIME, SINK_GONE_TIME, \
                SINK_RATE
            self.sink_elapsed += dt
            self.list_angle = LIST_MAX * min(
                1.0, self.sink_elapsed / LIST_RAMP_TIME)
            self.pos[1] -= SINK_RATE * dt
            if self.sink_elapsed >= SINK_GONE_TIME:
                self.state = ST_GONE
            return
        from sim.ships import BURN_SPEED_FRAC, BURN_TIME
        if self.state == ST_BURNING:
            self.burn_timer -= dt
            if self.burn_timer <= 0.0:
                self.state = ST_SINKING
                return
        if self.transport_state == TRANSPORT_SPLASH:
            return                      # dead in the water: no propulsion
        # RUN: beeline straight at the base (no rudder limit — a committed dash).
        speed = self.speed * (
            BURN_SPEED_FRAC if self.state == ST_BURNING else 1.0)
        self.heading = _heading_toward(
            (self.pos[0], self.pos[2]), self._base_xz)
        self.pos[0] += math.sin(self.heading) * speed * dt
        self.pos[2] += math.cos(self.heading) * speed * dt

    def _update_loiter(self, dt):
        """Destroyer racetrack navigation WITHOUT the radar sync (we have no
        radar).  Transcribed from Destroyer.update minus the final radar lines."""
        from sim.ships import (BURN_SPEED_FRAC, LIST_MAX, LIST_RAMP_TIME,
                               SINK_GONE_TIME, SINK_RATE, TURN_RATE)
        if self.state == ST_GONE:
            return
        if self.state == ST_SINKING:
            self.sink_elapsed += dt
            self.list_angle = LIST_MAX * min(
                1.0, self.sink_elapsed / LIST_RAMP_TIME)
            self.pos[1] -= SINK_RATE * dt
            if self.sink_elapsed >= SINK_GONE_TIME:
                self.state = ST_GONE
            return
        if self.state == ST_BURNING:
            self.burn_timer -= dt
            if self.burn_timer <= 0.0:
                self.state = ST_SINKING
                return
        if self.state in (ST_ALIVE, ST_BURNING):
            speed = self.speed * (
                BURN_SPEED_FRAC if self.state == ST_BURNING else 1.0)
            px = float(self.pos[0])
            pz = float(self.pos[2])
            self._advance_racetrack(px, pz)
            wx = float(self._rt_wps[self._rt_wp, 0])
            wz = float(self._rt_wps[self._rt_wp, 1])
            bearing = math.atan2(wx - px, wz - pz)
            err = (bearing - self.heading + math.pi) % (2.0 * math.pi) - math.pi
            limit = TURN_RATE * dt
            self.heading += min(max(err, -limit), limit)
            self.heading = (self.heading + math.pi) % (2.0 * math.pi) - math.pi
            self.pos[0] = px + math.sin(self.heading) * speed * dt
            self.pos[2] = pz + math.cos(self.heading) * speed * dt


class Lcac(Ship):
    """LCAC air-cushion landing craft — a minimal ``Ship`` subclass (hp=1) that
    beelines the LANDING_BOX.  Spawned by a Transport at its launch line.

      * hp=1 -> a SINGLE OBB/fuse hit from the existing damage sweep sinks it
        (physics, no kill roll);
      * NO radar (``radar = None``) -> emits nothing, never in ELINT/_emitters;
      * ``radar_size = "lcac"`` -> the player radar's SHORTER 'lcac' detection
        ring (PLAYER_RADAR_RANGES) is what makes it "hard to catch close in"
        (geometry, measured in the probe);
      * carries no weapons — it is a pure delivery craft.

    A ``Ship`` already gives us the damage ladder + OBB + contact-board duck
    typing for free; we override only the navigation (a straight box beeline).
    """

    is_air = False
    radar = None                 # no mount: never an emitter (fog contract)
    radar_size = "lcac"          # shorter player-radar ring than a 'ship'

    def __init__(self, lcac_id, spawn_xz, box_xz):
        # Build the Ship on a trivial one-segment stub lane at the spawn point
        # aimed at the box; we replace lane-following with a box beeline below.
        sx, sz = float(spawn_xz[0]), float(spawn_xz[1])
        bx, bz = float(box_xz[0]), float(box_xz[1])
        heading = _heading_toward((sx, sz), (bx, bz))
        stub_lane = [
            (sx, sz),
            (sx + math.sin(heading) * 100.0, sz + math.cos(heading) * 100.0),
        ]
        super().__init__(lcac_id, "lcac", stub_lane, lane_t0=0.0)
        self.pos = np.array([sx, 0.0, sz], dtype=np.float64)
        self.heading = heading
        self._box_xz = (bx, bz)
        self.landed = False

    @property
    def ship_id_str(self) -> str:
        return self.ship_id

    def range_to_box(self) -> float:
        return math.hypot(self.pos[0] - self._box_xz[0],
                          self.pos[2] - self._box_xz[1])

    def update(self, dt):
        """Damage ladder (from Ship.update) then a straight beeline at the box;
        no radar to sync.  A landed / sunk craft stops driving."""
        from sim.ships import (BURN_SPEED_FRAC, LIST_MAX, LIST_RAMP_TIME,
                               SINK_GONE_TIME, SINK_RATE)
        if self.state == ST_GONE:
            return
        if self.state == ST_SINKING:
            self.sink_elapsed += dt
            self.list_angle = LIST_MAX * min(
                1.0, self.sink_elapsed / LIST_RAMP_TIME)
            self.pos[1] -= SINK_RATE * dt
            if self.sink_elapsed >= SINK_GONE_TIME:
                self.state = ST_GONE
            return
        if self.state == ST_BURNING:
            self.burn_timer -= dt
            if self.burn_timer <= 0.0:
                self.state = ST_SINKING
                return
        if self.state not in (ST_ALIVE, ST_BURNING):
            return
        # Geometric landing latch: once inside the box it has landed and holds.
        if self.range_to_box() <= LANDING_BOX_RADIUS_M:
            self.landed = True
            return
        speed = self.speed * (
            BURN_SPEED_FRAC if self.state == ST_BURNING else 1.0)
        self.heading = _heading_toward(
            (self.pos[0], self.pos[2]), self._box_xz)
        self.pos[0] += math.sin(self.heading) * speed * dt
        self.pos[2] += math.cos(self.heading) * speed * dt


def landing_box_xz(base_xz) -> tuple:
    """The LANDING_BOX centre (XZ): a short hop seaward of the base toward the
    +Z threat axis.  Deterministic from BASE_POS."""
    return (float(base_xz[0]), float(base_xz[1]) + LANDING_BOX_OFFSET_M)
