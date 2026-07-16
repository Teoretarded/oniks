# Weather Composer and independent supercells — 2026-07-10

The Graphics settings now open a dedicated Weather Composer. A battle can use
one quick preset or a custom combination of four independent cards:

- low: off, scattered, broken, deck;
- mid: off, scattered, broken, massive;
- high: off, wispy, dense, sheet;
- convective: off, towering, supercell, storm line.

The subview edits a draft. `APPLY` persists the complete selection atomically;
`CANCEL` leaves the live and saved weather unchanged. Keyboard, mouse, quick
preset chips, and the readable result summary share the same model.

Custom selections resolve to an immutable `WeatherPreset` recipe and a stable
digest. The digest participates in cloud-field caching, renderer rebuilds, and
weather-effects resets, so two different custom combinations cannot reuse the
wrong baked cloud geography.

## Convective architecture

Towering and severe systems are not stamps in the repeating ambient tile.
They are seed-unique clouds in an independent 800 km domain:

- towering cumulus: 3–5 tall cells;
- supercell: 1–3 rotating systems with 15–19.5 km tops and 1–2.5 km
  overshooting domes;
- storm line: 4–6 aligned cells.

Each severe cell has a slim tilted updraft, inflow shelf/wall cloud, compact
overshoot, tight upwind anvil lip, and a very broad down-shear anvil. The
96×192×192 storm field and conservative occupancy volume are marched in the
same pass as low, mid, and high clouds, so mixed recipes retain correct depth
and transparency.

Rain, darkness, lightning position, and thunder delay use the same resolved
supercell locations. They remain visual-only and do not change sensors,
seekers, flight, or weapon physics.

## Performance policy

Normal weather keeps the existing quality-scaled V2 path. Severe systems use
a separate temporally reconstructed working resolution because a 20 km-tall
cloud can fill almost the entire screen. On the RTX 3050 Laptop worst-case
close supercell view, the isolated cloud pass measured about 8.5 ms on High
and 10.2 ms on Ultra. Normal V2 High remains about 3.5 ms in the same harness.

These worst-case numbers intentionally preserve the distant tower/anvil. A
hard global march cap was rejected because it made upper storm structure
disappear behind foreground clouds.
