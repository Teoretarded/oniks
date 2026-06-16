# COMBAT mode build log

Phase-gate record: what shipped, what the orchestrator verified personally,
what was found, what was fixed, what remains open. Spec:
`docs/superpowers/specs/2026-06-12-combat-mode-design.md`.

## Phase 1 — radar network + fog of war (merged)

- sim/radar.py (horizon, terrain LOS, RadarNetwork), gated ContactBoard,
  CombatWorld + CombatState + COMBAT menu item, player ground radar station.
- Gate: 318 tests green, smoke_combat 7/7, screenshot verified (armed
  Bastion, empty battlespace).

## Phase 2 — enemy destroyers that fight back (merged)

Workflow `combat-phase2-destroyers`: 3 parallel implementers (Destroyer
entity + SPY-1 mount, SM-2/CIWS sim, Burke 3D model), integrator
(sim/enemy_defense.py controller, CombatWorld wiring), adversarial verifier.

- Integrator-caught bugs: `Missile.velocity()` missing (terminal handover
  crash), SM-2 self-hit on own deck OBB (launch_platform exemption).
- Verifier: PASS, 381 tests, live geometry probes (SM-2 kills 14 km crosser
  from 110 km; SPY-1 horizon vs 15 m skimmer = 34.4 km, in spec band).

Orchestrator gate (balance pass, research-grounded per verifier numbers):
- **Fixed:** anchors 323/377 km exceeded lo-lo Oniks fuel (~230 km flown) —
  moved to (-20k, 150k) / (20k, 170k), verified open water, inside lo-lo
  reach, still past the player radar hull horizon.
- **Fixed:** SM2 min_intercept_alt 30 m let SM-2s engage the 60 m lo-lo
  cruise, violating spec §5.2 "lo-lo is king" — raised to 100 m (S-300
  floor parity). Locked two-sided in
  test_enemy_defense.py::test_lo_cruise_above_horizon_is_below_sm2_floor.
- **Open (accepted, realistic):** close-in low SM-2 shots can splash (wasted
  round).
- **Cosmetic backlog:** destroyer bow flare reads subtle at distance; aft
  stack hard to distinguish. Revisit in a polish pass with reference photos
  (docs/research pattern).
- Gate: 382 tests green, smoke 9/9, destroyer screenshot personally
  reviewed (renders/screenshot_022.png).

## Mid-phase-3 user feedback (2026-06-12)

- **Spawn zones** (DONE, wiring deferred to Phase 7): world/spawn_zones.py
  + tests — one sector zone 110-300 km, triangular density peaking 180 km,
  >=25 km separation, carrier-only deep band 240-330 km with 2 escorts.
  Map render: renders/map_anchors.png (probe_map_anchors.py).
- **SM-2 vs lo-lo must be physics, not dice** (QUEUED for the phase 3
  gate — same files the running workflow edits): replace the planned Pk
  roll with low-altitude multipath tracking noise feeding PN; measure
  seeded engagement batches; lock two-sided statistical bands (hi ~0.85+,
  sea-skim ~0.25-0.55 per shot). Revert the 100 m SM2 floor to a realistic
  value (~25 m) at the same time and retire the floor-based regression
  test in favor of the statistical contract. Memory: physics-not-dice.
- **Terminal lock-break on terrain mask** (QUEUED, same gate, user ask
  2026-06-12): SAM terminal seekers (SM-2 SARH illumination, S-300) must
  re-check terrain LOS while locked — target ducks behind an island ->
  lock snaps -> coast on last prediction (usually a miss). Makes
  island-hugging Oniks waypoint routes a genuine evasion tactic.
- **ELINT/ESM is LOS too** (Phase 4 brief): passive intercepts (destroyer
  ESM vs the player radar, drone ELINT vs ship emitters) require the same
  terrain LOS + horizon test as active radar — no hearing through hills.

## Phase reorder (2026-06-12, user gate)

Recon drone pulled forward to Phase 4 (was 6); air war -> 5, Pantsir -> 6.
Reason: phases 2-3 create a hostile fleet the player cannot locate — the
only interim recon is Oniks seeker recon-by-fire. ELINT scope clarified:
finds ANY emitting ship (self-defense = self-revealing), not just the
carrier; the silent deep carrier is the hardest SAR target.

## Phase 3 — the enemy strikes back (integration)

Workflow `combat-phase3`: 2 parallel implementers (Tomahawk/JASSM/HARM
phase machines in sim/strike.py + StrikeDef arsenal entries; destructible
structures in sim/bases.py), then the integrator.

