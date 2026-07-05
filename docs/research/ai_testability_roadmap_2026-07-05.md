# ONIKS — AI Testability Roadmap (brainstorm + research synthesis)

Date: 2026-07-05. Status: BRAINSTORM — nothing here is approved for build.
Question: how do we make the game future-proof so an AI agent (Claude) can find,
reproduce, and verify the bugs a human playtester sees, without a human playing?

Inputs: full codebase audit (sim/render coupling, determinism, telemetry, test
suite), plus two web-research sweeps — (A) industry practice in deterministic
sim testing (Factorio, OpenTTD, EA SEED, Ubisoft La Forge, DST/TigerBeetle),
(B) AI-agent-facing game interfaces (Gymnasium, Claude Plays Pokémon, Factorio
Learning Environment, TITAN commercial QA agent, MCP game servers).

---

## The core diagnosis

The reason Claude "can't see the bugs you see" is NOT that the game is untestable.
The audit found the foundations are unusually good for an 82k-LOC game:

- Sim runs fully headless: `App(hidden=True)`; tests step `world.step(DT)` with no GL.
- Fully deterministic: single seeded RNG chain, no wall-clock in sim, fixed 120 Hz
  dt, byte-identical reruns verified (`tools/probe_review2_determinism.py`).
- Truth vs sensor picture cleanly separated (`world.ships[i].pos` vs
  `world.contacts.tracks`) — fog-honest by construction.
- FlightRecorder + death-cause channel already record what flew and what killed it.

What is MISSING is three capabilities, in order of importance:

1. **Reproduce** — when you see a bug at minute 12 of a playtest, there is no
   artifact. No input-trace recording, no replay, no save/load. The moment is gone;
   Claude gets a prose description instead of the bug itself.
