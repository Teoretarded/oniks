"""COMBAT Phase 3 end-to-end (GL-free): the enemy strikes back.

Covers the integration seams wired in world/combat.py:

  * ESM localization accrues only while the player radar station is alive
    AND emitting AND a destroyer survives to hear it; decays at half rate
    otherwise (sim/enemy_strikes.py).
  * The first salvo at a full fix is exactly SALVO_SIZE (2) Tomahawks with
    the Phase-2 integration flags set; the salvo period gates follow-ups.
  * A silenced radar is never localized -> no strike ever launches.
  * Full kill chain: a Tomahawk flying its complete profile from a real
    destroyer anchor OBB-kills the radar-station structure, the Radar's
    alive clears via on_destroyed, and the player picture goes blind —
    existing tracks coast out and drop, no new tracks ever form.
  * The is_hostile filter: a friendly round sweeping the Bastion TEL OBB
    does NOT damage it; the same sweep flagged hostile does.
  * Lose condition: defeated flips when the Bastion structure dies and
    world.launch returns None from then on.

Physics at the locked 120 Hz step where rounds fly; the rate-based ESM
controller is exercised with coarse steps where no round is in the air.
"""

import numpy as np
import pytest

from sim.arsenal import TOMAHAWK
from sim.contacts import TRACK_DROP_S
from sim.enemy_strikes import (ESM_DECAY_FACTOR, ESM_FIX_TIME_S, SALVO_SIZE,
                               SALVO_PERIOD_S)
from sim.ships import ST_SINKING
from sim.strike import StrikeMissile
from world.combat import CombatWorld
from world.combat_config import CombatConfig

DT = 1.0 / 120.0


def _disarm_pantsirs(w):
    """Empty Pantsir magazines so Phase 3 kill-chain tests are not affected
    by the Phase 6 point-defense intercepting hostile strike missiles."""
    for p in getattr(w, "pantsirs", []):
        p.missile_ammo = 0
        p.gun.ammo = 0


# ---------------------------------------------------------------------------
# ESM localization accrual / decay
# ---------------------------------------------------------------------------

def test_esm_accrues_emitting_decays_silent_and_dead():
    w = CombatWorld()
    s = w.strikes
    assert s.progress == 0.0

    # Emitting + alive + heard: accrues at 1/ESM_FIX_TIME_S per second.
    s.step(w, 9.0)
    assert s.progress == pytest.approx(9.0 / ESM_FIX_TIME_S)

    # Silent: decays at ESM_DECAY_FACTOR of the accrual rate.
    w.radar_station.emitting = False
    s.step(w, 9.0)
    assert s.progress == pytest.approx(
        (1.0 - ESM_DECAY_FACTOR) * 9.0 / ESM_FIX_TIME_S)

    # Dead radar decays too — emitting alone is not enough.
    w.radar_station.emitting = True
    w.radar_station.alive = False
    s.step(w, 4.0)
    assert s.progress == pytest.approx(
        (1.0 - ESM_DECAY_FACTOR) * 9.0 / ESM_FIX_TIME_S
        - ESM_DECAY_FACTOR * 4.0 / ESM_FIX_TIME_S)

    # No living destroyer to hear the emissions: no accrual either.
    w.radar_station.alive = True
    for d in w.ships:
        d.state = ST_SINKING
    before = s.progress
    s.step(w, 9.0)
    assert s.progress < before

    # Floor at zero.
    s.step(w, 10_000.0)
    assert s.progress == 0.0


def test_silenced_radar_is_never_localized_no_strike():
    """Radar silent from t=0: progress stays at zero and nothing launches
    (the player's counter from the very first second)."""
    w = CombatWorld()
    w.radar_station.emitting = False
    for _ in range(300):                    # coarse: 300 s of controller time
        w.strikes.step(w, 1.0)
    assert w.strikes.progress == 0.0
    assert w.missiles == []
    # Every magazine untouched: the destroyers still hold their full 8;
    # the Phase-5a carrier ships none (silent doctrine, zero land-attack
    # cells) and must stay at zero.
    assert all(d.tomahawk_ammo == 8 for d in w.ships
               if d.ship_type == "destroyer")
    assert all(d.tomahawk_ammo == 0 for d in w.ships
               if d.ship_type == "carrier")


# ---------------------------------------------------------------------------
# Salvo discipline
# ---------------------------------------------------------------------------

def test_first_salvo_is_exactly_two_tomahawks():
    w = CombatWorld()
    w.strikes.progress = 1.0                # full ESM fix
    ammo0 = sum(d.tomahawk_ammo for d in w.ships)
    w.strikes.step(w, DT)

    toms = [m for m in w.missiles if getattr(m, "is_hostile", False)]
    assert len(toms) == SALVO_SIZE == 2
    assert sum(d.tomahawk_ammo for d in w.ships) == ammo0 - SALVO_SIZE
    for m in toms:
        assert isinstance(m, StrikeMissile)
        assert m.weapon is TOMAHAWK
        assert m.launch_cinematic is False          # no 1x time lock
        assert m.launch_platform in w.ships         # never self-OBB-hit
        assert m.is_air and m.radar_size == "missile"
        # Aimed at the radar station's surveyed coordinates.
        assert m.target_x == pytest.approx(float(w.radar_station.pos[0]))
        assert m.target_z == pytest.approx(float(w.radar_station.pos[2]))

    # Salvo period: nothing more until SALVO_PERIOD_S elapses ...
    w.strikes.step(w, SALVO_PERIOD_S - 1.0)
    assert len(w.missiles) == SALVO_SIZE
    # ... then the follow-up salvo while still located + alive + emitting.
    w.strikes.step(w, 2.0)
    assert len(w.missiles) == 2 * SALVO_SIZE


