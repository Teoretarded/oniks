# Spec 4: Electronic warfare (jamming) — two-sided EW

> Implementation-research spec for a fresh implementer. Read HANDOFF_README.md first for codebase orientation + non-negotiables.

## Summary
A physics-honest two-sided EW layer that plugs into the existing radar/ELINT/commander stack. The enemy fields an EA-18G-class escort jammer ("Growler") orbiting the carrier group; its barrage noise does NOT apply a flat debuff but instead SCALES every player radar's effective detection range per-target by a burn-through factor derived from the open-source J/S geometry (echo power falls as 1/R^4, jam power as 1/R^2 — the jammer wins at long range, the target "burns through" up close), and RAISES the ELINT bearing sigma on real emitters with a noise floor that grows the louder/closer the jammer is. The jammer is itself a fat, always-on ELINT/ARM beacon (it has to radiate to jam): it joins the drone's ELINT emitter list and the enemy datalink, so the player can localize and kill it with HARM/SAM, or simply go passive (drone SAR + ELINT) under the jam corridor. The jammer's own AI reads ONLY sensor state (player emissions + missile tracks): it stations between the fleet and the loudest believed player emitter, lifts the jam when it is RWR/ELINT-localized to deny the geometry, and runs for the carrier when a HARM/SAM track closes. Player counters: a drone-podded escort jammer (collapses enemy SPY-1/AWACS/nose-radar range so a salvo leaks) and a coastal SEAD loitering ARM (the feature_ideas "player anti-radiation munition") that homes the Growler/AWACS emissions. UI surface: a JAMMED band/corridor polygon on the tactical map (shaded wedge from the believed jammer bearing), a RADAR DEGRADED HUD row showing the burn-through range, and a JAM source ELINT marker. Everything is deterministic (seeded child streams), fog-of-war honest (the band is drawn from the SENSOR-believed jammer fix, not truth), and reuses Radar/ElintReceiver/RwrReceiver/EnemyPicture/HarmMissile/SamMissile/Structure with no rewrites. Real-world grounding: standoff/escort jamming, burn-through (crossover) range, J/S ratio — all unclassified radar-tutorial concepts.

**Dependencies:** FOUNDATION FIRST: sim/ew.py (the J/S + burn-through field model) is the keystone — every other feature consumes it; build and calibrate it (tools/probe_ew_burnthrough.py) before anything else. Then: (1) Enemy jammer platform + commander doctrine depends on sim/ew.py + the existing Awacs/EnemyCommander seams (sim/enemy_air.py, sim/commander.py order schema, world/combat.py _execute_commander_order + _step_enemy_air). (2) Radar.detects jammers= kwarg (sim/radar.py) must land with sim/ew.py and stay backward-compatible (default empty => byte-identical to today; ALL existing radar/contacts/defense tests are the regression gate). (3) ELINT sigma elevation depends on sim/ew.noise_floor_at + the ElintReceiver.update signature extension (sim/recon.py), default empty => existing recon determinism tests pass. (4) Player drone pod + player SEAD ARM depend on the field model + the existing ReconDrone, HarmMissile (sim/strike.py, already complete), the Oniks salvo launch machinery (world/combat.py launch()), and new CombatConfig fields (n_jammers, player_jammer, sead_ammo) + CLAMP entries in world/combat_config.py (LOCKED-schema change — needs integrator sign-off per that file's header) + the setup screen (game/combat_setup.py) + tests/test_combat_config.py. (5) UI overlay/HUD row depends on the world publishing self.ew_state each step (world/combat.py) so game/hud.py + game/tactical_map.py read a single source of truth. CROSS-CLUSTER: the JAMMED-band UI should align with the consolidated UI plan (Threat-Warning strip, intel-confidence ladder) since both surface fog-of-war belief; the player SEAD ARM overlaps the 'arsenal' cluster's weapon-select UX (S-300 round select / Zircon select pattern) and should reuse that select-state machinery; determinism uses a NEW seeded child stream tag (e.g. [seed, 8] for EW) that must not collide with the existing tags (defense [seed], spawn [seed,3], recon [seed,4], commander [seed,5], pantsir [seed,6], enemy-radar [seed,7]).

**Open questions:** 1) CALIBRATION: what burn-through collapse should the default Growler produce against the player station's 350 km ship ring at its default standoff — half range? two-thirds? Needs a measured probe + a playtest feel pass (the physics-not-dice memory says measure, don't guess). 2) Does the player EW pod live on the EXISTING recon drone (cheapest, but couples recon and EW into one airframe / one loss) or a SEPARATE EW drone (cleaner doctrine, but the world wiring is single-drone today — DRONE_COUNT note in world/combat.py)? Recommend pod-on-existing-drone for v1. 3) SEAD ARM platform: a new weapon_id on the Bastion TEL (reuses launch() instantly) vs a dedicated SEAD TEL (cleaner thematically, more wiring)? Recommend Bastion weapon_id for v1. 4) Can the player SEAD ARM (110 km HARM range) even REACH the AWACS at 405-435 km, or is it deliberately jammer-only (the jammer orbits closer)? Balance choice — recommend jammer-reachable, AWACS-not (forces the closer-but-killable jammer tension). 5) Multi-jammer dB combination — MIN burn-through (loudest wins) is proposed; confirm that's desired vs an incoherent power sum. 6) Should enemy fighters' nose radars ALSO be burn-through-degraded by the player pod, or only SPY-1/AWACS/ground radars (simpler)? Recommend all radars for consistency since they all route through Radar.detects. 7) LOCKED-schema sign-off: adding n_jammers/player_jammer/sead_ammo to CombatConfig requires the integrator approval the combat_config.py header mandates.


