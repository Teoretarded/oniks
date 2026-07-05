# Energy Physics + Launch Harness + Graphics Settings — Plan (2026-07-05)

**Goal (one sentence):** make every missile fly like it has mass — speed is an
energy budget spent by turning and drag and refilled slowly by thrust — and
make every launch sequence renderable, probe-measurable, and AI-testable,
with a GRAPHICS settings tab and per-weapon launch/exhaust effects sized for
an RTX 3050 laptop.

**User pain, ranked (their words):**
1. "I can right-click anywhere on the map, it will do a 180, it won't lose
   any speed" — turning is free; nothing bleeds energy. THE bug.
2. "It doesn't feel like it has mass / it feels animated / pre-planned" —
   no autopilot lag, no dynamic-pressure limits: commanded accel is achieved
   the same tick, at any speed, at any altitude.
3. "Render the launch sequences of all the missiles… make it a testable
   feature any AI can run."
4. Settings has only CONTROLS — wants a GRAPHICS tab.
5. "Every missile has the same particle effects… S-300 is massive, why is it
   boring" — per-weapon launch VFX, big smoke, ~2000-particle budget.

**Diagnosis (measured against code, sim/missile.py + sim/sam.py + sim/strike.py):**
- Drag is ZERO-LIFT ONLY (`cd_from_mach`); induced drag does not exist, so
  lateral g costs nothing.
- `_sustainer_thrust` is a Mach-hold with drag feedforward: any speed loss is
  refilled the same tick up to max_thrust — with no induced drag the 180°
  turn is energetically invisible.
- Available g is a flat `max_g` clamp — no dynamic-pressure dependence
  (except the crude stall fade below 200 m/s).
- Commanded accel = achieved accel (no autopilot/fin time constant).
- Launch sequences themselves are already footage-derived (Oniks hot-launch
  beats, S-300 cold catapult/hang/tip-over) — the launch complaint is mostly
  the ENERGY model plus VFX, not the phase machines.

## NORMATIVE RESEARCH (docs/research/, being produced by agents)
- `launch_sequences_2026-07-05.md` — per-weapon real launch mechanics/numbers.
- `missile_energy_autopilot_2026-07-05.md` — drag build-up, induced-drag K,
  CLmax, autopilot lag, worked speed-bleed examples.
- `launch_visuals_particles_2026-07-05.md` — frame-timed visual narratives +
  particle recipe (emission rates, lifetimes, colors, blend modes).
Implementers read them; reviewers spot-check implemented constants against
them. Where research and an existing measured band disagree, the
better-evidenced number wins and the change is argued in the commit.

## LOCKED CONVENTIONS
- Axes X=east Y=up Z=north; SI units; sim float64; GPU float32 only at the
  render boundary. Nothing under sim/ imports OpenGL.
- **One shared aero module**: `sim/aero.py` (new, GL-free, scalar-math hot
  paths). All three flight machines (Missile / SamMissile / StrikeMissile)
  call the SAME functions — no per-machine formula copies:
  - `q_scalar(speed, alt)` — dynamic pressure (exp atmosphere, same RHO0/H).
  - `induced_drag_scalar(lift_N, q, ref_area, k_ind)` = k*L²/(q*S), q floored.
  - `accel_limit_scalar(q, ref_area, mass, cl_max)` = q*S*CLmax/m.
  - `lag_step(actual, commanded, dt, tau)` — first-order autopilot lag.
- The energy model constants live in `sim/aero.py` as named module constants
  with research citations; per-weapon overrides are OPTIONAL def fields
  (`k_induced`, `cl_max`, `autopilot_tau`, `thrust_tau`) defaulting to 0.0 =
  class constants (the SamDef/WeaponDef "0.0 = UNSET" pattern already used).
- **The lift the airframe generates = the applied guidance accel vector
  (gravity compensation included) × mass.** That lift feeds induced drag.
  TVC phases (S-300 boost tilt, Oniks pitch-over) are thrust-vector turns:
  no induced-drag charge, but axial thrust pays `cos(deflection)`.
- **DIGEST POLICY:** this build DELIBERATELY changes flight physics. The old
  default-battle digest (`7d5716…06add`) is superseded — the new digest is
  measured once at the end and recorded in the run log. Every pinned
  two-sided band that breaks is RE-MEASURED with its existing probe tool and
  re-pinned at the measured value with reasoning in the commit message.
  NEVER widen a tolerance without a fresh measured number. Determinism
  contracts (same seed → same bytes, tapped==untapped) must still hold.
