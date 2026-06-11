"""Plan tests for engine/particles.py (pure math — no GL imports).

Plan list: emit/update kills particles at life 0, drag slows, vectorized
update of 10k particles < 2 ms, build_quads returns camera-relative finite
values, ribbon point spacing >= 35 m, ribbon capped.
"""

import time

import numpy as np

from engine.particles import (Effects, ParticlePool, TrailRibbon,
                              TRAIL_MAX_POINTS, TRAIL_POINT_SPACING)


def _rng():
    return np.random.default_rng(7)


def _emit_basic(pool, n=10, life=1.0, pos=(0.0, 0.0, 0.0),
                vel_mean=(0.0, 0.0, 0.0), vel_jitter=0.0):
    pool.emit(n, pos, 0.0, vel_mean, vel_jitter, life,
              (1.0, 2.0), ((1, 1, 1), (0.5, 0.5, 0.5)), _rng())


# ---------------------------------------------------------------- pool

def test_emit_update_kills_particles_at_life_zero():
    pool = ParticlePool(64)
    _emit_basic(pool, n=10, life=0.25)
    assert int(pool.alive.sum()) == 10
    pool.update(0.1)
    assert int(pool.alive.sum()) == 10          # still alive at life 0.15
    pool.update(0.2)                            # life crosses zero
    assert int(pool.alive.sum()) == 0


def test_drag_slows_particles():
    pool = ParticlePool(64)
    _emit_basic(pool, n=5, life=10.0, vel_mean=(100.0, 0.0, 0.0))
    v0 = np.linalg.norm(pool.vel[pool.alive], axis=1)
    for _ in range(20):
        pool.update(0.1, drag=0.5)
    v1 = np.linalg.norm(pool.vel[pool.alive], axis=1)
    assert (v1 < v0).all()
    # exponential-style decay: still moving, but clearly slower
    assert (v1 > 0.0).all() and v1.max() < 0.5 * v0.min()


def test_vectorized_update_of_10k_particles_under_2ms():
    pool = ParticlePool(10_000)
    _emit_basic(pool, n=10_000, life=1e9, vel_mean=(10.0, 5.0, 1.0),
                vel_jitter=3.0)
    assert int(pool.alive.sum()) == 10_000
    best = min(_timed_update(pool) for _ in range(10))
    assert best < 2e-3, f"update took {best * 1e3:.3f} ms"


def _timed_update(pool):
    t0 = time.perf_counter()
    pool.update(1.0 / 120.0, drag=0.15, gravity=9.81, buoyancy=1.0)
    return time.perf_counter() - t0


def test_build_quads_returns_camera_relative_finite_values():
    pool = ParticlePool(256)
    # Particles far from the origin (precision-killer if not camera-relative).
    pool.emit(50, (210_000.0, 35.0, 480_000.0), 4.0, (0.0, 6.0, 0.0), 2.0,
              3.0, (2.0, 9.0), ((1, 0.6, 0.2), (0.3, 0.3, 0.3)), _rng())
    pool.update(0.05)
    cam_eye = np.array([209_900.0, 60.0, 479_900.0], dtype=np.float64)
    quads = pool.build_quads(cam_eye, np.array([1.0, 0.0, 0.0]),
                             np.array([0.0, 1.0, 0.0]))
    assert quads.dtype == np.float32
    assert quads.shape == (50 * 4, 10)
    assert np.isfinite(quads).all()
    # Camera-relative: corner positions are within a few hundred meters of
    # the eye, never anywhere near the ~500 km world coordinates.
    assert np.abs(quads[:, 0:3]).max() < 1_000.0
    assert np.abs(quads[:, 0:3]).max() > 1.0     # and not collapsed to zero


def test_build_quads_empty_pool():
    pool = ParticlePool(8)
    quads = pool.build_quads(np.zeros(3), np.array([1.0, 0.0, 0.0]),
                             np.array([0.0, 1.0, 0.0]))
    assert quads.shape == (0, 10) and quads.dtype == np.float32


def test_gravity_and_buoyancy_act_on_vertical_velocity():
    pool = ParticlePool(16)
    _emit_basic(pool, n=4, life=10.0)
    pool.update(1.0, drag=0.0, gravity=9.81)
    assert (pool.vel[pool.alive, 1] < -9.0).all()
    pool2 = ParticlePool(16)
    _emit_basic(pool2, n=4, life=10.0)
    pool2.update(1.0, drag=0.0, buoyancy=2.0)
    assert (pool2.vel[pool2.alive, 1] > 1.5).all()


def test_emit_clamps_to_capacity():
    pool = ParticlePool(32)
    _emit_basic(pool, n=100, life=5.0)
    assert int(pool.alive.sum()) == 32


# ---------------------------------------------------------------- ribbon

def test_ribbon_point_spacing_at_least_35m():
    rib = TrailRibbon()
    # Feed positions every 5 m of travel; ribbon must keep >= 35 m spacing.
    for i in range(400):
        rib.add_point(np.array([0.0, 100.0, i * 5.0]))
    pts = rib.points()
    assert len(pts) >= 2
    gaps = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    assert (gaps >= TRAIL_POINT_SPACING - 1e-9).all()
    assert TRAIL_POINT_SPACING == 35.0


