# ONIKS — Improvement Roadmap & Research Backlog

*Generated 2026-07-04 from a full-game code audit (9 subsystem agents) + broad web research (8 topic agents) + 6 category synthesizers + a 14-item adversarial feasibility pass against the live code. Every item is de-duped against what already ships and checked for the physics-not-dice contract. Verdicts: **BUILD** = novel + supported, **MODIFY** = reshape the proposal, **ALREADY-EXISTS** = drop, **RISKY** = DNA/rewrite hazard.*

## Headline

> The game's deepest physics are either invisible or inconsequential — the single biggest opportunity is to make hits MATTER (warhead-mass lethality pool replacing hp -= 1) and make the go-low/EW gambles READABLE (horizon rings, forensics telemetry, event-warp), turning a faithful simulation into a legible tactical game.

## Recommended First Milestone (mutually reinforcing)

Make the deep physics both **consequential** (hits matter, no dice left) and **readable** (the go-low/EW gambles become visible), mostly quick/medium wins that unlock the big bets:

- Warhead-mass + terminal-KE lethality with a ship structural pool (sim/damage.py) — this is the keystone: warhead_mass is stored, cited per-round, and tested but has ZERO consequence today (every hit is hp -= 1). Nothing downstream — cripple tiers, damage locality, swarm-saturation rewards, honest weapon choice — can exist until the flat HP wall becomes a physics-driven pool. Build it first because the widest set of later items depend on it.
- Kill the last dice roll: physics-emergent CIWS/Pantsir-gun hit (sim/ciws.py:190, sim/pantsir.py:346) — the two remaining rng.random() < pk blocks are the game's last physics-not-dice violations. Doing this alongside the lethality pool means the ENTIRE kill chain (delivery AND terminal defense) becomes emergent in one milestone, so the SHOT DEBRIEF forensics ledger stops ever showing a coin-flip and every death is attributable to geometry.
- Seeker target priority + re-lock to stop homing onto wrecks (sim/missile.py:528/880) — this is a confirmed live correctness bug (nearest-in-cone forever, reads pos on a GONE hull). It reinforces the lethality pool directly: once a lead round can SINK a hull mid-salvo, the follow-on rounds must re-distribute onto live targets or they waste the new, more-lethal warheads on a corpse. The two together make salvo sequencing meaningful.
- Radar-horizon + reaction-time overlay AND the altitude-dependent threat-ring overlay (game/tactical_map.py) — the horizon/masking physics is the heart of the go-low DNA yet is completely invisible; the player commits to an ingress altitude blind. These two read-only overlays reuse radar_horizon_m and the existing TTI math to make the go-low gamble legible, and they give the (also-in-this-milestone) fog/classification work a visible payoff — a classified shooter's ring shrinks as you descend.
- Forensics BLACK BOX telemetry tab (game/forensics.py:729) — fills a shipped-but-empty tab entirely from data the flight recorder already holds. It closes the loop with the lethality and overlay work: after a battle the player reads the exact altitude-vs-range-vs-Mach trace that made a heavier warhead land on the waterline or overfly, learning the descent timing the horizon overlay let them plan. Together these five make the deep physics both CONSEQUENTIAL (pool + emergent guns) and READABLE (overlays + black box) in a single mutually-reinforcing pass — mostly quick/medium wins that unlock the big bets.

## Top Cross-Category Recommendations (ranked)

### 1. Warhead-mass + terminal-KE lethality with a ship structural pool
`model · core · effort M` — **BUILD** (exists=False, model_ok=True, phys_ok=True)

An 8 kg swarm now needs saturation to sink a destroyer while a 300 kg Zircon at Mach 4.5 one-shots it — weapon choice and per-hull spend finally become real decisions.

- **Hook:** `sim/damage.py apply_missile_hits (the ship.hp -= 1 at line 102) drawing damage POINTS = f(warhead_mass, 0.5*m*v^2) against a per-ship pool; sim/arsenal.py WeaponDef.warhead_mass (stored/tested but dead outside test_arsenal); sim/ships.py SHIP_TYPES hp -> structural pool + ST ladder`
- **Verification:** Not implemented: sim/damage.py:102 does a flat integer `ship.hp -= 1` per OBB crossing, so an 8 kg swarm round and a 300 kg Zircon deal identical damage today. `warhead_mass` is stored on every WeaponDef/StrikeDef (arsenal.py) but is dead in the sim — only tests/test_arsenal.py:5 reads it as a mass-budget assert (confirmed by grep). Data model fully supports it with no rewrite: the hit-site missile already carries self.weapon (reaching warhead_mass), self.vel (impact speed), and a `mass` property (missile.py:411-413, sam.py:267-269), so damage POINTS = f(warhead_mass, 0.5*m*v^2) against a per-ship pool is computable in place, and ships.py:18-27 SHIP_TYPES `hp` becomes the structural pool. It is honestly emergent (deterministic KE from measured kinematics + a fixed pool, no probability roll — swarm saturation vs one-shot Zircon falls out of arithmetic). MODIFY-not-blocker caveat: apply_missile_hits also processes enemy interceptor/strike rounds and the tests feed a _FakeMissile (test_damage.py:60) with no .weapon/.vel, so the formula must getattr-guard warhead_mass/vel and keep an integer/legacy fallback or the existing damage + swarm tests crash.

### 2. Kill the last dice roll: physics-emergent CIWS/Pantsir-gun hit
`model · core · effort M` — **BUILD** (exists=False, model_ok=True, phys_ok=True)

A fast crosser or hard-weaving sea-skimmer survives the inner ring because the gun cannot lead it, not because a coin came up tails — closes the final physics-not-dice violation.

- **Hook:** `sim/ciws.py:190 (self._rng.random() < pk) and sim/pantsir.py:346 same block; replace with range-scaled dispersion cone + lead-angle error vs target.velocity() already available in _RelTarget`
- **Verification:** Codebase hooks verified exact: sim/ciws.py:190 and sim/pantsir.py:346 are both literal `self._rng.random() < pk` flat per-burst kill coins feeding a linear `_kill_prob` range ramp — the last such rolls in the combat-outcome path (the SAM layer in sim/sam.py already models misses via per-axis Ornstein-Uhlenbeck multipath/stealth tracking noise into PN guidance, lines 114-148/313-331; strike.py `uniform` is CEP dispersion not a hit/miss coin; recon.py is sensor error). Data model supports it with no rewrite: `engage()` already has slant range, closing rate, and `target.velocity()` (ciws.py:130; _RelTarget.velocity()→missile.vel at pantsir.py:380), so a range-scaled dispersion cone + lead-angle error is computable from data already flowing — no WeaponDef/track-store change. This is exactly the DNA-blessed pattern in memory physics-not-dice.md ("model the physical cause of misses, then MEASURE with seeded probe batches and lock in two-sided statistical regression tests"). Two honest caveats keeping it BUILD not slam-dunk: (a) NOT novel-from-scratch — ciws.py:156-159 already hard-gates receding/pure-cross-course targets to no-fire with an inline "gun cannot lead far enough" comment, so this reshapes a binary gate + flat Pk into one continuous lead/dispersion physics; (b) real blast radius — the M effort is honest because test_sm2_ciws.py has seeded deterministic-outcome tests (test_ciws_kills_slow_close_target_within_few_bursts expects a first-burst kill at Pk=0.50, plus test_ciws_determinism) and test_pantsir*.py / test_sm2_statistics.py all assume the flat-Pk model; per the DNA note those regression contracts must be REPLACED with new measured statistical bands, never merely deleted/weakened.

### 3. G-limited rudder weave inside the integrated physics
`missile · core · effort M` — **MODIFY** (exists=False, model_ok=True, phys_ok=True)

'Does my weave beat their interceptor' becomes an emergent kinematic duel bounded by airframe max_g, not a cosmetic wiggle that currently exceeds the g-limit ~5x outside the integrator.

- **Hook:** `sim/missile.py _apply_weave (line 874, mutates pos/vel post-integration at line 841) + WEAVE_* constants (211-217); route as commanded lateral accel through the gmax = max_g*GRAVITY clamp in _guidance`
- **Verification:** Proposal is factually correct: sim/missile.py `_apply_weave` (874-903) mutates pos/vel AFTER the semi-implicit Euler step (called at 841, integration at 804-824), bypassing the `gmax = w.max_g*GRAVITY` clamp in `_guidance` (642-646); the constants docstring (209-210) itself admits the 200m/4s weave is "~5x that limit; cinematic spec" and that "the g-limited guidance never fights it" — so the current jink is a hard-coded kinematic displacement, the one place lateral motion escapes the airframe g-limit (a real DNA violation, though a fixed-displacement one, not a dice roll). It CAN be made emergent: inject a sinusoidal cross-track accel bias into gx/gz before line 642 so the existing gmax clamp bounds it — max_g already exists per-weapon (arsenal.py:32; Oniks 11.0, Zircon 14.0), no new fields needed. Verdict is MODIFY not clean BUILD because two locked regression contracts pin the current 5x behavior — test_retarget.py `test_terminal_weave_excursion_then_clean_finish` (273, asserts 150-250m cross-track) and tests/test_swarm.py determinism tests — so the clamp-bounded amplitude will shrink for slower/heavier airframes and those contracts must be reshaped (not weakened), which the proposal must own.

### 4. Seeker target priority + re-lock (stop homing onto wrecks)
`sensor · quick-win · effort M` — **MODIFY** (exists=False, model_ok=True, phys_ok=True)

Screening ships and cargo decoys become a real defensive tactic, and a salvo whose lead round sinks the target re-distributes onto live hulls instead of flying PN onto a corpse.

- **Hook:** `sim/missile.py _acquire_lock (line 528, nearest-in-cone with 'once locked, stays locked' at 550) + terminal branch reading locked_ship.pos at line 880 with no GONE/liveness check — a live correctness bug`
- **Verification:** The liveness bug is CONFIRMED: sim/missile.py _acquire_lock filters on ship.alive at acquisition (line 536) but line 550 is explicitly "once locked, stays locked" with no re-check; the terminal branch (595-611) and _apply_weave (line 880) then read locked_ship.pos/vel unconditionally, so follow-on rounds fly PN onto a SINKING/GONE hull that still returns a valid .pos (ships.py ladder ALIVE->BURNING->SINKING->GONE, update() lines 131-140). Data model already supports the fix cheaply — Ship.alive (ships.py 90-93) is the exact liveness signal and world.ships is already scanned, so re-lock is a ~3-line guard reusing the existing _acquire_lock. Both halves are physics-honest (pure geometry/kinematics; priority is a deterministic value tie-break on the cone/range gate, no dice). MODIFY, not a single quick-win, because it bundles a confirmed BUG FIX (re-lock — ship now) with a genuinely NEW FEATURE (value-based target priority does NOT exist today; _acquire_lock is pure nearest-in-cone, and decoys.py is unrelated enemy-HARM ESM bait) that needs a target-value field on Ship plus multi-hull convoy scenarios (world/generation.py has cargo lanes but no screening geometry) to make "screening ships and cargo decoys a real tactic" actually bite. Split: bugfix ships immediately; priority is its own scoped item.

### 5. Altitude-dependent threat-ring overlay (the go-low gamble made legible, fog-gated)
`ui · core · effort M` — **MODIFY** (exists=False, model_ok=True, phys_ok=True)

Pick ingress altitude and bearing by watching each classified shooter's shot window shrink as you go low — the core go-low-to-survive tradeoff becomes a readable plan instead of a blind stat choice.

- **Hook:** `game/tactical_map.py new overlay; reuse sim/radar.radar_horizon_m + per-emitter antenna_alt + size-class ranges; gate on sim/contacts.classify stage so unclassified shooters show a dashed uncertainty band`
- **Verification:** NOVEL: game/tactical_map.py _sam_ring (L923) draws only the player's OWN outbound SAM envelope + a dashed LOW-TGT honesty ring; there is no enemy-shooter threat ring, and radar_horizon_m is never imported into game/. PHYSICS IS REAL AND HONEST: sim/radar.py exposes radar_horizon_m (L36) + Radar.antenna_alt (L85), and sim/enemy_ships.py L53-55 literally documents the payoff — a 20 m SPY-1 mast (_SPY1_RANGES, 300 km nominal) sees a 15 m sea-skimmer only to ~30-40 km, so the detection ring genuinely shrinks with ingress altitude, no dice. TWO REQUIRED MODIFICATIONS: (1) Scope honesty — the ring must be the horizon-DETECTION envelope, not a hard 'can't-shoot' boundary; the SM-2's real low-alt weakness inside range is the multipath OU noise (sim/sam.py MULTIPATH_ALT_M=150, L114-153) that degrades terminal accuracy statistically, not a shrunk launch gate, so a ring implying a kill-free zone would oversell. (2) Fog constraint on 'each classified shooter' — enemy Destroyers set no weapon_id/radar_size, so sim/contacts.classify never resolves a hull past 'SURF' (L88); the picture cannot legibly attribute a specific SM-2/SM-6/SPY-1 envelope to a contact without a new ship-type classification stamp, else the overlay would have to read truth (a fog violation). Reshape to: dashed uncertainty band on unclassified/SURF contacts using a generic warship SPY-1 horizon model, tightening only when/if a type-classification hook lands.

### 6. Radar-horizon + detection-to-impact reaction-time overlay on the tactical map
`maps · quick-win · effort S` — **MODIFY** (exists=False, model_ok=True, phys_ok=True)

On any launch, see the predicted detection point and detection-to-impact seconds derived from mast height and skim altitude — plan the approach that minimizes the enemy's warning time.

- **Hook:** `game/tactical_map.py overlay layer reading sim/radar.radar_horizon_m + terrain_blocks + world.surface_height_at; reuse the existing INBOUND TTI math — the sim already computes every input`
- **Verification:** Novel and mechanically well-supported: sim/radar.py:36 radar_horizon_m() and :42 terrain_blocks() are pure/GL-free, terrain_height_scalar and WeaponDef.skim_alt/cruise_alt (sim/arsenal.py) exist, and enemy radar mast/ranges are static config (world/combat.py:481 _ENEMY_RADAR_ANTENNA_M, :482 _ENEMY_RADAR_RANGES) held on self.enemy_radars — so marching a planned route vs each radar's horizon/LOS to find first-detection, then dividing remaining path by weapon speed, is a straight physics reuse (no dice). Nothing like it exists today (the existing TTI math, threat_rows in game/hud.py:455, is the REVERSE geometry — enemy inbounds vs the player base, and reads only the gated contact picture). MODIFY not BUILD because enemy radars are fog-of-war gated (world/combat.py:1287: a radar marker surfaces only once a player sensor IMAGES it, via known_enemy_sites/_enemy_radar_known); drawing horizon/detection rings for every enemy radar as the one-liner says ("on any launch") leaks the enemy's exact sensor truth and violates the no-cheat DNA the codebase enforces everywhere. Scope it to DISCOVERED radars only, and treat AWACS (mobile, sim/enemy_air.py) as stale-per-frame not a static ring.

### 7. Forensics BLACK BOX telemetry tab
`features · core · effort M` — **MODIFY** (exists=True, model_ok=True, phys_ok=True)

Post-battle, read the exact go-low altitude-vs-range trace that made a shot hit or overfly — the shipped ledger becomes a real teaching tool for descent timing with zero new sim state.

