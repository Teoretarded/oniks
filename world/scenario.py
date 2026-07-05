"""SCENARIO FORGE: spawn precise tactical situations for tests and agents.

AI-testability build (2026-07-05).  A targeted test used to need minutes
of simulated enemy AI to produce "3 inbound Tomahawks at bearing 040";
this module spawns that situation in one call — THROUGH THE REAL SPAWN
MACHINERY, never a parallel test-only path:

* :func:`spawn_inbound` fires the exact StrikeMissile the enemy fires
  (sim/arsenal TOMAHAWK / JASSM defs, the EnemyStrikeController launch
  recipe: VLS eject for Tomahawk, air-drop release for JASSM, the same
  integration flags and the same belly-of-the-tower aim height).
* :func:`run_until` steps the real ``world.step`` loop to a condition,
  draining events per tick exactly like the live game loop.
* :func:`set_battery` adjusts only pools/flags the world already owns.

TEST/DEV-FACING ONLY: nothing in the game shell imports this module, so
the byte-identical default battle cannot be touched by construction.
Determinism: no RNG anywhere here — same args, same world -> byte-
identical spawns.
"""

from __future__ import annotations

import math

import numpy as np

from sim.arsenal import JASSM, TOMAHAWK
from sim.enemy_defense import VLS_DECK_M
from sim.enemy_strikes import RADAR_AIM_HEIGHT_M
from sim.strike import StrikeMissile

DT = 1.0 / 120.0

# Spacing between successive rounds of one spawned wave, along the ingress
# bearing (m).  Mirrors a ripple launch: round i starts i*SPACING further
# out, so the wave arrives as a stream, not a stacked point.
SPACING_M = 800.0

# JASSM release state (the enemy releases from strike-fighter cruise):
# altitude and forward speed at the drop point (sim/enemy_air.py releases
# at aircraft cruise ~9 km / high-subsonic; the def's _launched_above_cruise
# path then descends it onto its 30 m AGL run-in).
JASSM_RELEASE_ALT_M = 9_000.0
JASSM_RELEASE_SPEED = 240.0

_KINDS = {"tomahawk": TOMAHAWK, "jassm": JASSM}


def _aim_point(world, target):
    """The aim structure's (x, z, terminal y) — the same surveyed-coords
    aim the enemy strike controller uses (belly of the radar tower)."""
    if target == "radar" or target is None:
        station = world.radar_station
        return (float(station.pos[0]), float(station.pos[2]),
                float(station.pos[1]) + RADAR_AIM_HEIGHT_M)
    # An explicit (x, z) point (sea-level target).
    return float(target[0]), float(target[1]), 0.0


def spawn_inbound(world, *, kind: str = "tomahawk", bearing_deg: float,
                  range_km: float, n: int = 1, target="radar") -> list:
    """Spawn ``n`` hostile strike rounds inbound on ``target``.

    The launch point sits at ``bearing_deg`` / ``range_km`` FROM the target
    (bearing measured from the target, atan2(dx, dz) convention like the
    rest of the sim); successive rounds start SPACING_M further out along
    the same bearing.  Tomahawks eject VLS-style from deck height exactly
    like :meth:`sim.enemy_strikes.EnemyStrikeController._fire_salvo`;
    JASSMs release air-drop style at strike-fighter cruise state.  Returns
    the spawned rounds (already appended to ``world.missiles``)."""
    weapon = _KINDS[kind]
    tx, tz, ty = _aim_point(world, target)
    brg = math.radians(float(bearing_deg))
    ux, uz = math.sin(brg), math.cos(brg)
    rng0 = float(range_km) * 1_000.0
    rounds = []
    for i in range(int(n)):
        r = rng0 + i * SPACING_M
        x = tx + ux * r
        z = tz + uz * r
        if kind == "jassm":
            pos = np.array([x, JASSM_RELEASE_ALT_M, z], dtype=np.float64)
            # Release velocity: aircraft cruise vector, nose at the target.
            vel = np.array([-ux * JASSM_RELEASE_SPEED, 0.0,
                            -uz * JASSM_RELEASE_SPEED], dtype=np.float64)
        else:
            pos = np.array([x, VLS_DECK_M, z], dtype=np.float64)
            vel = np.array([0.0, weapon.eject_speed, 0.0], dtype=np.float64)
        m = StrikeMissile(weapon, pos, vel, (tx, tz), target_y=ty)
        m.launch_cinematic = False       # enemy rounds never 1x-lock
        m.launch_platform = None         # no deck to exempt (virtual launch)
        world.missiles.append(m)
        rounds.append(m)
    return rounds


def set_battery(world, *, oniks_ammo: int | None = None,
                zircon_ammo: int | None = None,
                sam_ammo: int | None = None,
                sam_ammo_40n6: int | None = None,
                radar_emitting: bool | None = None) -> None:
    """Adjust the player battery's own pools/flags — attributes the world
    already owns (world/combat.py); nothing is invented here."""
    if oniks_ammo is not None:
        world._oniks_ammo = int(oniks_ammo)
    if zircon_ammo is not None:
        world._zircon_ammo = int(zircon_ammo)
    if sam_ammo is not None:
        world.sam_ammo = int(sam_ammo)
    if sam_ammo_40n6 is not None:
        world.sam_ammo_40n6 = int(sam_ammo_40n6)
    if radar_emitting is not None:
        world.radar_station.emitting = bool(radar_emitting)


def run_until(world, cond, *, timeout_s: float, dt: float = DT) -> bool:
    """Step the world (draining events per tick, like the live loop) until
    ``cond(world)`` is truthy or ``timeout_s`` sim seconds elapse.  Returns
    True when the condition fired, False on timeout — a timeout is a FACT
    for the caller to assert on, never an exception."""
    steps = int(round(float(timeout_s) / dt))
    for _ in range(steps):
        if cond(world):
            return True
        world.step(dt)
        world.drain_events()
    return bool(cond(world))


# ---------------------------------------------------------- canned checks

def first_hostile_air_track(world) -> bool:
    """The player picture holds at least one hostile WEAPON track — the
    radar-gated detection of an inbound round (fog-honest: reads only the
    ContactBoard, an undetected round never trips it).  A weapon track is
    one whose ``kind`` is a weapon_id outside the player's OWN_KINDS IFF
    set; platform tracks (ships/aircraft, kind None) don't count."""
    from sim.contacts import OWN_KINDS
    for trk in world.contacts.tracks.values():
        kind = trk.get("kind")
        if trk.get("is_air") and kind is not None and kind not in OWN_KINDS:
            return True
    return False


def battle_over(world) -> bool:
    return bool(getattr(world, "victorious", False)
                or getattr(world, "defeated", False))
