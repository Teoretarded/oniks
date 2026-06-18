"""tests/test_heightfield.py — M3-terrain F3: the HeightField refactor.

A PURE, BIT-IDENTICAL refactor. ``generation.HeightField`` is the seam that a
later presets task will swap; the DEFAULT field MUST reproduce today's terrain
byte-for-byte for sensors, missiles and determinism. These tests pin:

(a) BIT-IDENTICAL default — HeightField() methods == the historical module
    functions EXACTLY (==, no tolerance) over a large fixed grid incl. base /
    SAM / island coords and every mask/skirt/cliff boundary.
(b) SHIM identity — the module terrain_height / terrain_height_scalar /
    surface_height_scalar delegate to DEFAULT_FIELD and return identically.
(c) LOS routing — terrain_blocks(a, b, height_fn=field.height_scalar) ==
    terrain_blocks(a, b) (default) over a fixed sensor/target grid.
(d) SYMMETRY / no-cheat — in a built CombatWorld every Radar / recon object's
    height_fn IS the world's field.height_scalar (player AND enemy), and the
    world's terrain-LOS accessor reads the SAME field — no side reads another.
(e) max_height — HeightField().max_height == 430.0, == the module constant.
"""

import math

import numpy as np

from world import generation as G
from sim.radar import Radar, terrain_blocks
from world.combat import CombatWorld
from world.combat_config import CombatConfig


# --------------------------------------------------------------------------
# Fixed grid spanning the whole map plus every tricky boundary the fast paths
# key on. Shared by the bit-identical + shim + LOS tests.
# --------------------------------------------------------------------------

def _grid_points():
    rng = np.random.default_rng(202606)
    xs = list(rng.uniform(-340_000.0, 340_000.0, 400))
    zs = list(rng.uniform(-40_000.0, 560_000.0, 400))
    # Hand-picked stress points: base, SAM, coast bands, shelf cutoffs, cliff
    # band crossings, mid ocean, enemy coast.
    for x, z in [
        (G.BASE_POS[0], G.BASE_POS[2]),
        (G.SAM_SITE_POS[0], G.SAM_SITE_POS[2]),
        (0.0, -600.0), (0.0, 1_000.0), (0.0, 2_500.0), (0.0, 2_499.0),
        (0.0, 14_500.0), (0.0, 14_499.9), (0.0, 150_000.0),
        (0.0, 485_500.0), (0.0, 499_000.0), (0.0, 530_000.0),
        (12_345.6, 200_000.0), (0.0, 300.0), (0.0, 0.0), (0.0, -150.0),
        (0.0, -450.0), (40_000.0, 200.0), (40_000.0, -300.0),
        (0.0, 497_500.0), (0.0, 497_501.0), (0.0, 501_500.0),
        (30_000.0, 499_200.0),
    ]:
        xs.append(x)
        zs.append(z)
    # Site coords (radar/depot/harbor) and island center/shoreline/skirt rings.
    for s in G.SITES:
        xs.append(float(s["pos"][0]))
        zs.append(float(s["pos"][1]))
    for cx, cz, r, _peak in G.ISLANDS:
        for d in (0.0, 0.5 * r, 0.999 * r, float(r), 1.001 * r, 1.8 * r):
            xs.append(cx + d)
            zs.append(cz)
            xs.append(cx)
            zs.append(cz - d)
    return np.array(xs, dtype=np.float64), np.array(zs, dtype=np.float64)


# --------------------------------------------------------------------------
# (a) BIT-IDENTICAL default field vs the historical module functions
# --------------------------------------------------------------------------

def test_heightfield_vectorized_bit_identical():
    """HeightField().height(X, Z) == terrain_height(X, Z) EXACTLY."""
    xs, zs = _grid_points()
    field = G.HeightField()
    got = field.height(xs, zs)
    expect = G.terrain_height(xs, zs)
    assert got.shape == expect.shape
    assert np.array_equal(got, expect)


def test_heightfield_scalar_bit_identical():
    """field.height_scalar(x, z) == terrain_height_scalar(x, z) EXACTLY."""
    xs, zs = _grid_points()
    field = G.HeightField()
    for x, z in zip(xs, zs):
        x = float(x)
        z = float(z)
        got = field.height_scalar(x, z)
        expect = G.terrain_height_scalar(x, z)
        assert got == expect, f"scalar mismatch at ({x}, {z}): {got!r} != {expect!r}"


def test_heightfield_surface_bit_identical():
    """field.surface_scalar(x, z) == surface_height_scalar(x, z) EXACTLY."""
    xs, zs = _grid_points()
    field = G.HeightField()
    for x, z in zip(xs, zs):
        x = float(x)
        z = float(z)
        got = field.surface_scalar(x, z)
        expect = G.surface_height_scalar(x, z)
        assert got == expect, f"surface mismatch at ({x}, {z}): {got!r} != {expect!r}"


