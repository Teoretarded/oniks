export const meta = {
  name: 'm5-buk-mid-sam',
  description: 'M5: Buk mid-SAM TEL, two rounds (9M317 long-reach + 9M338 agile) filling the Pantsir<->S-300 gap. implementer -> spec review -> fix -> quality review -> fix',
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
NON-NEGOTIABLES:
 - REGRESSION / BYTE-IDENTICAL DEFAULT: the Buk is NEW (2 SamDefs + a BUK_TEL launcher + new config
   fields n_buk/buk_9m317_ammo/buk_9m338_ammo/buk_mag_reload_s, all default 0). With n_buk=0 NO Buk is
   built and the default battle + the Oniks-vs-SM-2 duel + determinism stay BIT-IDENTICAL. The Buk
   touches NONE of the duel path. New CombatConfig fields default 0/OFF (LOCKED schema — sign-off
   granted on that condition; add CLAMP_BUK + clamp_config + test_combat_config).
 - PHYSICS NOT DICE: both rounds are SamMissiles guiding on the gated ContactBoard dead-reckoned
   contact estimate + truth only at the terminal fuse — identical to the S-300/SM-2/Pantsir physics.
   No new kill roll. Distinct behaviour (agile turns harder, long reaches farther) EMERGES from the
   SamDef fields (max_g / max_range / loft), MEASURED by a two-round-distinct flyoff probe.
 - FOG / NO CHEAT: launch_buk reads world.contacts.tracks (is_air) only — never truth. The Buk's 9S36
   radar joins radar_net and extends the gated picture honestly (same as the Pantsir radar).
 - DETERMINISM: any per-launch noise uses the [seed, 8] child stream (shared with player-ARM/EW — the
   ROADMAP reserves 8 for Buk too; confirm no collision, the streams are drawn at different call sites).
 - DEFER the 3D meshes (models/buk.py TELAR + build_9m317/9m338) to a later batched model pass — the
   round renders with the existing default missile mesh meanwhile (do NOT add to DEDICATED_MISSILE_IDS
   yet). NEVER weaken a test. STATUS: DONE/DONE_WITH_CONCERNS/BLOCKED/NEEDS_CONTEXT.`

const ANCHORS = `
VERIFIED ANCHORS (the S-300 is the explicit template — mirror it):
 - sim/arsenal.py: SamDef (~73); S300/N40N6/PANTSIR_57E6 are the modeled examples (SI + derivation
   comments per the file's locked convention). ADD BUK_LONG (9M317: ~70km max_range, medium loft =
   default loft params, max_g~24, terminal_range~20km, alt 15m..25km) and BUK_AGILE (9M338: ~40km,
   max_g~50, fuse_radius~12, terminal_range~12km, sprint motor, alt 10m..20km) + a BUK_TEL LauncherDef.
   CONTRACT: 9M338 max_g > 9M317 max_g; 9M317 max_range > 9M338 max_range. Both engage LOW (no 40N6
   4km floor).
 - world/combat.py:2158 _build_s300_battery, :2204 launch_sam(aircraft_id, round_id="48n6"), :2246
   _step_s300_tubes — MIRROR as _build_buk_battery / launch_buk(aircraft_id, round_id) / _step_buk_tubes
   (tube dicts + shared 9M317/9M338 pools + buk_mag_reload_s). :887 self.radar_net — the Buk's 9S36
   Radar JOINS it (like the Pantsir radar) and is dropped from the net on the Buk Structure's death
   (mirror the radar-station/Pantsir on_destroyed). Build a destructible Structure wrapper (reuse the
   s300_tel dims/hp) so it's killable. Keep the 9S36 'ship' range MODEST (don't over-extend the surface
   picture). Build n_buk from config in __init__.
 - world/combat_config.py: ADD n_buk / buk_9m317_ammo / buk_9m338_ammo / buk_mag_reload_s + CLAMP_BUK +
   clamp_config + test_combat_config (all default 0).
 - game/controls.py PLATFORMS_COMBAT (("bastion","s300","drone")) — ADD "buk" GATED OUT when n_buk==0.
   game/keybinds.py:78 sam_round=K_v — reuse V to cycle 9M317/9M338 on the buk platform (48n6/40n6 on
   s300). game/sandbox.py round-select + launch plumbing.
 - game/tactical_map.py:887 _sam_ring — draw the Buk envelope when buk is active (swap max_range/label
   per round, like the 48N6/40N6 ring). game/hud.py:622 s300_round_panel — add a buk_round_panel
   (selected round + readiness + both ammo pools), a pure helper.
 - game/combat_setup.py: Armory rows for the two Buk pools + reload.`

const TEST_CONTRACTS = `
WRITE tests FIRST (TDD). tools/probe_buk_rounds.py measures the two rounds (mirror compare_s300_rounds).
 (a) tests/test_buk.py (defs): both Buk SamDefs have positive physically-ordered fields; 9M338 max_g >
     9M317 max_g; 9M317 max_range > 9M338 max_range; both alt floors are LOW (no 4km floor).
 (b) two-round-distinct (mirror tests/test_s300_rounds_distinct.py): fly each SamMissile headless vs a
     fixed target — the agile 9M338 achieves a SMALLER miss vs a maneuvering target; the long 9M317
     kills a target BEYOND 9M338's range. MEASURED bands from the probe.
 (c) tests/test_buk_launch.py: launch_buk on an air contact returns a SamMissile + consumes the right
     pool; refuses on empty pool / mid-reload / no air track; the Buk 9S36 radar is in world.radar_net
     and extends a contact the 18m station alone misses (compare detection).
 (d) DETERMINISM: same seed + same launch -> identical round ([seed,8]).
 (e) REGRESSION: n_buk=0 -> no Buk, default battle + Oniks-vs-SM-2 duel + full suite + smoke unchanged.`

const IMPL_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['status', 'files_changed', 'tests_added', 'measured', 'regression_note', 'concerns'],
  properties: {
    status: { type: 'string', enum: ['DONE', 'DONE_WITH_CONCERNS', 'BLOCKED', 'NEEDS_CONTEXT'] },
    files_changed: { type: 'array', items: { type: 'string' } },
    tests_added: { type: 'array', items: { type: 'string' } },
    measured: { type: 'string', description: 'Two-round probe: 9M317 vs 9M338 reach + turn/miss numbers; launch_buk pool behavior; radar extension; full suite + smoke.' },
    regression_note: { type: 'string', description: 'Proof n_buk=0 keeps the default battle + duel bit-identical.' },
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
`You are the IMPLEMENTER for M5 Buk mid-SAM: a medium-range player SAM TEL with two rounds (9M317 long
reach + 9M338 agile) filling the Pantsir(20km)<->S-300(150km) gap. The S-300 two-round system is the
EXACT template — mirror it. TDD; measure the two rounds with a probe before locking the bands.
${CONVENTIONS}
${ANCHORS}
${TEST_CONTRACTS}
Build: (1) read sim/arsenal.py (S300/N40N6 SamDefs), world/combat.py (_build_s300_battery / launch_sam /
_step_s300_tubes / radar_net / the Pantsir Structure+on_destroyed), world/combat_config.py, game/controls
+ keybinds + sandbox (platform/V round cycle), game/tactical_map _sam_ring, game/hud s300_round_panel.
(2) Write tests/test_buk.py + test_buk_launch.py + tools/probe_buk_rounds.py FIRST. (3) 2 SamDefs +
BUK_TEL. (4) config fields + clamp + test_combat_config. (5) _build_buk_battery / launch_buk /
_step_buk_tubes + 9S36 radar in radar_net + destructible Structure + on_destroyed. (6) platform (gated)
+ V round cycle + ring + buk_round_panel + armory rows. (7) Run the new tests + the duel + full suite +
smoke; run the two-round probe. Report measured numbers + regression proof. DEFER meshes (placeholder
render). BLOCKED if a round can't hit its envelope honestly.`,
  { label: 'implement:M5-buk', phase: 'Implement', schema: IMPL_SCHEMA }
)
log(`Implementer: ${impl ? impl.status : 'NULL'} — ${impl ? impl.measured : ''}`)
if (!impl || impl.status === 'BLOCKED' || impl.status === 'NEEDS_CONTEXT') {
  return { halted: true, stage: 'implement', impl }
}

