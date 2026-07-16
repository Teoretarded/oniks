"""Cinematic mode (F3 lab tab): walker physics, baked-scene sampling, tile
geometry, the scripted S-300 launch and the lab tab wiring — all GL-free
(LOCKED convention: GL work is deferred to ``enter``)."""

from __future__ import annotations

import json
import math
import os
from types import SimpleNamespace

import numpy as np
import pygame
import pytest

from game.cinematic import CinematicState
from game.cinematic_missiles import (
    ScriptedLaunch,
    VARIANT_BY_ID,
    VARIANTS,
    next_variant,
)
from game.walker import (
    EYE_HEIGHT,
    SPRINT_SPEED,
    WALK_SPEED,
    Walker,
)
from world.cinematic_scene import (
    CinematicScene,
    SKIRT_MARGIN,
    build_tile_arrays,
    list_scenes,
    skirt_drops,
)


class _Recorder:
    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


def _key(key):
    return pygame.event.Event(pygame.KEYDOWN, key=key, mod=0, scancode=0)


# ------------------------------------------------------------------ walker

def _flat(x, z):
    return 0.0


def test_walker_stands_on_ground_at_eye_height():
    w = Walker(_flat, pos=(3.0, -4.0))
    w.step(0.1)
    assert w.on_ground
    assert w.eye == (3.0, EYE_HEIGHT, -4.0)


def test_walker_walks_forward_along_yaw():
    w = Walker(_flat, pos=(0.0, 0.0), yaw=0.0)   # yaw 0 = +Z north
    for _ in range(240):
        w.step(1 / 120.0, fwd=1.0)
    assert w.z > WALK_SPEED * 2.0 * 0.7          # accel ramp, then cruise
    assert abs(w.x) < 1e-6


def test_walker_sprint_outruns_walk():
    walk = Walker(_flat)
    run = Walker(_flat)
    for _ in range(360):
        walk.step(1 / 120.0, fwd=1.0)
        run.step(1 / 120.0, fwd=1.0, sprint=True)
    assert run.z > walk.z * 1.8
    assert run.z < 3.0 * SPRINT_SPEED + 1.0


def test_walker_follows_terrain_height():
    w = Walker(lambda x, z: 0.2 * z, pos=(0.0, 0.0))
    for _ in range(240):
        w.step(1 / 120.0, fwd=1.0)              # 11 deg uphill: fine
    assert w.on_ground
    assert w.y == pytest.approx(0.2 * w.z, abs=1e-6)


def test_walker_refuses_steep_slope():
    w = Walker(lambda x, z: max(0.0, z) * 2.0, pos=(0.0, -1.0))  # 63 deg wall
    for _ in range(240):
        w.step(1 / 120.0, fwd=1.0)
    assert w.z < 0.5                             # never climbed the face


def test_walker_slides_along_obstacle_wall():
    blocked = lambda x, z: z > 1.0               # noqa: E731 — wall at z=1
    w = Walker(_flat, blocked, pos=(0.0, 0.0), yaw=math.radians(30.0))
    for _ in range(360):
        w.step(1 / 120.0, fwd=1.0)
    assert w.z <= 1.0 + 1e-6                     # held by the wall
    assert w.x > 2.0                             # but slid east along it


def test_walker_jump_arc_and_landing():
    w = Walker(_flat)
    w.jump()
    apex = 0.0
    for _ in range(240):
        w.step(1 / 120.0)
        apex = max(apex, w.y)
    assert 0.4 < apex < 0.75                     # ~v0^2/2g for 3.4 m/s
    assert w.on_ground and w.y == 0.0


def test_walker_jump_only_from_ground():
    w = Walker(_flat)
    w.jump()
    w.step(1 / 120.0)
    vy = w.vy
    w.jump()                                     # air: must not double-jump
    assert w.vy == vy


def test_walker_rejects_bad_dt_and_input():
    w = Walker(_flat, pos=(1.0, 2.0))
    w.step(0.05, fwd=1.0)
    x, z = w.x, w.z
    w.step(-0.1, fwd=1.0)                        # negative dt: strict no-op
    assert (w.x, w.z) == (x, z)
    w.step(float("nan"), fwd=1.0)                # NaN dt: strict no-op
    assert (w.x, w.z) == (x, z)
    w.step(0.05, fwd=float("nan"), strafe=float("nan"))
    assert math.isfinite(w.x) and math.isfinite(w.z) \
        and math.isfinite(w.vx) and math.isfinite(w.vz)


def test_walker_airborne_cannot_enter_terrain_wall():
    """A jump toward a 10 m DTM wall must be stopped mid-air, not sail
    inside the terrain and teleport out on landing."""
    wall = lambda x, z: 10.0 if z > 2.0 else 0.0          # noqa: E731
    w = Walker(wall, pos=(0.0, 0.0), yaw=0.0)
    w.jump()
    for _ in range(240):
        w.step(1 / 120.0, fwd=1.0)
        ground = wall(w.x, w.z)
        assert w.y >= ground - 1e-6 or w.z <= 2.0         # never inside
    assert w.z <= 2.0 + 1e-6                              # held by the wall


def test_walker_diagonal_slope_not_double_counted():
    """A 30 deg slope climbed DIAGONALLY stays legal even though each
    axis-separated half would measure steeper than it is."""
    slope = lambda x, z: max(0.0, z) * 0.577              # noqa: E731
    w = Walker(slope, pos=(0.0, 0.0), yaw=math.radians(45.0))
    for _ in range(600):
        w.step(1 / 120.0, fwd=1.0)
    assert w.z > 2.0                                      # actually climbed
    assert w.x > 2.0                                      # on the diagonal


# ------------------------------------------------------------ skirt sizing

