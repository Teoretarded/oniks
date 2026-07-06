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
    y0/y1 vs the WATERLINE where y<0 scales by HULL_DRAFT (y=-1 keel) and
    y>=0 scales by ship.height/Y_TOP_FRAC (y=Y_TOP_FRAC masthead), x as a
    half-beam fraction.
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
# Research grids give y as: -1.0 = keel (== -HULL_DRAFT), 0 = waterline,
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


# --- Module grids (research doc RECOMMENDED GRID, transcribed verbatim) --------
# Row: (name, z0, z1, y0, y1, x_half, effect_kind)
BURKE_GRID = [
    ("vls_aft_64",    0.60, 0.70, -0.15, 0.15, 0.35, "vls"),
    ("vls_fwd_32",    0.72, 0.80, -0.15, 0.15, 0.30, "vls"),
    ("mer2_port",     0.30, 0.42, -1.00, 0.00, 0.60, "propulsion"),
    ("aux2",          0.42, 0.48, -0.90, -0.20, 0.50, "propulsion"),
    ("mer1_stbd",     0.48, 0.58, -1.00, 0.00, 0.60, "propulsion"),
    ("aux1_gtg",      0.58, 0.63, -0.90, -0.20, 0.50, "propulsion"),
    ("spy_fwd",       0.68, 0.74, 0.50, 0.90, 0.50, "sensors"),
    ("spy_aft",       0.55, 0.60, 0.60, 1.00, 0.50, "sensors"),
    ("mast",          0.60, 0.66, 0.90, 1.40, 0.15, "sensors"),
    ("bridge",        0.70, 0.75, 0.55, 0.75, 0.30, "c2"),
    ("cic",           0.66, 0.74, 0.05, 0.30, 0.40, "c2"),
    ("hangar",        0.18, 0.30, 0.10, 0.45, 0.50, "aviation"),
    ("fuel_f76",      0.25, 0.65, -1.00, -0.30, 0.90, "fire"),
]

TICO_GRID = [
    ("vls_aft_61",    0.20, 0.30, -0.15, 0.15, 0.35, "vls"),
    ("vls_fwd_61",    0.72, 0.82, -0.15, 0.15, 0.35, "vls"),
    ("er_aft",        0.34, 0.46, -1.00, 0.00, 0.60, "propulsion"),
    ("er_fwd",        0.52, 0.64, -1.00, 0.00, 0.60, "propulsion"),
    ("spy_fwd",       0.66, 0.72, 0.50, 0.90, 0.50, "sensors"),
    ("spy_aft",       0.28, 0.34, 0.50, 0.90, 0.50, "sensors"),
    ("bridge",        0.68, 0.74, 0.55, 0.80, 0.30, "c2"),
    ("fuel",          0.30, 0.66, -1.00, -0.30, 0.90, "fire"),
]

NIMITZ_GRID = [
    ("reactors",      0.40, 0.60, -1.00, -0.40, 0.40, "propulsion"),
    ("jp5_fuel",      0.35, 0.65, -1.00, -0.50, 0.60, "fire"),
    ("magazine_fwd",  0.30, 0.45, -0.90, -0.40, 0.40, "magazine"),
    ("magazine_aft",  0.65, 0.75, -0.90, -0.40, 0.40, "magazine"),
    ("hangar",        0.15, 0.75, 0.15, 0.45, 0.80, "aviation"),
    ("island",        0.52, 0.62, 0.45, 1.00, 0.60, "c2"),
    ("machinery",     0.20, 0.45, -1.00, -0.30, 0.70, "propulsion"),
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
    # merchants (cargo/tanker/warship-lane/transport) fall back to
    # MERCHANT_GRID in grid_for().
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
}
_MAIN_ENGINES = {"mer2_port", "mer1_stbd", "er_aft", "er_fwd"}


def grid_for(ship) -> list:
    return GRID_BY_TYPE.get(getattr(ship, "ship_type", ""), MERCHANT_GRID)


def _is_warship(ship) -> bool:
    return getattr(ship, "ship_type", "") in GRID_BY_TYPE


