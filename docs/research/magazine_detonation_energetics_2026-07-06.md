# Magazine Detonation Energetics — Normative Research

**Doc:** `docs/research/magazine_detonation_energetics_2026-07-06.md`
**Date:** 2026-07-06
**Status:** NORMATIVE — the RECOMMENDED CONSTANTS TABLE (§6) is the source of truth for the game's catastrophic-kill / magazine cook-off model. Every claim below carries an inline URL. Where sources disagree, both are shown and the better-evidenced one is marked **[PREFERRED]**.

> Design intent reminder (project memory): combat outcomes must emerge from **simulated physics + measured statistical bands, never flat probability rolls**. This doc therefore delivers *energy* and *timing* constants, and a **probability-free** cook-off trigger rule (fire-intensity threshold + dwell time), NOT a "detonation %" die roll like War Thunder uses.

---

## 1. Per-Round Energetics

### 1.1 SM-2 (RIM-66 / RIM-156) — warhead

- The SM-2MR (RIM-66) family evolved through several blast-fragmentation warheads: MK 51 continuous-rod (SM-1, ~62 kg / 137 lb), MK 90, MK 115, and the current **MK 125 blast-fragmentation** with "heavier grain explosive" on SM-2MR Block IIIA and later. Total SM-2MR round mass ~621 kg (1,370 lb). [designation-systems.net RIM-66](https://www.designation-systems.net/dusrm/m-66.html)
- MK 125 warhead mass is reported inconsistently across open sources: **~115 kg (253 lb)** (whole-warhead assembly, forum/document citations) vs **~60–64 kg (137–141 lb)** (a figure that likely reflects the section or a lighter measure). The discrepancy is attributed to whether the number counts explosive fill only, fill + casing, or fill + casing + target-detecting device. [weaponsystems.net / Missile Threat summary via search](https://missilethreat.csis.org/defsys/standard-missile-2-block-iv/)
- The SM-6 (RIM-174) uses the **same MK 125 warhead**, cited consistently as **64 kg (140–141 lb) blast-fragmentation**, proximity/impact fuzed (Mk 45 Mod 9 class fuze). [designation-systems.net RIM-174](https://www.designation-systems.net/dusrm/m-174.html), [en.missilery.info Standard-6](https://en.missilery.info/missile/standard-6)

**Resolution for the game:** treat the MK 125 **warhead assembly as ~64 kg**, of which the **net explosive quantity (NEQ) of high-explosive fill is ~20–25 kg** (a blast-frag warhead is a thick fragmenting steel case; explosive is typically 30–40% of warhead mass). This bracket is consistent with the MK 125 being a ~64 kg warhead and with comparable blast-frag AAW warheads. (Open sources do not publish the exact HE fill of MK 125; the 30–40% case-fraction is the standard rule for fragmenting warheads — see IATG guidance on NEQ, [UNSaferGuard IATG 01.80](https://data.unsaferguard.org/iatg/en/IATG-01.80-Formulae-ammunition-management-IATG-V.3.pdf).) Mark this value **[ESTIMATED — no public exact NEQ]**.

### 1.2 SM-2 / SM-6 — rocket motor (the dominant energy store)

The **MK 104 dual-thrust rocket motor (DTRM)** is the sustainer common to SM-2, SM-3 and SM-6; the SM-6/some SM-2ER variants add a **MK 72 booster** as first stage. [prnewswire X-Bow MK 72/MK 104](https://www.prnewswire.com/news-releases/x-bow-systems-to-build-mk-72-and-mk-104-standard-missile-rocket-motors-for-us-navy-302175738.html)

MK 104 mass figures (astronautix, via search — primary page was intermittently unreachable but the numbers were returned):
- Gross mass **~500 kg (1,100 lb)**, unfuelled/empty **~128 kg (282 lb)** → **propellant mass ≈ 372 kg**. [astronautix MK 104 (via search)](http://www.astronautix.com/m/mk104.html)

> Caveat: 372 kg is a large propellant load; some references treat the MK 104 sustainer grain as smaller and the "gross 500 kg" as including hardware/nozzle. Treat **MK 104 propellant as 230–370 kg** and default to **~250 kg** for a single-round sustainer for the game unless modeling SM-6 with booster. The MK 72 booster adds roughly another **250–360 kg** of propellant (RIM-174A/B total 1,500 kg vs AIM-174B 860 kg without booster — a ~640 kg booster stage). [designation-systems.net RIM-174](https://www.designation-systems.net/dusrm/m-174.html)

**Propellant type & energy content:** SM-family motors use **AP/HTPB composite** (ammonium perchlorate oxidizer + hydroxyl-terminated polybutadiene binder, usually aluminized), a **Hazard Division 1.3** propellant (mass-fire hazard, not mass-detonation). [ResearchGate AP/HTPB composite propellants](https://www.researchgate.net/publication/270663705_Solid_propellants_APHTPB_composite_propellants)

- Combustion (deflagration) heat of AP/HTPB composite: **~6.7–7.5 MJ/kg** (heat of decomposition ~7.08 MJ/kg reported). [tandfonline HTPB/ADN combustion](https://www.tandfonline.com/doi/full/10.1080/00102202.2025.2563123)
- For blast/hazard purposes, Class 1.3 solid rocket propellant is assigned a **TNT-equivalence factor ≈ 1.3** (i.e., detonating/violent-reacting propellant ≈ 1.3× its mass in TNT for airblast). Standard deflagration produces overpressure **without** true detonation. [DTIC ADA507382 — Explosive Testing of Class 1.3 Rocket Booster Propellant (via search)](https://apps.dtic.mil/sti/tr/pdf/ADA507382.pdf)

**Key physical point for the game:** the rocket **motor propellant, not the warhead, is the largest chemical-energy store per round** (hundreds of MJ). But 1.3 propellant normally **deflagrates (burns fast, vents)** rather than detonates. It only approaches a TNT-like detonation under strong confinement + shock (sympathetic detonation from an adjacent warhead going high-order). This is exactly the SM-2/SM-6 magazine story: warhead HE can detonate; motor propellant mostly *burns hard and vents*, unless confined and shocked.

### 1.3 Mk 41 VLS cell — venting design (does a VLS fire become a hull-killer?)

The Mk 41 is **explicitly engineered to vent a restrained firing / cook-off UP and OUT**, away from the hull:

- Cells are grouped in **8-cell modules (2 rows of 4) sharing a common uptake hatch (exhaust plenum)** between the rows. The plenum/uptake captures motor exhaust and vents it **vertically to atmosphere**. [globalsecurity.org MK 41 VLS](https://www.globalsecurity.org/military/systems/ship/systems/mk-41-vls.htm)
- The plenum is rated to withstand **7 normal launches from a cell PLUS a full-burn restrained firing from any other cell** — i.e., a stuck missile burning its entire grain inside its canister is a *designed-for* case, vented upward. [globalsecurity.org MK 41 VLS](https://www.globalsecurity.org/military/systems/ship/systems/mk-41-vls.htm)
- **Restrained-firing / cook-off protection:** if restraint bolts don't release after ignition, an **overtemperature sensor** triggers a **water deluge** into the canister (fresh then seawater) to cool it; the uptake vents the exhaust. [globalsecurity.org MK 41 VLS](https://www.globalsecurity.org/military/systems/ship/systems/mk-41-vls.htm)
- Each canister is an armored sealed tube, so a single missile's motor fire is meant to stay in-cell and vent up.

**Design consequence (normative):** In the ONIKS model, a Mk 41 VLS fire should **default to an upward-venting deflagration jet (survivable, spectacular column of flame/smoke out the deck), NOT an instant hull-killing detonation.** The catastrophic hull-kill path requires **defeating the venting design**: (a) a warhead going **high-order** and shocking neighbors into **sympathetic detonation** faster than the plenum can cope, or (b) sustained multi-cell cook-off overwhelming the deluge/uptake so that many rounds fire/detonate near-simultaneously. This is the branch that turns a "deck torch" into a "magazine goes." (Contrast: older non-vented Soviet-style magazines like Moskva's had no equivalent upward vent path — see §3.1.)

---

## 2. Scaling Law — many rounds cooking off

### 2.1 Two regimes

1. **Sequential deflagration / cook-off (the common case):** rounds burn/vent one-by-one or in loose clusters at intervals. Energy is released **spread over time**; peak blast is governed by however many rounds go **near-simultaneously**, not the whole magazine at once. Historical cook-off timing (Forrestal, §3.5) shows discrete explosions seconds-to-minutes apart, not one sum. [insensitivemunitions.org Forrestal](http://www.insensitivemunitions.org/history/the-uss-forrestal-cva-59-fire-and-munition-explosions/)
2. **Sympathetic detonation (the catastrophic case):** one warhead detonates high-order; its shock + fragments drive **adjacent** rounds to detonate essentially simultaneously (µs–ms), so their NEQ **adds**. This is the "magazine goes" instant-loss regime (Hood, §3.4). [Wikipedia — Sympathetic detonation](https://en.wikipedia.org/wiki/Sympathetic_detonation)

The **whole magazine only sums into one yield when sympathetic detonation propagates through all of it.** Insensitive-munitions design (less-sensitive fills, shock barriers between rounds) exists precisely to *break* that propagation and force regime 1. [globalsecurity.org Insensitive Munitions](https://www.globalsecurity.org/military/systems/munitions/im.htm)

### 2.2 TNT-equivalence math

For `n` rounds, per-round explosive net quantity `NEQ_round` (kg HE), converted to TNT-eq via a factor `k_TNT` (HE→TNT airblast factor; ~1.0–1.3 for typical warhead HE, ~1.3 for 1.3-class propellant if it detonates):

```
Effective TNT-eq yield (kg TNT):
   W_tnt(n) = participation(n) · n · NEQ_round · k_TNT
```

where `participation(n) ∈ (0,1]` is the fraction of rounds that go **coherently (within one blast window)**:
- Pure sympathetic detonation (all-adjacent): `participation → 1.0` (full sum).
- Sequential cook-off (spread in time): effective simultaneous participation is **small**, often modeled as **only the rounds within one shock radius / one time window**, e.g. `participation ≈ min(1, m/n)` with `m` = rounds in the near-field cluster.

A defensible game closed form that captures "more rounds = bigger, but with diminishing coherent participation":

```
W_tnt(n) = NEQ_round · k_TNT · ( c_sym · n  +  (1 - c_sym) · n^0.5 )
```
- `c_sym` = sympathetic-coupling coefficient (0 = everything just burns sequentially, blast grows like √n; 1 = full sympathetic detonation, blast grows linearly with n).
- Set `c_sym` from magazine type: modern insensitive-munition VLS with venting → **low c_sym (~0.1–0.2)**; old confined non-vented magazine → **high c_sym (~0.7–0.9)**.

### 2.3 Fireball / blast radius from yield (Hopkinson-Cranz)

- **Cube-root (Hopkinson-Cranz) scaling** is the governing law: similar blast effects occur at equal **scaled distance** `Z = R / W_tnt^(1/3)` (R in m, W in kg TNT). Doubling yield grows any given effect radius by only **2^(1/3) = 1.26×**. [ScienceDirect — Scaled Distance](https://www.sciencedirect.com/topics/engineering/scaled-distance), [vcalc — Hopkinson-Cranz](https://www.vcalc.com/wiki/hopkinson-cranz-scaling-law-range)
- **Damage/effect radius:** `R_effect = Z_target · W_tnt^(1/3)`, pick `Z_target` for the overpressure you want to draw (e.g. Z≈5–10 m/kg^1/3 for structural damage bands).
- **Visible fireball radius (conventional HE), empirical fit:** `R_fireball ≈ 3.0–4.7 · W_tnt^0.33–0.375` (m, W in kg TNT). A widely quoted conventional-HE fit is **R = 4.7 · W^0.375**; a cube-root simplification **R ≈ 3.5 · W^(1/3)** is defensible for a game. [search: conventional HE fireball fits](https://www.omnicalculator.com/physics/blast-radius) (nuclear surface-burst analog: R ≈ 130·W^(1/3) m with W in **kilotons** — do NOT use for chemical yields; shown only to confirm the cube-root exponent). [Wikipedia — Nuclear weapon yield](https://en.wikipedia.org/wiki/Nuclear_weapon_yield)

---

## 3. Historical Cases (what actually happens when a magazine goes)

### 3.1 Moskva (14 Apr 2022) — magazine fire → loss [PREFERRED modern analog for the ONIKS enemy back-plot]
- **Hit:** 2× R-360 Neptune subsonic sea-skimming ASCMs, **port side**, causing a strong roll; ship's air defense was distracted by a Bayraktar TB-2 decoy. [Wikipedia — Sinking of the Moskva](https://en.wikipedia.org/wiki/Sinking_of_the_Moskva)
- **What burned/detonated:** missile impacts → **fire → fire reached onboard ammunition, which exploded** (Russia's own account). Moskva's P-1000 Vulkan ASCMs and SAM magazines were large and **not vented upward like a Mk 41**. [Wikipedia — Sinking of the Moskva](https://en.wikipedia.org/wiki/Sinking_of_the_Moskva)
- **Timeline:** SOS ~01:05; **rolled onto her side ~01:14**; power lost ~30 min later; crew (~500) evacuated under "threat of detonation of ammunition"; sank **14 Apr** under tow in stormy seas. Largest Russian warship lost in wartime since WWII. [Wikipedia — Sinking of the Moskva](https://en.wikipedia.org/wiki/Sinking_of_the_Moskva), [USNI News](https://news.usni.org/2022/04/13/russian-navy-confirms-severe-damage-to-black-sea-cruiser-moskva-crew-abandoned-ship)
- **Damage control:** ineffective — fire propagation to magazines + heavy sea state + list overwhelmed it.

### 3.2 USS Stark (17 May 1987) — 2 Exocets, one dud — burned, survived
- **Hit:** 2× AM39 Exocet from an Iraqi Mirage F1. **First missile did NOT explode** but spewed burning rocket propellant through berthing/post office/store; **second detonated as designed.** [Wikipedia — USS Stark incident](https://en.wikipedia.org/wiki/USS_Stark_incident)
- **What burned:** unburned Exocet propellant fire (~3,500 °F) gutted crew quarters, radar room, CIC. Fire burned **almost a full day.** [Wikipedia — USS Stark incident](https://en.wikipedia.org/wiki/USS_Stark_incident)
- **Damage control / survival:** captain **counter-flooded the starboard side** to keep the port-side hole above water; crew DC saved the ship; reached Bahrain next day. **37 dead, 21 injured.** Classic "hit + propellant fire but no magazine detonation → saved by DC." [Wikipedia — USS Stark incident](https://en.wikipedia.org/wiki/USS_Stark_incident)

### 3.3 HMS Sheffield (4–10 May 1982) — Exocet, propellant fire, mission-killed, sank under tow
- **Hit:** 1× air-launched Exocet, starboard amidships. **Whether the warhead detonated was long debated**; a **2015 MoD reassessment concluded it DID detonate**; regardless, damage was dominated by **unburned propellant fire** + kinetic energy of a 660 kg missile. [Wikipedia — HMS Sheffield (D80)](https://en.wikipedia.org/wiki/HMS_Sheffield_(D80)), [Navy Lookout](https://www.navylookout.com/in-perspective-the-loss-of-hms-sheffield/)
- **Timeline:** hit 4 May → **mission-killed / abandoned same day** (fire fed by fuel + cabling, no firemain pressure) → drifted, taken under tow → **rolled and sank 10 May** through the hull hole in high seas. **20 dead.** [Wikipedia — HMS Sheffield (D80)](https://en.wikipedia.org/wiki/HMS_Sheffield_(D80))
- **Lesson:** even without a magazine going, a single ASCM propellant fire can be a slow-loss kill days later.

### 3.4 HMS Hood (24 May 1941) — magazine detonation, instant loss [canonical instant-kill]
- **Hit:** 15-inch shell(s) from Bismarck penetrated to an **after magazine**; cordite detonation. [Wikipedia — HMS Hood](https://en.wikipedia.org/wiki/HMS_Hood)
- **Timeline:** the explosion **broke the ship's back; she sank in ~3 minutes**; last sight was the bow near-vertical. **1,415 of 1,418 died (3 survivors).** [Wikipedia — HMS Hood](https://en.wikipedia.org/wiki/HMS_Hood), [Britannica — HMS Hood](https://www.britannica.com/topic/HMS-Hood)
- **Lesson:** full sympathetic magazine detonation = near-instantaneous total loss. This is the `participation → 1.0`, `c_sym → high` regime.

### 3.5 USS Forrestal (29 Jul 1967) — deck fire → sequential bomb cook-off [best cook-off TIMING data]
- **Ignition:** stray **5-inch Zuni rocket** fired on deck (power-surge), ruptured a fuel tank → JP-5 fire; **Zuni warhead safety prevented its own detonation.** [Wikipedia — 1967 USS Forrestal fire](https://en.wikipedia.org/wiki/1967_USS_Forrestal_fire)
- **Cook-off timing (gold for sequential model):** first **750-lb M117 (Composition B) bomb detonated ~90 seconds after fire start**, killing most firefighters; **major explosions continued for ~5.5 minutes**; fires took **~10 hours** to fully extinguish. **134 dead.** [Wikipedia — 1967 USS Forrestal fire](https://en.wikipedia.org/wiki/1967_USS_Forrestal_fire), [insensitivemunitions.org — Forrestal](http://www.insensitivemunitions.org/history/the-uss-forrestal-cva-59-fire-and-munition-explosions/)
- **Lesson:** thin-cased old bombs cook off in **~90 s of direct flame**, then a **burst cluster over ~5 min** — discrete detonations, not one sum. Use these numbers for the ONIKS cook-off cadence.

### 3.6 USS Samuel B. Roberts (14 Apr 1988) — mine, survived via damage control [DC-saves-the-ship canon]
- **Hit:** Iranian moored contact mine; **15-ft hull hole, flooded engine room, keel broken** (structural damage usually fatal). [USNI News — Sammy B](https://news.usni.org/2015/05/22/the-day-frigate-samuel-b-roberts-was-mined), [Wikipedia — USS Samuel B. Roberts (FFG-58)](https://en.wikipedia.org/wiki/USS_Samuel_B._Roberts_(FFG-58))
- **Survival:** crew fought fire+flooding **~5 hours**, cinched cables across the cracked superstructure to hold it together; saved a ship that fleet engineers **couldn't keep afloat even in simulation.** No magazine involvement. [USNI News — Sammy B](https://news.usni.org/2015/05/22/the-day-frigate-samuel-b-roberts-was-mined)
- **Lesson:** heroic DC can defeat even keel-breaking damage **if the magazine doesn't go.** Magazine involvement is the difference between §3.6 (saved) and §3.4 (instant loss).

### 3.7 Port Chicago (17 Jul 1944) — TNT-scaling calibration point
- Munitions-ship explosion equivalent to roughly **~1.6–2 kt TNT** from ~1,780 tons of ordnance loading; useful only as a **far-field cube-root anchor** for "entire ship magazine sympathetic-detonates" (extreme upper bound; far beyond a single VLS). Cite as the ceiling of the scaling curve. [Wikipedia — Port Chicago disaster](https://en.wikipedia.org/wiki/Port_Chicago_disaster)

---

## 4. Video / Visual References (build particles WITHOUT watching)

### 4.1 Moskva damage photos (Apr 2022)
- Two low-res geolocated photos + short clip surfaced ~18 Apr on a Ukrainian SIGINT Telegram channel; republished by CNN, Moscow Times, Stars & Stripes. [CNN — new Moskva photos](https://www.cnn.com/2022/04/18/europe/ukraine-moskva-warship-sinking-images-intl/index.html), [Stars & Stripes](https://www.stripes.com/theaters/europe/2022-04-18/photos-show-stricken-russian-ship-on-fire-possibly-confirm-ukrainian-missile-strike-5722704.html)
- **Visual signature:** large warship **listed to port**, **thick black/grey smoke column** billowing from amidships/port, ship **low in the water**, **all life rafts deployed** (crew gone). No visible active fireball in the surfaced stills — this is the **post-detonation smoldering/listing phase**, hours after the magazine event. Smoke is **sooty black (fuel/rubber/propellant)** grading to grey; the column leans downwind and flattens near sea surface. [CNN](https://www.cnn.com/2022/04/18/europe/ukraine-moskva-warship-sinking-images-intl/index.html)

### 4.2 USS Forrestal deck cook-off footage (1967)
- Extensively filmed by ship's PLAT camera; used as a Navy firefighting training film. [Wikipedia — 1967 USS Forrestal fire](https://en.wikipedia.org/wiki/1967_USS_Forrestal_fire)
- **Visual signature:** initial **orange JP-5 pool fire** spreading across the flight deck with **rolling black smoke**; then **sharp white/orange bomb detonations** at intervals (first ~90 s, then a cluster over ~5 min) each throwing a **hemispherical flash + debris fan + shockwave ring across the fuel sheet**; each blast momentarily **clears then re-ignites** the pool. Persistent **greasy black column** rising hundreds of feet. Secondary blasts are **discrete, punctuated**, seconds-to-tens-of-seconds apart — NOT a single big fireball. [insensitivemunitions.org — Forrestal](http://www.insensitivemunitions.org/history/the-uss-forrestal-cva-59-fire-and-munition-explosions/)

### 4.3 SINKEX missile-hit footage (Harpoon / LRASM on target hulls, RIMPAC)
- Public releases: RIMPAC 2024 sinkings of ex-USS Tarawa (LRASM from F/A-18F) and ex-USS Dubuque; NZ P-8A Harpoon hits; B-2 LRASM SINKEX 2026. [The War Zone — missiles clobber RIMPAC frigate](https://www.twz.com/watch-missiles-clobber-a-mothballed-u-s-navy-frigate-during-rimpac), [Maritime Executive — SINKEX video](https://maritime-executive.com/article/video-sinkex-live-fire-at-rimpac-sinks-us-guided-missile-frigate), [USNI News — Harpoon SINKEX](https://news.usni.org/2018/07/30/navy-may-bring-back-harpoon-missiles-on-attack-subs-after-successful-sinkex-rimpac-also-highlights-ground-to-ship-strike-capability)
- **Visual signature (subsonic ASCM on empty hull):** on impact a **brief bright orange-white flash** at the hull, a **compact fireball ~1–2 hull-heights** that collapses within ~1 s, punching a **ragged entry hole** and throwing **spray + fragments + a puff of grey-black smoke**; then a **lingering smoke plume** from the internal fire rather than a sustained fireball. Target ships often **absorb multiple hits and stay afloat for hours** (no live magazine aboard — the drama is the smoke column + slow list, echoing Moskva). [The War Zone](https://www.twz.com/watch-missiles-clobber-a-mothballed-u-s-navy-frigate-during-rimpac)

### 4.4 VLS restrained-firing / cook-off tests
- Mk 41 hot-restrained-firing and plenum qualification are described (not always filmed publicly), but the **design behavior** is documented: full-burn restrained firing vents up through the uptake hatch. [globalsecurity.org MK 41 VLS](https://www.globalsecurity.org/military/systems/ship/systems/mk-41-vls.htm)
- **Visual signature to build:** a **sustained vertical roaring jet of orange flame + white-hot exhaust + dense smoke erupting straight up out of the deck hatch** for the burn duration (seconds), like a **blowtorch geyser**, NOT a spherical detonation. This is the "survivable VLS fire" effect. Escalation to catastrophic = the jet is joined by **lateral secondary flashes** as neighbors cook off, then a **larger low-order deck rupture**.

---

## 5. War Thunder Naval Mechanics (design grounding — a foil, not a model to copy)

- **Ammo/magazine module:** magazines are **non-linear** — "when a magazine is destroyed it will normally **detonate**, causing catastrophic damage that often renders the ship inoperable." Detonation triggers at the module's **destroyed (black) state**. [wiki.warthunder.com — ship modules](https://wiki.warthunder.com/mechanics/5245-ship-modules)
- **Direct hit vs fire→magazine:** you can detonate racks/magazines with torpedoes, mines, depth charges or shells reaching the module; each module's **resistance to damage, to fire, and its explosion effect is set individually per vessel**, giving big survivability variance. [old-wiki.warthunder.com — Ammo racks (via search)](https://old-wiki.warthunder.com/Ammo_racks)
- **Probabilistic ignition:** WT uses a **separate "chance to cause a fire" setting** from the explosive setting on fire-vulnerable modules (simulating tracer/spark ignition) — i.e., WT explicitly rolls dice for fire and for detonation. [old-wiki.warthunder.com — Ammo racks (via search)](https://old-wiki.warthunder.com/Ammo_racks)
- **Does remaining ammo matter?** Community/official discussion indicates allocated/remaining ammunition load can influence detonation likelihood/severity, but WT does **not** transparently sum remaining-round yield; blast is a per-module scripted effect, not a physics sum. [forum.warthunder.com — ammunition allocated effect on detonation](https://forum.warthunder.com/t/clarification-on-ammunition-allocated-having-an-effect-on-detonation-likelihood/61100)
- **Crew + unsinkability:** buoyancy = displacement; hull breaches admit water; hull is split into **watertight compartments**; flooded compartments **reduce buoyancy proportionally**; DC is a **two-stage patch-then-pump** loop; **buoyancy shown as a %** and you sink when it hits **0% or you list too far too long.** Separately, a ship is **destroyed instantly when free crew hits 0%.** [wiki.warthunder.com — Ship Crew Mechanics](https://wiki.warthunder.com/640-ship-crew-mechanics), [forum.warthunder.com — Buoyancy Critical](https://forum.warthunder.com/t/buoyancy-critical-trash-in-naval/36805)

**Takeaway for ONIKS:** adopt WT's **buoyancy-%/compartment-flooding/DC-loop** framing (it's a good physics-flavored sinking model) but **REJECT WT's dice-roll detonation**. Per project memory ("physics not dice"), our magazine event must fire on a **deterministic energy/fire-intensity threshold**, and the blast should be a **physics sum** (§2) so remaining rounds genuinely matter — the thing WT hides.

---

## 6. RECOMMENDED CONSTANTS TABLE (source of truth)

| Constant | Value | Basis / cite |
|---|---|---|
| MK 125 warhead mass (SM-2 Blk III+/SM-6) | **64 kg** assembly | [designation-systems RIM-174](https://www.designation-systems.net/dusrm/m-174.html) |
| **Per-SM-2/SM-6 warhead NEQ** | **~22 kg TNT-eq** (band 20–25) **[ESTIMATED]** | 30–40% HE case-fraction of a 64 kg blast-frag WH; [IATG 01.80](https://data.unsaferguard.org/iatg/en/IATG-01.80-Formulae-ammunition-management-IATG-V.3.pdf) |
| MK 104 sustainer propellant mass | **~250 kg** (band 230–372) | [astronautix MK 104](http://www.astronautix.com/m/mk104.html) |
| MK 72 booster propellant (SM-6 full round) | **~300 kg** additional | [designation-systems RIM-174](https://www.designation-systems.net/dusrm/m-174.html) |
| Propellant chemical energy (deflagration) | **7.0 MJ/kg** | [tandfonline HTPB combustion](https://www.tandfonline.com/doi/full/10.1080/00102202.2025.2563123) |
| Propellant TNT-eq **if it detonates** (1.3-class) | **k=1.3** (mass×1.3) | [DTIC ADA507382](https://apps.dtic.mil/sti/tr/pdf/ADA507382.pdf) |
| Propellant TNT-eq if it just **deflagrates/vents** | **k≈0.05–0.15** (mostly thrust/heat, little airblast) | Class 1.3 = mass-fire not mass-detonation, [globalsecurity IM](https://www.globalsecurity.org/military/systems/munitions/im.htm) |
| Warhead HE→TNT factor | **k_TNT = 1.1** | typical modern HE fill |

**Cook-off blast-energy formula (per magazine event):**
```
NEQ_round      = 22 kg TNT-eq   (warhead)   [use 22 + 1.3*prop_kg only in full-detonation branch]
W_tnt(n) = NEQ_round * k_TNT * ( c_sym * n  +  (1 - c_sym) * sqrt(n) )
    c_sym = 0.15  for Mk 41 VLS (vented, insensitive)      -> mostly √n growth
    c_sym = 0.80  for old confined/non-vented magazine     -> near-linear growth (Moskva/Hood-like)
E_joules(n) = W_tnt(n) * 4.184e6      # 1 kg TNT = 4.184 MJ
```

**Fireball radius & duration (visual sizing):**
```
R_fireball(m) = 3.5 * W_tnt^(1/3)              # cube-root, conventional-HE calibrated
    (alt fit: 4.7 * W_tnt^0.375 if you want faster growth)   [Hopkinson-Cranz]
t_fireball(s) = 0.2 * W_tnt^(1/3)  clamped to [0.3 s, 3.0 s]   # bigger yield = longer-lived flash
smoke_column_lifetime(s) = 60 .. 600            # Moskva/Forrestal: minutes to hours of smoke
```
Basis: cube-root Hopkinson-Cranz scaling, [ScienceDirect scaled distance](https://www.sciencedirect.com/topics/engineering/scaled-distance), [vcalc Hopkinson-Cranz](https://www.vcalc.com/wiki/hopkinson-cranz-scaling-law-range).

**PROBABILITY-FREE cook-off trigger rule (physics, not dice — honors project memory):**
```
Each magazine/VLS cell has: fire_intensity (0..1), heat_dwell_timer (s), confinement (0..1), flooded (bool).

1. A hit or adjacent fire raises local fire_intensity.
2. If VLS cell and venting intact and not overwhelmed:
      -> VENT branch: upward flame-jet effect, deflagration, k≈0.1, ship survives.
      Deluge/flood can quench: if flooded -> intensity decays, no event.
3. COOK-OFF fires deterministically when BOTH hold for a single round:
      fire_intensity >= 0.75   AND   heat_dwell_timer >= T_cook
      T_cook = 90 s  for old thin-cased ordnance (Forrestal M117 datum)
      T_cook = adjust up for insensitive munitions (longer to cook)
   -> that round releases NEQ_round; it becomes a shock source for neighbors.
4. SYMPATHETIC propagation (the catastrophe): a round going HIGH-ORDER within
   shock-coupling distance of neighbors sets their heat_dwell to instant and
   raises their intensity to 1.0 -> they detonate within the same blast window.
   Propagation gated by confinement & c_sym (VLS venting/IM barriers break it).
5. participation n = count of rounds that detonate within one blast window;
   feed n into W_tnt(n) above for the single catastrophic-kill blast.
6. Sequential (non-coupled) cook-offs each fire their own smaller blast on the
   Forrestal cadence: first at T_cook, then a cluster over ~5 min.
```
This yields: **VLS fire usually vents and the ship lives (Stark/Sheffield-like slow fights); a defeated vent + sympathetic chain gives an instant magazine kill (Hood/Moskva-like)** — emergent from fire intensity, dwell time, confinement and neighbor coupling, with **zero detonation dice.**

**Sinking model (adopt WT's good part):** buoyancy-% from flooded watertight compartments; DC = patch-then-pump loop; sink at buoyancy 0% or sustained extreme list. Magazine event is the accelerant that outruns DC. [wiki.warthunder.com Ship Crew Mechanics](https://wiki.warthunder.com/640-ship-crew-mechanics)

---

## 7. Top-10 Visual Signatures for the Catastrophic-Kill Effect

1. **Pre-event torch (VLS):** sustained vertical **orange flame + white-hot exhaust jet** roaring straight up out of a deck hatch for several seconds — blowtorch geyser, dense smoke. [globalsecurity MK 41](https://www.globalsecurity.org/military/systems/ship/systems/mk-41-vls.htm)
2. **Sequential secondaries:** discrete **sharp white/orange bomb-like flashes at intervals** — first ~90 s after fire start, then a burst cluster over ~5 min (Forrestal cadence), each with a debris fan. [Wikipedia Forrestal](https://en.wikipedia.org/wiki/1967_USS_Forrestal_fire)
3. **Catastrophic flash:** a single **blue-white → orange hemispherical detonation flash** far brighter than the secondaries when the chain goes sympathetic (Hood-like). [Wikipedia HMS Hood](https://en.wikipedia.org/wiki/HMS_Hood)
4. **Fireball then collapse:** fireball expands to `R=3.5·W^(1/3)` m, luminous for **0.3–3 s**, then collapses into a rising dark cloud.
5. **Debris + fragment fan:** blast-frag steel + hull plating thrown radially; visible **tracer-like ejecta arcs** and splash rings on the sea.
6. **Greasy black smoke column:** sooty (fuel/rubber/propellant) black grading to grey, rising hundreds of feet, **leaning downwind, flattening at the sea surface** — persists minutes to hours (Moskva/Forrestal). [CNN Moskva](https://www.cnn.com/2022/04/18/europe/ukraine-moskva-warship-sinking-images-intl/index.html)
7. **Hull rupture glow:** ragged breach with **internal orange fire glow** venting through the hole, re-flashing as fuel re-ignites.
8. **Shockwave ring on water:** a fast expanding **pale ring/spray disc** across the sea surface at detonation, decoupling from the fireball.
9. **Progressive list:** ship **rolls toward the hit side**, sits **low in the water**, **life rafts/debris in the water** — the slow post-blast loss phase (Moskva/Sheffield). [Stars & Stripes Moskva](https://www.stripes.com/theaters/europe/2022-04-18/photos-show-stricken-russian-ship-on-fire-possibly-confirm-ukrainian-missile-strike-5722704.html)
10. **Steam + smoke transition:** as the hull floods/sinks, black fire-smoke gives way to **white steam** where fire meets seawater, then the smoke column detaches and drifts.

---

## 8. Source-disagreement ledger

- **MK 125 warhead mass:** 64 kg (designation-systems, missilery — **[PREFERRED]**, consistent across SM-6 sources) vs 115 kg (forum documents). Use 64 kg; the 115 kg figure is unverified/likely a different measure.
- **MK 104 propellant mass:** 372 kg (astronautix gross-empty subtraction) vs a smaller sustainer grain implied elsewhere. Propellant NEQ barely enters the **preferred (vented) branch** anyway (k≈0.1), so this uncertainty is low-impact unless modeling full detonation; default 250 kg.
- **Exact per-round HE NEQ:** **not published** for MK 125. The 22 kg figure is an **[ESTIMATED]** case-fraction; flag in code as tunable.
- **Fireball radius coefficient:** 3.5·W^(1/3) (cube-root, cleaner) vs 4.7·W^0.375 (empirical HE cloud fit). Both defensible; cube-root is **[PREFERRED]** for a game (matches Hopkinson-Cranz exactly).
