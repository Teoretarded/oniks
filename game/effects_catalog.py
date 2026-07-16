"""Inspectable particle-effect drivers for the F3 lab's EFFECTS tab.

GL-free: every driver only feeds the GL-free pools of an ``Effects``
instance the lab owns; the lab's ParticleRenderer draws whatever is
alive.  Each driver loops forever — one-shots re-fire every ``period``
so the inspector can study the whole life cycle, and full launches
re-arm after the round expires.

The point (user request): every effect in the game gets a name and a
front-row seat, so 'the vortex ring is weak' can be said while LOOKING
at exactly that effect instead of a mid-launch screenshot.
"""

from __future__ import annotations

import numpy as np

from sim.damage_model import fireball_radius_m
from game.cinematic_missiles import (
    ScriptedLaunch,
    VARIANT_BY_ID,
)

_UP = np.array([0.0, 1.0, 0.0])


class EffectDriver:
    """Loops one effect: fires ``trigger(fx, rng)`` every ``period`` s
    and/or runs ``continuous(fx, dt, t)`` each step."""

    def __init__(self, label: str, period: float, cam_dist: float,
                 trigger=None, continuous=None, blurb: str = ""):
        self.label = label
        self.period = float(period)
        self.cam_dist = float(cam_dist)
        self.blurb = blurb
        self._trigger = trigger
        self._continuous = continuous
        self.t = 0.0
        self._next_fire = 0.5          # first fire shortly after load

    def step(self, fx, dt: float) -> None:
        self.t += dt
        if self._trigger is not None and self.t >= self._next_fire:
            self._trigger(fx, fx.rng)
            self._next_fire += self.period
        if self._continuous is not None:
            self._continuous(fx, dt, self.t)


class _LaunchDriver:
    """A full scripted cold launch in the chamber, re-armed on expiry."""

    def __init__(self, variant_id: str):
        self.variant = VARIANT_BY_ID[variant_id]
        self.label = f"FULL LAUNCH - {self.variant.label}"
        self.blurb = self.variant.blurb
        self.cam_dist = 90.0
        self.t = 0.0
        self._m = None
        self._rearm_at = 0.5

    def step(self, fx, dt: float) -> None:
        self.t += dt
        if self._m is None:
            if self.t >= self._rearm_at:
                self._m = ScriptedLaunch(self.variant,
                                         (0.0, 0.0, 0.0), 0.0, 9.1)
                mouth = np.array([0.0, 9.1, 0.0])
                self._m.eject_fx(fx, mouth, 0.0)
            return
        events: list = []
        self._m.step(dt, events)
        for kind, pos in events:
            if kind == "ignite":
                self._m.ignition_fx(fx, pos)
            elif kind == "pad_blast":
                self._m.pad_blast_fx(fx, pos)
            elif kind == "pad_roll":
                self._m.pad_roll_fx(fx, pos)
        self._m.emit(fx, dt)
        if self._m.done:
            self._m = None
            self._rearm_at = self.t + 6.0    # let the column drift a beat


def _oneshot(name, label, period, cam_dist, blurb, h=6.0, **kwargs):
    def trigger(fx, rng):
        getattr(fx, name)(np.array([0.0, h, 0.0]), **kwargs)
    return lambda: EffectDriver(label, period, cam_dist, trigger=trigger,
                                blurb=blurb)


def _pad_fx(variant_id, which):
    v = VARIANT_BY_ID[variant_id]

    def trigger(fx, rng):
        m = ScriptedLaunch(v, (0.0, 0.0, 0.0), 0.0, 9.1)
        if which in ("blast", "both"):
            m.pad_blast_fx(fx, np.zeros(3))
        if which in ("roll", "both"):
            m.pad_roll_fx(fx, np.zeros(3))
    return trigger


def _continuous_plume(name, dirvec):
    d = np.asarray(dirvec, dtype=np.float64)

    def run(fx, dt, t, _carry=[0.0]):            # noqa: B006 — driver-local
        _carry[0] += dt * 120.0
        n = int(_carry[0])
        _carry[0] -= n
        for _ in range(min(n, 3)):
            getattr(fx, name)(np.array([0.0, 8.0, 0.0]), d)
    return run


