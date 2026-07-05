# Energy-Model Build Run Log — 2026-07-05/06

Plan: docs/plans/energy_physics_graphics_2026-07-05.md. Research (agents,
cited): docs/research/missile_energy_autopilot_2026-07-05.md,
launch_sequences_2026-07-05.md, launch_visuals_particles_2026-07-05.md.

## Shipped (commits 4f5d2ec..d9e522e+)
1. **sim/aero.py energy model in all three flight machines** — induced drag
   D_i = k·L²/(qS) with k = ALPHA_TAX(0.45)/CLmax for body-lift airframes
   (wing-derived k≈0.012 for TLAM/Kalibr/JASSM/SWARM), available-g
   q-limit, first-order autopilot lag (per-weapon tau, terminal
   gain-scheduling 0.15 s), engine spool lag. THE user bug ("does a 180,
   doesn't lose speed") measured fixed: Oniks 180° at sea level bleeds
   678→365 m/s, turn 23 s, 95% recovery at 36 s; at 14 km the turn takes
   66 s instead (q-limited). tests/test_aero.py (7 contracts).
2. **Launch harness (AI-runnable)** — tools/probe_launch_kinematics.py
   writes renders/launch/<id>_log.csv + launch_summary.json for EVERY
   weapon; tests/test_launch_kinematics.py pins phase sequences,
   cold-launch hang/ignition, tip-over caps, tube-exit speeds, VLS
   booster burns, JASSM drop beat, swarm no-zoom.
3. **Swarm boost-overshoot bug CLOSED** (documented open issue): per-weapon
   launch scaling (ride-out thrust min(46 kN, own booster), pitch inside
   booster burn, boost-end at own cruise Mach, booster speed-band cut).
4. **GRAPHICS settings tab** (ESC → SETTINGS → TAB): particle density
   LOW/MED/HIGH/ULTRA, exhaust trails, launch smoke, launch cinema, map
   layout — persisted ui_prefs, live Effects.density/launch_fx plumbing.
5. **Wave-2 SAM shaping** — midcourse 4 g budget, follow-the-fall (+ air-
   target margin), no-up-chase reentry rule, DIVE_MAX_TAN 25→50°,
   TERMINAL_AP_TAU; ASBM depressed profile (26 km ceiling cruise, late
   50° plunge, isp 262, fuse 30 m hull geometry, honest max_range 230 km);
   40N6 cl_max 14/tau 0.2/terminal 25 km/fade 70 km (kills the 100 km /
   20 km ARH crosser, keeps tall-arc + 250 km-reach discriminators);
   Kh-31P re-based 95 kg/14 kN powered profile (kills 60–140 km, short
   160+; rail kick now ELEVATED 15° everywhere — level toss below stall
   honestly sank); **real fog-law leak fixed** in sim/asbm.py (ghost was
   built from a truth-stamped _lock_pos; now from the last pre-handover
   estimate).

## Wave 3 (2026-07-06) — both reds closed
- SAM ENERGY CRUISE: loft bias capped at the drag-optimal altitude for the
  CURRENT speed (qS* = sqrt(k/CD0)·L; the optimum descends as the round
  slows — a fixed 33 km coast melted itself at a clean 1-g trim). 40N6
  rides +allowance above optimum (its identity), motor isp 258/19.4 s,
  timer 460 s. TGO_MAX 90→40 s (orbiting-target ghost leads).
  TERMINAL_PN_GAIN 5 (decel bias miss, Zarchan). AWACS test re-anchored
  205-245 km (argued: a fleeing AWACS honestly outruns a 360 m/s arrival
  at 240+ km; contract "kill beyond 200 km + flee" holds at measured
  233 km launch, 25.7 m closest).
- STEALTH_SNR_SIGMA_MAX_M 60→40 (the 0.15 s lag ~doubled felt miss per
  sigma; design shape restored: near-certain close, ~1/3 at edge).

## Verification (2026-07-06)
- Perf harness on the real RTX 3050 Laptop GPU: avg 12.58 ms vs 16 ms
  budget (worst-case scene, 8x warp) → PASS, energy model included.
- NEW default-battle digest:
  df9dbde3402c309f71ccd4b55136821fdddd8d19a78f6b35a733f4a1bf7b2321
  (old 7d5716…06add superseded by the deliberate physics change).
- Launch strips rendered + own-eyes reviewed: renders/launch/
  oniks_strip.png (ignition cloud → cream column → pitch kink → boost
  bloom → grey streak → climb) and s300_strip.png (catapult pop →
  flameless HANG → ignition fireball → tip-over streak).
- Full suite -n auto: run in progress at log time; see final report.

## Backlog for later passes
- Per-weapon launch VFX polish (research Part A): VLS flame+uptake jet,
  Buk/Pantsir needle trails, turbofan smokeless cruise (recipe in
  docs/research/launch_visuals_particles_2026-07-05.md). Density prefs
  and launch_fx scaling shipped this build.
- Kalibr pre-existing: fuel 80 kg honestly covers ~250 km at the 4.4 kN
  sustainer (label says 500 km) — later balance pass.
- Pantsir real boost 55 kN/1.5 s vs game 18 kN/3.5 s (flagged, unchanged).
- Launch strips for more weapons (tomahawk/buk/pantsir need combat-world
  spawn recipes in the render tool).
