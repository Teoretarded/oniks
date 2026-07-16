# Cinematic mode — real-world 1:1 walkabout scenes (2026-07-16)

Hidden F3 lab gained a third tab: **CINEMATIC** (F7). Pick a real place,
walk it first-person, watch a scripted S-300 cold launch at true range.
No HUD, ESC returns to the lab. The scenes are baked 1:1 from open
government LiDAR + orthophotos — no Google/Cesium data anywhere (their
terms prohibit offline baking; swisstopo/USGS open data does not).

## Data pipeline

```
tools/fetch_cinematic_data.py   swisstopo STAC -> data/cinematic_raw/<scene>/
tools/fetch_cinematic_us.py     USGS TNM + WMTS -> same raw layout (US)
tools/bake_cinematic_map.py     raw -> assets/cinematic/<scene>/ (runtime)
tools/shoot_cinematic.py        boots the real app hidden, screenshots
```

- **Lauterbrunnen** (Bernese Oberland): swissALTI3D 0.5 m DTM,
  swissSURFACE3D 0.5 m DSM (LiDAR surface: trees/roofs), SWISSIMAGE 10 cm
  orthos. 16 km² = ~1.2 GB raw, 253 MB baked. Attribution "© swisstopo"
  required and shown in-scene.
- **Yosemite Valley**: USGS 3DEP 1 m lidar DEM (bare earth only — DSM is
  copied from DTM, clutter 0) + USGS Imagery (NAIP) via the public WMTS,
  warped WebMercator -> UTM 11N in numpy. Public domain.

Bake outputs per scene: `dtm_1m.npy` (physics), `obstacle.npy`
(DSM−DTM > 2.5 m = wall), per-km-tile `*_hgt.npz` (dsm_1m/4m/20m +
clutter_* grids, all with a 1-cell halo, float32 — float16 quantizes to
1 m at alpine altitude and stairsteps everything), `*_tex.jpg` 4096²
(~25 cm), `*_mid.jpg` 1024², and `scene.json` (origin, spawn, S-300 pad,
credits). Every grid is bilinear-sampled from ONE scene-wide 0.5 m mosaic
at corner-aligned coordinates -> abutting tiles share bit-identical edge
vertices (same no-seam convention as world/terrain.py).

Spawn + pad are auto-surveyed from the data (no RNG): flattest cell with
an obstacle-free 12 m box, held to the local valley-floor altitude band
(a flat cliff LEDGE never wins), pad restricted to the half-plane toward
`look_en` at 1.1–1.7 km, and — because the whole mode is WATCHING — the
first pad candidate with a clear DSM line-of-sight from spawn eye height
to canister top wins.

## Runtime

- `world/cinematic_scene.py` (GL-free): manifest, bilinear ground
  sampler, obstacle query, and `build_tile_arrays` — 9-float vertex
  layout `[pos3 nrm3 uv2 clutter1]`, perimeter skirts with
  outward-winding (backface culling stays on), UV `v = 1 - z/size`
  (JPEG row 0 = north).
- `world/cinematic_terrain.py` (GL): one textured shader for all LODs
  (log-depth + shared haze block, LOCKED conventions). L0 = 1 m mesh +
  4K texture inside 650 m, streamed from a worker thread (numpy/PIL
  release the GIL; GL upload stays on the main thread), max 4 live, LRU
  evicted. L1 = 4 m/1024 inside 2.8 km, L2 = 20 m beyond, both built at
  load. Shader details: slope-gated procedural limestone on steep BARE
  faces (clutter gate — round-2 audit turned the village into standing
  stones without it), crown-noise canopy retexture on steep forested
  faces (kills the green-curtain smear), close-range albedo value noise.
- `game/walker.py` (GL-free): kinematic humanoid — 1.7 m eyes, 1.9/5.2
  m/s walk/sprint, gravity + jump, 38° slope refusal, 0.55 m step ledge,
  axis-separated wall slide on the obstacle mask.
- `game/cinematic.py`: the state. Scripted 5V55 cold launch (eject
  30 m/s → ignite at 1.5 s → 65 m/s² boost 7 s with pitch-over away from
  the viewer). **Sound cues are queued at 343 m/s propagation delay** —
  at 1.1 km you see the ignition ~3.2 s before you hear it.
