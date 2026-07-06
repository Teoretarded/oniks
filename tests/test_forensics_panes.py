"""Forensics pane pure helpers — BLACK BOX density deck + row formatting.

The deck (approved variation C) feeds from CombatState.ledger.records (the
SHIPPED BattleLedger).  Pure display logic under test: lane mapping, time
binning, and the row formatter — including the FOG GATE on loss rows (an
unobserved cause is never named mid-battle, even on the black box tape).
"""

from game.forensics import bin_lane_counts, fmt_ledger_row, ledger_lane


def test_ledger_lane_maps_all_record_kinds():
    assert ledger_lane({"rec": "cmd", "ok": True}) == "cmd"
    assert ledger_lane({"rec": "cmd", "ok": False}) == "hint"   # denial lane
    assert ledger_lane({"rec": "hint"}) == "hint"
    assert ledger_lane({"rec": "evt"}) == "evt"
    assert ledger_lane({"rec": "toggle"}) == "toggle"
    assert ledger_lane({"rec": "loss"}) == "loss"
    assert ledger_lane({"rec": "mark"}) == "mark"
    assert ledger_lane({"rec": "hash"}) == "hash"
    assert ledger_lane({"rec": "header"}) is None               # not a lane


def test_bin_lane_counts_bins_by_time():
    records = [
        {"rec": "cmd", "t": 1.0, "ok": True},
        {"rec": "cmd", "t": 9.0, "ok": True},
        {"rec": "evt", "t": 9.5},
        {"rec": "hash", "t": 5.0},
        {"rec": "header"},                      # no t, no lane: ignored
        {"rec": "evt", "t": 99.0},              # outside range: ignored
    ]
    bins = bin_lane_counts(records, 0.0, 10.0, 5)
    assert bins["cmd"] == [1, 0, 0, 0, 1]
    assert bins["evt"] == [0, 0, 0, 0, 1]
    assert bins["hash"] == [0, 0, 1, 0, 0]
    assert bins["loss"] == [0, 0, 0, 0, 0]


def test_fmt_cmd_ok_and_denied():
    ok = {"rec": "cmd", "t": 3.0, "verb": "launch", "ok": True,
          "args": {"profile": "lo-lo", "weapon_id": "oniks"}}
    kind, text, ink = fmt_ledger_row(ok, battle_over=True)
    assert kind == "CMD" and ink == "teal"
    assert "launch" in text and "OK" in text
    denied = {"rec": "cmd", "t": 4.0, "verb": "launch_sam", "ok": False,
              "args": {"aircraft_id": "tk_09"}}
    kind, text, ink = fmt_ledger_row(denied, battle_over=True)
    assert ink == "red" and "DENIED" in text


def test_fmt_loss_gates_unobserved_cause_mid_battle():
    """FOG LAW on the tape: the ledger RECORDS the true cause, but the
    mid-battle display may not name an unobserved killer."""
    loss = {"rec": "loss", "t": 8.0, "kind": "oniks", "seq": 6,
            "code": "sam", "detail": "sm6", "observed": False}
    _, text_mid, _ = fmt_ledger_row(loss, battle_over=False)
    assert "sm6" not in text_mid.lower()
    assert "UNCONFIRMED" in text_mid
    _, text_end, _ = fmt_ledger_row(loss, battle_over=True)
    assert "SM6" in text_end.upper()


def test_fmt_loss_observed_named_mid_battle():
    loss = {"rec": "loss", "t": 8.0, "kind": "oniks", "seq": 6,
            "code": "sam", "detail": "sm6", "observed": True}
    _, text, ink = fmt_ledger_row(loss, battle_over=False)
    assert "SM6" in text.upper() and ink == "red"


def test_fmt_other_kinds():
    _, text, ink = fmt_ledger_row(
        {"rec": "hash", "t": 5.0, "tick": 600, "digest": "9c41deadbeef"},
        battle_over=True)
    assert "9C41DEAD" in text.upper() and ink == "muted"
    _, text, _ = fmt_ledger_row(
        {"rec": "toggle", "t": 6.0, "name": "radar.emitting",
         "value": False}, battle_over=True)
    assert "radar.emitting" in text and "FALSE" in text.upper()
    _, text, _ = fmt_ledger_row(
        {"rec": "evt", "t": 7.0, "kind": "ciws_burst",
         "pos": [63_800.0, 0.0, 97_900.0]}, battle_over=True)
    assert "ciws_burst" in text and "+63.8" in text and "+97.9" in text
    _, text, _ = fmt_ledger_row(
        {"rec": "mark", "t": 9.0, "tick": 1080, "note": "BUG"},
        battle_over=True)
    assert "BUG" in text
