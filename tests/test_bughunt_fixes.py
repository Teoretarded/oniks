"""Regression tests for the 2026-07-04 hostile-review bug-hunt fixes:

  1. A SamMissile whose assigned target is already dead BREAKS OFF
     (self-destructs) instead of PN-homing onto the corpse, re-killing it
     and overwriting its death_cause/killed_by forensics stamp
     (sim/sam.py update + _fuse_check).
  2. A destroyed firing-TEL Structure marks its tube slice DEAD: the tubes
     stop firing/reloading, the armed gates and the salvo ready count
     exclude them, and only the surviving TELs keep shooting
     (world/combat.py _build_relocatable_registry / _launcher_committed).
  3. The enemy Tomahawk salvo loop tolerates hulls without a TLAM bank
     (LCACs ride in world.ships) instead of crashing on a bare attribute
     read (world/combat.py _fire_tomahawk_salvo).
  4. The submarine fires its Kalibr salvo only once RISEN to the shallow
     launch depth — the shallow-exposure window the state machine was
     designed around actually happens (sim/submarine.py).
  5. A recon-drone waypoint dropped inside the drone's turning circle is
     captured (turn-radius capture gate) instead of trapping the drone in
     a permanent orbit (sim/recon.py _update_route).
"""

import numpy as np

from sim.arsenal import SM2
from sim.sam import SamMissile
from sim.submarine import (SUB_DEPTH_M, SUB_LAUNCH, SUB_LAUNCH_DEPTH_M,
                           Submarine)
from world.combat import CombatWorld
from world.combat_config import CombatConfig

DT = 1.0 / 120.0


class _OpenWater:
    ships = []

    def terrain_height_at(self, x, z):
        return -50.0


def _kill(struct):
    while struct.alive:
        struct.hit()


def _struct(cw, sid):
    return next(s for s in cw.structures if s.structure_id == sid)


# --- 1. SAM break-off on a dead target -------------------------------------------

def test_sam_breaks_off_when_target_dies_and_keeps_forensics_stamp():
    class _Victim:
        def __init__(self):
            self.pos = np.array([0.0, 1_000.0, 5_000.0])
            self.alive = True

        def velocity(self):
            return np.zeros(3)

    v = _Victim()
    w = _OpenWater()
    sam = SamMissile(SM2, np.array([0.0, 10.0, 0.0]), v)
    for _ in range(int(2.0 / DT)):
        sam.update(DT, w)
    assert sam.alive
    # A sister round kills the target and stamps its cause.
    v.alive = False
    v.death_cause = ("hit", "lead-round")
    sam.update(DT, w)
    assert not sam.alive
    assert sam.self_destructed
    assert not sam.killed_target            # no corpse re-kill
    assert v.death_cause == ("hit", "lead-round")   # stamp never clobbered


# --- 2. destroyed TELs stop firing ------------------------------------------------

def test_dead_bastion_tel_tubes_die_and_battery_degrades():
    cw = CombatWorld(CombatConfig(seed=11, n_oniks=2))
    d0 = cw._relocatable_for("bastion_tel_00")
    d1 = cw._relocatable_for("bastion_tel_01")
    _kill(_struct(cw, "bastion_tel_00"))
    assert all(t.get("dead") and not t["loaded"] for t in d0["tubes"])
    # The magazine can never reload a dead tube.
    cw._step_oniks_tubes(1_000.0)
    assert all(not t["loaded"] for t in d0["tubes"])
    # The SURVIVING TEL still fires — and the round leaves ITS tube.
    m = cw.launch("hi-lo", np.array([0.0, 0.0, 200_000.0]))
    assert m is not None
    assert any(t["reload_left"] > 0.0 for t in d1["tubes"])
    assert all(t["reload_left"] <= 0.0 for t in d0["tubes"])
    # All TELs rubble: no launch, defeat trips.
    _kill(_struct(cw, "bastion_tel_01"))
    assert cw.launch("hi-lo", np.array([0.0, 0.0, 200_000.0])) is None
    assert cw.defeated


def test_dead_s300_tel_disarms_the_sam_battery():
    cw = CombatWorld(CombatConfig(seed=11, n_s300=1))
    assert cw.sam_launcher_armed
    _kill(_struct(cw, "s300_tel_00"))
    assert not cw.sam_launcher_armed
    assert not cw.sam_40n6_launcher_armed


def test_ready_tube_count_excludes_dead_tubes():
    from game.salvo import ready_tube_count
    cw = CombatWorld(CombatConfig(seed=11, n_oniks=2))
    full = ready_tube_count(cw, "bastion")
    assert full >= 2
    _kill(_struct(cw, "bastion_tel_00"))
    assert ready_tube_count(cw, "bastion") == full - 2   # 2 tubes per TEL


# --- 3. Tomahawk salvo vs hulls without a TLAM bank -------------------------------

def test_tomahawk_salvo_survives_hulls_without_tlam_bank():
    cw = CombatWorld(CombatConfig(seed=11))

    class _Craft:                    # LCAC-like: a live hull, no tomahawk_ammo
        alive = True
        ship_id = "lcac_test"
        pos = np.array([0.0, 0.0, 150_000.0])

    cw.ships.append(_Craft())
    for s in cw.ships:
        if hasattr(s, "tomahawk_ammo"):
            s.tomahawk_ammo = 0      # force the loop to REACH the craft
    # Old code: AttributeError on _Craft.tomahawk_ammo.  New code: no-op.
    cw._fire_tomahawk_salvo({"type": "tomahawk_salvo",
                             "target_id": "cluster_00",
                             "target_pos": np.array([0.0, 0.0, 0.0])})


