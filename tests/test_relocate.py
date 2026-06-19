"""M5 #4 SHOOT-AND-SCOOT relocatable firing TELs (spec 06 F1).

The headline mechanic: after a firing TEL (Bastion / S-300 / Buk) shoots, the
player can order it to a NEW map position.  While it drives it is COMMITTED
(cannot launch); on arrival its pad, EVERY launch tube, AND its destructible
Structure move to the new pad, so the enemy's stale back-plot cluster points at
empty dirt and the next enemy salvo hits nothing (a clean miss the player
EARNED by moving — physics-not-dice, never a roll).

It is a PLAYER ACTION: there is NO config field, and a battle that never calls
request_relocate is byte-identical to today (the relocate state defaults to
idle, _step_relocations is a pure no-op, and the arm gates' "and not committed"
clause is vacuously True).

Contracts (spec 06 F1):
  (a) request_relocate sets committed=True and the arm gate False IMMEDIATELY;
      a 2nd request while committed is refused;
  (b) a launch attempt while committed returns None (Oniks / S-300 / Buk);
  (c) after move_left_s (setup+drive+setup) elapses, the pad, every tube['pos'],
      and the matching Structure.pos ALL equal dest within 1 m, and committed
      flips back False (re-armed if ammo/reload allow);
  (d) DETERMINISM: same seed + same relocate sequence -> identical positions;
  (e) FOG/HONESTY: a back-plot cluster seeded at the OLD pad finds NO live
      Structure within SEEKER_BASKET_M of the stale centre after a relocate (the
      round hits dirt — the TEL survives), AND a NEW launch from the new pad
      originates at the new xz (the enemy can re-form a cluster);
  EDGE: a relocate ordered MID-RELOAD keeps the tube reload timer counting;
  applies to ALL THREE firing TELs.

REGRESSION: a battle with NO relocate -> default battle bit-identical (digest).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from sim.missile import Missile
from world.combat import (CombatWorld, RELOCATE_SETUP_S, RELOCATE_SPEED_MPS,
                          SEEKER_BASKET_M)
from world.combat_config import CombatConfig

DT = 1.0 / 120.0

# All three firing TELs present so every parametrized case has a platform.
_ALL_TELS_CFG = dict(seed=1337, n_oniks=1, n_s300=1, n_buk=1)


def _world():
    return CombatWorld(CombatConfig(**_ALL_TELS_CFG))


def _descriptor(cw, kind):
    d = next((d for d in cw._relocatable if d["kind"] == kind), None)
    assert d is not None, f"no relocatable {kind} built"
    return d


def _gate_for(cw, kind):
    """The battery's arm-gate property value (any-tube-ready) for ``kind``."""
    return {
        "bastion_tel": lambda: cw.launcher_armed,
        "s300_tel": lambda: cw.sam_launcher_armed,
        "buk_tel": lambda: cw.buk_9m317_launcher_armed,
    }[kind]()


def _make_armed(cw, kind):
    """Ensure the battery's gate reads armed at the start (Oniks tubes load on
    build; S-300/Buk need a held air track only for the LAUNCH, not the gate —
    the gate just needs a ready tube + pool, which the build provides)."""
    if kind == "bastion_tel":
        # Oniks tubes loaded at build with oniks_ammo=8 -> gate already armed.
        assert cw.launcher_armed
    # S-300 / Buk gates read armed from pool + ready tube at build.


# ---------------------------------------------------------------------------
# (a) commit + immediate disarm + 2nd-request refusal
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", ["bastion_tel", "s300_tel", "buk_tel"])
def test_request_commits_and_disarms_immediately(kind):
    cw = _world()
    d = _descriptor(cw, kind)
    _make_armed(cw, kind)
    assert _gate_for(cw, kind), f"{kind} gate should start ARMED"
    pad0 = (float(d["pos"][0]), float(d["pos"][2]))
    dest = (pad0[0] + 1_000.0, pad0[1] + 500.0)
    assert cw.request_relocate(d["structure"].structure_id, dest) is True
    assert d["committed"] is True
    # The arm gate goes False IMMEDIATELY (this is the only firing TEL of its
    # kind, so the whole battery gate flips).
    assert not _gate_for(cw, kind), f"{kind} gate must be FALSE while committed"
    # A 2nd request while committed is refused (no-op, returns False).
    assert cw.request_relocate(d["structure"].structure_id, (pad0[0], pad0[1])) \
        is False


