# Overnight Autonomous Build — Run Log

> Branch: `feat/combat-expansion` (off `master`). Method: Fable Method
> (implementer + 2-stage hostile review per feature; milestone gates verified by
> the orchestrator; physics-not-dice / fog-of-war / determinism / no-weakened-
> regressions contracts). Source of truth: `docs/research/handoff/` specs +
> `ROADMAP.md` (6 milestones). Per-feature/per-milestone detail lives in
> `docs/combat_build_log.md`; this file is the chronological agent ledger.

---

## MORNING REPORT

*(Filled in at halt. See the chronological ledger below until then.)*

**Status so far (updated 2026-06-17, overnight continuing):**
- Grounding complete (README, ROADMAP, specs 01–09, fable-method refs). Baseline
  green, branch `feat/combat-expansion` off `master`, baseline checkpoint `ac697d2`.
- **MILESTONE 1 (Legibility Foundation) — SHIPPED & GATED** (tip `3c10066`):
  widget primitives + SEMANTIC_COLORS + hud_widgets; track kind/size stamps;
  threat-warning strip; click-contact intel panel; per-tube battery panel.
  Full suite exit 0 (~864), smoke 70/70, Oniks-duel + determinism bit-identical
  (delta 0.0), fog honest (confirmed in a live battle), no-cheat CLEAN.
  Deferred: M1-F6 toast/hint upgrade (cosmetic). Human playtest recommended in AM.
- Now building Milestone 2 (SEAD / Anti-Radiation Warfare).

---

## CHRONOLOGICAL AGENT LEDGER

Format: `[timestamp] LABEL — role / model — task — verdict`

### Setup (orchestrator, no agents)
- Read handoff bundle in full (README, ROADMAP, 01–09) + fable-method refs.
- Confirmed baseline: `tools/smoke_combat.py` → 70/70, exit 0. Full suite kicked
  off in background to confirm the complete green baseline before checkpoint.
- Created branch `feat/combat-expansion`; `master` untouched.
- Pre-existing uncommitted working tree (28 tracked files +1251/−132, plus new
  `models/missiles.py` + test files matching the handoff) checkpointed as the
  baseline commit so milestone commits stay isolated (the flight recorder).
  Baseline commit `ac697d2`.

### M1-F1 Widget primitive library
- `build:M1-F1` — IMPLEMENTER / opus — badge/gauge_bar/mini_compass/tab_strip/
  scroll_list + SEMANTIC_COLORS + hud_widgets.py, TDD test_widgets.py — DONE
  (25 tests, full suite exit 0, combat_setup left untouched). Commit `73e7bfd`.
- `verify-spec:M1-F1` — SPEC REVIEW / opus — re-read spec 08 + diff, re-ran
  targeted tests — REJECTED: missing the spec-mandated tab_strip refactor of
  combat_setup + its regression. (Code unchanged otherwise compliant; no
  weakened tests; no hard-coded RGB; purity confirmed.)
- `review-quality:M1-F1` — CODE-QUALITY REVIEW / opus — APPROVED with 3 minor
  nits (docstring 1px→1.5px, SEMANTIC_STATES parallel list, style).
- `fix:M1-F1` — FIXER / opus — added tab_strip fixed-column mode (byte-identical
  to the old inline loop, empirically verified), refactored combat_setup, added
  regression test, derived SEMANTIC_STATES, fixed docstring — DONE (841 collected
  exit 0). Commit `fa72af0`. Orchestrator re-verified targeted tests + diff.

### M1-F2 track['kind']/track['size'] stamps
- `build:M1-F2` — ORCHESTRATOR-IMPLEMENTED (lean; mechanical 2-stamp change),
  TDD test_track_stamps.py — smoke gate caught an IrMissile `.weapon` crash,
  fixed (guard + weapon_id fallback). Commit `cda32d3`.
- `verify-spec+nocheat:M1-F2` — REVIEW / opus — fog verdict CLEAN (no truth
  leak); REJECTED on a missing third stamp site (`_inject_elint_tracks`).
- `fix:M1-F2` — ORCHESTRATOR — stamped the ELINT site via shared helpers +
  ELINT-injection test. Commit `f2e5afd`. Smoke 70/70 re-verified.

### M1-F3/F5 Threat-Warning strip + Click-contact intel panel
- `build:M1-TaskA` — IMPLEMENTER / opus — threat_rows + contact_intel pure
  helpers + _threat_strip/_intel_panel draw methods + 11 TDD tests — DONE
  (857 passed, smoke 70/70). Commit `e401d67`.
- `verify-spec+nocheat:M1-TaskA` — REVIEW / opus — line-by-line incl. draw
  methods — APPROVED, fog-honest end-to-end, no truth leak, HOSTILE_KINDS sound.
- `review-quality:M1-TaskA` — CODE-QUALITY / opus — APPROVED, no Critical/
  Important; 4 minor cosmetic nits logged.

