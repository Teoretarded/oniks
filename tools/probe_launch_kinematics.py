"""Launch-sequence kinematics probe — every weapon, tick by tick, GL-free.

usage: python -m tools.probe_launch_kinematics [weapon_id ...]

For EVERY weapon in the arsenal (WEAPONS + SAMS + STRIKES) this builds the
round with its REAL spawn recipe, integrates it at the fixed 120 Hz physics
step through its whole launch sequence (30 s), and writes:

  renders/launch/<id>_log.csv        per-substep kinematics
      t, x, y, z, speed, mach, pitch_deg, hdg_deg, turn_rate_dps,
      accel_g, phase
  renders/launch/launch_summary.json per-weapon summary:
      phase transition times/labels, cold-launch ignition height, speed at
      each transition, peak turn rate, peak accel, apex, final state

This is the AI-testable feature from the plan: any agent (or human) can run
this headless, read the CSV/JSON, and judge the launch against
docs/research/launch_sequences_2026-07-05.md — no GPU, no game window.
The two-sided oracles pinned from these measurements live in
tests/test_launch_kinematics.py.
"""

import csv
import json
import math
import os
import sys

import numpy as np

from sim.arsenal import SAMS, STRIKES, WEAPONS
from sim.missile import Missile
from sim.physics import GRAVITY, speed_of_sound_scalar
from sim.sam import SamMissile
from sim.strike import StrikeMissile

DT = 1.0 / 120.0
RECORD_S = 30.0
OUT_DIR = os.path.join("renders", "launch")

# Air-drop release state (the world/scenario.py JASSM recipe).
DROP_ALT_M = 9_000.0
DROP_SPEED = 240.0


class _World:
    """Open-ocean stub (the tests/test_retarget.py pattern)."""
    ships = []

    def terrain_height_at(self, x, z):
        return -50.0


class _AirTarget:
    """Static air target duck-type for SAM shots."""

    def __init__(self, pos):
        self.pos = np.asarray(pos, dtype=np.float64)
        self.alive = True

    def velocity(self):
        return np.zeros(3)


def _build(weapon_id: str):
    """Construct the round with its real spawn recipe (launcher heights and
    release states per world/combat.py + world/scenario.py)."""
    if weapon_id in WEAPONS:
        w = WEAPONS[weapon_id]
        profile = "lo-lo" if weapon_id == "swarm" else "hi-lo"
        return Missile(w, np.array([0.0, 2.0, 0.0]), 0.0, profile,
                       np.array([0.0, 0.0, 200_000.0]))
    if weapon_id in SAMS:
        s = SAMS[weapon_id]
        if weapon_id == "asbm":                      # anti-ship: sea-level aim
            tgt = _AirTarget((0.0, 0.0, 150_000.0))
        elif weapon_id == "pantsir_57e6":            # point defense geometry
            tgt = _AirTarget((0.0, 3_000.0, 12_000.0))
        elif weapon_id.startswith("buk"):
            tgt = _AirTarget((0.0, 6_000.0, 30_000.0))
        else:                                        # area SAM vs mid-alt jet
            tgt = _AirTarget((0.0, 8_000.0, 60_000.0))
        return SamMissile(s, np.array([0.0, 2.0, 0.0]), tgt)
    if weapon_id in STRIKES:
        w = STRIKES[weapon_id]
        if w.booster_thrust > 0.0 and w.eject_speed > 0.0:   # VLS vertical
            pos = np.array([0.0, 2.0, 0.0])
            vel = np.array([0.0, w.eject_speed, 0.0])
        else:                                                # air-drop
            pos = np.array([0.0, DROP_ALT_M, 0.0])
            vel = np.array([0.0, 0.0, DROP_SPEED])
        return StrikeMissile(w, pos, vel, (0.0, 150_000.0))
    raise KeyError(weapon_id)


