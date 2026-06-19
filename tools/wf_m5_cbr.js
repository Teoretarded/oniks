export const meta = {
  name: 'm5-counter-battery-radar',
  description: 'M5 #3: player Counter-Battery / Early-Warning Radar — early inbound-track detection (threat strip TTI) + SYMMETRIC shooter back-plot via the SHARED back_plot_surface() helper + a counter-fire cue. Emits -> honestly ESM/HARM-able. n_cbr=0 byte-identical. implementer -> spec review -> fix -> quality review -> fix',
  phases: [
    { title: 'Implement' },
    { title: 'Spec review' },
    { title: 'Spec fix' },
    { title: 'Quality review' },
    { title: 'Quality fix' },
  ],
}

const CONVENTIONS = `
ENV: Python 3.11, cwd = repo root "C:\\Users\\teoti\\OneDrive\\Desktop\\New folder\\oinks PROTO".
  Full suite: python -m pytest -q (~7 min). Smoke: python tools/smoke_combat.py (70/70 exit 0).
  Commit per task with a conventional message; NEVER touch git main. Branch: feat/combat-expansion.
NON-NEGOTIABLES:
 - BYTE-IDENTICAL DEFAULT (THE GATE): the new CombatConfig field n_cbr (default 0) gates EVERYTHING. With
   n_cbr=0: NO CBR Structure/radar is built, it is NOT in self.radar_net or any emitter/ELINT list, the
   CbrTracker is never stepped, world.cbr_threats / world.cbr_cues are empty, and the default battle +
   Oniks-vs-SM-2 duel (tests/test_sm2_statistics.py) + determinism stay BIT-IDENTICAL. PROVE with a same-seed
   multi-thousand-step state digest == pre-change HEAD. LOCKED schema: sign-off GRANTED on the 0-default; add
   CLAMP_CBR (floor 0) + clamp_config + tests/test_combat_config.py.
 - SHARED HELPER (the WHOLE POINT — symmetry): the CBR's shooter back-plot MUST CALL the existing module-level
   sim/commander.back_plot_surface() helper (already extracted in M5 #2) — do NOT copy/re-derive the
   back-projection. The enemy commander and the player CBR run the SAME math; a symmetry test feeds identical
   (first_pos, first_vel) to BOTH paths and asserts identical output. Read the helper's real signature first.
 - FOG / NO CHEAT (the central risk — spec calls it out): the CbrTracker reads ONLY tracks the CBR's own
   Radar.detects() passes (range-class gate + 4/3-earth horizon + terrain LOS) — NEVER a live missile/ship
   truth pos. A track OVER THE HORIZON or TERRAIN-MASKED yields NO threat and NO cue. Guard with a test that
   places a hostile outside detects() and asserts empty output. The cue is an ESTIMATE with error, never a
   truth read.
 - PHYSICS NOT DICE: the threat TTI emerges from the track's closure geometry (mirror
   sim/pantsir.PantsirDefenseController._time_to_impact); the cue error is det_range*BACKPLOT_ERR_FRAC (the
   same error model as the enemy back-plot); no kill/▒hit rolls anywhere. It does NOT auto-fire (player agency).
 - HONEST COST (symmetry of exposure): the CBR EMITS, so it must be ADDED to world/combat.py _emitters() and
   the _feed_enemy_picture emitter-accrual loop so the enemy ESM can localize it and the commander can HARM it
   (it is a real EmitterIntel like the radar station). A test asserts the enemy picture gains the CBR's emitter
   id when it is emitting. Killing the CBR Structure clears its radar.alive and drops it from radar_net +
   the emitter feed (mirror the radar-station / Pantsir on_destroyed).
 - DETERMINISM: a FRESH child-stream tag [seed, 9] for any CBR noise (the back-plot itself is deterministic;
   likely no RNG is needed — if so, none is added). Tags 3-8, 12, 13, 14, 15 are TAKEN and 10(decoys)/
   11(relocate) RESERVED — use ONLY 9. No wall-clock.
 - REGRESSION NEVER WEAKENED: if a planned test can't pass honestly, report BLOCKED — never widen a tolerance.
 - DEFER UI + meshes: the HUD threat strip + the tactical-map CB-cue markers / back-plot ray / CBR star are
   DEFERRED to the later UI-wiring pass. BUT the pure CbrTracker + the read-only world.cbr_threats /
   world.cbr_cues accessors ARE headless-testable now and MUST be covered. Keep all logic in sim/ + world/
   (GL-free); game/* imports pygame at top (untestable headless).
 STATUS: DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT. Bad work is worse than no work.`

