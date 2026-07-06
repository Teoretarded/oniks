# ONIKS Feature-Expansion Review — Fable 5, 2026-07-06

Status: **PLAN FOR APPROVAL — no code touched.** Every hook named in the research
package was re-verified against the working tree at commit b3c2efc. Suite size
today: **1678 tests** (the handoff said ~1300 — it has grown; the compat bar is
"the full current suite stays green").

---

## 0. Corrections to the research package (verified in code, not vibes)

| # | Research claim | What the code actually says |
|---|---|---|
| C1 | "a destroyer is exactly 3 flat hits" | **Wrong.** [damage.py:102-107](sim/damage.py) + [ships.py:141-144](sim/ships.py): ONE hit → BURNING, and burn expiry (45 s) auto-SINKS regardless of hp. hp only controls *instant* sink at 0 and burn-refresh. A single Oniks already kills any destroyer in ≤45 s. Exception: the carrier ([enemy_air.py:463-465](sim/enemy_air.py)) recovers to ALIVE at hp>0 — the ladder is not even uniform today. Calibration target for the new model must be "1 Oniks waterline hit sinks a destroyer on a comparable clock", **not** "Oniks ≈ 1 hp of 3". |
| C2 | "KE = 0.5·warhead_mass·v² … zero new plumbing" | Better plumbing exists: the energy model gives every round a **live total mass** — [missile.py:502](sim/missile.py) `mass = launch_mass − burned fuel`. The Sheffield lever is airframe+residual-fuel KE, not warhead KE. Use `0.5·m.mass·|m.vel|²` for the structural channel; `warhead_mass` drives only the blast/frag channel. Consequence: measured Zircon:Oniks KE ratio will land ~4–7×, not the predicted 3.4× — the test contract carries a wide measured band first, tightened after the probe run. |
| C3 | "`segment_hits_obb` → the local hit location is free" | Half-true. The transform exists but the function returns **bool only**, and `apply_missile_hits` uses the segment **midpoint** as impact. The subsystem path needs a new `segment_obb_entry()` returning `(t_enter, local_point)`; the legacy path keeps calling the untouched bool function. |
| C4 | "detection … SCR = RCS − clutter − noise" | The radar model ([radar.py](sim/radar.py)) is a **functional range-class gate** — no RCS, no dB. Bolting an SCR model on is the wrong altitude. The right seam is the existing EW precedent ([radar.py:91-98](sim/radar.py) → `ew.effective_range`): sea clutter = a deterministic **effective-range factor** `f(sea_state, target_alt/grazing)` applied inside `Radar.detects`, exactly 1.0 at the default sea state. The GIT σ⁰ data still informs the *shape* of the factor curve. |
| C5 | "quarter-res + temporal reprojection … all core GL 3.3" | True of the GL spec, but this engine has **zero FBO code anywhere** (grep `glGenFramebuffers` → no hits). The scene renders straight to the default framebuffer. Half-res + temporal is a real engine-infrastructure phase, not a flag. Correctness pass must be designed to need **no FBO** (direct draw, `gl_FragDepth` + depth test). |
| C6 | "preset authors a truly distinct home/enemy coastline" | `BASE_POS`/`SAM_SITE_POS`/`SITES`/`LANES` are **module constants** evaluated at import off the default field — **113 references across 30 files** (cameras, HUD, tactical map, spawn zones, amphibious, tests, tools). Moving the coastline moves the base and breaks all of it. v1 maps must keep both coast clusters frozen (as presets 1–3 already do) and win recognizability inside that constraint; a `MapDef` refactor that owns the pins is a separate, later phase. |
| C7 | "`scoring.first_fix_t`, `picture_has_actionable_contact`, `show_hint`, `CameraRig`, `replay_battle`, `state_digest`, flight-recorder windows" | All verified real and as described. `state_digest` hashes ship pos/state/ammo + missile pos/vel/alive — note it does **not** hash `hp`, so any new damage state must be *added to the digest under the new flag* or replay divergence in that state would be invisible. |
| C8 | RNG tags | [generation.py](world/generation.py) confirms tag 12 = map terrain; memory says 3–16 taken. **New streams start at 17** (only the cloud weathermap needs one; damage/clutter/sea-state need zero RNG). |

---

## 1. FEATURE 1 — Onboarding + Briefing

**Verdict: BUILD AS PROPOSED** (smallest risk, highest leverage; everything it
reads already exists). One design change: v1 ships the **briefing + objective
strip only**; the scripted tutorial is its own phase behind a menu item, because
it needs playtest feedback on the briefing first (playtest-before-polish rule).

