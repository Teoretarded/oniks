# Volumetric Clouds Implementation Plan (F3-P3/P4/P5)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans
> (inline, SOLO). Locked conventions from
> `feature_expansion_review_2026-07-06.md` §3 + PART 2 §12 of
> `weather_system_design_2026-07-07.md`.

**Goal:** Raymarched volumetric clouds — 5-type taxonomy, seeded unique per
battle, missiles fly through them — inside a hard perf gate that exists
before the shader does.

**Architecture:** `world/clouds.py` in two halves: a GL-free NumPy bake
(3D Perlin-Worley 128³ + Worley 32³ + 512² weathermap, `default_rng([seed,
17])`, disk-cached under `cache/`) importable by tests and later by
`sim/atmosphere.py` (the W-P6 CPU/GPU sync contract), and a deferred-GL
`Clouds` class (sky.py pattern) drawing a fullscreen pass LAST with depth
test ON, `gl_FragDepth` = slab-entry log depth (the exact locked formula:
`log2(1+w) * fcoef * 0.5`), premultiplied blend, `apply_haze` on the
result. **No FBO in v1.** Animation clock = sim time.

**Perf gate (F3-P3, built FIRST):** `tools/perf_clouds.py` reusing
`tools/perf_harness.py` machinery (FencePacer, throttle probe, section
report). Budget: cloud section ≤ 3.0 ms avg / 5.0 ms p95 at 1600×900;
whole frame ≤ 16 ms. Baseline (pre-clouds) numbers committed to the run
log. Escape ladder (F3-P5, only if the gate fails): march steps → march
distance → Low/Med/High setting → half-res FBO → temporal reprojection.

## Locked details

- Slab 300 m – 14,000 m; march ≤ 64 steps, early-out at transmittance
  < 0.01, march distance cap 60 km, dithered start (hash of pixel).
- Lighting: Beer–Lambert × powder (1−e^(−2τ)) × Henyey–Greenstein
  (g ≈ 0.55), 6-step sun cone march, ambient from the sky gradient pair.
- Weathermap 512² RGB over a 300 km periodic tile (REPEAT wrap; periodic
  bake so the seam is invisible): R = coverage, G = type (0 stratus →
  0.25 fair cu → 0.5 towering → 0.75 cumulonimbus → 1 cirrus band),
  B = top-height fraction. Per-column type drives the vertical density
  profile (§12 taxonomy). v1 bakes the FAIR/PARTLY mix; preset/type
  mixing knobs arrive with W-P6/P8 (`u_coverage_bias` reserved).
- Noise: base 128³ Perlin-Worley (Schneider remap), tile ~6 km; detail
  32³ Worley, tile ~1.2 km, erodes edges. R8 textures, REPEAT.
- Camera pos passed as world-space f32 (`u_cam_pos`) purely for NOISE
  sampling (float32 eps at 500 km ≈ 6 cm — no shimmer); ray dirs from
  `u_inv_proj_rot` (CPU inverse per frame). Geometry stays camera-relative.
- Determinism guard: no sim module imports world/clouds.py (grep-locked
  test); the bake half is GL-free.

## Tasks

1. **F3-P3 perf harness**: `tools/perf_clouds.py` — perf_harness scene +
   a `clouds` section (0 until clouds exist) + the two cloud budgets in
   the report; run, commit baseline numbers.
2. **Bake half**: `build_noise(seed)` → dict(base 128³ f32 0..1, detail
   32³, weathermap 512²×3); npz cache keyed `cache/clouds_{seed}.npz`;
   tests: determinism, shape/range, seed-sensitivity, no-sim-import guard.
3. **GL half**: `Clouds` class (textures, fullscreen tri, shader, draw
   after particles before HUD in game/sandbox.py render, sim-time clock,
   seed from world config); screenshot probe (`tools/probe_cloud_shots.py`
   renders 3 views hidden → renders/clouds_*.png) judged by eye against
   the named references.
4. **F3-P5 perf pass**: run the gate; apply the ladder only if it fails;
   commit final numbers.
5. Run log + memory + full suite.
