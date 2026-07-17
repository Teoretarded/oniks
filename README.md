# ONIKS

A standalone missile-warfare game in a to-scale 600 × 600 km world — a
coastal Bastion battery versus a naval strike group run by a sensor-honest
AI commander. Fixed-timestep 120 Hz float64 physics core, camera-relative
float32 OpenGL 3.3 renderer, and procedurally generated terrain, models and
audio (there are no art assets on disk; everything bakes on first launch).

This README documents the **repository**: layout, filing system, regression
testing, verification tooling, and the systems hidden inside it. AI
contributors: `CLAUDE.md` is the session-start brief — read it first.
Player-facing info lives in the game itself: **F1** shows the always-current
controls table (generated from the action registry in `game/keybinds.py`).

## Running

```
pip install -r requirements.txt      # pygame-ce, PyOpenGL, numpy — nothing else
python main.py                       # or run_game.bat; Python 3.11+, OpenGL 3.3 GPU
```

Modes in one line each: **SANDBOX** (all-seeing war toybox with a red-force
director), **COMBAT** (fog-of-war battle with setup screen, victory/defeat,
after-action report), **CAMPAIGN** (linked battles, carried-over ammo).

## The database (repository layout)

| Path | What lives there |
|---|---|
| `main.py` | THE loop: real time → fixed 120 Hz sim steps (× `time_scale`), render once per frame |
| `engine/` | GL primitives: window, shaders, lit-mesh renderer, particles, text, math3d, camera |
| `world/` | Terrain/ocean/sky/clouds, world constants (`generation.py`), `CombatWorld` + `SandboxWorld` orchestrators, `CombatConfig` |
| `sim/` | Pure-numpy, **GL-free** simulation — every weapon, sensor, ship, aircraft, sub, and the enemy commander |
| `game/` | Game states, HUD/UI, cameras, tactical map, forensics, cinematic walk mode, audio |
| `models/` | Procedural mesh builders, one file per unit family |
| `tools/` | ~145 headless probes, visual/perf harnesses, replay, digests (see Testing) |
| `tests/` | ~1400 GL-free pytest tests (no conftest.py; fixtures are local) |
| `../Markdown/docs/` | Plans, specs, run logs, audits, research (see Filing system) |
| `documentation and research/` | Per-session evidence folders `NN_topic/` |
| `renders/` | Screenshot/video output from the visual harnesses |
| `blackbox/` | Bit-exact battle ledgers, auto-recorded every battle |
| `bug_reports/` | F3 in-battle repro bundles (report + ledger + commands + screenshot) |
| `assets/`, `cache/`, `data/` | Baked cinematic scenes and generated caches — never hand-edit |
| `sounds/` | Synthesized on first launch |

## The filing system

- `../Markdown/docs/superpowers/specs/` — signed design specs; `../Markdown/docs/plans/` — approved
  build plans, many with **verbatim test contracts** (e.g.
  `feature_expansion_review_2026-07-06.md`).
- `../Markdown/docs/*_run_log_*.md` + `../Markdown/docs/combat_build_log.md` +
  `../Markdown/docs/overnight_run_log.md` — measured evidence for every shipped feature:
  what was built, what was probed, what numbers gated it.
- `../Markdown/docs/reviews/` + `../Markdown/docs/combat_code_audit_2026-07-17.md` — adversarial
  audits and their fix status.
- `../Markdown/docs/research/` — normative real-world references feeding sim constants
  (missile physics, radar bands, sea clutter, ICBM/MANPADS/S-300 data …).
  Check here **before** re-researching anything.
- `../Markdown/docs/research/handoff/` — a self-contained orientation bundle for fresh
  sessions: `HANDOFF_README.md` (file map + non-negotiables), `ROADMAP.md`,
  numbered feature specs, `CONTINUE_HERE.md` (shipped-vs-remaining ledger).
- `../Markdown/docs/session_notes_*.md` — cross-session coordination: which files other
  concurrent sessions own (**HANDS OFF** lists).
- `documentation and research/` — each work session takes the next free
  `NN_topic/` folder and leaves reference photos, renders, probe CSVs and a
  `FINDINGS.md` (convention in its README).
- Runtime settings persist to `%APPDATA%\ONIKS\settings.json`.

## Regression testing

- Full suite: `python -m pytest -q -n auto` — **always `-n auto`**
  (pytest-xdist); serial takes ~22 min.
- Only the tests your change touches:
  `python -m tools.select_tests --run` (static import-graph selection;
  falls back to the full suite when in doubt).
- Combat smoke gate: `python tools/smoke_combat.py` (all-pass, exit 0).
- **Locked contracts never weaken.** Same seed ⇒ byte-identical battles,
  proven by `state_digest` hashes and the `tools/wf_*_digest.py` gates;
  flagship duels and flight envelopes are pinned by dedicated tests; new
  features default OFF in `CombatConfig` when they would change existing
  battles.
- Bit-exact replay: every battle ledgers to `blackbox/`; F3 in-battle
  bundles a repro into `bug_reports/bug_NNN/`. Verify or inspect with
  `python tools/replay_battle.py <ledger> [--to-tick N]` — hash mismatches
  exit 1, `--to-tick` dumps the full world state at the flagged moment.

## How things get tested beyond pytest

- **Headless physics/AI probes** — `tools/probe_*.py`:
  `probe_fc_transcript.py` dumps every flight-computer replan (candidate
  corridors, costs, choice) as JSON and grades the flight; the
  `probe_audit_*.py` family audits the enemy AI for truth-leaks, sensor by
  sensor.
- **Visual verification ("AI eyes")** — render, don't guess:
  - `tools/screenshot_harness.py` — scripted scenes → `renders/*.png`.
  - `tools/record_missile_chase.py [oniks|s300] [--cam hero|side|chase]` —
    boots the real app hidden, fires through the real launch pipeline,
    chase-cam frames + 1:1 `telemetry.json` (attitude, AoA, peak g, turn
    rate, flight-computer commands per frame) + 8-frame annotated contact
    strips + `chase.mp4`.
  - `tools/shoot_*.py` — per-feature visual audits (missile models, model
    orbits, battery layouts, hitcam, MANPADS, cinematic scenes, sandbox
    war, UI reference …).
  - `python -m tools.probe_cloud_suite` — the deterministic cloud
    acceptance matrix (`../Markdown/docs/cloud_playtest_tooling.md`).
- **Performance gates** — `tools/perf_harness.py`,
  `tools/perf_sandbox_war.py`.
- **Scripted playtests** — `tools/playtest_harness.py` and the
  `pt_battle*.py` scenarios.

## Hidden inside the database (you wouldn't normally see these)

- **F3 on the main menu** → the hidden testing lab: true-scale asset
  inspector, missile workbench batch runner (headless twin:
  `tools/run_missile_workbench.py`), EFFECTS catalog, the CINEMATIC
  tab — first-person walk mode on 1:1 LiDAR-baked real terrain
  (Lauterbrunnen, Yosemite) with shoulder-fired MANPADS and full ICBM
  launches (Sarmat / Minuteman III) — and the TEST MAP tab (F8): the
  6-DOF rigid-body physics test map (`sim/sixdof.py`).
- **F3 in battle** → bug reporter (ledger mark + repro bundle).
- **I on the sandbox map** → RED-FORCE DIRECTOR: order any enemy ship, sub
  or jet to launch at a clicked point, or flip global auto-engage.
- **J in game** → forensics/shot debrief with fog-honest death attribution.
- **Weather composer** (Settings → Graphics) — per-layer cloud recipe
  editor driving the volumetric sky.
- `game/blackbox.py` silently records every battle for bit-exact replay.
