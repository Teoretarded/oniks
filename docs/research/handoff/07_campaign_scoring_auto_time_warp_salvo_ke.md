# Spec 7: Campaign + scoring + auto-time-warp + salvo key + status panel

> Implementation-research spec for a fresh implementer. Read HANDOFF_README.md first for codebase orientation + non-negotiables.

## Summary
Five tightly-coupled QOL/meta systems built on the existing finite-magazine economy, the salvo battery (_oniks_tubes/_s300_tubes), the TIME_SCALES ladder, the sensor-only EnemyPicture, and the CombatConfig/setup→battle→end flow. All five reuse code that already exists; none require sim-physics changes. The two systems that touch the sim loop (auto-time-warp drop triggers, salvo ripple) are pure read/schedule layers over the radar-gated contact board and the per-tube reload state, so the physics-not-dice and fog-of-war contracts are preserved by construction (every trigger/score signal reads only player-side sensor state, never enemy truth). Determinism is preserved by adding battle-index child RNG tags ([seed, battle_idx, phase_tag]) to the existing default_rng([seed, tag]) convention. The cluster's three load-bearing risks: (1) campaign persistence must NOT bypass clamp_config or the LOCKED CombatConfig schema; (2) auto-warp drop triggers must fire only on PLAYER-DETECTED inbound threats (the radar-gated _strike_board / contacts.tracks), never on world.missiles truth, or it leaks fog-of-war; (3) scoring's 'was-back-plotted' must read world.commander.picture.clusters (the enemy belief), which is already sensor-derived. Recommended build order: STATUS PANEL (pure HUD, zero sim risk) → SALVO KEY (controls + world helper) → AUTO-TIME-WARP (generalize the launch-lock) → SCORING (end-screen read-only pass) → CAMPAIGN (wraps all of the above + persistence).

**Dependencies:** CROSS-FEATURE (within this cluster): CAMPAIGN depends on SCORING (resupply is scaled by the ScoreCard grade) and naturally surfaces SALVO + STATUS PANEL (carried-forward ammo is read by the status panel; the salvo's magazine drain becomes the campaign's attrition cost). Build order: STATUS PANEL (independent, S, zero sim risk) → SALVO KEY (depends on nothing new; reuses world.launch/launch_sam) → AUTO-TIME-WARP (independent; generalizes launch_realtime_lock; SALVO should hold warp at 1x during its window, so wire after both exist) → SCORING (independent end-screen read; needs telemetry hooks in CombatState.sim_step) → CAMPAIGN (needs SCORING; needs the world.combat.py battle_idx + initial_state ingest threaded first). MUST-EXIST-FIRST (already in codebase, verified): the finite-magazine economy (world/world.py _arm_magazines + the salvo battery _oniks_tubes/_s300_tubes in world/combat.py); the TIME_SCALES ladder + effective_time_scale seam (main.py re-reads per frame); CombatConfig + clamp_config (world/combat_config.py — LOCKED schema, must not be mutated); the setup→battle→end flow (main.py start_combat/open_combat_setup/quit_to_menu, game/combat_end.py CombatEndOverlay with rematch/new_battle/menu cbs); the sensor-only EnemyPicture (sim/commander.py picture.clusters/_back_plots) for the was-back-plotted score; the radar-gated player picture (world.contacts.tracks + world._strike_board) for the fog-safe auto-warp inbound trigger. EXTERNAL/SHARED with sibling clusters: a NEW keybind ActionDef block (battery_panel, salvo_fire, salvo_mode, auto_warp_toggle) is added to game/keybinds.py ACTIONS — coordinate default keys (G/F/H/T proposed, all currently unclaimed) with other clusters to avoid collisions, and update the shared test_keybinds default-table assertions + the F1 overlay_rows count in test_hud once. The HUD telemetry stack (game/hud.py) is shared real estate — the consolidated UI plan should reconcile the status panel, salvo readout, auto-warp indicator, and any sibling threat strip into one coherent top-left/bottom layout.