---
## Feature: Enemy escort jammer (EA-18G-class Growler) — barrage standoff jam node  _(effort: L)_

**What it is + real-world grounding:**

An EA-18G-class escort jammer aircraft orbiting the carrier group that radiates a barrage noise corridor in the player radar band. Grounded in open-source standoff/escort jamming theory: barrage mode floods the threat band creating a noise corridor that masks targets within the mainbeam (radartutorial.eu Self-Protection/standoff jamming). It is NOT modelled as a flat radar debuff — its jam power at each player receiver follows the standoff J/S geometry so it degrades range smoothly and is beaten by burn-through up close.

**Platform (launched from / carried by):**

A new airborne platform on the enemy side: a JammerAircraft that subclasses/duck-types the existing Awacs racetrack orbiter (sim/enemy_air.py) — it already has a wide racetrack, altitude/speed model, kill-spiral, flee()/stop_flee(), and a Radar mount. It orbits between the fleet (destroyer screen ~150-170 km) and the player coast, at ~9-10 km alt like the AWACS. Count is armory-driven (config.n_jammers, default 1); it lives in self.enemy_air alongside the AWACS and fighters and is fed/stepped exactly like them in _step_enemy_air.

**Sensors (uses / detected by):**

It carries an RF noise EMITTER (a Radar-shaped object jammer.emitter with emitting=True whenever jamming) that the drone's ElintReceiver and RwrReceiver hear by construction (added to world.combat _emitters() and the RWR radar list). It uses NO offensive sensor of its own for targeting — it reads the EnemyPicture (believed player emitter fixes + missile tracks) to decide WHERE to point its jam and WHEN to lift it. So it is a sensor-DRIVEN, no-truth platform: a giant beacon that detects nothing but is detected by everything.

**AI brain (how the enemy commander uses or counters it):**

A new doctrine branch in sim/commander.py EnemyCommander._doctrine_defend: _defend_jammer(sim_time). Reads ONLY picture state: (a) station the jammer on the bearing from the fleet centroid toward the LOUDEST believed player emitter (the EmitterIntel with highest fix_progress, or the back-plot cluster centroid if no emitter located) so the jam corridor covers the player's eyes — never reads the real radar pos; (b) LIFT the jam (emitter.emitting=False) for a dwell when the jammer believes it is being ELINT-localized or an ARM/SAM track is inbound within JAMMER_THREAT_RANGE_M (same anti-strobe dwell pattern as AWACS EMCON, AWACS_EMCON_DWELL_S); (c) FLEE toward the carrier when a player missile track closes inside the threat range (reuse Awacs.flee()). Emits JAMMER order dicts ({type:'jammer_jam'|'jammer_lift'|'jammer_flee', station_xz, threat_pos}) executed in world.combat _execute_commander_order. Determinism: all decisions from picture + the commander's seeded RNG; no random.random().

**Player UX:**

Mostly a threat to read and counter, not a thing the player operates. The player SEES its effect (JAMMED band on the map, RADAR DEGRADED HUD row, ELINT marker for the jam source once localized) and ACTS: go passive (drone), maneuver the salvo through the corridor edge where burn-through is shorter, or kill it. No new key for the jammer itself — counters (player jammer pod, SEAD ARM) get their own verbs (separate features).

**UI needs:**

Feeds the JAMMED-band map overlay and the RADAR DEGRADED HUD row (separate features below). Needs an ELINT-style 'JAM SRC' marker in a distinct color (e.g. a magenta jagged icon) once the jammer emitter is heard/localized, drawn in tactical_map _elint_overlay alongside the existing emitter circles.

