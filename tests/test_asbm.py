"""M4-A Bastion-K ASBM contracts — the lofted quasi-ballistic top-attack
anti-ship round (sim/asbm.py AsbmMissile + sim/arsenal.py BASTION_K).

Every assertion is a MEASURED flight outcome off the real SamMissile
loft+boost+coast+PN+fuse machine (physics, not dice).  ENERGY-MODEL RE-PIN
(2026-07-05, argued): the old 90 km near-vertical lob only reached 250 km
because arresting its own ballistic reentry cost nothing; under induced
drag that shape landed 70+ km short.  The round now flies the DEPRESSED
profile a real MaRV would: ceiling cruise at ~26 km (above the SM-2's
24 km engagement ceiling — the design discriminator, now asserted
directly), then a late gravity-powered plunge steepening through terminal.
Bands re-locked to tools/probe_asbm_flyoff.py (2026-07-05):

    range  apogee  handover-FPA  terminal-min-FPA  peakMach  reentryMach
    100km  26.0km    -25.2 deg      -70.7 deg        4.66       3.03
    200km  26.0km    -25.1 deg      -67.4 deg        4.66       2.13  <- probe range
    250km  (10+ km short — the honest drag-limited envelope edge)

The stale-picture miss / fresh-track kill pair proves the miss comes
from guiding on a STALE estimate, never a kill roll.
"""

import math

import numpy as np

from sim.arsenal import BASTION_K
from sim.asbm import AsbmMissile
from sim.sam import SPH_MIDCOURSE, SPH_TERMINAL

DT = 1.0 / 120.0
LAUNCH = np.array([0.0, 5.0, 0.0])
PROBE_RANGE = 200_000.0           # the locked-band range (matches the probe;
#                                   inside the measured 230 km honest reach)


class _World:   # minimal stub: open ocean, ships injected per test
    def __init__(self, ships=()):
        self.ships = list(ships)

    def terrain_height_at(self, x, z):
        return -50.0              # open ocean: surface is sea level (y=0)


class _StaticShip:
    """A stationary hull at sea level (deck ~12 m).  ship_id + is_air=False
    duck-type it as a ContactBoard ship for the MaRV cone seeker."""

    is_air = False

    def __init__(self, pos, ship_id="tgt"):
        self.pos = np.array(pos, dtype=np.float64)
        self.ship_id = ship_id
        self.alive = True

    def velocity(self):
        return np.zeros(3)

    def kill(self):
        self.alive = False


class _MovingShip(_StaticShip):
    """Constant-velocity hull — exposes the stale-track geometry a static
    target hides."""

    def __init__(self, pos, vel, ship_id="tgt"):
        super().__init__(pos, ship_id)
        self.vel = np.array(vel, dtype=np.float64)

    def velocity(self):
        return self.vel

    def update(self, dt):
        self.pos = self.pos + self.vel * dt


def _fpa(vel):
    """Flight-path angle (deg): atan2(vy, horizontal speed). Negative = diving."""
    vh = math.hypot(float(vel[0]), float(vel[2]))
    return math.degrees(math.atan2(float(vel[1]), vh))


def _frozen_estimate(pos, vel):
    """A contact_estimate_fn closure FROZEN at launch (pos, vel) — the stale
    ContactBoard picture the round flies BOOST/MIDCOURSE on."""
    p = (float(pos[0]), float(pos[1]), float(pos[2]))
    v = (float(vel[0]), float(vel[1]), float(vel[2]))

    def est():
        return p, v
    return est


def _flyoff(target, contact_estimate_fn=None, rng=None, max_t=360.0):
    """Step the real flight model against ``target`` (static or moving) and
    report apogee, closest approach, terminal-handover FPA / altitude, the
    steepest terminal FPA, the midcourse min altitude and the outcome."""
    w = _World([target])
    m = AsbmMissile(BASTION_K, LAUNCH.copy(), target,
                    contact_estimate_fn=contact_estimate_fn, rng=rng)
    apogee = 0.0
    closest = float("inf")
    handover_fpa = handover_alt = None
    terminal_min_fpa = 0.0
    midcourse_min_alt = float("inf")
    while m.alive and m.t < max_t:
        if hasattr(target, "update"):
            target.update(DT)
        m.update(DT, w)
        alt = float(m.pos[1])
        apogee = max(apogee, alt)
        closest = min(closest, float(np.linalg.norm(m.pos - target.pos)))
        if m.phase == SPH_MIDCOURSE:
            midcourse_min_alt = min(midcourse_min_alt, alt)
        if m.phase >= SPH_TERMINAL:
            f = _fpa(m.vel)
            if handover_fpa is None:
                handover_fpa, handover_alt = f, alt
            terminal_min_fpa = min(terminal_min_fpa, f)
    return dict(apogee=apogee, closest=closest, t=m.t,
                killed=m.killed_target, self_destructed=m.self_destructed,
                handover_fpa=handover_fpa, handover_alt=handover_alt,
                terminal_min_fpa=terminal_min_fpa,
                midcourse_min_alt=(None if midcourse_min_alt == float("inf")
                                   else midcourse_min_alt))


