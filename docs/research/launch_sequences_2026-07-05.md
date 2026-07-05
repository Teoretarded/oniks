# Launch Sequences — how every weapon in the roster physically leaves its launcher
### Normative research document. Compiled 2026-07-05.

Purpose: give the sim one authoritative, cited description of the first seconds of flight for every
weapon in the game — cold-eject pop heights, ignition delays, booster burns, tip-over rates, and what
a FAILED launch looks like. Companion docs (do not re-derive, they are the deeper dive):
- `s300_reference.md` + `s300_tipover_physics.md` — full S-300 catapult/tip-over physics and footage frame analysis
- `oniks_reference.md` + `oniks_launch_sequence.md` — full P-800 frame-by-frame study (patent RU2240489C1 + timecoded video)

Convention used throughout: **t = 0 at first visible motion out of the tube/rail/pylon.**
Confidence marks: ★ primary/measured, ☆ secondary/estimate, ⚠ conflicting sources (recommendation given).

---

## 0. THE THREE LAUNCH FAMILIES (physics cheat-sheet)

| Family | Members here | Signature | Failure mode |
|---|---|---|---|
| **COLD (mortar) launch** — gas catapult ejects the round, motor lights in the air | S-300 48N6, DF-21D-style ASBM, (Kalibr sub-tube is a hybrid) | pop… hang… ignition kick | motor no-light → round falls back on/near the launcher, breaks up or burns; documented (§C.3) |
| **HOT launch** — motor ignites in the cell/tube/rail | SM-2/SM-6, Tomahawk, Kalibr VLS, Oniks (in-tube ride-out), Buk (rail), Pantsir (tube) | flame at the muzzle from frame 0, immediate accel | restrained firing — round burns in cell (Mk 41 design case); or thrust anomaly → tumble |
| **UNPOWERED SEPARATION** — round is dropped or gas-tossed, then transitions to powered flight | JASSM (air-drop), Switchblade/Hero (tube toss) | silent fall/coast, surfaces deploy, then engine start | engine no-start → ballistic splash; wings no-deploy → tumble |

<!-- SECTIONS 1-10 PER WEAPON FOLLOW -->

## 1. S-300 / 48N6 — vertical COLD launch (gas catapult + gas-vane declination)

**Scheme.** The 48N6 is ejected from its TPK by a gas-catapult (pneumatic cylinders + pushrods driven
by a powder pressure accumulator, ПАД). It coasts up unpowered, the motor ignites near apex, and gas
vanes (газовые рули) in the exhaust execute the programmed declination (склонение) toward the target
bearing. Full derivation and footage frame-timing: `s300_tipover_physics.md`.

### NUMBERS (48N6E-class; from s300_tipover_physics.md, cited there)
| Parameter | Value | Confidence |
|---|---|---|
| Launch mass | 1,835 kg (1,800–1,900) | ★ Nevsky Bastion, rusarmy, APA |
| Catapult ejection velocity | ~25 m/s vertical | ★ derived from 25–30 m apex |
| Pop height at ignition | **25–30 m** (48N6); ~20 m (5V55); (S-300V 9M82/83: ~50 m, different mechanism) | ★ Nevsky Bastion; ru.wiki С-300Ф; MAI |
| Ignition delay after tube exit | **1.0–1.5 s** — motor lights "at practically zero vertical speed" at apex | ★ Nevsky Bastion; Clip A frame-timing (~1.5 s exit→flame) |
| Motor thrust | ~245 kN (200–260), single-mode solid | ☆ derived |
| Burn time | 11 s ("до 12 с") | ★ Nevsky Bastion |
| Axial accel | 13 g at ignition → ~34 g at burnout | ☆ derived |
| Burnout speed | ~2,000 m/s (1,900–2,100) | ★ Nevsky Bastion, vistat |
| Tip-over (declination) mechanism | 4 gas vanes in motor exhaust, per pre-loaded autopilot program | ★ Nevsky Bastion |
| Body pitch rate | **35–50 deg/s peak war-shot** (30° at ~1 s, 60° at ~2 s after ignition); 10–15 deg/s near-vertical engagement | ★ footage frame analysis (Clips A/B) |
| Body pitch accel (commanded) | ~100 deg/s² (80–150); hardware could do 300+, autopilot caps it | ★ derived + footage |
| Path-turn cap | a_lat = T·sin(18°)/m ≈ 40 m/s² at ignition; path rate = a_lat/v | ★ derived |
| Max load factor | 25 g | ★ APA |

