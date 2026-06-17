"""M3-F4 player drone EW pod (self-protect / escort jammer).

The player's mirror of the Growler: a podded barrage jammer on the recon drone
that, when toggled ON, COLLAPSES the ENEMY radar net via the EW field model
(sim/ew.py, M3-F1) so a sea-skim salvo LEAKS under a degraded SPY-1/AWACS
picture — at the cost of going loud (the hot pod deafens the drone's OWN passive
ELINT).  It REUSES the same burn-through field the enemy Growler uses, now
applied against ENEMY radars.

CONTRACTS exercised here:
  * REGRESSION GATE — pod OFF (player_jammer=0 OR jam_active=False) makes the
    enemy's detection of a player missile byte-identical to today
    (_active_player_jammers() empty -> the enemy detects() calls get jammers=()).
  * THE gameplay link — with the pod ON, a player missile an enemy SPY-1 tracks
    pod-OFF is NO LONGER tracked (its enemy missile-track stops forming /
    refreshing) — the salvo leaks.
  * self-deafen cost — a hot pod makes the drone's OWN ELINT fix on a real enemy
    emitter SOFTER (larger fix_quality) than pod-off.
  * the JAM control toggles drone.jam_active ONLY on the drone platform.
  * determinism — two same-seed worlds with the pod ON behave bit-identically.
  * DEFAULT player_jammer == 0 and a default same-seed battle is bit-identical
    (no pod armed).

PHYSICS NOT DICE: the enemy seeing less is the deterministic effective_range
collapse; the self-deafen is the ELINT-sigma physics.  NO new RNG.  NO-CHEAT:
the enemy only ever reacts to its OWN degraded detects(), never a truth read.
"""

from __future__ import annotations

import numpy as np

from world.combat import CombatWorld
from world.combat_config import CombatConfig
from sim import ew


DT = 1.0 / 30.0


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _enemy_detector(world):
    """A live enemy missile-detecting radar (destroyer SPY-1) from the same
    set the enemy picture feeds off (_enemy_sensor_radars)."""
    return next(r for r in world._enemy_sensor_radars())


def _place_pod_near(world, detector, standoff_m=30_000.0):
    """Park the armed drone ``standoff_m`` from ``detector`` (clear LOS at
    cruise alt) so its hot pod strongly collapses that radar's ring."""
    dp = detector.pos
    world.drone.pos[:] = np.array(
        [float(dp[0]) + standoff_m, 18_000.0, float(dp[2])], dtype=np.float64)
    world.drone._sync_pod()


# ---------------------------------------------------------------------------
# 1. REGRESSION: pod OFF -> enemy detection byte-identical (jammers=()).
# ---------------------------------------------------------------------------

def test_pod_off_enemy_detection_byte_identical():
    """With the pod OFF (player_jammer=0, OR armed-but-cold), the active player
    jammer list is empty, so the enemy's detection of a player missile is
    IDENTICAL to passing no jammers at all (the byte-identical legacy path)."""
    # (a) player_jammer=0: no pod armed at all.
    w0 = CombatWorld(CombatConfig(seed=11, player_jammer=0))
    assert w0._active_player_jammers() == [], "player_jammer=0 arms no pod"
    det0 = _enemy_detector(w0)
    dp = det0.pos
    for rng in (40_000.0, 150_000.0, 270_000.0):
        m = np.array([float(dp[0]), 11_000.0, float(dp[2]) + rng],
                     dtype=np.float64)
        assert (det0.detects(m, "missile",
                             jammers=w0._active_player_jammers())
                == det0.detects(m, "missile", jammers=())), \
            "pod-off detection must equal the no-jammer detection"

    # (b) armed pod but jam_active False -> still empty list, still identical.
    w1 = CombatWorld(CombatConfig(seed=11, player_jammer=1))
    assert w1.drone.jam_active is False, "a freshly armed pod starts COLD"
    assert w1._active_player_jammers() == [], "a cold pod is not an active jammer"
    det1 = _enemy_detector(w1)
    dp = det1.pos
    for rng in (40_000.0, 150_000.0, 270_000.0):
        m = np.array([float(dp[0]), 11_000.0, float(dp[2]) + rng],
                     dtype=np.float64)
        assert (det1.detects(m, "missile",
                             jammers=w1._active_player_jammers())
                == det1.detects(m, "missile", jammers=()))


