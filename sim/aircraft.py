"""Aircraft: racetrack patrol flight, kill -> spiral descent (pure numpy, GL-free).

An Aircraft mirrors the Ship API shape (``pos``, ``velocity()``, ``alive``,
``state``, ``update(dt)``, plus ``heading``) so the ContactBoard, tactical map
and SAM seeker can duck-type it. It loops a rectangular racetrack derived from
two diagonal anchor corners with a rate-limited turn, deterministic from
construction. ``kill()`` drops it into a falling spiral (roll into a 25 deg
bank, pitch 12 deg down, 60% speed) until water/terrain impact -> AC_GONE.

Hot-loop style per the Task 22 perf pass: per-step math is plain-float
``math`` calls (no numpy scalar dispatch); terrain is queried only below
TERRAIN_MAX_HEIGHT via the scalar fast path. Axes per locked conventions:
X = east, Y = up (altitude), Z = north; heading 0 = +Z, clockwise from above.
"""

import math

import numpy as np

from sim.physics import GRAVITY
from world.generation import TERRAIN_MAX_HEIGHT, terrain_height_scalar

AIRCRAFT_TYPES = {  # length, wingspan, speed_mps, patrol altitude, hp
    "patrol": dict(length=30.0, wingspan=35.0, speed=170.0, alt=6500.0, hp=1),
    "fast":   dict(length=20.0, wingspan=14.0, speed=240.0, alt=4000.0, hp=1),
}

AC_ALIVE, AC_FALLING, AC_GONE = range(3)

# --- Tuning constants ----------------------------------------------------------

TURN_RATE = math.radians(1.5)     # rad/s max heading change on the racetrack
FALL_BANK = math.radians(25.0)    # spiral bank angle once fully rolled in
FALL_PITCH = math.radians(12.0)   # spiral nose-down pitch (stored negative)
FALL_SPEED_FRAC = 0.60            # falling speed as a fraction of type speed
FALL_TRANSITION = 2.5             # s to roll/pitch into the spiral after the kill
FALL_MIN_SPEED = 1.0              # m/s floor for the banked-turn-rate division


