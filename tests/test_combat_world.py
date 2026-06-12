"""CombatWorld (Phase 1): empty traffic, radar-gated picture, on-land site."""

from world.combat import (COMBAT_SITES, PLAYER_RADAR_RANGES,
                          RADAR_STATION_XZ, CombatWorld)
from world.generation import terrain_height_scalar

DT = 1.0 / 120.0


def test_no_sandbox_traffic():
    cw = CombatWorld()
    assert cw.ships == []
    assert cw.aircraft == []
    assert cw.sites is COMBAT_SITES


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


def test_empty_world_steps_and_s300_has_no_targets():
    cw = CombatWorld()
    for _ in range(120):
        cw.step(DT)
    assert cw.contacts.tracks == {}
    # S-300 cannot fire blind: no air track id exists to pass
    assert cw.launch_sam("anything") is None