- **Hook:** `game/forensics.py _right_column tab==1 branch (line 729, 'deliberately undesigned') + cumulative_ground_km (line 169) + game/flight_recorder.py samples/path_of — all data already recorded under the 1:1 accuracy contract`
- **Verification:** The proposal's stated payload — the go-low altitude-vs-range trace for descent-timing teaching — ALREADY ships as the always-visible LEDGER hero plot: game/forensics.py _side_plot (lines 506-609) draws path[:,2] altitude vs cumulative_ground_km(path) range 1:1 from the recorder, with CRUISE/DESCENT/TERMINAL phase pins, death anchor, and a dashed planned-remainder + 'N KM SHORT' annotation for overflies. A BLACK BOX tab (tab==1, currently the 'AWAITING DESIGN' placeholder at lines 747-759) showing the same alt-vs-range would duplicate it. MODIFY, not BUILD: reshape the tab to add non-redundant telemetry the side plot lacks — altitude / speed / fuel / climb-rate strips vs TIME (the recorder stores t in path[:,0] and could stamp speed/fuel like it stamps events, per flight_recorder.py). Data model fully supports it (all read from FlightRecorder samples, zero new sim state) and it stays physics-honest (pure kinematics readout, no probability shortcut). If reshaping to alt-vs-range specifically, it is ALREADY-EXISTS — drop it.

### 8. Event-jump auto-warp + latched cause label
`qol · core · effort M` — **MODIFY** (exists=True, model_ok=True, phys_ok=True)

Fast-forward dead transit and auto-slow the instant an armed event fires (new contact, launch detected, own round terminal) so the ~25-60s sea-skimmer reaction window is never missed at warp — plus fixes the shipped cause-tag flicker.

- **Hook:** `game/timewarp.py TimeWarpDirector (DWELL_S debounce, drop_cause at line 210) + game/hud.py _scale_text (line 1353); arm-list from a settings field; camera snap via game/sandbox.py cycle_camera_subject`
- **Verification:** The "auto-slow the instant an armed event fires + DWELL debounce + ramp-back" half is ALREADY SHIPPED end-to-end: game/timewarp.py TimeWarpDirector (DWELL_S, event_drop, drop_cause) is fed each frame by SandboxControls.update->warp_director.tick (game/controls.py:287-289), OR'd by sandbox.warp_drop_active() and surfaced via effective_time_scale() (game/sandbox.py:1104-1135) covering INBOUND/TERMINAL/INTERCEPT. Drop that portion. The cause-tag flicker is REAL and worth fixing: game/hud.py:1361 recomputes drop_cause(world) fresh every frame independent of the director, so during the DWELL hold (director.dropped==True but predicates already False) the "(auto: INBOUND)" tag desyncs from the still-1x warp — the director already exposes .dropped and could latch the cause, but the HUD ignores it. The two novel pieces are small/soft: (a) auto warp-UP / "fast-forward dead transit" does NOT exist (the director only eases toward the player's requested target, never above it) and is a modest QoL delta since the ladder already reaches 64x during transit — physics-honest ONLY if kept as a pure real->sim multiplier (a sim-time jump would violate the file's own determinism contract), and (b) camera auto-snap on event is unbuilt but trivial (cycle_camera_subject exists at sandbox.py:771, manual [ / ]). The proposed "arm-list from a settings field" is not in world/combat_config.py or anywhere — the arm-set is hardcoded in event_drop. Reshape to: fix the latched-cause flicker (core) + optional auto-warp-up-on-idle as a multiplier only; drop the already-shipped auto-slow.

### 9. Beachhead / defeat-cause honesty pass
`qol · quick-win · effort S` — **BUILD** (exists=False, model_ok=True, phys_ok=True)

A live landing-clock banner + LANDING_BOX ring lets the player divert fire before the 180s runs out, and the end screen finally reads the true cause instead of a hardcoded bastion string on every defeat.

- **Hook:** `world/combat.py beachhead_active/beachhead_left/defeat_cause (all exist, no HUD consumer) -> game/hud.py new banner + game/tactical_map.py _asw_overlay ring + game/combat_end.py subtitle map`
- **Verification:** Verified: world/combat.py exposes beachhead_active (L1647), beachhead_left (L1653) and defeat_cause (L2777) as properties whose own docstrings mark them 'DEFERRED' HUD wiring — none is consumed anywhere. game/hud.py has ZERO beachhead/landing references but already carries a _banner() helper (L1376) and a live world.defeated/victorious draw path (L1010-1013), so the landing-clock banner drops into an established pattern. game/tactical_map.py _asw_overlay (L1228) already renders fog-honest map geometry via world_to_screen/_poly_world, and sim/amphibious.py supplies landing_box_xz + LANDING_BOX_RADIUS_M for the ring. game/combat_end.py:304 genuinely hardcodes 'ALL BASTION TELs DESTROYED' for every defeat because CombatEndOverlay.__init__ (L152) takes only victory:bool and _open_end_overlay(victory=False) never reads defeat_cause — so a beachhead loss currently displays a false cause. Fully physics-honest: the beachhead defeat is a geometric latch (LCAC pos entering LANDING_BOX_RADIUS_M, amphibious.py:361) plus a countdown clock in _step_amphibious — the proposed work only DISPLAYS that emergent state, no probability shortcut. Scope is genuinely S. One caveat, not a blocker: defeat_cause must be threaded through _open_end_overlay -> CombatEndOverlay as a new arg (small signature change), and any existing combat_end tests asserting the old subtitle string will need updating.

### 10. SNR-coupled classification ladder (dwell scales with signal, not the wall clock)
`sensor · core · effort M` — **MODIFY** (exists=False, model_ok=True, phys_ok=True)

Closing to identify or killing the jammer buys the TYPE label sooner while a distant/jammed contact stays UNK long enough to matter for weapons-release timing — ID becomes an investment, not a stopwatch.

- **Hook:** `sim/contacts.py classify() (line 64; dwell = sim_time - first_seen at line 84 with admitted zero signal coupling) scaled by an SNR proxy from range vs Radar.ranges[size] + sim/ew.noise_floor_at the _seen gate already computes`
- **Verification:** The ladder itself already ships (sim/contacts.py classify() line 64, UNKNOWN/CLASSIFIED/IDENTIFIED gated by per-signature CLASSIFY_DWELL) but dwell is a pure wall-clock stopwatch — sim_time - first_seen (line 84) with the proposal's own admitted zero signal coupling; range/SNR/jammer state never enter classify(). The SNR-coupled delta is genuinely novel and well-supported: Radar.ranges[size] and the deterministic, measured-calibration ew.noise_floor_at(receiver_pos, jammers) (sim/ew.py:180) both exist, the EW burn-through gate is already threaded into the visible_fn (world/combat.py _player_visible line 1423 -> radar_net.visible(jammers=) -> ew.effective_range) but collapses to a bool before contacts.py sees it, and physics stays honest (1/R geometry + kinematics, no dice). MODIFY not BUILD: accumulate an SNR-scaled dwell RATE inside ContactBoard.update (where the radar+jammers are reachable) integrating so the spec's monotonic 'a coasting track keeps what it earned' contract (contacts.py lines 35-37) survives — do NOT rewrite classify()'s read-time (track, sim_time) signature (it's called geometry-blind from game/hud.py:532,1453), and keep the two-sided regression tests in tests/test_classification.py plus a probe-locked band for the SNR scaling rather than a guessed exponent.

### 11. Home-on-jam / bearing-riding seeker mode (anti-jammer round)
`missiles · core · effort M` — **ALREADY-EXISTS** (exists=True, model_ok=True, phys_ok=True)

An enemy Growler that collapses your net becomes a target you shoot on its own noise — jamming turns into a gamble, directly rewarding the EMCON/SEAD half of the game.

- **Hook:** `sim/ew.py:6 names home-on-jam as an intended-but-unbuilt consumer; world/combat._believed_jammer_fix + emitter_contacts (kind=='JAMMER') publish the bearing; reuse sim/strike.py PlayerArmMissile emitter-homing path as a new sim/missile.py guidance mode`
- **Verification:** The full anti-jammer kill chain already ships. sim/enemy_air.py JammerAircraft (EA-18G Growler) carries a Radar beacon with emitting=True + jam_power_w; world/combat.py:1905 labels it kind=="JAMMER" in _player_targetable_emitters and _inject_emitter_contacts/_believed_jammer_fix (combat.py:1918,1957) publish its fog-gated ELINT fix AND raw bearing. world/combat.py launch_arm (line 3643) accepts ANY localized emitter_id — including a JAMMER — and spawns a PlayerArmMissile (sim/strike.py:762) that PN-homes on the live emitting beacon and draws the seeded 150-400 m silence-CEP ring if it stops radiating (HarmMissile._update_aim/_guidance). That IS home-on-jam: a jammer radiates continuously, so the existing passive-ARM path homes on its noise. The proposal's own codebase_hook ("reuse PlayerArmMissile emitter-homing path") describes the shipped feature; building it as a NEW sim/missile.py guidance mode would duplicate sim/strike.py. Physics-honest already (PN on a real emitter, deterministic CEP, no dice) — tests/test_kh31p_arm.py + test_arm_emcon.py cover it. Only genuinely-missing sliver: a HUD affordance letting the player click a JAMMER-kind contact to fire (kh31p_ammo defaults to 0), plus a bearing-only "shoot down the wedge before a fix exists" launch variant — launch_arm currently requires a LOCALIZED fix, so pure bearing-riding is the one un-built nuance. Recommend dropping the item or re-scoping it to that thin UI+bearing-launch delta rather than a new seeker mode.

### 12. Threat-reactive fleet maneuver (clear-datum turn under fire)
`enemies · core · effort L` — **BUILD** (exists=False, model_ok=True, phys_ok=True)

A capital group stops being a stationary sponge — it reads a sensed ASCM inbound and opens range down the reciprocal bearing, so you must lead a maneuvering target and time the salvo before the turn completes.

- **Hook:** `sim/enemy_ships.py Destroyer._build_racetrack/_advance_racetrack + a new _doctrine_surface in sim/commander.py reading self.picture.live_missile_tracks (line 619, already exists); 'ship_maneuver' order routed in world/combat.py _execute_commander_order`
- **Verification:** Novel and fully supported. No ship-maneuver code exists anywhere (grep for ship_maneuver/clear_datum/open_range/_doctrine_surface/evade = zero hits); Destroyer.update() (sim/enemy_ships.py:210-273) only runs the fixed _advance_racetrack loiter, so ships really are stationary sponges — the only reactive behavior today is radar EMCON (commander.py:935), never movement. The cited hook is real: EnemyPicture.live_missile_tracks() at commander.py:619 already carries fog-honest sensed tracks, and combat.py:2355-2406 already feeds player Oniks (Missile) into it, physically gated on the ship's own SPY-1 detects() (in _enemy_sensor_radars, combat.py:2264) and stamped kind="oniks" — so the sensed-ASCM picture to react to exists. The order dispatch (_execute_commander_order keyed on order['type'], combat.py:2467) and the _defend_* doctrine pattern are directly extensible; _defend_awacs -> awacs.flee(threat_pos) (commander.py:899) is a working template for a bearing-away turn. Build it as pure kinematics: read the sensed track pos/vel, steer self.heading down the reciprocal under the existing TURN_RATE rudder limit at self.speed — no dice, and 'leading a maneuver' emerges because the Oniks guidance is already a physics pursuit. One DNA guard to enforce in review: the trigger must read ONLY live_missile_tracks (mirror _sensed_arm_within, commander.py:846), never the missile's truth pos. New CombatConfig knobs (trigger range, resume-to-racetrack) are additive, no rewrite.

### 13. Named QUICK-BATTLE presets + setup validation/PAR footer
`modes · quick-win · effort S` — **BUILD** (exists=False, model_ok=True, phys_ok=True)

One stepper fills a curated fight (Saturation Raid, Silent Hunt, Beachhead Denial) and a live footer warns when a threat axis lacks its counter (subs>0, sonobuoys=0) before you commit — instant replay variety and fair-fight feedback.

