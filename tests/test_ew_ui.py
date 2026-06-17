"""M3-F5 player-legibility EW layer: the JAMMED-band map overlay + the degraded
RADAR HUD row + the emissions-exposure meter.

This is the readout layer over the (otherwise invisible) J/S burn-through math:

  * hud.radar_jam_row(world) -> ("RADAR", "BURN-THRU <km>km", amber) when an
    enemy jammer is active and the player net still burns through; ("RADAR",
    "NET DEGRADED", red) when the ring has collapsed to the close-in floor;
    None when no jammer is active (the byte-identical default).
  * hud.emissions_exposure(world) -> (label, frac01, color) reading ONLY OWN
    assets (own radar emitting + own EW pod hot) — own-truth is allowed; None
    when nothing the player owns is radiating (SANDBOX / silent).
  * tactical_map._jam_overlay() — a translucent corridor WEDGE anchored at the
    SENSOR-BELIEVED jammer fix (world.ew_state.jammer_fix_xz), NEVER a real
    jammer entity's .pos (the FOG / NO-CHEAT contract), plus the player net's
    shrunken effective ring as a DASHED circle.  Bearing-only (un-localized)
    jammer -> an OPEN wedge with no closed origin circle.  Inactive -> no-op.

FOG / NO CHEAT (load-bearing): the band reads the BELIEF (ELINT est_pos /
bearing) the sim publishes into world.ew_state, never truth.  The burn-through
number is sourced from sim/ew.effective_range — the single source of truth.

DETERMINISM / BYTE-IDENTICAL DEFAULT: with n_jammers=0 and player_jammer=0
there is no active jammer, so ew_state reports inactive, radar_jam_row is None,
and _jam_overlay draws nothing — the out-of-the-box battle is untouched.

All pure helpers are headless / GL-free, tested with the FakeText draw-call
recorder (the locked tactical_map/hud test convention).  No tautologies: every
assertion drives a real code path against real values.
"""

from __future__ import annotations

import math

import numpy as np

import sim.ew as ew
from game.hud import (radar_jam_row, emissions_exposure, RELOAD_COL,
                      DANGER_COL, HUD, MARGIN, EMISSIONS_GAUGE_GAP_Y)
from game.tactical_map import MapView, TacticalMap
from world.combat import (CombatWorld, RADAR_STATION_XZ, RADAR_ANTENNA_M,
                          PLAYER_RADAR_RANGES)
from world.combat_config import CombatConfig
from sim.radar import Radar


W, H = 1600, 900


# ---------------------------------------------------------------------------
# Headless draw-call recorder (mirrors engine.text.TextRenderer's draw +
# measurement API), and a minimal stub world / sandbox.
# ---------------------------------------------------------------------------

class FakeText:
    """Records draw_* calls; stubs the measurement API deterministically."""

    def __init__(self):
        self.rects = []   # (x, y, w, h, rgba)
        self.lines = []   # (points, rgba, width)
        self.texts = []   # (x, y, s, color, size)

    def draw_rect(self, x, y, w, h, rgba):
        self.rects.append((x, y, w, h, tuple(rgba)))

    def draw_lines(self, points, rgba, width=1.5):
        self.lines.append(([tuple(p) for p in points], tuple(rgba), width))

    def draw_text(self, x, y, s, color=(1.0, 1.0, 1.0), size=18, scale=1.0):
        self.texts.append((x, y, s, tuple(color), size))

    def text_width(self, s, size=18):
        return float(len(s)) * (size * 0.6)

    def line_height(self, size=18):
        return int(size * 1.3)


class _StubRadar:
    """Own player radar stand-in for the emissions meter (own-truth allowed)."""

    def __init__(self, alive=True, emitting=False):
        self.alive = alive
        self.emitting = emitting


class _StubDrone:
    def __init__(self, alive=True, jam_active=False):
        self.alive = alive
        self.jam_active = jam_active


class _StubWorld:
    """A minimal world carrying just the attributes the pure helpers read."""

    def __init__(self, *, ew_state=None, radar_station=None, drone=None,
                 player_jammer=False):
        self.ew_state = ew_state
        self.radar_station = radar_station
        self.drone = drone
        self._player_jammer = player_jammer


def _real_radar():
    """The player ship-ring radar matching world/combat geometry."""
    x, z = RADAR_STATION_XZ
    return Radar("radar_player_00", (x, 0.0, z), RADAR_ANTENNA_M,
                 dict(PLAYER_RADAR_RANGES))


