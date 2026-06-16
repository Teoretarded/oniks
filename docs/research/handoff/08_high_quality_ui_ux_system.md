# Spec 8: High-quality UI/UX system

> Implementation-research spec for a fresh implementer. Read HANDOFF_README.md first for codebase orientation + non-negotiables.

## Summary
I read the real renderer and every existing UI surface before designing. The whole UI is ONE batched ortho pass (engine/text.py: draw_text/draw_rect/draw_lines append float32 quads in submission order; flush() = one glDrawArrays). Atlas is Consolas bold baked at 14/18/28/56pt (ASCII 32-126 + a white block for fills) — NO images, gradients, rounded corners, or per-glyph antialiased ornament beyond that. A complete, on-style visual language already exists and MUST be the spine of every new surface: game/states.py exports the palette tokens (BG0/BG1/BG2/LINE_COL/ACCENT/ACCENT_DIM/DANGER/OK_COL/WARN/TEXT_COL/MUTED/DISABLED), the 8px grid constants (ROW_H=40, PAD=16, FOCUS_BAR_W=3, TICK_LEG=8), and the two reusable chrome primitives draw_panel() (BG1 fill + 1px LINE border + 4 amber corner ticks + optional powered-on strip) and draw_header_rule() (1px line + 24px amber cap). The _ListScreen base already encodes the interaction grammar (UP/DN nav, hover/click hit-rects, 3px focus bar, 80ms ACCENT press-flash before firing, audio.ui_click on every state change, deferred-GL/headless-testable pattern). docs/research/ui_reference.md §1-5 is normative and these features are a strict superset of it.

My deliverable: (A) a consolidated visual-language layer — 6 new reusable widget primitives added to game/states.py (panel/rule/ticks already exist; I add badge, gauge_bar, mini_compass, tab_strip, scroll_list, toast_stack, plus a shared `hud_widgets.py` for the in-game overlay strips) so every other cluster's UI is assembled from the same vocabulary instead of one-off draws; (B) the specific surfaces the other clusters need, each grounded in real data sources (ContactBoard.tracks = dict(pos,vel,age,t_next,is_air) keyed by ship_id/aircraft_id; launch-warning rounds injected instantly into contacts.tracks; world.missiles is_hostile flags; RWR alerts; EnemyPicture for the post-battle truth reveal; controls.requested_scale vs effective_time_scale for the time-warp pill). 

Color semantics are FIXED and load-bearing (the "physics not dice / fog of war" contract made legible): amber ACCENT = the one brand/selection accent only; OK_COL green = friendly/ready/armed; WARN amber-orange = reloading/transient/caution; DANGER red = inbound/destroyed/terminal/destructive; MUTED = labels; cyan family (already used for the drone) = friendly-truth telemetry; the contact-orange CONTACT_COL = fog-of-war estimates (never truth). A hard rule I enforce in every spec: anything the player learns from a sensor renders in the contact/estimate idiom (faded by age, uncertainty shown), anything that is friendly truth renders in the cyan/green idiom — the UI itself must never let truth and estimate look alike, or it leaks the fog. Performance contract: the overlay is already a single flush; the budget is total quad count, so every new strip is rect+line+text only, uses the existing draw_text quad cache (keyed by string+pos+color, ~1us hit), culls off-screen rows, and only the threat strip animates (a sin-alpha pulse on the existing _pulse_t pattern, zero new GL state). I prioritized a build list of 12 surfaces in 4 tiers; the threat-warning strip + tube/battery panel + contact intel panel + toast/hint upgrade are the foundation everything else composes onto.

**Dependencies:** FOUNDATION FIRST — the widget primitive library (states.py additions + game/hud_widgets.py) must land before anything else; every other surface composes from badge/gauge_bar/mini_compass/tab_strip/scroll_list/toast. It depends on nothing new (only the existing TextRenderer + states.py palette/grid), so it can start immediately.

Cross-cluster data the UI consumes (these are READS the UI needs other clusters to provide or stamp):
- track['kind'] and track['size'] stamps on ContactBoard tracks (one-line adds in world/combat.py _update_strike_contacts and sim/contacts.py update()) — REQUIRED by the threat strip AND the contact intel panel. Smallest, highest-leverage cross-cluster dependency; coordinate with the sensors/threats cluster.
- world.ledger (typed battle events + per-round death cause) — REQUIRED by the After-Action/shot-debrief screen; the world already drain_events() typed kinds, so this is a recording layer the new-system cluster owns.
- CombatConfig.mission_type / posture / starting_intel fields — REQUIRED by the briefing screen; owned by the new-system cluster (world/combat_config.py).
- Per-launcher relocate() API + transit timer, and the salvo ripple driver hooks — the relocation + salvo UIs DRIVE these; the world/sim cluster must expose them (the UI provides the pure preview/lane helpers and the input mode).
- Submarine + sonobuoy entities + an escort-jammer degradation factor + SM-6 real engagement — the ASW overlay, EW overlay, and enemy-WEZ envelope bubbles RENDER these; owned by the enemy/sensors clusters. The UI overlays are cloneable from the existing _elint_overlay/_sam_ring with zero sim work once the data exists.