- `game/testing_lab.py`: CINEMATIC tab (F7), postcard-style location
  gallery; `main.py`: open_cinematic/close_cinematic (lab survives
  behind the scene).

## Visual audit rounds (tools/shoot_cinematic.py, screenshots in renders/cinematic_audit/)

1. Spawn was on the west wall — the from-memory LV95 easting for the
   village was 1 km off. Fixed with the swisstopo WGS84→LV95 formulas.
2. Rock shader painted houses/trees (steep DSM lumps) as limestone →
   clutter gate baked per-vertex.
3. Spawn in a street canyon; forests smeared as green curtains → meadow
   spawn + canopy retexture + [1,2,1] blur on coarse LODs.
4. Spawn snapped to a scree fan (flattest ≠ nicest) → distance cost in
   the survey + valley-floor band.
5. Pale waxy cliffs → darker banded rock with macro variation; LOS
   check for the pad added.
6. Final: contrail climbing between the cliff walls reads like real
   valley-launch footage. 24 unit tests green.

## GPT-5.6 Sol adversarial review (xhigh) + fixes

The full diff went to Codex/GPT-5.6 at xhigh effort; it ran numeric
diagnostics on the baked data and found real defects, all fixed same day:

- **Cross-LOD edge gaps up to 64 m** (fixed 2/8/40 m skirts too short on
  cliff tiles) → per-tile adaptive skirts sized from measured own-grid
  edge deltas (`world/cinematic_scene.skirt_drops`, unit-tested).
- **Coarse clutter corrupted** (blurred DSM minus raw DTM invented
  >100 m of fake canopy on cliffs, flipping rock/forest shading) →
  clutter sampled from the 0.5 m mosaic field and blurred with the same
  kernel as its DSM.
- **GPU budget**: L0 was 2M tris / 60 MB per tile with an ineffective
  4-tile cap (7 could pass the distance test, failures retried every
  frame, stale results uploaded) → L0 now 2 m mesh (¼ the load),
  nearest-N want-list, load/evict hysteresis, failure memo, stale-result
  discard, future cancellation.
- **Texture hitches** → all 4K tiles decoded on a pool and uploaded once
  at scene load (driver compression verified via GL_TEXTURE_COMPRESSED,
  2048 RGB8 fallback); the walk loop never touches textures.
- **GL leaks** → `Shader.delete()` added; Sky/ParticleRenderer/terrain
  dispose their programs; CinematicState.enter is exception-safe.
- **Particles broke the log-depth convention** (vertex-only) → ported to
  per-fragment `gl_FragDepth` like every other shader.
- **Walker** → NaN/negative-dt no-ops, airborne wall collision (no more
  sailing into cliffs mid-jump), diagonal slope evaluated on the full
  displacement (order-independent), wall slide preserved.
- Misc: haze now uses true altitude (renderer.alt_offset = origin ASL),
  TEL canister mouth measured from the model, cold eject is an unlit gas
  puff (was an orange muzzle flash), 48N6 naming, trail pruning, F6
  route from the cinematic tab, scene rescan on tab entry, manifest
  validation before entry, ASCII attribution glyphs.

## Scene 2: Yosemite Valley (USGS)

`tools/fetch_cinematic_us.py` normalizes USGS data into the same raw
layout the bake consumes: 3DEP 1 m lidar DEM (native UTM 11N, crop +
2x upsample) and USGS Imagery (NAIP) WMTS tiles warped WebMercator→UTM
in numpy. Gotchas hit: the USGS tile cache tops out at z16 (~1.9 m/px)
— z17 404s everywhere (a silent-black-tile bug until a 404 counter was
added); TNM API 504s (retries + cached-source fallback). No DSM exists
(3DEP is bare earth), so clutter=0: granite walls get the full
procedural rock treatment and the whole valley is walkable. Spawn is
El Capitan Meadow, battery up-valley east.

## Phase 2 (same day): interaction + spectacle pass

User verdict on v1: "pretty bland". Round 2 shipped:

