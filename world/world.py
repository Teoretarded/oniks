"""WorldState: the live simulation world — ships, sites, missiles, contacts.

Pure numpy / GL-free (LOCKED test convention): imports only sim modules,
world.generation and the bastion model *constants* (engine.meshdata is
numpy-only). The render/effects side lives in game/sandbox.py, which drains
``WorldState.events`` each sim step:

    ("ship_hit", pos)         missile struck a ship hull (sim/damage.py)
    ("splash", pos)           missile hit the water surface (pos[1] == 0)
    ("ground_hit", pos)       missile hit terrain (pos[1] > 0)
    ("aircraft_down", pos)    falling aircraft crashed on terrain (pos[1] > 0)
    ("aircraft_splash", pos)  falling aircraft hit the sea (pos[1] == 0)
    ("sam_kill", pos)         SAM proximity fuse downed an aircraft (altitude)
    ("sam_self_destruct", pos)  SAM timed/slowed out — air burst, no kill
    ("oniks_intercepted", pos)  an interceptor fuse killed a cruise missile
    ("ciws_burst", pos)       enemy CIWS burst fired (sim/enemy_defense.py)
    ("ciws_kill", pos)        enemy CIWS burst downed an inbound missile

All positions float64, SI units, axes per LOCKED CONVENTIONS.
"""

from __future__ import annotations

import numpy as np

from models import bastion
from models import s300 as s300_model
from sim.aircraft import AC_FALLING, AC_GONE, Aircraft
from sim.arsenal import (BASTION, ONIKS, S300, S300_TEL, N40N6, N40N6_AMMO,
                         N40N6_TEL, WEAPONS)
from sim.contacts import ContactBoard
from sim.damage import apply_missile_hits
from sim.missile import LAUNCH_PHASES, Missile
from sim.sam import SamMissile
from sim.ships import Ship
from world.generation import (AIRCRAFT_SPAWNS, BASE_POS, LANES,
                              SAM_SITE_POS, SEED, SHIP_SPAWNS, SITES,
                              surface_height_scalar, terrain_height_scalar)

# --- Launcher tuning ----------------------------------------------------------

LAUNCH_ELEV_DEG = 88.0      # raised-canister elevation (matches the TEL model)

# Mouth of the raised starboard canister relative to the TEL origin (= ground
# center at BASE_POS): the canister pivots about +X at (CAN_X, PIVOT_Y,
# PIVOT_Z) and its mouth sits CAN_LEN - PIVOT_BACK along the elevated axis.
_MOUTH_RUN = bastion.CAN_LEN - bastion.PIVOT_BACK
_ELEV = np.radians(LAUNCH_ELEV_DEG)
CANISTER_MOUTH_OFFSET = np.array([
    bastion.CAN_X,
    bastion.PIVOT_Y + _MOUTH_RUN * np.sin(_ELEV),
    bastion.PIVOT_Z + _MOUTH_RUN * np.cos(_ELEV),
])

# --- S-300 battery (Task S4) ----------------------------------------------------

# The 5P85 TEL stands on a concrete pad at the SAM site; the pad deck tops
# the local terrain (156.0-156.3 m there since the S5 cliff band raised the
# coastal shelf) so the wheels never sink.
SAM_PAD_TOP = 156.5
SAM_TEL_POS = np.array([SAM_SITE_POS[0], SAM_PAD_TOP, SAM_SITE_POS[2]])

# Tube mouths of the ERECTED (90 deg) 2x2 block, relative to the TEL origin:
# block space (sx*TUBE_X, dy, MOUTH_RUN) maps through rot_x(-90 deg) to
# (sx*TUBE_X, MOUTH_RUN, -dy) about the pivot. Fired lower pair first.
SAM_MOUTH_OFFSETS = tuple(
    np.array([sx * s300_model.TUBE_X,
              s300_model.PIVOT_Y + s300_model.MOUTH_RUN,
              s300_model.PIVOT_Z - dy])
    for dy in (0.0, s300_model.PAIR_DY) for sx in (1.0, -1.0))