# --- Geometry -------------------------------------------------------------------

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
    HULL_DRAFT below the waterline, positive = fraction of
    ship.height/Y_TOP_FRAC above it."""
    half_len = ship.length * 0.5
    z_frac = (float(q_local[2]) + half_len) / ship.length
    # The OBB's local y=0 sits (height - draft)/2 ABOVE the waterline.
    y_wl_m = float(q_local[1]) + (ship.height - HULL_DRAFT) * 0.5
    if y_wl_m < 0.0:
        y_grid = y_wl_m / HULL_DRAFT
    else:
        y_grid = y_wl_m * Y_TOP_FRAC / ship.height
    x_frac = float(q_local[0]) / (ship.beam * 0.5)
    return z_frac, y_grid, x_frac


def _box_contains(row, z, y, x, margin=0.0) -> bool:
    _n, z0, z1, y0, y1, xh, _k = row
    return (z0 - margin <= z <= z1 + margin
            and y0 - margin <= y <= y1 + margin
            and abs(x) <= xh + margin)


PATH_STEP_M = 2.0          # interior damage-path sample spacing (meters)


def _path_modules(ship, grid, q_entry, v_local, run_m, first_only,
                  margin) -> list:
    """Module boxes met along the interior damage path.

    Walk the LOCAL-frame straight line from the OBB entry point along the
    round's local velocity direction, ``run_m`` meters, sampling every
    PATH_STEP_M; each sample converts to grid coords (z-frac, y-grid,
    x-frac) and tests point-in-box.  ``first_only`` models a frag head that
    detonates on the FIRST structure met (it crosses open deck air until
    then); a SAP head keeps punching and doses EVERY box on the run.
    Deterministic, direction-agnostic (beam-on, bow-on and diving hits all
    walk their true path)."""
    n = np.linalg.norm(v_local)
    if n < _EPS:
        return []
    d = v_local / n
    hit, seen = [], set()
    steps = max(1, int(run_m / PATH_STEP_M))
    for i in range(steps + 1):
        q = q_entry + d * (i * PATH_STEP_M)
        z, y, x = local_to_grid(ship, q)
        if not (-0.02 <= z <= 1.02):
            break                        # left the hull lengthwise
        for row in grid:
            if row[0] in seen:
                continue
            if _box_contains(row, z, y, x, margin=margin):
                seen.add(row[0])
                hit.append(row)
                if first_only:
                    return hit
    return hit


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
        # Every hull in the grids carries exactly TWO main plants (Burke
        # MER1/MER2, Tico ER fwd/aft) — both dead means dead in the water.
        if name in _MAIN_ENGINES \
                and len(st.dead_modules & _MAIN_ENGINES) >= 2:
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


def resolve_hit(ship, m, impact_world, effects_out) -> None:
    """Apply one missile impact under the subsystem model.

    Caller (sim/damage.py) has already: passed the OBB test, killed the
    round, stamped forensics.  This function only damages the ship."""
    st = ensure_state(ship)
    center, half, rot = ship.obb()
    entry = segment_obb_entry(m.prev_pos, m.pos, center, half, rot)
    if entry is None:                    # numerical edge: fall back to the
        q_local = rot.T @ (np.asarray(impact_world, dtype=np.float64)
                           - center)    # midpoint the caller already has
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
    if penetrates:
        # SAP interior run: the round keeps punching through structure for
        # a fraction of the ship's length past the entry point.
        hit_modules = _path_modules(ship, grid, q_local, v_local,
                                    run_m=BLAST_RUN_FRAC * ship.length,
                                    first_only=False, margin=0.02)
    else:
        # Frag head: crosses open air/deck and detonates on the FIRST
        # structure met anywhere along its chord through the hull box.
        hit_modules = _path_modules(ship, grid, q_local, v_local,
                                    run_m=ship.length + ship.beam,
                                    first_only=True, margin=FRAG_MARGIN)

    # Blast/frag channel: full warhead dose to every module on the path
    # (deterministic and cumulative — two ARMs finish what one started).
    ignition_bonus = 0.0
    for row in hit_modules:
        name, kind = row[0], row[6]
        dose = st.module_dose.get(name, 0.0) + warhead
        st.module_dose[name] = dose
        if kind == "fire":
            ignition_bonus += 0.25      # ruptured fuel space feeds the fire
        if dose >= TOUGHNESS.get(kind, 1.0e9):
            if kind in ("vls", "magazine") and penetrates:
                # A penetrating warhead INSIDE a live magazine is the
                # sympathetic-chain worst case: instant cook-off, no dwell.
                n = _magazine_ammo(ship, name)
                _apply_module_kill(ship, st, name, kind, effects_out)
                if n > 0 and cookoff_tnt_kg(n) >= COOK_SINK_TNT_KG:
                    _catastrophe(ship, st, effects_out, impact_world)
                    return
                st.fire = min(1.0, st.fire + 0.5)   # deflagration fire
                st.fire_z = z
            else:
                _apply_module_kill(ship, st, name, kind, effects_out)

    # Structural channel: KE opens a breach.  Below-waterline entries breach
    # at full effect; internal detonations above the WL still open a reduced
    # breach (blast vents through decks/hull — Sheffield took water too).
    if penetrates:
        area = min(BREACH_M2_MAX, ke / KE_PER_BREACH_M2)
        if y >= 0.0:
            area *= ABOVE_WL_BREACH_FRAC
        ci = st.comp_of(z)
        st.breach[ci] += area
        if area >= BREACH_ADJ_M2 and ci + 1 < st.n_comp:
            st.breach[ci + 1] += area * 0.4
        if area >= BREACH_ADJ2_M2 and ci - 1 >= 0:
            st.breach[ci - 1] += area * 0.4

        # Internal detonation starts a fire scaled by the warhead
        # (energetics doc: internal fire is the decisive kill mechanism).
        st.fire = min(1.0, st.fire + warhead * IGNITE_PER_KG + ignition_bonus)
        st.fire_z = z
    else:
        # Frag hit: surface fire only if it found something flammable.
        if ignition_bonus > 0.0:
            st.fire = min(1.0, st.fire + ignition_bonus)
            st.fire_z = z

    if st.fire > FIRE_OUT_I and ship.state == ST_ALIVE:
        ship.state = ST_BURNING
        ship.burn_timer = BURN_TIME     # visual ladder; step_ships refreshes


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
            if row[6] in ("vls", "magazine") and row[0] not in st.dead_modules:
                z0, z1 = row[1], row[2]
                if z0 - COOK_Z_REACH <= st.fire_z <= z1 + COOK_Z_REACH:
                    near = row
                    break
        if near is not None:
            st.cook_dwell += dt
            if st.cook_dwell >= COOK_DWELL_S:
                n = _magazine_ammo(ship, near[0])
                _apply_module_kill(ship, st, near[0], near[6], effects_out)
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
