"""Magazine-detonation effect (audit item 2, 2026-07-17).

The sim's catastrophic cook-off event (sim/damage_model._catastrophe ->
("magazine_detonation", pos)) must map to a DEDICATED effect that reads
bigger than any single warhead hit, sized from the Hopkinson-Cranz fireball
radius (sim.damage_model.fireball_radius_m — finally consumed).  GL-free:
only the numpy pools are exercised.
"""

import numpy as np

from engine.particles import Effects
from sim.damage_model import COOK_SINK_TNT_KG, fireball_radius_m


def _live_counts(fx: Effects):
    return (int(fx.fire.alive.sum()), int(fx.smoke.alive.sum()),
            int(fx.spray.alive.sum()))


def test_magazine_detonation_spawns_all_pools():
    fx = Effects(seed=7)
    fx.magazine_detonation((0.0, 6.0, 0.0),
                           fireball_radius_m(250.0), water=False)
    fire, smoke, spray = _live_counts(fx)
    assert fire >= 60, f"fireball too thin: {fire} fire sprites"
    assert smoke >= 100, f"column too thin: {smoke} smoke sprites"
    assert spray >= 30, f"no ejecta arcs: {spray} spray sprites"


def test_magazine_detonation_outscales_ship_hit_explosion():
    """The cook-off must read BIGGER than the standard ship-hit explosion
    (the audit found it fell through to a SMALLER generic blast)."""
    mag = Effects(seed=3)
    mag.magazine_detonation((0.0, 6.0, 0.0), fireball_radius_m(250.0))
    hit = Effects(seed=3)
    hit.explosion((0.0, 6.0, 0.0), 1.6)   # game/sandbox EXPLOSION_SCALE_SHIP
    mag_fire, mag_smoke, _ = _live_counts(mag)
    hit_fire, hit_smoke, _ = _live_counts(hit)
    assert mag_fire > hit_fire
    assert mag_smoke > hit_smoke
    # Peak sprite size too: the smoke wall must dwarf a warhead hit's column.
    assert float(mag.smoke.size1[mag.smoke.alive].max()) > \
        float(hit.smoke.size1[hit.smoke.alive].max())


def test_magazine_detonation_scales_with_yield():
    """Bigger magazine -> bigger fireball radius -> bigger sprites (the
    Hopkinson-Cranz sizing is genuinely consumed, not cosmetic)."""
    small = Effects(seed=11)
    small.magazine_detonation((0.0, 6.0, 0.0),
                              fireball_radius_m(COOK_SINK_TNT_KG))
    big = Effects(seed=11)
    big.magazine_detonation((0.0, 6.0, 0.0), fireball_radius_m(1000.0))
    assert float(big.fire.size1[big.fire.alive].max()) > \
        float(small.fire.size1[small.fire.alive].max())


def test_magazine_detonation_water_adds_splash():
    dry = Effects(seed=5)
    dry.magazine_detonation((0.0, 6.0, 0.0), 20.0, water=False)
    wet = Effects(seed=5)
    wet.magazine_detonation((0.0, 6.0, 0.0), 20.0, water=True)
    assert int(wet.spray.alive.sum()) > int(dry.spray.alive.sum())


def test_magazine_detonation_deterministic():
    a = Effects(seed=42)
    a.magazine_detonation((10.0, 6.0, -4.0), 21.0, water=True)
    b = Effects(seed=42)
    b.magazine_detonation((10.0, 6.0, -4.0), 21.0, water=True)
    for pool in ("fire", "smoke", "spray"):
        pa, pb = getattr(a, pool), getattr(b, pool)
        assert np.array_equal(pa.alive, pb.alive)
        assert np.allclose(pa.pos[pa.alive], pb.pos[pb.alive])


def test_sandbox_maps_the_event():
    """The event branch exists and consumes fireball_radius_m (source-level
    check — the sandbox event loop needs a live app/GL to run)."""
    import inspect

    import game.sandbox as sb
    src = inspect.getsource(sb.SandboxState._update_effects) if hasattr(
        sb.SandboxState, "_update_effects") else inspect.getsource(sb)
    assert "magazine_detonation" in src
    assert "fireball_radius_m" in src
    assert sb.MAGAZINE_REP_TNT_KG >= COOK_SINK_TNT_KG
