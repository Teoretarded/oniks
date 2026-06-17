export const meta = {
  name: 'm3f5-jammed-ui',
  description: 'M3-F5 JAMMED-band overlay + RADAR-DEGRADED HUD row + emissions-exposure meter: implementer -> spec review -> fix -> quality review -> fix (Fable per-feature loop)',
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
  Full suite: python -m pytest -q   (~6 min). Targeted: python -m pytest tests/test_ew_ui.py -q
  Smoke gate (MUST stay 70/70 exit 0): python tools/smoke_combat.py
NON-NEGOTIABLES:
 - FOG / NO CHEAT: the JAMMED band MUST be drawn from the SENSOR-BELIEVED jammer fix
   (the drone ELINT est_pos / bearing), NEVER a real jammer entity's .pos. Reading a real
   jammer pos for the overlay = a fog leak = the build fails. The emissions-exposure meter may
   read the player's OWN assets (own radar_station.emitting, own drone pod hot) — own-truth is allowed.
 - DETERMINISM: pure UI helpers add NO RNG and do not touch sim state. The world's ew_state publish
   is a read-only summary computed from already-stepped state; it must not change any sim result.
 - REGRESSION / BYTE-IDENTICAL DEFAULT: with config.n_jammers=0 and config.player_jammer=0 there is
   no active jammer, so radar_jam_row(world) returns None and _jam_overlay draws nothing and ew_state
   reports inactive. The out-of-the-box battle and every existing test stay byte-identical.
   NEVER weaken an existing test. If a planned assertion can't pass honestly, report BLOCKED.
TEST CONVENTION: pure, GL-free helpers tested with the project's FakeText draw-call recorder (grep the
  existing tests, e.g. tests/test_*hud* / tests/test_*tactical* / how radar_status_row & _elint_overlay
  are tested) so OpenGL never enters tests. Mirror that convention exactly.
CODE CONVENTION: named tuning constants with a comment on the physical/visual rationale; reuse
  SEMANTIC_COLORS (game/states.py) — never hard-code a color per call site; reuse draw_text/draw_lines/
  draw_rect only (no images/gradients). New HUD helpers return (label, value, color) tuples like the
  existing row helpers and return None when not applicable (SANDBOX / no jammer) so non-EW worlds are
  unaffected. STATUS PROTOCOL: end your report with exactly one of DONE / DONE_WITH_CONCERNS / BLOCKED /
  NEEDS_CONTEXT and spell out any concern. Bad work is worse than no work — escalate, don't guess.
`

const INTEGRATION_ANCHORS = `
VERIFIED INTEGRATION ANCHORS (read these before writing):
 - sim/ew.py already has effective_range(radar, size_class, target_pos, jammers) and burn_through_range(...)
   — the SINGLE SOURCE OF TRUTH for the burn-through number. The HUD row MUST derive its km from this,
   not recompute physics.
 - world/combat.py:
     _active_enemy_jammers() (line ~782) returns the live enemy jammer emitters (.pos + .jam_power_w);
     _player_visible() (line ~834) already gates radar_net.visible(..., jammers=self._active_enemy_jammers()).
   ADD: publish self.ew_state each step (after the step where jammers + picture are current) — a small dict
   the UI reads, e.g. {"active": bool, "burn_through_m": float|None, "jammer_bearing": float|None,
   "jammer_fix_xz": (x,z)|None}. The believed jammer fix/bearing comes from the drone ELINT picture
   (world.elint / world.emitter_contacts where kind == "JAMMER") — the BELIEF, never the real jammer.
   burn_through_m = sim/ew.effective_range for the player's ship-ring radar under _active_enemy_jammers().
   With no active jammer -> {"active": False, ...} and the legacy byte-identical path is untouched.
 - game/hud.py: radar_status_row(world) @361 and pantsir_status_row @375 are the EXACT pure-helper template.
   ADD radar_jam_row(world) -> ("RADAR", "BURN-THRU <km>km", amber) / ("RADAR","NET DEGRADED",red) / None,
   reading world.ew_state. Call it in _bastion_block (@787) / _s300_block (@835) next to radar_status_row.
   ADD the emissions-exposure meter as a pure helper, e.g. emissions_exposure(world) -> (label, frac01, color)
   reading ONLY own assets (own radar_station.emitting + own drone pod hot) -> a 0..1 exposure fraction
   rendered with gauge_bar (game/states.py / hud_widgets). Returns None in SANDBOX / when nothing emits.
 - game/tactical_map.py: _elint_overlay() @1061 and _emitter_overlay() @1094 are the overlay template
   (already draws the JAMMER glyph). ADD _jam_overlay() called from draw(): a translucent corridor WEDGE
   from the BELIEVED jammer fix (world.ew_state.jammer_fix_xz) toward the coast, plus the player net's
   shrunken effective ring as a DASHED circle. If only a bearing is known (jammer_fix_xz None but bearing
   set) draw an OPEN bearing wedge with NO closed origin circle. If ew_state inactive -> draw nothing.
   Use the existing _poly_world / range-ring helpers + the ELINT magenta family palette.
