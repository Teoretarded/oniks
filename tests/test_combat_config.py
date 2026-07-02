"""Tests for world/combat_config.py and the config-driven CombatWorld.

Coverage:
1. CombatConfig defaults match spec 2.1 LOCKED schema.
2. clamp_config enforces all slider ranges; seed is unclamped.
3. Seeded determinism: same config -> same fleet anchors + enemy radar pins.
4. Different seed -> different layout.
5. n_destroyers=10 places 10 destroyers + 1 carrier in open water with separation.
6. Enemy ground radars: on dry land (terrain > 0) + alive in enemy sensor picture.
7. Oniks magazine: depletes, locks at 0, refills after oniks_mag_reload_s.
8. S-300 48N6 and 40N6 magazine refill.
9. Pantsir 57E6 magazine refill.
10. Sandbox WorldState Oniks stays infinite (pre-existing green must stay green).
11. victorious flips only when ships + radars + airfield all dead.
12. defeated unchanged (all bastion_tel dead).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from sim.ships import ST_GONE
from world.combat_config import (
    DEFAULT, CombatConfig, clamp_config, clamp_field,
    CLAMP_DESTROYERS, CLAMP_AWACS, CLAMP_JAMMERS, CLAMP_PLAYER_JAMMER,
    CLAMP_ENEMY_RADARS,
    CLAMP_PLAYER_RADARS,
    CLAMP_PANTSIR, CLAMP_DRONES, CLAMP_AMMO, CLAMP_ARM_AMMO, CLAMP_ASBM_AMMO,
    CLAMP_RELOAD_S,
    CLAMP_SWARM_PODS, CLAMP_SWARM_CELLS,
    CLAMP_BUK,
    CLAMP_CBR,
    CLAMP_DECOYS, CLAMP_CORNER_REFLECTORS,
    CLAMP_FLAGSHIP, CLAMP_AAW, CLAMP_GROUND_ATTACK,
    CLAMP_MAP_PRESET, MAP_PRESET_NAMES,
    CLAMP_SUBS, CLAMP_SONOBUOYS, CLAMP_ASW_AMMO, CLAMP_SUB_KALIBR,
    CLAMP_TRANSPORTS, CLAMP_BEACHHEAD_GRACE,
)

DT = 1.0 / 120.0


# ---------------------------------------------------------------------------
# 1. Default values match LOCKED schema
# ---------------------------------------------------------------------------

def test_defaults_match_locked_schema():
    c = CombatConfig()
    assert c.seed == 1337
    assert c.n_destroyers == 3
    assert c.n_awacs == 1
    # M3-F2: escort jammers DEFAULT to 0 (OFF) so the out-of-the-box battle
    # stays byte-identical (no jammer built -> _player_visible jammers=()).
    assert c.n_jammers == 0
    # M3-F4: the player drone EW pod DEFAULTS to 0 (OFF) so the out-of-the-box
    # battle stays byte-identical (no pod armed -> _active_player_jammers()
    # empty -> the enemy detection / own-ELINT paths get jammers=()).
    assert c.player_jammer == 0
    assert c.n_enemy_radars == 2
    assert c.n_player_radars == 1
    assert c.n_pantsir == 2
    assert c.n_drones == 1
    assert c.oniks_ammo == 8
    assert c.oniks_mag_reload_s == 120.0
    assert c.s300_48n6_ammo == 4
    assert c.s300_40n6_ammo == 2
    assert c.s300_mag_reload_s == 45.0
    assert c.pantsir_57e6_ammo == 12
    assert c.pantsir_gun_ammo == 700
    assert c.pantsir_mag_reload_s == 60.0
    # M2-T2: Kh-31P player ARM pool DEFAULTS to 0 (OFF) so the out-of-the-box
    # battle stays byte-identical until a setup screen arms it.
    assert c.kh31p_ammo == 0
    # M4-A: Bastion-K ASBM pool DEFAULTS to 0 (OFF) so the out-of-the-box battle
    # stays byte-identical (no ASBM in the B cycle / HUD strip, launch returns
    # None) until a setup screen arms it.
    assert c.asbm_ammo == 0
    # M3-F4: the map preset DEFAULTS to 0 (OPEN SEA = today's layout) so the
    # out-of-the-box battle map is byte-identical (make_field(0, .) is the
    # default field); presets 1-3 add seeded terrain.
    assert c.map_preset == 0
    # M4-B: the loitering swarm pod count DEFAULTS to 0 (OFF) so the out-of-the-
    # box battle stays byte-identical (no SwarmPod built -> _swarm_cells 0 ->
    # launch_swarm returns None).
    assert c.n_swarm_pods == 0
    assert c.swarm_cells_per_pod == 8
    assert c.swarm_mag_reload_s == 90.0
    # M5: the Buk mid-SAM count DEFAULTS to 0 (OFF) so the out-of-the-box battle
    # stays byte-identical (no Buk built -> no 9S36 radar in the net ->
    # launch_buk returns None) until a setup screen arms it.
    assert c.n_buk == 0
    assert c.buk_9m317_ammo == 6
    assert c.buk_9m338_ammo == 6
    assert c.buk_mag_reload_s == 45.0
    # M5 #3: the CBR (counter-battery / early-warning radar) count DEFAULTS to 0
    # (OFF) so the out-of-the-box battle stays byte-identical (no CBR built -> not
    # in radar_net / the emitter feed -> the tracker never steps).
    assert c.n_cbr == 0
    # M5 #5: ESM decoys + corner reflectors DEFAULT 0 (OFF) so the out-of-the-box
    # battle stays byte-identical (no decoy emitter / reflector built -> absent
    # from the enemy ESM feed + the back-plot bias hook).
    assert c.n_decoys == 0
    assert c.n_corner_reflectors == 0
    # M5 enemy ship classes: ALL DEFAULT 0 so the out-of-the-box fleet stays
    # byte-identical (the typed mixer draws today's 1 carrier + n_destroyers
    # general layout; _spawn_ships builds GeneralDestroyer == legacy Destroyer).
    assert c.n_flagship == 0
    assert c.n_aaw == 0
    assert c.n_ground_attack == 0
    # M5 submarine warfare + ASW: ALL DEFAULT 0 (OFF) so the out-of-the-box
    # battle stays byte-identical (no Submarine built -> self.subs empty ->
    # no sub stepping / acoustic sensors / launch datum; place_sonobuoy +
    # launch_asw return None on 0 stock; victorious unchanged).
    assert c.n_subs == 0
    assert c.n_sonobuoys == 0
    assert c.asw_ammo == 0
    assert c.sub_kalibr_ammo == 4
    # M5 #1 amphibious: the transport count DEFAULTS to 0 (OFF) so the out-of-the-
    # box battle stays byte-identical (no Transport/LCAC built -> _step_amphibious
    # is a no-op -> defeated trips only on the bastion clause); the grace default
    # is a positive 180 s (the timer only ever starts when an LCAC reaches the
    # box, which cannot happen at n_transports=0).
    assert c.n_transports == 0
    assert c.beachhead_grace_s == 180.0


def test_world_honors_awacs_drone_and_player_radar_counts():
    from world.combat import CombatWorld

    zero = CombatWorld(CombatConfig(seed=1337, n_awacs=0, n_drones=0))
    assert [e for e in zero.enemy_air
            if e.__class__.__name__ == "Awacs"] == []
    assert zero.drone is None

    many = CombatWorld(CombatConfig(seed=1337, n_awacs=3, n_player_radars=4))
    assert len([e for e in many.enemy_air
                if e.__class__.__name__ == "Awacs"]) == 3
    assert len([r for r in many.radar_net.radars
                if r.radar_id.startswith("radar_player_")]) == 4


def test_world_uses_every_awacs_as_enemy_cue_radar():
    from world.combat import CombatWorld

    world = CombatWorld(CombatConfig(seed=1337, n_awacs=3,
                                     n_enemy_radars=0))
    awacs_radars = [e.radar for e in world.enemy_air
                    if e.__class__.__name__ == "Awacs"]
    cues = world._enemy_cue_radars()

    assert len(awacs_radars) == 3
    assert all(r in cues for r in awacs_radars)


def test_enemy_ground_radar_antenna_height_not_double_counted():
    from world.combat import CombatWorld, _ENEMY_RADAR_ANTENNA_M
    from world.generation import terrain_height_scalar

    world = CombatWorld(CombatConfig(seed=1337, n_enemy_radars=1))
    _struct, radar = world.enemy_radars[0]
    terrain = terrain_height_scalar(float(radar.pos[0]), float(radar.pos[2]))

    assert radar.pos[1] == terrain
    assert radar.antenna_alt - terrain == _ENEMY_RADAR_ANTENNA_M


# ---------------------------------------------------------------------------
# M5 #1: amphibious config fields, clamp (OFF default survivable)
# ---------------------------------------------------------------------------

def test_clamp_config_amphibious():
    """M5 #1 transport count + beachhead grace clamps.  The transport floor is 0
    so the byte-identical default survives the default-through-setup path
    (clamp_config runs every field): clamping n_transports=0 with a (1, ..) range
    would silently build the landing force and break the out-of-the-box battle.
    The grace floor is 0 (a positive default survives a round-trip and never
    breaks the n_transports=0 gate, which is geometric).  Two-sided: floors
    preserved, ceilings honoured, defaults unchanged."""
    assert CLAMP_TRANSPORTS[0] == 0, "transport count floor must be 0 (OFF survivable)"
    assert CLAMP_BEACHHEAD_GRACE[0] == 0.0, "grace floor must be 0"
    # 0 stays 0 through a clamp round-trip (byte-identical guarantee).
    assert clamp_config(n_transports=0).n_transports == 0
    # A negative slider clamps up to the 0 floor.
    assert clamp_config(n_transports=-5).n_transports == CLAMP_TRANSPORTS[0]
    assert clamp_config(beachhead_grace_s=-9.0).beachhead_grace_s == \
        CLAMP_BEACHHEAD_GRACE[0]
    # Ceilings honoured (a small amphibious group, mirroring CLAMP_SUBS).
    assert CLAMP_TRANSPORTS == (0, 3)
    assert clamp_config(n_transports=9999).n_transports == CLAMP_TRANSPORTS[1]
    assert clamp_config(beachhead_grace_s=9999.0).beachhead_grace_s == \
        CLAMP_BEACHHEAD_GRACE[1]
    # In-band values round-trip unchanged.
    assert clamp_config(n_transports=2).n_transports == 2
    assert clamp_config(beachhead_grace_s=120.0).beachhead_grace_s == 120.0
    # A default-config build (no edits) keeps the landing force OFF + the
    # documented grace default surviving the setup-default clamp path.
    assert clamp_config().n_transports == 0
    assert clamp_config().beachhead_grace_s == 180.0


# ---------------------------------------------------------------------------
# M5: submarine warfare + ASW config fields, clamp (OFF default survivable)
# ---------------------------------------------------------------------------

def test_clamp_config_asw_domain():
    """M5 submarine/ASW count clamps. EVERY floor is 0 so the byte-identical
    default survives the default-through-setup path (clamp_config runs every
    field): clamping any of these from 0 with a (1, ..) range would silently
    spawn a boat / arm the ASW kit and break the out-of-the-box battle.
    Two-sided: floor 0 preserved, ceiling honoured, default unchanged."""
    assert CLAMP_SUBS[0] == 0, "sub count floor must be 0 (OFF survivable)"
    assert CLAMP_SONOBUOYS[0] == 0, "sonobuoy floor must be 0 (OFF survivable)"
    assert CLAMP_ASW_AMMO[0] == 0, "ASW ammo floor must be 0 (OFF survivable)"
    assert CLAMP_SUB_KALIBR[0] == 0, "sub Kalibr floor must be 0"
    # 0 stays 0 through a clamp round-trip (byte-identical guarantee).
    assert clamp_config(n_subs=0).n_subs == 0
    assert clamp_config(n_sonobuoys=0).n_sonobuoys == 0
    assert clamp_config(asw_ammo=0).asw_ammo == 0
    # Negatives clamp up to the 0 floor.
    assert clamp_config(n_subs=-5).n_subs == CLAMP_SUBS[0]
    assert clamp_config(n_sonobuoys=-5).n_sonobuoys == CLAMP_SONOBUOYS[0]
    assert clamp_config(asw_ammo=-5).asw_ammo == CLAMP_ASW_AMMO[0]
    assert clamp_config(sub_kalibr_ammo=-5).sub_kalibr_ammo == CLAMP_SUB_KALIBR[0]
    # Ceilings honoured.
    assert CLAMP_SUBS == (0, 3)
    assert clamp_config(n_subs=9999).n_subs == CLAMP_SUBS[1]
    assert clamp_config(n_sonobuoys=9999).n_sonobuoys == CLAMP_SONOBUOYS[1]
    assert clamp_config(asw_ammo=9999).asw_ammo == CLAMP_ASW_AMMO[1]
    assert clamp_config(sub_kalibr_ammo=9999).sub_kalibr_ammo == CLAMP_SUB_KALIBR[1]
    # In-band values round-trip unchanged.
    assert clamp_config(n_subs=1).n_subs == 1
    assert clamp_config(n_sonobuoys=12).n_sonobuoys == 12
    assert clamp_config(asw_ammo=4).asw_ammo == 4
    assert clamp_config(sub_kalibr_ammo=2).sub_kalibr_ammo == 2
    # A default-config build (no edits) keeps the whole domain OFF + the
    # documented per-boat Kalibr default surviving the setup path.
    assert clamp_config().n_subs == 0
    assert clamp_config().n_sonobuoys == 0
    assert clamp_config().asw_ammo == 0
    assert clamp_config().sub_kalibr_ammo == 4


# ---------------------------------------------------------------------------
# M5: enemy ship-class counts, clamp (OFF default survivable -> byte-identical)
# ---------------------------------------------------------------------------

def test_clamp_config_ship_classes():
    """M5 ship-class count clamps. EVERY floor is 0 so the byte-identical
    default survives the default-through-setup path (clamp_config runs every
    field): clamping any of these from 0 with a (1, ..) range would silently
    spawn the class and break the out-of-the-box battle. Two-sided: floor 0
    preserved, ceiling honoured, default unchanged."""
    assert CLAMP_FLAGSHIP[0] == 0, "flagship floor must be 0 (OFF survivable)"
    assert CLAMP_AAW[0] == 0, "aaw floor must be 0 (OFF survivable)"
    assert CLAMP_GROUND_ATTACK[0] == 0, "ground_attack floor must be 0"
    # 0 stays 0 through a clamp round-trip (byte-identical guarantee).
    assert clamp_config(n_flagship=0).n_flagship == 0
    assert clamp_config(n_aaw=0).n_aaw == 0
    assert clamp_config(n_ground_attack=0).n_ground_attack == 0
    # Negatives clamp up to the 0 floor.
    assert clamp_config(n_flagship=-5).n_flagship == CLAMP_FLAGSHIP[0]
    assert clamp_config(n_aaw=-5).n_aaw == CLAMP_AAW[0]
    assert clamp_config(n_ground_attack=-5).n_ground_attack == \
        CLAMP_GROUND_ATTACK[0]
    # Ceilings honoured (flagship is a 0/1 hull).
    assert CLAMP_FLAGSHIP == (0, 1)
    assert clamp_config(n_flagship=9).n_flagship == CLAMP_FLAGSHIP[1]
    assert clamp_config(n_aaw=9999).n_aaw == CLAMP_AAW[1]
    assert clamp_config(n_ground_attack=9999).n_ground_attack == \
        CLAMP_GROUND_ATTACK[1]
    # In-band values round-trip unchanged.
    assert clamp_config(n_flagship=1).n_flagship == 1
    assert clamp_config(n_aaw=3).n_aaw == 3
    assert clamp_config(n_ground_attack=2).n_ground_attack == 2
    # A default-config build (no edits) keeps every new class OFF.
    assert clamp_config().n_flagship == 0
    assert clamp_config().n_aaw == 0
    assert clamp_config().n_ground_attack == 0


# ---------------------------------------------------------------------------
# M5: n_buk config field, clamp (OFF default survivable)
# ---------------------------------------------------------------------------

def test_clamp_config_buk():
    """M5 Buk TEL count clamp round-trip. LIKE the swarm/ASBM/ARM gates its
    floor is 0, so the OFF default survives the default-through-setup path
    (clamp_config runs every field): clamping n_buk=0 with a (1, ..) range
    would silently build the Buk and break the byte-identical out-of-the-box
    battle. Two-sided: floor 0 preserved, ceiling honoured, default unchanged."""
    assert CLAMP_BUK[0] == 0, "Buk count floor must be 0 (OFF survivable)"
    # A 0 count stays 0 through a clamp round-trip (byte-identical guarantee).
    assert clamp_config(n_buk=0).n_buk == 0
    # A negative slider clamps up to the 0 floor.
    assert clamp_config(n_buk=-5).n_buk == CLAMP_BUK[0]
    # The ceiling is honoured.
    assert clamp_config(n_buk=9999).n_buk == CLAMP_BUK[1]
    # An in-band value round-trips unchanged.
    assert clamp_config(n_buk=1).n_buk == 1
    # A default-config build (no edits) keeps the Buk OFF.
    assert clamp_config().n_buk == 0
    # Both ammo pools + the reload round-trip and the documented defaults
    # survive the default-through-setup path.
    assert clamp_config().buk_9m317_ammo == 6
    assert clamp_config().buk_9m338_ammo == 6
    assert clamp_config().buk_mag_reload_s == 45.0
    assert clamp_config(buk_9m317_ammo=9999).buk_9m317_ammo == CLAMP_AMMO[1]
    assert clamp_config(buk_9m338_ammo=9999).buk_9m338_ammo == CLAMP_AMMO[1]


# ---------------------------------------------------------------------------
# M5 #3: n_cbr config field, clamp (OFF default survivable)
# ---------------------------------------------------------------------------

def test_clamp_config_cbr():
    """M5 #3 CBR count clamp round-trip. LIKE the Buk/swarm/ARM gates its floor
    is 0, so the OFF default survives the default-through-setup path (clamp_config
    runs every field): clamping n_cbr=0 with a (1, ..) range would silently build
    the CBR, join it to radar_net + the emitter feed, and break the byte-identical
    out-of-the-box battle. Two-sided: floor 0 preserved, ceiling honoured, default
    unchanged."""
    assert CLAMP_CBR[0] == 0, "CBR count floor must be 0 (OFF survivable)"
    # A 0 count stays 0 through a clamp round-trip (byte-identical guarantee).
    assert clamp_config(n_cbr=0).n_cbr == 0
    # A negative slider clamps up to the 0 floor.
    assert clamp_config(n_cbr=-5).n_cbr == CLAMP_CBR[0]
    # The ceiling is honoured (a small early-warning fit, mirroring CLAMP_BUK).
    assert CLAMP_CBR == (0, 2)
    assert clamp_config(n_cbr=9999).n_cbr == CLAMP_CBR[1]
    # An in-band value round-trips unchanged.
    assert clamp_config(n_cbr=1).n_cbr == 1
    # A default-config build (no edits) keeps the CBR OFF.
    assert clamp_config().n_cbr == 0


# ---------------------------------------------------------------------------
# M5 #5: n_decoys + n_corner_reflectors config fields, clamp (OFF survivable)
# ---------------------------------------------------------------------------

def test_clamp_config_decoys_and_reflectors():
    """M5 #5 decoy + corner-reflector count clamp round-trip. LIKE every other M5
    spoofer/launcher gate their floors are 0, so the OFF default survives the
    default-through-setup path (clamp_config runs every field): clamping either
    from 0 with a (1, ..) range would silently plant a spoofer and break the
    byte-identical out-of-the-box battle. Two-sided: floor 0 preserved, ceiling
    honoured, default unchanged."""
    assert CLAMP_DECOYS[0] == 0, "decoy count floor must be 0 (OFF survivable)"
    assert CLAMP_CORNER_REFLECTORS[0] == 0, "reflector floor must be 0"
    assert CLAMP_DECOYS == (0, 4)
    assert CLAMP_CORNER_REFLECTORS == (0, 4)
    # A 0 count stays 0 through a clamp round-trip (byte-identical guarantee).
    assert clamp_config(n_decoys=0).n_decoys == 0
    assert clamp_config(n_corner_reflectors=0).n_corner_reflectors == 0
    # Negative sliders clamp up to the 0 floor.
    assert clamp_config(n_decoys=-5).n_decoys == CLAMP_DECOYS[0]
    assert (clamp_config(n_corner_reflectors=-5).n_corner_reflectors
            == CLAMP_CORNER_REFLECTORS[0])
    # Ceilings honoured.
    assert clamp_config(n_decoys=9999).n_decoys == CLAMP_DECOYS[1]
    assert (clamp_config(n_corner_reflectors=9999).n_corner_reflectors
            == CLAMP_CORNER_REFLECTORS[1])
    # In-band values round-trip unchanged.
    assert clamp_config(n_decoys=2).n_decoys == 2
    assert clamp_config(n_corner_reflectors=3).n_corner_reflectors == 3
    # A default-config build (no edits) keeps both spoofers OFF.
    assert clamp_config().n_decoys == 0
    assert clamp_config().n_corner_reflectors == 0


# ---------------------------------------------------------------------------
# M6 campaign: clamp_config <-> CombatConfig field parity (campaign launch guard)
# ---------------------------------------------------------------------------

def test_clamp_config_accepts_every_combatconfig_field():
    """game.campaign.next_config does clamp_config(**dataclasses.asdict(base)).  If
    a CombatConfig field is ever ADDED without the matching clamp_config keyword
    param, that splat raises TypeError and kills the WHOLE campaign launch path
    (critique F-dual-maintenance).  Pin the 1:1 parity so such an add fails HERE,
    loudly, instead of silently breaking campaign."""
    import dataclasses
    import inspect
    cfg_fields = {f.name for f in dataclasses.fields(CombatConfig)}
    params = set(inspect.signature(clamp_config).parameters)
    missing = cfg_fields - params
    assert not missing, (
        f"clamp_config is missing a keyword param for CombatConfig field(s): "
        f"{sorted(missing)} — next_config's clamp_config(**asdict(base)) would "
        f"TypeError and break the campaign launch.")
    # the actual splat campaign relies on must not raise + must preserve values
    base = CombatConfig()
    rt = clamp_config(**dataclasses.asdict(base))
    assert rt.seed == base.seed and rt.n_destroyers == base.n_destroyers


# ---------------------------------------------------------------------------
# M3-F4: map_preset config field, clamp and names table
# ---------------------------------------------------------------------------

def test_map_preset_default_is_open_sea():
    """The locked default is 0 (OPEN SEA) so the default battle map is the
    byte-identical legacy field."""
    assert CombatConfig().map_preset == 0
    assert MAP_PRESET_NAMES[0] == "OPEN SEA"


def test_map_preset_names_full_table():
    assert MAP_PRESET_NAMES == ("OPEN SEA", "ARCHIPELAGO",
                                "NARROW STRAIT", "FJORD COAST")
    # Exactly one name per clamp value (0..3).
    assert len(MAP_PRESET_NAMES) == CLAMP_MAP_PRESET[1] - CLAMP_MAP_PRESET[0] + 1


def test_clamp_config_map_preset_round_trip():
    """clamp_config round-trips map_preset within (0, 3) and the default 0
    survives the default-through-setup path (every field runs clamp_config)."""
    assert CLAMP_MAP_PRESET == (0, 3)
    # Default 0 survives a clamp round-trip.
    assert clamp_config(map_preset=0).map_preset == 0
    # In-band values round-trip unchanged.
    for p in (0, 1, 2, 3):
        assert clamp_config(map_preset=p).map_preset == p
    # Below floor clamps up; above ceiling clamps down.
    assert clamp_config(map_preset=-5).map_preset == CLAMP_MAP_PRESET[0]
    assert clamp_config(map_preset=99).map_preset == CLAMP_MAP_PRESET[1]
    # A default-config build keeps OPEN SEA.
    assert clamp_config().map_preset == 0


def test_default_is_frozen():
    """Frozen dataclass: cannot assign fields."""
    with pytest.raises((AttributeError, TypeError)):
        DEFAULT.seed = 42  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2. clamp_config + clamp_field enforce ranges
# ---------------------------------------------------------------------------

def test_clamp_field_bounds():
    assert clamp_field(5, 0, 10) == 5
    assert clamp_field(-1, 0, 10) == 0
    assert clamp_field(99, 0, 10) == 10


def test_clamp_config_count_floors():
    c = clamp_config(
        n_destroyers=-5, n_awacs=-1, n_jammers=-1, player_jammer=-1,
        n_enemy_radars=-1,
        n_player_radars=0,   # below min 1
        n_pantsir=-1, n_drones=-1,
    )
    assert c.n_destroyers == CLAMP_DESTROYERS[0]
    assert c.n_awacs == CLAMP_AWACS[0]
    assert c.n_jammers == CLAMP_JAMMERS[0]    # floor 0 -> OFF survives clamp
    assert c.player_jammer == CLAMP_PLAYER_JAMMER[0]   # floor 0 -> OFF survives
    assert c.n_enemy_radars == CLAMP_ENEMY_RADARS[0]
    assert c.n_player_radars == CLAMP_PLAYER_RADARS[0]  # min=1
    assert c.n_pantsir == CLAMP_PANTSIR[0]
    assert c.n_drones == CLAMP_DRONES[0]


def test_clamp_config_count_ceilings():
    c = clamp_config(
        n_destroyers=999, n_awacs=999, n_jammers=999, player_jammer=999,
        n_enemy_radars=999,
        n_player_radars=999, n_pantsir=999, n_drones=999,
    )
    assert c.n_destroyers == CLAMP_DESTROYERS[1]
    assert c.n_awacs == CLAMP_AWACS[1]
    assert c.n_jammers == CLAMP_JAMMERS[1]
    assert c.player_jammer == CLAMP_PLAYER_JAMMER[1]   # 0/1 flag ceiling
    assert c.n_enemy_radars == CLAMP_ENEMY_RADARS[1]
    assert c.n_player_radars == CLAMP_PLAYER_RADARS[1]
    assert c.n_pantsir == CLAMP_PANTSIR[1]
    assert c.n_drones == CLAMP_DRONES[1]


def test_clamp_config_ammo_floor():
    c = clamp_config(
        oniks_ammo=0, s300_48n6_ammo=0, s300_40n6_ammo=0,
        pantsir_57e6_ammo=0, pantsir_gun_ammo=0,
    )
    assert c.oniks_ammo == CLAMP_AMMO[0]        # min 1
    assert c.s300_48n6_ammo == CLAMP_AMMO[0]
    assert c.s300_40n6_ammo == CLAMP_AMMO[0]
    assert c.pantsir_57e6_ammo == CLAMP_AMMO[0]
    assert c.pantsir_gun_ammo == CLAMP_AMMO[0]


def test_clamp_config_ammo_ceiling():
    c = clamp_config(
        oniks_ammo=9999, s300_48n6_ammo=9999,
    )
    assert c.oniks_ammo == CLAMP_AMMO[1]        # max 200
    assert c.s300_48n6_ammo == CLAMP_AMMO[1]


def test_clamp_config_kh31p_arm_pool():
    """M2-T2 Kh-31P ARM pool clamp round-trip. UNLIKE the other missile pools,
    its floor is 0 (CLAMP_ARM_AMMO), so the OFF default survives the
    default-through-setup path (clamp_config runs every field): clamping
    kh31p_ammo=0 with the missile CLAMP_AMMO=(1,200) would silently turn the
    ARM ON. Two-sided: floor 0 preserved, ceiling honoured, default unchanged."""
    assert CLAMP_ARM_AMMO[0] == 0, "ARM pool floor must be 0 (OFF survivable)"
    # A 0 pool stays 0 through a clamp round-trip (byte-identical guarantee).
    assert clamp_config(kh31p_ammo=0).kh31p_ammo == 0
    # A negative slider clamps up to the 0 floor.
    assert clamp_config(kh31p_ammo=-5).kh31p_ammo == CLAMP_ARM_AMMO[0]
    # The ceiling matches the other missile pools.
    assert clamp_config(kh31p_ammo=9999).kh31p_ammo == CLAMP_ARM_AMMO[1]
    # An in-band value round-trips unchanged.
    assert clamp_config(kh31p_ammo=4).kh31p_ammo == 4
    # A default-config build (no edits) keeps the ARM OFF.
    assert clamp_config().kh31p_ammo == 0


def test_clamp_config_asbm_pool():
    """M4-A Bastion-K ASBM pool clamp round-trip. LIKE the Kh-31P ARM pool its
    floor is 0 (CLAMP_ASBM_AMMO), so the OFF default survives the default-
    through-setup path (clamp_config runs every field): clamping asbm_ammo=0
    with the missile CLAMP_AMMO=(1,200) would silently turn the ASBM ON and
    break the byte-identical out-of-the-box battle. Two-sided: floor 0
    preserved, ceiling honoured, default unchanged."""
    assert CLAMP_ASBM_AMMO[0] == 0, "ASBM pool floor must be 0 (OFF survivable)"
    # A 0 pool stays 0 through a clamp round-trip (byte-identical guarantee).
    assert clamp_config(asbm_ammo=0).asbm_ammo == 0
    # A negative slider clamps up to the 0 floor.
    assert clamp_config(asbm_ammo=-5).asbm_ammo == CLAMP_ASBM_AMMO[0]
    # The ceiling matches the other missile pools.
    assert clamp_config(asbm_ammo=9999).asbm_ammo == CLAMP_ASBM_AMMO[1]
    # An in-band value round-trips unchanged.
    assert clamp_config(asbm_ammo=4).asbm_ammo == 4
    # A default-config build (no edits) keeps the ASBM OFF.
    assert clamp_config().asbm_ammo == 0


def test_clamp_config_swarm_pods():
    """M4-B swarm pod count clamp round-trip. LIKE the ASBM/ARM pools its floor
    is 0, so the OFF default survives the default-through-setup path
    (clamp_config runs every field): clamping n_swarm_pods=0 with a (1, ..)
    range would silently arm the swarm and break the byte-identical out-of-the-
    box battle. Two-sided: floor 0 preserved, ceiling honoured, default
    unchanged."""
    assert CLAMP_SWARM_PODS[0] == 0, "swarm pod floor must be 0 (OFF survivable)"
    # A 0 count stays 0 through a clamp round-trip (byte-identical guarantee).
    assert clamp_config(n_swarm_pods=0).n_swarm_pods == 0
    # A negative slider clamps up to the 0 floor.
    assert clamp_config(n_swarm_pods=-5).n_swarm_pods == CLAMP_SWARM_PODS[0]
    # The ceiling is honoured.
    assert clamp_config(n_swarm_pods=9999).n_swarm_pods == CLAMP_SWARM_PODS[1]
    # An in-band value round-trips unchanged.
    assert clamp_config(n_swarm_pods=2).n_swarm_pods == 2
    # A default-config build (no edits) keeps the swarm OFF.
    assert clamp_config().n_swarm_pods == 0
    # Cells-per-pod round-trips and the documented default (8) survives the
    # default-through-setup path (floor 4 would otherwise be a regression).
    assert clamp_config().swarm_cells_per_pod == 8
    assert clamp_config(swarm_cells_per_pod=1).swarm_cells_per_pod \
        == CLAMP_SWARM_CELLS[0]
    assert clamp_config(swarm_cells_per_pod=999).swarm_cells_per_pod \
        == CLAMP_SWARM_CELLS[1]
    # The reload uses the shared CLAMP_RELOAD_S; the default survives.
    assert clamp_config().swarm_mag_reload_s == 90.0


def test_clamp_config_player_jammer_flag():
    """M3-F4 player EW pod flag clamp round-trip. LIKE n_jammers (and the ARM
    pool) its floor is 0, so the OFF default survives the default-through-setup
    path (clamp_config runs every field): clamping player_jammer=0 with a
    (1, ..) range would silently ARM the pod and break the byte-identical
    out-of-the-box battle. It is a 0/1 flag: ceiling 1."""
    assert CLAMP_PLAYER_JAMMER == (0, 1), "the pod flag is a 0/1 OFF-survivable flag"
    # A 0 flag stays 0 through a clamp round-trip (byte-identical guarantee).
    assert clamp_config(player_jammer=0).player_jammer == 0
    # A negative slider clamps up to the 0 floor (OFF).
    assert clamp_config(player_jammer=-5).player_jammer == CLAMP_PLAYER_JAMMER[0]
    # Anything above 1 clamps down to the 0/1 ceiling.
    assert clamp_config(player_jammer=9).player_jammer == CLAMP_PLAYER_JAMMER[1]
    # 1 round-trips unchanged (the pod armed).
    assert clamp_config(player_jammer=1).player_jammer == 1
    # A default-config build (no edits) keeps the pod OFF.
    assert clamp_config().player_jammer == 0


def test_clamp_config_preserves_default_gun_belt():
    """The LOCKED schema default pantsir_gun_ammo=700 must survive a
    clamp_config() round-trip (the default-through-setup path runs every
    field through clamp_config; a 700 belt clamped with the missile
    CLAMP_AMMO=(1,200) would silently truncate to 200 — regression guard
    for the dedicated CLAMP_GUN_AMMO range)."""
    from world.combat_config import CLAMP_GUN_AMMO
    assert clamp_config(pantsir_gun_ammo=700).pantsir_gun_ammo == 700
    # ceiling + floor honoured on the gun-specific range
    assert clamp_config(pantsir_gun_ammo=99999).pantsir_gun_ammo == CLAMP_GUN_AMMO[1]
    assert clamp_config(pantsir_gun_ammo=0).pantsir_gun_ammo == CLAMP_GUN_AMMO[0]
    # a default-config build (no edits) keeps the full 700-round belt
    assert clamp_config().pantsir_gun_ammo == 700


def test_clamp_config_reload_range():
    c = clamp_config(oniks_mag_reload_s=0.0)    # below min 5.0
    assert c.oniks_mag_reload_s == CLAMP_RELOAD_S[0]

    c2 = clamp_config(oniks_mag_reload_s=9999.0)  # above max 600.0
    assert c2.oniks_mag_reload_s == CLAMP_RELOAD_S[1]


def test_clamp_config_seed_unclamped():
    """Seed must accept any integer — no clamping applied."""
    assert clamp_config(seed=0).seed == 0
    assert clamp_config(seed=2 ** 32).seed == 2 ** 32
    assert clamp_config(seed=-1).seed == -1


# ---------------------------------------------------------------------------
# 3 + 4. Seeded determinism / different-seed divergence
# ---------------------------------------------------------------------------

def _fleet_anchors(cw):
    """Sorted (x, z) anchor pairs for all ships (carrier included)."""
    return sorted(
        (round(float(s.pos[0])), round(float(s.pos[2])))
        for s in cw.ships)


def _enemy_radar_pins(cw):
    """Sorted (x, z) for each enemy ground radar structure."""
    return sorted(
        (round(float(struct.pos[0])), round(float(struct.pos[2])))
        for struct, _r in cw.enemy_radars)


def test_seeded_determinism_fleet_and_radars():
    """Same config -> same fleet anchors and enemy radar pins."""
    from world.combat import CombatWorld
    cfg = CombatConfig(seed=42, n_destroyers=3, n_enemy_radars=2)
    cw_a = CombatWorld(cfg)
    cw_b = CombatWorld(cfg)
    assert _fleet_anchors(cw_a) == _fleet_anchors(cw_b)
    assert _enemy_radar_pins(cw_a) == _enemy_radar_pins(cw_b)


def test_different_seed_different_layout():
    """Different seed -> different fleet layout."""
    from world.combat import CombatWorld
    cw1 = CombatWorld(CombatConfig(seed=100, n_destroyers=4))
    cw2 = CombatWorld(CombatConfig(seed=200, n_destroyers=4))
    assert _fleet_anchors(cw1) != _fleet_anchors(cw2)


# ---------------------------------------------------------------------------
# 5. n_destroyers=10: open water, separation
# ---------------------------------------------------------------------------

def test_large_destroyer_count_placement():
    """n_destroyers=10 places 10 destroyers + 1 carrier, all open water,
    all >= 25 km apart (world/spawn_zones.py contract)."""
    from world.combat import CombatWorld
    from world.spawn_zones import MIN_SEPARATION_M
    from world.generation import terrain_height_scalar

    cw = CombatWorld(CombatConfig(seed=1337, n_destroyers=10))
    assert len(cw.ships) == 11  # 10 destroyers + 1 carrier

    xz_list = [(float(s.pos[0]), float(s.pos[2])) for s in cw.ships]
    # Open water
    for x, z in xz_list:
        assert terrain_height_scalar(x, z) < -5.0, (
            f"ship at ({x:.0f}, {z:.0f}) not in open water")
    # >= 25 km separation
    for i, (ax, az) in enumerate(xz_list):
        for j, (bx, bz) in enumerate(xz_list):
            if i >= j:
                continue
            sep = math.hypot(ax - bx, az - bz)
            assert sep >= MIN_SEPARATION_M, (
                f"ships {i} and {j} too close ({sep/1e3:.1f} km)")


# ---------------------------------------------------------------------------
# 6. Enemy ground radars: on dry land, in enemy sensor picture
# ---------------------------------------------------------------------------

def test_enemy_radars_on_dry_land():
    """All enemy radar structures sit on dry land (terrain > 0)."""
    from world.combat import CombatWorld
    from world.generation import terrain_height_scalar

    cw = CombatWorld(CombatConfig(seed=1337, n_enemy_radars=4))
    assert len(cw.enemy_radars) == 4
    for struct, r in cw.enemy_radars:
        x, z = float(struct.pos[0]), float(struct.pos[2])
        h = terrain_height_scalar(x, z)
        assert h > 0.0, (
            f"enemy radar at ({x:.0f}, {z:.0f}) below sea level h={h:.1f}")


def test_enemy_radars_in_enemy_picture():
    """Enemy ground radars are returned by _enemy_cue_radars (datalink) and
    include their Radar in the emitters list."""
    from world.combat import CombatWorld

    cw = CombatWorld(CombatConfig(seed=1337, n_enemy_radars=2))
    cues = cw._enemy_cue_radars()
    # The ground radar Radars should be in the cue list (alive at init)
    ground_radars = [r for _s, r in cw.enemy_radars]
    for r in ground_radars:
        assert r in cues, "live enemy ground radar not in _enemy_cue_radars"

    # _emitters includes them
    emitter_ids = {eid for eid, _ in cw._emitters()}
    for _s, r in cw.enemy_radars:
        assert r.radar_id in emitter_ids, (
            f"{r.radar_id} not in _emitters()")


def test_zero_enemy_radars():
    """n_enemy_radars=0 is valid — no radars spawned."""
    from world.combat import CombatWorld
    cw = CombatWorld(CombatConfig(seed=1337, n_enemy_radars=0))
    assert cw.enemy_radars == []


# ---------------------------------------------------------------------------
# 7. Oniks magazine: deplete, lock, refill
# ---------------------------------------------------------------------------

def _build_combat(config=None):
    from world.combat import CombatWorld
    return CombatWorld(config or DEFAULT)


def test_oniks_magazine_depletes_and_locks():
    """Firing oniks_ammo shots drains the magazine to 0; next launch returns
    None and launcher_armed is False."""
    cfg = CombatConfig(seed=1337, oniks_ammo=3, oniks_mag_reload_s=60.0)
    cw = _build_combat(cfg)
    target = np.array([0.0, 0.0, 150_000.0])

    for _ in range(3):
        m = cw.launch("hi-lo", target)
        assert m is not None, "launch should succeed within magazine"
        # Skip the per-tube reload: instantly re-cock spent tubes from the pool
        # (the salvo battery's equivalent of the old reload_left skip; a single
        # Bastion now has 2 tubes, so a 3-round magazine spans two re-cocks).
        for t in cw._oniks_tubes:
            t["reload_left"] = 0.0
        cw._step_oniks_tubes(0.0)

    assert cw._oniks_ammo == 0
    assert not cw.launcher_armed
    # 4th launch blocked
    m4 = cw.launch("hi-lo", target)
    assert m4 is None, "4th launch must be blocked (magazine empty)"


def test_oniks_magazine_refills_after_timer():
    """After the magazine runs dry the refill timer runs and restores ammo."""
    cfg = CombatConfig(seed=1337, oniks_ammo=2, oniks_mag_reload_s=5.0)
    cw = _build_combat(cfg)
    target = np.array([0.0, 0.0, 150_000.0])

    for _ in range(2):
        cw.launch("hi-lo", target)
        cw.reload_left = 0.0

    assert cw._oniks_ammo == 0
    assert cw._oniks_mag_reload_left > 0.0

    # Run for 5.1 s — refill should complete
    for _ in range(int(5.1 * 120)):
        cw.step(DT)

    assert cw._oniks_ammo == 2
    assert cw.launcher_armed


def test_oniks_magazine_initial_count():
    """_oniks_ammo starts at oniks_ammo; a fresh config is fully loaded."""
    cfg = CombatConfig(seed=1337, oniks_ammo=8)
    cw = _build_combat(cfg)
    assert cw._oniks_ammo == 8
    assert cw._oniks_mag_cap == 8


# ---------------------------------------------------------------------------
# 8. S-300 magazine refill
# ---------------------------------------------------------------------------

def test_s300_48n6_magazine_refill():
    """48N6 pool: drains to 0, blocks further shots, refills after timer."""
    from world.combat import CombatWorld

    cfg = CombatConfig(seed=1337, s300_48n6_ammo=2, s300_mag_reload_s=5.0)
    cw = CombatWorld(cfg)
    assert cw.sam_ammo == 2

    # Drain by direct manipulation (no need for a tracked target)
    cw.sam_ammo = 0
    cw._s300_48n6_mag_reload_left = cfg.s300_mag_reload_s

    assert not cw.sam_launcher_armed

    for _ in range(int(5.1 * 120)):
        cw.step(DT)

    assert cw.sam_ammo == 2
    assert cw.sam_launcher_armed


def test_s300_40n6_magazine_refill():
    """40N6 pool: same mechanic as 48N6."""
    from world.combat import CombatWorld

    cfg = CombatConfig(seed=1337, s300_40n6_ammo=2, s300_mag_reload_s=5.0)
    cw = CombatWorld(cfg)
    assert cw.sam_ammo_40n6 == 2

    cw.sam_ammo_40n6 = 0
    cw._s300_40n6_mag_reload_left = cfg.s300_mag_reload_s

    assert not cw.sam_40n6_launcher_armed

    for _ in range(int(5.1 * 120)):
        cw.step(DT)

    assert cw.sam_ammo_40n6 == 2
    assert cw.sam_40n6_launcher_armed


# ---------------------------------------------------------------------------
# 9. Pantsir 57E6 magazine refill
# ---------------------------------------------------------------------------

def test_pantsir_magazine_refill():
    """Pantsir 57E6 magazine: drain, block, refill after timer."""
    from world.combat import CombatWorld
    from sim.pantsir import PantsirDefenseController

    cfg = CombatConfig(seed=1337, pantsir_57e6_ammo=3, pantsir_mag_reload_s=5.0)
    cw = CombatWorld(cfg)

    pantsir = cw.pantsirs[0]
    assert pantsir.missile_ammo == 3
    assert pantsir._mag_cap == 3
    assert pantsir._mag_reload_s == 5.0

    # Drain ammo and arm the timer
    pantsir.missile_ammo = 0
    pantsir._mag_reload_left = 5.0

    for _ in range(int(5.1 * 120)):
        cw.step(DT)

    assert pantsir.missile_ammo == 3, (
        f"Pantsir ammo should refill to 3 but got {pantsir.missile_ammo}")


# ---------------------------------------------------------------------------
# 10. Sandbox Oniks stays infinite (pre-existing green)
# ---------------------------------------------------------------------------

def test_sandbox_oniks_is_infinite():
    """WorldState (sandbox) must fire unlimited Oniks — _oniks_ammo=None."""
    from world.world import WorldState
    import numpy as np

    ws = WorldState()
    assert ws._oniks_ammo is None, "_oniks_ammo must be None in sandbox"

    target = np.array([0.0, 0.0, 150_000.0])
    for _ in range(10):
        m = ws.launch("hi-lo", target)
        assert m is not None, "Sandbox Oniks must be infinite"
        ws.reload_left = 0.0  # skip per-shot reload


# ---------------------------------------------------------------------------
# 11. victorious condition: ships + radars + airfield all dead
# ---------------------------------------------------------------------------

def test_victorious_requires_all_conditions():
    """victorious only flips when all ships AND all enemy radars AND airfield
    are destroyed — partial destruction is not enough."""
    from world.combat import CombatWorld

    cfg = CombatConfig(seed=1337, n_enemy_radars=2)
    cw = CombatWorld(cfg)

    # Initially none are dead — not victorious.
    assert not cw.victorious

    # Kill all ships only (alive is a read-only property; set state to ST_GONE).
    for s in cw.ships:
        s.state = ST_GONE
    assert not cw.victorious  # airfield + radars still alive

    # Kill airfield too.
    cw.airfield.alive = False
    assert not cw.victorious  # radars still alive

    # Kill all enemy radars.
    for struct, r in cw.enemy_radars:
        struct.alive = False
        r.alive = False
    assert cw.victorious


def test_victorious_with_zero_radars():
    """With n_enemy_radars=0 the win condition reduces to ships + airfield."""
    from world.combat import CombatWorld

    cfg = CombatConfig(seed=1337, n_enemy_radars=0)
    cw = CombatWorld(cfg)
    for s in cw.ships:
        s.state = ST_GONE
    cw.airfield.alive = False
    assert cw.victorious


# ---------------------------------------------------------------------------
# 12. defeated: unchanged — all bastion_tel structures dead
# ---------------------------------------------------------------------------

def test_defeated_unchanged():
    """Spec 2.2 lose condition: all bastion_tel structures dead."""
    from world.combat import CombatWorld

    cw = CombatWorld(DEFAULT)
    assert not cw.defeated

    for s in cw.structures:
        if s.kind == "bastion_tel":
            s.alive = False
    assert cw.defeated
