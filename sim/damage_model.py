"""Subsystem damage model (pure numpy, GL-free, ZERO RNG).

The 2026-07-06 approved revamp (docs/superpowers/specs/
2026-07-06-subsystem-damage-design.md): a hit ship stops being a flat hp
counter and becomes a hull with real internal modules, flooding
compartments, a crew that fights back, and an ammunition magazine that can
cook off.  Everything is deterministic — hit location from OBB-entry
geometry, damage magnitudes from kinetic energy and warhead mass, DoT from
fixed-rate integrators.  NO probability rolls anywhere (physics-not-dice).

Normative sources (constants cite these, do not re-derive from vibes):
  docs/research/warship_internal_layouts_2026-07-06.md   (module grids, DC)
  docs/research/magazine_detonation_energetics_2026-07-06.md (cook-off)

LOCKED conventions:
  * Ship-local frame == Ship.obb(): +Z bow, +Y up, +X starboard.  Grid rows
    use the research doc's units — z0/z1 as LENGTH FRACTIONS stern(0)->bow(1),
    y0/y1 vs the WATERLINE where y<0 scales by the hull's draft (y=-1 keel)
    and y>=0 scales by ship.height/Y_TOP_FRAC (y=Y_TOP_FRAC masthead), x as
    half-beam fractions. Seven-field rows are centered on x=0; optional
    eight-field rows add x_center before x_half for asymmetric modules.
  * This module is consulted ONLY when the world runs
    damage_model == "subsystem" (world/combat_config.py).  The legacy
    hp -= 1 path in sim/damage.py is byte-identical when it is off.
  * Sinking reuses the existing ship state ladder (ST_SINKING drives the
    list/sink animation unchanged).  While the subsystem model manages a
    ship it keeps ship.burn_timer refreshed so the legacy 45 s burn->sink
    clock NEVER fires — flooding/cook-off/gutting decide, not the timer.
  * All mutable per-ship damage state lives in one DamageState object at
    ship._dmg (created lazily on the first subsystem-mode hit), and is
    hashed into the replay digest by game/blackbox.state_digest when the
    mode is on (digest_floats()).
"""

from __future__ import annotations

import math

import numpy as np

from sim.ships import (BURN_TIME, HULL_DRAFT, ST_ALIVE, ST_BURNING,
                       ST_SINKING)

_EPS = 1e-12

# --- Grid vertical convention -------------------------------------------------
# Research grids give y as: -1.0 = keel (== ship draft), 0 = waterline,
# +Y_TOP_FRAC = masthead (== ship.height above the waterline).
Y_TOP_FRAC = 1.4

# --- Impact channels ------------------------------------------------------------
# Structural channel: KE of the WHOLE round (live mass x terminal speed^2 / 2 —
# the HMS Sheffield lever; sim/missile.py Missile.mass is launch mass minus
# burned fuel).  KE opens hull breaches; the breach area drives flooding.
# A 3000 kg Oniks at ~680 m/s carries ~6.9e8 J; a Zircon at ~1500 m/s ~4x more.
SKIN_KE_J = 2.0e6          # penetration gate (research: 1-3e6 J band); below
                           # this the round shreds surface fittings only
SAP_HARDNESS_MIN = 0.5     # nose_hardness below this = frag/blast head (ARM
                           # class): it never holes the hull no matter the KE
KE_PER_BREACH_M2 = 1.5e8   # J of KE per m^2 of below-waterline breach area
                           # (calibrated F2-P4: Oniks ~4.6 m^2 — inside the
                           # research's 1-12 m^2 SAP band; Sheffield's actual
                           # hole was 1.2 x 3 m from a smaller Exocet)
BREACH_M2_MAX = 14.0       # cap: a hit never opens more than a Cole-scale hole
BREACH_ADJ_M2 = 6.0        # breach area that also opens ONE adjacent
BREACH_ADJ2_M2 = 12.0      # ... and BOTH adjacent flooding compartments
ABOVE_WL_BREACH_FRAC = 0.25  # deck/superstructure penetrations still open a
                             # reduced waterline-adjacent breach (blast vents
                             # downward through decks — Sheffield flooded too)

# Blast/frag channel: module knockout dose in kg of warhead mass delivered
# along the interior path.  A module dies when its accumulated dose crosses
# its toughness (deterministic, cumulative).
BLAST_RUN_FRAC = 0.10      # SAP interior travel before/while detonating, as a
                           # fraction of ship length (research: 1-3 bulkheads)
FRAG_MARGIN = 0.06         # non-penetrator frag reach, normalized grid units
TOUGHNESS = {              # kg of delivered warhead dose to kill the module
    "sensors": 40.0,       # antenna faces/mast — a 66 kg frag ARM shreds them
    "c2": 60.0,
    "vls": 80.0,
    "magazine": 90.0,
    "propulsion": 100.0,   # a turbine room needs a real warhead
    "aviation": 60.0,
    "fire": 50.0,          # fuel spaces: 'killing' them = rupturing them
    "flotation": 1.0e9,    # flooding is handled by breaches, not doses
}

# --- Flooding / damage control (research doc: DC constants section) -----------
# A compartment fills in tens of seconds through a serious breach (McCain:
# <60 s); portable pumps lose ~10:1 to a big hole and win only once the crew
# has sealed it down.  Modelled per flooded compartment as
#   d(level)/dt = K_FILL * breach_area - PUMP_RATE      (level in 0..1)
# with the breach area itself decaying as the crew plugs/boundaries it.
K_FILL = 0.0056            # (fraction/s)/m^2: a 4 m^2 hole fills a DDG
                           # compartment in ~45 s (McCain datum)
