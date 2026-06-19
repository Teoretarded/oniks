export const meta = {
  name: 'm5-backplot-helper',
  description: 'M5 #2: EXTRACT a shared back_plot_surface() helper (BIT-IDENTICAL refactor, unblocks CBR/scoot/decoys) + a CONSERVATIVE, MEASURED, still-WINNABLE back-plot reliability buff on the enemy commander (its only base-kill path). Two commits: bit-identical extract, then the flagged buff. implementer -> spec review -> fix -> quality review -> fix',
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
  Commit per TASK with a conventional message; NEVER touch git main. Branch: feat/combat-expansion.
THIS FEATURE HAS TWO SEPARABLE TASKS — COMMIT THEM SEPARATELY in this order:
 TASK A (THE EXTRACT — BIT-IDENTICAL, ZERO BALANCE RISK): factor the launch-point back-projection out of
   sim/commander.CommanderBrain.process_missile_track (the climb-branch time-to-surface AND the level-skimmer
   coast-intersection, ~lines 1386-1416) into a PURE, module-level helper:
     back_plot_surface(first_pos, first_vel, *, coast_z=HOME_COAST_Z, climb_vy=BACKPLOT_CLIMB_VY,
                       min_close_vz=BACKPLOT_MIN_CLOSE_VZ) -> tuple[float,float] | None
   process_missile_track then CALLS it (no behavior change). This is the DRY/symmetry seam the player CBR
   (#3) and the corner-reflector decoys (#5) will reuse — so the SAME math runs on both sides.
   THE GATE: process_missile_track stays BIT-IDENTICAL. Prove it TWO ways: (1) a parametrized digest test
   feeding many synthetic (first_pos, first_vel) tracks (climb, level-closing, level-receding, coast-parallel,
   already-at-surface, the degenerate vz<=min_close_vz and dz<=0 rejections) through BOTH the pre-refactor
   inline path (capture expected outputs from git HEAD first) and the new helper -> identical; (2) a 3000-step
   seed-1337 DEFAULT-battle state digest == the pre-change HEAD digest (the extract changes NO observable sim
   state). Commit TASK A on its own ("refactor(combat): extract back_plot_surface() helper, bit-identical").
 TASK B (THE RELIABILITY BUFF — MEASURED, CONSERVATIVE, STILL-WINNABLE, FLAGGED): the enemy launch-site
   back-plot is the enemy's ONLY base-kill path (it back-plots a player Oniks/SAM launch, clusters >=3 fixes
   within BACKPLOT_CLUSTER_R_M, then fires TLAM/JASSM at the cluster centroid). GAME_ANALYSIS §5 + spec 06
   flag it as "too timid" — it mis-projects a sea-skimmer so clusters rarely form. Buff its RELIABILITY so
   scoot/decoy/CBR have something to act on — but it is BALANCE-CRITICAL: do NOT make the game unwinnable.
 NON-NEGOTIABLES:
  - MEASURE FIRST, NEVER GUESS: write tools/probe_backplot_reliability.py BEFORE touching the model. It must
    QUANTIFY the current behavior on the REAL world: fire a representative lo-lo (sea-skim) Oniks salvo from
    the real Bastion pad in a real CombatWorld, step it, and print: does a LaunchCluster form? after how many
    launches? the centroid error vs the TRUE pad XZ (m)? the per-fix back-projection error? Also measure a
    DOGLEG/coast-parallel launch (should NOT localize) and a SCOOT (relocated pad — N/A yet, so simulate by
    firing from a 2nd pad). Print BEFORE numbers; apply the buff; print AFTER numbers in the same probe.
  - CONSERVATIVE + PHYSICS-NOT-DICE: the buff is a BETTER GEOMETRIC ESTIMATE or a slightly wider eligibility
    window (e.g. correct the level-skimmer coast-intersection to the believed launch latitude instead of a
    hard z=coast_z that biases a deep-pad launch; or a small, justified widening of BACKPLOT_LOW_ALT_M /
    BACKPLOT_MAX_AGE_S / BACKPLOT_CLUSTER_R_M), NEVER a probability/fudge. Every changed constant is a NAMED
    module constant with a comment citing the measured number that drove it. Keep an ERROR FLOOR (the
    back-plot is a CUE with uncertainty, never a truth-snipe) — error_m must stay >= det_range*BACKPLOT_ERR_FRAC.
  - STILL-WINNABLE (THE HARD GATE): lock a TWO-SIDED regression: (a) a representative straight sea-skim leak
    now RELIABLY forms a cluster (centroid error below a measured bound) — the buff works; AND (b) a player
    who DOGLEGS (coast-parallel/receding) or fires from a DIFFERENT pad still DEFEATS localization (no cluster,
    or the cluster sits at the stale/wrong XZ so a salvo there hits dirt via _refine_strike_aim) — the game
    stays winnable. If you CANNOT achieve BOTH conservatively, ship ONLY Task A and report the buff BLOCKED
    with the measured reason (do NOT ship an unwinnable or trivially-localizing change).
  - DUEL BIT-IDENTICAL: the Oniks-vs-SM-2 duel (tests/test_sm2_statistics.py) touches NONE of the back-plot
    path and MUST stay bit-identical after BOTH tasks. The default-battle digest WILL change after Task B
    (the buff intentionally alters commander behavior) — that is the ONE allowed, documented exception; it is
    NOT byte-identical and you must NOT pretend it is. Capture the new default-battle digest and pin it so it
    is itself reproducible/deterministic.
  - FOG / NO CHEAT: process_missile_track + the helper read ONLY the sensor track (first_seen pos/vel/detector
    pos) — NEVER the launching missile's truth pos. The buff must not smuggle in a truth read. Determinism
    preserved (no RNG added; if any, a fresh tag — but a geometric estimate needs none).
  - FLAG LOUDLY: Task B changes the default battle's difficulty (the enemy localizes launches more reliably).
    Document the measured before/after (cluster-formation rate + centroid error + the dogleg/scoot escape) in
    the commit body AND append a dated entry to docs/combat_build_log.md marked "BALANCE — needs the user's
    hands-on playtest (memory: enemy-lethality-backplot, playtest-before-polish)".
 STATUS: DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT. Never weaken a test. Bad work is worse than no work.`

const ANCHORS = `
VERIFIED ANCHORS (read before coding):
 - sim/commander.py constants ~151-171: BACKPLOT_LOW_ALT_M=2000, BACKPLOT_MAX_AGE_S=30, BACKPLOT_ERR_FRAC=0.02,
   BACKPLOT_CLUSTER_R_M=3000, BACKPLOT_FIXES_NEEDED=3, HOME_COAST_Z=0.0, BACKPLOT_CLIMB_VY=50.0,
   BACKPLOT_MIN_CLOSE_VZ=50.0.
 - sim/commander.py process_missile_track ~1310-1423: the eligibility gate (alt<LOW_ALT, age<MAX_AGE,
   once-per-track) + the two-regime back-projection (climb: t_back=fy/vy; level: coast-intersection at
   HOME_COAST_Z, rejecting vz<=MIN_CLOSE_VZ or dz<=0) + error_m=det_range*ERR_FRAC + add_back_plot. The
   back-projection block (~1386-1416) is what TASK A extracts VERBATIM into back_plot_surface().
 - sim/commander.py add_back_plot ~389 + _update_clusters ~406 + LaunchCluster ~289 (targetable once
   FIXES_NEEDED distinct track_ids cluster within CLUSTER_R_M) + prune_missile_tracks ~511 (already bounds
   _back_plots — confirm; the spec's "unpruned raw list" appears already addressed, so DO NOT re-fix it
   unless the probe shows otherwise). targetable_clusters() ~439.
 - world/combat.py: the path that FEEDS process_missile_track each step (search "process_missile_track" — it
   is called from the world's commander feed with the enemy-radar track store) and _doctrine_kill firing
   TOMAHAWK_SALVO at the cluster centroid (sim/commander.py ~1136) + _refine_strike_aim (world/combat.py
   ~1852) which finds no structure within SEEKER_BASKET_M of an empty/stale pad -> a clean physics miss.
 - BASE_POS (world/generation.py) is the true Bastion pad XZ (z ~ -600, SOUTH of HOME_COAST_Z=0) — the deep
   pad vs the hard coast_z=0 intersection is the likely source of the measured level-skimmer bias; the probe
   must quantify this exact error before any change.
 - tools/compare_s300_rounds.py / tools/probe_*.py — the probe idiom (print measured numbers, no asserts).
   Mirror it for tools/probe_backplot_reliability.py.`

const TEST_CONTRACTS = `
TDD. Write tools/probe_backplot_reliability.py + the test files FIRST.
 TASK A (tests/test_backplot_helper.py): back_plot_surface is PURE + module-level; a parametrized table of
   synthetic tracks (climb-near-launch, level-closing, level-receding -> None, coast-parallel vz<=MIN_CLOSE_VZ
   -> None, dz<=0 -> None, already-at-surface) returns EXACTLY what the pre-refactor inline math returned
   (expected values captured from HEAD); process_missile_track delegates to it and a multi-track digest of its
   add_back_plot outputs is bit-identical to the pre-refactor digest; the 3000-step default-battle digest ==
   pre-change HEAD. NO behavior change in Task A.
 TASK B (tests/test_backplot_reliability.py), all two-sided + measured:
  - RELIABLE: a representative straight lo-lo sea-skim Oniks leak forms a targetable LaunchCluster within
    BACKPLOT_FIXES_NEEDED launches AND the centroid error vs the true pad is < the measured RELIABLE bound
    (the buff works — clusters now form where they were too timid before);
  - STILL-WINNABLE (the hard gate): a DOGLEG (coast-parallel/receding) launch yields NO localizable fix (or a
    fix whose error is so large no cluster forms), AND a salvo aimed at a STALE/empty pad finds no structure
    within SEEKER_BASKET_M (hits dirt) — the player can still defeat the back-plot;
  - ERROR FLOOR: error_m stays >= det_range*BACKPLOT_ERR_FRAC (no truth-snipe);
  - NO-TRUTH: the estimate uses only first_seen pos/vel/detector (assert it ignores the live missile pos);
  - DETERMINISM: identical inputs -> identical estimate; the new default-battle digest is itself reproducible.
 REGRESSION (both tasks): tests/test_sm2_statistics.py bit-identical; full suite + smoke green; the EXISTING
   commander/back-plot tests (tests/test_commander*.py / tests/test_backplot*.py if present) stay green or are
   updated ONLY to the new measured numbers WITH the reason in the commit (never weakened silently).`

const IMPL_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['status', 'task_a', 'task_b', 'files_changed', 'tests_added', 'measured', 'winnable_note', 'concerns'],
  properties: {
    status: { type: 'string', enum: ['DONE', 'DONE_WITH_CONCERNS', 'BLOCKED', 'NEEDS_CONTEXT'] },
    task_a: { type: 'string', description: 'Extract result + the bit-identical proof (helper digest == HEAD; default-battle 3000-step digest == HEAD). Commit sha/message.' },
    task_b: { type: 'string', description: 'Buff result: SHIPPED or BLOCKED; what constant(s)/geometry changed and the measured number that drove each; commit sha/message — OR the measured reason it was not shippable conservatively.' },
    files_changed: { type: 'array', items: { type: 'string' } },
    tests_added: { type: 'array', items: { type: 'string' } },
    measured: { type: 'string', description: 'Probe BEFORE/AFTER: sea-skim cluster-formation (forms? after N launches? centroid error m), dogleg (localized? error m), error floor, duel bit-identical, full suite + smoke counts.' },
    winnable_note: { type: 'string', description: 'The two-sided proof the game stays winnable: the reliable-leak bound AND the dogleg/stale-pad escape, with numbers. If Task B BLOCKED, why.' },
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
`You are the IMPLEMENTER for M5 #2 — the shared back_plot_surface() helper (a BIT-IDENTICAL extract) plus a
CONSERVATIVE, MEASURED, still-WINNABLE reliability buff on the enemy commander's launch-site back-plot (its
ONLY base-kill path). Do TASK A then TASK B, committing each separately. MEASURE with a probe before the buff;
keep the game winnable (the hard gate); never guess a constant.
${CONVENTIONS}
${ANCHORS}
${TEST_CONTRACTS}
Plan: (A) capture the pre-refactor expected back-projection outputs + the 3000-step default-battle digest from
git HEAD; extract back_plot_surface(); rewire process_missile_track to call it; prove bit-identical both ways;
commit. (B) write tools/probe_backplot_reliability.py and PRINT the current sea-skim cluster-formation +
centroid error + the deep-pad-vs-coast_z bias + a dogleg case; make the smallest CONSERVATIVE geometric/window
improvement that makes a straight leak reliably cluster while a dogleg/stale pad still escapes; lock the
two-sided tests; re-run the duel + full suite + smoke; capture + pin the new default-battle digest; FLAG the
balance change in the commit body + docs/combat_build_log.md. If the buff cannot be both reliable AND winnable
conservatively, SHIP ONLY TASK A and report Task B BLOCKED with the measured reason. Report measured
before/after + the winnability proof.`,
  { label: 'implement:M5-backplot', phase: 'Implement', schema: IMPL_SCHEMA }
)
log(`Implementer: ${impl ? impl.status : 'NULL'} — A:${impl ? impl.task_a : ''} | B:${impl ? impl.task_b : ''}`)
if (!impl || impl.status === 'BLOCKED' || impl.status === 'NEEDS_CONTEXT') {
  return { halted: true, stage: 'implement', impl }
}

phase('Spec review')
const specReview = await agent(
`SPEC-COMPLIANCE reviewer for M5 #2 back-plot helper + reliability buff. DO NOT TRUST THE IMPLEMENTER. Re-read
spec 06 (the back-plot dependency section) + GAME_ANALYSIS §5 if present + the diff (git show both commits) and
RE-RUN tests + tools/probe_backplot_reliability.py yourself. VERIFY:
 - TASK A BIT-IDENTICAL: independently confirm process_missile_track is unchanged in behavior — the helper
   returns the SAME values the old inline math did across the synthetic table; the 3000-step default-battle
   digest at the TASK-A commit == pre-change HEAD. back_plot_surface is pure + module-level + has NO truth read.
 - TASK B CONSERVATIVE + MEASURED: every changed constant is named + commented + justified by a probe number;
   physics-not-dice (a better geometric estimate / wider window, NOT a roll or fudge); the error floor
   (>= det_range*BACKPLOT_ERR_FRAC) holds; no truth leak.
 - STILL-WINNABLE (the hard gate): re-run the two-sided tests — a straight sea-skim leak RELIABLY clusters AND
   a dogleg/stale-pad launch still ESCAPES localization. If the buff makes localization trivial/instant or the
   dogleg no longer escapes, that is a BLOCKER.
 - DUEL bit-identical (tests/test_sm2_statistics.py); the new default-battle digest is reproducible; no test
   weakened silently (any updated commander/back-plot test changed only TO a measured number, argued in the commit).
 - FLAGGED: the balance change is documented in the commit body + docs/combat_build_log.md.
Re-run: the new test files + tests/test_sm2_statistics.py + any existing commander/back-plot tests + full suite + smoke.
${CONVENTIONS}
Implementer: ${impl.status}; A=${impl.task_a}; B=${impl.task_b}; measured=${impl.measured}; winnable=${impl.winnable_note}
PASS only if Task A is provably bit-identical AND (Task B is conservative + reliable + still-winnable OR was
correctly BLOCKED and only Task A shipped). Findings with file:line.`,
  { label: 'spec-review:M5-backplot', phase: 'Spec review', schema: REVIEW_SCHEMA }
)
log(`Spec review: ${specReview ? specReview.verdict : 'NULL'} (${specReview ? specReview.findings.length : 0}) — ${specReview ? specReview.reran_tests_output : ''}`)

if (specReview && specReview.verdict === 'FAIL' && specReview.findings.length) {
  phase('Spec fix')
  const fix = await agent(
`FIXER for M5 #2 back-plot. Fix ALL findings without weakening tests or breaking: Task-A bit-identicality, the
duel, physics-not-dice, no-truth, the error floor, and the STILL-WINNABLE two-sided gate. If a finding shows
the buff is not conservatively winnable, REVERT Task B to extract-only and report it. Re-run the new tests +
duel + full suite + smoke + the probe. Commit.
${CONVENTIONS}
FINDINGS:
${specReview.findings.map((f, i) => `${i + 1}. [${f.severity}] ${f.file}:${f.line} — ${f.issue}\n   FIX: ${f.required_fix}`).join('\n')}`,
    { label: 'spec-fix:M5-backplot', phase: 'Spec fix', schema: IMPL_SCHEMA }
  )
  log(`Spec fix: ${fix ? fix.status : 'NULL'}`)
  const recheck = await agent(
`Re-verify M5 #2 after the fixer: re-run the back-plot test files + the duel + full suite + smoke + the probe.
Confirm Task-A bit-identical + (Task-B reliable AND still-winnable, or correctly extract-only). PASS/FAIL with counts.
${CONVENTIONS}`,
    { label: 'spec-recheck:M5-backplot', phase: 'Spec fix', schema: REVIEW_SCHEMA }
  )
  log(`Spec recheck: ${recheck ? recheck.verdict : 'NULL'}`)
  if (recheck && recheck.verdict === 'FAIL') return { halted: true, stage: 'spec-recheck', specReview, recheck }
}

phase('Quality review')
const qReview = await agent(
`CODE-QUALITY reviewer for M5 #2 back-plot (spec passed). Judge whether it is WELL BUILT:
 - back_plot_surface is a clean, single-responsibility pure helper with NO duplication left in
   process_missile_track (the two-regime math lives in ONE place now); both sides will call the SAME helper;
 - the buff's changed constants are NAMED + commented with the driving measured number; no magic numbers;
 - no dead code; the probe is a real measurement (prints numbers), the tests verify measured behavior (cluster
   formation, centroid error, dogleg escape) not tautologies;
 - the still-winnable property is structurally clear (the dogleg/stale-pad escape is geometric, not a special-case);
 - the balance change is documented.
Re-run the back-plot tests + smoke. Findings with file:line.
${CONVENTIONS}`,
  { label: 'quality-review:M5-backplot', phase: 'Quality review', schema: REVIEW_SCHEMA }
)
log(`Quality review: ${qReview ? qReview.verdict : 'NULL'} (${qReview ? qReview.findings.length : 0})`)
if (qReview && qReview.verdict === 'FAIL' && qReview.findings.filter(f => f.severity !== 'MINOR').length) {
  phase('Quality fix')
  const qfix = await agent(
`FIXER for M5 #2 back-plot code-quality findings. Fix BLOCKER/MAJOR (MINOR where cheap) without changing
behavior or weakening tests. Re-run the back-plot tests + smoke. Commit.
${CONVENTIONS}
FINDINGS:
${qReview.findings.map((f, i) => `${i + 1}. [${f.severity}] ${f.file}:${f.line} — ${f.issue}\n   FIX: ${f.required_fix}`).join('\n')}`,
    { label: 'quality-fix:M5-backplot', phase: 'Quality fix', schema: IMPL_SCHEMA }
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
