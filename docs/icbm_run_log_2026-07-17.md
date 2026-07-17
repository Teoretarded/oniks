# ICBM strike in cinematic mode — run log (2026-07-17)

User brief (voice): the top Russian + top American ICBM in the F3
cinematic mode, researched to be as real as possible (silos, guidance,
launch), silo models in both maps, select-a-point + L targeting with a
watch-it-fly camera, "entire rocket ship launching" scale. Ordering:
research/missiles/models -> functional targeting -> the beautiful
targeting MENU last -> map/LiDAR expansion PARKED until the user says.

Plan + spec: docs/plans/icbm_cinematic_plan_2026-07-17.md.
Research: docs/research/icbm_reference_2026-07-17.md (normative).

## What shipped (commits f7f4b98..6ab50d1)

- **Weapons**: LGM-30G Minuteman III (hot launch, 36 t pencil) and
  RS-28 Sarmat (cold mortar launch, 208 t monster) — full stage tables
  from the research doc; `~` marks estimates.
- **Physics** (`game/cinematic_icbm.py`, GL-free, zero RNG): uniform-
  gravity Lambert in time-of-arrival form (v_req = D/tau + g*tau/2) +
  GEMS arccos energy management (US 4,387,865 / 10,323,907). Solids
  burn all three stages to depletion on the real 61/65/61 s schedule
  and corkscrew off the excess; Sarmat's PBV cuts off at Vg~0
  ("cutoff" event); PBV trims residuals at real RS-14-class Isp.
  8.5 km map shot lands < 1 m from the designated point; apex ~42 km;
  flight ~5.7 min (warp compresses the coast).
  - Measured-and-fixed #1: counting the bus inside GEMS capability C
    left |Vg| = 156 m/s at burnout (15 km miss). C counts BOOST stages
    only; the bus is the trim reserve.
  - Measured-and-fixed #2: slew-limiting the THRUST vector leaked 2.5%
    average alignment = 180 m/s residual. Thrust follows the law
    exactly; the slew limit applies to the drawn attitude only.
- **Models** (`models/icbm.py`): both missiles (signature checklists
  1.6/2.6), Minuteman LF (gravel lot, apron, 3.66 m mouth ring, 110 t
  door on rails as a separate animated mesh, hatch/antennas/fence) and
  15P718M-class Sarmat silo (concrete mesa, TPK rim in the mouth,
  massive round lid). Silo survey (`world/cinematic_scene.py`):
  deterministic flat/clear/LOS/valley-band ranking — Lauterbrunnen
  site 1800 m from spawn, Yosemite 1776 m.
- **Integration** (`game/cinematic.py`): LAUNCHER section in the
  director; T designates the ground point under the view ray (walk +
  freecam); L fires (one bird per silo); C chase cam; '.' time warp
  1x/8x/30x during ICBM flight only; silo compound + animated door
  drawn at the surveyed site; new event kinds door/eject/pallet/
  smoke_ring/stage/cutoff/impact with sounds, shake and toasts.
  S-300 salvo behavior untouched.
- **FX**: fire-in-the-hole annulus geyser + smoke-ring emitter + dense
  white pillar + vacuum bloom above 9 km + staging puffs + reentry
  streak + RV impact blast (MM III); lid slide + huge dark mortar puff
  + unlit 35 m hang + pallet kick + hypergolic flash + thin brown haze
  (Sarmat).

## Tests

tests/test_cinematic_icbm.py (10, plan contracts verbatim),
tests/test_icbm_models.py (6), 5 integration tests appended to
tests/test_cinematic.py (fire flow, warp gating, launcher rows, T
designation, full flight through state events to impact < 150 m).

## Visual audit (3 rounds, shots 25-35 + tools/probe_silo_render.py)

- R1: chase cam blinded by a 2x-body-length glow sprite; ground shots
  from spawn useless (moraine + sub-pixel fence). Fixed glow to
  flame-length scale, chase to 7x length.
- R2: compound confirmed rendering (40 m probe: apron/door/collar/
  fence all read); bare meadow inside the fence read wrong -> gravel
  lot pads.
- R3 keepers: shot 28 (MM III climbing out of its own pillar over the
  readable compound) and shot 33 (the Sarmat mortar hang — 35 m of
  dark airframe standing on nothing). Fire-in-the-hole doubled into a
  geyser after reading as a sparkle.

## Known cosmetic nits (honest list, non-blocking)

- The smoke ring reads as the column base, not yet a distinct drifting
  halo — needs a dedicated fx-art pass.
- Chase cam still glow-heavy when dead astern of the flame.
- Spent stages vanish at separation (puff only, no tumbling castoff
  meshes); post-boost the bus is not drawn (metres long, tens of km
  up).
- Impact is a conventional-scale blast — the nuclear question is the
  plan's open question #1 for the user.

## Map expansion (same day — USER GO, "extend by 80-150 km")

