"""Pantsir-S1 point-defense unit: 57E6 SAM channel + 30 mm gun channel.
(Pure numpy, GL-free — the rendering layer reads this module; it NEVER imports
anything GL.)

Spec §4.2 (Pantsir-S1):
  * Own radar ~30 km counts toward the player radar network.
  * 12× 57E6 missiles, ~20 km range, Mach 2.7 class, very high agility (40 g),
    small fuse (8 m), min intercept alt 5 m (sea-skimmers + pop-up HARMs).
  * Auto-engages inbound hostile missiles tracked by its own radar; no player
    micromanagement.
  * 2× 30 mm guns, ~4 km last-ditch (same Ciws probabilistic burst model as
    sim/ciws.py with 30 mm numbers; spec §4.2: last-ditch gun system).
  * Ammo/reload armory-configurable.

Module structure
----------------
``Pantsir``
    One stationary Pantsir-S1 unit: owns a sim.radar.Radar (joins the player
    network), a missile magazine, a gun (sim.ciws.Ciws with 30 mm numbers),
    a fire-control reload timer and a kill() / alive flag.

``PantsirDefenseController``
    Player-side mirror of EnemyDefenseController (sim/enemy_defense.py).
    Given a list of Pantsir units and the world, each step():
      - Runs each live unit's radar detection against INBOUND HOSTILE missiles
        (world.missiles where is_hostile and is_air and alive and
        radar_size == 'missile').
      - Maintains a sustained-detection track store (~0.8 s — fast point-defense
        reaction; significantly shorter than the destroyer's 1.5 s because the
        Pantsir engages INBOUND SHORT-RANGE threats and needs to react inside
        20 km at Mach 2 cruise closure).
      - Prioritises by least time-to-impact on the nearest protected structure.
      - Launches 57E6 SamMissiles within 20 km when ammo and reload allow, capped
        at PANTSIR_MAX_INFLIGHT simultaneous rounds per unit.
      - Runs the 30 mm gun (Ciws) against the nearest tracked target inside
        GUN_RANGE_M.
      - Forwards events ('pantsir_launch', pos) / ('pantsir_gun', pos) /
        ('pantsir_kill', pos) into world.events.
      - A dead Pantsir (alive=False) skips all engagement logic.

Player-side vs hostile classification
---------------------------------------
Every 57E6 launched here is IS_HOSTILE=False by default (SamMissile has no
is_hostile class attribute; getattr returns False — the same falsy default as
the player's S-300). The structure sweep in sim/bases.py filters
``m.is_hostile`` before testing OBBs, so a 57E6 in flight can never demolish
a player structure even if its terminal phase passes through the base geometry.
This is confirmed and noted here explicitly (spec integration check).

Determinism
-----------
All CIWS randomness is routed through the numpy.random.Generator injected at
construction. Every 57E6 launch draws one integer from it to seed a child
Generator for that round's multipath noise (same pattern as ShipDefense in
sim/enemy_defense.py). Given the same seed and call sequence the battle
replays exactly.
"""

from __future__ import annotations

import math

import numpy as np

from sim.arsenal import PANTSIR_57E6
from sim.ciws import Ciws
from sim.radar import Radar
from sim.sam import SamMissile

# --- Engagement constants (spec §4.2 + derivation) ----------------------------

# Sustained-detection gating: how long the unit must continuously see a target
# before a fire-control track forms.  0.8 s is shorter than the destroyer's
# 1.5 s because the Pantsir is a POINT-DEFENSE system reacting to threats
# already well inside 20 km — a longer gate would waste the short intercept
# window against a Mach 2 cruise missile (closing ~680 m/s: 0.7 s extra delay
# = ~480 m of closure, materially shrinking the available intercept range).
TRACK_FORM_S: float = 0.8       # s continuous visibility before track forms

# Visibility re-check cadence (shared with ShipDefense 0.25 s pattern; the
# terrain LOS check is the expensive call — we amortise it over multiple steps
# rather than paying per substep at 120 Hz).
VIS_CHECK_PERIOD: float = 0.25  # s between cached radar visibility re-checks

# In-flight cap: max simultaneous 57E6 rounds per Pantsir unit.  The real
# system has 12 tubes in 2 × 6 banks; 3 simultaneous engagements is a
# conservative doctrine cap leaving reserve ammo for the next salvo.
PANTSIR_MAX_INFLIGHT: int = 3

