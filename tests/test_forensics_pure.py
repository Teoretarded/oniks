"""game/forensics.py pure helpers — the ledger's display logic (GL-free).

The FOG DISPLAY GATE under test (user-locked): mid-battle the sheet names the
killer ONLY when the cause was recorded observed=True; an unobserved killer
displays LOST - UNCONFIRMED.  Post-battle the AAR may name everything but
must flag a reconstructed (unobserved) attribution.  Counters and the
cumulative ground-distance axis are derived 1:1 from the recorder — no
invented numbers.
"""

import numpy as np

from game.forensics import (
    cause_headline,
    cumulative_ground_km,
    stub_id,
    stub_status,
    tally,
)


def _rec(kind="oniks", seq=1, cause=None):
    return {"kind": kind, "seq": seq, "cause": cause,
            "launch_t": 0.0, "samples": [], "death": None,
            "target_xz": None, "events": []}


def _cause(code, detail=None, observed=True):
    return {"code": code, "detail": detail, "observed": observed}


# ---------------------------------------------------------------- identity

def test_stub_ids_by_kind():
    assert stub_id(_rec("oniks", 3)) == "ONX-3"
    assert stub_id(_rec("zircon", 1)) == "ZRC-1"
    assert stub_id(_rec("48n6", 2)) == "48N-2"


# ---------------------------------------------------------------- counters

def test_tally_derives_all_six_counters_from_causes():
    recs = [
        _rec(cause=_cause("hit", "destroyer")),            # HIT, observed
        _rec(cause=_cause("sam", "sm6")),                  # INT, observed
        _rec(cause=_cause("ciws", "destroyer", False)),    # INT, unconfirmed
        _rec(cause=_cause("fuel")),                        # OTHER, observed
        _rec(cause=_cause("lost", None, False)),           # OTHER, unconfirmed
        _rec(cause=None),                                  # still flying
    ]
    t = tally(recs)
    assert t == {"fired": 6, "hit": 1, "intercepted": 2, "other": 2,
                 "observed": 3, "unconfirmed": 2}


# ------------------------------------------------------------ fog display

def test_observed_interceptor_is_named_mid_battle():
    text, ink = stub_status(_cause("sam", "sm6"), battle_over=False)
    assert text == "SM-6 X" and ink == "red"


def test_unobserved_interceptor_is_gated_mid_battle():
    """FOG LAW: the killer was never a track — mid-battle the sheet must NOT
    name it."""
    text, ink = stub_status(_cause("sam", "sm6", observed=False),
                            battle_over=False)
    assert "SM-6" not in text
    assert text == "LOST?" and ink == "muted"


def test_unobserved_interceptor_flagged_reconstructed_post_battle():
    text, ink = stub_status(_cause("sam", "sm6", observed=False),
                            battle_over=True)
    assert text == "SM-6 X?" and ink == "red"


def test_hit_fuel_impact_and_live_stubs():
    assert stub_status(_cause("hit", "destroyer"), False) == ("HIT DDG",
                                                              "green")
    assert stub_status(_cause("hit", "carrier"), False) == ("HIT CV", "green")
    assert stub_status(_cause("fuel"), False) == ("FUEL", "amber")
    assert stub_status(_cause("impact"), False) == ("SPLASH", "muted")
    assert stub_status(None, False) == ("IN AIR", "teal")


def test_headline_names_only_observed_killers_mid_battle():
    assert cause_headline(_cause("sam", "sm6"), False) == \
        "KILLED BY SM-6 - OBSERVED"
    assert cause_headline(_cause("sam", "sm6", observed=False), False) == \
        "LOST - UNCONFIRMED"
    assert cause_headline(_cause("sam", "sm6", observed=False), True) == \
        "KILLED BY SM-6 - RECONSTRUCTED (NOT OBSERVED)"
    assert cause_headline(_cause("ciws", "destroyer"), False) == \
        "KILLED BY CIWS (DDG) - OBSERVED"
    assert cause_headline(_cause("hit", "destroyer"), False) == \
        "TARGET HIT - DDG"
    assert cause_headline(_cause("fuel"), False) == "FUEL EXHAUSTED"
    assert cause_headline(None, False) == "IN FLIGHT"


# ----------------------------------------------------- 1:1 distance axis

def test_cumulative_ground_km_is_sum_of_xz_hypots():
    """ACCURACY CONTRACT: the plot x-axis is the running sum of per-sample
    ground steps hypot(dx, dz) — altitude never leaks into distance."""
    path = np.array([
        # (t, x, y, z): leg 1 = hypot(3000, 4000) = 5 km ground;
        # leg 2 = 6 km along x WITH a 7 km climb — the climb must not count.
        [0.0, 0.0, 0.0, 0.0],
        [1.0, 3_000.0, 5_000.0, 4_000.0],
        [2.0, 9_000.0, 12_000.0, 4_000.0],
    ])
    km = cumulative_ground_km(path)
    assert km.shape == (3,)
    assert km[0] == 0.0
    assert abs(km[1] - 5.0) < 1e-12
    assert abs(km[2] - 11.0) < 1e-12
