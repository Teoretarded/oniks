// Generic M6 per-feature TDD + adversarial-review pipeline, parameterized via `args`.
// Invoke once per M6 meta-loop feature (status panel / salvo / auto-time-warp /
// scoring / campaign).  Runaway-proof: every agent uses -n auto + TARGETED tests
// (NEVER the ~22-min serial suite); the full suite is the orchestrator's gate only.
export const meta = {
  name: 'm6-feature',
  description: 'Generic M6 per-feature pipeline: TDD implementer -> spec-compliance review (re-runs targeted tests, proves byte-identical default + fog/no-cheat + determinism, distrusts the implementer) -> fixer -> code-quality review -> fixer. Parameterized via args {id,title,brief,files,anchors,contracts,testCmd}.',
  phases: [
    { title: 'Implement' },
    { title: 'Spec review' },
    { title: 'Spec fix' },
    { title: 'Quality review' },
    { title: 'Quality fix' },
  ],
}

let F = args || {}
if (typeof F === 'string') { try { F = JSON.parse(F) } catch (e) { F = {} } }
const ID = F.id || 'm6-feature'
const TITLE = F.title || 'an M6 feature'
const TESTCMD = F.testCmd || 'python -m pytest -q -n auto <feature test files> tests/test_sm2_statistics.py'

const CONVENTIONS = `
ENV: Python 3.11, cwd = repo root "C:\\\\Users\\\\teoti\\\\OneDrive\\\\Desktop\\\\New folder\\\\oinks PROTO".
  TEST RUNNER: pytest-xdist IS installed (16 cores). ALWAYS pass -n auto. NEVER run the suite serial
   (serial ~22 min; heavy real-world-sim tests in test_relocate.py/test_kalibr_salvo.py dominate the tail).
  FAST iteration (you + fixers): run ONLY the targeted files —
     ${TESTCMD}
   + python tools/smoke_combat.py (expect 70/70 exit 0) + the byte-identical digest. (~2-4 min)
  FULL regression (spec-compliance reviewer ONLY): python -m pytest -q -n auto  (~13 min, must be all-green).
  Commit per task with a conventional message; NEVER touch git main. Branch: feat/combat-expansion.
NON-NEGOTIABLES (project contracts — hold for EVERY M6 feature):
 - LOCKED CombatConfig schema: do NOT add a new frozen CombatConfig field. Campaign state rides a SEPARATE
   carrier (battle_idx + an optional initial_state ingest applied AFTER _arm_magazines), NEVER new schema fields.
 - BYTE-IDENTICAL DEFAULT: every new default path (salvo idle, auto-warp OFF, scorecard None, initial_state=None,
   battle_idx=0) MUST keep the default battle BIT-IDENTICAL. PROVE: the same-seed multi-thousand-step digest
   (python tools/wf_m5_digest.py) == pre-change HEAD, AND the Oniks-vs-SM-2 duel (tests/test_sm2_statistics.py)
   bit-identical. (Use git stash of your tracked edits to capture the HEAD digest, then pop.)
 - FOG / NO-CHEAT: triggers/scores/schedules read ONLY player-side sensor state — world.contacts.tracks,
   world._strike_board, and world.commander.picture (the enemy BELIEF, already sensor-derived). NEVER read
   world.missiles ENEMY truth for a fog-gated decision. The auto-warp inbound-drop + scoring first-fix MUST be
   fog-safe: an UNDETECTED hostile (in world.missiles, is_hostile, absent from _strike_board/contacts.tracks)
   must NOT trigger. End-of-battle kill tallies MAY read truth (after-action report). The enemy commander
   decision logic is NEVER modified.
 - PHYSICS NOT DICE + DETERMINISM: no new outcome rolls. Salvo reuses the existing per-tube launch; FAN offsets
   are a SEEDED deterministic child stream. For campaign per-battle seeding use derive_seed(seed, battle_idx)
   (RECOMMENDED — leaves existing [seed, tag] child streams untouched; battle_idx=0 collapses to today). No
   wall-clock in sim/world (warp must be a pure multiplier on accumulated sim time; commander is scale-invariant).
 - PURE LOGIC IS TESTABLE HEADLESS: put new logic in PURE GL-free modules / module-level helpers with NO
   top-level display calls — the suite imports game/* fine headless (1325 tests pass). Validate GL draw methods
   + input wiring via tools/smoke_combat.py; cover pure logic with a FakeText / fake-world harness (established:
   tests/test_threat_strip.py, test_tube_panel.py, test_controls.py, test_timewarp-style).
 - REGRESSION NEVER WEAKENED: if a planned test can't pass honestly, report BLOCKED — never widen a tolerance or
   delete a case. Updating a shared table when truth genuinely changed is allowed (e.g. test_keybinds default
   table + the F1 overlay_rows count in test_hud when you ADD a keybind) — that is a truth update, not a weakening.
 STATUS: DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT. Bad work is worse than no work — escalate, don't guess.`

