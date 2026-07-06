"""SandboxWarState: the WAR SANDBOX shell — the menu SANDBOX button.

CombatState with a SandboxWorld (docs/plans/sandbox_war_2026-07-06.md):
every combat mesh, platform, HUD pane, the forensics ledger (J), the
battery panel (O) and the black-box ledger come along by inheritance;
the world underneath swaps in the full passive toybox with the
all-seeing player picture and no defeat/victory latch (the end overlay
can therefore never open — ``_check_end_state`` reads the overridden
properties and stays inert forever).

The civilian lane traffic and patrol racetracks render through the SAME
inherited passes: ``_draw_ships`` routes by ``ship.ship_type`` through
the shared ``_ship_meshes`` dict (the base class builds the civilian
hull meshes, CombatState registers the destroyer/carrier), and
CombatState's ``_draw_aircraft`` calls the base pass first (the patrol
racetracks) before the drone / enemy-air additions.

Phase C lands ``toggle_director`` + the map director panel here; until
then the I key falls through to the base hint.

GL-touching module (subclasses game/combat.py) — never imported by unit
tests.
"""

from __future__ import annotations

from game.combat import CombatState
from world.sandbox_world import SandboxWorld


class SandboxWarState(CombatState):
    """The SANDBOX session: full toybox, passive red force, no game-over."""

    def _build_world(self):
        """Always the war-sandbox world — there is no setup screen on this
        path (the toybox IS the config; world/sandbox_world.SANDBOX_CONFIG)."""
        return SandboxWorld()

    def __init__(self, app):
        # CombatState stashes _config before its __init__ builds the world;
        # None here means the ledger header + scorecard paths read the
        # world's own _config (SANDBOX_CONFIG) — the established fallback.
        super().__init__(app, config=None)
