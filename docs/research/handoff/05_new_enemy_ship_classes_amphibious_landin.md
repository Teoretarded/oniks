# Spec 5: New enemy ship classes + amphibious landing mission

> Implementation-research spec for a fresh implementer. Read HANDOFF_README.md first for codebase orientation + non-negotiables.

## Summary
This cluster turns the homogeneous "2 Destroyers + 1 Carrier" fleet into a doctrinally differentiated task group plus a timed amphibious-landing lose condition, all implementable against the EXISTING seams. The codebase already gives us almost everything: Destroyer(Ship) with racetrack nav + SPY-1 radar + per-channel magazines (sm2/sm6/ciws/tomahawk), Carrier(Destroyer) that overrides HP/dims via SHIP_TYPES and runs silent, EnemyDefenseController building one ShipDefense per ship, EnemyStrikeController for ESM→Tomahawk, EnemyCommander (sensor-only EnemyPicture: ESM fixes, back-plot clusters, drone/missile tracks) issuing orders executed in world/combat.py, world/spawn_zones.sample_fleet for seeded open-water placement, CombatConfig+clamp_config+combat_setup.py for the setup screen, and victorious/defeated win-lose properties.

The five ship classes are NOT five new entity files — they are FOUR new Destroyer subclasses (and a re-skin of the general destroyer as today's class) that differ only in (a) magazine loadout dataclass values, (b) which ShipDefense channels are enabled, (c) one doctrine flag the commander reads, and SHIP_TYPES HP/dims. The discriminators map cleanly: GROUND-ATTACK SPECIALIST (big tomahawk_ammo, near-zero sm2/sm6 — the commander's KILL-doctrine TLAM bank), AIR-DEFENSE SPECIALIST (heavy sm2/sm6, the SM-2/SM-6 screen that already exists in enemy_defense.py — just more ammo + higher SM2_MAX_INFLIGHT), GENERAL DESTROYER (today's balanced Destroyer, renamed), CARRIER (today's Carrier, unchanged — already silent/high-HP/aircraft-bearing), and a new LEADER/FLAGSHIP whose only special power is being the CEC datalink hub: its radar IS the cue_radars_fn source, so killing it strips remote-cue track formation from every other ship (a real, sensor-honest AI degradation — grounded in CEC, which "operates without reliance on a central command node" yet whose loss collapses the shared air picture). The AMPHIBIOUS FORCE is a new ship class (Transport/LCAC-carrier) plus a timed objective: transports run a beeline to a coast landing box; if any reaches it, the LCAC "lands" and the player loses on a countdown — a second, race-against-the-clock lose condition orthogonal to "TELs destroyed". The commander sequences the landing (screen forward → suppress → run transports in) reading only its sensor picture.

Every feature is physics-not-dice (kills via existing OBB/fuse sweeps and the multipath/SNR guidance noise), fog-of-war honest (ship classes are indistinguishable on the player's contact board until imaged; the commander reads only EnemyPicture), and deterministic (all placement/RNG via SeedSequence child streams off config.seed, exactly like sample_fleet's [seed,3] tag).

**Dependencies:** CROSS-CLUSTER / ORDERING DEPENDENCIES:

1. ShipClass taxonomy (sim/enemy_ship_classes.py) is the FOUNDATION — every other ship feature (flagship, ground-attack, air-defense, carrier-integration, fleet composition) depends on the ShipClassDef registry + the Destroyer-subclass pattern existing first. Build it before the role-specific tweaks.

2. Fleet composition (sample_fleet generalization) depends on the taxonomy AND on the amphibious classes existing (it places transports). It is the integration point in _spawn_ships. Build taxonomy + amphibious classes, then the mixer.

3. enemy_defense.py change (read ship.sm2_max_inflight via getattr) is a tiny shared edit the air-defense and general classes both rely on; do it with the taxonomy. Must keep the fallback to the module constant so existing enemy_defense tests stay green.

4. Flagship's datalink-hub degradation reuses cue_radars_fn (already in EnemyDefenseController) — no signature change, but it adds an optional cohesion knob to ShipDefense. Coordinate with whoever owns enemy_defense.py edits to avoid merge churn on that file.

5. Amphibious objective (timed lose) depends on the amphibious entities (transport/LCAC) and touches THREE shared, much-contested files: world/combat.py (step + properties), world/combat_config.py (new fields + clamp_config — LOCKED schema, needs the documented sign-off note), game/hud.py (banner/countdown), and game/combat_setup.py (new stepper row). These are also touched by the parallel UI cluster — must coordinate. The combat_config schema is explicitly LOCKED ('field names and defaults must not be changed without a full integrator sign-off'); adding n_transports/n_flagship/n_aaw/n_ground_attack/beachhead_grace_s requires that sign-off and matching clamp_config kwargs + clamp ranges + combat_setup rows + tests/test_combat_config.py updates.

