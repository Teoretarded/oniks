export const meta = {
  name: 'm4b-swarm',
  description: 'M4-B: loitering-munition swarm with simultaneous time-on-target (compute_swarm_speeds + guarded _commanded_speed + SwarmPod + launch_swarm). implementer -> spec review -> fix -> quality review -> fix',
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
 - THE LOCKED CONTRACT: the _commanded_speed override in Missile._sustainer_thrust MUST be guarded so
   that when it is UNSET (None) the Mach-hold is byte-for-byte the existing path. The Oniks-vs-SM-2 duel
   (tests/test_sm2_statistics.py) + Oniks flight are LOCKED — they must stay bit-identical. A dedicated
   test_unset_commanded_speed_bit_identical pins an Oniks trajectory equal with/without the edit. If you
   cannot keep it bit-identical, STOP and report BLOCKED.
 - PHYSICS NOT DICE: saturation EMERGES from the enemy's existing in-flight caps (SM2_MAX_INFLIGHT=4 per
   ship + 3 s reload + single CIWS bubble) — a synchronized time-on-target puts more rounds in the
   terminal window than the defense can service, so leakers get through with NO kill roll. The
   simultaneous arrival is pure math: v_i = path_len_i / T, T = max_len/v_max + margin.
 - DETERMINISM: per-round weave seeded by salvo ordinal (deterministic); the speed-sync math is pure.
   No new RNG / wall-clock. Same seed -> identical.
 - REGRESSION / BYTE-IDENTICAL DEFAULT: SWARM is a NEW WeaponDef + NEW SWARM_POD launcher + NEW SwarmPod
   structure + NEW config fields (n_swarm_pods etc., default 0). With n_swarm_pods=0 the default battle
   is byte-identical (no pod built, launch_swarm never called).
 - PLAYER-ONLY (preserve asymmetry; the enemy does not field a swarm in v1).
 - NEVER weaken a test; BLOCKED if a contract can't pass honestly. STATUS: DONE/DONE_WITH_CONCERNS/
   BLOCKED/NEEDS_CONTEXT. Bad work is worse than no work.`

const ANCHORS = `
VERIFIED ANCHORS:
 - sim/missile.py:452 _sustainer_thrust(m_now, drag_ff, dt) — the Mach-hold. ADD optional
   self._commanded_speed=None in Missile.__init__; in _sustainer_thrust, if set, target the commanded
   GROUND speed (target_mach = commanded_speed / local_a) INSTEAD of cruise_mach — GUARDED so unset =
   the exact existing arithmetic (no reordering of the unset path). DESCENT_BASELINE_MACH @137 is the
   descent calibration; don't disturb it.
 - sim/arsenal.py:11 WeaponDef (ramjet cruise: Oniks/Zircon, cruise_mach_hi/lo). ADD a SWARM WeaponDef
   — small subsonic loiterer (cruise_mach_lo ~0.2-0.45, modest fuel for ~40 km, short seeker_range).
   :172 LauncherDef — ADD a SWARM_POD launcher (cells). Register in WEAPONS so render/logic resolve it.
 - NEW sim/swarm.py: compute_swarm_speeds(launch_pos, per_round_routes, v_max, margin) -> [v_i]
   (pure: path length via segment hypots, T = max_len/v_max + margin, v_i = len_i/T, clamp [v_min,v_max]).
   Headless-unit-testable.
 - world/combat.py:524 self.pantsirs (destructible-Structure + magazine + n_* config pattern) — MIRROR
   for SwarmPod structures + a _swarm_cells magazine. ADD launch_swarm(profile, aim_point, waypoints,
   sync) that spawns one Missile(SWARM,...) per ready cell, computes path lengths, derives the shared T
   + per-round commanded speed via compute_swarm_speeds, sets _commanded_speed on each (salvo ordinal
   seeds the weave so they don't formate), decrements the magazine by N.
 - sim/enemy_defense.py SM2_MAX_INFLIGHT=4 (the saturation counter — do NOT change it).
 - game/controls.py:41 PLATFORMS_COMBAT=("bastion","s300","drone") — ADD "swarm". ADD a
   swarm_arrival_mode bindable action (game/keybinds.py + controls.py).
 - game/tactical_map.py:453 add_waypoint — REUSE for the shared swarm route + aim point. ADD the swarm
   tasking panel (cells, TOT countdown, SYNC/MAX toggle, per-round speed bars, converging paths) as a
   PURE helper + a render method (keep the pure row-builder GL-free + FakeText-testable, per convention).
 - game/sandbox.py request_launch — ADD a swarm branch -> world.launch_swarm; TAB platform handling.
 - game/hud.py — ADD a swarm row (cells remaining, in-flight count) as a pure helper.
 - world/combat_config.py: ADD n_swarm_pods / swarm_cells_per_pod (or swarm_ammo) / swarm_mag_reload_s
   + CLAMPs + clamp_config + test_combat_config (all default 0).`

const TEST_CONTRACTS = `
WRITE tests FIRST (TDD). tools/probe_swarm_sync.py measures simultaneous arrival. tests/test_swarm.py:
 (1) test_compute_swarm_speeds_simultaneous: 3 rounds, different path lengths; flown at their v_i they
     all arrive within ~1 s of each other, AND the longest path runs at ~v_max, shorter paths slower.
 (2) test_commanded_speed_overrides_mach_hold: a Missile with _commanded_speed holds that GROUND speed
     in cruise (measured), not cruise_mach.
 (3) test_unset_commanded_speed_bit_identical (THE GUARD): an Oniks with no commanded speed flies the
     EXACT existing trajectory (bit-for-bit) — the regression guard on the _sustainer_thrust edit.
 (4) test_bundle_launch_fires_all_ready_cells: launch_swarm spawns N rounds, decrements the magazine by
     N, sets distinct salvo ordinals (weaves differ). Refuses on empty cells.
 (5) test_swarm_saturates_point_defense (e2e, mirror tests/test_phase6_e2e.py style): a SYNCHRONIZED
     N-round bundle vs one destroyer produces >= 1 leaker hit where a 4-round non-synced trickle does
     NOT — the saturation contract (leak emerges from SM2_MAX_INFLIGHT, no roll).
 (6) test_swarm_determinism: same seed + same tasking -> identical rounds/weaves.
 (7) byte-identical: n_swarm_pods=0 -> no pod, launch_swarm never invoked, duel + full suite + smoke
     unchanged.`

const IMPL_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['status', 'files_changed', 'tests_added', 'measured', 'bit_identical_note', 'concerns'],
  properties: {
    status: { type: 'string', enum: ['DONE', 'DONE_WITH_CONCERNS', 'BLOCKED', 'NEEDS_CONTEXT'] },
    files_changed: { type: 'array', items: { type: 'string' } },
    tests_added: { type: 'array', items: { type: 'string' } },
    measured: { type: 'string', description: 'Swarm-sync probe (arrival spread s, per-round speeds), saturation e2e leaker counts synced vs trickle, full suite + smoke.' },
    bit_identical_note: { type: 'string', description: 'Proof the unset _commanded_speed path is byte-identical + the Oniks duel + default battle unchanged.' },
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
`You are the IMPLEMENTER for M4-B: a loitering-munition swarm with coordinated time-on-target. The player
bundle-launches N small subsonic loiterers that reach one aim point SIMULTANEOUSLY by self-adjusting cruise
speed, saturating ship point-defense. TDD. The #1 risk is the _commanded_speed edit to the Oniks Mach-hold
— guard it so unset = bit-identical.

${CONVENTIONS}
${ANCHORS}
${TEST_CONTRACTS}

Build: (1) read sim/missile.py (_sustainer_thrust + __init__), sim/arsenal.py (WeaponDef/LauncherDef),
world/combat.py (Pantsir destructible+magazine pattern + launch), sim/enemy_defense.py (SM2_MAX_INFLIGHT),
game/controls.py (PLATFORMS_COMBAT), game/tactical_map.py (add_waypoint), game/sandbox.py (request_launch).
(2) WRITE tests/test_swarm.py (esp. the bit-identical guard) + tools/probe_swarm_sync.py FIRST. (3) sim/
swarm.py compute_swarm_speeds (pure). (4) Missile._commanded_speed (guarded override). (5) SWARM WeaponDef
+ SWARM_POD + SwarmPod structure + magazine + launch_swarm. (6) config fields + clamp + test_combat_config.
(7) swarm platform + arrival-mode key + request_launch + tasking panel (pure helper) + HUD row. (8) Run:
test_swarm.py, the duel, full suite, smoke; run the sync + saturation probes. Report measured numbers +
the bit-identical proof. BLOCKED if the guard can't hold the Oniks trajectory byte-for-byte.`,
  { label: 'implement:M4-B-swarm', phase: 'Implement', schema: IMPL_SCHEMA }
)
log(`Implementer: ${impl ? impl.status : 'NULL'} — ${impl ? impl.measured : ''}`)
if (!impl || impl.status === 'BLOCKED' || impl.status === 'NEEDS_CONTEXT') {
  return { halted: true, stage: 'implement', impl }
}