# ---------------------------------------------------------------------------
# is_hostile filter: friendly rounds can never demolish the player base
# ---------------------------------------------------------------------------

class _SweepStub:
    """Minimal missile duck-type whose one step sweeps through a structure
    OBB (update moves pos by `delta`; damage reads pos/prev_pos)."""

    is_hostile = False
    is_air = True
    radar_size = "missile"

    def __init__(self, start, delta):
        self.pos = np.asarray(start, dtype=np.float64).copy()
        self.prev_pos = self.pos.copy()
        self.vel = np.asarray(delta, dtype=np.float64) / DT
        self.delta = np.asarray(delta, dtype=np.float64)
        self.alive = True
        self.phase = 0
        self.impact_pos = None
        self.fuel = 1.0

    @property
    def aircraft_id(self):
        return f"stub_{id(self):x}"

    def velocity(self):
        return self.vel

    def update(self, dt, world):
        np.copyto(self.prev_pos, self.pos)
        self.pos += self.delta


def _bastion_sweep_stub(w):
    """A stub whose first step crosses the Bastion TEL OBB broadside."""
    bastion = next(s for s in w.structures if s.kind == "bastion_tel")
    mid = bastion.pos + np.array([0.0, 2.0, 0.0])     # 2 m over the ground
    return _SweepStub(mid - np.array([60.0, 0.0, 0.0]),
                      np.array([120.0, 0.0, 0.0]))


def test_friendly_round_cannot_damage_own_base():
    w = CombatWorld()
    bastion = next(s for s in w.structures if s.kind == "bastion_tel")
    hp0 = bastion.hp
    stub = _bastion_sweep_stub(w)
    assert stub.is_hostile is False
    w.missiles.append(stub)
    w.step(DT)
    assert bastion.alive and bastion.hp == hp0        # filter held
    assert stub.alive                                 # flew straight through


def test_hostile_round_damages_the_base():
    w = CombatWorld()
    bastion = next(s for s in w.structures if s.kind == "bastion_tel")
    hp0 = bastion.hp
    stub = _bastion_sweep_stub(w)
    stub.is_hostile = True
    w.missiles.append(stub)
    w.step(DT)
    assert bastion.hp == hp0 - 1
    assert not stub.alive and stub.impact_pos is not None
    assert "base_hit" in [kind for kind, _ in w.events]


# ---------------------------------------------------------------------------
# Lose condition
# ---------------------------------------------------------------------------

def test_defeat_flips_and_launch_locks():
    w = CombatWorld()
    assert not w.defeated
    assert w.launcher_armed
    target = np.array([0.0, 0.0, 200_000.0])
    assert w.launch("hi-lo", target) is not None      # battery works pre-kill

    bastion = next(s for s in w.structures if s.kind == "bastion_tel")
    while bastion.alive:
        bastion.hit()
    assert w.defeated

    w.reload_left = 0.0                               # reload is NOT the gate
    assert not w.launcher_armed
    assert w.launch("hi-lo", target) is None          # no Oniks ever again


# ---------------------------------------------------------------------------
# Full kill chain: Tomahawk profile -> station dead -> picture blind
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_tomahawk_kills_radar_station_and_blinds_the_picture():
    """One salvo from the real destroyer anchors flies the full VLS eject /
    boost / terrain-following cruise / two-stage terminal profile into the
    radar-station OBB. Afterwards the picture is blind.

    Phase 7 (updated): uses seed=5. The enemy-strike selector picks from all
    destroyers with ammo; destroyer_00 at 297 km launches both Tomahawks
    giving a flight time of ~1335 s. The loop runs 2000 s to cover all ships
    in the fleet. DEFAULT seed=1337 also places all destroyers at 260-340 km."""
    w = CombatWorld(CombatConfig(seed=5))
    _disarm_pantsirs(w)    # Phase 6 point-defense isolated from Phase 3 test
    w.strikes.progress = 1.0
    w.step(DT)                                        # salvo of 2 launches
    assert sum(1 for m in w.missiles
               if getattr(m, "is_hostile", False)) == 2
    for d in w.ships:
        d.tomahawk_ammo = 0                           # bound: one salvo only

    radar = w.radar_station
    station = next(s for s in w.structures if s.kind == "radar_station")
    saw_strike_track = False
    base_destroyed = False
    kill_time = None
    for _ in range(int(2000.0 / DT)):
        w.step(DT)
        if not saw_strike_track and any(
                cid.startswith("strike_") for cid in w.contacts.tracks):
            saw_strike_track = True                   # picture saw it coming
        for kind, _pos in w.drain_events():
            if kind == "base_destroyed":
                base_destroyed = True
        if not radar.alive:
            kill_time = w.sim_time
            break
    assert kill_time is not None, "Tomahawk never killed the radar station"
    assert 300.0 < kill_time < 1700.0                 # fleet is 130-330 km away
    assert saw_strike_track                           # picture saw it coming
    assert base_destroyed
    assert not station.alive                          # structure dead ...
    assert not radar.alive                            # ... cleared the Radar

    # The picture goes blind: the radar gate now fails for everything, so
    # the remaining tracks coast and drop (TRACK_DROP_S) and the board can
    # never form a new one — even with the second Tomahawk still flying.
    for _ in range(int((TRACK_DROP_S + 5.0) / DT)):
        w.step(DT)
    w.drain_events()
    assert w.contacts.tracks == {}