- **Missile variants** (`game/cinematic_missiles.py`, K key + UI): 48N6 /
  5V55 / 9M96E2 (dual pulse) / 40N6, each with its own burn schedule,
  acceleration, flame length/colors, smoke identity and column
  persistence — all numbers from `docs/research/s300_launch_visuals.md`
  (GPT-5.6 Sol footage research: ignition ~0.9 s at ~28 m, 8-12 s burns
  at 14-20 g, columns persisting minutes, per-distance observer tables).
- **Cinematic-grade launch fx**: smoke emitted PER METER of flight path
  (time-based emission tears into dots at 15 g), two-layer column (dense
  core + huge faint aged puffs), altitude-tapered budget, wind drift +
  buoyancy, elongated flickering flame (25-45 Hz + 8 Hz breathing) with
  a dim additive glow for range visibility, unlit cold-eject gas + pad
  dust ring, variant-scaled ignition fireball.
- **Binoculars** (mouse wheel): FOV stages 68/30/14/7 deg, procedural
  two-barrel mask (`game/cinematic_overlay.py` — remember glFrontFace is
  CW: fullscreen quads must disable culling), handheld sway that grows
  with magnification, sens scaling. Manual look only, no tracking.
- **Freecam** (F): fly WASD + Space/Ctrl, wheel = speed, center marker;
  LEFT CLICK ray-marches the DTM and teleports the walker there.
- **DIRECTOR overlay** (G): fresh glass/hairline/cyan UI (deliberately
  not the brass terminal look) — location switch, round select, LIGHT
  moods (alpine noon / golden hour / grey morning via per-renderer sun
  rig override), SKY presets (clear/fair/broken/overcast/storm via
  CloudsV2 + sim.atmosphere presets).
- Engine: renderer sun/haze became per-instance attrs (combat defaults
  untouched); audit tool grew shots 09-14 (bino, aged column, golden
  hour, director UI, freecam, storm).

## Phase 3 (same day): physics exhaust, spotting, trees, surround, weather-overhead

- **Exhaust physics** (per a second GPT-5.6 xhigh consult): pool gained
  optional per-particle alpha ramps + fade-in (kills sprite pop-in),
  WIND-RELATIVE drag (columns drift but stop climbing — the old combat
  buoyancy gave every particle a permanent 3.8 m/s elevator), and
  velocity-stretched sprites (hot jet, dust sheets). Emission is now four
  layers: stretched additive core, decelerating nozzle JET (36 m/s ->
  ~6 m/s in 2 s), CLUMPED billows (3-5 sharing a center + eddy every
  3-5.5 m of path — billows, not beads), and a faint persistent veil.
  Ignition adds a variant-scaled fireball plus a two-stage pad wall-jet
  (fast dust sheet at +0.08 s, rolling vortex ring at +0.26 s) and an
  observer ground-shock shake that arrives WITH the boom.
- **Variant art direction**: per-variant smoke_per_m / width / base cloud
  / ground blast / shake (9M96E2 is a pencil at 0.44 width; 40N6 is 1.35x
  wide, 1.5x blast, double shake thump).
- **I = spotter**: hairline from screen center to the missile + diamond +
  live range/Mach readout; while zoomed it auto-tracks at a human panning
  rate. Binoculars now reach 100x (0.68 deg).
- **Weather overhead**: cinematic biases the 300 km regional coverage up
  and, for storms, finds the densest supercell column in the baked field
  and world-shifts the cloud camera so it parks over the valley.
- **Surround ring**: 16x16 km of 2 m swisstopo DTM+ortho baked to 32 m
  chunks (16 draws) — snow-capped Jungfrau massif now closes the horizon
  instead of void. Core-overlapping cells tuck 8 m under the fine tiles.
- **3D trees** (implemented by a delegated GPT-5.6 xhigh write task in
  tools/bake_cinematic_trees.py + world/cinematic_trees.py + tests):
  159,725 trees for Lauterbrunnen classified from clutter height +
  orthophoto greenness (roofs rejected), deterministically thinned,
  rendered as wind-swaying crossed billboards from a procedural 3-species
  atlas, per-tree ortho tint, alpha-tested, <=2.5 km ring.

## Phase 4 (same day): salvos, no ribbon, bigger everything, EFFECTS tab

