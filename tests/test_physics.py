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


def test_scalar_fast_paths_match_vectorized():
    """Task 22 perf: the *_scalar variants must match the numpy versions."""
    rng = np.random.default_rng(5)
    for alt in [*rng.uniform(-100.0, 25_000.0, 50), 0.0, 10_999.9,
                11_000.0, 11_000.1]:
        alt = float(alt)
        assert P.speed_of_sound_scalar(alt) == float(P.speed_of_sound(alt))
        for speed in (0.0, 150.0, 700.0, 900.0):
            assert P.mach_scalar(speed, alt) == float(P.mach(speed, alt))
            cd = 0.31
            assert np.isclose(P.drag_force_scalar(speed, alt, cd, 0.35),
                              float(P.drag_force(speed, alt, cd, 0.35)),
                              rtol=1e-12)
    for m in [*rng.uniform(-0.5, 3.0, 200), 0.0, 0.80, 1.05, 2.0, 2.3, 9.9]:
        m = float(m)
        assert np.isclose(P.cd_from_mach_scalar(m), float(P.cd_from_mach(m)),
                          rtol=1e-12), f"cd mismatch at mach {m}"