def test_skirt_drops_flat_is_margin_only():
    h2 = np.zeros((503, 503), np.float32)      # 1 km at 2 m + halo
    h4 = np.zeros((253, 253), np.float32)      # 1 km at 4 m + halo
    h20 = np.zeros((53, 53), np.float32)       # 1 km at 20 m + halo
    assert skirt_drops(h2, h4, h20) == (SKIRT_MARGIN,) * 3


def test_skirt_drops_cover_measured_edge_deltas():
    """A coarse grid biased DOWN at the edges must grow the FINE tile's
    skirt (its edge sits above the coarse neighbour's surface), and a
    coarse grid biased UP must grow its own."""
    h2 = np.zeros((503, 503), np.float32)
    h4 = np.zeros((253, 253), np.float32)
    h20 = np.zeros((53, 53), np.float32)
    h4 -= 30.0                                   # coarse everywhere lower
    d2, d4, d20 = skirt_drops(h2, h4, h20)
    assert d2 >= 30.0 + SKIRT_MARGIN - 1e-6      # fine tile covers the gap
    h4 += 80.0                                   # now coarse sits higher
    d2, d4, d20 = skirt_drops(h2, h4, h20)
    assert d4 >= 50.0 + SKIRT_MARGIN - 1e-6      # coarse tile covers it


# ------------------------------------------------------------ tile builder

def test_tile_arrays_flat_grid_geometry():
    n = 11                                       # 10 m tile at 1 m cells
    h = np.zeros((n + 2, n + 2), dtype=np.float32)
    verts, idx = build_tile_arrays(h, 1.0, 10.0, skirt_drop=2.0)
    assert verts.shape == (n * n + 4 * n, 9)
    interior = verts[:n * n]
    assert np.allclose(interior[:, 3:6], (0.0, 1.0, 0.0))   # flat: +Y
    assert interior[:, 6].min() == 0.0 and interior[:, 6].max() == 1.0
    skirt = verts[n * n:]
    assert np.allclose(skirt[:, 1], -2.0)                    # dropped ring
    assert idx.max() < len(verts)
    assert len(idx) % 3 == 0


def test_tile_arrays_normals_face_uphill():
    n = 11
    xs = np.arange(n + 2, dtype=np.float32) - 1.0
    h = np.broadcast_to(xs[None, :] * 0.5, (n + 2, n + 2)).copy()
    verts, _ = build_tile_arrays(h, 1.0, 10.0, skirt_drop=1.0)
    nrm = verts[: n * n, 3:6]
    assert np.all(nrm[:, 0] < 0.0)               # slope rises east: nx < 0
    assert np.all(nrm[:, 1] > 0.0)
    assert np.allclose(np.linalg.norm(nrm, axis=1), 1.0, atol=1e-5)


def test_tile_arrays_shared_edges_bit_identical():
    """Two abutting tiles sampled from one field agree exactly on the
    shared edge (the bake samples one mosaic, so equal inputs -> equal
    vertices -> no cracks)."""
    field = np.arange(25 * 25, dtype=np.float32).reshape(25, 25) * 0.01
    west = field[:13, :13]
    east = field[:13, 10:23]
    vw, _ = build_tile_arrays(west, 1.0, 10.0, skirt_drop=1.0)
    ve, _ = build_tile_arrays(east, 1.0, 10.0, skirt_drop=1.0)
    n = 11
    west_edge = vw[:n * n].reshape(n, n, 9)[:, -1, 1]     # x = 10 column
    east_edge = ve[:n * n].reshape(n, n, 9)[:, 0, 1]      # x = 0 column
    assert np.array_equal(west_edge, east_edge)


# ------------------------------------------------------------ baked scene

@pytest.fixture()
def tiny_scene(tmp_path):
    """A synthetic 8 x 8 m baked scene: plane y = 0.1x + 2, one obstacle."""
    nx = nz = 9
    xs = np.arange(nx, dtype=np.float32)
    dtm = np.broadcast_to(xs[None, :] * 0.1 + 2.0, (nz, nx)).copy()
    obstacle = np.zeros((nz, nx), dtype=np.uint8)
    obstacle[4, 4] = 1
    np.save(tmp_path / "dtm_1m.npy", dtm)
    np.save(tmp_path / "obstacle.npy", obstacle)
    meta = {
        "name": "tiny", "title": "TINY", "subtitle": "TEST PATCH",
        "attribution": "test data", "epsg": 2056,
        "origin_e": 0.0, "origin_n": 0.0, "origin_alt": 100.0,
        "x0": 0.0, "x1": 8.0, "z0": 0.0, "z1": 8.0,
        "dtm": {"cell": 1.0, "file": "dtm_1m.npy"},
        "obstacle": {"cell": 1.0, "file": "obstacle.npy"},
        "spawn": {"x": 2.0, "z": 2.0, "yaw_deg": 90.0},
        "s300": {"x": 6.0, "z": 6.0, "yaw_deg": 270.0},
        "tiles": [],
    }
    (tmp_path / "scene.json").write_text(json.dumps(meta), encoding="utf-8")
    return tmp_path


def test_scene_bilinear_ground_matches_plane(tiny_scene):
    sc = CinematicScene(str(tiny_scene))
    for x, z in ((0.0, 0.0), (3.5, 2.25), (7.9, 7.9), (4.499, 0.501)):
        assert sc.ground_h(x, z) == pytest.approx(0.1 * x + 2.0, abs=1e-4)


def test_scene_blocked_cells_and_borders(tiny_scene):
    sc = CinematicScene(str(tiny_scene))
    assert sc.blocked(4.0, 4.0)                  # the marked obstacle
    assert not sc.blocked(2.0, 2.0)
    assert sc.blocked(-0.5, 2.0)                 # outside the data: wall
    assert sc.blocked(2.0, 8.5)


