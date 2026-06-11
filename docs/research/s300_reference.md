# S-300 (5P85 TEL + 48N6/5V55) — Visual & Technical Reference for 3D Game Implementation

Research date: 2026-06-11. Compiled for the "oinks PROTO" missile-sim project.
Reference images downloaded to `C:\Users\teoti\AppData\Local\Temp\oniks_research\img\` (described in detail below).

---

## 1. COLD LAUNCH SEQUENCE (the money shot)

### Mechanism
The S-300P family uses a **cold/catapult launch**: a gas generator inside the transport-launch container (TPK) drives a catapult — two gas cylinders with rod-pulls joined under the missile by a base plate/tray — that throws the missile straight up out of the tube **before** the rocket motor lights.
- "The vertical launch technique adopted used a catapult accelerator within the container to pop the missile to an altitude 20 m above the launcher, where the main motor ignited." — FAS / Astronautix (https://nuke.fas.org/guide/russia/airdef/s-300pmu.htm, http://www.astronautix.com/s/s-300.html)
- "For the operation of the ejection device is used gas generator located in the TPC." — Missilery.info S-300PS (https://en.missilery.info/missile/c300ps)
- Russian sources (ru.wikipedia.org/wiki/С-300; pvo.guns.ru/s300p/index_s300pt.htm; library.voenmeh.ru S-300 textbook PDF): the catapult consists of pneumatic cylinders with rods connected at the bottom of the rocket; the container **cover is shot off first** ("отстрел крышки"), then the missile is forcibly catapulted to ~20 m.

### Timeline (best-sourced numbers — use these)
| T (s) | Event |
|---|---|
| -0.1–0 | TPK front cover jettisoned/blown clear; first grey-white gas puff from tube mouth |
| 0.0 | Missile clears tube mouth at **~20 m/s** (back-calculated from 20 m apex: v=√(2g·20)≈20 m/s); **4 tail fins snap open the instant it exits** — "aerodynamic rudders open simultaneously with the missile's exit from the container" (https://en.missilery.info/missile/c300ps) |
| 0–1.5 | Pure ballistic coast upward, visibly decelerating — the "hang." Russian sources: engine start via a **delay unit 1.0–1.5 s after exit from the container, upon reaching nearly zero vertical speed** at ~20 m (ru.wikipedia.org/wiki/С-300; pvo.guns.ru). S-400 Wikipedia cross-ref for same 48N6 family: "at 30 metres downrange rocket motor ignition activates" (https://en.wikipedia.org/wiki/S-400_missile_system). So: **ignition 1–1.5 s after tube exit, at 20–30 m, near apex, near-zero speed** |
| 1.0–1.5 | **IGNITION**: spherical orange-yellow fireball erupts around the lower half of the near-stationary missile, wider than the missile itself; expanding smoke torus/donut at the base; debris (cover fragments, tray) flung outward |
| 1.5–3.5 | **Tip-over**: gas-dynamic rudders (TVC vanes in the motor exhaust) roll the missile to align its plane with the guidance plane and pitch it toward the target per a program loaded before launch (ru.wikipedia / pvo.guns.ru / missilery.info). The smoke column gets a sharp **kink** 30–100 m up where vertical becomes slanted |
| 1.5–13.5 | **Boost: ~12 s burn** — "the 48N6E2 accelerates up to 1,900 m/s in 12 sec" (https://nuke.fas.org/guide/russia/airdef/s-300pmu.htm, https://www.globalsecurity.org/military/world/russia/s-300pmu2.htm; burn duration also given as ~12 s by https://www.ausairpower.net/APA-Grumble-Gargoyle.html). Average accel ≈ 1900/12 ≈ **158 m/s² ≈ 16 g**; family-level claims "up to 100 g (1 km/s²)" exist (https://en.wikipedia.org/wiki/S-300_missile_system) — treat 100 g as marketing/maneuver figure, use ~16–25 g sustained boost with a hotter first second for feel |
| ~13.5+ | Burnout at **~1,900–2,100 m/s (Mach 6)**; missile coasts, maneuver limit ~25 g (https://weaponsystems.net/system/1417->>48N6) |

Ripple fire: **3–5 s interval between missiles** from one TEL (https://truck-encyclopedia.com/coldwar/ussr/5P85.php, ru.wikipedia).

### What it looks like on camera (from launch photos viewed)
- **File:UA S-300 firing.jpg** (https://commons.wikimedia.org/wiki/File:UA_S-300_firing.jpg) — ignition instant: dark slender missile, vertical, nose-up, ~30–50 m up; lower half swallowed by a fireball 3–4 missile-diameters wide; 6–8 brown debris chunks (cover/tray fragments) scattered mid-air around it; erected grey-green tube pair below; ground dust blasted radially outward and lit orange by the flash.
- **File:Ukrainian s-300 launch.jpg** (https://commons.wikimedia.org/wiki/File:Ukrainian_s-300_launch.jpg) — ~2–3 s after ignition: missile already tilted ~30° off vertical, riding a blinding yellow-white torch ~2 missile-lengths long; dense bright-white smoke column with a grey core; column rises vertically off the launcher then **bends** where tip-over happened; launcher buried in a ground-level white smoke cloud; tiny debris specks still falling.
- Failed-launch footage (engine no-light) shows the other half of the physics: missile pops out, hangs, falls straight back onto the TEL and detonates — "barely managing to take off before plummeting back down" (https://www.globaldefensecorp.com/2024/02/25/russias-s-300-missile-launch-spectacularly-goes-wrong-when-the-missile-drops-straight-back-down-and-explodes-on-the-launcher/). Confirms there is a real, visible ballistic hang with zero thrust.

---

## 2. 5P85 TEL GEOMETRY (MAZ-7910 8x8)

Sources: https://truck-encyclopedia.com/coldwar/ussr/5P85.php, https://www.ausairpower.net/APA-S-300PMU-TEL-TL.html, https://en.missilery.info/missile/c300ps, https://www.armyrecognition.com/military-products/army/air-defense-systems/air-defense-vehicles/5p85s-s-300-battery-russia-uk

- **Chassis**: MAZ-7910 (MAZ-543M derivative), 8x8, 4 evenly-ish spaced axles (axles 1-2 grouped front, 3-4 grouped rear with a gap mid-hull), 525 hp V-12 diesel, curb 23.3 t, full launcher 42.15 t.
- **Overall (launcher, stowed)**: length **13.11 m**, width **3.15 m**, height **3.8 m**. Bare chassis 11.45 x 3.05 x 3.55 m, wheelbase 7.7 m.
- **Cab**: single squat angular cab on the **front left** only; the engine housing sits right of it. Flat windscreen panels, headlight clusters low on bumper.
- **5P85S "master"**: large boxy **F3S electronics cabin** directly behind the cab (sloped-roof shed shape, as tall as the cab). **5P85D "slave"**: no big cabin — flatter deck. Late 5P85SE/TE: smaller enclosures (ausairpower).
- **Tube block**: 4 sealed cylindrical TPKs raised **as one block** at the very rear by a two-section hydraulic boom. Arrangement is **2x2, slightly trapezoidal** ("four launch tubes in a unique symmetrical trapezoidal arrangement" — ausairpower): the two outer/upper tubes sit a touch wider/higher than the inner pair when stowed.
- **Tube dimensions**: each TPK ~**8 m** long (missile 7.5 m + closures), outer diameter ~**1.0 m** including wall and clamp rings (scaled from photos vs 3.15 m vehicle width; missile inside is 0.52 m). Tubes have **5–6 prominent circumferential clamp/joint rings** dividing them into barrel segments — the single strongest modeling detail.
- **Erected**: block stands fully vertical just aft of the rear axles; tube bottoms (rounded dome end caps) hang ~0.5–1 m off the ground; tube tops reach ~**9–9.5 m** above ground (tube 8 m + ground clearance) — about 2.5x cab height. A **lattice umbilical mast/frame sits between/atop the tubes** carrying "U-shaped missile control and status umbilical cables and connectors" (ausairpower) plus the erecting boom structure on the cab-facing side (clearly visible in File:Sa10 1.jpg, the classic winter photo: https://commons.wikimedia.org/wiki/File:Sa10_1.jpg).
- **Stowed**: tubes lie horizontal pointing forward over the deck, forward ends (with khaki canvas weather covers over the caps) just behind/above the cab, rear ends overhanging the tail. Flat tube end faces at the rear.
- **Outriggers**: hydraulic jacks lowered before erection/launch — pads visible under hull between axle groups and at the rear; vehicle auto-levels (ausairpower). Deploy/stow in **5 minutes**.
- **Colors** (from viewed photos):
  - File:S-300PS_TEL,_Kyiv_2021,_10.jpg (https://commons.wikimedia.org/wiki/File:S-300PS_TEL,_Kyiv_2021,_10.jpg): uniform dark olive-green truck, **pale grey-green tubes**, tan/khaki canvas covers laced over forward tube ends, black tires, small red/white unit patch on cab.
  - File:Slovak_S-300_PS_TEL_at_SIAF-2021.jpg and File:Slovak_S300PS_5V55R.jpg (https://commons.wikimedia.org/wiki/File:Slovak_S300PS_5V55R.jpg): green + brown blotch camo over tubes and truck; rear view confirms 2x2 cluster, segment rings, dome bottom caps, canvas-covered deck boxes.
  - Default skin recommendation: overall dark olive (RAL 6003-ish), tubes either same olive or noticeably lighter grey-green.

---

## 3. 48N6 MISSILE GEOMETRY

Sources: https://en.wikipedia.org/wiki/S-300_missile_system, https://weaponsystems.net/system/1417->>48N6, https://www.ausairpower.net/APA-Grumble-Gargoyle.html, https://en.missilery.info/missile/c300pmu1

- **Length 7.5 m, body diameter 0.519 m, fin span 1.134 m, launch mass ~1,800 kg** (1,799–1,835 kg by variant). (5V55 for comparison: 7.25 m, 0.514 m, 1,480 kg.)
- **Shape**: clean constant-diameter cylinder over ~80% of length; **pointed ogive nose** roughly 1.5 m long; slight boat-tail at the nozzle.
- **Tail**: **4 small clipped-delta control fins** in cruciform, low aspect ratio, span only ~2.2x body diameter; they **fold to fit the tube and snap open at tube exit** (DCS modeling thread on fin folding: https://forum.dcs.world/topic/354021-s-300-5v55-missile-fins-folding-is-wrong-48n6-missile/). Gas-dynamic TVC vanes inside/behind the nozzle (not visible except as exhaust asymmetry during tip-over).
- **Body details**: very small low-profile strakes/conduit fairings running along the aft body; umbilical connector plate; radio-proximity-fuze antenna rings near nose; no mid-body wings (unlike Patriot's long strakes — keep the body conspicuously clean).
- **Colors**: display/parade rounds and museum 5V55/48N6 are **white or very light grey** with darker grey nose tip; in launch footage the missile reads as a **dark grey/black silhouette** against the flame. In-game: light grey body, near-black ogive tip works.
- Warhead 143–145 kg HE-frag; single-stage solid motor; cold-launch gas ejector listed as part of propulsion (weaponsystems.net).

---

## 4. INTERCEPT FLIGHT PROFILE

Sources: https://www.ausairpower.net/APA-Grumble-Gargoyle.html, https://nuke.fas.org/guide/russia/airdef/s-300pmu.htm, https://www.globalsecurity.org/military/world/russia/s-300pmu2.htm, https://en.missilery.info/missile/c300pmu1, https://en.wikipedia.org/wiki/S-300_missile_system

- **Guidance**: command guidance from the 30N6 Flap Lid engagement radar with **TVM/SAGG** (missile seeker measurements relayed down, commands up) and semi-active terminal homing; 48N6E2 described as "inertial guidance with radio correction... during target interception — active self-guidance" (globalsecurity). **Game simplification (valid): midcourse command steer to a predicted intercept point + terminal proportional navigation.**
- **Trajectory shaping**: long-range shots fly **lofted ballistic profiles with apogees in excess of 40 km**, trading altitude for speed and **diving on the target from above** ("approaches the target from above" — FAS/globalsecurity; "ballistic flight profiles with apogees in excess of 40 km" — ausairpower). Short/low engagements: near-direct, much flatter, with an aggressive early tip-over right after launch.
- **Envelope (48N6 family)**: range 5–**150 km** (48N6), **200 km** (48N6E2/D), 250 km (48N6DM, S-400); altitude **10 m (PMU2) / 25 m (earlier) up to 27 km** (some sources 30 km); target speed up to 2,800 m/s (PMU1) / 10,000 km/h (PMU2).
- **Speed profile**: 0 → ~1,900–2,100 m/s in ~12 s, then unpowered coast for the remaining 30–150+ s. Speed decays continuously after burnout (drag + gravity on the climb, partial recovery in the terminal dive). No hard sourced number for arrival speed; for game purposes ~700–900 m/s (Mach 2–2.5) at max range is a reasonable estimate consistent with the lofted "potential→kinetic energy" description (ausairpower). Maneuver cap ~25 g (weaponsystems.net).
- Max missile flight time on the order of 100–180 s for max-range shots (estimate).

---

## 5. TOP 10 VISUAL SIGNATURES (ranked — drives model/feel review)

1. **The vertical 2x2 tube block towering ~9 m over the rear of an 8x8 truck** — nothing else reads "S-300" faster.
2. **Eject – hang – BOOM**: missile pops out at ~20 m/s, visibly decelerates for ~1–1.5 s to near-zero at 20–30 m, then a fireball wider than the missile erupts at its base.
3. **The smoke-column kink**: vertical white column off the TEL bending 30°+ within the first 100 m as gas vanes slew the missile toward the target.
4. **Circumferential clamp rings** segmenting each launch tube into 5–6 barrel sections.
5. **Cover-blow debris**: tube cap fragments and the catapult tray spinning away around the ignition fireball.
6. **Tail fins snapping open** the instant the missile clears the tube mouth.
7. **F3S boxy electronics cabin** behind the cab on the 5P85S (and its absence on the 5P85D) + lattice umbilical mast between the erected tubes.
8. **Ground blast carpet**: radial dust/smoke washing out from under the TEL at ignition, orange-lit by the flash; TEL left shrouded in a white cloud.
9. **Brilliant torch + dense white trail** during the 12 s boost, missile shrinking to a dot at Mach 6, then trail abruptly ends at burnout.
10. **Dark olive truck / lighter grey-green tubes, khaki canvas tube covers, black dome bottom caps** hanging just off the ground when erected, outrigger jacks down.

---

## FEEL BRIEF — what the in-game launch must do to read as authentic

- **Sell the pause.** Eject at ~20 m/s with a hard initial jolt, then 1.0–1.5 s of pure gravity deceleration — the missile must visibly slow and almost stop ~20–30 m up. If the player doesn't subconsciously think "is it going to fall back?", the pause is too short.
- **Make ignition violent and instantaneous.** One frame: dim coasting dart; next frame: spherical fireball 3–4 body-diameters wide, smoke donut, debris chunks, ground dust slammed outward, audio whump delayed by distance. No slow throttle-up.
- **Tip over low and mean.** Begin the programmed slew 0.3–0.5 s after ignition and complete most of a 20–45° tilt within the first ~100 m, leaving a sharply kinked smoke column anchored to the TEL.
- **Boost should feel like a drag race, not a firework.** ~16–25 g for 12 s: the missile crosses the whole sky-dome in seconds, trail brilliant white and thick, then cuts off cleanly at burnout — after which the missile is a fast, slowly bleeding dart that arcs over and dives on far targets from 30–40 km up.
- **The TEL is a participant, not a prop.** Outriggers down, tubes erected as one block, one cap blowing per shot, 3–5 s ripple between rounds, truck rocking slightly on the jacks at eject, and a lingering white cloud that drifts off downwind.

---

## Source index
- https://en.wikipedia.org/wiki/S-300_missile_system | https://ru.wikipedia.org/wiki/С-300 | https://en.wikipedia.org/wiki/S-400_missile_system
- https://nuke.fas.org/guide/russia/airdef/s-300pmu.htm | http://www.astronautix.com/s/s-300.html
- https://www.globalsecurity.org/military/world/russia/s-300pmu2.htm
- https://en.missilery.info/missile/c300ps | https://en.missilery.info/missile/c300pmu1
- https://www.ausairpower.net/APA-S-300PMU-TEL-TL.html | https://www.ausairpower.net/APA-Grumble-Gargoyle.html
- https://truck-encyclopedia.com/coldwar/ussr/5P85.php
- https://www.armyrecognition.com/military-products/army/air-defense-systems/air-defense-vehicles/5p85s-s-300-battery-russia-uk
- https://weaponsystems.net/system/1417->>48N6
- https://pvo.guns.ru/s300p/index_s300pt.htm | https://library.voenmeh.ru/cnau/zYV8b40nMGwFpBA.pdf (S-300 systems textbook, Khramov/Yakovlev)
- https://www.globaldefensecorp.com/2024/02/25/russias-s-300-missile-launch-spectacularly-goes-wrong-when-the-missile-drops-straight-back-down-and-explodes-on-the-launcher/
- https://forum.dcs.world/topic/354021-s-300-5v55-missile-fins-folding-is-wrong-48n6-missile/
- Images viewed (local copies in `img\`): Commons File:UA_S-300_firing.jpg, File:Ukrainian_s-300_launch.jpg, File:S-300PS_TEL,_Kyiv_2021,_10.jpg, File:Slovak_S-300_PS_TEL_at_SIAF-2021.jpg, File:Slovak_S300PS_5V55R.jpg, File:Sa10_1.jpg
