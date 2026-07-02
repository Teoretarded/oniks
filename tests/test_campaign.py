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

def test_next_config_battle_zero_keeps_selected_seed_then_reseeds():
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
        # Battle 0 must reproduce the selected one-off battle exactly; later
        # campaign battles get fresh deterministic seeds.
        expected = base.seed if idx == 0 else derive_seed(1337, idx)
        assert cfg.seed == expected


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


def test_escalation_stages_the_m5_threat_axes():
    """The curve introduces the M5 axes on a schedule (not just more of the
    same hull): flagship+subs from battle 2, jammers/ground-attack from 3,
    transports from 4 — every count still clamp-bounded downstream."""
    camp = new_campaign(1337, n_battles=12)
    base = CombatConfig(seed=1337)

    camp.battle_idx = 0
    cfg0 = next_config(camp, base)
    assert (cfg0.n_flagship, cfg0.n_subs, cfg0.n_jammers,
            cfg0.n_transports) == (0, 0, 0, 0)     # battle 0 = the base battle

    camp.battle_idx = 2
    cfg2 = next_config(camp, base)
    assert cfg2.n_flagship == 1
    assert cfg2.n_subs == 1

    camp.battle_idx = 3
    cfg3 = next_config(camp, base)
    assert cfg3.n_jammers == 1
    assert cfg3.n_ground_attack == 1

    camp.battle_idx = 4
    cfg4 = next_config(camp, base)
    assert cfg4.n_transports == 1

    # Monotonic per axis across the whole ladder
    prev = {}
    for idx in range(12):
        camp.battle_idx = idx
        cfg = next_config(camp, base)
        for f in ("n_destroyers", "n_aaw", "n_subs", "n_jammers",
                  "n_ground_attack", "n_transports"):
            v = getattr(cfg, f)
            assert v >= prev.get(f, 0), (f, idx)
            prev[f] = v


def test_escalation_subs_arrive_with_their_counter():
    """FAIRNESS: whenever the curve fields a submarine the player gets the
    acoustic kit to fight it (buoys + ASW rounds) — a sub battle with zero
    counters is an uncounterable lose-path."""
    camp = new_campaign(1337, n_battles=12)
    base = CombatConfig(seed=1337)          # base has NO sub / NO ASW kit
    for idx in range(2, 12):
        camp.battle_idx = idx
        cfg = next_config(camp, base)
        if cfg.n_subs > 0:
            assert cfg.n_sonobuoys >= 8, idx
            assert cfg.asw_ammo >= 2, idx


def test_escalation_never_lowers_a_player_configured_kit():
    """A player who ALREADY configured a big buoy stock keeps it — the
    reinforcement is a floor, never a cut."""
    camp = new_campaign(1337, n_battles=12)
    base = CombatConfig(seed=1337, n_subs=1, n_sonobuoys=40, asw_ammo=10)
    camp.battle_idx = 2
    cfg = next_config(camp, base)
    assert cfg.n_sonobuoys == 40
    assert cfg.asw_ammo == 10


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


def test_advance_after_defeat_ends_campaign_without_next_battle():
    cfg = CombatConfig(seed=1337, oniks_ammo=8)
    world = CombatWorld(cfg)
    world._oniks_ammo = 3
    for s in world.structures:
        if s.kind == "bastion_tel":
            s.alive = False
    assert world.defeated

    camp = new_campaign(1337, n_battles=5)
    advance(camp, world, "D", cfg)

    assert camp.complete
    assert camp.battle_idx == camp.n_battles
    assert camp.grades == ["D"]
    assert camp.ledger["oniks"] == 3


def test_campaign_completes_after_n_battles():
    camp = new_campaign(1337, n_battles=3)
    assert not camp.complete
    camp.battle_idx = 3
    assert camp.complete
