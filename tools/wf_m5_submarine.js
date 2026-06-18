export const meta = {
  name: 'm5-submarine-asw',
  description: 'M5: acoustic-warfare cluster — enemy SSK + Kalibr salvo + player sonobuoys + launch-datum back-plot + ASW weapon (find->prosecute->kill). n_subs=0 byte-identical. implementer -> spec review -> fix -> quality review -> fix',
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
 - BYTE-IDENTICAL DEFAULT (THE GATE): new CombatConfig fields (n_subs / sub_kalibr_ammo / n_sonobuoys /
   asw_ammo, all default 0) -> with n_subs=0 NO sub/buoy/ASW machinery runs and the default battle +
   Oniks-vs-SM-2 duel + determinism stay bit-identical (prove with a same-seed multi-thousand-step digest
   == pre-change). LOCKED schema -> sign-off granted on the 0-default condition; add CLAMPs + clamp_config
   + test_combat_config for every field.
 - THE SUB IS INVISIBLE TO RADAR (the whole premise): the Submarine is NEVER in self.ships and is NEVER
   passed to Radar.detects / RadarNetwork.visible / any emitter list. It is detectable ONLY acoustically.
   Guard with a test. (Mirrors how ReconDrone stays out of self.aircraft.)
 - FOG / NO CHEAT: the SubCommander reads ONLY the sensor-only EnemyPicture (it shoots SURVEYED base
   coords with a CEP, like the existing GPS/INS Tomahawks — no live player-TEL truth). The player's
   sonobuoy fix + launch datum read only acoustic detections (noise-floor vs range), never the sub's
   truth pos. The Kalibr stays launch_warning=False (fog-gated like the Tomahawk) — the FAIR telegraph
   is the acoustic launch transient + datum, not a magic missile ping. ASW fires at a TRACK, not truth.
 - PHYSICS NOT DICE: the Kalibr base-hit emerges from surveyed-CEP vs the SEEKER_BASKET_M acquire (the
   existing _refine_strike_aim path); the ASW kill emerges from FIX QUALITY vs an acoustic basket; the
   buoy fix is the measured CRLB from real buoy geometry. No kill rolls.
 - ACOUSTIC DOMAIN != RADAR: the sonobuoy/AcousticReceiver reuses ElintReceiver._solve_triangulation but
   with NO radar_horizon and NO terrain_blocks (sound travels under the surface) — a buoy behind a coastal
   ridge from the sub STILL hears it. This divergence is load-bearing (test it).
 - DETERMINISM: FRESH child-stream tags — [seed,13] sub, [seed,14] sonar (tags 3-8 and 12 are TAKEN; do
   NOT reuse 8). No wall-clock.
 - WIN: victorious must require all subs dead (so the player MUST find+kill it) — but ship this TOGETHER
   with the ASW weapon so the sub is always killable (never an unwinnable state). n_subs=0 -> unchanged.
 - DEFER meshes: the sub renders as a map-only subsurface chevron; the Kalibr falls through to the
   Tomahawk mesh (StrikeMissile default). NEVER weaken a test. STATUS: DONE/DONE_WITH_CONCERNS/BLOCKED/
   NEEDS_CONTEXT. Bad work is worse than no work.`

const ANCHORS = `
VERIFIED ANCHORS:
 - sim/recon.py:595 ElintReceiver + :751 _solve_triangulation (lstsq A@[X,Z]=b + CRLB quality +
   consistency/geometry/range-observability gates). REUSE the solver for a NEW AcousticReceiver (factor
   it out or subclass) with: range gate SONOBUOY_RANGE_M (short ~25-40km), NO horizon/terrain calls,
   ACOUSTIC_BEARING_SIGMA_RAD (~2-3 deg, wider than ELINT), detection floor scaled by range vs the sub's
   radiated_noise().
 - sim/strike.py StrikeMissile (turbofan sea-skimmer; is_hostile/radar_size 'missile'/launch_warning
   class attrs). ADD KALIBR_PL StrikeDef in sim/arsenal.py (clone TOMAHAWK turbofan, max_range scaled
   DOWN ~400-600km so the boat is forced into buoy range, launch_warning=False). Flown by UNCHANGED
   StrikeMissile.
 - world/combat.py:1143 _step_recon_sensors (cadence pattern for _step_acoustic_sensors), :1184
   _inject_elint_tracks (mirror as _inject_sub_track + the launch datum injection into self.contacts),
   :1852 _refine_strike_aim (Kalibr terminal acquire — reused), :2022 victorious (extend: all subs dead),
   :2803 apply_missile_hits_structures (the EXISTING hostile-vs-base sweep already demolishes the base
   with Kalibrs — no new damage code; launch_platform=<sub> so damage.py never self-hits the launcher).
 - world/spawn_zones.py sample_fleet — ADD sample_subs(rng, n) a deep-open-water band ~80-140km (closer
   than the carrier band so the short-legged Kalibr reaches the base). Probe-measured open water.
 - game/controls.py PLATFORMS_COMBAT + combat_platforms() (the gated cycle from the Buk work) — ADD
   'sonobuoy' GATED on n_sonobuoys; LMB-drop a buoy at the clicked world point. game/keybinds.py: ASW
   launch / round verb. game/sandbox.py: place_sonobuoy + launch_asw plumbing.
 - game/tactical_map.py: subsurface chevron + uncertainty ring (reuse ELINT_CIRCLE), buoy glyphs +
   detection rings + acoustic bearing rays (distinct color), launch-datum fast-fading marker. game/hud.py:
   sonobuoy panel (mirror drone panel) + ASW ammo + 'SSK: <state>' once localized + a launch-transient
   threat banner.
 - world/combat_config.py: n_subs/sub_kalibr_ammo/n_sonobuoys/asw_ammo + CLAMPs + clamp_config + tests.`

const TEST_CONTRACTS = `
TDD. Probe acoustic detection + the ASW basket-vs-fix-quality before locking. Contracts (spec 03):
 SUB (test_submarine.py): never returned by any RadarNetwork.visible/Radar.detects (not in self.ships);
   state machine cycles deterministically under a fixed seed; radiated_noise() strictly higher in
   LAUNCH/SPRINT than APPROACH/DEEP.
 KALIBR (test_kalibr_salvo.py): fired round is is_hostile=True, radar_size 'missile', launch_warning
   False (fog-gated); launch_platform set (no self-hit); a salvo within SEEKER_BASKET_M of a TEL can kill
   it via _refine_strike_aim; a salvo whose surveyed aim is beyond the basket hits dirt; determinism.
 SONOBUOY (test_sonobuoy_asw.py): ONE buoy -> bearing only, NO actionable fix; TWO+ with baseline ->
   actionable fix that sharpens with more buoys/time; a QUIET approach sub at range R is NOT heard while
   a LAUNCH-transient sub at R IS (noise-floor physics); NO horizon/terrain gate (a buoy behind a ridge
   still hears the sub); placement consumes stock + refuses at 0; determinism [seed,14].
 LAUNCH DATUM (test_launch_transient_backplot.py): a Kalibr salvo injects a subsurface datum within error
   of the true launch point; it fades/drops within the window; the SubCommander's evade lengthens after a
   datum (deterministic); NO truth leak (datum carries error, not the live post-launch pos).
 ASW (test_player_asw.py): firing with NO subsurface track -> None (no blind fire); a SHARP fix within
   ASW_SEEKER_BASKET_M -> acquire + Submarine.kill(); a COARSE datum beyond the basket -> miss (sub
   survives); the ASW round is is_hostile=False (can't damage player structures); killing the last sub
   flips victorious True when other win sub-conditions hold; determinism.
 WIN: victorious stays False while any sub is alive even with all surface hulls + airfield + radars dead.
 REGRESSION: n_subs=0 -> default battle + duel + full suite + smoke bit-identical (digest).`

const IMPL_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['status', 'files_changed', 'tests_added', 'measured', 'byte_identical_note', 'concerns'],
  properties: {
    status: { type: 'string', enum: ['DONE', 'DONE_WITH_CONCERNS', 'BLOCKED', 'NEEDS_CONTEXT'] },
    files_changed: { type: 'array', items: { type: 'string' } },
    tests_added: { type: 'array', items: { type: 'string' } },
    measured: { type: 'string', description: 'Acoustic detect floor vs range (quiet vs loud), 1-buoy vs 2-buoy fix quality, ASW sharp-kill vs coarse-miss, Kalibr base-hit, full suite + smoke.' },
    byte_identical_note: { type: 'string', description: 'Proof n_subs=0 keeps the default battle + duel bit-identical (digest); sub never radar-visible.' },
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
`You are the IMPLEMENTER for M5 submarine warfare + ASW: a self-contained ACOUSTIC domain that adds a
second lose-path (an enemy diesel SSK creeps in, surfaces to fire a Kalibr salvo at the base, runs deep)
and the player's find->prosecute->kill counter (placed passive sonobuoys that triangulate via the ELINT
solver in the acoustic domain, a free launch-transient back-plot datum, and an ASW weapon). Build the WHOLE
loop so the sub is always killable. n_subs=0 keeps everything OFF and byte-identical. TDD; measure the
acoustic detection + ASW basket with probes before locking.
${CONVENTIONS}
${ANCHORS}
${TEST_CONTRACTS}
Build order (spec): (1) sim/submarine.py (Submarine + state machine + radiated_noise + fire_salvo) +
KALIBR_PL StrikeDef + the threat (sub stepped in world, salvo via apply_missile_hits_structures, fog-gated
contact). (2) the launch-transient datum. (3) sim/recon.py AcousticReceiver (reuse the solver, drop
horizon/terrain) + sonobuoy placement/stepping/_inject_sub_track. (4) sim/asw.py AswRound + launch_asw
(track-gated) + victorious-requires-subs-dead. (5) config fields + clamp + tests; platform/keybind/UI
wiring. Write the test files + probes FIRST. Run all new tests + the duel + full suite + smoke; prove the
n_subs=0 digest is byte-identical and the sub is never radar-visible. Report measured numbers + the
byte-identical proof. DEFER meshes (sub = map chevron; Kalibr = Tomahawk mesh). BLOCKED if any contract
can't hold honestly (e.g. the sub leaks into a radar path).`,
  { label: 'implement:M5-submarine', phase: 'Implement', schema: IMPL_SCHEMA }
)
log(`Implementer: ${impl ? impl.status : 'NULL'} — ${impl ? impl.measured : ''}`)
if (!impl || impl.status === 'BLOCKED' || impl.status === 'NEEDS_CONTEXT') {
  return { halted: true, stage: 'implement', impl }
}

