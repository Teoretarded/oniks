# Radar Scan Model + Seeker Honesty Implementation Plan (R-P0 / R-P1)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans
> (inline, SOLO — the user's standing rule is no subagent fleets). Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Radars scan directionally (paint-based detection behind a
`radar_model` legacy flag) and every missile seeker obeys physics
(horizon / terrain / cone / illuminator) instead of reading truth.

**Architecture:** Closed-form paint scheduling on `Radar` (no per-tick
sweeping), scan-driven `ContactBoard` refresh replacing the fake range-band
periods, and gate composition reusing the existing honest helpers
(`radar_horizon_m`, `terrain_blocks`) inside the seeker acquisition paths.
Spec: `docs/plans/weather_system_design_2026-07-07.md` PART 2 (§8–§13).

**Tech Stack:** pure numpy/math sim modules (GL-free), pytest (-n auto).

## Global Constraints

- SOLO build, no agent fleets (user law, memory `work-solo-no-agents`).
- TDD: every task's tests written RED first.
- `CombatConfig.radar_model: str = "functional"` default — the full
  ~1300-test suite must stay green untouched at every commit.
- Game layer forces `"scanned"` at the four damage_model-pattern sites:
  `world/sandbox_world.py:63`, `game/campaign.py:163`, `game/combat.py:93`,
  `game/combat_setup.py:558` (+ `clamp_config` in `world/combat_config.py:350/434`).
- Zero RNG in any new sensor code. Sim modules stay GL-free.
- No sim module may weaken an existing test contract.
- Research doc BEFORE the wiring task (repo convention: NORMATIVE docs).
- Run `pytest -q -n auto` (never serial) before every commit claim.
- Every task ends with a commit; run-log entry at the end of each phase.

## File Structure

- `sim/radar.py` — ScanDef + paint math + painted/next_paint on Radar +
  RadarNetwork.paint_state (grows ~150 lines; stays the one radar module).
- `sim/contacts.py` — ContactBoard paint_fn mode.
- `world/combat_config.py` — `radar_model` field + clamp_config plumbing.
- `world/combat.py` — ScanDef assignments, `_player_paint_state`, scanned
  wiring; enemy ground radars + Buk 9S36 + CBR assignments.
- `sim/enemy_air.py`, `sim/enemy_ships.py`, `sim/pantsir.py`, `sim/recon.py`
  — ScanDef assignments on their Radar constructions.
- `sim/missile.py` — seeker gates in `_acquire_lock` + terminal lock recheck.
- `sim/sam.py` — seeker cone + ARH/SARH handover gates.
- `sim/a2a.py` — in-flight gimbal FOV.
- `sim/arsenal.py` — WeaponDef/SamDef seeker + guidance + band fields.
- `docs/research/radar_scan_and_bands.md` — NORMATIVE assignments table.
- `tools/probe_radar_scan.py`, `tools/probe_seeker_honesty.py` — probes.
- Tests: `tests/test_radar_scan.py`, `tests/test_seeker_honesty.py`.

---

### Task 1: ScanDef + closed-form paint math (`sim/radar.py`)

**Files:**
- Modify: `sim/radar.py`
- Test: `tests/test_radar_scan.py`

**Interfaces:**
- Produces: `ScanDef(kind, period_s, beamwidth_deg, sector_deg)` frozen
  dataclass; `STARING = ScanDef("staring", 0.0, 360.0, 360.0)`;
  `Radar.__init__(..., scan=STARING, band="S", phase0_s=0.0)`;
  `Radar.boresight_deg: float | Callable[[], float]` (sector center, deg,
  0 = +Z north CW — the LOCKED heading convention);
  `Radar.painted(target_pos, now, window) -> bool`;
  `Radar.next_paint_t(target_pos, now) -> float` (math.inf when never).

- [ ] **Step 1: failing tests** (`tests/test_radar_scan.py`)

