"""AFTER-ACTION SCORING (M6) — pure ScoreCard + grade + per-seed PAR.

Headless: game/scoring.py is GL-free and reads a duck-typed fake world +
telemetry dict, so the whole feature is unit-testable without a window.  The
CombatEndOverlay stats-block test uses the same FakeApp/headless input pattern
as tests/test_combat_setup.py.

Contracts under test (spec 07 §AFTER-ACTION SCORING test contracts):
  (a) compute_par(seed, config) deterministic (same args -> identical) AND
      different seeds -> different par;
  (b) a fabricated 'perfect' world+telemetry grades S; a 'bad' one grades D;
  (c) was_back_plotted reads picture.clusters correctly (targetable -> YES);
  (d) leak_rate + efficiency from telemetry counters match hand-computed values;
  (e) CombatEndOverlay WITH a ScoreCard renders headless without crashing and
      exposes the metrics for assertion;
  (f) the None-scorecard path (smoke / legacy) still works.

NON-NEGOTIABLE: end-of-battle kill tallies MAY read truth (the AAR is
omniscient by design); every IN-BATTLE signal (first_fix_t, was_back_plotted)
is fog-honest — first-fix comes from the player contact picture, back-plot
from the ENEMY belief (already sensor-derived).
"""

import numpy as np
import pytest

from game.scoring import (
    ScoreCard, compute_par, compute_scorecard, grade, new_telemetry,
    picture_has_actionable_contact,
)
from world.combat_config import CombatConfig


# --------------------------------------------------------------- fake world

class _FakeShip:
    def __init__(self, alive):
        self._alive = alive

    @property
    def alive(self):
        return self._alive


class _FakeStruct:
    def __init__(self, kind, alive):
        self.kind = kind
        self.alive = alive


class _FakeCluster:
    def __init__(self, targetable):
        self.targetable = targetable


class _FakePicture:
    def __init__(self, clusters):
        self.clusters = clusters


class _FakeCommander:
    def __init__(self, clusters):
        self.picture = _FakePicture(clusters)


class _FakeWorld:
    """Duck-typed end-state world: only the fields scoring reads."""

    def __init__(self, ships, structures, enemy_radars, airfield_alive,
                 clusters, victorious=False, defeated=False):
        self.ships = ships
        self.structures = structures
        self.enemy_radars = enemy_radars      # list of (struct, radar)
        self.airfield = _FakeStruct("airfield", airfield_alive)
        self.commander = _FakeCommander(clusters)
        self.victorious = victorious
        self.defeated = defeated


def _perfect_world():
    """All enemy dead, every player structure intact, no targetable cluster."""
    return _FakeWorld(
        ships=[_FakeShip(False), _FakeShip(False), _FakeShip(False)],
        structures=[_FakeStruct("bastion_tel", True),
                    _FakeStruct("s300_tel", True),
                    _FakeStruct("radar_station", True)],
        enemy_radars=[(_FakeStruct("radar_station", False), None),
                      (_FakeStruct("radar_station", False), None)],
        airfield_alive=False,
        clusters=[],                          # never back-plotted
        victorious=True)


def _bad_world():
    """Base destroyed, back-plotted, enemy mostly alive."""
    return _FakeWorld(
        ships=[_FakeShip(True), _FakeShip(True), _FakeShip(True)],
        structures=[_FakeStruct("bastion_tel", False),
                    _FakeStruct("s300_tel", False),
                    _FakeStruct("radar_station", False)],
        enemy_radars=[(_FakeStruct("radar_station", True), None),
                      (_FakeStruct("radar_station", True), None)],
        airfield_alive=True,
        clusters=[_FakeCluster(True)],        # confirmed back-plot
        defeated=True)


# --------------------------------------------------------- (a) PAR determinism

def test_compute_par_deterministic():
    cfg = CombatConfig(seed=1337)
    p1 = compute_par(1337, cfg)
    p2 = compute_par(1337, cfg)
    assert p1 == p2                            # identical args -> identical PAR
    # every PAR field reproduces bit-for-bit
    assert p1.first_fix_t == p2.first_fix_t
    assert p1.efficiency == p2.efficiency
    assert p1.leak_rate == p2.leak_rate


def test_compute_par_differs_by_seed():
    cfg = CombatConfig(seed=1337)
    pa = compute_par(1337, cfg)
    pb = compute_par(9001, cfg)
    # the seeded jitter must move at least one axis between distinct seeds
    assert (pa.first_fix_t, pa.efficiency, pa.leak_rate) != \
           (pb.first_fix_t, pb.efficiency, pb.leak_rate)


