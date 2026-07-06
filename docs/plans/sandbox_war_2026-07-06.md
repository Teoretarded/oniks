# SANDBOX WAR — port COMBAT mechanics into SANDBOX + red-force director

Date: 2026-07-06.  Branch: feat/combat-expansion.
User directive (verbatim intent): sandbox must stay a sandbox — **no EMCON /
fog-of-war on the player picture** — but every combat toy (enemy warships,
subs, planes, their missiles) must exist in it, plus a **map-screen director
menu** (same access pattern as J/forensics) that can **force enemy ships /
planes / subs to launch at specific map points** or **flip them to
auto-engage** the player and player missiles.
Scope answers (asked + answered 2026-07-06): **full toybox spawned by
default**; **passive until ordered** (they sail/fly their patterns but never
shoot until auto-engage or a director order).

## Design in one paragraph

The new sandbox is a *subclass of the combat stack*, not a rewrite:
`SandboxWorld(CombatWorld)` re-adds civilian traffic + patrol aircraft,
swaps the radar-gated ContactBoard for the legacy all-seeing board
(`visible_fn=None`), never latches victory/defeat, and holds all enemy
weapons employment behind a new `enemy_weapons_free` flag (default **True**
on CombatWorld so every existing combat battle is byte-identical; **False**
on SandboxWorld).  `SandboxWarState(CombatState)` wires it to the menu
SANDBOX button, so all combat rendering (destroyer/carrier/fighter/AWACS/
airfield/drone meshes), the drone platform, forensics (J), the battery
panel, Buk/swarm platforms and the black-box ledger come along for free.
The DIRECTOR is a map overlay (new keybind `I`) whose sim half lives
GL-free on `SandboxWorld`.

## LOCKED CONVENTIONS

1. **New files**: `world/sandbox_world.py` (class `SandboxWorld(CombatWorld)`
   + module constant `SANDBOX_CONFIG`), `game/sandbox_war.py` (class
   `SandboxWarState(CombatState)`), `game/director.py` (map overlay; pure
   selection/order model separated from draw so it unit-tests headless),
   `tests/test_sandbox_world.py`, `tests/test_director.py`.
2. **No renames, no moves**: `SandboxState`, `CombatState`, `WorldState`,
   `CombatWorld` keep their names, modules and public APIs.  The menu label
   stays `SANDBOX`; only `App.start_sandbox` changes its constructed class.
