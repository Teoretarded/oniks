# Weather System Design — 2026-07-07

**Status: APPROVED (design). Extends — does not replace — Feature 3 of
[feature_expansion_review_2026-07-06.md](feature_expansion_review_2026-07-06.md).**
Everything F3 locked (sea state, clutter, cloud pass v1, perf ladder, tag 17)
stays locked. This doc adds: weather states with slow dynamic drift, a
real-rate day/night clock, thunderstorm theater, and **full sensor-physics
coupling** (user decision 2026-07-07).

Decisions made in brainstorming:

1. **Full physics coupling** — rain degrades radar, cloud/rain degrade IR,
   night degrades optical. Measured curves + test contracts, never dice.
2. **Slow dynamic drift** — weather interpolates along a seeded schedule
   during a battle; sensors read the live state.
3. **Real-rate day/night clock** — pick a start hour in battle setup; the sun
   advances at true rate on the sim clock.
4. **Option A cloud field** — physics queries the SAME cloud-density function
   the renderer draws. No scalar-coverage probability rolls.

---

## 1. Architecture — one atmosphere, two consumers

```
                 ┌─────────────────────────────┐
                 │  sim/atmosphere.py (GL-free) │
                 │  WeatherSchedule (tag 18)    │
                 │  WeatherState @ sim time     │
                 │  solar model (start_hour)    │
                 │  cloud_density(p, t)  NumPy  │
                 └──────────┬──────────┬────────┘
        physics consumers   │          │   visual consumers
  ┌─────────────────────────┴──┐   ┌───┴──────────────────────────┐
  │ sim/rain_atten.py          │   │ world/clouds.py (F3, GL)     │
  │ sim/clutter.py (F3)        │   │ world/sky.py (day/night)     │
  │ seeker LOS / night optics  │   │ rain particles, lightning    │
  └────────────────────────────┘   └──────────────────────────────┘
```

- `sim/atmosphere.py` is the **single source of truth**. GL-free, no pygame,
  no imports from `world/` GL modules or `engine/`.
