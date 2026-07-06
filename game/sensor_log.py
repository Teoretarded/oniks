"""Raw receiver-event recorder — the forensics panes' LIVE sensor feed.

Approved design round (proto_panels, 2026-07-06): the SENSOR RECORD
micro-ledger and the SENSORS plot board both display RAW RECEIVER RECORDS.
This module is their data source: a pure observer, updated once per fixed
sim step (game/combat.py sim_step, after world.step), that watches the
PLAYER PICTURE stores and appends an event whenever one of them changes:

  * ``world.contacts.tracks``   -> lane "radar" (TRACK FORMED / cadence-
    capped TRACK REFRESH / TRACK DROPPED) — or lane "lwarn" when the track
    arrived through the launch-warning channel (the round's own
    ``launch_warning`` flag: the SENSOR MODEL's ungated-RWR bypass, looked
    up by aircraft_id; the event's position is still the TRACK's belief).
  * ``world.emitter_contacts``  -> lane "elint" (EMITTER HEARD / capped
    RE-HEARD) with the triangulated est-pos belief.
  * ``world.sub_contacts``      -> lane "acoustic" (ACOUSTIC FIX / LAUNCH
    DATUM) with the fix quality (the uncertainty ring radius).

FOG BY CONSTRUCTION: every position stored here is the belief the picture
already holds — truth is never read (the only truth-adjacent read is the
launch_warning CHANNEL flag, which is itself part of the sensor pipeline).
Nothing in the sim reads this state (render/AAR layer only — the world
digest is untouched).  Deterministic: sim-clock driven, no wall clock, no
RNG; a ring buffer caps memory.

GL-free — unit-tested headless (tests/test_sensor_log.py).
"""

from __future__ import annotations

from collections import deque

LOG_CAP = 600                  # ring-buffer event cap
REFRESH_LOG_PERIOD_S = 30.0    # min sim seconds between REFRESH/RE-HEARD
                               # rows per contact (the strip logs cadence,
                               # not every sweep)