# ---------------------------------------------------------------------------
# 2. THE gameplay link: pod ON -> the salvo leaks (track stops forming).
# ---------------------------------------------------------------------------

def test_pod_on_salvo_leaks():
    """A player missile an enemy SPY-1 tracks at long range WITH the pod OFF is
    NO LONGER tracked WITH the pod ON (the EW field collapses the enemy
    missile-range ring), and a CLOSE-in missile both worlds see is STILL seen
    (the EW close-in floor — jamming never denies a knife-range detection)."""
    w = CombatWorld(CombatConfig(seed=11, player_jammer=1))
    det = _enemy_detector(w)
    _place_pod_near(w, det, standoff_m=30_000.0)
    dp = det.pos

    # The pod ON collapses the missile ring from the nominal 300 km to << that.
    w.drone.set_jam(True)
    pjam = w._active_player_jammers()
    assert pjam, "a hot, armed, airborne pod is an active player jammer"
    eff_on = ew.effective_range(det, "missile", dp, pjam)
    eff_off = det.ranges.get("missile", 0.0)
    assert eff_on < eff_off, \
        "the hot pod must collapse the enemy missile-range ring"

    # A high-altitude player missile BEYOND the collapsed ring (but inside the
    # nominal ring + above the horizon): tracked pod-OFF, leaks pod-ON.
    leak_rng = (eff_on + eff_off) / 2.0
    m_leak = np.array([float(dp[0]), 11_000.0, float(dp[2]) + leak_rng],
                      dtype=np.float64)
    assert det.detects(m_leak, "missile", jammers=()), \
        "pod-off the SPY-1 tracks the long-range player missile"
    assert not det.detects(m_leak, "missile", jammers=pjam), \
        "pod-on the salvo LEAKS: the SPY-1 no longer tracks it"

    # A close-in missile is still tracked under the jam (close-in floor).
    close_rng = min(ew.EW_CLOSE_FLOOR_M * 0.5, eff_on * 0.5)
    m_close = np.array([float(dp[0]), 6_000.0, float(dp[2]) + close_rng],
                       dtype=np.float64)
    assert det.detects(m_close, "missile", jammers=()), "close target seen off"
    assert det.detects(m_close, "missile", jammers=pjam), \
        "the pod must not deny a close-in detection (EW close floor)"


def test_pod_on_track_stops_forming_through_world():
    """End-to-end through the world's enemy picture feed: a real player missile
    placed where the SPY-1 would form a track pod-OFF forms NO enemy
    missile-track once the pod goes hot (the leak bites at the actual detection
    site in _feed_enemy_picture)."""
    def run(pod_on: bool):
        w = CombatWorld(CombatConfig(seed=11, player_jammer=1))
        det = _enemy_detector(w)
        # Silence the OTHER detectors so the test isolates this SPY-1's ring
        # (a second radar nearer the missile must not mask the collapse).
        for r in w._enemy_sensor_radars():
            if r is not det:
                r.emitting = False
        _place_pod_near(w, det, standoff_m=30_000.0)
        pjam_on = [w.drone.pod_emitter]
        eff_on = ew.effective_range(det, "missile", det.pos, pjam_on)
        eff_off = det.ranges.get("missile", 0.0)
        leak_rng = (eff_on + eff_off) / 2.0
        dp = det.pos
        # A live player Oniks (via the world's own launcher) repositioned to the
        # leak range, high enough to clear the horizon.
        m = w.launch("hi-lo", (float(dp[0]), 0.0, float(dp[2]) + leak_rng))
        assert m is not None, "the Bastion tube must fire a round"
        m.pos[:] = np.array([float(dp[0]), 11_000.0, float(dp[2]) + leak_rng],
                            dtype=np.float64)
        if pod_on:
            w.drone.set_jam(True)
        # Feed the enemy picture once and read the commander's missile tracks.
        w._feed_enemy_picture(0.25, w.sim_time)
        return len(w.commander.picture.missile_tracks)

    assert run(pod_on=False) >= 1, \
        "pod-off the SPY-1 must form an enemy missile-track for the player round"
    assert run(pod_on=True) == 0, \
        "pod-on the round leaks: NO enemy missile-track forms"


