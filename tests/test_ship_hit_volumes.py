"""Collision-volume alignment for rebuilt ship meshes."""

import numpy as np
import pytest

from sim.damage import apply_missile_hits, segment_hits_obb
from sim.enemy_air import Carrier
from sim.enemy_ship_classes import Flagship
from sim.enemy_ships import Destroyer
from sim.amphibious import Lcac, Transport
from sim.missile import PH_DEAD
from sim.ships import Ship, ST_ALIVE, ST_BURNING
from models.carrier import build_carrier
from models.destroyer import build_destroyer
from models.flagship import build_flagship
from models.ships_models import (build_cargo, build_lcac, build_tanker,
                                 build_transport, build_warship)


class _Round:
    def __init__(self, p0, p1):
        self.prev_pos = np.asarray(p0, dtype=np.float64)
        self.pos = np.asarray(p1, dtype=np.float64)
        self.alive = True
        self.phase = 5
        self.impact_pos = None


class _Weapon:
    weapon_id = "geometry_probe"
    warhead_mass = 250.0
    nose_hardness = 1.0


class _SubsystemRound(_Round):
    def __init__(self, p0, p1, velocity):
        super().__init__(p0, p1)
        self.vel = np.asarray(velocity, dtype=np.float64)
        self.mass = 2500.0
        self.weapon = _Weapon()
        self.is_hostile = False


def _volume_reach(ship):
    farthest = 0.0
    for center, half, rot in ship.hit_obbs():
        for sx in (-1.0, 1.0):
            for sy in (-1.0, 1.0):
                for sz in (-1.0, 1.0):
                    corner = center + rot @ (
                        half * np.array([sx, sy, sz], dtype=np.float64))
                    farthest = max(
                        farthest, float(np.linalg.norm(corner - ship.pos)))
    return farthest


def _cross_local(ship, local_center, axis=0, distance=30.0):
    """Return a world segment crossing local_center along one local axis."""
    rot = ship.obb()[2]
    delta = np.zeros(3, dtype=np.float64)
    delta[axis] = distance
    return (ship.pos + rot @ (local_center - delta),
            ship.pos + rot @ (local_center + delta))


def test_plain_ship_keeps_single_historical_hull_volume():
    ship = Ship("c", "cargo", [(0.0, 0.0), (0.0, 1000.0)], 0.25)
    volumes = ship.hit_obbs()
    assert len(volumes) == 1
    for actual, expected in zip(volumes[0], ship.obb()):
        assert np.array_equal(actual, expected)


def test_burke_topside_volume_catches_mast_but_not_empty_air():
    ship = Destroyer("ddg", (0.0, 0.0), heading_deg=37.0)
    hull, topside = ship.hit_obbs()
    mast_segment = _cross_local(ship, np.array([0.0, 35.0, 14.0]))
    assert not segment_hits_obb(*mast_segment, *hull)
    assert segment_hits_obb(*mast_segment, *topside)

    empty_segment = _cross_local(ship, np.array([0.0, 35.0, 50.0]))
    assert not any(segment_hits_obb(*empty_segment, *volume)
                   for volume in ship.hit_obbs())


def test_missile_sweep_uses_burke_compound_volume():
    ship = Destroyer("ddg", (0.0, 0.0), heading_deg=21.0)
    p0, p1 = _cross_local(ship, np.array([0.0, 35.0, 14.0]))
    round_ = _Round(p0, p1)
    effects = []
    apply_missile_hits([round_], [ship], effects)
    assert not round_.alive and round_.phase == PH_DEAD
    assert ship.state == ST_BURNING
    assert effects and effects[-1][0] == "ship_hit"


def test_carrier_deck_edge_and_high_island_have_separate_volumes():
    carrier = Carrier("cvn", (0.0, 0.0), heading_deg=-28.0)
    hull, deck, island, *_details = carrier.hit_obbs()

    deck_segment = _cross_local(
        carrier, np.array([35.0, 8.275, 100.0]), axis=1, distance=2.0)
    assert not segment_hits_obb(*deck_segment, *hull)
    assert segment_hits_obb(*deck_segment, *deck)

    island_segment = _cross_local(
        carrier, np.array([27.5, 42.0, 14.0]), axis=0, distance=12.0)
    assert not segment_hits_obb(*island_segment, *hull)
    assert segment_hits_obb(*island_segment, *island)


def test_carrier_hit_reach_covers_every_compound_corner():
    carrier = Carrier("cvn", (125.0, -480.0), heading_deg=63.0)
    assert carrier.hit_reach >= _volume_reach(carrier) - 1e-9


def test_clean_air_above_carrier_bow_remains_a_miss():
    carrier = Carrier("cvn", (0.0, 0.0))
    p0, p1 = _cross_local(
        carrier, np.array([0.0, 40.0, 120.0]), axis=0, distance=60.0)
    round_ = _Round(p0, p1)
    apply_missile_hits([round_], [carrier], [])
    assert round_.alive
    assert carrier.state == ST_ALIVE