class _Jammer:
    """Minimal duck-typed jammer: ``.pos`` (3,) and ``.jam_power_w`` (watts)."""

    def __init__(self, pos, jam_power_w):
        self.pos = np.asarray(pos, dtype=np.float64)
        self.jam_power_w = float(jam_power_w)


# A fake tactical-map shell: only what _jam_overlay touches (view + text +
# sandbox.world).  TacticalMap.__init__ imports GL, so we bind the unbound
# method onto a hand-built shell (the locked GL-free overlay test convention).
class _MapShell:
    def __init__(self, world, view, text):
        self.sandbox = type("S", (), {"world": world})()
        self.view = view
        self.text = text

    _on_screen = TacticalMap._on_screen
    _poly_world = TacticalMap._poly_world
    _jam_overlay = TacticalMap._jam_overlay
    _net_center = TacticalMap._net_center
    _shrunken_ring = TacticalMap._shrunken_ring


def _shell(world, center=(40_000.0, 250_000.0), mpp=400.0):
    text = FakeText()
    return _MapShell(world, MapView(W, H, center, mpp), text), text


# ===========================================================================
# (6) byte-identical default: no jammer -> inactive ew_state, None row, no-op
#      overlay.  Drives the real CombatWorld build + step.
# ===========================================================================

def test_default_world_ew_state_inactive():
    """n_jammers=0 + player_jammer=0: ew_state is published but INACTIVE, so
    every UI surface reads 'no jammer' and the legacy path is untouched."""
    w = CombatWorld(CombatConfig(seed=7, n_jammers=0, player_jammer=0))
    w.step(1.0 / 30.0)
    assert isinstance(w.ew_state, dict)
    assert w.ew_state["active"] is False
    assert w.ew_state["burn_through_m"] is None
    assert w.ew_state["jammer_fix_xz"] is None
    assert w.ew_state["jammer_bearing"] is None


def test_radar_jam_row_none_with_no_active_jammer():
    """(1) radar_jam_row returns None when no jammer is active."""
    # stub inactive state
    assert radar_jam_row(_StubWorld(ew_state={"active": False})) is None
    # missing ew_state (e.g. SANDBOX world) -> also None
    assert radar_jam_row(_StubWorld(ew_state=None)) is None
    # real default battle world
    w = CombatWorld(CombatConfig(seed=7, n_jammers=0, player_jammer=0))
    w.step(1.0 / 30.0)
    assert radar_jam_row(w) is None


def test_jam_overlay_noop_when_inactive():
    """(6) _jam_overlay draws nothing when ew_state is inactive / absent."""
    for st in ({"active": False, "burn_through_m": None,
                "jammer_fix_xz": None, "jammer_bearing": None}, None):
        shell, text = _shell(_StubWorld(ew_state=st,
                                        radar_station=_real_radar()))
        shell._jam_overlay()
        assert text.lines == [] and text.rects == [] and text.texts == []


def test_default_battle_overlay_is_noop():
    """The real default battle publishes inactive ew_state, so the overlay is
    a no-op over a built world (end-to-end byte-identical default)."""
    w = CombatWorld(CombatConfig(seed=7, n_jammers=0, player_jammer=0))
    w.step(1.0 / 30.0)
    shell, text = _shell(w)
    shell._jam_overlay()
    assert text.lines == [] and text.rects == [] and text.texts == []


# ===========================================================================
# (1)(2) radar_jam_row — amber BURN-THRU row, value sourced from sim/ew.
# ===========================================================================

def test_radar_jam_row_amber_with_active_jammer():
    """(1) An active jammer -> an amber ("RADAR", "BURN-THRU <km>km") row."""
    radar = _real_radar()
    bt = 175_000.0
    state = {"active": True, "burn_through_m": bt,
             "jammer_fix_xz": (10_000.0, 120_000.0), "jammer_bearing": None}
    row = radar_jam_row(_StubWorld(ew_state=state, radar_station=radar))
    assert row is not None
    label, value, color = row
    assert label == "RADAR"
    assert color == RELOAD_COL                      # amber: degraded, not gone
    assert value == f"BURN-THRU {int(round(bt / 1e3))}km"


