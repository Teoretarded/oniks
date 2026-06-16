# Implementation Handoff — Smarter/Bigger COMBAT Mode

**Read this first.** This folder is a self-contained implementation-research bundle
for a *fresh* Claude Code chat (you have the repo, but none of the prior design
conversation). It specifies a batch of new features for the COMBAT mode of this
coastal missile-combat game, each researched down to file-level implementation
sketches + test contracts. Build straight from it.

## How to use this bundle
1. Read this README (orientation + the non-negotiables + how to build).
2. Read `ROADMAP.md` — the phased build plan, dependency map, consolidated UI
   plan, cross-cutting risks, and the **recommended first milestone**.
3. For the feature(s) in your milestone, read the matching `NN_*.md` spec.
4. Build one feature at a time, TDD, behind the existing regression contracts.

## Spec index
| File | Cluster | Features |
|---|---|---|
| `01_anti_radiation_warfare.md` | SEAD/DEAD: player Kh-31P ARM, emitter-SIGINT channel, enemy wild-weasel ARM, ARM countermeasures | 4 |
| `02_top_attack_asbm_loitering_munition_swarm.md` | Quasi-ballistic top-attack AShM; loitering swarm w/ simultaneous time-on-target | 2 |
| `03_submarine_warfare_and_asw.md` | Enemy diesel sub + Kalibr salvo; player sonobuoys + missile-origin datum | 2 |
| `04_electronic_warfare.md` | Two-sided jamming: `sim/ew.py` field model, enemy Growler, player EW pod, JAMMED UI | 6 |
| `05_new_enemy_ship_classes_amphibious_landin.md` | Ground-attack / air-defense / general / carrier / flagship classes + amphibious landing lose-path | 8 |
| `06_relocatable_tel_mid_sam.md` | Shoot-and-scoot TEL, Buk mid-SAM (2 rounds), counter-battery radar, decoy emitters | 4 |
| `07_campaign_scoring_auto_time_warp_salvo_ke.md` | Campaign ledger, after-action scoring, event-aware auto-time-warp, salvo/ripple key, status panel | 5 |
| `08_high_quality_ui_ux_system.md` | The cohesive high-quality UI system + every new surface | 12 |
| `09_terrain_graphics_then_presets.md` | Improve existing terrain/graphics, then seeded map presets | 1 |
| `ROADMAP.md` | Lead-architect synthesis: dependency map, 6 milestones, UI plan, risks, recommended-first | — |

Each spec feature is written against the four required lenses the project owner
demanded: **WEAPON/system → PLATFORM it launches from → SENSORS it uses / that
detect it → AI BRAIN (how the enemy commander uses or counters it)**, plus player
UX, UI needs, game-model mapping, a file-level implementation sketch, test
contracts, and counters/balance.

---

## Codebase orientation (what a fresh chat needs to know)

A single-player, physics-honest, fog-of-war coastal missile-combat game. Pure-numpy
simulation (GL-free under `sim/` and `world/`) + a custom OpenGL renderer (`game/`).
Python 3.11, pytest. Run tests: `python -m pytest -q` (~815 tests, ~6 min). Run the
combat smoke gate: `python tools/smoke_combat.py` (70/70, exit 0). Headless probes
live in `tools/` (e.g. `probe_base_attack.py`, `compare_s300_rounds.py`).

**The game in one breath:** you command a coastal "Bastion" (Oniks/Zircon anti-ship
missiles on a Bastion TEL, S-300/40N6 SAMs on a TEL, Pantsir point-defense, a recon
drone, an 18 m ground radar) defending against an enemy carrier group (destroyers
w/ SM-2/SM-6/CIWS/Tomahawk, fighters w/ AIM-9X/HARM/JASSM, an AWACS). Loop: recon
(drone SAR imaging + passive ELINT triangulation + RWR) pierces fog of war to
localize the fleet, then fire LOW (sea-skim) to leak under the SM-2 horizon, while
managing your own emissions so the enemy can't back-plot + strike your TELs. Win =
all enemy ships + airfield + radars dead; lose = your launcher TELs destroyed.

