# Warship Internal Layouts — Normative Subsystem-Location Reference for ONIKS

**Status:** NORMATIVE. Numbers in the RECOMMENDED GRID tables are the values to transcribe into code.
**Date:** 2026-07-06
**Frame convention (game-local):** `+Z` = forward (bow), `+Y` = up (waterline at Y=0), `+X` = starboard. Longitudinal positions are given as **z-fraction** of ship length: `0.0 = stern`, `1.0 = bow`. Vertical positions are given in **hull-heights relative to the waterline** as a signed fraction of hull depth `H` (draft below + freeboard above); `-1.0` ≈ keel/bottom, `0.0` = waterline, positive = above waterline. Transverse extent `x` is given as a fraction of local beam, `±1.0` = full beam.

> **How to read "z-fraction" for a real ship.** Where a primary source gives frame numbers, they are converted assuming the ship's frames run stem-to-stern over the quoted length. For the Burke this is anchored to the FAS SWOS engineering student guide's frame numbers (below); other classes are estimated from photographs, cutaways, and published bay/deck dimensions and are flagged as ESTIMATE.

---

## 1. Arleigh Burke DDG (Flight IIA) — length 155 m

**Anchor data (frames).** The FAS/SWOS engineering student guide gives the machinery-space frame boundaries directly ([man.fas.org PS9-101](https://man.fas.org/dod-101/navy/docs/swos/eng/PS9-101.html)):

- **AUX 1** (Nr 1 Gas Turbine Generator + Nr 1 switchboard): frames **126–174**, two levels, forward-most main machinery space.
- **MER 1** (Main Engine Room 1, starboard power train, GTMs 1A/1B + Nr 1 main reduction gear): frames **174–220**, three levels.
- **AUX 2** (A/C plants, aux equipment): frames **220–254**, single level.
- **MER 2** (Main Engine Room 2, port power train, GTMs 2A/2B + Nr 2 reduction gear, Nr 2 GTG): frames **254–300**, three levels; the largest main space.
- **Generator Room:** Nr 3 GTG.

Propulsion is **4× LM2500 in COGAG**, MER 1 driving the starboard shaft, MER 2 the port shaft ([Wikipedia: Arleigh Burke](https://en.wikipedia.org/wiki/Arleigh_Burke-class_destroyer); [naval-technology.com](https://www.naval-technology.com/projects/burke/)). Frame range 126–300 out of ~340–360 usable hull frames puts the machinery box roughly amidships (z ≈ 0.30–0.62), consistent with cutaways.

**VLS (Flight IIA):** **fwd 32-cell block** + **aft 64-cell block**, 96 total; the Flight IIA deleted the at-sea reload cranes that had occupied 3 tubes per group, going from 29+61 to 32+64 ([USNI Proceedings, Oct 2023](https://www.usni.org/magazines/proceedings/2023/october/vertical-launch-systems-evolve); [Wikipedia armament template](https://en.wikipedia.org/wiki/Template:Arleigh_Burke-class_destroyer_Flight_IIA/III_armament)). Fwd block sits just forward of the deckhouse over the sonar/forward magazine; aft block sits abaft the aft stack between the machinery box and the hangar.

**SPY-1D:** four fixed phased-array faces on the forward deckhouse; on Flight IIA the two **aft-facing arrays are raised one deck (~8 ft / 2.4 m)** to clear the taller aft superstructure/hangar and avoid a blind spot ([Wikipedia: AN/SPY-1](https://en.wikipedia.org/wiki/AN/SPY-1_radar); [Wikipedia: Arleigh Burke](https://en.wikipedia.org/wiki/Arleigh_Burke-class_destroyer)). Two forward faces look fwd/starboard and fwd/port; the mast (SPQ-9B/SPS-67/EW) is just abaft the deckhouse.

**CIC:** below the main deck, inside the hull under the forward deckhouse ([man.fas.org DDG-51](https://man.fas.org/dod-101/sys/ship/ddg-51.htm)). Bridge is atop the forward deckhouse.

**CIWS / hangar:** Flight IIA restored the **helo hangar aft of the aft VLS**, two hangars outboard of the module, for 2× SH-60 ([globalsecurity.org Flt IIA](https://www.globalsecurity.org/military/systems/ship/ddg-51-flt2a.htm)). Phalanx CIWS: one mount forward (atop the fwd VLS/deckhouse area) and one aft (over the hangar).

**Fuel:** F-76 marine diesel in double-bottom and wing tanks low in the hull, distributed under and around the machinery box (below waterline).

### Subsystem table — Burke Flight IIA
| Subsystem | z-fraction (stern→bow) | height (vs WL) | x extent | Below WL? | Game effect |
|---|---|---|---|---|---|
| Aft 64-cell VLS | 0.60–0.70 | −0.15 … +0.15 | ±0.35 | tops above, mags at/below WL | **vls** |
| Fwd 32-cell VLS | 0.72–0.80 | −0.15 … +0.15 | ±0.30 | tops above, mags at/below WL | **vls** |
| MER 2 (port GT) | 0.30–0.42 | −1.0 … 0.0 | ±0.6 | **yes** | **propulsion** |
| AUX 2 | 0.42–0.48 | −0.9 … −0.2 | ±0.5 | **yes** | **propulsion** (aux) |
| MER 1 (stbd GT) | 0.48–0.58 | −1.0 … 0.0 | ±0.6 | **yes** | **propulsion** |
| AUX 1 (Nr1 GTG) | 0.58–0.63 | −0.9 … −0.2 | ±0.5 | **yes** | **propulsion** (power) |
| SPY-1D fwd faces (×2) | 0.68–0.74 | +0.5 … +0.9 | ±0.5 (canted) | no | **sensors** |
| SPY-1D aft faces (×2) | 0.55–0.60 | +0.6 … +1.0 | ±0.5 (canted) | no | **sensors** |
| Mast / EW / SPQ-9B | 0.60–0.66 | +0.9 … +1.4 | ±0.15 | no | **sensors** |
| Bridge | 0.70–0.75 | +0.55 … +0.75 | ±0.3 | no | **c2** |
| CIC | 0.66–0.74 | +0.05 … +0.30 | ±0.4 | no (main-deck, in hull) | **c2** |
| Hangar (2× SH-60) | 0.18–0.30 | +0.1 … +0.45 | ±0.5 | no | soft/aviation |
| CIWS fwd | 0.78 | +0.4 | ±0.15 | no | point-defense |
| CIWS aft | 0.20 | +0.45 | ±0.15 | no | point-defense |
| Fuel (F-76) tanks | 0.25–0.65 | −1.0 … −0.3 | ±0.9 (wing+DB) | **yes** | **flotation/fire** |

---

## 2. Ticonderoga CG — length 173 m

Built on the **Spruance (DD-963) hull**, so machinery layout mirrors the Burke lineage: 4× LM2500 COGAG in two main engine rooms amidships, two shafts ([Wikipedia: Ticonderoga](https://en.wikipedia.org/wiki/Ticonderoga-class_cruiser)). **VLS: two 61-cell Mk 41 (Mk 158) blocks, fwd + aft**, 122 total; 61 (not 64) because each block reserves 3 cells for a reload crane ([Wikipedia: Ticonderoga](https://en.wikipedia.org/wiki/Ticonderoga-class_cruiser); [Shipbucket Mk 41](https://www.shipbucket.com/wiki/index.php/Mk_41_VLS)). SPY-1A/B faces are split between the **forward and after superstructures** (two forward on the bridge deckhouse, two aft on the after deckhouse) — a distinguishing feature vs the Burke's single forward deckhouse. Bridge forward atop the fwd superstructure; the fwd VLS is between the 5"/54 gun and the bridge, the aft VLS between the after stack and the aft deckhouse/helo deck.

### Subsystem table — Ticonderoga
| Subsystem | z-fraction | height (vs WL) | x extent | Below WL? | Game effect |
|---|---|---|---|---|---|
| Aft 61-cell VLS | 0.20–0.30 | −0.15 … +0.15 | ±0.35 | mags at/below WL | **vls** |
| Fwd 61-cell VLS | 0.72–0.82 | −0.15 … +0.15 | ±0.35 | mags at/below WL | **vls** |
| Aft engine room | 0.34–0.46 | −1.0 … 0.0 | ±0.6 | **yes** | **propulsion** |
| Fwd engine room | 0.52–0.64 | −1.0 … 0.0 | ±0.6 | **yes** | **propulsion** |
| SPY fwd faces (×2) | 0.66–0.72 | +0.5 … +0.9 | ±0.5 | no | **sensors** |
| SPY aft faces (×2) | 0.28–0.34 | +0.5 … +0.9 | ±0.5 | no | **sensors** |
| Bridge / fwd deckhouse | 0.68–0.74 | +0.55 … +0.8 | ±0.3 | no | **c2** |
| Fuel tanks | 0.30–0.66 | −1.0 … −0.3 | ±0.9 | **yes** | **flotation/fire** |

*(ESTIMATE for exact z-splits; anchored to Spruance-derived machinery amidships and photographed fore/aft VLS + fore/aft SPY placement.)*

---

## 3. Nimitz-class CVN — length 333 m

**Reactors:** 2× Westinghouse **A4W** in shielded reactor compartments **low and roughly amidships, deep in the hull below the waterline and armor decks** ([Wikipedia: Nimitz](https://en.wikipedia.org/wiki/Nimitz-class_aircraft_carrier)). **Hangar deck:** ~208.5 × 32.9 × 8.07 m, divided into **3 bays by thick steel fire doors**; located above the waterline under the flight deck ([naval-encyclopedia.com](https://naval-encyclopedia.com/cold-war/us/nimitz-class-fleet-aircraft-carriers.php)). **JP-5 aviation fuel:** ~10,220,000 L, stowed **in tanks deep below** the hangar/magazine level, pumped up ([naval-encyclopedia.com](https://naval-encyclopedia.com/cold-war/us/nimitz-class-fleet-aircraft-carriers.php)). **Magazines:** in a **box-shaped protected zone** low in the hull, below the hangar; ordnance is elevated up to the deck. **Armor:** 3 protected decks (flight/hangar/lower ~45/50/56 mm) + side belt (~135 mm est.) + **box protection of magazines and vital zones** ([naval-encyclopedia.com](https://naval-encyclopedia.com/cold-war/us/nimitz-class-fleet-aircraft-carriers.php); [globalsecurity.org CVN-68 design](https://www.globalsecurity.org/military/systems/ship/cvn-68-design.htm)). **Island:** starboard, offset outboard, ~0.55–0.62 z. **Catapults:** two on the bow (z≈0.75–0.95), two on the angled/waist deck (port, z≈0.35–0.6).

**What historically kills carriers — fuel/ordnance fire, not flooding.** The 1967 **Forrestal** and 1969 **Enterprise** fires both began when a rocket ruptured JP-5 tanks; spreading fuel fire cooked off ordnance. On Forrestal, an old thin-cased Composition-B "fat boy" detonated **94 seconds** after ignition, and ~40,000 gal of burning fuel poured through deck holes into the hangar and berthing below ([Wikipedia: 1967 Forrestal fire](https://en.wikipedia.org/wiki/1967_USS_Forrestal_fire); [insensitivemunitions.org](http://www.insensitivemunitions.org/history/the-uss-forrestal-cva-59-fire-and-munition-explosions/)). The dominant lethal chain is **fuel fire → ordnance cook-off/magazine detonation**; huge reserve buoyancy makes progressive flooding a secondary threat. Modern insensitive munitions (Comp H6, thick cases) deflagrate rather than detonate, cutting the catastrophic-magazine risk ([Wikipedia: 1967 Forrestal fire](https://en.wikipedia.org/wiki/1967_USS_Forrestal_fire)).

> **Game rule for CVN:** model the carrier's kill state as driven by **aviation-fuel + magazine hit → fire/secondary-explosion**, not by a single waterline breach. A hit into the JP-5/magazine box should have far higher lethality than a hit into a void, machinery, or single hull compartment.

### Subsystem table — Nimitz CVN
| Subsystem | z-fraction | height (vs WL) | x extent | Below WL? | Game effect |
|---|---|---|---|---|---|
| Reactor compartments (×2) | 0.40–0.60 | −1.0 … −0.4 | ±0.4 (centerline) | **yes** | **propulsion** (catastrophic if breached) |
| Aviation fuel (JP-5) box | 0.35–0.65 | −1.0 … −0.5 | ±0.6 | **yes** | **fire/secondary-explosion** |
| Ordnance magazines | 0.30–0.45 & 0.65–0.75 | −0.9 … −0.4 | ±0.4 | **yes** | **magazine-detonation** |
| Hangar deck (3 bays) | 0.15–0.75 | +0.15 … +0.45 | ±0.8 | no | soft/aviation, fire spread |
| Island | 0.52–0.62 | +0.45 … +1.0 | +0.6 … +0.9 (stbd) | no | **c2/sensors** |
| Bow catapults (×2) | 0.75–0.95 | +0.5 | ±0.4 | no | aviation |
| Waist catapults (×2) | 0.35–0.60 | +0.5 | −0.2 … −0.7 (port) | no | aviation |
| Machinery / shafts | 0.20–0.45 | −1.0 … −0.3 | ±0.7 | **yes** | **propulsion** |

---

## 4. Modern SSN/SSK (Los Angeles / Virginia reference) — pressure-hull compartments

The pressure hull is a slender cylinder subdivided lengthwise by watertight bulkheads ([sciencedirect: pressure hull](https://www.sciencedirect.com/topics/engineering/pressure-hull)). Broad longitudinal arrangement (bow→stern): **torpedo/weapons room forward-low; control room (attack center) below the sail/forward-upper; reactor compartment amidships; engine/machinery room aft**; auxiliary/berthing between torpedo room and reactor.

**Why any breach at depth is essentially fatal.** At depth, ambient pressure is ~1 atm per 10 m. A pressure-hull breach does not just leak — it either (a) admits water at enormous rate through a high-pressure orifice, or (b) removes local structural support and triggers **progressive collapse/implosion** once external pressure exceeds hull strength; at 1,000 m that is ~100 atm (~1 tonne/cm²) ([scienceabc](https://www.scienceabc.com/innovation/what-makes-a-submarine-implode-causes-underwater-submersible-implosion); [americanoceans](https://www.americanoceans.org/facts/what-happens-during-a-submarine-implosion/)). Battle damage, depth-charge/torpedo shock, and welding/corrosion flaws are the historic breach causes ([DTIC ADA551459](https://apps.dtic.mil/sti/pdfs/ADA551459.pdf)). A surfaced submarine, by contrast, has zero external overpressure and can absorb light topside/ballast-tank damage and survive.

> **Defensible game rule for subs:**
> - **Submerged + any pressure-hull breach ⇒ loss** (flooding rate and collapse both scale with depth; treat as non-survivable).
> - **Surfaced ⇒ treat like a small unarmored surface combatant:** light damage survivable; only large below-DWL breach or magazine/torpedo-room hit is fatal.
> - Optional depth gate: breach at < ~50 m *might* allow emergency-blow survival; ≥ collapse-depth band ⇒ certain loss.

### Subsystem table — SSN
| Compartment | z-fraction | height (vs centerline) | Submerged breach ⇒ | Game effect |
|---|---|---|---|---|
| Torpedo / weapons room | 0.60–0.78 | lower | loss (also magazine) | **vls/magazine + flotation** |
| Control room (attack center) | 0.55–0.68 | upper (under sail) | loss | **c2** |
| Sail / masts / sensors | 0.55–0.65 | topside | (surfaced only) sensors kill | **sensors** |
| Reactor compartment | 0.40–0.55 | mid | loss | **propulsion** |
| Engine/machinery room | 0.15–0.40 | mid-lower | loss | **propulsion** |
| Aux/berthing | 0.45–0.60 | mid | loss | **flotation** |

---

## 5. Generic merchant (container ship / tanker)

**Engine room:** near the bottom, **aft**, few compartments, under/behind the accommodation block ([maritimeknowledge.in](https://www.maritimeknowledge.in/course-details.php?course_id=47); [marinepublic.com](https://marinepublic.com/blogs/marine-law/473885-ship-general-arrangement-every-space-has-a-purpose)). **Cargo holds/tanks:** long midship run forward of the engine room. **Bridge/accommodation:** aft (containers) or can be aft (modern tankers).

**Why tankers burn rather than sink; and a 2-compartment flooding rule.** Merchant subdivision standard: remain afloat/stable with damage; large ships are built so a **single compartment** flooded won't sink them, and modern rules push toward surviving flooding across a **two-compartment** damage length ([marinepublic.com](https://www.marinepublic.com/blogs/training/872963-ship-compartments-guide-vessel-sections-and-design-layout)). Tankers subdivide cargo into many oiltight tanks; a breach floods (or spills) one or two tanks but the rest provide buoyancy — so the **immediate lethal event is the cargo fire/explosion of volatile hydrocarbons**, not loss of buoyancy. Longitudinal oiltight bulkheads cause **asymmetric flooding → list**, countered by **cross-flooding ducts** ([navalgazing.net Survivability-Flooding](https://www.navalgazing.net/Survivability-Flooding)).

> **Game rule for merchants:** flooding of **1 compartment survivable; 2 adjacent compartments = crippled/sinking threshold**. A tanker cargo hit rolls to **fire/explosion** (high kill probability) rather than to flooding.

### Subsystem table — merchant
| Subsystem | z-fraction | height (vs WL) | Below WL? | Game effect |
|---|---|---|---|---|
| Engine room | 0.05–0.20 | −1.0 … −0.1 | **yes** | **propulsion** |
| Cargo holds/tanks | 0.20–0.90 | −1.0 … +0.5 | partly | **flotation / fire (tanker)** |
| Bridge/accommodation | 0.05–0.18 | +0.4 … +1.0 | no | **c2** |
| Fuel bunkers | 0.05–0.25 | −0.9 … −0.3 | **yes** | flotation/fire |

---

## Damage-control constants (calibration)

**Flooding rate vs hole size & depth (orifice / Torricelli).** From naval DC references ([navalgazing.net](https://www.navalgazing.net/Survivability-Flooding), quoting the 1945 USN DC handbook figures; corroborated by DC training sources):
- **1 ft² hole, 15 ft below WL ⇒ ~13,900 gal/min (~48 tons/min).**
- **12 in² (0.083 ft²) hole, 10 ft below WL ⇒ ~9,000 gal/min.**
- 1 in² hole, 1 ft below WL ⇒ ~1,200 gal/hr; 2 in² @ 2 ft ⇒ ~6,000 gal/hr.

Rate scales ≈ **area × √(depth)** (`Q ≈ Cd·A·√(2gh)`, Cd≈0.6). Implementable directly.

**Pump/eductor capacity.**
- P-500 pump w/ two 4-in eductors: **up to ~1,000 gal/min** at low discharge head; **P-100 ≈ 120 gal/min** ([EPA UNDS portable pump discharges](https://www.epa.gov/sites/default/files/2015-08/documents/2007_07_10_oceans_regulatory_unds_tdddocuments_appaportable.pdf); navalgazing).

> **Order-of-magnitude takeaway for the game:** a real below-waterline weapon breach (≥1 ft², several feet down) admits water at **~10,000 gal/min**, while a ship's portable pump moves **~1,000 gal/min**. **Pumps lose to any serious breach by ~10:1.** So DC "wins" only for small holes or after boundaries/plugs cut the effective orifice down; a large waterline breach is a **losing race** unless the compartment can be sealed.

**Compartment / subdivision standard (survivability).**
- **Modern destroyers are ~"four-compartment ships"** — up to four main transverse compartments can free-flood before the main deck goes awash; combined with hull section-modulus limits, survivable flooding is **"somewhat greater than two machinery spaces" (small DDs)** to **"greater than three" (larger classes)** ([erenow / *Rebuilding the Royal Navy*](https://erenow.org/ww/rebuilding-royal-navy-warship-design-since-1945/13.php)).
- **Merchant/large-ship standard:** afloat & stable with **1 compartment** flooded, trending to **2-compartment** damage-length survivability ([marinepublic.com](https://www.marinepublic.com/blogs/training/872963-ship-compartments-guide-vessel-sections-and-design-layout)).
- **Counter-/cross-flooding:** deliberately flood a symmetric compartment to correct **list** from asymmetric damage (accept lower freeboard to regain stability) ([navalgazing.net](https://www.navalgazing.net/Survivability-Flooding)).

**Calibration cases (breach size → outcome → time).**
| Case | Breach | Compartments | Outcome | Time |
|---|---|---|---|---|
| **USS Cole (2000)** | ~40×60 ft (~1,600 ft²) at WL, non-contact HE | multiple; too big to patch, sealed by boundaries | survived, thousands gal/min ingress | **96 hr** sustained DC ([history.navy.mil](https://www.history.navy.mil/content/history/nhhc/browse-by-topic/ships/modern-ships/uss-cole.html); [halsell substack](https://halsell.substack.com/p/25-years-later-remembering-the-uss-cole)) |
| **USS Fitzgerald (2017)** | ~12×12 ft (Aux 1) + 3×5 ft, **below WL** | **3 compartments** flooded, berthings + captain's cabin | survived (7 dead) | rapid; ship stayed up ([Wikipedia: Fitzgerald/ACX Crystal](https://en.wikipedia.org/wiki/USS_Fitzgerald_and_MV_ACX_Crystal_collision)) |
| **USS John S. McCain (2017)** | ~28 ft dia, above & **below WL** | berthing 5 (15→5 ft crushed) + adjacent | survived (10 dead); **berthing flooded in <1 min** | <60 s to flood one space ([Wikipedia: McCain/Alnic MC](https://en.wikipedia.org/wiki/USS_John_S._McCain_and_Alnic_MC_collision)) |

Lesson for the game: a Burke-sized DDG **survived breaches flooding ~3 below-waterline compartments** (Fitzgerald, McCain) and even a ~1,600 ft² waterline hole (Cole) — but individual below-WL compartments flood in **tens of seconds**, and outcome hinges on **how many adjacent compartments open to the sea**. This directly supports a **≈3-adjacent-compartment survival threshold for a DDG**, 1–2 for a merchant.

---

## What a 250–300 kg SAP anti-ship warhead does structurally

Anchors: **Exocet MM38/AM39 ~165 kg SAP** ([csis missilethreat](https://missilethreat.csis.org/missile/exocet/)); **Harpoon ~227 kg** programmed-impact-angle penetrator ([Exocet/Harpoon comparison](https://en.wikipedia.org/wiki/Exocet)). A SAP warhead is designed to **punch through the (unarmored, ~10–20 mm) hull/superstructure plating, then detonate inside** after a fuze delay.

- **HMS Sheffield (1982):** Exocet entered **2.4 m above the waterline**, drove through the scullery, breached the fwd auxiliary/engine-room bulkhead, and left a hull hole roughly **1.2 × 3 m**; MoD's 2015 reassessment concluded the warhead **did** detonate internally. Fire (fed by fuel/cable/foam), not flooding, killed the ship over several days ([Wikipedia: HMS Sheffield](https://en.wikipedia.org/wiki/HMS_Sheffield_(D80))).
- **USS Stark (1987):** two AM39 hits; at least one warhead detonated internally, 37 killed; frigate flooded and listed but was **saved by DC** — again fire + a below/near-WL breach, survivable with effort.

**Structural effects to model:**
1. **Penetration:** SAP defeats unarmored steel and typically penetrates **one or more internal bulkheads (~2–10 m in)** before detonating; delay fuze puts the blast **inside the hull**, not on the skin.
2. **Breach size at/near waterline:** on a frigate/destroyer, **~1–4 m across (order 1–12 m²)** entry/blast hole — enough to open one, sometimes two, compartments to the sea if at/below WL.
3. **Internal blast + "whiplash":** overpressure and fragments wreck the struck compartment and adjacent spaces; the Mach-2+ impact and detonation impart a shock/whip that can rupture nearby bulkheads, sever fire mains and cables, and **start fuel/propellant fires** — historically the decisive kill mechanism (Sheffield, Stark) even when initial flooding is controllable.
4. **Unexploded-penetrator case:** even a **dud** SAP (Sheffield/Stark early assessments) can wreck spaces and start fires purely by kinetic energy + burning rocket fuel.

> **Game rule for a ~250–300 kg SAP hit:** treat as **penetrate ~1–3 compartments deep**, open a **~1–12 m² breach** (floods 1–2 compartments if at/below WL), and roll a **high-probability internal fire** that can spread to adjacent spaces and threaten fuel/magazine. Lethality should come primarily from **(a) compartment count opened to sea** and **(b) fire reaching fuel/VLS/magazine**, not from the entry hole alone.

---

## RECOMMENDED GRID (transcribe to code)

**Geometry — one row per subsystem box.** `z0,z1` = length fraction (stern→bow); `y0,y1` = height fraction vs WL (−1 keel … +1.4 masthead); `x` = half-beam fraction; `sub` = below-waterline flag.

```
# Arleigh Burke DDG Flight IIA (L=155 m)
BURKE = [
  # name              z0    z1    y0    y1    x_half  belowWL  effect
  ("vls_aft_64",      0.60, 0.70, -0.15, 0.15, 0.35,  True,   "vls"),
  ("vls_fwd_32",      0.72, 0.80, -0.15, 0.15, 0.30,  True,   "vls"),
  ("mer2_port",       0.30, 0.42, -1.00, 0.00, 0.60,  True,   "propulsion"),
  ("aux2",            0.42, 0.48, -0.90,-0.20, 0.50,  True,   "propulsion"),
  ("mer1_stbd",       0.48, 0.58, -1.00, 0.00, 0.60,  True,   "propulsion"),
  ("aux1_gtg",        0.58, 0.63, -0.90,-0.20, 0.50,  True,   "propulsion"),
  ("spy_fwd_faces",   0.68, 0.74,  0.50, 0.90, 0.50,  False,  "sensors"),
  ("spy_aft_faces",   0.55, 0.60,  0.60, 1.00, 0.50,  False,  "sensors"),
  ("mast",            0.60, 0.66,  0.90, 1.40, 0.15,  False,  "sensors"),
  ("bridge",          0.70, 0.75,  0.55, 0.75, 0.30,  False,  "c2"),
  ("cic",             0.66, 0.74,  0.05, 0.30, 0.40,  False,  "c2"),
  ("hangar",          0.18, 0.30,  0.10, 0.45, 0.50,  False,  "aviation"),
  ("fuel_f76",        0.25, 0.65, -1.00,-0.30, 0.90,  True,   "flotation"),
]

# Ticonderoga CG (L=173 m)
TICO = [
  ("vls_aft_61",      0.20, 0.30, -0.15, 0.15, 0.35,  True,   "vls"),
  ("vls_fwd_61",      0.72, 0.82, -0.15, 0.15, 0.35,  True,   "vls"),
  ("er_aft",          0.34, 0.46, -1.00, 0.00, 0.60,  True,   "propulsion"),
  ("er_fwd",          0.52, 0.64, -1.00, 0.00, 0.60,  True,   "propulsion"),
  ("spy_fwd_faces",   0.66, 0.72,  0.50, 0.90, 0.50,  False,  "sensors"),
  ("spy_aft_faces",   0.28, 0.34,  0.50, 0.90, 0.50,  False,  "sensors"),
  ("bridge",          0.68, 0.74,  0.55, 0.80, 0.30,  False,  "c2"),
  ("fuel",            0.30, 0.66, -1.00,-0.30, 0.90,  True,   "flotation"),
]

# Nimitz CVN (L=333 m)  -- fire/magazine kill dominates
NIMITZ = [
  ("reactors",        0.40, 0.60, -1.00,-0.40, 0.40,  True,   "propulsion"),
  ("jp5_fuel_box",    0.35, 0.65, -1.00,-0.50, 0.60,  True,   "fire"),
  ("magazine_fwd",    0.30, 0.45, -0.90,-0.40, 0.40,  True,   "magazine"),
  ("magazine_aft",    0.65, 0.75, -0.90,-0.40, 0.40,  True,   "magazine"),
  ("hangar",          0.15, 0.75,  0.15, 0.45, 0.80,  False,  "aviation"),
  ("island",          0.52, 0.62,  0.45, 1.00, 0.60,  False,  "c2"),  # x offset +stbd
  ("machinery",       0.20, 0.45, -1.00,-0.30, 0.70,  True,   "propulsion"),
]

# SSN submerged (L~110 m LA / 115 m Virginia) -- breach@depth => loss
SSN = [
  ("torpedo_room",    0.60, 0.78, -0.5, 0.3, 0.5,  True,  "magazine"),
  ("control_room",    0.55, 0.68,  0.0, 0.5, 0.5,  True,  "c2"),
  ("reactor",         0.40, 0.55, -0.5, 0.3, 0.5,  True,  "propulsion"),
  ("engine_room",     0.15, 0.40, -0.5, 0.3, 0.5,  True,  "propulsion"),
]

# Merchant (container/tanker)
MERCHANT = [
  ("engine_room",     0.05, 0.20, -1.00,-0.10, 0.60, True,  "propulsion"),
  ("cargo",           0.20, 0.90, -1.00, 0.50, 0.90, True,  "flotation/fire"),
  ("bridge_accom",    0.05, 0.18,  0.40, 1.00, 0.50, False, "c2"),
]
```

**Damage-control / survivability constants:**
```
# Flooding:  Q_gpm ≈ 0.6 * A_ft2 * sqrt(2*32.2*depth_ft) * 448.8   (orifice)
FLOOD_CD          = 0.6
FLOOD_CALIB       = {"1ft2_15ft": 13900_gpm, "12in2_10ft": 9000_gpm}  # sanity anchors
PUMP_P500_GPM     = 1000     # portable, per pump, low head
PUMP_P100_GPM     = 120
# Rule of thumb: serious breach ingress ~10x total portable pump capacity.

# Survivable adjacent-compartments-flooded threshold:
SURVIVE_COMPARTMENTS = {"DDG": 3, "CG": 3, "CVN": 5, "SSN_surfaced": 1, "MERCHANT": 2}
# (DDG=3 anchored to Fitzgerald/McCain 3-compartment survivals + "> two/three machinery spaces" design std)

# Submarine rule:
SUB_SUBMERGED_BREACH = "LOSS"          # any pressure-hull breach at depth
SUB_SURFACED         = "surface_combatant_light"  # light damage survivable

# SAP anti-ship warhead (250-300 kg):
SAP_PENETRATE_COMPARTMENTS = (1, 3)    # bulkheads defeated before detonation
SAP_BREACH_AREA_M2         = (1, 12)   # entry/blast hole; floods 1-2 comp if <=WL
SAP_INTERNAL_FIRE_P        = 0.7       # high; escalates if reaches fuel/VLS/magazine
```