def test_ribbon_capped():
    rib = TrailRibbon()
    for i in range(TRAIL_MAX_POINTS + 500):
        rib.add_point(np.array([0.0, 50.0, i * 40.0]))   # > spacing each step
    assert len(rib.points()) <= TRAIL_MAX_POINTS
    assert TRAIL_MAX_POINTS == 1600


def test_ribbon_strip_camera_relative_finite():
    rib = TrailRibbon()
    for i in range(40):
        rib.add_point(np.array([300_000.0 + i * 50.0, 14.0, 250_000.0]))
    rib.update(1.0)
    cam_eye = np.array([300_500.0, 40.0, 249_700.0], dtype=np.float64)
    strip = rib.build_strip(cam_eye)
    assert strip.dtype == np.float32
    assert strip.shape[0] == 2 * len(rib.points()) and strip.shape[1] == 10
    assert np.isfinite(strip).all()
    assert np.abs(strip[:, 0:3]).max() < 5_000.0


def test_ribbon_old_points_expire():
    rib = TrailRibbon()
    for i in range(10):
        rib.add_point(np.array([0.0, 10.0, i * 40.0]))
    rib.update(30.0)                      # > 22 s fade window
    assert len(rib.points()) == 0


# ---------------------------------------------------------------- effects

def test_effects_spawn_helpers_emit_into_pools():
    fx = Effects(seed=3)
    fx.booster_plume(np.array([0.0, 60.0, -180.0]),
                     np.array([0.0, 0.5, 0.866]), 1.0)
    assert int(fx.fire.alive.sum()) > 0
    assert int(fx.smoke.alive.sum()) > 0
    n_fire = int(fx.fire.alive.sum())
    fx.explosion(np.array([1000.0, 5.0, 2000.0]), 1.0)
    assert int(fx.fire.alive.sum()) > n_fire
    fx.splash(np.array([500.0, 0.0, 500.0]))
    fx.ship_fire(np.array([0.0, 8.0, 90_000.0]))
    fx.update(0.5)        # ages everything without error
    assert np.isfinite(fx.smoke.pos[fx.smoke.alive]).all()


def test_effects_trail_lifecycle():
    fx = Effects(seed=1)
    rib = fx.add_trail()
    rib.add_point(np.array([0.0, 100.0, 0.0]))
    rib.add_point(np.array([0.0, 100.0, 50.0]))
    assert rib in fx.trails
    rib.finished = True
    fx.update(30.0)       # all points expire -> finished trail pruned
    assert rib not in fx.trails


# ------------------------------------------------- Task LC launch effects

def test_launch_effect_helpers_emit_into_pools():
    """muzzle_blast / rideout_plume / boost_plume / nose_puff /
    ignition_fireball all spawn live particles."""
    for name, args in (
            ("muzzle_blast", (np.array([0.0, 65.0, -180.0]),)),
            ("rideout_plume", (np.array([0.0, 90.0, -180.0]),
                               np.array([0.0, 1.0, 0.0]))),
            ("boost_plume", (np.array([0.0, 200.0, -180.0]),
                             np.array([0.0, 0.6, 0.8]))),
            ("nose_puff", (np.array([0.0, 150.0, -180.0]),
                           np.array([1.0, 0.0, 0.0]))),
            ("ignition_fireball", (np.array([0.0, 30.0, 0.0]),))):
        fx = Effects(seed=5)
        getattr(fx, name)(*args)
        assert int(fx.fire.alive.sum()) > 0, name
        if name != "nose_puff":              # puffs are fire-only
            assert int(fx.smoke.alive.sum()) > 0, name
        fx.update(0.1)
        assert np.isfinite(fx.smoke.pos[: fx.smoke._hi]).all()
        assert np.isfinite(fx.fire.pos[: fx.fire._hi]).all()


def test_boost_plume_blooms_vs_rideout():
    """The high-thrust plume is the violent beat: its fire sprites are
    several times the ride-out plume's."""
    a = Effects(seed=2)
    a.rideout_plume(np.zeros(3), np.array([0.0, 1.0, 0.0]))
    b = Effects(seed=2)
    b.boost_plume(np.zeros(3), np.array([0.0, 1.0, 0.0]))
    size_a = float(a.fire.size1[a.fire.alive].max())
    size_b = float(b.fire.size1[b.fire.alive].max())
    assert size_b >= 3.0 * size_a


def test_ignition_fireball_has_radial_smoke_donut():
    fx = Effects(seed=9)
    fx.ignition_fireball(np.array([0.0, 30.0, 0.0]))
    v = fx.smoke.vel[fx.smoke.alive]
    horiz = np.hypot(v[:, 0], v[:, 2])
    # a good share of the smoke is the expanding ground-level donut: its
    # horizontal radial speed dominates the vertical component
    assert (horiz > 2.0 * np.abs(v[:, 1])).sum() >= 12


def test_ribbon_per_point_color():
    rib = TrailRibbon()
    dark = (0.40, 0.39, 0.38)
    rib.add_point(np.array([0.0, 100.0, 0.0]))            # default cream
    rib.add_point(np.array([0.0, 100.0, 50.0]), col=dark)  # boost grey
    strip = rib.build_strip(np.array([200.0, 100.0, 0.0]))
    assert strip.shape == (4, 10)
    assert np.allclose(strip[0, 5:8], strip[1, 5:8])
    assert np.allclose(strip[2, 5:8], dark, atol=1e-6)     # fresh: birth color
    assert not np.allclose(strip[0, 5:8], strip[2, 5:8])   # colors differ
