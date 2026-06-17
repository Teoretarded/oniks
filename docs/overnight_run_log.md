# Overnight Autonomous Build — Run Log

> Branch: `feat/combat-expansion` (off `master`). Method: Fable Method
> (implementer + 2-stage hostile review per feature; milestone gates verified by
> the orchestrator; physics-not-dice / fog-of-war / determinism / no-weakened-
> regressions contracts). Source of truth: `docs/research/handoff/` specs +
> `ROADMAP.md` (6 milestones). Per-feature/per-milestone detail lives in
> `docs/combat_build_log.md`; this file is the chronological agent ledger.

---

## MORNING REPORT  (live — updated as work proceeds; branch `feat/combat-expansion`, do NOT touch `main`)

**Headline:** 2 of 6 milestones SHIPPED, GATED, and PLAYABLE overnight (M1, M2),
the new weapon's 3D model + reference photos, AND M3's EW CORE shipped + gated as
two reviewed features — the J/S burn-through field model AND the enemy Growler
that uses it to collapse the player's radar (M3 in progress; the player can already
SEAD-ARM the Growler via M2 — the two-sided EW↔SEAD loop closes). Full test suite
**937 passed, exit 0**;
combat smoke **70/70 exit 0**; the locked regression contracts (Oniks-vs-SM-2 duel,
Oniks/SAM flight, same-seed determinism, byte-identical out-of-the-box battle) all
held BIT-IDENTICAL throughout. Every feature went through the Fable-Method loop
(opus implementer → hostile spec/physics/no-cheat review → code-quality review →
fixer) and every milestone through a personal gate + an adversarial agent fleet
(game-test in live battles + bug-hunt + no-cheat auditor).

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

### Next (M3 remaining + M4–M6)
- M3 remaining: player drone EW pod (symmetric jamming), ELINT bearing-sigma
  elevation under jam, JAMMED-band UI + emissions meter, HeightField refactor +
  terrain uplift + seeded map presets.
- M4 (ASBM + swarm), M5 (fleet/sub/amphibious/scoot/CBR/decoys), M6 (campaign/
  scoring/salvo/auto-warp/presets) — each a coherent gateable milestone; resume
  from this report + the last commit. Future new models (ASBM/swarm/Buk/etc.) get
  the build-mesh + reference-photo treatment (task #7) when their milestones land.

