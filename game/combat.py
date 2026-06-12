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
drone platform is active. Later phases add the air war, the commander AI
and the setup screen on top.

GL-touching module (subclasses game/sandbox.py) — never imported by unit
tests.
"""

from __future__ import annotations

from engine.mesh import Mesh
from game.controls import PLATFORMS_COMBAT
from game.sandbox import AIRCRAFT_DRAW_RANGE, SandboxState
from models.common import rot_x, rot_y, rot_z
from models.destroyer import build_destroyer
from models.drone import build_recon_drone
from sim.recon import DRONE_GONE
from world.combat import CombatWorld


class CombatState(SandboxState):
    """The COMBAT session: fog-of-war world on the sandbox engine."""

    PLATFORMS = PLATFORMS_COMBAT    # bastion -> s300 -> drone (Phase 4)

    def _build_world(self):
        return CombatWorld()

    def _build_meshes(self) -> None:
        super()._build_meshes()
        # Registered into the shared dict so _draw_ships picks it up by
        # ship_type and dispose() frees it with the other ship meshes.
        self._ship_meshes["destroyer"] = Mesh(build_destroyer())
        self._mesh_drone = Mesh(build_recon_drone())

    def dispose(self) -> None:
        self._mesh_drone.delete()
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
