# Subsystem Damage Model — build run log (2026-07-06, Fable 5, lean mode)

User-approved via interview (spec: docs/superpowers/specs/
2026-07-06-subsystem-damage-design.md).  Built solo (budget-lean: no agent
fleet; the two Opus research agents ran BEFORE implementation and produced
the two normative docs below).

## Shipped (3 commits: aa89ea2, baf3377, badc0b6)

1. **sim/damage_model.py** — the physics core.  Zero RNG.  Module grids
   transcribed from `docs/research/warship_internal_layouts_2026-07-06.md`
   (Burke frames, Tico, Nimitz, merchant); cook-off energetics from
   `docs/research/magazine_detonation_energetics_2026-07-06.md`.
   - Hit location: OBB entry point (`segment_obb_entry`) → ship-local grid
     coords (z-fraction stern→bow, y vs waterline, x half-beam).
   - Structural channel: KE of the round's LIVE mass (energy model
     `m.mass`) → hull breach area (KE_PER_BREACH_M2, capped Cole-scale).
   - Blast channel: warhead-mass doses along the true 3D interior path
     (`_path_modules`); SAP runs 10% of length, frag heads detonate on
     first structure met and never breach (SAP_HARDNESS_MIN gate).
   - Module knockouts write state the AI already reads: sensors →
     radar.alive False, VLS → pool-fraction ammo zero, both MERs →
     speed 0 (dead in the water), c2 → halved fire-control cap.
   - DoT: flooding vs sealing (SEAL_RATE) vs pumps (McCain/Cole numbers),
     3-of-6-compartments sinking standard, logistic fire vs a RAMPING crew
     effort (Stark saves / Sheffield gutting emerge), deterministic
     cook-off (fire ≥ 0.75 for 90 s near a live magazine, Forrestal
     datum), yield W(n) scaled by REAL remaining rounds — full magazine
     breaks the hull (Moskva), depleted one burns.
2. **Wiring** — `CombatConfig.damage_model` (default "legacy" = the
   byte-identical flat ladder for the suite); the GAME layer passes
   "subsystem" everywhere (SANDBOX_CONFIG, setup build_config, campaign
   next_config, the screen-less combat fallback).  `state_digest` hashes
   the new state ONLY in subsystem mode.
3. **X-ray hit cam** (`game/hitcam.py`) — full-screen slow-mo (×0.25,
   sim never pauses) cutaway on every player ship hit: module schematic
   with new kills flashing red, flooding bins, fire glow, consequence
   readout, MAGAZINE DETONATION card.  Reads the WRITE-ONLY `m.hitcam`
   stamp; ESC dismisses.

## Measured ladder (tools/probe_damage_matrix.py, final constants)

| shot | outcome |
|---|---|
| Oniks, waterline, mid-ship (engines) | MER destroyed, fuel fire 0.81, 1 compartment floods — **crippled survivor** |
| Oniks, waterline, aft (near VLS + fuel) | fuel-fed fire dwells the magazine — **cook-off kill @ ~90 s** |
| Zircon, waterline | 3600 MJ → 14 m² breach, 3 compartments — **sinks in ~30 s** |
| Kh-31P (frag), mast/deck | SPY/CIC dead, hull dry — **mission kill, ship survives** |
| Swarm round (8 kg) | superficial |

Calibration change argued from the probe: `IGNITE_PER_KG` 1/400 → 1/450 so
a bare 300 kg warhead fire (0.67) stays under COOK_I 0.75 — only fuel-fed
(+0.25) or stacked fires cook a magazine, matching the approved
"one hit cripples, the second finishes" ladder.

## Gates
- tests/test_damage_model.py: 19 contracts (legacy characterization pinned
  BEFORE the change, no-RNG source guard, geometry exactness, the outcome
  ladder two-sided, subsystem battle digest-deterministic, legacy digest
  blind to the new state, hitcam stamp/logic headless).
- Full suite green twice during the build (after core: 1695 passed; after
  the game-layer flip: green) + final gate run after the hitcam wiring.
- Visual gate: tools/shoot_hitcam.py renders the cutaway through the real
  CombatState render path → renders/hitcam_{oniks_engine,arm_mast,
  magazine}.png, reviewed (fixed: ASCII-only atlas strings, fire glow
  under the module boxes, dimmer HUD bleed).

## Known nits / deferred (honest list)
- The hit cam schematic is a 2D X-ray (approved option); no 3D hull mesh
  damage states.
- Carrier grid drawn with the Burke silhouette proportions (side view is
  generic); fine at cutaway scale, revisit with dedicated meshes.
- Swarm rounds do near-zero module damage (physically honest for 8 kg;
  flag if saturation-swarm balance needs a buff).
- Sub damage keeps the existing one-ASW-hit rule (research doc justifies:
  breach at depth = loss). No sub cutaway cam.
- HUD does not yet show enemy ship damage summaries outside the cam;
  forensics hit cards could name subsystems (F2-P5 remainder).
- The four remaining expansion features (briefing, clouds+sea-state, maps,
  replay theater) are planned in docs/plans/
  feature_expansion_review_2026-07-06.md and untouched.
