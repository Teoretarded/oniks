"""Per-round flight-path recorder — the forensics/debrief data source.

ACCURACY CONTRACT (user-locked, 2026-07-03): the debrief plots are drawn
1:1 from REAL recorded state — this recorder stores each player round's
EXACT world-frame position (x, y, z float64) at fixed sim-time sample
boundaries, plus a launch anchor and a death anchor, so the renderer never
interpolates, smooths or guesses.  What the recorder holds IS what flew.

Mechanics
---------
* ``update(world)`` is called once per FIXED sim step (game/combat.py
  sim_step, after world.step) — the sample clock is the sim clock, so the
  recording is frame-rate independent and deterministic (same battle ->
  byte-identical records; no wall clock, no RNG).
* A round is picked up on the first step it appears in ``world.missiles``
  (its launch anchor = its first post-step position) and sampled every
  ``SAMPLE_PERIOD_S`` of sim time from then on.
* Death: the first step the round reads not-alive, a final anchor sample
  + a death record (t, pos) are written.  A round REMOVED from the list
  without an observed dead step is closed at its last known sample
  (honest: the recorder states what it saw, never more).

FOG / SCOPE: OWN rounds only (is_hostile False — the player's own
telemetry, always allowed).  Nothing in the sim reads this state
(render/AAR layer only — the world digest is untouched).

Death-cause channel (handoff spec, 2026-07-03)
----------------------------------------------
Each record closes with ``rec["cause"] = dict(code, detail, observed)``.
Attribution is read from the DEAD round's own attributes: the sim kill
sites stamp ``m.death_cause = (code, detail)`` + ``m.killed_by = killer``
(WRITE-ONLY stamps no sim code ever reads — digest-locked); self causes
(own fuse hit / fuel / impact) come from attributes the round already
carries.  FOG RULE (user-locked, v1 honest): ``observed`` is True only if
the killer was itself a track in ``world.contacts.tracks`` at kill time —
the mid-battle UI names the killer ONLY when observed, else it must show
"LOST - UNCONFIRMED"; self causes are own-force telemetry, always
observed.  A round that vanished with no evidence closes ("lost", False).

Plot extensions: ``target_xz`` (the round's own aim point at pickup, for
the dashed planned-remainder) and ``events`` — (t, phase_label) stamped
whenever the round's own ``phase_label`` changes (pushover/skim/seeker
flags on the debrief sheet).
"""

from __future__ import annotations

import numpy as np

SAMPLE_PERIOD_S = 0.5      # sim seconds between path samples (240 pts / 2 min)