- **Determinism guard (extends F3's):** sim modules may import
  `sim/atmosphere.py` and `sim/clutter.py` ONLY. No sim module imports
  `world/clouds.py` or reads any render uniform. `world/clouds.py` MAY import
  `sim/atmosphere.py` (visuals follow physics, never the reverse).
- **Clock:** everything runs on **sim time**. Replays are bit-identical.
- **RNG:** `default_rng([seed, 18])` for the weather schedule + lightning
  strike schedule (tag 17 = cloud noise textures per F3; 18 is next free).
  One stream, drawn in a fixed order at construction — no draw-order coupling
  to gameplay events.

### 1.1 WeatherState

```python
@dataclass(frozen=True)
class WeatherState:
    coverage: float        # 0..1, weathermap threshold bias
    cloud_base_m: float    # slab bottom
    cloud_top_m: float     # slab top
    density_scale: float   # optical density multiplier (0 for 'fair', see 3.1)
    precip_mmh: float      # rain rate, mm/h (0 = dry)
    storm: float           # 0..1, drives lightning rate + darkening
    wind_ms: tuple[float, float]  # cloud drift vector (visual + drift only)
```

`Atmosphere.state_at(t: float) -> WeatherState` — piecewise-linear
interpolation between seeded keyframes (one keyframe per ~5 min of sim time,
values drawn once at construction from the preset's band table).

### 1.2 Presets (battle-setup spinner, like sea state)

| Preset | coverage | precip mm/h | storm | density_scale | drift behavior |
|---|---|---|---|---|---|
| CLEAR | 0 | 0 | 0 | 0 | static |
| FAIR **(default)** | 0.15–0.30 | 0 | 0 | **0** | gentle coverage wander |
| PARTLY CLOUDY | 0.35–0.55 | 0 | 0 | 1 | wander ±0.1 |
| OVERCAST | 0.75–0.95 | 0–2 | 0 | 1 | may thicken |
| THUNDERSTORM | 0.6→0.95 | 2→25 | 0→1 | 1.5 | builds over ~20 min |

Drift is **band-limited**: a preset never leaves its row (a FAIR battle never
becomes a storm — the preset is a promise to the player). Keyframe values are
drawn uniformly inside the row's bands from the tag-18 stream.

### 1.3 Solar model

- `sun_dir(t)` from: per-map `latitude_deg` (default 60.0; F4 curated maps
  set their own — Ofotfjord 68, Kurils 46, Hormuz 26), **equinox sun path**
  (declination fixed at 0 — no date picker, YAGNI), and
  `hour = start_hour + t / 3600`.
- `CombatConfig.start_hour: float = 12.0` plus setup spinner rows
  (DAWN 05:30 / MORNING 09:00 / NOON 12:00 / DUSK 18:30 / NIGHT 23:00 /
  custom).
- Standard formula: `sin(el) = cos(lat)·cos(15°·(hour−12))` at equinox,
  azimuth from the same spherical triangle. Pure functions, unit-testable.

---

## 2. Sensor physics (all GL-free, all with research docs)

### 2.1 Rain vs radar — `sim/rain_atten.py`

- **Model:** ITU-R P.838-3 specific attenuation `γ = k·R^α` dB/km, two-way.
  Small locked coefficient table for the bands the game uses
  (S / C / X / Ku / Ka); every radar def gains `band: str` with the real
  value (SPY-1 → S, seeker radars → X or Ku, per existing per-weapon
  research docs).
- **Rain field:** SPATIAL, not uniform (Part 2 §11 — user decision
  2026-07-07): rain exists only under precipitating cloud cells; the
  attenuation integral samples the actual precip field along the radar→target
  path, exactly like the IR LOS samples cloud density.
- **Hook:** inside `Radar.detects`, same pattern as clutter:
  `max_range = _solve_attenuated_range(max_range, γ)` where the transcendental
  `r = R0 · 10^(−2·γ·r/40)` is solved by **fixed 24-iteration bisection**
  (deterministic, branch-free, ~µs).
- Composes multiplicatively with sea clutter: both factors apply, order
  irrelevant.

### 2.2 Cloud vs IR/optical seekers — Option A shared field

- `Atmosphere.cloud_density(p, t)` is **one NumPy function**: weathermap
  value (same 2D noise the GPU texture is baked from, evaluated analytically
  on CPU) × vertical profile over `[cloud_base, cloud_top]` × `density_scale`.
- Seeker LOS check: sample density at **16 fixed points** along
  seeker→target, trapezoid-integrate → optical depth `τ_los`. Lock denied /
  broken while `τ_los > TAU_BLOCK`; lock range scaled by `exp(−τ_los)` below
  that. The cloud your missile can't see through is the cloud on screen.
- CPU cost: 16 vectorized noise samples per IR/optical seeker per tick —
  negligible.
- **CPU/GPU sync contract:** a test bakes the GPU weathermap array and
  compares it against `cloud_density` sampled on the same grid —
  `np.allclose(..., atol=1e-6)`. One implementation, two consumers, proven.

### 2.3 Rain vs IR

- Extinction: IR lock range × `exp(−β(R)·range)` with `β(R)` a locked
  two-point log-interp curve (light rain ~0.3 dB/km-equivalent at 10 µm,
  heavy 25 mm/h ≫) from published MODTRAN-family measurements — curve cited
  in the research doc, two-sided band tested.

### 2.4 Night vs optical/TV

- `optical_light_factor(sun_el)`: 1.0 for `el ≥ 10°`, smooth (smoothstep)
  fall through civil/nautical twilight, **floor 0.15** at `el ≤ −12°`
  (moonless-night floor — optical seekers aren't bricks, they're badly
  degraded). Applies to TV/optical seekers and Mk-1-eyeball spotting only;
  radar and IR unaffected by darkness (IR mildly *helped* at night is out of
  scope — factor stays 1.0).

### 2.5 Enemy symmetry — zero AI changes

The enemy already reads only the sensor picture / track stores (the no-cheat
pattern). Degraded sensors degrade both sides automatically. **The standing
2-stage enemy-AI review still runs** on the seeker/radar hook diffs.

Lightning has **no sim effect** — pure theater.

---

## 3. Identity guarantees (the ~1300 tests stay green)

### 3.1 The FAIR trick

Default `CombatConfig()` ⇒ `weather="fair"`, `start_hour=12.0`, and:

- `precip_mmh == 0` ⇒ rain factors exactly 1.0 (P.838 at R=0 is 0 dB —
  identity by math, and the code short-circuits `precip == 0` to skip the
  bisection entirely, so it is identity **by construction**, not by float
  luck).
- FAIR sets `density_scale = 0` ⇒ `τ_los == 0` ⇒ IR factor exactly 1.0.
  *Modeling justification (goes in the research doc): fair-weather scattered
  cumuli are optically thin, sparse, ~sub-km thick; a seeker holds lock
  through momentary thin obscuration. Visual clouds render (coverage 0.15–
  0.30) but are declared below the extinction threshold.* PARTLY CLOUDY is
  the first preset where clouds bite.
- `start_hour = 12.0` ⇒ `optical_light_factor == 1.0` exactly at noon
  (clamped region, not a curve point).
- Sea state 3 identity is already F3-locked.

So the default battle is **byte-identical** in sim terms; only the sky
gains clouds visually. Any existing golden *screenshot* baselines that break
get re-baselined once, in the same commit, with a note.

### 3.2 Verbatim test contracts

```python
def test_weather_default_is_identity():
    from world.combat_config import CombatConfig
    from sim.atmosphere import Atmosphere
    cfg = CombatConfig()
    assert cfg.weather == "fair" and cfg.start_hour == 12.0
    atm = Atmosphere(cfg, seed=1234)
    for t in (0.0, 600.0, 3600.0):
        st = atm.state_at(t)
        assert st.precip_mmh == 0.0 and st.storm == 0.0
        assert st.density_scale == 0.0
        assert atm.optical_light_factor(t) == 1.0        # noon, exact
    # LOS through the thickest fair cloud is still identity
    assert atm.ir_los_factor((0,15,0), (40_000,9_000,0), 0.0) == 1.0

def test_rain_attenuation_monotonic_and_band_ordered():
    from sim.rain_atten import rain_range_factor as f
    R0 = 200_000.0
    for band in ("S", "C", "X", "Ku", "Ka"):
        fac = [f(R0, band, r) for r in (0.0, 1.0, 4.0, 12.0, 25.0)]
        assert fac[0] == 1.0                              # dry = exact identity
        assert all(a >= b for a, b in zip(fac, fac[1:]))  # non-increasing
        assert all(0.02 <= x <= 1.0 for x in fac)
    heavy = {b: f(R0, b, 25.0) for b in ("S", "X", "Ka")}
    assert heavy["Ka"] < heavy["X"] < heavy["S"]          # physics ordering

def test_night_optics_curve():
    from sim.atmosphere import optical_light_factor_from_elevation as g
    els = (30.0, 10.0, 5.0, 0.0, -6.0, -12.0, -30.0)
    vals = [g(e) for e in els]
    assert vals[0] == 1.0 and vals[1] == 1.0              # day plateau exact
    assert all(a >= b for a, b in zip(vals, vals[1:]))    # monotonic
    assert vals[-1] == vals[-2] == 0.15                   # moonless floor

def test_cloud_los_two_sided():
    # OVERCAST deck between 800 m and 2 200 m: an IR shot from 9 km down to
    # a sea-skimmer must cross it and lose lock; a shot UNDER the deck
    # (150 m -> 15 m) must be untouched.
    atm = _atmosphere(weather="overcast", seed=99)
    assert atm.ir_los_factor((0, 9_000, 0), (30_000, 15, 0), 0.0) < 0.35
    assert atm.ir_los_factor((0, 150, 0), (30_000, 15, 0), 0.0) == 1.0

def test_weathermap_cpu_gpu_single_source():
    import numpy as np
    from sim.atmosphere import cloud_density_grid
    from world.clouds import bake_weathermap        # numpy-only bake path
    a = bake_weathermap(seed=7, res=256)
    b = cloud_density_grid(seed=7, res=256)
    assert np.allclose(a, b, atol=1e-6)

def test_schedule_deterministic_and_band_limited():
    a1 = _atmosphere(weather="thunderstorm", seed=42)
    a2 = _atmosphere(weather="thunderstorm", seed=42)
    for t in range(0, 3600, 60):
        assert a1.state_at(float(t)) == a2.state_at(float(t))
    fair = _atmosphere(weather="fair", seed=42)
    assert all(fair.state_at(float(t)).precip_mmh == 0.0
               for t in range(0, 3600, 60))          # a promise, not a tendency

def test_solar_real_rate():
    atm = _atmosphere(start_hour=18.5, latitude_deg=60.0, seed=1)
    el0 = atm.sun_elevation(0.0)
    el40 = atm.sun_elevation(2_400.0)               # 40 min of sim time
    assert el40 < el0                                # dusk battle: sun sets
    assert -15.0 < el40 - el0 < -2.0                 # real rate, not time-lapse
```

Plus F3's five contracts, unchanged and un-weakened.

---

## 4. Rendering

### 4.1 Day/night (cheap — no new passes)

- [sky.py](../../world/sky.py) frag: the two hardcoded gradient colors become
  4 keyframed gradients (day / golden / twilight / night) mixed by
  `u_sun_elevation`. Sun disc dims + reddens near the horizon.
- **Stars:** procedural hash star field in the same frag, faded in below
  `el < −2°`. No texture, ~10 shader lines. Moon: cut (YAGNI).
- Renderer computes per-frame from `Atmosphere`: `u_sun_dir`, sun/ambient
  color (small elevation-keyed LUT on CPU), haze colors re-tinted. Every lit
  shader already takes these uniforms — terrain, ocean, units follow for
  free. Storm adds a darkening factor onto the same values.

### 4.2 Weather drift without texture churn

`u_coverage_bias` / `u_storm_mix` uniforms shift the coverage threshold and
type response against the **static** weathermap texture — zero per-frame
uploads. The CPU `cloud_density` applies the same bias arithmetic, keeping
2.2's sync contract intact.

### 4.3 Rain

Camera-following cylinder of stretched-billboard streaks via the existing
[particles.py](../../engine/particles.py), count keyed to `precip_mmh`,
velocity = fall speed + wind. Inside-cloud / above-cloud culls itself
naturally (cylinder is local to the camera under the deck). Budget ≤ 0.5 ms.

### 4.4 Lightning + thunder

- Strike schedule pre-drawn from tag 18 at construction: list of
  `(t_strike, world_pos)` while `storm > 0.6`, mean rate ∝ storm.
- Visual v1: 1–2 frame brightness pulse (one uniform added into sky + cloud
  + ambient), pos-weighted so the flash is directional. Bolt polyline = v2.
- Audio: thunder sample delayed by `dist / 343.0` s, attenuated with
  distance — you hear how far the strike was. Uses the existing sound path.

---

## 5. Performance

**The F3 gate stands and now runs the worst case.** `tools/perf_clouds.py`
scene ladder gains a THUNDERSTORM-at-dusk scene (max coverage, rain at 25
mm/h, lightning pulse active).

| Section | Budget (1600×900, this machine) |
|---|---|
| Cloud pass | ≤ 3.0 ms avg / 5.0 ms p95 (F3, unchanged) |
| Rain particles | ≤ 0.5 ms |
| Sky + lightning uniform work | ~0 (uniform changes only) |
| Whole frame | ≤ 16 ms |

Escape ladder in cheapness order (F3, unchanged): march step count → march
distance → Low/Med/High graphics setting → half-res cloud FBO + depth-aware
upsample → temporal reprojection (last resort). Day/night and drift cost
nothing by construction.

CPU: seeker LOS sampling is vectorized NumPy; the sim-side budget is
"unmeasurable in the profiler" — if a probe shows > 0.2 ms/tick total it
gets batched across seekers.

---

## 6. Build order

| Phase | Contents | Gate |
|---|---|---|
| F3-P1…P5 | Sea state, clutter, perf harness, clouds correctness, clouds perf — **exactly as locked** | F3 gates |
| W-P6 | `sim/atmosphere.py`: WeatherState, schedule (tag 18), solar model, presets, config fields + setup spinners | contracts in §3.2 green |
| W-P7 | Day/night rendering: sky gradients, stars, sun/ambient plumbing | screenshot gates: noon / golden / night vs named refs |
| W-P8 | Drift → shader: bias uniforms, preset visuals | screenshot per preset; CPU/GPU sync test |
| W-P9 | Storm theater: rain particles, lightning pulse, thunder audio | perf gate incl. storm scene |
| W-P10 | Sensor physics: rain_atten, IR LOS, night optics, `band` on radar defs + 2-stage enemy-AI review + probe tools | contracts + probes committed |
| — | **Human playtest gate** (standing rule) before any polish pass | user |

W-P10 last is deliberate (user-approved): physics lands once the clouds it
reads are visible and stable, so the probe tables can be sanity-checked
against what's on screen.

### Probe tools (committed output cited by the two-sided tests)

- `tools/probe_rain_atten.py` — detection range vs rain rate per band per
  radar (SPY-1, Buk, seeker heads).
- `tools/probe_cloud_los.py` — IR lock factor vs geometry per preset.
- Existing `tools/probe_sea_clutter.py` (F3) unchanged.

### Research docs (NORMATIVE, before the code of each phase)

- `docs/research/rain_attenuation.md` — P.838 coefficients, band table,
  which radar gets which band, the IR extinction curve + sources.
- `docs/research/atmosphere_model.md` — preset bands vs METAR/okta
  conventions, solar formula, twilight curve + floor justification, the FAIR
  density_scale=0 argument.

---

## 7. Out of scope (named, not dropped)

- Moon + moonlit-night optics bonus
- Lightning bolt geometry (v2 of W-P9)
- Snow / icing, wind affecting missile flight, cross-preset weather fronts
- FFT ocean (F3 already excluded)
- IR flares / IRCCM (a2a.py reserves them; unrelated to weather)

---

---

# PART 2 — 2026-07-07 amendments (sensor-truth audit + spatial weather)

User direction (verbatim intent): audit every sensor/missile for cheating
BEFORE building weather; radars must scan directionally, not as free 360°
range rings; weather physics must interact with WHERE the clouds actually
are, not a global "partly cloudy" factor; cloud layouts must be seeded and
unique per battle (Minecraft-style); cloud TYPES must exist (supercells,
cumulus, stratus, wavy cirrus), not one thin slab.

## 8. Sensor-truth audit (2026-07-07, code-verified)

| System | How it works today | Verdict |
|---|---|---|
| All radars (`sim/radar.py`) | Range-per-size-class lookup + 4/3-earth horizon + terrain LOS + EW burn-through. **No beam, no scan direction, no rotation, no band** — an omniscient 360° ring ("functional model" by original spec). | HONEST gates, but NO SCAN MODEL — the thing the user wants fixed (§9) |
| Track picture (`sim/contacts.py`) | Refresh periods are arbitrary range bands from base (20/60/120 s surface, 15/30/60 s air) — not derived from any radar's scan. Detect delay 2 s, drop 90 s, classification dwell ladder. | FUNCTIONAL, not physical — refresh should be PAINT-driven (§9) |
| Oniks/Zircon terminal seeker (`sim/missile.py::_acquire_lock`) | Real gimbal cone (32°/30° half-angle) + range gate (50/60 km), nearest-alive-ship pick, re-lock on dead target. **Reads truth `world.ships` inside the cone: no radar horizon, no terrain LOS, no weather.** Oniks at 10 m skim has ~31 km horizon to a mast — a 50 km acquisition is physically impossible; it also locks ships through islands. | **CHEATS — fix (§10.1)** |
| S-300/40N6/SM-2/SM-6 (`sim/sam.py`) | Midcourse flies the stale CONTACT estimate (fog-honest), terminal = range-gated handover to truth + multipath OU noise (physics not dice) + terrain LOS mask w/ frozen-lock coast; SARH checks from the illuminator. **No seeker CONE at handover, no ARH-vs-TVM distinction, no ground-radar sector dependency, no weather.** | SEMI-HONEST — fix (§10.2) |
| AIM-9X (`sim/a2a.py`) | Aspect-dependent lock range (8 km rear / 4 km front), 25° off-boresight launch limit, kinematic lock-break (2× band), energy self-destruct. **In flight it PN-homes on truth with no gimbal FOV re-check and no cloud/LOS interaction.** | MOSTLY HONEST — weather + FOV gaps (§10.3) |
| ELINT drone (`sim/recon.py`) | Passive bearings on radars that are actually `emitting`, seeded gaussian bearing noise, least-squares triangulation with observability + surround gates. | HONEST — no changes |
| Enemy AI | Reads sensor picture / track stores only (no-cheat pattern, standing 2-stage review). | HONEST — inherits all fixes free |

Radar band bonus finding: no radar def carries a frequency band today —
`band` (§2.1) must be added during W-P10 regardless.

## 9. Radar scan model (NEW scope, replaces "functional 360°")

### 9.1 The model

`Radar` gains a `scan: ScanDef` describing HOW it searches:

```python
@dataclass(frozen=True)
class ScanDef:
    kind: str            # "staring" | "rotating" | "sector"
    period_s: float      # rotation period (rotating) / sector revisit (sector)
    beamwidth_deg: float # azimuth beamwidth of the search beam
    sector_deg: float    # sector width (sector kind; 360 otherwise)
    boresight_fn: ...    # () -> center bearing (sector: slewable / body-fixed)
```

- **Detection becomes PAINT-based.** A target inside range/horizon/LOS is
  *detected* only when the beam crosses its bearing. `Radar.next_paint_t(bearing)`
  is derivable in closed form from `(kind, period_s, phase)` — deterministic,
  no per-tick sweeping cost.
- **Track refresh becomes physical:** `ContactBoard` `t_next` = the earliest
  next paint among the radars that can see the target, instead of the
  arbitrary range-band tables. A slow rotator gives stale-jumping tracks; a
  staring multi-face array gives near-continuous ones. UPDATE_PERIODS /
  AIR_UPDATE_PERIODS die (kept only for the legacy flag).
- **A sector radar can simply NOT be looking.** Targets outside the sector
  are undetectable regardless of range — the "wasting time scanning empty
  sky" the user called out becomes a real tactical dimension (engagement
  radars slew their sector to the threat axis; the commander AI already
  reads only the track store, so it inherits honest blindness).

### 9.2 Identity strategy — the damage_model pattern

`CombatConfig.radar_model: str = "functional"` (legacy, byte-identical: every
scan paints continuously, exactly today's gate). The game layer forces
`"scanned"` in SANDBOX_CONFIG / setup build_config / campaign next_config —
same mechanism as `damage_model` legacy/subsystem (shipped 2026-07-06).
Existing tests keep `functional`; new contracts pin `scanned`.

### 9.3 Which radar is what (research doc pins these, real-world grounded)

| Game radar | Real system (already implied by ranges/docs) | Scan |
|---|---|---|
| Player station | S-300 battery: 91N6-class acquisition + 30N6-class engagement | acquisition ROTATING ~12 s / engagement SECTOR ~60°, slewable |
| Player ships (SPY-1) | 4 fixed PESA faces | STARING 360° (today's behavior is genuinely right for it — validates, not changes) |
| Buk 9S36 | sector engagement radar | SECTOR, slewable, carried by TEL |
| Pantsir | rotating acquisition + tracking channel | ROTATING ~2 s acq |
| AWACS rotodome | E-3-class | ROTATING ~10 s |
| Fighter nose radar | AESA | SECTOR ±60° body-fixed to heading |
| Enemy ground EW radars | ROTATING ~10 s | |
| CBR counter-battery | staring sector (it stares at the arc) | SECTOR fixed |

Each also gets `band` (S/C/X/Ku) in the same pass — one research doc covers
both (`docs/research/radar_scan_and_bands.md`, NORMATIVE).

### 9.4 Verbatim test contracts (scan)

```python
def test_functional_default_is_identity():
    from world.combat_config import CombatConfig
    assert CombatConfig().radar_model == "functional"
    # under functional, next_paint_t is ALWAYS now (continuous paint)
    r = _rotating_radar(period_s=10.0, model="functional")
    assert r.next_paint_t(bearing=1.23, now=5.0) == 5.0

def test_rotating_radar_paints_on_the_period():
    r = _rotating_radar(period_s=10.0, model="scanned")
    t0 = r.next_paint_t(bearing=0.0, now=0.0)
    t1 = r.next_paint_t(bearing=0.0, now=t0 + 0.01)
    assert abs((t1 - t0) - 10.0) < 0.05        # one paint per rotation

def test_sector_radar_is_blind_outside_its_sector():
    r = _sector_radar(center_deg=0.0, sector_deg=60.0, model="scanned")
    assert r.detects_scanned(_tgt_at_bearing(0.0), "missile", now=0.0)
    assert not r.detects_scanned(_tgt_at_bearing(120.0), "missile", now=0.0)

def test_track_staleness_follows_scan_not_range_bands():
    # A target seen ONLY by a 10 s rotator refreshes ~every 10 s; the same
    # target also inside a staring face refreshes near-continuously.
    ages_rot = _track_age_samples(radars=[_rot10()])
    ages_star = _track_age_samples(radars=[_rot10(), _staring()])
    assert max(ages_rot) > 8.0 and max(ages_star) < 1.0
```

## 10. Seeker honesty fixes (CHEAT removal)

### 10.1 Oniks/Zircon active-radar seeker

`_acquire_lock` (and a lock-KEEP recheck on the LOS_CHECK_PERIOD_S cadence)
gains the full radar gate set, reusing `sim/radar.py` helpers:

- radar horizon from seeker altitude vs ship superstructure height,
- `terrain_blocks` (no locks through islands),
- sea-clutter range factor (F3 — the seeker looks DOWN at a ship in clutter),
- rain attenuation over the seeker→target path (Ku band — it's an active
  radar; §2.1 applies to it too),
- weather never affects the gimbal cone itself (radomes don't care).

Consequence (accepted, realistic): a skimmer's real acquisition is horizon-
limited to ~25–30 km — waypointed shots must be PLACED well (they already
are: the player fires on contact estimates). `seeker_range` stays as the
electronics limit; physics now caps below it.

```python
def test_oniks_seeker_horizon_limited():
    m = _terminal_oniks(alt=12.0)                    # 12 m skim
    ship = _ship_at(range_m=45_000.0, mast_m=20.0)   # beyond ~32 km horizon
    m._acquire_lock(_world([ship]), speed=680.0)
    assert m.locked_ship is None                     # was: instant lock

def test_oniks_seeker_blocked_by_island():
    m = _terminal_oniks(alt=12.0)
    ship = _ship_behind_ridge(range_m=18_000.0, ridge_m=140.0)
    m._acquire_lock(_world_with_terrain([ship]), speed=680.0)
    assert m.locked_ship is None
```

### 10.2 SAM terminal seeker

- `SamDef` gains `seeker_half_angle_deg` + `guidance: "arh" | "sarh"`.
  Terminal handover requires the target inside the seeker cone about the
  velocity vector (a crossing target the round is not pointed at is NOT
  auto-acquired; PN must earn the geometry). ARH (40N6, SM-6) self-
  illuminates; SARH/TVM (48N6, SM-2, Buk 9M317) keeps the existing
  illuminator dependency — which §9 upgrades: the ILLUMINATING ground radar
  must be alive AND have the target in its sector.
- Weather: terminal acquisition range takes the rain path-integral factor
  (X/Ku); cloud density does NOT break a radar seeker (radar sees through
  cloud — only rain rate matters). This is the honest physics answer to
  "how does the S-300 lose track": terrain mask (exists), illuminator death
  (exists), sector slew-away (new), heavy rain shrinking acquisition (new),
  multipath wander vs skimmers (exists).

### 10.3 AIM-9X

- In-flight gimbal FOV re-check (±90° seeker cone off the body axis;
  exceeded = lock lost, no reacquire — replaces the bare 2×-range band).
- Cloud LOS: the IR lock breaks while `τ_los > TAU_BLOCK` through the shared
  cloud field (§2.2) — flying the target into a cloud IS the counter-play.
  Reacquire allowed when the LOS clears inside lock range (IR seekers
  scan-reacquire; deterministic since the field is deterministic).
- Night: IR unaffected (already the §2.4 rule). Flares stay out of scope.

## 11. Spatial weather — cells, not a global state

`WeatherState` (§1.1) stops being map-global scalars for coverage/precip and
becomes the parameter set of a seeded 2D FIELD:

- **Weathermap channels (already planned for rendering, §4.2) become the
  physics truth too:** R = coverage/density, G = cloud type, B = top-height.
  Baked from `default_rng([seed, 17])` noise — same stream as F3 locked.
- **Storm cells:** the THUNDERSTORM/OVERCAST presets seed N discrete cells
  (position, radius ~8–25 km, intensity, drift velocity) from tag 18. The
  weathermap type/coverage channels are stamped by the cells; `precip_at(x, z, t)`
  reads cell membership. Rain exists ONLY under precipitating cells.
- **Attenuation integral (replaces §2.1 uniform rain):**
  `γ_path = Σ k·R(sample)^α · Δs` over 16 samples of the radar→target path —
  identical machinery to the IR cloud LOS, applied to the precip field. A
  radar looking AWAY from the storm cell is untouched; a shot fired through
  the cell is attenuated by exactly the wet kilometers it crosses.
- **Minecraft answer (why every seed is unique):** the noise basis (Perlin-
  Worley) is an infinite deterministic function of (x, z, seed) — the seed
  re-bases the permutation tables, so every battle's cloud/cell layout is a
  different draw from an unbounded family, yet bit-reproducible in replays.
  Same principle as Minecraft's terrain, same as `world/generation.py`
  already does for islands.

```python
def test_rain_attenuation_is_spatial():
    atm = _atmosphere(weather="thunderstorm", seed=5)
    cell = atm.storm_cells(t=0.0)[0]
    dry_path = _path_avoiding(cell)     # radar->target missing the cell
    wet_path = _path_through(cell)      # same range, through the cell core
    assert atm.rain_gamma_path(*dry_path, t=0.0) == 0.0     # exact
    assert atm.rain_gamma_path(*wet_path, t=0.0) > 0.0

def test_storm_cells_unique_per_seed_deterministic_per_seed():
    a, b = _atmosphere(seed=1), _atmosphere(seed=1)
    c = _atmosphere(seed=2)
    assert a.cell_layout_digest() == b.cell_layout_digest()
    assert a.cell_layout_digest() != c.cell_layout_digest()
```

## 12. Cloud taxonomy (render + physics share it)

The type channel selects a per-type vertical density profile + noise recipe
(one GLSL function + the mirrored NumPy one — §2.2 sync contract covers it):

| Type | Base/top | Character | Recipe |
|---|---|---|---|
| Stratus | 300–1,200 m | flat gray sheets | low-freq coverage, soft top, high horizontal stretch |
| Fair cumulus | 600–2,500 m | scattered puffs | Worley-carved billows, powder-heavy lighting |
| Towering cumulus | 800–6,000 m | building columns | tall profile, domain-warped edges |
| **Cumulonimbus / supercell** | 600–12,000+ m | anvil-topped storm column over each storm CELL | column stamped at cell pos, anvil spread at top, rain shaft under base, lightning source |
| Cirrus / undulatus | 7,000–11,000 m | thin wavy streaks | 2D domain-warped sine-modulated wisps, optically thin (density_scale→physics ≈ 0) |

- The march slab covers 300 m–14 km. Perf mitigation for the taller slab
  (this is the main new GPU cost): per-column min/max height from the
  weathermap B channel = empty-space skipping, plus the existing early-out.
  The perf gate (§5) is unchanged and must still pass — supercell scene
  included.
- Presets map to type mixes: FAIR = fair cumulus (+ cirrus), PARTLY = fair +
  towering, OVERCAST = stratus deck, THUNDERSTORM = supercells + towering +
  stratus scud.

## 13. Revised build order (supersedes §6 table)

| Phase | Contents |
|---|---|
| F3-P1/P2 | Sea state + clutter (locked, unchanged) |
| **R-P0** | Radar scan model: ScanDef, paint-based detection, ContactBoard scan-driven refresh, `radar_model` flag, per-radar assignments + bands, research doc, §9.4 contracts. **First — everything else reads through it.** |
| **R-P1** | Seeker honesty: Oniks/Zircon gates (§10.1), SAM cone + ARH/SARH (§10.2), AIM-9X FOV (§10.3 minus cloud), probes, 2-stage enemy-AI review |
| F3-P3/P4/P5 | Cloud perf harness → cloud pass w/ taxonomy (§12) → perf ladder |
| W-P6 | `sim/atmosphere.py` core + storm cells (§11) + solar model |
| W-P7/P8 | Day/night; drift + preset visuals |
| W-P9 | Storm theater (rain, lightning, thunder) |
| W-P10 | Weather↔sensor coupling: spatial rain attenuation, IR cloud LOS (needs W-P6 field + R-P1 seeker structure), night optics |
| — | Human playtest gate |

Rationale: scan model first because the track-refresh rewrite touches what
every later phase reads; seeker honesty second because weather coupling
plugs into the seeker gates it creates.
