export const meta = {
  name: 'm5-ship-classes',
  description: 'M5: enemy ship-class taxonomy (GroundAttack/AirDefense/General/Flagship + Carrier integration) + CEC datalink-hub degradation + fleet-composition mixer. All counts default 0 -> byte-identical. implementer -> spec review -> fix -> quality review -> fix',
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
 - BYTE-IDENTICAL DEFAULT (THE GATE): all new CombatConfig counts default 0 (n_flagship=0, n_aaw=0,
   n_ground_attack=0). With those 0 the fleet mixer must produce EXACTLY today's fleet (1 carrier +
   n_destroyers GENERAL destroyers) in the IDENTICAL placement, so sample_fleet's LOCKED tests
   (deterministic / open-water / 25km-separation / sector), the Oniks-vs-SM-2 duel, the smoke
   determinism check, and the default battle ALL stay bit-identical. Prove it with a multi-thousand-step
   same-seed digest (default config) == pre-change. LOCKED schema -> sign-off granted on the 0-default
   condition; add CLAMP_* + clamp_config + test_combat_config for every new field.
 - FOG / NO CHEAT: ship class is INVISIBLE on the player contact board until imaged (no class field
   leaks pre-imaging). The flagship CEC degradation is a SENSOR-honest nerf — escorts lose REMOTE CUE
   (cue_radars_fn drops the dead hub) so they fall back to own-SPY-1; NEVER reads player truth. The
   commander/defense read only EnemyPicture/tracks.
 - PHYSICS NOT DICE: kills stay via the existing OBB/fuse + SamMissile guidance noise. No new rolls.
 - DETERMINISM: ship-class placement jitter (if any) uses a FRESH child stream [seed, 9] (3..8 + 12
   are taken). No wall-clock.
 - enemy_defense.py edit MUST keep the fallback: read getattr(ship,'sm2_max_inflight',SM2_MAX_INFLIGHT)
   and getattr(ship,'_track_form_s',TRACK_FORM_S) so existing enemy_defense tests stay green.
 - Keep new classes in a NEW sim/enemy_ship_classes.py (do not disturb enemy_ships.py's locked tests).
 - NEVER weaken a test. STATUS: DONE/DONE_WITH_CONCERNS/BLOCKED/NEEDS_CONTEXT. Bad work is worse than none.`

const ANCHORS = `
VERIFIED ANCHORS:
 - sim/enemy_ships.py:110 class Destroyer(Ship) (SPY-1 + per-channel magazines sm2/sm6/ciws/tomahawk);
   sim/enemy_air.py:399 class Carrier(Destroyer) (silent, HP6, AirBase, zero offensive ammo) + SHIP_TYPES
   registration pattern (:59 SHIP_TYPES["carrier"]). NEW sim/enemy_ship_classes.py: a frozen ShipClassDef
   (role, sm2/sm6/ciws/tomahawk ammo, sm2_max_inflight, hp, dims, radar_missile_range, is_datalink_hub)
   + GroundAttackShip / AirDefenseShip / GeneralDestroyer(=today's Destroyer params) / Flagship subclasses,
   consumed in __init__ (mirror how Carrier overrides via SHIP_TYPES). Register SHIP_TYPES entries for
   any new dims/HP.
 - sim/enemy_defense.py: SM2_MAX_INFLIGHT=82-line const + TRACK_FORM_S(:81) + ShipDefense(cue_radars_fn)
   (:259, :293 _detects uses the cue set) + EnemyDefenseController(:663). Read ship.sm2_max_inflight via
   getattr (fallback to the const) in _try_sm2_launch (:406). ADD an optional per-unit cohesion/
   _track_form_s knob (default = TRACK_FORM_S so existing tests unchanged) the controller lowers when
   the hub dies (raises effective TRACK_FORM_S).
 - world/combat.py:821 _spawn_ships, :1307 _enemy_cue_radars (today returns AWACS + ground radars — ADD
   the live flagship radar; when no flagship alive return the degraded set), :1818 _fire_tomahawk_salvo
   (sort so GroundAttack TLAM banks drain FIRST). Add self.flagship ref; on flagship death bump escort
   cohesion + emit a 'datalink_degraded' event.
 - world/spawn_zones.py:100 sample_fleet(rng, n_destroyers, ...) — GENERALIZE to a typed roster
   {carrier, flagship, aaw:[...], ground_attack:[...], general:[...], transports:[...]} keeping the
   DEFAULT (only carrier + n_destroyers general; other roles empty) BYTE-IDENTICAL to today's output.
   Bands: carrier+flagship deep/central, aaw forward (toward ZONE_RANGE_MIN), ground_attack mid, general
   fill. Keep open-water(9km) + MIN_SEPARATION(25km) + determinism. (transports band exists but
   n_transports=0 here — amphibious is a later feature.)
 - world/combat_config.py: ADD n_flagship(0/1)/n_aaw/n_ground_attack + CLAMPs + clamp_config + tests.`

const TEST_CONTRACTS = `
TDD. Probe the flagship CEC magnitude before locking. Contracts (spec 05):
 (a) tests/test_ship_classes.py: each class instantiates with its def's ammo/hp/dims; class identity is
     fog-gated (no class field on the contact board until imaged).
 (b) tests/test_air_defense_ship.py: an AAW ship sustains MORE concurrent SM-2 than a general destroyer
     in the same raid (count inflight); lo-lo Oniks still leaks at the spec band against it (multipath
     unchanged — balance guard).
 (c) tests/test_ground_attack_ship.py: a GroundAttack ship's TLAM bank drains FIRST in a salvo (ammo
     accounting); salvo fires ONLY at a back-plot cluster (fog).
 (d) tests/test_flagship.py: flagship alive -> an escort forms an SM-2 track via the flagship/AWACS cue
     before its OWN SPY-1 has LOS (launch occurs); flagship dead -> SAME geometry yields NO remote-cued
     launch (own-sensor fallback) AND escort effective TRACK_FORM_S rises; NO-TRUTH (mock the player
     where the flagship cannot detect -> no cue); determinism replay bit-identical.
 (e) tests/test_spawn_zones.py (extend): typed roster keys; carrier/flagship deep, aaw forward,
     transports rear; all hulls open-water + >=25km separated for any mix; deterministic; 0 of a role ->
     empty list; **DEFAULT (no new classes) byte-identical to today's sample_fleet output.**
 (f) tests/test_combat_config.py: new counts default 0; clamp_config round-trips them.
 (g) REGRESSION: default config -> duel + full suite + smoke bit-identical (digest proof).`

const IMPL_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['status', 'files_changed', 'tests_added', 'measured', 'byte_identical_note', 'concerns'],
  properties: {
    status: { type: 'string', enum: ['DONE', 'DONE_WITH_CONCERNS', 'BLOCKED', 'NEEDS_CONTEXT'] },
    files_changed: { type: 'array', items: { type: 'string' } },
    tests_added: { type: 'array', items: { type: 'string' } },
    measured: { type: 'string', description: 'AAW more-inflight numbers; GroundAttack drain-first; flagship-alive-vs-dead remote-cue + TRACK_FORM_S delta (measured); full suite + smoke.' },
    byte_identical_note: { type: 'string', description: 'Proof the default config (all new counts 0) keeps sample_fleet + the default battle + duel bit-identical (digest).' },
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
`You are the IMPLEMENTER for M5 enemy ship classes: turn the homogeneous "2 Destroyers + 1 Carrier" fleet
into a doctrinally varied task group (GroundAttack / AirDefense / General / Flagship + the existing
Carrier), with the Flagship as a CEC datalink hub whose DEATH degrades the fleet (sensor-honest), and a
fleet-composition mixer. ALL new counts default 0 -> the default battle stays byte-identical. TDD.
${CONVENTIONS}
${ANCHORS}
${TEST_CONTRACTS}
Build: (1) read sim/enemy_ships.py (Destroyer), sim/enemy_air.py (Carrier + SHIP_TYPES), sim/enemy_defense.py
(ShipDefense/cue_radars_fn/SM2_MAX_INFLIGHT/TRACK_FORM_S), world/combat.py (_spawn_ships/_enemy_cue_radars/
_fire_tomahawk_salvo), world/spawn_zones.py (sample_fleet). (2) Write the test files FIRST. (3) NEW
sim/enemy_ship_classes.py (ShipClassDef + 4 subclasses + registry). (4) enemy_defense getattr edits
(fallback-preserving). (5) world wiring: typed mixer (default byte-identical), _spawn_ships per role,
flagship cue gating + cohesion-on-death + event, TLAM-drain ordering. (6) config counts + clamp + tests.
(7) Run the new tests + the duel + full suite + smoke; prove the default-config digest is byte-identical.
Report measured numbers + the byte-identical proof. DEFER any new ship MESHES (a later model pass —
classes can reuse the existing destroyer mesh). BLOCKED if the default can't stay byte-identical.`,
  { label: 'implement:M5-shipclasses', phase: 'Implement', schema: IMPL_SCHEMA }
)
log(`Implementer: ${impl ? impl.status : 'NULL'} — ${impl ? impl.measured : ''}`)
if (!impl || impl.status === 'BLOCKED' || impl.status === 'NEEDS_CONTEXT') {
  return { halted: true, stage: 'implement', impl }
}

