# ONIKS test-loop log

Findings and iterations for the /loop directive: "test the game till your 100% satisfied —
physics works, game is optimized, models look good."

## Pre-loop backlog (noted during Phase A milestone review, 2026-06-10)

- [ ] **Home coast has no cliffs.** Task 7 generation made a ~60 m rise over 2 km; spec says
  the Bastion battery sits on a cliff coastline. Steepen the shoreline rise (a few hundred
  meters horizontal) in `world/generation.py` — keep `test_height_continuity` (<30 m steps at
  50 m sampling) passing. Re-check `BASE_POS` height and sites tests after.
- [ ] **Land looks flat/featureless from altitude and offshore.** Single green tone dominates;
  color zones only read when zoomed. Add higher-frequency vertex-color variation (noise-modulated
  grass/scrub mottling), strengthen slope-based rock coloring, and consider a subtle
  AO-by-height term so relief reads at distance.
- [ ] **Mid-distance wave glint pattern looks repetitive/tiled** in the overview shot (regular
  dot field). Consider rotating/adding a 4th wave component or fading specular gloss with
  distance to break up the regularity.
- [ ] **terrain_height is the tile-build bottleneck** (~50-100k pts/s; evaluates all 9 islands'
  fbm everywhere). Masked per-island evaluation = bit-identical ~3-10x speedup (Task 8 note).
  Do in the perf pass (Task 22) if tile streaming hitches show up.

## Iterations

(filled in during Phase F)
