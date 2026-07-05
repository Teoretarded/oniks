"""BLACK BOX: the battle ledger, command recorder and bit-exact replay.

AI-testability build (2026-07-05, docs/research/ai_testability_roadmap):
this module is the machine-readable side of every battle — the artifact
that lets a coding agent SEE a playtest instead of being told about it.

Three pieces, all GL-free and side-effect-free w.r.t. the sim:

* :class:`BattleLedger` — an append-only structured event log.  One JSONL
  line per record (crash-safe: the file is complete up to the last event
  no matter how the process dies), or memory-only when ``path`` is None
  (headless tests / hidden tools).  Record kinds: ``header`` (config +
  seed + commit), ``cmd`` (a player world-verb call with RESOLVED args and
  its ok/denied outcome), ``hint`` (every HUD hint — the refusal/denial
  channel verbatim), ``evt`` (the world's drained effect events), ``toggle``
  (radar/jam attribute flips), ``hash`` (periodic state digest), ``loss``
  (a player round's close-out cause from the flight recorder), ``mark``
  (the player's BUG flag), ``end`` (battle outcome).

* :class:`CommandRecorder` — taps the PLAYER world verbs (launch,
  launch_sam, ...) on a live world instance so every sim-mutating command
  is recorded with fully-resolved args at its exact sim tick, no matter
  which UI path issued it (keyboard, map click, or a queued salvo beat).
  The tap is a pure observer: it calls the original verb unchanged and
  never touches sim state (the default-battle digest is byte-identical —
  gated by tools/wf_m5_digest.py).  No sim code calls these verbs
  internally (audited 2026-07-05), so wrapping them cannot change enemy
  behaviour.

* :func:`replay_battle` — rebuilds a CombatWorld from the recorded config
  and re-applies the command log at the recorded ticks.  DETERMINISM
  CONTRACT: the sim is fixed-timestep, single-seeded and wall-clock-free,
  so the replay is bit-identical to the live battle (verified by
  :func:`state_digest`); a divergence means a recording gap or a
  determinism regression — it must FAIL LOUDLY, never be absorbed.

The tick convention (LOCKED): ``tick`` counts COMPLETED world steps at the
moment a command executes — a command recorded at tick N ran after N
steps, before step N+1.  Replay applies every record with ``tick == n``
(in log order) immediately before stepping n -> n+1.  Ledger times ``t``
are SIM seconds (world.sim_time), never wall clock; wall time appears only
in the header's ``created`` field and in file NAMES.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
from dataclasses import asdict, is_dataclass

import numpy as np

SCHEMA_V = 1

# Periodic state-hash cadence (sim ticks): every 5 s at 120 Hz.  Frequent
# enough to bisect a divergence to a 5 s window, cheap enough to never
# show on the frame budget (the digest hashes ~10^2 entities).
HASH_EVERY_TICKS = 600


def git_commit(root: str = ".") -> str:
    """The working tree's short commit hash, by reading .git directly (no
    subprocess on the render thread).  Best-effort: '' when unreadable —
    the ledger header states facts or nothing."""
    try:
        head_path = os.path.join(root, ".git", "HEAD")
        with open(head_path, encoding="utf-8") as f:
            head = f.read().strip()
        if head.startswith("ref:"):
            ref = head.split(None, 1)[1]
            with open(os.path.join(root, ".git", *ref.split("/")),
                      encoding="utf-8") as f:
                return f.read().strip()[:7]
        return head[:7]
    except OSError:
        return ""

# Player verbs the recorder taps, with their positional-arg names and
# defaults (mirrors the world signatures — world/combat.py).  Recording
# fills defaults in so a replayer never needs the signatures again.
VERB_ARGS: dict = {
    "launch": (("profile", "target_point", "waypoints", "weapon_id"),
               {"waypoints": (), "weapon_id": "oniks"}),
    "launch_sam": (("aircraft_id", "round_id"), {"round_id": "48n6"}),
    "launch_buk": (("aircraft_id", "round_id"), {"round_id": "9m317"}),
    "launch_arm": (("emitter_id",), {}),
    "launch_swarm": (("profile", "aim_point", "waypoints", "sync"),
                     {"waypoints": (), "sync": True}),
    "launch_asw": (("track_id",), {"track_id": None}),
    "place_sonobuoy": (("xz",), {}),
}


def _jsonable(x):
    """Coerce numpy scalars/arrays (and nested tuples) to plain JSON types.
    Floats keep full repr precision — the ledger states facts 1:1, exactly
    like the flight recorder's accuracy contract."""
    if isinstance(x, np.ndarray):
        return [_jsonable(v) for v in x.tolist()]
    if isinstance(x, (np.floating,)):
        return float(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    return x


class BattleLedger:
    """Append-only structured battle log (see module docstring).

    ``path`` None -> memory only (``records``); else every record is also
    written as one JSON line, flushed immediately (black-box property)."""

    def __init__(self, path: str | None = None):
        self.path = path
        self.records: list[dict] = []
        self._fh = None

    # ------------------------------------------------------------ plumbing

    def _write(self, rec: dict) -> None:
        self.records.append(rec)
        if self.path is None:
            return
        if self._fh is None:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            self._fh = open(self.path, "a", encoding="utf-8")
        try:
            self._fh.write(json.dumps(rec) + "\n")
            self._fh.flush()
        except OSError:
            pass                            # read-only disk: play on

    def close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None

    # ------------------------------------------------------------- records

    def header(self, config, *, created: str = "", commit: str = "") -> None:
        """The battle's identity: full config (a frozen dataclass — the
        exact reconstruction recipe), seed, schema version.  ``created`` /
        ``commit`` are caller-supplied context (wall time lives ONLY here)."""
        cfg = asdict(config) if is_dataclass(config) else (config or {})
        self._write({"rec": "header", "v": SCHEMA_V,
                     "seed": int(cfg.get("seed", 0) or 0),
                     "created": created, "commit": commit, "config": cfg})

    def cmd(self, t: float, tick: int, verb: str, args: dict, *,
            ok: bool, kind: str = "") -> None:
        self._write({"rec": "cmd", "t": float(t), "tick": int(tick),
                     "verb": verb, "args": _jsonable(args), "ok": bool(ok),
                     "kind": kind})

    def toggle(self, t: float, tick: int, name: str, value) -> None:
        self._write({"rec": "toggle", "t": float(t), "tick": int(tick),
                     "name": name, "value": _jsonable(value)})

    def hint(self, t: float, text: str) -> None:
        self._write({"rec": "hint", "t": float(t), "text": str(text)})

    def evt(self, t: float, kind: str, pos) -> None:
        self._write({"rec": "evt", "t": float(t), "kind": str(kind),
                     "pos": _jsonable(pos)})

    def hash(self, t: float, tick: int, digest: str) -> None:
        self._write({"rec": "hash", "t": float(t), "tick": int(tick),
                     "digest": digest})

    def loss(self, t: float, **fields) -> None:
        rec = {"rec": "loss", "t": float(t)}
        rec.update(_jsonable(fields))
        self._write(rec)

    def mark(self, t: float, tick: int, note: str = "BUG") -> None:
        self._write({"rec": "mark", "t": float(t), "tick": int(tick),
                     "note": str(note)})

    def end(self, t: float, outcome: str, grade: str = "") -> None:
        self._write({"rec": "end", "t": float(t), "outcome": outcome,
                     "grade": grade})

    # -------------------------------------------------------------- reads

    def tail(self, n: int) -> list[dict]:
        """The last ``n`` records (bug-report context)."""
        return self.records[-n:]

    def commands(self) -> list[dict]:
        """The replayable records (cmd + toggle), in log order."""
        return [r for r in self.records if r["rec"] in ("cmd", "toggle")]


def load_ledger(path: str) -> tuple[dict, list[dict]]:
    """Read a ledger JSONL back: (header, all records).  Unparseable lines
    are skipped (a crash can truncate the final line — the black box is
    honest up to that point)."""
    records: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except ValueError:
                continue
    header = next((r for r in records if r.get("rec") == "header"), {})
    return header, records


# ---------------------------------------------------------------- recorder

class CommandRecorder:
    """Taps the player world verbs on a live world so every sim-mutating
    command is ledgered with resolved args at its sim tick (see module
    docstring for the tick convention)."""

    def __init__(self, ledger: BattleLedger, tick_fn):
        self.ledger = ledger
        self.tick_fn = tick_fn

    def tap(self, world) -> None:
        """Wrap every player verb the world exposes.  The wrapper is a pure
        observer bound as an instance attribute — sim internals never call
        these verbs, so enemy behaviour is untouched."""
        for verb in VERB_ARGS:
            original = getattr(world, verb, None)
            if original is None:
                continue
            setattr(world, verb, self._wrap(world, verb, original))

    def _wrap(self, world, verb: str, original):
        names, defaults = VERB_ARGS[verb]

        def recorded(*args, **kwargs):
            resolved = dict(defaults)
            resolved.update(zip(names, args))
            resolved.update(kwargs)
            result = original(*args, **kwargs)
            ok = bool(result) if isinstance(result, list) \
                else result is not None
            if verb == "launch":
                kind = str(resolved.get("weapon_id", "oniks"))
            else:
                kind = verb.replace("launch_", "").replace("place_", "")
            self.ledger.cmd(float(getattr(world, "sim_time", 0.0)),
                            int(self.tick_fn()), verb, resolved,
                            ok=ok, kind=kind)
            return result

        return recorded

    def toggle(self, world, name: str, value) -> None:
        """Record an attribute-flip command (radar emissions / drone jam)
        AFTER the game layer applied it."""
        self.ledger.toggle(float(getattr(world, "sim_time", 0.0)),
                           int(self.tick_fn()), name, value)

    def emit_hash(self, world) -> None:
        """Periodic determinism tripwire: ledger the current state digest
        (Factorio's CRC-per-interval pattern).  Replay verifies these."""
        self.ledger.hash(float(getattr(world, "sim_time", 0.0)),
                         int(self.tick_fn()), state_digest(world))


# ------------------------------------------------------------------ replay

def state_digest(world) -> str:
    """SHA-256 over the world's dynamic state (ship positions/state/ammo,
    missile positions/velocities/liveness, clock).  Same hashing family as
    tools/wf_m5_digest.py; excludes the un-drained event list so live play
    (which drains per tick) and replay hash identically."""
    h = hashlib.sha256()

    def f(x):
        h.update(struct.pack("<d", float(x)))

    f(getattr(world, "sim_time", 0.0))
    for s in getattr(world, "ships", ()):
        for c in s.pos:
            f(c)
        h.update(struct.pack("<i", int(s.state)))
        h.update(struct.pack("<i", int(getattr(s, "sm2_ammo", 0))))
        h.update(struct.pack("<i", int(getattr(s, "sm6_ammo", 0))))
        h.update(struct.pack("<i", int(getattr(s, "tomahawk_ammo", 0))))
    for m in getattr(world, "missiles", ()):
        for c in m.pos:
            f(c)
        for c in m.vel:
            f(c)
        h.update(b"\x01" if m.alive else b"\x00")
    h.update(struct.pack("<i", len(getattr(world, "missiles", ()))))
    return h.hexdigest()


def _apply_record(world, rec: dict) -> None:
    """Re-issue one recorded command against a replay world."""
    if rec["rec"] == "toggle":
        if rec["name"] == "radar":
            radar = getattr(world, "radar_station", None)
            if radar is not None:
                radar.emitting = bool(rec["value"])
        elif rec["name"] == "jam":
            drone = getattr(world, "drone", None)
            if drone is not None and drone.alive:
                drone.set_jam(bool(rec["value"]))
        return
    verb = rec["verb"]
    fn = getattr(world, verb, None)
    if fn is None:
        return
    args = dict(rec["args"])
    # JSON round-trip turned tuples into lists; the world verbs coerce with
    # np.asarray, so lists pass through — only waypoints wants tuples of
    # pairs for indexing symmetry with live play.
    if "waypoints" in args:
        args["waypoints"] = tuple(tuple(w) for w in args["waypoints"])
    if "xz" in args:
        args["xz"] = tuple(args["xz"])
    fn(**args)


def replay_battle(config, commands: list[dict], n_ticks: int,
                  dt: float = 1.0 / 120.0, drain: bool = True):
    """Rebuild the battle from its recording: construct a CombatWorld from
    ``config`` (a CombatConfig or the header's config dict), apply every
    command at its recorded tick, step ``n_ticks`` fixed steps.  Returns
    the replayed world (compare with :func:`state_digest`, inspect
    anything).  ``drain`` mirrors the live loop's per-tick event drain."""
    from world.combat import CombatWorld
    from world.combat_config import CombatConfig
    if isinstance(config, dict):
        config = CombatConfig(**config)
    world = CombatWorld(config)
    by_tick: dict[int, list[dict]] = {}
    for rec in commands:
        by_tick.setdefault(int(rec["tick"]), []).append(rec)
    for t in range(int(n_ticks)):
        for rec in by_tick.get(t, ()):
            _apply_record(world, rec)
        world.step(dt)
        if drain:
            world.drain_events()
    return world


# -------------------------------------------------------------- bug report

def _fmt_t(t: float) -> str:
    """Sim seconds -> the ledger sheet's T+MM:SS stamp."""
    t = max(0.0, float(t))
    return f"T+{int(t // 60):02d}:{int(t % 60):02d}"


def write_bug_report(base_dir: str, ledger: BattleLedger,
                     context: dict) -> str:
    """Bundle a numbered bug-report folder: report.md (typed, ledger-style,
    stating only recorded facts) + ledger.jsonl + commands.json.  Returns
    the report.md path.  ``context`` carries game-layer facts the caller
    already knows (t, tick, platform, note, tracks, screenshot name...)."""
    os.makedirs(base_dir, exist_ok=True)
    n = 1
    while os.path.exists(os.path.join(base_dir, f"bug_{n:03d}")):
        n += 1
    folder = os.path.join(base_dir, f"bug_{n:03d}")
    os.makedirs(folder)

    header = next((r for r in ledger.records if r["rec"] == "header"), {})
    t = float(context.get("t", 0.0))
    tick = int(context.get("tick", 0))
    hints = [r for r in ledger.records if r["rec"] == "hint"][-12:]
    cmds = ledger.commands()[-12:]
    tail = ledger.tail(40)

    lines = [
        "BUG REPORT - FIELD LEDGER SHEET",
        "=" * 60,
        f"{_fmt_t(t)}  TICK {tick}  SEED {header.get('seed', 0)}  "
        f"COMMIT {header.get('commit', '') or '---'}",
        f"FILED {header.get('created', '') or '---'}  "
        f"SCHEMA v{header.get('v', SCHEMA_V)}",
        "",
        "OPERATOR NOTE",
        "-" * 60,
        str(context.get("note", "") or "(none given - see the mark)"),
        "",
    ]
    if context.get("platform"):
        lines += [f"ACTIVE PLATFORM: {context['platform']}", ""]
    if context.get("selection"):
        lines += [f"SELECTION: {context['selection']}", ""]
    if context.get("tracks"):
        lines += ["PLAYER PICTURE AT THE MARK (fog-honest, sensor tracks "
                  "only)", "-" * 60]
        for trk in context["tracks"][:16]:
            lines.append("  " + "  ".join(f"{k}={v}"
                                          for k, v in trk.items()))
        lines.append("")
    lines += ["LAST COMMANDS (resolved args, ok=fired / DENIED)",
              "-" * 60]
    for c in cmds:
        if c["rec"] == "toggle":
            lines.append(f"  {_fmt_t(c['t'])}  TOGGLE {c['name']} -> "
                         f"{c['value']}")
        else:
            state = "ok" if c.get("ok") else "DENIED"
            lines.append(f"  {_fmt_t(c['t'])}  {c['verb']} "
                         f"{json.dumps(c['args'])}  [{state}]")
    if not cmds:
        lines.append("  (none)")
    lines += ["", "LAST HINTS (the refusal/denial channel, verbatim)",
              "-" * 60]
    for hrec in hints:
        lines.append(f"  {_fmt_t(hrec['t'])}  {hrec['text']}")
    if not hints:
        lines.append("  (none)")
    lines += ["", "LAST 40 LEDGER RECORDS", "-" * 60]
    for r in tail:
        lines.append("  " + json.dumps(r))
    if context.get("screenshot"):
        lines += ["", f"SCREENSHOT: {context['screenshot']}"]
    lines += [
        "",
        "REPRO",
        "-" * 60,
        "  python tools/replay_battle.py <this folder>/ledger.jsonl "
        f"--to-tick {tick}",
        "  (bit-exact: fixed 120 Hz steps, seeded RNG, no wall clock)",
        "",
    ]
    report = os.path.join(folder, "report.md")
    with open(report, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    with open(os.path.join(folder, "ledger.jsonl"), "w",
              encoding="utf-8") as f:
        for r in ledger.records:
            f.write(json.dumps(r) + "\n")
    with open(os.path.join(folder, "commands.json"), "w",
              encoding="utf-8") as f:
        json.dump(ledger.commands(), f, indent=1)
    return report
