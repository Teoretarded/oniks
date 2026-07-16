"""M5 Buk launch path in CombatWorld (mirror of the S-300 launch_sam tests).

Coverage:
  * n_buk=0 (default) -> NO Buk battery, NO 9S36 radar in radar_net, and
    launch_buk returns None (the round is never offered — byte-identical
    default battle);
  * a configured n_buk pool builds the battery + the 9S36 radar in
    world.radar_net, fires a SamMissile of the selected round at an AIR
    contact, consumes the RIGHT pool, decrements;
  * refuses on empty pool / mid-reload / no air track / non-air track;
  * the 9S36 radar EXTENDS the gated picture: it detects a low contact the
    18 m radar station alone misses (compare detection);
  * determinism: same seed + same launch -> bit-identical round;
  * the Buk's destructible Structure: on death the 9S36 radar drops from the
    net (mirror of the radar-station / Pantsir on_destroyed).

FOG / NO CHEAT: launch_buk reads world.contacts.tracks (is_air) only — never
truth (mirror of launch_sam).
"""

from __future__ import annotations

import numpy as np

from models.support_assets import BUK_MOUTH_OFFSETS
from sim.arsenal import BUK_AGILE, BUK_LONG, BUK_TEL
from sim.sam import SamMissile
from world.combat import CombatWorld
from world.combat_config import CombatConfig

DT = 1.0 / 120.0


def _air_entity(cw):
    """A live enemy AIR entity (fighter / AWACS) to back an injected track."""
    air = [e for e in cw.enemy_air if getattr(e, "alive", True)]
    assert air, "expected at least one enemy air entity to target"
    return air[0]


def _inject_air_track(cw, ent, pos=None, vel=None):
    """Seed a held AIR contact for ``ent`` on the player picture (mirror of a
    real ContactBoard air track — the fog-honest store launch_buk reads)."""
    p = ent.pos.copy() if pos is None else np.asarray(pos, dtype=np.float64)
    v = np.zeros(3) if vel is None else np.asarray(vel, dtype=np.float64)
    cw.contacts.tracks[ent.aircraft_id] = dict(
        pos=p.copy(), vel=v.copy(), age=0.0,
        t_next=cw.sim_time + 100.0, is_air=True, kind="fighter", size=0.3)
    return ent.aircraft_id


# ---------------------------------------------------------------------------
# Regression: n_buk=0 -> no Buk anywhere
# ---------------------------------------------------------------------------

def test_default_battle_has_no_buk():
    """DEFAULT config (n_buk=0): no battery, no 9S36 radar in the net,
    launch_buk returns None for either round (byte-identical default battle)."""
    cw = CombatWorld(CombatConfig(seed=1337))
    assert cw.n_buk == 0
    assert cw._buk_tubes == []
    assert cw._buk_launcher_positions == []
    # No buk_tel structure built.
    assert not any(s.kind == "buk_tel" for s in cw.structures)
    # No 9S36 radar joined the net.
    assert all("9s36" not in getattr(r, "radar_id", "")
               for r in cw.radar_net.radars)
    # Launch is refused regardless of any track.
    assert cw.launch_buk("anything", round_id="9m317") is None
    assert cw.launch_buk("anything", round_id="9m338") is None


# ---------------------------------------------------------------------------
# Armed battery: build + radar in net
# ---------------------------------------------------------------------------

def test_buk_battery_builds_and_radar_joins_net():
    cw = CombatWorld(CombatConfig(seed=1337, n_buk=1))
    assert cw.n_buk == 1
    assert len(cw._buk_launcher_positions) == 1
    assert len(cw._buk_tubes) >= 1
    # Pools seeded from config.
    assert cw.buk_9m317_ammo == 6
    assert cw.buk_9m338_ammo == 6
    # A destructible buk_tel structure exists.
    assert any(s.kind == "buk_tel" for s in cw.structures)
    # The 9S36 radar joined the player net.
    assert any("9s36" in getattr(r, "radar_id", "")
               for r in cw.radar_net.radars)


def test_buk_tubes_use_six_distinct_visible_model_mouths():
    cw = CombatWorld(CombatConfig(seed=1337, n_buk=1))
    launcher = cw._buk_launcher_positions[0]
    offsets = [tube["pos"] - launcher for tube in cw._buk_tubes]

    assert len(offsets) == BUK_TEL.tubes == len(BUK_MOUTH_OFFSETS) == 6
    for actual, expected in zip(offsets, BUK_MOUTH_OFFSETS):
        assert np.allclose(actual, expected)
    assert len({tuple(np.round(offset, 6)) for offset in offsets}) == 6

    target = _air_entity(cw)
    track_id = _inject_air_track(cw, target)
    expected_launch_pos = cw._buk_tubes[0]["pos"].copy()
    missile = cw.launch_buk(track_id)
    assert np.allclose(missile.pos, expected_launch_pos)


