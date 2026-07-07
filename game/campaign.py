"""CAMPAIGN (M6) — chain of seeded battles with carried-forward attrition.

Pure, GL-free, JSON-persistable.  Wraps the single-battle CombatConfig flow into
a chain of N battles.  Between battles: the player's offensive magazines CARRY
FORWARD (the finite-magazine economy becomes a campaign resource), a SCARCE
resupply tranche (scaled by the battle grade) tops the ledger back up, and the
enemy ESCALATES via the EXISTING CombatConfig counts.  v1 carries AMMO ONLY;
base-damage persistence is deferred to the campaign-loop pass (it needs an
on_destroyed-aware ingest + defeat-ends-campaign semantics — see world_snapshot).

NON-NEGOTIABLES honoured here:
  * LOCKED SCHEMA — campaign adds NO new frozen CombatConfig field.  Per-battle
    state rides a SEPARATE carrier (this CampaignState + the world's optional
    ``initial_state`` ingest).  Every per-battle config goes through
    ``clamp_config`` so escalation can never exceed the spawnable ceiling.
  * DETERMINISM — each battle re-seeds via ``derive_seed(base_seed, battle_idx)``
    passed as ``config.seed``.  This leaves every existing ``[seed, tag]`` sim
    child stream UNTOUCHED (no new tag dimension); ``battle_idx == 0`` with the
    base seed reproduces today's single battle exactly.  ``derive_seed`` uses a
    standalone Generator (campaign-setup time), never a sim stream.

The hub SCREEN (game/campaign_screen.py), the menu wiring, and the end-overlay
"NEXT BATTLE" affordance are the deferred UI-wiring pass; THIS module is the
headless-testable core (state, seeding, escalation, resupply, snapshot, persist).
"""

from __future__ import annotations

import dataclasses
import json
import os
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from world.combat_config import CombatConfig, clamp_config

# Standalone seed-derivation salt — NOT a sim child-stream tag (sim tags 3-16 are
# taken).  derive_seed builds a fresh SeedSequence at campaign-setup time to pick
# each battle's BASE seed (passed as config.seed); the sim's own [seed, tag]
# streams are untouched, so battle_idx 0 reproduces today's single battle.
_DERIVE_SALT: int = 90001

DEFAULT_N_BATTLES: int = 6

# Resupply fraction of each weapon's capacity granted between battles, by grade.
# A clean win (S) rearms most; a bad result (D) barely tops up — the risk/reward
# loop: empty your magazine to win battle N and you enter N+1 lean.
_RESUPPLY_BY_GRADE: dict = {"S": 0.60, "A": 0.45, "B": 0.30, "C": 0.20, "D": 0.10}

# The offensive magazines that carry forward, mapped to (live world attribute,
# CombatConfig capacity field).  These are WORLD-LEVEL scalar pools (one int
# each) so the snapshot + ingest are trivial and deterministic.  Per-unit
# point-defense (Pantsir) + the OFF-by-default exotic pools (Buk/swarm) rearm
# fresh each battle in v1 — a documented simplification, not a fog/determinism
# concern (carrying a per-unit count across a changing unit count is fiddly and
# the offensive economy is what makes the attrition loop bite).
WEAPONS: dict = {
    "oniks":     ("_oniks_ammo",   "oniks_ammo"),
    "zircon":    ("_zircon_ammo",  "zircon_ammo"),
    "asbm":      ("_asbm_ammo",    "asbm_ammo"),
    "kh31p":     ("_kh31p_ammo",   "kh31p_ammo"),
    "s300_48n6": ("sam_ammo",      "s300_48n6_ammo"),
    "s300_40n6": ("sam_ammo_40n6", "s300_40n6_ammo"),
}


# --------------------------------------------------------------- state

@dataclass
class CampaignState:
    """The persistent across-battles carrier (NOT a frozen config)."""
    seed: int
    n_battles: int = DEFAULT_N_BATTLES
    battle_idx: int = 0
    ledger: dict = field(default_factory=dict)        # weapon -> rounds left
    base_damage: dict = field(default_factory=dict)   # structure_id -> hp
    grades: list = field(default_factory=list)        # letter per finished battle

    @property
    def complete(self) -> bool:
        return self.battle_idx >= self.n_battles


def new_campaign(seed: int, n_battles: int = DEFAULT_N_BATTLES) -> CampaignState:
    """A fresh campaign at battle 0 with an EMPTY ledger.  Battle 0 arms from its
    config caps via the normal ``_arm_magazines`` path (``initial_state`` is None
    for the first battle); carry-forward begins at battle 1."""
    return CampaignState(seed=int(seed), n_battles=int(n_battles))


