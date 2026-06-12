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
With ``visible_fn`` set (COMBAT fog of war) the board additionally gates tracks on radar visibility — see ContactBoard.
"""

import numpy as np

UPDATE_PERIODS = ((100_000, 20.0), (300_000, 60.0), (1e12, 120.0))     # surface
AIR_UPDATE_PERIODS = ((100_000, 15.0), (300_000, 30.0), (1e12, 60.0))  # air

# both keyed by range from base

VIS_CHECK_PERIOD = 0.5    # s between cached visibility re-checks per entity
DETECT_DELAY_S = 2.0      # continuous visibility before a NEW track forms
TRACK_DROP_S = 90.0       # unseen coasting age at which a track drops


class ContactBoard:
    """contact_id -> dict(pos, vel, age, t_next, is_air), per-range refresh."""

    def __init__(self, base_xz, visible_fn=None):
        self.base_xz = np.asarray(base_xz, dtype=np.float64)
        self.tracks = {}
        # COMBAT fog of war: visible_fn(pos, size_class) -> bool gates
        # detection/refresh; None = legacy all-seeing sandbox behavior.
        self.visible_fn = visible_fn
        self._vis = {}    # cid -> dict(t_next, since, seen), cached checks

    def _period(self, pos, is_air):
        rng = float(np.hypot(pos[0] - self.base_xz[0], pos[2] - self.base_xz[1]))
        periods = AIR_UPDATE_PERIODS if is_air else UPDATE_PERIODS
        for max_range, period in periods:
            if rng <= max_range:
                return period
        return periods[-1][1]

    def _seen(self, ent, cid, sim_time):
        """Cached current visibility (re-checked each VIS_CHECK_PERIOD);
        always True when ungated."""
        if self.visible_fn is None:
            return True
        st = self._vis.get(cid)
        if st is None:
            st = self._vis[cid] = dict(t_next=-1.0, since=None, seen=False)
        if sim_time >= st["t_next"]:
            size = "fighter" if getattr(ent, "is_air", False) else "ship"
            seen = bool(self.visible_fn(ent.pos, size))
            if seen and st["since"] is None:
                st["since"] = sim_time
            elif not seen:
                st["since"] = None
            st["seen"] = seen
            st["t_next"] = sim_time + VIS_CHECK_PERIOD
        return st["seen"]

    def _detected(self, ent, cid, sim_time):
        """Seen continuously for DETECT_DELAY_S (instant when ungated)."""
        if not self._seen(ent, cid, sim_time):
            return False
        if self.visible_fn is None:
            return True
        since = self._vis[cid]["since"]
        return since is not None and sim_time - since >= DETECT_DELAY_S

    def _drop(self, cid):
        self.tracks.pop(cid, None)
        self._vis.pop(cid, None)

    def update(self, entities, dt, sim_time):
        for ent in entities:
            is_air = getattr(ent, "is_air", False)
            cid = ent.aircraft_id if is_air else ent.ship_id
            dead = not ent.alive
            track = self.tracks.get(cid)
            if track is None:
                if dead or not self._detected(ent, cid, sim_time):
                    continue                      # never seen alive: no track
                self.tracks[cid] = dict(
                    pos=ent.pos.copy(), vel=ent.velocity().copy(),
                    age=0.0, t_next=sim_time + self._period(ent.pos, is_air),
                    is_air=is_air)
            elif sim_time >= track["t_next"]:
                if dead:                          # drops after one refresh cycle
                    self._drop(cid)
                    continue
                if self._seen(ent, cid, sim_time):
                    track["pos"] = ent.pos.copy()
                    track["vel"] = ent.velocity().copy()
                    track["age"] = 0.0
                    track["t_next"] = sim_time + self._period(ent.pos, is_air)
                else:                             # unseen: coast, retry, drop
                    track["age"] += dt
                    track["t_next"] = sim_time + VIS_CHECK_PERIOD
                    if track["age"] >= TRACK_DROP_S:
                        self._drop(cid)
            else:
                track["age"] += dt

    def estimated_pos(self, contact_id, sim_time):
        """Dead-reckoned 3D position: last fix advanced along the last velocity."""
        track = self.tracks[contact_id]
        return track["pos"] + track["vel"] * track["age"]