### LOCKED CONVENTIONS (F1)
- All new logic is **GL-free and sim-free**: `game/briefing.py` (content model)
  and `game/tutorial.py` (step machine) import neither OpenGL nor mutate any
  world object. They read `CombatConfig`, the telemetry dict, and
  `world.contacts.tracks` only.
- The tutorial talks to the player through the **existing `show_hint` channel
  only** ([combat.py:414](game/combat.py)) — which means every line is already
  ledgered (`hint` records) for free.
- The tutorial battle is a **plain CombatConfig** (fixed seed, 1 destroyer,
  0 flagship/aaw/ground_attack, n_awacs=0) — no new sim flags, so determinism
  and digest are untouched by construction.
- Objective-strip stages are a pure function of `(telemetry, world)` reads:
  no state is stored in the sim.

### Phases
- **F1-P1 Briefing content model + state.** New `game/briefing.py`:
  `build_briefing(config) -> BriefingDoc` (dataclass: situation / threat table
  derived from force counts / objectives / win-lose conditions / key-hint
  table). New `BriefingState` rendered in the states.py panel language,
  inserted in [combat_setup.py](game/combat_setup.py)'s START callback:
  `CombatSetupState → BriefingState(config) → app.start_combat(config)`.
  ESC skips; ENTER launches.
- **F1-P2 Objective strip.** A HUD strip (top-left, existing hud_widgets
  language) lighting SENSE → FIX → SOLVE → FIRE → HIDE off:
  `first_fix_t is not None` (FIX), `picture_has_actionable_contact` (SENSE),
  selected targetable cluster (SOLVE), `offensive_fired > 0` (FIRE),
  radar-off + no ESM fix accrual (HIDE). Toggleable; default ON in the first
  three battles (a ui_prefs counter), OFF after.
- **F1-P3 Scripted first battle.** `game/tutorial.py` step machine (dataclass
  steps: trigger predicate on `(world, telemetry)` → hint text → completion
  predicate), driven once per sim_step from CombatState when
  `config.tutorial=True`; menu gets a TUTORIAL row that builds the fixed
  config.

### Verbatim test contracts (F1)
```python
def test_briefing_deterministic_and_config_driven():
    from game.briefing import build_briefing
    from world.combat_config import CombatConfig
    cfg = CombatConfig(seed=42, n_destroyers=2, n_subs=1, n_transports=2)
    a = build_briefing(cfg)
    b = build_briefing(cfg)
    assert a == b                                   # pure function of config
    text = "\n".join(a.threat_lines)
    assert "2" in text and "DESTROYER" in text.upper()
    assert any("BEACHHEAD" in ln.upper() or "TRANSPORT" in ln.upper()
               for ln in a.lose_lines)              # transports => beachhead lose-path named

def test_objective_stages_light_from_signals():
    from game.briefing import objective_stages
    tel = {"first_fix_t": None, "rounds_fired": 0, "offensive_fired": 0,
           "leakers": 0}
    stages0 = objective_stages(tel, tracks={}, radar_emitting=True)
    assert stages0["FIX"] is False and stages0["FIRE"] is False
    tel2 = dict(tel, first_fix_t=42.0, offensive_fired=1)
    stages1 = objective_stages(tel2, tracks={"c1": object()},
                               radar_emitting=False)
    assert stages1["FIX"] and stages1["FIRE"] and stages1["HIDE"]

def test_tutorial_steps_advance_only_on_completion():
    from game.tutorial import TutorialScript
    ts = TutorialScript.first_battle()
    n0 = ts.index
    ts.update(world=_FakeWorld(tracks={}), telemetry={"first_fix_t": None})
    assert ts.index == n0                           # no event -> no advance
    ts.update(world=_FakeWorld(tracks={"c": 1}),
              telemetry={"first_fix_t": 10.0})
    assert ts.index > n0
```
(`_FakeWorld` is a 5-line stub in the test file; the step machine reads only
duck-typed attributes — that is the testability contract.)

### Verification plan (F1)
- Screenshot gate: briefing screen at 3 configs (default / subs+amphib / big
  air war) — panel language matches states.py (same fonts, ACCENT color).
- Ledger check: run the tutorial config headless 2 min, assert `hint` records
  appear in scripted order.
- Human playtest checkpoint (mandatory per project memory) after F1-P2.

---

## 2. FEATURE 2 — Subsystem damage model

**Verdict: BUILD WITH CHANGES.** The sharpest feature in the package and the
right one to anchor the expansion. Changes from the proposal:
1. **Structural KE uses the round's live total mass** (`m.mass`, energy model)
   not `warhead_mass` (correction C2).
2. **Calibration target is the real legacy ladder** (correction C1): the
   subsystem model must reproduce "one good Oniks hull hit sinks a destroyer
   on a ~1-minute clock", and *add* the differentiation the flat model lacks
   (ARM ≠ Zircon; superstructure ≠ waterline).
