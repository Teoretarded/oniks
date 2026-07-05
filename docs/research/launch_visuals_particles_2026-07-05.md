# What Missile Launches Look Like — Visual Reference + Efficient Particle Rendering

Research date: 2026-07-05. Compiled for the "oinks PROTO" missile-defense sim.
Companion to the deeper single-weapon studies already in this folder:
`s300_reference.md` (cold-launch frame timeline), `oniks_launch_sequence.md`
(P-800 / BrahMos frame-by-frame + 10-step storyboard). This doc is the
**cross-weapon visual briefing** + a **concrete particle recipe** sized to the
project's existing `engine/particles.py` pools and a ~2000-particle budget.

Two audiences:
- **Part A** — for a VFX artist who can't watch the footage: what each launch
  type *looks like*, frame by frame, with timing.
- **Part B** — for the renderer: exact emission rates, lifetimes, sizes, RGB
  color ramps and blend modes that fit an RTX 3050 4GB / OpenGL 3.3 / PyOpenGL
  pipeline with a single interleaved streamed VBO.

Confidence marks: ★ = direct footage/primary source or measured in-repo;
☆ = inference / secondary source.

---

# PART A — VISUAL REFERENCE

## Signature quick-table (what separates the launch types at a glance)

| Weapon | Launch mode | Flame at exit? | Muzzle event | Smoke color | Trail life | Tell |
|---|---|---|---|---|---|---|
| **S-300 (48N6)** | COLD / catapult | **No** — silent dark pop-up, then hang | grey dust puff only, THEN ignition fireball 1–1.5 s later at ~20 m | bright white (aluminized) | thick, ~12 s boost | the **eject–hang–BOOM** and the kinked column |
| **P-800 Oniks / Bastion** | HOT ride-out (ПАД + low-thrust) | **Yes**, at the muzzle | pink-grey ПАД mushroom + orange fireball around canister | cream-white → dark grey on boost | lingers, candy-cane kink | slow heavy rise, nose-jet pitch-over, then violent boost |
| **Tomahawk (Mk41 VLS)** | HOT | **Yes**, jet out of cell + adjacent uptake | flame + smoke from cell AND shared uptake hatch | thick opaque white | ~6–12 s boost, then **near-nil** turbofan cruise | booster drops away, trail just stops → clean subsonic cruise |
| **Buk (9M38)** | HOT, inclined ~20–40° | **Yes**, instant | flash + dust off the rail | white → grey | short, horizontal-ish | instant violent departure off a tilted rail |
| **Pantsir (57E6)** | HOT, near-vertical off tube | **Yes**, instant | small flash | thin, reduced-smoke | thin, fast, fades quick | a **needle** of a trail; tiny dart, gone in a blink |

---

## 1. S-300 vertical COLD launch — the "eject, hang, BOOM"

This is the visually unique one: the missile leaves the tube **with no flame at
all**. (Full timeline in `s300_reference.md` §1; summarized here for the artist.)

**Frame-by-frame (t = 0 at tube exit):**

- **t ≈ −0.1 s — Cover blow + tube puff.** The TPK front cover is shot/blown
  clear. A single **annular grey-white dust/gas puff** coughs out of the tube
  mouth — this is catapult gas-generator efflux, NOT rocket exhaust. Thin,
  ~1 tube-diameter ring, dissipates in ~1 s. ★
- **t = 0.0 s — Cold ejection.** The missile is thrown straight up out of the
  tube at **~20 m/s** by the internal catapult. **It is a dark, slender,
  FLAMELESS dart.** The 4 tail fins **snap open the instant it clears the mouth.**
  No plume, no glow — just a body rising on momentum. ★
- **t = 0.0–1.5 s — The hang.** Pure ballistic coast. The missile visibly
  **decelerates** under gravity, slowing to near-zero vertical speed at
  **~20–30 m** altitude. This dead, silent, flameless drift is the signature.
  On a failed launch it literally falls back onto the TEL — proof the hang is
  real, thrust-free physics, not an effect. ★