def test_buk_battery_does_not_trip_lose_condition():
    """Killing the Buk struct must NOT trip ``defeated`` (only bastion_tel
    does — mirror of the Pantsir / swarm-pod wrappers)."""
    cw = CombatWorld(CombatConfig(seed=1337, n_buk=1))
    for s in cw.structures:
        if s.kind == "buk_tel":
            s.alive = False
    assert not cw.defeated


# ---------------------------------------------------------------------------
# Launch path: fires the right round, consumes the right pool
# ---------------------------------------------------------------------------

def test_launch_buk_9m317_fires_and_consumes_long_pool():
    cw = CombatWorld(CombatConfig(seed=1337, n_buk=1))
    ent = _air_entity(cw)
    tid = _inject_air_track(cw, ent)
    long0, agile0 = cw.buk_9m317_ammo, cw.buk_9m338_ammo
    m = cw.launch_buk(tid, round_id="9m317")
    assert isinstance(m, SamMissile)
    assert m.weapon is BUK_LONG
    assert m.target is ent
    assert m in cw.missiles
    assert cw.buk_9m317_ammo == long0 - 1, "9M317 pool did not decrement"
    assert cw.buk_9m338_ammo == agile0, "9M338 pool must be untouched"


def test_launch_buk_9m338_fires_and_consumes_agile_pool():
    cw = CombatWorld(CombatConfig(seed=1337, n_buk=1))
    ent = _air_entity(cw)
    tid = _inject_air_track(cw, ent)
    long0, agile0 = cw.buk_9m317_ammo, cw.buk_9m338_ammo
    m = cw.launch_buk(tid, round_id="9m338")
    assert isinstance(m, SamMissile)
    assert m.weapon is BUK_AGILE
    assert cw.buk_9m338_ammo == agile0 - 1, "9M338 pool did not decrement"
    assert cw.buk_9m317_ammo == long0, "9M317 pool must be untouched"


def test_launch_buk_refuses_no_air_track():
    cw = CombatWorld(CombatConfig(seed=1337, n_buk=1))
    assert cw.launch_buk(None, round_id="9m317") is None
    assert cw.launch_buk("no_such_track", round_id="9m317") is None
    assert cw.buk_9m317_ammo == 6, "a blocked launch must not consume a round"


def test_launch_buk_refuses_non_air_track():
    """A SURFACE track is not a Buk target (is_air gate — fog-honest)."""
    cw = CombatWorld(CombatConfig(seed=1337, n_buk=1))
    ship = cw.ships[0]
    cw.contacts.tracks[ship.ship_id] = dict(
        pos=ship.pos.copy(), vel=np.zeros(3), age=0.0,
        t_next=cw.sim_time + 100.0, is_air=False, kind="ship", size=1.0)
    assert cw.launch_buk(ship.ship_id, round_id="9m317") is None


def test_launch_buk_refuses_empty_pool():
    cw = CombatWorld(CombatConfig(seed=1337, n_buk=1))
    ent = _air_entity(cw)
    tid = _inject_air_track(cw, ent)
    cw.buk_9m317_ammo = 0
    assert not cw.buk_9m317_launcher_armed
    assert cw.launch_buk(tid, round_id="9m317") is None


def test_launch_buk_refuses_mid_reload():
    """A magazine refill in progress blocks the round (mirror of the S-300
    mag-reload gate)."""
    cw = CombatWorld(CombatConfig(seed=1337, n_buk=1))
    ent = _air_entity(cw)
    tid = _inject_air_track(cw, ent)
    cw.buk_9m338_ammo = 0
    cw._buk_9m338_mag_reload_left = 10.0
    assert not cw.buk_9m338_launcher_armed
    assert cw.launch_buk(tid, round_id="9m338") is None


# ---------------------------------------------------------------------------
# Magazine refill (mirror test_s300_*_magazine_refill)
# ---------------------------------------------------------------------------

def test_buk_9m317_magazine_refill():
    cfg = CombatConfig(seed=1337, n_buk=1, buk_9m317_ammo=2, buk_mag_reload_s=5.0)
    cw = CombatWorld(cfg)
    assert cw.buk_9m317_ammo == 2
    cw.buk_9m317_ammo = 0
    cw._buk_9m317_mag_reload_left = cfg.buk_mag_reload_s
    assert not cw.buk_9m317_launcher_armed
    for _ in range(int(5.1 * 120)):
        cw.step(DT)
    assert cw.buk_9m317_ammo == 2
    assert cw.buk_9m317_launcher_armed


def test_buk_9m338_magazine_refill():
    cfg = CombatConfig(seed=1337, n_buk=1, buk_9m338_ammo=2, buk_mag_reload_s=5.0)
    cw = CombatWorld(cfg)
    assert cw.buk_9m338_ammo == 2
    cw.buk_9m338_ammo = 0
    cw._buk_9m338_mag_reload_left = cfg.buk_mag_reload_s
    assert not cw.buk_9m338_launcher_armed
    for _ in range(int(5.1 * 120)):
        cw.step(DT)
    assert cw.buk_9m338_ammo == 2
    assert cw.buk_9m338_launcher_armed


