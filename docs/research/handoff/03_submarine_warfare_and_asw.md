# Spec 3: Submarine warfare + ASW

> Implementation-research spec for a fresh implementer. Read HANDOFF_README.md first for codebase orientation + non-negotiables.

## Summary
A self-contained "acoustic domain" cluster that bolts onto COMBAT as a SECOND lose-path orthogonal to the radar/ELINT/SAR fog. An enemy diesel boat (SSK) loiters submerged and undetectable (no RCS, no horizon to peek over, ignored by every existing sensor), periodically creeping to periscope depth to fire a small sub-launched Kalibr (3M14-class) salvo at the base, then going deep again. The player can NEVER find it the way it finds ships. Two player-controlled counters, BOTH reusing existing machinery: (1) player-PLACED passive sonobuoys (a fourth tasking platform) that triangulate the boat in the acoustic domain via a near-clone of ElintReceiver's least-squares bearing solver — short flat range, NO radar horizon, NO terrain LOS; and (2) launch-transient back-plotting that mirrors the enemy's own HOME_COAST_Z back-plot to fix the firing point when the boat surfaces to shoot. The fairness telegraph is the acoustic launch transient (a loud datum the boat MUST emit to fire) plus an RWR-style "TORPEDO/MISSILE IN THE WATER" threat cue, so a salvo is always survivable if the player keeps eyes on the buoy field. The five mechanics ground tightly in: StrikeDef/StrikeMissile (sub Kalibr is functionally a Tomahawk with launch_warning=False), ElintReceiver (the buoy solver), EnemyPicture/EnemyCommander (the boat's sensor-only brain), the launch_warning vs radar-gated contact channels in _update_strike_contacts, the player-placed-platform pattern that the drone already establishes, and CombatConfig's LOCKED armory schema (new tags [seed,8] sub, [seed,9] sonar).

**Dependencies:** MUST EXIST FIRST / cross-cluster deps: (1) The 'Threat-Warning HUD strip' (feature_ideas.md CONSENSUS item) is the perception layer that makes the acoustic launch transient FAIR — the sub salvo + transient cue should ship alongside or after it; the spec assumes a threat-cue surface exists (game/hud.py already has RWR rows + drone_respawn_left that the sub state/datum lines extend). (2) Reuses, unchanged: sim/strike.py StrikeMissile (Kalibr), sim/recon.py ElintReceiver._solve_triangulation (buoy solver — factor it out or subclass), sim/commander.py EnemyPicture + back-plot pattern (SubCommander + launch datum), world/combat.py _update_strike_contacts launch_warning/radar-gated channels + apply_missile_hits_structures + _refine_strike_aim (Kalibr terminal acquire) + _inject_elint_tracks pattern (buoy/datum injection) + SeedSequence child streams (new tags [seed,8] sub, [seed,9] sonar), world/spawn_zones.py (new sample_subs band). (3) world/combat_config.py is LOCKED-schema: adding n_subs, sub_kalibr_ammo, n_sonobuoys, asw_ammo + clamp ranges + clamp_config kwargs needs the integrator sign-off the file header demands, and tests/test_combat_config.py must be extended in lockstep. (4) victorious win condition + game/combat_setup.py armory UI must learn about subs/buoys/ASW. (5) New keybinds (ASW launch / round select, sonobuoy platform) go through game/keybinds.py ACTIONS registry. Ordering within the cluster: feature 1 (sub) + feature 2 (Kalibr) first (the threat); then feature 5-cue + feature 3 (buoys) as the primary counter; then feature 4-backplot + feature 5-weapon to close the kill loop.

**Open questions:** 1) BUOY DELIVERY: drop at a map-clicked point (max agency) vs drop at the drone's position (realistic, ties ASW to the recon tasking dilemma) vs both? Recommend map-click primary; revisit drone-laid buoy lines as flavor. 2) DOES THE PLAYER GET A SUB? Spec says NO (player gets the ASW weapon instead) to keep the coastal-Bastion fantasy and control surface tight — confirm this is the intended scope. 3) KALIBR max_range scale: real is 1500+ km; must scale DOWN (~400-600 km) so the boat is forced into buoy range and stays huntable — needs a balance pass against the map size and buoy stock. 4) ASW terminal model depth: the spec uses a simple acoustic-basket-vs-fix-quality check (honest + emergent, cheap). Is a richer torpedo-search model wanted later, or is the basket sufficient (recommend basket)? 5) SONAR PROPAGATION realism: should sea-state/thermocline modulate SONOBUOY_RANGE_M (ties into the planned weather/sea-state mechanic — a natural future hook) or stay a flat range for v1 (recommend flat for v1, sea-state later)? 6) Does the sub need a visible 3D model + a dedicated_missile_models-style Kalibr mesh, or is map-only + the Tomahawk placeholder mesh acceptable for v1 (StrikeMissile already falls through to the Oniks/Tomahawk mesh)? 7) Determinism tags: confirm [seed,8] and [seed,9] are free (current tags in use: 3 fleet, 4 recon, 5 commander, 6 pantsir, 7 enemy radars — 8/9 appear unused).