PUMP_RATE = 0.0012         # fraction/s a compartment's pumps remove (~10:1
                           # against a fresh multi-m^2 breach, decisive after
                           # sealing — Cole's 96 h DC fight)
SEAL_RATE = 0.004          # 1/s exponential breach-area decay (plugs,
                           # shoring, boundary-setting)
FLOODED_LEVEL = 0.85       # a compartment counts as LOST at this fill level
N_COMPARTMENTS = 6         # longitudinal watertight bins per warship hull
SINK_FLOODED = {           # bins lost => ST_SINKING.  Research: design std is
    "warship": 3,          # "somewhat greater than two machinery spaces" for
    "merchant": 2,         # small DDs — 3 of 6 game bins is HALF the hull,
}                          # already generous vs Fitzgerald's 3-of-~13.
MERCHANT_COMPARTMENTS = 3

# --- Fire / crew suppression (energetics doc + Sheffield/Stark anchors) --------
# dI/dt = FIRE_GROWTH*I*(1-I) - FIRE_SUPPRESS*(1 + t_fire/SUPPRESS_RAMP_S)
# Logistic growth against a crew effort that RAMPS as damage-control parties
# muster (deterministic, no dice).  Consequences, all emergent:
#   * a 66-87 kg ARM fire (I0~0.2) dies immediately — Stark-class save;
#   * a 250 kg Oniks internal fire (I0~0.6) burns hard for minutes, then the
#     ramped effort beats it UNLESS it reached a fuel space (+0.25) — only
#     fires that start >= COOK_I can dwell a magazine to cook-off;
#   * stacked hits stack ignition — the second missile finishes the job.
FIRE_GROWTH = 0.02         # 1/s logistic growth of an established fire
FIRE_SUPPRESS = 0.003      # 1/s initial crew suppression effort
SUPPRESS_RAMP_S = 300.0    # effort doubles every this many seconds of fire
IGNITE_PER_KG = 1.0 / 450.0  # ignition intensity per kg of warhead mass.
                           # Calibrated (probe_damage_matrix): a bare 300 kg
                           # Zircon fire (0.67) stays under COOK_I — only a
                           # fuel-fed (+0.25) or stacked fire can dwell a
                           # magazine to cook-off, per the approved ladder.
FIRE_OUT_I = 0.02          # below this the fire is out (state back to ALIVE)
GUT_FIRE_S = 600.0         # integral intensity-seconds that gut the ship
                           # (Sheffield: burned out -> lost); reachable only
                           # by re-fed / stacked fires, not one contained one

# --- Magazine cook-off (energetics doc, all deterministic) ---------------------
COOK_I = 0.75              # sustained fire intensity that heats a magazine
COOK_DWELL_S = 90.0        # ...for this long => cook-off (Forrestal M117 datum)
COOK_Z_REACH = 0.18        # fire reaches a magazine within this z-fraction
SM2_NEQ_TNT_KG = 22.0      # per-round warhead NEQ, kg TNT-eq  [energetics doc]
PROP_TNT_KG = 33.0         # per-round propellant contribution when a round
                           # deflagrates in the chain (250 kg * k~0.13)
C_SYM_VLS = 0.15           # vented Mk 41: only this fraction detonates
                           # sympathetically; the rest root-sums (doc formula)
COOK_SINK_TNT_KG = 120.0   # blast >= this breaks the hull outright (Moskva
                           # class outcome); below it = massive fire + breach
TNT_J = 4.184e6            # J per kg TNT


def cookoff_tnt_kg(n_rounds: int) -> float:
    """Deterministic magazine-event yield (kg TNT-eq) for n live rounds.
    Energetics doc: W(n) = NEQ_total * (c_sym*n + (1-c_sym)*sqrt(n))."""
    n = max(0, int(n_rounds))
    if n == 0:
        return 0.0
    per = SM2_NEQ_TNT_KG + PROP_TNT_KG
    return per * (C_SYM_VLS * n + (1.0 - C_SYM_VLS) * math.sqrt(n))


def fireball_radius_m(w_tnt_kg: float) -> float:
    """Hopkinson-Cranz cube-root fireball radius (visuals/forensics only)."""
    return 3.5 * max(0.0, w_tnt_kg) ** (1.0 / 3.0)


# --- Module grids ---------------------------------------------------------------
# Legacy row: (name, z0, z1, y0, y1, x_half, effect_kind)
# Offset row: (name, z0, z1, y0, y1, x_center, x_half, effect_kind)
# x_center/x_half are fractions of HALF the ship beam. Keeping the original
# seven-field form valid avoids invalidating existing research grids while
# allowing real off-centre structures such as a carrier island.
BURKE_GRID = [
    # Rebuilt mesh: aft field centred at z=-27 m, forward at z=+40 m.
    ("vls_aft_64",    0.305, 0.347, 0.24, 0.29, 0.55, "vls"),
    ("vls_fwd_32",    0.737, 0.779, 0.24, 0.29, 0.30, "vls"),
    ("mer2_port",     0.30, 0.42, -1.00, 0.00, 0.60, "propulsion"),
    ("aux2",          0.42, 0.48, -0.90, -0.20, 0.50, "propulsion"),
    ("mer1_stbd",     0.48, 0.58, -1.00, 0.00, 0.60, "propulsion"),
    ("aux1_gtg",      0.58, 0.63, -0.90, -0.20, 0.50, "propulsion"),
    # Four SPY faces sit at z=2.7/17.3 m and x=+-7.3 m on the rebuilt house.
    # The broad symmetric boxes cover each port/starboard pair; the narrow
    # mast remains a separate high sensor volume at z=14 m.
    ("spy_fwd",       0.594, 0.629, 0.35, 0.53, 1.00, "sensors"),
    ("spy_aft",       0.500, 0.535, 0.35, 0.53, 1.00, "sensors"),
    ("mast",          0.58, 0.61, 0.83, 1.40, 0.45, "sensors"),
    ("bridge",        0.60, 0.66, 0.49, 0.76, 0.72, "c2"),
    ("cic",           0.50, 0.64, 0.05, 0.50, 0.70, "c2"),
    ("hangar",        0.18, 0.30, 0.10, 0.45, 0.50, "aviation"),
    ("fuel_f76",      0.25, 0.65, -1.00, -0.30, 0.90, "fire"),
]

