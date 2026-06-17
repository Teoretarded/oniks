export const meta = {
  name: 'zero-bias-whole-game-audit',
  description: 'Two independent zero-bias Opus reviewers sweep the whole game; every finding adversarially verified, deduped, severity-ranked',
  phases: [
    { title: 'Independent review', detail: 'two reviewers, whole game, zero shared context' },
    { title: 'Adversarial verify', detail: 'refute-by-default skeptic per finding' },
  ],
}

const REPO = 'C:\\Users\\teoti\\OneDrive\\Desktop\\New folder\\oinks PROTO'

const NON_NEGOTIABLES = `
NON-NEGOTIABLE CONTRACTS of this game (a violation of any is a BUG):
1. PHYSICS NOT DICE — hit/miss/detection must EMERGE from simulated physics (guidance, fuse/OBB
   crossing, radar horizon, terrain LOS, multipath elevation noise, loft/terminal geometry,
   J/S burn-through) + measured statistical bands. A flat 'random() < Pk' roll is a BUG.
   (The ONE documented legacy exception is the CIWS burst roll — not a bug, do not report it.)
2. FOG OF WAR / NO CHEAT — EVERY enemy-AI decision AND every fog-gated player-UI element must read
   ONLY sensor-derived belief: EnemyPicture / ContactBoard / ElintReceiver / RWR / believed tracks.
   Reading a real entity's .pos/.fuel/.alive/.vel (ground truth) for a decision or a fog-gated
   render is a BUG (a "truth leak"). Friendly-own telemetry (own drone/own TEL) is allowed to read
   own truth. This is the project's #1 historical bug class — hunt it hard.
3. DETERMINISM — all RNG must be a seeded child stream np.random.default_rng([seed, tag]).
   Unseeded np.random.* , python random.* , time.time()/perf_counter()/datetime.now() feeding sim
   state, set-iteration order, or dict-order-dependent results that affect the sim = BUG.
   Two same-seed worlds must stay bit-identical over thousands of steps.
4. REGRESSION CONTRACTS — the Oniks-vs-SM-2 duel (tests/test_sm2_statistics.py) and Oniks/SAM
   flight are LOCKED bit-identical; every new CombatConfig field must default OFF/0 so the
   out-of-the-box battle is byte-identical. Code that would silently change the default battle = BUG.
`

const CODEBASE_MAP = `
CODEBASE (Python 3.11, pure-numpy sim + custom OpenGL renderer, pytest). cwd = the repo root.
- sim/  (GL-FREE numpy): arsenal.py (WeaponDef/SamDef/StrikeDef defs), missile.py (cruise flight),
  sam.py (SAM loft/terminal + multipath), strike.py (Tomahawk/JASSM + HarmMissile ARM seeker),
  radar.py (Radar.detects horizon+LOS+range gate — the most-tested seam; EW plugs in here),
  recon.py (ReconDrone/ElintReceiver triangulation/RwrReceiver/SarSensor), ew.py (J/S burn-through
  field model), commander.py (EnemyPicture sensor-only brain + EnemyCommander doctrine — THE AI BRAIN,
  must read only EnemyPicture), enemy_defense.py (ShipDefense SM-2/SM-6/CIWS fire control),
  enemy_air.py (Fighter/Awacs/JammerAircraft/AirBase), enemy_ships.py (Destroyer/Carrier),
  contacts.py (ContactBoard), enemy_strikes.py (enemy ESM).
- world/ (GL-FREE): combat.py (CombatWorld: order of battle, stepping, _feed_enemy_picture,
  _player_visible, _step_recon_sensors, launch/launch_sam/launch_arm, win/lose — the integration hub),
  combat_config.py (CombatConfig LOCKED frozen schema + clamp_config), generation.py (terrain).
- game/ (OpenGL — NOT in headless tests except pure helpers): states.py (UI primitives badge/
  gauge_bar/etc + SEMANTIC_COLORS), hud.py (HUD + pure row helpers), tactical_map.py (map overlays),
  sandbox.py (in-battle input/effects/camera), controls.py/keybinds.py (input, TIME_SCALES).
- tools/ : smoke_combat.py (the 70/70 smoke gate), probe_*.py (headless physics probes).
- tests/ : pytest contracts. RUN: python -m pytest -q   (~6 min, ~945 tests). Targeted: python -m pytest tests/test_X.py -q
  Smoke gate: python tools/smoke_combat.py  (must print 70/70, exit 0).
RNG tags already taken: [seed]=defense, [seed,3]=spawn, [seed,4]=recon, [seed,5]=commander,
  [seed,6]=pantsir, [seed,7]=enemy-radar, [seed,8]=player-ARM & EW. New tags should be allocated centrally.
`