phase('Spec review')
const specReview = await agent(
`SPEC-COMPLIANCE reviewer for M5 Buk. DO NOT TRUST THE IMPLEMENTER. Re-read spec + the diff, RE-RUN the
tests + the two-round probe yourself. Verify: the two rounds are physically distinct + the distinction is
MEASURED (agile turns harder, long reaches farther) not asserted; launch_buk is fog-honest (reads contact
tracks, refuses correctly, consumes the right pool); the 9S36 joins radar_net + drops on death; n_buk=0
is byte-identical (duel + default battle); no test weakened; determinism. Re-run tests/test_buk*.py
tests/test_sm2_statistics.py tests/test_combat_config.py + full suite + smoke.
${CONVENTIONS}
Implementer: ${impl.status}; measured=${impl.measured}; regression=${impl.regression_note}
PASS only if every contract holds. Findings w/ file:line.`,
  { label: 'spec-review:M5-buk', phase: 'Spec review', schema: REVIEW_SCHEMA }
)
log(`Spec review: ${specReview ? specReview.verdict : 'NULL'} (${specReview ? specReview.findings.length : 0}) — ${specReview ? specReview.reran_tests_output : ''}`)

if (specReview && specReview.verdict === 'FAIL' && specReview.findings.length) {
  phase('Spec fix')
  const fix = await agent(
`FIXER for M5 Buk. Fix ALL findings without weakening tests or breaking the n_buk=0 byte-identical / duel.
Re-run test_buk* + duel + full suite + smoke + the two-round probe.
${CONVENTIONS}
FINDINGS:
${specReview.findings.map((f, i) => `${i + 1}. [${f.severity}] ${f.file}:${f.line} — ${f.issue}\n   FIX: ${f.required_fix}`).join('\n')}`,
    { label: 'spec-fix:M5-buk', phase: 'Spec fix', schema: IMPL_SCHEMA }
  )
  log(`Spec fix: ${fix ? fix.status : 'NULL'}`)
  const recheck = await agent(
`Re-verify M5 Buk after the fixer: re-run tests/test_buk*.py tests/test_sm2_statistics.py + full suite +
smoke + the two-round probe. Confirm distinct rounds + byte-identical default. PASS/FAIL with counts.
${CONVENTIONS}`,
    { label: 'spec-recheck:M5-buk', phase: 'Spec fix', schema: REVIEW_SCHEMA }
  )
  log(`Spec recheck: ${recheck ? recheck.verdict : 'NULL'}`)
  if (recheck && recheck.verdict === 'FAIL') return { halted: true, stage: 'spec-recheck', specReview, recheck }
}

