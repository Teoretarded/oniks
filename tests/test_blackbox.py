"""BLACK BOX / BATTLE LEDGER contracts (AI-testability build, 2026-07-05).

The three locked contracts:

  * LEDGER — every battle leaves a structured, append-only JSONL record:
    header (config + seed), player commands with RESOLVED args, refusal
    hints (the denial channel), world effect events, per-N-tick state
    hashes.  Side-effect-free w.r.t. the sim: recording a battle must not
    change it (digest-locked separately by tools/wf_m5_digest.py).

  * REPLAY — a recorded command log re-runs bit-for-bit against a fresh
    CombatWorld built from the same config: same state digest at the same
    tick.  A tampered log (a dropped command) is DETECTED, not absorbed.

  * BUG REPORT — a pure writer bundles the ledger + commands + context
    into a folder; the report states only recorded facts.

All tests are GL-free: game/blackbox.py is a pure module (json/hashlib/
numpy), tapped onto a bare CombatWorld exactly as CombatState taps it.
"""

import json
import os

import numpy as np

from game.blackbox import (
    BattleLedger, CommandRecorder, load_ledger, replay_battle, state_digest,
    write_bug_report,
)
from world.combat import CombatWorld
from world.combat_config import CombatConfig

DT = 1.0 / 120.0


# ------------------------------------------------------------------- ledger

def test_ledger_records_header_and_events_in_memory():
    """A path-less ledger records everything in memory and touches no disk."""
    led = BattleLedger(path=None)
    led.header(CombatConfig(seed=42), created="2026-07-05T00:00:00Z",
               commit="abc1234")
    led.hint(3.5, "S-300: NO READY TUBE / TARGET LOST")
    led.evt(4.0, "ship_hit", np.array([1.0, 2.0, 3.0]))
    assert led.records[0]["rec"] == "header"
    assert led.records[0]["seed"] == 42
    assert led.records[0]["config"]["seed"] == 42
    assert led.records[1] == {"rec": "hint", "t": 3.5,
                              "text": "S-300: NO READY TUBE / TARGET LOST"}
    evt = led.records[2]
    assert evt["rec"] == "evt" and evt["kind"] == "ship_hit"
    assert evt["pos"] == [1.0, 2.0, 3.0]        # numpy coerced to plain JSON


def test_ledger_writes_jsonl_and_roundtrips(tmp_path):
    """With a path, every record appends one JSON line; load_ledger returns
    the identical records (the crash-safe black-box property: the file is
    complete up to the last event even if the process dies)."""
    p = tmp_path / "battle_test.jsonl"
    led = BattleLedger(path=str(p))
    led.header(CombatConfig(seed=7), created="x", commit="y")
    led.cmd(0.5, 60, "launch",
            {"profile": "hi-lo", "target_point": [0.0, 0.0, 200000.0],
             "waypoints": [], "weapon_id": "oniks"}, ok=True, kind="oniks")
    led.mark(1.0, 120, note="BUG")
    led.close()
    assert p.exists()
    header, records = load_ledger(str(p))
    assert header["seed"] == 7
    assert [r["rec"] for r in records] == ["header", "cmd", "mark"]
    assert records[1]["args"]["weapon_id"] == "oniks"
    assert records[1]["tick"] == 60


def test_ledger_memory_only_never_touches_disk(tmp_path, monkeypatch):
    """path=None must never create a file even after many records (the
    headless-test / hidden-tool mode)."""
    monkeypatch.chdir(tmp_path)
    led = BattleLedger(path=None)
    led.header(None, created="", commit="")
    for i in range(50):
        led.hint(float(i), "X")
    led.close()
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------- recorder

def _tapped_world(seed=1337):
    world = CombatWorld(CombatConfig(seed=seed))
    led = BattleLedger(path=None)
    tick = {"n": 0}
    rec = CommandRecorder(led, lambda: tick["n"])
    rec.tap(world)
    return world, led, rec, tick