def test_compute_par_uses_dedicated_tag_no_global_rng_touch():
    # PAR must use a FRESH standalone rng on tag [seed, 15] — it must NOT
    # consume from numpy's global stream (determinism: a sim that seeded the
    # global rng before scoring must be unaffected).
    np.random.seed(0)
    before = np.random.random()
    np.random.seed(0)
    compute_par(1337, CombatConfig(seed=1337))
    after = np.random.random()
    assert before == after


def test_compute_par_scales_with_force_count():
    # more enemy assets -> a more LENIENT (later) first-fix PAR (a harder seed
    # isn't graded on the same clock as a 1-destroyer skirmish).
    small = compute_par(1337, CombatConfig(seed=1337, n_destroyers=1))
    big = compute_par(1337, CombatConfig(seed=1337, n_destroyers=8))
    assert big.first_fix_t >= small.first_fix_t


# --------------------------------------------------- (b) perfect S / bad D

def test_perfect_world_grades_S():
    world = _perfect_world()
    tel = new_telemetry()
    tel["rounds_fired"] = 4
    tel["kills"] = 6                # bookkeeping; compute_scorecard recomputes
    tel["leakers"] = 4
    tel["first_fix_t"] = 120.0     # early recon
    card = compute_scorecard(world, tel)
    par = compute_par(1337, CombatConfig(seed=1337))
    assert grade(card, par) == "S"


def test_bad_world_grades_D():
    world = _bad_world()
    tel = new_telemetry()
    tel["rounds_fired"] = 30
    tel["leakers"] = 2
    tel["first_fix_t"] = 1800.0    # found the enemy very late
    card = compute_scorecard(world, tel)
    par = compute_par(1337, CombatConfig(seed=1337))
    assert grade(card, par) == "D"


# ------------------------------------------------- (c) was_back_plotted read

def test_was_back_plotted_yes_when_targetable_cluster():
    world = _perfect_world()
    world.commander.picture.clusters = [_FakeCluster(True)]
    card = compute_scorecard(world, new_telemetry())
    assert card.was_back_plotted is True


def test_was_back_plotted_no_when_no_targetable_cluster():
    world = _perfect_world()
    # a cluster that is NOT yet targetable must not count as 'found'
    world.commander.picture.clusters = [_FakeCluster(False)]
    card = compute_scorecard(world, new_telemetry())
    assert card.was_back_plotted is False


def test_was_back_plotted_no_when_empty_picture():
    world = _perfect_world()
    world.commander.picture.clusters = []
    card = compute_scorecard(world, new_telemetry())
    assert card.was_back_plotted is False


# -------------------------------------- (d) leak_rate + efficiency arithmetic

def test_leak_rate_and_efficiency_match_hand_values():
    world = _bad_world()                # 0 enemy ships dead (all alive)
    tel = new_telemetry()
    tel["rounds_fired"] = 10
    tel["leakers"] = 4
    card = compute_scorecard(world, tel)
    # leak_rate = leakers / rounds_fired = 4 / 10
    assert card.leak_rate == pytest.approx(0.4)
    # bad world: 0 enemy assets killed -> efficiency 0.0
    assert card.kills == 0
    assert card.efficiency == pytest.approx(0.0)


def test_efficiency_counts_all_enemy_assets():
    # perfect world: 3 ships + 2 radars + airfield = 6 kills over 4 rounds.
    world = _perfect_world()
    tel = new_telemetry()
    tel["rounds_fired"] = 4
    card = compute_scorecard(world, tel)
    assert card.kills == 6
    assert card.efficiency == pytest.approx(6.0 / 4.0)


def test_leak_rate_zero_rounds_is_zero_not_div0():
    world = _perfect_world()
    card = compute_scorecard(world, new_telemetry())   # rounds_fired 0
    assert card.leak_rate == 0.0
    assert card.efficiency == 0.0                       # 6 kills / 0 rounds -> 0


def test_base_intact_pct():
    world = _bad_world()    # 0 of 3 player structures alive
    card = compute_scorecard(world, new_telemetry())
    assert card.base_intact_pct == pytest.approx(0.0)
    world2 = _perfect_world()   # 3 of 3 alive
    card2 = compute_scorecard(world2, new_telemetry())
    assert card2.base_intact_pct == pytest.approx(1.0)


def test_first_fix_t_passthrough():
    world = _perfect_world()
    tel = new_telemetry()
    tel["first_fix_t"] = 247.5
    card = compute_scorecard(world, tel)
    assert card.first_fix_t == pytest.approx(247.5)


def test_first_fix_never_none_grades_without_crash():
    # never fixed the enemy (first_fix_t stays None): scoring must still grade.
    world = _bad_world()
    card = compute_scorecard(world, new_telemetry())   # first_fix_t None
    par = compute_par(1337, CombatConfig(seed=1337))
    assert card.first_fix_t is None
    assert grade(card, par) in ("S", "A", "B", "C", "D")


