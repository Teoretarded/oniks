# SANDBOX WAR run log — 2026-07-06

Plan: docs/plans/sandbox_war_2026-07-06.md.  Solo build (user directive:
no agents).  Branch feat/combat-expansion.

## Shipped

- **A1** `feat(sandbox): weapons-free gate + SandboxWorld toybox` —
  CombatWorld.enemy_weapons_free (True default, byte-identical; guards at
  defense.step / strikes.step / commander brain / sub fire-intent);
  world/sandbox_world.py SandboxWorld: SANDBOX_CONFIG full toybox
  (3+1+1+1 destroyers + carrier + transport, 2 subs, 4 fighters + AWACS +
  jammer, 2 enemy radars; blue: 2 Oniks TELs, S-300, 2 Pantsir, Buk,
  swarm pod, CBR, drone + EW pod, ASW kit; generous pools), civilian
  traffic + patrols re-added, all-seeing board (visible_fn None), fog
  latches forced open, defeated/victorious never latch.
- **A2** `feat(sandbox): SandboxWarState on the menu SANDBOX button` —
  CombatState subclass; menu SANDBOX boots it; director keybind I
  (graceful hint outside the war sandbox); tools/shoot_sandbox_war.py.
- **B** `feat(director): SandboxWorld order API` — director_units /
  director_order (per-ship TLAM salvo, sub Kalibr with CEP + launch
  datum, 2-ship JASSM package) / director_sead / set_weapons_free; all
  work while passive, spend real magazines.
- **C** `feat(director): map-screen panel (I)` — DirectorModel pure logic
  (tests) + panel/marker draw; ENTER arms, map LMB launches, ESC backs
  out; messages ride show_hint into the black-box ledger.

## Verification

- tests/test_sandbox_world.py (15) + tests/test_director.py (6) green;
  targeted regressions green (enemy_defense, combat_config, submarine,
  kalibr_salvo, commander, phase3/4/5b e2e, scenario_forge).
- Visual gate (renders/sandbox_war_*.png, reviewed by eye):
  - destroyer/carrier meshes render in the sandbox sea; airfield complex
    on the enemy plain with a CAP fighter lifting off (passive rotation
    alive);
  - map: all-seeing picture (enemy fleet + airfield + radars + civil
    lanes, no fog), full weapon rail, DEBRIEF [J] rail;
  - director panel: honest rows (AAW/flagship 0 TLAM by doctrine,
    ground-attack 40), ARMED banner, sub truth markers;
  - director_strike: ordered salvo visible as hostile TOMAHAWK tracks in
    the contact pane + threat pop-up, VLS row spent 8 -> 6.

## Findings fixed during the build

- Parked fighters report ``alive False`` by design (hangar) — the raw
  flag is ``_alive`` (the release-pump read); the parked filter and the
  panel airframe count use it.
- The nearest destroyer can be the TLAM-less AAW escort — tests and the
  strike scene pick an ARMED hull; the panel shows 0/"-" honestly.

## Phase D findings

- **Full suite red #1**: the director ActionDef was appended after the
  SIMULATION forensics entry, splitting the ENGAGEMENT group in two —
  the settings screen + F1 overlay derive group headers from registry
  order (test-locked).  Moved inside the contiguous ENGAGEMENT block.
- **Perf red**: tools/perf_sandbox_war.py (new gate: toybox live loop,
  8x, 16 ms budget) measured TOTAL 50.0 ms/frame.  Profile named the
  mechanism: `_publish_ew_state` -> `ew.effective_range` terrain ray
  march at 120 Hz = 78% of the world step (only visible with a LIVE
  jammer — combat's n_jammers=0 default never ran it).  Fix: 4 Hz
  publish cadence at the step() call site (EW_PUBLISH_PERIOD_S); the
  method stays a pure recompute for direct/test callers.  Re-measured:
  sim 44.3 -> 9.7 ms, TOTAL 15.4 ms, PASS.  p95 spikes ~30 ms remain
  (ELINT triangulation bursts on its own cadence) — absorbed by the
  main loop's accumulator; candidate for a later spread-the-work pass.

## Known nits (logged, not blocking)

1. Map label overprint near the top edge (ENEMY AIRFIELD / ENEMY RADAR /
   HARBOR KILO cluster) — pre-existing label layout, worse now that all
   fog latches are open.  Candidate: label de-confliction pass.
2. The threat pop-up (TOMAHAWK BRG…) can overlap the director panel's
   top-right corner at 1600x900.  Candidate: shift PANEL_Y or dodge the
   threat strip rect.
3. Director unit marker labels overprint in the fleet cluster at wide
   zoom.  Candidate: hide labels beyond a zoom threshold.
4. Contact rows read UNK for young tracks (classification needs dwell) —
   correct sensor behavior, listed here because the first map screenshot
   confused it for a bug; it self-resolves as tracks age.
5. Director orders ride the ledger only via the hint channel — they are
   not CommandRecorder verbs yet, so a bit-exact replay of a directed
   sandbox session will diverge.  Candidate: record director_order /
   set_weapons_free as replay commands.
6. Sim cost: the toybox steps ~3.4x realtime headless on this machine
   (22 hulls + 2 subs + EW).  Perf gate on the RTX 3050 pending in
   Phase D below.

## Phase D status

- [x] world/director tests green (22 new tests)
- [x] full suite `pytest -q -n auto` (first run caught the keybind
      registry split — fixed; final run green)
- [x] visual review (7 scenes, re-shot after the perf fix — EW
      burn-through row alive under the cadence)
- [x] perf gate: tools/perf_sandbox_war.py PASS (15.4 ms avg vs 16 ms
      budget after the EW-cadence fix)
