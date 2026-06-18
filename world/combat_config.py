"""CombatConfig: frozen dataclass for all setup-screen parameters (Phase 7).

LOCKED schema — field names and defaults must not be changed without a full
integrator sign-off.  Both the setup UI (game/combat_setup.py) and the
combat world (world/combat.py) import this module.

Magazine mechanic (LOCKED):
    Each player weapon has a magazine of <ammo> rounds.  Firing consumes
    one round plus runs the per-shot tube reload.  When the magazine hits 0
    a <mag_reload_s>-second timer runs and refills it to capacity.  This
    makes ammo renewable but rate-limited.

Clamp ranges are module-level constants, NOT dataclass fields.  UI spinners
    enforce them; the dataclass itself does NOT validate (frozen + simple).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CombatConfig:
    seed: int = 1337
    n_destroyers: int = 3        # carrier is ALWAYS 1, not configurable
    # M5 enemy ship classes — the doctrinally varied task group.  ALL DEFAULT 0
    # so the out-of-the-box fleet stays BYTE-IDENTICAL: with these 0 the typed
    # mixer (world/spawn_zones.sample_fleet) draws EXACTLY today's layout (1
    # carrier + n_destroyers GENERAL destroyers) and _spawn_ships builds
    # GeneralDestroyer hulls (numerically == the legacy Destroyer), so
    # sample_fleet's LOCKED tests, the duel, the smoke determinism check and the
    # default battle all replay bit-for-bit.  A non-zero count adds that class:
    #   n_flagship (0/1)   — the CEC datalink-hub command ship (cues the
    #                        escorts; its DEATH degrades the fleet, sensor-honest)
    #   n_aaw              — dedicated air-defense escorts (deep SM-2 + higher cap)
    #   n_ground_attack    — land-attack escorts (heavy TLAM bank, drains first)
    n_flagship: int = 0
    n_aaw: int = 0
    n_ground_attack: int = 0
    n_awacs: int = 1
    # M3-F2 EA-18G-class escort jammers. DEFAULT 0 so the out-of-the-box battle
    # stays BYTE-IDENTICAL (no jammer built -> _player_visible passes jammers=()
    # -> the EW field model is never consulted). A non-zero count spawns standoff
    # jammers that collapse the player radar via sim/ew.py.
    n_jammers: int = 0
    # M3-F4 player drone EW pod (self-protect / escort jammer). DEFAULT 0 (OFF)
    # so the out-of-the-box battle stays BYTE-IDENTICAL (no pod armed ->
    # _active_player_jammers() empty -> the enemy missile-detection calls get
    # jammers=() and the drone's own ELINT floor is unchanged). 1 arms the pod:
    # the player toggles it ON to collapse the ENEMY radar net so a salvo leaks,
    # at the cost of deafening the drone's own passive ELINT (going loud).
    player_jammer: int = 0
    n_enemy_radars: int = 2      # enemy coastal ground radars (Oniks targets, win condition)
    n_player_radars: int = 1
    n_pantsir: int = 2
    n_drones: int = 1
    n_oniks: int = 1             # Oniks TEL launchers, 2 tubes each (salvo fire)
    n_s300: int = 1              # S-300 TEL launchers, 4 tubes each (salvo fire)
    # Armory: magazine capacity + empty-refill reload per PLAYER weapon.
    oniks_ammo: int = 8
    oniks_mag_reload_s: float = 120.0
    zircon_ammo: int = 4         # scarce hypersonic anti-ship rounds (B selects)
    # M4-A Bastion-K quasi-ballistic top-attack ASBM pool. DEFAULT 0 (OFF) so
    # the out-of-the-box battle stays BYTE-IDENTICAL (no ASBM built -> the round
    # is never offered in the B cycle / HUD strip, and the world's _asbm_ammo
    # pool is 0 -> launch('asbm') returns None). A non-zero pool enables the
    # lofted anti-ship round (sim/asbm.py AsbmMissile) that overflies the SM-2
    # screen by altitude+speed and dives near-vertically onto a ship deck.
    asbm_ammo: int = 0
    # M2-T2 Kh-31P player anti-radiation pool. DEFAULT 0 so the out-of-the-box
    # battle stays BYTE-IDENTICAL (no ARM available until a setup screen arms
    # it); a non-zero pool enables launch_arm() against localized emitters.
    kh31p_ammo: int = 0
    s300_48n6_ammo: int = 4
    s300_40n6_ammo: int = 2
    s300_mag_reload_s: float = 45.0
    pantsir_57e6_ammo: int = 12
    pantsir_gun_ammo: int = 700
    pantsir_mag_reload_s: float = 60.0
    # M4-B loitering-munition swarm pod(s).  DEFAULT 0 (OFF) so the out-of-the-
    # box battle stays BYTE-IDENTICAL: with n_swarm_pods=0 the world builds NO
    # SwarmPod, _swarm_cells is 0, and launch_swarm returns None (never spawns a
    # round).  A non-zero count arms the bundle-launch saturation weapon
    # (sim/swarm.py + world.launch_swarm); each pod carries swarm_cells_per_pod
    # cells that refill on the swarm_mag_reload_s timer.
    n_swarm_pods: int = 0
    swarm_cells_per_pod: int = 8
    swarm_mag_reload_s: float = 90.0
    # M5 Buk mid-SAM TEL(s): a medium-range player SAM filling the
    # Pantsir(20km)<->S-300(150km) gap, carrying two rounds (9M317 long reach +
    # 9M338 agile).  DEFAULT 0 (OFF) so the out-of-the-box battle stays
    # BYTE-IDENTICAL: with n_buk=0 the world builds NO Buk battery, NO 9S36
    # radar joins radar_net, and launch_buk returns None (the round is never
    # offered; the buk platform is gated out of the TAB cycle).  A non-zero
    # count arms the battery (world._build_buk_battery + world.launch_buk); the
    # 9M317 / 9M338 pools refill on the buk_mag_reload_s timer.
    n_buk: int = 0
    buk_9m317_ammo: int = 6
    buk_9m338_ammo: int = 6
    buk_mag_reload_s: float = 45.0
    # M3-F4 seeded map preset (0 OPEN SEA / 1 ARCHIPELAGO / 2 NARROW STRAIT /
    # 3 FJORD COAST). DEFAULT 0 so the out-of-the-box battle map is
    # BYTE-IDENTICAL: world/generation.make_field(0, seed) returns the default
    # field (the seed is ignored for terrain on preset 0). Presets 1-3 build
    # seeded mid-ocean island terrain from np.random.default_rng([seed, 12]),
    # exercising the terrain-masking + radar-horizon physics; the home/enemy
    # coast cluster geometry stays stable across presets. Clamped to (0, 3).
    map_preset: int = 0
    # M5 submarine warfare + ASW acoustic domain.  ALL DEFAULT 0 (OFF) so the
    # out-of-the-box battle stays BYTE-IDENTICAL: with n_subs=0 the world builds
    # NO Submarine, self.subs is empty, _step_acoustic_sensors / sub stepping /
    # launch-datum injection are no-ops, victorious is unchanged (no subs to
    # require dead), and place_sonobuoy / launch_asw return None (no stock).
    #   n_subs            — enemy diesel SSK count (the second lose-path: each boat
    #                       creeps in, surfaces to fire a Kalibr salvo at the base,
    #                       runs deep; INVISIBLE to radar, killable only acoustically)
    #   sub_kalibr_ammo   — sub-launched 3M14 Kalibr-PL rounds PER boat
    #   n_sonobuoys       — player passive-sonobuoy stock (the primary ASW counter:
    #                       triangulate the boat via the acoustic solver)
    #   asw_ammo          — player ASW prosecution rounds (kill a localized boat)
    n_subs: int = 0
    sub_kalibr_ammo: int = 4
    n_sonobuoys: int = 0
    asw_ammo: int = 0
    # M5 #1 amphibious landing force + a TIMED beachhead lose-path.  DEFAULT 0
    # (OFF) so the out-of-the-box battle stays BYTE-IDENTICAL: with n_transports=0
    # NO Transport/LCAC is built, self.transports + self.lcacs are empty,
    # _step_amphibious is a pure no-op, and defeated trips ONLY on the bastion_tel
    # clause (the regression).  A non-zero count adds the SECOND lose-path: slow
    # Transport hulls (in self.ships -> count for victory) RUN to an offshore
    # launch line on the commander's sensor-only release, SPLASH fast LCAC craft,
    # and the LCACs sprint a coast LANDING_BOX; the FIRST LCAC to reach the box
    # starts the beachhead_grace_s clock — clear ALL committed craft before it
    # expires or defeated trips with cause 'beachhead'.
    #   n_transports      — enemy amphibious transport count (each splashes
    #                       LCAC_PER_TRANSPORT landing craft at its launch line)
    #   beachhead_grace_s — seconds to clear every committed craft once an LCAC
    #                       reaches the box (a POSITIVE default is safe at
    #                       n_transports=0: the timer only STARTS on a landing,
    #                       which cannot happen with no transports built)
    n_transports: int = 0
    beachhead_grace_s: float = 180.0


# --- Clamp ranges for the setup UI (module-level constants, not fields) -------
#     (min, max) inclusive
CLAMP_DESTROYERS:    tuple = (0, 12)
# M5 enemy ship classes: every floor is 0 (OFF) so the byte-identical default
# survives a clamp_config round-trip — the setup-default path runs every field
# through clamp_config; clamping any of these from 0 with a (1, ..) range would
# silently spawn the class and break the out-of-the-box battle.  The flagship is
# a 0/1 hull (one command ship); the escort classes scale like the destroyers.
CLAMP_FLAGSHIP:      tuple = (0, 1)
CLAMP_AAW:           tuple = (0, 12)
CLAMP_GROUND_ATTACK: tuple = (0, 12)
CLAMP_AWACS:         tuple = (0, 3)
# M3-F2 escort jammers: floor 0 (OFF default survives a clamp_config round-trip
# — like CLAMP_AWACS the setup-default path runs every field through clamp_config;
# clamping n_jammers=0 with a (1, ..) range would silently turn the corridor ON).
CLAMP_JAMMERS:       tuple = (0, 3)
# M3-F4 player EW pod: a 0/1 ARM flag, floor 0 (OFF default survives a
# clamp_config round-trip — the setup-default path runs every field through
# clamp_config; clamping player_jammer=0 with a (1, ..) range would silently
# arm the pod and break the byte-identical out-of-the-box battle).
CLAMP_PLAYER_JAMMER: tuple = (0, 1)
CLAMP_ENEMY_RADARS:  tuple = (0, 6)
CLAMP_PLAYER_RADARS: tuple = (1, 4)
CLAMP_PANTSIR:       tuple = (0, 6)
# M4-B swarm pods: floor 0 (OFF default survives a clamp_config round-trip —
# the setup-default path runs every field through clamp_config; clamping
# n_swarm_pods=0 with a (1, ..) range would silently arm the swarm and break
# the byte-identical out-of-the-box battle).
CLAMP_SWARM_PODS:    tuple = (0, 4)
# Cells per pod: at least 4 (a bundle that small could not saturate); ceiling
# 24 keeps a single SPACE bundle bounded.  Floor 4 is safe because the field is
# only read when n_swarm_pods > 0.
CLAMP_SWARM_CELLS:   tuple = (4, 24)
# M5 Buk mid-SAM TEL count: floor 0 (OFF default survives a clamp_config
# round-trip — the setup-default path runs every field through clamp_config;
# clamping n_buk=0 with a (1, ..) range would silently build the Buk and break
# the byte-identical out-of-the-box battle).  Ceiling 2 (a small medium-SAM
# battery, mirroring CLAMP_S300).
CLAMP_BUK:           tuple = (0, 2)
CLAMP_DRONES:        tuple = (0, 3)
CLAMP_ONIKS:         tuple = (1, 5)     # Oniks launchers (2 tubes each)
CLAMP_S300:          tuple = (1, 2)     # S-300 launchers (4 tubes each)
CLAMP_AMMO:          tuple = (1, 200)
# Pantsir 30 mm belt: a real 2A38M belt holds far more than a missile
# magazine, and the LOCKED schema default is 700 rounds — outside CLAMP_AMMO.
# Gun ammo therefore gets its own (1, 1000) range so the documented default
# survives a clamp_config() round-trip (the schema's pantsir_gun_ammo=700 and
# CLAMP_AMMO=(1,200) are otherwise mutually contradictory: clamping 700 with
# the missile range silently truncates the belt to 200).  Floor stays 1 so
# tests/test_combat_config.py::test_clamp_config_ammo_floor is unchanged.
CLAMP_GUN_AMMO:      tuple = (1, 1000)
# M2-T2 Kh-31P ARM pool: floor 0 (not 1) so the OFF default survives a
# clamp_config() round-trip. The setup-default path runs every field through
# clamp_config; clamping kh31p_ammo=0 with the missile CLAMP_AMMO=(1,200)
# would silently turn the ARM ON (1 round) and break the byte-identical
# out-of-the-box battle. Ceiling matches the other missile pools (200).
CLAMP_ARM_AMMO:      tuple = (0, 200)
# M4-A Bastion-K ASBM pool: floor 0 (not 1) so the OFF default survives a
# clamp_config() round-trip. The setup-default path runs every field through
# clamp_config; clamping asbm_ammo=0 with the missile CLAMP_AMMO=(1,200) would
# silently turn the ASBM ON (1 round) and break the byte-identical out-of-the-
# box battle. Ceiling matches the other missile pools (200).
CLAMP_ASBM_AMMO:     tuple = (0, 200)
CLAMP_RELOAD_S:      tuple = (5, 600)
# M3-F4 map preset: a cyclic enum index, floor 0 (OPEN SEA = the byte-identical
# default map survives a clamp_config round-trip — the setup-default path runs
# every field through clamp_config; clamping map_preset=0 with a (1, ..) range
# would silently swap the out-of-the-box battle to a terrain map). Ceiling 3
# (FJORD COAST) — exactly len(MAP_PRESET_NAMES) - 1.
CLAMP_MAP_PRESET:    tuple = (0, 3)

# M5 submarine warfare + ASW: every floor is 0 (OFF) so the byte-identical
# default survives a clamp_config round-trip — the setup-default path runs every
# field through clamp_config; clamping any of these from 0 with a (1, ..) range
# would silently spawn a boat / arm the ASW kit and break the out-of-the-box
# battle.  n_subs ceiling 3 (a small SSK threat, mirroring CLAMP_DRONES);
# sonobuoy stock + ASW ammo use the missile CLAMP_AMMO ceiling (200); the per-
# boat Kalibr pool floor is 0 too (a boat with 0 rounds simply never shoots).
CLAMP_SUBS:          tuple = (0, 3)
CLAMP_SONOBUOYS:     tuple = (0, 200)
CLAMP_ASW_AMMO:      tuple = (0, 200)
CLAMP_SUB_KALIBR:    tuple = (0, 200)

# M5 #1 amphibious landing: the transport count floor is 0 (OFF) so the byte-
# identical default survives a clamp_config round-trip — the setup-default path
# runs every field through clamp_config; clamping n_transports=0 with a (1, ..)
# range would silently build the landing force and break the out-of-the-box
# battle.  Ceiling 3 (a small amphibious group, mirroring CLAMP_SUBS).  The
# beachhead grace clamps with floor 0 (a positive default survives a round-trip;
# floor 0 keeps the schema default intact and never breaks the n_transports=0
# gate, which is geometric — the timer only starts on a landing) and a generous
# ceiling so a long grace is selectable.
CLAMP_TRANSPORTS:        tuple = (0, 3)
CLAMP_BEACHHEAD_GRACE:   tuple = (0.0, 600.0)

# M3-F4 display names, indexed by map_preset (0..3). One per CLAMP_MAP_PRESET
# value — the setup MAP row renders MAP_PRESET_NAMES[map_preset].
MAP_PRESET_NAMES:    tuple = ("OPEN SEA", "ARCHIPELAGO",
                              "NARROW STRAIT", "FJORD COAST")


def clamp_field(value, lo, hi):
    """Clamp a single UI value to [lo, hi]."""
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def clamp_config(
    *,
    seed: int = CombatConfig.seed,
    n_destroyers: int = CombatConfig.n_destroyers,
    n_flagship: int = CombatConfig.n_flagship,
    n_aaw: int = CombatConfig.n_aaw,
    n_ground_attack: int = CombatConfig.n_ground_attack,
    n_awacs: int = CombatConfig.n_awacs,
    n_jammers: int = CombatConfig.n_jammers,
    player_jammer: int = CombatConfig.player_jammer,
    n_enemy_radars: int = CombatConfig.n_enemy_radars,
    n_player_radars: int = CombatConfig.n_player_radars,
    n_pantsir: int = CombatConfig.n_pantsir,
    n_drones: int = CombatConfig.n_drones,
    n_oniks: int = CombatConfig.n_oniks,
    n_s300: int = CombatConfig.n_s300,
    oniks_ammo: int = CombatConfig.oniks_ammo,
    oniks_mag_reload_s: float = CombatConfig.oniks_mag_reload_s,
    zircon_ammo: int = CombatConfig.zircon_ammo,
    asbm_ammo: int = CombatConfig.asbm_ammo,
    kh31p_ammo: int = CombatConfig.kh31p_ammo,
    s300_48n6_ammo: int = CombatConfig.s300_48n6_ammo,
    s300_40n6_ammo: int = CombatConfig.s300_40n6_ammo,
    s300_mag_reload_s: float = CombatConfig.s300_mag_reload_s,
    pantsir_57e6_ammo: int = CombatConfig.pantsir_57e6_ammo,
    pantsir_gun_ammo: int = CombatConfig.pantsir_gun_ammo,
    pantsir_mag_reload_s: float = CombatConfig.pantsir_mag_reload_s,
    n_swarm_pods: int = CombatConfig.n_swarm_pods,
    swarm_cells_per_pod: int = CombatConfig.swarm_cells_per_pod,
    swarm_mag_reload_s: float = CombatConfig.swarm_mag_reload_s,
    n_buk: int = CombatConfig.n_buk,
    buk_9m317_ammo: int = CombatConfig.buk_9m317_ammo,
    buk_9m338_ammo: int = CombatConfig.buk_9m338_ammo,
    buk_mag_reload_s: float = CombatConfig.buk_mag_reload_s,
    map_preset: int = CombatConfig.map_preset,
    n_subs: int = CombatConfig.n_subs,
    sub_kalibr_ammo: int = CombatConfig.sub_kalibr_ammo,
    n_sonobuoys: int = CombatConfig.n_sonobuoys,
    asw_ammo: int = CombatConfig.asw_ammo,
    n_transports: int = CombatConfig.n_transports,
    beachhead_grace_s: float = CombatConfig.beachhead_grace_s,
) -> CombatConfig:
    """Build a CombatConfig with all count/ammo/reload fields clamped to the
    legal UI ranges.  Intended for the setup screen: pass raw slider values,
    get back a clean frozen config.  The seed is unclamped (any int is valid).
    """
    lo_d, hi_d = CLAMP_DESTROYERS
    lo_fs, hi_fs = CLAMP_FLAGSHIP
    lo_aaw, hi_aaw = CLAMP_AAW
    lo_ga, hi_ga = CLAMP_GROUND_ATTACK
    lo_aw, hi_aw = CLAMP_AWACS
    lo_jm, hi_jm = CLAMP_JAMMERS
    lo_pj, hi_pj = CLAMP_PLAYER_JAMMER
    lo_er, hi_er = CLAMP_ENEMY_RADARS
    lo_pr, hi_pr = CLAMP_PLAYER_RADARS
    lo_pa, hi_pa = CLAMP_PANTSIR
    lo_dr, hi_dr = CLAMP_DRONES
    lo_on, hi_on = CLAMP_ONIKS
    lo_s3, hi_s3 = CLAMP_S300
    lo_am, hi_am = CLAMP_AMMO
    lo_gun, hi_gun = CLAMP_GUN_AMMO
    lo_arm, hi_arm = CLAMP_ARM_AMMO
    lo_asbm, hi_asbm = CLAMP_ASBM_AMMO
    lo_re, hi_re = CLAMP_RELOAD_S
    lo_mp, hi_mp = CLAMP_MAP_PRESET
    lo_sp, hi_sp = CLAMP_SWARM_PODS
    lo_sc, hi_sc = CLAMP_SWARM_CELLS
    lo_bk, hi_bk = CLAMP_BUK
    lo_su, hi_su = CLAMP_SUBS
    lo_sb, hi_sb = CLAMP_SONOBUOYS
    lo_asw, hi_asw_ammo = CLAMP_ASW_AMMO
    lo_sk, hi_sk = CLAMP_SUB_KALIBR
    lo_tr, hi_tr = CLAMP_TRANSPORTS
    lo_bg, hi_bg = CLAMP_BEACHHEAD_GRACE

    return CombatConfig(
        seed=int(seed),
        n_destroyers=clamp_field(int(n_destroyers), lo_d, hi_d),
        n_flagship=clamp_field(int(n_flagship), lo_fs, hi_fs),
        n_aaw=clamp_field(int(n_aaw), lo_aaw, hi_aaw),
        n_ground_attack=clamp_field(int(n_ground_attack), lo_ga, hi_ga),
        n_awacs=clamp_field(int(n_awacs), lo_aw, hi_aw),
        n_jammers=clamp_field(int(n_jammers), lo_jm, hi_jm),
        player_jammer=clamp_field(int(player_jammer), lo_pj, hi_pj),
        n_enemy_radars=clamp_field(int(n_enemy_radars), lo_er, hi_er),
        n_player_radars=clamp_field(int(n_player_radars), lo_pr, hi_pr),
        n_pantsir=clamp_field(int(n_pantsir), lo_pa, hi_pa),
        n_drones=clamp_field(int(n_drones), lo_dr, hi_dr),
        n_oniks=clamp_field(int(n_oniks), lo_on, hi_on),
        n_s300=clamp_field(int(n_s300), lo_s3, hi_s3),
        oniks_ammo=clamp_field(int(oniks_ammo), lo_am, hi_am),
        zircon_ammo=clamp_field(int(zircon_ammo), lo_am, hi_am),
        asbm_ammo=clamp_field(int(asbm_ammo), lo_asbm, hi_asbm),
        kh31p_ammo=clamp_field(int(kh31p_ammo), lo_arm, hi_arm),
        oniks_mag_reload_s=clamp_field(float(oniks_mag_reload_s), lo_re, hi_re),
        s300_48n6_ammo=clamp_field(int(s300_48n6_ammo), lo_am, hi_am),
        s300_40n6_ammo=clamp_field(int(s300_40n6_ammo), lo_am, hi_am),
        s300_mag_reload_s=clamp_field(float(s300_mag_reload_s), lo_re, hi_re),
        pantsir_57e6_ammo=clamp_field(int(pantsir_57e6_ammo), lo_am, hi_am),
        pantsir_gun_ammo=clamp_field(int(pantsir_gun_ammo), lo_gun, hi_gun),
        pantsir_mag_reload_s=clamp_field(float(pantsir_mag_reload_s),
                                          lo_re, hi_re),
        n_swarm_pods=clamp_field(int(n_swarm_pods), lo_sp, hi_sp),
        swarm_cells_per_pod=clamp_field(int(swarm_cells_per_pod), lo_sc, hi_sc),
        swarm_mag_reload_s=clamp_field(float(swarm_mag_reload_s), lo_re, hi_re),
        n_buk=clamp_field(int(n_buk), lo_bk, hi_bk),
        buk_9m317_ammo=clamp_field(int(buk_9m317_ammo), lo_am, hi_am),
        buk_9m338_ammo=clamp_field(int(buk_9m338_ammo), lo_am, hi_am),
        buk_mag_reload_s=clamp_field(float(buk_mag_reload_s), lo_re, hi_re),
        map_preset=clamp_field(int(map_preset), lo_mp, hi_mp),
        n_subs=clamp_field(int(n_subs), lo_su, hi_su),
        sub_kalibr_ammo=clamp_field(int(sub_kalibr_ammo), lo_sk, hi_sk),
        n_sonobuoys=clamp_field(int(n_sonobuoys), lo_sb, hi_sb),
        asw_ammo=clamp_field(int(asw_ammo), lo_asw, hi_asw_ammo),
        n_transports=clamp_field(int(n_transports), lo_tr, hi_tr),
        beachhead_grace_s=clamp_field(float(beachhead_grace_s), lo_bg, hi_bg),
    )


# ------------------------------------------------------------------ default

DEFAULT = CombatConfig()
