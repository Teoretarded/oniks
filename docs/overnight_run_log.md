# Overnight Autonomous Build — Run Log

> Branch: `feat/combat-expansion` (off `master`). Method: Fable Method
> (implementer + 2-stage hostile review per feature; milestone gates verified by
> the orchestrator; physics-not-dice / fog-of-war / determinism / no-weakened-
> regressions contracts). Source of truth: `docs/research/handoff/` specs +
> `ROADMAP.md` (6 milestones). Per-feature/per-milestone detail lives in
> `docs/combat_build_log.md`; this file is the chronological agent ledger.

---

## MORNING REPORT  (live — updated as work proceeds; branch `feat/combat-expansion`, do NOT touch `main`)

**Headline (updated 2026-06-18, second session — workflow-orchestrated):** 4 of 6
milestones SHIPPED + GATED + COMMITTED (M1, M2, M3, M4), PLUS a two-reviewer
zero-bias whole-game audit whose 4 confirmed bugs are all fixed. Full suite
**~1099 passed, exit 0**; smoke **70/70 exit 0**; the locked contracts (Oniks-vs-SM-2
duel, Oniks/Zircon/SAM flight, same-seed determinism, byte-identical out-of-the-box
battle) held BIT-IDENTICAL throughout (proven by substep byte-dumps). Every feature
ran the Fable loop as a deterministic **Workflow** (opus implementer → hostile
spec/physics/no-cheat review → fixer → code-quality review → fixer); the orchestrator
personally gated each (re-ran suite/smoke/probes, read rendered maps).

**This session added (branch tip `53b2c9e`):**
- **M3 finished** — M3-F5 JAMMED-band UI + emissions meter (`5af9f7b`); HeightField
  refactor (`17d95b0`, bit-identical, 5113-pt proof); close-range terrain_blocks LOS
  fix (`8ca8931`); seeded map presets Open Sea/Archipelago/Strait/Fjord (`57097ec`,
  masking +106/+203/+271 m, per-preset smoke 16/16). **Deferred:** F1/F2 render polish.
- **Zero-bias audit + fixes** (`57fd0a8`, `8ca8931`): HIGH fighter no-cheat truth-track
  (re-gated on a live radar hold + 8 s dwell, TDD regression); LOW ship friendly-fire;
  LOW EW blind-class floor; MEDIUM terrain LOS. 2 findings correctly rejected.
- **M4** — Bastion-K top-attack ASBM (`d01a63c`, probe-measured apogee ~90 km / dive
  −85°, SM-6 counter intact); loitering swarm w/ simultaneous time-on-target (`fcafe0f`,
  cap-saturation proven) + per-weapon STALL_SPEED so a real round splashes ships
  (`53b2c9e`, Oniks/Zircon byte-identical). **Open balance note:** swarm tube-launch
  range ~25 km (boost-overshoot) vs ~40 km design — flagged for playtest.

**Below: the original M1/M2 + EW-core detail from the first session (unchanged).**

### Shipped milestone-by-milestone
- **M1 — Legibility Foundation** (tip `434d825`): widget primitive library
  (`badge`/`gauge_bar`/`mini_compass`/`tab_strip`/`scroll_list` + `SEMANTIC_COLORS`
  + `hud_widgets.py`); track `kind`/`size` stamps; threat-warning strip;
  click-contact intel panel; per-tube battery panel. **Measured (game-test):**
  severity bands exercised live (DANGER<20s/WARN<60s/MUTED), TTI monotonic,
  determinism delta **0.0** @15k steps, fog confirmed in a live battle
  (under-horizon hostiles never on the strip), 795 calls 0 exceptions. No-cheat
  CLEAN; bug-hunt SAFE (1 latent guard fixed). Deferred: M1-F6 toast upgrade (cosmetic).
