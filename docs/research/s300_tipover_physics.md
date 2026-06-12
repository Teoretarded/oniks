# S-300 (48N6 family) cold-launch tip-over: physical data, math, footage evidence, and sim constants

Research date: 2026-06-12. Purpose: settle whether the game's launch tip-over (path rotation up to 120 deg/s) is physically plausible for a 48N6-class round, and provide a defensible parameter set.

**TL;DR: 120 deg/s path rotation is ~3x too fast. Real 48N6 war-shot launches pitch the body at ~30–45 deg/s peak, reaching 30° from vertical ~1 s after motor ignition and ~60° at ~2 s. The path turn rate is capped by lateral acceleration = T·sin(AoA)/m ≈ 40–45 m/s², which gives ~45 deg/s at 50 m/s and decays as 1/v.**

---

## 1. Physical data

### 1.1 48N6 / 48N6E / 48N6E2 (S-300PM / PMU-1 / PMU-2, S-400 baseline round)

| Parameter | Best value | Spread in sources | Sources |
|---|---|---|---|
| Launch mass | **1,900 kg** (domestic 48N6); 1,800 kg (48N6E); 1,840 kg (48N6E2) | 1,780–1,900 kg | Nevsky Bastion S-300 supplement (GUAP mirror, decoded from PDF): "Стартовая масса ракеты – 1900 кг, масса с ТПК – 2580 кг" ([fs.guap.ru/uvc/meth/4_17.pdf](https://fs.guap.ru/uvc/meth/4_17.pdf)); [rusarmy.com](https://rusarmy.com/pvo/pvo_vvs/zur_5v55r_48n6e_48n6e2.html) gives 1800 (48N6E) / 1840 (48N6E2); [Air Power Australia](https://www.ausairpower.net/APA-Grumble-Gargoyle.html) gives 1800–1900 kg. The 1,500 kg on [astronautix](http://www.astronautix.com/4/48n6e.html) is an outlier and inconsistent with all Russian-language sources — discard. **Use 1,800–1,900; 1,835 kg is a good single number for an export E-round.** |
| Mass in TPK (canister) | 2,580–2,600 kg | — | Nevsky Bastion (2580); [missilery.info](https://en.missilery.info/missile/c300pmu1) (2600) |
| Length | **7.5 m** | 7.5 m universal | APA ("295.3 in"), Nevsky Bastion, rusarmy |
| Body diameter | **0.519 m** | 0.508–0.52 | APA ("20.4 in"), rusarmy |
| Tail fin span | **1.134 m** | — | APA ("44.65 in"), rusarmy |
| Tail fins | 4 all-moving (цельноповоротные), folding, clipped-delta | — | Nevsky Bastion: "четырьмя цельноповоротными, складывающимися управляющими поверхностями в хвостовой части" |
| Fin geometry (photo-derived estimate) | exposed semi-span per panel = (1.134−0.519)/2 ≈ **0.31 m**; root chord ≈ 1.0–1.2 m, tip chord ≈ 0.45–0.6 m, area ≈ **0.25–0.30 m² per panel** (~1.0–1.2 m² total) | estimate | Derived from span + proportions in launch photos/frames examined below; no source publishes chords |
| Nose | ogive ≈ 2.5–3 calibers ≈ **1.3–1.5 m**, then constant-section "несущий корпус" (lifting body, wingless) | estimate from drawings/photos | Nevsky Bastion (бескрылая схема / несущий корпус) |
| Warhead | 143–145 kg (48N6/E); 180 kg (48N6E2) | — | Nevsky Bastion (143), rusarmy (145/180), APA |
| Motor burn time | **up to 12 s**, single-mode ("однорежимный") solid | "<12 s" (APA), "до 12 с" (RU sources). 5.5 s claims found nowhere credible — pin **11–12 s** | Nevsky Bastion: "Время работы твердотопливного однорежимного маршевого двигателя до 12 секунд"; [vistat.org](https://vistat.org/objects/48n6-24f); APA |
| Burnout speed | 1,900–2,100 m/s, then coasts | — | Nevsky Bastion, vistat |
| Motor thrust | **~240–250 kN average** (derived, see §1.3) | 200–260 kN | derived; consistent with the "~200–250 kN" working assumption |
| Propellant mass | **~1,100–1,250 kg** (fraction 0.58–0.65) — derived §1.3, not published | — | derived (rocket equation) |
| CG | not published; **estimated 55% of length from nose (≈4.1–4.2 m)** at launch, moving forward ~0.3–0.5 m as propellant burns | — | mass-budget estimate §2 |
| Max load factor | 25 g | — | APA |
| Cold launch | catapult (pneumatic cylinders + pushrods driven by a gas generator, ПАД) ejects missile to **~25 m** (48N6) / ~20 m (5V55); fins unfold on tube exit; **motor ignites at near-zero vertical speed at apex** | 20–30 m across sources | Nevsky Bastion: "Старт... осуществляется с катапультированием на высоту 25 метров"; and for 5V55: "выбрасывается... на высоту около 20 метров... При достижении ракетой практически нулевой скорости запускается маршевый двигатель"; [ru.wikipedia С-300Ф](https://ru.wikipedia.org/wiki/%D0%A1-300%D0%A4) |
| TVC / declination mechanism | **Gas vanes (газовые рули) in the motor exhaust**, working per a pre-loaded autopilot program: roll the missile into the guidance plane, then pitch it over ("склонение"). APA notes "TVC vanes in the exhaust nozzle". Vane count is not published for 48N6; the 4 all-moving tail surfaces + the standard Russian practice (4 vanes ganged to the 4 tail actuators, as on 5V27/9M330 etc.) make **4 vanes** the confident assumption. Deflection range not published; jet-vane systems typically run ±20–25° vane deflection giving a few degrees of effective jet deflection ([jet-vane TVC literature](https://www.researchgate.net/publication/283661759_Numerical_Characterisation_of_Jet-Vane_based_Thrust_Vector_Control_Systems), [Wikipedia: Thrust vectoring](https://en.wikipedia.org/wiki/Thrust_vectoring) — 1–5% thrust loss typical) | — | Nevsky Bastion: "запускается маршевый двигатель и газовые рули по программе, заложенной в автопилот перед стартом, склоняют ракету в плоскость наведения и разворачивают ее... для скорейшего вывода на кинематическую траекторию ракета оснащена газовыми рулями, обеспечивающими ее энергичный разворот в направление на цель" |

Note the family contrast: the S-300V rounds (9M82/9M83) instead use **impulse declination motors (ИДС)** and are tossed to ~50 m ([MAI course page](https://files.mai.ru/site/unit/institute-of-military-science/tvvs/data/g4/4-1-3.html)); don't mix that mechanism into a P-series sim.

### 1.2 5V55 cross-check (older, lighter round)

| Parameter | 5V55K/KD | 5V55R | Source |
|---|---|---|---|
| Launch mass | 1,480–1,500 kg | 1,664–1,665 kg | Nevsky Bastion, APA, rusarmy |
| Length / diameter / span | 7.25 m / 0.508 m / 1.124 m | same | APA, rusarmy |
| Warhead | 133 kg | 130–196 kg (sources differ) | APA, rusarmy |
| Burn time | **8–10 s** | 8–10 s | Nevsky Bastion: "время работы которого 8-10 секунд"; APA |
| Burnout speed | ~1,900–2,000 m/s (M<6.7) | same | APA |
| Catapult apex / ignition | ~20 m, near-zero speed | same | Nevsky Bastion |

Implied 5V55 thrust ≈ (propellant ~850–950 kg)/(9 s) × 240 s × 9.81 ≈ **220–250 kN** — same thrust class as 48N6; the 48N6 simply burns ~2 s longer with ~25% more propellant. This cross-check supports the 48N6 estimates below.

### 1.3 Derived propulsion numbers (shown work)

- Burnout Δv (ideal) = burnout speed 2,000 m/s + gravity loss (~g·11 s·cos-weighted ≈ 90–110 m/s) + drag loss for a 0.52 m, M0–M6 low-altitude boost (~250–400 m/s) ≈ **2,350–2,500 m/s**.
- Modern composite solid Isp ≈ 235–250 s → mass ratio = e^(2400/2400) ≈ 2.6–2.8 → propellant fraction 0.61–0.64 → **m_p ≈ 1,100–1,250 kg** of 1,900 kg. (Take 1,150 kg.)
- Mass flow ≈ 1,150 kg / 11 s ≈ 105 kg/s → thrust = ṁ·Isp·g ≈ 105 × 240 × 9.81 ≈ **247 kN** (window 200–260 kN).
- Axial acceleration: ignition 247,000/1,900 ≈ **130 m/s² (13 g)**; burnout 247,000/750 ≈ 330 m/s² (34 g). Sanity check: ∫a dt with mass depletion reproduces ~2,000 m/s in 11 s. ✓

---

## 2. Pitch moment of inertia and gas-vane torque (the math)

### 2.1 I_yy estimate

Three-lump slender-body model (stations from nose, total 1,900 kg):

| Lump | Mass | Center | Extent (treated as rod) |
|---|---|---|---|
| Nose package (seeker/fuze/warhead/avionics) | 400 kg | 1.8 m | 2.0 m |
| Airframe, fins, actuators, cabling | 350 kg | 3.75 m | 7.5 m |
| Loaded motor (case + 1,150 kg propellant) | 1,150 kg | 5.1 m | 3.8 m |

- CG = (400·1.8 + 350·3.75 + 1150·5.1)/1900 = **4.16 m from nose (55% L)** — slender aft-heavy round, consistent with the big single motor.
- I_yy about CG = Σm·d² + Σ(m·ℓ²/12) = (400·2.36² + 350·0.41² + 1150·0.94²) + (400·2²/12 + 350·7.5²/12 + 1150·3.8²/12) = 3,300 + 3,160 ≈ **6,500 kg·m²** (radius of gyration 1.85 m = 0.25 L).
- Bounds: uniform rod mL²/12 = 8,900 kg·m² (upper); concentrated-center 5,500 (lower). **Use I_yy = 6,000–8,000 kg·m², nominal 6,500, scaling ∝ remaining mass.**

### 2.2 Gas-vane torque and achievable body pitch acceleration

- Vane station ≈ nozzle exit ≈ 7.5 m → moment arm to CG r ≈ **3.3–3.4 m** (≈ "half a length from CG" as expected).
- Jet-vane side force: 4-vane sets deliver an effective jet-deflection of a few degrees; side force F_s = T·sin(δ_eff). Literature puts usable δ_eff at 3–8° with 1–5% axial-thrust drag penalty ([jet-vane TVC studies](https://www.researchgate.net/publication/335212709_Experimental_and_Numerical_Investigation_of_a_Jet_Vane_of_Thrust_Vector_Control_System), [Wikipedia TVC](https://en.wikipedia.org/wiki/Thrust_vectoring)).
- Torque and body angular acceleration α = F_s·r / I_yy, with T = 247 kN, r = 3.3 m, I_yy = 6,500 kg·m²:

| Effective jet deflection | Side force | Torque | Body pitch accel |
|---|---|---|---|
| 1° | 4.3 kN | 14.2 kN·m | 2.2 rad/s² = **125 deg/s²** |
| 3° | 12.9 kN | 42.6 kN·m | 6.6 rad/s² = **375 deg/s²** |
| 6° | 25.8 kN | 85.2 kN·m | 13.1 rad/s² = **750 deg/s²** |

**Key insight: vane authority is not the limit.** Even ~1° of effective jet deflection produces >100 deg/s² of body pitch acceleration. The observed gentle tip-over (§3) means the *autopilot program* limits the rate (structural loads, guidance capture, keeping AoA bounded as q builds) — so a sim should enforce a commanded-rate cap, not an authority cap.
- A plausible **sustained body pitch rate**: footage (§3) shows the autopilot holds ~30–45 deg/s during an aggressive declination; spin-up to that rate takes ~0.4–0.5 s → effective commanded α ≈ **80–150 deg/s²**, i.e. δ_eff under 1° most of the time.

Assumptions stated: rigid body; thrust constant 247 kN; vanes at nozzle exit; CG fixed at 55% L during the 2 s of interest (propellant burned in first 2 s ≈ 210 kg, CG shift < 0.1 m — negligible); aerodynamic damping ignored (small at v < 200 m/s); gravity does not torque the body (acts at CG).

---

## 3. Footage-derived tip-over rates (decisive evidence)

Method: clips downloaded at native frame rate, frame-stepped with ffmpeg, body/trail angle vs frame vertical estimated visually per frame (±5° accuracy; fixed-camera clip preferred for measurement).

### Clip A (primary, fixed wide camera): Ukrainian/Russian range footage, two S-300P launches — [youtube.com/watch?v=bQ_NDM-NMMk](https://www.youtube.com/watch?v=bQ_NDM-NMMk) (854×480, 30 fps, 12 s, fixed tripod-style framing; @Blue_Sauron watermark)

This is a **low-elevation, long-range war-shot profile** (large programmed turn). Second launch, frame-timed (t = video time):

| t (s) | t after ignition | Body angle from vertical | Note |
|---|---|---|---|
| ~2.5 | — | 0° | catapult ejection puff at canister mouth |
| 2.8–2.93 | — | 0° | coasting up, ~25–30 m apex (body clearly visible) |
| **3.05** | 0 | 0° | **motor ignition** (flame appears), still vertical |
| 3.33 | +0.3 | ~3–5° | rate building |
| 3.47 | +0.4 | ~14° | hard pitch-over visible (body kinks over the flame) |
| 3.73 | +0.7 | ~24° | |
| 4.00 | +0.95 | **~30°** | climbing fast |
| 4.53 | +1.5 | **~50°** (trail head) | |
| 5.07 | +2.0 | **~60–65°** (trail head) | converging on programmed climb angle |

- **Ignition → 30°: ~0.95 s → average 32 deg/s.** 30° → 60°: ~1.0 s → **~30 deg/s.** Peak instantaneous (0.4–0.8 s window): **~40–45 deg/s**. Rate ramp 0→40 deg/s in ~0.4 s → **~80–100 deg/s² body pitch acceleration**.
- Geometry: 30° point at roughly 90–130 m altitude (v ≈ 60–130 m/s building at ~13 g); 60° point ≈ 300–400 m altitude, ~100–200 m downrange. First launch in the same clip shows an identical trail signature (~45° by +1.3 s, ~55° by +2 s).

### Clip B (panning camera): Greek S-300PMU1, first Greek live fire, NAMFI/Crete, 13-12-2013 — [youtube.com/watch?v=tMflHb6fHxQ](https://www.youtube.com/watch?v=tMflHb6fHxQ) (640×360, 25 fps)

This is a **near-vertical engagement** (high target over the range → small programmed turn): ejection at t≈96.0, ignition ≈96.9; ~5° at 97.2; ~15–18° at 98.0; ~25° at 98.8; **~30–33° at 99.6 (+2.7 s)**; then the attitude *holds* ~25–30° through t≈103+ — the turn is complete. Average **~10–12 deg/s**, peak ~15–20 deg/s. (Panning camera → treat as approximate; the qualitative contrast with Clip A is the point.)

### Clip C (montage, qualitative): "S-400 Triumf SAM in action" — [youtube.com/watch?v=qMO0F19Gmpk](https://www.youtube.com/watch?v=qMO0F19Gmpk) (24.98 fps, 49 s)

Cut-heavy montage (unusable for precise timing): shows the canonical sequence — cold ejection, ~1–1.5 s coast with visible attitude hold, ignition kick, then climb-out angles of ~30–45° established within ~2 s on war-shot launches. Consistent with Clip A.

**Conclusion from footage: body pitch rate during the declination is ~30–45 deg/s in an aggressive low-elevation shot (30° at ~1 s, 60° at ~2 s after ignition) and only ~10–15 deg/s / ~25–30° total in a near-vertical engagement. Nothing approaching 120 deg/s appears in any clip.**

---

## 4. PATH vs BODY in the first 3 seconds

The body can pitch quickly (it's almost a pure attitude rotation at near-zero airspeed), but the **flight path** only turns as fast as lateral force allows: ω_path = a_lat / v, where a_lat = T·sin(α_AoA)/m (+ small aero lift + gravity component g·sin(θ) pulling the velocity vector over).

With T = 247 kN, m = 1,900 kg (T/m = 130 m/s²):

| AoA | a_lat (thrust only) | ω_path @ v=50 m/s | @ 100 m/s | @ 200 m/s |
|---|---|---|---|---|
| 10° | 22.6 m/s² | 26 deg/s | 13 | 6.5 |
| 15° | 33.6 m/s² | 38.5 deg/s | 19 | 9.6 |
| **18° (recommended)** | **40.1 m/s²** | **46 deg/s** | **23** | **11.5** |
| 20° | 44.5 m/s² | 51 deg/s | 25.5 | 12.7 |

(Add ~g·sin θ/v ≈ +3–6 deg/s at v=50, +1.5–3 at 100 when already tilted 30–60°.)

So the correct picture for the first 3 s after ignition: the body leads (pitches to put ~15–20° AoA between body and the still-mostly-vertical velocity vector), and the path follows, turning fastest (~40–50 deg/s) in the brief window when v ≈ 40–80 m/s, decaying as 1/v. Because v grows at ~13 g, that window lasts well under a second — which is exactly why real launches look like a quick energetic "lean" that then straightens into a fast climb, not a continuous fast arc. Mid-boost (v ≈ 400+ m/s) the same AoA only bends the path ~5–6 deg/s, and the missile flies the programmed "kinematic trajectory" per the autopilot (Nevsky Bastion).

---

## 5. Verdict on the current sim

**120 deg/s path rotation is unphysical — roughly 3× too fast.** To rotate the *path* at 120 deg/s at even v = 100 m/s requires a_lat = v·ω = 209 m/s² ≈ 21 g of lateral acceleration at near-zero dynamic pressure. Thrust-borne lateral force maxes out at T/m ≈ 13 g *even if the motor pointed fully sideways*; at a realistic 18–20° AoA it's ~4.5 g. The creative director is right: the missile pitches over too fast.

**Realistic single-number range: body pitch rate 35–50 deg/s (peak), with the path turn capped by a_lat = T·sin(18–20°)/m.** That reproduces both observed regimes: war shot (30° at ~1 s, 60° at ~2 s after ignition) and near-vertical shot (~25–30° total at 10–15 deg/s) just by changing the commanded final climb angle.

---

## RECOMMENDED CONSTANTS (48N6E-class round)

| Sim parameter | Value | Range / note |
|---|---|---|
| Launch mass m₀ | 1,835 kg | 1,800–1,900 (48N6 domestic = 1,900) |
| Dry mass | 700 kg | 650–800 |
| Propellant mass | 1,135 kg | 1,100–1,250 (fraction ~0.62) |
| Length / diameter / fin span | 7.5 / 0.519 / 1.134 m | fixed |
| Fin area (4 clipped-delta panels) | 0.27 m² each | 0.25–0.30 (photo-derived) |
| Motor thrust (constant, single-mode) | 245 kN | 200–260 kN |
| Burn time | 11 s | 11–12 s ("до 12 с") |
| Burnout speed | ~2,000 m/s | 1,900–2,100 |
| I_yy (pitch, at launch) | 6,500 kg·m² | 6,000–8,000; scale ∝ mass |
| CG | 55% of length from nose | drifts <0.1 m in first 2 s |
| Catapult ejection velocity | 25 m/s vertical | apex 25–30 m |
| Coast before ignition | 1.0–1.5 s | ignite at near-zero vertical speed |
| TVC | 4 jet vanes in exhaust | effective jet deflection ≤ ~3–6°; authority is NOT the limiter |
| **Body pitch angular accel (commanded cap)** | **100 deg/s²** | 80–150 (hardware could do 300+, autopilot doesn't) |
| **Body pitch rate max** | **45 deg/s** | 35–50 war shot; 15–20 near-vertical engagement |
| **Max effective AoA during boost turn** | **18°** | 15–20° |
| **Lateral accel cap during boost** | **a_lat = T(t)·sin(18°)/m(t)** ≈ 40 m/s² at ignition | path rate = a_lat/v, additionally ≤ body rate |
| Programmed final climb angle (from vertical) | 25–35° (high/close target); 50–70° (low-elevation long-range) | select per engagement |
| Tip-over timeline target (war shot) | 30° at ~1.0 s, 60° at ~2.0 s after ignition | matches Clip A |
| Total declination duration | 1.5–2.5 s | then pure programmed climb |

### Source list
- Nevsky Bastion S-300 supplement (decoded from CID-encoded PDF): https://fs.guap.ru/uvc/meth/4_17.pdf
- Air Power Australia, Grumble/Gargoyle technical report: https://www.ausairpower.net/APA-Grumble-Gargoyle.html
- RusArmy 5V55R/48N6E/48N6E2 data: https://rusarmy.com/pvo/pvo_vvs/zur_5v55r_48n6e_48n6e2.html
- Missilery.info S-300PMU-1: https://en.missilery.info/missile/c300pmu1
- vistat.org 48N6: https://vistat.org/objects/48n6-24f
- Wikipedia С-300Ф (20 m ignition height, gas-dynamic rudders): https://ru.wikipedia.org/wiki/%D0%A1-300%D0%A4
- MAI military-science page (S-300V: 50 m toss, impulse declination motors): https://files.mai.ru/site/unit/institute-of-military-science/tvvs/data/g4/4-1-3.html
- Astronautix 48N6E (mass figure rejected as outlier): http://www.astronautix.com/4/48n6e.html
- Weaponsystems.net 48N6: https://weaponsystems.net/system/1417->>48N6
- Jet-vane TVC literature: https://www.researchgate.net/publication/283661759_Numerical_Characterisation_of_Jet-Vane_based_Thrust_Vector_Control_Systems ; https://en.wikipedia.org/wiki/Thrust_vectoring
- Footage: https://www.youtube.com/watch?v=bQ_NDM-NMMk (fixed-camera S-300P war shots, frame-timed); https://www.youtube.com/watch?v=tMflHb6fHxQ (Greek S-300PMU1, NAMFI 2013); https://www.youtube.com/watch?v=qMO0F19Gmpk (S-400 montage)
