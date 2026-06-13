"""COMBAT Phase 6 end-to-end (GL-free): the Pantsir-S1 point defense.

Covers the integration wired in world/combat.py (sim/pantsir.py controller,
sim/arsenal.py PANTSIR_57E6, models/pantsir.py body) — the player-side
mirror of the destroyers' auto-defense that protects the base STRUCTURES
against inbound hostile strike missiles:

  * WIRING: two Pantsirs guard the base at probe-measured dry-land sites,
    their 30 km radars JOIN the player network (dual role — point-defense
    sensor + contact-picture node), each carries 12x 57E6 + 700 gun rounds,
    and each is wrapped in a destructible Structure (kind "pantsir", HP 2)
    that does NOT trip the lose condition.
  * INTERCEPT: an inbound hostile Tomahawk at the Bastion draws a 57E6
    launch (pantsir_launch event, launch_platform set, is_hostile False so
    the round can never demolish the base it guards) and is killed before
    it can run the structure sweep — the base survives.
  * SHIELD, NOT WALL: a SMALL diving-JASSM raid (<= the measured leak
    threshold) is stopped and the base survives; a SATURATION raid above it
    leaks past the 57E6 + gun and reaches DEFEAT (spec 2.2 lose condition).
    Measured band (tools probes): 2 divers stopped, 4 divers leak.
  * SURVIVABILITY: a Pantsir whose destructible Structure is demolished
    (the real damage entry point, apply_missile_hits_structures) goes dark,
    stops launching, and its radar drops from the network coverage — while
    the OTHER Pantsir keeps defending.  A HARM aimed at a Pantsir whose
    flight segment crosses its OBB kills it through the same path.
  * PLACEMENT: each Pantsir sits OUTSIDE the seeker basket of the asset it
    guards, so the back-plotted JASSM/TLAM aim refinement still acquires
    the TEL — the Phase-5b kill chain is unperturbed.
  * SANDBOX untouched: WorldState carries no Pantsirs.

Physics at the locked 120 Hz step where rounds fly; coarse steps where
nothing ballistic is in the air (the established e2e pattern).  Scenario
forcing (cruise-state spawns from a release range the slow probes already
measured end-to-end) compresses the multi-hundred-km ingress.
"""

import numpy as np
import pytest

from game.hud import pantsir_status_row
from sim.arsenal import HARM as HARM_DEF
from sim.arsenal import JASSM, PANTSIR_57E6, TOMAHAWK
from sim.pantsir import PANTSIR_MAX_INFLIGHT
from sim.sam import SamMissile
from sim.strike import HarmMissile, StrikeMissile
from world.combat import (PANTSIR_COUNT, PANTSIR_STRUCT_HP, SEEKER_BASKET_M,
                          CombatWorld)
from world.generation import BASE_POS
from world.world import WorldState

DT = 1.0 / 120.0
DT_COARSE = 0.25    # nothing ballistic flies: rate-based machinery only


def _isolate(w):
    """Silence the player radar (no commander ESM fix) and empty the
    enemy escorts' magazines so the chain under test is the ONLY actor."""
    w.radar_station.emitting = False
    for s in w.ships:
        s.tomahawk_ammo = 0
        s.sm2_ammo = 0
        s.ciws_ammo = 0


def _spawn_inbound_tomahawk(w, xz, z_offset_m=18_000.0, alt_m=50.0):
    """A hostile Tomahawk inbound on (x, z) from z_offset_m north of it."""
    m = StrikeMissile(
        TOMAHAWK,
        np.array([xz[0], alt_m, xz[1] + z_offset_m], dtype=np.float64),
        np.zeros(3), (xz[0], xz[1]), target_y=0.0)
    m.launch_platform = None
    w.missiles.append(m)
    return m