### Key files & data models (reuse these — don't reinvent)
- `sim/arsenal.py` — pure-data weapon defs: **`WeaponDef`** (ramjet cruise missiles:
  Oniks/Zircon), **`SamDef`** (SAMs, with per-round loft fields: S-300/SM-2/SM-6/40N6/
  Pantsir-57E6), **`StrikeDef`** (land-attack/ARM: Tomahawk/JASSM/HARM), `LauncherDef`.
  New weapons are usually a new def + reuse of an existing flight machine.
- `sim/missile.py` — `Missile`: ramjet cruise flight (hi-lo/lo-lo, descent, terminal
  PN, weave). `DESCENT_BASELINE_MACH` scales descent authority by cruise Mach.
- `sim/sam.py` — `SamMissile`: catapult/boost/loft/terminal SAM flight + multipath
  noise (the "go-low-to-survive" physics). `StealthTargetSam` for low-SNR (drone) targets.
- `sim/strike.py` — `StrikeMissile` (Tomahawk/JASSM cruise) + **`HarmMissile`** (passive
  anti-radiation seeker — homes on any `Radar`, freezes + seeded CEP on silence,
  re-locks on re-emission). The player ARM reuses `HarmMissile` verbatim.
- `sim/radar.py` — `Radar.detects(pos, size_class)`: 4/3-earth horizon + terrain LOS +
  range-class gating. `RadarNetwork`. The most-tested seam — EW plugs in here.
- `sim/recon.py` — `ReconDrone`, `ElintReceiver` (least-squares bearing triangulation,
  with geometry/consistency/range gates), `RwrReceiver` (SPIKE/LOCK), `SarSensor`.
  The acoustic ASW receiver reuses the ELINT solver.
- `sim/commander.py` — **`EnemyPicture`** (the sensor-only enemy "brain": emitter ESM
  fixes, missile/drone tracks, launch-site back-plot, clusters) + **`EnemyCommander`**
  (doctrine: defend / blind (SEAD) / kill; AWACS EMCON; fighter tasking). **This is
  the AI brain — it reads ONLY EnemyPicture, never truth.**
- `sim/enemy_defense.py` — `ShipDefense` fire control (SM-2 anti-missile, SM-6 area
  defense `_try_sm6_launch`, drone hunt, CIWS). `SM2_MAX_INFLIGHT=4`, `SM6_AREA_MIN_ALT_M=1500`.
- `sim/enemy_air.py` — `Fighter` (nose radar + RWR-driven evasion), `Awacs` (EMCON), `AirBase`.
- `sim/enemy_ships.py` — `Destroyer`, `Carrier`. New ship classes subclass these.
- `world/combat.py` — `CombatWorld`: builds the order of battle, steps everything,
  feeds the EnemyPicture (`_feed_enemy_picture`), executes commander orders,
  win/lose. `_assign_air_threats` (fighter evasion), `_emitters`, `_inject_elint_tracks`.
- `world/combat_config.py` — **`CombatConfig`** (LOCKED frozen schema — new fields need
  integrator sign-off and must default OFF/0 to keep regressions bit-identical) +
  `clamp_config`. Setup/armory UI reads it.
- `world/generation.py` — `terrain_height_scalar` (needs a `HeightField` refactor +
  `terrain_blocks` LOS for new maps — see spec 09; neither exists yet).
- `game/sandbox.py` — the in-battle state: input → launch, effects, camera, HUD wiring,
  the `B`/`TAB`/`[`/`]` controls, hint system (`show_hint`).
- `game/hud.py`, `game/states.py` — HUD + UI chrome primitives (`draw_panel`,
  `draw_header_rule`, grid constants). The UI spine for spec 08.
