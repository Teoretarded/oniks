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
