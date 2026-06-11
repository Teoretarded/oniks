# P-800 Oniks / Yakhont / BrahMos — Launch Sequence, Frame-by-Frame
### Verification + timeline study for the in-game cinematic launch
Compiled 2026-06-11. Builds on `oniks_reference.md` (same folder). All claims cited inline.
New evidence images and extracted video frames in `C:\Users\teoti\AppData\Local\Temp\oniks_research\img\` (index in §7).

**Primary new sources for this study:**
- **NPO Mashinostroyeniya patent RU2240489C1** — the actual design bureau's patented launch method for a canisterized winged missile with nose-mounted orientation thrusters (the Oniks launch scheme): https://patents.google.com/patent/RU2240489C1/ru
- **Frame-by-frame analysis I performed on two official Indian MoD/Navy launch videos** (BrahMos = same 3M55 airframe and launch scheme):
  - `vid_brahmos_er.webm` — BrahMos-ER ground vertical test, ITR Chandipur, 20 Jan 2022, with on-screen T+ timecode (https://commons.wikimedia.org/wiki/File:Brahmos_ER.webm)
  - `vid_visakhapatnam.webm` — vertical UVLM launch from INS Visakhapatnam, Feb 2022, aerial view (https://commons.wikimedia.org/wiki/File:INS_Visakhapatnam_firing_Brahmos_Supersonic_missile.webm)
- Battle Machines explainer on the BrahMos/P-800 VLS pitch-over: https://battlemachines.org/2024/03/07/why-do-indian-brahmos-russian-p-800-sharply-pitch-over-during-launch-from-vls/
- BrahMos Aerospace official submarine-launch page: https://www.brahmos.com/page/submarine-system
- militaryrussia.ru 3M55 dossier: http://militaryrussia.ru/blog/topic-92.html
- testpilot.ru P-800 dossier: https://testpilot.ru/russia/chelomei/p/800/index_1.php

---

## 0. VERDICT ON THE CREATIVE DIRECTOR'S READ

He watched correctly. Three of his four observations are literally what the engineering does; one needs correction:

| His read | Verdict |
|---|---|
| "Missile comes up out of the tube" | ✔ Hot ride-out, flame already at the muzzle (see §2). |
| "Goes briefly near-stationary a few meters above it" | ✖ **Correct feel, wrong place.** It never hovers and never sits "a few metres" up. It exits at ~25–40 m/s and keeps accelerating gently. The "hesitation" he saw is the **pitch-over at ~100–250 m**, where vertical motion stops growing and the missile swaps ends — on long-lens footage this reads as a hang. |
| "Something at the NOSE (cap thrusters?) turns it toward the target" | ✔ Exactly right. Pulse rocket motors **inside the nose cap** do pitch, yaw AND roll (§1, §2). |
| "Then the nose cap blasts off and it accelerates extremely hard" | ✔ Word-for-word the patented sequence: cap is shot **forward** off the nose, and "immediately after the fact of SUO housing separation, the high-thrust motor ignites" (RU2240489C1). |

---

## 1. THE NOSE CAP (головной обтекатель)

### What it is
A conical fairing covering the annular intake + central cone during canister stowage and the vertical/underwater leg. Compare the two states in photos:
- **Capped:** `img/brahmos_display_drdo01.jpg` — white display BrahMos at a DRDO museum: smooth, sharp, featureless ogive-cone nose, intake completely hidden (https://commons.wikimedia.org/wiki/File:DRDO_Brahmos_Missile_01.jpg). Also `img/brahmos_chandipur2019_climb.jpg` — in actual flight, cap still on during the vertical climb, wearing a black/white checkered photogrammetry band (https://commons.wikimedia.org/wiki/File:BrahMos_supersonic_cruise_missile_successfully_test-fired_from_the_Integrated_Test_Range,_at_Chandipur_on_30_September_2019.jpg).
- **Uncapped:** `img/yakhont_armia2018.jpg`, `img/yakhont_army2022.jpg` — open annular intake ring with the needle central cone protruding (see `oniks_reference.md` §1.2 for geometry).

### What's inside it (this is the surprise)
The cap is not dead weight — it is the **SUO, the orientation-control unit** ("корпус средств управления ориентацией установлен на носовой части ракеты" — "the orientation control housing is installed on the nose section", NPO Mash patent https://patents.google.com/patent/RU2240489C1/ru). It carries pulse solid motors in groups:
- a **pitch pair** (двигатели склонения по тангажу),
- a **yaw pair** (двигатели разворота по курсу),
- **four tangential roll motors**,
- a **pair of separation/pull-away motors with nozzles angled to the missile axis** (пара РДТТ увода).

militaryrussia.ru confirms hardware: "2 х РДТТ отделения и увода носового обтекателя разработки НПО 'Искра' (г.Пермь)" — *two solid motors for separation and pull-away of the nose fairing, developed by NPO Iskra, Perm* (http://militaryrussia.ru/blog/topic-92.html). Battle Machines describes the same in English: "precisely timed rocket firings in the nose cap... pulse motors for initiating the pitching, arresting the pitching, initiating the rolling, arresting rolling" (https://battlemachines.org/2024/03/07/why-do-indian-brahmos-russian-p-800-sharply-pitch-over-during-launch-from-vls/).

### When it separates
**At the end of tip-over, before main boost — NOT at tube exit and NOT at ramjet transition.** Sequence per the patent: orient the missile → give the cap ("passive mass") "an impulse in the direction of rocket motion" → "вслед за фактом отделения корпуса СУО запускается РДТТ большой тяги" (*immediately after cap separation the high-thrust motor ignites*) (https://patents.google.com/patent/RU2240489C1/ru). BrahMos Aerospace puts it operationally: "the nose cap is fired for turning the missile in the desired direction to hit the target" (https://www.brahmos.com/page/submarine-system). Battle Machines: "Once the missile is directed towards its target, the nose cone is ejected, and a high thrust motor kicks in" (URL above). militaryrussia.ru: "Головной обтекатель отстреливается после старта" — *the nose fairing is shot off after launch* (http://militaryrussia.ru/blog/topic-92.html).

In my frame analysis of the timecoded Chandipur video (https://commons.wikimedia.org/wiki/File:Brahmos_ER.webm): cap events at **T+3 to T+4, ~2–3 s after tube exit**, right at the end of the ~90° pitch.

### How it separates and what it looks like
- **Mechanism:** the two angled NPO Iskra pull-away motors fire and throw the cap **forward off the nose** (forward impulse, patent RU2240489C1) — the slow missile then out-accelerates it and the cap falls behind. No pyro ring fragments; it's one rigid cone leaving whole.
- **In footage:** during the pitch the nose shows **short orange jets** distinct from the white tail flame — two flames on one airframe for a moment (`img/seq_t3_pitch_nose_jets.png`, frame at T+3 of the Chandipur video). One frame-pair later the cap is visible as a **small dark angular chunk hanging in mid-air** while the missile streaks past it on the freshly-lit high-thrust plume: `img/seq_t4_cap_away_highthrust.png` and zoom `img/seq_t4_cap_zoom.png` (frames at T+4, https://commons.wikimedia.org/wiki/File:Brahmos_ER.webm). It then simply drops — at sea, splashes a few hundred metres from the ship.

---

## 2. EXIT AND TIP-OVER

### Launch mode: hot ride-out with gas-generator assist (the sources reconcile)
- The patent's surface/land scheme: a **powder pressure accumulator (ПАД)** pressurizes the closed-bottom canister and starts the missile moving piston-style, AND the dual-thrust booster lights **in low-thrust mode while still moving through the canister**: "запуска разгонной двигательной установки в режиме малой тяги в процессе перемещения ракеты в контейнере" — *to increase exit velocity while limiting loads* (https://patents.google.com/patent/RU2240489C1/ru). This is why footage shows muzzle flame at exit (e.g. `img/brahmos_launch_imphal.jpg`, https://commons.wikimedia.org/wiki/File:Brahmos_being_launched_from_Imphal_Y-12706.jpg) even though some tertiary sources call it "cold launch" (e.g. https://en.namu.wiki/w/VLS); Battle Machines' "cold start using a gas generator... 20–50 m/s" describes the ПАД half of the same scheme (https://battlemachines.org/2024/03/07/why-do-indian-brahmos-russian-p-800-sharply-pitch-over-during-launch-from-vls/). The closed-bottom TPK needs no flame trench (https://en.missilery.info/missile/jakhont).
- Russian dossiers agree the booster proper is running from canister departure: "После выхода ракеты из пускового контейнера включается твердотопливный разгонный блок" (https://testpilot.ru/russia/chelomei/p/800/index_1.php).

### Exit velocity
- Battle Machines: **20–50 m/s** ejection (URL above).
- My pixel measurement on the Chandipur video (missile ≈ 9 m incl. cap, consecutive frames at 25 fps as the body clears the tower): **≈ 25–40 m/s, i.e. 3–4.5 body-lengths per second** — and visibly accelerating from the first second (frames `img/seq_t1_riseout.png`, https://commons.wikimedia.org/wiki/File:Brahmos_ER.webm).

### Is there a hang phase?
**No true hover anywhere in the footage.** The low-thrust ride is continuous but *lazy* — net acceleration looks like ~1–3 m/s² on top of the ejection speed, a heavy, columnar, "standing on its flame" climb (Chandipur video seconds T+1→T+3; Visakhapatnam video t≈1.3 s→4.2 s). The *impression* of hesitation comes at the pitch-over: vertical speed plateaus, the trail kinks, and for ~0.5 s the missile visibly trades climb for rotation (`img/vis_pitchover_t4.png`). Battle Machines: "a low-thrust engine kicks in carrying the missile to about 200–250 mtrs above the launcher" before the computer "pitches the missile dramatically" (URL above).

### How tip-over is done
**Nose-cap pulse motors, not booster TVC and not aerodynamics.** Pitch-initiate pulse → ballistic rotation → pitch-arrest pulse, plus a **roll program** so the missile is right-side-up for guidance ("a rolling maneuver which makes sure that the missile is the right-side up", Battle Machines URL above; motor groups per patent RU2240489C1). At 25–60 m/s the fins have almost no authority and the booster nozzle is buried in the ramjet duct ("Стартовый РДТТ находится в сопле маршевого ПВРД", http://militaryrussia.ru/blog/topic-92.html), so nose thrusters are the only way — exactly the "angled jets near the nose" seen in footage.

### Height and aggressiveness
- Turn altitude: **~100–250 m**. Battle Machines says 200–250 m; my measurement of the Visakhapatnam video (ship length 163 m as scale) puts the trail kink at ≈ 100–130 m above deck, with the turn complete by ~200 m — foreshortening makes the aerial measurement a lower bound (https://commons.wikimedia.org/wiki/File:INS_Visakhapatnam_firing_Brahmos_Supersonic_missile.webm).
- Rate: in the Chandipur video the missile goes from ~15° off vertical to **~90° (horizontal) in ≈ 0.75–1.0 s → peak ~90–120°/s** (frames T+2.5→T+3.5, `img/seq_t2_tilt_begin.png` → `img/seq_t3_pitch_nose_jets.png`). That ground test pitched all the way flat (low-trajectory shot); ship launches in footage typically stop at ~40–50° off vertical and flatten progressively (`img/vis_candycane_t7.png`). For something 3 tonnes and 9 m long, 90°/s looks *unnervingly* agile — the signature "whiplash" moment.
- The whole arc draws the famous **candy-cane trail**: straight white column, tight bend, long inclined leg (`img/vis_candycane_t7.png`).

---

## 3. TIMELINE — t = 0 at tube exit (vertical launch)

Built from the timecoded Chandipur ER video (T+ values; exit happens during T+1), the Visakhapatnam video, the NPO Mash patent, and the Russian dossiers. Confidence: ★ = direct footage/patent, ☆ = inference/secondary.

| t (s) | Event | Look: violent or gentle | Source |
|---|---|---|---|
| −0.4…−0.2 | Canister cap blown/membrane burst; ПАД fires; **pink-grey muzzle cloud** erupts; low-thrust booster mode lights in-tube | **VIOLENT** — fireball/mushroom at muzzle (`img/seq_t1_muzzle_cloud.png`; huge orange ball on land TEL: `img/brahmos_block3_parade.jpg`) | ★ RU2240489C1; Commons Brahmos_ER.webm; https://commons.wikimedia.org/wiki/File:Brahmos_Block_III.jpg |
| 0.0 | Tube exit at **25–40 m/s** (3–4.5 lengths/s), flame washing out of the muzzle around the tail | gentle-but-massive: a building leaving the ground | ★ frame measurement; ☆ 20–50 m/s battlemachines.org |
| 0.2–0.5 | Wings + tail fins snap out | small mechanical snap, barely visible | ☆ https://en.missilery.info/missile/jakhont |
| 0.5–2.0 | Low-thrust vertical ride to ~100–200 m; slight wiggle from attitude pulses; dense white column | **GENTLE / HEAVY** — the slow stately rise | ★ both videos |
| ~1.5–2.5 | **Pitch-initiate + roll pulses from nose-cap motors**; missile rotates at up to ~90–120°/s toward target bearing | eerie agility; trail kinks; reads as the "hesitation" | ★ Brahmos_ER.webm T+2.5–3.5; RU2240489C1; battlemachines.org |
| ~2.5–3.5 | Pitch-arrest pulses; **cap pull-away motors fire (orange nose jets), cap shot forward, tumbles away** | sharp little double-flash at the nose, debris drops | ★ Brahmos_ER.webm T+3–4 (`img/seq_t3_pitch_nose_jets.png`, `img/seq_t4_cap_zoom.png`); RU2240489C1 |
| ~2.7–3.7 | **High-thrust mode ignites immediately after cap-off** — plume bloom 3–5× bigger, trail turns darker grey | **VIOLENT** — the grunt; missile visibly jumps away from its own smoke | ★ Brahmos_ER.webm T+4 (`img/seq_t4_cap_away_highthrust.png`); RU2240489C1 |
| 3.7–9 | Flat/shallow boost; brutal acceleration; trail thins as speed grows | **VIOLENT** — streak (`img/seq_t5_grey_trail_flat.png`, `img/seq_t7_departure.png`) | ★ footage; ☆ "supersonic in about 7 seconds" battlemachines.org |
| ~7–10 | **Mach 2; booster burnout**; ram air through the now-open intake **expels the spent booster slug out the nozzle**; ramjet (T-6 kerosene) lights | smoke trail ENDS almost mid-air; plume goes near-transparent | ☆ "Скорость к моменту окончания работы стартового РДТТ — 2 М" http://militaryrussia.ru/blog/topic-92.html; "его выбрасывает из маршевого набегающим потоком воздуха" https://testpilot.ru/russia/chelomei/p/800/index_1.php; https://en.missilery.info/missile/jakhont |
| 10+ | Ramjet cruise M2.0–2.6 (680–750 m/s) | clean, almost smokeless dart | ☆ http://militaryrussia.ru/blog/topic-92.html |

Notes on uncertainty: no public source gives booster burn time to a decimal; "несколько секунд" (a few seconds) to M2 is the consistent Russian claim. The 2–5 s ripple interval between rounds of one TEL is documented (https://en.wikipedia.org/wiki/K-300P_Bastion-P).

---

## 4. SMOKE / FLAME SIGNATURES PER PHASE

1. **In-tube ignition / muzzle blast:** pink-grey ПАД + booster efflux mushroom blowing UP and OUT of the muzzle around the emerging body; on the Bastion/land TEL it reads as a genuine orange fireball enveloping the canister tops for ~1 s (`img/seq_t1_muzzle_cloud.png`; `img/brahmos_block3_parade.jpg` — note dark canister-cap debris flying at frame left; https://commons.wikimedia.org/wiki/File:Brahmos_Block_III.jpg).
2. **Ride-out plume (low thrust):** short brilliant white-orange tail flame ~1–1.5 body lengths; **dense cream/white smoke column** 3–5 m wide, slightly corkscrewed by attitude pulses; ground wash engulfs the TEL/deck (`img/brahmos_chandipur2019_climb.jpg`, `img/brahmos_launch_chennai.jpg`).
3. **Tip-over:** asymmetric **orange puffs at the nose** (pitch/roll/pull-away pulse motors), 2–4 short events, each a few frames long; trail kinks into the candy-cane (`img/seq_t3_pitch_nose_jets.png`, `img/vis_pitchover_t4.png`).
4. **Cap jettison:** tiny forward flash, then a black tumbling cone falling clear (`img/seq_t4_cap_zoom.png`). No smoke ring observed in any footage examined.
5. **High-thrust boost column:** plume blooms to several body lengths, white-yellow core; smoke turns **noticeably darker grey** and the trail thins with speed — by Mach ~1.5 it's a pencil line (`img/seq_t5_grey_trail_flat.png`, `img/seq_t7_departure.png`).
6. **Ramjet:** nearly **transparent** kerosene exhaust — the visible trail simply stops at burnout/slug-ejection; from then on the missile is a glinting dart with heat shimmer (booster expulsion per https://testpilot.ru/russia/chelomei/p/800/index_1.php; https://en.missilery.info/missile/jakhont).
7. **Launcher afterwards:** canister mouth scorched and wisping smoke for tens of seconds; drifting white ground cloud downwind; on ships, deck steam/wash (`img/vis_candycane_t7.png` shows the column still anchored to the ship long after the missile left). Bastion fires 3 rounds in quick succession through the same haze (https://www.twz.com/44891/russia-claims-it-launched-bastion-p-anti-ship-missiles-against-ground-targets-in-ukraine).

---

## 5. INCLINED vs VERTICAL

- **Bastion-P (land):** canisters erected to ~90°; full sequence as in §3 (https://en.wikipedia.org/wiki/K-300P_Bastion-P; `img/bastion_prelaunch.jpg`).
- **Vertical ship VLS (UVLM / 3S-14):** same as land; lid opens in 2.5 s (3S-14E data, http://militaryrussia.ru/blog/topic-92.html); pitch-over timed "to avoid damaging ship superstructure" — СУО activation "по заданному времени от начала движения" (RU2240489C1).
- **Inclined launch (ship modular launcher, some export Yakhont fits, TPK rated 15°–90°):** missile leaves the canister already pointed roughly on-bearing and right-side-up, so **no whiplash pitch and a simplified nose cap** — "In inclined launches... the missile is already stored the right-side up with no abrupt pitch maneuver, so the nose cap is significantly simplified" (https://battlemachines.org/2024/03/07/why-do-indian-brahmos-russian-p-800-sharply-pitch-over-during-launch-from-vls/). Footage: `img/brahmos_delhi_inclined_2022.jpg` — INS Delhi 2022, missile departing on a straight inclined line with flame + white trail, no candy-cane (https://commons.wikimedia.org/wiki/File:The_BrahMos_missile_fired_from_an_upgraded_modular_launcher_on_INS_Delhi_on_20_April_2022_-_1.jpg).
- **Submarine:** cap additionally keeps water out of the intake; "out of water command" from sensors triggers the cap thrusters at surface-broach (https://www.brahmos.com/page/submarine-system).

For the game's Bastion launch, use the vertical sequence; if you add a ship, an inclined cell is the "easy mode" variant with the same plume palette minus steps 5–6 of the storyboard.

---

## 6. CINEMATIC FEEL BRIEF — 10-step storyboard (vertical Bastion launch)

Goal: HEAVY. The trick the real footage teaches: **slow everything before the cap, then detonate the acceleration after it.** Contrast is the weight.

1. **t = −2.0 — Arm.** Canister cap stays on. TEL hunkers on jacks; hydraulics creak; a klaxon; birds scatter. Low sub-bass hum builds. (Lid/membrane: closed-bottom TPK, no flame trench — https://en.missilery.info/missile/jakhont)
2. **t = −0.3 — Muzzle blast.** Canister cap blows off in chunks; a pink-grey ПАД cloud punches 10 m up; one frame later an orange fireball blooms around the muzzle as the in-tube flame breaches. FULL camera shake, single concussive BOOM with echo. (RU2240489C1; `img/brahmos_block3_parade.jpg`)
3. **t = 0.0 — Exit, 30 m/s.** The nose spears out of the fire; the whole 9 m body rises in ~0.3 s; flame gushing AROUND the base from the tube. Sound: continuous ripping roar, but pitch LOW. Slight slow-motion here sells mass.
4. **t = 0.3 — Fins snap.** Four wings + four rudders flick out with a metallic clack barely audible under the roar. (https://en.missilery.info/missile/jakhont)
5. **t = 0.5–1.5 — The heavy ride.** Climb at 30→45 m/s, barely accelerating; dense cream smoke column; tiny attitude wiggles (±1°). Camera tilts up slowly; roar steady; shake decaying. This is the "it shouldn't be able to fly" beat. (Chandipur/Visakhapatnam footage)
6. **t = 1.6 — Nose thrusters.** At ~120 m: two sharp orange puffs from the nose cap, CRACK-CRACK over the roar; missile pitches toward target bearing at **80°/s** with a quarter-roll; smoke trail kinks into the candy-cane. Brief near-silence under it = the "hesitation". (`img/seq_t3_pitch_nose_jets.png`; RU2240489C1; ~90–120°/s measured)
7. **t = 2.4 — Arrest + cap kick.** Counter-puff arrests the pitch at ~50° (or flatter for close targets); the angled pull-away motors flash; **the black cone cap shoots forward, then tumbles past camera** as the missile out-runs it. (`img/seq_t4_cap_zoom.png`)
8. **t = 2.6 — Full grunt.** High-thrust ignition: plume blooms 4×, white-yellow, trail goes dark grey; **6–8 g** longitudinal (tuned for drama; sources say only "supersonic in ~7 s" — battlemachines.org). Sound: a second, deeper detonation rolling into a crackling Saturn-style tear. Hard camera punch + persistent low shake.
9. **t = 3–8 — The streak.** Flat/shallow trajectory, speed ramping through M1 (~5 s) toward M2 (~8 s); trail thinning to a pencil line; doppler drop as it crosses the camera. Launcher foreground: scorched, smoking canister mouth, drifting cloud. (`img/seq_t7_departure.png`)
10. **t = 8–10 — Ghost mode.** Booster burnout: the smoke line just STOPS mid-sky; a dark slug (spent booster) spits from the tailpipe and falls; ramjet plume nearly invisible — only heat shimmer and a receding glint. Sound fades to a thin distant shriek. (https://testpilot.ru/russia/chelomei/p/800/index_1.php; http://militaryrussia.ru/blog/topic-92.html)

**Effects cheat-sheet:** muzzle cloud = pink-grey; ride-out smoke = cream-white, dense, 3–5 m wide; nose puffs = small, orange, asymmetric; boost trail = grey, darker than ride-out; ramjet = transparent + shimmer. Shake peaks: step 2 (biggest), step 8 (deepest). Slow-motion budget: steps 3 and 7 only.

---

## 7. IMAGE INDEX (new files this study; older files indexed in oniks_reference.md)

| File | What it shows | Source |
|---|---|---|
| `img/seq_t1_muzzle_cloud.png` | T+1: muzzle cloud around tower, in-tube flame | frame, https://commons.wikimedia.org/wiki/File:Brahmos_ER.webm |
| `img/seq_t1_riseout.png` | T+1: ride-out on low thrust | frame, same video |
| `img/seq_t2_tilt_begin.png` | T+2: first ~15° of tilt | frame, same video |
| `img/seq_t3_pitch_nose_jets.png` | T+3: near-horizontal, ORANGE NOSE JETS + tail flame simultaneously | frame, same video |
| `img/seq_t4_cap_away_highthrust.png` | T+4: high-thrust bloom; cap visible as dark dot | frame, same video |
| `img/seq_t4_cap_zoom.png` | zoom: jettisoned cap tumbling in mid-air | frame, same video |
| `img/seq_t5_grey_trail_flat.png` | T+5: dark-grey boost trail, flat trajectory | frame, same video |
| `img/seq_t7_departure.png` | T+7: thinning trail, missile nearly gone | frame, same video |
| `img/vis_pitchover_t4.png` | ship launch: pitch-over bend ~100–200 m over INS Visakhapatnam | frame, https://commons.wikimedia.org/wiki/File:INS_Visakhapatnam_firing_Brahmos_Supersonic_missile.webm |
| `img/vis_candycane_t7.png` | full candy-cane trail anchored to the ship | frame, same video |
| `img/brahmos_block3_parade.jpg` | land TEL launch: orange fireball around canister mouths, cap debris | https://commons.wikimedia.org/wiki/File:Brahmos_Block_III.jpg |
| `img/brahmos_chandipur2019_climb.jpg` | vertical climb with NOSE CAP STILL ON (checkered band), TEL in smoke wash | https://commons.wikimedia.org/wiki/File:BrahMos_supersonic_cruise_missile_successfully_test-fired_from_the_Integrated_Test_Range,_at_Chandipur_on_30_September_2019.jpg |
| `img/brahmos_display_drdo01.jpg` | CAPPED nose, display round (vs uncapped Yakhont photos) | https://commons.wikimedia.org/wiki/File:DRDO_Brahmos_Missile_01.jpg |
| `img/brahmos_delhi_inclined_2022.jpg` | inclined ship launch — no pitch-over | https://commons.wikimedia.org/wiki/File:The_BrahMos_missile_fired_from_an_upgraded_modular_launcher_on_INS_Delhi_on_20_April_2022_-_1.jpg |
| `img/brahmos_launcher_republicday.jpg` | land TEL, 3 canisters, travel config | https://commons.wikimedia.org/wiki/File:Brahmos_launcher_Republic_day.jpg |
| `img/brahmos_pmc_2024.jpg` | scale model of mobile autonomous launcher (geometry ref only) | https://commons.wikimedia.org/wiki/File:2024-09-25_PMC_BrahMos_002.jpg |
| `vid_brahmos_er.webm`, `vid_visakhapatnam.webm` | source videos (in research root) | Commons, GODL-India license |

### Source list (deduplicated)
RU2240489C1 (NPO Mash) https://patents.google.com/patent/RU2240489C1/ru • battlemachines.org/2024/03/07/why-do-indian-brahmos-russian-p-800-sharply-pitch-over-during-launch-from-vls/ • brahmos.com/page/submarine-system • militaryrussia.ru/blog/topic-92.html • testpilot.ru/russia/chelomei/p/800/index_1.php • en.missilery.info/missile/jakhont • warfor.me/unifitsirovannyiy-protivokorabelnyiy-raketnyiy-kompleks-p-800-oniks/ • ru.wikipedia.org/wiki/Миномётный_старт • en.wikipedia.org/wiki/BrahMos • en.wikipedia.org/wiki/K-300P_Bastion-P • twz.com/44891 • en.namu.wiki/w/VLS (cold-launch claim, contradicted by patent/footage) • Commons file pages listed above.