def test_radar_jam_row_value_matches_ew_single_source():
    """(2) The km in the row equals sim/ew.effective_range for the player net
    under the active jammer — the single source of truth, not a recompute."""
    radar = _real_radar()
    # A real jammer at the default standoff collapses the 350 km ring.
    jam = _Jammer((float(radar.pos[0]), ew.EW_DEFAULT_JAMMER_ALT_M,
                   float(radar.pos[2]) + ew.EW_DEFAULT_STANDOFF_M),
                  ew.EW_DEFAULT_JAM_POWER_W)
    # The published burn-through is exactly what effective_range returns; the
    # row must surface THAT number (km-rounded), not derive its own physics.
    bt = ew.effective_range(radar, "ship", radar.pos, [jam])
    state = {"active": True, "burn_through_m": bt,
             "jammer_fix_xz": None, "jammer_bearing": 1.0}
    row = radar_jam_row(_StubWorld(ew_state=state, radar_station=radar))
    assert row is not None
    _label, value, _color = row
    assert value == f"BURN-THRU {int(round(bt / 1e3))}km"
    # And it really is a collapse (well under the 350 km clear ring).
    assert bt < PLAYER_RADAR_RANGES["ship"]


def test_radar_jam_row_net_degraded_when_collapsed():
    """A burn-through at the close-in floor (the ring has collapsed) reads the
    red 'NET DEGRADED' status, not a misleadingly small km."""
    radar = _real_radar()
    state = {"active": True, "burn_through_m": ew.EW_CLOSE_FLOOR_M,
             "jammer_fix_xz": (10_000.0, 50_000.0), "jammer_bearing": None}
    row = radar_jam_row(_StubWorld(ew_state=state, radar_station=radar))
    assert row is not None
    label, value, color = row
    assert label == "RADAR"
    assert value == "NET DEGRADED"
    assert color == DANGER_COL


# ===========================================================================
# (3) _jam_overlay geometry follows the BELIEVED fix, NOT truth.
# ===========================================================================

def _wedge_centroid_xz(shell, text):
    """Recover the wedge vertices' world centroid from the recorded line
    polylines by inverting the view transform on every recorded point."""
    v = shell.view
    pts = []
    for points, _rgba, _w in text.lines:
        for (sx, sy) in points:
            wx, wz = v.screen_to_world((sx, sy))
            pts.append((wx, wz))
    xs = [p[0] for p in pts]
    zs = [p[1] for p in pts]
    return (sum(xs) / len(xs), sum(zs) / len(zs)), pts


def test_jam_overlay_anchored_on_belief_not_truth():
    """(3) THE fog contract: the wedge ORIGIN is world.ew_state.jammer_fix_xz
    (the ELINT belief).  Move the (irrelevant) truth far away and the wedge
    does not budge; move the BELIEF and the wedge follows it."""
    radar = _real_radar()
    believed = (10_000.0, 120_000.0)
    state = {"active": True, "burn_through_m": 150_000.0,
             "jammer_fix_xz": believed, "jammer_bearing": None}
    world = _StubWorld(ew_state=state, radar_station=radar)
    shell, text = _shell(world)
    shell._jam_overlay()
    # The wedge apex (the believed fix) must appear among the drawn vertices.
    v = shell.view
    apex_px = v.world_to_screen(believed)
    drawn = [p for (points, _c, _w) in text.lines for p in points]
    assert any(math.hypot(p[0] - apex_px[0], p[1] - apex_px[1]) < 1.0
               for p in drawn), "wedge must originate at the believed fix"

    # Now MOVE the believed fix; the apex follows the belief, proving the
    # overlay reads ew_state (belief), never a separate truth source.
    moved = (-60_000.0, 300_000.0)
    state["jammer_fix_xz"] = moved
    shell2, text2 = _shell(world)
    shell2._jam_overlay()
    apex2_px = v.world_to_screen(moved)
    drawn2 = [p for (points, _c, _w) in text2.lines for p in points]
    assert any(math.hypot(p[0] - apex2_px[0], p[1] - apex2_px[1]) < 1.0
               for p in drawn2), "wedge apex follows the BELIEF when it moves"
    # And it is no longer at the old apex (it really moved with the belief).
    assert not any(math.hypot(p[0] - apex_px[0], p[1] - apex_px[1]) < 1.0
                   for p in drawn2)


# ===========================================================================
# (3) THE PUBLISH-BOUNDARY fog contract: world._publish_ew_state must source
#      jammer_fix_xz from the BELIEF (emitter_contacts est_pos / ELINT bearing),
#      NEVER a real jammer entity's truth .pos.  This is the genuine truth-vs-
#      belief separation the overlay test (which has no real jammer in scope)
#      cannot reach: here a REAL jammer sits at truth T, the SIGINT belief is
#      seeded at B != T, and the published fix must equal B and differ from T.
# ===========================================================================

