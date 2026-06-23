# Critique dossier — M5 #5 + M6 combat expansion (branch feat/combat-expansion)

Adversarial council input. Read the ARTIFACTS in full yourself; this orients you
+ lists the contracts, the test results I observed, the known deferrals, and the
MISSING evidence (UNVERIFIABLE seeds). Do NOT trust my summaries — re-run/re-read.

## GOAL / SPEC
Ship the gameplay-LOGIC of the M5/M6 combat-expansion features. Specs:
`docs/research/handoff/06_relocatable_tel_mid_sam.md` (F4 decoys),
`docs/research/handoff/07_campaign_scoring_auto_time_warp_salvo_ke.md` (M6),
`docs/research/handoff/ROADMAP.md`. Project log + contracts:
`docs/combat_build_log.md`.

PROJECT CONTRACTS (non-negotiable, from the build log + ROADMAP):
- **physics-not-dice** — outcomes emerge from simulated guidance/fuse/geometry,
  never flat Pk rolls.
- **fog / no-cheat** — every AI + fog-gated UI decision reads sensor-derived
  belief (EnemyPicture / ContactBoard / ELINT), NEVER ground truth
  (`world.missiles` enemy rounds, true ship pos). End-of-battle AAR may read truth.
- **determinism** — all RNG is a seeded `np.random.default_rng([seed, tag])`
  child stream; tags 3-16 are allocated (3 fleet/4 recon/5 commander/6 pantsir/
  7 enemy-radars/8 ARM-EW-Buk/9 CBR-salvo/10 decoys/11 relocate/12 map/13 sub/
  14 sonar/15 amphibious/16 scoring-PAR). No wall-clock in sim/world.
- **byte-identical default** — every new CombatConfig field defaults 0/OFF; the
  default battle is bit-identical (same-seed multi-thousand-step digest == HEAD).
  Campaign adds NO new frozen config field (state rides a separate carrier).
- **regression never weakened** — the Oniks-vs-SM-2 duel (test_sm2_statistics)
  + the default-battle digest are bit-identical; a test that can't pass honestly
  is reported BLOCKED, never loosened.

## ARTIFACTS (read in full)
- `sim/decoys.py` (DecoyEmitter — empty-ranges bait; CornerReflector; pure
  `biased_back_plot`)
- `game/salvo.py` (SalvoQueue scheduler + ready_tube_count/fan_offset/tot_delays)
- `game/timewarp.py` (TimeWarpDirector + the 3 fog-safe drop predicates)
- `game/scoring.py` (ScoreCard / compute_scorecard / compute_par / grade)
- `game/campaign.py` (CampaignState / derive_seed / next_config / world_snapshot
  / initial_state_for / apply_resupply / advance / save / load)
- `world/combat.py` — `apply_initial_state` (~line 1093, campaign carry-forward
  ingest), the decoy/reflector wiring (`_build_decoys`,
  `_inject_reflector_backplots`, `_emitter_by_id`, the `_feed_enemy_picture`
  emitter accrual ~2258), `_feed_enemy_picture`.
- Tests: `tests/test_decoy_emitter.py`, `test_corner_reflector.py`,
  `test_salvo.py`, `test_timewarp.py`, `test_scoring.py`, `test_campaign.py`,
  `test_battery_panel.py`. Stress probe: `tools/probe_bughunt_m6.py`.

## TESTS + RESULTS I OBSERVED (re-run them; do not trust this)
- Full suite `python -m pytest -q -n auto`: exit 0, 1325 collected, no failures (481s).
- `python tools/smoke_combat.py`: exit 0, 80 checks.
- `python tools/probe_bughunt_m6.py`: 6/6 PASS — all-features-on (41 ships/85
  rounds/3000 steps) crash-free+finite; same-seed determinism max delta 0.0 over
  1500 steps; zero-force edge clean; fog no-leak; passive 20k-step loop clean
  (defeat NOT reached in window); campaign 3-battle chain (distinct seeds + ledger
  carried).
- Byte-identical digest `python tools/wf_m5_digest.py` = `7d5716325a234607...`
  == HEAD for salvo/status-panel/auto-warp/campaign. Scoring diff is game/* only
  (no sim/world). Duel test_sm2_statistics bit-identical throughout.

## KNOWN DEFERRALS / SELF-FLAGGED WEAKNESSES (scrutinize whether these hide gaps)
1. SALVO TOT on a SINGLE surface aim point: all ranges equal -> `tot_delays`
   collapses every delay to 0 -> a Bastion TOT salvo fires ALL ready tubes in ONE
   tick (no stagger). Documented; the pure helper is correct. Real bug or ok?
2. SALVO early-release-stops-queue (KEYUP) NOT wired — `SalvoQueue.cancel()`
   exists but controls dispatch only KEYDOWN. Spawned as a follow-up.
3. AUTO-WARP `intercept_window` Pantsir-engaging clause: was inert (Pantsir had no
   engaging flag); commit 95aedbe wired a gun-only drop. Verify it is real now.
4. STATUS PANEL expanded board: `_battery_row` docstring promises a per-tube
   reload gauge it does NOT draw (the compact strip does). Data is correct+tested.
5. CAMPAIGN UI: hub screen (CampaignHubState) + main-menu CAMPAIGN item + the
   end-overlay NEXT BATTLE are NOT built (deferred UI-wiring pass). The pure core
   + world ingest ARE built+tested.
6. CAMPAIGN carry-forward is the world-level offensive pools (oniks/zircon/asbm/
   kh31p/s300_48n6/s300_40n6) + structure hp ONLY; Pantsir per-unit + Buk/swarm
   rearm fresh each battle (documented v1 simplification).
7. SCORING PAR thresholds (_PAR_BASE_*) are a deterministic SCAFFOLD, not
   balance-tuned against playtest data.

## GIT (this session)
`7eca77b` salvo, `cea9e91` status panel, `9a3cb21` wf-runner, `7339c70`+`95aedbe`
auto-warp, `a0a745e`+`01d2ab5` scoring (+tag fix), `36a021f` decoys, `9073561`
campaign core, `98744bc` bug-hunt probe.

## MISSING (UNVERIFIABLE seeds — name these if a claim needs them)
- NO live human playtest (the mandatory ~15-min hands-on COMBAT playtest is still
  pending; balance/feel of salvo, auto-warp pacing, scoring grades, campaign
  escalation is unjudged by a human).
- NO GL screenshot review of the new HUD surfaces (salvo readout, battery panel,
  scoring end-overlay) beyond "smoke renders without crashing".
- Campaign escalation + resupply + PAR thresholds are UNTUNED (no playtest data).
- The "deferred UI" features (campaign hub, salvo KEYUP, expanded-board gauge)
  have no end-to-end player-facing verification.