TICO_GRID = [
    # Rebuilt Ticonderoga mesh: VLS fields at z=-50/+53.5 m on the 6.7 m
    # weather deck. The damage frame's +28 m top makes that y=.33-.34.
    ("vls_aft_61",    0.190, 0.232, 0.30, 0.37, 0.45, "vls"),
    ("vls_fwd_61",    0.789, 0.830, 0.30, 0.37, 0.45, "vls"),
    ("er_aft",        0.34, 0.46, -1.00, 0.00, 0.60, "propulsion"),
    ("er_fwd",        0.52, 0.64, -1.00, 0.00, 0.60, "propulsion"),
    ("spy_fwd",       0.630, 0.660, 0.49, 0.70, 0.90, "sensors"),
    ("spy_aft",       0.340, 0.370, 0.46, 0.68, 0.90, "sensors"),
    ("bridge",        0.578, 0.734, 0.32, 0.86, 0.82, "c2"),
    ("mast_fwd",      0.578, 0.607, 0.79, 1.40, 0.55, "sensors"),
    ("mast_aft",      0.345, 0.376, 0.75, 1.27, 0.60, "sensors"),
    ("hangar",        0.268, 0.408, 0.32, 0.83, 0.82, "aviation"),
    ("fuel",          0.30, 0.66, -1.00, -0.30, 0.90, "fire"),
]

NIMITZ_GRID = [
    ("reactors",      0.40, 0.60, -1.00, -0.40, 0.40, "propulsion"),
    ("jp5_fuel",      0.35, 0.65, -1.00, -0.50, 0.60, "fire"),
    # Grid z=0 is stern and z=1 is bow; the former labels were reversed.
    ("magazine_aft",  0.30, 0.45, -0.90, -0.40, 0.40, "magazine"),
    ("magazine_fwd",  0.65, 0.75, -0.90, -0.40, 0.40, "magazine"),
    ("hangar",        0.15, 0.75, 0.00, 0.24, 0.80, "aviation"),
    # Rebuilt island: x=+27.5 m starboard on a 40 m waterline beam and
    # z=-1..+29 m. x_center exceeds 1 because the flight deck overhangs hull.
    ("island",        0.497, 0.587, 0.24, 1.40, 1.375, 0.40, "c2"),
    ("machinery",     0.20, 0.45, -1.00, -0.30, 0.70, "propulsion"),
]

CARGO_GRID = [
    ("engine_room",   0.05, 0.20, -1.00, -0.10, 0.60, "propulsion"),
    ("bridge_accom",  0.025, 0.105, 0.28, 0.95, 0.86, "c2"),
    ("cargo_holds",   0.17, 0.80, -0.70, 0.28, 0.90, "fire"),
]

TANKER_GRID = [
    ("engine_room",    0.02, 0.14, -1.00, -0.10, 0.62, "propulsion"),
    ("bridge_accom",   0.025, 0.090, 0.28, 0.95, 0.80, "c2"),
    ("cargo_tanks",    0.16, 0.88, -0.90, 0.25, 0.92, "fire"),
    ("cargo_manifold", 0.47, 0.55, 0.12, 0.42, 0.82, "fire"),
]

WARSHIP_GRID = [
    ("frigate_engine_aft", 0.28, 0.42, -1.00, -0.05, 0.62, "propulsion"),
    ("frigate_engine_fwd", 0.42, 0.54, -1.00, -0.05, 0.62, "propulsion"),
    ("frigate_vls_32",     0.737, 0.783, 0.28, 0.40, 0.42, "vls"),
    ("frigate_bridge",     0.61, 0.70, 0.45, 0.85, 0.58, "c2"),
    ("frigate_mast",       0.53, 0.62, 0.72, 1.40, 0.38, "sensors"),
    ("frigate_hangar",     0.20, 0.38, 0.20, 0.55, 0.72, "aviation"),
    ("frigate_fuel",       0.22, 0.66, -1.00, -0.30, 0.85, "fire"),
]

TRANSPORT_GRID = [
    ("transport_engine", 0.05, 0.20, -1.00, -0.08, 0.65, "propulsion"),
    ("well_deck",        0.00, 0.16, -0.35, 0.25, 0.62, "aviation"),
    ("transport_hangar", 0.25, 0.47, 0.18, 0.58, 0.78, "aviation"),
    ("transport_bridge", 0.63, 0.79, 0.50, 0.92, 0.68, "c2"),
    ("transport_masts",  0.49, 0.69, 0.78, 1.40, 0.32, "sensors"),
    ("transport_fuel",   0.20, 0.65, -1.00, -0.30, 0.84, "fire"),
]

LCAC_GRID = [
    # Machinery sponsons and the control cabin are genuinely offset from the
    # centre cargo lane; these exercise the eight-field asymmetric row form.
    ("lcac_engine_port", 0.14, 0.82, 0.12, 0.88, -0.72, 0.18, "propulsion"),
    ("lcac_engine_stbd", 0.14, 0.82, 0.12, 0.88, 0.72, 0.18, "propulsion"),
    ("lcac_cabin",       0.61, 0.81, 0.46, 1.25, 0.69, 0.22, "c2"),
    ("lcac_cushion",     0.01, 0.99, -1.00, 0.26, 1.00, "flotation"),
]