3. **Flooding ships in v1, fire+cook-off ships in v1 but simple** (single
   fire scalar per ship, one cook-off check against the VLS box) — they are
   ~40 lines of deterministic integrator and they ARE the sink/catastrophe
   mechanisms; without them the model has no payoff.
4. Digest: new dynamic state (`buoyancy`, `fire_intensity`, subsystem alive
   flags) is hashed **only when `config.damage_model != "legacy"`** — the
   legacy byte-stream is provably untouched, no golden-digest question.

### LOCKED CONVENTIONS (F2)
- New module `sim/damage_model.py` (pure numpy, GL-free, **zero RNG** — grep
  guard in tests). `sim/damage.py` keeps the legacy path **byte-identical**;
  it branches once at the top of the hit block on
  `world_damage_model == "subsystem"`.
- Config: `CombatConfig.damage_model: str = "legacy"` (opt-in). The combat
  setup screen exposes it as a spinner later; sandbox-war flips it on first.
- Hit frame: ship-local normalized coords `u = (rot.T@(impact−center))/half`,
  `u ∈ [−1,1]³`, +Z bow, +Y up, +X starboard (matches `Ship.obb`). The
  waterline sits at `u_y = WATERLINE_U = (2*HULL_DRAFT/(height+HULL_DRAFT)) − 1`
  (derived per ship type from existing dims — never a magic number).
- Subsystem grid: static per-ship-type list of named local-frame boxes in
  `damage_model.SUBSYSTEM_GRID[ship_type]` — v1 types: `destroyer`,
  `flagship`, `carrier`, `aaw` (merchants keep a hull+flooding-only grid).
  Boxes: `propulsion` (aft, low), `sensors` (center, high), `vls` (fore,
  deck), `c2` (superstructure), plus 4 flooding compartments (below
  waterline, fore→aft). Each box maps to state the AI **already reads**:
  `sensors → ship.radar.alive`, `vls → sm2_ammo/sm6_ammo = 0`,
  `propulsion → speed factor`, `c2 → the CEC/flagship datalink flag`.
- Two deterministic damage channels per penetrating hit:
  `struct = 0.5·m.mass·|m.vel|² / KE_PER_STRUCT` (hull/flooding), and
  `blast = warhead_mass · nose-type frag factor` applied to subsystem boxes
  intersecting a fixed-length interior segment continuing the impact
  direction (the "swept interior segment" — pure geometry, no sampling RNG).
- Penetration gate (deterministic): `penetrates = (KE ≥ SKIN_KE_J) and
  (u_y ≤ DECK_U)`; a non-penetrator (ARM/HARM frag class) damages only the
  subsystem boxes its impact point lies in/adjacent to (antenna shredding).