phase('Quality review')
const qReview = await agent(
`CODE-QUALITY reviewer for M5 Buk (spec passed). Judge: the SamDefs have derivation comments per the
arsenal.py convention; _build_buk_battery/launch_buk/_step_buk_tubes share structure with the S-300
(no gratuitous divergence); the platform is gated out at n_buk=0; named constants; no dead code; tests
verify measured behavior not tautologies; the 9S36 'ship' range is modest. Re-run test_buk*.py. Findings.
${CONVENTIONS}`,
  { label: 'quality-review:M5-buk', phase: 'Quality review', schema: REVIEW_SCHEMA }
)
log(`Quality review: ${qReview ? qReview.verdict : 'NULL'} (${qReview ? qReview.findings.length : 0})`)
if (qReview && qReview.verdict === 'FAIL' && qReview.findings.filter(f => f.severity !== 'MINOR').length) {
  phase('Quality fix')
  const qfix = await agent(
`FIXER for M5 Buk code-quality findings. Fix BLOCKER/MAJOR (MINOR where cheap) without changing behavior
or weakening tests. Re-run test_buk* + smoke.
${CONVENTIONS}
FINDINGS:
${qReview.findings.map((f, i) => `${i + 1}. [${f.severity}] ${f.file}:${f.line} — ${f.issue}\n   FIX: ${f.required_fix}`).join('\n')}`,
    { label: 'quality-fix:M5-buk', phase: 'Quality fix', schema: IMPL_SCHEMA }
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