def test_heightfield_scalar_matches_own_vectorized():
    """Internal consistency: a field's own scalar path == its own vectorized
    path (the same contract test_generation pins on the module functions)."""
    xs, zs = _grid_points()
    field = G.HeightField()
    expect = field.height(xs, zs)
    for x, z, e in zip(xs, zs, expect):
        got = field.height_scalar(float(x), float(z))
        assert got == e, f"self-mismatch at ({x}, {z}): {got!r} != {e!r}"


# --------------------------------------------------------------------------
# (b) SHIM identity — module funcs delegate to DEFAULT_FIELD
# --------------------------------------------------------------------------

def test_default_field_exists_and_is_a_heightfield():
    assert isinstance(G.DEFAULT_FIELD, G.HeightField)


def test_module_shims_match_default_field():
    """The module terrain_height / terrain_height_scalar / surface_height_scalar
    return identically to DEFAULT_FIELD's methods across the grid."""
    xs, zs = _grid_points()
    df = G.DEFAULT_FIELD
    assert np.array_equal(G.terrain_height(xs, zs), df.height(xs, zs))
    for x, z in zip(xs, zs):
        x = float(x)
        z = float(z)
        assert G.terrain_height_scalar(x, z) == df.height_scalar(x, z)
        assert G.surface_height_scalar(x, z) == df.surface_scalar(x, z)


def test_is_land_shim_matches_default_field():
    xs, zs = _grid_points()
    a = G.is_land(xs, zs)
    b = G.DEFAULT_FIELD.height(xs, zs) > 0.0
    assert np.array_equal(a, b)


# --------------------------------------------------------------------------
# (c) LOS routing — terrain_blocks honours field.height_scalar identically
# --------------------------------------------------------------------------

def _los_pairs():
    """A fixed grid of (sensor, target) 3-D pairs spanning coasts, islands and
    open ocean so terrain_blocks exercises clear AND blocked sight lines."""
    pairs = []
    # Player radar station-ish low mast to assorted low/high targets.
    src_lo = (0.0, 18.0, -600.0)
    src_hi = (52_000.0, 25.0, 137_000.0)   # near island/site
    targets = [
        (0.0, 50.0, 150_000.0),            # over deep ocean
        (140_000.0, 30.0, 260_000.0),      # toward depot/island
        (-120_000.0, 10.0, 180_000.0),     # toward small island
        (95_000.0, 8.0, 355_000.0),        # low skimmer past an island
        (30_000.0, 12.0, 499_200.0),       # toward enemy harbor
        (0.0, 200.0, 250_000.0),           # high-altitude clear shot
        (52_000.0, 400.0, 140_000.0),      # straight at an island peak
    ]
    for src in (src_lo, src_hi):
        for t in targets:
            pairs.append((src, t))
    return pairs


def test_terrain_blocks_routes_through_field_scalar():
    """terrain_blocks(a, b, height_fn=field.height_scalar) is identical to the
    default (module shim) for the default field over a fixed LOS grid."""
    field = G.HeightField()
    for a, b in _los_pairs():
        ref = terrain_blocks(a, b)
        routed = terrain_blocks(a, b, height_fn=field.height_scalar)
        assert routed == ref, f"LOS mismatch a={a} b={b}: {routed} != {ref}"


def test_radar_detects_routes_height_fn():
    """A Radar built with height_fn=field.height_scalar detects identically to
    a Radar built with the module default, for the default field."""
    ranges = {"ship": 400_000.0, "fighter": 300_000.0,
              "missile": 200_000.0, "stealth": 150_000.0}
    field = G.HeightField()
    pos = (0.0, G.terrain_height_scalar(0.0, -600.0), -600.0)
    r_default = Radar("r_def", pos, 18.0, ranges)
    r_field = Radar("r_fld", pos, 18.0, ranges, height_fn=field.height_scalar)
    for _src, tgt in _los_pairs():
        for sc in ("ship", "fighter", "missile", "stealth"):
            assert r_default.detects(tgt, sc) == r_field.detects(tgt, sc)


def test_radar_default_height_fn_is_module_shim():
    """Existing callers (no height_fn) must remain byte-identical: the default
    is the module terrain_height_scalar shim."""
    from world import generation as gen
    r = Radar("r", (0.0, 0.0, 0.0), 10.0, {"ship": 1.0})
    assert r._height_fn is gen.terrain_height_scalar


# --------------------------------------------------------------------------
# (d) SYMMETRY / no-cheat — one field, read by player AND enemy
# --------------------------------------------------------------------------

def _build_world():
    # Enable an enemy ground radar so the enemy-ground-radar construction site
    # is exercised; default everything else (byte-identical default battle).
    return CombatWorld(CombatConfig(seed=1337, n_enemy_radars=1))