---
## Feature: Enemy diesel submarine (SSK) — submerged contact + dive/surface state machine  _(effort: L)_

**What it is + real-world grounding:**

An older diesel-electric attack boat (Kilo/Project 877-class analogue) that loiters DEEP (e.g. -120 m) and submerged off the player coast. It is the one threat the radar/SAR/ELINT suite physically cannot find: no radar RCS, no antenna above water, never enters any Radar.detects() path. Grounding: Kilo-class diesel boats carry the 3M14 Kalibr-PL and are famously quiet ('the Black Hole'); they must creep to launch depth and emit an acoustic transient to fire (open-source/unclassified). The boat cycles DEEP_TRANSIT -> APPROACH (slow, quiet) -> LAUNCH_DEPTH (brief, noisy: flooding tubes + gas-generator eject = the loud datum) -> SALVO -> EVADE_DEEP (sprint away then quiet again). Speed/quietness is a tradeoff like the rest of the game's emissions economy: it is loudest exactly when it shoots.

**Platform (launched from / carried by):**

It IS the platform (a new sim/submarine.py Submarine entity, NOT in self.ships — it must never feed the player radar-gated ContactBoard, mirroring how ReconDrone is kept out of self.aircraft). Lives in a new self.subs list in world/combat.py. Carries the Kalibr-PL tubes (feature 2). Spawned via a seeded child stream off [seed, 8] at a probed-open-water deep anchor inside a new sub spawn band (closer than the carrier band — ~80-140 km — so its short-legged Kalibr can reach the base).

**Sensors (uses / detected by):**

DETECTABLE only acoustically: it emits a continuous low broadband 'radiated noise level' (function of its speed state — quiet on APPROACH, loud on SPRINT/LAUNCH) and a sharp LAUNCH TRANSIENT spike when it fires. These are what the player's sonobuoys (feature 3) and hydrophone array hear. It carries its OWN passive sonar + a brief periscope/ESM look at launch depth to localize the base — but the base position is a fixed installation the boat 'knows' coarsely (like the enemy commander already knows HOME_COAST_Z geometry), so its targeting is sensor-plausible without a live track requirement.

**AI brain (how the enemy commander uses or counters it):**

Sensor-driven, no truth read: the boat's behavior is owned by a tiny new SubCommander in sim/commander.py (or a method on EnemyCommander) that reads ONLY the existing sensor-only EnemyPicture. Doctrine: stay deep and quiet by default; advance to a launch box only when the picture's threat level to the boat is LOW (no recent player ASW prosecution event — see feature 5's symmetric cue); fire a salvo on a cooldown; after firing, EVADE_DEEP and lengthen the quiet window if it believes it was localized (i.e. the EnemyPicture records that a player sonobuoy/helo pinged near it — fed symmetrically, never reading the buoy's truth). Crucially it does NOT need a live base track to shoot (fixed target), so it stays honest: it shoots at surveyed base coordinates with a CEP, exactly like EnemyStrikeController's GPS/INS Tomahawks.

**Player UX:**

The player never directly controls the sub; UX is about HUNTING it. The sub appears on the tactical map ONLY as a low-confidence acoustic datum/track once the buoy net localizes it (feature 3), drawn in a distinct 'subsurface' color family. Killing it requires a localized fix + a weapon that reaches underwater (feature 4 player ASW). It contributes to the victorious win condition (all enemy hulls dead) so the player MUST eventually find and kill it.

**UI needs:**