2. **Observe** — the sim emits events (`world.effects_out`) but they are drained
   for particles/audio and never persisted. There is no durable structured event
   log, and crucially NOTHING logs *denied* actions ("player pressed fire, launch
   refused, reason=X"). The exact class of bug you notice instantly ("it won't
   fire on that missile") is invisible in every artifact the game produces.
3. **Act** — Claude can construct a `CombatWorld` and step it, but cannot *play*:
   there is no command-level API ("select track 7, fire"), no valid-actions query,
   no fog-gated `player_view()`. So interaction-layer bugs (targeting, salvo
   queue, UI state machine) escape headless testing.

Research verdict on "the AI can't actually play the game": **partially wrong, in a
useful way.** An LLM can absolutely play a game — Claude Plays Pokémon, Voyager,
Factorio Learning Environment, and TITAN (deployed in 8 commercial QA pipelines,
found 4 previously unknown bugs in live MMORPGs) all prove it. But every
successful harness feeds the agent **structured state, not pixels** (BALROG found
vision often makes LLM agents *worse*), gives it a **valid-action list**, and
runs the game **faster than real time, headless**. So the goal is not "make
Claude watch the screen" — it is "give the game a programmatic player seat."

---

## Ranked: best to worst

Ranking = value for THIS codebase ÷ effort, with dependencies noted.
Effort scale: S (<1 day), M (1–3 days), L (week+).

### 1. Battle Ledger — persistent structured event log with DENIAL events (S)
The single cheapest, highest-value move. One JSONL file per battle
(`renders/../battles/<timestamp>_<seed>.jsonl` or similar):
- Header record: full `CombatConfig` (it's a frozen dataclass — trivially
  serializable), seed, git commit hash, sim version.
- Every `world.effects_out` event, stamped with sim tick — the plumbing already
  exists, it's currently thrown away after the render layer drains it.
- Kill-site records — the death-cause channel already stamps these.
- **Every denied/failed player action with a machine-readable reason**:
  `{"t": 141.2, "ev": "FIRE_DENIED", "platform": "s300", "target": "trk_17",
  "reason": "NO_ILLUMINATOR_CHANNEL"}`. Same for track drops, seeker no-locks,
  salvo-queue rejections.
- Invariant violations (see #4) go into the same stream.

Why first: it converts "silent wrongness" into greppable text. Your "couldn't
fire on a specific missile" bug becomes one `grep FIRE_DENIED` away from a root
cause, in a file you can paste to Claude — or Claude reads directly after any
headless run. Industry basis: telemetry-guideline literature ("log the action
AND the game's response, facts not inferences"), GameAnalytics error events,
Factorio's desync-report-as-artifact.

Design constraints: append-only, side-effect-free w.r.t. sim state (must not
perturb determinism), events full-fidelity but per-tick state sampled (the
FlightRecorder's 0.5 s boundary-sampling pattern is the model). The fog rules
don't apply to the ledger itself (it's a dev artifact, like the flight recorder's
"render/AAR layer only" contract) but each event should carry an
`observed` flag where relevant so fog-honest analysis remains possible.

### 2. Black Box — input-trace record/replay + bug-flag key (M)
Record every player command (not keystrokes — semantic commands: launch, target
select, waypoint, time-scale change) with its sim tick, alongside seed + config.
Always on, negligible cost. Add:
- A **"flag bug" key** during play: stamps a marker event into the ledger and
  snapshots "the last N minutes" pointer. You keep playing.
- A replay harness: `python tools/replay.py <battle.jsonl>` reconstructs
  `CombatWorld(config)` and re-feeds the commands at their recorded ticks,
  headless, bit-for-bit (determinism already guarantees this works).
- Per-N-tick state hash written into the ledger (Factorio's whole-map CRC
  pattern, OpenTTD's desync levels). Any future determinism regression becomes
  a CI failure at a named tick; replay divergence is detected, not assumed.

Why second: this is THE bridge between your eyes and Claude's. Your playtest
becomes a repro artifact. "I flagged a bug at 12:31" → Claude replays to that
tick, pauses, inspects every object, steps tick-by-tick through the failure.
It also unlocks time-travel debugging (re-run to tick T-500 and diverge with a
modified build). Industry basis: OpenTTD `commands-out.log` + autosave;
Factorio replay+CRC; TigerBeetle/FoundationDB deterministic-simulation-testing.

Dependency: needs a serializable Command object at the controls→sim boundary —
an audit of `game/controls.py`/`game/combat.py` to route all sim-mutating player
input through one choke point. That refactor is also what makes #5 cheap.

### 3. Scenario Forge — spawn helpers + run_until (M)
Today a test that needs "3 inbound Zircons at 40 km" steps the world for
thousands of ticks of enemy AI to maybe produce that situation. Add a small
test-facing builder API (a `tests/` or `sim/scenario.py` module):
- `spawn_inbound(world, kind="zircon", bearing=40, range_km=80, alt_m=15, n=3)`
- `set_battery(world, "s300", ammo=..., radar_emitting=...)`
- `run_until(world, cond, timeout_s)` where cond is a lambda on world state —
  plus canned conditions (`first_detection`, `first_leaker`, `battle_over`).

Why third: it makes every future targeted test ~10x cheaper to write, for you
AND for Claude. It also becomes the vocabulary of bug reports: "spawn X, run
until Y, observe Z" is a runnable sentence. This is the Gymnasium `reset(seed,
options)` idea without the RL baggage.

Caveat: injected spawns must go through the same code paths real spawns use
(otherwise tests validate a parallel world). Prefer thin wrappers around the
existing spawn machinery over hand-built objects.

### 4. Tick Oracles — invariant layer wired into the ledger (S–M, incremental)
A dev/test-mode check pass (every tick or every N ticks) asserting things that
must ALWAYS hold, violations logged to the ledger (and hard-fail under pytest):
- Physics: no NaN/Inf, nothing below terrain, speeds within per-airframe bands,
  energy monotonic where it should be, dead-stays-dead.
- Fog contracts: no sim decision reads truth (the no-cheat pattern, now
  machine-checked); ledger `observed` flags consistent with track store.
- Game rules: track count ≤ sensor capacity, ammo never negative, every
  launch consumed exactly one round, every fire denial carries a reason code.

Why fourth: oracles are what let unattended runs FAIL LOUDLY. Without them,
soak tests and replays only catch crashes; with them they catch wrongness.
Start with five checks and grow the list every time a playtest finds a bug —
each human-found bug should retire into an invariant. Industry basis: game
test-oracle taxonomies, aplib invariants, error-event telemetry.

### 5. Player Seat API — fog-gated observe/act interface (L)
The "Claude can actually play it" layer, shaped by every successful LLM-game
harness:
- `player_view(world) -> dict` — the SAME fog-gated picture the HUD consumes
  (tracks with quality/classification, battery states, salvo queue, alerts),
  as plain data. Pure function, no GL. This is the humble-object/view-model
  pattern; `game/hud.py` row generators are already 80% of the way there —
  this formalizes them into one queryable structure the HUD then renders.
- `valid_actions(world) -> list` — what can legally be done right now (which
  tracks are engageable by which platform, and if not, WHY not). The action
  mask is the single most load-bearing affordance in the literature
  (PettingZoo masks, TextWorld valid-action lists, TITAN action prioritization).
  Note: `valid_actions` reason codes and #1's `FIRE_DENIED` reasons must be the
  same enum — one vocabulary of denial.
- `apply_action(world, cmd)` — the same Command objects #2 records.
- Wrap in a tiny driver so a script (or Claude, or Hypothesis, or a soak bot)
  plays: `obs = view(); act = policy(obs); apply(act); step(n)`.

Why fifth despite being the headline feature: it's the biggest lift, and its
value compounds only once 1–4 exist (ledger to read, commands to route through,
scenarios to start from, oracles to catch what the playing agent misses —
TITAN's key lesson: the player-agent and the judge must be separate passes).
FLE's REPL finding applies directly: since Claude has process access via
pytest/scripts, NO network protocol, socket, or MCP server is needed — a plain
Python API is the whole interface.

### 6. Night Shift — seeded soak bot + statistical bands (M, after 4+5)
A deterministic random-but-legal policy (seeded — every failure replays) playing
hundreds of headless battles overnight across seeds and configs:
- Oracles from #4 are the tripwire; any violation dumps its ledger + replay.
- Aggregate stats per build: Pk per weapon pairing, leaker rate, CEP,
  time-to-first-detection distributions → compared against stored bands.
This operationalizes the "physics not dice / measured statistical bands"
doctrine: the bands become regression contracts. EA SEED / Ubisoft evidence
says scripted/random bots catch most crash+stuck+invalid-state bugs; RL is AAA
coverage amplification you don't need.

### 7. Golden Bands — summary-stat snapshot tests (S, medium maintenance)
Per canonical scenario, commit derived stats (Pk band, CEP, intercept timeline)
with calibrated tolerances — NOT raw trajectories (brittle, rot fast). Catches
silent balance drift (the Zircon-overfly class of bug). Keep the set small
(5–10 scenarios); regeneration is a reviewed, deliberate act, never a reflex.

### 8. Hypothesis stateful + metamorphic properties (M, narrower payoff)
`RuleBasedStateMachine` over the Scenario Forge + Player Seat: Hypothesis
generates action sequences, oracles are the invariants, and failures SHRINK to
a minimal runnable repro — a perfect artifact to hand Claude. Metamorphic
relations attack the no-ground-truth cases: translate the whole scenario →
identical trajectories; faster interceptor → never-later intercept; finer
timestep → bounded outcome delta. High quality-per-test but more design effort
per property; do after the infrastructure above.

### 9. Live debug port / MCP server into a running game (L, mostly redundant)
A socket/MCP interface Claude queries while YOU play live. Sounds ideal, but
research found no mature precedent for "drive a running game as player" MCPs
(the Godot/Unity MCPs are editor tools), and #2's replay makes it unnecessary:
anything Claude could ask live, it can ask the replay — with rewind. Revisit
only if a class of bug turns out to be untriggerable by replay (unlikely given
strict determinism).

### 10. Pixel-level testing / VLM screen-watching (avoid)
Screenshot-diff golden images, or a vision model watching gameplay. Worst
ratio: brittle to every visual tweak, expensive, and the literature is clear
that LLM agents do worse on pixels than structured state. Keep exactly what
exists (smoke-test screenshot for "did the renderer explode") and nothing more.
Render-correctness bugs stay human-eyes territory — cheap for you, hard for AI.

---

## The loop, once 1–5 exist

1. You playtest. Every command is recorded (#2), every event and denial is
   ledgered (#1). You see a bug and press the flag key. You keep playing.
2. You tell Claude "flagged a bug around 12:30, fire kept refusing."
3. Claude replays the battle headless to the flag, reads the ledger around it,
   finds `FIRE_DENIED reason=STALE_TRACK` firing 40 ticks after the track was
   visually solid, steps the sim tick-by-tick, finds the root cause.
4. Claude writes the regression test in Scenario Forge vocabulary (#3), fixes,
   re-replays your exact battle to prove the flag point now fires, adds an
   invariant (#4) so the class of bug can never return silently.
5. Night Shift (#6) soaks the fix across 500 seeds before you wake up.

Every human-found bug permanently upgrades the machine's ability to find the
next one. That is what "future-proof" means here.

## Suggested build order

- **Wave 1 (a weekend):** #1 ledger + #4 first five oracles. Immediate payoff
  on the very next playtest.
- **Wave 2:** #2 command choke-point + record/replay + state hash. The bridge.
- **Wave 3:** #3 forge + #7 golden bands for the canonical scenarios.
- **Wave 4:** #5 player seat + #6 night shift + #8 Hypothesis on top.

## Key sources

- Factorio FFF-47/60/62/188 (per-tick CRC, replay regression, desync forensics)
- OpenTTD debugging_desyncs.md (command log + autosave replay; 3 desync classes)
- TigerBeetle / Antithesis / FoundationDB — deterministic simulation testing
- EA SEED (arXiv 2103.15819, 2307.11105) + Ubisoft La Forge Client Bots (GDC) —
  bot soak testing; scripted bots suffice below AAA scale
- TITAN (arXiv 2509.22170) — LLM QA agent in 8 commercial pipelines; separate
  player-agent from oracle-judge
- Factorio Learning Environment (arXiv 2503.09617) — REPL-over-API beats
  keypress interfaces for LLM agents
- Claude Plays Pokémon starter + Anthropic managed-agents writeup — memory
  reader over pixels; durable session log outside the context window
- BALROG (arXiv 2411.13543) — structured text beats vision for LLM game agents
- Gymnasium/PettingZoo — reset/step/action-mask API conventions
- Hypothesis stateful testing docs — rule-based state machines, shrinking
- Fowler/xUnitPatterns Humble Object — view-model extraction for HUD testability
- Metamorphic testing: NIST hybrid-sim validation; oracle-problem survey (IEEE TSE)