- **Hook:** `game/combat_setup.py PRESETS dict applied into self._fields (line 296) + render footer (line 506) calling game.scoring.compute_par(build_config()); reuse campaign._escalated_counts fairness rule; all clamped via world.combat_config.clamp_config`
- **Verification:** Novel and supported. No named-fight preset system exists — the only "preset" is map_preset (terrain morphology, world/generation.py + combat_config.py:281), not a curated force mix; there is no PRESETS dict, no live compute_par call, and no validation footer in game/combat_setup.py (the hook's line-296/506 citations are just the _fields comprehension and the header of render(), not preset/PAR code). Data model fully supports it: CombatConfig is a flat frozen dataclass and clamp_config(**kwargs) (combat_config.py:294) is the single clamped sink already used by build_config() (combat_setup.py:502), so a preset is a partial dict merged into self._fields then clamped — zero schema change; the cited fairness rule is real (campaign._escalated_counts subs>0 -> sonobuoys/asw block, campaign.py:142-144). Physics-honest: presets set only integer force counts and the footer is a count comparison, not a probability roll. Two MODIFY caveats before roadmapping: (1) compute_par (scoring.py:139) grades OFFENSIVE difficulty via _enemy_asset_count only and is blind to the player's counter-coverage, so displaying it as a "fair-fight" PAR conflates two signals — the axis-vs-counter validation footer is the real value; the PAR number is cosmetic reuse and may mislead. (2) compute_par currently runs only at battle-end AAR; calling it every render frame in setup is cheap (fresh seeded RNG, no sim touch) but should be memoized on (seed, config) to avoid re-seeding a Generator per frame.

### 14. Finish the attrition ledger: persist base/structure damage across campaign battles
`modes · big-bet · effort L` — **BUILD** (exists=False, model_ok=True, phys_ok=True)

A battered radar starts the next battle degraded and a destroyed bastion ends the campaign — the campaign's finite-magazine risk/reward loop finally has teeth on the structures axis, not just ammo.

- **Hook:** `game/campaign.py world_snapshot()/initial_state_for() (both ship base_damage:{} empty, deferral noted at 177-183); world/combat.py apply_initial_state must replay each carried-dead structure's on_destroyed kill closure to avoid the sensor/Pantsir desync the docstring warns about`
- **Verification:** Genuine gap, not implemented: game/campaign.py:167-198 (world_snapshot/initial_state_for) both hard-code base_damage:{} with the deferral documented at 171-183, and world/combat.py:1106-1129 apply_initial_state only ingests the 6 ammo attrs and deliberately ignores structure-hp keys. The plumbing skeleton exists (CampaignState.base_damage field line 79, JSON round-trip lines 251/267, advance() captures snap["base_damage"] line 228) but nothing populates or replays it. Data model fully supports it: Structure (sim/bases.py:70-117) has hp/alive/hit()->on_destroyed, and structure_ids are index-based/seed-independent (bastion_tel_NN, radar_station_00) so a {structure_id: hp} map keys deterministically across battles. Physics-honest: damage is residual hp/alive from simulated impacts (apply_missile_hits_structures / Structure.hit), zero dice. The one real hazard is correctly named in the hook — apply_initial_state must replay each carried-dead structure's on_destroyed kill closure (combat.py:743 clears radar_station.alive, 786-853 clear Pantsir/Buk/decoy/reflector .alive) or the sensor/Pantsir net desyncs, and a destroyed bastion must route through the existing defeated/_bastion_all_dead path (combat.py:230,2758) to end the campaign rather than pre-defeat the next battle. Scope/effort (L, big-bet) is honest.

### 15. Enemy fleet softkill: chaff + Nulka-style off-board decoy
`enemies · big-bet · effort L`

A seduced Oniks misses because its seeker guided on a real moving false return, so the player must classify the enemy softkill fit via ELINT and choose whether to commit active-seeker rounds into a decoy-rich picture.

- **Hook:** `sim/decoys.py DecoyEmitter pattern applied in reverse against Missile terminal seeker in sim/missile.py (_acquire_lock / terminal PN); wire a ship-side emitter into sim/enemy_defense.py ShipDefense.step — pairs with and depends on the seeker-priority fix`


---

# Full Category Backlogs

## Player missiles & weapons (missile)

### Warhead-mass + terminal-KE lethality with hull-zone locality
`core · effort M`

Replace the flat `ship.hp -= 1` with damage POINTS = f(warhead_mass, terminal kinetic energy 0.5*m*v^2 at impact, target displacement), drawn against a per-ship structural-integrity pool; then use the OBB slab test's already-computed t_enter to classify WHERE the segment struck (bow/midships/stern, above/below waterline) and apply a zone multiplier. New decision: an 8 kg SWARM now needs saturation to sink a destroyer while a 300 kg Zircon at Mach 4.5 one-shots it, and aiming the sea-skim run onto the waterline/magazine becomes a real tactic instead of hitting a 3-HP sponge. Merges the two warhead-mass audit ideas + damage-locality into one coherent lethality model.

- **Hook:** `sim/damage.py apply_missile_hits (the `ship.hp -= 1` line + segment_hits_obb returning t_enter/local hit point instead of bool), sim/arsenal.py WeaponDef.warhead_mass (currently dead), sim/ships.py SHIP_TYPES hp -> a structural pool + damage state`
- **Physics-honest:** Damage is a deterministic function of measured warhead mass, integrated impact velocity, and geometric strike zone from the swept-OBB t parameter — no probability roll, byte-reproducible per seed.

### Player anti-ship terminal seeker gets physics-not-dice degradation
`big-bet · effort L`

Give the Oniks/Zircon active seeker the same multipath/sea-clutter noise the enemy SM-2 already runs: lift sam.py's OU multipath model into a shared helper, wire an optional rng into Missile (unset = bit-identical), and add a low-ship / decoy false-target wander so a sea-skim terminal HIT EMERGES from a noisy seeker picture instead of reading world.ships truth. New decision: going lower/faster trades interceptor exposure against a noisier own-seeker basket, and enemy softkill/decoys can actually seduce the shot.

- **Hook:** `sim/sam.py _update_multipath / MULTIPATH_* (extract to a shared module), sim/missile.py _acquire_lock + the PH_TERMINAL PN branch of _guidance (add self.rng like SamMissile)`
- **Physics-honest:** Miss distance falls out of the same OU noise process the enemy interceptor uses (range- and altitude-scaled sigma), so hit/miss is emergent seeker error, never a hit%. rng unset keeps every locked test byte-identical.

### Seeker target priority + re-lock (stop homing onto wrecks)
`quick-win · effort M`

Make _acquire_lock SCORE candidates (warship > destroyer > cargo/decoy, reject already-GONE hulls) instead of nearest-in-cone, and drop/reacquire if the locked ship sinks before impact rather than flying PN onto a corpse. Optionally honor a player-designated hull. New decision: screening ships and cargo decoys become a real defensive tactic the player must sequence around, and a salvo whose lead round sinks the target re-distributes onto live hulls.

- **Hook:** `sim/missile.py _acquire_lock (nearest-in-cone, `once locked stays locked`) + the PH_TERMINAL locked_ship branch of _guidance (add staleness/GONE check)`
- **Physics-honest:** Selection is a deterministic score over sensed range/aspect/classification and a liveness check on tpos — pure geometry and target state, no roll.

### G-limited rudder weave inside the integrated physics
`core · effort M`

Replace the current terminal weave — a cross-track sin overlay added to pos/vel OUTSIDE integration that explicitly exceeds max_g — with a lateral-accel oscillation COMMANDED through _guidance and clamped by the g-limiter, so the displayed path IS the physics path. A genuinely tighter-turning interceptor (Pantsir 40g, Buk 50g) then has a real geometric chance to lead the jink. New decision: 'does my weave beat their interceptor' becomes an emergent kinematic duel set by airframe max_g, not a cosmetic wiggle.

- **Hook:** `sim/missile.py _apply_weave + WEAVE_* constants (currently mutates pos/vel post-integration), the g-limit block at the tail of _guidance`
- **Physics-honest:** The jink becomes a commanded lateral acceleration passing through the same gmax = max_g*GRAVITY clamp as all other guidance, so amplitude is bounded by what the airframe can pull — closing a real crack in the physics-not-dice contract.

### Player-selectable terminal profile: sea-skim vs pop-up/high-dive
`core · effort M`

A per-shot terminal-profile toggle (sea-skim / pop-up / high-dive) reusing the existing per-weapon descent fields (descent_range_m, ramp_rate, max_sink, final_pn_range_m) that already drive the Zircon's late dive. Sea-skim = latest detection but flattest, easiest-to-block near the surface; pop-up/high-dive = earlier detection over the horizon but a steep top-down terminal that stresses point-defense elevation and CIWS geometry. New decision: every salvo becomes a go-low-vs-expose gamble against the specific defense you've classified.

- **Hook:** `sim/arsenal.py WeaponDef descent fields (proven plumbing), sim/missile.py PH_DESCENT/PH_TERMINAL profile selection, world.launch profile arg (extends the existing hi-lo/lo-lo path), game/hud bastion_weapon_strip`
- **Physics-honest:** Detection range is computed from altitude via the existing radar-horizon model and terminal geometry from the integrated descent — the profile only sets kinematic targets, outcomes stay emergent.

### Bearing-only launch with a player-set seeker GO-ACTIVE point
`core · effort M`

Let the player fire on a bearing/waypoint and set the range at which the missile's active seeker turns on (flying INS/passive until then). Going active early lights the missile on enemy RWR (invites counter-launch / a RAM passive-RF shot) and may lock the wrong contact in clutter; too late risks no acquisition. New decision: the exact moment your OWN missile starts radiating is an emissions-timing gamble the player owns — EMCON extended onto the offensive round.

- **Hook:** `sim/missile.py _acquire_lock gate (add a seeker_active_range / go-active waypoint) + the terminal PN branch, world/combat.py launch plan, game/tactical_map RMB route plan`
- **Physics-honest:** Acquisition succeeds or fails from the geometry between the go-active point and the target's actual (fogged) position and the seeker cone — no roll; the emission itself is a real detectable event the enemy ESM/RWR consumes.

### Home-on-jam / bearing-riding seeker mode (anti-jammer round)
`core · effort M`

A seeker mode that flies the ELINT/jammer bearing even without a localized fix, sharpening as it closes and burning through to skin-track at short range — reusing the PlayerArmMissile emitter-homing path. Pairs with the flip side: leaving your own fire-control illuminator hot, or jamming, lets enemy ARM/HOJ shots home on YOUR emission. New decision: an enemy Growler/jammer that collapses your net becomes a target you can shoot on its own noise, and your EW becomes a back-plot risk.

- **Hook:** `sim/strike.py PlayerArmMissile / HarmMissile emitter-homing guidance (proven), sim/ew.py bearing feed + world/combat.py _believed_jammer_fix / emitter_contacts JAMMER kind, sim/missile.py new guidance mode`
- **Physics-honest:** The missile follows the emission the sim actually radiates; burnthrough is a computed signal-vs-noise crossover, and a HOJ shot on a silent emitter simply fails — geometry and propagation, not dice.

### LRASM-class passive-ESM/IIR silent penetrator round (pure data)
`big-bet · effort L`

A new subsonic (~Mach 0.9), long-range player round whose seeker is PASSIVE (ESM/IIR) — it never radiates, so enemy RWR/ELINT can't see a seeker emission, but it can only home when the target is EMITTING or thermally distinct; it trades speed for stealth. Add it as a WeaponDef reusing the Missile/HARM machine plus a passive-acquisition gate. New decision: this weapon is strongest exactly when the enemy fleet is radiating and weak against a silent/dark task group — the EMCON dilemma cut both ways.

- **Hook:** `sim/arsenal.py WEAPONS registry (ONIKS/ZIRCON as templates + a passive-seeker flag), sim/missile.py acquisition gate (require target emission/IR signature), world/combat.py launch dispatch, IIR weather coupling optional`
- **Physics-honest:** Homing success emerges from whether the target is emitting/hot at terminal (a modeled signature threshold), not an assigned hit% — a dark target genuinely defeats it.

### ARMORY missile envelope card (derived, not stat-bars)
`quick-win · effort S`

A per-weapon card in the Armory/setup that surfaces DERIVED physics-honest tradeoffs: computed enemy first-shot range at the chosen cruise altitude (radar horizon), terminal Mach, sea-skim altitude, seeker type (active/passive/IIR), emission signature, CIWS exposure-window seconds (= inner-ring range / closing speed), and expected detection range vs the current enemy sensor fit. New decision: the player picks weapons and profiles on tactics and geometry, learning that hit/miss is horizon + emissions + timing, not a probability stat.

- **Hook:** `game/combat_setup.py Armory page render, sim/arsenal.py WeaponDef fields, the radar-horizon + closing-speed helpers already in sim/radar.py / sensor model; reuse compute_par-style pure calls`
- **Physics-honest:** Every number on the card is computed from the same sim physics (horizon geometry, closing-speed windows) rather than authored — it teaches the emergent model instead of hiding it behind a bar.

### Booster-slug mass ejection + hypersonic Cd table extension
`quick-win · effort S`

Two small, additive fidelity fixes for fast rounds. (1) Drop the booster slug from Missile.mass at the BOOST->CLIMB transition (add booster_mass to WeaponDef, default 0 = current) so the ramjet cruise flies at the honest lighter mass instead of carrying phantom kg, matching how SamMissile burns propellant. (2) Extend the Cd-vs-Mach table into the hypersonic band (M3/M5/M8 wave-drag rise) leaving the <=M2.3 Oniks points untouched, so Zircon's whole profile stops flying on a clamped-flat drag tail. New decision: none directly — these correct range/acceleration fidelity that other missile decisions depend on.

- **Hook:** `sim/missile.py mass property + BOOST-end transition, sim/arsenal.py WeaponDef (new booster_mass=0.0), sim/physics.py CD_MACH_POINTS/CD_VALUES + _CD_TABLE scalar mirror`
- **Physics-honest:** Both change the integrated equations of motion (mass in F=ma, drag from a real Cd curve) — more honest physics, not a tuned outcome; Oniks stays byte-identical by leaving its band and default untouched.

### Two-stage sea-skim-then-sprint round + swept terrain/water impact test
`big-bet · effort L`

A YJ-18/Kalibr-3M54-profile weapon: long subsonic sea-skimming cruise below the horizon, then a booster-lit terminal sprint to ~Mach 2.9 triggered at a player-chosen range-to-target. Ship it together with the necessary correctness fix — make the terrain/water impact test a SWEPT segment (like the ship OBB test) so a fast steep diver can't tunnel one 120 Hz step past a coastal cliff. New decision: WHERE to trigger the sprint (early = more warning but more terminal energy; late = collapse the defender's reaction window).

- **Hook:** `sim/arsenal.py WEAPONS (new def + a sprint-trigger field reusing the descent-profile pattern), sim/missile.py phase machine + the surface-impact block (py <= surface -> swept prev_pos->pos surface query), _surface_at`
- **Physics-honest:** The two phases are distinct integrated kinematic legs; the defender's reaction window is set by the sprint-trigger geometry and SAM flyout physics, and the swept surface test removes a tunneling artifact — all deterministic.

## Enemies, defenses & fleet composition

### Warhead-mass + kinetic-energy lethality with a ship structural pool
`core · effort M`

Replace the flat ship.hp -= 1 with a structural-integrity pool that a hit removes damage POINTS from, computed deterministically as f(warhead_mass, terminal kinetic energy 0.5*m*v^2 at impact). A 300 kg Zircon at Mach 4 removes far more integrity than an 8 kg Swarm; sinking a Burke now depends on delivered charge + closing energy, not a hit count. New decision: which weapon (and how many) to spend per hull class, and whether a fast-but-light Zircon or a heavier-but-slower Oniks is the better sinker for a given escort.

- **Hook:** `sim/damage.py apply_missile_hits (the ship.hp -= 1 line), sim/arsenal.py WeaponDef.warhead_mass (line 33, currently dead outside one test), sim/ships.py SHIP_TYPES hp field -> a structural pool + the ST_BURNING/ST_SINKING ladder`
- **Physics-honest:** Damage = measured warhead mass x delivered kinetic energy at the swept-OBB impact; no probability roll, fully reproducible per seed.

### Kill the last dice roll: physics-emergent CIWS/Pantsir-gun hit
`core · effort M`

Replace Ciws._kill_prob's rng.random()<pk block (and the Pantsir 30mm gun) with a geometry test: a range-scaled dispersion cone plus a lead-angle error against the target's velocity, killing only when the swept fragment stream actually intersects the crossing/closing target with enough dwell. A fast crosser or a hard-weaving sea-skimmer survives because the gun cannot lead it, not because a coin came up tails. New decision: terminal weave amplitude and crossing geometry now genuinely matter against the inner ring.

- **Hook:** `sim/ciws.py Ciws.engage / _kill_prob (the self._rng.random() < pk block, lines 186-192) and the Pantsir 30mm gun channel; reuse the target.velocity() lead already available in _RelTarget`
- **Physics-honest:** Kill emerges from dispersion-cone vs lead-angle vs dwell geometry — the one remaining flat-Pk violation in the whole subsystem, brought in line with the SAM layer's OU-noise philosophy.

### Finite illuminator / fire-control channels as the saturation break
`core · effort M`

Replace the arbitrary SM2_MAX_INFLIGHT=4 / PANTSIR cap with a modeled count of SARH illuminator channels per ship (and per Pantsir). A semi-active SM-2 stays guided only while a channel paints it; exceed the channel count and the newest round breaks lock via the EXISTING _los_masked / null-illuminator path and goes stupid. Active SM-6 rounds don't consume a channel after launch. New decision: a tightly time-synchronized salvo of >N rounds arriving together forces the ship to leave some unengaged — the classic illuminator-saturation break the player earns by timing, not luck.

- **Hook:** `sim/enemy_defense.py ShipDefense._try_sm2_launch (max_inflight gate) + _illuminator() closure; make illuminator_pos_fn return None when all N channels are occupied so the excess round breaks lock via sim/sam.py's shipped lock-break contract`
- **Physics-honest:** A leaker emerges because the defender ran out of physical illuminator channels and the un-painted round loses its SARH lock — reuses shipped lock-break physics, no new gate or roll.

### Threat-reactive fleet maneuver (clear-datum turn under fire)
`core · effort L`

Add an EnemyCommander._doctrine_surface that, when the sensor picture holds an inbound missile track bearing on a ship, shifts that ship's racetrack anchor to open range down the reciprocal bearing — a slow doctrinal 'clear datum' turn, rate-limited by the existing TURN_RATE. Also let a hard beam-aspect turn exploit the SAM guide chain's Doppler notch. New decision: a static capital group stops being a stationary sponge; the player must lead a maneuvering, range-opening target and time the salvo before the turn completes.

- **Hook:** `sim/enemy_ships.py Destroyer._build_racetrack/_advance_racetrack + a new _doctrine_surface in sim/commander.py reading self.picture.live_missile_tracks (line 619); new 'ship_maneuver' order routed in world/combat.py _execute_commander_order`
- **Physics-honest:** The turn is chosen from the SENSED inbound track geometry (no-cheat picture), and the resulting miss/hit emerges from the changed intercept geometry vs the missile's PN — never a dodge roll.

### Enemy fleet softkill: chaff + Nulka-style off-board decoy
`big-bet · effort L`

Give the enemy fleet expendable countermeasures that mirror the player's DecoyEmitter/CornerReflector honesty pattern in reverse: chaff blooms a stationary elevated false RF centroid (defeatable by a seeker altitude-gate), and a Nulka-class hovering repeater radiates a MOVING, sea-level, ship-like return that a naive seeker walks onto. A seduced Oniks misses because its terminal seeker guided on a real false return. New decision: the player must classify the enemy seeker-counter fit via ELINT and choose whether to commit active-seeker rounds into a decoy-rich picture or hold for a cleaner geometry.

- **Hook:** `sim/decoys.py DecoyEmitter pattern applied against Missile terminal seeker in sim/missile.py (_acquire_lock / terminal PN); wire a ship-side emitter into sim/enemy_defense.py ShipDefense.step`
- **Physics-honest:** The Oniks seeker guides on the strongest/most-ship-like return in its gate; a seduction is the decoy physically winning the centroid, never a flag that says 'missile misses'.