```python
import math
import numpy as np
from sim.radar import Radar, ScanDef, STARING

def _radar(scan, boresight=0.0, phase0=0.0):
    r = Radar("t", (0.0, 0.0, 0.0), 20.0,
              {"missile": 100_000.0, "ship": 200_000.0,
               "fighter": 150_000.0, "stealth": 30_000.0},
              height_fn=lambda x, z: 0.0, scan=scan, phase0_s=phase0)
    r.boresight_deg = boresight
    return r

def _tgt(bearing_deg, rng_m=50_000.0, alt=5_000.0):
    b = math.radians(bearing_deg)
    return np.array([rng_m * math.sin(b), alt, rng_m * math.cos(b)])

def test_staring_paints_always():
    r = _radar(STARING)
    assert r.painted(_tgt(0.0), now=3.7, window=0.5)
    assert r.next_paint_t(_tgt(123.0), now=3.7) == 3.7

def test_rotating_paints_once_per_period():
    r = _radar(ScanDef("rotating", 10.0, 2.0, 360.0))
    t0 = r.next_paint_t(_tgt(90.0), now=0.0)
    t1 = r.next_paint_t(_tgt(90.0), now=t0 + 0.05)
    assert abs((t1 - t0) - 10.0) < 1e-6
    assert r.painted(_tgt(90.0), now=t0, window=0.5)
    assert not r.painted(_tgt(90.0), now=t0 + 5.0, window=0.5)

def test_rotating_phase_offsets_the_schedule():
    a = _radar(ScanDef("rotating", 10.0, 2.0, 360.0), phase0=0.0)
    b = _radar(ScanDef("rotating", 10.0, 2.0, 360.0), phase0=2.5)
    assert abs(a.next_paint_t(_tgt(0.0), 0.0)
               - b.next_paint_t(_tgt(0.0), 0.0)) > 1.0

def test_sector_radar_blind_outside_sector():
    r = _radar(ScanDef("sector", 2.0, 2.0, 60.0), boresight=0.0)
    assert r.next_paint_t(_tgt(0.0), now=0.0) < 2.0 + 1e-9
    assert r.next_paint_t(_tgt(120.0), now=0.0) == math.inf
    assert not r.painted(_tgt(120.0), now=1.0, window=10.0)

def test_sector_boresight_callable_slews():
    heading = {"deg": 0.0}
    r = _radar(ScanDef("sector", 2.0, 2.0, 60.0))
    r.boresight_deg = lambda: heading["deg"]
    assert r.next_paint_t(_tgt(120.0), now=0.0) == math.inf
    heading["deg"] = 120.0
    assert r.next_paint_t(_tgt(120.0), now=0.0) < 2.0 + 1e-9

def test_detects_unchanged_by_scan_fields():
    # detects() is the INSTANTANEOUS gate — byte-identical legacy behavior.
    r = _radar(ScanDef("sector", 2.0, 2.0, 60.0), boresight=0.0)
    assert r.detects(_tgt(120.0), "fighter")   # outside sector: still detects()
```

- [ ] **Step 2: run — must FAIL** (`pytest tests/test_radar_scan.py -x -q`,
  ImportError: ScanDef)

- [ ] **Step 3: implement.** In `sim/radar.py`:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class ScanDef:
    """HOW a radar searches. kind: "staring" (continuous, e.g. SPY-1 fixed
    faces), "rotating" (mechanical sweep, period_s per revolution),
    "sector" (electronically revisited wedge, period_s per revisit,
    sector_deg wide about the radar's boresight_deg)."""
    kind: str
    period_s: float
    beamwidth_deg: float
    sector_deg: float

STARING = ScanDef("staring", 0.0, 360.0, 360.0)
```

`Radar.__init__` gains `scan: ScanDef = STARING, band: str = "S",
phase0_s: float = 0.0`; stores `self.scan`, `self.band`, `self.phase0_s`,
`self.boresight_deg = 0.0`. Helpers (module level, pure):

```python
def _bearing_deg(from_pos, to_pos):
    return math.degrees(math.atan2(float(to_pos[0]) - float(from_pos[0]),
                                   float(to_pos[2]) - float(from_pos[2]))) % 360.0

def _ang_diff_deg(a, b):
    return abs((a - b + 180.0) % 360.0 - 180.0)
```

On `Radar`:

```python
def _boresight_now(self):
    b = self.boresight_deg
    return float(b()) if callable(b) else float(b)