def test_publish_ew_state_fix_is_belief_not_truth():
    """A real enemy jammer radiates at truth T; the drone SIGINT picture holds a
    JAMMER contact at a DIFFERENT est_pos B.  _publish_ew_state must publish B
    (the belief), NEVER T (the truth) — reading the jammer's .pos for the fix
    would be a fog leak."""
    w = CombatWorld(CombatConfig(seed=7, n_jammers=1, player_jammer=0))
    w.step(1.0 / 30.0)
    # A real, live, emitting jammer exists at truth.
    assert w._active_enemy_jammers(), "the n_jammers=1 build must radiate"
    truth = w._jammers[0].pos
    truth_xz = (float(truth[0]), float(truth[2]))

    # Seed the SIGINT belief (emitter_contacts) at an est_pos FAR from truth.
    believed_xz = (truth_xz[0] + 80_000.0, truth_xz[1] - 120_000.0)
    w.emitter_contacts["jammer_00"] = dict(
        pos=np.array([believed_xz[0], 12_000.0, believed_xz[1]],
                     dtype=np.float64),
        kind="JAMMER", quality=8_000.0, last_heard=w.sim_time, age=1.0)

    w._publish_ew_state()
    assert w.ew_state["active"] is True
    fix = w.ew_state["jammer_fix_xz"]
    assert fix is not None
    # The published fix is the BELIEF, exactly — and is NOT the truth .pos.
    assert math.isclose(fix[0], believed_xz[0]) and \
        math.isclose(fix[1], believed_xz[1]), \
        "published fix must equal the ELINT belief est_pos"
    assert not (math.isclose(fix[0], truth_xz[0])
                and math.isclose(fix[1], truth_xz[1])), \
        "published fix must NOT be the real jammer truth .pos (fog leak)"
    # The truth really is far away (the belief genuinely diverges from truth).
    assert math.hypot(believed_xz[0] - truth_xz[0],
                      believed_xz[1] - truth_xz[1]) > 50_000.0


def test_publish_ew_state_bearing_only_is_elint_belief_not_truth():
    """With a real jammer radiating but NO localized SIGINT fix yet, the
    published bearing is the ELINT belief (elint.latest_bearing), not the exact
    geometric bearing to the jammer's truth .pos."""
    w = CombatWorld(CombatConfig(seed=7, n_jammers=1, player_jammer=0))
    # Step long enough for ELINT to hear the jammer and form a bearing, but the
    # SIGINT picture stays un-localized (no actionable fix) -> bearing branch.
    for _ in range(20):
        w.step(1.0 / 30.0)
    assert w.ew_state["active"] is True
    assert w.ew_state["jammer_fix_xz"] is None, \
        "this case exercises the bearing-only (un-localized) branch"
    bearing = w.ew_state["jammer_bearing"]
    assert bearing is not None, "a heard jammer publishes its ELINT bearing"
    # The published bearing equals the belief the publisher reads back
    # (_believed_jammer_fix), proving it routes through the ELINT store...
    _fix, belief_bearing = w._believed_jammer_fix()
    assert math.isclose(bearing, belief_bearing)
    # ... and it is NOT the exact geometric bearing to the jammer's truth .pos
    # (which the fog contract forbids reading): the ELINT estimate diverges.
    drone = w.drone
    truth = w._jammers[0].pos
    geom_to_truth = math.atan2(float(truth[0] - drone.pos[0]),
                               float(truth[2] - drone.pos[2]))
    assert not math.isclose(bearing, geom_to_truth, abs_tol=1e-4), \
        "bearing is the ELINT belief, not a truth-geometry read"