const ANCHORS = `
VERIFIED ANCHORS (read before coding):
 - sim/commander.py: back_plot_surface(first_pos, first_vel, *, coast_z=HOME_COAST_Z, climb_vy=BACKPLOT_CLIMB_VY,
   min_close_vz=BACKPLOT_MIN_CLOSE_VZ, coast_setback_m=BACKPLOT_COAST_SETBACK_M) -> (x,z)|None — the shared
   helper (CONFIRM the exact signature in the file). process_missile_track (~1503) is the enemy-side caller;
   the CBR is the symmetric player-side caller. BACKPLOT_ERR_FRAC=0.02 is the error model.
 - world/combat.py: the radar_station build + _spawn_enemy_radars (~1023) + _build_buk_battery (~2739, the most
   RECENT "a player radar Structure joins self.radar_net + a destructible wrapper + on_destroyed drops it from
   the net" sibling — mirror it for the CBR). _emitters (~776) + _feed_enemy_picture (~1059, where player
   emitters accrue into the enemy EnemyPicture via update_emitter) — ADD the CBR emitter here (honest cost).
   step (~3058) — step the CbrTracker AFTER the contact/strike layers are current this frame (so it sees this
   tick's inbound tracks), like _step_acoustic_sensors. world._player_visible already ORs radar_net, so the CBR
   joining radar_net makes inbound Tomahawk/JASSM/HARM tracks appear EARLIER on the ContactBoard (test c).
 - sim/radar.py Radar + RadarNetwork: the set itself. The CBR uses a TALL antenna (~35 m mast, better horizon
   vs 50 m sea-skimmers) + a LONG 'missile' range (~190 km) but deliberately SHORT 'ship'/'fighter' ranges
   (it is a missile-WARNING set, not a surface-search set, so it complements the 18 m station, not replaces it).
   Constants: CBR_ANTENNA_M, CBR_RANGES {missile, ship, fighter, stealth}.
 - sim/pantsir.py PantsirDefenseController._time_to_impact — the TTI math to mirror for the threat strip.
 - sim/counter_battery.py is NEW: CbrTracker (pure numpy, GL-free). Each step it consumes the inbound HOSTILE
   StrikeMissile / SamMissile(is_hostile) tracks the CBR's Radar.detects() passes, maintains first-seen
   metadata (mirror world/combat _cmd_missile_intel: first_seen_t / first_seen_pos / first_seen_vel /
   detector_pos), and emits {threats:[{tti, pos, track_id}], cues:[{shooter_xz, error_m, track_id}]} — calling
   back_plot_surface() for each young/low track to get the shooter cue.
 - world/combat_config.py: CombatConfig + CLAMP_* + clamp_config + DEFAULT. Add n_cbr (default 0) mirroring the
   n_buk / n_subs pattern EXACTLY (CLAMP_CBR=(0,2) floor 0). tests/test_combat_config.py round-trip.
 - tools/probe_*.py — the probe idiom. Write tools/probe_cbr.py to MEASURE: the CBR's early-detection lead
   (sim_time the CBR sees an inbound Tomahawk vs the 18 m station alone) and the shooter-cue error vs the true
   launch ship, BEFORE locking the tests.`

