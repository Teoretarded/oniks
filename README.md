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

| Key | Action |
|---|---|
| M | tactical map |
| TAB | switch platform (Bastion Oniks / S-300 battery) |
| LMB / RMB (map) | set target / add waypoint (S-300: pick air contacts) |
| X (map) | clear waypoints |
| wheel / MMB-drag / arrows (map) | zoom at cursor / pan |
| 1 / 2 | profile hi-lo / lo-lo |
| SPACE | launch |
| C | cycle camera (chase/orbit/target/launcher/free) |
| WASD QE + RMB-drag | free camera (SHIFT fast, CTRL+SHIFT very fast) |
| - / = | time accel down/up (1–16×, locked to 1× during launch) |
| P / N | pause / frame-step |
| F2 | screenshot to renders/ |
| ESC | menu |
