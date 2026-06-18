"""M5 ship-class definitions (sim/enemy_ship_classes.py).

Contracts (spec 05 a):
  * each class instantiates with its def's ammo / hp / dims;
  * the GeneralDestroyer is NUMERICALLY identical to today's Destroyer
    (byte-identical default-fleet guarantee);
  * class identity is FOG-GATED — no class/role field leaks onto the player
    contact board before the hull is imaged (the contact stamp carries only
    a generic "ship" size + a weapon-less kind, never the role).
"""

import numpy as np
import pytest

from sim.contacts import _kind_of, _size_of
from sim.enemy_defense import SM2_MAX_INFLIGHT, TRACK_FORM_S
from sim.enemy_ship_classes import (AIR_DEFENSE_DEF, FLAGSHIP_DEF,
                                    GENERAL_DESTROYER_DEF, GROUND_ATTACK_DEF,
                                    AirDefenseShip, Flagship, GeneralDestroyer,
                                    GroundAttackShip, ShipClassDef)
from sim.enemy_ships import Destroyer
from sim.ships import SHIP_TYPES

ANCHOR = (0.0, 150_000.0)


# ---------------------------------------------------------------------------
# 1. Each class instantiates with its def's ammo / hp / dims
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cls,cdef", [
    (GeneralDestroyer, GENERAL_DESTROYER_DEF),
    (AirDefenseShip, AIR_DEFENSE_DEF),
    (GroundAttackShip, GROUND_ATTACK_DEF),
    (Flagship, FLAGSHIP_DEF),
])
def test_class_instantiates_from_its_def(cls, cdef):
    s = cls("u", ANCHOR)
    assert s.ship_type == cdef.ship_type
    assert s.sm2_ammo == cdef.sm2_ammo
    assert s.sm6_ammo == cdef.sm6_ammo
    assert s.ciws_ammo == cdef.ciws_ammo
    assert s.tomahawk_ammo == cdef.tomahawk_ammo
    assert s.sm2_max_inflight == cdef.sm2_max_inflight
    assert s.is_datalink_hub == cdef.is_datalink_hub
    assert s._track_form_s == pytest.approx(cdef.track_form_s)
    # dims/HP come from the SHIP_TYPES entry the def names
    spec = SHIP_TYPES[cdef.ship_type]
    assert s.length == spec["length"]
    assert s.beam == spec["beam"]
    assert s.height == spec["height"]
    assert s.speed == spec["speed"]
    assert s.hp == spec["hp"]


def test_ship_class_def_is_frozen():
    with pytest.raises((AttributeError, TypeError)):
        GENERAL_DESTROYER_DEF.role = "x"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2. GeneralDestroyer is byte-identical to today's Destroyer
# ---------------------------------------------------------------------------

def test_general_destroyer_numerically_matches_destroyer():
    """The default fleet is built from GeneralDestroyer; it must match the
    legacy Destroyer EXACTLY (ship_type, every magazine, dims, HP, the
    fire-control knobs at their LOCKED-const defaults)."""
    g = GeneralDestroyer("g", ANCHOR)
    d = Destroyer("d", ANCHOR)
    assert g.ship_type == d.ship_type == "destroyer"
    assert g.sm2_ammo == d.sm2_ammo
    assert g.sm6_ammo == d.sm6_ammo
    assert g.ciws_ammo == d.ciws_ammo
    assert g.tomahawk_ammo == d.tomahawk_ammo
    assert g.hp == d.hp
    assert (g.length, g.beam, g.height, g.speed) == \
           (d.length, d.beam, d.height, d.speed)
    # The new knobs default to the LOCKED constants -> inert in every path.
    assert g.sm2_max_inflight == SM2_MAX_INFLIGHT
    assert g._track_form_s == pytest.approx(TRACK_FORM_S)
    assert g.is_datalink_hub is False


def test_general_destroyer_obb_matches_destroyer():
    from sim.ships import HULL_DRAFT
    g = GeneralDestroyer("g", ANCHOR)
    spec = SHIP_TYPES["destroyer"]
    _c, half, _r = g.obb()
    assert np.allclose(half, [spec["beam"] / 2,
                              (spec["height"] + HULL_DRAFT) / 2,
                              spec["length"] / 2])