### Frame-timed narrative (war shot, from fixed-camera footage in s300_tipover_physics.md §3)
- **t −0.1 s** — TPK cap blown; grey catapult gas puff at the muzzle. No flame.
- **t 0.0** — round exits at ~25 m/s, dead vertical, fins unfolding. Silent-looking: no plume, just a
  green/grey telegraph pole rising on a gas cushion.
- **t 0.3–1.4** — unpowered coast, decelerating under gravity; apex ~25–30 m. The famous "hang":
  the missile visibly slows to near-zero vertical speed. This is the moment a failure would drop it back.
- **t ~1.5 (ignition)** — motor lights with a hard orange flash below the round while still vertical.
- **ign +0.3–0.4 s** — gas vanes bite: body kinks over the flame, 14° off vertical by +0.4 s.
- **ign +1.0 s** — ~30° off vertical, ~90–130 m up, speed building at ~13 g.
- **ign +2.0 s** — ~60–65°, converging on the programmed climb angle; 300–400 m altitude.
- **ign +11 s** — burnout ~2,000 m/s; coasting flight thereafter.

**Failed launch look:** eject and hang happen normally; no flash at apex; the 1.9-t round topples and
falls tube-side within ~2–3 s of exit, impacting within tens of metres of the TEL (see §C.3 for the
documented general pattern). Sim: apex-hang → tumble → ground impact at ~25 m/s + fall speed.

---

## 2. P-800 Oniks / Bastion-P — near-vertical HOT ride-out (closed-bottom canister)

**Scheme.** NOT a true cold launch. A ПАД pressurizes the sealed canister AND the dual-thrust booster
lights in low-thrust mode while still in the tube (patent RU2240489C1) — the missile exits at 25–40 m/s
with flame already at the muzzle. Booster sits inside the ramjet duct ("matryoshka"). Nose-cap pulse
motors do the pitch-over; the cap is then shot forward and the booster goes to high-thrust mode.
Full frame-by-frame study: `oniks_launch_sequence.md`.

### NUMBERS (from oniks_launch_sequence.md / oniks_reference.md, cited there)
| Parameter | Value | Confidence |
|---|---|---|
| Launch mass | 3,000 kg (3,900 kg in canister) | ★ missilery.info |
| Launch mode | hot ride-out: ПАД + booster low-thrust mode in-tube | ★ patent RU2240489C1 + footage |
| Exit velocity | **25–40 m/s** (battlemachines: 20–50) | ★ pixel measurement on timecoded video |
| Ignition delay | none (lit in tube) | ★ |
| Low-thrust ride | ~1–3 m/s² net accel, vertical to ~100–250 m | ★ footage |
| Tip-over mechanism | nose-cap pulse motors (pitch pair, yaw pair, 4 roll, 2 pull-away) — NOT TVC, NOT fins | ★ patent + militaryrussia.ru |
| Tip-over rate | **~90–120 deg/s peak** (15°→90° in ~0.75–1.0 s, ground test); ship shots stop at 40–50° | ★ frame analysis |
| Tip-over timing | initiate ~1.5–2.5 s, complete + cap-off ~2.5–3.5 s | ★ timecoded video |
| Cap jettison → high thrust | immediately after cap separation | ★ patent |
| Booster burn (total) | "a few seconds"; **~Mach 2 at ~7–10 s**, then slug ejected out the nozzle by ram air | ★ militaryrussia/testpilot ⚠ no decimal burn time published — sim 8 s |
| High-thrust accel | ~6–8 g longitudinal (tuned; consistent with "supersonic in ~7 s") | ☆ |
| Ramjet cruise | M2.0 lo / M2.5–2.6 hi (680–750 m/s), 4,000 kgf | ★ |
| Salvo interval per TEL | 2–5 s between the 2 canisters | ★ K-300P wiki |