# --- (1) lofts high and dives near-vertical -----------------------------------

def test_asbm_lofts_high_and_dives_near_vertical():
    """The DEPRESSED-profile top-attack signature (energy-model re-pin
    2026-07-05): ceiling cruise ABOVE the SM-2's engagement ceiling — the
    design discriminator, asserted against the SM2 def itself — then a late
    plunge steepening past -60 deg through terminal onto the deck.
    Measured at the probe range (200 km): apogee 26.0 km, handover -25 deg,
    terminal min -67 deg."""
    from sim.arsenal import SM2
    r = _flyoff(_StaticShip([0.0, 12.0, PROBE_RANGE]))
    assert r["apogee"] > SM2.max_intercept_alt, (
        f"cruise ceiling {r['apogee']:.0f} m must clear the SM-2's "
        f"{SM2.max_intercept_alt:.0f} m engagement ceiling")
    assert r["handover_fpa"] is not None, "never reached terminal handover"
    assert r["handover_fpa"] < -20.0, (
        f"handover dive too shallow: {r['handover_fpa']:.1f} deg")
    # The plunge steepens through terminal — a genuine top attack, and the
    # round comes down low (NOT a 40N6 4 km floor — it kills a deck at 12 m).
    # Re-pin 2026-07-06: with the 50-degree midcourse letdown clamp the
    # round hands over ALREADY diving at ~-44 and arrives at ~-45..-48
    # (measured); the old -60 pin described the free-energy vertical lob.
    assert r["terminal_min_fpa"] < -40.0, (
        f"terminal dive not steep: {r['terminal_min_fpa']:.1f} deg")
    # Two-sided apogee band: the drag-optimal ~26 km cruise, not a runaway
    # exo lob (which the energy model punishes into a 70 km shortfall).
    assert 24_000.0 <= r["apogee"] <= 35_000.0, (
        f"apogee out of measured band: {r['apogee']:.0f} m")


# --- (2) kills a stationary hull in envelope ----------------------------------

def test_asbm_kills_stationary_ship_in_envelope():
    """Fuse kill on a static hull at the probe range."""
    r = _flyoff(_StaticShip([0.0, 12.0, PROBE_RANGE]))
    assert r["killed"], f"ASBM missed the static hull (closest {r['closest']:.0f} m)"
    assert r["closest"] <= BASTION_K.fuse_radius


# --- (3) misses a fast mover launched on a STALE track ------------------------

def test_asbm_misses_fast_mover_on_stale_track():
    """Launched on a FROZEN contact estimate (the picture at launch) while the
    ship steams away: boost/midcourse fly the stale point, and even the
    terminal MaRV cannot recover the cross-range the hull opened up — closest
    approach exceeds the fuse radius.  The miss EMERGES from guiding on the
    stale picture, not a kill roll."""
    start = [0.0, 12.0, PROBE_RANGE]
    # A fast crossing destroyer (~18 m/s ~= 35 kn) — over the ~320 s time of
    # flight it walks ~5.8 km cross-range, far beyond the 20 m fuse.
    mover = _MovingShip(start, [18.0, 0.0, 0.0])
    frozen = _frozen_estimate(start, [0.0, 0.0, 0.0])   # picture frozen at rest
    r = _flyoff(mover, contact_estimate_fn=frozen)
    assert not r["killed"], (
        f"stale-track shot should MISS the mover (closest {r['closest']:.0f} m)")
    assert r["closest"] > BASTION_K.fuse_radius, (
        f"closest {r['closest']:.0f} m within fuse — stale picture did not miss")


# --- (4) SAME mover, FRESH track -> kill (proves it's the picture) ------------

def test_asbm_fresh_track_kills_same_mover():
    """The SAME fast mover, but the contact estimate REFRESHES to truth every
    step (a live track): boost/midcourse lead the real ship and the terminal
    MaRV closes the kill.  Proves the test (3) miss is the STALE picture, not
    the airframe being unable to hit a mover."""
    start = [0.0, 12.0, PROBE_RANGE]
    mover = _MovingShip(start, [18.0, 0.0, 0.0])

    def fresh_estimate():
        p = mover.pos
        v = mover.vel
        return ((float(p[0]), float(p[1]), float(p[2])),
                (float(v[0]), float(v[1]), float(v[2])))

    r = _flyoff(mover, contact_estimate_fn=fresh_estimate)
    assert r["killed"], (
        f"fresh-track shot should KILL the mover (closest {r['closest']:.0f} m)")


# --- (5) high midcourse is SM-6-targetable ------------------------------------