Shipped: 160 x 160 km world. fetch_cinematic_ring.py (7,601 files:
3,796 km2 swissALTI3D 2 m + 3,796 SWISSIMAGE 2 m + 9 GLO-30 tiles,
~4 GB, parallel/resumable) -> bake_cinematic_ring.py (surround2: 16 km
chunks / 64 m cells / 8 m-per-px ortho; surround3: 40 km chunks /
250 m GLO-30 / baked altitude+slope alpine tint) -> CinematicScene
ring physics chain + renderer consumes all rings (per-rec cell) +
220 km designation ray. Verified: ext ±80 km; ASL spot checks right
(Rhone floor 657 m at 70 km W); walkable at 25 km; **60 km Minuteman
shot lands 60 m from the point (t=341.5 s)** — same TOA/GEMS core,
zero physics changes. Probe: tools/probe_expansion.py, shots 40-45.

Defects found by eye in round 1 (fix = fill ring2 holes from the
GLO-30 mosaic + alpine tint instead of column-means/zero-RGB):
- black wedge artifact at one ridge in shot 43 (DEM hole fill)
- grey zero-ortho patches mid-ground in shot 44 (missing/border tiles)
Also: far-ring green tint reads too saturated without haze; far rings
skip baked terrain shadows (haze-dominated; logged).

## Overnight autonomous run (2026-07-17 night, second session)

User abandoned the first session, ordered: fix the flight computer,
universal T-targeting incl. S-300 ("fastest route, account for drag"),
more big ammunition, terrain deformation, the M globe. Six commits:

1. **Flight computer** (88115aa): GEMS burn-to-depletion RETIRED at
   map scale — measured 28-30 km cross-track on an 8 km Sarmat shot
   (= the user's "flies off into the distance"). New law: fastest
   feasible tau by a forward twin of the law itself, thrust dead along
   Vg, THRUST TERMINATION at Vg~0 (real Minuteman I/II vent-port
   mechanism), 30 deg terminal dive floor + 800 m terrain clearance.
   After: miss 17-126 m, tof 76-142 s (was 278-550), cross-track 0.
   Long shots still stage naturally (700 km: 233 s, 100 m off).
2. **Universal T-targeting** (f87b17d): GuidedLaunch — piecewise
   drag-aware Lambert with terrain GATES + bit-exact verification (the
   plan is flown on the real step() before launch). 16/16 dead hits
   across all four pad rounds, 5-45 km. Known: L-press plans up to
   ~1.9 s synchronously (worker thread = polish item).
3. **Terrain deformation** (craters): bowl+lip delta on ground_h
   (physics = renderer = same math), dirty-tile remesh + async ash
   scorch, Glasstone sizing. IcbmSpec.yield_kt (MM3 300 kt W87).
4. **Ammo expansion**: Trident II D5 from REAL water (survey found the
   Thunersee at 557.6 m ASL; broach + water column + spray), MIRV
   (Sarmat 10x500 kt, Trident 8x475 kt; one RV per T-mark, impacts
   walk 1.3-26 m off their marks), Iskander-M pad round (30 km < 90 s).
5. **M orbit view**: true-scale Blue Marble Earth UNDER the scene
   (surface = sea level, anchor = real LV95->WGS84 lat/lon), one
   continuous camera ride valley->LEO->full planet, drag/wheel/T-from-
   orbit, engine FAR 900 km -> 30,000 km. Probe frames 50-56.
6. **Nuclear impact timeline** (NuclearBurst): flash/fireball/stem/
   cap/ground-ring on the Glasstone clock, yield-scaled, per-RV.
   Probe frames 60-65; round-2 cap/stem tune from my own audit.

Full-suite verdict (end of the overnight run): 8 red, ALL verified
pre-existing — test_swarm saturation, test_launch_kinematics
[kh31p/pantsir_57e6/sm6/swarm/zircon], test_phase5b_e2e harm-mission +
ir-drone-hunt. Re-ran a sample covering all three files in a worktree
at 33f139e (the commit BEFORE this run): identical failures. Every
suite the overnight work touched (cinematic, icbm, guided, ammo,
craters, globe, nuclear burst — 100+ tests) is green. The 8 combat
reds need their own triage session ([[overnight-run-2026-07-17]]
already flagged pre-existing reds for user judgment).

Honest remaining for the next session:
- 60 fps x 15 s captures per weapon vs real footage values (user's
  explicit ask — structural work landed, the art loop needs eyes).
- Launch-FX eyeball passes: Trident broach, Iskander column, MIRV sep.
- GuidedLaunch route planning off the L-press thread.
- Globe nits: terrain patch brighter than Blue Marble + hard patch
  edge from orbit; cap top edge still shows discrete puffs.
- Targeting MENU (user: LAST, high design) still not started.

## Next (user-gated)

1. User playtest of the whole flow ([[playtest-before-polish]]).
2. The bespoke high-design targeting menu (user: LAST, must not look
   generic).
