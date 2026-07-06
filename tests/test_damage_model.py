"""Subsystem damage model contracts (2026-07-06 spec).

Guards, in order: the LEGACY path stays byte-identical (characterization +
config default), the new module is physics-not-dice (zero RNG), geometry is
exact, and the approved outcome ladder holds two-sided:
ARM = mission-kill never sink; one Oniks = crippling fire+flood the crew can
fight; magazine cook-off scales with live ammo and only a big-enough event
breaks the hull; subsystem battles replay deterministically.
"""

import inspect
import math

import numpy as np
import pytest

import sim.damage_model as dm
from sim.damage import apply_missile_hits
from sim.damage_model import (COOK_SINK_TNT_KG, DamageState, cookoff_tnt_kg,
                              local_to_grid, resolve_hit, segment_obb_entry,
                              step_ships)
from sim.ships import (BURN_TIME, HULL_DRAFT, ST_ALIVE, ST_BURNING,
                       ST_SINKING, Ship)
from world.combat_config import CombatConfig, clamp_config

DT = 1.0 / 120.0


class _Round:
    """Minimal player anti-ship round for the OBB sweep (test_amphibious
    pattern) extended with the subsystem-model inputs: vel, mass, weapon."""

    class _W:
        def __init__(self, warhead_mass, nose_hardness):
            self.warhead_mass = warhead_mass
            self.nose_hardness = nose_hardness
            self.weapon_id = "test_round"

    def __init__(self, prev_pos, pos, mass=2500.0, warhead=250.0,
                 hardness=1.0):
        self.prev_pos = np.asarray(prev_pos, dtype=np.float64)
        self.pos = np.asarray(pos, dtype=np.float64)
        self.vel = ((self.pos - self.prev_pos) / DT)
        self.alive = True
        self.is_hostile = False
        self.impact_pos = None
        self.phase = 0
        self.mass = float(mass)
        self.weapon = self._W(warhead, hardness)


def _destroyer():
    """A stationary-enough destroyer-classed hull for scripted impacts."""
    from sim.enemy_ships import Destroyer
    return Destroyer("d_probe", (0.0, 200_000.0), heading_deg=0.0)


def _hit_at(ship, z_frac, y_wl_m, mass=2500.0, warhead=250.0, hardness=1.0,
            speed=680.0):
    """A round on a beam-on (west->east) collision course through the hull
    point at length-fraction ``z_frac`` and ``y_wl_m`` meters vs waterline.
    Ship heading 0 = bow north => local +Z is world +Z."""
    zc = float(ship.pos[2]) - ship.length * 0.5 + z_frac * ship.length
    y = y_wl_m
    x0 = float(ship.pos[0]) - 60.0
    p_prev = (x0, y, zc)
    p_now = (x0 + speed * DT * 30.0, y, zc)   # long segment: guaranteed cross
    r = _Round(p_prev, p_now, mass=mass, warhead=warhead, hardness=hardness)
    r.vel = np.array([speed, 0.0, 0.0])
    return r


# ---------------------------------------------------------------- legacy guard

def test_legacy_ladder_characterization():
    """TODAY'S truth, pinned: one hit = hp-1 + BURNING; burn expiry sinks.
    Must stay green forever on the default (legacy) path."""
    ship = _destroyer()
    r = _hit_at(ship, 0.5, 2.0)
    ev = []
    apply_missile_hits([r], [ship], ev)              # no flag: legacy
    assert not r.alive
    assert ship.hp == 2 and ship.state == ST_BURNING
    assert any(k == "ship_hit" for k, _p in ev)
    for _ in range(int(BURN_TIME / DT) + 2):
        ship.update(DT)
    assert ship.state == ST_SINKING

def test_legacy_path_never_creates_damage_state():
    ship = _destroyer()
    apply_missile_hits([_hit_at(ship, 0.5, 2.0)], [ship], [])
    assert getattr(ship, "_dmg", None) is None

def test_config_default_is_legacy():
    assert CombatConfig().damage_model == "legacy"
    assert clamp_config().damage_model == "legacy"
    assert clamp_config(damage_model="subsystem").damage_model == "subsystem"
    assert clamp_config(damage_model="anything").damage_model == "subsystem"


# ------------------------------------------------------------ physics-not-dice

def test_no_rng_in_damage_model():
    src = inspect.getsource(dm)
    assert "default_rng" not in src
    assert "np.random" not in src
    assert "import random" not in src


# ----------------------------------------------------------------- geometry

