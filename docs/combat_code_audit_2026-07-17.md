# Combat core audit — 2026-07-17

Solo deep-read audit (user law: no subagent fleets). Scope: every line of the
combat core — `sim/` (all 37 modules), `world/combat.py` + `combat_config`,
`engine/particles.py`, the effects/event consumers in `game/sandbox.py`,
launch/orbit/manpads visual renders. UI layers (hud/tactical_map/forensics),
mesh builders in `models/`, and the cloud/graphics stack were reviewed
structurally only (clouds have their own recent audit trail).

Verdict: **FIX-THEN-SHIP.** The sim core is genuinely excellent — honest
sensors, honest energy physics, no truth leaks found in any enemy decision
path. The findings below are a handful of seams, one law violation, and one
visually-missing flagship moment.

---

## 🔴 FIX NOW

1. **CIWS / Pantsir gun kills are dice rolls** — the last flat probability
   roll in the kill chain. `sim/ciws.py:186-192` and
   `sim/pantsir.py:346-353`: `rng.random() < lerp(Pk)` → `target.alive=False`.
   Violates the project's physics-not-dice law that every other system
   (multipath, stealth-SNR, seeker baskets, MANPADS) obeys.
   → Fix direction: model each burst as an aim-point with an OU tracking
   error (the multipath pattern) plus round dispersion; a kill = the
   dispersion cone geometrically sweeping the target's crossing extent.
   Calibrate to the current measured Pk bands with a probe so gameplay
   balance is unchanged.

2. **`magazine_detonation` has no dedicated effect/audio.** The subsystem
   damage model's Moskva-scale catastrophe event falls into the generic
   `else` in `game/sandbox.py:1352` → `EXPLOSION_SCALE_GROUND` (1.3) —
   *smaller* than a routine ship hit (1.6). `damage_model.fireball_radius_m`
   (Hopkinson-Cranz, "for visuals") is defined at `sim/damage_model.py:155`
   and never called anywhere. The most dramatic outcome in the game is
   visually indistinguishable from a dud.
   → Add a bespoke handler: flash + fireball scaled by `cookoff_tnt_kg` via
   `fireball_radius_m`, tall column, debris ring, delayed heavy boom.

3. **Dead guidance path + doc rot in `sim/sam.py`.**
   `_aim_direction` (573-657, incl. loft/energy-cruise/follow-the-fall
   logic) and `_steer_accel` (804-826) are no longer called by production
   `update()` — midcourse now flows through the online flight computer.
   They are only exercised by `tests/test_aero.py:199` and
   `tools/probe_energy_bleed.py:87` (green tests on a dead path = false
   confidence). `MID_AIM_TAU_S` (sam.py:165) and `_dt_last` (sam.py:928)
   are fully dead — the aim-filter their comments describe no longer
   exists. `sim/arsenal.py:178` still documents `_aim_direction` as the
   loft consumer.
   → Delete the dead pair (or fold their unique energy-cruise math into the
   FC-path comments), retarget the tests at `_flight_computer_step`, fix
   the arsenal comment.