const TEST_CONTRACTS = `
TDD: write tools/probe_cbr.py + the test files FIRST. Contracts (spec 06 F3):
 tests/test_counter_battery.py (headless, pure CbrTracker + world accessors):
  - feed a synthetic inbound StrikeMissile track the CBR CAN see -> a threat with a FINITE, physically-correct
    TTI, and (for a young, low track) a back-plot CUE whose shooter_xz is within BACKPLOT_ERR_FRAC*det_range of
    the true launch ship;
  - FOG/HONESTY (load-bearing): a track OUTSIDE the CBR's detects() (over the horizon / terrain-masked) yields
    NO threat AND NO cue (the tracker reads only the gate, never truth);
  - EARLY WARNING: the CBR set joins world.radar_net and surfaces an inbound Tomahawk on the ContactBoard at an
    EARLIER sim_time than the 18 m station alone (compare detection times with vs without the CBR);
  - SYMMETRY: back_plot_surface() called via the CBR path and via the enemy commander path returns IDENTICAL
    output for the same (first_pos, first_vel) inputs (the shared helper is the single source);
  - HONEST COST: with the CBR emitting, the enemy EnemyPicture gains an EmitterIntel for the CBR id (it can be
    ESM-localized + HARMed); killing the CBR Structure drops it from radar_net + the emitter feed;
  - ERROR FLOOR: the cue error_m stays >= det_range*BACKPLOT_ERR_FRAC (a cue, not a snipe);
  - DETERMINISM: identical inputs -> identical threats/cues (tag [seed,9] if any noise; ideally none).
 tests/test_combat_config.py: clamp_config round-trips n_cbr; the OFF default (n_cbr=0) survives the clamp path.
 REGRESSION: n_cbr=0 -> default battle + duel + full suite + smoke bit-identical (digest).`

const IMPL_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['status', 'files_changed', 'tests_added', 'measured', 'byte_identical_note', 'concerns'],
  properties: {
    status: { type: 'string', enum: ['DONE', 'DONE_WITH_CONCERNS', 'BLOCKED', 'NEEDS_CONTEXT'] },
    files_changed: { type: 'array', items: { type: 'string' } },
    tests_added: { type: 'array', items: { type: 'string' } },
    measured: { type: 'string', description: 'Probe: CBR early-detection lead (s) vs the 18 m station, shooter-cue error vs the true launch ship, TTI sanity; the SYMMETRY equality with the enemy path; full suite + smoke counts.' },
    byte_identical_note: { type: 'string', description: 'Proof n_cbr=0 keeps the default battle + duel bit-identical (digest); CBR absent from radar_net/emitters at count 0; CBR present in the emitter feed at count>0 (honest cost).' },
    concerns: { type: 'string' },
  },
}
const REVIEW_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['verdict', 'reran_tests_output', 'findings'],
  properties: {
    verdict: { type: 'string', enum: ['PASS', 'FAIL'] },
    reran_tests_output: { type: 'string' },
    findings: { type: 'array', items: { type: 'object', additionalProperties: false,
      required: ['severity', 'file', 'line', 'issue', 'required_fix'],
      properties: {
        severity: { type: 'string', enum: ['BLOCKER', 'MAJOR', 'MINOR'] },
        file: { type: 'string' }, line: { type: 'string' }, issue: { type: 'string' }, required_fix: { type: 'string' },
      } } },
  },
}

