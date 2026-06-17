# Zero-Bias Whole-Game Audit — 2026-06-18

Two independent Opus reviewers (R1 correctness/physics/determinism/regression; R2
fog-of-war/no-cheat/integration) swept the whole game with zero shared context. Every
finding was then handed to a hostile verifier told to refute it by default, deduped,
and severity-ranked. Run: workflow `wf_bc7bb17c-464` (8 agents, ~1.03M subagent tokens).

**Result: 6 raw findings → 4 CONFIRMED (1 HIGH, 1 MEDIUM, 2 LOW), 2 REJECTED.**
No CRITICAL. Determinism + the Oniks-vs-SM-2 duel verified bit-identical during the audit.

## Fix status (2026-06-18)
- **#1 HIGH (fighter truth-track)** — FIXED. `sim/enemy_air.py`: continuous steer +
  AIM-9X release now gated on a CURRENT nose-radar hold; on contact loss the jet flies
  the cached last-known fix for `FIGHTER_INTERCEPT_HOLD_S` (8 s anti-strobe dwell) then
  drops the entity track. Regression test `tests/test_fighter_nocheat.py` (3 cases, TDD
  red→green). Duel + determinism + smoke unaffected.
- **#3 LOW (ship friendly-fire)** — FIXED. `sim/damage.py` skips `is_hostile` rounds from
  the ship sweep (forward-compatible: the M4 ASBM is `is_hostile=False` → still hits).
  Test added to `tests/test_damage.py`.
- **#4 LOW (EW blind-class floor)** — FIXED. `sim/ew.py` returns 0.0 for a zero-range
  class under jamming. Test added to `tests/test_ew_field.py`.
- **#2 MEDIUM (terrain_blocks sub-4 km sampling)** — DEFERRED to **M3-terrain** (next
  milestone): it changes the most-tested LOS seam + default-map close-range detection and
  conflicts with the existing `test_terrain_blocks_short_path_never_self_blocks` unit
  test. Its natural home is the HeightField refactor, where the LOS-baseline probe +
  bit-identical gate are built. Tracked there; not dropped.

---

## CONFIRMED — to fix

### 1. HIGH · FOG_LEAK_NO_CHEAT · `sim/enemy_air.py` (~1209-1228, 1328-1346) + `world/combat.py` (~1492-1499)
Fighter drone-hunt gates only the **initial** acquisition on an own-radar hit. Once
`_intercept_target` is set, `Fighter.update` steers on the drone's **truth** pos every
tick and `release_weapons` fires AIM-9X on truth pos/vel with no re-check that the nose
radar still holds it; `_vector_fighter_to_drone` returns early whenever a target is set,
so contact is never re-validated/cleared. Contract says continuous truth steering must be
gated behind a continuous own-sensor event. Verified by two probes (steers on truth after
contact loss; fires AIM-9X with radar OFF).
**Caveat:** the early-return is an intentional anti-strobe choice — the fix must steer to
**last-known + search** on contact loss (with a short hold), NOT hard-clear every tick, or
it reintroduces strobing.
**Fix:** re-gate continuous steer + AIM-9X release on `self.radar.detects(target...)` this
step; else fly last-known and search. TDD: add a regression test proving no truth-steer /
no-fire after radar loses the drone.

### 2. MEDIUM · CORRECTNESS · `sim/radar.py:40-46`
`terrain_blocks`: `n = int(hypot // LOS_STEP_M)` (LOS_STEP_M=2000) then `range(1, n)` →
**zero interior samples for any line < 4 km**, and the 2 km step can skip a narrow ridge.
Gates radar/SAM-terminal/ELINT/EW LOS. Confirmed on the real map: a target 3.5 km north of
the player radar, 152 m *below* a masking crest, reads LOS-CLEAR.
**Fix:** `n = max(2, ceil(dist / LOS_STEP_M))`. Re-run FULL suite + smoke + duel +
determinism (touches the most-tested seam). Verifier: duel is open-water so stays
bit-identical, but verify.

### 3. LOW · CORRECTNESS · `sim/damage.py:64-96`
`apply_missile_hits` only guards the *launching* hull (`m.launch_platform`). An enemy
SM-2/SM-6 (a `SamMissile` in `world.missiles`) crossing a sister hull's OBB at deck height
damages it; a player interceptor could likewise hit an enemy hull. Practically unreachable
(25 km hull separation + altitude geometry → 0 hits in an 80k-step battle), hence LOW.
**Fix:** side/type filter at the ship sweep — skip `SamMissile` interceptors vs ships, or
pass only `Missile` (Oniks/Zircon) rounds to the ship sweep (mirrors the combat
structure-sweep filter at `combat.py:~2190`). Verify duel bit-identical.

### 4. LOW · REGRESSION_RISK · `sim/ew.py:167-172`
`effective_range`: jammed path `max(EW_CLOSE_FLOOR_M, min(radar_max, bt))` → if
`radar_max == 0.0` for a class, returns the 8 km floor, so jamming *grants* coverage a
radar is normally blind to. Latent only (all live radars define all 4 size classes).
**Fix:** `if radar_max <= 0.0: return 0.0` before the floor. Bit-identical in current play.

---

## REJECTED — verified NOT bugs (no action)

- **"Setup spinners n_awacs/n_drones/n_player_radars are dead controls."** FALSE — those are
  `"fixed"` display rows ("1 (FIXED)"), not steppers; the UI was deliberately made honest
  (documented in build log). No misleading control. Mis-cited the config-mirror as spinners.
- **"Legacy EnemyStrikeController aims Tomahawks at the radar's truth coords (fog leak)."**
  FALSE — the modern commander HARM path aims at `believed_pos`, which is set verbatim to
  `radar.pos` with zero CEP too; both treat a fixed megawatt emitter as surveyed-to-truth
  (physically correct, gated by a 90 s emission-time fix accrual — physics-not-dice). Locked
  by `test_phase3_e2e.py`. Symmetric with the rest of the AI; not a leak.

---

## Coverage gaps the reviewers flagged (candidates for a follow-up pass)
- GL/render internals (`game/sandbox.py`, `controls.py`, `states.py`) only fog-grepped, not
  deeply audited (out of headless scope).
- `sim/damage.py` OBB math, `sim/guidance.py`/`physics.py` numerics, `world/generation.py`
  terrain not deeply audited.
- Full ~945-test suite not run end-to-end by the reviewers (locked-regression + targeted
  subsets only). The orchestrator runs the full suite at every gate regardless.
