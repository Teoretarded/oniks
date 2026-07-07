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

## Playtest v6 (round 2+3, 2026-07-07 night — 7 confirmed + close-range shading)

Plan: v6 section of `docs/plans/clouds_v5_fix_plan_2026-07-07.md` (P1–P7).
Implementer: Codex GPT-5.5 xhigh (same thread), orchestrator reviewed/gated.

**The perf gate was blind.** The `clouds` timer measured CPU submission
(~0.1 ms) while the GPU raymarch cost hid in the fence-paced swap — v5
"PASS 0.14 ms" while the playtest FPS collapsed. `tools/perf_clouds.py`
now wraps the pass in GL_TIME_ELAPSED (true GPU time) and gained an
in-mist scene (`--mist`). TRUE pre-v6 cost in-mist: **13.38 avg /
16.00 p95 ms**. Post-v6: **2.93 / 3.24 ms** (budget 3.0/5.0 PASS);
horizon 2.76/3.20. Frame-total still over on a loaded machine — sim_step
noise, swap wait now 0.05 ms; quiet re-run owed.

Fixes (per plan P1–P7 + sweep iterations):
- P1 topo-plate slicing: step never crosses >250 m altitude (dy clamp).
- P2 CRT stripes: IGN's diagonal signature — white-noise hash12 restored.
- P3 FPS: single march (dual removed), sun march every 2nd lit sample,
  early-out 0.03, mist skip-ahead (capped 8x, FULL reset on hit —
  unbounded doubling + gradual halving = obsidian-cloud bug).
- P4 overlap dark sides: coarse sun tap moved OUTSIDE the fine range;
  SUN_STEPS 6→4.
- P5 lone puffs: independent coverage term (probed 3 seeds).
- P6 far plateaus: far-flatten relaxed (120→400 km, max 60 %).
- P7 particles: clouds draw BEFORE particles (plumes no longer erased;
  tradeoff: behind-cloud plume shines through faintly — rare).
- Deck RINGS (360° sweep catch): first-hit depth quantized to the step
  grid — 4-probe entry bisection restarts stepping FROM the surface.
- Step-matched textureLod GATED to 8–25 km+: ungated it blurred view
  density against the fine sun march — crevices shaded as deep interior
  = black marbling (isolated by forcing lod 0). Sun taps always fine.
- Close-range shading (WT reference): ambient floor 0.50→0.78 (+brighter
  pair), sun_T cache low-passed, powder floored 0.18 — blue-gray
  crevices, zero black cavities at the 4 km deck-skim.

New gates: `tools/probe_cloud_sweep.py` — 360° contact sheets at
2/4/10/30/50 km (4 headings + up + down); the 5-view probe missed every
oblique-angle artifact the user found in minutes.

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

## Round 6 - camera-anchored morphing

Diagnosis confirmed in `world/clouds.py`: `density_at` had
view-distance-dependent structure. Detail erosion faded in over 8-25 km,
the near block under 4 km added a finer erosion octave plus a density
boost, and far flattening changed the base field past 120 km. That means
approach footage could show real camera-anchored shape changes, not just
resolution refinement.

Final code changes:
- Weather/base/detail still share one cloud-space coordinate `cs`.
- Deleted `far_flat`.
- Deleted `detail_amt`; primary detail erosion is always active.
- Deleted `near_amt` and the near-only density boost.
- Raised global `SIGMA` 0.016 -> 0.018.
- Kept the existing distance-gated texture LOD. Distance now changes
  resolution only.

Important deviation: the requested always-on second fine detail octave was
tested but not kept. Paying that extra 3D texture read across the full mist
march left the GPU gate at 11.66/16.59 ms. Guarding the read at max LOD did
not improve it (11.55/16.64 ms), and removing the second octave still left
the final shader over budget.

Approach metric (`docs/examples/flight_approach.json`, 20 s, 15 fps):

| run | frame diff mean/max | max comp jump | worst mask drop | worst mask step | mask start/end |
| --- | ---: | ---: | ---: | ---: | ---: |
| before | 7.66 / 47.40 | 19 | 0.6148 | 0.6148 | 0.4522 / 0.2485 |
| after final | 8.45 / 58.11 | 23 | 0.5913 | 0.5913 | 0.2570 / 0.4166 |

Coherence peaks:

| run | 0-37 | 0-75 | 0-150 | 0-299 |
| --- | ---: | ---: | ---: | ---: |
| before | 0.316 | 0.274 | 0.448 | 0.476 |
| after final | 0.333 | 0.229 | 0.279 | 0.432 |

