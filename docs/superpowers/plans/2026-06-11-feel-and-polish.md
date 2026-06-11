# Feel & Polish Implementation Plan

> **For agentic workers:** Execute task-by-task with two-stage review (spec, then quality).
> The LOCKED CONVENTIONS of `docs/superpowers/plans/2026-06-10-oniks-game.md` (lines 1-87)
> apply unchanged. Research reports in `docs/research/` are NORMATIVE for this plan —
> read the ones your task names before building.

**Goal:** Make the game *feel* right per the creative director's feedback: cinematic
reference-accurate launch sequences, a reference-rebuilt Oniks model, a player-controlled
orbit camera, mid-flight retargeting, and a redesigned menu/settings UI with working
rebindable keys.

**Research inputs (in `docs/research/`):** `oniks_reference.md` (geometry/signatures),
`oniks_launch_sequence.md` (frame-by-frame launch timeline + cinematic storyboard),
`s300_reference.md` (5P85/48N6 + cold-launch timings), `ui_reference.md` (menu visual
language, wireframes, keybind UX). Reference images in `docs/research/img/`.

**Baseline:** S-300 expansion complete (175 tests green, perf 15.1 ms worst case).
Full suite + perf gate re-run at the end; no regressions tolerated.

**Review mandate (user-set, permanent):** every visual gate must do an explicit
side-by-side critique against the reference images/timelines — "is this good or bad vs
the reference" — positive but critical. Rubber-stamping is a review failure.

---

## Task LC: Launch cinematics (sim + effects + audio feel)

**Normative:** `oniks_launch_sequence.md` (timeline + 10-step storyboard), `s300_reference.md`
(cold-launch section). **Files:** `sim/missile.py`, `sim/sam.py`, `game/sandbox.py`
(effects wiring), `engine/particles.py` (new effect helpers only if needed), `game/audio.py`,
`game/cameras.py` (shake hook), tests, harness scenes.

**Oniks (hybrid hot launch — replaces the current cold-eject fiction):**
- In-tube low-thrust ignition: muzzle fireball ring + pink-grey cloud at t=0; exit ~30 m/s.
- Low-thrust ride-out: continuous slow climb (~3.5 s, to ~120-220 m), cream-white dense column,
  missile visibly heavy (net accel small but positive).
- Pitch-over via nose-cap pulse jets between ~1.5-3.0 s: orange puffs at the NOSE while the tail
  burns; turn rate ramps to ~60-90 deg/s toward the route bearing (tunable constants; ground
  launch reference is 90-120 deg/s — pick what reads heavy-but-agile from the chase cam).
- Cap jettison at end of tip-over (~3.0-3.5 s): cap part shot FORWARD, tumbling ballistically
  (reuse dropped-part pattern from the old booster-drop code).
- Booster high-thrust mode immediately after: plume blooms ~4x, trail turns dark grey,
  ~7 s hard burn to Mach 2 (sustained accel; THE violent beat), then booster slug ram-ejected
  out the nozzle (small dark tumbling part, brief), ramjet takes over with a near-transparent
  plume (trail emission drops to a faint haze; the thick trail STOPS at burnout).
- Phase enum may gain PH_RIDEOUT/PH_PITCHOVER internally; keep `phase_label` strings for HUD:
  IGNITION / RIDE-OUT / PITCH-OVER / BOOST / CRUISE...