def next_paint_t(self, target_pos, now):
    s = self.scan
    if s.kind == "staring":
        return now
    if s.kind == "sector":
        if _ang_diff_deg(_bearing_deg(self.pos, target_pos),
                         self._boresight_now()) > s.sector_deg * 0.5:
            return math.inf
        k = math.ceil((now - self.phase0_s) / s.period_s - 1e-9)
        return self.phase0_s + max(k, 0) * s.period_s
    # rotating: boresight(t) = (360 * (t - phase0) / period) mod 360
    brg = _bearing_deg(self.pos, target_pos)
    t_first = self.phase0_s + brg / 360.0 * s.period_s
    k = math.ceil((now - t_first) / s.period_s - 1e-9)
    return t_first + max(k, 0) * s.period_s

def painted(self, target_pos, now, window):
    s = self.scan
    if s.kind == "staring":
        return True
    nxt = self.next_paint_t(target_pos, now - window)
    dwell = (s.beamwidth_deg / 360.0 * s.period_s
             if s.kind == "rotating" else 0.0)
    return nxt <= now + dwell and nxt != math.inf
```

`detects()` untouched.

- [ ] **Step 4: run — must PASS** (`pytest tests/test_radar_scan.py -q`)
- [ ] **Step 5: full suite** `pytest -q -n auto` green (defaults untouched).
- [ ] **Step 6: commit** `feat(radar): ScanDef + closed-form paint scheduling (staring/rotating/sector)`

---

### Task 2: `radar_model` config + `RadarNetwork.paint_state`

**Files:**
- Modify: `world/combat_config.py` (field at ~:179 area, clamp_config
  ~:350/:434), `sim/radar.py` (RadarNetwork)
- Test: `tests/test_radar_scan.py` (append)

**Interfaces:**
- Produces: `CombatConfig.radar_model: str = "functional"`;
  `RadarNetwork.paint_state(target_pos, size_class, now, window, jammers=())
  -> tuple[bool, float]` — (painted-and-detected now, earliest next paint
  among radars that pass `detects`; `math.inf` when none).

- [ ] **Step 1: failing tests**

```python
def test_radar_model_default_functional():
    from world.combat_config import CombatConfig
    assert CombatConfig().radar_model == "functional"

def test_paint_state_min_over_network():
    from sim.radar import RadarNetwork, ScanDef
    rot = _radar(ScanDef("rotating", 10.0, 2.0, 360.0))
    star = _radar(STARING)
    net = RadarNetwork([rot, star])
    seen, nxt = net.paint_state(_tgt(0.0), "fighter", now=5.0, window=0.5)
    assert seen and nxt == 5.0                    # the staring face wins
    net2 = RadarNetwork([rot])
    seen2, nxt2 = net2.paint_state(_tgt(90.0), "fighter", now=5.0, window=0.5)
    assert nxt2 == rot.next_paint_t(_tgt(90.0), 5.0)

def test_paint_state_dead_radar_contributes_nothing():
    rot = _radar(ScanDef("rotating", 10.0, 2.0, 360.0))
    rot.alive = False
    net = RadarNetwork([rot])
    assert net.paint_state(_tgt(0.0), "fighter", 0.0, 0.5) == (False, math.inf)
```

- [ ] **Step 2: run — FAIL.**
- [ ] **Step 3: implement** — config field (docstring: the damage_model
  pattern, values `"functional" | "scanned"`); `clamp_config` passes it
  through like damage_model (`"functional" if x == "functional" else
  "scanned"`). RadarNetwork:

```python
def paint_state(self, target_pos, size_class, now, window, jammers=()):
    seen, nxt = False, math.inf
    for r in self.radars:
        if not r.detects(target_pos, size_class, jammers=jammers):
            continue
        nxt = min(nxt, r.next_paint_t(target_pos, now))
        if r.painted(target_pos, now, window):
            seen = True
    return seen, nxt