def test_scene_spawn_pos_yaw(tiny_scene):
    sc = CinematicScene(str(tiny_scene))
    (x, z), yaw = sc.spawn_pos_yaw()
    assert (x, z) == (2.0, 2.0)
    assert yaw == pytest.approx(math.pi / 2.0)


def test_list_scenes_finds_manifest(tiny_scene):
    scenes = list_scenes(str(tiny_scene.parent))
    names = [s[0] for s in scenes]
    assert tiny_scene.name in names


@pytest.fixture()
def surround_scene(tmp_path):
    """A 128 m core (plane y = 0.1x + 2) ringed by flat 64 m surround
    chunks at y = 7 covering -64..192 on both axes."""
    nx = nz = 129
    xs = np.arange(nx, dtype=np.float32)
    dtm = np.broadcast_to(xs[None, :] * 0.1 + 2.0, (nz, nx)).copy()
    np.save(tmp_path / "dtm_1m.npy", dtm)
    np.save(tmp_path / "obstacle.npy", np.zeros((nz, nx), dtype=np.uint8))
    surround = []
    for ci, cx in enumerate((-64.0, 0.0, 64.0, 128.0)):
        for cj, cz in enumerate((-64.0, 0.0, 64.0, 128.0)):
            name = f"sur_{ci}_{cj}_hgt.npz"
            np.savez(tmp_path / name,
                     h=np.full((7, 7), 7.0, dtype=np.float32))
            surround.append({"x0": cx, "z0": cz, "size": 64.0,
                             "hgt": name, "tex": "missing.jpg"})
    meta = {
        "name": "ring", "title": "RING", "subtitle": "TEST",
        "attribution": "test data", "epsg": 2056,
        "origin_e": 0.0, "origin_n": 0.0, "origin_alt": 100.0,
        "x0": 0.0, "x1": 128.0, "z0": 0.0, "z1": 128.0,
        "dtm": {"cell": 1.0, "file": "dtm_1m.npy"},
        "obstacle": {"cell": 1.0, "file": "obstacle.npy"},
        "spawn": {"x": 64.0, "z": 64.0, "yaw_deg": 0.0},
        "s300": {"x": 100.0, "z": 100.0, "yaw_deg": 180.0},
        "tiles": [], "surround": surround,
    }
    (tmp_path / "scene.json").write_text(json.dumps(meta), encoding="utf-8")
    return tmp_path


def test_surround_extends_walkable_world(surround_scene):
    """Beyond the fine core the coarse surround chunks ARE ground now:
    height sampling works, nothing is blocked, and the walk bounds grow
    to the surround extent (user report: 'NO GROUND THERE')."""
    sc = CinematicScene(str(surround_scene))
    assert (sc.ext_x0, sc.ext_x1) == (-64.0, 192.0)
    assert (sc.ext_z0, sc.ext_z1) == (-64.0, 192.0)
    assert sc.ground_h(160.0, 64.0) == pytest.approx(7.0)
    assert sc.ground_h(-30.0, -30.0) == pytest.approx(7.0)
    assert not sc.blocked(160.0, 64.0)
    assert not sc.blocked(-30.0, -30.0)
    assert sc.blocked(250.0, 64.0)               # off the surround too
    assert sc.blocked(64.0, -100.0)


def test_surround_core_border_blends_not_cliffs(surround_scene):
    """Crossing the core border must not present a phantom ledge: deep
    inside the core the 1 m plane rules, at the border the value meets
    the coarse field, in between it blends monotonically."""
    sc = CinematicScene(str(surround_scene))
    deep = sc.ground_h(64.0, 64.0)
    assert deep == pytest.approx(0.1 * 64.0 + 2.0, abs=1e-4)
    at_border = sc.ground_h(0.01, 64.0)
    assert at_border == pytest.approx(7.0, abs=0.05)
    lo, hi = sorted((0.1 * 24.0 + 2.0, 7.0))
    mid = sc.ground_h(24.0, 64.0)                # inside the blend band
    assert lo - 1e-6 <= mid <= hi + 1e-6
    walkable_step = abs(sc.ground_h(-0.5, 64.0) - sc.ground_h(0.5, 64.0))
    assert walkable_step < 0.55                  # the walker's ledge limit


def test_teleport_from_outside_world_lands_inside(surround_scene):
    """A freecam OUTSIDE the world clicking back in must never land the
    walker beyond the walkable bounds (the border-clamped sampler used
    to fake ground a few metres outside — GPT-5.6 review)."""
    st = CinematicState(_App(), str(surround_scene))
    st.scene = CinematicScene(str(surround_scene))
    st.walker = Walker(st.scene.ground_h, st.scene.blocked, pos=(64.0, 64.0))
    st.freecam = True
    st.fc_pos = np.array([260.0, 45.0, 64.0])    # beyond ext_x1 = 192
    st.walker.yaw = math.radians(270.0)          # looking back west
    st.walker.pitch = math.radians(-50.0)
    st._teleport_to_view()
    assert not st.freecam                        # it did teleport
    assert st.scene.ext_x0 <= st.walker.x <= st.scene.ext_x1
    assert st.scene.ext_z0 <= st.walker.z <= st.scene.ext_z1
    assert not st.scene.blocked(st.walker.x, st.walker.z)


def test_teleport_lands_on_surround_ground(surround_scene):
    """Freecam-clicking onto the coarse surround terrain teleports the
    walker there instead of refusing with NO GROUND THERE."""
    st = CinematicState(_App(), str(surround_scene))
    st.scene = CinematicScene(str(surround_scene))
    st.walker = Walker(st.scene.ground_h, st.scene.blocked, pos=(64.0, 64.0))
    st.freecam = True
    st.fc_pos = np.array([150.0, 60.0, 64.0])    # over the surround ring
    st.walker.yaw = math.radians(90.0)           # +x
    st.walker.pitch = math.radians(-70.0)        # steeply down
    st._teleport_to_view()
    assert not st.freecam
    assert st.walker.x > 128.0                   # landed OUTSIDE the core
    assert st.walker.y == pytest.approx(7.0, abs=0.1)


