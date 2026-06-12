"""Enemy land-attack strikes via ESM localization (pure numpy, GL-free).

COMBAT Phase 3: the destroyers shoot back at the player's BASE, not just at
his missiles. This is a SEPARATE module from sim/enemy_defense.py on
purpose: defense is per-ship reactive fire control (SPY-1 tracks -> SM-2 /
CIWS), while strikes are a side-level OFFENSIVE process — one shared ESM
localization estimate accumulated across every living destroyer, with the
salvo drawn from whichever magazines still hold Tomahawks. Keeping them
apart leaves the Phase-2 defense controller (and its tests) untouched and
gives the Phase-4 commander AI a clean seam: the commander will own
target priorities and replace this module's single-target trigger loop.

Doctrine (spec section 6 "Find -> Blind/Kill", section 3 "Emissions are
detectable"):

  * ESM localization: while the player radar station is ALIVE and EMITTING
    and at least one destroyer is afloat to hear it, a localization fix
    accumulates at 1/ESM_FIX_TIME_S per second (full firing fix after 90 s
    of cumulative emission). While the radar is silent (or dead, or no
    destroyer survives) the fix DECAYS at half the accrual rate — going
    dark protects the station, but the bearings already taken don't vanish
    instantly. No range gate: a megawatt-class search radar is heard by
    shipboard ESM far beyond every distance on this map (functional model,
    same spirit as sim/radar.py skipping RCS math).
  * At a full fix: a salvo of SALVO_SIZE Tomahawks launches at the radar
    station's surveyed coordinates (GPS/INS rounds — silencing the radar
    AFTER launch does not save it, only HARMs care about live emissions).
    While the station stays located + alive + emitting, follow-up salvos
    fire every SALVO_PERIOD_S.
  * Phase 3 scope: ONLY the radar station is findable. The Bastion and
    S-300 TELs do not emit, so passive ESM can never localize them — the
    Phase-4 commander AI hunts those with reconnaissance instead. This is
    why the lose condition is reachable only in Phase 4: in Phase 3 the
    enemy can blind the player but not yet kill the battery.

Launched Tomahawks join ``world.missiles`` with the Phase-2 integration
flags: ``launch_cinematic = False`` (no 1x time lock for enemy launches)
and ``launch_platform = <destroyer>`` (sim/damage.py: a deck launch never
OBB-hits its own hull). They carry ``is_hostile = True`` (class attribute,
sim/strike.py) so world/combat.py feeds them — and never the player's own
rounds — to the base-structure damage pass.

Determinism: no randomness here at all; given the same world the strikes
replay exactly.
"""

from __future__ import annotations

import numpy as np

from sim.arsenal import TOMAHAWK
from sim.enemy_defense import VLS_DECK_M
from sim.strike import StrikeMissile

# Full firing fix after this much cumulative emission time (spec section 6:
# the commander must "find" before he can "kill"; 90 s gives the player a
# real but unforgiving window to work radar-silent from the start).
ESM_FIX_TIME_S = 90.0

# Silent decay at HALF the accrual rate: 90 s of emission is forgotten
# after 180 s of silence — cross-bearings already plotted age out, they
# don't evaporate the moment the scope goes dark.
ESM_DECAY_FACTOR = 0.5

SALVO_SIZE = 2          # Tomahawks per salvo (shoot-shoot vs a soft emitter)
SALVO_PERIOD_S = 120.0  # s between salvos while located + alive + emitting

# Terminal aim height above the station ground: mid-height of the 22 m
# radar-tower OBB (sim/bases.py DIMS_RADAR). The Tomahawk's shallow
# terrain-following terminal approach must aim at the tower's belly — an
# aim point at ground level would drag the last kilometres of the
# trajectory sub-meter over the shelf and clip terrain short of the target.
RADAR_AIM_HEIGHT_M = 11.0


class EnemyStrikeController:
    """Side-level ESM localization + Tomahawk salvo trigger.

    Parameters
    ----------
    destroyers:
        The shooting platforms (sim/enemy_ships.py Destroyer); their
        ``tomahawk_ammo`` magazines are drawn down by salvos.
    radar:
        The player radar station (sim/radar.py Radar) being localized.
        Phase 4 generalizes this to the commander's emitter target list.
    """

    def __init__(self, destroyers, radar):
        self.destroyers = list(destroyers)
        self.radar = radar
        self.progress = 0.0     # ESM localization fix, 0..1 (1 = firing fix)
        self.salvo_cd = 0.0     # s until the next salvo may fire

    @property
    def located(self) -> bool:
        return self.progress >= 1.0

    def step(self, world, dt: float) -> None:
        """Advance the ESM fix and fire when the doctrine gates align.
        Called once per world step (world/combat.py CombatWorld.step);
        the math is rate-based, so any dt works (tests use coarse steps)."""
        heard = (self.radar.alive and self.radar.emitting
                 and any(d.alive for d in self.destroyers))
        if heard:
            self.progress = min(1.0, self.progress + dt / ESM_FIX_TIME_S)
        else:
            self.progress = max(
                0.0, self.progress - ESM_DECAY_FACTOR * dt / ESM_FIX_TIME_S)
        if self.salvo_cd > 0.0:
            self.salvo_cd = max(0.0, self.salvo_cd - dt)
        if heard and self.located and self.salvo_cd <= 0.0:
            if self._fire_salvo(world):
                self.salvo_cd = SALVO_PERIOD_S

    def _fire_salvo(self, world) -> bool:
        """Launch up to SALVO_SIZE Tomahawks at the surveyed station coords,
        drawing rounds across the living destroyers' magazines in order.
        Returns True when at least one round left a cell."""
        tx = float(self.radar.pos[0])
        tz = float(self.radar.pos[2])
        ty = float(self.radar.pos[1]) + RADAR_AIM_HEIGHT_M
        fired = 0
        for ship in self.destroyers:
            while (fired < SALVO_SIZE and ship.alive
                   and ship.tomahawk_ammo > 0):
                deck = ship.pos + np.array([0.0, VLS_DECK_M, 0.0])
                m = StrikeMissile(
                    TOMAHAWK, deck,
                    np.array([0.0, TOMAHAWK.eject_speed, 0.0]),
                    (tx, tz), target_y=ty)
                m.launch_cinematic = False  # no 1x lock for enemy launches
                m.launch_platform = ship    # damage.py: never self-OBB-hit
                world.missiles.append(m)
                ship.tomahawk_ammo -= 1
                fired += 1
            if fired >= SALVO_SIZE:
                break
        return fired > 0
