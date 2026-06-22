"""Per-battery STATUS PANEL pure helpers (M6) — headless, GL-free.

``battery_status_rows(world)`` is the player-only own-force battery readout the
expanded panel (G) and the compact per-platform row render: one dict per player
battery (each Oniks TEL, each S-300 TEL) carrying every physical tube's state
(LOADED / RELOADING / EMPTY) + the shared magazine pool text/colour + the
magazine-refill countdown when the pool is dry.  ``tube_state(t)`` is the per-
tube classifier.

FOG / NO-CHEAT: both read ONLY the world's OWN launcher/magazine attributes
(_oniks_tubes / _s300_tubes + the ammo pools + reload timers).  They never touch
contacts / enemy / world.missiles truth — friendly own-force logistics, exempt
from the radar gate exactly like oniks_ammo_row / tube_cells.  Deterministic, no
RNG.  Tested against a REAL CombatWorld (poking the live tube dicts) so the
helpers match the structures the sim actually maintains.
"""

from __future__ import annotations

import numpy as np

from game.hud import battery_status_rows, tube_state
from world.combat import CombatWorld
from world.combat_config import CombatConfig

DT = 1.0 / 120.0

# A far surface aim point for an Oniks single-fire (any ship-less point; the
# Bastion takes a surface point and fires the next ready tube — no contact
# needed for the launch path itself).
_SURFACE_AIM = np.array([0.0, 0.0, 150_000.0])


def _oniks_batteries(rows):
    """The Oniks-TEL battery dicts (name starts with the BASTION display)."""
    return [b for b in rows if b["name"].startswith("BASTION")]


def _s300_batteries(rows):
    return [b for b in rows if b["name"].startswith("S-300")]


# ---------------------------------------------------------------------------
# tube_state classifier (the spec's truth table)
# ---------------------------------------------------------------------------

def test_tube_state_oniks_loaded_and_recocked_is_loaded():
    assert tube_state({"loaded": True, "reload_left": 0.0}) == "LOADED"


def test_tube_state_oniks_reloading():
    # not loaded yet but the re-cock timer is running -> RELOADING
    assert tube_state({"loaded": False, "reload_left": 30.0}) == "RELOADING"
    # a loaded flag does not override an active reload timer (mid-cycle)
    assert tube_state({"loaded": True, "reload_left": 5.0}) == "RELOADING"


def test_tube_state_oniks_empty():
    # re-cocked (reload_left <= 0) but no round fed -> EMPTY
    assert tube_state({"loaded": False, "reload_left": 0.0}) == "EMPTY"


def test_tube_state_s300_no_loaded_key():
    # S-300 tubes carry no 'loaded' key: reload_left>0 -> RELOADING; else the
    # pool decides (pool_has_round flag passed by the battery walker).
    assert tube_state({"reload_left": 5.0}) == "RELOADING"
    assert tube_state({"reload_left": 0.0}, pool_has_round=True) == "LOADED"
    assert tube_state({"reload_left": 0.0}, pool_has_round=False) == "EMPTY"


# ---------------------------------------------------------------------------
# (a) fresh battery: 2 Oniks TELs, each 2 LOADED tubes
# ---------------------------------------------------------------------------

def test_fresh_two_oniks_batteries_each_two_loaded_tubes():
    cw = CombatWorld(CombatConfig(seed=1337, n_oniks=2, oniks_ammo=8))
    rows = battery_status_rows(cw)
    bat = _oniks_batteries(rows)
    assert len(bat) == 2, "expected one battery dict per Oniks TEL"
    for b in bat:
        states = [s for (s, _left) in b["tubes"]]
        assert states == ["LOADED", "LOADED"], "each TEL has 2 LOADED tubes"
        assert b["pool_text"] == "8/8"            # full magazine
        assert b["refill_left"] == 0.0            # not refilling


# ---------------------------------------------------------------------------
# (b) after a launch: one tube RELOADING with reload_left == the reload total
# ---------------------------------------------------------------------------

def test_after_launch_one_tube_reloading_with_countdown():
    cfg = CombatConfig(seed=1337, n_oniks=1, oniks_ammo=8,
                       oniks_mag_reload_s=120.0)
    cw = CombatWorld(cfg)
    m = cw.launch("hi-lo", _SURFACE_AIM)
    assert m is not None
    rows = battery_status_rows(cw)
    bat = _oniks_batteries(rows)
    assert len(bat) == 1
    tubes = bat[0]["tubes"]
    reloading = [(s, left) for (s, left) in tubes if s == "RELOADING"]
    assert len(reloading) == 1, "exactly one tube re-cocking after one shot"
    # The fired tube's reload_left is the full per-tube reload total at t=0...
    _state, left0 = reloading[0]
    assert left0 == cfg.oniks_mag_reload_s
    # ...and it counts DOWN as the world steps.
    for _ in range(120):                          # 1 s
        cw.step(DT)
    rows2 = battery_status_rows(cw)
    left1 = next(left for (s, left) in _oniks_batteries(rows2)[0]["tubes"]
                 if s == "RELOADING")
    assert 0.0 < left1 < left0                    # strictly counted down