# --------------------------------------------------------------- seeding

def derive_seed(base_seed: int, battle_idx: int) -> int:
    """Deterministic, distinct per-battle base seed.

    Standalone (NOT a sim child stream): a fresh Generator seeded by
    ``(base_seed, salt, battle_idx)`` yields a reproducible 31-bit seed used as
    the next battle's ``config.seed``.  Same (base_seed, battle_idx) -> same
    result, every run; distinct battle_idx -> (with overwhelming probability)
    distinct seeds, so each battle's whole sim is a fresh deterministic draw."""
    rng = np.random.default_rng([int(base_seed), _DERIVE_SALT, int(battle_idx)])
    return int(rng.integers(1, 2 ** 31 - 1))


# --------------------------------------------------------------- escalation

def _escalated_counts(base: CombatConfig, battle_idx: int) -> dict:
    """Monotonic enemy escalation by battle index, built on the EXISTING base
    counts.  ``clamp_config`` bounds every value downstream, so escalation can
    never exceed the spawnable ceiling.  battle_idx 0 -> base counts unchanged.

    The curve stages the M5 threat AXES, not just more of the same hull —
    each battle band introduces a new doctrinal problem (all playable/
    counterable through the setup-screen features, all += on the base so a
    player-configured loadout escalates FROM its own numbers):
      b>=1  screen thickens (destroyers, then AAW hulls every 2nd battle)
      b>=2  a CEC flagship datalink hub joins the group
      b>=2  submarines (the acoustic axis; counter = sonobuoys + ASW)
      b>=3  escort jammers (the EW axis) + ground-attack hulls
      b>=4  amphibious transports (the TIMED beachhead lose-path)
    """
    b = int(battle_idx)
    subs = int(base.n_subs) + (b // 2 if b >= 2 else 0)
    counts = {
        "n_destroyers":   int(base.n_destroyers) + b,
        "n_enemy_radars": int(base.n_enemy_radars) + b // 2,
        "n_awacs":        int(base.n_awacs) + b // 3,
        "n_aaw":          int(base.n_aaw) + b // 2,
        "n_flagship":     max(int(base.n_flagship), 1 if b >= 2 else 0),
        "n_subs":         subs,
        "n_jammers":      int(base.n_jammers) + (b // 3),
        "n_ground_attack": int(base.n_ground_attack) + b // 3,
        "n_transports":   (int(base.n_transports) + 1 + (b - 4) // 3
                           if b >= 4 else int(base.n_transports)),
    }
    # FAIRNESS: the acoustic axis only escalates WITH its counter — a sub
    # battle with zero buoys/ASW is an uncounterable lose-path.  The kit
    # arrives as campaign reinforcements (never below the player's own base
    # loadout; fresh each battle, not part of the carry ledger).
    if subs > 0:
        counts["n_sonobuoys"] = max(int(base.n_sonobuoys), 8 * subs)
        counts["asw_ammo"] = max(int(base.asw_ammo), 2 * subs)
    return counts


def next_config(campaign: CampaignState,
                base_config: Optional[CombatConfig] = None) -> CombatConfig:
    """The CombatConfig for the campaign's CURRENT battle.

    Starts from the base config (preserving the player's loadout caps + map),
    keeps battle 0 on the selected seed, re-seeds later battles via
    :func:`derive_seed`, escalates the enemy counts, and runs the whole thing
    through ``clamp_config`` (NEVER a hand-built frozen config that bypasses the
    legal ranges)."""
    base = base_config or CombatConfig(seed=campaign.seed)
    fields = dataclasses.asdict(base)
    fields.update(_escalated_counts(base, campaign.battle_idx))
    fields["seed"] = (int(base.seed) if campaign.battle_idx == 0
                      else derive_seed(campaign.seed, campaign.battle_idx))
    # 2026-07-06 damage revamp: campaign battles play the subsystem model.
    fields["damage_model"] = "subsystem"
    # R-P0 2026-07-07: campaign battles play scanned radars.
    fields["radar_model"] = "scanned"
    return clamp_config(**fields)


# --------------------------------------------------------------- snapshot

def world_snapshot(world) -> dict:
    """Capture the END-STATE offensive ledger from a live world (duck-typed: any
    object exposing the WEAPONS attrs).

    v1 carries AMMO ONLY: base-damage persistence is DEFERRED to the campaign-loop
    pass, where it needs an on_destroyed-aware ingest (a carried-dead radar must
    fire its kill closure, not merely flip a flag — else the live radar/Pantsir
    desyncs) and defeat-ends-campaign semantics (a destroyed bastion = you LOST the
    campaign, not a pre-defeated next battle).  Carrying it naively desynced the
    sensor + started the next battle already defeated (critique F2/F16/F19), so
    base_damage stays empty until that pass.  A ``None`` pool (SANDBOX infinite
    Oniks) reads as 0, but campaigns only ever run real CombatWorlds (int pools)."""
    ledger: dict = {}
    for weapon, (attr, _cap) in WEAPONS.items():
        v = getattr(world, attr, None)
        ledger[weapon] = int(v) if v is not None else 0
    return {"ledger": ledger, "base_damage": {}}


def initial_state_for(campaign: CampaignState) -> Optional[dict]:
    """Build the ``initial_state`` dict the next battle's CombatWorld ingests
    (applied AFTER ``_arm_magazines``), keyed by the LIVE world attribute names
    so the world ingest is a flat setattr.  Returns ``None`` for a fresh battle 0
    with no carry-forward (so the default arming path is byte-identical).  v1
    carries AMMO ONLY (see world_snapshot)."""
    if not campaign.ledger:
        return None
    st: dict = {}
    for weapon, (attr, _cap) in WEAPONS.items():
        if weapon in campaign.ledger:
            st[attr] = int(campaign.ledger[weapon])
    return st or None


# --------------------------------------------------------------- resupply

def apply_resupply(campaign: CampaignState, grade: str,
                   base_config: Optional[CombatConfig] = None) -> None:
    """Top the ledger up by a grade-scaled fraction of each weapon's CAPACITY,
    capped at capacity.  Mutates ``campaign.ledger`` in place.  Deterministic
    (no rng): the same ledger + grade + caps yields the same result."""
    base = base_config or CombatConfig(seed=campaign.seed)
    frac = _RESUPPLY_BY_GRADE.get(grade, _RESUPPLY_BY_GRADE["D"])
    for weapon, (_attr, cap_field) in WEAPONS.items():
        cap = int(getattr(base, cap_field))
        # A key missing from the ledger reads as EMPTY (0), never as a free
        # full magazine — a hand-edited / older save with a dropped key must
        # not out-earn a played battle.
        cur = int(campaign.ledger.get(weapon, 0))
        grant = int(round(cap * frac))
        campaign.ledger[weapon] = max(0, min(cap, cur + grant))


def advance(campaign: CampaignState, world, grade: str,
            base_config: Optional[CombatConfig] = None) -> None:
    """Transition AFTER a finished battle: snapshot the end-state ledger + base
    damage off the world, record the grade, apply the grade-scaled resupply, and
    step to the next battle.  After this, ``next_config`` + ``initial_state_for``
    describe the upcoming battle."""
    snap = world_snapshot(world)
    campaign.ledger = snap["ledger"]
    campaign.base_damage = snap["base_damage"]
    campaign.grades.append(str(grade))
    if bool(getattr(world, "defeated", False)):
        campaign.battle_idx = campaign.n_battles
        return
    apply_resupply(campaign, grade, base_config)
    campaign.battle_idx += 1


# --------------------------------------------------------------- persistence

def default_save_path() -> str:
    """%APPDATA%/ONIKS/campaign.json (mirrors the keybinds settings_path
    pattern); falls back to the cwd if APPDATA is unset (non-Windows/tests)."""
    base = os.environ.get("APPDATA") or os.getcwd()
    return os.path.join(base, "ONIKS", "campaign.json")


def save(campaign: CampaignState, path: Optional[str] = None) -> str:
    """Write the campaign to JSON; returns the path written."""
    path = path or default_save_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(dataclasses.asdict(campaign), fh, indent=2, sort_keys=True)
    return path


def load(path: Optional[str] = None) -> Optional[CampaignState]:
    """Load a campaign from JSON; returns None if the file is absent."""
    path = path or default_save_path()
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return CampaignState(
        seed=int(data["seed"]),
        n_battles=int(data.get("n_battles", DEFAULT_N_BATTLES)),
        battle_idx=int(data.get("battle_idx", 0)),
        ledger={str(k): int(v) for k, v in data.get("ledger", {}).items()},
        base_damage={str(k): float(v) for k, v in data.get("base_damage", {}).items()},
        grades=list(data.get("grades", [])),
    )