**Open questions:** 1) Keybinds: confirm G/F/H/T are free across ALL clusters' new actions (verified unclaimed against the current ACTIONS table, but other clusters may also be adding actions). 2) CONTROLS hold-detection: game/controls.py SandboxControls currently dispatches only KEYDOWN via _handle_key — the SALVO 'hold to ripple' and any KEYUP need either a new KEYUP branch in handle_event or a held-key poll in SandboxControls.update (like the freecam keys). Which pattern does the team prefer? 3) Determinism threading: adding battle_idx to world/combat.py's child-stream tags ([seed, tag] → [seed, battle_idx, tag]) is the cleanest campaign-deterministic approach but touches a tested file; the spec defaults battle_idx=0 to collapse to today's behavior — confirm the seeded-determinism tests tolerate the extra tag dimension when it's 0 (they should, since [seed,0,tag] != [seed,tag] — so EITHER keep battle_idx out of the tag and instead derive a per-battle base seed via derive_seed(seed,battle_idx) and pass THAT as config.seed, which keeps existing tags untouched — RECOMMENDED, lower risk). 4) CombatConfig is LOCKED/frozen: campaign escalation + carry-forward must ride a SEPARATE carrier (battle_idx + initial_state passed alongside config), never new schema fields — confirm the integrator agrees rather than extending CombatConfig. 5) Auto-warp ceiling: the main.py loop caps at 64 sim steps/frame (0.53 s sim/frame at 120 Hz) — at 64x and 60 FPS that's exactly the cap; document the practical ceiling or raise the step cap. 6) Scoring 'rounds fired' source: count in the launch wrappers (precise) vs derive from cap-minus-current+refills (lossy with refills) — wrappers recommended; confirm CombatState may hook request_launch/_request_sam_launch/salvo. 7) Per-seed PAR formula: needs a balance pass with real playtest data (the spec gives a deterministic scaffold; the thresholds are tuning).


---
## Feature: Per-battery STATUS PANEL (per-tube LOADED/RELOADING/EMPTY + magazine + reload timers)  _(effort: S)_

**What it is + real-world grounding:**

A dedicated HUD surface showing, for every player battery (each Oniks TEL, each S-300 TEL, each Pantsir), the state of every physical tube: LOADED (green) / RELOADING Ns (amber, with countdown) / EMPTY (red), plus the shared magazine pool n/cap and the magazine-refill countdown when dry. Grounded in real TEL fire-control panels: a Bastion K340P / S-300 5P85 crew sees exactly this per-canister ready/reload state. The data already exists fully — world/combat.py _oniks_tubes (each {pos, loaded, reload_left}), _s300_tubes (each {pos, reload_left}), sam_ammo/sam_ammo_40n6, _oniks_ammo/_oniks_mag_cap/_oniks_mag_reload_left, Pantsir.missile_ammo/gun_ammo — and is currently summarized only as a single status line. This feature surfaces the whole battery at a glance (GAME_ANALYSIS.md §7 'Show which tubes are loaded/reloading on the HUD').

**Platform (launched from / carried by):**

Reads ALL player launch platforms: the N Oniks TELs (2 tubes each), the N S-300 TELs (4 tubes each), and the Pantsir units. Pure observer — it carries/launches nothing. No enemy platform involved (enemy magazines are fog-of-war; the panel only ever shows player-owned hardware the player commands).

**Sensors (uses / detected by):**

None — this is friendly telemetry (own-force logistics), not a sensor product, so it is exempt from the radar gate (the same exemption drone_panel_rows and oniks_ammo_row already use: the player always knows his own ammo). It does NOT read or expose any enemy state.

**AI brain (how the enemy commander uses or counters it):**

No interaction with the enemy commander. The panel is player-only own-force status; the EnemyCommander never reads player tube state (it back-plots launches, which is unchanged). Explicitly: adding this panel must not add any new field the commander could read — it is a pure projection of existing world state.

**Player UX:**

Always-visible compact battery strip on the HUD (top-left telemetry stack already exists). A new keybind (proposed action 'battery_panel', default key G — unclaimed by the current ACTIONS table) toggles an EXPANDED full-screen-ish battery board (like the F1 overlay pattern) showing every tube of every battery as a row of cells; the resting compact form shows only the active platform's tubes plus pooled counts. Tube cells render as small filled rects: green=loaded, amber w/ count=reloading, red=empty. Mouse not required (read-only).

**UI needs:**

NEW pure helper module-level functions in game/hud.py (unit-testable, GL-free): battery_status_rows(world) -> list of per-battery dicts {name, tubes:[(state,reload_left)], pool_text, pool_col, refill_left}. NEW HUD method HUD._battery_panel(sandbox,w,h) drawing the expanded board with the existing draw_panel/draw_header_rule chrome and the existing ARMED_COL/RELOAD_COL/DANGER_COL palette. The compact per-platform tube row integrates into the existing _bastion_block/_s300_block via a new tube_cells_row(tubes) renderer (a row of colored rects instead of label/value text). Reuse PANEL_PAD/LINE_H/HEADER_GAP. Add 'BATTERY PANEL' to the F1 overlay via a new ActionDef.

**Game-model mapping (reuse vs add):**

