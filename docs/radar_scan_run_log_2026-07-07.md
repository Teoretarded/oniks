# Radar scan model + seeker honesty — run log (2026-07-07)

Plan: `docs/plans/radar_scan_seeker_honesty_plan_2026-07-07.md`
Spec: `docs/plans/weather_system_design_2026-07-07.md` PART 2 (§8–§13)
Research (NORMATIVE): `docs/research/radar_scan_and_bands.md`

Build style: solo, TDD red-first, full `pytest -q -n auto` gate per task
batch (Tasks 2+3 shared one gate — both additive-with-default changes; the
Task 3 gate covers both. Noted as a deviation from the per-commit rule.)

## Task ledger

- **T1 ScanDef + paint math** (`1b3c4b0`): closed-form
  `next_paint_t`/`painted` on Radar — staring/rotating/sector; `detects()`
  untouched. 6 contracts. Full suite exit 0 before commit.
- **T2 radar_model flag + paint_state** (`b49b6b9`): config default
  "functional", clamp_config normalizes; `RadarNetwork.paint_state` =
  (seen, earliest next paint among detecting radars).
- **T3 scan-driven ContactBoard**: `paint_fn` mode — track initiation
  anchors `since` to the FIRST PAINT and survives inter-sweep dark time
  while the target stays detectable (real M-of-N initiation: the legacy
  2 s *continuous* rule can never form a track through a 10 s rotator
  whose dwell is ~55 ms/sweep). Refresh `t_next` = next real paint,
  clamped [0.5 s, 30 s]. Legacy tables kept verbatim for functional mode.
  Fixture note: the first staleness test placed the ship at 71 km / 0 m —
  below the 20 m antenna's ~18 km horizon, so no track EVER formed. The
  gate that caught it was `detects()` doing its job; ship moved to
  25.5 km / 15 m mast.

- **T4 world wiring**: ScanDefs per the research doc on every construction
  (station 91N6 rotate-12 s staggered / SPY-1+enemy-ship arrays staring /
  9S36+CBR fixed sector facing the northern threat axis / Pantsir 2 s +
  AWACS 10 s + enemy EW 10 s rotators / fighter nose ±60° body-fixed via
  the existing `_heading_ref`, radians→degrees). `_player_paint_state`
  mirrors `_player_visible` incl. jammer threading + SAR-as-continuous-
  imager. Enemy side: AWACS CUE paint-gated in `ShipDefense._detects`
  (own SPY-class array stays staring — correct per doc). `"scanned"`
  forced at the 4 game-layer sites + SANDBOX_CONFIG.

- **T5 Oniks/Zircon seeker honesty** (`f0e81b7`): `_seeker_can_see` =
  `radar_horizon_m` + `terrain_blocks` (one physics, reused); held-lock
  re-check 0.5 s cadence drops masked locks; dry rescans throttled to
  seeker frame time under scanned ONLY (legacy keeps per-substep rescan).
  KEY DECISION: seeker honesty arms under the SAME `radar_model="scanned"`
  flag — unconditional gates would have changed every legacy digest (a
  12 m skimmer really does lose a 40 km ship below the horizon).
- **T6 SAM cone + ARH/SARH**: SamDef gains `guidance`
  (48N6/SM-2/9M317 = sarh, 40N6/SM-6 = arh, 57E6/9M338 = command) +
  `seeker_half_angle_deg` (30°). Terminal handover requires the target
  inside the cone about the velocity vector (homing rounds, scanned only) —
  midcourse simply continues until PN brings the nose around. SARH rounds
  get `illuminator_ok_fn`: the station's NEW 30N6-class engagement radar
  (station_engagement, X-band 60° wedge, dies with the mast structure)
  slews to the most recent 48N6 engagement; a 9M317 rides its own TEL's
  9S36 (per-TEL slew, tube dicts carry "tel"). One FCR = one wedge:
  multi-axis raids saturate illumination capacity — EMERGENT, no dice.
- **T7 AIM-9X gimbal**: ±90° HOBS head limit off the body axis; LOS past
  it = lock lost, self-destruct (scanned only — legacy keeps the loop-back
  re-attack). Bounds the old bare 2×-range energy band.

## Measured (probe_radar_scan, JASSM inbound 100 km north, 240 s window)

| mode | missile track age p50/p95/max | ship p50/p95/max |
|---|---|---|
| functional (legacy bands) | 7.50 / 17.65 / **29.50 s** | 18.50 / 53.85 / **59.50 s** |
| scanned (91N6 12 s rotation) | 5.25 / 10.50 / **11.00 s** | 5.50 / 11.00 / **11.50 s** |

Max staleness now IS the rotation period (~11.5 s < 12 s incl. dwell) —
staleness became physical. Note the honest model gives FRESHER mid-range
ship tracks than the legacy 60 s band; the price is paint-based (slightly
later) track formation and true blindness outside sector radars' wedges.

## Measured (probe_seeker_honesty — Oniks max acquisition, km)

| geometry | legacy | honest (scanned) |
|---|---|---|
| 12 m skim, open water | 49.5 | **37.5** (horizon-true; theory 37.9) |
| 60 m lo-cruise, open water | 49.5 | 49.5 (horizon 55.6 km — unaffected) |
| 15 km dive, open water | 47.5 | 47.5 (looks down past the horizon) |
| 12 m skim, 140 m ridge at 7–10 km | 49.5 | **9.0** (ship must be in front of it) |

## Honest nit list

- Fighter intercept-hold + AIM-9X release gate use instantaneous
  `radar.detects` without a sector check. Defensible: the intercept
  steering keeps the nose ON the target (tracking channels stare), but a
  drone crossing BEHIND a transiting fighter is technically still
  "holdable" for the anti-strobe dwell. Candidate honesty upgrade when
  the fighter AI gets its next pass.
- `sim/recon.py` pod/self-deafen emitters keep default band "S"; research
  doc says X. Cosmetic until W-P10 (they are ELINT targets, not
  attenuation consumers).
- Station ENGAGEMENT radar (30N6-class sector FCR) is declared in the
  research doc + SCAN_ENG_30N6 constant but the OBJECT lands with Task 6
  (SARH illuminator) — it has no search role. LANDED with T6.
- SARH wedge-slew doctrine is "newest engagement wins": firing a second
  48N6 at a target far off the first one's bearing strands the FIRST
  round (its lock freezes when its target leaves the wedge). Honest but
  currently silent — a launch-time HUD hint ("30N6 SLEWING — ROUND N
  GOES BLIND") is a good UX follow-up.
- Buk 9S36 slewing to its engagement also slews its SEARCH wedge in
  radar_net (realistic — the FCR looks where it fights — but worth
  knowing when reading picture gaps).
- Enemy SM-2s keep illuminator liveness (existed) but no sector gate on
  the ship's staring array (correct: SPY-1 illuminators are slaved
  directional dishes — modeling their 3-channel capacity limit is a
  future honesty pass).
- 57E6/9M338 "command" rounds: no cone, no illuminator dependency wired
  (their mounts' tracking-channel death mid-flight is not yet a lock
  break — future pass alongside the Pantsir/Tor FCR model).