const FINDINGS_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['findings', 'coverage_notes'],
  properties: {
    coverage_notes: { type: 'string', description: 'Which files/subsystems you actually read, and anything you could not cover.' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['title', 'category', 'severity', 'file', 'line', 'description', 'evidence', 'repro_or_proof', 'suggested_fix', 'confidence'],
        properties: {
          title: { type: 'string', description: 'One-line bug summary.' },
          category: { type: 'string', enum: ['PHYSICS_NOT_DICE', 'FOG_LEAK_NO_CHEAT', 'DETERMINISM', 'REGRESSION_RISK', 'CORRECTNESS', 'CRASH_EDGE', 'INTEGRATION_GAP', 'PERF', 'TEST_QUALITY', 'OTHER'] },
          severity: { type: 'string', enum: ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] },
          file: { type: 'string', description: 'Repo-relative path, e.g. sim/commander.py' },
          line: { type: 'string', description: 'Line number or range, e.g. 412 or 410-418' },
          description: { type: 'string', description: 'What is wrong and why it violates a contract / is incorrect.' },
          evidence: { type: 'string', description: 'The actual code snippet or quoted lines that prove it.' },
          repro_or_proof: { type: 'string', description: 'How you confirmed it (a test you ran, a probe, or a precise logical argument). If not yet confirmed, say so.' },
          suggested_fix: { type: 'string', description: 'Concrete minimal fix.' },
          confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
        },
      },
    },
  },
}

const VERDICT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['is_real', 'severity', 'confidence', 'reasoning', 'evidence'],
  properties: {
    is_real: { type: 'boolean', description: 'True ONLY if this is a genuine bug you independently confirmed by reading the actual code path (and running a test/probe where feasible). Default false when uncertain.' },
    severity: { type: 'string', enum: ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'NOT_A_BUG'] },
    confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
    reasoning: { type: 'string', description: 'Why it is or is not real. If the original claim mis-cited a line or misread the fog/determinism rules, say so.' },
    evidence: { type: 'string', description: 'The exact code/lines or test output you used to decide.' },
  },
}

