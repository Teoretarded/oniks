# Other-session notes (transcribed 2026-07-17, for collision avoidance)

## 1. "Cinematic missile launcher system" (the MANPADS Claude) — idle, committed
- Built the full F1 walk-mode weapons rig: locker UI, 4 researched MANPADS
  (Igla-S / Stinger / Piorun / Starstreak), RMB sight / MMB designate / LMB fire.
- All physics, no rolls: eject charge, standoff ignition, boost/sustain,
  Mach drag, PN capped by fin authority; seeker gimbal/track-rate/occlusion.
- Proved a boosting 48N6 is honestly uncatchable; the ONE winnable shot =
  Starstreak in the cold-eject window (audit shows SPLASH – 48N6).
- RESOLVED this session's audit item #4 (the "audit misses" were honest physics).
- Files owned: sim/manpads.py, game/cinematic_weapons.py, models/manpads_model.py,
  game/cinematic.py (hooks), tools/shoot_manpads.py, tests/test_manpads.py,
  docs/research/manpads_reference.md.  **HANDS OFF these files.**
- Their open polish list: chunky Starstreak aiming-unit box; IR kills once
  slower targets exist.

## 2. "Cinematic mode maps and wind simulation" — idle
- Wind profiles, rolling fog, terrain shadow bakes, night/light moods in
  cinematic mode; particle-engine extensions (fog pool, alpha/fade/stretch).
- Was waiting on the slow full-suite tail at session end; targeted suites green.

## 3. "Game map location options" (became cinematic launch-effects polish) — idle
- Removed white TrailRibbon line from cinematic launches (smoke IS the trail).
- Salvo tube-cycle (L, 2.5 s), 3-stage pad blast, fatter base column,
  per-variant personalities (40N6/5V55/9M96E2), distance-based boom samples.
- EFFECTS tab in the asset inspector (16 entries); tools/shoot_missile_variants.py.
- Logged for next round: balloon-smooth broadleaf crowns, smeared ortho band
  near spawn.

Implication for the combat session: combat-side files are free to edit;
engine/particles.py is shared — additive changes only.

## 4. "User feedback round" session (evening 2026-07-17) — committed
Worked the user's 5-item playtest feedback. Files touched (all committed
on feat/combat-expansion, a94d2e2..d28703b):
- world/cinematic_scene.py — halo_axes (crater-grid off-by-one crash
  fix), CUT-TO-TARGET craters (5-tuple with gz_h; crater_delta_grid now
  takes a `baked` grid + optional per-ring `tuck`), nuclear_crater_dims
  (fireball-anchored: nukes decapitate summits), punch_core_hole.
- world/cinematic_terrain.py — ring-1 punched out of the core (the
  "overlapping mountains"), per-ring crater tuck, baked-DSM crater path.
- world/cinematic_trees.py — fell_mask + apply_craters (blast felling).
- world/sky.py — starfield + u_space_k space blend (dome now draws in
  orbit); world/earth_globe.py — wide terminator + dusk band.
- game/cinematic_missiles.py + game/cinematic_icbm.py — REAL flight
  physics everywhere (drag, mass, slew-limited attitude, drag-biased
  ICBM targeting); ICBM launch fx upgraded (silo apron blast trio,
  double vortex ring, Trident steam flash, Sarmat cutoff vent, shock
  diamonds).  NuclearBurst untouched.
- New tests: test_cinematic_flight_physics.py, test_cinematic_surround_
  punch.py, test_cinematic_tree_fell.py (+ crater additions).  Probes:
  tools/probe_icbm_physics.py, probe_icbm_bias_debug.py.
Open nits logged: mushroom-cloud scale at 300 kt reads small; crater rim
spikes at chunk edges; scorch texture lands a beat after impact; long-
range (3500 km) landing residual ~94 m; per-variant S-300 meshes still
share build_s300_missile in cinematic mode.
