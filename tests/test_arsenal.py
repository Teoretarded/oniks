from sim.arsenal import ONIKS, WEAPONS


def test_oniks_definition_sane():
    assert ONIKS.launch_mass > ONIKS.fuel_mass + ONIKS.warhead_mass
    assert ONIKS.cruise_alt_hi > 10_000 and ONIKS.skim_alt < 20
    assert "oniks" in WEAPONS