**Game-model mapping (reuse vs add):**

REUSE: Awacs flight model (racetrack, flee, kill spiral) as the base for JammerAircraft; Radar as the emitter mount (emitting flag = jam on/off); EmitterIntel/back-plot in EnemyPicture for the brain's aim; the commander order/execute seam. ADD: a JammerAircraft class in sim/enemy_air.py (or a thin subclass of Awacs with a jam_power_w field and a station_to() that points the orbit), a JammerDef-style constant block (power, band, racetrack anchors) in world/combat.py, and the EW field model in a new sim/ew.py (below). The jammer is NOT a Ship and NOT in self.aircraft — it is enemy_air, fed to the gated player picture as a 'fighter'-class air contact (radar-trackable once the net physically sees it).

**Implementation sketch + test contracts:**

Files: sim/enemy_air.py (new JammerAircraft, ~Awacs subclass; jam_power_w, band, station_to(bearing) that re-anchors the racetrack toward a believed-emitter bearing); world/combat.py (JAMMER_SPAWNS anchors deep behind the screen ~120-180 km, build n_jammers from config in __init__, append to self.enemy_air, add jammer.emitter to _emitters()/RWR list/_enemy_sensor_radars cue, step in _step_enemy_air, route jammer orders in _execute_commander_order); sim/commander.py (_defend_jammer + JAMMER constants + order schema doc). TEST CONTRACTS (tests/test_ew_jammer.py): (1) a JammerAircraft is heard by ElintReceiver and produces a SPIKE/own RWR-equivalent entry; (2) with a located player emitter the commander stations the jammer on the fleet->emitter bearing (assert orbit anchor moves toward that bearing) reading only picture; (3) jammer lifts jam within the dwell when an inbound ARM track is within JAMMER_THREAT_RANGE_M and re-jams when clear, never strobing faster than the dwell; (4) determinism: same seed+picture => identical jammer orders; (5) NO-TRUTH: monkeypatch the real player radar pos far from its EmitterIntel and confirm the station bearing follows the BELIEF, not truth.

**Counters / balance:**

Killable with the player SEAD ARM or an S-300/40N6 shot once localized (it is a fat beacon); neutralized by the player going passive (its jam only hurts ACTIVE player radar — drone SAR/ELINT are immune). Balance lever: jam_power_w and racetrack standoff distance set how far the corridor reaches; lifting-when-localized is the doctrine that keeps it from being a free always-on debuff.

**Risks:**

Over-powered if the corridor blinds the player's whole net permanently — the lift-when-localized dwell and burn-through (targets always visible up close) bound it. Determinism risk if station_to() uses any wallclock; keep it picture+seed only. Perf: one extra airborne entity + one emitter in the ELINT/cue loops is negligible at the existing 0.25-1 s cadences.


---
## Feature: EW field model — burn-through range scaling (physics-not-dice radar degradation)  _(effort: M)_

**What it is + real-world grounding:**

The core physics: a jammer degrades a victim radar by raising its noise floor so the target echo only 'burns through' inside the burn-through (crossover) range. Open-source: echo power ~1/R^4, barrage-jam power at the receiver ~1/R^2, so J/S = const + 40log(D_target) - 20log(D_jammer) (tscm.com burn-through & J/S notes; rfessentials standoff J/S). We translate this into a per-radar, per-target effective-range SCALE: a victim radar's max detection range for a given size class is multiplied by a burn-through factor f(geometry) in (0,1], never a flat subtraction or a dice roll. Outcomes (does the salvo leak? does the SAM get a track?) emerge from where the missile is relative to the burn-through range.

**Platform (launched from / carried by):**

Not a platform — a shared model in a new sim/ew.py used by BOTH sides' detection paths: the player radar net (so the jammer collapses player range) and, symmetrically, the player's own jammer pod (so the player collapses enemy SPY-1/AWACS/nose-radar range). One function, applied wherever Radar.detects is gated.

**Sensors (uses / detected by):**

Operates ON sensors: it wraps the range gate inside sim/radar.py Radar.detects. The function jam_range_scale(radar, target_pos, jammers) computes, for each active jammer with LOS to the radar, its J/S at that radar and the resulting burn-through range, then returns scale = min(1.0, R_burnthrough / radar_max_range) for the loudest jammer. Below burn-through the target is seen (scale keeps it in range); beyond it the radar's effective ring shrinks so far targets drop. ELINT is a separate hook (next feature).

**AI brain (how the enemy commander uses or counters it):**

