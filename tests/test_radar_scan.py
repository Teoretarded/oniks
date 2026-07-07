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


# --- Task 3: scan-driven ContactBoard refresh ---------------------------------

class _Ship:
    def __init__(self):
        # 25.5 km out with a 15 m superstructure: inside the 20 m-antenna
        # radar horizon (~34 km) — the paint schedule, not the horizon,
        # must be what gates these tests.
        self.pos = np.array([18_000.0, 15.0, 18_000.0])
        self.alive = True
        self.ship_id = "tgt"

    def velocity(self):
        return np.zeros(3)


def _paint_board(radars):
    from sim.contacts import ContactBoard
    from sim.radar import RadarNetwork
    net = RadarNetwork(radars)
    return ContactBoard(
        (0.0, 0.0),
        paint_fn=lambda p, s, now, win: net.paint_state(p, s, now, win))


def _ages(board, ship, t_end=60.0):
    ages, t = [], 0.0
    while t < t_end:
        board.update([ship], 0.1, t)
        tr = board.tracks.get("tgt")
        if tr is not None:
            ages.append(tr["age"])
        t += 0.1
    return ages


def test_track_staleness_follows_scan_not_range_bands():
    # Spec PART 2 §9.4: a target covered ONLY by a 10 s rotator goes stale
    # between paints; add a staring face and it stays fresh. The ship sits
    # 71 km out — the legacy surface range band would refresh every 20 s
    # regardless of any radar's real cadence.
    rot10 = _radar(ScanDef("rotating", 10.0, 2.0, 360.0))
    ages_rot = _ages(_paint_board([rot10]), _Ship())
    ages_star = _ages(_paint_board(
        [_radar(STARING),
         _radar(ScanDef("rotating", 10.0, 2.0, 360.0))]), _Ship())
    assert max(ages_rot) > 8.0        # stale between rotations
    assert max(ages_star) < 1.5       # staring face keeps it fresh


def test_paint_mode_track_drops_when_radar_dies():
    rot = _radar(ScanDef("rotating", 10.0, 2.0, 360.0))
    board = _paint_board([rot])
    ship = _Ship()
    _ages(board, ship, t_end=30.0)                # track formed
    assert "tgt" in board.tracks
    rot.alive = False
    _ages(board, ship, t_end=200.0)               # > TRACK_DROP_S unseen
    assert "tgt" not in board.tracks


# --- Task 4: world wiring ------------------------------------------------------

def test_scanned_mode_wires_paint_fn():
    from world.combat import CombatWorld
    from world.combat_config import CombatConfig
    w = CombatWorld(CombatConfig(radar_model="scanned"))
    assert w.contacts.paint_fn is not None
    assert w.radar_station.scan.kind == "rotating"      # 91N6 acquisition
    assert w.radar_station.band == "S"
    w2 = CombatWorld(CombatConfig())                    # functional default
    assert w2.contacts.paint_fn is None                 # legacy identity
    assert w2.contacts.visible_fn is not None


def test_game_layer_forces_scanned():
    import inspect
    from world.sandbox_world import SANDBOX_CONFIG
    assert SANDBOX_CONFIG.radar_model == "scanned"
    from game.combat_setup import CombatSetupState
    assert '"scanned"' in inspect.getsource(CombatSetupState.build_config)
    from game import campaign
    assert '"scanned"' in inspect.getsource(campaign.next_config)


def test_enemy_awacs_and_fighter_scan_assignments():
    import inspect
    from sim import enemy_air
    # AWACS rotodome rotates; fighter nose is a body-fixed sector.
    assert 'ScanDef("rotating", 10.0' in inspect.getsource(
        enemy_air.Awacs.__init__)
    assert 'ScanDef("sector", 2.0, 3.0, 120.0)' in inspect.getsource(
        enemy_air.FighterRadar.__init__)


def test_fighter_nose_sector_follows_heading():
    # A fighter flying SOUTH cannot paint a target to its NORTH under the
    # scanned model — the AESA field of regard is body-fixed.
    import math as _m
    from sim import enemy_air
    fr = enemy_air.FighterRadar("f_r", np.array([0.0, 8_000.0, 0.0]), 0.0)
    tgt_north = np.array([0.0, 8_000.0, 60_000.0])
    fr._heading_ref = 0.0                       # nose north
    assert fr._radar.next_paint_t(tgt_north, 0.0) < _m.inf
    fr._heading_ref = _m.pi                     # nose south
    assert fr._radar.next_paint_t(tgt_north, 0.0) == _m.inf


def test_legacy_visible_fn_path_untouched():
    # The range-band tables and the visible_fn path must survive verbatim
    # (radar_model="functional" identity).
    import inspect
    from sim import contacts
    src = inspect.getsource(contacts)
    assert "UPDATE_PERIODS" in src
    assert "AIR_UPDATE_PERIODS" in src
    board = contacts.ContactBoard((0.0, 0.0))     # no paint_fn: legacy
    assert board.paint_fn is None