phase('Spec review')
const specReview = await agent(
`SPEC-COMPLIANCE reviewer for M5 submarine/ASW. DO NOT TRUST THE IMPLEMENTER. Re-read spec + the diff,
RE-RUN tests + probes yourself. VERIFY: the Submarine is NEVER radar-visible (grep + a test that no
Radar.detects/RadarNetwork.visible ever sees it; it is not in self.ships/emitters); n_subs=0 is
BYTE-IDENTICAL (independent digest == HEAD; duel + smoke + full suite green); the Kalibr stays
launch_warning=False (fog-gated) + kills via the basket (physics-not-dice); the AcousticReceiver drops
horizon/terrain (buoy-behind-ridge still hears); 1-buoy=bearing-only, 2+=fix; quiet-not-heard vs
loud-heard; the launch datum carries ERROR not truth + the SubCommander reacts to being LOUD not to
reading the fix; ASW refuses blind + sharp-kills/coarse-misses + is_hostile=False; victorious requires
subs dead; fresh tags [seed,13]/[seed,14] (no [seed,8] collision); no test weakened. Re-run all the new
test files + tests/test_sm2_statistics.py + tests/test_combat_config.py + full suite + smoke.
${CONVENTIONS}
Implementer: ${impl.status}; measured=${impl.measured}; byteid=${impl.byte_identical_note}
PASS only if every contract holds — especially sub-invisible-to-radar + byte-identical default. Findings w/ file:line.`,
  { label: 'spec-review:M5-submarine', phase: 'Spec review', schema: REVIEW_SCHEMA }
)
log(`Spec review: ${specReview ? specReview.verdict : 'NULL'} (${specReview ? specReview.findings.length : 0}) — ${specReview ? specReview.reran_tests_output : ''}`)

