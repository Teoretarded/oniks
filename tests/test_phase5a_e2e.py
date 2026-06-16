"""COMBAT Phase 5a end-to-end (GL-free): the air war scaffolding.

Covers the integration seams wired in world/combat.py (NO weapons
employment — fighters fly and rearm but never shoot; that is 5b):

  * Order of battle: exactly ONE carrier in ``ships`` (Oniks-targetable,
    contact-picture fed, defense-controller covered), 2 fighters at the
    airfield + 2 on the carrier and one AWACS in ``enemy_air`` (NOT the
    legacy ``aircraft`` list), two AirBases wrapping airfield + carrier.
  * Placement pins (LOCKED): the airfield on dry enemy-continent land
    across its full runway span; the carrier anchor in verified open
    water inside the spawn-zone carrier band.
  * The standing-CAP scheduler keeps CAP_TARGET_AIRBORNE fighters
    rotating; bingo fuel forces RTB to the nearest surviving base and
    the rearm queue turns the fighter around.
  * Airfield destruction: a dead base launches no sorties and airborne
    fighters divert to the carrier; both bases dead -> winchester egress.
  * Player picture: CAP fighters at altitude form gated air tracks; the
    AWACS stays UNSEEN beyond the player radar's range (fog honesty).
  * Drone ELINT hears the AWACS and airborne fighter nose radars by
    construction (and never a silenced one).
  * Enemy picture symmetry: AWACS datalink cueing lets a destroyer form
    and engage a track its own silent SPY-1 never saw — while terminal
    SARH illumination stays own-ship (the documented seam).
  * Carrier hp ladder: damage control contains single-hit fires (big HP
    pool, spec 5.4) and a REAL Oniks launched from the base lands the
    first hit; fixed-installation fog of war (SAR reveals the airfield,
    knowledge latches).
  * SANDBOX untouched: WorldState carries none of the Phase-5a fields.

Physics at the locked 120 Hz step where rounds fly; coarse steps where
nothing ballistic is in the air (the established e2e pattern).
"""

import numpy as np
import pytest

from sim.contacts import TRACK_DROP_S
from sim.damage import apply_missile_hits
from sim.enemy_air import (FS_ON_STATION, FS_PARKED, FS_REARMING, FS_RTB,
                           FS_TAKEOFF, FS_TRANSIT, FS_WINCHESTER_EGRESS,
                           AirBase, Awacs, Carrier, Fighter)
from sim.enemy_defense import EnemyDefenseController, TRACK_FORM_S
from sim.missile import PH_CRUISE, Missile
from sim.arsenal import ONIKS, SM2
from sim.sam import SamMissile
from sim.ships import (BURN_TIME, ST_ALIVE, ST_BURNING, ST_SINKING)
from world.combat import (AIRFIELD_XZ, CAP_TARGET_AIRBORNE,
                          CARRIER_ANCHOR_XZ, COMBAT_SITES, CombatWorld)
from world.generation import BASE_POS, terrain_height_scalar
from world.spawn_zones import (CARRIER_RANGE_MAX_M, CARRIER_RANGE_MIN_M,
                               is_open_water)
from world.world import WorldState

DT = 1.0 / 120.0
DT_COARSE = 0.5     # nothing ballistic flies: rate-based machinery only

AIRBORNE_STATES = (FS_TAKEOFF, FS_TRANSIT, FS_ON_STATION)


def _fighters(w):
    return [e for e in w.enemy_air if isinstance(e, Fighter)]


def _airborne(w):
    return [f for f in _fighters(w) if f.state in AIRBORNE_STATES]


# ---------------------------------------------------------------------------
# Order of battle
# ---------------------------------------------------------------------------

def test_order_of_battle():
    w = CombatWorld()
    carriers = [s for s in w.ships if isinstance(s, Carrier)]
    assert len(carriers) == 1                      # spec 5.4: always exactly 1
    assert carriers[0].ship_type == "carrier"
    assert carriers[0] is w.carrier
    # Oniks-targetable / defense-covered like any hull.
    assert w.carrier in [u.ship for u in w.defense.units]
    fighters = _fighters(w)
    assert [f.aircraft_id for f in fighters] == [
        "fighter_00", "fighter_01", "fighter_02", "fighter_03"]
    assert all(f.state == FS_PARKED for f in fighters)
    awacs = [e for e in w.enemy_air if isinstance(e, Awacs)]
    assert len(awacs) == 1 and awacs[0] is w.awacs
    # Enemy air is NOT the legacy sandbox aircraft list.
    assert w.aircraft == []
    # Two recovery bases: the airfield structure and the carrier.
    assert len(w.air_bases) == 2
    assert all(isinstance(b, AirBase) for b in w.air_bases)
    assert w.air_bases[0]._site is w.airfield
    assert w.air_bases[1]._site is w.carrier
    # 2 parked per base at spawn.
    assert len(w.air_bases[0].parked) == 2
    assert len(w.air_bases[1].parked) == 2
    # The airfield is an ENEMY structure (player-missile sweep target),
    # never part of the player base structure list.
    # Phase 7: DEFAULT config includes n_enemy_radars=2 ground radar structures
    # in enemy_structures alongside the airfield — check airfield is FIRST and
    # present, not that it's the only entry (updated to Phase 7 truth).
    assert w.enemy_structures[0] is w.airfield
    assert w.airfield in w.enemy_structures
    assert w.airfield not in w.structures


