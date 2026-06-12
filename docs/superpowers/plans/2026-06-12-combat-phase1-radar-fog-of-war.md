# COMBAT Phase 1: Radar Network + Fog of War — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new COMBAT menu mode whose world has no sandbox traffic and a radar-gated (fog-of-war) contact picture fed by a new player ground radar station — the foundation every later combat phase builds on.

**Architecture:** A new GL-free `sim/radar.py` (radar horizon + terrain line-of-sight + `RadarNetwork`) gates the existing `ContactBoard` through an optional `visible_fn` (None = legacy all-seeing sandbox behavior, so SANDBOX is untouched). `WorldState` gains overridable spawn hooks; `CombatWorld` overrides them (empty traffic, friendly radar site, gated board). `CombatState` subclasses `SandboxState` swapping only the world; menu gains a COMBAT item.

**Tech Stack:** Python 3.11+, numpy (sim is GL-free — LOCKED test convention), pytest, pygame-ce/PyOpenGL on the render side only.

**Spec:** `docs/superpowers/specs/2026-06-12-combat-mode-design.md` (§3 radar network, §4.1 ground radar station, §8 phase 1).

**Run tests with:** `python -m pytest tests/ -q` (from the repo root).

---

## File map

| File | Action | Responsibility |
|---|---|---|
| `sim/radar.py` | Create | Horizon/LOS math, `Radar`, `RadarNetwork` |
| `tests/test_radar.py` | Create | Unit tests for the above |
| `sim/contacts.py` | Modify | Optional `visible_fn` gating on `ContactBoard` |
| `tests/test_contacts_gating.py` | Create | Gating behavior tests |
| `world/world.py` | Modify | Extract `_spawn_ships/_spawn_aircraft/_spawn_sites/_build_contacts` hooks |
| `world/combat.py` | Create | `CombatWorld` + player radar site constants |
| `tests/test_combat_world.py` | Create | CombatWorld invariants |
| `game/tactical_map.py` | Modify | `_sites` draws `world.sites` (not the global `SITES`) |
| `game/sandbox.py` | Modify | `_build_world()` hook |
| `game/combat.py` | Create | `CombatState` |
| `game/states.py` | Modify | COMBAT menu item |
| `main.py` | Modify | `App.start_combat()` |
| `tests/test_states.py` | Modify | New menu expectations |

---

### Task 1: `sim/radar.py` — horizon + terrain LOS helpers

**Files:**
- Create: `sim/radar.py`
- Create: `tests/test_radar.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_radar.py`:

```python
"""sim/radar.py: horizon math, terrain LOS, Radar.detects, RadarNetwork."""

import pytest

from sim.radar import (HORIZON_K, Radar, RadarNetwork, radar_horizon_m,
                       terrain_blocks)


def FLAT(x, z):
    return 0.0


def test_horizon_formula_matches_constant():
    assert radar_horizon_m(100.0, 0.0) == pytest.approx(HORIZON_K * 10.0)
    assert radar_horizon_m(100.0, 10_000.0) == pytest.approx(HORIZON_K * 110.0)
    assert radar_horizon_m(0.0, 0.0) == 0.0
    assert radar_horizon_m(-5.0, 0.0) == 0.0          # clamps, never NaN


def test_terrain_blocks_flat_hill_and_low_hill():
    a, b = (0.0, 120.0, 0.0), (100_000.0, 8_000.0, 0.0)
    assert not terrain_blocks(a, b, height_fn=FLAT)
    # 5 km wall mid-path rises above the climbing sight line: blocked
    hill = lambda x, z: 5_000.0 if 40_000.0 < x < 60_000.0 else 0.0
    assert terrain_blocks(a, b, height_fn=hill)
    # 500 m bump stays below the sight line: clear
    low = lambda x, z: 500.0 if 40_000.0 < x < 60_000.0 else 0.0
    assert not terrain_blocks(a, b, height_fn=low)


def test_terrain_blocks_short_path_never_self_blocks():
    # under 2 sample steps -> no interior samples -> never blocked
    assert not terrain_blocks((0.0, 10.0, 0.0), (1_000.0, 10.0, 0.0),
                              height_fn=lambda x, z: 9_999.0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_radar.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sim.radar'`