The enemy commander does not call this directly — it benefits from it: with the player net collapsed the enemy's strike fighters can ingress closer before the player picture forms (the existing HARM/JASSM doctrine becomes more effective for free). The PLAYER jammer pod path makes the enemy SPY-1/AWACS/FighterRadar.detects return False sooner, which the commander already handles (it loses tracks and goes to last-known/back-plot) — no special-casing needed, the no-cheat brain simply sees less.

**Player UX:**

Invisible math, but its consequences are surfaced: the JAMMED band shows the corridor, the HUD shows the current burn-through range ('RADAR BURN-THRU 62 km'), and the player learns that flying a salvo through the corridor edge (where the jammer is farther off-axis -> higher burn-through) or popping the drone to image passively is the answer.

**UI needs:**

The burn-through number per the player's net feeds the RADAR DEGRADED HUD row and the band radius. No new widget beyond those.

**Game-model mapping (reuse vs add):**

REUSE: Radar.ranges (the per-size-class max range dict already there) as the value to scale; HORIZON_K horizon math stays unchanged (jam degrades RANGE, not the curvature). ADD sim/ew.py with: constants (reference jam power, a calibration constant CAL so the default Growler at its default standoff yields a sensible ~half-range collapse against the player station's 350 km ship ring), js_db(radar_pos, target_pos, jammer) and burn_through_range(radar, target_pos, jammers) -> meters, and effective_range(radar, size_class, target_pos, jammers) -> meters. Radar.detects gains an OPTIONAL jammers=() kwarg (default empty -> identical behavior, every existing test passes) and uses effective_range instead of the raw ranges lookup when jammers is non-empty.

**Implementation sketch + test contracts:**

Files: NEW sim/ew.py (the J/S + burn-through math, pure numpy/math, GL-free); sim/radar.py (Radar.detects + RadarNetwork.visible accept jammers=(); when present, gate on effective_range; LOS from jammer to radar required for the jam to count — reuse terrain_blocks so a terrain-masked jammer doesn't jam); world/combat.py wiring (collect active enemy jammer emitters and pass to radar_net.visible in _player_visible; collect the player pod emitter and pass to enemy detectors in _enemy_sensor_radars/_feed_enemy_picture and the defense cue path). KEY: the math must be MONOTONIC and CONTINUOUS (no cliff): burn-through grows as the jammer moves off-axis or farther, shrinks as it closes the radar. TEST CONTRACTS (tests/test_ew_field.py): (1) effective_range == radar_max with no jammer (regression: detects() unchanged when jammers empty); (2) a target INSIDE burn-through is detected, the SAME target just OUTSIDE is not (the cliff is the burn-through range itself, which is the physical contract); (3) MONOTONIC: doubling jammer standoff distance raises burn-through range (less effective), halving lowers it; (4) a target very close to the radar is ALWAYS detected regardless of jam (burn-through floor); (5) determinism: pure function, identical inputs => identical output (no RNG at all in the field model — the only EW randomness is the ELINT sigma draw).

**Counters / balance:**

This IS the counter mechanic to brute-force jamming: burn-through guarantees close targets are always seen (you can never be totally blinded against a leaker that gets close), and the off-axis dependence rewards maneuvering the salvo/drone to the corridor edge. The symmetric player-pod application is the player's offensive use.

**Risks:**

Calibration is the main risk — pick CAL by a measured probe (tools/probe_ew_burnthrough.py: sweep jammer standoff, log burn-through vs the 350 km ship ring) and lock it with a two-sided regression band so balance is reproducible. Avoid double-counting: when multiple jammers are present, take the MIN burn-through (loudest wins), don't sum dB naively into nonsense.


---
## Feature: ELINT bearing-sigma elevation under jamming (degraded passive geolocation)  _(effort: M)_

**What it is + real-world grounding:**

Barrage noise doesn't just hide skin returns — it raises the noise floor at every passive receiver, widening the angular error on bearings taken against REAL emitters (the wanted emitter is now competing with the jammer's broadband floor). Grounded in the same J/S framing: a higher noise floor at the ELINT antenna directly degrades bearing SNR and thus the angular standard deviation. The drone's least-squares triangulation (sim/recon.py) already turns bearing sigma into a position-quality CRLB, so raising sigma honestly worsens the fix — no flat penalty.

**Platform (launched from / carried by):**

Acts on the drone's ElintReceiver (the player's passive geolocation). Primary effect: the enemy Growler widens the player's ELINT sigma. The enemy ESM is a time-accrual model (sim/enemy_strikes.py) with no bearing sigma, so there is no symmetric enemy-side sigma to degrade — the model stays one-directional and simple.

**Sensors (uses / detected by):**

