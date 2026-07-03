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
telemetry, always allowed).  CAUSE attribution is NOT recorded here; the
kill-attribution channel is a separate step (classification/observed
rules apply there).  Nothing in the sim reads this state (render/AAR
layer only — the world digest is untouched).
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
                    "next_t": t + self.period,
                    # Held reference (accuracy contract): the world PRUNES a
                    # dead round from the list within its death step, but the
                    # object's pos freezes at the exact death point — holding
                    # it lets the close-out anchor the TRUE terminal position
                    # instead of the last boundary sample.
                    "_m": m,
                }
                continue
            if rec["death"] is not None:
                continue                      # already closed
            if alive:
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

    # --------------------------------------------------------- read helpers

    def rounds(self) -> list:
        """Records in launch order (pure read for the debrief screen)."""
        return sorted(self.tracks.values(), key=lambda r: r["launch_t"])

    def path_of(self, rec) -> np.ndarray:
        """(N, 4) float64 array of (t, x, y, z) — the 1:1 plot input."""
        return np.asarray(rec["samples"], dtype=np.float64)
