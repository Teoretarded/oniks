# Clouds v5 — playtest fix plan (2026-07-07, evening playtest)

> **Status:** PLANNED → hand to implementer (Codex GPT-5.5 xhigh or any agent).
> Orchestrator (Fable) verifies every gate personally. Prior art:
> `docs/plans/volumetric_clouds_plan_2026-07-07.md`,
> `docs/clouds_run_log_2026-07-07.md`, implementation `world/clouds.py`.

## User playtest reports (v4, all confirmed against code)

| # | Report | Mechanism (exact) |
|---|--------|-------------------|
| R1 | "Clouds have a repeating pattern" (wallpaper motif, worst top-down) | `BASE_TILE_M = 6_000` — base shape noise repeats every 6 km; dozens of tiles visible from altitude. Weathermap varies over 300 km but the *shapes* are the 6 km tile. |
| R2 | "CRT-screen lines / color warp as you fly away" | 3D + 2D noise textures have **no mipmaps** (`GL_LINEAR` min filter). Minified noise at distance = moiré interference = scanlines. Compounded by R8 8-bit banding. |
| R3 | "Clouds morph/warp/shrink in real time, disappear out of view" | March reach ≈ 21 km total (128 steps, 60 m → 220 m cap). Cloud mass dissolves at a camera-centred ~21 km bubble; moving the camera moves the bubble → clouds "shrink"/"appear". Also horizontal in-slab rays hard-capped at `t1 = 3.0e4` (30 km). Also weathermap drift runs at **4×** wind (72 m/s) → visible coverage crawl. |
| R4 | "Ghosts — no shadows, no lighting depth" | σ = 0.011 too thin; ambient is a flat 2-color mix; sun-cone self-shadowing too weak to sculpt bases; **no cloud shadows on sea/terrain** (logged nit). |
| R5 | "Clouds everywhere on the map; overcast ≠ clouds everywhere" | Bake coverage formula (`mass*(0.30+0.70*puff)+0.35*mass²`) leaves few honest clear regions; FAIR should read ~3–4 okta with distinct systems and big blue lanes. |
| R6 | "Should render 400 km out — see a distant storm as a dark mass" | Same as R3 — after the march fix, verify slab-exit math + haze give horizon-distance clouds (slab top 14 km ⇒ geometric horizon of the deck is 400 km+). |

## LOCKED CONVENTIONS (unchanged — violations = instant review fail)

- Left-handed world (X east, Y up, Z north); **front face = CW**; the
  fullscreen NDC triangle is drawn with `GL_CULL_FACE` disabled.
- Log depth, exact formula: `gl_FragDepth = log2(max(1+w,1e-6)) * (u_log_depth_fcoef * 0.5)`.
- Geometry camera-relative f32; `u_cam_pos` world f32 for **noise lookups only**.
- Animation clock = **sim time** (replays identical). Never wall clock.
- Bake half of `world/clouds.py` stays GL-free; deferred GL imports in the class.
- No sim module imports `world/clouds.py` (grep-locked test).
- Never weaken a test to make it pass — report BLOCKED instead. Bake changes
  bump `CACHE_VERSION` ("v4" → "v5").
- Perf budgets (tools/perf_clouds.py): clouds ≤ 3.0 ms avg / 5.0 ms p95 at
  1600×900; frame ≤ 16 ms on a quiet machine. Escape ladder only if the gate
  fails: 128→96 steps → coverage pre-test skip → half-res FBO.

## Tasks (sequential; commit after each; conventional messages)

### T1 — Mipmaps + distance fades (kills R2)

`world/clouds.py` GL half:
- `_tex3` and the weathermap upload: set `GL_TEXTURE_MIN_FILTER` to
  `GL_LINEAR_MIPMAP_LINEAR` and call `glGenerateMipmap` after upload
  (`GL_TEXTURE_3D` / `GL_TEXTURE_2D`).
- Shader: fade the **detail erosion** to zero over march distance 8→25 km
  (`t`-based mix — far clouds don't need edge erosion, it's what aliases);
  past ~60 km let density lean on weathermap coverage × height profile with
  the base noise flattened toward its mean (0.5) so minification noise can't
  shimmer.