if (specReview && specReview.verdict === 'FAIL' && specReview.findings.length) {
  phase('Spec fix')
  const fix = await agent(
`FIXER for M5 submarine/ASW. Fix ALL findings without weakening tests or breaking sub-invisible-to-radar /
byte-identical default / fog / determinism. Re-run all sub tests + duel + full suite + smoke + the probes.
${CONVENTIONS}
FINDINGS:
${specReview.findings.map((f, i) => `${i + 1}. [${f.severity}] ${f.file}:${f.line} — ${f.issue}\n   FIX: ${f.required_fix}`).join('\n')}`,
    { label: 'spec-fix:M5-submarine', phase: 'Spec fix', schema: IMPL_SCHEMA }
  )
  log(`Spec fix: ${fix ? fix.status : 'NULL'}`)
  const recheck = await agent(
`Re-verify M5 submarine/ASW after the fixer: re-run all sub test files + duel + combat_config + full suite
+ smoke + the probes. Confirm sub-invisible + byte-identical default + the find->kill loop. PASS/FAIL with counts.
${CONVENTIONS}`,
    { label: 'spec-recheck:M5-submarine', phase: 'Spec fix', schema: REVIEW_SCHEMA }
  )
  log(`Spec recheck: ${recheck ? recheck.verdict : 'NULL'}`)
  if (recheck && recheck.verdict === 'FAIL') return { halted: true, stage: 'spec-recheck', specReview, recheck }
}