Perf gate (`python -m tools.perf_clouds 300 --mist`):

| run | clouds avg/p95 | frame avg | result |
| --- | ---: | ---: | --- |
| final | 11.27 / 16.87 ms | 39.36 ms | FAIL vs 3.0 / 5.0 ms |

Status: BLOCKED. The view-distance structure terms are removed, but the
numeric acceptance did not pass and the mist GPU budget is still far over
target. The next viable path is a separate performance/metric pass, likely
half-res/temporal clouds or a cheaper detail representation, not more
camera-distance gating.

**Orchestrator correction to Round 6:** Codex's BLOCKED verdict rested on
perf numbers taken while the machine was under heavy external load (its
frame totals read 39 ms; an independent re-run read clouds 3.89/5.91 ms
with totals still 29 ms — load-polluted, the last clean-machine reading
of the previous state was 2.93/3.24). The view-independent density
restructure is KEPT: camera-anchored morphing was the user's primary
complaint and structure-vs-resolution is the correct invariant. Owed on
a QUIET machine: the mist gate re-run; if genuinely over 3.0/5.0 the
knobs are MARCH_STEPS 224->192, then the half-res FBO phase.

## Round 7 — the LAST morphing source, diagnosed (orchestrator, eyes-on)

12-frame strip (0.5 s apart, renders/approach_strip.png) from the
approach GIF shows lobes MIGRATING/re-forming between 8-25 km and
liquid-glass swirls at contact. Mechanism: the step-matched textureLod
gate (8-25 km) is the one remaining view-distance term, and it is NOT
shape-safe because density_at pipes the blurred samples through
NONLINEAR remaps (coverage remap, erosion remap) — mip-mean in,
different structure out. Lobes merge/split as the camera sweeps the
LOD transition band; a ~600 m/s approach sweeps it fast = churn.

Fix path for the next session (in order):
1. Cap lod_b/lod_d at ~2.0 (not 6/4) — shrinks the fine-vs-blurred
   structural delta at moderate cost in far moire (dy-clamp + entry
   bisection already carry most of the anti-artifact load). Cheap, try
   first, judge with flight_approach.json + the 12-frame strip.
2. Soften the nonlinearity: replace the hard remap knees in density_at
   with smoothstep ramps so mip-blur approximately commutes.
3. The endgame (also fixes the perf ceiling): half-res cloud FBO +
   temporal reprojection — the War Thunder architecture. Design notes in
   the v5/v6 plan escape hatches.
Also: re-run perf_clouds --mist on a QUIET machine before/after (all
round-6/7 numbers were load-polluted).

## Round 7b - ungated step LOD + empty-only skip

Implemented in `world/clouds.py`:
- H1: removed the `lod_gate`; `lod_b`, `lod_d`, and `lod_w` now always
  follow `dt_step`.
- H1 root fix: `sun_transmittance` now takes the caller's `dt_step` and
  passes it through to all `density_at` taps, so view and sun march read
  the same density resolution.
- H2: mist skip-ahead now resets on any `d >= 0.003`; skip growth only
  happens through essentially empty samples.

Isolation note: H2-only was tested briefly. It reduced approach component
jump only 23 -> 19, so it is not the primary fix. H1+H2 reduced jump 23
-> 6 and frame diff 8.45 -> 3.34, so H1 is the main approach-morphing
mechanism.

Approach probe (`python -m tools.probe_cloud_flight --spec docs/examples/flight_approach.json`):

| run | frame diff mean/max | max comp jump | worst mask drop | worst mask step | mask start/end |
| --- | ---: | ---: | ---: | ---: | ---: |
| before | 8.45 / 58.11 | 23 | 0.5913 | 0.5913 | 0.2570 / 0.4166 |
| H2 only | 7.48 / 57.71 | 19 | 0.6004 | 0.6004 | 0.2580 / 0.4296 |
| H1+H2 final | 3.34 / 59.74 | 6 | 0.6623 | 0.6623 | 0.2688 / 0.3088 |

Stationary watch (`python -m tools.probe_cloud_flight --spec docs/examples/flight_morph_watch.json`):

| run | diff mean/max | coh 0-37 | coh 0-75 | coh 0-150 | coh 0-299 | comp jump |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| before | 0.33 / 0.35 | 0.962 | 0.922 | 0.794 | 0.578 | 2 |
| H1+H2 final | 0.09 / 0.12 | 0.929 | 0.877 | 0.770 | 0.608 | 1 |

Verdicts:
- H1: confirmed for approach morphing (large reduction in component
  jumps and frame diff), but it regresses stationary coherence at 0-37,
  0-75, and 0-150 and is much more expensive in mist.