phase('Implement')
const impl = await agent(
`You are the IMPLEMENTER for M5 #3 — the player COUNTER-BATTERY / EARLY-WARNING RADAR (CBR). It is a fixed
player ground radar that (a) catches INBOUND strike tracks EARLY (tall mast + long missile-class range) so the
player gets a threat-warning strip with time-to-impact, and (b) BACK-PLOTS the SHOOTER using the SHARED
back_plot_surface() helper (the symmetric mirror of the enemy's trick) to produce a counter-fire CUE at the
launching ship/fighter. It EMITS, so it is honestly ESM-locatable + HARM-able. It does NOT auto-fire. n_cbr=0
keeps everything OFF and byte-identical. TDD; measure the early-warning lead + cue error with a probe first.
${CONVENTIONS}
${ANCHORS}
${TEST_CONTRACTS}
Build order: (1) sim/counter_battery.py — CbrTracker (pure numpy: ingest the CBR-detected inbound hostile
tracks, keep first-seen metadata, emit threats[{tti,pos}] + cues[{shooter_xz,error_m}] via back_plot_surface()).
(2) world/combat.py — build the CBR Radar (tall mast + missile-warning ranges) + a destructible Structure +
on_destroyed (joins/leaves radar_net like the Buk radar); add the CBR to _emitters() + _feed_enemy_picture
(honest cost); step the CbrTracker in step(); expose read-only world.cbr_threats / world.cbr_cues. (3)
world/combat_config.py — n_cbr + CLAMP_CBR + clamp_config + DEFAULT. (4) tests + tools/probe_cbr.py FIRST. Run
all new tests + the duel + full suite + smoke; PROVE the n_cbr=0 digest is byte-identical to HEAD, the
CBR is absent from radar_net/emitters at 0 and present at >0, and the SYMMETRY equality holds. Report measured
numbers + the byte-identical proof. DEFER the HUD threat strip + map markers (the pure tracker + accessors are
tested now). Commit with a conventional message. BLOCKED if any contract cannot hold honestly (esp. a truth
read sneaking into the tracker, or a copy of the back-plot math instead of the shared helper).`,
  { label: 'implement:M5-cbr', phase: 'Implement', schema: IMPL_SCHEMA }
)
log(`Implementer: ${impl ? impl.status : 'NULL'} — ${impl ? impl.measured : ''}`)
if (!impl || impl.status === 'BLOCKED' || impl.status === 'NEEDS_CONTEXT') {
  return { halted: true, stage: 'implement', impl }
}

phase('Spec review')
const specReview = await agent(
`SPEC-COMPLIANCE reviewer for M5 #3 Counter-Battery Radar. DO NOT TRUST THE IMPLEMENTER. Re-read spec 06 (the
CBR feature) + the diff (git show), and RE-RUN the tests + tools/probe_cbr.py yourself. VERIFY:
 - BYTE-IDENTICAL DEFAULT: independently digest a same-seed multi-thousand-step run at n_cbr=0 == pre-change
   HEAD; duel + smoke + full suite green; the CBR is absent from radar_net + every emitter list at n_cbr=0.
 - SHARED HELPER: grep that the CBR's shooter back-plot CALLS sim/commander.back_plot_surface() and does NOT
   copy the back-projection; the SYMMETRY test proves identical output to the enemy path for identical inputs.
 - FOG/NO-CHEAT: the CbrTracker reads ONLY tracks the CBR's Radar.detects() passes — grep for any live missile/
   ship truth read; confirm an over-horizon/terrain-masked hostile yields NO threat + NO cue (re-run that test).
 - PHYSICS-NOT-DICE: TTI from closure geometry; cue error = det_range*BACKPLOT_ERR_FRAC; the error floor holds;
   no auto-fire; no rolls.
 - HONEST COST: with the CBR emitting, the enemy EnemyPicture gains its EmitterIntel id (HARM-able); killing the
   CBR drops it from radar_net + the emitter feed.
 - EARLY WARNING: the CBR surfaces an inbound Tomahawk on the ContactBoard EARLIER than the 18 m station alone.
 - DETERMINISM: tag [seed,9] only (no collision with 8/10/11/12/13/14/15); no wall-clock. No test weakened.
Re-run: the new test files + tests/test_sm2_statistics.py + tests/test_combat_config.py + full suite + smoke.
${CONVENTIONS}
Implementer: ${impl.status}; measured=${impl.measured}; byteid=${impl.byte_identical_note}
PASS only if EVERY contract holds — especially byte-identical default + the SHARED-helper symmetry + the
fog/no-cheat gate. Findings with file:line.`,
  { label: 'spec-review:M5-cbr', phase: 'Spec review', schema: REVIEW_SCHEMA }
)
log(`Spec review: ${specReview ? specReview.verdict : 'NULL'} (${specReview ? specReview.findings.length : 0}) — ${specReview ? specReview.reran_tests_output : ''}`)

