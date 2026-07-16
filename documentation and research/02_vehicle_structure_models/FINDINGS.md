# Vehicle and Structure Model Audit

Research and implementation session: 2026-07-10.

## Scope

- Ground vehicles and launchers
- Radar, fuel, harbor, and airfield structures
- Aircraft
- Ships, amphibious transports, landing craft, and the simulated SSK
- Missiles, ammunition, launch debris, and weather are deliberately deferred

## Render method

The audit is fully automated and headless; it does not use the F3 inspector.
For every catalog asset it captures eight azimuths (0 through 315 degrees) at
-45, 0, +45, and +70 degrees elevation, plus exact +90 top and -90 bottom
views. Each asset has 34 full-resolution frames, four elevation sheets, one
overview sheet, and machine-readable mesh/camera metadata.
The audit process uses a neutral camera-facing inspection light so underside
views stay readable; gameplay lighting is unchanged.

- `renders/before/`: 24 original assets, 816 angle frames
- `renders/after/`: 30 final assets, 1,020 primary angle frames
- Airfield detail regions add 40 close inspection frames for thresholds,
  hangar/apron, and tower/taxiway geometry
- `renders/after/manifest.json`: final coverage and geometry manifest
- `renders/after/qa_*.jpg`: category-level visual QA sheets
- `references/REFERENCES.md`: research sources

## Baseline findings

- Bastion, S-300, and Pantsir had overly generic truck bodies and incorrect or
  hard-to-read launcher/radar silhouettes from overhead.
- Buk, swarm pod, counter-battery radar, emitter decoy, reflector, and SAM pad
  either reused unrelated geometry or had no dedicated catalog model.
- The radar tower, fuel depot, harbor, and airfield lacked recognizable site
  details; the runway did not carry a complete marking/taxiway language.
- Aircraft had sparse generic silhouettes, several tail-orientation defects,
  and an incorrect E-3 tail arrangement.
- Ships lacked overhead-readable deck systems. Transport and LCAC reused proxy
  meshes, the flagship silently rendered as a Burke, and the simulated
  submarine had no dedicated rendered model.
- Several gameplay volumes no longer matched the visuals: TEL X/Z axes were
  swapped, raised launchers exceeded their boxes, carrier deck/island and Burke
  mast geometry sat outside the historical hull OBB, and subsystem boxes did
  not match the rebuilt deck layouts.

## Changes made

- Rebuilt Bastion, S-300, Pantsir, radar station, and fuel depot with distinct
  chassis, canister, stabilizer, radar, service, containment, and access detail.
- Added dedicated Buk TELAR, swarm pod, CBR radar, decoy emitter, corner
  reflector, SAM hardstand, and Project-636-style submarine builders.
- Rebuilt the airfield with runway numbers/thresholds/centerline/touchdown and
  aiming markings, taxiways, lights, aprons, hangars, and tower details.
- Rebuilt all six aircraft silhouettes around ATL2, Su-35, RQ-4, F/A-18E,
  E-3, and EA-18G references; corrected every inverted/canted tail defect.
- Rebuilt cargo, tanker, frigate/warship, Burke, Nimitz, amphibious transport,
  and LCAC geometry with type-specific deck equipment and overhead landmarks.
- Added a dedicated Ticonderoga-style flagship with twin 61-cell VLS fields,
  four SPY faces, twin masts/funnels, hangars, guns, and marked flight deck.
- Rebuilt the harbor with quay furniture, fenders, bollards, ladders, pitched
  warehouses, container stacks, crane rails, and braced ship-to-shore cranes.
- Replaced live Buk/swarm/support and transport/LCAC proxy mappings with their
  dedicated meshes while preserving public builder signatures and launcher
  hardpoints.
- Bound all six live Buk launch positions to the dedicated model's visible
  canister mouths, so launch effects and relocation remain mesh-aligned.

## Collision and damage alignment

- `Structure` dimensions now consistently mean Z length, X beam, Y height.
  Raised TELs and every dedicated support-site wrapper are covered by measured
  model envelopes; the 2.5 km airfield axis was corrected as well.
- Ships support compound swept-hit volumes. Burke adds a narrow topside/mast
  box; Nimitz adds thin flight-deck and starboard-island boxes without turning
  empty air around the hull into a hit.
- Carrier broad-phase reach is recomputed after carrier dimensions are applied.
- The LCAC owns a 1 m per-hull draft used by both collision and damage geometry.
- Damage grids now support laterally offset modules. Burke forward/aft VLS,
  SPY faces, mast, bridge and CIC; Nimitz island and magazine naming; and
  cargo/tanker/warship/transport/LCAC internal layouts are aligned to the
  rebuilt models.

## Remaining limits

- Missile and ammunition geometry was intentionally left for a later pass.
- The submarine is available to the headless inspection catalog, but is not
  drawn into the normal gameplay truth view because live submarines belong to
  the acoustic/fog-of-war layer.
- The fixed radar-station builder still represents more than one radar role;
  separate type-specific radar sets would be a useful future modeling pass.
- These remain optimized procedural game meshes rather than film-resolution
  replicas; the goal was recognizable proportions, readable silhouettes, and
  coherent gameplay geometry.

## Verification

- Final manifest: 30 assets, 1,020 primary angle frames, 40 close airfield
  frames, and no missing render paths.
- Visual audit passed across every category, including exact top/bottom views,
  carrier platforms, harbor geometry, flagship, aircraft, and ground vehicles.
- 229 model/catalog/hit-volume/grid audit tests passed; 120 focused alignment,
  launch, damage, and collision tests passed after the final Burke/Buk fixes.
- The complete regression suite passed: 1,914 tests, zero failures, with seven
  existing pygame-initialization warnings from keybind tests.