REUSE entirely: world._oniks_tubes, world._s300_tubes, world.sam_ammo, world.sam_ammo_40n6, world._oniks_ammo/_oniks_mag_cap/_oniks_mag_reload_left, world._s300_48n6_mag_reload_left/_s300_40n6_mag_reload_left, world.pantsirs (missile_ammo/gun_ammo/_mag_reload_left). ADD nothing to the sim. The only new data is the toggle bool on SandboxState (battery_panel_open) and the keybind. Per-launcher grouping: _oniks_tubes is flat (2 per TEL) — group by index pairs using len(world._oniks_launcher_positions); _s300_tubes groups in 4s via len(world._s300_launcher_positions).

**Implementation sketch + test contracts:**

Files: game/hud.py (new pure helpers + _battery_panel + tube_cells_row), game/sandbox.py (self.battery_panel_open=False in __init__; toggle method; route in HUD.draw), game/keybinds.py (new ActionDef('battery_panel','BATTERY PANEL','SIMULATION',pygame.K_g)), game/controls.py (_handle_key: elif action=='battery_panel': sandbox.toggle_battery_panel()). Key functions: battery_status_rows(world); tube state classifier tube_state(t)-> 'LOADED'|'RELOADING'|'EMPTY' (Oniks: loaded&reload_left<=0→LOADED, loaded False but reload_left>0→RELOADING, else EMPTY; S-300 tubes have no 'loaded' so reload_left>0→RELOADING else LOADED-if-pool>0 else EMPTY). TEST CONTRACTS (tests/test_battery_panel.py, headless, pure): (a) battery_status_rows on a fresh CombatConfig(n_oniks=2,oniks_ammo=8) returns 2 Oniks batteries each with 2 LOADED tubes; (b) after world.launch() one tube flips to RELOADING with reload_left==config.oniks_mag_reload_s and the matching countdown; (c) drain the magazine (oniks_ammo→0) → re-cocked-but-unfed tubes read EMPTY and pool_text '0/cap', refill_left>0; (d) S-300: after launch_sam one of 4 tubes RELOADING; (e) sandbox WorldState (infinite) → helper returns the sandbox batteries with pool_text None/omitted (mirrors oniks_ammo_row returning None). Add 'battery_panel' to test_keybinds default-table assertions and test_hud overlay_rows count.

**Counters / balance:**

N/A as a weapon. As a UI element it must not become an information leak: the panel shows ONLY player batteries. The balance contribution is legibility — it makes the salvo/saturation decision (the king move per GAME_ANALYSIS §2) readable, which is the intended counter-play surface, not a new capability.


---
## Feature: SALVO / RIPPLE-FIRE key (empty ready tubes at an interval / fan / time-on-target)  _(effort: M)_

**What it is + real-world grounding:**

A single command that empties all currently-ready tubes across the battery in a controlled ripple instead of one SPACE per round, so the player can saturate the SM-2 '<=4 in flight' cap (the documented king move, GAME_ANALYSIS §2, feature_ideas #4). Modes: (1) RIPPLE — fire each ready tube spaced by a fixed interval (default ~1.5 s, enough for the launch cinematic to clear); (2) FAN — same but each round gets a small bearing/aimpoint spread around the target for a multi-axis arrival; (3) TIME-ON-TARGET (TOT) — stagger launches so rounds ARRIVE together (compute per-round launch delay from each round's estimated flight time to the aim point). Grounded in real coastal-battery salvo doctrine (ripple-fire / TOT fire missions). Reuses the existing per-tube launch (world.launch / launch_sam already fire 'the next ready tube').

**Platform (launched from / carried by):**

Player Bastion battery (all Oniks/Zircon TELs, fires from _oniks_tubes) and, secondarily, the S-300 battery (_s300_tubes, anti-air saturation of a high-value air track). Each platform's salvo respects its own tube/magazine state. The enemy does NOT get this key (its saturation is the commander's coordinated-strike job, separate cluster).

**Sensors (uses / detected by):**

Inherits the launch path's sensor gating: an Oniks salvo still requires a player surface target_point (set from the radar/SAR/ELINT-derived contact via the tactical map); an S-300 salvo requires a live AIR track in contacts.tracks (the radar-gated picture). No new sensor — the salvo cannot fire at anything the player couldn't already single-fire at, so fog-of-war is unchanged.

**AI brain (how the enemy commander uses or counters it):**

The enemy commander observes a salvo exactly as it observes single launches: each round becomes a player missile track fed (radar-gated, first-seen recorded) into world.commander.picture via _feed_enemy_picture → process_missile_track → back-plot. A salvo therefore produces MORE back-plot fixes clustered in time/space, which (correctly, physics-driven) makes the launch cluster easier for the commander to confirm (BACKPLOT_FIXES_NEEDED) and strike — the intended risk/reward of mass fire. No commander code changes; the brain simply sees more tracks. Determinism preserved (the rounds use the same launch path + existing oniks_fired weave-phase seed).

