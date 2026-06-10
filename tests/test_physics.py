import numpy as np
from sim import physics as P


def test_density_falls():
    assert P.air_density(0.0) == 1.225
    assert P.air_density(14_000) < 0.3 * P.air_density(0.0)


def test_speed_of_sound_profile():
    assert 339 < P.speed_of_sound(0.0) <= 341
    assert np.isclose(P.speed_of_sound(20_000), 295.1)


def test_cd_curve_shape():
    assert P.cd_from_mach(0.5) < P.cd_from_mach(1.05)
    assert P.cd_from_mach(1.05) > P.cd_from_mach(2.0)
