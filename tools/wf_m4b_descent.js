export const meta = {
  name: 'm4b-swarm-descent-tuning',
  description: 'M4-B follow: per-weapon descent scaling so the SUBSONIC swarm actually splashes ships in a real lo-lo run (bit-identical Oniks/Zircon). probe-first; implementer -> spec review -> fix',
  phases: [
    { title: 'Implement' },
    { title: 'Spec review' },
    { title: 'Spec fix' },
  ],
}

const CONVENTIONS = `
ENV: Python 3.11, cwd = repo root "C:\\Users\\teoti\\OneDrive\\Desktop\\New folder\\oinks PROTO".
  Full suite: python -m pytest -q (~7 min). Smoke: python tools/smoke_combat.py (70/70 exit 0).
THE PROBLEM (diagnosed): sim/missile.py:320 self._descent_scale = max(1.0, weapon.cruise_mach_hi /
  DESCENT_BASELINE_MACH). The max(1.0,...) FLOOR forces a slower-than-Oniks weapon to use the full
  Oniks Mach-2.5 descent authority, so the SUBSONIC SWARM (cruise_mach_hi ~0.3-0.45) OVER-DIVES and
  hits the sea ~7 km short of a ship in a real lo-lo terminal. The swarm therefore cannot actually
  splash ships in play (the saturation e2e currently uses a dead-level _LevelSwarm stub to dodge this).
NON-NEGOTIABLES:
 - BIT-IDENTICAL Oniks + Zircon (LOCKED): the fix must leave Oniks (cruise_mach_hi 2.55) and Zircon
   (8.0) byte-for-byte unchanged. Removing/relaxing the floor is bit-identical for them ONLY if their
   computed _descent_scale is unchanged (2.55/2.55=1.0, 8.0/2.55=3.14 — both already >= 1.0, so the
   max() was a no-op for them). PROVE it: fly the locked Oniks hi-lo AND lo-lo shot + Zircon, byte-
   compare pos/vel/fuel/phase every substep vs pre-change. Re-run tests/test_sm2_statistics.py (duel)
   + tests/test_swarm.py::test_unset_commanded_speed_bit_identical. If ANY Oniks/Zircon bit drifts,
   the change is wrong — find a per-weapon gate that does not touch them.
 - PHYSICS NOT DICE: the swarm hit/miss still emerges from guidance+fuse; you are correcting the
   descent-authority SCALING for a subsonic airframe, measured by a probe — not adding a fudge.
 - DETERMINISM + BYTE-IDENTICAL DEFAULT preserved (n_swarm_pods=0 unaffected).
 - NEVER weaken a test. STATUS: DONE/DONE_WITH_CONCERNS/BLOCKED/NEEDS_CONTEXT.`

const TASK = `
GOAL: a REAL SWARM round (no _LevelSwarm forcing) flown lo-lo at a stationary ship SPLASHES it
(impacts within the fuse/seeker basket), while Oniks/Zircon stay bit-identical.

STEPS:
 1. Write tools/probe_swarm_descent.py: fly a REAL Missile(SWARM, ...) lo-lo from the coast at a
    stationary ship at a few ranges (e.g. 25/35/45 km). Print closest-approach-to-hull + impact range
    for SEVERAL candidate descent-scale schemes (current floored; floor removed = ratio; a subsonic
    baseline; etc.). MEASURE which scheme lands the round on the hull at sea-skim without overflying.
 2. Pick the scheme from the MEASURED numbers. Likely: drop the max(1.0,...) floor so the scale is the
    raw ratio (gentle dive for the slow round) — OR a clamped per-weapon scheme — whichever the probe
    shows reaches the hull. Apply it in sim/missile.py, GUARDED so Oniks/Zircon are byte-identical.
 3. Add tests/test_swarm.py::test_swarm_round_splashes_ship_in_lo_lo (a REAL SWARM Missile, NO
    _LevelSwarm, flown via m.update() at a static ship -> ship hit / closest < fuse radius). This is the
    proof the weapon actually works end-to-end.
 4. UPGRADE the saturation test (test_swarm_saturates_point_defense): if a real SWARM round now flies
    the terminal honestly, replace the _LevelSwarm stub with REAL SWARM rounds so the saturation is
    demonstrated on the real airframe. If the real terminal still can't be made reliable at sea-skim
    for the multi-round geometry, KEEP the documented stub but add the new single-round real-splash
    test (3) as the end-to-end lethality proof, and say so honestly.
 5. Verify: tools/probe_swarm_descent.py numbers; tests/test_swarm.py; the Oniks/Zircon bit-identical
    proof + tests/test_sm2_statistics.py; full suite; smoke. Report the measured before/after.`

