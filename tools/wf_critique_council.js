// Adversarial critique council for the M5/M6 combat expansion.
// parallel critique -> rebuttal barrier -> chair converge. Seats + dossier path
// are HARDCODED (no args dependency). Critics are READ-ONLY (no code edits).
export const meta = {
  name: 'critique-council-m6',
  description: 'Adversarial evidence-grounded critique of the M5/M6 combat-expansion build: 4 independent critics (correctness / future-proofing / security-safety / fog-physics-determinism) -> rebuttal -> chair verdict. Read-only.',
  phases: [{ title: 'Critique' }, { title: 'Rebut' }, { title: 'Converge' }],
}

const DOSSIER = 'docs/reviews/critique_dossier_m6.md'

const ENV = `
ENV: cwd = "C:\\\\Users\\\\teoti\\\\OneDrive\\\\Desktop\\\\New folder\\\\oinks PROTO" (Python 3.11).
TESTS: pytest-xdist IS installed — re-run with \`python -m pytest -q -n auto <files>\` (NEVER serial, ~22 min).
You are REVIEW-ONLY: read + run tests/probes, do NOT edit code. Branch feat/combat-expansion.`

const SEATS = [
  { key: 'correctness',
    lens: 'Is it actually RIGHT? Bugs, broken states, logic gaps, wrong outputs, off-by-one, edge cases. Re-run the tests yourself; read the diffs. Judge whether the tests are LOAD-BEARING or tautological (a test that asserts something always-true, or asserts construction rather than behavior, is worthless — name any).' },
  { key: 'future-proofing',
    lens: 'Can a much smarter future model improve this easily, or will it ROT and get buried under 10k lines? Legibility, modularity, lock-in, dead/duplicated code, the deferred-UI framing (does "deferred" hide a real gap that becomes unfindable later?). The 10k-lines-from-now test.' },
  { key: 'security-safety',
    lens: 'Does it FAIL SAFE? campaign JSON save/load (untrusted/corrupt file, KeyError, partial state), the apply_initial_state ingest (bad keys, negative ammo, missing structure ids), unsafe defaults, any crash an ordinary player session could trigger. Does a malformed save or edge config take down the game?' },
  { key: 'fog-physics-determinism',
    lens: 'The PROJECT CONTRACTS: physics-not-dice (no new outcome rolls), fog/no-cheat (every AI/fog-gated decision reads sensor-derived belief, NEVER world.missiles enemy truth — grep for it), determinism (seeded child streams, no wall-clock, byte-identical default == HEAD digest, no tag collision), regression-never-weakened. These are the heart of the game — hunt a single violation hard.' },
]

const FINDINGS = {
  type: 'object', additionalProperties: false,
  required: ['findings', 'credit'],
  properties: {
    findings: { type: 'array', items: { type: 'object', additionalProperties: false,
      required: ['claim', 'lens', 'severity', 'evidence', 'where', 'verifiable'],
      properties: {
        claim: { type: 'string' }, lens: { type: 'string' },
        severity: { type: 'string', enum: ['Critical', 'Important', 'Minor'] },
        evidence: { type: ['string', 'null'] }, where: { type: 'string' },
        verifiable: { type: 'boolean' },
      } } },
    credit: { type: 'array', items: { type: 'string' } },
  },
}
const REBUTTALS = {
  type: 'object', additionalProperties: false,
  required: ['refutations', 'reinforcements', 'new_findings'],
  properties: {
    refutations: { type: 'array', items: { type: 'string' } },
    reinforcements: { type: 'array', items: { type: 'string' } },
    new_findings: { type: 'array', items: { type: 'string' } },
  },
}
const VERDICT = {
  type: 'object', additionalProperties: false,
  required: ['verdict', 'fix_now', 'ok_for_now', 'unverifiable', 'contested', 'solid'],
  properties: {
    verdict: { type: 'string', enum: ['SHIP', 'FIX-THEN-SHIP', 'RETHINK'] },
    fix_now: { type: 'array', items: { type: 'string' } },
    ok_for_now: { type: 'array', items: { type: 'string' } },
    unverifiable: { type: 'array', items: { type: 'string' } },
    contested: { type: 'array', items: { type: 'string' } },
    solid: { type: 'string' },
  },
}