# --------------------------------------------------------- scripted launch

def _launch(vid="48n6", away_yaw=0.0):
    return ScriptedLaunch(VARIANT_BY_ID[vid], (0.0, 10.0, 0.0),
                          away_yaw=away_yaw, tube_top=9.1)


def test_scripted_launch_cold_eject_then_ignite():
    """Ignition fires at the variant's researched delay (~0.9 s) with the
    round coasting through the ~25-32 m band (research doc section 1)."""
    m = _launch()
    events: list = []
    dt = 1 / 120.0
    while not m.ignited:
        m.step(dt, events)
    assert m.t == pytest.approx(m.variant.ignite_delay, abs=0.02)
    assert [k for k, _ in events] == ["ignite"]
    assert 10.0 + 20.0 < m.pos[1] < 10.0 + 40.0


def test_scripted_launch_boosts_and_expires():
    m = _launch()
    events: list = []
    dt = 1 / 120.0
    speed_at_burnout = None
    burn_end = m.variant.ignite_delay + m.variant.burns[0][1]
    while not m.done:
        m.step(dt, events)
        if speed_at_burnout is None and m.t >= burn_end:
            speed_at_burnout = float(np.linalg.norm(m.vel))
    assert speed_at_burnout > 1000.0             # ~15 g for 12 s: hypersonic
    assert m.t >= m.variant.life_s
    assert m.tilt > 0.0


def test_scripted_launch_tilts_away_from_viewer():
    m = _launch(away_yaw=0.0)                    # away = +Z
    events: list = []
    dt = 1 / 120.0
    for _ in range(int(6.0 / dt)):
        m.step(dt, events)
    assert m.pos[2] > 50.0                       # went north, not at the lens
    assert abs(m.pos[0]) < 1e-6


def test_dual_pulse_variant_coasts_between_burns():
    m = _launch("9m96")
    (a0, a1), (b0, _b1) = m.variant.burns
    dt = 1 / 120.0
    events: list = []
    while m.t < m.variant.ignite_delay + (a1 + b0) / 2.0:
        m.step(dt, events)
    assert m.ignited and not m.burning()         # coasting between pulses
    while m.t < m.variant.ignite_delay + b0 + 0.2:
        m.step(dt, events)
    assert m.burning()                           # second pulse lit


def test_variant_emission_fills_pools_gl_free():
    from engine.particles import Effects
    fx = Effects(seed=11)
    m = _launch("40n6")
    events: list = []
    dt = 1 / 120.0
    for _ in range(int(4.0 / dt)):
        m.step(dt, events)
        m.emit(fx, dt)
    assert int(fx.fire.alive.sum()) > 0          # flame + glow
    assert int(fx.smoke.alive.sum()) > 60        # the column is building


def test_plume_lifetimes_shrink_with_altitude():
    """The column DISSIPATES at a decent distance: smoke emitted high on
    the trajectory must be born with much shorter lifetimes than smoke
    emitted just off the pad (the pad column keeps its long hang)."""
    from engine.particles import Effects

    m = _launch("48n6")
    events: list = []
    dt = 1 / 120.0
    fx_void = Effects(seed=1)          # sink while not sampling
    fx_low = Effects(seed=7)
    fx_high = Effects(seed=7)

    def collect(fx, seconds=0.35):
        for _ in range(int(seconds / dt)):
            m.step(dt, events)
            m.emit(fx, dt)
        return fx.smoke.max_life[fx.smoke.alive]

    low_lives = high_lives = None
    while not m.done:
        m.step(dt, events)
        rel_alt = m.pos[1] - 10.0
        if low_lives is None and m.burning() and rel_alt > 60.0:
            low_lives = collect(fx_low)
        elif m.burning() and rel_alt > 3000.0:
            high_lives = collect(fx_high)
            break
        else:
            m.emit(fx_void, dt)
    assert low_lives is not None and len(low_lives) and len(high_lives)
    assert float(np.median(high_lives)) < 0.6 * float(np.median(low_lives))
    assert float(low_lives.max()) > 60.0         # the pad column still hangs
    assert float(high_lives.max()) < 35.0        # aloft it shears away


def test_pad_spew_builds_lingering_ground_cloud():
    """While the booster is low the pad keeps SPEWING: seconds after
    ignition there must be a substantial long-lived cloud near the pad,
    not one instantly-fading puff."""
    from engine.particles import Effects

    fx = Effects(seed=3)
    m = _launch("40n6")
    events: list = []
    dt = 1 / 120.0
    for _ in range(int(3.0 / dt)):
        m.step(dt, events)
        m.emit(fx, dt)
    alive = fx.smoke.alive
    pos = fx.smoke.pos[alive]
    near_pad = (np.hypot(pos[:, 0], pos[:, 2]) < 80.0) & (pos[:, 1] < 60.0)
    lives = fx.smoke.max_life[alive][near_pad]
    assert near_pad.sum() > 150                  # a real ground cloud
    assert float(np.percentile(lives, 75)) > 15.0   # and it lingers


def test_pad_blast_oneshots_linger():
    """The blast one-shots must include genuinely long-lived particles
    (base cloud ~40 s, haze skirt ~55 s) — 'disappears immediately' is
    the bug being pinned here."""
    from engine.particles import Effects

    fx = Effects(seed=9)
    m = _launch("48n6")
    m.pad_blast_fx(fx, np.zeros(3))
    m.pad_roll_fx(fx, np.zeros(3))
    lives = fx.smoke.max_life[fx.smoke.alive]
    assert float(lives.max()) > 35.0
    assert float(np.percentile(lives, 90)) > 20.0


