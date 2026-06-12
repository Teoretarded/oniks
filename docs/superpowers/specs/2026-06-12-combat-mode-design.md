# COMBAT Mode — Design Spec

Date: 2026-06-12
Status: Approved pending user review

## 1. Overview

A new game mode, **COMBAT**, alongside the existing SANDBOX. The player (coastal
defense: Bastion/Oniks, S-300, plus new systems below) fights a seeded, randomly
placed enemy navy/air force (destroyers, carrier, fighters, AWACS, ground radars)
that actively hunts and strikes the player's bases. Both sides operate under
**fog of war** driven by a functional radar simulation.

SANDBOX is untouched. COMBAT reuses the engine (terrain, ocean, sky, cameras,
tactical map, effects, HUD) but spawns **none** of the old sandbox content
(no cargo/tanker/warship lanes, no old patrol aircraft, no old decorative
radar/depot/harbor sites). It keeps only: the map, the Bastion/Oniks system,
the S-300 — plus everything new in this spec.

## 2. Mode flow

- Main menu becomes `SANDBOX / COMBAT / SETTINGS / QUIT`.
- COMBAT → **Setup screen** → battle (a new `CombatState`, structured like
  `SandboxState` but with its own world builder and the combat systems wired in).

### 2.1 Setup screen

Two pages, navigable before launch:

**World page**
- Seed: type a number or press a key to randomize. Same seed + same settings =
  same battle (enemy positions derive deterministically from the seed).
- Force counts (sliders/steppers): destroyers, fighters, AWACS, enemy ground
  radar stations, player ground radar stations, Pantsir units.
- **Carrier count is always exactly 1** (displayed, not editable).
- Recon drone count (default 1) and replacement timer.

**Armory page**
- Per weapon system: ammo stock and reload seconds. No upper limit on stock.
- Covers: Oniks (loses its current infinite ammo — finite stock + reload like
  everything else), S-300 rounds, Pantsir missiles, Pantsir gun ammo.
- Defaults mirror current behavior where it exists (e.g. S-300: 4 rounds, 8 s
  tube reload) and sensible values elsewhere.

### 2.2 Win / lose

- **Win:** all enemy ships (incl. carrier), enemy ground radars, and the enemy
  airfield are destroyed.
- **Lose:** all player Bastion TELs destroyed (no Oniks = no offense).
- End screen states the outcome and offers rematch (same seed) / new setup / menu.

## 3. Radar network & fog of war

Functional model — no beam scanning, no RCS math beyond a per-target size class.
Each radar is defined by:

- **Position** (and altitude for airborne radars).
- **Max detection range per target size class** (ship / fighter / missile /
  stealth-drone).
- **Radar horizon:** earth-curvature check using radar altitude and target
  altitude — a sea-skimmer at 15 m is invisible to a mast-height radar beyond
  roughly 30–40 km regardless of nominal range. (Approximation:
  `horizon_km ≈ 4.12 * (sqrt(h_radar_m) + sqrt(h_target_m))`.)
- **Terrain line-of-sight:** a coarse sampled ray against the heightfield;
  terrain masks low flyers behind hills/islands.
- **Detection delay:** 1–3 s of continuous visibility before a track forms, so
  popping over the horizon is not instant death.

**Track picture / datalink:** all surviving radars on a side feed one shared
track set for that side. A track persists while at least one radar holds it;
when nothing holds it, it becomes a fading **last-known-position** estimate
(position + velocity extrapolation, visually aging on the map) and eventually
drops. The tactical map renders only the player's picture. The enemy commander
acts only on the enemy picture.

**Shooter dependency:** the S-300 has **no organic radar**. It can only engage
tracks held by the player network (ground radar station, or Pantsir's
shorter-range radar as degraded fallback). Destroying a radar instantly removes
its coverage. Symmetrically, enemy ships rely on their own radar or AWACS cueing.

**Emissions are detectable:** a radar that is switched on can be heard by
passive sensors (player drone ELINT, enemy HARM seekers). Radars can be
silent — silent radars cannot see, but cannot be passively located either. The
enemy commander manages ship radar silence tactically; the player's ground
radars can also be toggled (later phase, simple on/off).

## 4. Player assets

### 4.1 Ground radar station (new)

- Long-range search radar, the S-300's eyes. Approx 350 km vs high targets,
  horizon-limited vs low flyers. Static, destroyable (HP like other structures),
  emits while on → prime HARM target.
- New 3D model in `models/` (existing builder style), placed on the home
  continent by the world builder; count set in setup.

