# Missile Visual & Dimensional Reference Pack

Purpose: correct the low-poly 3D missile models in ONIKS — especially **fin placement, fin shape, and body proportions**. Every entry gives real dimensions, a fin-layout table (count / position as fraction of body length from the nose / shape / fixed-or-moving / which group steers), nose shape, and distinctive visual signatures.

Reference images live in `./references/`. Filenames are called out per missile. A few downloads were blocked by Wikimedia rate-limiting (HTTP 429); those URLs are noted inline so they can be fetched manually.

Notation: "position 0.0" = nose tip, "position 1.0" = tail. Dimensions are best-available open-source estimates; Russian systems in particular carry ±5–10% spread between sources, and hypersonic figures (Zircon) are analyst estimates only.

---

## 1. P-800 Oniks / Yakhont (3M55, SS-N-26) — the hero weapon

| Spec | Value |
|---|---|
| Length | 8.3 m (ship/anti-ship) to 8.9 m (some sources, land-attack) |
| Diameter | 0.67 m (670 mm) |
| Wingspan | ~1.7 m |
| Launch mass | ~3,000 kg |
| Propulsion | Liquid-fuel **ramjet** (kerosene/T-6), solid booster in the tail |

**Nose shape:** THE defining feature — a **pointed axisymmetric nose spike sitting inside an annular (ring) ram-air inlet**. The whole nose is a circular intake: air enters around a central conical shock-cone that houses the radar seeker. This is NOT a solid ogive. If the model has a plain pointed cone nose, it is wrong.

**Fin layout:**

| Group | Count | Position (frac) | Shape | Fixed/Moving | Steers? |
|---|---|---|---|---|---|
| Mid/aft wings | 4 | ~0.55–0.70 | Low-aspect **clipped-delta / trapezoidal**, cruciform (X or +) | Fixed | No |
| Tail control fins | 4 | ~0.90–1.0 | Smaller clipped-delta / trapezoidal, cruciform, in-line with wings | Moving | **Yes** |

Cruciform 4+4 layout. Wings are short and stubby (span only ~2.5× body diameter) because it flies fast and low — do not model long slender wings. Booster is internal (ejects from tail after burn), so no external booster stage is visible.

**Distinctive signatures:** annular ram-air intake nose; fat 0.67 m body; short stubby cruciform wings; overall "fat pencil with a ringed nose." References: `oniks_yakhont_side_01.jpg`, `oniks_yakhont_side_02.jpg`, `oniks_sketch_lineart.png` (line drawing — best for fin geometry).

