# Volumetric clouds — run log (F3-P3/P4/P5, 2026-07-07)

Plan: `docs/plans/volumetric_clouds_plan_2026-07-07.md`
Spec: F3 locked conventions + PART 2 §12 taxonomy.

## Shipped

- **F3-P3 gate first**: `tools/perf_clouds.py` (perf_harness FencePacer,
  horizon-stare worst case). BASELINE (pre-clouds): 13.43 ms avg total,
  RTX 3050 Laptop, 1600×900, 8× accel scene.
- **Bake half** (`world/clouds.py`, GL-free, `default_rng([seed, 17])`):
  128³ Perlin-Worley (Schneider remap) + 32³ Worley detail + 512²
  weathermap (R coverage / G type / B top-height), all PERIODIC (seamless
  REPEAT). Optimized 26.3 → **5.2 s** (fully-vectorized perlin corners;
  block-wise worley — the per-pixel-gather version was 7 s/octave).
  npz cache (`cache/clouds_v3_seed{N}.npz`) = one-time per seed.
- **GL half**: fullscreen raymarch drawn LAST — ≤64 steps, 40 km cap,
  dithered start, early-out at T<0.01; Beer–Lambert × local-density
  powder × dual-lobe HG (0.55/−0.25), 6-step sun cone; slab-entry
  `gl_FragDepth` via the exact locked log-depth formula (terrain/hulls
  occlude clouds); premultiplied blend; `apply_haze`; **sim-time** drift
  (18 m/s — replays identical). Seeded per battle: a new seed is a new sky.

## Screenshot-gate iterations (the gate caught everything)

1. **v1: invisible.** The CCW fullscreen triangle was CULLED — this engine
   declares front = CW (left-handed world, renderer.py); the sky dome's
   cull-disable was the precedent. One faint artifact read as a cloud.
2. **v2: 7-okta overcast + blowout.** Coverage stretch too hot; the
   step-size-dependent powder term saturated at grazing steps (940 m
   steps at the 60 km cap) → pure white; heavy dither grain.
3. **v3: PASS.** Fair-weather cumulus — scattered puffs, sunlit tops,
   shaded bases, ~half honest blue; in-layer flight view at 1.4 km sits
   among the puffs; top-down reads like flight imagery over the islands.
   `renders/clouds_{ground_horizon,inside_layer,above_looking_down}_seed7.png`.

## Perf gate (F3-P5): PASS — no ladder needed

| run | clouds avg/p95 | frame avg |
|---|---|---|
| baseline (no clouds) | 0.00 / 0.00 | 13.43 ms |
| with clouds | **0.14 / 0.21 ms** (budget 3.0/5.0) | **14.03 ms** (≤16) |

