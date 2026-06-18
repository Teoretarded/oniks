"""AswRound: the player's coastal ASW prosecution weapon (ASROC-class) — M5.

The player does NOT get a submarine; they get the MEANS to KILL the enemy boat
once it is localized.  An AswRound is a rocket-thrown lightweight torpedo /
depth-charge: it lofts from the base on a ballistic throw to the LOCALIZED FIX
point (a buoy cross-fix or a fresh launch datum — NEVER truth), splashes, and
runs a short acoustic-seeker terminal modelled as a BASKET check:

    splash at the fix  ->  is the REAL boat within ASW_SEEKER_BASKET_M of the
    fix?  yes -> acquire + Submarine.kill();  no -> miss into the deep.

So the kill probability EMERGES from the FIX QUALITY vs the basket (physics-not-
dice), identical in philosophy to the strike-acquisition SEEKER_BASKET_M gate —
a sharp buoy cross-fix kills, a coarse stale datum misses.  The round flies the
FIX (the believed pos); it reads the boat's truth ONLY at the terminal basket
check (it does not guide on truth), exactly as the S-300 fires at a contact
track and the proximity fuse resolves against the real target.

is_hostile = False (class attr) so the round is excluded from the base-damage
sweep (like the friendly Pantsir 57E6) — it can never demolish the player base.

Pure numpy, GL-free.  Axes: X east, Y up, Z north.  All SI float64.  No RNG (the
outcome is deterministic geometry — the believed fix is supplied by the caller).
"""

from __future__ import annotations

import math
from typing import Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Phase constants (distinct from the missile/sam/strike ranges)
# ---------------------------------------------------------------------------
ASW_THROW   = 40   # ballistic rocket-throw toward the fix
ASW_SPLASH  = 41   # entered the water at the fix; running the basket terminal
ASW_DEAD    = 42   # acquired+killed, or splashed and missed (spent)

PHASE_LABELS = {ASW_THROW: "THROW", ASW_SPLASH: "SPLASH", ASW_DEAD: "DEAD"}

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------
# The acoustic seeker basket: the terminal homing radius the lightweight torpedo
# can search around the splash point.  THE discriminator — a localized fix within
# this of the real boat is killed; beyond it the torpedo searches empty water.
# 1500 m: a real Mk54-class torpedo's acoustic acquisition is a few hundred m to
# ~1-2 km; 1500 m makes a SHARP buoy cross-fix (probe-measured ~1-2 km quality)
# a reliable kill while a COARSE launch datum (error ~4% of range, often 4-6 km)
# misses — exactly the find-then-kill incentive (refine with more buoys).
ASW_SEEKER_BASKET_M = 1_500.0

# Rocket-throw ground speed.  A rocket-boosted ASROC-class round is fast (the
# solid booster lofts the torpedo a long way in tens of seconds); 900 m/s keeps
# the time-of-flight to a launch-box boat (~80-130 km) at ~90-145 s, short
# enough that a FRESH fix on a slow-creeping boat (~few m/s) is still inside the
# basket when the torpedo splashes — a STALE datum on a sprinting EVADE boat
# (8 m/s) outruns it (the find-fast-then-kill incentive, emergent geometry).
ASW_THROW_SPEED_MPS = 900.0   # rocket-throw ground speed toward the fix
ASW_LOFT_FRAC = 0.18          # apogee height == this * throw range (a visible arc)
ASW_MIN_FLIGHT_S = 0.5        # floor so a point-blank shot still has a tick of arc


class AswRound:
    """Player ASW prosecution round (rocket-thrown torpedo).  Constructed at the
    launch point, aimed at the localized FIX (x, z); carries the live target
    Submarine only so the TERMINAL basket check can resolve the kill against
    truth (it does not guide on truth)."""

    # Player-side: excluded from the hostile-vs-base damage sweep (like the
    # friendly Pantsir 57E6).  The class-attr is the contract a test pins.
    is_hostile = False
    is_air = False               # subsurface/ballistic, not a radar air contact

    def __init__(self, launch_pos, fix_xz: Tuple[float, float],
                 fix_quality: float, target_sub=None):
        self.pos = np.asarray(launch_pos, dtype=np.float64).copy()
        self.prev_pos = self.pos.copy()
        self._launch = self.pos.copy()
        self.fix_x = float(fix_xz[0])
        self.fix_z = float(fix_xz[1])
        self.fix_quality = float(fix_quality)
        self._target = target_sub
        self.vel = np.zeros(3, dtype=np.float64)
        self.phase = ASW_THROW
        self.t = 0.0
        self.alive = True
        self.acquired = False
        self.impact_pos = None

        dx = self.fix_x - float(self.pos[0])
        dz = self.fix_z - float(self.pos[2])
        self._throw_range = math.hypot(dx, dz)
        self._flight_time = max(ASW_MIN_FLIGHT_S,
                                self._throw_range / ASW_THROW_SPEED_MPS)
        self._apogee = ASW_LOFT_FRAC * self._throw_range

    @property
    def phase_label(self) -> str:
        return PHASE_LABELS.get(self.phase, "---")

    def velocity(self):
        return self.vel

    def update(self, dt: float, world=None) -> None:
        """Advance the throw; at the fix, run the acoustic basket terminal once.
        ``world`` is accepted (ignored) so the round is duck-type-compatible with
        the missile-list step loop if it is ever flown there."""
        if not self.alive:
            return
        self.prev_pos = self.pos.copy()
        self.t += dt

        if self.phase == ASW_THROW:
            frac = min(1.0, self.t / self._flight_time)
            # Linear ground interpolation toward the fix + a parabolic loft arc.
            x = float(self._launch[0]) + (self.fix_x - float(self._launch[0])) * frac
            z = float(self._launch[2]) + (self.fix_z - float(self._launch[2])) * frac
            y = 4.0 * self._apogee * frac * (1.0 - frac)   # parabola: 0 at ends
            new = np.array([x, y, z], dtype=np.float64)
            self.vel = (new - self.pos) / dt if dt > 0 else np.zeros(3)
            self.pos = new
            if frac >= 1.0:
                self.pos = np.array([self.fix_x, 0.0, self.fix_z],
                                    dtype=np.float64)
                self.phase = ASW_SPLASH

        if self.phase == ASW_SPLASH:
            # Acoustic basket terminal: the kill EMERGES from the fix vs the real
            # boat distance (physics-not-dice).  The round reads truth ONLY here
            # to resolve the basket (it never guided on it).
            self.impact_pos = self.pos.copy()
            if self._target is not None and getattr(self._target, "alive", False):
                d = math.hypot(self.fix_x - float(self._target.pos[0]),
                               self.fix_z - float(self._target.pos[2]))
                if d <= ASW_SEEKER_BASKET_M:
                    self.acquired = True
                    self._target.kill()
            self.phase = ASW_DEAD
            self.alive = False