- `game/controls.py` — input mapping, `TIME_SCALES` (1–16x) + pause (auto-time-warp builds on these).
- `tests/` — pytest; `tools/smoke_combat.py` — the combat smoke gate.

---

## NON-NEGOTIABLES (every feature must honor these — they are how this game stays good)

1. **Physics, not dice.** Hit/miss must EMERGE from simulated physics (guidance,
   fuse/OBB crossing, radar horizon, terrain LOS, multipath elevation noise, loft/
   terminal-handover geometry) + measured statistical bands — **never a flat `random()
   < Pk` roll.** (The one legacy exception, the CIWS burst roll, is documented and not
   to be copied.) New stochastic effects model a physical quantity (dispersion, CEP,
   SNR) with a seeded noise process, calibrated to a measured band via a probe.
2. **Fog of war / no cheat.** Every AI decision AND every fog-gated UI element reads
   ONLY sensor-derived belief (`EnemyPicture` / `ContactBoard` / `ElintReceiver` /
   RWR-lock), NEVER a real entity's position/fuel/alive flag. (An adversarial review
   previously caught a fighter-evasion routine reading a SAM's true position — it was
   rerouted through the sensor track. Don't repeat that.) The UI must render
   sensor-estimates in the faded "contact" idiom and friendly truth in cyan/green so
   the two never look alike (or it leaks the fog).
3. **Determinism.** All RNG is a seeded child stream: `np.random.default_rng([seed, tag])`.
   Tags 3–7 are taken; allocate new tags centrally (see ROADMAP risk #4). Two same-seed
   worlds must stay bit-identical over thousands of steps. New config fields default
   OFF so the out-of-the-box battle is byte-identical to today.
4. **Regression contracts never weakened.** The Oniks-vs-SM-2 duel
   (`tests/test_sm2_statistics.py`) and the Oniks flight/descent are LOCKED — new
   features must leave them bit-identical (a new SamDef/WeaponDef touches none of the
   duel; a shared-helper refactor must keep `process_missile_track` etc. bit-identical).
   If a planned test can't pass honestly, report BLOCKED — never widen a tolerance.

---

## How to build it (recommended workflow for the receiving chat)

This project was built with a disciplined loop; keep it:
1. **Pick ONE feature** from the recommended milestone (start with Milestone 1 —
   Legibility Foundation; it's lowest-risk and unblocks everything).
2. **TDD.** Write the failing test FIRST from the spec's test contract; watch it fail
   for the right reason; write minimal code; watch it pass. Pure logic (UI row
   builders, swarm speed solver, EW burn-through, scoring) is headless-testable — the
   project's convention is a `FakeText` draw-call recorder for UI helpers so GL never
   enters tests.
3. **Measure, don't guess** for any physics (new trajectory, EW curve, CEP): write a
   `tools/probe_*.py` that prints numbers BEFORE locking the envelope test (mirror
   `tools/compare_s300_rounds.py` / `probe_zircon_traj.py`). Lock with a TWO-SIDED band.
4. **Verify each milestone with your own eyes:** full suite green + `smoke_combat.py`
   70/70 + the relevant probe numbers. Confirm the Oniks duel + determinism stay
   bit-identical.
5. **Adversarial review** (the project's standing rule): when a feature feels done,
   run a fresh agent to re-audit it for no-cheat / regression / determinism, a code-
   quality reviewer, and a game-test agent that measures the new behavior in a real
   battle. Fix findings; re-review. The automated no-cheat checks DON'T cover every
   path — line-level audit is what catches truth-leaks.
6. **Document** each change in `docs/combat_build_log.md` (the project's flight recorder).

> Note on scale: this is a large batch. Build it **milestone by milestone** (see
> ROADMAP §2) — each is a coherent, shippable, playtestable increment. Don't fan out
> parallel implementers on the shared repo (they corrupt each other); parallelize
> research/reviews, implement sequentially.