- **Salvos**: `CinematicState.launches` is a list; L fires again after a
  2.5 s tube cycle ("TUBE CYCLING" toast shows the wait), old rounds
  keep flying, smoke outlives pruned rounds. SMOKE_CAP 6000 -> 12000
  (two simultaneous 40N6 columns fit).
- **TrailRibbon removed from launches** — the skinny white line the user
  hated; the per-meter column is the trail.
- **Bigger**: pad blast rebuilt as dust sheet + white efflux surge +
  TEL-burying base cloud + rolling ring + lingering ground-haze skirt;
  eject cloud +50%; column +90% width at the pad fading by ~600 m up
  (fat fresh column, thinning with altitude); 5V55 re-directed as the
  FILTHY first-gen round (2.6/m, dirty colors), 48N6 2.0/m, 40N6 3.3/m
  at 1.6x width / 2.1x base / 2.3x blast; 9M96E2 faster (230 m/s^2).
- **Sound physics**: the SAMPLE is now chosen when the wavefront ARRIVES
  (near/far boom by traveled distance via audio.boom); eject pop is
  inaudible past 2.5 km (research table 6).
- **EFFECTS tab in the asset inspector**: new EFFECTS category with 16
  looping drivers (game/effects_catalog.py) — every engine one-shot
  (muzzle blast, fireball, explosions, splash), continuous plumes, the
  cinematic launch stages per round, and FULL cold launches that re-arm
  after expiry, with the raised TEL for scale. T pauses, orbit inspects.
- **Filmstrips**: tools/shoot_missile_variants.py captures each round at
  t = 0.6/1.4/3/7/14/26 s from 250 m into per-variant contact sheets.
- Logged for later: balloon-smooth broadleaf crowns up close; ortho
  smear band on the river cut near the observer bench.

## Phase 5 (2026-07-16 playtest feedback): environment pass

User playtest reports, each fixed this phase:

1. **"Missiles auto-launch every ~12 s"** — the auto-fire timer is GONE
   (`next_auto_launch` removed from `game/cinematic.py`).  A round
   leaves the tube only on L or the director UI.  Test:
   `test_no_auto_launch_ever_fires`.
2. **"The plume needs to dissipate at a decent distance"** — particle
   LIFETIMES now shrink with altitude above the pad
   (`ls = 1/(1+(rel_alt/1200)^1.6)` in `ScriptedLaunch.emit`; the veil
   collapses as `ls^2`).  The pad column keeps its minutes-long hang,
   the high trail shears away in tens of seconds.  Test:
   `test_plume_lifetimes_shrink_with_altitude`.
3. **"The pad blast is tiny and disappears immediately"** — new
   `_pad_spew`: while the booster is below ~260 m the wall jet keeps
   feeding the ground cloud (two feeds: white efflux boil + dusty
   skirt, 16–40 s lives), and the one-shot base cloud / haze skirt now
   live 22–55 s.  Tests: `test_pad_spew_builds_lingering_ground_cloud`,
   `test_pad_blast_oneshots_linger`.
4. **"NO GROUND THERE outside the LiDAR core"** — the 16 x 16 km
   surround chunks are now a physics field (`CinematicScene`
   `_load_surround_field`: one 32 m mosaic assembled from the SAME
   grids the renderer meshes).  `ground_h`/`blocked` fall back to it,
   heights BLEND across the core border (48 m band) so the seam is
   walkable, and the freecam teleport marches the full surround extent.
   Yosemite (no surround bake) is unchanged.
5. **Real-world wind** — `tools/fetch_cinematic_wind.py` pulls ONE YEAR
   of hourly archived model analyses (open-meteo historical forecast
   API; the plain ERA5 archive endpoint has no pressure levels) at each
   scene's true coordinates: 10 m/100 m + 9 pressure levels (~140 m to
   ~5.7 km ASL), distilled per altitude x time-of-day band into
   `assets/cinematic/<scene>/wind_profile.json`.  Measured physics is
   visible in the data: Lauterbrunnen floor ~1.1 m/s thermally driven
   (up-valley from N by day, drainage from SE by night, steadiness
   0.37) vs locked westerlies aloft (4.6 -> 11.6 m/s median from 3 to
   5.6 km, steadiness ~0.57); the baked valley axis (DTM PCA) is 1.2
   deg = the real N-S trench.  Runtime `world/cinematic_wind.py`
   interpolates per altitude, channels flow along the valley below the
   ridgeline, and breathes p50->p90 on a deterministic gust series
   ([[physics-not-dice]]: measured bands, zero runtime RNG).
   `ParticlePool.update` now accepts a callable wind, so one smoke
   column rides the valley breeze at the pad and the westerlies at
   altitude.  The wind band follows the light mood (grey morning =
   morning band, etc.).