- sim/enemy_strikes.py (new): side-level ESM localization of the emitting
  player radar station — full fix after 90 s cumulative emission heard by
  any living destroyer, decaying at half rate while silent — then 2-round
  Tomahawk salvos (8 rounds per destroyer), 120 s apart while the station
  stays located+alive+emitting. Bastion/S-300 are NOT findable in Phase 3
  (they don't emit); the commander AI hunts them in Phase 4, so `defeated`
  is wired but unreachable until then.
- world/combat.py: destructible base (sim/bases.py Structures for the
  Bastion TEL, S-300 TEL, radar station); killing the station structure
  clears the Radar via on_destroyed — coverage vanishes, the picture
  coasts and drops. Structure damage is hostile-only (is_hostile flag on
  StrikeMissile: a player Oniks can never demolish its own base).
  `defeated` + launcher_armed lock (spec 2.2). Hostile strike rounds feed
  the gated ContactBoard as air entities at the radar's missile-class
  range (sim/contacts.py: one-line radar_size override).
- Radar silence: rebindable `radar_toggle` (default R, no conflicts) flips
  radar_station.emitting; HUD radar row (EMITTING/SILENT/DESTROYED),
  DESTROYED launcher status, defeat banner, base_hit/base_destroyed
  explosion events. Tactical-map fog of war: hostile rounds draw as
  contacts only — never truth-position diamonds/trails, never click-
  pickable (Phase 2's enemy SM-2 diamonds left as-is, out of scope).
- **Integrator-caught geometry bug (measured, not guessed):** the radar
  station (ground 144 m) hides behind a 159 m coastal crest 2.5 km out on
  the destroyer approach bearing — a straight PN run from the 8 km
  terminal gate impacted the crest every time, making the station
  unhittable. Fix in sim/strike.py: two-stage TLAM-style terminal (hold
  the terrain-following deck until a 2 km commit, then PN) plus a target_y
  aim altitude so structure shots aim at OBB mid-height, not sea level.
  Verified end-to-end: salvo at t~0 -> first player track of the inbound
  at t=356 s -> base_destroyed at t=678 s (~670 s dead-reckoned for the
  167 km flight at Mach 0.74), picture blind 90 s later.
- Gate: full suite green incl. tests/test_phase3_e2e.py (7 new),
  smoke_combat extended with a pure-sim ESM section (radar starts
  EMITTING; fix at 90 s; >=1 Tomahawk in flight; silencing halts salvos).

## Phase 5b gate — commander + the SM-2 contact seam (2026-06-13)

- Workflow PASS: 664 tests, smoke 47/47. Commander holds zero world refs
  (beliefs only); back-plot lands 264 m off the true base after 3 observed
  launches; a totally silent player is mathematically unfindable
  (defeated=False forever). 40N6 kills the AWACS at >200 km; IR drone-kill
  fires with no RWR LOCK; all seven 5a flight fixes verified.
- **Orchestrator gate — user-reported crash chased down.** Repro: map-click
  an enemy SM-2 contact -> orbit -> zoom in. Could not reproduce the
  original crash on current master (likely fixed incidentally by the
  Missile.velocity duck-type in phase 2), BUT the hunt found the real
  adjacent defect: enemy SM-2s were never tagged is_hostile, so the
  tactical map treated them as friendly rounds — clickable, camera-follow,
  and drawn at TRUE position (fog-of-war leak). Fix:
  sim/enemy_defense._mark_hostile_round() tags every enemy interceptor
  (is_hostile + the is_air/radar_size/aircraft_id air duck-type) so it
  rides the gated ContactBoard as a fog-of-war contact and every existing
  player-facing filter excludes it. Surfaced a latent crash on the way:
  SamMissile lacked velocity() (the ContactBoard feed dead-reckons through
  it) — added. Pinned by test_enemy_sm2_is_hostile_with_air_duck_type +
  the permanent tools/probe_sm2_camera_crash.py harness.
- Gate: 665 tests green, smoke 47/47, crash probe survives both variants.

## Phase 6 gate — Pantsir-S1 point defense (2026-06-13)

- Workflow PASS: 715 tests, smoke green. Verifier caught + fixed the
  Pantsir destructible OBB being rotated 90 deg from its model (off-center
  strikes missed the box). Measured the balance two-sided: a single
  inbound (sea-skim Tomahawk / terminal diver / JASSM) is reliably killed
  by one 57E6; saturation leaks to DEFEAT (2 divers 0/3, 4 divers 1/3,
  6+ divers 3/3) — shield, not wall. Physics-not-dice confirmed (only the
  30mm gun rolls; 57E6 is kinematics + fuse-on-truth). No friendly fire,
  honest radar horizon/LOS, dual-role network node verified (S-300 gains
  low tracks only via the Pantsir radars).
- Orchestrator gate: 715 tests re-run green; Pantsir viewed personally
  guarding the Bastion (probe_pantsir_view.py), HUD PANTSIR panel live
  (2 UP / M24 / G1400). Nit -> backlog: 12-tube launcher reads flat at
  rest (tubes sit low); a raised/erect-on-engage pose would pop the
  silhouette.

## Phase 7 gate — setup + armory + seeded gen + win/lose (2026-06-13)

- Workflow PASS: 791 tests, smoke 70/70. Determinism bit-identical across
  seeds 1337/7/99999/2024 (layout AND 60 s of sim). Armory bites: Oniks
  finite in COMBAT (magazine + empty-refill), still infinite in SANDBOX;
  S-300 48N6/40N6 + Pantsir 57E6/gun magazines refill. Victory needs ALL
  enemy ships + ground radars + airfield dead; defeat = all Bastion TELs.
  Enemy ground radars fog-of-war (map only after SAR/overflight), cue the
  commander while alive. Perf: extreme 13-ship config 0.50 ms/step.
  Verifier fixed the default Pantsir gun belt clamped 700->200 (added
  CLAMP_GUN_AMMO 1-1000 — approved: locked ammo clamp 1-200 contradicted
  the locked 700 default; honor the default + spec "gun ammo configurable").
- Orchestrator gate: 791 re-run green; BOTH setup pages viewed personally
  (probe_setup_screen.py) — World + Armory render clean, on-aesthetic,
  correct footer hints, gun belt 700. End overlay renders over a live
  frame only — captured at the playtest; logic verified in tests.
- **ALL 7 CORE PHASES COMPLETE.** Next: 30-min playtest -> code audit ->
  QOL pass -> additions brainstorm -> Phase 8 polish.

## Phase 8 — polish backlog (rolling)

- Destroyer model: bow flare subtle, aft stack indistinct (reference-photo
  pass).
- Dedicated Tomahawk/JASSM/HARM meshes (currently reuse existing missiles).
- Visual wreck states for destroyed structures.
- Wasted close-in low SM-2 shots can splash (accepted realism; revisit).
- ~~Longer-range player anti-ship weapon~~ DESIGNED: 3M22 Zircon-class
  (spec 4.3b) — lands Phase 7 (drone fix is the launch gate).
- 40N6-class 380 km SAM (spec 4.3b) — lands Phase 5 with the air war.
- Fighter AIM-9X-class IR pair for the drone hunt (spec 5.1) — Phase 5.
- Drone respawn-after-cooldown: in spec 4.3 since v1 — re-confirm in the
  Phase 4 brief (user reminder 2026-06-12).
- Fighter model reads missile-ish in flight — wing/LEX proportion pass vs
  F/A-18E references.
- Carrier model: bare deck (no markings), island under-detailed.
- AWACS model: needs a close visual gate shot (playtest).
- Pantsir 12-tube launcher reads flat at rest — raise/erect the tube blocks
  (especially on engage) to pop the silhouette.
- Dedicated 57E6 mesh (currently reuses the S-300 missile dart).

## Phase 4 — recon drone (integration, 2026-06-12)

Workflow `combat-phase4`: 2 parallel implementers (sim/recon.py drone +
ELINT/SAR/RWR sensor suite, 45 tests; models/drone.py RQ-4-class mesh,
12 tests), then the integrator.

- world/combat.py: one ReconDrone in `self.drone` (NOT self.aircraft —
  that list feeds contact pictures; the drone is friendly telemetry).
  DRONE_COUNT=1 / DRONE_RESPAWN_S=300 constants for the Phase-7 armory.
  ELINT emitter list rebuilt each pass from the ships' radars (future
  emitters join by construction); actionable fixes inject tracks for the
  matching SHIP (emitter '{ship_id}_spy1' -> ship) with the estimate
  error mapped onto track AGE (5 km fix = ~80 s faded track, sharpening
  as geometry improves); silence stops the refresh and the track coasts
  out (intel aging). ContactBoard gate extended: surface targets are
  seen by the radar net OR the live drone's SAR strip — a silent hull
  overflown forms a track through the normal sustained-detection flow.
  Respawn: shot down -> wreck spirals in `drone_wrecks` (crash events on
  impact) -> replacement at the base, route cleared.
- sim/enemy_defense.py: the drone hunt — same cadence/sustain tracking
  as the missile store at the radar's 'stealth' range, SM-2 launches
  capped at 2 in flight per drone, self-defense outranks the hunt (the
  shared 3 s fire-control reload spaces the shots). StealthTargetSam:
  low-SNR tracking noise (user law: physics, never dice) — a second OU
  error on the guidance point with sigma ~ (R/R_detect)^3 (thermal-noise
  angle tracking: sigma_angle ~ 1/sqrt(SNR) ~ R^2, position = angle x R).
  **Measured** (tools/probe_drone_sm2.py, N=15 seeded engagements/cell):
  sigma_max 60 m / tau 0.7 s gives kill-per-shot 14/15 at 10 km, 10/15
  at 20 km, 4/15 at 28 km of the 30 km detect range — spec §4.3 "~35% at
  envelope edge, near-certain up close". A LINEAR range law was measured
  first and rejected: 3-4/15 even close in (PN cannot low-pass sigma 40
  at tau 0.7 vs a 20 m fuse). Clean control kills at all three ranges.
  Locked two-sided in tests/test_phase4_e2e.py.
- **Integrator-caught (measured, not guessed): the triangulation quality
  metric lied.** The delivered residual-RMS proxy reported 'sub-5-km'
  fixes from a base-loitering drone against emitters 150 km out (true
  error 19-125+ km): near-parallel bearing lines agree with each other
  (residual ~ 0) while the along-bearing position is unconstrained, and
  lstsq's min-norm solution collapses next to the drone. Rebuilt
  sim/recon.py quality as layered physics: Cramer-Rao covariance from
  the observation GEOMETRY (noise cannot fake angular diversity),
  angle-domain self-consistency (2 sigma), a true-baseline geometry gate
  (0.25 rad subtense) and a range-observability likelihood test (the fix
  counts only if 0.5x/2x range alternatives break consistency). Swept 12
  seeds x 128 windows of the degenerate loiter: zero false actionables;
  honest geometry still converges (60 km leg vs 80 km emitter: quality
  1.7-2.1 km vs true 1.0-4.5 km).
- **Integrator-caught: FIFO baseline starvation.** 64 pairs at the 0.5 s
  listen cadence spanned ~5 km of track — never enough geometry. Fix:
  ELINT_MIN_PAIR_SPACING_M 800 m (sub-noise parallax is redundant); the
  retained window now spans ~51 km and a 120 km crossing leg goes
  actionable in ~138 s sim.
- ELINT-is-LOS rule (queued Phase-3): satisfied by construction —
  ElintReceiver gates on radar_horizon_m + terrain_blocks, the RWR SPIKE
  reuses Radar.detects itself.
- UI: TAB cycle gains 'drone' (COMBAT only — sandbox keeps 2 platforms,
  locked by test), map RMB tasks the live drone route / X breaks off to
  loiter / LMB flashes DRONE: RECON ONLY, drone draws at TRUE position
  (cyan, never a contact) with route, faint ELINT bearing rays + fix
  uncertainty circles that shrink with quality; HUD RECON DRONE panel
  (ALT/SPD/SENSORS/RWR SPIKE-LOCK with bearing/respawn countdown); the
  RQ-4 mesh flies in the aircraft pass with the falling-spiral attitude;
  [ / ] cycles onto the airframe while the platform is active.
- Gate: full suite 504 green (incl. 12 new e2e), smoke_combat 30/30
  (pure-sim ELINT/SAR/engagement/respawn chains + a GL pass over the new
  UI), screenshot renders/screenshot_032.png.

## Phase 3 gate — SM-2 physics pass (2026-06-12)

Both queued mechanisms landed, measured, locked (physics-not-dice):

- **Low-altitude multipath noise** (sim/sam.py MULTIPATH_*): below 150 m
  the position a SamMissile guides on — midcourse estimate AND terminal
  lock — carries per-axis OU noise (tau 0.5 s, vertical included), sigma
  scaling with depth below the threshold. Fuse stays on truth. Enemy
  launches seed a child Generator per round off the side rng
  (deterministic battles); rng None (player S-300) = bit-identical.
- **Terminal lock-break on terrain mask** (sim/sam.py LOS_CHECK_PERIOD_S
  0.5 s): SM-2 checks SHIP illuminator -> target (SARH; dead ship = lock
  lost), S-300 checks missile seeker -> target. Blocked check freezes the
  last estimate, guided until a later check clears — island-hugging
  routes are now genuine evasion.
- **SM2 floor 100 m -> 25 m** (sim/arsenal.py): misses now come from
  physics; the floor regression test retired for the statistical contract
  (tests/test_sm2_statistics.py).

**Measured** (tools/probe_sm2_batch.py, N=20 seeded CombatWorld battles
per cell, REAL world.launch Oniks vs destroyer_00, weave in the loop —
kill-per-engagement of the SM-2 layer):

| config                  | lo-lo (60 m) | hi-lo |
|-------------------------|--------------|-------|
| old 100 m floor         | no shot taken| 1.00  |
| floor 25 m, sigma 0     | 1.00 (20/20) | 1.00  |
| sigma 18 (first guess)  | 1.00 (20/20) | 1.00  |
| sigma 30 / 45 / 50 / 55 | 0.90/0.60/0.60/0.55 | 1.00 |
| **sigma 60 (LOCKED)**   | **0.50 (10/20)** | **1.00 (20/20)** |

Gate contract met: hi-lo >= 0.8 (1.00 — intercepts happen at 14 km, far
above the noise region), lo-lo in 0.25-0.60 (0.50). Of the 10 lo-lo
leakers: 3 die to CIWS, 7 hit the destroyer — the gun layer matters
again. First-guess sigma 18 killed 20/20: PN low-passes the tau 0.5 s
wander, so the felt miss is well under the raw sigma — the reason the
value had to be measured, not eyeballed. Locked two-sided in
tests/test_sm2_statistics.py (60 m 3-round engagement batch 0.458 in
[0.2, 0.65]; 3 km batch 10/10 >= 0.75; clean control kills every time;
lock-break coast + reacquire).

## Phase 5a — air war scaffolding (integration, 2026-06-12)

Workflow `combat-phase5`: 2 parallel implementers (sim/enemy_air.py
Fighter/Awacs/Carrier/AirBase state machines, 54 tests; models
fighter/awacs/carrier/airfield, 32 tests), then the integrator. NO
weapons employment in 5a — fighters fly and rearm, the AWACS senses;
commander AI / JASSM/HARM delivery / AIM-9X / 40N6 are 5b.

- world/combat.py: exactly ONE Carrier joins `self.ships` at the FIXED
  deep anchor (0, 280 km) — open-water verified, the spawn-zone carrier
  band's mode range (seeded sample_fleet placement is Phase 7). Enemy
  AIRFIELD Structure pinned at (60 km, 516 km): probed dry land, 4.1 m
  height spread across the full 2.5 km runway footprint (flattest of a
  20-cell sweep); swept against PLAYER cruise missiles (mirror of the
  hostile-vs-base pass), hp 4. 2 fighters at the airfield + 2 on the
  carrier + 1 AWACS in `self.enemy_air` (NOT self.aircraft — that list
  is legacy sandbox traffic). Standing-CAP scheduler keeps 2 airborne
  (round-robin launches, bingo RTB to nearest surviving base, 90 s
  rearm queue); the 5b commander replaces it.
- Enemy picture symmetry: sim/enemy_defense.py gains `cue_radars_fn` —
  the AWACS radar contributes to track FORMATION for every destroyer
  (remote cue, local illumination: SARH terminal lock-break still runs
  from the launching ship's own director, the documented CEC seam).
- Drone ELINT/RWR emitter lists now include the AWACS (always emitting,
  5a doctrine) + airborne fighter nose radars; the carrier's mount is
  silent. Fixed-installation fog of war: the airfield reaches the map
  only after SAR images it (`airfield_known` latches; the 3D scene
  always shows the geometry).
- Integrator-caught seams: FighterRadar lacked the `antenna_alt`
  passthrough ELINT reads (AttributeError on first listen pass);
  Fighter/Awacs had no pitch/roll render attitude (draw pass needs
  them — added, sharing the spiral constants); the inherited ship burn
  ladder made ANY single hit terminal, voiding spec 5.4 "multiple Oniks
  hits" — Carrier damage control contains a burn while hp > 0 (only hp
  exhaustion sinks her; 6 real OBB hits to sink, locked by e2e).
- Updated-to-new-truth assertions (not weakened): test_combat_world
  ship roster now pins destroyers + exactly one carrier; phase-3 e2e
  silent-radar test pins per-class magazines (carrier ships 0 TLAM).
- Gate: 607 tests green (17 new e2e incl. a real 281 km Oniks hit on
  the carrier), smoke_combat 36/36 incl. CAP spin-up, bingo
  RTB-land-rearm, airfield-kill divert, ELINT hears the AWACS.
- 5b notes: fighter landing descends at 5 m/s from 9 km (a ~30 min
  approach — works, reads slow; RTB should descend en route), fighters
  land at y=0 even at the 140 m-elevation airfield (sub-pixel at range;
  parked airframes are not drawn), fighters stranded PARKED at a dead
  base need the commander's call, Fighter.hardpoints loadout dicts land
  with employment.

### Phase 5a orchestrator gate (2026-06-12)

- Verifier PASS (608 tests incl. its own winchester-approach regression
  pin, smoke 36/36); suite + smoke re-run green by orchestrator.
- Models viewed personally (tools/probe_air_force_views.py): carrier and
  airfield read correctly; fighter slightly missile-ish; AWACS shot too
  distant to judge — re-shoot at the playtest. Nits filed in the Phase 8
  backlog. 5b must take the verifier OPEN list (fuel math vs airfield
  geometry, dead-base rearm queue, descent profile, field-elevation
  landing, sinking-carrier queue, SM-2 ammo waste on far drone cues).

## Phase 5b — the commander runs the war (integration, 2026-06-12)

Workflow `combat-phase5`: 2 parallel implementers (sim/commander.py
EnemyCommander/EnemyPicture brain, 25 tests; sim/a2a.py AIM-9X + 40N6 +
fighter employment, 23 tests), then the integrator.

- world/combat.py: the commander ticks at 1 Hz on a SENSOR-ONLY picture
  fed at the 0.25 s defense cadence — ESM accrual on the emitting player
  radar, player missile tracks (with first-seen metadata) from whichever
  SPY-1/AWACS/nose radar physically detects them, drone tracks at
  stealth-class ranges. Orders execute here: HARM/JASSM packages roll
  PARKED jets silent-ingress (HARMs home on the actual EMITTER object —
  silence degrades to the seeded 150-400 m CEP offset and the radar
  SURVIVES), Tomahawk salvos at back-plotted clusters, AWACS flee/resume,
  ship silence with a sector-quiet gate (a drone track inside the 22 km
  engagement window keeps/raises the radar — spec 4.3 "silent ships may
  light up"), drone-hunt vectoring (fly to last-known; entity pursuit
  only after an own-nose-radar reacquire, and never re-vectored off it).
  Commander-managed CAP replaces the 5a scheduler (same rotation, gated
  off while a strike package owns the flight line). HARM BDA: a finished
  package believes the emitter dead until it is heard again.
- Terminal scene-matching (JASSM IIR / TLAM DSMAC class): a believed aim
  point within SEEKER_BASKET_M = 1 km of a live player structure acquires
  it at OBB mid-height; the measured 3-launch back-plot lands 264 m off
  the base, so strike accuracy emerges from sensor geometry, never dice.
- Kill-chain physics fixed by probe (tools/probe_5b_*): the air-launch
  descent ramp realized only kp/kd*30 ~ 9.5 m/s (JASSMs arrived terminal
  km-high and splashed) — the PD now gets its true 30 m/s equilibrium
  offset; the terminal commit line grazed the coastal rise under the
  cliff-top base (1.3 km short, measured) — stage 1 now also rides the
  deck while BELOW the aim point altitude (radar-station TLAM geometry
  bit-unchanged); fighters at 9 km could never close the 6 km 3-D IR
  gate on the 18 km drone — intercepts snap-up to the 15.5 km F/A-18E
  combat ceiling.
- 5a OPEN list closed: dynamic bingo reserve from the ACTUAL leg to the
  nearest surviving base (endurance 2 400 -> 3 600 s for the measured 5b
  strike legs); RTB descends en route on a 4 deg glide (the 30 min
  hover-down is gone); touchdown at field elevation; a dead/sinking base
  aborts in-progress rearms (fighters strand PARKED, launch refuses);
  SM-2 drone shots held inside DRONE_ENGAGE_RANGE_M = 22 km (the
  phase-4-measured 0.27-Pk waste zone beyond it).
- Player 40N6: V (rebindable `sam_round`) toggles 48N6 <-> 40N6; HUD
  panel/map strip show the selection + both stocks; the map ring swaps
  envelopes; 4 km floor + empty-stock hints. world.victorious (spec 2.2:
  all enemy ships + airfield; enemy ground radars join in Phase 7) drives
  a VICTORY banner mirroring the defeat one.
- Updated-to-new-truth (not weakened): 5a CAP e2e runs the radar silent
  (emitting now correctly draws a HARM package on top of the CAP);
  phase-4 drone-hunt e2e grounds the air wing to keep isolating the SM-2
  channel it pins.
- Gate: 664 tests green (25 commander + 23 weapons + 8 5b e2e incl.
  defeat-reachable: 3 Oniks -> cluster -> JASSM package -> Bastion dead
  -> DEFEAT; 40N6 kills the AWACS at 265 km; IR kill with ZERO RWR LOCK
  events), smoke 47/47.
- 5b verifier fix: the RTB glide sank at exactly the profile's own
  closure rate (cruise x tan 4 deg), so a jet starting ABOVE the 4 deg
  profile (bingo inside the ~129 km glide intersect, or descending off
  the 15.5 km snap-up ceiling after a drone hunt) kept its whole excess
  altitude to the field and crawled it off at the 5 m/s landing rate —
  the 5a hover-down resurfacing (probe: 1.9 km high over the field /
  812 s landing from a 100 km, 9 km start; ~5 km high post-snap-up).
  RTB_CATCHUP_SINK_MPS = 40 m/s (~9.5 deg idle/speedbrake descent at
  cruise) now converges onto the profile; once ON it the clamp rides it
  bit-identically (probe re-run: on-profile at 51 km out, 477 s landing,
  touchdown at field elevation).
- Verifier probes (suite + smoke re-run green after the fix): back-plot
  cluster lands 264 m off the true base (inside the 1 km basket; HIGH
  first-detection tracks produce ZERO back-plots); a fully silent player
  (radar dark, no launches) is NEVER found over 400 s — zero fixes, zero
  clusters, zero offensive orders, zero hostile rounds; the 40N6 kill
  survives the launching site (radar station + S-300 TEL structures)
  dying 5 s into the flight (true ARH); SM-2 drone discipline holds all
  shots beyond 22 km and engages inside; full-battle step cost 0.63 ms
  mean / 2.5 ms p95 at the 120 Hz step (8.33 ms budget).

## Phase 7 — setup screen + end screen + enemy radars (integration, 2026-06-13)

- Full flow wired: menu COMBAT -> CombatSetupState (World/Armory pages),
  START -> App.start_combat(config) -> CombatState(app, config) ->
  CombatWorld(config). start_combat stays backward-compatible (config=None
  -> default config) so the smoke tool and any bare caller are unchanged.
- Enemy ground radars (spec 5.5): config.n_enemy_radars units on the enemy
  continent. The 3D geometry ALWAYS renders (one build_radar_station mesh
  per unit in CombatState._site_draws, freed by the base dispose); the
  tactical MAP marker is fog-gated — latched only once a player sensor
  (drone SAR or the radar net) images the pin, mirroring airfield_known.
  known_enemy_sites surfaces the airfield + every imaged radar; the latch
  lives in _update_airfield_intel (cadence shared, no early-return on the
  airfield so radars still latch after it). Valid Oniks targets + part of
  the victorious win condition (all ships + airfield + radars dead).
- End screen: CombatState owns a CombatEndOverlay (not an app-state switch),
  latched the first frame world.defeated/victorious flips (defeat outranks).
  The sim keeps running underneath, dimmed — render draws the live scene
  then the overlay's dim+panel; input routes to the overlay. REMATCH ->
  start_combat(SAME config); NEW BATTLE -> open_combat_setup; MAIN MENU ->
  quit_to_menu. The 5b inline HUD banner still reads underneath.
- Armory HUD: the Bastion block gains an Oniks magazine row — "n/cap" green
  while loaded, "0/cap RLDG <s>s" amber while the refill timer runs (pure
  game/hud.oniks_ammo_row; None in the sandbox so its infinite Oniks shows
  no row). S-300/Pantsir readouts already carried magazine state.
- Updated-to-new-truth (NOT weakened): test_states menu-COMBAT now asserts
  the setup screen opens (was: straight into the battle); test_phase5a SAR
  airfield-reveal asserts the airfield is PRESENT in known_enemy_sites
  (the DEFAULT overflight point sits ~9 km from enemy_radar_01, inside the
  25 km SAR strip, so it legitimately images that radar too); smoke
  Phase-4/5b drone legs rebuilt RELATIVE to the seeded fleet (the retired
  DESTROYER_SPAWNS fixed anchors no longer hold — back-plot/drone-hunt use
  seed=5 per the canonical probe geometry, ELINT/SAR derive from live hulls).
- Gate: 790 tests green (16 new Phase-7 e2e: menu->setup->config->world
  flow, end-screen callbacks fire the right App flow, enemy-radar fog-of-war
  reveal + latch, victory needs radars dead, stepped determinism, sandbox
  untouched). smoke 69/69 incl. config-driven order of battle, Oniks 3->0->
  lock->refill, full victory condition, bit-identical 5 s stepped battle.
  Headless GL drive of the whole flow (menu->setup->combat->DEFEAT/VICTORY
  overlay->REMATCH/NEW BATTLE/MAIN MENU) renders every frame without crash.

## Phase 7 VERIFY (adversarial)

- Re-ran full suite + smoke from scratch: 790 baseline green, smoke 70/70 exit 0.
- Determinism (scratch probe, deleted): CombatWorld(CombatConfig(seed=S)) x2 for
  seeds 1337/7/99999/2024 -> bit-identical fleet anchors, enemy-radar pins, AWACS
  + Pantsir positions. 60 s of 120 Hz stepping on two same-seed worlds stayed
  bit-identical (ships/missiles/air pos+alive, oniks_fired); different seeds
  diverged in both layout and 60 s outcome. PASS.
- Armory: oniks_ammo=2 -> exactly 2 launches then lock then refill-to-cap;
  SANDBOX WorldState Oniks still infinite (50/50 launches, _oniks_ammo is None).
  S-300 48N6/40N6 + Pantsir 57E6 magazine seed + empty-refill all correct. PASS.
- Win/lose: victory withheld with ships dead but airfield OR radars alive;
  trips only when ships AND airfield AND all ground radars dead (also the
  n_enemy_radars=0 path). defeat = all bastion TELs dead; launch() returns None
  after defeat. PASS.
- Fog of war: enemy radars absent from known_enemy_sites until a sensor images
  them, then latched (persists after the drone leaves); alive radars cue the
  commander, dead ones drop from the cue list; no truth leak for distant radars. PASS.
- Perf: extreme config (12 destroyers / 6 radars / 6 Pantsir / 3 AWACS) mean
  step 0.502 ms, default config 0.228 ms — both well under the 8.33 ms @120 Hz
  budget. Steps 10 s with no crash. PASS.

- FIXED (small): pantsir_gun_ammo schema default is 700 but clamp_config() ran
  gun ammo through CLAMP_AMMO=(1,200), so the default-through-setup path (open
  setup, press START untouched) silently truncated the 30 mm belt 700 -> 200
  (~7.5 s of gun engagement vs ~25.5 s). Added a dedicated CLAMP_GUN_AMMO=(1,1000)
  used only for gun ammo (floor still 1, so test_clamp_config_ammo_floor is
  unchanged); setup gun-ammo stepper hi now 1000. New regression test
  test_clamp_config_preserves_default_gun_belt. NOTE: this adds a clamp constant
  beyond the locked "ammo 1-200" schema line to resolve a contradiction with the
  locked pantsir_gun_ammo=700 default; integrator should confirm the deviation.
- Gate after fix: 791 tests green (1 new), smoke 70/70 exit 0; end-to-end
  setup build_config() default now preserves 700.

## Phase 8 — Zircon hi-lo terminal-dive fix (anti-overfly, 2026-06-15)

- BUG (fresh Phase-8 code): the 3M22 Zircon on a hi-lo profile OVERFLEW the
  target at common ranges. Measured (tools/probe_zircon_traj.py): a 150 km
  hi-lo shot crossed directly over the target still at 4.4 km altitude, then
  wallowed in TERMINAL on the far side and splashed ~20 km past it (t=309 s).
  300 km "hit" only by luck (a shallow dive that bottomed out near the target).
- ROOT CAUSE (measured, not guessed): the hi-lo descent gains
  (DESCENT_RAMP_RATE / DESCENT_MAX_SINK / the descent alt-hold authority) are
  calibrated for the ~Mach-2.5 Oniks. The Mach-8 Zircon covers the fixed
  ~118 km descent corridor ~3x faster than the 220 m/s ramp can bleed altitude,
  so it reaches the target's ground position still kilometres high. The author's
  earlier mitigation (cruise_alt 14 km + terminal_range 100 km, arsenal.py)
  could not help: terminal_range is only consulted on the lo-lo profile — the
  hi-lo descent trigger is _descent_range(), which terminal_range never touches.
- FIX (sim/missile.py): a per-missile descent SCALE = max(1.0,
  weapon.cruise_mach_hi / DESCENT_BASELINE_MACH=2.55) multiplies the descent
  ramp rate, the descent alt-hold pull-down authority, and the sink clamp — only
  in PH_DESCENT. A faster round dives proportionally steeper INSIDE the same
  descent corridor, so it still arrives at sea-skim with the full
  SKIM_CAPTURE_RANGE speed-bleed margin and does not overshoot horizontally
  (an early experiment that shrank the corridor instead made it arrive low but
  too fast and overshoot — reverted). The descent START range is unchanged, so
  the Zircon keeps its long high Mach-8 cruise (the SM-6 counterplay axis,
  GAME_ANALYSIS §7). The Oniks scale is exactly 1.0 -> BIT-IDENTICAL.
- ENVELOPE (measured): hi-lo now hits cleanly across 80-250 km (was a MISS at
  150 km); lo-lo 80-150 km. The Zircon is fuel-starved past ~100 km and coasts,
  so ~250 km hi-lo is its honest reach (comfortably outranges the 150 km SM-2);
  300 km is an honest out-of-range MISS, not the prior overfly bug.
- TDD: tests/test_missile.py test_zircon_hi_lo_medium_range_hits (150 km, the
  RED test) + test_zircon_hi_lo_long_range_hits_and_stays_high (250 km, also
  asserts the high cruise survives). Watched the 150 km test fail (impact
  19768 m off) before the fix.
- Gate: 804 tests green (+2 new), Oniks flight + determinism bit-identical
  (same suite dot-pattern as the pre-fix baseline). verify_new_weapons.py +
  probe_zircon_traj.py updated to the corrected envelope.

### Phase 8 follow-ups (same session, 2026-06-15)

- FIX (correctness/memory): the enemy commander's picture.missile_tracks dict
  grew unbounded — prune_missile_tracks() existed but was never called. Wired it
  into CombatWorld._feed_enemy_picture (0.25 s cadence) using the live player-
  missile track-id set; drops records whose missile is gone AND last seen > 30 s
  ago (mirrors the world intel prune + live_missile_tracks' 30 s window, so
  back-plots/orders are unaffected). Test: tests/test_combat_world.py
  test_dead_missile_tracks_are_pruned (RED first: stale track persisted).
- FIX (stale tool): tools/smoke_combat.py still re-armed the Oniks with the
  pre-salvo-battery idiom `world.reload_left = 0.0`, which is now a no-op (the
  launcher arms off per-tube _oniks_tubes state). After firing the 2 initially-
  loaded tubes the third launch returned None and the harness crashed
  (m9.alive on None). Replaced both launch loops with the per-tube instant
  re-cock used in test_combat_config.py (zero each tube's reload_left, then
  _step_oniks_tubes(0.0) to reload from the magazine pool). Smoke back to 70/70.
- Gate: 806 tests green (+2 this follow-up), smoke 70/70 exit 0.

## Phase 8 — enemy lethality / "you can actually lose now" (2026-06-15)

User report: the enemy had never killed the player once; planes died/orbited
without effect. An independent Opus-4.8 clean-room audit + headless measurement
traced it to ONE keystone bug, plus a secondary deadlock.

- RANK 1 (keystone) — launch-site back-plot was geometrically broken for LEVEL
  flight. process_missile_track (sim/commander.py) back-projected the launch
  point by extrapolating the first-detection velocity to the surface
  (t_back = fy/vy). A sea-skimming Oniks cruises at vy~0, so the math was
  degenerate and slid the estimate ~75-84 km the WRONG way (into the enemy's own
  quadrant) — measured. Clusters formed but their centroids were 20-80 km off,
  far outside the 1 km seeker basket, so every Tomahawk/JASSM hit empty ocean
  and the bastion TEL was unhittable even with 0 Pantsir. FIX: a climbing
  boost-phase detection (vy >= BACKPLOT_CLIMB_VY=50) still time-projects to the
  surface (accurate near launch — the seed-5 smoke path is unchanged); a LEVEL
  sea-skimmer instead intersects its horizontal ground track with the known home
  coastline (HOME_COAST_Z=0; the enemy knows the coast, the bearing fixes where
  along it). A coast-parallel/receding dogleg is NOT localized (player
  counterplay). Test: tests/test_commander.py
  test_backplot_level_seaskimmer_localizes_to_launch_coast (RED first: 152.6 km
  off). MEASURED end-to-end (tools/probe_base_attack.py, seed 1337, 12 lo-lo
  Oniks, radar on): base LOCALIZED at cluster_err 643 m; a Tomahawk closes to
  4 m of the TEL. With 0 Pantsir the base is DESTROYED (defeated=True) — you can
  lose. With the default 2 Pantsir the TEL is hit but survives (point defense
  earns its keep). Before the fix the closest any strike got was ~21 km.
- RANK 2 — JASSM blind-before-kill DEADLOCK. _doctrine_kill's docstring says the
  gate releases once HARM is winchester ("we cannot blind, but can still kill"),
  but the code was strict (jassm_gated = radar_alive) and the radar belief
  re-latches alive every 0.25 s while it emits — so with the radar on, JASSM was
  suppressed forever. FIX: jassm_gated = radar_alive AND can_arm_harm_package(4)
  (matches the docstring). Test flipped to the new truth
  (test_doctrine_jassm_released_when_harm_winchester_and_radar_alive).
  NOTE: in a full battle the dedicated fighter JASSM base-strike is still
  availability-limited (only 4 fighters, busy on CAP/HARM), so the Tomahawk path
  is the primary loss axis; more plane aggression is a fighter-allocation tuning
  follow-up, not done here.
- RANK 3 (JASSM 30 m/s descent "wallow") — INVESTIGATED, NO CHANGE. The audit
  claimed a JASSM can't reach the base even with perfect targeting; direct
  measurement (a JASSM flown at the base) refuted this — it impacts within 1 m
  from 150 km and 250 km standoff at the current descent rate. The audit's
  number was a release-geometry artifact. No fix applied (measure, don't guess).
- DESIGN — setup fields n_awacs / n_player_radars / n_drones were accepted by the
  armory UI + CombatConfig but IGNORED by CombatWorld (one awacs/radar/drone
  hardcoded). Made the UI honest: those three are now FIXED rows (the sim fields
  one of each; multi-unit cascades into the enemy datalink/ESM model and the
  drone control UX — a focused follow-up). CombatConfig + clamp_config keep
  their full ranges so the wiring can land later without a schema change.
- QOL — clicking an air contact with the Oniks armed flashed a vague
  "SELECT SURFACE TARGET"; now "ONIKS HITS SHIPS ONLY - TAB TO S-300 FOR AIR"
  (the documented cause of the "can't launch" confusion).

## Phase 8 — smarter sensor-driven enemy AI (planes + AWACS) + systems audit (2026-06-15)

Driven by a user request to make the enemy genuinely smarter WITHOUT cheating
(fog of war preserved — the AI reads only the sensor-derived EnemyPicture, never
truth) and to verify every sensor/weapon system. Method: a measured systems
audit (12 probe agents), then TDD'd implementation, then TWO adversarial review
workflows (no-cheat audit + code review + game-test) per the user's process.

- SYSTEMS AUDIT (tools/probe_audit_*.py): ship SPY-1 radar, fighter nose radar
  (60 deg cone, 110/80/60 km), AWACS, drone stealth, drone RWR (SPIKE/LOCK) +
  ELINT geolocation (~1.3-3.6 km after ~2 min cross-track), Pantsir, CIWS, the
  commander brain — all WORK, fog-of-war intact, no truth leak, deterministic.
  SM-6 and Zircon were PARTIAL (below).
- T3 SM-6 area defense (sim/enemy_defense.py): was a paper weapon — iterated only
  the drone track store (stealthy, seen <=40 km) so its 240 km reach was
  unreachable. Now _try_sm6_launch ALSO engages HIGH inbound cruise missiles
  (alt >= SM6_AREA_MIN_ALT_M=1500 m, range SM6_MIN_RANGE_M=50 km..240 km) from
  the missile track store with a plain SamMissile (clean track, no stealth
  noise). MEASURED: hi-lo Oniks killed at t=207 s; lo-lo Oniks survives (the
  'go low to survive' loop holds). tests/test_sm6_area_defense.py.
- T1 AWACS EMCON (world/combat.py + sim/commander.py): the AWACS was a free
  always-on beacon. Now it runs SILENT while fleeing a threat and re-emits when
  clear, with an anti-strobe dwell (AWACS_EMCON_DWELL_S=60 s) so a sole-sensor
  AWACS doesn't un-blind itself when its own dark track ages out. Sensor-driven
  off picture.live_missile_tracks. tests/test_awacs_emcon.py.
- T2 fighter RWR-driven evasion (world/combat.py _assign_air_threats): a fighter
  breaks when a player SAM is GUIDING ON it (RWR lock = SAM.target is the
  fighter), reacting out to FIGHTER_RWR_REACT_RANGE_M. CONTRACT FIX (review
  MF-1): the break GEOMETRY comes from the commander's dead-reckoned missile
  TRACK store (the same picture the SM-2/SM-6 fire off), NEVER the SAM's true
  position; the old truth-reading 25 km geometric backstop was removed. A SAM
  locked-but-not-tracked yields no break. tests/test_fighter_rwr_evasion.py.
- CLEANUP: removed the dead no-op line in process_missile_track; prune_missile_
  tracks now also bounds the append-only _back_plots guard list.
- T6 Zircon fuel-range warning (game/sandbox.py): firing a Zircon beyond its
  measured envelope (hi-lo ~250 km / lo-lo ~150 km) flashes a HUD warning
  instead of a silent fall-short whiff.
- DELIBERATELY NOT CHANGED: the CIWS flat-Pk burst roll. A true constant-
  dispersion physics model changes the Pk envelope (~1/R^2 vs the calibrated
  linear ramp = a balance regression); preserving the exact envelope makes any
  conversion cosmetic. GAME_ANALYSIS deems the guns 'deliberately probabilistic
  last-ditch layers' and the CIWS is rarely reached. Left as-is with this note.
- REVIEW LOOP: two adversarial review workflows. Review 1 found MF-1 (fighter
  evasion truth-leak) + SF-1 (AWACS strobe) — both fixed above; review 2
  re-verifies. Gate: full suite green (~820 tests), smoke green, Oniks-vs-SM-2
  duel + Oniks descent bit-identical, determinism bit-identical.

### Phase 8 enemy-AI — review-2 closeout (2026-06-15)
- Second adversarial review verdict: SHIP IT. MF-1 (fighter no-cheat) and SF-1
  (AWACS dwell) confirmed resolved in source AND by probe; no new truth leak /
  determinism break / regression; SM-2 duel 7/7; full suite 815/0; two same-seed
  worlds bit-identical over 6000 steps. Measured capability gain is physics-
  grounded: evasion ON-miss >= OFF-miss at every range (+6 survivals via energy
  bleed, e.g. 90 km shot falls 6 km short), not a buffed hit-table.
- Cleanups applied from review 2: disarmed silent Carrier now also has
  sm6_ammo=0 (was firing SM-6 on AWACS cues while dark — incoherent);
  _defend_awacs flee order uses the captured threat_pos.copy() (not the leaked
  loop var); deleted the now-dead FIGHTER_EVADE_RANGE_M constant (+ its probe ref).
- Deferred (review-blessed): residual ~1-tick AWACS blink every ~91 s while a
  threat lingers (already 3x better than the old 31 s strobe; a full fix needs
  positive-clear gating); SM-6 fleet saturation measured BOUNDED (no runaway);
  CIWS flat-Pk roll left intact (see prior note) — flagged for a separate audit.
- Final gate: full suite 815 green, smoke 70/70 exit 0.

---

# Overnight expansion (branch `feat/combat-expansion`) — 2026-06-16

Autonomous Fable-Method build of the handoff bundle (`docs/research/handoff/`,
6 milestones). Baseline at checkpoint `ac697d2`: smoke 70/70 exit 0, full suite
exit 0 (~815 tests → 840 collected once M1-F1 tests land). Per-feature loop:
implementer (opus) → spec-compliance review (opus, distrusts implementer) →
code-quality review (opus) → fixer if needed. Agent ledger: `docs/overnight_run_log.md`.

## Milestone 1 — Legibility Foundation

### M1-F1 Widget primitive library (commits `73e7bfd`, `fa72af0`)
- **Files:** `game/states.py` (+`badge`/`gauge_bar`/`mini_compass`/`tab_strip`/
  `scroll_list` + `SEMANTIC_STATES`/`SEMANTIC_COLORS` beside the existing
  `draw_panel`/`draw_header_rule`); NEW `game/hud_widgets.py` (alpha-0.55 HUD
  variants delegating to states.py via `alpha=` — one source of truth);
  `game/combat_setup.py` (inline tab loop → `tab_strip(...tab_w=...)` dedup);
  NEW `tests/test_widgets.py`.
- **Contracts added:** badge emits exactly 1 rect + 1 border + 1 text and
  returns width; gauge_bar frac=0→no fill, frac=1→full width, clamps [0,1];
  `SEMANTIC_COLORS` total over `SEMANTIC_STATES` (parametrized); mini_compass
  radial tick lands on the 47° outer radius (≤2px); hud_widgets fill alpha 0.55;
  tab_strip fixed-column mode byte-identical to combat_setup's old inline loop
  (regression). 26 new tests.
- **Fog-of-war color contract encoded:** ready/armed/friendly→OK_COL,
  reload/transient→WARN, inbound/destroyed/terminal→DANGER, label→MUTED,
  accent→ACCENT, **ESTIMATE→ACCENT_DIM** (sensor guesses read dimmer than
  friendly truth). No hard-coded RGB at any call site (verified by review grep).
- **Reviews:** code-quality APPROVED (3 minor nits). Spec-compliance REJECTED on
  the missing tab_strip refactor (spec F1 contract). Fixer extracted the tabs
  into a fixed-column `tab_strip` mode, proved byte-identical empirically
  (`old.calls == new.calls` for active=0,1), added the regression test, derived
  `SEMANTIC_STATES = tuple(SEMANTIC_COLORS)`, fixed the docstring. Re-verified by
  orchestrator: targeted tests green, combat_setup diff is the clean one-call dedup.
- **Gate:** `pytest -q` exit 0, 841 collected (840 + tab regression). Pure UI;
  no sim/world change; no fog/determinism/physics surface touched.

### M1-F2 track['kind']/track['size'] stamps (commits `cda32d3`, `f2e5afd`)
- **Files:** `sim/contacts.py` (`_size_of`/`_kind_of` helpers; track creation
  stamps `size`=radar class + `kind`=weapon_id; `_seen` refactored to `_size_of`);
  `world/combat.py` (launch-warning channel + ELINT-fix channel both stamp);
  `sim/a2a.py` (IrMissile self-names `weapon_id="aim9x"` — no WeaponDef);
  NEW `tests/test_track_stamps.py`.
- **Contracts:** ship→size='ship'/kind=None; air→'fighter'; strike→'missile'/
  weapon_id; stamps additive (estimate + every existing key unchanged); ELINT
  ship-track carries the stamps too. 5 tests.
- **Bug caught by the smoke gate** (per-feature gate discipline working):
  `IrMissile` (AIM-9X) has no `.weapon` → first stamp crashed smoke. Fixed by
  guarding `.weapon` + a self-named `weapon_id` fallback. Smoke back to 70/70.
- **No-cheat verdict (review):** CLEAN — `size`/`kind` are the radar/IR
  classification axis (same provenance the detection gate already uses), NOT a
  truth-position read; no new track-creation path; no fog bypass; determinism
  intact (no RNG).
- **Review finding fixed:** spec-review caught a THIRD track-creation site
  (`_inject_elint_tracks`) missing the stamp — fixed via the shared helpers,
  locked with an ELINT-injection test.
- **Gate:** smoke 70/70 exit 0; stamp+gating+e2e regressions green.

### M1-F3/F5 Threat-Warning strip + Click-contact intel panel (commit `e401d67`)
- **Files:** `game/hud.py` (pure `threat_rows(world, friendly_xz, now)` →
  `ThreatRow(sid,kind,brg,rng,tti,severity)`; pure `contact_intel(world, sid,
  origin_xz, now)` → dict; `HUD._threat_strip` + `HUD._intel_panel` draw methods
  composing the M1-F1 widgets); `game/tactical_map._chrome` wires both;
  NEW `tests/test_threat_strip.py`, `tests/test_intel_panel.py` (11 tests).
- **Contracts:** TTI sort ascending; severity DANGER<20s / WARN<60s / MUTED;
  outbound→TTI None sorts last; only `is_air` + `HOSTILE_KINDS` tracks appear
  (player kinds excluded — friendly rounds can't show); empty→[]; intel CLASS
  from is_air+size, id ladder by age (IDENTIFIED<5s / CLASSIFIED<20s / UNKNOWN),
  confidence fades, dead_reckoned at age≥20s, course=compass(vel); determinism.
- **LOAD-BEARING fog test:** a hostile in `world.missiles` but absent from
  `contacts.tracks` does NOT appear. PASSES.
- **No-cheat verdict (review, line-by-line incl. draw methods):** FOG-HONEST
  end-to-end — helpers AND `_threat_strip`/`_intel_panel` source only the gated
  picture + friendly own-asset constants (BASE_POS); zero enemy-truth reads
  (grep confirmed truth refs only in docstrings). TTI origin = player base
  (friendly truth, allowed). Single-flush preserved (no flush in the methods).
- **Reviews:** spec+no-cheat APPROVED; code-quality APPROVED (no Critical/
  Important; minor nits logged: strip rows use draw_text not badge() pills, one
  unnamed gauge gap, a label-color comment — cosmetic, deferred).
- **Gate:** `pytest -q` 857 passed; smoke 70/70 exit 0.

### M1-F4 Tube/battery status panel (commit `c8d0d7e`)
- **Files:** `game/hud.py` (pure `tube_cells(world, platform)` → list of
  `(label, state, frac)`; `_block` gained an optional `cells=` arg + a
  `_tube_cells_row` that draws a badge per tube + an amber reload gauge;
  `_bastion_block`/`_s300_block` wire it); `game/states.py` (+`EMPTY`→DISABLED
  in SEMANTIC_COLORS); NEW `tests/test_tube_panel.py` (6 tests, vs a real
  CombatWorld).
- **Contracts:** fresh battery all READY (frac 1.0); mid-reload tube RELOADING
  with frac strictly in (0,1) and others unaffected; empty magazine → all EMPTY;
  S-300 cell count == tube count; SANDBOX (no _oniks_tubes) → [] (panel hidden);
  determinism. Oniks state: reload_left>0→RELOADING, loaded→READY, else EMPTY;
  S-300 READY when either 48N6/40N6 pool>0 (shared 5P85 tube).
- **Own-force only:** reads ONLY world tube/ammo attrs (getattr-guarded); zero
  contact/enemy/truth reads; green/amber/disabled idiom (never CONTACT_COL).
  `_block(cells=None)` is byte-identical (SANDBOX + existing blocks unaffected).
- **Bug caught by smoke:** first badge call had a bad signature → TypeError;
  fixed to `badge(renderer,label,x,y,state)`; smoke green; screenshot verified
  (TUBES row + READY badges inside the panel chrome).
- **Known minor limit:** >5 tube cells could clip the 268px panel; current
  configs have ≤4 (single Bastion=2 / S-300=4 TEL). Flagged for multi-launcher
  configs (M5). Render placement: extended `_block` (backward-compatible).
- **Gate:** `pytest -q` 864 passed; smoke 70/70 exit 0.

### M1-F6 Toast/hint upgrade — DEFERRED (documented)
- `toast_stack` primitive + a stacked transient-message queue is deferred:
  the existing `sandbox.hint_text`/`HUD._hint_flash` one-liner works and the
  stacked-toast upgrade is cosmetic polish. Flagged for a later pass / the
  morning review. Not a blocker for the M1 legibility goal.

### M1 GATE — PASSED clean in one pass (commit `3c10066` + probe)
Orchestrator-verified + adversarial fleet (all opus):
- **Full suite** `pytest -q` exit 0 (~864 tests). **Smoke** 70/70 exit 0.
- **Regression contracts BIT-IDENTICAL:** Oniks-vs-SM-2 duel
  (`test_sm2_statistics`), Oniks/SAM flight (`test_missile`), SM-6 area defense
  all green — M1 (pure UI + additive stamps) touched no physics/RNG.
- **GAME-TEST (live headless battles, measured):** threat strip exercises all
  severity bands live (MUTED 102→62s / WARN 58→20s / DANGER 19→1s), TTI shrinks
  monotonically, rounds drop off after impact; **FOG confirmed in a live battle**
  — 2 Tomahawks in `world.missiles` under the horizon → 0 contacts → 0 strip
  rows; tube reload frac 0→0.875 monotonic over 120 s; intel fresh→IDENTIFIED
  conf 1.0, age 25 s→UNKNOWN+dead_reckoned; **DETERMINISM bit-identical, MAX
  positional delta EXACTLY 0.0 at 15 000 steps**; 795 helper calls, 0 exceptions.
  Probe left at `tools/probe_m1_legibility.py`.
- **BUG-HUNT:** SAFE TO GATE — one LOW (latent `scroll_list` row_h<=0
  ZeroDivisionError, no caller yet) fixed defensively (`3c10066`).
- **NO-CHEAT auditor:** CLEAN — no truth leak in helpers OR draw methods; stamps
  are the classification axis (gate provenance), not a position read; estimate
  idiom (dim amber) vs friendly truth (green) visually distinct; no new RNG/clock.
- **Deferred (documented, non-blocking):** M1-F6 toast/hint upgrade; the strip's
  cosmetic badge-per-row pills; the >5-tube panel-clip edge (M5 multi-launcher).
- **Human playtest:** the ROADMAP's mandatory ~15-min hands-on COMBAT playtest
  after M1 is SUBSTITUTED by the agent game-test fleet for this unattended run;
  recommended for the morning reviewer (the legibility layer is now in place to
  make it informative).
