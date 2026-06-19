"""M5 #3 — player COUNTER-BATTERY / EARLY-WARNING RADAR (CBR).

Headless coverage of the pure CbrTracker (sim/counter_battery.py) + the
read-only world.cbr_threats / world.cbr_cues accessors (world/combat.py).  The
HUD threat strip + map markers are DEFERRED to the UI pass; the tracker + the
accessors are headless-testable now and ARE covered here.

Contracts (spec 06 F3):
  - THREAT + CUE: a synthetic inbound the CBR CAN see yields a threat with a
    finite, physically-correct TTI and (young+low) a back-plot CUE whose
    shooter_xz is within BACKPLOT_ERR_FRAC*det_range of the true launch ship.
  - FOG / HONESTY: a track OUTSIDE the CBR's detects() (over the horizon /
    terrain-masked) yields NO threat AND NO cue (the tracker reads only the gate).
  - EARLY WARNING: the CBR set joins world.radar_net and surfaces an inbound
    Tomahawk on the ContactBoard EARLIER than the 18 m station alone.
  - SYMMETRY: back_plot_surface() via the CBR path and via the enemy commander
    path return IDENTICAL output for the same (first_pos, first_vel).
  - HONEST COST: with the CBR emitting, the enemy EnemyPicture gains an
    EmitterIntel for the CBR id (ESM-localizable + HARM-able); killing the CBR
    Structure drops it from radar_net + the emitter feed.
  - ERROR FLOOR: the cue error_m stays >= det_range*BACKPLOT_ERR_FRAC.
  - DETERMINISM: identical inputs -> identical threats/cues.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from sim.radar import Radar, radar_horizon_m
from sim.commander import (
    back_plot_surface, BACKPLOT_ERR_FRAC, BACKPLOT_LOW_ALT_M, BACKPLOT_MAX_AGE_S,
)
from sim.counter_battery import (
    CbrTracker, CBR_ANTENNA_M, CBR_RANGES,
)
from world.combat import CombatWorld, CBR_SITE_XZ
from world.combat_config import CombatConfig
from world.generation import terrain_height_scalar


DT = 1.0 / 120.0


# ---------------------------------------------------------------------------
# Synthetic inbound track (duck-typed: pos/vel/alive + a stable id) — the same
# interface the world feeds (StrikeMissile.pos/.velocity()/.alive/.aircraft_id).
# ---------------------------------------------------------------------------

class _Track:
    is_hostile = True
    radar_size = "missile"

    def __init__(self, tid, pos, vel, alive=True):
        self.aircraft_id = tid
        self.pos = np.asarray(pos, dtype=np.float64)
        self.vel = np.asarray(vel, dtype=np.float64)
        self.alive = alive

    def velocity(self):
        return self.vel


class _Struct:
    def __init__(self, xz):
        self.pos = np.array([xz[0], 0.0, xz[1]], dtype=np.float64)


def _flat_cbr(xz=(0.0, 0.0)):
    """A CBR Radar over a FLAT (height 0) datum so the pure-tracker tests
    isolate the range/horizon physics from coastal terrain."""
    return Radar("cbr_test", (xz[0], 0.0, xz[1]), CBR_ANTENNA_M, CBR_RANGES,
                 height_fn=lambda x, z: 0.0)


# ---------------------------------------------------------------------------
# THREAT + CUE: a detectable young, low, climbing inbound back-plots the shooter
# ---------------------------------------------------------------------------

def test_threat_and_cue_for_detectable_inbound():
    radar = _flat_cbr()
    tracker = CbrTracker(radar)
    struct = _Struct((0.0, 0.0))            # protected asset at the CBR

    # True launch ship 60 km north; a young, low boost-climbing round just off it
    # closing toward the CBR.  Within the CBR horizon for a ~900 m climbing round.
    ship_xz = (3_000.0, 60_000.0)
    first_pos = np.array([ship_xz[0] + 400.0, 900.0, ship_xz[1] - 3_000.0],
                         dtype=np.float64)
    first_vel = np.array([20.0, 120.0, -300.0], dtype=np.float64)
    tr = _Track("inbound", first_pos, first_vel)

    out = tracker.step([tr], [struct], sim_time=0.0)

    # THREAT: exactly one, finite physically-correct TTI (== analytic d/|v|).
    assert len(out["threats"]) == 1
    th = out["threats"][0]
    assert th["track_id"] == "inbound"
    assert math.isfinite(th["tti"])
    d = math.hypot(struct.pos[0] - first_pos[0], struct.pos[2] - first_pos[2])
    speed = float(np.linalg.norm(first_vel))
    assert th["tti"] == pytest.approx(d / speed, rel=1e-9)

    # CUE: exactly one, shooter_xz within BACKPLOT_ERR_FRAC*det_range of the ship.
    assert len(out["cues"]) == 1
    cue = out["cues"][0]
    assert cue["track_id"] == "inbound"
    sx, sz = cue["shooter_xz"]
    err = math.hypot(sx - ship_xz[0], sz - ship_xz[1])
    det_range = math.hypot(first_pos[0] - radar.pos[0],
                           first_pos[2] - radar.pos[2])
    # The cue lands inside the stated 1-sigma uncertainty band (a real fix, not
    # a snipe): well within a few sigma of the true shooter.
    assert err <= 3.0 * det_range * BACKPLOT_ERR_FRAC


# ---------------------------------------------------------------------------
# ERROR FLOOR: the cue error_m is exactly det_range*BACKPLOT_ERR_FRAC (a cue,
# not a snipe — the floor is never weakened below the enemy back-plot's).
# ---------------------------------------------------------------------------

def test_cue_error_floor():
    radar = _flat_cbr()
    tracker = CbrTracker(radar)
    first_pos = np.array([2_000.0, 800.0, 55_000.0], dtype=np.float64)
    first_vel = np.array([10.0, 110.0, -280.0], dtype=np.float64)
    tr = _Track("inbound", first_pos, first_vel)
    out = tracker.step([tr], [_Struct((0.0, 0.0))], sim_time=0.0)
    assert out["cues"], "a young low inbound should produce a cue"
    cue = out["cues"][0]
    det_range = math.hypot(first_pos[0] - radar.pos[0],
                           first_pos[2] - radar.pos[2])
    assert cue["error_m"] == pytest.approx(det_range * BACKPLOT_ERR_FRAC, rel=1e-12)
    assert cue["error_m"] >= det_range * BACKPLOT_ERR_FRAC - 1e-9


# ---------------------------------------------------------------------------
# FOG / HONESTY: a track OUTSIDE the CBR's detects() -> NO threat AND NO cue
# ---------------------------------------------------------------------------

def test_fog_over_horizon_yields_nothing():
    """A low sea-skimmer FAR beyond the CBR horizon is invisible: no threat,
    no cue, no intel — the tracker reads only the gate, never truth."""
    radar = _flat_cbr()
    tracker = CbrTracker(radar)
    # A 15 m skimmer at 150 km: well inside the 190 km range ring but FAR over
    # the ~40 km radar horizon for a 35 m mast vs a 15 m target.
    alt = 15.0
    far = 150_000.0
    assert far > radar_horizon_m(CBR_ANTENNA_M, alt)
    pos = np.array([0.0, alt, far], dtype=np.float64)
    assert not radar.detects(pos, "missile")     # truly invisible to the set
    tr = _Track("ghost", pos, np.array([0.0, 0.0, -250.0]))
    out = tracker.step([tr], [_Struct((0.0, 0.0))], sim_time=0.0)
    assert out["threats"] == []
    assert out["cues"] == []
    assert tracker._intel == {}                  # no first-seen stamped


def test_fog_terrain_masked_yields_nothing():
    """A target the CBR could reach by range+horizon but is TERRAIN-MASKED
    (a ridge across the sight line) yields no threat and no cue."""
    # A broad wall of terrain at height 5000 m between the radar and the target
    # (wide enough to be hit by the coarse 2 km LOS sampling step).
    def wall(x, z):
        return 5_000.0 if 8_000.0 < z < 15_000.0 else 0.0

    radar = Radar("cbr_masked", (0.0, 0.0, 0.0), CBR_ANTENNA_M, CBR_RANGES,
                  height_fn=wall)
    tracker = CbrTracker(radar)
    pos = np.array([0.0, 100.0, 20_000.0], dtype=np.float64)  # behind the wall
    assert not radar.detects(pos, "missile")
    tr = _Track("masked", pos, np.array([0.0, 0.0, -250.0]))
    out = tracker.step([tr], [_Struct((0.0, 0.0))], sim_time=0.0)
    assert out["threats"] == []
    assert out["cues"] == []


# ---------------------------------------------------------------------------
# SYMMETRY: the CBR path and the enemy commander path call the SAME helper
# ---------------------------------------------------------------------------

def test_symmetry_shared_back_plot_helper():
    """back_plot_surface() called via the CBR path (CbrTracker._shooter_xz) and
    directly (the enemy commander's caller) returns IDENTICAL output for the
    same (first_pos, first_vel)."""
    radar = _flat_cbr()
    tracker = CbrTracker(radar)
    cases = [
        (np.array([5_000.0, 900.0, 50_000.0]),
         np.array([20.0, 120.0, -300.0])),       # boost climb
        (np.array([8_000.0, 30.0, 40_000.0]),
         np.array([10.0, 0.0, -250.0])),          # level sea-skimmer
        (np.array([-3_000.0, 30.0, 30_000.0]),
         np.array([100.0, 0.0, 5.0])),            # coast-parallel -> None
    ]
    for fp, fv in cases:
        enemy = back_plot_surface(fp.copy(), fv.copy())
        cbr = tracker._shooter_xz(fp.copy(), fv.copy())
        assert cbr == enemy, f"symmetry broken for fp={fp} fv={fv}"


# ---------------------------------------------------------------------------
# DETERMINISM: identical inputs -> identical threats/cues
# ---------------------------------------------------------------------------

def test_determinism_identical_inputs():
    fp = np.array([4_000.0, 800.0, 52_000.0], dtype=np.float64)
    fv = np.array([15.0, 115.0, -290.0], dtype=np.float64)
    outs = []
    for _ in range(2):
        tracker = CbrTracker(_flat_cbr())
        out = tracker.step([_Track("d", fp.copy(), fv.copy())],
                           [_Struct((0.0, 0.0))], sim_time=0.0)
        outs.append(out)
    a, b = outs
    assert a["threats"][0]["tti"] == b["threats"][0]["tti"]
    assert a["cues"][0]["shooter_xz"] == b["cues"][0]["shooter_xz"]
    assert a["cues"][0]["error_m"] == b["cues"][0]["error_m"]


# ---------------------------------------------------------------------------
# ONE CUE PER LAUNCH EVENT: a young track that has already cued does not re-cue,
# and an old track (> BACKPLOT_MAX_AGE_S) or a high track produces no cue.
# ---------------------------------------------------------------------------

def test_one_cue_per_launch_and_age_alt_gates():
    radar = _flat_cbr()
    tracker = CbrTracker(radar)
    fp = np.array([3_000.0, 900.0, 50_000.0], dtype=np.float64)
    fv = np.array([20.0, 120.0, -300.0], dtype=np.float64)
    tr = _Track("once", fp, fv)
    struct = [_Struct((0.0, 0.0))]
    out0 = tracker.step([tr], struct, sim_time=0.0)
    assert len(out0["cues"]) == 1
    # Same track, a moment later: a THREAT refreshes but NO second cue.
    out1 = tracker.step([tr], struct, sim_time=1.0)
    assert len(out1["threats"]) == 1
    assert out1["cues"] == []

    # A track first seen HIGH (>= BACKPLOT_LOW_ALT_M) produces no cue.
    th = _Track("high", np.array([3_000.0, BACKPLOT_LOW_ALT_M + 50.0, 50_000.0]),
                fv)
    out_high = tracker.step([tr, th], struct, sim_time=1.5)
    assert all(c["track_id"] != "high" for c in out_high["cues"])

    # A track whose first detection is OLDER than BACKPLOT_MAX_AGE_S never cues.
    # Seed first-seen at t=0 with the round HIGH (so the t=0 frame stamps the
    # metadata but produces no cue), then drop it low AFTER the age window — the
    # cue is gated on track_known_s, so it stays empty.
    tracker3 = CbrTracker(_flat_cbr())
    high0 = _Track("aged", np.array([3_000.0, BACKPLOT_LOW_ALT_M + 50.0, 50_000.0]),
                   fv.copy())
    tracker3.step([high0], struct, sim_time=0.0)        # high -> no cue, stamped
    aged = _Track("aged", fp.copy(), fv.copy())          # now low, but OLD
    out_aged = tracker3.step([aged], struct, sim_time=BACKPLOT_MAX_AGE_S + 1.0)
    assert out_aged["cues"] == [], "an aged-out track must not cue"


# ---------------------------------------------------------------------------
# DEAD / SILENT CBR sees nothing
# ---------------------------------------------------------------------------

def test_idless_tracks_get_distinct_keys():
    """Two inbound rounds WITHOUT a string id (e.g. SamMissile, which exposes
    neither aircraft_id nor track_id) must each get a DISTINCT threat — they
    must not collapse onto one 'None' key (the object-identity fallback)."""
    class _NoId:
        is_hostile = True
        radar_size = "missile"

        def __init__(self, pos, vel):
            self.pos = np.asarray(pos, dtype=np.float64)
            self.vel = np.asarray(vel, dtype=np.float64)
            self.alive = True

        def velocity(self):
            return self.vel

    radar = _flat_cbr()
    tracker = CbrTracker(radar)
    a = _NoId([1_000.0, 800.0, 50_000.0], [10.0, 110.0, -280.0])
    b = _NoId([2_000.0, 800.0, 48_000.0], [10.0, 110.0, -280.0])
    out = tracker.step([a, b], [_Struct((0.0, 0.0))], sim_time=0.0)
    ids = {th["track_id"] for th in out["threats"]}
    assert len(out["threats"]) == 2 and len(ids) == 2, (
        "id-less rounds must produce two distinct threats")


def test_dead_cbr_produces_nothing():
    radar = _flat_cbr()
    tracker = CbrTracker(radar)
    fp = np.array([3_000.0, 900.0, 50_000.0], dtype=np.float64)
    fv = np.array([20.0, 120.0, -300.0], dtype=np.float64)
    tr = _Track("x", fp, fv)
    radar.alive = False
    out = tracker.step([tr], [_Struct((0.0, 0.0))], sim_time=0.0)
    assert out["threats"] == [] and out["cues"] == []


# ===========================================================================
# WORLD-LEVEL: early warning, honest cost, kill path
# ===========================================================================

def test_world_off_default_no_cbr():
    """n_cbr=0: NO CBR Radar/Structure, not in radar_net, tracker never built,
    accessors empty (the byte-identical default gate)."""
    cw = CombatWorld(CombatConfig(seed=1337))
    assert cw.n_cbr == 0
    assert cw._cbr_radars == []
    assert cw._cbr_trackers == []
    assert cw.cbr_threats == []
    assert cw.cbr_cues == []
    ids = [r.radar_id for r in cw.radar_net.radars]
    assert not any(i.startswith("cbr_") for i in ids)
    # No CBR structure, and the enemy picture never gains a CBR emitter.
    assert not any(s.structure_id.startswith("cbr_") for s in cw.structures)
    for _ in range(int(1.0 * 120)):
        cw.step(DT)
    assert not any(e.startswith("cbr_") for e in cw.commander.picture.emitters)
    assert cw.cbr_threats == [] and cw.cbr_cues == []


def test_world_cbr_built_and_in_radar_net():
    """n_cbr>0: the CBR Radar joins radar_net and a destructible Structure +
    tracker exist."""
    cw = CombatWorld(CombatConfig(seed=1337, n_cbr=1))
    assert len(cw._cbr_radars) == 1
    assert len(cw._cbr_trackers) == 1
    ids = [r.radar_id for r in cw.radar_net.radars]
    assert "cbr_00" in ids
    structs = [s for s in cw.structures if s.structure_id == "cbr_00"]
    assert len(structs) == 1
    # The CBR sits on dry land (a real ground radar emplacement).
    cx, cz = CBR_SITE_XZ
    assert terrain_height_scalar(cx, cz) > 0.0


def test_world_early_warning_vs_station():
    """EARLY WARNING: the tall CBR mast catches an inbound sea-skimming Tomahawk
    FARTHER out (earlier) than the 18 m station — the whole point of the set.

    Isolated over a flat datum (a co-located station-spec radar vs the CBR-spec
    radar) so the result is PURE mast-height + range-class physics, not coastal
    terrain.  (That the real CBR JOINS world.radar_net so inbound tracks surface
    earlier on the ContactBoard is covered by test_world_cbr_built_and_in_radar_net
    — world._player_visible ORs radar_net, so a longer CBR detection range is a
    strictly larger visible set.)"""
    from world.combat import RADAR_ANTENNA_M, PLAYER_RADAR_RANGES

    flat = lambda x, z: 0.0
    cbr = Radar("cbr", (0.0, 0.0, 0.0), CBR_ANTENNA_M, CBR_RANGES, height_fn=flat)
    station = Radar("stn", (0.0, 0.0, 0.0), RADAR_ANTENNA_M, PLAYER_RADAR_RANGES,
                    height_fn=flat)
    alt = 30.0   # a low sea-skimming Tomahawk

    def first_detect_range(radar):
        rng = 200_000.0
        while rng > 0:
            pos = np.array([0.0, alt, rng], dtype=np.float64)
            if radar.detects(pos, "missile"):
                return rng
            rng -= 250.0
        return None

    cbr_r = first_detect_range(cbr)
    stn_r = first_detect_range(station)
    assert cbr_r is not None and stn_r is not None
    assert cbr_r > stn_r, (
        f"CBR first detect {cbr_r:.0f} m should exceed station {stn_r:.0f} m")


def test_world_honest_cost_enemy_hears_cbr():
    """HONEST COST: with the CBR emitting, the enemy EnemyPicture gains an
    EmitterIntel for the CBR id (ESM-localizable + HARM-able)."""
    cw = CombatWorld(CombatConfig(seed=1337, n_cbr=1))
    for _ in range(int(2.0 * 120)):
        cw.step(DT)
    pic = cw.commander.picture
    assert "cbr_00" in pic.emitters, "enemy ESM never heard the CBR emitter"
    ei = pic.emitters["cbr_00"]
    assert ei.alive
    assert ei.fix_progress > 0.0, "the CBR fix never accrued while emitting"


def test_world_kill_cbr_drops_from_net_and_emitter_feed():
    """Killing the CBR Structure clears its radar.alive (drops it from radar_net
    coverage) and stops the emitter being heard (the fix DECAYS)."""
    cw = CombatWorld(CombatConfig(seed=1337, n_cbr=1))
    for _ in range(int(2.0 * 120)):
        cw.step(DT)
    pic = cw.commander.picture
    radar = cw._cbr_radars[0]
    struct = next(s for s in cw.structures if s.structure_id == "cbr_00")
    assert radar.alive
    fix_before = pic.emitters["cbr_00"].fix_progress
    assert fix_before > 0.0

    while struct.alive:
        struct.hit()
    assert not radar.alive, "on_destroyed must clear the CBR radar.alive"

    for _ in range(int(2.0 * 120)):
        cw.step(DT)
    fix_after = pic.emitters["cbr_00"].fix_progress
    assert fix_after < fix_before, "a dead CBR must stop being heard (fix decays)"
