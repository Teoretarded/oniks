"""CombatWorld (Phase 2): destroyers at sea, radar-gated picture, on-land
site, enemy defense controller wired into step()."""

from sim.enemy_ships import Destroyer
from world.combat import (COMBAT_SITES, DESTROYER_SPAWNS,
                          PLAYER_RADAR_RANGES, RADAR_STATION_XZ, CombatWorld)
from world.generation import terrain_height_scalar

DT = 1.0 / 120.0


def test_no_sandbox_traffic():
    """Phase 2: the only ships are the two enemy destroyers — none of the
    sandbox lane traffic, no aircraft, only the friendly radar site."""
    cw = CombatWorld()
    assert [s.ship_id for s in cw.ships] == [s["ship_id"]
                                             for s in DESTROYER_SPAWNS]
    assert all(isinstance(s, Destroyer) for s in cw.ships)
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
    assert cw.radar_net.radars == [cw.radar_station]
    assert cw.radar_station.ranges == PLAYER_RADAR_RANGES
    # the station stands ON the terrain (not floating / buried)
    assert cw.radar_station.pos[1] == terrain_height_scalar(*RADAR_STATION_XZ)


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
