# Phased Build Roadmap (lead-architect synthesis)

Confirmed: `draw_panel`/`draw_header_rule` chrome primitives and the grid constants exist in `states.py`; `terrain_height_scalar` exists but there is **no `HeightField` class or `terrain_blocks` function yet** — confirming the terrain cluster's "HeightField refactor" is genuinely new machinery (a prerequisite for presets), exactly as that spec flagged. I now have everything I need.

---

# Fog-of-War Coastal Missile Combat — Phased Build Roadmap

Synthesized from 7 implementation-research clusters against the verified live codebase. Three non-negotiables hold across every milestone: **physics-not-dice** (outcomes emerge from simulated guidance/fuse/horizon, never Pk rolls), **fog-of-war honesty** (every AI/UI decision reads sensor-derived belief — `EnemyPicture`/`ElintReceiver`/`ContactBoard` — never ground truth), and **determinism** (all RNG is a seeded `np.random.default_rng([seed, tag])` child stream; tags `3..7` are taken, `8+` are free).

---

## 1. DEPENDENCY MAP

What must exist before what. Arrows = "blocks".

### Foundation layer (shared infra — build first, everything composes on it)
```
UI WIDGET PRIMITIVES (states.py: badge/gauge_bar/mini_compass/tab_strip/scroll_list/toast + hud_widgets.py)
   └─► every per-feature UI surface in every cluster

track['kind'] + track['size'] STAMPS (one-line adds in world/combat.py _update_strike_contacts + sim/contacts.py)
   └─► threat-warning strip ─► auto-time-warp inbound trigger
   └─► contact intel panel ─► ID-confidence ladder ─► AAR truth reveal

SHARED ELINT/triangulation solver already exists (sim/recon.py) — but EXTRACT to a shared module
   └─► enemy-emitter ELINT fix channel ─► player ARM target selection
   └─► acoustic AcousticReceiver (sub ASW) reuses it with no horizon check

SHARED back_plot_surface() helper (REFACTOR out of sim/commander.process_missile_track)
   └─► player Counter-Battery Radar (symmetric back-plot)  ─► corner-reflector decoys
   └─► [SOFT PREREQ] back-plot RELIABILITY pass (GAME_ANALYSIS §5: currently too timid)
        └─► shoot-and-scoot, decoys, CBR all only "pay off" once clusters reliably form

sim/ew.py FIELD MODEL (J/S burn-through) — the EW keystone
   └─► enemy Growler ─► ELINT-sigma elevation ─► player EW pod ─► JAMMED-band UI
   └─► Radar.detects(jammers=()) kwarg (must default-empty = byte-identical)

HeightField REFACTOR of terrain_height_scalar (bit-identical DEFAULT)
   └─► terrain_blocks LOS function ─► map presets (Archipelago/Strait/Fjord)
```

### Weapon/platform layer (depends on foundation)
```
emitter ELINT fix channel ─► PLAYER ARM (Kh-31P)  ─┐
                                                    ├─► enemy wild-weasel ARM vs NEW emitters ─► ARM countermeasures (scoot+decoy)
new player emitters (Pantsir radar / ARM illuminator / decoy) ─┘

ShipClassDef taxonomy (enemy_ship_classes.py) ─► flagship CEC hub / ground-attack / air-defense / carrier-integration
   └─► fleet-composition mixer (sample_fleet generalization) ─► amphibious classes ─► timed beachhead lose condition

SamMissile loft machine (EXISTS) ─► ASBM (re-pointed at ships)  [reuses SM-6 counter that EXISTS]
Missile route+Mach-hold (EXISTS) ─► swarm + commanded_speed simultaneous-arrival

Submarine + Kalibr (reuse Destroyer racetrack + StrikeDef) ─► sonobuoys + datum back-plot (reuse shared solver)

relocate() generic launcher API ─► shoot-and-scoot ─► Buk mid-SAM (reuses relocate + Pantsir radar-net pattern) ─► CBR
```

### Meta layer (depends on most gameplay existing)
```
SCORING (read-only end pass) ─► CAMPAIGN (resupply scaled by grade; battle_idx threading)
   needs: per-seed PAR; world.ledger; status panel; salvo key (attrition cost)
auto-time-warp ─ needs threat strip's threat_rows() for fog-safe inbound drop
```