def test_next_variant_cycles_all():
    seen = {VARIANTS[0].id}
    v = VARIANTS[0]
    for _ in range(len(VARIANTS) - 1):
        v = next_variant(v.id)
        seen.add(v.id)
    assert seen == {v.id for v in VARIANTS}


# ------------------------------------------------------------ baked shadow

def test_shadow_bake_peak_casts_away_from_sun():
    """A lone 120 m block under a low eastern sun throws a long shadow
    WEST of itself; the sun side and the off-axis ground stay lit."""
    from world.cinematic_shadows import bake_shadow_mask

    field = np.zeros((64, 64), np.float32)
    field[30:34, 30:34] = 120.0                  # block, cell = 10 m
    mask = bake_shadow_mask(field, 10.0, (0.9, 0.18, 0.0))  # sun in the east
    assert mask[31:33, 4:26].mean() > 100        # deep shadow to the west
    assert mask[31:33, 38:].mean() < 12          # sun side lit
    assert mask[:20, :].mean() < 10              # off the shadow corridor


def test_shadow_bake_zenith_none_below_horizon_all():
    from world.cinematic_shadows import bake_shadow_mask

    field = np.zeros((16, 16), np.float32)
    field[8, 8] = 500.0
    assert bake_shadow_mask(field, 10.0, (0.0, 1.0, 0.0)).max() == 0
    assert bake_shadow_mask(field, 10.0, (0.3, -0.2, 0.1)).min() == 255


def test_shadow_bake_diagonal_sun_shadows_diagonally():
    """Sun from the north-east: the shadow lands south-west of the peak
    (the fractional lateral shift must track the sun azimuth)."""
    from world.cinematic_shadows import bake_shadow_mask

    field = np.zeros((64, 64), np.float32)
    field[40:44, 40:44] = 150.0
    mask = bake_shadow_mask(field, 10.0, (0.65, 0.15, 0.65))
    assert mask[28:34, 28:34].mean() > 80        # SW of the peak: shadowed
    assert mask[50:, 50:].mean() < 12            # NE of it: lit


def test_shadow_compose_and_cache_roundtrip(surround_scene):
    """The composed field honors core + surround heights, and a second
    bake for the same mood comes back from the npz cache unchanged."""
    from world.cinematic_shadows import bake_mood_mask, compose_height_field

    sc = CinematicScene(str(surround_scene))
    field, x0, z0, cell = compose_height_field(sc, max_res=128)
    gi = lambda x, z: field[int(round((z - z0) / cell)),   # noqa: E731
                            int(round((x - x0) / cell))]
    assert gi(64.0, 64.0) == pytest.approx(0.1 * 64.0 + 2.0, abs=0.4)
    assert gi(170.0, 64.0) == pytest.approx(7.0, abs=0.1)
    m1, r1 = bake_mood_mask(sc, "golden", (0.62, 0.13, 0.45))
    assert os.path.isfile(os.path.join(str(surround_scene),
                                       "shadow_golden.npz"))
    m2, r2 = bake_mood_mask(sc, "golden", (0.62, 0.13, 0.45))
    assert np.array_equal(m1, m2) and r1 == pytest.approx(r2)


# ------------------------------------------------------------- rolling fog

def _fog(surround_scene, mood="noon"):
    from engine.particles import ParticlePool
    from world.cinematic_fog import FOG_CAP, CinematicFog

    sc = CinematicScene(str(surround_scene))
    fog = CinematicFog(sc, ParticlePool(FOG_CAP), wind_profile=None)
    fog.mood = mood
    return sc, fog


def test_fog_breeds_high_banks_in_every_mood(surround_scene):
    """The icy heights hold fog banks in all light moods (the valley
    population is separate and mood-gated)."""
    _sc, fog = _fog(surround_scene, "noon")
    for _ in range(300):
        fog.step(0.1)
    n = fog.pool._hi
    alive = fog.pool.alive[:n]
    assert int(alive.sum()) > 20
    assert not bool((fog._is_valley[:n] & alive).any())   # high fog only


def test_fog_valley_banks_only_at_low_sun(surround_scene):
    """Green-floor fog exists at grey morning but burns off within ~20 s
    of switching to a high-sun mood (user: green terrain fogs only at
    certain times of day)."""
    _sc, fog = _fog(surround_scene, "grey")
    for _ in range(300):
        fog.step(0.1)
    n = fog.pool._hi
    valley = int((fog._is_valley[:n] & fog.pool.alive[:n]).sum())
    assert valley > 15
    fog.set_mood("noon")
    for _ in range(260):                          # 26 s: burn-off window
        fog.step(0.1)
    n = fog.pool._hi
    valley = int((fog._is_valley[:n] & fog.pool.alive[:n]).sum())
    assert valley == 0


def test_fog_hugs_terrain_and_drifts(surround_scene):
    """Banks ride the wind horizontally while their height tracks the
    local ground + hover — over a ridge they climb and pour, never
    tunnel: |y - (ground + hover)| stays bounded as they move."""
    _sc, fog = _fog(surround_scene, "grey")
    for _ in range(200):
        fog.step(0.1)
    n = fog.pool._hi
    idx = np.flatnonzero(fog.pool.alive[:n])
    assert len(idx) > 10
    start = fog.pool.pos[idx].copy()
    for _ in range(300):                          # 30 s of drift
        fog.step(0.1)
    still = fog.pool.alive[:n][idx]
    idx = idx[still]
    assert len(idx) > 5
    pos = fog.pool.pos[idx]
    moved = np.hypot(pos[:, 0] - start[still][:, 0],
                     pos[:, 2] - start[still][:, 2])
    assert float(np.median(moved)) > 15.0         # the layer is ALIVE
    ground = fog._ground(pos[:, 0], pos[:, 2])
    err = np.abs(pos[:, 1] - (ground + fog._hover[idx]))
    assert float(np.percentile(err, 90)) < 25.0   # terrain-following
    assert bool(np.all(pos[:, 1] > ground - 5.0))  # never buried


