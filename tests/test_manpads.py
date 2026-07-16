"""Walk-mode MANPADS: physics, seeker, fuse, models and rig wiring.

All GL-free (LOCKED convention). Hit/miss must EMERGE from kinematics —
PN guidance with fin-authority limits, seeker gimbal/track-rate limits,
segment-measured fuses — never a probability roll. Specs researched in
docs/research/manpads_reference.md.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from sim.manpads import (
    GRAVITY,
    ManpadsRound,
    WEAPON_BY_ID,
    WEAPONS,
    air_density,
    drag_coefficient,
)


DT = 1.0 / 240.0            # sim step used throughout (fine, deterministic)


def _flat_ground(x, z):
    return 0.0


def _fly(rnd, seconds, events=None):
    ev = [] if events is None else events
    steps = int(round(seconds / DT))
    for _ in range(steps):
        if rnd.done:
            break
        rnd.step(DT, ev)
    return ev


def _launch(spec_id, direction=(0.0, 0.35, 0.94), target=None,
            ground_point=None, pos=(0.0, 1.7, 0.0), ground_h=_flat_ground):
    spec = WEAPON_BY_ID[spec_id]
    d = np.asarray(direction, dtype=np.float64)
    d = d / np.linalg.norm(d)
    return ManpadsRound(spec, np.asarray(pos, dtype=np.float64), d,
                        target=target, ground_point=ground_point,
                        ground_h=ground_h)


class _Drone:
    """Straight-line target with the ScriptedLaunch duck-type surface."""

    def __init__(self, pos, vel, hot=True):
        self.pos = np.asarray(pos, dtype=np.float64)
        self.vel = np.asarray(vel, dtype=np.float64)
        self.done = False
        self._hot = hot

    def burning(self):
        return self._hot

    def step(self, dt):
        self.pos = self.pos + self.vel * dt


# ---------------------------------------------------------------- specs

def test_four_weapons_with_sane_specs():
    assert len(WEAPONS) == 4
    ids = {s.id for s in WEAPONS}
    assert ids == {"igla_s", "stinger", "piorun", "starstreak"}
    for s in WEAPONS:
        assert 1.3 <= s.length_m <= 1.7
        assert 0.06 <= s.diameter_m <= 0.14
        assert 8.0 <= s.mass_kg <= 16.0
        assert s.eject_v > 15.0
        assert s.boost_thrust_n > 0.0
        assert s.g_limit >= 10.0
        assert s.life_s > 8.0
        assert s.range_m >= 4500.0
        assert s.seeker in ("ir", "beam")


def test_atmosphere_and_drag_curve_shapes():
    assert air_density(0.0) == pytest.approx(1.225, rel=0.01)
    assert air_density(3000.0) < air_density(0.0)
    # Transonic hump: Cd rises through M1, decays supersonic.
    assert drag_coefficient(1.05) > drag_coefficient(0.6)
    assert drag_coefficient(1.05) > drag_coefficient(2.5)
    assert drag_coefficient(3.4) <= drag_coefficient(2.5)


# ------------------------------------------------------------- propulsion

def test_stinger_burnout_speed_window():
    """Mach 2.2+ 'within 2 seconds' (designation-systems): the boost must
    put the round in the published window, drag and gravity included."""
    r = _launch("stinger")
    _fly(r, 2.4)
    v = float(np.linalg.norm(r.vel))
    assert 680.0 <= v <= 830.0


def test_igla_and_piorun_burnout_windows():
    for wid, lo, hi in (("igla_s", 520.0, 660.0), ("piorun", 580.0, 720.0)):
        r = _launch(wid)
        _fly(r, 2.6)
        v = float(np.linalg.norm(r.vel))
        assert lo <= v <= hi, f"{wid} burnout {v:.0f} outside [{lo},{hi}]"


def test_starstreak_is_the_fastest_and_separates_darts():
    r = _launch("starstreak")
    ev = _fly(r, 2.5)
    kinds = [k for k, _p in ev]
    assert "ignite" in kinds and "dart_sep" in kinds
    v = float(np.linalg.norm(r.vel))
    assert v >= 1000.0, "Starstreak must exceed Mach ~3 at dart separation"
    for other in ("igla_s", "stinger", "piorun"):
        o = _launch(other)
        _fly(o, 2.5)
        assert v > float(np.linalg.norm(o.vel))


def test_motor_lights_at_standoff_not_in_the_face():
    """Eject charge coasts the round out before the flight motor lights
    (Stinger ~9 m, Igla family ~5.5 m): the ignite event must not happen
    at the muzzle."""
    for wid, min_d in (("stinger", 6.0), ("igla_s", 3.5)):
        r = _launch(wid)
        ev = _fly(r, 1.5)
        ign = [p for k, p in ev if k == "ignite"]
        assert ign, f"{wid} never ignited"
        d = float(np.linalg.norm(ign[0] - np.array([0.0, 1.7, 0.0])))
        assert d >= min_d


def test_coast_decays_and_gravity_pulls():
    r = _launch("stinger", direction=(0.0, 0.0, 1.0), pos=(0.0, 300.0, 0.0),
                ground_h=lambda x, z: -1e9)
    _fly(r, 9.0)
    assert not r.done
    v1 = float(np.linalg.norm(r.vel))
    vy1 = float(r.vel[1])
    _fly(r, 3.0)
    assert float(np.linalg.norm(r.vel)) < v1     # drag bleeds speed
    assert float(r.vel[1]) < vy1                 # gravity keeps pulling


def test_self_destruct_at_life_end():
    r = _launch("stinger", direction=(0.0, 0.6, 0.8),
                ground_h=lambda x, z: -1e9)
    ev = _fly(r, 30.0)
    assert r.done and not r.hit
    assert any(k == "self_destruct" for k, _p in ev)
    assert r.t <= r.spec.life_s + 0.1


# --------------------------------------------------------------- guidance

def test_pn_intercepts_a_crossing_climber():
    """An S-300-profile target (climbing out at ~1.6 km) must be killable
    by physics alone: the gunner leads (airframe super-elevated toward
    the collision point, seeker gimballed onto the target) and PN trims
    the rest — no scripted hit."""
    tgt = _Drone(pos=(150.0, 220.0, 1600.0), vel=(18.0, 190.0, -35.0))
    r = _launch("igla_s", direction=(0.12, 0.46, 0.88), target=tgt)
    ev = []
    for _ in range(int(12.0 / DT)):
        if r.done:
            break
        tgt.step(DT)
        r.step(DT, ev)
    assert r.hit, f"missed: min approach {r.miss_dist}"


def test_realized_lateral_g_never_exceeds_structural_limit():
    """The fins can bend the path only as hard as the airframe allows: a
    target demanding an impossible turn must not produce super-structural
    acceleration on any step."""
    tgt = _Drone(pos=(60.0, 45.0, 420.0), vel=(-260.0, 5.0, 0.0))
    spec = WEAPON_BY_ID["stinger"]
    r = _launch("stinger", direction=(0.0, 0.1, 1.0), target=tgt)
    prev_v = r.vel.copy()
    worst = 0.0
    for _ in range(int(8.0 / DT)):
        if r.done:
            break
        tgt.step(DT)
        r.step(DT, [])
        acc = (r.vel - prev_v) / DT
        sp = float(np.linalg.norm(r.vel))
        if sp > 1e-6:
            along = np.dot(acc, r.vel) / sp
            lat = math.sqrt(max(float(np.dot(acc, acc)) - along * along,
                                0.0))
            worst = max(worst, lat)
        prev_v = r.vel.copy()
    assert worst <= spec.g_limit * GRAVITY * 1.05


def test_low_dynamic_pressure_starves_the_fins():
    """Right off the tube (v ~ eject, motor unlit) the canards have almost
    no authority: a 90-degree-off target must not bend the path yet.
    The target sits at +X, so any homing shows up as sideways velocity
    (super-elevation only pitches, never yaws)."""
    spec = WEAPON_BY_ID["stinger"]          # no gas-piston assist
    tgt = _Drone(pos=(500.0, 1.7, 0.0), vel=(0.0, 0.0, 0.0))
    r = ManpadsRound(spec, np.array([0.0, 1.7, 0.0]),
                     np.array([0.0, 0.0, 1.0]), target=tgt,
                     ground_h=lambda x, z: -1e9)
    r.step(0.05, [])
    v = r.vel / max(float(np.linalg.norm(r.vel)), 1e-9)
    assert abs(float(v[0])) < 1e-3, "path bent with no dynamic pressure"


def test_gimbal_limit_breaks_lock_to_ballistic():
    """A target dragged far off the nose (beyond the seeker gimbal) must
    break lock; afterwards the round flies ballistic (no homing)."""
    spec = WEAPON_BY_ID["igla_s"]
    tgt = _Drone(pos=(0.0, 260.0, 500.0), vel=(640.0, 0.0, 0.0))
    r = _launch("igla_s", direction=(0.0, 0.45, 0.89), target=tgt,
                ground_h=lambda x, z: -1e9)
    ev = []
    for _ in range(int(10.0 / DT)):
        if r.done:
            break
        tgt.step(DT)
        r.step(DT, ev)
    assert any(k == "lock_lost" for k, _p in ev)
    assert not r.hit


def test_terrain_occlusion_breaks_lock():
    """A ridge rising between seeker and target must break the IR lock."""
    tgt = _Drone(pos=(0.0, 60.0, 2400.0), vel=(0.0, 0.0, 0.0))
    wall_on = {"z": False}

    def ground(x, z):
        # A 400 m wall at z=1200 that appears 1 s into flight.
        if wall_on["z"] and 1100.0 < z < 1300.0:
            return 400.0
        return 0.0

    r = _launch("igla_s", direction=(0.0, 0.03, 1.0), target=tgt,
                ground_h=ground)
    ev = []
    for i in range(int(6.0 / DT)):
        if r.done:
            break
        if i == int(1.0 / DT):
            wall_on["z"] = True
        r.step(DT, ev)
    assert any(k == "lock_lost" for k, _p in ev)


def test_beam_rider_hits_a_ground_point():
    """Starstreak steered at a designated ground point 3 km out must
    arrive within a couple of meters — SACLOS has no seeker to lose."""
    gp = np.array([120.0, 0.0, 3000.0])
    r = _launch("starstreak", direction=(0.05, 0.06, 1.0), ground_point=gp)
    ev = _fly(r, 9.0)
    assert r.done
    kinds = [k for k, _p in ev]
    assert "ground" in kinds or "hit" in kinds
    end = ev[-1][1]
    assert float(np.linalg.norm(np.asarray(end)[[0, 2]] - gp[[0, 2]])) < 8.0


def test_ir_weapon_falls_to_ground_impact_event():
    """An IR round fired into terrain with no target must fly ballistic
    and end with a ground event where the trajectory meets the DTM."""
    r = _launch("igla_s", direction=(0.0, -0.4, 0.92))
    ev = _fly(r, 20.0)
    assert r.done
    assert any(k == "ground" for k, _p in ev)


# ------------------------------------------------------------------- fuse

def test_prox_fuse_catches_between_step_crossing():
    """A Mach-2 crossing target passes CLOSER than the prox radius only
    BETWEEN two integration steps — the segment fuse must still fire."""
    spec = WEAPON_BY_ID["igla_s"]
    assert spec.prox_radius_m > 0.0
    # Head-on pass, 2 m offset: closing speed ~1.8 km/s moves the relative
    # position ~7.5 m per 240 Hz step, so the closest approach can happen
    # BETWEEN integration steps — only a segment fuse reliably sees it.
    tgt = _Drone(pos=(2.0, 1.7, 3000.0), vel=(0.0, 0.0, -1200.0))
    r = _launch("igla_s", direction=(0.0, 0.0, 1.0), target=tgt,
                ground_h=lambda x, z: -1e9)
    hit = False
    for _ in range(int(10.0 / DT)):
        if r.done:
            hit = r.hit
            break
        tgt.step(DT)
        r.step(DT, [])
    assert hit, f"prox fuse missed a crossing target ({r.miss_dist})"


def test_victims_fuse_frags_a_passing_round():
    """The warhead does not care what it was aimed at: a round passing a
    DIFFERENT object inside the fuse envelope kills it. The sim is
    deterministic, so a dry run gives the exact flight path — park the
    bystander on it and rerun with the victims hook."""
    gp = np.array([0.0, 0.0, 4000.0])

    def make():
        return _launch("igla_s", direction=(0.0, 0.01, 1.0),
                       ground_point=gp, ground_h=lambda x, z: -1e9)

    probe = make()
    _fly(probe, 3.0)
    assert not probe.done
    bystander = _Drone(pos=probe.pos.copy(), vel=(0.0, 0.0, 0.0))
    bystander.radius = 2.0
    r = make()
    r.victims = lambda: [bystander]
    _fly(r, 8.0)
    assert r.hit and r.victim is bystander


def test_capsule_fuse_sees_the_airframe_not_a_point():
    """A pass 3 m off the CENTER of a 7.5 m airframe, near its nose, is
    really a sub-meter pass — the fuse must measure to the body capsule."""
    from sim.manpads import _capsule_min_dist, _segment_min_dist
    axis = np.array([0.0, 0.0, 1.0])
    r0 = np.array([0.5, 8.0, 3.0])
    r1 = np.array([0.5, -8.0, 3.0])     # crossing beside the nose
    point_miss = _segment_min_dist(r0, r1)
    body_miss = _capsule_min_dist(r0, r1, axis, 3.75)
    assert point_miss > 3.0
    assert body_miss == pytest.approx(0.5, abs=0.05)


def test_deterministic_replay_is_bit_identical():
    def run():
        tgt = _Drone(pos=(150.0, 220.0, 1600.0), vel=(18.0, 190.0, -35.0))
        r = _launch("stinger", direction=(0.09, 0.18, 0.98), target=tgt)
        for _ in range(int(6.0 / DT)):
            if r.done:
                break
            tgt.step(DT)
            r.step(DT, [])
        return r.pos.copy(), r.vel.copy(), r.t
    p1, v1, t1 = run()
    p2, v2, t2 = run()
    assert np.array_equal(p1, p2) and np.array_equal(v1, v2) and t1 == t2


# ----------------------------------------------------------------- models

def _check_mesh(md):
    assert md.vertices.dtype == np.float32
    assert md.indices.dtype == np.uint32
    assert len(md.vertices) > 0 and len(md.indices) > 0
    assert md.indices.max() < len(md.vertices)
    assert np.isfinite(md.vertices).all()
    n = md.vertices[:, 3:6]
    assert np.allclose(np.linalg.norm(n, axis=1), 1.0, atol=1e-3)


def test_launcher_and_missile_models_build_for_every_weapon():
    from models.manpads_model import build_launcher, build_missile
    seen = set()
    for s in WEAPONS:
        tube = build_launcher(s.id)
        rnd = build_missile(s.id)
        _check_mesh(tube)
        _check_mesh(rnd)
        # The missile's length must track the researched spec (built along
        # +Z like the other missile models).
        zlen = float(rnd.vertices[:, 2].max() - rnd.vertices[:, 2].min())
        want = s.length_m if not s.dart_sep else s.length_m
        assert zlen == pytest.approx(want, rel=0.08)
        seen.add((len(tube.vertices), len(rnd.vertices)))
    assert len(seen) == 4, "the four weapons must be visually distinct"


def test_dart_model_exists_for_starstreak():
    from models.manpads_model import build_dart
    md = build_dart()
    _check_mesh(md)
    zlen = float(md.vertices[:, 2].max() - md.vertices[:, 2].min())
    assert 0.3 <= zlen <= 0.6


# ------------------------------------------------------------------- rig

def test_weapon_rig_is_importable_headless_and_starts_stowed():
    from game.cinematic_weapons import WeaponRig
    rig = WeaponRig()
    assert rig.weapon is None            # nothing shouldered until chosen
    assert not rig.locker_open
    assert rig.ads == 0.0
