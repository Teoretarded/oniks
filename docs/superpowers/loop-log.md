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
- [x] Harbor site sits slightly inland; waterline-style harbor model looks odd up close
  (fine at gameplay distance). Candidate: nudge site seaward or add a shore apron.
  — fixed in Task GATE (`feat: feel & polish complete`): HARBOR KILO nudged from
  (30_000, 502_000) — 114 m up the coastal hill — to the foreshore at (30_000, 499_200)
  (terrain ~9.9 m, sites tests green); the model is drawn at the waterline 260 m seaward
  of the marker with a new shore apron slab in `build_harbor` joining the quay roots to
  the beach. Verified in renders: quays stand in the shallows, land rises behind.

## Iterations

- **2026-06-12 S-300 tip-over physics (user feel report, research-verified).**
  User felt the SAM still turned too fast off the launch. Research agent pinned the
  48N6: 1,900 kg, I_yy ~6,500 kg*m^2, gas-vane TVC (torque is never the limiter -
  the autopilot program is), and frame-timed footage: 30 deg off vertical ~1 s
  after ignition, 60 deg at ~2 s. Verdict: our 120 deg/s path cap was ~3x too fast
  (implied 21 g lateral at 100 m/s vs ~4.5 g physically available). Constants now
  research-grounded (body 45 deg/s peak, 100 deg/s^2 ramp, path <= T*sin18/m/v);
  two launch tests corrected to the frame-timed contract with two-sided bounds.
  Measured in-sim: 30 deg at 1.99 s after ignition; suite + all intercepts green.
- **2026-06-12 map-freeze fix (user bug report: app Not Responding on M).**
  Measured root cause: build_map_pixels ran the DENSE vectorized terrain_height
  (55 noise layers everywhere) over 1024^2 points on the main thread at the first
  M press — 42.4 s frozen, no event pumping, Windows flags Not Responding; all
  input appears dead and terrain streaming stalls (explains the flat-terrain
  report too — streaming resumed after the freeze). Fixes: (1) masked vectorized
  terrain_height (continent bands / island interiors+skirts / floor-only-where-
  it-wins) — bit-identical vs the scalar path on 4,845 boundary-stress points,
  42.4 s -> 3.9 s; (2) map pixels build in a daemon thread kicked at sandbox
  construction + disk cache (cache/map_pixels_v1_seed1337_1024.npy) — M press now
  blocks 0.019 s worst case and shows BUILDING MAP if pressed inside the first
  seconds; (3) BUILDING WORLD loading frame on SANDBOX click (prior commit).
  Full suite green.
- **2026-06-12 turn-dynamics fix (user playtest feedback, controller solo).**
  User reported missiles cornering instantly at launch (visible trail kink) and the
  S-300 platform accepting waypoint paths it ignores. Measured: velocity-direction
  turn rate jumped 0 -> 49 deg/s in one 8 ms tick at the boost handover. Fixed with
  slewed trapezoidal turn rates (TURN_ACCEL 150 deg/s^2, BRAKE_MARGIN 0.6 arrive-slow
  braking) on Oniks pitch-over/boost and SAM tip-over, TVC gravity compensation during
  launch steering, a 0.6 s post-burnout guidance ease-in, and a body_dir attitude state
  (nose leads the path, AOA clamp 10 deg) that the renderer now uses. Map: S-300
  refuses waypoint planning with a hint. Verification: probe shows peak exactly 70
  deg/s with ZERO jump events; 4 new regression tests; full suite green; perf 13.81 ms
  avg PASS; launch render shows a continuous candy-cane arc with no corner.
- **2026-06-11 Feel & Polish final verification (controller's own pass, clean machine).**
  Suite: full run exit 0 (~250 tests incl. slow e2e intercepts, retarget, launch timings).
  Perf: 10.82 ms avg / 14.02 p95 vs 16.0 budget — best result yet, gaming load closed.
  Render review vs references: Oniks intake signature (knife-edge lip, black annulus,
  protruding cone) matches yakhont_armia2018 — PASS; launch frames match the storyboard
  (S-300 hang frame flame-free with cover debris; Oniks t3 shows the cap tumbling in the
  trail) — PASS; settings/menu match the ui_reference spec — PASS. SATISFIED this round.
  Cosmetic backlog for a future pass (non-blocking): folded wings ride slightly proud of
  the hull (visible ~0.55 s); 5P85 lattice umbilical mast + MAZ split-cab not modeled;
  unlit wing faces read near-black at some sun angles (ambient lift candidate); terrain
  remains the blandest element from altitude despite the S5 improvements.
- **2026-06-11 Feel & Polish gate (Task GATE).** The package's sim_step regression
  (measured 12.29 ms avg at babdef4, ~14.8 ms on the gate machine-state; was ~5.4 before
  the package) was profiled per-substep and removed without behavior changes — suite +
  intercept e2e tolerances all green throughout:
  - per-substep particle feeds were the top cost: `_emit_one` now draws its 6 normals in
    one rng call (same stream, same values), the cruise ramjet jet/haze feed moved from
    every 120 Hz substep onto a `RAMJET_EMIT_PERIOD` accumulator (1/60 s, sizes/lives
    bumped to keep the faint wake continuous — the sanctioned second-target tuning),
    pool free-slot scans stay inside the occupied prefix, and trail expiry walks the
    aged prefix instead of reducing a bool array per substep;
  - terminal/sea-skim and impact surface queries got an exact open-water early-out
    (`generation.surface_height_scalar`, bit-identical to `max(terrain_height_scalar, 0)`
    — unit-tested) so skim holds over the ocean skip the full noise stack;
  - `apply_missile_hits` prefilter, `Missile._guidance` steering, `_acquire_lock`,
    `SamMissile.update` and `Ship.update` were scalarized (no per-substep numpy
    temporaries); the duplicate mach/cd/drag evaluation per ramjet step was removed;
    the SAM contact-estimate closure returns plain-float tuples.
  Result: worst-case harness avg total **11.5/11.8/15.4 ms** vs the 16.0 budget — PASS
  (sim_step back to ~5.3 ms, particles ~1.6 ms). Note: a background-loaded machine state
  inflated every row ~25-30% in some runs (20-21 ms total with identical code); the
  steady-state numbers above match the historical baselines. Full play-test scripted with
  injected events (38/38: menu, rebind, launch cinematic at 1x from the orbit cam with
  drag/zoom, mid-flight retarget + kill, S-300 hang-launch + aircraft kill, F1, pause,
  resume, quit). All harness scenes re-rendered and critiqued against the reference
  images one final time; harbor backlog item closed (see above).
- **2026-06-11 S6 perf re-gate (S-300 expansion complete).** Worst-case scene expanded with
  the 4 patrol aircraft (one shot down overhead: falling spiral + smoke/flame emission all
  600 frames) and 2 S-300s coasting in midcourse with full trail ribbons (honest
  out-of-envelope shots, steering every frame) on top of the v1 load (14 ships, 2 burning,
  4 Oniks airborne). Result: avg total 15.1 ms (runs 15.08/15.10/15.62) vs the 16.0 ms
  budget — PASS. Profile shows no new hot spot: SamMissile.update ~40 us and
  Aircraft.update ~7 us per call (both already scalar-math per the Task 22 pattern); the
  remaining cost is the pre-existing Oniks guidance + ship loops. Harness now warns if the
  scene sheds load mid-run (a SAM self-destructing would quietly lighten the measurement).
