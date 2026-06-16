# Spec 1: Anti-radiation warfare (SEAD/DEAD): player ARM, enemy ARM-vs-player-emitters, and ARM countermeasures

> Implementation-research spec for a fresh implementer. Read HANDOFF_README.md first for codebase orientation + non-negotiables.

## Summary
The codebase already contains 90% of the anti-radiation machinery, just wired one-directionally. sim/strike.py HarmMissile is a complete, deterministic passive-radar homing seeker: it PN-homes on any sim.radar.Radar object, freezes the last-known aim + draws a seeded CEP miss-offset ring (HARM_MISS_MIN/MAX_M = 150-400 m) when the emitter goes silent, and re-locks on re-emission. The enemy side fully uses it: EnemyCommander._doctrine_blind (sim/commander.py) reads sensor-only EmitterIntel (ESM fix accrued in EnemyPicture.update_emitter), schedules a 2-ship HARM package, and world/combat.py _launch_strike_package(sead=True) rolls fighters that emit-silent ingress, pop their nose radar at HARM_POPUP_RANGE_M, and release true HarmMissiles homing on self.radar_station. The player has the SYMMETRIC sensors already: self.elint (drone ElintReceiver) physically HEARS every enemy emitter listed by _emitters() (ship SPY-1, AWACS, enemy ground radars) with full triangulation, but _inject_elint_tracks only surfaces SHIP fixes — enemy radars are heard and never turned into a targetable fix.

So the cluster is four features: (1) PLAYER ARM — a Kh-31P-class ramjet anti-radiation round (open-source grounded: Mach 3+, 110 km, 600 kg, 87 kg warhead, solid-boost-then-ramjet — mirrors the Oniks WeaponDef ramjet architecture AND reuses HarmMissile homing) fired from the Bastion TEL via the existing B weapon-select, homing on a player-picked enemy emitter; (2) an EMITTER FIX CHANNEL surfacing heard enemy radars as selectable contacts (the missing half of the existing ELINT pipeline); (3) ENEMY ARM EXPANSION so wild-weasel HARM targets the player's NEW emitters (Pantsir radars, the ARM pop-up illuminator, a decoy emitter) not just the radar station; (4) ARM COUNTERMEASURES — shoot-and-scoot (mobile TELs/radar, currently a hard gap — every player emitter is at a fixed pin) + a deployable decoy emitter that the existing HarmMissile silence/relock logic and the commander's belief model already support physically. Every targeting decision on both sides routes through sensor-derived emitter belief (EmitterIntel / EnemyPicture on the enemy, ElintReceiver fix + known_enemy_sites on the player), never ground truth, preserving the fog-of-war contract. Outcomes are physics: a back-plot/ELINT error beyond the silence-CEP puts the round in the dirt; silence degradation is the seeded CEP ring, not a Pk roll.

**Dependencies:** CROSS-CLUSTER / ORDERING: Feature #2 (emitter ELINT fix channel) is a prerequisite for Feature #1 (player ARM) — the player needs a selectable enemy-emitter contact before an ARM has anything to target; build #2 first or together. Feature #1 reuses sim/strike.py HarmMissile UNCHANGED (must already exist — it does) and sim/arsenal.py StrikeDef + the STRIKES registry; the render path depends on game/sandbox.py _missile_mesh_key + DEDICATED_MISSILE_IDS and models/missiles.py (the build_kh31p mesh, paralleling build_harm). Feature #3 (enemy ARM vs new emitters) depends on Features #1/#4 actually EXISTING new emitters to hunt (the ARM pop-up illuminator from #1, Pantsir radars already in self.radar_net, the decoy from #4) AND on world/combat.py _feed_enemy_picture being extended to feed all player emitters into commander.picture; it reuses the existing _launch_strike_package(sead=True) + _doctrine_blind + EmitterIntel/mark_emitter_destroyed machinery. Feature #4 (countermeasures) depends on Feature #3 being smart enough that scoot/decoy MATTER (an enemy that only ever hits the radar station gives the player nothing to defend with mobility/decoys). MUST-EXIST-FIRST shared infra all four touch: the EnemyPicture/EmitterIntel sensor-only belief model (sim/commander.py) and the player ElintReceiver pipeline (sim/recon.py + world/combat.py _emitters/_inject_elint_tracks) — both already built and tested; this cluster extends, never rewrites them. Determinism: every new RNG (player ARM miss-offset, any decoy/displace stochasticity if added) must be a seeded child stream off the world seed with a NEW phase tag not colliding with defense[seed]/recon[seed,4]/commander[seed,5]/pantsir[seed,6]/enemy-radar[seed,7] — reserve e.g. [seed, 8] for player-ARM. Recommended build order: #2 -> #1 -> #3 -> #4. CONSOLIDATED UI (feeds the project's UI plan): an EMITTER/SIGINT picture layer on the tactical map (emitter glyphs + ELINT uncertainty rings + selection), a 3-way Bastion weapon strip (ONIKS|ZIRCON|KH-31P) in HUD+map chrome, an in-flight ARM seeker-state readout, an EMITTER-THREAT/RWR panel (which player emitters are believed targeted, time-to-impact), per-emitter EMCON/DISPLACE status, and a decoy deploy+stock panel.

