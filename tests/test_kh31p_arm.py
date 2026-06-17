"""tests/test_kh31p_arm.py — M2-T2 Kh-31P player anti-radiation missile.

The player SEAD round: a PlayerArmMissile (sim.arsenal.KH31P) that REUSES the
HarmMissile flight/homing machine but flies as a PLAYER round
(is_hostile=False).  Coverage:

  * Physics envelope (two-sided, LOCKED to the MEASURED flyoff in
    tools/probe_kh31p_flyoff.py): KILLS an emitting radar at the measured kill
    range, FALLS SHORT (fuel/range-limited) at the measured short range.
  * Passive homing on an EMITTING radar -> fuse kill; bit-identical across two
    same-seed runs (determinism / physics-not-dice).
  * Radar silence -> seeded CEP miss ring (HARM_MISS_MIN_M..HARM_MISS_MAX_M),
    emitter SURVIVES.
  * Silence then re-emit -> miss offset cleared, emitter killed (re-lock).
  * is_hostile == False: an ARM flown over the player base registers NO base
    hit through apply_missile_hits_structures.
  * launch_arm fog gate: None / un-localized emitter -> None; localized +
    ammo>0 -> a round + ammo decrement.
  * Victory credit: an ARM fusing on an enemy GROUND radar flips the radar
    dead AND advances the win condition (the Structure no longer counts as a
    live enemy radar for ``victorious``).
  * Default config: kh31p_ammo == 0 and launch_arm returns None out of the box
    (byte-identical guarantee).
  * Determinism: two same-seed worlds firing at the same silenced emitter draw
    the SAME miss offset.

MEASURED FLYOFF (tools/probe_kh31p_flyoff.py, seed [1337, 8], emitting radar):
    range  peakMach   ToF      closest    result
     60 km    2.63    118.0 s    11.6 m    HIT
     90 km    2.80    192.1 s    11.8 m    HIT   <- LOCKED KILL range (K)
    110 km    2.82    240.1 s    10.7 m    HIT
    130 km    2.84    284.9 s    11.4 m    HIT
    140 km    2.84    300.0 s  1022.4 m    MISS  <- LOCKED SHORT range (S)
    160 km    2.85    300.0 s  8227.0 m    MISS
  Silence-CEP (90 km shot, silent @40 s): closest 366.6 m, radar survives
  (inside the 150..400 m seeded ring).
  Cruise Mach >= 2.80 (meets the >= ~2.8 target).  The reused HarmMissile
  machine's altitude-hold gains are Mach-2-tuned, so a Mach-3 round zoom-glides
  and over-reaches the textbook 110 km (the in-game HARM does the same — its
  "110 km" is a data-sheet label, not a flyoff gate); the HONEST measured
  envelope is kill <= 130 km / short @ 140 km.  K=90, S=140.
"""

import math

import numpy as np
import pytest

from sim.arsenal import KH31P
from sim.bases import Structure, apply_missile_hits_structures
from sim.radar import Radar
from sim.strike import (HARM_MISS_MAX_M, HARM_MISS_MIN_M,
                        HarmMissile, PlayerArmMissile)
from world.combat import CombatWorld
from world.combat_config import CombatConfig
from world.generation import terrain_height_scalar

DT = 1.0 / 120.0   # 120 Hz fixed physics step

# MEASURED envelope ranges (see module docstring / probe output).
KILL_RANGE_M = 90_000.0     # K — kills an emitting radar
SHORT_RANGE_M = 140_000.0   # S — falls short (fuel/range-limited)


# ---------------------------------------------------------------------------
# Stub world (flat sea surface, matches tests/test_strike.py)
# ---------------------------------------------------------------------------

class _StubWorld:
    def surface_height_at(self, x: float, z: float) -> float:
        return 0.0


_WORLD = _StubWorld()