Ordering within this cluster: (1) widget library; (2) threat strip + tube panel + contact intel panel + toast/hint upgrade (the in-battle legibility core, all depend only on the kind/size stamps); (3) time-warp pill (depends on threat strip's threat_rows for auto-warp); (4) briefing + AAR screens (depend on config/ledger from new-system); (5) relocation, salvo, envelopes (depend on world/sim APIs); (6) ASW + EW overlays (depend on submarine/jammer from enemy clusters — last, but the overlay code is the cheapest because it clones _elint_overlay).

Determinism/test note: every pure helper listed is headless-testable with a FakeText draw-call recorder (the established LOCKED convention — states.py/hud.py/tactical_map.py already isolate pure logic from GL). No new GL state objects are introduced; everything rides the single existing flush(), so the performance contract (one ortho pass) is preserved.

**Open questions:** 1. Salvo input verb: hold-launch-key vs an explicit salvo-count stepper on the map — the former is fewer keys, the latter is more legible. Recommend the stepper (matches the existing combat_setup stepper idiom) with hold-to-ripple as a power-user shortcut. Needs a playtest call (the MEMORY 'playtest before polish' note applies).
2. Contact intel panel docking: bottom-left (opposite the telemetry block) vs a floating tag near the selected contact. Floating risks overlapping the map; docked is safer but uses fixed real estate. Recommend docked on the map, compact-tag on the HUD.
3. The emissions meter reads the enemy's ESM fix_progress for the PLAYER'S OWN emitters to show 'how loud am I' — this is a deliberate, documented exception to 'UI shows only player-side state' (it's the player's own exposure, not an enemy position). Confirm this is acceptable, or derive an equivalent player-side accrual mirror so the UI never imports EnemyPicture.
4. Truth-reveal on the AAR: how much enemy reasoning to expose (back-plot clusters, EMCON windows, package decisions). More is a better payoff but risks spoiling the next replay's surprise on the same seed. Recommend a 'REVEAL TRUTH' toggle (off by default).
5. Atlas additions: the spec uses only the existing 14/18/28/56pt Consolas bake; if any surface wants an icon glyph set (ship/air/missile silhouettes) we'd either bake a tiny vector-icon set as draw_lines primitives (cheap, on-style) or add a glyph row to the atlas. Recommend line-drawn mini-icons (no atlas change) to stay within the no-images constraint.
6. Confirm there is screen budget for a right-edge threat strip + top-left telemetry + bottom-left intel simultaneously at the minimum supported resolution (the 8px grid + 268px panel width assume >=1080p; verify the smallest target window).


---
## Feature: Widget primitive library (the shared vocabulary)  _(effort: M)_

**What it is + real-world grounding:**

Six new reusable, pure, headless-testable draw helpers added alongside the existing draw_panel()/draw_header_rule() in game/states.py, plus a new game/hud_widgets.py for the in-game (translucent, alpha 0.55) variants. This is the foundation that makes every other cluster's UI cohesive instead of bespoke. Grounded in the fact that states.py ALREADY proved this pattern (draw_panel/draw_header_rule are imported by hud.py, combat_setup.py, combat_end.py) — I am generalizing what's already working. Real-world grounding: military FUI (the ui_reference.md north stars Nuclear Option / Carrier Command 2) is built from exactly this kit — one accent, monospace, thin rects, status badges, bar gauges.

**Platform (launched from / carried by):**

N/A — this is the rendering vocabulary every player platform's UI is drawn with (Bastion/S-300/Pantsir/drone/radar panels all compose these). No sim entity.

**Sensors (uses / detected by):**

N/A directly; but two helpers encode the sensor-vs-truth visual contract: badge() takes a semantic state enum (READY/RELOAD/SILENT/INBOUND/DESTROYED) mapping to the fixed palette, and contact-idiom helpers fade by track age so estimate-data can never be drawn like truth-data.

**AI brain (how the enemy commander uses or counters it):**

N/A — pure presentation. (The widgets RENDER enemy-picture-derived intel in the post-battle reveal, but never feed the AI.)

**Player UX:**

Indirect: consistent focus bars, press-flash, hover, and badge colors mean the player learns one interaction grammar once and it holds across every screen and HUD strip.

**UI needs:**

These ARE the UI primitives. New helpers: (1) badge(text,x,y,state) — small filled rect + 1px border + centered CAPS label, color by semantic state; (2) gauge_bar(x,y,w,h,frac,color,bg) — fuel/ammo/fix-quality bar, 1px LINE track + filled portion + optional ticks; (3) mini_compass(cx,cy,r,bearings) — a small bearing ring with tick marks and N marker for the threat strip / intel panel; (4) tab_strip(x,y,labels,active) — the underline-tab pattern already hand-rolled in combat_setup.py, extracted; (5) scroll_list(...) — the whole-row scroll math already in states.py (visible_count/scroll_to_focus/max_scroll) wrapped with a draw loop + 2px track/4px thumb; (6) toast_stack — see the toast feature.

**Game-model mapping (reuse vs add):**

Reuse: states.py palette tokens + grid constants + TextRenderer.draw_*; the existing draw_panel/draw_header_rule stay as-is. Add: a SEMANTIC_COLORS dict mapping state enum -> color so badges/labels are never hard-coded per call site. Nothing in sim/ or world/ changes.

**Implementation sketch + test contracts:**

Files: edit game/states.py (add badge/gauge_bar/mini_compass/tab_strip/scroll_list + SEMANTIC_COLORS); NEW game/hud_widgets.py (HUD-alpha variants: same fns with PANEL_ALPHA=0.55 default, so the in-game strips match the menu chrome at lower opacity). Key fns: `def badge(text,x,y,state,size=SMALL_SIZE)->float` returns width for layout; `def gauge_bar(text,x,y,w,h,frac,col,*,ticks=0)`. TEST CONTRACTS (tests/test_widgets.py, headless via a FakeText recorder that captures draw calls): badge() emits exactly 1 rect + 1 border-lines + 1 text and returns measured width; gauge_bar(frac=0.0) draws no fill quad, frac=1.0 fills full width, frac clamps to [0,1]; SEMANTIC_COLORS has an entry for every state enum (parametrized over the enum); mini_compass(bearings=[047]) places the tick at the right angle (assert pixel within tol). Refactor combat_setup.py's inline tab code to call tab_strip and assert identical output (regression).


---
## Feature: Threat-Warning HUD strip (escalating inbound board)  _(effort: M)_

**What it is + real-world grounding:**

A persistent right-edge vertical strip listing every inbound hostile track — one row per threat: type icon, bearing, range, closing time-to-impact (TTI), with rows escalating color (MUTED->WARN->DANGER) and the nearest terminal threat pulsing. This is the #1 consensus feature in BOTH feature_ideas.md and GAME_ANALYSIS.md §7. The data already exists and is thrown away: world/combat.py _update_strike_contacts injects launch-warning rounds (enemy SM-2/AIM-9X) into contacts.tracks the instant they fire (is_air=True), and radar-gated Tomahawk/JASSM/HARM appear once detected; sandbox world.missiles carries is_hostile. Real-world grounding: an RWR/EW threat tote + a CDS (combat direction system) inbound-raid summary — count, type, bearing, TTI is exactly what a ship's CIC shows.

**Platform (launched from / carried by):**

Defends ALL player platforms (the strip is global to the battle, not per-launcher). Threats it shows are launched by: enemy destroyers/carrier (SM-2, Tomahawk), fighters (AIM-9X, HARM, JASSM). Player counters by relocating TELs (relocation UI), going radar-silent (R), and S-300/Pantsir intercept.

**Sensors (uses / detected by):**

Reads ONLY the player picture: contacts.tracks where is_air and the track was injected as a hostile (launch-warning instant cue) OR radar-gated detection. It must NOT read world.missiles truth for hostiles — it reads the SAME fog-gated track board the tactical map uses, so an undetected Tomahawk does NOT appear until radar finds it (preserving fog of war). TTI is computed from the track's dead-reckoned pos+vel toward the nearest friendly asset (estimate, not truth).

**AI brain (how the enemy commander uses or counters it):**

The strip is the player's symmetric counterpart to the enemy's EnemyPicture: it is the fog-pierced view of what the AI has THROWN at the player. It does not feed the AI. Honesty check: because it reads track pos/vel (sensor estimate) not the real missile, a track that the enemy commander's AWACS-EMCON or a notching fighter denies the player's radar will correctly drop off the strip — the UI stays sensor-true.

**Player UX:**

Always-visible thin strip, top-right under the corner labels (does not overlap the top-left telemetry block). Each row: [TYPE] BRG 047 | 32 km | TTI 18s. Rows sort by TTI ascending. Color: TTI>60s MUTED, 20-60s WARN, <20s DANGER + 2Hz sin-alpha pulse (reuse the _pulse_t breathing pattern from SettingsState). A count header 'INBOUND 3' in DANGER when any <20s. Clicking a row (when the map is open) centers/selects that contact. Audio: a one-shot warning tone on a NEW track appearing (hook the existing audio.play one-shot seam; debounced per track id).

**UI needs:**

New widget surface composed of: a borderless translucent column (hud_widgets panel at alpha 0.45, no fill when empty), per-row badge() for type, mini_compass tick or a 3-char bearing, gauge_bar optional for TTI. Needs a NEW threat_rows() pure helper (in game/hud.py) that turns the track board into sorted (type,brg,rng,tti,severity) tuples.

**Game-model mapping (reuse vs add):**

Reuse ContactBoard.tracks + estimated_pos(); reuse the is_hostile/launch_warning convention already in world/combat.py. ADD a small per-track 'kind' tag so the strip can label SM-2 vs TOMAHAWK vs HARM (currently tracks have no type field — the cleanest fix is for _update_strike_contacts to stamp track['kind']=m.weapon.weapon_id when injecting; this is a one-line world-side add that the intel panel also needs). No new sim physics.

**Implementation sketch + test contracts:**

Files: game/hud.py (add pure `threat_rows(world, friendly_xz, now)->list[tuple]` + a `_threat_strip(self,w,h)` draw method called from HUD.draw and also from tactical_map _chrome so it shows on the map too); world/combat.py (stamp track['kind'] in _update_strike_contacts — coordinate with the threat/sensors cluster). Constants: TTI_WARN_S=60, TTI_CRIT_S=20, STRIP_W=180. TTI = range / max(closing_speed, eps); closing_speed = -d/dt of range using track vel projected onto bearing-to-asset. TEST CONTRACTS (tests/test_threat_strip.py, headless): threat_rows sorts by TTI ascending; a track with TTI 5s gets severity DANGER, 40s WARN, 90s MUTED; an inbound moving AWAY (closing<=0) yields TTI None and sorts last / is dimmed; only is_air hostile-kind tracks appear (a friendly own missile or a surface ship contact never appears); empty board -> []; determinism (same tracks -> same rows). Pulse uses sin(_pulse_t) so it's frame-time pure.


---
## Feature: Tube / battery status panel (per-launcher salvo readout)  _(effort: M)_

**What it is + real-world grounding:**

Replaces the single STATUS/RELOADING line in the Bastion & S-300 HUD blocks with a per-tube board: one cell per tube showing READY (green) / RELOADING n s (amber gauge) / EMPTY, plus a magazine summary and the salvo-fire affordance. Directly requested in GAME_ANALYSIS.md §7 ('Show which tubes are loaded/reloading') and feature_ideas.md (qol: Tube/battery status). The sim already models this: world/combat.py has self._oniks_tubes and self._s300_tubes with per-tube reload_left (_step_oniks_tubes/_step_s300_tubes), and Phase-8 multi-launcher battery layout exists (_oniks_launcher_positions). Real-world grounding: a TEL/VLS readiness panel — Bastion K-340P has 2 tubes per TEL; S-400/300 5P85 has 4; per-cell ready/reload state is standard.

**Platform (launched from / carried by):**

Bastion TEL (Oniks/Zircon tubes), S-300 5P85 TEL (48N6/40N6 tubes), and a compact Pantsir row (already exists via pantsir_status_row — fold into the same visual language). One panel layout, parameterized by the active platform.

**Sensors (uses / detected by):**

N/A — these are FRIENDLY OWN assets, so this is truth telemetry (drawn in the green/cyan idiom, never the contact-orange estimate idiom). The panel's correctness contract is that it reads world tube state directly (own side), which is allowed (it is the player's own kit).

