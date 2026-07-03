# Sensor Classification & Track Quality — design spec (2026-07-03)

User directive: "you don't know if it's an SM-6 — you know its bearing, its
distance, and its speed, but you don't know anything else about it" + Proto 04
(Q-ladder) approved for implementation.

## 1. How the sensors work TODAY (audit, code-verified)

**Detection is honest physics — no truth leak:**
- `sim/radar.py Radar.detects`: alive+emitting gate → per-SIZE-CLASS max range
  (`ship`/`fighter`/`missile`/`stealth` — a coarse RCS-class model, per radar)
  → 4/3-earth radar horizon (`radar_horizon_m`) → terrain line-of-sight
  sampling (fine steps close-in). EW burn-through shrinks range under jamming.
- `sim/contacts.py ContactBoard`: a track only FORMS after 2.0 s of
  CONTINUOUS visibility (`DETECT_DELAY_S`); refresh is periodic and
  range-banded (stale between fixes → dead-reckoned estimate); unseen tracks
  coast and DROP at 90 s. An undetected entity has no track and never appears
  on any player surface.
- So: **the radar does not cheat on detection.** There is no beam-scan/RCS
  return simulation (functional model by spec), but nothing is known that the
  physics gates did not earn.

**Identification IS free today (the cheat the user smelled):**
- The instant a track forms it is stamped `kind=_kind_of(ent)` (the actual
  weapon_id — "sm6", "tomahawk") and the HUD prints `SM6 - BRG 330` on the
  first frame. Real-world type recognition (NCTR) is a separate, slower
  process from detection.
- The intel panel's ID field (IDENTIFIED/CLASSIFIED/UNKNOWN) is keyed to
  STALENESS (age since last fix) — semantically backwards: a brand-new track
  reads IDENTIFIED instantly.

## 2. Real-world grounding (research)

- Recognition doctrine splits into **cooperative ID (IFF)** — friendlies
  squawk, instant — and **non-cooperative target recognition (NCTR)** for
  unknown/hostile: coarse CLASS from kinematics first, then TYPE from
  signature techniques (HRR profiles, ISAR, jet-engine modulation) that need
  dwell/aspect — i.e. **class comes in seconds, type takes longer**.
  Sources: DTIC ADA358528 (Non-Cooperative Air Target Identification Using
  Radar); IET "Radar ATR and NCTR"; NATO STO ATR/NCTR reports; arXiv
  2211.10038 (detection→tracking→classification survey).
- NEBULOUS: Fleet Command ships the same idea as a track-quality ladder
  (TQ15..TQ1) and it is instantly legible to players.

## 3. The design (fog-honest, digest-safe, physics-not-dice)

### 3.1 Classification ladder (per hostile track)
Dwell = `sim_time - track["first_seen"]` (new stamp at track creation).

| Stage | Reveal | Basis |
|---|---|---|
| `UNKNOWN` (dwell < T_class) | bearing / range / speed / closing only — label `UNK` | pos+vel are honestly measured; type is not |
| `CLASSIFIED` (T_class ≤ dwell < T_ident) | size class: `MSL` / `AIR` / `SURF` | coarse kinematic classification |
| `IDENTIFIED` (dwell ≥ T_ident) | the type: `SM-6`, `TOMAHAWK`, ... | NCTR fine recognition earned by dwell |

Per-signature dwell constants (tuning scaffold; named constants, two-sided
regression tests):
- `missile`: T_class 2 s, T_ident 6 s (fast kinematics self-classify quickly)
- `fighter`: T_class 3 s, T_ident 10 s
- `ship`:    T_class 5 s, T_ident 20 s
- IFF: tracks whose `kind` is an OWN weapon id bypass the ladder entirely
  (cooperative ID — you always know your own rounds). The threat strip's
  HOSTILE_KINDS filter already implements IFF-negative screening.

### 3.2 Track quality ladder Q5..Q1 (Proto 04)
Pure banding of the EXISTING staleness age (Q5 fresh paint → Q1 about to
drop): Q5 < 2 s, Q4 < 10 s, Q3 < 30 s, Q2 < 60 s, else Q1 (drop at 90 s).
Displayed as a 5-bar chip (intel panel), and later as map ring treatment.
Multi-sensor weighting (count of radars holding the track) is a follow-up —
needs a `RadarNetwork.visible` count variant; v1 stays derived-only.

### 3.3 Where it lives
- `sim/contacts.py`: `first_seen` stamp (1 line) + pure `classify(track,
  sim_time)` + `track_quality(track)` helpers (GL-free, unit-tested).
- Consumers gate DISPLAY only: threat cards (UNK label until earned), intel
  panel (CLASS/ID/TYPE rows re-keyed to the ladder; staleness keeps driving
  CONF + the new Q chip), map intel. Enemy AI untouched (its own picture).
- "NEW INBOUND CONTACT" hint_flash on first UNKNOWN hostile air track.

### 3.4 Contracts
- **Digest**: tools/wf_m5_digest.py hashes ships/missiles/events only — the
  contact board is not hashed; `first_seen` feeds no sim decision. Digest
  must stay `7d5716...06add` (gate every commit).
- **Fog LAW**: this REMOVES free knowledge; nothing new is revealed.
- **No weakened tests**: intel-panel tests re-keyed honestly to the new
  semantics (the old age-keyed ID was the bug being fixed).

### 3.5 Follow-ups (not v1)
- ELINT cross-cue: an emitter fix co-located with a track jumps it to
  IDENTIFIED (the emission names the radar → the platform).
- Per-ship-class radar signatures (DDG vs CV vs transport detection ranges)
  — extends the existing size-class table.
- Acoustic classification bands for sub contacts (quality P% already exists).
- Multi-sensor Q weighting; launch-transient "SOMETHING LAUNCHED" ELINT cue.