def _radar_at(x, z, height=10.0):
    """A live, emitting radar at (x, 0, z)."""
    return Radar("test_emitter",
                 np.array([x, 0.0, z], dtype=np.float64),
                 antenna_m=height,
                 ranges={"missile": 300_000.0, "fighter": 300_000.0})


def _arm(launch_pos, vel, radar, rng):
    return PlayerArmMissile(KH31P, launch_pos, vel, radar, rng)


def _launch_toward(radar, seed=1337, child_tag=8, start_pos=None):
    """Build a PlayerArmMissile from the home shelf aimed at ``radar`` with the
    standard seeded ARM stream [seed, child_tag] (the world reserves [seed,8]).
    Mirrors the probe's launch geometry."""
    if start_pos is None:
        start_pos = np.array([0.0, 5.0, 0.0], dtype=np.float64)
    ex = float(radar.pos[0]) - float(start_pos[0])
    ez = float(radar.pos[2]) - float(start_pos[2])
    hdg = math.atan2(ex, ez)
    vel = np.array([math.sin(hdg) * 60.0, 0.0, math.cos(hdg) * 60.0],
                   dtype=np.float64)
    rng = np.random.default_rng([seed, child_tag])
    return _arm(start_pos, vel, radar, rng)


def _fly(m, world, max_t=300.0, on_step=None):
    """Step ``m`` until dead or max_t. ``on_step(m)`` runs each step (e.g. to
    toggle radar.emitting). Returns the closest 3-D approach to its radar."""
    closest = float("inf")
    n = int(max_t / DT)
    for _ in range(n):
        if not m.alive:
            break
        if on_step is not None:
            on_step(m)
        m.update(DT, world)
        closest = min(closest, float(np.linalg.norm(m.pos - m.target_radar.pos)))
    return closest


# ---------------------------------------------------------------------------
# 1. Physics envelope (two-sided, locked to the measured probe ranges)
# ---------------------------------------------------------------------------

def test_kh31p_def_envelope():
    """KH31P.max_range matches the measured kill reach, and a flown shot KILLS
    an emitting radar at K=90 km but FALLS SHORT at S=140 km. Two-sided,
    locked to the probe numbers (see module docstring)."""
    # max_range reflects the MEASURED kill reach on this airframe (130 km).
    assert KH31P.max_range == 130_000.0

    # KILL at K=90 km.
    radar_k = _radar_at(0.0, KILL_RANGE_M)
    m_k = _launch_toward(radar_k)
    closest_k = _fly(m_k, _WORLD)
    assert not radar_k.alive, (
        f"ARM must KILL the emitting radar at {KILL_RANGE_M/1e3:.0f} km "
        f"(closest {closest_k:.1f} m)")
    assert closest_k < KH31P.fuse_radius + 1.0

    # FALL SHORT at S=140 km — fuel/range-limited, emitter survives.
    radar_s = _radar_at(0.0, SHORT_RANGE_M)
    m_s = _launch_toward(radar_s)
    closest_s = _fly(m_s, _WORLD)
    assert radar_s.alive, (
        f"ARM must FALL SHORT at {SHORT_RANGE_M/1e3:.0f} km "
        f"(closest {closest_s:.1f} m — should miss)")
    assert closest_s > KH31P.fuse_radius * 5.0, (
        f"short-range miss {closest_s:.1f} m is suspiciously close")


# ---------------------------------------------------------------------------
# 2. Passive homing on an emitting radar + determinism
# ---------------------------------------------------------------------------

def test_player_arm_homes_emitter():
    """A PlayerArmMissile vs an EMITTING radar fuses within fuse_radius
    (radar.alive -> False); bit-identical across two same-seed runs."""
    def run():
        radar = _radar_at(0.0, KILL_RANGE_M)
        m = _launch_toward(radar)
        _fly(m, _WORLD)
        return (not radar.alive, m.impact_pos.copy() if m.impact_pos is not None
                else None)

    killed_a, impact_a = run()
    killed_b, impact_b = run()
    assert killed_a and killed_b, "ARM must fuse the emitting radar dead"
    assert impact_a is not None and impact_b is not None
    # Bit-identical impact across same-seed runs (determinism contract).
    assert np.array_equal(impact_a, impact_b), (
        f"same-seed runs diverged: {impact_a} vs {impact_b}")