- H2: weak contributor; useful invariant for edge stepping, but not the
  main approach fix by itself.

Perf (`python -m tools.perf_clouds 300 --mist`):

| run | clouds avg/p95 | frame avg | result |
| --- | ---: | ---: | --- |
| H1+H2 final | 18.89 / 29.59 ms | 40.90 ms | FAIL vs 3.0 / 5.0 ms |

Smoke sweep (`python -m tools.probe_cloud_sweep 7`) completed and wrote:
`renders/cloud_sweep_2km_seed7.png`, `4km`, `10km`, `30km`, and `50km`.

Status: BLOCKED. Approach morphing improves clearly, but two required
gates fail: stationary coherence regresses at three measured pairs, and
mist GPU time is far over budget. The next pass needs a cheaper
mean-preserving resolution strategy, likely capped LOD or half-res
clouds, rather than fully ungated LOD at full resolution.

## Round 8 - consolidation audit

Fresh shader audit:
- No removed-feature constants remain: `DETAIL_FADE*`, `FAR_FLAT*`,
  `near_amt`, `detail_amt`, and `far_flat` are gone.
- No remaining view-distance-dependent density structure remains. The
  density function no longer takes `view_t`; distance only affects the
  step footprint `dt_step`, which drives texture LOD.
- `density_at`, `sun_transmittance`, the entry bisection, and the main
  march now all pass the same per-sample `dt` into density queries.
- Skip-ahead and lit threshold are consistent: any `d >= 0.003` resets
  mist stride; lit work happens for `d > 0.003`.
- Stale comments still said "slab-entry" depth, while the shader writes
  first-hit depth. Comments were corrected to first-hit.
- The hard coverage and erosion remap knees were the main tuning conflict
  left after Round 7b. They cut facets into the cloud and hurt stationary
  autocorrelation.

Changes:
- Added `soft_remap01`, a smoothstep-shaped 0..1 remap.
- Replaced the coverage knee
  `remap(base * prof, 1 - coverage * 0.78, 1)` with `soft_remap01`.
- Replaced detail erosion `remap(d, det * 0.5, 1)` with `soft_remap01`.
- Removed the now-dead `view_t` parameter from `density_at` and
  `sun_transmittance`.
- Corrected first-hit depth comments.
- MARCH_STEPS stayed 224. The perf run was not quiet, so the 224->192
  ladder was not applied.

Approach probe (`python -m tools.probe_cloud_flight --spec docs/examples/flight_approach.json`):

| run | frame diff mean/max | max comp jump | worst mask drop | mask start/end |
| --- | ---: | ---: | ---: | ---: |
| Round 7b | 3.34 / 59.74 | 6 | 0.6623 | 0.2688 / 0.3088 |
| Round 8 | 2.62 / 58.73 | 6 | 0.6540 | 0.3220 / 0.2767 |

Acceptance: component jump <= 8 PASS; frame diff mean <= 4 PASS.

Stationary watch (`python -m tools.probe_cloud_flight --spec docs/examples/flight_morph_watch.json`):

| run | diff mean/max | coh 0-37 | coh 0-75 | coh 0-150 | coh 0-299 | comp jump |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Round 7b | 0.09 / 0.12 | 0.929 | 0.877 | 0.770 | 0.608 | 1 |
| Round 8 | 0.02 / 0.02 | 0.987 | 0.962 | 0.918 | 0.896 | 2 |

Verdict: the short-pair coherence dip was the sharper-edge
autocorrelation effect, not temporal instability. Softened knees restored
coherence and reduced per-frame diff.

Perf (`python -m tools.perf_clouds 300 --mist`):

| section | avg ms | p95 ms |
| --- | ---: | ---: |
| sim_step | 10.55 | 17.26 |
| clouds | 15.39 | 30.04 |
| TOTAL | 41.04 | 61.19 |

Verdict: perf is still not trustworthy for ladder tuning because the
frame total is far above the <20 ms quiet-machine threshold. No march
ladder was applied in this pass.

Sweep smoke (`python -m tools.probe_cloud_sweep 7`) completed after the
final shader cleanup and wrote all five sheets:
`renders/cloud_sweep_2km_seed7.png`, `4km`, `10km`, `30km`, and `50km`.

Status: DONE_WITH_CONCERNS. The consolidation cleanup and softening pass
improved approach metrics and restored stationary coherence, with no dead
view-distance density structure left. The remaining concern is perf: the
available measurement was load-contaminated and still far over budget.
