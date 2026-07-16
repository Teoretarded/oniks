"""Tests for sim/bases.py — destructible player base structures.

GL-free. No imports from engine/, game/, or world/ modules.
"""

import numpy as np
import pytest

from sim.bases import (
    HP_BASTION_TEL,
    HP_RADAR_STATION,
    HP_S300_TEL,
    Structure,
    apply_missile_hits_structures,
)
from sim.missile import PH_DEAD


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_structure(kind="bastion_tel", pos=None, hp=None, on_destroyed=None):
    """Return a Structure at the given world position (default origin)."""
    if pos is None:
        pos = np.array([0.0, 0.0, 0.0], dtype=np.float64)
    return Structure(
        structure_id="test_" + kind,
        kind=kind,
        pos=np.asarray(pos, dtype=np.float64),
        hp=hp,
        on_destroyed=on_destroyed,
    )


class _FakeMissile:
    """Minimal duck-type for a live missile with prev_pos / pos."""

    def __init__(self, prev_pos, pos):
        self.prev_pos = np.asarray(prev_pos, dtype=np.float64)
        self.pos = np.asarray(pos, dtype=np.float64)
        self.alive = True
        self.phase = None        # will be set to PH_DEAD on hit
        self.impact_pos = None


# ---------------------------------------------------------------------------
# Default HP and dims
# ---------------------------------------------------------------------------

class TestDefaults:
    def test_bastion_tel_hp(self):
        s = _make_structure("bastion_tel")
        assert s.hp == HP_BASTION_TEL == 2

    def test_s300_tel_hp(self):
        s = _make_structure("s300_tel")
        assert s.hp == HP_S300_TEL == 2

    def test_radar_station_hp(self):
        s = _make_structure("radar_station")
        assert s.hp == HP_RADAR_STATION == 1

    def test_dims_set_for_tel(self):
        s = _make_structure("bastion_tel")
        length, beam, height = s.dims
        assert length > 0 and beam > 0 and height > 0

    def test_dims_set_for_radar(self):
        s = _make_structure("radar_station")
        # radar tower must reach at least 20 m (spec mentions ~22 m)
        _length, _beam, height = s.dims
        assert height >= 20.0

    def test_alive_on_construction(self):
        s = _make_structure()
        assert s.alive is True

    def test_tel_obb_uses_beam_on_x_and_length_on_z(self):
        s = _make_structure("bastion_tel")
        _center, half, _rot = s.obb()
        length, beam, height = s.dims
        assert half == pytest.approx((beam * 0.5, height * 0.5,
                                      length * 0.5))


# ---------------------------------------------------------------------------
# Structure.hit()
# ---------------------------------------------------------------------------

class TestHit:
    def test_first_hit_decrements_hp(self):
        s = _make_structure("bastion_tel")
        assert s.hp == 2
        s.hit()
        assert s.hp == 1
        assert s.alive is True

    def test_second_hit_kills(self):
        s = _make_structure("bastion_tel")
        s.hit()
        s.hit()
        assert s.hp == 0
        assert s.alive is False

    def test_radar_one_hit_kills(self):
        s = _make_structure("radar_station")
        assert s.hp == 1
        s.hit()
        assert s.alive is False

    def test_hit_on_dead_is_noop(self):
        s = _make_structure("radar_station")
        s.hit()                    # kills it
        s.hit()                    # second hit must not raise or go below 0
        assert s.hp == 0
        assert s.alive is False


# ---------------------------------------------------------------------------
# on_destroyed callback
# ---------------------------------------------------------------------------

class TestOnDestroyedCallback:
    def test_callback_fires_once_at_kill(self):
        calls = []
        s = _make_structure("bastion_tel",
                             on_destroyed=lambda st: calls.append(st))
        s.hit()              # first hit — still alive
        assert calls == []
        s.hit()              # kill
        assert len(calls) == 1
        assert calls[0] is s

    def test_callback_not_fired_on_subsequent_dead_hits(self):
        calls = []
        s = _make_structure("radar_station",
                             on_destroyed=lambda st: calls.append(st))
        s.hit()              # kill
        s.hit()              # dead hit
        assert len(calls) == 1

    def test_callback_receives_correct_structure(self):
        received = []
        s = _make_structure("s300_tel",
                             on_destroyed=lambda st: received.append(st))
        s.hit(); s.hit()
        assert received[0] is s