```

- [ ] **Step 4: PASS; Step 5: full suite green; Step 6: commit**
  `feat(radar): radar_model config flag + RadarNetwork.paint_state`

---

### Task 3: scan-driven ContactBoard refresh

**Files:**
- Modify: `sim/contacts.py`
- Test: `tests/test_radar_scan.py` (append)

**Interfaces:**
- Consumes: `paint_state`-shaped callable.
- Produces: `ContactBoard(base_xz, visible_fn=None, paint_fn=None)`;
  `paint_fn(pos, size_class, now, window) -> (bool, float)`. With paint_fn
  set: `_seen` = painted-in-window; refresh `t_next` = clamp(next_paint,
  now + REFRESH_FLOOR_S, now + REFRESH_CEIL_S). `REFRESH_FLOOR_S = 0.5`
  (staring radars refresh at the vis cadence, bounding cost),
  `REFRESH_CEIL_S = 30.0` (a coasting long-rotator track still re-checks).
  Legacy path (paint_fn None) byte-identical.

- [ ] **Step 1: failing test** (spec §9.4 contract, concretized)

```python
def test_track_staleness_follows_scan_not_range_bands():
    from sim.contacts import ContactBoard
    class _Ship:
        def __init__(self):
            self.pos = np.array([50_000.0, 0.0, 50_000.0])
            self.alive, self.ship_id = True, "tgt"
        def velocity(self): return np.zeros(3)
    def _board(radars):
        net = RadarNetwork(radars)
        return ContactBoard((0.0, 0.0),
            paint_fn=lambda p, s, now, win:
                net.paint_state(p, s, now, win))
    def _ages(board, ship):
        ages, t = [], 0.0
        while t < 60.0:
            board.update([ship], 0.1, t)
            tr = board.tracks.get("tgt")
            if tr is not None:
                ages.append(tr["age"])
            t += 0.1
        return ages
    rot10 = _radar(ScanDef("rotating", 10.0, 2.0, 360.0))
    ages_rot = _ages(_board([rot10]), _Ship())
    ages_star = _ages(_board([_radar(STARING), rot10]), _Ship())
    assert max(ages_rot) > 8.0        # stale between rotations
    assert max(ages_star) < 1.5       # staring face keeps it fresh

def test_legacy_visible_fn_path_untouched():
    from sim import contacts
    import inspect
    src = inspect.getsource(contacts.ContactBoard.update)
    assert "UPDATE_PERIODS" in inspect.getsource(contacts)  # legacy kept