def _spawn_diving_jassms(w, n, release_z_m=100_000.0):
    """``n`` hostile JASSMs released at altitude north of the Bastion,
    aimed at the Bastion TEL mid-OBB — the terminal dive that physically
    reaches the base over the coastal ridge (a sea-skimmer cannot; the
    commander uses JASSM/TLAM for exactly this reason)."""
    bastion = next(s for s in w.structures if s.kind == "bastion_tel")
    aim_y = float(bastion.pos[1]) + bastion.dims[2] * 0.5
    rounds = []
    for i in range(n):
        m = StrikeMissile(
            JASSM,
            np.array([BASE_POS[0] + (i - n / 2) * 40.0, 9_000.0,
                      BASE_POS[2] + release_z_m], dtype=np.float64),
            np.array([0.0, 0.0, -272.0]),
            (BASE_POS[0], BASE_POS[2]), target_y=aim_y)
        m.launch_platform = None
        w.missiles.append(m)
        rounds.append(m)
    return rounds


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------

def test_pantsirs_wired_into_the_base():
    w = CombatWorld()
    assert len(w.pantsirs) == PANTSIR_COUNT == 2
    # Radars joined the player network (dual role: point defense + node).
    for p in w.pantsirs:
        assert p.radar in w.radar_net.radars
        assert p.missile_ammo == 12 and p.gun_ammo == 700
    # Each unit has a destructible Structure wrapper of kind "pantsir".
    structs = [s for s in w.structures if s.kind == "pantsir"]
    assert len(structs) == 2
    for s in structs:
        assert s.hp == PANTSIR_STRUCT_HP == 2
    # The defense controller defends EVERY structure (incl. the Pantsirs).
    assert len(w.pantsir_defense._unit_defenses) == 2


def test_pantsir_structs_do_not_trip_the_lose_condition():
    """Killing only the Pantsir structures must NOT defeat the player —
    only the Bastion TEL counts (spec 2.2)."""
    w = CombatWorld()
    for s in w.structures:
        if s.kind == "pantsir":
            while s.alive:
                s.hit()
    assert not w.defeated
    assert all(not p.alive for p in w.pantsirs)   # callbacks fired


def test_pantsir_radars_extend_the_contact_picture():
    """A low inbound the 18 m ground-radar station cannot see under the
    horizon is visible to the network through a Pantsir's 30 km radar."""
    w = CombatWorld()
    p = w.pantsirs[0]
    # 12 km north of the Pantsir at 60 m: inside the Pantsir radar, far
    # past the distant ground station's horizon to such a low target.
    low = np.array([p.pos[0], 60.0, p.pos[2] + 12_000.0], dtype=np.float64)
    assert p.radar.detects(low, "missile")
    assert w.radar_net.visible(low, "missile")
    # The ground station alone (kill every Pantsir radar) would miss it.
    for q in w.pantsirs:
        q.radar.alive = False
    assert not w.radar_net.visible(low, "missile")


# ---------------------------------------------------------------------------
# Intercept
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_pantsir_intercepts_inbound_tomahawk_at_the_base():
    w = CombatWorld()
    _isolate(w)
    inbound = _spawn_inbound_tomahawk(
        w, (BASE_POS[0], BASE_POS[2]),
        z_offset_m=18_000.0)
    assert inbound.is_hostile and inbound.radar_size == "missile"
    saw_launch = False
    first_sam = None
    for _ in range(int(120.0 / DT)):
        w.step(DT)
        for k, _pos in w.drain_events():
            if k == "pantsir_launch":
                saw_launch = True
        if first_sam is None:
            first_sam = next(
                (m for m in w.missiles
                 if isinstance(m, SamMissile)
                 and m.weapon is PANTSIR_57E6), None)
        if not inbound.alive:
            break
    assert saw_launch, "a pantsir_launch event must fire"
    assert not inbound.alive, "the 57E6 must kill the inbound Tomahawk"
    assert all(s.alive for s in w.structures if s.kind == "bastion_tel")
    assert not w.defeated
    # The 57E6 carries the right integration flags and is NOT hostile, so
    # the structure sweep can never feed it against the base it guards.
    assert first_sam is not None
    assert first_sam.launch_platform in w.pantsirs
    assert first_sam.launch_cinematic is False
    assert not getattr(first_sam, "is_hostile", False)


