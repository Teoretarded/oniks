# Walk-mode MANPADS — design (2026-07-16)

The cinematic walkabout gains shoulder-fired weapons: press **F1** for a
weapons locker UI, shoulder a researched MANPADS (Igla-S / Stinger /
Piorun / Starstreak), **right-click** to raise the sight, **middle-click**
to designate a target (a flying S-300 round or any ground point), and
**left-click** to fire. Hit or miss emerges from real physics — PN
guidance whose lateral authority is capped by dynamic pressure and the
airframe's structural limit, a seeker with a finite gimbal, FOV and
tracking rate, and a proximity/impact fuse measured on the actual
trajectory. No dice anywhere ([[physics-not-dice]]).

Specs and sources: `docs/research/manpads_reference.md`.

## Constraints

- Another session is concurrently working on cinematic maps + wind. ALL
  new behaviour lives in NEW files; `game/cinematic.py` gets a handful of
  one-line delegation hooks, added in one short read→edit→commit burst.
- GL-free sim + models (headless unit tests), same as walker/missiles.
- Zero RNG in gameplay physics; cosmetic particle jitter uses the
  Effects pool rng only (rendering, never guidance).

## Files

- `sim/manpads.py` — GL-free. `ManpadsSpec` (frozen dataclass, 4 entries
  in `WEAPONS`), `SeekerState` machine, `ManpadsRound` (thrust phases,
  Mach-dependent drag, gravity, PN with fin-authority cap, fuse,
  Starstreak dart separation). Steps against callables:
  `target_pos()/target_vel()` or a fixed ground point, plus `ground_h`
  for terrain impact + LOS occlusion checks.
- `models/manpads_model.py` — `build_launcher(spec_id)` (first-person
  tube: gripstock, BCU, IFF grid / aiming unit per weapon) and
  `build_missile(spec_id)` (+ dart for Starstreak), MeshBuilder based,
  dimensions from the research table.
- `game/cinematic_weapons.py` — `WeaponRig`: the F1 locker UI (glass /
  hairline / cyan palette shared with the director), shouldered view
  model, ADS zoom, MMB designation (airborne rounds by angular pick,
  else DTM ray-march ground point), fire sequence with backblast,
  per-meter corkscrew trail emission, impact/kill fx, HUD (reticle,
  seeker circle, TONE/LOCK, range, tube status). Talks to the state via
  a narrow contract (see hooks).
- `tests/test_manpads.py` + model checks in the same file.

## Hooks in game/cinematic.py (the ONLY edits there)

1. import + `self.weapons = WeaponRig(...)` in `_enter`.
2. `handle_event`: `if self.weapons.handle_event(ev, self): return`
   placed after the ESC/director handling (F1 toggle, RMB/MMB/LMB,
   locker clicks when open; returns True when consumed). ESC closes the
   locker first — folded into the existing ESC ladder.
3. `sim_step`: `self.weapons.update(dt, self)` (reads `self.launches`
   as the live target list, queues sounds through the state's
   `_queue_sound`, emits into `self.effects` pools).
4. `render`: `self.weapons.draw_world(...)` after the S-300 rounds;
   `_draw_hud`: `drew |= self.weapons.draw_hud(...)`.
5. FOV: `_fov()` returns the rig's ADS FOV when sighted (rig wins over
   binoculars; wheel-binos only work with the weapon lowered).

## Fire-control loop (player-facing)

CAGED (reticle) → MMB: designate → TONE (growing bracket + audio-less
pulse bar; IR needs the target inside the acquisition cone and range,
Starstreak designates anything on the crosshair including terrain) →
LMB: eject, motor light at the researched standoff, PN flight → impact/
prox kill (fireball + debris + delayed boom) or miss → self-destruct
puff. Reload ~4 s ("NEW TUBE"). Backblast cone behind the gunner on
launch (dust + pale smoke, camera thump).

IR seekers may lock ground points at reduced acquisition range (hot
spots — documented behaviour); Starstreak beam-rides to any held point.

## Testing contract (all deterministic, headless)

boost/burnout speed windows per weapon; coast drag decay; unpowered
gravity drop; realized lateral g never exceeds struct limit; low-q fin
starvation right off the tube; PN kills a crossing S-300-profile target;
Starstreak hits a 3 km ground point ≤ 2 m; gimbal-rate break → ballistic;
terrain occlusion breaks lock; segment-based prox fuse catches a
crossing target between steps; self-destruct at life end; two identical
runs bit-identical; models: vertex counts, lengths within 2% of spec,
distinct per weapon.