if (specReview && specReview.verdict === 'FAIL' && specReview.findings.length) {
  phase('Spec fix')
  const fix = await agent(
`FIXER for M5 #3 CBR. Fix ALL findings without weakening tests or breaking: byte-identical default, the
shared-helper symmetry, fog/no-cheat, physics-not-dice, the honest-cost emitter feed, determinism. Re-run all
CBR tests + the duel + test_combat_config + full suite + smoke + tools/probe_cbr.py. Commit.
${CONVENTIONS}
FINDINGS:
${specReview.findings.map((f, i) => `${i + 1}. [${f.severity}] ${f.file}:${f.line} — ${f.issue}\n   FIX: ${f.required_fix}`).join('\n')}`,
    { label: 'spec-fix:M5-cbr', phase: 'Spec fix', schema: IMPL_SCHEMA }
  )
  log(`Spec fix: ${fix ? fix.status : 'NULL'}`)
  const recheck = await agent(
`Re-verify M5 #3 CBR after the fixer: re-run all CBR test files + the duel + test_combat_config + full suite +
smoke + the probe. Confirm byte-identical default + shared-helper symmetry + fog/no-cheat + honest-cost. PASS/FAIL with counts.
${CONVENTIONS}`,
    { label: 'spec-recheck:M5-cbr', phase: 'Spec fix', schema: REVIEW_SCHEMA }
  )
  log(`Spec recheck: ${recheck ? recheck.verdict : 'NULL'}`)
  if (recheck && recheck.verdict === 'FAIL') return { halted: true, stage: 'spec-recheck', specReview, recheck }
}

phase('Quality review')
const qReview = await agent(
`CODE-QUALITY reviewer for M5 #3 CBR (spec passed). Judge whether it is WELL BUILT:
 - CbrTracker is a clean, single-responsibility pure module reusing back_plot_surface() (NO duplication of the
   back-projection) and the TTI math (no copy of the Pantsir closure code if a shared helper is sensible);
 - the CBR radar/Structure/on_destroyed mirror the established Buk/radar-station pattern (no bespoke wiring);
 - named, commented CBR constants (antenna height, ranges, the error model reuse) — no magic numbers;
 - no per-tick allocations in the tracker step; no dead code;
 - tests verify measured behavior (early-warning lead, cue error, TTI, symmetry, fog gate) not tautologies;
 - the fog gate + the byte-identical-default + the honest-cost emitter feed are structurally enforced.
Re-run the CBR tests + smoke. Findings with file:line.
${CONVENTIONS}`,
  { label: 'quality-review:M5-cbr', phase: 'Quality review', schema: REVIEW_SCHEMA }
)
log(`Quality review: ${qReview ? qReview.verdict : 'NULL'} (${qReview ? qReview.findings.length : 0})`)
if (qReview && qReview.verdict === 'FAIL' && qReview.findings.filter(f => f.severity !== 'MINOR').length) {
  phase('Quality fix')
  const qfix = await agent(
`FIXER for M5 #3 CBR code-quality findings. Fix BLOCKER/MAJOR (MINOR where cheap) without changing behavior or
weakening tests. Re-run the CBR tests + smoke. Commit.
${CONVENTIONS}
FINDINGS:
${qReview.findings.map((f, i) => `${i + 1}. [${f.severity}] ${f.file}:${f.line} — ${f.issue}\n   FIX: ${f.required_fix}`).join('\n')}`,
    { label: 'quality-fix:M5-cbr', phase: 'Quality fix', schema: IMPL_SCHEMA }
  )
  log(`Quality fix: ${qfix ? qfix.status : 'NULL'}`)
}

return {
  done: true, implementer: impl,
  spec_verdict: specReview ? specReview.verdict : null,
  quality_verdict: qReview ? qReview.verdict : null,
  spec_findings: specReview ? specReview.findings : [],
  quality_findings: qReview ? qReview.findings : [],
}