const IMPL_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['status', 'files_changed', 'measured_before_after', 'bit_identical_proof', 'splashes_ship', 'concerns'],
  properties: {
    status: { type: 'string', enum: ['DONE', 'DONE_WITH_CONCERNS', 'BLOCKED', 'NEEDS_CONTEXT'] },
    files_changed: { type: 'array', items: { type: 'string' } },
    measured_before_after: { type: 'string', description: 'Probe: swarm closest-approach/impact before vs after, per scheme; the chosen scale.' },
    bit_identical_proof: { type: 'string', description: 'How Oniks+Zircon were proven byte-identical (sample counts).' },
    splashes_ship: { type: 'string', description: 'Does a REAL SWARM round now hit a ship in lo-lo? closest/impact numbers. Did the saturation test move to real rounds?' },
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
`You are the IMPLEMENTER for the M4-B swarm descent-tuning. Make a REAL subsonic SWARM round actually
splash ships in a lo-lo run by correcting the descent-authority scaling, WITHOUT changing Oniks/Zircon by
one bit. MEASURE with a probe first.
${CONVENTIONS}
${TASK}
Report the measured before/after, the bit-identical proof, and whether a real SWARM round now hits a ship.
If no descent scheme makes it reach the hull honestly, report DONE_WITH_CONCERNS (keep the stubbed
saturation test + the real single-round test as far as it gets) — do NOT fake a hit.`,
  { label: 'implement:M4-B-descent', phase: 'Implement', schema: IMPL_SCHEMA }
)
log(`Implementer: ${impl ? impl.status : 'NULL'} — splashes: ${impl ? impl.splashes_ship : ''}`)
if (!impl || impl.status === 'BLOCKED' || impl.status === 'NEEDS_CONTEXT') {
  return { halted: true, stage: 'implement', impl }
}

phase('Spec review')
const specReview = await agent(
`SPEC-COMPLIANCE reviewer for the M4-B swarm descent-tuning. DO NOT TRUST THE IMPLEMENTER. Re-run the
descent probe + tests. VERIFY ABOVE ALL the BIT-IDENTICAL guard: independently fly the locked Oniks hi-lo
AND lo-lo shot + Zircon under the changed code and byte-compare against HEAD (extract the pre-change
sim/missile.py from git if needed) — confirm 0 drift; re-run tests/test_sm2_statistics.py. Verify a REAL
SWARM round (no _LevelSwarm stub) now hits a ship at sea-skim (or that the implementer honestly reported it
can't and kept the stub + the real single-round test). Verify physics-not-dice (no fudge), determinism,
byte-identical default, no test weakened. Re-run tests/test_swarm.py + full suite + smoke.
${CONVENTIONS}
Implementer: ${impl.status}; before/after=${impl.measured_before_after}; bitid=${impl.bit_identical_proof}; splashes=${impl.splashes_ship}
PASS only if Oniks/Zircon are byte-identical AND the swarm lethality claim is honestly substantiated.`,
  { label: 'spec-review:M4-B-descent', phase: 'Spec review', schema: REVIEW_SCHEMA }
)
log(`Spec review: ${specReview ? specReview.verdict : 'NULL'} (${specReview ? specReview.findings.length : 0}) — ${specReview ? specReview.reran_tests_output : ''}`)

if (specReview && specReview.verdict === 'FAIL' && specReview.findings.length) {
  phase('Spec fix')
  const fix = await agent(
`FIXER for the M4-B descent-tuning. Fix ALL findings without breaking the Oniks/Zircon bit-identical guard
or weakening tests. Re-run the descent probe + test_swarm + duel + full suite + smoke.
${CONVENTIONS}
FINDINGS:
${specReview.findings.map((f, i) => `${i + 1}. [${f.severity}] ${f.file}:${f.line} — ${f.issue}\n   FIX: ${f.required_fix}`).join('\n')}`,
    { label: 'spec-fix:M4-B-descent', phase: 'Spec fix', schema: IMPL_SCHEMA }
  )
  log(`Spec fix: ${fix ? fix.status : 'NULL'} — splashes: ${fix ? fix.splashes_ship : ''}`)
  const recheck = await agent(
`Re-verify the M4-B descent-tuning after the fixer: re-run the descent probe + tests/test_swarm.py +
tests/test_sm2_statistics.py + full suite + smoke. Confirm Oniks/Zircon byte-identical + the swarm
lethality claim. PASS/FAIL with counts.
${CONVENTIONS}`,
    { label: 'spec-recheck:M4-B-descent', phase: 'Spec fix', schema: REVIEW_SCHEMA }
  )
  log(`Spec recheck: ${recheck ? recheck.verdict : 'NULL'}`)
  if (recheck && recheck.verdict === 'FAIL') return { halted: true, stage: 'spec-recheck', specReview, recheck }
}

return {
  done: true, implementer: impl,
  spec_verdict: specReview ? specReview.verdict : null,
  spec_findings: specReview ? specReview.findings : [],
}
