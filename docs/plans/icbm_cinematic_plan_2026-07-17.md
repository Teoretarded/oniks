# ICBM strike for cinematic mode — spec + plan (2026-07-17)

User brief (voice, 2026-07-17): inside F3 cinematic mode add REAL ICBMs
— "the top ICBM for Russia and the top ICBM for America", researched
properly (silos, sensors, guidance), with ground silos modeled in both
cinematic maps; a targeting flow where the player selects a point on
the map and presses L to launch, then WATCHES it fly there; launch
spectacle at "entire rocket ship launching" scale. Priorities in the
user's own ordering: research + missiles + models first, functional
targeting next, the beautiful bespoke targeting MENU last ("least
important"), and the map/LiDAR expansion PARKED until the user says go.

Normative research: docs/research/icbm_reference_2026-07-17.md
(Sarmat + Minuteman III stage tables, silo architecture, launch
phenomenology, GEMS/Lambert short-range energy management, named
reference photos). Numbers below cite that doc; ~ = estimate there.

## Weapons

- **LGM-30G Minuteman III** — solid 3-stage pencil (18.3 x 1.68 m,
  36.0 t). HOT launch: ignites in the tube, fire-in-the-hole annulus
  eruption, THE SMOKE RING, dense white pillar, relentless g.
- **RS-28 Sarmat** — liquid 3-stage monster (35.3 x 3.0 m, 208.1 t).
  COLD launch: mortar eject ~25 m unlit, hang, pallet kick, hypergolic
  orange light-off, near-smokeless climb.

Both from silos surveyed into BOTH scenes (Lauterbrunnen, Yosemite) —
a silo compound is ~60 x 60 m; both valley floors fit one easily.
ONE silo site per scene; the model swaps with the selected launcher.

## The short-range physics problem (LOCKED approach)

A 16 km map cannot absorb a 7 km/s burnout. Real solutions only
([[physics-not-dice]], research doc §3):

- MM III: **Lambert targeting + GEMS** (Generalized Energy Management
  Steering, US 4,387,865 / 10,323,907): all three stages burn to
  DEPLETION on schedule; the autopilot steers thrust at
  θ = arccos(|Vg|/C) off the velocity-to-be-gained, rotating the
  orthogonal component — the corkscrew/weave visibly wastes energy and
  the net velocity integrates to exactly the ballistic requirement.
- Sarmat: S1 + S2 burn fully on the same shaped path (liquids CAN fly
  shaped trajectories); stage-3/PBV cuts off at Vg = 0 (liquid engine
  shutdown — the real mechanism).

Result: full boost with every staging event, apex tens of km over the
valley, RV falls back on the chosen point. Flight ~4-6 min; a coast
TIME WARP control compresses the quiet middle.

## LOCKED CONVENTIONS

- Sim: GL-free, float64, scene coordinates (x east, y up ASL, z north),
  dt-stepped forward Euler like ScriptedLaunch; zero RNG anywhere in
  the trajectory/outcome; fx.rng for visuals only.
- `game/cinematic_icbm.py` — specs + guidance + launch script + fx
  emission (mirror of cinematic_missiles.py). `models/icbm.py` —
  meshes only, built from engine.meshdata primitives like models/s300.
  No new file touches OpenGL outside models/ mesh building + draw
  calls in game/cinematic.py.
- IcbmLaunch duck-types ScriptedLaunch's contract used by
  CinematicState.sim_step: `.t .pos .done .variant.shake_amp
  .variant.label .step(dt, events) .emit(fx, dt)`; new event kinds are
  additive: ("door", pos), ("smoke_ring", pos), ("stage", pos),
  ("cutoff", pos), ("impact", pos) — unknown kinds must be ignored by
  any other consumer.
- Stage/thrust constants COPY the research-doc tables; deviations need
  a research-doc edit in the same commit.
- Tests headless (no GL, no scene assets needed — flat ground fn).

## Phases

### P1 — flight core (GL-free) + tests
`game/cinematic_icbm.py`: IcbmSpec/IcbmStage frozen dataclasses,
MINUTEMAN_III + SARMAT from the research tables; Lambert-lite required
velocity for a lofted arc in uniform gravity (loft solved so apex ≥
MIN_APEX_M); GEMS steering law; mass depletion m(t); staging events;
Sarmat mortar-eject phase (v0 ~22 m/s, ignite at ~25 m AGL) vs MM III
in-tube ignition; RV free fall with simple drag; impact event.

### P2 — models + siting + static render
`models/icbm.py`: build_minuteman_lf() apron/rails/tube ring +
separate door mesh (slides open), build_sarmat_silo() apron + massive
round lid + TPK rim, build_minuteman_iii(), build_sarmat().
Runtime silo survey (flat, obstacle-free, LOS from spawn, 1.5-3 km,
away half-plane — reuse pad-survey rules). Draw in cinematic render;
missile mesh rides IcbmLaunch.pos above door-open state.
Screenshot audit vs the research doc's named photos before P3.

### P3 — launch/staging/reentry fx + sound
MM III: door dust, fire-in-the-hole annulus, smoke-ring vortex
emitter, white pillar (altitude-tapered), vacuum bloom, staging puffs,
reentry glow, impact blast + delayed boom/shake.
Sarmat: lid slide, mortar puff, slow emergence of the actual mesh from
the tube, hang, pallet kick, hypergolic flash, shimmer flame + thin
haze, staging, impact. SMOKE_CAP perf check in the loop.

### P4 — targeting + watch-it-fly
T designates the ground point under the view ray (walk + freecam;
refactor _teleport_to_view's ray-march into a shared helper), HUD
marker + range; LAUNCHER section in the director UI (S-300 PAD /
MINUTEMAN III / SARMAT); L fires the selected launcher (ICBM requires
a designated target — toast otherwise); C follow-cam; '.' cycles time
warp 1x/8x/30x through effective_time_scale during ICBM flight.

### P5 — LAST: the bespoke targeting menu (user-gated)
Full-screen strategic targeting UI, researched for real launch-console
aesthetics; only after the user has playtested P1-P4
([[playtest-before-polish]]).

PARKED: LiDAR map expansion — waits for the user's explicit go.

## Test contracts (verbatim; BLOCKED > weakened, never edit tolerances)

```python
def test_icbm_specs_match_research():
    mm = ICBM_BY_ID["mm3"]; sar = ICBM_BY_ID["sarmat"]
    assert [s.burn_s for s in mm.stages] == [61.0, 65.0, 61.0]
    assert abs(sum(s.gross_kg for s in mm.stages) + mm.bus_kg - 36030) < 1500
    assert mm.diameter_m == 1.68 and mm.length_m == 18.3
    assert sar.launch_mode == "cold" and mm.launch_mode == "hot"
    assert abs(sar.stages[0].prop_kg - 150000) < 5000
    assert sar.length_m == 35.3 and sar.diameter_m == 3.0

def test_gems_full_burn_lands_on_target():
    lch = IcbmLaunch(ICBM_BY_ID["mm3"], silo=(0., 800., 0.),
                     target=(8000., 800., 3000.), ground_h=lambda x, z: 800.)
    evs = _fly(lch, max_s=900.)
    burn_end = lch.burnout_t
    assert 180.0 <= burn_end <= 194.0          # all 3 stages, real schedule
    assert lch.apex_m - 800.0 >= 15_000.0      # it goes UP
    imp = [p for k, p in evs if k == "impact"]
    assert imp and math.hypot(imp[0][0] - 8000., imp[0][2] - 3000.) < 150.0

def test_sarmat_cuts_off_at_vg_zero():
    lch = IcbmLaunch(ICBM_BY_ID["sarmat"], silo=(0., 800., 0.),
                     target=(-6000., 800., 5000.), ground_h=lambda x, z: 800.)
    evs = _fly(lch, max_s=1200.)
    assert any(k == "cutoff" for k, _ in evs)  # liquid shutdown happened
    imp = [p for k, p in evs if k == "impact"]
    assert imp and math.hypot(imp[0][0] + 6000., imp[0][2] - 5000.) < 150.0

def test_trajectory_is_deterministic():
    def run():
        lch = IcbmLaunch(ICBM_BY_ID["mm3"], silo=(0., 0., 0.),
                         target=(5000., 0., -4000.),
                         ground_h=lambda x, z: 0.)
        return _fly(lch, max_s=900.), lch.pos.copy()
    (e1, p1), (e2, p2) = run(), run()
    assert np.array_equal(p1, p2) and len(e1) == len(e2)

def test_cold_vs_hot_ignition_altitude():
    sar = IcbmLaunch(ICBM_BY_ID["sarmat"], silo=(0., 100., 0.),
                     target=(7000., 100., 0.), ground_h=lambda x, z: 100.)
    evs = _fly(sar, until_event="ignite")
    ign = [p for k, p in evs if k == "ignite"][0]
    assert 15.0 <= ign[1] - 100.0 <= 40.0      # research: mortar to ~25 m
    mm = IcbmLaunch(ICBM_BY_ID["mm3"], silo=(0., 100., 0.),
                    target=(7000., 100., 0.), ground_h=lambda x, z: 100.)
    evs = _fly(mm, until_event="ignite")
    ign = [p for k, p in evs if k == "ignite"][0]
    assert ign[1] - 100.0 < 2.0                # hot: lights in the tube

def test_mm3_emits_smoke_ring_once_at_tube_exit():
    lch = IcbmLaunch(ICBM_BY_ID["mm3"], silo=(0., 0., 0.),
                     target=(6000., 0., 0.), ground_h=lambda x, z: 0.)
    evs = _fly(lch, max_s=20.)
    rings = [p for k, p in evs if k == "smoke_ring"]
    assert len(rings) == 1 and 0.0 <= rings[0][1] <= 25.0
```

(_fly = headless stepper at dt=1/120 collecting events; in
tests/test_cinematic_icbm.py.)

## Open questions for the user (defaults chosen, flag on playtest)

1. Impact effect is a big conventional blast for now — say the word if
   you want the full nuclear treatment (flash/fireball/mushroom) and
   at what yield.
2. One silo site per scene, model swaps with launcher selection —
   want BOTH compounds standing simultaneously instead?
3. Coast time-warp defaults: 1x/8x/30x on '.' — happy to make it auto.
