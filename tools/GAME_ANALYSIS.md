# COMBAT — how it works, does it work, is it balanced, what to add

Synthesis of three deep code audits + in-game testing (the `verify_*`/`pt_battle*`
harnesses). Answers the playtest questions directly.

## 1. How the enemy attacks you

Three layers, in order of how often you'll see them:

1. **Ship air-defense (SM-2) — the layer you fight most.** Each destroyer carries
   24 SM-2 (SARH, 150 km, ≤4 in flight, 3 s reload). It fires at any inbound Oniks
   its radar/AWACS-cued picture forms a track on (1.5 s track-form). This is why
   your single hi-lo Oniks gets swatted ~98 km out. It *also* hunts your drone
   (`StealthTargetSam`) — but only when the drone enters a ship's SM-2 envelope,
   which on a normal recon leg it rarely does (see §5).
2. **Fighters (AIM-9X / HARM / JASSM).** The enemy commander vectors fighters:
   AIM-9X only ever at your **drone** (the one slow IR target); HARM at your
   **radar station** (countered by going silent — `R`); JASSM at your **base**
   from 150 km standoff.
3. **Land-attack on your base (Tomahawk / JASSM) — the only way you LOSE.** The
   commander back-plots your missile tracks to a launch cluster, then orders a
   Tomahawk salvo (from ships) or JASSM package (from fighters) at your Bastion.

## 2. How you attack them

- **Recon → fire.** Fly the drone to SAR-image / ELINT-localize the fleet, get an
  actionable surface contact, then fire the Oniks at it.
- **lo-lo Oniks is the king move.** Sea-skim (60 m) keeps the Oniks under the
  SM-2 horizon and inside the multipath-noise band, so it leaks through (~50% per
  round vs SM-2's near-100% kill on a hi-lo). **Salvo lo-lo** to overwhelm — a
  single shot gets intercepted, which is correct.
- Ships have HP (destroyer 3 / carrier 6), structures 2–4. A hit = −1 HP. So
  sinking a defended destroyer takes ~3 leakers = a real salvo.

## 3. Do the weapons work? (tested — YES, all of them)

Every weapon fires, guides, and kills in code. No dead weapons. The kill is
physics-driven (guidance → fuse/OBB crossing); only the two **guns** (ship CIWS,
Pantsir 30 mm) are deliberately probabilistic last-ditch layers.

| Weapon | Owner | Role | Works |
|---|---|---|---|
| Oniks hi-lo / lo-lo | you | anti-ship | ✅ lo-lo is the reliable killer |
| S-300 48N6 | you | anti-air (150 km) | ✅ |
| S-300 40N6 | you | anti-air (380 km, **HIGH only**, 2 rnds) | ✅ niche |
| Pantsir 57E6 + 30 mm | you | point-defense | ✅ but only vs inbound *strikes* |
| SM-2 | enemy ship | anti-air self-defense | ✅ your main obstacle |
| Tomahawk / JASSM | enemy | land-attack on base | ✅ but rarely fires (§5) |
| HARM | enemy | anti-radiation | ✅ countered by radar silence |
| AIM-9X | enemy fighter | anti-air (IR) | ✅ only ever vs the drone |
| Ship CIWS | enemy | point-defense gun | ✅ but almost never reached (§5) |

## 4. Is it balanced?

- **Oniks vs SM-2 core duel: well-tuned** (emergent multipath physics — go low to
  live). This is the best part of the game.
- **lo-lo dominates hi-lo** — hi-lo is almost always a wasted round vs an alert
  ship. Intended, but it makes hi-lo feel useless unless you suppress radar first.
- **40N6 is a 2-round niche** (only reaches the deep AWACS). Wasteful otherwise.
- **Tomahawk ≈ JASSM** — mechanically the same weapon, one role filled twice.
- **Role gaps:** you have no hypersonic/long-range anti-ship punch (→ **Zircon**);
  enemy ships have no long-range area-air SAM (→ **SM-6**).

## 5. Why you "never see" Tomahawks / Pantsir / CIWS / ships shooting the drone

These are linked, and mostly **not bugs** — the enemy is *under-aggressive*, not broken:

- **Tomahawks rarely fire** because the back-plot that localizes your base needs
  3 fixes clustering within 3 km, but it mis-projects a sea-skimming Oniks by
  ~12 km (Agent C, `commander.py`), so the cluster rarely forms. **Verified:** with
  the default 2 Pantsir, the base survived 60 min; with **0 Pantsir the base WAS
  destroyed** (you can lose). So the enemy *can* win — it's just timid and the
  Pantsir is very effective.
- **Pantsir never visibly engages** because it *only* shoots inbound **strike
  missiles** — and those rarely launch (above). No strikes → nothing to shoot.
- **CIWS never seen** because your Oniks almost always gets killed by SM-2 far
  out, so it never reaches the 2 km CIWS bubble. CIWS is a last-ditch layer you
  only see if a leaker gets *very* close to a specific ship.
- **Ships don't shoot the drone** because the drone usually loiters outside the
  ships' SM-2 envelope; the SM-2 drone-hunt only triggers when it's in range.
- **Enemy planes don't dodge** your S-300 — there is no evasion logic; they fly
  straight. This is a real gap worth adding.

**The single highest-leverage fix:** repair the launch-site back-plot so the
enemy reliably localizes and strikes your base. That one change makes Tomahawks,
the Pantsir, and the lose condition all come alive.

## 6. How each side "sees" (sensors)

- **You see them** via: the 18 m radar station (ship 350 km / missile 120 km, but
  only ~46 km vs a 50 m sea-skimmer due to the horizon), the drone's SAR (25 km
  strip, surface only) + ELINT (triangulates emitting radars → ship fix) + RWR,
  the Pantsir 30 km radars (join your net), and AWACS. Everything is fog-gated on
  the tactical map; the 3D world shows truth.