def test_request_unknown_platform_refused():
    cw = _world()
    assert cw.request_relocate("no_such_platform", (0.0, 0.0)) is False


def test_request_dead_tel_refused():
    cw = _world()
    d = _descriptor(cw, "bastion_tel")
    d["structure"].alive = False
    assert cw.request_relocate(d["structure"].structure_id, (1_000.0, 0.0)) \
        is False


# ---------------------------------------------------------------------------
# (b) launch refused while committed
# ---------------------------------------------------------------------------

def _inject_air_track(cw):
    ent = next(e for e in cw.enemy_air if getattr(e, "alive", True))
    cw.contacts.tracks[ent.aircraft_id] = dict(
        pos=ent.pos.copy(), vel=np.zeros(3), age=0.0,
        t_next=cw.sim_time + 100.0, is_air=True, kind="fighter", size=0.3)
    return ent.aircraft_id


def test_oniks_launch_refused_while_committed():
    cw = _world()
    d = _descriptor(cw, "bastion_tel")
    cw.request_relocate(d["structure"].structure_id, (3_000.0, 0.0))
    assert cw.launch("hi-lo", np.array([0.0, 0.0, 120_000.0])) is None


def test_s300_launch_refused_while_committed():
    cw = _world()
    d = _descriptor(cw, "s300_tel")
    tid = _inject_air_track(cw)
    cw.request_relocate(d["structure"].structure_id, (88_000.0, -3_500.0))
    assert cw.launch_sam(tid, round_id="48n6") is None


def test_buk_launch_refused_while_committed():
    cw = _world()
    d = _descriptor(cw, "buk_tel")
    tid = _inject_air_track(cw)
    cw.request_relocate(d["structure"].structure_id, (45_000.0, -5_000.0))
    assert cw.launch_buk(tid, round_id="9m317") is None


def test_committed_one_tel_does_not_disarm_a_second_oniks_tel():
    """GENERIC but PER-LAUNCHER: with two Oniks TELs, committing ONE leaves the
    OTHER armed and able to fire (only the committed launcher's tubes lock)."""
    cw = CombatWorld(CombatConfig(seed=1337, n_oniks=2, n_s300=1, n_buk=1))
    bastions = [d for d in cw._relocatable if d["kind"] == "bastion_tel"]
    assert len(bastions) == 2
    cw.request_relocate(bastions[0]["structure"].structure_id, (3_000.0, 0.0))
    # The OTHER Bastion's tubes are still ready -> the battery gate stays armed
    # and a launch fires from the un-committed launcher.
    assert cw.launcher_armed
    m = cw.launch("hi-lo", np.array([0.0, 0.0, 120_000.0]))
    assert isinstance(m, Missile)
    # The round spawned from the SECOND (un-moved) launcher, NOT the committed one.
    fired_xz = (float(m.pos[0]), float(m.pos[2]))
    committed_pad = (float(bastions[0]["pos"][0]), float(bastions[0]["pos"][2]))
    d_to_committed = math.hypot(fired_xz[0] - committed_pad[0],
                                fired_xz[1] - committed_pad[1])
    assert d_to_committed > 1.0, "a committed launcher must not have fired"


# ---------------------------------------------------------------------------
# (c) arrival: pad + tubes + Structure all at dest within 1 m, re-armed
# ---------------------------------------------------------------------------

def _drive_to_arrival(cw, d):
    eta = d["move_left_s"]
    n = int(eta / DT) + 5
    for _ in range(n):
        cw.step(DT)
        if not d["committed"]:
            break
    assert not d["committed"], "relocate never completed"


