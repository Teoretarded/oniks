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

## Remaining (as of this log)
- RED: tests/test_phase5b_e2e.py::test_40n6_kills_awacs_beyond_200km_on_forced_track
  (long-reach coast under energy model — trace the flight, likely needs
  more coast energy or less coast drag; do NOT touch the shared gains).
- RED: tests/test_phase4_e2e.py::test_stealth_kill_statistics_two_sided
  (close-in 10 km S-300 vs noisy stealth drone: kill fraction 0.47 vs
  ≥0.75 — terminal PN + lag vs OU noise; probe _drone_shot, consider
  whether the close-in geometry needs the boost-phase tilt to lead better
  or the band re-measured IF the physics is defensible).
- Full suite -n auto not yet re-run end-to-end after wave 2; then perf
  harness (tools/perf_harness.py), new default-battle digest measurement
  (old 7d5716…06add deliberately superseded), smoke run.
- tools/render_launch_sequences.py (GL frame strips per weapon,
  screenshot_harness pattern — _aim/_render_frame/read_pixels; oniks via
  s.request_launch, s300 via world.launch_sam vs an air track).
- Per-weapon launch VFX polish (research Part A): S-300 cold mortar puff,
  VLS flame+uptake jet, Buk/Pantsir needle trails, turbofan smokeless
  cruise (docs/research/launch_visuals_particles_2026-07-05.md recipe).
- Kalibr pre-existing note: fuel 80 kg honestly covers ~250 km at the
  4.4 kN sustainer (label says 500 km) — flag for a later balance pass.
- Pantsir real boost is 55 kN/1.5 s vs game 18 kN/3.5 s (flagged in
  research doc, not changed).