# ------------------------------------------------------------- light moods

def test_mood_roster_covers_requested_rigs():
    from game.cinematic import MOODS

    assert [m.id for m in MOODS] == ["alpine", "noon", "golden", "grey",
                                     "night"]
    for m in MOODS:
        d = np.asarray(m.sun_dir, dtype=np.float64)
        d = d / np.linalg.norm(d)
        assert d[1] > 0.0                        # key light above horizon


def test_grey_morning_sun_is_low_not_overhead():
    """User report: 'the sun is directly above in the gray morning' —
    the grey rig must hold a genuinely low morning sun."""
    from game.cinematic import MOODS

    grey = next(m for m in MOODS if m.id == "grey")
    d = np.asarray(grey.sun_dir, dtype=np.float64)
    elev = math.degrees(math.asin(d[1] / np.linalg.norm(d)))
    assert elev < 30.0
    golden = next(m for m in MOODS if m.id == "golden")
    d = np.asarray(golden.sun_dir, dtype=np.float64)
    assert math.degrees(math.asin(d[1] / np.linalg.norm(d))) < 15.0


def test_night_mood_darkens_ambient_and_smoke():
    from game.cinematic import MOODS

    night = next(m for m in MOODS if m.id == "night")
    assert night.hemi_gain < 0.3                 # terrain ambient crushed
    assert night.light_gain < 0.3                # smoke no longer glows
    assert max(night.sun_color) < 0.25           # moon, not sun


def test_apply_mood_drives_renderer_sky_and_wind_band():
    st = CinematicState(_App(), "x")
    st.wind = _synth_profile()
    st.mood_i = [m.id for m in __import__(
        "game.cinematic", fromlist=["MOODS"]).MOODS].index("grey")
    st._apply_mood()
    r = st.app.renderer
    assert r.hemi_gain == pytest.approx(1.08)
    assert st.wind.band == "morning"             # light + wind move together
    st.mood_i = 4                                # night
    st._apply_mood()
    assert r.light_gain == pytest.approx(0.22)
    assert st.wind.band == "night"


# ------------------------------------------------------------------- wind

def _synth_profile(axis_deg=None, floor_uv=(0.0, 1.0), floor_p=(1.0, 2.0),
                   steady=0.8):
    """Two-level synthetic profile: valley floor + free air aloft."""
    from world.cinematic_wind import WindProfile

    def lvl(alt, u, v, p50, p90, s=steady):
        st = {"u_mean": u, "v_mean": v, "speed_p50": p50,
              "speed_p90": p90, "dir_steadiness": s}
        return {"level": f"{alt}m", "alt_m_asl": alt, "all": st,
                "night": st, "morning": st, "day": st, "evening": st}

    profile = {"name": "synth", "levels": [
        lvl(800.0, floor_uv[0], floor_uv[1], floor_p[0], floor_p[1]),
        lvl(3000.0, 8.0, 0.0, 8.0, 16.0),
    ]}
    if axis_deg is not None:
        profile["valley_axis_deg"] = axis_deg
    return WindProfile(profile, origin_alt=760.0, floor_y=40.0,
                       ridge_y=1800.0)


def test_wind_profile_altitude_layers():
    """The pad feels the light valley breeze; 2.2 km above it the same
    profile answers with the strong free-air flow — never one global
    wind vector."""
    wp = _synth_profile()
    lo = wp.wind_at(40.0, 5.0)                   # valley floor
    hi = wp.wind_at(2240.0, 5.0)                 # 3000 m ASL
    assert 0.9 <= float(np.linalg.norm(lo)) <= 2.3   # p50..p90 band
    assert 7.5 <= float(np.linalg.norm(hi)) <= 16.5
    assert lo[2] > abs(lo[0])                    # floor: northward
    assert hi[0] > abs(hi[2])                    # aloft: eastward
    assert lo[1] == hi[1] == 0.0                 # no vertical wind


def test_wind_profile_is_deterministic():
    """Physics-not-dice: same scene, same second -> same wind."""
    a = _synth_profile().wind_at(500.0, 12.34)
    b = _synth_profile().wind_at(500.0, 12.34)
    assert np.array_equal(a, b)
    c = _synth_profile().wind_at(500.0, 40.0)
    assert not np.array_equal(a, c)              # gusts breathe over time


def test_wind_valley_channeling_kills_crosswind():
    """Below the ridgeline a pure crosswind is mostly absorbed by the
    trench walls; above the ridge it blows free."""
    free = _synth_profile(axis_deg=None, floor_uv=(1.0, 0.0),
                          floor_p=(1.0, 1.0), steady=1.0)
    chan = _synth_profile(axis_deg=0.0, floor_uv=(1.0, 0.0),
                          floor_p=(1.0, 1.0), steady=1.0)
    w_free = free.wind_at(40.0, 0.0)
    w_chan = chan.wind_at(40.0, 0.0)
    assert abs(w_chan[0]) < 0.45 * abs(w_free[0])
    hi_free = free.wind_at(2500.0, 0.0)
    hi_chan = chan.wind_at(2500.0, 0.0)
    assert hi_chan[0] == pytest.approx(hi_free[0], rel=1e-6)


