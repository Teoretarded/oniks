"""Nuclear-burst timeline contracts (Glasstone numbers, two-sided).

GL-free: the pools in CinematicEffects are plain numpy; the timeline
itself is deterministic (fx.rng touches only particle jitter).
"""

from __future__ import annotations

import numpy as np

from game.cinematic_icbm import NuclearBurst
from game.cinematic_missiles import CinematicEffects

DT = 1.0 / 120.0


def test_fireball_growth_matches_glasstone():
    """1 Mt: ~2,200 m diameter by 10 s; early growth is fast."""
    b = NuclearBurst((0.0, 800.0, 0.0), 1000.0, 800.0)
    b.t = 0.05
    early = b._ball_r()
    assert 100.0 <= early <= 450.0          # already enormous at 50 ms
    b.t = 10.0
    assert abs(b._ball_r() - 1100.0) < 5.0  # the book number
    b.t = 60.0
    assert b._ball_r() <= 1100.0 * 1.4      # growth saturates


def test_ball_rises_at_the_book_rate_and_caps_out():
    b = NuclearBurst((0.0, 800.0, 0.0), 1000.0, 800.0)
    b.t = 12.0
    y12 = b._ball_y()
    b.t = 22.0
    y22 = b._ball_y()
    rate = (y22 - y12) / 10.0
    assert 80.0 <= rate <= 120.0            # ~100 m/s climb
    b.t = 400.0
    assert b._ball_y() - 800.0 <= b.cap_alt + 1.0   # tropopause ceiling


def test_yield_scales_the_whole_event():
    small = NuclearBurst((0.0, 0.0, 0.0), 20.0, 0.0)     # 20 kt
    big = NuclearBurst((0.0, 0.0, 0.0), 800.0, 0.0)      # 800 kt
    small.t = big.t = 10.0
    assert big._ball_r() > small._ball_r() * 3.0
    assert big.cap_alt > small.cap_alt


def test_burst_emits_flash_fireball_stem_cap_ring():
    """Drive the real pools 20 s: fire appears instantly, smoke builds
    a stem/ring, and by 15+ s cap smoke sits well above the ground."""
    fx = CinematicEffects(seed=3)
    b = NuclearBurst((0.0, 500.0, 0.0), 300.0, 500.0)
    seen_fire_early = False
    max_smoke_y = -1e9
    ring_reach = 0.0
    t = 0.0
    while t < 20.0:
        b.step(DT)
        b.emit(fx, DT)
        fx.update(DT)
        if t < 0.5 and bool(fx.fire.alive.any()):
            seen_fire_early = True
        alive = fx.smoke.alive
        if alive.any():
            max_smoke_y = max(max_smoke_y,
                              float(fx.smoke.pos[alive, 1].max()))
            ring_reach = max(ring_reach,
                             float(np.abs(fx.smoke.pos[alive, 0]).max()))
        t += DT
    assert seen_fire_early                   # the flash + fireball
    assert max_smoke_y > 500.0 + 800.0       # cap/stem far above ground
    assert ring_reach > 600.0                # the dust ring raced out
    assert not b.done                        # a burst lives ~2 minutes


def test_burst_timeline_is_deterministic():
    def run():
        fx = CinematicEffects(seed=3)
        b = NuclearBurst((0.0, 0.0, 0.0), 300.0, 0.0)
        for _ in range(int(5.0 / DT)):
            b.step(DT)
            b.emit(fx, DT)
            fx.update(DT)
        return fx.smoke.pos[fx.smoke.alive].copy()
    a, c = run(), run()
    assert np.array_equal(a, c)