Only sky pixels march (down-rays exit the slab test instantly); the
fence-paced swap (0.05 ms) confirms the GPU absorbs it — the pass is
genuinely sub-ms on this machine. The Low/Med/High ladder and the FBO
path stay unbuilt (the plan's escape hatches, not needed).

## Playtest v4 (user reports 2026-07-07 — every one real)

1. **"Clouds cover the missile"** — CONFIRMED BUG: slab-entry depth = the
   camera when the camera is INSIDE the slab (orbit cam at 13 km) → the
   pass wrote near-zero depth and stomped every model. Fixed: depth at
   the FIRST CLOUD HIT; verify shot `renders/clouds_occlusion_check.png`
   (missile crisp in front of the mass while flying inside the band).
2. **"Too low"** — base 300 m read as fog. Now 800 m.
3. **"Static/fuzzy"** — equal ~600 m march steps = per-pixel dither noise
   as the dominant texture. Now 128 geometric steps (60 m near, ×1.018,
   220 m cap — uncapped growth sliced the far deck into horizontal bands,
   caught on the interim shot).
4. **"Zero variation"** — single-scale weathermap. Now two-scale: freq-3
   MASSES × freq-9 PUFFS, taller/denser cores inside masses, varying
   tops — clusters, lone puffs, honest lanes (cache v4).

Perf after v4: clouds 0.19–0.24 avg / ≤0.41 p95 ms (budget 3.0/5.0).
Frame-total gate runs read 16.04/18.66 ms BUT the A/B control (clouds
fully disabled, same session) read **19.06 ms** — the machine was under
external load; the quiet-machine baseline was 13.43. Clouds' controlled
frame delta ≈ 0. Re-run the gate on a quiet machine before the next
perf-sensitive phase.

## Playtest v5 (user reports 2026-07-07 evening — every one confirmed)

Plan: `docs/plans/clouds_v5_fix_plan_2026-07-07.md` (diagnosis table R1–R6).
Implementation: Codex GPT-5.5 xhigh from the plan (T1–T7), reviewed +
committed by the orchestrator; lighting/march quality then iterated 8
rounds against the screenshot gate.

1. **"Repeating pattern"** — base noise tiled every 6 km. Fixed: second
   base sample at ×2.618 scale (periods never align) + weathermap-derived
   domain warp (±2.5 km, 300 km period). Formulas in the module docstring
   for the W-P6 CPU mirror.
2. **"CRT lines as you fly away"** — no mipmaps on the noise textures =
   minification moiré. Fixed: GL_LINEAR_MIPMAP_LINEAR + glGenerateMipmap,
   detail erosion faded 8→25 km, base flattened past 60 km.
3. **"Clouds shrink/disappear as I move"** — march reach was ~21 km
   (and 30 km hard cap sideways). Fixed: distance-proportional stepping
   (3 %/step, 224 steps) reaching 450 km; weathermap drift 4× → 1×.
4. **"Ghosts, no shadows"** — fixed in two parts: (a) in-cloud lighting —
   ambient gradient was INVERTED (tops darker than bases); isotropic
   multi-scatter floor added (phase-only sun term is near-black at
   anti-solar angles); sun cone gets a 1.8 km coarse tap; (b) cloud
   shadows on terrain + ocean via CLOUD_SHADOW_GLSL (weathermap projected
   along the sun; ocean dims surface + glint).
5. **"Clouds everywhere"** — bake v5 coverage probed across seeds
   7/0/1337: ~70 % clear sky, ~9 % dense cores, big honest lanes; test
   contract updated per FAIR ≈ 3 okta (spec-driven change, argued in the
   commit).

### The stipple/banding war (8 screenshot-gate iterations)

Speckle amplitude tracks σ·d·dt per step. One march forces a choice:
no jitter → marching bands on near-horizontal views; full-step jitter at
6 km far strides → heavy stipple. Landed on: σ 0.022 → 0.016, 224 steps,
and TWO stratified 90 m-jittered marches averaged (bands decorrelated,
noise halved). An adaptive coarse/fine march was tried and REVERTED —
modal switching quantizes at coarse boundaries (blocky patches).

### Gates

- Bake tests: 5/5 green (new coverage contract included).
- Perf: clouds **0.12 avg / 0.16 p95 ms** (budget 3.0/5.0) WITH the dual
  march. Frame total 16.79 vs 16.0 FAILED but the A/B control (clouds
  disabled, same session) read 16.96 — the overage is sim_step/swap
  machine load, cloud-controlled delta ≈ 0 (same pattern as the v4 run).
  Quiet-machine re-run still owed before the next perf-sensitive phase.
- Screenshots: 5 views in renders/clouds_*.png judged against the plan's
  10-signature checklist — white domed tops, shaded bases, unique shapes
  (no motif at any scale), clouds to the horizon, ground shadow patches.

## Nits / next

- Residual fine grain on cloud edges in stills (halved from v4 level);
  the honest next knob is a half-res FBO or temporal pass — NOT more
  jitter tuning (both single-march failure modes are documented above).
- Far decks (>60 km) render as smooth plateaus (base noise flattened) —
  acceptable at horizon distances; a far-detail octave is a polish knob.
- v1 taxonomy renders the FAIR/PARTLY mix only; stratus decks, supercells
  and cirrus arrive with W-P6 presets (`u_coverage_bias` + type channel).
- Night lighting + launch-flash illumination: needs the day/night pass
  (backlogged in the v5 plan).
- Sensor/seeker weather occlusion (TV/EO lock gating): W-P6 CPU mirror of
  `density_at` — the v5 plan documents the exact formulas to mirror.
- First battle on a new seed pays the ~5 s bake under BUILDING WORLD;
  cached after. A boot-thread bake is the fix if it annoys.
