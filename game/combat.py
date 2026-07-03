"""CombatState: the COMBAT mode shell (Phase 2).

SandboxState with a CombatWorld: same engine, cameras, tactical map and
weapons — none of the sandbox traffic, a radar-gated contact picture, and
two enemy destroyers that defend themselves (SM-2 + CIWS via the world's
EnemyDefenseController). The only render-side addition is the destroyer
mesh: ``_draw_ships`` already routes by ``ship.ship_type`` through
``_ship_meshes``, so registering the builder is the whole job.

Phase 4 adds the recon drone: TAB gains the third 'drone' platform
(PLATFORMS_COMBAT), the RQ-4-class mesh (models/drone.py) flies the
world's drone + falling wrecks in the aircraft draw pass (same range cull
and attitude convention — ReconDrone exposes heading/pitch/roll), and the
[ / ] subject cycle swaps the TEL anchor for the live airframe while the
drone platform is active.

Phase 5a adds the enemy air war's bodies: the carrier renders through the
shared ``_ship_meshes`` routing (ship_type 'carrier'), the enemy airfield
joins ``_site_draws`` (a static mesh at the structure's terrain pin — the
3D world always shows the real geometry; only the MAP is fog-gated), and
``world.enemy_air`` (fighters + AWACS) draws in the aircraft pass with the
same range cull and attitude convention (both classes expose
heading/pitch/roll). Parked/rearming fighters are skipped: the airframe
is conceptually in the hangar / below deck, and at 280+ km it is
sub-pixel anyway (deck clutter is Phase-7 polish). Later phases add the
commander AI and the setup screen on top.

GL-touching module (subclasses game/sandbox.py) — never imported by unit
tests.
"""

from __future__ import annotations

from engine.mesh import Mesh
from game.combat_end import CombatEndOverlay
from game.controls import PLATFORMS_COMBAT, combat_platforms
from game.sandbox import AIRCRAFT_DRAW_RANGE, SandboxState
from game.scoring import (
    compute_par, compute_scorecard, grade, new_telemetry,
    picture_has_actionable_contact,
)
from models.airfield import build_airfield
from models.awacs import build_awacs
from models.carrier import build_carrier
from models.common import rot_x, rot_y, rot_z
from models.destroyer import build_destroyer
from models.drone import build_recon_drone
from models.fighter import build_fighter
from models.jammer import build_jammer
from models.pantsir import build_pantsir
from models.structures import build_radar_station
from sim.enemy_air import FS_GONE, FS_PARKED, FS_REARMING, Fighter, JammerAircraft
from sim.recon import DRONE_GONE
from world.combat import CombatWorld


# Phase 6: how long the HUD 'ENGAGING' label latches after a Pantsir launch
# (real time, decremented per sim step).  Long enough to read at a glance
# across the short reload cadence, short enough to clear between salvos.
PANTSIR_ENGAGE_FLASH_S = 1.5