def test_tap_records_launch_with_resolved_args():
    world, led, rec, tick = _tapped_world()
    tick["n"] = 60
    m = world.launch("hi-lo", np.array([0.0, 0.0, 200_000.0]))
    assert m is not None                       # the tap must not break firing
    cmds = [r for r in led.records if r["rec"] == "cmd"]
    assert len(cmds) == 1
    c = cmds[0]
    assert c["verb"] == "launch" and c["tick"] == 60 and c["ok"] is True
    assert c["args"]["profile"] == "hi-lo"
    assert c["args"]["target_point"] == [0.0, 0.0, 200_000.0]
    assert c["args"]["weapon_id"] == "oniks"   # default filled in
    assert c["kind"] == "oniks"


def test_tap_records_denied_command_as_ok_false():
    """A refused world verb (launch_sam at a nonexistent track) records
    ok=False — the machine-readable denial the ledger exists for."""
    world, led, rec, tick = _tapped_world()
    m = world.launch_sam("no_such_track")
    assert m is None
    c = [r for r in led.records if r["rec"] == "cmd"][0]
    assert c["verb"] == "launch_sam" and c["ok"] is False
    assert c["args"]["aircraft_id"] == "no_such_track"
    assert c["args"]["round_id"] == "48n6"     # default filled in


def test_tap_preserves_world_behavior_byte_identically():
    """Tapped and untapped worlds evolve identically: recording is a pure
    observer (same seed, same commands, same ticks -> same state digest)."""
    plain = CombatWorld(CombatConfig(seed=99))
    tapped, led, rec, tick = _tapped_world(seed=99)
    for i in range(240):
        if i == 60:
            plain.launch("hi-lo", np.array([0.0, 0.0, 200_000.0]))
            tick["n"] = i
            tapped.launch("hi-lo", np.array([0.0, 0.0, 200_000.0]))
        plain.step(DT)
        tapped.step(DT)
        plain.drain_events()
        tapped.drain_events()
    assert state_digest(plain) == state_digest(tapped)


# ------------------------------------------------------------------ replay

def _scripted_battle(seed=1337, n_ticks=900, drop_second=False):
    """Run a short scripted battle through a tapped world, mirroring the
    live loop's ordering (commands before the tick's world.step, events
    drained after).  Returns (world, ledger)."""
    world, led, rec, tick = _tapped_world(seed=seed)
    led.header(CombatConfig(seed=seed), created="t", commit="t")
    for i in range(n_ticks):
        tick["n"] = i
        if i == 60:
            world.launch("hi-lo", np.array([0.0, 0.0, 200_000.0]))
        if i == 300 and not drop_second:
            world.launch("lo-lo", np.array([40_000.0, 0.0, 260_000.0]))
        world.step(DT)
        world.drain_events()
    return world, led


def test_replay_reproduces_recorded_battle_bit_for_bit():
    live, led = _scripted_battle()
    header = led.records[0]
    cmds = [r for r in led.records if r["rec"] in ("cmd", "toggle")]
    replayed = replay_battle(header["config"], cmds, n_ticks=900, dt=DT)
    assert state_digest(replayed) == state_digest(live)


def test_replay_detects_a_dropped_command():
    live, led = _scripted_battle()
    header = led.records[0]
    cmds = [r for r in led.records if r["rec"] == "cmd"]
    tampered = [c for c in cmds if c["tick"] != 300]   # drop the 2nd launch
    assert len(tampered) == len(cmds) - 1
    replayed = replay_battle(header["config"], tampered, n_ticks=900, dt=DT)
    assert state_digest(replayed) != state_digest(live)


def test_replay_applies_radar_toggle_records():
    """Toggle records (radar silence) replay through the same attribute the
    game layer flips — EMCON decisions change the battle and must survive
    the round trip."""
    world, led, rec, tick = _tapped_world(seed=5)
    led.header(CombatConfig(seed=5), created="t", commit="t")
    for i in range(600):
        tick["n"] = i
        if i == 120:
            world.radar_station.emitting = False
            rec.toggle(world, "radar", False)
        world.step(DT)
        world.drain_events()
    cmds = [r for r in led.records if r["rec"] in ("cmd", "toggle")]
    assert any(r["rec"] == "toggle" and r["name"] == "radar" for r in cmds)
    replayed = replay_battle(led.records[0]["config"], cmds,
                             n_ticks=600, dt=DT)
    assert state_digest(replayed) == state_digest(world)