def test_jam_overlay_localized_draws_closed_origin_and_dashed_ring():
    """A localized fix draws a CLOSED wedge (apex returns to itself) plus the
    shrunken effective ring as a DASHED (multi-segment) circle."""
    radar = _real_radar()
    believed = (10_000.0, 120_000.0)
    state = {"active": True, "burn_through_m": 150_000.0,
             "jammer_fix_xz": believed, "jammer_bearing": None}
    shell, text = _shell(_StubWorld(ew_state=state, radar_station=radar))
    shell._jam_overlay()
    v = shell.view
    apex_px = v.world_to_screen(believed)
    # At least one polyline is a CLOSED wedge: first vertex == apex AND the
    # polyline returns to the apex (start == end).
    closed = False
    for points, _c, _w in text.lines:
        if (math.hypot(points[0][0] - apex_px[0],
                       points[0][1] - apex_px[1]) < 1.0
                and math.hypot(points[0][0] - points[-1][0],
                               points[0][1] - points[-1][1]) < 1.0):
            closed = True
    assert closed, "localized fix -> a closed-origin wedge"
    # The dashed ring: many short polylines centered on the player net (the
    # base), at a radius matching the burn-through (in px).
    bx, bz = RADAR_STATION_XZ  # player net center == the radar station
    # count short segments roughly at burn-through radius from the net center.
    cx, cy = v.world_to_screen((bx, bz))
    r_px = state["burn_through_m"] / v.meters_per_px
    near_ring = 0
    for points, _c, _w in text.lines:
        if len(points) == 2:
            mx = 0.5 * (points[0][0] + points[1][0])
            my = 0.5 * (points[0][1] + points[1][1])
            if abs(math.hypot(mx - cx, my - cy) - r_px) < r_px * 0.15:
                near_ring += 1
    assert near_ring >= 6, "the shrunken effective ring is drawn DASHED"


def test_jam_overlay_bearing_only_open_wedge_no_origin_circle():
    """(4) Bearing-only (un-localized): jammer_fix_xz None but jammer_bearing
    set -> an OPEN bearing wedge with NO closed origin circle/loop.  None of
    the drawn polylines may form a closed loop back to a single apex."""
    radar = _real_radar()
    state = {"active": True, "burn_through_m": 120_000.0,
             "jammer_fix_xz": None, "jammer_bearing": math.radians(30.0)}
    shell, text = _shell(_StubWorld(ew_state=state, radar_station=radar))
    shell._jam_overlay()
    # Something IS drawn (the open bearing wedge), so the player still feels
    # the corridor direction.
    assert text.lines, "a bearing-only jammer still draws the open wedge"
    # ... but no polyline is a closed loop (start != end for every polyline of
    # 3+ vertices: an open wedge never seals an origin circle).
    for points, _c, _w in text.lines:
        if len(points) >= 3:
            assert not (math.hypot(points[0][0] - points[-1][0],
                                   points[0][1] - points[-1][1]) < 1.0), \
                "bearing-only overlay must NOT close an origin circle"


# ===========================================================================
# emissions_exposure — own-asset loudness gauge (own-truth allowed).
# ===========================================================================

def test_emissions_exposure_none_when_silent():
    """Nothing radiating (radar silent, no pod) -> None (no gauge)."""
    w = _StubWorld(radar_station=_StubRadar(alive=True, emitting=False),
                   drone=_StubDrone(alive=True, jam_active=False),
                   player_jammer=True)
    assert emissions_exposure(w) is None
    # SANDBOX-like: no radar station at all -> None.
    assert emissions_exposure(_StubWorld(radar_station=None)) is None


def test_emissions_exposure_radar_only():
    """Radar emitting, pod cold -> a non-zero gauge tagged with a label and a
    fraction in (0, 1]."""
    w = _StubWorld(radar_station=_StubRadar(alive=True, emitting=True),
                   drone=_StubDrone(alive=True, jam_active=False),
                   player_jammer=True)
    out = emissions_exposure(w)
    assert out is not None
    label, frac, color = out
    assert isinstance(label, str) and label
    assert 0.0 < frac <= 1.0


def test_emissions_exposure_pod_adds_loudness():
    """A hot EW pod ON TOP of an emitting radar reads louder than the radar
    alone (own EW pod hot raises the exposure), capped at 1.0."""
    radar_only = _StubWorld(radar_station=_StubRadar(emitting=True),
                            drone=_StubDrone(jam_active=False),
                            player_jammer=True)
    radar_and_pod = _StubWorld(radar_station=_StubRadar(emitting=True),
                               drone=_StubDrone(jam_active=True),
                               player_jammer=True)
    f_radar = emissions_exposure(radar_only)[1]
    f_both = emissions_exposure(radar_and_pod)[1]
    assert f_both > f_radar
    assert f_both <= 1.0


