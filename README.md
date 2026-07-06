# ONIKS

A standalone missile-warfare game set in a to-scale 600 x 600 km world. You
command a coastal Bastion battery — P-800 Oniks supersonic cruise missiles,
an S-300 SAM battery, Pantsir point defense and more — against a naval
strike group that fights back. The simulation runs a fixed-timestep (120 Hz)
float64 physics core with camera-relative float32 OpenGL 3.3 rendering,
logarithmic depth, atmospheric haze, ring-LOD ocean, and procedurally
generated terrain, models and audio (sounds synthesize on first launch).

## Quick start (playing the game)

1. Install [Python 3.11+](https://www.python.org/downloads/) (tick
   "Add python.exe to PATH" in the installer).
2. Download this repo (green **Code** button → **Download ZIP**, unzip) or
   `git clone` it.
3. In the game folder:

```
pip install -r requirements.txt
```

4. Double-click `run_game.bat` (or run `python main.py`).

Needs a GPU with OpenGL 3.3 (any reasonably modern PC). The first launch
takes a few extra seconds while terrain, models and audio build.

## Game modes

- **SANDBOX** — the war sandbox: the full order of battle on both sides
  (destroyers, a carrier, submarines, fighters, AWACS, a jammer, amphibious
  transports vs. your full armory) with an all-seeing map and no game-over.
  Enemies are passive until you say otherwise: open the map (M) and press
  **I** for the RED-FORCE DIRECTOR — order enemy ships/subs/jets to launch
  at any point you click, or flip global AUTO-ENGAGE and fight the war.
  Click any contact on the map and close it to **spectate** that thing
  (arrow keys cycle targets, drag orbits, wheel zooms, C exits).
- **COMBAT** — the fog-of-war battle: a four-page setup screen (world seed,
  enemy fleet, your armory and defenses), a radar-gated sensor picture,
  an enemy commander that hunts your radar down, victory/defeat, an
  after-action report with grades, and a forensics debrief (J).
- **CAMPAIGN** — linked battles with escalation and carried-over ammo.

## Controls

Default bindings, generated from the action registry (`game/keybinds.py`).
Everything below is rebindable in SETTINGS (persisted to
`%APPDATA%\ONIKS\settings.json`) except the reserved ESC and F1 — press
**F1 in game for the always-current table**.

| Key | Action |
|---|---|
| **ENGAGEMENT** | |
| SPACE | launch weapon |
| TAB | cycle platform (Bastion / S-300 / drone / Buk / swarm) |
| M | tactical map |
| 1 / 2 | flight profile hi-lo / lo-lo |
| X | clear waypoints (map open) |
| R | radar emissions on/off (EMCON) |
| V | S-300 round select (48N6 / 40N6) |
| B | Bastion round select (Oniks / Zircon / ASBM / Kh-31P) |
| F / Y | salvo fire / salvo mode (ripple, fan, time-on-target) |
| U / K | sonobuoy drop (map) / ASW launch |
| G / H | drone EW pod / swarm arrival mode |
| I | red-force director (sandbox, map open) |
| **SIMULATION** | |
| O | battery status panel |
| J | forensics / shot debrief |
| T | auto time-warp |
| F4 / F5 | map layout board-classic / launch-cinema PiP |
| P / N | pause / frame step |
| - / = | time scale (1-16x, locked to 1x during launch cinematics) |
| **CAMERA** | |
| C | camera mode (chase/orbit/target/launcher/free) |
| [ / ] | camera subject prev / next |
| LEFT / RIGHT | spectate cycle (sandbox) |
| W A S D, E / Q | free cam (SHIFT fast, CTRL+SHIFT very fast) |
| **SYSTEM** | |
| F2 | screenshot to renders/ |
| F3 | report bug (ledger mark + bundle to bug_reports/) |
| F1 | controls overlay *(reserved)* |
| ESC | menu / back *(reserved)* |

Mouse: map — LMB target/select, RMB waypoint, wheel zoom, MMB/arrows pan;
orbit & spectate cams — LMB/RMB drag rotates, wheel zooms; chase cam —
wheel adjusts follow distance; free cam — RMB-drag mouse look.

## Development

Tests (~1400, GL-free): `python -m pytest -q -n auto`.
Visual/perf gates live in `tools/` (screenshot_harness, perf_harness,
shoot_sandbox_war, perf_sandbox_war). Design docs and run logs in `docs/`.