### Frame-timed narrative — see `oniks_launch_sequence.md` §3 for the full 10-row table
Compressed: muzzle fireball at t −0.3 → exit 25–40 m/s t 0 → fins snap 0.2–0.5 → heavy vertical ride
0.5–2.0 (to ~100–200 m) → nose thrusters kick, 90–120 deg/s pitch ~1.5–2.5 → cap shot forward + high
thrust ignition ~2.5–3.7 → brutal flat boost to M2 by ~7–10 s → booster slug spat out, ramjet lights.

**Failed launch look:** if the booster fails in-tube the round never leaves (canister fire); if
high-thrust mode fails after cap-off, the round is at ~150–250 m, 40–60 m/s, nose already tilted —
it arcs over and impacts 100–400 m downrange within ~5–8 s, likely with booster still burning weakly.

---

## 3. 3M-54/3M14 Kalibr — cold/"warm" vertical eject + TVC booster

**Scheme.** Ship 3S14 UKSK: cold-family vertical eject (analysts note the heavy round is likely
thrown by a low-pressure slow-burning charge — "'warm' launch is a better description",
russiadefence.net UKSK thread), then a **thrust-vectoring solid booster** ignites in the air and
pitches it toward the target (the TVC is CONFIRMED: the sub-tube variant explicitly carries a
conventional non-TVC booster instead — en.wikipedia.org/wiki/Kalibr_(missile_family)). Sub launch:
encapsulated eject from a 533 mm tube at ~30–40 m depth, breaches, booster lights in air.

### NUMBERS
| Parameter | Value | Confidence / source |
|---|---|---|
| Launch mass (3M14) | 1,770 kg | ★ missilery.info/3m14e |
| Eject velocity | ~15–25 m/s | ☆ ESTIMATE (unpublished) — sim 20 |
| Ignition delay after eject | ~0.3–1.0 s | ☆ ESTIMATE — sim 0.5 |
| Booster thrust / burn | ~26 kN / ~11 s | ☆ ESTIMATE by Tomahawk analogy — unpublished |
| Sustainer | turbojet 450 kgf (~4.4 kN), 37-01E/TRDD-50 class | ★ missilery.info/3m14e |
| Cruise | Mach 0.8 at 20 m over sea / 50–150 m over land | ★ missilery.info/3m14e |
| Terminal sprint (3M54 only) | separable solid 3rd stage, Mach 2.9, ~4.6 m skim | ★ CSIS SS-N-27 |

**Every launch-phase number for Kalibr is an engineering estimate** — Novator/Russian MoD publish
none of them. The sim's TLAM-derived profile (eject 10 m/s, 0.5 s, 27.5 kN/12 s) is inside the
defensible band.

---

## 4. BGM-109 Tomahawk — Mk 41 VLS HOT launch (the best-documented booster in the roster)

**Scheme.** HOT: the Mk 106/Mk 135 booster ignites INSIDE the cell (plenum/uptake vents the efflux).
Definitive numbers from designation-systems.net (Parsch): **booster 26.7 kN (6,000 lbf), 12 s burn**;
deploy order after clearing the launcher: tailfins → wings → ventral scoop → booster jettison
(breakaway bolts after complete burnout) → F107 turbofan start (2.67 kN). Jet-tab TVC noses it toward
the target immediately after cell exit (missilery.info/bgm109b-e; 1979 JPL jet-tab TVC paper).
T/W ≈ 1.9 at ignition on ~1,450 kg. Subsonic at burnout.

