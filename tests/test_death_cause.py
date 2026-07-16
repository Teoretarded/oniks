"""Death-cause channel — WHY each recorded round died + the fog OBSERVED flag.

Two layers under test (handoff spec, 2026-07-03):

* SIM KILL-SITE STAMPS: each kill site writes ``m.death_cause`` (a
  ``(code, detail)`` tuple) and ``m.killed_by`` (the killer object) onto the
  DEAD round.  WRITE-ONLY: no sim code ever reads either attribute — the sim
  digest stays byte-locked.  Sites: SamMissile fuse (sim/sam.py), IrMissile
  fuse (sim/a2a.py), ship CIWS (sim/enemy_defense.py), Pantsir 30 mm
  (sim/pantsir.py), ship hull hit (sim/damage.py), ARM radar kill
  (sim/strike.py).

* RECORDER CLASSIFICATION: FlightRecorder closes each round with
  ``rec["cause"] = dict(code, detail, observed)`` read from the dead round's
  OWN attributes.  FOG RULE (user-locked, v1 honest): ``observed`` is True
  ONLY IF the killer was itself a track in ``world.contacts.tracks`` at kill
  time; self-causes (fuel / impact / own-fuse hit) are own-force telemetry —
  always observed.  A round that vanished with no stamp and no impact closes
  as ("lost", observed False) — the recorder never claims more than it saw.

Plus the two recorder extensions the debrief plots need: ``target_xz``
(stamped at pickup from the round's own aim point) and phase-transition
``events`` (stamped on ``phase_label`` changes).
"""

import math

import numpy as np

from game.flight_recorder import FlightRecorder

DT = 1.0 / 120.0


# ---------------------------------------------------------------------------
# Fakes (house style: tests/test_flight_recorder.py)
# ---------------------------------------------------------------------------

class _Round:
    def __init__(self, hostile=False, kind="oniks"):
        self.is_hostile = hostile
        self.alive = True
        self.weapon_id = kind
        self.pos = np.array([0.0, 100.0, 0.0])

    def fly_to(self, x, y, z):
        self.pos = np.array([float(x), float(y), float(z)])


class _Contacts:
    def __init__(self):
        self.tracks = {}


class _World:
    def __init__(self):
        self.sim_time = 0.0
        self.missiles = []
        self.contacts = _Contacts()

    def tick(self, dt=DT):
        self.sim_time += dt


def _run(world, rec, steps):
    for _ in range(steps):
        world.tick()
        rec.update(world)


def _fly_and_kill(world, rec, m, steps=30, **stamps):
    """Fly ``m`` for ``steps``, apply the kill-site stamps, mark dead, step
    once more so the recorder observes the death, and return its record."""
    _run(world, rec, steps)
    for name, value in stamps.items():
        setattr(m, name, value)
    m.alive = False
    _run(world, rec, 1)
    return rec.rounds()[0]


class _Killer:
    """A killer with the contact-board identity key (aircraft_id)."""

    def __init__(self, cid="sm6_01"):
        self.aircraft_id = cid


class _KillerShip:
    def __init__(self, cid="dd_01"):
        self.ship_id = cid


# ===========================================================================
# 1. Recorder classification — stamped killer causes + the observed gate
# ===========================================================================

def test_sam_kill_observed_when_killer_was_tracked():
    w = _World(); r = FlightRecorder()
    m = _Round(); w.missiles.append(m)
    killer = _Killer("sm6_01")
    w.contacts.tracks["sm6_01"] = dict(pos=None)     # killer IS on the picture
    rec = _fly_and_kill(w, r, m,
                        death_cause=("sam", "sm6"), killed_by=killer)
    assert rec["cause"] == {"code": "sam", "detail": "sm6", "observed": True}


def test_sam_kill_unobserved_when_killer_untracked():
    """The killer interceptor never made the player picture: the cause is
    recorded (post-battle AAR truth) but observed=False gates the mid-battle
    display to LOST - UNCONFIRMED."""
    w = _World(); r = FlightRecorder()
    m = _Round(); w.missiles.append(m)
    rec = _fly_and_kill(w, r, m,
                        death_cause=("sam", "sm6"), killed_by=_Killer("x"))
    assert rec["cause"] == {"code": "sam", "detail": "sm6", "observed": False}