phase('Spec review')
const specReview = await agent(
`SPEC-COMPLIANCE reviewer for M5 ship classes. DO NOT TRUST THE IMPLEMENTER. Re-read spec + the diff,
RE-RUN tests yourself. VERIFY ABOVE ALL the BYTE-IDENTICAL DEFAULT: independently digest a default-config
battle (all new counts 0) over thousands of steps and confirm it equals pre-change HEAD (and that
sample_fleet's default output is unchanged + its locked tests pass + the duel passes). Verify: AAW
sustains more SM-2 (measured); GroundAttack drains first; the flagship CEC mechanic is SENSOR-HONEST and
MEASURED (alive->remote cue, dead->no cue + TRACK_FORM_S up, no-truth mock); class identity is fog-gated;
enemy_defense getattr keeps the fallback (existing tests green); determinism ([seed,9]); no test weakened.
Re-run tests/test_ship_classes.py test_flagship.py test_air_defense_ship.py test_ground_attack_ship.py
test_spawn_zones.py tests/test_sm2_statistics.py tests/test_combat_config.py + full suite + smoke.
${CONVENTIONS}
Implementer: ${impl.status}; measured=${impl.measured}; byteid=${impl.byte_identical_note}
PASS only if every contract holds — especially byte-identical default. Findings w/ file:line.`,
  { label: 'spec-review:M5-shipclasses', phase: 'Spec review', schema: REVIEW_SCHEMA }
)
log(`Spec review: ${specReview ? specReview.verdict : 'NULL'} (${specReview ? specReview.findings.length : 0}) — ${specReview ? specReview.reran_tests_output : ''}`)