def test_emissions_exposure_pod_ignored_when_unarmed():
    """A 'hot' drone flag with player_jammer disabled is NOT counted (the pod
    was never armed) — own-asset read stays honest about what is configured."""
    armed = _StubWorld(radar_station=_StubRadar(emitting=False),
                       drone=_StubDrone(jam_active=True), player_jammer=True)
    unarmed = _StubWorld(radar_station=_StubRadar(emitting=False),
                         drone=_StubDrone(jam_active=True), player_jammer=False)
    # armed + hot pod, radar silent -> a gauge from the pod alone.
    assert emissions_exposure(armed) is not None
    # pod unconfigured + radar silent -> nothing radiating -> None.
    assert emissions_exposure(unarmed) is None


# ===========================================================================
# (1) the emissions gauge is anchored OFF the panel's data-driven bottom — it
#      must never overlap a tall block (the magic-offset regression).
# ===========================================================================

def test_emissions_gauge_clears_a_tall_panel_bottom():
    """_block returns its data-driven height; _emissions_gauge anchors the gauge
    a fixed gap BELOW that bottom (MARGIN + height), so a tall bastion block
    (status + 3 weapon rows + ammo/profile/target/radar + the jam row + pantsir
    + time/clock + a tube band) can never overdraw the gauge — the magic-offset
    bug. The gauge gy must be >= the panel bottom for every drawn glyph."""
    text = FakeText()
    hud = HUD(text)
    # A bastion-shaped multi-row block PLUS the jam row (the row that makes the
    # panel taller exactly under jamming, when the gauge matters most).
    c = (1.0, 1.0, 1.0, 1.0)
    rows = [("STATUS", "ARMED", c)]
    rows += [("WEAPON" if i == 0 else "", "> ONIKS  x8", c) for i in range(3)]
    rows += [("AMMO", "x8", c), ("PROFILE", "HI-DIVE", c),
             ("TARGET", "BRG 010  50 km", c), ("RADAR", "EMITTING", c),
             ("RADAR", "BURN-THRU 175km", c), ("PANTSIR", "READY", c),
             ("TIME", "x1", c), ("CLOCK", "T+00:10", c)]
    cells = [("1", "READY", 0.0), ("2", "RELOADING", 0.5), ("3", "EMPTY", 0.0)]
    height = hud._block("BASTION", rows, cells=cells)
    assert isinstance(height, (int, float)) and height > 0
    panel_bottom = MARGIN + height

    # Drive the gauge with an emitting own radar + a hot pod (own-truth) so it
    # actually draws, then assert every gauge glyph sits below the panel bottom.
    before_t, before_r, before_l = (len(text.texts), len(text.rects),
                                    len(text.lines))
    w = _StubWorld(radar_station=_StubRadar(alive=True, emitting=True),
                   drone=_StubDrone(alive=True, jam_active=True),
                   player_jammer=True)
    hud._emissions_gauge(w, panel_bottom)
    new_texts = text.texts[before_t:]
    new_rects = text.rects[before_r:]
    new_lines = text.lines[before_l:]
    assert new_texts, "the gauge must actually draw (emitting radar + hot pod)"
    # Caption + percent readout both start a fixed gap below the panel bottom.
    for (x, y, *_rest) in new_texts:
        assert y >= panel_bottom, "gauge text overdraws the panel"
    assert all(y == panel_bottom + EMISSIONS_GAUGE_GAP_Y for (_x, y, *_r)
               in new_texts)
    # The gauge bar (rects/lines) likewise stays at/below the panel bottom.
    for (_x, y, *_rest) in new_rects:
        assert y >= panel_bottom, "gauge bar rect overdraws the panel"
    for (points, *_rest) in new_lines:
        for (_px, py) in points:
            assert py >= panel_bottom, "gauge bar line overdraws the panel"


# ===========================================================================
# (5) pure helpers import headless / stay GL-free.
# ===========================================================================

def test_helpers_are_gl_free_importable():
    """Importing the helpers + driving them never touches OpenGL (this module
    imported with no GL context, matching the locked HUD/tactical convention)."""
    # radar_jam_row / emissions_exposure are module-level pure functions;
    # _jam_overlay was exercised above via a hand-built shell (no GL ctor).
    assert callable(radar_jam_row)
    assert callable(emissions_exposure)
    # FakeText recorded calls for _jam_overlay above, proving no GL path runs.
    state = {"active": True, "burn_through_m": 150_000.0,
             "jammer_fix_xz": (0.0, 100_000.0), "jammer_bearing": None}
    shell, text = _shell(_StubWorld(ew_state=state, radar_station=_real_radar()))
    shell._jam_overlay()
    assert text.lines  # draw calls were captured headlessly