### Frame-timed narrative
- **t 0.0** — booster lights in-cell: flame erupts from the missile's own hatch AND the adjacent
  shared uptake — the double-source blast unique to Mk 41.
- **t 0–2 s** — vertical ride on a brilliant plume, ~9 m/s² net rising as propellant burns; tailfins
  then wings snap out.
- **t ~1–3 s** — steerable nozzle starts the nose-over toward the target bearing.
- **t ~12 s** — burnout; scoop out, booster kicked off by breakaway bolts (visible puff, small object
  tumbles away) — **and the smoke trail simply STOPS**: turbofan cruise is near-smokeless.
- **fly-out** — descends to 30–50 m AGL, Mach 0.74.

**Failed launch look:** restrained firing — cell fire venting through the uptake, round never emerges.

---

## 5. AGM-158 JASSM — air-drop, nose-down, unpowered separation

**Scheme.** Dropped from bay/pylon; documented **nose-down pitch moment at release** (B-1 external-
pylon test, theaviationist.com 2020). Wings + tails deploy by pyrotechnic actuators within the first
~1–2 s (500 fps cameras used specifically to film fin deploy). Engine: **Teledyne J402 turbojet,
3.0 kN** (the F107 belongs to the -ER only — correct any doc saying otherwise). Canonical drop
condition: 30,000 ft / Mach 0.85 (Boeing 1998 separation test). Per-second timeline is NOT public;
recommended sim values (flagged estimates): wings out ~0.8–1.2 s, engine light ~2.0 s, thrust ramp
1–2 s, stable powered cruise by ~5–6 s. The game's eject_time 1.0 s free-fall then motor is inside
the band.

---

## 6. Buk 9M317 — inclined-rail HOT launch off the 9A310 TELAR

**Scheme.** The dual-thrust solid motor ignites ON the elevated rail; the round clears the ~5.5 m
beam in well under 0.5 s and departs straight along the beam vector — **no eject, no hang, no
tip-over phase**. Rail elevation is target-cued (~20–70°, estimate). Total burn ~15 s (boost/sustain
split unpublished; est. boost 3–4 s). Peak speed **1230 m/s**, airframe limit **24 g**
(missilery.info/buk-2m, /bukm3; en.wikipedia.org/wiki/Buk_missile_system).

**Visual:** instant bright exhaust bloom washing over the beam, thick smoke trail on a straight
climbing departure — the launch LOOKS violent from frame 0, unlike every vertical launcher here.

---

## 7. Pantsir 57E6 — canister gas-eject + 1.5 s sprint booster + unpowered dart

**Scheme.** "Solid propellant booster motor **with gas ejector**" (weaponsystems.net/system/1604-57E6)
from a sealed tube on the slewing turret: brief soft-eject, booster lights ~immediately, burns
**~1.5–2 s to 1300 m/s** (army-technology: "t = 1.5 s, Vmax = 1300 m/s" — avg 66–88 g!), then the
fat 170 mm booster SEPARATES and the thin 76–90 mm **dart coasts unpowered**, decelerating
1300 → 900 m/s (12 km) → 780 m/s (18 km) while maneuvering on radio command.

**Visual:** muzzle gas puff, then a brief violent bright boost — the least smoky trail of the SAM
roster ("needle" trail, reduced-smoke propellant) — then flame CUTOFF and a dark, fast, flameless
dart. **Sim note:** the game's 18 kN / 3.5 s motor is a softer profile than the real ~55 kN-class /
1.5 s sprint; flagged for a possible per-weapon boost re-tune (NOT changed in the 2026-07-05 energy
build — the coasting-dart deceleration is what the new induced-drag model now renders honestly).
## 8. RIM-66 SM-2 / RIM-174 SM-6 — Mk 41 VLS HOT vertical launch + TVC tip-over