def test_asbm_high_midcourse_is_sm6_targetable():
    """The dead-reckoned midcourse cruise altitude stays ABOVE the existing
    SM-6 area-defense floor (SM6_AREA_MIN_ALT_M = 1500 m), so the high
    midcourse remains an SM-6 target — the existing counter still bites.
    Measured midcourse min altitude ~8 km."""
    from sim.enemy_defense import SM6_AREA_MIN_ALT_M
    r = _flyoff(_StaticShip([0.0, 12.0, PROBE_RANGE]))
    assert r["midcourse_min_alt"] is not None, "no midcourse phase observed"
    assert r["midcourse_min_alt"] > SM6_AREA_MIN_ALT_M, (
        f"midcourse dipped to {r['midcourse_min_alt']:.0f} m, below the "
        f"SM-6 floor {SM6_AREA_MIN_ALT_M:.0f} m (un-targetable)")


# --- (6) determinism: same seed -> identical trajectory -----------------------

def test_asbm_determinism():
    """Same seed -> bit-identical trajectory (reuses the SamMissile seeded
    multipath stream; no wall-clock)."""
    def run(seed):
        target = _StaticShip([0.0, 12.0, PROBE_RANGE])
        w = _World([target])
        m = AsbmMissile(BASTION_K, LAUNCH.copy(), target,
                        rng=np.random.default_rng(seed))
        pts = []
        while m.alive and m.t < 360.0:
            m.update(DT, w)
            pts.append(tuple(m.pos.tolist()))
        return pts
    a = run(20240617)
    b = run(20240617)
    assert a == b, "same seed produced different trajectories"


# --- terminal MaRV: re-acquires the nearest hull (anti-ship seeker) -----------

def test_asbm_marv_locks_nearest_ship_not_launch_target():
    """The MaRV terminal seeker locks the NEAREST alive ship in the seeker
    footprint, not necessarily the launch target — the ported _acquire_lock
    anti-ship seeker.  Two hulls close together: the round commits onto whichever
    is nearest the diving seeker and fuses it."""
    decoy = _StaticShip([0.0, 12.0, PROBE_RANGE], ship_id="decoy")
    real = _StaticShip([300.0, 12.0, PROBE_RANGE + 200.0], ship_id="real")
    w = _World([decoy, real])
    m = AsbmMissile(BASTION_K, LAUNCH.copy(), decoy)
    while m.alive and m.t < 360.0:
        m.update(DT, w)
    # One of the two hulls dies (the MaRV committed onto a footprint target).
    assert (not decoy.alive) or (not real.alive), (
        "MaRV failed to kill either hull")


# ===========================================================================
# World integration: launch_asbm + the asbm pool gate (CombatWorld)
# ===========================================================================

def test_world_default_battle_has_no_asbm():
    """DEFAULT config (asbm_ammo=0): the world's pool is 0 and launch('asbm')
    returns None — the round is never offered (byte-identical default battle)."""
    from world.combat import CombatWorld
    from world.combat_config import CombatConfig
    cw = CombatWorld(CombatConfig(seed=1337))
    assert cw._asbm_ammo == 0
    tp = np.array([0.0, 0.0, 0.0])
    assert cw.launch("hi-lo", tp, weapon_id="asbm") is None


def test_world_asbm_pool_arms_and_fires_at_ship_contact():
    """A configured asbm_ammo pool spawns an AsbmMissile aimed at the nearest
    SHIP contact, decrements the pool, and is a non-hostile player round.  The
    round flies on the dead-reckoned ContactBoard estimate (fog-honest)."""
    from world.combat import CombatWorld
    from world.combat_config import CombatConfig
    cw = CombatWorld(CombatConfig(seed=1337, asbm_ammo=3))
    assert cw._asbm_ammo == 3
    # Seed a held SHIP contact directly (the player picture; the enemy fleet
    # sits beyond the radar horizon so a real track needs the drone — not the
    # subject of this launch-path test).  Mirror a real ContactBoard ship track.
    ship = cw.ships[0]
    cw.contacts.tracks[ship.ship_id] = dict(
        pos=ship.pos.copy(), vel=np.zeros(3), age=0.0,
        t_next=cw.sim_time + 100.0, is_air=False, kind="ship", size=1.0)
    aim = np.array([float(ship.pos[0]), 0.0, float(ship.pos[2])])
    m = cw.launch("hi-lo", aim, weapon_id="asbm")
    assert m is not None, "configured ASBM pool failed to fire at a ship contact"
    assert isinstance(m, AsbmMissile)
    assert m.is_hostile is False, "player ASBM must not be a hostile round"
    assert m.target is ship, "ASBM should target the resolved ship contact"
    assert cw._asbm_ammo == 2, "ASBM pool did not decrement"
    assert m in cw.missiles


