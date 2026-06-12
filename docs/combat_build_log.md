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
