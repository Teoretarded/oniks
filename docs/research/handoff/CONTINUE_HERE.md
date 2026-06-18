# CONTINUE HERE — combat build handoff (2026-06-18)

Hand-off for a FRESH chat to continue the overnight combat build using **loops + workflows**
(Fable Method). Branch: `feat/combat-expansion` (off `main` — do NOT touch main). Read
`HANDOFF_README.md` + `ROADMAP.md` + the per-feature `0N_*.md` specs first.

## FIRST THING TO DO
Run the full suite to confirm the last commit is green (it was committed on its workflow
gates after a user interrupt, NOT a personal full-suite run):
```
python -m pytest -q            # expect exit 0, [100%]
python tools/smoke_combat.py   # expect 70/70 PASS, exit 0
```
If `tests/test_phase5b_e2e.py::test_backplot_jassm_strike_reaches_defeat` fails, it's a
KNOWN pre-existing load-sensitive flake — re-run it isolated to confirm green; it is not a
regression (the n_subs=0 path is byte-identical).

## SHIPPED + COMMITTED so far (newest last)
- **M1, M2** (prior session): legibility UI; SEAD/Kh-31P ARM + emitter SIGINT.
- **M3 (gameplay complete)**: EW F1–F5 (field model, Growler, ELINT-sigma, player pod,
  JAMMED UI), HeightField refactor (`17d95b0`), close-range terrain_blocks LOS fix
  (`8ca8931`), seeded map presets (`57097ec`). *F1/F2 terrain/graphics visual DEFERRED.*
- **Zero-bias audit + fixes** (`57fd0a8`, `8ca8931`): HIGH fighter no-cheat truth-track,
  LOW ship friendly-fire, LOW EW floor, MEDIUM terrain LOS — all fixed. Report:
  `docs/reviews/zero_bias_audit_2026-06-18.md`.
- **M4**: Bastion-K ASBM (`d01a63c`); loitering swarm (`fcafe0f`) + per-weapon STALL_SPEED
  lethality (`53b2c9e`).
- **M5 (3 of 8)**: Buk mid-SAM (`0c8098a`); enemy ship classes + CEC flagship + fleet mixer
  (`c553508`); submarine/ASW **sim** (`7edd68d`).

## REMAINING WORK (build in this order; each = one Workflow, gated + committed)

### M5 — 5 features left
1. **Amphibious + timed beachhead lose-path** (spec `05_*.md`, "Amphibious" + "Amphibious
   landing as a TIMED lose condition" + the fleet-mixer transports band, already scaffolded
   in `world/spawn_zones.py`). Self-contained 2nd lose-path. `n_transports=0` byte-identical.
2. **Back-plot reliability + shared `back_plot_surface()` helper** (ROADMAP §5 item 1; spec
   `06_*.md` deps). EXTRACT the back-projection from `sim/commander.process_missile_track`
   into a module-level helper (BIT-IDENTICAL refactor) — this unblocks 3,4,5. The *reliability
   BUFF* (GAME_ANALYSIS §5: back-plot too timid) is BALANCE-CRITICAL (it's the enemy's only
   base-kill path — see memory `enemy-lethality-backplot`); keep it CONSERVATIVE + measured +
   flag for the user's playtest (don't make it unwinnable).
3. **Counter-Battery Radar** (spec `06_*.md` F3): uses the helper; early-warning threat strip +
   back-plotted shooter counter-fire cue. Low-risk, high-QOL. New tag `[seed,9]`.
4. **Shoot-and-scoot relocate** (spec `06_*.md` F1): relocatable Bastion/S-300/Buk TELs;
   needs the back-plot reliable to have something to dodge. New tag `[seed,11]`.
5. **ESM decoys + corner-reflectors** (spec `06_*.md` F4): spoof the enemy ESM/back-plot.
   New tag `[seed,10]`.

### M6 — 5 features (spec `07_*.md`; map presets already shipped in M3)
1. Salvo / ripple-fire key (sandbox scheduler; `[seed, battle_idx, 9, ordinal]` FAN stream).
2. Auto-time-warp (`game/timewarp.py` TimeWarpDirector; **fog-safe** inbound drop predicates).
3. After-action scoring (`game/scoring.py` ScoreCard + AAR — the one screen allowed to reveal
   truth; deterministic per-seed PAR).