if (specReview && specReview.verdict === 'FAIL' && specReview.findings.length) {
  phase('Spec fix')
  const fix = await agent(
`FIXER for M5 ship classes. Fix ALL findings without weakening tests or breaking the byte-identical
default / duel / no-cheat. Re-run the ship-class tests + spawn_zones + duel + full suite + smoke + the
default digest.
${CONVENTIONS}
FINDINGS:
${specReview.findings.map((f, i) => `${i + 1}. [${f.severity}] ${f.file}:${f.line} — ${f.issue}\n   FIX: ${f.required_fix}`).join('\n')}`,
    { label: 'spec-fix:M5-shipclasses', phase: 'Spec fix', schema: IMPL_SCHEMA }
  )
  log(`Spec fix: ${fix ? fix.status : 'NULL'}`)
  const recheck = await agent(
`Re-verify M5 ship classes after the fixer: re-run the ship-class + spawn_zones + duel + combat_config
tests + full suite + smoke + the default-config digest. Confirm byte-identical default + the flagship
mechanic + AAW/GroundAttack behaviors. PASS/FAIL with counts.
${CONVENTIONS}`,
    { label: 'spec-recheck:M5-shipclasses', phase: 'Spec fix', schema: REVIEW_SCHEMA }
  )
  log(`Spec recheck: ${recheck ? recheck.verdict : 'NULL'}`)
  if (recheck && recheck.verdict === 'FAIL') return { halted: true, stage: 'spec-recheck', specReview, recheck }
}

phase('Quality review')
const qReview = await agent(
`CODE-QUALITY reviewer for M5 ship classes (spec passed). Judge: ShipClassDef is a clean frozen registry;
subclasses share the Destroyer machine (no copy-paste); the mixer generalization is DRY and the default
path is obviously byte-identical; the flagship cohesion knob is minimal + inert by default; enemy_defense
getattr edits preserve the fallback cleanly; named constants; no dead code; tests verify measured behavior
not tautologies; fog (class hidden until imaged) is real. Re-run the ship-class tests. Findings w/ file:line.
${CONVENTIONS}`,
  { label: 'quality-review:M5-shipclasses', phase: 'Quality review', schema: REVIEW_SCHEMA }
)
log(`Quality review: ${qReview ? qReview.verdict : 'NULL'} (${qReview ? qReview.findings.length : 0})`)
if (qReview && qReview.verdict === 'FAIL' && qReview.findings.filter(f => f.severity !== 'MINOR').length) {
  phase('Quality fix')
  const qfix = await agent(
`FIXER for M5 ship-classes code-quality findings. Fix BLOCKER/MAJOR (MINOR where cheap) without changing
behavior or weakening tests. Re-run the ship-class tests + smoke.
${CONVENTIONS}
FINDINGS:
${qReview.findings.map((f, i) => `${i + 1}. [${f.severity}] ${f.file}:${f.line} — ${f.issue}\n   FIX: ${f.required_fix}`).join('\n')}`,
    { label: 'quality-fix:M5-shipclasses', phase: 'Quality fix', schema: IMPL_SCHEMA }
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