MERCHANT_GRID = [
    ("engine_room",   0.05, 0.20, -1.00, -0.10, 0.60, "propulsion"),
    ("bridge_accom",  0.05, 0.18, 0.40, 1.00, 0.50, "c2"),
]

GRID_BY_TYPE = {
    "destroyer": BURKE_GRID,
    "aaw_destroyer": BURKE_GRID,
    "ground_attack_destroyer": BURKE_GRID,
    "flagship": TICO_GRID,
    "carrier": NIMITZ_GRID,
    "cargo": CARGO_GRID,
    "tanker": TANKER_GRID,
    "warship": WARSHIP_GRID,
    "transport": TRANSPORT_GRID,
    "lcac": LCAC_GRID,
}

# Grid presence no longer implies a naval damage-control standard: merchants
# and the LCAC have distinct grids but retain the lighter flooding model.
WARSHIP_TYPES = {
    "destroyer", "aaw_destroyer", "ground_attack_destroyer", "flagship",
    "carrier", "warship", "transport",
}

# Fraction of the SM-2/SM-6/TLAM pools stored in each VLS module (Burke:
# 32-cell fwd / 64-cell aft; Tico symmetric 61/61).
VLS_POOL_FRAC = {
    "vls_fwd_32": 1.0 / 3.0, "vls_aft_64": 2.0 / 3.0,
    "vls_fwd_61": 0.5, "vls_aft_61": 0.5,
    "magazine_fwd": 0.5, "magazine_aft": 0.5,
}

# Propulsion knockout: speed multiplier applied ONCE when the module dies.
# Main engine rooms bite hard; auxiliaries less.  Both MERs dead => dead in
# the water (handled explicitly in _apply_module_kill).
PROP_SPEED_MULT = {
    "mer2_port": 0.5, "mer1_stbd": 0.5, "aux2": 0.8, "aux1_gtg": 0.8,
    "er_aft": 0.5, "er_fwd": 0.5, "reactors": 0.3, "machinery": 0.6,
    "engine_room": 0.0,          # a merchant's single plant: dead in water
    "frigate_engine_aft": 0.5, "frigate_engine_fwd": 0.5,
    "transport_engine": 0.0,
    "lcac_engine_port": 0.5, "lcac_engine_stbd": 0.5,
}
_MAIN_ENGINE_PAIRS = (
    frozenset(("mer2_port", "mer1_stbd")),
    frozenset(("er_aft", "er_fwd")),
    frozenset(("frigate_engine_aft", "frigate_engine_fwd")),
    frozenset(("lcac_engine_port", "lcac_engine_stbd")),
)


def grid_for(ship) -> list:
    return GRID_BY_TYPE.get(getattr(ship, "ship_type", ""), MERCHANT_GRID)


def _is_warship(ship) -> bool:
    return getattr(ship, "ship_type", "") in WARSHIP_TYPES


# --- Geometry -------------------------------------------------------------------

def _ship_draft(ship) -> float:
    """Positive per-hull draft, with the historical global as fallback."""
    draft = float(getattr(ship, "draft", HULL_DRAFT))
    return draft if np.isfinite(draft) and draft > 0.0 else HULL_DRAFT


def _ship_damage_height(ship) -> float:
    """Waterline-to-grid-top height, independent of broad collision height."""
    height = float(getattr(ship, "damage_height", ship.height))
    return height if np.isfinite(height) and height > 0.0 else float(ship.height)


def _damage_obb(ship):
    """Return the stable subsystem-local frame for a ship.

    New ship implementations expose ``damage_obb``. The fallback preserves
    older test doubles/integration objects which only provide ``obb``.
    """
    damage_obb = getattr(ship, "damage_obb", None)
    return damage_obb() if damage_obb is not None else ship.obb()


def _row_parts(row) -> tuple:
    """Normalize legacy/offset module rows to an eight-value tuple.

    Returned order is ``name,z0,z1,y0,y1,x_center,x_half,effect_kind``.
    """
    if len(row) == 7:
        name, z0, z1, y0, y1, x_half, kind = row
        return name, z0, z1, y0, y1, 0.0, x_half, kind
    if len(row) == 8:
        return tuple(row)
    raise ValueError(f"module grid row must have 7 or 8 fields, got {len(row)}")


def _hitcam_row(row) -> tuple:
    """Seven-field projection for the existing symmetric hitcam renderer.

    Simulation geometry keeps the true lateral offset.  The renderer predates
    offset rows, so its symmetric plan-view envelope conservatively covers the
    module until the presentation layer gains x-center support of its own.
    """
    name, z0, z1, y0, y1, x_center, x_half, kind = _row_parts(row)
    return name, z0, z1, y0, y1, abs(x_center) + x_half, kind


def segment_obb_entry(p0, p1, center, half, rot3x3):
    """Entry point of segment p0->p1 into the OBB, or None.

    Same slab test as sim/damage.segment_hits_obb but returns
    (t_enter, q_entry) where q_entry is the entry point in the box's LOCAL
    frame (meters).  t_enter is 0.0 for a segment starting inside."""
    q0 = rot3x3.T @ (np.asarray(p0, dtype=np.float64) - center)
    q1 = rot3x3.T @ (np.asarray(p1, dtype=np.float64) - center)
    d = q1 - q0
    t_enter, t_exit = 0.0, 1.0
    for i in range(3):
        if abs(d[i]) < _EPS:
            if abs(q0[i]) > half[i]:
                return None
        else:
            ta = (-half[i] - q0[i]) / d[i]
            tb = (half[i] - q0[i]) / d[i]
            if ta > tb:
                ta, tb = tb, ta
            t_enter = max(t_enter, ta)
            t_exit = min(t_exit, tb)
            if t_enter > t_exit:
                return None
    return t_enter, q0 + d * t_enter