- Sim tests (TDD): exit speed 25-40 m/s; altitude at cap-jettison 100-260 m; heading within
  15 deg of route bearing by end of pitch-over; Mach 2 reached 6-9 s after high-thrust start;
  all existing flight/intercept tests stay green (timings of later phases unchanged enough —
  if a slow test's t budget shifts, adjust ONLY the launch-window seconds, never tolerances).

**S-300 (true cold launch — replaces immediate ignition):**
- Tube cover blown off (small cap debris) at t=0; catapult exit ~20 m/s; fins snap open
  (model hook if Task OM2's fin parts exist by then — else effects only).
- Ballistic decel to near-zero vertical speed at 20-30 m; HANG: ignition at 1.0-1.5 s after
  exit (tunable ~1.2 s) — this pause is sacred, do not shorten it.
- Ignition: fireball 3-4 body diameters, smoke donut, camera shake pulse; gas-vane tip-over
  kinks the column 30 deg+ within the first ~100 m; then the existing 12 s boost (keep S2's
  loft/guidance untouched beyond the new eject/ignition timeline).
- Sim tests: apex 18-32 m at near-zero vertical speed before ignition; ignition delay 1.0-1.5 s;
  all existing SAM e2e intercept tests green (they tolerate the ~1 s shift or get their time
  budgets +2 s, never their miss-distance tolerances).

**Audio:** Oniks: muffled in-tube thump → rising roar → cap 'crack' → full-thrust slam.
S-300: eject thump → 1.2 s of near-silence (wind) → detonation-grade ignition boom (boom_near
family) + sustained roar. Synthesized like the existing sounds; distance attenuation unchanged.
**Camera shake:** small camera-eye perturbation hook in CameraRig (amplitude/decay constants),
triggered by ignition events within 2 km of the camera; test the decay math.

**Visual gate:** harness time-series scenes — oniks_launch_t1/t2/t3/t4 (ride-out, pitch-over
with nose puffs, cap tumbling, high-thrust bloom) and s300_launch_t1/t2/t3 (hang at apex with
NO flame, ignition fireball, kinked column) — each READ and critiqued against the storyboard
sections of the research docs. Iterate until the sequence reads heavy-then-violent.

Commits: `feat: reference-accurate Oniks hot launch sequence`,
`feat: S-300 cold launch with hang and ignition`, `feat: launch audio and camera shake`.

## Task OM2: Oniks model v2 + S-300 TEL proportions (reference build)

**Normative:** `oniks_reference.md` (Top-10 signatures + modeler's brief, images in
docs/research/img/), `s300_reference.md` (TEL geometry). **Files:** `models/oniks.py`,
`models/s300.py`, `tests/test_models.py`, harness scenes.

- Oniks rebuilt to the signature list: annular intake with the sharp dielectric cone protruding
  ~0.45 m ahead of a knife-edge lip at ~70-75% body diameter, DEEP BLACK annulus, ogive shoulder
  to full diameter over ~1.4 m, clean tube body, 4 clipped-delta wings on the rear half
  (~2.3 m root chord, ~0.5 m exposed span) in X orientation + 4 small in-line tail rudders,
  gull-grey/grey-green body, dark cone, red tail cap accent. Parts that Task LC animates:
  `build_oniks(nose_cap=True/False, wings_folded=True/False)` (folded = wings rotated flat
  against the body for the in-tube/first-instants look; deploy = snap to X within ~0.2 s of
  exit, animated in sandbox draw by building both variants and switching, or by a fold-angle
  param if cheap); separate `build_oniks_nose_cap()` (the jettisoned part — also the pulse-jet
  carrier visual); NO external booster model anymore — `build_oniks_booster` retired from the
  flight visuals (slug ejection in LC uses a small dark cylinder).
- S-300 TEL proportion fix per reference: tube block moved to the REAR overhang, tube tops
  ~9-9.5 m when erect (visibly towering over the 3.8 m cab), F3S-style box cabin behind the
  cab, tube clamp rings (3-4 thin torus-ish rings via short fat cylinders), dome bottom caps.
- Dimension tests updated to the reference numbers (length 8.9 m incl. cap; wing span deployed
  1.7 m; TEL erect height 9-10 m). Visual gate: render model close-ups from 3 angles plus a
  SIDE-BY-SIDE critique paragraph against named reference images (cite which image each
  judgment uses). Iterate until the Top-10 signatures all read.

Commits: `feat: reference-built Oniks model with cap and folding wings`,
`fix: 5P85 TEL proportions per reference`.

## Task CAM: Free orbit camera + camera QOL

**Files:** `game/cameras.py`, `game/controls.py`, `tests/test_cameras.py`.

- Orbit mode 2.0: player-controlled — RMB-drag (or LMB-drag while in orbit mode) rotates
  azimuth/elevation around the tracked subject (elevation clamped -5..85 deg), mouse wheel
  zooms 8-600 m (exponential steps, smoothed with a critically-damped spring like the chase
  cam), gentle auto-drift (0.05 rad/s) ONLY after 5 s of no input. Works on: active missile,
  either TEL, any selected ship/aircraft (subject = current camera target).
- Subject cycling: `[`/`]` (or per keybind table once Task UI lands) cycles orbit/chase subject
  through: newest missile -> each in-flight missile -> active TEL -> selected contact's entity.
- Chase cam: wheel adjusts follow distance 25-120 m (same spring).
- QOL: transitions stay smooth when retargeting subjects; ground clamp everywhere; FOV
  unchanged. TDD: drag deltas map to az/el correctly with clamps; zoom spring converges, no
  overshoot oscillation; subject cycle order; idle-drift only after timeout. Scripted
  interactive run: drag around a TEL, zoom in/out, cycle to a missile mid-flight.

Commit: `feat: player-controlled orbit camera with zoom and subject cycling`.

## Task RTG: Mid-flight retargeting + Oniks profile accuracy

**Normative:** `oniks_reference.md` flight-profile section. **Files:** `sim/missile.py`,
`sim/sam.py`, `world/world.py`, `game/tactical_map.py`, `game/hud.py`, tests.

- Missile selection on map: LMB on an own-missile diamond selects it (14 px pick, own missiles
  take priority over contacts when overlapping); selected missile gets a highlight ring +
  its telemetry in the HUD flight block.
- Retarget: with a missile selected, LMB a new contact/point (surface for Oniks, air for SAM)
  -> `missile.retarget(new_target, new_waypoints=())`:
  - Oniks: allowed in CLIMB/CRUISE/DESCENT-before-lock; rebuilds route from CURRENT position,
    recomputes cruise_alt/descent point with the close-range scaling rule given remaining
    distance; in DESCENT it may re-climb if the new leg is long (re-enter CLIMB). Refused once
    the terminal seeker is LOCKED -> map flashes "COMMITTED" + HUD one-liner.
  - SAM: allowed in BOOST/MIDCOURSE (swap target aircraft + contact closure); refused in
    TERMINAL ("COMMITTED").
  - RMB with selection appends waypoints to the remaining route (same cap 8); X clears them.
- Oniks profile accuracy per research: descent timed so the missile is AT skim altitude
  ~50-75 km from target (seeker fix window) instead of the current geometry-only rule —
  set descent start so skim is reached at SKIM_CAPTURE_RANGE = 60 km (tunable 50-75);
  terminal evasive weaving: lateral S-curve jinks in the last 12 km (amplitude ~150-250 m
  tapering to 0 by 1.5 km, period ~4 s, deterministic phase from missile id) — must still hit:
  existing intercept e2e tolerances unchanged.
- TDD: retarget mid-cruise hits the new ship (e2e); retarget refused after lock (state
  unchanged, missile still kills original); SAM retarget midcourse kills the second aircraft;
  weaving missile still hits within existing tolerance and its cross-track excursion is
  150-250 m in the window; skim capture at 50-75 km out.

Commit: `feat: mid-flight retargeting and reference-accurate terminal profile`.

## Task UI: Menu, settings & working keybinds

**Normative:** `ui_reference.md` (palette, wireframes, rebind UX, persistence). **Files:**
`engine/text.py` (atlas SIZES + 56/14 pt), `game/states.py` (menu/pause/settings screens),
`game/controls.py` (binding table refactor), `game/hud.py` (hint bar removal, F1 overlay),
`game/keybinds.py` (new: actions registry, persistence), tests.

- Binding table: every action (launch, map, camera cycle, profiles, pause, frame-step,
  time accel, screenshot, orbit-subject cycle, waypoint keys, TAB platform, ESC, F1) routed
  through a single action->key table; defaults = current bindings.
- Persistence: versioned JSON at %APPDATA%\ONIKS\settings.json (pygame.key.name strings),
  missing keys filled from defaults, corrupt file regenerated. GL-free `game/keybinds.py` is
  fully unit-tested (load/save/defaults/corrupt/conflict-swap logic).
- Settings screen per wireframe: grouped two-column action list, click/ENTER -> "PRESS KEY"
  capture (scancode), ESC cancels, conflict offers ENTER-to-swap, per-row + global reset,
  wheel scroll. Reachable from main menu AND pause menu.
- Menu restyle per the visual-language spec: #060A10 bg, #0B1412 panels with 1 px #23332E
  borders + 8 px amber corner ticks (reuse bracket draw), amber #F2D973 accent, 56 pt title,
  40 px rows, hover fill + 3 px left focus bar + 80 ms press flash, version footer.
- HUD: bottom hint bar REMOVED; bottom-right micro-label "F1 CONTROLS"; F1 toggles an overlay
  generated live from the binding table; camera mode becomes bare corner text. Contextual
  one-liners (COMMITTED, S-300: SELECT AIR TARGET) stay.
- Visual gates: menu_main, menu_settings (idle + capturing + conflict states), menu_pause,
  hud (no hint bar, micro-label) — critique against the ui_reference wireframes/spec.
  Scripted interactive run: rebind launch to L, restart the app process, verify persisted
  binding fires; conflict swap path; reset-to-defaults.

Commits: `feat: keybind table with persistence and settings UI`, `feat: menu restyle`,
`feat: F1 controls overlay replaces hint bar`.

## Task GATE: Integration re-gate & loop prep

**Files:** `tools/perf_harness.py` (no scene change needed unless LC effects add load),
`README.md`, `docs/superpowers/loop-log.md`, harbor nudge in `world/generation.py`.

- Harbor backlog item: nudge HARBOR site seaward / add a shore apron so the waterline model
  sits right; sites tests stay green.
- Full suite green (target: all prior + all new); perf harness <= 16.0 ms (launch effects are
  the risk — if over, particle emission constants tune down before anything else).
- All harness scenes re-rendered; READ all of them; reference-critique the launch sequences
  and Oniks model one final time.
- Scripted full play-test: menu -> settings rebind -> sandbox -> Oniks launch (watch full
  cinematic sequence at 1x from orbit cam with drag/zoom) -> mid-flight retarget -> kill ->
  TAB -> S-300 hang-launch -> aircraft kill -> F1 overlay -> pause -> resume -> quit.
- README controls table regenerated from the binding defaults; loop-log iteration entry.

Commit: `feat: feel & polish complete`.
