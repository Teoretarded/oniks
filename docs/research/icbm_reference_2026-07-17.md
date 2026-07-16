# ICBM reference — RS-28 Sarmat & LGM-30G Minuteman III (2026-07-17)

Normative source for the cinematic-mode ICBM feature. Sim constants and
model dimensions derive from THIS file; a better number is a one-line
edit here plus the matching constant. Values marked `~` are best
estimates (public data is fuzzy, especially Sarmat) — same convention as
docs/research/s300_launch_visuals.md.

Why these two: the user asked for "the top ICBM for Russia and the top
ICBM for America". Russia = RS-28 Sarmat (entered service 2023; the
newest, heaviest, longest-ranged ICBM extant). America = LGM-30G
Minuteman III (the ONLY US land-based ICBM in service; LGM-35A Sentinel
is not deployed). They are also perfect visual opposites: solid vs
liquid, hot launch vs cold launch, pencil vs monster, smoke column vs
near-smokeless hypergolic flame.

---

## 1. LGM-30G Minuteman III (USA)

### 1.1 Airframe

| Quantity | Value | Source |
|---|---|---|
| Length | 18.3 m (59.9 ft) | AF fact sheet / Wikipedia |
| Diameter (S1) | 1.68 m (5.5 ft) | Wikipedia |
| Gross mass | 36,030 kg (79,432 lb) | AF fact sheet |
| Range | ~13,000 km | AF fact sheet |
| Terminal speed | ~Mach 23 (~7 km/s) | Wikipedia |
| CEP | ~200 m | Wikipedia (NS50 era) |

Shape: slim three-stage pencil. One visible shoulder taper above S1
(1.68 m -> ~1.33 m); S2/S3 nearly constant diameter; conical RV shroud.
Paint `~`: pale grey/off-white stack, dark raceway stripe, dark
interstage bands (verify against reference photos at modeling time).

### 1.2 Stages (normative sim table)

| Stage | Motor | Gross kg | Propellant kg | Thrust kN | Burn s | Isp vac s |
|---|---|---|---|---|---|---|
| 1 | Thiokol M55A1 | ~23,230 | ~20,780 | 935 max / ~790 avg | ~61 | ~262 |
| 2 | Aerojet SR19-AJ-1 | ~7,270 | ~6,240 | 267.7 | ~65 | ~288 |
| 3 | Aerojet/CSD SR73-AJ-1 | ~3,710 | ~3,310 | 152.0 | ~61 | ~285 |
| PBV+RS | PSRE, Rocketdyne RS-14 | ~1,100 | — | small | restartable | — |

Masses `~` per Fetter, "A Ballistic Missile Primer" (armscontrol.ru);
thrusts per Wikipedia LGM-30 / Minotaur I. Sum ≈ 35.3 t ✓ gross.

Trajectory milestones (Spaceline fact sheet, full-range test): S1 sep
t+60 s at ~24 km alt; S2 sep t+117 s; S3 burnout t+181 s at ~190 km,
~7 km/s. Kwajalein test shots (~6,700 km) fly ~30 min, apogee
~1,100 km.

TVC: S1 four movable nozzles; S2 single fixed nozzle + liquid injection
TVC; S3 fixed nozzle + LITVC. S3 also historically had thrust
termination ports (pre-GEMS range control).

### 1.3 Guidance

NS-50 Missile Guidance Set (replaced NS-20A, completed 2008): gimbaled
inertial platform — NO operational GPS; alignment via stored azimuth,
gyrocompassing. Post-boost: PSRE fine-tunes velocity, dispenses RV(s).
Under New START each missile carries a single W87-0 (300 kt) Mk21 RV.
For the game: inertial Lambert guidance during boost, zero external
sensors — matches [[enemy-ai-no-cheat-pattern]] trivially.

### 1.4 Silo & launch sequence (Launch Facility)

- Launch tube: 12 ft (3.66 m) diameter, 80 ft (24.4 m) deep
  (minutemanmissile.com). Air held at 60 °F.
