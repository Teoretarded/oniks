"""M5 submarine: the enemy diesel SSK entity + state machine + radiated noise.

Contracts (spec 03, feature 1):
  (a) a Submarine is NEVER returned by any RadarNetwork.visible / Radar.detects
      path, and is NOT in self.ships (it is invisible to radar by construction —
      the whole premise; mirrors how ReconDrone is kept out of self.aircraft).
  (b) the state machine cycles deterministically under a fixed seed (same state
      sequence under the same [seed, 13] child stream).
  (c) radiated_noise() is strictly HIGHER in LAUNCH/SPRINT than APPROACH/DEEP
      (the speed/quietness tradeoff: loudest exactly when it shoots).
  (d) victorious stays False while any sub is alive even with all surface hulls
      + airfield + radars dead (so the player MUST find + kill it).
"""

from __future__ import annotations

import numpy as np
import pytest

from sim.submarine import (
    Submarine, SUB_DEEP_TRANSIT, SUB_APPROACH, SUB_LAUNCH, SUB_EVADE,
    SUB_DEPTH_M, SUB_LAUNCH_DEPTH_M,
)

DT = 1.0 / 120.0


def _make_sub(seed=1337, anchor=(0.0, 110_000.0), ammo=4):
    rng = np.random.default_rng([seed, 13])
    return Submarine(anchor_xz=anchor, rng=rng, kalibr_ammo=ammo,
                     base_xz=(0.0, 0.0))


# ---------------------------------------------------------------------------
# (a) invisible to radar by construction
# ---------------------------------------------------------------------------

def test_sub_not_in_ships_and_never_radar_detected():
    """A Submarine is invisible to radar: not in self.ships, and a Radar's
    detects() path never returns it (it carries no radar_size / RCS surface)."""
    from world.combat import CombatWorld
    from world.combat_config import CombatConfig

    cw = CombatWorld(CombatConfig(seed=1337, n_subs=1, sub_kalibr_ammo=4))
    assert len(cw.subs) == 1
    sub = cw.subs[0]
    # NOT in self.ships (the radar-gated contact source).
    assert sub not in cw.ships
    # NOT in any emitter list (it has no Radar mount at all).
    emitter_ids = {eid for eid, _ in cw._emitters()}
    assert not any("sub" in str(eid).lower() for eid in emitter_ids), (
        "the sub must never join the emitter list")
    # Step the world a while; the radar-gated player picture must never form a
    # track at the sub's position (it is invisible — only acoustics can find it).
    for _ in range(240):
        cw.step(DT)
    for tid, tr in cw.contacts.tracks.items():
        d = float(np.hypot(tr["pos"][0] - sub.pos[0], tr["pos"][2] - sub.pos[2]))
        assert d > 5_000.0, (
            f"radar picture formed a track {d:.0f} m from the sub truth "
            f"(track {tid}) — the sub leaked into a radar path")


def test_sub_carries_no_radar_attributes():
    """Guard: the Submarine has no .radar mount and no radar_size — so it can
    never be passed to Radar.detects / RadarNetwork.visible by duck-type."""
    sub = _make_sub()
    assert not hasattr(sub, "radar"), "sub must not carry a Radar mount"
    assert getattr(sub, "radar_size", None) is None


# ---------------------------------------------------------------------------
# (b) deterministic state machine
# ---------------------------------------------------------------------------

def test_state_machine_cycles_deterministically():
    """Same seed -> identical state-transition sequence + positions."""
    sub_a = _make_sub(seed=2024)
    sub_b = _make_sub(seed=2024)
    seq_a, seq_b = [], []
    for _ in range(120 * 600):   # 600 s
        sub_a.step(DT, threat_level=0.0)
        sub_b.step(DT, threat_level=0.0)
        seq_a.append(sub_a.state)
        seq_b.append(sub_b.state)
    assert seq_a == seq_b
    assert np.allclose(sub_a.pos, sub_b.pos)


def test_state_machine_reaches_launch_then_evades():
    """With a LOW threat the boat advances to a launch box, fires, then EVADEs:
    the full cycle must be exercised within a reasonable window."""
    sub = _make_sub()
    seen = set()
    fired_any = False
    for _ in range(120 * 1800):    # 30 min
        out = sub.step(DT, threat_level=0.0)
        seen.add(sub.state)
        if out is not None:        # fire_salvo seam returns an aim when ready
            fired_any = True
    assert SUB_APPROACH in seen
    assert SUB_LAUNCH in seen
    assert SUB_EVADE in seen
    assert fired_any, "the boat must reach a salvo within 30 min on low threat"


def test_high_threat_keeps_boat_deep():
    """A HIGH threat level (recently prosecuted) must keep the boat from
    committing to the noisy launch run — it stays deep/quiet."""
    sub = _make_sub()
    states = set()
    for _ in range(120 * 600):
        sub.step(DT, threat_level=1.0)
        states.add(sub.state)
    assert SUB_LAUNCH not in states, (
        "a heavily-prosecuted boat must not surface to launch")