def test_particle_pool_accepts_altitude_wind():
    """Pool drag relaxes each particle toward the wind AT ITS HEIGHT: a
    low particle and a high particle drift apart under a sheared flow."""
    from engine.particles import ParticlePool

    pool = ParticlePool(8)
    rng = np.random.default_rng(0)
    pool.emit(1, (0.0, 0.0, 0.0), 0.0, (0.0, 0.0, 0.0), 0.0, 30.0,
              (1.0, 1.0), ((1, 1, 1), (1, 1, 1)), rng)
    pool.emit(1, (0.0, 1000.0, 0.0), 0.0, (0.0, 0.0, 0.0), 0.0, 30.0,
              (1.0, 1.0), ((1, 1, 1), (1, 1, 1)), rng)

    def shear(ys):
        out = np.zeros((len(ys), 3), dtype=np.float32)
        out[:, 0] = np.where(ys < 500.0, 5.0, -5.0)
        return out

    for _ in range(120):
        pool.update(1 / 30.0, drag=0.9, wind=shear)
    assert pool.pos[0, 0] > 5.0                  # low: blown east
    assert pool.pos[1, 0] < -5.0                 # high: blown west


def test_cinematic_effects_wind_fallback_and_profile():
    """Without a baked profile the legacy constant valley wind applies;
    with one, emission asks the profile at the right altitude."""
    from game.cinematic_missiles import CinematicEffects, WIND

    fx = CinematicEffects(seed=2)
    assert np.allclose(fx.wind_at(123.0), WIND)
    fx2 = CinematicEffects(seed=2, wind_profile=_synth_profile())
    hi = fx2.wind_at(2240.0)
    assert float(np.linalg.norm(hi)) > 7.0


# ------------------------------------------------------------- state logic

class _App:
    def __init__(self):
        self.window = SimpleNamespace()
        self.renderer = SimpleNamespace()
        self.audio = _Recorder()
        self.ui_prefs = SimpleNamespace(get=lambda _key: "high")
        self.screenshot_requested = False
        self.closed = 0
        self.opened = []

    def close_cinematic(self):
        self.closed += 1

    def close_testing_lab(self):
        self.closed += 1

    def open_cinematic(self, scene_dir):
        self.opened.append(scene_dir)


def test_cinematic_state_escape_before_enter_is_safe():
    app = _App()
    st = CinematicState(app, "does/not/exist")
    st.handle_event(_key(pygame.K_ESCAPE))
    assert app.closed == 1
    st.handle_event(_key(pygame.K_SPACE))        # walker None: ignored
    st.sim_step(1 / 120.0)                       # no GL, no crash


def test_cinematic_state_time_runs():
    st = CinematicState(_App(), "x")
    assert st.effective_time_scale() == 1.0


def test_freecam_click_teleports_walker_to_ground(tiny_scene):
    """Looking down at the tiny scene's plane from a freecam and clicking
    drops the walker onto the terrain under the marker."""
    st = CinematicState(_App(), str(tiny_scene))
    st.scene = CinematicScene(str(tiny_scene))
    st.walker = Walker(st.scene.ground_h, st.scene.blocked, pos=(2.0, 2.0))
    st.freecam = True
    st.fc_pos = np.array([1.0, 8.0, 1.0])
    st.walker.yaw = math.radians(45.0)           # toward +x/+z
    st.walker.pitch = math.radians(-75.0)        # steeply down (the ray
    # must reach the ground before leaving the tiny 8 m scene rect)
    st._teleport_to_view()
    assert not st.freecam                        # back on the boots
    assert 1.0 < st.walker.x < 8.0
    assert st.walker.y == pytest.approx(
        st.scene.ground_h(st.walker.x, st.walker.z), abs=0.05)


def test_freecam_click_into_sky_is_refused(tiny_scene):
    st = CinematicState(_App(), str(tiny_scene))
    st.scene = CinematicScene(str(tiny_scene))
    st.walker = Walker(st.scene.ground_h, st.scene.blocked, pos=(2.0, 2.0))
    st.freecam = True
    st.fc_pos = np.array([2.0, 30.0, 2.0])
    st.walker.pitch = math.radians(45.0)         # up into the sky
    st._teleport_to_view()
    assert st.freecam                            # nothing to land on


# --------------------------------------------------------------- lab tab

def _lab(monkeypatch, scenes):
    """Lab with a FIXED fake scene list: entering the cinematic tab
    rescans the disk, so the rescan is pinned to the fake list too and
    manifest validation is primed for the fake dirs."""
    import game.testing_lab as tl
    monkeypatch.setattr(tl, "list_scenes", lambda *a, **k: list(scenes))
    monkeypatch.setattr(tl.TestingLabState, "_cinema_meta",
                        lambda self, d: {"title": "fake"})
    app = _App()
    lab = tl.TestingLabState(app)
    lab.cinema_scenes = list(scenes)
    return app, lab


def test_lab_f7_toggles_cinematic_mode(monkeypatch):
    _app, lab = _lab(monkeypatch, [])
    assert lab.lab_mode == "assets"
    lab.handle_event(_key(pygame.K_F7))
    assert lab.lab_mode == "cinematic"
    lab.handle_event(_key(pygame.K_F7))
    assert lab.lab_mode == "assets"


def test_lab_cinematic_enter_opens_selected_scene(monkeypatch):
    app, lab = _lab(monkeypatch, [
        ("alps", "LAUTERBRUNNEN", "CH", "assets/cinematic/alps"),
        ("us", "YOSEMITE", "US", "assets/cinematic/us"),
    ])
    lab._set_lab_mode("cinematic")
    lab.handle_event(_key(pygame.K_DOWN))
    lab.handle_event(_key(pygame.K_RETURN))
    assert app.opened == ["assets/cinematic/us"]


def test_lab_cinematic_enter_without_scenes_reports(monkeypatch):
    app, lab = _lab(monkeypatch, [])
    lab._set_lab_mode("cinematic")
    lab.handle_event(_key(pygame.K_RETURN))
    assert app.opened == []
    assert "NO BAKED SCENES" in lab.status


