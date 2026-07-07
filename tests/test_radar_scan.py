"""R-P0 radar scan model contracts (plan: radar_scan_seeker_honesty_plan
_2026-07-07.md; spec: weather_system_design_2026-07-07.md PART 2 §9).

ScanDef paint scheduling is CLOSED-FORM (no per-tick sweeping) and pure —
these tests never touch GL or a world.
"""

import math

import numpy as np

from sim.radar import Radar, ScanDef, STARING


def _radar(scan, boresight=0.0, phase0=0.0):
    r = Radar("t", (0.0, 0.0, 0.0), 20.0,
              {"missile": 100_000.0, "ship": 200_000.0,
               "fighter": 150_000.0, "stealth": 30_000.0},
              height_fn=lambda x, z: 0.0, scan=scan, phase0_s=phase0)
    r.boresight_deg = boresight
    return r


def _tgt(bearing_deg, rng_m=50_000.0, alt=5_000.0):
    b = math.radians(bearing_deg)
    return np.array([rng_m * math.sin(b), alt, rng_m * math.cos(b)])


def test_staring_paints_always():
    r = _radar(STARING)
    assert r.painted(_tgt(0.0), now=3.7, window=0.5)
    assert r.next_paint_t(_tgt(123.0), now=3.7) == 3.7


def test_rotating_paints_once_per_period():
    r = _radar(ScanDef("rotating", 10.0, 2.0, 360.0))
    t0 = r.next_paint_t(_tgt(90.0), now=0.0)
    t1 = r.next_paint_t(_tgt(90.0), now=t0 + 0.05)
    assert abs((t1 - t0) - 10.0) < 1e-6
    assert r.painted(_tgt(90.0), now=t0, window=0.5)
    assert not r.painted(_tgt(90.0), now=t0 + 5.0, window=0.5)


def test_rotating_phase_offsets_the_schedule():
    a = _radar(ScanDef("rotating", 10.0, 2.0, 360.0), phase0=0.0)
    b = _radar(ScanDef("rotating", 10.0, 2.0, 360.0), phase0=2.5)
    assert abs(a.next_paint_t(_tgt(0.0), 0.0)
               - b.next_paint_t(_tgt(0.0), 0.0)) > 1.0


def test_sector_radar_blind_outside_sector():
    r = _radar(ScanDef("sector", 2.0, 2.0, 60.0), boresight=0.0)
    assert r.next_paint_t(_tgt(0.0), now=0.0) < 2.0 + 1e-9
    assert r.next_paint_t(_tgt(120.0), now=0.0) == math.inf
    assert not r.painted(_tgt(120.0), now=1.0, window=10.0)


def test_sector_boresight_callable_slews():
    heading = {"deg": 0.0}
    r = _radar(ScanDef("sector", 2.0, 2.0, 60.0))
    r.boresight_deg = lambda: heading["deg"]
    assert r.next_paint_t(_tgt(120.0), now=0.0) == math.inf
    heading["deg"] = 120.0
    assert r.next_paint_t(_tgt(120.0), now=0.0) < 2.0 + 1e-9


def test_detects_unchanged_by_scan_fields():
    # detects() is the INSTANTANEOUS gate — byte-identical legacy behavior:
    # a sector radar's detects() ignores the sector (the paint layer owns it).
    r = _radar(ScanDef("sector", 2.0, 2.0, 60.0), boresight=0.0)
    assert r.detects(_tgt(120.0), "fighter")


# --- Task 2: radar_model flag + RadarNetwork.paint_state ----------------------

def test_radar_model_default_functional():
    from world.combat_config import CombatConfig, clamp_config
    assert CombatConfig().radar_model == "functional"
    assert clamp_config().radar_model == "functional"       # round-trip safe
    assert clamp_config(radar_model="scanned").radar_model == "scanned"
    assert clamp_config(radar_model="typo").radar_model == "scanned"


def test_paint_state_min_over_network():
    from sim.radar import RadarNetwork
    rot = _radar(ScanDef("rotating", 10.0, 2.0, 360.0))
    star = _radar(STARING)
    net = RadarNetwork([rot, star])
    seen, nxt = net.paint_state(_tgt(0.0), "fighter", now=5.0, window=0.5)
    assert seen and nxt == 5.0                    # the staring face wins
    net2 = RadarNetwork([rot])
    seen2, nxt2 = net2.paint_state(_tgt(90.0), "fighter", now=5.0, window=0.5)
    assert nxt2 == rot.next_paint_t(_tgt(90.0), 5.0)


def test_paint_state_dead_radar_contributes_nothing():
    from sim.radar import RadarNetwork
    rot = _radar(ScanDef("rotating", 10.0, 2.0, 360.0))
    rot.alive = False
    net = RadarNetwork([rot])
    assert net.paint_state(_tgt(0.0), "fighter", 0.0, 0.5) == (False, math.inf)