6. Determinism contract: every new RNG (placement jitter, LCAC scatter) must use a fresh SeedSequence child tag off config.seed that does NOT collide with the existing tags ([seed,3]=fleet, [seed,4]=recon, [seed,5]=commander, [seed,6]=pantsir, [seed,7]=enemy radars). Reserve new tags (e.g. [seed,8]=amphibious, [seed,9]=ship-class placement) — coordinate tag allocation across clusters to avoid collisions.

7. victorious currently requires all self.ships dead. New combatant classes are in self.ships so they're covered automatically; but DECIDE whether transports/LCACs count toward victorious (recommend: they count as ships for the win, and separately drive the amphibious lose) — a one-line policy choice in the victorious property that the UI win-checklist must mirror.

8. UI cross-cluster: the fleet roster, per-contact class labels, HVU markers, threat strip, and beachhead countdown all feed the parallel 'more/high-quality UI' plan — hand those ui_needs to that cluster rather than building bespoke widgets here.

**Open questions:** 1. victorious policy: must the amphibious transports/LCACs be sunk to WIN, or only matter for the LOSE timer? Recommend ships-count-for-win + separate lose timer, but confirm with the win-condition owner (affects the win checklist UI and victorious property).

2. Flagship degradation magnitude: how hard should killing the hub nerf the fleet? Proposal = drop AWACS/flagship remote cueing (escorts → own-sensor only) + scale TRACK_FORM_S up ~1.5-2x. Needs a measured probe to tune so it's felt but not game-ending; lock with a two-sided statistical test like the existing SM-2 bands.

