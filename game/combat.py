"""CombatState: the COMBAT mode shell (Phase 2).

SandboxState with a CombatWorld: same engine, cameras, tactical map and
weapons — none of the sandbox traffic, a radar-gated contact picture, and
two enemy destroyers that defend themselves (SM-2 + CIWS via the world's
EnemyDefenseController). The only render-side addition is the destroyer
mesh: ``_draw_ships`` already routes by ``ship.ship_type`` through
``_ship_meshes``, so registering the builder is the whole job. Later
phases add enemy strikes, the commander AI and the setup screen on top.

GL-touching module (subclasses game/sandbox.py) — never imported by unit
tests.
"""

from __future__ import annotations

from engine.mesh import Mesh
from game.sandbox import SandboxState
from models.destroyer import build_destroyer
from world.combat import CombatWorld


class CombatState(SandboxState):
    """The COMBAT session: fog-of-war world on the sandbox engine."""

    def _build_world(self):
        return CombatWorld()

    def _build_meshes(self) -> None:
        super()._build_meshes()
        # Registered into the shared dict so _draw_ships picks it up by
        # ship_type and dispose() frees it with the other ship meshes.
        self._ship_meshes["destroyer"] = Mesh(build_destroyer())
