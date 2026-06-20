export const meta = {
  name: 'm5-esm-decoys',
  description: 'M5 #5 (last M5): ESM decoy emitters (draw enemy ESM/HARM onto a worthless decoy) + corner-reflector back-plot decoys (seed bogus launch clusters so enemy TLAM/JASSM scatter onto empty coast). The AI is fooled because its SENSORS are fooled — never a truth edit. n_decoys=n_corner_reflectors=0 byte-identical. implementer -> spec review -> fix -> quality review -> fix',
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
 - BYTE-IDENTICAL DEFAULT (THE GATE): the new CombatConfig fields n_decoys + n_corner_reflectors (BOTH default
   0) gate EVERYTHING. With both 0: NO decoy emitter and NO reflector is built, none appears in _emitters() /
   the ELINT feed / the enemy EnemyPicture, the reflector back-plot bias is never applied, and the enemy
   picture + back-plot clusters are BIT-IDENTICAL to today. PROVE with a same-seed multi-thousand-step state
   digest (incl. commander.picture.emitters + _back_plots + clusters) == pre-change HEAD. LOCKED schema:
   sign-off GRANTED on the 0-default; add CLAMP_DECOYS + CLAMP_CORNER_REFLECTORS (floor 0) + clamp_config +
   tests/test_combat_config.py.
 - HONESTY IS THE CENTRAL CONTRACT (the AI is fooled because its SENSORS are fooled — NEVER because we lie to
   the AI): the enemy commander is NOT modified — it already iterates picture.emitters (schedules HARM at any
   located+alive radar) and forms LaunchClusters from back-plots. A decoy works ONLY by planting a REAL sensor
   event: (1) the DECOY EMITTER is a radiating object the enemy ESM genuinely hears (added to _emitters() + the
   _feed_enemy_picture emitter-accrual loop so commander.update_emitter builds a real EmitterIntel on it); (2)
   the CORNER-REFLECTOR is a real false RF return near a planted XZ that biases the enemy's back-plot of a real
   player launch (an EXTRA / biased BackPlotEntry added through the SAME add_back_plot / back_plot_surface
   path), NOT a flag that tells the AI to miss. ABSOLUTELY NO "decoy => AI misses" boolean and NO truth edit.
 - PHYSICS NOT DICE: the HARM/TLAM wasted on a decoy is the EXISTING seeker/fuse/refine path acting on a real
   (planted) sensor fix — the round flies to the decoy/cluster centroid and _refine_strike_aim finds the decoy
   Structure (or empty dirt) there. No miss rolls. The decoy emitter NEVER detects anything (empty radar ranges
   — it is bait, not a sensor).
 - DETERMINISM: a FRESH child-stream tag [seed, 10] for any decoy placement/noise. Tags 3-8, 9(CBR), 11(relocate),
   12, 13, 14, 15 are TAKEN — use ONLY 10. No wall-clock. Same seed -> same decoy/reflector placement + bias.
 - REGRESSION NEVER WEAKENED: a decoy killed by a HARM marks its EmitterIntel dead via the EXISTING HARM BDA
   path (mark_emitter_destroyed). If a planned test can't pass honestly, report BLOCKED — never widen a tolerance.
 - DEFER UI + meshes: the tactical-map decoy/CR markers + the ON/OFF emit toggle affordance + the HUD decoy
   line are DEFERRED to the later UI-wiring pass. BUT the sim/world wiring (the decoy emitter heard by the
   feed, the reflector back-plot bias, the config gate) IS headless-testable now and MUST be covered. Keep logic
   in sim/ + world/ (GL-free); game/* imports pygame at top (untestable headless).
 STATUS: DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT. Bad work is worse than no work.`

const ANCHORS = `
VERIFIED ANCHORS (read before coding):
 - world/combat.py _emitters (~776): the list of player radiating sets the enemy ESM can hear (the radar
   station + CBR). ADD live decoy emitters here. _feed_enemy_picture (~1059): the per-step loop that accrues
   heard emitters into commander.picture via update_emitter (builds EmitterIntel / located fixes). The decoy
   rides the SAME path as the real radar.
 - sim/commander.py: update_emitter + EmitterIntel + _doctrine_blind (schedules a HARM package at a located+
   alive emitter — it will target a convincing decoy) + mark_emitter_destroyed (the HARM BDA path that marks an
   emitter dead — a killed decoy uses it) + add_back_plot (~389) + _update_clusters (~406) + back_plot_surface()
   (~292, the shared helper) + process_missile_track (~1503, the enemy back-plot feed). DO NOT modify the
   commander's decision logic — the decoys plant real sensor events it already consumes.
 - world/combat.py: the path that feeds process_missile_track for each detected player-missile track each step
   (search "process_missile_track"). The CORNER-REFLECTOR bias hooks HERE: when a planted reflector lies near a
   real player launch's ground track, inject an EXTRA biased BackPlotEntry toward the reflector (a real false-
   return geometry), so a LaunchCluster can form on the decoy coast. Implement as an optional decoy_sites list
   consulted in the feed — NOT a truth edit.
 - sim/radar.py Radar: a DecoyEmitter can REUSE Radar with EMPTY ranges (never detects) but real
   .alive/.emitting/.pos/.antenna_alt/.radar_id so ElintReceiver + the enemy feed hear it; OR a tiny dedicated
   class exposing the same attrs. sim/recon.py ElintReceiver is what hears emitters.
 - sim/bases.py Structure: decoy emitter + corner reflector are destructible Structures (low HP) so a HARM/TLAM
   into one is a satisfying waste; reuse a cheap kind (confirm it does NOT count toward defeated/victorious —
   like the CBR/Pantsir wrappers, which filter to bastion_tel / enemy structures only).
 - world/combat_config.py: CombatConfig + CLAMP_* + clamp_config + DEFAULT. Add n_decoys + n_corner_reflectors
   (both default 0) mirroring the n_cbr / n_buk pattern (CLAMP floor 0).
 - sim/decoys.py is NEW: DecoyEmitter + CornerReflector data + a pure helper to bias a back-plot toward a nearby
   reflector. tools/probe_decoys.py: MEASURE the HARM-diverted-to-decoy event + the reflector-biased cluster
   centroid vs the real pad BEFORE locking the tests.`

const TEST_CONTRACTS = `
TDD: write tools/probe_decoys.py + the test files FIRST. Contracts (spec 06 F4):
 tests/test_decoy_emitter.py:
  - with a decoy EMITTING and the real radar SILENT, the enemy EnemyPicture forms a located EmitterIntel on the
    DECOY id, and commander._doctrine_blind schedules a HARM package whose target_id == the decoy (HARM wasted)
    — fog-honest (the commander only ever saw a real emission);
  - the decoy in _emitters() is HEARD by ElintReceiver / the enemy feed but NEVER detects anything (empty ranges
    — assert detects() returns nothing for any target);
  - a decoy Structure killed by a HARM marks its EmitterIntel dead (mark_emitter_destroyed via the existing BDA).
 tests/test_corner_reflector.py:
  - a planted reflector biases the enemy back-plot so a LaunchCluster.centre forms within X m of the reflector
    (NOT the real pad), and a commander TLAM/JASSM salvo aims there -> _refine_strike_aim finds NO real structure
    within SEEKER_BASKET_M -> dirt (the real TEL survives);
  - the reflector bias is a SENSOR-LEVEL plant (an added BackPlotEntry from a real geometry), provable by the
    enemy acting on a normal cluster — NOT a "miss" flag.
 HONESTY / REGRESSION (load-bearing): with NO decoy lit AND NO reflector (n_decoys=n_corner_reflectors=0), the
   enemy picture (emitters + _back_plots + clusters) is BIT-IDENTICAL to today over a multi-thousand-step digest;
   duel + full suite + smoke green.
 DETERMINISM: tag [seed,10]; same seed -> same placement + bias.
 CONFIG: tests/test_combat_config.py round-trips n_decoys + n_corner_reflectors; the OFF default survives the clamp path.`

const IMPL_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['status', 'files_changed', 'tests_added', 'measured', 'byte_identical_note', 'concerns'],
  properties: {
    status: { type: 'string', enum: ['DONE', 'DONE_WITH_CONCERNS', 'BLOCKED', 'NEEDS_CONTEXT'] },
    files_changed: { type: 'array', items: { type: 'string' } },
    tests_added: { type: 'array', items: { type: 'string' } },
    measured: { type: 'string', description: 'Probe: the HARM diverted to the decoy id; the reflector-biased cluster centroid vs the real pad (and the stale-pad refine -> dirt); the decoy detects-nothing check; full suite + smoke counts.' },
    byte_identical_note: { type: 'string', description: 'Proof n_decoys=n_corner_reflectors=0 keeps the enemy picture (emitters+back_plots+clusters) bit-identical to HEAD (digest); decoys absent from all feeds at 0; present + HARM-able at >0; NO commander decision-logic edit and NO truth/miss flag.' },
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
`You are the IMPLEMENTER for M5 #5 (the LAST M5 feature) — ESM DECOY EMITTERS + CORNER-REFLECTOR back-plot
decoys. Two cheap player spoofers: (1) a decoy EMITTER that radiates a radar-like signature so the enemy ESM
fixes it and the commander wastes a HARM package on a worthless decoy; (2) a corner REFLECTOR that plants a
false RF return near a fake coastal point so the enemy's launch back-plot clusters there and its TLAM/JASSM
salvo scatters onto empty ground. The hard rule: the enemy AI is fooled because its SENSORS are fooled — you
plant REAL sensor events, you NEVER edit the AI's decision or add a "miss" flag or read/write truth. Both
default 0 -> byte-identical. TDD; measure the HARM diversion + the reflector-biased cluster with a probe first.
${CONVENTIONS}
${ANCHORS}
${TEST_CONTRACTS}
Build order: (1) sim/decoys.py — DecoyEmitter (radar-like attrs, EMPTY ranges so it never detects) +
CornerReflector (XZ + influence) + a pure back-plot-bias helper. (2) world/combat.py — build decoys/reflectors
as destructible Structures gated on the new config counts; add live decoy emitters to _emitters() + the
_feed_enemy_picture accrual; wire the reflector bias into the enemy back-plot feed (an EXTRA biased
BackPlotEntry near a planted reflector when a real launch crosses it). (3) world/combat_config.py — n_decoys +
n_corner_reflectors + CLAMPs + clamp_config + DEFAULT. (4) tests + tools/probe_decoys.py FIRST. Run all new
tests + the duel + full suite + smoke; PROVE the both-zero digest (incl. emitters + _back_plots + clusters) is
byte-identical to HEAD, the decoy is absent at 0 / HARM-able at >0, and NO commander decision code was touched.
Report measured numbers + the byte-identical proof. DEFER the map markers / emit toggle / HUD line (the sim+
world wiring is tested now). Commit. BLOCKED if honesty can't hold (any truth edit, miss flag, or commander
decision-logic change is a hard fail).`,
  { label: 'implement:M5-decoys', phase: 'Implement', schema: IMPL_SCHEMA }
)
log(`Implementer: ${impl ? impl.status : 'NULL'} — ${impl ? impl.measured : ''}`)
if (!impl || impl.status === 'BLOCKED' || impl.status === 'NEEDS_CONTEXT') {
  return { halted: true, stage: 'implement', impl }
}

phase('Spec review')
const specReview = await agent(
`SPEC-COMPLIANCE reviewer for M5 #5 ESM decoys + corner-reflectors. DO NOT TRUST THE IMPLEMENTER. Re-read spec
06 (the decoys feature) + the diff (git show), and RE-RUN the tests + tools/probe_decoys.py yourself. VERIFY:
 - BYTE-IDENTICAL DEFAULT: independently digest a same-seed multi-thousand-step run (incl. commander.picture
   emitters + _back_plots + clusters) at n_decoys=n_corner_reflectors=0 == pre-change HEAD; duel + smoke + full
   suite green; decoys absent from _emitters/ELINT/picture at 0.
 - HONESTY (the central contract): grep the diff for ANY commander decision-logic edit, any "decoy"/"miss"
   boolean the AI reads, or any truth read/write — there must be NONE. Confirm the decoy is heard via the SAME
   _emitters/_feed_enemy_picture path as the real radar, and the reflector bias is an added BackPlotEntry from a
   real geometry through the normal add_back_plot/back_plot_surface path (a SENSOR plant, not a flag).
 - DECOY EMITTER: emitting + real-radar-silent -> the enemy forms a located EmitterIntel on the DECOY id and
   _doctrine_blind schedules a HARM at target_id == the decoy; the decoy NEVER detects anything (empty ranges);
   a HARM kill marks its EmitterIntel dead via mark_emitter_destroyed.
 - CORNER-REFLECTOR: a planted reflector biases a real launch's back-plot so a LaunchCluster forms near the
   reflector (not the pad) and a commander salvo there finds no real structure within SEEKER_BASKET_M -> dirt.
 - DETERMINISM: tag [seed,10] only (no collision); no wall-clock. No test weakened.
Re-run: the new test files + tests/test_sm2_statistics.py + tests/test_combat_config.py + full suite + smoke.
${CONVENTIONS}
Implementer: ${impl.status}; measured=${impl.measured}; byteid=${impl.byte_identical_note}
PASS only if EVERY contract holds — especially byte-identical default + the HONESTY boundary (no AI edit, no
truth/miss flag) + the HARM-diversion / reflector-cluster behavior. Findings with file:line.`,
  { label: 'spec-review:M5-decoys', phase: 'Spec review', schema: REVIEW_SCHEMA }
)
log(`Spec review: ${specReview ? specReview.verdict : 'NULL'} (${specReview ? specReview.findings.length : 0}) — ${specReview ? specReview.reran_tests_output : ''}`)

if (specReview && specReview.verdict === 'FAIL' && specReview.findings.length) {
  phase('Spec fix')
  const fix = await agent(
`FIXER for M5 #5 decoys. Fix ALL findings without weakening tests or breaking: byte-identical default, the
HONESTY boundary (no AI decision edit / no truth or miss flag), the HARM-diversion + reflector-cluster behavior,
determinism. Re-run all decoy tests + the duel + test_combat_config + full suite + smoke + tools/probe_decoys.py. Commit.
${CONVENTIONS}
FINDINGS:
${specReview.findings.map((f, i) => `${i + 1}. [${f.severity}] ${f.file}:${f.line} — ${f.issue}\n   FIX: ${f.required_fix}`).join('\n')}`,
    { label: 'spec-fix:M5-decoys', phase: 'Spec fix', schema: IMPL_SCHEMA }
  )
  log(`Spec fix: ${fix ? fix.status : 'NULL'}`)
  const recheck = await agent(
`Re-verify M5 #5 decoys after the fixer: re-run all decoy test files + the duel + test_combat_config + full
suite + smoke + the probe. Confirm byte-identical default + the honesty boundary + HARM-diversion + reflector-
cluster. PASS/FAIL with counts.
${CONVENTIONS}`,
    { label: 'spec-recheck:M5-decoys', phase: 'Spec fix', schema: REVIEW_SCHEMA }
  )
  log(`Spec recheck: ${recheck ? recheck.verdict : 'NULL'}`)
  if (recheck && recheck.verdict === 'FAIL') return { halted: true, stage: 'spec-recheck', specReview, recheck }
}

phase('Quality review')
const qReview = await agent(
`CODE-QUALITY reviewer for M5 #5 decoys (spec passed). Judge whether it is WELL BUILT:
 - DecoyEmitter cleanly reuses the radar/emitter seam (no copy of the ELINT path); the reflector bias reuses the
   shared add_back_plot/back_plot_surface path (no duplicated back-projection);
 - the commander is genuinely UNCHANGED (the honesty boundary is structural, not just tested);
 - named, commented decoy constants (HP, influence radius, emit signature) — no magic numbers; no dead code;
 - tests verify measured behavior (HARM diverted, cluster biased, decoy detects-nothing, byte-identical) not
   tautologies;
 - the both-zero byte-identical gate + the no-truth/no-miss-flag honesty are structurally enforced.
Re-run the decoy tests + smoke. Findings with file:line.
${CONVENTIONS}`,
  { label: 'quality-review:M5-decoys', phase: 'Quality review', schema: REVIEW_SCHEMA }
)
log(`Quality review: ${qReview ? qReview.verdict : 'NULL'} (${qReview ? qReview.findings.length : 0})`)
if (qReview && qReview.verdict === 'FAIL' && qReview.findings.filter(f => f.severity !== 'MINOR').length) {
  phase('Quality fix')
  const qfix = await agent(
`FIXER for M5 #5 decoys code-quality findings. Fix BLOCKER/MAJOR (MINOR where cheap) without changing behavior
or weakening tests. Re-run the decoy tests + smoke. Commit.
${CONVENTIONS}
FINDINGS:
${qReview.findings.map((f, i) => `${i + 1}. [${f.severity}] ${f.file}:${f.line} — ${f.issue}\n   FIX: ${f.required_fix}`).join('\n')}`,
    { label: 'quality-fix:M5-decoys', phase: 'Quality fix', schema: IMPL_SCHEMA }
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