def test_airfield_pin_is_on_dry_enemy_land():
    """LOCKED placement contract: the 2.5 km runway footprint sits on dry
    land on the ENEMY continent (z >= 500 km band) — nudge the pin in
    world/combat.py if generation ever changes."""
    ax, az = AIRFIELD_XZ
    assert az >= 500_000.0                          # enemy continent side
    for dz in (-1_250.0, 0.0, 1_250.0):             # runway ends + midfield
        for dx in (-225.0, 0.0, 225.0):             # full OBB x span
            assert terrain_height_scalar(ax + dx, az + dz) > 5.0
    # The structure itself stands ON the terrain (not floating/buried).
    w = CombatWorld()
    assert w.airfield.pos[1] == terrain_height_scalar(ax, az)


def test_carrier_anchor_open_water_inside_band():
    """LOCKED placement contract: the fixed 5a anchor sits in verified
    open water (the spawn-zone 9 km clearance disc) inside the carrier
    band the Phase-7 seeded placement will sample from."""
    cx, cz = CARRIER_ANCHOR_XZ
    assert is_open_water(cx, cz)
    rng = float(np.hypot(cx - BASE_POS[0], cz - BASE_POS[2]))
    assert CARRIER_RANGE_MIN_M <= rng <= CARRIER_RANGE_MAX_M


# ---------------------------------------------------------------------------
# Standing CAP rotation
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_cap_scheduler_keeps_two_airborne():
    """The commander-managed CAP (5b: replaces the 5a scheduler with the
    same rotation rules) launches one fighter per check until
    CAP_TARGET_AIRBORNE are up (round-robin across the live bases), and
    never overshoots.  Updated to the 5b truth: the player radar runs
    SILENT here so the commander generates no strike packages — with the
    radar emitting it correctly launches a HARM package at the 90 s ESM
    fix on top of the CAP (the war starts; covered by the 5b e2e)."""
    w = CombatWorld()
    w.radar_station.emitting = False
    max_up = 0
    for _ in range(int(600.0 / DT_COARSE)):
        w.step(DT_COARSE)
        max_up = max(max_up, len(_airborne(w)))
    up = _airborne(w)
    assert len(up) == CAP_TARGET_AIRBORNE == 2
    assert max_up <= CAP_TARGET_AIRBORNE
    # Round-robin: one from the airfield, one from the carrier.
    assert {f.aircraft_id for f in up} == {"fighter_00", "fighter_02"}
    # Both climbed to patrol altitude and the rest are still parked.
    assert all(f.pos[1] > 8_000.0 for f in up)
    assert sum(1 for f in _fighters(w) if f.state == FS_PARKED) == 2


@pytest.mark.slow
def test_bingo_rtb_lands_and_rearms_through_world_step():
    """Integration of the fuel/RTB/rearm loop THROUGH CombatWorld.step:
    the world passes the bases list (bingo silently no-ops without it)
    and ticks the rearm queues."""
    w = CombatWorld()
    for _ in range(int(600.0 / DT_COARSE)):
        w.step(DT_COARSE)
    f = next(iter(_airborne(w)))
    f._fuel_s = f._bingo_s + 1.0                # force bingo
    # Shorten the 5 m/s descent from 9 km (test setup, not a behavior
    # change): drop the airframe to pattern altitude first.
    f.pos[1] = 600.0
    saw_rtb = saw_rearm = False
    for _ in range(int(2_000.0 / DT_COARSE)):
        w.step(DT_COARSE)
        saw_rtb = saw_rtb or f.state == FS_RTB
        saw_rearm = saw_rearm or f.state == FS_REARMING
        if saw_rearm and f.state == FS_PARKED:
            break
    assert saw_rtb and saw_rearm
    assert f.state == FS_PARKED
    assert f._fuel_s == 0.0                     # fresh tanks after rearm


