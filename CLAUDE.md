# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

ONIKS — a standalone missile-warfare game in a to-scale 600×600 km world: a
coastal Bastion battery (Oniks/Zircon/S-300/Pantsir and much more) versus a
naval strike group with a sensor-honest AI commander. Fixed-timestep 120 Hz
float64 simulation + camera-relative float32 OpenGL 3.3 renderer. Python
3.11+; the only runtime deps are pygame-ce, PyOpenGL, numpy. All terrain,
models and audio are procedurally generated at first launch — there are no
art assets to install.

Active branch: `feat/combat-expansion`. Do **not** touch `main`/`master`.

## Folder split: code vs. documentation

ALL markdown docs, research, plans, run logs, and session evidence live in
**`../Markdown/`** (containing the old `docs/` and
`documentation and research/` trees — every path below is under it). The
game itself is only: `main.py`, `engine/`, `world/`, `sim/`, `game/`,
`models/`, `tools/`, `tests/`. When asked to "go through the codebase",
read the code folders; only open `../Markdown/` when the
task needs a plan, spec, run log, or research reference. New docs/research
you produce go inside `../Markdown/` too — never at repo
root or inside code folders.

## Commands

| Task | Command |
|---|---|
| Run the game | `python main.py` (or `run_game.bat`) |
| Full test suite (~1400 GL-free tests) | `python -m pytest -q -n auto` — **always `-n auto`** (pytest-xdist); serial takes ~22 min |
| One file / one test | `python -m pytest tests/test_missile.py -q` / add `-k name` |
| Only the tests your change touches | `python -m tools.select_tests --run` (static import-graph selection; `--since REF`, `--graph mod` to debug) |
| Combat smoke gate | `python tools/smoke_combat.py` (expect all-pass, exit 0) |
| Bit-exact battle replay | `python tools/replay_battle.py <ledger.jsonl> [--to-tick N]` — ledgers auto-record to `blackbox/`; F3 in-battle bundles a repro into `bug_reports/bug_NNN/` |
| Visual / perf gates | `python tools/screenshot_harness.py`, `tools/perf_harness.py`, `tools/shoot_sandbox_war.py`, `tools/perf_sandbox_war.py` |

## Project laws (non-negotiable; enforced by tests and review)

1. **Physics, not dice.** Hit/miss must emerge from simulated physics and
   measured statistical bands (tracking error, dispersion, seeker baskets,
   multipath) — never a flat probability roll.
2. **Fog of war / no cheating.** Enemy decisions read only the enemy's own
   sensor picture (`EnemyPicture` in `sim/commander.py`), never ground truth.
   The player's picture is the gated `ContactBoard` (`sim/contacts.py`).
   The `tools/probe_audit_*.py` family audits this per subsystem.
3. **Determinism.** Seeded, tagged RNG streams; same seed ⇒ byte-identical
   battles (proven by `state_digest` hashes and the `tools/wf_*_digest.py`
   gates). New RNG streams take the next free tag in `world/generation.py`
   (3–16 are taken); prefer zero-RNG designs — most recent features needed none.
4. **Regression contracts never weaken.** Locked tests (Oniks-vs-SM-2 duel,
   flight envelopes, same-seed determinism, out-of-the-box battle) must stay
   green bit-identically; new features default OFF in `CombatConfig` when
   they would change existing battles.
5. **GL-free sim.** Nothing under `sim/` or `world/` imports OpenGL; tests run
   headless. Mesh *building* (`engine/meshdata.py`) is pure numpy, GL upload
   (`engine/mesh.py`) is separate.
6. **Measure, don't guess.** Before tuning anything, find or write a
   `tools/probe_*.py` and read numbers; run logs in `../Markdown/docs/` record the
   measured evidence for every shipped feature.
7. **Implement directly.** The user wants solo implementation, not subagent
   fleets (recorded in `../Markdown/docs/combat_code_audit_2026-07-17.md`).
8. **Playtest before polish.** Gameplay features get a hands-on playtest
   before polish passes.

## Architecture

`main.py` owns THE loop: real time accumulates into fixed 120 Hz sim steps
(scaled by `time_scale`, capped at 64 steps/frame), rendering once per frame.
States (menu/sandbox/combat/campaign/settings/lab) live in `game/states.py`
and siblings.

| Layer | Role |
|---|---|
| `engine/` | GL primitives: window, shaders, lit-mesh renderer, particles, text, math3d, camera |
| `world/` | Terrain/ocean/sky/cloud generation, world constants (`world/generation.py`), `CombatWorld` (`world/combat.py`) and `world/sandbox_world.py` orchestrators, `CombatConfig` |
| `sim/` | Pure-numpy simulation: every weapon, sensor, aircraft, ship, sub, the enemy commander — GL-free |
| `game/` | Game states, HUD/UI, cameras, audio, tactical map, forensics, cinematic/walk mode |
| `models/` | Procedural mesh builders (one file per unit family) |
| `tools/` | ~145 headless probes, visual/perf harnesses, replay, digests |
| `tests/` | ~166 files; no conftest.py — fixtures are local |