- [ ] **Step 3: Write the implementation**

Create `sim/radar.py`:

```python
"""Functional radar model (pure numpy, GL-free) — COMBAT fog of war.

A Radar detects a target when ALL of:
  * the radar is alive and emitting,
  * ground range <= its max range for the target's size class
    ("ship" / "fighter" / "missile" / "stealth"),
  * the target is above the radar horizon (earth curvature),
  * terrain does not block the straight sight line.

RadarNetwork is one side's datalink: a target is visible to the side when
ANY of its radars detects it — destroying a radar instantly removes its
coverage. ``RadarNetwork.visible`` is the ``ContactBoard`` gate
(sim/contacts.py). No beam scanning / RCS math (spec §3: functional model).
"""

from __future__ import annotations

import math

import numpy as np

from world.generation import terrain_height_scalar

HORIZON_K = 4_120.0     # m per sqrt(m): d = K*(sqrt(h_radar) + sqrt(h_tgt))
LOS_STEP_M = 2_000.0    # terrain sight-line sample spacing


def radar_horizon_m(h_radar_m: float, h_target_m: float) -> float:
    """4/3-earth radar horizon (meters) between two altitudes (meters ASL)."""
    return HORIZON_K * (math.sqrt(max(h_radar_m, 0.0))
                        + math.sqrt(max(h_target_m, 0.0)))


def terrain_blocks(a, b, height_fn=terrain_height_scalar) -> bool:
    """True when terrain rises above the straight sight line a -> b (both
    (x, y, z) meters). Samples every LOS_STEP_M, endpoints excluded so a
    radar can never block itself with its own hilltop."""
    ax, ay, az = float(a[0]), float(a[1]), float(a[2])
    bx, by, bz = float(b[0]), float(b[1]), float(b[2])
    n = int(math.hypot(bx - ax, bz - az) // LOS_STEP_M)
    for i in range(1, n):
        t = i / n
        if height_fn(ax + (bx - ax) * t, az + (bz - az) * t) \
                > ay + (by - ay) * t:
            return True
    return False


class Radar:
    """One radar: site position (x, y_ground, z) float64, antenna height
    above the site, max detection range per size class. ``alive`` clears on
    destruction (Phase 3 wires HP); ``emitting`` is the radar-silence switch
    (a silent radar sees nothing — and can't be passively located later)."""

    def __init__(self, radar_id: str, pos, antenna_m: float, ranges: dict):
        self.radar_id = radar_id
        self.pos = np.asarray(pos, dtype=np.float64)
        self.antenna_m = float(antenna_m)
        self.ranges = dict(ranges)      # size class -> max range (m)
        self.alive = True
        self.emitting = True

    @property
    def antenna_alt(self) -> float:
        return float(self.pos[1]) + self.antenna_m

    def detects(self, target_pos, size_class: str) -> bool:
        if not (self.alive and self.emitting):
            return False
        max_range = self.ranges.get(size_class, 0.0)
        dx = float(target_pos[0]) - float(self.pos[0])
        dz = float(target_pos[2]) - float(self.pos[2])
        rng = math.hypot(dx, dz)
        if rng > max_range:
            return False
        if rng > radar_horizon_m(self.antenna_alt, float(target_pos[1])):
            return False
        return not terrain_blocks(
            (self.pos[0], self.antenna_alt, self.pos[2]), target_pos)


class RadarNetwork:
    """One side's shared track sources: visible == any live radar detects."""

    def __init__(self, radars=()):
        self.radars = list(radars)

    def visible(self, target_pos, size_class: str) -> bool:
        return any(r.detects(target_pos, size_class) for r in self.radars)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_radar.py -q`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add sim/radar.py tests/test_radar.py