# ---------------------------------------------------------------------------
# (c) drained magazine: re-cocked-unfed tubes EMPTY, pool '0/cap', refill > 0
# ---------------------------------------------------------------------------

def test_drained_magazine_empty_tubes_pool_zero_and_refilling():
    cfg = CombatConfig(seed=1337, n_oniks=1, oniks_ammo=2,
                       oniks_mag_reload_s=60.0)
    cw = CombatWorld(cfg)
    # Drain the pool: fire both tubes, then instantly re-cock them (the per-tube
    # timer skip used elsewhere) so a re-cocked-but-unfed tube reads EMPTY.
    for _ in range(2):
        assert cw.launch("hi-lo", _SURFACE_AIM) is not None
        for t in cw._oniks_tubes:
            t["reload_left"] = 0.0
        cw._step_oniks_tubes(0.0)
    assert cw._oniks_ammo == 0
    assert cw._oniks_mag_reload_left > 0.0
    rows = battery_status_rows(cw)
    b = _oniks_batteries(rows)[0]
    assert all(s == "EMPTY" for (s, _left) in b["tubes"]), \
        "re-cocked-but-unfed tubes read EMPTY when the magazine is dry"
    assert b["pool_text"] == "0/2"
    assert b["refill_left"] > 0.0


# ---------------------------------------------------------------------------
# (d) S-300: after launch_sam one of 4 tubes is RELOADING
# ---------------------------------------------------------------------------

def test_s300_after_launch_one_tube_reloading():
    cfg = CombatConfig(seed=1337, n_s300=1, s300_48n6_ammo=4)
    cw = CombatWorld(cfg)
    # Seed a held AIR contact (the fog-honest store launch_sam reads) on a live
    # enemy air entity, then fire one 48N6 round.
    air = [e for e in cw.enemy_air if getattr(e, "alive", True)]
    assert air, "expected an enemy air entity to target"
    ent = air[0]
    cw.contacts.tracks[ent.aircraft_id] = dict(
        pos=ent.pos.copy(), vel=np.zeros(3), age=0.0,
        t_next=cw.sim_time + 100.0, is_air=True, kind="fighter", size=0.3)
    m = cw.launch_sam(ent.aircraft_id, round_id="48n6")
    assert m is not None
    rows = battery_status_rows(cw)
    b = _s300_batteries(rows)[0]
    states = [s for (s, _left) in b["tubes"]]
    assert states.count("RELOADING") == 1, "exactly one of 4 tubes re-cocking"
    assert states.count("LOADED") == 3      # the rest still ready (pool > 0)


def test_s300_battery_tube_count_is_four_per_tel():
    cfg = CombatConfig(seed=1337, n_s300=1)
    cw = CombatWorld(cfg)
    b = _s300_batteries(battery_status_rows(cw))[0]
    assert len(b["tubes"]) == 4


# ---------------------------------------------------------------------------
# (e) sandbox WorldState (infinite ammo, no tube structures) -> no batteries /
#     pool_text omitted (mirrors oniks_ammo_row returning None in sandbox)
# ---------------------------------------------------------------------------

def test_sandbox_world_has_no_battery_rows():
    from world.world import WorldState
    ws = WorldState()
    rows = battery_status_rows(ws)
    assert rows == [], "sandbox infinite world surfaces no per-battery panel"


def test_object_without_tube_attrs_returns_empty():
    class _Bare:
        pass
    assert battery_status_rows(_Bare()) == []


# ---------------------------------------------------------------------------
# (f) determinism: same world -> identical rows
# ---------------------------------------------------------------------------

def test_determinism_same_world_same_rows():
    cw = CombatWorld(CombatConfig(seed=1337, n_oniks=2, oniks_ammo=8))
    assert battery_status_rows(cw) == battery_status_rows(cw)


def test_shape_contract_keys_present():
    cw = CombatWorld(CombatConfig(seed=1337, n_oniks=1))
    b = _oniks_batteries(battery_status_rows(cw))[0]
    assert set(b.keys()) == {"name", "tubes", "pool_text", "pool_col",
                             "refill_left"}
    # tubes is a list of (state, reload_left) pairs.
    for cell in b["tubes"]:
        assert len(cell) == 2
        assert cell[0] in ("LOADED", "RELOADING", "EMPTY")
        assert isinstance(cell[1], float)