### M1-F4 Tube/battery status panel
- `build:M1-F4` — IMPLEMENTER / opus — tube_cells + _block cells row + EMPTY
  color + 6 TDD tests — DONE (864 passed; smoke caught+fixed a badge signature
  bug, then 70/70). Commit `c8d0d7e`. Orchestrator self-verified the diff
  (own-force-only, _block backward-compatible).

### M1 milestone gate — PASSED clean in one pass
- `gate:M1-fullsuite` — ORCHESTRATOR — pytest -q exit 0 (~864); smoke 70/70;
  Oniks-duel + missile-flight + SM-6 contracts green (bit-identical).
- `gate:M1-gametest` — GAME-TEST / opus — drove live headless battles, measured
  all surfaces + determinism (max delta 0.0 @15k steps), fog confirmed live,
  795 calls 0 exceptions — PASS. Left `tools/probe_m1_legibility.py`. (First
  dispatch died on an infra socket error; re-dispatched, succeeded.)
- `gate:M1-bughunt` — BUG-HUNT / opus — SAFE TO GATE; one LOW (scroll_list
  row_h<=0) fixed (`3c10066`).
- `gate:M1-nocheat` — NO-CHEAT / opus — CLEAN, no truth leak (helpers + draw).
- **M1 COMPLETE.** Branch tip after gate: `3c10066`.

### M2 — SEAD / Anti-Radiation Warfare
- `build:M2-T1` — IMPLEMENTER / opus — emitter ELINT channel (separate
  `emitter_contacts` store + resolver) + 6 tests — DONE (870). Commit `adf55b3`.
  Orchestrator self-verified diff (est_pos not truth; contacts.tracks untouched).
- `build:M2-T2` — IMPLEMENTER / opus — KH-31P ARM (reuse HarmMissile,
  is_hostile=False, launch_arm, victory credit, flyoff probe) + 10 tests — DONE
  (881). Commit `34088c7`. MEASURED: airframe over-reaches 110→130 km (HARM does
  too); locked envelope to measured kill@90/short@140.
- `verify-spec+physics+nocheat:M2-T2` — REVIEW / opus — APPROVED (physics
  measured not faked; CEP miss can't credit; byte-identical fingerprint).
- `review-quality:M2-T2` — CODE-QUALITY / opus — APPROVED; 2 minor nits fixed
  (`6c39bb2`).
- `build:M2-T3` — IMPLEMENTER / opus — enemy radar EMCON vs sensed ARM (ship +
  ground, fog-honest) + 8 tests — DONE (889). Commit `ba083aa`.
- `gate:M2-gametest` — GAME-TEST / opus — CONCERN: ship SPY-1 resurrected each
  tick (ARM can't kill it). Probe `tools/probe_m2_sead.py`.
- `gate:M2-bughunt` — BUG-HUNT / opus — HIGH-1 ARM-EMCON dead in play (feed
  filter); HIGH-2 ground radars out of ARM reach; LOW-4 attribution; rest CLEAN.
- `gate:M2-nocheat` (1st) — died on API Overloaded; re-dispatched.
- `gate-fix:M2` — FIXER / opus — fed ARM to enemy picture (detection-gated) +
  stopped ship-radar resurrection + 3 real-ARM e2e tests (RED→GREEN) + documented
  ground-radar gap — DONE (892, smoke 70/70, byte-identical). Commit `472bc6e`.
- `gate:M2-nocheat` (re-dispatch) — NO-CHEAT / opus — CLEAN, all 7 surfaces; ARM-
  EMCON + feed read only sensed tracks; determinism intact.
- **M2 sim COMPLETE + gated.** Remaining: M2-T4 player UI (armory/control/overlay)
  to make the SEAD capability playable; dedicated KH-31P mesh + photos (task #7).

### M2-T4 — player UI for the ARM
- `build:M2-T4` (1st) — died on a transient 529 Overloaded (0 tokens); re-dispatched.
- `build:M2-T4` — IMPLEMENTER / opus — armory ammo stepper + 3-way gated B-cycle +
  request_launch ARM branch + tactical_map emitter glyph/pick/select + hud weapon
  strip + ARM seeker readout + 27 TDD tests — DONE (919 passed, smoke 70/70,
  live-GL probe verified). Commit `d9c4f4b`. Orchestrator re-verified smoke + UI +
  Oniks-duel.
- **M2 COMPLETE + playable.** Branch tip `d9c4f4b`.

### Note: infrastructure
- Several agents hit transient API "Overloaded" (529) errors mid-run (1st M2
  no-cheat auditor, 1st M2-T4 implementer, 1st M1 game-test socket close). All
  re-dispatched and succeeded — no work lost (completed/committed work is never redone).

### Next
- Task #7: dedicated KH-31P mesh (`build_kh31p`) + reference photos to
  `Assets of oinks/New models 1` (the user's explicit ask). Then assess M3.

