"""Ships: shipping-lane following, kinematics, damage states (pure numpy, GL-free).

A Ship is a hull that follows a lane polyline at its type speed with a
rate-limited rudder, reverses direction at the lane ends, and walks the damage
ladder ALIVE -> BURNING -> SINKING -> GONE (sim/damage.py applies the hits;
this module owns the state timings and the hull OBB used for hit tests).

Axes per locked conventions: X = east, Y = up, Z = north; heading 0 = +Z
(north), increasing clockwise seen from above. Model space forward = +Z
(bow at max Z), so the OBB's local +Z half-extent is length/2. All
simulation state is float64.
"""

import math

import numpy as np

SHIP_TYPES = {  # length, beam, height(above water), speed_mps, hp
    "cargo":      dict(length=180.0, beam=28.0, height=22.0, speed=7.5,  hp=2),
    "tanker":     dict(length=240.0, beam=40.0, height=20.0, speed=8.5,  hp=3),
    "warship":    dict(length=150.0, beam=19.0, height=24.0, speed=13.0, hp=2),
    # Arleigh Burke-class destroyer (combat mode enemy unit, Phase 2).
    # height=30 is mast-top; SPY-1 antenna_m=20 adds 20 m above the waterline
    # so horizon math sees the mast at +20 m. OBB dims come from these three
    # values automatically via Ship (damage.py does not need to be touched).
    "destroyer":  dict(length=155.0, beam=20.0, height=30.0, speed=15.0, hp=3),
}

ST_ALIVE, ST_BURNING, ST_SINKING, ST_GONE = range(4)

# --- Tuning constants ----------------------------------------------------------

TURN_RATE = np.radians(1.2)       # rad/s rudder-limited max heading change
WAYPOINT_RADIUS = 200.0           # m: a lane waypoint counts as reached inside this
WAYPOINT_BEHIND_RADIUS = 2_000.0  # m: ...or once overshot but still this close
                                  # (prevents orbiting a waypoint tighter than the
                                  #  turning circle without skipping far ones)
BURN_SPEED_FRAC = 0.30            # burning ships limp on at 30% of type speed
BURN_TIME = 45.0                  # s of burning before the ship starts sinking
LIST_MAX = np.radians(35.0)       # final list (roll about the keel) while sinking
LIST_RAMP_TIME = 25.0             # s to ramp from 0 to full list
SINK_RATE = 1.2                   # m/s downward while sinking
SINK_GONE_TIME = 60.0             # s of sinking before the wreck is removed
HULL_DRAFT = 5.0                  # legacy/fallback draft for unknown hull types

# Rebuilt meshes use the waterline as model-space y=0.  Keep three vertical
# concepts separate: visible draft, the top of the broad hull collision box,
# and the top used by the subsystem grid.  Tall, narrow fittings are represented
# by compound boxes instead of inflating the whole hull into empty air.
SHIP_DRAFT_BY_TYPE = {
    "cargo": 2.0,
    "tanker": 2.0,
    "warship": 2.0,
    "transport": 2.0,
    "lcac": 1.0,
    "destroyer": 6.0,
    "aaw_destroyer": 6.0,
    "ground_attack_destroyer": 6.0,
    "flagship": 5.0,
    "carrier": 9.0,
}

SHIP_COLLISION_TOP_BY_TYPE = {
    "warship": 7.5,
    "transport": 9.2,
    "lcac": 4.6,
    "flagship": 6.8,
    "carrier": 7.5,
}

SHIP_COLLISION_BEAM_BY_TYPE = {
    "carrier": 40.84,
}

SHIP_DAMAGE_TOP_BY_TYPE = {
    "warship": 28.22,
    "transport": 36.25,
    "lcac": 4.6,
    "destroyer": 39.427433,
    "aaw_destroyer": 39.427433,
    "ground_attack_destroyer": 39.427433,
    "flagship": 28.0,
    "carrier": 48.6,
}

# Additional visible volumes in waterline-relative ship-local coordinates.
# These boxes cover only rebuilt superstructures/fittings above the broad hull.
_EXTRA_LOCAL_HIT_BOXES = {
    "warship": (
        ((0.0, 8.2, 0.0), (9.2, 1.2, 74.0)),
        ((0.0, 11.0, 16.0), (6.6, 4.3, 15.6)),
        ((0.0, 21.7, 10.0), (3.7, 6.6, 3.8)),
        ((0.0, 13.2, -2.0), (2.7, 2.7, 3.8)),
        ((0.0, 10.0, -31.5), (6.7, 3.7, 13.0)),
        ((0.0, 9.0, 58.5), (2.2, 2.0, 7.0)),
    ),
    "transport": (
        ((0.0, 14.7, 28.0), (12.7, 8.7, 29.2)),
        ((0.0, 29.2, 25.0), (3.7, 7.1, 3.7)),
        ((0.0, 28.7, 5.0), (3.7, 6.6, 3.7)),
        ((0.0, 11.3, -21.0), (12.7, 4.2, 14.5)),
    ),
    "flagship": (
        ((0.0, 8.0, 0.0), (8.4, 1.6, 85.0)),
        ((0.0, 11.8, 27.0), (7.0, 5.5, 14.0)),
        ((0.0, 11.5, -28.0), (7.0, 5.3, 12.5)),
        ((0.0, 22.0, 16.0), (4.8, 6.1, 1.5)),
        ((0.0, 20.1, -24.0), (4.5, 5.5, 1.4)),
        ((0.0, 10.4, -1.5), (2.6, 4.1, 10.2)),
        ((0.0, 9.0, 74.0), (2.2, 2.7, 9.0)),
        ((0.0, 9.0, -65.0), (2.2, 2.7, 8.0)),
    ),
}