```

- [ ] **Step 2: FAIL. Step 3: implement** — in `_seen`, when
  `self.paint_fn is not None`: `seen, nxt = self.paint_fn(ent.pos,
  _size_of(ent), sim_time, VIS_CHECK_PERIOD)`; store `nxt` in the vis-cache
  entry. In `update`, when paint_fn mode and a track refreshes:
  `track["t_next"] = min(max(nxt, sim_time + REFRESH_FLOOR_S),
  sim_time + REFRESH_CEIL_S)` instead of `self._period(...)`.
  DETECT_DELAY_S / TRACK_DROP_S / classification ladder unchanged.
- [ ] **Step 4: PASS. Step 5: full suite `-n auto` green. Step 6: commit**
  `feat(contacts): paint-driven track refresh (scanned radar model)`

---

### Task 4: research doc + world wiring (assignments per §9.3)

**Files:**
- Create: `docs/research/radar_scan_and_bands.md` (NORMATIVE — written FIRST)
- Modify: `world/combat.py` (player radars :1382, enemy ground :1334,
  Buk 9S36 :3486, CBR :3519, `_build_contacts` :1377,
  `_player_visible` :1456 area), `sim/pantsir.py:197`,
  `sim/enemy_ships.py:168`, `sim/enemy_air.py:492/:638/:1497/:1709`,
  `sim/recon.py:374/:391`, the four `"scanned"` forcing sites
  (Global Constraints), `world/sandbox_world.py:63`.
- Test: `tests/test_radar_scan.py` (append)

**Interfaces:**
- Consumes: ScanDef, paint_state, paint_fn.
- Produces: module-level ScanDefs in `world/combat.py`:
  `SCAN_ACQ_91N6 = ScanDef("rotating", 12.0, 2.0, 360.0)` (player station
  acquisition), `SCAN_ENG_30N6 = ScanDef("sector", 2.0, 2.0, 60.0)`
  (slewable engagement — R-P1 Task 7 consumes it),
  `SCAN_SPY1 = STARING`, `SCAN_BUK_9S36 = ScanDef("sector", 2.0, 2.0, 90.0)`,
  `SCAN_PANTSIR = ScanDef("rotating", 2.0, 4.0, 360.0)`,
  `SCAN_AWACS = ScanDef("rotating", 10.0, 1.5, 360.0)`,
  `SCAN_FIGHTER_NOSE = ScanDef("sector", 2.0, 3.0, 120.0)` (boresight =
  fighter heading callable), `SCAN_ENEMY_EW = ScanDef("rotating", 10.0,
  2.0, 360.0)`, `SCAN_CBR = ScanDef("sector", 1.0, 2.0, 90.0)` (fixed at
  the threat arc). Bands: station S, SPY-1 S, Buk X (actually C/X — doc
  decides, code takes the doc's value), Pantsir Ku(track)/S(acq) — acq
  radar object gets "S", fighter X, AWACS S, CBR X, seekers Ku (Task 6).

- [ ] **Step 1: write the research doc.** Contents: per-system table
  (game radar → real system → scan kind/period/beamwidth/sector → band →
  source note e.g. "91N6E Big Bird: ~12 s rotation, S-band" /
  "SPY-1D: 4 fixed passive faces, continuous, S-band" / "9S36: X-band
  sector FCR" / "E-3 rotodome 10 s" / "30N6E/92N6: sector engagement,
  X-band"). Values above are the doc's defaults; where the doc research
  contradicts them, the DOC wins and the constants follow it.
- [ ] **Step 2: failing wiring test**

```python
def test_scanned_mode_wires_paint_fn():
    from world.combat import CombatWorld
    from world.combat_config import CombatConfig
    w = CombatWorld(CombatConfig(radar_model="scanned"))
    assert w.contacts.paint_fn is not None
    assert w.radar_station.scan.kind == "rotating"      # 91N6 acquisition
    w2 = CombatWorld(CombatConfig())                    # functional default
    assert w2.contacts.paint_fn is None                 # legacy identity

def test_game_layer_forces_scanned():
    from world.sandbox_world import SANDBOX_CONFIG
    assert SANDBOX_CONFIG.radar_model == "scanned"
    from game.combat_setup import CombatSetupState   # build_config path is
    import inspect                                    # asserted like damage_model
    assert '"scanned"' in inspect.getsource(CombatSetupState.build_config)