# ---------------------------------------------------------------------------
# apply_missile_hits_structures — direct hit registers
# ---------------------------------------------------------------------------

class TestApplyMissileHitsStructures:

    # Position missile segment to cross through the structure OBB.
    # Bastion TEL at origin: half-extents are (7, 3, 1.75) m in local X/Y/Z.
    # A missile flying straight through the long axis (Z direction) at Y=3 m
    # (inside the 6 m height OBB since centre is at Y=3, half=3) passes inside.

    def _direct_hit_missile(self, s: Structure):
        """Return a missile that travels through the structure's centre OBB."""
        cx = float(s.pos[0])
        cy = float(s.pos[1]) + s.dims[2] * 0.5   # OBB centre height
        cz = float(s.pos[2])
        half_length = s.dims[0] * 0.5
        # prev_pos is 2 m before the start face; pos is 2 m past the end face
        prev_pos = np.array([cx, cy, cz - half_length - 2.0])
        pos = np.array([cx, cy, cz + half_length + 2.0])
        return _FakeMissile(prev_pos, pos)

    def test_direct_hit_missile_dies(self):
        s = _make_structure()
        m = self._direct_hit_missile(s)
        events = []
        apply_missile_hits_structures([m], [s], events)
        assert m.alive is False

    def test_direct_hit_missile_phase_is_dead(self):
        s = _make_structure()
        m = self._direct_hit_missile(s)
        events = []
        apply_missile_hits_structures([m], [s], events)
        assert m.phase == PH_DEAD

    def test_direct_hit_missile_impact_pos_set(self):
        s = _make_structure()
        m = self._direct_hit_missile(s)
        events = []
        apply_missile_hits_structures([m], [s], events)
        assert m.impact_pos is not None

    def test_direct_hit_decrements_hp(self):
        s = _make_structure("bastion_tel")  # hp=2
        m = self._direct_hit_missile(s)
        events = []
        apply_missile_hits_structures([m], [s], events)
        assert s.hp == 1

    def test_direct_hit_emits_base_hit_event(self):
        s = _make_structure()
        m = self._direct_hit_missile(s)
        events = []
        apply_missile_hits_structures([m], [s], events)
        kinds = [e[0] for e in events]
        assert "base_hit" in kinds

    def test_second_hit_kills_and_fires_both_events_exactly_once(self):
        """Two sequential missiles: first leaves it damaged, second kills it.
        Events must contain exactly one 'base_hit' and one 'base_destroyed'.
        """
        s = _make_structure("bastion_tel")  # hp=2
        events = []

        m1 = self._direct_hit_missile(s)
        apply_missile_hits_structures([m1], [s], events)
        assert s.alive is True
        assert [e[0] for e in events] == ["base_hit"]

        m2 = self._direct_hit_missile(s)
        apply_missile_hits_structures([m2], [s], events)
        assert s.alive is False
        kinds = [e[0] for e in events]
        assert kinds.count("base_hit") == 2
        assert kinds.count("base_destroyed") == 1

    # --- miss (offset) ---------------------------------------------------------

    def test_miss_parallel_offset_does_not_hit(self):
        """A segment that runs parallel to the structure long axis but offset
        laterally far beyond the beam half-width must not register."""
        s = _make_structure("bastion_tel")
        half_beam = s.dims[1] * 0.5  # 1.75 m
        # Offset 10 m in X — far outside the 1.75 m beam half
        cy = float(s.pos[1]) + s.dims[2] * 0.5
        offset_x = float(s.pos[0]) + half_beam + 10.0
        prev_pos = np.array([offset_x, cy, -20.0])
        pos = np.array([offset_x, cy, 20.0])
        m = _FakeMissile(prev_pos, pos)
        events = []
        apply_missile_hits_structures([m], [s], events)
        assert m.alive is True
        assert events == []
        assert s.hp == HP_BASTION_TEL   # unchanged

    # --- dead structures are ignored -------------------------------------------

    def test_dead_structure_ignored(self):
        s = _make_structure("radar_station")
        s.hit()                           # kills it (hp=1)
        assert s.alive is False

        m = self._direct_hit_missile(s)
        events = []
        apply_missile_hits_structures([m], [s], events)
        # missile should pass through, structure was already dead
        assert m.alive is True
        assert events == []

    # --- dead missiles are ignored ---------------------------------------------

    def test_dead_missile_does_not_register(self):
        s = _make_structure()
        m = self._direct_hit_missile(s)
        m.alive = False                   # missile already dead
        events = []
        apply_missile_hits_structures([m], [s], events)
        assert s.hp == HP_BASTION_TEL    # untouched

    # --- on_destroyed callback in bulk context --------------------------------

    def test_on_destroyed_callback_fires_in_bulk_hit(self):
        calls = []
        s = _make_structure("radar_station",
                             on_destroyed=lambda st: calls.append(st))
        m = self._direct_hit_missile(s)
        events = []
        apply_missile_hits_structures([m], [s], events)
        assert len(calls) == 1
        assert calls[0] is s

    def test_on_destroyed_callback_fires_exactly_once(self):
        """Even if two missiles race in the same list, only the first hits."""
        calls = []
        s = _make_structure("radar_station",
                             on_destroyed=lambda st: calls.append(st))
        m1 = self._direct_hit_missile(s)
        m2 = self._direct_hit_missile(s)
        events = []
        apply_missile_hits_structures([m1, m2], [s], events)
        # Only one hit can land — the structure dies after m1, m2 sees dead target
        assert len(calls) == 1

    # --- radar tower altitude test --------------------------------------------

    def test_oniks_crossing_radar_tower_at_15m_altitude_hits(self):
        """Synthetic Oniks-like missile at 15 m altitude crosses the radar
        station footprint (tower is 22 m tall) — must register a hit.

        The radar_station OBB has height=22 m, so the OBB spans Y=[0, 22].
        At Y=15 the missile is inside the OBB vertically.  The footprint is
        14x14 m; the missile segment passes straight through the X/Z centre.
        """
        radar_pos = np.array([50_000.0, 80.0, -6_000.0], dtype=np.float64)
        s = Structure(
            structure_id="radar_test",
            kind="radar_station",
            pos=radar_pos,
        )
        # Missile altitude: 15 m above the base of the structure (ground level)
        # so absolute Y = radar_pos[1] + 15 = 95 m
        cruise_alt = float(radar_pos[1]) + 15.0
        cx = float(radar_pos[0])
        half_length = s.dims[0] * 0.5   # 7 m in X
        # Segment approaches from the west and exits east (X axis)
        prev_pos = np.array([cx - half_length - 5.0, cruise_alt,
                             float(radar_pos[2])])
        pos = np.array([cx + half_length + 5.0, cruise_alt,
                        float(radar_pos[2])])
        m = _FakeMissile(prev_pos, pos)
        events = []
        apply_missile_hits_structures([m], [s], events)
        assert m.alive is False, (
            "Missile at 15 m altitude should intersect the 22 m radar tower"
        )
        assert any(e[0] == "base_hit" for e in events)

    def test_missile_above_radar_tower_misses(self):
        """A missile at altitude well above the tower top must not hit."""
        radar_pos = np.array([50_000.0, 80.0, -6_000.0], dtype=np.float64)
        s = Structure(
            structure_id="radar_test_high",
            kind="radar_station",
            pos=radar_pos,
        )
        tower_top = float(radar_pos[1]) + s.dims[2]  # pos[Y] + height
        # Fly 50 m above the top
        high_alt = tower_top + 50.0
        cx = float(radar_pos[0])
        half_length = s.dims[0] * 0.5
        prev_pos = np.array([cx - half_length - 5.0, high_alt,
                             float(radar_pos[2])])
        pos = np.array([cx + half_length + 5.0, high_alt,
                        float(radar_pos[2])])
        m = _FakeMissile(prev_pos, pos)
        events = []
        apply_missile_hits_structures([m], [s], events)
        assert m.alive is True
        assert events == []