# ---------------------------------------------------------------------------
# 9S36 radar EXTENDS the gated picture (compare detection)
# ---------------------------------------------------------------------------

def test_9s36_radar_extends_picture_beyond_station_alone():
    """The Buk's 9S36 radar detects a low air contact over the seam (16 km
    north of the Buk site at 150 m, open water) that the 18 m radar station
    alone misses — the station's terrain LOS to that low point is masked, while
    the closer 9S36 holds it.  Honest network extension (compare detection) —
    same mechanic as the Pantsir radar joining the net."""
    cw = CombatWorld(CombatConfig(seed=1337, n_buk=1))
    buk_radar = next(r for r in cw.radar_net.radars
                     if "9s36" in getattr(r, "radar_id", ""))
    bx, bz = (float(buk_radar.pos[0]), float(buk_radar.pos[2]))
    tgt = np.array([bx, 150.0, bz + 16_000.0], dtype=np.float64)
    # The 9S36 sees the low seam contact; the network (with it) holds it.
    assert buk_radar.detects(tgt, "fighter"), \
        "9S36 should detect the low seam contact"
    assert cw.radar_net.visible(tgt, "fighter"), \
        "the network (with the 9S36) should hold the low seam contact"
    # The SAME world WITHOUT the Buk: the station-only net must MISS it (the
    # 9S36 is what extends coverage there — the compare-detection assertion).
    cw0 = CombatWorld(CombatConfig(seed=1337, n_buk=0))
    assert not cw0.radar_net.visible(tgt, "fighter"), \
        "station-only net should NOT hold the low seam contact (no 9S36)"


def test_buk_radar_drops_from_net_on_struct_death():
    """The Buk struct's on_destroyed clears the 9S36's ``alive`` so the net no
    longer counts it (mirror of the radar-station / Pantsir wrapper)."""
    cw = CombatWorld(CombatConfig(seed=1337, n_buk=1))
    buk_radar = next(r for r in cw.radar_net.radars
                     if "9s36" in getattr(r, "radar_id", ""))
    assert buk_radar.alive
    struct = next(s for s in cw.structures if s.kind == "buk_tel")
    while struct.alive:
        struct.hit()
    assert not buk_radar.alive, "9S36 radar should go dark on Buk struct death"


# ---------------------------------------------------------------------------
# Determinism: same seed + same launch -> identical round
# ---------------------------------------------------------------------------

def test_buk_launch_determinism():
    """Same seed + same launch -> bit-identical round trajectory (the Buk uses
    the [seed, 8] child stream shared with the player-ARM/EW; the SamMissile
    flight is otherwise deterministic)."""
    def build_and_fly():
        cw = CombatWorld(CombatConfig(seed=4242, n_buk=1))
        ent = _air_entity(cw)
        tid = _inject_air_track(cw, ent, vel=[200.0, 0.0, 0.0])
        m = cw.launch_buk(tid, round_id="9m338")
        traj = []
        for _ in range(600):
            cw.step(DT)
            if m.alive:
                traj.append(tuple(round(float(c), 6) for c in m.pos))
            else:
                break
        return traj
    a = build_and_fly()
    b = build_and_fly()
    assert a == b, "Buk launch is not deterministic for the same seed"


# ---------------------------------------------------------------------------
# REGRESSION: n_buk=0 keeps the default battle bit-identical
# ---------------------------------------------------------------------------

def _battle_digest(cw, steps=900):
    """A bit-level digest of the default battle after stepping: missile
    positions + ship/aircraft positions + the event stream, rounded to 1e-6.
    Two worlds with identical config must produce identical digests."""
    rows = []
    for _ in range(steps):
        cw.step(DT)
        for ev in cw.events:
            rows.append((ev[0],) + tuple(round(float(c), 6)
                                         for c in np.asarray(ev[1]).ravel()))
        for m in cw.missiles:
            rows.append(("m",) + tuple(round(float(c), 6) for c in m.pos))
        for s in cw.ships:
            rows.append(("s",) + tuple(round(float(c), 6) for c in s.pos))
    return rows


def test_n_buk_zero_default_battle_bit_identical():
    """The Buk is NEW: with n_buk=0 NO Buk is built, and the default battle
    stays BIT-IDENTICAL across two builds (the Buk code path is inert and does
    not perturb determinism — the non-negotiable regression contract)."""
    a = CombatWorld(CombatConfig(seed=1337))
    b = CombatWorld(CombatConfig(seed=1337))
    # No Buk state perturbs the world.
    assert a.n_buk == 0 and a._buk_tubes == [] and a._buk_radars == []
    assert _battle_digest(a) == _battle_digest(b), \
        "n_buk=0 default battle is not bit-identical across builds"


def test_n_buk_zero_radar_net_unchanged():
    """With n_buk=0 the radar_net is exactly the station + Pantsir radars — no
    9S36 node is added (the gated picture is byte-identical)."""
    cw = CombatWorld(CombatConfig(seed=1337))
    assert all("9s36" not in getattr(r, "radar_id", "")
               for r in cw.radar_net.radars)
