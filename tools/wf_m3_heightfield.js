export const meta = {
  name: 'm3-heightfield-refactor',
  description: 'M3-terrain F3: HeightField class wrapping the terrain field + field-routed LOS, BIT-IDENTICAL on the default map. implementer -> spec review -> fix -> quality review -> fix',
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
  Full suite: python -m pytest -q  (~6 min). Targeted: python -m pytest tests/test_heightfield.py tests/test_generation.py tests/test_radar.py -q
  Smoke gate (MUST stay 70/70 exit 0): python tools/smoke_combat.py
THE ONE CONTRACT THAT MATTERS HERE — BIT-IDENTICAL DEFAULT:
  This is a PURE REFACTOR. The default map must behave EXACTLY as today, byte-for-byte, for
  sensors AND missiles AND determinism. The way to guarantee it: the HeightField methods must
  execute the IDENTICAL arithmetic in the IDENTICAL order as the current module functions —
  literally MOVE the function bodies into methods, bind the module constants to self, and change
  NOTHING about the math. Any float reordering can drift a last bit and fail the gate. If you
  cannot keep it bit-identical, STOP and report BLOCKED — do NOT weaken any test.
  NEVER modify an existing test. The existing tests/test_generation.py must pass UNCHANGED.
OTHER NON-NEGOTIABLES: determinism (no new RNG here), fog/no-cheat (player AND enemy must read LOS
  through the SAME field instance — no asymmetry, no truth leak). STATUS PROTOCOL: end with exactly
  one of DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT. Bad work is worse than no work.
SCOPE GUARD: do NOT change terrain_blocks' SAMPLING (the LOS_STEP_M loop) in this task — a separate
  follow-up handles that behavior fix. Here terrain_blocks is REUSED UNCHANGED; you only add the
  height_fn plumbing. Do NOT add height detail to the default field. Do NOT touch CombatConfig.`

const ANCHORS = `
VERIFIED ANCHORS (read these first):
 - world/generation.py: TERRAIN_MAX_HEIGHT=430.0 @28; terrain_height(x,z) vectorized @122;
   is_land @178; terrain_height_scalar(x,z) scalar fast path @255; surface_height_scalar @310.
   These functions close over module constants (SEED, ISLANDS, ENEMY_COAST_Z, coast/cliff/shelf
   tuning). The refactor: define a HeightField class whose __init__ binds those constants to self
   and whose methods height(x,z) / height_scalar(x,z) / surface_scalar(x,z) hold the EXACT current
   bodies; add self.max_height (=430.0 default). Then DEFAULT_FIELD = HeightField() at module level,
   and the existing module functions terrain_height / terrain_height_scalar / surface_height_scalar
   / is_land become THIN SHIMS delegating to DEFAULT_FIELD (so every existing import keeps working
   byte-for-byte and the bit-identical gate is trivially met). Keep TERRAIN_MAX_HEIGHT=430.0 as the
   module constant too (sim files import it directly; leave those imports untouched in THIS task —
   per-field max plumbing is the presets task's job, the default field's max IS 430).
 - sim/radar.py: terrain_blocks(a, b, height_fn=terrain_height_scalar) @34 — REUSE UNCHANGED.
   Radar.__init__ @55 + Radar.detects @67 call terrain_blocks with the DEFAULT height_fn. ADD an
   optional height_fn arg to Radar.__init__ (default = the module shim terrain_height_scalar, so
   existing callers are byte-identical) stored on self, and pass it in detects -> terrain_blocks.
 - sim/recon.py ALREADY accepts height_fn (ElintReceiver/SarSensor/ReconDrone, @280/609/969,
   default terrain_height_scalar). No signature change needed there — just thread the field in from
   world/combat.py if it isn't already.
 - world/combat.py: build the active field ONCE in __init__ (for the default map: field =
   generation.DEFAULT_FIELD, or HeightField() — same thing), store self.height_field, and thread
   field.height_scalar as the height_fn to every Radar / SAM / recon / aircraft / enemy-air
   construction site so PLAYER and ENEMY read the SAME field. (Grep the constructors; some already
   default to the module shim, which for the default field is identical — but thread explicitly so
   a future preset swaps everywhere at once.)
 - TERRAIN_MAX_HEIGHT consumers (leave their imports as-is this task): sim/aircraft.py:21,156;
   sim/enemy_air.py:954,966,1557,1569; sim/missile.py:24,757; sim/recon.py:564,582.`

const TEST_CONTRACTS = `
WRITE tests/test_heightfield.py FIRST (TDD), then refactor until green:
 (a) BIT-IDENTICAL default: for a large fixed grid of (x,z) (e.g. a few hundred points spanning the
     map incl. base/SAM/island coords), HeightField().height(X,Z) == terrain_height(X,Z) EXACTLY
     (no float drift, use ==), .height_scalar(x,z) == terrain_height_scalar(x,z), .surface_scalar
     == surface_height_scalar. ALL existing tests/test_generation.py pass UNCHANGED.
 (b) SHIM identity: the module terrain_height/terrain_height_scalar/surface_height_scalar return
     identically to DEFAULT_FIELD's methods for the grid.
 (c) LOS routing: terrain_blocks(a, b, height_fn=field.height_scalar) == terrain_blocks(a, b)
     (default) for the default field over a fixed sensor/target grid.
 (d) SYMMETRY / no-cheat: in a built CombatWorld, assert every Radar / SAM / recon object's
     height_fn IS the same callable as the world's field.height_scalar (player AND enemy) — no side
     reads a different field. (If a constructor stores it under a private name, assert via that.)
 (e) max_height: HeightField().max_height == 430.0 and a flyer above it still skips ground queries
     identically (the sim/missile.py / sim/enemy_air.py optimization result is unchanged).
 (f) Full combat regression: python -m pytest -q green + python tools/smoke_combat.py 70/70 exit 0.`

const IMPL_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['status', 'files_changed', 'tests_added', 'bit_identical_evidence', 'concerns'],
  properties: {
    status: { type: 'string', enum: ['DONE', 'DONE_WITH_CONCERNS', 'BLOCKED', 'NEEDS_CONTEXT'] },
    files_changed: { type: 'array', items: { type: 'string' } },
    tests_added: { type: 'array', items: { type: 'string' } },
    bit_identical_evidence: { type: 'string', description: 'The exact grid-equality + full-suite + smoke results proving the default map is byte-identical.' },
    concerns: { type: 'string' },
  },
}
const REVIEW_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['verdict', 'reran_tests_output', 'findings'],
  properties: {
    verdict: { type: 'string', enum: ['PASS', 'FAIL'] },
    reran_tests_output: { type: 'string', description: 'Real counts from RE-RUNNING the heightfield + generation + radar tests + smoke yourself.' },
    findings: { type: 'array', items: { type: 'object', additionalProperties: false,
      required: ['severity', 'file', 'line', 'issue', 'required_fix'],
      properties: {
        severity: { type: 'string', enum: ['BLOCKER', 'MAJOR', 'MINOR'] },
        file: { type: 'string' }, line: { type: 'string' },
        issue: { type: 'string' }, required_fix: { type: 'string' },
      } } },
  },
}

phase('Implement')
const impl = await agent(
`You are the IMPLEMENTER for M3-terrain feature F3: the HeightField refactor. This is a PURE,
BIT-IDENTICAL refactor — scaffolding for seeded map presets. TDD: write tests/test_heightfield.py
FIRST, then refactor until green without changing ONE bit of default-map behavior.

${CONVENTIONS}
${ANCHORS}
${TEST_CONTRACTS}

Work: (1) read world/generation.py (the functions + constants), sim/radar.py (terrain_blocks +
Radar), sim/recon.py (existing height_fn), world/combat.py (the Radar/SAM/recon/aircraft/enemy-air
construction sites). (2) Write tests/test_heightfield.py. (3) Introduce HeightField + DEFAULT_FIELD
+ shims; add Radar height_fn; thread field.height_scalar in world/combat.py. (4) Run the targeted
tests, then the FULL suite + smoke. Report the bit-identical evidence. If any grid point drifts or
any existing test would need changing, report BLOCKED with specifics — do not fudge.`,
  { label: 'implement:M3-F3-heightfield', phase: 'Implement', schema: IMPL_SCHEMA }
)
log(`Implementer: ${impl ? impl.status : 'NULL'} — ${impl ? impl.files_changed.join(', ') : ''}`)
if (!impl || impl.status === 'BLOCKED' || impl.status === 'NEEDS_CONTEXT') {
  return { halted: true, stage: 'implement', impl }
}

phase('Spec review')
const specReview = await agent(
`You are the SPEC-COMPLIANCE reviewer for the M3 HeightField refactor. DO NOT TRUST THE IMPLEMENTER.
Re-read spec intent + the actual git diff, then RE-RUN the tests yourself and report real counts.
The bar is BIT-IDENTICAL default: prove HeightField grid-equals the legacy functions, prove NO
existing test was modified (git diff --stat on tests/), prove the SYMMETRY contract (player AND
enemy LOS read the same field — no truth leak / asymmetry), and that terrain_blocks SAMPLING was NOT
changed (out of scope here). Re-run: python -m pytest tests/test_heightfield.py tests/test_generation.py
tests/test_radar.py tests/test_sm2_statistics.py -q AND python tools/smoke_combat.py AND the FULL
suite python -m pytest -q.

${CONVENTIONS}
Implementer reported: ${impl.status}; files=${impl.files_changed.join(', ')}; evidence=${impl.bit_identical_evidence}
Return PASS only if bit-identical holds and no test was weakened. List concrete findings w/ file:line.`,
  { label: 'spec-review:M3-F3-heightfield', phase: 'Spec review', schema: REVIEW_SCHEMA }
)
log(`Spec review: ${specReview ? specReview.verdict : 'NULL'} (${specReview ? specReview.findings.length : 0}) — ${specReview ? specReview.reran_tests_output : ''}`)

if (specReview && specReview.verdict === 'FAIL' && specReview.findings.length) {
  phase('Spec fix')
  const fix = await agent(
`FIXER for the M3 HeightField refactor. Fix ALL findings without breaking bit-identical and without
weakening any test. Re-run the heightfield + generation + radar + duel tests + smoke + full suite.
${CONVENTIONS}
FINDINGS:
${specReview.findings.map((f, i) => `${i + 1}. [${f.severity}] ${f.file}:${f.line} — ${f.issue}\n   FIX: ${f.required_fix}`).join('\n')}`,
    { label: 'spec-fix:M3-F3-heightfield', phase: 'Spec fix', schema: IMPL_SCHEMA }
  )
  log(`Spec fix: ${fix ? fix.status : 'NULL'}`)
  const recheck = await agent(
`Re-verify the M3 HeightField refactor after the fixer. Re-run tests/test_heightfield.py
tests/test_generation.py tests/test_radar.py tests/test_sm2_statistics.py -q + smoke + full suite.
Confirm bit-identical. Report PASS/FAIL with real counts.
${CONVENTIONS}`,
    { label: 'spec-recheck:M3-F3-heightfield', phase: 'Spec fix', schema: REVIEW_SCHEMA }
  )
  log(`Spec recheck: ${recheck ? recheck.verdict : 'NULL'}`)
  if (recheck && recheck.verdict === 'FAIL') return { halted: true, stage: 'spec-recheck', specReview, recheck }
}

phase('Quality review')
const qReview = await agent(
`CODE-QUALITY reviewer for the M3 HeightField refactor (spec passed). Judge: are the methods a clean
move of the bodies (no duplicated math, no dead module-level code left behind), constants bound to
self with comments, shims minimal, the field threaded everywhere (no construction site left silently
on the module shim that a preset swap would miss), tests verify real behavior not tautologies?
Re-run tests/test_heightfield.py to confirm green. List concrete findings w/ file:line.
${CONVENTIONS}`,
  { label: 'quality-review:M3-F3-heightfield', phase: 'Quality review', schema: REVIEW_SCHEMA }
)
log(`Quality review: ${qReview ? qReview.verdict : 'NULL'} (${qReview ? qReview.findings.length : 0})`)
if (qReview && qReview.verdict === 'FAIL' && qReview.findings.filter(f => f.severity !== 'MINOR').length) {
  phase('Quality fix')
  const qfix = await agent(
`FIXER for M3 HeightField code-quality findings. Fix BLOCKER/MAJOR (MINOR where cheap) without
changing behavior (stay bit-identical) or weakening tests. Re-run heightfield tests + smoke.
${CONVENTIONS}
FINDINGS:
${qReview.findings.map((f, i) => `${i + 1}. [${f.severity}] ${f.file}:${f.line} — ${f.issue}\n   FIX: ${f.required_fix}`).join('\n')}`,
    { label: 'quality-fix:M3-F3-heightfield', phase: 'Quality fix', schema: IMPL_SCHEMA }
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