git commit -m "feat(combat): radar horizon + terrain LOS helpers (sim/radar.py)"
```

---

### Task 2: `Radar.detects` + `RadarNetwork` tests

**Files:**
- Modify: `tests/test_radar.py` (append; implementation already exists from Task 1)

- [ ] **Step 1: Write the failing-or-passing tests (they pin behavior)**

Append to `tests/test_radar.py`:

```python
RANGES = {"ship": 350_000.0, "fighter": 350_000.0, "stealth": 35_000.0}


def make_radar(**kw):
    kw.setdefault("radar_id", "r0")
    kw.setdefault("pos", (0.0, 100.0, 0.0))      # 100 m coastal hill
    kw.setdefault("antenna_m", 20.0)
    kw.setdefault("ranges", RANGES)
    return Radar(**kw)


def test_detects_high_target_in_range_over_open_water():
    # 150 km out over the ocean at 8 km altitude: in range, above horizon
    r = make_radar()
    assert r.detects((0.0, 8_000.0, 150_000.0), "fighter")


def test_rejects_beyond_class_range_and_unknown_class():
    r = make_radar()
    assert not r.detects((0.0, 8_000.0, 360_000.0), "fighter")  # > 350 km
    assert not r.detects((0.0, 8_000.0, 150_000.0), "no_such")  # range 0
    # stealth class: same target, tiny range -> rejected
    assert not r.detects((0.0, 8_000.0, 150_000.0), "stealth")


def test_sea_skimmer_hides_below_the_horizon():
    # 15 m target at 150 km: horizon ~ 4120*(sqrt(120)+sqrt(15)) ~ 61 km
    r = make_radar()
    assert not r.detects((0.0, 15.0, 150_000.0), "ship")
    assert r.detects((0.0, 15.0, 40_000.0), "ship")     # inside the horizon


def test_dead_or_silent_radar_sees_nothing():
    tgt = (0.0, 8_000.0, 150_000.0)
    r = make_radar(); r.alive = False
    assert not r.detects(tgt, "fighter")
    r = make_radar(); r.emitting = False
    assert not r.detects(tgt, "fighter")


def test_network_is_any_of_and_empty_network_is_blind():
    far = make_radar(radar_id="far", pos=(0.0, 100.0, 100_000.0))
    near_dead = make_radar(radar_id="dead"); near_dead.alive = False
    net = RadarNetwork([near_dead, far])
    assert net.visible((0.0, 8_000.0, 200_000.0), "fighter")
    assert not RadarNetwork([]).visible((0.0, 8_000.0, 0.0), "fighter")
```

- [ ] **Step 2: Run the tests**

Run: `python -m pytest tests/test_radar.py -q`
Expected: 8 passed. (These pin Task 1's implementation; if any fail, the implementation — not the test — is wrong: re-read `detects` against the docstring.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_radar.py
git commit -m "test(combat): pin Radar.detects + RadarNetwork behavior"
```

---

### Task 3: ContactBoard fog-of-war gating

**Files:**
- Modify: `sim/contacts.py`
- Create: `tests/test_contacts_gating.py`

**Behavior:** `ContactBoard(base_xz, visible_fn=None)`. With `visible_fn=None` the board behaves EXACTLY as today (sandbox untouched; existing tests must stay green). With a `visible_fn(pos, size_class) -> bool`:
- visibility is re-checked per entity every `VIS_CHECK_PERIOD` (0.5 s, cached — LOS scans are not free at 120 Hz),
- a NEW track forms only after `DETECT_DELAY_S` (2.0 s) of continuous visibility (spec §3 detection delay),
- an EXISTING track refreshes its fix only while visible; unseen it coasts (dead-reckons, `age` grows — the map already alpha-fades by age) and drops after `TRACK_DROP_S` (90 s) unseen.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_contacts_gating.py`:

```python
"""ContactBoard visible_fn gating (COMBAT fog of war, spec section 3)."""

