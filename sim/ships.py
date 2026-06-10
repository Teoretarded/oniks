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

import numpy as np

SHIP_TYPES = {  # length, beam, height(above water), speed_mps, hp
    "cargo":   dict(length=180.0, beam=28.0, height=22.0, speed=7.5, hp=2),
    "tanker":  dict(length=240.0, beam=40.0, height=20.0, speed=8.5, hp=3),
    "warship": dict(length=150.0, beam=19.0, height=24.0, speed=13.0, hp=2),
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
HULL_DRAFT = 5.0                  # m of hull below the waterline (OBB extends
                                  #  down to it so waterline strikes register)


class Ship:
    """Lane-following surface ship with damage states and a hull OBB."""

    def __init__(self, ship_id, ship_type, lane_pts, lane_t0, direction=1):
        spec = SHIP_TYPES[ship_type]
        self.ship_id = ship_id
        self.ship_type = ship_type
        self.length = spec["length"]
        self.beam = spec["beam"]
        self.height = spec["height"]
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

    def _advance_waypoint(self):
        wx, wz = self._pts[self._wp]
        dx = wx - self.pos[0]
        dz = wz - self.pos[2]
        dist = float(np.hypot(dx, dz))
        behind = (dx * np.sin(self.heading) + dz * np.cos(self.heading)) < 0.0
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
        self._advance_waypoint()
        wx, wz = self._pts[self._wp]
        bearing = float(np.arctan2(wx - self.pos[0], wz - self.pos[2]))
        err = (bearing - self.heading + np.pi) % (2.0 * np.pi) - np.pi
        self.heading += float(np.clip(err, -TURN_RATE * dt, TURN_RATE * dt))
        self.heading = (self.heading + np.pi) % (2.0 * np.pi) - np.pi
        self.pos[0] += np.sin(self.heading) * speed * dt
        self.pos[2] += np.cos(self.heading) * speed * dt

    # --- hull box for hit tests ----------------------------------------------------

    def obb(self):
        """Hull box: (center(3,), half_extents(3,), rotation3x3 local->world).

        Local frame: +Z forward (bow), +Y up, +X starboard. The box spans the
        full length/beam and from HULL_DRAFT below the waterline up to the
        superstructure height; it rolls with the sinking list.
        """
        ch, sh = np.cos(self.heading), np.sin(self.heading)
        r_head = np.array([[ch, 0.0, sh],
                           [0.0, 1.0, 0.0],
                           [-sh, 0.0, ch]])
        cl, sl = np.cos(self.list_angle), np.sin(self.list_angle)
        r_list = np.array([[cl, -sl, 0.0],
                           [sl, cl, 0.0],
                           [0.0, 0.0, 1.0]])
        rot = r_head @ r_list
        half = np.array([self.beam * 0.5,
                         (self.height + HULL_DRAFT) * 0.5,
                         self.length * 0.5])
        center = self.pos + rot @ np.array([0.0, (self.height - HULL_DRAFT) * 0.5,
                                            0.0])
        return center, half, rot