- **t ≈ 1.0–1.5 s — IGNITION (the money frame).** Motor light-off at/near apex.
  **One frame:** dim coasting dart. **Next frame:** a **spherical orange-yellow
  fireball** erupts around the lower half of the missile, **3–4 body-diameters
  wide** (wider than the missile). Simultaneously an **expanding grey-white smoke
  donut/torus** blooms at ground/base level, and **cover + catapult-tray debris
  chunks** (6–8 brown fragments) are flung radially. Ground dust slams outward,
  lit orange by the flash. ★
- **t = 1.5–3.5 s — Tip-over + column kink.** A **blinding yellow-white torch**
  ~2 body-lengths long now trails the missile. It leaves a **dense, bright-white
  smoke column** with a grey core. Gas-dynamic vanes slew the missile toward
  target bearing, so the column develops a **sharp kink** 30–100 m up — vertical
  below the kink, slanted above it. The TEL sits buried in a white ground cloud. ★
- **t = 1.5–13.5 s — Boost.** ~12 s burn to ~1900 m/s. Brilliant white torch,
  thick white trail, missile shrinks to a dot. **Trail ends abruptly at
  burnout** (~13.5 s); after that the missile is a fast, silent, bleeding dart. ★

**Palette:** ignition fireball = orange→yellow-white core; boost torch =
blinding yellow-white; smoke = **bright white** (aluminized propellant, see §5);
tube puff and debris dust = neutral grey.

---

## 2. P-800 Oniks / Bastion near-vertical HOT launch

Full study in `oniks_launch_sequence.md`. Unlike the S-300, **flame is at the
muzzle from the very first frame** — it's a hot ride-out, not a cold pop.

**Frame-by-frame (t = 0 at tube exit):**

- **t ≈ −0.3 s — Muzzle blast.** Canister cap blows off in chunks. A **pink-grey
  ПАД (powder-pressure-accumulator) gas cloud punches ~10 m up and out** of the
  muzzle, and one frame later an **orange fireball** blooms around the canister
  mouth as the in-tube booster flame breaches. On the land Bastion TEL this reads
  as a genuine fireball engulfing the canister tops for ~1 s. Dark cap debris
  tumbles at frame edge. ★
- **t = 0.0 s — Exit at 25–40 m/s.** The nose spears out of the fire; the whole
  ~9 m body clears in ~0.3 s with **flame washing around the tail/base** out of
  the tube. A **radial ground wash of smoke engulfs the TEL/deck.** ★
- **t = 0.5–2.0 s — The heavy ride.** Low-thrust climb to ~100–200 m, **barely
  accelerating** — a slow, stately, "standing on its flame" rise. Short brilliant
  **white-orange tail flame** ~1–1.5 body-lengths; a **dense CREAM-white smoke
  column 3–5 m wide**, slightly corkscrewed by attitude pulses. ★
- **t ≈ 1.5–2.5 s — Pitch-over (the "hesitation").** **Asymmetric orange puffs
  at the NOSE** (nose-cap pulse motors) — reads as a second flame on the
  airframe. The missile rotates toward target bearing at up to ~90–120°/s; the
  trail **kinks into the candy-cane** (straight column, tight bend, inclined leg).
  Vertical speed plateaus → the eye reads this as a hang. ★
- **t ≈ 2.5–3.5 s — Cap jettison + boost.** A small forward flash; the black cone
  cap shoots forward and tumbles away. **Immediately** the high-thrust mode lights:
  **plume blooms ~4× bigger, white-yellow core,** and the trail smoke turns
  **noticeably darker grey.** The missile visibly jumps away from its own smoke. ★
- **t = 3.5–9 s — The streak.** Flat/shallow boost, brutal acceleration through
  M1→M2; **trail thins to a pencil line** as speed grows. ★
