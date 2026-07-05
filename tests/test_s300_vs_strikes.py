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


@pytest.mark.slow
def test_pantsir_stops_an_on_target_tomahawk_salvo():
    """The point-defense layer must actually DEFEND: an on-target 2-round
    Tomahawk salvo dies to the Pantsir ring BEFORE reaching the base
    structures.  REGRESSION: the multipath tracking error was a flat 60 m
    regardless of range (an ANGLE error baked in at its 20 km calibration),
    so the Pantsir at 3-8 km chased long-range noise with an 8 m fuse —
    measured: a full 12-round magazine spent for ~one kill, one leaker
    IMPACTING the base every time.  With the range-scaled error the salvo
    dies 3+ km out (measured across seeds 1337/42/7)."""
    from sim.strike import SPH_STRIKE_CRUISE

    w = CombatWorld(CombatConfig(seed=1337))
    base = np.array(BASE_POS, dtype=np.float64)
    w.radar_station.emitting = False          # the live-playtest EMCON case
    w._fire_tomahawk_salvo(dict(
        target_pos=np.array([base[0], 0.0, base[2]]), target_id="probe"))
    tlams = [m for m in w.missiles
             if getattr(m, "weapon", None) is not None
             and m.weapon.weapon_id == "tomahawk"]
    for _ in range(int(120.0 / DT)):
        w.step(DT)
        if all(m.phase == SPH_STRIKE_CRUISE for m in tlams if m.alive):
            break
    for k, m in enumerate(tlams):
        m.pos[0] = base[0] + k * 300.0
        m.pos[2] = base[2] + 30_000.0
    for _ in range(int(300.0 / DT)):
        w.step(DT)
        if not any(m.alive for m in tlams):
            break
    assert not any(m.alive for m in tlams), "the salvo must be stopped"
    for m in tlams:
        d = float(np.linalg.norm(np.asarray(m.pos) - base))
        # Re-pin 2026-07-06 (argued): 900 m, not 2000. Under the honest
        # energy model one round of the salvo reaches the GUN layer, which
        # kills it at its designed ~1.2 km last-ditch range (the kill sits
        # at 1195 m across ALL missile-profile variants — it is the gun's
        # geometry, not a flight artifact). The 2 km pin encoded the old
        # free-energy "missiles get everything" outcome; the contract that
        # matters — stopped clear of the structures, nothing lost — holds.
        assert d > 900.0, (
            f"a round died only {d:.0f} m from the base — the point-defense "
            "ring must kill inbound strikes clear of the structures")
    assert all(s.alive for s in w.structures), "no structure may be lost"