def test_ciws_kill_observed_via_ship_track():
    w = _World(); r = FlightRecorder()
    m = _Round(); w.missiles.append(m)
    ship = _KillerShip("dd_02")
    w.contacts.tracks["dd_02"] = dict(pos=None)
    rec = _fly_and_kill(w, r, m,
                        death_cause=("ciws", "destroyer"), killed_by=ship)
    assert rec["cause"] == {"code": "ciws", "detail": "destroyer",
                            "observed": True}


def test_hit_stamp_carries_ship_kind():
    w = _World(); r = FlightRecorder()
    m = _Round(); w.missiles.append(m)
    ship = _KillerShip("cv_01")
    w.contacts.tracks["cv_01"] = dict(pos=None)
    rec = _fly_and_kill(w, r, m,
                        death_cause=("hit", "carrier"), killed_by=ship)
    assert rec["cause"] == {"code": "hit", "detail": "carrier",
                            "observed": True}


# ===========================================================================
# 2. Recorder classification — self causes (own telemetry, always observed)
# ===========================================================================

def test_fuel_exhaustion_from_own_fuel_state():
    """Dry tank + surface impact = FUEL: read from the round's OWN fuel
    attribute, no stamp needed (own-force telemetry, always observed)."""
    w = _World(); r = FlightRecorder()
    m = _Round(); w.missiles.append(m)
    rec = _fly_and_kill(w, r, m, fuel=0.0,
                        impact_pos=np.array([5.0, 0.0, 5.0]))
    assert rec["cause"] == {"code": "fuel", "detail": None, "observed": True}


def test_surface_impact_with_fuel_remaining_is_impact():
    w = _World(); r = FlightRecorder()
    m = _Round(); w.missiles.append(m)
    rec = _fly_and_kill(w, r, m, fuel=42.0,
                        impact_pos=np.array([5.0, 0.0, 5.0]))
    assert rec["cause"] == {"code": "impact", "detail": None,
                            "observed": True}


def test_own_interceptor_fuse_kill_is_hit():
    """A player SAM that fused on its target (killed_target=True): own-round
    outcome, always observed. Detail = the victim's weapon kind when the
    round's own target reference names one."""
    w = _World(); r = FlightRecorder()
    m = _Round(kind="48n6"); w.missiles.append(m)
    victim = _Round(hostile=True, kind="tomahawk")
    rec = _fly_and_kill(w, r, m, killed_target=True, target=victim,
                        impact_pos=np.array([0.0, 900.0, 0.0]))
    assert rec["cause"] == {"code": "hit", "detail": "tomahawk",
                            "observed": True}


def test_vanished_round_closes_lost_unconfirmed():
    """Pruned with no stamp, no impact, no fuse: the recorder states only
    what it saw — LOST, unobserved."""
    w = _World(); r = FlightRecorder()
    m = _Round(); w.missiles.append(m)
    _run(w, r, 30)
    w.missiles.clear()                        # vanished, nothing stamped
    _run(w, r, 1)
    rec = r.rounds()[0]
    assert rec["cause"] == {"code": "lost", "detail": None,
                            "observed": False}


def test_live_round_has_no_cause():
    w = _World(); r = FlightRecorder()
    m = _Round(); w.missiles.append(m)
    _run(w, r, 30)
    assert r.rounds()[0]["cause"] is None


# ===========================================================================
# 3. Recorder extensions — target_xz at pickup + phase events
# ===========================================================================

def test_target_xz_stamped_at_pickup_from_aim_point():
    w = _World(); r = FlightRecorder()
    m = _Round()
    m.target_point = np.array([120_000.0, 0.0, 340_000.0])
    w.missiles.append(m)
    _run(w, r, 2)
    assert r.rounds()[0]["target_xz"] == (120_000.0, 340_000.0)


