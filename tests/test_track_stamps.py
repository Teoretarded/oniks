"""track['kind'] / track['size'] stamps on ContactBoard tracks (M1-F2).

These are the cross-cutting dependency the threat strip + contact-intel panel
read. They are NOT a fog-of-war leak: ``size`` is the radar size class (the same
provenance ``_seen`` already uses to GATE detection) and ``kind`` is the weapon
classification (surfaced behind the panel's ID-confidence ladder). The stamps
are ADDITIVE — every existing track key and the dead-reckoned estimate are
unchanged.
"""

import numpy as np

from sim.contacts import ContactBoard


class _Ent:
    """Minimal entity duck-typed for ContactBoard.update()."""

    def __init__(self, eid, pos, *, is_air=False, radar_size=None,
                 weapon_id=None, vel=(0.0, 0.0, 0.0)):
        self.ship_id = eid
        self.aircraft_id = eid
        self.is_air = is_air
        self.pos = np.asarray(pos, dtype=np.float64)
        self._v = np.asarray(vel, dtype=np.float64)
        self.alive = True
        if radar_size is not None:
            self.radar_size = radar_size
        if weapon_id is not None:
            self.weapon = type("_W", (), {"weapon_id": weapon_id})()

    def velocity(self):
        return self._v


def _board():
    # visible_fn=None -> ungated (sandbox): a track forms on the first update.
    return ContactBoard(base_xz=(0.0, 0.0))


def test_ship_track_size_is_ship_and_kind_is_none():
    b = _board()
    b.update([_Ent("ship_0", (1000.0, 0.0, 1000.0))], 0.1, 0.1)
    t = b.tracks["ship_0"]
    assert t["size"] == "ship"
    assert t["kind"] is None            # a platform carries no weapon kind


def test_air_track_size_is_fighter():
    b = _board()
    b.update([_Ent("air_0", (1000.0, 9000.0, 1000.0), is_air=True)], 0.1, 0.1)
    assert b.tracks["air_0"]["size"] == "fighter"


def test_missile_track_size_and_kind():
    b = _board()
    e = _Ent("m_0", (500.0, 50.0, 500.0), is_air=True,
             radar_size="missile", weapon_id="tomahawk")
    b.update([e], 0.1, 0.1)
    t = b.tracks["m_0"]
    assert t["size"] == "missile"
    assert t["kind"] == "tomahawk"


def test_stamps_are_additive_estimate_and_keys_unchanged():
    b = _board()
    e = _Ent("ship_1", (2000.0, 0.0, 0.0), vel=(10.0, 0.0, 0.0))
    b.update([e], 0.0, 0.0)
    # Original keys all still present.
    t = b.tracks["ship_1"]
    for k in ("pos", "vel", "age", "t_next", "is_air"):
        assert k in t
    # Dead-reckoned estimate behaves exactly as before (age 0 -> last fix).
    assert np.allclose(b.estimated_pos("ship_1", 0.0), e.pos)


def test_elint_injected_ship_track_carries_stamps():
    """The THIRD track-creation site (_inject_elint_tracks) must stamp too, so
    the 'every track carries kind/size' invariant holds for ELINT ship fixes."""
    from world.combat import CombatWorld
    cw = CombatWorld()                       # DEFAULT config
    ship = cw.ships[0]
    eid = ship.radar.radar_id
    # Force one actionable, fresh ELINT fix for this ship's emitter.
    cw.elint.heard_emitters = lambda: [eid]
    cw.elint.last_heard = lambda e: cw.sim_time
    cw.elint.fix_quality = lambda e: 1.0     # metres, well under actionable
    cw.elint.est_pos = lambda e: ship.pos.copy()
    cw._inject_elint_tracks(cw.sim_time)
    t = cw.contacts.tracks[ship.ship_id]
    assert t["size"] == "ship"               # a hull is surface/ship class
    assert t["kind"] is None                 # a platform carries no weapon kind