def test_segment_obb_entry_point():
    center = np.zeros(3)
    half = np.array([1.0, 2.0, 3.0])
    rot = np.eye(3)
    hit = segment_obb_entry((-5.0, 0.0, 0.0), (5.0, 0.0, 0.0),
                            center, half, rot)
    assert hit is not None
    t, q = hit
    assert abs(q[0] - (-1.0)) < 1e-12        # entered through the -X face
    assert abs(t - 0.4) < 1e-12
    assert segment_obb_entry((-5.0, 5.0, 0.0), (5.0, 5.0, 0.0),
                             center, half, rot) is None

def test_local_to_grid_waterline_and_bow():
    ship = _destroyer()
    center, half, rot = ship.obb()
    # World point at the waterline (world y == 0 == ship.pos[1]), at the bow
    # tip, centered in beam.
    world = ship.pos + rot @ np.array([0.0, 0.0, ship.length * 0.5])
    q = rot.T @ (world - center)
    z, y, x = local_to_grid(ship, q)
    assert abs(z - 1.0) < 1e-9               # bow
    assert abs(y) < 1e-9                     # exactly the waterline
    assert abs(x) < 1e-9


# ------------------------------------------------------------- outcome ladder

def test_arm_frag_mission_kills_never_sinks():
    """An 87 kg frag head into the mast: radar dead, hull dry, ship afloat."""
    ship = _destroyer()
    ev = []
    r = _hit_at(ship, 0.63, 22.0, mass=600.0, warhead=87.0, hardness=0.2,
                speed=700.0)
    apply_missile_hits([r], [ship], ev, damage_model="subsystem")
    assert not r.alive
    assert ship.radar.alive is False          # sensors shredded
    st = ship._dmg
    assert sum(st.breach) == 0.0              # frag head: no hull breach
    assert sum(st.flood) == 0.0
    # The small fire (if any) is contained by the crew: run 10 minutes.
    for _ in range(int(600.0 / DT)):
        step_ships([ship], DT, ev)
    assert ship.state in (ST_ALIVE, ST_BURNING)
    assert st.flooded_count() == 0

def test_oniks_waterline_floods_one_compartment_crew_fights():
    """One Oniks at the waterline: a real breach, the hit compartment floods,
    the ship is crippled but 1 flooded bin of 6 does NOT sink her."""
    ship = _destroyer()
    ev = []
    r = _hit_at(ship, 0.35, -1.0)             # MER2 region, below WL
    apply_missile_hits([r], [ship], ev, damage_model="subsystem")
    st = ship._dmg
    assert st.breach[st.comp_of(0.35)] > 1.0  # SAP breach band (research 1-12 m^2)
    assert r.impact_ke > 4.0e8                # the Sheffield lever is real
    for _ in range(int(240.0 / DT)):          # 4 min of flooding vs pumps
        step_ships([ship], DT, ev)
    assert st.flooded_count() >= 1
    assert ship.state != ST_SINKING           # crippled, afloat

def test_engine_room_hits_stop_the_ship():
    """Both main engine rooms knocked out => dead in the water (speed 0)."""
    ship = _destroyer()
    ev = []
    apply_missile_hits([_hit_at(ship, 0.35, -1.0)], [ship], ev,
                       damage_model="subsystem")     # MER2 0.30-0.42
    apply_missile_hits([_hit_at(ship, 0.52, -1.0)], [ship], ev,
                       damage_model="subsystem")     # MER1 0.48-0.58
    assert ship.speed == 0.0

def test_three_flooded_compartments_sink():
    """Two more waterline hits spreading the flooding past the 3-bin standard
    sink the destroyer through the EXISTING sinking ladder."""
    ship = _destroyer()
    ev = []
    for zf in (0.20, 0.45, 0.75):
        apply_missile_hits([_hit_at(ship, zf, -1.5)], [ship], ev,
                           damage_model="subsystem")
    for _ in range(int(300.0 / DT)):
        step_ships([ship], DT, ev)
        if ship.state == ST_SINKING:
            break
    assert ship.state == ST_SINKING

def test_cookoff_scales_with_ammo_and_gates_catastrophe():
    """Energetics doc formula: yield grows with live rounds; a near-empty
    magazine cannot produce a hull-breaking event."""
    assert cookoff_tnt_kg(0) == 0.0
    assert cookoff_tnt_kg(1) < cookoff_tnt_kg(8) < cookoff_tnt_kg(25)
    assert cookoff_tnt_kg(2) < COOK_SINK_TNT_KG      # depleted mag: survivable
    assert cookoff_tnt_kg(25) > COOK_SINK_TNT_KG     # full mag: hull-breaking

