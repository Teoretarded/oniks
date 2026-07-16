"""Signature checks for the researched ground-asset rebuilds."""

import numpy as np

from models import bastion as bastion_model
from models.bastion import build_bastion_tel
from models.common import PALETTE
from models.pantsir import build_pantsir
from models.s300 import build_s300_tel
from models.structures import build_fuel_depot, build_radar_station


def _color_mask(md, key):
    return np.all(np.isclose(md.vertices[:, 6:9], PALETTE[key], atol=1e-4),
                  axis=1)


def test_bastion_travel_enclosure_covers_tubes_and_opens_for_launch():
    stowed = build_bastion_tel(elevation_deg=0.0)
    tube = stowed.vertices[_color_mask(stowed, "oniks_body"), :3]

    # The horizontal pair sits wholly inside the long K-340P enclosure.
    assert tube[:, 2].min() >= bastion_model.SHROUD_Z0 - 0.10
    assert tube[:, 2].max() <= bastion_model.SHROUD_Z1
    assert tube[:, 1].max() <= bastion_model.SHROUD_TOP + 0.03

    # In launch state the two long roof leaves stand outside the closed
    # travel width, making a real opening around the erecting canisters.
    raised = build_bastion_tel(elevation_deg=88.0)
    p = raised.vertices[:, :3]
    green = _color_mask(raised, "mil_green")
    opened_lids = green & (np.abs(p[:, 0]) > 1.60) & (p[:, 1] > 3.50)
    assert opened_lids.any()


def test_s300_has_asymmetric_maz_nose_and_segmented_four_tube_pack():
    md = build_s300_tel(elevation_deg=0.0)
    p = md.vertices[:, :3]

    # Production 5P85: glazing occupies the left crew cab while the right
    # half is an engine/radiator housing, not another full-width windscreen.
    front_glass = p[_color_mask(md, "radome") & (p[:, 2] > 4.8)]
    assert len(front_glass) and front_glass[:, 0].max() < 0.0
    grille = p[_color_mask(md, "tire") & (p[:, 2] > 6.45)]
    assert len(grille) and (grille[:, 0] > 0.1).any()

    # Eight visible hoop stations across four tubes retain the 2x2 pack.
    rings = p[_color_mask(md, "tube_ring")]
    assert len(rings) >= 3_500
    assert rings[:, 0].min() < -1.1 and rings[:, 0].max() > 1.1
    assert rings[:, 2].max() - rings[:, 2].min() > 7.0


def test_pantsir_signature_arrays_and_round_tpk_racks_are_readable():
    md = build_pantsir()
    p = md.vertices[:, :3]

    # The broad acquisition array replaces the old tiny search-radar drum.
    high_radar = p[_color_mask(md, "radar_white") & (p[:, 1] > 3.35)]
    assert len(high_radar)
    assert high_radar[:, 0].max() - high_radar[:, 0].min() >= 2.15

    # Twelve cylindrical TPKs form distinct racks on both turret flanks.
    tubes = p[_color_mask(md, "tube_grey")]
    assert len(tubes) >= 750
    assert tubes[:, 0].min() < -1.7 and tubes[:, 0].max() > 1.7
    assert tubes[:, 1].max() - tubes[:, 1].min() >= 1.25


def test_radar_station_uses_a_braced_tower_inside_the_existing_envelope():
    md = build_radar_station()
    p = md.vertices[:, :3]
    dark = _color_mask(md, "mil_green_dark")

    tower = p[dark & (np.abs(p[:, 0]) < 3.0) &
              (np.abs(p[:, 2]) < 3.0) & (p[:, 1] > 5.0)]
    assert len(tower) >= 500
    assert tower[:, 1].max() >= 13.5
    assert np.ptp(p, axis=0)[0] <= 14.0
    assert np.ptp(p, axis=0)[1] <= 22.0
    assert np.ptp(p, axis=0)[2] <= 14.0


def test_fuel_depot_has_cone_roofs_access_and_secondary_containment():
    md = build_fuel_depot()
    p = md.vertices[:, :3]

    concrete = p[_color_mask(md, "concrete")]
    assert np.ptp(concrete[:, 0]) >= 68.0
    assert np.ptp(concrete[:, 2]) >= 39.5

    # Roof vents and full-height access ladders rise above the 12 m shells.
    pipe = p[_color_mask(md, "pipe")]
    assert pipe[:, 1].max() >= 13.6
    tanks = p[_color_mask(md, "tank_white")]
    assert 13.2 <= tanks[:, 1].max() <= 14.0
