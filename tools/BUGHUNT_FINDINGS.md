# COMBAT bug-hunt findings

Consolidated from a hands-on playtest (Battles 1, 1b, 2 + the S-300 flyoff and
model renders) plus four read-only code-audit agents (weapons/sim, render/camera,
enemy-AI/sensors, lifecycle/map/win-lose). Each agent finding was re-read in the
code before being trusted; in-game-verified items are marked.

## FIXED (crashers) — done this session, verified

1. **Camera zoom crash on enemy missiles** (the #1 reported bug). The HUD
   followed-missile block assumed Oniks-shaped attributes: `m.target_point`
   (missing on StrikeMissile/HarmMissile) and `target.length` (missing when a
   SAM's bracket target is a `Missile`). Zooming an enemy SM-2 (terminal),
   Tomahawk, or HARM crashed. Fixed `game/hud.py` `_missile_target_pos` +
   `_target_bracket` with duck-typed fallbacks. **Verified:** Battle 2 sweep of
   all 8 missile types → 0 crashes.

2. **S-300 launch IndexError after magazine refill (ammo ≥ 9)**. Refill reset
   `sam_ammo` to the full magazine without the 4-tube cap, so `tube =
   S300_TEL.ammo - sam_ammo` went negative-out-of-range. Fixed `world/world.py`
   with a two-sided clamp (the tube index only picks a cosmetic mouth offset).
   The lifecycle audit independently confirmed the fix correct.

## CONFIRMED — real, needs a design/balance decision (not crashers)

3. **48N6 and 40N6 are near-identical in-envelope** (your report). ✅ **FIXED
   this session.** The defs DO differ (mass 1900→4000, fuel 1020→2142, motor
   200kN/12s→280kN/18s, max range 150→380 km, self-destruct 180→380 s, ceiling
   25→40 km), but peak speed is ~identical by design (bigger motor offset by
   bigger mass: 1534 vs 1558 m/s) AND the loft constants were SHARED module
   globals, so both flew the same ~32 km arc ≤150 km. Fix: the loft
   (`loft_gain/loft_bias_max/loft_fade_range`) is now PER ROUND on the SamDef
   (sim/arsenal.py); `sam._aim_direction` reads them off `self.weapon`. The
   48N6 keeps the medium-loft default (14 km bias, ~32 km apogee); the 40N6
   gets a HIGH loft (24 km bias) AND a fade range (45 km) pushed 5 km outside
   its 40 km terminal gate — so the dive is established in midcourse before the
   ARH seeker takes over (kills the overshoot/wallow: a 40 km handover at
   apogee was the cause). Measured (tools/compare_s300_rounds.py, extended):
   in-envelope 120 km the 40N6 lofts to **37 km vs the 48N6's 32 km**; on long
   shots it climbs to 44–50 km and KILLS at 200/300/360 km where the 48N6
   self-destructs short; a close 60 km shot stays flat (15 km) and still kills.
   Locked by `tests/test_s300_rounds_distinct.py` (5 tests); full suite green.

4. **Only 2 missile meshes for 9 missiles** (your "all the same model"). `_draw_
   missiles` (game/sandbox.py:943-958): every `SamMissile` (48N6/40N6/SM-2/
   Pantsir) → `_mesh_s300_missile`; everything else (Oniks/Tomahawk/JASSM/HARM/
   AIM-9X) → `_mesh_oniks`. Reference renders + spec in
   `Assets of oinks/MAPPING.md` for new-model generation.

5. **Setup fields `n_awacs`, `n_drones`, `n_player_radars` are silently ignored**
   (found by 2 agents). `CombatWorld.__init__` reads destroyers/enemy-radars/
   pantsir/ammo but never these three — it hardcodes 1 AWACS, 1 drone, 1 radar.
   The armory lets you change them and nothing happens. Not unwinnable, but the
   UI lies.

6. **The battle may be impossible to LOSE** (enemy-AI audit F1+F2, med
   confidence — VERIFY IN-GAME). The enemy's attack-your-base kill chain needs
   to back-plot your missile tracks to a launch site (`sim/commander.py:959`),
   but the math yields ~12 km error for sea-skimming Oniks so fixes never
   cluster → the enemy never targets the Bastion. Compounded by the JASSM
   "blind-before-kill" gate re-arming every 0.25 s while your radar emits. Net:
   keep the radar on and you may never be attacked. **This is the most important
   one to confirm by playing a long battle.**

7. **Enemy SM-2 can damage your own ground structures** (enemy-AI F3, med). SM-2s
   are flagged `is_hostile` for the contact board, and the base-damage sweep
   selects purely on that flag with no type filter — so a stray SM-2 crossing a
   player TEL/radar OBB could destroy it. Geometrically rare; category error.

## TO VERIFY / minor (lower priority)

- victorious+defeated can both be true one frame (handled: defeated checked
  first — fragile, not a bug today).
- End overlay latches the first outcome; a later state flip won't update it (by
  design?).
- ELINT-only ship tracks inject `vel=0` → S-300 lead solution aims at a static
  dead-reckon of a moving hull (verify intercept geometry).
- CIWS last-burst Pk double-discounted when ammo bottoms out (rare).
- `commander.prune_missile_tracks` defined but never called → `missile_tracks`
  dict grows unbounded over a very long match (memory smell, behavior correct).
- AIM-9X renders at full Oniks mesh scale (subset of #4).

## "NEW SEED NEVER LOADS" — investigation

Ruled OUT: world generation (12 seeds built clean, deterministic, <0.01 s each),
the headless `start_combat` reload path (6 transitions, 0.8–0.96 s each), and the
tactical-map raster build (seed-independent, cached, 2.5 s cold / 0.004 s cached;
the "42 s" note is stale). Remaining suspect: the **terrain LOD geometry streamer
/ GL asset load in the windowed app** (every `start_combat` logs `[terrain] …
LOD0/LOD1 stream in`). NEEDS USER INPUT: does it hang on a SPECIFIC seed or ANY
new seed, and is it a true freeze or just slow?

## Checked and CORRECT (not bugs)

Determinism (all RNG seeded via SeedSequence child streams); drone-track XZ
indexing; carrier damage-control vs sink; tactical-map hostile-contact filtering
(no truth leak); no GL/thread/audio leak across repeated new-battles.
