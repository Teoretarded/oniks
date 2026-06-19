"""CbrTracker — the player COUNTER-BATTERY / EARLY-WARNING RADAR brain
(pure numpy, GL-free).

M5 #3.  A fixed PLAYER ground radar that:

  (a) catches INBOUND hostile strike tracks EARLY (a TALL mast + a LONG
      missile-class range complement the 18 m surface-search station) and
      publishes a THREAT strip — each entry a time-to-impact (TTI) computed
      from the track's own closure geometry; AND

  (b) BACK-PLOTS the SHOOTER (the launching ship / fighter) using the SHARED
      module-level ``sim.commander.back_plot_surface()`` helper — the SYMMETRIC
      mirror of the enemy commander's trick (sim/commander.process_missile_track)
      — to publish a counter-fire CUE at the believed launch point.

THE CONTRACTS (locked):

  * FOG / NO CHEAT.  The tracker reads ONLY the tracks the CBR's own
    ``Radar.detects()`` passes (range-class gate + 4/3-earth horizon + terrain
    LOS).  A track OVER THE HORIZON or TERRAIN-MASKED yields NO threat and NO
    cue.  Nothing here peeks at a live missile/ship truth pos — the first-seen
    metadata is stamped at the FIRST physical detection (mirror of
    world/combat _cmd_missile_intel), and the cue is an ESTIMATE with error.

  * SHARED HELPER (symmetry).  The shooter back-plot CALLS back_plot_surface()
    directly (``_shooter_xz`` is a thin wrapper) — the enemy commander and the
    player CBR run the SAME math.  No copy / re-derivation.

  * PHYSICS NOT DICE.  The TTI emerges from the track's closure geometry (mirror
    of sim/pantsir.PantsirDefenseController._time_to_impact: dead-reckon the
    track, divide ground distance to the nearest protected structure by the 3-D
    speed).  The cue error is ``det_range * BACKPLOT_ERR_FRAC`` (the same error
    model as the enemy back-plot).  No kill / hit rolls anywhere.  The CBR does
    NOT auto-fire (player agency).

  * DETERMINISM.  The back-plot is deterministic; this tracker adds NO RNG.
    (The reserved fresh child-stream tag is [seed, 9] should noise ever be
    needed — it is not.)

The tracker is platform-agnostic by duck typing: a "track" is anything with
``.pos`` (3,), a velocity (``.velocity()`` or ``.vel``), ``.alive``, and a
stable id (``.aircraft_id`` or ``.track_id``).  ``world/combat.py`` feeds it the
live inbound HOSTILE StrikeMissile / SamMissile(is_hostile) rounds, gated by the
CBR Radar.  Tests feed lightweight synthetic tracks with the same interface.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

from sim.commander import (
    back_plot_surface,
    BACKPLOT_ERR_FRAC,
    BACKPLOT_LOW_ALT_M,
    BACKPLOT_MAX_AGE_S,
)

# --- CBR radar parameters -----------------------------------------------------
# A missile-WARNING set, NOT a surface-search set: a TALL antenna (better horizon
# vs 15-50 m sea-skimmers than the 18 m station) + a LONG 'missile' range, but
# DELIBERATELY SHORT 'ship'/'fighter' ranges so it COMPLEMENTS the 18 m station
# (which covers the sea) instead of replacing it.  It catches the inbound strike
# early; it is not a second area-search radar.
CBR_ANTENNA_M: float = 35.0          # m — tall mast, ~2x the 18 m station tower
CBR_RANGES: dict = {                 # size class -> max detection range (m)
    "missile": 190_000.0,            # LONG missile-warning reach (vs 120 km stn)
    "ship":     40_000.0,            # SHORT — not a surface-search set
    "fighter":  60_000.0,            # SHORT — not an air-search set
    "stealth":  25_000.0,            # reduced SNR for low-observable targets
    # M5 #1 amphibious 'lcac' key: held only at a tiny ring (byte-identical at
    # n_transports=0 — nothing rates 'lcac' until a splash).
    "lcac":     25_000.0,
}


def _vel_of(track) -> np.ndarray:
    """Read a track's 3-D velocity (``.velocity()`` or ``.vel``) as float64."""
    if hasattr(track, "velocity"):
        return np.asarray(track.velocity(), dtype=np.float64)
    return np.asarray(track.vel, dtype=np.float64)


def _id_of(track) -> str:
    """Stable per-round track id.  Prefer an explicit ``.aircraft_id`` /
    ``.track_id`` (StrikeMissile exposes ``aircraft_id``); fall back to the
    Python object identity so rounds WITHOUT a string id (e.g. SamMissile, which
    has neither) each get a DISTINCT key — mirror of world/combat's
    ``key = id(m)`` missile-intel keying.  Without this every id-less interceptor
    would collapse onto a single 'None' track."""
    tid = getattr(track, "aircraft_id", None)
    if tid is None:
        tid = getattr(track, "track_id", None)
    if tid is None:
        return f"obj_{id(track):x}"
    return str(tid)