function reviewerPrompt(lensName, emphasis) {
  return `You are an independent, ZERO-BIAS senior code reviewer auditing a finished-but-suspected-buggy
missile-combat game. The owner "has a big feeling there are bugs." You have NO stake in the code being
correct — your job is to FIND REAL BUGS. You are reviewer "${lensName}". You work ALONE; you do not see
any other reviewer's output (that independence is the point).

${NON_NEGOTIABLES}
${CODEBASE_MAP}

YOUR PRIMARY EMPHASIS: ${emphasis}
But report ANY genuine bug you find in ANY subsystem — you are reviewing the WHOLE game, not just your emphasis.

METHOD (be exhaustive — token cost is not a concern):
1. Build a mental map: Glob/Read the sim/ and world/ files; these hold the simulation + AI brain + integration.
2. Go subsystem by subsystem. For EACH, read the real code (not just signatures) and actively hunt:
   - Grep for the anti-patterns: 'random(' , 'np.random' without a seeded child rng, 'time.time' /
     'perf_counter' / 'datetime' feeding sim, '.pos' / '.alive' / '.fuel' / '.vel' reads inside the
     enemy commander / EnemyPicture / fog-gated UI (truth leaks), 'Pk' / probability rolls, bare 'except'.
   - Trace whether features wired in unit tests actually fire in real play (the INTEGRATION_GAP class:
     dead branches, orders never executed, a kwarg that is always default — like a past bug where the
     enemy EMCON was dead code because the ARM was never fed to the enemy picture).
   - Check numerical correctness: unit mismatches (m vs km, rad vs deg), wrong axis (the sim uses a
     specific coordinate convention — verify x/z/alt usage), sign errors, off-by-one, clamp bounds.
   - Check edge cases: empty contact lists, zero-length routes, div-by-zero, None deref, index past end.
3. CONFIRM before you claim. Prefer running a targeted test or writing a tiny throwaway probe with Bash
   (python -c '...' or python tools/...) to PROVE a suspicion with a number. A confirmed bug with a repro
   beats five hunches. If you cannot confirm, lower the confidence field and say exactly what is unproven.
4. Do NOT report style nits, naming, or cosmetic preferences. Do NOT report the documented CIWS burst-roll
   legacy exception. Do NOT invent bugs to seem productive — an empty findings list is a valid result if
   the code is clean in an area. Bad findings waste the owner's time.
5. For tests: only flag a test as TEST_QUALITY if it is tautological / asserts nothing meaningful / was
   weakened to pass (e.g. a tolerance widened to hide a real miss). Do not "review" tests for style.

Return the structured findings object. Every finding needs a real file:line, the quoted offending code in
'evidence', and how you confirmed it in 'repro_or_proof'. Be precise — a verifier will try to REFUTE each one.`
}

phase('Independent review')
const reviewers = [
  { lens: 'R1-CORRECTNESS', emphasis: 'Simulation PHYSICS correctness + DETERMINISM + REGRESSION risk. Scrutinise sim/missile.py, sim/sam.py, sim/strike.py, sim/radar.py, sim/ew.py, sim/recon.py, sim/enemy_defense.py, sim/arsenal.py and world/combat.py stepping. Verify guidance/fuse/horizon/loft math, seeded-RNG discipline, and that the default battle stays byte-identical.' },
  { lens: 'R2-FOGOFWAR', emphasis: 'FOG-OF-WAR / NO-CHEAT truth leaks + INTEGRATION gaps + CRASH/edge cases + UI-logic fog leaks. Scrutinise sim/commander.py (EnemyPicture + EnemyCommander), sim/enemy_air.py, world/combat.py (_feed_enemy_picture/_player_visible/_step_recon_sensors/_execute_commander_order/win-lose), and the pure helpers in game/hud.py & game/tactical_map.py. Trace every AI decision and every fog-gated render back to a SENSOR source, not truth.' },
]

const reviews = await parallel(reviewers.map(r => () =>
  agent(reviewerPrompt(r.lens, r.emphasis), { label: `review:${r.lens}`, phase: 'Independent review', schema: FINDINGS_SCHEMA })
))

const valid = reviews.map((r, i) => ({ r, lens: reviewers[i].lens })).filter(x => x.r && Array.isArray(x.r.findings))
log(`Reviewers returned: ${valid.map(v => `${v.lens}=${v.r.findings.length}`).join(', ')}`)

// Flatten + light dedup by (file, rounded line, category) so two reviewers spotting the same thing collapse.
const all = []
for (const v of valid) for (const f of v.r.findings) all.push({ ...f, source: v.lens })
function key(f) {
  const ln = parseInt(String(f.line).split('-')[0], 10) || 0
  return `${(f.file || '').toLowerCase().trim()}::${Math.round(ln / 5)}::${f.category}`
}
const seen = new Map()
for (const f of all) {
  const k = key(f)
  if (!seen.has(k)) seen.set(k, f)
  else { const e = seen.get(k); e.source = `${e.source}+${f.source}`; if (!e.repro_or_proof.includes(f.repro_or_proof)) e.repro_or_proof += ` | also: ${f.repro_or_proof}` }
}
const deduped = [...seen.values()]
log(`Findings: ${all.length} raw -> ${deduped.length} deduped. Verifying each adversarially...`)

