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
