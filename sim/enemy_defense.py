"""Enemy ship self-defense controller (pure numpy, GL-free) — COMBAT Phase 2.

Per-destroyer fire control wiring SPY-1 detection (sim/enemy_ships.py) to
the SM-2 interceptor (sim/sam.py + sim/arsenal.py SM2) and the CIWS gun
(sim/ciws.py). The controller is the integration layer the Destroyer's
module docstring promised: the ship owns the sensors and the magazines,
this module owns the engagement decisions.

Doctrine per step (spec §5.2):

  * The SPY-1 must hold an inbound player cruise missile for TRACK_FORM_S
    of CONTINUOUS visibility before a fire-control track forms (the same
    sustained-detection gating as the player's ContactBoard — popping over
    the horizon is not instant death for the missile either). Visibility is
    re-checked on a VIS_CHECK_PERIOD cadence, not per substep: the terrain
    sight-line ray is the expensive part of Radar.detects.
  * SM-2 launch: against the highest-priority tracked missile inside the
    weapon envelope (ground range within [SM2_MIN_RANGE_M, max_range],
    estimate altitude within the intercept band — the 25 m floor reaches
    sea-skimmers; what keeps lo-lo king per spec §5.2 is the low-altitude
    multipath noise PHYSICS in sim/sam.py, not an engagement gate), gated
    on sm2_ammo, the 3 s fire-control reload (Destroyer.sm2_reload_timer)
    and at most SM2_MAX_INFLIGHT simultaneous rounds per destroyer.
    Priority: fewest SM-2s already assigned, then nearest — a raid gets
    spread shots, a lone leaker gets shoot-shoot-look up to the cap.
  * The SM-2 flies on the CONTACT picture: boost/midcourse aim at a
    dead-reckoned closure over this controller's track (mirrors
    world.world.WorldState._contact_estimate); only the terminal seeker
    sees truth — through the multipath error against low targets, and
    only while the SHIP's illuminator holds terrain line of sight (SARH:
    the lock-break check in sim/sam.py runs ship antenna -> target).
  * CIWS: the nearest tracked hostile missile inside its 2 km envelope is
    engaged every substep; kills set the missile dead with impact
    bookkeeping and the burst/kill events are forwarded into world.events.

Launched SM-2s join ``world.missiles`` (rendering/trails for free) with two
integration flags: ``launch_cinematic = False`` (an enemy launch 300 km away
must not force the player's time accel to 1x — world.world.
launch_realtime_lock honors it) and ``launch_platform = <destroyer>``
(sim/damage.py skips the pair so a deck launch can never OBB-hit its own
hull on the first substep).

Determinism: all CIWS randomness routes through the injected generator,
and every SM-2 launch draws ONE integer from it to seed a child Generator
for that round's multipath noise (sim/sam.py); given the same seed and
call sequence the battle replays exactly.
"""

from __future__ import annotations

import math

import numpy as np

from sim.arsenal import SM2
from sim.ciws import Ciws
from sim.missile import Missile
from sim.sam import SamMissile

VIS_CHECK_PERIOD = 0.25     # s between cached SPY-1 visibility re-checks
TRACK_FORM_S = 1.5          # s of continuous visibility before track forms
SM2_MAX_INFLIGHT = 4        # simultaneous SM-2s per destroyer (raid cap)
SM2_MIN_RANGE_M = 5_000.0   # inside this the SM-2 cannot arm/turn: CIWS work
VLS_DECK_M = 10.0           # m, Mk 41 deck above the waterline (launch pos)
CIWS_MOUNT_M = 12.0         # m, gun mount above the waterline (slant ranges)
ILLUMINATOR_M = 20.0        # m, SPY-1/director illuminator above the
#                             waterline (matches the SPY-1 antenna height in
#                             sim/enemy_ships.py): the SARH LOS source for
#                             the SM-2 terminal lock-break check


