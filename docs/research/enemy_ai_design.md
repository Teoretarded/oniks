# Smarter sensor-driven enemy AI — design & plan (2026-06-15)

Grounded in the measured systems audit (tools/probe_audit_*.py + the workflow
synthesis). Goal: make the enemy (planes + AWACS especially) genuinely smarter
WITHOUT cheating — every decision reads only the sensor-derived `EnemyPicture`
(sim/commander.py), never ground truth. Determinism contract preserved (all RNG
via seeded child streams). "Physics not dice" preserved/extended.

## What the audit established (so we build on facts, not vibes)
- Sensor PHYSICS and the fog-of-war contract are sound & deterministic. No truth leak.
- Ship SPY-1 / AWACS / fighter nose radar all work (horizon-honest, range-class gated).
- Drone RWR (SPIKE/LOCK) + ELINT geolocation work (~1.3–3.6 km fix after ~2 min cross-track).
- KEYSTONE GAPS:
  1. **SM-6 is a paper weapon** — `_try_sm6_launch` reads the 30 km SPY-1 *stealth*
     range and iterates **only drone tracks**; it never engages missiles/aircraft
     despite its docstring, and can only fire in a 22–30 km sliver.
  2. **AWACS has zero EMCON** — never goes silent; a free always-on beacon.
  3. **Tracks carry no quality/confidence** → the brain can't weight fusion.
  4. **Fighter nose-radar returns are computed then discarded** (one reacquire gate);
     fighters can't act on their own sensing, and evasion only triggers near a
     *friendly* S-300 instead of on a real RWR/incoming-SAM threat.
  5. CIWS kill is a flat `random()<pk` dice roll (violates the project "physics not dice" law).
  6. Dead code: KnownStructure store unwired; a no-op line in `process_missile_track`;
     `picture._back_plots` raw list never pruned.

## LOCKED CONVENTIONS (freeze before any code)
- Axes X=east, Y=up, Z=north; heading 0=+Z CW. SI units. float64 in sim/world.
- No GL imports under sim/ or world/. No `Date.now`/wallclock/`random.random()` in sim
  decision paths — RNG only via seeded child streams (SeedSequence [seed, tag]).
- The enemy AI reads ONLY EnemyPicture / RWR-equivalent sensor state. NEVER reads a
  real entity position, fuel, or alive flag to make a decision. (Render/sweep code may.)
- New tuning constants: named, unit-suffixed, with a justification comment.
- Tests are the spec: an agent/impl that can't pass a planned test reports BLOCKED;
  it never weakens an assertion. Tolerances change only with better evidence, argued
  in the commit/log.
- Every change: failing test first (TDD) OR a measured probe before+after; full suite
  + smoke must stay green; Oniks-vs-SM-2 duel stays bit-identical (the good loop).

## TASKS (ordered; each ends runnable + tested)

### T1 — AWACS EMCON (highest leverage)
The AWACS manages `radar.emitting` from the sensor picture: go SILENT when a player
missile track is inbound within a threat radius OR the commander believes it is being
ELINT-localized; lean on ship/ground cueing during the silent window; re-emit when the
threat clears or when no other sensor holds the needed track. Hysteresis/dwell so it
isn't a 1 Hz strobe. No truth: trigger off `picture` missile tracks + flee state.
Test contract: with an inbound player-missile track within the threat radius, AWACS
`emitting` goes False within the dwell; with a clear sky it emits; it never strobes
faster than the dwell; determinism holds.

### T2 — Fighter sensor→decision brain (survive + engage)
- Evasion triggers on REAL threat: RWR-equivalent (a player SAM guiding on the fighter,
  or an inbound player SAM track within react range), not on friendly-S300 proximity.
- Fighters consume their own nose-radar returns: when a valid target is in cone+range
  and the threat is acceptable, press the attack autonomously (don't wait for a cue);
  when threatened, break/dive/notch.
- Keep no-cheat: the fighter senses via FighterRadar.detects (already sensor-honest).
Test contract: a fighter with a player SAM guiding on it evades (heading break + dive)
regardless of friendly-S300 proximity; a fighter with a sensed in-cone target and no
threat presses toward weapon release; determinism holds.

### T3 — SM-6 real engagement (fix the paper weapon)
- `_try_sm6_launch` uses the SM-6's OWN acquisition range, not the 30 km SPY-1 stealth.
- It iterates the missile/aircraft track stores (high Oniks/Zircon/drone), not drone-only.
- The StealthTargetSam noise scale uses the SM-6's real detection range (not 30 km), so
  kill probability degrades smoothly with range instead of flatlining.
Test contract: a high inbound Oniks/air track beyond 30 km is engaged by SM-6; the kill
fraction degrades monotonically with range (no flat 0.33–0.47 plateau); no truth leak
(engages a TRACK, not the real entity).

### T4 — Track quality/confidence for fusion
Add a per-track confidence (range-fraction + age, derived from sensor data only) to
EnemyPicture tracks; the brain prefers higher-confidence tracks. Detection stays boolean.
Test contract: a fresh in-close track outranks a stale far one in the brain's selection;
confidence is deterministic.

### T5 — CIWS physics (remove the dice roll)
Replace `random()<pk` with a physics-derived burst/dispersion model (rounds vs crossing
geometry), keeping a tiny seeded jitter at most. Preserve the measured Pk envelope as a
two-sided regression so balance is unchanged but the mechanism is physical.
Test contract: CIWS kill emerges from burst geometry; the per-range hit envelope stays
within the prior band (two-sided); determinism holds.

### T6 — Zircon fuel/range honesty + dead-code cleanup
- A fuel-aware launch warning / range hint so a beyond-envelope Zircon shot isn't a
  silent whiff (HUD hint, mirrors the existing Oniks/40N6 hints).
- Remove the no-op line in `process_missile_track`; prune `picture._back_plots`;
  delete or wire the dead KnownStructure store.

## VERIFICATION (every milestone, orchestrator's own eyes)
- Full pytest suite + tools/smoke_combat.py (70/70) green.
- Battle probes (tools/probe_base_attack.py + new behavioral probes) show the new
  behavior with NUMBERS (AWACS silent-window %, SM-6 engagements > 30 km, fighter
  evasions on threat, etc.).
- Then the user-requested review loop: a review agent (audits what changed), a
  code-review agent, and a game-test agent (writes behavioral probes) — fix findings,
  repeat until all pass in one iteration.