3. Should the carrier ALSO be a datalink contributor, or strictly dark (today it's dark)? Keeping it dark makes flagship-vs-carrier a meaningful distinction (flagship = findable hot hub, carrier = silent HVU). Recommend keeping carrier dark.

4. Amphibious counter-detection balance: how short should the LCAC 'ship' detection range be? Too short = unfair surprise; too long = trivial. Recommend tuning so the player can catch transports far out but must hustle on leaking LCACs — measure with a probe (mirror the drone-stealth kill-per-range methodology).

5. Default config posture: should the DEFAULT CombatConfig field the new classes (changing baseline balance) or keep them at 0/off so existing tests + the established Oniks-vs-SM-2 duel stay bit-identical, exposing the new classes only via the setup screen? Strong recommendation: default OFF (n_flagship=0, n_aaw=0, n_ground_attack=0, n_transports=0) to preserve all regression contracts; let the player opt in. Needs sign-off because it shapes the 'out of the box' experience.

6. Beachhead timer semantics: does ANY single LCAC in the box start an irreversible countdown, or does it require a threshold of craft / a sustained presence? Recommend: first craft in box starts a grace timer; killing all committed craft before expiry cancels it (gives the player a real save). Confirm the exact grace_s and whether multiple beachheads stack.

7. LCAC vs Pantsir/gun interplay: LCACs are surface, but the Pantsir/CIWS are air-defense — confirm the player has an effective SURFACE last-ditch against leaking LCACs (Oniks is overkill/slow to retask; maybe the Pantsir gun or a coastal gun should engage surface craft inside an inner ring). This may surface a small new player-weapon need (out of this cluster's scope but flagged).

Open-source grounding used: Wasp-class LHD (22 kt, well deck, 3x LCAC) and LCAC (40+ kt, 60-75 t, over-the-beach) for the amphibious model; CEC (single fused air picture, decentralized cue-vs-engage, no central node yet collapses when the netting hub is lost) for the flagship datalink-hub mechanic.


---
## Feature: ShipClass taxonomy: typed Destroyer subclasses (ground-attack / air-defense / general / flagship)  _(effort: M)_

**What it is + real-world grounding:**

Replace the single Destroyer with a small family of subclasses that differ ONLY in magazine loadout, enabled fire-control channels, HP/dims, and one commander-read doctrine flag. Grounded in real task-group role specialization: a US CSG mixes Tomahawk land-attack shooters (Arleigh Burke VLS heavy on TLAM), dedicated AAW pickets (Aegis BMD/AAW configured), general-purpose DDGs, and a command ship/flagship hosting the AAW commander. This is a re-skin + parameterization of the existing Destroyer, NOT new physics.

**Platform (launched from / carried by):**

Each is a surface combatant on the existing racetrack loiter (Destroyer base). Ground-attack = TLAM arsenal ship; air-defense = SM-2/SM-6 picket; general = balanced; flagship = command ship (CG/CGN-class). All sit in self.ships and feed the player contact board identically (fog of war: the player cannot tell classes apart on the map until SAR/ELINT characterizes them).

**Sensors (uses / detected by):**

All carry the existing SPY-1 Radar (sim/enemy_ships.py _SPY1_RANGES). Air-defense specialist gets a longer 'missile' detection range (better AAW radar) and the flagship's radar is flagged as a DATALINK HUB (see ai_brain). The player detects all classes via the same RadarNetwork horizon/terrain-LOS gate + drone SAR/ELINT — class identity is itself fog-gated (only revealed once imaged, mirroring known_enemy_sites latching).

**AI brain (how the enemy commander uses or counters it):**

The commander/defense layer reads each ship's role purely through its magazine state and a role attribute, never truth about the player. Concretely: ShipDefense already prioritizes by track/envelope; the air-defense specialist simply has more sm2/sm6 ammo and a higher SM2_MAX_INFLIGHT raid cap, so it naturally becomes the screen. The ground-attack specialist's big tomahawk_ammo is drained by EnemyCommander._fire_tomahawk_salvo / EnemyStrikeController (already iterates ship.tomahawk_ammo across hulls — it will pull from the TLAM ships first). No new brain logic for the basic three; the flagship adds the datalink-hub power (separate feature).

**Player UX:**

The player attacks all classes with the same Oniks/Zircon flow. Added UX: once a hull is imaged (SAR/ELINT classification), the tactical-map contact label and the contact info panel show the class (e.g. 'DDG-AAW', 'DDG-LAND', 'CG-FLAG') and a threat hint ('heavy SAM screen' / 'TLAM shooter' / 'datalink hub — high value'), so the player can prioritize. Before imaging it stays a generic surface contact.

**UI needs:**

Tactical map: per-contact class glyph/label once characterized (extends the existing contact_symbol + SITE_COL families). Contact info readout: class name + role hint + believed HP. Fleet roster strip (consolidated UI plan): one row per known enemy hull with class icon, alive/sinking state, and a HVU star on the flagship/carrier.

**Game-model mapping (reuse vs add):**

Subclass Destroyer in sim/enemy_ships.py (or a new sim/enemy_ship_classes.py to keep enemy_ships.py's locked tests intact). Reuse SHIP_TYPES registration pattern (Carrier already adds SHIP_TYPES['carrier']). Each class = a frozen ShipClassDef (role str, sm2/sm6/ciws/tomahawk ammo, sm2_max_inflight, hp, dims, radar_missile_range, is_datalink_hub) consumed in __init__ — mirrors how Carrier overwrites length/beam/height/hp/ammo. Magazines reuse the EXISTING channels in enemy_defense.py; no new SamDef needed (air-defense ship just stocks more SM2/SM6 from arsenal.py).

**Implementation sketch + test contracts:**

New file sim/enemy_ship_classes.py: SHIP_CLASS_DEFS dict + GroundAttackShip, AirDefenseShip, GeneralDestroyer(=today's Destroyer params), Flagship subclasses of Destroyer; register SHIP_TYPES entries for any new dims/HP. world/combat.py _spawn_ships: extend sample_fleet output consumption to instantiate the mix (see fleet-composition feature). enemy_defense.py: read ship.sm2_max_inflight (default SM2_MAX_INFLIGHT) instead of the module constant so AAW ships raid harder. EnemyDefenseController already covers Carrier (zero ammo = inert) so the new classes drop in. TEST CONTRACTS: tests/test_ship_classes.py — (1) each class instantiates with its def's ammo/hp/dims; (2) an AirDefenseShip fires more concurrent SM-2 than a GeneralDestroyer given the same raid (count inflight); (3) a GroundAttackShip is the first hull drained by a TLAM salvo (ammo accounting); (4) determinism: same seed → same class placement; (5) fog: the player contact board exposes no class field until _sensor_images characterizes the hull.


---
## Feature: Flagship / leader: CEC datalink hub whose death degrades the enemy AI  _(effort: M)_

**What it is + real-world grounding:**

A command-ship class whose ONLY special power is being the fleet's Cooperative Engagement Capability hub: it fuses and redistributes the shared air picture so escorts can form fire-control tracks on sensors they don't personally hold. Grounded directly in CEC — 'data from each unit is distributed to all other units... combined into a single common air picture', enabling 'decentralized targeting where a threat detected by one platform's sensors can be engaged by another's weapons'. Killing the hub collapses the netted picture: ships fall back to own-sensor-only, the commander loses its fused-track advantage. This is a SENSOR-HONEST AI nerf, not a stat debuff.

**Platform (launched from / carried by):**

CG/CGN-class command ship on the racetrack loiter, anchored centrally in the formation (near the carrier, inside the screen). High-value, lightly self-defended (modest SM-2), runs its radar HOT (it must, to be the hub) — which makes it ELINT-locatable, the player's path to finding and killing it.

**Sensors (uses / detected by):**

Its own SPY-1 radar PLUS it is the node returned by cue_radars_fn. Today _enemy_cue_radars returns AWACS + ground radars; the flagship's radar JOINS that list, and — the key mechanic — the cue set is GATED on the flagship being alive: with the flagship dead, cue_radars_fn returns only own-ship + (optionally) a degraded subset, so ShipDefense._detects falls back to own SPY-1 only for most escorts.

**AI brain (how the enemy commander uses or counters it):**

Pure fog-of-war: the flagship contributes track FORMATION (the CEC 'remote cue, local illumination' seam already documented in enemy_defense.ShipDefense._detects). While alive, every escort can form/engage tracks the flagship's radar or the AWACS holds before its own SPY-1 sees them (existing behavior). On flagship death: (a) cue_radars_fn drops the hub, so escorts lose remote cueing and engage later/less; (b) the commander's reaction quality drops — model as a confidence/cohesion penalty: raise TRACK_FORM_S for escorts and/or disable AWACS→ship cueing fusion, so the fleet visibly fights worse. NEVER reads player truth. Determinism preserved (no RNG added).

**Player UX:**

The flagship is the juiciest HVU after the carrier: kill it and the SM-2 screen gets sloppier (your Oniks leak more). The player learns this via the post-imaging class hint ('DATALINK HUB — degrades fleet on kill') and a tangible feel change. It runs its radar hot, so it's findable by ELINT triangulation faster than the silent carrier.

**UI needs:**

HVU marker (star/diamond) on the flagship once characterized; a transient 'FLEET DATALINK DEGRADED' event banner when it dies (mirrors the existing base_destroyed event → HUD cue). Fleet roster: flagship row flagged HVU. Optional: a small 'enemy coordination' status pip that drops after the hub dies.

**Game-model mapping (reuse vs add):**

Flagship subclass with is_datalink_hub=True. world/combat.py _enemy_cue_radars: append flagship.radar while alive; when no flagship alive, return the degraded cue set. EnemyDefenseController already takes cue_radars_fn — no signature change. The degradation knob is a field on ShipDefense (e.g. cohesion=1.0) the controller lowers when the hub dies, scaling TRACK_FORM_S; this is the documented 'remote cue, local illumination' contract extended.

**Implementation sketch + test contracts:**

sim/enemy_ship_classes.py Flagship(Destroyer, is_datalink_hub=True, modest sm2). world/combat.py: (1) _enemy_cue_radars adds the live flagship radar; (2) add self.flagship reference; (3) on flagship death, EnemyDefenseController.set_cohesion(degraded) bumps each ShipDefense's effective TRACK_FORM_S (new optional attr, default = module constant so existing tests unchanged); (4) emit a 'datalink_degraded' event for the HUD. TEST CONTRACTS: tests/test_flagship.py — (1) with flagship alive, an escort forms an SM-2 track via the flagship's radar cue before its own SPY-1 has LOS (assert launch occurs); (2) after flagship death the same geometry yields NO remote-cued launch (own-sensor fallback); (3) escort effective TRACK_FORM_S increases post-hub-death; (4) no truth read (mock the player at a position the flagship cannot physically detect → no cue); (5) determinism: identical battle replays bit-for-bit.


---
## Feature: Ground-attack specialist: massed Tomahawk barrage ship  _(effort: S)_

**What it is + real-world grounding:**

A surface combatant configured as a land-attack arsenal: a large Tomahawk magazine, minimal self-defense. Grounded in the real Burke 'land-attack' loadout where most of the 90 Mk-41 cells carry TLAM rather than SM-2 (the codebase already comments on this in enemy_ships.py _TOMAHAWK_AMMO_DEFAULT). It is the commander's KILL-doctrine fist: when the back-plot localizes a TEL cluster, this ship supplies the salvo.

**Platform (launched from / carried by):**

Destroyer-hull racetrack loiter, hanging back in the screen (TLAM has whole-map range, so it doesn't need to close). Large tomahawk_ammo (e.g. 24), small sm2_ammo (e.g. 6), zero/low sm6, normal CIWS. It depends on the AAW ships and flagship for protection — kill its escorts and it's exposed.

**Sensors (uses / detected by):**

Own SPY-1 for self-defense only. For OFFENSE it needs no organic sensor: Tomahawks are GPS/INS to the back-plotted coordinates (the existing TOMAHAWK_SALVO path fires at commander cluster centroids; terminal scene-matching via _refine_strike_aim). It relies on the side-level back-plot picture, not its own radar.

**AI brain (how the enemy commander uses or counters it):**

EnemyCommander._doctrine_kill already issues TOMAHAWK_SALVO at targetable clusters; _fire_tomahawk_salvo iterates ships drawing tomahawk_ammo. The only change: prefer ground-attack ships first (sort the salvo source list so TLAM banks empty before incidental rounds on other hulls). Fog-honest: fires only at back-plotted clusters (≥3 fixes within 3 km), which derive from sensor-detected missile tracks — never player truth. Saturation tactic emerges: a big bank lets the commander mass enough rounds to overwhelm the player's Pantsir (which caps at 3 in flight), making the lose condition reachable.

**Player UX:**

The player feels this as concentrated TLAM raids on the base once the launch site is back-plotted. Counter-play: keep the radar silent (no ESM fix → but TLAM uses back-plot of YOUR missile tracks, so the real counter is doglegging Oniks so the back-plot never clusters), saturate the Pantsir window, and SINK the TLAM ship early (its small SAM screen makes it soft once escorts are gone).

**UI needs:**

Class label 'DDG-LAND / TLAM shooter' once imaged; inbound-TLAM count on the threat strip (feeds the consolidated threat HUD); fleet roster shows its (believed) heavy land-attack role.

**Game-model mapping (reuse vs add):**

Reuses StrikeDef TOMAHAWK + StrikeMissile + the existing salvo path. No new weapon. Magazine via ShipClassDef(tomahawk_ammo big, sm2 small). The salvo-source ordering is a 2-line sort in _fire_tomahawk_salvo / EnemyStrikeController._fire_salvo.

**Implementation sketch + test contracts:**

sim/enemy_ship_classes.py GroundAttackShip(tomahawk_ammo=24, sm2_ammo=6, sm6_ammo=0). world/combat.py _fire_tomahawk_salvo: sort self.ships by (not is_ground_attack, ...) so TLAM banks drain first. TEST CONTRACTS: tests/test_ground_attack_ship.py — (1) a TLAM ship supplies a full SALVO_SIZE before any general destroyer's cells are touched; (2) with a ground-attack ship present the commander can mass ≥ Pantsir-cap rounds at a cluster (saturation reachable); (3) salvo fires ONLY at a targetable back-plot cluster, not at a believed-but-unconfirmed site (fog); (4) determinism.


---
## Feature: Air-defense specialist: the SM-2/SM-6 screen picket  _(effort: S)_

**What it is + real-world grounding:**

A dedicated AAW picket with a heavy SM-2 (150 km) + SM-6 (240 km) load and a higher concurrent-engagement cap — the ship that makes leaking an Oniks hard and reaches out to kill the recon drone / high flyers. Grounded in Aegis AAW-configured DDG/CG doctrine and the existing SM6 area-air role already written into enemy_defense.py (the SM-6 'reach out and force the player low' loop from GAME_ANALYSIS §7).

**Platform (launched from / carried by):**

Destroyer-hull picket stationed FORWARD in the screen (closer to the player than the carrier/flagship) so its envelopes cover the threat axis. Big sm2_ammo (e.g. 48) + sm6_ammo (e.g. 12), normal CIWS, little/no TLAM.

**Sensors (uses / detected by):**

Its SPY-1 gets the best 'missile' detection range of the surface ships (better AAW radar). It is a prime consumer of the flagship/AWACS datalink cue (forms tracks early). It also runs hot → ELINT-locatable, giving the player a way to find and kill the screen.

**AI brain (how the enemy commander uses or counters it):**

Already implemented in enemy_defense.ShipDefense (_try_sm2_launch / _try_sm6_launch / drone hunt). The ONLY change: this class raises its per-ship SM2_MAX_INFLIGHT (e.g. 6) and stocks more rounds, so against a salvo it spreads more shots and against a lone leaker it shoot-shoot-looks more. All decisions are on the dead-reckoned track PICTURE (no truth); SARH terminal still needs own-ship illumination (the documented seam). Physics-not-dice: kills emerge from SamMissile guidance + multipath/SNR noise.

**Player UX:**

The player feels a thicker SAM wall on the threat axis. Counter-play stays the codified loop: go lo-lo to exploit multipath, salvo to overwhelm the (still finite) inflight cap and magazine, or kill the picket first (it's forward and soft to a saturating Oniks salvo once you accept losses). Zircon high-profile is specifically countered by this ship's SM-6 — preserving the 'go low' loop.

**UI needs:**

Class label 'DDG-AAW / heavy SAM screen'; SM-2/SM-6 launch-warning cues already exist (launch_warning flag) — the threat strip should attribute inbound SAM density. Fleet roster role hint.

**Game-model mapping (reuse vs add):**

No new weapons (SM2, SM6 in arsenal.py). ShipClassDef(sm2_ammo=48, sm6_ammo=12, sm2_max_inflight=6). enemy_defense.py reads ship.sm2_max_inflight (fallback to the constant).

**Implementation sketch + test contracts:**

sim/enemy_ship_classes.py AirDefenseShip(...). enemy_defense.py: replace the bare SM2_MAX_INFLIGHT in _try_sm2_launch with getattr(ship,'sm2_max_inflight',SM2_MAX_INFLIGHT); same idea for SM6 if desired. world/combat.py: give this class a larger PLAYER-facing... no — only its OWN radar 'missile' range increases (in its ShipClassDef.radar_missile_range, applied to self.radar.ranges). TEST CONTRACTS: tests/test_air_defense_ship.py — (1) an AAW ship sustains more simultaneous SM-2 than a general destroyer in the same raid; (2) it engages a HIGH Oniks via SM-6 beyond the SM-2 band (existing SM6 area path) — kill fraction degrades monotonically with range (no flat plateau); (3) lo-lo Oniks still leaks at the spec band against it (multipath physics unchanged — guards balance); (4) no truth leak; (5) determinism.


---
## Feature: Carrier (high-value, runs dark, launches/recovers aircraft) — confirm + harden  _(effort: S)_

**What it is + real-world grounding:**

The carrier already exists (sim/enemy_air.Carrier): CVN HP 6, silent radar under the escort umbrella, damage-control burn containment, AirBase recovery site for fighters. Grounded in CVN doctrine: the carrier emits nothing (EMCON), shelters behind the AAW screen, and is the air-wing's home plate. This feature is about INTEGRATING it into the typed taxonomy and making 'kill the carrier' meaningfully cripple enemy air, not rebuilding it.

**Platform (launched from / carried by):**

Carrier(Destroyer) on a deep racetrack anchor (spawn_zones CARRIER band 240-330 km, usually beyond lo-lo reach). Hosts CARRIER_FIGHTERS parked fighters via AirBase; recovers RTB fighters. Zero offensive ammo (sm2/sm6/ciws/tomahawk = 0) — purely the HVU + airbase.

**Sensors (uses / detected by):**

Silent SPY-1 (emitting=False) so ELINT can't hear it — the player must find it by SAR imaging (the recon game) or by following its fighters/aircraft back. It contributes nothing to the enemy cue picture (doctrine: dark).

**AI brain (how the enemy commander uses or counters it):**

The commander already treats the carrier as an AirBase. New honest behavior: while the carrier lives it keeps generating sorties (CAP + strike packages from its deck); on carrier death those fighters can't rearm there (AirBase.update aborts rearm at a dead base — already implemented via _strand). So killing the carrier throttles the enemy air war over time — an emergent, sensor-free consequence. The carrier never reads player truth.

**Player UX:**

Carrier is the deepest HVU: reaching it is the hi-lo/Zircon/saturation game (spawn_zones puts it past lo-lo fuel range). Sinking it starves the air wing of rearm and is a major win-condition checkbox. UX: 'CVN — HVU, air-wing home' label once imaged; a 'sorties degraded' feel after it sinks.

**UI needs:**

HVU star on the carrier; fleet roster carrier row with air-wing status (believed fighters home); win-condition checklist surfaces 'CARRIER' as a discrete objective.

**Game-model mapping (reuse vs add):**

Already in code. Slot it into SHIP_CLASS_DEFS as the CARRIER role so the taxonomy + roster + win checklist treat it uniformly. victorious already requires all ships dead (carrier included).

**Implementation sketch + test contracts:**

Minimal: register Carrier in the ShipClassDef registry (role='carrier'); ensure _spawn_ships' new mixer always places exactly 1 carrier (it does today). Optional hardening: emit a 'carrier_sunk' event for the HUD. TEST CONTRACTS: tests/test_carrier_class.py (extend existing) — (1) carrier stays silent (ELINT never hears it); (2) after carrier death its parked/queued fighters strand and cannot rearm; (3) carrier counts toward victorious; (4) found only by SAR/visual, never ELINT (fog).


---
## Feature: Amphibious transport class + LCAC landing-craft model  _(effort: L)_

**What it is + real-world grounding:**

A new amphibious class: an LHD/LST-style transport that carries fast landing craft (LCAC). Grounded in open-source data — Wasp-class LHD: 22 kt, well deck launches up to 3 LCACs; LCAC: 40+ kt hovercraft, over-the-beach, 60-75 t payload, reaches >70% of coastlines. The transport approaches a launch line offshore, 'splashes' LCACs from its well deck, and the LCACs sprint to a coast landing box.

**Platform (launched from / carried by):**

Two-tier platform: (1) Transport (Destroyer-hull racetrack→beeline nav, slow ~11 m/s, modest HP, light self-defense) that, on reaching a LAUNCH LINE offshore, spawns (2) LCAC craft (small fast surface entities, ~20 m/s, very low HP, no weapons) that beeline to a fixed coast LANDING BOX near the player base. Both are Oniks/Pantsir/gun targetable surface entities in self.ships-equivalent lists.

**Sensors (uses / detected by):**

Transports + LCACs are detected by the player exactly like ships (RadarNetwork horizon/terrain-LOS at 'ship' class; drone SAR images them). LCACs are small/low → short horizon detection (set a small 'ship' RCS-equivalent range, like the drone's stealth gating) so they're hard to catch close in — the player must engage the transports far out or the LCACs in the gap. They carry no radar (emit nothing; ELINT-invisible — find them by SAR/radar only).

**AI brain (how the enemy commander uses or counters it):**

The commander sequences the landing on its sensor picture only (a new _doctrine_amphibious): hold transports back until the AAW screen is forward and (optionally) the player's base is believed suppressed/back-plotted; then order TRANSPORT_RUN — transports turn from loiter to the launch line; at the line they LCAC-splash; LCACs run the box. If transports take fire (the commander senses player missile tracks near them via the picture), it may abort/scatter or push harder on a timer. Never reads player truth — it reasons from EnemyPicture missile tracks + believed base state. Determinism: launch-line/box and any scatter jitter via a SeedSequence child.

**Player UX:**

A hard, visible race: imaged transports show a 'LANDING FORCE — sink before it lands' label and a countdown to the landing box. The player must re-task Oniks from the carrier hunt to the beach defense — a genuine priority dilemma. LCACs are fast and many: the player uses Oniks on transports (kill the source) and Pantsir/gun on leaking LCACs. Sinking a transport in its well-deck-loading phase (at the launch line) kills its embarked LCACs (high-value moment).

**UI needs:**

Mission objective banner + countdown timer (new HUD element: 'AMPHIBIOUS THREAT — T-minus MM:SS to landing'); landing-box marker on the tactical map; transport/LCAC distinct glyphs; a beach-defense alert when the first LCAC crosses an inner range ring. This is the cluster's biggest NEW UI surface.

**Game-model mapping (reuse vs add):**

New sim/amphibious.py: Transport(Destroyer subclass for nav/damage reuse) with a launch_line and an embarked_lcac count; Lcac (lightweight Ship-like entity: pos/vel/heading/state ladder, hp=1, OBB for Oniks/gun hits). Both live in self.ships (so the contact board + OBB damage sweeps + tactical map work unchanged). Landing box = a fixed XZ + radius near BASE_POS. The landing lose-check is a new world property (see next feature).

**Implementation sketch + test contracts:**

sim/amphibious.py (Transport, Lcac). world/combat.py: spawn transports via the fleet mixer when config.n_transports>0; step transports/LCACs in step() (reuse the ship update loop or a dedicated _step_amphibious); LCAC-splash spawns Lcac entities at the transport on launch-line arrival. Commander: sim/commander.py _doctrine_amphibious emits TRANSPORT_RUN / LCAC-splash intent; world executes. TEST CONTRACTS: tests/test_amphibious.py — (1) a transport reaching the launch line splashes the right LCAC count; (2) sinking a transport before the line removes its embarked LCACs from ever spawning; (3) LCACs beeline the box and are Oniks/Pantsir-killable (OBB hit → dead); (4) the commander only orders TRANSPORT_RUN from its picture (no truth); (5) determinism (same seed → same launch line, box, scatter).


---
## Feature: Amphibious landing as a TIMED lose condition + win/lose integration  _(effort: M)_

**What it is + real-world grounding:**

The amphibious force is a second, race-against-the-clock LOSE path orthogonal to 'all TELs destroyed': if a landing force gets ashore, the beachhead overruns the Bastion. Grounded in coastal-defense doctrine — the whole point of a Bastion missile battery is to deny the sea approach; letting troops land is mission failure regardless of whether the TELs survive. Mechanic: when any LCAC reaches the landing box, a BEACHHEAD timer starts; if it isn't cleared (all landed/landing craft killed) before it expires, the player loses.

**Platform (launched from / carried by):**

N/A (a world-state rule), driven by the Lcac entities reaching the landing box near BASE_POS.

**Sensors (uses / detected by):**

The lose check is a world-truth rule (like defeated/victorious — these read sim truth for OUTCOME, which is allowed; only the AI brain is forbidden truth). The player's AWARENESS of the threat is fog-gated (they see transports/LCACs only once imaged), which is the tension: an un-imaged landing force is a nasty surprise.

**AI brain (how the enemy commander uses or counters it):**

The commander's amphibious doctrine TRIES to make this condition fire (sequence transports in once the screen/suppression supports it), all from its sensor picture. It will time the landing run to coincide with a TLAM saturation strike (the ground-attack ship) so the player is forced to split attention — an emergent combined-arms push.

**Player UX:**

Two ways to lose now (TELs destroyed OR beachhead established) and the win condition optionally gains an amphibious clause. Clear feedback: a prominent countdown when a beachhead forms, a DEFEAT banner variant ('BEACHHEAD ESTABLISHED — DEFEAT') distinct from 'BASTION DESTROYED'. Counter-play: kill every landing craft before the timer, or sink transports before they splash.

**UI needs:**

Beachhead countdown HUD (reuses the DEFEAT banner panel style); a distinct defeat-cause banner string; objective tracker in the consolidated UI ('LANDING FORCE: N transports / M LCACs remaining'); map landing-box highlight that pulses when a craft is inside it.

**Game-model mapping (reuse vs add):**

New CombatWorld properties paralleling defeated/victorious: amphibious_threat (any transport/LCAC alive & committed), beachhead_timer, and an extended defeated that also trips on beachhead expiry. HUD reads them like it reads defeated today (game/hud.py lines ~309 banner block). config.n_transports + landing geometry constants.

**Implementation sketch + test contracts:**

world/combat.py: add _step_amphibious bookkeeping; properties beachhead_active/beachhead_left; extend defeated to OR the beachhead-expired case (keep the bastion_tel clause). game/hud.py: add the countdown + cause-specific banner (mirror DEFEAT_TEXT/VICTORY_TEXT block). world/combat_config.py: n_transports (CLAMP_TRANSPORTS, default 0 so existing scenarios/tests are unchanged) + beachhead_grace_s. combat_setup.py: add an ENEMY TRANSPORTS stepper row. TEST CONTRACTS: tests/test_amphibious_objective.py — (1) an LCAC in the box starts the beachhead timer; (2) clearing all craft before expiry cancels the loss; (3) timer expiry sets defeated with cause='beachhead'; (4) n_transports=0 reproduces today's behavior exactly (defeated only on TELs) — regression guard; (5) determinism. tests/test_combat_config.py: clamp_config round-trips n_transports/beachhead_grace_s.


---
## Feature: Fleet composition + seeded placement for the typed task group  _(effort: M)_

**What it is + real-world grounding:**

Generalize world/spawn_zones.sample_fleet (today: 1 carrier + N generic destroyers, 2 as escorts) into a doctrinally-shaped task group: carrier (deep), flagship (central, with the carrier), AAW pickets (forward screen), ground-attack ships (mid), general destroyers (fill), and transports (rear, deep, screened — they commit late). Grounded in CSG screen geometry: HVUs (CVN, flagship) centered, AAW pickets on the threat axis, amphibs protected in the rear until the landing phase.

**Platform (launched from / carried by):**

N/A (placement layer feeding _spawn_ships).

**Sensors (uses / detected by):**

Placement respects the existing open-water + separation contracts (is_open_water 9 km disc, MIN_SEPARATION 25 km). Forward pickets sit in the main zone (110-300 km, mode 180); carrier/flagship/transports in the deeper band; classes are placed by ROLE so the screen geometry is doctrinally sensible yet fully fog-gated to the player.

**AI brain (how the enemy commander uses or counters it):**

No brain change — but the resulting geometry is what the commander's screen/landing sequencing assumes (pickets forward, amphibs rear). The mixer is deterministic so the commander's plan replays identically.

**Player UX:**

The player faces a believable formation: a SAM wall up front, HVUs deep, a landing force lurking. Recon priorities emerge (find the pickets to plan a leak, find the carrier/flagship/transports to win/survive).

**UI needs:**

None new (feeds the roster/map features above). The setup screen exposes the per-class counts.

**Game-model mapping (reuse vs add):**

Extend sample_fleet to return a typed roster: {'carrier':xz,'flagship':xz,'aaw':[...],'ground_attack':[...],'general':[...],'transports':[...]}. Keep the LOCKED test contracts (deterministic, open water, separation, sector). _spawn_ships maps each list to its class. Counts come from CombatConfig (new fields n_flagship(0/1), n_aaw, n_ground_attack; n_destroyers stays = general).

**Implementation sketch + test contracts:**

world/spawn_zones.py: add typed bands (flagship near carrier ring; transports in a deep rear band; aaw biased toward ZONE_RANGE_MIN; ground_attack mid). world/combat.py _spawn_ships: instantiate per role from sim/enemy_ship_classes.py + sim/amphibious.py. world/combat_config.py: new count fields + clamps (defaults chosen so the DEFAULT config ≈ today's balance + the new classes off/optional to keep regressions green). TEST CONTRACTS: tests/test_spawn_zones.py (extend) — (1) typed roster keys present; (2) carrier+flagship in the deep band, aaw forward, transports rear; (3) all hulls open-water + ≥25 km separated regardless of mix; (4) deterministic per seed; (5) requesting 0 of a role yields an empty list (and the DEFAULT config still produces a playable, regression-safe fleet).
