# HANDOFF PROMPT — Forensics/Debrief implementation (paste this to a fresh Claude)

Repo: `C:\Users\teoti\OneDrive\Desktop\New folder\oinks PROTO` (git, branch `feat/combat-expansion` — never touch `main`). Python + pygame + custom OpenGL engine. Read first: `docs/overnight_run_log.md` (recent sessions), `docs/research/classification_spec.md`, `Assets of oinks/ui_prototypes/README.md`.

## What you are building

The in-game FORENSICS / SHOT DEBRIEF screen, implementing the APPROVED mock
`Assets of oinks/ui_prototypes/ledger2_final_debrief.html` (render:
`.../renders/ledger2_final_debrief.png`). Match that sheet: it is the signed
design. Plus the missing data channel (death-cause attribution). Two work
items, in order:

### 1. Death-cause channel (sim-adjacent, do this first)
`game/flight_recorder.py` already records per-round paths (see below) but not
WHY a round died. Add a cause record to each round's close-out:
- Causes the sim already knows: SAM intercept (`sim/sam.py` — the kill lands
  via `kill_fn` / `target.alive = False` around line 453; identify the
  interceptor's weapon kind), CIWS/Pantsir gun kills (`sim/ciws.py`,
  `sim/pantsir.py`), fuel exhaustion (missile's own fuel state), decoy
  seduction (`sim/decoys.py`), terrain/sea impact vs target HIT (damage sweep
  in `sim/damage.py` / world impact paths).
- Attribution flows to the recorder WITHOUT touching sim decisions: preferred
  pattern = the recorder inspects the dead round's own attributes; where the
  killer isn't readable from the round, add a WRITE-ONLY stamp on the round
  object at the kill site (e.g. `m.death_cause = ("sam", "sm6")`) — a stamp no
  sim code ever reads (digest safety, see gates).
- FOG RULE (user-locked): mid-battle the UI names the killer ONLY IF OBSERVED —
  v1 honest rule: the killer interceptor was itself a track in
  `world.contacts.tracks` at kill time → cause carries `observed=True`; else
  display "LOST - UNCONFIRMED". Post-battle AAR may show everything but must
  flag observed vs reconstructed. Record both facts; let the display gate.
- TDD: pure tests for each cause class + the observed flag. Never weaken an
  existing test.

### 2. The FORENSICS screen (game/forensics.py, new)
- ENTRY: a side-rail button on the tactical map screen (M) — NOT inside the
  map canvas — plus a DEBRIEF row on the AAR end screen. Key `J` opens it
  directly in battle (add to `game/keybinds.py` registry so the F1 overlay
  auto-lists it).
- THE SIM MUST NOT PAUSE. Non-negotiable. Follow the F1/O overlay pattern
  (`game/hud.py _controls_overlay` / `_battery_panel`) or the tactical map's
  pattern (`game/tactical_map.py` — the map runs while open). Show a live
  clock chip ("T+mm:ss - SIM RUNNING") + inbound count so the player sees it.
- CONTENT per the mock, all fed from `CombatState.flight_recorder`
  (`game/combat.py`, `self.flight_recorder`, class in
  `game/flight_recorder.py` — API: `.rounds()` → records with kind/seq/
  launch_t/samples/death; `.path_of(rec)` → (N,4) float64 `(t,x,y,z)`):
  - Counter row: FIRED / HIT / INTERCEPTED / OTHER LOSS / OBSERVED /
    UNCONFIRMED (derive from recorder + cause channel; FIRED can cross-check
    `self._telemetry["rounds_fired"]`).
  - Round stub row: one stub per record, click/UP-DN selects, sheet redraws.
  - THE 1:1 PLOT (the whole point — user-locked ACCURACY CONTRACT): altitude
    (y) × cumulative ground distance (from the samples: sum of hypot(dx,dz))
    as a polyline via `text.draw_lines` DIRECTLY from `path_of()` — no
    smoothing, no interpolation, no schematic shapes. Real axes: altitude
    labels left, km ticks bottom, ground line, launcher at origin. Death
    anchor = red mark at the exact recorded death pos. Dashed planned
    remainder to the target if the round died short (target point is on the
    record's launch metadata — extend the recorder to stamp `target_xz` at
    pickup from the round's aim point, read-only).
  - Top-down ground track: same samples, x/z plotted at UNIFORM scale.
  - Event flags: launch/death exist now; phase-transition events (pushover,
    skim, seeker) are a recorder extension — stamp on phase_label changes in
    `FlightRecorder.update` (the round's own attribute, allowed).
  - Sensor-lane strip + BLACK BOX + SENSORS tabs: NOT approved visually yet —
    render the tab strip with those two tabs present but showing
    "AWAITING DESIGN" placeholder text. Do not design them yourself.
- STYLE: Wardroom Dusk tokens live in `game/states.py`. The ledger look is
  light paper on the dark desk — add NEW tokens (PAPER_BG, PAPER_INK,
  PAPER_MUTED, INK_RED/TEAL/AMBER/GREEN/VIOLET from the mock's hex values);
  do not repurpose existing tokens. Engine constraints (hard): monospace
  atlas ASCII 32-126 only (no unicode glyphs — use `-`, `>`, `X`), exactly 4
  font sizes 14/18/28/56 (`engine/text.py`), flat rects + 1px polylines only
  (`draw_text/draw_rect/draw_lines`), no blur/rounded corners. The plot
  polyline is `draw_lines` — a perfect fit.

## Hard gates (run ALL after every commit-sized change)
- `python tools/wf_m5_digest.py` MUST print
  `7d5716325a234607493a8ce6f7f17b72fd4fe44dd66a799fe7f6deb310b06add` — the
  sim digest is byte-locked. Your work is game/render-layer; if the digest
  moves you broke the contract, revert and rethink.
- `python tools/smoke_combat.py` → 0 FAIL (84 PASS currently).
- Targeted pytest for what you touched, then FULL `pytest -q -n auto`
  (~1300 tests, ~10-20 min; ALWAYS `-n auto`). Two known pre-existing reds
  you must NOT fix or mask: `tests/test_pantsir_model.py::test_width_approx_3m`
  (model geometry, separately owned) and `tests/test_phase5b_e2e.py` is an
  order-flake that passes in isolation.
- `python tools/shoot_ui_reference.py` regenerates UI screenshots to
  `C:/Users/teoti/OneDrive/Desktop/Assets of oinks/ui_reference/` — extend it
  to capture the new forensics screen, then LOOK at the PNG yourself and
  compare against `renders/ledger2_final_debrief.png` before claiming done.
  (Headless renders of HTML mocks: Brave at
  `C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe`
  `--headless --disable-gpu --screenshot=<plain-temp-path> --window-size=1920,1080`;
  it cannot write into OneDrive folders — write to `%TEMP%` and copy.)

## Laws (violating any of these is a failed task)
- Fog color LAW: sensor beliefs teal family, own-force truth green, hostile
  dusk-red, brass = selection/weapons only (tokens in `game/states.py`).
- Never display data the sim doesn't produce (no invented PARs, no Pk, no
  enemy-intent labels like "ASSIGNED").
- Never weaken a test assertion/tolerance to make something pass; a DESIGN
  change may re-key a display test honestly (say so in the commit).
- Enemy AI reads only its own sensor picture — you shouldn't touch enemy code
  at all here.
- Keyboard-first UI: every mouse affordance needs a key path; the 80ms press
  flash, 3px focus bar, corner-tick panel idioms stay (restyle ok).
- Commit per feature, conventional messages, and append a session entry to
  `docs/overnight_run_log.md` at the end.

## Working style expected
TDD for every pure helper (see `tests/test_flight_recorder.py` for the house
style); measure before claiming (run a headless battle and print recorder
output — see the end-to-end probe pattern in the log); when a mock element
can't be rendered under engine constraints, implement the closest
constraint-respecting version and note the deviation in the commit message.
Work autonomously; don't stop to ask unless a locked contract (digest / fog
law / no-pause) is genuinely at risk.