Directly modifies ElintReceiver: the per-bearing gaussian noise draw currently uses the fixed ELINT_BEARING_SIGMA_RAD. Under jamming the effective sigma becomes sigma_eff = base * (1 + k * jam_noise_floor_at_drone), where jam_noise_floor is computed from the same sim/ew.py J/S geometry but evaluated at the DRONE position (the receiver) for each active jammer with LOS. The existing geometry/consistency/range-observability gates in _solve_triangulation then naturally make a noisier fix LESS actionable (longer baseline / more time needed), which is exactly the spec intent.

**AI brain (how the enemy commander uses or counters it):**

The jammer brain's lift-when-localized doctrine interacts here: by widening the player's sigma the jammer slows its OWN localization too (it is a loud emitter the drone is triangulating) — so the commander's choice to keep jamming trades 'blind the player's active radar' against 'get localized and HARM'd'. No extra AI code; it is an emergent tension from the shared field model.

**Player UX:**

The player sees ELINT uncertainty circles (tactical_map _elint_overlay) STAY LARGE / shrink slower while the jam is up, and the ELINT 'n heard' count in the drone HUD may include the jammer itself. The lesson: cross-track the drone harder (longer baseline) to beat the noise, or close the range to the emitters.

**UI needs:**

Reuses the existing ELINT uncertainty circles and bearing rays in tactical_map — they simply read a worse fix_quality. Optional: tint the uncertainty circle when jam is active (a 'JAM-DEGRADED' hue) to teach the player WHY the fix is soft. Feeds the same JAM SRC marker.

**Game-model mapping (reuse vs add):**

REUSE: ElintReceiver bearing-noise draw, _triangulate quality math, the map overlay. ADD: an OPTIONAL jammers/drone-pos argument plumbed into ElintReceiver.update so sigma scales; default empty -> base sigma -> every existing recon test passes unchanged. The jam floor is computed once per ELINT pass in world.combat _step_recon_sensors and passed in.

**Implementation sketch + test contracts:**

Files: sim/ew.py (add noise_floor_at(receiver_pos, jammers) -> scalar in [0, ...)); sim/recon.py (ElintReceiver.update gains jammers=() + the drone is the receiver; the noisy_bearing draw multiplies sigma by 1 + EW_ELINT_SIGMA_K * floor, all seeded via the SAME self._rng so determinism holds); world/combat.py (_step_recon_sensors passes the live enemy jammer emitters to elint.update). TEST CONTRACTS (tests/test_ew_elint.py): (1) jammers=() => byte-identical fix to today (regression on the existing ELINT determinism test); (2) with a jammer up, the SAME bearing geometry yields a LARGER fix_quality (worse) than without — monotone in jam floor; (3) the degraded fix takes MORE distinct cross-track pairs to cross ELINT_FIX_ACTIONABLE_M (assert pair count rises); (4) determinism: same seed + same jammer => identical noisy bearings; (5) lifting the jam restores base sigma on the NEXT pass.

**Counters / balance:**

Player counter is geometry + time (more baseline) and killing the jammer; the jammer pays by being localizable while it radiates. Balance lever: EW_ELINT_SIGMA_K.

**Risks:**

If k is too high the player can never localize anything while jammed — keep k modest and verify with a probe that a determined cross-track still gets an actionable fix in a reasonable time. Must not break the existing carefully-tuned ELINT gates (consistency/geometry/range-observability) — sigma only feeds the noise DRAW, not those gate thresholds.


---
## Feature: Player drone EW pod (self-protect / escort jammer) — offensive use of the field model  _(effort: L)_

**What it is + real-world grounding:**

The player's mirror of the threat: a podded jammer carried by the recon drone (or a separate EW drone) that collapses the ENEMY radar net so a sea-skim salvo leaks under a degraded SPY-1/AWACS picture. feature_ideas.md explicitly lists 'Player decoys / chaff & EW counter-play' and the jammer counter to 'going loud'. Grounded in the SAME burn-through math applied against enemy radars — the player trades stealth (the pod is a loud beacon the enemy localizes and HARMs) for a window where the fleet can't form a clean track.

**Platform (launched from / carried by):**

The existing ReconDrone (sim/recon.py) gains a podded emitter, OR an armory toggle turns one drone into an EW drone. The pod is a Radar-shaped emitter on the drone; when active the drone radiates (loses its 'silent recon' stealth). Armory-bound: config.player_jammer (0/1) and a JAM key to toggle the pod on/off in flight.

**Sensors (uses / detected by):**