import numpy as np

from sim.contacts import (DETECT_DELAY_S, TRACK_DROP_S, VIS_CHECK_PERIOD,
                          ContactBoard)

DT = 1.0 / 120.0


class FakeShip:
    """Minimal Ship duck-type for the board (pos/velocity/alive/ship_id)."""

    def __init__(self, sid="s0", pos=(0.0, 0.0, 50_000.0)):
        self.ship_id = sid
        self.pos = np.array(pos, dtype=np.float64)
        self.alive = True

    def velocity(self):
        return np.array([0.0, 0.0, 8.0])


def run(board, ents, seconds, t0=0.0):
    t = t0
    steps = int(round(seconds / DT))
    for _ in range(steps):
        t += DT
        board.update(ents, DT, t)
    return t


def test_none_gate_keeps_legacy_instant_tracking():
    board = ContactBoard((0.0, 0.0))
    board.update([FakeShip()], DT, DT)
    assert "s0" in board.tracks


def test_invisible_entity_never_tracks():
    board = ContactBoard((0.0, 0.0), visible_fn=lambda p, c: False)
    run(board, [FakeShip()], 10.0)
    assert board.tracks == {}


def test_track_forms_only_after_detect_delay():
    board = ContactBoard((0.0, 0.0), visible_fn=lambda p, c: True)
    ship = FakeShip()
    t = run(board, [ship], DETECT_DELAY_S * 0.5)
    assert board.tracks == {}                 # half the delay: not yet
    run(board, [ship], DETECT_DELAY_S, t0=t)  # well past it: tracked
    assert "s0" in board.tracks


def test_lost_track_coasts_then_drops():
    seen = {"v": True}
    board = ContactBoard((0.0, 0.0), visible_fn=lambda p, c: seen["v"])
    ship = FakeShip()
    t = run(board, [ship], DETECT_DELAY_S + 1.0)
    assert "s0" in board.tracks
    seen["v"] = False                         # radar killed / target masked
    t = run(board, [ship], TRACK_DROP_S * 0.5, t0=t)
    assert "s0" in board.tracks               # coasting, not dropped yet
    assert board.tracks["s0"]["age"] > 1.0    # estimate is aging (map fades)
    run(board, [ship], TRACK_DROP_S, t0=t)
    assert board.tracks == {}                 # stale: dropped


