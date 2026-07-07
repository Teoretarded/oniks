# Sea state + clutter — run log (F3-P1/P2, 2026-07-07)

Plan: `docs/plans/sea_state_clutter_plan_2026-07-07.md`
Research (NORMATIVE): `docs/research/sea_clutter.md`
Contracts: VERBATIM from `feature_expansion_review_2026-07-06.md` §3.

## Shipped

- `sim/clutter.py`: `sea_clutter_range_factor(s, alt)` — states ≤ 3 exactly
  1.0 (identity by construction), GIT-shaped reduction table for 4–9,
  linear altitude depth to `CLUTTER_ALT_M = 100`, floor 0.28.
- `Radar.detects` hook (missile/stealth below 100 m) + `Radar.sea_state`
  attr (default 3 = identity); `CombatWorld._all_sea_state_radars()`
  threads the battle's state onto player net + engagement FCR + enemy
  ground/ship/AWACS radars — one sea, both sides. Fighter NOSE radars
  deliberately excluded (airborne lookdown clutter is a Doppler-notch
  problem, not this model — research doc §simplifications).
- `CombatConfig.sea_state = 3` + `CLAMP_SEA_STATE (0,9)` + clamp plumbing +
  WORLD-page spinner ("0 GLASS" … "9 PHENOMENAL"; the page-group parity
  guard caught the forgotten plate count — WORLD group 2 → 3).
- Visual: `world/ocean.py sea_amp_scale` (Douglas heights normalized to
  state 3 = exactly 1.0), `u_sea_amp` uniform scaling wave height AND
  normal slopes; `Ocean.draw(sea_amp=)` default 1.0 keeps legacy callers
  byte-identical; sandbox/combat states resolve it once from config.

## Measured (tools/probe_sea_clutter.py, detection km by state)

SPY-1-class fixture (20 m antenna, 30 km missile ring — range-bound):

| target | s3 | s4 | s5 | s6 | s7 | s9 |
|---|---|---|---|---|---|---|
| Oniks skim 12 m | 30.0 | 27.4 | 24.2 | 20.0 | 16.3 | 11.0 |
| TLAM skim 15 m | 30.0 | 27.4 | 24.4 | **20.3** | 16.7 | 11.6 |
| drone 60 m | 30.0 | 28.8 | 27.4 | 25.4 | 23.8 | 21.4 |

State 6 vs the 15 m skimmer = 0.68× — inside the locked [0.45, 0.85]
duel band. Player station (18 m mast, 120 km ring): **the horizon binds
before clutter at every state** (31.8/33.4/49.4 km flat rows) — correct
physics layering, and a doctrine insight: rough seas hurt the short-ringed
ship radars, the ground station is horizon-owned regardless.

## Crash investigated (user report: sandbox froze at BUILDING WORLD)

Root cause: the game was launched from the working tree during a ~1-minute
mid-edit window where `sim/radar.py` referenced the clutter helpers before
the import line landed → NameError on the first `detects()` call after
world build; the process died with the traceback in the launcher console
while the SDL window froze on the last-swapped "BUILDING WORLD..." frame.
Current tree verified healthy end-to-end: SandboxWorld construction +
10 s stepping, hidden-App `start_sandbox()` + `start_combat()` + stepped
renders, UI overlap oracle ALL PASS. `run_game.bat` already `pause`s, so
the traceback was visible in the console behind the frozen window.
Lesson (process): commit-or-stash before stepping away; the user may
launch the game at any moment.

## Pending / nits

- Sea-state SCREENSHOT gate (state 0 vs 3 vs 7 renders) not captured yet —
  the next visual pass / human playtest judges the swell scaling; the
  Douglas table may need a visual cap if state 9 reads as spikes (pure
  vertical sines can't self-intersect, but steepness taste is a
  screenshot call).
- Ocean wavelengths don't grow with state (locked: one amplitude uniform,
  no FFT) — heavy seas are taller, not longer. Revisit only if the
  playtest flags it.