- Launcher closure door: 110 US tons, 3.5 ft thick, rectangular,
  slides on rails; ballistic gas actuators accelerate it to ~35 mph
  nearly instantly; wedge-shaped leading edge plows debris. When open,
  the tube mouth reads as a clean metal RING.
- Compound: ~1-acre gravel rectangle, security fence, the door + apron,
  a personnel access hatch, HF/UHF antenna bumps, soft-support building
  nothing else. Deceptively mundane — a parking lot with a god inside.
- HOT LAUNCH ("fire in the hole"): S1 ignites INSIDE the tube. The
  annulus between missile and tube vents the efflux around the missile
  body: flame + smoke erupt in a donut AROUND the emerging airframe.
- **The smoke ring**: signature phenomenon (Smithsonian/NBC). The
  pressurized humid silo air + efflux forced through the circular tube
  mouth rolls a PERFECT vortex ring that climbs hundreds of feet. The
  missile "usually doesn't climb past its own ring until several
  seconds into flight"; sometimes it pierces it dead center, more often
  the ring drifts leeward and lingers as a halo. WE MUST MODEL THIS.
- Egress: first motion to clear-of-tube ~1-2 s `~`; immediate roll to
  flight azimuth + pitch-over.

### 1.5 Plume phenomenology (solid, aluminized composite)

- Brilliant white-orange flame, flame length ~1.5-2x body `~`.
- DENSE bright white/pale-tan smoke column the entire S1 burn — the
  classic Vandenberg pillar; column persists minutes and kinks with
  wind shear.
- S2/S3 at altitude: vacuum bloom — plume widens into a translucent
  cone/jellyfish; at night this is the famous glowing halo. Staging
  events leave hanging puffs + a tumbling spent stage (visible glints,
  occasional propellant wisps).
- Reentry (full-range): RV streak at ~Mach 23 — thin incandescent
  line, no smoke. In-map GEMS shot arrives slower (~1-2 km/s) — orange
  glow + sonic crack, no long plasma tail.

### 1.6 Visual signature checklist (model + fx MUST hit these)

1. Pencil proportions: 18.3 m x 1.68 m = 10.9:1 slenderness.
2. Single shoulder taper above S1; conical shroud tip.
3. Rectangular 110 t closure door OPEN on rails beside a clean round
   tube mouth in a concrete apron.
4. Fire-in-the-hole donut: efflux erupts AROUND the missile at tube
   exit, not from a clean pad.
5. The smoke ring — rolls up, climbs, drifts; missile pierces or
   bypasses it.
6. Relentless straight-line acceleration (0.9 -> ~8 g through S1); no
   S-300-style lazy tilt — it is GONE upward.
7. Dense white pillar to ~25 km, then almost nothing (upper stages
   near-smokeless at altitude, bloom instead).
8. Staging puffs at t+61 s and t+126 s `~` with tumbling castoffs.
9. Gravel LF compound: fence, apron, hatch, antennas — banal and flat.
10. Scale honesty: silo mouth 3.66 m vs missile 1.68 m — the tube
    swallows the airframe with a wide annulus.

### 1.7 Named reference photos (verify models side-by-side)

- Smithsonian "Minuteman, the Missile that Blows Smoke Rings" — GT
  launch, ring + pillar: smithsonianmag.com/air-space-magazine/minuteman-missile-blows-smoke-rings-180958003/
- NBC "Air Force Minuteman Missile Launch Blows Perfect Smoke Ring"
  (Feb 2015 GT launch photo): nbcnews.com/science/space/air-force-minuteman-missile-launch-blows-perfect-smoke-ring-n328861
- minutemanmissile.com/launcherclosuredoor.html + /launchtube.html —
  Delta-09 door, rails, tube interior.
- Wikipedia LGM-30 article images: silo emergence frame, LF diagram,
  stage cutaway.
- Vandenberg SFB test-launch article imagery (night halo):
  vandenberg.spaceforce.mil.

---

## 2. RS-28 Sarmat / 15A28, NATO SS-X-30 "Satan II" (Russia)

### 2.1 Airframe

