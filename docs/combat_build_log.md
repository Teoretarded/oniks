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

## Phase 8 — polish backlog (rolling)

- Destroyer model: bow flare subtle, aft stack indistinct (reference-photo
  pass).
- Dedicated Tomahawk/JASSM/HARM meshes (currently reuse existing missiles).
- Visual wreck states for destroyed structures.
- Wasted close-in low SM-2 shots can splash (accepted realism; revisit).
- Longer-range player anti-ship weapon to contest the carrier's deep band
  (user: "if the oniks doesnt have the range we will build something new").
