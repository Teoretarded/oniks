"""M6 CAMPAIGN — headless tests for the pure core + the world carry-forward
ingest.  Covers: deterministic per-battle seeding, clamped/monotonic escalation,
JSON round-trip, grade-scaled resupply (capped), end-state snapshot, and the
ammo + base-damage carry-forward via CombatWorld.apply_initial_state (with the
None path proving the default battle is untouched)."""

from game.campaign import (
    CampaignState, new_campaign, derive_seed, next_config, world_snapshot,
    initial_state_for, apply_resupply, advance, save, load, WEAPONS,
    DEFAULT_N_BATTLES,
)
from world.combat_config import (
    CombatConfig, CLAMP_DESTROYERS, CLAMP_ENEMY_RADARS, CLAMP_AWACS,
)
from world.combat import CombatWorld


# --------------------------------------------------------------- seeding

def test_derive_seed_deterministic_and_distinct():
    assert derive_seed(1337, 0) == derive_seed(1337, 0)      # reproducible
    assert derive_seed(1337, 3) == derive_seed(1337, 3)
    seeds = [derive_seed(1337, i) for i in range(8)]
    assert len(set(seeds)) == 8                              # distinct per battle
    assert derive_seed(1337, 0) != derive_seed(7, 0)         # base seed matters
    assert all(1 <= s < 2 ** 31 for s in seeds)


# --------------------------------------------------------------- escalation

def test_next_config_clamped_and_reseeded_at_any_battle_idx():
    camp = new_campaign(1337, n_battles=60)
    base = CombatConfig(seed=1337)
    for idx in (0, 1, 5, 20, 59):
        camp.battle_idx = idx
        cfg = next_config(camp, base)
        # escalation can NEVER exceed the spawnable ceiling (clamp_config ran)
        assert CLAMP_DESTROYERS[0] <= cfg.n_destroyers <= CLAMP_DESTROYERS[1]
        assert CLAMP_ENEMY_RADARS[0] <= cfg.n_enemy_radars <= CLAMP_ENEMY_RADARS[1]
        assert cfg.n_awacs <= CLAMP_AWACS[1]
        # player loadout caps preserved from the base config
        assert cfg.oniks_ammo == base.oniks_ammo
        assert cfg.s300_48n6_ammo == base.s300_48n6_ammo
        # re-seeded deterministically per battle (NOT the raw base seed)
        assert cfg.seed == derive_seed(1337, idx)


def test_escalation_monotonic_to_the_clamp_ceiling():
    camp = new_campaign(1337, n_battles=60)
    base = CombatConfig(seed=1337)
    prev = -1
    for idx in range(12):
        camp.battle_idx = idx
        n = next_config(camp, base).n_destroyers
        assert n >= prev                          # monotonic non-decreasing
        prev = n
    camp.battle_idx = 59                           # far past the ceiling
    assert next_config(camp, base).n_destroyers == CLAMP_DESTROYERS[1]


# --------------------------------------------------------------- persistence

def test_save_load_round_trip(tmp_path):
    camp = new_campaign(99, n_battles=5)
    camp.battle_idx = 2
    camp.ledger = {"oniks": 3, "zircon": 1, "s300_48n6": 2}
    camp.base_damage = {"bastion_tel_00": 1}
    camp.grades = ["A", "B"]
    p = str(tmp_path / "campaign.json")
    save(camp, p)
    assert load(p) == camp
    assert load(str(tmp_path / "absent.json")) is None


# --------------------------------------------------------------- resupply

def test_apply_resupply_scales_with_grade_capped_and_deterministic():
    base = CombatConfig(seed=1)
    s_camp = new_campaign(1); s_camp.ledger = {w: 0 for w in WEAPONS}
    d_camp = new_campaign(1); d_camp.ledger = {w: 0 for w in WEAPONS}
    apply_resupply(s_camp, "S", base)
    apply_resupply(d_camp, "D", base)
    assert s_camp.ledger["oniks"] > d_camp.ledger["oniks"]      # S rearms more
    # never exceeds capacity
    full = new_campaign(1); full.ledger = {"oniks": base.oniks_ammo}
    apply_resupply(full, "S", base)
    assert full.ledger["oniks"] == base.oniks_ammo
    # deterministic (no rng): same inputs -> same ledger
    a = new_campaign(1); a.ledger = {"oniks": 2}
    b = new_campaign(1); b.ledger = {"oniks": 2}
    apply_resupply(a, "B", base); apply_resupply(b, "B", base)
    assert a.ledger == b.ledger


# --------------------------------------------------------------- snapshot

def test_world_snapshot_and_initial_state_shape():
    world = CombatWorld(CombatConfig(seed=1337, oniks_ammo=8))
    snap = world_snapshot(world)
    assert snap["ledger"]["oniks"] == 8           # a fresh world = full magazine
    assert set(WEAPONS).issubset(snap["ledger"])  # every tracked weapon present
    assert snap["base_damage"] == {}              # v1 ammo-only (base-damage deferred)
    # a fresh battle-0 campaign carries nothing -> the default arm path runs
    assert initial_state_for(new_campaign(1337)) is None
    camp = new_campaign(1337); camp.ledger = {"oniks": 2}
    st = initial_state_for(camp)
    assert st["_oniks_ammo"] == 2                  # keyed by the live world attr


# --------------------------------------------------------------- carry-forward

def test_ammo_carry_forward_and_none_is_byte_identical():
    cfg = CombatConfig(seed=1337, oniks_ammo=8)
    world = CombatWorld(cfg)
    assert world._oniks_ammo == 8                  # armed fresh
    world.apply_initial_state({"_oniks_ammo": 2, "sam_ammo": 1})
    assert world._oniks_ammo == 2 and world.sam_ammo == 1
    # the DEFAULT (no carry) path is untouched: None is a strict no-op
    w2 = CombatWorld(cfg)
    armed = w2._oniks_ammo
    w2.apply_initial_state(None)
    w2.apply_initial_state({})
    assert w2._oniks_ammo == armed == 8


def test_base_damage_not_carried_in_v1():
    """v1 carries AMMO ONLY (critique F2/F16/F19).  A legacy structure_hp key is
    IGNORED by apply_initial_state — structures keep their fresh hp/alive, so no
    battle ever starts pre-defeated and no live radar/Pantsir desyncs.  Base-damage
    carry is deferred to the campaign-loop pass."""
    cfg = CombatConfig(seed=1337)
    world = CombatWorld(cfg)
    s = world.structures[0]
    fresh_hp, fresh_alive = s.hp, s.alive
    # even an explicit structure_hp=0 ingest must NOT touch the structure
    world.apply_initial_state({"structure_hp": {s.structure_id: 0}})
    assert s.hp == fresh_hp and s.alive == fresh_alive and s.alive
    # world_snapshot does not capture base damage in v1
    assert world_snapshot(world)["base_damage"] == {}


def test_advance_snapshots_records_grade_and_steps():
    cfg = CombatConfig(seed=1337, oniks_ammo=8)
    world = CombatWorld(cfg)
    world._oniks_ammo = 3                           # spent 5 rounds this battle
    camp = new_campaign(1337, n_battles=5)
    advance(camp, world, "B", cfg)
    assert camp.battle_idx == 1
    assert camp.grades == ["B"]
    # snapshotted 3, then B-grade resupply (+30% of 8 = +2) -> 5, capped at 8
    assert camp.ledger["oniks"] == min(8, 3 + round(0.30 * 8))
    assert not camp.complete


def test_campaign_completes_after_n_battles():
    camp = new_campaign(1337, n_battles=3)
    assert not camp.complete
    camp.battle_idx = 3
    assert camp.complete