### Seeker target priority, re-lock, and false-target discrimination
`core · effort M`

Make the player's Oniks/Zircon terminal seeker score candidates (warship/flagship > general destroyer > cargo decoy, reject GONE hulls), drop-and-reacquire if the locked ship sinks before impact instead of homing onto a wreck, and — with an IIR/ATR-class seeker — risk locking the WRONG hull when mid-course cueing is stale or the track picture is ambiguous. New decision: screening ships, neutral traffic, and decoys become a real terminal problem; a bad sensor picture can waste a missile, and target designation becomes worth the ELINT investment.

- **Hook:** `sim/missile.py _acquire_lock and the PH_TERMINAL branch of _guidance (locked_ship staleness / priority scoring); read the ContactBoard track quality already computed in sim/contacts.py`
- **Physics-honest:** The wrong-target lock emerges from the measured track-quality/ambiguity of the fed picture and the seeker's nearest-in-cone geometry — no random miss; a clean, well-cued track always locks the intended hull.

### Coordinated saturation wave with computed time-on-target
`big-bet · effort L`

Let _doctrine_blind/_doctrine_kill buffer HARM+JASSM+Tomahawk (and sub-launched Kalibr) launch intents and release them with a per-weapon time-on-target derived from each weapon's range/speed, so terminal arrivals deliberately overlap and exceed the player's measured concurrent-channel cap. Add wolfpack sub sync so multiple boats' Kalibr transients land in one window. New decision: the player's layered SAM defense faces a genuine multi-axis saturation pulse and must decide what to let leak, not a trickle of uncoordinated shots.

- **Hook:** `sim/commander.py _doctrine_blind/_doctrine_kill (add a scheduler holding MissionState launch_at times, using JASSM/HARM/Tomahawk speeds for TOT math) + world/combat._step_subs shared launch-window gate`
- **Physics-honest:** Arrival overlap is pure range/speed geometry and the outcome emerges from whether the defense's real channel count (see the illuminator-channel item) can absorb it — never a scripted wave that always overwhelms.

### Doctrinally distinct fleet effects: cripple tier + visible role differences
`core · effort M`

Add an ST_CRIPPLED tier (between BURNING and SINKING) driven by the new structural pool: a heavily damaged but afloat ship freezes its rudder, loses its self-defense SAM/CIWS, and lists — so a saturation strike that doesn't sink a destroyer still removes its air-defense contribution. Also make the currently-inert ship-class differences bite: the AirDefenseShip's deeper magazine and the GroundAttackShip's TLAM-first drain become observable, and a Flagship sinking surfaces a 'FLEET COHESION DEGRADED' line. New decision: partial hits and the fleet-mixer steppers finally change how the group fights.

- **Hook:** `sim/ships.py state ladder (add ST_CRIPPLED) + sim/damage.py pool accounting; sim/enemy_ship_classes.py ShipClassDef fields (sm2_max_inflight/track_form_s already wired) + world/combat _check_flagship_cec; after-action/scoring for the cohesion line`
- **Physics-honest:** Cripple onset is a deterministic threshold on accumulated structural damage; the degraded ship's defenses simply stop launching — behavior emerges from measured damage, not a mobility-kill dice check.

### Enemy AWACS/CEC engage-on-remote against sea-skimmers
`big-bet · effort L`

Let any elevated enemy sensor (AWACS/E-2D-class orbit or a forward picket) that holds a track on the player's LOW missile cue a below-horizon shooter via the existing cue_radars_fn datalink, so a sea-skimmer the ship's own mast radar cannot see still gets engaged. Kill or jam the elevated eye and the horizon advantage of going low is restored and rear shooters go blind. New decision: the AWACS becomes a priority SEAD target with a concrete payoff — suppress the elevated sensor to reopen the low-altitude corridor.

- **Hook:** `sim/enemy_defense.py ShipDefense._detects already fans in _cue_radars_fn for track FORMATION; extend the AWACS orbit's radar as a remote cue and add an EnemyCommander AWACS-cued CAP/engage path in sim/commander.py _doctrine_defend`
- **Physics-honest:** The cue only forms a track where an elevated radar actually has line-of-sight via the shipped 4/3-earth radar_horizon_m; killing/jamming that sensor removes the track — pure geometry, no gated hit chance.

### Wolfpack + emitter-cued submarine attack
`core · effort M`