```

- [ ] **Step 3: implement.** Every `Radar(...)` construction gets its
  ScanDef + band per the doc; `phase0_s` for multi-radar sets = index
  spread (`i * period / n`, deterministic — no RNG). Fighter nose radar
  boresight = `lambda f=fighter: math.degrees(f.heading) % 360.0` (check
  the actual heading attr in sim/enemy_air.py FighterRadar and use it).
  `_build_contacts` passes
  `paint_fn=self._player_paint_state if self.radar_model == "scanned" else None`
  where `_player_paint_state(pos, size, now, window)` wraps
  `self.radar_net.paint_state(..., jammers=self._active_enemy_jammers())`
  mirroring `_player_visible`'s jammer threading; `self.radar_model =
  getattr(config, "radar_model", "functional")` beside the damage_model
  read at `world/combat.py:584`. Force `"scanned"` at the four game-layer
  sites + SANDBOX_CONFIG. Enemy-side boards: find every other
  `ContactBoard(`/`visible(` consumer (grep during execution:
  `Grep "ContactBoard(" world sim`) and wire the same way when the world
  is scanned — the enemy commander reads the same honest picture
  (no-cheat pattern).
- [ ] **Step 4: PASS + full suite `-n auto` green (functional default).**
- [ ] **Step 5: probe** `tools/probe_radar_scan.py`: boots a scanned
  CombatWorld, tabulates per-track age p50/p95 by covering-radar mix +
  paints/minute per radar; prints the §9.4 staleness assertion numbers.
  Commit output summary into the run log.
- [ ] **Step 6: commit** `feat(radar): per-system scan assignments + scanned-mode wiring (91N6/30N6/SPY-1/9S36/AWACS/nose-AESA) + research doc`
- [ ] **Step 7: HOSTILE SELF-REVIEW pass** (enemy-AI no-cheat memory law:
  2-stage review on sensor diffs). Checklist: does any enemy module still
  read truth where a paint gate now exists? Does EMCON (silent radar)
  interact with paint_state (an off radar must contribute nothing —
  `detects` already gates emitting)? Do Buk TEL relocations carry their
  9S36 boresight? Does the CBR sector face the threat arc? Fix + commit.

---

### Task 5 (R-P1): Oniks/Zircon seeker physics gates

**Files:**
- Modify: `sim/missile.py` (`_acquire_lock` :637, terminal branch :715),
  `sim/arsenal.py` (WeaponDef: add `seeker_band: str = "Ku"` — consumed by
  W-P10 rain later, documented now)
- Test: `tests/test_seeker_honesty.py`

**Interfaces:**
- Consumes: `sim.radar.radar_horizon_m`, `sim.radar.terrain_blocks`,
  `world.terrain_height_at` (already threaded into worlds; stub worlds in
  tests provide it).
- Produces: `_acquire_lock(world, speed)` additionally requires, per
  candidate ship: `slant_range <= radar_horizon_m(missile_alt,
  ship_mast_alt)` with `SHIP_MAST_M = 18.0` module constant (superstructure
  radar-return height, cited vs DDG/frigate mast heights) and
  `not terrain_blocks(missile_pos, ship_pos_at_mast, height_fn=
  world.terrain_height_at)`; plus a KEEP-gate: the terminal branch
  re-checks the locked ship on `SEEKER_RECHECK_S = 0.5` cadence and drops
  the lock when masked (re-acquire allowed — the existing dead-lock drop
  pattern).

- [ ] **Step 1: failing tests** (spec §10.1 verbatim, fixtures concretized)

```python
import numpy as np
from sim.arsenal import ONIKS
from sim.missile import Missile

class _StubWorld:
    def __init__(self, ships, height_fn=lambda x, z: 0.0):
        self.ships = ships
        self.terrain_height_at = height_fn
    # minimal duck-type: _surface_at reads terrain_height_at / ocean 0

class _Ship:
    def __init__(self, x, z, alive=True):
        self.pos = np.array([x, 15.0, z]); self.alive = alive
        self.vel = np.zeros(3)
    def velocity(self): return self.vel

def _terminal_oniks(alt):
    m = Missile.__new__(Missile)          # bare: only what _acquire_lock reads
    m.weapon = ONIKS
    m.pos = np.array([0.0, alt, 0.0])
    m.vel = np.array([0.0, 0.0, 680.0])
    m.locked_ship = None
    return m

def test_oniks_seeker_horizon_limited():
    m = _terminal_oniks(alt=12.0)                       # 12 m skim
    far = _Ship(0.0, 45_000.0)                          # beyond ~32 km horizon
    m._acquire_lock(_StubWorld([far]), speed=680.0)
    assert m.locked_ship is None
    near = _Ship(0.0, 25_000.0)                         # inside horizon
    m._acquire_lock(_StubWorld([near]), speed=680.0)
    assert m.locked_ship is near

def test_oniks_seeker_blocked_by_island():
    ridge = lambda x, z: 140.0 if 8_000.0 < z < 9_000.0 else 0.0
    m = _terminal_oniks(alt=12.0)
    hidden = _Ship(0.0, 18_000.0)
    m._acquire_lock(_StubWorld([hidden], ridge), speed=680.0)
    assert m.locked_ship is None

def test_high_diver_keeps_long_acquisition():
    # a Zircon diving from 20 km sees past any surface horizon — the gates
    # must not nerf the designed high-altitude acquisition geometry.
    m = _terminal_oniks(alt=15_000.0)
    far = _Ship(0.0, 45_000.0)
    m._acquire_lock(_StubWorld([far]), speed=1_500.0)
    assert m.locked_ship is far
```

- [ ] **Step 2: FAIL. Step 3: implement** in `_acquire_lock`'s candidate
  loop, after the range/cone gates:

```python
mast_alt = float(sp[1]) + SHIP_MAST_M
if math.hypot(rx, rz) > radar_horizon_m(py, mast_alt):
    continue
hfn = getattr(world, "terrain_height_at", None)
if hfn is not None and terrain_blocks(
        (px, py, pz), (sp[0], mast_alt, sp[2]), height_fn=hfn):
    continue
```

  plus the keep-gate in the terminal branch (mirror the SamMissile
  `_los_next_t` cadence pattern; a masked lock is DROPPED to None so the
  existing re-acquire path runs).
- [ ] **Step 4: PASS. Step 5: full suite `-n auto`** — EXPECT possible
  breakage in e2e tests where shots relied on impossible locks; each
  breakage is triaged: geometry now honest → re-pin with a comment citing
  this plan; genuine regression → fix. NO tolerance-bump re-pins.
- [ ] **Step 6: probe** `tools/probe_seeker_honesty.py`: acquisition-range
  table (skim vs hi-dive, open water vs behind ridge) — numbers into the
  run log. **Step 7: commit** `fix(missile): Oniks/Zircon seeker obeys radar horizon + terrain (no more truth peeking)`

---

### Task 6 (R-P1): SAM seeker cone + ARH/SARH split

**Files:**
- Modify: `sim/sam.py` (terminal handover :663-677), `sim/arsenal.py`
  (SamDef: `seeker_half_angle_deg: float = 30.0`,
  `guidance: str = "arh"`, per-round values: 48N6 "sarh", 40N6 "arh",
  SM-2 "sarh", SM-6 "arh", 9M317 "sarh", 9M338 + 57E6 command/"arh"-
  equivalent per research doc), `world/combat.py` (player S-300 launch
  sites :3428/:3690 — wire `illuminator_pos_fn` for SARH rounds to the
  station engagement radar; enemy SM-2 already wired :3186)
- Test: `tests/test_seeker_honesty.py` (append)

**Interfaces:**
- Consumes: SCAN_ENG_30N6 sector radar from Task 4 (the illuminator's
  sector gate), `_ang_diff_deg`.
- Produces: terminal handover requires BOTH (a) target inside
  `seeker_half_angle_deg` of the missile velocity vector, (b) for
  `guidance == "sarh"`: `illuminator_pos_fn` present, returning non-None,
  AND (scanned mode) the illuminating radar's sector containing the
  target (threaded as `illuminator_ok_fn: () -> bool`; functional mode =
  always True when alive). Failing (a) at the range gate = handover simply
  WAITS (midcourse continues; PN geometry converges the cone); failing (b)
  mid-terminal = the existing `_lock_ok = False` frozen-point coast.

- [ ] **Step 1: failing tests**

```python
def test_sam_handover_requires_seeker_cone():
    m = _terminal_sam(vel_toward=(0.0, 0.0, 1.0))       # flying north
    beam_tgt = _AirTgt(x=25_000.0, z=0.0)               # 90 deg off the nose
    m.target = beam_tgt
    _step_to_terminal_range(m)
    assert m.phase == SPH_MIDCOURSE                     # cone refuses handover

def test_sarh_lock_dies_with_the_illuminator():
    m = _terminal_sam_sarh(illuminator_alive={"v": True})
    _step_to_terminal(m)
    m._illum_alive["v"] = False
    _step(m, 1.0)
    assert not m._lock_ok                               # frozen-point coast

def test_arh_round_survives_station_death():
    m = _terminal_sam_arh()                             # 40N6: own seeker
    _kill_station(m)
    _step(m, 1.0)
    assert m._lock_ok
```

  (fixture helpers `_terminal_sam*` build a SamMissile with a stub SamDef
  at terminal range — full code in the test file, following the
  test_sm2_statistics.py fixture style.)
- [ ] **Step 2: FAIL. Step 3: implement.** Handover gate at :668:

```python
close_enough = (rx*rx + ry*ry + rz*rz
                < w.terminal_range * w.terminal_range)
if close_enough and speed > 1e-9:
    cos_off = (rx*hx + ry*hy + rz*hz) / max(
        math.sqrt(rx*rx + ry*ry + rz*rz), 1e-9)
    if cos_off >= math.cos(math.radians(w.seeker_half_angle_deg)):
        ... existing handover ...
```

  SARH liveness folds into `_los_masked` (illuminator None → masked,
  already there) + new `illuminator_ok_fn` checked on the same cadence.
  Player wiring: 48N6-family launches pass `illuminator_pos_fn` = station
  engagement radar pos-if-alive closure + `illuminator_ok_fn` = sector
  check; 40N6/SM-6 pass neither. Also slew `SCAN_ENG_30N6`'s boresight to
  the engaged target's bearing at launch (the battery points its FCR —
  simple: world keeps `self._eng_boresight` updated per live engagement;
  the ScanDef boresight callable reads it).
- [ ] **Step 4: PASS. Step 5: full suite triage (same rule as Task 5).**
- [ ] **Step 6: commit** `feat(sam): terminal seeker cone + ARH/SARH illuminator physics (48N6 needs its station; 40N6 self-guides)`

---

### Task 7 (R-P1): AIM-9X in-flight gimbal FOV

**Files:**
- Modify: `sim/a2a.py` (update loop :453-479 region)
- Test: `tests/test_seeker_honesty.py` (append)

**Interfaces:**
- Produces: `IR_GIMBAL_HALF_ANGLE_RAD = math.radians(90.0)` (AIM-9X HOBS
  gimbal); each update step, when the LOS to the live target exceeds the
  gimbal off `body_dir`, the lock is LOST → `self_destructed` (replaces
  nothing — adds to the 2×-range band which stays as the energy band).

- [ ] **Step 1: failing test**

```python
def test_aim9x_loses_lock_past_gimbal():
    # target teleported directly BEHIND the missile: real seekers unlock.
    m = _boosting_aim9x(target=_drone_at(0.0, 0.0, 5_000.0))
    m.update(0.1, _stub_world())
    m.target.pos = np.array([0.0, 5_000.0, -6_000.0])    # behind
    m.update(0.1, _stub_world())
    assert not m.alive and m.self_destructed
```

- [ ] **Step 2: FAIL. Step 3: implement** in the live-target block:

```python
los = tpos - self.pos
d = float(np.linalg.norm(los))
if d > 1.0:
    cos_off = float(los @ self.body_dir) / d
    if cos_off < math.cos(IR_GIMBAL_HALF_ANGLE_RAD):
        self.self_destructed = True
        self._die(self.pos.copy())
        return
```

- [ ] **Step 4: PASS. Step 5: full suite. Step 6: commit**
  `fix(a2a): AIM-9X seeker gimbal FOV — lock breaks past 90 deg off-body`

---

### Task 8: run log + probes committed + wrap

- [ ] Write `docs/radar_scan_run_log_2026-07-07.md`: measured probe tables
  (track-age ladders per radar mix; seeker acquisition ranges skim vs
  dive), the honest nit list, any re-pinned tests with their geometry
  justification.
- [ ] `pytest -q -n auto` full green; smoke run of the game
  (`tools/probe_ui_overlaps.py` still passes — HUD reads tracks whose
  cadence changed).
- [ ] Second-stage hostile review of the whole diff (enemy-AI law):
  grep every `\.pos` read in sim/ enemy modules touched; confirm no new
  truth path.
- [ ] Update memory `combat-expansion-state.md`.
- [ ] Commit: `docs: radar scan + seeker honesty run log`.

## Self-Review (done at write time)

- Spec coverage: §9.1 (Task 1–3), §9.2 (Task 2/4), §9.3 (Task 4), §9.4
  contracts (Tasks 1/3/4), §10.1 (Task 5), §10.2 (Task 6), §10.3 minus
  cloud-LOS (Task 7; cloud part is W-P10 by design). Rain `band` fields
  seeded in Tasks 4/5 for W-P10.
- Type consistency: `paint_state` 4-arg + jammers kwarg everywhere;
  `ScanDef` field order fixed; `boresight_deg` float-or-callable
  resolved only via `_boresight_now`.
- No placeholders: fixture helpers named in Task 6 are defined in the test
  file itself (style reference: existing tests/test_sm2_statistics.py).