phase('Spec review')
const specReview = await agent(
`SPEC-COMPLIANCE reviewer for M4-B swarm. DO NOT TRUST THE IMPLEMENTER. Re-read spec + the diff, RE-RUN
tests + probes yourself. Verify above all the BIT-IDENTICAL GUARD: read the _sustainer_thrust edit line by
line and confirm the unset path is byte-for-byte the original; re-run tests/test_sm2_statistics.py (the
duel) + test_unset_commanded_speed_bit_identical. Verify the simultaneous-arrival math (probe: arrival
spread < ~1 s, longest path at v_max); the saturation e2e (synced bundle leaks where a trickle does not —
and it's the in-flight CAP, not a roll); determinism; byte-identical default (n_swarm_pods=0); no test
weakened. Re-run tests/test_swarm.py tests/test_sm2_statistics.py tests/test_combat_config.py + full suite
+ smoke.
${CONVENTIONS}
Implementer: ${impl.status}; measured=${impl.measured}; bit_identical=${impl.bit_identical_note}
PASS only if every contract holds. Concrete findings w/ file:line.`,
  { label: 'spec-review:M4-B-swarm', phase: 'Spec review', schema: REVIEW_SCHEMA }
)
log(`Spec review: ${specReview ? specReview.verdict : 'NULL'} (${specReview ? specReview.findings.length : 0}) — ${specReview ? specReview.reran_tests_output : ''}`)