def local_to_grid(ship, q_local) -> tuple:
    """OBB-local meters -> (z_frac stern->bow, y_grid, x_frac half-beam).

    y_grid follows the research convention: negative = fraction of
    the ship's draft below the waterline, positive = fraction of
    the ship's damage-grid height/Y_TOP_FRAC above it."""
    draft = _ship_draft(ship)
    damage_height = _ship_damage_height(ship)
    half_len = ship.length * 0.5
    z_frac = (float(q_local[2]) + half_len) / ship.length
    # The damage frame's local y=0 sits (height - draft)/2 above waterline.
    y_wl_m = float(q_local[1]) + (damage_height - draft) * 0.5
    if y_wl_m < 0.0:
        y_grid = y_wl_m / draft
    else:
        y_grid = y_wl_m * Y_TOP_FRAC / damage_height
    x_frac = float(q_local[0]) / (ship.beam * 0.5)
    return z_frac, y_grid, x_frac


def _box_contains(row, z, y, x, margin=0.0) -> bool:
    _n, z0, z1, y0, y1, xc, xh, _k = _row_parts(row)
    return (z0 - margin <= z <= z1 + margin
            and y0 - margin <= y <= y1 + margin
            and abs(x - xc) <= xh + margin)


PATH_STEP_M = 2.0          # interior damage-path sample spacing (meters)
BLAST_RADIUS_K = 1.8       # m per kg^(1/3) of warhead: lethal module-damage
                           # reach around the detonation path (cube-root
                           # blast scaling — Oniks 250 kg -> ~11 m, Zircon
                           # 300 kg -> ~12 m, HARM 87 kg -> ~8 m).  Tuning
                           # latitude lives HERE, never in the tests.
FRAG_CONTACT_M = 4.0       # m: a frag head detonates on the first structure
                           # within this reach of its chord


def _grid_y_to_m(ship, y_grid: float) -> float:
    """Grid vertical (research convention) -> waterline-relative meters."""
    if y_grid < 0.0:
        return y_grid * _ship_draft(ship)
    return y_grid * _ship_damage_height(ship) / Y_TOP_FRAC


def _box_local_m(ship, row):
    """A grid row's box as (center, half) in OBB-LOCAL meters."""
    _n, z0, z1, y0, y1, xc, xh, _k = _row_parts(row)
    draft = _ship_draft(ship)
    damage_height = _ship_damage_height(ship)
    half_len = ship.length * 0.5
    za = z0 * ship.length - half_len
    zb = z1 * ship.length - half_len
    ya = _grid_y_to_m(ship, y0)
    yb = _grid_y_to_m(ship, min(y1, Y_TOP_FRAC))
    off = (damage_height - draft) * 0.5   # waterline in damage-frame local y
    x_center = xc * ship.beam * 0.5
    x_half = xh * ship.beam * 0.5
    center = np.array([x_center, (ya + yb) * 0.5 - off,
                       (za + zb) * 0.5])
    half = np.array([x_half, (yb - ya) * 0.5, (zb - za) * 0.5])
    return center, half


def _clearance_m(p, center, half) -> float:
    """Euclidean distance from point ``p`` to the box surface (0 inside)."""
    d = np.abs(p - center) - half
    d = np.maximum(d, 0.0)
    return float(np.sqrt(d @ d))


def _walk_path(ship, grid, q_entry, v_local, run_m, blast_r_m, first_only):
    """The interior damage path, in LOCAL METERS with a real blast reach.

    Walk the straight line from the OBB entry point along the round's local
    velocity, sampling every PATH_STEP_M.  A module is damaged when the
    path passes within ``blast_r_m`` of its box (cube-root blast scaling —
    a warhead does not need to thread the box exactly).  ``first_only``
    models a frag head: it detonates at the first structure met and reaches
    nothing beyond it.  Returns (hit_rows, q_detonation, min_y_wl_m):
    the modules damaged, the LOCAL detonation point (end of the SAP run /
    the frag contact), and the lowest waterline-relative height the path
    reached (a diving round that crosses below the waterline floods as a
    BELOW-waterline breach no matter where it entered).  Deterministic and
    direction-agnostic."""
    draft = _ship_draft(ship)
    damage_height = _ship_damage_height(ship)
    n = np.linalg.norm(v_local)
    if n < _EPS:
        return [], q_entry, float(q_entry[1] + (damage_height - draft)
                                  * 0.5)
    d = v_local / n
    boxes = [(row, *_box_local_m(ship, row)) for row in grid]
    off = (damage_height - draft) * 0.5
    half_len = ship.length * 0.5
    hit, seen = [], {}
    q_det = q_entry.copy()
    min_y_wl = float(q_entry[1] + off)
    steps = max(1, int(run_m / PATH_STEP_M))
    for i in range(steps + 1):
        q = q_entry + d * (i * PATH_STEP_M)
        if abs(q[2]) > half_len + 2.0 or q[1] + off < -draft - 2.0:
            break                        # left the hull (length or keel)
        q_det = q
        min_y_wl = min(min_y_wl, float(q[1] + off))
        for row, center, half in boxes:
            clear = _clearance_m(q, center, half)
            if clear <= blast_r_m:
                # inside=True only when the round's PATH pierces the box
                # itself (clearance 0) — the sympathetic-detonation worst
                # case; a blast-radius graze doses the module but cannot
                # set the whole magazine off at once.
                inside = clear <= 1e-9
                idx = seen.get(row[0])
                if idx is None:
                    seen[row[0]] = len(hit)
                    hit.append((row, inside))
                    if first_only:
                        return hit, q, min_y_wl
                elif inside and not hit[idx][1]:
                    hit[idx] = (row, True)
    return hit, q_det, min_y_wl


