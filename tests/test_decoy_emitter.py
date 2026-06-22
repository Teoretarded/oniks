"""M5 #5 — ESM DECOY EMITTER (sim/decoys.DecoyEmitter + world wiring).

The decoy works ONLY by planting a REAL sensor event: a radiating object the
enemy ESM genuinely hears, so the EXISTING commander schedules a HARM at the
located decoy.  NO commander decision code is touched; NO "miss" flag; NO truth
read.  The decoy NEVER detects anything (bait, not a sensor).

Contracts (spec 06 F4):
  - with a decoy EMITTING and the real radar SILENT, the enemy EnemyPicture forms
    a LOCATED EmitterIntel on the DECOY id, and the commander schedules a HARM
    package whose target_id == the decoy (HARM wasted) — fog-honest;
  - the decoy in _emitters() is HEARD by the enemy feed but NEVER detects anything
    (empty ranges — detects() returns nothing for any target);
  - a decoy Structure killed by a HARM marks its EmitterIntel dead (the EXISTING
    HARM BDA path mark_emitter_destroyed);
  - DETERMINISM: same seed -> same decoy placement;
  - byte-identical default: n_decoys=0 builds NO decoy (absent from _emitters()).
"""

from __future__ import annotations

import numpy as np

from sim.commander import EnemyCommander, EnemyPicture
from sim.decoys import DecoyEmitter, DECOY_RANGES
from world.combat import CombatWorld
from world.combat_config import CombatConfig

DT = 1.0 / 120.0


# ---------------------------------------------------------------------------
# Pure DecoyEmitter unit contracts
# ---------------------------------------------------------------------------

def test_decoy_emitter_radar_ducktype():
    """A DecoyEmitter exposes the Radar attributes the ELINT feed reads."""
    d = DecoyEmitter("decoy_00", (1000.0, 50.0, -200.0))
    assert d.radar_id == "decoy_00"
    assert d.alive and d.emitting
    assert d.pos.dtype == np.float64
    # antenna_alt = ground + mast (the ESM/LOS horizon datum).
    assert d.antenna_alt == 50.0 + d.antenna_m


def test_decoy_detects_nothing_any_class():
    """Empty ranges -> the decoy NEVER detects (bait, not a sensor).  A target
    sitting right on top of it is still invisible for every size class."""
    assert DECOY_RANGES == {}, "decoy ranges must be empty (bait)"
    d = DecoyEmitter("decoy_00", (0.0, 0.0, 0.0))
    on_top = np.array([0.0, 10.0, 0.0], dtype=np.float64)
    for size in ("ship", "fighter", "missile", "stealth", "lcac"):
        assert d.detects(on_top, size) is False
    # Even silenced/dead it never detects (defensive: detects is unconditional).
    d.alive = False
    assert d.detects(on_top, "ship") is False


# ---------------------------------------------------------------------------
# Enemy ESM hears the decoy -> located EmitterIntel (pure picture path)
# ---------------------------------------------------------------------------

def test_decoy_accrues_located_emitter_intel():
    """Feeding the decoy through update_emitter (the SAME path the world uses for
    the real radar) builds a real, LOCATED EmitterIntel — the prerequisite the
    EXISTING commander _doctrine_blind targets."""
    pic = EnemyPicture()
    d = DecoyEmitter("decoy_00", (5000.0, 30.0, -1000.0))
    # 90 s of cumulative emission (ESM_FIX_TIME_S) -> a firing-quality fix.
    t = 0.0
    while t < 95.0:
        pic.update_emitter(d.radar_id, d.pos, True, 0.25, t)
        t += 0.25
    ei = pic.emitters[d.radar_id]
    assert ei.located, "decoy ESM fix should mature to located"
    assert ei.alive


# ---------------------------------------------------------------------------
# World wiring: decoy in _emitters / heard / HARM diverted
# ---------------------------------------------------------------------------

def test_decoy_built_and_not_in_player_elint():
    """A built decoy lives in world._decoy_emitters (heard by the ENEMY ESM via
    _feed_enemy_picture); absent at n_decoys=0 (byte-identical default).  CRUCIAL
    FOG CHECK: the player's own decoy must NEVER leak into _emitters() — that is
    the ENEMY-radar list the player's DRONE ELINT hears, so a decoy there would be
    a fog violation (the player magically 'hearing' its own bait as a contact)."""
    cw0 = CombatWorld(CombatConfig(seed=1337, n_decoys=0))
    assert cw0._decoy_emitters == []

    cw1 = CombatWorld(CombatConfig(seed=1337, n_decoys=1))
    assert [d.radar_id for d in cw1._decoy_emitters] == ["decoy_00"]
    # No leak into the player-facing drone-ELINT enemy-emitter list.
    assert not any(eid.startswith("decoy_") for eid, _ in cw1._emitters())