# ---------------------------------------------------------------------------
# 3. Radar silence -> seeded CEP miss ring, emitter survives
# ---------------------------------------------------------------------------

def test_player_arm_silence_cep():
    """Radar goes silent before terminal: the round impacts within the
    HARM_MISS_MIN_M..HARM_MISS_MAX_M ring of the last-known pos and the
    emitter SURVIVES (radar.alive True). Seeded, repeatable."""
    radar = _radar_at(0.0, KILL_RANGE_M)
    real_pos = radar.pos.copy()
    m = _launch_toward(radar)

    state = {"silenced": False}

    def silence_at_30km(mm):
        dx = float(mm.pos[0]) - float(real_pos[0])
        dz = float(mm.pos[2]) - float(real_pos[2])
        if not state["silenced"] and math.hypot(dx, dz) < 30_000.0:
            radar.emitting = False
            state["silenced"] = True

    _fly(m, _WORLD, on_step=silence_at_30km)

    assert state["silenced"], "test geometry: ARM never reached 30 km"
    assert not m.alive and m.impact_pos is not None
    assert radar.alive, "a silenced radar must SURVIVE the ARM (no truth homing)"

    miss = float(np.linalg.norm(m.impact_pos - real_pos))
    # The offset is drawn in [MIN, MAX]; the fuse then triggers at <=fuse_radius
    # of the DEGRADED aim point, so total miss ~ offset radius +/- fuse_radius.
    assert miss >= HARM_MISS_MIN_M - KH31P.fuse_radius - 1.0, (
        f"miss {miss:.1f} m below the {HARM_MISS_MIN_M} m CEP floor")
    assert miss <= HARM_MISS_MAX_M + KH31P.fuse_radius + 1.0, (
        f"miss {miss:.1f} m above the {HARM_MISS_MAX_M} m CEP ceiling")


# ---------------------------------------------------------------------------
# 4. Silence then re-emit -> miss offset cleared, emitter killed
# ---------------------------------------------------------------------------

def test_player_arm_relock():
    """Silence then re-emit before terminal: the miss offset is cleared and
    the emitter is killed (the round re-locks the live position)."""
    radar = _radar_at(0.0, KILL_RANGE_M)
    real_pos = radar.pos.copy()
    m = _launch_toward(radar)

    state = {"silenced_step": None, "reemitted": False, "step": 0}

    def toggle(mm):
        s = state
        dx = float(mm.pos[0]) - float(real_pos[0])
        dz = float(mm.pos[2]) - float(real_pos[2])
        dist = math.hypot(dx, dz)
        if s["silenced_step"] is None and dist < 50_000.0:
            radar.emitting = False
            s["silenced_step"] = s["step"]
        elif (s["silenced_step"] is not None and not s["reemitted"]
              and s["step"] > s["silenced_step"] + int(2.0 / DT)):
            radar.emitting = True
            s["reemitted"] = True
        s["step"] += 1

    _fly(m, _WORLD, on_step=toggle)

    assert state["silenced_step"] is not None, "test geometry: never silenced"
    assert state["reemitted"], "test logic: never re-emitted"
    assert not m.alive and m.impact_pos is not None
    assert m._miss_offset is None, "re-emission must clear the miss offset"
    assert not radar.alive, "re-locked ARM must kill the re-emitting radar"
    miss = float(np.linalg.norm(m.impact_pos - real_pos))
    assert miss <= KH31P.fuse_radius * 3 + 20.0, (
        f"re-locked ARM should hit near the radar; miss = {miss:.1f} m")


# ---------------------------------------------------------------------------
# 5. is_hostile == False: no base hit over the player base
# ---------------------------------------------------------------------------

