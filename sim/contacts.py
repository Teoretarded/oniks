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

# --- Classification ladder (docs/research/classification_spec.md) ------------
#
# DETECTION was always honest physics; IDENTIFICATION used to be free (a track
# printed its weapon type on frame one).  Type knowledge is now EARNED by
# track dwell, mirroring real recognition doctrine: coarse CLASS from
# kinematics within seconds, TYPE via signature analysis (NCTR: HRR/ISAR/JEM)
# later.  Dwell counts from ``first_seen`` (stamped at track creation) and is
# MONOTONIC — a coasting track keeps what it earned (recorded returns keep
# being analyzed); staleness degrades position QUALITY, never knowledge.
#
# Per-signature (t_class, t_ident) dwell seconds — tuning scaffold, guarded
# by two-sided tests (a ship must classify slower than a missile):
CLASSIFY_DWELL = {
    "missile": (2.0, 6.0),    # fast kinematics self-classify quickly
    "fighter": (3.0, 10.0),
    "stealth": (4.0, 14.0),   # reduced returns: slower to pin down
    "ship":    (5.0, 20.0),   # slow movers reveal type slowly
}
CLASSIFY_DWELL_DEFAULT = (3.0, 10.0)

# Coarse class label per signature class (the CLASSIFIED-stage display).
CLASS_LABELS = {"missile": "MSL", "fighter": "AIR", "stealth": "AIR",
                "ship": "SURF"}

# Cooperative ID (IFF): the player's OWN round kinds squawk — instantly
# identified, the ladder never applies.  Explicit allowlist (an unknown
# future kind must NOT silently read as friendly).
OWN_KINDS = frozenset({"oniks", "zircon", "asbm", "kh31p", "swarm",
                       "s300", "40n6", "9m317", "9m338", "57e6"})

# Platform-type NCTR (2026-07-05, the ladder's THIRD tier): an enemy
# AIRFRAME's platform type (FIGHTER / AWACS / JAMMER) is earned only after
# a LONG signature dwell — the radar must collect enough returns to match
# the airframe's signature, well after "it's an aircraft" (t_ident).
# Two-sided pinned: slower than weapon ident, earnable before the
# TRACK_DROP_S=90 drop.  Ships carry no platform_kind and keep SURF.
PLATFORM_KINDS = frozenset({"fighter", "awacs", "jammer", "drone"})
PLATFORM_IDENT_DWELL = {"fighter": 45.0, "stealth": 60.0}
PLATFORM_IDENT_DEFAULT = 45.0

# Track-quality ladder Q5..Q1 (position quality from staleness age; the
# board drops a track at TRACK_DROP_S=90).  (max_age_exclusive, Q) bands.
QUALITY_BANDS = ((2.0, 5), (10.0, 4), (30.0, 3), (60.0, 2))


def classify(track, sim_time):
    """The classification ladder for one track — pure, fog-honest (reads only
    the track dict + the clock; the stamps themselves were sensor-gated).

    Returns ``(stage, label)``:
      * ("UNKNOWN", "UNK")            dwell < t_class — brg/rng/speed only;
      * ("CLASSIFIED", "MSL"/...)     class earned from kinematics;
      * ("IDENTIFIED", "SM6"/"SURF")  type earned by signature dwell (a
        platform with no weapon kind identifies as its class label).
    Own-kind rounds (IFF) and legacy tracks without a ``first_seen`` stamp
    are IDENTIFIED immediately (cooperative ID / old-fixture back-compat)."""
    kind = track.get("kind")
    size = track.get("size")
    if kind in OWN_KINDS:
        return ("IDENTIFIED", kind.upper())
    first_seen = track.get("first_seen")
    if kind in PLATFORM_KINDS and first_seen is not None:
        # Third tier: the platform TYPE waits for the long NCTR dwell;
        # until then the airframe reads as its class label ("AIR").
        t_plat = PLATFORM_IDENT_DWELL.get(size, PLATFORM_IDENT_DEFAULT)
        if float(sim_time) - float(first_seen) < t_plat:
            kind = None
    type_label = (kind or CLASS_LABELS.get(size, "UNK")).upper()
    if first_seen is None:
        return ("IDENTIFIED", type_label)
    t_class, t_ident = CLASSIFY_DWELL.get(size, CLASSIFY_DWELL_DEFAULT)
    dwell = float(sim_time) - float(first_seen)
    if dwell < t_class:
        return ("UNKNOWN", "UNK")
    if dwell < t_ident:
        return ("CLASSIFIED", CLASS_LABELS.get(size, "UNK"))
    return ("IDENTIFIED", type_label)


def track_quality(track):
    """Position-quality ladder Q5 (fresh paint) .. Q1 (about to drop) from
    the track's staleness age — pure banding, no truth read."""
    age = float(track.get("age", 0.0))
    for max_age, q in QUALITY_BANDS:
        if age < max_age:
            return q
    return 1


def _size_of(ent):
    """Radar size class for the gate AND the track stamp: an explicit
    ``radar_size`` (strike missiles -> 'missile'), else air -> 'fighter',
    surface -> 'ship'. Same provenance the detection gate already uses."""
    return getattr(ent, "radar_size",
                   "fighter" if getattr(ent, "is_air", False) else "ship")


def _kind_of(ent):
    """Type classification for the track stamp: the weapon_id of a round
    (Tomahawk/SM-2/HARM/AIM-9X/...), else the airframe's ``platform_kind``
    (fighter/awacs/jammer — displayed only after the PLATFORM_IDENT_DWELL
    tier), else None for a plain platform (ship). Reads the round's own def
    (``weapon.weapon_id``) or self-named attrs — never truth pos."""
    w = getattr(ent, "weapon", None)
    if w is not None:
        return getattr(w, "weapon_id", None)
    wid = getattr(ent, "weapon_id", None)
    if wid is not None:
        return wid
    return getattr(ent, "platform_kind", None)


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
            # Size class for the radar gate: entities may carry an explicit
            # radar_size (strike missiles: "missile" — sim/strike.py), else
            # air entities rate "fighter" and surface entities "ship".
            seen = bool(self.visible_fn(ent.pos, _size_of(ent)))
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
                    is_air=is_air, kind=_kind_of(ent), size=_size_of(ent),
                    # Classification dwell anchor: when this track FORMED
                    # (spec: type knowledge is earned from here, monotonic).
                    first_seen=sim_time)
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