**Scheme.** Hot launch: the motor ignites inside the canister, efflux vents through the Mk 41
plenum/uptake, the missile punches through the frangible canister cover. The definitive open
description (JHU APL Technical Digest V22-N03, Sullins — describes SM-3, which shares the identical
Mk 72 first stage, Mk 104 second stage and Mk 41 launch): *"the missile is launched from the Vertical
Launching System (VLS) and is accelerated by the Mk 72 solid propellant rocket motor. During this
'boost' phase, four thrust vector-controlled nozzles at the aft end of the Mk 72 provide the missile
control. The missile pierces the canister cover during egress, flies vertically until it reaches a
safe distance from the ship, and then maneuvers to fly to a predetermined point. Upon burnout of the
Mk 72 motor, separation of the first and second stages occurs, and the second-stage Mk 104 solid
propellant rocket motor is ignited."*
(https://secwww.jhuapl.edu/techdigest/content/techdigest/pdf/V22-N03/22-03-Sullins.pdf)
CSIS: the SM "is fired vertically and pitches over to align its velocity vector with initialized
commands" (https://missilethreat.csis.org/defsys/sm-2/). SM-2MR has no Mk 72 — its integral Mk 104
dual-thrust motor's boost grain does the same job with aerodynamic tip-over once moving.

### NUMBERS
| Parameter | SM-2MR (RIM-66) | SM-6 (RIM-174) | Confidence / source |
|---|---|---|---|
| Launch mass | 708 kg | 1,500 kg (Jane's 1,398–1,509) | ★ wiki/designation-systems/Jane's |
| Length / dia | 4.72 m / 0.343 m | 6.55 m / 0.343 m (0.53 m booster) | ★ |
| Booster | — (Mk 104 boost grain) | Mk 72: 712 kg total, 468 kg HTPB-AP propellant, 4 TVC nozzles | ★ Jane's/missilery |
| Booster burn time | ~6 s boost grain | **6 s**, then jettison | ★ missilery.info/standard-6 |
| Booster avg thrust | ≈154 kN (derived: 360 kg prop × Isp 262.5 s / 6 s) | **≈200 kN** (derived: 468 kg × 262.5 s × 9.81 / 6 s) | ☆ DERIVED — no open thrust figure; "270 kN" folklore is high |
| Initial net accel | **~21 g** | **~12.6 g** | ☆ derived from above |
| Ignition delay | none — hot launch | none | ★ |
| Vertical hold before tip-over | — | ~1 s ("safe distance from the ship") | ★ APL (qualitative) → sim 1 s |
| Tip-over | aerodynamic, once moving | **TVC pitch onto bearing complete by ~2 s** | ★/☆ APL narrative; rate not published — sim ~40–60 deg/s |
| Sustainer | Mk 104 DTRM: 488 kg, 360 kg TP-H1205/6, Isp 260–265 s | Mk 104 (same), lights at staging t≈6 s | ★ missilery |
| Max speed | Mach 3.5 | Mach 3.5 | ★ |
| Airframe lateral g | ~30 g class (widely cited, no single authoritative source) | ~30 g | ⚠ informed estimate |

### Frame-timed narrative (SM-6 war shot)
- **t 0.0** — Mk 72 ignites IN the cell; flame and smoke erupt from both the cell hatch and the
  adjacent uptake vents; missile punches through the frangible cover already accelerating at ~12 g.
- **t 0.2–1.0** — vertical ride on TVC, ship-length clearance in under a second; huge white plume.
- **t ~1–2 s** — hard programmed TVC pitch-over onto threat bearing — visibly "leans" out of the
  vertical column and departs at an angle. (This is the classic Aegis launch photo look.)
- **t 6 s** — Mk 72 burnout + separation; Mk 104 lights; booster tumbles away.
- **fly-out** — Mach 3.5, ~30 g-class terminal maneuvering.

**Failed launch look (hot VLS):** "restrained firing" — the round burns in the cell (the Mk 41 is
designed to contain it, venting flame through the uptake); the visible signature is a cell fire, not
a falling round. A TVC failure just after egress is a tumble into the sea within ~2–4 s.

---

## 9. Anti-ship ballistic missile (DF-21D-style) — TEL vertical COLD launch, slow majestic rise

**Scheme.** Confirmed COLD launch. CSIS: the DF-21 "is cold-launched from its canister, with **motor
ignition occurring about 20 m above the launch vehicle**" (https://missilethreat.csis.org/missile/df-21/).
missilery.info: launch "is carried out directly from the transport and launch container with the help
of special PAD [powder gas generator] placed on the bottom of the container. The first stage marching
engine is switched on after the rocket leaves the container." (https://en.missilery.info/missile/df21)
Chinese cold-eject patents describe ignition after a set clearance distance
(https://patents.google.com/patent/US7398721B1). The wheeled TEL "requires firm ground when firing"
(https://en.wikipedia.org/wiki/DF-21) — consistent with the recoil of a 15-t cold eject.

### NUMBERS
| Parameter | Value | Confidence / source |
|---|---|---|
| Launch mass | 14,700 kg (base) / 15,200 kg (DF-21A) / ~15,000 kg (DF-21D) | ★ missilery/CSIS/wiki |
| Length / dia | 10.7 m / 1.4 m, 2-stage solid | ★ |
| First-stage mass | ~7,800 kg | ★ missilery |
| Launch method | COLD — PAD eject from canister | ★ CSIS + missilery |
| Ignition height | **~20 m above the TEL** | ★ CSIS |
| Ejection velocity | ~20–35 m/s (derived from 20 m pop) | ☆ DERIVED — sim 25–30 m/s |
| Ignition delay | ~1–2 s after eject | ☆ DERIVED |
| Initial net accel after ignition | liftoff T/W ≈ 1.5–2.2 → **~0.5–1.2 g net** — the slow, heavy climb | ☆ DERIVED (no published thrust) |
| First-stage burn | ~50–60 s (class-typical large solid MRBM; not published) | ⚠ estimate — sim 55 s |
| Terminal speed | ~Mach 10 MaRV dive | ★ CSIS |
| Range (DF-21D) | 1,450–1,550 km | ★ CSIS |

### Frame-timed narrative
- **t −0.2** — PAD fires in the erected canister: a fat grey-white gas puff at the muzzle, no flame.
- **t 0.0** — the 15-tonne round emerges at ~25–30 m/s. Utterly silent-looking compared to its size.
- **t 0.5–1.5** — engine-off float to ~20 m above the vehicle, visibly decelerating — the hang.
- **t ~1.5 (ignition)** — first stage lights ~20 m up: massive orange flash and dust blast under the
  round. Then the DEFINING look: it barely climbs at first (~0.5–1 g net), a slow majestic rise that
  visibly accelerates over the next 10 s as propellant burns off.
- **t +5–10 s** — still near-vertical, building speed; then a gentle pitch program/gravity turn tips
  it downrange. No hard SAM-style tip-over — a ballistic missile leans, it does not whip.
- **t ~55 s** — first-stage burnout/staging, high in the sky.

**Failed launch look:** identical cold-launch failure family as the S-300 but far worse: a 15-t round
falling from ~20 m lands on or beside the TEL — catastrophic for the launcher. Sim: eject → hang →
no flash → topple → TEL destroyed.

---

## 10. Loitering munition (SWARM) — pneumatic/booster cell toss

**Scheme.** Two real families: pneumatic cold pop (Switchblade/Hero-120/Warmate — "the propeller,
wings and tail are extended immediately after launch", designation-systems.net) and small solid
booster kick (Harop: booster to height+speed, jettison, main engine takeover 2–4 s,
airforce-technology.com). Recommended sim (est., unpublished): muzzle 25–35 m/s, coast 0.2–0.5 s,
wings snap out ~0.4 s, motor at full power ~0.8 s, stable flight 1.5–2 s. The game's SWARM
(22 m/s eject, 0.25 s, 12 kN/1.5 s cell-clear booster) matches the booster family.

---

## C. Cross-cutting cold-launch physics + failure modes

- **Pop heights** cluster 16–30 m: Tor 16–21 m, S-300F 20–25 m, 9M96/S-400 ~30 m, DF-21 ~20 m
  (missilery.info/tor, /fort, /s400; CSIS df-21). Best attested eject velocity: **Tor ~25 m/s**.
- **Ignition trigger logic (Tor, gold standard):** motor fires at a fixed **1 s** OR at **50° of
  tilt**, whichever first → derived tip-over ~50°/s; the gas-dynamic system actively STOPS the
  rotation before ignition — the round is never tumbling when thrust arrives (missilery.info/tor).
- **Failed cold launch** (documented: HMS Vanguard Trident II, Jan 2024 — first stage no-light,
  splash "yards" from the boat): eject succeeds, hang, no flash, ballistic fall-back beside the
  launcher. Naval cold cells are canted outboard so duds splash clear (dsiac.dtic.mil).
- **Failed hot launch = restrained firing:** round burns inside the cell; >600°F warhead cook-off
  risk; water-deluge response (US patents 5,198,610 / 8,584,569).

---

## S. Cross-weapon summary — recommended sim launch constants vs. what the game has

| Weapon (game id) | Real launch | Eject v | Ignition delay | Boost | Game arsenal today | Verdict |
|---|---|---|---|---|---|---|
| s300 / 40n6 | COLD catapult, 20–30 m pop | ~25 m/s | 1.0–1.5 s | ~245 kN / 11 s | 18 m/s / 1.5 s / 200 kN / 12 s | ✔ in band |
| sm2 | HOT Mk 41, TVC | n/a | ~0 | ~154–200 kN / 6 s + Mk 104 | 20 m/s eject 0.5 s / 130 kN / 15 s | ✔ acceptable single-stage abstraction |
| sm6 | HOT Mk 41, Mk 72 6 s + Mk 104 | n/a | ~0 | ≈200 kN / 6 s | 150 kN / 16 s | ✔ single-stage abstraction |
| oniks / zircon | warm tube, ride-out + pulse-jet tip | ~30 m/s | in-tube | 300 kN-class to M2 | per oniks_launch_sequence.md | ✔ normative already |
| kalibr | cold/warm eject + TVC booster | ~20 (est.) | ~0.5 (est.) | ~26 kN / 11 s (est.) | 10 m/s / 0.5 s / 27.5 kN / 12 s | ✔ in estimate band |
| tomahawk | HOT Mk 41 | n/a | ~0 in-cell | **26.7 kN / 12 s** ★ | 10 m/s "eject" 0.5 s / 27.5 kN / 12 s | ✔ thrust/burn cited-correct; eject beat is a minor abstraction |
| jassm | air-drop nose-down | release vel | ~2 s (est.) | none (J402 3.0 kN) | 1.0 s free-fall, 3.2 kN | ✔ in band |
| buk_9m317/9m338 | HOT rail, <0.5 s clear | rail | ~0 on rail | dual-thrust ~15 s | 18 m/s / 0.3 s rail | ✔ |
| pantsir_57e6 | gas-eject + **~55 kN / 1.5 s** sprint, then unpowered dart | ~15–20 | ~0.2 | 1300 m/s at burnout | 15 m/s / 0.3 s / 18 kN / 3.5 s | ⚠ softer boost than real — flagged, not changed this build |
| asbm | COLD TEL, ~20 m pop, slow majestic rise | 25–30 | ~1–1.5 s | T/W 1.5–2.2 | 18 m/s / 1.0 s / 300 kN / 16 s | ✔ in family |
| swarm | pneumatic/booster cell toss | 25–35 (est.) | ~0.3 | small cell-clear kick | 22 m/s / 0.25 s / 12 kN / 1.5 s | ✔ |