class CombatState(SandboxState):
    """The COMBAT session: fog-of-war world on the sandbox engine."""

    PLATFORMS = PLATFORMS_COMBAT    # bastion -> s300 -> drone (Phase 4)

    def _build_world(self):
        """Build the combat world from the setup-screen config.  ``_config``
        is stashed BEFORE super().__init__ runs (which calls this), so it is
        available here; falls back to the CombatWorld default when None (the
        screen-less smoke/test path)."""
        config = getattr(self, "_config", None)
        return CombatWorld(config) if config is not None else CombatWorld()

    def __init__(self, app, config=None):
        # _config must exist before super().__init__ -> _build_meshes/
        # _build_world reads it (the world is constructed inside the base
        # __init__).  None is the legacy default-config path.
        self._config = config
        super().__init__(app)
        # The TAB cycle is built from the world: the base three-platform cycle,
        # plus the Buk mid-SAM (M5, when n_buk>0) and the loitering-swarm pod
        # (M4-B, when a pod is armed).  The default battle (n_buk=0, no pod)
        # returns EXACTLY PLATFORMS_COMBAT, so the cycle is byte-identical.
        self.PLATFORMS = combat_platforms(self.world)
        # Phase 8: draw one Bastion TEL per Oniks launcher + one S-300 TEL per
        # S-300 launcher (salvo batteries).
        self._tel_positions = [p.copy()
                               for p in self.world._oniks_launcher_positions]
        self._sam_tel_positions = [p.copy()
                                   for p in self.world._s300_launcher_positions]
        # M5 Buk mid-SAM TEL positions (empty list when n_buk=0).  The buk
        # platform anchors / subjects at the first TEL; the rounds render with
        # the existing default missile mesh (DEDICATED meshes deferred to a
        # later batched model pass — NOT yet in DEDICATED_MISSILE_IDS).
        self._buk_tel_positions = [p.copy()
                                   for p in self.world._buk_launcher_positions]
        if self._buk_tel_positions:
            from game.sandbox import StaticSubject, _UP, LAUNCHER_LOOK_UP
            buk0 = self._buk_tel_positions[0]
            self._buk_tel_pos = buk0.copy()
            self._tel_subjects["buk"] = StaticSubject(
                buk0 + _UP * LAUNCHER_LOOK_UP, "BUK TEL")
        # HUD 'ENGAGING' flash: a real-time countdown refreshed whenever a
        # Pantsir launches a 57E6 (detected as a drop in pooled missile ammo
        # across the units — a launch is exactly one round consumed).  Read
        # by game/hud.py pantsir_status_row via the ``pantsir_engaging``
        # property.
        self._pantsir_engage_left = 0.0
        self._pantsir_ammo_prev = self._pantsir_ammo_total()
        # Phase 7 end screen: a CombatEndOverlay is created the first time
        # ``victorious`` or ``defeated`` latches (subsuming the 5b inline HUD
        # banner — a brief in-HUD line may still read underneath).  The
        # overlay is OWNED by this state (not an app-state switch) so the sim
        # keeps running underneath, dimmed, exactly as the spec asks; input
        # routes to it while it is up.  None until the battle ends.
        self._end_overlay: CombatEndOverlay | None = None
        self._final_card = None      # the graded ScoreCard at battle end
        # M6 after-action scoring telemetry: a per-battle accumulator updated in
        # sim_step (round counts from the launch-wrapper returns, first-fix from
        # the PLAYER contact picture, leakers from own-round TERMINAL events).
        # All fog-honest — see game/scoring.py.  Built into the ScoreCard at
        # battle end (the ONE truth read allowed: the AAR kill tallies).
        self._telemetry = new_telemetry()
        # Player offensive rounds already counted as leakers (by id), so a round
        # is tallied ONCE the first time it enters its TERMINAL homing leg.
        self._leaker_seen: set[int] = set()

    def _pantsir_ammo_total(self) -> int:
        """Pooled 57E6 rounds remaining across all Pantsir units (alive or
        not — a dead unit launches nothing, so its count is frozen and the
        delta detector never false-fires on a death)."""
        return sum(u.missile_ammo
                   for u in getattr(self.world, "pantsirs", ()))

    @property
    def pantsir_engaging(self) -> bool:
        """True while the post-launch HUD flash window is open."""
        return self._pantsir_engage_left > 0.0

    # ----------------------------------------------------- scoring telemetry

    @staticmethod
    def _is_player_offensive(m) -> bool:
        """A player OFFENSIVE round (Oniks/Zircon/ASBM cruise — NOT a SAM) in
        its TERMINAL homing leg: the go-low payoff a 'leaker' measures.  Excludes
        every hostile round (is_hostile) and friendly SAM intercepts (a SAM
        carries ``sam_phase``).  Friendly-round state -> no fog."""
        if getattr(m, "is_hostile", False):
            return False
        if hasattr(m, "sam_phase") or type(m).__name__.endswith("SamMissile"):
            return False
        return True

    def request_launch(self):
        """Single-fire (SPACE, and the salvo's FIRST round): count ONE player
        round on a real launch (non-None Missile return).  Counting on the
        wrapper RETURN is precise — a refused/empty/reloading tube returns None
        and is NOT counted.  The world launch path is untouched (no counter in
        world -> the CombatWorld digest stays byte-identical)."""
        m = super().request_launch()
        if m is not None:
            self._telemetry["rounds_fired"] += 1
        return m

    def _request_sam_launch(self):
        """S-300 single-fire: count ONE round on a real (non-None) launch."""
        m = super()._request_sam_launch()
        if m is not None:
            self._telemetry["rounds_fired"] += 1
        return m

    def _tick_salvo(self, dt: float) -> None:
        """Salvo ripple rounds (the queued tubes after the first): count exactly
        the player rounds the salvo ADDED to ``world.missiles`` this tick — by
        diffing the live player-round id set across the base tick.  This is
        precise even when several beats fall due in one tick (high warp) and
        never counts a no-op reload beat (which adds no round).  The salvo's
        FIRST round already fired through request_launch above, so it is counted
        there, not here (it was launched before this tick's diff window)."""
        before = self._player_round_ids()
        super()._tick_salvo(dt)
        after = self._player_round_ids()
        self._telemetry["rounds_fired"] += len(after - before)

    def _player_round_ids(self) -> set:
        """Ids of the player's OWN live rounds currently in ``world.missiles``
        (non-hostile cruise + friendly SAM).  Friendly-round state -> no fog."""
        return {id(m) for m in getattr(self.world, "missiles", ())
                if not getattr(m, "is_hostile", False)}

    def _accumulate_telemetry(self) -> None:
        """Fog-honest in-battle telemetry, called each sim_step AFTER world.step:
          * first_fix_t — latched ONCE to ``world.sim_time`` the first time the
            PLAYER contact picture (world.contacts.tracks) holds an enemy SURFACE
            contact (is_air False): the recon->fire opening move.  Reads only the
            radar-gated player picture -> an UNDETECTED hostile never trips it.
          * leakers — each player OFFENSIVE round counted ONCE the first time it
            enters its TERMINAL homing leg (a round that got through to terminal).
            Reads friendly-round state only.
        Neither read touches enemy truth for a decision; both are measurements."""
        world = self.world
        tel = self._telemetry
        if tel["first_fix_t"] is None and picture_has_actionable_contact(world):
            tel["first_fix_t"] = float(getattr(world, "sim_time", 0.0))
        for m in getattr(world, "missiles", ()):
            mid = id(m)
            if mid in self._leaker_seen:
                continue
            if (getattr(m, "phase_label", None) == "TERMINAL"
                    and self._is_player_offensive(m)):
                self._leaker_seen.add(mid)
                tel["leakers"] += 1

    def sim_step(self, dt: float) -> None:
        """Base sim step, then refresh the Pantsir 'ENGAGING' HUD flash: any
        drop in pooled 57E6 ammo this step is a fresh launch -> relatch the
        window; otherwise let it count down in real time.  Accumulate the M6
        scoring telemetry, then latch the end screen the first time the battle
        is decided."""
        super().sim_step(dt)
        ammo = self._pantsir_ammo_total()
        if ammo < self._pantsir_ammo_prev:
            self._pantsir_engage_left = PANTSIR_ENGAGE_FLASH_S
        elif self._pantsir_engage_left > 0.0:
            self._pantsir_engage_left = max(0.0,
                                            self._pantsir_engage_left - dt)
        self._pantsir_ammo_prev = ammo
        self._accumulate_telemetry()
        self._check_end_state()

    # ------------------------------------------------------------- end screen

    def _check_end_state(self) -> None:
        """Latch the CombatEndOverlay the first time the battle is decided.
        Defeat outranks victory if both somehow trip in one frame (losing the
        Bastion is final — same precedence as the HUD banner)."""
        if self._end_overlay is not None:
            return
        world = self.world
        if getattr(world, "defeated", False):
            self._open_end_overlay(victory=False)
        elif getattr(world, "victorious", False):
            self._open_end_overlay(victory=True)

    def _open_end_overlay(self, victory: bool) -> None:
        """Build the end overlay with callbacks wired onto the App flows:
        REMATCH replays the SAME config, NEW BATTLE re-opens the setup
        screen, MAIN MENU discards the session.  enter() is called so its
        deferred GL/text bind runs (the overlay is owned by this state, not
        switched in via the state machine).

        M6: compute the after-action ScoreCard (a deterministic END pass — the
        ONE truth read allowed, the AAR kill tallies) and pass it into the
        overlay's stats block.  Any failure degrades gracefully to the legacy
        no-stats overlay so a scoring edge case can never block the end screen."""
        app = self.app
        config = self._config
        card = self._build_scorecard()
        # M6 campaign wiring: a battle launched through the hub ends into
        # CONTINUE CAMPAIGN (advance + save + back to the hub) instead of
        # REMATCH/NEW BATTLE — and MAIN MENU also records first, so a decided
        # battle is never grade-scummable.
        in_campaign = (getattr(app, "campaign_battle", False)
                       and getattr(app, "campaign", None) is not None)
        self._final_card = card
        overlay = CombatEndOverlay(
            app, victory,
            rematch_cb=lambda: app.start_combat(config),
            new_battle_cb=app.open_combat_setup,
            menu_cb=(self._campaign_quit if in_campaign
                     else app.quit_to_menu),
            scorecard=card,
            campaign_cb=self._campaign_continue if in_campaign else None)
        overlay.enter()
        self._end_overlay = overlay

    def _campaign_advance(self) -> None:
        """Record the decided battle into the campaign: snapshot the ledger,
        record the grade, resupply, step (or END the campaign on a defeat),
        persist.  The campaign_battle flag flips False first so a second
        overlay callback can never double-advance."""
        import game.campaign as campaign
        app = self.app
        if not getattr(app, "campaign_battle", False):
            return
        app.campaign_battle = False
        letter = getattr(self._final_card, "grade", "") or "D"
        campaign.advance(app.campaign, self.world, letter)
        campaign.save(app.campaign)

    def _campaign_continue(self) -> None:
        self._campaign_advance()
        self.app.open_campaign()

    def _campaign_quit(self) -> None:
        self._campaign_advance()
        self.app.quit_to_menu()

    def _build_scorecard(self):
        """Compose the end-of-battle ScoreCard from the world + telemetry and
        grade it against the per-seed PAR.  Returns None on any error (the
        overlay then renders the legacy no-stats layout)."""
        try:
            card = compute_scorecard(self.world, self._telemetry)
            seed = int(getattr(self._config, "seed", 0)) if self._config \
                else int(getattr(getattr(self.world, "_config", None),
                                 "seed", 0) or 0)
            cfg = self._config or getattr(self.world, "_config", None)
            if cfg is not None:
                card.grade = grade(card, compute_par(seed, cfg))
            return card
        except Exception:
            return None

    def handle_event(self, ev) -> None:
        """Route input to the end overlay once the battle is decided (its
        REMATCH/NEW BATTLE/MAIN MENU rows + ESC); otherwise the normal
        sandbox controls."""
        if self._end_overlay is not None:
            self._end_overlay.handle_event(ev)
            return
        super().handle_event(ev)

    def render(self, dt_real: float) -> None:
        """Normal sandbox render; once the battle is decided, draw the live
        scene (the sim keeps running underneath — spec §2.2) and lay the
        end overlay's dim + panel on top.  The overlay's _tick_pending runs
        inside its render, advancing the 80 ms press-flash before firing."""
        if self._end_overlay is not None:
            self.controls.update(dt_real)        # free-cam still flies
            self.rig.update(dt_real, self.followed)
            audio = self.app.audio
            audio.set_listener(self.camera.eye)
            audio.update_loops(self._loop_sources())
            w, h = self.window.size()
            self._draw_scene(w, h)
            self._end_overlay.render(dt_real)
            return
        super().render(dt_real)

    def _build_meshes(self) -> None:
        super()._build_meshes()
        # Registered into the shared dict so _draw_ships picks it up by
        # ship_type and dispose() frees it with the other ship meshes.
        self._ship_meshes["destroyer"] = Mesh(build_destroyer())
        self._ship_meshes["carrier"] = Mesh(build_carrier())
        self._mesh_drone = Mesh(build_recon_drone())
        self._mesh_fighter = Mesh(build_fighter())
        self._mesh_awacs = Mesh(build_awacs())
        # M3-F2 escort jammer (EA-18G Growler): a dedicated mesh so the player
        # can tell a Growler from the E-2/E-3 AWACS it used to share a mesh
        # with.  Built unconditionally; the draw pass only picks it for a live
        # JammerAircraft, so the n_jammers=0 default never touches it.
        self._mesh_jammer = Mesh(build_jammer())
        # Phase 6: the player's Pantsir-S1 SHORAD vehicles (friendly, static
        # ground units guarding the base).  One shared mesh drawn at each
        # unit's terrain-pinned position in _draw_pantsirs.
        self._mesh_pantsir = Mesh(build_pantsir())
        # Enemy airfield: drawn like the land sites (appended into
        # _site_draws so the base _draw_scene renders it and dispose()
        # frees it with the other site meshes). The structure's pos is
        # already terrain-pinned (world/combat.py).
        self._site_draws.append((Mesh(build_airfield()),
                                 self.world.airfield.pos.copy()))
        # Phase 7 enemy ground radars (spec §5.5): each is a radar-station
        # structure on the enemy continent.  The 3D geometry ALWAYS exists
        # (only the tactical MAP marker is fog-gated via known_enemy_sites),
        # so each draws at its terrain pin in the same _site_draws list the
        # airfield uses — one Mesh per unit, all freed by the base dispose().
        # Reuses build_radar_station (the friendly station's model); a hulk
        # stays rendered after a kill (destruction visuals are backlog, like
        # the other structures).
        for struct, _radar in getattr(self.world, "enemy_radars", ()):
            self._site_draws.append((Mesh(build_radar_station()),
                                     struct.pos.copy()))

    def dispose(self) -> None:
        self._mesh_drone.delete()
        self._mesh_fighter.delete()
        self._mesh_awacs.delete()
        self._mesh_jammer.delete()
        self._mesh_pantsir.delete()
        super().dispose()

    # ------------------------------------------------------------- platform

    def _platform_anchor(self):
        """Launcher-cam ground anchor for the active platform.  The M5 buk
        platform anchors at the Buk site; everything else defers to the base
        (s300 -> SAM site, else the Bastion base)."""
        if self.active_platform == "buk" and getattr(self, "_buk_tel_pos", None) \
                is not None:
            return self._buk_tel_pos
        return super()._platform_anchor()

    def _platform_subject(self):
        """[ / ] cycle entry for the active platform: the flying drone
        when the drone platform is active and one is up (falling wrecks
        are not camera subjects — the rig drops dead subjects anyway);
        otherwise the TEL StaticSubject like the base class."""
        if self.active_platform == "drone":
            drone = getattr(self.world, "drone", None)
            if drone is not None and drone.alive:
                return drone
        return super()._platform_subject()

    # --------------------------------------------------------------- render

    def _draw_tel(self) -> None:
        """The base TEL/S-300 ground assets (super) plus the Pantsir-S1
        SHORAD vehicles.  Each Pantsir is static and terrain-pinned; the
        model's forward (+Z) already faces the +z threat-ingress bearing,
        so it draws with identity rotation.  Destroyed units stay rendered
        as a hulk (base structures do the same — destruction visuals are
        Phase-7 polish), but their radar has already gone dark in the sim.

        M5/M4 stand-ins: the Buk TELAR draws the erected S-300 TEL mesh and
        a swarm pod the horizontal Bastion TEL truck at their sim positions —
        an armed battery the camera anchors on must never be INVISIBLE
        (dedicated meshes are the deferred model pass).  Both lists are
        empty at defaults (byte-identical n_buk=0 / no pods)."""
        super()._draw_tel()
        for unit in getattr(self.world, "pantsirs", ()):
            self.renderer.draw_mesh(self._mesh_pantsir, unit.pos)
        # Live world positions (NOT the init copy): a shoot-and-scoot Buk
        # must render where it actually is.
        for pos in getattr(self.world, "_buk_launcher_positions", ()):
            self.renderer.draw_mesh(self._mesh_s300_tel, pos)
        for pos in getattr(self.world, "_swarm_pod_positions", ()):
            self.renderer.draw_mesh(self._tel_meshes[0], pos)

    def _draw_aircraft(self) -> None:
        """The sandbox aircraft pass (none spawn in COMBAT), plus the
        recon drone and any falling wrecks — same visual-range cull and
        the Aircraft attitude convention (rot_x(-pitch) noses down for
        negative pitch, rot_z(-roll) drops the right wing)."""
        super()._draw_aircraft()
        world = self.world
        drones = list(getattr(world, "drone_wrecks", ()))
        drone = getattr(world, "drone", None)
        if drone is not None:
            drones.append(drone)
        eye = self.camera.eye
        for d in drones:
            if d.state == DRONE_GONE:
                continue
            p = d.pos
            dx = p[0] - eye[0]
            dy = p[1] - eye[1]
            dz = p[2] - eye[2]
            if (dx * dx + dy * dy + dz * dz
                    > AIRCRAFT_DRAW_RANGE * AIRCRAFT_DRAW_RANGE):
                continue                        # sub-pixel: skip the draw
            rot = rot_y(d.heading) @ rot_x(-d.pitch) @ rot_z(-d.roll)
            self.renderer.draw_mesh(self._mesh_drone, p, rot)
        # Phase 5a: enemy air (fighters + AWACS), same cull + attitude
        # convention. Fighters on the ground (parked/rearming) or out of
        # the war (GONE) are skipped; a crashed AWACS (impact landed) too.
        for e in getattr(world, "enemy_air", ()):
            if isinstance(e, Fighter):
                if e.state in (FS_PARKED, FS_REARMING, FS_GONE):
                    continue
                mesh = self._mesh_fighter
            else:
                if e.impact_pos is not None:    # AWACS/jammer wreck on ground
                    continue
                # JammerAircraft subclasses Awacs — test it FIRST so the
                # Growler draws as a Growler, not an E-2/E-3 (the AWACS mesh
                # is the fallthrough for the genuine AWACS).
                mesh = (self._mesh_jammer if isinstance(e, JammerAircraft)
                        else self._mesh_awacs)
            p = e.pos
            dx = p[0] - eye[0]
            dy = p[1] - eye[1]
            dz = p[2] - eye[2]
            if (dx * dx + dy * dy + dz * dz
                    > AIRCRAFT_DRAW_RANGE * AIRCRAFT_DRAW_RANGE):
                continue                        # sub-pixel: skip the draw
            rot = rot_y(e.heading) @ rot_x(-e.pitch) @ rot_z(-e.roll)
            self.renderer.draw_mesh(mesh, p, rot)