def test_airfield_killed_stops_sorties_and_diverts_airborne():
    """Spec 5.5: a destroyed airfield flies no more sorties; airborne
    fighters divert to the carrier (nearest SURVIVING base)."""
    w = CombatWorld()
    for _ in range(int(120.0 / DT_COARSE)):     # first two launches roll
        w.step(DT_COARSE)
    up = _airborne(w)
    assert len(up) >= 1
    f = up[0]
    # Put the airborne fighter right over the airfield so the airfield
    # WOULD be its nearest base — then crater it.
    f.pos[0], f.pos[2] = float(AIRFIELD_XZ[0]), float(AIRFIELD_XZ[1])
    while w.airfield.alive:
        w.airfield.hit()
    assert not w.air_bases[0].alive             # AirBase mirrors the kill
    f._fuel_s = f._bingo_s + 1.0                # force the recovery decision
    for _ in range(int(10.0 / DT_COARSE)):
        w.step(DT_COARSE)
    assert f.state == FS_RTB
    assert f._base is w.air_bases[1]            # diverted to the carrier
    # Fighters parked at the dead airfield never launch again.
    grounded = [g for g in _fighters(w)
                if g.state == FS_PARKED and g._base is w.air_bases[0]]
    assert grounded                             # at least one stranded
    for _ in range(int(60.0 / DT_COARSE)):
        w.step(DT_COARSE)
    assert all(g.state == FS_PARKED for g in grounded)


def test_both_bases_dead_winchester_egress():
    """Spec 5.1: both bases destroyed -> airborne fighters fly to the map
    edge and are out of the war."""
    w = CombatWorld()
    for _ in range(int(120.0 / DT_COARSE)):
        w.step(DT_COARSE)
    f = _airborne(w)[0]
    while w.airfield.alive:
        w.airfield.hit()
    w.carrier.state = ST_SINKING                # carrier dies too
    f._fuel_s = f._bingo_s + 1.0
    for _ in range(int(10.0 / DT_COARSE)):
        w.step(DT_COARSE)
    assert f.state == FS_WINCHESTER_EGRESS
    p0 = f.pos.copy()
    for _ in range(int(60.0 / DT_COARSE)):
        w.step(DT_COARSE)
    # Still egressing on its way out (GONE only at the 700 km edge),
    # covering ground at cruise speed the whole way.
    assert f.state == FS_WINCHESTER_EGRESS
    assert float(np.hypot(f.pos[0] - p0[0], f.pos[2] - p0[2])) > 10_000.0


# ---------------------------------------------------------------------------
# Player picture + drone ELINT
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_enemy_air_feeds_gated_picture_awacs_stays_unseen():
    """CAP fighters at 9 km inside the player radar's 350 km 'fighter'
    range form air tracks; the AWACS orbits 405+ km out — past the range
    gate — and must never appear (fog of war honesty both ways)."""
    w = CombatWorld()
    fighter_track = None
    for _ in range(int(600.0 / DT_COARSE)):
        w.step(DT_COARSE)
        if fighter_track is None:
            fighter_track = next(
                (cid for cid in w.contacts.tracks
                 if cid.startswith("fighter_")), None)
    assert fighter_track is not None
    assert w.contacts.tracks[fighter_track]["is_air"]
    assert "awacs_00" not in w.contacts.tracks
    # The S-300 can resolve the tracked fighter entity (launch gate path).
    assert w._find_air_entity(fighter_track) is not None


@pytest.mark.slow
def test_drone_elint_hears_awacs_and_airborne_fighters():
    """The AWACS emits in 5a and airborne fighter nose radars search:
    both join the drone's passive emitter list by construction.  A
    parked fighter radiates nothing."""
    w = CombatWorld()
    parked_radar_ids = {f"{f.aircraft_id}_radar" for f in _fighters(w)}
    for _ in range(int(5.0 / DT_COARSE)):
        w.step(DT_COARSE)
    # AWACS heard immediately: 420 km < the 450 km ELINT cap, both
    # platforms high, ocean between (LOS/horizon honest).
    assert w.elint.last_heard("awacs_00_radar") is not None
    # No fighter is airborne yet at t=2.5 s except the first takeoff at
    # ground level 280+ km out... which IS airborne the moment it rolls.
    # The honest no-emission assertion is about PARKED airframes:
    airborne_ids = {f"{f.aircraft_id}_radar" for f in _airborne(w)}
    for rid in parked_radar_ids - airborne_ids:
        assert w.elint.last_heard(rid) is None
    # Spin the CAP up: an airborne nose radar becomes audible.
    heard_fighter = None
    for _ in range(int(500.0 / DT_COARSE)):
        w.step(DT_COARSE)
        heard_fighter = next(
            (rid for rid in (f"{f.aircraft_id}_radar" for f in _airborne(w))
             if w.elint.last_heard(rid) is not None), None)
        if heard_fighter is not None:
            break
    assert heard_fighter is not None


