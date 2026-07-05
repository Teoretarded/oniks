"""Launch-sequence oracles for EVERY weapon (plan Phase 2 — the AI-testable
launch feature).

Each weapon's launch is integrated headless by
tools/probe_launch_kinematics.launch_record (the same code path the CLI
probe uses; CSV/JSON artifacts land in renders/launch/). The bands below
are MEASURED (probe run 2026-07-05) and sanity-checked against
docs/research/launch_sequences_2026-07-05.md — two-sided on purpose: a
launch that gets faster/snappier than the researched behavior is as wrong
as one that gets slower. Re-run the probe BEFORE touching any band.
"""

import math

import pytest

from sim.physics import speed_of_sound_scalar
from tools.probe_launch_kinematics import DT, launch_record

# weapon_id -> (exact phase-label sequence, peak path-turn-rate cap deg/s)
# Turn caps: Missile machine PITCH_RATE_MAX 70 (+margin), SamMissile
# TILT_RATE_MAX 45 (+margin; measured 27-33), StrikeMissile boost pitch 20.
ORACLES = {
    "oniks": (["IGNITION", "RIDE-OUT", "PITCH-OVER", "BOOST", "CLIMB"], 75.0),
    "zircon": (["IGNITION", "RIDE-OUT", "PITCH-OVER", "BOOST", "CLIMB"], 75.0),
    # The cell-tossed loiterer reaches its whole speed band during ride-out
    # (booster cut) and turns downrange IMMEDIATELY (measured: pitch-over
    # from ~0.9 s, apex ~250 m, settles into cruise).
    "swarm": (["IGNITION", "RIDE-OUT", "PITCH-OVER", "BOOST", "CRUISE"], 75.0),
    "s300": (["EJECT", "BOOST", "MIDCOURSE"], 48.0),
    # 40n6/sm6 re-pin 2026-07-06: the wave-3 energy-cruise shaping flies a
    # longer approach — neither reaches TERMINAL inside the 30 s record.
    "40n6": (["EJECT", "BOOST", "MIDCOURSE"], 48.0),
    "asbm": (["EJECT", "BOOST", "MIDCOURSE"], 48.0),
    "sm2": (["EJECT", "BOOST", "MIDCOURSE"], 48.0),
    "sm6": (["EJECT", "BOOST", "MIDCOURSE"], 48.0),
    "buk_9m317": (["EJECT", "BOOST", "MIDCOURSE", "TERMINAL"], 48.0),
    "buk_9m338": (["EJECT", "BOOST", "MIDCOURSE", "TERMINAL"], 48.0),
    # Sprint-profile re-pin 2026-07-06 (55 kN / 1.16 s real boost): the
    # measured 87 g sprint changes the 30 s record's endpoint phase.
    "pantsir_57e6": (["EJECT", "BOOST", "MIDCOURSE"], 48.0),
    "tomahawk": (["EJECT", "BOOST", "CRUISE"], 25.0),
    "kalibr": (["EJECT", "BOOST", "CRUISE"], 25.0),
    "jassm": (["EJECT", "CLIMB"], 25.0),
    "harm": (["EJECT", "CRUISE"], 25.0),
    "kh31p": (["EJECT", "CLIMB"], 25.0),
}

_RECORDS = {}


def _rec(weapon_id):
    if weapon_id not in _RECORDS:
        _RECORDS[weapon_id] = launch_record(weapon_id)
    return _RECORDS[weapon_id]


def _transition(summary, phase):
    for tr in summary["transitions"]:
        if tr["phase"] == phase:
            return tr
    raise AssertionError(f"no {phase} transition in {summary['transitions']}")


@pytest.mark.parametrize("weapon_id", sorted(ORACLES))
def test_launch_phase_sequence_and_rates(weapon_id):
    """Phase order is exactly the documented launch sequence; the path never
    turns faster than the researched tip-over caps; nothing goes NaN or
    underground; the round survives its launch (the Pantsir record runs all
    the way to a terminal FUSE on its test target — death by success)."""
    rec = _rec(weapon_id)
    s = rec["summary"]
    phases, turn_cap = ORACLES[weapon_id]
    got = [tr["phase"] for tr in s["transitions"]]
    assert got == phases, f"{weapon_id}: {got} != {phases}"
    assert s["peak_turn_rate_dps"] <= turn_cap, (
        f"{weapon_id} turned {s['peak_turn_rate_dps']} deg/s (cap {turn_cap})")
    assert s["alive_at_end"] or s["killed_target"], f"{weapon_id} died"
    for r in rec["rows"]:
        assert math.isfinite(r["speed"]) and math.isfinite(r["y"])
        assert r["y"] > -1.0, f"{weapon_id} underground at t={r['t']}"


