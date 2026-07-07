# Sea State + Radar Clutter Implementation Plan (F3-P1 / F3-P2)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans
> (inline, SOLO — standing user rule). Contracts are VERBATIM from
> `docs/plans/feature_expansion_review_2026-07-06.md` §3 (LOCKED) and must
> not be weakened.

**Goal:** Douglas sea state 0–9 as a battle-setup condition: taller seas on
screen (`u_sea_amp`) and physically-degraded radar detection of low targets
(sea-clutter range factor inside `Radar.detects`).

**Architecture:** `world/ocean.py` keeps its 4 shader sines; one uniform
scales them (locked). `sim/clutter.py` is a pure GL-free lookup+interp
module; the hook multiplies `max_range` for `missile`/`stealth` classes
below `CLUTTER_ALT_M`. `sea_state=3` is today: `sea_amp_scale(3) == 1.0`
and `sea_clutter_range_factor(3, ·) == 1.0` EXACT (byte-identical default —
no radar_model flag needed; identity is by construction).

**Tech stack:** numpy/math sim, GLSL uniform, pytest -n auto.

## Global Constraints
- Same as the R-P0/R-P1 plan (solo, TDD red-first, full suite per gate,
  zero RNG, GL-free sim, no weakened contracts, research doc NORMATIVE).
- Locked F3 conventions: no FFT ocean; clutter curve justified from the
  GIT σ⁰ model in `docs/research/sea_clutter.md`; sim reads sea_state ONLY
  through `sim/clutter.py`.

## Tasks

### Task 1: `sim/clutter.py` + verbatim contracts
- Create `sim/clutter.py`: `CLUTTER_ALT_M = 100.0`,
  `sea_clutter_range_factor(sea_state: int, target_alt_m: float) -> float`.
  Curve: states ≤ 3 return exactly 1.0; `depth = clamp(1 - alt/CLUTTER_ALT_M, 0, 1)`;
  `factor = 1.0 - _REDUCTION[s] * depth` with
  `_REDUCTION = {4: .10, 5: .22, 6: .38, 7: .52, 8: .63, 9: .72}`
  (state ≥ 9 clamps to the 9 row; floor 0.28 ≥ the 0.25 contract bound).
- Tests (tests/test_sea_state_clutter.py): the four verbatim F3 contracts
  `test_sea_state_default_is_identity`, `test_clutter_monotonic_and_bounded`,
  `test_high_altitude_immune_to_clutter`, `test_sea_state_config_default_unchanged`
  + curve-shape sanity (deeper = worse).
- Research doc `docs/research/sea_clutter.md` FIRST (GIT σ⁰: clutter
  backscatter grows with wind/sea state and grazing angle; a low target
  competes with the clutter ridge inside the same range-Doppler cells →
  detection range factor; state-6-vs-skimmer band justified).

### Task 2: `Radar.detects` hook + config field + two-sided duel test
- `Radar` gains `sea_state: int = 3` attr (constructor kw, default keeps
  every construction identity). Hook in `detects`, after the EW/max_range
  resolution, before the range compare:
  `if size_class in ("missile", "stealth") and float(target_pos[1]) < CLUTTER_ALT_M:
       max_range *= sea_clutter_range_factor(self.sea_state, float(target_pos[1]))`
- `CombatConfig.sea_state: int = 3`, `CLAMP_SEA_STATE = (0, 9)`,
  clamp_config plumbing. `CombatWorld` threads config.sea_state onto EVERY
  radar it builds/registers (player, ships, Pantsir, Buk, CBR, enemy —
  one sea, both sides; set at construction or immediately after).
- Verbatim `test_sea_skimmer_detection_two_sided` with `_spy1` fixture:
  antenna 20 m, `missile` range 30 km (< the 34.4 km horizon at 15 m —
  the factor, not the horizon, must set the ratio), bisect detects()
  boundary at alt 15 m; state 6 in [0.45, 0.85]·state 3. Curve gives
  1 − 0.38·0.85 = 0.677 → inside the band with margin.

### Task 3: sea state VISUAL (`u_sea_amp`) + setup spinner
- `world/ocean.py`: `sea_amp_scale(state) -> float` — Douglas significant
  wave heights normalized to state 3 (0.88 m):
  `(0.0, 0.06, 0.34, 1.0, 2.14, 3.69, 5.68, 8.52, 13.07, 18.18)`
  (state 3 EXACTLY 1.0; vertical sines cannot self-intersect, steep is
  honest). Shader: `uniform float u_sea_amp` multiplying the height sum
  and the two normal derivative sums. `Ocean.draw(..., sea_amp=1.0)` sets
  it (default keeps sandbox/legacy callers identical).
- `game/sandbox.py:1659` passes
  `sea_amp_scale(getattr(world._config, "sea_state", 3))` (cache at state
  build; combat state reads its world config).
- Setup WORLD row: stepper `"SEA STATE"`, field `sea_state`, names
  `("0 GLASS","1 RIPPLED","2 SMOOTH","3 SLIGHT","4 MODERATE","5 ROUGH",
    "6 VERY ROUGH","7 HIGH","8 VERY HIGH","9 PHENOMENAL")`.
- Screenshot evidence: state 0 vs 3 vs 7 via the existing render-probe
  pattern, saved for the run log.

### Task 4: probe + run log + memory
- `tools/probe_sea_clutter.py`: detection-range vs sea-state table for
  Oniks skim (12 m) / TLAM skim (15 m) / drone (60 m) vs the SPY-1
  fixture + the player station — committed output cited by the run log.
- Run log update, memory update, full suite green.