def test_gate_receives_size_class():
    classes = []

    def gate(pos, size_class):
        classes.append(size_class)
        return True

    board = ContactBoard((0.0, 0.0), visible_fn=gate)
    run(board, [FakeShip()], VIS_CHECK_PERIOD * 3)
    assert set(classes) == {"ship"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_contacts_gating.py -q`
Expected: FAIL — `ImportError: cannot import name 'DETECT_DELAY_S'`

- [ ] **Step 3: Implement the gating**

In `sim/contacts.py`, add after the `AIR_UPDATE_PERIODS` line:

```python
VIS_CHECK_PERIOD = 0.5    # s between cached visibility re-checks per entity
DETECT_DELAY_S = 2.0      # continuous visibility before a NEW track forms
TRACK_DROP_S = 90.0       # unseen coasting age at which a track drops
```

Replace `ContactBoard.__init__` with:

```python
    def __init__(self, base_xz, visible_fn=None):
        self.base_xz = np.asarray(base_xz, dtype=np.float64)
        self.tracks = {}
        # COMBAT fog of war: visible_fn(pos, size_class) -> bool gates
        # detection/refresh; None = legacy all-seeing sandbox behavior.
        self.visible_fn = visible_fn
        self._vis = {}    # cid -> dict(t_next, since, seen), cached checks
```

Add these methods to `ContactBoard` (before `update`):

```python
    def _seen(self, ent, cid, sim_time):
        """Cached current visibility (re-checked each VIS_CHECK_PERIOD);
        always True when ungated."""
        if self.visible_fn is None:
            return True
        st = self._vis.get(cid)
        if st is None:
            st = self._vis[cid] = dict(t_next=-1.0, since=None, seen=False)
        if sim_time >= st["t_next"]:
            size = "fighter" if getattr(ent, "is_air", False) else "ship"
            seen = bool(self.visible_fn(ent.pos, size))
            if seen and st["since"] is None:
                st["since"] = sim_time
            elif not seen:
                st["since"] = None
            st["seen"] = seen
            st["t_next"] = sim_time + VIS_CHECK_PERIOD
        return st["seen"]

    def _detected(self, ent, cid, sim_time):
        """Seen continuously for DETECT_DELAY_S (instant when ungated)."""
        if not self._seen(ent, cid, sim_time):
            return False
        if self.visible_fn is None:
            return True
        since = self._vis[cid]["since"]
        return since is not None and sim_time - since >= DETECT_DELAY_S

    def _drop(self, cid):
        self.tracks.pop(cid, None)
        self._vis.pop(cid, None)
```

Replace `update` with (changed lines marked):

```python
    def update(self, entities, dt, sim_time):
        for ent in entities:
            is_air = getattr(ent, "is_air", False)
            cid = ent.aircraft_id if is_air else ent.ship_id
            dead = not ent.alive
            track = self.tracks.get(cid)
            if track is None:
                if dead or not self._detected(ent, cid, sim_time):  # gated
                    continue                      # never seen alive: no track
                self.tracks[cid] = dict(
                    pos=ent.pos.copy(), vel=ent.velocity().copy(),
                    age=0.0, t_next=sim_time + self._period(ent.pos, is_air),
                    is_air=is_air)
            elif sim_time >= track["t_next"]:
                if dead:                          # drops after one refresh cycle
                    self._drop(cid)
                    continue
                if self._seen(ent, cid, sim_time):                  # gated
                    track["pos"] = ent.pos.copy()
                    track["vel"] = ent.velocity().copy()
                    track["age"] = 0.0
                    track["t_next"] = sim_time + self._period(ent.pos, is_air)
                else:                             # unseen: coast, retry, drop
                    track["age"] += dt
                    track["t_next"] = sim_time + VIS_CHECK_PERIOD
                    if track["age"] >= TRACK_DROP_S:
                        self._drop(cid)
            else:
                track["age"] += dt
```

Also update the module docstring's first paragraph to mention the gate:
append the sentence `With ``visible_fn`` set (COMBAT fog of war) the board
additionally gates tracks on radar visibility — see ContactBoard.` to the
end of the existing docstring.

- [ ] **Step 4: Run the new tests AND the full suite (legacy behavior must hold)**

Run: `python -m pytest tests/test_contacts_gating.py tests/ -q`
Expected: all pass, zero failures anywhere (especially any existing contact/world/map tests).

- [ ] **Step 5: Commit**

```bash
git add sim/contacts.py tests/test_contacts_gating.py
git commit -m "feat(combat): ContactBoard visible_fn gating (fog of war)"
```

---

### Task 4: WorldState spawn hooks

**Files:**
- Modify: `world/world.py:81-96` (`__init__`) — no behavior change

- [ ] **Step 1: Refactor `__init__` to call hooks**

In `world/world.py`, replace these `__init__` lines:

```python
        self.ships = [self._spawn_ship(i, spawn)
                      for i, spawn in enumerate(SHIP_SPAWNS)]
        self.aircraft = [Aircraft(s["aircraft_id"], s["aircraft_type"],
                                  s["anchor_a"], s["anchor_b"])
                         for s in AIRCRAFT_SPAWNS]
        self.sites = SITES
```

with:

```python
        self.ships = self._spawn_ships()
        self.aircraft = self._spawn_aircraft()
        self.sites = self._spawn_sites()
```

and replace `self.contacts = ContactBoard((BASE_POS[0], BASE_POS[2]))` with
`self.contacts = self._build_contacts()`.

Then add, right after `_spawn_ship`:

```python
    def _spawn_ships(self) -> list[Ship]:
        """Sandbox default: the 14 lane-following traffic ships.
        CombatWorld overrides (world/combat.py)."""
        return [self._spawn_ship(i, spawn)
                for i, spawn in enumerate(SHIP_SPAWNS)]

    def _spawn_aircraft(self) -> list[Aircraft]:
        """Sandbox default: the 4 racetrack patrols."""
        return [Aircraft(s["aircraft_id"], s["aircraft_type"],
                         s["anchor_a"], s["anchor_b"])
                for s in AIRCRAFT_SPAWNS]

    def _spawn_sites(self):
        """Sandbox default: the enemy-coast land sites."""
        return SITES

    def _build_contacts(self) -> ContactBoard:
        """Sandbox default: the legacy all-seeing fuzzy board."""
        return ContactBoard((BASE_POS[0], BASE_POS[2]))
```

- [ ] **Step 2: Run the full suite — pure refactor, everything stays green**

Run: `python -m pytest tests/ -q`
Expected: all pass (`tests/test_world_state.py` pins `ws.sites is generation.SITES` — still true).

- [ ] **Step 3: Commit**

```bash
git add world/world.py
git commit -m "refactor(world): overridable spawn/contacts hooks for CombatWorld"
```

---

### Task 5: `world/combat.py` — CombatWorld

**Files:**
- Create: `world/combat.py`
- Create: `tests/test_combat_world.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_combat_world.py`:

```python
"""CombatWorld (Phase 1): empty traffic, radar-gated picture, on-land site."""

from world.combat import (COMBAT_SITES, PLAYER_RADAR_RANGES,
                          RADAR_STATION_XZ, CombatWorld)
from world.generation import terrain_height_scalar

DT = 1.0 / 120.0


def test_no_sandbox_traffic():
    cw = CombatWorld()
    assert cw.ships == []
    assert cw.aircraft == []
    assert cw.sites is COMBAT_SITES


def test_radar_station_pin_is_on_dry_land():
    x, z = RADAR_STATION_XZ
    assert terrain_height_scalar(x, z) > 5.0


def test_contact_board_is_radar_gated():
    cw = CombatWorld()
    assert cw.contacts.visible_fn is not None
    assert cw.radar_net.radars == [cw.radar_station]
    assert cw.radar_station.ranges == PLAYER_RADAR_RANGES
    # the station stands ON the terrain (not floating / buried)
    assert cw.radar_station.pos[1] == terrain_height_scalar(*RADAR_STATION_XZ)


def test_empty_world_steps_and_s300_has_no_targets():
    cw = CombatWorld()
    for _ in range(120):
        cw.step(DT)
    assert cw.contacts.tracks == {}
    # S-300 cannot fire blind: no air track id exists to pass
    assert cw.launch_sam("anything") is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_combat_world.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'world.combat'`

- [ ] **Step 3: Write the implementation**

Create `world/combat.py`:

```python
"""CombatWorld: the COMBAT-mode world (Phase 1 — fog-of-war shell).

Keeps the terrain, the Bastion/Oniks battery and the S-300; spawns NONE of
the sandbox traffic (no ship lanes, no patrol aircraft, no enemy-coast
sites). The contact picture is radar-gated (sim/radar.py): the player's
ground radar station is the side's only set of eyes — the S-300 cannot
engage what the station does not see. Later phases stack enemies, Pantsir,
base damage and the commander AI on this shell.

Pure numpy / GL-free (LOCKED test convention), like world.world.
"""

from __future__ import annotations

from sim.contacts import ContactBoard
from sim.radar import Radar, RadarNetwork
from world.generation import BASE_POS, SEED, terrain_height_scalar
from world.world import WorldState

# Player ground radar station: home-coast shelf east of the base (the same
# raised cliff band that carries the S-300 pad; the on-land pin is LOCKED
# by tests/test_combat_world.py — nudge z south if generation ever changes).
RADAR_STATION_XZ = (40_000.0, -6_000.0)
RADAR_ANTENNA_M = 18.0          # radome center above the slab
PLAYER_RADAR_RANGES = {         # size class -> max detection range (m)
    "ship": 350_000.0, "fighter": 350_000.0,
    "missile": 120_000.0, "stealth": 35_000.0,
}

COMBAT_SITES = [
    {"id": "radar_player_00", "kind": "radar",
     "pos": RADAR_STATION_XZ, "name": "RADAR STN (FRIENDLY)"},
]


class CombatWorld(WorldState):
    """WorldState variant: empty traffic, radar-gated contact picture."""

    def _spawn_ships(self):
        return []

    def _spawn_aircraft(self):
        return []

    def _spawn_sites(self):
        return COMBAT_SITES

    def _build_contacts(self) -> ContactBoard:
        x, z = RADAR_STATION_XZ
        self.radar_station = Radar(
            "radar_player_00", (x, terrain_height_scalar(x, z), z),
            RADAR_ANTENNA_M, PLAYER_RADAR_RANGES)
        self.radar_net = RadarNetwork([self.radar_station])
        return ContactBoard((BASE_POS[0], BASE_POS[2]),
                            visible_fn=self.radar_net.visible)
```

(`SEED` import: `WorldState.__init__(rng_seed=SEED)` default already covers
it — if your linter flags the unused import, drop it from the import line.)

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_combat_world.py -q`
Expected: 4 passed. **If `test_radar_station_pin_is_on_dry_land` fails:** the
constant sits on water — move `RADAR_STATION_XZ` further inland (more
negative z, e.g. `(40_000.0, -10_000.0)`) until the test passes, keeping it
within ~50 km of the base.

- [ ] **Step 5: Commit**

```bash
git add world/combat.py tests/test_combat_world.py
git commit -m "feat(combat): CombatWorld with player ground radar station"
```

---

### Task 6: Tactical map draws the world's sites

**Files:**
- Modify: `game/tactical_map.py:718-727` (`_sites`)

- [ ] **Step 1: Make `_sites` read `world.sites`**

In `game/tactical_map.py`, change the loop header in `_sites` (line ~720):

```python
    def _sites(self) -> None:
        s = SITE_HALF_PX
        for site in self.sandbox.world.sites:
```

(`SITES` stays imported — `pick_*` helpers may still use it; in SANDBOX
`world.sites is SITES`, so this draw is behavior-identical there. COMBAT now
shows the friendly radar station instead of the enemy-coast sites.)

- [ ] **Step 2: Run the map tests**

Run: `python -m pytest tests/test_tactical_map.py -q`
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add game/tactical_map.py
git commit -m "fix(map): draw the session world's sites, not the global list"
```

---

### Task 7: CombatState + COMBAT menu item

**Files:**
- Modify: `game/sandbox.py:227` (`self.world = WorldState()`)
- Create: `game/combat.py`
- Modify: `game/states.py:68` (`MAIN_ITEMS`), `game/states.py:350-356` (`MenuState._fire`)
- Modify: `main.py` (add `App.start_combat` after `start_sandbox`)
- Modify: `tests/test_states.py:50` (FakeApp), `tests/test_states.py:79` (items)

- [ ] **Step 1: Update the menu tests to the new expectation (failing first)**

In `tests/test_states.py` change line 79:

```python
    assert MAIN_ITEMS == ("SANDBOX", "COMBAT", "SETTINGS", "QUIT")
```

In `FakeApp` (after `start_sandbox`, line ~50) add:

```python
    def start_combat(self):
        self.combat_started = getattr(self, "combat_started", 0) + 1
```

And add this test after `test_menu_starts_on_sandbox_and_navigates`:

```python
def test_menu_combat_item_starts_combat(kb):
    menu = MenuState(FakeApp(kb))
    menu._fire("COMBAT")
    assert menu.app.combat_started == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_states.py -q`
Expected: FAIL on the two new/changed tests.

- [ ] **Step 3: Implement menu + state + app wiring**

`game/states.py` line 68:

```python
MAIN_ITEMS = ("SANDBOX", "COMBAT", "SETTINGS", "QUIT")
```

`game/states.py` `MenuState._fire` — add the branch after the SANDBOX one:

```python
        elif name == "COMBAT":
            self.app.start_combat()     # fresh combat session
```

Also update the `MenuState` docstring first line to
`"""Main menu: SANDBOX / COMBAT / SETTINGS / QUIT over a flat BG0 field, ..."""`.

`game/sandbox.py` — in `SandboxState.__init__` replace
`self.world = WorldState()` with `self.world = self._build_world()`, and add
right after `__init__` (before `_slug_meshdata`):

```python
    def _build_world(self):
        """The session's world; CombatState overrides (game/combat.py)."""
        return WorldState()
```

Create `game/combat.py`:

```python
"""CombatState: the COMBAT mode shell (Phase 1).

SandboxState with a CombatWorld: same engine, cameras, tactical map and
weapons — none of the sandbox traffic, and a radar-gated contact picture.
Later phases add enemies, the commander AI and the setup screen on top.
"""

from __future__ import annotations

from game.sandbox import SandboxState
from world.combat import CombatWorld


class CombatState(SandboxState):
    """The COMBAT session: fog-of-war world on the sandbox engine."""

    def _build_world(self):
        return CombatWorld()
```

`main.py` — add after `start_sandbox` (line ~90):

```python
    def start_combat(self) -> None:
        """Menu COMBAT item: start a fresh fog-of-war combat session.
        Reuses the ``sandbox`` slot so pause/resume/quit flows apply."""
        from game.combat import CombatState     # after the GL context exists
        self._draw_loading_frame()
        if self.sandbox is not None:
            self.sandbox.dispose()
        self.paused = False
        self.sandbox = CombatState(self)
        self.states.switch(self.sandbox)
```

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add game/states.py game/sandbox.py game/combat.py main.py tests/test_states.py
git commit -m "feat(combat): COMBAT menu mode running CombatWorld"
```

---

### Task 8: Manual smoke run + verification

- [ ] **Step 1: Run the game**

Run: `python main.py`

Verify by hand:
1. Main menu shows `SANDBOX / COMBAT / SETTINGS / QUIT`.
2. COMBAT loads (BUILDING WORLD frame, then terrain) — no ships, no aircraft anywhere.
3. The radar station model stands on the home coast (fly the free cam toward x=40 km just south of the waterline).
4. M map: no enemy sites, no contacts; the friendly radar site marker is drawn at the station.
5. TAB to S-300, click around the map: it must refuse to fire (no air contacts can exist) — the existing "SELECT AIR TARGET" hint flashes.
6. ESC pause → RESUME works; MAIN MENU (double-ENTER) → SANDBOX still behaves exactly as before (full traffic, all-seeing map).

- [ ] **Step 2: Run the whole suite one final time**

Run: `python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Step 3: Commit any smoke-run fixes, then log the milestone**

```bash
git add -A
git commit -m "feat(combat): phase 1 complete - fog-of-war combat shell"
```

---

## Out of scope for Phase 1 (next plans)

Enemy destroyers/SM-2/CIWS (Phase 2), enemy strikes + base HP (Phase 3),
fighters/AWACS/carrier/airfield/commander (Phase 4), Pantsir (5), recon
drone (6), setup screen/armory/seeded generation/win-lose (7) — per spec §8.