class Aircraft:
    """Racetrack patrol aircraft with a kill -> falling-spiral -> gone ladder.

    The two anchors are opposite corners of the racetrack rectangle; the
    aircraft loops its four corners clockwise (seen from above), starting at
    the (min x, min z) corner. Switching to the next corner one turn radius
    early keeps the whole turn inside the rectangle, so the flown track never
    leaves the anchors' bbox (tests allow + 5 km of slack).
    """

    is_air = True   # ContactBoard duck-typing flag (ships default to False)

    def __init__(self, aircraft_id, aircraft_type, anchor_a, anchor_b):
        spec = AIRCRAFT_TYPES[aircraft_type]
        self.aircraft_id = aircraft_id
        self.aircraft_type = aircraft_type
        self.length = spec["length"]
        self.wingspan = spec["wingspan"]
        self.speed = spec["speed"]
        self.alt = spec["alt"]
        self.hp = spec["hp"]
        self.state = AC_ALIVE
        self.roll = 0.0           # rad, + = right wing down (render + spiral)
        self.pitch = 0.0          # rad, + = nose up (negative while falling)
        self.impact_pos = None    # set at the FALLING -> GONE surface impact
        self._fall_t = 0.0

        ax, az = float(anchor_a[0]), float(anchor_a[1])
        bx, bz = float(anchor_b[0]), float(anchor_b[1])
        x0, x1 = min(ax, bx), max(ax, bx)
        z0, z1 = min(az, bz), max(az, bz)
        self._corners = ((x0, z0), (x0, z1), (x1, z1), (x1, z0))
        self._wp = 1              # start at corner 0 flying its first leg
        # Turning at TURN_RATE carves a circle of exactly this radius; the
        # corner switch happens this early so the turn stays inside the bbox.
        self.turn_radius = self.speed / TURN_RATE
        self.pos = np.array([x0, self.alt, z0], dtype=np.float64)
        wx, wz = self._corners[self._wp]
        self.heading = math.atan2(wx - x0, wz - z0)   # along the first leg

    # --- interop properties (board/seeker duck-type these, like Ship) ----------

    @property
    def alive(self):
        """Targetable / trackable: still in controlled flight."""
        return self.state == AC_ALIVE

    @property
    def vel(self):
        return self.velocity()

    # --- kinematics --------------------------------------------------------------

    def _fall_speed(self):
        """Current spiral speed: type speed easing to 60% over the roll-in."""
        frac = min(1.0, self._fall_t / FALL_TRANSITION)
        return self.speed * (1.0 - (1.0 - FALL_SPEED_FRAC) * frac)

    def velocity(self):
        """World-space velocity (3,) float64 for the current state."""
        if self.state == AC_ALIVE:
            sp = self.speed
            return np.array([math.sin(self.heading) * sp, 0.0,
                             math.cos(self.heading) * sp])
        if self.state == AC_FALLING:
            sp = self._fall_speed()
            hs = sp * math.cos(self.pitch)
            return np.array([math.sin(self.heading) * hs,
                             sp * math.sin(self.pitch),
                             math.cos(self.heading) * hs])
        return np.zeros(3)        # AC_GONE

    def _advance_waypoint(self):
        wx, wz = self._corners[self._wp]
        dx = wx - self.pos[0]
        dz = wz - self.pos[2]
        dist = math.hypot(dx, dz)
        behind = (dx * math.sin(self.heading)
                  + dz * math.cos(self.heading)) < 0.0
        if dist < self.turn_radius or (behind and dist < 2.0 * self.turn_radius):
            self._wp = (self._wp + 1) % 4

    def update(self, dt):
        if self.state == AC_GONE:
            return
        if self.state == AC_FALLING:
            self._update_falling(dt)
            return
        self._advance_waypoint()
        wx, wz = self._corners[self._wp]
        bearing = math.atan2(wx - self.pos[0], wz - self.pos[2])
        err = (bearing - self.heading + math.pi) % (2.0 * math.pi) - math.pi
        limit = TURN_RATE * dt
        self.heading += min(max(err, -limit), limit)
        self.heading = (self.heading + math.pi) % (2.0 * math.pi) - math.pi
        self.pos[0] += math.sin(self.heading) * self.speed * dt
        self.pos[2] += math.cos(self.heading) * self.speed * dt

    def _update_falling(self, dt):
        """Spiral descent: ramp into the bank/pitch, turn at the banked-turn
        rate (g*tan(bank)/speed), sink along the pitched velocity vector, and
        die on the surface (terrain queried only below the world ceiling)."""
        self._fall_t += dt
        frac = min(1.0, self._fall_t / FALL_TRANSITION)
        self.roll = FALL_BANK * frac
        self.pitch = -FALL_PITCH * frac
        sp = self._fall_speed()
        omega = GRAVITY * math.tan(self.roll) / max(sp, FALL_MIN_SPEED)
        self.heading = (self.heading + omega * dt + math.pi) % (2.0 * math.pi) - math.pi
        hs = sp * math.cos(self.pitch)
        px = self.pos[0] + math.sin(self.heading) * hs * dt
        py = self.pos[1] + sp * math.sin(self.pitch) * dt
        pz = self.pos[2] + math.cos(self.heading) * hs * dt
        self.pos[0] = px
        self.pos[1] = py
        self.pos[2] = pz
        if py > TERRAIN_MAX_HEIGHT:
            return
        surface = max(terrain_height_scalar(px, pz), 0.0)
        if py <= surface:
            self.pos[1] = surface
            self.impact_pos = self.pos.copy()
            self.state = AC_GONE

    # --- damage ---------------------------------------------------------------------

    def kill(self):
        """A hit (hp 1): controlled flight ends, the falling spiral begins.
        The SAM proximity fuse calls this (Task S2); no-op unless AC_ALIVE."""
        if self.state != AC_ALIVE:
            return
        self.hp -= 1
        if self.hp <= 0:
            self.state = AC_FALLING
            self._fall_t = 0.0