# ---------------------------------------------------------------------------
# 3. Self-deafen: a hot pod softens the drone's OWN ELINT fix.
# ---------------------------------------------------------------------------

def test_pod_on_deafens_own_elint():
    """With the pod hot the drone's OWN ELINT fix quality on a REAL enemy
    emitter is SOFTER (larger fix_quality m) than pod-off — going loud raises
    the drone's own passive noise floor (sim/ew.noise_floor_at -> wider bearing
    sigma).  Run the SAME seeded cross-track listen pass both ways.

    Also asserts the cost is a COST, NOT A WALL: a determined cross-track pass
    STILL reaches an actionable fix under the hot pod (the spec's explicit risk
    — "too high and the player can never localize anything while jammed" — must
    not bite).  The self-deafen FLOOR is calibrated below the gate knee for
    exactly this."""
    def run(pod_on: bool):
        w = CombatWorld(CombatConfig(seed=11, player_jammer=1))
        # A real enemy ground radar to localize (always-on coastal emitter).
        emitter = w._enemy_ground_radars[0]
        ep = emitter.pos
        eid = emitter.radar_id
        if pod_on:
            w.drone.set_jam(True)
        # Fly a determined cross-track baseline ~60 km abeam the emitter so the
        # triangulation geometry is valid, listening on the ELINT cadence.
        x0 = float(ep[0]) - 25_600.0          # centre the 64-pair window abeam
        z_abeam = float(ep[2]) - 60_000.0
        sd = w._player_self_deafen_jammers()
        for i in range(64):
            w.drone.pos[:] = np.array(
                [x0 + i * 800.0, 18_000.0, z_abeam], dtype=np.float64)
            w.drone._sync_pod()
            w.elint.update(w.drone.pos, w._emitters(),
                           sim_time=float(i),
                           jammers=(w._active_enemy_jammers() + sd))
        return w.elint.fix_quality(eid)

    q_off = run(pod_on=False)
    q_on = run(pod_on=True)
    assert np.isfinite(q_off), "pod-off the cross-track pass yields a fix"
    assert q_on > q_off, \
        "a hot pod must make the drone's OWN ELINT fix SOFTER (larger quality)"
    # Cost, not a wall: a determined pass STILL localizes under the hot pod.
    from sim.recon import ELINT_FIX_ACTIONABLE_M
    assert q_on < ELINT_FIX_ACTIONABLE_M, \
        "the self-deafen must be a COST, not a WALL — a determined pass still fixes"


# ---------------------------------------------------------------------------
# 4. The JAM control toggles only on the drone platform.
# ---------------------------------------------------------------------------

def test_pod_toggle_through_controls():
    """sandbox.toggle_jam() flips drone.jam_active ONLY when the drone platform
    is active (and the pod is fitted); it is a no-op on other platforms."""
    from game.sandbox import SandboxState

    class _Audio:
        def ui_click(self):
            pass

    class _App:
        audio = _Audio()

    # A minimal sandbox shim: real CombatWorld, stubbed app/hint surface.
    sb = SandboxState.__new__(SandboxState)
    sb.world = CombatWorld(CombatConfig(seed=11, player_jammer=1))
    sb.app = _App()
    sb.active_platform = "bastion"
    sb.hint_text = ""
    sb.hint_left = 0.0

    drone = sb.world.drone
    assert drone.jam_active is False

    # Wrong platform: no toggle.
    sb.toggle_jam()
    assert drone.jam_active is False, "JAM is a no-op off the drone platform"

    # Drone platform: toggles ON then OFF.
    sb.active_platform = "drone"
    sb.toggle_jam()
    assert drone.jam_active is True, "JAM on the drone platform arms the pod"
    sb.toggle_jam()
    assert drone.jam_active is False, "JAM toggles back off"