# ---------------------------------- FOG-OF-WAR: first-fix source (load-bearing)

class _Contacts:
    def __init__(self, tracks):
        self.tracks = tracks


class _PictureWorld:
    """Only the fields the first-fix predicate reads."""

    def __init__(self, tracks, missiles=()):
        self.contacts = _Contacts(tracks)
        self.missiles = missiles


class _Hostile:
    is_hostile = True
    alive = True


def test_first_fix_predicate_fires_on_surface_contact():
    # a held enemy SURFACE contact (is_air False) is the recon->fire opener.
    world = _PictureWorld({"destroyer_00": {"is_air": False}})
    assert picture_has_actionable_contact(world) is True


def test_first_fix_predicate_empty_picture_is_false():
    world = _PictureWorld({})
    assert picture_has_actionable_contact(world) is False


def test_first_fix_predicate_air_only_is_false():
    # an inbound hostile ROUND (is_air True) is NOT 'found the enemy to shoot'.
    world = _PictureWorld({"tlam_07": {"is_air": True}})
    assert picture_has_actionable_contact(world) is False


def test_first_fix_predicate_undetected_hostile_does_not_trip():
    # LOAD-BEARING fog test: an UNDETECTED hostile sits in world.missiles
    # (is_hostile, alive) but is ABSENT from the gated contact picture.  The
    # first-fix predicate reads ONLY the picture, so it must NOT trip -> an
    # undetected threat can never leak its existence through the score clock.
    world = _PictureWorld({}, missiles=[_Hostile(), _Hostile()])
    assert picture_has_actionable_contact(world) is False


# --------------------------------------------- (e) overlay renders WITH a card

class _Recorder:
    def __getattr__(self, name):
        return lambda *a, **k: None


class _FakeStates:
    def __init__(self):
        self.current = None

    def switch(self, state):
        self.current = state


class _FakeWindow:
    def size(self):
        return (1280, 720)


class _FakeText:
    """Records draw calls; returns plausible metrics for layout math."""

    def __init__(self):
        self.texts = []

    def line_height(self, size=None):
        return 18

    def text_width(self, s, size=None):
        return 8 * len(s)

    def draw_rect(self, *a, **k):
        pass

    def draw_lines(self, *a, **k):
        pass

    def draw_text(self, x, y, s, *a, **k):
        self.texts.append(s)

    def flush(self, *a, **k):
        pass


class _FakeApp:
    def __init__(self):
        self.audio = _Recorder()
        self.states = _FakeStates()
        self.window = _FakeWindow()
        self._text = _FakeText()

    def ui_text(self):
        return self._text


def _make_overlay(scorecard):
    from game.combat_end import CombatEndOverlay
    app = _FakeApp()
    ov = CombatEndOverlay(
        app, victory=True,
        rematch_cb=lambda: None,
        new_battle_cb=lambda: None,
        menu_cb=lambda: None,
        scorecard=scorecard)
    # bypass GL bind: install the fake text directly (mirrors enter())
    ov.text = app._text
    ov._sel = 0
    ov._pending = None
    ov._pending_left = 0.0
    ov._hit_rects = []
    return ov, app


def _graded_card():
    world = _perfect_world()
    tel = new_telemetry()
    tel["rounds_fired"] = 4
    tel["leakers"] = 4
    tel["first_fix_t"] = 120.0
    card = compute_scorecard(world, tel)
    card.grade = grade(card, compute_par(1337, CombatConfig(seed=1337)))
    return card


def test_overlay_with_scorecard_renders_headless():
    card = _graded_card()
    ov, app = _make_overlay(card)
    ov.render(0.016)                # must not raise
    blob = " ".join(app._text.texts)
    # the grade letter and at least one metric label are drawn
    assert card.grade in blob
    assert "BASE" in blob.upper() or "INTACT" in blob.upper()


def test_overlay_exposes_scorecard():
    card = _graded_card()
    ov, _ = _make_overlay(card)
    assert ov.scorecard is card


# ------------------------------------------------- (f) None-scorecard path

def test_overlay_none_scorecard_renders_headless():
    ov, app = _make_overlay(None)
    ov.render(0.016)                # legacy / smoke path must still work
    blob = " ".join(app._text.texts)
    assert "VICTORY" in blob


def test_overlay_default_scorecard_is_none():
    # the param defaults to None so the smoke/legacy constructor is unchanged.
    from game.combat_end import CombatEndOverlay
    app = _FakeApp()
    ov = CombatEndOverlay(app, victory=False,
                          rematch_cb=lambda: None,
                          new_battle_cb=lambda: None,
                          menu_cb=lambda: None)
    assert ov.scorecard is None
