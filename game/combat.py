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
from game.controls import PLATFORMS_COMBAT
from game.sandbox import AIRCRAFT_DRAW_RANGE, SandboxState
from models.airfield import build_airfield
from models.awacs import build_awacs
from models.carrier import build_carrier
from models.common import rot_x, rot_y, rot_z
from models.destroyer import build_destroyer
from models.drone import build_recon_drone
from models.fighter import build_fighter
from models.pantsir import build_pantsir
from models.structures import build_radar_station
from sim.enemy_air import FS_GONE, FS_PARKED, FS_REARMING, Fighter
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
        # Phase 8: draw one Bastion TEL per Oniks launcher + one S-300 TEL per
        # S-300 launcher (salvo batteries).
        self._tel_positions = [p.copy()
                               for p in self.world._oniks_launcher_positions]
        self._sam_tel_positions = [p.copy()
                                   for p in self.world._s300_launcher_positions]
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

    def sim_step(self, dt: float) -> None:
        """Base sim step, then refresh the Pantsir 'ENGAGING' HUD flash: any
        drop in pooled 57E6 ammo this step is a fresh launch -> relatch the
        window; otherwise let it count down in real time.  Finally latch the
        end screen the first time the battle is decided."""
        super().sim_step(dt)
        ammo = self._pantsir_ammo_total()
        if ammo < self._pantsir_ammo_prev:
            self._pantsir_engage_left = PANTSIR_ENGAGE_FLASH_S
        elif self._pantsir_engage_left > 0.0:
            self._pantsir_engage_left = max(0.0,
                                            self._pantsir_engage_left - dt)
        self._pantsir_ammo_prev = ammo
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
        switched in via the state machine)."""
        app = self.app
        config = self._config
        overlay = CombatEndOverlay(
            app, victory,
            rematch_cb=lambda: app.start_combat(config),
            new_battle_cb=app.open_combat_setup,
            menu_cb=app.quit_to_menu)
        overlay.enter()
        self._end_overlay = overlay

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
        self._mesh_pantsir.delete()
        super().dispose()

    # ------------------------------------------------------------- platform

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
        Phase-7 polish), but their radar has already gone dark in the sim."""
        super()._draw_tel()
        for unit in getattr(self.world, "pantsirs", ()):
            self.renderer.draw_mesh(self._mesh_pantsir, unit.pos)

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
                if e.impact_pos is not None:    # AWACS wreck on the ground
                    continue
                mesh = self._mesh_awacs
            p = e.pos
            dx = p[0] - eye[0]
            dy = p[1] - eye[1]
            dz = p[2] - eye[2]
            if (dx * dx + dy * dy + dz * dz
                    > AIRCRAFT_DRAW_RANGE * AIRCRAFT_DRAW_RANGE):
                continue                        # sub-pixel: skip the draw
            rot = rot_y(e.heading) @ rot_x(-e.pitch) @ rot_z(-e.roll)
            self.renderer.draw_mesh(mesh, p, rot)