def test_target_xz_none_when_round_has_no_aim_point():
    w = _World(); r = FlightRecorder()
    m = _Round(); w.missiles.append(m)
    _run(w, r, 2)
    assert r.rounds()[0]["target_xz"] is None


def test_phase_events_stamped_on_label_change():
    w = _World(); r = FlightRecorder()
    m = _Round()
    m.phase_label = "CLIMB"
    w.missiles.append(m)
    _run(w, r, 10)
    m.phase_label = "CRUISE"
    _run(w, r, 10)
    m.phase_label = "DESCENT"
    _run(w, r, 10)
    events = r.rounds()[0]["events"]
    labels = [label for _, label in events]
    assert labels == ["CLIMB", "CRUISE", "DESCENT"]
    times = [t for t, _ in events]
    assert times == sorted(times)
    # Each transition is stamped at the sim clock of the step it was seen.
    assert abs(times[1] - 11 * DT) < 1e-9


# ===========================================================================
# 4. Sim kill-site stamps (write-only; the sim never reads them)
# ===========================================================================

def test_sam_fuse_stamps_victim():
    from sim.arsenal import SM2
    from sim.sam import SamMissile

    class _Victim:
        def __init__(self):
            self.pos = np.array([0.0, 1_000.0, 0.0])
            self.alive = True

    victim = _Victim()
    sam = SamMissile(SM2, np.array([0.0, 10.0, 0.0]), victim)
    # Drive the swept segment straight through the victim: fuse must trigger.
    sam.prev_pos = np.array([0.0, 900.0, 0.0])
    sam.pos = np.array([0.0, 1_100.0, 0.0])
    assert sam._fuse_check() is True
    assert victim.alive is False
    assert victim.death_cause == ("sam", "sm2")
    assert victim.killed_by is sam


def test_a2a_fuse_stamps_victim():
    from sim.a2a import IrMissile

    class _Victim:
        def __init__(self):
            self.pos = np.array([0.0, 5_000.0, 0.0])
            self.alive = True

        def velocity(self):
            return np.zeros(3)

    victim = _Victim()
    m = IrMissile(np.array([0.0, 5_000.0, -3_000.0]),
                  np.array([0.0, 0.0, 300.0]), victim)
    m.prev_pos = np.array([0.0, 5_000.0, -50.0])
    m.pos = np.array([0.0, 5_000.0, 50.0])
    assert m._fuse_check() is True
    assert victim.alive is False
    assert victim.death_cause == ("a2a", "aim9x")
    assert victim.killed_by is m


def test_ciws_kill_stamps_victim_with_ship():
    """The ship CIWS kill (sim/enemy_defense.py consumes the gun events and
    already owns the impact bookkeeping — the stamp lands there, where the
    real round and the firing ship are both in scope)."""
    from sim.arsenal import ONIKS
    from sim.enemy_defense import EnemyDefenseController, TRACK_FORM_S
    from sim.enemy_ships import Destroyer
    from sim.missile import PH_CRUISE, Missile

    class _ZeroRng:
        def random(self):
            return 0.0

        def standard_normal(self, n=None):
            return 0.0 if n is None else np.zeros(n)

    class _StubWorld:
        def __init__(self):
            self.missiles = []
            self.events = []
            self.sim_time = 0.0

    anchor = (-40_000.0, 320_000.0)
    d = Destroyer("dd_stamp", anchor)
    ctrl = EnemyDefenseController([d], rng=_ZeroRng())
    w = _StubWorld()
    leaker = Missile(ONIKS, np.array([anchor[0], 60.0, anchor[1] - 1_200.0]),
                     0.0, "lo-lo", np.zeros(3))
    leaker.vel[:] = (0.0, 0.0, 680.0)
    leaker.prev_pos[:] = leaker.pos
    leaker.phase = PH_CRUISE
    w.missiles.append(leaker)
    for _ in range(int(round((TRACK_FORM_S + 3.0) / DT))):
        w.sim_time += DT
        d.update(DT)
        ctrl.step(w, DT)
        if not leaker.alive:
            break
    assert leaker.alive is False
    assert leaker.death_cause == ("ciws", "destroyer")
    assert leaker.killed_by is d