**Open questions:** (1) Player ARM platform: Bastion TEL via B-cycle (recommended — reuses all tube/salvo/magazine plumbing) vs a dedicated coastal ARM TEL/structure (more realistic SEAD site, but a whole new launcher+render+structure for v1)? I assumed Bastion-TEL reuse. (2) Player ARM class: model KH31P as a StrikeDef (reuses HarmMissile flight machine directly — recommended, parallels enemy HARM exactly) vs a WeaponDef ramjet (truer to the Kh-31 ramjet but HarmMissile expects StrikeDef fields)? I assumed StrikeDef. (3) Should the player ARM reach the AWACS at all (405-435 km orbit vs 110 km ARM range)? Options: leave it out-of-reach unless the AWACS is dragged in (realistic, current assumption), add a longer Kh-58U-class variant (250 km), or a forward drone-relay launch. (4) Decoy value-tuning: how attractive should a decoy be to the enemy brain relative to the real radar — needs a balance pass / two-sided regression once #3 exists. (5) Shoot-and-scoot fidelity: discrete pre-surveyed jumps (assumed, bounded scope) vs continuous mobility (large change)? (6) Does the existing ARM fuse-kill path flip the enemy ground-radar STRUCTURE (for victory credit) or only the Radar object? Needs verification — the enemy_structure death currently drives Radar.alive via on_destroyed, but the ARM kills Radar.alive directly; the reverse link may be missing. (7) Should the player gain a per-Pantsir-radar EMCON toggle (needed for #4's emitter-level shoot-and-scoot) or is the single radar-station R toggle sufficient for v1?


---
## Feature: Player anti-radiation missile (Kh-31P-class) fired from the Bastion TEL  _(effort: L)_

**What it is + real-world grounding:**