class CbrTracker:
    """Counter-battery / early-warning tracker for ONE player CBR Radar.

    Each ``step`` consumes the inbound hostile tracks the CBR's Radar.detects()
    physically passes, maintains first-seen metadata per track, and returns::

        {"threats": [{"track_id", "tti", "pos"}, ...],
         "cues":    [{"track_id", "shooter_xz", "error_m"}, ...]}

    ``threats`` is one entry per currently-detected inbound; ``cues`` is one
    per YOUNG, LOW track that back-plots cleanly to a surface launch point (one
    cue per launch event — re-emitted while the launch geometry is still fresh).
    """

    def __init__(self, radar) -> None:
        self.radar = radar
        # track_id -> first-seen metadata (mirror of world/combat
        # _cmd_missile_intel): first_t / first_pos / first_vel / det_pos.
        self._intel: dict[str, dict] = {}
        # track_ids that already produced a cue (one fix per launch event).
        self._cued: set[str] = set()

    # ------------------------------------------------------------------ helpers

    def _shooter_xz(self, first_pos, first_vel) -> Optional[tuple[float, float]]:
        """Back-plot the shooter via the SHARED helper (symmetry seam — the
        enemy commander calls the SAME back_plot_surface())."""
        return back_plot_surface(first_pos, first_vel)

    def _time_to_impact(self, pos, vel, age, structures) -> float:
        """Estimated time for the dead-reckoned track to reach the nearest
        protected structure (mirror of
        sim/pantsir.PantsirDefenseController._time_to_impact).  Infinity if no
        structures, or the track is effectively stationary."""
        if not structures:
            return math.inf
        ex = float(pos[0]) + float(vel[0]) * age
        ez = float(pos[2]) + float(vel[2]) * age
        vx, vy, vz = float(vel[0]), float(vel[1]), float(vel[2])
        speed = math.sqrt(vx * vx + vy * vy + vz * vz)
        if speed < 1.0:
            return math.inf
        best = math.inf
        for s in structures:
            dx = float(s.pos[0]) - ex
            dz = float(s.pos[2]) - ez
            d = math.hypot(dx, dz)
            t = d / speed
            if t < best:
                best = t
        return best

    def _det_range(self, first_pos) -> float:
        """Ground range from the CBR to a first-detection point (the cue error
        scale — the same det_range the enemy back-plot uses)."""
        return math.hypot(
            float(first_pos[0]) - float(self.radar.pos[0]),
            float(first_pos[2]) - float(self.radar.pos[2]),
        )

    # --------------------------------------------------------------------- step

    def step(self, tracks, structures, sim_time: float) -> dict:
        """Consume the inbound hostile tracks the CBR physically detects this
        tick; return {threats, cues}.  FOG: a track the CBR cannot ``detects()``
        (range / horizon / terrain) is invisible — no threat, no cue, no intel
        update (its launch can never be back-plotted from a sensor it produced
        no track on)."""
        threats: list[dict] = []
        cues: list[dict] = []
        live_ids: set[str] = set()

        # The CBR is dead/silent -> it sees nothing this tick (mirror of
        # Radar.detects()'s own alive+emitting gate; checked once so a dead set
        # produces an empty picture even before per-track gating).
        if not (getattr(self.radar, "alive", True)
                and getattr(self.radar, "emitting", True)):
            self._intel.clear()
            self._cued.clear()
            return {"threats": threats, "cues": cues}

        for tr in tracks:
            if not getattr(tr, "alive", True):
                continue
            size = getattr(tr, "radar_size", "missile")
            pos = np.asarray(tr.pos, dtype=np.float64)
            # FOG GATE: read ONLY what the CBR Radar physically detects.
            if not self.radar.detects(pos, size):
                continue
            tid = _id_of(tr)
            live_ids.add(tid)
            vel = _vel_of(tr)

            # First-seen metadata: stamped at the FIRST physical detection only
            # (mirror of world/combat _cmd_missile_intel) — never re-stamped, so
            # the back-plot reads the launch-azimuth velocity, not a turned one.
            rec = self._intel.get(tid)
            if rec is None:
                rec = dict(first_t=float(sim_time),
                           first_pos=pos.copy(),
                           first_vel=vel.copy())
                self._intel[tid] = rec

            # THREAT: TTI from the LIVE dead-reckoned closure geometry (age 0 —
            # pos/vel are this tick's detection; the dead-reckon term is the
            # Pantsir form, kept for signature parity and future coasting).
            tti = self._time_to_impact(pos, vel, 0.0, structures)
            threats.append({
                "track_id": tid,
                "tti": tti,
                "pos": pos.copy(),
            })

            # CUE: back-plot the shooter for a YOUNG, LOW track (the same
            # eligibility the enemy commander uses), once per launch event.
            if tid in self._cued:
                continue
            alt_at_first = float(rec["first_pos"][1])
            track_known_s = float(sim_time) - rec["first_t"]
            if track_known_s > BACKPLOT_MAX_AGE_S:
                continue
            if alt_at_first >= BACKPLOT_LOW_ALT_M:
                continue
            plot = self._shooter_xz(rec["first_pos"], rec["first_vel"])
            if plot is None:
                continue
            det_range = self._det_range(rec["first_pos"])
            cues.append({
                "track_id": tid,
                "shooter_xz": (float(plot[0]), float(plot[1])),
                "error_m": det_range * BACKPLOT_ERR_FRAC,
            })
            self._cued.add(tid)

        # Prune intel/cued state for tracks no longer detected (a coasting /
        # destroyed round drops out — bounded memory, mirror of the commander's
        # missile-track prune).
        self._intel = {k: v for k, v in self._intel.items() if k in live_ids}
        self._cued &= live_ids

        return {"threats": threats, "cues": cues}
