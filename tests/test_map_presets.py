"""tests/test_map_presets.py — M3-terrain F4: seeded map presets.

Four selectable battle maps that finally exercise the terrain-masking +
radar-horizon physics:

    0 OPEN SEA   = today's default layout (BYTE-IDENTICAL gate)
    1 ARCHIPELAGO
    2 NARROW STRAIT
    3 FJORD COAST

Contracts pinned here (spec 09 F4):

(a) PRESET 0 BYTE-IDENTICAL — make_field(0, seed).height(grid) ==
    HeightField().height(grid) EXACTLY over a large fixed grid, for ANY seed
    (preset 0 ignores the seed for terrain).
(b) DETERMINISM — make_field(p, s) twice -> identical heights for all p; a
    different seed -> a content diff for presets 1-3; same seed+preset replays.
(c) MASKING BITES — on Archipelago / Strait / Fjord there EXIST sensor/target
    pairs where terrain_blocks is True (terrain is actually used); on Open Sea
    masking is rare. A known shadow target is masked from a known sensor.
(d) SYMMETRY / HONESTY — on each preset the world's player AND enemy sensors
    share ONE field instance; a target hidden by terrain is hidden from both.
(e) max_height respected — field.height(grid).max() < field.max_height for
    every preset (incl. the Fjord's taller max); the flyer-skip holds.
(g) SPAWNS VALID — no ship spawns on land for any preset
    (field.height_scalar <= 0 at every ship spawn point).
"""

import math

import numpy as np
import pytest

from world import generation as G
from world.generation import HeightField, make_field
from sim.radar import terrain_blocks
from world.combat import CombatWorld
from world.combat_config import (CombatConfig, MAP_PRESET_NAMES,
                                 CLAMP_MAP_PRESET)

PRESETS = (0, 1, 2, 3)
SEEDED_PRESETS = (1, 2, 3)


# --------------------------------------------------------------------------
# Shared fixed grid (whole map + coast/island boundaries).
# --------------------------------------------------------------------------

def _grid():
    rng = np.random.default_rng(606)
    xs = rng.uniform(-340_000.0, 340_000.0, 500)
    zs = rng.uniform(-40_000.0, 560_000.0, 500)
    # Hand-picked coast / cluster stress points (home + enemy continents).
    extra = [
        (G.BASE_POS[0], G.BASE_POS[2]), (G.SAM_SITE_POS[0], G.SAM_SITE_POS[2]),
        (40_000.0, -6_000.0), (0.0, 2_500.0), (0.0, 150_000.0),
        (60_000.0, 516_000.0), (0.0, 502_000.0), (30_000.0, 499_200.0),
    ]
    xs = np.concatenate([xs, [p[0] for p in extra]])
    zs = np.concatenate([zs, [p[1] for p in extra]])
    return xs, zs


# --------------------------------------------------------------------------
# (a) PRESET 0 BYTE-IDENTICAL
# --------------------------------------------------------------------------

def test_preset0_is_the_default_field_object():
    """make_field(0, s) returns the module DEFAULT_FIELD (the byte-identical
    default map) regardless of seed."""
    assert make_field(0, 1337) is G.DEFAULT_FIELD
    assert make_field(0, 99) is G.DEFAULT_FIELD
    assert make_field(0, -5) is G.DEFAULT_FIELD


def test_preset0_byte_identical_vectorized():
    """make_field(0, seed).height == HeightField().height EXACTLY, any seed."""
    xs, zs = _grid()
    ref = HeightField().height(xs, zs)
    for seed in (1337, 0, 7, 123456):
        got = make_field(0, seed).height(xs, zs)
        assert np.array_equal(got, ref), f"preset 0 not byte-identical at seed {seed}"


def test_preset0_byte_identical_scalar():
    """Scalar path of preset 0 matches the module shim EXACTLY."""
    xs, zs = _grid()
    f = make_field(0, 1337)
    for x, z in zip(xs[:120], zs[:120]):
        x, z = float(x), float(z)
        assert f.height_scalar(x, z) == G.terrain_height_scalar(x, z)


def test_preset0_max_height_unchanged():
    assert make_field(0, 1337).max_height == G.TERRAIN_MAX_HEIGHT


# --------------------------------------------------------------------------
# (b) DETERMINISM
# --------------------------------------------------------------------------

def test_every_preset_determinism_same_seed():
    """make_field(p, s) twice -> identical heights for every preset."""
    xs, zs = _grid()
    for p in PRESETS:
        a = make_field(p, 4242).height(xs, zs)
        b = make_field(p, 4242).height(xs, zs)
        assert np.array_equal(a, b), f"preset {p} not deterministic"


def test_seeded_presets_diff_with_seed():
    """Presets 1-3 produce DIFFERENT terrain (a content diff) for different
    seeds — the islands move with the seed."""
    xs, zs = _grid()
    for p in SEEDED_PRESETS:
        a = make_field(p, 1).height(xs, zs)
        b = make_field(p, 2).height(xs, zs)
        assert not np.array_equal(a, b), (
            f"preset {p} ignored the seed (same terrain for seeds 1 and 2)")


