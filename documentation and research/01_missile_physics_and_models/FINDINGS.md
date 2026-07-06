# 01 — Missile physics & models audit (2026-07-06 overnight)

User report: "the Oniks does a swervy thing on final approach and GAINS
speed — does this game even have physics?"  Findings, measured not vibed.

## 1. Does the game have real missile physics?  YES — with one fake part (now fixed)

Every guided phase integrates, per 1/120 s substep (sim/missile.py:921-978):
- **Thrust**: Mach-hold PI controller burning real fuel (ramjet ISP), with
  spool lag.  **Drag**: q·S·Cd(Mach) parasite + K·L²/(qS) induced — turning
  costs energy.  **Lift limit**: a_avail = q·S·CLmax/m — a PHYSICAL g-limit
  that shrinks at low speed/high altitude (not a software clamp).
  **Fin/autopilot lag**: commanded accel takes ~tau to be achieved.
  **Gravity**, semi-implicit Euler, swept surface impact.
- The models do NOT articulate individual fins (no 6-DOF fin deflection);
  the fin AUTHORITY is modeled through CLmax/tau.  The body visibly leads
  turns via body_dir with an AoA clamp.  This is the standard
  point-mass-plus-autopilot fidelity used by professional missile sims.

**THE FAKE PART (the user's bug, confirmed):** the terminal evasive weave
was a kinematic position/velocity OVERLAY — `probe_missile_physics`
measured a level lo-lo terminal going 680 -> **749 m/s (+69 phantom)** at
the jink peaks with only 1.1 g on the autopilot.  FIXED: the weave is now
an acceleration command through the q-limit/lag/induced-drag chain
(commit 69b14ab).  After: max 681 m/s, honest bleed to 657 mid-jink,
13.7 g achieved of 14.3 available, 201 m excursion (contract 150-250 m),
clean 36 m finish.  Regression: tests/test_retarget.py::
test_terminal_weave_is_flown_not_free (two-sided: no phantom gain AND
real bleed AND per-sample q-limit honesty).

## 2. Permanent stress-test tooling (built this session)

- `tools/probe_missile_physics.py <weapon> <profile> <range_km>` — full
  per-0.1 s dynamics table (speed/Mach/fuel/g-available/g-achieved/
  parasite+induced drag/thrust/cross-track), phase transitions, RED-FLAG
  scan (phantom energy, g-limit violation, teleport), CSV into this folder.
- `tools/render_missile_views.py` — every missile mesh from side/top/
  BOTTOM/quarter (the in-game camera never looks straight up/down, so
  ventral model errors were historically invisible).  Output: renders/.

## 3. Model audit (renders/ vs references/)

- Previous sessions DID document model research: docs/research/
  oniks_reference.md, s300_reference.md,
  dedicated_missile_models_reference.md — the Oniks (annular intake,
  cropped-delta wings, dimensions) is reference-built and test-pinned
  (tests/test_models.py).
- CONFIRMED user complaint: **48N6 and 40N6 render as near-twins** (same
  proportions, same tail cruciform; the 40N6 is only 0.5 m longer with a
  nose band).  Model correction applied this session — see §4.
- Aliased stand-ins remain (kalibr->tomahawk, buk->s300/57e6, asbm->40n6,
  swarm->aim9x): honest scale stand-ins awaiting dedicated meshes.

## 4. Model corrections applied (see git log this session)

- **40N6 rebuilt as a TWO-STAGE round** (models/missiles.py build_40n6):
  7.8 m (referenced figure), fat dark 0.65 m booster stage with large
  tail controls, interstage joint ring, slimmer 48N6-family sustainer
  with its control band pushed aft, blunter dual-mode-seeker radome.
  Length + silhouette contracts updated to the referenced reality
  (tests/test_models.py: 8.00->7.80 pin, distinctness now asserts the
  fat booster stage, not a fictional 0.45 m length gap).
- Oniks verified CORRECT (annular intake + wings already reference-built
  and test-pinned) — my own first-glance critique was wrong; the render
  lighting hides the intake at some angles.

## 5. Ranked remaining model backlog (from missile_reference.md top-5)

1. Kalibr dedicated mesh (pop-out plank wings + booster GRID FINS) —
   currently renders the Tomahawk stand-in.
2. Tomahawk tail: modern 3-fin inverted-Y (currently 4-fin cruciform).
3. Zircon: slimmer waverider forebody (currently too Oniks-like).
4. Buk 9M317 dedicated mesh (currently the 48N6 stand-in) — note the
   reference doc: "9M338" is really the Tor round name.
5. SM-6: two-piece look (slim dart on the fatter Mk 72 booster).
