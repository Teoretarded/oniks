"""The S-300 vs inbound hostile STRIKE ROUNDS (live playtest 2026-07-03:
'I can't intercept the missiles').

Root cause: CombatWorld._find_air_entity searched aircraft + enemy_air only;
hostile strike rounds live in world.missiles keyed by the same aircraft_id
their track carries, so launch_sam returned a silent None for EVERY
anti-missile shot — the S-300 (and the Buk, same hook) physically could not
engage cruise missiles despite the docstring promising them as targets.

Envelope note (measured, tools/probe_s300_vs_tomahawk.py): with the fix the
user-tuned 48N6 kills a 50 m skimmer that passes ~20 km from the SITE
(closest 27.7 m -> fuse); 35+ km wave-top shots run out of energy after the
loft — consistent with the real S-300's ~25-40 km low-altitude envelope, so
only the CLOSE case is contracted here."""

import numpy as np
import pytest

from sim.strike import SPH_STRIKE_CRUISE
from world.combat import CombatWorld
from world.combat_config import CombatConfig
from world.generation import BASE_POS
from world.world import SAM_TEL_POS

DT = 1.0 / 120.0


def _cruising_tlam(w):
    """Fire the world's own Tomahawk salvo and fly the first round to CRUISE
    (the real machine state a player faces); kill the extras."""
    base = np.array(BASE_POS, dtype=np.float64)
    w._fire_tomahawk_salvo(dict(
        target_pos=np.array([base[0], 0.0, base[2]]), target_id="probe"))
    tlams = [m for m in w.missiles
             if getattr(m, "weapon", None) is not None
             and m.weapon.weapon_id == "tomahawk"]
    assert tlams, "the salvo machinery must spawn rounds"
    tlam = tlams[0]
    for extra in tlams[1:]:
        extra.alive = False
    for _ in range(int(120.0 / DT)):
        w.step(DT)
        if tlam.phase == SPH_STRIKE_CRUISE:
            break
    assert tlam.phase == SPH_STRIKE_CRUISE
    return tlam


def test_find_air_entity_resolves_hostile_strike_rounds():
    """The entity behind a strike round's track id must resolve — this is the
    lookup launch_sam needs before it will fire."""
    w = CombatWorld(CombatConfig(seed=1337))
    tlam = _cruising_tlam(w)
    ent = w._find_air_entity(tlam.aircraft_id)
    assert ent is tlam


@pytest.mark.slow
def test_s300_kills_a_sea_skimmer_passing_close_to_the_site():
    """E2E: a cruising Tomahawk 20 km from the SAM site is tracked, launched
    on (launch_sam returns a ROUND, not the silent None), and KILLED by the
    48N6 well before the Pantsir ring — the player's anti-missile shot works."""
    w = CombatWorld(CombatConfig(seed=1337))
    base = np.array(BASE_POS, dtype=np.float64)
    site = np.array(SAM_TEL_POS, dtype=np.float64)
    tlam = _cruising_tlam(w)
    tlam.pos[0] = site[0]
    tlam.pos[2] = site[2] + 20_000.0

    track_id, fired, sams = None, 0, []
    for _ in range(int(300.0 / DT)):
        w.step(DT)
        if track_id is None:
            for cid, tr in w.contacts.tracks.items():
                if tr.get("is_air"):
                    est = w.contacts.estimated_pos(cid, w.sim_time)
                    if est is not None and \
                            abs(float(est[2]) - float(tlam.pos[2])) < 15_000.0:
                        track_id = cid
                        break
        if track_id is not None and fired < 2:
            sam = w.launch_sam(track_id, round_id="48n6")
            if sam is not None:
                sams.append(sam)
                fired += 1
        if not tlam.alive:
            break
    assert fired > 0, "launch_sam must FIRE at a strike track (was silent None)"
    assert not tlam.alive, "the 48N6 must kill the close skimmer"
    dist_base = float(np.linalg.norm(np.asarray(tlam.pos) - base))
    assert dist_base > 6_000.0, (
        "the kill must be the S-300's (beyond the Pantsir point-defense ring), "
        f"but the round died {dist_base / 1e3:.1f} km from the base")
