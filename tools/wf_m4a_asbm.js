export const meta = {
  name: 'm4a-asbm',
  description: 'M4-A: Bastion-K top-attack ASBM (AsbmMissile(SamMissile) re-pointed at ships). flyoff-probe-first; implementer -> spec review -> fix -> quality review -> fix',
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
 - PHYSICS NOT DICE: the ASBM's apogee/dive/terminal-kill must EMERGE from the SamMissile loft+PN+fuse
   machine, never a roll. MEASURE FIRST: write tools/probe_asbm_flyoff.py (mirror compare_s300_rounds.py)
   that prints apogee / terminal flight-path-angle / peak Mach BEFORE you lock the envelope test. The
   project memory warns the loft/descent gains are Mach-2.5-tuned (Oniks) — a fast lofted round may
   overfly/undershoot; tune loft_bias_max + motor_time to the MEASURED profile, do NOT copy the 40N6's
   4 km floor (the ASBM dives to the SEA). Lock the test to the MEASURED band (two-sided).
 - REGRESSION / BYTE-IDENTICAL: ASBM is a NEW SamDef + a NEW AsbmMissile subclass + a NEW ammo pool
   (asbm_ammo default 0). It must touch NONE of the Oniks-vs-SM-2 duel or existing SAM flight — the
   duel + determinism + default battle stay bit-identical. New CombatConfig field defaults 0/OFF.
 - FOG / NO CHEAT: the ASBM flies BOOST/MIDCOURSE on the dead-reckoned player ContactBoard estimate
   (contact_estimate_fn); only the terminal MaRV seeker sees truth (the proximity fuse, like every
   round). The enemy SM-6/SM-2 fire ONLY off their own sensor tracks (already coded) — add no AI cheat.
 - DETERMINISM: reuse the SamMissile seeded streams; same seed -> identical trajectory. No wall-clock.
 - NEVER weaken a test; BLOCKED if a contract can't pass honestly. STATUS: DONE/DONE_WITH_CONCERNS/
   BLOCKED/NEEDS_CONTEXT. Bad work is worse than no work.`

const ANCHORS = `
VERIFIED ANCHORS:
 - sim/arsenal.py: @73 class SamDef carries loft_gain/loft_bias_max/loft_fade_range (read per-round by
   sim/sam.py). ADD an ASBM SamDef (long burn, high loft_bias_max ~50-60 km, terminal handover to a
   ship seeker, intercept-alt band set to the SEA so the ARH terminal works at the surface — NOT the
   40N6 4 km floor). Register it + an ASBM ammo constant.
 - sim/sam.py: class SamMissile = catapult/boost/loft/coast/terminal-PN/proximity-fuse + multipath OU.
   sim/sam.py also has StealthTargetSam (low-SNR). REUSE SamMissile UNCHANGED for boost/loft/coast/
   fuse; subclass AsbmMissile(SamMissile) whose TERMINAL phase locks the nearest alive SHIP in a cone
   (port the cos_half/seeker_range loop from sim/missile.py _acquire_lock) instead of the air-target PN.
   Put it in NEW sim/asbm.py.
 - sim/missile.py: _acquire_lock — the nearest-ship-in-cone seeker loop to PORT for the MaRV terminal.
 - world/world.py:461 _contact_estimate(aircraft_id) — the dead-reckoned contact the round flies on.
 - world/combat.py:450 self._zircon_ammo (scarce-pool pattern) + :1858 the zircon launch branch + :1878
   decrement — mirror for self._asbm_ammo. launch() weapon_id branch: add 'asbm' spawning AsbmMissile
   aimed at the selected ship contact estimate, is_hostile=False.
 - sim/enemy_defense.py SM6_AREA_MIN_ALT_M=1500 + _try_sm6_launch — the EXISTING counter; the ASBM's
   high midcourse must stay ABOVE this band so it's SM-6-targetable (a test pins this). Do NOT touch it.
 - game/sandbox.py:507 cycle_oniks_weapon (oniks->zircon->kh31p->oniks today) — extend to include 'asbm'
   (4-way; only show ASBM when asbm_ammo configured, like kh31p). :590 request_launch — add an asbm
   branch reusing the ship-contact path (skip the hi-lo/lo-lo envelope warning; add a stale-track hint).
 - game/keybinds.py:80 oniks_weapon=K_b; game/controls.py:186 routes it.
 - game/hud.py bastion_weapon_strip (@~447 area) — add the ASBM row when configured (mirror KH-31P).
 - world/combat_config.py: ADD asbm_ammo:int=0 + CLAMP + clamp_config + test_combat_config.
 - tests/test_s300_rounds_distinct.py: reuse its _World/_StaticTarget/_MovingTarget stubs for the flyoff.`

const TEST_CONTRACTS = `
MEASURE then TDD. tools/probe_asbm_flyoff.py prints apogee / terminal FPA / peak Mach vs a ship at
~250 km BEFORE locking the band. Then tests/test_asbm.py:
 (1) test_asbm_lofts_high_and_dives_near_vertical: apogee >= 40 km AND terminal flight-path angle
     steeper than -60 deg (measured at terminal handover).
 (2) test_asbm_kills_stationary_ship_in_envelope: fuse kill on a static hull.
 (3) test_asbm_misses_fast_mover_on_stale_track: launched on a FROZEN contact_estimate while the ship
     moved away -> closest approach > fuse radius (the stale-picture miss, physics not dice).
 (4) test_asbm_fresh_track_kills_same_mover: SAME mover but contact_estimate refreshed -> kill (proves
     it's the STALE picture, not the airframe, that misses).
 (5) test_asbm_high_midcourse_is_sm6_targetable: dead-reckoned midcourse altitude stays > 1500 m over
     the cruise (locks the existing SM-6 counter contract).
 (6) test_asbm_determinism: same seed -> identical trajectory.
 (7) byte-identical: asbm_ammo=0 -> no ASBM; Oniks-vs-SM-2 duel + full suite + smoke unchanged.`

const IMPL_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['status', 'files_changed', 'tests_added', 'measured_profile', 'regression_note', 'concerns'],
  properties: {
    status: { type: 'string', enum: ['DONE', 'DONE_WITH_CONCERNS', 'BLOCKED', 'NEEDS_CONTEXT'] },
    files_changed: { type: 'array', items: { type: 'string' } },
    tests_added: { type: 'array', items: { type: 'string' } },
    measured_profile: { type: 'string', description: 'Probe numbers: apogee km, terminal FPA deg, peak Mach, kill/miss ranges — the MEASURED band the tests lock.' },
    regression_note: { type: 'string', description: 'Proof the duel + default battle stay bit-identical (asbm_ammo=0).' },
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
`You are the IMPLEMENTER for M4-A: the Bastion-K quasi-ballistic top-attack ASBM — a lofted anti-ship
missile that beats the SM-2 screen by ALTITUDE+SPEED then dives near-vertically onto a ship. MEASURE the
flight profile with a probe BEFORE locking envelope tests, then TDD.

${CONVENTIONS}
${ANCHORS}
${TEST_CONTRACTS}

Build: (1) read sim/sam.py (SamMissile loft/terminal/fuse), sim/missile.py _acquire_lock (ship seeker),
sim/arsenal.py SamDef, world/combat.py (zircon pool + launch), world/world.py _contact_estimate,
sim/enemy_defense.py (SM-6 counter), game/sandbox.py cycle_oniks_weapon + request_launch, game/hud.py
weapon strip. (2) Write tools/probe_asbm_flyoff.py and RUN it; tune the ASBM SamDef to a real lofted
top-attack profile (apogee>=40km, dive steeper than -60deg to the SEA, NOT the 40N6 floor). (3) AsbmMissile
in sim/asbm.py (terminal ship-cone seeker ported from _acquire_lock). (4) ASBM SamDef + asbm_ammo config
+ clamp + test_combat_config. (5) world launch() 'asbm' branch (AsbmMissile on the contact estimate,
is_hostile=False) + _asbm_ammo pool. (6) B-cycle 4-way + request_launch asbm + HUD ASBM row + tactical
arc preview/ToF (UI; keep GL helpers pure-testable where the project does). (7) tests/test_asbm.py locked
to the MEASURED band. (8) Run: test_asbm.py, the duel (tests/test_sm2_statistics.py), full suite, smoke.
Report the measured profile + regression proof. BLOCKED if the airframe can't hit the profile honestly.`,
  { label: 'implement:M4-A-asbm', phase: 'Implement', schema: IMPL_SCHEMA }
)
log(`Implementer: ${impl ? impl.status : 'NULL'} — ${impl ? impl.measured_profile : ''}`)
if (!impl || impl.status === 'BLOCKED' || impl.status === 'NEEDS_CONTEXT') {
  return { halted: true, stage: 'implement', impl }
}

phase('Spec review')
const specReview = await agent(
`SPEC-COMPLIANCE reviewer for M4-A ASBM. DO NOT TRUST THE IMPLEMENTER. Re-read spec + the diff, RE-RUN the
tests + the flyoff probe yourself. Verify: the apogee/dive/Mach band is MEASURED (probe) not guessed and
the test locks the measured numbers (two-sided); the stale-track MISS vs fresh-track KILL pair proves a
physics miss (not a weakened tolerance); the high midcourse stays > SM6_AREA_MIN_ALT_M (counter intact);
fog (flies the contact estimate, truth only at the fuse); byte-identical (asbm_ammo=0 -> duel + full suite
+ smoke unchanged); no existing test weakened; determinism. Re-run tests/test_asbm.py
tests/test_sm2_statistics.py tests/test_combat_config.py + full suite + smoke.
${CONVENTIONS}
Implementer: ${impl.status}; measured=${impl.measured_profile}; regression=${impl.regression_note}
PASS only if every contract holds honestly. Concrete findings w/ file:line.`,
  { label: 'spec-review:M4-A-asbm', phase: 'Spec review', schema: REVIEW_SCHEMA }
)
log(`Spec review: ${specReview ? specReview.verdict : 'NULL'} (${specReview ? specReview.findings.length : 0}) — ${specReview ? specReview.reran_tests_output : ''}`)

if (specReview && specReview.verdict === 'FAIL' && specReview.findings.length) {
  phase('Spec fix')
  const fix = await agent(
`FIXER for M4-A ASBM. Fix ALL findings without weakening tests or touching the duel/determinism/byte-
identical contracts. Re-run test_asbm + duel + full suite + smoke + re-run the flyoff probe.
${CONVENTIONS}
FINDINGS:
${specReview.findings.map((f, i) => `${i + 1}. [${f.severity}] ${f.file}:${f.line} — ${f.issue}\n   FIX: ${f.required_fix}`).join('\n')}`,
    { label: 'spec-fix:M4-A-asbm', phase: 'Spec fix', schema: IMPL_SCHEMA }
  )
  log(`Spec fix: ${fix ? fix.status : 'NULL'}`)
  const recheck = await agent(
`Re-verify M4-A after the fixer: re-run tests/test_asbm.py tests/test_sm2_statistics.py + full suite +
smoke + the flyoff probe. Confirm the measured band holds + byte-identical. Report PASS/FAIL with counts.
${CONVENTIONS}`,
    { label: 'spec-recheck:M4-A-asbm', phase: 'Spec fix', schema: REVIEW_SCHEMA }
  )
  log(`Spec recheck: ${recheck ? recheck.verdict : 'NULL'}`)
  if (recheck && recheck.verdict === 'FAIL') return { halted: true, stage: 'spec-recheck', specReview, recheck }
}

phase('Quality review')
const qReview = await agent(
`CODE-QUALITY reviewer for M4-A ASBM (spec passed). Judge: AsbmMissile reuses SamMissile cleanly (no
copy-paste of the loft/fuse machine), the ported seeker shares logic with _acquire_lock rather than
duplicating, named tuning constants w/ comments (apogee/loft/dive), no dead code, tests verify the
physics (apogee/dive/stale-miss) not tautologies, the B-cycle/HUD stay consistent with the kh31p pattern.
Re-run test_asbm.py to confirm green. Findings w/ file:line.
${CONVENTIONS}`,
  { label: 'quality-review:M4-A-asbm', phase: 'Quality review', schema: REVIEW_SCHEMA }
)
log(`Quality review: ${qReview ? qReview.verdict : 'NULL'} (${qReview ? qReview.findings.length : 0})`)
if (qReview && qReview.verdict === 'FAIL' && qReview.findings.filter(f => f.severity !== 'MINOR').length) {
  phase('Quality fix')
  const qfix = await agent(
`FIXER for M4-A code-quality findings. Fix BLOCKER/MAJOR (MINOR where cheap) without changing behavior or
weakening tests. Re-run test_asbm + smoke.
${CONVENTIONS}
FINDINGS:
${qReview.findings.map((f, i) => `${i + 1}. [${f.severity}] ${f.file}:${f.line} — ${f.issue}\n   FIX: ${f.required_fix}`).join('\n')}`,
    { label: 'quality-fix:M4-A-asbm', phase: 'Quality fix', schema: IMPL_SCHEMA }
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
