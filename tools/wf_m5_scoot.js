export const meta = {
  name: 'm5-shoot-and-scoot',
  description: 'M5 #4: generic relocatable firing TELs (Bastion/S-300/Buk) — request_relocate(platform,dest) commits + disarms the TEL, drives it, and re-pins its tubes + destructible Structure at the new pad so the enemy back-plot points at the STALE pad. No relocate requested == byte-identical. implementer -> spec review -> fix -> quality review -> fix',
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
  Commit per task with a conventional message; NEVER touch git main. Branch: feat/combat-expansion.
NON-NEGOTIABLES:
 - BYTE-IDENTICAL DEFAULT (THE GATE): relocate is a PLAYER ACTION, not a config count — there is NO new
   CombatConfig field. The byte-identical contract is: a battle in which request_relocate is NEVER called
   plays EXACTLY as today. Each firing TEL gains relocate state that DEFAULTS to idle (dest=None,
   committed=False, move_left_s=0); _step_relocations(dt) is a pure no-op while every launcher is idle; the
   arm gates only gain an "and not launcher.committed" clause that is vacuously True when committed=False. PROVE
   a same-seed multi-thousand-step state digest == pre-change HEAD (the default battle + smoke + Oniks-vs-SM-2
   duel never relocate, so they stay BIT-IDENTICAL).
 - GENERIC OVER FIRING TELs ONLY: the relocate mechanic is GENERIC over a "relocatable launcher" so the Oniks
   Bastion TEL(s), the S-300 TEL(s), AND the M5 Buk TEL all reuse ONE implementation. The radar station and
   Pantsir are NOT relocatable in v1 (fixed sites — keeps scope to the firing TELs the back-plot targets).
 - THE LOAD-BEARING HONESTY LINK (moving Structures): on arrival the launcher pad, EVERY launch tube['pos'],
   AND the matching destructible Structure (.pos + its OBB) must all move to the new pad. A strike aimed at the
   OLD pad must then MISS and a strike at the NEW pad must be able to hit. CRITICAL: verify sim/bases Structure
   rebuilds its OBB from .pos PER QUERY (not cached at __init__); if the OBB is cached, the move desyncs the
   damage sweep (apply_missile_hits_structures) — fix the Structure to recompute from live pos, with a test
   (pad + tubes + Structure all within 1 m of dest after the move).
 - FOG / NO CHEAT: relocate adds NO sensor on the player side and NO AI code. The enemy can only re-localize a
   moved TEL through a FRESH back-plot from a NEW launch (it does not emit while moving). The dodge is EMERGENT
   and physics-not-dice: after a relocate the commander's TOMAHAWK/JASSM salvo flies to the STALE cluster
   centroid and _refine_strike_aim finds NO live Structure within SEEKER_BASKET_M of the empty pad -> the round
   hits dirt (a clean miss the player EARNED by moving, never a roll). A NEW launch from the new pad must seed a
   back-plot near the NEW xz (the enemy can re-form a cluster — the cat-and-mouse stays alive).
 - PHYSICS NOT DICE / DETERMINISM: the move is a deterministic constant-speed drive (RELOCATE_SPEED_MPS) plus a
   fixed emplace/displace dwell (RELOCATE_SETUP_S) each end during which the TEL is committed-but-not-yet-moving.
   Named module constants with comments. Same seed + same relocate sequence -> identical positions. If any RNG
   is needed (it should not be — the move is deterministic), use the reserved tag [seed, 11] (tags 3-8,12-15
   TAKEN; 9=CBR, 10=decoys RESERVED; use ONLY 11). No wall-clock.
 - REGRESSION NEVER WEAKENED: a relocate ordered MID-RELOAD keeps the tube reload timer running (it re-cocks
   while driving). If a planned test can't pass honestly, report BLOCKED — never widen a tolerance.
 - DEFER UI + meshes: the tactical-map move-route polyline + ghost-destination marker + the MOVING launcher
   status strip + the game/sandbox _draw_tel position LERP + the RMB-on-active-platform relocate input are
   DEFERRED to the later UI-wiring pass. BUT the world-side request_relocate + _step_relocations + the arm
   gates + the Structure/tube move ARE headless-testable now and MUST be covered. Keep logic in world/ + sim/
   (GL-free).
 STATUS: DONE / DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT. Bad work is worse than no work.`

const ANCHORS = `
VERIFIED ANCHORS (read before coding):
 - world/combat.py: _build_oniks_battery (~2347) + _oniks_launcher_positions + _oniks_tubes (each tube a dict
   with a baked 'pos'); _build_s300_battery + _s300_launcher_positions + _s300_tubes; _build_buk_battery (~2739)
   + _buk_tubes — the three firing-TEL tube-dict builders whose tube 'pos' must be RECOMPUTED from the live pad
   on arrival (today they are baked at build from BASE_POS + CANISTER_MOUTH_OFFSET). launcher_armed (~2337) +
   the SAM/Buk arm gates — add the "and not committed" clause. The destructible Structure wrappers
   (bastion_tel_NN / s300_tel_NN / buk_tel_NN) in self.structures whose .pos must move with the TEL.
 - world/combat.py step (~3058): add self._step_relocations(dt) (advance committed moves, re-pin tube + Structure
   pos on arrival) — a no-op while all launchers idle (byte-identical). New world API request_relocate(platform,
   dest_xz) -> bool (sets committed + dest, disarms; refuses a 2nd request while committed).
 - world/combat.py _refine_strike_aim (~1852) + SEEKER_BASKET_M (the stale-pad miss physics) +
   sim/commander.py _doctrine_kill (~1136) TOMAHAWK_SALVO at the cluster centroid + process_missile_track
   (~1503) which seeds a NEW back-plot from the new pad's launch (already reads the missile's first-seen
   pos/vel, which now originate at the new pad — verify, do not change).
 - sim/bases.py: Structure (.pos, .obb / hit-OBB). VERIFY the OBB is derived from .pos per query (the M5 ship
   classes recompute hit_reach from dims; the Structure must likewise not cache a stale world OBB). If cached,
   recompute from live pos — this is the load-bearing honesty link. apply_missile_hits_structures is the sweep.
 - New constants in world/combat.py (open-source K-300P/Buk road march): RELOCATE_SPEED_MPS=12.0
   (~43 km/h TEL road speed), RELOCATE_SETUP_S=35.0 (emplace/displace dwell each end).
 - tools/probe_*.py — the idiom. Write tools/probe_scoot.py to MEASURE the move ETA (setup+drive) and to PROVE
   the stale-pad miss: build a back-plot cluster at the OLD pad, relocate, run a commander TOMAHAWK_SALVO, and
   print whether _refine_strike_aim finds a live Structure within SEEKER_BASKET_M (expect NO -> dirt) and that a
   new launch seeds a back-plot near the NEW xz.`

const TEST_CONTRACTS = `
TDD: write tools/probe_scoot.py + tests/test_relocate.py FIRST (headless against CombatWorld). Contracts (spec 06 F1):
 - (a) request_relocate(platform, dest) sets committed=True and the platform's arm gate (launcher_armed /
   sam/buk) False IMMEDIATELY; a 2nd request while committed is refused (returns False / no-op);
 - (b) a launch attempt while committed returns None (launch / launch_sam / launch_buk all refuse);
 - (c) after move_left_s (setup+drive+setup) elapses, the launcher pad, EVERY tube['pos'], and the matching
   Structure.pos ALL equal dest within 1 m, and committed flips back False (re-armed if ammo/reload allow);
 - (d) DETERMINISM: same seed + same relocate sequence -> identical positions (bit-for-bit);
 - (e) FOG/HONESTY (the headline): seed a back-plot cluster at the OLD pad; relocate the TEL; fire a commander
   TOMAHAWK_SALVO at the stale centroid; assert _refine_strike_aim finds NO Structure within SEEKER_BASKET_M of
   the stale centre (the round hits dirt — the relocated TEL SURVIVES); AND a NEW launch from the new pad seeds
   a back-plot near the NEW xz (the enemy can re-form a cluster);
 - EDGE: a relocate ordered MID-RELOAD keeps the tube reload timer counting while driving;
 - applies to ALL THREE firing TELs (parametrize Oniks / S-300 / Buk where the platform exists).
 REGRESSION: a battle with NO relocate -> default battle + duel + full suite + smoke BIT-IDENTICAL (digest);
   the Structure-OBB-from-pos change (if needed) keeps every existing damage/structure test green.`

const IMPL_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['status', 'files_changed', 'tests_added', 'measured', 'byte_identical_note', 'concerns'],
  properties: {
    status: { type: 'string', enum: ['DONE', 'DONE_WITH_CONCERNS', 'BLOCKED', 'NEEDS_CONTEXT'] },
    files_changed: { type: 'array', items: { type: 'string' } },
    tests_added: { type: 'array', items: { type: 'string' } },
    measured: { type: 'string', description: 'Probe: move ETA (setup+drive), pad/tube/Structure all within 1 m of dest, the stale-pad MISS (no structure in basket -> dirt), the new-pad back-plot re-seed; full suite + smoke counts.' },
    byte_identical_note: { type: 'string', description: 'Proof a no-relocate battle is bit-identical to HEAD (digest); the idle relocate state + _step_relocations no-op + the vacuous arm-gate clause; whether the Structure OBB needed a from-pos fix and that it kept structure tests green.' },
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
`You are the IMPLEMENTER for M5 #4 — SHOOT-AND-SCOOT relocatable firing TELs. After firing, the player can order
a Bastion / S-300 / Buk TEL to a new map position; while moving it is COMMITTED (cannot launch) and on arrival
the enemy's back-plotted launch cluster points at the STALE pad, so the next enemy salvo hits dirt. This is the
headline mechanic that makes the (now-reliable, M5 #2) enemy back-plot a threat the player actively dodges. It
is a PLAYER ACTION, so there is NO config field — a battle with no relocate is byte-identical to today. TDD;
measure the move ETA + the stale-pad miss with a probe first.
${CONVENTIONS}
${ANCHORS}
${TEST_CONTRACTS}
Build order: (1) a GENERIC relocatable-launcher state on each firing TEL in world/combat.py (pad_xz, dest_xz,
move_left_s, committed; defaults idle) + request_relocate(platform, dest_xz) + _step_relocations(dt) (advance,
re-pin tube 'pos' + Structure .pos on arrival) + the "and not committed" arm-gate clauses; constants
RELOCATE_SPEED_MPS=12.0, RELOCATE_SETUP_S=35.0. (2) if sim/bases Structure caches its OBB at init, make it
recompute from live .pos (the load-bearing honesty link) — verify every existing structure/damage test stays
green. (3) tests + tools/probe_scoot.py FIRST. Run all new tests + the duel + full suite + smoke; PROVE the
no-relocate digest is byte-identical to HEAD, the pad/tubes/Structure all move within 1 m, the stale-pad salvo
hits dirt, and a new-pad launch re-seeds a back-plot. Report measured numbers + the byte-identical proof. DEFER
the map move-route + MOVING status + _draw_tel lerp + RMB input (the world-side verbs are tested now). Commit
with a conventional message. BLOCKED if any contract cannot hold honestly (esp. the moving-Structure desync, or
a relocate that perturbs the default battle digest).`,
  { label: 'implement:M5-scoot', phase: 'Implement', schema: IMPL_SCHEMA }
)
log(`Implementer: ${impl ? impl.status : 'NULL'} — ${impl ? impl.measured : ''}`)
if (!impl || impl.status === 'BLOCKED' || impl.status === 'NEEDS_CONTEXT') {
  return { halted: true, stage: 'implement', impl }
}

phase('Spec review')
const specReview = await agent(
`SPEC-COMPLIANCE reviewer for M5 #4 shoot-and-scoot. DO NOT TRUST THE IMPLEMENTER. Re-read spec 06 (the
Shoot-and-Scoot feature) + the diff (git show), and RE-RUN the tests + tools/probe_scoot.py yourself. VERIFY:
 - BYTE-IDENTICAL DEFAULT: independently digest a same-seed multi-thousand-step run with NO relocate == pre-change
   HEAD; duel + smoke + full suite green; _step_relocations is a no-op and the arm gates are unchanged while idle.
 - GENERIC: one relocate implementation serves Oniks + S-300 + Buk (no copy-paste per TEL); radar/Pantsir are NOT
   relocatable.
 - MOVING STRUCTURE (load-bearing): after the move, pad + every tube['pos'] + the Structure.pos are all within 1 m
   of dest; the Structure OBB is derived from live .pos (not a stale cache) — confirm in sim/bases and re-run the
   structure/damage tests.
 - FOG/PHYSICS: a stale-pad TOMAHAWK_SALVO finds NO Structure within SEEKER_BASKET_M (round hits dirt — the
   relocated TEL survives); a new-pad launch re-seeds a back-plot near the NEW xz; no AI code added; no truth read.
 - ARM GATES: request_relocate disarms immediately; a launch while committed returns None; a 2nd request is refused;
   a mid-reload relocate keeps the reload timer running.
 - DETERMINISM: same seed+sequence -> identical positions; tag [seed,11] only if any RNG (ideally none); no wall-clock.
 - No test weakened.