def test_arm_not_hostile():
    """A PlayerArmMissile is is_hostile == False; flown across a player base
    Structure it registers NO base hit through apply_missile_hits_structures
    (the hostile-rounds sweep that demolishes the player base must skip it)."""
    assert PlayerArmMissile.is_hostile is False
    assert HarmMissile.is_hostile is True   # enemy HARM stays hostile

    # A player base structure (TEL) at the origin.
    base_struct = Structure("player_tel", "bastion_tel",
                            np.array([0.0, 0.0, 0.0], dtype=np.float64))
    radar = _radar_at(0.0, KILL_RANGE_M)
    m = _launch_toward(radar)

    events = []
    # Drive the ARM right over the base structure for the first second, running
    # the HOSTILE-rounds sweep each step exactly as world/combat.py does.
    for _ in range(int(2.0 / DT)):
        if not m.alive:
            break
        m.update(DT, _WORLD)
        # The world's hostile-vs-base sweep filters on is_hostile; the ARM
        # (False) is excluded, so even directly over the OBB it cannot hit.
        hostile = [mm for mm in [m] if getattr(mm, "is_hostile", False)]
        apply_missile_hits_structures(hostile, [base_struct], events)

    assert base_struct.alive, "player base must survive its own ARM overflight"
    assert events == [], f"ARM wrongly registered base hits: {events}"


# ---------------------------------------------------------------------------
# 6. launch_arm fog gate
# ---------------------------------------------------------------------------

def _localize(cw, radar, kind="GND RADAR"):
    """Inject ``radar`` into the player's localized SIGINT picture (the M2-T1
    emitter channel the drone's ELINT would populate)."""
    cw.emitter_contacts[radar.radar_id] = dict(
        pos=radar.pos.copy(), kind=kind, quality=100.0,
        last_heard=cw.sim_time, age=10.0)


def test_launch_arm_requires_localized_emitter():
    """launch_arm(None) -> None; an emitter NOT in emitter_contacts -> None
    (fog gate); with the emitter localized + ammo>0 -> a round + ammo
    decrement."""
    cw = CombatWorld(CombatConfig(seed=1337, kh31p_ammo=2, n_enemy_radars=1))
    struct, radar = cw.enemy_radars[0]

    assert cw.launch_arm(None) is None, "None emitter must be rejected"

    eid = radar.radar_id
    # Not localized yet -> fog gate rejects.
    assert eid not in cw.emitter_contacts
    assert cw.launch_arm(eid) is None, "un-localized emitter must be rejected"
    assert cw._kh31p_ammo == 2, "rejected launch must not spend ammo"

    # Localize -> now targetable.
    _localize(cw, radar)
    m = cw.launch_arm(eid)
    assert isinstance(m, PlayerArmMissile), "localized emitter must launch a round"
    assert cw._kh31p_ammo == 1, "a successful launch decrements the pool"
    assert m in cw.missiles
    assert m.is_hostile is False
    assert m.target_radar is radar, "the ARM must home on the LIVE radar"


def test_launch_arm_empty_pool_returns_none():
    """A configured-but-empty pool (ammo exhausted) returns None."""
    cw = CombatWorld(CombatConfig(seed=1337, kh31p_ammo=1, n_enemy_radars=1))
    _struct, radar = cw.enemy_radars[0]
    _localize(cw, radar)
    assert cw.launch_arm(radar.radar_id) is not None
    assert cw._kh31p_ammo == 0
    # Pool now empty -> next launch blocked.
    _localize(cw, radar)
    assert cw.launch_arm(radar.radar_id) is None


# ---------------------------------------------------------------------------
# 7. Victory credit: ARM ground-radar kill advances the win condition
# ---------------------------------------------------------------------------