### 4.2 Pantsir-S1 (new)

- Combined point-defense vehicle parked near player sites (Bastion, S-300,
  radars). Own radar: ~30 km search/track (counts toward the player network).
- **12 × 57E6 missiles:** ~20 km range, ~Mach 2.7, hittile/proximity vs cruise
  missiles, HARMs, and aircraft. Auto-engages inbound hostile missiles tracked
  by its radar; no player micromanagement required.
- **2 × 30 mm guns:** ~4 km, last-ditch hose against leakers; ammo pool,
  effective as probabilistic kill per burst at close range.
- Ammo/reload configurable in Armory.

### 4.3 Recon drone (new) — stealth ELINT/SAR aircraft

One (configurable) high-altitude, slow, unarmed stealth recon aircraft,
player-tasked with waypoints on the tactical map.

- **ELINT (passive):** hears emitting enemy radars from far away. One
  intercept = a bearing line; the fix sharpens over minutes as the drone moves
  (triangulation). Emitting destroyers/AWACS/ground radars get located
  eventually from total safety. Silent emitters are invisible to ELINT.
- **SAR/optical (look-down):** narrow footprint, ~50 km strip beneath the
  drone. Finds non-emitting targets (airfield, silent carrier, parked units)
  but requires flying over/near them.
- **Stealth:** enemy radars detect the drone at **~10% of normal range**:
  SPY-1 ~30 km, AWACS ~40 km, F/A-18 nose radar ~11 km (nose cone only),
  enemy ground radar ~35 km. The 50 km SAR strip lets a careful player image a
  destroyer from just outside its 30 km bubble.
- **Once detected, the enemy knows exactly what it means** and reacts
  instantly: silent ships may light up, fighters get vectored to the contact.
- **Radar warning receiver:** drone passively detects search illumination and
  fire-control lock; HUD/map shows "ILLUMINATED" / **"TRACKED"** alerts. Turning
  cold exits a 30 km bubble in ~60–90 s.
- **Survivability:** SM-2 vs the tiny stealth target has degraded Pk at long
  range (~35% at envelope edge, near-certain up close). Outside the bubble the
  track fades — enemies search the last-known area but must reacquire.
- **Intel ages:** drone-found contacts become fading last-known-position
  estimates like any lost track.
- If shot down, a replacement arrives after a long timer (configurable).

### 4.4 Existing systems

- **Oniks:** unchanged flight logic (preset profile/waypoints + terminal
  seeker — it is *not* an autopilot system; lo-lo keeps the existing
  altitude-hold sea-skim). Gains finite ammo + reload via the Armory.
- **S-300:** unchanged interceptor; now gated on the player track picture
  (no radar = blind) and Armory-driven ammo/reload.
- All player structures (Bastion TELs, S-300 TEL, radars, Pantsir, drone
  base if modeled) gain HP and destroyed states.

## 5. Enemy order of battle

Positions generated from the seed: fleet at sea on/near the enemy side,
airfield + ground radars on the enemy continent, AWACS orbit deep.

### 5.1 F/A-18E-class fighters

- Nose radar ~110 km vs fighter-size (forward cone), less vs missile-size.
- **4 hardpoints** per sortie, loadout chosen by the commander per mission:
  - **AGM-158 JASSM-class** standoff land-attack cruise missile: ~370 km,
    subsonic, terrain-skimming, GPS/INS to fixed coordinates (player bases) —
    the Pantsir's main customer.
  - **AGM-88 HARM-class** anti-radiation missile: ~110 km, fast, homes on
    *emitting* radars; loses lock (degrades to last-known impact point) if the
    radar goes silent.
  - *(Designed but not enabled in v1: Harpoon-class anti-ship — for the future
    friendly-ships update.)*
- Behavior loop: `PARKED → TAKEOFF → INGRESS (low when player radar net is
  up) → LAUNCH at standoff range → EGRESS → LAND → REARM (timer) → repeat`.
- Rearm at the **nearest surviving base** (airfield or carrier). Both
  destroyed → airborne fighters fight until winchester, then are effectively
  out of the war (fly to map edge / ditch).

### 5.1b Fleet placement (seeded spawn zone)

One zone, one mechanism (`world/spawn_zones.py`, wired into generation in
Phase 7): ships spawn in an ocean sector fanning from the player base
toward the enemy coast, range 110-300 km, half-angle 50°. Range is drawn
from a **triangular distribution peaking at 180 km** — anywhere in the
zone is possible, the middle band is most likely. Hulls keep >= 25 km
separation and verified open water (9 km clearance disc). The **carrier
samples a deeper 240-330 km band** (usually beyond lo-lo Oniks fuel,
~230 km flown) with up to two destroyers escorting 20-35 km off it; the
rest screen forward. Longer-range player weapons to contest the deep band
are future scope (post-Phase-8 candidate).