def launch_realtime_lock(missiles) -> bool:
    """True while any live missile is inside the launch cinematic (Oniks
    IGNITION/RIDE-OUT/PITCH-OVER/BOOST; the S-300's eject/boost ints alias
    into the same set): time accel is forced to 1x so the launch always plays
    real-time (requested rate auto-restores once every missile reaches
    CLIMB/CRUISE — the caller re-evaluates each frame). Enemy-launched
    rounds carry ``launch_cinematic = False`` (sim/enemy_defense.py) and
    never lock the player's time accel."""
    return any(m.alive and m.phase in LAUNCH_PHASES
               and getattr(m, "launch_cinematic", True) for m in missiles)


class WorldState:
    """Owns every simulated entity and steps them at the fixed physics rate."""

    # Damage-model flag (2026-07-06 subsystem revamp).  Class attribute so
    # every existing construction path stays byte-identical: "legacy" is the
    # flat hp-=1 ladder; CombatWorld overwrites it from CombatConfig, and
    # the game layer always plays "subsystem" (world/combat_config.py).
    damage_model = "legacy"

    def __init__(self, rng_seed: int = SEED):
        self.rng = np.random.default_rng(rng_seed)
        self.ships = self._spawn_ships()
        self.aircraft = self._spawn_aircraft()
        self.sites = self._spawn_sites()
        self.missiles: list[Missile] = []
        self.contacts = self._build_contacts()
        self.sim_time = 0.0
        self.events: list[tuple[str, np.ndarray]] = []
        self.reload_left = 0.0          # s until the launcher is ARMED again
        self.sam_reload_left = 0.0      # s until the next S-300 tube is ready
        self.sam_ammo = S300_TEL.ammo   # rounds left in the 4-tube block (48N6)
        # 40N6 stocks: 2 rounds on the same TEL (heavier missile, half load).
        # Shared reload timer with the 48N6 (one tube-to-tube reload cycle).
        self.sam_ammo_40n6 = N40N6_AMMO  # rounds: N40N6_AMMO = 2
        self.oniks_fired = 0            # launch ordinal: seeds the weave phase

        # --- Magazine-refill armory (LOCKED mechanic) -------------------------
        # These are None in the sandbox (infinite ammo); CombatWorld sets them
        # via _arm_magazines() after super().__init__() completes.
        self._oniks_mag_cap: int | None = None    # None -> infinite Oniks
        self._oniks_ammo: int | None = None       # current magazine count
        self._oniks_mag_reload_s: float = 0.0     # duration of refill
        self._oniks_mag_reload_left: float = 0.0  # s until refill completes

        # S-300 48N6 magazine refill (separate pool; shared refill duration)
        self._s300_48n6_mag_cap: int | None = None
        self._s300_48n6_mag_reload_left: float = 0.0
        # S-300 40N6 magazine refill
        self._s300_40n6_mag_cap: int | None = None
        self._s300_40n6_mag_reload_left: float = 0.0
        self._s300_mag_reload_s: float = 0.0      # shared refill duration

    @staticmethod
    def _spawn_ship(i: int, spawn: dict) -> Ship:
        ship = Ship(f"{spawn['ship_type']}_{i:02d}", spawn["ship_type"],
                    LANES[spawn["lane_index"]], spawn["lane_t0"])
        ship.speed = float(spawn["speed"])     # per-spawn speed override
        return ship

    def _spawn_ships(self) -> list[Ship]:
        """Sandbox default: the 14 lane-following traffic ships.
        CombatWorld overrides (world/combat.py)."""
        return [self._spawn_ship(i, spawn)
                for i, spawn in enumerate(SHIP_SPAWNS)]

    def _spawn_aircraft(self) -> list[Aircraft]:
        """Sandbox default: the 4 racetrack patrols."""
        return [Aircraft(s["aircraft_id"], s["aircraft_type"],
                         s["anchor_a"], s["anchor_b"])
                for s in AIRCRAFT_SPAWNS]

    def _spawn_sites(self):
        """Sandbox default: the enemy-coast land sites."""
        return SITES

    def _build_contacts(self) -> ContactBoard:
        """Sandbox default: the legacy all-seeing fuzzy board."""
        return ContactBoard((BASE_POS[0], BASE_POS[2]))

    @property
    def launcher_armed(self) -> bool:
        """True when the Bastion TEL is ready to fire.

        Two gates:
        1. Tube reload: ``reload_left`` must be 0 (tube mechanically re-cocked).
        2. Magazine: if a finite Oniks magazine is active (``_oniks_ammo`` is
           not None) the count must be positive.  None = sandbox infinite.
        """
        if self.reload_left > 0.0:
            return False
        if self._oniks_ammo is not None and self._oniks_ammo <= 0:
            return False
        return True

    @property
    def sam_launcher_armed(self) -> bool:
        """True when the S-300 48N6 battery is ready: tube reload expired,
        at least one 48N6 round in the tube block, AND the magazine refill
        timer (if active) has completed.

        This is the original interface used by the HUD and by
        tests/test_world_state.py — kept 48N6-specific so existing callers
        and tests are unchanged.

        For the 40N6 separate stock, check ``sam_40n6_launcher_armed``."""
        if self.sam_reload_left > 0.0:
            return False
        if self.sam_ammo <= 0:
            return False
        # Magazine refill in progress: block firing until refill completes.
        if self._s300_48n6_mag_reload_left > 0.0:
            return False
        return True

    @property
    def sam_40n6_launcher_armed(self) -> bool:
        """True when the 40N6 battery is ready: tube reload expired, at least
        one 40N6 round remaining, and any magazine refill timer completed."""
        if self.sam_reload_left > 0.0:
            return False
        if self.sam_ammo_40n6 <= 0:
            return False
        if self._s300_40n6_mag_reload_left > 0.0:
            return False
        return True

    # ---------------------------------------------------------------- armory

    def _arm_magazines(
        self,
        oniks_ammo: int | None,
        oniks_mag_reload_s: float,
        s300_48n6_ammo: int | None,
        s300_40n6_ammo: int | None,
        s300_mag_reload_s: float,
    ) -> None:
        """Set finite-magazine caps and reload durations (CombatWorld only).

        Call AFTER ``super().__init__()`` so that the tube-block counts
        (``self.sam_ammo``, ``self.sam_ammo_40n6``) are already initialised.
        Passing None for an ammo count leaves the corresponding pool infinite
        (sandbox behaviour is preserved by never calling this method at all).

        Parameters
        ----------
        oniks_ammo
            Starting Oniks magazine count (None -> infinite).
        oniks_mag_reload_s
            Seconds to refill a depleted Oniks magazine.
        s300_48n6_ammo
            Starting 48N6 magazine count (None -> infinite).
        s300_40n6_ammo
            Starting 40N6 magazine count (None -> infinite).
        s300_mag_reload_s
            Shared refill duration for both S-300 pools.
        """
        if oniks_ammo is not None:
            self._oniks_mag_cap = int(oniks_ammo)
            self._oniks_ammo = int(oniks_ammo)
        self._oniks_mag_reload_s = float(oniks_mag_reload_s)

        if s300_48n6_ammo is not None:
            self._s300_48n6_mag_cap = int(s300_48n6_ammo)
            # Seed the tube block with the smaller of magazine and TEL ammo.
            self.sam_ammo = min(self.sam_ammo, s300_48n6_ammo)
        if s300_40n6_ammo is not None:
            self._s300_40n6_mag_cap = int(s300_40n6_ammo)
            self.sam_ammo_40n6 = min(self.sam_ammo_40n6, s300_40n6_ammo)
        self._s300_mag_reload_s = float(s300_mag_reload_s)

    def terrain_height_at(self, x: float, z: float) -> float:
        """Scalar heightfield query (generation's bit-identical fast path)."""
        return terrain_height_scalar(x, z)

    def surface_height_at(self, x: float, z: float) -> float:
        """max(terrain_height_at, 0) — the impact/skim surface — through
        generation's exact open-water early-out (Task GATE perf): per-substep
        surface checks over the ocean skip the full noise stack."""
        return surface_height_scalar(x, z)

    # ------------------------------------------------------------------ step

    def step(self, dt: float) -> None:
        """Advance ships, aircraft, missiles, damage and the contact board by
        ``dt``; emit effects events and prune dead missiles."""
        self.sim_time += dt
        if self.reload_left > 0.0:
            self.reload_left = max(0.0, self.reload_left - dt)
        if self.sam_reload_left > 0.0:
            self.sam_reload_left = max(0.0, self.sam_reload_left - dt)

        # --- Magazine-refill timers (finite-ammo mode only) -------------------
        if self._oniks_mag_reload_left > 0.0:
            self._oniks_mag_reload_left = max(
                0.0, self._oniks_mag_reload_left - dt)
            if self._oniks_mag_reload_left == 0.0 and self._oniks_mag_cap is not None:
                self._oniks_ammo = self._oniks_mag_cap

        if self._s300_48n6_mag_reload_left > 0.0:
            self._s300_48n6_mag_reload_left = max(
                0.0, self._s300_48n6_mag_reload_left - dt)
            if (self._s300_48n6_mag_reload_left == 0.0
                    and self._s300_48n6_mag_cap is not None):
                self.sam_ammo = self._s300_48n6_mag_cap

        if self._s300_40n6_mag_reload_left > 0.0:
            self._s300_40n6_mag_reload_left = max(
                0.0, self._s300_40n6_mag_reload_left - dt)
            if (self._s300_40n6_mag_reload_left == 0.0
                    and self._s300_40n6_mag_cap is not None):
                self.sam_ammo_40n6 = self._s300_40n6_mag_cap
        for ship in self.ships:
            ship.update(dt)
        for ac in self.aircraft:
            was_falling = ac.state == AC_FALLING
            ac.update(dt)
            if was_falling and ac.state == AC_GONE:   # impact ends the spiral
                kind = ("aircraft_down" if ac.impact_pos[1] > 1e-6
                        else "aircraft_splash")
                self.events.append((kind, ac.impact_pos.copy()))
        flying = [m for m in self.missiles if m.alive]
        for m in flying:
            m.update(dt, self)
        # Missiles that died inside update() hit the surface; ship hits are
        # applied next (disjoint sets — apply_missile_hits skips dead ones).
        surface_dead = [m for m in flying if not m.alive]
        apply_missile_hits(self.missiles, self.ships, self.events,
                           damage_model=self.damage_model)
        if self.damage_model == "subsystem":
            # 2026-07-06 subsystem model: integrate flooding-vs-pumps /
            # fire-vs-crew / cook-off dwell for every managed hull.  Pure
            # no-op in legacy mode (this branch is never taken), and a
            # near-no-op with no hits yet (no ship carries a _dmg state).
            from sim import damage_model as _dm
            _dm.step_ships(self.ships, dt, self.events)
        for m in surface_dead:
            # SAM death causes first (a fuse kill / self-destruct happens at
            # altitude and must not classify as a terrain strike).
            if getattr(m, "killed_target", False):
                kind = "sam_kill"
            elif getattr(m, "self_destructed", False):
                kind = "sam_self_destruct"
            elif m.impact_pos is None:
                # Killed mid-air by an interceptor fuse (COMBAT: an SM-2
                # downing an Oniks): no surface was ever touched, so this
                # must not classify as a terrain strike or splash.
                m.impact_pos = m.pos.copy()
                kind = "oniks_intercepted"
            elif m.impact_pos[1] > 1e-6:
                kind = "ground_hit"
            else:
                kind = "splash"
            self.events.append((kind, m.impact_pos.copy()))
        if any(not m.alive for m in self.missiles):
            self.missiles = [m for m in self.missiles if m.alive]
        self.contacts.update(self.ships, dt, self.sim_time)
        self.contacts.update(self.aircraft, dt, self.sim_time)

    def drain_events(self) -> list:
        """Return and clear the pending effects events."""
        events, self.events = self.events, []
        return events

    # ---------------------------------------------------------------- launch

    def launch(self, profile: str, target_point, waypoints=(),
               weapon_id="oniks"):
        """Fire a Bastion round (Oniks or Zircon) from the base TEL at
        ``target_point`` (float64 (3,), sea level) via optional (x, z)
        ``waypoints``. Returns the Missile, or None while reloading."""
        if not self.launcher_armed:
            return None
        base = np.array(BASE_POS, dtype=np.float64)
        pos = base + CANISTER_MOUTH_OFFSET
        tp = np.asarray(target_point, dtype=np.float64)
        fx, fz = waypoints[0] if len(waypoints) else (tp[0], tp[2])
        heading = float(np.arctan2(fx - pos[0], fz - pos[2]))
        m = Missile(WEAPONS.get(weapon_id, ONIKS), pos, heading, profile, tp,
                    waypoints=waypoints, salvo=self.oniks_fired)
        self.oniks_fired += 1
        self.missiles.append(m)
        self.reload_left = BASTION.reload_s

        # Consume one round from the finite magazine (if armed).
        if self._oniks_ammo is not None:
            self._oniks_ammo -= 1
            if self._oniks_ammo <= 0:
                # Magazine depleted — start the refill timer.
                self._oniks_ammo = 0
                self._oniks_mag_reload_left = self._oniks_mag_reload_s

        return m

    def launch_sam(self, aircraft_id, round_id: str = "48n6"):
        """Fire an S-300 at the air contact ``aircraft_id``.

        Parameters
        ----------
        aircraft_id : str
            Track id on the contact board.
        round_id : str, optional
            ``'48n6'`` (default) — standard S-300 48N6 round (max 4 in TEL).
            ``'40n6'`` — very-long-range 40N6 round (max 2 in TEL).

        Round selection notes
        --------------------
        Both rounds share the same 5P85 TEL and the same sam_reload_left timer
        (one tube mechanically indexes per reload cycle; mixing round types is
        realistic — the TEL operator selects the canister type electronically).
        The 40N6 uses an ACTIVE terminal seeker (illuminator_pos_fn=None):
        the SamMissile LOS check runs from the missile itself, not a ground
        illuminator.  This is the key difference from the 48N6 (which uses
        the same None default — the player S300 is also own-seeker because
        there is no S-300-specific illuminator pointer in the sandbox world).

        Engagement-envelope enforcement (round-specific):
            40N6: min_intercept_alt = 4,000 m — only engages HIGH targets.
                  Attempting a sub-4 km-alt target returns None (no shoot).
            48N6: min_intercept_alt = 100 m (existing behavior unchanged).

        Returns the SamMissile, or None when cold/empty/invalid track/out-of-
        envelope.
        """
        # Gate on round-specific armed state (reload timer + ammo).
        if round_id == "40n6":
            if not self.sam_40n6_launcher_armed:
                return None
        else:
            if not self.sam_launcher_armed:
                return None

        track = self.contacts.tracks.get(aircraft_id)
        if track is None or not track.get("is_air"):
            return None
        target = self._find_air_entity(aircraft_id)
        if target is None:
            return None

        # Select weapon def and ammo pool.
        if round_id == "40n6":
            if self.sam_ammo_40n6 <= 0:
                return None
            weapon_def = N40N6
            # 40N6 envelope check: min altitude 4,000 m.  Judge the DEAD-
            # RECKONED estimate — the exact altitude the contact card
            # displays (hud.intel_snapshot alt = estimated_pos()[1]).  The
            # raw fix lags a climbing target: a stale sub-4 km fix denied
            # shots the card showed at 4.7+ km (playtest 2026-07-05).  The
            # player acts on what they SEE, not on the stale fix.
            target_alt = float(
                self.contacts.estimated_pos(aircraft_id, self.sim_time)[1])
            if target_alt < weapon_def.min_intercept_alt:
                return None  # out of envelope: refuses sub-4 km targets
            # Tube index: 40N6 occupies the last 2 canister positions (index
            # 2 and 3 of the 4-tube block, after the 48N6 pair).
            tube = N40N6_AMMO - self.sam_ammo_40n6 + 2
        else:
            # Default: 48N6
            if self.sam_ammo <= 0:
                return None
            weapon_def = S300
            tube = S300_TEL.ammo - self.sam_ammo

        # Guard the tube index on BOTH sides: a refilled magazine (mag_cap can
        # exceed the 4-tube block) drives ``S300_TEL.ammo - sam_ammo`` negative
        # past -len, which IndexErrors on the canister-offset tuple. The tube
        # only picks a cosmetic mouth offset, so clamping is safe.
        tube = max(0, min(tube, len(SAM_MOUTH_OFFSETS) - 1))
        pos = SAM_TEL_POS + SAM_MOUTH_OFFSETS[tube]

        # Active seeker (40N6) vs SARH (48N6 in sandbox context):
        # Both pass illuminator_pos_fn=None here.  The 48N6 in the sandbox
        # uses its own seeker LOS (same behaviour as before this change).
        # The 40N6 is explicitly ARH — also None.  CombatWorld subclasses
        # that want SARH for 48N6 can override _launch_sam_48n6 separately.
        m = SamMissile(weapon_def, pos, target,
                       contact_estimate_fn=self._contact_estimate(aircraft_id))
        self.missiles.append(m)

        if round_id == "40n6":
            self.sam_ammo_40n6 -= 1
            # Start magazine refill if the 40N6 pool just ran out.
            if self.sam_ammo_40n6 <= 0 and self._s300_40n6_mag_cap is not None:
                self.sam_ammo_40n6 = 0
                self._s300_40n6_mag_reload_left = self._s300_mag_reload_s
        else:
            self.sam_ammo -= 1
            # Start magazine refill if the 48N6 pool just ran out.
            if self.sam_ammo <= 0 and self._s300_48n6_mag_cap is not None:
                self.sam_ammo = 0
                self._s300_48n6_mag_reload_left = self._s300_mag_reload_s

        self.sam_reload_left = S300_TEL.reload_s
        return m

    def _find_air_entity(self, aircraft_id):
        """The live air ENTITY behind an air contact id — the S-300 launch
        and retarget lookups and the sandbox's selected-contact camera all
        route through this one hook.  The sandbox world only flies
        ``self.aircraft``; CombatWorld overrides to also search its enemy
        air list (world/combat.py — fighters/AWACS are S-300 targets)."""
        return next((a for a in self.aircraft
                     if a.aircraft_id == aircraft_id), None)

    def _contact_estimate(self, aircraft_id):
        """A () -> (pos, vel) closure over the board's dead-reckoned track
        for ``aircraft_id``, frozen at the last fix if the track drops.
        Returns plain-float 3-tuples (Task GATE perf: the SAM guidance reads
        components per 120 Hz substep — no per-call array temporaries)."""
        board = self.contacts
        est = board.estimated_pos(aircraft_id, self.sim_time)
        vel = board.tracks[aircraft_id]["vel"]
        last = [(float(est[0]), float(est[1]), float(est[2])),
                (float(vel[0]), float(vel[1]), float(vel[2]))]

        def contact_estimate():
            trk = board.tracks.get(aircraft_id)
            if trk is not None:
                px, py, pz = trk["pos"].tolist()
                vx, vy, vz = trk["vel"].tolist()
                age = trk["age"]
                last[0] = (px + vx * age, py + vy * age, pz + vz * age)
                last[1] = (vx, vy, vz)
            return last[0], last[1]

        return contact_estimate

    def retarget_sam(self, missile, aircraft_id) -> bool:
        """Swap a flying SAM onto air contact ``aircraft_id`` (Task RTG):
        new target aircraft + a fresh contact-estimate closure over the new
        track. False when the track is not a live air contact or the round
        is committed (terminal) — the missile is untouched."""
        track = self.contacts.tracks.get(aircraft_id)
        if track is None or not track.get("is_air"):
            return False
        target = self._find_air_entity(aircraft_id)
        if target is None:
            return False
        return missile.retarget(
            target, contact_estimate_fn=self._contact_estimate(aircraft_id))