| Quantity | Value | Source |
|---|---|---|
| Length | 35.3 m | Wikipedia/CSIS |
| Diameter | 3.0 m | Wikipedia/CSIS |
| Launch mass | 208,100 kg | Wikipedia |
| Throw weight | ~10,000 kg | Wikipedia |
| Range | ~18,000 km | Wikipedia |
| Payload | 10x ~750 kt MIRV, or up to 15-16 light RVs, or 3 Avangard HGV | Wikipedia |
| Service | Sept 2023, Strategic Rocket Forces (Uzhur) | Wikipedia |

Shape: enormous blunt cylinder — 11.8:1 but reads FAT because of the
3 m diameter; short rounded ogive fairing, no visible taper (stages are
common-diameter). Launched from/with a TPK (transport-launch canister).
Paint `~`: very dark green-black thermal coat, pale nose cap seam
(verify at modeling).

### 2.2 Stages (estimates from R-36M2 Voevoda heritage — Sarmat data is closed)

Three-stage liquid, N2O4/UDMH (hypergolic, storable).

| Stage | Engine | Propellant kg | Thrust | Burn s |
|---|---|---|---|---|
| 1 | PDU-99 (4-chamber, R-36M2 RD-274 class) | ~150,000 | ~4,600 kN SL / ~5,000 vac (R-36M2: 468.6 t SL / 504.9 t vac, russianspaceweb) | ~95 `~` |
| 2 | RD-0255 class, main + verniers | ~37,500 | ~760 kN vac `~` | ~165 `~` |
| 3/PBV | restartable bus | ~2,000 `~` | small | long, MIRV dispense |

Liquid engines throttle and SHUT DOWN on command — energy management
for short flights is engine cutoff + vernier trim (no GEMS contortions
needed, unlike solids).

### 2.3 Guidance

Inertial with astro-correction + GLONASS aiding (reported `~`) —
Russian ICBM tradition is astro-inertial. Boost is fully autonomous
after key-turn; same no-external-sensor property as MM III.

### 2.4 Silo & cold-launch sequence (15P718M)

- Converted R-36M silos (Uzhur, Dombarovsky): tube ~6 m class `~`,
  depth ~39 m `~`; MASSIVE circular/rounded-square sliding armored lid
  (hundreds of tonnes) on rails over a broad concrete apron; perimeter
  security ring. Reads as a low concrete mesa with a monstrous manhole.
- COLD LAUNCH (mortar start): a powder pressure accumulator (PAD)
  inside the TPK ejects the FULL 208 t missile out of the canister —
  ejection tests 2017+ preceded flight (Plesetsk, April 20 2022 first
  full flight, hit Kura/Kamchatka).
- Sequence per R-36M heritage + 2022 MoD footage: lid slides open →
  dull THUMP, huge dark grey-brown gas puff vents from the tube mouth →
  the missile rises slowly, majestically clear of the silo (eject
  ~20-30 m `~`, exit speed ~20-25 m/s `~`) → visible hang moment,
  gas-generator tail-off wisps → lateral solid charges kick the spent
  pressure pallet AWAY from the airframe → S1 hypergolic light-off:
  hard orange flash, near-instant full thrust (~2.2 g at 208 t) →
  climbs on a comparatively CLEAN flame.

### 2.5 Plume phenomenology (hypergolic N2O4/UDMH)

- Ignition transient: orange-red flash with reddish-brown NTO tint.
- Steady flame: bright orange-yellow, translucent; FAR less smoke than
  a solid — a shimmering column of heat + thin brown-grey haze, not the
  Minuteman's white pillar. The mortar puff at the silo is the dirtiest
  moment of the whole launch.
- Four distinct chamber plumes merge within ~1 body diameter `~`.
- At altitude: same vacuum bloom physics; staging = brief transparent
  flash + tumbling 3 m stage (huge castoff — reads like a falling
  grain silo).

### 2.6 Visual signature checklist

1. FAT: 3 m x 35.3 m — next to a Minuteman it is a freight train vs a
   pencil (2x diameter, 2x length, 5.8x mass).
2. Blunt rounded nose fairing, common-diameter stack, no shoulder.
3. Cold mortar eject: missile CLIMBS OUT of the ground unlit — the
   single most alien-looking event we can render.