### 5.2 Arleigh Burke-class destroyers

- **SPY-1-class radar:** ~300 km vs high targets, horizon-limited vs
  sea-skimmers (lo-lo Oniks gets inside ~30–40 km before detection).
- **SM-2-class SAMs:** ~150 km vs aircraft/high missiles. Engages hi-flying
  Oniks at long range — hi-lo profile becomes risky. Sea-skimmers ARE
  engageable (real Aegis doctrine), but intercepts are **simulated physics,
  never probability rolls** (LOCKED, user direction): against targets below
  ~150 m the SM-2's target track carries time-correlated multipath/clutter
  noise; PN guidance chases the jittering aim point under its real max-g
  limit and the hit/miss outcome is whether closest approach falls inside
  the 20 m proximity fuse. The Oniks's existing terminal weave genuinely
  stresses the interceptor. Outcome statistics are measured by seeded probe
  batches and locked as two-sided statistical regression bands (target:
  high-altitude kill ~0.85+, sea-skim kill roughly 0.25-0.55 per shot —
  tuned via the physical noise parameter, not the outcome). Saturation
  salvos overwhelm fire-control channels naturally. Finite magazine.
- **Phalanx CIWS:** 20 mm, ~2 km auto-engage vs leakers, probabilistic kill.
- **Tomahawk-class land-attack missiles:** long-range (effectively whole-map),
  subsonic, low-flying strikes on located player bases. Finite magazine.
- Ship damage reuses the existing HP ladder (alive → burning → sinking → gone).

### 5.3 AWACS (E-2/E-3-class)

- ~400 km radar with good look-down vs low flyers — the counter to lo-lo
  Oniks and the main long-range cueing node for silent ships.
- Unarmed; orbits deep; flees threats. Killing it punches the biggest hole in
  the enemy picture. Count configurable.

### 5.4 Carrier (always exactly 1)

- Launches/recovers/rearms fighters like the airfield. Big HP pool (multiple
  Oniks hits). Escorted by destroyers; may run radar-silent inside the
  AWACS/escort umbrella — typically must be found by drone SAR.

### 5.5 Enemy airfield + ground radars

- Airfield: fixed structure on the enemy continent; destroyable (stops
  land-based sorties; surviving fighters divert to the carrier).
- Ground radars: enemy mirror of the player's stations; feed the enemy
  picture; valid Oniks targets.

## 6. Enemy commander AI

One brain per side (player side has none in v1 — the player is the brain;
Pantsir/S-300 auto-defense covered by their own logic).

- Ticks at ~1 Hz (negligible FPS cost); units execute simple orders between
  ticks. Decisions use **only the enemy track picture** (fog of war is
  symmetric).
- Doctrine, in priority order:
  1. **Find:** locate player emitters (passive bearings from HARM-capable
     flights / ESM), build target coordinates.
  2. **Blind:** HARM strikes on player radars.
  3. **Kill:** JASSM/Tomahawk strikes on Bastion TELs (win condition for the AI).
  4. **Defend:** vector fighters at detected drone/missile raids, manage ship
     radar silence, reposition the fleet, keep AWACS and carrier safe.
- Mission generator: composes strike packages (n fighters + loadout + route +
  standoff launch point), respecting weapon stocks and rearm cycles.
- Deterministic given seed + picture; debuggable via a dev overlay (later).

## 7. Weapons & physics implementation

- Every new missile reuses the existing architecture: phase machine
  (`sim/missile.py` / `sim/sam.py` pattern), guidance helpers
  (`sim/guidance.py` PN / altitude-hold / heading-steer), swept-segment OBB
  hits (`sim/damage.py`), real drag/mass/thrust numbers in the
  `sim/arsenal.py` def style.
- New defs: JASSM-class, HARM-class, Tomahawk-class, SM-2-class, 57E6,
  30 mm/20 mm gun bursts (guns are hitscan-with-travel-time probabilistic
  bursts, not per-round physics).
- Missile-vs-missile intercepts use the existing proximity-fuse approach.
- New 3D models in `models/`: ground radar station, Pantsir-S1,
  recon drone, F/A-18-class fighter, Arleigh Burke-class destroyer, carrier,
  AWACS, airfield, plus visible missiles (JASSM, HARM, Tomahawk, SM-2, 57E6)
  in the existing numpy MeshBuilder style.