- **M2 — SEAD / Anti-Radiation Warfare** (tip `0d5635f`): emitter ELINT SIGINT
  channel; **Kh-31P player ARM** (reuses HarmMissile, fog-gated launch, victory
  credit); enemy radar **EMCON vs a sensed ARM**; full player UI (armory ammo,
  3-way B-cycle, emitter map glyph + selection, ARM seeker readout). **Measured:**
  flyoff kill@90km / short@140km / peak Mach 2.80 (envelope locked to the MEASURED
  band — the airframe over-reaches the textbook 110km on the reused Mach-2 loft
  machine, exactly as the in-game HARM does; documented, AWACS@407km stays
  unreachable). The SEAD duel works end-to-end: a ship senses the ARM → EMCON →
  ARM degrades to its seeded CEP ring → radar survives (physics-not-dice). No-cheat
  CLEAN (all 7 surfaces; EMCON reads only sensed tracks). **The M2 gate caught 2
  HIGH integration gaps that all unit tests masked** — the ARM wasn't fed to the
  enemy picture (EMCON was dead code in play) and ship radars resurrected each tick
  (ARM couldn't kill them) — both FIXED, with the missing real-ARM e2e tests added.
- **3D model (task #7):** `build_kh31p` mesh (Kh-31 signature: 4 mid-body ramjet
  intakes), registered for the in-flight render; reference photos
  `kh31p_side.png` + `kh31p_front.png` saved to
  `Assets of oinks/New models 1 needs improving and updating/` and orchestrator-verified.

### Open items / deviations / TODO (for the morning reviewer)
1. **Hands-on playtest recommended.** Agent game-tests substituted for the human
   playtest per the unattended mandate; the legibility + SEAD layers are now in
   place to make a real playtest informative. Try: arm KH-31P in the armory,
   localize an enemy emitter via the drone, fire the ARM, watch the enemy EMCON.
2. **Deviation (honest, measured):** the KH-31P kills to ~130km not the textbook
   110km — the reused HarmMissile loft gains are Mach-2-tuned and a Mach-3 round
   over-glides (the existing HARM does the same). Locked to measured reality, not
   faked. AWACS (407km) stays out of reach as designed.
3. **Geometry note:** the ARM (130km) can't reach the inland enemy ground radars
   (~505km) — by design it's anti-ship-SPY-1 / anti-AWACS-when-dragged-in SEAD;
   the ground-radar victory-credit path is sound and serves closer engagements.
4. **Pre-existing flake (NOT introduced by this run):**
   `tests/test_phase5b_e2e.py::test_backplot_jassm_strike_reaches_defeat` is
   order-dependent (passes in isolation + in the full after-run; untouched sim).
   Worth a look.
5. **Deferred cosmetics:** M1 toast/hint stacked-upgrade; the threat-strip
   badge-per-row pills. Both non-blocking.
6. **User's broader "improve existing models" ask** is OPEN (existing model photos
   live in `Assets of oinks/updated models/`; a quality-lift pass is its own task).

### Recommended next step
Milestones 3–6 remain (EW + terrain; ASBM + swarm; fleet/sub/amphibious; meta
loop). The dependency-correct next build is M3's keystone — `sim/ew.py` J/S
burn-through field model (measure-calibrated; `Radar.detects(jammers=())` defaults
empty = byte-identical). Each remaining milestone is a coherent, gateable increment;
resume from this report + the last commit. The two shipped milestones are
production-quality and safe to merge/playtest as-is.

---

*(Chronological ledger below.)*

---

## CHRONOLOGICAL AGENT LEDGER

Format: `[timestamp] LABEL — role / model — task — verdict`

### Setup (orchestrator, no agents)
- Read handoff bundle in full (README, ROADMAP, 01–09) + fable-method refs.
- Confirmed baseline: `tools/smoke_combat.py` → 70/70, exit 0. Full suite kicked
  off in background to confirm the complete green baseline before checkpoint.
- Created branch `feat/combat-expansion`; `master` untouched.
- Pre-existing uncommitted working tree (28 tracked files +1251/−132, plus new
  `models/missiles.py` + test files matching the handoff) checkpointed as the
  baseline commit so milestone commits stay isolated (the flight recorder).
  Baseline commit `ac697d2`.

