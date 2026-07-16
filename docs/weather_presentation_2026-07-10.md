# Weather presentation layer — 2026-07-10

`game/weather_effects.py` is a visual-only companion to the seeded Cloud V2
field. It does not change radar, seekers, flight, rain attenuation, or world
state.

- CLEAR and FAIR are exact no-ops.
- OVERCAST and storm presets add an inexpensive fullscreen blue-gray darkness
  pass below their cloud ceiling.
- THUNDERSTORM and custom supercell/storm-line recipes evaluate the camera
  against the same seed-unique 800 km convective systems used by Cloud V2;
  rain and the strongest darkness occur beneath those cells and fade out above
  the cloud layer.
- Rain is procedural screen-space streaking in the same fullscreen pass. It
  allocates no particles and requires no per-drop CPU work.
- Lightning intervals, cell choice, location, double-flash shape, sound delay,
  and gain are deterministic from battle seed + preset. Thunder reuses the
  existing distant-boom one-shot after a speed-of-sound delay.
- The controller advances on clamped render time, alongside cloud motion, so
  battle time warp does not multiply rain speed or lightning frequency.

The pass renders after clouds and particles but before the HUD. Launch-cinema
PiP samples the same weather clock at its own camera position.
