"""CombatState: the COMBAT mode shell (Phase 1).

SandboxState with a CombatWorld: same engine, cameras, tactical map and
weapons — none of the sandbox traffic, and a radar-gated contact picture.
Later phases add enemies, the commander AI and the setup screen on top.
"""

from __future__ import annotations

from game.sandbox import SandboxState
from world.combat import CombatWorld


class CombatState(SandboxState):
    """The COMBAT session: fog-of-war world on the sandbox engine."""

    def _build_world(self):
        return CombatWorld()