**Player UX:**

HOLD the launch key (or a dedicated 'salvo' action, proposed default key F, unclaimed) to ripple all ready tubes; a quick tap stays single-fire. A salvo-mode selector cycles RIPPLE/FAN/TOT (reuse a hint flash like cycle_sam_round). While a salvo is queued the HUD shows 'SALVO n/m' and the auto-time-warp (sibling feature) is held at 1x for the launch window. Releasing the key early stops queuing further rounds (already-launched rounds fly).

**UI needs:**

HUD hint flashes (reuse show_hint): 'SALVO: RIPPLE 4 TUBES', 'SALVO: TIME-ON-TARGET', 'SALVO COMPLETE'. A small queued-rounds readout in the launcher block ('SALVO 2/4'). The status panel (sibling feature) visually shows tubes flipping to RELOADING in sequence — the two features reinforce. Optional FAN spread preview on the tactical map (small fan of aim arrows) — backlog. Add 'salvo_fire' + 'salvo_mode' ActionDefs to keybinds + F1 overlay.

**Game-model mapping (reuse vs add):**

REUSE world.launch(profile,target_point,waypoints,weapon_id) and world.launch_sam(aircraft_id,round_id) — both already fire 'the next ready tube' and return None when none ready. ADD a thin scheduler on SandboxState/CombatState (NOT in world: keep world single-shot/deterministic): self._salvo_queue = {'platform','count_left','interval','next_t','mode','aim_fn'}; ticked in sim_step. For TOT, compute per-round launch offsets from a flight-time estimate (reuse a coarse range/speed model: range_to_target / weapon cruise speed from sim.arsenal WeaponDef). FAN perturbs target_point by a deterministic small offset per round drawn from a salvo child rng ([seed, battle_idx, 9, salvo_ordinal]).

**Implementation sketch + test contracts:**

Files: game/sandbox.py (salvo queue state + _tick_salvo(dt) called from sim_step BEFORE world.step so queued launches enter this frame; request_salvo(); release handling in controls), game/controls.py (KEYDOWN/KEYUP for salvo_fire — note: controls currently only dispatches KEYDOWN, so add a KEYUP path or use a hold-poll in SandboxControls.update like the freecam keys), game/keybinds.py (ActionDefs salvo_fire=K_f, salvo_mode=K_h), game/hud.py (salvo readout). Key fns: _tick_salvo decrements next_t, calls the platform's launch with the per-round aim, decrements count_left, re-anchors the cinematic camera onto the newest round (reuse request_launch's followed/retarget). TEST CONTRACTS (tests/test_salvo.py, headless via a fake controls harness like test_controls.py): (a) RIPPLE with 4 ready Oniks tubes + interval=1.5 launches exactly 4 rounds at t=0,1.5,3.0,4.5 and stops (count_left→0); (b) a salvo never fires a tube that is RELOADING/EMPTY (drain magazine mid-salvo → remaining queue no-ops, world.launch returns None, queue clears gracefully); (c) determinism — same seed+config+target → identical aim points across two runs (FAN offsets reproducible); (d) TOT — per-round launch delays are monotonic decreasing for rounds with longer flight time so estimated arrival times are within a tolerance band; (e) salvo respects active_platform (s300 salvo calls launch_sam, requires an air track). Keybind table tests updated for the two new actions.

**Counters / balance:**

Balance: the salvo's counter is the enemy SM-2 magazine + the back-plot. Firing many rounds → more leakers (good) BUT more back-plot fixes → faster base-strike (bad), and it drains the finite magazine fast (campaign persistence makes this bite). RIPPLE interval is gated by the launch cinematic length so you can't fire faster than physics allows. The physics-not-dice contract holds: each round's leak/kill still emerges from the multipath/SM-2 sim, the salvo just launches more of them.


---
## Feature: AUTO-TIME-WARP (togglable, event-aware: set a warp e.g. 8x; drop to 1x on important events, then ramp back)  _(effort: M)_

**What it is + real-world grounding:**

Generalizes the EXISTING launch-cinematic 1x lock (game/sandbox.py effective_time_scale + world.world.launch_realtime_lock) and the TIME_SCALES ladder (game/controls.py) into a smart pacing system: the player sets a desired warp (the existing - / = ladder, now extended past 16x); when something important happens the effective scale auto-drops to 1x for the event window, then ramps back to the requested warp. Events that drop warp (all PLAYER-KNOWLEDGE-DERIVED): (1) a hostile missile DETECTED inbound to a player asset (the existing radar-gated _strike_board / launch-warning cue); (2) a terminal own-round (a player missile in TERMINAL phase near its target — the satisfying hit); (3) an active intercept window (a player SAM in TERMINAL on an air track, or a Pantsir 'ENGAGING' flash). Grounded in how every modern wargame/4X paces (auto-slow on contact). No physics change — only the scalar fed to the App loop's accumulator.

