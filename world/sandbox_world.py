"""SandboxWorld: the WAR SANDBOX — every combat toy, no fog, no game-over.

The 2026-07-06 sandbox-war port (docs/plans/sandbox_war_2026-07-06.md):
the sandbox becomes a subclass of the combat stack instead of the bare
WorldState.  Three deltas, everything else inherited verbatim:

  * FULL TOYBOX, PASSIVE: SANDBOX_CONFIG spawns the whole red force
    (typed destroyer fleet + carrier, subs, fighters/AWACS/jammer,
    transports) AND the whole blue armory (multi-TEL Oniks battery,
    S-300, Pantsir, Buk, swarm pod, drone, CBR, ASW kit) — but
    ``enemy_weapons_free`` starts False: the red force sails and flies
    its patterns, senses and evades, yet never fires until the director
    flips auto-engage or issues a direct launch order.
  * ALL-SEEING PLAYER PICTURE: the ContactBoard is built UNGATED
    (visible_fn None — the legacy sandbox behavior, sim/contacts.py),
    and the fixed-installation fog latches (airfield_known /
    _enemy_radar_known) are forced open, so the map shows the world.
    The ENEMY still fights on its own sensor picture (no-cheat DNA is
    untouched); only the PLAYER side is omniscient.
  * NO SESSION END: ``defeated`` / ``victorious`` never latch (the
    structures still burn — only the end screen is disabled), so the
    sandbox runs forever.

GL-free (LOCKED test convention) — unit-tested headless in
tests/test_sandbox_world.py.
"""

from __future__ import annotations

from sim.contacts import ContactBoard
from world.combat import CombatWorld
from world.combat_config import clamp_config
from world.generation import BASE_POS, SHIP_SPAWNS, SITES
from world.world import WorldState

# --- The toybox ---------------------------------------------------------------
# Built through clamp_config so every value is guaranteed inside the setup-UI
# ranges (the LOCKED plan rule: take the clamp's cap rather than bypass it).
# Counts: the full red order of battle (every M5 ship class, subs, a jammer,
# a transport for the LCAC show) + the full blue armory (every optional
# battery armed).  Ammo pools are GENEROUS (a sandbox should not run dry in
# a sitting) with short magazine refills — but still finite, so the HUD ammo
# rows stay honest and the magazine mechanic remains visible.
SANDBOX_SEED = 7
SANDBOX_CONFIG = clamp_config(
    seed=SANDBOX_SEED,
    # Red force.
    n_destroyers=3,
    n_flagship=1,
    n_aaw=1,
    n_ground_attack=1,
    n_awacs=1,
    n_jammers=1,
    n_enemy_radars=2,
    n_subs=2,
    sub_kalibr_ammo=8,
    n_transports=1,
    # Blue force.
    n_player_radars=1,
    n_pantsir=2,
    n_drones=1,
    player_jammer=1,
    n_oniks=2,
    n_s300=1,
    n_buk=1,
    n_swarm_pods=1,
    n_cbr=1,
    # Blue armory (generous pools, quick refills).
    oniks_ammo=99,
    oniks_mag_reload_s=30.0,
    zircon_ammo=99,
    asbm_ammo=12,
    kh31p_ammo=12,
    s300_48n6_ammo=32,
    s300_40n6_ammo=12,
    s300_mag_reload_s=30.0,
    pantsir_57e6_ammo=24,
    pantsir_mag_reload_s=30.0,
    buk_9m317_ammo=24,
    buk_9m338_ammo=24,
    buk_mag_reload_s=30.0,
    swarm_cells_per_pod=8,
    swarm_mag_reload_s=60.0,
    n_sonobuoys=30,
    asw_ammo=10,
)


class SandboxWorld(CombatWorld):
    """CombatWorld variant: full toybox, passive red force, no fog, no end."""

    def __init__(self, config=SANDBOX_CONFIG, rng_seed: int | None = None):
        super().__init__(config, rng_seed)
        # Passive until ordered: the director (game/director.py) flips this
        # or calls the director_* order API directly.
        self.enemy_weapons_free = False
        # A sandbox map hides nothing: latch the fixed-installation fog
        # open (moving tracks are already ungated by _build_contacts below).
        self.airfield_known = True
        self._enemy_radar_known.update(
            site["id"] for site in self._enemy_radar_sites)

    # ------------------------------------------------------------- spawning

    def _spawn_ships(self):
        """The combat fleet PLUS the legacy civilian lane traffic.

        Civilian hulls are plain sim.ships.Ship — every combat roster
        filter (defense/strikes/ELINT/commander) selects by
        isinstance(Destroyer), so the traffic never enters a fire-control
        list; it is scenery the player may sink."""
        ships = super()._spawn_ships()
        ships.extend(self._spawn_ship(i, spawn)
                     for i, spawn in enumerate(SHIP_SPAWNS))
        return ships

    def _spawn_aircraft(self):
        """Re-add the legacy patrol racetracks CombatWorld removed."""
        return WorldState._spawn_aircraft(self)

    def _spawn_sites(self):
        """Combat sites (player radar pins) + the legacy coast scenery.

        The legacy 'radar' pin (RADAR STN ALPHA) is EXCLUDED: real enemy
        ground radars exist in this world and a scenery twin on the map
        would read as a third installation that cannot be killed."""
        sites = list(super()._spawn_sites())
        sites.extend(s for s in SITES if s["kind"] != "radar")
        return sites

    # ------------------------------------------------------------- sensors

    def _build_contacts(self) -> ContactBoard:
        """All-seeing player board (visible_fn None = the legacy sandbox
        behavior).  super() still runs first so the radar infrastructure
        (player_radars / radar_station / radar_net) is built identically —
        the enemy ESM/strike/ARM paths and the R-key emissions toggle all
        need the real station; only the returned PLAYER board is ungated."""
        super()._build_contacts()
        return ContactBoard((BASE_POS[0], BASE_POS[2]))

    # ------------------------------------------------------------ no ending

    @property
    def defeated(self) -> bool:
        """The sandbox never ends: structures burn, the session continues."""
        return False

    @property
    def defeat_cause(self):
        return None

    @property
    def victorious(self) -> bool:
        return False