# Minimum intercept range for the 57E6 missile channel (inside this the gun
# is the only defence because the SAM cannot arm/turn in time — same pattern
# as SM2_MIN_RANGE_M in sim/enemy_defense.py).
SAM_MIN_RANGE_M: float = 1_000.0    # m

# Fire-control reload between SAM launches (spec §4.2 "armory-configurable";
# default 1.5 s — time for the fire-control radar to re-solve a new fire-
# control solution after a launch).
MISSILE_RELOAD_S: float = 1.5       # s

# Gun (30 mm) engagement range (spec §4.2 "~4 km last-ditch").
GUN_RANGE_M: float = 4_000.0        # m

# Gun mount height above the vehicle chassis (the Pantsir turret sits at
# approximately 4 m above ground level when deployed; the gun barrels are
# at the turret top).
GUN_MOUNT_M: float = 4.0            # m

# 30 mm gun probabilistic burst model (Ciws with Pantsir 30 mm numbers):
# The Pantsir mounts 2 × 2A38M twin-barrel autocannons, combined rate ~2500
# rd/min = ~42 rd/s effective (accounting for dual-feed pauses). Spec §4.2:
# "last-ditch" role. Burst fire and kill-probability ramp mirrors ciws.py but
# with different range / rate numbers appropriate to the 30 mm.
#   ROUNDS_PER_SECOND: 40 rd/s effective (real 2A38M ~1250 rd/min per barrel,
#     2 barrels interleaved; burst bursts allow cooling at ~40 rd/s sustained).
#   Pk ramp: same shape as ciws.py but shorter range (4 km max, 1 km near).
#     P_FAR = 0.15 at 4 km (long shot into a Mach 2 target — very marginal).
#     P_NEAR = 0.55 at 1 km (close-in saturating the target airspace).
# These values are stored in a sub-class of Ciws that overrides the module
# constants — we pass them as constructor arguments using the same ROUNDS_PER_
# SECOND from the Ciws module scaled appropriately.
GUN_ROUNDS_PER_SECOND: float = 40.0   # rd/s effective rate
GUN_DEFAULT_AMMO: int = 700            # rounds total (spec §4.2; configurable)

# Pantsir radar spec (spec §4.2):
#   "own radar ~30 km counts toward the player network"
#   The Pantsir's PESA radar covers all target classes at ~30 km.
#   Stealth class is downgraded to ~12 km (same approach as the destroyer SPY-1
#   stealth range in sim/enemy_ships.py — a small, cold target has a lower RCS
#   cross-section and the downrange SNR is reduced at stealth detection ranges).
PANTSIR_RADAR_RANGES: dict = {
    "missile":  30_000.0,   # m — spec §4.2 "~30 km"
    "fighter":  30_000.0,   # m — all air threats at the same horizon-limited range
    "stealth":  12_000.0,   # m — reduced SNR for low-observable targets
    "ship":     30_000.0,   # m — surface search (same aperture)
}
PANTSIR_ANTENNA_M: float = 5.0  # m above the vehicle chassis (radar mast height)


# ---------------------------------------------------------------------------
# Pantsir unit
# ---------------------------------------------------------------------------