**Platform (launched from / carried by):**

N/A (a time-control system, not a weapon). It governs the whole sim clock that all platforms share. It reads player-asset and player-round state to decide drops.

**Sensors (uses / detected by):**

CRITICAL fog-of-war contract: the 'inbound missile detected' drop trigger reads ONLY the player's detected-threat set — world.contacts.tracks / world._strike_board (radar-gated + launch-warning cues), NEVER world.missiles truth. A sea-skimming Tomahawk under the horizon must NOT drop the warp until the player's radar (or a launch-warning RWR cue) actually holds it — otherwise the auto-warp itself leaks that an undetected threat exists. Player own-round triggers (terminal/intercept) read world.missiles directly because those are friendly rounds the player owns (no fog there).

**AI brain (how the enemy commander uses or counters it):**

Zero interaction with the enemy commander — the commander never reads time_scale and is unaffected by warp (it ticks on sim_time, which advances faster/slower transparently; its 1 Hz/0.25 s cadences are sim-time gated, so behavior is scale-invariant and deterministic regardless of warp). Must verify: the warp must remain a pure multiplier on accumulated sim time (main.py already does acc += dt_real*time_scale), so the commander's sensor feeds and orders are bit-identical at any warp for a given seed (determinism contract). A drop to 1x changes only real-time pacing, not sim outcomes.

**Player UX:**

A new togglable 'AUTO-WARP' mode (proposed action 'auto_warp_toggle', default key T, unclaimed). When ON: - / = set the TARGET warp (extended ladder e.g. 1,2,4,8,16,32,64 — capped by the 64-steps/frame loop guard, so the effective ceiling is documented). The HUD TIME row already shows 'x8 (launch)' when locked; extend the suffix to '(auto)' when an auto-drop is active and '↑ramping' while easing back. The player always retains manual override (any - / = press, or toggling auto off). Smooth ramp-back over ~1.5 s avoids a jarring snap.

**UI needs:**

Extend HUD._scale_text to show the auto-warp state (TARGET vs EFFECTIVE, plus a cause tag: 'INBOUND'/'TERMINAL'/'INTERCEPT'). A small persistent 'AUTO-WARP 8x' indicator near the TIME row. Add 'AUTO TIME-WARP' to the F1 overlay (new ActionDef). Optional: a brief screen-edge pulse when an auto-drop fires (reuse the effects/hint layer) so the player notices WHY time slowed.

**Game-model mapping (reuse vs add):**

REUSE TIME_SCALES + SandboxControls.requested_scale + the per-frame main.py time_scale = state.effective_time_scale() seam (no loop change). GENERALIZE world.world.launch_realtime_lock into a family of 'drop predicates'. ADD: a TimeWarpDirector on SandboxControls (or a small module game/timewarp.py, pure + unit-testable) holding target_idx (extends _scale_idx), an auto_enabled bool, a current_ramp scalar, and event_drop(world)->bool. effective_time_scale becomes: if launch_lock or any drop predicate true → ease toward 1x; else ease toward requested. Extend TIME_SCALES to (1,2,4,8,16,32,64).

**Implementation sketch + test contracts:**

Files: new game/timewarp.py (pure TimeWarpDirector: tick(dt_real, requested_scale, drop_active)->effective_scale with ease + dwell; no GL, no pygame), game/controls.py (TIME_SCALES extended; SandboxControls owns a TimeWarpDirector; auto_warp_toggle action), game/sandbox.py (effective_time_scale delegates to the director, passing the OR of launch_realtime_lock(world.missiles) and the fog-safe drop predicates), game/hud.py (_scale_text shows target/effective/cause), game/keybinds.py (ActionDef auto_warp_toggle=K_t). Drop predicates (game/timewarp.py or sandbox helpers, all fog-safe): inbound_detected(world)= any track in world.contacts.tracks with is_air and a hostile-strike id present in world._strike_board (player-detected only); own_terminal(world)= any player (not is_hostile) Missile with phase_label=='TERMINAL'; intercept_window(world)= any non-hostile SamMissile TERMINAL OR world Pantsir engaging. TEST CONTRACTS (tests/test_timewarp.py, headless, pure director + integration with a fake world): (a) director at target 8x with no drop returns 8x (after ramp settles); (b) drop_active True → eases to 1x within the ramp window and stays (dwell) >=1 s after drop clears; (c) ramp-back reaches target within ~1.5 s; (d) launch lock still forces 1x (regression: keep test_sandbox/test_combat launch-lock behavior green); (e) FOG-OF-WAR contract test: an undetected hostile (in world.missiles, is_hostile, NOT in _strike_board/contacts.tracks) does NOT trigger inbound_detected (assert no drop) — this is the load-bearing fog test; (f) determinism: stepping the world at 1x vs at 8x (auto, no events) for the same seed yields identical world.commander/back-plot state at the same sim_time. Update test_controls for the extended ladder + new action.