def test_silenced_awacs_is_never_heard():
    w = CombatWorld()
    w.awacs.radar.emitting = False
    for _ in range(int(20.0 / DT_COARSE)):
        w.step(DT_COARSE)
    assert w.elint.last_heard("awacs_00_radar") is None


def test_sar_overflight_reveals_airfield_and_latches():
    """Fixed-installation fog of war: the airfield is absent from the map
    until the drone's SAR strip images it; the knowledge then LATCHES
    (installations don't move) even after the drone leaves."""
    w = CombatWorld()
    assert w.known_enemy_sites == []
    drone = w.drone
    drone.pos[0], drone.pos[2] = AIRFIELD_XZ[0], AIRFIELD_XZ[1] - 10_000.0
    drone.set_route([(AIRFIELD_XZ[0], AIRFIELD_XZ[1] - 9_000.0)])
    for _ in range(int(5.0 / DT_COARSE)):
        w.step(DT_COARSE)
    assert w.airfield_known
    # The airfield marker is now revealed.  (Phase 7 fog-of-war extends the
    # same SAR-imaging latch to enemy ground radars; the DEFAULT config's
    # enemy_radar_01 sits ~9 km from this overflight point, inside the 25 km
    # SAR strip, so it is legitimately imaged here too — assert the airfield
    # is present rather than over-specifying the exact set.)
    assert "airfield_enemy_00" in [s["id"] for s in w.known_enemy_sites]
    # Latched: fly the drone home, the marker stays.
    drone.pos[0], drone.pos[2] = BASE_POS[0], BASE_POS[2]
    drone.set_route([])
    for _ in range(int(5.0 / DT_COARSE)):
        w.step(DT_COARSE)
    assert w.airfield_known


# ---------------------------------------------------------------------------
# Enemy picture symmetry: AWACS datalink cueing
# ---------------------------------------------------------------------------

class _AllSeeingCue:
    """Stand-in AWACS radar: holds every track (the geometry-correct AWACS
    is exercised through CombatWorld; this isolates the datalink seam)."""

    radar_id = "awacs_cue"
    alive = True
    emitting = True

    def detects(self, pos, size_class):
        return True


def _mid_cruise_oniks(pos, vel):
    """A real Missile teleported into mid-cruise (the controller's hostile
    filter is an isinstance check — test_enemy_defense.py pattern)."""
    m = Missile(ONIKS, np.array(pos, dtype=np.float64), 0.0, "hi-lo",
                np.zeros(3))
    m.vel[:] = vel
    m.prev_pos[:] = m.pos
    m.phase = PH_CRUISE
    return m


class _StubWorld:
    def __init__(self):
        self.missiles = []
        self.events = []
        self.sim_time = 0.0


def test_awacs_cue_forms_track_own_radar_silent():
    """The datalink seam: a destroyer whose own SPY-1 is SILENT still
    forms a fire-control track and launches on an AWACS-held contact —
    while the round's terminal illuminator stays the launching ship
    (SARH lock-break machinery unchanged)."""
    from sim.enemy_ships import Destroyer
    anchor = (-40_000.0, 320_000.0)
    d = Destroyer("dd_cue", anchor)
    d.radar.emitting = False                    # own radar dark
    ctrl = EnemyDefenseController([d], cue_radars_fn=lambda: [_AllSeeingCue()])
    w = _StubWorld()
    w.missiles.append(_mid_cruise_oniks(
        (anchor[0], 14_000.0, anchor[1] - 100_000.0), (0.0, 0.0, 680.0)))
    for _ in range(int(round((TRACK_FORM_S + 1.0) / DT))):
        w.sim_time += DT
        d.update(DT)
        ctrl.step(w, DT)
    # SM-2 channel only (the SM-6 area channel may co-fire on the same cue;
    # this test pins the SM-2 datalink seam).
    sams = [m for m in w.missiles
            if isinstance(m, SamMissile) and m.weapon is SM2]
    assert len(sams) == 1                       # engaged on the cue alone
    # Terminal seam: illumination is the OWN ship, not the cue source.
    ix, iy, iz = sams[0].illuminator_pos_fn()
    assert abs(ix - d.pos[0]) < 1.0 and abs(iz - d.pos[2]) < 1.0


