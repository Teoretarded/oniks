# ONIKS

A standalone missile game set in a to-scale 600 x 600 km world. You command a coastal
Bastion battery and launch P-800 Oniks supersonic cruise missiles at moving ships and
land targets. The simulation runs a fixed-timestep (120 Hz) float64 physics core with
camera-relative float32 OpenGL 3.3 rendering, logarithmic depth, atmospheric haze,
ring-LOD ocean, and procedurally generated terrain and models.

## Install

```
pip install -r requirements.txt
```

Requires Python 3.11+.

## Run

```
python main.py
```

or double-click `run_game.bat`.

## Controls

Default bindings, generated from the action registry (`game/keybinds.py`).
Every key below is rebindable in SETTINGS (persisted to
`%APPDATA%\ONIKS\settings.json`) except the reserved ESC and F1; press F1
in game for the live table.

| Key | Action |
|---|---|
| **ENGAGEMENT** | |
| SPACE | launch weapon |
| TAB | cycle platform (Bastion Oniks / S-300 battery) |
| M | tactical map |
| 1 | profile hi-lo |
| 2 | profile lo-lo |
| X | clear waypoints (map open) |
| **SIMULATION** | |
| P | pause sim |
| N | frame step (while paused) |
| - | time scale down |
| = | time scale up (1-16x, locked to 1x during a launch cinematic) |
| **CAMERA** | |
| C | camera mode (chase/orbit/target/launcher/free) |
| [ | subject prev |
| ] | subject next |
| W / S | free cam fwd / back |
| A / D | free cam left / right |
| E / Q | free cam up / down (SHIFT fast, CTRL+SHIFT very fast) |
| **SYSTEM** | |
| F2 | screenshot to renders/ |
| F1 | controls overlay *(reserved)* |
| ESC | menu / back *(reserved)* |

Mouse (fixed): map — LMB target or select a flying round, RMB waypoint,
wheel zoom at cursor, MMB-drag / arrows pan; orbit cam — LMB/RMB drag
rotates, wheel zooms; chase cam — wheel adjusts follow distance; free
cam — RMB-drag mouse look.
