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

import numpy as np

from sim.amphibious import Transport
from sim.arsenal import TOMAHAWK
from sim.contacts import ContactBoard
from sim.enemy_air import Carrier, FS_PARKED
from sim.enemy_defense import VLS_DECK_M
from sim.enemy_ships import Destroyer
from sim.enemy_strikes import SALVO_SIZE
from sim.strike import StrikeMissile
from world.combat import CombatWorld
from world.combat_config import clamp_config
from world.generation import BASE_POS, SHIP_SPAWNS, SITES
from world.world import WorldState

# Director orders per press: a destroyer answers with the doctrine salvo
# size (sim/enemy_strikes.py SALVO_SIZE — shoot-shoot), a strike package
# rolls the doctrine 2-ship element (sim/commander.py package shape).
DIRECTOR_PACKAGE_JETS = 2

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

    # ---------------------------------------------------------- the director
    #
    # The RED-FORCE DIRECTOR (game/director.py drives this from the map):
    # inventory + direct launch orders that WORK WHILE PASSIVE — that is the
    # whole point — and spend real magazine ammo through the SAME launch
    # paths the enemy commander uses (physics-not-dice: the rounds fly the
    # combat physics, the aim runs the same _refine_strike_aim terminal
    # scene-matching, the sub still betrays itself with a launch datum).

    def set_weapons_free(self, on: bool) -> None:
        """The global AUTO-ENGAGE switch (defense + strikes + commander
        brain + sub fire-intent — see CombatWorld.enemy_weapons_free)."""
        self.enemy_weapons_free = bool(on)

    @staticmethod
    def _director_label(uid: str) -> str:
        return uid.replace("_", " ").upper()

    def director_units(self) -> list[dict]:
        """One row per orderable red unit for the director panel.

        Fighters are ONE aggregate row (the flight line rolls 2-ship
        packages; individual airframes belong to their own state machine).
        The carrier and AWACS are listed as informational rows (ready
        False) so the panel shows the whole force."""
        units = []
        for s in self.ships:
            if isinstance(s, Carrier):
                units.append(dict(
                    uid=s.ship_id, kind="carrier",
                    label=self._director_label(s.ship_id), pos=s.pos,
                    alive=s.alive, weapon="-", ammo=0, ready=False,
                    detail="FLIGHT OPS: USE THE FIGHTERS ROW"))
            elif isinstance(s, Destroyer) and not isinstance(s, Transport):
                ammo = int(getattr(s, "tomahawk_ammo", 0))
                units.append(dict(
                    uid=s.ship_id, kind="destroyer",
                    label=self._director_label(s.ship_id), pos=s.pos,
                    alive=s.alive, weapon="TOMAHAWK", ammo=ammo,
                    ready=bool(s.alive and ammo > 0),
                    detail=f"VLS {ammo} TLAM"))
        for sub in self.subs:
            ammo = int(sub.kalibr_ammo)
            units.append(dict(
                uid=sub.sub_id, kind="sub",
                label=self._director_label(sub.sub_id), pos=sub.pos,
                alive=sub.alive, weapon="KALIBR", ammo=ammo,
                ready=bool(sub.alive and ammo > 0),
                detail=f"TUBES {ammo} KALIBR"))
        parked = self._director_parked_fighters()
        n_alive = sum(1 for f in self._fighter_list
                      if getattr(f, "_alive", True))
        units.append(dict(
            uid="fighters", kind="fighters", label="FIGHTERS (STRIKE PKG)",
            pos=self.airfield.pos, alive=n_alive > 0, weapon="JASSM/HARM",
            ammo=len(parked), ready=len(parked) > 0,
            detail=f"{len(parked)} PARKED / {n_alive} AIRFRAMES"))
        for a in self.awacs_units:
            units.append(dict(
                uid=a.aircraft_id, kind="awacs",
                label=self._director_label(a.aircraft_id), pos=a.pos,
                alive=a.alive, weapon="-", ammo=0, ready=False,
                detail="SENSOR ORBIT (NOT ORDERABLE)"))
        return units

    def _director_parked_fighters(self) -> list:
        """Parked airframes at LIVE bases (a cratered runway rolls none —
        Fighter.launch itself refuses, this filter keeps the count honest).
        NOTE: a parked Fighter's ``alive`` property is False by design (the
        airframe is conceptually in the hangar) — the raw life flag is
        ``_alive``, the same read _release_fighter_weapons uses."""
        live_bases = [b for b in self.air_bases if b.alive]
        out = []
        for base in live_bases:
            out.extend(f for f in base.parked
                       if getattr(f, "_alive", True)
                       and f.state == FS_PARKED)
        return out

    def director_order(self, uid: str, target_xz) -> tuple[bool, str]:
        """Order unit ``uid`` to launch at the map point ``target_xz``
        (x, z) — works while passive, spends real magazine ammo.  Returns
        (ok, HUD-ready message)."""
        tx, tz = float(target_xz[0]), float(target_xz[1])
        if uid == "fighters":
            return self._director_strike_package(tx, tz, sead=False)
        ship = next((s for s in self.ships if s.ship_id == uid), None)
        if ship is not None:
            return self._director_tomahawk(ship, tx, tz)
        sub = next((s for s in self.subs if s.sub_id == uid), None)
        if sub is not None:
            return self._director_kalibr(sub, tx, tz)
        return False, f"DIRECTOR: NO SUCH UNIT '{uid}'"

    def director_sead(self) -> tuple[bool, str]:
        """The point-free SEAD row: a 2-ship HARM package at the player
        radar station (the seeker chases the EMISSION — going silent on R
        degrades the rounds to their CEP offsets, the honest counter)."""
        station = self.radar_station
        return self._director_strike_package(
            float(station.pos[0]), float(station.pos[2]), sead=True)

    def _director_tomahawk(self, ship, tx: float, tz: float):
        label = self._director_label(ship.ship_id)
        if isinstance(ship, Carrier):
            return False, "CARRIER: NO STRIKE WEAPONS"
        if not ship.alive:
            return False, f"{label}: DESTROYED"
        ammo = int(getattr(ship, "tomahawk_ammo", 0))
        if ammo <= 0:
            return False, f"{label}: TLAM MAGAZINE EMPTY"
        ax, az, ay = self._refine_strike_aim(tx, tz)
        n = min(SALVO_SIZE, ammo)
        for _ in range(n):
            deck = ship.pos + np.array([0.0, VLS_DECK_M, 0.0])
            m = StrikeMissile(
                TOMAHAWK, deck,
                np.array([0.0, TOMAHAWK.eject_speed, 0.0]),
                (ax, az), target_y=ay)
            m.launch_cinematic = False
            m.launch_platform = ship
            self.missiles.append(m)
            ship.tomahawk_ammo -= 1
        return True, f"TOMAHAWK x{n} AWAY - {label}"

    def _director_kalibr(self, sub, tx: float, tz: float):
        label = self._director_label(sub.sub_id)
        if not sub.alive:
            return False, f"{label}: SUNK"
        if sub.kalibr_ammo <= 0:
            return False, f"{label}: KALIBR TUBES EMPTY"
        before = int(sub.kalibr_ammo)
        # The combat launch path: CEP jitter + terminal refinement + the
        # launch-transient datum (the boat betrays itself — hunt it).
        self._fire_kalibr_salvo(sub, (tx, tz, 0.0))
        n = before - int(sub.kalibr_ammo)
        return True, f"KALIBR x{n} AWAY - {label}"

    def _director_strike_package(self, tx: float, tz: float, sead: bool):
        parked = self._director_parked_fighters()
        if not parked:
            return False, "FIGHTERS: NONE PARKED AT A LIVE BASE"
        jets = parked[:DIRECTOR_PACKAGE_JETS]
        self._director_seq = getattr(self, "_director_seq", 0) + 1
        kind = "harm_package" if sead else "jassm_package"
        target_id = (self.radar_station.radar_id if sead
                     else f"director_strike_{self._director_seq:03d}")
        # The commander's own order schema — _launch_strike_package arms
        # the loadout, rolls the jets and wires the release fields; the
        # (unconditional) release pump does the rest.  complete_mission on
        # a director target_id is a tolerant no-op in sim/commander.py.
        self._launch_strike_package({
            "type": kind,
            "target_pos": np.array([tx, 0.0, tz], dtype=np.float64),
            "target_id": target_id,
            "fighter_ids": [f.aircraft_id for f in jets],
        }, sead=sead)
        weapon = "HARM" if sead else "JASSM"
        return True, (f"{weapon} PACKAGE ROLLING - {len(jets)} "
                      f"JET{'S' if len(jets) != 1 else ''}")

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