- **t ≈ 7–10 s — Ghost mode.** Booster burnout: **the smoke line just STOPS
  mid-sky;** a dark spent-booster slug spits from the tailpipe; the ramjet takes
  over with a **near-transparent** exhaust — only heat shimmer and a receding
  glint remain. ☆

**Palette:** muzzle cloud = **pink-grey**; ride-out smoke = **cream-white**;
nose puffs = small orange asymmetric; boost trail = **dark grey**; ramjet =
transparent + shimmer.

---

## 3. Tomahawk Mk41 VLS launch

Hot-launch cruise missile: a solid booster throws it out and up, then drops away
and a smokeless turbofan takes over. The two-phase "loud then silent" is the tell.

**Frame-by-frame (t = 0 at cell exit):**

- **t ≈ −0.2 s — Cell + uptake fire.** The Mk41 is a **hot-launch** system with a
  shared exhaust plenum: each 8-cell module (2×4) vents through a **common uptake
  hatch between the two rows.** So at ignition you see a **flame jet blasting up
  out of the missile's own cell AND a second sheet of flame/exhaust roaring out of
  the adjacent uptake hatch** — a distinctive double-source blast unique to VLS.
  A water-deluge steam wisp may accompany it. ★ (Mk41 exhaust-management sources.)
- **t = 0.0–1 s — Fast bright rise.** The Mk135 booster (550 lb solid) throws the
  3200 lb missile up on a **bright yellow-white plume** — a much faster, more
  aggressive rise than the heavy Oniks ride-out. A **thick, opaque white smoke
  column** stands off the deck; the ship's launch cell area is wreathed in white
  smoke and steam. ★
- **t = 1–12 s — Boost climb + tip.** The missile climbs and pitches over toward
  the flight azimuth on the booster. Thick white aluminized-propellant trail
  (see §5). ☆