@pytest.mark.parametrize("weapon_id,ign_t,alt_lo,alt_hi", [
    # Cold catapult launches: ballistic hang, motor lights at the delay-unit
    # time near apex with almost no vertical speed (research: pop 16-30 m,
    # delay ~1-1.5 s; measured 2026-07-05: s300 17.9 m / 4.1 m/s).
    ("s300", 1.5, 12.0, 32.0),
    ("40n6", 1.5, 12.0, 32.0),
    ("asbm", 1.0, 10.0, 32.0),
])
def test_cold_launch_hang_then_ignition(weapon_id, ign_t, alt_lo, alt_hi):
    s = _rec(weapon_id)["summary"]
    ign = _transition(s, "BOOST")
    assert abs(ign["t"] - ign_t) < 0.05, f"ignition at {ign['t']} s"
    assert alt_lo <= ign["alt_m"] <= alt_hi, f"pop height {ign['alt_m']} m"
    assert ign["speed_ms"] < 12.0, (
        f"{weapon_id} must IGNITE AT THE HANG (near-zero speed), "
        f"got {ign['speed_ms']} m/s")


@pytest.mark.parametrize("weapon_id,ign_t", [
    ("buk_9m317", 0.3), ("buk_9m338", 0.3), ("pantsir_57e6", 0.3),
    ("sm2", 0.5), ("sm6", 0.5),
])
def test_hot_launch_immediate_motor(weapon_id, ign_t):
    """Rail/VLS hot launches: motor within half a second, no hang."""
    s = _rec(weapon_id)["summary"]
    ign = _transition(s, "BOOST")
    assert abs(ign["t"] - ign_t) < 0.05
    assert ign["alt_m"] < 15.0, "hot launch must not coast upward unlit"


@pytest.mark.parametrize("weapon_id", ["oniks", "zircon"])
def test_oniks_family_tube_exit_and_boost_handover(weapon_id):
    """Warm tube launch: ~30 m/s muzzle exit (oniks_launch_sequence.md), and
    the booster hands over to the ramjet at Mach 2.0 (two-sided)."""
    rec = _rec(weapon_id)
    assert 27.0 <= rec["rows"][0]["speed"] <= 34.0
    hand = _transition(rec["summary"], "CLIMB")
    mach = hand["speed_ms"] / speed_of_sound_scalar(hand["alt_m"])
    assert 1.85 <= mach <= 2.15, f"boost handover at Mach {mach:.2f}"


def test_swarm_no_boost_overshoot_regression():
    """The 55 kg loiterer must NOT zoom (old bug: Oniks-sized 46 kN ride-out
    took it to ~Mach 6 / 3.7 km and it crashed back 25 km out). Two-sided:
    it clears the cell briskly but stays subsonic and settles into cruise."""
    rec = _rec("swarm")
    s = rec["summary"]
    assert s["apex_alt_m"] < 2_500.0, f"swarm zoomed to {s['apex_alt_m']} m"
    assert max(r["mach"] for r in rec["rows"]) <= 0.85
    assert s["alive_at_end"]
    assert 90.0 <= s["final"]["speed"] <= 220.0, (
        f"swarm should settle near its cruise band, got {s['final']['speed']}")


@pytest.mark.parametrize("weapon_id", ["tomahawk", "kalibr"])
def test_vls_cruiser_booster_burn_then_turbofan(weapon_id):
    """VLS strike: booster carries ~12 s (research: Mk 106 26.7 kN / 12 s),
    hands over subsonic, and the round is down on the deck in cruise."""
    s = _rec(weapon_id)["summary"]
    cruise = _transition(s, "CRUISE")
    assert 11.0 <= cruise["t"] <= 14.0, f"turbofan light at {cruise['t']} s"
    assert cruise["speed_ms"] < 300.0, "burnout must be subsonic"
    assert s["final"]["y"] < 120.0, "cruiser must settle onto the deck"


def test_jassm_drops_before_motor_light():
    """Air drop: documented nose-down free-fall (~1 s per the game recipe,
    inside the researched 0.5-2 s band) BEFORE the motor lights."""
    rec = _rec("jassm")
    fall = rec["rows"][int(0.9 / DT)]
    assert fall["pitch_deg"] < 0.0, "JASSM must be falling at 0.9 s"
    climb = _transition(rec["summary"], "CLIMB")
    assert 0.9 <= climb["t"] <= 1.15
