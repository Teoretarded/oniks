# Missile Flight-Energy Physics & Autopilot Structure

### Normative engineering reference for the flight sim — the math that makes a missile bleed speed in turns and fly like it has mass
Compiled 2026-07-05. All numbers cited inline. This is a **normative** doc: where it says
"USE", that is the recommended sim value. Companion to `oniks_reference.md` (geometry) and
`dedicated_missile_models_reference.md`.

> **Design axiom (repo memory: "Physics not dice"):** every number below feeds a *simulated*
> equation of motion. Hit/miss falls out of whether the missile still has the *energy and the
> available-g* to close the geometry — never a flat probability roll. The whole point of this
> doc is to make "the missile ran out of speed in the terminal turn" a thing that *emerges*.

---

## 0. Symbols, units, conventions

| Symbol | Meaning | Unit |
|---|---|---|
| `V` | airspeed (≈ inertial speed, no wind) | m/s |
| `M` | Mach number = `V / a` | – |
| `a` | speed of sound (≈ 340 at SL, ≈ 295 at 11 km) | m/s |
| `rho` | air density | kg/m³ |
| `q` | dynamic pressure = `0.5 * rho * V²` | Pa |
| `h` | altitude | m |
| `gamma` | flight-path angle (climb +) | rad |
| `m` | current mass | kg |
| `g` | 9.80665 | m/s² |
| `n` | load factor (lateral g's pulled), `L = n·m·g` | – |
| `S` | aerodynamic reference area | m² |
| `d` | body diameter | m |
| `T` | thrust | N |
| `D` | drag | N |
| `L` | lift (normal force) | N |
| `CD0` | zero-lift (parasite) drag coefficient | – |
| `CDi` | induced (lift-dependent) drag coefficient | – |
| `CL` | lift coefficient | – |
| `K` | induced-drag factor, `CDi = K·CL²` | – |
| `Isp` | specific impulse | s |

**Reference-area convention (IMPORTANT — pick one and never mix):** for a slender missile the
universal choice is the **body cross-section**, `S = π·d²/4`, *not* the wing planform used for
aircraft. Fleeman's build-up and virtually all missile aero data are non-dimensionalised on
`S = π·d²/4` ([Fleeman, *Tactical Missile Design*, ch. "Aerodynamic Considerations"](https://docplayer.net/117312640-Tactical-missile-design-tactical-missile-design-professional-development-short-course-on-eugene-l-fleeman.html)).
Aircraft texts non-dimensionalise on wing area ([lissys c05](https://www.lissys.uk/pug/c05.html)) — do **not** copy their absolute CD0 numbers without re-basing the area.

**Reference areas for the three example missiles** (`S = π·d²/4`):

| Missile | `d` (m) | `S = π d²/4` (m²) |
|---|---|---|
| P-800 Oniks | 0.67 | **0.353** |
| 48N6 (S-300) | 0.50 | **0.196** |
| Tomahawk | 0.52 | **0.212** |

---

## 1. Drag model

### 1.1 Atmosphere (density) — simple exponential ISA

For a point-mass engagement sim the multi-layer ICAO ISA is overkill. The **isothermal exponential**
fit is standard and accurate to a few percent through the troposphere:

```
rho(h) = 1.225 * exp(-h / H)          H ≈ 8500 m  (scale height)
```

- `rho0 = 1.225 kg/m³` is the exact ISA sea-level density ([ISA / Wikipedia](https://en.wikipedia.org/wiki/International_Standard_Atmosphere)).
- **Scale height `H`:** the physically-correct isothermal value is `H = R·T/g ≈ 8.4–8.5 km`.
  `8500 m` is the conventional round number and is confirmed as the standard engineering choice
  ([scale-height references](https://en.wikipedia.org/wiki/International_Standard_Atmosphere)). **USE H = 8500 m.**
- Speed of sound: cheap linear-ish fit good to ~11 km: `a(h) ≈ 340.3 - 0.00394*h` (m/s), or just
  table it. Below 11 km temperature falls ~6.5 K/km so `a` drops from 340 (SL) to ~295 (11 km).

At 15 km `rho ≈ 1.225·exp(-15000/8500) = 1.225·0.171 = 0.209 kg/m³` — **~17 % of sea-level
density.** That single factor is why the same missile pulling the same g bleeds far *less* speed
up high (§2) but also has far *less* available-g (§3). Both effects are `q`-driven.

### 1.2 Zero-lift drag CD0(Mach) — the transonic hump

`CD0` for a slender supersonic missile has three regimes, all captured by Fleeman's build-up
`(CD0)Body = (CD0)Wave + (CD0)Base + (CD0)Friction`
([Fleeman drag build-up](https://docplayer.net/117312640-Tactical-missile-design-tactical-missile-design-professional-development-short-course-on-eugene-l-fleeman.html)):

- **Wave drag** (Mach > 1): `(CD0)Wave = (1.59 + 1.83/M²)·{atan[0.5/(lN/d)]}^1.69` — grows sharply
  through Mach 1, then *decays* as `1/M²` supersonically. `lN/d` = nose fineness.
- **Base drag:** coasting `(CD0)Base = 0.25/M` for M>1, `= 0.12 + 0.13·M²` for M<1. Powered flight
  multiplies by `(1 − Ae/Sref)` because the plume fills the base — **base drag roughly halves when
  the motor is lit.** This matters: a coasting missile has materially more drag than a thrusting one.
- **Skin friction:** `(CD0)Friction = 0.053·(l/d)·[M/(q·l)]^0.2` — weak Mach/Reynolds dependence.

The qualitative curve everyone uses (on `S = πd²/4`), for a clean slender round like Oniks:

| Regime | Mach | CD0 (body-area based) | note |
|---|---|---|---|
| Subsonic | 0.6–0.8 | **~0.25–0.35** | friction + base dominate |
| Transonic **spike** | ~1.0–1.2 | **~0.5–0.6+** | wave-drag onset, the "sound-barrier hump" |
| Low supersonic | 2.0–2.5 | **~0.35–0.45** | wave drag decaying as 1/M² |
| High supersonic | 4–6 | **~0.20–0.30** | wave drag low, friction-limited |

> These are **body-cross-section** CD0. On wing/planform area they'd look ~10× smaller — that's the
> aircraft-book convention (lissys quotes `CD0 ≈ 0.020` on *wing* area). Do not conflate the two.
> ([lissys c05](https://www.lissys.uk/pug/c05.html), [Zero-lift drag coefficient / Wikipedia](https://en.wikipedia.org/wiki/Zero-lift_drag_coefficient))

**Recommendation:** ship a small **CD0(Mach) lookup table per missile** and linearly interpolate.
The transonic hump is the single most important feature — a subsonic weapon (Tomahawk) never crosses
it; a supersonic weapon pays it once on the way up and must never fall back through it in the
terminal phase or it will mush.

### 1.3 Induced (lift-dependent) drag — the turn tax

Standard quadratic polar ([drag polar / lissys](https://www.lissys.uk/pug/c05.html), [NASA induced drag](https://www1.grc.nasa.gov/beginners-guide-to-aeronautics/induced-drag-coefficient/)):

```
CD = CD0(M) + K·CL²           (the drag polar)
```

- `CL` is set by how hard you're pulling: `L = n·m·g = CL·q·S`  ⇒  `CL = n·m·g / (q·S)`.
- `K = 1/(π·AR·e)` for a winged body. Cruciform tactical missiles have **low aspect ratio**
  (stubby fins, AR ~1–2) and modest span efficiency `e ~ 0.6–0.8`, so `K` is **large** compared to
  an airliner (which runs `K ≈ 0.04–0.05`). Aircraft drag polars span `K ≈ 0.04–0.09`
  ([drag-polar refs](https://aerotoolbox.com/drag-polar/)); a slender cruciform missile is up at
  the top of / above that range.

**Recommended cruciform value:** `K ≈ 0.2` (range 0.15–0.35 depending on fins-only vs body-lift
sharing). **USE K = 0.2** as the default; it is deliberately on the punishing side so that hard
turns cost real energy. Because `CL ∝ n`, the whole induced term scales as **`n²`** — the crux of §2.

Total drag force: `D = q·S·(CD0 + K·CL²) = q·S·CD0 + K·(n·m·g)²/(q·S)`.
Note the second term ∝ `n²` and ∝ `1/q`: **hard turns at low q are catastrophically draggy.**

---

## 2. Speed bleed in turns — why a burned-out missile dies in the terminal

### 2.1 The governing equation (point-mass, along-track)

The along-velocity equation of motion (Fleeman / Zarchan standard form):

```
dV/dt = (T − D)/m − g·sin(gamma)
```

with, from §1.3,
```
D = q·S·CD0(M)  +  K·(n·m·g)² / (q·S)
     └ parasite ┘   └──── induced (turn tax), ∝ n² ────┘
```

When the motor is **burned out `T = 0`** and flight is level `sin(gamma)=0`, every newton of drag
comes straight off kinetic energy:

```
dV/dt = −(1/m)·[ q·S·CD0 + K·(n·m·g)²/(q·S) ]
```

The induced term scales as **n²**: pulling 5 g instead of 1 g multiplies the *turn* portion of the
drag by **25×**. This is the whole physical story of energy bleed. ([Fleeman EOM & maneuver, *Maximizing Missile Flight Performance*](https://kirill200281.narod.ru/Maximizing_Missile_Flight_Performance.pdf))

### 2.2 Turn kinematics

- Lateral (turn) acceleration `= n·g` (for `n ≫ 1`; exactly `√(n²−1)·g` in a level turn).
- Turn rate `psi_dot = n·g / V`  (rad/s). Turn radius `R = V² / (n·g)`.
- Time to sweep heading change `Δψ`:  `t = Δψ / psi_dot = V·Δψ / (n·g)`.
  A 180° (π rad) reversal at `V`, pulling `n`:  **`t_180 = π·V / (n·g)`.**

### 2.3 Worked example A — Oniks-class, Mach 2.5, 3000 kg, motor OUT, 5 g, 180°

Common inputs: `S = 0.353 m²`, `CD0 ≈ 0.40` (M≈2.5, §1.2), `K = 0.2`, `m = 3000 kg`, `n = 5`.
`V0 = 2.5·a`. This is an *energy* calc — integrate `dV/dt` over `t_180`.

**At sea level** (`rho = 1.225`, `a = 340` ⇒ `V0 = 850 m/s`):
- `q = 0.5·1.225·850² = 4.43e5 Pa`.
- Parasite drag `= q·S·CD0 = 4.43e5·0.353·0.40 = 6.25e4 N`.
- Induced `= K·(n m g)²/(q S) = 0.2·(5·3000·9.81)²/(4.43e5·0.353) = 0.2·(1.472e5)²/(1.564e5) = 2.77e4 N`.
- `D ≈ 9.0e4 N` ⇒ `dV/dt ≈ −30 m/s²`.
- `t_180 = π·850/(5·9.81) = 54 s`. But drag is enormous — the missile decelerates hard; integrating
  (drag falls as V falls) it sheds on the order of **~700–900 m/s over the reversal**, i.e. it drops
  from M2.5 toward **M1–1.5 and risks falling into the transonic hump.** Sea-level hard turns are
  brutal: dense air → huge `q` → huge parasite drag, *and* the turn tax on top.

**At 15 km** (`rho = 0.209`, `a ≈ 295` ⇒ `V0 = 738 m/s`):
- `q = 0.5·0.209·738² = 5.69e4 Pa` — **~8× lower q than SL.**
- Parasite `= 5.69e4·0.353·0.40 = 8.0e3 N`.
- Induced `= 0.2·(1.472e5)²/(5.69e4·0.353) = 0.2·2.166e10/2.01e4 = 2.16e5 N` **(!!)** — induced drag
  *explodes* because it scales `1/q`. At this thin-air condition the missile may not even *make* 5 g
  (see §3 corner speed). If it can, `D ≈ 2.2e5 N`, `dV/dt ≈ −73 m/s²` — but realistically the
  autopilot is g-limited by `CLmax` first and the turn is slower/wider.

**Takeaway (matches missile literature):** down low, *parasite* drag dominates and speed bleed in a
turn is severe but the missile *can* pull the g. Up high, the missile bleeds less to parasite drag
but **cannot generate the lift** to pull hard g at all, and if forced to, induced drag is ruinous.
Neither regime lets a coasting supersonic missile sustain a hard high-g turn — exactly why terminal
maneuvers must be *short*. ([Zarchan, *Tactical & Strategic Missile Guidance*](https://arc.aiaa.org/doi/book/10.2514/4.868948); [Fleeman](https://kirill200281.narod.ru/Maximizing_Missile_Flight_Performance.pdf))

### 2.4 Worked example B — 48N6, Mach 6, 20 g terminal snap

`S = 0.196 m²`, `m ≈ 1800 kg` ([48N6 mass](https://www.deagel.com/Weapons/48N6/a000994)),
`n = 20`, `CD0 ≈ 0.25` (M≈6). A 20 g pull is a *terminal* SAM maneuver, done high & fast.
At, say, 10 km (`rho = 0.30`), `V = 6·300 = 1800 m/s` ⇒ `q = 0.5·0.30·1800² = 4.86e5 Pa`:
- Induced `= K·(n m g)²/(q S) = 0.2·(20·1800·9.81)²/(4.86e5·0.196) = 0.2·(3.53e5)²/(9.53e4) = 2.62e5 N`.
- Parasite `= 4.86e5·0.196·0.25 = 2.38e4 N`.
- `D ≈ 2.86e5 N` ⇒ `dV/dt = −159 m/s²`. A 20 g snap that lasts even **1–2 s bleeds 160–320 m/s** and
  the induced (n²) term is 90 % of it. This is why SAMs do their hard turn *once*, at the endgame,
  and why a target that forces multiple reversals can make the interceptor run out of energy — the
  "drag the missile until it can't turn" defence. Rule of thumb (Zarchan): **each hard terminal
  maneuver costs the interceptor a chunk of its remaining speed margin; two or three and it misses.**

### 2.5 Rules of thumb to bake in (from the literature)

- **Turn tax ∝ n²** — doubling g quadruples induced drag. (Fleeman EOM.)
- **Induced drag ∝ 1/q** — the same g costs 8× more drag at 15 km than at SL for the same TAS.
- **Sustained-g needs thrust.** With `T=0`, any `n>1` is pure deceleration; a missile can only
  *sustain* the g at which `T = D`. Burned-out ⇒ no sustained turning, only a decaying spiral.
- **Don't fall through Mach 1.2.** Bleeding back into the transonic CD0 hump (§1.2) is a
  death-spiral: more drag → slower → even less available-g.
- **Corner speed** (§3) is the sweet spot: fastest turn rate for least energy loss.

---

## 3. Autopilot architecture — command → fin deflection, and the g you *actually* get

### 3.1 What guidance hands the autopilot

The guidance law (proportional navigation, PN) outputs a **commanded lateral acceleration**
`a_cmd = N·Vc·λ_dot` (N ≈ 3–5, Vc closing speed, λ_dot LOS rate). The autopilot's job is to turn
`a_cmd` (in g's, `n_cmd = a_cmd/g`) into fin deflections that produce that acceleration — subject to
hard physical limits. It does **not** achieve it instantly or perfectly.

### 3.2 The three-loop autopilot (industry standard)

Real tactical missiles use a **three-loop acceleration autopilot** ([Analysis & improvement of missile three-loop autopilots](https://www.researchgate.net/publication/260508614_Analysis_and_improvement_of_missile_three-loop_autopilots); [three-loop pitch-plane design](https://www.ijerd.com/paper/vol1-issue8/C0181217.pdf)):

1. **Innermost — rate loop** (pitch-rate `q` gyro feedback): adds damping, stabilises the fast
   airframe short-period mode.
2. **Middle — synthetic-stability / accelerometer-rate loop:** shapes the response, sets the
   effective time constant.
3. **Outer — acceleration loop:** drives achieved lateral accel to `a_cmd`.
Gains are **gain-scheduled on dynamic pressure `q`** (and Mach/altitude) so the loop behaves
consistently as the airframe's control effectiveness changes across the envelope
([gain-scheduling on q](https://www.sciencedirect.com/science/article/abs/pii/S1270963817311550)).

### 3.3 Achieved-vs-commanded lag — model it as first order

For a point-mass sim you do **not** simulate the fins. Collapse the whole autopilot+airframe into a
**first-order lag** between commanded and achieved lateral acceleration ([Zarchan's standard flight-control model](https://arc.aiaa.org/doi/book/10.2514/4.868948)):

```
a_achieved_dot = ( a_cmd_clamped − a_achieved ) / tau
```

- **Time constant `tau ≈ 0.2–0.5 s`** for a tactical missile (agile terminal SAM ~0.15–0.3 s;
  larger/slower weapon ~0.4–0.6 s). **USE tau = 0.3 s** default. This lag is *load-bearing*: it is
  why a missile overshoots, why it can't perfectly track a jinking target, and why last-instant
  target maneuvers work.

### 3.4 The two hard limits on `a_cmd`

Before the lag, **clamp** `a_cmd` by the *smaller* of two ceilings:

**(a) Structural / alpha limit** — the airframe/autopilot won't command beyond a max angle of attack
`alpha_max` (and a structural `n_struct`, e.g. 30–40 g for a SAM, 10–15 g for a big cruise weapon).
`alpha_max` caps `CLmax`.

**(b) Aerodynamic (q-limited) available-g — the one that makes low speed lethal-to-*yourself*:**

```
n_available = q · S · CLmax / (m · g) = 0.5·rho·V²·S·CLmax / (m·g)
```

This is the single most important autopilot equation for realism. **Available g ∝ q ∝ rho·V².**
([available-g / CLmax·q relation](https://help.agi.com/stk/Content/aircraft/missileModels.htm), [NAVAVSCOLSCOM aero SG-200](https://www.cnatra.navy.mil/training/assets/media/aerodynamics/aero-trainee-guide.pdf))

Consequences:
- **At low speed a missile physically cannot pull its rated g.** A 30-g SAM at Mach 0.8 low down
  might only make 6–8 g; the same missile at Mach 4 makes its full 30 g and is alpha/structure-limited.
- **At high altitude, same story via `rho`.** Thin air ⇒ low `q` ⇒ low available-g. This is the
  hard ceiling that §2.3's "can it even make 5 g at 15 km?" runs into.

Take `CLmax ≈ 0.9–1.4` (cruciform, high-alpha capable; body+fin lift). **USE CLmax = 1.2.**

### 3.5 Corner speed

The **corner speed** `V*` is where the two ceilings cross: the lowest speed at which the missile can
*just* pull its full structural/alpha g. ([corner-velocity definition](https://pressbooks.lib.vt.edu/aerodynamics/chapter/chapter-8-accelerated-performance-turns/))

```
n_struct = 0.5·rho·V*²·S·CLmax /(m·g)   ⇒   V* = sqrt( 2·n_struct·m·g / (rho·S·CLmax) )
```

- **Above `V*`:** structure/alpha-limited (plenty of q, you choose the g). Turning faster than
  needed just wastes energy.
- **Below `V*`:** q-limited (you get less g than rated, no matter how hard you pull the fins) — the
  missile "mushes". Fall well below `V*` and it can't turn enough to correct LOS rate → miss.
- **At `V*`:** best turn rate for the energy. The autopilot/guidance ideal is to arrive at the
  endgame *at or above* corner speed with energy to spare.

Example: 48N6, `n_struct = 25`, `m=1800`, `S=0.196`, `CLmax=1.2`, at 10 km (`rho=0.30`):
`V* = sqrt(2·25·1800·9.81/(0.30·0.196·1.2)) = sqrt(8.83e5/0.0706) = sqrt(1.25e7) ≈ 3540 m/s ≈ M12`
— i.e. at 10 km it is *always* q-limited below its structural g for realistic speeds; the thin air,
not the airframe, sets its turn. Down at sea level `rho=1.225`, `V* ≈ 1750 m/s ≈ M5.1` — now it can
reach structural g in the lower/faster part of its envelope. **This altitude dependence is exactly
the behaviour to reproduce.**

---

## 4. Boost / burnout — mass change and the velocity you buy

### 4.1 Propellant mass fraction

Solid rocket motors in tactical missiles are **50–60 % of total mass as motor**, with propellant
mass fraction (propellant / motor mass) high, and *system* propellant fraction typically **0.5–0.6**
([Fleeman via NASA JANNAF: motor ≈ 50–60 % of system mass](https://ntrs.nasa.gov/api/citations/20240015535/downloads/JANNAF%209871%20Propellants%20for%20Space%20Kibbey.pdf); [solid-propellant rocket / Wikipedia](https://en.wikipedia.org/wiki/Solid-propellant_rocket)). Optimised space motors (STAR series) hit 0.9+, but tactical rounds carry seekers,
warheads, wings → **use ~0.5.**

### 4.2 Boost-sustain thrust profile

Tactical motors commonly run **boost-sustain**: a short high-thrust boost to get to flying speed,
then a long low-thrust sustain to hold it against drag ([boost-sustain profile](https://ntrs.nasa.gov/api/citations/20240015535/downloads/JANNAF%209871%20Propellants%20for%20Space%20Kibbey.pdf)).
For the sim, model as **piecewise-constant thrust stages** with a mass-flow per stage:

```
mdot = T / (Isp · g)        m(t+dt) = m(t) − mdot·dt   (only while fuel remains & stage active)
```

Oniks is the special case: a solid **booster inside the ramjet**, then a **liquid-fuel ramjet
sustain** that runs for most of the flight (see `oniks_reference.md` §1.6). Model it as
boost stage → long sustain stage whose thrust *falls with altitude/Mach* (ramjet ∝ air mass flow).

### 4.3 Ideal rocket equation with losses

Ideal (vacuum, no drag/gravity) velocity gain:

```
ΔV_ideal = Isp · g · ln( m_initial / m_burnout ) = Ve · ln(m0/mf)
```

Real burnout speed is **less**, by gravity and drag losses accrued during boost
([ideal rocket eq. & losses](https://en.wikipedia.org/wiki/Solid-propellant_rocket)):

```
ΔV_real = Isp·g·ln(m0/mf)  −  ∫ g·sin(gamma) dt  −  ∫ (D/m) dt
                              └ gravity loss ┘     └ drag loss ┘
```

- **Gravity loss:** for a near-horizontal sea-skimmer boost, `sin(gamma)≈0` → negligible; for a
  vertical SAM launch it's real (`≈ g·t_boost`, tens–hundreds of m/s).
- **Drag loss:** big for a low-altitude high-q boost. A solid `Isp ≈ 240–260 s` boost with mass
  fraction 0.5 gives `ΔV_ideal = 250·9.81·ln(1/0.5) ≈ 1700 m/s` ideal; real burnout Mach after
  losses lands the round at its ~M2.5 (Oniks) / M6 (48N6) cruise/burnout number — which is the
  cross-check that the fractions above are right.

**Don't over-model.** Just integrate the same `dV/dt` from §2 with `T>0` during boost and mass
decreasing; the losses fall out automatically. The rocket equation is the *sanity check*, not the
runtime path.

---

## 5. Practical sim recipe — the pseudo-5DOF tick

This is the standard **point-mass 3-DOF with load-factor-limited turning** ("pseudo-5DOF") used in
engagement sims: a handful of ops per tick, physically honest energy. State per missile:
`position (3)`, `velocity vector or (V, heading, gamma)`, `mass m`, `a_achieved` (lateral, per axis).

### 5.1 Per-tick algorithm (dt ≈ 0.01–0.02 s)

```
# --- environment ---
rho = 1.225 * exp(-h / 8500)
a_snd = 340.3 - 0.00394*h            # or table
M   = V / a_snd
q   = 0.5 * rho * V*V

# --- propulsion / mass ---
T = thrust_stage(t)                  # boost / sustain / 0 (coast); table per weapon
if fuel_remaining > 0:
    mdot = T / (Isp * g)
    m   -= mdot * dt ; fuel_remaining -= mdot*dt
else:
    T = 0

# --- guidance command (PN) -> desired lateral accel ---
a_cmd = N * Vc * lambda_dot          # from seeker; N ~ 3-5

# --- AVAILABLE-G CLAMP (the realism core) ---
n_avail = q * S * CLmax / (m * g)              # aero ceiling  (§3.4b)
n_max   = min(n_avail, n_struct)               # vs structural/alpha ceiling
a_cap   = n_max * g
a_cmd   = clamp(a_cmd, -a_cap, +a_cap)

# --- autopilot first-order lag (achieved != commanded) ---
a_achieved += (a_cmd - a_achieved) * (dt / tau)          # tau ~ 0.3 s  (§3.3)
n = abs(a_achieved) / g

# --- aerodynamic forces ---
CL  = (n * m * g) / (q * S)                    # lift coeff needed for this n
CD  = CD0_table(M) + K * CL*CL                 # drag polar  (§1.2, §1.3)
D   = q * S * CD

# --- equations of motion ---
dV      = ((T - D)/m - g*sin(gamma)) * dt      # ALONG-TRACK: speed bleed lives here (§2.1)
V      += dV
turn_rate = a_achieved / V                     # rad/s ; apply to heading (and gamma for pitch axis)
heading += turn_rate * dt
# integrate position from (V, heading, gamma)
```

**Why this is enough:** the `K·CL²` term with `CL ∝ n` makes hard turns bleed speed as `n²`; the
`n_avail = qS·CLmax/mg` clamp makes low speed / high altitude genuinely un-maneuverable; the `tau`
lag makes tracking imperfect; the `CD0(M)` table puts the transonic wall in. All emergent, no dice.

### 5.2 Recommended constants — the three example missiles

| Constant | P-800 Oniks | 48N6 (S-300) | Tomahawk | source / note |
|---|---|---|---|---|
| Diameter `d` (m) | 0.67 | 0.50 | 0.52 | [CSIS](https://missilethreat.csis.org/missile/ss-n-26/) / [48N6 deagel](https://www.deagel.com/Weapons/48N6/a000994) / [Tomahawk wiki](https://en.wikipedia.org/wiki/Tomahawk_missile) |
| Ref area `S=πd²/4` (m²) | **0.353** | **0.196** | **0.212** | body cross-section |
| Launch mass `m0` (kg) | 3000 | 1800 | 1450 | [Oniks](https://en.missilery.info/missile/jakhont) / [48N6](https://www.deagel.com/Weapons/48N6/a000994) / [Tomahawk](https://en.wikipedia.org/wiki/Tomahawk_missile) |
| Burnout/cruise mass (kg) | ~2000 (ramjet) | ~900–1000 | ~1200 (booster gone) | prop. fraction ~0.5 |
| Cruise/burnout Mach | 2.5 | 6 (burnout) | 0.74 | given / [48N6 M6](https://www.deagel.com/Weapons/48N6/a000994) |
| CD0 subsonic | 0.30 | 0.32 | **0.30** (its whole life) | §1.2 body-area |
| CD0 transonic peak | 0.55 | 0.55 | n/a (never goes there) | §1.2 |
| CD0 at cruise M | 0.40 (M2.5) | 0.25 (M6) | 0.30 (M0.74) | §1.2 |
| Induced factor `K` | 0.20 | 0.20 | 0.18 | cruciform, §1.3 |
| `CLmax` | 1.2 | 1.2 | 0.9 (cruise config) | §3.4 |
| Structural g `n_struct` | ~8–10 | ~25–30 | ~3–4 | ASCM vs SAM vs cruise |
| Autopilot `tau` (s) | 0.4 | 0.25 | 0.5 | §3.3 |
| Motor `Isp` (s) | ~240 solid boost / ramjet | ~250 solid | ~230 solid boost + turbofan | §4 |
| Propellant fraction | ~0.5 (+ ramjet fuel) | ~0.5 | booster ~0.1 + fuel | §4.1 |

> **Tuning note (repo memory: "Missile gains tuned for Oniks"):** the descent/guidance gains are
> Mach-2.5-calibrated. A Mach-6 48N6 or a faster Zircon will overfly with Oniks gains — its higher
> `V` makes `turn_rate = a/V` smaller for the same g, so it needs **per-weapon descent/guidance
> scaling** (roughly ∝ V) or it won't pitch over in time. Keep `tau`, `n_struct`, and the CD0 table
> per-weapon; do not share one tune across the Mach range.

---

## 6. Source list

**Primary textbooks (buy/borrow — the authoritative references):**
- Eugene L. Fleeman, *Tactical Missile Design* (AIAA Education Series) — ch. "Aerodynamic
  Considerations" (drag build-up, CD0 components), "Flight Performance" (EOM, turn, rocket eq.).
  Course notes: [docplayer scan](https://docplayer.net/117312640-Tactical-missile-design-tactical-missile-design-professional-development-short-course-on-eugene-l-fleeman.html)
- E. L. Fleeman, *Maximizing Missile Flight Performance* (short-course PPT/notes) — worked EOM,
  drag, propulsion trade charts: [PDF](https://kirill200281.narod.ru/Maximizing_Missile_Flight_Performance.pdf), [slides](https://www.slideshare.net/slideshow/maximizing-missile-flight-performance-ppt/272561912)
- Paul Zarchan, *Tactical and Strategic Missile Guidance* (AIAA, Progress in Astronautics &
  Aeronautics) — PN guidance, flight-control first-order lag model, maneuver/energy: [AIAA](https://arc.aiaa.org/doi/book/10.2514/4.868948), [archive scan](https://archive.org/details/TacticalAndStrategicMissileGuidance2012)

**Aerodynamics / atmosphere:**
- NASA GRC, *Induced Drag Coefficient* & *Drag Coefficient*: [induced](https://www1.grc.nasa.gov/beginners-guide-to-aeronautics/induced-drag-coefficient/), [drag](https://www.grc.nasa.gov/www/k-12/VirtualAero/BottleRocket/airplane/dragco.html)
- *Zero-lift drag coefficient* & *Lift-induced drag*, Wikipedia: [CD0](https://en.wikipedia.org/wiki/Zero-lift_drag_coefficient), [induced](https://en.wikipedia.org/wiki/Lift-induced_drag)
- Drag polar (`CD=CD0+KCL²`, `K=1/πARe`): [AeroToolbox](https://aerotoolbox.com/drag-polar/), [lissys c05](https://www.lissys.uk/pug/c05.html)
- *International Standard Atmosphere* (rho0=1.225, scale height ~8.4–8.5 km): [Wikipedia](https://en.wikipedia.org/wiki/International_Standard_Atmosphere)
- Corner velocity / turn performance: [Aerodynamics & Aircraft Performance ch.8](https://pressbooks.lib.vt.edu/aerodynamics/chapter/chapter-8-accelerated-performance-turns/), [NAVAVSCOLSCOM aero SG-200](https://www.cnatra.navy.mil/training/assets/media/aerodynamics/aero-trainee-guide.pdf)

**Autopilot:**
- *Analysis and improvement of missile three-loop autopilots*: [ResearchGate](https://www.researchgate.net/publication/260508614_Analysis_and_improvement_of_missile_three-loop_autopilots)
- *Three-loop lateral missile autopilot design in pitch plane*: [IJERD PDF](https://www.ijerd.com/paper/vol1-issue8/C0181217.pdf)
- Gain-scheduling on dynamic pressure (rolling-airframe three-loop): [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S1270963817311550)
- Available-g / CLmax·q missile model: [AGI STK missile models](https://help.agi.com/stk/Content/aircraft/missileModels.htm)

**Propulsion / mass:**
- *Solid-propellant rocket* (rocket eq., mass fraction, boost-sustain): [Wikipedia](https://en.wikipedia.org/wiki/Solid-propellant_rocket)
- NASA JANNAF, propellant mass fractions / motor % of system mass: [NTRS PDF](https://ntrs.nasa.gov/api/citations/20240015535/downloads/JANNAF%209871%20Propellants%20for%20Space%20Kibbey.pdf)

**Missile data:**
- P-800 Oniks: [CSIS SS-N-26](https://missilethreat.csis.org/missile/ss-n-26/), [missilery.info](https://en.missilery.info/missile/jakhont) (and repo `oniks_reference.md`)
- 48N6 / S-300: [deagel](https://www.deagel.com/Weapons/48N6/a000994), [S-300 wiki](https://en.wikipedia.org/wiki/S-300_missile_system)
- Tomahawk: [Wikipedia](https://en.wikipedia.org/wiki/Tomahawk_missile), [CSIS](https://missilethreat.csis.org/missile/tomahawk/)

---
*End — `missile_energy_autopilot_2026-07-05.md`. Normative for the flight-model rewrite. Cross-refs:*
*`oniks_reference.md` (geometry), `dedicated_missile_models_reference.md`, `s300_reference.md`.*