- Sim stays GL-free and 120 Hz fixed-timestep; radar network and commander
  tick at reduced rates (radar ~5 Hz, commander ~1 Hz) for performance.

## 8. Build phases (each leaves the game playable)

1. **Radar network + fog of war:** sensor/track/datalink core, radar horizon +
   terrain LOS, player ground radar station (model + world placement), tactical
   map shows only the player picture, S-300 gated on the picture.
2. **Enemy ships that fight back:** destroyer model + SPY-1 + SM-2 + CIWS;
   they defend against Oniks. CombatState + minimal combat world builder
   (fixed seed, no setup screen yet).
3. **Enemy strikes back:** Tomahawk/JASSM/HARM sims, base HP/destruction,
   lose condition, radar silence mechanics.
4. **Recon drone:** ELINT bearings/triangulation, SAR footprint, RWR alerts,
   stealth detection ranges, intel aging. (Pulled forward from 6 — user
   gate: without it the player has no way to find the fleet that phases
   2-3 made hostile; until it lands the only recon is Oniks seeker
   recon-by-fire. ELINT finds ANY emitting ship — a destroyer that
   defends itself radiates and gives itself away; SAR finds silent hulls;
   the deep, silent carrier is the hardest SAR target, not the only one.)
5. **Air war:** fighter + AWACS + carrier + airfield models and behaviors,
   sortie/rearm cycle, commander AI v1. (Drone risk mechanics become real
   exactly when interceptors arrive.)
6. **Pantsir:** model + auto-engagement vs inbound missiles.
7. **Setup screen + Armory + seeded generation + win/lose screens.**
8. **Polish (rolling):** a standing backlog accumulated through phases 1-7
   (user feedback, gate critiques, deferred visuals) executed as the final
   phase — and kept open afterward as the live feedback loop. Backlog lives
   in `docs/combat_build_log.md`.

(Phases 5–7 order can flex; 1–4 are sequential.)

## 9. Reference numbers (game-tuned from real-world research)

| System | Real basis | Game value |
|---|---|---|
| JASSM-class | AGM-158B ~925 km, AGM-158 ~370 km | 370 km, Mach 0.8, 30 m cruise |
| HARM-class | AGM-88 ~110 km gw Mach 2+ | 110 km, Mach 2.0, loft profile |
| Tomahawk-class | ~1600 km, Mach 0.74 | whole-map, Mach 0.74, 30–50 m cruise |
| SM-2-class | SM-2ER ~150–190 km | 150 km, Mach 3.5, prox fuse |
| Phalanx CIWS | 20 mm, ~1.5–2 km | 2 km auto, prob. kill per burst |
| SPY-1-class | ~320+ km | 300 km (high), horizon vs low |
| AWACS radar | E-3 ~400 km+ look-down | 400 km incl. low flyers |
| F/A-18 radar | APG-79 AESA ~110+ km | 110 km forward cone |
| Pantsir 57E6 | ~20 km, Mach 2.7 | 20 km, Mach 2.7 |
| Pantsir 30 mm | 2A38M ~4 km | 4 km, prob. kill per burst |
| Player ground radar | 64N6-class ~300–600 km | 350 km (high), horizon vs low |
| Drone stealth | — | detected at 10% of normal radar range |
| Drone SAR strip | — | ~50 km wide footprint |
| SM-2 Pk vs drone | — | ~35% at envelope edge → ~90% close |

Exact aero/mass/thrust constants get finalized per-weapon during
implementation, following the research-doc pattern in `docs/` (as done for
Oniks and S-300).

## 10. Testing

- Unit tests per new sim module mirroring the existing `tests/` style:
  radar horizon math, LOS masking, track formation/fade, triangulation
  convergence, each new missile's phase machine + intercept geometry,
  commander mission generation determinism (same seed + picture → same orders),
  rearm cycle state machine.
- E2E-style: scripted scenario where a lo-lo Oniks sneaks a destroyer's
  horizon; a hi-lo Oniks gets SM-2'd; a JASSM raid is stopped by Pantsir;
  a HARM kills an emitting radar but misses a silenced one.

## 11. Out of scope (explicitly deferred)

- Player-controllable friendly ships (future update; anti-ship weapon defs
  designed to slot in then).
- Jamming/ECM, chaff/flares, beam-level radar simulation.
- Player-side AI commander.
- Multiplayer, campaign/persistence between battles.