def test_subsystem_uses_earliest_compound_entry_and_kills_high_island():
    """A diving chord meets the island before deck/hull; that exact entry must
    seed damage, while the historical effect/impact position stays midpoint."""
    carrier = Carrier("cvn", (0.0, 0.0))
    p0 = carrier.pos + np.array([27.5, 60.0, 14.0])
    p1 = carrier.pos + np.array([27.5, -20.0, 14.0])
    round_ = _SubsystemRound(p0, p1, (0.0, -680.0, 0.0))
    effects = []

    apply_missile_hits(
        [round_], [carrier], effects, damage_model="subsystem")

    assert "island" in carrier._dmg.dead_modules
    z, y, x = round_.hitcam["entry"]
    assert z == pytest.approx((14.0 + 166.5) / 333.0)
    assert y == pytest.approx(1.4)  # actual island top y=48.6 m
    assert x == pytest.approx(27.5 / 20.0)
    midpoint = (p0 + p1) * 0.5
    assert np.allclose(round_.impact_pos, midpoint)
    assert any(kind == "ship_hit" and np.allclose(pos, midpoint)
               for kind, pos in effects)


def test_subsystem_accepts_deck_only_hit_outside_waterline_hull():
    carrier = Carrier("cvn", (0.0, 0.0))
    p0 = carrier.pos + np.array([35.0, 20.0, 100.0])
    p1 = carrier.pos + np.array([35.0, 0.0, 100.0])
    round_ = _SubsystemRound(p0, p1, (0.0, -680.0, 0.0))

    apply_missile_hits(
        [round_], [carrier], [], damage_model="subsystem")

    assert not round_.alive
    assert hasattr(carrier, "_dmg")
    assert round_.hitcam["entry"][1] == pytest.approx(
        8.85 * 1.4 / carrier.damage_height)


def _mesh_is_inside_hit_volumes(ship, builder):
    vertices = builder().vertices[:, :3].astype(np.float64)
    world = vertices + ship.pos
    covered = np.zeros(len(vertices), dtype=bool)
    for center, half, rot in ship.hit_obbs():
        local = (world - center) @ rot
        covered |= np.all(np.abs(local) <= half + 1e-5, axis=1)
    return covered


@pytest.mark.parametrize(("ship_factory", "builder"), (
    (lambda: Ship("cargo", "cargo", [(0.0, 0.0), (0.0, 1000.0)], 0.0),
     build_cargo),
    (lambda: Ship("tanker", "tanker", [(0.0, 0.0), (0.0, 1000.0)], 0.0),
     build_tanker),
    (lambda: Ship("warship", "warship", [(0.0, 0.0), (0.0, 1000.0)], 0.0),
     build_warship),
    (lambda: Destroyer("destroyer", (0.0, 0.0)), build_destroyer),
    (lambda: Flagship("flagship", (0.0, 0.0)), build_flagship),
    (lambda: Carrier("carrier", (0.0, 0.0)), build_carrier),
    (lambda: Transport("transport", (0.0, 0.0)), build_transport),
    (lambda: Lcac("lcac", (0.0, 0.0), (0.0, 1000.0)), build_lcac),
))
def test_rebuilt_mesh_vertices_are_covered_by_actual_hit_volumes(
        ship_factory, builder):
    ship = ship_factory()
    covered = _mesh_is_inside_hit_volumes(ship, builder)
    assert covered.all(), f"{np.count_nonzero(~covered)} mesh vertices uncovered"


@pytest.mark.parametrize(("ship_factory", "draft", "collision_top", "grid_top"), (
    (lambda: Ship("cargo", "cargo", [(0.0, 0.0), (0.0, 1000.0)], 0.0),
     2.0, 22.0, 22.0),
    (lambda: Ship("tanker", "tanker", [(0.0, 0.0), (0.0, 1000.0)], 0.0),
     2.0, 20.0, 20.0),
    (lambda: Ship("warship", "warship", [(0.0, 0.0), (0.0, 1000.0)], 0.0),
     2.0, 7.5, 28.22),
    (lambda: Destroyer("destroyer", (0.0, 0.0)), 6.0, 30.0, 39.427433),
    (lambda: Carrier("carrier", (0.0, 0.0)), 9.0, 7.5, 48.6),
    (lambda: Transport("transport", (0.0, 0.0)), 2.0, 9.2, 36.25),
    (lambda: Lcac("lcac", (0.0, 0.0), (0.0, 1000.0)), 1.0, 4.6, 4.6),
))
def test_visual_draft_collision_top_and_damage_top_are_explicit(
        ship_factory, draft, collision_top, grid_top):
    ship = ship_factory()
    assert ship.draft == pytest.approx(draft)
    assert ship.collision_height == pytest.approx(collision_top)
    assert ship.damage_height == pytest.approx(grid_top)
    center, half, rot = ship.obb()
    local_center = rot.T @ (center - ship.pos)
    assert local_center[1] - half[1] == pytest.approx(-draft)
    assert local_center[1] + half[1] == pytest.approx(collision_top)
    assert ship.hit_reach >= _volume_reach(ship) - 1e-9