### M1-F1 Widget primitive library
- `build:M1-F1` — IMPLEMENTER / opus — badge/gauge_bar/mini_compass/tab_strip/
  scroll_list + SEMANTIC_COLORS + hud_widgets.py, TDD test_widgets.py — DONE
  (25 tests, full suite exit 0, combat_setup left untouched). Commit `73e7bfd`.
- `verify-spec:M1-F1` — SPEC REVIEW / opus — re-read spec 08 + diff, re-ran
  targeted tests — REJECTED: missing the spec-mandated tab_strip refactor of
  combat_setup + its regression. (Code unchanged otherwise compliant; no
  weakened tests; no hard-coded RGB; purity confirmed.)
- `review-quality:M1-F1` — CODE-QUALITY REVIEW / opus — APPROVED with 3 minor
  nits (docstring 1px→1.5px, SEMANTIC_STATES parallel list, style).
- `fix:M1-F1` — FIXER / opus — added tab_strip fixed-column mode (byte-identical
  to the old inline loop, empirically verified), refactored combat_setup, added
  regression test, derived SEMANTIC_STATES, fixed docstring — DONE (841 collected
  exit 0). Commit `fa72af0`. Orchestrator re-verified targeted tests + diff.

### M1-F2 track['kind']/track['size'] stamps
- `build:M1-F2` — ORCHESTRATOR-IMPLEMENTED (lean; mechanical 2-stamp change),
  TDD test_track_stamps.py — smoke gate caught an IrMissile `.weapon` crash,
  fixed (guard + weapon_id fallback). Commit `cda32d3`.
- `verify-spec+nocheat:M1-F2` — REVIEW / opus — fog verdict CLEAN (no truth
  leak); REJECTED on a missing third stamp site (`_inject_elint_tracks`).
- `fix:M1-F2` — ORCHESTRATOR — stamped the ELINT site via shared helpers +
  ELINT-injection test. Commit `f2e5afd`. Smoke 70/70 re-verified.

### M1-F3/F5 Threat-Warning strip + Click-contact intel panel
- `build:M1-TaskA` — IMPLEMENTER / opus — threat_rows + contact_intel pure
  helpers + _threat_strip/_intel_panel draw methods + 11 TDD tests — DONE
  (857 passed, smoke 70/70). Commit `e401d67`.
- `verify-spec+nocheat:M1-TaskA` — REVIEW / opus — line-by-line incl. draw
  methods — APPROVED, fog-honest end-to-end, no truth leak, HOSTILE_KINDS sound.
- `review-quality:M1-TaskA` — CODE-QUALITY / opus — APPROVED, no Critical/
  Important; 4 minor cosmetic nits logged.

### M1-F4 Tube/battery status panel
- `build:M1-F4` — IMPLEMENTER / opus — tube_cells + _block cells row + EMPTY
  color + 6 TDD tests — DONE (864 passed; smoke caught+fixed a badge signature
  bug, then 70/70). Commit `c8d0d7e`. Orchestrator self-verified the diff
  (own-force-only, _block backward-compatible).

### M1 milestone gate — PASSED clean in one pass
- `gate:M1-fullsuite` — ORCHESTRATOR — pytest -q exit 0 (~864); smoke 70/70;
  Oniks-duel + missile-flight + SM-6 contracts green (bit-identical).
- `gate:M1-gametest` — GAME-TEST / opus — drove live headless battles, measured
  all surfaces + determinism (max delta 0.0 @15k steps), fog confirmed live,
  795 calls 0 exceptions — PASS. Left `tools/probe_m1_legibility.py`. (First
  dispatch died on an infra socket error; re-dispatched, succeeded.)
- `gate:M1-bughunt` — BUG-HUNT / opus — SAFE TO GATE; one LOW (scroll_list
  row_h<=0) fixed (`3c10066`).
- `gate:M1-nocheat` — NO-CHEAT / opus — CLEAN, no truth leak (helpers + draw).
- **M1 COMPLETE.** Branch tip after gate: `3c10066`.

