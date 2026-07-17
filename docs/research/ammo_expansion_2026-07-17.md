# Ammunition expansion — normative values (2026-07-17)

Companion to `icbm_reference_2026-07-17.md`; same conventions: values
marked `~` are estimates chosen to sit inside the public envelope, all
sim constants derive from THIS table (no magic numbers in code).

## 1. UGM-133A Trident II (D5) — sub-launched, MIRV

The user order is a LAKE launch: the boat sits submerged in Lake Thun
(577 m ASL, in ring 2) and the missile broaches like the Atlantic
test shots.

- Length 13.58 m, diameter 2.11 m, launch mass 59,090 kg. 3-stage
  solid + PBCS bus. Sub-launch: steam-gas generator ejects the round;
  it broaches at ~20-25 m/s, coasts unlit ~1 s, then S1 lights at
  10-30 m above the surface (famous "water column + instant pillar").
- Stage table (public envelope, `~` splits):
  - S1: gross ~39,000 kg, prop ~36,000 kg, thrust ~1,470 kN, 65 s
  - S2: gross ~11,500 kg, prop ~10,500 kg, thrust ~444 kN, 65 s
  - S3: gross ~2,800 kg, prop ~2,500 kg, thrust ~175 kN, 40 s
  - PBCS bus: ~1,200 kg dry + ~300 kg prop, ~3 kN, Isp ~300 s
- Payload: up to 8 W88 (475 kt) MIRV — the game loadout.
- Visual signatures (footage: DASO/FCET Atlantic launches):
  1. White WATER COLUMN + foam ring at broach (not smoke)
  2. Dark unlit airframe hanging over its own splash
  3. Instant brilliant aluminized pillar on light-off
  4. Fast pitch-over (much quicker than a silo ICBM)
  5. Pale grey-white column, thinner than Minuteman's

## 2. MIRV dispensing (Sarmat + Trident II)

- Sarmat loadout: 10 x ~500 kt (public "up to 10 heavy"). Trident II:
  8 x 475 kt (W88).
- Real sequence: boost ends, the bus coasts and RELEASES RVs one at a
  time, trimming cross-range between releases (bus does the delta-v,
  RV flies ballistic after release).
- Map-scale adaptation (honest mechanics, map-scale spreads): at each
  release the retarget delta-v (Lambert difference at release state)
  is applied at the release moment, releases every ~2.2 s during the
  post-termination coast, per-RV arrival staggered ~1.5 s so impacts
  WALK across the target area. Designation-time spread cap 25 km
  (release delta-v stays inside a few hundred m/s — bus-class).
- Every RV: own reentry streak, own impact event, own crater
  (per-RV yield, NOT the whole bus yield).

## 3. 9K720 Iskander-M (9M723) — quasi-ballistic pad round

- Length 7.3 m, diameter 0.92 m, launch mass 3,800 kg, single solid
  stage, hot TEL launch, near-vertical departure then hard pitch.
- Flight: quasi-ballistic, apogee ~50 km on max-range (500 km) shots;
  at map ranges it flies FLAT and FAST (Mach 5-6), terminal maneuvers.
- Sim values: boost ~75 m/s^2 for ~42 s (dv ~3.1 km/s), Cd ~0.30,
  g_max 30, warhead 700 kg HE (unitary), range 500 km.
- Visual signatures: dirty grey column much fatter than an S-300, a
  long bright exhaust, TEL-scale ground blast, and a visibly FLAT
  downrange dash instead of a loft.

## 4. Crater/yield notes

- Per-RV craters use the RV yield (475-500 kt class -> ~140-150 m
  radius by the Glasstone dry-soil scaling already in the code).
- Iskander 700 kg HE -> ~8 m radius crater (cube-root law).