def test_world_has_height_field():
    w = _build_world()
    assert hasattr(w, "height_field")
    assert isinstance(w.height_field, G.HeightField)
    # The default map's field IS (or is bit-equal to) the default field.
    assert w.height_field.max_height == G.TERRAIN_MAX_HEIGHT


def test_world_height_fn_is_the_field_scalar():
    """The world's cached terrain callable IS the active field's scalar query
    (equal — accessing the bound method gives a fresh wrapper each time, so the
    contract is value-equality to field.height_scalar, identity to ``_height_fn``)."""
    w = _build_world()
    assert w._height_fn == w.height_field.height_scalar
    # And it actually computes the field's terrain.
    assert w._height_fn(0.0, -600.0) == w.height_field.height_scalar(0.0, -600.0)


def test_player_radar_reads_world_field():
    w = _build_world()
    assert w.radar_station._height_fn is w._height_fn


def test_enemy_ground_radars_read_world_field():
    w = _build_world()
    assert w._enemy_ground_radars, "expected at least one enemy ground radar"
    for r in w._enemy_ground_radars:
        assert r._height_fn is w._height_fn


def test_enemy_air_radars_read_world_field():
    """Fighter nose radars and the AWACS radar (the enemy airborne sensor net)
    must read the SAME field as the player — no asymmetry, no truth leak."""
    w = _build_world()
    hf = w._height_fn
    checked = 0
    for e in w.enemy_air:
        radar = getattr(e, "radar", None)
        if radar is None:
            continue
        inner = getattr(radar, "_radar", radar)   # FighterRadar wraps ._radar
        assert inner._height_fn is hf, f"{getattr(e, 'aircraft_id', e)} radar field differs"
        checked += 1
    assert checked >= 2, "expected fighter + AWACS radars to be checked"


def test_recon_sensors_read_world_field():
    """The drone airframe, ELINT and RWR receivers all read the world field."""
    w = _build_world()
    hf = w._height_fn
    assert w.drone._height_fn is hf
    assert w.elint._height_fn is hf
    assert w.rwr._height_fn is hf


def test_world_terrain_accessor_reads_field():
    """The world's terrain-LOS accessor (used by SAM / missile / strike LOS)
    must resolve to the SAME field — so a SAM round and the player radar read
    one terrain truth."""
    w = _build_world()
    xs, zs = _grid_points()
    for x, z in zip(xs[:80], zs[:80]):
        x = float(x)
        z = float(z)
        assert w.terrain_height_at(x, z) == w.height_field.height_scalar(x, z)
        assert w.surface_height_at(x, z) == w.height_field.surface_scalar(x, z)


def test_world_field_symmetry_player_and_enemy_same_instance():
    """The decisive no-cheat assertion: every terrain-reading sensor on BOTH
    sides shares ONE callable identity — there is no second field anywhere."""
    w = _build_world()
    hf = w._height_fn
    fns = {id(w.radar_station._height_fn)}
    for r in w._enemy_ground_radars:
        fns.add(id(r._height_fn))
    for e in w.enemy_air:
        radar = getattr(e, "radar", None)
        if radar is None:
            continue
        inner = getattr(radar, "_radar", radar)
        fns.add(id(inner._height_fn))
    fns.add(id(w.drone._height_fn))
    fns.add(id(w.elint._height_fn))
    assert fns == {id(hf)}, "more than one terrain field in play across sides"


def test_jammer_beacon_reads_world_field():
    """With an escort jammer fielded (n_jammers>=1) its beacon must share the
    ONE world field too — the 'no second field anywhere' invariant proven for
    the jammer config, not just the no-jammer default (2026-06-18 review gap)."""
    w = CombatWorld(CombatConfig(seed=1337, n_enemy_radars=1, n_jammers=1))
    hf = w._height_fn
    assert w._jammers, "expected at least one escort jammer"
    for j in w._jammers:
        assert j.emitter._height_fn is hf
        assert j.radar._height_fn is hf      # .radar is the same beacon object


# --------------------------------------------------------------------------
# (e) max_height — default field's ceiling is 430 and the flyer skip is intact
# --------------------------------------------------------------------------

def test_max_height_is_430():
    assert G.HeightField().max_height == 430.0
    assert G.HeightField().max_height == G.TERRAIN_MAX_HEIGHT


def test_no_terrain_exceeds_field_max_height():
    """A flyer above max_height skips ground queries; the field must honour
    that bound everywhere (the optimization result is unchanged)."""
    field = G.HeightField()
    x = np.linspace(-340_000, 340_000, 600)
    z = np.linspace(-40_000, 560_000, 600)
    assert field.height(x[None, :], z[:, None]).max() < field.max_height