@pytest.mark.slow
def test_57e6_respects_the_inflight_cap_against_a_raid():
    """Against a multi-round raid one unit never exceeds its in-flight cap
    (a fire-control discipline, not a magic salvo)."""
    w = CombatWorld()
    _isolate(w)
    # A tight cluster of inbound Tomahawks at the Bastion guard.
    p = w.pantsirs[0]
    for i in range(6):
        _spawn_inbound_tomahawk(
            w, (p.pos[0] + (i - 3) * 150.0, p.pos[2]),
            z_offset_m=16_000.0)
    peak = 0
    for _ in range(int(40.0 / DT)):
        w.step(DT)
        w.drain_events()
        for ud in w.pantsir_defense._unit_defenses:
            peak = max(peak, len(ud._inflight))
    assert peak <= PANTSIR_MAX_INFLIGHT


# ---------------------------------------------------------------------------
# Shield, not wall
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_small_raid_is_stopped_base_survives():
    """Two diving JASSMs (at/under the measured leak threshold) are
    defeated; the Bastion survives."""
    w = CombatWorld()
    _isolate(w)
    rounds = _spawn_diving_jassms(w, 2)
    for _ in range(int(520.0 / DT)):
        w.step(DT)
        w.drain_events()
        if w.defeated:
            break
    assert not w.defeated, "the Pantsir must stop a 2-round JASSM raid"
    assert all(s.alive for s in w.structures if s.kind == "bastion_tel")
    assert all(not m.alive for m in rounds), "both JASSMs are dead"


@pytest.mark.slow
def test_saturation_raid_leaks_and_reaches_defeat():
    """A four-round diving-JASSM raid (above the measured leak threshold)
    overwhelms the 57E6 + gun and reaches DEFEAT — the Pantsir is a shield,
    not an invincible wall (the whole point of spec 4.2 vs 2.2)."""
    w = CombatWorld()
    _isolate(w)
    _spawn_diving_jassms(w, 4)
    defeated = False
    for _ in range(int(520.0 / DT)):
        w.step(DT)
        w.drain_events()
        if w.defeated:
            defeated = True
            break
    assert defeated, "a saturation raid must still be able to kill the base"
    bastion = next(s for s in w.structures if s.kind == "bastion_tel")
    assert not bastion.alive
    assert w.launch("hi-lo", np.zeros(3)) is None   # launcher locked


# ---------------------------------------------------------------------------
# Survivability: a killed Pantsir drops from the fight and the net
# ---------------------------------------------------------------------------

def test_destroyed_pantsir_goes_dark_and_leaves_the_net():
    """Demolishing a Pantsir's destructible Structure (the real damage
    path) kills the unit, darkens its radar, removes it from network
    coverage, and stops it launching — the OTHER unit keeps defending."""
    w = CombatWorld()
    pk = w.pantsirs[0]
    other = w.pantsirs[1]
    struct = next(s for s in w.structures
                  if s.structure_id == f"{pk.unit_id}_struct")
    while struct.alive:
        struct.hit()
    assert not pk.alive and not pk.radar.alive
    # No longer contributes to the network picture.
    low = np.array([pk.pos[0], pk.pos[1] + 300.0, pk.pos[2] + 8_000.0],
                   dtype=np.float64)
    assert not any(r is pk.radar and r.detects(low, "missile")
                   for r in w.radar_net.radars)
    assert other.alive and other.radar.alive
    # The dead unit's fire control launches nothing even with a threat up.
    _isolate(w)
    _spawn_inbound_tomahawk(w, (pk.pos[0], pk.pos[2]), z_offset_m=10_000.0)
    dead_ud = next(ud for ud in w.pantsir_defense._unit_defenses
                   if ud.unit is pk)
    for _ in range(int(5.0 / DT)):
        w.step(DT)
        w.drain_events()
    assert pk.missile_ammo == 12, "a dead Pantsir must not launch"
    assert dead_ud._inflight == []