Coordinate n_subs>1 boats so their noisy Kalibr launch transients arrive in a shared window (staggered commit gated by the existing SUB_THREAT_COMMIT_MAX), and let a boat aim at a LOCALIZED player radar-station emitter (via the commander's EmitterIntel belief) instead of only the coarse surveyed base coords. Add a perpendicular EVADE leg so a boat can break an acoustic cross-fix by opening the baseline. New decision: multi-sub setups become a real saturation axis, EMCON-quiet base management denies the sub a precise aim, and re-seeding buoys ahead of the boat's evade turn becomes the ASW counter.

- **Hook:** `world/combat.py _step_subs (shared launch-window gate) + _fire_kalibr_salvo aim source (read sim/commander _believed_radar_station/EmitterIntel); sim/submarine.py Submarine._creep EVADE branch (perpendicular turn using last-heard bearing)`
- **Physics-honest:** The evade geometry feeds the existing acoustic cross-fix solver so the fix decays honestly from baseline geometry, and the emitter-cued aim consumes the same sensor-honest belief the amphibious doctrine uses — no truth read, no dice.

## Game modes, campaign, scoring & replayability

### Finish the attrition ledger: persist base/structure damage across campaign battles
`big-bet · effort L`

Carry structure damage (base cluster, radars, Pantsir sites, bastion TELs) forward between campaign battles instead of healing it free every fight, via the on_destroyed-aware ingest the code already scopes. A battered radar starts the next battle degraded; a destroyed bastion ends the campaign as a real defeat. New decision: whether to spend a marginal battle bleeding structures to save a scarce magazine, knowing the damage follows you into the next fight — the campaign's core risk/reward loop finally has teeth on both axes, not just ammo.

- **Hook:** `game/campaign.py world_snapshot()/initial_state_for() (both explicitly ship 'base_damage:{}' empty and note the deferral at lines 171-183); world/combat.py apply_initial_state must replay each carried-dead structure's on_destroyed kill closure (not just flip a flag) to avoid the sensor/Pantsir desync the docstring warns about; campaign.advance() already handles defeat-ends-campaign.`
- **Physics-honest:** Pure state carry-forward of already-simulated damage — a structure that was killed by real missile geometry last battle simply starts dead this battle; no new probability, the ingest just replays deterministic kill events.

### Difficulty / enemy-competence stepper on the WORLD setup page
`core · effort M`

A single clamped CombatConfig int on the WORLD page that scales existing enemy-AI competence knobs — sensor tick cadence, SM-2 magazine depth, evasion aggressiveness, back-plot accrual rate — via one multiplier, defaulting to a floor that is byte-identical to today. New decision: skilled players get a HARDER version of the same fleet without just piling on more hulls, so the challenge axis becomes competence, not headcount.

- **Hook:** `world/combat_config.py CombatConfig + clamp_config (add difficulty:int with a CLAMP floor so default is unchanged); game/combat_setup.py _WORLD_ROWS (new stepper alongside the MAP row at line 98); the enemy-AI threshold reads in world/combat.py and sim/commander.py multiply against it.`
- **Physics-honest:** Tunes measured reaction-time bands, magazine counts, and emission cadences — the same inputs the no-cheat brain already reads from its sensor picture — never a hit-roll or damage modifier; outcomes still emerge from kinematics.

### Per-battle OBJECTIVE VARIETY across the campaign chain
`core · effort L`

Tag each campaign battle_idx with an objective archetype — SEA CONTROL (kill the fleet), SEAD (kill all radars first), CONVOY DENIAL (stop the transports before beachhead), SILENT RUNNING (win without ever being back-plotted), PICKET HUNT (kill the elevated sensor) — that reweights the five grade axes and the win/lose check for that battle. New decision: each battle demands a different doctrine (loft vs skim, go-dark vs go-loud, prioritize the sensor node vs the shooters) instead of running the same 'more hulls' slugfest six times.

- **Hook:** `game/campaign.py CampaignState (add an objectives list) + next_config; game/scoring.py grade() axis weights (already five measured axes); world/combat.py victorious/defeat clause selection; game/campaign_screen.py next_battle_preview to display the objective in the INTEL panel.`
- **Physics-honest:** Reuses the five already-measured grade axes and existing win/lose clauses — objectives only reweight what's measured from world truth, never add a dice outcome; a SEAD win still requires physically destroying the radars.

### Expand PAR + after-action KILLS to score the full objective (subs, transports, air)
`quick-win · effort M`

Widen the PAR asset model and the AAR KILLS line to count subs, transports/beachhead-denied, and air kills (AWACS/fighters/jammers), not just surface ships + carrier + radars + airfield. New decision: on a sub-heavy or amphibious seed, the hardest work (prosecuting the boat, stopping the landing, killing the AWACS) finally shows up in your grade, so the scorecard rewards servicing the whole threat picture rather than ignoring the domains that were invisible to it.

- **Hook:** `game/scoring.py _enemy_asset_count() (currently only ships/carrier/radars/airfield at lines 125-138) and compute_scorecard(); game/combat_end.py aar_rows() KILLS row.`
- **Physics-honest:** Purely widens the deterministic truth-read that already happens at battle end — it counts additional real dead entities; no probability, just more of the world state fed into the same banded grade.

### Named QUICK-BATTLE presets on the setup header
`quick-win · effort S`

A single stepper on the setup header that fills the CombatConfig with a curated, fully-editable scenario — e.g. 'Saturation Raid' (Tomahawk/Kalibr heavy), 'Carrier Alpha Strike', 'Silent Hunt' (sub-heavy), 'Beachhead Denial', 'Picket Gauntlet'. New decision: instant access to distinct, hand-tuned tactical puzzles that teach the feature space, without hand-stepping 40 fields — and every preset is still a starting point the player can tweak before START.

- **Hook:** `game/combat_setup.py (a PRESETS dict of {name: kwargs} applied into self._fields; new header stepper row); reuses world.combat_config.clamp_config so every preset is still clamped/safe.`
- **Physics-honest:** Only populates config values that already exist and clamp; the battle it produces runs the identical deterministic sim — no new mechanic, just curated starting parameters.

### Per-seed PAR leaderboard / personal-best store
`quick-win · effort M`

Persist the best grade + key metrics per (seed, config-hash) to a small JSON beside campaign.json, and show 'YOUR BEST' next to PAR on the end overlay. New decision: a one-off Combat battle becomes a replayable time-attack against your own prior run on the identical deterministic seed — do you rematch to beat your emissions time / shots-per-kill, or move on?

- **Hook:** `game/scoring.py ScoreCard (serialize it); new persistence mirroring game/campaign.py save/load + default_save_path; game/combat_end.py render (an extra column beside the VALUE-vs-PAR table).`
- **Physics-honest:** Stores and compares already-computed deterministic ScoreCard metrics; a fixed seed reproduces the same physics, so the comparison is honest by construction — no scoring change, just persistence.

### Setup-screen validation + PAR-difficulty footer
`quick-win · effort S`

A live footer on the setup screen showing total offensive rounds, the estimated PAR difficulty of the in-progress config (compute_par is pure and already takes a config), and warnings when a threat axis is enabled without its counter (e.g. n_subs>0 but sonobuoys=0, or transports>0 with no ASW/point-defense to stop the beachhead). New decision: the player can read whether they've built a fair, winnable fight BEFORE committing, instead of discovering an uncounterable loadout only on the defeat screen.

- **Hook:** `game/combat_setup.py render footer — call game.scoring.compute_par on build_config(); reuse the sub-vs-ASW fairness rule already living in campaign._escalated_counts to drive the warning strings.`
- **Physics-honest:** Read-only decision support — it surfaces the deterministic compute_par output and a config sanity check; it never alters the sim or any outcome.

### Daily-seed and weekly-challenge modes
`core · effort M`

A globally-shared daily seed fixes the enemy fleet, strike composition, sea-state and RNG so everyone fights the identical battle (one attempt, ranked on a PAR-relative score); a weekly variant locks a seed re-runnable all week to optimize, gated by a scoring condition (e.g. base survives AND under N interceptors expended). New decision: a fixed public seed turns tactical mastery into a comparable, competitive optimization problem rather than a private one-off.

- **Hook:** `main.py / menu (a new mode entry alongside SANDBOX/COMBAT/CAMPAIGN); game/scoring.py compute_par + ScoreCard for the ranked bar; reuse the deterministic LCG/derive_seed and the personal-best JSON persistence for the daily record.`
- **Physics-honest:** A fixed seed makes the deterministic physics reproduce identically for every player; the ranking compares real ScoreCard metrics on that shared seed — no dice, the sim IS the leveler.

### Challenge-modifier stack (composable one-rule mutators)
`core · effort M`

A set of independently-toggled, stackable modifiers that each change ONE existing rule: EMCON LOCKDOWN (search radar starts OFF — fight on ELINT/passive until you accept the emissions gamble), NO RESUPPLY (the starting magazine is all you get), COLD WAR / WEAPONS-TIGHT (no firing on a track below CLASSIFIED), IRON MAGAZINE (every missed interceptor is gone for the battle), FOG BANK (degraded sensor ranges). New decision: each modifier forces a distinct discipline in systems that already exist — when to emit, when to commit a scarce round, how tightly to ration — turning one battle into many self-selected difficulty puzzles.

- **Hook:** `world/combat_config.py CombatConfig (a small set of bool/int modifier flags with clamp defaults = off); game/combat_setup.py a modifier toggle block; the flags gate EXISTING mechanics — toggle_radar start-state, resupply in campaign.apply_resupply, the classification-gated fire path, and the interceptor/ammo accounting.`
- **Physics-honest:** Every modifier gates or reconfigures a mechanic already in the sim (emissions, resupply, classification, magazine); none introduces a probability — outcomes still emerge from the same physics under tighter constraints.

### Consequence-branching campaign nodes (outcome-driven, not menu-driven)
`big-bet · effort L`

Make each campaign node's successor depend on measured battle outcome rather than a fixed chain: a clean defense pushes the enemy to a longer-range, sensor-harder engagement; heavy losses force a fighting-retreat node with a damaged base and depleted magazine. Branch selection reads campaign state variables (base health, magazine %, enemy tempo) directly. New decision: the player feels tactical sensor/EW choices ripple forward — win efficiently to earn an easier strategic position, or bleed and inherit a harder one.

- **Hook:** `game/campaign.py CampaignState + next_config/advance (branch on carried base_damage %, ledger %, and grade instead of a linear battle_idx); game/campaign_screen.py IN-PROGRESS preview to show the branch rationale.`
- **Physics-honest:** Branches key off measured outcomes (surviving structures, ammo remaining, grade) that are all deterministic reads of the prior battle — no randomness picks the path, the player's real performance does.

## Maps, terrain, weather & environment

### Sea-state dial coupling waves, sea-clutter, and minimum skim altitude
`big-bet · effort L`

One measured Beaufort-like sea_state value per battle (seeded, set on the World page and carried on the HeightField/config) that drives THREE things at once: (1) ocean wave amplitude (a0..a3 become shader uniforms instead of hardcoded), (2) a sea-clutter noise-floor term added to Radar.detects for low-altitude targets — higher seas shorten the range at which a sea-skimmer is seen, (3) a physical minimum-safe skim altitude in _surface_at / skim ref: below it a low-frequency deterministic swell (seeded sinusoid on the ocean surface) risks a wave-crest clip that spoils the terminal run. New decision: in calm seas your skimmer is easy to see but you can hug the deck; in rough seas the clutter hides you but you must fly higher and give the defender more warning — a genuine two-edged environmental gamble made every salvo.

- **Hook:** `world/ocean.py OCEAN_VERT a0..a3 -> uniforms + RINGS wave_weight; sim/radar.py Radar.detects (add a sea_state clutter term to the low-altitude range/floor, reusing the jammers!=() branch pattern); sim/missile.py _surface_at/_skim_ref swell modulation; world/generation.py HeightField (carry sea_state); world/combat_config.py CombatConfig new clamped int (floor 0 = byte-identical calm)`
- **Physics-honest:** Detection shrinks because clutter raises the measured noise floor and a crest clip is a real surface-collision at a computed altitude — miss/detection emerge from geometry and propagation, never a Pk roll; sea_state 0 is bit-identical to today.

### Evaporation-duct weather event: forecastable, uncertain low-altitude detection window
`core · effort M`

A semi-random coastal surface-duct condition, seeded per battle and tied to the map's climate, that temporarily multiplies the effective low-altitude detection range 2-3x (a real radar waveguide over the sea). It can be present at battle start or form/lift mid-battle on a deterministic schedule. Surfaced as a briefing-screen forecast with a confidence band (the forecast can be wrong within a stated margin). New decision: time your sea-skimming salvo to a duct-FREE window (or accept that the enemy will see it far earlier than the nominal horizon), and conversely exploit a duct to extend YOUR early warning against an inbound raid.

- **Hook:** `sim/radar.py radar_horizon_m / Radar.detects (a duct multiplier on the low-altitude horizon term); world/combat.py step schedule for form/lift timing; world/generation.py HeightField or config carries the duct climate + seeded schedule; a forecast read on the briefing/setup screen`
- **Physics-honest:** The duct only changes detection GEOMETRY (the horizon distance for a low flyer) on a deterministic seeded schedule — the missile is either over the horizon or not; no probability is ever rolled on hit/miss, and the forecast uncertainty is a stated band, not a dice draw.

### Per-map lighting profile + day/night thermal clock (dawn / midday / dusk / overcast / night)
`core · effort M`

Promote SUN_DIR, SUN_COLOR, HAZE_COLOR and the sky-gradient endpoints from module constants to a LightingProfile selected by the map/scenario (or a time-of-day stepper), driving the existing single-sun pipeline and sky shader; add stars/moon + faint horizon cloud bands to the dome under a night factor. Couple the same clock to a ship-vs-sea thermal-contrast scalar so passive IR/IIR acquisition (any future IR seeker or IRST) peaks in afternoon and collapses at the pre-dawn crossover. New decision: schedule a strike for the thermal crossover to blind IR sensors, or wait for peak contrast if you rely on passive tracking — plus night scenarios read as genuinely distinct, not just darker.

- **Hook:** `engine/renderer.py SUN_*/HAZE_* constants -> a LightingProfile passed into Renderer.set_common; world/sky.py SKY_FRAG endpoints + a night-factor uniform (star hash-noise, horizon cloud gradient); a thermal-contrast scalar on the HeightField/config read by any IR seeker acquisition`
- **Physics-honest:** IR acquisition range is a function of the modeled thermal-contrast scalar vs a fixed threshold — a target is either bright enough to detect or it isn't; the day/night state is a deterministic clock, no roll. Lighting alone is pure presentation and changes nothing simulated.

### Ocean relief on the mid/far rings (kill the flat-plate horizon)
`quick-win · effort S`

Enable wave displacement past the current 8 km cutoff: raise wave_weight on ring 2 and add a third longer-wavelength swell to OCEAN_VERT, tapering amplitude to 0 by the far ring so there is no hard seam. Purely analytic — no new geometry, the rings already exist. The sea stops reading as a flat plate at distance, so sea-skimming missiles and distant ships have real relief to be seen against, reinforcing the visual-sensor loop.

- **Hook:** `world/ocean.py RINGS wave_weight (ring 2 currently 0.0) + OCEAN_VERT wave set (add a 3rd swell, taper by ring)`
- **Physics-honest:** Pure render-side displacement of the visual ocean surface; no sim/detection state reads it, so nothing about hit/miss changes — cosmetic realism only.

### Radar-horizon + reaction-time overlay on the tactical map
`quick-win · effort S`

Draw each sensor's true LOS/horizon footprint against terrain and sea on the map, and on any launch (yours or an inbound) show the predicted detection point and the detection-to-impact seconds derived from mast height, skim altitude, and missile speed. The sim already computes every input (radar_horizon_m, terrain_blocks, the height field); this only surfaces it. New decision: plan skim altitude and approach bearing to MINIMIZE the enemy's seconds-of-warning, reading the horizon gamble instead of guessing it.

- **Hook:** `game/tactical_map.py overlay layer; read sim/radar.radar_horizon_m + terrain_blocks + world.surface_height_at; reuse the existing INBOUND TTI math`
- **Physics-honest:** Displays numbers the sim already derives from geometry (horizon distance, closing time); it computes nothing new and rolls nothing — it makes the existing deterministic physics legible.

### Pre-battle Environment Briefing card
`quick-win · effort S`

A setup/briefing-screen card showing sea state, wind, duct forecast + confidence, cloud/fog and humidity (IR impact), moon/solar phase for the thermal clock, and the resulting nominal radar horizon per platform. Every value feeds the sim; the forecast may be wrong within a stated band. Makes the environment a readable, plannable input to the EMCON/go-low decision rather than an invisible modifier, and gives the sea-state/duct/lighting work a single home to be read from.

- **Hook:** `game/combat_setup.py (new card beside the MAP/SEED rows) or a briefing state; reads the sea_state/duct/lighting fields off CombatConfig + HeightField and sim/radar.radar_horizon_m`
- **Physics-honest:** A pure read-out of the environmental dials the sim already consumes, with a forecast-uncertainty band instead of false precision — no simulated outcome depends on the card itself.

### Seeded fleet-spawn minimap thumbnail on the World setup page
`quick-win · effort S`

Render a tiny fog-free minimap thumbnail of the chosen map preset + seed (terrain + deterministic fleet spawn) beside the MAP/SEED rows, so the player sees the geography and rough force layout they're committing to before START. Reuses the existing deterministic tactical-map pixel builder and the pure fleet sampler. New decision: seed-shopping becomes an informed geographic choice (which chokepoint, which island cover) instead of a blind commit.

- **Hook:** `game/tactical_map.py build_map_pixels/ensure_map_pixels_async (already caches per-preset digest); world/spawn_zones.sample_fleet (already pure/deterministic); game/combat_setup.py render`
- **Physics-honest:** Presentation only — it draws deterministic terrain + spawn data that already fully determine the battle; nothing simulated is altered.

### Deepen map archetypes with distinct default sea-state and duct climate per geography
`core · effort M`

Give each of the four existing map presets (OPEN SEA / ARCHIPELAGO / NARROW STRAIT / FJORD COAST) a characteristic default sea_state and duct-formation tendency so the geographies play differently in the environmental layer, not just the island layout: open ocean = pure horizon-timing with calm-to-moderate seas, fjord = frequent ducting in sheltered water and steep radar shadows, strait = funneled corridor, archipelago = pop-up-behind-island ambush. New decision: the map you pick now implies an environmental style of play, deepening replay variety with no new geometry.

- **Hook:** `world/generation.py _make_preset / HeightField (carry per-preset default sea_state + duct climate); depends on the sea-state and duct items landing first; world/combat_config.py map_preset already selects the field`
- **Physics-honest:** Only sets the seeded defaults of the sea-state/duct physics per map; all detection/collision outcomes still emerge from those deterministic models, never a roll.

### Swept terrain/water surface-impact test (close the hypersonic tunneling gap)
`quick-win · effort S`

Make the terrain/water impact check a swept segment like the ship OBB test already is: check prev_pos->pos against the surface height at a few samples ALONG the step (gated by step length so slow Oniks keeps its single query), instead of only the endpoint. A Zircon moving ~6.7 m/step at max sink can currently tunnel one step past a coastal cliff face; this fixes that against terrain — which matters precisely on the island/fjord maps this cluster adds.

- **Hook:** `sim/missile.py update() surface-impact block (py <= surface) + _surface_at; sim/sam.py same block; gate the multi-sample by step length so Oniks is perf-neutral`
- **Physics-honest:** It makes the collision test honest to the actual swept path — impact emerges from real geometry rather than an aliased point sample; no probability involved, and slow rounds stay bit-identical.

## Sensors, EW & simulation depth (sensor)

### SNR-coupled classification ladder (dwell scales with signal, not the wall clock)
`core · effort M`

Make the CLASS->TYPE identification ladder earn faster on a close, clean, loud return and slower on a distant, jammed, or low-RCS one, instead of a fixed stopwatch from first_seen. Scale the elapsed dwell by an SNR proxy built from the SAME inputs the detection gate already has: target range vs the radar's per-size max range, plus the live ew.noise_floor_at at the tracking sensor. New tactical decision: closing to identify (or killing the jammer) actively buys you the TYPE label sooner, so ID becomes a thing you invest in rather than wait out; and a deceptive/distant contact stays UNK long enough to matter for weapons-release timing.

- **Hook:** `sim/contacts.py classify() (scale dwell = (sim_time-first_seen) by an SNR factor before the CLASSIFY_DWELL thresholds); feed it the range vs Radar.ranges[size] and sim/ew.noise_floor_at that the ContactBoard._seen gate already computes; the track dict already carries first_seen/size.`
- **Physics-honest:** No roll: dwell-scale is a deterministic function of measured range/noise-floor (the same 1/R and J/S quantities the radar/EW model already computes); same seed and geometry -> same ID timing, byte-identical when SNR is nominal.

### Fog-honest blind-fire penalty: classification gates the seeker handoff basket
`core · effort M`

Give the classification ladder teeth by making launch quality depend on how well the target is identified. Firing an Oniks/S-300/Buk at an UNKNOWN or low-Q track widens the terminal seeker's acquisition basket / initial handoff error (a fuzzy track = a fuzzy cue), while a firm IDENTIFIED, high-Q track hands off tightly. Surface it as a map hint (e.g. 'LOW-Q HANDOFF - WIDE BASKET'). New tactical decision: shoot now on a fuzzy paint and accept a real miss-distance risk, or keep the emitter painted / close the drone in to firm the track first (revealing yourself) for a clean shot.

- **Hook:** `game/tactical_map.py _click_target/_retarget_selected reads sim/contacts.classify stage + track_quality; scales the initial handoff/lock basket in sim/missile.py _acquire_lock (and sim/sam.py) from that quality; reuse contact_intel()'s already-computed stage/Q.`
- **Physics-honest:** The basket size is a deterministic function of the track's staleness/quality bands and classification stage — the seeker then still has to physically acquire from that wider (but exact) initial error, so hit/miss emerges from the acquisition geometry, never a probability gate.

### Home-on-jam seeker mode (an ARM/Oniks variant that flies the ELINT bearing to a jammer)
`core · effort M`

Add a seeker mode that homes on a jammer's emission even without a localized fix: the round flies the passive ELINT bearing to the believed jammer and sharpens as it closes (bearing error shrinks with range, then skin-track/terminal takes over). New tactical decision: the enemy turning up a Growler to blind your net now becomes a beacon you can shoot down the bearing — jamming is a gamble, not a free win, and it directly rewards the EMCON/SEAD half of the game.

- **Hook:** `sim/ew.py already names 'home-on-jam seekers' as an intended consumer; world/combat._believed_jammer_fix + emitter_contacts (kind=='JAMMER') already publish the bearing/fix; add the guidance mode to sim/missile.py reusing the existing ARM emitter-homing path.`
- **Physics-honest:** Guidance follows the actual radiated-emission bearing the ELINT chain measures (with its real, geometry-driven angular error) and only converges as 1/R closes the bearing error — pure pursuit geometry, no dice; if the jammer goes silent the bearing decays and the round misses honestly.

### Staged EMCON posture (SILENT / LPI-low-power / FULL) instead of the binary radar toggle
`core · effort M`

Replace the on/off radar switch with a three-position emissions dial. LPI/low-power shrinks your own detection ranges but also shrinks the range at which enemy ESM accrues a back-plot fix on you; FULL sees farthest but paints you loudest; SILENT is blind but un-back-plottable. New tactical decision: a graded detect-vs-be-detected gamble — go quiet to survive the counter-battery, or light up to see the raid earlier and accept a faster enemy fix, with a middle band that was impossible before.

- **Hook:** `game/sandbox.py toggle_radar -> a posture cycle; add an emit_power scalar on sim/radar.Radar that scales self.ranges; feed the same scalar into world/combat _feed_enemy_picture ESM accrual and game/hud.emissions_exposure (already a 0..1 loudness gauge).`
- **Physics-honest:** Both the shrunken detection range and the reduced ESM accrual are the same 1/R propagation quantities scaled by one power factor — the enemy's fix rate emerges from received power geometry, not a difficulty modifier or roll.

### Deceptive (DRFM) jammer variety: false ghost tracks the player must filter, defeatable by home-on-jam
`big-bet · effort L`

Add a jammer kind that injects false ContactBoard tracks (range/velocity-gate pull-off ghosts) rather than only raising the noise floor. Ghosts carry an is_ghost provenance, drift off real kinematics, and can be localized/burned-through or killed by home-on-jam. New tactical decision: under deception jamming the picture itself lies, so the player must cross-check ghosts against a second sensor or ELINT bearing before committing a scarce missile — turning target discrimination into a real fog problem instead of pure noise.

- **Hook:** `sim/ew.py (new deceptive branch alongside noise_floor_at); sim/contacts.ContactBoard.update injects gated ghost tracks with an is_ghost flag; game/tactical_map glyph for a suspected ghost; pairs with the HOJ seeker above.`
- **Physics-honest:** Ghost placement is a deterministic function of the jammer's gate-pull parameters and geometry (a real DRFM range/velocity walk), and a ghost fails cross-sensor/ELINT consistency by construction — the player defeats it via measured disagreement, never a luck check.

### Multi-sensor track quality: fusion lifts Q, not just staleness
`quick-win · effort S`

Let track quality rise with the NUMBER of independent sensors currently holding a track (radar net + SAR + ELINT), not staleness alone. Add a fused-sensor count and lift the Q5..Q1 chip when coverage overlaps. New tactical decision: overlapping your radar, drone SAR, and ELINT on the same contact is now rewarded with a firmer, higher-Q track (which — combined with the blind-fire-penalty item — means a better shot), making multi-domain coverage an explicit EW objective rather than a happy accident.

- **Hook:** `sim/radar.RadarNetwork add a visible_count variant; stamp a per-refresh sensor count on the track dict in sim/contacts.ContactBoard.update; sim/contacts.track_quality() lifts Q by that count; game/hud _intel_panel Q chip already renders Q.`
- **Physics-honest:** The sensor count is a deterministic tally of which detection gates (each pure geometry) currently pass — Q is derived, never rolled; single-sensor tracks stay byte-identical to today.

### Sensor-disagreement uncertainty ellipse: show the fog instead of hiding it
`quick-win · effort S`

When ELINT and radar hold the same platform at meaningfully different positions, render an uncertainty ellipse (or twin belief markers) spanning both fixes instead of silently keeping only the fresher one. The ellipse tightens as the fixes converge. New tactical decision: the player can SEE when the picture is ambiguous and decide whether to invest a second bearing / another sensor pass before committing a missile, rather than trusting a false-precise dot.

- **Hook:** `world/combat.py _inject_elint_tracks (keep both the radar fix and the ELINT est_pos rather than refusing the overwrite); carry a belief-spread on the track dict; game/tactical_map.py _contacts/_elint overlay draws the ellipse from the two fixes' separation + fix_quality.`
- **Physics-honest:** The ellipse is pure derived geometry — the separation of two independently measured fixes and the ELINT CRLB error already computed — no simulated outcome changes, it only stops discarding information the sim already has.

### Physical JAMMED-corridor beamwidth driven by the actual ELINT fix quality
`quick-win · effort S`

Replace the fixed 22-degree cartoon jam wedge with a beamwidth that narrows as the believed jammer is localized — driven by the real ELINT angular uncertainty (fix_quality), so a well-localized jammer shows a tight corridor and a barely-heard one shows a fat one. New tactical decision (teaching, not a lever): the overlay now visibly rewards flying the drone to sharpen the jammer fix — the corridor tightening is the feedback that localizing the source is what restores your picture.

- **Hook:** `game/tactical_map.py _jam_overlay / JAM_BEAMWIDTH_RAD (currently a literal 22deg 'for now'); read world.ew_state + elint.fix_quality for the localized JAMMER emitter to derive the half-angle.`
- **Physics-honest:** Beamwidth becomes a monotone function of the measured ELINT angular error (fix_quality) — deterministic geometry, no roll; render-only, so zero sim/determinism impact.

### Live ELINT/acoustic fix-quality readout + best-next-baseline cue for the drone
`quick-win · effort S`

Surface the actual localization numbers the solver computes: a small 'FIX 3.2 km / need 5.0' label on each emitter and subsurface glyph, and a subtle 'fly here to sharpen' baseline-geometry cue arrow for the drone. New tactical decision: the deepest mechanic in the game (bearing-only triangulation with three CRLB gates) becomes learnable and steerable — the player can read whether one more cross-track leg makes the fix actionable and task the drone to the baseline that does it.

- **Hook:** `game/tactical_map.py _elint_overlay / _emitter_overlay / _asw_overlay; read sim/recon.ElintReceiver.fix_quality + est_pos and the stored observer geometry in _solve_triangulation; the acoustic subclass exposes the same via hearing_count.`
- **Physics-honest:** Pure read-only surfacing of numbers the CRLB solver already produces (fix error in metres, observer baseline vs range) — no sim change, and the cue arrow just points along the geometry that the solver's own gates say sharpens the fix.

### Altitude-dependent threat-ring overlay (the go-low gamble made legible, fog-gated)
`core · effort M`

Draw each CLASSIFIED enemy shooter's effective first-shot envelope for the player's CURRENT chosen cruise altitude, using the radar-horizon geometry: a low sea-skim shrinks a shooter's opening range dramatically (target below its horizon), a higher profile balloons it. Rings appear only for shooters the player has classified via ELINT/track (a dashed uncertainty band for unclassified ones). New tactical decision: pick the ingress altitude and bearing by watching the enemy's shot windows shrink/grow live, turning the go-low gamble into a readable plan rather than a blind stat choice.

- **Hook:** `game/tactical_map.py new overlay; reuse sim/radar.radar_horizon_m + each emitter's antenna_alt and its size-class ranges; gate on sim/contacts.classify stage so unclassified shooters show a dashed band (fog).`
- **Physics-honest:** Each ring is computed straight from the radar-horizon equation (mast height + target altitude) and the shooter's real max range — the same geometry the detection gate uses — so it is a faithful projection of when the target actually crests the horizon, never an assigned probability.

## QoL, UX, UI & controls

### Event-jump auto-warp + latched cause label
`core · effort M`

Extend the existing TimeWarpDirector so the player can arm which sim events snap time back to 1x (new contact, contact classified/reclassified, ELINT bearing, launch detected, own round goes terminal, intercept/miss resolved, own-unit damaged). Sim fast-forwards through dead transit and auto-slows the instant an armed event fires, centering the camera on it. Bundle the shipped auto-warp fix: latch drop_cause for the director's DWELL_S so the '_scale_text' cause tag stops flickering INBOUND/TERMINAL frame-to-frame. New decision: which event classes are worth your attention this scenario, so the ~25-60s sea-skimmer reaction window is never missed at warp.

- **Hook:** `game/timewarp.py TimeWarpDirector (DWELL_S debounce, drop_cause at line 210) + game/hud.py _scale_text (line 1353); arm-list read from a small settings field; camera snap via game/sandbox.py cycle_camera_subject`
- **Physics-honest:** Only changes how many 120Hz steps run per frame and when to pause; it never alters an outcome — the events it stops on are the real sensor/kinematic state transitions the sim already computes.

### Beachhead / defeat-cause honesty pass
`quick-win · effort S`

Two coupled fixes for a shipped lose-path that is invisible until the loss screen. (1) A live HUD banner + LANDING_BOX ring + committed-craft count and red countdown while world.beachhead_active is True. (2) Wire world.defeat_cause into the end overlay subtitle so a beachhead loss reads 'BEACHHEAD ESTABLISHED' and a bastion loss 'ALL BASTION TELs DESTROYED', instead of the hardcoded bastion string on every defeat. New decision: the player can actually see the landing clock ticking and choose to divert fire to the corridor before the 180s runs out.

- **Hook:** `world/combat.py beachhead_active/beachhead_left/defeat_cause (all exist, no HUD consumer); game/hud.py (new banner) + game/tactical_map.py _asw_overlay (LANDING_BOX ring); game/combat.py _open_end_overlay + game/combat_end.py subtitle map`
- **Physics-honest:** Pure read of already-computed world state and a geometric ring; no simulated behavior changes, it only surfaces truth the sim already tracked.

### Adaptive per-track TTI countdown bar
`quick-win · effort S`

Replace the global TTI_BAR_WINDOW_S=240s normalization with a per-card window keyed off that track's own first-detection TTI (or a per-kind expected flight time), so the glance bar drains meaningfully for a fast ASBM/Zircon inbound and a slow Tomahawk alike. Store first-seen TTI per sid (extend the existing _threat_seen set to a dict). New decision: the drain rate itself now tells the player which inbound is genuinely time-critical, so triage-by-glance actually works during saturation.

- **Hook:** `game/hud.py TTI_BAR_WINDOW_S (line 144) + _threat_strip frac calc (line 1479) + _threat_seen (line 990, promote set->dict)`
- **Physics-honest:** Presentation only — the TTI number stays the true simulated time-to-impact; only the bar's fill fraction is renormalized per track.

### Camera-slew-to-threat from the inbound strip
`core · effort M`

Make each INBOUND threat card clickable to slew the camera onto that track's dead-reckoned estimate, and insert detected hostile tracks into the [ / ] subject cycle as fog-safe estimate anchors (StaticSubject on the ESTIMATE, never truth). New decision: the ranked threat list becomes actionable — glance, click, and look at the vampire you decided is most dangerous, instead of hunting for it on the map.

- **Hook:** `game/hud.py _threat_strip (add per-card click rects, line 1391) + game/cameras.py subject_cycle_order/StaticSubject + game/sandbox.py cycle_camera_subject`
- **Physics-honest:** Anchors on the dead-reckoned belief position the ContactBoard already publishes, so it reveals nothing the fog wouldn't — no ground-truth read, no outcome change.

### Click-to-inspect contact in the 3D main view
`core · effort M`

Reuse world_to_screen to hit-test rendered contacts under the cursor in the main 3D view (not just the map) and set sandbox.selected_contact, so the existing contact_intel/_intel_panel widget works without opening the tactical map. New decision: the player can interrogate a contact's class/quality/bearing while flying the shot, keeping eyes on the world during the terminal moment.

- **Hook:** `game/hud.py world_to_screen (line 924) + _intel_panel/contact_intel (lines 1490/496); game/controls.py SandboxControls camera-mouse handler (add LMB pick when not orbit-dragging)`
- **Physics-honest:** The panel it feeds is the same fog-gated contact_intel read (belief, quality chip, teal-not-green LAW); picking a screen entity changes nothing simulated.

### One-key declutter + threat-only filter
`quick-win · effort S`

A hotkey that ghosts everything except armed/hostile/inbound contacts and suppresses their vectors and range rings; a companion toggle merges overlapping range rings; and zoom-dependent label detail (type-only zoomed out, full datablock zoomed in). A second key snaps the map/camera to the nearest inbound. New decision: none directly — it makes the existing decisions survivable under a saturation strike, exactly when the screen is busiest and time is shortest.

- **Hook:** `game/tactical_map.py contact + overlay draw passes (filter flag), range-ring merge in the same overlay layer; game/keybinds.py new rebindable action`
- **Physics-honest:** Hides symbols only; nothing in the sim state or fog picture changes, so no outcome is affected.

### Quick-battle presets on the setup header
`quick-win · effort S`

A single stepper on the combat-setup header that fills the _fields dict with curated CombatConfigs — 'Saturation Raid', 'Carrier Alpha Strike', 'Silent Hunt' (sub-heavy), 'Beachhead Denial' — each still fully editable and re-clamped afterward. New decision: instant interesting fights and a fast on-ramp to the ~40-stepper feature space, teaching the player what the axes do by example.

- **Hook:** `game/combat_setup.py (a PRESETS dict of {name: kwargs} applied into self._fields at line 296; new stepper row in _WORLD_ROWS); reuses world.combat_config clamp on build_config (line 490)`
- **Physics-honest:** Presets are just field populations fed through the existing deterministic clamp/spawn; the battle that runs is the same physics, only pre-configured.

### Setup validation + PAR/cost footer
`quick-win · effort S`

A live setup-screen footer showing total offensive rounds, estimated PAR difficulty (call compute_par on the in-progress config), and an amber warning when a threat axis is enabled without its counter (e.g. subs>0 but sonobuoys/asw=0), reusing the campaign escalation fairness rule. New decision: the player sees they've built an uncounterable or trivially-easy loadout before committing, instead of discovering it at the loss/PAR screen.

- **Hook:** `game/combat_setup.py render footer (line 506) calling game.scoring.compute_par(build_config()); n_subs-vs-ASW check mirroring campaign._escalated_counts fairness block`
- **Physics-honest:** compute_par is a pure deterministic function of the config; the footer only reads and displays, never nudging any outcome.

### Forensics BLACK BOX telemetry tab
`core · effort M`

Fill the placeholder BLACK BOX tab with a per-sample telemetry table straight from the flight_recorder samples (t, altitude, cumulative ground-km, derived speed/mach), reusing cumulative_ground_km. New decision: post-battle, the player reads the exact go-low altitude-vs-range trace that made a shot hit or overfly, learning the descent timing that worked.

- **Hook:** `game/forensics.py _right_column tab==1 branch (line 729, currently 'deliberately undesigned') + cumulative_ground_km (line 169) + game/flight_recorder.py samples/path_of`
- **Physics-honest:** Every number is a replayed recorded sample under the 1:1 accuracy contract — no invented values, fog-gated to what the player could see.

### Combat message log with click-to-locate
`core · effort M`

A per-unit combat message log with type color-coding (contacts / weapons / EW / damage), unread highlighting, and click-to-fly-to-location, fed from the same event bus the SHOT DEBRIEF forensics recorder already drains — one source of truth for the live log and the after-action ledger. New decision: under a saturation strike the player can scan a bounded, prioritized stream instead of watching the whole map, bounding the cognitive load that sank comparable sims.

- **Hook:** `WorldState.events (already drained in game/sandbox.py) + game/forensics.py flight/event recorder as the shared source; new scrollable HUD panel modeled on the existing overlay widgets`
- **Physics-honest:** Read-only over the real event stream and fog-gated to detected events; it reports what happened, it does not change what happens.

### Persist camera/pacing prefs + Buk salvo-row parity
`quick-win · effort S`

Two small consistency fixes bundled. (1) Persist camera mode, last time-scale, and the auto-warp toggle into the same versioned settings.json the keybinds already use, so a session restores the player's preferred view/pacing. (2) Add the missing salvo_readout row to the Buk plate (_buk_block) so a Buk ripple shows queued-round progress like the Bastion/S-300 plates already do. New decision: none — pure friction removal and cross-platform consistency.

- **Hook:** `game/keybinds.py settings save/load payload (line 289, extend versioned schema) + game/controls.py _scale_idx/auto_warp + game/cameras.py mode; game/hud.py _buk_block (line 1313) add salvo_readout (line 408)`
- **Physics-honest:** Preferences and a readout row; neither touches simulation, only what persists and what's displayed.

### In-HUD F1 rebind capture panel
`core · effort M`

Make the F1 controls overlay's 'REBIND IN SETTINGS' actionable in-battle: a lightweight capture overlay mirroring the settings-screen layout that drives the already-complete Keybinds.rebind/conflict/reset_row/reset_all model (injective swap-on-conflict included). New decision: the player fixes an awkward binding the moment it bites, without abandoning the fight.

- **Hook:** `game/keybinds.py Keybinds.rebind/conflict/reset_row/reset_all (model complete + tested); new capture overlay mirroring the F1 _controls_overlay layout in game/hud.py`
- **Physics-honest:** Pure input-mapping UI; it changes which key does what, never any simulated outcome.


---

# Appendix — Research Sources & Real-World Grounding

## player-missiles — modern anti-ship & land-attack cruise / hypersonic missiles the ONIKS player could wield beyond Oniks & Zircon

- LRASM (AGM-158C): subsonic (~Mach 0.9 / 1,050 km/h), range ~926 km. Flies medium altitude in transit then descends to a low sea-skimming terminal approach. Multi-mode PASSIVE seeker suite: jam-resistant GPS/INS + imaging IR with automatic target recognition + passive ESM/RWR — it emits nothing, homing on the target's own RF emissions and IR signature. This is the defining trait: a stealthy, emissions-silent penetrator, not a fast one.  *(src: Wikipedia AGM-158C LRASM; globalmilitary.net/missiles/lrasm; Lockheed Martin product card)*
- LRASM is highly autonomous: onboard route planning tied to its ESM package lets it AUTOMATICALLY re-route mid-flight when a new emitter/air-defense radar appears (RF-cued threat avoidance). Semi-autonomous terminal logic reduces dependence on ISR, datalink and GPS in EW/denied environments; onboard threat-library classifier IDs the correct ship and avoids neutral shipping in crowded waters. This is an EW-reactive, network-optional weapon by design.  *(src: military-history.fandom AGM-158C LRASM; militaryaerospace.com Lockheed AI-enabled IIR; NAVAIR LRASM)*
- NSM (Kongsberg): high-subsonic Mach 0.93, range >200 km (JSM air-launched variant extends toward ~300+ km). Completely PASSIVE — no active radar emissions at all; uses INS/GPS + terrain-reference (TERCOM) mid-course and an imaging-IR seeker with Autonomous Target Recognition in terminal. Explicitly flies OVER and AROUND landmasses using terrain masking to strike from unexpected bearings, plus programmed evasive terminal maneuvers. 407 kg / 120 kg warhead.  *(src: Wikipedia Naval Strike Missile; kongsberg.com NSM; armyrecognition NSM)*
- BrahMos: Mach 3.0 (~3,700 km/h) throughout, range 290 km (baseline) to 350–450 km (extended). Sea-skims at 3–10 m altitude; active X-band radar seeker goes live at 50–70 km, tracking moving ships autonomously (INS + multi-GNSS mid-course, active radar terminal). Demonstrated evasive high-G 'S' maneuver at Mach 2.8 in the terminal seconds. ~9x the kinetic impact energy of a subsonic missile at the same warhead mass — speed itself is a damage multiplier.  *(src: Wikipedia BrahMos; nationalsecurityjournal.org; missilestrikes.com/weapons/brahmos)*
- YJ-18 (two-stage 'sprint' architecture — the key design pattern): turbojet cruise ~180 km at Mach 0.8 (sea-skimming, low-observable), then a solid-rocket booster kicks the final ~40 km terminal dash to Mach 2.5–3.0. Total range 220–540 km. Active radar terminal seeker; ~300 kg warhead; HE or anti-radiation options. The subsonic cruise stays under the radar horizon and gives the defender almost no warning; the supersonic sprint collapses the terminal reaction window. US assesses it as derived from the Russian 3M-54 Klub.  *(src: CSIS Missile Threat YJ-18; Wikipedia YJ-18; USCC report on YJ-18)*
- Kalibr 3M54 (SS-N-27 Sizzler): mirrors YJ-18 — subsonic 0.8–0.9 Mach turbojet cruise, then a separating supersonic terminal stage sprinting to Mach 2.9 at just ~4.6 m sea-skim altitude. Range 220–300 km (export) up to 440–660 km (domestic 3M54K). Active radar terminal seeker. The two-stage sea-skim-then-sprint is the canonical anti-ship penetration profile.  *(src: CSIS Missile Threat SS-N-27 Sizzler; Wikipedia Kalibr family; armyrecognition 3M54-1)*
- Tomahawk Block Va Maritime Strike (MST): subsonic, range 500–700 km (anti-ship profile) / up to ~1,600 km land. New PASSIVE multi-mode seeker to detect and hit MOVING ships at extreme range; sea-skimming terminal path; heavy reliance on off-board targeting/cueing and mid-course updates because the target moves during the long transit. EOC reached late FY2025. Niche: very-long-range, patient, network-cued precision strike vs a moving fleet.  *(src: Naval News (2025) US Navy Tomahawk anti-ship upgrade; National Security Journal MST; naval-technology.com MST)*
- Exocet MM40 Block 3/3c: high-subsonic, range >180–200 km (turbojet TRI-40, JP10 fuel). Sea-skims at just 1–2 m above the surface (lowest of the set). Active J-band RF seeker with adaptive search patterns. Accepts programmable 3D GPS WAYPOINTS enabling off-axis approach, land-target strike, and coordinated 'simultaneous time-on-target' salvos from multiple bearings. Niche: waypoint-choreographed multi-axis saturation.  *(src: MBDA Exocet MM40 Block 3c datasheet; Wikipedia Exocet; weaponsystems.net MM40 Block 3)*

## enemy-defenses — modern naval air-defense & point-defense systems the enemy fleet could field as new counters to the player's Oniks/Zircon salvo

- Layered naval air defense is explicitly zoned by range: long-range area SAM ~50–100+ nm, medium ~10–30 nm (ESSM/lasers/EW), and ship self-defense 'leaker' layer at 2–5 nm (RAM/CIWS). Each incoming missile can be shot at across multiple layers, so the tactically interesting number is how many LEAK past each ring, not a single Pk. This maps directly to a go-low kinematic gamble: sea-skimming compresses the outer layers' reaction windows.  *(src: CSBA 'Peeling Back the Layers' / USNI Proceedings 'Layered Air Defense' — csbaonline.org, usni.org)*
- Saturation math is the core mechanic: even a 90% intercept rate leaks 1 of 10 but 50 of 500. Standard USN doctrine is 'shoot-shoot-look-shoot' (SS-L-S), which burns ~2 interceptors per threat; a 96-cell VLS fully tasked to AAW is exhausted by fewer than ~50 anti-ship missiles. Shifting to 'shoot-look-shoot' (S-L-S) halves consumption but needs high interceptor lethality/fast BDA. Magazine depth and shot doctrine are the real currency, not per-shot dice.  *(src: CSBA 'Peeling Back the Layers'; CIMSEC saturation analysis — csbaonline.org, cimsec.org)*
- SM-6 (RIM-174 ERAM): engages high-altitude targets to ~150 nm (~280 km) and sea-skimmers at extended range; active radar homing terminal seeker (derived from AMRAAM) enables autonomous terminal engagement without ship illuminator; Mach ~3.5. Its active seeker is the key differentiator vs SM-2's semi-active homing (which needs a continuous illuminator lock).  *(src: Missile Threat/CSIS SM-6; RIM-174 Wikipedia — missilethreat.csis.org, en.wikipedia.org)*
- SM-2 uses semi-active radar homing — requires the launching ship's illuminator to keep a fire-control radar locked on the target through terminal intercept. This caps the number of simultaneous SM-2 terminal engagements to the number of illuminator channels on the ship, a hard saturation limit. SM-6 and ESSM Block 2 remove this bottleneck via active seekers.  *(src: Aegis Combat System / RIM-162 ESSM Wikipedia — en.wikipedia.org)*
- ESSM Block 2: ~50 km (27 nm) range, dual-mode X-band seeker (active + semi-active). Block 2's active seeker lets it complete terminal intercept WITHOUT the ship's illuminator, breaking the channel limit of Block 1. Quad-packed 4-per-VLS-cell — deep magazine for the medium layer. Reuses Block 1 rocket motor, higher maneuverability.  *(src: Naval News ESSM Block 2; DOT&E FY2022 ESSM report; RIM-162 Wikipedia — navalnews.com, dote.osd.mil)*
- Real engagement envelopes are far smaller than headline range against a low sea-skimmer: an '80 km' SAM may only protect against a low-altitude crosser at ~20–40 km because radar horizon and missile energy at low altitude collapse the intercept geometry. This is the physics justification for the player's go-low tactic and must be modeled as altitude-dependent effective range, not a flat max range.  *(src: Defence-and-Freedom 'Naval air defence of the 2020s' — defense-and-freedom.blogspot.com)*
- RIM-116 RAM: ~9 km range (Block 0/1), up to ~15 km Block 2; Mach 2+; 21-round Mk-144 launcher; passive RF + IR dual-mode seeker (homes on the incoming missile's own seeker/radar emissions in RF mode, IR-only for non-emitters). Autonomous, very fast reaction, engages >4 threats. SeaRAM couples a RAM launcher to a Phalanx-derived radar/EO for a self-contained supersonic sea-skimmer killer.  *(src: RIM-116 RAM Wikipedia; Defence Turkey RIM-116C — en.wikipedia.org, defenceturkey.com)*
- Phalanx CIWS (Block 1B): 20mm gun at 4,500 rounds/min, effective range only ~1–2 nm (couple of miles). Against a Mach 2.5+ sea-skimmer closing at ~0.85 km/s it has a firing window measured in a few seconds; it relies on closed-loop spotting (tracks both target and its own rounds). Last-ditch only; saturation-limited to one target at a time per mount.  *(src: Phalanx CIWS Wikipedia; Defense Industry Daily — en.wikipedia.org, defenseindustrydaily.com)*

## sensors-ew-real: Naval sensors & electronic warfare for a fog-of-war go-low missile-defense sim

- Passive ESM/ELINT detects an emitter at roughly 6x the range that the emitter's own radar detects a target: a common rule-of-thumb pairs emitter-intercept ranges of ~120 nautical miles vs ~20 nm active detection. Because ESM only receives, the emitter never knows it has been detected. Frequency coverage ~0.5-40 GHz (radars mostly 2-18 GHz).  *(src: International Defense Security & Technology (idstch.com) — ESM/ELINT vs LPI radars)*
- EMCON doctrine: the detectable range of any emission is ~twice the emitter's own useful sensor range (propagation asymmetry). Every pulse a ship radiates broadcasts its position at 2x the range it can see. This is why a force stays passive/dark and relies on offboard sensors (AWACS, other ships) to see without being seen. EMCON = tactical suppression of all detectable energy (radar, radio, sonar, IR).  *(src: USNI Proceedings 'In the Digital Age, Make Ships Go Dark' (Aug 2022); itsreleased.com EMCON primer)*
- AESA vs PESA: SPY-1 (PESA) detects a golf-ball target beyond ~165 km, a ballistic-missile-size target ~310 km. SPY-6 (AESA) exceeds ~300 nm (~556 km) and is rated SPY-1 +15 dB = 'detect a target half the size at twice the distance,' plus far more simultaneous tracks. AESA gives graceful degradation (element failures), frequency agility, and lower probability of intercept than mechanically/PESA-scanned arrays.  *(src: missilethreat.csis.org/defsys/amdr; TWZ 'US Navy Getting a Major Radar Upgrade'; Wikipedia AN/SPY-6 & AN/SPY-1)*
- Radar horizon caps sea-skimmer detection: for a ~35 m radar mast vs a ~2 m-altitude target the horizon is ~28-46 km. Skimming altitude is 'almost always below 50 m, often near 2 m.' Warning window is only ~25-60 s. Going lower shrinks detection range: at 5-10 m evasion + sea clutter, effective detection collapses to ~5-10 km and reaction time to ~18-30 s. Supersonic sea-skimmers give ~20-40 s of warning vs ~55-120 s for subsonic.  *(src: Wikipedia Sea skimming; Grokipedia Sea skimming; Defencyclopedia 'How To Shoot Down Anti-Ship Missiles Pt.2')*
- IRST is fully passive (no emissions, no signature added) and detects sea-skimming ASCMs by aerodynamic-heating + exhaust thermal signature at ranges 'exceeding 20-30 km,' with better angular resolution than radar (shorter wavelength) but shorter range and weather/atmosphere attenuation. Systems: Thales ARTEMIS (360deg static), Safran VAMPIR NG, Leonardo DSS-IRST.  *(src: Thales ARTEMIS IRST; Safran VAMPIR NG; Leonardo DSS-IRST; Wikipedia Infrared search and track)*
- Cooperative Engagement Capability (CEC) fuses fire-control-quality tracks from multiple ships/aircraft into one composite picture. Two escalating modes: LAUNCH-ON-REMOTE (fire on another platform's track, but the firing ship's own radar must acquire for terminal), and ENGAGE-ON-REMOTE (missile flies entirely on offboard data; the firing ship's radar never sees the target). This lets a dark shooter kill a target it cannot see, using a distant sensor as eyes.  *(src: US Navy CEC Fact File (navy.mil); FAS CEC page; Wikipedia Cooperative Engagement Capability)*
- Softkill decoy taxonomy (SRBOC Mk36 / SLQ-32): DISTRACTION decoys bloom BEFORE missile lock, outside the seeker's track gate, so the seeker acquires the decoy first; SEDUCTION decoys bloom AFTER lock, inside the track gate, presenting a larger RCS to walk the seeker off the ship; DILUTION spreads multiple false targets. Chaff/IR to ~4 km. SLQ-32/SEWIP auto-detects the ASCM and can auto-fire the Mk36. Timing relative to seeker lock is everything.  *(src: Wikipedia Mark 36 SRBOC; globalsecurity.org MK-36; BAE Systems Mk36 SRBOC)*
- Nulka is a rocket-hovering ACTIVE off-board decoy: an RF repeater on a hovering rocket radiates a large ship-like RCS and flies a programmed path that walks the ASCM seeker away from the ship. Unlike chaff it moves and radiates a coherent false ship, defeating seekers that reject stationary chaff clouds. Fitted to 150+ USN/RAN/RCN ships.  *(src: BAE Systems Nulka; Royal Australian Navy Nulka; Wikipedia Nulka)*

## enemy-platforms

- Type 055 Renhai destroyer: 11,000-13,000 t full load, 112 universal VLS cells (64 fwd + 48 aft) mixing HHQ-9/9B long-range SAM (200+ km), YJ-18 ASCM and CJ-10 land-attack. Dual-band radar: four S-band Type 346B AESA panels (claimed 400+ km detection, ~60% better vs low-observable targets) plus four X-band mast panels. Close-in defense: 24-cell HHQ-10 SAM-CIWS + 11-barrel 30mm H/PJ-11. ASW: 324mm Yu-7 torpedoes, hull + towed + variable-depth sonar. This is a hard-to-saturate, multi-layer picket that sees the player's Oniks salvo far out.  *(src: Wikipedia Type 055 destroyer + Naval-Technology + USNI Proceedings Mar 2023)*
- YJ-18 ASCM is a two-stage threat: subsonic turbojet cruise at ~Mach 0.8 sea-skimming a few meters over water, then a solid-rocket terminal sprint to Mach 2.5-3.0 igniting ~20-40 km from target. Range 220-540 km, 150-300 kg warhead. Derived from Russian 3M-54 Kalibr. The dual-speed profile is explicitly designed to defeat point defenses (short high-speed reaction window) unlike Harpoon's continuous subsonic run. Directly mirrors ONIKS's own Oniks/Zircon go-low DNA but pointed BACK at the player's base.  *(src: CSIS Missile Threat YJ-18 + Wikipedia YJ-18 + USCC report)*
- Arleigh Burke Flight III: AN/SPY-6(V)1 GaN AESA claims 30x sensitivity over legacy SPY-1D, detection/track past 300 nmi (~555 km), can volume-search while continuously fire-controlling. Aegis allocates SM-2/SM-6/ESSM across a raid; SM-6 gives over-the-horizon and terminal ballistic intercept. Design lesson: 'the earlier a destroyer sees and classifies a threat, the more shots-on-goal it creates' - detection lead time directly converts to interceptor allocation depth. A sensor-rich hard target that punishes early emission by the player.  *(src: Wikipedia AN/SPY-6 + TWZ + National Interest (SPY-6 missile hunter))*
- E-2D Advanced Hawkeye / AN/APY-9 UHF AESA: tracks targets past 550 km, purpose-built to detect low-observable AND sea-skimming cruise missiles below 50 m altitude while simultaneously tracking high-altitude/ballistic tracks. Orbits at 25,000+ ft. Feeds Cooperative Engagement Capability (CEC) + Link-16 - distributes FIRE-CONTROL-QUALITY tracks to ships so a destroyer can launch on the Hawkeye's picture without ever emitting itself. This breaks the player's 'go low to hide' gamble: an airborne UHF sensor sees the sea-skimmer the ship's horizon-limited radar can't.  *(src: Lockheed Martin AN/APY-9 + ArmyRecognition E-2D + Airforce-Technology)*
- Diesel-electric SSK on batteries/AIP produces virtually no machinery noise - acoustic signature on par with the quietest SSNs, and can bottom or loiter patrol-quiet for weeks. SSNs by contrast radiate a near-constant signature from continuous reactor coolant pumps that 'will rarely be hidden.' SSKs (1,500-4,000 t) excel in shallow/littoral/congested water where ambient noise further masks them. Clear physics-honest split: SSN = detectable-but-fast persistent threat; SSK = near-silent ambush that appears only when it moves or shoots.  *(src: Maritime Review + DefenseTalks AIP + WION nuclear-vs-diesel)*
- P-8 Poseidon MPA: 490 kt max, 41,000 ft ceiling, mission radius 1,200+ nmi with 4 hrs on-station, air-refuelable. ASW via large sonobuoy load laid in barriers/lines/grids matched to acoustic conditions and likely sub tracks, plus ISAR, ESM, Mk54 torpedoes and HAAWC (high-altitude ASW weapon). Anti-surface: Harpoon + SLAM-ER. A P-8 is the enemy's roving sensor-and-hunter that can localize the player's own submarine assets or vector strikes onto the coast - and it emits ISAR/ESM the player can detect first.  *(src: Boeing P-8 + Wikipedia P-8 Poseidon + ArmyRecognition P-8A)*
- Type 054A frigate: ~4,000 t, 32-cell VLS carrying HHQ-16 medium SAM (up to ~40 nmi / 74 km) AND Yu-8 ASW rockets from the SAME cells; H/LJQ-382 air search + H/LJQ-366 FC radar; one Z-9/Ka-28 ASW helo; 240mm ASW rocket launchers; twin triple 324mm torpedo tubes. A cheaper, numerous escort that fills the ASW screen and adds a medium-range SAM bubble - the 'many mid-tier escorts' layer between corvettes and the Type 055.  *(src: Wikipedia Type 054A + Naval-Technology Jiangkai II + MilitaryFactory)*
- Tarantul/Molniya-class missile corvette (Project 1241): optimized for saturation anti-surface strikes in inshore/territorial water; doctrine explicitly emphasizes NUMERICAL SWARMS over individual survivability to deny littorals to a superior blue-water force. CODAG (diesel cruise + gas-turbine dash) for economical transit then high-speed sprint to launch, reducing exposure on the approach. Sloped superstructure for marginal RCS reduction. Carries supersonic 3M80 Moskit / P-15 in quad launchers. Perfect low-cost swarm attacker that forces the player to spend expensive SAMs on cheap boats.  *(src: Naval-Encyclopedia Tarantul + Grokipedia Tarantul + Wikipedia Tarantul-class)*

## Naval/missile wargame & sim design patterns to borrow for ONIKS (Command: Modern Operations, Sea Power, Cold Waters, Nebulous: Fleet Command, Harpoon, War on the Sea, DCS naval, Modern Naval Warfare) — anchored to real-world missile/sensor/EW numbers

- Sea Power (from the Cold Waters lead designer) builds detection on per-unit RCS (radar cross-section) values against individually-modeled radars whose power output and detection capability determine detection range — hit/miss and detection emerge from modeled sensor physics, not a flat roll. 90% positive over 3,420 reviews. This is the exact 'physics-not-dice' DNA ONIKS already targets, validated commercially.  *(src: Sea Power Steam page / strategyandwargaming.com first impressions)*
- Sea Power EMCON: each unit toggles specific emitters — 'Air search radar (LR)', 'Surface search radar (MR)', 'Active sonar (LF)', towed arrays, decoys. Radiating switches the unit's status label from 'EMCON' to 'Radio Routine'; going fully silent makes the unit 'like a hole in the water'. Activating any sensor reveals your position to the enemy — a persistent risk/reward decision to radiate.  *(src: sea-power.pmctactical.org/emcon.php + Stormbirds hands-on (stormbirds.blog 2024-11-09))*
- Sea Power represents contact uncertainty as a 'circle of uncertainty' on the tactical display: where a contact MIGHT be vs where it is estimated to be. Contacts have distinct certainty tiers (confirmed position vs radar signature vs bearing-only sonar contact). Civilian/neutral traffic deliberately muddles ID; firing on neutrals triggers penalties, forcing verification before firing.  *(src: Sea Power Steam search summary + Stormbirds hands-on (stormbirds.blog))*
- Sea Power uses graduated/dynamic time compression: up to ~100x during transit lulls, auto-throttling to ~30x during engagements, preventing both dead-air waiting and rushed decisions. Tension is built from asymmetric knowledge (seeing the enemy first), the 'Vampire! Vampire!' inbound-missile call giving ~a minute to react, and irreversible fired-missile decisions.  *(src: Stormbirds hands-on (stormbirds.blog 2024-11-09))*
- Command: Modern Operations time control uses discrete time-pulses (run 15s / 1min / 5min / 15min then auto-pause) instead of raw pause/play, explicitly to prevent 'runaway sim'. This gives momentum without losing control at decision points — directly relevant to a 120 Hz fixed-step sim that should never pause.  *(src: command.matrixgames.com UI dev blog (?p=4954) + Wargamer review)*
- Command 'Message Log 2.0' UX patterns: per-unit message aggregation into dedicated windows, type-based color coding (combat/contacts/messages), spatial message balloons that pop up at the exact map location for ~10s when an event fires, and unread highlighting for rapid catch-up.  *(src: command.matrixgames.com UI dev blog (?p=4954))*
- Command models Cooperative Engagement Capability (CEC) / datalink handoff: a missile (e.g. SM-6) can switch its guiding 'datalink parent' mid-flight; AIM-120D can be guided mid-course by an E-2D; Soviet anti-ship missiles receive mid-course updates from aircraft. It also has 'more accurate uncertainty areas for long-range passive detections like SOSUS and ESM,' and when the datalink is jammed/dead, distributed forces degrade. ELINT/passive tracks are bearing-only and ambiguous (no range/motion), and towed arrays have left-right bearing ambiguity.  *(src: command.matrixgames.com (?p=4454 Communications disruption; AI & Mechanics addendum ?page_id=2711) + ELINT/towed-array patents)*
- Cold Waters thermal-layer model: a thermocline (rapid temperature/density drop) creates a shadow zone — a sub below the layer hides from sensors above it and vice versa. Surface wind, waves and rain raise ambient noise and shorten passive detection. Passive listening is the default; pinging active sonar, raising the periscope/mast, or exceeding a cavitation speed threshold all instantly reveal position.  *(src: Cold Waters Steam discussions + killerfish-games.fandom.com Tactics + PC Gamer review)*

## modes-campaign — Mission, scenario, and campaign design for the single-player coastal missile-defense sim ONIKS

- Falcon 4.0's dynamic campaign (still unmatched, per the community) has NO scripted path: missions and the world evolve continuously, driven by an AI campaign engine reading configurable variables, and player behavior feeds back into it. The lesson for an indie sim: a small set of tunable state variables + a mission-tasking loop beats hand-scripted missions for replayability.  *(src: Wikipedia — Falcon 4.0; Mudspike/Falcon-BMS forums)*
- The Falcon BMS Air Tasking Order generates missions off THREAT-THRESHOLD variables (e.g. MaxFlymissionThreat=85, MaxFlymissionHighThreat=100, MinAvoidThreat=40). Missions are bucketed No-Threat / Medium / High-Threat; high-threat areas only get SEAD/DEAD or stealth strikes, and later strike packages unlock only AFTER earlier SEAD missions have driven the local threat score down. This is a mission-prerequisite chain keyed to a computed threat field, not a script.  *(src: forum.falcon-bms.com — 'How to rationalize the Dynamic Campaign engine')*
- Command: Modern Operations scenarios are built entirely from Triggers-Conditions-Actions events (plus optional Lua). Concrete trigger types include 'Unit Enters Area', 'Unit Detected' — and critically the 'Unit Detected' trigger has a 'minimum classification level' criterion so a scenario only fires once the target is classified to a chosen level. Points can be added/deducted per event. This proves a sensor/classification-gated objective system is a shipping, generalizable pattern.  *(src: command.matrixgames.com Scenario Editor addendum; commandlua.github.io)*
- Cogmind ships ~12 permanent 'challenge modes' that are cheap because they reuse the whole game and change ONE rule each: e.g. No-Salvage (destroyed enemies drop only matter, not usable parts), Pure Core (zero inventory), Gauntlet (only the furthest exit is usable), Trapped (10x trap density), Unstable Evolution (upgrades are randomized, player loses build control). Modes can stack for compound difficulty. Design principle: a MODE changes the experience fundamentally by altering a rule; a DIFFICULTY SETTING only scales parameters.  *(src: gridsagegames.com — 'Special Game Modes in a Roguelike Context')*
- Spelunky Daily Challenge = one globally-shared seed per day, one attempt, its own leaderboard scored on money+depth. STRAFE weekly 'Speed Zone' = a locked seed you may re-run all week to optimize a time, but you must kill 90% of enemies before the finish line (a scoring GATE that shapes the whole run). Seeds are cheap to share and turn a physics sim into a competitive, everyone-plays-the-same-fight event.  *(src: Spelunky Wiki (Daily Challenge Mode); Steam — STRAFE Gold Edition)*
- Armoured Commander II (roguelike tank-commander wargame) structures a campaign as Missions -> Days -> hex-map actions. Each DAY hands you a randomly-assigned mission archetype (spearhead assault, pitched battle, fighting retreat) with objective hexes worth extra VP; every action consumes part of the day (a time budget). Two permadeath modes: 'commander dies = campaign ends' vs 'continue, replacing tank/crew'. Crew carry names/history/morale/grit and level up between battles — losses hurt because they're personified and persistent.  *(src: armouredcommander.com; Steam Community ArmCom2 Manual; awargamersneedfulthings.co.uk)*
- FTL's escalation is a literal clock: the Rebel fleet advances one region every jump (an incrementing counter), shading the map red and forcing forward motion — you cannot camp to farm resources. Community critique notes some players feel rushed, so the pressure rate must be tunable. A per-tick 'pressure that punishes stalling' is the core anti-turtle mechanic of the genre.  *(src: FTL Wiki (Rebel Fleet); vigaroe.com FTL analysis)*
- Into the Breach makes tactics a PUZZLE via near-perfect information: enemies telegraph exactly what they'll do next turn, there are no to-hit dice, and you win by repositioning/pushing/sacrificing. Each battle offers optional BONUS objectives that pay distinct resource currencies (Reputation->gear, Reactor Cores->power, Grid points). Failure is reframed as an iterative time-loop, not a dead end. Telegraphed enemy intent + optional secondary objectives = decisions without randomness.  *(src: gamedeveloper.com — 'Reimagining failure...Into the Breach'; jeremiahgames.com 'Perfect Information')*

## maps-environment

- Radar horizon is the dominant limiter for sea-skimmers: a target at ~5 m altitude seen by a radar at ~20-25 m mast height is only detectable at ~19-27 km (combined horizon), NOT the missile's 200-300 km kinematic range. First detection is almost always INSIDE the radar horizon even with an airborne radar present.  *(src: navy-matters.blogspot.com Cruise Missile Characteristics; Grokipedia Sea skimming)*
- Reaction-time math: at Mach 3 sea level a missile covers 27 nmi in ~49 s; a Mach 0.9 cruise missile gives ~90 s from a 25 m mast horizon. Detection-to-impact window is a direct function of (mast height, target altitude, missile speed) — pure geometry + speed, not dice.  *(src: navy-matters.blogspot.com; Grokipedia Sea skimming)*
- Concrete sea-skim altitudes: Exocet 2 m; C-801/C-802 <20 m; P-270 Moskit 20 m cruise / <7 m terminal; P-800 Oniks terminal descent to 10-15 m. Speeds: subsonic Mach 0.75-0.92, supersonic Oniks/BrahMos/Moskit Mach 2-3. Lower altitude = shorter enemy detection range but higher collision/control risk.  *(src: navy-matters.blogspot.com; armyrecognition.com P-800 Oniks; thedefensepost.com NSM)*
- Sea state is a coupled two-edged dial: sea clutter raises the radar noise floor in low-elevation beams (hides your sea-skimmers), BUT in sea state >5 (Beaufort 5+, significant wave height >2.5 m) wave crests force sea-skimmers to climb to avoid collision, introducing control oscillations and raising their exposure. High sea state degrades detection of small fast low-altitude targets for BOTH sides.  *(src: Grokipedia Sea skimming; PMC small sea-surface target detection; NCBI low-altitude clutter detection)*
- Evaporation/tropospheric ducting: strong humidity/temperature gradients in the first few meters over the sea trap radar waves in a surface waveguide, producing k-factors >4 and detection ranges 2-3x normal — occasionally >400 km for low-altitude targets. It is a coastal, weather-driven, semi-predictable anomaly that can suddenly expose or extend low-flyer detection.  *(src: MDPI Joint Inversion of Evaporation Duct; Academia Anomalous Tropospheric Propagation; FIRGELLI Radar Horizon)*
- IR imaging seekers (MWIR/LWIR) are strongly weather- and time-of-day dependent: water vapor/aerosols attenuate and blur; clouds/fog scatter IR; if target-background thermal contrast is ~0 the target is invisible. SWIR ship brightness tracks solar irradiance so dusk/overcast drops ship-water contrast. MWIR favored for long-range in high humidity/maritime; LWIR best in cold low-humidity. Thermal sees through light fog/mist only.  *(src: FLIR thermal through fog/rain; Grokipedia Infrared homing; iNEWS IIR seeker; arXiv LSFDNet SWIR/LWIR ships)*
- Terrain masking is an exploitable geometry, not a flat modifier: missiles hug valleys/ridgelines/coastlines to stay below enemy radar LOS and break continuous track. NSM flies from inland launch, dodges mountains/hills, and flies AROUND landmasses to attack from unexpected bearings; explicitly built for 'straits, fjords and skerries' cluttered littorals.  *(src: thinkdefence.co.uk NSM; wikipedia Naval Strike Missile; wionews BrahMos terrain-masking)*
- Command: Modern Operations models this with SRTM 3-arc-sec (~900 m/cell) terrain giving real LOS where 'terrain can hide you but also block your weapons from firing'; 75 ft antenna over water = 10 nmi radar horizon; IR/visual checks suffer look-down clutter and it is EASIER to see a target over the horizon line than against surface/terrain background. Weather/environment zones are definable per-area.  *(src: command.matrixgames.com Inside the Features; Steam CMO radar discussion)*

## QoL & UX patterns from complex single-player sims for ONIKS: time control, threat-warning, doctrine automation, sensor-uncertainty display, after-action replay, decluttering, and accessibility

- Command: Modern Operations separates time acceleration (1x/2x/5x/turbo dropdown) from precise 'Time Step' buttons that run the sim at the current speed for a fixed interval (15 in-game seconds up to 15 minutes) and then auto-pause. This gives a pause-and-plan loop with a bounded, predictable fast-forward instead of manual pause spamming.  *(src: Command: Modern Operations — Manual Addendum: User Interface (command.matrixgames.com/?page_id=2697))*
- CMO's message log can be configured per-event-type to auto-pause the clock on triggers like 'New Contact', 'New Air/Surface/Submerged Contact', weapon impacts, or BDA changes — each category individually togglable between clock-stopping popup vs silent log entry. This is event-jump auto-warp: the sim runs fast until something tactically relevant happens, then stops itself.  *(src: Command: Modern Operations — Manual Addendum: User Interface; Matrix Games Forums time-mode threads)*
- CMO 'No-Pulse Mode' (Ctrl+Q, on by default) refreshes the map/UI every 0.1s instead of 1s, decoupling render cadence from sim-step cadence for smooth playback at acceleration; a High-Fidelity toggle runs 0.1s slices even at 1x for precision at a performance cost. Fixed-step sims benefit from an explicit render/step decoupling toggle.  *(src: Command: Modern Operations — Manual Addendum: User Interface; Steam CMO WOTY tech discussions)*
- Real radar-warning receivers (ALR-67/ALR-46) present threats in three concentric bands: outer non-lethal (detected but out of range), middle lethal (in range but not tracking), inner critical (locked/launching). Highest-priority threat gets a superimposed 'floating diamond'; fighter locks/launches shown as a 'spike'. Threat proximity to display center = increasing danger, not geographic range.  *(src: Heatblur F-4E RWR manual (f4.manuals.heatblur.se); Wikipedia Radar warning receiver; VTOL VR Wiki RWR)*
- RWR audio is a distinct, learnable alert language: 'new-guy' audio = 3 beeps in 1.5s when a new emitter appears or its PRF changes; launch/'missile' audio = ~7 beeps in 1.5s (1 kHz) when an emitter enters launch state; a slow warble = threat in the critical band, a fast warble = actively engaging you. Audio channel carries state changes so the operator need not stare at the display.  *(src: Heatblur F-4E RWR manual; AN/ALR-67 documentation (openflightschool.de))*
- Aegis implements doctrine-based automation with four escalating modes — manual, semi-auto, auto, and Auto-Special. 'Control by doctrine' lets the operator pre-author rules (by track characteristics) that automate everything from ID to engagement. Auto-Special auto-fires SAMs at a fast anti-ship missile detected in close proximity, explicitly to cut reaction time and human error. This is TEWA (Threat Evaluation & Weapons Assignment) inherited from NTDS.  *(src: Wikipedia Aegis Combat System; Gersh 1987 'Doctrinal Automation in Naval Combat Systems' (Naval Engineers Journal); JHU-APL Aegis AAW Tactical Decision Aids)*
- NEBULOUS: Fleet Command grades every contact on a Track Quality scale TQ15 (near-perfect track) down to TQ1 (nearly unusable), and the fire-control solution quality is gated by TQ. ELINT passively detects enemy emitters out to ~1.25x that radar's own max range: one ELINT module yields a rough line-of-bearing, two produce a crossfix, and ELINT also classifies the emitter type. This makes emission control a two-sided information gamble rendered directly in the track UI.  *(src: NEBULOUS: Fleet Command Official Wiki — Radar & Electronic Warfare (wiki.hoodedhorse.com); Steam NEBULOUS radar guides)*
- NATO/MIL-STD-2525 & APP-6 symbology encodes affiliation redundantly in BOTH shape and color: friend = blue/cyan rectangle, hostile = red diamond, unknown = yellow quatrefoil, neutral = green square. The redundancy is deliberate so the picture stays readable on monochrome/night-vision displays. Within an affiliation, only luminosity varies (hue/saturation fixed). This is a built-in colorblind-safe design pattern.  *(src: Wikipedia NATO Joint Military Symbology; MIL-STD-2525 (nps.edu); Corvus Intelligence 'Symbology engineering for C2 dashboards')*