class Pantsir:
    """One Pantsir-S1 unit: stationary point-defense node.

    Parameters
    ----------
    unit_id:
        String identifier, e.g. "pantsir_00".
    pos:
        Deployment position in world space — float64 (3,) with Y = terrain
        height at the site.  The radar antenna projects PANTSIR_ANTENNA_M
        above this.
    missile_ammo:
        57E6 round count at construction (spec §4.2: default 12).
    gun_ammo:
        30 mm round count (spec §4.2: default 700).
    rng:
        numpy.random.Generator for the CIWS burst rolls and 57E6 multipath
        noise seeds.  If None a default_rng(0) is used (tests that need
        determinism inject an explicit seeded generator).
    radar_network:
        The player RadarNetwork (sim.radar.RadarNetwork); the Pantsir's radar
        is appended to it on construction so coverage is immediate.
    """

    def __init__(
        self,
        unit_id: str,
        pos,
        missile_ammo: int = 12,
        gun_ammo: int = GUN_DEFAULT_AMMO,
        rng: np.random.Generator | None = None,
        radar_network=None,
    ):
        self.unit_id = unit_id
        self.pos = np.asarray(pos, dtype=np.float64).copy()
        self.alive = True

        # --- Radar (joins the player network) ----------------------------------
        self.radar = Radar(
            radar_id=f"{unit_id}_pantsir",
            pos=self.pos,
            antenna_m=PANTSIR_ANTENNA_M,
            ranges=PANTSIR_RADAR_RANGES,
        )
        if radar_network is not None:
            radar_network.radars.append(self.radar)

        # --- Magazine ---------------------------------------------------------
        self.missile_ammo: int = int(missile_ammo)
        # Magazine-refill mechanic (armed by CombatWorld via arm_magazine).
        # Default 0.0 reload duration means the mechanic is inactive; when
        # arm_magazine is called the refill kicks in once the count hits 0.
        self._mag_cap: int = int(missile_ammo)   # full magazine size
        self._mag_reload_s: float = 0.0           # duration of one refill cycle
        self._mag_reload_left: float = 0.0        # s until next refill completes

        # --- Fire-control reload ----------------------------------------------
        self._reload_timer: float = 0.0   # counts DOWN; > 0 means reloading

        # --- Gun (30 mm — Ciws model with Pantsir numbers) --------------------
        # We subclass Ciws at the call site by passing the Pantsir-specific
        # parameters.  The Ciws class reads module-level constants (ENGAGE_RANGE,
        # ROUNDS_PER_SECOND, etc.) so we use _Pantsir30mmGun below.
        if rng is None:
            rng = np.random.default_rng(0)
        self._rng = rng
        self.gun: _Pantsir30mmGun = _Pantsir30mmGun(gun_ammo, rng)

    @property
    def gun_ammo(self) -> int:
        return self.gun.ammo

    def arm_magazine(self, mag_reload_s: float) -> None:
        """Activate the magazine-refill mechanic for this unit.

        Called by CombatWorld after construction (see world/combat.py
        _arm_magazines section).  Once the missile_ammo count hits 0 a
        timer of ``mag_reload_s`` seconds starts; on expiry the magazine
        is refilled to the construction count (``_mag_cap``).

        Parameters
        ----------
        mag_reload_s:
            Seconds to reload the full missile magazine (config-driven;
            spec §4.2 "armory-configurable").
        """
        self._mag_reload_s = float(mag_reload_s)

    def kill(self) -> None:
        """Destroy this unit (called by the damage system when HP reaches 0).
        The radar goes dark immediately; any in-flight 57E6s continue on their
        own guidance until their own self-destruct triggers."""
        self.alive = False
        self.radar.alive = False


# ---------------------------------------------------------------------------
# 30 mm gun — Ciws subclass with Pantsir-specific engagement parameters
# ---------------------------------------------------------------------------

