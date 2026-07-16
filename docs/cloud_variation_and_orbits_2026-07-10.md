# Seeded cloud variation and orbit review

## Outcome

Cloud V2 remains a deterministic, world-seeded field bake. A battle seed is
split into isolated component streams (ambient mass, puff/detail, layer
height/base, cirrus, local cells, and independent supercells), baked once when
the weather is loaded, cached as `cloudfield_v13_*`, then translated by wind at
render time. Camera position never participates in generation.

This is preferable to a library of pre-authored cloud meshes: the same world
seed reconstructs the same sky, different seeds change the cloud geography,
and the runtime cost stays bounded by fixed-size textures and occupancy maps.

## Storm repair

The thunderstorm preset no longer combines a very broad anvil with a dense
ambient upper blanket. Its feeder/scud layers are sparse, while the independent
800 km convective field owns the tower, wall cloud, anvil, and overshooting top.
The maximum anvil footprint was reduced and made down-shear asymmetric.

Every resolved convective cell now has a stable `variant` in the range 0..3:

1. classic incus with a moderate trailing anvil;
2. pulse/calvus with a broad vertical crown and compact cap;
3. strongly sheared narrow tower with a longer downwind anvil;
4. multi-updraft system with a stepped, asymmetric skyline.

Radius, height, intensity, base, aspect, heading, tilt, overshoot, and anvil
spread remain independently seeded, so the phenotype is not merely a texture
swap. The storm texture dimensions and renderer pass count did not increase.

## Full inspection matrix

`tools.probe_cloud_shots --orbit-matrix` captures each preset at four azimuths
(0/90/180/270 degrees) and five elevations (level, +45, +90, -45, -90), saving
all 20 full frames plus one labeled contact sheet. Screen-space rain, gameplay
darkening, terrain, and ocean are excluded only from these asset-inspection
captures so they cannot hide the cloud silhouette.

Run every built-in weather preset in fresh processes:

```powershell
python -m tools.probe_cloud_suite --seed 7 --quality high --mode orbit `
  --manifest renders/cloud_orbit_manifest_seed7.json
```

Outputs:

- `renders/cloud_orbit_v2_high_p0_seed7.png` — clear reference
- `renders/cloud_orbit_v2_high_p1_seed7.png` — fair
- `renders/cloud_orbit_v2_high_p2_seed7.png` — partly cloudy
- `renders/cloud_orbit_v2_high_p3_seed7.png` — overcast
- `renders/cloud_orbit_v2_high_p4_seed7.png` — high cirrus
- `renders/cloud_orbit_v2_high_p5_seed7.png` — towering cumulus
- `renders/cloud_orbit_v2_high_p6_seed7.png` — thunderstorm
- `renders/cloud_orbit_manifest_seed7.json` — commands and return codes

The probe explicitly forces `ONIKS_CLOUD_WEATHER=battle`; a saved Graphics
weather override can no longer silently make every labeled capture render the
same preset.

## Performance strategy

- Ambient fields repeat over a 196.6 km density tile; sparse convective systems
  use a separate non-repeating 800 km domain.
- Conservative occupancy textures skip empty ray segments.
- Cirrus remains a cheap high-altitude 2D field with runtime filament detail.
- Half-resolution temporal rendering and quality-scaled step budgets remain
  bounded; High now uses a smaller reconstruction buffer and coarser safe
  sub-voxel storm steps.
- The full-resolution composite uses hardware bilinear color sampling and
  performs extra depth lookups only on silhouette pixels, replacing the old
  unconditional eight-fetch/four-exponential path.
- Bakes are cached by field version, seed, and complete weather recipe key.
- Separate random streams mean changing storm style does not reshuffle fair
  cumulus, cirrus, or other recipe components.

## Acceptance checks

- Same seed and recipe produce byte-identical cloud fields and storm variants.
- Seeds 0..11 exercise all four storm phenotypes.
- Clear has no volumetric or high-cloud density.
- The orbit matrix contains exactly 20 unique views per preset.
- Focused cloud/weather regression tests and Ruff are required before review.

On the local RTX 3050 laptop, the original High pass measured roughly
3.7 ms for fair weather and 5.0 ms for the supercell recipe. The tuned pass
measured about 2.0-2.2 ms during a heavily loaded desktop run. This is a large
improvement, but it still exceeds the repository's aspirational 1.0/1.5 ms
High GPU gate; further work should target the raymarch/composite boundary or a
compute/upscale path rather than reducing seeded field quality.
