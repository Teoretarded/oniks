# War Thunder Hit-Camera / X-Ray Visual Language — Normative Design Reference

**Purpose:** describe War Thunder's (WT) hit-camera / X-ray damage view in enough visual
detail that an engineer who has NEVER seen it can reproduce the look-and-feel with 2D or
simple-3D primitives (colored boxes, lines, a translucent hull shell). This is a NORMATIVE
reference for the ONIKS damage-view redesign: the current flat side-view box schematic reads
as lackluster; below is the exact visual grammar that makes WT's version feel great.

**Method & caveat:** compiled 2026-07-06 from WT devblogs, WT wikis, official forum threads,
Steam guides and community analyses (URLs cited inline on every claim). Several primary
devblog pages are archived stubs; where the stub was empty, the claim is sourced from wiki /
forum / guide restatements instead, cited accordingly. Exact hex values are NOT published by
Gaijin; the palette in the 2D-adaptation section is a reconstruction calibrated to the
described color names, and is flagged as such.

---

## 1. The X-Ray Shell (how the vehicle is rendered during the hit cam)

### 1.1 The ghost hull
During the kill cam, the vehicle is drawn as a **semi-transparent, texture-less grey ghost
model** — the outer armor/hull becomes a translucent shell so you can see through it to the
internals. Community description: "Each tank's internal components are represented by
semi-transparent texture-less grey models"
([WebSearch summary of Kill Camera X-ray feature](https://warthunder.com/en/devblog/current/651),
[warthunder.com/en/news/3880--en](https://warthunder.com/en/news/3880--en)). The hull reads as a
frosted-glass / smoked-glass shell; internal modules are rendered as **solid, opaque colored
shapes floating inside** that shell, so the eye separates "skin" (translucent) from "guts"
(solid).

The kill cam's stated job: show "how and where the enemy shell penetrated the armour, which
components were damaged, which assemblies were knocked out and any injuries or debilitation
caused against the crew members"
([warthunder.com/en/news/3880--en](https://warthunder.com/en/news/3880--en)).

### 1.2 What the colors code
WT does NOT use a fixed "this module is always blue" palette for module *type*. Instead the
color of a module encodes its **damage STATE**, and there is a small set of intrinsically
colored hazardous items (crew, ammo, fuel) that are always tinted so you can spot them.

**Crew** — rendered as small human figures. Crew color is a **health gradient**:
- Healthy: **blue / blue-white** (pale, cool tone).
- Lightly injured: shifts toward **yellow**.
- Heavily injured: shifts through **orange** to **red**.
- Knocked out / dead: **hard red outline** (a solid red figure).
Source (community color legend): crew "start out blue/white-ish, then the more hurt they get,
they'll turn more yellow, orange, and red, finally if they are knocked out you'll see them in
a hard red outline… yellow basically means lightly injured, red means heavily injured"
([WebSearch summary](https://old-forum.warthunder.com/index.php?/topic/398790-x-ray-damage-indication-colors-and-the-meaning-of-them/)).
For naval, crew-density overlays go the other way for "value of target": **red areas = most
crew (best target), green areas = least crew**
([wiki.warthunder.com/640-ship-crew-mechanics](https://wiki.warthunder.com/640-ship-crew-mechanics)).

**Ammunition / propellant** — the hazardous ammo is tinted warm and stands out. In WT's own
diagram conventions, **propellant is labelled orange and secondary-armament ammo racks red**
([old-wiki.warthunder.com/How_to_add_Ammo_Rack_information_to_vehicle_pages](https://old-wiki.warthunder.com/How_to_add_Ammo_Rack_information_to_vehicle_pages)
via [WebSearch](https://warthunder.com/en/news/3880--en)). Practically: shells / charges read
as **yellow-to-orange-to-red** cylinders, and when struck they flash red and the feed says
"Ammunition." The point of the color is danger legibility — the eye is drawn straight to ammo
and fuel.

**Fuel tanks** — drawn as distinct solid blocks (commonly a green/olive tint in the module
mesh); a struck fuel tank triggers a "Fuel tank" callout and, if set alight, a fire.

**Engine / transmission / radiator / gun breech / turret ring etc.** — these are ordinary
modules and follow the **damage-state color law** below. At rest (undamaged) they are neutral
grey/steel; their color only appears once hit.

### 1.3 Damaged vs destroyed — the state color law
This is the single most important grammar rule. A module's tint tells you its functional
state, on a four-step ramp
([forum.warthunder.com/t/when-red-doesnt-mean-damaged/83667](https://forum.warthunder.com/t/when-red-doesnt-mean-damaged/83667)):

| Color | Meaning |
|---|---|
| **Yellow** | Operational, light damage |
| **Orange** | Damaged |
| **Red** | Severely damaged but STILL FUNCTIONAL (degraded — e.g. red turret ring = turret turns much slower) |
| **Black** | Destroyed / non-operational (e.g. black turret ring = cannot turn at all) |

Key nuance an artist must respect: **red ≠ dead. Black = dead.** "Red components can still
work, but they won't work well… Damaged doesnt mean dead. Black is dead. Red can sometimes
still operate, but may go out with use"
([forum.warthunder.com/t/when-red-doesnt-mean-damaged/83667](https://forum.warthunder.com/t/when-red-doesnt-mean-damaged/83667)).
So the destroyed state is signalled by **desaturation to black/charred**, NOT by "more red."
The living-to-dead ramp is: grey (fine) → yellow → orange → red (crippled) → black (dead).

The moment of damage is punctuated by a **flash** on the struck module (it lights up in its
new state color for a beat) synchronized with the shell impact — see §2 timing.

---

## 2. The Projectile Visualization (the shell's path INTO the vehicle)

### 2.1 Entry
The incoming shell is shown as a solid tracer/round travelling on its real trajectory. At the
armor it produces an **entry marker** — a bright impact flash / hole at the point where the
armor line is crossed. This is where the "how and where it penetrated" reading happens
([warthunder.com/en/news/3880--en](https://warthunder.com/en/news/3880--en)).

### 2.2 The three armor outcomes (must look different)
WT's Protection Analysis and hit cam encode outcome by color, and the engineer must reproduce
all three as visually distinct
([specailgamemoment.wordpress.com/2018/09/15/protection-analysis-eng](https://specailgamemoment.wordpress.com/2018/09/15/protection-analysis-eng/)):

- **Penetration (green):** the shell path continues *through* the armor line into the interior.
  A clean bright line from entry point deep into the hull.
- **Non-penetration / stopped by armor (red):** the shell path **stops at the armor line** — a
  red impact splash at the surface, no interior line. "can't penetration."
- **Ricochet (grey):** the shell path **bounces off** the armor and deflects away at an angle
  — a grey/steel glancing streak leaving the hull. "ricochet only," no interior damage.
- (Yellow in Protection Analysis = marginal/"wounded" — penetration possible but low; useful
  as an intermediate "just barely got in" tint.)

So: green = went in, red = bounced off flat/stopped, grey = skipped off. The **direction and
termination** of the path line is the primary read; color reinforces it.

### 2.3 The spall / fragment cone (the signature "fan")
After penetration, the shell (or the armor it punched through) throws a **cone of fragments**
into the interior. This is the visual money shot. Fragments **fan out within an arc of roughly
30–45 degrees from the point of penetration**
([wiki.warthunder.com/mechanics/4236-the-mechanics-of-high-explosive-effect-and-overpressure](https://wiki.warthunder.com/mechanics/4236-the-mechanics-of-high-explosive-effect-and-overpressure),
[warthunder.com/en/news/8670-development-detailed-information-surrounding-spall-liners-in-war-thunder-en](https://warthunder.com/en/news/8670-development-detailed-information-surrounding-spall-liners-in-war-thunder-en)).

Physical structure the visual mimics: "a fragmentation stream consists of several groups of
fragments with different angles of expansion… more powerful fragments have narrower cones of
dispersion and smaller numbers"
([WebSearch summary of spall-liner devblog](https://warthunder.com/en/news/8670-development-detailed-information-surrounding-spall-liners-in-war-thunder-en)).
Translated to the visual: a **spray of thin straight rays** originating at the entry point,
fanning forward into the hull in the shell's direction of travel. The rays that **hit a
module or crew figure** trigger that module's damage flash; rays terminate on whatever they
strike. Denser/central rays go deepest; outer rays splay wider and shallower.

### 2.4 HE / overpressure
For HE/overpressure kills the interior blast is shown as **two red spheres in the hit cam**
(the overpressure blast volume), rather than a fan of rays
([wiki.warthunder.com/mechanics/4236-the-mechanics-of-high-explosive-effect-and-overpressure](https://wiki.warthunder.com/mechanics/4236-the-mechanics-of-high-explosive-effect-and-overpressure)).

### 2.5 Timing / speed / duration
- The camera triggers **immediately after the vehicle is destroyed** and replays the fatal
  shot ([warthunder.com/en/news/3880--en](https://warthunder.com/en/news/3880--en)).
- The sequence runs in **heavy slow-motion** so the eye can track the round.
- There is a **beat-pause at the moment of impact/penetration** — the action nearly freezes at
  the entry, the entry flash pops, then the fragment fan plays out and modules flash.
- The whole X-ray beat is short (a few seconds), then control returns / respawn UI appears.
(Slow-mo + impact-pause is consistently described across community coverage of the death cam,
e.g. [youtube.com/watch?v=togFXO-ysB8](https://www.youtube.com/watch?v=togFXO-ysB8) "X-Ray Death
Cam" and [youtube.com/watch?v=X2Eq3nbpUDQ](https://www.youtube.com/watch?v=X2Eq3nbpUDQ) "NEW
Damage Animation and Kill Cam".)

---

## 3. Camera Work

There are effectively **three distinct camera contexts** the engineer should treat separately:

**(a) Kill cam / hit cam (post-death X-ray).** Triggered on your destruction. The camera
frames the target vehicle from a **side-ish / three-quarter angle** that best shows the shell's
entry and the interior it traveled into, then holds on the impact. It is essentially a
scripted "cinematic" of the fatal round: follow the shell in, pause at penetration, reveal the
X-ray interior + fragment fan + module flashes. It can **orbit slightly** to sell the 3D of
the internals but the defining framing is broadside to the shell path so entry→interior reads
left-to-right. ([warthunder.com/en/news/3880--en](https://warthunder.com/en/news/3880--en))

**(b) Shell chase camera (naval, and air ordnance).** A follow-cam that sits **behind the
projectile** and rides it through the air toward the target — used in naval to "personally
follow the flight of the ranging or main salvo," analogous to holding space to track a bomb /
rocket / torpedo in air battles
([warthunder.com/en/news/7194-development-naval-shell-chase-camera-en](https://warthunder.com/en/news/7194-development-naval-shell-chase-camera-en)).
This is the "behind the incoming shell" angle; on impact it can hand off to the hit-cam X-ray.

**(c) Protection Analysis (static, in-hangar tool).** Not a cam of a live event — a free-orbit
inspector. You pick vehicle, shell, and range; you aim a probe at the enemy hull and it draws
the predicted path with the green/yellow/red/grey outcome coloring of §2.2, using "the same
result that the game engine does in battle"
([WebSearch summary](https://warthunder.com/en/news/5569-development-protection-analysis-en),
[specailgamemoment.wordpress.com](https://specailgamemoment.wordpress.com/2018/09/15/protection-analysis-eng/)).
Fully orbitable; this is where players study weak spots.

The "two angles" players talk about = the **kill cam (what killed me, cinematic)** vs the
**protection analysis (what could kill it, interactive)**. Both share the X-ray hull + path +
outcome-color grammar.

---

## 4. Naval Specifics

Ships use the same translucent-hull + solid-module idea but at a much larger scale, with a
dedicated damage-control HUD.

### 4.1 Internal layout
Two crew/compartment models
([wiki.warthunder.com/640-ship-crew-mechanics](https://wiki.warthunder.com/640-ship-crew-mechanics)):
- **Simple layout** (boats/small vessels): crew compartments span the whole watertight hull
  sections (bow / amidships / stern).
- **Complex layout** (large warships): crew compartments drawn as **rectangular prisms along
  the centerline** at intervals; critical modules carry extra crew — **"Boilers and engines
  typically contain the most"** crew, making them the highest-value aim points.

Key internal modules to depict: **magazines / shell rooms** (detonate → catastrophic kill or
flooding), **boilers**, **engines**, **bridge**, **torpedo/depth-charge/mine stores**, plus the
crew-compartment prisms.

### 4.2 Crew-density overlay
A **"Show crew distribution"** button casts a heatmap overlay onto the hull: **red = densest
crew (most damaging to hit), green = least crew**
([wiki.warthunder.com/640-ship-crew-mechanics](https://wiki.warthunder.com/640-ship-crew-mechanics)).

### 4.3 The in-battle damage-control HUD
When a ship takes a hit, a compartment/status indicator updates. From the Steam naval guide
([steamcommunity.com/sharedfiles/filedetails/?id=2841054332](https://steamcommunity.com/sharedfiles/filedetails/?id=2841054332)):
"you'll see an indicator of modules, their status, if there's a fire, if you breached the hull
(far left), and how much crew dies per hit."

- **Compartment color-coding:** sections color by damage level and **turn black when heavily
  damaged/saturated** — "if a section turns black, aim for other sections since that part is
  already mostly damaged." (Same black-=-dead law as ground.) The compartment indicator sits on
  the ship's damage-indicator silhouette.
- **Buoyancy / flooding:** shown as a **percentage**. "When it hits zero or you list too heavily
  to one side for too long, you sink." So the flooding read is a **buoyancy % bar** plus a
  **list/heel** state.
- **Irreparable breaches:** torpedo/bomb breaches flood permanently; once the bulkhead is closed
  the compartment **turns blue and can't be drained.**
- **Fire:** fire ticks damage per second; a **critical fire flashes and plays a warbling siren**
  ("DEEDOODEEDOODEEDOO"). Fire is shown as an icon + flashing highlight on the affected section.
- **Waterline:** the hull is drawn against the sea surface; flooding pulls the hull down / heels
  it, so the waterline creeping up the silhouette is itself the flooding indicator.

### 4.4 Damage-control actions UI
Modern DC replaces manual repair with **three action presets you prioritize**: **firefighting,
module repair, and water pumping**
([warthunder.com/en/news/9795-development-the-new-damage-control-mechanic-for-naval-en](https://warthunder.com/en/news/9795-development-the-new-damage-control-mechanic-for-naval-en)).
The player **adjusts priority** of which area to focus. Each ship has an individual DC
coefficient scaled by hull size, crew count, and ship generation. "Survival Leadership" reduces
the repair time penalty
([steamcommunity.com/sharedfiles/filedetails/?id=2841054332](https://steamcommunity.com/sharedfiles/filedetails/?id=2841054332)).
So the UI = three toggleable/prioritizable icons (flame = firefight, wrench = repair, pump/drop
= pumping) plus the buoyancy % and fire/breach icons.

---

## 5. UI Text / Callouts

- **Damage feed (text log):** short, stacked, plain-language module callouts that appear on hit,
  e.g. **"Ammunition,"** **"Engine damaged," "Fuel tank," "Loader / Gunner / Driver knocked
  out," "Transmission," "Barrel."** These stack as a running list during the exchange; the fatal
  one is emphasized. (Naming per WT damage feed; the kill cam's stated purpose is to show
  "which components were damaged, which assemblies were knocked out and any injuries… against
  the crew members" — [warthunder.com/en/news/3880--en](https://warthunder.com/en/news/3880--en).)
- **Hit-marker semantics:** a **"hit"** just means a projectile landed; a **"critical hit"**
  means a component was actually damaged — the two are distinguished in the feed
  ([forum.warthunder.com/t/when-red-doesnt-mean-damaged/83667](https://forum.warthunder.com/t/when-red-doesnt-mean-damaged/83667)).
- **Color of text** follows the state law: knocked-out/destroyed items read in red; the feed
  entry color matches the module flash.
- **Placement:** damage feed stacks in a corner (bottom-left / lower-center) of the frame; the
  compartment/module status indicator (naval) sits as a silhouette panel to one side (breach
  indicator far left).

---

## 6. Named Video References (artist build sheet)

For each: title, URL, what it shows, and a frame-by-frame "visual signatures" note an artist
can build from without watching.

1. **"War Thunder — In Development: X-Ray Death Cam"** —
   [youtube.com/watch?v=togFXO-ysB8](https://www.youtube.com/watch?v=togFXO-ysB8) (Gaijin
   official, 2014). The original reveal of the death cam.
   *Visual signatures:* translucent grey ghost hull; solid grey internal modules; a bright
   tracer punching the armor with an entry flash; slow-mo through the interior; struck modules
   and crew figures flashing their damage color; camera holds broadside to the shot.

2. **"NEW Damage Animation and Kill Cam !!! War Thunder Dev Server"** —
   [youtube.com/watch?v=X2Eq3nbpUDQ](https://www.youtube.com/watch?v=X2Eq3nbpUDQ) (2022).
   Updated animation pass.
   *Visual signatures:* stronger impact beat-pause; the fragment/spall fan (thin bright rays
   fanning ~30–45° forward from the entry hole); modules going grey→yellow→red→black; crew
   figures reddening; short cinematic orbit.

3. **"(Tutorial) How to Use the New 'Protection Analysis' Armor Viewing System (Update 1.79)"** —
   [youtube.com/watch?v=ryE3jz34I3s](https://www.youtube.com/watch?v=ryE3jz34I3s).
   The interactive armor inspector.
   *Visual signatures:* free-orbit hull; aim a probe, get a drawn path; green = penetrates,
   yellow = marginal, red = stopped, grey = ricochet; armor plates tinted by protection; range
   & shell selectors; static (no slow-mo) study view.

4. **"How to use the protection analysis tool in War Thunder"** —
   [youtube.com/watch?v=c7NXyv_vD1A](https://www.youtube.com/watch?v=c7NXyv_vD1A).
   *Visual signatures:* the four-color outcome legend in action; ricochet deflection lines
   glancing off sloped plates; the path line terminating at the plate on non-pen vs continuing
   through on pen.

5. **"War Thunder Aircraft X-ray and Module Damage Guide"** —
   [dailymotion.com/video/x92ably](https://www.dailymotion.com/video/x92ably) /
   [youtube.com/watch?v=P_Dduc3Ttiw](https://www.youtube.com/watch?v=P_Dduc3Ttiw).
   Aircraft internals.
   *Visual signatures:* translucent fuselage; pilot figure, fuel tanks, engine, control rods,
   ammo belts as distinct solid modules; rounds stitching through and lighting up modules;
   fuel-tank fires.

6. **"How to see x-ray in battle — War Thunder"** —
   [youtube.com/watch?v=7R8NYg9pL0s](https://www.youtube.com/watch?v=7R8NYg9pL0s).
   The in-battle module-status view (Controls → Common → "Show status of the vehicle modules").
   *Visual signatures:* live side-panel showing your own modules in current state color; the
   same grey→yellow→orange→red→black ramp.

7. **"[Development] Naval shell chase camera"** (devblog + embedded clip) —
   [warthunder.com/en/news/7194-development-naval-shell-chase-camera-en](https://warthunder.com/en/news/7194-development-naval-shell-chase-camera-en).
   *Visual signatures:* camera pinned behind the shell; long ballistic arc over water; splash of
   the ranging salvo; hand-off toward the target ship for the impact read.

8. **"[Development] The New Damage Control Mechanic for Naval"** (devblog, "940_dc_en" UI image) —
   [warthunder.com/en/news/9795-development-the-new-damage-control-mechanic-for-naval-en](https://warthunder.com/en/news/9795-development-the-new-damage-control-mechanic-for-naval-en).
   *Visual signatures:* DC panel with the three prioritizable presets (firefight / repair /
   pump); buoyancy %; fire & breach icons; compartment silhouette coloring.

(Also useful as reference text, not video: the Steam **War Thunder Naval Guide**
[steamcommunity.com/sharedfiles/filedetails/?id=2841054332](https://steamcommunity.com/sharedfiles/filedetails/?id=2841054332)
for the exact HUD element list.)

---

## TOP-15 VISUAL SIGNATURES (ranked — what most makes it read as a WT hit cam)

1. **Translucent frosted-grey ghost hull** with the outer skin see-through and internals visible.
2. **Solid, opaque, color-coded module boxes** floating inside that shell (skin translucent, guts solid).
3. **The shell path as a single bright line** with a hot **entry flash** where it crosses the armor.
4. **Three visually distinct armor outcomes:** penetrate (green, line continues in) / stop (red, line dies at plate) / ricochet (grey, line deflects away).
5. **The fragment/spall FAN** — thin bright rays spraying ~30–45° forward from the entry hole into the interior.
6. **Slow-motion with a hard beat-pause at impact**, then the fan and module flashes play out.
7. **Damage-state color LAW: grey → yellow → orange → red → black**, where **red = crippled-but-alive, black = destroyed** (never "more red" for dead).
8. **Crew as small human figures** on a health gradient: blue/white → yellow → orange → red → hard-red knocked-out.
9. **Modules flash their new state color on the exact frame a fragment ray hits them.**
10. **Ammo & fuel intrinsically tinted warm** (yellow/orange/red) so the eye jumps to the hazards.
11. **Broadside/three-quarter cinematic framing** so entry→interior reads left-to-right, with a slight orbit.
12. **Stacking plain-language damage feed** ("Ammunition," "Engine damaged," crewman "knocked out") in a corner.
13. **Hit vs critical-hit distinction** — a landed round vs an actually-damaged component.
14. **Naval: compartment silhouette that colors up and goes black when saturated + buoyancy %** and flashing fire icon.
15. **Two modes sharing one grammar:** cinematic kill cam ("what killed me") and free-orbit Protection Analysis ("what could kill it").

---

## 2D ADAPTATION RECIPE (fake the 3D feel with primitives)

**Goal:** reproduce signatures 1–13 with 2D primitives + a light 3D fake, cheaply.

### A. Two synchronized orthographic views
Draw the vehicle as **two flat schematics that share the same X (fore-aft) axis and animation
clock**:
- **SIDE view** (top of screen): the hull as a rounded-rect **translucent shell** (fill alpha
  ~15–25%, 2px stroke). Modules as solid rounded-rects inside.
- **TOP / plan view** (below it, aligned on the same X): same hull outline from above, same
  module boxes. The projectile's lateral (Y) position lives here.
Two orthographic views together read as "3D understood" without a real 3D pipeline — a hit
that looks central in SIDE but off-axis in TOP instantly communicates a glancing entry.

### B. The projectile path
- Draw an **incoming tracer dot** animating along a straight line toward the hull on BOTH views.
- At the armor stroke, spawn an **entry burst**: a 6–10px white-hot star + expanding ring,
  hold 1 frame at full, fade over ~200 ms.
- **Outcome branch** at the armor line:
  - *Penetrate:* continue the line INTO the hull to the detonation point (green core, white
    hot head).
  - *Non-pen:* stop the line at the plate; red splash; no interior line.
  - *Ricochet:* reflect the line about the plate normal and run it back out of frame; grey/steel
    streak, no interior line.

### C. Detonation marker + fragment fan
At the interior detonation point on the SIDE view (and mirrored on TOP):
- Draw a **small filled detonation node** (bright orange, 4–6px).
- Emit **8–16 thin straight rays** (1–1.5px) within a **±22° half-angle (≈45° total)** cone
  pointing in the shell's travel direction. Ray length varies (center rays longest, edge rays
  short). Color: hot yellow core fading to transparent. Rays **clip/terminate on the first
  module box they intersect**; that box registers a hit.
- For an HE/overpressure kill, instead draw **two overlapping translucent red circles** (the
  blast spheres) centered at detonation.

### D. Module flash timing (per struck module)
On the frame a ray terminates on a module:
- **t=0:** flash the module fill to **white** (100% alpha), 1 frame.
- **t=0–120 ms:** ease from white to the module's **new state color**.
- **New state color** steps one rung down the ramp per qualifying ray:
  grey(fine) → yellow → orange → red → black.
- A tiny **impact spark** at the ray-hit point on the module edge.
- **Crew figures:** same timing but on the crew gradient (blue→yellow→orange→red→hard-red).
Global clock: run the whole sequence at **~0.15–0.25× speed**, with a **250–400 ms freeze at
the entry-flash frame** before the fan fires.

### E. Damage feed
Bottom-left, stack up to ~5 lines, newest on top, each fades after ~3 s. Text = module name +
verb ("Engine — damaged", "Ammunition — detonated", "Gunner — knocked out"). Line color = the
module's resulting state color.

### F. Naval extension
Add a **compartment silhouette strip**: the hull profile divided into fore/mid/aft cells; each
cell fills by cumulative damage (grey→yellow→orange→red→**black when saturated**). Overlay a
**buoyancy % bar** (drops on flooding; hull graphic sinks/heels as it drops), a **flashing
fire icon** on burning cells, and a **breach marker far-left**. DC action row = three icons
(flame / wrench / pump) the player can prioritize.

### G. Reconstructed palette (hex — RECONSTRUCTION, not official Gaijin values)
Gaijin does not publish hex; these are calibrated to the described color names and are safe
defaults. Tune to taste.

| Role | Hex | Notes |
|---|---|---|
| Ghost hull stroke | `#8A97A0` | cool steel-grey |
| Ghost hull fill | `#8A97A0` @ 18% alpha | frosted shell |
| Module — fine/undamaged | `#9AA6AD` | neutral steel |
| State: light damage | `#F2C744` | yellow |
| State: damaged | `#F08A24` | orange |
| State: crippled (alive) | `#E23B2E` | red |
| State: destroyed | `#1B1B1E` | near-black / charred |
| Crew healthy | `#Bcd4e6` | blue-white |
| Crew injured (mid) | `#F0A83C` | orange |
| Crew knocked out | `#D21F1F` | hard red |
| Ammo / propellant | `#F4B233` → `#E23B2E` | yellow-orange danger |
| Fuel | `#5FA05A` | olive-green block |
| Path — penetrate | `#5BE06A` core, `#FFFFFF` head | green line |
| Path — non-pen splash | `#E23B2E` | red at plate |
| Path — ricochet | `#B7C0C7` | grey deflect |
| Fragment ray | `#FFE55C` → transparent | hot yellow fan |
| Entry flash / hot head | `#FFFFFF` → `#FFD27A` | white-hot |
| HE blast spheres | `#E23B2E` @ 30% alpha | two overlapping circles |
| Naval buoyancy bar | `#3FA9F5` (full) → `#E23B2E` (low) | flooding |
| Naval permanent-flood compartment | `#2E6FB0` | "turns blue, can't drain" |

**Minimum viable to still read as WT:** translucent hull + solid state-colored module boxes +
one bright path line with an entry flash + a yellow fragment fan + slow-mo-with-impact-pause +
the grey→yellow→orange→red→black ramp + a stacking text feed. Ship those seven and it reads as
a War Thunder hit cam even in pure 2D.

---

### Source index
- Kill Camera X-ray feature: [warthunder.com/en/news/3880--en](https://warthunder.com/en/news/3880--en), [warthunder.com/en/devblog/current/651](https://warthunder.com/en/devblog/current/651)
- Damage-state colors / red≠dead: [forum.warthunder.com/t/when-red-doesnt-mean-damaged/83667](https://forum.warthunder.com/t/when-red-doesnt-mean-damaged/83667)
- Crew color gradient + module legend: [old-forum.warthunder.com X-ray damage indication colors](https://old-forum.warthunder.com/index.php?/topic/398790-x-ray-damage-indication-colors-and-the-meaning-of-them/)
- Protection Analysis colors (green/yellow/red/grey): [specailgamemoment.wordpress.com](https://specailgamemoment.wordpress.com/2018/09/15/protection-analysis-eng/), [warthunder.com/en/news/5569](https://warthunder.com/en/news/5569-development-protection-analysis-en)
- Fragment cone 30–45° + blast spheres: [wiki.warthunder.com HE & overpressure](https://wiki.warthunder.com/mechanics/4236-the-mechanics-of-high-explosive-effect-and-overpressure), [warthunder.com/en/news/8670 spall liners](https://warthunder.com/en/news/8670-development-detailed-information-surrounding-spall-liners-in-war-thunder-en)
- Naval crew/compartments + crew-density overlay: [wiki.warthunder.com/640-ship-crew-mechanics](https://wiki.warthunder.com/640-ship-crew-mechanics)
- Naval HUD (buoyancy %, fire siren, black compartments, breach): [steamcommunity.com Naval Guide](https://steamcommunity.com/sharedfiles/filedetails/?id=2841054332)
- Naval damage control presets: [warthunder.com/en/news/9795](https://warthunder.com/en/news/9795-development-the-new-damage-control-mechanic-for-naval-en)
- Shell chase camera: [warthunder.com/en/news/7194](https://warthunder.com/en/news/7194-development-naval-shell-chase-camera-en)
- Videos: [togFXO-ysB8](https://www.youtube.com/watch?v=togFXO-ysB8), [X2Eq3nbpUDQ](https://www.youtube.com/watch?v=X2Eq3nbpUDQ), [ryE3jz34I3s](https://www.youtube.com/watch?v=ryE3jz34I3s), [c7NXyv_vD1A](https://www.youtube.com/watch?v=c7NXyv_vD1A), [P_Dduc3Ttiw](https://www.youtube.com/watch?v=P_Dduc3Ttiw), [7R8NYg9pL0s](https://www.youtube.com/watch?v=7R8NYg9pL0s)
</content>
</invoke>