phase('Adversarial verify')
const verified = await parallel(deduped.map(f => () =>
  agent(
`You are a hostile VERIFIER. Another reviewer filed the bug below. Your job is to REFUTE it: assume it is
WRONG until the actual code proves otherwise. Read the real code path yourself (Read the cited file around
the cited line, and follow the data flow). Where feasible, run a targeted test or a tiny python probe with
Bash to settle it with evidence. Default is_real=false if you cannot independently confirm it.

${NON_NEGOTIABLES}
${CODEBASE_MAP}

CLAIMED BUG:
- title: ${f.title}
- category: ${f.category}   (claimed severity: ${f.severity}, claimed confidence: ${f.confidence})
- file:line: ${f.file}:${f.line}
- description: ${f.description}
- evidence cited: ${f.evidence}
- how they say they confirmed it: ${f.repro_or_proof}
- their suggested fix: ${f.suggested_fix}

Decide: is this a GENUINE bug (a real contract violation or real defect that affects behavior)? Watch for:
the claim mis-citing a line, misreading the coordinate/units convention, calling an allowed own-truth read a
"leak", calling the documented CIWS roll a dice bug, or flagging a default-empty kwarg as broken. If it IS
real, assign the correct severity (CRITICAL=crashes/corrupts/duel-or-determinism-broken/blatant truth-leak in
live play; HIGH=wrong behavior in normal play or a real but bounded leak; MEDIUM=edge-case/minor; LOW=trivial).
Return the verdict object with the exact evidence you used.`,
    { label: `verify:${(f.file || '?').split('/').pop()}:${f.line}`, phase: 'Adversarial verify', schema: VERDICT_SCHEMA }
  ).then(v => ({ finding: f, verdict: v })).catch(() => null)
))

const results = verified.filter(Boolean)
const confirmed = results.filter(x => x.verdict && x.verdict.is_real && x.verdict.severity !== 'NOT_A_BUG')
const rejected = results.filter(x => !(x.verdict && x.verdict.is_real && x.verdict.severity !== 'NOT_A_BUG'))

const sevRank = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 }
confirmed.sort((a, b) => (sevRank[a.verdict.severity] ?? 9) - (sevRank[b.verdict.severity] ?? 9))

log(`CONFIRMED bugs: ${confirmed.length} (CRITICAL ${confirmed.filter(c => c.verdict.severity === 'CRITICAL').length}, HIGH ${confirmed.filter(c => c.verdict.severity === 'HIGH').length}). Rejected/uncertain: ${rejected.length}.`)

return {
  summary: {
    reviewers: valid.map(v => ({ lens: v.lens, count: v.r.findings.length, coverage: v.r.coverage_notes })),
    raw: all.length, deduped: deduped.length,
    confirmed: confirmed.length, rejected: rejected.length,
    by_severity: {
      CRITICAL: confirmed.filter(c => c.verdict.severity === 'CRITICAL').length,
      HIGH: confirmed.filter(c => c.verdict.severity === 'HIGH').length,
      MEDIUM: confirmed.filter(c => c.verdict.severity === 'MEDIUM').length,
      LOW: confirmed.filter(c => c.verdict.severity === 'LOW').length,
    },
  },
  confirmed: confirmed.map(c => ({
    severity: c.verdict.severity, category: c.finding.category, title: c.finding.title,
    file: c.finding.file, line: c.finding.line, source: c.finding.source,
    description: c.finding.description, evidence: c.finding.evidence,
    verifier_reasoning: c.verdict.reasoning, verifier_evidence: c.verdict.evidence,
    suggested_fix: c.finding.suggested_fix, confidence: c.verdict.confidence,
  })),
  rejected: rejected.map(r => ({
    title: r.finding.title, file: r.finding.file, line: r.finding.line, category: r.finding.category,
    why_rejected: r.verdict ? r.verdict.reasoning : 'verifier errored',
  })),
}