A player SEAD round that homes passively on an emitting enemy radar. Open-source grounding: Kh-31P/PD (Zvezda) — solid-boost to Mach 1.8 then ramjet to ~Mach 3-4.5, range up to 110 km, launch mass ~600 kg, 87 kg penetrating warhead, INS + broadband passive radar seeker (https://en.wikipedia.org/wiki/Kh-31, deagel.com/Offensive Weapons/Kh-31). This is the natural player counterpart to the enemy AGM-88 HARM already in sim/arsenal.py, and its solid-then-ramjet architecture mirrors the existing Oniks WeaponDef so the physics are honest and the codebase already models them. Add as a new arsenal entry KH31P (a StrikeDef like HARM, OR a WeaponDef variant; see game_model) so it can reuse the HarmMissile flight machine. Mach 3 / 110 km makes it a real SEAD tool: it can reach the AWACS only if the orbit is dragged in or with a forward drone-relay, can punish a destroyer SPY-1, and one-shots a soft radar (HP_RADAR_STATION=1).

**Platform (launched from / carried by):**

Launched from the existing Bastion TEL tube (sim/arsenal.py BASTION launcher), selected via the EXISTING B 'oniks_weapon' cycle extended to a 3-way oniks->zircon->kh31p (game/sandbox.py cycle_oniks_weapon). The TEL already supports per-tube salvo + finite magazine; the ARM draws from its own scarce pool (config.kh31p_ammo, like Zircon's _zircon_ammo). Rationale for reusing the Bastion TEL rather than a new launcher: the TEL tube/reload/salvo plumbing (_oniks_tubes, _build_oniks_battery, launch()) is already built and tested; a dedicated coastal ARM site is possible later but adds a whole launcher+structure+render path for v1. The round is land-attack class (StrikeMissile lineage), so it must carry is_hostile=False (it is a PLAYER round — the class default on StrikeMissile is is_hostile=True, which would let it hit the player base in the structure sweep; MUST override per-instance/subclass).

**Sensors (uses / detected by):**

Homes on a sim.radar.Radar object via the existing HarmMissile passive seeker (PN on the live emitter while it emits; freeze last-known + seeded CEP ring 150-400 m on silence; re-lock on re-emission). To PICK that emitter the player uses the drone-borne ElintReceiver (sim/recon.py) which already hears the enemy SPY-1/AWACS/ground radars via world/combat.py _emitters(); the player RWR is drone-side. Detection of the ARM by the enemy: it is radar-gated like Tomahawk/JASSM (StrikeMissile.launch_warning=False, radar_size='missile'), so the enemy commander only sees it once a destroyer/AWACS radar physically detects it — and an enemy radar that goes silent to defeat the ARM stops feeding the EnemyPicture, the same tradeoff the player faces.

**AI brain (how the enemy commander uses or counters it):**

Targeting is PLAYER-driven (the player picks the emitter from the contact/ELINT picture), so no enemy-AI use here — but the ENEMY brain COUNTERS it without cheating: EnemyCommander / the per-entity radar-silence logic already reads only sensor state. When the player ARM track is held in EnemyPicture.missile_tracks within a threat radius of an emitting radar, that radar (AWACS via _defend_awacs EMCON dwell, ship via _defend_ship_radars, and NEW: enemy ground radar) goes silent — which is exactly what degrades the live HarmMissile to its seeded CEP ring. This must trigger off the SENSED missile track, never the ARM's true position. New: extend _defend_ship_radars / add _defend_ground_radars so a sensed inbound ARM-class track (tag the track type via the existing strike-board feed) silences the threatened emitter, mirroring the AWACS EMCON.

**Player UX:**

B cycles Bastion round to KH31P (HUD hint 'KH-31P ANTI-RADIATION SELECTED'). On the tactical map the player LMB-selects an enemy EMITTER contact (surfaced by feature #2) — a new contact subclass shown with an emitter glyph + ELINT uncertainty ring (the _elint_overlay circle already exists). SPACE launches (request_launch routes a new active branch: if oniks_weapon=='kh31p', require a selected emitter contact, else HINT_ARM_NO_EMITTER). HUD shows ARM stock + a 'SEEKER: TRACKING / SILENT (CEP)' state read off the live round's HarmMissile aim mode so the player sees when a target shutdown spoiled the shot. Range/fuel hint mirrors the Zircon out-of-envelope warning (HINT_ARM_RANGE if emitter beyond 110 km).

**UI needs:**

(a) Emitter contact glyph + selection on the tactical map (diamond-in-ring, distinct from ship/air contacts) with the ELINT fix-error ring (reuse _elint_overlay). (b) Bastion 3-way weapon strip in HUD + map chrome (game/hud.py + tactical_map _chrome): ONIKS | ZIRCON | KH-31P with the selected one lit and stock counts. (c) In-flight ARM seeker-state readout in the HUD flight block ('ARM SEEKER: LOCK' / 'ARM SEEKER: SILENT — CEP' / 'ARM: MEMORY') from the round's _aim mode. (d) An RWR-style 'EMITTER LOCALIZED' cue line when a fresh actionable enemy-emitter fix lands (the new emitter fix channel).

**Game-model mapping (reuse vs add):**

REUSE sim/strike.py HarmMissile verbatim for flight+homing (it is emitter-agnostic — takes any Radar). ADD arsenal KH31P: cleanest path is a StrikeDef (parallels HARM exactly: booster_thrust/time for the solid boost, max_thrust/isp for the ramjet sustain, cruise_alt for a sea-skim-then-loft or a flat M3 ingress, max_range=110_000, fuse_radius~10 m, warhead_mass=87). Register in STRIKES. The render mesh: add build_kh31p() to models/missiles.py and register 'kh31p' in game/sandbox.py _missile_meshes + DEDICATED_MISSILE_IDS so _missile_mesh_key routes it (Kh-31 has the distinctive 4 mid-body ramjet intakes — visually separable from the slim HARM). World wiring: a new CombatWorld.launch_arm(emitter_id) mirroring launch_sam — resolve emitter_id -> the live Radar (from a new self._player_targetable_emitters() = ship SPY-1 + AWACS + enemy ground radars), spawn HarmMissile(KH31P, tube_pos, vel0, target_radar=that_radar, rng=child stream off [seed, ARM_TAG]); MUST set m.is_hostile=False and m.launch_platform so it never OBB-hits the player base and feeds the ENEMY picture as a player round. The enemy-airfield/radar structure sweep (apply_missile_hits_structures vs self.enemy_structures) already runs player rounds against enemy structures — the ARM fuse kill calls target_radar.alive=False AND the swept warhead detonation kills the co-located enemy_structures radar (the radar Radar object and its Structure share a pos; the existing on_destroyed seam clears Radar.alive when the Structure dies — verify the ARM fuse-kill path also flips the Structure, or route the kill through the structure sweep using a small fuse OBB).

**Implementation sketch + test contracts:**

Files: sim/arsenal.py (add KH31P StrikeDef + register in STRIKES; ~30 lines with derivation comment like HARM). sim/strike.py (HarmMissile reused as-is; if a player ARM needs is_hostile=False, add a small PlayerArmMissile(HarmMissile) subclass with is_hostile=False, or set the flag on the instance in launch_arm). world/combat.py: add _player_targetable_emitters() and launch_arm(emitter_id); extend _arm_magazines for kh31p_ammo; route the ARM kill into the enemy structure death. game/sandbox.py: extend cycle_oniks_weapon to 3-way; request_launch ARM branch; register build_kh31p mesh + DEDICATED_MISSILE_IDS. models/missiles.py: build_kh31p(). game/hud.py + game/tactical_map.py: weapon strip + emitter selection + seeker readout. game/keybinds.py: no new key (reuse B). TEST CONTRACTS (tests/, headless, no GL): test_kh31p_def_envelope — KH31P.max_range==110_000 and the round flown vs an emitter at 90 km kills it, vs one at 130 km falls short (physics envelope, not a gate). test_player_arm_homes_emitter — HarmMissile(KH31P,...,target_radar) fused within fuse_radius of an EMITTING radar -> radar.alive False; deterministic across two runs same seed. test_player_arm_silence_cep — radar set emitting=False before terminal -> round impacts within HARM_MISS_MIN..MAX of last-known and the emitter SURVIVES (seeded, repeatable). test_player_arm_relock — silence then re-emit before terminal -> miss offset cleared, emitter killed. test_arm_not_hostile — a KH31P overflying a player TEL never registers a base hit (is_hostile False through apply_missile_hits_structures). test_launch_arm_requires_emitter — launch_arm(None/unknown) returns None; valid emitter returns a round and decrements kh31p_ammo.

**Counters / balance:**

Balance + the physics/fog contract: the ARM is countered by EMCON (a radar that goes silent before the round's terminal phase survives with the seeded CEP ring — the HarmMissile silence logic already enforces this; outcome EMERGES from when the enemy AI silences, not a roll). It is range-limited (110 km can't reach a deep AWACS orbit at 405-435 km unless the orbit is dragged in by a drone threat, or with a forward relay — a real tension). Scarce magazine (config.kh31p_ammo small). The enemy's NEW counter is the sensed-track-driven radar silence in feature #3's ai_brain. Determinism: the miss-offset rng is a child stream off the world seed [seed, ARM_TAG], never colliding with defense/recon/commander/pantsir streams.

**Risks:**

(1) StrikeMissile.is_hostile defaults True — forgetting the override would let the player ARM demolish the player base (a hard bug; locked by test_arm_not_hostile). (2) The ARM fuse kills target_radar.alive but the co-located enemy_structure (the Structure giving victory credit) may not flip — must route the kill so the enemy ground radar's Structure dies too (existing on_destroyed seam is Structure->Radar, the ARM needs Radar-or-Structure->both). (3) M3 ramjet on the StrikeMissile machine: the StrikeMissile speed controller (KP_THRUST/THRUST_SCALE) is tuned for subsonic cruise — a Mach 3 cruise_mach may need the same drag-feedforward saturation check the Oniks uses; verify the round actually reaches M3 in a flyoff probe (tools/, like the s300 flyoff) before locking the envelope test. (4) Emitter selection UX must not collide with ship/air contact picking on the map.


---
## Feature: Enemy-emitter ELINT fix channel (surface heard enemy radars as targetable contacts)  _(effort: M)_

**What it is + real-world grounding:**

The missing half of the existing player ELINT pipeline. Today self.elint (drone ElintReceiver) physically HEARS every enemy emitter that _emitters() lists (ship SPY-1, AWACS, enemy ground radars) and fully triangulates them (fix_quality/est_pos with the CRLB geometry gate), but world/combat.py _inject_elint_tracks ONLY maps a heard emitter_id back to a SHIP (by_emitter = {s.radar.radar_id: s for s in self.ships}) — so AWACS and enemy ground-radar fixes are computed and discarded. This feature surfaces them as a distinct EMITTER contact the player can select for the ARM (and that sharpens with drone cross-track baseline, exactly like the ship ELINT today). Grounded in real coastal-defense SEAD doctrine: you locate the emitter passively before you shoot the radiation-homer — the spec's whole 'recon pierces fog' loop.

**Platform (launched from / carried by):**

No new platform — rides the existing drone ElintReceiver + the player ContactBoard. The emitter belongs to whatever enemy platform carries the radar (AWACS airframe, enemy ground-radar Structure, destroyer). Knowledge is fog-gated: an emitter only appears once it has been HEARD and the fix is actionable (ELINT_FIX_ACTIONABLE_M), and a SILENCED emitter's fix stops refreshing and the contact ages out (last_heard + ELINT_FRESH_S — already the ship-fix behavior).

**Sensors (uses / detected by):**

Pure passive ELINT (drone ElintReceiver) — the triangulation, consistency gate, geometry gate and range-observability gate already exist and are well-tested. The only change is the back-mapping: a heard emitter_id that is NOT a ship is mapped to an AWACS / enemy-radar contact id instead of being dropped. Also wire the player RWR-equivalent so an emitting enemy radar that is illuminating the drone shows a SPIKE bearing the player can act on (RwrReceiver already produces this; surface it as a coarse emitter cue even before triangulation converges).

**AI brain (how the enemy commander uses or counters it):**

N/A directly (this is the PLAYER's intel surface), but it is the fog-of-war-honest input to the player ARM: the player acts on the SENSED emitter fix (with its uncertainty ring), so an ARM fired at a stale/low-quality fix can miss for geometry reasons — symmetric to how the enemy commander acts on its own EmitterIntel ESM fix. No truth read: the contact carries the triangulated est_pos, not the real radar pos.

**Player UX:**

New emitter contacts on the tactical map (diamond-in-ring glyph) labeled by kind (AWACS / GND RADAR / SPY-1), drawn with the live ELINT uncertainty ring (radius = fix error, shrinking as the drone builds baseline — _elint_overlay already draws this for any heard emitter). Selecting one sets it as the ARM target (feature #1). A HUD 'EMITTER LOCALIZED' latch line when a fresh actionable fix appears. An emitter contact that goes stale (silenced) fades and drops like any aged track.

**UI needs:**

Emitter-class contact rendering + selection in game/tactical_map.py (a third contact category beyond ship/air); a legend entry; the localization cue line in game/hud.py. This directly serves the project's 'more, high-quality UI' goal: a passive-SIGINT picture distinct from the active-radar picture.

**Game-model mapping (reuse vs add):**

Generalize _inject_elint_tracks: build emitter_source = {radar_id -> (kind, owning entity/structure)} across ships + AWACS + enemy ground radars (the same set _emitters() already builds), and inject an actionable, fresh fix as a contact track keyed on the emitter_id with a new is_emitter=True / kind field (the ContactBoard.tracks dict already carries arbitrary keys; add 'is_emitter' alongside 'is_air'). Reuse the existing ELINT error->age mapping (ELINT_AGE_MAX_S) so the contact sharpens/fades on the one staleness axis. The ARM's launch_arm(emitter_id) resolves the SAME emitter_id back to the live Radar.

**Implementation sketch + test contracts:**

Files: world/combat.py (_inject_elint_tracks generalized + a _player_targetable_emitters() helper shared with launch_arm; ~40 lines). game/tactical_map.py (emitter contact glyph + pick path; reuse pick_contact with an emitter filter, ~50 lines). game/hud.py (cue line). TEST CONTRACTS: test_elint_surfaces_awacs_emitter — with the drone holding a converged AWACS fix, world.contacts.tracks contains an is_emitter track for the AWACS radar_id with est within fix error of truth; deterministic. test_elint_emitter_ages_out — silence the emitter, advance > ELINT_FRESH_S, the emitter contact drops. test_emitter_fix_only_when_actionable — a far/short-baseline emitter with fix_quality >= ELINT_FIX_ACTIONABLE_M produces NO contact. test_emitter_id_resolves_to_radar — launch_arm(emitter_id) for a surfaced emitter returns a HarmMissile whose target_radar is that live Radar.

**Counters / balance:**

This is intel, not a weapon, but it honors the contract: the enemy counters it by EMCON (a silent emitter is never heard, so it never surfaces — going dark protects the radar AND denies the player a SEAD target, the core tension). The fix quality is geometry-limited (the existing gates prevent a confident-wrong fix), so a hasty ARM shot on a poor fix can miss — physics, not dice.

**Risks:**

(1) Don't double-inject: the ship-fix path already injects ship SPY-1 fixes; the generalized path must not create two contacts for one ship radar (key collision is fine if both use the ship_id/emitter_id consistently). (2) Contact-id namespace: emitter ids (radar_id) must not collide with ship_id/aircraft_id keys in contacts.tracks — they don't today (radar_ids are '{ship}_spy1' / 'enemy_radar_00' / awacs radar id) but assert it. (3) Map clutter — gate emitter glyphs to actionable+fresh only.


---
## Feature: Enemy wild-weasel ARM vs the player's NEW emitters (HARM beyond the radar station)  _(effort: M)_

**What it is + real-world grounding:**

The enemy ARM already exists and works (AGM-88 HARM via HarmMissile, _doctrine_blind, _launch_strike_package(sead=True)) but it only ever targets self.radar_station. The moment the player fields NEW emitters — the Pantsir tracking radars (already in self.radar_net), an ARM pop-up illuminator, or a decoy emitter (feature #4) — the enemy should weasel-hunt THOSE too. Grounded in real SEAD/DEAD: a wild-weasel package homes on whichever hostile emitter is up, and shoot-and-scoot doctrine exists precisely because of this. This closes the loop: the player who lights a Pantsir radar to extend coverage now pays an ARM-exposure cost.

**Platform (launched from / carried by):**

Enemy fighters (the SEAD package, LOADOUT_SEAD = 2x HARM + 2x AIM-9X) and, optionally, a destroyer-launched ARM is out of scope (HARM is air-launched). Carried/launched exactly as today via _launch_strike_package; the only change is WHICH emitter the package is sent at and whose Radar the HarmMissile homes on.

**Sensors (uses / detected by):**

The enemy localizes the new emitters with the SAME sensor-only ESM it uses for the radar station: EnemyPicture.update_emitter accrues a fix for ANY player emitter an enemy platform can hear. Today world/combat.py _feed_enemy_picture only feeds the radar_station's emitter into the picture. Extend it to feed EVERY live player emitter the enemy can hear (Pantsir radars while emitting, the ARM illuminator during its pop-up window, the decoy). The HarmMissile then homes on that Radar object — physical emissions homing, with the silence/CEP/relock already implemented.

**AI brain (how the enemy commander uses or counters it):**

EnemyCommander._doctrine_blind generalized from 'the one radar station' to 'the highest-value LOCATED, believed-alive player emitter with HARM stock remaining' — selected from picture.emitters (the sensor-derived EmitterIntel set), NEVER from truth. Priority by emitter kind/value (radar station > Pantsir radar > decoy, with the decoy DELIBERATELY attractive so the player can bait HARM stock — feature #4). The brain must read EmitterIntel.believed_pos / located / alive only. Belief reset by evidence: an emitter heard again flips back to alive (mark_emitter_alive already does this), so a silenced-then-relit Pantsir re-enters the target list. No-cheat is preserved because the whole selection runs off picture.emitters, which _feed_enemy_picture populates only from radars that physically heard the emitter.

**Player UX:**

The player experiences this as RWR/threat cues (the drone RWR SPIKE/LOCK already exists) and as inbound HARM tracks once radar-gated. New: a HUD/RWR warning when an enemy SEAD package is believed inbound on a specific player emitter ('HARM THREAT: PANTSIR-01 RADAR') so the player can choose to silence that emitter (shoot-and-scoot / EMCON) before the round arrives. This is sensor-honest from the PLAYER side too — derived from the drone RWR + the radar-gated HARM track, not from reading enemy intent.

**UI needs:**

An emitter-threat panel/line in the HUD listing player emitters currently believed targeted by an inbound ARM (with time-to-impact estimate from the gated track), so emissions-control decisions are legible. Reuse the RWR alert rendering style.

**Game-model mapping (reuse vs add):**

Extend _feed_enemy_picture to call commander.picture.update_emitter for EVERY live player emitter (radar_station + each Pantsir.radar while emitting + the ARM illuminator + decoy), with the same heard-gate (an enemy platform must physically hear it). Generalize _believed_radar_station() -> _believed_target_emitters() returning the sorted EmitterIntel list. _doctrine_blind picks the top entry; _launch_strike_package(sead=True) already takes target_radar — pass the chosen emitter's live Radar. The BDA/mark_emitter_destroyed completion logic already exists per-emitter (keyed by target_id == emitter_id), so it generalizes for free.

**Implementation sketch + test contracts:**

Files: world/combat.py (_feed_enemy_picture emitter loop; pass the chosen Radar to _launch_strike_package; ~30 lines). sim/commander.py (_doctrine_blind generalized to multi-emitter priority; _believed_target_emitters helper; ~40 lines, keep the determinism single-Generator). game/hud.py (emitter-threat line). TEST CONTRACTS: test_commander_targets_pantsir_radar — with the radar station dead but a Pantsir radar located+alive+heard in the picture and HARM stock, the commander schedules a HARM package at the Pantsir emitter_id (sensor-only; assert no truth read by feeding ONLY picture updates). test_emitter_priority — radar station outranks a Pantsir radar when both located. test_harm_homes_new_emitter — the launched HarmMissile.target_radar is the Pantsir's live Radar. test_belief_reset_on_relight — a silenced emitter marked destroyed, then heard again, re-enters the target list (mark_emitter_alive). test_no_truth_leak — commander given a picture with a STALE/wrong believed_pos fires at the believed_pos, not the real one (round misses if belief is wrong).

**Counters / balance:**

Player counters: EMCON timing (silence the threatened emitter — the existing R toggle for the station; a per-Pantsir emit toggle is the new control), shoot-and-scoot (feature #4), and the decoy (bait the HARM stock). The enemy's HARM stock is finite (AIRFIELD_HARM/CARRIER_HARM in WeaponStock), so baiting it with a decoy has strategic value. Balance: feeding more player emitters into the enemy picture makes 'going loud' genuinely costly, the intended spec tension, without making the player's own radar station MORE vulnerable than today.

**Risks:**

(1) Determinism: the commander must keep ordering emitter selection by a stable key (located + value + emitter_id tiebreak), not by dict iteration order, or replays diverge. (2) Don't over-feed: a Pantsir radar that is only briefly up (point-defense) should accrue fix slowly (the ESM_FIX_TIME_S 90 s accrual already protects this — a blip never reaches a firing fix). (3) The existing single-active-HARM-mission guard (active_harm in _doctrine_blind) must become per-emitter so two emitters can be hunted, but bounded so the enemy doesn't spam packages. (4) Keep the blind-before-kill gate coherent when 'the radar' is now several emitters.


---
## Feature: ARM countermeasures: shoot-and-scoot mobility + deployable decoy emitter  _(effort: L)_

**What it is + real-world grounding:**

Two defensive plays against ARM, both leaning on machinery that already exists. (a) SHOOT-AND-SCOOT: real coastal TELs/radars relocate after emitting/firing to defeat back-plot and ARM. Today EVERY player emitter and TEL is a fixed pin (RADAR_STATION_XZ, BASE_POS, PANTSIR_SPAWNS) — a hard realism gap and the spec explicitly lists 'shoot-and-scoot' as the ARM defense. (b) DECOY EMITTER: a deployable radiating decoy that draws enemy ARM/back-plot onto an empty point — the HarmMissile homes on ANY Radar object and its silence/CEP/relock logic already models a decoy that blinks, and the enemy commander's EmitterIntel will localize and target it because it only reads sensed emissions. Grounded in feature_ideas.md ('Player decoys / chaff & EW counter-play', 'shoot-and-scoot') and standard SEAD doctrine.

**Platform (launched from / carried by):**

(a) The player radar station and Pantsir units gain a relocate action (the TEL/radar 'displaces' to one of a few pre-surveyed alternate pins — a discrete jump with a vulnerable transit window, not full drivable movement, to bound scope). (b) The decoy is a lightweight new player object: a Radar (emitting, a recognizable but distinct emitter signature) at a player-chosen empty coordinate, with low HP and no detection value — it exists only to radiate. Carried by the base (a deployable, finite count via config.decoy_count).

**Sensors (uses / detected by):**

(a) Relocation defeats the enemy's accrued ESM fix: EmitterIntel.believed_pos tracks last-known, so after a scoot the enemy's HARM (fired at the believed_pos) hits the OLD location — physical, fog-honest. The new position must be re-localized from scratch (fix decays during the silent transit). (b) The decoy is a real emitter heard by enemy ESM exactly like any radar; it feeds EnemyPicture.update_emitter and the commander localizes+targets it. The decoy itself has NO sensor function (it doesn't see — it only radiates), so it never leaks intel to the player.

**AI brain (how the enemy commander uses or counters it):**

The enemy brain is UNCHANGED in principle — it keeps reading sensor-derived EmitterIntel — but now (1) a scooted emitter's fix points at an empty pin until re-localized, so the commander's HARM/Tomahawk back-plot lands on nothing (emergent, no special-case), and (2) the decoy appears in picture.emitters as a believed-alive located emitter and the commander may spend a HARM package on it (feature #3's priority must rank the decoy plausibly — attractive enough to bait, not so attractive it ignores the real radar; tune by emitter 'value' which the brain reads from the SENSED kind, which a good decoy spoofs). Crucially the brain cannot tell decoy from real except by behavior — it has no truth flag, preserving no-cheat.

**Player UX:**

(a) A 'DISPLACE' action per relocatable emitter (a new keybind or a map context action): pick a pre-surveyed alternate site; the emitter goes silent and unavailable during a transit timer, then re-emits at the new pin. HUD shows the transit countdown + a 'VULNERABLE — DISPLACING' state. (b) A 'DEPLOY DECOY' action: place a decoy emitter at a map point (RMB-class tasking); HUD shows decoy stock + each decoy's alive/targeted state. Both give the player legible agency against the now-smarter enemy SEAD (feature #3).

**UI needs:**

(a) Relocation: per-emitter status (EMITTING / SILENT / DISPLACING t-) in the HUD emitter panel; alternate-site markers on the tactical map. (b) Decoy: a deploy cursor mode, decoy glyphs on the map (distinct from real emitters), stock counter, and a 'DECOY TARGETED' satisfaction cue when an enemy HARM commits to it. This is high-value UI surface area the project wants.

**Game-model mapping (reuse vs add):**

(a) Shoot-and-scoot: add alt-site lists for the radar station / Pantsir; a displace(site) that sets emitting=False, starts a transit timer, then moves Radar.pos + the owning Structure.pos to the new pin and re-emits. The enemy EmitterIntel.believed_pos naturally lags (it only updates from new hearings), so no enemy-side change is needed — the miss is emergent. (b) Decoy: a small DecoyEmitter wrapping a sim.radar.Radar (alive, emitting, distinct radar_id, tiny ranges so it has no real detection use) added to self._emitters() and self._player_emitters fed to the enemy picture; a low-HP Structure wrapper so a HARM can kill it (and SHOULD — that's the bait paying off). Determinism: no RNG needed for displace; the decoy adds nothing stochastic.

**Implementation sketch + test contracts:**

Files: world/combat.py (alt-site config + displace() for radar/Pantsir; DecoyEmitter spawn/deploy + feed into _emitters()/_feed_enemy_picture; ~80 lines). game/keybinds.py (new actions: 'displace_emitter', 'deploy_decoy' — currently-unused keys). game/sandbox.py + game/tactical_map.py (displace action, decoy deploy cursor, glyphs; ~80 lines). game/hud.py (emitter status + decoy panel). TEST CONTRACTS: test_displace_moves_emitter_and_silences — displace() silences then re-emits at the new pin after the transit timer; Radar.pos and Structure.pos both move. test_scoot_defeats_harm — an enemy HARM fired at the pre-scoot believed_pos impacts the old location (CEP ring around the OLD pin) and the relocated radar survives (deterministic). test_decoy_is_heard_and_targetable — a deployed DecoyEmitter is heard by enemy ESM, gets an EmitterIntel fix, and the commander can schedule a HARM at the decoy emitter_id (sensor-only). test_decoy_killable — a HARM fused on the decoy kills the decoy Structure and consumes enemy HARM stock, leaving the real radar untouched. test_displace_determinism — same seed/config replays the displace + decoy outcomes bit-identically.

**Counters / balance:**

These ARE the counters in the cluster — but they have costs to keep balance: displacing silences the emitter during transit (you lose coverage / a SAM-illumination window — the spec's EMCON tradeoff), and decoys are finite (config.decoy_count) and can be ignored if the enemy belief value-ranks them below the real radar. The enemy's counter to the decoy is simply not wasting HARM on a low-value emitter (the value-priority in feature #3's brain), so a well-mimicked decoy is the skill play. All emergent from sensed emitter belief — no dice.

**Risks:**

(1) Scope creep: keep displace a DISCRETE pre-surveyed jump, not free vehicle driving (full mobility is a much larger physics/AI change). (2) The decoy value-tuning is delicate — too attractive and the enemy never hits the real radar (game trivially won by spamming decoys, bounded by finite stock); too unattractive and the decoy is useless. Lock the balance with a two-sided regression like the SM-2 hi/lo bands. (3) Moving a Structure.pos at runtime must update its OBB and any render anchor (the 3D scene draws structures at their pin) — verify the structure sweep + render both read the live pos. (4) Adding decoy emitters to the enemy picture must not let the enemy localize the REAL base by association — the decoy carries only its own pos, no link to BASE_POS.
