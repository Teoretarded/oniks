# MANPADS reference — walk-mode shoulder weapons (2026-07-16)

Research for the cinematic-mode F1 weapons rig: four real man-portable
SAM systems, their launch sequences, guidance physics and airframe
limits. Sim values live in `sim/manpads.py`; entries marked `~` are best
estimates from open sources (same convention as the S-300 research doc:
one table, a better number is a one-line edit).

Hit/miss is NEVER a dice roll ([[physics-not-dice]]): the missile flies
proportional navigation against the real target kinematics, the fins can
only bend the trajectory as hard as dynamic pressure and the structural
limit allow, and the fuse fires only when the miss distance says so.

## Sources

- Igla / Igla-S: [Wikipedia 9K38 Igla](https://en.wikipedia.org/wiki/9K38_Igla),
  [missilery.info 9M342](https://en.missilery.info/missile/igla-c/9m342),
  [weaponsystems.net 9K338](https://weaponsystems.net/system/771-9K338+Igla-S),
  [CIA Abbottabad tech sheet](https://www.cia.gov/library/abbottabad-compound/65/65B127CBF02A4667D8A8A229D6A5E87BIGLA.pdf)
- Stinger: [designation-systems.net FIM-92](https://www.designation-systems.net/dusrm/m-92.html),
  [Wikipedia FIM-92](https://en.wikipedia.org/wiki/FIM-92_Stinger),
  [FM 44-18-1 Ch.1 system description](https://www.globalsecurity.org/military/library/policy/army/fm/44-18-1/Ch1.htm)
- Starstreak: [Wikipedia](https://en.wikipedia.org/wiki/Starstreak),
  [army-technology.com](https://www.army-technology.com/projects/starstreak/),
  [Think Defence HVM doc](https://www.thinkdefence.co.uk/docs/starstreak-high-velocity-missile/)
- Piorun: [Wikipedia Piorun](https://en.wikipedia.org/wiki/Piorun_(missile)),
  [MESKO product page](https://www.mesko.com.pl/en/product/piorun-manpads),
  [armyrecognition Piorun GROM-M](https://www.armyrecognition.com/military-products/army/air-defense-systems/man-portable-air-defense-systems/piorun-grom-m-manpads)

## Reference photos (for the models — verified Commons files)

- Igla family:
  [9K38 Igla launch tubes](https://commons.wikimedia.org/wiki/File:9K38_Igla_launch_tubes.jpg),
  [SA-18 missile + launcher side-by-side](https://commons.wikimedia.org/wiki/File:SA-18_misil_y_lanzador.jpg),
  [SA-16/SA-18 missiles and launchers](https://commons.wikimedia.org/wiki/File:SA-16_and_SA-18_missiles_and_launchers.jpg),
  [Igla on Dzhigit support unit](https://commons.wikimedia.org/wiki/File:Dzhighit_with_Igla_MANPADS.jpg)
- Stinger:
  [FIM-92 round in profile](https://commons.wikimedia.org/wiki/File:FIM-92_Stinger_round.png),
  [missile in flight configuration (fins out)](https://commons.wikimedia.org/wiki/File:Stinger_missile_in_flight_configuration.png),
  [Redeye vs Stinger dimensioned comparison](https://commons.wikimedia.org/wiki/File:Redeye_and_Stinger_weapon_comparisons_with_dimensions.png),
  [USMC launcher with gripstock/IFF](https://commons.wikimedia.org/wiki/File:FIM-92_Stinger_USMC.JPG),
  [launcher with IFF at proving ground](https://commons.wikimedia.org/wiki/File:Stinger_missile_launcher_with_IFF_device_at_a_proving_ground_(in_colour).jpg)
- Starstreak: British Army page photos
  (https://www.army.mod.uk/learn-and-explore/equipment/artillery-and-air-defence/starstreak-high-velocity-missile/),
  Think Defence photo set (aiming unit clipped to canister).

Distinctive silhouettes (from the photos above):

- **Igla-S launcher**: thin olive-drab tube ~1.7 m, flared muzzle,
  conical nose cap; pistol-grip trigger unit hangs under the tube aft of
  center; sausage-shaped ground power supply (battery) clipped under the
  forward tube, slanted down-forward. Missile: needle "spike" standoff
  probe on a fine tripod ahead of the seeker ball (the *igla* = needle),
  one pair of steering canards + fixed strakes on the nose section, four
  swept clipped-delta tail fins that fold in the tube.
- **Stinger launcher**: fatter olive/tan fiberglass tube with a bulged
  bell muzzle and a dark conical breech cover; boxy gripstock with pistol
  grip under the rear tube; fold-down open sight frame on the left; the
  IFF antenna is a distinctive flat fold-down GRID slab under the muzzle
  half; BCU (battery coolant unit) cylinder sticks down-forward out of
  the gripstock. Missile: near-hemispherical seeker dome behind a short
  conical tip, 2 control canards + 2 fixed at the nose, 4 folding tail
  fins, body a clean 70 mm cylinder.
- **Starstreak**: much fatter dark-green canister (missile is 130 mm),
  blunt front cap, rounded rear venturi; the AIMING UNIT is a separate
  grey box with a monocular sight that clips onto the canister side
  (shoulder mode) — no pistol gripstock on the tube itself. Missile: a
  pointed two-stage stack; the nose third is three tungsten DARTS in a
  triangular cluster around the second-stage motor; each dart is a long
  thin finned needle (~0.45 m, ~22 mm) with tiny canards.
- **Piorun**: Grom/Igla lineage — visually an Igla-pattern thin tube with
  a squarer grip unit and a modern rectangular sight bracket over the
  tube; missile is Igla-like (needle probe, canards, folding fins).

## Weapon table (sim values)

| Param | Igla-S 9M342 | Stinger FIM-92 RMP | Piorun | Starstreak HVM |
|---|---|---|---|---|
| Nation / year | RU 2004 | US 1987 | PL 2019 | UK 1997 |
| Missile length m | 1.635 | 1.52 | 1.596 | 1.40 (stack) |
| Diameter mm | 72 | 70 | 72 | 130 (2nd stage) |
| Launch mass kg | 11.7 | 10.1 | 10.5 | ~14 (stack) |
| Warhead kg | 2.5 frag+HE | 3.0 blast-frag | 1.82 frag | 3×0.9 delayed HE dart |
| Fuse | contact+graze, laser prox ~1.5 m | impact + time-delay (prox on J) ~2 m | prox ~1.5 m | delayed impact only |
| Eject exit m/s | ~28 | ~28 | ~28 | in-tube 1st stage, ~40 at 2nd light |
| Motor light | ~5.5 m out | ~9 m coast | ~5.5 m | 4 m out |
| Boost | ~2.0 s @ ~29 g | 1.9 s @ ~38 g | ~2.0 s @ ~32 g | ~1.4 s @ ~80 g `~` |
| Sustain | ~5.5 s @ ~2.5 g `~` | ~6 s @ ~1.5 g `~` | ~5.5 s @ ~2.8 g `~` | none (darts coast) |
| Peak speed m/s | ~600 | ~750 (M2.2+) | 660 | ~1190 (M3.5) |
| Range km | 6.0 | 4.8 | 6.5 | 7.0 |
| Ceiling km | 3.5 | 3.8 | 4.0 | 5.0 `~` |
| Self-destruct s | ~15 | 17±2 | ~14 | dart ~10 after sep `~` |
| Seeker | 2-band IR (InSb MWIR cooled + PbS SWIR) | IR/UV rosette scan | cooled IR, IRCCM | laser beam riding (SACLOS matrix) |
| Lock FOV half-angle | ~2° | ~2.25° | ~2° | n/a (beam) |
| Gimbal limit | ~40° | ~40° (two-axis, hemispheric FOR) `~` | ~40° | n/a |
| Seeker track rate | ~12°/s `~` | ~20°/s `~` (tracks >8 g targets) | ~15°/s `~` | operator slew |
| Guidance | PN (digital) | PN + target-adaptive bias | PN | beam riding, 3 darts in formation |
| Struct. g-limit | 16 `~` (10-16 in open lit) | 20 `~` (13-22 debated) | 18 `~` | dart 20 `~` (9 g target at 7 km) |
| Max trim AoA | ~18° `~` | ~20° `~` | ~18° `~` | dart ~10° `~` |
| Roll (airframe) | 900-1200 rpm, 1 canard pair @ ~15 Hz | rolling airframe, rosette | rolling | darts spin-stabilised `~` |

Notes:
- Boost accelerations derived from published burnout speeds and times
  (e.g. Stinger "Mach 2.2 within 2 seconds" ⇒ ~(730−28)/1.9 ≈ 370 m/s²).
  Sustain figures hold cruise speed against drag (see Cd model) out to
  the published range — tuned in tests, marked `~`.
- The MANPADS corkscrew: single-channel rolling-airframe control makes
  the smoke trail visibly helical. Cosmetic helix is applied to the trail
  EMISSION only, never to the guidance state.
- Starstreak is the ground-attack-honest choice: beam riding will steer
  into whatever the operator holds the aim on (used against ground
  targets in Ukraine). IR seekers may also lock sun-heated/hot ground
  spots at reduced range — both documented MANPADS behaviours.

## Physics model (sim/manpads.py)

- ISA-like density `rho(h) = 1.225·exp(−h/8500)`.
- Drag `D = ½ρv²·Cd(M)·S`, `S = πd²/4`; Cd(M): subsonic 0.30, transonic
  peak 0.75 at M1.05, supersonic decay to 0.38 by M2.5 (slender
  finned-body curve, same shape family as sim/aero.py).
- Thrust phases: EJECT (tube exit velocity, unlit), BOOST (constant
  thrust), SUSTAIN (constant lower thrust), COAST. Starstreak: BOOST then
  dart separation event (mass, diameter, Cd swap to dart values ×3
  bodies flying formation as one guided entity + two cosmetic wingmen).
- Guidance: true PN, `a_cmd = N·Vc·dLOS/dt` (N=3.7) computed from real
  relative kinematics, no target-state cheating beyond what the seeker
  can see. Achievable lateral acceleration is
  `a_max = min(g_struct·9.81, q·S·CNα·α_max/m)` — at low q (just off the
  tube) the fins CANNOT turn the missile no matter the command, exactly
  the real fin-authority limit. Igla-family gets the documented
  gas-piston assist: a small fixed turn authority during the first 0.4 s.
- Seeker state machine: CAGED → TONE (target inside acquisition cone and
  range) → LOCK (uncaged, gimbal follows LOS at ≤ track-rate) → LOST
  (gimbal limit exceeded, LOS rate > track rate, or occluded by terrain).
  After LOST the missile flies ballistic (no reacquire — honest for this
  generation).
- Fuse: contact when miss ≤ body radius + target radius; proximity when
  closest approach ≤ prox radius (computed by segment-point distance per
  step, no frame quantisation miss); self-destruct timer; ground impact
  when the trajectory crosses the DTM.