- `WeaponDef` gains `nose_hardness: float = 1.0` and
  `frag_mass_frac: float = 0.0` (0.0 = UNSET → derived, mirroring the energy
  model's UNSET pattern). Defaults keep every existing WeaponDef valid.
- DoT integrators live in `Ship.update` behind a per-instance flag set at
  spawn from the config (so `sim/ships.py` stays legacy-identical when off):
  `buoyancy -= k_flood·(open flooded volume)·dt`, pumps counter it,
  `fire_intensity += burn_growth·dt − suppress·dt`, cook-off when the fire
  box overlaps `vls` and `fire_intensity > COOKOFF_T`.
- Sinking in subsystem mode: `buoyancy ≤ 0` OR cook-off → ST_SINKING (reuses
  the existing list/sink animation states — render untouched).
- Forensics stamps stay WRITE-ONLY: `m.hit_subsystem`, `m.impact_ke`,
  `m.impact_u` — no sim read, digest untouched by them.
- Tuning constants are named module constants with comments and **tuning
  latitude**: if a contract test won't pass at the suggested value, tune the
  constant — never the test's structure.

### Phases
- **F2-P0 Characterization tests.** BEFORE any change, pin the current legacy
  ladder in tests (contract below) so the "legacy is untouched" claim has
  teeth inside the suite, not just across commits.
- **F2-P1 Geometry.** `segment_obb_entry()` (entry t + local point + unit
  coords), subsystem grid data, waterline math. Headless unit tests only.
- **F2-P2 Impact resolution.** The subsystem branch in `apply_missile_hits`:
  penetration gate, struct/blast channels, subsystem knockout writes
  (radar.alive, sm2_ammo, speed factor, c2). No DoT yet — a flooding hit
  registers compartment state but ships don't yet sink from it. Runnable:
  sandbox-war I-key director + F3 forensics show per-hit subsystem stamps.
- **F2-P3 DoT.** Flooding/pumps/fire/cook-off integrators + sink condition +
  digest extension (flag-gated). Runnable: full battle in subsystem mode.
- **F2-P4 Calibration battery + probe.** `tools/probe_damage_matrix.py`:
  every weapon × {waterline, deck, superstructure} × {destroyer, carrier}
  → table of (KE, penetrated, subsystems lost, time-to-sink). Tune
  `KE_PER_STRUCT`, `SKIN_KE_J`, `k_flood`, `COOKOFF_T` against the target
  ladder; then tighten the two-sided test bands to the measured values.
- **F2-P5 Surfacing.** HUD/forensics: hit cards name the subsystem; AAR
  distinguishes MISSION KILL / FIREPOWER KILL / SUNK. Enemy AI needs **zero
  changes** — it already reads sm2_ammo/radar.alive/CEC (that was the point).

### Verbatim test contracts (F2)
```python
def test_legacy_ladder_characterization():
    # Pinned BEFORE the feature; must stay green forever on the default path.
    from sim.ships import Ship, ST_BURNING, ST_SINKING, BURN_TIME
    from sim.damage import apply_missile_hits
    ship = Ship("s", "destroyer", [(0.0, 0.0), (0.0, 10_000.0)], 0.0)
    m = _round_through(ship)          # scripted round whose segment crosses the OBB
    apply_missile_hits([m], [ship], [])
    assert ship.hp == 2 and ship.state == ST_BURNING
    for _ in range(int(BURN_TIME / (1/120.0)) + 1):
        ship.update(1/120.0)
    assert ship.state == ST_SINKING   # one hit sinks after the burn — TODAY'S truth

def test_subsystem_mode_deterministic():
    from world.combat import CombatWorld
    from world.combat_config import CombatConfig
    from game.blackbox import state_digest
    cfg = CombatConfig(seed=777, damage_model="subsystem")
    ws = [CombatWorld(cfg), CombatWorld(cfg)]
    for w in ws:
        for _ in range(2400):
            w.step(1/120.0); w.drain_events()
    assert state_digest(ws[0]) == state_digest(ws[1])

def test_no_rng_in_damage_model():
    import inspect, sim.damage_model as dm
    src = inspect.getsource(dm)
    assert "default_rng" not in src and "np.random" not in src \
        and "import random" not in src

def test_struct_channel_uses_live_mass_and_speed():
    from sim.damage_model import structural_damage
    # Same warhead, double the impact speed -> 4x the structural channel.
    d1 = structural_damage(mass_kg=2400.0, speed_mps=680.0)
    d2 = structural_damage(mass_kg=2400.0, speed_mps=1360.0)
    assert abs(d2 / d1 - 4.0) < 1e-9   # exact: KE is the only speed term

def test_zircon_vs_oniks_ke_ratio_two_sided():
    # Band starts wide (measured in F2-P4, then TIGHTENED to measured +/-15%
    # in the same phase — the loose band never ships past P4).
    ke = _terminal_ke_by_weapon()      # probe helper: flies each round to impact
    ratio = ke["zircon"] / ke["oniks"]
    assert 3.0 <= ratio <= 9.0

def test_arm_mission_kills_never_sinks():
    w = _scripted_world(damage_model="subsystem")
    _fly_kh31p_into_mast(w)            # frag class, superstructure hit
    ship = w.ships[0]
    assert ship.radar.alive is False   # sensor kill
    assert ship.state in (0, 1)        # afloat (ALIVE or BURNING)
    assert ship.buoyancy > 0.9         # no hull breach from a 87 kg frag head

def test_oniks_waterline_hit_floods_to_sink():
    w = _scripted_world(damage_model="subsystem")
    _fly_oniks_into_waterline(w)
    ship = w.ships[0]
    b0 = ship.buoyancy
    t_sink = _step_until_sinking(w, timeout_s=300.0)
    assert ship.buoyancy < b0          # flooding is monotonic (pump < inflow here)
    assert 20.0 <= t_sink <= 180.0     # comparable clock to today's 45 s burn
```
(`_scripted_world` / `_fly_*` helpers place one destroyer and one round on a
deterministic collision course — the pattern the existing e2e tests already
use. If any bound cannot pass honestly after tuning the named constants,
report **BLOCKED**, do not touch the assert.)

### Verification plan (F2)
- **Backward compat:** full suite green with the feature merged (default
  legacy); `tools/wf_m5_digest.py` run before/after — identical digest.
- **Probe:** `probe_damage_matrix.py` table committed to
  `docs/research/damage_model_calibration_2026-07.md` (NORMATIVE) with the
  measured KE ratios and time-to-sink ladder; constants cite it.
- **Playtest:** sandbox-war with director, subsystem mode on — fire every
  weapon at a destroyer, read the forensics hit cards.

---

## 3. FEATURE 3 — Weather, volumetric clouds, sea state

**Verdict: BUILD WITH CHANGES, SPLIT IN TWO.** The tactical half (sea state +
clutter) is small, test-lockable, and pure win — build early. The visual half
(volumetric clouds) is the only feature touching engine infrastructure the
codebase doesn't have yet (C5) — build it correctness-first, perf ladder after,
and it must be **visual-only** (sim never reads it).

### LOCKED CONVENTIONS (F3)
- `CombatConfig.sea_state: int = 3` (Douglas scale). **State 3 is today**:
  `sea_amp_scale(3) == 1.0` exactly and `sea_clutter_range_factor(3, ·) == 1.0`
  exactly — the default battle is byte-identical by construction.
- Ocean: the 4 Gerstner amplitudes stay in the shader; one new uniform
  `u_sea_amp` (default 1.0) scales them. Scale table derived from Douglas
  significant wave heights, normalized to state 3. No FFT (out of scope).
- Clutter: applied **inside `Radar.detects`** as
  `max_range *= sea_clutter_range_factor(sea_state, target_alt)` for
  size classes `missile`/`stealth` when target altitude < CLUTTER_ALT_M;
  ships/fighters at altitude unaffected. Pure lookup+interp table in a new
  `sim/clutter.py` (GL-free, no RNG), curve shape justified from the GIT
  σ⁰ dataset in a NORMATIVE research doc.
- Clouds: new `world/clouds.py` mirroring the sky.py deferred-GL pattern;
  shared GLSL in `engine/shaderlib.py`; 3D noise (128³ Perlin-Worley + 32³
  Worley) precomputed in NumPy at load, seeded `default_rng([seed, 17])`
  (tag 17 — first free tag); weathermap 2D texture from the same stream.
  Cloud animation clock = **sim time** (replays look identical), never wall
  clock.
- Cloud pass v1 = fullscreen slab-limited march drawn LAST into the default
  framebuffer, `gl_FragDepth` from the slab entry point via the **exact
  locked log-depth formula**, depth test ON (hard occlusion by terrain),
  `apply_haze()` on the result. **No FBO in v1.**
- Perf ladder (v2, only if the gate fails): scene→FBO refactor, half-res
  cloud FBO + depth-aware upsample; temporal reprojection last resort.
- Determinism guard: no sim module may import `world/clouds.py` or read
  `sea_amp` — sea_state reaches the sim ONLY through `sim/clutter.py`.

### Phases
- **F3-P1 Sea state visual.** Config field + spinner, `u_sea_amp`, scale
  table. Seeable: state 0 glass vs state 7 heavy swell screenshots.
- **F3-P2 Clutter physics.** `sim/clutter.py` + the `Radar.detects` hook +
  research doc. Test-locked (contracts below).
- **F3-P3 Perf gate harness.** `tools/perf_clouds.py` (perf_harness pattern:
  hidden window, fence-paced, per-section timers) built BEFORE the cloud
  shader — the gate exists on day one. Budget: cloud section ≤ 3.0 ms avg /
  5.0 ms p95 at 1600×900 on this machine; whole frame stays ≤ 16 ms.
- **F3-P4 Clouds correctness.** Noise textures, weathermap, Beer × powder ×
  HG, 6-step sun cone, ~64-step march + early-out, haze, log depth. Judged
  by screenshot gates only; perf may fail here.
- **F3-P5 Clouds perf.** Step-count/res ladder (Low/Med/High graphics
  setting) until the P3 gate passes. FBO work only if the direct pass can't
  reach budget.

### Verbatim test contracts (F3)
```python
def test_sea_state_default_is_identity():
    from world.ocean import sea_amp_scale
    from sim.clutter import sea_clutter_range_factor
    assert sea_amp_scale(3) == 1.0                      # exact — not approx
    for alt in (2.0, 15.0, 50.0, 200.0, 9_000.0):
        assert sea_clutter_range_factor(3, alt) == 1.0  # exact — not approx

def test_clutter_monotonic_and_bounded():
    from sim.clutter import sea_clutter_range_factor as f
    for alt in (5.0, 15.0, 30.0):
        factors = [f(s, alt) for s in range(10)]
        assert all(a >= b for a, b in zip(factors, factors[1:]))  # non-increasing
        assert all(0.25 <= x <= 1.0 for x in factors)   # never blinds, never boosts

def test_high_altitude_immune_to_clutter():
    from sim.clutter import sea_clutter_range_factor as f
    for s in range(10):
        assert f(s, 9_000.0) == 1.0     # a 9 km fighter is not in sea clutter

def test_sea_skimmer_detection_two_sided():
    # SPY-1-class radar vs a 15 m sea-skimmer: state 6 must cut the
    # detection range meaningfully but not blind the ship.
    from sim.radar import Radar
    r3 = _spy1(sea_state=3); r6 = _spy1(sea_state=6)
    d3 = _detect_range(r3, target_alt=15.0)   # bisect the detects() boundary
    d6 = _detect_range(r6, target_alt=15.0)
    assert 0.45 * d3 <= d6 <= 0.85 * d3

def test_sea_state_config_default_unchanged():
    from world.combat_config import CombatConfig
    assert CombatConfig().sea_state == 3
```

### Verification plan (F3)
- Perf gate (above) run before/after every cloud phase; numbers into the
  run log.
- Screenshot gates vs NAMED references: WT Dagor cumulus bank screenshot,
  Nubis paper fig. (stratus slab, cumulonimbus column), plus "clouds occluded
  by fjord wall" and "clouds through haze at 100 km" scenes.
- Clutter probe: `tools/probe_sea_clutter.py` prints detection-range vs
  sea-state table for Oniks skim / TLAM skim / drone — committed to the
  research doc; the two-sided band cites it.

---

## 4. FEATURE 4 — More maps

**Verdict: BUILD WITH CHANGES.** The research's curated list is good, but C6
(113 `BASE_POS` references) rules out per-map coastlines in v1. v1 delivers
**3 recognizable curated maps inside the frozen-coast constraint** — which the
top three picks happen to fit: Kurils (a diagonal island chain), Hormuz (a
mid-ocean pinch), Ofotfjord (a wall-and-gate). "Truly distinct coastlines"
becomes a named later phase (F4-P4, the MapDef refactor) — not dropped, staged.

### LOCKED CONVENTIONS (F4)
- Curated maps are **hand-authored island lists** (like the default `ISLANDS`
  table — cx, cz, radius, peak), NOT `_seeded_islands` draws: recognizability
  and testability come from fixed geometry. The RNG presets 1–3 stay as the
  "RANDOM …" spinner rows.
- Both coast clusters and the continents keep the DEFAULT seed — every
  LOCKED pin (`BASE_POS`, `SAM_SITE_POS`, `SITES`, spawn zones) reads
  identical terrain on every curated map (test-pinned).
- Corridor rule becomes **per-map**: `MapPreset.corridor_half_x` (default
  45 km). Hormuz sets it to 0 and instead carries an explicit
  `navigable_gap` test asserting a water path through the pinch — the
  soft-lock guarantee is preserved by construction, not by the x=0 rule.
- Per-map `max_height` allowed up to the fjord ceiling (600 m); the
  flyer-skip bound must use the field's own `max_height` (already plumbed).
- Every curated map ships with a "top-N visual signatures" checklist in the
  plan and a named reference image under `docs/research/img/maps/`.
- LANES: v1 keeps the 4 global lanes but every curated map must pass the
  lanes-stay-wet test; where a lane would cross an island the map author
  moves the island, not the lane (lanes are gameplay-tuned).

### Phases
- **F4-P1 Preset plumbing.** `MAP_PRESET_COUNT` grows; presets get names +
  descriptions surfaced in combat_setup; `make_field` dispatches curated
  tables; per-map corridor parameter.
- **F4-P2 KURILS.** ~7-island NE–SW diagonal chain with 2 straits (12–20 km
  gaps), peaks 300–520 m volcanic cones. Signature: the chain reads as a
  wall the carrier must force.
- **F4-P3 HORMUZ + OFOTFJORD.** Hormuz: two long low headland-islands
  narrowing the mid-ocean to a ~39 km throat + 2 stepping-stone islands on
  the sight line; corridor rule off; navigable-gap test. Ofotfjord: an
  island wall across z≈250 km with one 15 km gate + tall (500–600 m) walls
  flanking a north channel; fjord ceiling.
- **F4-P4 (LATER, separate approval) MapDef refactor.** Move
  `BASE_POS`/`SITES`/`LANES`/spawn anchors behind a `MapDef` object owned by
  the world; then real coastlines (Crimea, Kaliningrad, Guam) become data.
  Effort L, touches 30 files — do not bundle with v1.

### Verbatim test contracts (F4)
```python
def test_curated_maps_deterministic_and_pins_frozen():
    import numpy as np
    from world.generation import make_field, BASE_POS, SAM_SITE_POS, SITES, DEFAULT_FIELD
    for preset in CURATED_PRESETS:                    # exported list of ids
        f1 = make_field(preset, 999); f2 = make_field(preset, 999)
        assert f1.islands == f2.islands               # bit-stable authorship
        for (x, _y, z) in (BASE_POS, SAM_SITE_POS):
            assert f1.height_scalar(x, z) == DEFAULT_FIELD.height_scalar(x, z)
        for s in SITES:
            x, z = s["pos"]
            assert f1.height_scalar(x, z) == DEFAULT_FIELD.height_scalar(x, z)

def test_kurils_chain_geometry():
    f = make_field(PRESET_KURILS, 1337)
    isl = sorted(f.islands, key=lambda i: i[1])       # by z
    xs = [i[0] for i in isl]
    assert all(a < b for a, b in zip(xs, xs[1:]))     # monotonic diagonal
    gaps = _adjacent_gaps(isl)                        # edge-to-edge distances
    assert sum(1 for g in gaps if 12_000 <= g <= 25_000) >= 2   # >=2 straits

def test_hormuz_pinch_navigable():
    f = make_field(PRESET_HORMUZ, 1337)
    throat = _min_water_gap(f, z_band=(200_000, 280_000))
    assert 30_000 <= throat <= 50_000                 # the ~39 km signature
    assert _water_path_exists(f, z0=60_000, z1=440_000, draft_m=0.0)

def test_lanes_stay_wet_on_all_curated_maps():
    from world.generation import LANES
    for preset in CURATED_PRESETS:
        f = make_field(preset, 1337)
        for lane in LANES:
            for x, z in _densify(lane, step_m=500.0):
                assert f.height_scalar(x, z) < 0.0

def test_fjord_ceiling_respected():
    f = make_field(PRESET_OFOTFJORD, 1337)
    assert f.max_height == 600.0
    assert max(pk for (_x, _z, _r, pk) in f.islands) <= 520.0
```

### Verification plan (F4)
- Tactical-map screenshot per map vs the named reference image + the
  signature checklist (orchestrator eyes, per milestone rule).
- One scripted battle per map (headless, 5 min): victory/defeat reachable,
  no AI soft-lock (commander issues ≥1 strike order; player Oniks can reach
  a ship track) — pinned as a slow-marked test.

---

## 5. FEATURE 5 — Replay Theater

**Verdict: BUILD AS PROPOSED**, with one honesty clause on seeking: snapshots
= `copy.deepcopy(world)` (CombatWorld is GL-free pure-numpy state, and RNG
Generators deepcopy exactly), **gated by a bit-identity test**. If that test
cannot pass (some world member proves non-copyable), v1 seeking degrades to
restart+fast-forward (still correct, just slower) and snapshots move to v2 —
BLOCKED is reported, the assert is not weakened. All the research's answers
(math not video; ring-buffer killcam promoted at death; PH_TERMINAL trigger;
ledger never deleted) are confirmed correct against the code and adopted.

### LOCKED CONVENTIONS (F5)
- **Tier A re-simulates; Tier B replays recorded truth.** Tier A must drive
  the *same* fixed-step loop as live play (`world.step(PHYS_DT)` +
  per-tick `drain_events`), applying ledger records by the LOCKED tick
  convention (before stepping n→n+1). Divergence from a `hash` record FAILS
  LOUDLY on screen ("RECONSTRUCTED — CODE HAS MOVED" when header commit ≠
  current, hard error when commits match).
- The theater stepper is a refactor of `replay_battle`'s core into
  `ReplayClock` (game/replay.py, GL-free); `replay_battle` becomes a thin
  wrapper calling it — existing tests untouched.
- Killcam recorder extends `game/flight_recorder.py`: per live round a ring
  buffer of high-rate samples (`KILLCAM_HZ = 24`) covering the trailing
  `KILLCAM_WINDOW_S = 5.0`, plus the first 5 s after launch, plus nearby
  entities (target ship pos/heading, any interceptor within 3 km) at the
  same rate; promoted into the record at the death step the recorder
  already detects. Cruise keeps the 0.5 s samples. Render/AAR-only; sim
  never reads it.
- Files: `<blackbox_dir>/battle_<stamp>_s<seed>/` gains `killcams.jsonl`;
  ledger unchanged and never deleted; killcam clips ring-buffered last-N=20
  with `cause=="hit"` clips exempt; moment-score picks "Play of the Battle"
  (carrier hit > ddg > cargo > near-miss > else).
- Theater UI: a new `ReplayTheaterState` that reuses CombatState's scene
  drawing against the replay world with input disabled, transport bar
  (play/pause, ×0.25–×8, scrub), `CameraRig` + `SpectateSubject` cycling.
  Snapshot cadence 30 s of sim time.

### Phases
- **F5-P1 Stepper + snapshots (headless).** `ReplayClock` + deepcopy
  snapshots + the bit-identity contracts. Runnable via a CLI:
  `python -m tools.theater <ledger> --to 05:30` prints digest match.
- **F5-P2 Killcam recorder (headless).** Ring buffer + promotion + file
  format + moment score. Contract-tested.
- **F5-P3 Theater state (GL).** Scene render around the replay world,
  transport, camera rig; entry from the AAR end screen + forensics.
- **F5-P4 Killcam playback.** Interpolated playback of Tier B clips
  (chase/target cams), "Play of the Battle" card on the AAR.

### Verbatim test contracts (F5)
```python
def test_snapshot_resume_bit_identical():
    import copy
    from world.combat import CombatWorld
    from world.combat_config import CombatConfig
    from game.blackbox import state_digest
    w = CombatWorld(CombatConfig(seed=4242))
    for _ in range(1200):
        w.step(1/120.0); w.drain_events()
    snap = copy.deepcopy(w)
    for _ in range(1200):
        w.step(1/120.0); w.drain_events()
        snap.step(1/120.0); snap.drain_events()
    assert state_digest(w) == state_digest(snap)   # BLOCKED if unfixable, never loosened

def test_replay_clock_matches_replay_battle():
    from game.blackbox import replay_battle, state_digest
    from game.replay import ReplayClock
    header, records = _recorded_default_battle(n_ticks=3600)   # existing test helper pattern
    w_ref = replay_battle(header["config"], _cmds(records), 3600)
    clock = ReplayClock(header["config"], _cmds(records))
    clock.seek_tick(3600)
    assert state_digest(clock.world) == state_digest(w_ref)

def test_replay_clock_scrub_forward_consistent():
    clock = _clock_for_default_battle(n_ticks=3600)
    clock.seek_tick(1800); d_mid = state_digest(clock.world)
    clock.seek_tick(3600)
    clock.seek_tick(1800)                      # backward seek via snapshot/rebuild
    assert state_digest(clock.world) == d_mid

def test_killcam_window_rates():
    rec = _record_battle_with_one_hit()        # scripted Oniks kill
    clip = rec.killcams[0]
    t_death = clip["death_t"]
    last5 = [s for s in clip["samples"] if s[0] >= t_death - 5.0]
    assert len(last5) >= 5.0 * 20              # >=20 Hz in the terminal window
    mid = [s for s in clip["samples"]
           if clip["launch_t"] + 5.0 < s[0] < t_death - 5.0]
    if len(mid) >= 2:
        dts = [b[0] - a[0] for a, b in zip(mid, mid[1:])]
        assert all(dt >= 0.45 for dt in dts)   # cruise stays sparse (~0.5 s)

def test_moment_score_prefers_carrier_hit():
    from game.replay import moment_score
    assert moment_score(cause="hit", target="carrier") > \
           moment_score(cause="hit", target="destroyer") > \
           moment_score(cause="hit", target="cargo") > \
           moment_score(cause="pantsir", target=None)
```

### Verification plan (F5)
- Determinism: F5-P1 contracts + replaying three REAL ledgers from the
  `blackbox/` folder and checking every stored `hash` record.
- Perf: theater render under the 12 SM-6 + 8 Oniks director scene ≥ 60 FPS
  (perf_harness pattern, replay-driven); killcam recorder overhead measured
  in the existing perf harness (budget: < 0.3 ms/frame at 20 live rounds).
- Storage probe: full 20-min battle → print ledger + killcams + snapshots
  bytes (expect KB / ~250 KB / few MB); numbers into the run log.

---

## 6. Build order and the v1 line

Recommended order (each phase ends runnable; milestone gate between):

1. **F1-P1/P2** — briefing + objective strip. Two sessions, zero sim risk,
   and it makes every later playtest sharper. Then the **mandatory human
   playtest** (project rule) with the strip on.
2. **F2 (all phases)** — the damage model is the expansion's core and pure
   headless sim work; the payoff (ARM mission-kills, Zircon catastrophics)
   feeds directly into forensics and the killcam.
3. **F5-P1/P2 → P3/P4** — theater + killcam; showcases F2's new outcomes.
4. **F4-P1..P3** — Kurils, Hormuz, Ofotfjord.
5. **F3-P1/P2** — sea state + clutter (small, test-locked).
6. **F3-P3..P5** — clouds, correctness then perf (highest engine risk, zero
   sim risk — safe to do last, and skippable to v1.1 without hurting v1).

**v1 line:** ships with 1–5 plus F3-P1/P2. Explicitly OUT of v1: the scripted
tutorial (F1-P3, after briefing feedback), clouds (F3-P3+ if the schedule
tightens), MapDef/real coastlines (F4-P4), FFT ocean, snapshot seeking iff
the deepcopy contract proves BLOCKED (degrades to fast-forward).

Standing rules for every phase: commit per task; run
`python -m pytest -q -n auto` before/after; no test weakened — BLOCKED is
reported instead; tuning latitude only on named constants; new RNG streams
start at tag 17; all new sim state seeded, wall-clock-free, digest-covered
under its flag.