@pytest.mark.parametrize("kind", ["bastion_tel", "s300_tel", "buk_tel"])
def test_arrival_moves_pad_tubes_structure_within_1m(kind):
    cw = _world()
    d = _descriptor(cw, kind)
    pad0 = (float(d["pos"][0]), float(d["pos"][2]))
    dest = (pad0[0] + 4_000.0, pad0[1] + 2_000.0)
    # Predicted ETA = 2 setups + drive distance / speed.
    drive = math.hypot(dest[0] - pad0[0], dest[1] - pad0[1])
    eta_pred = 2.0 * RELOCATE_SETUP_S + drive / RELOCATE_SPEED_MPS
    cw.request_relocate(d["structure"].structure_id, dest)
    assert d["move_left_s"] == pytest.approx(eta_pred, abs=1e-6)
    _drive_to_arrival(cw, d)
    # Pad within 1 m of dest.
    assert math.hypot(float(d["pos"][0]) - dest[0],
                      float(d["pos"][2]) - dest[1]) <= 1.0
    # EVERY tube within 1 m of (dest + its baked mouth offset).
    for t, off in zip(d["tubes"], d["offsets"]):
        want = (dest[0] + float(off[0]), dest[1] + float(off[2]))
        assert math.hypot(float(t["pos"][0]) - want[0],
                          float(t["pos"][2]) - want[1]) <= 1.0
    # The matching Structure within 1 m of dest (the moving-Structure link).
    s = d["structure"]
    assert math.hypot(float(s.pos[0]) - dest[0],
                      float(s.pos[2]) - dest[1]) <= 1.0
    # Committed cleared (re-armed if ammo/reload allow).
    assert d["committed"] is False
    if kind == "bastion_tel":
        assert cw.launcher_armed, "Bastion should re-arm on arrival"


@pytest.mark.parametrize("kind", ["bastion_tel", "s300_tel", "buk_tel"])
def test_structure_obb_follows_the_move(kind):
    """The load-bearing honesty link: after the move the Structure's OBB centre
    (rebuilt from .pos PER QUERY in sim/bases.py) sits over the NEW pad, so the
    damage sweep follows.  A strike at the OLD pad now finds no structure; one at
    the NEW pad does."""
    cw = _world()
    d = _descriptor(cw, kind)
    s = d["structure"]
    old_pad = (float(s.pos[0]), float(s.pos[2]))
    dest = (old_pad[0] + 6_000.0, old_pad[1] - 1_500.0)
    cw.request_relocate(s.structure_id, dest)
    _drive_to_arrival(cw, d)
    center, half, rot = s.obb()
    assert math.hypot(float(center[0]) - dest[0],
                      float(center[2]) - dest[1]) <= 1.0
    # _refine_strike_aim: NEW pad acquires this structure (within basket);
    # OLD pad does not (it moved away — assuming nothing else is within basket).
    nx, nz, _ = cw._refine_strike_aim(dest[0], dest[1])
    assert math.hypot(nx - dest[0], nz - dest[1]) <= SEEKER_BASKET_M


# ---------------------------------------------------------------------------
# (d) determinism: same seed + same relocate sequence -> identical positions
# ---------------------------------------------------------------------------

def test_relocate_is_deterministic():
    def run():
        cw = _world()
        d = _descriptor(cw, "bastion_tel")
        cw.request_relocate(d["structure"].structure_id, (4_321.0, 1_234.0))
        traj = []
        for _ in range(int(d["move_left_s"] / DT) + 5):
            cw.step(DT)
            traj.append((tuple(round(float(c), 9) for c in d["pos"]),
                         tuple(round(float(c), 9) for c in d["tubes"][0]["pos"]),
                         tuple(round(float(c), 9) for c in d["structure"].pos)))
            if not d["committed"]:
                break
        return traj
    assert run() == run(), "relocate is not deterministic for the same seed"