def _ship_fire(fx, dt, t, _carry=[0.0]):         # noqa: B006
    _carry[0] += dt * 30.0
    n = int(_carry[0])
    _carry[0] -= n
    for _ in range(min(n, 2)):
        fx.ship_fire(np.array([0.0, 2.0, 0.0]))


_BUILDERS = {
    # Engine one-shots (combat effects, inspectable in isolation).
    "fx_muzzle_blast": _oneshot("muzzle_blast", "MUZZLE BLAST", 3.0, 26.0,
                                "57E6 rail launch flash + wash"),
    "fx_ignition_fireball": _oneshot("ignition_fireball",
                                     "IGNITION FIREBALL", 4.0, 40.0,
                                     "SAM light-off at the hang apex"),
    "fx_explosion_ground": _oneshot("explosion", "EXPLOSION - GROUND",
                                    5.0, 60.0, "ground impact",
                                    scale=1.0),
    "fx_explosion_water": _oneshot("explosion", "EXPLOSION - WATER",
                                   5.0, 60.0, "sea impact", scale=1.0,
                                   water=True),
    "fx_splash": _oneshot("splash", "SPLASH", 4.0, 40.0,
                          "missile into the sea"),
    "fx_magazine_detonation": lambda: EffectDriver(
        "MAGAZINE DETONATION", 12.0, 140.0,
        trigger=lambda fx, rng: fx.magazine_detonation(
            np.array([0.0, 6.0, 0.0]),
            fireball_radius_m(250.0), water=True),
        blurb="cook-off: double flash, black wall, ejecta"),
    # Continuous plumes.
    "fx_rideout_plume": lambda: EffectDriver(
        "RIDE-OUT PLUME", 1e9, 30.0,
        continuous=_continuous_plume("rideout_plume", (0.0, 1.0, 0.0)),
        blurb="low-thrust cream column (per step)"),
    "fx_boost_plume": lambda: EffectDriver(
        "BOOST PLUME", 1e9, 30.0,
        continuous=_continuous_plume("boost_plume", (0.0, 0.8, 0.6)),
        blurb="full-thrust grey bloom (per step)"),
    "fx_ship_fire": lambda: EffectDriver(
        "SHIP FIRE", 1e9, 40.0, continuous=_ship_fire,
        blurb="deck fire + black smoke"),
    # Cinematic launch stages (per round where it matters).
    "fx_cold_eject": lambda: EffectDriver(
        "COLD EJECT CLOUD - 48N6", 5.0, 40.0,
        trigger=lambda fx, rng: ScriptedLaunch(
            VARIANT_BY_ID["48n6"], (0.0, 0.0, 0.0), 0.0, 9.1
        ).eject_fx(fx, np.array([0.0, 9.1, 0.0]), 0.0),
        blurb="unlit gas ring + pad dust wash"),
    "fx_pad_blast_48n6": lambda: EffectDriver(
        "PAD BLAST - 48N6", 8.0, 90.0, trigger=_pad_fx("48n6", "both"),
        blurb="dust sheet + efflux surge + rolling ring"),
    "fx_pad_blast_40n6": lambda: EffectDriver(
        "PAD BLAST - 40N6", 10.0, 120.0, trigger=_pad_fx("40n6", "both"),
        blurb="the monster's wall jet"),
    "fx_pad_blast_9m96": lambda: EffectDriver(
        "PAD BLAST - 9M96", 6.0, 60.0, trigger=_pad_fx("9m96", "both"),
        blurb="the pencil's polite puff"),
    # Full launches (whole life cycle, re-armed after expiry).
    "fx_launch_48n6": lambda: _LaunchDriver("48n6"),
    "fx_launch_5v55": lambda: _LaunchDriver("5v55"),
    "fx_launch_9m96": lambda: _LaunchDriver("9m96"),
    "fx_launch_40n6": lambda: _LaunchDriver("40n6"),
}


def effect_ids() -> tuple:
    return tuple(sorted(_BUILDERS))


def effect_driver(effect_id: str):
    """Build a fresh looping driver for ``effect_id`` (lab entry point)."""
    try:
        return _BUILDERS[effect_id]()
    except KeyError:
        raise ValueError(f"unknown effect {effect_id!r}") from None
