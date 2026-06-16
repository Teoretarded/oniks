"""Emitter ELINT fix channel (M2-T1): heard enemy radars (AWACS / ground / SPY-1)
surface as localized EMITTER contacts in a SEPARATE SIGINT store
(world.emitter_contacts). contacts.tracks is left byte-identical."""

import numpy as np

from sim.recon import ELINT_FIX_ACTIONABLE_M
from world.combat import CombatWorld


def _cw():
    return CombatWorld()


def _awacs(w):
    aw = next((e for e in w.enemy_air if type(e).__name__ == "Awacs"), None)
    assert aw is not None, "default battle should field an AWACS"
    return aw


def _force_fix(w, eid, est, quality, heard_t):
    w.elint.heard_emitters = lambda: [eid]
    w.elint.last_heard = lambda e: heard_t
    w.elint.fix_quality = lambda e: quality
    w.elint.est_pos = lambda e: np.asarray(est, dtype=float)


def test_player_targetable_emitters_includes_awacs_and_ground():
    w = _cw()
    tgt = w._player_targetable_emitters()
    aw = _awacs(w)
    assert aw.radar.radar_id in tgt
    _kind, radar, _owner = tgt[aw.radar.radar_id]
    assert radar is aw.radar                      # resolves to the live Radar
    for r in w._enemy_ground_radars:
        assert r.radar_id in tgt


def test_elint_surfaces_awacs_emitter_when_actionable():
    w = _cw()
    aw = _awacs(w)
    eid = aw.radar.radar_id
    _force_fix(w, eid, aw.radar.pos, ELINT_FIX_ACTIONABLE_M * 0.2, w.sim_time)
    w._inject_emitter_contacts(w.sim_time)
    assert eid in w.emitter_contacts
    c = w.emitter_contacts[eid]
    err = float(np.hypot(c["pos"][0] - aw.radar.pos[0],
                         c["pos"][2] - aw.radar.pos[2]))
    assert err < ELINT_FIX_ACTIONABLE_M          # estimate near truth


def test_emitter_fix_only_when_actionable():
    w = _cw()
    aw = _awacs(w)
    eid = aw.radar.radar_id
    _force_fix(w, eid, aw.radar.pos, ELINT_FIX_ACTIONABLE_M * 2.0, w.sim_time)
    w._inject_emitter_contacts(w.sim_time)        # fix too poor to be actionable
    assert eid not in w.emitter_contacts


def test_emitter_ages_out_when_silent():
    w = _cw()
    aw = _awacs(w)
    eid = aw.radar.radar_id
    _force_fix(w, eid, aw.radar.pos, ELINT_FIX_ACTIONABLE_M * 0.2, w.sim_time)
    w._inject_emitter_contacts(w.sim_time)
    assert eid in w.emitter_contacts
    w.elint.heard_emitters = lambda: []           # emitter goes silent
    w._inject_emitter_contacts(w.sim_time + 100.0)
    assert eid not in w.emitter_contacts


def test_contacts_tracks_untouched_by_emitter_channel():
    w = _cw()
    aw = _awacs(w)
    eid = aw.radar.radar_id
    before = {k: dict(v) for k, v in w.contacts.tracks.items()}
    _force_fix(w, eid, aw.radar.pos, ELINT_FIX_ACTIONABLE_M * 0.2, w.sim_time)
    w._inject_emitter_contacts(w.sim_time)
    after = {k: dict(v) for k, v in w.contacts.tracks.items()}
    assert after == before                        # SIGINT store is separate


def test_determinism_emitter_contacts_same_seed():
    w1, w2 = _cw(), _cw()
    for _ in range(1200):                          # ~10 s of stepping
        w1.step(1 / 120.0)
        w2.step(1 / 120.0)
    assert set(w1.emitter_contacts) == set(w2.emitter_contacts)
    for eid in w1.emitter_contacts:
        assert np.array_equal(w1.emitter_contacts[eid]["pos"],
                              w2.emitter_contacts[eid]["pos"])
