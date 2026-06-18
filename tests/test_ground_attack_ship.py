"""M5 GroundAttackShip behavior (spec 05 c).

  * a GroundAttack ship's TLAM bank drains FIRST in a salvo (ammo accounting):
    the dedicated land-attack hull spends its deep magazine before the general
    escorts dip into their token self-defense TLAM;
  * the salvo fires ONLY at a back-plot cluster (fog): _fire_tomahawk_salvo
    flies the order's believed target_pos (a commander back-plot from the
    enemy picture), never the player's truth position.
"""

import numpy as np
import pytest

from sim.enemy_ship_classes import GroundAttackShip
from sim.enemy_strikes import SALVO_SIZE
from world.combat import CombatWorld
from world.combat_config import CombatConfig


def _mixed_world(seed=1337):
    """A task group with general escorts + ONE ground-attack hull (+ carrier)."""
    cfg = CombatConfig(seed=seed, n_destroyers=2, n_ground_attack=1)
    return CombatWorld(cfg)


def test_ground_attack_bank_drains_first_in_a_salvo():
    """A back-plot salvo draws its TLAM from the GroundAttack hull's deep bank
    BEFORE touching the general escorts' token self-defense TLAM."""
    cw = _mixed_world()
    ga = next(s for s in cw.ships if isinstance(s, GroundAttackShip))
    generals = [s for s in cw.ships
                if getattr(s, "ship_class_role", None) == "general"]

    ga_start = ga.tomahawk_ammo
    gen_start = {g.ship_id: g.tomahawk_ammo for g in generals}
    n_missiles_before = len(cw.missiles)

    # A commander-style TOMAHAWK_SALVO order at a believed (back-plotted) base
    # cluster — never the player's truth position.
    order = {"type": "tomahawk_salvo", "target_id": "cluster_0",
             "target_pos": np.array([0.0, 0.0, 150_000.0])}
    cw._fire_tomahawk_salvo(order)

    # SALVO_SIZE rounds spawned, ALL from the ground-attack bank.
    assert len(cw.missiles) - n_missiles_before == SALVO_SIZE
    assert ga.tomahawk_ammo == ga_start - SALVO_SIZE, (
        "the ground-attack bank must drain first")
    for g in generals:
        assert g.tomahawk_ammo == gen_start[g.ship_id], (
            f"general escort {g.ship_id} TLAM must be untouched while the "
            "ground-attack bank still has rounds")


def test_general_only_fleet_unchanged_salvo_order():
    """Byte-identical guard: with NO ground-attack ship the salvo draws from
    the general escorts in the legacy ship order (the sort is a no-op)."""
    cw = CombatWorld(CombatConfig(seed=1337, n_destroyers=3))
    generals = [s for s in cw.ships
                if getattr(s, "ship_class_role", None) == "general"]
    first_general = generals[0]
    start = first_general.tomahawk_ammo
    order = {"type": "tomahawk_salvo", "target_id": "c",
             "target_pos": np.array([0.0, 0.0, 150_000.0])}
    cw._fire_tomahawk_salvo(order)
    # The first general escort (legacy order) spends the first rounds.
    assert first_general.tomahawk_ammo == start - SALVO_SIZE


def test_salvo_flies_the_backplot_not_truth():
    """FOG: the salvo aims at the order's believed target_pos (a back-plot),
    refined ONLY by the terminal scene-match against KNOWN live structures —
    it never reads a player truth position.  A back-plot in empty water (no
    structure within the seeker basket) flies to those believed coordinates."""
    cw = _mixed_world()
    n_before = len(cw.missiles)
    backplot = np.array([12_345.0, 0.0, 140_000.0])   # arbitrary empty water
    order = {"type": "tomahawk_salvo", "target_id": "cluster_x",
             "target_pos": backplot}
    cw._fire_tomahawk_salvo(order)
    new = cw.missiles[n_before:]
    assert len(new) == SALVO_SIZE
    # Each round's terminal target is the believed XZ (no live structure near
    # the basket of this empty-water point -> the round flies the back-plot).
    for m in new:
        assert m.target_x == pytest.approx(float(backplot[0]))
        assert m.target_z == pytest.approx(float(backplot[2]))