def test_lab_cinematic_escape_leaves_lab(monkeypatch):
    app, lab = _lab(monkeypatch, [])
    lab._set_lab_mode("cinematic")
    lab.handle_event(_key(pygame.K_ESCAPE))
    assert app.closed == 1


def test_lab_f6_from_cinematic_goes_to_missile_lab(monkeypatch):
    """The cinematic tab's button says MISSILE [F6] — F6 must go there."""
    _app, lab = _lab(monkeypatch, [])
    lab._set_lab_mode("cinematic")
    lab.handle_event(_key(pygame.K_F6))
    assert lab.lab_mode == "flight"


def test_no_auto_launch_ever_fires():
    """Missiles leave ONLY on the player's trigger (user report: rounds
    were auto-launching every few seconds) — a full simulated minute of
    standing still must leave the pad quiet, and L must still fire."""
    from game.cinematic_missiles import CinematicEffects

    st = CinematicState(_App(), "x")
    st.walker = Walker(_flat)
    st.effects = CinematicEffects(seed=5)
    st._pad = np.array([0.0, 0.0, 120.0])
    for _ in range(int(60.0 * 30)):
        st.sim_step(1 / 30.0)
    assert st.launches == []                     # a quiet pad
    st._fire()                                   # the L-key path
    assert len(st.launches) == 1


def test_cinematic_sound_arrives_at_speed_of_sound():
    """A cue queued 686 m away fires ~2 s later, not immediately."""
    from game.cinematic import SPEED_OF_SOUND

    class _Audio:
        def __init__(self):
            self.played = []

        def set_listener(self, eye):
            pass

        def play(self, name, pos=None, gain=1.0):
            self.played.append(name)

        def __getattr__(self, _name):
            return lambda *a, **k: None

    app = _App()
    app.audio = _Audio()
    st = CinematicState(app, "x")
    st.walker = Walker(_flat)                    # stand at the origin
    st._queue_sound("boom_far", np.array([0.0, 0.0, 2.0 * SPEED_OF_SOUND]))
    for _ in range(int(1.9 * 120)):
        st.sim_step(1 / 120.0)
    assert app.audio.played == []                # wavefront still en route
    for _ in range(int(0.2 * 120)):
        st.sim_step(1 / 120.0)
    assert app.audio.played == ["boom_far"]


# ------------------------------------------------------------ ICBM battery

def _icbm_state(with_fx: bool = False):
    """Headless state with just enough scene for the silo/target flow."""
    st = CinematicState(_App(), "x")
    st.walker = Walker(lambda x, z: 0.0, pos=(0.0, 0.0))
    st.scene = SimpleNamespace(ground_h=lambda x, z: 0.0)
    st._silo_site = np.array([0.0, 0.0, 0.0])
    if with_fx:
        from game.cinematic_missiles import CinematicEffects
        st.effects = CinematicEffects(seed=1)
    return st


def test_icbm_fire_requires_target_then_one_bird_per_silo():
    from game.cinematic import LAUNCHERS
    from game.cinematic_icbm import IcbmLaunch
    st = _icbm_state()
    st.launcher_i = 1                       # MINUTEMAN III SILO
    assert LAUNCHERS[1][0] == "mm3"
    st._fire()
    assert not st.launches                  # no target -> refused
    st.icbm_target = np.array([5000.0, 0.0, 2000.0])
    st._fire()
    assert len(st.launches) == 1
    assert isinstance(st.launches[0], IcbmLaunch)
    st._fire()
    assert len(st.launches) == 1            # silo empty while in flight


def test_icbm_warp_only_while_a_bird_flies():
    from game.cinematic import WARPS
    st = _icbm_state()
    st.warp_i = 2
    assert st.effective_time_scale() == 1.0     # no ICBM in the air
    st.launcher_i = 2                            # SARMAT
    st.icbm_target = np.array([-4000.0, 0.0, 3000.0])
    st._fire()
    assert st.effective_time_scale() == WARPS[2]


def test_icbm_launcher_rows_and_s300_salvo_untouched():
    st = _icbm_state(with_fx=True)
    kinds = [k for k, *_ in st._rows()]
    assert kinds.count("launcher") == 3
    st.launcher_i = 0                       # the S-300 pad still salvos
    st._pad = np.array([0.0, 0.0, 0.0])
    st._fire()
    assert len(st.launches) == 1
    assert isinstance(st.launches[0], ScriptedLaunch)


def test_designate_target_marks_ground_point(tiny_scene):
    st = CinematicState(_App(), str(tiny_scene))
    st.scene = CinematicScene(str(tiny_scene))
    st.walker = Walker(st.scene.ground_h, st.scene.blocked, pos=(2.0, 2.0))
    st.freecam = True
    st.fc_pos = np.array([1.0, 8.0, 1.0])
    st.walker.yaw = math.radians(45.0)
    st.walker.pitch = math.radians(-75.0)
    st._designate_target()
    assert st.icbm_target is not None
    assert 1.0 < st.icbm_target[0] < 8.0
    assert st.icbm_target[1] == pytest.approx(
        st.scene.ground_h(float(st.icbm_target[0]),
                          float(st.icbm_target[2])), abs=0.05)


def test_icbm_full_flight_through_state_events_reaches_impact():
    """The whole battery loop headless: fire, sim_step to impact, prune."""
    st = _icbm_state(with_fx=True)
    st.launcher_i = 1
    st.icbm_target = np.array([4000.0, 0.0, -2500.0])
    st._fire()
    m = st.launches[0]
    for _ in range(120 * 480):
        if m.done:
            break
        st.sim_step(1.0 / 120.0)
    assert m.done
    err = math.hypot(m.pos[0] - 4000.0, m.pos[2] + 2500.0)
    assert err < 150.0
    st.sim_step(1.0 / 120.0)
    assert m not in st.launches             # pruned; smoke lives on