class _RelTarget:
    """Adapts a world missile into the CIWS's gun-centric frame: Ciws.engage
    measures slant range straight off ``target.pos``, so the adapter holds
    pos relative to the mount and forwards ``alive`` writes (the kill flag)
    back to the real missile."""

    __slots__ = ("_missile", "pos")

    def __init__(self, missile, gun_pos):
        self._missile = missile
        self.pos = missile.pos - gun_pos

    def velocity(self):
        # Mount motion (≤ ship speed) is negligible against a Mach-2 closer.
        return self._missile.vel

    @property
    def alive(self):
        return self._missile.alive

    @alive.setter
    def alive(self, value):
        self._missile.alive = value


class ShipDefense:
    """One destroyer's fire control: track store + SM-2 channel + CIWS."""

    def __init__(self, ship, rng):
        self.ship = ship
        self.rng = rng          # shared side rng: CIWS rolls + SM-2 noise seeds
        self.ciws = Ciws(ship.ciws_ammo, rng)
        # id(missile) -> dict(missile, t_next, since, pos, vel, age):
        # the same cadence/sustain gating shape as ContactBoard._vis, plus
        # the last radar fix (pos/vel/age) the SM-2 dead-reckons against.
        self._tracks: dict[int, dict] = {}
        self._inflight: list[tuple] = []    # (SamMissile, target track key)

    # -------------------------------------------------------------- tracking

    def _update_tracks(self, hostiles, now, dt):
        live_keys = set()
        for m in hostiles:
            key = id(m)
            live_keys.add(key)
            st = self._tracks.get(key)
            if st is None:
                st = self._tracks[key] = dict(
                    missile=m, t_next=-1.0, since=None,
                    pos=None, vel=None, age=0.0)
            if st["pos"] is not None:
                st["age"] += dt
            if now >= st["t_next"]:
                st["t_next"] = now + VIS_CHECK_PERIOD
                if self.ship.radar.detects(m.pos, "missile"):
                    if st["since"] is None:
                        st["since"] = now
                    st["pos"] = m.pos.copy()    # fresh fire-control fix
                    st["vel"] = m.vel.copy()
                    st["age"] = 0.0
                else:
                    st["since"] = None          # sustain clock resets
        for key in [k for k in self._tracks if k not in live_keys]:
            del self._tracks[key]               # missile died / was pruned

    def _tracked(self, st, now):
        return st["since"] is not None and now - st["since"] >= TRACK_FORM_S

    def _estimate(self, key):
        """() -> (pos, vel) dead-reckoning closure over this track, frozen
        at the last fix if the track drops (mirrors WorldState's
        _contact_estimate: plain-float tuples, no per-call temporaries)."""
        tracks = self._tracks
        st = tracks[key]
        px, py, pz = st["pos"].tolist()
        vx, vy, vz = st["vel"].tolist()
        age = st["age"]
        last = [(px + vx * age, py + vy * age, pz + vz * age),
                (vx, vy, vz)]

        def contact_estimate():
            trk = tracks.get(key)
            if trk is not None and trk["pos"] is not None:
                tx, ty, tz = trk["pos"].tolist()
                wx, wy, wz = trk["vel"].tolist()
                a = trk["age"]
                last[0] = (tx + wx * a, ty + wy * a, tz + wz * a)
                last[1] = (wx, wy, wz)
            return last[0], last[1]

        return contact_estimate

    def _illuminator(self):
        """() -> SARH illuminator position for the SM-2 terminal lock-break
        LOS check (sim/sam.py): the SPY-1 antenna of the LAUNCHING ship,
        tracked live. Returns None once the ship dies — a sinking ship
        stops illuminating and every round it was guiding goes stupid."""
        ship = self.ship

        def illuminator_pos():
            if not ship.alive:
                return None
            return (float(ship.pos[0]),
                    float(ship.pos[1]) + ILLUMINATOR_M,
                    float(ship.pos[2]))

        return illuminator_pos

    # ----------------------------------------------------------------- SM-2

    def _try_sm2_launch(self, world, now):
        ship = self.ship
        if (ship.sm2_ammo <= 0 or ship.sm2_reload_timer > 0.0
                or len(self._inflight) >= SM2_MAX_INFLIGHT):
            return
        sx, sz = float(ship.pos[0]), float(ship.pos[2])
        best_key = None
        best_rank = None
        for key, st in self._tracks.items():
            if not self._tracked(st, now) or not st["missile"].alive:
                continue
            # The shot is decided on the PICTURE: the dead-reckoned estimate
            # gates the envelope, exactly what the missile will aim at.
            ex = float(st["pos"][0]) + float(st["vel"][0]) * st["age"]
            ey = float(st["pos"][1]) + float(st["vel"][1]) * st["age"]
            ez = float(st["pos"][2]) + float(st["vel"][2]) * st["age"]
            rng_ground = math.hypot(ex - sx, ez - sz)
            if not SM2_MIN_RANGE_M <= rng_ground <= SM2.max_range:
                continue
            if not SM2.min_intercept_alt <= ey <= SM2.max_intercept_alt:
                continue                        # under the floor: CIWS only
            assigned = sum(1 for _, k in self._inflight if k == key)
            rank = (assigned, rng_ground)
            if best_rank is None or rank < best_rank:
                best_key, best_rank = key, rank
        if best_key is None:
            return
        deck = ship.pos + np.array([0.0, VLS_DECK_M, 0.0])
        sam = SamMissile(
            SM2, deck, self._tracks[best_key]["missile"],
            contact_estimate_fn=self._estimate(best_key),
            # One parent draw seeds a child Generator per launch: the
            # multipath noise stays seeded/deterministic per battle while
            # each round wanders independently (sim/sam.py MULTIPATH_*).
            rng=np.random.default_rng(int(self.rng.integers(2 ** 63))),
            illuminator_pos_fn=self._illuminator())
        sam.launch_cinematic = False    # no 1x time lock for enemy launches
        sam.launch_platform = ship      # damage.py: never self-OBB-hit
        world.missiles.append(sam)
        ship.sm2_ammo -= 1
        ship.sm2_reload_timer = ship.sm2_reload_s
        self._inflight.append((sam, best_key))

    # ----------------------------------------------------------------- CIWS

    def _run_ciws(self, world, now, dt):
        if not self.ciws.ready:
            return
        gun = self.ship.pos + np.array([0.0, CIWS_MOUNT_M, 0.0])
        best = None
        best_d = 2_000.0                # sim/ciws.py ENGAGE_RANGE
        for st in self._tracks.values():
            m = st["missile"]
            if not self._tracked(st, now) or not m.alive:
                continue
            d = math.sqrt(float((m.pos[0] - gun[0]) ** 2
                                + (m.pos[1] - gun[1]) ** 2
                                + (m.pos[2] - gun[2]) ** 2))
            if d < best_d:
                best, best_d = m, d
        if best is None:
            return
        events = self.ciws.engage(_RelTarget(best, gun), dt)
        self.ship.ciws_ammo = self.ciws.ammo    # keep the mirror honest
        for kind, rel_pos in events:
            world_pos = rel_pos + gun
            if kind == "ciws_kill":
                # Impact bookkeeping: the dead round is pruned silently by
                # the next world.step (it never re-enters the flying set),
                # so the kill point must be recorded here.
                best.impact_pos = world_pos.copy()
            world.events.append((kind, world_pos))

    # ----------------------------------------------------------------- step

    def step(self, world, dt):
        ship = self.ship
        ship.radar.alive = ship.alive   # a sinking ship's SPY-1 is off
        if not ship.alive:
            self._tracks.clear()
            self._inflight.clear()
            return
        now = world.sim_time
        # Hostiles = player cruise missiles. SamMissile is a separate type
        # (never a Missile subclass), so every interceptor — player S-300
        # and own SM-2s alike — is excluded by construction.
        hostiles = [m for m in world.missiles
                    if m.alive and isinstance(m, Missile)]
        self._update_tracks(hostiles, now, dt)
        self._inflight = [(sam, key) for sam, key in self._inflight
                          if sam.alive]
        self._try_sm2_launch(world, now)
        self._run_ciws(world, now, dt)


class EnemyDefenseController:
    """All destroyers' defenses, stepped after the base world step
    (world/combat.py CombatWorld.step)."""

    def __init__(self, destroyers, rng=None):
        rng = np.random.default_rng(0) if rng is None else rng
        self.units = [ShipDefense(d, rng) for d in destroyers]

    def step(self, world, dt):
        for unit in self.units:
            unit.step(world, dt)
