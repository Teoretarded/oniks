# Feature / content ideas — design menu (2026-06-15)

From my own reasoning + three independent clean-room ideation agents (lenses:
Arsenal/Threats/Sensors, Depth/Replayability, Game-Feel/Usability). Judged by:
does it deepen the game's DNA — the SENSOR/EW battle (who detects whom, fog of
war, emissions control) wrapped around the GO-LOW-TO-SURVIVE kinematic gamble,
all physics-honest? Every idea reuses an existing data model (WeaponDef /
SamDef / StrikeDef / Radar / EnemyPicture / contact board / hint+overlay).

## CONSENSUS (named independently by me + 2-3 agents = build first)
- **Threat-Warning HUD strip** — inbound count / type / bearing / time-to-impact,
  color-escalating, terminal pulse. The data already exists (launch_warning
  tracks + radar-gated hostiles carry pos/vel) and is thrown away. The
  perception layer that makes every new threat fair. high / S-M.
- **Enemy submarine + drone sonobuoy ASW (paired)** — the one threat axis the
  radar/SAR/ELINT suite physically can't find; a 2nd lose-path independent of
  the flaky back-plot; counter reuses the ELINT solver in the acoustic domain;
  turns the drone into a tasking dilemma. high / L (M for the buoy counter).
- **Salvo / ripple-fire key** — saturating the SM-2 "<=4 in flight" cap is the
  king move but the only fire verb is one SPACE. Multi-tube batteries already
  exist. high / S-M.
- **Weather / sea-state modifier** — a dial on the EXISTING physics (multipath
  band, SAR range, IR seeker): rough seas reward go-low, calm rewards stealth.
  Same seed -> different correct play. high / M.

## RANKED TOP 10 (impact x fit x low-effort)
1. Threat-Warning HUD strip (new-ui) — high/S-M
2. After-action scoring + per-seed "par" (new-system) — high/S
3. Mission types beyond Defend: Sea Denial, Decapitation, Recon-in-Force,
   Convoy Interdiction, Counter-Battery Survival, First-Strike Window (new-system) — high/M
4. Salvo / ripple-fire key (qol) — high/S-M
5. Player coastal ELINT listening array — fight the fog without emitting (new-defense) — high/S
6. Shot Debrief — WHY the round died ("KILLED BY SM-2 @94km" / "WHIFF fuel-out 12km short") (new-ui) — high/M
7. Enemy submarine + sonobuoy ASW (new-enemy+system) — high/L
8. Smart auto-time-warp (event-aware pacing) (qol) — high/M
8. Weather / sea-state (new-mechanic) — high/M
10. Enemy coordinated saturation strike (TLAM+JASSM+HARM time-on-target) (new-system) — high/M

## CATALOGUE BY CATEGORY
### new-weapon
- Anti-ship ballistic missile (ASBM) — lofted top-attack, beats the SAM ceiling not the horizon; foil to go-low; punishes stale fixes. high/L.
- Player anti-radiation loitering munition (HARM-equiv) — coastal SEAD; punishes a silent-when-threatened AWACS/jammer. high/M.
- Player decoys / chaff & EW counter-play. med/M.
### new-enemy
- Diesel submarine + sub-launched cruise salvo. high/L.
- EA-18G-class escort jammer — collapses your radar range, raises ELINT sigma; the counter to "going loud." high/M.
- Fast missile-boat skirmish layer (close-in surface). med/M.
### new-defense
- Coastal ELINT listening array. high/S.
- Medium-range SAM (Buk-class ~40-50 km) — fills Pantsir<->S-300 gap, shelters the drone. med/S.
- Active counter-battery / layer-cake base survival minigame. high/M.
### new-system
- After-action scoring + seed leaderboard. high/S.
- Mission types beyond Defend. high/M.
- Coordinated saturation strike. high/M.
- Campaign attrition ledger (chain 5-8 seeded battles, persistent ammo/damage). high/L.
- Oniks decoy/chaff terminal package. med/M.
- Time-pressure / resource-clock framing. med/S.
### new-mechanic
- Weather / sea-state. high/M.
- Enemy fleet doctrine archetypes per seed (Aggressive Push / Turtle Screen / Picket / EMCON Ambush). high/M.
- Intel-confidence ID ladder (UNKNOWN->CLASSIFIED->IDENTIFIED). high/M.
- Day/night & EMCON tempo cycle. med/M.
- Enemy wild-weasel HARM vs YOUR new emitters (shoot-and-scoot). med/S.
### new-map
- Terrain-masking / seeded archipelago presets (Island Chain / Open Sea / Narrow Strait / Fjord) — exercises the under-used terrain LOS physics. high/L.
### new-ui
- Threat-Warning strip; Shot Debrief; Contact intel panel (click a track);
  Engagement-envelope shading (estimated bubbles); Drone recon coverage feedback;
  First-battle onboarding overlay; Briefing/variable starting intel;
  Pre-launch trajectory & leak preview; Pause situation board.
### qol
- Salvo key; Smart auto-time-warp; Tube/battery status readout; Wrong-weapon
  launch guidance; Audio cue layer; Quick-look camera jump-to-action; Measure tool.

## QUICK WINS (high impact, S effort): after-action scoring, coastal ELINT array,
salvo key, threat strip (S-M), tube status, wrong-weapon guidance, starting-intel.
## BIG BETS (high impact, L effort): submarine+ASW, archipelago maps, ASBM, campaign ledger.

## RECOMMENDED FIRST MILESTONE (mutually reinforcing, mostly quick wins)
Threat-Warning strip (legibility) + Salvo key (the winning answer) + After-action
scoring (reason to replay) + Shot Debrief — then the Submarine/ASW pair as the
headline new axis (the strip exists precisely to make it fair).