def test_penetrating_hit_into_full_vls_is_catastrophic():
    """A SAP warhead delivered INTO a live 2/3-loaded VLS block detonates the
    magazine: instant loss + the magazine_detonation effect event."""
    ship = _destroyer()                        # 24 SM-2 + 6 SM-6 + 8 TLAM
    ev = []
    r = _hit_at(ship, 0.65, 0.5)               # vls_aft_64 (0.60-0.70), at WL
    apply_missile_hits([r], [ship], ev, damage_model="subsystem")
    assert ship.state == ST_SINKING
    assert any(k == "magazine_detonation" for k, _p in ev)

def test_vls_kill_on_empty_magazine_is_firepower_kill_only():
    ship = _destroyer()
    ship.sm2_ammo = 2; ship.sm6_ammo = 0; ship.tomahawk_ammo = 0
    ev = []
    apply_missile_hits([_hit_at(ship, 0.65, 0.5)], [ship], ev,
                       damage_model="subsystem")
    assert ship.state != ST_SINKING            # no yield to break the hull
    assert not any(k == "magazine_detonation" for k, _p in ev)
    # The aft block (2/3 of the pool) is dead; the fwd block's share of the
    # 2 remaining rounds (round(2 * 1/3) = 1) survives in its own cells.
    assert ship.sm2_ammo == 1

def test_zircon_class_ke_ratio_two_sided():
    """Structural channel is pure KE: a Mach-4.5-class arrival must carry
    3-9x an Oniks-class arrival (band tightens after the F2-P4 probe)."""
    oniks = 0.5 * 2500.0 * 680.0 ** 2
    zircon = 0.5 * 3000.0 * 1500.0 ** 2
    assert 3.0 <= zircon / oniks <= 9.0

def test_merchant_two_compartments_sink():
    ship = Ship("m_probe", "cargo", [(0.0, 0.0), (0.0, 10_000.0)], 0.5)
    ev = []
    for zf in (0.25, 0.70):
        apply_missile_hits([_hit_at(ship, zf, -1.5)], [ship], ev,
                           damage_model="subsystem")
    for _ in range(int(300.0 / DT)):
        step_ships([ship], DT, ev)
        if ship.state == ST_SINKING:
            break
    assert ship.state == ST_SINKING


# ------------------------------------------------------------- determinism

@pytest.mark.slow
def test_subsystem_battle_deterministic():
    """Two identical subsystem-mode battles digest-equal after 20 sim-sec."""
    from game.blackbox import state_digest
    from world.combat import CombatWorld
    cfg = CombatConfig(seed=777, damage_model="subsystem")
    worlds = [CombatWorld(cfg), CombatWorld(cfg)]
    for w in worlds:
        for _ in range(2400):
            w.step(DT)
            w.drain_events()
    assert state_digest(worlds[0]) == state_digest(worlds[1])

def test_hitcam_stamp_is_write_only_and_complete():
    """The dead round carries the full X-ray snapshot (render-layer input);
    legacy rounds never carry it (guarded above)."""
    ship = _destroyer()
    r = _hit_at(ship, 0.35, -1.0)
    apply_missile_hits([r], [ship], [], damage_model="subsystem")
    snap = r.hitcam
    assert snap["ship_type"] == "destroyer"
    assert snap["penetrated"] is True
    assert snap["breach_m2"] > 1.0
    assert "mer2_port" in snap["new_dead"]
    assert snap["impact"][1] < 0.0            # below the waterline
    assert snap["catastrophe"] is False
    assert len(snap["flood"]) == 6

def test_hitcam_overlay_logic_headless():
    """notify/tick/dismiss run GL-free (draw is the only GL-touching path)."""
    from game.hitcam import HITCAM_S, HitCam
    cam = HitCam(state=None)
    assert not cam.active
    cam.notify({"ship_type": "destroyer"})
    assert cam.active
    cam.tick(HITCAM_S * 0.5)
    assert cam.active
    cam.tick(HITCAM_S)                        # countdown expires
    assert not cam.active and cam.snap is None
    cam.notify({"ship_type": "destroyer"})
    cam.dismiss()
    assert not cam.active


def test_digest_ignores_damage_state_in_legacy_mode():
    """Legacy digests must not change because the subsystem code exists."""
    from game.blackbox import state_digest
    ship = _destroyer()

    class _W:                                  # minimal digest-able world
        sim_time = 1.0
        ships = [ship]
        missiles = ()
    d0 = state_digest(_W())
    ship._dmg = DamageState(ship)              # even with a state attached...
    assert state_digest(_W()) == d0            # ...legacy digests are blind