A subsurface contact glyph on the tactical map (distinct from surface triangles and air diamonds — e.g. a downward chevron) drawn at the buoy-triangulated estimate with an uncertainty ring (reuse ELINT_CIRCLE drawing). A HUD line in the threat panel: 'SSK: <state>' only once localized. An 'unlocalized but active' ambient cue is deliberately absent (fog) until a buoy hears it.

**Game-model mapping (reuse vs add):**

New sim/submarine.py Submarine entity (pure numpy, GL-free, +Y up, X east, Z north). Reuses Ship's damage ladder conceptually but underwater (a hit = mission kill; no burning/listing needed, or a simple sinking). Reuses the SeedSequence child-stream pattern. Adds a 'subsurface' size class concept used ONLY by the acoustic sensors (it is invisible to sim/radar.py by construction — never passed to Radar.detects). Spawn via world/spawn_zones.py extended with sample_subs(rng, n) (new open-water band). NOT added to self.ships (would leak into radar gating). Win condition (world/combat.py victorious property) extended to require all subs dead.

**Implementation sketch + test contracts:**

Files: NEW sim/submarine.py (Submarine class: pos/vel/depth, state enum DEEP_TRANSIT/APPROACH/LAUNCH/EVADE, radiated_noise() -> float by state, fire_salvo() seam, alive/kill); world/combat.py (self.subs list built from a new SUB_SPAWNS or sample_subs off np.random.default_rng([rng_seed, 8]); stepped in step() right after _step_drones; victorious extended). New constants: SUB_DEPTH_M=-120, SUB_LAUNCH_DEPTH_M=-15, SUB_APPROACH_SPEED_MPS, SUB_SPRINT_SPEED_MPS, SUB_NOISE_QUIET/LOUD (radiated-noise scalars). Test contracts (tests/test_submarine.py): (a) a Submarine is NEVER returned by any RadarNetwork.visible / Radar.detects call (assert it is not in self.ships and radar gating ignores it); (b) the state machine cycles deterministically under a fixed seed (same state sequence/timings); (c) radiated_noise() is strictly higher in LAUNCH/SPRINT than APPROACH/DEEP; (d) victorious stays False while any sub is alive even with all surface hulls + airfield + radars dead.

**Counters / balance:**

The boat counters the player's radar-centric sensor suite by living in a domain it cannot see. The player counters the boat with the sonobuoy net (feature 3) + launch-transient back-plot (feature 5) + an underwater-reaching weapon (feature 4). Balance: short Kalibr legs force the boat close, into buoy range; the loud launch transient guarantees a fix opportunity every salvo. Physics-not-dice: the boat's hit on the base emerges from its surveyed-coordinate CEP vs the SEEKER_BASKET_M structure-acquisition gate (identical mechanism to the existing JASSM/TLAM _refine_strike_aim), never a roll.

**Risks:**

Pathing/anchor must be probe-measured deep open water (re-use the DESTROYER_SPAWNS terrain-sweep discipline). Must NOT accidentally enter self.ships or any emitter list (would make it radar-visible and break the whole premise — guard with an isinstance/exclusion test). Keep determinism: every draw via the [seed,8] child stream.


---
## Feature: Sub-launched Kalibr (3M14-PL) salvo  _(effort: S)_

**What it is + real-world grounding:**

A small salvo (2-4 rounds) of sub-launched land-attack cruise missiles fired at the base when the boat reaches launch depth. Grounding: the 3M14 Kalibr (SS-N-30A), ~1500-2500 km range, Mach 0.8-0.9 subsonic turbofan cruise, ~20 m sea-skim altitude, fired from Kilo-class via torpedo-tube gas-generator eject then booster (open-source/unclassified, confirmed by web search: missilethreat.csis.org/missile/ss-n-30a). Functionally near-identical to the existing Tomahawk StrikeDef — a turbofan sea-skimmer — so it reuses StrikeMissile wholesale.

**Platform (launched from / carried by):**

Launched from the Submarine (feature 1) at SUB_LAUNCH_DEPTH_M, breaching the surface like a VLS cold-gas eject. Reuses the EXACT pattern of EnemyStrikeController._fire_salvo / world.combat _fire_tomahawk_salvo: spawn StrikeMissile with launch_cinematic=False and launch_platform=<sub> (so sim/damage.py never self-OBB-hits the launcher) into self.missiles; the round flies on the next base step like any enemy launch.