Re-run: the new test files + tests/test_sm2_statistics.py + the structure/damage tests + full suite + smoke.
${CONVENTIONS}
Implementer: ${impl.status}; measured=${impl.measured}; byteid=${impl.byte_identical_note}
PASS only if EVERY contract holds — especially byte-identical default + the moving-Structure honesty link + the
stale-pad miss. Findings with file:line.`,
  { label: 'spec-review:M5-scoot', phase: 'Spec review', schema: REVIEW_SCHEMA }
)
log(`Spec review: ${specReview ? specReview.verdict : 'NULL'} (${specReview ? specReview.findings.length : 0}) — ${specReview ? specReview.reran_tests_output : ''}`)

if (specReview && specReview.verdict === 'FAIL' && specReview.findings.length) {
  phase('Spec fix')
  const fix = await agent(
`FIXER for M5 #4 shoot-and-scoot. Fix ALL findings without weakening tests or breaking: byte-identical default,
the generic mechanic, the moving-Structure honesty link, the stale-pad miss physics, the arm gates, determinism.
Re-run all relocate tests + the duel + the structure/damage tests + full suite + smoke + tools/probe_scoot.py. Commit.
${CONVENTIONS}
FINDINGS:
${specReview.findings.map((f, i) => `${i + 1}. [${f.severity}] ${f.file}:${f.line} — ${f.issue}\n   FIX: ${f.required_fix}`).join('\n')}`,
    { label: 'spec-fix:M5-scoot', phase: 'Spec fix', schema: IMPL_SCHEMA }
  )
  log(`Spec fix: ${fix ? fix.status : 'NULL'}`)
  const recheck = await agent(
`Re-verify M5 #4 shoot-and-scoot after the fixer: re-run all relocate test files + the duel + structure/damage
tests + full suite + smoke + the probe. Confirm byte-identical default + the moving-Structure honesty link + the
stale-pad miss + the arm gates. PASS/FAIL with counts.
${CONVENTIONS}`,
    { label: 'spec-recheck:M5-scoot', phase: 'Spec fix', schema: REVIEW_SCHEMA }
  )
  log(`Spec recheck: ${recheck ? recheck.verdict : 'NULL'}`)
  if (recheck && recheck.verdict === 'FAIL') return { halted: true, stage: 'spec-recheck', specReview, recheck }
}

phase('Quality review')
const qReview = await agent(
`CODE-QUALITY reviewer for M5 #4 shoot-and-scoot (spec passed). Judge whether it is WELL BUILT:
 - ONE generic relocatable-launcher abstraction serves all three firing TELs (no per-TEL duplication);
 - _step_relocations is clean, single-responsibility, no per-tick allocation while idle;
 - named, commented constants (RELOCATE_SPEED_MPS, RELOCATE_SETUP_S); no magic numbers;
 - the Structure-OBB-from-pos change (if any) is minimal + correct (no broad refactor of locked base code);
 - no dead code; tests verify measured behavior (move ETA, 1 m re-pin, stale-pad dirt, re-seed) not tautologies;
 - the byte-identical-idle gate + the moving-Structure honesty link are structurally enforced.
Re-run the relocate tests + smoke. Findings with file:line.
${CONVENTIONS}`,
  { label: 'quality-review:M5-scoot', phase: 'Quality review', schema: REVIEW_SCHEMA }
)
log(`Quality review: ${qReview ? qReview.verdict : 'NULL'} (${qReview ? qReview.findings.length : 0})`)
if (qReview && qReview.verdict === 'FAIL' && qReview.findings.filter(f => f.severity !== 'MINOR').length) {
  phase('Quality fix')
  const qfix = await agent(
`FIXER for M5 #4 shoot-and-scoot code-quality findings. Fix BLOCKER/MAJOR (MINOR where cheap) without changing
behavior or weakening tests. Re-run the relocate tests + smoke. Commit.
${CONVENTIONS}
FINDINGS:
${qReview.findings.map((f, i) => `${i + 1}. [${f.severity}] ${f.file}:${f.line} — ${f.issue}\n   FIX: ${f.required_fix}`).join('\n')}`,
    { label: 'quality-fix:M5-scoot', phase: 'Quality fix', schema: IMPL_SCHEMA }
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