- Hot-path budget: the energy model adds scalar math only (a handful of
  mul/adds per missile per 120 Hz substep) — no numpy allocation, no new
  atmosphere evaluations (reuse the step's existing rho/q where possible).
- UI style law: Wardroom Dusk — flat plates, existing tokens, NO glow.
- Test command: `pytest -q -n auto`. Commit after every task.

## PHASES

### Phase 1 — sim/aero.py + energy model in all three machines
Files: sim/aero.py (new), sim/missile.py, sim/sam.py, sim/strike.py,
sim/arsenal.py (optional fields), tests/test_aero.py (new),
tools/probe_energy_bleed.py (new).
1. `sim/aero.py` with the four functions + constants (K_INDUCED_BODY ~1.0
   wingless/body-lift, K_INDUCED_WINGED ~0.35, CL_MAX ~3.5, AUTOPILOT_TAU
   0.3 s, THRUST_TAU_RAMJET 1.5 s / TURBOFAN 3.0 s / SOLID 0.2 s — all to be
   confirmed/cited from the research doc before commit).
2. Missile/StrikeMissile/SamMissile guided phases: clamp guidance accel to
   min(max_g·g, accel_limit); first-order-lag the achieved accel; charge
   induced drag from achieved lift; first-order-lag sustainer thrust.
3. Probe `tools/probe_energy_bleed.py`: cruise Oniks lo-lo, command a 180°
   retarget, log speed/time; print min speed, % bleed, recovery time. Also
   an S-300 max-g terminal-turn bleed case, and a 14 km-altitude turn case
   (must bleed MORE than sea level — thin air).
4. Re-measure and re-pin every broken band with its probe (zircon traj,
   kh31p flyoff, asbm flyoff, sm2 statistics, swarm splash, intercept e2e…).

Test contract (verbatim, tests/test_aero.py — tune gains, never the test):
```python
def test_180_retarget_bleeds_speed_and_recovers():
    """The user's exact complaint: a 180-degree retarget must cost speed.
    Two-sided: it BLEEDS (>=12% of cruise speed lost) and RECOVERS
    (>=90% of cruise speed back within 90 s of the turn command)."""

def test_turn_at_altitude_bleeds_more_than_sea_level():
    """Same commanded turn at 14 km loses MORE speed than at 60 m
    (induced drag scales 1/q — thin air is expensive to turn in)."""

def test_available_g_shrinks_with_dynamic_pressure():
    """accel_limit at 200 m/s sea level < accel_limit at 700 m/s sea
    level; an Oniks at 14 km cannot pull its flat 11 g rating."""

def test_autopilot_lag_no_single_tick_accel_step():
    """Commanded 6 g step: achieved lateral accel reaches 63% in ~tau
    and >95% only after 3*tau — never full authority in one tick."""

def test_straight_cruise_unchanged_regime():
    """A straight, unaccelerated cruise leg still holds cruise Mach
    within 2% — the energy model must not tax straight flight."""
```

### Phase 2 — launch kinematics probe + render harness (AI-runnable)
Files: tools/probe_launch_kinematics.py (new), tools/render_launch_sequences.py
(new), tests/test_launch_kinematics.py (new).
1. GL-FREE probe: for EVERY weapon id (WEAPONS + SAMS + STRIKES), construct
   its round via the real spawn recipe, integrate at PHYS_DT with a stub
   world, and write per-tick logs (t, alt, speed, mach, pitch_deg,
   turn_rate_dps, accel_g, phase) to `renders/launch/<id>_log.csv` + a
   summary JSON (phase transition times, apex of cold-launch hang, speed at
   burnout, max turn rate, max accel).
2. Oracles in tests/test_launch_kinematics.py, per weapon, two-sided, from
   the research doc + measured values (phase order; S-300 eject apex 18–32 m
   and ignition at 1.5 s; tip-over peak rate <= 45 deg/s; Oniks Mach 2.0
   burnout; no |Δaccel| discontinuity above TURN_ACCEL·dt; every launch
   monotonic climb until pitch-over…).
3. GL render harness: chase-cam frame strips (t = 0/0.5/1/1.5/2/3/5/8 s) per
   key weapon composited to `renders/launch/<id>_strip.png` via the
   screenshot-harness pattern (App hidden, read_pixels).
Any AI: `python -m tools.probe_launch_kinematics` (logs+JSON, no GL) then
`pytest tests/test_launch_kinematics.py`; a GPU box also runs the renderer.

### Phase 3 — GRAPHICS settings tab
Files: game/states.py (SettingsState tabs), game/ui_prefs.py (schema),
game/sandbox.py / main.py (plumb density prefs into Effects), tests.
Rows (persisted in UiPrefs): PARTICLE DENSITY LOW/MED/HIGH/ULTRA (0.5/1.0/
1.5/2.0 emission multiplier), EXHAUST TRAILS ON/OFF, LAUNCH SMOKE
MINIMAL/FULL, LAUNCH CINEMA ON/OFF (existing pref surfaced), MAP LAYOUT
BOARD/CLASSIC (existing pref surfaced). Tab rail KEYBINDS | GRAPHICS on the
settings header (draw_tabs fixed-grid mode), LEFT/RIGHT cycles values, mouse
clickable, R resets row. Keybinds behavior byte-identical on its tab.

### Phase 4 — per-weapon launch/exhaust VFX
Files: engine/particles.py (density scale + new helpers), game/sandbox.py
(per-launch-type dispatch). Per research Part A: S-300 cold-launch mortar
puff at tube exit + bigger ground donut at ignition; VLS hot flame-jet +
white column; Bastion TEL dust cloud; Pantsir/Buk thin fast inclined trails;
turbofan cruise = near-smokeless. All emission counts × density pref;
budget target ~2000 live particles in a 4-launch salvo at MED (perf harness
gate on the 3050 target: no regression vs baseline frame time).

### Phase 5 — satisfaction loop
Full suite `-n auto` + perf harness + open the launch strips and CRITIQUE
against the research visual signatures; loop until tests+perf+visuals pass
in the SAME iteration. Record new digest, update run log + memory.

## Out of scope (this build)
- New 3D meshes for TELs/missiles (separate modeling pass, already backlog).
- Fin/control-surface ANIMATION on the missile models (needs mesh rework).
- Terrain/graphics overhaul (spec 09 backlog).
- Resolution/MSAA options in the graphics tab (window is fixed-pipeline
  today; only honest, wired options ship).
- Weather/wind affecting flight (future).