4. The hang: a 208 t object coasting upward, engine dark, for ~1-2 s.
5. Pressure-pallet kick: a burning/smoking slug thrown sideways off
   the tail just before light-off.
6. Hypergolic light-off flash: orange, violent, from DARK to full
   flame in ~0.2 s.
7. Clean-burning climb: heat shimmer + thin haze, not a smoke pillar —
   the column at the silo is mortar gas + dust, and it stops there.
8. Huge circular silo lid slid open on rails; broad flat apron.
9. Slow initial climb (~2.2 g total, ~1.2 g net) — it accelerates like
   a heavy freight elevator, then builds.
10. TPK rim visible in the tube mouth (the missile lives in a canister,
    not bare in the silo).

### 2.7 Named reference photos

- Wikipedia RS-28 Sarmat page lead image — April 2022 Plesetsk launch
  (missile clear of silo, mortar cloud below).
- overtdefense.com 2022-04-21 first-test article stills (MoD footage
  frames: lid, eject, light-off).
- Russian MoD April 2022 launch video (YouTube mirrors) — the
  authoritative motion reference for eject timing.
- weaponsparade.com R-36M2 gallery — silo lid, TPK loading (Sarmat's
  silo is a converted R-36 site; closest open imagery).

---

## 3. Hitting a target 3-15 km away with a full ICBM burn (the map problem)

A full-range ICBM burn yields ~7 km/s — orders of magnitude beyond a
16 km map shot. Real, documented solutions, no dice and no fudge:

- **Solids (Minuteman III): Lambert guidance + GEMS** — Generalized
  Energy Management Steering. Solid stages can't shut down, so the
  autopilot flies a deliberately fuel-inefficient WEAVING/HELICAL
  velocity path whose LENGTH equals the remaining velocity capability
  while the net velocity vector integrates to exactly the Lambert
  requirement (US patents 4387865, 10323907; Trident practice). All
  three stages burn to depletion, staging happens on schedule, and the
  net imparted velocity is small: the missile corkscrews/doglegs
  overhead — spectacular AND true.
- **Liquids (Sarmat): early engine cutoff** — command shutdown once
  the Lambert velocity-to-be-gained hits zero, vernier trim, coast.
  For spectacle-parity the game may still fly S1 to depletion on a
  GEMS-like shaped path and cut S2 early `~` (a real short-range
  liquid shot would simply cut off early; both are physical).
- Result: full boost-phase spectacle (all staging events), lofted arc
  apex of a few km to a few tens of km over the valley, RV terminal
  speed ~0.3-2 km/s depending on loft — minutes, not tens of minutes,
  of flight. [[physics-not-dice]]: the trajectory comes from thrust
  integration + Lambert targeting, zero RNG.

## 4. Sources

- en.wikipedia.org/wiki/LGM-30_Minuteman · en.wikipedia.org/wiki/RS-28_Sarmat · en.wikipedia.org/wiki/Minotaur_I · en.wikipedia.org/wiki/R-36_(missile)
- af.mil LGM-30G fact sheet · spaceline.org Minuteman III fact sheet
- minutemanmissile.com /launcherclosuredoor.html /launchtube.html · themilitarystandard.com Minuteman pages · nps.gov Minuteman Missile NHS
- smithsonianmag.com "Minuteman, the Missile that Blows Smoke Rings" · nbcnews.com smoke-ring article · gizmodo.com smoke-ring article
- russianspaceweb.com/r36m2.html (RD-274 thrusts, stage propellant loads) · astronautix.com R-36M2/Minuteman pages (site intermittently down) · globalsecurity.org R-36M2 + RS-28 pages
- missilethreat.csis.org /missile/rs-28-sarmat/ /missile/minuteman-iii/ · armyrecognition.com RS-28 page
- overtdefense.com 2022-04-21 Sarmat first flight · space.com Sarmat first flight · rferl.org + newsweek.com Sarmat test-failure satellite analyses
- Steve Fetter, "A Ballistic Missile Primer" (armscontrol.ru) — MM III stage mass model
- US patents 4,387,865 (solid-propellant steering) & 10,323,907 (velocity-deficit guidance) — GEMS/Lambert energy management
