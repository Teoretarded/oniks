export const meta = {
  name: 'm5-amphibious-beachhead',
  description: 'M5 #1: amphibious landing force (Transport hulls + LCAC craft) + a TIMED beachhead lose-path orthogonal to "TELs destroyed". n_transports=0 byte-identical. implementer -> spec review -> fix -> quality review -> fix',
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
  Commit per task with a conventional message; NEVER touch git main. Work on branch feat/combat-expansion.
NON-NEGOTIABLES (this game stays good only if every one holds):
 - BYTE-IDENTICAL DEFAULT (THE GATE): new CombatConfig fields n_transports (default 0) + beachhead_grace_s
   (a positive default is fine — the timer only ever starts when an LCAC reaches the box, which CANNOT
   happen at n_transports=0). With n_transports=0: NO transport/LCAC is built, self.transports + self.lcacs
   are empty, _step_amphibious is a pure no-op, defeated is unchanged (only the bastion_tel clause can trip),
   victorious is unchanged, and the default battle + Oniks-vs-SM-2 duel (tests/test_sm2_statistics.py) +
   determinism stay BIT-IDENTICAL. PROVE it with a same-seed multi-thousand-step state digest == pre-change
   HEAD. The CombatConfig schema is LOCKED: sign-off is GRANTED for these two fields ON the 0/OFF-default
   condition; you MUST add CLAMP_TRANSPORTS + CLAMP_BEACHHEAD_GRACE (floor 0 so the default survives a
   clamp_config round-trip) + the clamp_config kwargs + tests/test_combat_config.py rows.
 - FOG / NO CHEAT: the enemy commander's amphibious sequencing (sim/commander.py _doctrine_amphibious or the
   world hook that releases the transports) reads ONLY the sensor-only EnemyPicture (believed base state /
   missile tracks / clusters) to decide WHEN to order TRANSPORT_RUN — NEVER a live player-TEL/missile truth
   read. It must be deterministic. The beachhead LOSE-check itself is a world-OUTCOME rule and MAY read sim
   truth (exactly like the existing defeated/victorious properties — only the AI BRAIN is forbidden truth).
   The player's AWARENESS is fog-gated: transports + LCACs are ordinary surface entities the existing
   RadarNetwork horizon/terrain-LOS + drone SAR pipeline detects — an un-imaged landing force is a fair
   surprise, NOT a cheat. Transports/LCACs carry NO radar -> emit nothing -> ELINT NEVER hears them
   (mirrors the carrier running dark); they are found by radar/SAR only. Guard with a test.
 - PHYSICS NOT DICE: a transport/LCAC dies from the EXISTING OBB/fuse damage sweep when an Oniks / Pantsir
   gun round crosses its hull (no kill roll). The LCAC being "hard to catch close in" EMERGES from its
   small radar_size class shortening the radar horizon (Radar.detects geometry) — NOT a probability flag.
   "Landing" is a geometric event: an LCAC whose pos enters the LANDING_BOX radius. The beachhead countdown
   is a deterministic clock.
 - WIN/LOSE POLICY (LOCKED for this feature — spec 05 open-Q1/Q6 resolved): (a) transports AND LCACs live in
   self.ships, so they COUNT toward victorious (you must sink the landing force to WIN — ships-count-for-win);
   (b) SEPARATELY, the first LCAC to reach the LANDING_BOX starts a beachhead grace timer; if the player does
   NOT clear ALL committed craft (every alive transport+LCAC of the landing force) before it expires, defeated
   trips with cause='beachhead'; killing them all before expiry CANCELS the loss (a real save). defeated keeps
   its bastion_tel clause and ORs the beachhead-expiry case. Add a defeat_cause property ('bastion' | 'beachhead'
   | None) so the HUD can pick the banner. n_transports=0 -> defeated only on TELs (the regression).
 - DETERMINISM: transports place via the EXISTING fleet stream (world/spawn_zones.sample_fleet already draws
   the n_transports rear band on [seed,3] AFTER every legacy + M5 draw -> 0 is byte-identical). Any NEW jitter
   (LCAC splash scatter, run timing) uses a FRESH child stream tag [seed, 15] the world owns. Tags 3-8, 12, 13,
   14 are TAKEN and 9(CBR)/10(decoys)/11(relocate) are RESERVED — do NOT reuse any of them; use 15. No wall-clock.
 - REGRESSION NEVER WEAKENED: if a planned test cannot pass honestly, report BLOCKED — never widen a tolerance,
   weaken an assertion, or delete a case.
 - DEFER UI + meshes: transports/LCACs render as map-only glyphs falling back to existing ship meshes; the HUD
   beachhead countdown + cause-specific DEFEAT banner are DEFERRED to the later UI-wiring pass. BUT the pure
   world-state helpers (beachhead_active, beachhead_left, defeat_cause, the objective tallies) ARE headless-
   testable now and MUST be covered. game/* import pygame at top (untestable headless) — keep ALL new logic in
   world/ + sim/ (GL-free) so it is unit-tested.
 STATUS protocol: DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT. Bad work is worse than no work.`

const ANCHORS = `
VERIFIED ANCHORS (read these before writing code; line numbers approximate — confirm by reading):
 - world/spawn_zones.py sample_fleet(...) ALREADY accepts n_transports and draws the TRANSPORT rear band
   (TRANSPORT_RANGE_*; ~lines 100-216) AFTER the legacy + flagship/aaw/ground_attack draws, returning
   layout['transports']=[(x,z)...]. The byte-identical draw order is LOCKED by tests/test_spawn_zones.py — do
   NOT reorder it. The TODO at ~line 110 says n_transports is "intentionally UNWIRED" pending this feature;
   wiring it is YOUR job. (No spawn_zones change needed unless a test demands it — it is already scaffolded.)
 - sim/enemy_ship_classes.py _ClassedDestroyer: the EXACT pattern for a Transport hull — subclass Destroyer,
   overwrite dims/HP from a SHIP_TYPES entry, recompute hit_reach with the SAME formula, set per-unit knobs.
   Register SHIP_TYPES['transport'] (a slow ~11 m/s LHD-class hull, modest HP, light/zero self-defense:
   sm2/sm6/tomahawk small or 0). Transport adds: launch_line geometry, embarked_lcac count, a nav/posture
   state (LOITER -> RUN -> at launch line SPLASH). Reuse the Destroyer racetrack for LOITER and a straight
   beeline-to-launch-line for RUN.
 - sim/submarine.py (the M5 sub) + world/combat.py _step_subs (~1272) / _fire_kalibr_salvo (~1293) /
   _spawn_subs (~975): the CLEANEST end-to-end template for "a new threat platform stepped each tick that
   spawns sub-entities and is wired byte-identically behind a count=0 gate". Mirror its structure for the
   amphibious layer. The Submarine is NOT in self.ships (invisible) — TRANSPORTS/LCACs are the OPPOSITE: they
   ARE in self.ships (visible surface contacts). That is the key divergence.
 - world/combat.py _spawn_ships (~911): pass n_transports into sample_fleet; instantiate Transport hulls from
   layout['transports'] and append them to the returned ships list (-> self.ships). 0 transports => no append
   => byte-identical. Give each Transport a heading toward BASE_POS via the local _heading() helper.
 - world/combat.py step (~3058): add self._step_amphibious(dt) — place it alongside the M5 _step_subs call
   (after super().step()/_step_drones, before the strikes/defense or right after _step_subs) so an LCAC
   splashed this tick joins self.ships and is stepped on the NEXT base step (the established reactive
   convention). LCACs are damaged by the SAME base ship-vs-missile OBB sweep that kills destroyers (they are
   Ships) — confirm by reading how super().step() / damage.py applies missile hits to self.ships.
 - world/combat.py defeated (~2305) + victorious (~2313): extend defeated to OR the beachhead-expiry case
   (keep the bastion_tel clause); transports/LCACs are in self.ships so victorious already requires them dead
   (it ANDs "all(not s.alive for s in self.ships)") — verify that and add the test. Add defeat_cause.
 - sim/commander.py _doctrine_defend/_doctrine_blind/_doctrine_kill (~714/1081/1136) + process_missile_track
   (~1276): the commander reasons ONLY from self.picture (EnemyPicture). Add the amphibious release trigger
   here (or a small world-side sensor-only hook) — sensor belief in, TRANSPORT_RUN order out. Keep
   process_missile_track BIT-IDENTICAL.
 - world/combat_config.py: CombatConfig (LOCKED frozen schema) + CLAMP_* constants + clamp_config(...) +
   DEFAULT. Add n_transports (default 0) + beachhead_grace_s (e.g. 180.0) following the n_subs pattern EXACTLY
   (CLAMP_TRANSPORTS=(0,3) like CLAMP_SUBS; CLAMP_BEACHHEAD_GRACE with floor 0). tests/test_combat_config.py
   covers the round-trip.
 - tools/probe_*.py (e.g. tools/compare_s300_rounds.py): the probe idiom. Write tools/probe_amphibious.py to
   MEASURE the transport->launch-line ETA, the LCAC->box ETA, and the LANDING_BOX/launch-line geometry BEFORE
   locking the timing tests, and to confirm an Oniks/Pantsir-gun OBB hit kills an LCAC.`

const TEST_CONTRACTS = `
TDD: write the test files + tools/probe_amphibious.py FIRST; watch them fail for the right reason; implement;
watch them pass. Lock any timing/geometry band TWO-SIDED from the probe's measured numbers (never guessed).
Contracts (spec 05 "Amphibious transport class + LCAC" + "Amphibious landing as a TIMED lose condition"):
 ENTITIES (tests/test_amphibious.py):
  - a Transport reaching its launch line SPLASHES exactly LCAC_PER_TRANSPORT Lcac entities at the transport pos;
  - sinking a Transport BEFORE it reaches the line removes its embarked LCACs (they NEVER spawn);
  - a spawned Lcac beelines toward the LANDING_BOX and is killed by an Oniks OR Pantsir-gun OBB hit (hp=1);
  - transports + LCACs are NOT emitters: ELINT/_emitters never lists them; they appear on the contact board
    ONLY via radar/SAR detection (fog), and an LCAC's small radar_size shortens its detection horizon vs a
    transport (physics, measured in the probe);
  - determinism: same seed -> same launch line, same box approach, same splash scatter ([seed,15]).
 OBJECTIVE / LOSE (tests/test_amphibious_objective.py):
  - an Lcac entering the LANDING_BOX sets beachhead_active True and starts beachhead_left counting down;
  - killing ALL committed craft (transports + LCACs) before expiry sets beachhead_active False and CANCELS the
    loss (defeated stays False on the amphibious clause);
  - letting beachhead_left reach 0 sets defeated True with defeat_cause == 'beachhead';
  - a TEL-only defeat still yields defeat_cause == 'bastion';
  - victorious requires the transports + LCACs dead (ships-count-for-win) — alive landing force => not victorious
    even with all other hulls/airfield/radars dead;
  - REGRESSION: n_transports=0 reproduces today EXACTLY — defeated trips only on the bastion_tel clause; a
    same-seed multi-thousand-step digest == pre-change HEAD (the byte-identical gate);
  - the commander orders TRANSPORT_RUN only from its sensor picture (mock a geometry where the picture lacks the
    trigger -> no run; supply the believed trigger -> run) — NO truth read; determinism.
 CONFIG (tests/test_combat_config.py): clamp_config round-trips n_transports + beachhead_grace_s; the OFF
  default (n_transports=0) survives the setup-default clamp path.
 REGRESSION: n_transports=0 -> default battle + duel + full suite + smoke bit-identical (digest); tests/
  test_spawn_zones.py stays green (the transport band was already scaffolded).`

const IMPL_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['status', 'files_changed', 'tests_added', 'measured', 'byte_identical_note', 'concerns'],
  properties: {
    status: { type: 'string', enum: ['DONE', 'DONE_WITH_CONCERNS', 'BLOCKED', 'NEEDS_CONTEXT'] },
    files_changed: { type: 'array', items: { type: 'string' } },
    tests_added: { type: 'array', items: { type: 'string' } },
    measured: { type: 'string', description: 'Probe numbers: transport->line ETA, LCAC->box ETA, LANDING_BOX geometry, Oniks/Pantsir OBB-kill of an LCAC, LCAC vs transport detection horizon; full suite + smoke counts.' },
    byte_identical_note: { type: 'string', description: 'Proof n_transports=0 keeps the default battle + duel bit-identical (digest method + result); transports/LCACs never appear in any emitter/ELINT path.' },
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
`You are the IMPLEMENTER for M5 #1 — the AMPHIBIOUS landing force + a TIMED beachhead lose-path. This adds a
SECOND way to lose, orthogonal to "all TELs destroyed": slow Transport hulls run a beeline to an offshore
launch line, splash fast LCAC landing craft, and the LCACs sprint to a coast landing box near the player base;
if a landing force gets ashore and is not cleared in time, the beachhead overruns the Bastion and the player
loses. Build the WHOLE loop so it is always counter-able (sink transports far out, or kill leaking LCACs before
the grace timer). n_transports=0 keeps everything OFF and byte-identical. TDD; measure geometry/timing with a
probe before locking bands.
${CONVENTIONS}
${ANCHORS}
${TEST_CONTRACTS}
Build order: (1) sim/amphibious.py — Transport(Destroyer subclass: SHIP_TYPES['transport'], slow, light
self-defense, launch_line + embarked_lcac + LOITER/RUN/SPLASH state) + Lcac (minimal Ship subclass: pos/vel/
heading/state, hp=1, OBB, no weapons, beeline-to-box) + named geometry/timing constants (LANDING_BOX center+
radius near BASE_POS, launch-line offshore distance, TRANSPORT_SPEED, LCAC_SPEED, LCAC_PER_TRANSPORT,
BEACHHEAD_GRACE_S). (2) world/combat.py — wire n_transports through _spawn_ships (Transport hulls into
self.ships); a self.lcacs OR keep LCACs in self.ships (per the WIN/LOSE policy — both in self.ships);
_step_amphibious(dt) stepping transports (LOITER->RUN on the commander's sensor-only release; SPLASH at the
line) + LCACs (beeline the box) + beachhead bookkeeping; beachhead_active/beachhead_left/defeat_cause
properties; extend defeated (OR beachhead-expiry, keep bastion clause); confirm victorious requires the
landing force dead; hook step(). (3) sim/commander.py — the sensor-only TRANSPORT_RUN trigger. (4)
world/combat_config.py — n_transports + beachhead_grace_s + CLAMPs + clamp_config + DEFAULT. (5) tests +
tools/probe_amphibious.py FIRST. Run all new tests + the duel + full suite + smoke; PROVE the n_transports=0
state digest is byte-identical to HEAD and transports/LCACs never enter an emitter/ELINT path. Report measured
numbers + the byte-identical proof. DEFER the HUD banner/countdown + dedicated meshes (map glyph + ship-mesh
fallback). Commit with a conventional message. BLOCKED if any contract cannot hold honestly.`,
  { label: 'implement:M5-amphibious', phase: 'Implement', schema: IMPL_SCHEMA }
)
log(`Implementer: ${impl ? impl.status : 'NULL'} — ${impl ? impl.measured : ''}`)
if (!impl || impl.status === 'BLOCKED' || impl.status === 'NEEDS_CONTEXT') {
  return { halted: true, stage: 'implement', impl }
}

phase('Spec review')
const specReview = await agent(
`SPEC-COMPLIANCE reviewer for M5 #1 amphibious + beachhead lose-path. DO NOT TRUST THE IMPLEMENTER. Re-read the
spec (docs/research/handoff/05_new_enemy_ship_classes_amphibious_landin.md, the two Amphibious features) + the
diff (git show), and RE-RUN the tests + tools/probe_amphibious.py yourself. VERIFY EVERY CONTRACT:
 - BYTE-IDENTICAL DEFAULT: independently digest a same-seed multi-thousand-step run at n_transports=0 and
   confirm == pre-change HEAD; duel (tests/test_sm2_statistics.py) + smoke + full suite green; defeated trips
   ONLY on bastion_tel at n_transports=0.
 - FOG/NO-CHEAT: grep the commander/world amphibious-release path for any live player truth read; confirm it
   reasons only from EnemyPicture; confirm transports/LCACs are absent from every _emitters/ELINT list (a test
   proves ELINT never hears them) and appear on the contact board only via radar/SAR.
 - PHYSICS-NOT-DICE: the LCAC/transport kill is the OBB sweep (no roll); "landing" is the box-radius geometry;
   the beachhead timer is a deterministic clock; LCAC short detection is its size class, not a flag.
 - WIN/LOSE: an LCAC in the box starts the timer; clearing all committed craft cancels; expiry => defeated +
   defeat_cause=='beachhead'; TEL defeat => defeat_cause=='bastion'; victorious requires the landing force dead.
 - DETERMINISM: fresh tag [seed,15], NO reuse of 8/9/10/11/12/13/14; no wall-clock; same seed => same geometry.
 - NO TEST WEAKENED; tests/test_spawn_zones.py + tests/test_combat_config.py green.
Re-run: the new test files + tests/test_sm2_statistics.py + tests/test_spawn_zones.py + tests/test_combat_config.py
+ full suite + smoke.
${CONVENTIONS}
Implementer: ${impl.status}; measured=${impl.measured}; byteid=${impl.byte_identical_note}
PASS only if EVERY contract holds — especially byte-identical default + no-truth commander + the lose-path
semantics. Findings with file:line.`,
  { label: 'spec-review:M5-amphibious', phase: 'Spec review', schema: REVIEW_SCHEMA }
)
log(`Spec review: ${specReview ? specReview.verdict : 'NULL'} (${specReview ? specReview.findings.length : 0}) — ${specReview ? specReview.reran_tests_output : ''}`)

if (specReview && specReview.verdict === 'FAIL' && specReview.findings.length) {
  phase('Spec fix')
  const fix = await agent(
`FIXER for M5 #1 amphibious. Fix ALL findings without weakening any test or breaking byte-identical default /
fog-no-cheat / physics-not-dice / determinism / the win-lose policy. Re-run all amphibious tests + the duel +
test_spawn_zones + test_combat_config + full suite + smoke + tools/probe_amphibious.py. Commit.
${CONVENTIONS}
FINDINGS:
${specReview.findings.map((f, i) => `${i + 1}. [${f.severity}] ${f.file}:${f.line} — ${f.issue}\n   FIX: ${f.required_fix}`).join('\n')}`,
    { label: 'spec-fix:M5-amphibious', phase: 'Spec fix', schema: IMPL_SCHEMA }
  )
  log(`Spec fix: ${fix ? fix.status : 'NULL'}`)
  const recheck = await agent(
`Re-verify M5 #1 amphibious after the fixer: re-run all amphibious test files + the duel + test_combat_config +
test_spawn_zones + full suite + smoke + the probe. Confirm byte-identical default (digest) + the no-truth
commander + the beachhead lose/cancel/cause semantics + victorious-requires-landing-force-dead. PASS/FAIL with counts.
${CONVENTIONS}`,
    { label: 'spec-recheck:M5-amphibious', phase: 'Spec fix', schema: REVIEW_SCHEMA }
  )
  log(`Spec recheck: ${recheck ? recheck.verdict : 'NULL'}`)
  if (recheck && recheck.verdict === 'FAIL') return { halted: true, stage: 'spec-recheck', specReview, recheck }
}

phase('Quality review')
const qReview = await agent(
`CODE-QUALITY reviewer for M5 #1 amphibious (spec passed). Judge whether it is WELL BUILT:
 - Transport reuses the Destroyer racetrack/damage/OBB (no new flight/damage physics); Lcac is a clean minimal
   Ship subclass; no copy-paste of the ship-step or damage code;
 - the beachhead state machine (LOITER/RUN/SPLASH + the timer) is clean + has ONE responsibility per method;
 - all geometry/timing values are NAMED module constants with comments (LANDING_BOX, launch line, speeds, grace,
   LCAC_PER_TRANSPORT) — no magic numbers in the hot loop;
 - no per-tick allocations in _step_amphibious; no dead code;
 - tests verify measured behavior (ETAs, OBB kill, box-entry, timer expiry/cancel) not tautologies;
 - the byte-identical-default + no-emitter-leak guarantees are structurally enforced (count=0 gate, no
   transport in any emitter list), not merely asserted once.
Re-run the amphibious tests + smoke. Findings with file:line.
${CONVENTIONS}`,
  { label: 'quality-review:M5-amphibious', phase: 'Quality review', schema: REVIEW_SCHEMA }
)
log(`Quality review: ${qReview ? qReview.verdict : 'NULL'} (${qReview ? qReview.findings.length : 0})`)
if (qReview && qReview.verdict === 'FAIL' && qReview.findings.filter(f => f.severity !== 'MINOR').length) {
  phase('Quality fix')
  const qfix = await agent(
`FIXER for M5 #1 amphibious code-quality findings. Fix BLOCKER/MAJOR (MINOR where cheap) without changing
behavior or weakening tests. Re-run the amphibious tests + smoke. Commit.
${CONVENTIONS}
FINDINGS:
${qReview.findings.map((f, i) => `${i + 1}. [${f.severity}] ${f.file}:${f.line} — ${f.issue}\n   FIX: ${f.required_fix}`).join('\n')}`,
    { label: 'quality-fix:M5-amphibious', phase: 'Quality fix', schema: IMPL_SCHEMA }
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