`

const SPEC_F5 = `
SPEC (verbatim, spec 04 "JAMMED-band map overlay + RADAR DEGRADED HUD row", + the emissions-exposure meter
listed in ROADMAP M3 UI surfaces). Build EXACTLY this:

The mandatory player-legibility layer: a JAMMED corridor/band on the tactical map and a degraded-radar
readout on the HUD, so the invisible J/S math becomes a readable tactical picture. The band is drawn from
the SENSOR-BELIEVED jammer location (fog honest), not truth.

Player reads: a translucent magenta/red wedge spanning the jam corridor (origin = believed jammer, width =
a fixed beamwidth, length = to the map edge); the player net's shrunken effective ring as a DASHED circle
(vs the normal solid range ring); a HUD row "RADAR BURN-THRU 62 km" (amber) or "NET DEGRADED" when collapsed.
As the player kills/closes the jammer the wedge narrows/fades. Plus an emissions-exposure meter: a gauge
showing how loud the PLAYER currently is (own radar emitting + own EW pod hot) so the player can manage the
back-plot risk of going active — reads own assets only (own-truth allowed).

Sourced entirely from PLAYER sensors: the wedge is anchored at the believed jammer ELINT fix, or (before a
fix) drawn as an open bearing wedge from the ELINT/RWR bearing. If the player has NO sensor on the jammer at
all, the band is absent (you feel the degraded range via the HUD row but can't place the source — the fog
intent). The burn-through number is the player net's effective_range under jam (sim/ew.py — single source).

TEST CONTRACTS (write tests/test_ew_ui.py FIRST, headless/pure, FakeText where GL is involved):
 (1) radar_jam_row returns None with no active jammer, an amber row with one active jammer.
 (2) the burn-through value in the row matches sim/ew.effective_range for the player net (single source of truth).
 (3) _jam_overlay band geometry is computed from the BELIEVED fix (assert it uses world.ew_state.jammer_fix,
     not a real jammer pos) — the fog-of-war contract (e.g. monkeypatch the real jammer far from its believed
     fix and assert the wedge follows the BELIEF).
 (4) with a bearing-only (un-localized) jammer the overlay draws an OPEN wedge (no closed origin circle).
 (5) pure helpers stay GL-free and import headless (matches the locked tactical_map/hud test convention).
 (6) byte-identical default: with n_jammers=0/player_jammer=0, radar_jam_row is None, ew_state inactive,
     _jam_overlay is a no-op, and the existing suite + smoke stay green.
`

const IMPL_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['status', 'files_changed', 'tests_added', 'measured_numbers', 'fog_determinism_note', 'concerns'],
  properties: {
    status: { type: 'string', enum: ['DONE', 'DONE_WITH_CONCERNS', 'BLOCKED', 'NEEDS_CONTEXT'] },
    files_changed: { type: 'array', items: { type: 'string' } },
    tests_added: { type: 'array', items: { type: 'string' } },
    measured_numbers: { type: 'string', description: 'pytest result for the new file + smoke result + the burn-through km the row shows in a built EW world.' },
    fog_determinism_note: { type: 'string', description: 'Exactly how the band reads belief not truth, and why default stays byte-identical.' },
    concerns: { type: 'string' },
  },
}
const REVIEW_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['verdict', 'reran_tests_output', 'findings'],
  properties: {
    verdict: { type: 'string', enum: ['PASS', 'FAIL'] },
    reran_tests_output: { type: 'string', description: 'The actual pass/fail counts you got RE-RUNNING the tests + smoke yourself (do not trust the implementer).' },
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
`You are the IMPLEMENTER for feature M3-F5. TDD: write tests/test_ew_ui.py FIRST (from the contracts below),
watch them fail for the right reason, then implement minimally until green. Do NOT modify any existing test.

${CONVENTIONS}
${INTEGRATION_ANCHORS}
${SPEC_F5}

Steps: (1) read sim/ew.py, world/combat.py (the EW seams ~780-940), game/hud.py (radar_status_row pattern),
game/tactical_map.py (_elint_overlay/_emitter_overlay), game/states.py (SEMANTIC_COLORS, gauge_bar) and an
existing pure-helper test to learn the FakeText convention. (2) Write tests/test_ew_ui.py. (3) Implement
world.ew_state publish + hud.radar_jam_row + emissions_exposure + tactical_map._jam_overlay + wire the HUD
calls. (4) Run: python -m pytest tests/test_ew_ui.py -q  AND  python -m pytest tests/test_ew_field.py
tests/test_ew_jammer.py tests/test_player_ew_pod.py -q (EW regression) AND python tools/smoke_combat.py.
Report the structured result. If anything can't be done honestly, BLOCKED with the reason — do not fudge.`,
  { label: 'implement:M3-F5', phase: 'Implement', schema: IMPL_SCHEMA }
)
log(`Implementer: ${impl ? impl.status : 'NULL'} — ${impl ? impl.files_changed.join(', ') : ''}`)
if (!impl || impl.status === 'BLOCKED' || impl.status === 'NEEDS_CONTEXT') {
  return { halted: true, stage: 'implement', impl }
}