**Sensors (uses / detected by):**

The Kalibr itself is radar-gated EXACTLY like the Tomahawk (is_hostile=True, radar_size='missile', launch_warning=False on StrikeDef): the player only sees it once his radar physically detects the low sea-skimmer — i.e. close, under the horizon until terminal. CRUCIAL DESIGN CHOICE: keep launch_warning=False so the missile stays fog-honest (no free instant cue), and instead surface the warning via the ACOUSTIC launch transient (feature 5) — the player's fair telegraph is hearing the boat shoot, not a magic missile ping.

**AI brain (how the enemy commander uses or counters it):**

Targeting is sensor-plausible and truth-free: the salvo flies at SURVEYED base coordinates (the boat's coarse known-installation belief, mirroring how EnemyStrikeController fires GPS/INS Tomahawks at the radar station's surveyed coords). Terminal acquisition reuses world.combat _refine_strike_aim (SEEKER_BASKET_M scene-matching against live player structures), so kill probability EMERGES from the boat's targeting CEP vs the basket, never a dice roll. The boat back-plots/aims like the existing commander, never reading a player TEL's real position.

**Player UX:**

The player experiences it as a sudden low-altitude inbound salvo from the SOUTH/sea sector at close range — the hardest profile to intercept because it leaks under the radar horizon. Counter: Pantsir point-defense (already auto-engages inbound hostile StrikeMissiles) + S-300 if the radar net (extended by the buoy-cued picture or a high drone) sees it in time. The acoustic transient cue (feature 5) buys reaction seconds.

**UI needs:**

Reuses the existing hostile-strike contact rendering (the radar-gated channel in _update_strike_contacts) — no new missile glyph needed. The NEW ui is the launch-transient threat banner (feature 5). A debrief line ('KALIBR SALVO x2 FROM SSK') fits the planned Shot Debrief / threat strip.

**Game-model mapping (reuse vs add):**

