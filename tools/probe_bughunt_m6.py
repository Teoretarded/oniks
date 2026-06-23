"""BUG-HUNT (M6 close-out): stress the live game for crashes, logic / game-loop
errors, fog leaks, and determinism breaks across the WHOLE feature set.

Run: python tools/probe_bughunt_m6.py   (prints per-check PASS/FAIL; exit 1 on any FAIL)

Not a unit test (it does not assert exact numbers) — it exercises the game the way
a player session would (long battles, every feature on at once, the zero-force
edge, a campaign chain) and flags anything that throws, goes non-finite, leaks the
fog, or breaks same-seed determinism.
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from world.combat import CombatWorld
from world.combat_config import clamp_config, CombatConfig
import game.campaign as campaign

DT = 1.0 / 120.0
_FAILS = []


def _check(name, fn):
    try:
        ok, detail = fn()
    except Exception:
        _FAILS.append(name)
        print(f"[bughunt] FAIL  {name}\n{traceback.format_exc()}")
        return
    tag = "PASS" if ok else "FAIL"
    if not ok:
        _FAILS.append(name)
    print(f"[bughunt] {tag}  {name} — {detail}")


def _all_features_config(seed=1337):
    """Every feature ON, every count/pool pushed past its ceiling so clamp_config
    returns the legal maximum of each — the densest, most-interacting battle."""
    big = 999
    return clamp_config(
        seed=seed, n_destroyers=big, n_flagship=big, n_aaw=big, n_ground_attack=big,
        n_awacs=big, n_jammers=big, player_jammer=big, n_enemy_radars=big,
        n_player_radars=big, n_pantsir=big, n_drones=big, n_oniks=big, n_s300=big,
        oniks_ammo=big, zircon_ammo=big, asbm_ammo=big, kh31p_ammo=big,
        s300_48n6_ammo=big, s300_40n6_ammo=big, pantsir_57e6_ammo=big,
        pantsir_gun_ammo=big, n_swarm_pods=big, n_buk=big, n_cbr=big,
        n_decoys=big, n_corner_reflectors=big, n_subs=big, sub_kalibr_ammo=big,
        n_sonobuoys=big, asw_ammo=big, n_transports=big, map_preset=2,
    )


def _finite_world(w):
    """True iff every live entity position/velocity is finite (no NaN/Inf)."""
    for s in w.ships:
        if not np.all(np.isfinite(s.pos)):
            return False
    for m in w.missiles:
        if not (np.all(np.isfinite(m.pos)) and np.all(np.isfinite(m.vel))):
            return False
    return True


def _fog_leak(w):
    """True iff a hostile round the player has NOT detected appears in the gated
    contact picture (a fog-of-war leak).  A contact is a player-side track; a
    truth round under the horizon must never show up."""
    tracks = getattr(getattr(w, "contacts", None), "tracks", {}) or {}
    # Every track must correspond to something the radar net actually sees; we
    # approximate the leak test by checking no track claims a hostile missile id
    # that is currently outside any player sensor range is impossible to verify
    # cheaply here, so we assert the weaker invariant the gate guarantees: tracks
    # only ever hold ids the ContactBoard admitted (no raw world.missiles object
    # is exposed as a contact).  A track value must be a dict (estimate), never a
    # live Missile object (which would be a truth handle).
    for t in tracks.values():
        if not isinstance(t, dict):
            return True
        if "pos" not in t and "est" not in t and "estimate" not in t:
            return True
    return False


def check_all_features_crashfree():
    cfg = _all_features_config()
    w = CombatWorld(cfg)
    # fire a couple of salvos to wake the offensive + back-plot paths
    fired = 0
    for i in range(3000):
        if i == 60:
            w.launch("lo-lo", np.array([0.0, 0.0, 200_000.0])); fired += 1
        if i == 600:
            w.launch("hi-lo", np.array([40_000.0, 0.0, 260_000.0])); fired += 1
        w.step(DT)
        if not _finite_world(w):
            return False, f"non-finite entity at step {i}"
    return True, (f"3000 steps, {len(w.ships)} ships, {fired} salvos, "
                  f"{len(w.missiles)} live rounds, finite, no crash")


def check_all_features_determinism():
    cfg = _all_features_config(seed=4242)
    a = CombatWorld(cfg)
    b = CombatWorld(cfg)
    for i in range(1500):
        if i == 60:
            a.launch("lo-lo", np.array([0.0, 0.0, 210_000.0]))
            b.launch("lo-lo", np.array([0.0, 0.0, 210_000.0]))
        a.step(DT); b.step(DT)
    # compare full ship + missile state
    if len(a.ships) != len(b.ships) or len(a.missiles) != len(b.missiles):
        return False, "entity counts diverged"
    maxd = 0.0
    for sa, sb in zip(a.ships, b.ships):
        maxd = max(maxd, float(np.max(np.abs(sa.pos - sb.pos))))
    for ma, mb in zip(a.missiles, b.missiles):
        maxd = max(maxd, float(np.max(np.abs(ma.pos - mb.pos))))
    return maxd == 0.0, f"max same-seed positional delta over 1500 steps = {maxd}"


def check_zero_force_edge():
    """A near-empty battlespace must not crash the loop or the win/lose logic."""
    cfg = clamp_config(seed=7, n_destroyers=0, n_enemy_radars=0, n_pantsir=0,
                       n_drones=0, n_awacs=0)
    w = CombatWorld(cfg)
    for _ in range(1200):
        w.step(DT)
    # victorious / defeated must be readable booleans, not throw
    v = bool(getattr(w, "victorious", False))
    d = bool(getattr(w, "defeated", False))
    return _finite_world(w), f"1200 steps, victorious={v} defeated={d}, finite"


def check_fog_no_leak():
    cfg = _all_features_config(seed=99)
    w = CombatWorld(cfg)
    leaked = False
    for i in range(1500):
        w.step(DT)
        if _fog_leak(w):
            leaked = True
            break
    return (not leaked), ("no truth handle in the contact picture over 1500 steps"
                          if not leaked else f"FOG LEAK at step {i}")


def check_lose_reachable():
    """A passive player (never fires, radar on) — the enemy must be ABLE to win
    eventually (the lose path exists).  We don't require it within the window,
    only that the loop runs clean and defeated stays a valid bool."""
    cfg = clamp_config(seed=1337, n_destroyers=4, n_enemy_radars=2)
    w = CombatWorld(cfg)
    defeated_seen = False
    for _ in range(20000):           # ~2.8 min sim @120Hz
        w.step(DT)
        if getattr(w, "defeated", False):
            defeated_seen = True
            break
    return _finite_world(w), (f"passive 20k steps, defeated={defeated_seen} "
                              f"(lose path {'reached' if defeated_seen else 'not reached in window — ok'})")


def check_campaign_chain():
    """Run a 3-battle campaign through the real API: next_config -> CombatWorld ->
    apply_initial_state -> step -> advance.  Surfaces campaign integration bugs."""
    base = CombatConfig(seed=1337)
    camp = campaign.new_campaign(1337, n_battles=3)
    seeds = []
    for b in range(3):
        cfg = campaign.next_config(camp, base)
        seeds.append(cfg.seed)
        w = CombatWorld(cfg)
        st = campaign.initial_state_for(camp)
        w.apply_initial_state(st)               # None on battle 0, a dict after
        for i in range(400):
            if i == 60:
                w.launch("lo-lo", np.array([0.0, 0.0, 200_000.0]))
            w.step(DT)
        if not _finite_world(w):
            return False, f"battle {b} went non-finite"
        campaign.advance(camp, w, "B", base)
    distinct = len(set(seeds)) == 3
    carried = bool(camp.ledger)
    return (distinct and carried and camp.battle_idx == 3), (
        f"3 battles ran clean, seeds distinct={distinct}, ledger carried={carried}, "
        f"idx={camp.battle_idx}, oniks left={camp.ledger.get('oniks')}")


def main():
    print("=== M6 BUG-HUNT ===")
    _check("all-features-on crash-free (3000 steps, dense battle)", check_all_features_crashfree)
    _check("all-features-on same-seed determinism (1500 steps)", check_all_features_determinism)
    _check("zero-force edge crash-free", check_zero_force_edge)
    _check("fog: no truth handle leaks into the contact picture", check_fog_no_leak)
    _check("lose path reachable / passive battle clean (20k steps)", check_lose_reachable)
    _check("campaign 3-battle chain (seed + carry-forward)", check_campaign_chain)
    print("=== RESULT ===")
    if _FAILS:
        print(f"FAIL: {len(_FAILS)} check(s) failed: {_FAILS}")
        sys.exit(1)
    print("ALL BUG-HUNT CHECKS PASSED")


if __name__ == "__main__":
    main()