**Counters / balance:**

N/A (no balance/counter — it's pacing). The one design guard: auto-drop must be debounced/latched with a minimum dwell (e.g. stay at 1x for >=1 s after the last triggering event) so a flickering radar track at the horizon can't strobe the warp. The dwell timer is real-time, deterministic in sim terms.


---
## Feature: AFTER-ACTION SCORING (grade from efficiency / time-to-first-fix / was-back-plotted / leak rate / base intact %, deterministic per-seed PAR)  _(effort: M)_

**What it is + real-world grounding:**

On battle end (victorious/defeated, already latched), compute a letter grade from measured performance metrics, compared against a deterministic per-seed PAR so the same seed has a fixed bar to beat (feature_ideas #2, GAME_ANALYSIS §7). Metrics, all from EXISTING sensor-derived or own-force state: (1) rounds-vs-kills efficiency = enemy assets killed per player round expended; (2) time-to-first-fix = sim_time of the first ACTIONABLE enemy contact (the recon→fire loop's opening move); (3) was-back-plotted = did the enemy commander confirm a launch cluster (world.commander.picture.clusters with any targetable) — i.e. did you get found; (4) leak rate = player rounds that reached terminal/hit vs launched (the go-low payoff); (5) base intact % = surviving player structures / total. Physics-honest: every metric is a measurement of what already happened in the sim, not a roll.

**Platform (launched from / carried by):**

N/A (an end-of-battle analysis system). It instruments all player platforms (round counts) and reads enemy-asset death state for kill tallies.

**Sensors (uses / detected by):**

Scoring READS sensor-derived state but does not itself sense. 'time-to-first-fix' is measured from the player's contact picture (the first contacts.tracks entry / first ELINT actionable fix via elint.last_heard+is_actionable), honoring fog. 'was-back-plotted' reads world.commander.picture.clusters — the ENEMY's sensor-derived belief, which is already fog-honest by construction (the commander never reads truth). Kill tallies read ground-truth death flags (ships ST_GONE, structure.alive, airfield.alive) — legitimate at end-of-battle for an after-action report (the battle is over; the report is omniscient by design, like a real AAR).

**AI brain (how the enemy commander uses or counters it):**

The 'was-back-plotted' axis is precisely a read of the enemy brain's success: world.commander.picture.clusters / _back_plots and emitter intel (located). Scoring does not change the commander; it grades the player against it. This couples the score to the enemy AI's sensor-only behavior — staying silent (R) and going low (lo-lo) to avoid back-plot directly improves the grade, reinforcing the core EW loop. No commander code change; only new read-only accessors if needed (the fields are already public-ish: picture.clusters, picture._back_plots).

**Player UX:**

The CombatEndOverlay (game/combat_end.py) gains a stats block above the REMATCH/NEW BATTLE/MAIN MENU rows: a big letter grade (S/A/B/C/D), then metric rows (KILLS x/y, ROUNDS n, EFFICIENCY, FIRST FIX T+mm:ss, BACK-PLOTTED YES/NO, LEAK RATE %, BASE INTACT %), each shown vs PAR (e.g. 'FIRST FIX 4:12  / PAR 6:00 ✓'). Color cues reuse OK_COL/WARN/DANGER. No new input — it renders in the existing overlay.

**UI needs:**

Extend game/combat_end.py CombatEndOverlay to accept a ScoreCard and render the stats block (resize END_PANEL_W/panel_h; reuse draw_panel/draw_header_rule/row chrome). NEW pure module game/scoring.py: ScoreCard dataclass + compute_scorecard(world, telemetry) + grade(scorecard, par) + compute_par(seed, config) — all GL-free, unit-tested. A telemetry accumulator on CombatState tracks rounds_fired (per weapon), first_fix_t, peak leak counts during the battle (end-state alone can't see leak rate, so accumulate during sim_step).

**Game-model mapping (reuse vs add):**

REUSE: world.victorious/defeated, world.ships (ST_GONE), world.structures/.airfield/.enemy_radars (.alive), world.commander.picture.clusters/_back_plots, world.contacts.tracks (first-fix), world.elint (actionable timing), the magazine counters (rounds = cap - current + refills; better: count in launch wrappers). ADD: CombatState telemetry dict updated in sim_step (round counters by hooking request_launch/_request_sam_launch return values; first_fix_t latched when contacts.tracks first non-empty with an enemy ship/site; leakers counted on player-round ship_hit/base events). compute_par(seed,config): deterministic — derive a target time/efficiency from config force counts via a fixed formula + a small seeded jitter from np.random.default_rng([seed, 8]) so PAR is fixed per seed and reproducible.

**Implementation sketch + test contracts:**

Files: new game/scoring.py (ScoreCard, compute_scorecard, compute_par, grade), game/combat.py (telemetry accumulation in sim_step + __init__; pass ScoreCard into _open_end_overlay), game/combat_end.py (render the stats block; CombatEndOverlay.__init__ gains scorecard=None param, defaulting to no-stats for the legacy/smoke path). Key fns: compute_scorecard reads world+telemetry → metrics; grade maps (metrics vs par) → letter via fixed thresholds. TEST CONTRACTS (tests/test_scoring.py, headless): (a) compute_par(seed,config) is deterministic (same args → identical par) and different seeds → different par; (b) a fabricated 'perfect' world+telemetry (all enemy dead, base 100%, low rounds, early first-fix, no clusters) grades S; a 'bad' one (base destroyed, back-plotted, high rounds) grades D; (c) was_back_plotted reads picture.clusters correctly (inject a targetable cluster → YES); (d) leak_rate/efficiency computed from telemetry counters match hand-computed values; (e) CombatEndOverlay with a ScoreCard renders without crashing (headless input-logic test like test_combat_setup) and exposes the metrics for assertion; (f) the None-scorecard path (smoke) still works. Add a probe tool tools/probe_scoring.py that plays a scripted battle and prints the card (mirrors playtest_killchain.py).

**Counters / balance:**

N/A (grading, not a weapon). Balance note: PAR must scale with config difficulty (more destroyers/radars = more lenient time PAR, stricter efficiency PAR) so a hard seed isn't unfairly graded. The grade is advisory (drives campaign bonuses in the sibling feature) — it never blocks play.


---
## Feature: CAMPAIGN (chain of seeded battles, persistent ammo + base damage carried forward, scarce resupply, escalating enemy)  _(effort: L)_

**What it is + real-world grounding:**

A meta-layer wrapping the existing single-battle CombatConfig→battle→end flow into a chain of 5–8 deterministically-seeded battles. Between battles: player magazines and base damage CARRY FORWARD (the finite-magazine economy becomes a campaign resource), with a SCARCE resupply tranche granted between battles (tunable, e.g. partial Oniks/SAM top-up scaled by the previous battle's score), and an ESCALATING enemy (each battle increments force counts / doctrine aggression via the existing CombatConfig fields). Built directly on the LOCKED CombatConfig schema + clamp_config + the existing setup/end screens (feature_ideas #56 'Campaign attrition ledger', the MEMORY 'finite-magazine economy' note).

**Platform (launched from / carried by):**

Governs all player platforms across battles (their ammo/damage state persists). The escalation acts on enemy platforms via CombatConfig counts (n_destroyers, n_enemy_radars, n_pantsir-equiv, fighters/AWACS) and a new doctrine knob. No new in-battle platform.

**Sensors (uses / detected by):**

No sensor interaction within a battle (each battle's fog-of-war is untouched). The only cross-battle 'intel' concept (optional, backlog): carry a small starting-intel bonus on a high score (e.g. one pre-known enemy site) — but that must be expressed as a fog-of-war seed into the NEXT battle's known_enemy_sites at t=0, NOT as enemy-truth access. Default campaign keeps each battle's fog fresh to stay safe.

**AI brain (how the enemy commander uses or counters it):**

Escalation tunes the enemy commander's environment, not its fog-honesty: more destroyers/radars/fighters (CombatConfig counts) and an optional 'aggression' scalar that the commander already supports implicitly via more sensors/magazines. The commander remains strictly sensor-only every battle. A new doctrine field would map to existing knobs (e.g. CAP_TARGET_AIRBORNE, salvo periods) seeded per-battle — but to respect the LOCKED CombatConfig schema, escalation rides EXISTING fields (counts + ammo) plus a separate CampaignState scalar passed alongside config, never by mutating the frozen schema.

**Player UX:**

A new CAMPAIGN item on the main menu (alongside SANDBOX/COMBAT). Selecting it opens a campaign hub screen (reuse the _ListScreen/setup-screen chrome): shows the battle ladder (BATTLE 1..N, completed grades), the persistent ledger (remaining Oniks/Zircon/48N6/40N6/57E6, base damage per structure), the resupply granted, and START NEXT BATTLE. The end-overlay's NEW BATTLE row becomes 'NEXT BATTLE' in campaign mode (advances the chain, applies resupply, persists the ledger). A campaign is saved to %APPDATA%/ONIKS so it survives a quit (reuse keybinds.py settings_path pattern).

**UI needs:**

NEW screen game/campaign_screen.py (CampaignHubState, GL-deferred like CombatSetupState): battle ladder + ledger + resupply + START. EXTEND game/combat_end.py for campaign mode (NEXT BATTLE wording + carry the scorecard into resupply). NEW persistence in a campaign module. Reuse all states.py chrome constants. The status panel (sibling) naturally shows the carried-forward ammo in-battle. A small 'CAMPAIGN BATTLE 3/6' banner in the HUD corner during a campaign battle.

**Game-model mapping (reuse vs add):**

REUSE CombatConfig + clamp_config (every per-battle config MUST go through clamp_config — never hand-build a frozen CombatConfig that bypasses the ranges). REUSE the magazine fields as the persistence surface: at battle end, snapshot world._oniks_ammo, world._zircon_ammo, world.sam_ammo, world.sam_ammo_40n6, each Pantsir.missile_ammo/gun_ammo, and each structure.alive/hp. ADD: new module game/campaign.py with CampaignState dataclass {seed, battle_idx, n_battles, ledger:{oniks,zircon,s300_48n6,s300_40n6,pantsir_57e6,pantsir_gun}, base_damage:{structure_id: hp}, grades:[...]} + functions next_config(campaign)->CombatConfig (escalates counts via a deterministic schedule, seeds each battle as derive_seed(base_seed, battle_idx)), apply_resupply(campaign, scorecard), load/save (JSON, %APPDATA%/ONIKS/campaign.json). Determinism: each battle's world RNG is default_rng([base_seed, battle_idx, phase_tag]) — REQUIRES threading battle_idx into world/combat.py's child-stream tags (currently [seed, tag]); add an optional config field carrier or pass battle_idx through CombatState (NOT into the frozen CombatConfig). Carrying ammo in needs a new CombatWorld ingest path: an optional 'initial_state' arg applied AFTER _arm_magazines (sets _oniks_ammo, sam_ammo, etc. and structure hp) — mirrors how _arm_magazines overwrites counters post-super-init.

**Implementation sketch + test contracts:**

Files: new game/campaign.py (CampaignState + next_config/apply_resupply/load/save/derive_seed, all pure + JSON, unit-tested), new game/campaign_screen.py (CampaignHubState), main.py (App.open_campaign(), App.start_campaign_battle(campaign), thread battle_idx into start_combat; CAMPAIGN menu wiring), game/states.py (MenuState MAIN_ITEMS gains 'CAMPAIGN'; _fire routes it), game/combat.py (CombatState accepts initial_state + battle_idx; snapshot helper world_snapshot(world) for end; pass campaign through to end-overlay NEXT BATTLE cb), world/combat.py (optional initial_state ingest after _arm_magazines + battle_idx threaded into the [seed, tag] child-stream tags as [seed, battle_idx, tag]; default battle_idx=0 keeps every existing call/test bit-identical), game/combat_end.py (campaign-aware NEXT BATTLE). TEST CONTRACTS (tests/test_campaign.py, headless): (a) derive_seed deterministic + distinct per battle_idx; (b) next_config always returns a clamp_config'd CombatConfig within all ranges even at high battle_idx (escalation can't exceed clamps); (c) round-trip persistence: save→load yields an equal CampaignState; (d) ammo carry-forward: build a CombatWorld with initial_state {oniks_ammo:2} → world._oniks_ammo==2 after init (and DEFAULT path with initial_state=None unchanged — regression for every existing test); (e) base_damage carry: a structure entered at hp=1 starts the next battle damaged; (f) apply_resupply scales with scorecard grade deterministically and never exceeds the config cap; (g) DETERMINISM regression: CombatWorld(cfg) with battle_idx=0 produces the SAME fleet anchors as today's CombatWorld(cfg) (the new tag dimension must default-collapse so test_combat_config seeded-determinism stays green); (h) escalation monotonic: battle_idx N+1 has >= the enemy force of N (until clamp ceiling). Add a probe tools/probe_campaign.py chaining 3 battles headless via the playtest harness.

**Counters / balance:**

Balance is the campaign's whole point: scarce resupply + persistent attrition means the salvo/saturation king move (sibling feature) has a CAMPAIGN cost — empty your magazine to win battle 2 and you enter battle 3 dry. Escalating enemy counts must be bounded by clamp_config (CLAMP_DESTROYERS max 12, etc.) so escalation can't produce an unspawnable fleet (world/spawn_zones must still place them — reuse the existing 25 km separation contract, already tested to n_destroyers=10). Resupply scaled by score creates the risk/reward loop (a clean win → more resupply).
