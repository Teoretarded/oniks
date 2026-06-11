# ONIKS test-loop log

Findings and iterations for the /loop directive: "test the game till your 100% satisfied —
physics works, game is optimized, models look good."

## Pre-loop backlog (noted during Phase A milestone review, 2026-06-10)

- [x] **Home coast has no cliffs.** Task 7 generation made a ~60 m rise over 2 km; spec says
  the Bastion battery sits on a cliff coastline. Steepen the shoreline rise (a few hundred
  meters horizontal) in `world/generation.py` — keep `test_height_continuity` (<30 m steps at
  50 m sampling) passing. Re-check `BASE_POS` height and sites tests after.
  — fixed in Task S5 (`feat: terrain cliff band and color detail`): ~45 m smoothstep cliff
  band over ~300 m where the coast runs; BASE_POS-dependent constants re-frozen.
- [x] **Land looks flat/featureless from altitude and offshore.** Single green tone dominates;
  color zones only read when zoomed. Add higher-frequency vertex-color variation (noise-modulated
  grass/scrub mottling), strengthen slope-based rock coloring, and consider a subtle
  AO-by-height term so relief reads at distance.
  — fixed in Task S5 (same commit): grass/scrub mottling, stronger slope rock,
  height-based brightening.
- [x] **Mid-distance wave glint pattern looks repetitive/tiled** in the overview shot (regular
  dot field). Consider rotating/adding a 4th wave component or fading specular gloss with
  distance to break up the regularity.
  — fixed in Task S5 (`feat: ocean glint variation`): 4th wave direction at an
  irrational-ish angle + distance-faded specular power/intensity.
- [x] **terrain_height is the tile-build bottleneck** (~50-100k pts/s; evaluates all 9 islands'
  fbm everywhere). Masked per-island evaluation = bit-identical ~3-10x speedup (Task 8 note).
  Do in the perf pass (Task 22) if tile streaming hitches show up.
  — closed in Task S6: the condition never triggered (budgeted streaming kept tile builds
  hitch-free through the v1 perf pass and the S6 re-gate); the per-step scalar queries got
  a bit-identical masked fast path (`terrain_height_scalar`) in Task 22 instead. The
  vectorized tile-build path stays a known follow-up if streaming ever hitches.

## Pre-loop backlog additions (Phase B+C milestone review)

- [x] **Bastion TEL needs an art pass.** Current model reads as a green slab with wheels; the
  launcher cam makes it a hero object. Needs: articulated cab (windows, fenders), visible
  chassis/axle line, beefier canister proportions with end caps and frame mounts, mudguards.
  — fixed in Task S5 (`feat: bastion TEL art pass`).
- [x] **Log-depth grazing-angle artifact** (terrain holes through huge LOD2 triangles at
  low land cameras) — fixed in Phase D Task 16b via fragment-shader gl_FragDepth.
- [x] Ocean wave stripes still read repetitive at mid distance in model scenes (same item
  as Phase A backlog — confirmed fixed after the Task S5 glint/wave variation pass).

## Pre-loop backlog additions (Phase D milestone review)

- [x] **16x time accel tanks to ~3.4 FPS** — per-ship Python loop in world.step dominates
  (Task 18 finding). Primary target for Task 22 perf pass (vectorize ship updates or batch
  the per-substep work).
  — fixed in Task 22 (`perf: 60fps worst-case scene`): scalar-math hot loops, packed-prefix
  particle pools, cached text, scalar culling; re-verified by the S6 perf re-gate below.
- [x] **Close-range hi-lo overshoot** — a hi-lo launch inside the ~105 km descent envelope
  climbs to 14 km, flies past, and circles back before killing. Fix as Phase E Task 22b:
  scale cruise altitude to the available distance.
  — fixed in Task 22b (`fix: scale hi-lo cruise altitude to route length for close-range
  shots`).
- [ ] Harbor site sits slightly inland; waterline-style harbor model looks odd up close
  (fine at gameplay distance). Candidate: nudge site seaward or add a shore apron.

## Iterations

- **2026-06-11 S6 perf re-gate (S-300 expansion complete).** Worst-case scene expanded with
  the 4 patrol aircraft (one shot down overhead: falling spiral + smoke/flame emission all
  600 frames) and 2 S-300s coasting in midcourse with full trail ribbons (honest
  out-of-envelope shots, steering every frame) on top of the v1 load (14 ships, 2 burning,
  4 Oniks airborne). Result: avg total 15.1 ms (runs 15.08/15.10/15.62) vs the 16.0 ms
  budget — PASS. Profile shows no new hot spot: SamMissile.update ~40 us and
  Aircraft.update ~7 us per call (both already scalar-math per the Task 22 pattern); the
  remaining cost is the pre-existing Oniks guidance + ship loops. Harness now warns if the
  scene sheds load mid-run (a SAM self-destructing would quietly lighten the measurement).