const SPECREF = `
SPEC + CONTEXT (read before coding): docs/research/handoff/07_campaign_scoring_auto_time_warp_salvo_ke.md (this
feature's section), docs/research/handoff/ROADMAP.md (M6), docs/combat_build_log.md (recent entries, conventions).
FEATURE: ${TITLE}.
WHAT TO BUILD: ${F.brief || '(see the spec section)'}
FILES (reuse, don't rewrite): ${F.files || '(see the spec)'}
VERIFIED ANCHORS: ${F.anchors || '(grep the named symbols before editing)'}
TEST CONTRACTS (write the tests FIRST, TDD): ${F.contracts || '(see the spec test contracts)'}`

const IMPL_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['status', 'files_changed', 'tests_added', 'measured', 'byte_identical_note', 'concerns'],
  properties: {
    status: { type: 'string', enum: ['DONE', 'DONE_WITH_CONCERNS', 'BLOCKED', 'NEEDS_CONTEXT'] },
    files_changed: { type: 'array', items: { type: 'string' } },
    tests_added: { type: 'array', items: { type: 'string' } },
    measured: { type: 'string', description: 'Targeted test counts + smoke + the key measured behavior of the feature.' },
    byte_identical_note: { type: 'string', description: 'Proof the default path is bit-identical: the digest == HEAD + duel bit-identical; what the new default-OFF gate is.' },
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
`You are the IMPLEMENTER for M6 feature "${TITLE}". Build it TDD: write the targeted test files FIRST (red),
then the implementation, then make them green. Keep new logic PURE/GL-free so it is headless-testable. Prove the
byte-identical default + run smoke. Report measured numbers + the byte-identical proof. Commit with a conventional
message. BLOCKED if a contract can't hold honestly (any fog leak, truth read for a gated decision, new frozen
config field, or determinism break is a hard fail).
${CONVENTIONS}
${SPECREF}`,
  { label: `implement:${ID}`, phase: 'Implement', schema: IMPL_SCHEMA }
)
log(`Implementer: ${impl ? impl.status : 'NULL'} — ${impl ? impl.measured : ''}`)
if (!impl || impl.status === 'BLOCKED' || impl.status === 'NEEDS_CONTEXT') {
  return { halted: true, stage: 'implement', impl }
}

phase('Spec review')
const specReview = await agent(
`SPEC-COMPLIANCE reviewer for M6 "${TITLE}". DO NOT TRUST THE IMPLEMENTER. Re-read the spec section + the diff
(git show / git diff), and RE-RUN the targeted tests + the FULL suite (python -m pytest -q -n auto) yourself.
VERIFY with file:line evidence:
 - BYTE-IDENTICAL DEFAULT: independently capture the same-seed digest at the default path (git stash the tracked
   edits -> python tools/wf_m5_digest.py -> pop) == HEAD; duel bit-identical; smoke 70/70; FULL suite green.
 - FOG / NO-CHEAT: grep the diff for any read of world.missiles (or enemy truth) feeding a fog-gated decision;
   confirm triggers/scores read only contacts.tracks / _strike_board / commander.picture. The undetected-hostile
   fog test must exist and pass. The enemy commander decision logic is UNCHANGED (git diff sim/commander.py).
 - DETERMINISM: derive_seed / battle_idx=0 collapses to today; no wall-clock; FAN/seeded streams reproducible.
 - NO LOCKED-SCHEMA VIOLATION: no new frozen CombatConfig field; campaign rides battle_idx + initial_state.
 - TESTS verify measured behavior, not tautologies; no weakened tolerance; shared tables updated correctly.
${CONVENTIONS}
Implementer: ${impl.status}; measured=${impl.measured}; byteid=${impl.byte_identical_note}
PASS only if EVERY contract holds. Findings with file:line + a concrete required fix.`,
  { label: `spec-review:${ID}`, phase: 'Spec review', schema: REVIEW_SCHEMA }
)
log(`Spec review: ${specReview ? specReview.verdict : 'NULL'} (${specReview ? specReview.findings.length : 0})`)

