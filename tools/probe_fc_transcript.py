"""Probe: transcribe HOW a missile's flight computer THINKS, replan by replan.

usage: python -m tools.probe_fc_transcript [weapon] [profile] [range_km]
       (defaults: oniks hi-lo 250)   weapons: oniks | zircon

Purpose (AI-testability, 2026-07-17): an AI session must be able to judge
whether the online flight computer is choosing GOOD paths without booting
the game.  This probe flies a REAL sim.missile.Missile headless, turns on
the flight computer's debug snapshots, and writes one JSON line per replan:

    {"t": ..., "plan": N, "phase": "CRUISE", "mach": ..., "fuel_kg": ...,
     "alt_m": ..., "selected": "preferred", "gamma_deg": ...,
     "candidates": [{"name", "feasible", "cost", "terminal_speed",
                     "terminal_fuel", "clearance_m"}, ...]}

so the WHOLE candidate ladder the computer considered — and what it chose —
is inspectable after the fact.  The final summary grades the flight against
physics bounds no plan can beat:

  * ideal time  = route length / cruise speed at the hi cruise altitude
    (boost/climb overhead makes >1.0 normal; large ratios flag wallowing);
  * arrival speed vs the weapon's terminal band;
  * corridor switch count (chatter) and infeasible-replan fraction.

Output: prints the summary; writes renders/fc_transcript_<weapon>.jsonl.
Measurement tool, exit 0 always.
"""

from __future__ import annotations

import json
import math
import os
import sys

import numpy as np

from sim.arsenal import ONIKS, ZIRCON
from sim.missile import Missile
from sim.physics import speed_of_sound_scalar

DT = 1.0 / 120.0
OUT_DIR = "renders"


class _World:
    """Flat open sea (the probe_energy_bleed stub)."""

    ships = []

    def terrain_height_at(self, x, z):
        return -50.0

    def surface_height_at(self, x, z):
        return 0.0


def run(weapon_id: str, profile: str, range_km: float) -> dict:
    weapon = {"oniks": ONIKS, "zircon": ZIRCON}[weapon_id]
    world = _World()
    target = np.array([0.0, 0.0, range_km * 1_000.0])
    m = Missile(weapon, np.zeros(3), 0.0, profile, target)
    m._fc.set_debug_enabled(True)

    rows = []
    last_plan = -1
    switches = 0
    infeasible = 0
    last_selected = None
    while m.alive and m.t < 1_800.0:
        m.update(DT, world)
        snap = m._fc.debug_snapshot
        if snap is not None and snap.plan_id != last_plan:
            last_plan = snap.plan_id
            if last_selected is not None and snap.selected != last_selected:
                switches += 1
            last_selected = snap.selected
            chosen = next((c for c in snap.candidates if c.selected), None)
            if chosen is not None and not chosen.feasible:
                infeasible += 1
            speed = float(np.linalg.norm(m.vel))
            rows.append({
                "t": round(m.t, 2), "plan": snap.plan_id,
                "phase": m.phase_label,
                "alt_m": round(float(m.pos[1]), 1),
                "mach": round(speed / speed_of_sound_scalar(
                    float(m.pos[1])), 3),
                "fuel_kg": round(float(m.fuel), 1),
                "range_to_go_m": round(snap.route_range_m, 0),
                "selected": snap.selected,
                "gamma_deg": round(math.degrees(snap.gamma_command_rad), 2),
                "path_accel": round(snap.path_accel_mps2, 2),
                "candidates": [{
                    "name": c.name, "feasible": c.feasible,
                    "cost": round(c.cost, 2),
                    "terminal_speed": round(c.terminal_speed_mps, 1),
                    "terminal_fuel": round(c.terminal_fuel_kg, 1),
                    "clearance_m": round(c.min_clearance_m, 1),
                } for c in snap.candidates],
            })

    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"fc_transcript_{weapon_id}.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    # --- grading ------------------------------------------------------------
    dist = range_km * 1_000.0
    cruise_speed = weapon.cruise_mach_hi * speed_of_sound_scalar(
        weapon.cruise_alt_hi if profile == "hi-lo" else weapon.lo_alt)
    ideal_t = dist / cruise_speed
    arrive_speed = float(np.linalg.norm(m.vel))
    hit = (m.impact_pos is not None and math.hypot(
        float(m.impact_pos[0]) - target[0],
        float(m.impact_pos[2]) - target[2]) < 200.0)
    summary = {
        "weapon": weapon_id, "profile": profile, "range_km": range_km,
        "outcome": "reached target area" if hit else
                   ("died at " + str(np.round(m.impact_pos, 0).tolist())
                    if m.impact_pos is not None else "timed out"),
        "time_of_flight_s": round(m.t, 1),
        "ideal_time_s": round(ideal_t, 1),
        "time_ratio": round(m.t / ideal_t, 3),
        "arrival_speed_mps": round(arrive_speed, 1),
        "fuel_left_kg": round(float(m.fuel), 1),
        "replans": last_plan, "corridor_switches": switches,
        "infeasible_replans": infeasible,
        "transcript": os.path.abspath(path),
    }
    return summary


if __name__ == "__main__":
    args = sys.argv[1:]
    weapon_id = args[0] if len(args) > 0 else "oniks"
    profile = args[1] if len(args) > 1 else "hi-lo"
    range_km = float(args[2]) if len(args) > 2 else 250.0
    summary = run(weapon_id, profile, range_km)
    print("=== flight-computer transcript probe ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