- **They see you** via: ship radars + AWACS datalink + the ESM/back-plot that
  reverse-engineers your launch site from your missile tracks.
- **NEW:** you now see enemy SM-2 and AIM-9X launches the instant they fire
  (launch warning); Tomahawks stay hidden until your radar detects them.

## 7. What I'd add (brainstorm)

**Weapons (specs ready to implement):**
- **3M22 Zircon** — your hypersonic (M8) anti-ship punch that out-speeds the SM-2
  reaction window even on a high profile. The "break the SM-2 screen" tool.
- **SM-6** — enemy ship long-range (240 km) area-air + anti-surface SAM, so the
  fleet can reach out and kill your loitering drone / high Oniks, and threaten
  your base without the slow Tomahawk. It also counters the Zircon's high profile
  (forcing Zircon low too) — preserving the "go low to survive" loop.
- A player **anti-radiation** option (SEAD the enemy ground radars without flying
  an Oniks into them).

**Enemy brain (biggest gameplay win):**
- Fix the launch-site back-plot (makes the enemy actually contest your base).
- **Aircraft evasion**: when an S-300 locks a fighter, it should beam/notch/dive,
  not fly straight into the missile.
- **Coordinated strike packages**: time TLAM + JASSM + HARM to arrive together to
  saturate the Pantsir (it can only handle 3 in flight).
- Ships **maneuver** (turn into/away, make smoke) and concentrate SM-2 on the
  highest-threat leaker.

**Systems / vehicles:**
- Enemy **submarine** (sub-launched cruise missiles — a threat axis you can't see
  without ASW).
- A player **strike aircraft** or a second drone for SEAD/decoy.
- Enemy **EW/jamming** that degrades your radar picture (counter-play to going
  loud).
- Player **decoys / chaff** on the Oniks to spoof SM-2 terminal.

**QOL:**
- When you click an air contact with the Oniks active, flash "TAB to S-300 for
  air targets" (right now it silently refuses — the cause of the "can't launch"
  confusion).
- A threat-warning HUD strip (incoming count, time-to-impact) feeding off the new
  launch-warning cues.
- A salvo/ripple-fire key (hold to empty ready tubes) now that batteries exist.
- Show which tubes are loaded/reloading on the HUD.