if (specReview && specReview.verdict === 'FAIL' && specReview.findings.length) {
  phase('Spec fix')
  const fix = await agent(
`FIXER for M6 "${TITLE}". Fix ALL findings WITHOUT weakening tests or breaking byte-identical default / fog-no-cheat
/ determinism / the locked schema. Re-run the targeted tests + duel + smoke + the digest. Commit.
${CONVENTIONS}
FINDINGS:
${specReview.findings.map((f, i) => `${i + 1}. [${f.severity}] ${f.file}:${f.line} — ${f.issue}\n   FIX: ${f.required_fix}`).join('\n')}`,
    { label: `spec-fix:${ID}`, phase: 'Spec fix', schema: IMPL_SCHEMA }
  )
  log(`Spec fix: ${fix ? fix.status : 'NULL'}`)
  const recheck = await agent(
`Re-verify M6 "${TITLE}" after the fixer: re-run the targeted tests + duel + smoke + the digest + a FULL
-n auto suite. Confirm byte-identical default + fog/no-cheat + determinism + no locked-schema violation. PASS/FAIL
with counts.
${CONVENTIONS}`,
    { label: `spec-recheck:${ID}`, phase: 'Spec fix', schema: REVIEW_SCHEMA }
  )
  log(`Spec recheck: ${recheck ? recheck.verdict : 'NULL'}`)
  if (recheck && recheck.verdict === 'FAIL') return { halted: true, stage: 'spec-recheck', specReview, recheck }
}

phase('Quality review')
const qReview = await agent(
`CODE-QUALITY reviewer for M6 "${TITLE}" (spec passed). Judge whether it is WELL BUILT: genuine reuse of the
existing launch/time-scale/magazine/picture seams (no copy-paste); pure logic cleanly separated from GL; named,
commented tuning constants (no magic numbers); no dead code; tests verify measured behavior not tautologies;
the byte-identical default + fog boundary are STRUCTURALLY enforced (not just tested). Re-run the targeted tests
+ smoke. Findings with file:line.
${CONVENTIONS}`,
  { label: `quality-review:${ID}`, phase: 'Quality review', schema: REVIEW_SCHEMA }
)
log(`Quality review: ${qReview ? qReview.verdict : 'NULL'} (${qReview ? qReview.findings.length : 0})`)
if (qReview && qReview.verdict === 'FAIL' && qReview.findings.filter(f => f.severity !== 'MINOR').length) {
  phase('Quality fix')
  const qfix = await agent(
`FIXER for M6 "${TITLE}" code-quality findings. Fix BLOCKER/MAJOR (MINOR where cheap) WITHOUT changing behavior or
weakening tests. Re-run the targeted tests + smoke. Commit.
${CONVENTIONS}
FINDINGS:
${qReview.findings.map((f, i) => `${i + 1}. [${f.severity}] ${f.file}:${f.line} — ${f.issue}\n   FIX: ${f.required_fix}`).join('\n')}`,
    { label: `quality-fix:${ID}`, phase: 'Quality fix', schema: IMPL_SCHEMA }
  )
  log(`Quality fix: ${qfix ? qfix.status : 'NULL'}`)
}

return {
  done: true, id: ID, implementer: impl,
  spec_verdict: specReview ? specReview.verdict : null,
  quality_verdict: qReview ? qReview.verdict : null,
  spec_findings: specReview ? specReview.findings : [],
  quality_findings: qReview ? qReview.findings : [],
}