const criticPrompt = (seat) => `You are the ${seat.key.toUpperCase()} critic on an adversarial review council. Be ruthless but honest.
Read the dossier at ${DOSSIER} IN FULL, then read the ARTIFACTS it names (the actual code + tests), and RE-RUN the relevant tests/probes yourself.
${ENV}
YOUR LENS — ${seat.key}: ${seat.lens}
THE EVIDENCE LAW (absolute): every flaw MUST cite evidence you actually found — file:line, a test result you ran, a measured value, a grep hit. If judging a claim needs evidence that does not exist and you cannot obtain it, DO NOT GUESS — set verifiable=false and name exactly what is missing in 'evidence'. Asserting a flaw you cannot back is the one unforgivable failure.
Return findings only (no essay), each: {claim (one line), lens, severity (Critical|Important|Minor), evidence (the proof, or what's missing), where (file:line/region), verifiable}. Also name 0-2 things that genuinely hold up (credit).`

phase('Critique')
const raw = (await parallel(SEATS.map(seat => () =>
  agent(criticPrompt(seat), { label: `critique:${seat.key}`, phase: 'Critique', schema: FINDINGS })
    .then(r => r ? { seat: seat.key, ...r } : null)
))).filter(Boolean)

const allFindings = raw.flatMap(r => (r.findings || []).map(f => `[${r.seat}/${f.severity}] ${f.claim} @ ${f.where} — evidence: ${f.evidence} (verifiable=${f.verifiable})`))
log(`Round 1: ${allFindings.length} findings from ${raw.length} critics`)

phase('Rebut')
const rebuttals = (await parallel(raw.map(r => () =>
  agent(`You are the ${r.seat.toUpperCase()} critic. ROUND 2 — cross-examination. Default to SKEPTICISM: a finding nobody can substantiate must die or drop to UNVERIFIABLE.
${ENV}
ALL round-1 findings (yours + the others'):
${allFindings.map((f, i) => `${i + 1}. ${f}`).join('\n')}
For each finding that is NOT yours: REFUTE it (evidence weak/wrong/absent — say why, with your own evidence), REINFORCE it (you independently confirmed it — add evidence), or leave it. Add any NEW finding only visible from your lens now. Cite evidence (file:line / test result) for everything.
Return {refutations:[], reinforcements:[], new_findings:[]} — each a one-line string WITH its evidence.`,
    { label: `rebut:${r.seat}`, phase: 'Rebut', schema: REBUTTALS })
))).filter(Boolean)

phase('Converge')
const verdict = await agent(`You are the CHAIR of the critique council. You do NOT invent findings; you judge them on evidence.
${ENV}
ROUND-1 FINDINGS:
${allFindings.map((f, i) => `${i + 1}. ${f}`).join('\n')}
ROUND-2 REBUTTALS:
${rebuttals.map((rb, i) => `--- ${raw[i] ? raw[i].seat : '?'} ---\nREFUTE: ${(rb.refutations || []).join(' | ')}\nREINFORCE: ${(rb.reinforcements || []).join(' | ')}\nNEW: ${(rb.new_findings || []).join(' | ')}`).join('\n')}
CREDITS: ${raw.flatMap(r => r.credit || []).join(' | ')}
For each distinct finding decide CONFIRMED (evidence held / reinforced, none refuted) / CONTESTED (critics genuinely disagree) / REFUTED (drop). Assign every CONFIRMED finding a tier: FIX NOW (rots if deferred — buried, built-upon, unfixable within a few sessions) or OK FOR NOW (real but a smarter future model can fix later). Evidence-law failures go to unverifiable with the missing evidence named.
Set the top-line VERDICT: SHIP / FIX-THEN-SHIP / RETHINK (RETHINK only if the APPROACH itself was challenged, not just details). Be TERSE — one line per finding. Return the VERDICT schema.`,
  { label: 'chair', phase: 'Converge', schema: VERDICT })

return verdict
