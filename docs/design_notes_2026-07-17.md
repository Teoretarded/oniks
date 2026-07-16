# Design notes — 2026-07-17 autonomous run (lists only)

## 1. Your questions, answered

### "Is the missile genuinely there — seeker, flight computer, fins?"
- YES, per-missile live state: position/velocity (float64), fuel mass that
  burns at thrust/(Isp·g), its own seeker clocks, its own flight computer
  instance, its own autopilot lag state. Nothing is "just rendered".
- The SEEKER is real logic: acquisition needs range + gimbal cone + radar
  horizon + terrain line-of-sight; a held lock re-checks LOS on a cadence
  and BREAKS (round goes stupid on the frozen point). SARH rounds die when
  their ship stops illuminating.
- The FLIGHT COMPUTER is real: `sim/flight_computer.py` re-plans 2-4x/s,
  rolls out candidate vertical corridors against terrain/fuel/terminal
  energy, and the 120 Hz autopilot flies its command.
- The FINS are abstracted one level up: no per-fin deflection sim; instead
  commanded g is capped by q·S·CLmax/m (no airspeed = no authority), fins
  "bite" through a first-order lag (0.15-0.4 s), and every g of lift is
  paid in induced drag. The visible body attitude leads the path with an
  AoA clamp. This is the standard middle fidelity between point-mass and
  full 6-DOF — a 6-DOF fin sim would cost ~10x CPU for the same outcomes.
- "The missile is blind until it knows": holds. Midcourse flies the stale
  dead-reckoned CONTACT picture; only a locked seeker sees truth (through
  modeled noise); the proximity fuse resolves on truth.

### "Can AI test how the flight computer thinks?" — YES, built this run
- `tools/probe_fc_transcript.py` — flies a real missile headless, writes
  one JSON line PER REPLAN: every candidate corridor the FC considered
  (feasibility, cost, predicted terminal speed/fuel/clearance) + what it
  chose + commanded gamma. Then grades: time-of-flight vs the physics
  bound, arrival speed, corridor chatter, infeasible fraction.
- Measured today: Oniks 250 km hi-lo = 1.107x the ideal time (healthy);
  Zircon 250 km = 1.164x, arrives Mach 4.1 (in the combat band).
- The "optimal path" reference already exists in `sim/optimal_guidance.py`
  (minimum-effort ZEM + GENEX laws) — a future step can fly the same
  mission under the optimal law and diff the trajectories automatically.
- `tools/record_missile_chase.py` — the "AI can also SEE it" half: real
  app, real launch pipeline, chase camera → per-frame PNGs + 1:1
  telemetry.json + contact strips + chase.mp4. Frame N pairs with
  telemetry row N, so a reviewing AI cites the number AND the picture.

### "Does the enemy have a real brain? Is it smart? Does it try to destroy me?"
- YES it has a brain (sim/commander.py) and NO it never cheats (verified
  line-by-line: every decision reads its own sensor picture).
- What it genuinely does: Find→Blind→Kill doctrine; ESM-localizes your
  radar (90 s of your emissions); back-plots your missile launches to the
  coast and clusters 3 fixes into a targetable site; HARM packages at your
  radar BEFORE JASSM packages at your TELs; Tomahawk salvos at clusters;
  AWACS flees your missiles with anti-strobe EMCON; ships silence radars
  when your drone snoops and re-emit under attack; ARM-EMCON darks radars
  your Kh-31P threatens; jammer stations itself on the believed bearing of
  your loudest emitter; releases the amphibious force once your base is
  localized; fighters get vectored at drone tracks and break+dive when a
  SAM guides on them.
