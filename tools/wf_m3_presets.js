export const meta = {
  name: 'm3-map-presets',
  description: 'M3-terrain F4: seeded map presets (Open Sea / Archipelago / Narrow Strait / Fjord) exercising terrain masking. implementer -> spec review -> fix -> quality review -> fix',
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
  Full suite: python -m pytest -q (~6 min). Smoke: python tools/smoke_combat.py (70/70 exit 0).
NON-NEGOTIABLES:
 - PRESET 0 BYTE-IDENTICAL: make_field(0, seed) MUST equal today's default field bit-for-bit; the
   out-of-the-box battle (map_preset default 0) stays byte-identical. This is THE regression gate.
 - DETERMINISM: every preset field is built ONLY from np.random.default_rng([seed, 12]) — NEW tag 12
   (tags 3..7 + 8/9/10/11 are taken; 12 is fresh for map terrain). No wall-clock, no global RNG.
   make_field(p, s) twice -> identical; same seed+preset replays exactly.
 - FOG/SYMMETRY: the renderer must show the SAME field the sim masks with (spec risk: a 3D coastline
   that doesn't match LOS is a perception/fog bug). Player AND enemy already read world.height_field
   (M3-F3); presets just swap which field that is.
 - LOCKED CombatConfig schema: adding map_preset needs the integrator sign-off the file mandates —
   it is GRANTED here on the condition it defaults 0 (byte-identical) + clamps to (0,3). Add the field,
   CLAMP_MAP_PRESET, a MAP_PRESET_NAMES table, clamp_config wiring, and a test in test_combat_config.py.
 - NEVER weaken a test; if a contract can't pass honestly, report BLOCKED. STATUS PROTOCOL: end with
   DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT. Bad work is worse than no work.`

const ANCHORS = `
VERIFIED ANCHORS:
 - world/generation.py: HeightField(seed, islands, enemy_coast_z, max_height, coast_wiggle, coast_ramp,
   shelf_ramp, island_shore_slope, cont_band_m, skirt_min_m) ALREADY exists (M3-F3) and is fully
   parameterized — presets are just different constructor args. DEFAULT_FIELD = HeightField() is the
   byte-identical default. ISLANDS is the default island list [(cx, cz, radius, peak), ...]. ADD
   make_field(preset: int, seed: int) -> HeightField: preset 0 returns the DEFAULT field (ignore seed
   for terrain so it stays byte-identical); presets 1-3 build island sets / coast params from
   np.random.default_rng([seed, 12]). Keep the HOME-coast base cluster geometry stable across presets
   (do NOT relocate base/SAM/Pantsir/radar — vary the ENEMY-side approaches + mid-ocean islands).
   Fjord (preset 3) may use a taller max_height (per-field) + indented coast walls.
 - world/combat.py: builds the field for the world (currently the default). Change to
   make_field(config.map_preset, config.seed) and thread it (M3-F3 plumbing already threads
   self._height_field everywhere). Spawns: LANES / SHIP_SPAWNS / AIRCRAFT_SPAWNS must DODGE new islands
   (no ship/aircraft starts on land) — gate each spawn so field.height_scalar(x,z) <= 0 there
   (mirror the existing '>= 12 km from ISLANDS' lane comment).
 - world/combat_config.py: LOCKED frozen schema + clamp_config. ADD map_preset:int=0,
   CLAMP_MAP_PRESET=(0,3), MAP_PRESET_NAMES=("OPEN SEA","ARCHIPELAGO","NARROW STRAIT","FJORD COAST").
 - world/terrain.py: the 3D Terrain renderer derives FEATURES/ISLANDS/h_ref — make it read the active
   world.height_field (Terrain(field)) instead of importing module ISLANDS, so the 3D coast MATCHES the
   sim field. (If a full Terrain(field) refactor is too deep, at minimum make its island/coast source the
   world field and note any remainder.) game/tactical_map.py already samples the field -> auto-correct.
 - game/combat_setup.py: _WORLD_ROWS — ADD a MAP row. If an 'enum' cyclic row kind exists use it; else
   add a minimal cyclic LEFT/RIGHT row bound to map_preset within CLAMP_MAP_PRESET (mirror the existing
   stepper/seed row handling in _adjust). START must emit a config carrying map_preset.
 - The M3 close-range LOS fix (terrain_blocks fine sampling <6km) is IN — masking now bites for these
   presets. Probe: tools/probe_terrain_los.py is the pattern for tools/probe_preset_masking.py.`

const TEST_CONTRACTS = `
WRITE tests FIRST (TDD), then implement. Contracts (spec 09 F4):
 (a) PRESET 0 BYTE-IDENTICAL: make_field(0, 1337).height(grid) == HeightField().height(grid) exactly
     over a large fixed grid; all of tests/test_heightfield.py + test_generation.py still pass.
 (b) DETERMINISM: make_field(p, s) twice -> identical heights for all p in 0..3; different seeds ->
     different islands (a content diff) for presets 1-3; same seed+preset replays exactly.
 (c) MASKING BITES: tools/probe_preset_masking.py + a test asserting that on Archipelago/Strait/Fjord
     there EXIST sensor/target pairs where terrain_blocks is True (terrain is actually used); on Open Sea
     masking is rare. A known fjord/island shadow target is masked from a known sensor.
 (d) SYMMETRY/HONESTY: on each preset enemy and player height_fn are the SAME field instance (reuse the
     M3-F3 symmetry assertion); a target hidden from the player by terrain is hidden from the enemy too.
 (e) max_height respected: field.height(grid).max() < field.max_height for every preset (incl. Fjord's
     taller max); the flyer-skip optimization still holds.
 (f) AI NOT STUCK: run python tools/smoke_combat.py for EACH preset (parametrize the smoke or a per-preset
     harness) -> exit 0 / battle resolves (the AI finds fire lines; not soft-locked).
 (g) SPAWNS VALID: no ship/aircraft spawn on land for any preset (field.height_scalar <= 0 at every
     spawn point) — add an explicit test building a world per preset.
 (h) SETUP MAP row: tests/test_combat_setup.py cycles map_preset within CLAMP and START emits it.
 (i) test_combat_config.py: map_preset default 0, clamp_config round-trips it within (0,3).`

const IMPL_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['status', 'files_changed', 'tests_added', 'measured', 'byte_identical_note', 'concerns'],
  properties: {
    status: { type: 'string', enum: ['DONE', 'DONE_WITH_CONCERNS', 'BLOCKED', 'NEEDS_CONTEXT'] },
    files_changed: { type: 'array', items: { type: 'string' } },
    tests_added: { type: 'array', items: { type: 'string' } },
    measured: { type: 'string', description: 'Per-preset: masking-bites probe numbers, per-preset smoke exit codes, full suite + smoke results.' },
    byte_identical_note: { type: 'string', description: 'Proof preset 0 is byte-identical + default battle unchanged.' },
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
`You are the IMPLEMENTER for M3-terrain feature F4: seeded map presets. Four selectable battle maps
(0 Open Sea = today's layout / 1 Archipelago / 2 Narrow Strait / 3 Fjord Coast) that finally exercise
the terrain-masking + radar-horizon physics. TDD: write the tests/probe FIRST, then implement.

${CONVENTIONS}
${ANCHORS}
${TEST_CONTRACTS}

Build order: (1) read world/generation.py (HeightField + ISLANDS + coast params), world/combat.py (field
build + LANES/SHIP_SPAWNS/AIRCRAFT_SPAWNS), world/combat_config.py, world/terrain.py, game/combat_setup.py.
(2) Write tests/test_map_presets.py + tools/probe_preset_masking.py (TDD). (3) make_field factory + 4
preset HeightFields (preset 0 = default, byte-identical; 1-3 seeded [seed,12], home cluster stable,
enemy-side islands/walls). (4) map_preset config + clamp + names + test_combat_config. (5) thread
make_field in world/combat.py + spawn-dodging. (6) Terrain reads the world field (3D coast matches sim).
(7) setup MAP row. (8) Run: the new tests, per-preset smoke (all 4 exit 0), full suite, smoke.
Report measured numbers. If a preset soft-locks the AI or can't dodge spawns, report it — do not ship a
broken map. Keep each preset WINNABLE and LOSABLE.`,
  { label: 'implement:M3-F4-presets', phase: 'Implement', schema: IMPL_SCHEMA }
)
log(`Implementer: ${impl ? impl.status : 'NULL'} — ${impl ? impl.files_changed.join(', ') : ''}`)
if (!impl || impl.status === 'BLOCKED' || impl.status === 'NEEDS_CONTEXT') {
  return { halted: true, stage: 'implement', impl }
}

phase('Spec review')
const specReview = await agent(
`SPEC-COMPLIANCE reviewer for M3-F4 map presets. DO NOT TRUST THE IMPLEMENTER. Re-read spec + the actual
diff, RE-RUN tests yourself. Verify: preset 0 BYTE-IDENTICAL (grid-equality + default battle unchanged);
determinism (only [seed,12]); masking actually BITES on presets 1-3 (re-run probe_preset_masking.py);
symmetry (one field both sides); spawns valid (no ship/aircraft on land, all presets); AI not stuck (run
tools/smoke_combat.py per preset, all exit 0); the renderer (Terrain) reads the world field not module
ISLANDS; no existing test weakened. Re-run the new tests + test_combat_config + test_combat_setup +
test_heightfield + test_generation + full suite + smoke.
${CONVENTIONS}
Implementer reported: ${impl.status}; files=${impl.files_changed.join(', ')}; measured=${impl.measured}
Return PASS only if every contract holds. Concrete findings w/ file:line.`,
  { label: 'spec-review:M3-F4-presets', phase: 'Spec review', schema: REVIEW_SCHEMA }
)
log(`Spec review: ${specReview ? specReview.verdict : 'NULL'} (${specReview ? specReview.findings.length : 0}) — ${specReview ? specReview.reran_tests_output : ''}`)

if (specReview && specReview.verdict === 'FAIL' && specReview.findings.length) {
  phase('Spec fix')
  const fix = await agent(
`FIXER for M3-F4 map presets. Fix ALL findings without breaking preset-0 byte-identical / determinism /
spawns-valid / AI-not-stuck, and without weakening tests. Re-run the preset tests + per-preset smoke +
full suite + smoke.
${CONVENTIONS}
FINDINGS:
${specReview.findings.map((f, i) => `${i + 1}. [${f.severity}] ${f.file}:${f.line} — ${f.issue}\n   FIX: ${f.required_fix}`).join('\n')}`,
    { label: 'spec-fix:M3-F4-presets', phase: 'Spec fix', schema: IMPL_SCHEMA }
  )
  log(`Spec fix: ${fix ? fix.status : 'NULL'}`)
  const recheck = await agent(
`Re-verify M3-F4 after the fixer. Re-run the preset tests + test_combat_config + test_combat_setup +
per-preset smoke + full suite. Confirm preset-0 byte-identical + masking bites + spawns valid + AI not
stuck. Report PASS/FAIL with real counts.
${CONVENTIONS}`,
    { label: 'spec-recheck:M3-F4-presets', phase: 'Spec fix', schema: REVIEW_SCHEMA }
  )
  log(`Spec recheck: ${recheck ? recheck.verdict : 'NULL'}`)
  if (recheck && recheck.verdict === 'FAIL') return { halted: true, stage: 'spec-recheck', specReview, recheck }
}

phase('Quality review')
const qReview = await agent(
`CODE-QUALITY reviewer for M3-F4 (spec passed). Judge: are the preset params named constants with a
comment on the geography they model (not magic tuples), the make_field factory clean, spawn-dodging DRY
(not copy-pasted), no dead code, tests verifying real masking/spawn behavior not tautologies, the [seed,12]
tag allocated centrally with a comment? Re-run the preset tests to confirm green. Findings w/ file:line.
${CONVENTIONS}`,
  { label: 'quality-review:M3-F4-presets', phase: 'Quality review', schema: REVIEW_SCHEMA }
)
log(`Quality review: ${qReview ? qReview.verdict : 'NULL'} (${qReview ? qReview.findings.length : 0})`)
if (qReview && qReview.verdict === 'FAIL' && qReview.findings.filter(f => f.severity !== 'MINOR').length) {
  phase('Quality fix')
  const qfix = await agent(
`FIXER for M3-F4 code-quality findings. Fix BLOCKER/MAJOR (MINOR where cheap) without changing behavior or
weakening tests. Re-run preset tests + smoke.
${CONVENTIONS}
FINDINGS:
${qReview.findings.map((f, i) => `${i + 1}. [${f.severity}] ${f.file}:${f.line} — ${f.issue}\n   FIX: ${f.required_fix}`).join('\n')}`,
    { label: 'quality-fix:M3-F4-presets', phase: 'Quality fix', schema: IMPL_SCHEMA }
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