class SensorLog:
    """Append-only raw receiver events (see module docstring).

    Event shape: dict(t, lane, label, ref, pos=(x, z) | None,
    quality=float | None) — pos/quality are the PICTURE's belief values.
    """

    def __init__(self):
        self.events: deque = deque(maxlen=LOG_CAP)
        # Per-store bookkeeping (ids seen + last logged/heard clocks +
        # last known belief pos for the DROPPED row).
        self._trk_seen: dict = {}      # cid -> dict(last_log, pos, lane)
        self._em_seen: dict = {}       # eid -> dict(last_log, last_heard)
        self._sub_seen: dict = {}      # cid -> last_heard

    # -------------------------------------------------------------- write

    def _emit(self, t, lane, label, ref, pos=None, quality=None) -> None:
        self.events.append({"t": float(t), "lane": lane, "label": label,
                            "ref": str(ref), "pos": pos,
                            "quality": quality})

    # ------------------------------------------------------------- update

    def update(self, world) -> None:
        """One fixed sim step's worth of observation (AFTER world.step)."""
        t = float(getattr(world, "sim_time", 0.0))
        self._watch_tracks(world, t)
        self._watch_emitters(world, t)
        self._watch_subs(world, t)

    # ------------------------------------------------------------- tracks

    @staticmethod
    def _lwarn_channel(world, cid) -> bool:
        """True when the track's entity rode the launch-warning bypass (the
        sensor pipeline's own channel flag — never a truth position)."""
        for m in getattr(world, "missiles", ()):
            if getattr(m, "aircraft_id", None) == cid:
                return bool(getattr(m, "launch_warning", False))
        return False

    def _watch_tracks(self, world, t) -> None:
        contacts = getattr(world, "contacts", None)
        tracks = getattr(contacts, "tracks", None)
        if tracks is None:
            tracks = {}
        for cid, trk in tracks.items():
            pos = trk.get("pos")
            xz = (float(pos[0]), float(pos[2])) if pos is not None else None
            st = self._trk_seen.get(cid)
            if st is None:
                lane = ("lwarn" if self._lwarn_channel(world, cid)
                        else "radar")
                label = "LAUNCH CUE" if lane == "lwarn" else "TRACK FORMED"
                self._trk_seen[cid] = {"last_log": t, "pos": xz,
                                       "lane": lane}
                self._emit(t, lane, label, cid, xz)
                continue
            st["pos"] = xz
            # A refresh resets track age to 0; log it on the strip cadence.
            if (trk.get("age", 1.0) == 0.0
                    and t - st["last_log"] >= REFRESH_LOG_PERIOD_S):
                st["last_log"] = t
                self._emit(t, st["lane"], "TRACK REFRESH", cid, xz)
        for cid in [c for c in self._trk_seen if c not in tracks]:
            st = self._trk_seen.pop(cid)
            self._emit(t, st["lane"], "TRACK DROPPED", cid, st["pos"])

    # ------------------------------------------------------------ emitters

    def _watch_emitters(self, world, t) -> None:
        emitters = getattr(world, "emitter_contacts", None) or {}
        for eid, fix in emitters.items():
            pos = fix.get("pos")
            xz = (float(pos[0]), float(pos[2])) if pos is not None else None
            heard = float(fix.get("last_heard", t))
            st = self._em_seen.get(eid)
            if st is None:
                self._em_seen[eid] = {"last_log": t, "last_heard": heard}
                self._emit(t, "elint", "EMITTER HEARD", eid, xz,
                           quality=fix.get("quality"))
                continue
            if (heard > st["last_heard"]
                    and t - st["last_log"] >= REFRESH_LOG_PERIOD_S):
                st["last_log"] = t
                st["last_heard"] = heard
                self._emit(t, "elint", "RE-HEARD", eid, xz,
                           quality=fix.get("quality"))
            elif heard > st["last_heard"]:
                st["last_heard"] = heard
        # A faded fix simply stops re-hearing: silence is honest, no event.
        for eid in [e for e in self._em_seen if e not in emitters]:
            del self._em_seen[eid]

    # ---------------------------------------------------------------- subs

    def _watch_subs(self, world, t) -> None:
        subs = getattr(world, "sub_contacts", None) or {}
        for cid, fix in subs.items():
            pos = fix.get("pos")
            xz = (float(pos[0]), float(pos[2])) if pos is not None else None
            heard = float(fix.get("last_heard", t))
            st = self._sub_seen.get(cid)
            if st is None:
                self._sub_seen[cid] = {"last_log": t, "last_heard": heard}
                label = ("LAUNCH DATUM" if fix.get("kind") == "datum"
                         else "ACOUSTIC FIX")
                self._emit(t, "acoustic", label, cid, xz,
                           quality=fix.get("quality"))
                continue
            if heard > st["last_heard"]:
                st["last_heard"] = heard
                # A held boat re-fixes every few seconds: strip cadence cap
                # (same rule as radar refresh / ELINT re-heard).
                if t - st["last_log"] >= REFRESH_LOG_PERIOD_S:
                    st["last_log"] = t
                    label = ("LAUNCH DATUM" if fix.get("kind") == "datum"
                             else "ACOUSTIC FIX")
                    self._emit(t, "acoustic", label, cid, xz,
                               quality=fix.get("quality"))
        for cid in [c for c in self._sub_seen if c not in subs]:
            del self._sub_seen[cid]

    # --------------------------------------------------------------- reads

    def events_between(self, t0: float, t1: float) -> list:
        """Events with t0 <= t <= t1, oldest first (pure read)."""
        return [e for e in self.events if t0 <= e["t"] <= t1]

    def latest(self, n: int) -> list:
        """The newest ``n`` events, newest FIRST (the feed order)."""
        evs = list(self.events)
        return evs[::-1][:n]
