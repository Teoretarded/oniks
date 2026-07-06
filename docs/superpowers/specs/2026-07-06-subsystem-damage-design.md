# Subsystem Damage Model — approved design (2026-07-06)

Interview-approved by the user (see chat). Supersedes nothing; the flat
`hp -= 1` model stays as the `legacy` compatibility flag.

## The seven approved points

1. **Physics decides the hit point.** Swept segment vs hull OBB gives the
   entry point in ship-local coords; the flight profile (skim/dive) shapes
   the outcome. No aim menu, no dice.
2. **Impact energy = live missile mass × speed² / 2 (structural channel) +
   warhead blast channel.** Zircon ≫ Oniks emerges from physics.
3. **Real module maps per ship class** (Burke, Ticonderoga-flagship, carrier,
   AAW escort, subs; merchants = simple hull+flooding), from the normative
   research docs:
   - `docs/research/warship_internal_layouts_2026-07-06.md` (grids)
   - `docs/research/magazine_detonation_energetics_2026-07-06.md` (cook-off)
   Modules: propulsion (dead in water), magazines/VLS (cook-off scaled by
   REMAINING ammo; Mk 41 vents — catastrophe needs a sympathetic chain),
   sensors (blind), bridge/c2, flooding compartments.
4. **Crew fights back**: pumps vs flooding, fire teams vs fire. One hit
   usually cripples; overwhelming damage (big breach, magazine event)
   outruns damage control. Stark survives, Moskva dies — from the numbers.
5. **Full-screen slow-mo X-ray hit cam** on player hits (toggleable), sim
   running underneath (forensics-overlay pattern).
6. **Scope v1**: all enemy warships + submarines (pressure-hull rule:
   breach at depth = loss); merchants hull+flooding only.
7. **Permanent in every mode** (COMBAT / SANDBOX / CAMPAIGN game layers set
   `damage_model="subsystem"`); `CombatConfig` dataclass default stays
   `"legacy"` so the existing 1678-test suite is untouched; new tests cover
   the subsystem mode.

## Locked implementation conventions

Per docs/plans/feature_expansion_review_2026-07-06.md §2 (LOCKED CONVENTIONS
F2), with interview amendments:
- New module `sim/damage_model.py`: pure numpy, GL-free, ZERO RNG.
- Deterministic cook-off trigger: `fire_intensity ≥ 0.75 for ≥ T_COOK` near a
  non-empty magazine (Forrestal datum), blast `W(n)` per the energetics doc
  (`c_sym=0.15` vented VLS), fireball `R = 3.5·W^{1/3}` m for effects.
- Subsystem writes drive state the AI already reads (radar.alive, sm2/sm6
  ammo, speed, CEC) — no AI changes.
- New dynamic state (buoyancy, fire, module flags) hashed into
  `state_digest` only when the mode is subsystem; legacy byte-stream
  provably unchanged.
- Sinking reuses the existing ST_SINKING list/sink animation.

## Build order (lean mode — user budget constrained, no agent fleet)

P0 legacy characterization tests → P1 geometry+grids → P2 impact resolution
+ module knockout → P3 flooding/fire/crew/cook-off + digest → P4 calibration
probe + tightened two-sided tests → P5 X-ray hit cam → P6 subs + surfacing
(HUD/forensics/AAR kill types).

Out of scope here (tracked in the feature-expansion plan): clouds/sea-state,
maps, replay theater, briefing.