def test_no_cue_silent_radar_stays_blind():
    """Control for the seam: without the cue the silent ship never
    forms the track (pre-5a behavior preserved by default)."""
    from sim.enemy_ships import Destroyer
    anchor = (-40_000.0, 320_000.0)
    d = Destroyer("dd_blind", anchor)
    d.radar.emitting = False
    ctrl = EnemyDefenseController([d])
    w = _StubWorld()
    w.missiles.append(_mid_cruise_oniks(
        (anchor[0], 14_000.0, anchor[1] - 100_000.0), (0.0, 0.0, 680.0)))
    for _ in range(int(round((TRACK_FORM_S + 1.0) / DT))):
        w.sim_time += DT
        d.update(DT)
        ctrl.step(w, DT)
    assert [m for m in w.missiles if isinstance(m, SamMissile)] == []


# ---------------------------------------------------------------------------
# Carrier hp ladder
# ---------------------------------------------------------------------------

class _SweepStub:
    """Player-round duck-type whose segment sweeps the carrier OBB
    (phase-3 e2e pattern, applied through sim.damage.apply_missile_hits)."""

    def __init__(self, start, delta):
        self.pos = np.asarray(start, dtype=np.float64).copy()
        self.prev_pos = self.pos - np.asarray(delta, dtype=np.float64)
        self.alive = True
        self.phase = 0
        self.impact_pos = None

    def velocity(self):
        return np.zeros(3)


def _stub_hit(carrier, events):
    mid = carrier.pos + np.array([0.0, 5.0, 0.0])
    m = _SweepStub(mid + np.array([60.0, 0.0, 0.0]),
                   np.array([120.0, 0.0, 0.0]))
    apply_missile_hits([m], [carrier], events)
    assert not m.alive                          # the sweep connected


def test_carrier_damage_control_contains_single_hit():
    """Spec 5.4 'big HP pool': one hit burns but damage control contains
    the fire — the carrier resumes ALIVE with hp 5 instead of riding the
    destroyer ladder's terminal burn to the bottom."""
    w = CombatWorld()
    c = w.carrier
    events = []
    _stub_hit(c, events)
    assert c.hp == 5 and c.state == ST_BURNING
    assert ("ship_hit" in [k for k, _ in events])
    for _ in range(int((BURN_TIME + 2.0) / DT_COARSE)):
        c.update(DT_COARSE)
    assert c.state == ST_ALIVE and c.hp == 5    # fire contained
    assert c.alive                              # still a target


def test_carrier_sinks_only_at_hp_zero():
    w = CombatWorld()
    c = w.carrier
    events = []
    for i in range(6):
        assert c.state != ST_SINKING
        _stub_hit(c, events)
    assert c.hp == 0 and c.state == ST_SINKING
    assert not c.alive                          # off the targetable list


@pytest.mark.slow
def test_real_oniks_first_hit_on_the_carrier():
    """A REAL Oniks launched from the base TEL flies the full hi-lo
    profile ~281 km into the carrier's OBB (enemy interceptors emptied —
    this test pins the damage ladder, not the SM-2 duel).  Carrier takes
    exactly one hit: hp 6 -> 5, BURNING — and stays afloat."""
    w = CombatWorld()
    for d in w.ships:                           # disarm the escort screen
        d.sm2_ammo = 0
        d.sm6_ammo = 0                          # incl. the SM-6 area channel
        d.ciws_ammo = 0
    c = w.carrier
    target = c.pos.copy()
    target[1] = 0.0
    m = w.launch("hi-lo", target)
    assert m is not None
    hit_time = None
    for _ in range(int(700.0 / DT)):
        w.step(DT)
        if any(kind == "ship_hit" for kind, _ in w.drain_events()):
            hit_time = w.sim_time
            break
    assert hit_time is not None, "Oniks never reached the carrier"
    assert c.hp == 5 and c.state == ST_BURNING
    assert c.alive                              # one hit does NOT kill her


# ---------------------------------------------------------------------------
# Sandbox untouched
# ---------------------------------------------------------------------------

def test_sandbox_untouched():
    """The SANDBOX world carries none of the Phase-5a machinery: no
    carrier, no enemy air, no air bases, no enemy structures — and its
    14-ship lane traffic is unchanged."""
    w = WorldState()
    assert not hasattr(w, "enemy_air")
    assert not hasattr(w, "air_bases")
    assert not hasattr(w, "enemy_structures")
    assert not hasattr(w, "carrier")
    assert len(w.ships) == 14
    assert all(s.ship_type in ("cargo", "tanker", "warship")
               for s in w.ships)
    # COMBAT sites object is still the locked Phase-2 list (the airfield
    # reaches the map only through known_enemy_sites, never sites).
    cw = CombatWorld()
    assert cw.sites is COMBAT_SITES