class _Pantsir30mmGun(Ciws):
    """2× 2A38M autocannon on the Pantsir turret.

    Overrides the module-level Ciws engagement constants with the Pantsir
    30 mm numbers:
      ENGAGE_RANGE  = 4 000 m  (spec §4.2 "~4 km last-ditch")
      R_FAR         = 4 000 m
      R_NEAR        = 1 000 m  (effective last-ditch range)
      P_FAR         = 0.15     (marginal at the outer range — Mach 2 target)
      P_NEAR        = 0.55     (close-in; saturating the airspace)
      ROUNDS_PER_SECOND = 40   (2× 2A38M interleaved, ~40 rd/s effective)

    The burst fire model (BURST_FIRE_TIME, BURST_PAUSE_TIME) is inherited from
    Ciws unchanged — the cadence is the same for any autocannon system.

    Implementation note: Python class-level shadowing of the module's constants
    is used rather than monkey-patching, to avoid interfering with any live Ciws
    instance elsewhere in the same process.
    """

    # Override module-level constants from sim/ciws.py
    _ENGAGE_RANGE = GUN_RANGE_M         # 4 000 m
    _R_FAR        = GUN_RANGE_M         # 4 000 m
    _R_NEAR       = 1_000.0             # m last-ditch near boundary
    _P_FAR        = 0.15                # Pk at far boundary
    _P_NEAR       = 0.55                # Pk at near boundary
    _ROUNDS_PER_SECOND = GUN_ROUNDS_PER_SECOND  # 40 rd/s

    # --- Override the Ciws engage() loop ---
    def engage(self, target, dt: float) -> list:
        """Step the 30 mm gun for one physics substep.

        Identical logic to Ciws.engage but uses the Pantsir-specific
        engagement parameters stored as class-level attributes.
        """
        if not self.ready or not target.alive:
            return []

        tpos = target.pos
        tvel = target.velocity()

        dx = float(tpos[0])
        dy = float(tpos[1])
        dz = float(tpos[2])
        slant = math.sqrt(dx * dx + dy * dy + dz * dz)

        if slant > self._ENGAGE_RANGE:
            self._firing = False
            self._phase_t = 0.0
            return []

        if slant > 1e-6:
            closing = -(dx * float(tvel[0]) + dy * float(tvel[1])
                        + dz * float(tvel[2])) / slant
        else:
            closing = 1.0

        if closing <= 0.0:
            return []

        import sim.ciws as _ciws_mod
        BURST_FIRE_TIME  = _ciws_mod.BURST_FIRE_TIME
        BURST_PAUSE_TIME = _ciws_mod.BURST_PAUSE_TIME

        events = []
        self._phase_t += dt

        if not self._firing:
            if self._phase_t >= BURST_PAUSE_TIME:
                self._phase_t -= BURST_PAUSE_TIME
                self._firing = True
        if self._firing:
            if self._phase_t >= BURST_FIRE_TIME:
                self._phase_t -= BURST_FIRE_TIME
                self._firing = False

                rounds_fired = int(self._ROUNDS_PER_SECOND * BURST_FIRE_TIME)
                actual = min(rounds_fired, self.ammo)
                self.ammo -= actual

                snap_pos = np.array([dx, dy, dz], dtype=np.float64)
                events.append(("pantsir_gun", snap_pos))

                if actual > 0:
                    pk = self._kill_prob(slant)
                    if actual < rounds_fired:
                        pk *= actual / rounds_fired
                    if self._rng.random() < pk:
                        target.alive = False
                        events.append(("pantsir_kill", snap_pos))

        return events

    def _kill_prob(self, slant_range: float) -> float:
        """Linear Pk ramp clamped to [_P_FAR, _P_NEAR]."""
        if slant_range <= self._R_NEAR:
            return self._P_NEAR
        if slant_range >= self._R_FAR:
            return self._P_FAR
        t = (slant_range - self._R_NEAR) / (self._R_FAR - self._R_NEAR)
        return self._P_NEAR + t * (self._P_FAR - self._P_NEAR)


# ---------------------------------------------------------------------------
# Relative-target adapter (mirrors _RelTarget in sim/enemy_defense.py)
# ---------------------------------------------------------------------------

class _RelTarget:
    """Adapts a world missile into the gun-centric frame.

    The Ciws/gun measures slant range from target.pos (origin = gun mount);
    this adapter offsets the position and forwards the alive flag writes back
    to the real missile.
    """

    __slots__ = ("_missile", "pos")

    def __init__(self, missile, gun_pos: np.ndarray):
        self._missile = missile
        self.pos = missile.pos - gun_pos

    def velocity(self):
        return self._missile.vel

    @property
    def alive(self) -> bool:
        return self._missile.alive

    @alive.setter
    def alive(self, value: bool):
        self._missile.alive = value


# ---------------------------------------------------------------------------
# One unit's fire control (internal helper for PantsirDefenseController)
# ---------------------------------------------------------------------------