def test_arm_kills_ground_radar_for_victory_credit():
    """A PlayerArmMissile fusing on an enemy ground radar flips the radar dead
    AND advances the win condition: the radar's Structure no longer counts as a
    live enemy radar for ``victorious``.

    The enemy ground radars spawn ~500 km inland (an Oniks target); the ARM's
    measured reach is ~130 km, so this test RELOCATES one ground radar within
    the ARM envelope to exercise the victory-credit MECHANISM (spec risk #2).
    """
    cw = CombatWorld(CombatConfig(seed=1337, kh31p_ammo=2, n_enemy_radars=1))
    struct, radar = cw.enemy_radars[0]

    # Relocate radar + Structure to ~110 km down-range of the launcher.
    lp = cw._oniks_tubes[0]["pos"]
    nx = float(lp[0])
    nz = float(lp[2]) + 110_000.0
    ny = max(terrain_height_scalar(nx, nz), 0.0)
    radar.pos = np.array([nx, ny + 18.0, nz], dtype=np.float64)
    struct.pos = np.array([nx, ny, nz], dtype=np.float64)

    _localize(cw, radar)
    assert struct.alive and radar.alive

    m = cw.launch_arm(radar.radar_id)
    assert m is not None

    for _ in range(int(300.0 / DT)):
        cw.step(DT)
        if not struct.alive:
            break

    assert not radar.alive, "ARM fuse must flip the Radar dead"
    assert not struct.alive, (
        "ARM ground-radar kill must ALSO flip the Structure dead "
        "(victory-credit path)")
    # No live enemy radar Structure remains -> the win condition's radar gate
    # is satisfied (the ground radar no longer counts as live).
    live = [s for s, _r in cw.enemy_radars if s.alive]
    assert live == [], "killed ground radar must not count as live for victory"


# ---------------------------------------------------------------------------
# 8. Default config: no ARM out of the box (byte-identical guarantee)
# ---------------------------------------------------------------------------

def test_default_config_no_arm_byte_identical():
    """CombatConfig() has kh31p_ammo == 0; launch_arm on a default world
    returns None (no ARM available out of the box)."""
    assert CombatConfig().kh31p_ammo == 0
    cw = CombatWorld(CombatConfig(seed=1337))   # default ammo == 0
    assert cw._kh31p_ammo == 0
    # Even with a localized emitter, an empty pool refuses to fire.
    if cw.enemy_radars:
        _struct, radar = cw.enemy_radars[0]
        _localize(cw, radar)
        assert cw.launch_arm(radar.radar_id) is None
    assert cw.launch_arm(None) is None


# ---------------------------------------------------------------------------
# 9. Determinism: same seed -> same silenced-emitter miss offset
# ---------------------------------------------------------------------------

def test_arm_determinism():
    """Two same-seed worlds firing the same ARM at the same SILENCED emitter
    draw the SAME miss offset (the [seed, 8] child stream is deterministic)."""
    def run():
        cw = CombatWorld(CombatConfig(seed=2024, kh31p_ammo=1, n_enemy_radars=1))
        _struct, radar = cw.enemy_radars[0]
        # Relocate within envelope and localize.
        lp = cw._oniks_tubes[0]["pos"]
        nx, nz = float(lp[0]), float(lp[2]) + 90_000.0
        ny = max(terrain_height_scalar(nx, nz), 0.0)
        radar.pos = np.array([nx, ny + 18.0, nz], dtype=np.float64)
        _struct.pos = np.array([nx, ny, nz], dtype=np.float64)
        _localize(cw, radar)
        m = cw.launch_arm(radar.radar_id)
        # Silence the emitter immediately so the miss offset is drawn.
        radar.emitting = False
        for _ in range(int(300.0 / DT)):
            cw.step(DT)
            if not m.alive:
                break
        return m._miss_offset

    off_a = run()
    off_b = run()
    assert off_a is not None and off_b is not None, (
        "a silenced emitter must produce a drawn miss offset")
    assert np.array_equal(off_a, off_b), (
        f"same-seed ARM miss offsets diverged: {off_a} vs {off_b}")
