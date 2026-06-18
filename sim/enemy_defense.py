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

COMBAT Phase 4 — the recon drone as an SM-2 target:

  * A destroyer that radar-DETECTS the player's stealth drone (its
    'stealth' range, ~30 km, with the same sustained-detection gating as
    inbound missiles) treats it as an SM-2 target.  The drone cruises at
    18 km — inside the SM-2 intercept band — and at most
    DRONE_SM2_MAX_INFLIGHT rounds fly against one drone at a time.
    Self-defense outranks the drone hunt: the missile channel is offered
    targets first each step (the shared 3 s fire-control reload then
    naturally delays the drone shot).
  * Stealth low-SNR tracking noise (user law: physics, never dice) —
    StealthTargetSam below: against a 'stealth'-class target the position
    the round guides on (midcourse fix AND terminal illumination) carries
    a second per-axis OU error whose sigma scales UP with the fraction of
    the detection range the target sits at.  At the ~30 km detection edge
    the return is at the noise floor and the track wanders; close in the
    SNR climbs and the track cleans up — long shots miss because the
    guidance chased a dirty point, exactly like the multipath mechanism
    against sea-skimmers.  The proximity fuse stays on truth.
"""

from __future__ import annotations

import math

import numpy as np

from sim.arsenal import SM2, SM6
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

# --- Phase 4: drone engagement -------------------------------------------------
DRONE_SM2_MAX_INFLIGHT = 2  # rounds in flight per drone (spec 4.3 brief:
#                             shoot-shoot-look vs one slow target — the full
#                             4-round raid cap stays reserved for missiles)
DRONE_ENGAGE_RANGE_M = 22_000.0  # m: NO drone shots beyond this ground range
SM6_MAX_INFLIGHT = 2             # long-range SM-6 rounds in flight per ship
#                             (5b ammo discipline, 5a verifier OPEN item).
#                             The Phase-4 measured kill-per-shot curve
#                             (tools/probe_drone_sm2.py seeded batches,
#                             locked by tests/test_phase4_e2e.py) reads
#                             0.93 at 10 km, 0.67 at 20 km, 0.27 at 28 km
#                             of the 30 km stealth detection range: past
#                             ~22 km the low-SNR track noise (sigma ~ R^3)
#                             makes a launch a near-coin-flip magazine
#                             drain against a target that is CLOSING
#                             anyway — fire control holds the shot until
#                             the geometry pays.  AWACS far cues made this
#                             waste real in 5a (a 40 km cue could trigger
#                             launches the seeker could never finish).

# SM-6 AREA air-defense band (Phase 8): the SM-6's design role is to reach out
# and kill HIGH inbound cruise missiles (hi-profile Oniks/Zircon) far beyond the
# SM-2 band, forcing the player low — the "go low to survive" loop (GAME_ANALYSIS
# §7). It engages a tracked missile only when the dead-reckoned altitude is above
# SM6_AREA_MIN_ALT_M (a sea-skimmer stays the SM-2/CIWS/multipath domain) and the
# ground range sits in [SM6_MIN_RANGE_M, SM6.max_range]. A high flyer is a clean
# track (no stealth multipath), so the round is a plain SamMissile like the SM-2
# anti-missile channel — no low-SNR noise scaling.
SM6_AREA_MIN_ALT_M = 1_500.0     # m: above the sea-skim band -> SM-6 area target
SM6_MIN_RANGE_M = 50_000.0       # m: SM-6 reaches OUT (50-240 km); the SM-2's
#                                  150 km layer backs it up closer in.

# Stealth low-SNR tracking noise (the multipath analog for tiny targets,
# user law: outcomes emerge from guidance physics, never kill rolls).
# Same OU process shape as sim/sam.py MULTIPATH_* — time-correlated so PN
# chases a coherently wandering point — but sigma scales with the SHIP ->
# target ground range as a fraction of the radar's stealth detection
# range, CUBED: thermal-noise-limited angle tracking has sigma_angle ~
# 1/sqrt(SNR) ~ R^2 (radar SNR ~ R^-4), and position error = angle error
# x range ~ R^3.  At the detection edge the track sits at the noise
# floor; halfway in the error has already dropped 8x.  Values MEASURED,
# not guessed (tools/probe_drone_sm2.py seeded batches, methodology of
# the Phase-3 probe_sm2_batch sweep — see docs/combat_build_log.md):
# sigma_max 60 m / tau 0.7 s vs the 160 m/s drone measured kill-per-shot
# 14/15 (0.93) at 10 km, 10/15 (0.67) at 20 km, 4/15 (0.27) at 28 km of
# the 30 km detect range — matching spec §4.3 "~35% at envelope edge,
# near-certain up close".  The sigma 40/80 sweep neighbours moved the
# edge cell to 7/15 and 3/15 with the close cell pinned ~0.93-1.0.
# Clean-guidance control kills at all three ranges (the misses ARE the
# noise).  Locked two-sided by tests/test_phase4_e2e.py.
STEALTH_SNR_SIGMA_MAX_M = 60.0   # m per-axis OU RMS at the detection edge
STEALTH_SNR_RANGE_EXP = 3.0      # sigma ~ (R / R_detect)^3 (see above)
STEALTH_SNR_TAU_S = 0.7          # s correlation (scintillation/track loop)


def _mark_hostile_round(sam) -> None:
    """Enemy-launched interceptor: flag it for every player-facing filter.

    ``is_hostile`` drives the tactical-map pick/draw and camera-cycle
    exclusions plus the structure sweep; the air-entity duck-type
    (``is_air`` / ``radar_size`` / ``aircraft_id``) lets the round ride
    the gated ContactBoard feed (world/combat.py _update_strike_contacts)
    so the player sees a fog-of-war CONTACT — never the truth-position
    diamond that enemy SM-2s leaked before (user-reported seam: clicking
    one selected it like a friendly round)."""
    sam.is_hostile = True
    sam.is_air = True
    sam.radar_size = "missile"
    sam.aircraft_id = f"hostile_sam_{id(sam):x}"
    sam.launch_warning = True    # Phase 8: enemy SM-2 seen the instant it fires


class StealthTargetSam(SamMissile):
    """SM-2 engaging a 'stealth'-class target (the recon drone).

    Adds the low-SNR tracking error on top of the inherited multipath
    process: a second, independent per-axis OU error whose sigma is
    STEALTH_SNR_SIGMA_MAX_M scaled by (illuminator->target ground range /
    detection range), clamped to 1.  Both error processes ride the same
    ``_mp_*`` components the guidance reads (midcourse estimate AND
    terminal lock — sim/sam.py _target_state / terminal block), so a long
    shot chases a wandering point through its whole flight while a
    close-in shot tracks nearly clean.  The fuse stays on truth: misses
    EMERGE from guiding on the dirty track (user law).

    Implementation note: the parent's OU state lives in ``_mp_x/y/z`` and
    integrates in place, so each step restores the saved multipath base,
    advances it via super(), then adds this class's own OU state on top —
    two independent processes, one summed guidance error.
    """

    def __init__(self, *args, detection_range_m: float, **kwargs):
        super().__init__(*args, **kwargs)
        self._detect_range = float(detection_range_m)
        self._mp_base = (0.0, 0.0, 0.0)   # parent multipath OU state
        self._sn = [0.0, 0.0, 0.0]        # stealth low-SNR OU state

    def _snr_fraction(self) -> float:
        """(range / detection range)^STEALTH_SNR_RANGE_EXP from the
        ILLUMINATOR (the launching ship's director — SNR lives in the
        illumination chain), clamped to 1.  A dead/None illuminator rates
        1.0: with no painter the track is pure noise floor (the lock-break
        check kills the shot anyway)."""
        src = (self.illuminator_pos_fn()
               if self.illuminator_pos_fn is not None else None)
        if src is None:
            return 1.0
        tp = self.target.pos
        rng_ground = math.hypot(float(tp[0]) - float(src[0]),
                                float(tp[2]) - float(src[2]))
        return min(rng_ground / self._detect_range, 1.0) \
            ** STEALTH_SNR_RANGE_EXP

    def _update_multipath(self, dt):
        # 1) the inherited multipath term on its own saved state (zero for
        #    a high-flying drone, live for any future low stealth target).
        self._mp_x, self._mp_y, self._mp_z = self._mp_base
        super()._update_multipath(dt)
        self._mp_base = (self._mp_x, self._mp_y, self._mp_z)
        # 2) the stealth low-SNR term: OU with range-scaled sigma.
        sigma = STEALTH_SNR_SIGMA_MAX_M * self._snr_fraction()
        k = dt / STEALTH_SNR_TAU_S
        q = sigma * math.sqrt(2.0 * dt / STEALTH_SNR_TAU_S)
        rng = self.rng
        sn = self._sn
        sn[0] += -sn[0] * k + q * rng.standard_normal()
        sn[1] += -sn[1] * k + q * rng.standard_normal()
        sn[2] += -sn[2] * k + q * rng.standard_normal()
        # Guidance reads the SUM of both processes.
        self._mp_x += sn[0]
        self._mp_y += sn[1]
        self._mp_z += sn[2]


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
    """One destroyer's fire control: track store + SM-2 channel + CIWS.

    ``cue_radars_fn`` (COMBAT Phase 5a, spec section 3 "enemy ships rely
    on their own radar or AWACS cueing"): an optional () -> [Radar]
    closure of EXTERNAL datalinked detectors (the AWACS) that contribute
    to track FORMATION only — see _detects below for the SARH seam.
    None (the default) preserves Phase-2/3/4 behavior exactly."""

    def __init__(self, ship, rng, cue_radars_fn=None):
        self.ship = ship
        self.rng = rng          # shared side rng: CIWS rolls + SM-2 noise seeds
        self._cue_radars_fn = cue_radars_fn
        self.ciws = Ciws(ship.ciws_ammo, rng)
        # id(missile) -> dict(missile, t_next, since, pos, vel, age):
        # the same cadence/sustain gating shape as ContactBoard._vis, plus
        # the last radar fix (pos/vel/age) the SM-2 dead-reckons against.
        self._tracks: dict[int, dict] = {}
        self._inflight: list[tuple] = []    # (SamMissile, target track key)
        # Phase 4: the drone hunt — aircraft_id -> the same track dict shape
        # (keyed by id string: a respawned drone reuses the id, the track
        # store re-binds to the new airframe each step).
        self._drone_tracks: dict[str, dict] = {}
        self._drone_inflight: list[tuple] = []  # (SamMissile, aircraft_id)
        self._sm6_inflight: list[tuple] = []    # (SamMissile, key) long-range

    # -------------------------------------------------------------- tracking

    def _detects(self, pos, size_class):
        """Track-formation detection: the ship's own SPY-1, OR any
        datalinked cueing radar (Phase 5a: the AWACS — spec section 3).

        The cue feeds DETECTION only.  A destroyer may launch an SM-2 on
        a track the AWACS holds before its own radar ever sees the
        target (the midcourse flies on this controller's dead-reckoned
        picture regardless of which sensor refreshed it), but the SARH
        terminal phase is untouched: sim/sam.py's lock-break check still
        runs from the LAUNCHING SHIP's illuminator (_illuminator below),
        so a round whose own ship never gains line of sight by terminal
        goes stupid exactly as before.  That is the real Aegis/CEC seam:
        remote cue, local illumination."""
        if self.ship.radar.detects(pos, size_class):
            return True
        if self._cue_radars_fn is None:
            return False
        return any(r.detects(pos, size_class)
                   for r in self._cue_radars_fn())

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
                if self._detects(m.pos, "missile"):
                    if st["since"] is None:
                        st["since"] = now
                    st["pos"] = m.pos.copy()    # fresh fire-control fix
                    st["vel"] = m.vel.copy()
                    st["age"] = 0.0
                else:
                    st["since"] = None          # sustain clock resets
        for key in [k for k in self._tracks if k not in live_keys]:
            del self._tracks[key]               # missile died / was pruned

    def _update_drone_tracks(self, drones, now, dt):
        """The drone hunt's track store: identical cadence + sustained-
        detection gating as the missile store above, but checked at the
        radar's 'stealth'-class range (the drone's own size class).  Keyed
        by aircraft_id; re-binds to the live airframe each pass so a
        respawned drone (same id, new object) tracks cleanly."""
        live = set()
        for d in drones:
            if not d.alive:
                continue
            did = d.aircraft_id
            live.add(did)
            st = self._drone_tracks.get(did)
            if st is None:
                st = self._drone_tracks[did] = dict(
                    drone=d, t_next=-1.0, since=None,
                    pos=None, vel=None, age=0.0)
            st["drone"] = d
            if st["pos"] is not None:
                st["age"] += dt
            if now >= st["t_next"]:
                st["t_next"] = now + VIS_CHECK_PERIOD
                if self._detects(d.pos, d.radar_size):
                    if st["since"] is None:
                        st["since"] = now
                    st["pos"] = d.pos.copy()    # fresh fire-control fix
                    st["vel"] = d.velocity().copy()
                    st["age"] = 0.0
                else:
                    st["since"] = None          # sustain clock resets
        for key in [k for k in self._drone_tracks if k not in live]:
            del self._drone_tracks[key]         # shot down / despawned

    def _tracked(self, st, now):
        # M5: a per-unit continuous-visibility delay before a fire-control
        # track forms.  Default = TRACK_FORM_S (getattr fallback keeps a plain
        # Destroyer on the LOCKED const).  The world RAISES this on the
        # surviving escorts when the flagship CEC hub dies (cohesion loss), so
        # the fleet reacts slower with the datalink down — a SENSOR-honest nerf.
        track_form_s = getattr(self.ship, "_track_form_s", TRACK_FORM_S)
        return st["since"] is not None and now - st["since"] >= track_form_s

    def _estimate(self, key, tracks=None):
        """() -> (pos, vel) dead-reckoning closure over this track, frozen
        at the last fix if the track drops (mirrors WorldState's
        _contact_estimate: plain-float tuples, no per-call temporaries).
        ``tracks`` selects the store (default: the missile store; the
        drone hunt passes its own)."""
        tracks = self._tracks if tracks is None else tracks
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
        # M5: a per-unit simultaneous-SM-2 cap (an AirDefenseShip sustains more
        # concurrent rounds than a general destroyer).  getattr fallback keeps
        # a plain Destroyer on the LOCKED SM2_MAX_INFLIGHT const (existing
        # enemy_defense tests unchanged).
        max_inflight = getattr(ship, "sm2_max_inflight", SM2_MAX_INFLIGHT)
        if (ship.sm2_ammo <= 0 or ship.sm2_reload_timer > 0.0
                or len(self._inflight) >= max_inflight):
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
        _mark_hostile_round(sam)
        world.missiles.append(sam)
        ship.sm2_ammo -= 1
        ship.sm2_reload_timer = ship.sm2_reload_s
        self._inflight.append((sam, best_key))

    def _try_sm2_drone_launch(self, world, now):
        """One SM-2 at a tracked drone when the channel is free (called
        AFTER the missile launch attempt: self-defense outranks the hunt —
        the shared fire-control reload then spaces the drone shot).  Caps
        at DRONE_SM2_MAX_INFLIGHT rounds per drone; the round is a
        StealthTargetSam so the low-SNR physics rides the guidance."""
        ship = self.ship
        if ship.sm2_ammo <= 0 or ship.sm2_reload_timer > 0.0:
            return
        sx, sz = float(ship.pos[0]), float(ship.pos[2])
        detect_range = ship.radar.ranges.get("stealth", 0.0)
        for did, st in self._drone_tracks.items():
            drone = st["drone"]
            if not self._tracked(st, now) or not drone.alive:
                continue
            if sum(1 for _, k in self._drone_inflight
                   if k == did) >= DRONE_SM2_MAX_INFLIGHT:
                continue
            # Envelope on the PICTURE (dead-reckoned estimate), like the
            # missile channel above.
            ex = float(st["pos"][0]) + float(st["vel"][0]) * st["age"]
            ey = float(st["pos"][1]) + float(st["vel"][1]) * st["age"]
            ez = float(st["pos"][2]) + float(st["vel"][2]) * st["age"]
            rng_ground = math.hypot(ex - sx, ez - sz)
            if not SM2_MIN_RANGE_M <= rng_ground <= DRONE_ENGAGE_RANGE_M:
                continue        # beyond 22 km: measured waste zone — hold
            if not SM2.min_intercept_alt <= ey <= SM2.max_intercept_alt:
                continue
            deck = ship.pos + np.array([0.0, VLS_DECK_M, 0.0])
            sam = StealthTargetSam(
                SM2, deck, drone,
                contact_estimate_fn=self._estimate(did, self._drone_tracks),
                rng=np.random.default_rng(int(self.rng.integers(2 ** 63))),
                illuminator_pos_fn=self._illuminator(),
                detection_range_m=detect_range)
            sam.launch_cinematic = False    # no 1x time lock (enemy launch)
            sam.launch_platform = ship      # damage.py: never self-OBB-hit
            _mark_hostile_round(sam)
            world.missiles.append(sam)
            ship.sm2_ammo -= 1
            ship.sm2_reload_timer = ship.sm2_reload_s
            self._drone_inflight.append((sam, did))
            return                          # one round per free channel

    def _try_sm6_launch(self, world, now):
        """SM-6 long-range channel (240 km).  Two roles, both decided purely on
        the sensor PICTURE (a formed track, never ground truth):

          1. AREA air defense (primary): reach out and kill HIGH inbound cruise
             missiles (hi-profile Oniks/Zircon) far beyond the SM-2 band — the
             round that forces the player low (GAME_ANALYSIS §7).  A high flyer
             is a clean track, so it is a plain SamMissile like the SM-2
             anti-missile channel (no stealth low-SNR noise).
          2. Anti-drone standoff: a drone a sensor still holds past the SM-2's
             22 km cap (rare — the drone is stealthy, seen <=40 km).
        """
        ship = self.ship
        if (ship.sm6_ammo <= 0 or ship.sm6_reload_timer > 0.0
                or len(self._sm6_inflight) >= SM6_MAX_INFLIGHT):
            return
        sx, sz = float(ship.pos[0]), float(ship.pos[2])

        # --- 1. AREA defense: the HIGH inbound flyers, farthest first ---
        best_key = None
        best_rank = None
        for key, st in self._tracks.items():
            if not self._tracked(st, now) or not st["missile"].alive:
                continue
            ex = float(st["pos"][0]) + float(st["vel"][0]) * st["age"]
            ey = float(st["pos"][1]) + float(st["vel"][1]) * st["age"]
            ez = float(st["pos"][2]) + float(st["vel"][2]) * st["age"]
            if ey < SM6_AREA_MIN_ALT_M:
                continue                # sea-skimmer: SM-2/CIWS/multipath domain
            rng_ground = math.hypot(ex - sx, ez - sz)
            if not SM6_MIN_RANGE_M <= rng_ground <= SM6.max_range:
                continue
            if not SM6.min_intercept_alt <= ey <= SM6.max_intercept_alt:
                continue
            assigned = sum(1 for _, k in self._sm6_inflight if k == key)
            # Reach out and kill early: prefer the farthest-out high threat.
            rank = (assigned, -rng_ground)
            if best_rank is None or rank < best_rank:
                best_key, best_rank = key, rank
        if best_key is not None:
            deck = ship.pos + np.array([0.0, VLS_DECK_M, 0.0])
            sam = SamMissile(
                SM6, deck, self._tracks[best_key]["missile"],
                contact_estimate_fn=self._estimate(best_key),
                rng=np.random.default_rng(int(self.rng.integers(2 ** 63))),
                illuminator_pos_fn=self._illuminator())
            sam.launch_cinematic = False
            sam.launch_platform = ship
            _mark_hostile_round(sam)
            world.missiles.append(sam)
            ship.sm6_ammo -= 1
            ship.sm6_reload_timer = ship.sm6_reload_s
            self._sm6_inflight.append((sam, best_key))
            return

        # --- 2. Anti-drone standoff (existing) ---
        detect_range = ship.radar.ranges.get("stealth", 0.0)
        for did, st in self._drone_tracks.items():
            drone = st["drone"]
            if not self._tracked(st, now) or not drone.alive:
                continue
            if sum(1 for _, k in self._sm6_inflight if k == did) \
                    >= SM6_MAX_INFLIGHT:
                continue
            ex = float(st["pos"][0]) + float(st["vel"][0]) * st["age"]
            ey = float(st["pos"][1]) + float(st["vel"][1]) * st["age"]
            ez = float(st["pos"][2]) + float(st["vel"][2]) * st["age"]
            rng_ground = math.hypot(ex - sx, ez - sz)
            # The SM-2 owns the close-in band; the SM-6 takes the standoff zone.
            if not DRONE_ENGAGE_RANGE_M <= rng_ground <= SM6.max_range:
                continue
            if not SM6.min_intercept_alt <= ey <= SM6.max_intercept_alt:
                continue
            deck = ship.pos + np.array([0.0, VLS_DECK_M, 0.0])
            sam = StealthTargetSam(
                SM6, deck, drone,
                contact_estimate_fn=self._estimate(did, self._drone_tracks),
                rng=np.random.default_rng(int(self.rng.integers(2 ** 63))),
                illuminator_pos_fn=self._illuminator(),
                detection_range_m=detect_range)
            sam.launch_cinematic = False
            sam.launch_platform = ship
            _mark_hostile_round(sam)
            world.missiles.append(sam)
            ship.sm6_ammo -= 1
            ship.sm6_reload_timer = ship.sm6_reload_s
            self._sm6_inflight.append((sam, did))
            return

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
        if not ship.alive:
            # A sunk ship's SPY-1 is off, and STAYS off.
            ship.radar.alive = False
            self._tracks.clear()
            self._inflight.clear()
            self._drone_tracks.clear()
            self._drone_inflight.clear()
            self._sm6_inflight.clear()
            return
        # Ship alive: leave radar.alive AS-IS. It is True in normal play, but a
        # player ARM (Kh-31P) fuse flips it False directly — that kill must
        # STICK (M2 GATE Finding 2). The previous unconditional
        # `radar.alive = ship.alive` resurrected an ARM-killed SPY-1 every tick
        # while the hull floated, so an ARM could only blink a radar, never kill
        # it. The only behavior change: a radar killed while the ship LIVES now
        # stays dead (the intended ARM effect). A sunk ship still kills its
        # radar via the branch above.
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
        # Phase 4: the drone hunt — AFTER the missile channel (self-defense
        # priority; a launch above set the reload timer, spacing this one).
        # Worlds without a drone (SANDBOX WorldState) duck out via getattr.
        drone = getattr(world, "drone", None)
        self._update_drone_tracks(
            [drone] if drone is not None else [], now, dt)
        self._drone_inflight = [(sam, key) for sam, key in
                                self._drone_inflight if sam.alive]
        self._try_sm2_drone_launch(world, now)
        # Phase 8: SM-6 long-range channel — engages the drone (and high air
        # tracks) past the SM-2's 22 km drone cap / 150 km envelope.
        self._sm6_inflight = [(sam, key) for sam, key in self._sm6_inflight
                              if sam.alive]
        self._try_sm6_launch(world, now)
        self._run_ciws(world, now, dt)


class EnemyDefenseController:
    """All destroyers' defenses, stepped after the base world step
    (world/combat.py CombatWorld.step).  ``cue_radars_fn`` fans the
    shared datalink cue (the AWACS) into every ship's fire control."""

    def __init__(self, destroyers, rng=None, cue_radars_fn=None):
        rng = np.random.default_rng(0) if rng is None else rng
        self.units = [ShipDefense(d, rng, cue_radars_fn=cue_radars_fn)
                      for d in destroyers]

    def step(self, world, dt):
        for unit in self.units:
            unit.step(world, dt)