### T2 — Kill the 6 km wallpaper (R1)

In `density_at`:
- **Two-scale base**: second base sample at an irrational scale ratio,
  `texture(u_base_noise, (wp+drift) / (BASE_TILE*2.618))`, blend
  `base = mix(b1, b2, 0.38)` BEFORE the remap. Periods never visually align.
- **Domain warp**: warp the base lookup with a low-frequency offset derived
  from the existing weathermap (no new texture): sample
  `u_weather` at `wp.xz / (WEATHER_TILE*0.37) + 0.618` and use `(gb - 0.5)`
  channels as a horizontal offset of ±2.5 km applied to `wp.xz` for the base
  noise lookup only. Warp period ≫ 100 km ⇒ no repeat within the map.
- Document both formulas in the module docstring — W-P6 will mirror them on
  CPU (`sim/atmosphere.py` single-source contract).

### T3 — March to the horizon + stability (R3, R6)

- Replace fixed geometric stepping with **distance-proportional** stepping:
  `dt = clamp(t * 0.055, 60.0, 6000.0)` applied per step (t multiplies by
  ~1.055 ⇒ 128 steps reach ≥ 400 km from a 60 m start). With T1's mipmaps the
  far strides are clean; near-field keeps ≤ 60–90 m steps inside 2 km.
- Fix the near-horizontal branch: no `3.0e4` cap — compute honest slab exit;
  cap total march distance at `MARCH_DIST_CAP = 450e3`.
- Weathermap drift: 4× → 1× (`drift.xz * 4.0` → `* 1.0`). 72 m/s coverage
  crawl was visible morphing.
- Keep first-hit depth logic exactly as-is (playtest-fixed).

### T4 — Lighting depth (R4a)

- `SIGMA` 0.011 → 0.022 (denser cores, honest alpha).
- Sun cone: after the 6 fine taps add ONE coarse tap at 1.8 km along the sun
  dir (catches neighbouring towers shading this one).
