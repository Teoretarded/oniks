# Radar scan patterns + frequency bands — NORMATIVE (R-P0, 2026-07-07)

Status: NORMATIVE for `sim/radar.py` ScanDef assignments and the `band`
tags consumed by W-P10 rain attenuation (ITU-R P.838). Values are
real-system grounded; where public sources give a range, the chosen game
value is stated and the choice justified. Scan kinds per spec PART 2 §9.1:
`staring` (fixed phased faces), `rotating` (mechanical, once per period),
`sector` (electronically revisited wedge about a boresight).

## Assignments

| Game radar | Real-system basis | Kind | Period | Beam | Sector | Band | Notes |
|---|---|---|---|---|---|---|---|
| Player station acquisition (`radar_player_NN`) | 91N6E "Big Bird" acquisition radar of the S-300/400 battery — rotating S-band panel, ~5–6 rpm | rotating | **12.0 s** | 2.0° | 360° | **S** | The battery's search picture. 12 s = low end of 5 rpm; keeps the player picture playable while honestly stale. |
| Player station engagement (NEW object, Task 6 illuminator) | 30N6E "Flap Lid" / 92N6E "Grave Stone" X-band engagement radar — electronically scanned wedge, mechanically slewable mount | sector | 2.0 s | 2.0° | **60°** | **X** | Slews to the engaged threat bearing at launch (the crew points the FCR). SARH/TVM rounds (48N6-class) need it ALIVE and ON-SECTOR. |
| Ship SPY-1 (fleet AAW) | AN/SPY-1D: four fixed passive phased-array faces, continuous hemispheric coverage | **staring** | — | — | 360° | S | The legacy always-painting behavior is CORRECT for this system — validated, not changed. |
| Buk 9S36 (TEL FCR) | 9S36 X-band engagement radar of Buk-M2, sector coverage from the TELAR mast | sector | 2.0 s | 2.0° | **90°** | X | Boresight slews to the TEL's engaged target; carried on relocation. |
| Pantsir acquisition | SOTS/2RL80-class rotating S-band target-acquisition radar on the mount | rotating | **2.0 s** | 4.0° | 360° | S | Fast rotator — point defense needs a fresh close picture. Tracking channel (1RS2-1, Ku) is the ENGAGEMENT path and stares while engaging (not modeled as a search radar). |
| AWACS rotodome | E-3/A-50 class surveillance radar, 6 rpm rotodome | rotating | **10.0 s** | 1.5° | 360° | S | The classic 10 s revisit. |
| Fighter nose radar | modern fighter AESA (APG-81 / N036 class): fixed nose array, ±60° field of regard | sector | 2.0 s | 3.0° | **120°** | X | Boresight = the fighter's live heading (body-fixed callable). A fighter cannot search behind itself — evasion geometry now has teeth. |
| Enemy ground EW radars (`enemy_radar_NN`) | P-18 / Nebo-class early-warning rotators | rotating | **10.0 s** | 2.0° | 360° | S | (VHF in reality; S chosen as the game's coarse band bucket — rain-hardened either way, which is the property that matters for W-P10.) |
| CBR counter-battery | AN/TPQ-53 class: electronically scanned, typically emplaced staring at a 90° threat sector | sector | 1.0 s | 2.0° | **90°** | S | Boresight fixed at the enemy arc at emplacement. (TPQ-53 is S-band.) |
| Recon-drone SIGINT pod / self-deafen emitters (`sim/recon.py`) | jam/beacon emitters, not search radars | staring | — | — | 360° | X | They exist to BE heard (ELINT geometry); staring keeps ELINT behavior identical. |
| Enemy ship radars (`sim/enemy_ships.py`) | destroyer multifunction arrays (Aegis-like on the AAW ships) | staring | — | — | 360° | S | Same SPY-class justification as the player fleet. |
| Oniks/Zircon terminal seeker | active radar seeker in the nose | (gimbal cone, not a ScanDef) | — | — | ±32°/±30° | **Ku** | `WeaponDef.seeker_band` (Task 5); rain attenuation will bite hardest here — correct physics ordering (Ka > Ku > X > C > S). |
| SAM terminal seekers (40N6, SM-6 ARH; 48N6, SM-2, 9M317 SARH) | ARH: own Ku/X seeker; SARH: reflected illumination from the FCR | (cone) | — | — | per SamDef | X | ARH self-illuminates; SARH dies with its illuminator or off-sector slew. |

## Phase offsets

Multi-radar sets (player stations i = 0..n-1, enemy EW radars) get
`phase0_s = i * period_s / n` — deterministic stagger, no RNG, and honest:
crews do not synchronize rotations.

## Modeling decisions (locked)

1. **`detects()` stays instantaneous.** Scan gating lives ONLY in the paint
   layer (`painted` / `next_paint_t` / `RadarNetwork.paint_state`), so the
   legacy `radar_model="functional"` path is byte-identical by construction.
2. **Tracking channels stare.** Once a fire-control engagement is running,
   the tracking channel is locked to the target (that is what an FCR does);
   scan gating applies to SEARCH and to which targets can be ACQUIRED, plus
   the SARH on-sector requirement.
3. **Sector revisit is a tick schedule, not a sweep.** Electronically
   scanned wedges revisit every `period_s` uniformly — beam scheduling
   inside the wedge is below the model's resolution (and below gameplay
   relevance at 120 Hz).
4. **Bands are coarse buckets** (S/C/X/Ku/Ka) chosen for the P.838 rain
   ladder, not emitter-accurate frequencies. The ordering property
   (higher band = more rain loss) is what the physics consumes.