def launch_record(weapon_id: str, seconds: float = RECORD_S) -> dict:
    """Integrate one launch; return {'id', 'rows', 'summary'} (pure, GL-free).

    rows: list of dicts (the CSV fields). summary: phase transitions with
    time/altitude/speed, cold-launch ignition state, peaks, final state.
    """
    world = _World()
    m = _build(weapon_id)
    rows = []
    transitions = []
    last_phase = None
    prev_h = None
    peak_turn = 0.0
    peak_acc = 0.0
    apex = float(m.pos[1])
    prev_speed = float(np.linalg.norm(m.vel))
    t = 0.0
    steps = int(round(seconds / DT))
    for _ in range(steps):
        m.update(DT, world)
        t += DT
        vx, vy, vz = m.vel.tolist()
        speed = math.sqrt(vx * vx + vy * vy + vz * vz)
        alt = float(m.pos[1])
        apex = max(apex, alt)
        hsp = math.hypot(vx, vz)
        pitch = math.degrees(math.atan2(vy, hsp)) if speed > 1e-9 else 0.0
        hdg = math.degrees(math.atan2(vx, vz))
        turn_dps = 0.0
        if prev_h is not None and speed > 1e-9:
            inv = 1.0 / speed
            c = min(max(prev_h[0] * vx * inv + prev_h[1] * vy * inv
                        + prev_h[2] * vz * inv, -1.0), 1.0)
            turn_dps = math.degrees(math.acos(c)) / DT
        if speed > 1e-9:
            prev_h = (vx / speed, vy / speed, vz / speed)
        acc_g = abs(speed - prev_speed) / DT / GRAVITY
        prev_speed = speed
        phase = m.phase_label
        if phase != last_phase:
            transitions.append({"t": round(t, 4), "phase": phase,
                                "alt_m": round(alt, 2),
                                "speed_ms": round(speed, 2)})
            last_phase = phase
        # Peaks only while alive and past the very first tick (the eject
        # impulse at t=0 is a launch condition, not a maneuver).
        if m.alive and t > 2 * DT:
            peak_turn = max(peak_turn, turn_dps)
            peak_acc = max(peak_acc, acc_g)
        rows.append({"t": round(t, 4), "x": round(float(m.pos[0]), 2),
                     "y": round(alt, 2), "z": round(float(m.pos[2]), 2),
                     "speed": round(speed, 2),
                     "mach": round(speed / speed_of_sound_scalar(alt), 3),
                     "pitch_deg": round(pitch, 2), "hdg_deg": round(hdg, 2),
                     "turn_rate_dps": round(turn_dps, 2),
                     "accel_g": round(acc_g, 2), "phase": phase})
        if not m.alive:
            break
    ignition = None
    for tr in transitions:
        if tr["phase"] in ("BOOST",):        # first powered phase after eject
            ignition = tr
            break
    summary = {
        "weapon_id": weapon_id,
        "transitions": transitions,
        "ignition": ignition,
        "peak_turn_rate_dps": round(peak_turn, 2),
        "peak_axial_accel_g": round(peak_acc, 2),
        "apex_alt_m": round(apex, 2),
        "alive_at_end": bool(m.alive),
        "killed_target": bool(getattr(m, "killed_target", False)),
        "final": rows[-1] if rows else None,
    }
    return {"id": weapon_id, "rows": rows, "summary": summary}


def main(argv) -> int:
    ids = argv or sorted(list(WEAPONS) + list(SAMS) + list(STRIKES))
    os.makedirs(OUT_DIR, exist_ok=True)
    # Merge into the existing summary so a partial re-probe of one weapon
    # never clobbers the rest of the table.
    summaries = {}
    sum_path = os.path.join(OUT_DIR, "launch_summary.json")
    if os.path.exists(sum_path):
        try:
            with open(sum_path, encoding="utf-8") as f:
                summaries = json.load(f)
        except (OSError, ValueError):
            summaries = {}
    for wid in ids:
        rec = launch_record(wid)
        path = os.path.join(OUT_DIR, f"{wid}_log.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, fieldnames=list(rec["rows"][0].keys()))
            wr.writeheader()
            wr.writerows(rec["rows"])
        summaries[wid] = rec["summary"]
        s = rec["summary"]
        seq = " > ".join(tr["phase"] for tr in s["transitions"])
        print(f"{wid:14s} {seq}")
        print(f"{'':14s} peak turn {s['peak_turn_rate_dps']:6.1f} deg/s | "
              f"peak accel {s['peak_axial_accel_g']:5.1f} g | "
              f"apex {s['apex_alt_m']:8.0f} m | "
              f"final {s['final']['speed']:7.1f} m/s "
              f"@ {s['final']['y']:7.0f} m [{s['final']['phase']}]")
    with open(os.path.join(OUT_DIR, "launch_summary.json"), "w",
              encoding="utf-8") as f:
        json.dump(summaries, f, indent=2)
    print(f"\nwrote {OUT_DIR}/<id>_log.csv + launch_summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
