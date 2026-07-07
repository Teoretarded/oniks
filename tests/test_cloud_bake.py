"""F3-P4 cloud noise bake contracts (GL-free half of world/clouds.py).

The bake feeds the GPU textures AND (W-P6) the sim's cloud-density
queries — determinism and seed-uniqueness are the load-bearing bits
('Minecraft seeds': same seed = identical field, new seed = new sky).
"""

import re
from pathlib import Path

import numpy as np


def test_bake_shapes_dtypes_ranges():
    from world.clouds import build_noise
    n = build_noise(seed=7, cache_dir=None)
    assert n["base"].shape == (128, 128, 128)
    assert n["detail"].shape == (32, 32, 32)
    assert n["weather"].shape == (512, 512, 3)
    for k in ("base", "detail", "weather"):
        arr = n[k]
        assert arr.dtype == np.float32
        assert 0.0 <= float(arr.min()) and float(arr.max()) <= 1.0
        assert float(arr.std()) > 0.02        # not a constant field


def test_bake_deterministic_and_seed_unique():
    from world.clouds import build_noise
    a = build_noise(seed=42, cache_dir=None)
    b = build_noise(seed=42, cache_dir=None)
    c = build_noise(seed=43, cache_dir=None)
    for k in ("base", "detail", "weather"):
        assert np.array_equal(a[k], b[k])          # bit-identical replay
        assert not np.array_equal(a[k], c[k])      # a new seed is a new sky


def test_bake_cache_roundtrip(tmp_path):
    from world.clouds import CACHE_VERSION, build_noise
    a = build_noise(seed=9, cache_dir=tmp_path)
    assert (tmp_path / f"clouds_{CACHE_VERSION}_seed9.npz").exists()
    b = build_noise(seed=9, cache_dir=tmp_path)    # loads the cache
    for k in ("base", "detail", "weather"):
        assert np.array_equal(a[k], b[k])


def test_weathermap_has_cloud_and_gap_regions():
    # The FAIR/PARTLY default mix must produce real coverage variation:
    # some columns cloudy, some clear — never a uniform overcast sheet.
    from world.clouds import build_noise
    w = build_noise(seed=7, cache_dir=None)["weather"]
    coverage = w[:, :, 0]
    assert (coverage < 0.1).mean() > 0.10          # honest gaps
    assert (coverage > 0.4).mean() > 0.10          # honest clouds


def test_no_sim_module_imports_clouds():
    # LOCKED determinism guard (F3): the sim never reads the visual half.
    sim_dir = Path(__file__).resolve().parents[1] / "sim"
    pat = re.compile(r"^\s*(from|import)\s+world\.clouds", re.M)
    offenders = [p.name for p in sim_dir.glob("*.py")
                 if pat.search(p.read_text(encoding="utf-8", errors="ignore"))]
    assert offenders == []
