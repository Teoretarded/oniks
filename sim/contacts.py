"""Fuzzy delayed contact picture (pure numpy, GL-free).

The player never sees live ship positions: the ContactBoard refreshes each
track only periodically (less often the farther the ship is from the base) and
exposes a dead-reckoned estimate between refreshes — so launch solutions are
made against stale, drifting contacts, exactly what the terminal seeker must
correct for.
"""

import numpy as np

from sim.ships import ST_GONE, ST_SINKING

UPDATE_PERIODS = ((100_000, 20.0), (300_000, 60.0), (1e12, 120.0))  # by range from base


class ContactBoard:
    """ship_id -> dict(pos, vel, age, t_next) refreshed on a per-range period."""

    def __init__(self, base_xz):
        self.base_xz = np.asarray(base_xz, dtype=np.float64)
        self.tracks = {}

    def _period(self, pos):
        rng = float(np.hypot(pos[0] - self.base_xz[0], pos[2] - self.base_xz[1]))
        for max_range, period in UPDATE_PERIODS:
            if rng <= max_range:
                return period
        return UPDATE_PERIODS[-1][1]

    def update(self, ships, dt, sim_time):
        for ship in ships:
            dead = ship.state in (ST_SINKING, ST_GONE)
            track = self.tracks.get(ship.ship_id)
            if track is None:
                if dead:
                    continue                      # never seen alive: no track
                self.tracks[ship.ship_id] = dict(
                    pos=ship.pos.copy(), vel=ship.velocity().copy(),
                    age=0.0, t_next=sim_time + self._period(ship.pos))
            elif sim_time >= track["t_next"]:
                if dead:                          # drops after one refresh cycle
                    del self.tracks[ship.ship_id]
                    continue
                track["pos"] = ship.pos.copy()
                track["vel"] = ship.velocity().copy()
                track["age"] = 0.0
                track["t_next"] = sim_time + self._period(ship.pos)
            else:
                track["age"] += dt

    def estimated_pos(self, ship_id, sim_time):
        """Dead-reckoned position: last fix advanced along the last velocity."""
        track = self.tracks[ship_id]
        return track["pos"] + track["vel"] * track["age"]