NEW StrikeDef KALIBR_PL in sim/arsenal.py (clone TOMAHAWK's turbofan profile: length 8.22 m, diameter 0.533 m, Mach ~0.8, cruise_alt ~20 m, max_range ~500_000 m game-scaled down from real to fit the map and force the boat close, warhead ~450 kg). Registered in STRIKES dict. Flown by the UNCHANGED StrikeMissile (it is a subsonic VLS-style sea-skimmer = the Tomahawk code path; _is_vls triggers on the vertical eject + booster). is_hostile/radar_size/launch_warning inherited from StrikeMissile class attrs.

**Implementation sketch + test contracts:**

Files: sim/arsenal.py (add KALIBR_PL StrikeDef + STRIKES entry); sim/submarine.py (fire_salvo(world, aim_xz, aim_y) spawning N StrikeMissile(KALIBR_PL, breach_pos, vertical eject vel, aim) with launch_platform=self, launch_cinematic=False); world/combat.py (sub step calls fire_salvo into self.missiles; the EXISTING apply_missile_hits_structures hostile-vs-base sweep already demolishes the base with these — no new damage code; the EXISTING radar-gated _update_strike_contacts already feeds them to the player picture). Test contracts (tests/test_kalibr_salvo.py): (a) a fired Kalibr is is_hostile=True, radar_size=='missile', launch_warning==False (stays fog-gated); (b) launch_platform is set so sim/damage cannot self-hit the sub; (c) a salvo aimed at the bastion cluster within SEEKER_BASKET_M acquires + can kill a TEL via the shared _refine_strike_aim path; (d) a salvo whose surveyed aim is beyond the basket hits dirt (physics-not-dice kill emergence); (e) determinism: same seed -> same salvo count/positions.

**Counters / balance:**

Countered by Pantsir (auto-engages inbound StrikeMissiles already), S-300 if cued, and ultimately by killing the boat before it shoots again. The salvo counters the player's horizon-limited radar by sea-skimming. Balance lever: salvo size + SALVO_PERIOD cooldown + scaled max_range (forces the boat into buoy range). Reuses the existing strike balance contracts unchanged.

**Risks:**

Must scale max_range DOWN from the real 1500+ km so the boat is forced close enough to be huntable (otherwise it lurks at map edge and the buoy counter never bites). Keep launch_warning=False — flipping it would hand the player a free fog-piercing cue and defeat the acoustic-telegraph design. Don't add KALIBR_PL to the player's WEAPONS/launch path (it's enemy-only).


---
## Feature: Player-placed passive sonobuoy field (acoustic triangulation counter)  _(effort: L)_

**What it is + real-world grounding:**

The PRIMARY player counter: a finite stock of passive sonobuoys the player drops at positions of their choosing during the match. Each buoy is a passive acoustic listener with a SHORT FLAT detection range that hears the sub's radiated noise + launch transient and yields a noisy BEARING; two or more buoys hearing the boat triangulate it via least squares — exactly the ELINT solver, moved into the acoustic domain. Grounding: real DIFAR/passive sonobuoys give bearing-to-noise-source; a field of them cross-fixes a contact (unclassified ASW doctrine). This deliberately re-creates the ELINT 'fight the fog without emitting' loop in a domain radar can't touch.

**Platform (launched from / carried by):**

Buoys are placed by the PLAYER as a new tasking verb. Two viable controls both already exist: (a) add 'sonobuoy' as a fourth entry in controls.PLATFORMS_COMBAT (bastion -> s300 -> drone -> sonobuoy) and on that platform a tactical-map LMB-click drops a buoy at the clicked world point (reusing the map's existing LMB world-point pick), OR (b) drop a buoy at the drone's current position on a keypress (the drone is the realistic delivery platform — a recon drone laying a buoy line). Recommend (a) for player agency + (b) flavor later. Buoys live in a new self.sonobuoys list; placement consumes from a finite config stock.

**Sensors (uses / detected by):**

The buoy IS a sensor: a new AcousticReceiver in sim/recon.py (sibling of ElintReceiver) per buoy, or one shared AcousticArray fed all buoy positions. It hears a Submarine when ground_range <= SONOBUOY_RANGE_M (short, ~25-40 km) AND the sub's radiated_noise() exceeds a detection floor scaled by range (a loud LAUNCH transient is heard much farther than a quiet APPROACH — the speed/quietness tradeoff bites here). NO radar_horizon, NO terrain_blocks (sound travels under the surface) — this is the key divergence from ElintReceiver and the reason ASW is a distinct domain. Each detection accumulates a noisy bearing pair; the existing least-squares + CRLB-quality + geometry-gate + range-observability machinery triangulates a fix.

**AI brain (how the enemy commander uses or counters it):**

No enemy brain here — this is a player sensor. But it FEEDS the symmetric fairness loop: when a buoy localizes the boat to actionable quality, world.combat injects a low-confidence subsurface track into the player picture AND records (in the enemy picture, sensor-honestly) that the boat is being prosecuted — which the SubCommander (feature 1) reads to decide to evade. The buoy's own placement is a player decision; the only AI is the boat reacting to being heard.

**Player UX:**

A genuine tasking dilemma (the design goal): buoys are finite and the player must guess WHERE the boat will be — committing the drone/attention to ASW means less recon on the fleet. Placing a buoy line across the likely launch corridor (south/sea sector) is the skill. The map shows buoy positions (friendly markers), their detection radius rings, live bearing rays from buoys currently hearing the boat (reuse ELINT_RAY drawing), and the triangulated fix circle that SHARPENS as more buoys hear it (reuse the ELINT error->confidence visual).

**UI needs:**

Tactical map: friendly buoy glyphs + faint detection-range rings; live acoustic bearing rays (distinct purple/teal from ELINT's rays); a subsurface fix chevron + uncertainty ring. HUD: a 'SONOBUOY platform' panel (mirror the existing drone panel in game/hud.py) showing buoys remaining, buoys currently in contact, and current fix quality. A placement hint ('LMB DROP BUOY') when the sonobuoy platform is selected (mirror DRONE_RECON_HINT). Counts feed the new armory rows.

**Game-model mapping (reuse vs add):**

NEW AcousticReceiver/AcousticArray in sim/recon.py reusing ElintReceiver's _solve_triangulation verbatim (same A@[X,Z]=b least squares, CRLB quality, consistency/geometry/range-observability gates) but: range gate SONOBUOY_RANGE_M, NO horizon/terrain calls, bearing sigma a NEW acoustic constant (~2-3 deg, wider than ELINT's 0.02 rad), and the 'emitter' is a Submarine whose radiated_noise() must clear a range-scaled floor. Buoy stock + placement in world/combat.py self.sonobuoys (child rng [seed, 9]). Fix-injection mirrors _inject_elint_tracks: actionable fix -> subsurface track keyed to the sub id with error-on-age fade (reuse the ELINT_AGE_MAX_S mapping).

**Implementation sketch + test contracts:**

Files: sim/recon.py (AcousticReceiver, ACOUSTIC_BEARING_SIGMA_RAD, SONOBUOY_RANGE_M, ACOUSTIC_DETECT_FLOOR; reuse the triangulation solver — factor it out or subclass); world/combat.py (self.sonobuoys, place_sonobuoy(xz) consuming stock, _step_acoustic_sensors on a cadence like _step_recon_sensors, _inject_sub_track mirroring _inject_elint_tracks, child rng [seed,9]); game/controls.py (add 'sonobuoy' to PLATFORMS_COMBAT + LMB-drop handling); game/tactical_map.py (buoy glyphs/rings/rays/fix-circle); game/hud.py (sonobuoy panel + hint); world/combat_config.py (n_sonobuoys field + clamp). Test contracts (tests/test_sonobuoy_asw.py): (a) ONE buoy hearing the boat yields a bearing but NOT an actionable fix (bearing-only, no range — same property ElintReceiver enforces); (b) TWO+ buoys with adequate baseline geometry produce an actionable fix whose quality improves as more buoys/time accrue; (c) a quiet APPROACH sub at the same range is NOT heard while a LAUNCH-transient sub IS (noise-floor physics); (d) NO horizon/terrain gate (a buoy behind a coastal ridge from the sub still hears it — assert terrain does not block, unlike ElintReceiver); (e) determinism under [seed,9]; (f) placement consumes stock and refuses at zero.

**Counters / balance:**

This is THE counter to the sub. Countered-by (boat's side): the boat staying quiet/deep (low noise = short detection range = needs more buoys / closer placement), and EVADE_DEEP after a salvo to slip the fix before the player can prosecute. Balance: buoy stock vs sub stealth vs Kalibr range — tuned so a player who commits a buoy line to the launch corridor reliably gets a fix, but a passive player loses the base. Physics-not-dice: the fix quality is the measured CRLB from real buoy geometry (already in the solver), and detection is a noise-floor-vs-range physics check, never a roll.

**Risks:**

Don't let the buoy net trivially see everything (keep range SHORT and the quiet-sub floor high, so placement matters). Reusing the ELINT solver is correct but the acoustic domain MUST drop the horizon/terrain calls — a copy-paste that keeps terrain_blocks would wrongly mask a buoy from a sub behind a hill. Keep the lstsq cadence off the 120 Hz step (use a cadence like ELINT_FIX_PERIOD_S).


---
## Feature: Launch-transient back-plot (free, always-on ASW fix when the boat shoots)  _(effort: M)_

**What it is + real-world grounding:**

The SECONDARY player counter and the fairness backbone: when the boat fires (the loud acoustic transient + the breaching Kalibr), the player gets a launch DATUM — a coarse fix of where the boat was at launch — even with NO buoys nearby, by back-plotting the transient/missile origin. This guarantees that every salvo, however well the player guessed buoy placement, leaves a trail the player can act on, so a salvo is never an un-counterable bolt from the deep. Grounding: this is the EXACT mirror of the enemy commander's own HOME_COAST_Z launch back-plot (sim/commander.py process_missile_track) — the player's ASW back-plot reuses the same idea in reverse.

**Platform (launched from / carried by):**

No new platform — it is a passive side-level inference in world/combat.py, triggered by the Kalibr launch event. The 'sensor' is the player's coastal hydrophone/transient detector (conceptually always listening for a loud transient anywhere; cheap because it only fires on a launch event, not continuously).

**Sensors (uses / detected by):**

Hears the LAUNCH transient (the loudest acoustic event the boat makes) and/or back-projects the just-detected Kalibr's first-seen track to its sea-surface origin — directly analogous to the enemy's back-plot of a player sea-skimmer to HOME_COAST_Z. Because the transient is loud, the detector has long reach (unlike the short passive buoys), but the resulting fix is COARSE (error grows with range, like BACKPLOT_ERR_FRAC) — good enough to cue, not to snipe, and it ages out fast (the boat immediately runs).

**AI brain (how the enemy commander uses or counters it):**

Symmetric honesty: the back-plot fix is fed into the PLAYER picture as a decaying subsurface datum, and the fact that a salvo was localized is recorded sensor-honestly in the ENEMY picture so the SubCommander knows it is 'datum'd' and lengthens its evade. No truth read on either side: the player gets the launch point ± error, not the boat's live position; the boat reacts to having shot (it knows it was loud), not to reading the player's fix.

**Player UX:**

On a salvo, the player gets: (1) the RWR-style threat banner (feature 5 cue), and (2) a coarse subsurface datum chevron on the map at the launch point, fading over ~30-60 s. This is the player's cue to either vector the drone to lay a buoy on the datum, or fire an ASW weapon (feature 5) at the datum if in range before it ages out. It rewards fast reaction and turns every salvo into a hunt opportunity.

**UI needs:**

A distinct 'launch datum' marker on the tactical map (larger, fast-fading uncertainty ring vs the buoy fix's sharpening ring) + a HUD/threat-strip line 'SSK DATUM brg/rng' with a countdown feel via fade. Reuses the contact-age fade machinery already in the map.

**Game-model mapping (reuse vs add):**

Reuses sim/commander.py's back-plot math pattern (project a first-seen low/level track back to its surface origin; error = detection range * a fraction) but applied to the ENEMY Kalibr's first-seen track to fix the SUB's launch point, injected into the PLAYER picture (self.contacts.tracks) as a subsurface datum with age-based fade. The boat's 'I was datum'd' belief is set in the EnemyPicture via a new sensor-honest flag the SubCommander reads.

**Implementation sketch + test contracts:**

Files: world/combat.py (on Kalibr salvo spawn, compute the launch datum from the sub's surface breach point ± error and inject a fast-fading subsurface track; set a 'prosecuted' marker in the enemy picture for the SubCommander); sim/commander.py (SubCommander reads the prosecuted marker to extend evade). Reuse BACKPLOT_ERR_FRAC-style error growth. Test contracts (tests/test_launch_transient_backplot.py): (a) a Kalibr salvo injects a subsurface datum into the player picture near (within error of) the sub's true launch point; (b) the datum fades/drops within the configured window (ages out — the boat ran); (c) the SubCommander's evade window lengthens after a datum event (deterministic); (d) no truth leak: the datum carries error, not the sub's post-launch live position.

**Counters / balance:**

Counters the boat's stealth at its single most vulnerable moment (firing). The boat counters BACK by sprinting away immediately (EVADE_DEEP) so the datum is stale by the time the player reaches it — the player must react fast or pre-position. Balance: datum error + fade time vs ASW weapon range/flight time. Physics-not-dice: error scales with range exactly like the existing back-plot; whether the player converts the datum into a kill emerges from geometry + reaction speed.

**Risks:**

Tune the datum error so it's a cue, not a free kill (must be coarser than a buoy cross-fix). Ensure the 'prosecuted' enemy-picture flag is sensor-honest (set because the boat WAS loud, not because it read the player's fix). Keep the datum fade short so a passive player can't sit on a stale datum.


---
## Feature: Player ASW weapon — depth-reaching prosecution (does the player get a sub? No; player gets the WEAPON to kill one)  _(effort: M)_

**What it is + real-world grounding:**

The player does NOT get their own submarine (it would not fit the coastal-Bastion fantasy and adds a whole control surface). Instead the player gets the means to KILL the enemy boat once localized: a coastal ASW asset — a rocket-thrown lightweight torpedo / depth-charge (ASROC-class) fired from the base, OR an ASW round delivered to a buoy/datum fix. Grounding: coastal/shore ASW and ship-launched ASROC (rocket + parachute-retarded Mk54-class torpedo) are the standard unclassified way a non-sub force prosecutes a localized contact. This closes the loop: find (buoys/datum) -> prosecute (ASW weapon) -> kill (win-condition hull).

**Platform (launched from / carried by):**

Fired from the player base/coast (a new ASW launcher conceptually co-located with the battery, or delivered by the drone). It is a player offensive verb against a LOCALIZED subsurface track only — you cannot fire it blind (must have a buoy fix or a fresh launch datum), which enforces the find-then-kill discipline and prevents map-wide blind sub-sweeping.

**Sensors (uses / detected by):**

Fires at a subsurface TRACK (the buoy fix or launch datum in the player picture), not at truth — same discipline as the S-300 firing at a contact track, not the real entity. The weapon's terminal homing on the sub is a short acoustic-seeker basket (a SEEKER_BASKET_M analogue in the acoustic domain): if the localized fix is within the seeker basket of the real boat, it acquires and kills; if the fix error exceeds the basket, it misses into the deep. Kill probability EMERGES from fix quality vs basket — physics-not-dice, identical philosophy to the strike-acquisition gate.

**AI brain (how the enemy commander uses or counters it):**

No enemy brain in the weapon; but the boat's SubCommander reacts to a prosecution attempt (an inbound ASW round detected acoustically as a fast transient) by sprinting/jinking (EVADE), so a marginal fix lets the boat slip the basket. The boat's reaction is sensor-driven (it hears the splash/transient), never truth.

**Player UX:**

Once the player has a localized subsurface track (buoy cross-fix or fresh datum), select the ASW weapon and fire at the track (reuse the S-300's 'select air target then launch' flow, retargeted to subsurface tracks). A sharp buoy fix = high kill chance; a coarse stale datum = likely miss, prompting the player to refine with more buoys. This makes buoy investment pay off concretely.

**UI needs:**

A weapon/round selector entry (mirror the S-300 round-select 'V' / Oniks-Zircon 'B' toggle pattern in keybinds.py) or a dedicated ASW launch when a subsurface track is selected. HUD readout of ASW rounds remaining + a 'NO SUB FIX' refusal hint when fired without a localized track (mirror the existing 'S-300: SELECT AIR TARGET' contextual hint). Map: the ASW round in flight + its splash/seeker basket.

**Game-model mapping (reuse vs add):**

NEW lightweight ASW round. Simplest honest model: a new sim entity (a ballistic rocket to the fix point, then a short acoustic-homing terminal modeled as a basket check against the localized track vs the real sub). Could reuse StrikeMissile's eject/boost/cruise machine for the rocket-throw leg, with a NEW terminal 'splash + acoustic basket acquire' step. Player-side (is_hostile=False) so it never trips the base damage sweep. Adds an ASW ammo field to CombatConfig. The kill itself calls Submarine.kill(); the win condition (feature 1) then clears.

**Implementation sketch + test contracts:**

Files: sim/asw.py (NEW AswRound: rocket-throw to fix XZ, parachute-retard, acoustic basket acquire vs the localized track; ASW_SEEKER_BASKET_M); world/combat.py (player launch_asw(track_id) gated on a subsurface track existing + ASW ammo; round joins self.missiles or a self.asw_rounds list, prosecutes the sub, calls kill() on basket hit; SubCommander evade on inbound); game/controls.py + keybinds.py (ASW launch verb / round select); game/hud.py (ASW ammo + refusal hint); world/combat_config.py (asw_ammo field + clamp). Test contracts (tests/test_player_asw.py): (a) firing with NO subsurface track returns None (refused — can't shoot blind); (b) a SHARP buoy fix within ASW_SEEKER_BASKET_M of the real sub -> acquire + Submarine.kill(); (c) a COARSE datum beyond the basket -> miss (sub survives) — physics-not-dice kill emergence from fix quality; (d) the ASW round is is_hostile=False and cannot damage player structures; (e) killing the last sub flips victorious True when other win sub-conditions already hold; (f) determinism.

**Counters / balance:**

This is how the player CLOSES the win condition against the sub. The boat counters by evading on the inbound transient (a marginal fix lets it slip), so the player is incentivized to get a tight cross-fix before prosecuting. Balance: ASW ammo scarcity + basket size vs fix quality + boat evade agility. Reuses the SEEKER_BASKET acquisition philosophy so it sits inside the established physics-not-dice contract.

**Risks:**

Don't let the player blind-fire a sub-sweep (gate strictly on a localized track). Keep the ASW round player-only (is_hostile=False) so it's excluded from the base-damage sweep like the friendly Pantsir 57E6. Acoustic terminal can stay simple (a basket check) — resist building a full torpedo sonar sim; the basket-vs-fix-quality model already delivers honest, emergent outcomes.
