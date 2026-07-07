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

## Nits / next

- Dither speckle on cloud edges is visible in stills; acceptable in
  motion at 1600×900. A blue-noise texture or 2-tap average is the first
  polish knob if the playtest objects.
- v1 taxonomy renders the FAIR/PARTLY mix only (type channel biased to
  fair-cu/towering); stratus decks, supercells and cirrus arrive with the
  W-P6 atmosphere presets driving `u_coverage_bias` + the type channel.
- Cloud shadows on the sea/terrain: not modeled (v2 candidate with the
  day/night pass — sample the weathermap in the lit shader).
- First battle on a new seed pays the 5.2 s bake under BUILDING WORLD;
  cached after. Acceptable; a boot-thread bake is the fix if it annoys.