phase('Spec review')
const specReview = await agent(
`You are the SPEC-COMPLIANCE reviewer for M3-F5. DO NOT TRUST THE IMPLEMENTER'S REPORT. Re-read the spec and
the ACTUAL diff (git diff), then RE-RUN the tests yourself and report the real counts. Check for: missing
requirements, smuggled extras, and especially the FOG CONTRACT — prove the band reads world.ew_state belief
and NOT a real jammer pos (read _jam_overlay line by line; trace jammer_fix_xz back to the ELINT belief).
Verify byte-identical default (n_jammers=0 -> radar_jam_row None, no-op overlay) and that NO existing test
was weakened. Re-run: python -m pytest tests/test_ew_ui.py tests/test_ew_field.py tests/test_ew_jammer.py
tests/test_player_ew_pod.py -q AND python tools/smoke_combat.py.

${CONVENTIONS}
${SPEC_F5}

Implementer reported: status=${impl.status}; files=${impl.files_changed.join(', ')}; note=${impl.fog_determinism_note}
Return PASS only if every contract holds honestly. List concrete findings with file:line and the required fix.`,
  { label: 'spec-review:M3-F5', phase: 'Spec review', schema: REVIEW_SCHEMA }
)
log(`Spec review: ${specReview ? specReview.verdict : 'NULL'} (${specReview ? specReview.findings.length : 0} findings) — reran: ${specReview ? specReview.reran_tests_output : ''}`)

if (specReview && specReview.verdict === 'FAIL' && specReview.findings.length) {
  phase('Spec fix')
  const fix = await agent(
`You are the FIXER for M3-F5. The spec reviewer found these issues — fix ALL of them without weakening any
test and without breaking the fog/determinism/byte-identical contracts. Re-run the EW UI + EW regression
tests + smoke and confirm green.
${CONVENTIONS}
FINDINGS:
${specReview.findings.map((f, i) => `${i + 1}. [${f.severity}] ${f.file}:${f.line} — ${f.issue}\n   FIX: ${f.required_fix}`).join('\n')}`,
    { label: 'spec-fix:M3-F5', phase: 'Spec fix', schema: IMPL_SCHEMA }
  )
  log(`Spec fix: ${fix ? fix.status : 'NULL'}`)
  const recheck = await agent(
`Re-verify M3-F5 after the fixer. Re-run python -m pytest tests/test_ew_ui.py tests/test_ew_field.py
tests/test_ew_jammer.py tests/test_player_ew_pod.py -q and python tools/smoke_combat.py and confirm the
fog contract holds (band reads belief). Report PASS/FAIL with the real counts.
${CONVENTIONS}`,
    { label: 'spec-recheck:M3-F5', phase: 'Spec fix', schema: REVIEW_SCHEMA }
  )
  log(`Spec recheck: ${recheck ? recheck.verdict : 'NULL'}`)
  if (recheck && recheck.verdict === 'FAIL') return { halted: true, stage: 'spec-recheck', specReview, recheck }
}

phase('Quality review')
const qReview = await agent(
`You are the CODE-QUALITY reviewer for M3-F5 (spec already passed). Judge whether it is WELL built:
named visual/tuning constants WITH comments (no magic numbers in the wedge/ring geometry), reuse of
SEMANTIC_COLORS (no hard-coded colors), no dead code, helpers pure/GL-free, tests verify real behavior
(not tautologies — e.g. the fog test must actually move truth away from belief and assert the wedge follows
belief), and the overlay respects the one-flush quad budget (rect+line+text only). Re-run the EW UI tests to
confirm still green. List concrete findings with file:line.
${CONVENTIONS}`,
  { label: 'quality-review:M3-F5', phase: 'Quality review', schema: REVIEW_SCHEMA }
)
log(`Quality review: ${qReview ? qReview.verdict : 'NULL'} (${qReview ? qReview.findings.length : 0} findings)`)

if (qReview && qReview.verdict === 'FAIL' && qReview.findings.filter(f => f.severity !== 'MINOR').length) {
  phase('Quality fix')
  const qfix = await agent(
`You are the FIXER for M3-F5 code-quality findings. Fix all BLOCKER/MAJOR items (and MINOR where cheap)
without changing behavior or weakening tests. Re-run tests/test_ew_ui.py + smoke; confirm green.
${CONVENTIONS}
FINDINGS:
${qReview.findings.map((f, i) => `${i + 1}. [${f.severity}] ${f.file}:${f.line} — ${f.issue}\n   FIX: ${f.required_fix}`).join('\n')}`,
    { label: 'quality-fix:M3-F5', phase: 'Quality fix', schema: IMPL_SCHEMA }
  )
  log(`Quality fix: ${qfix ? qfix.status : 'NULL'}`)
}

return {
  done: true,
  implementer: impl,
  spec_verdict: specReview ? specReview.verdict : null,
  quality_verdict: qReview ? qReview.verdict : null,
  spec_findings: specReview ? specReview.findings : [],
  quality_findings: qReview ? qReview.findings : [],
}