def test_jam_keybind_registered_and_unique():
    """The JAM action is registered with a non-reserved, conflict-free key."""
    from game.keybinds import Keybinds
    import os
    import tempfile

    # Use a throwaway path so we never touch the real settings file.
    path = os.path.join(tempfile.gettempdir(), "oniks_test_jam_binds.json")
    if os.path.exists(path):
        os.remove(path)
    kb = Keybinds(path=path)
    assert "jam" in kb.keys, "the jam action must be registered"
    key = kb.key_for("jam")
    assert key is not None, "the jam action must have a default key"
    # No other action shares the JAM key (injective table).
    owners = [aid for aid, k in kb.keys.items() if k == key]
    assert owners == ["jam"], f"the JAM key must be unique, got {owners}"
    if os.path.exists(path):
        os.remove(path)


# ---------------------------------------------------------------------------
# 5. Determinism: same seed + pod ON -> bit-identical.
# ---------------------------------------------------------------------------

def _world_fingerprint(w):
    """A compact bit-exact snapshot of the moving state after stepping."""
    drone = w.drone
    return (
        tuple(round(float(x), 9) for x in (
            (drone.pos[0], drone.pos[1], drone.pos[2]) if drone else (0, 0, 0))),
        round(float(w.sim_time), 9),
        len(w.missiles),
        tuple(sorted(w.commander.picture.missile_tracks.keys())),
        tuple(round(w.elint.fix_quality(e), 6)
              for e in sorted(w.elint.heard_emitters())),
    )


def test_determinism_pod():
    """Two same-seed worlds with the pod ON step bit-identically."""
    def run():
        w = CombatWorld(CombatConfig(seed=909, player_jammer=1))
        w.drone.set_jam(True)
        for _ in range(int(15.0 / DT)):
            w.step(DT)
        return _world_fingerprint(w)

    assert run() == run(), "same-seed pod-ON battle diverged"


# ---------------------------------------------------------------------------
# 6. DEFAULT player_jammer == 0 + default battle byte-identical.
# ---------------------------------------------------------------------------

def _default_fingerprint(w):
    ships = tuple(sorted(
        (s.ship_id, bool(s.radar.emitting),
         round(float(s.pos[0]), 6), round(float(s.pos[2]), 6))
        for s in w.ships if getattr(s, "radar", None) is not None))
    drone = w.drone
    dpos = ((round(float(drone.pos[0]), 6), round(float(drone.pos[2]), 6))
            if drone else None)
    tracks = tuple(sorted(w.commander.picture.missile_tracks.keys()))
    return ships, dpos, tracks, round(float(w.sim_time), 6)


def test_default_player_jammer_zero_byte_identical():
    """CombatConfig().player_jammer == 0; a default same-seed battle is
    bit-identical (no pod armed; the enemy detection / own-ELINT paths get
    jammers=() exactly as before this feature)."""
    assert CombatConfig().player_jammer == 0, "the pod is OFF by default"

    w = CombatWorld(CombatConfig(seed=42))
    assert w._player_jammer is False, "default config arms no pod"
    assert w._active_player_jammers() == [], "no active player jammer by default"
    # Even if jam_active were somehow flipped, the unarmed gate keeps it empty.
    w.drone.jam_active = True
    assert w._active_player_jammers() == [], \
        "an UNARMED pod can never become an active jammer (config gate)"

    def runb():
        wb = CombatWorld(CombatConfig(seed=42))
        for _ in range(int(20.0 / DT)):
            wb.step(DT)
        return _default_fingerprint(wb)

    assert runb() == runb(), "default battle diverged"