if (specReview && specReview.verdict === 'FAIL' && specReview.findings.length) {
  phase('Spec fix')
  const fix = await agent(
`FIXER for M4-B swarm. Fix ALL findings without weakening tests or breaking the bit-identical Oniks guard /
duel / determinism. Re-run test_swarm + duel + full suite + smoke + the sync/saturation probes.
${CONVENTIONS}
FINDINGS:
${specReview.findings.map((f, i) => `${i + 1}. [${f.severity}] ${f.file}:${f.line} — ${f.issue}\n   FIX: ${f.required_fix}`).join('\n')}`,
    { label: 'spec-fix:M4-B-swarm', phase: 'Spec fix', schema: IMPL_SCHEMA }
  )
  log(`Spec fix: ${fix ? fix.status : 'NULL'}`)
  const recheck = await agent(
`Re-verify M4-B after the fixer: re-run tests/test_swarm.py tests/test_sm2_statistics.py + full suite +
smoke + the sync + saturation probes. Confirm the bit-identical guard + saturation contract. PASS/FAIL with
counts.
${CONVENTIONS}`,
    { label: 'spec-recheck:M4-B-swarm', phase: 'Spec fix', schema: REVIEW_SCHEMA }
  )
  log(`Spec recheck: ${recheck ? recheck.verdict : 'NULL'}`)
  if (recheck && recheck.verdict === 'FAIL') return { halted: true, stage: 'spec-recheck', specReview, recheck }
}

phase('Quality review')
const qReview = await agent(
`CODE-QUALITY reviewer for M4-B swarm (spec passed). Judge: compute_swarm_speeds is a clean pure function;
the _commanded_speed guard is minimal + obviously inert when unset; SwarmPod reuses the Pantsir
destructible pattern (not copy-paste); named tuning constants w/ comments; the tasking-panel pure helper is
GL-free + tested; no dead code; tests verify real behavior (simultaneous arrival, saturation leak) not
tautologies. Re-run test_swarm.py to confirm green. Findings w/ file:line.
${CONVENTIONS}`,
  { label: 'quality-review:M4-B-swarm', phase: 'Quality review', schema: REVIEW_SCHEMA }
)
log(`Quality review: ${qReview ? qReview.verdict : 'NULL'} (${qReview ? qReview.findings.length : 0})`)
if (qReview && qReview.verdict === 'FAIL' && qReview.findings.filter(f => f.severity !== 'MINOR').length) {
  phase('Quality fix')
  const qfix = await agent(
`FIXER for M4-B code-quality findings. Fix BLOCKER/MAJOR (MINOR where cheap) without changing behavior or
weakening tests. Re-run test_swarm + smoke.
${CONVENTIONS}
FINDINGS:
${qReview.findings.map((f, i) => `${i + 1}. [${f.severity}] ${f.file}:${f.line} — ${f.issue}\n   FIX: ${f.required_fix}`).join('\n')}`,
    { label: 'quality-fix:M4-B-swarm', phase: 'Quality fix', schema: IMPL_SCHEMA }
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