def test_world_asbm_blocked_when_no_ship_contact():
    """launch_asbm with no ship track returns None (the fog gate — the player
    may only target a ship the sensor picture holds)."""
    from world.combat import CombatWorld
    from world.combat_config import CombatConfig
    cw = CombatWorld(CombatConfig(seed=1337, asbm_ammo=2))
    assert cw.launch_asbm(None) is None
    assert cw.launch_asbm("no_such_ship") is None
    assert cw._asbm_ammo == 2, "a blocked launch must not consume a round"


# ===========================================================================
# B-cycle 4-way + HUD strip (gated on the ASBM pool)
# ===========================================================================

class _StubAudio:
    def ui_click(self):
        pass


class _StubApp:
    def __init__(self):
        self.audio = _StubAudio()


class _StubWorld:
    """Minimal world carrying just the scarce pools the cycle/strip read."""
    def __init__(self, asbm_ammo=0, kh31p_ammo=0,
                 oniks_ammo=8, oniks_cap=8, zircon_ammo=4):
        self._asbm_ammo = asbm_ammo
        self._kh31p_ammo = kh31p_ammo
        self._oniks_ammo = oniks_ammo
        self._oniks_mag_cap = oniks_cap
        self._zircon_ammo = zircon_ammo


class _CycleSandbox:
    """A bare Sandbox carrying only what cycle_oniks_weapon touches."""
    def __init__(self, **pools):
        from game.sandbox import SandboxState
        self.oniks_weapon = "oniks"
        self.app = _StubApp()
        self.world = _StubWorld(**pools)
        self.hint_text = ""
        self.hint_left = 0.0
        self._cycle = SandboxState.cycle_oniks_weapon

    def show_hint(self, text, seconds=2.5):
        self.hint_text = text
        self.hint_left = seconds

    def cycle_oniks_weapon(self):
        return self._cycle(self)


def test_b_cycle_stays_two_way_with_no_scarce_pools():
    """asbm_ammo == kh31p_ammo == 0 -> the EXACT oniks<->zircon 2-way UX
    (byte-identical default battle); ASBM never reachable."""
    sb = _CycleSandbox(asbm_ammo=0, kh31p_ammo=0)
    assert sb.cycle_oniks_weapon() == "zircon"
    assert sb.cycle_oniks_weapon() == "oniks"      # wraps, never hits asbm
    assert sb.cycle_oniks_weapon() == "zircon"


def test_b_cycle_includes_asbm_when_pool_configured():
    """asbm_ammo > 0 -> oniks->zircon->asbm->oniks (ARM absent)."""
    sb = _CycleSandbox(asbm_ammo=4, kh31p_ammo=0)
    assert sb.cycle_oniks_weapon() == "zircon"
    assert sb.cycle_oniks_weapon() == "asbm"
    assert sb.cycle_oniks_weapon() == "oniks"


def test_b_cycle_four_way_asbm_then_arm():
    """Both pools configured -> oniks->zircon->asbm->kh31p->oniks."""
    sb = _CycleSandbox(asbm_ammo=4, kh31p_ammo=4)
    assert sb.cycle_oniks_weapon() == "zircon"
    assert sb.cycle_oniks_weapon() == "asbm"
    assert sb.cycle_oniks_weapon() == "kh31p"
    assert sb.cycle_oniks_weapon() == "oniks"


def test_b_cycle_never_stuck_on_drained_asbm():
    """ON asbm with the pool drained mid-battle: the next B press advances back
    to oniks (no stuck state)."""
    sb = _CycleSandbox(asbm_ammo=2, kh31p_ammo=0)
    sb.oniks_weapon = "asbm"
    sb.world._asbm_ammo = 0
    assert sb.cycle_oniks_weapon() == "oniks"


def test_hud_strip_omits_asbm_by_default():
    """The Bastion strip is exactly ONIKS|ZIRCON when no scarce pool is
    configured (byte-identical default HUD)."""
    from game.hud import bastion_weapon_strip
    sb = _CycleSandbox(asbm_ammo=0, kh31p_ammo=0)
    labels = [row[0] for row in bastion_weapon_strip(sb, sb.world)]
    assert labels == ["ONIKS", "ZIRCON"]


def test_hud_strip_shows_asbm_row_when_configured():
    """A configured ASBM pool adds an ASBM row (pool count), ordered after
    ZIRCON and before KH-31P (mirrors the B cycle)."""
    from game.hud import bastion_weapon_strip
    sb = _CycleSandbox(asbm_ammo=4, kh31p_ammo=3)
    rows = bastion_weapon_strip(sb, sb.world)
    labels = [r[0] for r in rows]
    assert labels == ["ONIKS", "ZIRCON", "ASBM", "KH-31P"]
    asbm_row = next(r for r in rows if r[0] == "ASBM")
    assert asbm_row[2] == "4", "ASBM row should show the pool count"