### M2 — SEAD / Anti-Radiation Warfare
- `build:M2-T1` — IMPLEMENTER / opus — emitter ELINT channel (separate
  `emitter_contacts` store + resolver) + 6 tests — DONE (870). Commit `adf55b3`.
  Orchestrator self-verified diff (est_pos not truth; contacts.tracks untouched).
- `build:M2-T2` — IMPLEMENTER / opus — KH-31P ARM (reuse HarmMissile,
  is_hostile=False, launch_arm, victory credit, flyoff probe) + 10 tests — DONE
  (881). Commit `34088c7`. MEASURED: airframe over-reaches 110→130 km (HARM does
  too); locked envelope to measured kill@90/short@140.
- `verify-spec+physics+nocheat:M2-T2` — REVIEW / opus — APPROVED (physics
  measured not faked; CEP miss can't credit; byte-identical fingerprint).
- `review-quality:M2-T2` — CODE-QUALITY / opus — APPROVED; 2 minor nits fixed
  (`6c39bb2`).
- `build:M2-T3` — IMPLEMENTER / opus — enemy radar EMCON vs sensed ARM (ship +
  ground, fog-honest) + 8 tests — DONE (889). Commit `ba083aa`.
- `gate:M2-gametest` — GAME-TEST / opus — CONCERN: ship SPY-1 resurrected each
  tick (ARM can't kill it). Probe `tools/probe_m2_sead.py`.
- `gate:M2-bughunt` — BUG-HUNT / opus — HIGH-1 ARM-EMCON dead in play (feed
  filter); HIGH-2 ground radars out of ARM reach; LOW-4 attribution; rest CLEAN.
- `gate:M2-nocheat` (1st) — died on API Overloaded; re-dispatched.
- `gate-fix:M2` — FIXER / opus — fed ARM to enemy picture (detection-gated) +
  stopped ship-radar resurrection + 3 real-ARM e2e tests (RED→GREEN) + documented
  ground-radar gap — DONE (892, smoke 70/70, byte-identical). Commit `472bc6e`.
- `gate:M2-nocheat` (re-dispatch) — NO-CHEAT / opus — CLEAN, all 7 surfaces; ARM-
  EMCON + feed read only sensed tracks; determinism intact.
- **M2 sim COMPLETE + gated.** Remaining: M2-T4 player UI (armory/control/overlay)
  to make the SEAD capability playable; dedicated KH-31P mesh + photos (task #7).

### M2-T4 — player UI for the ARM
- `build:M2-T4` (1st) — died on a transient 529 Overloaded (0 tokens); re-dispatched.
- `build:M2-T4` — IMPLEMENTER / opus — armory ammo stepper + 3-way gated B-cycle +
  request_launch ARM branch + tactical_map emitter glyph/pick/select + hud weapon
  strip + ARM seeker readout + 27 TDD tests — DONE (919 passed, smoke 70/70,
  live-GL probe verified). Commit `d9c4f4b`. Orchestrator re-verified smoke + UI +
  Oniks-duel.
- **M2 COMPLETE + playable.** Branch tip `d9c4f4b`.

### Note: infrastructure
- Several agents hit transient API "Overloaded" (529) errors mid-run (1st M2
  no-cheat auditor, 1st M2-T4 implementer, 1st M1 game-test socket close). All
  re-dispatched and succeeded — no work lost (completed/committed work is never redone).

### Task #7 — KH-31P model + reference photos
- `model:kh31p` — MODELER / opus — `build_kh31p()` (slim ramjet body, ogive ARM
  seeker nose, 4 mid-body ramjet intake scoops = the Kh-31 signature, cruciform
  tail fins), registered in `_missile_meshes`/`DEDICATED_MISSILE_IDS` (in-flight
  ARM now uses the real mesh), `tools/shoot_kh31p.py`, test_models asserts —
  DONE (920 passed, smoke 70/70), 4-iteration render self-critique. Commit `31846a8`.
- Photos saved + ORCHESTRATOR-VERIFIED (viewed both): `kh31p_side.png` +
  `kh31p_front.png` in `Assets of oinks/New models 1 needs improving and updating/`.
  Both read as a Kh-31 (4 intakes visible), montage-style sky/sea backdrop.
- **Model-task status:** the NEW M2 weapon (KH-31P) is modeled + photographed per
  the user's ask. Future new models (M4 ASBM/swarm, M5 Buk/sub/etc.) get the same
  treatment when their milestones build them. The user's broader "improve the
  EXISTING models" ask is OPEN (the existing fleet of model photos lives in
  `Assets of oinks/updated models/`; a quality-lift pass is a separate task).

### M3 — Electronic Warfare + Terrain depth (IN PROGRESS)
- `build:M3-F1` (1st) — IMPLEMENTER / opus — ran 34m then user-stopped; left
  nothing committed (clean tree). Re-dispatched.
- `build:M3-F1` — IMPLEMENTER / opus — `sim/ew.py` J/S burn-through field model +
  `Radar.detects(jammers=())` byte-identical default + calibration probe + 10
  tests — DONE (930 passed, smoke 70/70, byte-identical). Commit `3637ea7`.
  MEASURED: EW_CAL=1.2e-13, default jammer collapses the 350 km ring to 175 km
  (half, monotonic). Orchestrator re-verified (EW tests + regression contracts +
  re-ran probe). The EW keystone — remaining M3 consumers queued.

- `build:M3-F2` — IMPLEMENTER / opus — enemy Growler (`JammerAircraft` +
  `_defend_jammer` no-cheat doctrine + world wiring so the field model bites the
  player radar) + 7 tests — DONE (937 passed, smoke 70/70, byte-identical).
  Commit `f6c4a77`. e2e: 300 km target dropped under jam, restored on lift.
- `review:M3-F2-nocheat` — NO-CHEAT + REGRESSION / opus — CLEAN / PASS; stations
  off belief (verified by moving the real radar to the map edge), no truth read,
  byte-identical to parent via worktree digest. No fixes needed.

- `bg-task:jammer-model` — (spawned follow-up) — `build_jammer()` Growler mesh +
  map glyph + jammer_pod palette + 87 tests — landed uncommitted; orchestrator
  VERIFIED (tests + smoke green, additive) + COMMITTED `c2686e3` + shot reference
  photos (`jammer_side/front.png`, orchestrator-viewed, reads as a Growler).
- `build:M3-F3` — IMPLEMENTER / opus — ELINT bearing-sigma elevation under jam
  (`noise_floor_at` + `ElintReceiver.update(jammers=)` sigma scaling, byte-
  identical default) + probe + 8 tests — DONE (smoke 70/70, bit-identical
  default). Commit `b3ca1cb`. K=1.0 (24-seed probe; player still localizes).
  Orchestrator re-verified.

### Next (M3 remaining + M4–M6)
- M3 remaining: player drone EW pod (symmetric jamming — player jams the enemy
  net so a salvo leaks), JAMMED-band UI + emissions meter, HeightField refactor +
  terrain uplift + seeded map presets.
- M4 (ASBM + swarm), M5 (fleet/sub/amphibious/scoot/CBR/decoys), M6 (campaign/
  scoring/salvo/auto-warp/presets) — each a coherent gateable milestone; resume
  from this report + the last commit. Future new models (ASBM/swarm/Buk/etc.) get
  the build-mesh + reference-photo treatment (task #7) when their milestones land.


---

## SESSION 2026-07-03 — overnight autonomous playtest + UI-unlock (Fable 5, lean mode)

**Headline:** the game's built content is now REACHABLE. Nine commits: the
inherited WIP verified+checkpointed, 6 real bugs fixed (each probe-measured,
each regression-locked), and the three biggest deferred UI passes shipped —
the four-page setup screen (every M2-M6 feature exposed), the CAMPAIGN mode
(hub + menu + CONTINUE CAMPAIGN), and the submarine/ASW player UI (U buoy-drop
mode, K ASW launch, map glyphs). Campaign escalation now stages the M5 threat
axes with their counters. Full suite green (known phase5b order-flake passes
in isolation), smoke 84 PASS, default-battle digest byte-identical through
every commit (`7d5716325a..06add`).

Commits (oldest first): `61c9d7e` WIP checkpoint (multi-AWACS/radar/drone
counts, campaign battle-0 seed, defeat-ends-campaign, antenna double-count
fix) -> `bce0f48` ASW surround-gate fix -> `5711e69` four-page setup ->
`a69ee81` grade-tier/resupply/TOT fixes -> `846a546` campaign UI ->
`8f19b2e` sub/ASW UI -> `38c3cc2` staged escalation -> `1ea6771` map label
collision -> `da9c762` render stand-ins + mesh aliases.

**Probe sweep (all PASS):** playtest_combat (core loop, storyboard),
playtest_killchain (SAR find -> hi-lo -> SM-2 intercept @165.8 km),
acoustic ASW (detection bands + cross-fix quality; found+fixed the 4-buoy-box
false-kill), amphibious (transit/LCAC/OBB kills), scoot (0.00 m errors,
stale-strike misses / fresh-strike hits), CBR (back-plot symmetry exact),
decoys (reflector pulls strikes to dirt), bughunt 6/6 incl. full-density
41-ship battle, scoring, campaign 3-battle chain, boot/menu/pause/map GL walk,
NEW: campaign flow end-to-end + ASW UI end-to-end GL probes.

**For the human playtest (STILL MANDATORY, still pending):** ENEMY page ->
SUBMARINES 1 + DEFENSE page -> SONOBUOYS 8 / ASW 2 for the acoustic duel;
CAMPAIGN from the main menu for the meta-loop. Balance flags: PAR rewards
passivity (500 s of nothing = B), swarm launch range 25 vs 40 km design,
back-plot buff feel, rear-band transports ~324 min sim transit.

## SESSION 2026-07-03 (evening) — "Wardroom Dusk" UI implementation + prototype research (Fable 5, lean mode)

**Headline:** the approved Claude-Design direction ("Wardroom Dusk", handoff
pack extracted to `Assets of oinks/ui_design/handoff/` — spec + 10 mocks) is
now IN THE GAME across every surface, in 7 render-only commits, with the sim
digest byte-identical through all of them (`7d5716...06add`) and the fog color
LAW strengthened (belief teal / own green / hostile dusk-red / brass =
selection+weapons only). Plus 4 standalone HTML prototypes for the NEXT
design round in `Assets of oinks/ui_prototypes/` (research-cited, not wired
into the game).

Commits (oldest first): `cab83bc` A1 token layer (palette port, plate/brass/
hint chrome, BELIEF teal for estimates, brass locked-target bracket) ->
`5b35ce4` A2 setup grouped plates (2-col grid, chip headers, boxed tab rail,
brass START key) -> `2dbb62e` A3 AAR grade plate + VALUE-vs-PAR table (real
compute_par bar per row; mock's fake ROUNDS-PAR + wrong LEAK/BACK-PLOT
directions corrected; D-shame + S-glow) -> `0f0bbf7` A4 campaign hub (ladder
chips, ledger bars, intel plate + DERIVED escalation caption; mock's false
'NO RESUPPLY' copy corrected) -> `38d62b0` A5 battle HUD (platform plate w/
status badge + tube boxes + in-plate EMCON, ink .93 calibration, INBOUND
ranked cards w/ TTI drain bars, clock chip, CAM chip; banned 'S-300 ASSIGNED'
dropped) -> `29a1554` A6 map symbology recolor (+ fixed pre-existing
miscolor: friendly radar stations drew in enemy red) -> `b6ff789` F1 overlay
two-column (one-column had outgrown 1080p).

**Gates (every commit):** targeted tests + smoke_combat 84 PASS exit 0 +
digest byte-identical + screenshots regenerated (tools/shoot_ui_reference.py)
and orchestrator-reviewed against the mocks. Honest test updates where the
DESIGN changed (ledger tuple shape, EMCON-in-plate containment regression);
no logic assertion weakened.

**Full suite (pytest -q -n auto): ONE real failure, PRE-EXISTING, not UI:**
`test_pantsir_model.py::test_width_approx_3m` — the morning model-readability
pass (1e912d6) moved the Pantsir canister packs outboard to 3.89 m vs the
3.0 m ±20% reference pin (real vehicle ≈3.13 m). Filed as a spawn-task chip;
needs a canister-offset re-tune, NOT a tolerance bump. (4 other pytest-cache
entries were stale IDs from deleted tests; the phase5b flake passed this run.)

**Task B — prototypes for the next Claude-Design round** (each header
carries idea/sources/data-status; README.md summarizes):
01 shot-debrief card (why each round died; needs a per-round event log),
02 engagement-envelope bands + DLZ bracket (probe-measured bands exist),
03 threat-priority stack w/ real NTDS engagement modifiers (honest TODAY:
   own-interceptor pairing is own-truth), 04 sensor-confidence Q5..Q1 ladder
(pure display mapping over existing confidence data).

**Known nits (honest):** letter-tracking + the U+25B8/middot glyphs are
un-renderable on the fixed ASCII atlas (spaced/ASCII stand-ins used);
the map terrain palette (sea gradient / land tones per spec §2) is a
render-level pass NOT done here (chrome/symbology only); mock 02 main-menu
full restyle not separately implemented (token layer carries it).

## SESSION 2026-07-03 (daytime) — live-playtest bug burst + physics realism pass

The user played; every report was a real engine bug (3/3):
- 'I can't intercept the missiles' -> S-300/Buk could NEVER engage strike
  rounds (_find_air_entity never searched world.missiles) + silent refusals.
  Fixed 28d119f. Measured: 48N6 kills a 50 m Tomahawk passing 20 km from the
  site (27.7 m fuse); 35+ km wave-top shots are honestly out of energy
  (matches the real S-300's ~25-40 km low-alt envelope; loft left AS TUNED).
- 'the Pantsirs should be intercepting... why why why' -> the multipath
  tracking error was an ANGLE (3 mrad @ 20 km) implemented as flat 60 m at
  ANY range: point defense at 5 km chased long-range noise with an 8 m fuse
  (12-round magazine for ~1 kill, a leaker impacting every seed). Fixed
  fe8c204 (range-scaled sigma, capped at the calibration range). Measured:
  on-target salvos now die 3-6.3 km out, zero structures lost, all seeds.
  Duel bands + digest UNCHANGED.
- Zircon realism ('the missiles don't look accurate') -> per-weapon descent
  profile fields (3d5f287): M5.5 @ 20 km combat-validated cruise, late steep
  dive, FULL-LEG PN; measured HIT 5 m at Mach 4.5 (was: 159 m/s crawl/miss).
  Lo-lo: M4.5 hits to ~90 km, honest fuel death beyond.
- UX: LOW TGT ~22 km dashed honesty ring on the S-300 map envelope (bed9129),
  F1 overlay now draws over the map (24e07f9), unfitted-vs-empty hints for
  buoys/ASW (9087bf4).
Note: two long audit agents were killed by the user's ESC ~2 h in; a scoped
sim-logic reviewer was relaunched at session end.

**Scoped adversarial logic review (Opus, post-ESC relaunch): CLEAN.** Damage
sweep double-hit/dead-entity/self-hit guards correct; is_hostile + isinstance
two-sweep gating internally consistent (ASBM correctly hits ships, never enemy
structures); all kill rolls on seeded streams, no wall-clock/set-iteration
hazards; CIWS/Pantsir Pk math clamped+guarded. ONE known nit (deliberately
NOT fixed — it would shift the byte-identical baseline for a 0.8% cosmetic
step): sim/physics.py speed-of-sound has a 2.3 m/s discontinuity at the 11 km
tropopause boundary (hardcoded 295.1 vs computed 297.4). Fix alongside the
next argued physics change: set the stratosphere constant to 297.4.