**Locked conventions** (full list: `../Markdown/docs/superpowers/plans/2026-06-10-oniks-game.md`
§LOCKED CONVENTIONS): SI units, radians; X=east, Y=up, Z=north, heading 0=+Z
increasing clockwise; sim state float64, GPU data float32 produced only at the
render boundary after subtracting the camera eye; model space +Z forward at
real scale; matrices are numpy (4,4) column-translation uploaded with
`transpose=GL_TRUE`; vertex layout `[px py pz nx ny nz r g b]` float32 +
uint32 indices.

**Combat data flow:** `CombatWorld` builds the order of battle from
`CombatConfig` and steps everything → sensors fill the two belief stores
(`ContactBoard` for the player, `EnemyPicture` for the AI) → the enemy
commander (`sim/commander.py`, Find→Blind→Kill doctrine: ESM localization,
launch back-plot, HARM-before-JASSM, amphibious release) acts only on its
picture → weapons are data defs in `sim/arsenal.py` (`WeaponDef`/`SamDef`/
`StrikeDef`/`LauncherDef`) flown by a small set of flight machines
(`sim/missile.py` ramjet cruise, `sim/sam.py` + online replanning
`sim/flight_computer.py`, `sim/strike.py` Tomahawk/JASSM/HARM,
`sim/asbm.py`, `sim/swarm.py`, `sim/manpads.py`). A new weapon is usually a
new def + an existing flight machine, not new engine code.

## It probably already exists — check here before building

The project's history is full of "do X" requests where X was already built.
Search this table (and the docs map below) first.

**Game modes:** SANDBOX war with red-force director (`game/sandbox_war.py`,
`world/sandbox_world.py`, `game/director.py` — I on the map orders enemy
launches); fog-of-war COMBAT with 4-page setup, victory/defeat, after-action
grades (`game/combat.py`, `game/combat_setup.py`, `game/scoring.py`,
`game/combat_end.py`); CAMPAIGN with carried-over ammo (`game/campaign.py`).

**Hidden dev lab:** F3 on the **main menu** (F3 in-battle = bug report) →
asset inspector, missile workbench batch runner (`game/missile_workbench.py`
+ `tools/run_missile_workbench.py`), EFFECTS catalog, and the CINEMATIC tab:
first-person walk mode on 1:1 LiDAR-baked real terrain (Lauterbrunnen,
Yosemite — `game/cinematic.py`, `game/walker.py`), shoulder-fired MANPADS
(`sim/manpads.py`), and full ICBM launches (Sarmat/Minuteman III,
`game/cinematic_icbm.py`, GEMS/Lambert guidance, T targets a point);
and the TEST MAP tab (F8): the 6-DOF rigid-body test chamber — one
all-new test hopper on a bland flat plate, thrust at the nozzle, real
hover ceiling from atmosphere, tip-over/tumble failure demos
(`sim/sixdof.py`, `models/test_rocket.py`, plan + measured contracts in
`../Markdown/docs/plans/sixdof_plan_2026-07-17.md`, visual audit
`tools/shoot_test_map.py`). 6-DOF is TEST MAP ONLY until promoted.

**Simulation systems already in:** energy-model aero with induced drag and
autopilot lag (`sim/aero.py`); online flight computer that re-plans corridors
2–4×/s (`sim/flight_computer.py`) + reference optimal-guidance laws
(`sim/optimal_guidance.py`); WT-style subsystem damage model — modules,
flooding, ammo-scaled cook-off, zero RNG (`sim/damage_model.py`) with X-ray
hit cam (`game/hitcam.py`); radar honesty (scan cadence, seeker gimbal/LOS
lock-break, `sim/radar.py`); EW/jamming field (`sim/ew.py`); sea-state
clutter (`sim/clutter.py`); ELINT/RWR/SAR recon (`sim/recon.py`); decoys
(`sim/decoys.py`); counter-battery radar (`sim/counter_battery.py`);
ASW/sonobuoys/submarines (`sim/asw.py`, `sim/submarine.py`); amphibious
lose-path (`sim/amphibious.py`); air-to-air (`sim/a2a.py`); weather composer
UI + volumetric clouds (`game/weather_composer.py`, `world/clouds.py`);
salvo/ripple/time-on-target (`game/salvo.py`); event-aware auto time-warp
(`game/timewarp.py`).

**AI-facing introspection (built so an AI can verify the sim):**
`tools/probe_fc_transcript.py` — one JSON line per flight-computer replan
(every candidate corridor, cost, choice), then grades the flight;
`tools/record_missile_chase.py` — real-app chase-cam PNGs paired 1:1 with
`telemetry.json` rows; `game/forensics.py` + `game/flight_recorder.py` (J
in game) — fog-honest shot debrief; `game/blackbox.py` + `tools/replay_battle.py`
— bit-exact replay with hash verification and `--to-tick` state dumps;
`tools/playtest_harness.py` — scripted playtests.

## Seeing your work (visual verification — render, don't guess)

Editing a model, effect, or anything rendered **without looking at renders
before and after is how assets get mangled**. The loop (used by every
model-correction pass, verified working 2026-07-17):