def test_harm_through_the_obb_kills_a_pantsir():
    """A HARM whose flight segment crosses a Pantsir's OBB demolishes it via
    the SAME structure sweep that kills the radar station — the Pantsir
    struct is registered in self.structures, so apply_missile_hits_structures
    (the exact function step() calls each frame) feeds the round against it
    and the on_destroyed wiring propagates the kill.  The round homes on the
    Pantsir's own emitter (a real HARM target geometry)."""
    from sim.bases import apply_missile_hits_structures
    w = CombatWorld()
    pk = w.pantsirs[0]
    struct = next(s for s in w.structures
                  if s.structure_id == f"{pk.unit_id}_struct")
    events = []
    killed = False
    for _ in range(struct.hp):                # HP HARMs, one OBB crossing each
        h = HarmMissile(HARM_DEF, pk.pos.copy(),
                        np.array([0.0, -300.0, 0.0]), pk.radar,
                        rng=np.random.default_rng(0))
        h.launch_platform = None
        # A descending segment straddling the OBB centre (top -> just above
        # the floor): the swept-segment test registers a hit.
        h.prev_pos = pk.pos + np.array([0.0, 12.0, 0.0])
        h.pos = pk.pos + np.array([0.0, 1.0, 0.0])
        apply_missile_hits_structures([h], w.structures, events)
        if not pk.alive:
            killed = True
            break
    assert killed, "HARMs crossing the OBB must kill the Pantsir"
    assert not pk.radar.alive
    assert not struct.alive
    assert "base_destroyed" in [k for k, _ in events]
    # Network coverage is gone with the node.
    low = np.array([pk.pos[0], pk.pos[1] + 300.0, pk.pos[2] + 8_000.0],
                   dtype=np.float64)
    assert not any(r is pk.radar and r.detects(low, "missile")
                   for r in w.radar_net.radars)


# ---------------------------------------------------------------------------
# Placement: the Pantsir never steals the strike aim
# ---------------------------------------------------------------------------

def test_pantsir_placement_does_not_steal_jassm_aim():
    """Each Pantsir sits outside the seeker basket of the asset it guards,
    so the believed bastion cluster refines onto the Bastion TEL — never
    the adjacent SHORAD vehicle (the Phase-5b kill chain hinges on this)."""
    w = CombatWorld()
    bastion = next(s for s in w.structures if s.kind == "bastion_tel")
    s300 = next(s for s in w.structures if s.kind == "s300_tel")
    for unit in w.pantsirs:
        d_bastion = float(np.hypot(unit.pos[0] - bastion.pos[0],
                                   unit.pos[2] - bastion.pos[2]))
        d_s300 = float(np.hypot(unit.pos[0] - s300.pos[0],
                                unit.pos[2] - s300.pos[2]))
        # The unit is > a basket away from at least the asset it shields
        # (the nearer of the two TELs).
        assert min(d_bastion, d_s300) > SEEKER_BASKET_M
    # Aim refinement at the Bastion's own coordinates returns the Bastion.
    tx, tz, _ay = w._refine_strike_aim(float(bastion.pos[0]),
                                       float(bastion.pos[2]))
    assert np.allclose([tx, tz], [bastion.pos[0], bastion.pos[2]])


# ---------------------------------------------------------------------------
# HUD helper + SANDBOX isolation
# ---------------------------------------------------------------------------

def test_pantsir_hud_row_states():
    w = CombatWorld()
    label, text, _col = pantsir_status_row(w)
    assert label == "PANTSIR"
    assert text == "2 UP  M24 G1400"           # 2 units, pooled ammo
    assert pantsir_status_row(w, engaging=True)[1] == "ENGAGING"
    for p in w.pantsirs:
        p.kill()
    assert pantsir_status_row(w)[1] == "DOWN"


def test_sandbox_world_has_no_pantsirs():
    w = WorldState()
    assert not hasattr(w, "pantsirs")
    assert pantsir_status_row(w) is None