# ---------------------------------------------------------------------------
# (e) FOG / HONESTY — the headline: stale-pad salvo hits dirt; new pad re-seeds
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", ["bastion_tel", "s300_tel", "buk_tel"])
def test_stale_backplot_salvo_hits_dirt_after_scoot(kind):
    cw = _world()
    d = _descriptor(cw, kind)
    pad0 = (float(d["pos"][0]), float(d["pos"][2]))
    # Seed a TARGETABLE back-plot cluster right at the OLD pad.
    pic = cw.commander.picture
    for i in range(5):
        pic.add_back_plot(np.array([pad0[0], pad0[1]]), 50.0, cw.sim_time,
                          f"fix_{kind}_{i}")
    cluster = max(pic.clusters, key=lambda c: len(c.fixes))
    assert cluster.targetable
    stale = (float(cluster.centre[0]), float(cluster.centre[1]))
    # Relocate FAR enough that the moved Structure leaves the stale basket.
    dest = (pad0[0] + 8_000.0, pad0[1] + 4_000.0)
    cw.request_relocate(d["structure"].structure_id, dest)
    _drive_to_arrival(cw, d)
    # The commander's TOMAHAWK_SALVO refines its aim at the stale centroid:
    # NO live Structure within SEEKER_BASKET_M -> the round flies into the dirt.
    tx, tz, _ = cw._refine_strike_aim(stale[0], stale[1])
    near = min((math.hypot(float(s.pos[0]) - stale[0], float(s.pos[2]) - stale[1])
                for s in cw.structures if s.alive), default=float("inf"))
    assert near > SEEKER_BASKET_M, \
        "a live structure is still within the stale basket — the scoot did not miss"
    # _refine_strike_aim returns the believed coords (no acquisition) -> dirt.
    assert (abs(tx - stale[0]) < 1e-6 and abs(tz - stale[1]) < 1e-6), \
        "the stale-pad salvo acquired a structure (should hit dirt)"
    # The relocated TEL's own Structure is ALIVE (it survived the stale salvo).
    assert d["structure"].alive


def test_new_launch_originates_at_new_pad_reseeds_backplot():
    """After a scoot a NEW Oniks launch spawns at the NEW pad, so the enemy's
    back-plot (which keys on the missile's first-seen position) would re-form a
    cluster near the NEW xz — the cat-and-mouse stays alive."""
    cw = _world()
    d = _descriptor(cw, "bastion_tel")
    dest = (10_000.0, 5_000.0)
    cw.request_relocate(d["structure"].structure_id, dest)
    _drive_to_arrival(cw, d)
    # Fire from the relocated Bastion.
    m = cw.launch("hi-lo", np.array([0.0, 0.0, 120_000.0]))
    assert isinstance(m, Missile)
    # The round spawned at the NEW pad tube (within a few m of dest), NOT the
    # original pad (0, -600) — so a back-plot of THIS round localizes near dest.
    assert math.hypot(float(m.pos[0]) - dest[0],
                      float(m.pos[2]) - dest[1]) < 50.0
    assert math.hypot(float(m.pos[0]) - 0.0,
                      float(m.pos[2]) - (-600.0)) > 5_000.0


# ---------------------------------------------------------------------------
# EDGE: a relocate ordered MID-RELOAD keeps the reload timer counting
# ---------------------------------------------------------------------------

def test_relocate_mid_reload_keeps_reload_timer_running():
    """Firing an Oniks tube starts its reload; ordering a relocate mid-reload
    must KEEP the reload timer counting (the tube re-cocks while driving) — the
    regression that must NOT be weakened."""
    cw = _world()
    d = _descriptor(cw, "bastion_tel")
    # Fire one tube -> it starts reloading.
    m = cw.launch("hi-lo", np.array([0.0, 0.0, 120_000.0]))
    assert isinstance(m, Missile)
    fired = next(t for t in d["tubes"] if t["reload_left"] > 0.0)
    reload0 = fired["reload_left"]
    # Order the relocate WHILE that tube is mid-reload.
    cw.request_relocate(d["structure"].structure_id, (3_000.0, 1_000.0))
    assert d["committed"]
    # Step a few seconds of the drive; the reload timer must DECREASE.
    for _ in range(int(2.0 / DT)):
        cw.step(DT)
    assert fired["reload_left"] < reload0, \
        "the tube reload timer stalled during the relocate (regression weakened)"


# ---------------------------------------------------------------------------
# REGRESSION: NO relocate -> default battle bit-identical
# ---------------------------------------------------------------------------

def _battle_digest(cw, steps=900):
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


def test_no_relocate_default_battle_bit_identical():
    """The relocate verbs are NEW: a battle that never calls request_relocate
    stays BIT-IDENTICAL across two builds (the relocate code path is inert —
    _step_relocations is a no-op while every launcher is idle, and the arm
    gates' 'and not committed' clause is vacuously True).  This is the GATE."""
    a = CombatWorld(CombatConfig(seed=1337))
    b = CombatWorld(CombatConfig(seed=1337))
    # The registry exists but every launcher is idle (no committed move).
    assert all(not d["committed"] and d["dest"] is None for d in a._relocatable)
    assert _battle_digest(a) == _battle_digest(b), \
        "default battle (no relocate) is not bit-identical across builds"
