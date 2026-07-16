# Cloud V2 visual/playtest tooling

These probes are deterministic for a fixed seed, preset, quality, camera path,
and cloud clock. Run them from the repository root. They fail rather than
silently accepting V2's legacy fallback.

## One-command acceptance matrix

Print the exact commands without opening a GL window:

```powershell
python -m tools.probe_cloud_suite --dry-run
```

Run the complete visual and quantitative matrix:

```powershell
python -m tools.probe_cloud_suite --seed 7 --quality high --mode all
```

The visual matrix captures all seven presets (`CLEAR`, `FAIR`,
`PARTLY_CLOUDY`, `OVERCAST`, `HIGH_CIRRUS`, `TOWERING_CUMULUS`, and
`THUNDERSTORM`) plus 60 m/1/4/10/17.5/30/50 km altitude sweeps for fair,
high-cirrus, and storm conditions. The command manifest is written to
`renders/cloud_acceptance_manifest.json`.

Flight specs can use `{"cluster_point": "center|edge|outside"}` so fixed
camera checks lock to actual seeded cloud geometry instead of arbitrary space.

The default full suite requires at least one player-visible deterministic
lightning pulse during the ten-second thunderstorm watch. To collect the rest
of the matrix while diagnosing a missing/occluded pulse:

```powershell
python -m tools.probe_cloud_suite --mode all --allow-missing-lightning
```

Do not use that override for the final rollout/deletion gate. Lightning is a
post-cloud weather effect, so its detector reads final composited luminance;
alpha/depth morph checks continue to read the resolved cloud buffers.

## Preset and altitude screenshots

Capture the named view plan for one preset:

```powershell
python -m tools.probe_cloud_shots 7 --renderer v2 --quality high --preset 4 --preset-views
python -m tools.probe_cloud_shots 7 --renderer v2 --quality high --preset 6 --preset-views
```

Preset 4 includes below/edge/above high-cirrus views. Convective presets add
dry wide-angle tower silhouettes and far-above structure views; preset 6 also
includes storm underbelly, anvil, above-storm, and lightning-watch views. Cluster-based views
are resolved from the actual seeded V2 density and macro-weather fields; they
are not arbitrary fixed offsets.

Capture a vertical sweep:

```powershell
python -m tools.probe_cloud_shots 7 --renderer v2 --quality high --preset 6 --altitude-sweep
```

PNG names include the actual backend. A requested V2 capture aborts if V2
enters legacy fallback.

## Custom Weather Composer recipes

Capture a mixed low + mid + high + supercell recipe from deterministic ground,
side, anvil, above-system, and high-layer cameras:

```powershell
python -m tools.probe_weather_composer `
  --recipe docs/examples/weather_recipe_mixed.json --quality ultra
```

Use `--view supercell_side` to capture only one view. Recipe files accept the
short keys `low`, `mid`, `high`, and `convective`; filenames include the stable
recipe digest. Benchmark the same resolved system with:

```powershell
python -m tools.perf_clouds 240 --renderer v2 --quality high `
  --recipe docs/examples/weather_recipe_mixed.json
```

## Flight, repeat, morph, and pop checks

Close approach (the original disappear/pop complaint):

```powershell
python -m tools.probe_cloud_flight 7 --renderer v2 --quality high --preset 1 `
  --spec docs/examples/flight_close_approach_v2.json --override-spec-seed `
  --gate --gate-profile approach --repeat-check
```

Stationary fixed-clock convergence/repeat check:

```powershell
python -m tools.probe_cloud_flight 7 --renderer v2 --quality high --preset 2 `
  --spec docs/examples/flight_stationary_v2.json --override-spec-seed `
  --freeze-cloud-time --gate --gate-profile stationary --repeat-check
```

Storm underbelly and lightning watch:

```powershell
python -m tools.probe_cloud_flight 7 --renderer v2 --quality high --preset 6 `
  --spec docs/examples/flight_storm_underbelly_lightning.json `
  --override-spec-seed --gate --gate-profile motion --expect-lightning
```

Each run writes a GIF, two contact sheets, and a JSON report under `renders/`.
The JSON contains composited-RGB diagnostics for historical comparison and
direct V2 resolved alpha/first-hit-depth metrics for acceptance.

## Metric interpretation

Direct buffers are point-sampled to at most 256×144 to bound memory while
preserving deterministic locations. The checks are:

- `alpha_mae_p95`: 95th percentile adjacent-frame cloud-alpha change.
- `max_coverage_drop`: largest one-frame loss of alpha ≥ 0.05 pixels.
- `max_coverage_step`: largest absolute one-frame coverage change.
- `max_component_disappear`: largest loss of 4-connected cloud components.
- `coverage_max`: must exceed 1%; an empty/missed cloud view cannot pass.
- repeat `alpha_mismatch_ratio_max`: pixels differing by more than 1/255
  across identical replays.
- `depth_rel_p95_max`: persistent-cloud first-hit depth repeat error.
- lightning `brightest_pulse`/`flash_count`: localized positive cloud-luminance
  pulses using a 99.5th-percentile delta and a default 0.08 threshold.

Thresholds live in `tools/cloud_probe_metrics.py`. `stationary` is strict and
must be paired with `--freeze-cloud-time`; `approach` allows perspective motion
but rejects the old whole-puff dropout; `motion` is the looser inside/altitude
diagnostic. A metric failure exits 1 only when `--gate` is supplied.

## Rules for future changes

1. Keep the seven preset IDs and view plan stable; add views without silently
   renaming existing artifact paths.
2. Never infer V2 success from the requested CLI string. Check `using_v2` and
   record `backend_name`.
3. Do not use sky brightness as the rollout gate. Dark storm clouds require
   direct alpha/depth.
4. Reset cloud time and the `main` temporal history after terrain settling.
5. Run `pytest tests/test_cloud_probe_tools.py` after changing suite plans,
   metric math, thresholds, or CLI command generation.