4. Campaign (`game/campaign.py`; `derive_seed(seed, battle_idx)`; persistent ammo/base-damage;
   `initial_state=None` path bit-identical).
5. Mission briefing screen.

### DEFERRED PASSES (do LAST; GL/visual — verify with smoke screenshots + USER PLAYTEST)
- **UI-WIRING PASS (functional UI deferred from sim features)**: submarine controls+awareness
  (sonobuoy platform + LMB-drop, ASW launch keybind + sandbox plumbing, `game/tactical_map.py`
  sub-chevron + buoy glyphs/rings/bearing-rays + launch-datum marker, `game/hud.py` sonobuoy
  panel + ASW ammo + "SSK: <state>" + launch-transient banner); **swarm tasking panel** + the
  swarm tab is wired but the panel UI isn't; **ASBM** ballistic-arc preview + ToF/track-age
  strip; JAMMED-wedge translucent fill. World verbs already exist + tested — this is rendering +
  input only. (`game/*` import pygame at top → untestable headless; verify via smoke screenshot.)
- **MODEL PASS** (meshes + REFERENCE PHOTOS — the user's standing requirement): generate meshes
  for ASBM, swarm loiterer + SwarmPod, Buk TELAR + 9M317/9M338, flagship/AAW/ground-attack ship
  glyphs (+ HVU star), submarine + Kalibr; render detailed side/front photos and SAVE them
  LABELED to `C:\Users\teoti\OneDrive\Desktop\Assets of oinks\New models 1 needs improving and
  updating\` (pattern: `tools/shoot_kh31p.py` → `kh31p_side.png`/`kh31p_front.png`). Also the
  user's "improve EXISTING models" ask (existing photos in `Assets of oinks\updated models\`).
  Use reference-driven modeling (gather real-world refs → top-10 signatures → build → critique).
- **F1/F2 terrain/graphics visual** (spec `09_*.md`): `_colorize` material grading + ocean/sky/
  foam/fog + Low/High toggle. Render-only, hard regression gates.

## OPEN BALANCE / KNOWN ITEMS (for the user's hands-on playtest)
- Back-plot reliability buff (above) — feel-tune with playtest.
- Swarm tube-launch range ~25 km vs ~40 km design (Oniks-sized RIDEOUT_THRUST on the 55 kg
  airframe → boost overshoot); a per-weapon ride-out/boost pass restores design range. See memory
  `missile-gains-tuned-for-oniks`.
- Mandatory ~15-min hands-on COMBAT playtest (memory `playtest-before-polish`).

## CONTRACTS (every feature — never violate)
- **physics-not-dice**, **fog/no-cheat** (AI + fog-gated UI read sensor belief only),
  **determinism** (`np.random.default_rng([seed, tag])`), **regression never weakened**
  (Oniks-vs-SM-2 duel `tests/test_sm2_statistics.py` + default battle BYTE-IDENTICAL; every new
  CombatConfig field defaults 0/OFF — prove with a same-seed multi-thousand-step digest).
- **Determinism tags USED**: 3 fleet, 4 recon, 5 commander, 6 pantsir, 7 enemy-radars,
  8 player-ARM/EW/Buk, 12 map-terrain, 13 sub, 14 sonar. **Free/reserved**: 9 (CBR), 10 (decoys),
  11 (relocate), 15+. Allocate centrally; do not reuse 8.

## METHOD (how to run it in the new chat)
Per feature, one **Workflow**: TDD implementer → spec-compliance review (re-runs tests, no-cheat/
byte-identical proof) → fixer → code-quality review → fixer. Then the orchestrator personally gates
(full suite + smoke + the feature's probe) and commits with a conventional message. Defer pygame UI
+ meshes per the passes above. The committed workflow scripts under `tools/wf_*.js` are reusable
templates. Spawn TWO independent zero-bias reviewers periodically (the audit pattern in
`tools/wf_zero_bias_audit.js`) — re-run after M5/M6 to catch regressions.