- **Booster separation (~6–12 s in, ~partway through the climb).** The spent
  booster **falls away** — visually a small puff/discontinuity and a dark object
  tumbling back, then the trail character changes. ★ (Booster "falls away once it
  has burned its fuel.")
- **After separation — turbofan cruise.** Wings, tail fins and air inlet unfold;
  the **F107 turbofan (~600 lbf, RJ4 fuel) takes over.** The missile drops to
  ~880 km/h and flies **nearly smokeless** — no bright plume, no white column,
  just a small dark cruise missile with at most a faint heat haze. **The trail
  essentially ends at booster burnout.** ★

**Palette:** booster plume = yellow-white; smoke = **thick opaque white** (this
is aluminized/standard propellant, cf. ESSM's near-invisible minimum-smoke plume
in §5); cruise = no visible exhaust.

---

## 4. Buk / Pantsir inclined HOT launches — instant, violent, short

Both are **hot launches with no cold-eject phase and no hang** — the motor is
lit at t=0 and the missile is *gone*. No footage-grade timeline in the sources,
so this is the general read (☆ except where noted).

**Buk (9M38/9M317, off an inclined rail ~20–40°):**
- **t = 0.0 s — Instant departure.** Motor lights on the rail; the missile
  **leaps off violently and immediately**, no ballistic pop, no hang. Bright
  flame from the first frame.
- A **flash + dust kick** off the rail/vehicle; a **white→grey smoke trail** laid
  roughly along the inclined launch line (more horizontal than the S-300/Oniks
  vertical columns).
- Fast boost, then the trail persists a few seconds and drifts. The overall
  gesture is a **diagonal streak** rather than a vertical column with a kink.

**Pantsir-S1 (57E6, near-vertical off a canister tube, bicaliber missile):**
- **t = 0.0 s — Instant, and thin.** Small two-stage SAM launched hot from a
  sealed tube; **violent instant departure**, a small flash.
- The 57E6 uses a **reduced-smoke** style motor and is a tiny dart — the trail is
  a **thin, fast, faint line that fades quickly**, not a fat white column. The
  missile accelerates to very high speed and shrinks to a dot in a blink; the
  booster drops and the darted second stage coasts.
- Signature: a **needle** of a trail; the least smoky of the five.

**Contrast to bank against:** S-300 = *ceremony* (pop, hang, boom, kink); Buk =
*a diagonal punch*; Pantsir = *a hiss and a needle*.

---

## 5. Solid rocket exhaust — general physics for the palette

Why the colors are what they are (drives the RGB ramps in Part B):

- **Flame core (the bright part behind the nozzle).** A solid motor's visible
  flame is a **brilliant, near-white-to-orange torch** a few nozzle/body-diameters
  long — for these missiles roughly **1–3 body-lengths** of visible core in the
  ride-out/boost. Aluminized propellants burn especially bright because glowing
  molten **alumina (Al₂O₃)** particles incandesce. The core is **white-hot at the
  root, grading to yellow then orange** toward the tip. ★/☆
- **Mach diamonds / shock diamonds.** Present when the exhaust is over- or
  under-expanded; the **axial spacing between diamonds ≈ the nozzle exit
  diameter.** Solid boosters often run near-optimally expanded and show weak or no
  diamonds. For a game: a faint repeating brightening in the first ~1–2 core
  lengths is enough; don't over-render them. ☆
- **Smoke color — two families:**
  - **Aluminized / "standard" propellant (S-300, Oniks boost, Tomahawk, most SAMs):
    thick, opaque, BRIGHT WHITE smoke.** The exhaust is rich in HCl (from ammonium
    perchlorate) which **condenses atmospheric moisture**, plus white alumina
    particulate — together a dense white/grey-white cloud that lingers. ★
  - **Reduced-smoke / "minimum-smoke" propellant (ESSM-class, some point-defense
    SAMs, Pantsir tendency): thin, translucent, near-invisible plume**, often a
    faint bluish translucency instead of a white column. Little aluminum, less
    condensable exhaust. ★
  - So: **more aluminum → brighter flame + whiter, denser smoke.** Reduced-smoke →
    dim/translucent flame + almost no trail.
- **How the trail evolves:** fresh exhaust is dense and near-white; over seconds
  it **expands (widens), thins, drifts downwind, and greys** as it disperses and
  cools. It also **thins with altitude** (lower air density, less moisture to
  condense) — high-altitude trails are wispier than the fat column at the pad.
- **Ramjet cruise (Oniks after transition):** kerosene ramjet exhaust is **almost
  invisible** — no white smoke, just a faint transparent shimmer/heat haze. The
  Tomahawk turbofan cruise is likewise effectively smokeless. **Model these as
  "trail stops, faint shimmer only."** ★/☆

---

## 6. Launch dust — the ground-effect donut

At every hot launch and at S-300 ignition, exhaust/gas hits the ground and blasts
dust **radially outward as an expanding ring ("dust donut")**:
- Spawns at ground level at the base of the launcher, expands radially at roughly
  **5–15 m/s** in the first second, forming a low, flat, expanding torus.
- Neutral tan/grey dust color, lit orange by the ignition flash for the first
  ~0.3 s, then settling to grey.
- **Lingers ~3–8 s**, drifting and settling; the launcher/TEL is left shrouded in
  a slowly-dispersing ground cloud that drifts downwind for tens of seconds.
- Already implemented in-repo as the muzzle-wash / ignition-donut ring (radial
  horizontal velocities re-shaped after emit; see `engine/particles.py`
  `muzzle_blast` and `ignition_fireball`).

---

## TOP-10 VISUAL SIGNATURES CHECKLIST (cross-weapon, ranked)

Use this as the acceptance checklist when reviewing launch VFX:

1. **S-300 eject–hang–BOOM:** a FLAMELESS dark dart pops out, visibly slows and
   nearly stops ~20–30 m up, THEN a fireball wider than the missile erupts. If the
   viewer never thinks "will it fall back?", the hang is too short.
2. **The smoke-column kink:** vertical white column bending sharply where the
   missile tips over (S-300 gas vanes; Oniks candy-cane). The bend is anchored to
   the launcher and stays after the missile leaves.
3. **Oniks two-phase weight shift:** slow heavy cream-white ride-out, then after
   the nose-cap jettison the plume blooms ~4× and the smoke turns dark grey — the
   missile jumps away from its own smoke.
4. **Nose jets in the pitch-over:** small asymmetric ORANGE puffs at the NOSE
   (not the tail) during the Oniks turn — two flames on one airframe.
5. **Tomahawk double-source blast:** flame from the missile's own cell AND from
   the adjacent shared uptake hatch at VLS ignition.
6. **Tomahawk go-quiet:** thick white booster column, then booster drops and the
   trail simply STOPS — smokeless turbofan cruise, a small dark missile.
7. **Aluminized bright-white vs reduced-smoke translucent:** big SAMs/Tomahawk lay
   thick opaque white columns; point-defense (Pantsir-lean/ESSM-class) leave a
   thin, near-invisible plume.
8. **Trail dies at burnout:** every solid-boost trail ENDS abruptly at burnout
   (Oniks/S-300/Tomahawk); the missile continues as a dot with no plume.
9. **Ground dust donut:** radial expanding dust ring at the base, orange-lit for
   a frame at ignition, then grey, lingering 3–8 s; launcher left shrouded.
10. **Debris + cover blow:** S-300 tube-cap fragments and catapult tray spinning
    away in the ignition fireball; Oniks canister cap chunks and the jettisoned
    nose cone tumbling clear.

---

# PART B — EFFICIENT GAME RENDERING RECIPE

Target: RTX 3050 4GB laptop, OpenGL 3.3, Python + PyOpenGL, an existing simple
particle system, **budget ~2000 live particles.** The repo already implements the
right architecture (`engine/particles.py`): camera-facing billboard quads + a
soft-disc sprite, additive fire / alpha smoke, a streamed interleaved VBO, and a
ribbon trail. This part gives the numbers to hit the 2000 budget and stay ~60 fps.

## B.0 What the existing engine already does right (keep it)

- **Camera-facing billboard quads**, 10 float32/vertex interleaved
  `[px py pz u v r g b a size]`, stride 40 B — one VBO, `glBufferData(...,
  GL_STREAM_DRAW)` re-upload per frame. At a few thousand quads this is fine on a
  3050; a single interleaved streamed VBO is the correct choice (don't reach for
  instancing/persistent-mapped buffers at this scale).
- **Soft circular sprite:** a 64×64 single-channel `R8` "soft disc" =
  `1 − smoothstep(0.35, 1.0, r)`. Cheap, no atlas needed for the baseline.
- **Two blend modes:** smoke/spray **alpha** (`GL_SRC_ALPHA,
  GL_ONE_MINUS_SRC_ALPHA`), fire/flash **additive** (`GL_SRC_ALPHA, GL_ONE`).
  Additive is drawn last, depth-test on, **depth writes off** (`glDepthMask(FALSE)`)
  so particles never punch holes in each other. This is exactly the LearnOpenGL /
  standard-VFX split.
- **Fade + growth over life:** per-particle `size0→size1`, `col0→col1`, alpha
  `1−frac`. Back-to-front sort per pool for correct alpha layering.
- **Ribbon trail** with **distance-based points** (`TRAIL_POINT_SPACING = 35 m`):
  a point is stored only after 35 m of travel, so **trails don't gap at high
  speed** (this is the "emit over distance not over time" rule — essential when a
  Mach-6 missile moves >2 km/frame at 60 fps).

## B.1 The 2000-particle budget — how to spend it

Rule of thumb per the sources: **emit per meter of travel, not per frame**, and
keep smoke lifetimes long (2–8 s) but counts low; keep flame lifetimes tiny
(0.1–0.3 s) but bright. A single boosting missile trail should cost **~150–400
live particles**; that lets you have several missiles + a couple of explosions
inside 2000.

| Effect layer | Blend | Emission | Lifetime | Live count (1 missile) |
|---|---|---|---|---|
| Flame core (torch) | additive | per-meter, see B.2 | **0.1–0.3 s** | ~20–60 |
| Smoke trail column | alpha | per-meter, see B.2 | **2–8 s** (fresh→drift) | ~120–300 |
| Muzzle/ignition blast | mixed | one-shot burst | fire 0.1–0.4 s, smoke 2.5–5 s | ~60–90 (fades out) |
| Ground dust donut | alpha | one-shot ring | 1–3 s | ~16–24 |
| Ribbon trail (far LOD) | alpha strip | 1 point / 35 m | 22 s fade | ~10–40 verts |

**LOD switch:** near the camera, spend particles on the billboard trail; far
away, drop the per-meter billboards and let the **ribbon** carry the trail (it's
~2 verts per 35 m — almost free). This keeps a sky full of missiles under budget.

## B.2 Per-meter emission math (no gaps, bounded cost)

Spawn particles based on distance travelled since the last spawn, not per frame:

```
accumulator += |pos - last_pos|            # metres this frame
while accumulator >= SPACING:
    emit_one(along the segment, lerp position)
    accumulator -= SPACING
```

Recommended spacings (tune to taste):

- **Flame core:** `SPACING_FLAME ≈ 3–5 m`. With 0.1–0.3 s life at boost speed the
  live core is a short bright stub of ~20–60 sprites.
- **Smoke trail:** `SPACING_SMOKE ≈ 6–10 m`. With 3–6 s life this gives a
  continuous column of ~120–300 sprites that widens and greys behind the missile.
- **Ribbon point:** `SPACING_RIBBON = 35 m` (already the repo default).

Cap the while-loop (e.g. max 8 emits/frame) so a teleport/huge-dt frame can't
dump thousands of particles at once.

## B.3 Color ramps (RGB 0–1, birth → death)

These match Part A's palette and the ramps already tuned in `engine/particles.py`.
`col0` = birth (near nozzle / fresh), `col1` = death (dispersed / cooled). Fire
draws additive so its "death" is really "fade toward dim orange then alpha→0".

**Flame core / torch (additive):**
- White-hot boost core: `col0 (1.00, 0.96, 0.74)` → `col1 (1.00, 0.45, 0.10)`
  (white-yellow → orange). Size ~2.6–7 m, life 0.08–0.18 s. (repo `BOOST` fire)
- Low-thrust ride-out core: `col0 (1.00, 0.93, 0.70)` → `col1 (1.00, 0.50, 0.14)`,
  size ~1.2–2.4 m, life 0.12–0.25 s. (repo `RIDEOUT` fire)
- Ignition/explosion flash: `col0 (1.00, 0.97, 0.85)` → `col1 (1.00, 0.62, 0.20)`,
  huge (7–30 m) and very short (~0.12 s).

**Generic white-hot → orange → grey fire-to-smoke handoff** (the classic VFX
ramp, if you drive one gradient): `(1.0,1.0,0.9)` white-hot →
`(1.0,0.55,0.15)` orange → `(0.35,0.34,0.33)` dark grey → alpha 0.

**Smoke columns (alpha):**
- **Aluminized bright-white** (S-300, ignition donut): `col0 (0.86,0.85,0.83)` →
  `col1 (0.58,0.58,0.61)` (bright white → pale grey).
- **Oniks cream ride-out:** `col0 (0.94,0.91,0.85)` → `col1 (0.74,0.73,0.72)`.
- **Oniks dark-grey boost:** `col0 (0.35,0.34,0.33)` → `col1 (0.52,0.52,0.54)`
  (starts dark, greys lighter as it disperses — the boost-leg tell).
- **Muzzle pink-grey (ПАД):** `col0 (0.84,0.72,0.70)` → `col1 (0.58,0.56,0.58)`.
- **Reduced-smoke (Pantsir/ESSM-lean):** skip the column; emit a very faint,
  short-lived translucent puff at low alpha (peak α ≈ 0.1) or nothing.
- **Dirty combustion smoke (ship fire, dark):** `col0 (0.07,0.07,0.07)` →
  `col1 (0.22,0.22,0.24)`.

**Ground dust donut:** neutral, `col0 (0.80,0.78,0.75)` → `col1 (0.60,0.60,0.62)`,
tinted orange for the first ~0.3 s if inside an ignition flash.

## B.4 Blend, depth, sizes, curves

- **Blend:** additive fire (`GL_SRC_ALPHA, GL_ONE`), alpha smoke/dust/spray
  (`GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA`). Draw order: alpha (ribbons → smoke →
  spray) first, then additive fire last, so glow sits on top. Depth test ON,
  **depth write OFF** the whole time.
- **Soft particles (optional polish):** fade a particle's alpha where it's within
  ~0.5–2 m of scene depth (sample the depth buffer in the fragment shader,
  `alpha *= smoothstep(0, softDist, sceneZ - particleZ)`) to kill hard sprite
  intersections against the sea/terrain. Cheap and worth it for the ground donut.
- **Size / alpha curves over life:** smoke **grows** (size0→size1 ≈ 2–4× over
  life) and **fades** (`α = peak·(1−frac)`); flame **shrinks or holds** and fades
  fast. Growth simulates turbulent expansion — the standard fire/smoke curve.
- **Size jitter:** multiply each particle's size by a uniform `[0.75, 1.30]` for
  natural variety (repo `SIZE_JITTER_LO/HI`).
- **Buoyancy/drag:** hot smoke rises (buoyancy ~1.7 m/s²) and drags to a stop
  (~0.45/s exp decay); fire drags hard and dies (repo `SMOKE_*`, `FIRE_*`). Add a
  small constant **wind vector** to all smoke velocity so columns drift and lean —
  cheap realism the sources emphasize.

## B.5 Ribbons vs point sprites — when to use which

- **Point-sprite billboards** (the smoke column): best for **volume and
  softness** near camera; cost scales with count, so gate them by LOD/distance.
- **Ribbon strip** (one triangle-strip along the flight path): best for the
  **long thin persistent contrail** and for **far/high-speed** missiles — a
  handful of verts covers kilometres, never gaps (distance-based points), and it's
  the cheapest way to keep a trail visible after the billboard budget is spent.
- Use **both**: ribbon = the skeleton that's always there; billboards = the
  fluffy near-field body layered on top. The repo already feeds a birth color per
  ribbon point, so the cream→dark-grey boost transition rides the same ribbon.

## B.6 Texture atlas (optional upgrade over the single soft disc)

The single 64×64 soft disc is enough to ship. If you want more organic smoke, bake
a **2×2 atlas of 2–4 smoke puffs** (different noise) into one 128×128 R8 (or RGBA
if you want per-puff shape) texture; pick a random cell per particle via a UV
offset. One texture bind, no extra draw calls. Keep it small — VRAM on a 4GB card
is precious and a soft puff needs almost no resolution.

## B.7 Concrete per-frame budget sanity check

- 3 boosting missiles × (~50 flame + ~250 smoke) = ~900
- 1 ignition/explosion in progress (fading) = ~150
- ground dust + ambient = ~100
- headroom = ~850 → **under the 2000 cap with margin.**
- Cost: one `glBufferData` STREAM_DRAW per pool per frame (smoke/spray/fire) +
  one per active ribbon; ~2000 quads = 8000 verts = 320 KB upload/frame — trivial
  bandwidth for a 3050. The per-frame numpy sort + build is the real cost; the
  repo already bounds every pass to the occupied prefix (`_hi`) to keep it cheap.

---

## SOURCES

**In-repo primary studies (measured / frame-analyzed):**
- `docs/research/s300_reference.md` — S-300 cold-launch frame timeline, ignition,
  tip-over, top-10 signatures.
- `docs/research/oniks_launch_sequence.md` — P-800/BrahMos frame-by-frame,
  patent-backed sequence, 10-step storyboard, per-phase smoke/flame signatures.
- `engine/particles.py` — existing pools, blend modes, color ramps, ribbon trail,
  streamed-VBO renderer (numbers cited in Part B are the live tuning values).

**Missile launch / propulsion:**
- Mk41 VLS exhaust/uptake (hot launch, shared plenum, uptake hatch, water deluge):
  https://en.wikipedia.org/wiki/Mark_41_vertical_launching_system •
  https://www.globalsecurity.org/military/systems/ship/systems/mk-41-vls.htm •
  https://thedefensepost.com/2026/02/24/mk41-vertical-launch-system-guide/ •
  https://www.navalgazing.net/VLS
- Tomahawk booster (Mk135, 550 lb solid, falls away) + F107 turbofan cruise
  (600 lbf, RJ4, ~550 mph): https://en.wikipedia.org/wiki/Tomahawk_missile •
  https://www.l3harris.com/all-capabilities/tactical-tomahawk •
  https://insights.globalspec.com/article/5402/tomahawk-missiles-everything-you-need-to-know
- Exhaust flame/smoke color, aluminized vs minimum-smoke (yellow-white + thick
  opaque white vs translucent blue + thin), APCP chemistry (HCl + moisture
  condensation → white contrail, alumina particulate):
  https://en.wikipedia.org/wiki/Ammonium_perchlorate_composite_propellant •
  https://www.mdpi.com/1996-1073/15/4/1470 (optical diagnostics, solid plumes) •
  https://ntrs.nasa.gov/citations/19770006284 (Shuttle SRM plume, HCl fraction)
- Mach/shock diamonds (spacing ≈ nozzle exit diameter; solids often show weak/no
  diamonds): https://www.ms8.com/shock-diamonds-the-fiery-patterns-in-rocket-exhaust/ •
  https://www.quora.com/Why-dont-solid-rocket-boosters-have-mach-diamonds
- Buk / Pantsir systems (9M38 rail launch; 57E6 tube, reduced-smoke bicaliber):
  https://en.wikipedia.org/wiki/Buk_missile_system •
  https://en.wikipedia.org/wiki/Pantsir_missile_system •
  https://missilethreat.csis.org/defsys/pantsir-s-1/

**Rendering / VFX technique:**
- OpenGL particle rendering (Particle struct, pool reuse of dead particles,
  additive `glBlendFunc(GL_SRC_ALPHA, GL_ONE)` vs alpha, life decay, ~500-particle
  pools, spawn fewer per frame): https://learnopengl.com/In-Practice/2D-Game/Particles
- Billboard particles, additive vs alpha blend, fire core + smoke layer, color
  gradients & size-over-life: https://generalistprogrammer.com/tutorials/game-particle-effects-complete-vfx-programming-guide-2025 •
  https://www.theseus.fi/bitstream/handle/10024/156135/Raappana_Joona.pdf (thesis:
  "Great Particles and How to Make Them")
- Distance-based / rate-over-distance emission to avoid trail gaps on fast movers:
  https://www.edraflame.com/blog/tutorial-unity-particle-systems-constant-emission/ •
  https://discussions.unity.com/t/high-speed-emit-over-distance-particle-system-leaves-gaps/712569 •
  https://vfxdoc.readthedocs.io/en/latest/vfx/particlesystems/
- Color/size/lifetime over particle life (white-hot → orange → grey, size growth
  for expansion): https://docs.unity.cn/Manual//PartSysColorOverLifeModule.html •
  https://www.vfxapprentice.com/blog/everything-know-about-fire-fx •
  https://unity.com/blog/engine-platform/realistic-smoke-with-6-way-lighting-in-vfx-graph