6. **Light rigs + PRE-BAKED terrain shadows** — MOODS are now real
   dataclasses: ALPINE / NOON / GOLDEN HOUR / GREY MORNING / NIGHT,
   each with sun + haze + sky-dome colors + ambient gains (the sky
   dome gained horizon/zenith/disc uniforms; `hemi_gain` dims the
   hardcoded hemisphere light at night, `light_gain` dims reflective
   particles — additive fire stays self-luminous).  Grey morning's sun
   is genuinely LOW now (16 deg; the user caught it sitting at the
   zenith).  Because mood sun directions are fixed, terrain shadows
   are BAKED per mood (`world/cinematic_shadows.py`: O(N) heightfield
   sweep over core DTM + surround mosaic, 2049^2 in ~2 s on a worker
   thread, npz-cached in the scene dir) and sampled by the terrain AND
   tree shaders — at golden hour 55.6% of the Lauterbrunnen extent is
   in real mountain shadow (alpine noon: 2.5%).
7. **Rolling fog** — `world/cinematic_fog.py`: fog banks breed on the
   icy heights (cells above the scene's 90th height percentile) in
   every mood, and on the green valley floor only at grey morning /
   golden hour / night (burn-off within ~20 s of switching to a high
   sun).  Banks drift on the measured wind at their own altitude and
   RELAX toward a hover height above the local ground (slow climb,
   faster pour), so flow pushes them up the windward side and they
   cascade down the lee — rolling over the ridge, not clipping through
   it.  Dedicated 2000-slot pool drawn with the alpha particles.

New tests: 20 (60 total in tests/test_cinematic.py).  New audit shots
in `tools/shoot_cinematic.py`: golden-hour shadows, grey morning,
night, fog x2, pad cloud at +12 s/+35 s (shot from 250 m — from the
spawn a moraine hides the cloud), standing on the surround.

GPT-5.6 adversarial review (high) of this phase, fixes applied:
teleport could land a few metres OUTSIDE the walkable bounds via the
border-clamped sampler (hit now nudged/refused + regression test);
`_shift_frac` rejected the last lateral line under axis-aligned sun;
shadow-mask uv mapped grid posts to texel EDGES (half-cell shadow
shift; rect now texel-centered); shadow caches ignored terrain changes
and wrote non-atomically (fingerprint + temp-file `os.replace`);
`fetch_year` ignored its start/end args.  Two flags were pre-existing
intentional phase-1/4 work (particle fragment-log depth, SMOKE_CAP
12000), one accepted as a limitation (below).

- KNOWN: inside the 48 m core-border blend band the WALKER height blends
  toward the coarse surround while the fine mesh renders unblended —
  boots can float/sink slightly vs pixels there.  Second-order next to
  the existing DTM-vs-DSM mismatch (we walk bare earth under rendered
  canopy); revisit only if a playtest actually feels it.

## Known v1 limitations (accepted, ranked for later)

- LiDAR canopy = melted lumps up close; convincing beyond ~100 m.
- Skyline needle-teeth at glancing angles on L1/L2 despite the blur.
- Ground texture blurs inside ~3 m (25 cm ortho + weak detail noise).
- Buildings are solid terrain lumps — no interiors, no doors.
- Ortho lighting is baked (capture-day sun) and ignores the engine sun.

## Adding a scene

1. Add a spec to `tools/fetch_cinematic_data.py` (CH) or
   `fetch_cinematic_us.py` (US) + `tools/bake_cinematic_map.py`.
2. Run fetch, then bake, then `tools/shoot_cinematic.py <scene>` and
   LOOK at the shots before shipping.
