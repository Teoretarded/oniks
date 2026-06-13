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
    n_awacs: int = 1
    n_enemy_radars: int = 2      # enemy coastal ground radars (Oniks targets, win condition)
    n_player_radars: int = 1
    n_pantsir: int = 2
    n_drones: int = 1
    # Armory: magazine capacity + empty-refill reload per PLAYER weapon.
    oniks_ammo: int = 8
    oniks_mag_reload_s: float = 120.0
    s300_48n6_ammo: int = 4
    s300_40n6_ammo: int = 2
    s300_mag_reload_s: float = 45.0
    pantsir_57e6_ammo: int = 12
    pantsir_gun_ammo: int = 700
    pantsir_mag_reload_s: float = 60.0


# --- Clamp ranges for the setup UI (module-level constants, not fields) -------
#     (min, max) inclusive
CLAMP_DESTROYERS:    tuple = (0, 12)
CLAMP_AWACS:         tuple = (0, 3)
CLAMP_ENEMY_RADARS:  tuple = (0, 6)
CLAMP_PLAYER_RADARS: tuple = (1, 4)
CLAMP_PANTSIR:       tuple = (0, 6)
CLAMP_DRONES:        tuple = (0, 3)
CLAMP_AMMO:          tuple = (1, 200)
# Pantsir 30 mm belt: a real 2A38M belt holds far more than a missile
# magazine, and the LOCKED schema default is 700 rounds — outside CLAMP_AMMO.
# Gun ammo therefore gets its own (1, 1000) range so the documented default
# survives a clamp_config() round-trip (the schema's pantsir_gun_ammo=700 and
# CLAMP_AMMO=(1,200) are otherwise mutually contradictory: clamping 700 with
# the missile range silently truncates the belt to 200).  Floor stays 1 so
# tests/test_combat_config.py::test_clamp_config_ammo_floor is unchanged.
CLAMP_GUN_AMMO:      tuple = (1, 1000)
CLAMP_RELOAD_S:      tuple = (5, 600)


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
    n_awacs: int = CombatConfig.n_awacs,
    n_enemy_radars: int = CombatConfig.n_enemy_radars,
    n_player_radars: int = CombatConfig.n_player_radars,
    n_pantsir: int = CombatConfig.n_pantsir,
    n_drones: int = CombatConfig.n_drones,
    oniks_ammo: int = CombatConfig.oniks_ammo,
    oniks_mag_reload_s: float = CombatConfig.oniks_mag_reload_s,
    s300_48n6_ammo: int = CombatConfig.s300_48n6_ammo,
    s300_40n6_ammo: int = CombatConfig.s300_40n6_ammo,
    s300_mag_reload_s: float = CombatConfig.s300_mag_reload_s,
    pantsir_57e6_ammo: int = CombatConfig.pantsir_57e6_ammo,
    pantsir_gun_ammo: int = CombatConfig.pantsir_gun_ammo,
    pantsir_mag_reload_s: float = CombatConfig.pantsir_mag_reload_s,
) -> CombatConfig:
    """Build a CombatConfig with all count/ammo/reload fields clamped to the
    legal UI ranges.  Intended for the setup screen: pass raw slider values,
    get back a clean frozen config.  The seed is unclamped (any int is valid).
    """
    lo_d, hi_d = CLAMP_DESTROYERS
    lo_aw, hi_aw = CLAMP_AWACS
    lo_er, hi_er = CLAMP_ENEMY_RADARS
    lo_pr, hi_pr = CLAMP_PLAYER_RADARS
    lo_pa, hi_pa = CLAMP_PANTSIR
    lo_dr, hi_dr = CLAMP_DRONES
    lo_am, hi_am = CLAMP_AMMO
    lo_gun, hi_gun = CLAMP_GUN_AMMO
    lo_re, hi_re = CLAMP_RELOAD_S

    return CombatConfig(
        seed=int(seed),
        n_destroyers=clamp_field(int(n_destroyers), lo_d, hi_d),
        n_awacs=clamp_field(int(n_awacs), lo_aw, hi_aw),
        n_enemy_radars=clamp_field(int(n_enemy_radars), lo_er, hi_er),
        n_player_radars=clamp_field(int(n_player_radars), lo_pr, hi_pr),
        n_pantsir=clamp_field(int(n_pantsir), lo_pa, hi_pa),
        n_drones=clamp_field(int(n_drones), lo_dr, hi_dr),
        oniks_ammo=clamp_field(int(oniks_ammo), lo_am, hi_am),
        oniks_mag_reload_s=clamp_field(float(oniks_mag_reload_s), lo_re, hi_re),
        s300_48n6_ammo=clamp_field(int(s300_48n6_ammo), lo_am, hi_am),
        s300_40n6_ammo=clamp_field(int(s300_40n6_ammo), lo_am, hi_am),
        s300_mag_reload_s=clamp_field(float(s300_mag_reload_s), lo_re, hi_re),
        pantsir_57e6_ammo=clamp_field(int(pantsir_57e6_ammo), lo_am, hi_am),
        pantsir_gun_ammo=clamp_field(int(pantsir_gun_ammo), lo_gun, hi_gun),
        pantsir_mag_reload_s=clamp_field(float(pantsir_mag_reload_s),
                                          lo_re, hi_re),
    )


# ------------------------------------------------------------------ default

DEFAULT = CombatConfig()