When the pod is ON: the drone emitter is added to the jammers list passed to the ENEMY detectors (SPY-1, AWACS, FighterRadar, ground radars) via sim/ew.py effective_range, collapsing their rings; AND the drone becomes a loud emitter on the ENEMY EnemyPicture (it should accrue an emitter fix / be RWR-spiked by the fleet) so the enemy can localize and shoot it. When OFF the drone is the normal passive ELINT/SAR platform. Mutually-exclusive realism: jamming while listening passively is degraded (the pod deafens its own ELINT) — model as raising the OWN drone's ELINT sigma while its pod is hot (reuse noise_floor_at for the own pod).

**AI brain (how the enemy commander uses or counters it):**

The enemy commander reacts via existing doctrine with no new code: a radiating player jammer drone is an EMITTER the EnemyPicture localizes (ESM accrual) and a track the fleet/CAP can engage — the commander's drone-hunt vector + ship SM-2 drone channel already fire on a detected drone, and a SEAD-style response (if added) homes the pod. The brain reads only the sensor picture, so it engages the pod because it is loud, not because it is told.

**Player UX:**

A new JAM toggle key (game/keybinds.py + game/controls.py) active only with the drone platform selected; the drone HUD block (game/hud.py drone_panel_rows) gains a 'JAM ON/OFF' row (amber when hot) and a warning that the pod makes the drone targetable. On the map, the player's OWN jam corridor is drawn toward the fleet (a friendly-tinted wedge) so the player aims it. The core loop: pop the pod, watch the enemy net collapse (their tracks of your salvo stop forming), fire the salvo into the window, toggle off before the SM-6 arrives.

**UI needs:**

Drone HUD 'JAM' status row; a friendly-colored jam corridor wedge on the tactical map (reuse the JAMMED-band renderer with a friendly palette + the drone as origin); a JAM key hint in the F1 overlay (auto via the binding table). A 'POD HOT — DRONE TARGETABLE' hint_flash on toggle-on.

**Game-model mapping (reuse vs add):**