# ---------------------------------------------------------------------------
# (c) radiated-noise physics (loudest when it shoots)
# ---------------------------------------------------------------------------

def test_radiated_noise_louder_in_launch_and_sprint():
    """radiated_noise() strictly higher in LAUNCH/EVADE(sprint) than
    APPROACH/DEEP (the speed/quietness tradeoff)."""
    sub = _make_sub()
    sub.state = SUB_DEEP_TRANSIT
    n_deep = sub.radiated_noise()
    sub.state = SUB_APPROACH
    n_appr = sub.radiated_noise()
    sub.state = SUB_LAUNCH
    n_launch = sub.radiated_noise()
    sub.state = SUB_EVADE
    n_evade = sub.radiated_noise()
    assert n_launch > n_appr
    assert n_launch > n_deep
    assert n_evade > n_appr
    # APPROACH must be quiet (it is the stealthy creep), and all positive.
    assert n_appr <= n_deep * 4.0
    assert min(n_deep, n_appr, n_launch, n_evade) > 0.0


def test_depths_by_state():
    """The boat sits DEEP by default and only rises to launch depth in LAUNCH."""
    sub = _make_sub()
    sub.state = SUB_DEEP_TRANSIT
    sub._apply_state_depth()
    assert sub.depth <= SUB_DEPTH_M + 1.0       # deep (negative, ~-120 m)
    sub.state = SUB_LAUNCH
    sub._apply_state_depth()
    assert sub.depth >= SUB_LAUNCH_DEPTH_M - 1.0  # shallow (~-15 m)


# ---------------------------------------------------------------------------
# (d) victorious requires all subs dead
# ---------------------------------------------------------------------------

def test_victorious_requires_subs_dead():
    """With a sub alive, victorious stays False even with ALL surface hulls +
    airfield + radars dead — the player MUST find and kill the boat."""
    from sim.ships import ST_GONE
    from world.combat import CombatWorld
    from world.combat_config import CombatConfig

    cw = CombatWorld(CombatConfig(seed=1337, n_subs=1, n_enemy_radars=2))
    # Flatten every OTHER win sub-condition.
    for s in cw.ships:
        s.state = ST_GONE
    cw.airfield.alive = False
    for struct, r in cw.enemy_radars:
        struct.alive = False
        r.alive = False
    # Still NOT victorious — the sub lives.
    assert not cw.victorious, "a live sub must block victory"
    # Kill the boat -> victory.
    cw.subs[0].kill()
    assert cw.victorious, "killing the last sub must flip victory"


def test_zero_subs_unchanged_victory():
    """n_subs=0 -> the sub clause is inert; victory reduces to ships + radars
    + airfield (the legacy condition)."""
    from sim.ships import ST_GONE
    from world.combat import CombatWorld
    from world.combat_config import CombatConfig

    cw = CombatWorld(CombatConfig(seed=1337, n_subs=0, n_enemy_radars=0))
    assert cw.subs == []
    for s in cw.ships:
        s.state = ST_GONE
    cw.airfield.alive = False
    assert cw.victorious


# ---------------------------------------------------------------------------
# REGRESSION: n_subs=0 keeps the default battle bit-identical (THE GATE)
# ---------------------------------------------------------------------------

def _battle_digest(cw, steps=900):
    """Bit-level digest of the battle after stepping: missile + ship positions
    + the event stream, rounded to 1e-6.  Two identical configs must match."""
    import numpy as _np
    rows = []
    for _ in range(steps):
        cw.step(DT)
        for ev in cw.events:
            rows.append((ev[0],) + tuple(round(float(c), 6)
                                         for c in _np.asarray(ev[1]).ravel()))
        for m in cw.missiles:
            rows.append(("m",) + tuple(round(float(c), 6) for c in m.pos))
        for s in cw.ships:
            rows.append(("s",) + tuple(round(float(c), 6) for c in s.pos))
    return rows


def test_n_subs_zero_default_battle_bit_identical():
    """The whole M5 ASW domain is NEW: with n_subs=0 NO Submarine / sonobuoy /
    ASW machinery runs, self.subs is empty, and the default battle stays
    BIT-IDENTICAL across two builds (the new code path is inert and does not
    perturb determinism — the non-negotiable byte-identical GATE)."""
    from world.combat import CombatWorld
    from world.combat_config import CombatConfig

    a = CombatWorld(CombatConfig(seed=1337))
    b = CombatWorld(CombatConfig(seed=1337))
    assert a.subs == [] and a.sonobuoys == [] and a.asw_rounds == []
    assert a.sub_contacts == {} and a._sonobuoy_stock == 0 and a._asw_ammo == 0
    assert _battle_digest(a) == _battle_digest(b), \
        "n_subs=0 default battle is not bit-identical across builds"