phase('Quality review')
const qReview = await agent(
`CODE-QUALITY reviewer for M5 submarine/ASW (spec passed). Judge: the AcousticReceiver SHARES the solver
with ElintReceiver (no copy-paste of the lstsq/CRLB) while cleanly dropping horizon/terrain; the Submarine
state machine is clean; KALIBR_PL reuses StrikeMissile (no new flight code); named acoustic constants w/
comments; no dead code; tests verify measured behavior (noise-floor, basket-vs-fix-quality) not
tautologies; the sub-exclusion-from-radar is structurally enforced not just tested. Re-run the sub tests.
Findings w/ file:line.
${CONVENTIONS}`,
  { label: 'quality-review:M5-submarine', phase: 'Quality review', schema: REVIEW_SCHEMA }
)
log(`Quality review: ${qReview ? qReview.verdict : 'NULL'} (${qReview ? qReview.findings.length : 0})`)
if (qReview && qReview.verdict === 'FAIL' && qReview.findings.filter(f => f.severity !== 'MINOR').length) {
  phase('Quality fix')
  const qfix = await agent(
`FIXER for M5 submarine/ASW code-quality findings. Fix BLOCKER/MAJOR (MINOR where cheap) without changing
behavior or weakening tests. Re-run the sub tests + smoke.
${CONVENTIONS}
FINDINGS:
${qReview.findings.map((f, i) => `${i + 1}. [${f.severity}] ${f.file}:${f.line} — ${f.issue}\n   FIX: ${f.required_fix}`).join('\n')}`,
    { label: 'quality-fix:M5-submarine', phase: 'Quality fix', schema: IMPL_SCHEMA }
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