**Critical hard ordering takeaways:**
1. **UI primitives → all feature UI.** No bespoke widgets before the shared kit.
2. **Threat strip + `track['kind']`/`['size']` stamps → sub axis, EW UI, auto-warp** (they're how the player reads any new threat).
3. **`sim/ew.py` → all four EW features** (one model, many callers).
4. **HeightField refactor → all new maps.**
5. **Emitter ELINT channel → player ARM → enemy expansion → countermeasures** (strict chain, build in that order).
6. **ShipClassDef → flagship/specialists/fleet-mixer → amphibious.**
7. **Back-plot reliability pass is a soft gate** for scoot/decoy/CBR — schedule it alongside, or those features have nothing to dodge.

---

## 2 & 3. PHASED ROADMAP (6 milestones)

Ordered by dependency + impact. Each is a coherent, shippable, playtestable increment. Reuse-cost flagged **[CHEAP]** (rides existing data models) vs **[NEW]** (needs new machinery).

---

### Milestone 1 — **Legibility Foundation** (UI spine + the threat picture)
*The whole game's UI cuts across every later feature, and the playable loop today is illegible. This is also lowest sim-risk (mostly pure, headless-testable helpers), so it de-risks everything downstream and is the right next pass.*

**Reuse profile:** [CHEAP] — almost no sim changes; reuses `TextRenderer`, `states.py` palette/grid, `ContactBoard`, the single ortho flush.

**New machinery introduced:**
- **UI primitives** [NEW, but generalizes proven `draw_panel`/`draw_header_rule`]: `badge`, `gauge_bar`, `mini_compass`, `tab_strip`, `scroll_list`, `toast_stack` in `states.py` + `game/hud_widgets.py` (alpha-0.55 in-game variants) + a `SEMANTIC_COLORS` enum→color map.
- **Sensors:** `track['kind']` (weapon_id) + `track['size']` (radar size class) stamps — one line each in `world/combat.py _update_strike_contacts` and `sim/contacts.py update()`. This is the highest-leverage cross-cutting dependency.
- **UI surfaces:** Threat-Warning HUD strip (sorted inbound board, TTI, MUTED→WARN→DANGER, terminal-pulse); per-battery Tube/Status panel (per-tube READY/RELOADING/EMPTY + magazine); Click-Contact Intel panel (est pos/course/speed, age, source, ID-confidence ladder, uncertainty); Toast/hint upgrade.
- **AI-brain:** none. (These render fog-pierced *player* belief; they never feed the AI.)

**Key test contracts:**
- `threat_rows()` sorts by TTI asc; severity bands at <20s/20-60s/>60s; closing≤0 → TTI None, sorts last; only `is_air` hostile-kind tracks appear; empty board → `[]`.
- **Fog test (load-bearing):** an undetected hostile present in `world.missiles` but absent from `contacts.tracks`/`_strike_board` does **not** appear in the strip.
- `contact_intel`: fresh radar track → IDENTIFIED/high confidence; age 30s → UNKNOWN + "dead-reckoned" flag; CLASS derived from `is_air`+`size`, never the real entity.
- `tube_cells`: mid-reload tube → state `reload`, frac∈(0,1); SANDBOX world → `[]` (panel hidden).
- Widget purity: `badge()` emits exactly 1 rect+1 border+1 text; `gauge_bar(frac=0)` no fill, `frac` clamps [0,1]; `SEMANTIC_COLORS` total over the enum (parametrized).

---

### Milestone 2 — **SEAD / Anti-Radiation Warfare** (player gets an offensive answer to the radar war + emitter SIGINT)
*Player ARM is the single highest-impact new offensive verb and reuses `HarmMissile` verbatim. It needs the emitter ELINT channel first, which is itself a major intel surface. Both ride existing, tested pipelines.*

**Reuse profile:** [CHEAP] for the seeker (`HarmMissile` reused unchanged) and intel (ELINT solver + `_emitters()` already hear enemy radars and are discarded). [NEW] only the arsenal def, mesh, world wiring, and the emitter-contact surface.

**New machinery:**
- **Weapon:** `KH31P` StrikeDef (Mach 3 ramjet, 110 km, 87 kg) in `sim/arsenal.py` → `STRIKES`; reuse `HarmMissile` (subclass `PlayerArmMissile(is_hostile=False)` or set flag in `launch_arm`). New mesh `build_kh31p()` + `DEDICATED_MISSILE_IDS` registration.
- **Platform:** Bastion TEL via 3-way `B` cycle (oniks→zircon→kh31p); own scarce pool `config.kh31p_ammo`.
- **Sensors:** generalize `_inject_elint_tracks` to surface **all** heard emitters (AWACS / ground radar / SPY-1) as `is_emitter=True` contacts with the ELINT uncertainty ring — the missing half of the existing pipeline. New `_player_targetable_emitters()` shared with `launch_arm(emitter_id)`.
- **AI-brain:** enemy radars now go silent on a *sensed* inbound ARM-class track (`_defend_ship_radars` / new `_defend_ground_radars`, mirroring AWACS EMCON) — degrading the live `HarmMissile` to its seeded CEP ring. Sensor-triggered, never off the ARM's true pos.
- **Determinism:** reserve `[seed, 8]` for the player-ARM miss-offset stream.
- **UI:** emitter glyph (diamond-in-ring) + selection; 3-way Bastion weapon strip; in-flight ARM seeker-state readout (LOCK / SILENT-CEP / MEMORY); "EMITTER LOCALIZED" cue.

**Key test contracts:**
- `test_kh31p_def_envelope`: kills emitter at 90 km, falls short at 130 km (physics envelope).
- `test_player_arm_homes_emitter` / `_silence_cep` / `_relock`: emitting → kill; silent before terminal → impacts within HARM_MISS_MIN..MAX of last-known, **emitter survives**; silence-then-relight → kill. All deterministic across two same-seed runs.
- `test_arm_not_hostile`: KH-31P overflying a player TEL never registers a base hit.
- `test_elint_surfaces_awacs_emitter` / `_ages_out` / `_only_when_actionable`; `test_emitter_id_resolves_to_radar`.
- **Risk-locked:** verify the ARM fuse-kill flips both the `Radar.alive` **and** the co-located enemy `Structure` (victory credit) — spec open-question #6.

---

### Milestone 3 — **Electronic Warfare (two-sided jamming)** + **Map/Terrain depth**
*EW is the contract-fairness keystone the spec calls "build first" within its cluster, and it must land carefully because it touches the contact gate. Bundling the terrain HeightField refactor here keeps the two riskiest "touch shared infra" jobs in one carefully-reviewed milestone; the player SEAD-ARM-vs-jammer counter reuses Milestone 2's ARM.*

**Reuse profile:** [NEW] `sim/ew.py` field model + `Radar.detects(jammers=())` kwarg + HeightField refactor (all backward-compatible: default-empty/DEFAULT = byte-identical). [CHEAP] Growler reuses the AWACS racetrack/flee; player pod rides the existing drone; SEAD-ARM reuses Milestone 2.

**New machinery:**
- **Sensors / field model:** `sim/ew.py` — J/S burn-through (`echo ~1/R⁴`, jam `~1/R²`), monotonic/continuous `effective_range(radar, size, target, jammers)`; `Radar.detects` gains optional `jammers=()` (empty → identical, the regression gate). `noise_floor_at()` raises `ElintReceiver` bearing sigma under jam (degraded geolocation). **Calibration via a measured probe** (`tools/probe_ew_burnthrough.py`), locked with a two-sided band — never guessed.
- **Platform:** enemy `JammerAircraft` (EA-18G-class, `n_jammers`) — a fat always-on ELINT/ARM beacon; player drone EW pod (`config.player_jammer`, JAM toggle key) that collapses enemy SPY-1/AWACS/nose-radar and makes itself localizable.
- **AI-brain:** `_defend_jammer` doctrine — station on fleet→loudest-believed-emitter bearing, lift jam when ELINT-localized or ARM inbound (AWACS-EMCON dwell pattern), flee to carrier when a missile track closes. Sensor-only, `[seed, 8]` EW stream (shared with ARM tag per the spec — confirm no collision; if needed split).
- **Terrain [NEW]:** `HeightField` refactor of `terrain_height_scalar` (bit-identical), enabling a `terrain_blocks` LOS function; GL ocean/sky/foam uplift (shader layer only, no sim change) with a Low/High toggle.
- **UI:** JAMMED-band map overlay (drawn from **believed** jammer fix, not truth) + RADAR-DEGRADED/burn-through HUD row + JAM-SRC ELINT marker + emissions-exposure meter.

**Key test contracts:**
- `effective_range == max` with no jammer (regression: all existing radar/contacts/defense tests stay green); target inside burn-through detected, just outside not; **monotonic** (double standoff → more burn-through); close-in floor always detected.
- ELINT: `jammers=()` byte-identical; jam up → larger `fix_quality`; more cross-track pairs needed to reach actionable.
- Jammer brain: stations off **belief** not truth (monkeypatch real radar far from its EmitterIntel → station follows belief); lift within dwell on inbound ARM, no strobing.
- UI: band geometry uses `world.ew_state.jammer_fix` (believed), not real pos.
- Terrain: `test_generation.py` bit-identical gate on DEFAULT; frametime under budget; masking probe shows `terrain_blocks` degrades radar/SAR as designed.

---

### Milestone 4 — **New Trajectory Regimes** (top-attack ASBM + loitering swarm)
*Two new player offensive axes that break the SM-2 screen on altitude (ASBM) and saturation (swarm). Both are high-reuse against proven flight machines and slot into counters that already exist (SM-6 area band for the ASBM).*

**Reuse profile:** [CHEAP] ASBM = `AsbmMissile(SamMissile)` reusing the per-round loft/dive/PN machine re-pointed at a ship, terminal seeker ported from `Missile._acquire_lock`; swarm reuses `Missile` route + Mach-hold + per-salvo weave. [NEW] only the SamDef/WeaponDef constants, the SwarmPod structure, and the `_commanded_speed` override.

**New machinery:**
- **Weapons:** `ASBM` SamDef (apogee ≥40 km, near-vertical dive to the deck — *do not* copy the 40N6 4 km floor); `SWARM` WeaponDef (subsonic loiterer) + `SWARM_POD` LauncherDef. Both player-only (preserves asymmetry).
- **Platforms:** ASBM via Bastion 3-way→4-way cycle, `config.asbm_ammo`; SwarmPod a new destructible multi-cell launcher, `config.n_swarm_pods`.
- **New sim layer:** `compute_swarm_speeds(routes, v_max, margin)` (pure: `v_i = len_i / T`, `T = max_len/v_max + margin`) + `Missile._commanded_speed` overriding the Mach-hold target — **guarded so unset = bit-identical** (the regression contract). `launch_swarm(...)` bundles all ready cells.
- **AI-brain:** none required for v1 — the SM-6 area channel (`SM6_AREA_MIN_ALT_M=1500`) **already** counters the high ASBM midcourse; saturation **already** emerges from `SM2_MAX_INFLIGHT=4` + 3 s reload + single CIWS bubble. Optional Phase-2: SM-6 prefer-highest-closing-rate; "pop-up raid detected" radar-raise.
- **UI:** ASBM ballistic arc preview + apogee marker + ToF/track-age strip ("TRACK AGE 45s — MAY MISS A MOVER"); the **biggest new map surface** = swarm tasking panel (cells, shared aim, TOT countdown, SYNC/MAX arrival toggle, per-round commanded-speed bars, converging path lines).

**Key test contracts:**
- `test_asbm_lofts_high_and_dives_near_vertical` (apogee ≥40 km, terminal FPA steeper than −60°); `_kills_stationary_ship`; `_misses_fast_mover_on_stale_track` vs `_fresh_track_kills_same_mover` (proves it's the **stale picture**, not the airframe, that misses); `_high_midcourse_is_sm6_targetable` (locks the counter contract); determinism.
- `test_compute_swarm_speeds_simultaneous` (arrivals within ~1 s, longest path at ~v_max); `test_commanded_speed_overrides_mach_hold`; **`test_unset_commanded_speed_bit_identical`** (the Oniks regression guard on the `_sustainer_thrust` edit); `test_bundle_launch_fires_all_ready_cells`; `test_swarm_saturates_point_defense` (synced bundle leaks where a 4-round trickle does not).

---

### Milestone 5 — **Fleet Differentiation + New Threat Axes** (ship classes, amphibious lose-path, submarine/ASW, mid-SAM + scoot + CBR + decoys)
*The biggest milestone — it makes the enemy a doctrinally varied task group and adds two orthogonal lose-paths (beachhead timer, sub salvo). Sequenced internally so each sub-feature's prerequisite lands first. The shared back-plot reliability pass lives here, unblocking scoot/decoy/CBR.*

**Reuse profile:** mixed. Ship classes [CHEAP] (Destroyer subclasses = loadout + flags + HP). Amphibious [NEW] entities + timed lose rule. Sub [CHEAP] (Destroyer racetrack + StrikeDef + seeker basket) + [NEW] sub phase + acoustic receiver. Buk [CHEAP] (proven two-round SamDef pattern + Pantsir radar-net) + [NEW] meshes. Scoot/CBR/decoys [NEW] but reuse the shared back-plot helper.

**New machinery (grouped, build in this internal order):**
1. **Back-plot reliability pass + shared `back_plot_surface()` helper** (refactor out of commander; keep `process_missile_track` bit-identical). Unblocks 3 below.
2. **ShipClassDef taxonomy** (`sim/enemy_ship_classes.py`): GroundAttack (heavy TLAM), AirDefense (heavy SM-2/SM-6 + higher `sm2_max_inflight` via `getattr`), General, **Flagship** (CEC datalink hub — its radar joins `cue_radars_fn`; **its death strips remote cueing + bumps `TRACK_FORM_S`**, a sensor-honest AI nerf), Carrier (integrate the existing dark CVN). Fleet-composition mixer generalizes `sample_fleet` into a doctrinal screen geometry.
3. **Buk mid-SAM** (9M317 long-reach + 9M338 agile, two SamDefs) — fills the measured 20→150 km gap, shelters the drone, answers the aircraft-evasion gap. Its 9S36 radar joins `radar_net`; reuses `[seed, 8]` Buk stream (coordinate tag allocation).
4. **Shoot-and-scoot** generic `relocate(dest)` on Bastion/S-300/Buk TELs (committed/transit/re-pin tube+Structure pos) — the player counter to the now-reliable back-plot.
5. **Counter-Battery Radar** (`sim/counter_battery.py`): early inbound detection + symmetric shooter back-plot (same shared helper) + threat strip TTI + counter-fire cue. Emits → ESM-locatable (honest cost).
6. **ESM decoy emitters + corner-reflector** decoys (plant **real** sensor events: a decoy `Radar` heard by ESM; a biased `BackPlotEntry` — never a "miss" flag).
7. **Submarine (Kilo 636 + Kalibr)** + **passive sonobuoys + missile-origin datum** (`AcousticReceiver` reuses the shared ELINT solver with no horizon check; `SubDatumTracker` mirrors the back-plot). Sub invisible except during surfaced launch exposure.
8. **Amphibious** Transport + LCAC + **timed beachhead lose condition** (`_doctrine_amphibious` sequences the landing from the sensor picture; `defeated` ORs a beachhead-expiry clause).

- **Determinism tags:** `[seed,8]` Buk, `[seed,9]` CBR/ship-class placement, `[seed,10]` decoys, `[seed,11]` relocate, `[seed,8]`(amphibious — coordinate to avoid collision; allocate fresh tags centrally).
- **Config:** many new `CombatConfig` fields (`n_flagship/n_aaw/n_ground_attack/n_transports/n_buk/n_cbr/n_decoys/...`) — **LOCKED schema, all default OFF/0** so every regression stays bit-identical; needs integrator sign-off + matching `clamp_config` + setup rows + `test_combat_config`.
- **UI:** per-contact class labels + HVU stars + "FLEET DATALINK DEGRADED" banner; beachhead countdown + distinct DEFEAT-cause banner; Buk envelope ring + round panel; relocate move-route + ETA + RELOCATING badge; CBR threat strip + back-plot cue markers; decoy/CR markers; sonobuoy drop mode + acoustic bearing rays + datum ring + ASW coverage overlay (clones `_elint_overlay`).

**Key test contracts (representative):**
- Ship classes: each instantiates with its def; AAW sustains more concurrent SM-2; GroundAttack drained first by a TLAM salvo; **fog** — no class field on the contact board until imaged.
- Flagship: alive → escort forms a remote-cued track before own SPY-1 LOS; dead → no remote-cued launch + `TRACK_FORM_S` rises; **no-truth** (mock player where flagship can't detect → no cue).
- Buk: two-round-distinct (agile turns harder, long reaches farther) like `test_s300_rounds_distinct`; `launch_buk` consumes the right pool, refuses on empty/no-air-track; Oniks-vs-SM-2 duel **bit-identical** (Buk touches none of it).
- Scoot: `relocate` sets committed + disarms; fire refused in transit; pad+tubes+Structure all move within 1 m; **scoot-defeats-HARM** (round impacts the OLD pad, relocated TEL survives); new launch seeds a back-plot near the NEW pad.
- CBR: synthetic inbound → finite TTI + shooter back-plot within `BACKPLOT_ERR_FRAC*range`; **fog** — track outside `detects()` yields nothing; **symmetry** — shared helper identical output enemy-side vs player-side; CBR appears in the enemy emitter feed (HARM-able).
- Decoys: silent real radar + lit decoy → commander schedules HARM at the **decoy** id; **honesty** — no decoy/no-reflector → enemy picture bit-identical to today.
- Sub: invisible/excluded from contacts; rise-then-launch ordering; cue precedes salvo; two-buoy acoustic fix, ∞ for degenerate geometry, horizon-ignoring, no truth leak.
- Amphibious: transport at launch line splashes the right LCAC count; sinking it pre-line removes embarked LCACs; LCAC in box starts timer; clearing all craft cancels loss; **`n_transports=0` reproduces today exactly**.

---

### Milestone 6 — **Meta Loop** (campaign, scoring/AAR, salvo key, auto-time-warp, map presets)
*The wrapper that turns the finite-magazine economy into a campaign resource and makes battles legible after the fact. Depends on most gameplay existing (scoring grades against the now-rich battle), and map presets depend on the M3 HeightField refactor.*

**Reuse profile:** [CHEAP] — almost entirely read/schedule layers over existing state; scoring is a read-only end pass; auto-warp generalizes the existing launch-lock; salvo calls existing `launch`/`launch_sam` N times; presets exercise the M3 `terrain_blocks`.

**New machinery:**
- **Salvo / ripple-fire key:** thin scheduler on the sandbox state (NOT world — keep world deterministic/single-shot) ticking RIPPLE/FAN/TOT launches; `salvo_lanes()` pure helper; `[seed, battle_idx, 9, ordinal]` FAN stream.
- **Auto-time-warp:** `game/timewarp.py` `TimeWarpDirector` (ease + dwell) generalizing `launch_realtime_lock`; extended `TIME_SCALES` ladder; **fog-safe drop predicates** (inbound reads `_strike_board`/`contacts.tracks` only — never `world.missiles` truth; own-round terminal/intercept may read truth).
- **After-action scoring:** `game/scoring.py` — `ScoreCard` from efficiency / time-to-first-fix / **was-back-plotted** (reads `commander.picture.clusters` — already fog-honest) / leak rate / base-intact %; deterministic per-seed PAR; shot-debrief from a `world.ledger` fed by typed `drain_events` + per-round death cause; AAR is the **one screen allowed to reveal truth** (truth-vs-belief overlay).
- **Campaign:** `game/campaign.py` — chain of seeded battles; persistent ammo + base damage; scarce resupply scaled by grade; escalating enemy via existing `CombatConfig` counts. **Determinism approach (recommended, lower-risk):** derive a per-battle base seed `derive_seed(seed, battle_idx)` and pass it as `config.seed` — keeps existing `[seed, tag]` child streams untouched rather than adding a `battle_idx` tag dimension. Carry-forward via an optional `initial_state` ingest applied **after** `_arm_magazines`.
- **Map presets [NEW data]:** Archipelago / Strait / Fjord exercising `terrain_blocks` LOS; `CombatConfig` preset field (sign-off).
- **Mission briefing screen** (between setup and battle): mission type, starting intel, ROE, win/lose — seeds `ContactBoard`/`EnemyPicture` initial conditions + commander posture.

**Key test contracts:**
- Salvo: RIPPLE fires exactly N ready tubes at the interval then stops; never fires a RELOADING/EMPTY tube; FAN offsets reproducible per seed; TOT delays monotone with flight time.
- Auto-warp: settles to target with no drop; eases to 1x within the ramp + holds the dwell; launch-lock still forces 1x (regression); **fog test** — undetected hostile does **not** trigger a drop; **determinism** — stepping at 1x vs 8x yields identical commander/back-plot state at the same sim_time.
- Scoring: `compute_par` deterministic per seed; perfect world → S, bad → D; `was_back_plotted` reads `picture.clusters`; None-scorecard smoke path still works.
- Campaign: `derive_seed` deterministic + distinct per battle; `next_config` always `clamp_config`'d within ranges even at high battle_idx; save↔load round-trips; ammo/base-damage carry-forward; **`initial_state=None` path bit-identical to today** (the determinism regression gate); escalation monotonic to the clamp ceiling.
- Presets: HeightField DEFAULT bit-identical; clamp round-trips the preset field.

---

## 4. CONSOLIDATED UI PLAN

UI cuts across every cluster; build it as **one vocabulary, many surfaces**, on the existing single-flush ortho pass. The performance contract is total quad count: every strip is rect+line+text only, uses the `draw_text` quad cache, culls off-screen rows, and only the threat strip animates (one `sin(_pulse_t)` alpha, zero new GL state).

### Shared primitive library (Milestone 1 — build first)
Added beside the proven `draw_panel`/`draw_header_rule`/`draw_ticks`:
- **`badge(text, x, y, state)`** — semantic status pill (READY/RELOAD/SILENT/INBOUND/DESTROYED → fixed palette).
- **`gauge_bar(x, y, w, h, frac, col)`** — fuel/ammo/fix-quality/reload-progress/score.
- **`mini_compass(cx, cy, r, bearings)`** — bearing ring for threat strip + intel panel.
- **`tab_strip` / `scroll_list` / `toast_stack`** — extracted from existing hand-rolled code.
- **`SEMANTIC_COLORS`** map so colors are never hard-coded per call site.
- **`game/hud_widgets.py`** — alpha-0.55 in-game variants matching menu chrome.

### Fixed, load-bearing color semantics (the fog contract made legible)
- amber **ACCENT** = the one brand/selection accent only
- green **OK_COL** = friendly/ready/armed
- amber-orange **WARN** = reloading/transient/caution
- red **DANGER** = inbound/destroyed/terminal/destructive
- **MUTED** = labels
- **cyan family** = friendly-truth telemetry (drone, own assets)
- **contact-orange CONTACT_COL** = fog-of-war estimates, faded by age
- **Hard rule:** sensor-derived data renders in the contact/estimate idiom (faded, uncertainty shown); friendly truth renders in cyan/green. The UI must never let truth and estimate look alike, or it leaks the fog.

### Per-feature surfaces (composed from the primitives), by milestone
| Milestone | Surfaces |
|---|---|
| **M1** | Threat-warning strip, tube/battery status panel, contact-intel panel + ID-confidence ladder, toast/hint upgrade, time-warp pill (basic) |
| **M2** | Emitter/SIGINT layer (emitter glyph + ELINT ring + selection), 3-way→4-way Bastion weapon strip, in-flight ARM seeker-state readout, "EMITTER LOCALIZED" cue, emitter-threat/RWR panel |
| **M3** | JAMMED-band corridor overlay (from belief), RADAR-DEGRADED/burn-through HUD row, JAM-SRC marker, emissions-exposure meter, Low/High terrain toggle |
| **M4** | ASBM ballistic-arc preview + apogee + ToF/track-age strip; **swarm tasking panel** (cells, TOT countdown, SYNC/MAX toggle, per-round speed bars, converging paths) |
| **M5** | Fleet roster strip + class labels + HVU stars + datalink-degraded banner; beachhead countdown + cause-specific defeat banner; Buk envelope ring + round panel; relocate move-route/ETA/RELOCATING badge; CBR threat cues + back-plot markers; ASW sonobuoy overlay + datum ring |
| **M6** | After-action / shot-debrief screen (scroll_list + gauge_bars + truth-reveal toggle); campaign hub (battle ladder + attrition ledger); mission briefing; envelope/leak-ring shading |

Every per-feature surface has a **pure, headless-testable helper** (e.g. `threat_rows`, `contact_intel`, `tube_cells`, `warp_pill`, `briefing_rows`, `aar_summary`) tested with a FakeText draw-call recorder — the established LOCKED convention that isolates pure logic from GL.

---

## 5. CROSS-CUTTING RISKS

1. **New trajectory regimes on borrowed flight machines (M4).** The `StrikeMissile`/`SamMissile` speed controllers are tuned for subsonic cruise / the SAM loft-with-a-4km-floor. The Mach-3 KH-31P ramjet and the ASBM's apogee-then-deck dive can both miss their intended profile (controller saturation, copied altitude floors). **Mitigation:** flyoff probes in `tools/` (mirroring `compare_s300_rounds.py`) that *measure* apogee/dive-angle/Mach before locking the envelope tests — never assume the airframe behaves; the spec explicitly warns the 40N6 4 km floor must not be copied.

2. **EW touching the contact gate (M3).** `sim/ew.py` plugs into `Radar.detects`, the most-tested seam in the codebase. A non-default-empty `jammers=()` or a discontinuous burn-through curve breaks every radar/contacts/defense regression and can blind or over-expose either side. **Mitigation:** the kwarg defaults empty → byte-identical (the regression is the gate); burn-through must be monotonic + continuous with a close-in floor (you can never be totally blinded against a leaker); calibrate with a measured probe + two-sided band, MIN burn-through for multi-jammer.

3. **Submarine fairness / fog (M5).** A sub the player's radar/SAR/ELINT *physically cannot find* is a fun second lose-path but trivially unfair if it never surfaces or if its salvo isn't telegraphed. **Mitigation:** sub must surface to launch (becomes radar/SAR-visible during exposure — the player's kill window); a subsurface-launch cue precedes the salvo; the acoustic datum is a *stale lead* (sub dives after firing); ASW kill emerges from datum-quality-vs-lethal-radius, not a roll. The AI never reads buoys.

4. **Determinism tag collisions (all milestones).** Tags `3..7` are taken; the clusters independently propose `8` for player-ARM, EW, and amphibious. **Mitigation:** allocate tags centrally — one reserved tag per new stochastic system (ARM 8, EW 12, Buk 8?→reassign, CBR 9, decoys 10, relocate 11, amphibious 13, salvo-FAN nested by ordinal). Every campaign battle should re-seed via `derive_seed(seed, battle_idx)` rather than adding a tag dimension, keeping all existing streams untouched.

5. **LOCKED CombatConfig schema (M5/M6).** Many features add fields; the schema header mandates integrator sign-off. **Mitigation:** all new fields default OFF/0 so the out-of-the-box Oniks-vs-SM-2 duel and every regression stay bit-identical; campaign escalation + carry-forward ride a *separate carrier* (`battle_idx` + `initial_state` passed alongside config), never new frozen fields. Batch the sign-off.

6. **Performance / UI quad budget (M1+).** The overlay is one flush; the budget is total quads. **Mitigation:** rect+line+text only (no images/gradients/fills beyond concentric strokes), quad cache, off-screen row culling, single animated element. Verify the right-edge threat strip + top-left telemetry + bottom-left intel coexist at the **smallest** supported window (the 8px grid assumes ≥1080p — spec open-question).

7. **Back-plot reliability is a soft gate (M5).** GAME_ANALYSIS §5 flags the current back-plot as too timid (mis-projects a sea-skimmer ~12 km), so scoot/decoy/CBR have nothing to act on. **Mitigation:** schedule the reliability pass *first* inside M5, and extract the shared `back_plot_surface()` helper so the enemy commander and the player CBR improve together and stay symmetric (a regression test pins `process_missile_track` bit-identical post-refactor).

8. **Moving Structures at runtime (M5 scoot/amphibious).** Relocating a TEL or splashing LCACs moves `Structure.pos`; the OBB sweep and 3D render anchor must read the live pos, not a cached init value. **Mitigation:** verify `Structure` rebuilds its OBB from `pos` per query; test pad+tube+Structure all move within 1 m; the renderer lerps without breaking the TEL-erect animation.

---

## 6. RECOMMENDED FIRST MILESTONE TO BUILD NEXT PASS

**Milestone 1 — Legibility Foundation.**

Rationale:
- **Lowest sim-risk, highest cross-cutting leverage.** It is almost entirely pure, headless-testable helpers over existing data; it cannot break the physics or fog contracts, and it unblocks the UI of every later cluster.
- **It is a true dependency, not just polish.** The `track['kind']`/`track['size']` stamps it lands are required by the sub axis (M5), EW UI (M3), auto-warp (M6), and the intel panel/AAR — building them now avoids re-touching the contact board repeatedly.
- **It makes the current loop playable enough to evaluate.** Per the project's standing memory ("playtest before polish"), the existing COMBAT mode is hard to read (single status line, no inbound board, no tube state). The threat strip + tube panel + intel panel are exactly the "make the invisible legible" surfaces flagged as the #1 consensus need in both `feature_ideas.md` and `GAME_ANALYSIS.md §7`.

Concrete first-pass scope: ship the six widget primitives + `hud_widgets.py` + `SEMANTIC_COLORS`; add the two track stamps; build the threat-warning strip, tube/battery status panel, and click-contact intel panel; upgrade toasts. All behind the FakeText-recorder test convention, with the load-bearing fog test (undetected hostile never appears) as the gate.

**Immediately after M1, run the mandatory ~15-min hands-on COMBAT playtest** (per memory) before starting Milestone 2 — the legibility layer is what makes that playtest informative, and its findings should tune M2's SEAD priorities.

---

Key verified files this roadmap leans on (absolute paths):
- `C:\Users\teoti\OneDrive\Desktop\New folder\oinks PROTO\sim\strike.py` (`HarmMissile` @ line 583 — reused verbatim by player ARM)
- `C:\Users\teoti\OneDrive\Desktop\New folder\oinks PROTO\world\combat.py` (`_emitters` @776, `_inject_elint_tracks` @820, `_feed_enemy_picture` @1059, `launch_sam` @1562; RNG tags `[seed,3..7]` @458-677)
- `C:\Users\teoti\OneDrive\Desktop\New folder\oinks PROTO\sim\enemy_defense.py` (`SM6_AREA_MIN_ALT_M=1500` @119, `SM2_MAX_INFLIGHT=4` @82, `_try_sm6_launch` @491 — the ASBM counter already exists)
- `C:\Users\teoti\OneDrive\Desktop\New folder\oinks PROTO\game\states.py` (`draw_panel` @97, `draw_header_rule` @114, grid constants @44-47 — the UI spine)
- `C:\Users\teoti\OneDrive\Desktop\New folder\oinks PROTO\world\combat_config.py` (LOCKED frozen schema @1-4 — all new fields default OFF, need sign-off)
- `C:\Users\teoti\OneDrive\Desktop\New folder\oinks PROTO\world\generation.py` (`terrain_height_scalar` @255 — needs the HeightField refactor; no `terrain_blocks`/`HeightField` exists yet, confirming that machinery is genuinely new)