# --- Per-ship damage state -------------------------------------------------------

class DamageState:
    """All mutable subsystem-damage state for one hull.  Created lazily by
    ensure_state() on the first subsystem-mode hit; stepped by step_ships().
    Deterministic: plain float64 scalars, no RNG, no wall clock."""

    def __init__(self, ship):
        self.warship = _is_warship(ship)
        n = N_COMPARTMENTS if self.warship else MERCHANT_COMPARTMENTS
        self.n_comp = n
        self.flood = [0.0] * n          # fill level 0..1 per z-bin
        self.breach = [0.0] * n         # open breach area m^2 per z-bin
        self.fire = 0.0                 # ship-wide fire intensity 0..1
        self.fire_z = 0.5               # z-fraction of the burning region
        self.fire_time = 0.0            # s this fire has burned (DC ramp)
        self.fire_integral = 0.0        # gutting clock (s of intensity)
        self.cook_dwell = 0.0           # s of fire >= COOK_I near live ammo
        self.module_dose = {}           # module name -> accumulated kg
        self.dead_modules = set()       # module names knocked out
        self.cooked_off = False
        self.sink_flooded = (SINK_FLOODED["warship"] if self.warship
                             else SINK_FLOODED["merchant"])

    # -- digest support (game/blackbox.state_digest, subsystem mode only) --
    def digest_floats(self):
        out = list(self.flood) + list(self.breach)
        out += [self.fire, self.fire_z, self.fire_time,
                self.fire_integral, self.cook_dwell,
                float(len(self.dead_modules)), float(self.cooked_off)]
        # Dose map in sorted-name order so iteration is deterministic.
        for name in sorted(self.module_dose):
            out.append(self.module_dose[name])
        return out

    def flooded_count(self) -> int:
        return sum(1 for f in self.flood if f >= FLOODED_LEVEL)

    def comp_of(self, z_frac: float) -> int:
        return min(self.n_comp - 1, max(0, int(z_frac * self.n_comp)))


def ensure_state(ship) -> DamageState:
    st = getattr(ship, "_dmg", None)
    if st is None:
        st = DamageState(ship)
        ship._dmg = st
    return st


# --- Hit resolution ---------------------------------------------------------------

def _round_mass_kg(m) -> float:
    """Live total mass of the round (energy model), with fallbacks for
    rounds that predate it: launch mass, else 4x warhead, else 500 kg."""
    mass = getattr(m, "mass", None)
    if mass is not None and np.isfinite(mass) and mass > 0.0:
        return float(mass)
    w = getattr(m, "weapon", None)
    lm = getattr(w, "launch_mass", None) if w is not None else None
    if lm:
        return float(lm)
    wh = getattr(w, "warhead_mass", 0.0) if w is not None else 0.0
    return float(wh) * 4.0 if wh else 500.0


def _warhead_kg(m) -> float:
    w = getattr(m, "weapon", None)
    return float(getattr(w, "warhead_mass", 0.0) or 0.0) if w is not None \
        else 0.0