def test_seeded_presets_islands_differ_from_default():
    """Presets 1-3 are NOT the default map (their islands differ from preset 0)."""
    xs, zs = _grid()
    ref = make_field(0, 1337).height(xs, zs)
    for p in SEEDED_PRESETS:
        got = make_field(p, 1337).height(xs, zs)
        assert not np.array_equal(got, ref), f"preset {p} == default map"


def test_preset_island_lists_are_seeded():
    """Presets 1-3 carry a non-empty island list that varies with the seed."""
    for p in SEEDED_PRESETS:
        f1 = make_field(p, 11)
        f2 = make_field(p, 22)
        assert len(f1.islands) > 0
        assert f1.islands != f2.islands, f"preset {p} islands not seed-driven"


# --------------------------------------------------------------------------
# Home-coast cluster geometry is STABLE across presets (LOCKED pins survive)
# --------------------------------------------------------------------------

def test_home_and_enemy_cluster_terrain_stable_across_presets():
    """The base / SAM / radar / airfield / enemy-radar pins must read the
    SAME terrain height on every preset — presets vary mid-ocean + enemy
    approaches, never the home/enemy coast cluster sites."""
    pins = [
        (G.BASE_POS[0], G.BASE_POS[2]),
        (G.SAM_SITE_POS[0], G.SAM_SITE_POS[2]),
        (40_000.0, -6_000.0),            # player radar station
        (1_200.0, -600.0), (83_700.0, -3_500.0),   # Pantsir pads
        (60_000.0, 516_000.0),           # enemy airfield
        (0.0, 502_000.0), (30_000.0, 499_200.0),   # enemy radar band / harbor
    ]
    ref = make_field(0, 1337)
    for p in PRESETS:
        f = make_field(p, 1337)
        for x, z in pins:
            assert f.height_scalar(x, z) == ref.height_scalar(x, z), (
                f"preset {p} moved cluster terrain at ({x}, {z})")


# --------------------------------------------------------------------------
# (e) max_height respected (incl. Fjord's taller ceiling)
# --------------------------------------------------------------------------

def test_max_height_respected_every_preset():
    """field.height(grid).max() < field.max_height for every preset; the
    flyer-skip optimization (a flyer above max_height skips ground queries)
    stays valid."""
    x = np.linspace(-340_000, 340_000, 700)
    z = np.linspace(-40_000, 560_000, 700)
    for p in PRESETS:
        f = make_field(p, 1337)
        peak = f.height(x[None, :], z[:, None]).max()
        assert peak < f.max_height, (
            f"preset {p} peak {peak:.1f} >= max_height {f.max_height}")


def test_fjord_has_taller_max_height():
    """The Fjord (preset 3) uses a taller per-field max_height than the
    default 430 m (steeper walls), and still respects it."""
    fjord = make_field(3, 1337)
    assert fjord.max_height > G.TERRAIN_MAX_HEIGHT, (
        "Fjord must raise its terrain ceiling above the default 430 m")


# --------------------------------------------------------------------------
# (c) MASKING BITES
# --------------------------------------------------------------------------

def _islands_in_fleet_band(field):
    """Islands sitting in the mid-ocean fleet band (z 60-440 km) — the ones a
    sea-skim sight line can hide behind."""
    return [isl for isl in field.islands if 60_000.0 < isl[1] < 440_000.0]


def _find_masked_pair(field):
    """Find a (sensor, target) pair where a tall island masks a low target:
    sensor on one side of an island, low target on the far side, both near
    sea level. Returns (a, b) or None."""
    for cx, cz, r, peak in field.islands:
        if peak < 120.0:
            continue
        # Sensor 1.5 island-radii south at low mast; target 1.5 radii north
        # at sea level — the sight line grazes the island crest.
        a = (cx, 20.0, cz - 1.5 * r)
        b = (cx, 8.0, cz + 1.5 * r)
        if terrain_blocks(a, b, height_fn=field.height_scalar):
            return a, b
    return None


@pytest.mark.parametrize("preset", SEEDED_PRESETS)
def test_masking_bites_on_terrain_presets(preset):
    """On Archipelago / Strait / Fjord there EXISTS a sensor/target pair where
    terrain_blocks is True — terrain is actually consulted by the LOS."""
    field = make_field(preset, 1337)
    assert _islands_in_fleet_band(field), (
        f"preset {preset} has no mid-ocean islands to mask behind")
    pair = _find_masked_pair(field)
    assert pair is not None, (
        f"preset {preset}: no terrain-masked sensor/target pair found")


def test_open_sea_masking_is_rare():
    """Open Sea: a sea-skim sight line across the open fleet band is CLEAR
    (the default map has no islands in the deep-water duel corridor)."""
    field = make_field(0, 1337)
    # The canonical Oniks-vs-SM-2 open-water duel corridor (mid ocean, deep).
    a = (0.0, 20.0, 150_000.0)
    b = (0.0, 20.0, 330_000.0)
    assert not terrain_blocks(a, b, height_fn=field.height_scalar)


