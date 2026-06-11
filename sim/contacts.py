"""Fuzzy delayed contact picture (pure numpy, GL-free).

The player never sees live positions: the ContactBoard refreshes each track
only periodically (less often the farther from the base) and exposes a
dead-reckoned estimate between refreshes — so launch solutions are made
against stale, drifting contacts, exactly what the terminal seeker / proximity
fuse must correct for.

The board tracks ships AND aircraft on the same update pass (Task S1): air
entities carry ``is_air = True`` (class attribute on Aircraft; ships default
to False via getattr) and refresh on the faster AIR_UPDATE_PERIODS. Track
ids are the entities' own ids (``ship_id`` / ``aircraft_id``). Estimates
dead-reckon the full 3D fix, so air tracks carry altitude. Entities whose
``alive`` property has gone False (sinking/falling) drop after one refresh.
"""

import numpy as np

UPDATE_PERIODS = ((100_000, 20.0), (300_000, 60.0), (1e12, 120.0))     # surface
AIR_UPDATE_PERIODS = ((100_000, 15.0), (300_000, 30.0), (1e12, 60.0))  # air

# both keyed by range from base


class ContactBoard:
    """contact_id -> dict(pos, vel, age, t_next, is_air), per-range refresh."""

    def __init__(self, base_xz):
        self.base_xz = np.asarray(base_xz, dtype=np.float64)
        self.tracks = {}

    def _period(self, pos, is_air):
        rng = float(np.hypot(pos[0] - self.base_xz[0], pos[2] - self.base_xz[1]))
        periods = AIR_UPDATE_PERIODS if is_air else UPDATE_PERIODS
        for max_range, period in periods:
            if rng <= max_range:
                return period
        return periods[-1][1]

    def update(self, entities, dt, sim_time):
        for ent in entities:
            is_air = getattr(ent, "is_air", False)
            cid = ent.aircraft_id if is_air else ent.ship_id
            dead = not ent.alive
            track = self.tracks.get(cid)
            if track is None:
                if dead:
                    continue                      # never seen alive: no track
                self.tracks[cid] = dict(
                    pos=ent.pos.copy(), vel=ent.velocity().copy(),
                    age=0.0, t_next=sim_time + self._period(ent.pos, is_air),
                    is_air=is_air)
            elif sim_time >= track["t_next"]:
                if dead:                          # drops after one refresh cycle
                    del self.tracks[cid]
                    continue
                track["pos"] = ent.pos.copy()
                track["vel"] = ent.velocity().copy()
                track["age"] = 0.0
                track["t_next"] = sim_time + self._period(ent.pos, is_air)
            else:
                track["age"] += dt

    def estimated_pos(self, contact_id, sim_time):
        """Dead-reckoned 3D position: last fix advanced along the last velocity."""
        track = self.tracks[contact_id]
        return track["pos"] + track["vel"] * track["age"]