4. **The MANPADS audit scenario misses both scripted shots.**
   `tools/shoot_manpads.py` (run 2026-07-17) prints `igla kill: False` and
   `starstreak kill: False (closest 30.62 m)`; the intercept frame shows
   the trail curving past with no burst. Since f7bda5a ("honest endgame
   physics") the shipped audit no longer ends in kills — either the CLOS/
   PN retune broke the envelope or the audit scenario is stale. Feature is
   one day old; find out now while it's cheap.
   → Add a headless flyoff probe (the probe_kh31p pattern) with a
   two-sided hit/miss envelope per weapon, then re-shoot the visual audit.

## 🟡 OK FOR NOW

- **Doc rot in arsenal:** KH31P block self-contradicts (`short at 140 km`
  table vs `kills 60-140, short at 160` field comment; stale "43 kg of the
  63 kg budget" line — arsenal.py ~547/562/592). `WEAVE_G` (missile.py:264)
  is a dead constant with a live-looking comment (weave reads
  `weapon.terminal_weave_g`). `sim/manpads.py:26` claims its 320 m/s
  speed-of-sound "matches sim/missile.py" (that uses 340.3/295.1).
- **Speed-of-sound seam:** 2.3 m/s discontinuity at the 11 km tropopause
  (`sim/physics.py:20-22`; lapse 0.0039 vs ISA-consistent 0.00411).
- **RWR LOCK reads intent, not physics:** `sim/recon.py` RwrReceiver keys
  LOCK off `missile.target is drone`. A real RWR senses illumination — an
  ARH round in midcourse or a command-guided round would show nothing.
  Also `_states` grows unbounded (dead missiles leave CLEAR entries).
- **Structures are flat 1-hp-per-hit:** a 109 kg JASSM and a 450 kg TLAM do
  identical damage to a TEL (`sim/bases.py`). Ships got the warhead-scaled
  subsystem model; ground structures didn't.
- **CIWS never engages pure crossers** (`closing <= 0` gate) — defensible
  doctrine-wise, but combined with the dice-roll fix a geometric model
  would handle it naturally.
- **Particles:** pools are depth-sorted internally but never interleaved
  across pools (spray can draw over nearer smoke). Launch smoke columns
  read as discrete blobs in the strips — larger sprites at lower alpha or
  higher emission with `fade_in` would read as a continuous column. Combat
  mode passes no `wind` to `Effects.update` (game/sandbox.py:1368) so
  columns stand perfectly still (the cinematic pool already threads wind).
- **No gun visuals:** CIWS/Pantsir gun = 3 grey puffs at the target only —
  no muzzle flash, no tracer stream (game/sandbox.py:1336). Reads as
  nothing happening.
- **No cruise plume for strike missiles** (documented Phase-7 backlog) —
  Tomahawk/JASSM/HARM-sustain are visually naked in cruise.
- **Proxy meshes:** kalibr, buk_9m317/9m338, asbm, swarm loiterer render as
  stand-in models (game/testing_catalog.py PROXY entries).
- **MANPADS view-models are placeholder-grade:** bare untextured cylinders
  with a visually detached grip cylinder; the eject flash is a large white
  blob that reads as an explosion (renders/manpads_audit/22, 23, 24).
- **Enemy aircraft are kinematic movers** (instant speed changes, fixed
  altitudes) while missiles pay full energy physics — a fidelity mismatch,
  acceptable as an abstraction.
- **Fighter takeoff/climb ignores terrain under the climb-out** (fine on
  current maps).
- **Unknown event kinds silently become ground explosions** (the `else` in
  the sandbox event loop) — the same seam that swallowed
  `magazine_detonation`; consider logging unknown kinds in debug.

## ⚪ UNVERIFIABLE (needs data that doesn't exist yet)

- **MANPADS kill envelopes vs the published systems** — no flyoff probe
  table exists for Igla/Stinger/Piorun/Starstreak (unlike Kh-31P/ASBM/Buk,
  which have measured two-sided envelopes). Until a probe exists, whether
  a 6 km Igla shot at a crossing S-300 SHOULD kill is untestable.
- **Perceived quality of intercept/hit-cam moments in motion** — statics
  look right; the mandated human playtest (project memory) is still the
  open gate.

## SOLID (what genuinely holds up)

- **No cheating found anywhere in the enemy kill chain.** Every decision I
  traced reads sensor stores only: SPY-1/AWACS scan-paint schedules →
  1.5 s track formation → dead-reckoned fire-control picture → SM-2 flies
  the picture with live SARH illumination checks → terminal PN on truth
  degraded by physically-modeled multipath/SNR noise → fuse on truth.
  Launch-site discovery is honest back-plotting of first-detection tracks;
  ESM fixes accrue only while the radar actually emits; EMCON, decoys,
  corner reflectors, and the jammer all work through real sensor events.
- The **energy model** (q-limited g, induced-drag turn tax, autopilot lag,
  thrust spool) is uniformly applied across all missile families with
  per-weapon derivations documented against research notes and probes.
- The **flight computer** (receding-horizon corridor planner with terminal
  feasibility, energy fallback, corridor hysteresis) is genuinely
  sophisticated and deterministic.
- The **launch sequences** are researched and staged correctly per weapon:
  Oniks hot in-tube ignition → ride-out → pulse-jet pitch-over → cap
  jettison (physical falling part) → Mach-2 burnout slug ejection; S-300
  cold catapult → ballistic hang → delay-unit ignition fireball + donut;
  VLS cold-gas TLAM; rail-launch Pantsir/Buk; air-drop JASSM/HARM.
- The subsystem damage model (deterministic module grids, flooding,
  DC-party fire logistic, cook-off energetics) is well grounded.

## Renders produced for this audit

- `renders/launch/oniks_strip.png`, `renders/launch/s300_strip.png`
- `renders/audit_2026-07-17/` (bastion/s300/pantsir/destroyer orbit sheets)
- `renders/manpads_audit/` (full walk-mode weapon audit set)
