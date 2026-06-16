"""CombatWorld (Phase 2/7): destroyers at sea, radar-gated picture, on-land
site, enemy defense controller wired into step().

test_no_sandbox_traffic: UPDATED for Phase 7 — CombatWorld now uses seeded
fleet generation (sample_fleet) driven by CombatConfig.  The legacy
DESTROYER_SPAWNS 2-element constant is retired as the generation source;
ship counts are now config-driven (DEFAULT: 3 destroyers + 1 carrier).
The test now asserts ship count and type rather than exact IDs from the old
constant (updated to seeded-fleet truth).
"""

import numpy as np

from sim.enemy_ships import Destroyer
from world.combat import (COMBAT_SITES, PLAYER_RADAR_RANGES,
                          RADAR_STATION_XZ, CombatWorld)
from world.combat_config import DEFAULT as DEFAULT_CONFIG
from world.generation import terrain_height_scalar

DT = 1.0 / 120.0


def test_no_sandbox_traffic():
    """Phase 5a/7 (updated): the only ships are config.n_destroyers enemy
    destroyers plus EXACTLY one carrier (spec 5.4) — no sandbox lane
    traffic, no legacy aircraft (enemy air lives in cw.enemy_air), only
    the friendly radar site.  DEFAULT config: 3 destroyers + 1 carrier.

    Updated from legacy DESTROYER_SPAWNS (the 2-entry module constant is
    retired as the generation source) to seeded-fleet truth: count and
    type assertions rather than exact IDs.
    """
    cw = CombatWorld()
    n_d = DEFAULT_CONFIG.n_destroyers     # 3
    assert len(cw.ships) == n_d + 1      # n destroyers + 1 carrier
    d_ids = [s.ship_id for s in cw.ships if s.ship_type != "carrier"]
    assert all(d_id.startswith("destroyer_") for d_id in d_ids)
    assert len(d_ids) == n_d
    assert any(s.ship_id == "carrier_00" for s in cw.ships)
    assert all(isinstance(s, Destroyer) for s in cw.ships)
    assert [s.ship_type for s in cw.ships].count("carrier") == 1
    assert cw.aircraft == []
    assert cw.sites is COMBAT_SITES


def test_destroyers_spawn_in_open_water():
    cw = CombatWorld()
    for ship in cw.ships:
        x, z = float(ship.pos[0]), float(ship.pos[2])
        assert terrain_height_scalar(x, z) < -5.0


def test_defense_controller_covers_every_destroyer():
    cw = CombatWorld()
    assert [u.ship for u in cw.defense.units] == cw.ships


def test_radar_station_pin_is_on_dry_land():
    x, z = RADAR_STATION_XZ
    assert terrain_height_scalar(x, z) > 5.0


def test_contact_board_is_radar_gated():
    cw = CombatWorld()
    assert cw.contacts.visible_fn is not None
    # The ground station is the primary network node; Phase 6 adds the
    # Pantsir radars as additional nodes (their documented dual role —
    # point-defense sensor + contact-picture node, world/combat.py).
    assert cw.radar_station in cw.radar_net.radars
    pantsir_radars = [p.radar for p in cw.pantsirs]
    assert cw.radar_net.radars == [cw.radar_station] + pantsir_radars
    assert cw.radar_station.ranges == PLAYER_RADAR_RANGES
    # the station stands ON the terrain (not floating / buried)
    assert cw.radar_station.pos[1] == terrain_height_scalar(*RADAR_STATION_XZ)


def test_dead_missile_tracks_are_pruned():
    """Regression: the commander's picture.missile_tracks dict must not grow
    unbounded over a long match. prune_missile_tracks is wired into the picture
    feed, so a track with no live missile that was last seen > 30 s ago is
    dropped (a still-recent dead track lingers, mirroring live_missile_tracks'
    30 s age window)."""
    cw = CombatWorld(DEFAULT_CONFIG)
    pic = cw.commander.picture
    pic.update_missile_track("hostile_stale", np.zeros(3), np.zeros(3),
                             sim_time=0.0)
    pic.update_missile_track("hostile_recent", np.zeros(3), np.zeros(3),
                             sim_time=95.0)
    cw._feed_enemy_picture(0.25, now=100.0)   # 100 s in, no live player missile
    assert "hostile_stale" not in pic.missile_tracks   # 100 s old -> pruned
    assert "hostile_recent" in pic.missile_tracks       # 5 s old -> kept


def test_picture_stays_empty_and_s300_has_no_targets():
    """The destroyers sit 160+ km out at sea level — far past the player
    radar's ~50-75 km horizon against a hull — so no track may ever form
    (fog of war end-to-end), and the S-300 stays blind."""
    cw = CombatWorld()
    for _ in range(120):
        cw.step(DT)
    assert cw.contacts.tracks == {}
    # S-300 cannot fire blind: no air track id exists to pass
    assert cw.launch_sam("anything") is None