# --- 4. submarine fires only at launch depth --------------------------------------

def test_sub_fires_only_after_rising_to_launch_depth():
    sub = Submarine(anchor_xz=(0.0, 100_000.0),
                    rng=np.random.default_rng(3),
                    kalibr_ammo=4, base_xz=(0.0, 0.0))
    sub.state = SUB_LAUNCH
    sub._enter(SUB_LAUNCH)
    sub.pos[1] = SUB_DEPTH_M                       # still at transit depth
    assert sub.step(DT, threat_level=0.0) is None  # NO transit-depth launch
    fired_depth = None
    for _ in range(int(60.0 / DT)):
        if sub.step(DT, threat_level=0.0) is not None:
            fired_depth = float(sub.pos[1])
            break
    assert fired_depth is not None, "the boat must fire once shallow"
    assert fired_depth >= SUB_LAUNCH_DEPTH_M - 1.0


# --- 5. drone waypoint inside the turning circle -----------------------------------

def test_drone_waypoint_inside_turn_circle_is_captured():
    from sim.recon import ReconDrone
    drone = ReconDrone(spawn_xz=(0.0, 0.0), height_fn=lambda x, z: 0.0)
    # 300 m abeam: inside the 640 m minimum-turn circle — the old 160 m
    # capture gate orbited it forever; now it captures and flies on.
    drone.set_route([(300.0, 0.0), (0.0, 20_000.0)])
    for _ in range(int(30.0 / DT)):
        drone.update(DT)
        if drone._loitering or drone._wp_idx >= 1:
            break
    assert drone._wp_idx >= 1, "close-abeam waypoint must be captured"


# --- second wave: fog / scoring / UI-contract fixes --------------------------------

def test_killer_observed_for_launch_warning_round():
    """A launch-warning killer (enemy SM-2/AIM-9X) is on the player picture
    its whole flight: observed by construction, even though its track was
    dropped the same step it died (the old lookup always missed)."""
    from game.flight_recorder import FlightRecorder

    class _Sam:
        launch_warning = True
        aircraft_id = "sm2_00"

    class _World:
        contacts = None

    assert FlightRecorder._killer_observed(_Sam(), _World())


def test_tally_hides_unobserved_loss_class_mid_battle():
    from game.forensics import tally
    recs = [{"cause": {"code": "sam", "detail": "sm2", "observed": False}}]
    mid = tally(recs, battle_over=False)
    assert mid["intercepted"] == 0          # class not leaked mid-battle
    assert mid["unconfirmed"] == 1
    post = tally(recs, battle_over=True)
    assert post["intercepted"] == 1         # post-battle reconstruction


def test_leak_rate_uses_offensive_denominator():
    from game.scoring import compute_scorecard, new_telemetry

    class _W:
        ships = []
        structures = []
        enemy_radars = []
        airfield = None
        victorious = False
        commander = None

    tel = new_telemetry()
    tel["rounds_fired"] = 10                # 6 SAM shots + 4 Oniks
    tel["offensive_fired"] = 4
    tel["leakers"] = 4
    card = compute_scorecard(_W(), tel)
    assert card.leak_rate == 1.0            # 4-of-4 offensive got through


def test_ready_tube_count_bounds_by_selected_round_pool():
    from game.salvo import ready_tube_count

    class _W:
        _s300_tubes = [{"reload_left": 0.0} for _ in range(4)]
        sam_ammo = 0
        sam_ammo_40n6 = 3

    assert ready_tube_count(_W(), "s300", sam_round="40n6") == 3
    assert ready_tube_count(_W(), "s300", sam_round="48n6") == 0


def test_salvo_rounds_carry_the_plotted_waypoints():
    from game.salvo import SalvoQueue

    class _W:
        def __init__(self):
            self.calls = []

        def launch(self, profile, aim, waypoints=(), weapon_id="oniks"):
            self.calls.append(tuple(waypoints))
            return object()

    w = _W()
    q = SalvoQueue()
    q.start("bastion", count=2, target_point=(0.0, 0.0, 1_000.0),
            waypoints=((5_000.0, 5_000.0),))
    q.tick(10.0, w)                          # both beats fall due
    assert w.calls
    assert all(c == ((5_000.0, 5_000.0),) for c in w.calls)


def test_rebind_from_unbound_row_never_silently_unbinds(tmp_path):
    import pygame
    from game.keybinds import Keybinds, RESERVED_KEYS, _DEFS
    kb = Keybinds(str(tmp_path / "settings.json"))
    used = ({k for k in kb.keys.values() if k is not None}
            | set(RESERVED_KEYS))
    free = next(k for k in (pygame.K_F7, pygame.K_F8, pygame.K_F9,
                            pygame.K_SEMICOLON, pygame.K_QUOTE)
                if k not in used)
    b = "map"
    assert kb.rebind(b, free)                # move b OFF its default
    a = "launch"
    kb.keys[a] = None                        # an unbound row
    assert kb.rebind(a, free)                # a takes b's key
    assert kb.keys[a] == free
    # b fell back to its now-free default instead of a silent None unbind.
    assert kb.keys[b] == _DEFS[b].default


def test_unbound_row_persists_across_reload(tmp_path):
    from game.keybinds import Keybinds
    path = str(tmp_path / "settings.json")
    kb = Keybinds(path)
    kb.keys["screenshot"] = None
    kb.save()
    kb2 = Keybinds(path)
    assert kb2.keys["screenshot"] is None