def _apply_module_kill(ship, st: DamageState, name: str, kind: str,
                       effects_out) -> None:
    """A module crossed its toughness: write the knockout into state the
    REST OF THE SIM ALREADY READS (fog-honest AI reacts for free)."""
    if name in st.dead_modules:
        return
    st.dead_modules.add(name)
    if kind == "sensors":
        radar = getattr(ship, "radar", None)
        if radar is not None:
            # All three sensor boxes must die to fully blind the ship only
            # for the mast-and-faces Burke; one SPY face bank down already
            # blinds (functional radar model has no sectors) — the FIRST
            # sensors kill flips it, matching the ARM precedent.
            radar.alive = False
    elif kind == "vls" or kind == "magazine":
        frac_lost = VLS_POOL_FRAC.get(name, 0.5)
        for attr in ("sm2_ammo", "sm6_ammo", "tomahawk_ammo"):
            cur = getattr(ship, attr, None)
            if cur:
                setattr(ship, attr, int(round(cur * (1.0 - frac_lost))))
    elif kind == "propulsion":
        mult = PROP_SPEED_MULT.get(name, 0.6)
        ship.speed = float(ship.speed) * mult
        # A paired plant is dead in the water only when both halves are gone.
        if any(name in pair and pair <= st.dead_modules
               for pair in _MAIN_ENGINE_PAIRS):
            ship.speed = 0.0
    elif kind == "c2":
        cap = getattr(ship, "sm2_max_inflight", None)
        if cap is not None:
            ship.sm2_max_inflight = max(1, int(cap) // 2)
        tf = getattr(ship, "_track_form_s", None)
        if tf is not None:
            ship._track_form_s = float(tf) * 2.0
    # "fire" (fuel space rupture) has no discrete write: the ignition bonus
    # is applied by the caller; "aviation" is cosmetic until fighters rearm
    # is modelled per-hangar.


def _magazine_ammo(ship, name: str) -> int:
    """Live rounds attributable to a magazine module (drives cook-off)."""
    frac = VLS_POOL_FRAC.get(name, 0.5)
    total = 0
    for attr in ("sm2_ammo", "sm6_ammo", "tomahawk_ammo"):
        total += int(getattr(ship, attr, 0) or 0)
    return int(round(total * frac))


def _catastrophe(ship, st: DamageState, effects_out, pos) -> None:
    """Magazine detonation: hull-breaking blast (Moskva/Hood outcome)."""
    st.cooked_off = True
    for i in range(st.n_comp):
        st.breach[i] = max(st.breach[i], BREACH_M2_MAX)
        st.flood[i] = max(st.flood[i], FLOODED_LEVEL)
    ship.state = ST_SINKING
    effects_out.append(("ship_hit", np.asarray(pos, dtype=np.float64).copy()))
    effects_out.append(("magazine_detonation",
                        np.asarray(pos, dtype=np.float64).copy()))


def resolve_hit(ship, m, impact_world, effects_out, *, entry_world=None) -> None:
    """Apply one missile impact under the subsystem model.

    Caller (sim/damage.py) has already: passed the OBB test, killed the
    round, stamped forensics.  This function only damages the ship."""
    st = ensure_state(ship)
    center, half, rot = _damage_obb(ship)
    if entry_world is not None:
        # sim.damage already selected the earliest entry across every actual
        # compound collision volume. Convert that world point into the stable
        # damage frame; do not try the broad hull again (deck/island/mast-only
        # impacts may never intersect it).
        q_local = rot.T @ (
            np.asarray(entry_world, dtype=np.float64) - center)
    else:
        entry = segment_obb_entry(m.prev_pos, m.pos, center, half, rot)
        if entry is None:                # numerical edge / legacy direct call
            q_local = rot.T @ (np.asarray(impact_world, dtype=np.float64)
                               - center)
        else:
            q_local = entry[1]
    z, y, x = local_to_grid(ship, q_local)
    z = min(1.0, max(0.0, z))

    speed = float(np.linalg.norm(m.vel))
    ke = 0.5 * _round_mass_kg(m) * speed * speed
    warhead = _warhead_kg(m)
    hardness = float(getattr(getattr(m, "weapon", None),
                             "nose_hardness", 1.0) or 1.0)
    # A frag/blast head (ARM class) never holes the hull regardless of KE;
    # a SAP nose needs real kinetic energy (gates out drone-class rounds).
    penetrates = hardness >= SAP_HARDNESS_MIN and ke >= SKIN_KE_J

    # Forensics stamps (WRITE-ONLY, the sim never reads them).
    m.impact_ke = ke
    m.impact_u = (z, y, x)

    grid = grid_for(ship)
    v_local = rot.T @ np.asarray(m.vel, dtype=np.float64)
    blast_r = BLAST_RADIUS_K * warhead ** (1.0 / 3.0) if warhead > 0.0 \
        else 1.0
    if penetrates:
        # SAP interior run: the round keeps punching through structure for
        # a fraction of the ship's length; everything within the blast
        # radius of that path takes the warhead dose.
        hit_modules, q_det, min_y_wl = _walk_path(
            ship, grid, q_local, v_local,
            run_m=BLAST_RUN_FRAC * ship.length + blast_r,
            blast_r_m=blast_r, first_only=False)
    else:
        # Frag head: crosses open air/deck and detonates on the FIRST
        # structure met anywhere along its chord through the hull box.
        hit_modules, q_det, min_y_wl = _walk_path(
            ship, grid, q_local, v_local,
            run_m=ship.length + ship.beam,
            blast_r_m=FRAG_CONTACT_M, first_only=True)

    # Blast/frag channel: full warhead dose to every module on the path
    # (deterministic and cumulative — two ARMs finish what one started).
    ignition_bonus = 0.0
    dead_before = set(st.dead_modules)
    catastrophe = False
    for row, inside in hit_modules:
        name, *_unused, kind = _row_parts(row)
        dose = st.module_dose.get(name, 0.0) + warhead
        st.module_dose[name] = dose
        if kind == "fire":
            ignition_bonus += 0.25      # ruptured fuel space feeds the fire
        if dose >= TOUGHNESS.get(kind, 1.0e9):
            if kind in ("vls", "magazine") and penetrates and inside:
                # A penetrating warhead bursting INSIDE a live magazine is
                # the sympathetic-chain worst case: instant cook-off, no
                # dwell.  (A blast-radius graze only wrecks the cells.)
                n = _magazine_ammo(ship, name)
                _apply_module_kill(ship, st, name, kind, effects_out)
                if n > 0 and cookoff_tnt_kg(n) >= COOK_SINK_TNT_KG:
                    _catastrophe(ship, st, effects_out, impact_world)
                    catastrophe = True
                    break
                st.fire = min(1.0, st.fire + 0.5)   # deflagration fire
                st.fire_z = z
            else:
                _apply_module_kill(ship, st, name, kind, effects_out)

    # Structural channel: KE opens a breach at the DETONATION point.  A
    # path that reached the waterline or below (a sea-skimmer through the
    # side OR a diver punching down through the decks) breaches at full
    # effect; a burst that stayed wholly above it opens a reduced breach
    # (blast vents down through decks — Sheffield took water too).
    z_det, _y_det, _x_det = local_to_grid(ship, q_det)
    z_det = min(1.0, max(0.0, z_det))
    breach_area = 0.0
    if penetrates and not catastrophe:
        breach_area = min(BREACH_M2_MAX, ke / KE_PER_BREACH_M2)
        if min_y_wl >= 0.0:
            breach_area *= ABOVE_WL_BREACH_FRAC
        ci = st.comp_of(z_det)
        st.breach[ci] += breach_area
        if breach_area >= BREACH_ADJ_M2 and ci + 1 < st.n_comp:
            st.breach[ci + 1] += breach_area * 0.4
        if breach_area >= BREACH_ADJ2_M2 and ci - 1 >= 0:
            st.breach[ci - 1] += breach_area * 0.4

        # Internal detonation starts a fire scaled by the warhead
        # (energetics doc: internal fire is the decisive kill mechanism).
        st.fire = min(1.0, st.fire + warhead * IGNITE_PER_KG + ignition_bonus)
        st.fire_z = z_det                # the fire burns where it BURST
    elif not catastrophe:
        # Frag hit: surface fire only if it found something flammable.
        if ignition_bonus > 0.0:
            st.fire = min(1.0, st.fire + ignition_bonus)
            st.fire_z = z_det

    if st.fire > FIRE_OUT_I and ship.state == ST_ALIVE and not catastrophe:
        ship.state = ST_BURNING
        ship.burn_timer = BURN_TIME     # visual ladder; step_ships refreshes

    # X-RAY HIT-CAM snapshot (WRITE-ONLY: the render layer reads it off the
    # dead round like the forensics stamps; NO sim code ever does — the
    # digest contract is untouched).
    grid = grid_for(ship)
    hitcam_grid = [_hitcam_row(row) for row in grid]
    m.hitcam = {
        "ship_type": getattr(ship, "ship_type", "ship"),
        "grid": hitcam_grid,
        "kinds": {row[0]: _row_parts(row)[-1] for row in grid},
        "dose": dict(st.module_dose),
        "toughness": {
            row[0]: TOUGHNESS.get(_row_parts(row)[-1], 1.0e9)
            for row in grid
        },
        "new_dead": sorted(st.dead_modules - dead_before),
        "all_dead": sorted(st.dead_modules),
        "flood": list(st.flood),
        "fire": st.fire, "fire_z": st.fire_z,
        "impact": (z, y, x), "ke": ke, "penetrated": penetrates,
        # Shot-path drawing (hit cam v2): entry + detonation points in grid
        # coords, and the blast reach as a length fraction.
        "entry": (z, y, x),
        "det": local_to_grid(ship, q_det),
        "blast_frac": blast_r / ship.length,
        "breach_m2": breach_area,
        "weapon": str(getattr(getattr(m, "weapon", None), "weapon_id",
                              "round")),
        "catastrophe": catastrophe,
        "dead_in_water": float(getattr(ship, "speed", 1.0)) == 0.0,
    }


# --- Per-step dynamics -------------------------------------------------------------

def step_ships(ships, dt: float, effects_out) -> None:
    """Integrate flooding / fire / crew action for every managed hull.
    Called once per fixed world substep when damage_model == 'subsystem'."""
    for ship in ships:
        st = getattr(ship, "_dmg", None)
        if st is None or ship.state not in (ST_ALIVE, ST_BURNING):
            continue
        _step_one(ship, st, dt, effects_out)


def _step_one(ship, st: DamageState, dt: float, effects_out) -> None:
    # -- flooding vs pumps, per compartment --
    for i in range(st.n_comp):
        b = st.breach[i]
        if b > 0.0:
            st.breach[i] = b * math.exp(-SEAL_RATE * dt)   # crew seals
        level = st.flood[i]
        if b > 0.0 or level > 0.0:
            level += (K_FILL * b - PUMP_RATE) * dt
            st.flood[i] = min(1.0, max(0.0, level))

    # -- fire: logistic growth vs a ramping crew effort --
    if st.fire > 0.0:
        st.fire_time += dt
        f = st.fire
        suppress = FIRE_SUPPRESS * (1.0 + st.fire_time / SUPPRESS_RAMP_S)
        f += (FIRE_GROWTH * f * (1.0 - f) - suppress) * dt
        st.fire = min(1.0, max(0.0, f))
        st.fire_integral += st.fire * dt
        if st.fire <= FIRE_OUT_I:
            st.fire = 0.0
            st.fire_time = 0.0          # DC parties stand down
            if ship.state == ST_BURNING:
                ship.state = ST_ALIVE   # fire contained (Stark outcome)

    # Keep the legacy burn clock from ever expiring while we manage the hull
    # (the 45 s auto-sink is the LEGACY ladder; here flooding decides).
    if ship.state == ST_BURNING:
        ship.burn_timer = BURN_TIME

    # -- magazine cook-off from sustained fire --
    if st.fire >= COOK_I and not st.cooked_off:
        near = None
        for row in grid_for(ship):
            kind = _row_parts(row)[-1]
            if kind in ("vls", "magazine") \
                    and row[0] not in st.dead_modules:
                z0, z1 = row[1], row[2]
                if z0 - COOK_Z_REACH <= st.fire_z <= z1 + COOK_Z_REACH:
                    near = row
                    break
        if near is not None:
            st.cook_dwell += dt
            if st.cook_dwell >= COOK_DWELL_S:
                n = _magazine_ammo(ship, near[0])
                _apply_module_kill(
                    ship, st, near[0], _row_parts(near)[-1], effects_out)
                if n > 0 and cookoff_tnt_kg(n) >= COOK_SINK_TNT_KG:
                    _catastrophe(ship, st, effects_out, ship.pos)
                    return
                st.fire = 1.0           # deflagration feeds the blaze
        else:
            st.cook_dwell = 0.0
    else:
        st.cook_dwell = 0.0

    # -- loss conditions --
    if st.flooded_count() >= st.sink_flooded:
        ship.state = ST_SINKING         # existing list/sink animation
    elif st.fire_integral >= GUT_FIRE_S:
        ship.state = ST_SINKING         # gutted hulk (Sheffield outcome)