- Ambient: multiply by `(0.35 + 0.65 * sun_T)` so self-shadowed bases darken
  instead of glowing flat, and tint shadowed ambient toward
  `vec3(0.62,0.70,0.85)` (blue shadow — reference signature #10).
- Slightly raise sun boost if needed to keep sunlit tops near-white
  (currently `* 9.0`).

### T5 — Cloud shadows on terrain & sea (R4b)

- New `CLOUD_SHADOW_GLSL` in `engine/shaderlib.py`: uniforms
  `sampler2D u_cloud_weather; vec2 u_cloud_cam_xz; float u_cloud_amt;
  float u_cloud_time;` and
  `float cloud_shadow(vec3 view_vec)`: world xz = `u_cloud_cam_xz +
  view_vec.xz`, project along the sun to the mid-slab: `xz -=
  (u_sun_dir.xz / max(u_sun_dir.y, 0.2)) * 2500.0`, apply the SAME drift
  formula as the cloud shader (`u_cloud_time * 18.0`, z `* 0.35`, ×1 scale),
  sample coverage (mip'd), return `1.0 - u_cloud_amt *
  smoothstep(0.30, 0.75, coverage)`, with `u_cloud_amt ≈ 0.5`.
- `engine/renderer.py` LIT_FRAG: multiply the `u_sun_color * ndl` diffuse
  term AND the spec term by `cloud_shadow(v_view_vec)` (hemi/ambient
  untouched). Same in `world/ocean.py`'s sun terms.
- Wiring: `Clouds` exposes `bind_shadow_uniforms(shader, unit)`;
  `game/sandbox.py` calls it for the lit + ocean shaders each frame (or
  renderer.set_common learns optional cloud params — implementer's choice,
  keep it minimal). When clouds are disabled/absent set `u_cloud_amt = 0`
  and bind nothing.
- GLSL note: `u_sun_dir` is already declared by HAZE_GLSL — CLOUD_SHADOW_GLSL
  must not redeclare it; concatenate after HAZE_GLSL.

### T6 — Honest weather cells (R5) — bake v5

- `build_noise`: sharpen the mass field (`_remap(mass_n, 0.50, 0.72, 0, 1)`),
  drop the `0.35*mass²` floor to `0.25*mass²`, and require puffs to live
  inside masses (`coverage = mass * (0.18 + 0.82*puff) + 0.25*mass*mass`).
  Target: big honest blue lanes between distinct systems.
- `CACHE_VERSION = "v5"`.
- Test contract update (spec-driven, NOT a weakening — FAIR ≈ 3–4 okta):

```python
def test_weathermap_has_cloud_and_gap_regions():
    from world.clouds import build_noise
    w = build_noise(seed=7, cache_dir=None)["weather"]
    coverage = w[:, :, 0]
    assert (coverage < 0.1).mean() > 0.30          # big clear lanes (v5)
    assert (coverage > 0.4).mean() > 0.08          # honest cloud systems
    assert (coverage > 0.4).mean() < 0.45          # never wall-to-wall
```

### T7 — Dither polish (R2 residual)

- Replace `hash12` start dither with interleaved gradient noise (IGN):
  `fract(52.9829189 * fract(0.06711056*x + 0.00583715*y))` — visibly less
  clumpy than the hash; keep amplitude = one step.

### T8 — Gates + docs

1. `pytest -q -n auto tests/test_cloud_bake.py` green (and full suite before
   final commit: `pytest -q -n auto`).
2. `python -m tools.perf_clouds` on a QUIET machine — budgets above; ladder
   only on failure.
3. `python -m tools.probe_cloud_shots 7` + TWO added views in `VIEWS`:
   `("high_lookdown", (0.0, 17_500.0, 60_000.0), 0.0, -1.2)` and
   `("far_field", (0.0, 2_000.0, 5_000.0), 0.0, 0.02)`.
4. Append results to `docs/clouds_run_log_2026-07-07.md` (v5 section).

## Visual signature checklist (judge screenshots against this)

Cumulus references: War Thunder Dagor cumulus banks; classic fair-weather-cu
aerial photography. Ten signatures:

1. Flat-ish darker bases, domed bright tops.
2. Sun-facing sides near-white; away sides gray-blue (~30–50 % darker).
3. FAIR mix: distinct clouds, honest blue between, big clear lanes.
4. Organization at 10–50 km (clusters/streets) with **no periodic motif** —
   compare any three screen regions of a top-down shot; none may match.
5. Crisp cauliflower detail near; soft haze-whitened far.
6. Ground shadow patches on sea/terrain aligned with overhead clouds.
7. Clouds visible to the horizon with perspective compression.
8. Zero scanline/moiré/banding at any altitude (17.5 km lookdown is the test).
9. Shapes world-anchored: flying toward/away must not reshape a cloud.
10. Self-shadowing: bases and cores darker, shadow tint slightly blue.

## Out of scope (backlog — do NOT build now)

- **W-P6 sensor/seeker weather occlusion**: CPU mirror of `density_at` in
  `sim/atmosphere.py` (same formulas — that's why T2 documents them), LOS
  optical-depth integral gating TV/EO seeker lock + degrading IR; rain bands
  attenuating radar per `weather_system_design_2026-07-07.md` PART 2. The
  no-cheat pattern applies (sensors read the sim picture, never truth).
- Night lighting + launch-flash illumination (needs the day/night pass).
- Weather presets driving `u_coverage_bias` + type channel (stratus deck,
  supercell, cirrus) — W-P6/P8.
- Boot-thread bake (first-seed 5 s stall under BUILDING WORLD).

## Environment facts (for the implementer)

- Windows 11, Python 3.11, run tests `pytest -q -n auto` (xdist installed).
- GPU RTX 3050 Laptop; GL 3.3 core; pygame window; screenshots via the probe
  tools (hidden window) — no display needed.
- Status protocol: DONE / DONE_WITH_CONCERNS / BLOCKED (+ why). Bad work is
  worse than no work — escalate instead of guessing.