class FlightRecorder:
    """Records (t, x, y, z) paths + fate anchors for the player's rounds."""

    def __init__(self, sample_period: float = SAMPLE_PERIOD_S):
        self.period = float(sample_period)
        # key: id(round) for the round's lifetime (session-scoped).
        # rec: dict(kind, seq, launch_t, samples=[(t,x,y,z)...],
        #           death=None | dict(t, pos), next_t)
        self.tracks: dict = {}
        self._seq_by_kind: dict = {}

    # ------------------------------------------------------------- update

    def update(self, world) -> None:
        """One fixed sim step's worth of recording (call AFTER world.step)."""
        t = float(getattr(world, "sim_time", 0.0))
        seen = set()
        for m in getattr(world, "missiles", ()):
            if getattr(m, "is_hostile", False):
                continue                      # own rounds only
            key = id(m)
            seen.add(key)
            rec = self.tracks.get(key)
            alive = bool(getattr(m, "alive", False))
            if rec is None:
                if not alive:
                    continue                  # never seen alive: not ours to log
                kind = self._kind_of(m)
                seq = self._seq_by_kind.get(kind, 0) + 1
                self._seq_by_kind[kind] = seq
                self.tracks[key] = rec = {
                    "kind": kind, "seq": seq, "launch_t": t,
                    "samples": [self._sample(t, m)], "death": None,
                    "cause": None,
                    # Aim point at pickup (read-only): the dashed planned-
                    # remainder target for a round that died short.
                    "target_xz": self._target_xz(m),
                    "events": [],
                    "next_t": t + self.period,
                    # Held reference (accuracy contract): the world PRUNES a
                    # dead round from the list within its death step, but the
                    # object's pos freezes at the exact death point — holding
                    # it lets the close-out anchor the TRUE terminal position
                    # instead of the last boundary sample.
                    "_m": m,
                    "_label": None,           # last seen phase_label
                }
                self._stamp_phase(rec, t, m)
                continue
            if rec["death"] is not None:
                continue                      # already closed
            if alive:
                self._stamp_phase(rec, t, m)
                # Fixed-boundary sampling: exact post-step state whenever the
                # sim clock has crossed the next boundary (ticks are far
                # smaller than the period, so one sample per crossing).
                if t + 1e-9 >= rec["next_t"]:
                    rec["samples"].append(self._sample(t, m))
                    while rec["next_t"] <= t + 1e-9:
                        rec["next_t"] += self.period
            else:
                # Death anchor: the exact position the round died at.
                rec["samples"].append(self._sample(t, m))
                rec["death"] = {"t": t,
                                "pos": np.asarray(m.pos, dtype=np.float64).copy()}
                rec["cause"] = self._cause_of(m, world)
        # Rounds pruned from the list (the world removes a dead round within
        # its death step): close them at the held object's FROZEN terminal
        # position — the exact death point — stamped at this step's clock
        # (accurate to one fixed tick).
        for key, rec in self.tracks.items():
            if key not in seen and rec["death"] is None:
                m = rec["_m"]
                rec["samples"].append(self._sample(t, m))
                rec["death"] = {"t": t,
                                "pos": np.asarray(m.pos,
                                                  dtype=np.float64).copy()}
                rec["cause"] = self._cause_of(m, world)

    # ------------------------------------------------------------- helpers

    @staticmethod
    def _kind_of(m) -> str:
        w = getattr(m, "weapon", None)
        if w is not None:
            return str(getattr(w, "weapon_id", "round"))
        return str(getattr(m, "weapon_id", "round"))

    @staticmethod
    def _sample(t: float, m) -> tuple:
        p = m.pos
        return (t, float(p[0]), float(p[1]), float(p[2]))

    @staticmethod
    def _target_xz(m):
        """(x, z) of the round's own aim point at pickup, or None (a round
        with no target_point — e.g. a SAM homing on an object)."""
        tp = getattr(m, "target_point", None)
        if tp is None:
            return None
        return (float(tp[0]), float(tp[2]))

    @staticmethod
    def _stamp_phase(rec, t: float, m) -> None:
        """Append (t, phase_label) whenever the round's OWN label changes
        (pushover/skim/terminal event flags for the debrief sheet)."""
        label = getattr(m, "phase_label", None)
        if label is not None and label != rec["_label"]:
            rec["_label"] = label
            rec["events"].append((t, str(label)))

    # ------------------------------------------------------- cause channel

    @staticmethod
    def _killer_observed(killer, world) -> bool:
        """v1 honest fog rule: the killer counts as OBSERVED only if it was
        itself a track in world.contacts.tracks at kill time (checked the
        same fixed step the death is recorded — at most one tick late)."""
        if killer is None:
            return False
        # A LAUNCH-WARNING round (enemy SM-2 / AIM-9X) is injected into the
        # player picture the INSTANT it fires and stays there its whole
        # flight — but its track is dropped the same world.step it dies, so
        # the at-kill-time lookup below ALWAYS missed it and every SAM/A2A
        # kill closed as unobserved.  The player watched that interceptor
        # the entire engagement: it is observed by construction.
        if getattr(killer, "launch_warning", False):
            return True
        kid = getattr(killer, "aircraft_id", None)
        if kid is None:
            kid = getattr(killer, "ship_id", None)
        if kid is None:
            return False
        contacts = getattr(world, "contacts", None)
        tracks = getattr(contacts, "tracks", None)
        return tracks is not None and kid in tracks

    def _cause_of(self, m, world) -> dict:
        """Classify WHY the round died from its OWN attributes (the sim kill
        sites stamp death_cause/killed_by; fuel/impact/own-fuse outcomes are
        state the round already carries).  Never claims more than recorded:
        no evidence at all closes as ('lost', unobserved)."""
        dc = getattr(m, "death_cause", None)
        if dc is not None:
            code, detail = dc
            return {"code": str(code),
                    "detail": None if detail is None else str(detail),
                    "observed": self._killer_observed(
                        getattr(m, "killed_by", None), world)}
        if getattr(m, "killed_target", False) or getattr(m, "acquired", False):
            # Own interceptor/ASW fuse success: own-round telemetry, always
            # observed.  Detail = the victim's weapon kind when named.
            tgt = getattr(m, "target", None)
            if tgt is None:
                tgt = getattr(m, "_target", None)
            detail = None
            if tgt is not None:
                w = getattr(tgt, "weapon", None)
                detail = (getattr(w, "weapon_id", None) if w is not None
                          else getattr(tgt, "weapon_id", None))
                detail = None if detail is None else str(detail)
            return {"code": "hit", "detail": detail, "observed": True}
        if getattr(m, "impact_pos", None) is not None:
            fuel = getattr(m, "fuel", None)
            if fuel is not None and fuel <= 0.0:
                return {"code": "fuel", "detail": None, "observed": True}
            return {"code": "impact", "detail": None, "observed": True}
        return {"code": "lost", "detail": None, "observed": False}

    # --------------------------------------------------------- read helpers

    def rounds(self) -> list:
        """Records in launch order (pure read for the debrief screen)."""
        return sorted(self.tracks.values(), key=lambda r: r["launch_t"])

    def path_of(self, rec) -> np.ndarray:
        """(N, 4) float64 array of (t, x, y, z) — the 1:1 plot input."""
        return np.asarray(rec["samples"], dtype=np.float64)