3. **The flag**: `self.enemy_weapons_free: bool = True` set in
   `CombatWorld.__init__`.  `SandboxWorld.__init__` sets it False after
   super().  Exactly these employment sites gate on it — nothing else:
   - `CombatWorld.step`: `self.defense.step(self, dt)` and
     `self.strikes.step(self, dt)` (world/combat.py ~3928/3932).
   - `CombatWorld._step_commander`: ONLY the brain
     (`for order in self.commander.step(...)`) is gated.  The picture feed
     `_feed_enemy_picture`, the weapon-release pump
     `_release_fighter_weapons`, and mission bookkeeping
     `_update_commander_missions` run UNCONDITIONALLY (the pump only serves
     fighters that already hold orders — in combat that is identical
     behavior; in the sandbox it is what makes director-ordered strikes
     release their rounds).
   - `CombatWorld._step_subs`: the fire-intent consumption
     (`if aim is not None: self._fire_kalibr_salvo(sub, aim)` at ~1574)
     becomes `if aim is not None and self.enemy_weapons_free:`.
   Everything else keeps running in passive mode BY DESIGN: CAP rotation
   (`_commander_cap`), RWR evasion (`_assign_air_threats`), rearm queues,
   sub movement, acoustic/recon/ELINT/CBR sensors, and the player-side
   `pantsir_defense` (it is the player's shield, never gated).
4. **All-seeing picture**: `SandboxWorld._build_contacts` builds the SAME
   radar infrastructure as combat (player_radars, radar_station, radar_net
   — enemy ESM/ARM/EW paths need them) but returns
   `ContactBoard((BASE_POS[0], BASE_POS[2]))` with **no visible_fn**
   (sim/contacts.py:144 — None = legacy all-seeing).  Map fog latches are
   forced open: `airfield_known` True, `_enemy_radar_known` = all ids,
   carrier-known latch True (find the exact attrs in _update_airfield_intel
   / known_enemy_sites and force them in `SandboxWorld.__init__`).
5. **No session end**: `SandboxWorld.defeated` -> False,
   `SandboxWorld.victorious` -> False (property overrides; structures still
   take damage and die — only the latch is disabled).  `defeat_cause`
   returns None.
6. **SANDBOX_CONFIG** (module constant in world/sandbox_world.py): built
   from the default CombatConfig via dataclasses.replace with a full
   toybox: >=2 destroyers, 1 flagship, 1 aaw, 1 ground_attack, 1 transport,
   >=1 sub with kalibr ammo, 1 awacs, 1 jammer, n_pantsir>=2, n_buk=1,
   n_cbr=1, n_swarm_pods=1, n_enemy_radars>=2, drone on, and GENEROUS
   finite ammo (order 20-99 per pool, generous sub/destroyer strike
   magazines) with short magazine reload timers.  Seed fixed (e.g. 7).
   Values must pass `clamp_config` unchanged — if a clamp caps a wish,
   take the clamp's max rather than bypassing it.
7. **Civilian traffic**: `SandboxWorld._spawn_ships` = super() fleet +
   legacy lane traffic from world/generation.SHIP_SPAWNS (same classes the
   old sandbox used).  `_spawn_aircraft` returns the legacy patrol
   aircraft.  `_spawn_sites` = combat sites + legacy scenery sites
   EXCLUDING any legacy 'radar' kind pin (real enemy radars exist now).
   Civilian hulls are Ship (not Destroyer) so every combat roster filter
   (defense/strikes/ELINT) ignores them by existing isinstance checks —
   verify, don't assume.
8. **Director sim API** (GL-free, on SandboxWorld):
   - `director_units() -> list[dict]`: one dict per orderable unit:
     `{"uid", "kind" in ("destroyer","carrier","sub","fighters","awacs"),
       "label", "pos"(np (3,)), "alive", "weapon", "ammo", "ready"(bool),
       "detail"(str)}`.  Fighters are ONE aggregate row (the flight line),
     not per-airframe.
   - `director_order(uid, target_xz) -> (bool, str)`: routes by kind —
     destroyer -> Tomahawk salvo at point (reuse the _fire_tomahawk_salvo
     order path, aim refined by _refine_strike_aim), sub -> immediate
     Kalibr salvo at point (`_fire_kalibr_salvo`), fighters -> JASSM
     package at point via `_execute_commander_order` (auto-pick 2 parked
     fighters; msg says why when <2 available).  Returns a short HUD-ready
     message either way ("TOMAHAWK SALVO AWAY - DESTROYER 01" /
     "NO PARKED FIGHTERS").
   - `director_sead() -> (bool, str)`: HARM package at the player radar
     station (the point-free SEAD row).
   - `set_weapons_free(on: bool)` + property `enemy_weapons_free`.
   - Director orders WORK while passive (that is the whole point) and
     spend real magazine ammo.  No new RNG streams; reuse existing paths.
9. **Keybind**: `ActionDef("director", "RED-FORCE DIRECTOR (MAP)",
   "ENGAGEMENT", pygame.K_i)` in game/keybinds.py (I is unclaimed).
   Routed in game/controls.py like forensics: `sandbox.toggle_director()`.
   Base `SandboxState.toggle_director` = graceful hint no-op ("DIRECTOR:
   WAR SANDBOX ONLY"); `CombatState` inherits that no-op; the real toggle
   lives on `SandboxWarState`.  Director opens ONLY while the tactical map
   is open (pressing I without the map open flashes "DIRECTOR: OPEN MAP
   (M) FIRST").
10. **Test purity**: `world/sandbox_world.py` and the director model stay
    importable headless (no OpenGL; pygame key constants only where
    already conventional).  `game/sandbox_war.py` is GL-touching and is
    NEVER imported by unit tests.
11. **No test weakening — ever.**  Existing suite runs untouched.  A task
    that cannot make a planned test pass reports BLOCKED with the failure
    pasted; it does not widen tolerances, delete cases, or mark xfail.
12. **Commits**: conventional messages per task
    (`feat(sandbox): ...` / `feat(director): ...` / `test(...): ...`),
    ending with the Claude Fable co-author line.

## Environment facts (for every agent)

- Windows 11, PowerShell primary; repo root:
  `C:\Users\teoti\OneDrive\Desktop\New folder\oinks PROTO` (note the space
  — quote paths).
- Run tests: `python -m pytest -q -n auto` (~1300 tests, xdist installed;
  NEVER run the full suite serial).  Targeted:
  `python -m pytest tests/test_sandbox_world.py -q`.
- Unit tests are headless: they may import world/ and sim/ but never the
  GL-touching game modules (game/sandbox.py, game/combat.py,
  game/sandbox_war.py).  Pure-logic game modules (keybinds, scoring,
  salvo, forensics-pure parts) are fair game — follow existing patterns.
- Scenario helpers: world/scenario.py (forge) + existing e2e tests
  (tests/test_phase5b_e2e.py, tests/test_asbm.py, tests/test_buk_ui.py)
  show how to build worlds/configs and step them; copy their setup
  patterns instead of inventing new ones.
- Determinism: no Date-like entropy, no new unseeded RNG anywhere in sim/
  world code.

## Tasks

### A1 (world layer): flag + guards + SandboxWorld + tests
Files: world/combat.py (guards only, per LOCKED #3), world/sandbox_world.py
(new), tests/test_sandbox_world.py (new).
Deliverables: SANDBOX_CONFIG; SandboxWorld with toybox roster, all-seeing
board, forced-open map latches, no-latch defeated/victorious, passive
default; CombatWorld byte-identical with the flag True.
Test contract (assertion semantics LOCKED; setup may reuse existing
helpers/forge; constants imported, not re-typed):

```python
def test_combat_default_weapons_free():
    w = CombatWorld()
    assert w.enemy_weapons_free is True

def test_sandbox_toybox_roster():
    w = SandboxWorld()
    kinds = {type(s).__name__ for s in w.ships}
    assert {"Carrier"} <= kinds
    assert sum(isinstance(s, Destroyer) for s in w.ships) >= 3  # incl. carrier subclass
    assert len(w.subs) >= 1 and w.subs[0].kalibr_ammo > 0
    assert any(not isinstance(s, Destroyer) for s in w.ships)   # civilian traffic
    assert len(w.aircraft) >= 1                                  # patrol aircraft
    assert sum(isinstance(e, Fighter) for e in w.enemy_air) >= 2
    assert w.enemy_weapons_free is False

def test_sandbox_board_is_all_seeing():
    w = SandboxWorld()
    assert w.contacts.visible_fn is None
    for _ in range(int(20.0 / DT) )
        w.step(DT)
    ship_ids = {s.ship_id for s in w.ships if s.alive}
    assert ship_ids <= set(w.contacts.tracks.keys())   # every live hull tracked

def test_sandbox_passive_never_fires():
    # Radar emitting + player round flying at the fleet for 3 sim minutes:
    # passive world must spawn ZERO hostile rounds and spend ZERO enemy ammo.
    w = SandboxWorld()
    <launch one Oniks at the nearest destroyer using the established
     launch(...) pattern from the e2e tests>
    for _ in range(int(180.0 / DT)):
        w.step(DT)
    assert not any(getattr(m, "is_hostile", False) for m in w.missiles)

def test_sandbox_weapons_free_defends():
    # Same scenario with enemy_weapons_free True: a hostile interceptor
    # (SamMissile, is_hostile) must appear before the Oniks arrives.
    ...
    assert any(isinstance(m, SamMissile) and getattr(m, "is_hostile", False)
               for m in seen_rounds)

def test_sandbox_no_end_latch():
    w = SandboxWorld()
    for s in w.structures: s.alive = False   # or the structure kill API
    <step once>
    assert w.defeated is False and w.victorious is False
```

### A2 (game layer): SandboxWarState + menu wiring + director stub keybind
Files: game/sandbox_war.py (new), main.py (`start_sandbox` builds it),
game/keybinds.py (ActionDef), game/controls.py (route),
game/sandbox.py (base `toggle_director` hint no-op only).
Deliverables: menu SANDBOX launches the war sandbox; all combat meshes AND
civilian/patrol meshes render (verify _ship_meshes/_site_draws routing
covers the union — the state may need to merge both builders); TAB cycle =
combat_platforms(world); forensics J works; end overlay can never latch;
smoke screenshot tool run + PNGs reviewed.
No new unit tests (GL layer) — verification is the smoke run + screenshots.

### B (world layer): director API on SandboxWorld + tests
Files: world/sandbox_world.py, tests/test_sandbox_world.py (extend).
Test contract (semantics LOCKED):

```python
def test_director_units_inventory():
    w = SandboxWorld()
    kinds = {u["kind"] for u in w.director_units()}
    assert {"destroyer", "sub", "fighters"} <= kinds

def test_director_tomahawk_at_point_while_passive():
    w = SandboxWorld()
    uid = <first destroyer uid>; tx, tz = <a point ~30 km off the base>
    before = <that destroyer>.tomahawk_ammo
    ok, msg = w.director_order(uid, (tx, tz))
    assert ok
    round_ = <newest StrikeMissile in w.missiles>
    assert round_.is_hostile
    assert np.hypot(round_.target_xz[0]-tx, round_.target_xz[1]-tz) < 2_000.0
    assert <that destroyer>.tomahawk_ammo < before

def test_director_kalibr_at_point_while_passive():
    # sub fires immediately regardless of its state machine; ammo spent
    ...

def test_director_jassm_package_releases_while_passive():
    # order fighters at a point; step long enough for takeoff+transit+release;
    # assert >=1 hostile StrikeMissile appears with target within 2 km of the
    # order point (or of the refined structure aim) WITHOUT weapons_free.
    ...

def test_director_order_dead_unit_refused():
    # kill the unit first; (ok False, msg non-empty), no round spawned.
    ...
```

### C (game layer): director map overlay
Files: game/director.py (new; pure model + draw split), game/sandbox_war.py
(toggle + event routing + draw call), game/tactical_map.py ONLY if a hook
is strictly needed, tests/test_director.py (pure model only).
Behavior: with the map open, I toggles the DIRECTOR side panel (Wardroom
Dusk styling, same family as the battery panel/forensics rail).  Panel
rows: AUTO-ENGAGE ON/OFF (global) at top, then one row per director unit
(label, weapon, ammo, READY/DEAD).  UP/DOWN select, ENTER arms TARGET MODE
("CLICK MAP TO LAUNCH" armed hint), next LMB on the map converts through
the map's screen->world transform to a world point and issues
director_order; the (ok,msg) result flashes as the standard HUD hint.
SEAD row is ENTER-only (no click).  ESC or I closes.  While the panel is
open the map's normal click-to-target is suppressed (restored on close).
Sub/enemy markers: while the panel is open, draw truth markers for
director units on the map (subs included — the all-seeing sandbox may
show its own toys).
Pure-model test contract (semantics LOCKED):

```python
def test_model_select_and_arm():   # up/down wraps, enter arms target mode
def test_model_click_issues_order_and_disarms()
def test_model_autoengage_row_toggles_world_flag()
def test_model_dead_units_not_selectable()
```

### D: full-suite green + visual satisfaction loop
- `python -m pytest -q -n auto` full suite green.
- Smoke run of the war sandbox (headless screenshot tool or hidden-window
  App) covering: fleet visible from base, map with director panel open,
  a director-ordered Tomahawk in flight, auto-engage SM-2 plume.
- Orchestrator personally reviews every PNG and writes the honest critique
  + run log at docs/sandbox_war_run_log_2026-07-06.md.
- Exit only when tests + screenshots pass in the same iteration.

## Review protocol (every task)

Implementer -> spec reviewer (re-reads this plan section + the diff, re-runs
the tests, trusts nothing) -> quality reviewer (hot-path discipline, named
constants, no dead code, no tautological tests) -> fixer if needed, max 3
rounds then HALT to orchestrator.  Status protocol: DONE /
DONE_WITH_CONCERNS / BLOCKED / NEEDS_CONTEXT — bad work is worse than no
work; escalate instead of guessing.