REUSE: ReconDrone, the sim/ew.py field model (same function, enemy radars as victims), the enemy ESM/RWR localization of emitters (the drone emitter joins the enemy's emitter set), the commander's existing drone-engage doctrine, hint/overlay/keybind infra. ADD: drone.pod_emitter (a Radar) + drone.jam_active flag; CombatConfig.player_jammer field + CLAMP; a JAM action in game/keybinds.py ACTIONS; the corridor renderer reuse.

**Implementation sketch + test contracts:**

Files: sim/recon.py (ReconDrone gains pod_emitter + jam_active + set_jam(bool)); world/combat.py (when jam_active, add drone.pod_emitter to the jammers passed to enemy detectors in _enemy_sensor_radars/_feed_enemy_picture/defense cue, and add it to the enemy's emitter-localization + RWR-of-the-fleet so the enemy can find/shoot the drone; raise the drone's OWN ELINT sigma while hot); game/keybinds.py (+ 'jam' action), game/controls.py (toggle on the drone platform), game/hud.py (drone JAM row), game/tactical_map.py (friendly corridor wedge). TEST CONTRACTS (tests/test_player_jammer.py): (1) pod OFF => enemy effective_range == enemy max (regression); (2) pod ON => an enemy SPY-1's effective range against a player Oniks at long range SHRINKS, so a salvo that was tracked is no longer tracked beyond burn-through; (3) pod ON => the drone accrues an enemy emitter fix / becomes RWR-spiked (it is now findable); (4) pod ON degrades the drone's OWN ELINT fix_quality (deafens itself); (5) toggle is deterministic and the key maps through keybinds; (6) NO-TRUTH: the enemy engages the drone only via its sensor detection of the pod emitter, not a truth flag.

**Counters / balance:**

Self-balancing: jamming makes the player loud and killable (SM-6/CAP/SEAD), and deafens his own ELINT, so it is a timed gamble not a free win. The enemy lifting its own AWACS/jammer is the symmetric counter-counter.

**Risks:**

Scope creep vs the enemy jammer — share ALL math in sim/ew.py so there is one model, two callers. Risk that 'jam + go loud' dominates; bound it by making the pod a strong emitter (fast enemy localization) and keeping burn-through honest (the fleet still sees close-in leakers). If the EW drone is a separate airframe, mind the single-drone wiring note in world/combat.py (DRONE_COUNT) — prefer a pod on the existing drone first.


---
## Feature: Player coastal SEAD loitering ARM — anti-radiation counter to the jammer/AWACS  _(effort: M)_

**What it is + real-world grounding:**

The dedicated kill answer to a loud jammer/AWACS that lifts-when-localized: a player anti-radiation loitering munition (feature_ideas.md 'Player anti-radiation loitering munition (HARM-equiv) — punishes a silent-when-threatened AWACS/jammer'). It launches from the coast, lofts toward the believed emitter bearing, and homes on the live emissions — if the emitter goes dark it reverts to the last-known point with a CEP miss ring. This is the mirror of the enemy HarmMissile already in sim/strike.py, so the physics already exist.

**Platform (launched from / carried by):**

A player coastal ARM launcher — cleanest reuse: add it as a selectable weapon on the existing Bastion TEL battery (a new weapon_id alongside oniks/zircon) OR a small dedicated SEAD TEL near the S-300 site. Armory: config.sead_ammo. It fires from the player base coordinates like the Oniks salvo, so it slots into the existing launch()/tube machinery.

**Sensors (uses / detected by):**

It is CUED by the player's own ELINT fix: the player selects a believed emitter (the jammer's or AWACS's ELINT marker / JAM SRC marker on the tactical map) and fires; the round is built as a HarmMissile (sim/strike.py) targeting that enemy Radar/jammer emitter object. The round homes on emissions while the emitter is alive+emitting; on silence it freezes the last-known aim + draws the deterministic HARM_MISS ring — identical to the enemy HARM model, just is_hostile=False.

**AI brain (how the enemy commander uses or counters it):**

This pressures the enemy jammer/AWACS brain: the jammer's lift-when-ARM-track-inbound doctrine (feature 1) is precisely the counter to this weapon — and lifting blinds the jam, which is the player's goal even on a miss. So the player ARM forces a lose-lose on the enemy: keep jamming and eat the ARM, or lift and let the salvo through. The enemy brain reads the inbound ARM as a missile track (already in EnemyPicture) — no truth.

**Player UX:**

With the drone/ELINT having localized the jammer (JAM SRC marker), the player TAB-selects a SEAD weapon, clicks the emitter marker on the tactical map, and SPACE-fires. The round shows on the map as a friendly missile; the HUD flight block shows its phase (the existing StrikeMissile phase_label). A hint teaches 'ARM: needs an ELINT-located emitter' if fired with no emitter cued.

**UI needs:**

A SEAD weapon select state (mirrors the S-300 round select / Zircon B-select): a HUD launcher row + tactical-map ring/label for the ARM. Clicking an ELINT/JAM-SRC marker as the ARM target (tactical_map _click_target gains an 'emitter target' path when the SEAD weapon is active). A 'CUE EMITTER' affordance on the map.

**Game-model mapping (reuse vs add):**

REUSE: HarmMissile (sim/strike.py) verbatim for the flight + silence-miss physics; the Oniks salvo tube machinery (world/combat.py launch()) for firing; the StrikeDef HARM arsenal entry (sim/arsenal.py) — possibly a player-tuned PLAYER_ARM StrikeDef; the ELINT marker as the targeting source. ADD: a player ARM weapon_id, config.sead_ammo + CLAMP, an emitter-target click path, the SEAD weapon-select UI state.

**Implementation sketch + test contracts:**

Files: sim/arsenal.py (a PLAYER_ARM StrikeDef if tuning differs from HARM, else reuse HARM); world/combat.py (launch path for the ARM that constructs a HarmMissile(target_radar=<selected enemy emitter>, rng=seeded child) with is_hostile=False; the existing HarmMissile._fuse_check already sets the hit emitter's radar.alive=False, and the mirror structure-sweep already excludes SamMissile so no extra damage wiring is needed); game/keybinds.py + game/controls.py (SEAD select + fire); game/hud.py + game/tactical_map.py (ARM status + emitter-target click). TEST CONTRACTS (tests/test_player_sead.py): (1) firing the ARM at a live emitting enemy jammer kills it (HarmMissile fuse -> emitter.alive False) — reuses the proven HARM fuse path; (2) the SAME shot at an emitter that goes silent misses by the HARM_MISS ring (emitter survives) — the silence-survives contract; (3) determinism: seeded miss offset identical per seed; (4) the ARM cannot be fired without a cued enemy emitter (returns None + hint); (5) the round is is_hostile=False so it never damages the player base sweep.

**Counters / balance:**

Countered by the enemy lifting emissions (silence-survives) — which is itself the player's win (jam down). Balance: scarce sead_ammo so the player can't spam SEAD; the loft/range of the ARM (reuse HARM 110 km) gates whether the deep AWACS (orbits 405-435 km) is reachable vs only the closer jammer — a deliberate 'the jammer comes closer so it's killable, the AWACS stays deep' tension.

**Risks:**

Targeting UX complexity (selecting an emitter vs a contact vs a coordinate) — keep it explicit: SEAD weapon active => clicks resolve to ELINT/JAM-SRC emitter markers only. Don't let the ARM home on truth — it must target the EMITTER object (Radar) exactly like the enemy HARM, and the player only knows WHERE to aim from his own ELINT fix (fog honest).


---
## Feature: JAMMED-band map overlay + RADAR DEGRADED HUD row (EW UI surface)  _(effort: M)_

**What it is + real-world grounding:**

The mandatory player-legibility layer: a JAMMED corridor/band on the tactical map and a degraded-radar readout on the HUD, so the invisible J/S math becomes a readable tactical picture. ui_reference.md demands high-quality, instrument-style UI (Nuclear Option thin overlays, amber/cyan/red semantics) and 'live data in chrome'. The band is drawn from the SENSOR-BELIEVED jammer location (fog honest), not truth.

**Platform (launched from / carried by):**

UI only — renders on game/tactical_map.py (the band) and game/hud.py (the row). Reads world state: the player's effective burn-through range (from sim/ew.py against the player net) and the believed jammer bearing/fix (from the drone ELINT marker, or 'bearing only' if not yet localized).

**Sensors (uses / detected by):**

Sourced entirely from PLAYER sensors: the jam corridor wedge is anchored at the believed jammer ELINT fix (or, before a fix, drawn as an open bearing wedge from the RWR/ELINT bearing of the jam emitter — a 'jam strobe' like a real RWR). The burn-through ring is the player net's effective_range under jam. If the player has NO sensor on the jammer at all, the band is absent (you feel the degraded range via the HUD row but can't place the source — exactly the fog-of-war intent).

**AI brain (how the enemy commander uses or counters it):**

None directly; it visualizes the consequence of the enemy jammer AI. The enemy lifting the jam makes the band fade — a readable tell that the player's SEAD/closing pressure worked.

**Player UX:**

The player reads: a translucent magenta/red wedge spanning the jam corridor on the map (origin = believed jammer, width = a fixed beamwidth, length = to the map edge), the player net's shrunken effective ring drawn as a dashed circle (vs the normal solid range ring), and a HUD row 'RADAR BURN-THRU 62 km' (amber) or 'NET DEGRADED' when collapsed. As the player kills/closes the jammer the wedge narrows/fades. This directly teaches the corridor-edge and burn-through tactics.

**UI needs:**

NEW map overlay method tactical_map._jam_overlay (wedge polygon via draw_lines + a faint fill via draw_rect, in the existing ELINT magenta family); NEW HUD row via a pure helper game/hud.radar_jam_row(world) -> (label, value, color) added to the bastion/s300 blocks next to radar_status_row; palette tokens from ui_reference (DANGER red / WARN amber / a magenta EW accent). All draw_text/draw_lines/draw_rect only — no images/gradients (engine constraint).

**Game-model mapping (reuse vs add):**

REUSE: tactical_map _elint_overlay drawing patterns (rays + circles), the range-ring renderer (_rings) for the dashed degraded ring, the HUD row helper pattern (radar_status_row/pantsir_status_row are the exact template — pure, unit-testable), the ELINT fix as the band origin. ADD: hud.radar_jam_row, tactical_map._jam_overlay, EW palette constants.

**Implementation sketch + test contracts:**

Files: game/hud.py (radar_jam_row pure helper + call it in _bastion_block/_s300_block; returns None when no jammer is active so non-EW worlds/SANDBOX are unaffected); game/tactical_map.py (_jam_overlay called from draw(); reads world.ew_state — a small dict the world publishes each step: {burn_through_m, jammer_bearing, jammer_fix_xz_or_None, active}); world/combat.py (publish self.ew_state from the field model each step so the UI never recomputes physics). TEST CONTRACTS (tests/test_ew_ui.py, headless/pure): (1) radar_jam_row returns None with no active jammer, an amber row with one; (2) the burn-through value in the row matches sim/ew.effective_range for the player net (single source of truth); (3) _jam_overlay band geometry is computed from the BELIEVED fix (assert it uses world.ew_state.jammer_fix, not a real jammer pos) — fog-of-war contract; (4) with a bearing-only (un-localized) jammer the overlay draws an open wedge (no closed origin circle); (5) pure helpers stay GL-free and import headless (matches the locked tactical_map/hud test convention).

**Counters / balance:**

It is the readability that makes every other EW feature fair (the feature_ideas Threat-Warning-strip philosophy applied to EW). No balance lever of its own.

**Risks:**

Don't draw the band from truth (a common shortcut) — it MUST read the player's belief or it leaks the jammer's exact position for free. Keep the wedge cheap (a handful of draw_lines) to respect the GL-overlay budget; avoid tiling/fills beyond the one faint corridor rect.