1. **Render BEFORE** with the matching harness; **change**; **render AFTER**
   and actually Read the PNGs side by side, against reference photos in
   `../Markdown/docs/research/` / `../Markdown/documentation and research/NN_*/references/`.
2. Harness catalog: `tools/screenshot_harness.py` (scripted scenes),
   `tools/shoot_model_orbits.py` (az/el orbit grids of a model),
   `tools/shoot_missile_models.py` / `shoot_missile_variants.py` /
   `shoot_battery_layout.py` / `shoot_hitcam.py` / `shoot_manpads.py` /
   `shoot_sandbox_war.py` / `shoot_cinematic.py` (per-feature audits),
   `python -m tools.probe_cloud_suite` (cloud acceptance matrix — see
   `../Markdown/docs/cloud_playtest_tooling.md`). All boot the app **hidden** and write
   to `renders/`.
3. **Motion**: `python -m tools.record_missile_chase [oniks|s300]
   [--cam hero|side|chase] [--fps N] [--max-s S] [--range-km R] [--out D]`
   — real launch, chase camera → `renders/chase/<out>/`: per-frame PNGs,
   1:1 `telemetry.json` (per frame: t/pos/vel/mach/phase/fuel **plus**
   gamma/heading/body-pitch/AoA, 120 Hz-sampled peak g and turn rate,
   alt AGL, dist-to-go, and the live flight-computer command — compare
   `fc.cmd_gamma_deg` vs `gamma_deg` to see the airframe lag its own
   guidance), 8-up contact strips with t/phase/Mach/alt + fp/aoa/g burned
   into each tile, and `chase.mp4` (ffmpeg). It also writes
   `telemetry_full.jsonl` — EVERY 120 Hz substep (7,200 rows/min), the
   complete numeric record independent of video fps. Graph any recording
   with `python -m tools.plot_chase_telemetry <name>` → stacked
   time-series panels (gamma vs FC command, AoA, Mach, alt, g, turn rate,
   unwrapped heading; phase lines) + printed anomaly summary with
   timestamps (worst guidance gap, peak AoA/g/turn, 1 s heading-swing
   "180-detector"). Default camera is `hero` (¾-front, sun side —
   airframe large and lit); `side` gives exact attitude profiles. When a
   "watch the launch — does it feel right?" request comes in: plot first,
   read the anomaly summary, then open the exact frames (frame ≈ t×fps)
   and diff commanded-vs-actual gamma before judging. New capture
   subjects: copy this file's pattern (hidden App + real launch pipeline
   + per-sim-second grabs).

**How video works for an AI (the honest contract):** Claude cannot watch an
`.mp4` — the mp4 is for humans. Claude sees the PNG frames. Viewing every
frame of a long high-fps capture does not fit in context (budget a few dozen
images per session), so the system is built for triage instead: record at
low fps (default 6), read the contact strips first (8 annotated frames per
image), scan `telemetry.json` — which covers **every** frame numerically —
for the anomaly, then open the exact frames where the numbers look wrong and
cite both. Do not raise `--fps` for AI review; raise it only when producing
an mp4 for the user to watch.

**Keybinds** come from the action registry in `game/keybinds.py` (README
table is generated from it; F1 in game shows the live table). Settings
persist to `%APPDATA%\ONIKS\settings.json`.

## Docs map (where knowledge lives)

- **Orientation bundle for fresh sessions:** `../Markdown/docs/research/handoff/HANDOFF_README.md`
  ("reuse these — don't reinvent" file map), `ROADMAP.md` (milestones),
  `CONTINUE_HERE.md` (shipped-vs-remaining ledger), numbered `0N_*.md`
  feature specs with file-level sketches and test contracts.
- **Plans with verbatim test contracts:** `../Markdown/docs/plans/` — especially
  `feature_expansion_review_2026-07-06.md` (code-verified corrections to the
  research package + contracts for the remaining expansion features).
- **Run logs (measured evidence per shipped feature):** `../Markdown/docs/*_run_log_*.md`
  and `../Markdown/docs/overnight_run_log.md`, `../Markdown/docs/combat_build_log.md`.
- **Audits / known open items:** `../Markdown/docs/combat_code_audit_2026-07-17.md`
  (latest line-level audit), `../Markdown/docs/reviews/`.
- **Cross-session coordination:** `../Markdown/docs/session_notes_2026-07-17.md` names
  files owned by other concurrent sessions — respect its HANDS OFF lists,
  and `engine/particles.py` is shared (additive changes only).
- **Normative real-world research** (values feeding sim constants):
  `../Markdown/docs/research/*.md` (missile physics, ICBM, MANPADS, S-300, radar bands,
  sea clutter, warship layouts, …). Check here before re-researching.
- **Session evidence folders:** `../Markdown/documentation and research/` — take the next
  free `NN_topic/` number for your session, leave renders/probe CSVs and a
  `FINDINGS.md` (convention documented in its README).

## Session-start reading order

1. This file.
2. `../Markdown/docs/session_notes_2026-07-17.md` (or the newest session notes) — what
   other sessions own right now.
3. The newest run log / `CONTINUE_HERE.md` — current state and next work.
4. The plan/spec matching your task from the docs map above.