def test_state_digest_is_deterministic_and_sensitive():
    a = CombatWorld(CombatConfig(seed=11))
    b = CombatWorld(CombatConfig(seed=11))
    assert state_digest(a) == state_digest(b)
    b.launch("hi-lo", np.array([0.0, 0.0, 200_000.0]))
    assert state_digest(a) != state_digest(b)


def test_recorder_emit_hash_writes_hash_record():
    world, led, rec, tick = _tapped_world()
    tick["n"] = 600
    rec.emit_hash(world)
    h = [r for r in led.records if r["rec"] == "hash"]
    assert len(h) == 1 and h[0]["tick"] == 600
    assert h[0]["digest"] == state_digest(world)


# -------------------------------------------------------------- bug report

def test_write_bug_report_bundles_ledger_and_context(tmp_path):
    led = BattleLedger(path=None)
    led.header(CombatConfig(seed=1337), created="2026-07-05T01:00:00Z",
               commit="abc1234")
    led.cmd(0.5, 60, "launch",
            {"profile": "hi-lo", "target_point": [0.0, 0.0, 200000.0],
             "waypoints": [], "weapon_id": "oniks"}, ok=True, kind="oniks")
    led.hint(12.0, "S-300: NO READY TUBE / TARGET LOST")
    led.mark(12.5, 1500, note="BUG")
    ctx = {"t": 12.5, "tick": 1500, "platform": "s300",
           "note": "fire refused on a solid track",
           "tracks": [{"id": "dd_00", "label": "SURF", "quality": "Q4"}]}
    report = write_bug_report(str(tmp_path), led, ctx)
    assert os.path.exists(report)
    text = open(report, encoding="utf-8").read()
    assert "BUG REPORT" in text
    assert "T+00:12" in text                   # sim-time stamp of the mark
    assert "SEED 1337" in text
    assert "S-300: NO READY TUBE / TARGET LOST" in text   # denial trail
    assert "fire refused on a solid track" in text
    # the raw data rides along for the machine reader
    folder = os.path.dirname(report)
    names = set(os.listdir(folder))
    assert "ledger.jsonl" in names
    assert "commands.json" in names
    cmds = json.load(open(os.path.join(folder, "commands.json"),
                          encoding="utf-8"))
    assert cmds and cmds[0]["verb"] == "launch"


def test_write_bug_report_numbers_folders(tmp_path):
    led = BattleLedger(path=None)
    led.header(None, created="", commit="")
    r1 = write_bug_report(str(tmp_path), led, {"t": 1.0, "tick": 120})
    r2 = write_bug_report(str(tmp_path), led, {"t": 2.0, "tick": 240})
    assert os.path.dirname(r1) != os.path.dirname(r2)


def test_write_bug_report_includes_note_and_tagged_ui(tmp_path):
    """v2 (2026-07-05): the report carries the player's TYPED note and the
    UI elements they click-tagged — each tag names the element, its pixel
    rect and its code site, so the reader lands in the right file."""
    led = BattleLedger(path=None)
    led.header(CombatConfig(seed=2), created="x", commit="y")
    ctx = {"t": 30.0, "tick": 3600,
           "note": "the weapon row shows ZIRCON but SPACE fired an ONIKS",
           "tags": [{"name": "hud.plate.bastion.body",
                     "rect": [16, 46, 316, 210],
                     "code": "game/hud.py:_block"}]}
    report = write_bug_report(str(tmp_path), led, ctx)
    text = open(report, encoding="utf-8").read()
    assert "the weapon row shows ZIRCON" in text
    assert "TAGGED UI" in text
    assert "hud.plate.bastion.body" in text
    assert "game/hud.py:_block" in text