def _farthest_obb_corner_dist(ship):
    """Max distance from ship.pos to any of the 8 OBB corners — the true reach
    the damage.py bounding-sphere prefilter must NOT under-cover."""
    c, half, rot = ship.obb()
    maxd = 0.0
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            for sz in (-1.0, 1.0):
                corner = c + rot @ (half * np.array([sx, sy, sz]))
                maxd = max(maxd, float(np.linalg.norm(corner - ship.pos)))
    return maxd


@pytest.mark.parametrize("cls", [GeneralDestroyer, AirDefenseShip,
                                 GroundAttackShip, Flagship])
def test_hit_reach_covers_farthest_obb_corner(cls):
    """damage.py uses ship.hit_reach as a conservative bounding-sphere reject:
    any missile/ship pair farther apart than the sum of reaches is rejected
    BEFORE the exact OBB test.  So hit_reach must be >= the distance from
    ship.pos to the hull's farthest OBB corner, or a real grazing hit at the
    bow/stern is wrongly rejected.  Regression guard for the Flagship, whose
    non-destroyer dims were overwritten AFTER Ship.__init__ set hit_reach from
    the base 'destroyer' dims (the reach must be recomputed)."""
    s = cls("u", ANCHOR)
    assert s.hit_reach >= _farthest_obb_corner_dist(s) - 1e-9, (
        f"{cls.__name__} hit_reach {s.hit_reach} under-covers its farthest "
        f"OBB corner {_farthest_obb_corner_dist(s)}")


def test_general_destroyer_hit_reach_equals_legacy_destroyer():
    """BYTE-IDENTICAL guard: the GeneralDestroyer (default-fleet hull) keeps the
    legacy destroyer dims, so the recomputed hit_reach must match the legacy
    Destroyer's EXACTLY (no perturbation of the default battle's prefilter)."""
    g = GeneralDestroyer("g", ANCHOR)
    d = Destroyer("d", ANCHOR)
    assert g.hit_reach == d.hit_reach


# ---------------------------------------------------------------------------
# 3. Doctrinal differentiation (the classes are actually different)
# ---------------------------------------------------------------------------

def test_air_defense_has_more_sm2_capacity_than_general():
    aaw = AirDefenseShip("aaw", ANCHOR)
    gen = GeneralDestroyer("gen", ANCHOR)
    assert aaw.sm2_ammo > gen.sm2_ammo
    assert aaw.sm2_max_inflight > gen.sm2_max_inflight


def test_ground_attack_has_the_deepest_tlam_bank():
    ga = GroundAttackShip("ga", ANCHOR)
    gen = GeneralDestroyer("gen", ANCHOR)
    aaw = AirDefenseShip("aaw", ANCHOR)
    assert ga.tomahawk_ammo > gen.tomahawk_ammo
    assert ga.tomahawk_ammo > aaw.tomahawk_ammo


def test_only_flagship_is_a_datalink_hub():
    assert Flagship("f", ANCHOR).is_datalink_hub is True
    for cls in (GeneralDestroyer, AirDefenseShip, GroundAttackShip):
        assert cls("u", ANCHOR).is_datalink_hub is False


# ---------------------------------------------------------------------------
# 4. FOG: class identity never leaks onto the contact board
# ---------------------------------------------------------------------------

def test_class_identity_is_fog_gated_on_the_contact_board():
    """The contact stamp (_size_of / _kind_of — sim/contacts.py) is what the
    player picture carries.  For EVERY ship class it must read a generic
    surface "ship" size and a weapon-less (None) kind — the role/class is
    invisible until the hull is imaged (no class field on the board)."""
    for cls in (GeneralDestroyer, AirDefenseShip, GroundAttackShip, Flagship):
        s = cls("u", ANCHOR)
        assert _size_of(s) == "ship", (
            f"{cls.__name__} leaks a non-ship size class to the board")
        assert _kind_of(s) is None, (
            f"{cls.__name__} leaks a weapon/kind onto the board")
        # The role exists for tooling but is NOT a contact-board attribute the
        # gating path consumes (the board reads pos + _size_of + _kind_of only).
        assert hasattr(s, "ship_class_role")
        assert not hasattr(s, "radar_size"), (
            f"{cls.__name__} must not stamp an explicit radar_size (would "
            "leak/alter the fogged size class)")


def test_role_is_not_a_weapon_or_size_attribute():
    """Defensive: the role label is a plain string field, never wired into the
    duck-typed weapon/size provenance the board scrapes."""
    s = Flagship("f", ANCHOR)
    assert isinstance(s.ship_class_role, str)
    assert not hasattr(s, "weapon")
    assert not hasattr(s, "weapon_id")
