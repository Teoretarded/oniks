# ONIKS — Standalone Missile Game Design

**Date:** 2026-06-10
**Status:** Approved by user
**Location:** `C:\Users\teoti\OneDrive\Desktop\New folder\oinks PROTO`

## Summary

A new standalone missile game centered on the P-800 Oniks anti-ship cruise missile.
It shares only the tech stack with the old "missle sim" project (Python 3, pygame-ce,
PyOpenGL, numpy) — no code, models, or assets are copied. The defining goals, in order:

1. **Massive, to-scale world.** 600 × 600 km, real missile speeds and ranges. The
   old game's biggest failing was that it never felt big; this game is built around
   scale from the ground up.
2. **Looks good.** Clean, sharp low-poly art direction (Nuclear Option as the
   reference): smooth-shaded models with real silhouettes, strong sun lighting,
   atmospheric haze, glinting ocean.
3. **Extensible arsenal.** The user will add many more missiles later. Weapons are
   data-driven definitions; adding a missile must not require engine changes.
4. **Optimized.** 60 FPS target with many ships and multiple missiles in flight.

V1 is a sandbox (launch, ride the missile, sink ships). Structured missions come later.

## World

- **Region:** 600 × 600 km, flat plane (no earth curvature in v1; haze sells the
  horizon), Y-up, meters, simulation coordinates in float64.
- **Generated once from a fixed seed** — the same world every run so it feels like a
  real place. Named locations.
- **Layout:** player's Bastion-P battery on a cliff coastline at one edge; open ocean
  ahead; scattered islands at 50–400 km; enemy coastline ~500 km out.
- **Terrain:** heightfield from layered value noise (numpy), rendered with ring/quadtree
  LOD meshes.
- **Ocean:** ring-LOD grid centered on the camera. Near rings get vertex-displaced waves
  (Gerstner-style) and sun specular glint; far rings flatten out. Depth-based color.
- **Sky:** gradient dome with sun disc and cheap analytic atmospheric scattering;
  distance haze blends terrain/ocean into the sky at the horizon.
- **Life:** shipping lanes crossed by moving cargo ships, tankers, and warships on
  routes. Static land targets on islands and the far coast: radar station, fuel depot,
  harbor structures.

## Engine

- **Stack:** Python 3, pygame-ce (window/input/audio), PyOpenGL with an OpenGL 3.3
  core profile, numpy for all math and mesh building. No new dependencies.
- **Camera-relative rendering:** simulation positions are float64; each frame, object
  positions are taken relative to the camera before being cast to float32 for the GPU.
  This eliminates far-from-origin jitter entirely.
- **Shader pipeline:** VAO/VBO geometry (no display lists, no immediate mode).
  Shaders: lit-mesh (directional sun + ambient + rim), terrain, ocean, sky, particles,
  HUD/2D. Per-part material colors on models; no image textures in v1.
- **Fixed-timestep simulation** (120 Hz, accumulator) decoupled from rendering.
  Time acceleration 1×–16× runs more substeps; physics stays stable at all speeds.
- **Performance budget:** 60 FPS on a mid-range gaming PC with ~30 ships and 4
  missiles in flight. Per-frame Python work must stay bounded: numpy-vectorized
  particle and ocean updates, no per-vertex Python loops at runtime.

## The Oniks

- **Model:** all-new, procedurally built (numpy mesh builders): pointed nose cone with
  the characteristic ring intake, clipped delta fins, booster section. Smooth shading,
  crisp material colors, correct ~8.9 m proportions.
- **Launch sequence:** cold vertical eject from the canister (gas eject, visible pause),
  booster ignition, pitch-over toward the route.
- **Flight profiles, selectable at launch:**
  - *Hi-lo:* climb to ~14 km, cruise ~Mach 2.6, descend to terminal sea-skim.
  - *Lo-lo:* whole flight low, ~Mach 2, shorter range.
- **Terminal phase:** sea-skim at ~12 m altitude with active radar seeker acquisition.
- **Guidance:** waypoint mid-course (inertial), terminal proportional navigation that
  genuinely leads moving targets — and genuinely misses if the targeting picture was
  stale and the ship moved outside the seeker basket.
- **Flight model:** point mass with thrust curves, Mach-dependent drag table, gravity,
  G-limits, fuel burn. Visual orientation follows velocity with small attack angles.

## Arsenal architecture

- Data-driven weapon definitions (cleaner successor to the old `arsenal.py`):
  dimensions, mass, thrust stages, drag table, guidance type, seeker parameters,
  flight profiles, launcher compatibility.
- Adding a future missile = new definition + new procedural model builder. No engine
  surgery. Launchers are also definitions (v1 ships with the Bastion-P TEL only).

## Gameplay (v1 sandbox)

- **Tactical map** is the heart: full-world zoomable map (launcher → all 600 km),
  shows ship contacts and land targets, click to set target or drop waypoints, pick
  flight profile, launch.
- **Cameras:** missile chase, orbit, target cam, launcher cam, free cam. Smooth
  transitions. The chase cam at Mach 2 over open ocean is the signature shot.
- **Time controls:** pause, frame-step, 1×–16× time acceleration.
- **Damage:** ships take hits, burn, list, and sink; land targets explode. Hit
  detection against ship hull bounds.
- **Contacts:** the map shows shipping contacts with slightly delayed/fuzzy positions
  (justifies the terminal seeker doing real work). No full sensor sim in v1.
- **Audio:** launch thump, booster roar, sustainer rumble, impact. Sounds loaded from
  a local `sounds/` folder, missing files skipped safely; v1 ships with procedurally
  synthesized placeholder sounds (numpy → pygame Sound).

## Code structure

```
oinks PROTO/
  main.py                 entry point, game loop, fixed timestep
  engine/                 window, shader, mesh, renderer, camera, particles, text
  world/                  generation, terrain, ocean, sky, world state, ship routes
  sim/                    physics, missile, guidance, arsenal, ships, damage
  game/                   game states, tactical map, HUD, controls, cameras
  models/                 procedural model builders (oniks, bastion TEL, ships, structures)
  sounds/                 audio files (placeholders generated)
  tests/                  pytest suite
  docs/superpowers/specs/ this document
```

## Testing & acceptance (the user's /loop directive)

The user invoked `/loop test the game till your 100% satisfied` — testing iterates
until all of the following hold:

1. **Physics correct (pytest, no GL required):** launch geometry (vertical eject →
   pitch-over), cruise speed/altitude per profile, sea-skim altitude hold, PN
   intercepts of moving ships at various ranges/speeds, fuel/range limits, time-accel
   producing identical trajectories to real-time.
2. **Looks good (screenshot harness):** scripted scenarios rendered to image files
   that are visually reviewed — model silhouettes, ocean/sky/haze, launch sequence,
   terminal approach. Iterate on models and shaders until they pass review.
3. **Optimized (performance harness):** frame-time measurement with ~30 ships and 4
   missiles in flight; budget 16.6 ms/frame (60 FPS). Profile and fix hotspots.
4. **Determinism:** same seed → identical world; same launch inputs → identical flight.

## Out of scope for v1

- Missions/campaign structure (architecture must not block it)
- Enemy defenses (CIWS, SAMs) shooting back
- Additional missiles beyond the Oniks
- Earth curvature, weather, day/night cycle
- Multiplayer (never planned)