def test_decoy_diverts_harm_package():
    """With the decoy lit and the real radar SILENT, the only located emitter the
    enemy can find is the decoy -> the commander schedules a HARM whose target_id
    is the decoy id (HARM wasted on bait).  Fog-honest: the commander only ever
    saw a real emission; NO decision code is modified."""
    cw = CombatWorld(CombatConfig(seed=1337, n_decoys=1))
    cw.radar_station.emitting = False        # real eyes dark -> only the decoy emits
    decoy_ids = {d.radar_id for d in cw._decoy_emitters}

    harm_target = None
    for _ in range(int(200 * 120)):
        cw.step(DT)
        for rec in cw._cmd_missions:
            if rec["kind"] == "harm_package":
                harm_target = rec["target_id"]
                break
        if harm_target is not None:
            break
    assert harm_target in decoy_ids, (
        f"HARM should target the decoy bait, got {harm_target}")


def test_decoy_emitter_intel_dead_on_harm_bda():
    """A decoy 'killed' by a HARM marks its EmitterIntel dead via the EXISTING
    HARM BDA path (mark_emitter_destroyed) — no special case.  We assert the
    EXISTING world path: marking the emitter destroyed flips the intel alive flag,
    exactly as the radar station does."""
    cw = CombatWorld(CombatConfig(seed=1337, n_decoys=1))
    pic = cw.commander.picture
    d = cw._decoy_emitters[0]
    # Mature a fix so the intel exists + is located.
    t = 0.0
    while t < 95.0:
        cw._feed_enemy_picture(0.25, t)
        t += 0.25
    assert pic.emitters[d.radar_id].located
    # The EXISTING BDA path (run in _update_commander_missions for a completed
    # HARM) marks the emitter destroyed by id — call it directly with the decoy id.
    cw.commander.picture.mark_emitter_destroyed(d.radar_id)
    assert pic.emitters[d.radar_id].alive is False


def test_decoy_death_clears_emitter_via_structure():
    """Killing the decoy Structure clears the DecoyEmitter.alive (the wrapper's
    on_destroyed), so the _feed_enemy_picture decoy accrual goes heard=False: a
    decoy believed destroyed (HARM BDA) is NEVER re-marked alive by the feed, and
    its fix decays — the bait drops out of the picture with its mast."""
    cw = CombatWorld(CombatConfig(seed=1337, n_decoys=1))
    d = cw._decoy_emitters[0]
    pic = cw.commander.picture
    struct = next(s for s in cw.structures
                  if s.structure_id == f"{d.radar_id}_struct")
    # Mature a located, alive ESM fix on the live decoy (the feed hears it).
    t = 0.0
    while t < 95.0:
        cw._feed_enemy_picture(0.25, t)
        t += 0.25
    ei = pic.emitters[d.radar_id]
    assert ei.located and ei.alive
    fix_before = ei.fix_progress
    # A HARM kills the bait: the BDA marks the intel destroyed AND the Structure
    # death clears the emitter's alive flag (HP=1 -> dies on the first hit).
    pic.mark_emitter_destroyed(d.radar_id)
    struct.hit()
    assert not struct.alive
    assert d.alive is False, "decoy emitter alive must clear with its Structure"
    # Feed again: a DEAD decoy is heard=False, so it is NEVER re-marked alive and
    # its fix DECAYS.  Load-bearing — an un-gated mark_emitter_alive (or a failure
    # to clear d.alive) would resurrect the bait and fail here.
    cw._feed_enemy_picture(0.25, t)
    assert pic.emitters[d.radar_id].alive is False, "dead decoy must not be re-lit"
    assert pic.emitters[d.radar_id].fix_progress < fix_before, "dead bait fix decays"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_decoy_placement_deterministic():
    """Same seed -> same decoy placement."""
    a = CombatWorld(CombatConfig(seed=4242, n_decoys=2))
    b = CombatWorld(CombatConfig(seed=4242, n_decoys=2))
    pa = [tuple(np.round(d.pos, 6)) for d in a._decoy_emitters]
    pb = [tuple(np.round(d.pos, 6)) for d in b._decoy_emitters]
    assert pa == pb
    assert len(pa) == 2