def test_pantsir_gun_kill_stamps_victim():
    from sim.pantsir import Pantsir, PantsirDefenseController, TRACK_FORM_S
    from sim.radar import RadarNetwork

    class _AlwaysKillRng:
        def random(self, *a, **kw):
            return 0.0

        def normal(self, *a, **kw):
            return 0.0

        def uniform(self, *a, **kw):
            return 0.0

        def integers(self, *a, **kw):
            return 0

        def standard_normal(self, n=None):
            # Perfect fire-control solution: zero OU tracking error, so the
            # physics gun gate (sim/ciws.py 2026-07-17) kills every burst.
            return 0.0 if n is None else np.zeros(n)

    class _StubWorld:
        def __init__(self):
            self.missiles = []
            self.events = []
            self.sim_time = 0.0

        @staticmethod
        def terrain_height_at(x, z):
            return -500.0

        @staticmethod
        def surface_height_at(x, z):
            return -500.0

    class _HostileMissile:
        is_hostile = True
        is_air = True
        radar_size = "missile"

        def __init__(self, pos, vel):
            self.pos = np.asarray(pos, dtype=np.float64)
            self.vel = np.asarray(vel, dtype=np.float64)
            self.prev_pos = self.pos.copy()
            self.alive = True
            self.impact_pos = None

        def velocity(self):
            return self.vel.copy()

    pantsir_pos = np.array([0.0, 160.6, -3_000.0])
    p = Pantsir("p_stamp", pantsir_pos, missile_ammo=0,
                rng=_AlwaysKillRng(), radar_network=RadarNetwork())
    ctrl = PantsirDefenseController([p])
    w = _StubWorld()
    threat = _HostileMissile(pantsir_pos + np.array([0.0, 300.0, 2_000.0]),
                             np.array([0.0, 0.0, -0.001]))
    w.missiles.append(threat)
    for _ in range(int(round((TRACK_FORM_S + 4.0) / DT))):
        w.sim_time += DT
        ctrl.step(w, DT)
        if not threat.alive:
            break
    assert threat.alive is False
    assert threat.death_cause == ("pantsir", "30mm")
    assert threat.killed_by is p


def test_ship_hull_hit_stamps_missile():
    from sim.damage import apply_missile_hits
    from sim.ships import Ship

    class _FakeMissile:
        def __init__(self, p0, p1):
            self.prev_pos = np.asarray(p0, dtype=np.float64)
            self.pos = np.asarray(p1, dtype=np.float64)
            self.alive = True
            self.phase = 5
            self.impact_pos = None

    ship = Ship("c", "cargo", [(0.0, 0.0), (0.0, 50_000.0)], 0.5)
    c, _, _ = ship.obb()
    m = _FakeMissile(c + np.array([-200.0, 0.0, 0.0]),
                     c + np.array([40.0, 0.0, 0.0]))
    apply_missile_hits([m], [ship], [])
    assert not m.alive
    assert m.death_cause == ("hit", "cargo")
    assert m.killed_by is ship


def test_arm_radar_kill_stamps_itself():
    """A player ARM that fused on a LIVE radar records its own success
    (self-stamp: the round is both actor and record)."""
    from sim.arsenal import HARM
    from sim.strike import HarmMissile

    class _FakeRadar:
        def __init__(self):
            self.pos = np.array([0.0, 50.0, 0.0])
            self.alive = True
            self.emitting = True

    radar = _FakeRadar()
    m = HarmMissile(HARM, np.array([0.0, 60.0, -9_000.0]),
                    np.array([0.0, 0.0, 300.0]), radar,
                    np.random.default_rng(1))
    m.prev_pos = np.array([0.0, 50.0, -10.0])
    m.pos = np.array([0.0, 50.0, 10.0])
    assert m._fuse_check() is True
    assert radar.alive is False
    assert m.death_cause == ("hit", "radar")
