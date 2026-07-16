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
    from world.clouds import build_noise
    w = build_noise(seed=7, cache_dir=None)["weather"]
    coverage = w[:, :, 0]
    assert (coverage < 0.1).mean() > 0.30          # big clear lanes (v5)
    assert (coverage > 0.4).mean() > 0.08          # honest cloud systems
    assert (coverage > 0.4).mean() < 0.45          # never wall-to-wall


def test_no_sim_module_imports_clouds():
    # LOCKED determinism guard (F3): the sim never reads the visual half.
    sim_dir = Path(__file__).resolve().parents[1] / "sim"
    pat = re.compile(r"^\s*(from|import)\s+world\.clouds", re.M)
    offenders = [p.name for p in sim_dir.glob("*.py")
                 if pat.search(p.read_text(encoding="utf-8", errors="ignore"))]
    assert offenders == []


def test_clouds_use_render_weather_clock_not_sim_time():
    root = Path(__file__).resolve().parents[1]
    sandbox = (root / "game" / "sandbox.py").read_text(encoding="utf-8")
    assert "self._cloud_time = 0.0" in sandbox
    assert "weather_dt = min(max(float(dt_real), 0.0), 0.05)" in sandbox
    assert "self._cloud_time += weather_dt" in sandbox
    assert "self.weather_effects.advance(weather_dt" in sandbox
    assert "clouds.draw(self.renderer, self.camera, self.world.sim_time)" not in sandbox
    assert "bind_shadow_uniforms(self.renderer.lit, 6, self.camera,\n                                        self.world.sim_time)" not in sandbox


def test_cloud_wind_is_slow_and_shared_with_shadows():
    root = Path(__file__).resolve().parents[1]
    clouds = (root / "world" / "clouds.py").read_text(encoding="utf-8")
    shaderlib = (root / "engine" / "shaderlib.py").read_text(encoding="utf-8")
    assert re.search(r"const float WIND_MS\s*=\s*3\.0;", clouds)
    assert "uniform vec2 u_cloud_wind_xz;" in shaderlib
    assert "uniform float u_cloud_tile_m;" in shaderlib
    assert "u_cloud_time * 18.0" not in shaderlib