class Ship:
    """Lane-following surface ship with damage states and a hull OBB."""

    def __init__(self, ship_id, ship_type, lane_pts, lane_t0, direction=1):
        spec = SHIP_TYPES[ship_type]
        self.ship_id = ship_id
        self.ship_type = ship_type
        self.length = spec["length"]
        self.beam = spec["beam"]
        self.height = spec["height"]
        self._configure_type_hit_geometry()
        self.speed = spec["speed"]
        self.hp = spec["hp"]
        self.state = ST_ALIVE
        self.direction = 1 if direction >= 0 else -1
        self.burn_timer = BURN_TIME
        self.sink_elapsed = 0.0
        self.list_angle = 0.0     # rad, roll about the keel while sinking
        # Position interpolated along the lane polyline at fraction lane_t0 of
        # its total arc length; heading along the lane in the travel direction.
        self._pts = np.asarray(lane_pts, dtype=np.float64).reshape(-1, 2)
        self._pts_xz = [(float(p[0]), float(p[1])) for p in self._pts]
        seg = np.diff(self._pts, axis=0)
        seg_len = np.hypot(seg[:, 0], seg[:, 1])
        cum = np.concatenate(([0.0], np.cumsum(seg_len)))
        s = float(np.clip(lane_t0, 0.0, 1.0)) * float(cum[-1])
        i = int(np.clip(np.searchsorted(cum, s, side="right") - 1,
                        0, len(seg_len) - 1))
        f = (s - cum[i]) / seg_len[i] if seg_len[i] > 0.0 else 0.0
        xz = self._pts[i] + seg[i] * f
        self.pos = np.array([xz[0], 0.0, xz[1]], dtype=np.float64)
        d = seg[i] * self.direction
        self.heading = float(np.arctan2(d[0], d[1]))
        self._wp = i + 1 if self.direction == 1 else i
        # Use Ship.hit_obbs explicitly: subclass constructors may not yet have
        # installed their final dimensions, but plain merchant/frigate extras
        # are already valid here. Subclasses recompute after every override.
        self._set_hit_reach(Ship.hit_obbs(self))

    # --- interop properties (missile seeker duck-types these) -------------------

    @property
    def alive(self):
        """Targetable: still afloat enough for the seeker to track."""
        return self.state in (ST_ALIVE, ST_BURNING)

    @property
    def vel(self):
        return self.velocity()

    # --- kinematics --------------------------------------------------------------

    def velocity(self):
        """World-space velocity (3,) float64 for the current state."""
        if self.state == ST_ALIVE:
            sp = self.speed
        elif self.state == ST_BURNING:
            sp = self.speed * BURN_SPEED_FRAC
        elif self.state == ST_SINKING:
            return np.array([0.0, -SINK_RATE, 0.0])
        else:                                   # ST_GONE
            return np.zeros(3)
        return np.array([np.sin(self.heading) * sp, 0.0,
                         np.cos(self.heading) * sp])

    def _advance_waypoint(self, px, pz):
        wx, wz = self._pts_xz[self._wp]
        dx = wx - px
        dz = wz - pz
        dist = math.hypot(dx, dz)
        behind = (dx * math.sin(self.heading)
                  + dz * math.cos(self.heading)) < 0.0
        if dist < WAYPOINT_RADIUS or (behind and dist < WAYPOINT_BEHIND_RADIUS):
            nxt = self._wp + self.direction
            if nxt >= len(self._pts):           # loop lane ends: reverse
                self.direction = -1
                nxt = len(self._pts) - 2
            elif nxt < 0:
                self.direction = 1
                nxt = 1
            self._wp = nxt

    def update(self, dt):
        if self.state == ST_GONE:
            return
        if self.state == ST_SINKING:
            self.sink_elapsed += dt
            self.list_angle = LIST_MAX * min(1.0, self.sink_elapsed / LIST_RAMP_TIME)
            self.pos[1] -= SINK_RATE * dt
            if self.sink_elapsed >= SINK_GONE_TIME:
                self.state = ST_GONE
            return
        if self.state == ST_BURNING:
            self.burn_timer -= dt
            if self.burn_timer <= 0.0:
                self.state = ST_SINKING
                return
        speed = self.speed * (BURN_SPEED_FRAC if self.state == ST_BURNING else 1.0)
        px = float(self.pos[0])                # plain floats: scalar-fast math
        pz = float(self.pos[2])
        self._advance_waypoint(px, pz)
        wx, wz = self._pts_xz[self._wp]
        bearing = math.atan2(wx - px, wz - pz)
        err = (bearing - self.heading + math.pi) % (2.0 * math.pi) - math.pi
        limit = TURN_RATE * dt
        self.heading += min(max(err, -limit), limit)
        self.heading = (self.heading + math.pi) % (2.0 * math.pi) - math.pi
        self.pos[0] = px + math.sin(self.heading) * speed * dt
        self.pos[2] = pz + math.cos(self.heading) * speed * dt

    # --- hull box for hit tests ----------------------------------------------------

    def _configure_type_hit_geometry(self):
        """Install vertical geometry for the current ``ship_type``/dimensions.

        Subclasses which replace their type/dimensions call this once after all
        overrides, followed by :meth:`recompute_hit_reach`.
        """
        ship_type = self.ship_type
        self.draft = SHIP_DRAFT_BY_TYPE.get(ship_type, HULL_DRAFT)
        self.collision_height = SHIP_COLLISION_TOP_BY_TYPE.get(
            ship_type, self.height)
        self.collision_beam = SHIP_COLLISION_BEAM_BY_TYPE.get(
            ship_type, self.beam)
        self.damage_height = SHIP_DAMAGE_TOP_BY_TYPE.get(ship_type, self.height)

    def _rotation(self):
        """Ship-local to world rotation, including the sinking list."""
        ch, sh = np.cos(self.heading), np.sin(self.heading)
        r_head = np.array([[ch, 0.0, sh],
                           [0.0, 1.0, 0.0],
                           [-sh, 0.0, ch]])
        cl, sl = np.cos(self.list_angle), np.sin(self.list_angle)
        r_list = np.array([[cl, -sl, 0.0],
                           [sl, cl, 0.0],
                           [0.0, 0.0, 1.0]])
        return r_head @ r_list

    def obb(self):
        """Hull box: (center(3,), half_extents(3,), rotation3x3 local->world).

        Local frame: +Z forward (bow), +Y up, +X starboard. The box spans the
        full length/beam and from ``self.draft`` below the waterline up to the
        broad collision top; it rolls with the sinking list. Narrow structure
        above that is supplied by :meth:`hit_obbs`.
        """
        rot = self._rotation()
        top = self.collision_height
        half = np.array([self.collision_beam * 0.5,
                         (top + self.draft) * 0.5,
                         self.length * 0.5])
        center = self.pos + rot @ np.array([0.0, (top - self.draft) * 0.5,
                                            0.0])
        return center, half, rot

    def damage_obb(self):
        """Stable local frame for subsystem grids (not a collision volume)."""
        rot = self._rotation()
        top = self.damage_height
        half = np.array([self.beam * 0.5,
                         (top + self.draft) * 0.5,
                         self.length * 0.5])
        center = self.pos + rot @ np.array(
            [0.0, (top - self.draft) * 0.5, 0.0])
        return center, half, rot

    def hit_obbs(self):
        """Return the oriented volumes used by swept weapon hit tests.

        Ordinary ships retain the historical single hull box. Ship classes
        whose visible geometry extends beyond it can override this method with
        a compound set. :meth:`damage_obb` remains the stable ship-local frame
        used by the subsystem damage model.
        """
        hull = self.obb()
        rot = hull[2]
        volumes = [hull]
        for center, half in _EXTRA_LOCAL_HIT_BOXES.get(self.ship_type, ()):
            local_center = np.asarray(center, dtype=np.float64)
            volumes.append((
                self.pos + rot @ local_center,
                np.asarray(half, dtype=np.float64).copy(),
                rot,
            ))
        return tuple(volumes)

    def _set_hit_reach(self, volumes):
        """Set the exact conservative sphere for a supplied OBB collection."""
        farthest = 0.0
        signs = (-1.0, 1.0)
        for center, half, rot in volumes:
            local_center = rot.T @ (center - self.pos)
            for sx in signs:
                for sy in signs:
                    for sz in signs:
                        corner = local_center + half * np.array(
                            [sx, sy, sz], dtype=np.float64)
                        farthest = max(farthest, float(np.linalg.norm(corner)))
        self.hit_reach = farthest

    def recompute_hit_reach(self):
        """Recompute broad-phase reach after type/dimension overrides."""
        self._set_hit_reach(self.hit_obbs())