Citations: [Wikipedia P-800](https://en.wikipedia.org/wiki/P-800_Oniks) · [Missile Threat CSIS SS-N-26](https://missilethreat.csis.org/missile/ss-n-26/) · [Army Recognition](https://www.armyrecognition.com/military-products/navy/weapons-systems/missiles/p-800-oniks-3m55-yakhont-ss-n-26-strobile)

---

## 2. 3M22 Zircon (SS-N-33) — hypersonic

| Spec | Value |
|---|---|
| Length | ~8–10 m (est.; commonly cited ~9 m, some ~9.5 m) |
| Diameter | ~0.6–0.7 m |
| Launch mass | ~3,000–4,000 kg (some to ~5 t) |
| Propulsion | Solid booster (1st stage) + **scramjet** sustainer |

**Nose shape:** slender, sharp waverider-style forebody. Widely believed to fly under a jettisonable aero/nose fairing during boost; terminal shape is a lifting center-body, not a simple ogive. Much is classified — model conservatively as a very slender pointed body.

**Fin layout:**

| Group | Count | Position (frac) | Shape | Fixed/Moving | Steers? |
|---|---|---|---|---|---|
| Tail control fins | 4 | ~0.90–1.0 | Small clipped/swept, cruciform | Moving | **Yes** |
| Lifting body / strakes | — | mid-body | Blended lifting center-body (waverider), folding surfaces reported | — | contributes lift |

**Distinctive signatures:** noticeably more **slender** than Oniks for its length (higher fineness ratio); scramjet ventral/annular intake; hypersonic "arrow." Do not reuse the Oniks body — Zircon is thinner and longer. Reference: `zircon_01.jpg` (color cutaway).

Citations: [Wikipedia 3M22 Zircon](https://en.wikipedia.org/wiki/3M22_Zircon) · [Army Recognition Zircon](https://www.armyrecognition.com/military-products/army/missiles/hypersonic-missiles/3m22-zircon-ss-n-33) · [Missile Defense Advocacy](https://www.missiledefenseadvocacy.org/missile-threat-and-proliferation/todays-missile-threat/russia/3m22-zircon/)

---

## 3. 3M14 Kalibr (SS-N-30A) — land-attack cruise missile

| Spec | Value |
|---|---|
| Length | ~6.2 m (missile); ~8.9 m with booster (canister length) |
| Diameter | 0.514 m (533 mm class) |
| Launch mass | ~1,770 kg with booster |
| Propulsion | Solid **launch/turn booster** (with lattice/grid stabilizers) then **turbojet** cruise; pop-out intake |

**Nose shape:** rounded ogive housing the ARGS-14E radar/nav; NOT pointed — subsonic cruise missile.

**Fin layout:**

| Group | Count | Position (frac) | Shape | Fixed/Moving | Steers? |
|---|---|---|---|---|---|
| Pop-out cruise wings | 2 | ~0.45–0.55 (mid) | Straight/slightly-swept **plank wings that deploy from a mid-body slot** | Deploy then fixed | No (lift) |
| Tail control fins | 4 | ~0.90–1.0 | Small clipped, cruciform | Moving | **Yes** |
| Booster grid/lattice fins | 4 | booster tail | **Lattice (grid) fins** on the jettisonable booster | Fixed | booster stabilize |

**Distinctive signatures:** the **mid-body pop-out straight wings** (stowed flush in the tube, spring out after launch — model both stowed and deployed if animating); flush air intake that opens for the turbojet; **grid/lattice fins on the discardable booster** (a Tomahawk does NOT have these). This is a Tomahawk-analog silhouette but with the Russian grid-finned booster. References: `kalibr_3m14e_01.jpg`, `kalibr_3m14e_02.jpg`.

Citations: [Wikipedia Kalibr family](https://en.wikipedia.org/wiki/Kalibr_(missile_family)) · [Missile Threat SS-N-30A](https://missilethreat.csis.org/missile/ss-n-30a/) · [en.missilery.info 3M-14E](https://en.missilery.info/missile/3m14e)

---

## 4. Kh-31P (AS-17 Krypton) — anti-radiation

| Spec | Value |
|---|---|
| Length | 4.70 m (base) / 5.23 m (P-D / PD modernized) |
| Diameter | 0.36 m (360 mm) |
| Wingspan (rudders) | ~1.1 m |
| Propulsion | Solid booster (in empty case) then **integral ramjet**; **4 side air-intakes open after boost** |

**Nose shape:** pointed cone housing the passive anti-radiation seeker.

**Fin layout:**

| Group | Count | Position (frac) | Shape | Fixed/Moving | Steers? |
|---|---|---|---|---|---|
| Mid/aft wings | 4 | ~0.6–0.7 | **Clipped-delta**, cruciform, titanium | Fixed | No |
| Tail control surfaces | 4 | ~0.9–1.0 | Smaller **clipped-delta** of similar shape, cruciform | Moving | **Yes** |

**Distinctive signatures:** **four flush air-intake scoops around the mid-body that pop open** during the ramjet phase (the single most-missed detail — a plain smooth tube is wrong); 4 clipped-delta wings + 4 matching smaller tail fins, all cruciform. Compact and stocky. References: `kh31_armia_02.jpg` (Kh-31 at Army-2018).

Citations: [Wikipedia Kh-31](https://en.wikipedia.org/wiki/Kh-31) · [en.missilery.info X-31P](https://en.missilery.info/missile/x31p)

---

## 5. S-300/S-400 — 48N6 (long SAM) vs 40N6 (very-long SAM) — CRITICAL: THEY ARE DIFFERENT

These currently share one model in-game. They should NOT. See dedicated comparison table at the end of the doc. Summary:

### 48N6 (48N6E / 48N6DM) — the standard long-range round
| Spec | Value |
|---|---|
| Length | ~7.5 m |
| Diameter | 0.519 m (519 mm) |
| Wingspan | ~1.134 m |
| Launch mass | ~1,800 kg (48N6E) / ~1,835 kg (48N6D) |
| Warhead | ~143 kg |
| Propulsion | Single-stage solid rocket |

### 40N6 (40N6E) — the very-long-range (~380–400 km) round
| Spec | Value |
|---|---|
| Length | ~7.8 m (longer than 48N6) |
| Diameter | ~0.5 m body (comparable/slightly larger; some sources larger aft) |
| Launch mass | ~1,893 kg (heavier) |
| Propulsion | **Two-stage** — dedicated first stage + sustainer; has an active + semi-active combined seeker for over-the-horizon shots |

**Nose shape (both):** sharp pointed cone (supersonic interceptor). 40N6 nose houses the larger dual-mode (active/SARH) seeker for lofted OTH engagements.

**Fin layout (both, canonical S-300/400 interceptor pattern):**

| Group | Count | Position (frac) | Shape | Fixed/Moving | Steers? |
|---|---|---|---|---|---|
| Long-chord tail control fins | 4 | ~0.75–1.0 | **Long-root-chord clipped-delta / trapezoid running along the rear third**, cruciform, folding | Moving (gas-dynamic + aero) | **Yes** |
| Strakes/lattice (context) | small | forebody | small forward strakes on some variants | Fixed | destabilize/control aid |

Note: the S-300/400 family uses **cold vertical launch** (ejected from the tube, then the motor lights and it tips over), so there are **no external booster fins** on the tube — the control fins are the long rear cruciform set. The 40N6's extra length comes largely from its **longer/second motor stage**, so on the model the 40N6 should read as a **longer body with the fin band pushed slightly further aft**, not just a scaled copy.

**Distinctive signatures / how to tell them apart on the model:**
- 40N6 is **~0.3 m longer** and **~90 kg heavier** — model it visibly longer.
- 40N6 is **two-stage** — a visible girth/interstage break or a longer aft motor section; 48N6 is one clean single-stage tube.
- Real-world consequence baked into the game world: an S-400 TEL carries **4× 48N6 but only 2× 40N6** because the 40N6 is physically bigger — good sanity check that they are different sizes.

References: no clean isolated 48N6/40N6 line drawing downloaded (parade shots only; the missiles are usually tube-encased). See citations for figures.

Citations: [weaponsystems.net 48N6](https://weaponsystems.net/system/1417-%3E%3E48N6) · [Wikipedia S-400](https://en.wikipedia.org/wiki/S-400_missile_system) · [GlobalSecurity S-400 missiles](https://www.globalsecurity.org/military/world/russia/s-400-missiles.htm) · [Deagel 40N6](https://www.deagel.com/Weapons/40N6/a000990) · [DRAS S-400 Part 3](https://dras.in/s-400-triumph-missiles-for-air-defence-part-3-of-3/)

---

## 6. 9M317 and 9M317M/9M338 (Buk rounds)

Naming caution: the two "Buk rounds" are **9M317** (Buk-M1-2 / Buk-M2, rail-launched) and **9M317M** (Buk-M3, canister-launched, more compact). The designation **9M338 is actually the Tor-M2 round**, not a Buk round — several sources conflate them. Documented here as 9M317 vs 9M317M with the 9M338/Tor caveat.

### 9M317 (Buk-M2 / SA-17)
| Spec | Value |
|---|---|
| Length | ~5.5 m |
| Diameter | ~0.4 m |
| Wingspan | ~0.86 m (860 mm) |
| Launch mass | ~710–715 kg |
| Warhead | ~70 kg |

### 9M317M (Buk-M3)
| Spec | Value |
|---|---|
| Length | ~5.18 m (shorter) |
| Diameter | ~0.36 m (slimmer) |
| Fin span | ~0.82 m (820 mm) |
| Launch mass | ~581 kg (lighter) |
| Warhead | ~62 kg |
| Note | **Canisterized** (flies from a sealed tube), dual-mode seeker |

**Nose shape:** ogive/pointed housing SARH or active radar seeker.

**Fin layout (both, "normal aerodynamic scheme"):**

| Group | Count | Position (frac) | Shape | Fixed/Moving | Steers? |
|---|---|---|---|---|---|
| Fixed forward/mid wings | 4 | ~0.45–0.6 | Long low **clipped-delta**, cruciform (9M317 has smaller chord than the older 9M38) | Fixed | No |
| Tail control fins | 4 | ~0.9–1.0 | Clipped-delta / trapezoid, cruciform | Moving | **Yes** |

**Distinctive signatures:** classic tail-controlled cruciform SAM. 9M317M (Buk-M3) is **shorter, slimmer, lighter** than 9M317 and flies from a **tube** — if the game shows Buk-M3 as a bare rail round it is wrong. References: `buk_9m317_lineart.svg` (line drawing — best for fins), `buk_9m317_photo_01.jpg`.

Citations: [Wikipedia Buk](https://en.wikipedia.org/wiki/Buk_missile_system) · [en.missilery.info Buk-M3](https://en.missilery.info/missile/bukm3) · [Deagel 9M317](https://www.deagel.com/Defensive%20Weapons/9M317/a003645)

---

## 7. 57E6 (Pantsir round) — the distinctive two-stage pencil

| Spec | Value |
|---|---|
| Length | 3.3 m |
| Diameter | 170 mm (booster) tapering to a **very thin dart sustainer** (~90 mm class) |
| Launch mass | ~75.7 kg |
| Warhead | ~20 kg continuous-rod/frag |
| Propulsion | Two-stage tandem, solid |

**Nose shape:** blunt-ish pointed dart; command-guided (radio + optical track), so **no seeker dome** — a beam-riding/command round.

**Fin layout (this is the unusual one):**

| Group | Count | Position (frac) | Shape | Fixed/Moving | Steers? |
|---|---|---|---|---|---|
| Booster stage | — | rear ~0.4 of length | Fat 170 mm cylinder, small fixed tail fins | Fixed | boost only, then **separates** |
| Sustainer dart tail fins | 4 | ~0.9–1.0 of the thin dart | Small folding fins at the very tail of the thin dart | Fixed/limited | minimal — command-guided, aerodynamically stabilized |

**Distinctive signatures:** **bi-caliber "two-stage pencil"** — a fat short booster at the back and a long very-thin sustainer dart in front; the booster **burns ~2 s then drops away**, leaving an unpowered thin dart that coasts to target. Almost **no big control fins** — it is command-guided, not a fin-steered homing missile. Do NOT give it prominent cruciform steering wings. Model the fat-back / thin-front staging and the separation. Reference: `pantsir_57e6_01.jpg` (missiles on Pantsir launcher).

Citations: [Wikipedia Pantsir](https://en.wikipedia.org/wiki/Pantsir_missile_system) · [Missile Threat Pantsir S-1](https://missilethreat.csis.org/defsys/pantsir-s-1/) · [GlobalSecurity 57E6](https://www.globalsecurity.org/military/world/russia/57e6.htm)

---

## 8a. BGM-109 Tomahawk — land-attack cruise missile

| Spec | Value |
|---|---|
| Length | 5.56 m (missile) / 6.25 m with booster |
| Diameter | 0.52 m (527 mm) |
| Wingspan | ~2.67 m (deployed) |
| Launch mass | ~1,300–1,600 kg with booster |
| Propulsion | Solid booster then **turbofan** cruise |

**Nose shape:** rounded/ogive (subsonic).

**Fin layout:**

| Group | Count | Position (frac) | Shape | Fixed/Moving | Steers? |
|---|---|---|---|---|---|
| Pop-out cruise wings | 2 | ~0.5 (mid) | **Swept plank wings that deploy from a slot**, high aspect | Deploy then fixed | No (lift) |
| Tail control fins | 3 or 4 | ~0.95–1.0 | Early blocks: 4 cruciform (+). **Block IV/V (BGM-109E): 3 fins in an inverted-Y** | Moving | **Yes** |
| Booster fins | 4 | booster tail | small fixed fins on the jettisonable booster (NO grid fins) | Fixed | boost stabilize |

**Distinctive signatures:** mid-body **pop-out swept wings** (higher aspect ratio than Kalibr's straighter planks); modern blocks use a **3-fin inverted-Y tail** (a good way to distinguish a modern TLAM from the 4-fin Kalibr); plain conical booster (no lattice fins). References: `tomahawk_underview_01.jpg` (underview shows wing/fin plan).

Citations: [Wikipedia Tomahawk](https://en.wikipedia.org/wiki/Tomahawk_missile) · [GlobalSecurity BGM-109 specs](https://www.globalsecurity.org/military/systems/munitions/bgm-109-specs.htm)

## 8b. AGM-158 JASSM — stealth cruise missile

| Spec | Value |
|---|---|
| Length | ~4.26 m |
| Diameter/body | ~0.55 m (non-circular, flat-sided low-observable cross-section) |
| Wingspan | ~2.4–2.7 m (deployed) |
| Launch mass | ~1,020 kg |

**Nose/body shape:** faceted, **chined low-observable body** — a rounded-triangular / trapezoidal cross-section, NOT a plain cylinder. This is the key modelling point: JASSM is not a tube.

**Fin layout:**

| Group | Count | Position (frac) | Shape | Fixed/Moving | Steers? |
|---|---|---|---|---|---|
| Mid wings | 2 | ~0.45–0.55 | Folding **trapezoidal mid-body wings** | Deploy then fixed | No (lift) |
| Tail | 1 | ~0.95–1.0 | **Single dorsal vertical tail** (plus small control surfaces) | Moving | **Yes** |

**Distinctive signatures:** **single vertical tail fin** (not cruciform), stealth faceted body, folding trapezoidal wings, flush inlet. If the model is a round tube with cruciform fins, it is very wrong. Reference: download blocked (429). URLs: `https://upload.wikimedia.org/wikipedia/commons/a/a5/AGM-158_JASSM_at_Radom-2023.jpg` and File:Agm-158 JASSM.jpg on Commons.

Citations: [Wikipedia AGM-158 JASSM](https://en.wikipedia.org/wiki/AGM-158_JASSM) · [designation-systems.net m-158](https://www.designation-systems.net/dusrm/m-158.html)

## 8c. AGM-88 HARM — anti-radiation

| Spec | Value |
|---|---|
| Length | ~4.17 m |
| Diameter | 0.254 m (254 mm) |
| Wingspan | ~1.13 m |
| Launch mass | ~360 kg |

**Nose shape:** pointed cone (passive anti-radiation seeker).

**Fin layout:**

| Group | Count | Position (frac) | Shape | Fixed/Moving | Steers? |
|---|---|---|---|---|---|
| Mid-body wings | 4 | ~0.45–0.6 | **Double-delta (long thin cropped-delta) wings mounted mid-body**, cruciform | Fixed | No |
| Tail control fins | 4 | ~0.9–1.0 | Small clipped, cruciform, in-line | Moving | **Yes** |

**Distinctive signatures:** the **long mid-body double-delta cruciform wings** are the signature — they run along much of the mid/aft body and are unusually long-chord; small tail fins behind. (Newest AGM-88G/AARGM-ER swaps mid-wings for strakes — but classic HARM = mid-body double-deltas.) References: `harm_museum_01.jpg`.

Citations: [Wikipedia AGM-88 HARM](https://en.wikipedia.org/wiki/AGM-88_HARM) · [GlobalSecurity AGM-88 specs](https://www.globalsecurity.org/military/systems/munitions/agm-88-specs.htm)

---

## 9. RIM-66 SM-2 and RIM-174 SM-6 (Standard Missile)

### RIM-66 SM-2MR (medium range)
| Spec | Value |
|---|---|
| Length | ~4.72 m (MR, no booster) |
| Diameter | 0.343 m (343 mm) |
| Wingspan | ~1.07 m |
| Launch mass | ~707 kg |

### RIM-174 SM-6 (ERAM)
| Spec | Value |
|---|---|
| Length | ~6.55 m (with Mk 72 booster) |
| Diameter | 0.343 m body, **0.53 m booster** |
| Launch mass | ~1,500 kg with booster |
| Seeker | Active (AIM-120C AMRAAM seeker) on an SM-2ER Blk IV airframe |

**Nose shape:** pointed ogive.

**Fin layout (Standard family pattern):**

| Group | Count | Position (frac) | Shape | Fixed/Moving | Steers? |
|---|---|---|---|---|---|
| Mid-body wings | 4 | ~0.4–0.7 | **Long-chord narrow strake-like wings** running much of the mid-body, cruciform | Fixed | No |
| Tail control fins | 4 | ~0.9–1.0 | Clipped-delta, cruciform | Moving | **Yes** |
| Booster (SM-6/ER) | 4 | booster tail | Mk 72 booster with its own 4 fins, **wider 0.53 m** | Fixed | boost stabilize |

**Distinctive signatures:** long thin mid-body strake-wings + tail control (tail-controlled). **SM-6 is a two-piece stack: a slim 0.343 m dart on a fatter 0.53 m Mk 72 booster** — model the booster as a distinctly wider aft section. SM-2MR (single-stage, no wide booster) is shorter and uniform-diameter. References: SM-6 profile line drawing download blocked (429); URL `https://upload.wikimedia.org/wikipedia/commons/c/c9/SM-6_Missile_Profile.png`.

Citations: [Wikipedia RIM-174 ERAM](https://en.wikipedia.org/wiki/RIM-174_Standard_ERAM) · [Wikipedia RIM-66 Standard](https://en.wikipedia.org/wiki/RIM-66_Standard) · [designation-systems.net m-174](https://www.designation-systems.net/dusrm/m-174.html)

---

## 10. AIM-9X Sidewinder and AIM-120 AMRAAM (fighter rounds)

### AIM-9X Sidewinder (short-range IR)
| Spec | Value |
|---|---|
| Length | ~3.02 m |
| Diameter | 0.127 m (127 mm / 5 in) |
| Wingspan | ~0.45 m (tail); fins small |
| Launch mass | ~85 kg |

**Fin layout:**

| Group | Count | Position (frac) | Shape | Fixed/Moving | Steers? |
|---|---|---|---|---|---|
| Forward canards / control fins | 4 | ~0.15–0.25 | Small **cropped-delta canards near the nose** | Moving | **Yes** (AIM-9X uses thrust-vectoring + small canards; earlier -9 used rollerons) |
| Tail fins | 4 | ~0.9–1.0 | Small cropped-delta; **AIM-9X has clipped low-drag tails** (older 9M had rolleron rollers) | Fixed | roll/stabilize |

**Distinctive signatures:** very **thin 127 mm tube**; small fins; AIM-9X has **jet-vane thrust vectoring** at the tail and small clipped tails (no big rolleron paddles of legacy Sidewinders). Reference: line-art `aim9x_lineart.svg`.

### AIM-120 AMRAAM (medium-range active radar)
| Spec | Value |
|---|---|
| Length | ~3.65 m |
| Diameter | 0.178 m (178 mm / 7 in) |
| Wingspan | ~0.48–0.53 m (A/B); ~0.45 m (C/D, clipped) |
| Launch mass | ~152 kg |

**Fin layout:**

| Group | Count | Position (frac) | Shape | Fixed/Moving | Steers? |
|---|---|---|---|---|---|
| Mid-body wings | 4 | ~0.5–0.6 | Small **strake-like clipped wings**, cruciform (C/D clipped smaller for internal carriage) | Fixed | No |
| Tail control fins | 4 | ~0.9–1.0 | Clipped-delta, cruciform | Moving | **Yes** |

**Distinctive signatures:** slim 178 mm body, **tail-controlled** (control at the back, small fixed mid-wings) — the opposite of the AIM-9X which controls at the front. AMRAAM is longer and fatter than the Sidewinder. Reference: `aim120_udvar_01.jpg`, and mislabeled `aim9x_side_01.jpg` (actually an AMRAAM museum shot — usable for AMRAAM).

Citations: [Wikipedia AIM-9 Sidewinder](https://en.wikipedia.org/wiki/AIM-9_Sidewinder) · [Army Recognition AMRAAM](https://www.armyrecognition.com/military-products/army/missiles/tactical-missiles/amraam-aim-120-air-to-air-missile) · [Sandboxx AIM-120 specs](https://www.sandboxx.us/news/references/weapon-systems/specs-aim-120-advanced-medium-range-air-to-air-missile-amraam/)

---

# COMPARISON: 48N6 vs 40N6 (the critical pair — currently ONE model in-game, which is wrong)

| Attribute | 48N6 (48N6E/DM) | 40N6 (40N6E) | Modelling delta |
|---|---|---|---|
| Role | Long-range SAM (~150–250 km) | Very-long-range SAM (~380–400 km) | — |
| Length | ~7.5 m | ~7.8 m | 40N6 is **~0.3 m (4%) longer** — make its body visibly longer |
| Diameter | 0.519 m | ~0.5 m body (comparable; larger aft section) | Similar forebody; 40N6 aft/motor section reads chunkier |
| Launch mass | ~1,800 kg | ~1,893 kg | 40N6 **~90 kg heavier** |
| Warhead | ~143 kg | ~180 kg class | — |
| Stages | **Single-stage** solid | **Two-stage** (extra sustainer) | 40N6 should show an **interstage break / longer aft motor** |
| Seeker | SARH (needs illumination) | **Combined active + SARH** (OTH, can go active terminal) | larger nose seeker section on 40N6 |
| Fins | 4 long-chord rear cruciform control fins, folding | Same family layout; fin band sits slightly further aft due to longer body | move the fin band aft on 40N6 |
| Launcher load | **4 per TEL** | **2 per TEL** (too big for 4) | direct size sanity check: 40N6 is the bigger missile |

Bottom line: give 40N6 its **own longer, two-stage, heavier-looking mesh** with the fin band pushed aft and a bigger seeker nose; do not reuse the 48N6 model scaled up uniformly.

---

# TOP-5 IN-GAME MODEL CORRECTIONS MOST WORTH MAKING

Assuming the current models are simple cylinder + cruciform-fin low-poly bodies:

1. **Oniks/Yakhont annular ram-air inlet nose.** The hero weapon's signature is a **ringed intake nose with a central shock-cone**, not a solid pointed ogive. Fixing the nose alone makes it instantly recognizable. (Same fix conceptually applies to Kh-31's four pop-open side intakes and Zircon's ventral scramjet intake.)

2. **Split 48N6 and 40N6 into two meshes.** 40N6 = longer (7.8 vs 7.5 m), two-stage (visible interstage), heavier, bigger seeker nose, fin band further aft, and canonically only 2-per-TEL. This is the user-flagged error and the highest-value correctness fix.

3. **Give cruise missiles their real planforms, not cruciform fins.** Kalibr and Tomahawk have **mid-body pop-out plank/swept wings + a small tail set** (Tomahawk modern = 3-fin inverted-Y; Kalibr = 4-fin + **grid/lattice fins on the booster**). JASSM has a **faceted stealth body with a single vertical tail** — not a tube with cruciform fins. These three are probably all wrong if modeled as plain finned cylinders.

4. **57E6 Pantsir must be a bi-caliber two-stage pencil.** Fat short booster at the rear that **separates**, long very-thin sustainer dart in front, and **almost no large control fins** (command-guided). If it's currently a normal finned cylinder, the whole silhouette is wrong.

5. **Get "which fins steer" and control location right per class.** Tail-controlled (most: Oniks, Kh-31, HARM, Standard family, AMRAAM, Buk — control at the **back**, small/none up front) vs canard/nose-controlled (**AIM-9X** steers with **forward canards + thrust vectoring**). Also fix relative slenderness: Zircon is slimmer-for-length than Oniks; AIM-9X (127 mm) is a thin dart while AMRAAM (178 mm) is fatter and longer. Correct fineness ratios and fin band positions read as "right" even on low-poly meshes.

---

## Downloaded reference inventory (`./references/`)
- `oniks_yakhont_side_01.jpg`, `oniks_yakhont_side_02.jpg`, `oniks_sketch_lineart.png` (line drawing)
- `zircon_01.jpg` (color cutaway)
- `kalibr_3m14e_01.jpg`, `kalibr_3m14e_02.jpg`
- `kh31_armia_02.jpg`
- `buk_9m317_lineart.svg` (line drawing), `buk_9m317_photo_01.jpg`
- `pantsir_57e6_01.jpg`
- `tomahawk_underview_01.jpg` (plan view)
- `harm_museum_01.jpg`
- `aim9x_lineart.svg` (line drawing), `aim9x_side_01.jpg` (AMRAAM), `aim120_udvar_01.jpg`

Blocked by Wikimedia rate-limiting (fetch manually):
- JASSM: `https://upload.wikimedia.org/wikipedia/commons/a/a5/AGM-158_JASSM_at_Radom-2023.jpg`
- SM-6 profile line drawing: `https://upload.wikimedia.org/wikipedia/commons/c/c9/SM-6_Missile_Profile.png`
- Kh-31 Armia-2018 #1: `https://upload.wikimedia.org/wikipedia/commons/0/0a/Kh-31_Armia-2018_1.jpg`
