"""Classification ladder + track quality (docs/research/classification_spec.md).

The fog-of-war upgrade the user asked for: DETECTION was always honest
physics, but IDENTIFICATION was free — a track printed 'SM6' on its first
frame.  Now type knowledge is EARNED by dwell (NCTR: class from kinematics in
seconds, type from signature analysis later), while position quality (Q5..Q1)
degrades separately with staleness.  Knowledge is monotonic: a coasting track
keeps what it earned; it loses WHERE, never WHAT.

Pure helpers in sim/contacts.py — GL-free, deterministic, no truth read
(classify/track_quality consume only the track dict + sim_time).
"""

import numpy as np

from sim.contacts import (
    CLASSIFY_DWELL, ContactBoard, OWN_KINDS, classify, track_quality,
)


def _track(*, kind="sm6", size="missile", first_seen=0.0, age=0.0,
           is_air=True):
    t = dict(pos=np.zeros(3), vel=np.zeros(3), age=age, t_next=0.0,
             is_air=is_air, kind=kind, size=size)
    if first_seen is not None:
        t["first_seen"] = first_seen
    return t


# ------------------------------------------------------------- ladder stages

def test_new_track_is_unknown_even_when_fresh():
    """Dwell 0: bearing/range/speed only — the label is UNK, never the type."""
    stage, label = classify(_track(first_seen=100.0), 100.0)
    assert stage == "UNKNOWN"
    assert label == "UNK"


def test_class_reveals_after_class_dwell():
    t_class, t_ident = CLASSIFY_DWELL["missile"]
    stage, label = classify(_track(first_seen=100.0), 100.0 + t_class)
    assert stage == "CLASSIFIED"
    assert label == "MSL"                    # size class, not the type


def test_type_reveals_after_ident_dwell():
    _t_class, t_ident = CLASSIFY_DWELL["missile"]
    stage, label = classify(_track(first_seen=100.0), 100.0 + t_ident)
    assert stage == "IDENTIFIED"
    assert label == "SM6"


def test_ladder_is_monotonic_no_regression_with_staleness():
    """A coasting (stale) track KEEPS its earned identification — staleness
    degrades position quality, never knowledge."""
    _t_class, t_ident = CLASSIFY_DWELL["missile"]
    stale = _track(first_seen=100.0, age=60.0)      # long unseen coast
    stage, label = classify(stale, 100.0 + t_ident + 60.0)
    assert stage == "IDENTIFIED" and label == "SM6"


def test_ship_classifies_slower_than_missile():
    assert CLASSIFY_DWELL["ship"][0] > CLASSIFY_DWELL["missile"][0]
    assert CLASSIFY_DWELL["ship"][1] > CLASSIFY_DWELL["missile"][1]


def test_platform_track_identified_label_is_class_label():
    """A platform (kind None) has no weapon type to reveal: the IDENTIFIED
    label stays its sensor class (SURF/AIR)."""
    t_ident = CLASSIFY_DWELL["ship"][1]
    stage, label = classify(
        _track(kind=None, size="ship", is_air=False, first_seen=0.0), t_ident)
    assert stage == "IDENTIFIED"
    assert label == "SURF"


def test_own_round_bypasses_ladder_iff():
    """Cooperative ID: our own rounds squawk — instantly identified."""
    for kind in ("oniks", "s300"):
        assert kind in OWN_KINDS
        stage, label = classify(_track(kind=kind, first_seen=100.0), 100.0)
        assert stage == "IDENTIFIED"
        assert label == kind.upper()


def test_legacy_track_without_first_seen_reads_identified():
    """Back-compat: a track dict with no first_seen stamp (old fixtures,
    probes) degrades to today's instant-ID behavior instead of crashing."""
    stage, label = classify(_track(first_seen=None), 5.0)
    assert stage == "IDENTIFIED" and label == "SM6"


# ------------------------------------------------------------- track quality

def test_quality_bands_two_sided():
    """Q5 fresh paint .. Q1 about to drop (drop is at 90 s)."""
    assert track_quality(_track(age=0.0)) == 5
    assert track_quality(_track(age=5.0)) == 4
    assert track_quality(_track(age=20.0)) == 3
    assert track_quality(_track(age=45.0)) == 2
    assert track_quality(_track(age=75.0)) == 1


# ------------------------------------ first_seen stamped by the ContactBoard