**AI brain (how the enemy commander uses or counters it):**

N/A for the panel. (Indirectly, the enemy's back-plot localizes whichever launcher fired — so the relocation UI pairs with this; the panel itself just shows readiness.)

**Player UX:**

Tube cells laid out as a row of badges under the launcher header: [1 RDY][2 RDY][3 17s][4 RDY]. A reloading cell shows a thin gauge_bar of reload progress (1 - reload_left/reload_total). Magazine line: 'MAG 6/12  RLDG 22s' reusing oniks_ammo_row. Adds the SALVO affordance: a hint 'HOLD SPACE: RIPPLE FIRE' when >1 tube ready (the salvo key is a paired qol feature; the panel surfaces it). Selecting the platform (TAB) swaps which battery's tubes show.

**UI needs:**

A tube-cell row built from badge() + gauge_bar(); a magazine summary line. Slots into the existing top-left _block() panel (so it inherits the corner ticks + header rule). Needs a pure tube_cells(world, platform)->list[(label,state,frac)] helper.

**Game-model mapping (reuse vs add):**

Reuse world/combat.py _oniks_tubes/_s300_tubes (each a dict with reload_left), _oniks_launcher_positions, the existing oniks_ammo_row/s300_round_panel/pantsir_status_row pure helpers in hud.py. ADD nothing to sim — the tube dicts already carry reload_left; expose a tube reload-total constant for the progress fraction (read from world config). If a salvo key is added it lives in keybinds (ENGAGEMENT group) — the panel only displays its availability.

**Implementation sketch + test contracts:**

Files: game/hud.py (new pure `tube_cells(world, platform)->list[tuple]` + extend _bastion_block/_s300_block to render the cell row via the new widgets); add SALVO_HINT string. Constants: TUBE_CELL_W=44, TUBE_GAP=6. Fraction = 1 - reload_left/reload_total (clamp). TEST CONTRACTS (tests/test_tube_panel.py, headless): tube_cells for a battery with one tube mid-reload returns that cell state='reload' frac in (0,1) and others 'ready'; an all-empty magazine yields all cells 'empty'; SANDBOX world (no _oniks_tubes) returns [] (panel hidden) — mirrors the existing None-guards in oniks_ammo_row; cell count == number of tubes in the active platform's battery; determinism.


---
## Feature: Click-contact intel panel (fog-of-war track inspector)  _(effort: M)_

**What it is + real-world grounding:**

When the player LMB-selects a contact on the tactical map, a docked panel shows everything the SENSORS know about it and — crucially — everything they DON'T: estimated position/course/speed, track age (staleness), sensor source (RADAR/ELINT/SAR/RWR), an intel-confidence ID ladder (UNKNOWN->CLASSIFIED->IDENTIFIED), and an uncertainty figure. Requested in feature_ideas.md (new-ui: Contact intel panel + Intel-confidence ID ladder). The selection mechanism already exists (tactical_map.selected_contact, pick_contact); today it only moves target_point. Real-world grounding: a CIC track-detail readout / NTDS hooked-track amplifying data — bearing/range/course/speed/quality/ID, with explicit ambiguity when ID is uncertain.

**Platform (launched from / carried by):**

Inspects enemy platforms (destroyers, carrier, fighters, AWACS, inbound missiles) AND can show friendly truth for own assets if clicked — but the headline is enemy contacts, where the fog matters.

**Sensors (uses / detected by):**

This panel IS the sensor-fusion display. It reads contacts.tracks[sid] (pos,vel,age,is_air) + the ELINT/SAR/RWR provenance. Confidence is derived from track age + how recently it was refreshed (fresh, sensor-locked = IDENTIFIED; coasting/stale = UNKNOWN) — purely sensor-derived, never truth. The panel must visibly degrade: a stale track shows 'AGE 47s — DEAD RECKONED' in WARN and a growing uncertainty radius, mirroring the map's alpha-fade. This is the clearest place the fog-of-war contract becomes a designed UI feature.

**AI brain (how the enemy commander uses or counters it):**

N/A for the panel (player-side). But it is the conceptual mirror of EnemyPicture: the player gets a tool to reason about an imperfect picture, exactly as the AI does. The post-battle After-Action reveal (separate feature) can then overlay truth-vs-belief for BOTH sides using this same panel layout.

**Player UX:**

Bottom-left or right docked panel (opposite the telemetry block) that appears only while a contact is selected on the map (and optionally persists as a small tag on the HUD when the map closes). Header = contact id + ID-ladder badge. Rows: CLASS (surface/air/missile), BRG/RNG from active platform, COURSE/SPD (from track vel), ALT (air), AGE + source, CONFIDENCE gauge_bar. A 'last seen' timestamp. If the track is hostile-kind, a one-line threat note ('SM-2 — anti-air').

**UI needs:**

A docked draw_panel with header rule + label/value rows (reuse the _block() layout) + an ID-ladder badge + a confidence gauge_bar + a small mini_compass showing relative bearing. Needs a pure contact_intel(world, sid, origin_xz, now)->dict helper.

**Game-model mapping (reuse vs add):**

Reuse ContactBoard.tracks + estimated_pos + the track['kind'] tag (added for the threat strip). ADD a track classification: today tracks only carry is_air; the ID ladder needs at least a size_class (already computed in contacts._seen via radar_size: 'ship'/'fighter'/'missile') — stamp track['size'] alongside is_air so the panel can label CLASS without truth. Confidence = f(age, refresh recency) computed in the helper, no sim change.

**Implementation sketch + test contracts:**

Files: game/hud.py (pure `contact_intel(...)` + `_intel_panel(self,...)`), game/tactical_map.py (call hud.draw_intel_panel for selected_contact in draw(), and keep showing a compact tag when map closed). contacts.py: stamp track['size'] in update() (one line; coordinate with sensors cluster). Constants: ID ladder thresholds AGE_IDENTIFIED_S=5, AGE_CLASSIFIED_S=20 (older=UNKNOWN). TEST CONTRACTS (tests/test_intel_panel.py, headless): contact_intel on a fresh radar track returns confidence high + id='IDENTIFIED'; age 30s returns id='UNKNOWN' + a non-empty 'dead reckoned' flag; course derived from vel matches atan2(vel.x,vel.z); a None sid returns None (panel hidden); surface vs air vs missile CLASS comes from is_air+size, never from the real entity; determinism.


---
## Feature: Relocation order UI (shoot-and-scoot TEL move)  _(effort: L)_

**What it is + real-world grounding:**

A map-mode order to relocate a TEL/launcher to a new position before the enemy back-plot localizes and strikes it — the direct counter-play to the enemy KILL doctrine. GAME_ANALYSIS.md §5 establishes that losing happens when the commander back-plots your launch cluster and salvos Tomahawks/JASSM; the only defenses today are radar silence and the Pantsir. Mobility is the missing verb. Real-world grounding: shoot-and-scoot is THE doctrine for coastal TEL survival (Bastion-P is road-mobile precisely so it relocates between salvos).

**Platform (launched from / carried by):**

Bastion TEL and S-300 5P85 TEL (the road-mobile launchers). Not the fixed radar station or Pantsir (design choice — keeps scope; can extend). The drone is tasked separately (it already has route waypoints).

**Sensors (uses / detected by):**

The relocation itself emits nothing, but its PURPOSE is sensor-driven: it invalidates the enemy's back-plot cluster (EnemyPicture.clusters) because the next launch comes from a new spot that won't cluster with the old fixes. The UI should hint this ('MOVING BREAKS ENEMY BACK-PLOT'). The move's risk is that an in-transit TEL might be caught by an already-launched strike — surfaced via the threat strip.

**AI brain (how the enemy commander uses or counters it):**

This is a first-class AI-counter, fully no-cheat: the enemy commander only knows where you launched FROM (back-plot fixes are tied to the launch position at fire time). When you relocate and fire again, the new fixes form a NEW cluster (or fail to reach BACKPLOT_FIXES_NEEDED), so a relocated battery genuinely resets the KILL clock. The AI never reads the TEL's real new position — it must re-localize via back-plot, exactly as designed. The relocation UI is the player's lever on the commander's commander.py back-plot pipeline without ever touching it.

**Player UX:**

On the map, with a TEL platform active: press a relocate key (new keybind, ENGAGEMENT group) to enter 'PLACE LAUNCHER' mode, then LMB a destination within a move-radius ring (drawn around the current pos); a ghost TEL marker + an ETA (distance/move-speed) shows; confirm to issue. The TEL becomes UNAVAILABLE (can't fire) for the transit time, shown as a countdown in the tube panel ('RELOCATING 84s'). A move-radius ring and the candidate path render in the friendly-green idiom.

**UI needs:**

Map: a move-radius ring (reuse the range-ring draw), a ghost launcher star at the cursor, an ETA tag, a confirm/cancel hint line. HUD: a RELOCATING countdown badge in the tube panel. Reuses the toast system for 'BATTERY RELOCATED'.

**Game-model mapping (reuse vs add):**

ADD world-side state (coordinate with a sim/world cluster): a per-launcher relocate(target_xz) that sets an in-transit timer and disables fire until arrival, then updates _oniks_launcher_positions/_tel_pos. The UI layer (sandbox + tactical_map) drives it. Reuse the existing platform-active routing + the map's screen_to_world + ground_aim_point clamp. The 3D TEL render already reads _tel_positions, so the move is reflected visually for free.

**Implementation sketch + test contracts:**

Files: game/keybinds.py (add 'relocate' action, ENGAGEMENT, default G); game/tactical_map.py (relocate-placement mode in _click_target + a _relocation_overlay draw with ring/ghost/ETA); game/hud.py (RELOCATING badge in tube_cells); world side adds relocate API + transit timer (owned by the world/sim cluster — UI calls it). Constants: TEL_MOVE_SPEED_MS, RELOCATE_MAX_RADIUS_M. TEST CONTRACTS: UI-side pure `relocation_preview(origin, dest, speed)->(dist, eta, in_radius)` in tactical_map (tests/test_relocation_ui.py): eta=dist/speed; in_radius false beyond RELOCATE_MAX_RADIUS_M; a dest on water/invalid clamps via ground_aim_point. World-side relocate test (owned by other cluster) asserts fire refused during transit + position updated on arrival + back-plot cluster does NOT absorb post-move fixes. Determinism.


---
## Feature: Swarm / salvo waypoint bundle tasking  _(effort: L)_

**What it is + real-world grounding:**

Extends the existing single-route launch planner to plan a SALVO: N rounds sharing a bundle of waypoints with per-round fan-out (time/heading stagger) so the player can saturate the SM-2 '<=4 in flight' cap — the king move per GAME_ANALYSIS.md §2/§4. feature_ideas.md ranks the salvo/ripple key #4 and notes multi-tube batteries already exist. The map already has a full waypoint chain (waypoints list, add_waypoint, _plan_chain, MAX_WAYPOINTS, the seeker cone). Real-world grounding: a coordinated time-on-target salvo with offset ingress lanes is exactly how Oniks batteries are doctrinally fired to overwhelm Aegis.

**Platform (launched from / carried by):**

Bastion battery (multi Oniks/Zircon tubes — _oniks_launcher_positions) primarily; the salvo size is bounded by ready tubes (ties to the tube panel).

**Sensors (uses / detected by):**

Targeting still goes through the contact picture (pick_contact / selected_contact) — the salvo aims at a sensor-estimated surface track, not truth. Fan-out lanes are planned on the map; the rounds still fly fog-blind until terminal seeker acquisition (the seeker cone preview already shows this).

**AI brain (how the enemy commander uses or counters it):**

Directly engages the enemy's layered defense: a salvo forces more simultaneous SM-2 commitments than the '<=4 in flight, 3s reload' fire-control can service (enemy_defense.py), so leakers get through — the intended emergent counter. The AI doesn't see the plan; it reacts to the rounds as they're detected, and the threat-saturation is a physics outcome of the fan-out timing, not a UI trick.

**Player UX:**

With a Bastion ready and >1 tube loaded: a SALVO mode (hold the launch key, or a salvo count stepper on the map chrome) shows a fan of N planned routes from the battery, each a slightly offset lane converging on the target, with a stagger readout ('SALVO 4 — 2s STAGGER'). Per-lane waypoints inherit the shared bundle; LMB on a lane lets you nudge it. Confirm fires the ripple. The tube panel shows tubes draining as the ripple steps.

**UI needs:**

Map: multiple PLAN_COL route polylines (the _plan_chain draw, looped over lanes), a salvo-count chevron stepper (reuse the combat_setup stepper idiom), a stagger label. Reuse the seeker cone per lane. A 'RIPPLE FIRING' toast.

**Game-model mapping (reuse vs add):**

Reuse sandbox.waypoints + world.launch (called N times by the ripple) + _oniks_launcher_positions for per-tube origins. ADD a UI-side salvo plan model (count, stagger, per-lane offset) in sandbox; the ripple just calls world.launch repeatedly on a stagger timer (the world already supports many concurrent rounds). No new sim physics — the fan-out is just N independent routes.

**Implementation sketch + test contracts:**

Files: game/sandbox.py (salvo plan state + a ripple-fire driver in request_launch when salvo mode on / key held); game/tactical_map.py (multi-lane plan draw + salvo stepper in _chrome); game/keybinds.py (optional 'salvo_mode' toggle). Pure helper `salvo_lanes(origin, target, waypoints, count, spread_m)->list[route]` (offsets each lane perpendicular to the run-in). TEST CONTRACTS (tests/test_salvo_plan.py, headless): salvo_lanes(count=4) returns 4 routes, symmetric perpendicular offsets summing ~0, all converging within tol of the target; count clamps to ready-tube count; a single tube -> 1 lane (degenerates to today's behavior, regression); stagger schedule is monotone; determinism.


---
## Feature: Sonobuoy placement + ASW coverage overlay  _(effort: L)_

**What it is + real-world grounding:**

Drone-tasking UI to drop sonobuoys and a coverage/ELINT-in-the-acoustic-domain overlay to localize an enemy submarine — the paired counter to the new submarine threat axis (the headline 'big bet' in feature_ideas.md: the one threat radar/SAR/ELINT physically cannot find; a 2nd lose-path independent of the flaky back-plot). The counter REUSES the ELINT least-squares solver in the acoustic domain (sim/recon.py ElintReceiver), and the drone already has a full waypoint-tasking UI. Real-world grounding: P-8/MH-60R sonobuoy fields + DIFAR bearing fixes; a buoy pattern that triangulates a diesel boat's transient is textbook ASW.

**Platform (launched from / carried by):**

Carried/dropped by the recon drone (already a tasked platform with routes). The threat it counters is the enemy submarine (sub-launched cruise salvo). The player's coastal array could also host hydrophones (ties to the coastal-ELINT feature).

**Sensors (uses / detected by):**

Buoys are passive acoustic sensors that produce BEARINGS to a noise source — the exact input shape the ElintReceiver already triangulates. The overlay shows buoy positions, their detection radius, live bearing lines, and a shrinking uncertainty circle as the baseline improves — visually IDENTICAL to the existing _elint_overlay (bearing rays + fix circle), which is perfect for consistency and reuses proven code. Fully fog-honest: a quiet (drifting) sub produces no bearing and no fix.

**AI brain (how the enemy commander uses or counters it):**

The submarine AI (other cluster) decides when to go quiet vs fire from its own sensor picture; the buoy field is the player's no-cheat localization tool against it. The UI never reveals the sub's truth position — only the acoustic fix, which can be stale/ambiguous, so the player faces the same fog the enemy does.

**Player UX:**

Drone platform active on the map: a 'DROP BUOY' key plants a buoy at the drone's current pos (or LMB a planned drop point along the route); buoys render as small friendly-cyan markers with a faint detection ring. As >=2 buoys hear the sub, bearing lines and a fix circle appear (reusing the ELINT visuals). A coverage heat hint shows gaps. A buoy budget counter ('BUOYS 4/8'). The sub contact, once fixed, becomes a normal selectable contact for the intel panel + an Oniks/torpedo target.

**UI needs:**

Map: buoy markers + detection rings + acoustic bearing rays + fix circle (clone _elint_overlay with the buoy color family), a buoy-budget badge, a 'DROP BUOY' hint. Reuses the drone route UI wholesale.

**Game-model mapping (reuse vs add):**

Reuse sim/recon.py ElintReceiver (the solver) + the drone route tasking + the _elint_overlay draw structure + ContactBoard for the resulting sub track. ADD (other clusters): a Sonobuoy entity + acoustic bearing source + the submarine. UI side: a buoy list + budget in the world, drop API called from the drone platform.

**Implementation sketch + test contracts:**

Files: game/keybinds.py ('drop_buoy', ENGAGEMENT); game/tactical_map.py (_asw_overlay cloned from _elint_overlay, buoy markers + budget); game/hud.py (buoy budget badge in the drone block). Pure helper `buoy_coverage(buoys)->list[(pos,radius)]` for the rings. TEST CONTRACTS (tests/test_asw_overlay.py, headless): buoy markers draw at each buoy pos; a fix circle draws only when the acoustic solver error < threshold (mirrors ELINT_CIRCLE_MAX_M gate exactly); budget badge shows remaining/total; with 0 buoys no rings; determinism. (Solver/sub physics tests owned by the sensors/enemy clusters.)


---
## Feature: Mission briefing screen  _(effort: M)_

**What it is + real-world grounding:**

A pre-battle briefing page shown after COMBAT SETUP and before the battle: mission type + objective, starting intel (what you know about the fleet at T0), force ROE, win/lose conditions, and a coastline preview. feature_ideas.md lists Mission types (Sea Denial, Decapitation, Recon-in-Force, Counter-Battery Survival, First-Strike Window) and 'Briefing/variable starting intel' as new-system/new-ui. The setup screen (combat_setup.py) and end screen (combat_end.py) already exist in this exact visual language; the briefing slots between them. Real-world grounding: a strike package brief / OPORD summary — situation, mission, objectives, intel, ROE.

**Platform (launched from / carried by):**

N/A (front-end screen). Describes the forces both sides bring (player Bastion/S-300/Pantsir/drone vs enemy CSG) so the player plans which platforms to use.

**Sensors (uses / detected by):**

Defines the STARTING intel state — e.g. Recon-in-Force starts with the fog fully down (no contacts), Decapitation starts with a partial AWACS ELINT cut. This directly seeds ContactBoard / EnemyPicture initial conditions, making the briefing a real gameplay input, not flavor.

**AI brain (how the enemy commander uses or counters it):**

The mission type selects the enemy doctrine archetype (feature_ideas.md: Aggressive Push / Turtle Screen / Picket / EMCON Ambush), which configures the commander's posture at construction (seed-derived, deterministic). The briefing shows the player the doctrine hint without revealing positions.

**Player UX:**

After START on the setup screen, the briefing renders (same corner-tick panel chrome): MISSION header + type badge, OBJECTIVE line(s), STARTING INTEL block (icons for known/unknown), WIN/LOSE conditions, ENEMY POSTURE hint, a small coastline thumbnail (reuse the map texture). Footer: ENTER DEPLOY / ESC BACK. Mirrors the setup screen's input model exactly.

**UI needs:**

A new full-screen GameState (BriefingState) built from draw_panel + draw_header_rule + label/value rows + badges + a small textured map thumbnail (reuse the tactical_map terrain quad shader at a fixed view). Reuses the _ListScreen confirm/press-flash pattern.

**Game-model mapping (reuse vs add):**

Reuse CombatConfig (carries seed + force counts) — ADD mission_type + starting_intel + posture fields (coordinate with the new-system cluster). Reuse the map pixel array (tactical_map.get_map_pixels) for the thumbnail. The briefing reads config, writes nothing.

**Implementation sketch + test contracts:**

Files: NEW game/combat_briefing.py (BriefingState mirroring combat_setup.py structure — deferred GL, headless input, press-flash DEPLOY); game/states.py menu flow (open_combat_setup -> START -> BriefingState -> start_combat). world/combat_config.py gains mission_type/posture (other cluster). Pure `briefing_rows(config)->list[(label,value,badge)]`. TEST CONTRACTS (tests/test_briefing.py, headless): briefing_rows for a 'Decapitation' config lists the airfield objective; DEPLOY fires start_combat(config) after the press-flash; ESC returns to setup; the win/lose strings match world/combat victory/defeat conditions; determinism (same config -> same rows).


---
## Feature: After-Action / scoring + shot-debrief screen  _(effort: L)_

**What it is + real-world grounding:**

The post-battle debrief: outcome, a score vs a per-seed 'par', a timeline of key events, ammo expended/efficiency, and a per-shot debrief (WHY each round died — 'KILLED BY SM-2 @94km' / 'WHIFF fuel-out 12km short' / 'HIT destroyer'). feature_ideas.md ranks After-action scoring #2 and Shot Debrief #6; both are 'high impact'. The end screen (combat_end.py) already gives REMATCH/NEW BATTLE/MAIN MENU — the AAR EXPANDS it. Real-world grounding: a post-mission debrief / weapon employment summary; a TACTS/ACMI replay summary.

**Platform (launched from / carried by):**

Summarizes every player platform's contribution (Oniks/Zircon hits, S-300/Pantsir intercepts, drone recon coverage) and every enemy platform killed.

**Sensors (uses / detected by):**

This is the ONE screen allowed to reveal TRUTH (the battle is over — no fog to protect), and it should do so DELIBERATELY as a payoff: overlay the enemy's EnemyPicture belief vs the real fleet, and the player's contact picture vs truth, so the player learns how good their recon was. Visually it must distinguish truth (solid) from belief (the estimate idiom) — the same sensor-vs-truth visual contract, now contrasted side by side.

**AI brain (how the enemy commander uses or counters it):**

The reveal exposes the enemy commander's reasoning post-hoc: which back-plot clusters formed, when the AWACS went EMCON, which packages launched and why — turning the no-cheat AI into a readable story. It reads the (now frozen) EnemyPicture; it does not influence the AI (battle is over).

**Player UX:**

Replaces/extends the end overlay: VICTORY/DEFEAT banner (kept), then a scrollable AAR — SCORE vs PAR (gauge_bar), KEY EVENTS timeline (scroll_list), AMMO/EFFICIENCY rows, SHOT DEBRIEF (one row per round: weapon, result badge, range, cause). A 'REVEAL TRUTH' toggle flips the mini-map between your picture and ground truth. Footer keeps REMATCH/NEW BATTLE/MAIN MENU.

**UI needs:**

A scroll_list (the new widget) for events/shots, gauge_bars for score/efficiency, result badges, a mini-map truth toggle (reuse the map thumbnail). Built as an expanded CombatEndOverlay.

**Game-model mapping (reuse vs add):**

ADD a battle event/shot ledger (coordinate with new-system cluster): the world already drains typed events (drain_events: ship_hit, sam_kill, oniks_intercepted, base_hit...) — record them with sim_time + pos into a session ledger; each player round records its death cause. Reuse EnemyPicture (frozen) for the reveal, the map pixels for the thumbnail.

**Implementation sketch + test contracts:**

Files: extend game/combat_end.py (or NEW game/combat_aar.py) with the AAR body; world/combat.py grows a self.ledger fed from drain_events + per-round outcome tagging (other cluster). Pure `aar_summary(ledger, config)->dict(score, par, events, shots)` and `shot_debrief_rows(ledger)->list[tuple]`. TEST CONTRACTS (tests/test_aar.py, headless): shot_debrief_rows maps an 'oniks_intercepted' event to a DANGER 'KILLED BY SM-2' row with the range; a 'ship_hit' to an OK 'HIT' row; score is deterministic from the ledger; an empty ledger yields a valid (zeroed) summary; the truth toggle is pure UI state. Determinism.


---
## Feature: Time-warp indicator + smart auto-warp control  _(effort: S)_

**What it is + real-world grounding:**

A clear time-acceleration pill (current scale, ladder position, and WHY it's clamped) plus an optional event-aware auto-warp that drops to 1x on threats/launches and speeds up during quiet transit. The HUD already shows 'x8 (launch)' text (hud._scale_text) but it's buried in the telemetry rows; the launch cinematic already force-locks 1x (effective_time_scale / launch_realtime_lock). feature_ideas.md ranks Smart auto-time-warp #8. Real-world grounding: sim time-compression UX (DCS/CMO) that auto-decompresses on contact/threat.

**Platform (launched from / carried by):**

N/A (global sim control). But its triggers come from platform events (a launch locks 1x; an inbound threat should auto-drop warp).

**Sensors (uses / detected by):**

Auto-warp reads ONLY the player's own picture (the threat strip's track list) and own launch state — same fog-honest data as the threat strip. It never reads enemy truth to decide when to slow down (so a sneaking Tomahawk you haven't detected won't tip you off via a warp drop — preserving fog).

**AI brain (how the enemy commander uses or counters it):**

N/A. (It reacts to the AI's detected actions via the player picture, symmetric with how the player reacts.)

**Player UX:**

A pill top-center or near the clock: 'x8' with a 5-segment ladder (1/2/4/8/16, the TIME_SCALES tuple) and the active segment lit; when clamped, a small reason tag ('1x — LAUNCH' or '1x — THREAT'). Auto-warp on: the pill shows 'AUTO' and animates segment changes; a key toggles auto vs manual. Slowing on a new inbound is the key game-feel win.

**UI needs:**

A compact ladder widget (5 segment rects + label) + a reason badge. Replaces the inline TIME row's prominence; lives as its own pill. Pure `warp_pill(requested, effective, reason)->(label, segments, reason_text)`.

**Game-model mapping (reuse vs add):**

Reuse controls.requested_scale + sandbox.effective_time_scale + TIME_SCALES + launch_realtime_lock. ADD an auto-warp policy in controls (reads threat_rows() + launch lock to pick a target scale); a keybind to toggle auto. No sim change — it just drives the existing _scale_idx.

**Implementation sketch + test contracts:**

Files: game/hud.py (warp pill draw + pure warp_pill helper); game/controls.py (optional auto-warp policy updating _scale_idx from threat/launch state); game/keybinds.py ('auto_warp' toggle, SIMULATION). Constants: AUTOWARP_THREAT_TTI_S=30 (drop to 1x when any inbound TTI under this). TEST CONTRACTS (tests/test_warp_pill.py, headless): warp_pill(requested=8,effective=1,reason='launch') lights segment[3] but flags clamp with reason 'LAUNCH'; equal requested/effective shows no clamp; auto-warp policy returns target 1x when a sub-30s TTI threat exists, else the requested scale; the policy reads threat_rows (fog) not truth (assert it ignores an undetected hostile); determinism.


---
## Feature: EW / JAMMED map overlay + emissions-budget meter  _(effort: M)_

**What it is + real-world grounding:**

A map overlay that visualizes degraded sensing under enemy jamming (a hatched/dimmed sector where the radar picture is unreliable, raised ELINT sigma) AND a persistent emissions meter showing the player's own radar-on exposure (how localizable you are right now). feature_ideas.md lists EA-18G escort jammer ('collapses your radar range, raises ELINT sigma; the counter to going loud') and the EW/JAMMED overlay (new-ui). The radar-silence mechanic (R / toggle_radar) and the ESM fix model (EnemyPicture.emitters fix_progress) already exist — this makes the invisible EW battle legible. Real-world grounding: a radar performance/jam-strobe display + an EMCON state indicator; jam strobes on a PPI are classic.

**Platform (launched from / carried by):**

Enemy escort jammer (other cluster) degrades the player's radar station + drone sensors; the player's own emitters (radar station, Pantsir radars) are what the emissions meter measures.

**Sensors (uses / detected by):**

Two-way: (1) the JAMMED overlay shows where the player's radar/ELINT is degraded (a sector of raised uncertainty / dropped detection range — derived from the jammer's bearing relative to the player radar); (2) the emissions meter reflects the ENEMY's ESM fix_progress on the player's emitters (i.e., how close the enemy is to localizing the radar station) — read symmetrically from the same accrual the commander uses, but shown to the player as their own exposure. Both are fog-honest: the player sees the EFFECT (degraded picture, rising exposure), inferring the jammer's presence, not its truth position unless localized.

**AI brain (how the enemy commander uses or counters it):**

The emissions meter is the player's window into the enemy commander's BLIND doctrine: as the player keeps the radar emitting, EnemyPicture.emitters[...].fix_progress climbs toward a HARM package. Showing that rising bar lets the player time their radar-silence (R) against the AI's localization — the no-cheat EW duel made playable. The AI still reads only its own ESM accrual; the meter just mirrors that number to the player.

**Player UX:**

Map: a dimmed/hatched arc over the jammed sector with a 'JAMMED' tag and a reduced-range ring; ELINT fix circles visibly enlarge under jam. HUD: a thin EMISSIONS meter (gauge_bar) — green when silent, climbing amber->red as the enemy's fix accrues; a 'LOCATED — HARM RISK' DANGER flag at full fix. The R radar toggle already exists; the meter gives it stakes.

**UI needs:**

Map: a hatched sector (a fan of thin LINE strokes — cheap), a jammed-range ring, a tag. HUD: an emissions gauge_bar + exposure badge. Pure `emissions_meter(world)->(frac, state)` and `jam_overlay(world)->(bearing, halfangle, range_frac)`.

**Game-model mapping (reuse vs add):**

Reuse toggle_radar/radar.emitting + EnemyPicture.emitters fix_progress (the player UI may read the enemy's ESM accrual ONLY for the player's OWN emitters' exposure number — this is the player learning how loud they are, not seeing enemy positions; document the exception). ADD (other cluster) the jammer entity + a player-radar degradation factor; the overlay reads that factor. Reuse _elint_overlay's circle scaling for the enlarged-uncertainty effect.

**Implementation sketch + test contracts:**

Files: game/tactical_map.py (_jam_overlay sector + degraded rings); game/hud.py (emissions meter + exposure badge + pure emissions_meter/jam_overlay helpers). Constants: EXPOSURE_HARM_RISK_FRAC=1.0 (located). TEST CONTRACTS (tests/test_ew_overlay.py, headless): emissions_meter returns frac 0 + state SILENT when radar.emitting False; frac rising + state EXPOSED while emitting; state LOCATED at fix_progress>=1; jam_overlay returns a sector only while a jammer degradation is active, else None; the meter reads the player's own emitter intel, never an enemy entity position; determinism.


---
## Feature: Engagement-envelope shading (range/leak rings)  _(effort: M)_

**What it is + real-world grounding:**

Reusable shaded envelope rendering on the map: each SAM/weapon's reachable bubble (already partly done — _sam_ring shows the selected S-300 round's range; range rings exist), PLUS the enemy SM-2 horizon/leak band that teaches the go-low gamble, and a pre-launch leak-preview for the planned Oniks shot. feature_ideas.md: 'Engagement-envelope shading (estimated bubbles)' + 'Pre-launch trajectory & leak preview' (new-ui). GAME_ANALYSIS.md §2/§4 is built on the lo-lo-leaks-under-the-horizon physics — making that horizon visible is the single biggest teaching win. Real-world grounding: SAM WEZ (weapon engagement zone) rings + a radar horizon footprint vs a sea-skimmer.

**Platform (launched from / carried by):**

Player: S-300 (48N6/40N6) + Pantsir + Oniks/Zircon envelopes. Enemy: each destroyer/carrier SM-2/SM-6 WEZ + radar horizon vs the player's chosen profile altitude — shown as ESTIMATED bubbles around contacts.

**Sensors (uses / detected by):**

Enemy envelopes are drawn around CONTACT estimates (fog-honest: the bubble sits at the dead-reckoned track position, fades with track age, and is labeled 'EST' — it's the player's best guess of a ship's reach, not truth). The leak-preview computes, for the planned profile (hi-lo vs lo-lo) and the estimated ship positions, where along the run-in the Oniks crosses each ship's detection horizon — surfacing the multipath/horizon physics the duel already simulates.

**AI brain (how the enemy commander uses or counters it):**

N/A (player planning aid). It visualizes the consequence of the enemy fire-control envelope (enemy_defense.py SM-2 horizon/track-form) so the player can plan to leak under it — the counter the whole game is balanced around. It reads no enemy truth.

**Player UX:**

Map: toggle envelope shading; player rings in green/amber (own), enemy WEZ bubbles in faded DANGER around contacts (EST tag). With a launch planned, a leak-preview colors the planned route GREEN where it's below the nearest ship's detection horizon and RED where it pops into view, with a 'LEAK 70%' estimate label — the pre-launch payoff. Reuses the seeker cone + plan chain already drawn.

**UI needs:**

Shaded rings (the existing ring draw + a fill via concentric thin strokes since flat fills are cheap), per-contact WEZ bubbles, a colored route segmenting (recolor the existing PLAN_COL polyline per-segment), a leak-% label. Pure `envelope_rings(world, platform, selected_round)` and `leak_preview(route, profile, contacts)->list[(segment, leaks)]`.

**Game-model mapping (reuse vs add):**

Reuse _sam_ring/_rings/_seeker_cone + the weapon defs (WeaponDef.max_range, SamDef ranges) + the radar horizon math (sim/radar.py) + contacts for enemy bubble centers. Reuse the profile altitudes already in world.launch. No new sim — the horizon/range numbers all exist.

**Implementation sketch + test contracts:**

Files: game/tactical_map.py (generalize _sam_ring into envelope_rings covering all player weapons + enemy WEZ bubbles around contacts; recolor _plan_chain per-segment using leak_preview). game/keybinds.py (optional 'envelopes' toggle, ENGAGEMENT). Pure helpers in tactical_map (already the home of pure view helpers). TEST CONTRACTS (tests/test_envelopes.py, headless): envelope_rings includes the selected S-300 round's max_range (regression vs current _sam_ring); an enemy WEZ bubble centers on the contact's estimated_pos and fades with age; leak_preview marks a lo-lo route below a ship's horizon as leaking and a hi-lo route as exposed (mirrors the GAME_ANALYSIS physics direction); leak_preview reads contact estimates not truth; determinism.