@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize("seed", (1337, 99, 7))
def test_central_duel_corridor_stays_clear(preset, seed):
    """Every preset (every seed) keeps the central x=0 deep-water transit
    corridor CLEAR — the canonical Oniks-vs-SM-2 duel runs straight up the
    middle, so an island masking it would soft-lock the AI fire line. The
    presets carve islands OUT of the corridor; this is the WINNABLE guard."""
    field = make_field(preset, seed)
    a = (0.0, 20.0, 150_000.0)
    b = (0.0, 20.0, 330_000.0)
    assert not terrain_blocks(a, b, height_fn=field.height_scalar), (
        f"preset {preset} seed {seed}: central duel corridor masked")


# --------------------------------------------------------------------------
# (d) SYMMETRY / HONESTY — one field, read by player AND enemy
# --------------------------------------------------------------------------

@pytest.mark.parametrize("preset", PRESETS)
def test_world_builds_with_preset_field(preset):
    """A CombatWorld built with map_preset=p uses make_field(p, seed) as its
    one active field."""
    w = CombatWorld(CombatConfig(seed=1337, map_preset=preset))
    ref = make_field(preset, 1337)
    xs, zs = _grid()
    for x, z in zip(xs[:60], zs[:60]):
        x, z = float(x), float(z)
        assert w.height_field.height_scalar(x, z) == ref.height_scalar(x, z)


@pytest.mark.parametrize("preset", PRESETS)
def test_world_field_symmetry_player_and_enemy(preset):
    """The no-cheat assertion per preset: every terrain-reading sensor on BOTH
    sides shares ONE callable identity — no second field anywhere."""
    w = CombatWorld(CombatConfig(seed=1337, map_preset=preset, n_enemy_radars=1))
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
    assert fns == {id(hf)}, f"preset {preset}: more than one terrain field in play"


def test_default_preset_world_byte_identical_to_no_preset():
    """A world with map_preset=0 (the default) builds the SAME field object as
    a world with no map_preset set — the out-of-the-box battle is unchanged."""
    w_default = CombatWorld(CombatConfig(seed=1337))
    w_preset0 = CombatWorld(CombatConfig(seed=1337, map_preset=0))
    assert w_default.height_field is w_preset0.height_field
    assert w_default.height_field is G.DEFAULT_FIELD


# --------------------------------------------------------------------------
# (g) SPAWNS VALID — no ship spawns on land for any preset
# --------------------------------------------------------------------------

@pytest.mark.parametrize("preset", PRESETS)
def test_no_ship_spawns_on_land(preset):
    """Every ship hull spawns in open water on the ACTIVE preset field
    (field.height_scalar <= 0 at the spawn point)."""
    w = CombatWorld(CombatConfig(seed=1337, map_preset=preset, n_destroyers=6))
    hf = w.height_field.height_scalar
    for s in w.ships:
        x, z = float(s.pos[0]), float(s.pos[2])
        assert hf(x, z) <= 0.0, (
            f"preset {preset}: {s.ship_id} spawned on land "
            f"(h={hf(x, z):.1f}) at ({x:.0f}, {z:.0f})")


@pytest.mark.parametrize("preset", PRESETS)
def test_no_ship_spawns_on_land_alt_seed(preset):
    """Spawn validity holds for a second seed too (rejection sampling must
    dodge the preset islands, not just one lucky layout)."""
    w = CombatWorld(CombatConfig(seed=99, map_preset=preset, n_destroyers=8))
    hf = w.height_field.height_scalar
    for s in w.ships:
        x, z = float(s.pos[0]), float(s.pos[2])
        assert hf(x, z) <= 0.0, (
            f"preset {preset} seed 99: {s.ship_id} on land at ({x:.0f}, {z:.0f})")


@pytest.mark.parametrize("preset", PRESETS)
def test_enemy_radars_on_dry_land_every_preset(preset):
    """Enemy ground radars still sit on dry land on every preset (the enemy
    continent is stable)."""
    w = CombatWorld(CombatConfig(seed=1337, map_preset=preset, n_enemy_radars=3))
    hf = w.height_field.height_scalar
    for struct, _r in w.enemy_radars:
        x, z = float(struct.pos[0]), float(struct.pos[2])
        assert hf(x, z) > 0.0, (
            f"preset {preset}: enemy radar below sea level at ({x:.0f}, {z:.0f})")


# --------------------------------------------------------------------------
# Config surface: names table + clamp range
# --------------------------------------------------------------------------

def test_map_preset_names_table():
    assert MAP_PRESET_NAMES == ("OPEN SEA", "ARCHIPELAGO",
                                "NARROW STRAIT", "FJORD COAST")
    assert len(MAP_PRESET_NAMES) == CLAMP_MAP_PRESET[1] + 1