class _UnitDefense:
    """Fire control for a single Pantsir unit.

    Track store and engagement decision logic — mirrors ShipDefense in
    sim/enemy_defense.py, adapted for the player-side point-defense role.
    """

    def __init__(self, unit: Pantsir):
        self.unit = unit
        # id(missile) -> track dict matching ShipDefense._tracks schema:
        # {missile, t_next, since, pos, vel, age}
        self._tracks: dict[int, dict] = {}
        # Live 57E6 rounds fired by this unit (pruned each step)
        self._inflight: list[tuple] = []    # (SamMissile, target_key)

    # ---------------------------------------------------------------- tracking

    def _update_tracks(self, hostiles, now: float, dt: float) -> None:
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
                if self.unit.radar.detects(m.pos, "missile"):
                    if st["since"] is None:
                        st["since"] = now
                    st["pos"] = m.pos.copy()
                    st["vel"] = m.vel.copy()
                    st["age"] = 0.0
                else:
                    st["since"] = None          # sustain clock resets on loss
        for key in [k for k in self._tracks if k not in live_keys]:
            del self._tracks[key]               # missile died / left area

    def _tracked(self, st, now: float) -> bool:
        return st["since"] is not None and now - st["since"] >= TRACK_FORM_S

    def _estimate(self, key: int):
        """() -> (pos, vel) dead-reckoning closure over this track.

        Mirrors ShipDefense._estimate: plain-float tuples, no per-call
        temporaries. The last dead-reckoned estimate freezes if the track
        drops (the 57E6 continues guiding on the frozen point — same doctrine
        as the SM-2 on the destroyer).
        """
        st = self._tracks[key]
        px, py, pz = st["pos"].tolist()
        vx, vy, vz = st["vel"].tolist()
        age = st["age"]
        last = [(px + vx * age, py + vy * age, pz + vz * age),
                (vx, vy, vz)]

        def contact_estimate():
            trk = self._tracks.get(key)
            if trk is not None and trk["pos"] is not None:
                tx, ty, tz = trk["pos"].tolist()
                wx, wy, wz = trk["vel"].tolist()
                a = trk["age"]
                last[0] = (tx + wx * a, ty + wy * a, tz + wz * a)
                last[1] = (wx, wy, wz)
            return last[0], last[1]

        return contact_estimate

    # -------------------------------------------------------- SAM engagement

    def _time_to_impact(self, st, structures) -> float:
        """Estimated time for the tracked missile to reach the nearest structure.

        Uses the dead-reckoned position + velocity from the track to compute
        horizontal closing time to the closest structure.  A lower value means
        higher urgency.  Returns infinity if structures is empty.
        """
        if not structures:
            return math.inf
        ex = float(st["pos"][0]) + float(st["vel"][0]) * st["age"]
        ey = float(st["pos"][1]) + float(st["vel"][1]) * st["age"]
        ez = float(st["pos"][2]) + float(st["vel"][2]) * st["age"]
        vx, vy, vz = float(st["vel"][0]), float(st["vel"][1]), float(st["vel"][2])
        speed = math.sqrt(vx * vx + vy * vy + vz * vz)
        if speed < 1.0:
            return math.inf
        best = math.inf
        for s in structures:
            dx = float(s.pos[0]) - ex
            dz = float(s.pos[2]) - ez
            d = math.hypot(dx, dz)
            t = d / speed
            if t < best:
                best = t
        return best

    def _try_sam_launch(self, world, now: float, structures) -> None:
        unit = self.unit
        if (not unit.alive
                or unit.missile_ammo <= 0
                or unit._reload_timer > 0.0
                or len(self._inflight) >= PANTSIR_MAX_INFLIGHT):
            return

        ux, uz = float(unit.pos[0]), float(unit.pos[2])
        best_key = None
        best_rank = None

        for key, st in self._tracks.items():
            if not self._tracked(st, now) or not st["missile"].alive:
                continue
            # Gate on the dead-reckoned estimate position (mirrors ShipDefense)
            ex = float(st["pos"][0]) + float(st["vel"][0]) * st["age"]
            ey = float(st["pos"][1]) + float(st["vel"][1]) * st["age"]
            ez = float(st["pos"][2]) + float(st["vel"][2]) * st["age"]
            rng_ground = math.hypot(ex - ux, ez - uz)
            if not SAM_MIN_RANGE_M <= rng_ground <= PANTSIR_57E6.max_range:
                continue
            if not (PANTSIR_57E6.min_intercept_alt
                    <= ey
                    <= PANTSIR_57E6.max_intercept_alt):
                continue
            # Priority: smallest time-to-impact on nearest protected structure.
            tti = self._time_to_impact(st, structures)
            rank = (tti,)
            if best_rank is None or rank < best_rank:
                best_key, best_rank = key, rank

        if best_key is None:
            return

        # Launch position: PANTSIR_ANTENNA_M above the unit chassis (the 57E6
        # tubes are mounted on the same turret arm as the radar).
        launch_pos = unit.pos + np.array([0.0, PANTSIR_ANTENNA_M, 0.0])
        sam = SamMissile(
            PANTSIR_57E6,
            launch_pos,
            self._tracks[best_key]["missile"],
            contact_estimate_fn=self._estimate(best_key),
            rng=np.random.default_rng(int(unit._rng.integers(2 ** 63))),
            # No SARH illuminator: the 57E6 uses its own active/radar seeker
            # in terminal phase (illuminator_pos_fn=None → missile's own seeker
            # is the LOS source, identical to the S-300 player rounds).
            illuminator_pos_fn=None,
        )
        # Integration flags:
        #   launch_platform = unit → sim/damage.py skips self-OBB-hit on
        #     the first substep (same contract as ShipDefense SM-2 launches).
        #   launch_cinematic = False → no 1x time-accel lock (this is an
        #     automated point-defense event, not a dramatic player launch).
        #   is_hostile is not set → getattr(sam, 'is_hostile', False) returns
        #     False, so sim/bases.py apply_missile_hits_structures never feeds
        #     a 57E6 into the structure sweep.  Confirmed here explicitly.
        sam.launch_platform = unit
        sam.launch_cinematic = False

        world.missiles.append(sam)
        unit.missile_ammo -= 1
        # Start the magazine refill timer when the last round is consumed.
        if unit.missile_ammo <= 0 and unit._mag_reload_s > 0.0:
            unit.missile_ammo = 0
            unit._mag_reload_left = unit._mag_reload_s
        unit._reload_timer = MISSILE_RELOAD_S
        self._inflight.append((sam, best_key))
        world.events.append(("pantsir_launch", launch_pos.copy()))

    # -------------------------------------------------------- gun engagement

    def _run_gun(self, world, now: float, dt: float) -> None:
        unit = self.unit
        if not unit.alive or not unit.gun.ready:
            return

        gun_pos = unit.pos + np.array([0.0, GUN_MOUNT_M, 0.0])
        best = None
        best_d = GUN_RANGE_M

        for st in self._tracks.values():
            m = st["missile"]
            if not self._tracked(st, now) or not m.alive:
                continue
            d = math.sqrt(float((m.pos[0] - gun_pos[0]) ** 2
                                + (m.pos[1] - gun_pos[1]) ** 2
                                + (m.pos[2] - gun_pos[2]) ** 2))
            if d < best_d:
                best, best_d = m, d

        if best is None:
            return

        events = unit.gun.engage(_RelTarget(best, gun_pos), dt)
        for kind, rel_pos in events:
            world_pos = rel_pos + gun_pos
            if kind == "pantsir_kill":
                best.impact_pos = world_pos.copy()
            # Gun event kinds are already "pantsir_gun" / "pantsir_kill" as
            # set by _Pantsir30mmGun.engage().
            world.events.append((kind, world_pos))

    # ------------------------------------------------------------------- step

    def step(self, world, dt: float, structures) -> None:
        unit = self.unit
        unit.radar.alive = unit.alive   # dead unit → radar dark

        if not unit.alive:
            self._tracks.clear()
            self._inflight.clear()
            return

        now = world.sim_time

        # Tick down the fire-control reload timer
        if unit._reload_timer > 0.0:
            unit._reload_timer = max(0.0, unit._reload_timer - dt)

        # Tick the magazine refill timer (active only when _mag_reload_s > 0).
        if unit._mag_reload_left > 0.0:
            unit._mag_reload_left = max(0.0, unit._mag_reload_left - dt)
            if unit._mag_reload_left == 0.0:
                unit.missile_ammo = unit._mag_cap  # full refill

        # Inbound hostile missiles: is_hostile AND is_air AND alive AND
        # radar_size == 'missile'.  SamMissile instances (friendly 57E6, player
        # S-300) are excluded by is_hostile being False/absent.
        hostiles = [
            m for m in world.missiles
            if (getattr(m, "is_hostile", False)
                and getattr(m, "is_air", False)
                and m.alive
                and getattr(m, "radar_size", None) == "missile")
        ]

        self._update_tracks(hostiles, now, dt)
        self._inflight = [(sam, key) for sam, key in self._inflight if sam.alive]
        self._try_sam_launch(world, now, structures)
        self._run_gun(world, now, dt)


# ---------------------------------------------------------------------------
# PantsirDefenseController — the top-level player-side integration point
# ---------------------------------------------------------------------------

class PantsirDefenseController:
    """All Pantsir units' defenses, stepped after the base world step.

    Mirror of EnemyDefenseController (sim/enemy_defense.py) on the player
    side: defends player STRUCTURES against hostile strike missiles.

    Parameters
    ----------
    units:
        List of Pantsir instances (already joined to the radar network at
        their construction).
    structures:
        List of sim.bases.Structure objects representing player base
        elements (Bastion TELs, S-300 TELs, radar station).  Used to
        prioritise the most urgent intercept (threat closest to a structure
        in time-to-impact order).
    """

    def __init__(self, units, structures=None):
        self._unit_defenses = [_UnitDefense(u) for u in units]
        self._structures = structures if structures is not None else []

    def step(self, world, dt: float) -> None:
        for ud in self._unit_defenses:
            ud.step(world, dt, self._structures)