- Where it is NOT smart yet (improvement list, no fixes made):
  1. No raid coordination: Tomahawk salvos fire on cooldown, not massed
     for simultaneous time-on-target from multiple ships/axes (your swarm
     pods do this; the enemy doesn't).
  2. No EMCON deception: it never blinks radars to poison your ELINT
     triangulation baseline, never uses the carrier as a silent trap.
  3. No adaptive weaponeering: JASSM/HARM package sizes are fixed (2x2);
     it never scales a package to observed Pantsir/S-300 performance.
  4. No BDA-driven re-strike logic beyond emitter-alive belief: a
     surviving TEL that stops firing is forgotten rather than re-cued.
  5. Fighters never fly SEAD escort with the strike package or drag SAMs.
  6. It cannot learn your patterns (e.g. your dogleg launch doctrine
     defeats back-plotting forever; a smarter brain would widen clusters).
  7. Sub threat belief decays on a timer, not on searched-area reasoning.

### "The P-800 launches very inaccurately" + "grid launches"
- Checked the launch pipeline end-to-end (strip renders + kinematics
  probe): the sequence follows the researched beats (hot in-tube ignition,
  ride-out, pulse-jet pitch-over, cap-off, boost) and the trajectory
  converges onto the route bearing.
- Possible reads of "inaccurate", each checkable next session with you:
  1. The pitch-over visually overshoots/undershoots the route bearing
     before correcting (chase.mp4 from the new recorder will show it).
  2. The muzzle/ride-out effects sit slightly off the canister mouth.
  3. "Grid fins" — the real P-800 has no grid fins (Iskander/N1 style);
     the model correctly doesn't either. If you meant grid fins on the
     S-300/48N6: also not present on the real 48N6.
- Need your eyes on renders/launch/oniks_strip.png + renders/chase/oniks/
  chase.mp4 to pin what looks wrong to you.

## 2. UI / tactical map — findings list (NOT fixed; needs your taste)
1. LMB on the map means five different things depending on invisible
   state (round selected → REDIRECTS the round; buoy mode armed → drops a
   buoy; drone platform → hint; Bastion+Kh-31P → emitter pick; else
   contact/coordinate pick). There is no persistent "CLICK MODE" chip.
   This is the single biggest "confusing af" driver I found.
2. DANGEROUS: with one of your rounds selected, a stray LMB on empty sea
   RETARGETS the live round there instantly — no confirm, no undo
   (tactical_map.py `_retarget_selected`). An accidental click wastes an
   Oniks. Suggest: require a second click or a modifier to confirm.
3. Own missiles have pick priority over contacts — with rounds in the
   air you often can't click the contact under them (PICK_RADIUS 16 px).
4. Selecting a round on the map also hijacks the 3D camera
   (`sandbox.followed = m` + rig retarget) — surprising side effect.
5. RMB with an S-300 round selected silently does nothing (no hint),
   while RMB with the S-300 platform active shows a hint — inconsistent
   refusal feedback.
6. Waypoint cap refusals are silent ("refuses silently" by design) —
   at least flash the existing hint line.
7. hud.py was NOT line-audited this run (structure looks disciplined);
   map draw layers (rings/overlays) not audited pixel-by-pixel either.

## 3. Pre-existing bugs found (listed, NOT fixed — need judgment)
0. `tests/test_s300_rounds_distinct.py::test_both_rounds_kill_high_in_envelope_target`
   FAILS in the current tree (pre-existing — fails with and without this
   run's changes): a 48N6 shot at a 15 km-high target at 120 km flies a
   PERFECT guidance solution (LOS error ~0 deg the whole endgame) but
   bleeds to its 250 m/s self-destruct floor 3.3 km short — an honest
   energy death at the envelope edge. The FC's level 14.8 km coast for
   the last 35 km is the expensive choice; needs the 40N6-style corridor
   retune (your balance call, the 49-case-matrix game).
1. `tests/test_swarm.py::test_swarm_saturates_point_defense` FAILS in the
   current tree (lone swarm round leaks on 1 of 3 seeds, hits [0,1,0]) —
   PRE-EXISTING: fails identically with the old dice gun restored; came
   in with the previously-uncommitted flight-computer-era delta. Needs a
   tuning pass on the SM-2-vs-slow-skimmer chain, which is your balance
   call.
2. Zircon arrives with EXACTLY 0.0 kg fuel on a 250 km hi-lo shot
   (probe_fc_transcript) — the terminal dive is partly unpowered; the
   arsenal comment promises a powered dive. Retune isp/fuel or accept.
3. Boost plume reads as a popcorn chain of discrete fireballs from chase
   distance (renders/chase/oniks/strip_0.png frames 3-6) — cosmetic.
4. Combat-mode smoke ignores wind (engine supports it; sandbox passes
   none — game/sandbox.py:1368). One argument once you pick the wind
   source for the combat map.
5. RWR LOCK reads `missile.target` identity (truth-ish) instead of
   illumination physics; RwrReceiver._states grows unbounded (cosmetic
   memory growth) — sim/recon.py.
6. Ground structures take flat 1 hp per hit regardless of warhead
   (JASSM 109 kg == TLAM 450 kg vs a TEL) — ships got the subsystem
   model, structures didn't.
7. Speed-of-sound has a 2.3 m/s step at the 11 km tropopause seam
   (sim/physics.py lapse 0.0039 vs ISA-consistent 0.00411).
8. `Ciws` gun never engages purely-crossing targets (closing<=0 gate) —
   now partially superseded by the servo-lag dead zone, but the gate
   still hard-stops engagement the instant closing goes negative.
9. Kalibr / Buk rounds / ASBM / swarm loiterer fly PROXY meshes
   (testing catalog marks them) — dedicated models missing.
10. MANPADS view-model polish items are the other session's list
    (chunky Starstreak aiming unit; bare-cylinder tubes; big white eject
    blob) — hands off per your instruction.

## 4. How I'd add the new content (implementation sketches)
- Each entry: what it reuses, what's new, the counterplay.
1. SeaRAM/RAM inner layer (enemy ships)
   - Reuse: SamMissile machine verbatim + a small SamDef (11 kg round,
     10 km, IR-class terminal = no illuminator, high g, tiny fuse).
   - New: a `ram_ammo` magazine + launch gate in ShipDefense between
     SM-2 min range and CIWS range.
   - Counterplay: saturation still wins (RAM magazine is 21 rounds);
     your swarm becomes the counter to the counter.
2. Kh-35 cheap subsonic sea-skimmer (player quantity round)
   - Reuse: the ENTIRE Missile machine — it's a WeaponDef with subsonic
     numbers (M0.85, 130 km, 145 kg warhead) + a new ammo pool + HUD row.
   - Counterplay: SM-2 multipath already models why skimmers leak; the
     enemy's inner layers matter more against volume.
3. MALD-style decoy missile (player)
   - Reuse: StrikeMissile flight + `radar_size="missile"` so every enemy
     sensor/track/SM-2 path engages it with zero new enemy code.
   - New: tiny warhead-less def + pool; forensics tag so the debrief
     shows SM-2s wasted.
   - This is the highest gameplay-value/lowest-code item on the list.
4. LRASM-class stealthy enemy skimmer
   - Reuse: StrikeMissile + `radar_size="stealth"` (your radar already
     has a stealth ring) + the existing terminal seeker basket.
   - Counterplay: your CBR's tall mast + IRST (below) become the answer.
5. IRST sensor node (player)
   - New small module: passive IR detection = f(target IR signature ∝
     thrust/Mach, range, weather attenuation); plugs into radar_net as a
     paint_fn-style gate that ignores jamming/EMCON but hates rain.
   - Counterplay for the enemy: weather + terrain masking still work.
6. Satellite recon pass (player)
   - New: an orbital schedule (deterministic ephemeris from seed); at
     each pass, a SAR-strip snapshot injected like the drone SAR gate.
   - Enemy counterplay: the commander already has EMCON; add "hide
     during predicted pass windows" as its 8th doctrine rule.
7. ASW helicopter (player)
   - Reuse: Aircraft racetrack + AcousticReceiver with a MOVING single
     buoy (the dipping sonar is a buoy that relocates on command).
   - Completes the sub loop: datum → dip → cross-fix → ASROC.
8. Towed decoy (Nulka) for enemy ships
   - Reuse: the corner-reflector bias pattern, applied to the terminal
     seeker: a decoy point offset from the hull that captures a lock
     whose quality is below a threshold. Physics: seduction emerges from
     track error vs decoy offset, no roll.
9. Night battles
   - Reuse: cinematic light moods (already baked) + existing effects
     (additive fire already night-agnostic); main work is HUD/map
     readability + searchlight/flare effects.
10. Real-world combat map
    - Reuse: the whole cinematic LiDAR pipeline (fetch → HeightField);
      `CombatConfig.map_preset` already swaps `height_field` everywhere
      (the M3 one-terrain-truth seam) — a real coastline preset is
      mostly data plumbing + spawn-zone re-probing.
11. Sea-state ↔ multipath coupling
    - One line of physics: scale MULTIPATH_SIGMA_M by
      sea_clutter-style factor of config.sea_state. Makes weather a
      tactical weapon; re-run the SM-2 statistical probes to re-pin.

## 5. AI-testability roadmap (what future sessions get from this run)
1. probe_fc_transcript.py — FC reasoning as data (built, run, committed).
2. record_missile_chase.py — missile flight as video+telemetry (built).
3. probe_gun_physics.py — gun calibration bands (built).
4. Existing: blackbox digests, forensics stamps, per-weapon flyoff
   probes, launch strips, orbit sheets, screenshot harness scenes.
5. Missing (next): a scenario DSL for one-command seeded engagements
   ("spawn X at Y, fire Z, assert band"), an intercept-geometry recorder
   (both trajectories + miss vector plotted), a HUD/map screenshot diff
   harness for UI regressions, and wiring probe summaries into pytest
   bands automatically (measure → pin in one step).
