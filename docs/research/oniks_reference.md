# P-800 Oniks / Yakhont (SS-N-26 Strobile) — Visual & Technical Reference
### For 3D model rebuild + flight-sim implementation
Compiled 2026-06-11. All numbers cited inline. Local reference images downloaded to
`C:\Users\teoti\AppData\Local\Temp\oniks_research\img\` (sources given per image).

---

## 1. GEOMETRY (for the modeler)

### 1.1 Master dimensions
| Item | Value | Source |
|---|---|---|
| Length, ship/ground round | **8.0 m** (ruwiki) / **8.6 m** (CSIS) / **8.9 m** (en.wiki — this figure matches the TPK canister, i.e. round incl. booster + canister clearances) | https://ru.ruwiki.ru/wiki/Оникс_(противокорабельная_ракета) ; https://missilethreat.csis.org/missile/ss-n-26/ ; https://en.wikipedia.org/wiki/P-800_Oniks |
| Length, air-launched version | 6.1 m (no big booster) | https://en.missilery.info/missile/jakhont |
| Body diameter | **0.67 m** (CSIS, armyrecognition) — 0.7 m (en.wiki) | https://missilethreat.csis.org/missile/ss-n-26/ |
| Wingspan (deployed) | **1.70 m** | https://en.wikipedia.org/wiki/P-800_Oniks |
| Launch mass | 3,000 kg (3,100 kg per Commons infobox); **3,900 kg in canister** | https://en.missilery.info/missile/jakhont |
| Transport-launch canister (TPK) | **8.9–9.0 m long × 0.71–0.72 m diameter**, sealed, maintenance-free | https://ru.ruwiki.ru/wiki/Оникс_(противокорабельная_ракета) ; https://thaimilitaryandasianregion.wordpress.com/2017/01/29/bastion-p-k-300p-costal-defense-missile-system/ |

For the game model use: **body Ø 0.67 m, round length ~8.6–8.9 m, span 1.7 m** → fineness ratio ≈ 12–13:1 (a very slender, clean tube).

### 1.2 Nose: annular intake + central cone (THE signature feature)
Russian sources describe it as a "nose axisymmetric air intake with a central cone"; the cone houses "control system units, the homing radar antenna and the warhead" (https://en.missilery.info/missile/jakhont ; https://flot3000.com/ru/file/1899).

What I see on photographs of real display rounds (downloaded & inspected):
- **`img/yakhont_armia2018.jpg`** — 3M55 at Armia-2018, Almaz-Antey grounds (https://commons.wikimedia.org/wiki/File:3M55_Yakhont_Onyx_SS-N-26_Armia_2018.jpg). Front-quarter view. The intake lip is a thin, sharp-edged perfect circle, slightly smaller than body diameter. From inside it a **sharp, needle-pointed cone protrudes well ahead of the lip plane** — the visible cone tip sticks out roughly **0.6–0.8 lip-diameters** in front of the lip. The annulus between cone and lip reads as a **deep, black shadowed ring** (you can see perhaps 0.5 m into the duct before the cone base fills it). On this round the cone is **dark grey / near-black** (dielectric radome over the seeker antenna), contrasting with the light-grey body.
- **`img/yakhont_army2022.jpg`** — 3M55 at ARMY-2022 (https://commons.wikimedia.org/wiki/File:3M55_Yakhont_Onyx_SS-N-26_at_ARMY-2022.JPG). Same geometry; on this round the cone is painted **the same grey-green as the body**. Cone half-angle looks ~20–25° at the visible tip, steepening near its base.
- **`img/oniks_sketch.png`** — scaled line drawing with 1 m bar (https://commons.wikimedia.org/wiki/File:P-800_oniks_sketch.svg). Measured against the bar: cone tip protrudes **≈ 0.45 m** ahead of the lip; **intake lip outer Ø ≈ 0.48–0.50 m (~70–75 % of body Ø)**; behind the lip the fuselage swells from lip diameter to the full 0.67 m over an ogive **≈ 1.3–1.5 m long** — a soft "shoulder" just aft of the intake ring.

Modeling recipe: sharp cone (tip radius ~near zero), cone base buried inside the duct; lip ring with a knife-edge inner profile; keep a real recess of ≥ 0.4 m depth between lip and cone base so the dark annulus reads correctly at glancing angles.

### 1.3 Mid-body
- Clean constant-diameter cylinder; the whole missile from intake to nozzle is "an integrated powerplant combined with the airframe", fuel filling internal volumes (https://flot3000.com/ru/file/1899). Almost no external clutter.
- Both display photos and the line drawing show **two slim, parallel cable raceways/strakes** running along the fuselage flanks from ≈ 2.0 m to ≈ 4.4 m from the nose (sketch scale) — long thin half-round blisters, the only surface relief on the forward half.
- A small probe/fitting (tiny triangular vane) near the top of the nose section is visible in `yakhont_armia2018.jpg`.
- Flush panel/access lines; faint red stencil markings mid-body on the 2018 round.

### 1.4 Wings (main lifting surfaces)
- **Four clipped-tip delta ("trapezoidal") wings in cruciform** on the rear half of the body — BrahMos (same airframe) is described identically: "four clipped tip delta wings at mid-body, with four small delta control fins at the rear" (https://en.wikipedia.org/wiki/BrahMos).
- From the scaled sketch: root chord **≈ 2.2–2.4 m** (a quarter of the missile's length!), leading-edge sweep **≈ 55–65°**, exposed half-span **≈ 0.5 m** per side (total span 1.7 m incl. 0.67 m body), clipped tip chord ≈ 1.2–1.3 m. Wing root runs from roughly **55 % to 83 %** of body length.
- **Folding:** "trapezoidal folding wing and plumage… stored in the sealed canister with compactly folded wings and fins"; packing is so dense there is "almost complete absence of gaps between the fuselage … and the inner surface" of the 0.71 m tube (https://en.missilery.info/missile/jakhont ; https://thaimilitaryandasianregion.wordpress.com/2017/01/29/bastion-p-k-300p-costal-defense-missile-system/). The panels fold flat around the body inside the canister and **snap out immediately after canister exit**. Model both states: folded (wrapped, chord-wise hinge at the root) and deployed; show hinge/fold lines at the roots in the deployed state.
- **X vs + :** the four wings are at 90° spacing, with the tail fins in the same planes (in-line). Launch and in-flight footage of Oniks/BrahMos shows the missile cruising with surfaces in an **X (45°) orientation** relative to the ground; the line drawing draws them in "+" merely for drafting convenience. For the sim, fly it in X.

### 1.5 Tail
- **Four small clipped-delta control fins (rudders) at the extreme tail**, in-line with the wings, also folding (same sources). From the sketch: root chord ≈ 0.5–0.6 m, span noticeably smaller than the wings (~1.2–1.3 m total). They sit on the slightly boat-tailed last ~0.5 m of the body.
- The tail truncates in a single circular **ramjet nozzle**; on display rounds it is closed by a **bright red protective cap** (visible in both Commons photos).

### 1.6 Booster section — there is none externally
The solid booster sits **inside the ramjet combustion chamber** "on the 'matryoshka' principle"; after burnout it is "ejected from the marching engine by the raging air flow" through the nozzle (https://en.missilery.info/missile/jakhont). **Externally the missile looks identical before and after booster separation** — no strap-ons, no skirt. For the sim, separation = a dark cylindrical slug + nozzle insert tumbling out of the tailpipe, plus flame signature change.

### 1.7 Colors & markings (real examples)
- Armia-2018 round: overall **light gull grey**, semi-gloss; **near-black cone**; red tail cap; faint red stencils (`img/yakhont_armia2018.jpg`).
- ARMY-2022 round: overall **grey-green (greenish light grey)**, cone in body color, red tail cap (`img/yakhont_army2022.jpg`).
- Export/parade BrahMos rounds (same airframe) are typically **white/cream**; white is appropriate for an export "Yakhont" skin. Radome/cone may be rendered dark grey (dielectric) for the Russian look.
- Canisters: grey/blue-grey smooth tubes with rounded end caps (`img/bastion_prelaunch.jpg`).

---

## 2. LAUNCH SEQUENCE — Bastion-P (K-300P), TEL K-340P

### 2.1 The vehicle (MZKT-7930 chassis)
Photos inspected:
- **`img/bastion_tel.jpg`** (https://commons.wikimedia.org/wiki/File:K-300P_Bastion-P.jpg): travel configuration. **4 axles / 8 large wheels** (two steering axles at the cab, a gap, two rear axles). Dark olive-green overall. Two-man-wide forward cab with flat, slightly raked windshield panels and roof-mounted light/sensor mast; behind it a long **slab-sided box superstructure with a shallow ridge ("hip-roof") cover** running the vehicle's length — the two canisters lie horizontally inside.
- **`img/bastion_prelaunch.jpg`** (mil.ru photo, https://commons.wikimedia.org/wiki/File:Комплекс_Бастион_перед_пуском_ракет.jpg): firing configuration in the field. **Both canisters erected to vertical (~90°) at the rear third of the vehicle**, standing side-by-side as two plain grey tubes with rounded caps, the erecting mast/hydraulic frame visible between them; roof covers opened; vehicle leveled on jacks.
- Specs: length 12.7 m, width 3.0 m, height 3.29 m, YaMZ-846 diesel 500 hp, payload 24 t, crew 3 (https://thaimilitaryandasianregion.wordpress.com/2017/01/29/bastion-p-k-300p-costal-defense-missile-system/ ; https://en.wikipedia.org/wiki/K-300P_Bastion-P).

### 2.2 Elevation angle
The missile/TPK family supports launch angles **15°–90°** (ships use inclined or vertical); **Bastion-P fires near-vertically (~90°)** — confirmed by the erected-canister photo above and by "fired vertically from the launchers" (https://en.wikipedia.org/wiki/K-300P_Bastion-P ; https://thaimilitaryandasianregion.wordpress.com/2017/01/29/bastion-p-k-300p-costal-defense-missile-system/).

### 2.3 Hot ride-out from a closed-bottom canister (not a true cold/mortar eject)
- Russian sources: launch is "from a closed-bottom launch container", and the launch scheme "does not require the organization of jet stream gas removal" (no flame trench / efflux ducting needed) (https://thaimilitaryandasianregion.wordpress.com ; https://en.missilery.info/missile/jakhont). The **solid booster ignites inside the sealed tube** and the missile rides its own booster out.
- Visual confirmation, frame inspected: **`img/brahmos_launch_imphal.jpg`** (identical airframe & UKSK-type vertical canister, https://commons.wikimedia.org/wiki/File:Brahmos_being_launched_from_Imphal_Y-12706.jpg): at the instant of exit the missile is only ~1.5 lengths out of the hatch and **orange booster flame is already blasting laterally out of the canister mouth around the missile's base** — ignition clearly happened in the tube.
- **`img/brahmos_launch_chennai.jpg`** (https://commons.wikimedia.org/wiki/File:BrahMos-ER_fired_from_INS_Chennai_on_5_March_2022_-_1.jpg): ~1 second later the missile is 80–100 m up on a brilliant flame, atop a **dense, vertical white-grey smoke column 3–5 m wide** rising straight from the launcher. Russian MoD footage of Crimean Bastion launches shows the same picture from the land TEL (three missiles in quick succession; https://www.twz.com/44891/russia-claims-it-launched-bastion-p-anti-ship-missiles-against-ground-targets-in-ukraine).
- Note: some tertiary sources (e.g. Grokipedia) call it "vertical cold-launch"; the photographic record and the Russian closed-bottom-TPK description both support **in-tube booster ignition**. Sim it as: canister cap blown → flame gush at muzzle → missile exits already at full booster thrust (no separate gas-eject coast phase) → fins/rudders snap open within the first ~0.5 s → vertical climb a few hundred metres → pitch-over toward target azimuth while the booster finishes.

### 2.4 Timing numbers
| Event | Value | Source |
|---|---|---|
| March → ready to fire | ≤ 5 min | https://en.wikipedia.org/wiki/K-300P_Bastion-P |
| Interval between the 2 canisters | **2–5 s** | https://en.wikipedia.org/wiki/K-300P_Bastion-P ; https://en.missilery.info/missile/jakhont |
| Booster burn | "a few seconds", accelerates the round to **~Mach 2**, then is shut down and **ejected out the nozzle by ram air** | https://en.missilery.info/missile/jakhont ; https://flot3000.com/ru/file/1899 |
| Standby on station | 3–5 days (30 with support vehicle) | https://en.wikipedia.org/wiki/K-300P_Bastion-P |
| Battery | 4 TELs × 2 missiles + 1–2 C2 vehicles (KamAZ-43101) + loaders | https://en.wikipedia.org/wiki/K-300P_Bastion-P |

---

## 3. FLIGHT PROFILE (sim numbers)

| Parameter | Value | Source |
|---|---|---|
| Hi-lo climb / cruise altitude | **14,000–15,000 m** | https://en.missilery.info/missile/jakhont ; https://en.wikipedia.org/wiki/P-800_Oniks |
| Hi cruise speed | **750 m/s ≈ Mach 2.5–2.6** (Mach 2.9 max claimed) | https://ru.ruwiki.ru/wiki/Оникс_(противокорабельная_ракета) ; https://en.wikipedia.org/wiki/P-800_Oniks |
| Lo-lo speed | **680 m/s ≈ Mach 2.0** at low altitude | https://missilethreat.csis.org/missile/ss-n-26/ |
| Terminal sea-skim | **10–15 m** (sources give 5–15 m on the final run) | https://missilethreat.csis.org/missile/ss-n-26/ ; https://en.missilery.info/missile/jakhont |
| Range hi-lo (export Yakhont) | **300 km** | https://missilethreat.csis.org/missile/ss-n-26/ |
| Range lo-lo (export) | **120 km** | https://missilethreat.csis.org/missile/ss-n-26/ |
| Range, domestic Oniks | up to **600 km**; Oniks-M **800 km** | https://en.wikipedia.org/wiki/P-800_Oniks |
| Seeker first acquisition | active-passive radar seeker locks a **cruiser-class target at up to 75 km** (50 km per Wikipedia/ruwiki) | https://en.missilery.info/missile/jakhont ; https://en.wikipedia.org/wiki/P-800_Oniks |
| Mid-course logic | climb, INS cruise high; brief seeker fix at ~50–75 km; **shuts seeker off and dives below the radio horizon**; re-activates the seeker for the terminal run at skim height | https://en.missilery.info/missile/jakhont |
| Terminal behavior | "erratic terminal maneuvers" / "complex maneuvers in its terminal phase" to defeat CIWS — model as low-g weave at Mach 2, 10–15 m AGL | https://www.armyrecognition.com/military-products/navy/weapons-systems/missiles/p-800-oniks-3m55-yakhont-ss-n-26-strobile ; https://www.armyrecognition.com/news/navy-news/2025/russia-tests-bastion-coastal-defense-with-onyx-anti-ship-missiles-during-zapad-2025-drills-in-the-arctic |
| Booster phase | vertical exit → pitch-over → **~Mach 2 within a few seconds** → booster slug ejected through the nozzle by ram pressure → ramjet (4,000 kgf thrust, T-6 kerosene) lights | https://en.missilery.info/missile/jakhont ; https://en.wikipedia.org/wiki/P-800_Oniks |
| Warhead | 200–250 kg SAP (300 kg domestic) | https://en.wikipedia.org/wiki/P-800_Oniks |
| Guidance | INS mid-course + active/passive radar terminal; fire-and-forget | https://flot3000.com/ru/file/1899 |

Suggested sim event chain (hi-lo): t=0 in-tube ignition → t≈0.4 s muzzle exit + fin deploy → vertical to ~300 m → pitch-over → booster burnout/eject ~t+3–4 s at ~M2 → ramjet climb to 14 km, M2.6 cruise → seeker fix at 75 km → descend below horizon → 10–15 m skim at M2.0 with weave from ~25 km → impact.

---

## 4. TOP 10 VISUAL SIGNATURES (ranked — drives the model rebuild & review)

1. **Annular nose intake with a sharp central cone protruding ~0.45 m ahead of the lip** — the deep black ring of the inlet annulus around a needle cone is the instant identifier; nothing generic has it.
2. **Extremely clean, constant-diameter tube body** (Ø 0.67 m × ~8.6 m, fineness ≈ 12:1) with almost zero external clutter.
3. **Four huge-root-chord clipped-delta wings on the rear half** — root chord ~2.3 m (≈ ¼ of the missile) but only ~0.5 m exposed span each: long, low, knife-like.
4. **Four small in-line clipped-delta rudders at the extreme tail**, same planes as the wings, X-oriented in flight.
5. **Ogive "shoulder" just behind the intake lip** — body swells from ~0.5 m lip diameter to 0.67 m over ~1.4 m.
6. **Single circular ramjet nozzle filling the tail; no external booster at any point** (booster is hidden inside, ejected through the nozzle).
7. **Pair of slim longitudinal cable raceways/strakes** on the forward/mid fuselage flanks (~2.0–4.4 m station).
8. **Contrasting dark dielectric cone** on a light-grey/white body (some rounds body-color), red tail cap on display rounds.
9. **Fold hinges at wing/fin roots** — surfaces fold flat to fit a Ø 0.71 m tube; deployed surfaces show root fold lines.
10. **Launch context**: two plain vertical grey canisters on a dark-green 4-axle (8-wheel) MZKT-7930 TEL with hip-roof cover — and at launch, flame erupting from the canister mouth around the missile.

---

## Modeler's brief
Build a Ø 0.67 m × ~8.6 m semi-gloss light-grey tube with a fineness ratio of about 12:1 and almost nothing on its skin except two slim flank raceways. Spend the polygon budget at the nose: a thin, knife-edged annular intake lip about 70–75 % of body diameter, with a sharp dark cone punching ~0.45 m out of a genuinely recessed (≥ 0.4 m deep) black annulus, then a 1.4 m ogive shoulder up to full diameter. Mount four clipped-delta wings of ~2.3 m root chord but only ~0.5 m exposed span on the rear half (55–83 % of length), and four small in-line clipped-delta rudders at the very tail, all rigged to fold flat for the canister and snap out at launch; fly everything in X orientation. The tail is a single round ramjet nozzle — never model an external booster; separation is just a slug dropped out of the tailpipe. Pair it with a dark-green 4-axle MZKT-7930 TEL whose two grey canisters erect to vertical, and animate launch as in-tube booster ignition: muzzle flame gush, dense white smoke column, vertical ride-out, pitch-over, booster gone within ~4 seconds.
