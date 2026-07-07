"""R-P0 probe: measure track-age behavior under radar_model scanned vs
functional (run log evidence, not a test).

Boots a CombatWorld in each mode, injects a real inbound Tomahawk at
altitude (world/scenario.py forge) plus reads the enemy-ship surface
tracks, and tabulates per-track age p50/p95 over a fixed window.

Run:  python tools/probe_radar_scan.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from world.combat import CombatWorld
from world.combat_config import CombatConfig
from world.scenario import spawn_inbound, run_until


def _age_samples(radar_model: str, t_end: float = 240.0):
    w = CombatWorld(CombatConfig(radar_model=radar_model))
    # A real strike round released high (JASSM air-drop) so the horizon
    # holds it in view for the whole window (we probe SCAN cadence, not
    # the horizon), inbound on the station from the northern threat axis.
    spawn_inbound(w, kind="jassm", bearing_deg=0.0, range_km=100.0)
    ages = {"missile": [], "ship": []}
    elapsed = {"t": 0.0}
    sample_dt = 0.5

    def _tick(world):
        for tr in world.contacts.tracks.values():
            key = "missile" if tr.get("size") == "missile" else "ship"
            ages[key].append(float(tr["age"]))
        elapsed["t"] += sample_dt
        return elapsed["t"] >= t_end

    run_until(w, _tick, timeout_s=t_end + 5.0, dt=sample_dt)
    return ages


def _stats(xs):
    if not xs:
        return "  (no samples)"
    a = np.asarray(xs)
    return (f"n={len(a):6d}  p50={np.percentile(a, 50):6.2f}s  "
            f"p95={np.percentile(a, 95):6.2f}s  max={a.max():6.2f}s")


def main():
    for model in ("functional", "scanned"):
        print(f"\n=== radar_model = {model} ===")
        try:
            ages = _age_samples(model)
        except Exception as e:  # scenario forge geometry may not apply
            print(f"  PROBE FAILED: {e!r}")
            continue
        for key in ("missile", "ship"):
            print(f"  {key:8s} track age: {_stats(ages[key])}")


if __name__ == "__main__":
    main()