class _Ent:
    is_air = True
    radar_size = "missile"

    def __init__(self):
        self.aircraft_id = "hostile_1"
        self.pos = np.array([1000.0, 100.0, 0.0])
        self.alive = True

    def velocity(self):
        return np.array([-100.0, 0.0, 0.0])


def test_board_stamps_first_seen_at_track_creation():
    board = ContactBoard((0.0, 0.0), visible_fn=lambda pos, size: True)
    ent = _Ent()
    # The 2 s continuous-visibility detect delay must elapse first.
    t = 0.0
    for _ in range(30):
        board.update([ent], 0.1, t)
        t += 0.1
    trk = board.tracks["hostile_1"]
    assert "first_seen" in trk
    # Stamped when the track FORMED (after DETECT_DELAY_S), not at t=0.
    assert 1.9 <= trk["first_seen"] <= t
    # And the ladder runs off it: a brand-new real track reads UNK.
    stage, label = classify(trk, trk["first_seen"])
    assert stage == "UNKNOWN" and label == "UNK"


# --------------------------------------- interceptor pairings (proto 03)

def test_interceptor_pairings_counts_own_air_shots_only():
    """PAIRED/UNCOVERED reads MY rounds' own target refs (own-force truth):
    enemy rounds and surface-target shots never count."""
    from game.hud import interceptor_pairings

    class _Tgt:
        def __init__(self, tid, is_air=True):
            self.aircraft_id = tid
            self.is_air = is_air

    class _Round:
        def __init__(self, target, hostile=False, alive=True):
            self.target = target
            self.is_hostile = hostile
            self.alive = alive

    class _Ship:                      # surface target: not an interceptor shot
        is_air = False

    class _W:
        def __init__(self, missiles):
            self.missiles = missiles

    vamp = _Tgt("hostile_7")
    w = _W([
        _Round(vamp),                          # ours, at the vampire
        _Round(vamp),                          # second interceptor, same tgt
        _Round(_Tgt("hostile_9")),             # ours, other vampire
        _Round(vamp, hostile=True),            # ENEMY round: ignored
        _Round(vamp, alive=False),             # splashed: ignored
        _Round(_Ship()),                       # anti-ship shot: ignored
        _Round(None),                          # no assignment: ignored
    ])
    p = interceptor_pairings(w)
    assert p == {"hostile_7": 2, "hostile_9": 1}


# --------------------------------------------- platform-type NCTR (2026-07-05)
# The user's radar-signature depth ask: an enemy AIRFRAME earns its platform
# TYPE (FIGHTER / AWACS / JAMMER) only after a LONG signature dwell — the
# ladder's third tier.  Between weapon-ident dwell and platform dwell the
# track reads IDENTIFIED 'AIR': class known, exact platform not yet.  Ships
# (no platform_kind) keep the existing SURF behavior — pinned above.

def test_aircraft_platform_type_needs_the_platform_dwell():
    from sim.contacts import PLATFORM_IDENT_DWELL
    t_ident = CLASSIFY_DWELL["fighter"][1]
    t_plat = PLATFORM_IDENT_DWELL["fighter"]
    trk = _track(kind="awacs", size="fighter", is_air=True, first_seen=0.0)
    assert classify(trk, t_ident) == ("IDENTIFIED", "AIR")
    assert classify(trk, t_plat - 0.1) == ("IDENTIFIED", "AIR")
    assert classify(trk, t_plat) == ("IDENTIFIED", "AWACS")


def test_platform_dwell_is_slower_than_weapon_ident_two_sided():
    from sim.contacts import PLATFORM_IDENT_DWELL
    for size, t_plat in PLATFORM_IDENT_DWELL.items():
        assert t_plat > CLASSIFY_DWELL[size][1], (
            "platform NCTR must be SLOWER than weapon-type ident")
        assert t_plat <= 90.0, "and still earnable before the track drops"


def test_enemy_airframes_carry_platform_kind_stamps():
    from sim.contacts import PLATFORM_KINDS, _kind_of
    from sim.enemy_air import Awacs, Fighter, JammerAircraft
    assert Fighter.platform_kind == "fighter"
    assert Awacs.platform_kind == "awacs"
    assert JammerAircraft.platform_kind == "jammer"
    assert {"fighter", "awacs", "jammer"} <= PLATFORM_KINDS

    class _Bare:
        platform_kind = "awacs"

    assert _kind_of(_Bare()) == "awacs"
